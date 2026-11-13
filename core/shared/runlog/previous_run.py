#!/usr/bin/env python3
"""CF-0781: what a batch re-run (`batch_control rerun-from`) left on disk from
the run before it - so that a reader can tell the re-run's output from the
previous run's.

`rerun-from` keeps the files the reset stages wrote (`kept`: the re-run
overwrites them) and moves only the files a `stage-start` guard reads
(CF-0776). Three readers still took a kept file for the re-run's own:

* the executor's `output_check` (CF-0730) counted an LLM stage done because
  its `produces` file was on disk - the previous run's 04/05/06;
* the stop-cock (CF-0322) and `run_checks reserve-refill` read
  `01b -> reserve_substitution` written by the previous run's reserve loop;

So `rerun-from` records, in its `manual_resets` row of `run-state.json`, a
fingerprint of each kept file and of each block it knows a reset stage wrote
into an earlier stage's file:

    "previous_run": {"files":  {"<rel path>": "<sha256 of the bytes>"},
                     "blocks": {"<rel path>#<key>": "<sha256 of the block>"}}

A file (block) whose fingerprint is still the one recorded by the latest reset
that names it is the previous run's; anything the re-run writes differs.

Why a content hash and not the file's mtime against the stage's start: an
mtime moves under a copy (`cp`, `rsync` without `-t`, a restore from the
archive) and tells nothing about who wrote the bytes, and comparing it with a
start time also leans on two clocks agreeing. The hash is explicit: it is the
previous run's bytes, written down at the moment of the reset. The one case it
reads wrong - a re-run that writes byte-for-byte the same file - does not
happen to the files in question (they carry their own run's times and ids),
and it would fail loud (`stage_left_no_output`), never pass silent.

CF-0784: `rerun-from` no longer records `blocks` - it moves the previous run's
entries out of the block into `before-rerun-<ts>/` (`batch_control.STALE_BLOCKS`),
so every reader, the agents' included, reads what stays as the earlier stage's
own. The `blocks` of rows written before that are still honoured here.

Stdlib only; pure but for reading the batch's own files.
"""
import hashlib
import json
from pathlib import Path

__all__ = ["TASK", "STATE_FILE", "RESETS_KEY", "ROW_KEY", "file_sha", "block_sha",
           "block_ref", "read_state", "recorded", "is_previous_file", "is_previous_block"]

TASK = "CF-0781"
STATE_FILE = "run-state.json"       # run_executor.STATE_FILE
RESETS_KEY = "manual_resets"        # batch_control.rerun_from's rows
ROW_KEY = "previous_run"            # the row's record of what stayed on disk


def file_sha(path):
    """sha256 of the file's bytes, or None when it cannot be read."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def block_sha(block):
    """sha256 of a JSON value, independent of the file's layout and key order."""
    text = json.dumps(block, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def block_ref(rel, key):
    return f"{rel}#{key}"


def read_state(batch):
    """The batch's `run-state.json` as a dict, or None."""
    if batch is None:
        return None
    try:
        doc = json.loads((Path(batch) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def recorded(state):
    """`(files, blocks)` - for each path (block ref) the fingerprint the latest
    reset that named it recorded."""
    files, blocks = {}, {}
    for row in (state or {}).get(RESETS_KEY) or []:
        rec = row.get(ROW_KEY) if isinstance(row, dict) else None
        if not isinstance(rec, dict):
            continue
        files.update({k: v for k, v in (rec.get("files") or {}).items() if isinstance(v, str)})
        blocks.update({k: v for k, v in (rec.get("blocks") or {}).items() if isinstance(v, str)})
    return files, blocks


def is_previous_file(batch, rel, state=None):
    """True when `<batch>/<rel>` is the previous run's file: a reset recorded
    it and its bytes have not changed since."""
    files, _ = recorded(state if state is not None else read_state(batch))
    want = files.get(str(rel))
    return bool(want) and file_sha(Path(batch) / rel) == want


def is_previous_block(state, rel, key, block):
    """True when `block` (the value of `key` in `rel`) is the one the latest
    reset recorded - written by the run before the re-run."""
    if block is None:
        return False
    _, blocks = recorded(state)
    want = blocks.get(block_ref(rel, key))
    return bool(want) and block_sha(block) == want

#!/usr/bin/env python3
"""CF-0713: what an LLM stage changed in the factory's tracked code.

Batch example-science/2026-10-12T2001Z: the footage-indexer stage (`claude -p`
with Edit/Write) hit a thread race in `agents/footage-indexer/scripts/
source_rights.py`, added a lock to it - uncommitted, on an agent pinned at
`v2.3` - and finished the batch on code that is not the code its `code_shas`
name. The stage's prompt now forbids it (run_executor.CODE_RULE_LINES); this
module is the mechanical half: the executor takes a `snapshot()` of every repo
before an LLM stage and another after it, and `compare()` names what the stage
changed.

What counts is exactly what `runlog batch-start` refuses (CF-0479), read with
runlog's own functions so that the two can never disagree:

* a modified or staged **tracked** file (`git status --porcelain
  --untracked-files=no`) of the root or of any `agents/<name>` repo. Untracked
  and ignored files never count - the batch directory, the footage pool
  (`shared/footage/`), caches and logs are the stage's data. The root's
  records (`runlog.NON_CODE_PATHS`: `pipeline/`, `tasks/`, `publish/`,
  `rotation/ledger/`, `analytics/` - a Studio read from the center that lands
  during a stage is not the stage's edit, CF-0895 - docs) are not code either: a tracked record a step
  writes and commits itself (commit-records, the rights-check sync of CF-0704
  are machine stages and are not checked at all) is never flagged;
* a file that was already dirty before the stage counts only when its bytes
  changed during it (a digest per dirty path);
* a commit made during the stage: a move of a repo's HEAD that touches code
  (`runlog.code_moved`, CF-0479/CF-0685 - a root commit of records alone is
  not one).

Never raises: a repo whose `git status` fails is left out of the snapshot,
and a snapshot that cannot be taken at all is `{}` (nothing compared).
Stdlib only.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = "CF-0713"
EVENT_KIND = "stage_code_edit"
# The rule's mode until a price is signed (CF-0320): a stage that changed
# tracked code is recorded loudly, never failed - "a refusal without a price
# stands as a warning". `fail` is the mode a signature would move it to.
MODE = "warn"


def _runlog():
    d = str(HERE / "runlog")
    if d not in sys.path:
        sys.path.insert(0, d)
    import runlog  # noqa: PLC0415
    return runlog


def _digest(repo_dir, rel):
    try:
        return hashlib.sha1((Path(repo_dir) / rel).read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return "deleted"
    except OSError:
        return "unreadable"


def snapshot(root):
    """{label: {"head": sha, "dirty": {path: digest}}} of every git repo of the
    factory (the root, every `agents/<name>`). Non-git directories and repos
    whose status cannot be read are left out."""
    try:
        rl = _runlog()
        out = {}
        for label, d in rl.factory_repos(root):
            st = rl.repo_state(label, d)
            if not st.get("git") or st.get("dirty") is None:
                continue
            out[label] = {"head": st.get("head"),
                          "dirty": {p: _digest(d, p) for p in st["dirty"]}}
        return out
    except Exception:                                   # noqa: BLE001
        return {}


def compare(before, after, root, channel=None):
    """[{repo, files, head_was, head_now}] - per repo, the tracked files the
    stage made dirty or changed again, and the HEAD move when it touches code.
    [] when nothing of the code moved."""
    out = []
    try:
        rl = _runlog()
        dirs = dict(rl.factory_repos(root))
    except Exception:                                   # noqa: BLE001
        return out
    for label, now in sorted((after or {}).items()):
        was = (before or {}).get(label)
        if was is None:
            continue                                    # a repo the before-snapshot did not see
        files = sorted(p for p, dg in (now.get("dirty") or {}).items()
                       if (was.get("dirty") or {}).get(p) != dg)
        head_was, head_now = was.get("head"), now.get("head")
        moved = False
        if head_was and head_now and head_was != head_now:
            try:
                moved = rl.code_moved(label, head_was, head_now, dirs.get(label, root),
                                      channel=channel)
            except Exception:                           # noqa: BLE001
                moved = True
        if files or moved:
            row = {"repo": label, "files": files}
            if moved:
                row.update(head_was=head_was, head_now=head_now)
            out.append(row)
    return out


def describe(edits, limit=6):
    """One line: `agents/footage-indexer: scripts/source_rights.py; root: ...`."""
    parts = []
    for e in edits or []:
        files = list(e.get("files") or [])
        shown = ", ".join(files[:limit]) + (f" (+{len(files) - limit})" if len(files) > limit else "")
        if e.get("head_now"):
            commit = f"HEAD {str(e.get('head_was'))[:10]} -> {str(e['head_now'])[:10]}"
            shown = f"{shown}; {commit}" if shown else commit
        parts.append(f"{e.get('repo')}: {shown}")
    return "; ".join(parts)

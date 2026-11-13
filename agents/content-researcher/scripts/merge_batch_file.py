#!/usr/bin/env python3
"""CF-0306: write this stage's own topics into a `03-content-researcher.json`
that already exists, without touching anybody else's.

The stage runs twice on a batch that lost a topic after compliance. The first
call writes the batch file as always. Then the Footage Indexer refills the
lost slot from compliance's reserve (`01b-footage-index.json ->
reserve_substitution`), and this stage is called a second time **for the
substituted topics only**. That second call must not rewrite `03`: the scripts
and the refusals of the first pass are the batch's record of topics this call
never looked at, and a rewrite would quietly delete them.

So the second call writes its own topics into a fragment - the same file shape,
carrying only what this call decided - and this script merges the fragment into
the batch file. It exists so that the merge is machine work: an operator
splicing JSON by hand is how a script loses a `visual_anchors` entry or a
refusal loses its `fact_lookup`.

**The rules, and they are the whole contract.**

* `scripts[]` and `skipped[]` are keyed by `topic_id`. A topic the fragment
  carries replaces that topic's record **in place** (same position), a topic it
  does not carry is left exactly as it was, and a topic nothing carried yet is
  appended in the fragment's own order.
* A topic is in one list or the other, never both: a topic the fragment writes
  a script for leaves `skipped[]`, and a topic it skips leaves `scripts[]`. A
  fragment that puts the same topic in both lists is a contradiction and is
  refused (exit 2) rather than resolved by guesswork.
* `warnings[]` is merged, not replaced: an entry for the same
  (`topic_id`, `warning_code`, `gate`) is replaced in place, anything else is appended.
* The head fields (`batch_id`, `channel`, `language`, `generated_at`,
  `voice_profile`, `stance`, `footage_note`, and anything else at the top) are
  taken from the fragment where it carries them - the file was last written by
  this call, and `generated_at` should say so - and kept from the batch file
  where it does not. A fragment whose `batch_id` is not the batch file's is
  refused (exit 2): that is a fragment for another batch.
* A fragment that refuses a topic the Footage Indexer kept on own graphics
  (`01b-footage-index.json` beside the batch file, `own_graphic_footing.kept[]`)
  as `nothing_to_check` or `thin_scene` is refused (exit 2) and nothing is
  written. Only the fragment's own entries are judged: the first call's file
  was held to the same rule when it was written (`CF-0806`, `check_own_graphic_skips.py`): such a topic is written
  graphics-first, it has no pool to be thin against.
* The write is atomic (temp file in the same directory, then `os.replace`) and
  **idempotent**: merging the same fragment twice gives the same bytes.
* The batch file is `<...>/pipeline/<channel>/<batch-id>/03-content-researcher.json`
  in a batch directory that already exists, and nothing else (`CF-0907`,
  `example-film/2026-11-01T0832Z`: the operator's `$B` was empty in that shell,
  the path became `/03-content-researcher.json`, and the write went for `/`).
  An empty path, a directory, another file name, a tree that is not under
  `pipeline/` (a bare name in a cwd that is not a batch, `..` out of it) or a
  batch directory that does not exist is refused (exit 2) before anything is
  read or written. That is a refusal of the call, never of a topic.

With no batch file there yet, the fragment simply becomes it - so the second
call's command is the same command whether or not the first pass wrote
anything, and an operator has nothing to decide.

Usage::

    python3 scripts/merge_batch_file.py \\
        ~/shorts-content-factory/pipeline/<channel>/<batch-id>/03-content-researcher.json \\
        --add /tmp/03-reserve-topics.json

    # see what it would write, touch nothing
    python3 scripts/merge_batch_file.py <batch-file> --add <fragment> --stdout
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runlog import runlog  # noqa: E402
import check_own_graphic_skips as ogs  # noqa: E402 - CF-0806

# The two lists merged by `topic_id`, in the order they are reported.
KEYED_LISTS = ("scripts", "skipped")
# `warnings[]` has no topic-unique key: one topic can carry several warnings,
# so the identity of a warning is the triple below. `gate` joined it in CF-0330:
# one topic can be warned by two step-6 gates under the same `pool_too_thin`;
# an older entry without a gate keys as None and merges exactly as before.
WARNING_KEY = ("topic_id", "warning_code", "gate")


def read_json(path):
    return json.loads(Path(path).read_text())


def dump(data):
    """The batch file's own formatting, as every `--write` checker in this repo
    spells it - so a merged file and a rewritten one differ in content only."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


BATCH_FILE_NAME = "03-content-researcher.json"


def batch_file_problem(raw):
    """Why `raw` is not a batch file this script may write, or None (CF-0907).

    The check is on the spelled path made absolute against the cwd, with `..`
    folded but symlinks left alone - a `pipeline/` that is a link to another
    disk is still `pipeline/`."""
    if raw is None or not str(raw).strip():
        return ("the batch file path is empty - set the batch directory in the "
                "same shell call (a variable from an earlier call or from inside "
                "a heredoc is not there)")
    path = Path(os.path.abspath(os.path.expanduser(str(raw))))
    if path.name != BATCH_FILE_NAME or (path.exists() and not path.is_file()):
        return (f"{raw!r} is not a batch's {BATCH_FILE_NAME} - pass "
                f"pipeline/<channel>/<batch-id>/{BATCH_FILE_NAME}")
    batch_dir = path.parent
    if len(batch_dir.parts) < 4 or batch_dir.parent.parent.name != "pipeline":
        return (f"{raw!r} resolves to {path}, which is not under "
                f"pipeline/<channel>/<batch-id>/ - an empty shell variable or "
                f"the wrong cwd; nothing was written")
    if not batch_dir.is_dir():
        return (f"the batch directory {batch_dir} does not exist - check the "
                f"channel and the batch id; nothing was written")
    return None


def write_atomically(path, text):
    path = Path(path)
    target_dir = Path(os.path.abspath(path.parent))
    if target_dir == Path(target_dir.anchor):
        raise ValueError(f"CF-0907: refusing to write {path} into the "
                         f"filesystem root {target_dir}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def entries(data, key):
    """The list as it stands, entry for entry. Nothing is filtered out: a
    record this script does not understand is still somebody's record, and
    dropping it would be exactly the loss the merge exists to prevent."""
    value = data.get(key)
    return list(value) if isinstance(value, list) else []


def topic_of(entry):
    return entry.get("topic_id") if isinstance(entry, dict) else None


def topic_ids(data, key):
    return [t for t in (topic_of(e) for e in entries(data, key)) if t]


def merge_keyed(base_list, fragment_list, drop):
    """`base_list` with the fragment's records written in: same topic replaced
    in place, a topic in `drop` removed, anything new appended.

    Returns the merged list and the (replaced, added, removed) counts."""
    incoming = {}
    for entry in fragment_list:
        tid = topic_of(entry)
        if tid:
            incoming[tid] = entry
    out, replaced, removed = [], 0, 0
    seen = set()
    for entry in base_list:
        tid = topic_of(entry)
        if tid and tid in incoming:
            out.append(incoming[tid])
            seen.add(tid)
            replaced += 1
            continue
        if tid and tid in drop:
            removed += 1
            continue
        out.append(entry)
    added = 0
    for entry in fragment_list:
        tid = topic_of(entry)
        if tid and tid in seen:
            continue
        out.append(entry)
        added += 1
    return out, replaced, added, removed


def merge_warnings(base_list, fragment_list):
    def key(entry):
        if not isinstance(entry, dict):
            return ("", json.dumps(entry, sort_keys=True, ensure_ascii=False))
        return tuple(entry.get(k) for k in WARNING_KEY)

    incoming = {key(e): e for e in fragment_list}
    out, seen = [], set()
    for entry in base_list:
        k = key(entry)
        if k in incoming:
            out.append(incoming[k])
            seen.add(k)
            continue
        out.append(entry)
    added = 0
    for entry in fragment_list:
        k = key(entry)
        if k in seen:
            continue
        out.append(entry)
        added += 1
    return out, added


def merge(base, fragment):
    """The merged document, and the lines to print about it.

    Raises ValueError on the two contradictions this refuses to resolve: a
    fragment for another batch, and a topic the fragment puts in both lists."""
    if not isinstance(base, dict) or not isinstance(fragment, dict):
        raise ValueError("both the batch file and the fragment must be JSON "
                         "objects shaped like 03-content-researcher.json")
    base_id, fragment_id = base.get("batch_id"), fragment.get("batch_id")
    if base_id and fragment_id and base_id != fragment_id:
        raise ValueError(
            f"batch_id mismatch: the batch file says {base_id!r} and the "
            f"fragment says {fragment_id!r}. A fragment is merged into its own "
            f"batch's file and nothing else - check which batch directory this "
            f"call was for")
    written = set(topic_ids(fragment, "scripts"))
    refused = set(topic_ids(fragment, "skipped"))
    both = sorted(written & refused)
    if both:
        raise ValueError(
            f"the fragment puts {both} in both `scripts[]` and `skipped[]` - a "
            f"topic is written or refused, not both, and this script will not "
            f"guess which one was meant")

    out = dict(base)
    for key, value in fragment.items():
        if key in KEYED_LISTS or key == "warnings":
            continue
        out[key] = value

    lines = []
    for key in KEYED_LISTS:
        drop = refused if key == "scripts" else written
        merged, replaced, added, removed = merge_keyed(
            entries(base, key), entries(fragment, key), drop)
        out[key] = merged
        lines.append(f"  {key}: {added} added, {replaced} replaced, "
                     f"{removed} moved to the other list, "
                     f"{len(merged) - added - replaced} kept untouched")
    merged_warnings, added = merge_warnings(entries(base, "warnings"),
                                            entries(fragment, "warnings"))
    if merged_warnings or "warnings" in base or "warnings" in fragment:
        out["warnings"] = merged_warnings
    lines.append(f"  warnings: {added} added, {len(merged_warnings)} in all")
    return out, lines


def build_parser():
    parser = argparse.ArgumentParser(
        description="CF-0306: merge this stage's own topics into an existing "
                    "03-content-researcher.json instead of rewriting it.")
    parser.add_argument("batch_file",
                        help="the batch's 03-content-researcher.json (written "
                             "if it does not exist yet)")
    parser.add_argument("--add", required=True, metavar="FRAGMENT",
                        help="a file of the same shape carrying only the "
                             "topics this call decided")
    parser.add_argument("--stdout", action="store_true",
                        help="print the merged file instead of writing it")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    problem = batch_file_problem(args.batch_file)
    if problem:
        print(f"merge_batch_file.py: CF-0907: {problem}", file=sys.stderr)
        return 2
    path = Path(os.path.abspath(os.path.expanduser(args.batch_file)))
    base = read_json(path) if path.exists() else {}
    fragment = read_json(args.add)
    try:
        merged, lines = merge(base, fragment)
    except ValueError as exc:
        print(f"merge_batch_file.py: {exc}", file=sys.stderr)
        return 2
    try:
        barred = ogs.problems(fragment, ogs.read_index(ogs.index_path_for(path)))
    except ValueError as exc:
        print(f"merge_batch_file.py: {exc}", file=sys.stderr)
        return 2
    if barred:
        for line in barred:
            print(f"merge_batch_file.py: {line}", file=sys.stderr)
        return 2
    text = dump(merged)
    if args.stdout:
        sys.stdout.write(text)
        return 0
    write_atomically(path, text)
    print(f"merged {args.add} into {path}")
    for line in lines:
        print(line)
    return 0


@runlog.script("content-researcher", "merge-batch", name="merge_batch_file.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()

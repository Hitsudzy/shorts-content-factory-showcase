#!/usr/bin/env python3
"""CF-0806: a topic kept on own graphics is written, not refused for want of a pool.

On a channel whose base footage is the graphics the Video Editor draws from
the script's facts (ExampleTech, `own_graphic`, CF-0689) the Footage Indexer
keeps a topic with no pool, or a pool of one short source, when its support
text carries enough quotable facts: `01b-footage-index.json ->
own_graphic_footing.kept[]` (and `two_source_floor.kept_on_own_graphics`).
The funnel counts it as passing the footage step. Such a topic is written
graphics-first (SKILL.md step 5, "Own graphics").

`example-tech/2026-10-19T0844Z` is the case: the writer refused 004 (no
source, 38 quotable facts) as `nothing_to_check` - "no footage pool to measure
a script against" - and 005 (one 9 s source, 215 facts) as `thin_scene` -
"the only scene is generic". Both are refusals *because the pool is thin*, and
a kept topic has no pool to be thin against by design. So:

* a `skipped[]` entry with `reason_code` `nothing_to_check` or `thin_scene`
  for a topic 01b keeps on own graphics is refused;
* the cadence gate's own `thin_scene` (`check_anchor_cadence.py --write`, the
  entry carries its `anchor_cadence` record) is not: it is written after a
  script existed and twice could not be told in enough moments - a verdict
  on the writing, not on the pool;
* every other code stays open for a kept topic - `no_fact`,
  `claim_unsupported`, `story_claim_failed`, ... A topic whose facts do not
  hold is refused as before (the subject of the fact is CF-0809's question,
  not this one's).

`merge_batch_file.py` runs the same check on what it is about to write, so
the reserve call's fragment is held to it too.

Usage::

    python3 scripts/check_own_graphic_skips.py <batch>/03-content-researcher.json
    python3 scripts/check_own_graphic_skips.py <03> --footage-index <01b-footage-index.json>

Exit codes: 0 - no such refusal (or no index beside the file: then no topic is
kept); 1 - at least one refused entry, each named on stdout; 2 - usage or an
unreadable file.

Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _own_graphic import kept_on_own_graphics  # noqa: E402

TASK = "CF-0806"
FOOTAGE_INDEX_NAME = "01b-footage-index.json"
# The two refusals that say "the pool is too thin to write on".
BARRED_CODES = ("nothing_to_check", "thin_scene")
# The cadence gate's own `thin_scene` carries this record (check_anchor_cadence.skip_entry).
CADENCE_RECORD = "anchor_cadence"


def index_path_for(batch_file, footage_index=None):
    return Path(footage_index) if footage_index else Path(batch_file).parent / FOOTAGE_INDEX_NAME


def read_index(path):
    """The parsed 01b, or None when there is none. A file that is there and
    cannot be read raises ValueError: a guard judged against nothing is not judged."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot be read as JSON ({exc})")
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: not a JSON object")
    return doc


def is_barred(entry, kept):
    """True when this `skipped[]` entry refuses a kept topic for want of a pool."""
    if not isinstance(entry, dict):
        return False
    return (entry.get("topic_id") in kept
            and entry.get("reason_code") in BARRED_CODES
            and not isinstance(entry.get(CADENCE_RECORD), dict))


def problems(batch, index):
    """One sentence per refused entry of `batch['skipped']`; [] when clean."""
    kept = kept_on_own_graphics(index)
    if not kept or not isinstance(batch, dict):
        return []
    out = []
    for entry in batch.get("skipped") or []:
        if not is_barred(entry, kept):
            continue
        tid, code = entry["topic_id"], entry["reason_code"]
        rec = kept[tid]
        facts = rec.get("quotable_facts")
        sources = rec.get("sources")
        what = (f"{len(sources)} pool source(s)" if isinstance(sources, list) else "its pool")
        if facts is not None:
            what += f", {facts} quotable fact(s)"
        out.append(
            f"{tid}: `{code}` is not a refusal for a topic kept on own graphics ({TASK}) - "
            f"01b own_graphic_footing.kept[] keeps it ({what}); its base footage is the "
            f"graphics the Video Editor draws from the script's facts, so it has no pool to "
            f"be thin against. Write it graphics-first (SKILL.md step 5, \"Own graphics\"), "
            f"or refuse it on its facts (`no_fact`, `claim_unsupported`, ...)")
    return out


def build_parser():
    parser = argparse.ArgumentParser(
        description=f"{TASK}: refuse `nothing_to_check` / `thin_scene` for a topic the "
                    f"Footage Indexer kept on own graphics.")
    parser.add_argument("batch_file", help="the batch's 03-content-researcher.json")
    parser.add_argument("--footage-index", metavar="FILE",
                        help=f"the batch's {FOOTAGE_INDEX_NAME} (default: beside the batch file)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        batch = json.loads(Path(args.batch_file).read_text(encoding="utf-8"))
        index = read_index(index_path_for(args.batch_file, args.footage_index))
    except (OSError, ValueError) as exc:
        print(f"check_own_graphic_skips.py: {exc}", file=sys.stderr)
        return 2
    if index is None:
        print(f"  none {args.batch_file}: no {FOOTAGE_INDEX_NAME} beside it, no topic is "
              f"kept on own graphics")
        return 0
    found = problems(batch, index)
    for line in found:
        print(f"  FAIL {line}")
    if not found:
        kept = len(kept_on_own_graphics(index))
        print(f"  ok   {args.batch_file}: no topic kept on own graphics ({kept}) is refused "
              f"as {' / '.join(BARRED_CODES)}")
    return 1 if found else 0


@runlog.script("content-researcher", "own-graphic-skips", name="check_own_graphic_skips.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()

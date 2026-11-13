#!/usr/bin/env python3
"""CF-0763..0766: a batch that hands the Content Researcher no topic still
leaves `03-content-researcher.json` - written by a machine, not by a model's
goodwill.

The case, example-tech/2026-10-16T0702Z: Trend Hunter wrote 0 topics (2 scored,
both refused `no_fact`), the compliance shortlist carried 0, the indexer
fetched nothing, and the Researcher closed by its SKILL's `empty_shortlist_close`
("0 eligible topics, no scripts written") with no `03`. Its SKILL said "the
stop-cock of CF-0322 closes the batch" - but the stop-cock reads `03`, and
without it its state is `not_reached`, which stops nothing. So
compliance-scripts, the Editor and the frame judge each ran on nothing, each
closed with a note and without its own file, and the triage filed four
broken contracts (CF-0763..0766) for one empty shelf.

The fix is the CF-0707 shape (frame-judge-empty): the run plan's machine
stage `content-researcher-empty` runs this script exactly when the
`run_checks` condition `nothing_to_write` holds, and the LLM stage
`content-researcher` runs only on `write_candidates`. The file it writes is
the one a stopped batch has always had (CF-0322: `scripts: []`), so the
stop-cock reads `stop`, every stage after it is skipped by its own
`when: runlog stopcock`, and the runs row says `outcome: no_material` - the
named, normal end of a batch with no material, not an accident.

**What counts as "nothing to write"** - deliberately conservative, because a
wrong "nothing" would skip the Researcher on a batch that had material (a new
refusal with no price). The incoming set (SKILL step 1, CF-0265, CF-0306) is

    02 results[] with a production verdict (clear / caution / review)
  + the topics 01b -> reserve_substitution substituted in (this run's block,
    CF-0781: the previous run's block a rerun-from left in 01b is not read)
  - 01b skipped_topics[]
  + every topic 01b registered sources for (sources_by_topic)

and "nothing" means that set is empty with both `02` and `01b` readable. A
batch without a readable `02` or `01b` is not ours: the Researcher's own
no-waiting exit names the missing file and the triage puts the break on the
upstream stage (CF-0730).

Usage:

    python3 scripts/researcher_nothing_to_write.py --batch <batch dir> [--check]

Exit 0: the empty `03` was written (with `--check`: there is nothing to write).
Exit 1: with `--check`, the Researcher has topics to write (or an input is
        unreadable).
Exit 2: bad usage - no batch directory; without `--check`, a batch whose
        Researcher has something to write (the stage never passes an empty
        record off as the Researcher's work), or a `03` already there.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
import funnel                                                      # noqa: E402
import runlog                                                      # noqa: E402
sys.path.insert(0, str(ROOT / "shared"))
import channel_ids                                                 # noqa: E402
import stopcock                                                    # noqa: E402

TASK = "CF-0763"
RESEARCHER_FILE = stopcock.RESEARCHER_FILE
INDEX_FILE = stopcock.INDEX_FILE
COMPLIANCE_FILE = stopcock.COMPLIANCE_FILE
NOTE_KEY = "nothing_to_write"
# the SKILL's own note of this exit, letter for letter (shared/runlog/no_waiting.py
# `empty_shortlist_close`), so the record reads it as the same close
CLOSE_NOTE = "0 eligible topics, no scripts written"


def _load(path):
    """(parsed dict, error sentence); a file that is not there is (None, None)."""
    if not path.is_file():
        return None, None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{path.name} will not parse ({e.__class__.__name__}: {e})"
    if not isinstance(d, dict):
        return None, f"{path.name} is not a JSON object"
    return d, None


def _ids(rows):
    return {r.get("topic_id") for r in rows if isinstance(r, dict) and r.get("topic_id")}


def incoming(batch_dir):
    """(set of topic ids the Researcher may be handed, None) or (None, why) when
    `02` or `01b` is not readable - then the condition is not ours to answer."""
    bd = Path(batch_dir)
    A = {}
    for name in (COMPLIANCE_FILE, INDEX_FILE):
        d, err = _load(bd / name)
        if d is None:
            return None, err or f"no {name}"
        A[name] = d
    c02, idx = A[COMPLIANCE_FILE], A[INDEX_FILE]
    passed = {r.get("topic_id") for r in funnel._rows(c02, "results")
              if r.get("topic_id") and r.get("verdict") in funnel.PRODUCTION_VERDICTS}
    sub, _ = stopcock.substitution_block(A, bd)
    subs, _ = funnel._substitutions({funnel.SUBSTITUTION_KEY: sub} if sub else None)
    dropped = _ids(funnel._rows(idx, "skipped_topics"))
    sourced = {t for t, v in funnel._sources_by_topic(idx).items() if t and v}
    return ((passed | set(subs)) - dropped) | sourced, None


def nothing_to_write(batch_dir):
    """(holds, sentence): True when `02` and `01b` are readable and hand the
    Researcher no topic at all."""
    topics, err = incoming(batch_dir)
    if topics is None:
        return False, f"{err}: the Researcher's own stage says what is missing"
    if topics:
        return False, (f"{len(topics)} topic(s) reach the Researcher: "
                       + ", ".join(sorted(topics)[:5]) + (" ..." if len(topics) > 5 else ""))
    bd = Path(batch_dir)
    c02, _ = _load(bd / COMPLIANCE_FILE)
    idx, _ = _load(bd / INDEX_FILE)
    res, shelf = funnel._rows(c02, "results"), funnel._rows(c02, "reserve")
    passed = [r for r in res if r.get("verdict") in funnel.PRODUCTION_VERDICTS]
    dropped = funnel._rows(idx, "skipped_topics")
    return True, (f"nothing to write - {COMPLIANCE_FILE}: {len(res)} result(s), "
                  f"{len(passed)} with a production verdict, {len(shelf)} in reserve; "
                  f"{INDEX_FILE}: sources for 0 topic(s), {len(dropped)} skipped, "
                  f"0 substituted in")


def _batch_id(bd):
    for name in (COMPLIANCE_FILE, INDEX_FILE):
        d, _ = _load(bd / name)
        if isinstance(d, dict) and isinstance(d.get("batch_id"), str) and d["batch_id"]:
            return d["batch_id"], channel_ids.resolve_channel(d.get("channel"), root=ROOT)
    return bd.name, channel_ids.resolve_channel(bd.parent.name, root=ROOT)


def document(batch_dir, why):
    bd = Path(batch_dir)
    batch_id, channel = _batch_id(bd)
    return {"batch_id": batch_id, "channel": channel or bd.parent.name,
            "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "written_by": f"scripts/researcher_nothing_to_write.py ({TASK})",
            "scripts": [], "skipped": [], NOTE_KEY: why}


def write(batch_dir):
    """Write the empty `03`; SystemExit(str) when the batch has something to
    write or already has its `03`."""
    bd = Path(batch_dir)
    out = bd / RESEARCHER_FILE
    if out.exists():
        raise SystemExit(f"researcher-empty: {out} is already there - this stage never "
                         f"overwrites the Researcher's record")
    holds, why = nothing_to_write(bd)
    if not holds:
        raise SystemExit(f"researcher-empty: refused - {why}")
    doc = document(bd, why)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="CF-0763: write 03-content-researcher.json with "
                                             "scripts: [] for a batch that hands the "
                                             "Researcher no topic")
    ap.add_argument("--batch", default=os.environ.get(runlog.BATCH_ENV),
                    help="batch directory (default: $RUNLOG_BATCH)")
    ap.add_argument("--check", action="store_true",
                    help="only answer: exit 0 when there is nothing to write, 1 otherwise")
    a = ap.parse_args(argv)
    if not a.batch:
        raise SystemExit("researcher-empty: no batch directory - pass --batch DIR or set "
                         f"{runlog.BATCH_ENV}")
    bd = Path(a.batch)
    if not bd.is_dir():
        raise SystemExit(f"researcher-empty: {bd} is not a directory")
    if a.check:
        holds, why = nothing_to_write(bd)
        print(f"nothing_to_write: {'yes' if holds else 'no'} - {why}")
        return 0 if holds else 1
    doc = write(bd)
    print(f"{RESEARCHER_FILE}: scripts: [] - {doc[NOTE_KEY]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(2)
        raise

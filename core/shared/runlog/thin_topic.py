#!/usr/bin/env python3
"""CF-0845: a topic whose pool is too thin for a script is not written past
the first plan check and gets no thin-pool supplement.

The user's signature of 2026-10-21 (Q8, the floor 10). The review of the Reel
batch of 21.10 and of the five batches with a supplement (13.10, 18.10, Tech
16.10, Tech 20.10, 21.10): no topic with 7 usable shots or fewer was saved by
the supplement - the one save was a topic with 96 (Reel 13.10, 007). Topics
001 and 005 of 21.10 (0 usable each) cost ~40 minutes (two plan checks of
4m55 and 6m22, 23.4 min of supplement, two post-supplement checks of 2m49 and
2m12) and 36 searches, and the writer itself wrote "only 2 usable shots".

**The count** is the Footage Indexer's own, never re-derived here:
`01b-footage-index.json -> pool_depth.topics[].usable_shots` - the CLEAN shots
of the topic's pool by `pool_depth.screen_shots()` (CF-0304/CF-0435), the
number the indexer's walk holds against its depth floor. A topic with no
measured row (no `pool_depth`, `measured: false`, no whole number) is not
called thin: nobody can say, and the rule never drops a topic on a guess.

**The floor** is the channel's
`content_researcher.min_usable_shots_for_script` (schema:
patterns/validate_patterns.py::validate_content_researcher_block); absent or
unusable means `DEFAULT_MIN_USABLE_SHOTS` (10); `0` switches the rule off.

**Two places read it:**

* the thin-pool supplement step (`supplement.py`, `_close_too_thin`): a
  pending request of a topic under the floor is closed `skipped`, `outcome:
  too_thin`, before the clock and before any tool - nothing searched, nothing
  fetched (the CF-0842 way);
* the drop before the first plan check (`drop()` / the CLI `--write`): every
  script of a topic under the floor leaves `03-content-researcher.json ->
  scripts[]` for `skipped[]` with the existing code `pool_too_thin` (funnel
  "пул тоньше сценария"), `stage: "scripts"`, `gate: "min_usable_shots"` and
  the numbers. Nothing else is needed for the slot: `reserve_refill`
  (shared/run_checks.py) counts every `skipped[]` entry whose slot the
  reserve has not answered, so the reserve round refills it by the usual
  rules. The Content Researcher calls it at its step 6b, before
  `plan_check_loop.py` (agents/content-researcher - the agent's half).

  CF-0850: the same pass also records a thin topic that has **no script at
  all**. The Researcher's step 2 asks `--check` first and does not write a
  topic it lists, so on `example-tech/2026-10-22T0833Z` the drop above found
  no script of `-017` (0 usable shots) to move and the topic left the batch
  in neither `scripts[]` nor `skipped[]` - a contract breach (`runlog
  triage`: unexplained), and its slot never reached `reserve_refill`. Now
  every thin topic the Researcher was handed (`handed_topics()`: the reading
  of `tests/test_pipeline_contracts.py::
  check_researcher_accounts_for_every_topic`) that is in neither list gets
  the same `pool_too_thin` entry, without a `script_id`. No new refusal: the
  code and the floor are CF-0845's, priced there.

CLI:

    python3 scripts/thin_topic_gate.py --batch <batch> [--check] [--write] [--json]

`--check` (the default) lists the thin topics and exits 1 when there are any,
0 when none; `--write` moves the scripts of the thin topics of 03 into
`skipped[]` and records a handed thin topic with no script there (CF-0850)
(idempotent) and exits 0. 2 - bad call. Stdlib only.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import supplement                                                   # noqa: E402

TASK = "CF-0845"
KEY_PATH = ("content_researcher", "min_usable_shots_for_script")
DEFAULT_MIN_USABLE_SHOTS = 10
INDEX_FILE = "01b-footage-index.json"
SCRIPTS_FILE = "03-content-researcher.json"
COMPLIANCE_FILE = "02-compliance-checker.json"
REASON_CODE = "pool_too_thin"            # funnel.FUNNEL_CODES, since CF-0232
GATE = "min_usable_shots"
STAGE = "scripts"
MEASURE = "01b-footage-index.json pool_depth.topics[].usable_shots"


def threshold(channel, root=None):
    """-> `(floor, source)`: the channel's `content_researcher.
    min_usable_shots_for_script`, or the default when the config, the block or
    a usable value (a whole number >= 0) is missing."""
    cfg = supplement._read(supplement._root(root) / "channels" / f"{channel}.json") \
        if channel else None
    v = cfg
    for k in KEY_PATH:
        v = v.get(k) if isinstance(v, dict) else None
    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
        return v, f"channels/{channel}.json {'.'.join(KEY_PATH)}"
    return DEFAULT_MIN_USABLE_SHOTS, "default"


def batch_threshold(batch_dir, root=None):
    """`threshold()` of the batch's channel (`supplement.batch_channel`)."""
    return threshold(supplement.batch_channel(batch_dir, root), root)


def usable_shots(batch_dir):
    """`{topic_id: usable_shots}` of the topics the indexer measured
    (`pool_depth.topics[]` rows with a whole `usable_shots` and not
    `measured: false`); {} without a readable 01b or `pool_depth`."""
    idx = supplement._read(Path(batch_dir) / INDEX_FILE)
    block = idx.get("pool_depth") if isinstance(idx, dict) else None
    rows = block.get("topics") if isinstance(block, dict) else None
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("topic_id") or r.get("measured") is False:
            continue
        n = r.get("usable_shots")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
            out[r["topic_id"]] = n
    return out


def thin_topics(batch_dir, root=None, topics=None):
    """`[{topic_id, usable_shots, floor, floor_from}]` of the measured topics
    under the channel's floor, sorted by topic id; `topics` narrows the set
    (default: every measured topic). [] when the rule is off (floor 0)."""
    floor, source = batch_threshold(batch_dir, root)
    if floor <= 0:
        return []
    want = set(topics) if topics is not None else None
    return [{"topic_id": t, "usable_shots": n, "floor": floor, "floor_from": source}
            for t, n in sorted(usable_shots(batch_dir).items())
            if n < floor and (want is None or t in want)]


def handed_topics(batch_dir):
    """CF-0850: the topics the Researcher was handed - the set the live
    contract (`tests/test_pipeline_contracts.py::
    check_researcher_accounts_for_every_topic`) holds it to: every
    `02-compliance-checker.json -> results[]` topic and every reserve
    substitute the indexer promoted (`01b reserve_substitution.substitutions[]`
    with `outcome: "sources"`), less the topics the indexer itself took off
    (`01b skipped_topics[]` - a promoted substitute only when its pool closed
    empty, CF-0306/CF-0308 #3). An unused reserve topic is never in it. Empty
    without a readable 02 (nobody can say what was handed)."""
    bdir = Path(batch_dir)
    c02 = supplement._read(bdir / COMPLIANCE_FILE)
    if not isinstance(c02, dict):
        return set()
    idx = supplement._read(bdir / INDEX_FILE)
    idx = idx if isinstance(idx, dict) else {}
    pools = idx.get("sources_by_topic") if isinstance(idx.get("sources_by_topic"), dict) else {}
    subs = (idx.get("reserve_substitution") or {}) \
        if isinstance(idx.get("reserve_substitution"), dict) else {}
    promoted = {s["topic_id"] for s in subs.get("substitutions") or []
                if isinstance(s, dict) and s.get("topic_id") and s.get("outcome") == "sources"}
    with_pool = {t for t in promoted if pools.get(t, None) != []}
    off = {s["topic_id"] for s in idx.get("skipped_topics") or []
           if isinstance(s, dict) and s.get("topic_id") and s["topic_id"] not in with_pool}
    results = {r["topic_id"] for r in c02.get("results") or []
               if isinstance(r, dict) and r.get("topic_id")}
    return (results | promoted) - off


def reason(row, script_id=None):
    if script_id is None and row.get("unwritten"):
        return (f"{row['usable_shots']} usable shot(s) in the topic's pool ({MEASURE}) - "
                f"under the floor of {row['floor']} for a script ({row['floor_from']}, "
                f"{TASK}): not written (thin_topic_gate.py --check, the Researcher's step 2), "
                f"recorded by the gate before the first plan check (CF-0850), no supplement; "
                f"the slot goes to the reserve")
    return (f"{script_id + ': ' if script_id else ''}{row['usable_shots']} usable shot(s) in "
            f"the topic's pool ({MEASURE}) - under the floor of {row['floor']} for a script "
            f"({row['floor_from']}, {TASK}): taken out before the first plan check, no "
            f"supplement; the slot goes to the reserve")


def skip_entry(row, script=None):
    """The `03 -> skipped[]` entry of a thin topic - the CF-0232 shape
    (`topic_id`, `reason_code`, `reason` read alone, `stage`) and the numbers."""
    script = script or {}
    e = {"topic_id": row["topic_id"]}
    if script.get("script_id"):
        e["script_id"] = script["script_id"]
    e.update({"reason_code": REASON_CODE, "reason": reason(row, script.get("script_id")),
              "stage": STAGE, "gate": GATE, "usable_shots": row["usable_shots"],
              "min_usable_shots": row["floor"], "floor_from": row["floor_from"],
              "measure": MEASURE, "task": TASK})
    if row.get("unwritten") and not script.get("script_id"):
        e["unwritten"] = True                       # CF-0850: no script was ever written
    return e


def _already(skipped, tid):
    return any(isinstance(s, dict) and s.get("topic_id") == tid and s.get("gate") == GATE
               for s in skipped)


def drop(doc, rows):
    """Move every script of the topics in `rows` from `doc["scripts"]` to
    `doc["skipped"]` in place. -> the entries added (one per script; a topic
    already skipped by this gate gets none)."""
    by_topic = {r["topic_id"]: r for r in rows}
    scripts = doc.get("scripts") if isinstance(doc.get("scripts"), list) else []
    skipped = doc.setdefault("skipped", [])
    if not isinstance(skipped, list):
        skipped = doc["skipped"] = []
    keep, added = [], []
    for s in scripts:
        tid = s.get("topic_id") if isinstance(s, dict) else None
        if tid not in by_topic:
            keep.append(s)
            continue
        if not _already(skipped, tid):
            added.append(skip_entry(by_topic[tid], s))
    doc["scripts"] = keep
    skipped.extend(added)
    return added


def record_unwritten(doc, rows):
    """CF-0850: a `skipped[]` entry, in place, for every topic of `rows` that
    is in neither `doc["scripts"]` nor `doc["skipped"]` (under any code) - the
    thin topic the Researcher did not write. -> the entries added."""
    skipped = doc.setdefault("skipped", [])
    if not isinstance(skipped, list):
        skipped = doc["skipped"] = []
    accounted = {s.get("topic_id") for s in (doc.get("scripts") or []) + skipped
                 if isinstance(s, dict)}
    added = [skip_entry(dict(r, unwritten=True)) for r in rows
             if r["topic_id"] not in accounted]
    skipped.extend(added)
    return added


def write(batch_dir, root=None):
    """The drop on the batch's 03: -> `(rows, added)`. 03 is rewritten
    atomically only when a script moved."""
    bdir = Path(batch_dir)
    doc = supplement._read(bdir / SCRIPTS_FILE)
    if not isinstance(doc, dict):
        raise SystemExit(f"thin-topic: no readable {SCRIPTS_FILE} in {bdir}")
    live = {s.get("topic_id") for s in doc.get("scripts") or [] if isinstance(s, dict)}
    rows = thin_topics(bdir, root, topics=live | handed_topics(bdir))
    added = drop(doc, [r for r in rows if r["topic_id"] in live]) if rows else []
    # CF-0850: a thin topic handed to the Researcher and never written is
    # recorded too - the drop above only sees scripts.
    added += record_unwritten(doc, rows) if rows else []
    if added:
        doc.setdefault("thin_topic_gate", []).append(
            {"task": TASK, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "topics": sorted({a["topic_id"] for a in added})})
        supplement._write(bdir / SCRIPTS_FILE, doc)
    return rows, added


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="thin_topic_gate.py",
                                 description="CF-0845: a topic with fewer usable shots than "
                                             "the channel's floor leaves 03 before the plan check")
    ap.add_argument("--batch", default=os.environ.get("RUNLOG_BATCH"))
    ap.add_argument("--check", action="store_true", help="list the thin topics (the default)")
    ap.add_argument("--write", action="store_true",
                    help="move their scripts from 03 scripts[] to skipped[]")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None)
    ns = ap.parse_args(argv)
    if not ns.batch or not Path(ns.batch).is_dir():
        print(f"thin-topic: no batch directory ({ns.batch!r}) - pass --batch DIR",
              file=sys.stderr)
        return 2
    floor, source = batch_threshold(ns.batch, ns.root)
    if ns.write:
        try:
            rows, added = write(ns.batch, ns.root)
        except SystemExit as e:
            print(e.code, file=sys.stderr)
            return 2
        out = {"floor": floor, "floor_from": source, "thin": rows, "skipped": added}
        print(json.dumps(out, indent=2, ensure_ascii=False) if ns.json else
              f"thin-topic: floor {floor} ({source}) - "
              + (", ".join(f"{a.get('script_id') or a['topic_id']} -> skipped[] "
                           f"{REASON_CODE} ({a['usable_shots']} usable)" for a in added)
                 or "nothing to take out"))
        return 0
    rows = thin_topics(ns.batch, ns.root)
    out = {"floor": floor, "floor_from": source, "thin": rows}
    print(json.dumps(out, indent=2, ensure_ascii=False) if ns.json else
          f"thin-topic: floor {floor} ({source}) - "
          + (", ".join(f"{r['topic_id']} ({r['usable_shots']} usable)" for r in rows)
             or "no topic under it"))
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CF-0323, item 3: where every `no_production_fact` loss was actually decided,
and what the ones decided late were paid for.

The grill of 2026-09-22 counted `no_production_fact` at 29 topics of 101 across
ten instrumented runs - the funnel's first killer - and read that number as
"29 topics indexed and then thrown away". The funnel counts a code, not a
stage, and both ends of the pipeline write this one code: Trend Hunter at
selection (`fact_probe_topics.py`, CF-0264) and Content Researcher after the
footage is indexed (`agents/content-researcher/scripts/fact_refusal.py`,
CF-0185). So the number has to be split before it can be acted on, and that is
all this script does.

It replays over the **frozen artifacts** and nothing else - the batch
directories under `pipeline/<channel>/<batch>/`, which no later run rewrites
(the same corpus and the same reason as `shared/runlog/gate_price.py`, CF-0320;
`shared/footage/` is not frozen and is deliberately not read here). Per batch it
reads:

    01-trend-hunter.json    skipped_topics[]   -> the losses taken at selection
                            topics[].fact_probe -> the answer that was observable
    01b-footage-index.json  sources_by_topic{} -> what a topic cost to index
    03-content-researcher.json skipped[]       -> the losses taken after it

and for every loss says which stage decided it, whether the answer was already
observable at selection, and how many indexed sources the late ones were paid
with. A loss taken at selection costs nothing: it happens before compliance,
before the footage fan-out, before a single download.

    scripts/fact_rule_replay.py            # the table
    scripts/fact_rule_replay.py --json     # the same, machine-readable

No network, no venv, stdlib only. Read-only: it writes nothing anywhere.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402
from _factrule import fact_rule  # noqa: E402

HUNTER = "01-trend-hunter.json"
INDEX = "01b-footage-index.json"
WRITER = "03-content-researcher.json"
CODE = fact_rule.REFUSAL_CODE

STAGE_HUNTER = "trend-hunter"
STAGE_WRITER = "content-researcher"


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def batches(pool):
    """Every frozen batch directory holding a writer artifact, oldest first."""
    out = []
    for channel in sorted(p for p in Path(pool).iterdir() if p.is_dir()):
        for batch in sorted(p for p in channel.iterdir() if p.is_dir()):
            if (batch / WRITER).is_file():
                out.append((channel.name, batch.name, batch))
    return out


def indexed_sources(index):
    """`{topic_id: sources indexed for it}` - what a topic cost the indexer."""
    by_topic = (index or {}).get("sources_by_topic") or {}
    return {tid: (len(v) if isinstance(v, list) else (v or 0))
            for tid, v in by_topic.items()}


def probe_records(hunter):
    """Every probe answer the selection pass recorded, carried or refused."""
    out = {}
    for topic in (hunter or {}).get("topics") or []:
        out[topic.get("topic_id")] = topic.get("fact_probe")
    for row in (hunter or {}).get("skipped_topics") or []:
        out.setdefault(row.get("topic_id"), row.get("fact_probe"))
    return out


# CF-0640: the selection pass grew a second fact gate on 2026-10-06 (CF-0548,
# 1a9bdb5): `check_scenes.py --write` judges every topic's fact candidates
# against the topic's own scenes and refuses, before the indexer, a topic whose
# every passing candidate is about something else (WNL 0701Z: the cold open
# under the monologue). A batch selected before that gate - or replayed later
# from such a selection, as `rebuilds/2026-10-05T1244Z` was - lets that topic
# through to the writer, which refuses it after the footage is paid for. The
# gate leaves its mark in the data, the way `selection` marks CF-0264: every
# candidate it judged carries `scene_fit`, every topic it refused sits in
# `skipped_topics[]` with `rule: "CF-0548"`.
SCENE_FIT_TASK = "CF-0548"
SCENE_FIT_KEY = "scene_fit"       # fact_scene.FIT_KEY, written on each judged candidate


def scene_fit_ran(hunter):
    """True when the hunter artifact bears the CF-0548 gate's mark: a fact
    candidate (in `topics[]` or `skipped_topics[]`) carrying `scene_fit`, or a
    topic it refused. False for a selection made before the gate - and, since
    the data cannot tell the two apart, for one made after it whose
    `check_scenes.py --write` did not run (CF-0640): read it with
    `scene_fit_drops`, never as a reason to skip a whole batch."""
    hunter = hunter or {}
    for row in (hunter.get("skipped_topics") or []):
        if isinstance(row, dict) and row.get("rule") == SCENE_FIT_TASK:
            return True
    for row in (hunter.get("topics") or []) + (hunter.get("skipped_topics") or []):
        for cand in (row.get("fact_candidates") or []) if isinstance(row, dict) else []:
            if isinstance(cand, dict) and SCENE_FIT_KEY in cand:
                return True
    return False


def scene_fit_drops(hunter, topic_id):
    """True when today's CF-0548 gate (`check_scenes.fact_fit`, the root's
    `fact_scene.py`) refuses this topic of the batch at selection: every one of
    its passing candidates is about another scene. Loaded lazily - it needs the
    factory root."""
    import check_scenes  # noqa: E402 - reads <root>/shared/factrule/fact_scene.py
    topics = [t for t in (hunter or {}).get("topics") or [] if isinstance(t, dict)]
    topic = next((t for t in topics if t.get("topic_id") == topic_id), None)
    if topic is None:
        return False
    return bool(check_scenes.fact_fit(topic, topics)[1])


def replay_batch(batch_dir):
    """One batch: a row per `no_fact` loss (`no_production_fact` before
    CF-0438, read as the same code through `fact_rule.canonical_code`), in the order the
    pipeline took them."""
    hunter = _read(Path(batch_dir) / HUNTER)
    writer = _read(Path(batch_dir) / WRITER)
    cost = indexed_sources(_read(Path(batch_dir) / INDEX))
    probes = probe_records(hunter)
    rows = []

    for row in (hunter or {}).get("skipped_topics") or []:
        if fact_rule.canonical_code(row.get("reason_code")) != CODE:
            continue
        answer = fact_rule.answer_of_probe(row.get("fact_probe") or {})
        rows.append({"topic_id": row.get("topic_id"), "title": row.get("title"),
                     "decided_by": STAGE_HUNTER,
                     "state": fact_rule.classify(answer),
                     "status": answer.get("status"),
                     "observable_at_selection": True,
                     "indexed_sources": 0, "paid": False})

    for row in (writer or {}).get("skipped") or []:
        if fact_rule.canonical_code(row.get("reason_code")) != CODE:
            continue
        tid = row.get("topic_id")
        answer = fact_rule.answer_of_lookup(row.get("fact_lookup") or {})
        state = fact_rule.classify(answer)
        probe = probes.get(tid)
        # Was the answer already there to be read at selection? Two ways yes:
        # the stage probed this topic (a record, whatever it said), or the
        # stage did not probe at all but the answer the writer got is one the
        # same probe returns - the probe is `production_facts.py` with
        # `limit=1`, so any status but `source_unreachable` was observable the
        # moment the topic was scored. A batch written before CF-0264 has no
        # probe records and is exactly that second case.
        settled_at_selection = (
            probe is not None
            and fact_rule.settled(fact_rule.classify(fact_rule.answer_of_probe(probe))))
        observable = settled_at_selection or fact_rule.settled(state)
        rows.append({"topic_id": tid, "title": (row.get("fact_lookup") or {})
                     .get("asked", {}).get("name"),
                     "decided_by": STAGE_WRITER, "state": state,
                     "status": answer.get("status"),
                     "probe_at_selection": (probe or {}).get("outcome") if probe else None,
                     "observable_at_selection": observable,
                     "indexed_sources": cost.get(tid, 0),
                     "paid": cost.get(tid, 0) > 0})
    return rows


def replay(pool):
    out = []
    for channel, batch, path in batches(pool):
        for row in replay_batch(path):
            row["channel"], row["batch"] = channel, batch
            out.append(row)
    return out


def totals(rows):
    late = [r for r in rows if r["decided_by"] == STAGE_WRITER]
    return {"losses": len(rows),
            "decided_at_selection": sum(1 for r in rows if r["decided_by"] == STAGE_HUNTER),
            "decided_after_indexing": len(late),
            "paid_with_indexing": sum(1 for r in late if r["paid"]),
            "indexed_sources_paid": sum(r["indexed_sources"] for r in late),
            "late_and_observable_at_selection":
                sum(1 for r in late if r["observable_at_selection"]),
            "late_and_not_observable":
                sum(1 for r in late if not r["observable_at_selection"])}


def report(rows, out=sys.stdout):
    t = totals(rows)
    out.write(f"{CODE} over {len({(r['channel'], r['batch']) for r in rows})} frozen "
              f"batch(es) that lost a topic to it\n\n")
    out.write(f"{'batch':22} {'topic':24} {'decided by':18} {'status':16} {'sources':>7}\n")
    for r in sorted(rows, key=lambda r: (r["batch"], r["decided_by"])):
        out.write(f"{r['batch']:22} {(r['topic_id'] or '?')[:24]:24} "
                  f"{r['decided_by']:18} {str(r['status']):16} "
                  f"{r['indexed_sources'] or '-':>7}\n")
    out.write(f"\n  losses                       {t['losses']}\n"
              f"  taken at selection (free)    {t['decided_at_selection']}\n"
              f"  taken after the indexer      {t['decided_after_indexing']}\n"
              f"    of those, paid with        {t['indexed_sources_paid']} indexed source(s)\n"
              f"    observable at selection    {t['late_and_observable_at_selection']}\n"
              f"    not observable there       {t['late_and_not_observable']}\n")
    out.write(f"\nrule: {fact_rule.RULE_ID} {fact_rule.RULE_VERSION} ({fact_rule.ORIGIN})\n")
    return t


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", default=None,
                        help="the frozen pipeline pool (default <root>/pipeline)")
    parser.add_argument("--json", action="store_true", help="rows and totals as JSON")
    args = parser.parse_args(argv)
    pool = Path(args.pool) if args.pool else factory_root() / "pipeline"
    if not pool.is_dir():
        sys.stderr.write(f"no pool at {pool}\n")
        return 2
    rows = replay(pool)
    if args.json:
        json.dump({"rows": rows, "totals": totals(rows)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())

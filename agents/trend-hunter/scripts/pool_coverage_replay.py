#!/usr/bin/env python3
"""CF-0325 item 4: how many of the pool losses hype x pool would have taken off.

Replays every frozen batch of the channel (`pipeline/<channel>/*` and the
directories under its former ids, read from `former_channel_ids`) against the pool **as it
stood when that batch started** - `index.json` entries fetched before the
batch id's time, shots retired before it - and asks two questions of every
topic the batch lost to a pool code:

  pool_had_it  the pool already held what the loss says was missing:
               `no_second_source` / `fetch_failed` - at least SOURCE_FLOOR (2)
               sources of the title were in the pool before a byte was
               fetched; `pool_too_thin` - the pool already held
               POOL_DEPTH_FLOOR (60) usable shots of it.
  ranked_out   re-cut under hype x pool, the topic falls out of the first
               `max_titles_per_batch` (5) of the batch's viable topics
               (`topics[]` + the `below_shortlist` reserve), i.e. a pooled
               topic would have taken its slot.

Losses read (topic level only; per-candidate `failed[]` records are counted
separately as fetch failures, not as lost topics):
  01b-footage-index.json  skipped_topics[]   no_second_source / fetch_failed
  03-content-researcher   skipped[]          no_second_source / pool_too_thin
  05-video-editor         refusals[]         no_second_source / pool_too_thin
A topic lost twice (01b then 03) is counted once, at its first loss.

Caveats, said by the output too: the pool is screened with *today's* cached
verdicts (CF-0275 and CF-0283 restamped caches since), and a source deleted
from `shared/footage` since is invisible - the replay can undercount the pool
a batch had, never overcount it.

    .venv/bin/python scripts/pool_coverage_replay.py --channel <id> [--json]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _channel_ids  # noqa: E402
import pool_coverage as pc  # noqa: E402

# The channel is the caller's (`--channel`, CF-0213: no default - it used to
# be a constant naming the first channel); the directories it has written
# under (the current one and every former id in `channels/<id>.json` ->
# `former_channel_ids`) come from shared/channel_ids.py via the shim.
POOL_CODES = ("no_second_source", "pool_too_thin", "fetch_failed")
LOSS_SITES = (("01b-footage-index.json", "skipped_topics"),
              ("03-content-researcher.json", "skipped"),
              ("05-video-editor.json", "refusals"))
BATCH_TARGET = 5


def batch_time(batch_id):
    """`2026-09-21T0358Z` -> `2026-09-21T03:58:00+00:00` (index.json's form)."""
    d, _, t = batch_id.partition("T")
    t = t.rstrip("Z")
    return f"{d}T{t[:2]}:{t[2:4]}:00+00:00"


def _load(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def losses(batch_dir):
    """[(topic_id, code, where)] - first loss per topic."""
    out, seen = [], set()
    for name, key in LOSS_SITES:
        doc = _load(batch_dir / name) or {}
        for row in doc.get(key) or []:
            if not isinstance(row, dict):
                continue
            code, tid = row.get("reason_code"), row.get("topic_id")
            if code in POOL_CODES and tid and tid not in seen:
                seen.add(tid)
                out.append((tid, code, name))
    return out


def fetch_failures(batch_dir):
    doc = _load(batch_dir / "01b-footage-index.json") or {}
    return sum(1 for r in doc.get("failed") or [] if isinstance(r, dict)
               and r.get("reason_code") == "fetch_failed")


def viable_topics(hunter):
    rows = list(hunter.get("topics") or [])
    for r in hunter.get("skipped_topics") or []:
        if isinstance(r, dict) and r.get("reason_code") == "below_shortlist":
            rows.append(r.get("topic") or {"topic_id": r.get("topic_id"),
                                           "title_ref": {"name": r.get("title")},
                                           "signal": {"popularity_score":
                                                      r.get("popularity_score")}})
    return rows


def score(t):
    try:
        return float((t.get("signal") or {}).get("popularity_score"))
    except (TypeError, ValueError):
        return -1.0


def replay(root, channel):
    root = Path(root)
    channel = _channel_ids.resolve_channel(channel, root=root)
    entries = pc.load_index(root)
    names = pc.topic_names(root)
    judge = pc.host_judge(root, channel)      # CF-0817: host shows earn no bonus
    rows, fetch_fail = [], 0
    # Oldest name first, so the rows keep the order of the batches' history.
    chan_dirs = _channel_ids.channel_batch_dirs(channel, root / pc.PIPELINE_REL, root=root)
    for chan_dir in reversed(chan_dirs):
        for bdir in sorted(chan_dir.glob("2026-*")):
            hunter = _load(bdir / "01-trend-hunter.json")
            lost = losses(bdir)
            fetch_fail += fetch_failures(bdir)
            if not hunter or not lost:
                continue
            before = batch_time(bdir.name)
            pool = pc.Pool(entries, names,
                           retired=pc.retired_shots(root, channel, before=before),
                           screener=lambda v, r: pc.screen(root, v, r),
                           host_judge=judge)
            viable = [t for t in viable_topics(hunter) if t.get("topic_id")]
            by_id = {t["topic_id"]: t for t in viable}
            for tid, code, _ in lost:
                if tid not in by_id:
                    by_id[tid] = {"topic_id": tid, "title_ref": {"name": tid}}
            cov = pool.coverage(list(by_id.values()), before=before)
            old = sorted(viable, key=lambda t: -score(t))
            new = sorted(viable, key=lambda t: -(pc.rank_score(score(t), cov[t["topic_id"]])
                                                  if score(t) >= 0 else -1))
            for tid, code, where in lost:
                rec = cov[tid]
                if code == "pool_too_thin":
                    had = rec["usable"] is not None and rec["usable"] >= rec["floor"]
                else:
                    had = rec["sources"] >= pc.SOURCE_FLOOR
                ids_new = [t["topic_id"] for t in new]
                ids_old = [t["topic_id"] for t in old]
                rows.append({
                    "batch": f"{chan_dir.name}/{bdir.name}", "topic_id": tid, "code": code,
                    "where": where, "name": (by_id[tid].get("title_ref") or {}).get("name"),
                    "prior_sources": rec["sources"], "prior_usable": rec["usable"],
                    "matched": [(m["video_id"], m["by"]) for m in rec["matched"]],
                    "pool_had_it": had,
                    "rank_old": ids_old.index(tid) + 1 if tid in ids_old else None,
                    "rank_new": ids_new.index(tid) + 1 if tid in ids_new else None,
                    "ranked_out": (tid in ids_new and ids_new.index(tid) >= BATCH_TARGET
                                   and tid in ids_old
                                   and ids_old.index(tid) < BATCH_TARGET),
                })
    return rows, fetch_fail


def main(argv=None):
    from _runlog import factory_root
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--channel", required=True,
                    help="channel id whose frozen batches are replayed (no default)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows, fetch_fail = replay(factory_root(), args.channel)
    if args.json:
        print(json.dumps({"losses": rows, "fetch_failures": fetch_fail}, ensure_ascii=False,
                         indent=2))
        return 0
    for r in rows:
        print(f"{r['batch']:<32} {r['code']:<17} {str(r['name'])[:34]:<34} "
              f"prior src={r['prior_sources']:<2} usable={r['prior_usable']!s:<4} "
              f"had={'Y' if r['pool_had_it'] else '-'} rank {r['rank_old']}->{r['rank_new']}"
              f"{' OUT' if r['ranked_out'] else ''}")
    by = {}
    for r in rows:
        b = by.setdefault(r["code"], [0, 0, 0, 0])
        b[0] += 1
        b[1] += r["pool_had_it"]
        b[2] += r["ranked_out"]
        b[3] += r["pool_had_it"] or r["ranked_out"]
    print(f"\nlosses: {len(rows)}; per-candidate fetch failures (not topic losses): {fetch_fail}")
    for code, (n, had, out, either) in sorted(by.items()):
        print(f"  {code:<17} {n:>3} lost, pool had it {had}, ranked out {out}, removed {either}")
    tot = [sum(b[i] for b in by.values()) for i in range(4)]
    print(f"  {'total':<17} {tot[0]:>3} lost, pool had it {tot[1]}, ranked out {tot[2]}, "
          f"removed {tot[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

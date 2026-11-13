#!/usr/bin/env python3
"""CF-0325 part 2, item 4: how many of the frozen batches' pool losses the
indexer would not have had, had it counted the checked pool sources.

Part 1 (`agents/trend-hunter/scripts/pool_coverage_replay.py`) found the
losses and what the pool held for each topic **as it stood when the batch
started** (index entries fetched before the batch id's time). Its answer is
read here as it is - run in its own process under Trend Hunter's venv, or read
from `--from <its --json output>` - and every lost topic's matched sources are
put through this repo's own `pool_sources.vet()`: the cache (media), Trend
Hunter's work checks (`pool_work_check.py`) and the CF-0299 sieve. What is
left is deduped by the stored CF-0080 fingerprints and measured with
`pool_depth` - the numbers the walk itself would have read.

A loss is **removed** when what the check lets through would have closed it:

  no_second_source / fetch_failed   >= SOURCES_WANTED (2) canonical sources
  pool_too_thin                     >= the depth floor (60) usable shots, the
                                    point at which the walk stops fetching

Caveats, printed with the numbers: the cache is today's (a source deleted
since reads `pool_media_gone` - an undercount, never an overcount), the sieve
flags are today's, and `pool_too_thin` was decided by the writer against real
anchors, so "the pool held 60 usable shots of the work" is the indexer's half
of that loss, not a promise about the writer's.

    .venv/bin/python scripts/pool_sources_replay.py [--from replay.json] [--json]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import ingest_batch  # noqa: E402,F401 - pool_sources' sieve reads it through source_sieve
import pool_depth  # noqa: E402
import pool_sources  # noqa: E402
import source_fingerprint  # noqa: E402
from _channel_ids import ROOT as FACTORY_ROOT  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197

PART1 = pool_sources.TREND_HUNTER_REL / "scripts" / "pool_coverage_replay.py"
REPLAY_TIMEOUT = 280
WANTED = ingest_batch.SOURCES_WANTED


def part1_losses(root, path=None):
    """Part 1's `--json` answer: {"losses": [...], ...}."""
    if path:
        return json.load(open(path))
    cp = subprocess.run([pool_sources.trend_hunter_python(root), str(Path(root) / PART1),
                         "--json"], text=True, capture_output=True, timeout=REPLAY_TIMEOUT)
    if cp.returncode:
        raise SystemExit(f"part 1's replay failed: {cp.stderr.strip()[-400:]}")
    return json.loads(cp.stdout)


def title_ref(root, batch, tid):
    try:
        doc = json.load(open(Path(root) / "pipeline" / batch / "01-trend-hunter.json"))
    except Exception:
        return None
    rows = list(doc.get("topics") or [])
    rows += [r.get("topic") or r for r in doc.get("skipped_topics") or []
             if isinstance(r, dict)]
    for t in rows:
        if t.get("topic_id") == tid and t.get("title_ref"):
            return t["title_ref"]
    return None


def _fingerprint(path):
    """The stored CF-0080 fingerprint, else a fresh one that is **not** saved -
    the replay writes nothing into the pool. None when neither is possible."""
    try:
        return source_fingerprint.load_or_make(path, save=False)
    except Exception:
        return None


def canonical(counted, cache, fingerprint=None):
    """The counted ids minus re-uploads (CF-0080), as the walk would dedup them."""
    fingerprint = fingerprint or _fingerprint
    canon = []
    for r in counted:
        fp = fingerprint(Path(cache) / f"{r['video_id']}.mp4")
        dup = fp is not None and any(
            cfp is not None and source_fingerprint.is_duplicate(
                source_fingerprint.compare(fp, cfp)) for _, cfp in canon)
        if not dup:
            canon.append((r["video_id"], fp))
    return [v for v, _ in canon]


def channel_of(loss, root=None):
    """CF-0631: the loss's batch's channel - `channel` of the loss, else the
    first part of a `<channel>/<batch-id>` batch name; None when neither says.
    Resolved to the current id at the door (CF-0197): a former id names the
    channel it became."""
    if loss.get("channel"):
        return resolve_channel(loss.get("channel"), root=root)
    parts = Path(str(loss.get("batch") or "")).parts
    return resolve_channel(parts[0], root=root) if len(parts) > 1 else None


def replay(losses, root, cache, checker=None, judge=pool_sources.sieve_verdict,
           depth=None, fingerprint=None, floor=pool_depth.POOL_DEPTH_FLOOR):
    depth = depth or (lambda tid, vids: pool_depth.topic_depth(tid, vids, cache=cache))
    rows = []
    by_channel = {}
    for i, loss in enumerate(losses):
        ref = title_ref(root, loss["batch"], loss["topic_id"]) or {"name": loss.get("name")}
        by_channel.setdefault(channel_of(loss, root), []).append(
            {"topic_id": f"{i}", "title_ref": ref,
             "pool": {"matched": [{"video_id": m[0], "by": m[1]}
                                  for m in loss.get("matched") or []]}})
    vetted = {}
    for channel, topics in by_channel.items():      # CF-0631: each with its channel's list
        vetted.update(pool_sources.vet(topics, cache, root=root, checker=checker, judge=judge,
                                       log=lambda *a, **k: None, channel=channel))
    for i, loss in enumerate(losses):
        v = vetted.get(f"{i}") or {"counted": [], "refused": [], "matched": 0}
        def closes(counted):
            canon = canonical(counted, cache, fingerprint)
            d = depth(loss["topic_id"], canon) if canon else None
            usable = d.usable if d is not None and d.measured else (0 if d is None else None)
            if loss["code"] == "pool_too_thin":
                return canon, usable, usable is not None and usable >= floor
            return canon, usable, len(canon) >= WANTED

        canon, usable, removed = closes(v["counted"])
        # The strict reading: a source the CF-0299 sieve has not answered for
        # yet is left out (a live run answers it in the batch's sieve pass,
        # and may refuse it there - wS6wtevVlmc is such a source).
        sieved = [r for r in v["counted"] if r.get("sieve") == "kept"]
        _, usable_strict, removed_strict = closes(sieved)
        rows.append({
            "batch": loss["batch"], "topic_id": loss["topic_id"], "code": loss["code"],
            "name": loss.get("name"),
            "part1_pool_had_it": loss.get("pool_had_it"),
            "matched": len(loss.get("matched") or []),
            "counted": [r["video_id"] for r in v["counted"]],
            "canonical": canon, "usable": usable,
            "refused": [{"video_id": r["video_id"], "reason_code": r["reason_code"],
                         "check": r["check"], "title": r.get("title")}
                        for r in v["refused"]],
            "removed": removed,
            "unsieved": [r["video_id"] for r in v["counted"] if r.get("sieve") != "kept"],
            "usable_strict": usable_strict,
            "removed_strict": removed_strict,
        })
    return rows


def summary_line(code, b):
    return (f"  {code:<17} {b[0]:>3} lost, part 1 pool had it {b[1]}, removed "
            f"with the check {b[2]} (only sieve-cleared sources: {b[3]})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", help="part 1's saved --json output")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = FACTORY_ROOT
    cache = root / "shared" / "footage"
    if not Path(pool_depth.VIDEO_EDITOR_SCRIPTS).exists():
        # run from a worktree: the Video Editor sits beside the main checkout
        pool_depth.VIDEO_EDITOR_SCRIPTS = root / "agents" / "video-editor" / "scripts"
    losses = [r for r in part1_losses(root, args.source).get("losses") or []]
    rows = replay(losses, root, cache)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for r in rows:
        print(f"{r['batch']:<30} {r['code']:<17} {str(r['name'])[:30]:<30} "
              f"matched {r['matched']:<2} counted {len(r['counted']):<2} "
              f"canon {len(r['canonical']):<2} usable {r['usable']!s:<4} "
              f"part1 {'Y' if r['part1_pool_had_it'] else '-'} "
              f"removed {'Y' if r['removed'] else '-'}"
              f"{'' if r['removed_strict'] == r['removed'] else ' (strict -)'}")
        if r["unsieved"]:
            print(f"      counted, not sieved yet: {', '.join(r['unsieved'])}")
        for x in r["refused"]:
            print(f"      not counted {x['video_id']} {x['reason_code']} ({x['check']}): "
                  f"{str(x['title'])[:70]}")
    by = {}
    for r in rows:
        b = by.setdefault(r["code"], [0, 0, 0, 0])
        b[0] += 1
        b[1] += bool(r["part1_pool_had_it"])
        b[2] += r["removed"]
        b[3] += r["removed_strict"]
    print(f"\nlosses {len(rows)}")
    tot = [0, 0, 0, 0]
    for code, b in sorted(by.items()):
        tot = [x + y for x, y in zip(tot, b)]
        print(summary_line(code, b))
    print(summary_line("total", tot))
    print("caveats: today's cache and sieve flags (a source deleted since is "
          "pool_media_gone - an undercount); pool_too_thin is the indexer's half "
          "of that loss (60 usable shots), the writer decided it against anchors")
    return 0


if __name__ == "__main__":
    sys.exit(main())

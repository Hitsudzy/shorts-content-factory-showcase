#!/usr/bin/env python3
"""CF-0316: where the watchdog's ceilings come from.

Reads frozen `RUN_EVENTS.jsonl` of the runs CF-0112 measured and prints the
distribution the ceilings in `shared/runlog/watchdog.py` are derived from.
Runs nothing, writes nothing.

The watchdog does not time an operation, it times its **silence**: the stretch
with no event of the operation's own subtree. So the number that matters here
is not "how long does an operation take" (52 minutes of honest indexing is
normal) but "how long does an honest operation stay quiet" - a leaf binary
call is the only thing that can hold the journal silent, so the worst honest
silence is the worst honest leaf.

    python3 scripts/watchdog_threshold.py [BATCH_DIR ...]

CF-0331 correction: `shot-full-frame` stopped launching one ffmpeg per sampled
frame (one call per shot now), p50 7.53 s -> 1.38 s, 5.24x. Every silence
window that is a `shot-full-frame` call is therefore divided by 5.24 in the
"after CF-0331" column; nothing else in the stage changed.
"""
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FULL_FRAME_SPEEDUP = 5.24            # CF-0331, measured with the CF-0112 reader
DEFAULT_RUNS = (
    "pipeline/example-film/2026-09-22T1001Z",
    "pipeline/example-film/2026-09-21T1541Z",
    "pipeline/example-film/2026-09-21T0358Z",
)
# the ffmpeg command shapes CF-0331 touched (same needles indexer_cost.py uses)
FULL_FRAME_NEEDLES = ("-vf crop=", "select='gte(t,")


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _is_full_frame(e):
    if (e.get("tool") or "") != "ffmpeg":
        return False
    joined = " ".join(e.get("argv") or [])
    return any(n in joined for n in FULL_FRAME_NEEDLES)


def load(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = _ts(e.get("ts"))
            if t is not None:
                e["_t"] = t
                out.append(e)
    out.sort(key=lambda e: e["_t"])
    return out


def operations(events):
    """Every script event as one operation, with the silence windows inside it.

    A window is (seconds, kind, tool): kind is "full-frame" when the window is
    one `shot-full-frame` call, else "other".
    """
    parent = {}
    for e in events:
        if e.get("id"):
            parent.setdefault(e["id"], e.get("parent"))

    ops = []
    open_scripts = {}
    for e in events:
        if e.get("kind") != "script":
            continue
        if e.get("status") == "start":
            open_scripts[e["id"]] = e
        elif e["id"] in open_scripts:
            s = open_scripts.pop(e["id"])
            ops.append({"id": e["id"], "stage": e.get("stage"), "step": e.get("step"),
                        "name": e.get("name"), "video": e.get("video"),
                        "t0": s["_t"], "t1": e["_t"], "dur": e["_t"] - s["_t"]})
    by_id = {o["id"]: o for o in ops}
    # attach every event to the innermost operation it hangs under
    marks = collections.defaultdict(list)
    for e in events:
        if e.get("kind") not in ("script", "child"):
            continue                # samples are not a sign of an operation's life (CF-0339)
        chain, eid, seen = [], e.get("parent"), set()
        while eid and eid not in seen:
            seen.add(eid)
            if eid in by_id:
                chain.append(eid)
            eid = parent.get(eid)
        if chain:
            marks[chain[0]].append(e)
    for o in ops:
        pts = sorted(marks.get(o["id"], []), key=lambda e: e["_t"])
        prev, prev_e = o["t0"], None
        gaps = []
        for e in pts:
            g = e["_t"] - prev
            if g > 0:
                same_call = (prev_e is not None and prev_e.get("status") == "start"
                             and e.get("id") == prev_e.get("id"))
                kind = "full-frame" if (same_call and _is_full_frame(prev_e)) else "other"
                gaps.append((g, kind, (prev_e or {}).get("tool")))
            prev, prev_e = e["_t"], e
        tail = o["t1"] - prev
        if tail > 0:
            gaps.append((tail, "other", None))
        o["gaps"] = gaps
        o["events"] = len(pts)
        o["silence"] = max((g for g, _, _ in gaps), default=o["dur"])
        o["silence_after"] = max((g / FULL_FRAME_SPEEDUP if k == "full-frame" else g
                                  for g, k, _ in gaps), default=o["dur"])
    return ops


def _p(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def _hms(s):
    s = int(round(s))
    return f"{s // 3600}h{(s % 3600) // 60:02d}m{s % 60:02d}s" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    dirs = [Path(a) for a in argv] or [root / d for d in DEFAULT_RUNS]
    ops = []
    for d in dirs:
        p = Path(d) / "RUN_EVENTS.jsonl"
        if not p.exists():
            print(f"skip {d}: no RUN_EVENTS.jsonl")
            continue
        ops += operations(load(p))
    if not ops:
        print("no material")
        return 1
    print(f"{len(ops)} operations in {len(dirs)} run(s)\n")
    print(f"{'stage/step':38s} {'n':>4s} {'dur p50':>9s} {'dur max':>9s} "
          f"{'sil p50':>8s} {'sil p90':>8s} {'sil max':>8s} {'sil max 0331':>13s}")
    groups = collections.defaultdict(list)
    for o in ops:
        groups[f"{o['stage']}/{o['step']}"].append(o)
    for k in sorted(groups, key=lambda k: -max(o["silence"] for o in groups[k])):
        g = groups[k]
        sil = [o["silence"] for o in g]
        aft = [o["silence_after"] for o in g]
        dur = [o["dur"] for o in g]
        print(f"{k:38s} {len(g):4d} {_hms(_p(dur, .5)):>9s} {_hms(max(dur)):>9s} "
              f"{_p(sil, .5):7.1f}s {_p(sil, .9):7.1f}s {max(sil):7.1f}s {max(aft):12.1f}s")
    print("\nworst honest silences (top 12):")
    for o in sorted(ops, key=lambda o: -o["silence"])[:12]:
        worst = (0, "other", None)
        for g in o["gaps"]:
            if g[0] == o["silence"]:
                worst = g
                break
        print(f"  {o['silence']:8.1f}s ({worst[1]}, before it: {worst[2] or 'nothing'}) "
              f"in {o['stage']}/{o['step']} {o['video'] or '-'} "
              f"dur={_hms(o['dur'])} events={o['events']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CF-0122/CF-0155 instrument: how resolve_anchors.usable()'s verdict moves
ALONG a cut clip, and what the gate's redesigns would say about it.

Written for CF-0122, where usable() probed two frames - 0.5s and seconds/2 -
and the second one moved with the block length the rhythm asked for. On
SJVmeJaS44s shot 1 a 6.25s block passed and a 5.41s block of the same clip
failed (RUN_LOG 2026-09-03T2037Z:27).

CF-0155 changed *which window* a frame is judged against, which is the axis
this script now measures on both sides. It cuts the shot the way cut() does,
extracts a frame every --step seconds in ONE ffmpeg pass, and gates every
frame twice:

  own   - qc_asset.py as CF-0122 measured it: each frame against its own best
          9:16 crop. The number the gate used to read, and which no render
          ever uses.
  plan  - qc_asset.py --window: every frame against the window
          build_render_plan.py will actually frame this clip with, taken from
          the frame at PROBE_OFFSET exactly as the planner takes it (CF-0155).

Then, from those two profiles:

  old gate  - the verdict before CF-0155 at each --length L: own-window
              verdicts at 0.5 AND L/2
  new gate  - the verdict after CF-0155: plan-window verdicts at all four
              resolve_anchors.probe_offsets(L), every one of them passing
  passing   - how many of those four passed, which is the number CF-0156's
              aggregation rule (strict vs a tolerance) has to be chosen on
  cand1     - CF-0122's rejected candidate 1, kept for continuity: fixed
              25/50/75% points of the whole shot, all pass

Measurements are written next to the clips as JSON. Nothing here changes a
verdict. Vision costs are real: budget ~0.6s per sampled frame per profile on
a warm worker plus the cut itself (2.7-9s per shot).

Usage (one shot):
    measure_probe_profile.py --source shared/footage/SJVmeJaS44s.mp4 --shot 1
Usage (survey: first eligible live shot of every index in the pool):
    measure_probe_profile.py --pool shared/footage --limit 20
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import resolve_anchors as ra  # noqa: E402
from common import (FFMPEG, MIN_COVERAGE, MIN_SHORT_SIDE,  # noqa: E402
                    SIBLING_SCRIPT_TIMEOUT_SECONDS, media_timeout)

LENGTHS = (2.68, 4.17, 5.41, 6.25, 7.2)   # the RUN_LOG:27 block lengths
MAX_BLACK = ra.MAX_BLACK_CLIPS             # what resolve_anchors.py hands usable()


def verdict_at(rows, t):
    return min(rows, key=lambda r: abs(r["t"] - t))


def gate_frame(frame, card, applied, window=None, window_zoom=1.0):
    """One frame through the exact qc_asset.py call the gate makes, optionally
    against a given window (CF-0155). Returns the parsed verdict or None."""
    o = subprocess.run(ra.qc_command(frame, MIN_SHORT_SIDE, MIN_COVERAGE, MAX_BLACK,
                                     card, applied, window=window,
                                     window_zoom=window_zoom),
                       capture_output=True, text=True,
                       timeout=SIBLING_SCRIPT_TIMEOUT_SECONDS)  # CF-0135
    return json.loads(o.stdout) if o.stdout.strip() else None


def profile(source, shot, out_dir, step, cap, card=False):
    """Cut `shot` of `source` (head-cut, capped at `cap` seconds), sample it
    every `step` seconds, and gate every sample twice - against its own best
    crop and against the window the planner will frame the clip with.
    Returns (rows, timings)."""
    dur = min(cap, shot["end"] - shot["start"])
    clip = out_dir / f"{Path(source).stem}_s{shot['index']:03d}.mp4"
    t0 = time.monotonic()
    applied = ra.cut(source, shot["start"], dur, str(clip),
                     shot.get("crop_bottom_cached", 0.0), card=card)
    t_cut = time.monotonic() - t0
    if applied is None:
        return None, {"cut": t_cut}
    frames = out_dir / (clip.stem + "_frames")
    frames.mkdir(exist_ok=True)
    for f in frames.glob("*.png"):
        f.unlink()
    t0 = time.monotonic()
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", "-i", str(clip),
                    "-vf", f"fps=1/{step}", str(frames / "f%04d.png")],
                   capture_output=True, timeout=media_timeout(dur))  # CF-0135
    t_extract = time.monotonic() - t0
    files = sorted(frames.glob("f*.png"))

    # The window the render will use: the planner's own frame (PROBE_OFFSET),
    # pointed at itself, exactly as resolve_anchors.usable() takes it.
    t0 = time.monotonic()
    anchor = min(range(len(files)), key=lambda i: abs(i * step - ra.PROBE_OFFSET))
    anchor_verdict = gate_frame(files[anchor], card, applied, window="self")
    window = (anchor_verdict or {}).get("coverage_window")
    focus = ((window["focus"]["x"], window["focus"]["y"]) if window else None)
    zoom = window["zoom"] if window else 1.0

    rows = []
    for i, f in enumerate(files):
        own = gate_frame(f, card, applied)
        plan = (gate_frame(f, card, applied, window=focus, window_zoom=zoom)
                if focus else None)
        if not own:
            continue
        rows.append({"t": round(i * step, 2),
                     "ok": own["usable"], "cov": own.get("roi_coverage"),
                     "roi": own.get("roi_source"), "failed": own.get("failed"),
                     "plan_ok": (plan or {}).get("usable"),
                     "plan_cov": (plan or {}).get("roi_coverage"),
                     "plan_failed": (plan or {}).get("failed"),
                     "luma": own.get("mean_luma"), "black": own.get("black_fraction")})
    t_qc = time.monotonic() - t0
    timings = {"cut": round(t_cut, 2), "extract": round(t_extract, 2),
               "qc_total": round(t_qc, 2), "frames": len(rows), "clip_seconds": round(dur, 2)}
    json.dump({"source": source, "shot": shot["index"], "start": shot["start"], "dur": dur,
               "step": step, "window": window, "timings": timings, "rows": rows},
              open(out_dir / (clip.stem + ".json"), "w"), indent=1)
    return rows, timings


def report(name, rows, timings, lengths, tolerate):
    dur = timings["clip_seconds"]
    own_pass = sum(r["ok"] for r in rows)
    plan_pass = sum(bool(r["plan_ok"]) for r in rows)
    roi_flips = sum(1 for a, b in zip(rows, rows[1:]) if a["roi"] != b["roi"])
    own_flips = sum(1 for a, b in zip(rows, rows[1:]) if a["ok"] != b["ok"])
    plan_flips = sum(1 for a, b in zip(rows, rows[1:]) if a["plan_ok"] != b["plan_ok"])
    print(f"{name} clip={dur:.1f}s cut={timings['cut']:.1f}s extract={timings['extract']:.1f}s "
          f"qc={timings['qc_total']:.1f}s/{len(rows)}fr x2")
    print(f"   own  pass={own_pass}/{len(rows)} verdict-flips={own_flips} "
          f"roi-flips={roi_flips}: " + " ".join(
              f"{r['t']:.1f}:{'P' if r['ok'] else 'F'}{(r['roi'] or '?')[0]}" for r in rows))
    print(f"   plan pass={plan_pass}/{len(rows)} verdict-flips={plan_flips}"
          f"{' ' * 13}: " + " ".join(
              f"{r['t']:.1f}:{'P' if r['plan_ok'] else 'F'}{(r['roi'] or '?')[0]}"
              for r in rows))
    ls = [L for L in lengths if L <= dur]
    old = {L: verdict_at(rows, 0.5)["ok"] and verdict_at(rows, max(0.6, L / 2))["ok"]
           for L in ls}
    probes = {L: [verdict_at(rows, t) for t in ra.probe_offsets(L) if t <= dur] for L in ls}
    new = {L: all(r["plan_ok"] for r in probes[L]) for L in ls}
    kept = {L: (sum(bool(r["plan_ok"]) for r in probes[L]), len(probes[L])) for L in ls}
    c1 = [verdict_at(rows, dur * q)["ok"] for q in (0.25, 0.5, 0.75)]
    c2q = {L: (sum(bool(r["plan_ok"]) for r in probes[L])
               >= tolerate * len(probes[L])) for L in ls}
    pf = lambda d: " ".join(f"{L}:{'P' if v else 'F'}" for L, v in d.items())  # noqa: E731
    print(f"   old gate (0.5 & L/2, own window):   {pf(old)}")
    print(f"   new gate (4 probes, plan window):   {pf(new)}")
    print(f"   probes passing per L:               "
          + " ".join(f"{L}:{a}/{b}" for L, (a, b) in kept.items()))
    print(f"   new gate @{tolerate:.2f} tolerance:        {pf(c2q)}")
    print(f"   cand1(25/50/75%, own window):       "
          f"{' '.join('P' if v else 'F' for v in c1)} -> {'P' if all(c1) else 'F'}",
          flush=True)


def eligible(shot):
    """A live shot the pre-filter would let through - the ones usable() is
    actually asked about."""
    uc = shot.get("usable_cached") or {}
    return (not shot.get("is_card")
            and uc.get("roi_coverage", 0) >= MIN_COVERAGE
            and uc.get("mean_luma", 0) >= 28
            and uc.get("short_side", 0) >= MIN_SHORT_SIDE)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--source", help="one source .mp4 (its .shots.json sits next to it)")
    p.add_argument("--shot", type=int, help="shot index within --source")
    p.add_argument("--pool", help="footage dir: first eligible live shot >= --min-seconds "
                                  "of every index")
    p.add_argument("--limit", type=int, default=20, help="pool survey: at most this many shots")
    p.add_argument("--min-seconds", type=float, default=5.0)
    p.add_argument("--step", type=float, default=0.5, help="seconds between sampled frames")
    p.add_argument("--cap", type=float, default=12.0, help="cut at most this much of a shot")
    p.add_argument("--lengths", type=float, nargs="*", default=list(LENGTHS),
                   help="block lengths to evaluate the rules at")
    p.add_argument("--tolerate", type=float, default=0.75,
                   help="cand2@q: share of sampled frames in [0, L] that must pass")
    p.add_argument("--out", default="/tmp/cf0122-probe-profile")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    if args.source:
        if args.shot is None:
            p.error("--source needs --shot")
        d = json.load(open(Path(args.source).with_suffix(".shots.json")))
        shot = next(s for s in d["shots"] if s["index"] == args.shot)
        jobs.append((args.source, shot))
    elif args.pool:
        for sj in sorted(Path(args.pool).glob("*.shots.json")):
            d = json.load(open(sj))
            for s in d["shots"]:
                if eligible(s) and s["end"] - s["start"] >= args.min_seconds:
                    jobs.append((str(sj.with_name(sj.name.replace(".shots.json", ".mp4"))), s))
                    break
            if len(jobs) >= args.limit:
                break
    else:
        p.error("give --source/--shot or --pool")

    for source, shot in jobs:
        name = f"{Path(source).stem} s{shot['index']}"
        rows, timings = profile(source, shot, out, args.step, args.cap,
                                card=bool(shot.get("is_card")))
        if not rows:
            print(f"{name}: cut failed or no verdicts ({timings})")
            continue
        report(name, rows, timings, args.lengths, args.tolerate)


if __name__ == "__main__":
    main()

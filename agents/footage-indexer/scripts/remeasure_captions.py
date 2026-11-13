#!/usr/bin/env python3
"""Re-take the cached caption-band measurement over an index that already exists.

CF-0055's other half, and the exact counterpart of `remeasure_usability.py`.
`caption_cache.py` makes a `crop_bottom_cached` measured by older code visible
and stops the pipeline believing it; this is how the pool is brought back into
agreement with the code, without paying for a full re-index (shot boundaries,
CLIP embeddings, hand-written descriptions, contact sheets, card flags and the
usability cache are all untouched - none of them depend on caption detection).

It is not optional in the way `remeasure_usability.py` is. A stale usability
cache costs speed, so the pipeline can go on without a remeasure; a stale
caption crop cuts real clips in the wrong place, so the pipeline refuses to
start and this command is the only way out of that refusal. It is still a
separate command, run by hand, printing what changed: re-measuring alters the
geometry of clips in every video built from these sources from then on, which
is something to look at, not a cache-warming chore.

Usage:
    remeasure_captions.py <video-or-shots.json> [more...] [--dry-run]
                          [--include-uncached] [--jobs N]

`--dry-run` measures and reports without writing. By default only shots that
already carry a `crop_bottom_cached` are re-measured - that is what the
refusal is about, and it is what "re-measure" means. `--include-uncached` also
gives a first cached crop to shots that have none (indexes built before
CF-0029, where `resolve_anchors.cut()` falls back to a fresh `--auto-crop`
today): correct, and a real change to how those videos are cut, so it is asked
for explicitly rather than done in passing.

`--jobs N` re-measures N sources at a time in child processes of this script
(CF-0151). The whole pool is ~8.9 hours of ffmpeg seeks serially, which is a
number that keeps a pool stale rather than a command anyone runs; see MAX_JOBS
below for what divides and what does not.
"""
import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import caption_cache  # noqa: E402
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
import shot_schema  # noqa: E402 - CF-0281: the index is rewritten whole or not at all
from common import FFPROBE, MIN_SHORT_SIDE  # noqa: E402 - on sys.path via caption_cache

# A caption crop that moves by less than this is not worth a line of output:
# it is under a pixel of a 1080-high source and cannot change any gate.
REPORT_EPS = 0.0005

# CF-0819: the clock the budget is read on (a test steps it by hand).
_now = time.monotonic


def targets(arg):
    """Accept either the video or its index; return (video, shots.json)."""
    path = Path(arg)
    if path.suffix == ".json":
        shots_json = path
        data = json.load(open(shots_json))
        video = Path(data.get("source", "")) if data.get("source") else None
        if video is None or not video.exists():
            video = Path(str(shots_json).replace(".shots.json", ".mp4"))
    else:
        video = path
        shots_json = video.with_suffix(".shots.json")
    return video, shots_json


def source_height(video):
    """The source's own frame height, so a change in the crop fraction can be
    reported in the unit that actually decides anything: pixels left.

    Height rather than "short side" on purpose - these sources are landscape,
    the crop only ever takes frame off the bottom, and it is the height that
    the resolution floor then bites on (CF-0053: a 0.3272 crop took a 720-high
    card down to 484 and the clip failed `usable()` on resolution alone).
    """
    out = runlog.run_child(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "default=nw=1:nk=1", str(video)],
        tool="ffprobe", capture_output=True, text=True)
    try:
        return int(out.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def kept_pixels(height, crop_bottom):
    """What prepare_clip.py's own crop filter leaves, in pixels."""
    if not height:
        return None
    return int((height * (1 - crop_bottom)) // 2) * 2


def remeasure(video, shots_json, args):
    data = json.load(open(shots_json))
    shots = data["shots"]
    height = source_height(video)
    moved, appeared, vanished, failed, floor_flips = [], 0, 0, 0, []
    measured = 0
    # CF-0819: --stale-only, --budget-seconds (args.deadline on _now()),
    # --set-aside-rest. A shot not started before the deadline is not
    # measured; with --set-aside-rest its stale crop is set aside instead.
    stale_only = getattr(args, "stale_only", False)
    deadline = getattr(args, "deadline", None)
    over_budget, put_aside = [], 0

    for shot in shots:
        had = caption_cache.VALUE_KEY in shot
        if not had and not args.include_uncached:
            continue
        if had and stale_only and caption_cache.stale_stamp(shot) is None:
            continue
        if deadline is not None and _now() >= deadline:
            if had:
                over_budget.append(shot)
            continue
        before = shot.get(caption_cache.VALUE_KEY)
        try:
            caption_cache.measure(shot, video)
        except Exception as e:
            failed += 1
            print(f"  shot {shot.get('index')}: probe failed ({e}), "
                  f"cache left as it was", file=sys.stderr)
            continue
        measured += 1
        after = shot[caption_cache.VALUE_KEY]
        if not had:
            continue
        if abs(after - before) < REPORT_EPS:
            continue
        moved.append((shot, before, after))
        if before == 0.0 and after > 0.0:
            appeared += 1
        elif before > 0.0 and after == 0.0:
            vanished += 1
        # The one consequence that is not a matter of degree: whether the clip
        # cut from this shot still clears the resolution floor at all.
        was, now = kept_pixels(height, before), kept_pixels(height, after)
        if was is not None and (was >= MIN_SHORT_SIDE) != (now >= MIN_SHORT_SIDE):
            floor_flips.append((shot, was, now))

    for shot, before, after in moved:
        card = " [is_card]" if shot.get("is_card") else ""
        px = ""
        if height:
            px = (f"  ({kept_pixels(height, before)} -> "
                  f"{kept_pixels(height, after)} px of {height})")
        print(f"  shot {shot.get('index')}{card}: crop {before} -> {after}{px}")
    for shot, was, now in floor_flips:
        print(f"  shot {shot.get('index')}: crosses the {MIN_SHORT_SIDE}px floor "
              f"({was} -> {now}) - this changes whether usable() takes it at all")

    # An index with nothing to re-measure (no cached crop on any shot, and
    # --include-uncached not asked for) is left alone rather than rewritten
    # byte-identically: "which indexes did this run touch" should stay a
    # question the filesystem can answer.
    if getattr(args, "set_aside_rest", False):
        put_aside = sum(caption_cache.set_aside_shot(s) for s in over_budget)
    if over_budget:
        print(f"  {len(over_budget)} shot(s) past the budget, not measured"
              + (f" - {put_aside} stale crop(s) set aside (fresh --auto-crop at cut)"
                 if put_aside else " - stale ones stay stale"))
    if not args.dry_run and (measured or put_aside):
        # CF-0281: whole or not at all - a kill inside this rewrite would
        # otherwise destroy an index that was already good.
        shot_schema.write_index(shots_json, data)

    return {"shots": len(shots), "measured": measured, "moved": len(moved),
            "appeared": appeared, "vanished": vanished,
            "floor_flips": len(floor_flips), "failures": failed,
            "over_budget": len(over_budget), "set_aside": put_aside}


# Why this script can be run several sources at a time (CF-0151).
#
# Measured on this pool on 2026-09-14, one shot of `pOY-Q5DXfcI`: the 8-sample
# scan costs 27.4 s of ffmpeg frame grabs and 5.4 s of Vision. The grabs are
# eight separate `ffmpeg -ss T -i src -frames:v 1` calls (detect_text_band.
# sample_frames()), about 3.4 s each, and a raw ffmpeg seek on that file
# measures 2.95 s on its own - so the time is ffmpeg's, not ours, and it is
# spent in a child process that holds no lock of ours. Serially that is ~33 s
# a shot; the 980 stale shots CF-0151 found in the pool are ~8.9 hours, which
# is not a command anyone runs, which is how a pool stays stale.
#
# The one shared thing is the warm Vision worker (one process on a Unix
# socket), and that is the 5.4 s, not the 27.4 s. At N processes the ffmpeg
# time divides and the Vision time does not, so the floor for 980 shots is
# ~88 minutes however wide this is opened. Past ~6 jobs the machine (12 cores,
# ffmpeg already threading) stops giving the division back, and the ceiling
# below says so rather than letting `-j 32` thrash.
#
# CF-0225 then removed the divisible half, and that changes what this ceiling
# is for. `sample_frames()` now takes the eight frames in one pass, so the
# 27.4 s is gone and what remains is essentially the Vision worker. Measured
# 2026-09-14 on the full pool (CF-0151, second pass): 1411 shots at `--jobs 6
# --include-uncached` took 51.7 minutes, i.e. **2.20 s a shot** - against
# 2.45 s a shot measured serially on one source the same day. Through the run
# only 2-4 ffmpeg processes were ever alive while the Vision worker held
# ~0.8 of a core.
#
# So `--jobs` is now worth roughly nothing and MAX_JOBS stays at 6 only as a
# guard rail, not as a saving. It is deliberately not raised: more processes
# queue harder on the same single worker. The next real saving is inside the
# Vision worker (batching, or more than one of them), and until somebody takes
# that on, the honest figure to quote for a full-pool re-measure is ~50
# minutes at any --jobs from 1 to 6.
MAX_JOBS = 6
# A child's own ceiling (CF-0128: no external call without one). 180 s a shot
# is 5.5x the measured 33 s, plus a base for interpreter start and the first
# Vision warm-up, which the cold run measured at ~35 s.
CHILD_BASE_SECONDS = 120
CHILD_SECONDS_PER_SHOT = 180
SUMMARY_PREFIX = "SUMMARY-JSON "

TOTAL_KEYS = ("shots", "measured", "moved", "appeared", "vanished",
              "floor_flips", "failures", "over_budget", "set_aside")


def plan(target_args):
    """(video, shots.json, shot count) per target that can actually be
    re-measured. Skips are reported here, once, so that both the serial and
    the parallel path report them identically and neither hands a child a
    source it already knows is missing."""
    for arg in target_args:
        video, shots_json = targets(arg)
        if not shots_json.exists():
            print(f"{shots_json}: no index, skipped", file=sys.stderr)
            continue
        if not video.exists():
            print(f"{video}: source missing, cannot re-measure {shots_json.name}",
                  file=sys.stderr)
            continue
        try:
            n = len(json.load(open(shots_json)).get("shots", []))
        except (OSError, ValueError) as e:
            print(f"{shots_json}: unreadable ({e}), skipped", file=sys.stderr)
            continue
        yield video, shots_json, n


def _report_one(shots_json, result):
    print(f"  {result['measured']} of {result['shots']} shots re-measured, "
          f"{result['moved']} moved "
          f"({result['appeared']} newly cropped, {result['vanished']} no "
          f"longer cropped, {result['floor_flips']} crossing the "
          f"{MIN_SHORT_SIDE}px floor)"
          + (f", {result['failures']} probe failures"
             if result["failures"] else ""))


def run_serial(work, args):
    total = dict.fromkeys(TOTAL_KEYS, 0)
    for video, shots_json, _ in work:
        print(f"{shots_json.name}:")
        # CF-0107: one nested event per source; the per-shot `vision` children
        # come from caption_cache.measure().
        with runlog.run("footage-indexer", "remeasure-captions", video=video.stem,
                        name="remeasure_captions.py"):
            result = remeasure(video, shots_json, args)
        for k in total:
            total[k] += result[k]
        _report_one(shots_json, result)
    return total


def _chunks(work, n):
    """`n` lists of indexes, balanced by shot count rather than by file count.

    The pool's indexes run from 1 shot to 60, so handing out every n-th file
    would leave one process with `ZZ_urA56pJE` (60 shots, ~33 min) while the
    others finished in three minutes and the wall clock stayed the longest
    chunk's. Longest-first into the currently-lightest bucket - the greedy
    rule, which is enough when the item sizes are known up front.
    """
    buckets = [[] for _ in range(n)]
    load = [0] * n
    for item in sorted(work, key=lambda w: -w[2]):
        i = load.index(min(load))
        buckets[i].append(item)
        load[i] += item[2]
    return [b for b in buckets if b]


def run_parallel(work, args):
    """Re-measure `work` in up to args.jobs child processes of this script.

    Child *processes of this same script*, rather than a thread or process
    pool inside this one, on purpose: the unit of work is one index, a child
    opens the same index nobody else opens and writes only that file, and a
    child that dies takes nothing with it but its own chunk. It also means the
    thing being parallelised is the exact serial path, flags and all, so there
    is no second implementation of the measurement to drift from the first -
    which is the failure this whole cache mechanism exists to catch.
    """
    jobs = min(args.jobs, MAX_JOBS, len(work))
    if args.jobs > MAX_JOBS:
        print(f"--jobs {args.jobs} capped at {MAX_JOBS} (see MAX_JOBS: past "
              f"this the warm Vision worker, not ffmpeg, is the floor)",
              file=sys.stderr)
    buckets = _chunks(work, jobs)
    flags = ([] + (["--dry-run"] if args.dry_run else [])
             + (["--include-uncached"] if args.include_uncached else [])
             + (["--stale-only"] if args.stale_only else [])
             + (["--set-aside-rest"] if args.set_aside_rest else []))
    print(f"{len(work)} sources ({sum(w[2] for w in work)} shots) over "
          f"{len(buckets)} processes")

    def one(bucket):
        budget = []
        ceiling = CHILD_BASE_SECONDS + CHILD_SECONDS_PER_SHOT * sum(w[2] for w in bucket)
        if args.deadline is not None:
            # CF-0819: the child gets what is left of the budget, and its
            # ceiling is that plus one shot in flight - not hours of shots.
            left = max(0.0, args.deadline - _now())
            budget = ["--budget-seconds", f"{left:.0f}"]
            ceiling = min(ceiling, left + CHILD_BASE_SECONDS + CHILD_SECONDS_PER_SHOT)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--summary-json",
               *flags, *budget, *[str(sj) for _, sj, _ in bucket]]
        return runlog.run_child(cmd, tool="remeasure-captions", step="chunk",
                                capture_output=True, text=True, timeout=ceiling)

    total = dict.fromkeys(TOTAL_KEYS, 0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(buckets)) as pool:
        futures = {pool.submit(one, b): b for b in buckets}
        for fut in concurrent.futures.as_completed(futures):
            bucket = futures[fut]
            names = ", ".join(sj.name for _, sj, _ in bucket)
            try:
                out = fut.result()
            except subprocess.TimeoutExpired:
                print(f"chunk [{names}] hit its ceiling and was killed - those "
                      f"indexes keep their old values and stay stale",
                      file=sys.stderr)
                continue
            for line in out.stdout.splitlines():
                if line.startswith(SUMMARY_PREFIX):
                    for k, v in json.loads(line[len(SUMMARY_PREFIX):]).items():
                        total[k] += v
                elif not line.startswith("caption-band code fingerprint:"):
                    print(line)
            if out.stderr:
                sys.stderr.write(out.stderr)
            if out.returncode != 0:
                print(f"chunk [{names}] exited {out.returncode} - anything it "
                      f"did not reach stays stale", file=sys.stderr)
    return total


def main():
    p = argparse.ArgumentParser()
    p.add_argument("targets", nargs="+", help="video files or their .shots.json")
    p.add_argument("--dry-run", action="store_true",
                   help="measure and report, write nothing")
    p.add_argument("--include-uncached", action="store_true",
                   help="also give a first cached crop to shots that have none "
                        "(pre-CF-0029 indexes) - a real change to how those "
                        "videos are cut, not a re-measure")
    p.add_argument("--jobs", "-j", type=int, default=1, metavar="N",
                   help="re-measure N sources at a time in separate processes "
                        f"(default 1, ceiling {MAX_JOBS}). No source is ever "
                        "handled by two of them, so nothing races: the unit of "
                        "work is a whole index and each process writes only its "
                        "own. See MAX_JOBS for why this exists and where it "
                        "stops paying.")
    p.add_argument("--stale-only", action="store_true",
                   help="CF-0819: re-measure only the shots whose cached crop "
                        "reads stale, not every cached crop of the index")
    p.add_argument("--budget-seconds", type=float, default=None, metavar="S",
                   help="CF-0819: start no shot after S seconds; the rest is "
                        "left as it is (or set aside with --set-aside-rest)")
    p.add_argument("--set-aside-rest", action="store_true",
                   help="CF-0819: a stale crop the budget did not reach is set "
                        "aside (caption_cache.SET_ASIDE_KEY) - the cut gives "
                        "that shot a fresh --auto-crop; the pool reads current")
    p.add_argument("--summary-json", action="store_true",
                   help=argparse.SUPPRESS)  # internal: how a child reports back
    args = p.parse_args()
    if args.jobs < 1:
        p.error("--jobs must be at least 1")
    if args.budget_seconds is not None and args.budget_seconds < 0:
        p.error("--budget-seconds must be 0 or more")
    args.deadline = (None if args.budget_seconds is None
                     else _now() + args.budget_seconds)

    print(f"caption-band code fingerprint: {caption_cache.captions_fingerprint()}")
    work = list(plan(args.targets))
    if args.jobs > 1 and len(work) > 1:
        total = run_parallel(work, args)
    else:
        total = run_serial(work, args)

    if args.summary_json:
        print(SUMMARY_PREFIX + json.dumps(total))
        return

    print(f"\nTOTAL {total['measured']} shots re-measured across "
          f"{total['shots']} indexed shots.")
    print(f"  {total['moved']} caption crops moved: {total['appeared']} shots "
          f"are newly cropped, {total['vanished']} are no longer cropped, "
          f"{total['floor_flips']} change side of the {MIN_SHORT_SIDE}px "
          f"resolution floor")
    if total["failures"]:
        print(f"  {total['failures']} shots kept their old value because the "
              f"probe failed - those stay stale and will still be refused")
    if total["over_budget"]:
        runlog.annotate(caption_over_budget=total["over_budget"],
                        caption_set_aside=total["set_aside"],
                        caption_key=caption_cache.captions_fingerprint())
        if total["set_aside"] and not args.dry_run:
            print(caption_cache.set_aside_warning(
                total["set_aside"], len(work)), file=sys.stderr)
        left = total["over_budget"] - (0 if args.dry_run else total["set_aside"])
        if left:
            print(f"WARNING caption-band cache: {left} shot(s) past the "
                  f"{args.budget_seconds:.0f}s budget were not re-measured"
                  f"{' (dry run)' if args.dry_run else ''} - stale ones stay "
                  f"stale", file=sys.stderr)
    if args.dry_run:
        print("dry run - nothing written")


@runlog.script("footage-indexer", "remeasure-captions", name="remeasure_captions.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
"""Re-take the cached usability measurement over an index that already exists.

CF-0048's other half. `cache_fingerprint.py` makes a cache measured by older
code *visible* and stops it being believed; this is how the pool is brought
back up to date once the measuring code has moved, without paying for a full
re-index (shot boundaries, CLIP embeddings, hand-written descriptions,
contact sheets and card flags are untouched - none of them depend on the
usability probe).

Deliberately a separate command, and deliberately not wired into anything.
Re-measuring changes which candidates the pre-filter skips, for every video
built from these sources from then on - that is a real change to what the
montages will look like, not a cache-warming chore, and it should happen
because someone asked for it and then looked at the result.

CF-0410: never over the whole pool. The pool is transient (CF-0358: sources
are deleted after publication, the old pool is not processed in bulk) and a
stale stamp is safe - `resolve_anchors.py` measures such a candidate live. At
~2.3 s a shot a pool-wide run is hours (run 2026-09-27T0929Z lost one before
the user stopped it). When a remeasure is wanted at all, it is the sources of
the current batch, by name - what `test_usability_cache_freshness.py` prints.

Usage:
    remeasure_usability.py <video-or-shots.json> [more...] [--dry-run]

`--dry-run` measures and reports without writing, which is how you find out
what a remeasure would do before doing it. Every run prints, per source, the
shots whose *pre-filter verdict* changes - not merely whose numbers move -
using resolve_anchors.py's own rule at the thresholds a real run uses.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from usability_probe import extract_full_frames, probe_usability  # noqa: E402
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
import shot_schema  # noqa: E402 - CF-0281: the index is rewritten whole or not at all
# The reader's own verdict rule, imported rather than reimplemented: "what
# does this change" has to be answered by the code that does the filtering.
import resolve_anchors  # noqa: E402 - on sys.path via usability_probe's Video Editor bootstrap
from common import MIN_COVERAGE, MIN_SHORT_SIDE  # noqa: E402


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


def verdict(shot, cached, args):
    """True when the pre-filter would skip this shot on these numbers."""
    if not cached:
        return False
    return resolve_anchors.cached_verdict(shot, cached, args.min_short_side,
                                          args.min_coverage, args.max_black)


def remeasure(video, shots_json, args):
    data = json.load(open(shots_json))
    shots = data["shots"]
    changed_numbers, flips, failed = 0, [], 0
    # Counted before the loop below overwrites each shot's cache - afterwards
    # every shot has one and the question cannot be asked any more.
    uncached_before = sum(1 for s in shots if not s.get("usable_cached"))

    with tempfile.TemporaryDirectory() as tmp:
        # CF-0107: the frame loop and each shot's Vision probe are `child`
        # events here, at the call sites - usability_probe.py's own bytes are
        # the usability fingerprint and stay untouched.
        with runlog.child("ffmpeg", argv=["ffmpeg", "full-frames", str(video)],
                          params={"shots": len(shots)}):
            frames = extract_full_frames(video, shots, Path(tmp))
        for i, shot in enumerate(shots):
            if frames[i] is None:
                failed += 1
                print(f"  shot {i}: no frame extracted, cache left as it was",
                      file=sys.stderr)
                continue
            before = shot.get("usable_cached")
            try:
                with runlog.child("vision", argv=["vision", "usability", str(frames[i])],
                                  step="probe"):
                    after = probe_usability(frames[i])
            except Exception as e:
                failed += 1
                print(f"  shot {i}: probe failed ({e}), cache left as it was",
                      file=sys.stderr)
                continue
            # The stamp itself always changes on the first remeasure after a
            # code change; that is not news. What is news is a number moving -
            # and only a shot that had a measurement can have one move, so a
            # shot getting its first cache is not counted here either.
            if before and measurements(before) != measurements(after):
                changed_numbers += 1
            was, now = verdict(shot, before, args), verdict(shot, after, args)
            if was != now:
                flips.append((i, shot, before, after, was, now))
            shot["usable_cached"] = after

    for i, shot, before, after, was, now in flips:
        card = " [is_card]" if shot.get("is_card") else ""
        print(f"  shot {i}{card}: {'skipped -> kept' if was else 'kept -> skipped'}"
              f"\n      was {describe(before)}"
              f"\n      now {describe(after)}")

    if not args.dry_run:
        # CF-0281: whole or not at all - a kill inside this rewrite would
        # otherwise destroy an index that was already good.
        shot_schema.write_index(shots_json, data)

    # Two different things get called a "changed verdict" here and they must
    # not be added up. A shot that *had* a measurement and changes verdict is
    # the staleness this exists to fix. A shot that had none - an index built
    # before CF-0029, or whose probe failed then - is not changing its mind:
    # it is being pre-filtered for the first time, which is CF-0029 arriving
    # at that index. Only the first number says how much re-measuring moves a
    # montage; reporting their sum would overstate it several-fold.
    restamp = [f for f in flips if f[2]]
    first = [f for f in flips if not f[2]]
    return {"shots": len(shots), "numbers_changed": changed_numbers,
            "probe_failures": failed, "uncached_before": uncached_before,
            "restamp_flips": len(restamp),
            "restamp_now_kept": sum(1 for f in restamp if f[4] and not f[5]),
            "restamp_cards": sum(1 for f in restamp if f[1].get("is_card")),
            "first_cache_flips": len(first)}


def measurements(cached):
    """The cached measurement without its CF-0048 stamp, so that "did this
    shot's numbers move" is not answered `yes` by the stamp alone."""
    return {k: v for k, v in (cached or {}).items() if k != "measured_by"}


def describe(cached):
    if not cached:
        return "no cached measurement"
    ink = cached.get("card_ink_fraction", "not measured")
    return (f"{cached['roi_source']} / coverage {cached['roi_coverage']} / "
            f"black {cached['black_fraction']} / luma {cached['mean_luma']} / "
            f"ink {ink} / by {cached.get('measured_by', 'unrecorded')}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("targets", nargs="+", help="video files or their .shots.json")
    p.add_argument("--dry-run", action="store_true",
                   help="measure and report, write nothing")
    p.add_argument("--min-short-side", type=int, default=MIN_SHORT_SIDE)
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE)
    p.add_argument("--max-black", type=float, default=resolve_anchors.MAX_BLACK_CLIPS)
    args = p.parse_args()

    total = {"shots": 0, "numbers_changed": 0, "probe_failures": 0,
             "uncached_before": 0, "restamp_flips": 0, "restamp_now_kept": 0,
             "restamp_cards": 0, "first_cache_flips": 0}
    for arg in args.targets:
        video, shots_json = targets(arg)
        if not shots_json.exists():
            print(f"{shots_json}: no index, skipped", file=sys.stderr)
            continue
        if not video.exists():
            print(f"{video}: source missing, cannot re-measure {shots_json.name}",
                  file=sys.stderr)
            continue
        print(f"{shots_json.name}:")
        with runlog.run("footage-indexer", "remeasure-usability", video=video.stem,
                        name="remeasure_usability.py"):   # CF-0107: one event per source
            result = remeasure(video, shots_json, args)
        for k in total:
            total[k] += result[k]
        print(f"  {result['shots']} shots, {result['numbers_changed']} of the "
              f"already-measured ones moved, {result['restamp_flips']} of those "
              f"changed verdict ({result['restamp_now_kept']} newly kept, "
              f"{result['restamp_cards']} cards)"
              + (f", {result['first_cache_flips']} shots pre-filtered for the "
                 f"first time" if result["first_cache_flips"] else "")
              + (f", {result['probe_failures']} probe failures"
                 if result["probe_failures"] else ""))

    stale_shots = total["shots"] - total["uncached_before"]
    print(f"\nTOTAL {total['shots']} shots, {stale_shots} of them carrying a "
          f"measurement already.")
    print(f"  re-measuring those {stale_shots}: {total['numbers_changed']} "
          f"of their measurements moved, {total['restamp_flips']} changed the pre-filter's "
          f"verdict ({total['restamp_now_kept']} newly kept, "
          f"{total['restamp_flips'] - total['restamp_now_kept']} newly skipped, "
          f"{total['restamp_cards']} of them cards)")
    print(f"  separately, {total['uncached_before']} shots had no measurement at "
          f"all and now have one; {total['first_cache_flips']} of those become "
          f"pre-filterable (CF-0029 reaching that index, not staleness)")
    if args.dry_run:
        print("dry run - nothing written")


@runlog.script("footage-indexer", "remeasure-usability", name="remeasure_usability.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()

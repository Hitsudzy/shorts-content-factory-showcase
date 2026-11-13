#!/usr/bin/env python3
"""Re-derive the caption-band thickness of every card in a footage pool, and
what CF-0103's guard and threshold make of it.

Not part of the pipeline. This is the measurement three tasks in a row had
to rebuild by hand - CF-0047 found the defect, CF-0053 proposed band
thickness as the feature that tells a card's own bottom lettering from
somebody else's burned-in subtitles, CF-0061 measured it and found the
populations interleave *on the clamped number* - and each of them re-wrote
this loop from scratch to get its numbers. CF-0103 is the implementation of
the decision CF-0061 ended in (thick band = the card's own design, thin band =
subtitles, with a guard for text that covers the frame), and this is the
loop that checks it: a threshold argued from a note nobody can re-run is a
threshold nobody can check.

What it prints, per `is_card` shot that has a non-zero cached band:

  cached       what the index holds, i.e. what the pipeline cut with
  raw          detect_captions() today - unclamped since CF-0103 (0.0 when
               the guard refused the measurement)
  band_top     top of the lower-region text cluster
  upper_lines  text lines held above LOWER_REGION - what the guard counts
  guard        REJECT when the frame is covered in text, ok otherwise
  verdict      what prepare_clip.py --card does with `raw`: crop (a thin
               band, subtitles), keep (a thick band, the card's own), none

`--subtitled` names the pool's subtitled sources, because "does this card
carry foreign text" is not in the index - it is a human judgement about the
source, and it is the label the whole separation is measured against. It is
passed in rather than hardcoded so the pool this is run on can be a different
one: the entire open question is what a third subtitled source does to the
gap, and the threshold's comment in prepare_clip.py says to re-run this then.

`--dump-frames DIR` writes the per-frame Vision boxes of every measured shot
to DIR as JSON, and `--from-frames DIR` replays them through the detector's
pure half without Vision or ffmpeg - that is how the guard was calibrated
and how tests/test_card_band_threshold.py checks it on real geometry.

Usage:
    measure_card_bands.py <pool-dir> [--subtitled x9wMFCMXCRE,FfYCVp8hLcg]
      [--only SOURCE[:SHOT],...] [--dump-frames DIR | --from-frames DIR] [--json]
"""
import argparse
import json
import sys
from pathlib import Path

import detect_text_band
import prepare_clip


def selected(source, index, only):
    """Whether `--only` (a set of "source" / "source:shot") admits this shot."""
    return not only or source in only or f"{source}:{index}" in only


def cards(pool, only=()):
    """Every (source, video, shot) in the pool whose shot is a card with a band.

    A card with `crop_bottom_cached` of 0.0 or missing is not part of the
    question: nothing is cropped from it either way, so it can neither be
    saved by a threshold nor lost to one. (FfYCVp8hLcg shots 8/14/22 are the
    reminder that "no band" can be a subtitled card the detector missed -
    that is a detector question, not a threshold one.)
    """
    for index in sorted(Path(pool).glob("*.shots.json")):
        video = index.with_suffix("").with_suffix(".mp4")
        source = index.name[: -len(".shots.json")]
        for shot in json.load(open(index))["shots"]:
            if not (shot.get("is_card") and shot.get("crop_bottom_cached")):
                continue
            if not selected(source, shot["index"], only):
                continue
            if not video.exists():
                print(f"  no video beside {index.name} - skipped", file=sys.stderr)
                break
            yield source, video, shot


def fixture_name(source, index):
    return f"{source}_s{index}.json"


def row(source, shot, result, subtitled):
    raw = result.get("crop_bottom", 0.0)
    guard = bool(result.get("fullscreen_text"))
    applied, withheld, why = prepare_clip.caption_crop(raw, card=True)
    return {
        "source": source,
        "shot": shot["index"],
        "subtitled": source in subtitled,
        "cached": shot.get("crop_bottom_cached"),
        "raw": raw,
        "band_top": result.get("band_top"),
        "upper_lines": result.get("upper_lines"),
        "guard": "REJECT" if guard else "ok",
        "verdict": "keep" if withheld else ("crop" if applied else "none"),
    }


def measure(pool, subtitled, only=(), dump_frames=None):
    rows = []
    for source, video, shot in cards(pool, only):
        frames = detect_text_band.sample_frames(
            str(video), shot["start"], shot["end"], samples=8)
        if dump_frames:
            Path(dump_frames).mkdir(parents=True, exist_ok=True)
            json.dump({"source": source, "shot": shot["index"],
                       "start": shot["start"], "end": shot["end"],
                       "is_card": True,
                       "crop_bottom_cached": shot.get("crop_bottom_cached"),
                       "crop_bottom_measured_by": shot.get("crop_bottom_measured_by"),
                       "samples": len(frames),
                       "frames": [[[round(t, 4), round(b, 4)] for t, b in sorted(f)]
                                  for f in frames]},
                      open(Path(dump_frames) / fixture_name(source, shot["index"]), "w"))
        rows.append(row(source, shot, detect_text_band.band_from_frames(frames), subtitled))
        print(line(rows[-1]), file=sys.stderr, flush=True)
    return rows


def replay(frames_dir, subtitled, only=()):
    rows = []
    for path in sorted(Path(frames_dir).glob("*.json")):
        fx = json.load(open(path))
        if not selected(fx["source"], fx["shot"], only):
            continue
        frames = [[tuple(b) for b in f] for f in fx["frames"]]
        shot = {"index": fx["shot"], "crop_bottom_cached": fx.get("crop_bottom_cached")}
        rows.append(row(fx["source"], shot, detect_text_band.band_from_frames(frames), subtitled))
    return rows


HEADER = (f"{'source':<12} {'shot':>4} {'label':<9} {'cached':>7} {'raw':>7} "
          f"{'band_top':>8} {'upper':>5} {'guard':<6} verdict")


def line(r):
    fmt = lambda v: f"{v:7.4f}" if isinstance(v, (int, float)) else f"{'-':>7}"
    return (f"{r['source']:<12} {r['shot']:>4} {'subtitled' if r['subtitled'] else 'clean':<9} "
            f"{fmt(r['cached'])} {fmt(r['raw'])} "
            f"{fmt(r['band_top']) if r['band_top'] is not None else '-':>8} "
            f"{r['upper_lines'] if r['upper_lines'] is not None else '-':>5} "
            f"{r['guard']:<6} {r['verdict']}")


def report(rows):
    """The table, the two populations, and what separates them."""
    print(HEADER)
    for r in rows:
        print(line(r))
    print()
    for label, want in (("subtitled sources", True), ("clean sources", False)):
        values = sorted(r["raw"] for r in rows if r["subtitled"] is want
                        and r["guard"] == "ok" and r["raw"])
        print(f"{label} (n={len(values)}, guard ok, band found): "
              + ", ".join(f"{v:.4f}" for v in values))
    rejected = [r for r in rows if r["guard"] == "REJECT"]
    print(f"guard rejected: {len(rejected)} - "
          + ", ".join(f"{r['source']} shot {r['shot']} ({r['upper_lines']} lines)"
                      for r in rejected))

    subtitled = [r for r in rows if r["subtitled"] and r["guard"] == "ok" and r["raw"]]
    clean = [r for r in rows if not r["subtitled"] and r["guard"] == "ok" and r["raw"]]
    if not subtitled or not clean:
        return
    highest = max(subtitled, key=lambda r: r["raw"])
    lowest = min(clean, key=lambda r: r["raw"])
    gap = lowest["raw"] - highest["raw"]
    print(f"\nhighest subtitled: {highest['raw']:.4f} "
          f"({highest['source']} shot {highest['shot']})")
    print(f"lowest clean:      {lowest['raw']:.4f} "
          f"({lowest['source']} shot {lowest['shot']})")
    threshold = prepare_clip.CARD_OWN_BAND
    if gap > 0:
        print(f"gap {gap:.4f}; CARD_OWN_BAND {threshold} "
              f"{'sits inside it' if highest['raw'] < threshold < lowest['raw'] else 'is OUTSIDE it - recalibrate'}")
    else:
        crossing = sorted((r for r in subtitled if r["raw"] > lowest["raw"]),
                          key=lambda r: r["raw"])
        print(f"NO GAP - the populations overlap by {-gap:.4f}; "
              f"{len(crossing)} subtitled card(s) sit above the lowest clean one:")
        for r in crossing:
            print(f"  {r['source']} shot {r['shot']}: {r['raw']:.4f}")
    wrong = [r for r in rows if r["guard"] == "ok" and r["raw"]
             and (r["verdict"] == "crop") != r["subtitled"]]
    print(f"misjudged by CARD_OWN_BAND {threshold}: {len(wrong)}"
          + (" - " + ", ".join(f"{r['source']} shot {r['shot']} ({r['raw']:.4f} -> {r['verdict']})"
                              for r in wrong) if wrong else ""))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pool", nargs="?", help="directory of <source>.mp4 + <source>.shots.json")
    p.add_argument("--subtitled", default="",
                   help="comma-separated sources known to carry burned-in "
                        "foreign text - the label the split is measured against")
    p.add_argument("--only", default="",
                   help="comma-separated SOURCE or SOURCE:SHOT to restrict the run to")
    p.add_argument("--dump-frames", metavar="DIR",
                   help="write each measured shot's per-frame text boxes to DIR")
    p.add_argument("--from-frames", metavar="DIR",
                   help="replay dumped frames from DIR instead of measuring the pool")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    subtitled = {s for s in args.subtitled.split(",") if s}
    only = {s for s in args.only.split(",") if s}
    if args.from_frames:
        rows = replay(args.from_frames, subtitled, only)
    elif args.pool:
        rows = measure(args.pool, subtitled, only, args.dump_frames)
    else:
        p.error("a pool directory or --from-frames DIR is required")
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
    else:
        report(rows)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""What the caption-band crop does to the resolution floor, shot by shot.

Not part of the pipeline - the measurement CF-0062 asked for, kept as a tool
for the same reason measure_card_bands.py is: a number argued from a note
nobody can re-run is a number nobody can check.

CF-0104: the floor is checked on the *cut clip*, but against different
geometry depending on the delivery mode (resolve_anchors.usable() and
build_render_plan.inspect_asset() both probe a frame of it), i.e. after
prepare_clip.py has taken the source's own letterbox bars and then the
caption band off the bottom. The index's `usable_cached.short_side` is taken
before the caption crop and does not carry the geometry either floor now
needs. So for every shot in the pool with a non-zero `crop_bottom_cached`
this reproduces prepare_clip.py's geometry exactly - detect_letterbox() on
the shot's own span, then the same `floor(ih*(1-crop)/2)*2` - and reports:

  pre / post          short side before and after the caption crop (kept for
                      reference; not what either floor is checked against
                      any more - see below)
  window / window_h   the region, in source pixels, of the 9:16 window
                      AssetLayer.jsx's object-fit:cover actually displays for
                      a `cover` shot (smart_crop.delivered_window(), with the
                      `zoom` smart_crop.analyse() computes on the real
                      post-crop frame) - this is what gets scaled to 1920
                      tall, and MIN_SHORT_SIDE is the floor on its height
                      (`window[1]`), before and after the caption crop.
  upscale_cover        1920 / window height: how many times a `cover` shot's
                      delivered window is blown up.
  upscale_contain       1920 / frame height: how many times a `contain`
                      shot's (an `is_card` shot's) whole frame has to be
                      blown up vertically to reach the 1920px delivery
                      height - what MAX_CONTAIN_UPSCALE actually gates, not
                      the CSS object-fit:contain scale (upscale_contain_css,
                      kept for reference) - every card measured in this pool
                      is comfortably narrower than the 1080px delivery width
                      once letterboxed, so that number never moves and
                      cannot see the softness the norm exists to catch.
  upscale_delivered     upscale_contain for an `is_card` shot, upscale_cover
                      otherwise - what the real gate actually compares to
                      its floor.
  verdict             "genuinely low-res" (the shot's floor was not cleared
                      even before the caption crop) / "dropped by our crop"
                      (it was, and the crop took it under) / "clears the
                      floor" - computed per delivery mode: MIN_SHORT_SIDE on
                      window height for `cover`, MAX_CONTAIN_UPSCALE on
                      upscale_contain for `contain`.

`--no-vision` skips the Vision pass (zoom is then 1.0 and window_h is the
natural cover window); the geometry columns need only ffmpeg.

Usage:
    measure_crop_floor.py <pool-dir> [--json] [--no-vision]
"""
import argparse
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import smart_crop
from common import (FFMPEG, MIN_SHORT_SIDE, MAX_CONTAIN_UPSCALE, PROBE_OFFSET,
                    PROBE_FRAME_TIMEOUT_SECONDS)
from prepare_clip import detect_letterbox, video_size

TARGET_W, TARGET_H = 1080, 1920


def cropped_height(height, crop_bottom):
    """prepare_clip.py's own filter: crop=iw:floor(ih*(1-crop)/2)*2:0:0."""
    return int((height * (1 - crop_bottom)) // 2) * 2


def parse_bars(bars):
    """(w, h) out of detect_letterbox()'s "crop=w:h:x:y", or None."""
    if not bars:
        return None
    w, h, _, _ = (int(v) for v in bars[len("crop="):].split(":"))
    return w, h


def banded_shots(pool):
    for index in sorted(Path(pool).glob("*.shots.json")):
        video = index.with_suffix("").with_suffix(".mp4")
        if not video.exists():
            print(f"  no video beside {index.name} - skipped", file=sys.stderr)
            continue
        source = index.name[: -len(".shots.json")]
        for shot in json.load(open(index))["shots"]:
            if shot.get("crop_bottom_cached"):
                yield source, video, shot


def probe_frame(video, shot, bars, crop_bottom, dest):
    """One frame of the shot, cut exactly as prepare_clip.py would cut the
    clip, at the offset usable() probes first."""
    vf = []
    if bars:
        vf.append(bars)
    if crop_bottom > 0:
        vf.append(f"crop=iw:floor(ih*{1 - crop_bottom}/2)*2:0:0")
    t = min(shot["start"] + PROBE_OFFSET, max(shot["start"], shot["end"] - 0.05))
    cmd = [FFMPEG, "-y", "-nostdin", "-v", "error", "-ss", str(t), "-i", str(video)]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-frames:v", "1", str(dest)]
    # CF-0135: one frame costs what it costs, so the CF-0077 frame ceiling -
    # an instrument that wedges is still a wedged instrument.
    subprocess.run(cmd, capture_output=True, timeout=PROBE_FRAME_TIMEOUT_SECONDS)
    return dest.exists()


def measure_shot(source, video, shot, size, use_vision, tmp):
    w0, h0 = size
    crop = shot["crop_bottom_cached"]
    bars = detect_letterbox(str(video), shot["start"], shot["end"] - shot["start"])
    w1, h1 = parse_bars(bars) or (w0, h0)
    h2 = cropped_height(h1, crop)
    pre, post = min(w1, h1), min(w1, h2)

    zoom, coverage, roi_source = 1.0, None, None
    if use_vision:
        import vision_client
        frame = tmp / f"{source}_s{shot['index']:03d}.png"
        if probe_frame(video, shot, bars, crop, frame):
            try:
                info = vision_client.find_roi(str(frame), f"{TARGET_W}:{TARGET_H}")
                zoom = info.get("zoom", 1.0) or 1.0
                coverage = info.get("roi_coverage")
                roi_source = info.get("roi_source")
            except Exception as e:  # a broken frame is a fact about the shot, not the run
                print(f"  {source} shot {shot['index']}: Vision failed ({e})",
                      file=sys.stderr)
            frame.unlink(missing_ok=True)

    # cover: what AssetLayer.jsx shows for a clip. focus does not change the
    # window's size, only where it sits, so (0.5, 0.5) is as good as any.
    # Computed both after the caption crop (what actually ships) and before
    # it (what would have shipped without our own crop), because CF-0104's
    # gate - like CF-0062's before it - has to be able to say which one a
    # shot failed.
    _, _, cw, ch = smart_crop.delivered_window(
        (w1, h2), (0.5, 0.5), zoom, TARGET_W, TARGET_H, "cover")
    _, _, cw0, ch0 = smart_crop.delivered_window(
        (w1, h1), (0.5, 0.5), zoom, TARGET_W, TARGET_H, "cover")
    upscale_cover = TARGET_H / ch
    upscale_cover_pre = TARGET_H / ch0

    # contain: what it shows for an is_card shot (build_render_plan.py forces
    # fit=contain, zoom=1 for those). CF-0104: this is *not* the CSS
    # object-fit:contain scale (min of both axes' fit) - every card measured
    # in this pool is comfortably narrower than TARGET_W once letterboxed
    # (upscale_contain_css below sits at 0.5-0.6x, i.e. downscaled, for all
    # of them), so that number never moves and cannot see the softness the
    # norm exists to catch. CF-0062's own measurement (median x2.67, max
    # x3.31 on ZZ_urA56pJE) is against the frame's *height* alone - how far
    # a card has to be blown up vertically to fill the 1920px delivery
    # height - which is what MAX_CONTAIN_UPSCALE in common.py is defined
    # against and what qc_asset.py's evaluate() actually gates on.
    upscale_contain_css = min(TARGET_W / w1, TARGET_H / h2)
    upscale_contain = TARGET_H / h2 if h2 else None
    upscale_contain_pre = TARGET_H / h1 if h1 else None

    is_card = bool(shot.get("is_card"))
    if is_card:
        pass_pre = upscale_contain_pre is not None and upscale_contain_pre <= MAX_CONTAIN_UPSCALE
        pass_post = upscale_contain is not None and upscale_contain <= MAX_CONTAIN_UPSCALE
    else:
        pass_pre = ch0 >= MIN_SHORT_SIDE
        pass_post = ch >= MIN_SHORT_SIDE

    if not pass_pre:
        verdict = "genuinely low-res"
    elif not pass_post:
        verdict = "dropped by our crop"
    else:
        verdict = "clears the floor"

    return {
        "source": source, "shot": shot["index"], "is_card": is_card,
        "source_size": [w0, h0], "letterbox": bars, "after_letterbox": [w1, h1],
        "crop_bottom": crop, "after_crop": [w1, h2],
        "short_side_pre": pre, "short_side_post": post,
        "cached_short_side": (shot.get("usable_cached") or {}).get("short_side"),
        "zoom": zoom, "roi_coverage": coverage, "roi_source": roi_source,
        "window": [round(cw), round(ch)],
        "window_pre": [round(cw0), round(ch0)],
        "upscale_cover": round(upscale_cover, 2),
        "upscale_cover_pre": round(upscale_cover_pre, 2),
        "upscale_contain_css": round(upscale_contain_css, 2),
        "upscale_contain": round(upscale_contain, 2) if upscale_contain else None,
        "upscale_contain_pre": (round(upscale_contain_pre, 2)
                                if upscale_contain_pre else None),
        "upscale_delivered": round(upscale_contain if is_card else upscale_cover, 2),
        "verdict": verdict,
    }


def measure(pool, use_vision):
    rows, sizes = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        for source, video, shot in banded_shots(pool):
            if source not in sizes:
                sizes[source] = video_size(video)
            row = measure_shot(source, video, shot, sizes[source], use_vision, Path(tmp))
            rows.append(row)
            print(f"  {source} shot {shot['index']:>3}{' [card]' if row['is_card'] else ''}"
                  f"  crop {row['crop_bottom']:.4f}  {row['after_letterbox'][0]}x"
                  f"{row['after_letterbox'][1]} -> {row['after_crop'][0]}x"
                  f"{row['after_crop'][1]}  window_h {row['window'][1]}  "
                  f"x{row['upscale_delivered']}  {row['verdict']}",
                  file=sys.stderr, flush=True)
    return rows


def report(rows):
    """Per source, then per case. The three cases CF-0062 asked to keep
    apart are the three verdicts above, and they fall along source size."""
    by_source = defaultdict(list)
    for r in rows:
        by_source[r["source"]].append(r)

    print(f"{'source':14s} {'size':10s} {'band':>4s} {'lowres':>6s} {'crop':>5s} "
          f"{'ok':>3s}  upscale of what is delivered (min..max)")
    for source, rs in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        counts = defaultdict(int)
        for r in rs:
            counts[r["verdict"]] += 1
        ups = sorted(r["upscale_delivered"] for r in rs)
        w, h = rs[0]["source_size"]
        print(f"{source:14s} {f'{w}x{h}':10s} {len(rs):4d} "
              f"{counts['genuinely low-res']:6d} {counts['dropped by our crop']:5d} "
              f"{counts['clears the floor']:3d}  x{ups[0]} .. x{ups[-1]}")

    for verdict in ("dropped by our crop", "genuinely low-res", "clears the floor"):
        rs = [r for r in rows if r["verdict"] == verdict]
        if not rs:
            continue
        print(f"\n== {verdict}: {len(rs)} shots ==")
        for r in sorted(rs, key=lambda r: (r["source"], r["shot"])):
            print(f"  {r['source']} shot {r['shot']:>3}{' [card]' if r['is_card'] else '      '}"
                  f"  crop {r['crop_bottom']:.4f}  short side {r['short_side_pre']} -> "
                  f"{r['short_side_post']}  window {r['window'][0]}x{r['window'][1]}"
                  f"  zoom {r['zoom']}  cover x{r['upscale_cover']}"
                  f"  contain x{r['upscale_contain']}"
                  + (f"  cov {r['roi_coverage']}" if r["roi_coverage"] is not None else ""))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pool", help="directory of <source>.mp4 + <source>.shots.json")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-vision", action="store_true",
                   help="geometry only - skip smart_crop's zoom on the real frame")
    args = p.parse_args()

    rows = measure(args.pool, not args.no_vision)
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
    else:
        report(rows)


if __name__ == "__main__":
    main()

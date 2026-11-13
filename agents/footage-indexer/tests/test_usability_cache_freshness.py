#!/usr/bin/env python3
"""CF-0048: the cached usability measurement still describes what the code measures.

CF-0029 cached the raw measurements rather than a verdict so that moving a
threshold would not need a re-index. It does not, and that reasoning stands.
What it did not account for is that a raw measurement is the output of *code*:
CF-0004 changed `smart_crop.analyse()` seven hours after the whole pool was
indexed, CF-0047 changed the measuring path again a day later, and `shots.json`
recorded neither, so `resolve_anchors.py` went on skipping candidates on
numbers nothing in the pipeline would produce any more.

Four checks, cheapest first:
  - the probe stamps what measured it, at all;
  - the sources of *this batch* (`$RUNLOG_BATCH/01b-footage-index.json` ->
    `fetched`) carry this checkout's stamp (fast, no Vision);
  - the rest of the pool is counted and reported, never failed on (CF-0410);
  - on real shots from real footage, the cached numbers still equal what the
    probe returns today (slow, the only one that can catch a measurement that
    drifted without any source file changing - a macOS Vision update, say).

CF-0410: the pool is transient (CF-0358, the user's 2026-09-23 decision -
sources are deleted after publication and the old pool is not processed in
bulk), and a stale usability stamp is safe: `resolve_anchors.py` measures such
a candidate live, and a batch's new sources are measured when they are indexed.
So a stale pool is information, not work: `pool-maintenance` closes with
"usability: stale, not remeasured", and nothing here names a command that
remeasures the whole pool. Run `example-film/2026-09-27T0929Z` followed exactly
such a command from this test's old failure text: ~2.3 s a shot, ~3 h for the
pool, stopped by the user at ~35 % after an hour of wall clock.

The pool checks read `shared/footage/`, which is not in git, and the batch check
reads `$RUNLOG_BATCH`. Without them they are vacuous and say so out loud rather
than passing quietly.

No pytest dependency - plain asserts, run directly.
"""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import usability_probe  # noqa: E402
import cache_fingerprint  # noqa: E402 - on sys.path via usability_probe
import qc_asset  # noqa: E402 - on sys.path via usability_probe (card ink)
import smart_crop  # noqa: E402 - on sys.path via usability_probe (window, text_kept)

from _fi_paths import factory_root  # noqa: E402 - CF-0267: the root, not parents[N]
from _live_monitors import live_only  # noqa: E402

# Three real shots of ZZ_urA56pJE (the Wren Hollow trailer this defect was
# found on), chosen for the three paths through probe_usability():
#   3  - a card whose framing is what CF-0004's animation fallback rescued,
#        and the shot CF-0035's analysis re-probed by hand;
#   50 - a dark card, so card_ink() is exercised, not just skipped;
#   57 - ordinary live-action (the candlelit great hall that opens the
#        finished video), so an ordinary shot is pinned too.
LIVE_PROBE_SOURCE = "ZZ_urA56pJE"
LIVE_PROBE_SHOTS = [3, 50, 57]

REMEASURE = "agents/footage-indexer/scripts/remeasure_usability.py"


# CF-0733 (example-film/2026-10-13T1411Z): since CF-0711 Vision runs on the
# CPU of this Intel Mac, and the pool was measured on its GPU. The stamp chain
# says so - the neutral pair c883fbad1183 -> 9b61e5035625 is of kind
# "device-pin", whose `why` (video-editor's cache_fingerprint.NEUTRAL_EDITS)
# grants float noise only: CPU float32 against GPU float16 moves a Vision box.
#
# CF-0754 (example-tech/2026-10-15T1854Z, 10-16T0702Z, 10-16T0839Z): CF-0733
# sized that noise as one fixed fraction of the frame, 0.0005, from one shot -
# shot 3 (one 504x98 px box, text_area 0.0537 -> 0.0536). 1411Z's monitor
# stopped at shot 3, so shots 50 and 57 were never compared there; the first
# monitor to reach shot 50 (a dark card, five boxes, one of them 589x167 px)
# saw text_area 0.1357 -> 0.1345, text_cut_area 0.1055 -> 0.1065,
# text_outside_crop 0.2428 -> 0.2472 and card_ink_fraction 0.0972 -> 0.0981,
# the same numbers in three batches and twice in one process (the CPU probe is
# deterministic - this is the device, not jitter). The unit was wrong, not the
# number: a box edge that lands one pixel further moves text_area by that
# box's side over the frame, 589/921600 = 0.00064 for one edge of the big box
# - over 0.0005 already - and 0.000027 for the short side of the small one. A
# fraction is not what the device moves; a box edge in pixels is.
# card_ink_fraction was left out altogether, though its pixels are read
# inside the very same Vision boxes.
#
# So across a device-pin link (and only there) the tolerance of each field is
# computed from the frame's own live boxes: how far the field can move when
# every box edge - and the delivered window, which the saliency box places -
# moves by up to EDGE_JITTER_PX, plus one step of the field's 4-decimal
# rounding (device_noise_tolerance(); exact interval arithmetic on monotone
# areas, no sampling). One pixel: Vision returns float16 coordinates on the
# GPU, whose spacing in [0.5, 1) is 2^-11 of the side, 0.62 px of 1280, so
# "the edge landed on the neighbouring pixel" is the smallest honest unit. On
# shot 50's live boxes it allows text_area 0.0036, text_cut_area 0.0017,
# text_outside_crop 0.0124, card_ink_fraction 0.0028 against the
# 0.0012/0.0010/0.0044/0.0009 seen, and on shot 3 text_area 0.0014 against
# 0.0001; half a pixel would already miss shot 50 (text_cut_area 0.0009 <
# 0.0010), so one pixel is the least that explains what the device did, not a
# margin picked to go green. What a real change does - a
# Vision revision that pads its boxes, a window from another aspect, thicker
# ink - moves these fields by far more than a pixel of every
# edge and stays red (test_device_noise_is_sized_by_box_geometry_and_a_real_change_stays_red). Everything
# else - size, roi_source, roi_coverage, the region count, text_cut_by_crop (a
# ratio of counts: it moves only when a region crosses the crop, a real
# change), luma, black - stays exact, and a stamp chain without a device-pin
# link compares all of it exactly, as before. A tolerated difference is
# printed, never silent.
EDGE_JITTER_PX = 1.0
ROUNDING_STEP = 0.0001      # every DEVICE_NOISY_FIELDS value is round(x, 4)
DEVICE_NOISY_FIELDS = ("text_area", "text_outside_crop", "text_cut_area",
                       "card_ink_fraction")


def crosses_device_pin(stamp, current):
    """Whether the LEGACY_STAMPS chain from `stamp` to `current` passes a
    NEUTRAL_EDITS pair of kind "device-pin" - the cache was measured on
    another device than the one measuring now."""
    neutral = getattr(cache_fingerprint, "NEUTRAL_EDITS", {})
    seen = set()
    while stamp not in seen and stamp != current:
        seen.add(stamp)
        if (neutral.get(stamp) or {}).get("kind") == "device-pin":
            return True
        stamp = cache_fingerprint.LEGACY_STAMPS.get(stamp)
    return False


def moved_regions(regions, size, px):
    """`regions` (Vision's fractional boxes) with every edge moved `px` source
    pixels outward - inward for a negative `px`; a box shrinks to a line, it
    never turns inside out."""
    w, h = size
    out = []
    for r in regions:
        left, right = r["left"] * w - px, (r["left"] + r["width"]) * w + px
        top, bottom = r["top"] * h - px, r["bottom"] * h + px
        if right < left:
            left = right = (left + right) / 2
        if bottom < top:
            top = bottom = (top + bottom) / 2
        out.append(dict(r, left=left / w, width=(right - left) / w,
                        top=top / h, bottom=bottom / h, height=(bottom - top) / h))
    return out


def _area_px(regions, size):
    return sum(r["width"] * size[0] * r["height"] * size[1] for r in regions)


def device_noise_tolerance(regions, window, size, frame=None, jitter=EDGE_JITTER_PX):
    """{field: how far it may move between two devices measuring this frame}
    - the move every box edge and the window shifting by up to `jitter`
    source pixels can make, plus one rounding step (CF-0754).

    Each bound is an interval on quantities monotone in a box's extent: the
    text area, the area outside the window and the box pixels (lit or not)
    all only grow when a box grows, so the boxes moved `jitter` in and out
    bracket every placement in between. `regions`/`window`/`size` are what
    usability_probe.text_against_window() works from; `frame` is the image
    card_ink_fraction is read from (no frame, no card-ink tolerance)."""
    frame_px = size[0] * size[1]
    small = moved_regions(regions, size, -jitter)
    big = moved_regions(regions, size, jitter)
    tol = {"text_area": (_area_px(big, size) - _area_px(regions, size)) / frame_px}

    cut = [r for r in regions if usability_probe.cut_regions([r], window, size)[0]]
    tol["text_cut_area"] = (_area_px(moved_regions(cut, size, jitter), size)
                            - _area_px(cut, size)) / frame_px

    def outside(regs, win):
        return (1.0 - smart_crop.text_kept(regs, win, size)) * _area_px(regs, size)
    x, y, ww, wh = window
    windows = [(x + dx, y + dy, ww, wh) for dx in (-jitter, 0, jitter)
               for dy in (-jitter, 0, jitter)]
    share = 1.0 - smart_crop.text_kept(regions, window, size)
    lo = min(outside(small, win) for win in windows) / _area_px(big, size)
    hi = max(outside(big, win) for win in windows) / max(_area_px(small, size), 1e-9)
    tol["text_outside_crop"] = max(share - lo, hi - share)

    if frame is not None:
        # text_ink_pixels() truncates each edge to a whole pixel, so an edge
        # within `jitter` of another lands within ceil(jitter) pixels of it.
        step = math.ceil(jitter)
        content = qc_asset.card_text_regions(regions)

        def lit_and_all(regs):
            pixels = qc_asset.text_ink_pixels(frame, regs)
            return qc_asset.ink_fraction(pixels) * len(pixels), len(pixels)
        lit, total = lit_and_all(content)
        if total:
            lit_s, total_s = lit_and_all(moved_regions(content, size, -step))
            lit_b, total_b = lit_and_all(moved_regions(content, size, step))
            ink = lit / total
            tol["card_ink_fraction"] = max(ink - lit_s / max(total_b, 1),
                                           lit_b / max(total_s, 1) - ink)
    return {k: v + ROUNDING_STEP for k, v in tol.items()}


def probe_geometry(frame):
    """(regions, window, size) of a real frame, exactly as
    usability_probe.text_against_window() takes them - the live boxes a
    device-noise tolerance is computed from."""
    vision = usability_probe.vision_client.find_roi(str(frame), usability_probe.QC_ASPECT)
    size = (vision["source_size"]["width"], vision["source_size"]["height"])
    aspect_w, aspect_h = (int(v) for v in usability_probe.QC_ASPECT.split(":"))
    window = smart_crop.delivered_window(
        size, smart_crop.focus_point(vision), vision.get("zoom", 1.0),
        aspect_w, aspect_h, "cover")
    return usability_probe.vision_client.text_regions(str(frame), level=0), window, size


def measurement_diff(cached, live, tolerance=None):
    """(disagreements, tolerated): the fields where the cache and a live probe
    differ, `measured_by` aside. With `tolerance` ({field: bound}, from
    device_noise_tolerance()) a field of DEVICE_NOISY_FIELDS within its bound
    goes to `tolerated` instead."""
    bad, tolerated = {}, {}
    tolerance = tolerance or {}
    for k in sorted(set(cached) | set(live)):
        if k == "measured_by":
            continue
        a, b = cached.get(k), live.get(k)
        if a == b:
            continue
        if (k in DEVICE_NOISY_FIELDS and k in tolerance
                and isinstance(a, (int, float)) and isinstance(b, (int, float))
                and not isinstance(a, bool) and not isinstance(b, bool)
                and abs(a - b) <= tolerance[k] + 1e-12):
            tolerated[k] = (a, b)
        else:
            bad[k] = (a, b)
    return bad, tolerated


# Shot 50 of ZZ_urA56pJE as the CPU (9b61e5035625) measures it on this Mac,
# 2026-10-16: the five boxes (source pixels left, top, width, height) and the
# delivered window - a stand-in, so the suite needs neither Vision nor the pool.
SHOT50_SIZE = (1280, 720)
SHOT50_WINDOW = (427.9625, 0.0, 405.0, 720.0)
SHOT50_BOXES_PX = [(558.0, 186.0, 158.0, 26.0), (577.9, 213.3, 124.3, 27.4),
                   (352.6, 282.6, 588.8, 166.8), (510.0, 458.0, 164.0, 36.0),
                   (558.8, 502.2, 244.8, 50.6)]
SHOT50_CACHED = {"measured_by": "c8a4a9661e70", "short_side": 720, "width": 1280,
                 "height": 720, "roi_source": "animation_center", "roi_coverage": 1.0,
                 "black_fraction": 0.951, "mean_luma": 4.9, "text_regions": 5,
                 "text_area": 0.1357, "text_outside_crop": 0.2428,
                 "text_cut_by_crop": 0.2, "text_cut_area": 0.1055,
                 "card_ink_fraction": 0.0972}
SHOT50_LIVE = dict(SHOT50_CACHED, measured_by="9b61e5035625", text_area=0.1345,
                   text_outside_crop=0.2472, text_cut_area=0.1065,
                   card_ink_fraction=0.0981)


def _regions_px(boxes, size):
    w, h = size
    return [{"left": x / w, "top": y / h, "width": bw / w, "height": bh / h,
             "bottom": (y + bh) / h} for x, y, bw, bh in boxes]


def _card_frame(path, boxes, size, ink_rows=0.1):
    """A dark card: black, and inside each box a lit band `ink_rows` of its
    height tall - glyph strokes on a dark margin, as on shot 50."""
    from PIL import Image, ImageDraw
    im = Image.new("L", size, 4)
    draw = ImageDraw.Draw(im)
    for x, y, bw, bh in boxes:
        mid = y + bh / 2
        draw.rectangle([x + 3, mid - bh * ink_rows / 2, x + bw - 3, mid + bh * ink_rows / 2],
                       fill=200)
    im.save(path)
    return path


def _measure(regions, window, size, frame):
    """The four fields text_against_window() and card_ink() would write for
    these boxes - test arithmetic over the same functions, for stand-ins."""
    cut_count, cut_area = usability_probe.cut_regions(regions, window, size)
    pixels = qc_asset.text_ink_pixels(frame, qc_asset.card_text_regions(regions))
    return {"text_area": round(sum(r["width"] * r["height"] for r in regions), 4),
            "text_outside_crop": round(1.0 - smart_crop.text_kept(regions, window, size), 4),
            "text_cut_area": round(cut_area, 4),
            "card_ink_fraction": round(qc_asset.ink_fraction(pixels), 4)}


def test_device_noise_is_tolerated_only_across_a_device_pin_and_only_in_fractions():
    """CF-0733, on stand-ins: shot 3 of 1411Z's monitor passes, a count, a
    category or a chain with no device-pin link does not."""
    pin = next((old for old, e in getattr(cache_fingerprint, "NEUTRAL_EDITS", {}).items()
                if e.get("kind") == "device-pin"), None)
    assert pin is not None, "no device-pin pair - CF-0711's pair is gone, revisit CF-0733"
    after = cache_fingerprint.NEUTRAL_EDITS[pin]["after"]
    assert crosses_device_pin("c8a4a9661e70", after)          # the pool's stamp, chained
    assert crosses_device_pin(pin, after)
    assert not crosses_device_pin(after, after)                # measured on this device
    assert not crosses_device_pin("edcd5ade6f17", pin)         # a chain short of the pin
    # shot 3: one 504x98 px box, the window cutting it on both sides
    size, window = (1280, 720), (431.375, 0.0, 405.0, 720.0)
    regions = _regions_px([(403.8, 285.0, 504.4, 98.0)], size)
    tolerance = device_noise_tolerance(regions, window, size)
    cached = {"measured_by": "c8a4a9661e70", "short_side": 720, "roi_source": "animation_center",
              "roi_coverage": 1.0, "text_regions": 1, "text_area": 0.0537,
              "text_outside_crop": 0.197, "text_cut_by_crop": 1.0, "text_cut_area": 0.0537}
    live = dict(cached, measured_by=after, text_area=0.0536, text_cut_area=0.0536)
    assert measurement_diff(cached, live, tolerance) == (
        {}, {"text_area": (0.0537, 0.0536), "text_cut_area": (0.0537, 0.0536)})
    assert measurement_diff(cached, live)[0]                   # no pin: exact, as before
    for k, v in (("text_regions", 2), ("roi_source", "saliency"), ("text_cut_by_crop", 0.5),
                 ("short_side", 719), ("roi_coverage", 0.999)):
        assert k in measurement_diff(cached, dict(live, **{k: v}), tolerance)[0], k
    assert "text_area" in measurement_diff(cached, dict(live, text_area=None), tolerance)[0]
    # 1 px of every edge of one 504x98 box is ~0.0013 of the frame: 0.0531
    # (six pixels' worth of a 504 px side) is not noise
    assert measurement_diff(cached, dict(live, text_area=0.0521), tolerance)[0] == {
        "text_area": (0.0537, 0.0521)}


def test_device_noise_is_sized_by_box_geometry_and_a_real_change_stays_red():
    """CF-0754, on a stand-in of shot 50 (its five live boxes, a synthetic
    dark card): the move 1854Z/0702Z/0839Z saw is inside one pixel of every
    edge, and what a real change does to the same frame is not."""
    size, window = SHOT50_SIZE, SHOT50_WINDOW
    regions = _regions_px(SHOT50_BOXES_PX, size)
    with tempfile.TemporaryDirectory() as tmp:
        frame = _card_frame(Path(tmp) / "card.png", SHOT50_BOXES_PX, size)
        tolerance = device_noise_tolerance(regions, window, size, frame)
        assert set(tolerance) == set(DEVICE_NOISY_FIELDS), tolerance
        # the old fixed 0.0005 is under one pixel row of the 589 px box
        assert tolerance["text_area"] > 588.8 / (1280 * 720) > 0.0005, tolerance
        bad, tolerated = measurement_diff(SHOT50_CACHED, SHOT50_LIVE, tolerance)
        assert not bad and set(tolerated) == set(DEVICE_NOISY_FIELDS), (bad, tolerated)
        assert measurement_diff(SHOT50_CACHED, SHOT50_LIVE)[0]     # no pin: exact

        base = _measure(regions, window, size, frame)

        def red(changed, frame_=frame, window_=window):
            """The fields a real change moves beyond device noise."""
            moved = dict(SHOT50_LIVE, **_measure(changed, window_, size, frame_))
            return set(measurement_diff(dict(SHOT50_LIVE, **base), moved, tolerance)[0])
        # a Vision revision that pads its boxes by 4 px
        # (the share outside the window barely moves: area grows inside and out)
        assert {"text_area", "text_cut_area"} <= red(moved_regions(regions, size, 4))
        # the window from a 4:5 aspect (0.2472 -> 0.0283)
        assert "text_outside_crop" in red(regions, window_=smart_crop.delivered_window(
            size, (0.4891, 0.5), 1.0, 4, 5, "cover"))
        # a card whose glyphs are thicker (or an ink level read lower)
        thicker = _card_frame(Path(tmp) / "thick.png", SHOT50_BOXES_PX, size, ink_rows=0.14)
        assert "card_ink_fraction" in red(regions, frame_=thicker)


def _live_pool():
    """CF-0505: a live monitor (the batch's sources and the pool's stale-stamp line, a live re-probe of real shots). None in the suite, which prints why;
    FI_TESTS_LIVE=1 (or a real batch's RUNLOG_BATCH) reads the live pool."""
    if live_only("test_usability_cache_freshness.py::_live_pool"):
        return None
    return factory_root() / "shared" / "footage"


def indexes():
    pool = _live_pool()
    return sorted(pool.glob("*.shots.json")) if pool and pool.is_dir() else []


def test_probe_records_what_measured_it():
    """Without a stamp there is nothing for resolve_anchors.py to compare, and
    the cache goes stale silently again. Vision and ffmpeg are stubbed out -
    this is about the bookkeeping, not the picture."""
    original = (usability_probe.vision_client.find_roi,
                usability_probe.vision_client.text_regions,
                usability_probe.qc_asset.luma_stats)
    # CF-0275: `roi` is part of what find_roi() has always returned; the stub
    # needs it now because the probe also asks where the delivered 9:16 window
    # would sit, and that window is built from the ROI's own centre.
    usability_probe.vision_client.find_roi = lambda *a, **k: {
        "source_size": {"width": 1280, "height": 720},
        "roi": {"x": 400, "y": 150, "width": 300, "height": 300},
        "roi_source": "saliency", "roi_coverage": 0.641}
    usability_probe.vision_client.text_regions = lambda *a, **k: []
    usability_probe.qc_asset.luma_stats = lambda *a, **k: (0.0, 63.1)
    try:
        cached = usability_probe.probe_usability("nowhere.png")
    finally:
        (usability_probe.vision_client.find_roi,
         usability_probe.vision_client.text_regions,
         usability_probe.qc_asset.luma_stats) = original
    assert cached["measured_by"] == cache_fingerprint.usability_fingerprint()
    assert cached["measured_by"] is not None
    # The measurements themselves are untouched by the stamp (CF-0029's point:
    # raw numbers, so a threshold change still needs no re-index).
    assert cached["roi_coverage"] == 0.641 and cached["mean_luma"] == 63.1
    # CF-0275: a frame Vision found no text on says so with a count and
    # explicit nulls - "measured, nothing there" is not "never asked".
    assert cached["text_regions"] == 0 and cached["text_cut_area"] is None


def stale_measurements(paths, current):
    """`name#index (stamp)` for every cached measurement in `paths` whose
    stamp does not name the code measuring now. CF-0406: a legacy whole-file
    stamp paired with today's key (cache_fingerprint.LEGACY_STAMPS) is fresh."""
    stale = []
    for path in paths:
        for shot in json.load(open(path))["shots"]:
            cached = shot.get("usable_cached")
            if cached and not cache_fingerprint.stamp_is_current(
                    cached.get("measured_by"), current):
                stale.append(f"{path.name}#{shot['index']} "
                             f"({cached.get('measured_by') or 'unstamped'})")
    return stale


def batch_sources(batch_dir=None, footage=None):
    """The indexes of the sources the current batch fetched, or None when
    there is no batch to speak of: `$RUNLOG_BATCH` unset, or a batch that has
    no `01b-footage-index.json` yet - which is every batch during
    `pool-maintenance`, since that stage runs before the Footage Indexer."""
    batch_dir = batch_dir or os.environ.get("RUNLOG_BATCH")
    if not batch_dir:
        return None
    footage = footage or _live_pool()
    if footage is None:
        return None
    index = Path(batch_dir) / "01b-footage-index.json"
    if not index.exists():
        return None
    ids = []
    for entry in json.load(open(index)).get("fetched") or []:
        vid = entry.get("video_id") or Path(entry.get("path", "")).stem
        if vid and vid not in ids:
            ids.append(vid)
    return [footage / f"{vid}.shots.json" for vid in ids
            if (footage / f"{vid}.shots.json").exists()]


def batch_stale_message(stale, sources, current):
    """What a stale batch source says: the few indexes of this batch, by name,
    and nothing about the pool."""
    return (
        f"{len(stale)} cached measurements of this batch's sources were made by "
        f"other code than this checkout's ({current}): "
        f"{stale[:5]}{' ...' if len(stale) > 5 else ''}\n"
        f"resolve_anchors.py measures those candidates live, so the batch is "
        f"safe, only slower. A source this batch indexed itself should carry "
        f"today's stamp - look at why it does not. If a remeasure is wanted, it "
        f"is these sources only, never the pool (CF-0410): "
        f"{REMEASURE} {' '.join('shared/footage/' + p.name for p in sources)}")


def pool_report(paths, current):
    """One line on the whole pool, for `pool-maintenance`'s note."""
    stale = stale_measurements(paths, current)
    if not stale:
        return f"usability: fresh ({len(paths)} indexes)"
    return (f"usability: stale, not remeasured - {len(stale)} measurements in "
            f"{len({s.split('#')[0] for s in stale})} of {len(paths)} indexes "
            f"carry another stamp than {current}; resolve_anchors.py measures "
            f"them live (CF-0410, the pool is transient - CF-0358)")


def test_this_batch_sources_were_measured_by_this_code():
    """The sources of the current batch, in milliseconds. These are the ones
    a batch's videos are cut from and the ones its indexer just measured, so
    a stale stamp here is either a source reused from the pool (safe, slower)
    or an indexer that measured with other code than the editor keys on - the
    second is a defect. Either way the answer names a handful of sources."""
    sources = batch_sources()
    if sources is None:
        print("  NOTE: no batch with an 01b-footage-index.json in $RUNLOG_BATCH "
              "- no batch sources to check (the pool is reported below)")
        return
    if not sources:
        print("  NOTE: the batch's fetched sources have no index in "
              "shared/footage - nothing checked")
        return
    current = cache_fingerprint.usability_fingerprint()
    stale = stale_measurements(sources, current)
    assert not stale, batch_stale_message(stale, sources, current)


def test_the_pool_is_reported_not_owed_a_remeasure():
    """CF-0410: the rest of the pool is counted, never failed on and never
    handed a remeasure command. Pinned on a synthetic pool - a fresh, a legacy
    and a stale stamp - and then run on the real one, whose line is printed
    for `pool-maintenance`'s `stage-done --note`."""
    current = cache_fingerprint.usability_fingerprint()
    assert current is not None, "no usability key - code_reach.py not beside video-editor?"
    legacy = next((old for old, new in cache_fingerprint.LEGACY_STAMPS.items()
                   if new == current), None)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shots = [{"index": 0, "usable_cached": {"measured_by": current}},
                 {"index": 1, "usable_cached": {"measured_by": "000000000000"}},
                 {"index": 2}]
        if legacy:
            shots.append({"index": 3, "usable_cached": {"measured_by": legacy}})
        (tmp / "aaa.shots.json").write_text(json.dumps({"shots": shots}))
        (tmp / "bbb.shots.json").write_text(json.dumps({"shots": shots[:1]}))
        pool = sorted(tmp.glob("*.shots.json"))
        assert stale_measurements(pool, current) == ["aaa.shots.json#1 (000000000000)"]
        line = pool_report(pool, current)
        assert line.startswith("usability: stale, not remeasured"), line
        assert "1 measurements in 1 of 2 indexes" in line, line
        assert REMEASURE.rsplit("/", 1)[-1] not in line and "*" not in line, line

        # The batch half: only the batch's own sources, by name, never a glob.
        batch = tmp / "batch"
        batch.mkdir()
        (batch / "01b-footage-index.json").write_text(json.dumps({"fetched": [
            {"video_id": "aaa", "path": str(tmp / "aaa.mp4")},
            {"video_id": "aaa", "path": str(tmp / "aaa.mp4")},
            {"video_id": "zzz", "path": str(tmp / "zzz.mp4")}]}))
        sources = batch_sources(batch, tmp)
        assert [p.name for p in sources] == ["aaa.shots.json"], sources
        message = batch_stale_message(stale_measurements(sources, current),
                                      sources, current)
        assert message.endswith(f"{REMEASURE} shared/footage/aaa.shots.json"), message
        assert "*" not in message and "bbb" not in message, message
        assert batch_sources(tmp / "no-such-batch", tmp) is None

    if not indexes():
        print("  NOTE: no shared/footage indexes present - pool not reported")
        return
    print(f"  NOTE: {pool_report(indexes(), current)}")


def test_cache_agrees_with_a_live_probe_on_real_shots():
    """The check the stamp cannot make: run the probe again, now, on real
    frames of real footage and compare it with what is stored. A stamp only
    says the source files match; this says the measurement does.

    Slow on purpose (a few seconds of Vision per shot) and small on purpose -
    three shots covering the three paths through the probe."""
    pool = _live_pool()
    if pool is None:
        return
    index_path = pool / f"{LIVE_PROBE_SOURCE}.shots.json"
    video = pool / f"{LIVE_PROBE_SOURCE}.mp4"
    if not (index_path.exists() and video.exists()):
        print(f"  NOTE: {LIVE_PROBE_SOURCE} footage absent - nothing checked")
        return
    shots = json.load(open(index_path))["shots"]
    by_index = {s["index"]: s for s in shots}
    picked = [by_index[i] for i in LIVE_PROBE_SHOTS if i in by_index]
    assert len(picked) == len(LIVE_PROBE_SHOTS), "index no longer has those shots"

    with tempfile.TemporaryDirectory() as tmp:
        frames = usability_probe.extract_full_frames(video, picked, Path(tmp))
        for shot, frame in zip(picked, frames):
            assert frame is not None, f"no frame extracted for shot {shot['index']}"
            live = usability_probe.probe_usability(frame)
            cached = shot.get("usable_cached")
            assert cached, (
                f"shot {shot['index']} has no cached usability at all - it "
                f"would cost a cut() rather than give a wrong answer, but the "
                f"index is not what it should be")
            # CF-0406: the stamp through LEGACY_STAMPS (an old whole-file stamp
            # that names today's reachable code is current), the numbers as
            # they are.
            if not cache_fingerprint.stamp_is_current(
                    cached.get("measured_by"), live["measured_by"]):
                # CF-0410: a stamp from other code may legitimately give other
                # numbers, and this source is part of the transient pool - it
                # is not remeasured to make this test compare something.
                print(f"  NOTE: shot {shot['index']} measured by "
                      f"{cached.get('measured_by')}, not {live['measured_by']} "
                      f"- stale, not remeasured; numbers not compared")
                continue
            noise = crosses_device_pin(cached.get("measured_by"), live["measured_by"])
            tolerance = None
            if noise and any(cached.get(k) != live.get(k) for k in DEVICE_NOISY_FIELDS):
                # CF-0754: sized by this frame's own live boxes, not a fixed fraction
                tolerance = device_noise_tolerance(*probe_geometry(frame), frame=frame)
            bad, tolerated = measurement_diff(cached, live, tolerance)
            if tolerated:
                print(f"  NOTE: shot {shot['index']} measured on another device "
                      f"(device-pin, CF-0711): within {EDGE_JITTER_PX:g} px of every "
                      f"Vision box edge (CF-0754) - "
                      + ", ".join(f"{k} {a} -> {b} (<= {tolerance[k]:.4f})"
                                  for k, (a, b) in tolerated.items()))
            why = (
                f"The cache was measured on another device (device-pin, "
                f"CF-0711), and this move is more than {EDGE_JITTER_PX:g} px of "
                f"every Vision box edge and of the window explains (bounds "
                f"{ {k: round(v, 4) for k, v in (tolerance or {}).items()} }) - a "
                f"change in the measurement itself (a macOS Vision update, "
                f"say), and it needs looking at by hand." if noise else
                f"The stamp names this code on this device, so the measurement "
                f"moved without any code the probe reaches changing - the case "
                f"cache_fingerprint.py cannot see (a macOS Vision update, say), "
                f"and it needs looking at by hand.")
            assert not bad, (
                f"shot {shot['index']}: the cache and a live probe disagree"
                f"{' beyond device noise' if noise else ''}: {bad}\n"
                f"  cached {cached}\n  live   {live}\n{why}")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

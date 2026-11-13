#!/usr/bin/env python3
"""The per-shot usability measurement CF-0029 caches in `shots.json`.

Split out of `index_footage.py` (CF-0048) for two reasons. `remeasure_
usability.py` needs to run exactly this measurement over an existing index
without re-deriving shots or re-embedding them; and `cache_fingerprint.py`
needs a file to hash that *is* the measurement, so that editing the contact
sheet layout or the CLIP call in `index_footage.py` does not invalidate every
cached measurement in the pool for no reason.

Usability (resolution/subject/black-fraction/luma) and caption-band presence
are properties of the shot itself, not of whichever anchor later tries it
(CF-0029) - measured once here instead of recomputed from scratch by every
candidate `resolve_anchors.py` tries against every anchor. Video Editor owns
both the Vision worker (macOS Vision needs pyobjc, which this venv does not
have) and the `qc_asset.py` logic these values are checked against, so this
reaches into its scripts dir rather than duplicating either.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
# CF-0267: the sibling from the root (`_fi_paths`, a name no other repo has -
# `_runlog` here may be the Video Editor's). Imported by name through importlib
# on purpose: it is a path helper of the same kind as `_runlog`/`repo_paths`,
# which the fingerprint import-graph checks exempt by file name, and the
# Video Editor's check (test_stale_usability_cache) does not know this name.
# It decides where the measuring code is, never what is measured.
import importlib  # noqa: E402
VIDEO_EDITOR_SCRIPTS = importlib.import_module("_fi_paths").sibling_scripts("video-editor")
sys.path.insert(0, str(VIDEO_EDITOR_SCRIPTS))
import qc_asset  # noqa: E402 - luma_stats() + card_ink(), so the cache and the real gate never drift
import vision_client  # noqa: E402 - talks to the warm Vision worker (CF-0029 step 3)

# CF-0275: `smart_crop` gives this file focus_point/delivered_window/text_kept -
# the window build_render_plan.framing() actually points the renderer at, and a
# second copy of that formula is precisely how CF-0033 happened. Importing it
# here needs two lines of preparation, and the reason they are *here* matters.
#
# `smart_crop.py` does `from _runlog import runlog, video_script, video_attempt`
# at module level, for its own CLI decorator. In an indexer process `_runlog`
# resolves to this repo's file, which has neither name, so the import raises -
# `detect_text_band.py` works around the same hazard with a `try/except
# ImportError` falling back to exactly the two definitions below. The shim
# lives here rather than in this repo's `_runlog.py` for tidiness only: since
# CF-0387 `_runlog` is opaque to the caption key, and since CF-0406 the
# usability key digests only what the probe's entry points can reach - the
# shim is not in either key.
#
# Both names only ever run on Video Editor's own command line. `video_script`
# is per-video run accounting (CF-0177) and this repo has no per-video ledger,
# so it is `runlog.script` - what detect_text_band's fallback already chose;
# `video_attempt` answers "which attempt of which video is this", and in an
# indexer process the honest answer is "none", which annotates nothing.
import _runlog  # noqa: E402
if not hasattr(_runlog, "video_script"):
    _runlog.video_script = (
        lambda stage, step=None, name=None, video_arg=None, batch_arg=None:
        _runlog.runlog.script(stage, step=step, name=name))
    _runlog.video_attempt = lambda path: {}
import smart_crop  # noqa: E402
import cache_fingerprint  # noqa: E402 - what code took these measurements (CF-0048)
from common import FFMPEG, PROBE_OFFSET  # noqa: E402 - the same offset usable() itself probes at
# CF-0506: the ceiling of one ffmpeg frame grab - Video Editor's constant for
# that class of call (common.py documents it), not a second number for it.
from common import PROBE_FRAME_TIMEOUT_SECONDS  # noqa: E402
from prepare_clip import detect_letterbox  # noqa: E402 - trailers ship pillarboxed/letterboxed;
# prepare_clip.py always crops those bars out before the real check ever sees a frame, so the
# cache has to as well or it reads a shot's own black bars as the shot being unusable.


# qc_asset.py's own CLI default, and what resolve_anchors.py's usable() check
# leaves unoverridden - kept identical here so the cached numbers describe the
# same crop the real check will eventually make.
QC_ASPECT = "1080:1920"


# CF-0047: qc_asset.py's own strictest near-black ceiling. Under it no
# darkness gate anywhere in the pipeline can fire, so there is nothing for the
# ink measurement to decide and it is not taken; at or above it some caller's
# ceiling might, and resolve_anchors.py's pre-filter needs the number to tell
# a legitimately dark title card from a dead frame without paying for a cut.
# Deliberately the strictest of the ceilings in use rather than the loosest,
# so the cache answers for every caller, not just today's. Measured cost on
# this repo's pool: 84 of 688 shots (12%) pay one extra accurate-mode Vision
# text scan; the other 88% pay nothing at all.
INK_PROBE_BLACK = qc_asset.MAX_BLACK_FRACTION


# CF-0275: how much of a text region has to fall on the far side of the crop
# window's edge before that region counts as *cut* rather than as grazed.
#
# Vision's box is a little larger than the glyphs inside it, and the window's
# edge is a float, so a region that ends exactly at the edge routinely reports
# a fraction of a percent on the other side. That is not a severed word. Two
# percent of a text line's area at 1080p is roughly a third of one character's
# width - below that the render shows a whole line with a hair of padding
# missing, at or above it the viewer sees a glyph cut in half, which is the
# defect this measurement exists to find ("...UING" on -3NpUXI5juI shot 9).
# A region counts as cut when *both* sides hold at least this much of it, so a
# line that is 99% outside the window is not "cut" either - it is gone, and
# `text_outside_crop` is the number that says so.
CUT_EDGE_EPSILON = 0.02


def text_against_window(frame_path, vision):
    """CF-0275: what the delivered 9:16 window does to this frame's own text.

    The defect this answers (batch `example-film/2026-09-17T1901Z`,
    `-3NpUXI5juI` shots 9 and 54) is a split-screen: a commentary video with
    the host in the right half of a 16:9 frame and an article or a phone
    screenshot in the left half. `cover` to 9:16 keeps a ~56%-wide strip
    centred on the host's face, so the article is not removed - it is sliced
    down its middle, and the montage shows half-words under our own captions.
    Nothing in the cache could see it: `roi_coverage` is 0.75/0.66 (the face
    survives beautifully, which is the whole point), `card_text_hit_rate` is
    0.0 (the text is half the frame but does not dominate it) and
    `caption_hit_rate` 1.0 only ever moves the *bottom* edge.

    Two numbers, because they answer two different questions and the threshold
    belongs to whoever reads them (CF-0029: the cache holds measurements, not
    verdicts):

      `text_outside_crop` - share of the recognised text's *area* that the
        window does not show. High and alone it means "there was text and the
        crop dropped it", which a title card's severed wordmark and an
        untouched sign at the frame's edge both produce.

      `text_cut_by_crop` - share of text *regions* the window's edge runs
        through, each side holding at least CUT_EDGE_EPSILON of the region.
        This is the one that separates a panel sliced in half from text that
        merely fell outside: a region wholly outside the window is dropped
        cleanly and reads fine, a region the edge crosses is a half-word.

      `text_cut_area` - the same severed regions as a fraction of the *frame*,
        not of the regions. A share of a count is meaningless at the counts
        Vision actually returns, and it is not a subtlety: measured on this
        pool, `-3NpUXI5juI` shots 40 and 42 are ordinary talking heads whose
        single recognised region is the host's own SUBSCRIBE banner, and one
        severed banner out of one region is `text_cut_by_crop` 1.0 - a higher
        number than either shot of the actual defect. In frame area the same
        banner is 0.017 against shot 9's 0.11, which is the comparison that
        holds. Kept alongside the count share rather than instead of it: the
        count is what the task asked to see, and the two disagreeing about a
        frame is itself informative.

    The window is the one `build_render_plan.framing()` points the renderer
    at - `smart_crop.focus_point()` + `delivered_window()` at `fit: cover` -
    not the per-frame optimum `analyse()["crop"]` reports, for exactly the
    reason CF-0155 gives about `roi_coverage`: no render ever uses the
    per-frame optimum.

    Deliberately measured on the same full frame the rest of `usable_cached`
    describes, *before* `prepare_clip.py`'s caption crop. The cache is one
    frame's measurement and `crop_bottom_cached` is a separate, separately
    stamped one; folding them together here would make this number depend on
    a measurement it is not fingerprinted with. The direction of the error is
    known and safe for the reader: a shot with a thick caption crop has some
    of its bottom text counted as kept when the render will not show it, so
    `text_outside_crop` is a floor, never an overstatement. The defect itself
    is a *horizontal* cut, which the bottom crop cannot touch either way.

    Returns the three fields as a dict. `text_regions` is always an integer,
    so "measured, this frame has no text" (0) stays distinguishable from "this
    index never asked" (key absent) - the same rule CF-0047 set for
    `card_ink_fraction`, and the one the reader's fallback depends on.
    """
    regions = vision_client.text_regions(str(frame_path), level=0)
    size = (vision["source_size"]["width"], vision["source_size"]["height"])
    aspect_w, aspect_h = (int(v) for v in QC_ASPECT.split(":"))
    window = smart_crop.delivered_window(
        size, smart_crop.focus_point(vision), vision.get("zoom", 1.0),
        aspect_w, aspect_h, "cover")
    measured = {"text_regions": len(regions)}
    if not regions:
        for key in ("text_area", "text_outside_crop", "text_cut_by_crop",
                    "text_cut_area"):
            measured[key] = None
        return measured
    kept = smart_crop.text_kept(regions, window, size)
    if kept is None:
        # Regions with no area at all: text_kept() has nothing to divide by and
        # says so. Vision is not known to return such a box, and if it starts
        # to, "no text worth measuring" is the honest reading rather than a
        # ZeroDivisionError in the middle of a pool remeasure.
        for key in ("text_area", "text_outside_crop", "text_cut_by_crop",
                    "text_cut_area"):
            measured[key] = None
        return measured
    cut_count, cut_area = cut_regions(regions, window, size)
    measured["text_area"] = round(
        sum(r["width"] * r["height"] for r in regions), 4)
    measured["text_outside_crop"] = round(1.0 - kept, 4)
    measured["text_cut_by_crop"] = round(cut_count / len(regions), 4)
    measured["text_cut_area"] = round(cut_area, 4)
    return measured


def cut_regions(regions, window, size):
    """(how many of `regions` straddle `window`'s edge, what fraction of the
    frame they cover).

    `regions` are Vision's fractional boxes (detect_text_band.text_regions),
    `window` is (x, y, w, h) in source pixels from smart_crop.delivered_
    window(), `size` is (width, height) of the same frame. Pure arithmetic,
    like smart_crop.text_kept() next to which the area half of this pair
    lives, so both are testable without Vision or a frame.

    Overlapping boxes are counted twice, exactly as card_frame.text_area()
    counts them - Vision splits one line into several boxes that can share a
    pixel or two, and de-duplicating them would be a second, unstated model
    of what a text line is.
    """
    frame_w, frame_h = size
    wx, wy, ww, wh = window
    count, area_cut = 0, 0.0
    for region in regions:
        x0, x1 = region["left"] * frame_w, (region["left"] + region["width"]) * frame_w
        y0, y1 = region["top"] * frame_h, region["bottom"] * frame_h
        area = (x1 - x0) * (y1 - y0)
        if area <= 0:
            continue
        inside = (max(0.0, min(x1, wx + ww) - max(x0, wx))
                  * max(0.0, min(y1, wy + wh) - max(y0, wy)))
        if CUT_EDGE_EPSILON <= inside / area <= 1.0 - CUT_EDGE_EPSILON:
            count += 1
            area_cut += area
    return count, area_cut / (frame_w * frame_h)


def extract_full_frames(path, shots, out_dir):
    """One frame per shot, at the source's native resolution, near the shot's
    own start rather than its midpoint.

    Two things CF-0029's usability cache has to match about the real check:
    resolution (the 336px-wide frame extract_frames() makes is scaled down
    for fast CLIP embedding, nowhere near a real clip's resolution - this is
    a second, unscaled extraction) and *where in the shot* it looks. A cut
    candidate always starts at the shot's own start (match_anchors.py hands
    back shots.json's own start/end), and usable()'s first probe is at
    PROBE_OFFSET into that cut - so probing the shot's true midpoint instead
    systematically disagreed with the real check on any shot whose lighting
    or framing changes across its span (this trailer has plenty - a shot
    that opens on a lit face and fades to black by its middle read as
    "unusable" here while the actual candidate cut, which never gets past
    its first second, would have passed). Matching the real probe's offset
    is what keeps the pre-filter's opinion close to usable()'s.

    prepare_clip.py also crops the source's own letterbox/pillarbox bars out
    of every candidate before usable() ever sees a frame. Skipping that here
    would read a shot's own black bars as the shot being mostly black;
    detect_letterbox() runs the same cropdetect prepare_clip.py runs, so the
    cached measurement describes the same cropped frame the real check
    eventually measures.

    CF-0506: each grab runs under PROBE_FRAME_TIMEOUT_SECONDS. A grab that
    hangs (a broken file) is that shot's frame not extracted - None, as when
    ffmpeg fails - and a partial file it left is removed; the other shots of
    the source are still extracted.
    """
    frames = []
    for i, shot in enumerate(shots):
        t = min(shot["start"] + PROBE_OFFSET, max(shot["start"], shot["end"] - 0.05))
        bars = detect_letterbox(str(path), shot["start"], shot["end"] - shot["start"])
        cmd = [FFMPEG, "-y", "-nostdin", "-v", "error", "-ss", str(t), "-i", str(path)]
        if bars:
            cmd += ["-vf", bars]
        f = out_dir / f"shot_{i:03d}_full.png"
        cmd += ["-frames:v", "1", str(f)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=PROBE_FRAME_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            f.unlink(missing_ok=True)
        frames.append(f if f.exists() else None)
    return frames


def probe_usability(frame_path):
    """The same measurements qc_asset.py makes on a candidate clip, run once
    here on the shot's own representative frame (CF-0029) instead of once per
    candidate that later tries this shot. Raw measurements are cached, not a
    baked pass/fail - resolve_anchors.py's pre-filter re-applies whatever
    thresholds that particular run actually uses, so a threshold change never
    needs a re-index to take effect."""
    vision = vision_client.find_roi(str(frame_path), QC_ASPECT)
    black, mean_luma = qc_asset.luma_stats(str(frame_path))
    size = vision["source_size"]
    cached = {
        # CF-0048: which code made the four numbers below. A threshold change
        # still needs no re-index - that was CF-0029's point and it stands -
        # but a change to the measuring code makes them describe a measurement
        # this pipeline no longer takes, and the reader has to be able to see
        # that. Written first so it is the first thing visible on the shot in
        # a diff of shots.json.
        "measured_by": cache_fingerprint.usability_fingerprint(),
        "short_side": min(size["width"], size["height"]),
        # CF-0078: `short_side` alone cannot tell a 608px-wide portrait source
        # from a 608px-tall landscape one apart, and the pre-filter
        # (resolve_anchors.py::cached_verdict()) needs the orientation to
        # predict the *post-crop* delivery geometry (CF-0104), not just
        # compare one cached number to a flat floor. Cheap to keep: `size` is
        # already `vision["source_size"]`, read off the same frame
        # `short_side` uses.
        "width": size["width"],
        "height": size["height"],
        "roi_source": vision["roi_source"],
        "roi_coverage": vision["roi_coverage"],
        "black_fraction": round(black, 3),
        "mean_luma": round(mean_luma, 1),
    }
    # CF-0275: one accurate-mode text scan of the whole frame, and what the
    # delivered 9:16 window does to what it finds. Taken on every frame, not
    # only on dark ones like the ink probe below: a split-screen with an
    # article in its left half is a perfectly lit frame, and there is no
    # cheaper measurement that could say in advance whether this frame has
    # text worth asking about.
    cached.update(text_against_window(frame_path, vision))
    # CF-0047: how much of this frame's own on-screen text is lit - the one
    # measurement that separates a gold-on-black title card from a dead frame,
    # both of which read as ~100% near-black above. Taken here only for frames
    # dark enough for that question to arise (see INK_PROBE_BLACK). Written as
    # an explicit null when Vision finds no text, because "measured, nothing
    # legible on screen" and "never measured" are opposite answers to the
    # pre-filter and it distinguishes them by the key's presence.
    if black >= INK_PROBE_BLACK or mean_luma < qc_asset.MIN_MEAN_LUMA:
        ink = qc_asset.card_ink(frame_path)
        cached["card_ink_fraction"] = None if ink is None else round(ink, 4)
    return cached

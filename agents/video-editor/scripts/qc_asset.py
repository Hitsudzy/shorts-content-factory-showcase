#!/usr/bin/env python3
"""Decide whether a still is fit to appear in a video, before it is montaged in.

Three real failures from the first batch motivate each check:
  - a 240px browser crop was upscaled into a 1080-wide slot and looked soft;
  - a frame landed on the top of someone's head, with the face out of shot;
  - a frame was actually a screenshot of a YouTube page - black letterbox plus
    unrelated sidebar thumbnails - and nobody noticed until the video was cut.

Vision catches the second on its own (no faces, no salient object). It does not
catch the third: it happily calls the sidebar thumbnails a salient object, so
the near-black share of the frame is measured separately. Interface screenshots
and letterboxed captures are mostly dead pixels; real photography is not.

Usage: qc_asset.py <image> [--aspect 9:16] [--json]
Exit code 0 = usable, 1 = rejected.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from common import (luma_pixels, MIN_COVERAGE, MIN_SHORT_SIDE, MAX_CONTAIN_UPSCALE,
                     delivery_fit)
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
# CF-0177: `video_script` is this repo's entry-point decorator (the pairing
# per-video events need). It is the same cross-repo import as `video_attempt`
# below, so a shim without it - the indexer's - falls back instead of failing;
# the decorated CLI never runs outside this repo.
try:
    from _runlog import video_script  # noqa: E402
except ImportError:  # pragma: no cover - only the other repo's shim
    video_script = runlog.script
# CF-0159: `video_attempt` is video-editor's own addition to the shim, and this
# module is imported across repositories (agents/footage-indexer). Requiring the
# addition at module level made that import fail with the indexer's own _runlog
# already in sys.modules, so the indexer would not start at all. It is needed on
# the CLI path only, which never runs outside this repo, so it is imported there.

MAX_BLACK_FRACTION = 0.35
BLACK_LEVEL = 24
# A uniformly dim shot has few *black* pixels and still cannot be read. The
# near-black frame that shipped under "no wide, expensive coverage" passed the
# black-fraction check for exactly this reason.
MIN_MEAN_LUMA = 28

# CF-0047: a title/end card that is legitimately dark - gold on black - fails
# both checks above for precisely the reason it was designed that way, and a
# dead frame fails them for the opposite reason. Neither number can separate
# the two, because both measure the whole frame and the whole frame really is
# black in both cases: 0.951/4.9 for the real "Wren Hollow" card
# (ZZ_urA56pJE shot 50) against 0.987-1.000 / 0.0-2.6 for the dead frames
# (f_bKjZeJBBI shots 1/7/19, 6fcoM7Q348Q shot 0). That is why loosening
# either constant was rejected by measurement in CF-0035 - the two classes
# overlap on the axis those constants live on.
#
# What does separate them is the only part of a card that is meant to be lit:
# its text. Measured across every one of the 28 dark card frames in this
# repo's footage pool, as the share of pixels inside Vision's accurate-mode
# text boxes reaching CARD_INK_LEVEL:
#   - 19 legitimate dark cards:  0.0972 .. 0.5246
#   - f_bKjZeJBBI 7 and 19:      0.0000, 0.0000 (a navy title mid-fade-in,
#                                its brightest pixel reaching luma 46 / 58)
#   - 6 more, incl. 6fcoM7Q348Q 0 and f_bKjZeJBBI 1: no recognised text at all
# A gap between 0.0000 and 0.0972 is not a threshold squeeze, and it is not
# the same axis as the constants above: it asks whether anything on the frame
# is lit, not how dark the frame is.
#
# CARD_INK_LEVEL is bracketed by that data on both sides rather than picked:
# the brightest pixel any dead frame's text reaches is 58, the dimmest real
# card's ink reaches 129, and the separation is unchanged at every level from
# 48 to 96. It collapses below 40 (at level 32 the dead frames read
# 0.1955/0.1819 against the real card's 0.2241), which is the measured reason
# a card cannot simply be given a lower MIN_MEAN_LUMA.
CARD_INK_LEVEL = 64
MIN_CARD_INK_FRACTION = 0.02

# CF-0094: the ink fraction above is a ratio *inside* the frame's text boxes
# - deliberately, so a small gold title on a large black card is judged by
# its own lettering rather than diluted by the black around it. The price of
# that denominator is that the number carries no idea of how much of the
# frame the text takes, and a streaming platform's corner bug is text too:
# SJVmeJaS44s s8, a fade-to-black with nothing on it but the "Example max" bug,
# read 0.5745 lit and was accepted as a card under three blocks (batch
# 2026-09-03T2037Z, RUN_LOG.txt:26). No arithmetic is wrong there - 57% of
# the bug's own pixels *are* lit. What was missing is the question the
# indexer already asks before it calls a frame a card at all: is this text
# card-sized, and is it where a card puts its text?
#
# Measured on the pool's own probe frames (accurate-mode Vision, the same
# frames the usability cache is built from):
#   platform bugs - "Example Network"/"max" as two boxes (SJVmeJaS44s s8, 1RnyZgfN-JY
#   s5/s8/s17/s21/s23/s36), "EXAMPLESTREAM" as one (9s8gGcvBVIM s3/s4):
#       per-box area 0.0027-0.0056, box centre x 0.90-0.92 / y 0.07-0.16 -
#       the top-right corner, on every frame of a source that carries it
#   card text - eokBqEFiVHs s51 "AND CHANGED / THE WORLD", 6fcoM7Q348Q s3
#   "THIS SUMMER", 7EY3QyPTEso s25 "ONLY ON EXAMPLESTREAM / OCTOBER 1",
#   -xSxaE1ClEE s17/s26/s36/s38, 47P9fKmWbEs s5/s6:
#       per-box area 0.0146-0.62, box centre x 0.45-0.55 / y 0.35-0.62;
#       the smallest single line ("ONLY ON EXAMPLESTREAM") is 0.0146
# Two axes separate them and both are required: a box is a watermark when it
# is *both* smaller than the smallest text the indexer accepts as card text
# (footage-indexer's card_frame.CARD_TEXT_AREA_THRESHOLD, 0.015 - repeated
# here rather than imported because the dependency runs the other way: the
# indexer imports this file) *and* pinned in a corner, its centre within
# CORNER_MARGIN of a vertical edge and of a horizontal edge. Size alone
# would sit 0.0004 from the smallest real line; position alone would drop a
# title legitimately set in a corner. 0.25 is the midpoint of the measured
# gap on both axes (y: bug 0.16 vs card 0.35; x from the right edge: bug
# 0.08-0.10 vs card 0.45). A burned-in caption - bottom *centre* - is neither
# and stays exactly what it was to this measurement; CF-0062 is where
# captions are handled.
WATERMARK_MAX_AREA = 0.015
CORNER_MARGIN = 0.25

# CF-0092: the framing check above (`roi_coverage`) asks whether the 9:16
# cover window *contains* the subject, and on a caption-cropped live shot it
# always does - cover keeps the frame's full height, so there is nothing to
# lose - while the picture is wrong in a way coverage cannot express: the
# crop took the lower 40% of a studio shot (the CNBC desk's static lettering
# and name plates read as burned-in captions, W4mvmBXg9Nc s8/s4/s2/s13 in
# run 2026-09-03T2037Z) and left the heads on the bottom edge of a 634px
# frame under two thirds of empty backdrop, with no room for the window to
# reframe. Two numbers, both measured on the cut clip's face ROI and both
# tied to *our* crop - the same frame reconstructed before the crop has to
# have been fine, exactly as `resolution_lost_to_crop` blames a floor
# failure on the crop only when the source cleared it:
#
#   MIN_CROP_FOOT_MARGIN  - the share of the cropped frame's height left
#       below the face box. 0 means Vision's (frame-clamped) box reaches the
#       crop line, i.e. the chin is cut. Measured on the pool's live shots
#       cut with their cached crop: the chin-cut cases sit at 0.000-0.026
#       (UaWVjS5SId4 s3/s7/s9, 1RnyZgfN-JY s24, F_31ZfVsUlA s2), the nearest
#       intact framing at 0.060-0.071 (with the centre rule catching two of
#       those anyway), and ordinary talking heads at 0.15-0.55.
#   MAX_CROP_SUBJECT_CENTRE - the face box's vertical centre as a share of
#       the cropped height. Past the lower-third line the head sits under a
#       slab of backdrop: the CNBC shots measure 0.71-0.73 after the crop
#       against 0.42-0.43 before it; 47P9fKmWbEs s39, BROAzK8oP9U s59,
#       _LE1L4Huyys s59 measure 0.71-0.82 after against 0.45-0.46 before.
#       The nearest passing faces in the same sample are 0.63-0.64 (with
#       foot margins that pass too, or that fail on their own); a face
#       already low in the *source's* own framing (FfYCVp8hLcg s15: 0.72
#       before an 8% crop, 0.78 after) is not the crop's doing and passes.
MIN_CROP_FOOT_MARGIN = 0.05
MAX_CROP_SUBJECT_CENTRE = 0.66


def luma_stats(path):
    """Fraction of near-black pixels, and mean brightness. Two different
    failures: a letterboxed screenshot is part black, a murky shot is all dim."""
    with Image.open(path) as im:
        pixels = luma_pixels(im.convert("L").resize((160, 160)))
    black = sum(1 for p in pixels if p <= BLACK_LEVEL) / len(pixels)
    return black, sum(pixels) / len(pixels)


def lifted_luma(path, gain):
    """CF-0436: mean brightness of `path` once lifted by `gain` - what a
    `luma_lift` block puts on screen. PIL's ImageEnhance.Brightness is a
    blend with black, i.e. every channel times `gain`, clipped at 255 - the
    same arithmetic as the renderer's CSS `brightness(gain)`. Measured the
    way luma_stats() measures the frame it lifts (L, 160x160), so the two
    numbers compare."""
    from PIL import ImageEnhance
    with Image.open(path) as im:
        lifted = ImageEnhance.Brightness(im.convert("RGB")).enhance(float(gain))
        pixels = luma_pixels(lifted.convert("L").resize((160, 160)))
    return sum(pixels) / len(pixels)


def ink_fraction(values, level=CARD_INK_LEVEL):
    """Share of `values` - luma samples taken from inside a frame's
    recognised text boxes - that reach `level`.

    Pure, so the measured numbers in the comment above are testable against
    fixed real data without Vision or an image on disk.
    """
    values = list(values)
    if not values:
        return 0.0
    return sum(1 for v in values if v >= level) / len(values)


def text_ink_pixels(path, regions):
    """Luma of every pixel inside `path`'s recognised text boxes."""
    pixels = []
    with Image.open(path) as im:
        grey = im.convert("L")
        w, h = grey.size
        for r in regions:
            x0, x1 = int(max(0, r["left"] * w)), int(min(w, (r["left"] + r["width"]) * w))
            y0, y1 = int(max(0, r["top"] * h)), int(min(h, r["bottom"] * h))
            if x1 <= x0 or y1 <= y0:
                continue
            pixels += luma_pixels(grey.crop((x0, y0, x1, y1)))
    return pixels


def is_watermark_box(region):
    """A text box shaped like a platform's corner bug (CF-0094): smaller
    than any card text and pinned in a corner. Pure geometry on one of
    text_regions()'s dicts, so the rule is testable on measured boxes
    without Vision."""
    width = region["width"]
    height = region["bottom"] - region["top"]
    if width * height >= WATERMARK_MAX_AREA:
        return False
    cx = region["left"] + width / 2
    cy = region["top"] + height / 2
    return (min(cx, 1.0 - cx) <= CORNER_MARGIN
            and min(cy, 1.0 - cy) <= CORNER_MARGIN)


def card_text_regions(regions):
    """The boxes that are the card's own text - everything Vision found
    except watermark-shaped boxes (CF-0094)."""
    return [r for r in regions if not is_watermark_box(r)]


def card_text_ink(path):
    """How much of this frame's own on-screen text is actually lit
    (CF-0047), and what was counted as that text (CF-0094).

    `ink` is None when the frame carries no card text at all - which is
    itself the answer for a shot flagged as a card with nothing legible on
    it at this instant, and is how 6fcoM7Q348Q shot 0 and f_bKjZeJBBI shot 1
    stay rejected. Since CF-0094 a frame whose only text is a platform bug in
    the corner reads the same way: the bug is not the card's text, and a
    fade-to-black under it is as empty as one without it (SJVmeJaS44s s8).
    `text_boxes`/`watermark_boxes` say which of the two happened, so the
    verdict can name it.

    Accurate mode (level=0), for the reason CF-0010 established: fast mode
    reads texture as text.
    """
    import vision_client
    regions = vision_client.text_regions(str(path), level=0)
    content = card_text_regions(regions)
    pixels = text_ink_pixels(path, content)
    return {"ink": ink_fraction(pixels) if pixels else None,
            "text_boxes": len(regions),
            "watermark_boxes": len(regions) - len(content)}


def card_ink(path):
    """card_text_ink()'s `ink` alone - the number the usability cache stores
    (footage-indexer's usability_probe.py) and evaluate() consumes."""
    return card_text_ink(path)["ink"]


def analyse(path, aspect):
    """Face/saliency ROI for `path`, via the warm Vision worker (CF-0029).

    This used to spawn smart_crop.py fresh for every single probe frame,
    which paid macOS Vision's ~0.7s cold start on every call - resolve_
    anchors.py's usable() alone made two of these per candidate. vision_
    client talks to a long-lived worker process instead, and falls back to
    a local call if that worker cannot be reached at all.
    """
    import vision_client
    try:
        return vision_client.find_roi(path, aspect)
    except Exception as e:
        return {"error": str(e)}


def against_window(vision, aspect, focus, zoom, fit="cover"):
    """Re-measure `vision`'s coverage against the window the render will
    actually show, and record which window that was (CF-0155).

    `analyse()` reports how much of the subject *this frame's own* optimal
    9:16 window would keep. The renderer never computes such a window per
    frame: build_render_plan.py points the asset once, from the frame at
    PROBE_OFFSET, and holds that framing for the whole clip. So for every
    other frame of that clip the number `analyse()` reports answers "this
    frame could have been cropped well", which nothing downstream uses,
    instead of "the subject is inside the rectangle the viewer sees".

    `focus`/`zoom` are that rectangle, as build_render_plan.framing() states
    it; `"self"` (see main()) is the frame pointing at itself, which is what
    the planner does with the frame it takes the framing from. Only
    `roi_coverage` changes - the resolution floor still reads the frame's own
    `crop`, the darkness checks its own pixels - so the verdict moves for one
    reason and evaluate() stays the only place a verdict is decided.

    Returns the mutated `vision`; the frame's own number is kept as
    `roi_coverage_own` so a measurement can compare the two.
    """
    import smart_crop  # lazy: CF-0029/CF-0159, this module is imported across repos
    aw, ah = (int(v) for v in aspect.split(":"))
    size = vision["source_size"]
    if focus == "self":
        focus = smart_crop.focus_point(vision)
        zoom = vision.get("zoom", 1.0)
    window = smart_crop.delivered_window(
        (size["width"], size["height"]), focus, zoom, aw, ah, fit)
    # CF-0292: `subject_coverage` and not `window_coverage` - for a frame with
    # several faces the honest question is how much of *a person* the window
    # keeps, not how much of the union box, which for two people at opposite
    # edges of a wide shot is mostly the air between them. One rule, shared
    # with the planner, in smart_crop.
    coverage = smart_crop.subject_coverage(vision, focus, zoom, aw, ah, fit)
    vision["roi_coverage_own"] = vision["roi_coverage"]
    vision["roi_coverage"] = round(coverage, 3)
    vision["coverage_window"] = {
        "focus": {"x": round(focus[0], 4), "y": round(focus[1], 4)},
        "zoom": zoom, "fit": fit,
        "x": round(window[0]), "y": round(window[1]),
        "width": round(window[2]), "height": round(window[3]),
    }
    return vision


def crop_framing(vision, caption_crop, min_foot_margin=MIN_CROP_FOOT_MARGIN,
                 max_centre=MAX_CROP_SUBJECT_CENTRE):
    """CF-0092: did our own caption crop push the faces to the bottom of the
    frame? Judged on the cut clip's face ROI (smart_crop.analyse()'s `roi`,
    measured *after* prepare_clip.py's crop, which is the only frame the
    gate ever sees) and on the same geometry reconstructed before the crop:
    the band comes off the bottom, so every pixel above it keeps its y and
    the pre-crop height is `height / (1 - caption_crop)`.

    Returns None when there is nothing to judge - no caption crop was
    applied, Vision found no face (a saliency box legitimately runs to the
    bottom edge: bodies do), or the caller's `vision` carries no `roi` at
    all (the cache pre-filter's placeholder dict; "unknown" is not "doomed").
    Otherwise a dict whose `lost_to_crop` says whether the crop is to blame:
    the face is pinned to the crop line or sits in the lower third *now*
    and was neither before the crop. Pure, so the pool numbers behind the
    thresholds above are testable without Vision or a clip on disk.
    """
    if not caption_crop or caption_crop >= 1.0:
        return None
    roi = vision.get("roi")
    if not roi or vision.get("roi_source") != "faces":
        return None
    height = vision["source_size"]["height"]
    if not height or not roi.get("height"):
        return None
    bottom = roi["y"] + roi["height"]
    centre_px = roi["y"] + roi["height"] / 2
    height_before = height / (1 - caption_crop)
    foot = (height - bottom) / height
    foot_before = (height_before - bottom) / height_before
    centre = centre_px / height
    centre_before = centre_px / height_before

    pinned = foot < min_foot_margin and foot_before >= min_foot_margin
    sunk = centre > max_centre and centre_before <= max_centre
    return {
        "foot_margin": round(foot, 3), "foot_margin_before_crop": round(foot_before, 3),
        "centre": round(centre, 3), "centre_before_crop": round(centre_before, 3),
        "pinned": pinned, "sunk": sunk, "lost_to_crop": pinned or sunk,
    }


def evaluate(vision, black, mean_luma, min_short_side, min_coverage, max_black,
             min_mean_luma, card_ink=None, caption_crop=None,
             short_side_before_crop=None, fit="cover", target_height=1920,
             max_contain_upscale=MAX_CONTAIN_UPSCALE):
    """The actual pass/fail logic, apart from where `vision`/`black`/
    `mean_luma` came from (CF-0029: index_footage.py caches these same
    measurements per shot, and resolve_anchors.py's pre-filter re-applies
    this exact function to the cache instead of re-deriving its own copy of
    the thresholds - one place these can disagree, not two).

    `card_ink` (CF-0047) is the shot's measured ink fraction when - and only
    when - the caller knows this frame is a title/end card and bothered to
    measure it. A lit card is excused the two darkness checks and *nothing
    else*: resolution, subject and framing are applied to it unchanged, and
    every excusal is recorded in `relaxations` so a card never passes
    quietly. None means "not a card, or not measured", and changes nothing.

    `fit` (CF-0104) is the delivery mode this frame will actually be shown
    through - `common.delivery_fit()`'s answer, `"cover"` or `"contain"` -
    and it decides *what* the resolution floor is checked against:

      cover   - `vision["crop"]` (smart_crop.analyse()'s tightened 9:16
                window, when the caller supplied it) or, absent that, the
                frame's own short side - the same number this function
                always compared `min_short_side` against, which happens to
                equal the cover window's height for any source wider than
                9:16 (the common case). `min_short_side` is that floor,
                unchanged (720, CF-0062 variant A).
      contain - there is no crop window; the whole frame is shown, so what
                limits it is how far its own height must be blown up to
                reach `target_height`. `max_contain_upscale` is that ceiling.

    `caption_crop` and `short_side_before_crop` (CF-0062) are what
    prepare_clip.py cut off the bottom of this clip for burned-in captions
    and the short side of the frame it cut it from, when the caller knows
    them - a card can carry a caption crop too (CF-0103's subtitle band).
    They change no verdict. What they change is the name of the failure: a
    source that cleared the relevant floor before this pipeline's own crop
    and failed only because of it is named as such, in either delivery mode.
    The pre-crop size is taken as measured rather than reconstructed from the
    cropped height: prepare_clip.py's floor-to-even makes the reconstruction
    up to 3px low, which on the real pool turned a 720px source at a 720px
    floor into "718, low-res" (ZZ_urA56pJE 21).
    """
    size = vision["source_size"]
    short_side = min(size["width"], size["height"])
    contain = fit == "contain"
    before_crop = short_side_before_crop if caption_crop else None

    if contain:
        # CF-0104: a card is fitted whole (CF-0047) and letterboxed - there
        # is no crop window to measure. `vision["source_size"]["height"]` is
        # already the frame *after* any caption crop (the crop happens at
        # extraction, before this frame is ever measured), same as
        # `short_side` always was for cover.
        delivery_dimension = size["height"]
        contain_upscale = (round(target_height / delivery_dimension, 2)
                            if delivery_dimension else None)
        floor_failed = contain_upscale is None or contain_upscale > max_contain_upscale
        pre_crop_upscale = (target_height / before_crop) if before_crop else None
        lost_to_crop = (floor_failed and pre_crop_upscale is not None
                        and pre_crop_upscale <= max_contain_upscale)
    else:
        # CF-0104: the delivered 9:16 window, not the source's own short
        # side - object-fit:cover always frames the source's full available
        # height once it is wider than 9:16 (CF-0033), so a portrait source
        # close to 9:16 keeps its whole height in the window even when its
        # *width* sits under the floor. `vision["crop"]` is smart_crop.
        # analyse()'s already-tightened cover rect (crop_for_aspect()'s
        # `rect`, zoom folded in); when the caller did not supply one (the
        # cache pre-filter, or a bare vision dict a test built by hand) this
        # falls back to the frame's own short side, which is exactly what
        # this function always compared against and is correct for any
        # source wider than 9:16 - the common case, and the only one any
        # caller without a `crop` has ever exercised.
        crop = vision.get("crop") or {}
        delivery_dimension = crop.get("height", short_side)
        contain_upscale = None
        floor_failed = delivery_dimension < min_short_side
        lost_to_crop = (floor_failed and before_crop is not None
                        and before_crop >= min_short_side)

    # A card whose own text is lit is dark on purpose. One that is dark with
    # nothing lit on it - card_ink None (no text found) or below the floor -
    # gets no excusal at all and fails these checks exactly as before.
    lit_card = card_ink is not None and card_ink >= MIN_CARD_INK_FRACTION

    failures, failed, relaxations = [], [], []
    if floor_failed:
        failed.append("resolution")
        if contain:
            if contain_upscale is None:
                failures.append("resolution: could not measure the frame's height")
            elif lost_to_crop:
                failures.append(
                    f"resolution: contain blows the {delivery_dimension}px frame up "
                    f"x{contain_upscale} to reach {target_height}px "
                    f"(> x{max_contain_upscale} norm) - the source cleared the norm "
                    f"at {before_crop}px and our own {caption_crop:.0%} caption crop "
                    f"(CF-0062/CF-0103) took it over; the shot is not low-res, the "
                    f"crop is what was rejected")
            else:
                failures.append(
                    f"resolution: contain blows the {delivery_dimension}px frame up "
                    f"x{contain_upscale} to reach {target_height}px "
                    f"(> x{max_contain_upscale} norm)")
        elif lost_to_crop:
            failures.append(
                f"resolution: short side {delivery_dimension}px < {min_short_side}px - "
                f"the source cleared the floor at {before_crop}px and our own "
                f"{caption_crop:.0%} caption crop took it under (CF-0062); the "
                f"shot is not low-res, the crop is what was rejected")
        else:
            failures.append(
                f"resolution: short side {delivery_dimension}px < {min_short_side}px")
    if vision["roi_source"] == "none":
        failed.append("subject")
        failures.append("subject: Vision found neither a face nor a salient object")
    if black > max_black:
        if lit_card:
            relaxations.append(
                f"dead pixels: {black:.0%} near-black (> {max_black:.0%}) excused - "
                f"a title/end card with {card_ink:.1%} of its on-screen text lit "
                f"(>= {MIN_CARD_INK_FRACTION:.0%}), i.e. dark by design, not dead")
        else:
            failed.append("black")
            failures.append(
                f"dead pixels: {black:.0%} of the frame is near-black "
                f"(> {max_black:.0%}) - likely a letterbox or UI screenshot")
    if mean_luma < min_mean_luma:
        if lit_card:
            relaxations.append(
                f"too dark to read: mean brightness {mean_luma:.0f} of 255 "
                f"(< {min_mean_luma}) excused - a title/end card with "
                f"{card_ink:.1%} of its on-screen text lit")
        else:
            failed.append("luma")
            failures.append(
                f"too dark to read: mean brightness {mean_luma:.0f} of 255 "
                f"(< {min_mean_luma}) - dim rather than black, so the "
                f"dead-pixel check does not catch it")
    # CF-0296: coverage is "how much of the subject the delivered window
    # keeps", and under `contain` that window is the whole frame - the card is
    # letterboxed, nothing is cut, so there is no share to fall short. Which
    # is exactly what the window-aware path already reports: against_window()
    # builds delivered_window() for this `fit`, and for contain that rectangle
    # is the image, so subject_coverage() is 1.0 by construction for every
    # frame that reaches it. The number this branch reads when no window was
    # given is smart_crop.analyse()'s own, measured on a 9:16 *cover* window -
    # a rectangle a contained card is never shown through. So the two callers
    # disagreed on the same frame: resolve_anchors.usable() passes
    # `--window self` and read 1.0, build_render_plan.inspect_asset() passes
    # none and read 0.344 (block 1 of lf-2026-09-19-008) and 0.264 (block
    # 19) against the 65% floor, and took the whole video down for a window
    # the render never uses - build_render_plan.py sets these blocks
    # `fit: contain, focus 0.5/0.5, zoom 1.0` forty lines later and says so
    # itself ("roi_coverage is not this block's framing question").
    #
    # A card is not let off its own gate by this: what a card has to keep is
    # its text, and that is MIN_CARD_TEXT_KEPT on smart_crop.text_survival()
    # (CF-0047), measured on the delivered framing. `subject` (Vision found
    # nothing at all), resolution/upscale, darkness and ink are unchanged.
    if not contain and vision["roi_coverage"] < min_coverage:
        failed.append("coverage")
        if vision.get("coverage_window"):
            # CF-0155: measured against the window the render actually shows
            # (against_window()), not against this frame's own best crop -
            # the failure says so, because the two answer different questions
            # and only one of them is visible to a viewer.
            failures.append(
                f"framing: the window this block is framed with keeps only "
                f"{vision['roi_coverage']:.0%} of the subject "
                f"(< {min_coverage:.0%}); its own best crop would keep "
                f"{vision.get('roi_coverage_own', 0):.0%}")
        else:
            failures.append(
                f"framing: a focus-aware crop keeps only "
                f"{vision['roi_coverage']:.0%} of the subject (< {min_coverage:.0%})")
    # CF-0092: the post-crop framing of a live shot. Cover only - a
    # contained card is shown whole and its subject is its text, which
    # CF-0047's text_survival gate judges; this check is about faces on
    # footage the cover window cannot reframe vertically.
    framing = None if contain else crop_framing(vision, caption_crop)
    framing_lost = bool(framing and framing["lost_to_crop"])
    if framing_lost:
        failed.append("crop_framing")
        if framing["pinned"]:
            failures.append(
                f"framing: our own {caption_crop:.0%} caption crop runs through the "
                f"faces - {framing['foot_margin']:.0%} of the frame left under the "
                f"face box (< {MIN_CROP_FOOT_MARGIN:.0%}), {framing['foot_margin_before_crop']:.0%} "
                f"before the crop (CF-0092); the shot is framed fine, the crop is what "
                f"was rejected")
        else:
            failures.append(
                f"framing: our own {caption_crop:.0%} caption crop leaves the faces in "
                f"the lower third - centre at {framing['centre']:.0%} of the cropped frame "
                f"(> {MAX_CROP_SUBJECT_CENTRE:.0%}), {framing['centre_before_crop']:.0%} "
                f"before the crop - and the 9:16 cover window keeps the full height, so "
                f"it cannot reframe (CF-0092); the shot is framed fine, the crop is what "
                f"was rejected")

    return {
        "usable": not failures,
        "failures": failures,
        # The same verdict as `failures`, keyed rather than prose (CF-0047):
        # resolve_anchors.py's pre-filter has to ask *which* check failed, and
        # matching on the wording of an error message is not a way to ask.
        "failed": failed,
        "relaxations": relaxations,
        # CF-0104: which delivery geometry the floor was actually checked
        # against, and the pixel height that was measured for it - "высота
        # доставки" (delivery height): the cover window's height, or the
        # whole frame's height for a contained card.
        "fit": fit,
        "delivery_height": delivery_dimension,
        "contain_upscale_factor": contain_upscale,
        "short_side": short_side,
        # CF-0062: what the resolution number above was before the caption
        # crop, and whether that crop is the only reason it failed.
        "short_side_before_crop": before_crop,
        "resolution_lost_to_crop": lost_to_crop,
        # CF-0092: whether the caption crop pushed the faces to the bottom
        # of the frame, and the two numbers that say so (None when there was
        # no crop, no face, or no ROI to judge).
        "framing_lost_to_crop": framing_lost,
        "subject_foot_margin": framing["foot_margin"] if framing else None,
        "subject_centre": framing["centre"] if framing else None,
        "black_fraction": round(black, 3),
        "mean_luma": round(mean_luma, 1),
        "card_ink": None if card_ink is None else round(card_ink, 4),
        "roi_source": vision["roi_source"],
        "roi_coverage": vision["roi_coverage"],
        # CF-0296: whether that number was a gate at all. Under `contain` the
        # delivered window is the whole frame, so coverage has nothing to fall
        # short of and is reported, not judged (see the check above).
        "coverage_judged": not contain,
        # CF-0292: the individual faces `roi_coverage` was measured over when
        # there was more than one (None otherwise) - without them a report
        # cannot tell "the window keeps 40% of a face" from "it keeps 40% of a
        # union box", and those are different failures.
        "roi_parts": vision.get("roi_parts"),
        # CF-0155: which window `roi_coverage` was measured against (None -
        # the frame's own best crop, the answer before CF-0155 and still the
        # one every caller that asks for no window gets), and what the frame's
        # own crop would have kept. `coverage_window.focus`/`.zoom` is what
        # resolve_anchors.usable() carries from the frame the planner frames
        # this clip by to the rest of the frames it probes.
        "coverage_window": vision.get("coverage_window"),
        "roi_coverage_own": vision.get("roi_coverage_own", vision["roi_coverage"]),
        "min_short_side": min_short_side,
        "min_coverage": min_coverage,
        "max_black": max_black,
        "upscale_factor": round(1080 / short_side, 2) if short_side else None,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--aspect", default="1080:1920")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-black", type=float, default=MAX_BLACK_FRACTION,
                   help="near-black ceiling; dark cinematography legitimately exceeds the "
                        "still-image default, so clips are checked against a looser one")
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE,
                   help="subject-retention floor; relaxing it is recorded, not hidden")
    p.add_argument("--min-mean-luma", type=float, default=MIN_MEAN_LUMA,
                   help="floor on average brightness; a dim shot is unreadable "
                        "even when it is not black")
    p.add_argument("--min-short-side", type=int, default=MIN_SHORT_SIDE,
                   help="resolution floor; relaxing it is recorded, not hidden")
    p.add_argument("--caption-crop", type=float, default=None,
                   help="share of frame height prepare_clip.py already cropped off "
                        "the bottom of this clip for burned-in captions (CF-0062). "
                        "Changes no verdict; with --frame-before-crop, a resolution "
                        "failure caused by that crop is named as such instead of "
                        "reading as a low-res source.")
    p.add_argument("--frame-before-crop", default=None, metavar="WxH",
                   help="the frame --caption-crop was taken from, as prepare_clip.py "
                        "reports it (its own bars already off)")
    p.add_argument("--card", action="store_true",
                   help="this frame comes from a shot the index flagged as a title/"
                        "end card (CF-0047). Only changes anything for a frame the "
                        "darkness checks would otherwise reject, and only if its own "
                        "on-screen text is measurably lit - recorded, never silent.")
    p.add_argument("--window", default=None, metavar="self|X,Y",
                   help="CF-0155: judge the subject's coverage against the "
                        "window the render will actually show instead of "
                        "against this frame's own best crop. `self` is the "
                        "window this frame's own framing defines (what the "
                        "planner does with the frame it points the asset by); "
                        "`X,Y` is that framing carried from another frame of "
                        "the same clip - object-position fractions, with "
                        "--window-zoom.")
    p.add_argument("--window-zoom", type=float, default=1.0,
                   help="the zoom that goes with an explicit --window X,Y "
                        "(smart_crop's `zoom`, >= 1.0). Ignored for `self`.")
    p.add_argument("--fit", choices=["cover", "contain"], default=None,
                   help="delivery geometry this frame is actually shown through "
                        "(CF-0104): cover crops to fill 9:16, contain shows the whole "
                        "frame letterboxed. Defaults to common.delivery_fit(card) - a "
                        "card is always contain - so most callers never pass this.")
    p.add_argument("--max-contain-upscale", type=float, default=MAX_CONTAIN_UPSCALE,
                   help="contain-mode upscale ceiling (CF-0104/CF-0062): how far the "
                        "whole frame may be blown up to reach the delivery height "
                        "before it reads as soft. The measured max a real batch "
                        "actually accepted, not a guess.")
    p.add_argument("--with-framing", action="store_true",
                   help="CF-0649: also put this frame's smart_crop.analyse() "
                        "under `framing` in the --json verdict - the dict "
                        "`smart_crop.py <image> --aspect <aspect> --json` "
                        "prints, which the gate has already computed. "
                        "build_render_plan.inspect_asset() asks for it so a "
                        "block pays for one gate process, not two.")
    args = p.parse_args()
    from _runlog import video_attempt  # CF-0159: CLI-only, see the import above
    runlog.annotate(**video_attempt(args.image))  # CF-0107

    fit = args.fit or delivery_fit(args.card)
    _, target_height = (int(v) for v in args.aspect.split(":"))

    vision = analyse(args.image, args.aspect)
    if "error" in vision:
        print(f"REJECT {args.image}: {vision['error']}", file=sys.stderr)
        sys.exit(1)
    # Before --window rewrites the coverage numbers: `framing` is the frame's
    # own analyse(), exactly what smart_crop.py would print for it.
    framing = json.loads(json.dumps(vision)) if args.with_framing else None

    if args.window:
        focus = ("self" if args.window == "self"
                 else tuple(float(v) for v in args.window.split(",")))
        vision = against_window(vision, args.aspect, focus, args.window_zoom, fit)

    black, mean_luma = luma_stats(args.image)
    # Measured only where it could change the verdict, on the same discipline
    # as CF-0004's animation classifier: a frame already clearing the darkness
    # checks never pays for an accurate-mode Vision text scan, and this can
    # only ever recover a frame that was going to be rejected - never reject
    # one that was going to pass.
    ink, text = None, None
    if args.card and (black > args.max_black or mean_luma < args.min_mean_luma):
        text = card_text_ink(args.image)
        ink = text["ink"]
    before = None
    if args.frame_before_crop:
        before = min(int(v) for v in args.frame_before_crop.lower().split("x"))
    result = evaluate(vision, black, mean_luma, args.min_short_side,
                       args.min_coverage, args.max_black, args.min_mean_luma,
                       card_ink=ink, caption_crop=args.caption_crop,
                       short_side_before_crop=before, fit=fit,
                       target_height=target_height,
                       max_contain_upscale=args.max_contain_upscale)
    result["image"] = args.image
    if framing is not None:
        result["framing"] = framing
    if text is not None:
        # CF-0094: what the ink number was measured over. A dark card that
        # failed with `ink` None because its only text was a platform bug
        # has to say so in `failures` - that list is the reason the resolver
        # records for a rejected candidate, and "dead pixels" alone reads
        # like a letterbox, not like "a fade with only the Example max bug".
        result["card_text_boxes"] = text["text_boxes"] - text["watermark_boxes"]
        result["watermark_boxes"] = text["watermark_boxes"]
        if ink is None and text["watermark_boxes"] and not result["usable"]:
            result["failures"].append(
                f"card text: none - the only text on this frame is "
                f"{text['watermark_boxes']} watermark-shaped box(es) in a corner "
                f"(a platform's bug is not the card's own text, CF-0094)")

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        verdict = "OK    " if result["usable"] else "REJECT"
        print(f"{verdict} {Path(args.image).name:22s} "
              f"roi={result['roi_source']:9s} cov={result['roi_coverage']:.2f} "
              f"black={result['black_fraction']:.2f} luma={result['mean_luma']:.0f}"
              + (f" ink={result['card_ink']:.3f}" if result["card_ink"] is not None else ""))
        for f in result["failures"]:
            print(f"       - {f}")
        for r in result["relaxations"]:
            print(f"       ~ RELAXED {r}")

    sys.exit(0 if result["usable"] else 1)


@video_script("video-editor", "qc-asset", name="qc_asset.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

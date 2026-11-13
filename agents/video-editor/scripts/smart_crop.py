#!/usr/bin/env python3
"""Compute a content-aware crop rectangle for an image, using macOS Vision.

The v2 pipeline cropped every image at the geometric centre and let ffmpeg's
zoompan default to x=0,y=0 (the top-left corner), which is why faces came out
decapitated. This module answers the question that code never asked: where is
the subject?

Faces win when present. When there are none, Vision's attention-based saliency
stands in - that is what covers frames like the corn shot, which have no faces
but still have an obvious subject.

Usage:
    smart_crop.py <image> --aspect 9:16 [--json]

Emits the crop rect in pixel coords plus `roi_contained`, which the QC gate
reads to decide whether the crop severed the subject.
"""
import argparse
import json
import sys

from common import MIN_COVERAGE
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

# Imported lazily inside the functions that actually touch Vision, not at
# module level (CF-0029): index_footage.py imports this module's pure-Python
# pieces from footage-indexer's own venv, which has no pyobjc at all - a
# top-level `import Quartz` would make the whole module unimportable there,
# even for callers that never reach the Vision-calling functions.
#
# CLIP (torch/transformers) is imported lazily for the same reason, inside
# classify_animated() only - it is a much heavier import than Quartz and is
# only ever needed for the minority of frames that fail the Vision-based crop
# first (see CF-0004).


def load_cgimage(path):
    import Quartz
    url = Quartz.CFURLCreateFromFileSystemRepresentation(
        None, path.encode("utf-8"), len(path.encode("utf-8")), False
    )
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None or Quartz.CGImageSourceGetCount(src) == 0:
        raise SystemExit(f"cannot read image: {path}")
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def _perform(handler, request):
    import vision_compute  # CF-0711: CPU on an Intel Mac, never the iGPU
    vision_compute.pin(request)
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        raise SystemExit(f"Vision request failed: {err}")
    return request.results() or []


def _to_pixels(bbox, w, h):
    """Vision normalises to [0,1] with the origin bottom-left; images are
    addressed top-left, so y is flipped here rather than at every call site."""
    x = bbox.origin.x * w
    y = (1.0 - bbox.origin.y - bbox.size.height) * h
    return (x, y, bbox.size.width * w, bbox.size.height * h)


def find_roi(path):
    """CF-0107: the in-process Vision request (faces, then attention
    saliency) is one `vision` child event, probe `find_roi`. Silent inside
    vision_worker.py - the client's request child accounts for it there."""
    with runlog.child("vision", argv=["vision", "find_roi", str(path)],
                      params={"probe": "find_roi"}):
        return _find_roi(path)


def _find_roi(path):
    """Return (roi_rect_px, size, source, single_subject, parts).

    source is 'faces', 'saliency' or 'none'. single_subject is False when the
    ROI is a union of more than one detected face/salient region (CF-0033):
    crop_for_aspect() needs to know this, because centring tightly on the
    union of several spread-out people lands the crop on the gap between
    them, not on anyone's face.

    CF-0292: `parts` are the individual detections the union was built from,
    clamped to the frame, in Vision's own order. They used to be thrown away
    here, and that is the whole defect: from the union box alone nobody
    downstream can tell a tight two-shot from two people at opposite edges of
    a hangar, because both collapse to one wide rectangle that a 9:16 window
    covers most of. Every question about *people* - which face the window can
    hold, how much of any one of them survives it - needs the faces
    themselves, so they travel with the union from here on.
    """
    import Quartz
    import Vision
    image = load_cgimage(path)
    w = Quartz.CGImageGetWidth(image)
    h = Quartz.CGImageGetHeight(image)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, {})

    faces = _perform(handler, Vision.VNDetectFaceRectanglesRequest.alloc().init())
    rects = [_to_pixels(f.boundingBox(), w, h) for f in faces]
    source = "faces"

    if not rects:
        req = Vision.VNGenerateAttentionBasedSaliencyImageRequest.alloc().init()
        for obs in _perform(handler, req):
            for obj in (obs.salientObjects() or []):
                rects.append(_to_pixels(obj.boundingBox(), w, h))
        source = "saliency" if rects else "none"

    if not rects:
        return (w * 0.25, h * 0.25, w * 0.5, h * 0.5), (w, h), "none", True, []

    # Vision extrapolates the box of a face clipped by the frame edge, so it
    # can report coordinates outside the image. Clamp before taking the union,
    # otherwise the ROI is wider than the picture and containment never holds.
    # Each part is clamped the same way and for the same reason (CF-0292): a
    # face whose box runs off the edge would otherwise count area the frame
    # does not contain against the window that does contain it.
    parts = [_clamp_rect(r, w, h) for r in rects]
    parts = [p for p in parts if p[2] > 0 and p[3] > 0]
    x0 = max(0.0, min(r[0] for r in rects))
    y0 = max(0.0, min(r[1] for r in rects))
    x1 = min(float(w), max(r[0] + r[2] for r in rects))
    y1 = min(float(h), max(r[1] + r[3] for r in rects))
    return (x0, y0, x1 - x0, y1 - y0), (w, h), source, len(rects) <= 1, parts


def faces_in_rect(path, rect):
    """CF-0367: Vision's faces on `rect` (x, y, w, h in source pixels) of the
    image at `path`, as (x, y, w, h) rects in the crop's own pixels.

    The crop is taken with CGImageCreateWithImageInRect, so the pixels and the
    colour profile are the source's own - no re-encode, no resample. That is
    the point of it: it asks Vision the question "is there a face in *this
    window* of the source", and nothing else may change between that and
    find_roi()'s question about the whole frame. A re-save through PIL drops
    the PNG's gAMA chunk and alone flips a marginal detection (measured on
    american-dread-story block 6: 0.583 on the file, nothing on its PIL copy).
    """
    with runlog.child("vision", argv=["vision", "faces_in_rect", str(path)],
                      params={"probe": "faces_in_rect"}):
        import Quartz
        import Vision
        image = load_cgimage(path)
        crop = Quartz.CGImageCreateWithImageInRect(
            image, Quartz.CGRectMake(*[float(v) for v in rect]))
        if crop is None:
            raise SystemExit(f"cannot crop {rect} out of {path}")
        w = Quartz.CGImageGetWidth(crop)
        h = Quartz.CGImageGetHeight(crop)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(crop, {})
        faces = _perform(handler, Vision.VNDetectFaceRectanglesRequest.alloc().init())
        return [_to_pixels(f.boundingBox(), w, h) for f in faces]


def _clamp_rect(rect, w, h):
    """`rect` cut down to the frame - the same clamp the union gets."""
    x0 = max(0.0, rect[0])
    y0 = max(0.0, rect[1])
    x1 = min(float(w), rect[0] + rect[2])
    y1 = min(float(h), rect[1] + rect[3])
    return (x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))


# CF-0033: tightening only pays for itself once the ROI is already too wide
# for the "largest window" crop to fully contain - below that, the existing
# full-height window already contains the whole subject (roi_coverage 1.0)
# with real, legitimate content (hair, shoulders) around it, and shrinking
# further only crops a perfectly good frame tighter for no reason (confirmed
# by rendering still_08 from the same real batch: roi 303px against a 459px
# window - already fully contained - regressed from a normal headshot to a
# chin-clipped close-up when this used to trigger at a 0.6 ratio instead).
# At >=1.0 the window's width was never going to contain the full ROI anyway
# (that's exactly block 14's case, 468px of ROI against a 459px window), so
# trading unused height for a tighter frame costs nothing already achievable.
SINGLE_SUBJECT_TIGHTEN_RATIO = 1.0
# How much headroom to leave around a single subject once the crop tightens:
# the window's height is the subject's own height times this, not the whole
# source image's height. 1.35 was chosen by rendering the real regression
# frame (rapid-reckless-neon-drift block 14, an upside-down face in a
# 1920x816 letterboxed source) at a few candidate values and picking the one
# that reads as a normal close-up crop rather than either "still half empty"
# (bigger) or "uncomfortably tight" (smaller).
SINGLE_SUBJECT_PADDING = 1.35


def crop_for_aspect(roi, size, aspect_w, aspect_h, single_subject=True):
    """Largest window of the target aspect that stays inside the image and is
    centred on the ROI. Faces sit high in a frame, so the window is biased
    upward: centring vertically on a face crops the body and looks wrong.

    CF-0033: that "largest window" rule quietly assumed the source is never
    much wider than the target aspect. This pipeline's footage is 2.35:1
    (1920x816) cropped to 9:16, so the "largest window" always uses the
    source's *entire* height - for a single subject whose own bounding box
    doesn't need anywhere near that much height (a close-up face box is
    roughly square), the leftover height renders as a fixed slab of whatever
    is above/below the subject, often near-black background, looking like
    half the frame was left empty. `single_subject` (from find_roi's face/
    saliency count) gates the fix to the one case it actually helps: a union
    box spanning several people is deliberately left alone, because its
    centroid usually falls in the gap between them, and tightening around
    that centroid crops everyone worse, not better.

    CF-0292: that last sentence described the symptom of a defect and treated
    it as a boundary. Centring on the gap is not "leaving the frame alone" -
    it delivers a window with nobody in it (the 2026-09-18T2232Z delver block:
    two people at x=0.33 and x=0.70 of a 1920px frame, 607px of window laid
    over the hangar between them). So a union too wide for the window is no
    longer handed to this function at all: analyse() picks one face first
    (window_face()) and calls this with that face and single_subject=True.
    What this function does with a union it is still given is unchanged, and
    that is deliberate - a caller that has a real union (a tight group that
    fits) still gets the old framing.
    """
    w, h = size
    target = aspect_w / aspect_h

    cw, ch = (h * target, h) if (w / h) > target else (w, w / target)
    cw, ch = min(cw, w), min(ch, h)
    natural_ch = ch

    if single_subject and roi[2] >= cw * SINGLE_SUBJECT_TIGHTEN_RATIO:
        tight_ch = min(ch, roi[3] * SINGLE_SUBJECT_PADDING)
        if tight_ch < ch:
            ch = tight_ch
            cw = ch * target

    # CF-0033: the renderer (AssetLayer.jsx) never actually crops this
    # rectangle out of the file - it applies CSS object-fit:cover, which is
    # mathematically the same "largest window" cw/ch computed above, always
    # at natural_ch, positioned via `focus` (the ROI centre). This `crop`
    # rect is otherwise only a diagnostic used for roi_coverage/roi_contained
    # and the plan's notes. `zoom` is what actually carries the tightened
    # window into the render: a >=1 scale factor, applied as an *additional*
    # transform anchored on the same focus point object-position already
    # centres on, so cover's natural framing shrinks down to this window
    # instead of silently being ignored.
    zoom = round(natural_ch / ch, 4) if ch else 1.0

    roi_cx = roi[0] + roi[2] / 2
    roi_cy = roi[1] + roi[3] / 2

    x = roi_cx - cw / 2
    y = roi_cy - ch / 2 - ch * 0.06

    x = max(0.0, min(x, w - cw))
    y = max(0.0, min(y, h - ch))

    contained = (
        roi[0] >= x - 1 and roi[1] >= y - 1
        and roi[0] + roi[2] <= x + cw + 1
        and roi[1] + roi[3] <= y + ch + 1
    )
    return (round(x), round(y), round(cw), round(ch)), contained, zoom


# CF-0047: crop_for_aspect() above answers "where should the window be".
# These two answer "where does the renderer actually put it, and does the
# text survive it" - a different question, and one nothing in Python could
# answer before. CF-0033 already found that AssetLayer.jsx never cuts the
# `crop` rect out of the file at all; the same gap hid a second thing, that
# a title card's wordmark is severed by the 9:16 cover crop while
# roi_coverage reports a perfect 1.0. roi_coverage is not wrong - it
# measures Vision's saliency box, and that box does survive. It is simply
# not the question a card poses, because a card exists to be read.
def delivered_window(size, focus, zoom, aspect_w, aspect_h, fit="cover"):
    """The region of the source the renderer displays, as (x, y, w, h) in
    source pixels.

    Mirrors AssetLayer.jsx rather than re-deriving it: object-fit sets the
    window's size, CSS object-position places it (the focus point's `p%` of
    the image aligned with the same `p%` of the box), and `zoom` shrinks it
    further around that same point. `contain` letterboxes instead of
    cropping, so the whole source is on screen and the window is the entire
    image.
    """
    w, h = size
    if fit == "contain":
        return (0.0, 0.0, float(w), float(h))
    target = aspect_w / aspect_h
    cw, ch = (h * target, h) if (w / h) > target else (w, w / target)
    scale = max(zoom or 1.0, 1e-9)
    cw, ch = min(cw, w) / scale, min(ch, h) / scale
    return (focus[0] * (w - cw), focus[1] * (h - ch), cw, ch)


# CF-0155: the two answers a *gate* needs about that window, and the reason
# they live here rather than in the gate. build_render_plan.py points the
# renderer with `focus` (below), keeps one window for the whole asset, and
# never recomputes it; resolve_anchors.usable() used to judge every probe
# frame against that frame's *own* optimal window - a number no render ever
# uses. Judging a frame against the window the viewer will actually see needs
# the same two formulas the planner uses, and a second copy of either is
# exactly how CF-0033 happened, so they are one function each, here, next to
# delivered_window() they both build on.
FACE_HEADROOM = 0.06


def focus_point(info):
    """Where the renderer points this asset, as (x, y) fractions of the frame -
    CSS object-position, which AssetLayer.jsx applies and delivered_window()
    above mirrors.

    The ROI's centre, except for faces: centring the crop on the eyes crops the
    forehead and reads as a mistake, so the framing is nudged up by
    FACE_HEADROOM and the gap opens above the head rather than below the chin.

    Moved out of build_render_plan.framing() (CF-0155), which now calls this:
    the gate has to reproduce the planner's window to judge a frame against it,
    and reproducing it by hand is a second copy of the framing rules.
    """
    roi, size = info["roi"], info["source_size"]
    focus_y = (roi["y"] + roi["height"] / 2) / size["height"]
    if info["roi_source"] == "faces":
        focus_y = max(0.0, focus_y - FACE_HEADROOM)
    return (round((roi["x"] + roi["width"] / 2) / size["width"], 4),
            round(focus_y, 4))


def window_coverage(roi, size, focus, zoom, aspect_w, aspect_h, fit="cover"):
    """Share of `roi` that a *given* window keeps - the window the render will
    actually show, from delivered_window(), rather than the one this frame
    would have chosen for itself.

    `roi` is (x, y, w, h) in source pixels, as find_roi() returns it (or
    analyse()'s `roi` dict read in that order).

    A real rectangle intersection, unlike analyse()'s `roi_coverage`, which is
    the product of the two overlapping *dimensions* and ignores where the
    window sits. That shortcut is sound there and only there: crop_for_aspect()
    centres its rect on the ROI, so the two boxes always share a centre and the
    dimensions are the whole story. A window computed from a different frame
    shares nothing with this frame's ROI - it can miss it entirely - and the
    dimension product would report a comfortable number for a subject that is
    off screen.
    """
    wx, wy, ww, wh = delivered_window(size, focus, zoom, aspect_w, aspect_h, fit)
    rx, ry, rw, rh = roi
    if not rw or not rh:
        return 0.0
    overlap_x = max(0.0, min(rx + rw, wx + ww) - max(rx, wx))
    overlap_y = max(0.0, min(ry + rh, wy + wh) - max(ry, wy))
    return (overlap_x * overlap_y) / (rw * rh)


# CF-0292: what "coverage" means once there is more than one face.
#
# window_coverage() above is an honest intersection, but of the *union* box,
# and that box is the wrong subject for a wide two-shot: Tom Carver at x=0.33
# and his interviewer at x=0.70 of a 1920px frame make a 679px-wide union that
# is mostly the empty hangar between them, so the 607px 9:16 window laid over
# that emptiness scored 0.895 while containing no face at all (the real
# 2026-09-18T2232Z delver.mp4 block the viewer rejected: "only the hosts' legs
# left"). The gate was asking "how much of the box is in the window"; the
# viewer asks "can I see a person". For one face the two are the same
# question, which is why this went unnoticed for so long.
#
# So for several faces the measure is over the faces themselves, and it is the
# *best-served* face rather than their total area: a window that holds one
# person whole is a good shot of that person (1.0), not a half-failure because
# somebody else stayed outside it (0.5). A window in the gap holds nobody and
# scores near zero, which is exactly the verdict that was missing.
def faces_coverage(parts, size, focus, zoom, aspect_w, aspect_h, fit="cover"):
    """Largest share of any one of `parts` that the delivered window keeps.

    `parts` are (x, y, w, h) source-pixel rects, as _find_roi() returns them.
    None when there are none to measure - "no faces" is not "faces at 0%".
    """
    kept = [window_coverage(p, size, focus, zoom, aspect_w, aspect_h, fit)
            for p in parts if p[2] and p[3]]
    return max(kept) if kept else None


def subject_coverage(info, focus, zoom, aspect_w, aspect_h, fit="cover"):
    """Share of the subject a given window keeps, by the rule that fits what
    `info` actually found: the best-served face when Vision found several
    (see above), otherwise the ROI box itself, unchanged.

    One function because the planner (analyse(), below) and the gate
    (qc_asset.against_window()) have to answer this the same way about the
    same frame - CF-0033 and CF-0047 are both what happens when they don't.
    `info` is an analyse() result, or any dict with `source_size`, `roi`,
    `roi_source` and (optionally) `roi_parts`.
    """
    size = (info["source_size"]["width"], info["source_size"]["height"])
    parts = [(p["x"], p["y"], p["width"], p["height"])
             for p in (info.get("roi_parts") or [])]
    if info.get("roi_source") == "faces" and len(parts) > 1:
        kept = faces_coverage(parts, size, focus, zoom, aspect_w, aspect_h, fit)
        if kept is not None:  # None only if every part was degenerate
            return kept
    roi = info["roi"]
    return window_coverage((roi["x"], roi["y"], roi["width"], roi["height"]),
                           size, focus, zoom, aspect_w, aspect_h, fit)


def roi_dict(rect):
    """A (x, y, w, h) pixel rect as the dict shape analyse() reports."""
    return {"x": round(rect[0]), "y": round(rect[1]),
            "width": round(rect[2]), "height": round(rect[3])}


def own_coverage(roi, rect, size, source, parts, zoom, aspect_w, aspect_h):
    """Coverage of this frame against *its own* window - what analyse()
    reports, and what the planner carries into the plan for the one frame it
    takes a block's framing from.

    Several faces go through subject_coverage() against the window this
    frame's own focus point produces (CF-0292). Everything else keeps the
    product-of-overlapping-dimensions shortcut this has always used, which is
    sound exactly where it is applied: crop_for_aspect() centres its rect on
    the ROI, so the two boxes share a centre and the dimensions are the whole
    story (window_coverage()'s docstring has the full argument).
    """
    if source == "faces" and len(parts) > 1:
        info = {"source_size": {"width": size[0], "height": size[1]},
                "roi": roi_dict(roi), "roi_source": source,
                "roi_parts": [roi_dict(p) for p in parts]}
        return subject_coverage(info, focus_point(info), zoom, aspect_w, aspect_h)
    return ((min(roi[2], rect[2]) * min(roi[3], rect[3])) / (roi[2] * roi[3])
            if roi[2] and roi[3] else 0.0)


# How much smaller than the biggest face still counts as "the same size" when
# choosing which one the window goes to (CF-0292). Vision's boxes on two
# equally-close people differ by a few percent from head angle alone, so an
# exact-maximum rule would pick by noise; within this ratio the tie is broken
# by distance to the frame's centre instead, which is where a director puts
# the person the shot is about.
FACE_TIE_RATIO = 0.9


def window_face(parts, size, aspect_w, aspect_h):
    """The one face the target window should be built around, or None when it
    does not have to choose.

    None means the faces fit together inside the natural window - the union is
    a fine thing to centre on and framing is unchanged. Otherwise the window
    cannot hold everyone, and centring on the union centres on the gap
    (CF-0033 knew this and left it; CF-0292 is the frame that made it
    unacceptable), so the window goes to the largest face - the person nearest
    the camera, the one a wide shot is usually about - with near-ties decided
    by nearness to the frame's centre.
    """
    if len(parts) < 2:
        return None
    w, h = size
    target = aspect_w / aspect_h
    cw, ch = (h * target, h) if (w / h) > target else (w, w / target)
    cw, ch = min(cw, w), min(ch, h)

    x0 = min(p[0] for p in parts)
    y0 = min(p[1] for p in parts)
    x1 = max(p[0] + p[2] for p in parts)
    y1 = max(p[1] + p[3] for p in parts)
    if (x1 - x0) <= cw and (y1 - y0) <= ch:
        return None

    biggest = max(p[2] * p[3] for p in parts)
    tied = [p for p in parts if p[2] * p[3] >= biggest * FACE_TIE_RATIO]
    return min(tied, key=lambda p: abs((p[0] + p[2] / 2) - w / 2))


def text_kept(regions, window, size):
    """Share of the recognised text's area that survives `window`.

    `regions` are Vision's fractional boxes (detect_text_band.text_regions).
    None when there is no text at all, which is a different answer from 0.0
    and the caller has to treat it as one: a frame with no text is not a
    frame whose text was cropped away.

    Pure math, like crop_for_aspect() - no Vision, no I/O - so the real
    numbers it produced on this repo's own card frames are testable.
    """
    w, h = size
    x, y, cw, ch = window
    total = kept = 0.0
    for r in regions:
        bx0, bx1 = r["left"] * w, (r["left"] + r["width"]) * w
        by0, by1 = r["top"] * h, r["bottom"] * h
        total += (bx1 - bx0) * (by1 - by0)
        ix = max(0.0, min(bx1, x + cw) - max(bx0, x))
        iy = max(0.0, min(by1, y + ch) - max(by0, y))
        kept += ix * iy
    return kept / total if total else None


def text_survival(path, size, focus, zoom, aspect_w, aspect_h, fit):
    """text_kept() for one real frame, fetching its text boxes from the warm
    Vision worker. The I/O half of the pair above, kept apart from it so the
    arithmetic stays unit-testable."""
    import vision_client
    regions = vision_client.text_regions(str(path), level=0)
    window = delivered_window(size, focus, zoom, aspect_w, aspect_h, fit)
    return text_kept(regions, window, size), len(regions)


# CF-0004: on animated footage, Vision's attention saliency does not come
# back empty - it fires, but on frames with painterly/flat lighting it can't
# separate figure from ground the way it does on photographic depth-of-field
# and exposure cues, so it returns a box spanning most of the frame's width.
# Measured on a real frame from Coyote vs. Acme (kMsiD1Nky5I.mp4, the
# animated half of the footage pool the 2026-08-30T2329Z batch had to skip):
# a centred, well-composed shot of Wile E. Coyote at a drafting table got
# roi=(379,128,1492,627) in a 1920x804 frame - 78% of the frame's width - so
# the 9:16 crop only ever keeps roi_coverage=0.30 against MIN_COVERAGE=0.65,
# even though the character is dead centre and the crop is fine. This is not
# a coverage problem to fix by loosening the threshold (that would also let
# through the live-action group/background boxes MIN_COVERAGE exists to
# catch) - it's Vision's box being the wrong *shape* for this genre, so the
# fix re-centres on the same box's centroid instead of trusting its size.
_CLIP_MODEL = None
_CLIP_PROC = None
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
ANIMATION_PROMPTS = [
    "a photo from a live-action film with real people",
    "an animated cartoon scene with a drawn or CGI character",
]
# Softmax prob of the "animated" prompt above this counts as animated.
#
# CF-0004 set this at 0.5 against 9 real frames (8/9 right) and argued that
# the one false positive was safe: this classifier only runs on a frame
# Vision's own crop has *already failed*, so misreading a frame as animated
# could only change which fallback crop a losing frame got.
#
# CF-0296 is that false positive costing a whole video. A verdict of
# "animated" does not just re-centre a losing frame - it replaces Vision's
# box with a synthetic one that fits the window, so `roi_coverage` jumps from
# under the floor to ~1.0 and the frame stops losing. At 0.5 that verdict was
# a coin flip on block 10 of lf-2026-09-19-008 (a live-action plaza wide
# shot): resolve_anchors.py's four probe frames scored 0.510-0.582 and the
# clip was accepted, build_render_plan.py's own probe of the same moment
# scored 0.497 and the plan was refused at 45% coverage. Two stages, one
# clip, 0.003 of softmax between shipping and losing 23 blocks.
#
# So the excuse now has to be argued rather than won on a coin toss. Where
# the line goes is measured, not chosen (seed 296, this repo's pool):
#
#   * 20 shots drawn at random from the 897 whose cached coverage is under
#     MIN_COVERAGE - the population that reaches this classifier at all -
#     score 0.002-0.402, and *none* of them reaches 0.5; today none of them
#     is excused and after this change none of them is either;
#   * the five disputed frames of the block-10 clip above: 0.497-0.582;
#   * kMsiD1Nky5I (Coyote vs. Acme, the animated source CF-0004 was written
#     on): of its 12 shots under the floor - the frames this fallback exists
#     for - the three that are excused today score 0.914, 0.919, 0.985, and
#     the other nine are already under 0.5 and stay unexcused.
#
# Between 0.582 and 0.914 the sample is empty; 0.75 is that gap's midpoint,
# leaving 0.17 above the highest live-action frame measured and 0.16 below
# the lowest animated frame that needs the excuse. It changes no verdict in
# either sample - what it removes is the band where the verdict was noise.
#
# Measured on frames delivered through `cover`, because those are the only
# ones this line decides anything for: under `contain` the whole frame is on
# screen, coverage is not judged at all (CF-0296, qc_asset.evaluate()) and
# nothing reaches this classifier's verdict. Which is just as well - the
# `is_card` clip of block 19 of the same scenario, a wordmark over an
# amphitheatre, scores 0.193 and 0.354 on its first two frames and 0.804 and
# 0.815 on its last two. On graphics this classifier reads high and unsteadily,
# and no raisable threshold would make it steady there.
ANIMATION_CONFIDENCE = 0.75
# How much of the natural target-aspect window the synthetic fallback ROI
# claims, centred on the original (oversized) ROI's centroid. <1.0 so the
# reported roi_coverage is a real, checkable number and not a trivially
# rigged 100%.
FALLBACK_ROI_FRACTION = 0.8


def classify_animated(path):
    """True if `path` looks like animation/CGI rather than live-action
    photography, via CLIP zero-shot (see ANIMATION_PROMPTS/_CONFIDENCE).

    Lazily loads openai/clip-vit-base-patch32 - already a local dependency of
    footage-indexer's match_anchors.py and cached under
    ~/.cache/huggingface, so this is no new download. The model/processor are
    cached at module level so a warm vision_worker.py process (CF-0029) pays
    the ~5s load once per run, not once per frame that reaches this path.
    """
    global _CLIP_MODEL, _CLIP_PROC
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    if _CLIP_MODEL is None:
        _CLIP_MODEL = CLIPModel.from_pretrained(CLIP_MODEL_NAME).eval()
        _CLIP_PROC = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)

    image = Image.open(path).convert("RGB")
    inputs = _CLIP_PROC(text=ANIMATION_PROMPTS, images=image,
                         return_tensors="pt", padding=True)
    with torch.no_grad():
        logits = _CLIP_MODEL(**inputs).logits_per_image
    animated_prob = logits.softmax(dim=1)[0, 1].item()
    return animated_prob >= ANIMATION_CONFIDENCE


def animation_fallback_roi(roi, size, source, aspect_w, aspect_h,
                            fraction=FALLBACK_ROI_FRACTION):
    """A synthetic ROI sized to fit the aspect crop instead of trusting
    Vision's (too-wide) box size, centred on that box's own centroid - still
    a good position estimate even when its size is not (see module docstring
    above). Falls back to the frame's geometric centre when Vision found
    nothing at all (source == "none").

    Pure math, like crop_for_aspect() - no Vision, no CLIP, unit-testable
    against fixed real numbers.
    """
    w, h = size
    target = aspect_w / aspect_h
    cw, ch = (h * target, h) if (w / h) > target else (w, w / target)
    cw, ch = min(cw, w), min(ch, h)

    if source != "none":
        cx, cy = roi[0] + roi[2] / 2, roi[1] + roi[3] / 2
    else:
        cx, cy = w / 2, h / 2

    fw, fh = cw * fraction, ch * fraction
    x = max(0.0, min(cx - fw / 2, w - fw))
    y = max(0.0, min(cy - fh / 2, h - fh))
    return (x, y, fw, fh)


def analyse(image, aspect="9:16"):
    """Full ROI + crop verdict for `image`, as a plain dict.

    Factored out of main() (CF-0029) so vision_worker.py can call it
    in-process - once Vision is warm, this call costs ~0.1-0.18s instead of
    the ~0.7s a fresh `smart_crop.py` subprocess used to pay every time.
    """
    aw, ah = (int(v) for v in aspect.split(":"))
    roi, size, source, single_subject, parts = find_roi(image)
    # CF-0292: when the window cannot hold everyone, it goes to one face
    # rather than to the middle of the union - window_face() has the rule and
    # the reason. From here on this frame *is* a single-subject frame: the ROI
    # is one face, so focus_point() points at it, crop_for_aspect() may tighten
    # around it exactly as it does for a lone face, and the plan's `focus`
    # carries that same point into the render. Coverage is still measured over
    # every face (own_coverage below), so the shot cannot claim the person it
    # left outside - if what stayed in frame is under the floor, the frame is
    # unusable for cover and resolve_anchors.py moves to the next candidate
    # (CF-0290), which is the whole point of keeping the measure honest.
    if source == "faces":
        chosen = window_face(parts, size, aw, ah)
        if chosen is not None:
            roi, single_subject = chosen, True
    rect, contained, zoom = crop_for_aspect(roi, size, aw, ah, single_subject)
    coverage = own_coverage(roi, rect, size, source, parts, zoom, aw, ah)

    # CF-0004: Vision's own result already fails the gate qc_asset.py is
    # about to apply (MIN_COVERAGE) - only then is it worth asking CLIP
    # whether this is animation. A passing live-action frame never reaches
    # this branch, so the gate is exactly as strict for live-action as
    # before; this can only recover a frame that was already going to be
    # rejected.
    if coverage < MIN_COVERAGE:
        try:
            animated = classify_animated(image)
        except Exception as e:
            print(f"animation classifier unavailable ({e}), "
                  f"keeping Vision's own result for {image}", file=sys.stderr)
            animated = False
        if animated:
            fb_roi = animation_fallback_roi(roi, size, source, aw, ah)
            fb_rect, fb_contained, fb_zoom = crop_for_aspect(
                fb_roi, size, aw, ah, single_subject=True)
            roi, rect, contained, zoom = fb_roi, fb_rect, fb_contained, fb_zoom
            source, single_subject, parts = "animation_center", True, []
            coverage = own_coverage(roi, rect, size, source, parts, zoom, aw, ah)

    return {
        "image": image,
        "source_size": {"width": size[0], "height": size[1]},
        "roi_source": source,
        "single_subject": single_subject,
        "roi": roi_dict(roi),
        # CF-0292: the individual faces behind that union box, so the gate can
        # ask about people rather than about a rectangle. Only for faces, and
        # only when there is more than one - a single face *is* the ROI, and a
        # saliency box has no parts worth naming.
        "roi_parts": [roi_dict(p) for p in parts] if (
            source == "faces" and len(parts) > 1) else None,
        "crop": {"x": rect[0], "y": rect[1], "width": rect[2], "height": rect[3]},
        "roi_contained": contained,
        "roi_coverage": round(coverage, 3),
        # CF-0033: >=1.0 static zoom the renderer must apply on top of cover's
        # natural framing for this crop to be anything but a diagnostic
        # number - see crop_for_aspect's docstring.
        "zoom": zoom,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--aspect", default="9:16")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.image))  # CF-0107

    result = analyse(args.image, args.aspect)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"{args.image}: roi={result['roi_source']} crop={result['crop']} "
              f"contained={result['roi_contained']}")


@video_script("video-editor", "smart-crop", name="smart_crop.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
"""CF-0004: wide/close animated shots pass Vision's own crop check with a
box far too large to satisfy MIN_COVERAGE - not because Vision finds
nothing (source stays "saliency"), but because it can't discriminate figure
from ground on painterly/flat-lit animated frames the way it does on
photographic depth-of-field and exposure cues.

Real numbers below are Vision's actual output (via smart_crop.find_roi(),
run against real extracted frames, not synthesised) for two shots from
Coyote vs. Acme's trailer footage (kMsiD1Nky5I.mp4, letterbox already
stripped to 1920x804 - the animated half of the footage pool the
2026-08-30T2329Z batch had to skip entirely, per CF-0004's task file):

  - "wide desk" (t=33s, Wile E. Coyote standing at a drafting table, wide
    enough to show the blueprint wall behind him): roi=(379,128,1492,627) -
    78% of the frame's width - roi_coverage 0.303 against MIN_COVERAGE 0.65.
  - "closeup" (t=30s, his face in extreme closeup): roi=(242,78,971,742) in
    the un-letterboxed 1920x1080 capture - roi_coverage 0.581, still under
    the 0.65 floor.

These are pure-math checks against animation_fallback_roi() + crop_for_aspect()
directly - no Vision, no CLIP, no images, no subprocess - same style as
test_smart_crop_single_subject.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smart_crop  # noqa: E402

WIDE_DESK_ROI = (379, 128, 1492, 627)
WIDE_DESK_SIZE = (1920, 804)

CLOSEUP_ROI = (242, 78, 971, 742)
CLOSEUP_SIZE = (1920, 1080)


def _coverage(roi, rect):
    return (min(roi[2], rect[2]) * min(roi[3], rect[3])) / (roi[2] * roi[3])


def test_vision_saliency_box_really_fails_coverage_on_these_frames():
    """Confirms the premise: Vision's own saliency result, unmodified, does
    not meet MIN_COVERAGE for either real frame - the fallback exists to
    treat a genuine failure, not a hypothetical one."""
    rect, _, _ = smart_crop.crop_for_aspect(
        WIDE_DESK_ROI, WIDE_DESK_SIZE, 9, 16, single_subject=True)
    assert _coverage(WIDE_DESK_ROI, rect) < smart_crop.MIN_COVERAGE

    rect, _, _ = smart_crop.crop_for_aspect(
        CLOSEUP_ROI, CLOSEUP_SIZE, 9, 16, single_subject=True)
    assert _coverage(CLOSEUP_ROI, rect) < smart_crop.MIN_COVERAGE


def test_fallback_roi_centres_on_the_original_boxs_centroid():
    """The synthetic ROI should sit at the same centroid Vision found - its
    size was the problem, not its position."""
    fb = smart_crop.animation_fallback_roi(
        WIDE_DESK_ROI, WIDE_DESK_SIZE, "saliency", 9, 16)
    fb_cx, fb_cy = fb[0] + fb[2] / 2, fb[1] + fb[3] / 2
    orig_cx = WIDE_DESK_ROI[0] + WIDE_DESK_ROI[2] / 2
    orig_cy = WIDE_DESK_ROI[1] + WIDE_DESK_ROI[3] / 2
    assert abs(fb_cx - orig_cx) < 1, (fb_cx, orig_cx)
    assert abs(fb_cy - orig_cy) < 1, (fb_cy, orig_cy)


def test_fallback_roi_fixes_coverage_on_both_real_frames():
    """The whole point: re-running crop_for_aspect on the fallback ROI must
    clear MIN_COVERAGE, on both real shots, not just one."""
    for roi, size in ((WIDE_DESK_ROI, WIDE_DESK_SIZE), (CLOSEUP_ROI, CLOSEUP_SIZE)):
        fb = smart_crop.animation_fallback_roi(roi, size, "saliency", 9, 16)
        rect, contained, _ = smart_crop.crop_for_aspect(
            fb, size, 9, 16, single_subject=True)
        coverage = _coverage(fb, rect)
        assert coverage >= smart_crop.MIN_COVERAGE, (
            f"fallback still fails coverage for size={size}: {coverage:.3f}")
        assert contained


def test_fallback_roi_uses_frame_centre_when_vision_found_nothing():
    """source == "none" carries no centroid to trust - the fallback must not
    read roi[0]/roi[1] as real coordinates in that case (find_roi's own
    "none" placeholder is arbitrary, not a position estimate)."""
    w, h = 1920, 804
    fb = smart_crop.animation_fallback_roi(
        (w * 0.25, h * 0.25, w * 0.5, h * 0.5), (w, h), "none", 9, 16)
    fb_cx, fb_cy = fb[0] + fb[2] / 2, fb[1] + fb[3] / 2
    assert abs(fb_cx - w / 2) < 1
    assert abs(fb_cy - h / 2) < 1


def test_fallback_roi_stays_inside_the_frame_near_an_edge():
    """A centroid close to the image edge must not push the synthetic ROI
    out of bounds - crop_for_aspect's own edge clamp would then disagree
    with where the ROI claims to be, and coverage could come out wrong
    instead of just imperfect."""
    w, h = 1920, 804
    near_edge_roi = (0, 0, 200, 200)  # centroid at (100, 100), hard against
                                       # the top-left corner
    fb = smart_crop.animation_fallback_roi(near_edge_roi, (w, h), "saliency", 9, 16)
    assert fb[0] >= 0 and fb[1] >= 0
    assert fb[0] + fb[2] <= w + 1e-6
    assert fb[1] + fb[3] <= h + 1e-6


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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

#!/usr/bin/env python3
"""CF-0033: a single subject's ROI that is already too wide to fit the
"largest window" crop used to keep the crop at the source's *entire* height
anyway - fine for normal 16:9 footage, but this pipeline's trailer footage is
2.35:1 (1920x816), so the leftover height rendered as a fixed slab of
whatever was above/below the subject, often near-black background. A real
frame from the 2026-08-31T2155Z batch (rapid-reckless-neon-drift, block
14: a single upside-down face, ROI 468x468 in a 1920x816 still) reproduced
this exactly - roi_coverage reported a passing 98%, but the rendered frame
was about half solid black.

These are pure-math checks against crop_for_aspect() directly - no Vision,
no images, no subprocess - using the real numbers from that frame (and from
block 8/9's real ROIs, which must NOT change) as fixtures. No pytest
dependency, plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smart_crop  # noqa: E402

# The real ROI/source size smart_crop.py reported for
# rapid-reckless-neon-drift's still_14.png (block 14) before this fix -
# a single face, upside-down, in a 1920x816 letterboxed still. See
# CF-0033's task file for the extracted-frame evidence.
BLOCK14_ROI = (707, 142, 468, 468)
BLOCK14_SIZE = (1920, 816)

# still_08.png from the same real batch: also a single face, also 2.35:1,
# but roi width (303) is well inside the 459px max window - the crop already
# fully contained the subject with real content (hair, shoulders) around it.
# This is the regression case: an earlier, looser gate (roi width >= 60% of
# the max window) tightened this one too, clipping the chin off what was
# already a normal-looking headshot.
BLOCK08_ROI = (701, 166, 303, 303)
BLOCK08_SIZE = (1920, 816)

# block 4 from the same batch: a *group* shot - Vision's face union spans
# several riders spread across the frame, so single_subject is False.
BLOCK04_ROI = (609, 56, 653, 369)
BLOCK04_SIZE = (1920, 816)


def test_single_subject_too_wide_for_max_window_gets_tightened():
    rect, contained, zoom = smart_crop.crop_for_aspect(
        BLOCK14_ROI, BLOCK14_SIZE, 9, 16, single_subject=True)
    x, y, cw, ch = rect

    assert zoom > 1.2, f"expected a real zoom-in for block 14's ROI, got {zoom}"
    assert ch < 816, f"crop should no longer default to the source's full height, got ch={ch}"
    assert cw < 459, f"crop width should shrink along with height (fixed aspect), got cw={cw}"
    # The subject should end up occupying most of the tightened window's
    # height - the whole point of the fix - not just a fraction of it.
    assert BLOCK14_ROI[3] / ch > 0.7, (
        f"subject still only fills {BLOCK14_ROI[3] / ch:.0%} of the tightened "
        f"window's height - the dead-space problem is not actually fixed")


def test_single_subject_already_contained_is_left_alone():
    """A face box that already fit inside the largest window (block 8, real
    batch) must render exactly as before: zoom 1.0, full-height crop. This is
    the regression this test guards - a looser trigger ratio (0.6x) used to
    tighten this one too and clipped the chin off an otherwise fine crop."""
    rect, contained, zoom = smart_crop.crop_for_aspect(
        BLOCK08_ROI, BLOCK08_SIZE, 9, 16, single_subject=True)
    x, y, cw, ch = rect

    assert zoom == 1.0, f"a well-contained single-subject ROI should not be zoomed, got {zoom}"
    assert (cw, ch) == (459, 816), f"expected the untouched max window, got {(cw, ch)}"
    assert contained, "block 8's ROI fit inside the max window before this fix and still must"


def test_group_shot_union_box_is_never_tightened():
    """A union of several faces (single_subject=False) must never trigger the
    tightening path, even when the union box is wider than the max window
    (block 4, real batch, 2 riders) - centring tightly on the gap between
    people makes the frame worse, not better, so this case is left exactly
    as the pre-CF-0033 code produced it."""
    rect, contained, zoom = smart_crop.crop_for_aspect(
        BLOCK04_ROI, BLOCK04_SIZE, 9, 16, single_subject=False)
    x, y, cw, ch = rect

    assert zoom == 1.0, f"a multi-face union box must never be tightened, got zoom={zoom}"
    assert (cw, ch) == (459, 816), f"expected the untouched max window, got {(cw, ch)}"


def test_small_single_face_in_wide_shot_is_untouched():
    """A small, legitimately distant face (roi far narrower than the max
    window) must not be treated as needing a tighter crop - an establishing
    shot showing the surroundings is correct here, not a bug."""
    roi = (1257, 307, 90, 90)  # real block 0 ROI, same batch
    rect, contained, zoom = smart_crop.crop_for_aspect(
        roi, (1920, 816), 9, 16, single_subject=True)
    _, _, cw, ch = rect

    assert zoom == 1.0
    assert (cw, ch) == (459, 816)
    assert contained


def test_zoom_defaults_to_untightened_math_when_flag_omitted():
    """crop_for_aspect's new single_subject parameter defaults True, and the
    tighten condition is still gated by roi width vs the max window - a
    caller that doesn't know about CF-0033 yet must get sane output, not a
    crash from a missing argument."""
    rect, contained, zoom = smart_crop.crop_for_aspect(BLOCK14_ROI, BLOCK14_SIZE, 9, 16)
    assert zoom > 1.0


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

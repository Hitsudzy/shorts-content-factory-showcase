#!/usr/bin/env python3
"""CF-0062: a shot our own caption crop pushed under the resolution floor is
named as such, and is distinguishable from a source that was low-res to
begin with.

The floor (`MIN_SHORT_SIDE`) is checked on the cut clip, after
prepare_clip.py has cropped the caption band, so a 1280x720 source fails it
on *any* non-zero band - and before this the failure line was identical to
the one a 608px source gets. Numbers below are the real pool's: the
geometry measure_crop_floor.py reproduces from prepare_clip.py's own filter.

Pure asserts against evaluate() and qc_command(); no Vision, no ffmpeg.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import qc_asset  # noqa: E402
import resolve_anchors  # noqa: E402

FLOOR = 720


def vision(width, height):
    return {"source_size": {"width": width, "height": height},
            "roi_source": "saliency", "roi_coverage": 1.0}


def verdict(width, height, caption_crop=None, before=None):
    # Bright, well-framed: the only check that can fail here is resolution.
    return qc_asset.evaluate(vision(width, height), 0.10, 120.0,
                             FLOOR, 0.65, 0.90, qc_asset.MIN_MEAN_LUMA,
                             caption_crop=caption_crop,
                             short_side_before_crop=before)


# --- evaluate(): the same verdict, a different name for it -----------------

def test_720p_source_under_the_floor_is_blamed_on_the_crop():
    """ZZ_urA56pJE shot 50: 1280x720, crop 0.3272 -> 484px left."""
    v = verdict(1280, 484, caption_crop=0.3272, before=720)
    assert not v["usable"]
    assert v["failed"] == ["resolution"], v["failed"]
    assert v["resolution_lost_to_crop"] is True
    assert v["short_side_before_crop"] == 720
    assert len(v["failures"]) == 1
    assert "caption crop" in v["failures"][0] and "(CF-0062)" in v["failures"][0]


def test_608px_source_is_low_res_whether_or_not_it_was_cropped():
    """The 30 shots of the pool's three 608x1080 sources: the crop is not
    what fails them, and the failure line must not claim it is."""
    cropped = verdict(608, 766, caption_crop=0.2911, before=608)
    plain = verdict(608, 1080)
    for v in (cropped, plain):
        assert not v["usable"] and v["failed"] == ["resolution"]
        assert v["resolution_lost_to_crop"] is False
        assert "caption crop" not in v["failures"][0]
    assert cropped["short_side_before_crop"] == 608
    assert plain["short_side_before_crop"] is None


def test_letterboxed_1080p_source_is_blamed_on_the_crop_too():
    """f_bKjZeJBBI shot 14: a 2.35:1 trailer is 1920x804 once its own bars
    are off, and crop 0.45 leaves 442. The source cleared the floor at 804,
    so this is the crop's doing - the '0.333 limit' of a full-height 1080
    frame is 0.104 for this one."""
    v = verdict(1920, 442, caption_crop=0.45, before=804)
    assert v["resolution_lost_to_crop"] is True
    assert v["short_side_before_crop"] == 804


def test_a_clip_that_clears_the_floor_after_the_crop_is_untouched():
    """x9wMFCMXCRE shot 58: 1920x1080 cropped 0.0819 -> 990. Passes, and the
    new fields say so without inventing a loss."""
    v = verdict(1920, 990, caption_crop=0.0819, before=1080)
    assert v["usable"] and v["failed"] == []
    assert v["resolution_lost_to_crop"] is False
    assert v["short_side_before_crop"] == 1080


def test_the_boundary_case_is_measured_not_reconstructed():
    """ZZ_urA56pJE shot 21: 720 * (1 - 0.3814) = 445.4, floored to even ->
    444. Undoing that gives ceil(444 / 0.6186) = 718, i.e. "the source was
    under the floor too" - false, and false on exactly the source this task
    is about. So the pre-crop size is what prepare_clip.py saw, and a crop
    reported without it names nothing rather than guessing."""
    measured = verdict(1280, 444, caption_crop=0.3814, before=720)
    assert measured["resolution_lost_to_crop"] is True
    unknown = verdict(1280, 444, caption_crop=0.3814)
    assert unknown["resolution_lost_to_crop"] is False
    assert unknown["short_side_before_crop"] is None
    assert unknown["failures"] == ["resolution: short side 444px < 720px"]


def test_default_path_is_what_it_was():
    """No caption_crop: the old failure line, verbatim, and the new fields
    are explicit nulls rather than absent."""
    v = verdict(200, 120)
    assert v["failures"] == ["resolution: short side 120px < 720px"]
    assert v["resolution_lost_to_crop"] is False
    assert v["short_side_before_crop"] is None


# --- resolve_anchors.usable() tells the gate about the crop ------------------

def test_gate_is_told_the_crop_and_the_frame_only_when_there_was_one():
    crop = {"crop_bottom": 0.3272, "frame_before_crop": "1280x720"}
    with_crop = resolve_anchors.qc_command("p.png", 720, 0.65, 0.9, card=True, crop=crop)
    assert with_crop[with_crop.index("--caption-crop") + 1] == "0.3272"
    assert with_crop[with_crop.index("--frame-before-crop") + 1] == "1280x720"
    assert "--card" in with_crop
    none = {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}
    without = resolve_anchors.qc_command("p.png", 720, 0.65, 0.9, crop=none)
    assert "--caption-crop" not in without and "--frame-before-crop" not in without
    assert "--card" not in without
    assert "--caption-crop" not in resolve_anchors.qc_command("p.png", 720, 0.65, 0.9)


# --- CF-0104: the floor is checked by delivery mode, not source short side -

def vision_crop(width, height, crop_height):
    """A `vision` dict carrying smart_crop.analyse()'s `crop` rect (CF-0104):
    what a real qc_asset.py call always has and the bare `vision()` helper
    above never does. `crop_height` is the cover window's height in source
    pixels - the number the floor is actually checked against now."""
    v = vision(width, height)
    v["crop"] = {"height": crop_height}
    return v


def cover_verdict(width, height, crop_height=None, caption_crop=None, before=None):
    v = vision_crop(width, height, crop_height) if crop_height is not None \
        else vision(width, height)
    return qc_asset.evaluate(v, 0.10, 120.0, FLOOR, 0.65, 0.90,
                             qc_asset.MIN_MEAN_LUMA, caption_crop=caption_crop,
                             short_side_before_crop=before, fit="cover")


def contain_verdict(height, caption_crop=None, before=None, width=1920):
    # width does not enter the contain check at all (CF-0104: the norm is
    # against the frame's height alone) - a fixed placeholder is enough.
    return qc_asset.evaluate(vision(width, height), 0.10, 120.0, FLOOR, 0.65, 0.90,
                             qc_asset.MIN_MEAN_LUMA, caption_crop=caption_crop,
                             short_side_before_crop=before, fit="contain")


def test_delivery_fit_is_the_one_switch():
    import common
    assert common.delivery_fit(True) == "contain"
    assert common.delivery_fit(False) == "cover"


def test_cover_608_wide_portrait_source_passes_on_the_real_window_height():
    """CF-0104's whole point: a 608px-*wide* portrait source whose 9:16 cover
    window keeps its full ~1080px height is not the same shot as one cut
    down to 608px of usable height. The old check read width alone off the
    probe frame's short side and rejected both; the new one reads the
    window smart_crop actually computed."""
    v = cover_verdict(608, 1080, crop_height=1080)
    assert v["usable"] and v["failed"] == []
    assert v["fit"] == "cover"
    assert v["delivery_height"] == 1080
    # The raw short side is still reported (diagnostic), just not the gate.
    assert v["short_side"] == 608


def test_cover_portrait_source_still_fails_if_its_own_window_is_tight():
    """The fix is about reading the real window, not about exempting every
    portrait source: one whose window was tightened toward a subject (smart_
    crop's `zoom`) down to under 720px of height still fails, same as any
    other shot the window leaves too small."""
    v = cover_verdict(608, 1080, crop_height=650)
    assert not v["usable"] and v["failed"] == ["resolution"]
    assert v["delivery_height"] == 650
    assert v["failures"] == ["resolution: short side 650px < 720px"]


def test_cover_without_a_crop_rect_falls_back_to_the_frame_short_side():
    """A caller that never ran smart_crop (a bare vision dict, same as every
    test above this section) gets the pre-CF-0104 answer: the frame's own
    short side. Every real caller in this pipeline supplies `crop` (qc_asset.
    py's own analyse() always does); this is the documented limit of the
    ones that do not - cached_verdict()'s pre-filter is exactly this case,
    which is why CF-0104 stopped trusting it for resolution at all (see
    resolve_anchors.cached_verdict)."""
    v = cover_verdict(608, 1080)  # no crop_height -> plain vision()
    assert not v["usable"] and v["delivery_height"] == 608


def test_cover_720p_landscape_still_fails_after_the_caption_crop():
    """ZZ_urA56pJE shot 21, restated with an explicit `crop` rect instead of
    relying on the short-side fallback: object-fit:cover keeps the source's
    full height once it is wider than 9:16, so for this landscape source the
    window height and the short side are the same 444px either way - the
    fix does not change this verdict, only how it is computed."""
    v = cover_verdict(1280, 444, crop_height=444, caption_crop=0.3814, before=720)
    assert not v["usable"]
    assert v["resolution_lost_to_crop"] is True
    assert v["delivery_height"] == 444


def test_cover_clooney_cnbc_40pct_crop_still_fails():
    """Acceptance criterion: Clooney/CNBC s2/s4/s8/s13, a 40% caption crop
    landing at 634px, still fails the floor - CF-0104 fixes the portrait
    case, it is not a general loosening, and this is the gate CF-0092 needs
    to still be caught by."""
    v = cover_verdict(1920, 634, crop_height=634, caption_crop=0.40, before=1057)
    assert not v["usable"] and v["failed"] == ["resolution"]
    assert v["delivery_height"] == 634


def test_contain_card_within_the_upscale_norm_passes():
    """47P9fKmWbEs shot 4: 1920x1080 cropped 0.2106 -> 852px tall, x2.25 to
    reach 1920 - inside the x3.31 norm."""
    v = contain_verdict(852, caption_crop=0.2106, before=1080)
    assert v["usable"] and v["failed"] == []
    assert v["fit"] == "contain"
    assert v["delivery_height"] == 852
    assert v["contain_upscale_factor"] == 2.25


def test_contain_card_over_the_upscale_norm_fails():
    """ZZ_urA56pJE shot 8: a 1280x396 card, x4.85 to reach 1920 - over the
    x3.31 norm CF-0062 measured as what a real batch actually accepted."""
    v = contain_verdict(396)
    assert not v["usable"] and v["failed"] == ["resolution"]
    assert v["contain_upscale_factor"] == 4.85
    assert v["resolution_lost_to_crop"] is False
    assert "contain" in v["failures"][0] and "x4.85" in v["failures"][0]
    assert "x3.31" in v["failures"][0]


def test_contain_card_pushed_over_the_norm_by_our_own_crop_is_named():
    """1RnyZgfN-JY shot 35: 872px tall before the caption crop (x2.2, inside
    the norm), 508px after a 0.4152 crop (x3.78, over it) - the crop is what
    was rejected, same story as CF-0062's cover-mode case, told for contain."""
    v = contain_verdict(508, caption_crop=0.4152, before=872)
    assert not v["usable"]
    assert v["contain_upscale_factor"] == 3.78
    assert v["resolution_lost_to_crop"] is True
    assert v["short_side_before_crop"] == 872
    assert "caption crop" in v["failures"][0] and "CF-0062" in v["failures"][0]


def test_contain_card_genuinely_over_the_norm_even_before_the_crop():
    """The crop is not blamed when the card would have failed anyway: 350px
    tall before the crop is already x5.49, over the x3.31 norm."""
    v = contain_verdict(300, caption_crop=0.5, before=350)
    assert not v["usable"]
    assert v["resolution_lost_to_crop"] is False
    assert "caption crop" not in v["failures"][0]


def test_contain_default_path_has_no_crop_to_blame():
    """No caption_crop at all (most cards never see one) - the plain over-
    norm failure line, and the new fields are explicit nulls."""
    v = contain_verdict(396)
    assert v["resolution_lost_to_crop"] is False
    assert v["short_side_before_crop"] is None


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

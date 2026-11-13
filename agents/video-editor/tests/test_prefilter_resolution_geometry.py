#!/usr/bin/env python3
"""CF-0078: the pre-filter predicts a guaranteed post-crop resolution-floor
failure from cached geometry alone, before paying for cut().

CF-0104 taught the real gate (qc_asset.py::evaluate()) to judge the
resolution floor against the geometry that is actually delivered - a cover
shot's tightened 9:16 window, or a contain (card) shot's own frame height -
instead of the source's raw short side. It deliberately left resolve_
anchors.py's pre-filter neutralised on the resolution axis (min_short_side=0
/ max_contain_upscale=inf in cached_verdict()) because usable_cached carried
only a squared `short_side` placeholder with the orientation thrown away,
not enough to tell a 608px-wide portrait source (which keeps ~1080px of
height in a cover window and passes) from a 608px-tall landscape one (which
does not).

CF-0078 gives the cache real `width`/`height` (usability_probe.py) and
un-neutralises the resolution axis wherever the geometry proves a
*guaranteed* fail - the case measure_crop_floor.py found on ZZ_urA56pJE: a
720p landscape source whose short side already sits exactly at the floor,
so our own caption-band crop (`crop_bottom_cached`, any nonzero amount)
necessarily drops it under 720 and cut() was being paid for a foregone
conclusion.

No pytest dependency - plain asserts, run directly, same shape as
test_stale_usability_cache.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cache_fingerprint  # noqa: E402
import common  # noqa: E402
import resolve_anchors  # noqa: E402

THRESHOLDS = (720, 0.65, resolve_anchors.MAX_BLACK_CLIPS)

# Vision numbers that clear every *other* check (subject/black/luma/coverage)
# comfortably, so every assertion below turns on the resolution axis alone.
CLEAN_OTHER_CHECKS = {
    "roi_source": "face", "roi_coverage": 0.90,
    "black_fraction": 0.0, "mean_luma": 120.0,
}


def shot(cached=None, **extra):
    s = {"index": 3, "start": 10.0, "end": 12.0, **extra}
    if cached is not None:
        s["usable_cached"] = cached
    return s


def cached(width, height, crop_bottom=None, **extra):
    c = {
        "measured_by": cache_fingerprint.usability_fingerprint(),
        "short_side": min(width, height),
        "width": width, "height": height,
        **CLEAN_OTHER_CHECKS, **extra,
    }
    return c


# --- common.predict_resolution_floor_fail(): pure geometry, no cache/index ---

def test_720p_landscape_with_any_crop_is_guaranteed_to_fail_cover():
    """The cited case: ZZ_urA56pJE-shaped source, short side already at the
    floor - any nonzero caption crop takes it under and the natural
    (untightened) cover window can only get smaller from there, never
    recover, so this is decidable without Vision on the real cut clip."""
    assert common.predict_resolution_floor_fail(1280, 720, 0.0, "cover") is False
    assert common.predict_resolution_floor_fail(1280, 720, 0.05, "cover") is True
    assert common.predict_resolution_floor_fail(1280, 720, 0.30, "cover") is True


def test_near_9_16_portrait_source_is_not_guaranteed_to_fail_cover():
    """CF-0104's own motivating case: a 608px-wide portrait source whose
    aspect ratio is just past 9:16, so cover keeps its whole ~1080px height.
    The pre-filter must not condemn this from geometry alone - it is exactly
    the shot CF-0104 stopped losing."""
    assert common.predict_resolution_floor_fail(608, 1080, 0.0, "cover") is False
    assert common.predict_resolution_floor_fail(608, 1080, 0.10, "cover") is False


def test_narrow_portrait_source_can_still_be_proven_doomed():
    """A source narrow enough that even the untightened window falls under
    the floor - proof does not require the source to be landscape, only that
    width/delivery-aspect (the window's own floor for a genuinely narrow
    source) sits under min_short_side."""
    assert common.predict_resolution_floor_fail(300, 1080, 0.0, "cover") is True


def test_contain_card_prediction_is_exact_not_just_a_bound():
    """A card has no crop window (build_render_plan.py forces zoom=1,
    contain), so the post-crop frame height is exactly what evaluate()
    measures - the prediction can call both a pass and a fail."""
    assert common.predict_resolution_floor_fail(1920, 852, 0.0, "contain") is False
    assert common.predict_resolution_floor_fail(1920, 500, 0.0, "contain") is True
    # A crop that pushes a previously-fine card over the upscale norm:
    assert common.predict_resolution_floor_fail(1920, 852, 0.45, "contain") is True


def test_zero_or_missing_crop_bottom_is_the_uncropped_geometry():
    assert (common.predict_resolution_floor_fail(1280, 720, None, "cover")
            == common.predict_resolution_floor_fail(1280, 720, 0.0, "cover"))


# --- wired into cached_verdict()/probably_unusable() -------------------------

def test_720p_source_with_band_is_skipped_before_cut_when_cache_has_geometry():
    """The actual regression this task closes: a candidate that predict_
    resolution_floor_fail() alone would prove doomed must be skipped by
    probably_unusable() - i.e. never reach cut() - once the cache carries
    real width/height."""
    c = cached(1280, 720, crop_bottom=None)
    s = shot(c, crop_bottom_cached=0.06)
    # CF-0435: the bundle still proves it under the floor (cached_verdict),
    # but a low resolution is a price now, not a refusal - the candidate is
    # ranked behind the clean ones and reaches cut() when it is the best.
    assert resolve_anchors.cached_verdict(s, c, *THRESHOLDS) is True
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_same_shot_without_band_is_not_skipped():
    c = cached(1280, 720)
    s = shot(c, crop_bottom_cached=0.0)
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_portrait_source_with_band_is_not_skipped_by_the_prefilter():
    """The false-positive CF-0104 guarded against, now checked at the
    resolve_anchors.py boundary too: a portrait source near 9:16 with a
    modest caption crop is not guaranteed to fail and must still reach the
    real gate on its own cut clip - the pre-filter never decides who is
    chosen, only who is spared."""
    c = cached(608, 1080)
    s = shot(c, crop_bottom_cached=0.10)
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_old_cache_without_width_height_falls_back_to_unneutralised_behaviour():
    """CF-0048's own rule extended to the new fields: an index measured
    before CF-0078 has no width/height to predict from at all, and 'unknown'
    is not 'doomed' - the candidate must still cost a cut(), exactly as it
    did the day before this task landed."""
    old = {
        "measured_by": cache_fingerprint.usability_fingerprint(),
        "short_side": 720, **CLEAN_OTHER_CHECKS,
    }
    s = shot(old, crop_bottom_cached=0.30)
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_card_with_band_that_breaks_the_upscale_norm_is_skipped():
    """A card whose *subtitle* band (thin, at or under CARD_OWN_BAND, so
    prepare_clip.py will cut it) leaves too little height for the contain
    upscale is doomed: 720 * 0.70 = 504px, x3.81 to 1920."""
    c = cached(1280, 720, crop_bottom=None)
    s = shot(c, is_card=True, crop_bottom_cached=0.30)
    # CF-0435: the bundle's opinion, no longer the pre-filter's.
    assert resolve_anchors.cached_verdict(s, c, *THRESHOLDS) is True
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_card_whose_thick_band_is_kept_is_not_skipped():
    """CF-0103: a card's band above CARD_OWN_BAND is its own lettering and
    is not cut, so the prediction is made from the full 1920x852 frame
    (x2.25, fine) - not from the 468px the cached band would have left.
    Before CF-0103 this exact shot was the 'skipped' case above."""
    c = cached(1920, 852, crop_bottom=None)
    s = shot(c, is_card=True, crop_bottom_cached=0.45)
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_resolution_doom_short_circuits_ahead_of_the_card_ink_fallback():
    """A card whose darkness cannot be judged from an older cache (no
    card_ink_fraction) normally falls through to the real gate rather than
    being skipped (CF-0047/CF-0048's ink-unknown rule) - but a shot that is
    *also* geometrically doomed must still be skipped: resolution is a fact
    about pixels, not about ink, and does not need the ink question
    answered first."""
    c = cached(1920, 500, crop_bottom=None,
               black_fraction=0.99, mean_luma=4.9)
    assert "card_ink_fraction" not in c
    s = shot(c, is_card=True, crop_bottom_cached=0.0)
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is True


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

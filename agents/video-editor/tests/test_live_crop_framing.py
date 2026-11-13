#!/usr/bin/env python3
"""CF-0092: a live (non-card) shot's caption crop must not take the people
with it - and when it does, the gate has to see it.

Run 2026-09-03T2037Z cut every CNBC shot of W4mvmBXg9Nc with the cached
37-45% "caption" band - the desk's static lettering and name plates - and
rendered blue backdrop with the heads on the bottom edge; no gate caught it,
because roi_coverage only asks whether the cover window *contains* the
faces, and at full height it always does. Two independent fixes:

  direction 1 - qc_asset.crop_framing(): the post-crop framing of the faces,
      judged on the cut clip and blamed on the crop only when the same frame
      was fine before it. The safety net: it has to work on its own.
  direction 2 - prepare_clip.live_caption_crop(): a live shot's band above
      MAX_LIVE_CAPTION_CROP is scene text and is refused, not cut.

Every geometry below is a real pool measurement (smart_crop.analyse() on a
probe frame of the shot cut with its cached crop, 2026-09-06). Pure asserts,
no Vision, no ffmpeg.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import common  # noqa: E402
import prepare_clip  # noqa: E402
import qc_asset  # noqa: E402
import resolve_anchors  # noqa: E402


def faces(width, height, y, h, coverage=1.0):
    """A smart_crop.analyse()-shaped dict: Vision found faces, whose union
    box sits at `y` with height `h` in a `width`x`height` frame."""
    return {"source_size": {"width": width, "height": height},
            "roi_source": "faces", "roi_coverage": coverage,
            "roi": {"x": 600, "y": y, "width": 500, "height": h}}


def verdict(vision, caption_crop=None, fit="cover"):
    # Bright, lit, resolution floor off, coverage floor relaxed to 0.30:
    # the only check left that can fail here is CF-0092's own.
    return qc_asset.evaluate(vision, 0.10, 120.0, 0, 0.30, 0.90,
                             qc_asset.MIN_MEAN_LUMA, caption_crop=caption_crop,
                             short_side_before_crop=1080, fit=fit)


# --- direction 1: the gate sees the crop's damage on its own ---------------

def test_cnbc_backdrop_crop_is_caught_by_the_gate_alone():
    """W4mvmBXg9Nc s8 cut with the cached 41% band: 1920x634, faces at
    y=370 h=166 - centre 71% of the cropped frame against 42% before the
    crop. The gate is handed the crop exactly as the failed run applied it
    (as if direction 2 had never existed) and rejects on framing."""
    v = verdict(faces(1920, 634, 370, 166, coverage=0.34), caption_crop=0.41)
    assert v["usable"] is False
    assert "crop_framing" in v["failed"]
    assert v["framing_lost_to_crop"] is True
    assert 0.70 <= v["subject_centre"] <= 0.73
    assert any("CF-0092" in f and "lower third" in f for f in v["failures"])


def test_the_other_cnbc_shots_are_caught_too():
    # s4 (37% band): 1920x680, faces y=443 h=88;  s2 (38%): 1920x666, y=449 h=77.
    for height, y, h, crop in ((680, 443, 88, 0.37), (666, 449, 77, 0.38)):
        v = verdict(faces(1920, height, y, h), caption_crop=crop)
        assert "crop_framing" in v["failed"], (height, y, h, crop)


def test_a_chin_cut_by_the_crop_is_caught():
    """UaWVjS5SId4 s7 cut with its cached 45% band: the face box runs to
    the crop line (foot margin 0.000) where it had 44% of the frame under
    it before - pinned, not merely low."""
    v = verdict(faces(1920, 594, 217, 377), caption_crop=0.45)
    assert "crop_framing" in v["failed"]
    assert v["subject_foot_margin"] == 0.0
    assert any("runs through the faces" in f for f in v["failures"])


def test_direction_1_does_not_need_direction_2():
    """F_31ZfVsUlA s2: a 25% band - *under* the live ceiling, so direction 2
    applies it - still cuts a big close-up face at the chin (1920x614,
    faces y=209 h=405, foot margin 0.000). The gate catches what the ceiling
    let through."""
    applied, refused = prepare_clip.live_caption_crop(0.25)
    assert applied == 0.25 and refused is None
    v = verdict(faces(1920, 614, 209, 405, coverage=0.74), caption_crop=applied)
    assert "crop_framing" in v["failed"]


def test_the_same_frame_uncropped_is_not_blamed():
    """W4mvmBXg9Nc s8 at full height (1920x1080, faces y=369 h=165): the
    check only ever blames a crop, and there is none."""
    v = verdict(faces(1920, 1080, 369, 165, coverage=0.59))
    assert "crop_framing" not in v["failed"]
    assert v["framing_lost_to_crop"] is False
    assert v["subject_centre"] is None


def test_a_real_caption_band_leaves_the_faces_where_they_were():
    """Real subtitle crops on faces that had room: 1RnyZgfN-JY s27 (21%,
    692px, faces y=8 h=324) and BROAzK8oP9U s10 (14%, 822px, y=222 h=164)
    pass exactly as before."""
    for height, y, h, crop in ((692, 8, 324, 0.21), (822, 222, 164, 0.14)):
        v = verdict(faces(1920, height, y, h), caption_crop=crop)
        assert v["usable"] is True, (height, y, h, crop)
        assert v["framing_lost_to_crop"] is False


def test_a_face_the_source_framed_low_is_not_the_crops_doing():
    """FfYCVp8hLcg s15: an 8% band off a 1080px source leaves the face
    centre at 78% - but it sat at 72% in the source's own framing. The crop
    did not do this, so the crop is not blamed."""
    v = verdict(faces(1920, 990, 668, 208), caption_crop=0.08)
    assert v["framing_lost_to_crop"] is False
    assert v["usable"] is True


def test_only_faces_are_judged():
    """A saliency box legitimately runs to the bottom edge (bodies do), and
    the cache pre-filter's placeholder dict has no ROI at all: neither is
    a verdict, in either direction."""
    saliency = {"source_size": {"width": 1920, "height": 594}, "roi_source": "saliency",
                "roi_coverage": 0.22, "roi": {"x": 0, "y": 143, "width": 1920, "height": 451}}
    assert qc_asset.crop_framing(saliency, 0.45) is None
    placeholder = {"source_size": {"width": 720, "height": 720},
                   "roi_source": "faces", "roi_coverage": 1.0}
    assert qc_asset.crop_framing(placeholder, 0.45) is None
    assert verdict(placeholder, caption_crop=0.45)["framing_lost_to_crop"] is False


def test_a_contained_card_is_not_judged():
    """The CNBC geometry under a card's own delivery (contain): CF-0103's
    business, not this gate's - a card is shown whole and its subject is
    its text."""
    v = verdict(faces(1920, 634, 370, 166, coverage=0.34), caption_crop=0.41, fit="contain")
    assert "crop_framing" not in v["failed"]
    assert v["framing_lost_to_crop"] is False


def test_crop_framing_numbers_reconstruct_the_frame_before_the_crop():
    f = qc_asset.crop_framing(faces(1920, 634, 370, 166), 0.41)
    assert f["centre_before_crop"] == round((370 + 83) / (634 / 0.59), 3)
    assert f["sunk"] is True and f["pinned"] is False


# --- direction 2: a live shot is not cut for a band that thick -------------

def test_live_band_above_the_ceiling_is_refused_not_capped():
    for band in (0.34, 0.3744, 0.4115, 0.45):
        assert prepare_clip.live_caption_crop(band) == (0.0, band), band


def test_live_band_within_subtitle_reach_is_applied_unchanged():
    for band in (0.0, 0.08, 0.20, 0.31, prepare_clip.MAX_LIVE_CAPTION_CROP):
        assert prepare_clip.live_caption_crop(band) == (band, None), band


def test_a_cards_band_is_untouched():
    """is_card handling belongs to CF-0103; the ceiling never sees a card."""
    for band in (0.20, 0.45):
        assert prepare_clip.live_caption_crop(band, card=True) == (band, None), band


def test_an_unknown_band_stays_unknown():
    assert prepare_clip.live_caption_crop(None) == (None, None)


def test_cut_tells_prepare_clip_which_is_which():
    live = resolve_anchors.cut_command("s.mp4", 1.0, 2.0, "d.mp4", 0.4115, card=False)
    card = resolve_anchors.cut_command("s.mp4", 1.0, 2.0, "d.mp4", 0.4115, card=True)
    assert "--card" not in live and "--card" in card
    assert live[live.index("--crop-bottom") + 1] == "0.4115"
    assert card[card.index("--crop-bottom") + 1] == "0.4115"
    auto = resolve_anchors.cut_command("s.mp4", 1.0, 2.0, "d.mp4", None)
    assert "--auto-crop" in auto and "--crop-bottom" not in auto


def test_prefilter_predicts_from_the_crop_that_will_actually_be_applied():
    """CF-0078's geometry pre-filter, fed the raw cached band, would prove
    a 1080p CNBC shot doomed (1080 * 0.59 = 637 < 720) and skip it before
    the cut - a cut that is now going to happen at full height."""
    raw = 0.4115
    assert common.predict_resolution_floor_fail(1920, 1080, raw, "cover") is True
    effective, _ = prepare_clip.live_caption_crop(raw, card=False)
    assert common.predict_resolution_floor_fail(1920, 1080, effective, "cover") is False
    still_card, _ = prepare_clip.live_caption_crop(raw, card=True)
    assert still_card == raw


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

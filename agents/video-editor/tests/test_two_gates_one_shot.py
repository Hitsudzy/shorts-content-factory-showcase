#!/usr/bin/env python3
"""CF-0296: the resolver passed three shots the plan gate then refused, and
the whole Famine Trials video (23 blocks, 20 of them fine) was lost.

Batch `2026-09-19T0116Z`, scenario `lf-2026-09-19-008-script1`. Two
different defects wearing the same refusal line, both measured on the real
work files and pinned here as plain numbers - no Vision, no ffmpeg, no batch:

  * blocks 1 and 19 are `is_card` shots, delivered `contain` (the whole frame
    on screen, letterboxed). `resolve_anchors.usable()` asks qc_asset.py with
    `--window self`, so coverage is measured against the *delivered* window -
    the entire frame - and is 1.0. `build_render_plan.inspect_asset()` asks
    the same script with no window at all, so the number stays
    smart_crop.analyse()'s own, computed on a 9:16 **cover** window the card
    is never shown through: 0.344 and 0.264 against the 65% floor. The plan
    was refused over a rectangle the render does not use.

  * block 10 is live-action delivered `cover`, and its refusal was a coin
    toss. Its saliency box is 1342x795 of a 1920x1080 frame, the cover window
    keeps 45% of it, so the frame reaches CF-0004's animation classifier -
    and that classifier scored the resolver's four probe frames 0.510-0.582
    (excused, `animation_center`, coverage ~1.0) and the planner's own probe
    of the same moment 0.497 (not excused, 0.45, refused). The threshold was
    0.5.

The fixes: coverage is judged in the fit the block is delivered with, and
the animation excuse has to be argued (ANIMATION_CONFIDENCE, sampled). What
must NOT move is the face rule CF-0292 put in - the last test here is the
Delver frame, which has nothing to do with either fix and has to stay 1.0.

No pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smart_crop  # noqa: E402
import qc_asset  # noqa: E402
from common import MIN_COVERAGE, MIN_SHORT_SIDE, MAX_CONTAIN_UPSCALE  # noqa: E402

MAX_BLACK_CLIPS = 0.90  # resolve_anchors.py's ceiling for clips

# ---------------------------------------------------------------- the frames
# Block 1: the "WITNESS" wordmark over the amphitheatre, is_card, 1920x804
# after prepare_clip.py, Vision reports one saliency box.
B1 = {"size": (1920, 804), "roi": (456, 43, 1284, 574), "coverage": 0.344}
# Block 19: the full title/logo card, is_card, 1920x614 (a 23% caption crop
# already off the bottom).
B19 = {"size": (1920, 614), "roi": (255, 80, 1288, 494), "coverage": 0.264}
# Block 10: the plaza wide shot, live action, 1920x1080, no caption crop.
B10 = {"size": (1920, 1080), "roi": (91, 94, 1342, 795), "coverage": 0.450}


def _vision(frame, source="saliency"):
    """An analyse()-shaped dict, as vision_client hands one to the gate."""
    w, h = frame["size"]
    return {
        "source_size": {"width": w, "height": h},
        "roi_source": source,
        "roi": smart_crop.roi_dict(frame["roi"]),
        "roi_parts": None,
        "roi_coverage": frame["coverage"],
        "zoom": 1.0,
        "crop": {"x": 0, "y": 0, "width": round(h * 9 / 16), "height": h},
    }


def _evaluate(frame, fit, source="saliency", card_ink=0.2, **kw):
    """qc_asset.evaluate() on a lit, bright frame - so the only thing that can
    fail is the framing question this file is about."""
    return qc_asset.evaluate(
        _vision(frame, source), black=0.1, mean_luma=90,
        min_short_side=MIN_SHORT_SIDE, min_coverage=MIN_COVERAGE,
        max_black=MAX_BLACK_CLIPS, min_mean_luma=qc_asset.MIN_MEAN_LUMA,
        card_ink=card_ink if fit == "contain" else None, fit=fit,
        max_contain_upscale=10.0 if kw.pop("ignore_upscale", True)
        else MAX_CONTAIN_UPSCALE, **kw)


# ------------------------------------------------- the two cards (1 and 19)
def test_the_plan_gate_refused_both_cards_on_a_cover_window():
    """The defect, pinned: the numbers as the refusal recorded them."""
    for frame, kept in ((B1, "34%"), (B19, "26%")):
        verdict = _evaluate(frame, "cover")
        assert not verdict["usable"], frame
        assert "coverage" in verdict["failed"], verdict["failed"]
        assert any(kept in f for f in verdict["failures"]), verdict["failures"]


def test_a_contained_card_is_not_judged_by_a_window_it_is_not_shown_through():
    """The fix. `contain` puts the whole frame on screen - there is no share
    of the subject to fall short, and the number that used to be compared was
    measured on a rectangle this block never gets."""
    for frame in (B1, B19):
        verdict = _evaluate(frame, "contain")
        assert verdict["usable"], verdict["failures"]
        assert "coverage" not in verdict["failed"], verdict["failed"]
        # Reported, not judged - the number is still on the record.
        assert verdict["roi_coverage"] == frame["coverage"]
        assert verdict["coverage_judged"] is False


def test_the_resolver_was_already_answering_one_point_zero():
    """Why "not judged" and not "judged loosely": the window-aware path, which
    is what resolve_anchors.usable() asks for, has always measured these two
    frames against the delivered window - and for contain that rectangle *is*
    the image, so the answer is 1.0 by construction. The two gates now say the
    same thing about the same frame instead of differing by 0.66."""
    for frame in (B1, B19):
        vision = _vision(frame)
        focus = smart_crop.focus_point(vision)
        assert smart_crop.subject_coverage(
            vision, focus, 1.0, 9, 16, "contain") == 1.0
        window = smart_crop.delivered_window(
            frame["size"], focus, 1.0, 9, 16, "contain")
        assert window == (0.0, 0.0, float(frame["size"][0]), float(frame["size"][1]))


def test_a_card_keeps_every_other_gate():
    """Nothing here excuses a card from anything else. Vision finding nothing
    at all, and contain's own upscale norm, still refuse it."""
    blind = _evaluate(B1, "contain", source="none")
    assert not blind["usable"] and "subject" in blind["failed"], blind

    # 614px blown up to 1920 is x3.13 - inside the norm; the same card at
    # 400px is not, and contain has no crop window to save it.
    small = dict(B19, size=(1920, 400))
    verdict = _evaluate(small, "contain", ignore_upscale=False)
    assert not verdict["usable"] and "resolution" in verdict["failed"], verdict
    ok = _evaluate(B19, "contain", ignore_upscale=False)
    assert ok["usable"], ok["failures"]


def test_the_cards_own_gate_is_still_its_text():
    """What a card has to keep is its wordmark, and that is CF-0047's
    measure on the delivered framing (build_render_plan.py, MIN_CARD_TEXT_KEPT
    0.98). Contain keeps all of it; the cover crop these blocks were being
    judged by would have cut it - which is why the card is contained in the
    first place."""
    # A wordmark spanning the middle 80% of the frame, as Vision's fractional
    # boxes come back from detect_text_band.text_regions().
    regions = [{"left": 0.1, "width": 0.8, "top": 0.4, "bottom": 0.6}]
    size = B1["size"]
    contained = smart_crop.delivered_window(size, (0.5, 0.5), 1.0, 9, 16, "contain")
    assert smart_crop.text_kept(regions, contained, size) == 1.0
    cropped = smart_crop.delivered_window(size, (0.5, 0.5), 1.0, 9, 16, "cover")
    assert smart_crop.text_kept(regions, cropped, size) < 0.5


# ------------------------------------------------------- block 10 (cover)
def test_both_gates_refuse_block_ten_on_the_same_number():
    """The live-action plaza shot is legitimately under the floor, and after
    this change both stages say so: the resolver drops the candidate and the
    block goes down CF-0290's ladder instead of the plan being refused whole.
    0.45 is the measured number, from the frame's own window."""
    vision = _vision(B10)
    focus = smart_crop.focus_point(vision)
    kept = smart_crop.subject_coverage(vision, focus, 1.0, 9, 16, "cover")
    assert 0.44 <= kept <= 0.46, kept
    assert kept < MIN_COVERAGE
    verdict = _evaluate(B10, "cover")
    assert not verdict["usable"] and "coverage" in verdict["failed"], verdict
    assert verdict["coverage_judged"] is True


def test_the_animation_excuse_has_to_be_argued():
    """Where ANIMATION_CONFIDENCE sits, against the frames it was measured on
    (seed 296; the comment in smart_crop.py has the full sample).

    Under `cover` - the only delivery this line decides anything for - the
    highest live-action score measured is block 10's own 0.582, and the lowest
    score among the frames the fallback exists for (kMsiD1Nky5I's shots under
    the coverage floor, the ones excused today) is 0.914."""
    live_action_cover = [0.402,   # the top of 20 random pool shots under the floor
                         0.497, 0.510, 0.528, 0.554, 0.582]  # block 10's five frames
    animated_needing_the_excuse = [0.914, 0.919, 0.985]  # kMsiD1Nky5I 43, 45, 50
    assert max(live_action_cover) < smart_crop.ANIMATION_CONFIDENCE
    assert min(animated_needing_the_excuse) > smart_crop.ANIMATION_CONFIDENCE
    # 0.5 - the old line - ran straight through block 10's own frames, which
    # is the whole defect: the resolver's probes fell one side of it and the
    # planner's fell the other.
    assert min(live_action_cover[1:]) < 0.5 < max(live_action_cover)


def test_the_fallback_itself_is_untouched():
    """CF-0004's own frame (Coyote vs. Acme, kMsiD1Nky5I.mp4): a 1492px-wide
    saliency box in a 1920x804 frame, a well-composed centred character. When
    the classifier *is* confident, the synthetic ROI is the same one it always
    was and it still clears the floor."""
    roi, size = (379, 128, 1492, 627), (1920, 804)
    fb = smart_crop.animation_fallback_roi(roi, size, "saliency", 9, 16)
    rect, contained, zoom = smart_crop.crop_for_aspect(fb, size, 9, 16, True)
    kept = smart_crop.own_coverage(fb, rect, size, "animation_center", [], zoom, 9, 16)
    assert kept >= MIN_COVERAGE, kept
    assert abs((fb[0] + fb[2] / 2) - (roi[0] + roi[2] / 2)) < 1, fb


# ------------------------------------------------------------- CF-0292 guard
def test_the_delver_frame_still_lands_on_a_face():
    """Neither fix touches faces, and the fixture that made CF-0292 has to
    stay exactly where it was: two 67-69px faces at opposite edges of a
    1920x1080 frame, the window on Cruise, coverage 1.0 - and the old window
    (the gap between them) still refused at 0.515."""
    faces = [(631, 417, 67, 67), (1241, 392, 69, 69)]
    size = (1920, 1080)
    chosen = smart_crop.window_face(faces, size, 9, 16)
    assert chosen == faces[0], chosen
    info = {"source_size": {"width": size[0], "height": size[1]},
            "roi_source": "faces", "roi": smart_crop.roi_dict(chosen),
            "roi_parts": [smart_crop.roi_dict(f) for f in faces],
            "roi_coverage": 1.0, "zoom": 1.0}
    assert smart_crop.subject_coverage(
        info, smart_crop.focus_point(info), 1.0, 9, 16) == 1.0
    old_window_kept = smart_crop.subject_coverage(info, (0.5055, 0.3456), 1.0, 9, 16)
    assert abs(old_window_kept - 0.515) < 0.01, old_window_kept
    assert old_window_kept < MIN_COVERAGE


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

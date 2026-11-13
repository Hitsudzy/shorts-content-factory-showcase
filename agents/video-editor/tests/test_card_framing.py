#!/usr/bin/env python3
"""CF-0047, second layer: how a title/end card is framed.

`roi_coverage` is the wrong question for a card, and that is measurable
rather than arguable. On the real card frames of the 2026-08-31T2155Z batch
smart_crop.py reports roi_coverage 1.000 - Vision's saliency box does survive
the 9:16 crop - while the crop severs a quarter of the lettering the card was
chosen for. So the answer is not to relax the coverage floor (which those
frames were passing anyway) but to stop cropping the card: fit it whole and
check the text, not the saliency box.

Fixtures are the real accurate-mode Vision text boxes of those frames, the
real source size after the letterbox crop, and the real focus point
build_render_plan.py derives from smart_crop.py's ROI. Pure math against
delivered_window()/text_kept() - no Vision, no images, no subprocess.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smart_crop  # noqa: E402

W, H = 1080, 1920  # the delivered frame

# ZZ_urA56pJE shot 50, "gold ornate 'Wren Hollow' logo card on black
# background with the Example Max mark" - the shot the anchor literally
# describes. 1280x720 after the letterbox crop; five text boxes, the big one
# being the wordmark itself at 46% of the frame's width.
HP_SIZE = (1280, 720)
HP_FOCUS = (0.4898, 0.4417)
HP_TEXT = [
    {"left": 0.4359, "top": 0.2583, "width": 0.1234, "height": 0.0361, "bottom": 0.2944},
    {"left": 0.4515, "top": 0.2970, "width": 0.0969, "height": 0.0365, "bottom": 0.3335},
    {"left": 0.2755, "top": 0.3922, "width": 0.4600, "height": 0.2294, "bottom": 0.6217},
    {"left": 0.3964, "top": 0.6310, "width": 0.1318, "height": 0.0663, "bottom": 0.6972},
    {"left": 0.4366, "top": 0.6975, "width": 0.1913, "height": 0.0702, "bottom": 0.7677},
]

# ZZ_urA56pJE shot 3, "purple Example Max logo splash screen" - the other phrase
# of CF-0034, one wide text box holding the whole "Examplemax" wordmark.
Example_Network_SIZE = (1280, 720)
Example_Network_FOCUS = (0.4930, 0.4264)
Example_Network_TEXT = [
    {"left": 0.3155, "top": 0.3958, "width": 0.3941, "height": 0.1362, "bottom": 0.5320},
]

# ZZ_urA56pJE shot 33, the UK tabloid front-page card - the *less* accurate
# candidate the anchor fell back to before this fix. Its text is narrow
# enough to nearly survive the crop, which is why it must not be used as
# evidence that cropping cards is fine in general.
TABLOID_SIZE = (1280, 720)
TABLOID_FOCUS = (0.4859, 0.4750)
TABLOID_TEXT = [
    {"left": 0.4875, "top": 0.4139, "width": 0.0406, "height": 0.0250, "bottom": 0.4389},
    {"left": 0.4090, "top": 0.4035, "width": 0.1633, "height": 0.1097, "bottom": 0.5132},
    {"left": 0.3453, "top": 0.5472, "width": 0.3031, "height": 0.0583, "bottom": 0.6056},
    {"left": 0.3344, "top": 0.5944, "width": 0.3250, "height": 0.0667, "bottom": 0.6611},
    {"left": 0.3984, "top": 0.6472, "width": 0.1969, "height": 0.0556, "bottom": 0.7028},
]


def kept(text, size, focus, fit, zoom=1.0):
    window = smart_crop.delivered_window(size, focus, zoom, W, H, fit)
    return smart_crop.text_kept(text, window, size)


# --- the defect, in numbers -------------------------------------------------

def test_cover_severs_the_wordmark_the_card_was_chosen_for():
    """The measured damage: the 9:16 cover crop throws away a quarter of the
    Wren Hollow card's text ("Harry Pott") and a fifth of the Example Max
    splash's ("Examplemax" with its edges cut)."""
    assert round(kept(HP_TEXT, HP_SIZE, HP_FOCUS, "cover"), 3) == 0.757
    assert round(kept(Example_Network_TEXT, Example_Network_SIZE, Example_Network_FOCUS, "cover"), 3) == 0.803


def test_contain_keeps_every_card_whole():
    for text, size, focus in [(HP_TEXT, HP_SIZE, HP_FOCUS),
                              (Example_Network_TEXT, Example_Network_SIZE, Example_Network_FOCUS),
                              (TABLOID_TEXT, TABLOID_SIZE, TABLOID_FOCUS)]:
        assert kept(text, size, focus, "contain") == 1.0


def test_the_crop_that_severs_the_text_passes_roi_coverage_anyway():
    """Why this could not be found by loosening or tightening a threshold:
    smart_crop.py measures roi_coverage 1.000 on both of these frames. The
    saliency box survives; the lettering does not. Two different questions,
    and only one of them was ever being asked."""
    assert kept(HP_TEXT, HP_SIZE, HP_FOCUS, "cover") < 0.80
    # The ROI these frames report is the animation-centre fallback box, which
    # sits inside the cover window entirely - hence coverage 1.0.
    roi = smart_crop.animation_fallback_roi((0, 0, 1280, 720), HP_SIZE,
                                            "saliency", W, H)
    rect, _, _ = smart_crop.crop_for_aspect(roi, HP_SIZE, W, H)
    coverage = ((min(roi[2], rect[2]) * min(roi[3], rect[3])) / (roi[2] * roi[3]))
    assert round(coverage, 3) == 1.0


def test_the_fallback_candidate_would_not_have_shown_the_defect():
    """Shot 33 - what the anchor settled for - keeps 99% of its text even
    under the crop. Had the fix been judged on it, there would have been
    nothing to see; the defect is specific to wide wordmarks."""
    assert round(kept(TABLOID_TEXT, TABLOID_SIZE, TABLOID_FOCUS, "cover"), 3) == 0.990


# --- the window arithmetic itself -------------------------------------------

def test_contain_window_is_the_whole_source():
    assert smart_crop.delivered_window(HP_SIZE, HP_FOCUS, 1.0, W, H, "contain") \
        == (0.0, 0.0, 1280.0, 720.0)


def test_cover_window_is_the_largest_9_16_window_placed_by_focus():
    """1280x720 is far wider than 9:16, so cover takes the full height and
    405px of width - which is less than the 589px the wordmark alone needs."""
    x, y, cw, ch = smart_crop.delivered_window(HP_SIZE, HP_FOCUS, 1.0, W, H, "cover")
    assert round(cw) == 405 and round(ch) == 720
    assert round(x) == 429 and y == 0.0
    wordmark_px = HP_TEXT[2]["width"] * HP_SIZE[0]
    assert wordmark_px > cw


def test_zoom_shrinks_the_cover_window_and_crops_further():
    """CF-0033's zoom tightens the window, so it can only ever cost a card
    more of its text - which is why a card's zoom is reset to 1.0."""
    tight = kept(HP_TEXT, HP_SIZE, HP_FOCUS, "cover", zoom=1.3)
    assert tight < kept(HP_TEXT, HP_SIZE, HP_FOCUS, "cover")


def test_zoom_is_ignored_under_contain():
    """A contained card must not be scaled at all - AssetLayer.jsx suppresses
    the Ken Burns/punch/zoom for exactly this reason, and the window maths
    here has to agree with it."""
    assert smart_crop.delivered_window(HP_SIZE, HP_FOCUS, 1.3, W, H, "contain") \
        == smart_crop.delivered_window(HP_SIZE, HP_FOCUS, 1.0, W, H, "contain")


def test_no_text_is_not_the_same_answer_as_no_text_kept():
    """A frame with no recognised text returns None, not 0.0: "nothing to
    crop" and "everything cropped away" are opposite verdicts and the plan
    branches on the difference."""
    window = smart_crop.delivered_window(HP_SIZE, HP_FOCUS, 1.0, W, H, "cover")
    assert smart_crop.text_kept([], window, HP_SIZE) is None


def test_text_wholly_outside_the_window_reads_as_zero():
    """The guard has to be able to fail, or it is not a guard."""
    far = [{"left": 0.0, "top": 0.0, "width": 0.05, "height": 0.05, "bottom": 0.05}]
    window = smart_crop.delivered_window(HP_SIZE, HP_FOCUS, 1.0, W, H, "cover")
    assert smart_crop.text_kept(far, window, HP_SIZE) == 0.0


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            passed += 1
    print(f"\n{passed}/{passed} passed  # card-framing checks")

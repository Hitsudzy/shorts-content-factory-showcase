#!/usr/bin/env python3
"""CF-0093: card_frame.classify_frame() on synthetic frames.

The bug: probe_card_text() counted any frame with enough text as card
evidence, so captioned photos, talking heads and subtitled game stills
(UaWVjS5SId4 s28, ScKvReYRZ-A s0, _m4e4oWFmac s1/13/16/26) came out
`is_card`. card_frame.py replaces "enough text" with two measurements -
headline-sized text, or text on a flat single-colour ground - and reads a
frame as "card", "caption" or None.

Everything here is PIL/numpy on synthetic frames: no Vision, no ffmpeg, no
shared/footage. The text boxes are handed in as the dicts Vision would
return ({top, bottom, left, width, height}, fractions of the frame), with
the geometry of real shots from the module docstring - Le Monde subtitles
at 0.052 tall, a God of War caption at 0.04, a tabloid card's headline at
0.106, an Example Network card's small gold serif on black. The real-footage check is
test_card_probe_real_footage.py.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import card_frame  # noqa: E402
from card_frame import (  # noqa: E402
    CARD_TEXT_AREA_THRESHOLD, FLAT_DOMINANT_SHARE, HEADLINE_MIN_HEIGHT,
    classify_frame, dominant_colour_share, has_headline, text_area)

W, H = 640, 360  # 16:9, small enough that every test is instant


def region(top, left, width, height):
    """One Vision text box in the shape detect_text_band.text_regions()
    returns."""
    return {"top": top, "bottom": top + height, "left": left,
            "width": width, "height": height}


def flat(colour=(8, 8, 8), size=(W, H)):
    """A solid card ground - near-black by default, like a studio card."""
    return Image.new("RGB", size, colour)


def noisy(seed=0, size=(W, H)):
    """A 'photo': every pixel a different colour, so no bin dominates.
    Real pictures with captions measured 0.15-0.45 dominant share; this is
    the far end of that, which is fine - the tests that need a picture
    *near* the threshold build one on purpose."""
    rng = np.random.RandomState(seed)
    px = rng.randint(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(px, "RGB")


def gradient(size=(W, H)):
    """A splash-screen gradient (Example Max's purple measured 0.23-0.25
    dominant share): smooth, but spread over many colour bins."""
    w, h = size
    x = np.linspace(0, 255, w, dtype=np.float32)
    y = np.linspace(0, 255, h, dtype=np.float32)[:, None]
    px = np.stack([np.broadcast_to(x, (h, w)) * 0.6 + 40,
                   np.broadcast_to(y, (h, w)) * 0.3 + 10,
                   np.broadcast_to(x, (h, w)) * 0.8 + 60], axis=-1)
    return Image.fromarray(np.clip(px, 0, 255).astype(np.uint8), "RGB")


def paint(image, box, colour=(240, 240, 240)):
    """Fill a text box with a glyph colour so the box's pixels really are
    different from the ground (a card's white title on black)."""
    w, h = image.size
    px = np.array(image)
    px[int(box["top"] * h):int(box["bottom"] * h),
       int(box["left"] * w):int((box["left"] + box["width"]) * w)] = colour
    return Image.fromarray(px, "RGB")


# --- the geometries the docstring calibrated on ---------------------------

# A card's headline: 'BASED ON A TRUE STORY' measured 0.119-0.129 tall.
HEADLINE = region(top=0.42, left=0.15, width=0.70, height=0.125)
# A subtitle line: Le Monde's French captions measured 0.052-0.055 tall.
SUBTITLE = region(top=0.86, left=0.20, width=0.60, height=0.052)
# A game-still caption: God of War stills measured 0.035-0.048 tall.
GAME_CAPTION = region(top=0.88, left=0.25, width=0.50, height=0.04)
# A corner watermark: 0.004-0.009 fractional area in real scans (CF-0010).
WATERMARK = region(top=0.02, left=0.85, width=0.12, height=0.05)


def test_flat_card_with_headline_is_card():
    """The plainest card there is: a title on near-black. Both signals
    fire; the frame is a card."""
    im = paint(flat(), HEADLINE)
    out = classify_frame(im, [HEADLINE])
    assert out["verdict"] == "card", out
    assert out["headline"] is True, out
    assert out["dominant_share"] >= FLAT_DOMINANT_SHARE, out


def test_flat_card_with_small_text_is_card_via_flat_ground():
    """'A NEW Example Network ORIGINAL SERIES' is only 0.057-0.074 tall but sits on
    black (0.86-0.90 dominant): caption-sized text on a flat ground is
    still a card - the flat-ground route exists for exactly this."""
    small = region(top=0.46, left=0.25, width=0.50, height=0.065)
    im = paint(flat(), small, colour=(200, 170, 90))
    out = classify_frame(im, [small])
    assert out["verdict"] == "card", out
    assert out["headline"] is False, out
    assert out["dominant_share"] >= FLAT_DOMINANT_SHARE, out


def test_gradient_splash_with_headline_is_card_via_headline():
    """Example Max's purple gradient (0.23-0.25 dominant share) is nowhere near
    flat, but its title is headline-sized: the headline route admits it."""
    im = paint(gradient(), HEADLINE)
    out = classify_frame(im, [HEADLINE])
    assert out["verdict"] == "card", out
    assert out["headline"] is True, out
    assert out["dominant_share"] < FLAT_DOMINANT_SHARE, out


def test_photo_with_subtitle_is_caption():
    """ScKvReYRZ-A s0's shape: a picture (not flat) with one subtitle line
    (not headline-sized). This is the false positive CF-0093 removes."""
    im = paint(noisy(), SUBTITLE)
    out = classify_frame(im, [SUBTITLE])
    assert out["verdict"] == "caption", out
    assert out["headline"] is False, out
    assert out["dominant_share"] < FLAT_DOMINANT_SHARE, out


def test_game_still_with_two_caption_lines_is_caption():
    """_m4e4oWFmac s1/13/16/26's shape: a rendered scene with a two-line
    subtitle. Two lines clear CARD_TEXT_AREA_THRESHOLD together (0.04 of
    the frame, well over 0.015) - the old probe called that a card."""
    second = region(top=0.93, left=0.25, width=0.50, height=0.04)
    im = paint(paint(noisy(seed=3), GAME_CAPTION), second)
    regions = [GAME_CAPTION, second]
    assert text_area(regions) >= CARD_TEXT_AREA_THRESHOLD
    out = classify_frame(im, regions)
    assert out["verdict"] == "caption", out


def test_no_text_is_none():
    """A frame with no text says nothing about cards either way - it is
    not counted as caption evidence either, so a captionless card (a logo
    animation) still goes to CLIP alone."""
    out = classify_frame(flat(), [])
    assert out["verdict"] is None, out
    assert out["dominant_share"] is None, out
    out = classify_frame(noisy(), [])
    assert out["verdict"] is None, out


def test_watermark_below_area_threshold_is_none():
    """A corner watermark is under CARD_TEXT_AREA_THRESHOLD (CF-0010's
    number), so the frame is None - even on a flat ground, where the flat
    route would otherwise have called it a card."""
    assert text_area([WATERMARK]) < CARD_TEXT_AREA_THRESHOLD
    out = classify_frame(paint(flat(), WATERMARK), [WATERMARK])
    assert out["verdict"] is None, out
    assert out["headline"] is False, out


def test_tall_narrow_rotated_text_is_not_a_headline():
    """A book spine or a hand-addressed envelope gives Vision a box taller
    than HEADLINE_MIN_HEIGHT but narrower than it is tall. has_headline()'s
    width condition drops it: on a picture such a frame is a caption, not
    a card, even though the box clears the height bar three times over."""
    spine = region(top=0.30, left=0.47, width=0.06, height=0.30)
    assert spine["height"] >= HEADLINE_MIN_HEIGHT
    assert not has_headline([spine])
    # The same box, wide enough - a genuine headline.
    assert has_headline([region(top=0.30, left=0.20, width=0.30, height=0.30)])
    # And a square box counts (at least as wide as tall, not strictly wider).
    assert has_headline([region(top=0.30, left=0.40, width=0.12, height=0.12)])
    im = paint(noisy(seed=5), spine)
    out = classify_frame(im, [spine])
    assert out["verdict"] == "caption", out
    assert out["headline"] is False, out


def test_headline_height_boundary_matches_the_calibration():
    """HEADLINE_MIN_HEIGHT sits between the tallest overlay measured (0.090,
    UaWVjS5SId4 s28's wall sign) and the shortest card line (0.106,
    ZZ_urA56pJE s33's tabloid headline). Both real numbers land on the
    side the calibration put them."""
    sign = region(top=0.40, left=0.30, width=0.40, height=0.090)
    tabloid = region(top=0.40, left=0.10, width=0.80, height=0.106)
    assert not has_headline([sign])
    assert has_headline([tabloid])
    # On a picture the sign is a caption; the tabloid line is a card even
    # on a picture (newsprint measured 0.98 flat, but it should not need it).
    assert classify_frame(paint(noisy(seed=7), sign), [sign])["verdict"] == "caption"
    assert classify_frame(paint(noisy(seed=7), tabloid), [tabloid])["verdict"] == "card"


def test_photo_with_a_list_of_small_text_is_not_a_card():
    """CF-0061's neighbour finding: an aerial photo with a Patreon
    supporters list over it - a lot of text by area, none of it
    headline-sized, on a picture. Area alone (the old signal) reads it as
    a card outright; neither of the new signals does."""
    lines = [region(top=0.20 + i * 0.05, left=0.30, width=0.40, height=0.035)
             for i in range(12)]
    assert text_area(lines) > 0.15  # ten times the area threshold
    im = noisy(seed=11)
    for line in lines:
        im = paint(im, line, colour=(255, 255, 255))
    out = classify_frame(im, lines)
    assert out["verdict"] == "caption", out
    assert out["headline"] is False, out


def test_dominant_share_masks_the_text_boxes():
    """The colour share is measured on the picture *outside* the text: a
    white title on black must not lower the black's share. Without the
    boxes the same frame's share drops by the title's area."""
    box = region(top=0.30, left=0.10, width=0.80, height=0.40)  # a third of the frame
    im = paint(flat(), box)
    masked = dominant_colour_share(im, [box])
    unmasked = dominant_colour_share(im, [])
    assert masked > 0.99, masked
    assert unmasked < 0.75, unmasked
    assert unmasked < masked


def test_dominant_share_is_flat_for_solid_and_low_for_noise():
    assert dominant_colour_share(flat()) == 1.0
    assert dominant_colour_share(flat((30, 60, 200))) == 1.0  # Example+ blue, not just black
    assert dominant_colour_share(noisy()) < 0.05
    assert dominant_colour_share(gradient()) < FLAT_DOMINANT_SHARE


def test_grain_on_a_dark_card_stays_in_one_bin():
    """Film grain and compression noise on a black card must not split its
    one colour into many: real near-black cards measured 0.76-0.93."""
    rng = np.random.RandomState(1)
    px = np.clip(rng.normal(12, 4, size=(H, W, 3)), 0, 31).astype(np.uint8)
    im = Image.fromarray(px, "RGB")
    share = dominant_colour_share(im)
    assert share >= FLAT_DOMINANT_SHARE, share


def test_text_wall_reads_flat():
    """A frame whose text boxes cover everything has no picture left to
    judge and reads as flat: a wall of text is a card's kind of frame."""
    wall = region(top=0.0, left=0.0, width=1.0, height=1.0)
    assert dominant_colour_share(noisy(), [wall]) == 1.0
    assert classify_frame(noisy(), [wall])["verdict"] == "card"


def test_accepts_a_path_as_well_as_an_image(tmp_path=None):
    """probe_card_text() hands over the ffmpeg frame's path, not a PIL
    image; both spellings give the same answer."""
    import tempfile
    im = paint(noisy(seed=2), SUBTITLE)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "frame.png"
        im.save(p)
        from_path = classify_frame(p, [SUBTITLE])
        from_str = classify_frame(str(p), [SUBTITLE])
    from_image = classify_frame(im, [SUBTITLE])
    assert from_path["verdict"] == from_str["verdict"] == from_image["verdict"] == "caption"
    assert abs(from_path["dominant_share"] - from_image["dominant_share"] ) < 1e-6


def test_pillarbox_bars_would_fake_a_flat_ground():
    """Why probe_card_text() crops to the source's picture first: a
    vertical short pillarboxed inside 16:9 (UaWVjS5SId4: 748 of 1920
    columns are picture) has black bars over 60% of the frame, and the bars
    alone would read as a flat card ground. Cropped, the picture is
    judged on its own and is not flat."""
    picture_w = int(W * 748 / 1920)
    picture = noisy(seed=4, size=(picture_w, H))
    boxed = Image.new("RGB", (W, H), (0, 0, 0))
    boxed.paste(picture, ((W - picture_w) // 2, 0))
    assert dominant_colour_share(boxed) >= FLAT_DOMINANT_SHARE
    assert dominant_colour_share(picture) < FLAT_DOMINANT_SHARE


def test_area_threshold_is_still_importable_from_index_footage():
    """The constant moved to card_frame.py; callers that imported it from
    index_footage keep working and see the same number."""
    import index_footage
    assert index_footage.CARD_TEXT_AREA_THRESHOLD == CARD_TEXT_AREA_THRESHOLD
    assert card_frame.CARD_TEXT_AREA_THRESHOLD == 0.015


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)

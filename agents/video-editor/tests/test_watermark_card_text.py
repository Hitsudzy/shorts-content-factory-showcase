#!/usr/bin/env python3
"""CF-0094: a platform's corner bug is not the card's own text.

CF-0047's ink fraction is a ratio *inside* the frame's text boxes, so a
fade-to-black whose only text is the "Example max" bug read 57% lit - 57% of the
bug's own pixels are lit - and SJVmeJaS44s s8 was accepted as a card under
three blocks (batch 2026-09-03T2037Z, RUN_LOG.txt:26). The arithmetic was
right; what was missing was any notion of how much of the frame the text
takes and where it sits.

Fixtures are the real accurate-mode Vision boxes measured on the pool's own
probe frames (same PROBE_OFFSET, same letterbox crop the indexer applies),
so the two constants are tested against the data they were bracketed by,
not against numbers invented to pass. Pure asserts on is_watermark_box() /
card_text_regions() / evaluate(); the one image-backed test paints its own
frame and stubs Vision, so nothing here needs the worker. Run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import io
import json
import sys
import tempfile
import types
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import qc_asset  # noqa: E402


def box(top, bottom, left, width, text=""):
    return {"top": top, "bottom": bottom, "left": left, "width": width,
            "height": bottom - top, "text": text}


# SJVmeJaS44s s8 - the frame this task exists for: a near-black fade
# (black 0.824, luma 21.3) with nothing on it but the "Example max" bug, which
# Vision reads as two boxes in the top-right corner. Cached ink 0.5745.
EXAMPLE_MAX_S8 = [box(0.073, 0.141, 0.884, 0.068, "Example Network"),
              box(0.141, 0.182, 0.884, 0.065, "max")]
# The same bug on the other upload of the teaser (1RnyZgfN-JY s5) and on
# other frames of it: the box moves by a few thousandths, never out of the
# corner.
EXAMPLE_MAX_S5 = [box(0.042, 0.105, 0.882, 0.070, "Example Network"),
              box(0.105, 0.150, 0.885, 0.064, "max")]
# 9s8gGcvBVIM s3/s4 - ExampleStream's bug, one box.
EXAMPLESTREAM_S3 = [box(0.052, 0.108, 0.850, 0.102, "EXAMPLESTREAM")]

# eokBqEFiVHs s51 - "AND CHANGED / THE WORLD", white block letters on dark
# newsprint; black 0.874, luma 27.0, cached ink 0.52, 57.7% at the real
# gate on the cut clip (RUN_LOG.txt:21). The legitimate relaxation that has
# to keep passing.
INK_S51 = [box(0.346, 0.453, 0.297, 0.404, "AND CHANGED"),
           box(0.454, 0.671, 0.188, 0.625, "THE WORLD")]
# 7EY3QyPTEso s25 - a date card whose top line, "ONLY ON EXAMPLESTREAM", is the
# smallest card line in the pool at 0.0146 of the frame: *smaller* than
# WATERMARK_MAX_AREA. It is card text because of where it is, not its size.
DATE_CARD_S25 = [box(0.328, 0.381, 0.363, 0.275, "ONLY ON EXAMPLESTREAM"),
                 box(0.427, 0.578, 0.286, 0.416, "OCTOBER 1"),
                 box(0.823, 0.872, 0.340, 0.321, "ТОЛЬКО HA EXAMPLESTREAM"),
                 box(0.890, 0.939, 0.403, 0.193, "C1ОКТЯБРЯ")]
# -xSxaE1ClEE s36 - a single centred word.
LIFE_S36 = [box(0.448, 0.563, 0.428, 0.143, "LIFE")]
# 1RnyZgfN-JY s21 - a dark scene with the bug *and* a burned-in caption at
# the bottom centre. The caption is not this task's business (CF-0062 is):
# it must read exactly as it did.
CAPTION_S21 = [box(0.802, 0.866, 0.289, 0.424, "Let's hope you show some talent"),
               box(0.898, 0.975, 0.298, 0.406, "on the Quidditch pitch, Hollow.")]

WATERMARKS = EXAMPLE_MAX_S8 + EXAMPLE_MAX_S5 + EXAMPLESTREAM_S3
CARD_TEXT = INK_S51 + DATE_CARD_S25 + LIFE_S36 + CAPTION_S21


# --- the rule ---------------------------------------------------------------

def test_the_example_max_bug_is_not_card_text():
    """SJVmeJaS44s s8: both boxes are the bug, nothing is left to measure."""
    assert all(qc_asset.is_watermark_box(b) for b in EXAMPLE_MAX_S8)
    assert qc_asset.card_text_regions(EXAMPLE_MAX_S8) == []


def test_every_measured_platform_bug_reads_as_one():
    for b in WATERMARKS:
        assert qc_asset.is_watermark_box(b), b["text"]


def test_no_measured_card_text_reads_as_a_bug():
    """Ink s51 above all - but also the smallest card line in the pool and a
    single centred word."""
    for b in CARD_TEXT:
        assert not qc_asset.is_watermark_box(b), b["text"]
    assert qc_asset.card_text_regions(INK_S51) == INK_S51


def test_a_card_that_carries_the_bug_keeps_only_its_own_text():
    """The common case on a commercial trailer: a real card *and* the
    platform bug on the same frame. The bug drops out, the card stays."""
    kept = qc_asset.card_text_regions(INK_S51 + EXAMPLE_MAX_S8)
    assert kept == INK_S51


def test_both_axes_are_required():
    """Size alone or position alone would each be wrong on real data.
    ONLY ON EXAMPLESTREAM (0.0146) is under the area cap and is card text because
    it is centred; a corner box bigger than any bug is kept because of its
    size - a title legitimately set in a corner must not vanish."""
    small_centred = DATE_CARD_S25[0]
    assert small_centred["width"] * small_centred["height"] < qc_asset.WATERMARK_MAX_AREA
    assert not qc_asset.is_watermark_box(small_centred)
    big_corner = box(0.03, 0.15, 0.70, 0.28, "NOW STREAMING")
    assert big_corner["width"] * big_corner["height"] >= qc_asset.WATERMARK_MAX_AREA
    assert not qc_asset.is_watermark_box(big_corner)


def test_any_corner_counts_not_just_top_right():
    """The rule is about a bug's shape, not Example Network's choice of corner."""
    for top, left in [(0.05, 0.05), (0.05, 0.88), (0.90, 0.05), (0.90, 0.88)]:
        assert qc_asset.is_watermark_box(box(top, top + 0.06, left, 0.07))
    # ...and the same box in the middle of an edge is not in a corner.
    assert not qc_asset.is_watermark_box(box(0.05, 0.11, 0.47, 0.07))
    assert not qc_asset.is_watermark_box(box(0.47, 0.53, 0.88, 0.07))


def test_the_constants_sit_in_the_measured_gap_not_on_its_edge():
    """Every bug box is well under the area cap and well inside the corner
    margin; every card box's centre is well outside it. Neither constant is
    a squeeze."""
    for b in WATERMARKS:
        area = b["width"] * b["height"]
        assert area <= 0.4 * qc_asset.WATERMARK_MAX_AREA, b
        cy = (b["top"] + b["bottom"]) / 2
        cx = b["left"] + b["width"] / 2
        assert cy <= qc_asset.CORNER_MARGIN - 0.08, b
        assert 1 - cx <= qc_asset.CORNER_MARGIN - 0.10, b
    for b in CARD_TEXT:
        cx = b["left"] + b["width"] / 2
        assert min(cx, 1 - cx) >= qc_asset.CORNER_MARGIN + 0.10, b


# --- what the verdict does with it ------------------------------------------

def vision(coverage=1.0, side=720):
    return {"source_size": {"width": side, "height": side},
            "roi_source": "faces", "roi_coverage": coverage}


def verdict(black, luma, ink):
    return qc_asset.evaluate(vision(), black, luma, 720, 0.65, 0.90,
                             qc_asset.MIN_MEAN_LUMA, card_ink=ink)


def test_wren_hollow_s8_is_rejected_at_its_real_numbers():
    """With the bug excluded the frame has no card text - ink None - and
    fails the darkness check exactly like a frame with no text at all."""
    v = verdict(0.824, 21.3, ink=None)
    assert not v["usable"]
    assert "luma" in v["failed"]
    assert v["relaxations"] == []


def test_ink_s51_still_passes_at_both_of_its_real_numbers():
    """The legitimate dark card: cached 0.52 on the probe frame, 0.577 on
    the cut clip at the real gate. Both keep the excusal, on the record."""
    for ink in (0.52, 0.577):
        v = verdict(0.874, 27.0, ink=ink)
        assert v["usable"], v["failures"]
        assert v["relaxations"] and all("text lit" in r for r in v["relaxations"])


# --- the measurement end to end, on a painted frame ------------------------

def stub_vision(regions):
    """Stand in for vision_client.text_regions with fixed boxes."""
    mod = types.ModuleType("vision_client")
    mod.text_regions = lambda path, level=0: list(regions)
    sys.modules["vision_client"] = mod


def paint(path, size=(640, 360), lit=()):
    """A near-black frame with bright rectangles inside the given boxes."""
    im = Image.new("L", size, 8)
    w, h = size
    for b in lit:
        im.paste(220, (int(b["left"] * w), int(b["top"] * h),
                       int((b["left"] + b["width"]) * w), int(b["bottom"] * h)))
    im.save(path)


def test_card_text_ink_measures_only_the_cards_own_text():
    saved = sys.modules.get("vision_client")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            # A fade with only the bug: the bug's pixels are lit, and it
            # still reads as "no card text".
            paint(frame, lit=EXAMPLE_MAX_S8)
            stub_vision(EXAMPLE_MAX_S8)
            r = qc_asset.card_text_ink(frame)
            assert r == {"ink": None, "text_boxes": 2, "watermark_boxes": 2}
            assert qc_asset.card_ink(frame) is None
            # The same bug on a real card: the ink is the card's, the bug is
            # neither counted nor diluting.
            paint(frame, lit=EXAMPLE_MAX_S8 + INK_S51)
            stub_vision(EXAMPLE_MAX_S8 + INK_S51)
            r = qc_asset.card_text_ink(frame)
            assert r["text_boxes"] == 4 and r["watermark_boxes"] == 2
            assert r["ink"] > 0.9
            # No text at all is still None with nothing to blame on a bug.
            stub_vision([])
            assert qc_asset.card_text_ink(frame) == {"ink": None, "text_boxes": 0,
                                                     "watermark_boxes": 0}
    finally:
        if saved is not None:
            sys.modules["vision_client"] = saved
        else:
            sys.modules.pop("vision_client", None)


def test_the_cli_names_a_watermark_only_frame_in_its_failures():
    """resolve_anchors.usable() records `failures` as the reason a candidate
    was rejected; "dead pixels" alone reads like a letterbox. The verdict
    has to say the only text was a bug."""
    saved = (qc_asset.analyse, qc_asset.card_text_ink, qc_asset.luma_stats, sys.argv)
    try:
        qc_asset.analyse = lambda path, aspect: vision()
        qc_asset.luma_stats = lambda path: (0.824, 21.3)
        qc_asset.card_text_ink = lambda path: {"ink": None, "text_boxes": 2,
                                               "watermark_boxes": 2}
        sys.argv = ["qc_asset.py", "s8.png", "--card", "--json", "--max-black", "0.90"]
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                qc_asset.main()
            except SystemExit as e:
                assert e.code == 1
        result = json.loads(out.getvalue())
        assert not result["usable"]
        assert result["watermark_boxes"] == 2 and result["card_text_boxes"] == 0
        assert any("watermark-shaped" in f for f in result["failures"])
        assert result["relaxations"] == []
    finally:
        qc_asset.analyse, qc_asset.card_text_ink, qc_asset.luma_stats, sys.argv = saved


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            passed += 1
    print(f"\n{passed}/{passed} passed  # watermark-vs-card-text checks")

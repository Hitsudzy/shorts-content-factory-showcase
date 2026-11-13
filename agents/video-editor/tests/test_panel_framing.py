#!/usr/bin/env python3
"""CF-0327: the planner may not point a window at a sliver of an inset panel.

`build_render_plan.frame_the_panel()` on the synthetic bad input CF-0024 asks
for - a drawn split screen, framed the way the planner framed
`mormon-wives-comeback` block 11 (`example-film/2026-09-17T1901Z`): focus on the
face at x 0.5305, panel across 0.056-0.459 of the source, 24 % of the panel
delivered flush against the left edge.

The three outcomes, each with its own test: the framing moves and the panel
comes out whole; the framing moves off a panel too wide to hold and the panel
comes out absent; nothing can move without losing the subject, so nothing does
and the record says `unresolved` for `qc_render` to refuse.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_render_plan  # noqa: E402
import inset_panel  # noqa: E402
from common import MIN_COVERAGE  # noqa: E402

SIZE = (1920, 1080)
ASPECT = (1080, 1920)


def _frame(path, x0, x1):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", SIZE, (28, 26, 32))
    ImageDraw.Draw(im).rectangle([int(x0 * SIZE[0]), 0, int(x1 * SIZE[0]), SIZE[1]],
                                 fill=(232, 188, 196))
    im.save(path)
    return path


def _asset(focus_x, fit="cover"):
    return {"kind": "clip", "focus": {"x": focus_x, "y": 0.3974}, "fit": fit,
            "zoom": 1.0, "source_size": {"width": SIZE[0], "height": SIZE[1]}}


def _info(face_x, face_w=240):
    """An analyse()-shaped record with one face at `face_x` (source pixels)."""
    return {"source_size": {"width": SIZE[0], "height": SIZE[1]},
            "roi": {"x": face_x, "y": 300, "width": face_w, "height": face_w},
            "roi_source": "faces", "roi_parts": None}


def _visible(asset, panel):
    window = inset_panel.window_for(SIZE, asset["focus"]["x"], asset["focus"]["y"],
                                    asset["zoom"], asset["fit"], ASPECT)
    return inset_panel.visible_fraction(panel, window, SIZE)


def test_the_mormon_block_is_moved_off_its_panel():
    """The real geometry: a 774 px panel cannot fit a 607 px window, so the
    only legal answer left is to show none of it - and the guest's face, which
    the shot is of, is to the right of the panel and survives the move."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = _frame(Path(tmp) / "split.png", 0.056, 0.459)
        asset = _asset(0.5305)
        panel = build_render_plan.frame_the_panel(asset, frame, _info(1150),
                                                  MIN_COVERAGE, ASPECT)
        assert panel is not None and panel["moved"], panel
        assert panel["verdict"] == inset_panel.ABSENT, panel
        assert asset["focus"]["x"] > 0.5305, asset
        assert _visible(asset, panel) <= inset_panel.PANEL_ABSENT


def test_a_panel_that_fits_is_delivered_whole():
    with tempfile.TemporaryDirectory() as tmp:
        frame = _frame(Path(tmp) / "split.png", 0.42, 0.66)
        asset = _asset(0.20)
        panel = build_render_plan.frame_the_panel(asset, frame, _info(1000),
                                                  MIN_COVERAGE, ASPECT)
        assert panel["moved"] and panel["verdict"] == inset_panel.WHOLE, panel
        assert _visible(asset, panel) >= inset_panel.PANEL_WHOLE


def test_a_framing_that_already_shows_the_panel_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        frame = _frame(Path(tmp) / "split.png", 0.42, 0.66)
        asset = _asset(0.5)
        panel = build_render_plan.frame_the_panel(asset, frame, _info(1000),
                                                  MIN_COVERAGE, ASPECT)
        assert panel["verdict"] == inset_panel.WHOLE and not panel["moved"], panel
        assert asset["focus"]["x"] == 0.5


def test_the_subject_is_never_spent_on_the_panel():
    """The face sits exactly where the sliver is. Every move that answers the
    panel loses it, so nothing moves and the record hands the decision on."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = _frame(Path(tmp) / "split.png", 0.056, 0.459)
        asset = _asset(0.5305)
        panel = build_render_plan.frame_the_panel(asset, frame, _info(820, 120),
                                                  MIN_COVERAGE, ASPECT)
        assert panel["verdict"] == "unresolved", panel
        assert not panel["moved"]
        assert asset["focus"]["x"] == 0.5305


def test_a_shot_with_no_panel_costs_nothing_and_says_nothing():
    """Block 10 of the same video: the picture the user saw whole. The planner
    must not put a `panel` record on an asset that has none."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "gradient.png"
        im = Image.new("L", SIZE)
        im.putdata([int(255 * (x / SIZE[0])) for _ in range(SIZE[1])
                    for x in range(SIZE[0])])
        im.convert("RGB").save(p)
        asset = _asset(0.6214)
        assert build_render_plan.frame_the_panel(asset, p, _info(1200),
                                                 MIN_COVERAGE, ASPECT) is None
        assert asset["focus"]["x"] == 0.6214


def test_a_contained_asset_is_never_touched():
    """`contain` shows the whole source - a card, CF-0047 - so there is no
    sliver to fix and no framing to spend."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = _frame(Path(tmp) / "split.png", 0.056, 0.459)
        asset = _asset(0.5, fit="contain")
        assert build_render_plan.frame_the_panel(asset, frame, _info(1000),
                                                 MIN_COVERAGE, ASPECT) is None


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

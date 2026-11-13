#!/usr/bin/env python3
"""CF-0327: the shot's own inset panel, and the window that cuts it in half.

The defect, in numbers taken off the material once and frozen here.
`mormon-wives-comeback` (`example-film/2026-09-17T1901Z`), the render the user
rejected at 29 s. Two consecutive blocks of the same source video, both of
shots that carry an on-screen panel, framed by the same planner:

    block 10  25.58-28.98s  focus.x 0.6214  no panel border on its frame
    block 11  28.98-31.16s  focus.x 0.5305  panel across x 0.056-0.459

Block 11's frame at composition 29.5 s was measured column by column: two
vertical borders, each stepping across more than 25 luma in 96-97 % of the
frame's 1080 rows, at x=127 and x=871 of 1920. Block 10's frame, the "insert
that was drawn whole" one second earlier, has no such border at all - its
strongest candidate column runs through 57 % of the rows, which is a shoulder
and a doorway, not a panel. `MIN_EDGE_ROWS = 0.85` sits in that gap, and that
gap is why the detector can tell the two apart at all.

Against the window block 11 was actually framed with - `smart_crop.
delivered_window((1920, 1080), (0.5305, ...), 1.0, 9, 16, "cover")`, which is
x 696.3..1303.8 - the panel keeps 0.24 of its width. A quarter of a panel,
flush against the left edge: the "narrow pink strip" of the user's verdict, as
one number.

The synthetic bad input CF-0024 asks for is `_panel_frame()` below: a drawn
split screen with a bright panel on a dark ground, at a stated position, so
that every threshold in the module is exercised without a frame of footage.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import inset_panel  # noqa: E402

SIZE = (1920, 1080)

# The measurement above, frozen.
MORMON_PANEL = {"x0": 0.0563, "x1": 0.4594, "width": 0.4031, "rows": 0.967}
MORMON_FOCUS_X = 0.5305


def _panel_frame(path, x0, x1, width=1920, height=1080,
                 panel=(232, 188, 196), ground=(28, 26, 32)):
    """A drawn split screen: a bright panel over `x0..x1` on a dark ground.

    The synthetic bad input. Two hard vertical borders running the full height
    is exactly the structure the detector is looking for, and drawing it means
    the test states its own input instead of depending on a frame of footage
    that a rotation will eventually delete.
    """
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (width, height), ground)
    d = ImageDraw.Draw(im)
    d.rectangle([int(x0 * width), 0, int(x1 * width), height], fill=panel)
    im.save(path)
    return path


def test_synthetic_panel_is_found():
    with tempfile.TemporaryDirectory() as tmp:
        p = _panel_frame(Path(tmp) / "split.png", 0.07, 0.45)
        found = inset_panel.find_panel(p)
        assert found is not None, "a drawn split screen has a panel"
        assert abs(found["x0"] - 0.07) < 0.02, found
        assert abs(found["x1"] - 0.45) < 0.02, found
        assert found["rows"] >= inset_panel.MIN_EDGE_ROWS, found


def test_a_plain_gradient_is_not_a_panel():
    """The block 10 case: bright on one side, dark on the other, no border.

    This is the half of the answer that keeps the gate from firing on ordinary
    footage - and the reason the fix is not "centre every window".
    """
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        im = Image.new("L", SIZE)
        im.putdata([int(255 * (x / SIZE[0])) for _ in range(SIZE[1])
                    for x in range(SIZE[0])])
        p = Path(tmp) / "gradient.png"
        im.convert("RGB").save(p)
        assert inset_panel.border_columns(p) == []
        assert inset_panel.find_panel(p) is None


def test_a_thin_strip_is_not_a_panel():
    """A lower-third sting or a sign is bordered too, and is not the defect."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _panel_frame(Path(tmp) / "strip.png", 0.40, 0.46)
        assert inset_panel.find_panel(p) is None


def test_the_mormon_window_keeps_a_quarter_of_the_panel():
    window = inset_panel.window_for(SIZE, MORMON_FOCUS_X, 0.3974, 1.0, "cover")
    assert abs(window[0] - 696.3) < 1.0, window
    assert abs(window[2] - 607.5) < 1.0, window
    fraction = inset_panel.visible_fraction(MORMON_PANEL, window, SIZE)
    assert 0.20 < fraction < 0.30, fraction
    assert inset_panel.verdict(fraction) == inset_panel.CUT


def test_verdict_has_exactly_three_answers():
    assert inset_panel.verdict(1.0) == inset_panel.WHOLE
    assert inset_panel.verdict(inset_panel.PANEL_WHOLE) == inset_panel.WHOLE
    assert inset_panel.verdict(0.0) == inset_panel.ABSENT
    assert inset_panel.verdict(inset_panel.PANEL_ABSENT) == inset_panel.ABSENT
    assert inset_panel.verdict(0.5) == inset_panel.CUT
    assert inset_panel.verdict(None) is None


def test_resolve_moves_the_window_off_a_panel_too_wide_to_fit():
    """Block 11's panel is 774 px against a 607 px window: it cannot be shown
    whole, so the only allowed answer left is to show none of it."""
    focus, outcome = inset_panel.resolve_focus(MORMON_PANEL, SIZE, MORMON_FOCUS_X)
    assert outcome == inset_panel.ABSENT, (focus, outcome)
    window = inset_panel.window_for(SIZE, focus, 0.4, 1.0, "cover")
    assert inset_panel.visible_fraction(MORMON_PANEL, window, SIZE) <= inset_panel.PANEL_ABSENT
    # And it moved right, off the panel - the shortest way out of the sliver.
    assert focus > MORMON_FOCUS_X


def test_resolve_keeps_a_panel_that_fits_whole():
    panel = {"x0": 0.42, "x1": 0.66, "width": 0.24, "rows": 0.95}
    focus, outcome = inset_panel.resolve_focus(panel, SIZE, 0.20)
    assert outcome == inset_panel.WHOLE, (focus, outcome)
    window = inset_panel.window_for(SIZE, focus, 0.4, 1.0, "cover")
    assert inset_panel.visible_fraction(panel, window, SIZE) >= inset_panel.PANEL_WHOLE
    # And a panel that fits is shown rather than stepped off, even though
    # stepping off it would have moved the framing less.
    assert abs(focus - 0.20) > 0.1


def test_resolve_leaves_a_window_that_already_answers_alone():
    """Nothing is moved when the framing already shows the panel whole - the
    focus is where the subject is, and this may only spend it on the defect."""
    panel = {"x0": 0.42, "x1": 0.66, "width": 0.24, "rows": 0.95}
    window = inset_panel.window_for(SIZE, 0.5, 0.4, 1.0, "cover")
    assert inset_panel.verdict(
        inset_panel.visible_fraction(panel, window, SIZE)) == inset_panel.WHOLE
    # Which is why the planner never asks: it moves a window only on `cut`.
    # Asked anyway, the answer it gets back is the same framing to a quarter
    # of a percent - `candidates()` places the panel wholly inside, where the
    # floor accepts 99.3 % of it, and that difference is the whole move.
    focus, outcome = inset_panel.resolve_focus(panel, SIZE, 0.5)
    assert outcome == inset_panel.WHOLE
    assert abs(focus - 0.5) < 0.005, focus


def test_candidates_offer_the_planner_a_fallback():
    """Showing the panel ranks above hiding it, and both are on the list -
    the planner needs the second one when the first loses the face."""
    panel = {"x0": 0.42, "x1": 0.66, "width": 0.24, "rows": 0.95}
    found = inset_panel.candidates(panel, SIZE, 0.20)
    assert [c[1] for c in found][0] == inset_panel.WHOLE, found
    assert inset_panel.ABSENT in [c[1] for c in found], found
    for focus, outcome in found:
        window = inset_panel.window_for(SIZE, focus, 0.4, 1.0, "cover")
        fraction = inset_panel.visible_fraction(panel, window, SIZE)
        assert inset_panel.verdict(fraction) == outcome, (focus, outcome, fraction)


def test_contain_shows_the_whole_source_so_nothing_is_ever_cut():
    window = inset_panel.window_for(SIZE, 0.5305, 0.4, 1.0, "contain")
    assert inset_panel.visible_fraction(MORMON_PANEL, window, SIZE) == 1.0


def test_a_picture_that_cannot_be_read_is_not_an_accusation():
    """This gate refuses videos, so everything it cannot look at is silence.
    A path that is not there, a file that is not an image, a portrait still -
    none of them may raise, and none of them may report a panel."""
    assert inset_panel.border_columns("/nowhere/at/all.png") == []
    assert inset_panel.find_panel("/nowhere/at/all.png") is None
    with tempfile.TemporaryDirectory() as tmp:
        junk = Path(tmp) / "notanimage.png"
        junk.write_text("this is not a PNG")
        assert inset_panel.find_panel(junk) is None
        from PIL import Image
        tall = Path(tmp) / "portrait.png"
        Image.new("RGB", (1080, 1920), (40, 40, 40)).save(tall)
        assert inset_panel.find_panel(tall) is None
    assert inset_panel.visible_fraction(None, (0, 0, 10, 10), SIZE) is None
    assert inset_panel.visible_fraction(MORMON_PANEL, None, SIZE) is None
    assert inset_panel.candidates(None, SIZE, 0.5) == []


def test_mode_and_floor_come_from_configuration():
    import os
    assert inset_panel.mode_of({}) == inset_panel.DEFAULT_MODE
    assert inset_panel.mode_of(
        {"qc_thresholds": {inset_panel.MODE_KEY: "warn"}}) == inset_panel.MODE_WARN
    assert inset_panel.mode_of(
        {"qc_thresholds": {inset_panel.MODE_KEY: "OFF"}}) == inset_panel.MODE_OFF
    # A value nobody recognises is not a disabled gate.
    assert inset_panel.mode_of(
        {"qc_thresholds": {inset_panel.MODE_KEY: "maybe"}}) == inset_panel.DEFAULT_MODE
    os.environ[inset_panel.MODE_ENV] = "warn"
    try:
        assert inset_panel.mode_of(
            {"qc_thresholds": {inset_panel.MODE_KEY: "fail"}}) == inset_panel.MODE_WARN
    finally:
        del os.environ[inset_panel.MODE_ENV]
    assert inset_panel.floor_of({}) == inset_panel.PANEL_WHOLE
    assert inset_panel.floor_of({"qc_thresholds": {inset_panel.FLOOR_KEY: 0.8}}) == 0.8
    assert inset_panel.floor_of({"qc_thresholds": {inset_panel.FLOOR_KEY: 4}}) == \
        inset_panel.PANEL_WHOLE


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

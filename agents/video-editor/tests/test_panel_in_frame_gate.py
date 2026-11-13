#!/usr/bin/env python3
"""CF-0327: `qc_render`'s panel gate - the machine catches the cut-off insert.

DoD item 4 of 1.4.5: the defect the user found by watching the render at 29 s
has to be found by a gate before the render is ever shown to him. The gate
measures the shot's own inset panel against the window the block is framed
with (`qc_render.panel_blocks()`), and refuses the render when what reaches
the screen is a sliver of it.

The input is synthetic, as CF-0024 asks: a drawn split screen written to a PNG
and a two-block plan that points at it - one block framed the way
`mormon-wives-comeback` block 11 was framed (a quarter of the panel, flush
against the left edge) and one framed so the same panel is off screen
entirely. No ffmpeg, no Vision, no render: `still` assets are read straight off
disk by `source_frame()`, which is what makes this a check rather than a
measurement.

The third test is the one the task's last paragraph is about: the gate is a new
refusal, so its mode has to be configuration. The same plan and the same
picture come out as a failure or as a note depending on
`qc_thresholds.panel_in_frame_mode` alone.

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
import qc_render  # noqa: E402

SIZE = (1920, 1080)
PANEL = (0.056, 0.459)          # mormon-wives-comeback block 11, measured
CUT_FOCUS = 0.5305              # the focus that delivered 24 % of it
CLEAR_FOCUS = 0.95              # a window right of the panel: none of it


def _split_screen(path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", SIZE, (28, 26, 32))
    ImageDraw.Draw(im).rectangle(
        [int(PANEL[0] * SIZE[0]), 0, int(PANEL[1] * SIZE[0]), SIZE[1]],
        fill=(232, 188, 196))
    im.save(path)
    return path


def _plan(src, focus_xs, thresholds=None):
    return {
        "output": {"width": 1080, "height": 1920},
        "qc_thresholds": dict(thresholds or {}),
        "blocks": [
            {"start": 2.0 * k, "end": 2.0 * k + 2.0,
             "asset": {"kind": "still", "src": str(src), "fit": "cover",
                       "zoom": 1.0, "roi_source": "faces",
                       "focus": {"x": fx, "y": 0.3974},
                       "source_size": {"width": SIZE[0], "height": SIZE[1]}}}
            for k, fx in enumerate(focus_xs)],
    }


def test_the_cut_panel_is_caught_and_the_clear_one_is_not():
    with tempfile.TemporaryDirectory() as tmp:
        src = _split_screen(Path(tmp) / "split.png")
        rows = qc_render.panel_blocks("unused.mp4",
                                      _plan(src, [CUT_FOCUS, CLEAR_FOCUS]))
        assert len(rows) == 2, rows
        cut, clear = rows
        assert cut["index"] == 0 and cut["fault"] is True, cut
        assert cut["verdict"] == inset_panel.CUT
        assert 0.20 < cut["visible"] < 0.30, cut
        assert "against the edge of the frame" in cut["reason"]
        assert clear["fault"] is False and clear["verdict"] == inset_panel.ABSENT, clear


def test_the_failure_line_names_the_gate():
    line = ("blocks delivering a cut-off inset panel: block 0 at 1.0s - the shot "
            "carries an inset panel across 0.06-0.46 of its width")
    assert qc_render.failed_gates([line]) == ["panel"]


def test_a_contained_block_is_never_judged():
    """The whole source is on screen: nothing can be cut off it."""
    with tempfile.TemporaryDirectory() as tmp:
        src = _split_screen(Path(tmp) / "split.png")
        plan = _plan(src, [CUT_FOCUS])
        plan["blocks"][0]["asset"]["fit"] = "contain"
        assert qc_render.panel_blocks("unused.mp4", plan) == []


def test_a_block_under_an_opaque_insert_is_not_judged():
    """CF-0363: there is no shot under a proof card to have a panel cut off."""
    with tempfile.TemporaryDirectory() as tmp:
        src = _split_screen(Path(tmp) / "split.png")
        plan = _plan(src, [CUT_FOCUS])
        plan["blocks"][0]["insert"] = {"kind": "proof", "capture_path": str(src)}
        assert qc_render.panel_blocks("unused.mp4", plan) == []


def test_the_mode_is_configuration_and_not_code():
    """The same picture, the same plan, two verdicts - and the measurement is
    written in both, because a mode that silenced it would make the rule's
    price unmeasurable (CF-0320)."""
    plan = _plan("nowhere.png", [CUT_FOCUS])
    assert inset_panel.mode_of(plan) == inset_panel.MODE_FAIL
    plan["qc_thresholds"][inset_panel.MODE_KEY] = "warn"
    assert inset_panel.mode_of(plan) == inset_panel.MODE_WARN
    plan["qc_thresholds"][inset_panel.MODE_KEY] = "off"
    assert inset_panel.mode_of(plan) == inset_panel.MODE_OFF


def test_the_channel_config_is_what_sets_the_mode():
    import build_render_plan
    assert build_render_plan.panel_gate_thresholds(None) == {}
    assert build_render_plan.panel_gate_thresholds(
        {"video_editor": {"panel_in_frame": {"mode": "warn"}}}) == {
            inset_panel.MODE_KEY: "warn"}
    assert build_render_plan.panel_gate_thresholds(
        {"video_editor": {"panel_in_frame": {"mode": "sometimes"}}}) == {}
    assert build_render_plan.panel_gate_thresholds(
        {"video_editor": {"panel_in_frame": {"mode": "fail", "floor": 0.75}}}) == {
            inset_panel.MODE_KEY: "fail", inset_panel.FLOOR_KEY: 0.75}


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

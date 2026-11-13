#!/usr/bin/env python3
"""CF-0894: the panel gate (CF-0327/CF-0493) judges a `sequence` block cut by
cut instead of skipping it.

panel_blocks() used to `continue` on anything but a clip or a still, so a
cover cut of a sequence framed onto a sliver of an on-screen panel was never
measured. It now walks the cuts on the layout every gate reads a sequence
with (qc_render.sequence_cuts(), CF-0893): each cropped cut over its own
seconds, its source read on its own clip clock, its own focus. The rows
carry `cut`.

A cut's fault is a new refusal and a new price, so until the channel says
`video_editor.panel_in_frame.sequence_cuts: true` it is kept apart
(`panel_cut_sequence_blocks`) - measured, noted, never refused or priced.

Synthetic input as in test_panel_in_frame_gate.py: a drawn split screen in a
tmp PNG, `still` cuts read straight off disk. No ffmpeg, no Vision.
"""
import _isolated_runlog  # noqa: F401,E402 - run accounting never lands in a real batch
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import inset_panel  # noqa: E402
import qc_render  # noqa: E402
from common import RENDER_CROSSFADE  # noqa: E402
from test_panel_in_frame_gate import (CLEAR_FOCUS, CUT_FOCUS, SIZE,  # noqa: E402
                                      _split_screen)


def _still(src, fx, seconds, **kw):
    return {"kind": "still", "src": str(src), "seconds": seconds, "fit": "cover",
            "zoom": 1.0, "roi_source": "faces", "focus": {"x": fx, "y": 0.3974},
            "source_size": {"width": SIZE[0], "height": SIZE[1]}, **kw}


def _plan(cuts, start=10.0, end=16.0, thresholds=None):
    return {"output": {"width": 1080, "height": 1920},
            "qc_thresholds": dict(thresholds or {}),
            "blocks": [{"start": start, "end": end,
                        "asset": {"kind": "sequence", "cuts": cuts,
                                  # build_render_plan mirrors cut 0 onto the asset
                                  **{k: v for k, v in cuts[0].items()
                                     if k not in ("kind", "seconds")}}}]}


def test_a_cover_cut_that_slivers_the_panel_is_measured_on_its_own_seconds():
    with tempfile.TemporaryDirectory() as tmp:
        src = _split_screen(Path(tmp) / "split.png")
        plan = _plan([_still(src, CLEAR_FOCUS, 3.0), _still(src, CUT_FOCUS, 3.0)])
        rows = qc_render.panel_blocks("unused.mp4", plan)
    assert [(r["index"], r.get("cut"), r["fault"]) for r in rows] == [
        (0, 0, False), (0, 1, True)], rows
    real_cut = 10.0 - RENDER_CROSSFADE + 3.0
    assert rows[1]["at"] == round((real_cut + 16.0) / 2, 2), rows[1]
    assert rows[0]["at"] == round((10.0 + real_cut) / 2, 2), rows[0]
    assert 0.20 < rows[1]["visible"] < 0.30, rows[1]
    assert "cut 1 of this block" in rows[1]["reason"], rows[1]["reason"]


def test_contained_and_blur_fill_cuts_are_not_judged():
    """The whole shot is on screen: nothing can be cut off it - whatever
    build_render_plan mirrored onto the sequence asset from cut 0."""
    with tempfile.TemporaryDirectory() as tmp:
        src = _split_screen(Path(tmp) / "split.png")
        contained = _still(src, CUT_FOCUS, 3.0, fit="contain")
        blurred = _still(src, CUT_FOCUS, 3.0,
                         presentation={"blur_fill": {"rect": {"x": 0, "y": 600,
                                                              "width": 1080,
                                                              "height": 608}}})
        assert qc_render.panel_blocks("unused.mp4", _plan([contained, blurred])) == []
        # and a plain blur_fill block too (shown whole over its blurred copy)
        plain = {"output": {"width": 1080, "height": 1920},
                 "blocks": [{"start": 0.0, "end": 2.0, "asset": blurred}]}
        assert qc_render.panel_blocks("unused.mp4", plain) == []


def test_a_cut_under_an_opaque_insert_is_not_judged():
    with tempfile.TemporaryDirectory() as tmp:
        src = _split_screen(Path(tmp) / "split.png")
        plan = _plan([_still(src, CLEAR_FOCUS, 3.0), _still(src, CUT_FOCUS, 3.0)])
        plan["blocks"][0]["insert"] = {"kind": "proof", "capture_path": str(src)}
        assert qc_render.panel_blocks("unused.mp4", plan) == []


def test_a_cut_fault_is_measured_apart_until_the_channel_has_it_judged():
    plain = {"index": 2, "at": 5.0, "visible": 0.24, "fault": True}
    cut = {"index": 4, "cut": 1, "at": 14.3, "visible": 0.24, "fault": True}
    clean = {"index": 4, "cut": 0, "at": 11.3, "visible": 1.0, "fault": False}
    rows = [plain, cut, clean]
    assert inset_panel.sequence_cuts_judged({}) is False
    assert qc_render.split_panel_faults(rows, {}) == ([plain], [cut])
    on = {"qc_thresholds": {inset_panel.SEQUENCE_KEY: True}}
    assert inset_panel.sequence_cuts_judged(on) is True
    assert qc_render.split_panel_faults(rows, on) == ([plain, cut], [])
    # only a real boolean switches it
    odd = {"qc_thresholds": {inset_panel.SEQUENCE_KEY: "yes"}}
    assert qc_render.split_panel_faults(rows, odd) == ([plain], [cut])


def test_the_score_never_sees_a_cut_fault_kept_apart():
    """score_log prices `panel_cut_blocks` only; the rows kept apart cost
    nothing (the channel has not had their price measured)."""
    import score_log
    cut = {"index": 0, "cut": 1, "at": 14.3, "visible": 0.24, "fault": True}
    plan = {"blocks": [{"start": 10.0, "end": 16.0, "asset": {"kind": "sequence"}}]}
    found = score_log.qc_findings({"measured": {"panel_cut_blocks": [],
                                                "panel_cut_sequence_blocks": [cut]},
                                   "failures": []}, plan)
    assert not [f for f in found if "panel" in str(f.get("note", ""))], found
    # the same row on the judged path is priced (the check above is not vacuous)
    priced = score_log.qc_findings({"measured": {"panel_cut_blocks": [cut]},
                                    "failures": []}, plan)
    assert [f for f in priced if "panel" in str(f.get("note", ""))], priced


def test_the_channel_config_carries_the_switch():
    import build_render_plan
    assert build_render_plan.panel_gate_thresholds(
        {"video_editor": {"panel_in_frame": {"mode": "warn",
                                             "sequence_cuts": True}}}) == {
            inset_panel.MODE_KEY: "warn", inset_panel.SEQUENCE_KEY: True}
    assert build_render_plan.panel_gate_thresholds(
        {"video_editor": {"panel_in_frame": {"sequence_cuts": "true"}}}) == {}


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

#!/usr/bin/env python3
"""CF-0740 L1: the card-text probe's frames reach Vision at most 720 px tall.

Accurate-mode OCR costs by the pixel; card-text was most of the Vision
service time of a CPU-pinned pass. What is pinned here is the shape of the
one ffmpeg call (stubbed - nothing is decoded): the scale comes after the
crop and after the picker, keeps the aspect, leaves a frame already at or
below the cap alone, and $FI_CARD_TEXT_MAX_H moves or lifts the cap for a
measurement run.
"""
import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage as ix  # noqa: E402
import indexer_cost  # noqa: E402


def _vf_of(bars="crop=1920:800:0:140", **kw):
    calls = []

    def rec(cmd, **k):
        calls.append(cmd)
        return None

    real = ix.runlog.run_child
    ix.runlog.run_child = rec
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ix.grab_span_samples("/pool/src.mp4", 4.0, 12.0, 12, bars, tmp, **kw)
    finally:
        ix.runlog.run_child = real
    assert len(calls) == 1, calls
    cmd = calls[0]
    return cmd, cmd[cmd.index("-vf") + 1]


def _with_env(value, fn):
    saved = os.environ.get(ix.CARD_TEXT_MAX_H_ENV)
    if value is None:
        os.environ.pop(ix.CARD_TEXT_MAX_H_ENV, None)
    else:
        os.environ[ix.CARD_TEXT_MAX_H_ENV] = value
    try:
        return fn()
    finally:
        if saved is None:
            os.environ.pop(ix.CARD_TEXT_MAX_H_ENV, None)
        else:
            os.environ[ix.CARD_TEXT_MAX_H_ENV] = saved


def test_default_cap_is_720_after_crop_and_picker():
    cmd, vf = _with_env(None, _vf_of)
    parts = vf.split(",select=")
    assert parts[0] == "crop=1920:800:0:140", vf
    # crop -> select -> scale: the bars come off at full size and only the
    # picked frames are scaled.
    assert vf.index("crop=") < vf.index("select=") < vf.index("scale="), vf
    assert vf.endswith("scale=w='if(gt(ih,720),-2,iw)':h='min(720,ih)'"), vf
    # Still one call, still read as the same op by the cost report.
    assert indexer_cost.op_of("ffmpeg", cmd, {}) == "shot-full-frame", cmd


def test_no_bars_still_scaled():
    _, vf = _with_env(None, lambda: _vf_of(bars=None))
    assert vf.startswith("select="), vf
    assert vf.endswith(",scale=w='if(gt(ih,720),-2,iw)':h='min(720,ih)'"), vf


def test_small_frames_are_left_alone():
    """At or below the cap the width stays iw and the height ih: ffmpeg's
    scale then passes the frame through unchanged."""
    f = ix.card_text_scale(720)
    assert "if(gt(ih,720),-2,iw)" in f and "min(720,ih)" in f, f
    # -2 (keep aspect, even width) only on the branch where ih > cap.
    assert f.index("-2") > f.index("gt(ih,720)"), f


def test_env_moves_or_lifts_the_cap():
    assert ix.card_text_max_height({}) == 720
    assert ix.card_text_max_height({"FI_CARD_TEXT_MAX_H": "540"}) == 540
    assert ix.card_text_max_height({"FI_CARD_TEXT_MAX_H": " 1080 "}) == 1080
    assert ix.card_text_max_height({"FI_CARD_TEXT_MAX_H": "0"}) is None
    assert ix.card_text_max_height({"FI_CARD_TEXT_MAX_H": "-5"}) is None
    assert ix.card_text_max_height({"FI_CARD_TEXT_MAX_H": "big"}) == 720
    assert ix.card_text_max_height({"FI_CARD_TEXT_MAX_H": ""}) == 720
    _, vf = _with_env("540", _vf_of)
    assert vf.endswith("scale=w='if(gt(ih,540),-2,iw)':h='min(540,ih)'"), vf
    # 0 = the full-resolution frames of before CF-0740 (the baseline run).
    _, vf = _with_env("0", _vf_of)
    assert "scale=" not in vf, vf
    assert vf.startswith("crop=1920:800:0:140,select="), vf


def test_explicit_argument_beats_env():
    _, vf = _with_env("540", lambda: _vf_of(max_height=None))
    assert "scale=" not in vf, vf
    _, vf = _with_env("0", lambda: _vf_of(max_height=360))
    assert vf.endswith("min(360,ih)'"), vf


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

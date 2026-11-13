#!/usr/bin/env python3
"""CF-0331: the card probe's frames come from ONE ffmpeg call per shot.

The per-frame `-ss` loop this replaced was 33.5 % of the whole indexing
stage's machine work (CF-0112) - 8 to 20 process starts a shot. The frames
themselves were proven identical pixel by pixel on real pool sources; what
this file pins is the shape of the call, because the cost is in the shape:
one process, the same (i + 0.5) / samples grid, the letterbox crop still in
front of the picker, a ceiling on the call (CF-0077), and a classification
`indexer_cost.py` still reads as `shot-full-frame` so the next measurement
is comparable with the last one.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage as ix  # noqa: E402
import indexer_cost  # noqa: E402


class Recorder:
    """Stands in for runlog.run_child: records the call, writes the frames
    ffmpeg would have written."""

    def __init__(self, frames_written):
        self.calls = []
        self.frames = frames_written

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        pattern = Path(cmd[-1])
        for i in range(self.frames):
            (pattern.parent / f"ct{i:02d}.png").write_bytes(b"")
        return None


def grab(tmp_path, *, start=10.0, duration=12.0, samples=12,
         bars="crop=1920:800:0:140", frames_written=None):
    rec = Recorder(frames_written if frames_written is not None else samples)
    real = ix.runlog.run_child
    ix.runlog.run_child = rec
    try:
        out = ix.grab_span_samples("/pool/src.mp4", start, duration, samples,
                                   bars, tmp_path)
    finally:
        ix.runlog.run_child = real
    return rec, out


def tmpdir():
    import tempfile
    return tempfile.TemporaryDirectory()


def test_one_call_per_shot():
    with tmpdir() as tmp:
        rec, frames = grab(tmp, samples=20)
        assert len(rec.calls) == 1, f"one ffmpeg a shot, not {len(rec.calls)}"
        assert len(frames) == 20, frames
        cmd, _ = rec.calls[0]
        assert cmd[cmd.index("-frames:v") + 1] == "20", cmd
        # The whole span is decoded once, not seeked to per frame.
        assert cmd.count("-ss") == 1 and cmd[cmd.index("-ss") + 1] == "10.0", cmd
        assert cmd[cmd.index("-t") + 1] == "12.0", cmd


def test_grid_is_the_probe_s_own():
    """(i + 0.5) / samples of the span, expressed absolutely."""
    with tmpdir() as tmp:
        rec, _ = grab(tmp, duration=12.0, samples=12)
        vf = rec.calls[0][0][rec.calls[0][0].index("-vf") + 1]
        assert "select='gte(t,(selected_n+0.5)*1.000000)'" in vf, vf
        # prev_selected_t would let each frame's own rounding move the next
        # threshold; the grid must not depend on where a frame landed.
        assert "prev_selected_t" not in vf, vf
    with tmpdir() as tmp:
        rec, _ = grab(tmp, duration=4.0, samples=8)
        vf = rec.calls[0][0][rec.calls[0][0].index("-vf") + 1]
        assert "*0.500000)" in vf, vf


def test_crop_comes_before_the_picker():
    with tmpdir() as tmp:
        rec, _ = grab(tmp, bars="crop=748:1080:586:0")
        vf = rec.calls[0][0][rec.calls[0][0].index("-vf") + 1]
        assert vf.startswith("crop=748:1080:586:0,select="), vf
    with tmpdir() as tmp:
        rec, _ = grab(tmp, bars=None)
        vf = rec.calls[0][0][rec.calls[0][0].index("-vf") + 1]
        assert vf.startswith("select="), vf


def test_the_call_is_bounded():
    """CF-0077: no unbounded child call."""
    with tmpdir() as tmp:
        rec, _ = grab(tmp)
        assert rec.calls[0][1].get("timeout") == ix.SPAN_GRAB_TIMEOUT_S, rec.calls[0][1]


def test_a_timeout_degrades_instead_of_crashing():
    """The loop swallowed a failed grab; so does this."""
    import subprocess

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    with tmpdir() as tmp:
        real = ix.runlog.run_child
        ix.runlog.run_child = boom
        try:
            frames = ix.grab_span_samples("/pool/src.mp4", 0.0, 3.0, 8, None, tmp)
        finally:
            ix.runlog.run_child = real
        assert frames == [], frames


def test_fewer_frames_than_asked_is_survivable():
    with tmpdir() as tmp:
        rec, frames = grab(tmp, samples=16, frames_written=9)
        assert len(frames) == 9, frames
        assert [p.name for p in frames] == sorted(p.name for p in frames)


def test_indexer_cost_still_calls_it_shot_full_frame():
    with tmpdir() as tmp:
        for bars in ("crop=1920:800:0:140", None):
            rec, _ = grab(tmp, bars=bars)
            cmd = rec.calls[0][0]
            assert indexer_cost.op_of("ffmpeg", cmd, {}) == "shot-full-frame", cmd
            rec.calls.clear()


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

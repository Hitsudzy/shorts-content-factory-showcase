#!/usr/bin/env python3
"""CF-0506: a hanging ffmpeg costs one shot's frame, not the source.

`usability_probe.extract_full_frames()` grabs one full-resolution frame per
shot, from `index_footage.py` (every indexed source) and
`remeasure_usability.py`. It used to call ffmpeg with no ceiling: one grab
wedged on a broken file and the stage waited forever, until a process-level
ceiling outside took the whole step down and lost every frame of the source.

Each grab now runs under `PROBE_FRAME_TIMEOUT_SECONDS` (Video Editor's
constant for one frame grab). A grab past it is that shot's frame not
extracted - None, the same verdict as a failed ffmpeg - and the shots after it
are still extracted.

The check runs a real child: a stand-in ffmpeg that writes the frame for every
shot except one, where it writes a partial file and then hangs for
HANG_SECONDS. The ceiling is lowered to TEST_CEILING_SECONDS for the run; the
letterbox probe (its own ffmpeg) is stubbed out.

CF-0649: the test ceiling is not on the edge. It applies to every grab, the
good ones too, and on a loaded machine (load 15-20) starting the stand-in shell
alone can cost more than a second - a 1 s ceiling killed shot 0's healthy grab
and the test went red for no fault of the code. The ceiling is now seconds
wide, and the time bound sits between it and the hang: a grab that is not
killed is waited on for HANG_SECONDS, past the bound, so "not killed" is still
caught.

No pytest dependency - plain asserts, run directly.
"""
import stat
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import usability_probe  # noqa: E402

HANGING_SHOT = 1
TEST_CEILING_SECONDS = 10   # per grab; a healthy grab under load stays far below
HANG_SECONDS = 120          # the hung grab, if nobody kills it
ELAPSED_BOUND_SECONDS = 60  # > ceiling + three healthy grabs, < HANG_SECONDS
FAKE_FFMPEG = """#!/bin/sh
for a; do out="$a"; done
case "$out" in
  *shot_%03d_full.png) printf partial > "$out"; exec sleep %d;;
esac
printf frame > "$out"
""" % (HANGING_SHOT, HANG_SECONDS)


def _extract_with_a_hanging_grab(tmp):
    fake = tmp / "ffmpeg"
    fake.write_text(FAKE_FFMPEG)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    out = tmp / "frames"
    out.mkdir()
    shots = [{"start": float(i * 2), "end": float(i * 2 + 2)} for i in range(4)]
    saved = (usability_probe.FFMPEG, usability_probe.PROBE_FRAME_TIMEOUT_SECONDS,
             usability_probe.detect_letterbox)
    usability_probe.FFMPEG = str(fake)
    usability_probe.PROBE_FRAME_TIMEOUT_SECONDS = TEST_CEILING_SECONDS
    usability_probe.detect_letterbox = lambda *a, **kw: None
    try:
        started = time.monotonic()
        frames = usability_probe.extract_full_frames(tmp / "source.mp4", shots, out)
        return frames, time.monotonic() - started
    finally:
        (usability_probe.FFMPEG, usability_probe.PROBE_FRAME_TIMEOUT_SECONDS,
         usability_probe.detect_letterbox) = saved


def test_a_hanging_grab_is_that_shots_frame_not_extracted():
    with tempfile.TemporaryDirectory() as tmp:
        frames, elapsed = _extract_with_a_hanging_grab(Path(tmp))
        assert elapsed < ELAPSED_BOUND_SECONDS, (
            f"the hanging grab was waited on for {elapsed:.1f}s")
        assert len(frames) == 4, frames
        assert frames[HANGING_SHOT] is None, (
            f"the hung grab should give no frame, got {frames[HANGING_SHOT]}")
        leftover = Path(tmp) / "frames" / f"shot_{HANGING_SHOT:03d}_full.png"
        assert not leftover.exists(), "the hung grab's partial file was left behind"
        for i, f in enumerate(frames):
            if i == HANGING_SHOT:
                continue
            assert f is not None and f.read_text() == "frame", (
                f"shot {i} after/before the hung one was not extracted: {f}")


def test_the_ceiling_is_the_one_frame_grab_constant():
    """The grab's ceiling is Video Editor's one-frame constant, not a second
    number for the same class of call."""
    import common  # on sys.path via usability_probe - Video Editor's scripts
    assert usability_probe.PROBE_FRAME_TIMEOUT_SECONDS is common.PROBE_FRAME_TIMEOUT_SECONDS
    assert 0 < common.PROBE_FRAME_TIMEOUT_SECONDS <= 120


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

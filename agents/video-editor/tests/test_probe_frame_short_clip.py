"""CF-0483: a clip probe that finds no frame refuses the clip, it does not
crash the plan.

example-film/2026-10-01T2210Z, spire-runner-fresh-dawn: build_render_plan.py
died with CalledProcessError on `ffmpeg -ss 0.5 -i .../a07_..._s020.mp4
-frames:v 1` - the clip had been deleted under the plan by a second,
concurrent plan_check_loop's resolve (ffprobe on it failed a moment before),
so media_duration() said 0.0 and the seek was not clamped. One bad clip took
the whole plan round down.

Pinned here: the seek stays inside a short clip (0.3 s), and an empty or
missing clip is an unusable asset with a failure line - the ordinary ASSETS
REJECTED path - never a traceback.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import build_render_plan as brp  # noqa: E402
import shot_score  # noqa: E402
from test_asset_tool_timeout import _silent_wav  # noqa: E402


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"ok: {msg}")


def _clip(path, seconds):
    subprocess.run([brp.FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=320x240:rate=30", "-t", str(seconds),
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=60)
    return path


def _assert_no_frame(info, source, reason):
    _check(info is not None, "a verdict, not None")
    qc = info["qc"]
    _check(qc["usable"] is False, "the clip is not usable")
    _check(qc["failed"] == [brp.NO_FRAME_KEY], f"failed keyed {brp.NO_FRAME_KEY!r}")
    line = qc["failures"][0]
    _check(str(source) in line and reason in line,
           f"failure line names the clip and {reason!r}: {line}")
    hard, soft = shot_score.split_verdict(qc)
    _check(hard and not soft, "a hard refusal, not a priced soft rule")
    _check(brp.probe_missing(info), "probe_missing() says there is no probe on disk")
    brp.framing(info)


def test_short_clip_is_probed_inside_its_length():
    with tempfile.TemporaryDirectory() as tmp:
        clip = _clip(Path(tmp) / "short.mp4", 0.3)
        dest = str(Path(tmp) / "f.png")
        info = brp.probe_frame(str(clip), brp.PROBE_OFFSET, dest, seconds=0.3)
        _check(info is None, "0.3 s clip with its length known: frame grabbed")
        _check(Path(dest).exists(), "the frame is on disk")


def test_short_clip_without_its_length_is_refused_not_crashed():
    with tempfile.TemporaryDirectory() as tmp:
        clip = _clip(Path(tmp) / "short.mp4", 0.3)
        dest = str(Path(tmp) / "f.png")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            info = brp.probe_frame(str(clip), 2.0, dest)
        _assert_no_frame(info, clip, "")
        _check("treated as a gate failure" in err.getvalue(), "stderr says so")


def test_empty_clip_is_refused_not_crashed():
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "empty.mp4"
        clip.write_bytes(b"")
        with contextlib.redirect_stderr(io.StringIO()):
            info = brp.probe_frame(str(clip), 0.5, str(Path(tmp) / "f.png"))
        _assert_no_frame(info, clip, "clip is empty")


def test_missing_clip_is_refused_not_crashed():
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "gone.mp4"
        with contextlib.redirect_stderr(io.StringIO()):
            info = brp.probe_frame(str(clip), 0.5, str(Path(tmp) / "f.png"),
                                   seconds=0.0)
        _assert_no_frame(info, clip, "clip not on disk")


def test_stale_probe_is_not_judged():
    """A probe left by an earlier pass must not stand in for a frame this
    pass failed to grab."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "f.png"
        dest.write_bytes(b"stale")
        with contextlib.redirect_stderr(io.StringIO()):
            info = brp.probe_frame(str(Path(tmp) / "gone.mp4"), 0.5, str(dest))
        _check(info is not None and not dest.exists(), "stale probe removed, clip refused")


def test_main_refuses_a_missing_clip_on_the_rejected_path():
    """End to end: the spire-runner shape - a clip block whose file is gone.
    main() exits 2 on ASSETS REJECTED with the no-frame line, no traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        clip = tmp / "clips" / "a07_gone_s020.mp4"
        words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
                  "end": round(0.9 + i * 0.5, 2)} for i in range(6)]
        (tmp / "words.json").write_text(json.dumps(words))
        story = {"script_id": "cf-0483", "style": "motion",
                 "blocks": [{"word_range": [0, 5], "intent": "a clip",
                             "asset_kind": "clip", "asset": str(clip),
                             "emphasis_words": []}]}
        (tmp / "storyboard.json").write_text(json.dumps(story))
        out = tmp / "plan.json"
        argv = sys.argv
        sys.argv = ["build_render_plan.py", str(tmp / "storyboard.json"),
                    str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
                    "--style", "motion", "--target-duration", "1", "60"]
        err = io.StringIO()
        code = None
        try:
            with contextlib.redirect_stderr(err):
                try:
                    brp.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = argv
        text = err.getvalue()
        _check(code == 2, f"main() exits 2 like any rejected asset - got {code!r}\n{text[-1500:]}")
        _check("ASSETS REJECTED - plan not written" in text, "the ordinary rejected listing")
        _check("no probe frame" in text, "the listing carries the no-frame line")
        _check("Traceback" not in text and "CalledProcessError" not in text, "no traceback")
        _check(not out.exists(), "plan.json was not written")


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

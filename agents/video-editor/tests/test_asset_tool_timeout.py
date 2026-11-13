#!/usr/bin/env python3
"""CF-0077: build_render_plan.py never waits on a gate tool without a ceiling.

qc_asset.py, smart_crop.py and the ffmpeg probe-frame grab each run under a
`timeout=` (common.ASSET_TOOL_TIMEOUT_SECONDS / PROBE_FRAME_TIMEOUT_SECONDS).
A tool that reaches it is killed and the asset is failed *by that gate*: the
same `rejected` path a dark frame takes - a failure line naming the tool, the
asset and the ceiling, `failed` keyed `tool_timeout`, stderr saying which
tool hung on what - and main() ends on the ordinary ASSETS REJECTED listing
(exit 2, plan not written), never a hang and never a traceback.

Synthetic: `subprocess.run` is replaced for the duration of each test with a
fake that raises TimeoutExpired for the one tool under test and passes
everything else (ffprobe on the voice, the real ffmpeg grab) through.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import build_render_plan as brp  # noqa: E402
from common import (ASSET_TOOL_TIMEOUT_SECONDS, PROBE_FRAME_TIMEOUT_SECONDS,  # noqa: E402
                    TOOL_TIMEOUT_KEY)

REAL_RUN = subprocess.run
USABLE_VERDICT = {"usable": True, "failures": [], "failed": [],
                  "relaxations": ["floor relaxed for the test"],
                  "short_side": 1080, "upscale_factor": 1.0}


def _cmd_has(cmd, needle):
    return any(needle in str(part) for part in cmd)


@contextlib.contextmanager
def hanging(tool, qc_verdict=None):
    """subprocess.run that times out on `tool` and passes the rest through.
    With `qc_verdict`, a qc_asset.py call returns that JSON instead of
    running (so smart_crop.py's timeout is tested behind a passing gate)."""
    seen = []

    def fake(cmd, *a, **kw):
        if _cmd_has(cmd, tool):
            seen.append(kw.get("timeout"))
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        if qc_verdict is not None and _cmd_has(cmd, "qc_asset.py"):
            seen.append(("qc", kw.get("timeout")))
            return subprocess.CompletedProcess(cmd, 0, json.dumps(qc_verdict), "")
        return REAL_RUN(cmd, *a, **kw)

    subprocess.run = fake
    try:
        yield seen
    finally:
        subprocess.run = REAL_RUN


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"ok: {msg}")


def _assert_timeout_verdict(info, tool, asset, ceiling):
    qc = info["qc"]
    _check(qc["usable"] is False, f"{tool}: asset is not usable")
    _check(qc["failed"] == [TOOL_TIMEOUT_KEY] or TOOL_TIMEOUT_KEY in qc["failed"],
           f"{tool}: failed is keyed {TOOL_TIMEOUT_KEY!r} - got {qc['failed']}")
    line = qc["failures"][-1]
    for needle in (tool, f"{ceiling} s ceiling", asset, "hung, not slow"):
        _check(needle in line, f"{tool}: failure line names {needle!r}")
    _check(info[TOOL_TIMEOUT_KEY] == {"tool": tool, "ceiling_seconds": ceiling},
           f"{tool}: info carries the tool and the ceiling")
    # framing(info) has to work on it - the block is built, then refused.
    brp.framing(info)
    print(f"ok: {tool}: framing() accepts the placeholder")


def test_qc_asset_timeout_is_a_gate_failure():
    err = io.StringIO()
    with hanging("qc_asset.py") as seen, contextlib.redirect_stderr(err):
        info = brp.inspect_asset("/x/frame.png", "9:16", 720, 0.8, 0.35)
    _check(seen == [ASSET_TOOL_TIMEOUT_SECONDS],
           f"qc_asset.py ran under timeout={ASSET_TOOL_TIMEOUT_SECONDS}")
    _assert_timeout_verdict(info, "qc_asset.py", "/x/frame.png", ASSET_TOOL_TIMEOUT_SECONDS)
    _check(f"qc_asset.py exceeded the ceiling of {ASSET_TOOL_TIMEOUT_SECONDS} s on /x/frame.png"
           in err.getvalue(), "stderr names the tool, the asset and the ceiling")
    _check("treated as a gate failure" in err.getvalue(), "stderr says it is a gate failure")


def test_smart_crop_timeout_keeps_the_qc_findings():
    err = io.StringIO()
    with hanging("smart_crop.py", qc_verdict=USABLE_VERDICT) as seen, \
            contextlib.redirect_stderr(err):
        info = brp.inspect_asset("/x/frame.png", "9:16", 720, 0.8, 0.35)
    _check(seen == [("qc", ASSET_TOOL_TIMEOUT_SECONDS), ASSET_TOOL_TIMEOUT_SECONDS],
           "both tools ran under the asset-tool ceiling")
    _assert_timeout_verdict(info, "smart_crop.py", "/x/frame.png", ASSET_TOOL_TIMEOUT_SECONDS)
    _check(info["qc"]["relaxations"] == USABLE_VERDICT["relaxations"],
           "qc_asset.py's relaxations survive a smart_crop.py timeout")
    _check("smart_crop.py exceeded the ceiling" in err.getvalue(), "stderr names smart_crop.py")


def test_probe_frame_timeout_fails_the_clip():
    err = io.StringIO()
    with hanging(brp.FFMPEG) as seen, contextlib.redirect_stderr(err):
        info = brp.probe_frame("/x/clip.mp4", 0.5, "/x/_probe_0.png")
    _check(seen == [PROBE_FRAME_TIMEOUT_SECONDS],
           f"ffmpeg ran under timeout={PROBE_FRAME_TIMEOUT_SECONDS}")
    _assert_timeout_verdict(info, "ffmpeg (probe frame)", "/x/clip.mp4",
                            PROBE_FRAME_TIMEOUT_SECONDS)


def test_probe_frame_ok_returns_none_and_writes_the_frame():
    """The happy path is untouched: a real grab off a real (synthesised) clip."""
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.mp4"
        REAL_RUN([brp.FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
                  "-i", "testsrc=size=320x240:rate=10", "-t", "1", str(clip)],
                 check=True, timeout=60)
        dest = str(Path(tmp) / "f.png")
        _check(brp.probe_frame(str(clip), 0.5, dest) is None, "probe_frame returns None")
        _check(Path(dest).exists(), "the frame was written")


def _silent_wav(path, seconds=4.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += int(2000 if (i // 40) % 2 else -2000).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def test_main_refuses_the_plan_on_the_ordinary_rejected_path():
    """End to end through main(): a still block whose qc_asset.py hangs ends
    on the ASSETS REJECTED listing with the timeout line - exit 2, plan not
    written, no traceback, and main() came back at all."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        still = tmp / "still.png"
        Image.new("RGB", (1920, 1080), (120, 140, 160)).save(still)
        words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
                  "end": round(0.9 + i * 0.5, 2)} for i in range(6)]
        (tmp / "words.json").write_text(json.dumps(words))
        story = {"script_id": "cf-0077", "style": "motion",
                 "blocks": [{"word_range": [0, 5], "intent": "a still",
                             "asset_kind": "still", "asset": str(still),
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
            with hanging("qc_asset.py"), contextlib.redirect_stderr(err):
                try:
                    brp.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = argv
        text = err.getvalue()
        _check(code == 2, f"main() exits 2 like any rejected asset - got {code!r}\n{text[-1500:]}")
        _check("ASSETS REJECTED - plan not written" in text, "the ordinary rejected listing")
        _check(f"block 0: {still}" in text, "the listing names the block and the asset")
        _check(f"- qc_asset.py: no verdict within the {ASSET_TOOL_TIMEOUT_SECONDS} s ceiling"
               in text, "the listing carries the timeout failure line")
        _check("Traceback" not in text, "no traceback")
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

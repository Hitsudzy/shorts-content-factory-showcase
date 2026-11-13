#!/usr/bin/env python3
"""CF-0649: a block pays for one gate process, not two.

qc_asset.py already computes the frame's smart_crop.analyse() (through the
warm Vision worker) to judge the subject; `--with-framing` hands that dict
back under `framing`, and build_render_plan.inspect_asset() takes it as the
framing instead of starting smart_crop.py to compute it again, cold. Before,
that second process was 219 s of a 25-block plan's 277 s under load.

What has to hold:
  * qc_asset.py is asked for the framing;
  * a verdict that carries it never starts smart_crop.py, and inspect_asset()
    returns exactly that dict with the verdict - minus `framing` - as `qc`;
  * a verdict without it (an older qc_asset.py, a stub) still runs
    smart_crop.py under its own ceiling, as CF-0077 has it;
  * qc_asset.py's `framing` is the frame's own analyse(), not the copy
    --window rewrites, and is absent unless asked for.

Synthetic: subprocess.run and qc_asset.analyse are stubbed, no Vision, no
worker, no real media. Plain asserts, run through tests/run_tests.py.
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
sys.path.insert(0, str(HERE))

import build_render_plan as brp  # noqa: E402
import qc_asset  # noqa: E402
from common import ASSET_TOOL_TIMEOUT_SECONDS  # noqa: E402

REAL_RUN = subprocess.run

FRAMING = {
    "image": "/x/frame.png",
    "source_size": {"width": 1920, "height": 1080},
    "roi_source": "faces", "single_subject": True,
    "roi": {"x": 800, "y": 300, "width": 300, "height": 400},
    "roi_parts": None,
    "crop": {"x": 646.0, "y": 0.0, "width": 607.5, "height": 1080.0},
    "roi_contained": True, "roi_coverage": 1.0, "zoom": 1.0,
}
VERDICT = {"usable": True, "failures": [], "failed": [], "relaxations": [],
           "short_side": 1080, "upscale_factor": 1.0}


@contextlib.contextmanager
def fake_tools(qc_out):
    """qc_asset.py answers `qc_out`; smart_crop.py answers FRAMING; every
    call is recorded as (tool, argv, timeout)."""
    seen = []

    def fake(cmd, *a, **kw):
        tool = next((t for t in ("qc_asset.py", "smart_crop.py")
                     if any(t in str(c) for c in cmd)), None)
        if tool is None:
            return REAL_RUN(cmd, *a, **kw)
        seen.append((tool, [str(c) for c in cmd], kw.get("timeout")))
        out = qc_out if tool == "qc_asset.py" else FRAMING
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    subprocess.run = fake
    try:
        yield seen
    finally:
        subprocess.run = REAL_RUN


def test_the_gate_is_asked_for_the_framing_and_smart_crop_does_not_run():
    with fake_tools({**VERDICT, "framing": FRAMING}) as seen:
        info = brp.inspect_asset("/x/frame.png", "1080:1920", 720, 0.8, 0.35)
    assert [s[0] for s in seen] == ["qc_asset.py"], seen
    assert "--with-framing" in seen[0][1], seen[0][1]
    assert seen[0][2] == ASSET_TOOL_TIMEOUT_SECONDS, seen[0][2]
    assert info == {**FRAMING, "qc": VERDICT}, info
    assert "framing" not in info["qc"], info["qc"]


def test_a_verdict_without_framing_still_runs_smart_crop():
    with fake_tools(dict(VERDICT)) as seen:
        info = brp.inspect_asset("/x/frame.png", "1080:1920", 720, 0.8, 0.35)
    assert [s[0] for s in seen] == ["qc_asset.py", "smart_crop.py"], seen
    assert seen[1][2] == ASSET_TOOL_TIMEOUT_SECONDS, seen[1][2]
    assert info == {**FRAMING, "qc": VERDICT}, info


def test_a_framing_without_a_roi_is_not_taken():
    with fake_tools({**VERDICT, "framing": {"error": "x"}}) as seen:
        info = brp.inspect_asset("/x/frame.png", "1080:1920", 720, 0.8, 0.35)
    assert [s[0] for s in seen] == ["qc_asset.py", "smart_crop.py"], seen
    assert info == {**FRAMING, "qc": VERDICT}, info


def _qc_main(image, *extra):
    """qc_asset.main() in process on a real (synthetic) image, with the
    Vision call stubbed to FRAMING. Returns the --json verdict."""
    real = qc_asset.analyse
    qc_asset.analyse = lambda path, aspect: json.loads(json.dumps(
        {**FRAMING, "image": path}))
    argv, out = sys.argv, io.StringIO()
    sys.argv = ["qc_asset.py", image, "--aspect", "1080:1920", "--json", *extra]
    try:
        with contextlib.redirect_stdout(out):
            try:
                qc_asset.main()
            except SystemExit:
                pass
    finally:
        sys.argv, qc_asset.analyse = argv, real
    return json.loads(out.getvalue())


def test_qc_asset_emits_the_frames_own_analyse_only_when_asked():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        image = str(Path(tmp) / "f.png")
        Image.new("RGB", (1920, 1080), (120, 90, 60)).save(image)
        plain = _qc_main(image)
        asked = _qc_main(image, "--with-framing")
        windowed = _qc_main(image, "--with-framing", "--window", "0.1,0.5",
                            "--window-zoom", "1.0")
    assert "framing" not in plain, sorted(plain)
    assert asked["framing"] == {**FRAMING, "image": image}, asked["framing"]
    framing = asked.pop("framing")
    assert asked == plain, "the verdict itself does not change"
    # --window rewrites the coverage the verdict is judged on; `framing` is
    # still the frame's own analyse(), what smart_crop.py would print.
    assert windowed["framing"] == framing, windowed["framing"]
    assert "coverage_window" not in windowed["framing"]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")
             and callable(v) and v.__module__ == __name__]
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

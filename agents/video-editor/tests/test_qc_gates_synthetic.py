#!/usr/bin/env python3
"""CF-0024: prove each QC gate can actually reject something, not just accept
good input. 1.1's caption-legibility gate shipped with its threshold set below
the metric's own floor - it could never fail, and nothing caught that until a
human noticed. These are the cheap synthetic-bad-input checks that would have.

No pytest dependency (not installed in this venv) - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from repo_paths import VENV_PY  # noqa: E402 - CF-0125: resolved against the main checkout
FFMPEG = "/usr/local/opt/ffmpeg-full/bin/ffmpeg"


def test_qc_asset_rejects_solid_black_image():
    """No subject, all dead pixels, unreadable - should fail on at least the
    dead-pixel and subject checks, ideally without needing a real photo."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "black.png"
        Image.new("RGB", (1920, 1080), (0, 0, 0)).save(img)
        out = subprocess.run(
            [VENV_PY, str(SCRIPTS / "qc_asset.py"), str(img), "--json"],
            capture_output=True, text=True)
        assert out.returncode == 1, (
            f"qc_asset.py accepted a solid black frame (exit {out.returncode}) - "
            f"the gate cannot fail, which is exactly how 1.1's caption gate shipped broken.\n"
            f"stdout: {out.stdout}\nstderr: {out.stderr}")


def test_qc_asset_rejects_below_resolution_floor():
    """A tiny, otherwise-plausible image should fail the resolution floor
    even if it somehow clears everything else."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "tiny.png"
        # Mid-grey with a bit of noise, so this fails on resolution specifically,
        # not by accident on the black/luma checks too.
        import random
        px = Image.new("RGB", (200, 120))
        random.seed(0)
        px.putdata([(random.randint(80, 180),) * 3 for _ in range(200 * 120)])
        px.save(img)
        out = subprocess.run(
            [VENV_PY, str(SCRIPTS / "qc_asset.py"), str(img), "--json"],
            capture_output=True, text=True)
        assert out.returncode == 1, (
            f"qc_asset.py accepted a 200x120 frame - resolution floor cannot fail.\n"
            f"stdout: {out.stdout}\nstderr: {out.stderr}")


def test_qc_render_blackdetect_finds_a_synthetic_black_run():
    """qc_render.py's frame-level black check is ffmpeg's blackdetect filter
    wrapped in detect(). Feed it a video that is genuinely all black and
    confirm the wrapper actually parses a hit out of ffmpeg's stderr - this
    is regex-against-ffmpeg-output, exactly the kind of thing that silently
    stops matching after an ffmpeg version bump. Filter string and pattern
    copied verbatim from qc_render.py's real call site, not reinvented, so a
    drift there breaks this test too instead of testing something else."""
    sys.path.insert(0, str(SCRIPTS))
    import qc_render
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "black.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
             "-i", "color=c=black:s=320x180:d=2", "-frames:v", "60", str(video)],
            capture_output=True, check=True)
        hits = qc_render.detect(str(video), "blackdetect=d=0.1:pix_th=0.10")
        assert hits, "blackdetect found no black run in a 2s all-black synthetic clip"
        # CF-0141: and the *position* comes back too, not only the duration -
        # without it the gate cannot tell a run in the body of the video from
        # one inside the channel's ending clip.
        run = hits[0]
        assert set(run) == {"start", "end", "duration"}, run
        assert run["start"] < 0.1 and run["duration"] > 1.5, run
        assert abs((run["end"] - run["start"]) - run["duration"]) < 0.05, run


def test_qc_render_silencedetect_finds_synthetic_silence():
    """Same idea, for the silence-detection side - filter and pattern copied
    verbatim from qc_render.py's real call site."""
    sys.path.insert(0, str(SCRIPTS))
    import qc_render
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "silence.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
             "-i", "anullsrc=r=44100:cl=mono", "-t", "2", str(audio)],
            capture_output=True, check=True)
        hits = qc_render.detect(str(audio), "silencedetect=n=-45dB:d=1.0")
        assert hits, "silencedetect found no silence in a 2s synthetic silent clip"
        run = hits[0]
        assert set(run) == {"start", "end", "duration"}, run
        assert run["start"] < 0.1 and run["duration"] > 1.5, run
        # CF-0141: one parser now, so this and the black run above cannot
        # come to disagree about what a run is.
        assert qc_render.silence_runs(str(audio)) == hits


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

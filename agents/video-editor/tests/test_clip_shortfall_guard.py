#!/usr/bin/env python3
"""CF-0131: a clip block that outruns its own clip never reaches the renderer.

The defect is from the CF-0052 demo render. Block 2 (raygun) held a 1.30s clip
over a 31.6s block: roughly 948 `OffthreadVideo` frames past the end of the
file, about 250s of a 29-minute render, every one of them decoding and drawing
the same held last frame. `qc_render.py`'s `frozen_blocks()` did catch it -
afterwards, as `frozen_clip_blocks` with the reason "playback ran out" - but
`build_render_plan.py` wrote that plan and sent it to render anyway. The most
expensive class of frame in the pipeline was being spent on a defect that was
already decided at plan time.

The whole point of these tests is that the planner's threshold is *not a new
number*. `common.clip_shortfall()` is `freeze_verdict()`'s own condition -
every probe qc_render.py would take is already on the held last frame - lifted
into common.py so both stages call it instead of restating it. A second,
slightly different threshold on the planning side would be worse than none:
the planner would be degrading blocks the gate accepts, or waving through
blocks the gate fails, and neither side would be wrong on its own terms.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import common  # noqa: E402
import qc_render  # noqa: E402
import build_render_plan  # noqa: E402
from common import FFMPEG  # noqa: E402


def _clip(path, seconds):
    """A moving 9:16 clip of exactly `seconds`. testsrc moves everywhere, so a
    probe that lands on real footage can never read as held footage - which is
    what makes the agreement test below about playback running out and nothing
    else."""
    subprocess.run(
        [FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=1080x1920:rate=25",
         "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _block(start, end, src, start_seconds=0):
    return {"start": start, "end": end,
            "asset": {"kind": "clip", "src": src, "start_seconds": start_seconds}}


# --------------------------------------------------------------------------
# One threshold, structurally
# --------------------------------------------------------------------------

def test_planner_and_gate_share_the_one_definition():
    """Not a value comparison - an identity one. Two modules agreeing on a
    number today is how they come to disagree on it later; these are the same
    objects, so a change to the freeze geometry cannot reach one stage without
    reaching the other."""
    assert qc_render.source_time is common.source_time
    assert qc_render.probe_exhausted is common.probe_exhausted
    assert qc_render.PROBE_FRACTIONS is common.PROBE_FRACTIONS
    assert qc_render.PROBE_GAP == common.PROBE_GAP
    assert qc_render.RENDER_CROSSFADE == common.RENDER_CROSSFADE
    assert qc_render.CLIP_TAIL_TOLERANCE == common.CLIP_TAIL_TOLERANCE
    assert qc_render.LAST_FRAME_EPSILON == common.LAST_FRAME_EPSILON
    assert build_render_plan.clip_shortfall is common.clip_shortfall


def test_shortfall_is_exactly_what_freeze_verdict_faults_on():
    """The agreement test. For each block, ask the planner's question
    (`clip_shortfall`) and the gate's question (`freeze_verdict`, given the
    probe times `frozen_blocks()` would hand it) about the same clip, and
    require the same answer every time.

    `freeze_verdict` can also fault a block for a second reason - the source
    moves where the render does not - which is a fact about the render and
    nothing the planner can know. So the claim under test is specifically
    about its playback-ran-out verdict, which is a fact about the plan."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        short = _clip(tmp / "short.mp4", 1.0)
        long = _clip(tmp / "long.mp4", 3.0)
        cases = [
            # (block, clip, what it is)
            (_block(1.2, 6.0, short), "CF-0052's shape: a 4.8s block on a 1s clip"),
            (_block(0.0, 1.2, long), "an ordinary block well inside its clip"),
            (_block(5.0, 8.0, long), "a block that outruns its clip by a second - "
                                     "the crossfade tail every clip block has"),
            (_block(5.0, 9.0, long), "further over, still with a live first probe"),
            (_block(5.0, 20.0, long), "far past the end of a clip that is not short"),
            (_block(5.0, 9.0, long, start_seconds=2.5), "trimmed most of the way "
                                                        "into its own clip"),
            (_block(2.0, 2.3, short), "too short to be probed at all"),
        ]
        for n, (block, what) in enumerate(cases):
            clip_seconds = common.media_duration(block["asset"]["src"])
            shortfall = common.clip_shortfall(block, clip_seconds)
            times = common.probe_times(block)
            if not times:
                # No probe, no verdict: frozen_blocks() collects no motion for
                # such a block and skips it before freeze_verdict() is reached,
                # so the planner must not judge it either.
                assert shortfall is None, f"{what}: judged a block QC never probes"
                continue
            fault, reason, _ = qc_render.freeze_verdict(block, times, str(tmp),
                                                        f"case{n}")
            ran_out = fault and "playback ran out" in reason
            assert (shortfall is not None) == ran_out, (
                f"{what}: planner says shortfall={shortfall}, the gate says "
                f"{'ran out' if ran_out else reason!r} - the two stages are "
                f"using different thresholds for the same defect")
            if ran_out:
                # The number the planner reports is the same overrun the gate
                # names in its own reason line.
                assert abs((shortfall + clip_seconds)
                           - common.source_time(block, block["end"])) < 1e-6


def test_a_clip_block_may_outrun_its_clip_a_little():
    """Explicitly, because it is the rule most likely to be "tightened" by
    someone reading only the task title. Every clip block ends past the end of
    its clip by design - Video.jsx mounts the Sequence RENDER_CROSSFADE early
    and runs it to the block's end - and `qc_render.py` accepts that. A
    planner that degraded on "block longer than clip" would drop a rung on
    ordinary, correct blocks."""
    block = _block(5.0, 8.0, "/nowhere.mp4")   # 3s block
    assert common.clip_shortfall(block, 2.0) is None, (
        "a block one second longer than its clip is the normal crossfade tail")
    assert common.clip_shortfall(block, 0.6) is not None, (
        "a block five times longer than its clip is the CF-0131 defect")


def test_an_unreadable_clip_is_not_degraded_on_a_guess():
    """media_duration() answers 0.0 for a file ffprobe cannot read. That is
    "unknown", not "zero seconds long", and degrading on it would silently
    drop a rung for every clip on a machine with a broken ffprobe. The asset
    gate refuses unreadable footage on its own."""
    assert common.clip_shortfall(_block(1.2, 6.0, "/nowhere.mp4"), 0.0) is None


# --------------------------------------------------------------------------
# End to end through the real planner
# --------------------------------------------------------------------------

def _silent_wav(path, seconds=6.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = 2000 if (i // 40) % 2 else -2000
            frames += int(v).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def test_build_render_plan_degrades_the_starved_block_and_only_that_one():
    """The whole path, through the real script: two clip blocks, one of them
    the CF-0052 shape. It comes out a still, with the shortfall written into
    `degraded_blocks` where write_batch_metadata.py already reports it - and
    the block beside it, which has footage to spare, is untouched. CF-0031's
    rule holds: a degradation is per-block, never a style change."""
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        (tmp / "words.json").write_text(json.dumps(
            [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]))
        fed = _clip(tmp / "fed.mp4", 3.0)
        starved = _clip(tmp / "starved.mp4", 1.0)

        def sb(shot, asset, start, end):
            return {"word_range": [0, 0], "intent": "clip", "asset_kind": "clip",
                    "asset": asset, "emphasis_words": [], "rhythm_role": "beat",
                    "side": None, "shot": shot, "held_frame": False,
                    "_start": start, "_end": end}

        (tmp / "storyboard.json").write_text(json.dumps({
            "script_id": "cf-0131", "style": "motion",
            "resolved_from_anchors": True,
            "rhythm": {"pattern_requested": "explainer",
                       "rhythm_requested": "staccato", "rhythm_built": "staccato",
                       "parameters": {"block_count": 2,
                                      "key_frame_hold_seconds": 1.4},
                       "opening_requested": None, "opening_delivered": None,
                       "anchor_count": 2},
            # Block 1 runs to the end of the voice (6.0s) on a 1.0s clip - the
            # CF-0052 shape, scaled down.
            "blocks": [sb("fed:1", fed, 0.0, 1.2),
                       sb("starved:1", starved, 1.2, 6.0)],
            "unresolved_anchors": [], "rejected_candidates": [],
        }))
        out = tmp / "plan.json"
        result = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "motion", "--target-duration", "1", "60"],
            capture_output=True, text=True, cwd=tmp)
        assert result.returncode == 0, result.stderr[-3000:]
        plan = json.loads(out.read_text())

        kinds = [b["asset"]["kind"] for b in plan["blocks"]]
        assert kinds == ["clip", "still"], (
            f"expected the starved block alone to drop a rung, got {kinds}")
        assert plan["style"] == "motion", "a per-block drop is not a style change"

        degraded = plan["degraded_blocks"]
        assert [d["index"] for d in degraded] == [1], degraded
        assert degraded[0]["from"] == "clip" and degraded[0]["to"] == "still", degraded
        # The record has to carry the shortfall itself, not just the fact of a
        # drop: "why is this block a still" is the question a later reader asks.
        assert "1.00s" in degraded[0]["reason"] and "5.15s" in degraded[0]["reason"], \
            degraded[0]["reason"]
        assert "CF-0131" in degraded[0]["reason"], degraded[0]["reason"]

        # The still it degraded to is a frame of that block's own clip, on
        # disk - CF-0121's one-sample-one-use holds because the sample went
        # from moving to motionless in the place it was already going to be.
        src = Path(plan["blocks"][1]["asset"]["src"])
        assert src.name == "_degraded_still_1.png", src
        assert src.exists() and src.stat().st_size > 0, src
        # And the block it did not touch still plays its footage.
        assert plan["blocks"][0]["asset"]["src"] == fed


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

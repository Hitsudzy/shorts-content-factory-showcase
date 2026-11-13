#!/usr/bin/env python3
"""CF-0249: a block that is alive for its first half and frozen for its second.

Found by the user on review of batch example-film/2026-09-15T1034Z: "dtf-st-louis
has a frozen frame from second 4 to second 9". The video had passed QC. Block 0
spans 0.0-9.4s and its clip runs 4.03s, so the render holds the clip's last
frame for 5.37s - and `frozen_blocks()` did not see it, because it asked
`max(motions) >= MIN_BLOCK_MOTION` over three probes and the probe at 25% of
the block landed on real footage.

The rule the gate asks now is the *length of the longest motionless stretch*
(`common.MAX_HELD_RUN`, 1.8s). What these tests hold in place:

  * the half-frozen block is caught, and is described by how long it was stuck
    rather than by a block-wide average that was never true of it;
  * the hold that is ordinary in real footage is not caught. Measured with the
    gate's own definition of motion, the 58 clips of that batch - every shot
    the detector and the source gate let through - hold still for at most 1.2s,
    and CF-0004's canonical held pose (Wile E. Coyote on rocket skates,
    H-43VeYGiPM) is 1.2s. 1.8s is above that population and 3x under the 5.37s
    defect; a test here pins the gap from the "still ordinary" side;
  * CF-0004's `max()` is still in place and still failing what it failed - a
    block that never moves anywhere is a still whatever its length;
  * the sweep measures what pair_motion() measures. One definition of motion,
    sampled continuously instead of at three points.

Videos are synthesized with ffmpeg's `tpad=stop_mode=clone`, which repeats the
last frame - the exact pixel signature of the renderer holding a clip past its
end, produced without a Remotion render.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import common  # noqa: E402
import qc_render  # noqa: E402
import build_render_plan  # noqa: E402
from common import FFMPEG  # noqa: E402

SIZE = "540x960"
RATE = 25


def _ffmpeg(*args):
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", *args], check=True)


def _moving(path, seconds):
    """A clip that moves everywhere, of exactly `seconds`."""
    _ffmpeg("-f", "lavfi",
            "-i", f"testsrc2=duration={seconds}:size={SIZE}:rate={RATE}",
            "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _moving_then_frozen(path, moving_seconds, frozen_seconds):
    """`moving_seconds` of real motion, then the last frame held - what the
    renderer produces when a block outruns its clip."""
    _ffmpeg("-f", "lavfi",
            "-i", f"testsrc2=duration={moving_seconds}:size={SIZE}:rate={RATE}",
            "-vf", f"tpad=stop_mode=clone:stop_duration={frozen_seconds}",
            "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _hold_in_the_middle(path, before, hold, after):
    """Motion, a hold of exactly `hold` seconds, then motion again - a locked
    -off beat inside a live shot, which is CF-0004's class and must not fail."""
    _ffmpeg("-f", "lavfi",
            "-i", f"testsrc2=duration={before + after}:size={SIZE}:rate={RATE}",
            "-filter_complex",
            f"[0:v]trim=0:{before},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={hold}[a];"
            f"[0:v]trim={before}:{before + after},setpts=PTS-STARTPTS[b];"
            f"[a][b]concat=n=2:v=1[out]",
            "-map", "[out]", "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _plan(blocks):
    return {"blocks": blocks}


def _block(start, end, src, start_seconds=0):
    return {"start": start, "end": end,
            "asset": {"kind": "clip", "src": src, "start_seconds": start_seconds}}


# --------------------------------------------------------------------------
# One threshold, structurally (the shape test_clip_shortfall_guard.py uses)
# --------------------------------------------------------------------------

def test_both_stages_fail_a_freeze_by_the_same_number():
    """The gate's threshold and the planner's are the same object, so the
    render-time rule and the plan-time rule cannot drift apart."""
    assert qc_render.MAX_HELD_RUN is common.MAX_HELD_RUN
    assert build_render_plan.held_tail is common.held_tail
    # And it is a stretch of held picture, not a block-wide aggregate: it has
    # to sit above what real cut footage holds (1.2s measured) and under the
    # shortest block the pattern band allows (4.0s), or a freeze covering half
    # a legal block would pass.
    assert 1.2 < common.MAX_HELD_RUN < 4.0


# --------------------------------------------------------------------------
# The render gate
# --------------------------------------------------------------------------

def test_the_half_frozen_block_is_caught():
    """dtf-st-louis block 0, to scale: a 9.4s block on a 4.03s clip. Live for
    the first 43% of its length, held for the other 57%, which is precisely
    the shape `max(motions)` cannot see."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clip = _moving(tmp / "clip.mp4", 4.0)
        video = _moving_then_frozen(tmp / "render.mp4", 4.0, 5.4)

        records = qc_render.frozen_blocks(video, _plan([_block(0.0, 9.4, clip)]))
        assert len(records) == 1, f"the half-frozen block was not caught: {records}"
        r = records[0]
        assert r["fault"], r
        # Named by the mechanism, because the mechanism is knowable: the block
        # asks for more seconds of footage than the file holds.
        assert "playback ran out" in r["reason"], r["reason"]
        # Described by how long it was stuck, near enough the 5.4s of held
        # frame that is really there (the sweep's windows are PROBE_GAP wide
        # and the first still window has to be wholly inside the freeze).
        assert r["still_run"] >= 4.5, r
        assert abs(r["still_run_at"] - 4.0) <= 0.6, r
        assert r["motion"] < qc_render.MIN_BLOCK_MOTION, r


def test_a_block_that_moves_throughout_is_not_touched():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clip = _moving(tmp / "clip.mp4", 10.0)
        assert qc_render.frozen_blocks(clip, _plan([_block(0.0, 9.5, clip)])) == []


def test_a_hold_of_the_length_real_footage_holds_is_not_a_fault():
    """The CF-0004 protection, restated for the new rule. A 1.2s hold is the
    longest this pipeline's own cut clips produce, and the longest hold in the
    trailer CF-0004 was written about; the gate must not fire on it - and must
    not even ask the source about it, because that is a second look this block
    never needed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        video = _hold_in_the_middle(tmp / "render.mp4", 4.0, 1.2, 4.0)
        records = qc_render.frozen_blocks(video, _plan([_block(0.0, 9.0, video)]))
        assert records == [], f"a 1.2s hold was treated as a freeze: {records}"


def test_a_block_that_never_moves_is_still_a_still():
    """CF-0004's max() is not weakened by any of this. A block with no motion
    anywhere in it is a still, whatever its length - here well under
    MAX_HELD_RUN, so only the old rule can catch it."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clip = _moving(tmp / "clip.mp4", 3.0)
        video = _moving_then_frozen(tmp / "render.mp4", 0.04, 3.0)
        records = qc_render.frozen_blocks(video, _plan([_block(1.5, 3.0, clip)]))
        assert len(records) == 1, f"a motionless block was not reported: {records}"
        assert records[0]["still_run"] < common.MAX_HELD_RUN, records[0]
        # It moves in the clip and not in the render, so it is a fault, and
        # the reason says which of freeze_verdict()'s three answers it is.
        assert records[0]["fault"] and "source clip moves" in records[0]["reason"], \
            records[0]


# --------------------------------------------------------------------------
# The plan stage: the same defect, named before anything is rendered
# --------------------------------------------------------------------------

def test_the_plan_stage_names_dtf_st_louis_block_0():
    """The real numbers of the block the user caught. Nothing here is a
    picture measurement: a block's span and its clip's duration are both in
    hand while the plan is being written, and 9.40 - 4.03 is the 5.37s of held
    frame the viewer saw. The rule CF-0131 left in place says nothing about
    it, which is the whole gap this closes."""
    block = _block(0.0, 9.4, "/dtf/a00_dPmklyud1P8_s001.mp4")
    assert common.clip_shortfall(block, 4.03) is None, (
        "the CF-0131 rule is 'every probe is on the held frame' and this block "
        "has four live seconds - if this starts answering, the test below is "
        "measuring the wrong thing")
    assert common.held_tail(block, 4.03) == 5.37


def test_the_crossfade_tail_every_clip_block_has_is_still_allowed():
    """The rule most likely to be over-tightened by someone reading only the
    task title (test_clip_shortfall_guard.py makes the same point about the
    CF-0131 rule). Video.jsx mounts every Sequence RENDER_CROSSFADE early, so
    a correct clip block outruns its clip by 0.35s and QC accepts it."""
    block = _block(5.0, 8.0, "/nowhere.mp4")        # 3s block, 3.35s of footage
    assert common.held_tail(block, 3.35) is None, "an exactly fed block"
    assert common.held_tail(block, 3.0) is None, (
        "0.35s of held tail is the crossfade lead, not a freeze")
    assert common.held_tail(block, 1.5) == 1.85, "past MAX_HELD_RUN, and by how much"
    # "Unknown duration" is not "zero seconds long" - same reasoning as
    # clip_shortfall()'s, and the same trap: ffprobe answering 0.0 on one
    # machine would otherwise degrade every clip block in the plan.
    assert common.held_tail(block, 0.0) is None


def _silent_wav(path, seconds=6.0, rate=16000):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = 2000 if (i // 40) % 2 else -2000
            frames += int(v).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def test_build_render_plan_degrades_the_half_starved_block_before_the_render():
    """End to end through the real planner, with dtf-st-louis's shape scaled
    down: a 4.8s block on a 2.6s clip. Its first probe lands on live footage,
    so the CF-0131 guard passes it - and it still holds a frozen frame for
    2.55s, which is what comes out as a still here instead of as minutes of
    render and a QC failure afterwards."""
    import json
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        (tmp / "words.json").write_text(json.dumps(
            [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]))
        fed = _moving(tmp / "fed.mp4", 3.0)
        half = _moving(tmp / "half.mp4", 2.6)

        def sb(shot, asset, start, end):
            return {"word_range": [0, 0], "intent": "clip", "asset_kind": "clip",
                    "asset": asset, "emphasis_words": [], "rhythm_role": "beat",
                    "side": None, "shot": shot, "held_frame": False,
                    "_start": start, "_end": end}

        (tmp / "storyboard.json").write_text(json.dumps({
            "script_id": "cf-0249", "style": "motion",
            "resolved_from_anchors": True,
            "rhythm": {"pattern_requested": "explainer",
                       "rhythm_requested": "staccato", "rhythm_built": "staccato",
                       "parameters": {"block_count": 2,
                                      "key_frame_hold_seconds": 1.4},
                       "opening_requested": None, "opening_delivered": None,
                       "anchor_count": 2},
            "blocks": [sb("fed:1", fed, 0.0, 1.2),
                       sb("half:1", half, 1.2, 6.0)],
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
            f"expected the half-starved block alone to drop a rung, got {kinds}")
        assert plan["style"] == "motion", "a per-block drop is not a style change"
        degraded = [d for d in plan["degraded_blocks"] if d["index"] == 1]
        assert degraded, plan["degraded_blocks"]
        # The reason carries the measurement and the task, so a later reader
        # is not left with "this block is a still because someone said so".
        assert "2.55s" in degraded[0]["reason"], degraded[0]["reason"]
        assert "CF-0249" in degraded[0]["reason"], degraded[0]["reason"]


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

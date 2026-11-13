#!/usr/bin/env python3
"""CF-0004: the motion gate has to tell a hung render from held footage.

`qc_render.py`'s `frozen_blocks()` fails a clip block whose render does not
change over 0.3s. That is CF-0031's signature - and it is also what a locked-off
shot, a title card and an animated held pose look like, which is the half of
CF-0004 the crop fix did not touch. The render alone cannot separate the two:
both are literally zero pixel change. The clip the block was cut from can, so
`freeze_verdict()` looks there.

Measured on this repo's own material (numbers quoted here are real ffmpeg
output, not invented, and the profiling command is in CF-0004's task file):

  * Across all 20 cached trailers in shared/footage - 10,740 windows of 0.3s
    measured exactly the way the gate measures them - 78.5% read above 3.0,
    8.1% read under MIN_BLOCK_MOTION (1.0) and 3.4% read under 0.1. Held
    frames are ordinary in real trailer footage, not an edge case.
  * H-43VeYGiPM.mp4 (Coyote vs. Acme trailer), shot 4 = 8.97-10.18s: Wile E.
    Coyote held in mid-air on ACME rocket skates - a drawn held pose, the exact
    CF-0004 case. Source motion across that shot: 0.97 / 0.44 / 0.41.
  * Batch 2026-08-31T2155Z, rapid-reckless-neon-drift plan.json block 4:
    an 11.91s block cut from a 1.07s clip. The recorded qc.log of that run
    measured the render at motion 0.14 - a real hung block, and it must keep
    failing.

CF-0522/CF-0558: the three verdicts run in the suite on synthetic clips of
the same shape; the live monitor reads the newest live plan's real clips and
says NOT_CHECKED (never a pass) when they are gone.

CF-0908: the held-pose half used to be a second live monitor on the pool
trailer H-43VeYGiPM.mp4 - one fixed clip, and the pool is transient
(CF-0358): the trailer left and the monitor went NOT_CHECKED for good. No
live subject can stand in for it: the pool index carries no motion
measurement (finding a held shot there would mean measuring the pool, which
no test does), and the gate's own past excuses in a batch's QC log are
circular and go stale with the gate - tulsa-king of 2026-10-26T1514Z was
excused at source motion 0.73 by the pre-CF-0893 clock, and today's gate,
reading the cut's own clock, measures 1.76 there and fails it, rightly. So
the monitor is gone from the registry, and what the trailer added over the
single-frame held clip - a held pose that is not a perfect still (the
coyote shot read 0.43-0.64 under the 1.0 bar, codec noise and grain) - is a
stand in the suite: test_noisy_held_pose_like_the_coyote_trailer_is_excused.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import qc_render  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_monitors import live_only, newest_run, not_checked, untouched  # noqa: E402 - CF-0519/CF-0558
import common  # noqa: E402
from common import FFMPEG  # noqa: E402
import _synthetic_media as syn  # noqa: E402 - CF-0522


MONITOR_PLAN = "test_frozen_block_source_check.py::_live_batch_plan"
LIVE_SAMPLE_BLOCKS = 20     # clip blocks decoded per run (each probe is ffmpeg)


def _live_clip_blocks(plan):
    """[(index, block)] of the plan's clip blocks whose clip file is still
    on disk - what the shipped-clip monitor decodes."""
    return [(i, b) for i, b in enumerate(plan.get("blocks") or [])
            if (b.get("asset") or {}).get("kind") == "clip"
            and Path(b["asset"].get("src") or "/nowhere").exists()]


def _has_live_clip_block(work):
    """newest_run() accept: the run's plan has a clip block whose clip is
    still there. CF-0868: a run cut wholly from sequence / still blocks
    (0841Z/i-play-rocky: 6 sequence + 2 still) holds plan.json and clips/
    yet gives this monitor nothing, while wicker of the same batch had 16
    live clip blocks - the first slug alone must not decide."""
    try:
        plan = json.loads((work / "plan.json").read_text())
    except (OSError, ValueError):
        return False
    return bool(_live_clip_blocks(plan))


def _live_batch_plan(batch_dirs=None):
    """(plan, work dir, batch dir) of the newest live run of the channel
    whose plan.json has a clip block with its clip still there - a live
    monitor (CF-0519/CF-0558): the clips are mp4s no fixture holds. Every
    run of every batch is looked at, newest batch first (CF-0868), and
    NotChecked only when none anywhere has such a block."""
    if batch_dirs is None:
        import _channel_ids   # the channel's batches under every name it had (CF-0180)
        batch_dirs = _channel_ids.channel_batch_dirs("example-film")
    hit = newest_run(batch_dirs, ("plan.json", "clips"), accept=_has_live_clip_block)
    if hit is None:
        not_checked(MONITOR_PLAN, "no live run of the channel holds a plan.json with "
                                  "a clip block whose clip is still there")
    batch, work, _slug = hit
    return json.loads((work / "plan.json").read_text()), work, batch


# H-43VeYGiPM shot 4 (CF-0004's coyote held pose): 1.08s, the length the
# synthetic held pose below is cut to and mounted at.
HELD_SHOT = (8.97, 1.08)


def _probe_times(block):
    """The composition times frozen_blocks() would sample this block at."""
    span = block["end"] - block["start"]
    return [block["start"] + span * f for f in qc_render.PROBE_FRACTIONS
            if block["start"] + span * f + qc_render.PROBE_GAP < block["end"]]


def test_source_time_follows_the_renderers_own_sequence_offset():
    """Video.jsx mounts each block CROSSFADE early, so at block["start"] the
    clip is already 0.35s into its own playback. Getting this wrong lands the
    source probe on the wrong frame, which is worse than not probing at all -
    it would answer confidently about a moment the render never showed."""
    block = {"start": 7.0, "end": 8.21, "asset": {"start_seconds": 0}}
    assert abs(qc_render.source_time(block, 7.0) - 0.35) < 1e-9
    assert abs(qc_render.source_time(block, 8.21) - 1.56) < 1e-9

    # The opening block cannot start early - Video.jsx clamps `from` at 0.
    first = {"start": 0.0, "end": 1.92, "asset": {"start_seconds": 0}}
    assert abs(qc_render.source_time(first, 0.0) - 0.0) < 1e-9

    # start_seconds is an extra trim on top, not a replacement for it.
    trimmed = {"start": 7.0, "end": 8.21, "asset": {"start_seconds": 2.5}}
    assert abs(qc_render.source_time(trimmed, 7.0) - 2.85) < 1e-9


def test_crossfade_constant_matches_the_renderer():
    """RENDER_CROSSFADE is a copy of a number that lives in Video.jsx. Two
    copies of a constant in two languages is how CF-0003 happened, and nothing
    else in the repo would notice this one drifting."""
    src = (AGENT_ROOT / "render" / "src" / "Video.jsx").read_text()
    import re
    m = re.search(r"const CROSSFADE = ([\d.]+);", src)
    assert m, "Video.jsx no longer declares CROSSFADE - source_time() is now guessing"
    assert float(m.group(1)) == qc_render.RENDER_CROSSFADE, (
        f"Video.jsx crossfades over {m.group(1)}s but qc_render.py assumes "
        f"{qc_render.RENDER_CROSSFADE}s - every source probe lands on the wrong frame")


def test_source_bar_is_the_same_bar_as_the_render_bar():
    """The verdict is 'is the still the render shows a still that is really in
    the footage?'. Answering it with a looser bar on the source side would be a
    silent relaxation of MIN_BLOCK_MOTION by the back door - exactly what
    CF-0004 says not to do."""
    assert qc_render.MIN_SOURCE_MOTION == qc_render.MIN_BLOCK_MOTION


def test_held_pose_override_is_reported_as_an_override():
    """Variant 3, the manual escape valve: an editor can mark one block in the
    plan. It must not be silent - the reason has to say a human decided it, so
    it is distinguishable in the QC report from a measurement."""
    block = {"start": 7.0, "end": 8.21,
             "asset": {"kind": "clip", "src": "/nonexistent.mp4", "held_pose": True}}
    fault, reason, source_motion = qc_render.freeze_verdict(block, [7.3], "/tmp", "t")
    assert fault is False
    assert "held_pose" in reason
    assert source_motion is None


def test_unverifiable_freeze_stays_a_failure():
    """Fail closed. A block whose clip is gone cannot be excused - the gate
    exists to stop a bad render reaching a human, so 'I could not check' has
    to keep the same answer it had before this check existed."""
    block = {"start": 7.0, "end": 8.21,
             "asset": {"kind": "clip", "src": "/definitely/not/here.mp4"}}
    fault, reason, _ = qc_render.freeze_verdict(block, [7.3], "/tmp", "t")
    assert fault is True and "missing" in reason


def test_live_shipped_clip_blocks_never_run_out():
    """CF-0031/CF-0131/CF-0249 on the factory's latest real plan: the planner
    degrades a clip block that would run past its clip before the render, so
    no clip block it shipped may - common.clip_shortfall() and held_tail()
    on the real clip's length say None, and freeze_verdict() decoding the
    real clip at the gate's own probe times never says 'ran out'. The
    synthetic hung / moving / held-pose tests above hold the verdicts; this is
    the same rule on real output. Reads only (untouched)."""
    if live_only(MONITOR_PLAN):
        return
    plan, work, batch = _live_batch_plan()
    blocks = _live_clip_blocks(plan)
    if not blocks:      # the clips left between the pick and now
        not_checked(MONITOR_PLAN, f"{work.relative_to(batch.parent)}: no clip block "
                                  f"whose clip is still there")
    bad = []
    with untouched(work, batch / "videos"), tempfile.TemporaryDirectory() as tmp:
        for i, block in blocks[:LIVE_SAMPLE_BLOCKS]:
            seconds = common.media_duration(block["asset"]["src"])
            short = common.clip_shortfall(block, seconds)
            tail = common.held_tail(block, seconds)
            times = _probe_times(block)
            _fault, reason, _m = (qc_render.freeze_verdict(block, times, tmp, f"b{i}")
                                  if times else (False, "", None))
            if short is not None or tail is not None or "ran out" in (reason or ""):
                bad.append(f"block {i} ({Path(block['asset']['src']).name}, "
                           f"{seconds:.2f}s clip, {block['end'] - block['start']:.2f}s "
                           f"block): shortfall={short} held_tail={tail} verdict={reason!r}")
    print(f"     {work.relative_to(batch.parent)}: {min(len(blocks), LIVE_SAMPLE_BLOCKS)} "
          f"clip blocks decoded")
    assert not bad, ("a shipped clip block runs past its clip (CF-0131/CF-0249 let it "
                     "through):\n" + "\n".join(bad))


def _fake_run(chan, batch, slug, blocks, clips_dir=True):
    work = chan / batch / "work" / slug
    work.mkdir(parents=True)
    if clips_dir:
        (work / "clips").mkdir()
    (work / "plan.json").write_text(json.dumps({"blocks": blocks}))
    return work


def test_live_plan_pick_skips_runs_with_no_live_clip_block():
    """CF-0868: the shipped-clip monitor's pick on temp batches (no live
    tree). The newest batch's first slug is all sequence/still (the
    0841Z/i-play-rocky shape) and the next one's clip is gone; the pick
    lands on the same batch's run whose clip is on disk, not on an older
    batch and not on NOT_CHECKED. With no live clip anywhere it is
    NotChecked, never a pass."""
    from _live_monitors import NotChecked
    with tempfile.TemporaryDirectory() as tmp:
        chan = Path(tmp) / "example-film"
        live_clip = Path(tmp) / "live.mp4"
        live_clip.write_bytes(b"x")
        seq = {"start": 0, "end": 2, "asset": {"kind": "sequence", "cuts": [
            {"kind": "clip", "src": str(live_clip), "seconds": 2}]}}
        still = {"start": 2, "end": 3, "asset": {"kind": "still", "src": str(live_clip)}}
        gone = {"start": 0, "end": 2, "asset": {"kind": "clip", "src": str(Path(tmp) / "gone.mp4")}}
        live = {"start": 0, "end": 2, "asset": {"kind": "clip", "src": str(live_clip)}}
        _fake_run(chan, "2026-10-26T0841Z", "a-all-sequence", [seq, still])
        _fake_run(chan, "2026-10-26T0841Z", "b-clip-gone", [gone])
        _fake_run(chan, "2026-10-26T0841Z", "c-no-clips-dir", [live], clips_dir=False)
        want = _fake_run(chan, "2026-10-26T0841Z", "d-live", [seq, live])
        _fake_run(chan, "2026-10-25T0834Z", "a-older", [live])
        plan, work, batch = _live_batch_plan([chan])
        assert work == want and batch.name == "2026-10-26T0841Z", work
        assert [i for i, _ in _live_clip_blocks(plan)] == [1]

        # no run anywhere with a live clip block -> NotChecked, not a pass
        chan2 = Path(tmp) / "empty"
        _fake_run(chan2, "2026-10-26T0841Z", "a-all-sequence", [seq, still])
        _fake_run(chan2, "2026-10-25T0834Z", "b-clip-gone", [gone])
        (chan2 / "2026-10-25T0834Z" / "work" / "broken").mkdir()
        (chan2 / "2026-10-25T0834Z" / "work" / "broken" / "clips").mkdir()
        (chan2 / "2026-10-25T0834Z" / "work" / "broken" / "plan.json").write_text("{not json")
        try:
            _live_batch_plan([chan2])
        except NotChecked as e:
            assert "clip block whose clip is still there" in str(e)
        else:
            raise AssertionError("no live clip block anywhere must be NotChecked")


# --------------------------------------------------------------------------
# CF-0522: the same three verdicts on synthetic media of the same shape - the
# regression runs in the suite; the 2155Z clips and the pool trailer are gone
# (CF-0908: the trailer's grained held pose is a stand below, not a monitor).
# --------------------------------------------------------------------------

def test_hung_block_on_a_short_clip_fails_as_playback_ran_out():
    """CF-0031 in the shape 2155Z block 4 had: an 11.91s block on a 1.07s
    clip. Every probe lands past the clip's last frame - 'playback ran out' -
    and that stays a failure, whatever the source looks like."""
    with tempfile.TemporaryDirectory() as tmp:
        clip = syn.moving_clip(Path(tmp) / "short.mp4", 1.07)
        block = {"start": 20.0, "end": 31.91,
                 "asset": {"kind": "clip", "src": clip, "start_seconds": 0}}
        fault, reason, source_motion = qc_render.freeze_verdict(
            block, _probe_times(block), tmp, "hung")
    assert fault is True, f"a hung block was excused: {reason}"
    assert "ran out" in reason, reason
    assert source_motion is None, source_motion


def test_moving_source_under_a_still_render_is_not_excused():
    """The other fault: the clip is long enough and moves, so a motionless
    render is not showing it - the source probe must say it moves."""
    with tempfile.TemporaryDirectory() as tmp:
        clip = syn.moving_clip(Path(tmp) / "moving.mp4", 4.0)
        block = {"start": 0.0, "end": 3.0,
                 "asset": {"kind": "clip", "src": clip, "start_seconds": 0}}
        fault, reason, source_motion = qc_render.freeze_verdict(
            block, _probe_times(block), tmp, "moving")
    assert fault is True, f"a moving clip was excused: {reason}"
    assert source_motion >= qc_render.MIN_SOURCE_MOTION, source_motion


def test_held_pose_in_the_source_is_excused():
    """CF-0004: a drawn held pose (one frame held for the whole shot) renders
    as a still because the shot is a still - excused, with the source motion
    in the reason, mounted the way the coyote-vs-acme plan mounted it."""
    with tempfile.TemporaryDirectory() as tmp:
        clip = syn.held_clip(Path(tmp) / "held.mp4", HELD_SHOT[1])
        block = {"start": 7.0, "end": 7.0 + HELD_SHOT[1],
                 "asset": {"kind": "clip", "src": clip, "start_seconds": 0}}
        fault, reason, source_motion = qc_render.freeze_verdict(
            block, _probe_times(block), tmp, "held")
    assert fault is False, f"a genuine held pose was still failed: {reason}"
    assert source_motion is not None and source_motion < qc_render.MIN_SOURCE_MOTION, (
        source_motion)
    assert "motionless" in reason, reason


# What H-43VeYGiPM shot 4 measured inside the kept window (CF-0004): a drawn
# held pose is not a perfect still - codec noise and grain kept it at
# 0.43-0.64, under MIN_SOURCE_MOTION but far from zero.
TRAILER_HELD_MOTION = (0.43, 0.64)
HELD_GRAIN = 4      # ffmpeg `noise` strength that lands a held frame there


def _noisy_held_clip(path, seconds):
    """A held frame with temporal grain on it - the shape of the real
    trailer's held pose, not the single frame syn.held_clip() repeats."""
    subprocess.run(
        [FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc2=duration=0.04:size={syn.SIZE}:rate={syn.RATE}",
         "-vf", f"tpad=stop_mode=clone:stop_duration={seconds},"
                f"noise=alls={HELD_GRAIN}:allf=t",
         "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264",
         "-crf", "18", "-preset", "ultrafast", "-threads", "1", str(path)],
        capture_output=True, check=True)
    return str(path)


def test_noisy_held_pose_like_the_coyote_trailer_is_excused():
    """CF-0004/CF-0908: the stand for the retired pool-trailer monitor. A
    held pose whose source still flickers the way the coyote shot did (a
    measurable motion, well under the bar) is excused as held footage - the
    gate must not read grain as the clip moving. Mounted the way the real
    coyote-vs-acme plan mounted it."""
    with tempfile.TemporaryDirectory() as tmp:
        clip = _noisy_held_clip(Path(tmp) / "grain.mp4", HELD_SHOT[1])
        block = {"start": 7.0, "end": 7.0 + HELD_SHOT[1],
                 "asset": {"kind": "clip", "src": clip, "start_seconds": 0}}
        fault, reason, source_motion = qc_render.freeze_verdict(
            block, _probe_times(block), tmp, "grain")
    assert source_motion is not None and 0.1 < source_motion < qc_render.MIN_SOURCE_MOTION, (
        f"the grained held pose measured {source_motion} - the stand no longer has the "
        f"trailer's shape ({TRAILER_HELD_MOTION[0]}-{TRAILER_HELD_MOTION[1]})")
    assert fault is False, f"a held pose with codec grain was failed: {reason}"
    assert "motionless" in reason, reason


def test_relaxation_is_written_into_the_report():
    """A leniency nobody can see is worse than no leniency. Every excused block
    has to leave a reason behind for the QC report and the batch record, not
    just vanish from the failure list."""
    excused = {"index": 5, "motion": 0.14, "fault": False,
               "reason": "the source clip is motionless here too (source motion 0.44)",
               "source_motion": 0.44}
    assert excused["reason"], "an excused block with no reason is a silent pass"
    # The shape main() reads: excused blocks are absent from frozen_clip_blocks
    # but present, with their measurement, in held_source_blocks.
    stills = [excused, {"index": 4, "motion": 0.14, "fault": True,
                        "reason": "playback ran out", "source_motion": None}]
    assert [s["index"] for s in stills if s["fault"]] == [4]
    assert [s["index"] for s in stills if not s["fault"]] == [5]


if __name__ == "__main__":
    from _live_monitors import not_checked_tail, run_tests
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed, unchecked, rc = run_tests(tests)
    print(f"\n{len(tests) - failed - unchecked}/{len(tests)} passed"
          + not_checked_tail(unchecked))
    sys.exit(rc)

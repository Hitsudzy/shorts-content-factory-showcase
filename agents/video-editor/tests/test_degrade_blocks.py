#!/usr/bin/env python3
"""CF-0031: degradation must be per-block, not per-video.

Real batch 2026-08-31T2155Z (video 2, "Rapid & Reckless: Neon Drift") is
the regression this guards: `qc_render.py`'s `frozen_blocks()` flagged one
block (index 4, a static title-card, motion 0.32) out of 19, and the old
retry logic responded by re-rendering the *entire* video as stills - 18 good
motion blocks thrown away to fix one. These tests replayed that real
storyboard through `build_render_plan.py --degrade-block`; since the batch
left the live tree (CF-0500) they run on synthetic media of its shape
(CF-0522) and check that only the flagged index changes, and a live monitor
checks the record of the newest real run (CF-0558).

No pytest dependency - plain asserts, run directly (matches this directory's
other tests).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from repo_paths import VENV_PY  # noqa: E402 - CF-0125: resolved against the main checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_monitors import live_only, newest_run, not_checked, untouched  # noqa: E402 - CF-0519/CF-0558
import _synthetic_media as syn  # noqa: E402 - CF-0522
from _tmproot import tmp_root  # noqa: E402

# CF-0519/CF-0558: the 2155Z run these tests replayed left the live tree
# with CF-0500; the regressions run on synthetic media of its shape below
# (CF-0522), and the live monitor (_live_batch) checks the record of the
# newest real run. The typo refusal needs no batch at all.
MONITOR = "test_degrade_blocks.py::_live_batch"
STORYBOARD = WORDS = VOICE = None


def _live_batch():
    """(batch, work, slug) of the newest live run with a plan.json and its
    rendered mp4 - preferring one whose plan degraded a block, so the record
    has something to name. NotChecked when the live tree has none."""
    import _channel_ids   # the channel's batches under every name it had (CF-0180)
    dirs = _channel_ids.channel_batch_dirs("example-film")

    def degraded(work):
        try:
            return bool(json.loads((work / "plan.json").read_text()).get("degraded_blocks"))
        except (OSError, ValueError):
            return False
    hit = (newest_run(dirs, ("plan.json",), videos=True, accept=degraded)
           or newest_run(dirs, ("plan.json",), videos=True))
    if hit is None:
        not_checked(MONITOR, "no live run of the channel holds a plan.json and its "
                             "rendered mp4")
    return hit


# CF-0137: a channel config with the per-block assetless rung switched *on*.
# Since CF-0137 that rung is off by default on every channel and
# build_render_plan.py refuses to write a plan carrying a block with no
# picture (tests/test_assetless_rung_gate.py pins the refusal). CF-0031's
# subject - that a degradation stays isolated to the block it was asked for -
# is unchanged, but the runs below that actually produce a procedural block
# now have to say which channel allowed it. A test config, never a real
# channel file.
def _rung_on_channel(tmp):
    path = Path(tmp) / "rung-on-channel.json"
    path.write_text(json.dumps({
        "channel_id": "test-rung-on",
        "display_name": "Test Channel", "theme": STAND_IN_THEME,
        "assetless_block_rung": {
            "enabled": True,
            "reason": "test config only - CF-0137's rung is off on every real "
                      "channel, and this exercises the branch under it"},
    }))
    return ["--channel", str(path)]


def _run_plan(tmp, extra_args):
    out = Path(tmp) / "plan.json"
    result = subprocess.run(
        [VENV_PY, str(SCRIPTS / "build_render_plan.py"),
         str(STORYBOARD), str(WORDS), str(VOICE), str(out),
         "--style", "motion",
         # CF-0104: three of this batch's clips (a07/a08/a10 of
         # 6fcoM7Q348Q_s012, blocks 10/11/14) sit right on a single subject's
         # face, and crop_for_aspect()'s pre-existing single-subject
         # tightening (CF-0033, unrelated to this task) zooms their
         # delivered 9:16 window down to ~632px of real source height - a
         # genuine resolution loss the new geometry-aware floor now
         # correctly measures (source short side is 816px; this batch
         # shipped before that floor existed). This suite is CF-0031's - it
         # exists to prove degradation stays isolated to the one flagged
         # block, not to grade this particular archived batch's crops - so
         # the floor is relaxed to 600 (the pre-CF-0003 default, per
         # common.py) for these three unrelated blocks rather than teaching
         # the suite to also expect a second, incidental rejection.
         "--min-short-side", "600"] + extra_args,
        capture_output=True, text=True, cwd=tmp)
    return result, out


def test_live_record_names_every_degraded_block():
    """CF-0031's honesty requirement on the newest real run: write_batch_
    metadata.py, on a temp copy of the shipped plan (it writes the score log
    next to the plan it reads) and the real mp4, names every block the plan
    degraded - index, from, to, reason - and `style_delivered` says
    'mixed: k/N' exactly when k > 0. Reads the live tree only (untouched)."""
    if live_only(MONITOR):
        return
    batch, work, slug = _live_batch()
    mp4 = batch / "videos" / f"{slug}.mp4"
    plan = json.loads((work / "plan.json").read_text())
    with untouched(work, batch / "videos"), tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "plan.json"
        copy.write_text((work / "plan.json").read_text())
        score = work / "plan.score.json"
        if score.exists():
            (Path(tmp) / "plan.score.json").write_text(score.read_text())
        meta = subprocess.run(
            [VENV_PY, str(SCRIPTS / "write_batch_metadata.py"), tmp,
             "--video", slug, str(copy), str(mp4),
             "--style-requested", plan.get("style") or "motion"],
            capture_output=True, text=True, cwd=tmp)
        assert meta.returncode == 0, meta.stderr[-3000:]
        v = json.loads((Path(tmp) / "05-video-editor.json").read_text())["videos"][0]
    want = [{"block_index": d["index"], "from": d["from"], "to": d["to"],
             "reason": d.get("reason") or "failed post-render QC"}
            for d in plan.get("degraded_blocks") or []]
    print(f"     {batch.name}/{slug}: {len(want)} degraded of {len(plan['blocks'])}")
    assert v["degradation"] == want, (v["degradation"], want)
    k, n = len(want), len(plan["blocks"])
    if k:
        assert f"mixed: {k}/{n}" in v["style_delivered"], v["style_delivered"]
    else:
        assert "mixed" not in v["style_delivered"], v["style_delivered"]


def test_degrade_block_invalid_target_rejected():
    """A typo in the target ('stils' instead of 'still') must fail loudly at
    argument-parsing time, not silently do nothing or crash deep inside the
    per-block loop. CF-0519: no batch needed - the refusal comes before any
    input is read, so the inputs are empty temp files."""
    global STORYBOARD, WORDS, VOICE
    with tempfile.TemporaryDirectory() as tmp:
        saved = STORYBOARD, WORDS, VOICE
        STORYBOARD, WORDS, VOICE = (Path(tmp) / n for n in
                                    ("storyboard.json", "words.json", "voice.wav"))
        for f in (STORYBOARD, WORDS, VOICE):
            f.write_text("")
        try:
            result, out = _run_plan(tmp, ["--degrade-block", "4:stils:typo"])
        finally:
            STORYBOARD, WORDS, VOICE = saved
        assert result.returncode != 0, "an invalid --degrade-block target should fail"
        assert "must be 'still' or 'typographic'" in result.stderr, result.stderr
        assert not out.exists(), "no plan should be written on a bad argument"


# --------------------------------------------------------------------------
# CF-0522: the regressions on synthetic media of the 2155Z shape, in the suite
# --------------------------------------------------------------------------
# The 2155Z clips, voice and mp4 are gone with the batch (CF-0500), so the
# real-run tests above check nothing outside a live run. The same shape is
# built here: five clip blocks over a synthetic voice - block 1 is the one a
# post-render probe flags (2155Z's block 4), block 2 a 2.0s block on a 0.3s
# clip (CF-0131, 2155Z's block 5), block 3 a 4.0s block on a 1.8s clip that
# plays and then holds its last frame (CF-0249, 2155Z's block 18); 0 and 4
# are sound and must stay clips. Built once and shared by the tests that read
# it - each plan run inspects every block (qc_asset + smart_crop, ~8 s each).
SYN_DURATIONS = [2.0, 2.0, 2.0, 4.0, 2.0]
SYN_CLIPS = {2: 0.3, 3: 1.8}          # the starved ones; the rest run 3.0s
SYN_FLAGGED = 1
SYN_SHORTFALL, SYN_HOLD = 2, 3
_SYN = {}


def _syn_inputs():
    """(tmp, storyboard, words, voice) of the synthetic run, built once."""
    if "inputs" not in _SYN:
        tmp = tmp_root("ve-degrade-blocks-")
        blocks, t = [], 0.0
        for i, d in enumerate(SYN_DURATIONS):
            clip = syn.moving_clip(tmp / f"a{i:02d}.mp4", SYN_CLIPS.get(i, 3.0))
            blocks.append(syn.storyboard_block(clip, round(t, 2), round(t + d, 2),
                                               word_range=(i * 4, i * 4 + 3)))
            t += d
        story = syn.write_json(tmp / "storyboard.json", syn.storyboard(blocks))
        words = syn.write_json(tmp / "words.json", syn.words(
            len(SYN_DURATIONS) * 4, start=0.1, step=t / (len(SYN_DURATIONS) * 4)))
        voice = Path(syn.voice(tmp / "voice.wav", t + 0.3, lead=0.1))
        # The real channel's 50 % still-share refusal (CF-0418) is not this
        # suite's subject: three of five blocks go still here by design.
        chan = syn.write_json(tmp / "channel.json", {
            "channel_id": "test-still-share-off",
            "display_name": "Test Channel", "theme": STAND_IN_THEME,
            "video_editor": {"max_still_share": 1.0}})
        _SYN["inputs"] = (tmp, story, words, voice, chan)
    return _SYN["inputs"]


def _syn_plan(out_dir, extra_args):
    _tmp, story, words, voice, chan = _syn_inputs()
    out = Path(out_dir) / "plan.json"
    result = subprocess.run(
        [VENV_PY, str(SCRIPTS / "build_render_plan.py"), str(story), str(words),
         str(voice), str(out), "--style", "motion", "--channel", str(chan)]
        + list(extra_args),
        capture_output=True, text=True, cwd=out_dir, env=syn.env(out_dir))
    return result, out


def _syn_flagged_plan():
    """The plan with block SYN_FLAGGED degraded by a post-render verdict -
    built once, read by the isolation test and the metadata test."""
    if "flagged" not in _SYN:
        out_dir = _syn_inputs()[0] / "flagged"
        out_dir.mkdir()
        result, out = _syn_plan(out_dir, [
            "--degrade-block", f"{SYN_FLAGGED}:still:motion 0.32 below threshold"])
        assert result.returncode == 0, (
            f"build_render_plan.py failed:\n{result.stdout}\n{result.stderr[-3000:]}")
        _SYN["flagged"] = out
    return _SYN["flagged"]


def _expected_degradations(plan_or_list, key="index"):
    rows = plan_or_list
    assert [r[key] for r in rows] == [SYN_FLAGGED, SYN_SHORTFALL, SYN_HOLD], rows
    assert rows[0]["reason"] == "motion 0.32 below threshold", rows[0]
    assert "CF-0131" in rows[1]["reason"] and "every frame" in rows[1]["reason"], rows[1]
    assert "CF-0249" in rows[2]["reason"] and "held last frame" in rows[2]["reason"], rows[2]
    for r in rows:
        assert (r["from"], r["to"]) == ("clip", "still"), r


def test_synthetic_degrade_block_touches_only_the_flagged_index():
    """CF-0031 on the 2155Z shape: degrading the one flagged block leaves the
    sound blocks clips; the two starved ones (CF-0131, CF-0249) go still on
    the planner's own call, each with its own reason, and the style stays."""
    plan = json.loads(_syn_flagged_plan().read_text())
    kinds = [b["asset"]["kind"] for b in plan["blocks"]]
    assert len(kinds) == len(SYN_DURATIONS), kinds
    for i, k in enumerate(kinds):
        want = "still" if i in (SYN_FLAGGED, SYN_SHORTFALL, SYN_HOLD) else "clip"
        assert k == want, (f"block {i}: {k!r}, expected {want!r} - per-block "
                           f"degradation must not leak into other blocks ({kinds})")
    _expected_degradations(plan["degraded_blocks"])
    assert plan["style"] == "motion"


def test_synthetic_zero_surviving_blocks_triggers_whole_video_fallback_notice():
    """Every block degraded to typographic (rung allowed by a test channel):
    an all-procedural plan, and the whole-video notice on stderr."""
    tmp = _syn_inputs()[0]
    out_dir = tmp / "all-typographic"
    out_dir.mkdir()
    chan = syn.write_json(out_dir / "channel.json", {
        "channel_id": "test-rung-on",
        "display_name": "Test Channel", "theme": STAND_IN_THEME,
        "assetless_block_rung": {"enabled": True, "reason": "test config only (CF-0137)"},
        "video_editor": {"max_still_share": 1.0}})
    story, words, voice = _syn_inputs()[1:4]
    args = []
    for i in range(len(SYN_DURATIONS)):
        args += ["--degrade-block", f"{i}:typographic:synthetic total-failure test"]
    result = subprocess.run(
        [VENV_PY, str(SCRIPTS / "build_render_plan.py"), str(story), str(words),
         str(voice), str(out_dir / "plan.json"), "--style", "motion",
         "--channel", str(chan)] + args,
        capture_output=True, text=True, cwd=out_dir, env=syn.env(out_dir))
    assert result.returncode == 0, result.stderr[-3000:]
    plan = json.loads((out_dir / "plan.json").read_text())
    assert {b["asset"]["kind"] for b in plan["blocks"]} == {"procedural"}, plan["blocks"]
    assert len(plan["degraded_blocks"]) == len(SYN_DURATIONS)
    assert "ALL BLOCKS DEGRADED" in result.stderr, result.stderr[-3000:]


def test_synthetic_metadata_records_per_block_degradation():
    """05-video-editor.json names each degraded block with its reason and
    style_delivered says the video is mixed, 3 of 5 (the 2155Z run: 3/19)."""
    plan_path = _syn_flagged_plan()
    out_dir = plan_path.parent
    mp4 = syn.video_with_audio(out_dir / "synthetic.mp4", sum(SYN_DURATIONS))
    meta = subprocess.run(
        [VENV_PY, str(SCRIPTS / "write_batch_metadata.py"), str(out_dir),
         "--video", "synthetic", str(plan_path), mp4, "--style-requested", "motion"],
        capture_output=True, text=True, env=syn.env(out_dir))
    assert meta.returncode == 0, meta.stderr[-3000:]
    v = json.loads((out_dir / "05-video-editor.json").read_text())["videos"][0]
    _expected_degradations(v["degradation"], key="block_index")
    assert "mixed" in v["style_delivered"] and "3/5" in v["style_delivered"], (
        v["style_delivered"])


# --------------------------------------------------------------------------
# CF-0681: the live monitor above, run on a stand-in live tree, writes nothing
# --------------------------------------------------------------------------
# 10.10 the monitor, run live on 2.3, left videos/harbourlights.jpg in the shipped
# batch 2026-10-05T0701Z: write_batch_metadata.py wrote CF-0674's preview
# beside the real mp4 it was only handed to read. Here the same monitor
# function runs with its live switch on for this call only, on a stand-in
# factory root under tmp_root (FACTORY_ROOT, the channel's batch dirs), with
# a shipped-shaped batch built of the synthetic flagged plan - and the tree is
# the same byte for byte afterwards. The real tree is never named: the batch
# the monitor picks is checked to sit under the stand before it runs.

def _tree_bytes(root):
    import hashlib
    return {str(f.relative_to(root)): (hashlib.sha256(f.read_bytes()).hexdigest(),
                                       f.stat().st_mtime_ns)
            for f in sorted(Path(root).rglob("*")) if f.is_file()}


def test_live_monitor_on_a_stand_in_tree_leaves_it_byte_for_byte():
    import os
    import _channel_ids
    root = tmp_root("ve-cf0681-stand-") / "factory"
    batch = root / "pipeline" / "example-film" / "2026-10-05T0701Z"
    work = batch / "work" / "harbourlights"
    work.mkdir(parents=True)
    (work / "plan.json").write_text(_syn_flagged_plan().read_text())
    (batch / "videos").mkdir()
    syn.video_with_audio(batch / "videos" / "harbourlights.mp4", sum(SYN_DURATIONS))
    g = globals()
    saved = (g["live_only"], _channel_ids.channel_batch_dirs,
             os.environ.get("FACTORY_ROOT"))
    g["live_only"] = lambda test_id: False          # the switch, for this call only
    _channel_ids.channel_batch_dirs = lambda channel, *a, **k: [
        root / "pipeline" / channel]
    os.environ["FACTORY_ROOT"] = str(root)
    try:
        picked = _live_batch()
        assert picked[0] == batch, f"the stand's monitor picked {picked[0]}, not {batch}"
        before = _tree_bytes(root)
        test_live_record_names_every_degraded_block()
        after = _tree_bytes(root)
    finally:
        g["live_only"], _channel_ids.channel_batch_dirs = saved[:2]
        if saved[2] is None:
            os.environ.pop("FACTORY_ROOT", None)
        else:
            os.environ["FACTORY_ROOT"] = saved[2]
    assert after == before, ("the live monitor wrote the tree it reads (CF-0681): "
                             f"{sorted(set(after) ^ set(before)) or 'changed bytes'}")
    assert not (batch / "videos" / "harbourlights.jpg").exists()


if __name__ == "__main__":
    from _live_monitors import not_checked_tail, run_tests
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed, unchecked, rc = run_tests(tests)
    print(f"\n{len(tests) - failed - unchecked}/{len(tests)} passed"
          + not_checked_tail(unchecked))
    sys.exit(rc)

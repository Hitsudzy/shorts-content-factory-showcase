#!/usr/bin/env python3
"""CF-0549: `--degrade-block N:still` on a `sequence` block gives a real still.

Rebuild `pipeline/rebuilds/2026-10-05T1244Z`, video `delver` (v1.7.2): QC
failed block 3 `frozen` - a stretch split (CF-0480/CF-0536) of five clip cuts
and a held tail, stuck 1.8s inside its fifth cut - and hinted `3:still`. The
rebuild with `--degrade-block 3:still:...` renamed the block's first cut
`still` and kept its `.mp4` as the asset, so qc_asset.py / smart_crop.py were
handed a video as a picture ("cannot read image") and the plan died, every
time. The rung now goes the way QC found the fault: the cut that stuck becomes
a frame lifted out of its own clip (the hold rule - sharpest-calm moment,
calmest, middle), the other cuts keep moving; with no cut named, the block
holds its first picture, lifted the same way.

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

import attempts  # noqa: E402
import build_render_plan as bp  # noqa: E402
import qc_render  # noqa: E402
from common import FFMPEG  # noqa: E402

# The detail line the 1244Z ledger carries for delver attempt 1, verbatim.
DELVER_DETAIL = ("clip blocks rendered as stills: block 3 (still for 1.8s from "
                 "24.9s, motion 0.8) - the source clip moves here (source motion "
                 "1.18) but the render does not")


def _clip(path, seconds):
    subprocess.run(
        [FFMPEG, "-y", "-nostdin", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=1080x1920:rate=25",
         "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _frame(clip, at, dest):
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", "-ss", str(at),
                    "-i", str(clip), "-frames:v", "1", str(dest)], check=True)
    return str(dest)


def _is_image(path):
    from PIL import Image
    with Image.open(path) as im:
        im.verify()
    return True


def _cut(asset, shot, at, seconds, kind="clip", held=False):
    return {"asset": asset, "kind": kind, "held_frame": held, "shot": shot,
            "at": at, "seconds": seconds, "is_card": False, "crop_bottom": 0.0,
            "frame_before_crop": "1080x1920"}


# --------------------------------------------------------------------------
# which cut stuck
# --------------------------------------------------------------------------

def _ledger(work, last):
    (work / attempts.LEDGER_NAME).write_text(json.dumps(
        {"slug": work.name, "attempts": [{"n": 1, "kind": "attempt",
                                          "result": "qc_failed", **last}],
         "needs_you": None}))


def _seq_plan(work):
    """The plan QC judged: block 3 of delver 1244Z, its spans as built."""
    cuts = [{"kind": "clip", "seconds": s} for s in (0.98, 1.27, 2.74, 0.92, 4.04)]
    cuts.append({"kind": "still", "seconds": 1.01, "held_frame": True})
    blocks = [{"start": 0.0, "end": 17.42, "asset": {"kind": "clip"}}] * 3
    blocks.append({"start": 17.42, "end": 28.38,
                   "asset": {"kind": "sequence", "cuts": cuts}})
    (work / "plan.json").write_text(json.dumps({"blocks": blocks}))
    return work / "plan.json"


def test_qc_names_the_cut_and_the_planner_reads_it():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "batch" / "work" / "delver"
        work.mkdir(parents=True)
        out = _seq_plan(work)
        _ledger(work, {"detail": DELVER_DETAIL, "qc_hint": ["3:still"],
                       "qc_frozen": attempts.qc_frozen_records(
                           [{"index": 3, "cut": 4, "still_run_at": 24.9,
                             "still_run": 1.8}])})
        assert bp.frozen_cuts(str(out), {3}) == {3: [4]}
        # Only the indices asked about.
        assert bp.frozen_cuts(str(out), {5}) == {}


def test_an_old_ledger_is_read_off_its_detail_line_and_the_judged_plan():
    """1244Z's ledger was written before `qc_frozen`: "from 24.9s" is mapped
    onto the plan QC judged - 24.9s is 7.48s into block 3, inside cut 4
    (5.91-9.95s), the cut the stretch split stretched."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "batch" / "work" / "delver"
        work.mkdir(parents=True)
        out = _seq_plan(work)
        _ledger(work, {"detail": DELVER_DETAIL, "qc_hint": ["3:still"]})
        assert bp.frozen_cuts(str(out), {3}) == {3: [4]}


def test_no_ledger_or_a_passed_render_names_no_cut():
    with tempfile.TemporaryDirectory() as tmp:
        assert bp.frozen_cuts(str(Path(tmp) / "plan.json"), {3}) == {}
        work = Path(tmp) / "batch" / "work" / "delver"
        work.mkdir(parents=True)
        out = _seq_plan(work)
        (work / attempts.LEDGER_NAME).write_text(json.dumps(
            {"slug": "delver", "attempts": [{"n": 1, "result": "rendered_ok",
                                             "detail": DELVER_DETAIL}]}))
        assert bp.frozen_cuts(str(out), {3}) == {}


def test_qc_render_tags_the_cut_of_a_sequence():
    """The record frozen_blocks() writes for a sequence carries the cut its
    probe target was (probe_targets' tag `b<i>c<k>`)."""
    block = {"start": 0.0, "end": 3.0,
             "asset": {"kind": "sequence", "cuts": [
                 {"kind": "clip", "src": "/a.mp4", "seconds": 1.0},
                 {"kind": "still", "src": "/a.png", "seconds": 1.0},
                 {"kind": "clip", "src": "/b.mp4", "seconds": 1.0}]}}
    tags = [t for _, _, t, _ in qc_render.probe_targets(block, 3)]
    assert tags == ["b3c0", "b3c2"], tags
    src = Path(qc_render.__file__).read_text()
    assert 'r"b\\d+c(\\d+)"' in src and '"cut": int(cut_tag.group(1))' in src


def test_the_ledger_keeps_qc_frozen_on_a_qc_failure_only():
    with tempfile.TemporaryDirectory() as tmp:
        b = Path(tmp) / "pipeline" / "chan" / "b1"
        (b / "work" / "vid").mkdir(parents=True)
        attempts.begin(b, "vid", reason="first")
        rec = attempts.qc_frozen_records([{"index": 3, "cut": 4,
                                           "still_run_at": 24.9, "still_run": 1.8}])
        attempt, _, _ = attempts.end(b, "vid", attempts.RESULT_QC_FAILED,
                                     detail=DELVER_DETAIL, qc_hint=["3:still"],
                                     qc_frozen=rec)
        assert attempt["qc_frozen"] == [{"index": 3, "cut": 4, "still_run_at": 24.9,
                                         "still_run": 1.8}], attempt


# --------------------------------------------------------------------------
# the frame
# --------------------------------------------------------------------------

def test_the_frame_is_lifted_by_the_hold_rule():
    """sharpest-calm moment of the record when it falls in the clip, else the
    calmest moment of the clip, else its middle - and always an image."""
    saved = (bp.shot_score.held_moment, bp.held_motion.calmest_moment)
    with tempfile.TemporaryDirectory() as tmp:
        clip = _clip(Path(tmp) / "c.mp4", 2.0)
        cut = {**_cut(clip, "s:1", 0.0, 2.0), "cut_at": 100.0}
        try:
            bp.shot_score.held_moment = lambda used: (101.2, 0.7)
            bp.held_motion.calmest_moment = lambda c: 0.4
            fail, rec = bp.lift_held_frame(cut, str(Path(tmp) / "a.png"))
            assert fail is None and rec["rule"] == "sharpest_calm" and rec["at"] == 1.2, rec
            bp.shot_score.held_moment = lambda used: (130.0, 0.7)   # outside the clip
            fail, rec = bp.lift_held_frame(cut, str(Path(tmp) / "b.png"))
            assert fail is None and rec["rule"] == "calmest" and rec["at"] == 0.4, rec
            bp.held_motion.calmest_moment = lambda c: None
            fail, rec = bp.lift_held_frame(cut, str(Path(tmp) / "c.png"))
            assert fail is None and rec["rule"] == "middle", rec
        finally:
            bp.shot_score.held_moment, bp.held_motion.calmest_moment = saved
        for n in "abc":
            assert _is_image(Path(tmp) / f"{n}.png")
        # A clip that is gone is a probe verdict, never a crash and never a
        # video handed on as a picture.
        fail, _ = bp.lift_held_frame(_cut(str(Path(tmp) / "gone.mp4"), "s:2", 0, 1.0),
                                     str(Path(tmp) / "d.png"))
        assert fail and fail["qc"]["usable"] is False, fail


def test_only_the_stuck_cut_stops_and_a_held_tail_of_its_shot_is_one_picture():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        a, b, c = (_clip(t / f"{n}.mp4", 1.5) for n in "abc")
        tail = _frame(c, 0.7, t / "held_c.png")
        cuts = [_cut(a, "a:1", 0.0, 1.5), _cut(b, "b:1", 1.5, 1.5),
                _cut(c, "c:1", 3.0, 1.5), _cut(tail, "c:1", 4.5, 1.0, "still", True)]
        out, rec, fails = bp.degrade_sequence_cuts(cuts, [1], 5.5, t, 3)
        assert not fails, fails
        assert [x["kind"] for x in out] == ["clip", "still", "clip", "still"], out
        assert out[1]["asset"].endswith("_degraded_still_3_c1.png"), out[1]
        assert _is_image(out[1]["asset"]) and out[1]["held_frame"] is True
        assert out[0] is cuts[0] and out[2] is cuts[2], "a cut that moved was touched"
        assert rec["cuts"] == [1], rec
        # The stuck cut right before a held frame of its own shot: one still.
        out, rec, _ = bp.degrade_sequence_cuts(cuts, [2], 5.5, t, 3)
        assert [x["kind"] for x in out] == ["clip", "clip", "still"], out
        assert out[2]["asset"] == tail and out[2]["seconds"] == 2.5, out[2]
        # Nothing named: the whole block holds its first picture - a frame.
        out, rec, _ = bp.degrade_sequence_cuts(cuts, None, 5.5, t, 3)
        assert len(out) == 1 and out[0]["kind"] == "still" and out[0]["seconds"] == 5.5
        assert out[0]["asset"].endswith("_degraded_still_3.png") and _is_image(out[0]["asset"])
        assert rec["cuts"] == "all", rec


# --------------------------------------------------------------------------
# end to end through the real planner
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


def _run_plan(work, ledger=None):
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    _silent_wav(work / "voice.wav")
    (work / "words.json").write_text(json.dumps(
        [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
          "end": round(0.9 + i * 0.5, 2)} for i in range(10)]))
    first = _clip(work / "first.mp4", 2.0)
    a, b = _clip(work / "a.mp4", 2.0), _clip(work / "b.mp4", 2.0)
    tail = _frame(b, 1.0, work / "held_b.png")
    seq = {"word_range": [0, 0], "intent": "seq", "asset_kind": "sequence",
           "cuts": [_cut(a, "a:1", 0.0, 1.9), _cut(b, "b:1", 1.9, 1.9),
                    _cut(tail, "b:1", 3.8, 1.0, "still", True)],
           "emphasis_words": [], "rhythm_role": "beat", "side": None,
           "shot": "a:1", "held_frame": False, "_start": 1.2, "_end": 6.0}
    one = {"word_range": [0, 0], "intent": "clip", "asset_kind": "clip",
           "asset": first, "emphasis_words": [], "rhythm_role": "beat",
           "side": None, "shot": "first:1", "held_frame": False,
           "_start": 0.0, "_end": 1.2}
    (work / "storyboard.json").write_text(json.dumps({
        "script_id": "cf-0549", "style": "motion", "resolved_from_anchors": True,
        "rhythm": {"pattern_requested": "explainer", "rhythm_requested": "staccato",
                   "rhythm_built": "staccato",
                   "parameters": {"block_count": 2, "key_frame_hold_seconds": 1.4},
                   "opening_requested": None, "opening_delivered": None,
                   "anchor_count": 2},
        "blocks": [one, seq], "unresolved_anchors": [], "rejected_candidates": []}))
    if ledger:
        _ledger(work, ledger)
    out = work / "plan.json"
    result = subprocess.run(
        [py, str(SCRIPTS / "build_render_plan.py"), str(work / "storyboard.json"),
         str(work / "words.json"), str(work / "voice.wav"), str(out),
         "--style", "motion", "--target-duration", "1", "60",
         "--degrade-block", "1:still:frozen in QC"],
        capture_output=True, text=True, cwd=work, timeout=280)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(out.read_text()), result.stderr


def test_build_render_plan_stills_the_stuck_cut_of_a_sequence():
    """The delver 1244Z shape, scaled down: QC named cut 1 of sequence block 1
    (its ledger says so); the plan builds, cut 1 and the held frame of its own
    shot after it are one still lifted out of the clip (a png the asset gate
    read), cut 0 still moves, block 0 is untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "batch" / "work" / "vid"
        work.mkdir(parents=True)
        plan, _ = _run_plan(work, {"qc_hint": ["1:still"], "qc_frozen": [
            {"index": 1, "cut": 1, "still_run_at": 3.4, "still_run": 1.8}]})
        blk = plan["blocks"][1]
        assert blk["asset"]["kind"] == "sequence", blk["asset"]
        cuts = blk["asset"]["cuts"]
        assert [c["kind"] for c in cuts] == ["clip", "still"], cuts
        assert cuts[0]["src"].endswith("a.mp4"), cuts[0]
        assert cuts[1]["src"].endswith("held_b.png") and cuts[1]["held_frame"], cuts[1]
        assert cuts[1]["source_size"]["width"] > 1, cuts[1]
        deg = plan["degraded_blocks"]
        assert [(d["index"], d["from"], d["to"], d["cuts"]) for d in deg] == \
            [(1, "sequence", "still", [1])], deg
        assert attempts.degraded_tags(plan) == ["1:still"]
        assert plan["blocks"][0]["asset"]["kind"] == "clip"


def test_build_render_plan_without_a_named_cut_holds_a_lifted_frame():
    """No ledger: the whole block holds its first picture - a png lifted out
    of the clip and through qc_asset, never the clip's .mp4 as a picture."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        plan, _ = _run_plan(work)
        cuts = plan["blocks"][1]["asset"]["cuts"]
        assert [c["kind"] for c in cuts] == ["still"], cuts
        assert cuts[0]["src"].endswith("_degraded_still_1.png"), cuts[0]
        assert Path(cuts[0]["src"]).exists() and _is_image(cuts[0]["src"])
        assert cuts[0]["source_size"]["width"] == 1080, cuts[0]
        assert plan["degraded_blocks"][0]["cuts"] == "all", plan["degraded_blocks"]


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

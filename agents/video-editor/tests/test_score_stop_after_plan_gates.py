#!/usr/bin/env python3
"""CF-0794: a video the score stops before its render is a refusal on record.

example-film 2026-10-18T0841Z, street-fighter: the plan stage of its score log
ended at F · 36,08 (thin picture 13,36 s, a face held still out of a moving
shot) - prices added by the plan's last gates, after CF-0433's own check. The
plan was written, render_video.py refused it (exit 4) and nothing wrote
`plan.score.refusal.json`; the operator then ran qc_render.py on the mp4 that
was never rendered (`KeyError: 'streams'`) and named a refusal file that did
not exist to write_batch_metadata.py (exit 2). 05-video-editor.json listed
the script nowhere. What is pinned:

- the plan's last check (`build_render_plan.late_score_stop`) under N writes
  the score's own sidecar - gate and funnel code `score_below_threshold` -
  and exits 2 with no plan; over N it lets the plan through and removes a
  stale sidecar;
- that refusal reaches `refusals[]` of 05-video-editor.json;
- a log stopped with no sidecar is still filed: by render_video.py's stop,
  and by write_batch_metadata.py itself (off the stored log, never re-priced);
- qc_render.py on a missing / unreadable video says so in a sentence and
  exits 2 (4 when the score had already stopped the video), no traceback.

No pytest dependency - plain asserts, run directly. Temp trees only.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0794-runlog-")))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import _pinned_prices as P  # noqa: E402
import _score  # noqa: E402
import plan_refusal  # noqa: E402
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo
import score_log  # noqa: E402

F = _score.finding


def _under_n():
    """44 on the pinned table (N 60): five similar blocks and a cut hero."""
    return ([F("score.low_similarity", {"block": i}) for i in range(5)]
            + [F("score.crop_cuts_subject", {"block": 2})])


def _py():
    venv = Path(repo_paths.VENV_PY3)
    return str(venv) if venv.exists() else sys.executable


def _run(argv, cwd, env=None):
    return subprocess.run([_py()] + [str(a) for a in argv], capture_output=True, text=True,
                          cwd=cwd, env={**os.environ, **(env or {})}, timeout=120)


def _args(plan, script_id="s1"):
    return SimpleNamespace(output=str(plan), script_id=script_id, degrade_block=None)


def _skip():
    if _score.module() is None:
        print(f"  SKIP: {_score.error()}")
        return True
    return False


# --------------------------------------------------------------------------
# build_render_plan: the check after the plan's last gates
# --------------------------------------------------------------------------

def test_a_plan_priced_under_n_by_its_last_gates_is_refused_with_the_score_sidecar():
    if _skip():
        return
    import build_render_plan as brp
    with P.pinned():
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            block = score_log.record(plan, score_log.STAGE_PLAN, _under_n(), script_id="s1")
            assert score_log.stops(block)
            try:
                brp.late_score_stop(_args(plan), dict(block), {})
            except SystemExit as e:
                assert e.code == 2, e.code
            else:
                raise AssertionError("a plan under N went on")
            assert not plan.exists()
            rec = json.loads(score_log.refusal_path(plan).read_text())
            assert score_log.refusal_path(plan).name == "plan.score.refusal.json"
            assert rec["script_id"] == "s1"
            assert rec["gate"] == plan_refusal.GATE_SCORE == "score_below_threshold"
            assert rec["reason_code"] == "score_below_threshold"
            assert rec["supersedes_video"] is True
            assert rec["numbers"]["stage"] == "plan", rec["numbers"]
            assert rec["score_line"].startswith("F · 44"), rec["score_line"]


def test_a_plan_over_n_goes_on_and_a_stale_score_sidecar_goes():
    if _skip():
        return
    import build_render_plan as brp
    with P.pinned():
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            stale = score_log.record(plan, score_log.STAGE_PLAN, _under_n(), script_id="s1")
            assert score_log.check(plan, stale, "s1", score_log.STAGE_QC)
            block = score_log.record(plan, score_log.STAGE_PLAN,
                                     [F("score.no_lofi_bed", {})], script_id="s1")
            assert brp.late_score_stop(_args(plan), dict(block), {}) is None
            assert not score_log.refusal_path(plan).exists()


# --------------------------------------------------------------------------
# 05-video-editor.json
# --------------------------------------------------------------------------

def test_the_refusal_reaches_05_with_its_code():
    if _skip():
        return
    import build_render_plan as brp
    import test_plan_refusal as tpr
    with P.pinned():
        with tempfile.TemporaryDirectory() as tmp:
            b = tpr._batch(tmp)
            sf = tpr._video(b, "street-fighter")
            ok = tpr._video(b, "s2")
            Path(sf[1]).unlink()  # the refused plan is not written
            block = score_log.record(sf[1], score_log.STAGE_PLAN, _under_n(),
                                     script_id="lf-1-script1")
            try:
                brp.late_score_stop(_args(sf[1], "lf-1-script1"), dict(block), {})
            except SystemExit:
                pass
            tpr._write(b, ok)
            doc = tpr._read(b)
            assert [v["script_id"] for v in doc["videos"]] == ["s2"], doc["videos"]
            (ref,) = doc["refusals"]
            assert ref["script_id"] == "lf-1-script1"
            assert ref["reason_code"] == "score_below_threshold", ref
            assert ref["gate"] == "score_below_threshold", ref


def test_metadata_files_a_stopped_log_that_has_no_sidecar():
    """The street-fighter state on disk: plan.json written, its log F, no
    refusal anywhere. The metadata call files it - off the stored log."""
    if _skip():
        return
    import test_plan_refusal as tpr
    with P.pinned():
        with tempfile.TemporaryDirectory() as tmp:
            b = tpr._batch(tmp)
            sf = tpr._video(b, "street-fighter")
            ok = tpr._video(b, "s2")
            score_log.record(sf[1], score_log.STAGE_PLAN, _under_n(), script_id="lf-1-script1")
            score_log.record(ok[1], score_log.STAGE_PLAN, [F("score.no_lofi_bed", {})],
                             script_id="s2")
            side = score_log.refusal_path(sf[1])
            assert not side.exists()
            _, err = tpr._write(b, ok, refusals=[side])
            assert side.exists() and "score refusal written (CF-0794)" in err, err
            assert not score_log.refusal_path(ok[1]).exists()
            doc = tpr._read(b)
            assert [v["script_id"] for v in doc["videos"]] == ["s2"]
            (ref,) = doc["refusals"]
            assert (ref["script_id"], ref["reason_code"]) == ("lf-1-script1",
                                                              "score_below_threshold"), ref


def test_metadata_never_reprices_a_stored_log():
    """A log written over N stays a video even if today's table would sink
    it: the filing reads the stored block, not a recomputed one."""
    if _skip():
        return
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work" / "a"
        work.mkdir(parents=True)
        plan = work / "plan.json"
        plan.write_text("{}")
        score_log.path_for(plan).write_text(json.dumps({
            "schema": score_log.SCHEMA, "script_id": "a", "plan": "plan.json", "stages": [],
            "score": {"score": 50, "threshold": 40, "stopped_at": None}, "score_line": "C · 50"}))
        assert score_log.ensure_refusals(tmp) == []
        assert not score_log.refusal_path(plan).exists()


# --------------------------------------------------------------------------
# render_video.py's stop
# --------------------------------------------------------------------------

def test_the_renderer_files_the_refusal_it_stops_on():
    if _skip():
        return
    with P.pinned() as root:
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({"style": "motion", "blocks": [],
                                        "audio": {"duration": 40.0, "src": "voice.wav"},
                                        "output": {"width": 1080, "height": 1920, "fps": 30}}))
            score_log.record(plan, score_log.STAGE_PLAN, _under_n(), script_id="s1")
            r = _run([SCRIPTS / "render_video.py", plan, Path(tmp) / "out.mp4"], tmp,
                     env={"FACTORY_ROOT": str(root)})
            assert r.returncode == 4, (r.returncode, r.stdout[-2000:], r.stderr[-2000:])
            assert "not rendered" in r.stdout and "no QC" in r.stdout, r.stdout
            rec = json.loads(score_log.refusal_path(plan).read_text())
            assert rec["reason_code"] == "score_below_threshold" and rec["script_id"] == "s1"
            assert not (Path(tmp) / "out.mp4").exists()


# --------------------------------------------------------------------------
# qc_render.py with no video
# --------------------------------------------------------------------------

def _plain_plan(tmp):
    plan = Path(tmp) / "plan.json"
    plan.write_text(json.dumps({"style": "motion", "blocks": [],
                                "audio": {"duration": 2.0, "src": "voice.wav"},
                                "output": {"width": 1080, "height": 1920, "fps": 25}}))
    return plan


def _clean(r):
    both = r.stdout + r.stderr
    assert "Traceback" not in both and "KeyError" not in both, both[-3000:]


def test_qc_on_a_missing_video_is_a_sentence_and_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        plan = _plain_plan(tmp)
        missing = Path(tmp) / "videos" / "street-fighter.mp4"
        r = _run([SCRIPTS / "qc_render.py", missing, plan], tmp)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr[-2000:])
        _clean(r)
        assert f"no video at {missing}" in r.stderr, r.stderr
        r = _run([SCRIPTS / "qc_render.py", missing, plan, "--json"], tmp)
        assert r.returncode == 2
        _clean(r)
        res = json.loads(r.stdout)
        assert res["passed"] is False and res["error"] == "no_video", res
        assert str(missing) in res["failures"][0]


def test_qc_on_an_unreadable_video_is_a_sentence_and_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        plan = _plain_plan(tmp)
        for name, data in (("empty.mp4", b""), ("junk.mp4", b"not a video at all\n" * 50)):
            bad = Path(tmp) / name
            bad.write_bytes(data)
            r = _run([SCRIPTS / "qc_render.py", bad, plan], tmp)
            assert r.returncode == 2, (name, r.returncode, r.stdout, r.stderr[-2000:])
            _clean(r)
            assert str(bad) in r.stderr, r.stderr


def test_qc_on_a_video_the_score_refused_before_the_render_exits_4_with_the_refusal():
    if _skip():
        return
    with P.pinned() as root:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plain_plan(tmp)
            score_log.record(plan, score_log.STAGE_PLAN, _under_n(), script_id="s1")
            before = score_log.path_for(plan).read_text()
            r = _run([SCRIPTS / "qc_render.py", Path(tmp) / "never.mp4", plan], tmp,
                     env={"FACTORY_ROOT": str(root)})
            assert r.returncode == 4, (r.returncode, r.stdout, r.stderr[-2000:])
            _clean(r)
            assert "refused before the render" in r.stdout, r.stdout
            assert score_log.refusal_path(plan).exists()
            # nothing recorded: the log keeps its plan stage only
            assert score_log.path_for(plan).read_text() == before


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
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

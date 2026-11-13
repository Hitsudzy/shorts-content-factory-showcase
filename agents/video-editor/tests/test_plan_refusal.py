#!/usr/bin/env python3
"""CF-0254: a video refused before the render leaves a record, not a silence.

Every gate of `build_render_plan.py` that refuses a whole plan used to end on
stderr and exit 2, and the stage's convention said a refused video therefore
has no entry in 05-video-editor.json at all - so for a batch whose only script
was refused the file was never written. Batch `example-film/2026-09-16T2148Z` is
that batch: one script (`lf-2026-09-16-005-script1`), refused at the source
badge gate because `stroudtimes.com` is in neither list (CF-0166), and the
root's funnel reads it as `unexplained` 1 / SILENT 1 - the one outcome DoD
1.4.4 item 1 forbids. The refusal was in RUN_EVENTS; the funnel reads
artifacts.

What is pinned here:

- the codes this stage writes are all in the root's `funnel.FUNNEL_CODES`
  (skipped, loudly, when the factory root is not reachable from this checkout);
- every gate that refuses a plan goes through `refuse_plan()` - no `sys.exit`
  in `build_render_plan.py` prints "plan not written" on its own any more, and
  every gate id in `plan_refusal.GATE_CODES` is used by one;
- a refusal writes a sidecar beside where the plan would have been, carrying
  `{script_id, reason_code, reason}` with the gate's own sentence, and the
  gate's stderr is unchanged above it;
- `write_batch_metadata.py` runs with zero videos, finds the sidecars by
  itself, and writes `05-video-editor.json` with `refusals[]` and `videos: []`;
- an ordinary video is unaffected: `refusals[]` is `[]` and the record is what
  it always was;
- a script that has a video record is not also refused - a refusal from the
  attempt that was retried is dropped, and said out loud;
- with neither videos nor refusals the call is an error, not an empty file;
- and the whole point, end to end: the root's funnel, over a batch built from
  these artifacts, reports the loss under this stage's code with this stage's
  sentence, `unexplained` 0 and SILENT gone.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
FACTORY_ROOT = next((a for a in AGENT_ROOT.parents
                     if (a / "shared" / "runlog" / "funnel.py").is_file()), None)

# CF-0107: never let this file's runs write accounting into a real batch.
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0254-runlog-")))

sys.path.insert(0, str(SCRIPTS))
import plan_refusal  # noqa: E402
import write_batch_metadata as wbm  # noqa: E402

DEST = "05-video-editor.json"


def _funnel():
    """shared/runlog/funnel.py of the factory root, loaded by path (it is not
    on any import path from this repo, and it inserts its own directory for
    the `runlog` beside it)."""
    path = FACTORY_ROOT / "shared" / "runlog" / "funnel.py"
    spec = importlib.util.spec_from_file_location("funnel_for_cf0254", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plan():
    """The smallest plan video_record() accepts, with no layers switched on."""
    return {"style": "motion", "blocks": [], "duration": {"total": 12.0, "blocks": 0},
            "audio": {"duration": 12.0}, "output": {"width": 1080, "height": 1920}}


def _batch(tmp, channel="example-film", batch="b1"):
    b = Path(tmp) / "pipeline" / channel / batch
    (b / "work").mkdir(parents=True)
    return b


def _video(batch_dir, script_id):
    work = batch_dir / "work" / script_id
    work.mkdir(parents=True, exist_ok=True)
    p = work / "plan.json"
    p.write_text(json.dumps(_plan()))
    return [script_id, str(p), str(batch_dir / "videos" / f"{script_id}.mp4")]


def _refusal(batch_dir, script_id, gate=plan_refusal.GATE_SOURCE_BADGE, reason=None):
    """What a gate leaves behind: <batch>/work/<slug>/plan.refusal.json."""
    work = batch_dir / "work" / script_id
    work.mkdir(parents=True, exist_ok=True)
    return plan_refusal.write(work / "plan.json", script_id, gate,
                              reason or "SOURCE BADGE NOT PLANNED: comparison line: host "
                                        "'stroudtimes.com' is in neither list")


def _write(batch_dir, *videos, refusals=(), replace_all=False):
    """One call of write_batch_metadata.main(), in process, with qc stubbed.
    Returns (stdout, stderr); a call that exits raises SystemExit."""
    argv = ["write_batch_metadata.py", str(batch_dir)]
    for v in videos:
        argv += ["--video"] + list(v)
    for r in refusals:
        argv += ["--refusal", str(r)]
    if replace_all:
        argv.append("--replace-all")
    out, err = io.StringIO(), io.StringIO()
    real_qc, real_argv = wbm.qc_report, sys.argv
    wbm.qc_report = lambda video, plan: {"passed": True, "failures": [], "notes": [],
                                         "measured": {}}
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            wbm.main()
    finally:
        wbm.qc_report, sys.argv = real_qc, real_argv
    return out.getvalue(), err.getvalue()


def _read(batch_dir):
    return json.loads((batch_dir / DEST).read_text())


# --------------------------------------------------------------------------
# the contract with the root
# --------------------------------------------------------------------------

def test_every_code_this_stage_writes_is_in_the_root_vocabulary():
    """`FUNNEL_CODES` lives in the factory root and this repo may not widen it:
    a stage writing a code the root does not know is printed by the funnel as
    a contract to fix. GATE_CODES is the whole of what we write."""
    if FACTORY_ROOT is None:
        print("  (factory root not reachable from this checkout - vocabulary check skipped)")
        return
    codes = _funnel().FUNNEL_CODES
    for gate, code in sorted(plan_refusal.GATE_CODES.items()):
        assert code in codes, f"{gate} writes {code!r}, which is not in funnel.FUNNEL_CODES"


# CF-0282: the scripts of this stage that may refuse a script outright. Two of
# them refuse *before* a plan exists (the anchor preflight before the TTS, the
# narration ceiling on the finished wav) and are gates of the same kind - a
# decision about a script, taken by this stage, owed a record.
REFUSING_SCRIPTS = ("build_render_plan.py", "script_anchors.py", "narration_length.py",
                    "score_log.py")  # CF-0434: the early stop on the score


def test_every_gate_that_refuses_a_script_goes_through_plan_refusal():
    """The wiring, read off the source: no gate prints its own "plan not
    written" headline any more, and every gate id has a caller in one of the
    refusing scripts. A gate added later that forgets the record fails here
    rather than in a batch."""
    src = (SCRIPTS / "build_render_plan.py").read_text()
    headline = "plan not written:"
    for line in src.splitlines():
        if headline in line and "print(" in line:
            assert "{headline} - plan not written:" in line, (
                f"a gate still prints its own refusal headline: {line.strip()}")
    sources = {name: (SCRIPTS / name).read_text() for name in REFUSING_SCRIPTS}
    consts = {k: v for k, v in vars(plan_refusal).items()
              if k.startswith("GATE_") and k != "GATE_CODES"}
    assert set(consts.values()) == set(plan_refusal.GATE_CODES), consts
    for const in consts:
        users = [n for n, s in sources.items() if f"plan_refusal.{const}" in s]
        assert users, (f"no gate in {list(REFUSING_SCRIPTS)} uses {const} - a gate id "
                       f"with no caller is a refusal nothing writes")


def test_the_record_carries_the_three_keys_the_funnel_reads():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        path = Path(_refusal(b, "s1"))
        assert path.name == "plan.refusal.json", path
        rec = json.loads(path.read_text())
        assert rec["script_id"] == "s1"
        assert rec["reason_code"] == plan_refusal.HELD_BACK
        assert "stroudtimes.com" in rec["reason"]
        assert rec["gate"] == plan_refusal.GATE_SOURCE_BADGE and rec["at"]


def test_the_reason_is_one_self_contained_line():
    """The funnel prints it in a table cell, beside a code and nothing else."""
    text = plan_refusal.reason_text("TWO-SOURCE GATE FAILED",
                                    ["1/2 independent source(s)", "canonical:\n  abc"])
    assert text == ("TWO-SOURCE GATE FAILED: 1/2 independent source(s); canonical: abc"), text
    assert "\n" not in text


def test_a_gate_of_the_plan_builder_writes_it():
    """The real call site: refuse_plan() prints what the gate always printed,
    writes the record beside where the plan would have been, and exits."""
    import argparse
    import build_render_plan
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        work = b / "work" / "lf-2026-09-16-005-script1"
        work.mkdir(parents=True)
        args = argparse.Namespace(output=str(work / "plan.json"),
                                  script_id="lf-2026-09-16-005-script1")
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                build_render_plan.refuse_plan(
                    args, plan_refusal.GATE_SOURCE_BADGE, "SOURCE BADGE NOT PLANNED",
                    ["comparison line: host 'stroudtimes.com' is in neither list"],
                    notes=["the badge names the publication (CF-0166)."],
                    exit_code=3)
        except SystemExit as e:
            assert e.code == 3, e.code
        else:
            raise AssertionError("refuse_plan() returned instead of exiting")
        text = err.getvalue()
        assert "SOURCE BADGE NOT PLANNED - plan not written:" in text, text
        assert "stroudtimes.com" in text and "CF-0166" in text
        assert "refusal -> " in text and "held_back" in text
        rec = json.loads((work / "plan.refusal.json").read_text())
        assert rec["script_id"] == "lf-2026-09-16-005-script1"
        assert rec["reason"].startswith("SOURCE BADGE NOT PLANNED: comparison line:")


# --------------------------------------------------------------------------
# the batch artifact
# --------------------------------------------------------------------------

def test_a_batch_with_no_video_at_all_still_writes_the_file():
    """The defect: `write_batch_metadata.py` needed a plan and an mp4, a
    refused video has neither, so the file did not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _refusal(b, "lf-2026-09-16-005-script1")
        out, err = _write(b)
        doc = _read(b)
        assert doc["videos"] == []
        assert [r["script_id"] for r in doc["refusals"]] == ["lf-2026-09-16-005-script1"]
        r = doc["refusals"][0]
        assert r["reason_code"] == plan_refusal.HELD_BACK
        assert "stroudtimes.com" in r["reason"]
        assert "0 video(s), 1 refusal(s)" in out, out
        assert "REFUSED (no video): lf-2026-09-16-005-script1" in err, err
        assert doc["batch_id"] == "b1" and doc["channel"] == "example-film"
        assert doc["merge_log"][-1]["refusals"] == ["lf-2026-09-16-005-script1"]


def test_an_ordinary_video_is_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _, err = _write(b, _video(b, "s1"))
        doc = _read(b)
        assert [v["script_id"] for v in doc["videos"]] == ["s1"]
        assert doc["refusals"] == []
        assert "METADATA: merged 0 existing + 1 written (0 replaced)" in err, err
        assert "REFUSED" not in err


def test_a_refusal_and_a_video_live_in_one_file():
    """Two scripts, one refused and one built - the ordinary mixed batch."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _refusal(b, "s1", gate=plan_refusal.GATE_TWO_SOURCE,
                 reason="TWO-SOURCE GATE FAILED: 1/2 independent source(s)")
        _write(b, _video(b, "s2"))
        doc = _read(b)
        assert [v["script_id"] for v in doc["videos"]] == ["s2"]
        assert [r["script_id"] for r in doc["refusals"]] == ["s1"]
        assert doc["refusals"][0]["reason_code"] == plan_refusal.NO_SECOND_SOURCE


def test_a_video_wins_over_a_stale_refusal_of_the_same_script():
    """A rejected asset refuses the attempt; the caller retries with another
    candidate and the video comes out. The sidecar is still on disk, and the
    file must not say both."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _refusal(b, "s1", gate=plan_refusal.GATE_ASSETS_REJECTED,
                 reason="ASSETS REJECTED: block 0: a.mp4 - too dark")
        _, err = _write(b)
        assert len(_read(b)["refusals"]) == 1
        _, err = _write(b, _video(b, "s1"))
        doc = _read(b)
        assert [v["script_id"] for v in doc["videos"]] == ["s1"]
        assert doc["refusals"] == []
        assert "refusal dropped: s1" in err, err


def test_a_refusal_survives_the_next_call_for_another_video():
    """CF-0030's promise, for the other list: one call per video, and the
    refusal recorded two calls ago is still there."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _refusal(b, "s1")
        _write(b)
        _write(b, _video(b, "s2"))
        _write(b, _video(b, "s3"))
        doc = _read(b)
        assert [v["script_id"] for v in doc["videos"]] == ["s2", "s3"]
        assert [r["script_id"] for r in doc["refusals"]] == ["s1"]


def test_a_named_refusal_outside_the_batch_is_read():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        elsewhere = Path(tmp) / "elsewhere"
        elsewhere.mkdir()
        path = plan_refusal.write(elsewhere / "plan.json", "s9",
                                  plan_refusal.GATE_END_CARD, "END CARD NOT PLANNED: no stance")
        _write(b, refusals=[path])
        assert [r["script_id"] for r in _read(b)["refusals"]] == ["s9"]


def test_neither_a_video_nor_a_refusal_is_an_error():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                _write(b)
        except SystemExit as e:
            assert e.code == 2, e.code
        else:
            raise AssertionError("an empty call wrote a file instead of stopping")
        assert not (b / DEST).exists()


# --------------------------------------------------------------------------
# what the root sees
# --------------------------------------------------------------------------

def _batch_of_2026_09_16(tmp, with_refusal):
    """The shape of `example-film/2026-09-16T2148Z`: one topic, cleared, two
    sources, one script, and the Editor refusing it at the source badge."""
    b = _batch(tmp, batch="2026-09-16T2148Z")
    sid = "lf-2026-09-16-005-script1"
    (b / "01-trend-hunter.json").write_text(json.dumps(
        {"channel": "example-film", "topics": [{"topic_id": "t5"}]}))
    (b / "02-compliance-checker.json").write_text(json.dumps(
        {"results": [{"topic_id": "t5", "verdict": "clear"}]}))
    (b / "01b-footage-index.json").write_text(json.dumps(
        {"sources_by_topic": {"t5": ["vid-a", "vid-b"]}}))
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"scripts": [{"topic_id": "t5", "script_id": sid}]}))
    (b / "04-compliance-checker.json").write_text(json.dumps(
        {"results": [{"script_id": sid, "verdict": "clear"}]}))
    if with_refusal:
        _refusal(b, sid)
        _write(b)
    return b, sid


def test_the_funnel_stops_calling_it_unexplained():
    """End to end, and the reason this task exists: the same batch shape the
    funnel read as `unexplained` 1 / SILENT 1 now carries this stage's code and
    this stage's sentence."""
    if FACTORY_ROOT is None:
        print("  (factory root not reachable from this checkout - funnel check skipped)")
        return
    funnel = _funnel()
    with tempfile.TemporaryDirectory() as tmp:
        before, sid = _batch_of_2026_09_16(tmp, with_refusal=False)
        f = funnel.funnel(before)
        assert f["silent"] is True and len(f["unexplained"]) == 1, f["losses"]

        after, _ = _batch_of_2026_09_16(tmp + "/after", with_refusal=True)
        f = funnel.funnel(after)
        assert f["silent"] is False, f["unexplained"]
        assert f["unexplained"] == [] and f["unknown_codes"] == []
        assert f["losses"] == {plan_refusal.HELD_BACK: 1}, f["losses"]
        ready = [s for s in f["steps"] if s["step"] == "ready"][0]
        assert [x["item"] for x in ready["lost"]] == [sid]
        assert "stroudtimes.com" in ready["lost"][0]["reason"]
        assert ready["lost"][0]["stage"] == DEST


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

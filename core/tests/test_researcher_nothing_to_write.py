#!/usr/bin/env python3
"""CF-0763..0766: a batch that hands the Content Researcher no topic still
leaves `03-content-researcher.json`, and the stop-cock closes it there.

example-tech/2026-10-16T0702Z: Trend Hunter wrote 0 topics, compliance carried
0, the indexer fetched nothing, and the Researcher closed by its SKILL's
`empty_shortlist_close` without `03`. Without `03` the stop-cock reads
`not_reached` and stops nothing, so compliance-scripts, the Editor and the
frame judge each ran on nothing and closed without its file - the triage filed
four broken contracts for one empty shelf. The fix is a writer (the CF-0707
shape): the plan's machine stage `content-researcher-empty` runs
`scripts/researcher_nothing_to_write.py` exactly when `nothing_to_write`
holds, and the LLM stage `content-researcher` runs only on
`write_candidates`. Tested here on fixture batches shaped like 0702Z in a temp
dir (no live batch is read):

* the script writes `03` with `scripts: []` and the sentence, and it passes
  the `03` contract; it refuses a batch with a topic to write and never
  overwrites a `03`;
* the two conditions are complements; a missing `02`/`01b` leaves the
  Researcher's own stage to say so; a substituted or sourced topic is
  something to write;
* the stop-cock reads `stop` on the written file (so every later stage is
  skipped by its own `when`), the funnel renders it, and the triage finds no
  broken contract for the stage's close;
* the plans of every channel put the writer right after the LLM stage, under
  the conditions, with the reserve loop after it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("researcher-empty-test-")
os.environ["RUNLOG_BATCH"] = str(TMP / "events")
(TMP / "events").mkdir()

import funnel                                                        # noqa: E402
import researcher_nothing_to_write as writer                         # noqa: E402
import run_checks                                                    # noqa: E402
import run_plan as rp                                                # noqa: E402
import stopcock                                                      # noqa: E402
import triage                                                        # noqa: E402

SCRIPT = ROOT / "scripts" / "researcher_nothing_to_write.py"
CHANNELS = ("example-film", "example-science", "example-tech")
CR = "03-content-researcher.json"
_n = [0]


def batch(results=(), reserve=(), sources=None, skipped_topics=(), subs=None,
          with_02=True, with_01b=True):
    """A batch shaped like example-tech/2026-10-16T0702Z: 01 with no topic,
    02 with an empty cut, 01b with nothing fetched."""
    _n[0] += 1
    b = TMP / "example-tech" / f"2026-10-16T07{_n[0]:02d}Z"
    b.mkdir(parents=True)
    (b / "01-trend-hunter.json").write_text(json.dumps(
        {"batch_id": b.name, "channel": "example-tech", "topics": [],
         "skipped_topics": [{"topic_id": "lf-x-001", "reason_code": "no_fact",
                             "reason": "no fact"}]}))
    if with_02:
        (b / "02-compliance-checker.json").write_text(json.dumps(
            {"batch_id": b.name, "channel": "example-tech", "results": list(results),
             "reserve": list(reserve)}))
    if with_01b:
        idx = {"batch": str(b), "fetched": [], "sources_by_topic": sources or {},
               "skipped_topics": list(skipped_topics), "failed": []}
        if subs is not None:
            idx[funnel.SUBSTITUTION_KEY] = subs
        (b / "01b-footage-index.json").write_text(json.dumps(idx))
    return b


def run(b, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--batch", str(b), *args],
                          capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, RUNLOG_BATCH=str(b)))


def _03(b):
    p = b / CR
    return json.loads(p.read_text()) if p.is_file() else None


# --------------------------------------------------------------------------
# the writer

def test_the_writer_writes_the_empty_record_of_a_batch_with_nothing_to_write():
    b = batch()
    r = run(b)
    assert r.returncode == 0, r.stderr
    d = _03(b)
    assert d is not None, "no 03 written"
    assert d["scripts"] == [] and d["skipped"] == [], d
    assert d["batch_id"] == b.name and d["channel"] == "example-tech", d
    why = d[writer.NOTE_KEY]
    assert why.startswith("nothing to write") and "0 result(s)" in why, why
    # the pipeline contract of 03 (tests/test_pipeline_contracts.py test_content_researcher_stage)
    for k in ("batch_id", "scripts"):
        assert k in d, k


def test_the_writer_refuses_a_batch_with_a_topic_to_write():
    b = batch(results=[{"topic_id": "t1", "verdict": "clear"}], sources={"t1": ["v1", "v2"]})
    r = run(b)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "refused" in r.stderr and "t1" in r.stderr, r.stderr
    assert _03(b) is None, "the refusal wrote a 03"


def test_the_writer_never_overwrites_a_03():
    b = batch()
    (b / CR).write_text(json.dumps({"batch_id": b.name, "scripts": [{"script_id": "s"}]}))
    r = run(b)
    assert r.returncode == 2 and "already there" in r.stderr, (r.returncode, r.stderr)
    assert _03(b)["scripts"] == [{"script_id": "s"}]


def test_the_check_flag_answers_without_writing():
    b = batch()
    r = run(b, "--check")
    assert r.returncode == 0 and r.stdout.startswith("nothing_to_write: yes"), r.stdout
    assert _03(b) is None
    r = run(batch(results=[{"topic_id": "t1", "verdict": "review"}]), "--check")
    assert r.returncode == 1 and r.stdout.startswith("nothing_to_write: no"), r.stdout


# --------------------------------------------------------------------------
# the conditions

def test_the_conditions_are_complements():
    for b, empty in ((batch(), True),
                     (batch(results=[{"topic_id": "t1", "verdict": "caution"}]), False),
                     (batch(with_02=False), False), (batch(with_01b=False), False)):
        n, w = run_checks.check("nothing_to_write", b), run_checks.check("write_candidates", b)
        assert n[0] is empty and w[0] is (not empty), (b, n, w)


def test_a_missing_input_leaves_the_researchers_own_stage_to_say_so():
    holds, why = run_checks.check("write_candidates", batch(with_01b=False))
    assert holds is True and "01b-footage-index.json" in why, why


def test_only_a_production_verdict_dropped_by_the_indexer_is_nothing():
    """A blocked row is not handed over; a clear row the indexer skipped is
    not either; a substituted topic or any topic with sources is."""
    assert run_checks.check("nothing_to_write", batch(
        results=[{"topic_id": "t1", "verdict": "blocked"}]))[0] is True
    assert run_checks.check("nothing_to_write", batch(
        results=[{"topic_id": "t1", "verdict": "clear"}],
        skipped_topics=[{"topic_id": "t1", "reason_code": "no_source"}]))[0] is True
    assert run_checks.check("nothing_to_write", batch(
        subs={"substitutions": [{"topic_id": "r1", "replaced": "t1", "outcome": "sources"}],
              "remaining": []}))[0] is False
    assert run_checks.check("nothing_to_write", batch(sources={"t9": ["v1"]}))[0] is False


def test_the_conditions_are_named_in_the_plan_vocabulary():
    for name in ("write_candidates", "nothing_to_write"):
        assert name in rp.CONDITIONS and name in run_checks.CHECKS, name


# --------------------------------------------------------------------------
# the readers: the stop-cock closes the batch, nothing is an accident

def test_the_stopcock_reads_stop_on_the_written_record():
    b = batch()
    assert stopcock.verdict(b)["state"] == stopcock.NOT_REACHED   # the 0702Z state
    assert run(b).returncode == 0
    v = stopcock.verdict(b)
    assert v["state"] == stopcock.STOP and v["scripts"] == 0, v


def test_the_funnel_and_the_triage_read_the_empty_record():
    b = batch()
    assert run(b).returncode == 0
    f = funnel.funnel(b)
    assert not f["errors"] and not f["unexplained"], f
    funnel.render(f)                                     # renders without raising
    f["_dir"] = str(b)
    events = [{"kind": "marker", "stage": "content-researcher", "status": "stage-start"},
              {"kind": "marker", "stage": "content-researcher", "status": "stage-done",
               "note": "0 eligible topics, no scripts written"}]
    found = [i for i in triage.artifact_incidents(events, f) if i["kind"] == triage.CONTRACT]
    assert found == [], found


# --------------------------------------------------------------------------
# the plans

def _conds(st):
    w = st.get("when")
    return w if isinstance(w, list) else [w]


def test_every_plan_writes_the_empty_record_after_the_researcher():
    for ch in CHANNELS:
        plan = rp.load(ch, ROOT)
        assert rp.validate(plan, ROOT, skip_missing_checkouts=True) == [], ch
        by_id = {s["id"]: s for s in plan["stages"]}
        order = rp.order(plan)
        i = order.index("content-researcher-empty")
        assert order[i - 1] == "content-researcher", (ch, order)
        # the empty record is on disk before anything reads 03 for the reserve:
        # CF-0882's supply from below the shortlist (shared/below_shortlist.py
        # need() reads 03's refusals) and then the reserve indexer
        assert order[i + 1] == "reserve-below-shortlist", (ch, order)
        assert order[i + 2] == "footage-indexer-reserve", (ch, order)
        empty, cr = by_id["content-researcher-empty"], by_id["content-researcher"]
        assert empty["kind"] == "machine" and empty["marker"] == "content-researcher", ch
        assert empty["marker_by"] == "executor", ch
        assert {"check": "nothing_to_write"} in _conds(empty), ch
        assert {"check": "write_candidates"} in _conds(cr), ch
        argv = empty["steps"][0]["argv"]
        assert argv[1] == "{root}/scripts/researcher_nothing_to_write.py", argv
        assert cr["produces"] == [CR] and "produces" not in empty, ch
        note = empty["steps"][0]["note_on_exit"]["0"]
        assert note.startswith(writer.CLOSE_NOTE), note
        # a rewrite / rerun from the Researcher runs the writer too
        if "rewrite" in rp.rebuild_modes(plan):
            assert "content-researcher-empty" in rp.rebuild_layout(plan, "rewrite")["run"], ch


def test_the_plan_step_writes_03_on_the_fixture_batch():
    """The step's argv as the executor expands it, run on the fixture."""
    plan = rp.load("example-tech", ROOT)
    step = next(s for s in plan["stages"] if s["id"] == "content-researcher-empty")["steps"][0]
    b = batch()
    argv = [sys.executable if a == "python3" else
            a.replace("{root}", str(ROOT)).replace("{batch}", str(b)) for a in step["argv"]]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, RUNLOG_BATCH=str(b)))
    assert r.returncode == 0, r.stderr
    assert _03(b)["scripts"] == []


# --------------------------------------------------------------------------
# the triage: one empty upstream is one task, not one per stage after it

def _close(stage, note):
    return [{"kind": "marker", "stage": stage, "status": "stage-start"},
            {"kind": "marker", "stage": stage, "status": "stage-done", "note": note}]


CASCADE_0702Z = (
    _close("compliance-checker", "0 verdicts, 0 blocked (after 01-trend-hunter; shortlist empty)")
    + _close("content-researcher", "0 eligible topics, no scripts written")
    + _close("compliance-checker", "0 verdicts, 0 blocked (no 03-content-researcher.json: "
             "compliance-shortlist carried 0 topics, content-researcher wrote no scripts)")
    + _close("video-editor", "0 videos rendered, 0 refused, 0 needs-you, 0 attempts - no "
             "03-content-researcher.json: content-researcher wrote no scripts")
    + _close("frame-judge", "0 video(s) judged: no 05-video-editor.json in the batch (editor "
             "rendered 0 videos, content-researcher wrote no scripts)"))


def _contracts(b, events):
    f = funnel.funnel(b)
    f["_dir"] = str(b)
    return triage._merge([i for i in triage.artifact_incidents(events, f)
                          if i["kind"] == triage.CONTRACT])


def test_the_0702Z_cascade_is_one_broken_contract_at_the_researcher():
    b = batch()                     # 01, 02, 01b; the Researcher wrote no 03 (pre-fix)
    found = _contracts(b, CASCADE_0702Z)
    assert len(found) == 1, found
    one = found[0]
    assert one["key"] == "contract:missing:03-content-researcher.json", one
    assert one["stage"] == "content-researcher" and one["count"] == 4, one
    assert "without writing 03-content-researcher.json" in one["detail"], one
    assert "compliance-checker, video-editor, frame-judge" in one["detail"], one


def test_a_stage_that_had_its_input_and_wrote_nothing_is_still_its_own():
    """The note names 03 missing, but 03 is there: the Editor's own break."""
    b = batch()
    (b / CR).write_text(json.dumps({"batch_id": b.name, "scripts": [], "skipped": []}))
    found = _contracts(b, _close("video-editor", "no 03-content-researcher.json: nothing"))
    assert [i["key"] for i in found] == ["contract:missing:05-video-editor.json"], found
    assert found[0]["stage"] == "video-editor", found


def test_the_judge_on_an_editor_that_broke_itself_merges_into_the_editors_task():
    b = batch()
    (b / CR).write_text(json.dumps({"batch_id": b.name, "scripts": [], "skipped": []}))
    found = _contracts(b, _close("video-editor", "rendered 0") + _close(
        "frame-judge", "0 video(s) judged: no 05-video-editor.json in the batch"))
    assert len(found) == 1 and found[0]["key"] == "contract:missing:05-video-editor.json", found
    assert found[0]["stage"] == "video-editor" and found[0]["count"] == 2, found
    assert "frame-judge" in found[0]["detail"], found


def test_after_the_fix_the_0702Z_batch_files_nothing():
    """With the writer's 03 the stop-cock reads stop, the stages after the
    Researcher do not run (no markers), and the triage finds no contract."""
    b = batch()
    assert run(b).returncode == 0
    events = CASCADE_0702Z[:4]                       # up to the Researcher's close
    assert _contracts(b, events) == []


if __name__ == "__main__":
    import inspect
    tests = [(n, fn) for n, fn in sorted(globals().items())
             if n.startswith("test_") and inspect.isfunction(fn)]
    failed = 0
    for n, fn in tests:
        try:
            fn()
            print(f"ok   {n}")
        except Exception as e:                                   # noqa: BLE001
            failed += 1
            print(f"FAIL {n}: {e.__class__.__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

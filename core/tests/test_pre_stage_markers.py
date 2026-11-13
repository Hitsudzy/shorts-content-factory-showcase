#!/usr/bin/env python3
"""CF-0173: the pre-stage block gets a name.

In run `2026-09-09T2031Z` the 1 h 56 m between `batch-start` and the first
`stage-start` was 46.6 % of the wall clock and carried no stage marker at all,
so sections 1, 4 and 5 of RUN_SUMMARY.md - the three that split the run by
stage - dissolved it into `between`. Measured here: that block is one kind of
work, `remeasure_captions.py` (4769 s) and `remeasure_usability.py` (1581 s)
over 42 sources of the pool, and it does not depend on the topics of the batch.

Three things have to hold, and each is a test below:

1. the block lands in sections 1, 4 and 5 under `pool-maintenance`;
2. a `pool-maintenance` that found the pool fresh - the 1.3 s check of CF-0151
   and no more - is a **zero**, not a silence: a stage that costs nothing must
   not read like a stage that never ran, or the day CF-0099 empties it nobody
   can tell the difference;
3. a run recorded before this change still summarises, and both its summary and
   its row in the cumulative table say it was marked up the old way - otherwise
   a comparison of the per-stage columns across the change lies.

Everything runs on synthetic events in a temp root: FACTORY_ROOT and
RUNLOG_STATE_DIR point there, so the real pipeline/runs.jsonl is never touched.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("pre-stage-test-")
FAKE_ROOT = TMP / "root"
(FAKE_ROOT / "pipeline").mkdir(parents=True)
os.environ["FACTORY_ROOT"] = str(FAKE_ROOT)
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)
os.environ.pop("RUNLOG_STAGE", None)

import runlog  # noqa: E402
import runs_table  # noqa: E402
import summary  # noqa: E402

T0 = runlog.parse_z("2026-09-09T20:31:55Z")
POOL = runlog.S_POOL_MAINTENANCE
_n = [0]


# --------------------------------------------------------------------------
# events

def ev(off, kind, stage=None, status=None, **kw):
    e = {"ts": runlog.now_z(T0 + off), "machine": "m", "kind": kind, "stage": stage, "video": None,
         "step": None, "attempt": None, "status": status, "params": None, "duration_s": None,
         "pid": 1, "id": None, "parent": None}
    e.update(kw)
    return e


def header(markup=runlog.MARKUP):
    h = {"batch": "legacy-film/x", "version": "1.4",
         "git": {"root": {"commit": "abcdef0123", "dirty": False}},
         "models": {"operator": "claude-opus-5", "subagent_default": None, "subagents": None},
         "counts": {"videos": 2}, "machine": {"cpu": "Apple M2", "ram_gb": 16}}
    if markup is not None:
        h["markup"] = markup
    return h


def script(a, b, stage, step, video=None, eid=None):
    eid = eid or f"s{a}-{step}-{video}"
    return [ev(a, "script", stage, "start", step=step, video=video, id=eid),
            ev(b, "script", stage, "done", step=step, video=video, id=eid, duration_s=float(b - a))]


def limits(off, five, seven):
    return ev(off, "limits", None, params={"five_hour": {"used_percentage": five},
                                           "seven_day": {"used_percentage": seven}})


def usage_row(off, stage, calls=10, tokens=1000):
    return ev(off, "usage", stage, model="claude-opus-5", role="operator", calls=calls,
              usage={"input": tokens, "cache_write": 0, "cache_read": 0, "output": 0, "thinking": 0},
              computed=runlog.now_z(T0 + 9999))    # one generation: read_usage keeps only the newest


def a_run(pool_a=60, pool_b=7000, markup=runlog.MARKUP, pool_work=True, pool_tokens=True):
    """The shape of the real run: a long pool block before the first agent stage,
    then trend-hunter. `pool_work=False` is the pool that was already fresh."""
    out = [ev(0, "marker", None, "batch-start", header=header(markup)), limits(1, 1.0, 0.5)]
    if markup is not None and markup >= runlog.MARKUP:
        out.append(ev(pool_a, "marker", POOL, "stage-start"))
    if pool_work:
        # the two scripts the block is actually made of, relabelled by RUNLOG_STAGE
        stage = POOL if (markup or 0) >= runlog.MARKUP else "footage-indexer"
        out += script(pool_a + 5, pool_a + 4800, stage, "remeasure-captions", video="v1")
        out += script(pool_a + 4810, pool_b - 10, stage, "remeasure-usability", video="v1")
        if pool_tokens:
            out.append(usage_row(pool_a + 100, stage if (markup or 0) >= runlog.MARKUP else "between"))
    if markup is not None and markup >= runlog.MARKUP:
        out.append(ev(pool_b, "marker", POOL, "stage-done"))
    out += [limits(pool_b + 1, 2.0, 0.9),
            ev(pool_b + 10, "marker", "trend-hunter", "stage-start")]
    out += script(pool_b + 20, pool_b + 500, "trend-hunter", "hunt")
    out += [usage_row(pool_b + 100, "trend-hunter"),
            limits(pool_b + 600, 9.0, 3.5),
            ev(pool_b + 600, "marker", "trend-hunter", "stage-done"),
            ev(pool_b + 610, "marker", None, "batch-done")]
    return out


def a_batch(events):
    _n[0] += 1
    b = FAKE_ROOT / "pipeline" / "legacy-film" / f"b{_n[0]}"
    b.mkdir(parents=True)
    import json
    (b / runlog.EVENTS_FILE).write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return b


# --------------------------------------------------------------------------
# 1. the block has a name in sections 1, 4 and 5

def test_the_pre_stage_block_is_its_own_stage_in_sections_1_4_and_5():
    c = summary.compute(a_batch(a_run()))
    s1 = {w["stage"]: w for w in c["times"]["stages"]}
    assert POOL in s1, sorted(s1)
    assert s1[POOL]["wall_s"] > 6000, s1[POOL]           # the block, not a sliver of it
    assert s1[POOL]["scripts"] == 2, s1[POOL]            # both remeasure scripts inside it
    assert POOL in c["tokens"]["by_stage"], sorted(c["tokens"]["by_stage"])
    assert POOL in c["windows"]["stages"], sorted(c["windows"]["stages"])
    assert c["windows"]["stages"][POOL]["five_hour"] is not None, c["windows"]["stages"]


def test_the_block_no_longer_falls_into_between():
    """The whole defect in one assertion: the same work, marked up, stops being
    `between`. `between` is what CF-0168 attributes honestly when no stage is
    open - the fix is to open one, not to re-point the bucket."""
    marked = summary.compute(a_batch(a_run()))
    legacy = summary.compute(a_batch(a_run(markup=None)))
    assert marked["tokens"]["by_stage"].get("between", {"calls": 0})["calls"] == 0, \
        marked["tokens"]["by_stage"]
    assert legacy["tokens"]["by_stage"]["between"]["calls"] > 0, legacy["tokens"]["by_stage"]
    assert POOL not in legacy["times"]["stages"][0]["stage"], legacy["times"]["stages"]


def test_the_rendered_summary_names_the_stage_in_all_three_sections():
    text = summary.render(data=summary.compute(a_batch(a_run())))
    for head in ("## 1. Time by stage", "## 4. Tokens by stage", "## 5. Share of the subscription"):
        i = text.index(head)
        j = text.index("\n## ", i + 4)
        assert POOL in text[i:j], f"{head}: no {POOL} row"


# --------------------------------------------------------------------------
# 2. a stage that cost nothing is a zero, not a silence

def test_a_pool_that_was_already_fresh_is_a_zero_row_and_not_a_missing_one():
    """CF-0151 made the freshness check 1.3 s. When it says the pool is current
    the stage does nothing else - and still has to be in the sections, or the
    day CF-0099 takes this work off the critical path reads as data loss."""
    b = a_batch(a_run(pool_a=60, pool_b=61, pool_work=False))
    c = summary.compute(b)
    s1 = {w["stage"]: w for w in c["times"]["stages"]}
    assert s1[POOL]["wall_s"] <= 1.0 and s1[POOL]["scripts"] == 0, s1[POOL]
    tok = c["tokens"]["by_stage"]
    assert POOL in tok and tok[POOL]["calls"] == 0 and tok[POOL]["total"] == 0, tok
    text = summary.render(data=c)
    assert f"**= {POOL}**" in text, "section 4 dropped the stage that spent nothing"
    assert f"`= {POOL}` at zero" in text, "the zero is not explained as a zero"


def test_a_stage_that_never_ran_has_no_row_at_all():
    """The other half of the same statement: the zero row means *ran and spent
    nothing*. A stage nobody declared must stay absent, or the zero says nothing."""
    c = summary.compute(a_batch(a_run(markup=None)))
    assert POOL not in c["tokens"]["by_stage"], c["tokens"]["by_stage"]
    assert POOL not in c["windows"]["stages"], c["windows"]["stages"]


# --------------------------------------------------------------------------
# 3. the two generations of markup are told apart

def test_a_run_recorded_before_the_markers_still_summarises_and_says_so():
    c = summary.compute(a_batch(a_run(markup=None)))
    assert c["markup"] == runlog.MARKUP_LEGACY, c["markup"]
    text = summary.render(data=c)
    assert f"stage markup: generation {runlog.MARKUP_LEGACY}" in text, text[:400]
    assert "not** comparable" in text, "the old run does not warn against comparing its sections"


def test_a_run_recorded_now_says_which_generation_it_is():
    c = summary.compute(a_batch(a_run()))
    assert c["markup"] == runlog.MARKUP, c["markup"]
    assert f"stage markup: generation {runlog.MARKUP} (current)" in summary.render(data=c)


def test_the_row_of_a_run_carries_its_markup_generation():
    old = runs_table.row(a_batch(a_run(markup=None)))
    new = runs_table.row(a_batch(a_run()))
    assert old["markup"] == runlog.MARKUP_LEGACY and new["markup"] == runlog.MARKUP, (old, new)


def test_a_row_written_before_the_field_existed_reads_as_the_old_generation():
    r = runs_table.row(a_batch(a_run()))
    r.pop("markup")
    runs_table.write_tables([r], FAKE_ROOT)
    back = [x for x in runs_table.read_rows(FAKE_ROOT) if x["batch"] == r["batch"]]
    assert back and back[0]["markup"] == runlog.MARKUP_LEGACY, back


def test_the_table_warns_when_it_holds_rows_of_two_generations():
    """The point of the table is that two rows can be compared. Across a change
    of the markers the per-stage columns cannot be, and the table has to say so
    itself - a reader comparing `indexer` between these rows gets no other hint."""
    old = dict(runs_table.row(a_batch(a_run(markup=None))), batch="legacy-film/old")
    new = dict(runs_table.row(a_batch(a_run())), batch="legacy-film/new")
    mixed = runs_table.render_md([old, new])
    assert "Two generations of stage markup" in mixed, mixed[:500]
    assert "may not be compared" in mixed
    assert "stay comparable" in mixed, "the warning must also say what survives the change"
    for one in ([old], [new]):
        assert "Two generations" not in runs_table.render_md(one), "warned without a mixed table"


def test_the_markup_column_is_in_the_table_and_in_its_key():
    assert "markup" in dict(runs_table.COLUMNS), runs_table.COLUMNS
    md = runs_table.render_md([runs_table.row(a_batch(a_run()))])
    assert "| markup |" in md.replace("markup |", "markup |"), md[:600]
    assert f"| {runlog.MARKUP} |" in md, md[-600:]


def test_pool_maintenance_is_not_counted_as_footage_indexer_time():
    """`indexer_s` sums the footage-indexer windows. The pool block is that
    agent's code, but it is not that stage - if it were folded in, the column
    would jump by two hours the moment the marker appeared and the runs before
    and after would look like a regression."""
    r = runs_table.row(a_batch(a_run()))
    assert not r["indexer_s"], r["indexer_s"]


# --------------------------------------------------------------------------
# 4. RUNLOG_STAGE: how the block gets the label in the first place

def test_runlog_stage_relabels_scripts_and_children_but_never_markers():
    """`remeasure_captions.py` is footage-indexer's code and labels itself so.
    Run over the whole pool before the run it is pool-maintenance, and the
    events have to say which - the sections read the label, not the file path."""
    b = a_batch([ev(0, "marker", None, "batch-start", header=header())])
    os.environ["RUNLOG_BATCH"] = str(b)
    os.environ["RUNLOG_STAGE"] = POOL
    try:
        m = runlog.marker("stage-start", "trend-hunter", batch_dir=b, strict=False)
        s = runlog.emit(b, runlog.KIND_SCRIPT, "footage-indexer", step="remeasure-captions")
        ch = runlog.emit(b, runlog.KIND_CHILD, "footage-indexer", step="probe", tool="vision")
    finally:
        os.environ.pop("RUNLOG_STAGE", None)
        os.environ.pop("RUNLOG_BATCH", None)
    assert m["stage"] == "trend-hunter", "a marker's stage is what the operator typed"
    assert s["stage"] == POOL and ch["stage"] == POOL, (s["stage"], ch["stage"])
    plain = runlog.emit(b, runlog.KIND_SCRIPT, "footage-indexer", step="index")
    assert plain["stage"] == "footage-indexer", "the override leaked past its own process"


def test_the_stage_name_is_one_marker_and_the_sub_steps_stay_visible():
    """Why one stage and not three: the block is remeasure-captions plus
    remeasure-usability, and section 1 already breaks a stage down by `step`.
    A second and third marker pair would buy a column that is already there,
    and cost two more marker calls an operator can forget - a forgotten
    stage-done swallows everything up to batch-done."""
    c = summary.compute(a_batch(a_run()))
    w = next(x for x in c["times"]["stages"] if x["stage"] == POOL)
    assert set(w["attempts"]) == {"remeasure-captions", "remeasure-usability"}, w["attempts"]
    assert runlog.MAINTENANCE_STAGES == (POOL,), runlog.MAINTENANCE_STAGES
    assert POOL not in runlog.AGENT_NAMES, "a maintenance stage is not an agent's turn"


# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)

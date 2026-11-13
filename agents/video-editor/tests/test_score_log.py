#!/usr/bin/env python3
"""CF-0434: the score log of a video and the early stop on it.

The grill of 2026-09-29 (Q11, Q17, Q20, Q21, Q28): every stage writes its real
penalties into the video's log (`work/<slug>/plan.score.json`); as soon as they
put the video under N it goes no further. Pinned here, on the price table as it
stood before 2026-10-01 (N 60, neutral 1 - `_pinned_prices`, CF-0467) for the
arithmetic, and on the live table (`shared/gate-prices.json`) for today's N and
neutral price; skipped when the root is not reachable:

- the one-line summary, in the grill's format;
- a stage replaces itself and forgets every later stage;
- under N after a stage -> the refusal sidecar (gate `score_below_threshold`,
  code `score_below_threshold`, `supersedes_video`), back over N -> the sidecar is gone;
- a hard finding makes the tier F but is not the early stop (its own gate
  refuses, as before);
- qc_render's readings map to the model's rules;
- `record_fields()` is what 05 carries, and falls back to the plan's own score.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0434-runlog-")))
sys.path.insert(0, str(SCRIPTS))

sys.path.insert(0, str(HERE))

import _pinned_prices as P  # noqa: E402
import _score  # noqa: E402
import plan_refusal  # noqa: E402
import score_log as L  # noqa: E402

F = _score.finding


def _model():
    if _score.module() is None:
        print(f"  SKIP: {_score.error()}")
        return False
    return True


def _plan(n=8, seg=4.0, comparison=None):
    blocks = [{"start": round(i * seg, 3), "end": round((i + 1) * seg, 3)} for i in range(n)]
    return {"blocks": blocks, "comparison_lines": comparison or []}


def test_the_line_reads_like_the_grill():
    if not _model():
        return
    with P.pinned():
        f = ([F("score.low_similarity", {"block": i}) for i in range(3)]
             + [F("score.pace_below_floor", {}, units=3)]
             + [F("score.low_framing", {"block": i}) for i in (4, 5)]
             + [F("score.judge_neutral", {"block": 6}), F("score.card_over_face", {"block": 1})])
        b = L.build([{"stage": "plan", "findings": f}])
        line = L.summary_line(b)
        assert line == ("B · 78 — −9 похожесть (3 блока), −6 темп, −6 кадрирование (2 шота), "
                        "−1 судья: 1 neutral"), line
        # a zero price (card over face) is not in the line; a clean video says so
        assert "карточка" not in line
        assert L.summary_line(L.build([])) == "S · 100 — без штрафов", L.summary_line(L.build([]))


def test_the_line_marks_the_hook_the_hard_list_and_the_judge():
    if not _model():
        return
    with P.pinned():
        f = [F("score.frozen_block", {"block": 0, "t": 0.0}, hook=True),
             F("score.judge_contradicts", {"block": 2}), F("score.judge_neutral", {"block": 3}),
             F("score.judge_neutral", {"block": 4}), F("score.hard.render_defect", {})]
        line = L.summary_line(L.build([{"stage": "qc", "findings": f}]))
        assert line.startswith("F · 48 — жёсткий: брак рендера; −40 зависший кадр (1 блок, хук)"), line
        assert line.endswith("−12 судья: 1 contradicts, 2 neutral"), line
        assert L.summary_line({"score": None, "error": "boom"}) == "очки не посчитаны: boom"


def test_a_stage_replaces_itself_and_forgets_what_came_after():
    if not _model():
        return
    with tempfile.TemporaryDirectory() as tmp:
        plan = Path(tmp) / "plan.json"
        L.record(plan, "plan", [F("score.low_similarity", {"block": 1})], script_id="s1")
        L.record(plan, "render", [F("score.short_length", {}, units=2)])
        b = L.record(plan, "qc", [F("score.no_lofi_bed", {})])
        assert b["score"] == 92 and [s["stage"] for s in b["stages"]] == ["plan", "render", "qc"]
        assert [s["charged"] for s in b["stages"]] == [-3, -2, -3], b["stages"]
        # a QC-degrade render: QC again replaces QC
        b = L.record(plan, "qc", [])
        assert b["score"] == 95, b["score"]
        # a rebuilt plan: render and QC of the old one are forgotten
        b = L.record(plan, "plan", [])
        assert b["score"] == 100 and [s["stage"] for s in b["stages"]] == ["plan"]
        doc = json.loads(L.path_for(plan).read_text())
        assert L.path_for(plan).name == "plan.score.json"
        assert doc["schema"] == L.SCHEMA and doc["script_id"] == "s1"
        assert doc["score_line"] == "S · 100 — без штрафов", doc["score_line"]


def test_under_n_stops_with_a_refusal_and_back_over_n_takes_it_back():
    if not _model():
        return
    with P.pinned():
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            L.record(plan, "plan", [F("score.low_similarity", {"block": i}) for i in range(5)])
            b = L.record(plan, "qc", [F("score.crop_cuts_subject", {"block": 3, "t": 12.0})])
            assert b["score"] == 44 and L.stops(b) and b["stopped_at"] == "qc", b
            side = L.check(plan, b, "s1", "qc")
            assert side and Path(side).name == "plan.score.refusal.json", side
            rec = plan_refusal.read(side)
            assert rec["gate"] == plan_refusal.GATE_SCORE
            assert rec["reason_code"] == plan_refusal.SCORE_BELOW_THRESHOLD
            assert rec["supersedes_video"] is True
            assert rec["score_line"].startswith("F · 44 — −15 похожесть (5 блоков), −41 кроп"), rec
            assert rec["numbers"] == {"score": 44, "threshold": 60, "stage": "qc"}
            # write_batch_metadata finds it with every other refusal
            assert [r["script_id"] for r in plan_refusal.collect(Path(tmp).parent)] in ([], ["s1"])
            # a degrade render that no longer cuts the hero: back over N, sidecar gone
            b = L.record(plan, "qc", [])
            assert not L.stops(b) and L.check(plan, b, "s1", "qc") is None
            assert not Path(side).exists()


def test_the_live_table_n_40_and_a_neutral_that_costs_nothing():
    """CF-0462 (signed 2026-10-01): on the live table N is 40, E starts at 40,
    `score.judge_neutral` costs 0 - neutral blocks alone leave no item in the
    line, beside a contradicts they are counted but charge nothing; five weak
    blocks are over N now, a crop (CF-0469) still takes a video under it."""
    if not _model():
        return
    live = P.live_table()
    assert live["score"]["threshold"] == 40 and live["score"]["tiers"]["E"] == 40, live["score"]
    pen = live["rules"]["score.judge_neutral"]["penalty"]
    assert pen["price"] == 0 and pen["cap"] == 0, pen
    b = L.build([{"stage": "qc", "findings": [F("score.judge_neutral", {"block": i})
                                              for i in range(4)]}])
    assert b["score"] == 100 and b["threshold"] == 40, b
    assert L.summary_line(b) == "S · 100 — без штрафов", L.summary_line(b)
    b = L.build([{"stage": "qc", "findings": [F("score.judge_contradicts", {"block": 2}),
                                              F("score.judge_neutral", {"block": 3})]}])
    # the judge's item is what contradicts charged; the neutral is counted, free
    assert L.summary_line(b) == "A · 90 — −10 судья: 1 contradicts, 1 neutral", L.summary_line(b)
    # the 44 of the pinned check: five weak blocks alone are over N 40 now, and
    # the crop - a defect the user refuses for, 61 since CF-0469 (01.10) - takes
    # the video under N on its own: 100 - 15 - 61 = 24, stopped at qc
    b = L.build([{"stage": "plan", "findings": [F("score.low_similarity", {"block": i})
                                                for i in range(5)]}])
    assert b["score"] == 85 and not L.stops(b) and b["stopped_at"] is None, b
    b = L.build([{"stage": "plan", "findings": [F("score.low_similarity", {"block": i})
                                                for i in range(5)]},
                 {"stage": "qc", "findings": [F("score.crop_cuts_subject",
                                                {"block": 3, "t": 12.0})]}])
    assert b["score"] == 24 and L.stops(b) and b["stopped_at"] == "qc", b



def test_the_hard_list_is_tier_f_but_not_the_early_stop():
    if not _model():
        return
    b = L.build([{"stage": "qc", "findings": [F("score.hard.foreign_text", {"block": 2})]}])
    assert b["tier"] == "F" and b["passed"] is False and b["score"] == 100
    assert not L.stops(b) and b["stopped_at"] is None
    assert not L.stops({"score": None, "passed": None})


def test_qc_readings_map_to_the_models_rules():
    if not _model():
        return
    plan = _plan(comparison=[{"start_s": 20.0, "end_s": 24.0}])
    result = {"passed": False, "failures": [
        "shot with burned-in text: block 5 (abc:3) - CF-0351 ...",
        "supplement shot without the entity: block 6 (x:1) - ...",
        "1 silent stretch(es) over 2.5s: 3.00s at 10.00s - dead air",
        "picture runs 40.00s but the plan says 39.00s (the voiceover) (+1.00s adrift)",
        "clip blocks rendered as stills: block 0 ..."],
        "measured": {
            "frozen_clip_blocks": [0],
            "subject_offscreen_blocks": [
                {"index": 2, "at": 9.0, "fault": True, "reason": "no face"},
                {"index": 7, "at": 29.0, "fault": True,
                 "reason": "source could not be checked to explain it"}],
            "panel_cut_blocks": [{"index": 3, "at": 13.0, "visible": 0.24, "fault": True},
                                 {"index": 4, "at": 17.0, "visible": 0.59, "fault": True}],
            # CF-0442: the gate itself says the face is under the comparison
            # card - a covered record, fault False, never an offscreen one
            "subject_covered_blocks": [
                {"index": 5, "at": 22.0, "fault": False, "covered": True,
                 "covered_by": [{"kind": "comparison_line", "layer": "comparison_line",
                                 "window": [20.0, 24.0]}]}],
            "background_hole_blocks": [1],
            "repeated_pictures": [{"blocks": [1, 3], "kind": "repeat", "similarity": 1.0}],
            "bed_missing": True}}
    got = [(f["rule"].replace("score.", ""), f["where"].get("block"), f["hook"])
           for f in L.qc_findings(result, plan)]
    assert got == [
        ("frozen_block", 0, True),
        ("crop_cuts_subject", 2, False),
        ("crop_cuts_subject", 3, False),       # a sliver of a panel
        ("panel_partly_cut", 4, False),
        ("card_over_face", 5, False),          # the face is under the comparison card
        ("abstract_background", 1, False),
        ("repeated_shot", 3, False),
        ("hard.foreign_text", 5, False),
        ("off_topic_shot", 6, False),
        ("hard.sound_broken", None, False),
        ("hard.render_defect", None, False),
        ("no_lofi_bed", None, False)], got
    # every rule it writes is on the price table
    L.build([{"stage": "qc", "findings": L.qc_findings(result, plan)}])
    got = {f["where"].get("block"): f["note"] for f in L.qc_findings(result, plan)
           if f["rule"] == "score.card_over_face"}
    assert got == {5: "face under comparison_line"}, got
    # the translator no longer guesses from the plan's line spans: an
    # offscreen record inside one is still what the gate called it
    only = {"measured": {"subject_offscreen_blocks": [
        {"index": 5, "at": 21.0, "fault": True, "reason": "no face"}]}}
    assert [f["rule"] for f in L.qc_findings(only, plan)] == ["score.crop_cuts_subject"]
    # CF-0363's record before covered_by: the insert kind names the card
    legacy = {"measured": {"subject_covered_blocks": [
        {"index": 1, "fault": False, "covered": True, "insert_kind": "proof"}]}}
    assert [f["note"] for f in L.qc_findings(legacy, plan)] == ["face under proof"]
    assert L.qc_findings({"audio_only": True, "measured": {"bed_missing": True}}, plan) == []



def test_cf0751_every_qc_note_reaches_the_log_with_its_russian():
    """CF-0751: the command center shows `note_ru` - the root's score model
    puts it beside every `note` of the log and the hard list. Every note this
    stage writes off a QC verdict has its Russian (the root's
    tests/test_score_note_ru.py holds the full list of shapes)."""
    if not _model():
        return
    if not hasattr(_score.module(), "note_ru"):
        print("  SKIP: the root's score model predates CF-0751")
        return
    plan = _plan()
    result = {"passed": False, "failures": [
        "shot with burned-in text: block 5 (abc:3) - CF-0351 ...",
        "supplement shot without the entity: block 6 (x:1) - ...",
        "1 silent stretch(es) over 2.5s: 3.00s at 10.00s - dead air",
        "audio peaks at 0.10 dB - clipping",
        "no video stream",
        "resolution 720x1280 != requested 1080x1920",
        "picture runs 40.00s but the plan says 39.00s (the voiceover) (+1.00s adrift)"],
        "measured": {
            "frozen_clip_blocks": [0],
            "subject_offscreen_blocks": [{"index": 2, "at": 9.0, "fault": True,
                                          "reason": "no face"}],
            "panel_cut_blocks": [{"index": 3, "at": 13.0, "visible": 0.24, "fault": True},
                                 {"index": 4, "at": 17.0, "visible": 0.59, "fault": True}],
            "subject_covered_blocks": [{"index": 5, "fault": False, "covered": True,
                                        "covered_by": [{"kind": "meme"}]}],
            "background_hole_blocks": [1],
            "repeated_pictures": [{"blocks": [1, 3], "kind": "near_duplicate",
                                   "similarity": 0.87}],
            "lifted_blocks": [{"index": 6, "gain": 1.27, "luma_render": 27.3, "fault": True}],
            "bed_missing": True}}
    findings = L.qc_findings(result, plan) + L.render_findings(43.6, 720, 1280)
    block = L.build([{"stage": "qc", "findings": findings}])
    entries = block["hard"] + block["log"]
    assert len(entries) == len(findings), (entries, findings)
    missing = [e["note"] for e in entries if not e.get("note_ru")]
    assert not missing, missing
    ru = {e["rule"]: e["note_ru"] for e in entries}
    assert ru["score.frozen_block"] == "видеоблок вышел стоп-кадром", ru
    assert ru["score.short_length"] == "43,6 с — короче 45 с (1 × 3 с)", ru
    assert all(e["note"] for e in entries)          # the English stays as it was


def test_cf0493_the_panel_boundary_is_the_tables_27_5():
    """CF-0493 (the user 2026-10-03: «Да, 27,5%, до релиза»): a panel kept
    under 27.5 % is a sliver (crop_cuts_subject, -61), at or over it a panel
    partly cut (-4). PANEL_SLIVER is the root table's
    `score.panel_partly_cut.panel_visible_from`; coach-hale of the rerun 1748Z
    (31 %, accepted) falls on the -4 side, mormon-wives-comeback (24 %,
    rejected) stays on the -61 one."""
    assert L.PANEL_SLIVER == 0.275
    root = _score.factory_root()
    if root is not None and (root / "shared" / "gate-prices.json").is_file():
        row = json.loads((root / "shared" / "gate-prices.json").read_text(encoding="utf-8")
                         )["rules"].get("score.panel_partly_cut") or {}
        if "panel_visible_from" in row:     # a root older than CF-0493 has no field
            assert row["panel_visible_from"] == L.PANEL_SLIVER, row["panel_visible_from"]
    plan = _plan()

    def rule(visible):
        r = {"measured": {"panel_cut_blocks": [
            {"index": 2, "at": 3.88, "visible": visible, "fault": True}]}}
        return [f["rule"] for f in L.qc_findings(r, plan)]
    assert rule(0.24) == ["score.crop_cuts_subject"]          # mormon-wives-comeback
    assert rule(0.2749) == ["score.crop_cuts_subject"]
    for vis in (0.275, 0.3106, 0.3673, 0.4126, 0.5883):        # coach-hale 1748Z, backrooms, harbourlights
        assert rule(vis) == ["score.panel_partly_cut"], vis

def test_the_render_prices_its_length_and_its_frame():
    if not _model():
        return
    assert [f["rule"] for f in L.render_findings(52.0, 1080, 1920)] == []
    short = L.render_findings(33.9, 1080, 1920)
    assert [(f["rule"], f["units"]) for f in short] == [("score.short_length", 4)], short
    bad = [f["rule"] for f in L.render_findings(61.0, 720, 1280)]
    assert bad == ["score.hard.duration_out_of_range", "score.hard.render_defect"], bad


def test_05_fields_come_off_the_log_or_the_plans_own_score():
    if not _model():
        return
    with tempfile.TemporaryDirectory() as tmp:
        plan_path = Path(tmp) / "plan.json"
        plan = {"score": {"findings": [F("score.hold_band_exceeded", {"block": 2})]}}
        # no log file yet (a plan built before CF-0434): the plan stage from the plan
        got = L.record_fields(plan_path, plan)
        assert got["score"]["score"] == 98 and got["score_line"] == "S · 98 — −2 полоса удержания (1 блок)", got
        assert [s["stage"] for s in got["score"]["stages"]] == ["plan"]
        L.record(plan_path, "plan", plan["score"]["findings"])
        L.record(plan_path, "render", [F("score.short_length", {}, units=1)])
        got = L.record_fields(plan_path, plan)
        assert got["score"]["score"] == 97 and got["score"]["tier"] == "S"
        for k in ("start", "score", "tier", "threshold", "passed", "hard", "log", "by_rule",
                  "stages", "stopped_at", "findings"):
            assert k in got["score"], k
        assert L.record_fields(None, {}) == {"score": None, "score_line": None}



def test_the_line_and_the_arithmetic_are_the_roots():
    """No second spelling of the line here (CF-0434 follow-up): the local
    constants a rootless checkout writes with are the root's, and without the
    root the log still builds - `score: null`, the reason in the line."""
    if not _model():
        return
    mod = _score.module()
    assert (L.SCHEMA, L.SUFFIX, L.STAGES, L.LINE_FIELD) == (
        mod.LOG_SCHEMA, mod.LOG_SUFFIX, mod.STAGES, mod.LINE_FIELD)
    for name in ("LABELS", "HARD_LABELS", "NOUNS", "_plural", "_num", "_per_of"):
        assert not hasattr(L, name), name
    real, real_err = _score.module, _score.error
    _score.module = lambda: None
    _score.error = lambda: "score model not found: test"
    try:
        b = L.build([{"stage": "plan", "findings": [F("score.low_similarity", {"block": 0})]},
                     {"stage": "qc", "findings": []}])
        assert b["score"] is None and b["error"] == "score model not found: test", b
        assert [s["stage"] for s in b["stages"]] == ["plan", "qc"], b["stages"]
        assert b["stopped_at"] is None and not L.stops(b)
        assert L.summary_line(b) == "очки не посчитаны: score model not found: test"
        assert L.path_for("/x/work/s/plan.json") == Path("/x/work/s/plan.score.json")
    finally:
        _score.module, _score.error = real, real_err


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

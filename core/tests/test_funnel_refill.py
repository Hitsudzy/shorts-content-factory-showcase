#!/usr/bin/env python3
"""CF-0888: the funnel reads the below-shortlist refill (CF-0882) itself - the
rounds of `work/below-shortlist-refill.json`, Trend Hunter's walk in
`01 -> below_shortlist_refill[]` and compliance's on-the-fly refusals in
`02 -> refill_refused[]` - so the command center never assembles them from the
raw files; every refusal code has its Russian line.

Synthetic, in the shape of ExampleTech 2026-10-28T0833Z (round `late`, one
topic admitted, one search)."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import funnel                                                        # noqa: E402

AT = "2026-10-28T10:43:30Z"


def _record():
    return {"task": "CF-0882", "schema": "below-shortlist-refill/1", "rounds": [
        {"round": "late", "at": AT, "at_code": "researcher_refusal", "need": 1,
         "need_why": "N=1 refused unanswered, M=0 in reserve",
         "queue": ["b1", "b2", "b3"],
         "judged": [{"topic_id": "b1", "verdict": "clear", "outcome": "eligible", "reason": "clear"},
                    {"topic_id": "b2", "verdict": "review", "outcome": "refused",
                     "reason": "a forbidden term"},
                    {"topic_id": "b3", "verdict": "reject", "outcome": "refused",
                     "reason": "excluded holder"}],
         "footage": [{"topic_id": "b1", "outcome": "candidates", "searches": 1,
                      "reason": "own graphics"}],
         "admitted": ["b1"], "searches": 1, "outcome": "admitted",
         "why": "1 of 1 slot(s) from below the shortlist (b1), 1 search(es)",
         "budget": {"line": "квота суток: потрачено 19 из 100 -> можно 9"}, "spent_after": 20},
        {"round": "first", "at": "2026-10-28T09:00:00Z", "at_code": "researcher_refusal",
         "need": 0, "need_why": "nothing refused", "queue": [], "judged": [], "footage": [],
         "admitted": [], "searches": 0, "outcome": "not_needed", "why": "nothing refused"}]}


def _th():
    return {"topics": [{"topic_id": "t1"}, {"topic_id": "b1"}],
            "below_shortlist_refill": [
                {"topic_id": "b1", "outcome": "candidates", "searches": 1,
                 "at": "2026-10-28T10:43:33Z", "reason": "0 footage candidate(s), own graphics",
                 "task": "CF-0882"}]}


def _c02():
    return {"results": [{"topic_id": "t1", "verdict": "clear"}],
            "reserve": [{"topic_id": "b1", "verdict": "clear", "reason_code": "reserve_unused",
                         "refill": {"task": "CF-0882", "round": "late", "at": AT}}],
            "refill_refused": [
                {"topic_id": "b2", "verdict": "review", "reason_code": "refill_screen",
                 "reason": "a forbidden term", "at": AT},
                {"topic_id": "b3", "verdict": "reject", "reason_code": "rights_exclusion",
                 "reason": "excluded holder", "at": AT, "round": "late"},
                {"topic_id": "zz", "verdict": "review", "reason_code": "refill_screen",
                 "reason": "nobody's round", "at": AT}]}


def test_the_rounds_join_the_record_the_walk_and_the_refusals():
    r = funnel.below_shortlist_refill(_record(), _th(), _c02())
    assert [x["round"] for x in r["rounds"]] == ["first", "late"]
    late = r["rounds"][1]
    assert late["outcome"] == "admitted" and late["outcome_ru"]
    assert late["need"] == 1 and late["queue"] == 3 and late["eligible"] == 1
    assert late["admitted"] == ["b1"] and late["searches"] == 1 and late["spent_after"] == 20
    assert late["budget_line"].startswith("квота суток")
    (walk,) = late["footage"]
    # Trend Hunter's own row wins: its `at` and its fuller reason
    assert walk["at"] == "2026-10-28T10:43:33Z" and "own graphics" in walk["reason"]
    codes = {x["topic_id"]: x["reason_code"] for x in late["refused"]}
    assert codes == {"b2": "refill_screen", "b3": "rights_exclusion"}
    assert all(x["reason_ru"] for x in late["refused"])
    assert r["admitted"] == 1 and r["searches"] == 1 and r["refused"] == 3
    assert [x["topic_id"] for x in r["unattributed"]["refused"]] == ["zz"]
    assert r["rounds"][0]["outcome_ru"] and r["rounds"][0]["footage"] == []


def test_a_walk_without_a_root_record_goes_to_its_own_round_or_unattributed():
    th = {"below_shortlist_refill": [
        {"topic_id": "b1", "outcome": "candidates", "searches": 2, "round": "judge", "at": AT},
        {"topic_id": "b9", "outcome": "refused", "searches": 0, "at": AT}]}
    r = funnel.below_shortlist_refill(None, th, None)
    (judge,) = r["rounds"]
    assert judge["round"] == "judge" and judge["outcome"] is None and judge["outcome_ru"] is None
    assert [x["topic_id"] for x in judge["footage"]] == ["b1"]
    assert [x["topic_id"] for x in r["unattributed"]["footage"]] == ["b9"]
    line = funnel.refill_line(r)
    assert "judge: not recorded by the root" in line and "no round for 1 walk(s)" in line


def test_no_refill_is_none_and_no_line():
    assert funnel.below_shortlist_refill(None, {"topics": []}, {"results": []}) is None
    assert funnel.below_shortlist_refill({"rounds": []}, None, None) is None
    assert funnel.refill_line(None) is None


def test_every_refill_refusal_code_and_round_outcome_reads_in_russian():
    for code in funnel.REFILL_REFUSAL_CODES:
        assert (funnel.refill_reason_ru(code) or "").strip(), code
        assert (funnel.reason_ru(code) or "").strip(), code
    assert funnel.reason_ru("refill_screen") == funnel.REFILL_REASONS_RU["refill_screen"]
    # a topic-loss code keeps its own sentence; the refill gets the refill's
    assert funnel.reason_ru("rights_exclusion") == funnel.REASONS_RU["rights_exclusion"]
    assert funnel.refill_reason_ru("rights_exclusion") == \
        funnel.REFILL_REASONS_RU["rights_exclusion"]
    # the refill codes are not topic-loss codes (CF-0714's one-row-per-code rule)
    assert funnel.REFILL_SCREEN not in funnel.FUNNEL_CODES
    for outcome in ("admitted", "not_needed", "queue_empty", "search_quota",
                    "none_eligible", "no_pool", "seam_failed"):
        assert (funnel.REFILL_OUTCOMES_RU.get(outcome) or "").strip(), outcome


def test_the_funnel_json_and_the_text_report_carry_the_refill():
    with tempfile.TemporaryDirectory() as d:
        b = Path(d) / "pipeline" / "example-tech" / "2026-10-28T0833Z"
        (b / "work").mkdir(parents=True)
        (b / "01-trend-hunter.json").write_text(json.dumps(_th()))
        (b / "02-compliance-checker.json").write_text(json.dumps(_c02()))
        (b / funnel.REFILL_RECORD_FILE).write_text(json.dumps(_record()))
        f = funnel.funnel(b, events=[])
        r = f[funnel.BELOW_SHORTLIST_REFILL_KEY]
        assert r and r["admitted"] == 1
        json.dumps(f, default=str)
        text = "\n".join(funnel.render(f))
        (line,) = [x for x in text.splitlines() if x.startswith("below-shortlist refill")]
        assert "2 round(s), 1 admitted, 3 refused, 1 search(es)" in line
        assert "late: admitted, need 1, judged 3 (1 eligible), walked 1, admitted b1" in line
        assert "b2 `refill_screen`" in line and "b3 `rights_exclusion`" in line
        # the record handed in with the artifacts wins over the directory
        A = funnel.read_artifacts(b)
        A[funnel.REFILL_RECORD_FILE] = {"rounds": []}
        f2 = funnel.funnel(None, artifacts=A, events=[])
        assert [x["round"] for x in f2[funnel.BELOW_SHORTLIST_REFILL_KEY]["rounds"]] == ["late"]


def test_a_batch_without_artifacts_says_none():
    with tempfile.TemporaryDirectory() as d:
        f = funnel.funnel(Path(d), events=[])
        assert f["available"] is False and f[funnel.BELOW_SHORTLIST_REFILL_KEY] is None


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")

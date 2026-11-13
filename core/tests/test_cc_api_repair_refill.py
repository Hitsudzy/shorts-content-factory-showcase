#!/usr/bin/env python3
"""CC-0171 (factory 2.37): the batch's two second chances in the center -
`api/repair_refill.py` under `GET /api/batches/{channel}/{batch_id}/topics`,
`.../topics/{topic_id}` and `.../videos`.

In-process against temp factory roots - the stage files written by the test
in the shapes the factory writes (`scripts/frame_judge_gate.py --repair` /
`shared/judge_repair.py apply` for `06 -> repairs[]`; `shared/below_shortlist.py`
and the agents' halves for the refill), no real batch, no network.

What is pinned:

* the repair succeeded: the script's `frame.repair` (outcome, blocks with their
  defect, before / after with reason_ru), «ролик готов после ремонта», the
  batch's `repairs` counts; the video's `repair` on /videos;
* the repair failed: `repair_failed` with its reason, the refusal stands,
  «...; ремонт не удался»; on /videos the reason with no absolute path;
* the refill admitted a topic: its `refill` (admitted, promoted, round, the
  facet run's searches), the batch's `refill` rounds with the totals;
* the refill refused: by the Trend Hunter's sieve (skipped_topics[]
  refill_outcome / refill_reason) and by the compliance check on the fly
  (02 refill_refused[]), the skipped topic's line, the one-topic route;
* a batch before 2.37 (none of these files or keys): every new field null,
  no error;
* the contract: 0.76.0 and the new models' fields;
* CC-0173 (factory 2.38, CF-0888): the blocks' defect and the rounds are the
  funnel's (`judge_repairs`, `below_shortlist_refill`) - its `outcome_ru`, its
  `reason_ru` of a refusal, a walk no round claims - not a parse of its own.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import test_cc_api_batch_topics as T                 # noqa: E402
import test_cc_api_videos as V                       # noqa: E402
from test_cc_api_batches import _w, client           # noqa: E402

import api                                           # noqa: E402
from api import factory as _factory                  # noqa: E402

FJ = "06-frame-judge.json"
TH = "01-trend-hunter.json"
C02 = "02-compliance-checker.json"
REFILL = "work/below-shortlist-refill.json"


def RU(code):
    return _factory.funnel().reason_ru(code)


def _blocks():
    return [{"block": 14, "entry": "block-14", "target": "shot", "exclude_shot": "KK:10",
             "kind": "thin_strip", "why": "a thin strip of picture", "start": 41.2, "end": 44.3},
            {"block": 5, "entry": "block-5-meme", "target": "meme", "exclude_shot": None,
             "kind": "smeared", "why": "the meme is smeared", "start": 12.0, "end": 14.0}]


def _repair(sid, slug, outcome, reason=None, after=None):
    return {"task": "CF-0881", "at": "2026-10-12T23:10:00Z", "script_id": sid, "slug": slug,
            "topic_id": sid.rsplit("-script", 1)[0], "blocks": _blocks(),
            "editor": {"outcome": "rendered" if after else "no_replacement", "reason": None,
                       "changed_blocks": [5, 14, 15], "replaced": []},
            "before": {"gate": "reject", "reason_code": "judge_footage_defect",
                       "score_line": "E · 41"},
            "after": after, "judged_entries": ["block-5-meme", "block-14"],
            "carried_entries": [], "outcome": outcome, "reason": reason}


def judge_repaired():
    """06 after `apply`: zeta's row replaced by the ready one, its record kept."""
    doc = T.judge()
    doc["videos"][1] = {"script_id": "reel-006-script1", "slug": "zeta", "gate": "pass",
                        "reason_code": None, "reason": None, "score_line": "B · 77"}
    doc["repairs"] = [_repair("reel-006-script1", "zeta", "repaired",
                              after={"gate": "pass", "reason_code": None,
                                     "score_line": "B · 77"})]
    doc["counts"] = {"repaired": 1, "repair_failed": 0}
    return doc


def judge_failed(reason):
    doc = T.judge()
    doc["videos"][1]["reason_code"] = "judge_footage_defect"
    doc["repairs"] = [_repair("reel-006-script1", "zeta", "repair_failed", reason=reason)]
    doc["counts"] = {"repaired": 0, "repair_failed": 1}
    return doc


def _with_refill(root, d):
    """01 / 02 / the record as the refill leaves them: reel-009 promoted and
    admitted (first round, 6 searches), reel-008 refused by the sieve, reel-010
    refused by the compliance check on the fly."""
    th = T.hunter()
    t9 = T._topic(9, "Iota")
    t9["refill"] = {"task": "CF-0882", "restored": False}
    th["topics"].append(t9)
    th["skipped_topics"][1].update(refill_outcome="refused",
                                   refill_reason="step 5b: the pool is too thin")
    th["skipped_topics"].append({"topic_id": "reel-010", "reason_code": "below_shortlist",
                                 "reason": "rank 11", "stage": "trend-hunter",
                                 "title": "Kappa", "kind": "work", "popularity_score": 40.0})
    th["below_shortlist_refill"] = [
        {"topic_id": "reel-009", "outcome": "candidates", "searches": 6,
         "at": "2026-10-12T21:00:00Z", "reason": "12 footage candidate(s), 6 search(es)",
         "task": "CF-0882", "round": "first"},
        {"topic_id": "reel-008", "outcome": "refused", "searches": 6,
         "at": "2026-10-12T21:01:00Z", "reason": "step 5b: the pool is too thin",
         "task": "CF-0882", "round": "first"}]
    _w(d / TH, th)
    c02 = T.compliance()
    c02["reserve"].append(T._verdict("reel-009", "clear", reason_code="reserve_unused",
                                     reason="refill, rank 10",
                                     refill={"task": "CF-0882", "round": "first",
                                             "at": "2026-10-12T21:02:00Z"}))
    c02["refill_refused"] = [{"topic_id": "reel-010", "verdict": "reject",
                              "reason": "the screen: a real tragedy", "reason_code":
                              "refill_screen", "decided_by": "script", "task": "CF-0882",
                              "at": "2026-10-12T20:59:00Z", "round": "first"}]
    _w(d / C02, c02)
    _w(d / REFILL, {"task": "CF-0882", "schema": "below-shortlist-refill/1", "rounds": [
        {"round": "first", "at": "2026-10-12T20:58:00Z", "at_code": "researcher_refusal",
         "need": 2, "need_why": "N=2 refused", "queue": ["reel-008", "reel-009", "reel-010"],
         "judged": [{"topic_id": "reel-008", "verdict": "clear", "outcome": "eligible",
                     "reason": None},
                    {"topic_id": "reel-009", "verdict": "clear", "outcome": "eligible",
                     "reason": None},
                    {"topic_id": "reel-010", "verdict": "reject", "outcome": "refused",
                     "reason": "the screen: a real tragedy"}],
         "footage": [{"topic_id": "reel-008", "outcome": "refused", "searches": 6,
                      "reason": "step 5b: the pool is too thin"},
                     {"topic_id": "reel-009", "outcome": "candidates", "searches": 6,
                      "reason": "12 candidates"}],
         "admitted": ["reel-009"], "searches": 12, "spent_after": 58,
         "budget": {"line": "day 46 of 100, 6 a topic, 7 affordable", "price": 6},
         "outcome": "admitted", "why": "1 of 2 slot(s) from below the shortlist"},
        {"round": "late", "at": "2026-10-12T22:00:00Z", "at_code": "researcher_refusal",
         "need": 0, "need_why": "N=0", "queue": [], "judged": [], "footage": [],
         "admitted": [], "searches": 0, "outcome": "not_needed", "why": "N=0"}]})


def _no_abs(obj, root):
    text = json.dumps(obj, ensure_ascii=False)
    assert str(root) not in text, text[:400]


# --------------------------------------------------------------------- the repair
def test_the_repair_succeeded():
    root, d = T.tree()
    _w(d / FJ, judge_repaired())
    got = T.get(root)
    assert got["repairs"] == {"repaired": 1, "repair_failed": 0, "videos": 1}
    zeta = T.by_id(got)["reel-006"]
    fr = zeta["scripts"][0]["frame"]
    assert fr["gate"] == "pass" and fr["score_line"] == "B · 77"
    rep = fr["repair"]
    assert rep["outcome"] == "repaired" and rep["reason"] is None
    assert rep["at"] == "2026-10-12T23:10:00Z"
    assert rep["blocks"] == [
        {"block": 14, "entry": "block-14", "target": "shot", "kind": "thin_strip",
         "why": "a thin strip of picture"},
        {"block": 5, "entry": "block-5-meme", "target": "meme", "kind": "smeared",
         "why": "the meme is smeared"}]
    assert rep["before"] == {"gate": "reject", "reason_code": "judge_footage_defect",
                             "reason_ru": RU("judge_footage_defect"), "score_line": "E · 41"}
    assert rep["after"]["gate"] == "pass" and rep["after"]["score_line"] == "B · 77"
    assert rep["editor_outcome"] == "rendered" and rep["changed_blocks"] == [5, 14, 15]
    assert zeta["state"]["phase"] == "done"
    assert zeta["state"]["line"] == "ролик готов после ремонта"
    alpha = T.by_id(got)["reel-001"]
    assert alpha["scripts"][0]["frame"]["repair"] is None
    assert alpha["state"]["line"] == "ролик готов"


def test_the_repair_failed():
    root, d = T.tree()
    _w(d / FJ, judge_failed("the Editor: no_replacement - no other shot for block 14"))
    got = T.get(root)
    assert got["repairs"] == {"repaired": 0, "repair_failed": 1, "videos": 1}
    zeta = T.by_id(got)["reel-006"]
    fr = zeta["scripts"][0]["frame"]
    assert fr["gate"] == "reject"
    assert fr["repair"]["outcome"] == "repair_failed"
    assert fr["repair"]["reason"] == "the Editor: no_replacement - no other shot for block 14"
    assert fr["repair"]["after"] is None and fr["repair"]["editor_outcome"] == "no_replacement"
    assert zeta["state"]["phase"] == "dropped"
    assert zeta["state"]["line"] == (f"отсеяна: судья кадров ({RU('judge_footage_defect')}); "
                                     f"ремонт не удался"), zeta["state"]


def test_the_videos_carry_the_repair():
    root = V.tree()
    d = root / "pipeline" / "reel" / V.BATCH
    _w(d / FJ, {"schema": "frame-judge/2", "videos": [
        {"script_id": "t-paper-dragon-script1", "slug": "paper-dragon", "gate": "pass",
         "reason_code": None, "score_line": "B · 77"},
        {"script_id": "t-night-owl-script1", "slug": "night-owl", "gate": "reject",
         "reason_code": "judge_footage_defect", "score_line": "E · 40"}],
        "repairs": [_repair("t-paper-dragon-script1", "paper-dragon", "repaired",
                            after={"gate": "pass", "reason_code": None,
                                   "score_line": "B · 77"}),
                    _repair("t-night-owl-script1", "night-owl", "repair_failed",
                            reason=f"the judge left no {d}/work/night-owl/frame-judge/"
                                   f"verdicts.repair.json")]})
    r = client(root).get(f"/api/batches/reel/{V.BATCH}/videos")
    assert r.status_code == 200, r.text
    got = r.json()
    vs = V.by_slug(got["videos"])
    assert vs["paper-dragon"]["repair"]["outcome"] == "repaired"
    assert vs["paper-dragon"]["repair"]["before"]["reason_ru"] == RU("judge_footage_defect")
    assert [b["kind"] for b in vs["paper-dragon"]["repair"]["blocks"]] == ["thin_strip",
                                                                          "smeared"]
    failed = vs["night-owl"]["repair"]
    assert failed["outcome"] == "repair_failed"
    assert failed["reason"].endswith("verdicts.repair.json") and str(root) not in failed["reason"]
    assert vs["no-file"]["repair"] is None
    for rb in got["rebuilds"]:
        assert all(v["repair"] is None for v in rb["videos"])
    _no_abs(got, root)


# --------------------------------------------------------------------- the refill
def test_the_refill_admitted_a_topic():
    root, d = T.tree()
    _with_refill(root, d)
    got = T.get(root)
    iota = T.by_id(got)["reel-009"]
    assert iota["rank"] == 7
    ref = iota["refill"]
    assert ref["outcome"] == "admitted" and ref["round"] == "first"
    assert ref["promoted"] is True and ref["restored"] is False and ref["admitted"] is True
    assert ref["refused_by"] is None and ref["reason"] is None
    assert ref["compliance"] == {"outcome": "eligible", "verdict": "clear", "reason_code": None,
                                 "reason_ru": None, "reason": None}
    assert ref["footage"] == {"outcome": "candidates", "searches": 6,
                              "at": "2026-10-12T21:00:00Z",
                              "reason": "12 footage candidate(s), 6 search(es)"}
    assert iota["compliance"]["place"] == "reserve"
    assert iota["state"]["phase"] == "reserve"
    assert T.by_id(got)["reel-001"]["refill"] is None
    b = got["refill"]
    assert b["record"] == REFILL and b["admitted"] == 1 and b["searches"] == 12
    first, late = b["rounds"]
    assert first["round"] == "first" and first["outcome"] == "admitted"
    assert first["need"] == 2 and first["admitted"] == ["reel-009"]
    assert first["queue"] == ["reel-008", "reel-009", "reel-010"]
    assert first["searches"] == 12 and first["spent_after"] == 58
    assert first["budget_line"] == "day 46 of 100, 6 a topic, 7 affordable"
    assert [x["outcome"] for x in first["judged"]] == ["eligible", "eligible", "refused"]
    assert first["footage"][0] == {"topic_id": "reel-008", "outcome": "refused", "searches": 6,
                                   "reason": "step 5b: the pool is too thin"}
    assert late["outcome"] == "not_needed" and late["searches"] == 0 and late["admitted"] == []


def test_the_refill_refused_topics():
    root, d = T.tree()
    _with_refill(root, d)
    got = T.get(root)
    sk = {s["topic_id"]: s for s in got["skipped"]}
    theta = sk["reel-008"]["refill"]
    assert theta["outcome"] == "refused" and theta["refused_by"] == "trend_hunter"
    assert theta["reason"] == "step 5b: the pool is too thin"
    assert theta["promoted"] is False and theta["admitted"] is False
    assert theta["footage"]["outcome"] == "refused" and theta["footage"]["searches"] == 6
    assert sk["reel-008"]["state"]["line"] == "не вошла в шорт-лист; добор: отказ (сито футажа)"
    kappa = sk["reel-010"]["refill"]
    assert kappa["outcome"] == "refused" and kappa["refused_by"] == "compliance"
    assert kappa["round"] == "first" and kappa["reason"] == "the screen: a real tragedy"
    assert kappa["compliance"]["reason_code"] == "refill_screen"
    assert "reason_ru" in kappa["compliance"] and kappa["footage"] is None
    assert sk["reel-010"]["state"]["line"] == ("не вошла в шорт-лист; добор: отказ "
                                               "(проверка правил)")
    assert sk["reel-007"]["refill"] is None
    assert sk["reel-007"]["state"]["line"].startswith("отсеяна")
    one = T.get(root, f"{T.URL}/reel-008")
    assert one["shortlisted"] is False and one["skipped"]["refill"]["refused_by"] == "trend_hunter"
    one = T.get(root, f"{T.URL}/reel-009")
    assert one["shortlisted"] is True and one["summary"]["refill"]["outcome"] == "admitted"


def test_the_sieve_alone_says_refused():
    """A topic the sieve refused with no log row (the record lost): the skipped
    row's refill_outcome / refill_reason are enough."""
    root, d = T.tree()
    th = T.hunter()
    th["skipped_topics"][1].update(refill_outcome="refused", refill_reason="thin pool")
    _w(d / TH, th)
    got = T.get(root)
    theta = {s["topic_id"]: s for s in got["skipped"]}["reel-008"]["refill"]
    assert theta["outcome"] == "refused" and theta["refused_by"] == "trend_hunter"
    assert theta["reason"] == "thin pool" and theta["footage"]["searches"] is None
    assert got["refill"] is None


# --------------------------------------------------------------------- an old batch
def test_a_batch_before_2_37_has_every_new_field_null():
    root, d = T.tree()
    before = T.snapshot(root)
    got = T.get(root)
    assert got["repairs"] is None and got["refill"] is None
    for t in got["topics"]:
        assert t["refill"] is None
        for s in t["scripts"] or []:
            assert s["frame"] is None or s["frame"]["repair"] is None
    assert all(s["refill"] is None for s in got["skipped"])
    assert T.by_id(got)["reel-006"]["state"]["line"].endswith(
        f"({RU('score_below_threshold')})")
    one = T.get(root, f"{T.URL}/reel-008")
    assert one["skipped"]["refill"] is None
    # a record that does not parse is no rounds, not an error
    (d / "work").mkdir(exist_ok=True)
    (d / REFILL).write_text("{broken", encoding="utf-8")
    assert T.get(root)["refill"] is None
    (d / REFILL).unlink()
    assert T.snapshot(root) == before

    root = V.tree()
    r = client(root).get(f"/api/batches/reel/{V.BATCH}/videos")
    assert r.status_code == 200, r.text
    assert all(v["repair"] is None for v in r.json()["videos"])


def test_only_02_before_the_judge():
    """01 + 02 only: no 06 - repairs null; the refill already shows."""
    root, d = T.tree(upto=2)
    _with_refill(root, d)
    got = T.get(root)
    assert got["repairs"] is None and got["refill"]["admitted"] == 1
    assert T.by_id(got)["reel-009"]["refill"]["outcome"] == "admitted"


# --------------------------------------------------------------------- CC-0173
def test_the_rounds_and_the_refusals_are_the_funnel_s():
    """CC-0173 (CF-0888): the round's Russian outcome and the refusal's
    `reason_ru` are the funnel's (REFILL_OUTCOMES_RU, refill_reason_ru)."""
    fn = _factory.funnel()
    root, d = T.tree()
    _with_refill(root, d)
    got = T.get(root)
    first, late = got["refill"]["rounds"]
    assert first["outcome_ru"] == fn.REFILL_OUTCOMES_RU["admitted"]
    assert late["outcome_ru"] == fn.REFILL_OUTCOMES_RU["not_needed"]
    assert first["need_why"] == "N=2 refused" and late["queue"] == []
    kappa = {s["topic_id"]: s for s in got["skipped"]}["reel-010"]["refill"]
    assert kappa["compliance"]["reason_ru"] == fn.refill_reason_ru("refill_screen")
    assert kappa["compliance"]["reason_ru"]


def test_a_walk_no_round_claims_still_reaches_its_topic():
    """A Trend Hunter row with no `round` and no record of the root (the
    funnel's `unattributed`): the topic still shows its walk; the batch's
    refill is there with no round."""
    root, d = T.tree()
    th = T.hunter()
    th["below_shortlist_refill"] = [{"topic_id": "reel-008", "outcome": "quota",
                                     "searches": 0, "at": "2026-10-12T21:01:00Z",
                                     "reason": "the day's quota is spent"}]
    _w(d / TH, th)
    got = T.get(root)
    theta = {s["topic_id"]: s for s in got["skipped"]}["reel-008"]["refill"]
    assert theta["outcome"] == "quota" and theta["round"] is None
    assert theta["footage"] == {"outcome": "quota", "searches": 0,
                                "at": "2026-10-12T21:01:00Z",
                                "reason": "the day's quota is spent"}
    assert got["refill"] == {"record": REFILL, "rounds": [], "admitted": 0, "searches": 0}


def test_the_api_follows_the_funnel_not_the_raw_files():
    """The funnel is the one reader: what its `judge_repairs` and
    `below_shortlist_refill` say is what the center gets, whatever the raw
    files hold."""
    from api import repair_refill
    fn = _factory.funnel()
    for name in ("_rounds", "LOG_KEY", "REFUSED_KEY", "BLOCK_KEYS"):
        assert not hasattr(repair_refill, name), name
    real_jr, real_bs = fn.judge_repairs, fn.below_shortlist_refill

    def jr(fj):
        got = real_jr(fj)
        for v in got["videos"]:
            for b in v["block_details"]:
                b["kind"], b["why"] = "foreign_share", "the funnel's word"
        return got

    def bs(record, th=None, c02=None):
        got = real_bs(record, th, c02)
        got["rounds"][0]["outcome_ru"] = "the funnel's line"
        return got

    fn.judge_repairs, fn.below_shortlist_refill = jr, bs
    try:
        root, d = T.tree()
        _w(d / FJ, judge_repaired())
        _with_refill(root, d)
        got = T.get(root)
    finally:
        fn.judge_repairs, fn.below_shortlist_refill = real_jr, real_bs
    rep = T.by_id(got)["reel-006"]["scripts"][0]["frame"]["repair"]
    assert {(b["kind"], b["why"]) for b in rep["blocks"]} == {("foreign_share",
                                                               "the funnel's word")}
    assert [b["target"] for b in rep["blocks"]] == ["shot", "meme"]
    assert got["refill"]["rounds"][0]["outcome_ru"] == "the funnel's line"


# --------------------------------------------------------------------- the contract
def test_the_contract_has_the_new_fields():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    sc = spec["components"]["schemas"]
    assert set(sc["VideoRepair"]["properties"]) == {
        "outcome", "reason", "at", "blocks", "before", "after", "editor_outcome",
        "changed_blocks"}
    assert set(sc["RepairBlock"]["properties"]) == {"block", "entry", "target", "kind", "why"}
    assert set(sc["TopicRefill"]["properties"]) == {
        "outcome", "round", "promoted", "restored", "admitted", "refused_by", "reason",
        "compliance", "footage"}
    assert set(sc["BatchRefill"]["properties"]) == {"record", "rounds", "admitted", "searches"}
    assert "outcome_ru" in sc["RefillRound"]["properties"]                  # CC-0173
    assert "repair" in sc["ScriptFrame"]["properties"] and "repair" in sc["Video"]["properties"]
    for m in ("TopicSummary", "SkippedTopic"):
        assert "refill" in sc[m]["properties"], m
    for k in ("repairs", "refill"):
        assert k in sc["BatchTopics"]["properties"], k
        assert k not in sc["BatchTopics"].get("required", []), k


def test_the_factory_readers_are_the_ones_used():
    """The repair goes through funnel.judge_repairs - the API keeps no parse of
    its own counts; the refill's file name and mark are the factory's."""
    fn = _factory.funnel()
    doc = judge_repaired()
    assert fn.judge_repairs(copy.deepcopy(doc))["repaired"] == 1
    bs = _factory.below_shortlist()
    from api import repair_refill
    assert bs.RECORD_FILE == repair_refill.RECORD_FILE and bs.REFILL_MARK == "refill"
    assert fn.FRAME_JUDGE_FILE == repair_refill.FJ


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn_ in tests:
        try:
            fn_()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

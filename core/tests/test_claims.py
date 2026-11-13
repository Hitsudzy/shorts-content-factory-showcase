#!/usr/bin/env python3
"""CF-0552: `script.claims[]` - every checkable statement the viewer meets
stands on a verbatim quote of the topic's support_text or on a shot under its
words - held by `shared/factrule/claims.py`.

The acceptance cases are the grill's (CF-0546, 2026-10-05): East of Eden
0701Z said "months before anyone outside the production knew the shape of
the show" while Variety had announced the cast in September 2024 - a claim
(Q2), and no quote of the topic's text says it; Harbourlights 0701Z said
"Zorvath is behind the kill" off a headline that lists "Killer ... Revealed,
Zorvath Creates [SPOILER]". The support texts below are short synthetic
stand-ins written for the test (not copies of Wikipedia); offline, no batch
of pipeline/ is read."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("claims_cf0552",
                                              ROOT / "shared" / "factrule" / "claims.py")
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)

ARTICLE = ("East of Eden is an American drama limited series based on the novel by John "
           "Steinbeck, created by Zoe Kazan for ExampleStream.\n\n"
           "Production\n"
           "In September 2024, Christopher Abbott, Mike Faist and Hoon Lee joined the cast "
           "opposite Florence Pugh. Filming took place in New Zealand.")
TOPIC = {
    "topic_id": "t1",
    "support_text": [
        {"id": "wikipedia:East_of_Eden_(miniseries)", "kind": "work_article",
         "source": "wikipedia", "title": "East of Eden (miniseries)",
         "url": "https://en.wikipedia.org/wiki/East_of_Eden_(miniseries)",
         "revision_id": 1, "revised_at": "2026-10-05T00:00:00Z", "text": ARTICLE},
        {"id": "rss:1", "kind": "rss_summary", "source": "rss", "title": "Harbourlights finale",
         "url": "https://example.test/harbourlights", "revision_id": None, "revised_at": None,
         "published_at": "2026-10-05T00:00:00Z",
         "text": "'Harbourlights' Finale: Hal Garrett’s Killer and Manhunter Revealed, "
                 "Zorvath Creates [SPOILER]"},
    ],
    "support_check": {"state": "ok"},
}
GOOD_QUOTE = {"source": "wikipedia:East_of_Eden_(miniseries)",
              "quote": "In September 2024, Christopher Abbott, Mike Faist and Hoon Lee "
                       "joined the cast"}
SCRIPT = {
    "script_id": "s1", "topic_id": "t1",
    "hook": "Florence Pugh carries East of Eden.",
    "commentary": ("Here is the part the trailers skip: in September 2024 Christopher Abbott, "
                   "Mike Faist and Hoon Lee joined the cast. Watch her on the porch."),
    "payoff": "That porch is the whole show.",
    "production_fact": {"on_screen": "Abbott, Faist, Hoon Lee joined cast, Sept. 2024"},
    "claims": [
        {"claim_id": "c1", "where": "commentary",
         "text": "in September 2024 Christopher Abbott, Mike Faist and Hoon Lee joined the cast",
         "support": [GOOD_QUOTE]},
        {"claim_id": "c2", "where": "on_screen",
         "text": "Abbott, Faist, Hoon Lee joined cast, Sept. 2024", "support": [GOOD_QUOTE]},
        {"claim_id": "c3", "where": "commentary", "text": "Watch her on the porch",
         "support": [{"shot_id": "VID:1"}]},
    ],
}
POOL = {"VID:0": "A wide shot of a farm field.",
        "VID:1": "Bright close-up of Cathy in a blue-striped dress on a porch."}


def _words(text, t0=0.0, step=0.3):
    out, t = [], t0
    for w in text.split():
        out.append({"word": w, "start": round(t, 3), "end": round(t + step - 0.05, 3)})
        t += step
    return out


def _plan(script, shot_under_porch="VID:1"):
    text = " ".join(script[k] for k in ("hook", "commentary", "payoff"))
    aligned = _words(text)
    i = next(k for k, w in enumerate(aligned) if w["word"] == "Watch")
    cut = aligned[i]["start"] - 0.1
    return {"words": aligned, "blocks": [
        {"start": 0.0, "end": cut, "shot": "VID:0"},
        {"start": cut, "end": aligned[-1]["end"], "shot": shot_under_porch,
         "cuts": [{"shot": "VID:0"}]},
    ]}


def test_a_grounded_script_passes():
    rep = cl.check_claims(SCRIPT, topic=TOPIC, pool=POOL, plan=_plan(SCRIPT))
    assert rep["action"] == cl.ACTION_PASS, rep["violations"]
    assert rep["claims"] == 3 and not rep["pending"]
    quote = rep["results"][0]["supports"][0]
    assert quote["found"] and quote["revision_id"] == 1
    assert "Hoon Lee joined the cast" in quote["context"], quote
    shot = rep["results"][2]["supports"][0]
    assert shot["placement"] == cl.PLACED_UNDER and "porch" in shot["description"]


def test_east_of_eden_exaggeration_has_no_quote():
    """Q2: "before anyone outside the production knew" is a claim, and the
    topic's text says the opposite - no verbatim quote can carry it."""
    s = copy.deepcopy(SCRIPT)
    s["commentary"] += " This was months before anyone outside the production knew the shape of the show."
    s["claims"].append({"claim_id": "c4", "where": "commentary",
                        "text": "months before anyone outside the production knew the shape of the show",
                        "support": [{"source": "wikipedia:East_of_Eden_(miniseries)",
                                     "quote": "months before anyone outside the production knew"}]})
    rep = cl.check_claims(s, topic=TOPIC, pool=POOL, plan=_plan(s))
    assert cl.codes(rep) == [cl.FAIL_QUOTE_NOT_IN_SOURCE], rep["violations"]
    assert rep["results"][3]["state"] == cl.STATE_FAIL
    assert rep["violations"][0]["claim_id"] == "c4" and rep["violations"][0]["fix"]


def test_harbourlights_headline_glue_is_not_a_quote():
    s = copy.deepcopy(SCRIPT)
    s["commentary"] += " Zorvath is behind the kill."
    s["claims"].append({"claim_id": "c4", "where": "commentary",
                        "text": "Zorvath is behind the kill",
                        "support": [{"source": "rss:1", "quote": "Zorvath is behind the kill"}]})
    assert cl.codes(cl.check_claims(s, topic=TOPIC, pool=POOL)) == [cl.FAIL_QUOTE_NOT_IN_SOURCE]
    # the headline's own words are a verbatim quote - whether they *say* the
    # claim is CF-0553's judge, not this mechanics
    s["claims"][-1]["support"] = [{"source": "rss:1",
                                   "quote": "Hal Garrett's Killer and Manhunter Revealed"}]
    rep = cl.check_claims(s, topic=TOPIC, pool=POOL)
    assert rep["action"] == cl.ACTION_PASS, rep["violations"]


def test_a_news_headline_is_quotable_and_shown_with_its_summary():
    """CF-0556: the headline of an RSS piece is its text too (Rennick 1313Z
    kept no summary, only the headline said the renewal); a Wikipedia piece's
    title is a page name and is not."""
    topic = copy.deepcopy(TOPIC)
    topic["support_text"].append(
        {"id": "rss:2", "kind": "rss_summary", "source": "rss", "url": "https://example.test/r",
         "title": "'Rennick' Gets Early Season 6 Renewal With 66M Viewers In 28 Days",
         "revision_id": None, "revised_at": None, "text": ""})
    s = copy.deepcopy(SCRIPT)
    s["commentary"] += " The show got an early season six renewal."
    s["claims"].append({"claim_id": "c9", "where": "commentary",
                        "text": "The show got an early season six renewal",
                        "support": [{"source": "rss:2", "quote": "Gets Early Season 6 Renewal"}]})
    rep = cl.check_claims(s, topic=topic, pool=POOL)
    assert rep["action"] == cl.ACTION_PASS, rep["violations"]
    sup = next(r for r in rep["results"] if r["claim_id"] == "c9")["supports"][0]
    assert "66M Viewers" in sup["context"]
    s["claims"][-1]["support"] = [{"source": "wikipedia:East_of_Eden_(miniseries)",
                                   "quote": "East of Eden (miniseries)"}]
    assert cl.codes(cl.check_claims(s, topic=topic, pool=POOL)) == [cl.FAIL_QUOTE_NOT_IN_SOURCE]


def test_a_quote_carries_the_section_it_stands_under():
    """CF-0556 (Coach Hale 1313Z): "Season 1" was the heading above the Rotten
    Tomatoes paragraph - the judge sees the heading path with the quote."""
    text = ("Intro line.\n\n== Reception ==\n\n=== Critical response ===\n\n==== Season 1 ====\n"
            "Review aggregator Rotten Tomatoes reported an approval rating of 92% based on 74 "
            "reviews.\n\n==== Season 2 ====\nMetacritic gave it 79.\n\n== Accolades ==\nNone.")
    q = cl.norm_quote("an approval rating of 92% based on 74 reviews")
    assert cl.quote_section(text, q) == "Reception > Critical response > Season 1"
    assert cl.quote_section(text, cl.norm_quote("Metacritic gave it 79")) == \
        "Reception > Critical response > Season 2"
    assert cl.quote_section(text, cl.norm_quote("Intro line")) is None


def test_normalisation_is_spaces_quotes_dashes_case_only():
    piece = {"id": "p", "text": "He said “it’s over” — and  left in 1986–1990."}
    for quote in ('he said "it\'s over" - and left in 1986-1990.',
                  "He  said ‘it's over’ – and left in 1986 - 1990",
                  "“He said \"it's over\" — and left”"):
        rec, code = cl.judge_quote({"source": "p", "quote": quote}, {"p": piece})
        assert code is None, (quote, code)
    for quote in ("he said it is over and left",          # paraphrase
                  "he said ... left in 1986",             # splice
                  "he stated \"it's over\""):             # one word changed
        rec, code = cl.judge_quote({"source": "p", "quote": quote}, {"p": piece})
        assert code == cl.FAIL_QUOTE_NOT_IN_SOURCE, (quote, code)
    assert cl.judge_quote({"source": "p", "quote": "left in"}, {"p": piece})[1] == \
        cl.FAIL_QUOTE_TOO_SHORT
    assert cl.judge_quote({"source": "q", "quote": "he said it"}, {"p": piece})[1] == \
        cl.FAIL_SOURCE_UNKNOWN


def test_shot_must_be_under_the_words():
    """Q8: the shot backing what is visible is in a block under the words."""
    rep = cl.check_claims(SCRIPT, topic=TOPIC, pool=POOL, plan=_plan(SCRIPT, "VID:0"))
    assert cl.codes(rep) == [cl.FAIL_SHOT_NOT_UNDER_WORDS]
    rec = rep["results"][2]["supports"][0]
    assert rec["placement"] == cl.PLACED_ELSEWHERE and rec["blocks"], rec
    # a cut of the block under the words counts as being in it
    plan = _plan(SCRIPT, "VID:0")
    plan["blocks"][1]["cuts"] = [{"shot": "VID:1"}]
    assert cl.check_claims(SCRIPT, topic=TOPIC, pool=POOL, plan=plan)["action"] == "pass"


def test_shot_before_the_plan_is_pending_and_out_of_pool_fails():
    rep = cl.check_claims(SCRIPT, topic=TOPIC, pool=POOL, plan=None)
    assert rep["action"] == cl.ACTION_PASS
    assert [p["code"] for p in rep["pending"]] == [cl.PENDING_NO_PLAN]
    assert rep["results"][2]["state"] == cl.STATE_PENDING
    rep = cl.check_claims(SCRIPT, topic=TOPIC, pool=None)
    assert [p["code"] for p in rep["pending"]] == [cl.PENDING_POOL_NOT_READ]
    s = copy.deepcopy(SCRIPT)
    s["claims"][2]["support"] = [{"shot_id": "OTHER:4"}]
    assert cl.codes(cl.check_claims(s, topic=TOPIC, pool=POOL)) == [cl.FAIL_SHOT_NOT_IN_POOL]
    s["claims"][1]["support"] = [{"shot_id": "VID:1"}]     # on_screen: nothing is "under" it
    assert cl.FAIL_SHOT_NOT_SPOKEN in cl.codes(cl.check_claims(s, topic=TOPIC, pool=POOL))


def test_text_is_verbatim_from_its_field_and_title_waits_for_the_caller():
    s = copy.deepcopy(SCRIPT)
    s["claims"][0]["where"] = "hook"
    assert cl.codes(cl.check_claims(s, topic=TOPIC, pool=POOL)) == [cl.FAIL_TEXT_NOT_IN_FIELD]
    s = copy.deepcopy(SCRIPT)
    s["claims"].append({"claim_id": "c9", "where": "title", "text": "Hoon Lee joined the cast",
                        "support": [GOOD_QUOTE]})
    rep = cl.check_claims(s, topic=TOPIC, pool=POOL)
    assert rep["action"] == "pass" and [p["code"] for p in rep["pending"]] == \
        [cl.PENDING_NO_PLAN, cl.PENDING_FIELD_NOT_GIVEN]
    rep = cl.check_claims(s, topic=TOPIC, pool=POOL,
                          extra_texts={"title": "Florence Pugh's East of Eden"})
    assert cl.codes(rep) == [cl.FAIL_TEXT_NOT_IN_FIELD]


def test_hearsay_is_not_a_way_out():
    """Q3: "reportedly" / "rumoured" anywhere the viewer looks is refused,
    declared or not."""
    s = copy.deepcopy(SCRIPT)
    s["payoff"] = "Rumor has it the finale was reshot."
    rep = cl.check_claims(s, topic=TOPIC, pool=POOL)
    assert cl.codes(rep) == [cl.FAIL_HEDGED] and rep["violations"][0]["where"] == "payoff"
    s["payoff"] = "Variety reported that the finale was reshot."   # attribution is not hearsay
    assert cl.check_claims(s, topic=TOPIC, pool=POOL)["action"] == "pass"
    rep = cl.check_claims(SCRIPT, topic=TOPIC, pool=POOL,
                          extra_texts={"description": "Pugh was allegedly first choice."})
    assert cl.codes(rep) == [cl.FAIL_HEDGED]


def test_topic_without_text_fails_every_quoted_claim():
    topic = dict(TOPIC, support_check={"state": "unreachable"})
    rep = cl.check_claims(SCRIPT, topic=topic, pool=POOL)
    assert cl.FAIL_TOPIC_WITHOUT_TEXT in cl.codes(rep)
    rep = cl.check_claims(SCRIPT, topic={"topic_id": "t1"}, pool=POOL)
    assert cl.FAIL_TOPIC_WITHOUT_TEXT in cl.codes(rep)
    assert cl.FAIL_SOURCE_UNKNOWN in cl.codes(rep)


def test_shape():
    assert cl.codes(cl.check_claims(dict(SCRIPT, claims=None), topic=TOPIC)) == [cl.FAIL_MISSING]
    no = {"claims": []}
    assert cl.check_claims(dict(SCRIPT, **no), topic=TOPIC)["action"] == "pass"
    bad = [
        dict(SCRIPT["claims"][0], support=[]),
        dict(SCRIPT["claims"][0], where="voiceover"),
        dict(SCRIPT["claims"][0], claim_id="C 1"),
        dict(SCRIPT["claims"][0], verified=True),
        dict(SCRIPT["claims"][0], support=[{"source": "x", "quote": "a b c", "shot_id": "V:1"}]),
        dict(SCRIPT["claims"][0], support=[{"shot_id": "VID-1"}]),
        {k: v for k, v in SCRIPT["claims"][0].items() if k != "text"},
    ]
    for c in bad:
        rep = cl.check_claims(dict(SCRIPT, claims=[c]), topic=TOPIC, pool=POOL)
        assert cl.codes(rep) == [cl.FAIL_MALFORMED], (c, rep["violations"])
    rep = cl.check_claims(dict(SCRIPT, claims=[SCRIPT["claims"][0]] * 2), topic=TOPIC)
    assert cl.codes(rep) == [cl.FAIL_MALFORMED]
    assert set(cl.FIXES) == set(cl.FAIL_CODES)


def test_batch_file_and_command_line():
    """The CLI reads 01 beside the 03, the topic's pool from
    `anchor_coverage_pool.indexes`, and 6b's plan through its verdict."""
    with tempfile.TemporaryDirectory() as tmp:
        batch = Path(tmp) / "batch"
        (batch / "work" / "eoe").mkdir(parents=True)
        shots = Path(tmp) / "VID.shots.json"
        shots.write_text(json.dumps({"shots": [
            {"index": i, "description": d} for i, d in
            ((0, POOL["VID:0"]), (1, POOL["VID:1"]))]}))
        script = dict(SCRIPT, anchor_coverage_pool={"indexes": [str(shots)]})
        (batch / "01-trend-hunter.json").write_text(json.dumps({"topics": [TOPIC]}))
        (batch / "03-content-researcher.json").write_text(json.dumps({"scripts": [script]}))
        res = cl.check_batch_file(batch / "03-content-researcher.json")
        assert res[0][1]["pending"][0]["code"] == cl.PENDING_NO_PLAN
        (batch / "work" / "eoe" / "plan_check.json").write_text(json.dumps(
            {"kind": "plan_check", "script_id": "s1", "at": "1"}))
        (batch / "work" / "eoe" / "plan.json").write_text(json.dumps(_plan(SCRIPT, "VID:0")))
        out = subprocess.run([sys.executable, str(ROOT / "shared" / "factrule" / "claims.py"),
                              str(batch / "03-content-researcher.json")],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 1 and "shot_not_under_words c3" in out.stdout, out
        out = subprocess.run([sys.executable, str(ROOT / "shared" / "factrule" / "claims.py"),
                              str(batch / "missing.json")],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 3, out



# ------------------------------------------- CF-0660: a fact on a preprint
PREPRINT_FACT = {"text": "Abbott joined the cast in September 2024.", "kind": "other",
                 "source": "arXiv", "url": "https://arxiv.org/abs/2501.00001", "tier": 1,
                 "needs_caveat": True}


def _preprint_script(**fields):
    s = copy.deepcopy(SCRIPT)
    s["fact"] = dict(PREPRINT_FACT)
    s.update(fields)
    return s


def test_a_preprint_fact_with_the_caveat_in_the_narration_passes():
    s = _preprint_script(payoff="A preprint, not yet peer-reviewed - that porch is the whole show.")
    rep = cl.check_claims(s, topic=TOPIC, pool=POOL)
    assert rep["action"] == "pass", rep["violations"]
    for line in ("It hasn't been peer reviewed yet.", "The study is not peer-reviewed."):
        assert cl.check_claims(_preprint_script(hook=line), topic=TOPIC,
                               pool=POOL)["action"] == "pass", line


def test_a_preprint_fact_with_the_caveat_on_the_plate_passes():
    s = _preprint_script()
    s["production_fact"] = {"on_screen": "Preprint - not peer-reviewed"}
    s["claims"] = [c for c in s["claims"] if c["where"] != "on_screen"]
    assert cl.check_claims(s, topic=TOPIC, pool=POOL)["action"] == "pass"
    # a Russian plate says it in Russian
    s["production_fact"] = {"on_screen": "Препринт, ещё не рецензирован"}
    assert cl.check_claims(s, topic=TOPIC, pool=POOL)["action"] == "pass"


def test_a_preprint_fact_without_the_caveat_is_refused_with_its_code():
    rep = cl.check_claims(_preprint_script(), topic=TOPIC, pool=POOL)
    assert cl.codes(rep) == [cl.FAIL_PREPRINT_WITHOUT_CAVEAT] and rep["action"] == "fail"
    v = rep["violations"][0]
    assert v["code"] == "preprint_without_caveat" and v["where"] is None
    assert "arxiv.org/abs/2501.00001" in v["detail"]
    assert "рецензирован" in v["text_ru"] and v["text_ru"] == cl.REFUSALS_RU[v["code"]]
    # "preprint" alone is not the caveat, nor is a title or a description
    rep = cl.check_claims(_preprint_script(payoff="It is a preprint on arXiv."),
                          topic=TOPIC, pool=POOL,
                          extra_texts={"description": "A preprint, not peer-reviewed."})
    assert cl.codes(rep) == [cl.FAIL_PREPRINT_WITHOUT_CAVEAT]
    # nor a sentence that says the opposite
    rep = cl.check_claims(_preprint_script(payoff="Peer-reviewed and published."),
                          topic=TOPIC, pool=POOL)
    assert cl.codes(rep) == [cl.FAIL_PREPRINT_WITHOUT_CAVEAT]
    # the refusal stands even when the claims list itself is missing
    rep = cl.check_claims(_preprint_script(claims=None), topic=TOPIC)
    assert cl.codes(rep) == [cl.FAIL_PREPRINT_WITHOUT_CAVEAT, cl.FAIL_MISSING]


def test_a_reviewed_fact_asks_for_no_caveat():
    s = copy.deepcopy(SCRIPT)
    s["fact"] = {k: v for k, v in PREPRINT_FACT.items() if k != "needs_caveat"}
    s["fact"]["url"] = "https://doi.org/10.1038/x"
    assert cl.check_claims(s, topic=TOPIC, pool=POOL)["action"] == "pass"
    s["fact"]["needs_caveat"] = False
    assert cl.check_claims(s, topic=TOPIC, pool=POOL)["action"] == "pass"
    assert cl.check_claims(SCRIPT, topic=TOPIC, pool=POOL)["action"] == "pass"   # no record


def test_the_caveat_flag_travels_from_the_fact_rule_to_the_script_check():
    """The rule's check -> fact_record -> 03 `fact` -> this check, on a
    stand-in list (no channel's file)."""
    spec = importlib.util.spec_from_file_location(
        "fact_rule_cf0660", ROOT / "shared" / "factrule" / "fact_rule.py")
    rule = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rule)
    src = {"kinds": ["other"], "tiers": {
        "1": [{"id": "arxiv", "hosts": ["arxiv.org"], "preprint": True},
              {"id": "doi", "hosts": ["doi.org"]}],
        "2": [{"id": "wikipedia", "hosts": ["wikipedia.org"]}]}}
    assert rule.validate_sources(src) == []
    cand = {"text": "Abbott joined the cast in September 2024.", "kind": "other",
            "source": "Wikipedia", "url": "https://en.wikipedia.org/wiki/X",
            "primary_url": "https://arxiv.org/abs/2501.00001"}
    best = rule.best_candidate(rule.check_candidates([cand], src))
    rec = rule.fact_record(best)
    assert rec["needs_caveat"] is True
    assert rule.NEEDS_CAVEAT_KEY == cl.NEEDS_CAVEAT_KEY
    s = copy.deepcopy(SCRIPT)
    s["fact"] = rec
    assert cl.codes(cl.check_claims(s, topic=TOPIC, pool=POOL)) == [cl.FAIL_PREPRINT_WITHOUT_CAVEAT]
    s["commentary"] += " The paper is not yet peer-reviewed."
    assert cl.check_claims(s, topic=TOPIC, pool=POOL)["action"] == "pass"
    reviewed = rule.fact_record(rule.best_candidate(rule.check_candidates(
        [dict(cand, primary_url="https://doi.org/10.1038/x")], src)))
    assert "needs_caveat" not in reviewed


def test_every_violation_has_its_russian_line():
    assert set(cl.REFUSALS_RU) == set(cl.FAIL_CODES)
    for code, line in cl.REFUSALS_RU.items():
        assert line.strip() and any("а" <= ch <= "я" for ch in line.lower()), code


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

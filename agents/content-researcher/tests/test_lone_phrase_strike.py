#!/usr/bin/env python3
"""CF-0886: a hook / payoff claim struck `claim_not_enough` that is the only
sentence of its section gets the phrase pass of CF-0883 - one edit of that
sentence, the rest held to a snapshot, the judge again - not a refusal.

Stand-ins from the window of 2026-10-20..27 (four topics lost so, each with
`failed_attempts: 2` and neither DELETE nor PHRASE offered):

* Reel 27.10 -023 - the hook "Six things about Tulsa King to know before you
  argue about the casting.": the judge found no six in the quote;
* Tech 22.10 -033 - the payoff "Anthropic's funding came in Series E, F and G
  rounds.": "came in" read as all of the funding;
* Reel 27.10 -028 - the payoff restated the video's own fact (2012, the
  announcement) with "long before Hader was cast", which the quote does not
  state; the fact on screen followed. The edit is the fact's one rewording.

What is not let through: a struck claim with another sentence beside it in its
section (DELETE's), `claim_not_entailed`, a commentary claim, a fact already
reworded or whose screen line did not follow, a redone sentence still not
enough (refused).

Offline: the canned answer command of tests/test_check_claims.py."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import check_claims as cc  # noqa: E402
import _claim_ladder as ladder  # noqa: E402
from test_check_claims import JUDGE, bench  # noqa: E402
from test_hook_phrase_pass import edit, go  # noqa: E402

SRC = "wikipedia:Tulsa_King#p1"
TULSA_TEXT = ("Tulsa King is Stallone's first leading role in a scripted television series. "
              "Sheridan wrote the pilot episode in a week. Winter moved the show's setting to "
              "Tulsa, Oklahoma.")
TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    {"id": SRC, "kind": "article", "title": "Tulsa King",
     "url": "https://en.wikipedia.org/wiki/Tulsa_King", "revision_id": 1,
     "revised_at": "2026-10-27T00:00:00Z", "text": TULSA_TEXT}]}


def q(quote):
    return {"source": SRC, "quote": quote}


HOOK = "Six things about Tulsa King to know before you argue about the casting."
FIRST = "Tulsa King is Stallone's first leading role in a scripted television series"
PILOT = "Sheridan wrote the pilot episode in a week"
MOVED = "Winter moved the show's setting to Tulsa, Oklahoma"
WRONG = "Sheridan wrote every episode alone"
SCRIPT = {
    "script_id": "s1", "topic_id": "t1",
    "hook": HOOK,
    "commentary": f"{FIRST}. {PILOT}. {WRONG}.",
    "payoff": "Watch the pilot again.",
    "production_fact": {"beat_text": MOVED, "on_screen": "Setting moved to Tulsa"},
    "claims": [
        {"claim_id": "c1", "where": "hook", "text": HOOK.rstrip("."), "support": [q(FIRST)]},
        {"claim_id": "c2", "where": "commentary", "text": FIRST, "support": [q(FIRST)]},
        {"claim_id": "c3", "where": "commentary", "text": PILOT, "support": [q(PILOT)]},
        {"claim_id": "c4", "where": "commentary", "text": WRONG, "support": [q(PILOT)]},
        {"claim_id": "c5", "where": "on_screen", "text": "Setting moved to Tulsa",
         "support": [q(MOVED)]},
    ],
}
EXTRACT = [{"where": c["where"], "text": c["text"]} for c in SCRIPT["claims"]]
ENTAIL = {HOOK.rstrip("."): "not_enough", FIRST: "follows", PILOT: "follows",
          WRONG: "does_not_follow", "Setting moved to Tulsa": "follows"}


def to_phrase(name, script=SCRIPT, extract=EXTRACT, entail=ENTAIL, rewrite=None, topic=TOPIC):
    """Round 1 strikes c4 (and c1): REWRITE. The rewrite takes c4 out and
    keeps the lone hook: round 2 strikes c1 alone - returns the batch there."""
    batch, cmd, canned = bench(name, script=script, extract=extract, entail=entail, topic=topic)
    (_, _, refused), text, _ = go(batch, cmd)
    assert "REWRITE   s1" in text and not refused, text

    def default(s):
        s["commentary"] = f"{FIRST}. {PILOT}."
        s["claims"] = [c for c in s["claims"] if c["claim_id"] != "c4"]
    edit(batch, rewrite or default)
    res, text, data = go(batch, cmd)
    return batch, cmd, canned, res, text, data


# ------------------------------------------------------------- the grant

def test_tulsa_lone_hook_gets_the_phrase_pass_not_a_refusal():
    """27.10 -023: before CF-0886 this run refused the topic."""
    _, _, _, (problems, _, refused), text, data = to_phrase("cf0886-tulsa")
    assert not refused and "PHRASE    s1" in text, text
    assert "DELETE" not in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["failed_attempts"] == 2, rec
    grant = rec[cc.PHRASE_KEY]
    assert grant["state"] == "granted" and grant["strike_rule"] == "CF-0886", grant
    assert grant["sentences"] == {"hook": [HOOK]}, grant
    assert grant["phrases"] == [], grant
    (strike,) = grant["strikes"]
    assert strike["claim_id"] == "c1" and strike["code"] == "claim_not_enough", strike
    assert strike["fact_claim"] is False and strike["quotes"] == [q(FIRST)], strike
    assert "only sentence of its section" in text and f"quote [{SRC}]" in text, text


def test_the_redone_hook_is_judged_again_and_passes():
    batch, cmd, _, _, _, _ = to_phrase("cf0886-tulsa-ok")

    def redo(s):
        s["hook"] = "Here is what to know about Tulsa King's casting."
        s["claims"] = [c for c in s["claims"] if c["claim_id"] != "c1"]
    edit(batch, redo)
    (problems, _, refused), text, data = go(batch, cmd)
    assert not problems and not refused, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass" and rec["failed_attempts"] == 2, rec
    pp = rec[cc.PHRASE_KEY]
    assert pp["state"] == "judged" and "base" not in pp, pp
    assert pp["changed"]["sentences"]["hook"]["now"] == [
        "Here is what to know about Tulsa King's casting."], pp


def test_a_redone_hook_still_not_enough_refuses():
    """Nothing passes unread: the redone sentence is judged like any claim."""
    batch, cmd, canned, _, _, _ = to_phrase("cf0886-tulsa-fail")
    again = "Seven things about Tulsa King"
    c = json.loads(canned.read_text())
    c["extract"].append({"where": "hook", "text": again})
    canned.write_text(json.dumps(c))

    def redo(s):
        s["hook"] = f"{again}."
        s["claims"][0] = dict(s["claims"][0], text=again)
    edit(batch, redo)
    (_, _, refused), text, data = go(batch, cmd)
    assert len(refused) == 1 and "after the one phrase pass" in text, text
    skip = data["skipped"][0]
    assert skip["reason_code"] == "claim_unsupported", skip
    assert skip["claims_check"][cc.PHRASE_KEY]["state"] == "judged", skip


def test_an_edit_past_the_lone_hook_refuses():
    batch, cmd, _, _, _, _ = to_phrase("cf0886-tulsa-over")

    def over(s):
        s["hook"] = "Here is what to know about Tulsa King."
        s["commentary"] = f"{FIRST}."
    edit(batch, over)
    (_, _, refused), text, _ = go(batch, cmd)
    assert len(refused) == 1 and "went past its sentences" in text, text


ANTH = "Anthropic's funding came in Series E, F and G rounds"


def test_anthropic_lone_payoff_gets_the_phrase_pass():
    """22.10 -033: the same on the payoff."""
    s = copy.deepcopy(SCRIPT)
    s["hook"] = "Tulsa King, in three facts."
    s["claims"] = s["claims"][1:]
    s["payoff"] = f"{ANTH}."
    s["claims"].append({"claim_id": "c6", "where": "payoff", "text": ANTH,
                        "support": [q(FIRST)]})
    extract = [{"where": c["where"], "text": c["text"]} for c in s["claims"]]
    entail = dict(ENTAIL, **{ANTH: "not_enough"})
    _, _, _, (_, _, refused), text, data = to_phrase("cf0886-anth", script=s, extract=extract,
                                                     entail=entail)
    assert not refused and "PHRASE    s1" in text, text
    grant = data["scripts"][0]["claims_check"][cc.PHRASE_KEY]
    assert grant["sentences"] == {"payoff": [f"{ANTH}."]}, grant
    assert [x["claim_id"] for x in grant["strikes"]] == ["c6"], grant


# ------------------------------------------------------------- the video's own fact

CAT = "An animated Cat in the Hat was announced by Illumination in 2012"
CAT_SRC = "wikipedia:Cat_in_the_Hat#p1"
CAT_TEXT = ("In 2012, Illumination announced an animated Cat in the Hat. In March 2024 Hader "
            "was reported cast in the title role.")
CAT_TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    dict(TOPIC["support_text"][0], id=CAT_SRC, title="The Cat in the Hat", text=CAT_TEXT)]}
Q_CAT = {"source": CAT_SRC, "quote": "In 2012, Illumination announced an animated Cat in the Hat"}
Q_HADER = {"source": CAT_SRC, "quote": "In March 2024 Hader was reported cast in the title role"}
CAT_OVER = f"{CAT}, long before Hader was cast"
CAT_SCRIPT = {
    "script_id": "s1", "topic_id": "t1",
    "hook": "The one detail in The Cat in the Hat that changes everything.",
    "commentary": "In March 2024 Hader was reported cast in the title role. Hader wrote it too.",
    "payoff": f"{CAT}.",
    "production_fact": {"beat_text": CAT, "on_screen": "2012: animated Cat announced"},
    "claims": [
        {"claim_id": "c1", "where": "commentary",
         "text": "In March 2024 Hader was reported cast in the title role", "support": [Q_HADER]},
        {"claim_id": "c2", "where": "commentary", "text": "Hader wrote it too",
         "support": [Q_HADER]},
        {"claim_id": "c3", "where": "payoff", "text": CAT, "support": [Q_CAT]},
        {"claim_id": "c4", "where": "on_screen", "text": "2012: animated Cat announced",
         "support": [Q_CAT]},
    ],
}
CAT_EXTRACT = [{"where": c["where"], "text": c["text"]} for c in CAT_SCRIPT["claims"]] + [
    {"where": "payoff", "text": CAT_OVER}]
CAT_ENTAIL = {"In March 2024 Hader was reported cast in the title role": "follows",
              "Hader wrote it too": "does_not_follow", CAT: "follows",
              "2012: animated Cat announced": "follows", CAT_OVER: "not_enough"}


def cat_rewrite(s):
    """The rewrite takes c2 out and restates the fact on the payoff past its
    quote (27.10 -028)."""
    s["commentary"] = "In March 2024 Hader was reported cast in the title role."
    s["payoff"] = f"{CAT_OVER}."
    s["claims"] = [c for c in s["claims"] if c["claim_id"] != "c2"]
    s["claims"][1] = dict(s["claims"][1], text=CAT_OVER)


def test_cat_payoff_fact_restated_past_its_quote_gets_its_one_rewording_here():
    assert JUDGE.is_fact_claim({"where": "payoff", "text": CAT_OVER}, CAT_SCRIPT)
    batch, cmd, _, (_, _, refused), text, data = to_phrase(
        "cf0886-cat", script=CAT_SCRIPT, extract=CAT_EXTRACT, entail=CAT_ENTAIL,
        rewrite=cat_rewrite, topic=CAT_TOPIC)
    assert not refused and "PHRASE    s1" in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["fact_struck"] and rec["refuse_now"], rec
    (strike,) = rec[cc.PHRASE_KEY]["strikes"]
    assert strike["fact_claim"] is True and strike["quotes"] == [Q_CAT], strike
    assert "[the video's own fact]" in text, text

    def redo(s):
        s["payoff"] = f"{CAT}."
        s["claims"][1] = dict(s["claims"][1], text=CAT)
    edit(batch, redo)
    (problems, _, refused), text, data = go(batch, cmd)
    assert not problems and not refused, text
    assert data["scripts"][0]["claims_check"]["action"] == "pass"


def test_a_fact_already_reworded_is_refused_not_phrased():
    """CF-0580: the fact's one rewording was spent - no second one here."""
    batch, cmd, canned = bench("cf0886-cat-reworded", script=CAT_SCRIPT, extract=CAT_EXTRACT,
                               entail=CAT_ENTAIL, topic=CAT_TOPIC)
    go(batch, cmd)
    edit(batch, cat_rewrite)
    data = json.loads(batch.read_text())
    data["scripts"][0]["claims_check"][cc.FACT_REWORD_KEY] = {"rule": "CF-0580", "claims": []}
    batch.write_text(json.dumps(data))
    (_, _, refused), text, _ = go(batch, cmd)
    assert len(refused) == 1 and "PHRASE" not in text, text


# ------------------------------------------------------------- what is not let through

def record(*violations, struck=None, **kw):
    rec = {"violations": list(violations), "mechanics": {"violations": []},
           "struck": struck if struck is not None else
           [{"claim_id": v["claim_id"]} for v in violations if v.get("claim_id")],
           "verdicts": [{"claim_id": "c5", "where": "on_screen", "state": "supported"}]}
    rec.update(kw)
    return rec


def ne(cid, **kw):
    return dict({"code": "claim_not_enough", "claim_id": cid}, **kw)


def test_a_struck_claim_with_another_sentence_in_its_section_is_not_phrased():
    """That one is DELETE's: the section keeps a sentence."""
    s = copy.deepcopy(SCRIPT)
    s["hook"] = f"{HOOK} Watch closely."
    assert ladder.phrase_grant(s, record(ne("c1"))) is None
    assert ladder.phrase_grant(SCRIPT, record(ne("c1")))["sentences"] == {"hook": [HOOK]}


def test_only_not_enough_on_the_hook_or_payoff():
    assert ladder.phrase_grant(SCRIPT, record(dict(ne("c1"), code="claim_not_entailed"))) is None
    s = copy.deepcopy(SCRIPT)
    s["commentary"] = f"{FIRST}."
    assert ladder.phrase_grant(s, record(ne("c2"))) is None, "a commentary claim"
    assert ladder.phrase_grant(SCRIPT, record(ne("c1"), struck=[{"claim_id": "c1"},
                                                                {"claim_id": "c4"}])) is None
    assert ladder.phrase_grant(SCRIPT, record(ne("c1"), refuse_now=True)) is None, \
        "refused at once for anything but the fact"
    mech = record(ne("c1"))
    mech["mechanics"]["violations"] = [{"code": "quote_not_in_source"}]
    assert ladder.phrase_grant(SCRIPT, mech) is None


def test_a_fact_strike_needs_fact_ok_and_the_screen_line_followed():
    rec = record(ne("c1", fact_claim=True), fact_struck=True, refuse_now=True)
    assert ladder.phrase_grant(SCRIPT, rec) is None, "fact_ok not given"
    assert ladder.phrase_grant(SCRIPT, rec, fact_ok=True) is not None
    rec["verdicts"] = [{"claim_id": "c5", "where": "on_screen", "state": "struck"}]
    assert ladder.phrase_grant(SCRIPT, rec, fact_ok=True) is None, "the fact itself fell"


def test_mixed_undeclared_and_lone_strike_is_one_pass():
    rec = record(ne("c1"), {"code": "claim_undeclared", "where": "payoff",
                            "text": "Watch the pilot again"})
    grant = ladder.phrase_grant(SCRIPT, rec)
    assert grant["sentences"] == {"hook": [HOOK], "payoff": ["Watch the pilot again."]}, grant


def test_skill_and_readme_name_cf0886():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    readme = (HERE.parent / "README.md").read_text()
    assert "CF-0886" in skill and "CF-0886" in readme


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

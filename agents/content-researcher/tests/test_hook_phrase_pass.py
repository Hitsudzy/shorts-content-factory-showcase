#!/usr/bin/env python3
"""CF-0883: a topic is not lost to the hook's framing - `scripts/_hook_frame.py`
and the phrase pass of `scripts/_claim_ladder.py`, through `check_claims.py`.

Stand-ins from the Reel funnel of 2026-10-20..27 (4 of 5 `claim_unsupported`
losses were one `claim_undeclared` on the hook / payoff, every declared claim
following):

* 26.10 -008 - the hook "Before you watch Vanguards: Doomsday, know this: ..."
  and the reader's "Vanguards: Doomsday" listed as a claim: a title with a
  subtitle colon is a name, matched to a claim that followed and names it;
* 25.10 -008 - "Everyone missed the part of Wildwood where the film was
  already shooting, before anyone had announced it.": the opener's own words
  are read away, the rest is matched by the root's rule to the hook claim;
* 27.10 -019 - "Here's what nobody tells you about ..." left alone after the
  one rewrite: ONE more edit of that sentence only (`PHRASE`), held to the
  snapshot, judged again, a failure refuses.

And what is not let through: a title no followed claim names, a fact in the
formula's slot that no claim states, a formula that states something itself.

Offline: the answer command is the canned stand-in of tests/test_check_claims.py
(no network, no model)."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import check_claims as cc  # noqa: E402
import _claim_ladder as ladder  # noqa: E402
import _hook_frame as hf  # noqa: E402
from test_check_claims import EXTRACT, JUDGE, ROOT, SCRIPT, bench  # noqa: E402

OPENERS = [
    {"id": "before-you-watch", "template": "Before you watch {x}, know this: {fact}"},
    {"id": "everyone-missed", "template": "Everyone missed the part of {x} where {fact}"},
    {"id": "what-nobody-tells-you", "template": "Here's what nobody tells you about {x}: {fact}"},
    {"id": "almost-didnt", "template": "{x} almost didn't happen, because {fact}"},
]

DOOM_TEXT = ("At San Diego Comic-Con in July 2024, the Russo brothers revealed that the film "
             "previously called Vanguards 5 had a new title: Vanguards: Doomsday. Robert Downey "
             "Jr. was cast as Victor von Doom.")
DOOM_TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    {"id": "wikipedia:Vanguards_Doomsday#p1", "kind": "article", "title": "Vanguards: Doomsday",
     "url": "https://en.wikipedia.org/wiki/Vanguards:_Doomsday", "revision_id": 1,
     "revised_at": "2026-10-20T00:00:00Z", "text": DOOM_TEXT}]}
Q_TITLE = {"source": "wikipedia:Vanguards_Doomsday#p1",
           "quote": "the film previously called Vanguards 5 had a new title: Vanguards: Doomsday"}
Q_DOOM = {"source": "wikipedia:Vanguards_Doomsday#p1",
          "quote": "Robert Downey Jr. was cast as Victor von Doom"}
DOOM_SCRIPT = {
    "script_id": "s1", "topic_id": "t1", "hook_opener_id": "before-you-watch",
    "hook": "Before you watch Vanguards: Doomsday, know this: one quick thing.",
    "commentary": "The film once called Vanguards 5 got a new title: Vanguards: Doomsday. "
                  "Robert Downey Junior was cast as Victor von Doom.",
    "payoff": "Keep that in mind.",
    "production_fact": {"beat_text": "Robert Downey Junior was cast as Victor von Doom",
                        "on_screen": "Downey cast as Doom"},
    "claims": [
        {"claim_id": "c1", "where": "commentary",
         "text": "The film once called Vanguards 5 got a new title: Vanguards: Doomsday",
         "support": [Q_TITLE]},
        {"claim_id": "c2", "where": "commentary",
         "text": "Robert Downey Junior was cast as Victor von Doom", "support": [Q_DOOM]},
        {"claim_id": "c3", "where": "on_screen", "text": "Downey cast as Doom",
         "support": [Q_DOOM]},
    ],
}
DOOM_EXTRACT = [
    {"where": "hook", "text": "Vanguards: Doomsday"},
    {"where": "commentary", "text": "The film once called Vanguards 5 got a new title: Vanguards: Doomsday"},
    {"where": "commentary", "text": "Robert Downey Junior was cast as Victor von Doom"},
    {"where": "on_screen", "text": "Downey cast as Doom"},
]
DOOM_ENTAIL = {c["text"]: "follows" for c in DOOM_SCRIPT["claims"]}


def go(batch, cmd, openers=OPENERS):
    lines = []
    res = cc.check_batch(batch, root=ROOT, write=True, out=lines.append, judge=JUDGE,
                         answer_cmd=cmd, openers=openers)
    return res, "\n".join(lines), json.loads(batch.read_text())


def edit(batch, fn):
    data = json.loads(batch.read_text())
    fn(data["scripts"][0])
    batch.write_text(json.dumps(data))


# ------------------------------------------------------------- 1. not claims

def test_frame_slots_reads_the_formula_away():
    t = "Everyone missed the part of {x} where {fact}"
    assert hf.frame_slots("Everyone missed the part of Wildwood where the film was shot early.",
                          t) == "Wildwood the film was shot early."
    assert hf.frame_slots("Before you watch Vanguards: Doomsday, know this: four things.",
                          "Before you watch {x}, know this: {fact}") \
        == "Vanguards: Doomsday, four things."
    assert hf.frame_slots("Here's what nobody tells you about Tulsa King.",
                          "Here's what nobody tells you about {x}: {fact}") == "Tulsa King."
    assert hf.frame_slots("Wildwood was shot early.", t) is None


def test_only_the_hype_formulas_are_read_away():
    s = {"hook": "Wildwood almost didn't happen, because the money ran out.",
         "hook_opener_id": "almost-didnt"}
    assert hf.frames_of(s, OPENERS) == [], "a formula that states something is not read away"
    s = {"hook": "Everyone missed the part of Wildwood where it was shot early."}
    assert hf.frames_of(s, OPENERS) == [OPENERS[1]["template"]], "found without the id"




def test_title_name():
    assert hf.title_name(JUDGE, "Vanguards: Doomsday") == "Vanguards Doomsday"
    assert hf.title_name(JUDGE, "Vanguards: the film nobody saw coming") is None
    assert hf.title_name(JUDGE, "Vanguards Doomsday") is None, "no colon - the root's own rule"


def test_doomsday_title_in_the_hook_is_not_a_claim():
    """26.10 -008: one pass, no rewrite asked, the title read as a name."""
    batch, cmd, _ = bench("cf0883-doom", script=DOOM_SCRIPT, extract=DOOM_EXTRACT,
                          entail=DOOM_ENTAIL, topic=DOOM_TOPIC)
    (problems, _, refused), text, data = go(batch, cmd)
    assert not problems and not refused, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass" and rec["failed_attempts"] == 0, rec
    assert rec[cc.RELIEF_KEY] == [{"rule": "CF-0883", "where": "hook",
                                   "text": "Vanguards: Doomsday", "why": "bare_title",
                                   "read_as": "Vanguards Doomsday", "matched": ["c1"]}], rec
    row = [x for x in rec["extracted"] if x["where"] == "hook"][0]
    assert row["matched"] == ["c1"] and row["matched_by"] == "CF-0883:bare_title", row


def test_a_title_no_followed_claim_names_stays_undeclared():
    s = copy.deepcopy(DOOM_SCRIPT)
    s["hook"] = "Before you watch Vanguards: Secret Wars, know this: one quick thing."
    extract = [dict(DOOM_EXTRACT[0], text="Vanguards: Secret Wars")] + DOOM_EXTRACT[1:]
    batch, cmd, _ = bench("cf0883-doom-other", script=s, extract=extract,
                          entail=DOOM_ENTAIL, topic=DOOM_TOPIC)
    (problems, _, refused), text, data = go(batch, cmd)
    assert "REWRITE   s1" in text and "claim_undeclared" in text, text
    assert cc.RELIEF_KEY not in data["scripts"][0]["claims_check"]


def test_a_title_named_only_by_a_struck_claim_stays_undeclared():
    entail = dict(DOOM_ENTAIL)
    entail[DOOM_SCRIPT["claims"][0]["text"]] = "does_not_follow"
    batch, cmd, _ = bench("cf0883-doom-struck", script=DOOM_SCRIPT, extract=DOOM_EXTRACT,
                          entail=entail, topic=DOOM_TOPIC)
    (problems, _, refused), text, data = go(batch, cmd)
    rec = data["scripts"][0]["claims_check"]
    assert "REWRITE   s1" in text and cc.RELIEF_KEY not in rec, text
    assert "claim_undeclared" in cc.codes_of(rec), rec


WILD_TEXT = ("Laika quietly began shooting Wildwood in May 2021, before the film was announced. "
             "The announcement came that September.")
WILD_TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    {"id": "wikipedia:Wildwood#p1", "kind": "article", "title": "Wildwood",
     "url": "https://en.wikipedia.org/wiki/Wildwood_(film)", "revision_id": 1,
     "revised_at": "2026-10-20T00:00:00Z", "text": WILD_TEXT}]}
Q_WILD = {"source": "wikipedia:Wildwood#p1",
          "quote": "Laika quietly began shooting Wildwood in May 2021, before the film was "
                   "announced"}
WILD_HOOK = ("Everyone missed the part of Wildwood where the film was already shooting, before "
             "anyone had announced it.")
WILD_SCRIPT = {
    "script_id": "s1", "topic_id": "t1", "hook_opener_id": "everyone-missed",
    "hook": WILD_HOOK,
    "commentary": "The announcement came that September.",
    "payoff": "Keep that in mind.",
    "production_fact": {"beat_text": "the film was already shooting, before anyone had "
                                     "announced it",
                        "on_screen": "Shooting began May 2021"},
    "claims": [
        {"claim_id": "c1", "where": "hook",
         "text": "the film was already shooting, before anyone had announced it",
         "support": [Q_WILD]},
        {"claim_id": "c2", "where": "commentary", "text": "The announcement came that September",
         "support": [{"source": "wikipedia:Wildwood#p1",
                      "quote": "The announcement came that September"}]},
        {"claim_id": "c3", "where": "on_screen", "text": "Shooting began May 2021",
         "support": [Q_WILD]},
    ],
}
WILD_EXTRACT = [{"where": "hook", "text": WILD_HOOK.rstrip(".")},
                {"where": "commentary", "text": "The announcement came that September"},
                {"where": "on_screen", "text": "Shooting began May 2021"}]
WILD_ENTAIL = {c["text"]: "follows" for c in WILD_SCRIPT["claims"]}


def test_wildwood_opener_words_do_not_dilute_the_declared_hook_claim():
    """25.10 -008: the formula's five words put the declared hook claim under
    the root's coverage; read without them, it covers the rest."""
    assert JUDGE.match_extracted([WILD_EXTRACT[0]], WILD_SCRIPT["claims"], WILD_SCRIPT) == [[]], \
        "the root alone reads the formula as part of the claim"
    batch, cmd, _ = bench("cf0883-wild", script=WILD_SCRIPT, extract=WILD_EXTRACT,
                          entail=WILD_ENTAIL, topic=WILD_TOPIC)
    (problems, _, refused), text, data = go(batch, cmd)
    assert not problems and not refused, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass", rec
    (r,) = rec[cc.RELIEF_KEY]
    assert r["why"] == "opener_frame" and r["matched"] == ["c1"], r
    assert r["read_as"].startswith("Wildwood the film was already shooting"), r


def test_a_fact_in_the_slot_that_no_claim_states_stays_undeclared():
    s = copy.deepcopy(WILD_SCRIPT)
    s["hook"] = ("Everyone missed the part of Wildwood where the studio nearly went bankrupt "
                 "making it.")
    s["claims"] = s["claims"][1:]
    extract = [{"where": "hook", "text": s["hook"].rstrip(".")}] + WILD_EXTRACT[1:]
    batch, cmd, _ = bench("cf0883-wild-new", script=s, extract=extract, entail=WILD_ENTAIL,
                          topic=WILD_TOPIC)
    (problems, _, refused), text, data = go(batch, cmd)
    assert "REWRITE   s1" in text and "claim_undeclared" in text, text


def test_no_library_no_formula_read_away():
    batch, cmd, _ = bench("cf0883-wild-nolib", script=WILD_SCRIPT, extract=WILD_EXTRACT,
                          entail=WILD_ENTAIL, topic=WILD_TOPIC)
    (problems, _, refused), text, _ = go(batch, cmd, openers=[])
    assert "REWRITE   s1" in text, text


# ------------------------------------------------------------- 2. phrase pass

TAIL = "The finale is only the first answer"


def phrase_bench(name):
    """Round 1 strikes c3; the rewrite takes it out but ends on a framing the
    reader lists and nothing declares (21.10 -003 "the number one opening is
    only the first answer"): PHRASE, not a refusal."""
    extract = EXTRACT + [{"where": "payoff", "text": TAIL}]
    batch, cmd, canned = bench(name, extract=extract)
    go(batch, cmd)

    def rewrite(s):
        s["payoff"] = f"What a bold finale. {TAIL}."
        s["commentary"] = "The finale settles it."
        s["claims"] = s["claims"][:2]
    edit(batch, rewrite)
    (problems, _, refused), text, data = go(batch, cmd)
    assert not refused and "PHRASE    s1" in text, text
    return batch, cmd, canned, data


def test_the_phrase_pass_is_granted_for_the_framing_only():
    _, _, _, data = phrase_bench("cf0883-phrase")
    rec = data["scripts"][0]["claims_check"]
    assert rec["failed_attempts"] == 2, rec
    grant = rec[cc.PHRASE_KEY]
    assert grant["state"] == "granted" and grant["rule"] == "CF-0883", grant
    assert grant["sentences"] == {"payoff": [f"{TAIL}."]}, grant
    assert grant["phrases"] == [{"where": "payoff", "text": TAIL}], grant


def test_the_redone_hook_is_judged_again_and_passes():
    batch, cmd, _, _ = phrase_bench("cf0883-phrase-ok")
    edit(batch, lambda s: s.__setitem__("payoff", "What a bold finale. Watch it again."))
    (problems, _, refused), text, data = go(batch, cmd)
    assert not problems and not refused, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass" and rec["failed_attempts"] == 2, rec
    pp = rec[cc.PHRASE_KEY]
    assert pp["state"] == "judged" and "base" not in pp, pp
    assert pp["changed"] == {"sentences": {"payoff": {"was": [f"{TAIL}."],
                                                      "now": ["Watch it again."]}}}, pp


def test_a_failure_after_the_phrase_pass_refuses():
    batch, cmd, canned, _ = phrase_bench("cf0883-phrase-fail")
    c = json.loads(canned.read_text())
    c["extract"].append({"where": "payoff", "text": "Nobody saw it coming"})
    canned.write_text(json.dumps(c))
    edit(batch, lambda s: s.__setitem__("payoff", "What a bold finale. Nobody saw it coming."))
    (problems, _, refused), text, data = go(batch, cmd)
    assert len(refused) == 1 and "after the one phrase pass" in text, text
    skip = data["skipped"][0]
    assert skip["reason_code"] == "claim_unsupported", skip
    assert skip["claims_check"][cc.PHRASE_KEY]["state"] == "judged", skip
    assert "phrase pass" in skip["reason"], skip["reason"]


def test_an_edit_past_the_phrase_refuses():
    batch, cmd, _, _ = phrase_bench("cf0883-phrase-over")

    def over(s):
        s["payoff"] = "What a bold finale."
        s["commentary"] = "The finale settles everything."
    edit(batch, over)
    (_, _, refused), text, data = go(batch, cmd)
    assert len(refused) == 1 and "went past its sentences" in text, text
    assert "commentary: changed" in text, text
    pp = data["skipped"][0]["claims_check"][cc.PHRASE_KEY]
    assert pp["state"] == ladder.STATE_NOT_PHRASE, pp


def test_no_phrase_pass_for_an_undeclared_commentary_statement():
    """The framing lives on the hook and the payoff; a statement in the
    commentary is a fact of the video - the old ladder."""
    extract = EXTRACT + [{"where": "commentary", "text": "months before anyone knew"}]
    batch, cmd, _ = bench("cf0883-phrase-commentary", extract=extract)
    go(batch, cmd)

    def rewrite(s):
        s["commentary"] = "The finale settles it, months before anyone knew."
        s["claims"] = s["claims"][:2]
    edit(batch, rewrite)
    (_, _, refused), text, _ = go(batch, cmd)
    assert len(refused) == 1 and "PHRASE" not in text, text


def test_phrase_grant_needs_nothing_struck():
    s = copy.deepcopy(SCRIPT)
    rec = {"violations": [{"code": "claim_undeclared", "where": "hook", "text": "Kerry"}],
           "struck": [{"claim_id": "c3"}], "mechanics": {"violations": []}}
    assert ladder.phrase_grant(s, rec) is None
    rec["struck"] = []
    assert ladder.phrase_grant(s, rec)["sentences"] == {"hook": [s["hook"]]}


def test_skill_and_readme_name_the_phrase_pass():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    readme = (HERE.parent / "README.md").read_text()
    for words in ("**`PHRASE`**", "`phrase_pass`", "`not_claims`", "CF-0883"):
        assert words in skill, words
    assert "CF-0883" in readme and "`phrase_pass`" in readme


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

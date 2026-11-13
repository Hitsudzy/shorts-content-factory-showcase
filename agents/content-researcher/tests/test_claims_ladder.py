#!/usr/bin/env python3
"""CF-0807: the claims ladder of `scripts/check_claims.py` around what needs
no model, and the one deletion-only edit (`scripts/_claim_ladder.py`).

Pinned here, on the three losses of `example-tech/2026-10-19T0844Z` (each 32
of 33 claims supported):

* 022 - a mechanics finding (`claim_text_not_in_field` after the hook was
  reworded for check-hook-opener) is reported before the judge and spends no
  attempt; the free runs are capped (`free_fixes`), past the cap the old rule;
* 023 - a claim that opens on a pronoun ("It began as Project Tailwind…") is
  sent back before the judge as `claim_subject_pronoun`, no model call;
* 006 - after the one rewrite, a strike left on one line gets ONE edit that
  only deletes; the edit is held to the snapshot mechanically, the result is
  judged again, a failure refuses the topic; `deletion_pass` says what went.

Offline: the answer command is the stand-in of tests/test_check_claims.py
(canned answers, no network, no model)."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import check_claims as cc  # noqa: E402
import _claim_ladder as ladder  # noqa: E402
from test_check_claims import EXTRACT, SCRIPT, bench, run  # noqa: E402


def calls(batch):
    """The model calls asked so far (one cache file per request)."""
    cache = batch.parent / "work" / "claim-judge-cache"
    return len([p for p in cache.glob("*.json")]) if cache.is_dir() else 0


def edit(batch, fn):
    data = json.loads(batch.read_text())
    fn(data["scripts"][0])
    batch.write_text(json.dumps(data))


def rewrite_once(batch, cmd):
    """The first failure (c3 struck) and the edit that takes it out."""
    run(batch, cmd)

    def fix(s):
        s["commentary"] = "The finale settles it."
        s["claims"] = s["claims"][:2]
    edit(batch, fix)
    (problems, _, refused), text, data = run(batch, cmd)
    assert not problems and not refused, text
    assert data["scripts"][0]["claims_check"]["failed_attempts"] == 1


# ---------------------------------------------------------------- 1. mechanics

def test_a_mechanics_slip_after_a_green_check_spends_no_attempt():
    """022: claims passed after the one rewrite, the hook was reworded for the
    opener gate, the claim's text no longer stands in the hook. Before
    CF-0807 that run was the second failure and took the topic."""
    batch, cmd, _ = bench("mech-022")
    rewrite_once(batch, cmd)
    asked = calls(batch)
    edit(batch, lambda s: s.__setitem__("hook", "Here is the twist: Kerry did it to protect Noah."))
    (problems, _, refused), text, data = run(batch, cmd)
    assert not refused and "FAIL      s1" in text and "claim_text_not_in_field" in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["failed_attempts"] == 1 and rec[cc.FREE_FIXES_KEY] == 1, rec
    assert rec[cc.PREJUDGE_KEY] is True and rec["asked"] == 0, rec
    assert calls(batch) == asked, "nothing is asked before the mechanics hold"
    # the same text again is UNCHANGED, not another free run
    (_, _, refused), text, data = run(batch, cmd)
    assert "UNCHANGED s1" in text and data["scripts"][0]["claims_check"][cc.FREE_FIXES_KEY] == 1

    def fix(s):
        s["hook"] = "Kerry killed Hal to protect Noah."
    edit(batch, fix)
    (problems, _, refused), text, data = run(batch, cmd)
    assert not problems and not refused, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass" and rec["failed_attempts"] == 1, rec
    assert rec[cc.FREE_FIXES_KEY] == 1, "the count of free runs is kept, never reset"


def test_free_runs_are_capped_and_past_the_cap_mechanics_count_again():
    batch, cmd, _ = bench("mech-cap")
    rewrite_once(batch, cmd)
    for n in range(1, cc.FREE_FIXES_ALLOWED + 1):
        edit(batch, lambda s, n=n: s.__setitem__("hook", f"Kerry did it, take {n}."))
        (_, _, refused), text, data = run(batch, cmd)
        rec = data["scripts"][0]["claims_check"]
        assert not refused and rec[cc.FREE_FIXES_KEY] == n and rec["failed_attempts"] == 1, text
    edit(batch, lambda s: s.__setitem__("hook", "Kerry did it, once more."))
    (_, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "REFUSE    s1" in text, text
    assert data["skipped"][0]["claims_check"]["failed_attempts"] == 2


def test_a_fatal_mechanics_finding_still_refuses_at_once():
    from test_check_claims import TOPIC
    batch, cmd, _ = bench("mech-fatal", topic=dict(TOPIC, support_check={"state": "failed"}))
    (_, _, refused), text, _ = run(batch, cmd)
    assert len(refused) == 1 and "no support text" in text, text


# ---------------------------------------------------------------- 2. pronouns

def test_pronoun_heads():
    yes = {"It began as Project Tailwind, a notebook.": "It",
           "These make the chip fast.": "These",
           "That computer runs Linux.": "That",
           "Now it runs code on them.": "Now it",
           "Two. These cores are new.": "These",
           "1) They shipped it in May.": "They",
           "First, it learns from documents.": "it",
           "\"Both ship in May.\"": "Both",
           "It's the first Arm laptop.": "It's",
           "And this one costs $999.": "And this"}
    for text, head in yes.items():
        assert ladder.pronoun_head(text) == head, (text, ladder.pronoun_head(text))
    for text in ("Its price is $999.", "Items ship in May.", "Thailand gets it first.",
                 "NotebookLM began as Project Tailwind.", "Nvidia says this is new.",
                 "Two GPUs ship in May."):
        assert ladder.pronoun_head(text) is None, text


def test_a_fragment_claim_inside_a_pronoun_sentence_is_caught():
    script = {"payoff": "Short. It began as Project Tailwind, a notebook.",
              "claims": [{"claim_id": "c1", "where": "payoff",
                          "text": "began as Project Tailwind"}]}
    out = ladder.pronoun_violations(script, {"payoff": script["payoff"]})
    assert [v["code"] for v in out] == [ladder.PRONOUN_CODE], out
    script["payoff"] = "Short. Google's notebook began as Project Tailwind."
    assert ladder.pronoun_violations(script, {"payoff": script["payoff"]}) == []


def test_a_pronoun_claim_is_sent_back_before_the_judge():
    """023: "It began as Project Tailwind…" - the judge could not tell what
    "It" is. Now it never gets there: FAIL, nothing asked, no attempt."""
    s = copy.deepcopy(SCRIPT)
    s["payoff"] = "It began as a bold finale."
    s["claims"].append({"claim_id": "c4", "where": "payoff", "text": "It began as a bold finale",
                        "support": [{"source": "wikipedia:Harbourlights#e8",
                                     "quote": "During the game, John tells Kerry"}]})
    batch, cmd, _ = bench("pronoun-023", script=s)
    (problems, _, refused), text, data = run(batch, cmd)
    assert not refused and "claim_subject_pronoun c4" in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["failed_attempts"] == 0 and rec["asked"] == 0 and calls(batch) == 0, rec
    assert "name the subject" in text, text


def test_a_pronoun_claim_the_judge_already_passed_is_not_sent_back():
    """6b's rerun on frozen text must not become a text edit: a claim read as
    following on an earlier run, in the same words, keeps its pronoun."""
    batch, cmd, canned = bench("pronoun-held")
    rewrite_once(batch, cmd)

    def pretend(s):
        rec = s["claims_check"]
        for v in rec["verdicts"]:
            if v["claim_id"] == "c1":
                v["text"] = "It killed Hal to protect Noah"
        s["hook"] = "It killed Hal to protect Noah."
        s["claims"][0]["text"] = "It killed Hal to protect Noah"
        s["production_fact"]["beat_text"] = "It killed Hal to protect Noah"
    edit(batch, pretend)
    c = json.loads(canned.read_text())
    c["entail"]["It killed Hal to protect Noah"] = "follows"
    c["extract"][0] = {"where": "hook", "text": "It killed Hal to protect Noah"}
    canned.write_text(json.dumps(c))
    (problems, _, refused), text, _ = run(batch, cmd)
    assert "claim_subject_pronoun" not in text and not refused, text


# ------------------------------------------------------------ 3. deletion pass

def second_failure(name, extra_sentence="And Zorvath is behind the kill!", **kw):
    """The second failure with only c3 struck: the writer kept the claim."""
    batch, cmd, canned = bench(name, **kw)
    run(batch, cmd)
    edit(batch, lambda s: s.__setitem__(
        "commentary", f"The finale settles it. {extra_sentence} What a night."))
    (problems, _, refused), text, data = run(batch, cmd)
    assert not refused and "DELETE    s1" in text, text
    return batch, cmd, canned, data


def test_the_deletion_pass_takes_the_struck_sentence_out_and_passes():
    """006: the topic is not dropped for one deletable line."""
    batch, cmd, _, data = second_failure("delete-pass")
    rec = data["scripts"][0]["claims_check"]
    assert rec["failed_attempts"] == 2, rec
    grant = rec[cc.DELETION_KEY]
    assert grant["state"] == "granted" and grant["rule"] == "CF-0807", grant
    assert grant["sentences"] == {"commentary": ["And Zorvath is behind the kill!"]}, grant

    def delete(s):
        s["commentary"] = "The finale settles it. What a night."
        s["claims"] = s["claims"][:2]
    edit(batch, delete)
    (problems, _, refused), text, data = run(batch, cmd)
    assert not problems and not refused, text
    assert "check_narration_budget.py" in text, "the shorter text is read for length again"
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass" and rec["failed_attempts"] == 2, rec
    dp = rec[cc.DELETION_KEY]
    assert dp["state"] == "judged" and "base" not in dp, dp
    assert dp["removed"] == {"sentences": {"commentary": ["And Zorvath is behind the kill!"]},
                             "graphics": [], "claims": ["c3"]}, dp


def test_a_failure_after_the_deletion_pass_refuses_the_topic():
    batch, cmd, canned, _ = second_failure("delete-fail")

    def delete(s):
        s["commentary"] = "The finale settles it. What a night."
        s["claims"] = s["claims"][:2]
    edit(batch, delete)
    c = json.loads(canned.read_text())
    c["extract"].append({"where": "commentary", "text": "What a night"})   # undeclared
    canned.write_text(json.dumps(c))
    (problems, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "after the one deletion pass" in text, text
    skip = data["skipped"][0]
    assert skip["claims_check"]["failed_attempts"] == 3, skip
    assert skip["claims_check"][cc.DELETION_KEY]["state"] == "judged"
    assert "deletion pass" in skip["reason"], skip["reason"]


def test_deleting_a_sentence_that_holds_no_struck_claim_refuses():
    batch, cmd, _, _ = second_failure("delete-extra")

    def delete(s):
        s["commentary"] = "The finale settles it."            # "What a night." went too
        s["claims"] = s["claims"][:2]
    edit(batch, delete)
    (_, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "holds no struck claim" in text, text


def test_a_rewritten_claim_entry_is_not_a_deletion():
    batch, cmd, _, _ = second_failure("delete-claims")

    def delete(s):
        s["commentary"] = "The finale settles it. What a night."
        s["claims"] = s["claims"][:2]
        s["claims"][0]["support"][0]["quote"] = "she killed Hal"
    edit(batch, delete)
    (_, _, refused), text, _ = run(batch, cmd)
    assert len(refused) == 1 and "claims[] c1" in text, text


def test_a_mechanics_slip_inside_the_deletion_pass_is_still_free():
    """The sentence went but its claim stayed: `claim_text_not_in_field` is a
    free fix, and the pass is held to its snapshot on the run after it."""
    batch, cmd, _, _ = second_failure("delete-mech")
    edit(batch, lambda s: s.__setitem__("commentary", "The finale settles it. What a night."))
    (_, _, refused), text, data = run(batch, cmd)
    assert not refused and "claim_text_not_in_field" in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec[cc.DELETION_KEY]["state"] == "granted" and rec["failed_attempts"] == 2, rec
    edit(batch, lambda s: s.__setitem__("claims", s["claims"][:2]))
    (problems, _, refused), text, data = run(batch, cmd)
    assert not problems and not refused, text
    assert data["scripts"][0]["claims_check"][cc.DELETION_KEY]["state"] == "judged"


def test_no_deletion_pass_when_the_section_would_be_left_empty():
    """The struck claim is the payoff's only sentence: deleting it leaves no
    payoff - the topic is refused as before."""
    s = copy.deepcopy(SCRIPT)
    s["commentary"] = "The finale settles it."
    s["payoff"] = "Zorvath is behind the kill."
    s["claims"][2]["where"] = "payoff"
    extract = EXTRACT[:2] + [{"where": "payoff", "text": "Zorvath is behind the kill"}]
    batch, cmd, _ = bench("delete-empty", script=s, extract=extract)
    run(batch, cmd)
    edit(batch, lambda s: s.__setitem__("payoff", "Zorvath is behind the kill!"))
    (_, _, refused), text, _ = run(batch, cmd)
    assert len(refused) == 1 and "DELETE" not in text, text


def test_grant_and_check_on_a_graphic():
    """006's line was a graphic (g15 "Replaces: Windows 11 Home"): the graphic
    is removed whole, its claim with it; a changed graphic is not a deletion."""
    g1 = {"graphic_id": "g1", "template": "spec_card", "data": {"rows": [1]}, "values": []}
    g15 = {"graphic_id": "g15", "template": "spec_card", "data": {"rows": [2]}, "values": []}
    script = {"hook": "A new laptop.", "commentary": "It ships in May. Nice.", "payoff": "Ok.",
              "production_fact": {"beat_text": "x"}, "graphics": [g1, g15],
              "claims": [{"claim_id": "c1", "where": "graphic:g1", "text": "RAM: 32 GB"},
                         {"claim_id": "c33", "where": "graphic:g15",
                          "text": "Replaces: Windows 11 Home"}]}
    record = {"mechanics": {"violations": []}, "refuse_now": False, "fact_struck": False,
              "violations": [{"code": "claim_not_enough", "claim_id": "c33",
                              "fact_claim": False}]}
    grant = ladder.grant(script, record)
    assert grant and grant["graphics"] == ["g15"] and grant["sentences"] == {}, grant
    after = copy.deepcopy(script)
    after["graphics"] = [g1]
    after["claims"] = after["claims"][:1]
    problems, removed = ladder.deletion_problems(after, grant)
    assert problems == [] and removed["graphics"] == ["g15"] and removed["claims"] == ["c33"]
    changed = copy.deepcopy(after)
    changed["graphics"][0] = dict(g1, data={"rows": [9]})
    problems, _ = ladder.deletion_problems(changed, grant)
    assert any("graphic:g1: changed" in p for p in problems), problems
    # a fact strike, an undeclared claim or a mechanics finding gets no pass
    for bad in ({"fact_struck": True}, {"violations": [{"code": "claim_undeclared"}]},
                {"mechanics": {"violations": [{"code": "quote_not_in_source"}]}}):
        assert ladder.grant(script, dict(record, **bad)) is None, bad


def test_a_reworded_sentence_is_not_a_deletion():
    script = {"hook": "A.", "commentary": "One fact. Struck line here. Two fact.", "payoff": "P.",
              "claims": [{"claim_id": "c2", "where": "commentary", "text": "Struck line here"}]}
    record = {"mechanics": {"violations": []},
              "violations": [{"code": "claim_not_entailed", "claim_id": "c2"}]}
    grant = ladder.grant(script, record)
    ok = dict(script, commentary="One fact.  Two fact.", claims=[])
    assert ladder.deletion_problems(ok, grant)[0] == []
    worded = dict(script, commentary="One fact. Two facts.", claims=[])
    problems, _ = ladder.deletion_problems(worded, grant)
    assert problems and "adds and rewords nothing" in problems[0], problems


def test_skill_and_readme_name_the_new_ladder():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    readme = (HERE.parent / "README.md").read_text()
    for words in ("**`DELETE`**", "`claim_subject_pronoun`", "`deletion_pass`", "`free_fixes`",
                  "CF-0807"):
        assert words in skill, words
    assert "CF-0807" in readme


def test_style_gates_come_before_the_claims_check_in_step_6():
    """CF-0807 item 4: check-hook-opener and the other style gates rewrite
    the text, so they run BEFORE the claims check, not after it."""
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    step6 = skill[skill.index("\n6. **Hold the batch to the budget"):skill.index("\n6b. **")]

    def at(cmd):
        return step6.index(f"scripts/{cmd} \\\n")
    claims = at("check_claims.py")
    for gate in ("check_hook_opener.py", "check_number_density.py", "check_production_fact.py",
                 "check_narration_budget.py"):
        assert at(gate) < claims, gate
    assert step6.index("shared/factrule/claims.py \\\n") < claims


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

#!/usr/bin/env python3
"""CF-0553: `scripts/check_claims.py` - the writer's ladder around the root's
claim judge (`shared/factrule/claim_judge.py`).

Pinned here: the record written onto the script (`claims_check`, the root's
contract for `03` reads it), the one edit (REWRITE -> UNCHANGED spends
nothing -> an edit that passes / an edit that fails again is refused into
`skipped[]` as `claim_unsupported`), the video's own fact without footing is
refused at once, a missing field is a field to fix and not an attempt, and
a model that cannot be asked is exit 3 with nothing written.

Offline: the answer command is a stand-in written here that answers from a
canned file; no network, no model. The texts are short synthetic stand-ins
(the Harbourlights 0701Z line "Zorvath is behind the kill" against a summary in
which Kerry kills Hal)."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import check_claims as cc  # noqa: E402

ROOT = cc.find_root()
JUDGE = cc.load_judge(ROOT)
_TMP = tmp_root("cr-check-claims-")

SUMMARY = ("John learns from Zorvath that Noah freed and brought him to the island. "
           "During the game, John tells Kerry he knows she killed Hal to protect Noah.")
TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    {"id": "wikipedia:Harbourlights#e8", "kind": "episode_summary", "title": "Harbourlights",
     "url": "https://en.wikipedia.org/wiki/Harbourlights_(TV_series)", "revision_id": 1,
     "revised_at": "2026-10-05T00:00:00Z", "text": SUMMARY}]}
Q_KERRY = {"source": "wikipedia:Harbourlights#e8", "quote": "she killed Hal to protect Noah"}
Q_ZORVATH = {"source": "wikipedia:Harbourlights#e8",
              "quote": "John learns from Zorvath that Noah freed and brought him"}
SCRIPT = {
    "script_id": "s1", "topic_id": "t1",
    "hook": "Kerry killed Hal to protect Noah.",
    "commentary": "The finale settles it. And Zorvath is behind the kill.",
    "payoff": "What a bold finale.",
    "production_fact": {"beat_text": "Kerry killed Hal to protect Noah",
                        "on_screen": "Kerry killed Hal"},
    "claims": [
        {"claim_id": "c1", "where": "hook", "text": "Kerry killed Hal to protect Noah",
         "support": [Q_KERRY]},
        {"claim_id": "c2", "where": "on_screen", "text": "Kerry killed Hal",
         "support": [Q_KERRY]},
        {"claim_id": "c3", "where": "commentary", "text": "Zorvath is behind the kill",
         "support": [Q_ZORVATH]},
    ],
}
EXTRACT = [{"where": "hook", "text": "Kerry killed Hal to protect Noah"},
           {"where": "on_screen", "text": "Kerry killed Hal"},
           {"where": "commentary", "text": "Zorvath is behind the kill"}]
ENTAIL = {"Kerry killed Hal to protect Noah": "follows", "Kerry killed Hal": "follows",
          "Zorvath is behind the kill": "does_not_follow"}

FAKE = r'''
import json, sys
req, out, canned = sys.argv[1:4]
r = json.load(open(req)); c = json.load(open(canned))
if c.get("exit"):
    sys.stderr.write(c.get("stderr", "")); sys.exit(c["exit"])
if r["kind"] == "extract":
    texts = r["payload"]["texts"]
    a = {"claims": [e for e in c["extract"] if e["where"] in texts
                    and e["text"].lower() in texts[e["where"]].lower()]}
else:
    a = {"verdict": c["entail"].get(r["payload"]["claim"], "not_enough"), "reason": "canned",
         "reveal": r["payload"]["claim"] in c.get("reveal", [])}
json.dump(a, open(out, "w"))
'''


def bench(name, script=None, extract=EXTRACT, entail=ENTAIL, topic=None, **extra):
    d = _TMP / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "fake.py").write_text(FAKE)
    canned = d / "canned.json"
    canned.write_text(json.dumps(dict(extract=extract, entail=entail, **extra)))
    (d / "01-trend-hunter.json").write_text(json.dumps({"topics": [topic or TOPIC]}))
    batch = d / "03-content-researcher.json"
    batch.write_text(json.dumps({"scripts": [copy.deepcopy(script or SCRIPT)], "skipped": []}))
    cmd = f"{sys.executable} {d / 'fake.py'} {{request}} {{answer}} {canned}"
    return batch, cmd, canned


def run(batch, cmd, write=True):
    lines = []
    res = cc.check_batch(batch, root=ROOT, write=write, out=lines.append, judge=JUDGE,
                         answer_cmd=cmd)
    return res, "\n".join(lines), json.loads(batch.read_text())


def test_constants_match_the_root():
    assert cc.RECORD_KEY == JUDGE.CHECK_FIELD
    assert cc.SKIP_REASON_CODE == JUDGE.SKIP_REASON_CODE
    assert cc.CLAIMS_FIELD == JUDGE.claims.CLAIMS_FIELD


def test_the_struck_claim_asks_for_one_rewrite_then_an_unchanged_rerun_spends_nothing():
    batch, cmd, _ = bench("rewrite")
    (problems, records, refused), text, data = run(batch, cmd)
    assert refused == [] and len(problems) == 1, (problems, text)
    assert "REWRITE   s1" in text and "claim_not_entailed c3" in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "fail" and rec["failed_attempts"] == 1, rec
    assert [s["claim_id"] for s in rec["struck"]] == ["c3"]
    (problems, _, refused), text, data = run(batch, cmd)
    assert "UNCHANGED s1" in text and refused == [], text
    assert data["scripts"][0]["claims_check"]["failed_attempts"] == 1
    assert data["scripts"][0]["claims_check"]["unchanged_reruns"] == 1


def test_the_edit_without_the_claim_passes():
    batch, cmd, _ = bench("edit-pass")
    run(batch, cmd)
    data = json.loads(batch.read_text())
    s = data["scripts"][0]
    s["commentary"] = "The finale settles it."
    s["claims"] = s["claims"][:2]
    batch.write_text(json.dumps(data))
    (problems, records, refused), text, data = run(batch, cmd)
    assert not problems and not refused, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["action"] == "pass" and rec["failed_attempts"] == 1, rec
    assert {v["state"] for v in rec["verdicts"]} == {"supported"}


def test_an_edit_that_fails_again_is_refused_as_claim_unsupported():
    batch, cmd, _ = bench("edit-fail")
    run(batch, cmd)
    data = json.loads(batch.read_text())
    data["scripts"][0]["commentary"] = "The finale settles it. And Zorvath is behind the kill!"
    batch.write_text(json.dumps(data))
    # CF-0807: the second failure, with only a struck claim left, is the one
    # deletion pass - and an edit after it that rewords instead of deleting
    # refuses the topic.
    (problems, _, refused), text, data = run(batch, cmd)
    assert not refused and "DELETE    s1" in text, text
    data["scripts"][0]["commentary"] = "The finale settles it. And Zorvath planned the kill!"
    batch.write_text(json.dumps(data))
    (problems, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "REFUSE    s1" in text, text
    assert "not a deletion" in data["skipped"][0]["reason"], data["skipped"][0]["reason"]
    assert data["scripts"] == []
    skip = data["skipped"][0]
    assert skip["reason_code"] == "claim_unsupported" and skip["stage"] == "scripts", skip
    assert skip["claims_check"]["failed_attempts"] == 3
    assert skip["claims_check"]["deletion_pass"]["state"] == "not_deletion_only"
    assert cc.main([str(batch), "--answer-cmd", cmd]) in (0, 3)   # nothing left to judge


def test_the_struck_fact_gets_one_rewording_not_a_refusal():
    """CF-0580: the video's own fact that does not follow is not refused at
    once - the first failure is REWORD, with the fact's quotes printed."""
    entail = dict(ENTAIL, **{"Kerry killed Hal": "not_enough"})
    batch, cmd, _ = bench("fact", entail=entail)
    (problems, _, refused), text, data = run(batch, cmd)
    assert refused == [] and len(problems) == 1, text
    assert "REWORD    s1" in text and "[the video's own fact]" in text, text
    assert repr(Q_KERRY["quote"]) in text, text
    rec = data["scripts"][0]["claims_check"]
    assert rec["failed_attempts"] == 1 and rec["refuse_now"] is True, rec
    assert [c["claim_id"] for c in rec["fact_reword"]["claims"]] == ["c2"], rec["fact_reword"]
    assert rec["fact_reword"]["claims"][0]["quotes"] == [Q_KERRY]


def test_a_fact_struck_after_the_one_edit_is_refused():
    """The rewording is the script's one edit: a fact struck on the run after
    a REWRITE has no rewording left."""
    batch, cmd, canned = bench("fact-after-rewrite")
    run(batch, cmd)                                   # REWRITE: c3 struck
    data = json.loads(batch.read_text())
    s = data["scripts"][0]
    s["commentary"] = "The finale settles it."
    s["claims"] = s["claims"][:2]
    s["production_fact"]["on_screen"] = s["claims"][1]["text"] = "Kerry shot Hal"
    batch.write_text(json.dumps(data))
    c = json.loads(canned.read_text())      # the edit's new screen wording does not follow
    c["entail"]["Kerry shot Hal"] = "not_enough"
    c["extract"].append({"where": "on_screen", "text": "Kerry shot Hal"})
    canned.write_text(json.dumps(c))
    (problems, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "REWORD" not in text, text
    assert data["skipped"][0]["claims_check"]["failed_attempts"] == 2


def test_rewordable_is_the_wording_verdicts_only():
    fact = {"fact_struck": True, "mechanics": {"violations": []}}
    ok = dict(fact, violations=[{"code": "claim_not_enough", "fact_claim": True},
                                {"code": "claim_not_entailed", "fact_claim": False}])
    assert cc.fact_rewordable(ok, JUDGE)
    fresh = dict(fact, violations=[{"code": "reveal_too_fresh", "fact_claim": True}])
    assert not cc.fact_rewordable(fresh, JUDGE), "no wording ages the text"
    bare = dict(ok, mechanics={"violations": [{"code": JUDGE.FATAL_MECHANICS[0]}]})
    assert not cc.fact_rewordable(bare, JUDGE), "a topic without text is refused at once"
    assert not cc.fact_rewordable(dict(ok, fact_struck=False), JUDGE)
    assert set(cc.REWORDABLE_CODES) == {JUDGE.FAIL_NOT_ENTAILED, JUDGE.FAIL_NOT_ENOUGH}


def test_a_topic_without_text_is_still_refused_at_once():
    topic = dict(TOPIC, support_check={"state": "failed"})
    batch, cmd, _ = bench("no-text", topic=topic)
    (problems, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "REWORD" not in text, text
    assert "no support text" in text, text


# ---- CF-0580: the two facts of the CF-0556 exam, worded past their quotes
ENDGAME_PIECE = "wikipedia:Vanguards:_Endgame"
ENDGAME_TEXT = (
    "In October 2014, Zenith Studios announced a two-part sequel of Vanguards: Age of Ultron "
    "(2015) entitled Vanguards: Infinity War. Part 1 was scheduled to be released on May 4, "
    "2018, and Part 2 was scheduled for May 3, 2019. Producer Kevin Feige said they would be "
    "\"two distinct\" projects with shared elements, not one story split across two films.")
ENDGAME_QUOTE = {"source": ENDGAME_PIECE, "quote": "In October 2014, Zenith Studios announced "
                 "a two-part sequel of Vanguards: Age of Ultron (2015) entitled Vanguards: "
                 "Infinity War"}
HARBOURLIGHTS_PIECE = "wikipedia:Harbourlights_(TV_series)"
HARBOURLIGHTS_TEXT = ("Greg Berlanti announced that he was developing a series based on the Green "
                 "Lantern characters for the streaming service Example Max in October 2019.")
HARBOURLIGHTS_QUOTE = {"source": HARBOURLIGHTS_PIECE, "quote": "announced that he was developing a series "
                  "based on the Green Lantern characters for the streaming service Example Max in "
                  "October 2019"}
WORDINGS = {
    # the exam's wording (not_enough in 3 of 4 live runs) -> the source's
    # (CF-0807: the exam said "this whole two-movie structure ..." - a claim
    # opening on "this" is now sent back before the judge, so the subject is
    # named here; the wording past the quote is the same.)
    "endgame": ("Endgame's whole two-movie structure was announced as one single project back "
                "in October 2014",
                "Zenith announced a two-part sequel to Age of Ultron in October 2014",
                "Endgame was announced as one project, Oct. 2014",
                "Announced as a two-part sequel, Oct. 2014",
                ENDGAME_PIECE, ENDGAME_TEXT, ENDGAME_QUOTE),
    "harbourlights": ("Greg Berlanti first pitched this as a Green Lantern series in October 2019",
                 "Greg Berlanti announced he was developing a Green Lantern series for Example Max "
                 "in October 2019",
                 "Berlanti pitched Green Lantern series, Oct. 2019",
                 "Oct. 2019: Berlanti developing Green Lantern series",
                 HARBOURLIGHTS_PIECE, HARBOURLIGHTS_TEXT, HARBOURLIGHTS_QUOTE),
}


def wording_bench(name, case, reworded_follows=True):
    beat, beat2, screen, screen2, piece, text, quote = WORDINGS[case]
    topic = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
        {"id": piece, "kind": "article", "title": piece.split(":", 1)[1],
         "url": "https://en.wikipedia.org/wiki/" + piece.split(":", 1)[1], "revision_id": 1,
         "revised_at": "2026-10-05T00:00:00Z", "text": text}]}
    script = {"script_id": "s1", "topic_id": "t1", "hook": "Here is how it started.",
              "commentary": f"And here's the part most recaps skip: {beat}.",
              "payoff": "What a bold plan.",
              "production_fact": {"beat_text": beat, "on_screen": screen},
              "claims": [{"claim_id": "f1", "where": "commentary", "text": beat,
                          "support": [quote]},
                         {"claim_id": "f2", "where": "on_screen", "text": screen,
                          "support": [quote]}]}
    extract = [{"where": "commentary", "text": t} for t in (beat, beat2)] + \
              [{"where": "on_screen", "text": t} for t in (screen, screen2)]
    after = "follows" if reworded_follows else "not_enough"
    entail = {beat: "not_enough", screen: "not_enough", beat2: after, screen2: "follows"}
    batch, cmd, _ = bench(name, script=script, extract=extract, entail=entail, topic=topic)
    return batch, cmd, (beat, beat2, screen, screen2)


def reword(batch, words):
    beat, beat2, screen, screen2 = words
    data = json.loads(batch.read_text())
    s = data["scripts"][0]
    s["commentary"] = s["commentary"].replace(beat, beat2)
    s["production_fact"] = {"beat_text": beat2, "on_screen": screen2}
    s["claims"][0]["text"], s["claims"][1]["text"] = beat2, screen2
    batch.write_text(json.dumps(data))


def test_endgame_and_harbourlights_facts_pass_in_the_source_s_words():
    for case in ("endgame", "harbourlights"):
        batch, cmd, words = wording_bench(f"wording-{case}", case)
        (problems, _, refused), text, data = run(batch, cmd)
        assert "REWORD    s1" in text and not refused, (case, text)
        rec = data["scripts"][0]["claims_check"]
        assert {c["claim_id"] for c in rec["fact_reword"]["claims"]} == {"f1", "f2"}, case
        reword(batch, words)
        (problems, _, refused), text, data = run(batch, cmd)
        assert not problems and not refused, (case, text)
        rec = data["scripts"][0]["claims_check"]
        assert rec["action"] == "pass" and rec["failed_attempts"] == 1, (case, rec)
        assert rec["fact_reworded"]["rule"] == "CF-0580", rec


def test_a_reworded_fact_that_still_does_not_follow_is_refused():
    batch, cmd, words = wording_bench("wording-still", "endgame", reworded_follows=False)
    run(batch, cmd)
    reword(batch, words)
    (problems, _, refused), text, data = run(batch, cmd)
    assert len(refused) == 1 and "still does not follow after its one rewording" in text, text
    skip = data["skipped"][0]
    assert skip["reason_code"] == "claim_unsupported", skip
    assert "after its one rewording in the source's words" in skip["reason"], skip["reason"]
    assert skip["claims_check"]["failed_attempts"] == 2


def test_an_undeclared_claim_is_a_rewrite():
    s = copy.deepcopy(SCRIPT)
    s["commentary"] = "The finale settles it, months before anyone knew."
    s["claims"] = s["claims"][:2]
    extract = EXTRACT[:2] + [{"where": "commentary", "text": "months before anyone knew"}]
    batch, cmd, _ = bench("undeclared", script=s, extract=extract)
    (problems, _, refused), text, _ = run(batch, cmd)
    assert "claim_undeclared" in text and not refused, text


def test_a_missing_field_is_not_an_attempt():
    s = copy.deepcopy(SCRIPT)
    del s["claims"]
    batch, cmd, _ = bench("missing", script=s)
    (problems, records, refused), text, data = run(batch, cmd)
    assert "FAIL      s1" in text and not records and not refused, text
    assert "claims_check" not in data["scripts"][0]


def test_not_logged_in_is_exit_3_and_nothing_written():
    batch, cmd, _ = bench("login", exit=4, stderr="claim answerer: NOT_LOGGED_IN")
    before = batch.read_text()
    assert cc.main([str(batch), "--write", "--answer-cmd", cmd, "--root", str(ROOT)]) == 3
    assert batch.read_text() == before


def judge_round_bench(name, at="frame_judge_refusal"):
    """CF-0902: a first-pass script s1 (topic t1) that the judge's round does
    not own, and the round's substitute s2 (topic t2), both carrying the
    struck c3 - the record s1 went on with is a pass."""
    batch, cmd, _ = bench(name)
    d = batch.parent
    t2 = dict(copy.deepcopy(TOPIC), topic_id="t2")
    (d / "01-trend-hunter.json").write_text(json.dumps({"topics": [TOPIC, t2]}))
    (d / "01b-footage-index.json").write_text(json.dumps({"reserve_substitution": {
        "substitutions": [{"replaced": "t1", "topic_id": "t2", "at": at,
                           "outcome": "sources"}]}}))
    first = dict(copy.deepcopy(SCRIPT), claims_check={"rule": "CF-0553", "action": "pass",
                                                      "violations": [], "kept": True})
    sub = dict(copy.deepcopy(SCRIPT), script_id="s2", topic_id="t2")
    batch.write_text(json.dumps({"scripts": [first, sub], "skipped": []}))
    return batch, cmd


def test_the_round_after_the_judge_leaves_the_first_pass_alone():
    """CF-0902 (example-film/2026-10-30T1033Z, pine-park): the round after the
    frame judge re-judged a first-pass script against a newer plan and wrote a
    failing record nobody would rewrite. Now it is FROZEN: nothing asked,
    the record it went on with stays; the substitute is judged as always."""
    batch, cmd = judge_round_bench("judge-round")
    before = json.loads(batch.read_text())["scripts"][0]
    (problems, records, refused), text, data = run(batch, cmd)
    assert "FROZEN    s1" in text and "CF-0902" in text, text
    assert "s1" not in records and not any(p.startswith("s1:") for p in problems), problems
    assert data["scripts"][0] == before
    assert "s2" in records and records["s2"]["action"] == "fail", records   # c3 struck
    assert any(p.startswith("s2:") for p in problems), problems


def test_the_reserve_round_does_not_stamp_the_first_pass():
    """CF-0933 (example-tech/2026-11-11T0956Z, nvidia): the reserve round before
    compliance (a substitution at `researcher_refusal`) judged the whole 03 and
    stamped a failing record onto a first-pass script it does not own. Now
    that script is NOT OWNED: what the free mechanics find is said, nothing is
    asked, its record stays; the round's substitute is judged as always."""
    batch, cmd = judge_round_bench("late-round", at="researcher_refusal")
    before = json.loads(batch.read_text())["scripts"][0]
    (problems, records, refused), text, data = run(batch, cmd)
    assert "NOT OWNED s1 (the mechanics pass)" in text and "CF-0933" in text, text
    assert "FROZEN" not in text, text
    assert "s1" not in records and not any(p.startswith("s1:") for p in problems), problems
    assert data["scripts"][0] == before
    assert records["s2"]["action"] == "fail", records                      # c3 struck
    assert any(p.startswith("s2:") for p in problems), problems


def test_an_index_pass_substitution_is_no_round():
    """The Indexer's own refill (`index_pass`, `sieve`) happens before this
    stage runs; the first pass writes those topics itself and owns every one."""
    batch, cmd = judge_round_bench("index-pass", at="index_pass")
    (problems, records, refused), text, data = run(batch, cmd)
    assert "NOT OWNED" not in text and "FROZEN" not in text, text
    assert records["s1"]["action"] == "fail" and records["s2"]["action"] == "fail", records
    assert "kept" not in data["scripts"][0]["claims_check"]


SHOT_CLAIM = {"claim_id": "c4", "where": "commentary", "text": "The finale settles it",
              "support": [{"shot_id": "vid:3"}]}


def lay_plan(batch, script, shot):
    """A stand-in for step 6b's plan of `script`: one word a second over
    hook + commentary + payoff, one block under all of it showing `shot`
    (`work/<slug>/plan_check.json` naming the script, `plan.json` beside it)."""
    cl = JUDGE.claims
    toks = [w for k in cl.WHERE_SPOKEN for w in cl.words(script.get(k))]
    work = batch.parent / "work" / script["script_id"]
    work.mkdir(parents=True, exist_ok=True)
    (work / cl.PLAN_VERDICT).write_text(json.dumps(
        {"kind": cl.PLAN_KIND, "script_id": script["script_id"], "at": "2026-11-11T11:22:48Z"}))
    (work / cl.PLAN_FILE).write_text(json.dumps({
        "words": [{"word": w, "start": float(i), "end": i + 1.0} for i, w in enumerate(toks)],
        "blocks": [{"start": 0.0, "end": float(len(toks)), "shot": shot}]}))


def shot_script(batch, sid="s1"):
    shots = batch.parent / "vid.shots.json"
    shots.write_text(json.dumps({"shots": [{"index": 1, "description": "a crowd"},
                                           {"index": 3, "description": "the finale"}]}))
    script = copy.deepcopy(SCRIPT)
    script.update(script_id=sid, claims=script["claims"] + [SHOT_CLAIM],
                  anchor_coverage_pool={"indexes": [str(shots)]})
    return script


def test_not_owned_names_the_plan_failure_without_writing():
    """The 0956Z shape: the first pass's plan puts another shot under the
    words of a shot claim. In the reserve round the line says so -
    `NOT OWNED s1 (fails: shot_not_under_words c4)` - and the record the
    first pass left is not touched, the exit code does not move."""
    batch, cmd = judge_round_bench("not-owned-plan", at="researcher_refusal")
    data = json.loads(batch.read_text())
    first = dict(shot_script(batch), claims_check=data["scripts"][0]["claims_check"])
    data["scripts"][0] = first
    batch.write_text(json.dumps(data))
    lay_plan(batch, first, "vid:1")
    (problems, records, refused), text, after = run(batch, cmd)
    assert "NOT OWNED s1 (fails: shot_not_under_words c4)" in text, text
    assert after["scripts"][0] == first and "s1" not in records, text
    assert not any(p.startswith("s1:") for p in problems), problems


def test_script_ids_judge_only_the_named_script_and_own_vouches_for_one():
    """CF-0933: `script_ids` judges the named script only (the rest untouched,
    not even printed); `own` is the caller vouching for a first-pass script
    the reserve round does not own (6b's check after the supplement)."""
    batch, cmd = judge_round_bench("script-ids", at="researcher_refusal")
    before = json.loads(batch.read_text())["scripts"]
    lines = []
    _, records, _ = cc.check_batch(batch, root=ROOT, write=True, out=lines.append, judge=JUDGE,
                                   answer_cmd=cmd, script_ids={"s2"})
    text = "\n".join(lines)
    assert set(records) == {"s2"} and "s1" not in text.split("judging")[1], text
    assert json.loads(batch.read_text())["scripts"][0] == before[0]
    lines = []
    _, records, _ = cc.check_batch(batch, root=ROOT, write=True, out=lines.append, judge=JUDGE,
                                   answer_cmd=cmd, script_ids={"s1"}, own={"s1"})
    assert set(records) == {"s1"} and records["s1"]["action"] == "fail", lines
    assert "NOT OWNED" not in "\n".join(lines)


def test_skill_names_the_check_and_its_code():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    assert "check_claims.py" in skill and "claim_unsupported" in skill
    assert "**`REWORD`**" in skill and "source's verb" in skill     # CF-0580
    for code in ("claim_undeclared", "claim_not_entailed", "claim_not_enough"):
        assert code in skill, code


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

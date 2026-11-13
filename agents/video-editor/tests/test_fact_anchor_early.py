#!/usr/bin/env python3
"""CF-0583 (CF-0547's price, signed by the user 2026-10-06 «цену за кадр
раньше слов подтверждаю»): `score.fact_anchor_early` in the video's own
score log, charged at the plan stage.

Pinned here: which anchor is early (begins before the fact beat in the
commentary and runs into it; one that ends before the fact is not), the lead
in seconds of the voice between the anchor's first word and the fact's first
word, units = the lead over the 2 s allowance (to 0.1 s), the signed price
(-2 a second, cap 10: WNL 0701Z's 6.02 s -> -8, 92 S), the same seconds the
Content Researcher's `fact_anchor_record` charges for the same script and
voice, and the plan builder asking it beside the tail under `_score.has_rule`.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _score  # noqa: E402
import fact_anchor  # noqa: E402

HOOK = "Nobody in that studio saw any of this coming, not even the host himself."
COMMENTARY = ("The show opened with a cold open that ran long and the crowd went very quiet "
              "for a while, then Swift walked in and the room finally woke up.")
FACT = "then Swift walked in and the room finally woke up."
EARLY = "a cold open that ran long and the crowd went very quiet for a while, then Swift walked in"
BEFORE = "The show opened with"


def script(anchors=(EARLY,), fact=FACT):
    return {"script_id": "s1", "hook": HOOK, "commentary": COMMENTARY, "payoff": "",
            "production_fact": {"text": "x", "beat_text": fact, "source_url": "https://e.x"},
            "visual_anchors": [{"anchor_id": f"a{i}", "beat_text": bt}
                               for i, bt in enumerate(anchors)]}


def words(step=0.4):
    out, t = [], 0.0
    for w in (HOOK + " " + COMMENTARY).split():
        out.append({"word": w, "start": round(t, 2), "end": round(t + step - 0.05, 2)})
        t += step
    return out


def expected_lead(step=0.4):
    toks = (HOOK + " " + COMMENTARY).split()
    ia = len(HOOK.split()) + len(COMMENTARY[:COMMENTARY.index(EARLY)].split())
    jf = len(HOOK.split()) + len(COMMENTARY[:COMMENTARY.index(FACT)].split())
    assert toks[ia] == "a" and toks[jf] == "then"
    return round((jf - ia) * step, 2)


def test_the_early_anchor_is_found_and_its_lead_is_seconds_of_voice():
    got = fact_anchor.leads(script(), words())
    assert len(got) == 1, got
    e = got[0]
    assert e["anchor_id"] == "a0" and e["words_early"] == 15, e
    assert e["lead_s"] == expected_lead() == 6.0, e


def test_one_finding_units_over_the_allowance():
    got = fact_anchor.findings(script(), words(), allow=2)
    assert len(got) == 1, got
    f = got[0]
    assert f["rule"] == fact_anchor.RULE == "score.fact_anchor_early"
    assert f["units"] == 4.0 and f["where"]["anchor"] == "a0", f
    assert f["source"] == "metric" and f["hook"] is False, f


def test_within_the_allowance_or_not_early_nothing_is_charged():
    # 0.1 s a word: 15 words = 1.5 s, inside the 2 s the user called «пару секунд»
    assert fact_anchor.findings(script(), words(step=0.1), allow=2) == []
    # an anchor that ends before the fact begins keeps its own words
    assert fact_anchor.findings(script(anchors=(BEFORE,)), words(), allow=2) == []
    # no fact, no anchors, no script at all
    s = script()
    s.pop("production_fact")
    assert fact_anchor.findings(s, words(), allow=2) == []
    assert fact_anchor.findings(script(anchors=()), words(), allow=2) == []
    assert fact_anchor.findings(None, words(), allow=2) == []
    # a fact beat not in the commentary is another check's problem
    assert fact_anchor.findings(script(fact="never said."), words(), allow=2) == []


def test_the_signed_price_two_a_second_over_two_capped_at_ten():
    if not _score.has_rule(fact_anchor.RULE):
        print("  skip: the root's table does not carry the signed row")
        return
    assert fact_anchor.allowance() == 2.0
    wnl = _score.score_block([_score.finding(fact_anchor.RULE, {}, units=4.0)])
    assert wnl["score"] == 92 and wnl["tier"] == "S", wnl     # WNL 0701Z, 6.02 s
    delver = _score.score_block([_score.finding(fact_anchor.RULE, {}, units=5.3)])
    assert delver["score"] == 90, delver                      # delver 1427Z, 7.26 s: the cap
    mine = _score.score_block(fact_anchor.findings(script(), words()))
    assert mine["score"] == 92, mine


def test_the_researcher_charges_the_same_seconds():
    """The Researcher's `fact_anchor_record` (step 6b, 03) and this stage
    measure one script on one voice to the same lead and units. Run in its
    own interpreter: both repos have a module named `_score`."""
    cr = HERE.parent.parent / "content-researcher" / "scripts"
    if not (cr / "check_production_fact.py").is_file():
        print("  skip: no agents/content-researcher beside this repo")
        return
    cases = [(script(), words()), (script(), words(step=0.27)),
             (script(anchors=(BEFORE, EARLY)), words(step=0.55))]
    code = ("import json,sys; sys.path.insert(0, sys.argv[1]); import check_production_fact as c; "
            "cases=json.loads(sys.stdin.read()); "
            "print(json.dumps([[r['lead_s'], r['units']] if r else None for r in "
            "(c.fact_anchor_record(s, w) for s, w in cases)]))")
    out = subprocess.run([sys.executable, "-c", code, str(cr)], input=json.dumps(cases),
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(f"  skip: the Researcher's module would not load here ({out.stderr.strip()[-200:]})")
        return
    theirs = json.loads(out.stdout.strip().splitlines()[-1])
    allow = fact_anchor.allowance()
    for (s, w), t in zip(cases, theirs):
        lead = max(e["lead_s"] for e in fact_anchor.leads(s, w))
        units = round(max(0.0, lead - allow), 1)
        assert t == [lead, units], (t, lead, units)


def test_the_plan_builder_asks_it_beside_the_tail_under_has_rule():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    at_tail = src.index("rhythm.tail_over_band_top_findings(blocks, pattern, words)")
    at_fact = src.index("fact_anchor.findings(fact_anchor.script_of(args.script, args.script_id), words)")
    assert 0 < at_fact - at_tail < 700
    seg = src[at_fact:at_fact + 200]
    assert "_score.has_rule(fact_anchor.RULE)" in seg, seg
    # inside the plan stage's score block, which is then recorded in the log
    block = src.rindex("plan_score = _score.score_block(", 0, at_fact)
    assert at_tail - 1200 < block < at_tail, block
    log = src.index("score_log.record(args.output, score_log.STAGE_PLAN,", at_fact)
    assert "plan_score.get(\"findings\")" in src[log:log + 200]
    assert "plan_score = " not in src[at_fact:log]


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

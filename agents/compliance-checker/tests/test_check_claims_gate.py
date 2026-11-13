#!/usr/bin/env python3
"""CF-0553: `scripts/check_claims_gate.py` - the root's claim judge as the
second pass' gate. A script whose words do not pass the judge now is blocked
in `contribution_check` with `claim_unsupported`; a passing one only gets
`claims_gate`; a model that cannot be asked is exit 3 and nothing written.

Offline: the answer command is a stand-in that answers from a canned file."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import check_claims_gate as g  # noqa: E402

JUDGE = g.load_judge()
_TMP = tmp_root("cc-claims-gate-")

SUMMARY = "During the game, John tells Kerry he knows she killed Hal to protect Noah."
TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    {"id": "w:e8", "kind": "episode_summary", "title": "Harbourlights", "url": "https://x.test",
     "revision_id": 1, "revised_at": "2026-10-05T00:00:00Z", "text": SUMMARY}]}
Q = {"source": "w:e8", "quote": "she killed Hal to protect Noah"}
GOOD = {"script_id": "s1", "topic_id": "t1", "hook": "Kerry killed Hal to protect Noah.",
        "commentary": "The finale settles it.", "payoff": "What a finale.",
        "claims": [{"claim_id": "c1", "where": "hook",
                    "text": "Kerry killed Hal to protect Noah", "support": [Q]}]}
BAD = dict(copy.deepcopy(GOOD), script_id="s2",
           commentary="The finale settles it. Zorvath is behind the kill.")
EXTRACT = [{"where": "hook", "text": "Kerry killed Hal to protect Noah"},
           {"where": "commentary", "text": "Zorvath is behind the kill"}]

FAKE = r'''
import json, sys
req, out, canned = sys.argv[1:4]
r = json.load(open(req)); c = json.load(open(canned))
if c.get("exit"):
    sys.stderr.write(c.get("stderr", "")); sys.exit(c["exit"])
if r["kind"] == "extract":
    t = r["payload"]["texts"]
    a = {"claims": [e for e in c["extract"] if e["text"] in t.get(e["where"], "")]}
else:
    a = {"verdict": "follows", "reason": "canned", "reveal": False}
json.dump(a, open(out, "w"))
'''


def bench(name, **canned):
    d = _TMP / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "fake.py").write_text(FAKE)
    (d / "canned.json").write_text(json.dumps(dict(extract=EXTRACT, **canned)))
    (d / "01-trend-hunter.json").write_text(json.dumps({"topics": [TOPIC]}))
    (d / "03-content-researcher.json").write_text(json.dumps({"scripts": [GOOD, BAD]}))
    rows = [{"script_id": "s1", "verdict": "clear",
             "contribution_check": {"verdict": "pass", "judged": True, "failures": [],
                                    "reason": None, "note": None}},
            {"script_id": "s2", "verdict": "clear",
             "contribution_check": {"verdict": "pass", "judged": True, "failures": [],
                                    "reason": None, "note": None}}]
    p04 = d / "04-compliance-checker.json"
    p04.write_text(json.dumps({"stage_checked": "03-content-researcher", "results": rows}))
    return p04, f"{sys.executable} {d / 'fake.py'} {{request}} {{answer}} {d / 'canned.json'}"


def test_an_undeclared_claim_blocks_the_script_and_the_good_one_passes():
    p04, cmd = bench("block")
    lines = []
    blocked, recs = g.check(p04, write=True, out=lines.append, judge=JUDGE, answer_cmd=cmd)
    assert blocked == ["s2"], "\n".join(lines)
    d = json.loads(p04.read_text())
    s1, s2 = d["results"]
    assert s1["claims_gate"]["action"] == "pass"
    assert s1["contribution_check"]["verdict"] == "pass"
    cc = s2["contribution_check"]
    assert cc["verdict"] == "block", cc
    assert [f["reason_code"] for f in cc["failures"]] == ["claim_unsupported"], cc
    assert "Zorvath is behind the kill" in cc["failures"][0]["detail"]
    assert s2["claims_gate"]["undeclared"] == ["Zorvath is behind the kill"]
    # a second run asks nothing and does not double the failure
    blocked, recs = g.check(p04, write=True, out=lines.append, judge=JUDGE, answer_cmd=cmd)
    d = json.loads(p04.read_text())
    assert len(d["results"][1]["contribution_check"]["failures"]) == 1
    assert d["results"][1]["claims_gate"]["asked"] == 0


def test_not_logged_in_writes_nothing():
    p04, cmd = bench("login", exit=4, stderr="NOT_LOGGED_IN")
    before = p04.read_text()
    assert g.main([str(p04), "--write", "--answer-cmd", cmd]) == 3
    assert p04.read_text() == before


def test_the_code_is_the_root_one():
    assert g.REASON_CODE == JUDGE.SKIP_REASON_CODE


def test_the_gate_record_carries_the_price_of_second_opinions():
    # CF-0579: the judge asks again before a strike; the gate says how much
    rep = {"action": "fail", "mechanics": {"violations": []}, "violations": [],
           "struck": [{"claim_id": "c2", "text": "Zorvath is behind the kill"}],
           "extracted": [], "asked": 5, "cached": 0, "model": "sonnet",
           "opinion_calls": 2, "second_opinions": 1, "third_opinions": 1}
    rec = g.gate_record(JUDGE, rep)
    assert rec["opinion_calls"] == 2 and rec["asked"] == 5, rec
    del rep["opinion_calls"]
    assert g.gate_record(JUDGE, rep)["opinion_calls"] == 0


def test_skill_runs_the_gate():
    skill = (HERE.parent / ".claude" / "skills" / "compliance-checker" / "SKILL.md").read_text()
    assert "check_claims_gate.py" in skill and "claim_unsupported" in skill



# --------------------------------------------------------------------------
# CF-0917: a full 04 keyed by the topic id (batch example-tech/2026-11-04T0835Z)
# --------------------------------------------------------------------------

TOPICS_0835Z = ["lf-2026-11-04-016", "lf-2026-11-04-061", "lf-2026-11-04-022"]


def bench_0835z(name, keyed_by="script", file_name="04-compliance-checker.json",
                drop=()):
    d = _TMP / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "fake.py").write_text(FAKE)
    (d / "canned.json").write_text(json.dumps({"extract": EXTRACT}))
    (d / "01-trend-hunter.json").write_text(json.dumps(
        {"topics": [dict(copy.deepcopy(TOPIC), topic_id=t) for t in TOPICS_0835Z]}))
    (d / "03-content-researcher.json").write_text(json.dumps({"scripts": [
        dict(copy.deepcopy(GOOD), script_id=f"{t}-script1", topic_id=t)
        for t in TOPICS_0835Z]}))
    rows = []
    for t in TOPICS_0835Z:
        if t in drop:
            continue
        row = {"verdict": "clear",
               "contribution_check": {"verdict": "pass", "judged": True, "failures": [],
                                      "reason": None, "note": None}}
        if keyed_by == "topic":       # what the operator wrote on 0835Z
            row["script_id"] = t
        else:
            row.update(script_id=f"{t}-script1", topic_id=t)
        rows.append(row)
    p04 = d / file_name
    p04.write_text(json.dumps({"stage_checked": "03-content-researcher", "results": rows}))
    return p04, f"{sys.executable} {d / 'fake.py'} {{request}} {{answer}} {d / 'canned.json'}"


def run_main(*argv):
    import contextlib
    import io
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = g.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def test_a_full_04_keyed_by_the_topic_id_is_not_done():
    p04, cmd = bench_0835z("topic-keyed", keyed_by="topic")
    code, out, err = run_main(p04, "--write", "--answer-cmd", cmd)
    assert code == g.EXIT_NO_ROW == 4, (code, out, err)
    for t in TOPICS_0835Z:
        assert f"{t}-script1" in err, err
        assert f"NO ROW {t}-script1" in out, out
    assert "note:" not in out, out
    assert "not the topic id" in err, err
    # what it can write is still written: nothing matched, so no row has a gate
    rows = json.loads(p04.read_text())["results"]
    assert [r["script_id"] for r in rows] == TOPICS_0835Z
    assert not any("claims_gate" in r for r in rows), rows
    # without --write it is the same answer
    code, _, err = run_main(p04, "--answer-cmd", cmd)
    assert code == 4 and "lf-2026-11-04-061-script1" in err


def test_one_missing_row_of_three_names_only_that_script_and_still_writes_the_rest():
    p04, cmd = bench_0835z("one-missing", drop=("lf-2026-11-04-061",))
    code, out, err = run_main(p04, "--write", "--answer-cmd", cmd)
    assert code == 4, (code, out, err)
    assert "lf-2026-11-04-061-script1" in err
    assert "016-script1" not in err and "022-script1" not in err, err
    rows = json.loads(p04.read_text())["results"]
    assert all(r["claims_gate"]["action"] == "pass" for r in rows), rows


def test_the_new_only_staging_file_keeps_exit_0():
    # CF-0800: the staging file holds only the new rows by design
    p04, cmd = bench_0835z("staging", drop=TOPICS_0835Z[:2],
                           file_name="04-compliance-checker.added.json")
    code, out, err = run_main(p04, "--write", "--answer-cmd", cmd)
    assert code == 0, (code, out, err)
    assert "note: lf-2026-11-04-016-script1 has no row" in out, out
    assert "not done" not in err and "NO ROW" not in out, (out, err)
    row, = json.loads(p04.read_text())["results"]
    assert row["claims_gate"]["action"] == "pass"


def test_the_partial_flag_keeps_exit_0_on_any_file_name():
    p04, cmd = bench_0835z("partial-flag", drop=TOPICS_0835Z[1:])
    code, out, err = run_main(p04, "--write", "--partial", "--answer-cmd", cmd)
    assert code == 0, (code, out, err)
    assert g.is_partial("x/04-compliance-checker.added.json")
    assert not g.is_partial("x/04-compliance-checker.json")


def test_a_correct_04_is_unchanged_by_the_new_rule():
    p04, cmd = bench_0835z("correct")
    code, out, err = run_main(p04, "--write", "--answer-cmd", cmd)
    assert code == 0, (code, out, err)
    assert err == "" and "NO ROW" not in out and "note:" not in out, (out, err)
    rows = json.loads(p04.read_text())["results"]
    assert [r["claims_gate"]["action"] for r in rows] == ["pass"] * 3, rows
    assert [r["topic_id"] for r in rows] == TOPICS_0835Z


def test_skill_says_the_key_is_the_script_id_and_exit_4_is_not_done():
    skill = (HERE.parent / ".claude" / "skills" / "compliance-checker" / "SKILL.md").read_text()
    assert "-script1" in skill and "never the topic id" in skill, "key rule"
    assert "Exit 4" in skill and "04 is not done" in skill, "exit 4"


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

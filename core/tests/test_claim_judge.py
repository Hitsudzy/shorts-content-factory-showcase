#!/usr/bin/env python3
"""CF-0553: the independent reader of the finished text (Q13) and the judge
of entailment (Q6) - `shared/factrule/claim_judge.py` and its default
answerer `claim_answer_claude.py`.

No network and no model: the answer command is a stand-in written here
(`FAKE`), which answers from a canned file and logs every request it got, so
a test can see what each call was shown. The acceptance cases are the
grill's: Harbourlights 0701Z "Zorvath is behind the kill" (a quote that is in the
text and does not say it - the judge says `does_not_follow`), East of Eden
0701Z "months before anyone outside the production knew" (a claim the writer
did not declare - the reader lists it). The texts are short synthetic
stand-ins, not copies of Wikipedia."""
import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FR = ROOT / "shared" / "factrule"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmproot import tmp_root  # noqa: E402

TMP = tmp_root("claim-judge-test-")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cj = _load("claim_judge_cf0553", FR / "claim_judge.py")
ans = _load("claim_answer_cf0553", FR / "claim_answer_claude.py")

SUMMARY = ("John learns from Zorvath that Noah freed and brought him to the island. "
           "During the game, John tells Kerry he knows she killed Hal to protect Noah.")
ARTICLE = ("East of Eden is a drama limited series created by Zoe Kazan for ExampleStream.\n\n"
           "In September 2024, Christopher Abbott, Mike Faist and Hoon Lee joined the cast "
           "opposite Florence Pugh.")
TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"}, "support_text": [
    {"id": "wikipedia:Harbourlights#e8", "kind": "episode_summary", "title": "Harbourlights (TV series)",
     "url": "https://en.wikipedia.org/wiki/Harbourlights_(TV_series)", "revision_id": 1,
     "revised_at": "2026-10-05T00:00:00Z", "text": SUMMARY},
    {"id": "wikipedia:East_of_Eden", "kind": "work_article", "title": "East of Eden",
     "url": "https://en.wikipedia.org/wiki/East_of_Eden", "revision_id": 2,
     "revised_at": "2026-10-05T00:00:00Z", "text": ARTICLE},
]}
Q_ZORVATH = {"source": "wikipedia:Harbourlights#e8",
              "quote": "John learns from Zorvath that Noah freed and brought him"}
Q_KERRY = {"source": "wikipedia:Harbourlights#e8", "quote": "she killed Hal to protect Noah"}
Q_CAST = {"source": "wikipedia:East_of_Eden",
          "quote": "In September 2024, Christopher Abbott, Mike Faist and Hoon Lee joined the cast"}

SCRIPT = {
    "script_id": "s1", "topic_id": "t1",
    "hook": "Kerry killed Hal to protect Noah.",
    "commentary": "In September 2024 Christopher Abbott, Mike Faist and Hoon Lee joined the cast. "
                  "And Zorvath is behind the kill.",
    "payoff": "What a bold finale.",
    "production_fact": {"beat_text": "In September 2024 Christopher Abbott, Mike Faist and "
                                     "Hoon Lee joined the cast",
                        "on_screen": "Abbott, Faist, Hoon Lee joined, Sept. 2024"},
    "claims": [
        {"claim_id": "c1", "where": "hook", "text": "Kerry killed Hal to protect Noah",
         "support": [Q_KERRY]},
        {"claim_id": "c2", "where": "commentary",
         "text": "In September 2024 Christopher Abbott, Mike Faist and Hoon Lee joined the cast",
         "support": [Q_CAST]},
        {"claim_id": "c3", "where": "on_screen", "text": "Abbott, Faist, Hoon Lee joined, Sept. 2024",
         "support": [Q_CAST]},
        {"claim_id": "c4", "where": "commentary", "text": "Zorvath is behind the kill",
         "support": [Q_ZORVATH]},
    ],
}
EXTRACTED = [
    {"where": "hook", "text": "Kerry killed Hal to protect Noah"},
    {"where": "commentary", "text": "In September 2024 Christopher Abbott, Mike Faist and Hoon "
                                    "Lee joined the cast"},
    {"where": "commentary", "text": "Zorvath is behind the kill"},
    {"where": "on_screen", "text": "Abbott, Faist, Hoon Lee joined, Sept. 2024"},
]
VERDICTS = {"Kerry killed Hal to protect Noah": "follows",
            "In September 2024 Christopher Abbott, Mike Faist and Hoon Lee joined the cast":
                "follows",
            "Abbott, Faist, Hoon Lee joined, Sept. 2024": "follows",
            "Zorvath is behind the kill": "does_not_follow"}

FAKE = r'''
import json, sys
req, out, canned, seen = sys.argv[1:5]
r = json.load(open(req))
c = json.load(open(canned))
with open(seen, "a") as f:
    f.write(json.dumps(r) + "\n")
if c.get("exit"):
    sys.stderr.write(c.get("stderr", ""))
    sys.exit(c["exit"])
if r["kind"] == "extract":
    a = {"claims": c["extract"]}
else:
    p = r["payload"]
    news = {f["kind"] for f in p["footing"]} == {"news"}
    table = c.get("news", {}) if news else c["entail"]
    a = {"verdict": table.get(p["claim"], "not_enough"), "reason": "canned"}
    seq = c.get("by_opinion", {}).get(p["claim"])      # CF-0579: one verdict per opinion
    if seq and not news:
        a["verdict"] = seq[p.get("opinion", 1) - 1]
        a["reason"] = f"canned opinion {p.get('opinion', 1)}"
    if p["claim"] in c.get("reveal", {}):
        a["reveal"] = c["reveal"][p["claim"]]
    if p["claim"] in c.get("needs_context", {}) and not news:   # CF-0728
        if p.get("context") == c["needs_context"][p["claim"]]:
            a = dict(a, verdict="follows", reason="canned: read with its line")
        else:
            a = dict(a, verdict="not_enough", reason="canned: 'it' is not told",
                     missing="what 'it' refers to")
    if p["claim"] in c.get("needs_footing", {}) and not news:   # CF-0872
        want = c["needs_footing"][p["claim"]]
        if any(want in (f.get("quote") or "") for f in p["footing"]):
            a = dict(a, verdict="follows", reason="canned: the footing names it")
        else:
            a = dict(a, verdict="not_enough", reason="canned: the footing does not name it",
                     missing=want)
    if p["claim"] in c.get("missing", {}) and a["verdict"] != "follows":
        a["missing"] = c["missing"][p["claim"]]
json.dump(a, open(out, "w"))
'''


class Bench:
    """A temp dir with the stand-in answerer, its canned answers and log."""

    def __init__(self, extract=None, entail=None, **extra):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-", dir=TMP))
        (self.tmp / "fake.py").write_text(FAKE)
        self.canned = self.tmp / "canned.json"
        self.seen = self.tmp / "seen.jsonl"
        self.write(extract=EXTRACTED if extract is None else extract,
                   entail=VERDICTS if entail is None else entail, **extra)
        self.cmd = (f"{sys.executable} {self.tmp / 'fake.py'} {{request}} {{answer}} "
                    f"{self.canned} {self.seen}")

    def write(self, **c):
        self.canned.write_text(json.dumps(c))

    def asker(self, cache="cache"):
        return cj.Asker(self.tmp / cache, answer_cmd=self.cmd, timeout=30)

    def requests(self):
        if not self.seen.exists():
            return []
        return [json.loads(x) for x in self.seen.read_text().splitlines()]


def judge(script=None, bench=None, **kw):
    bench = bench or Bench()
    return cj.judge_script(copy.deepcopy(script or SCRIPT), topic=TOPIC, pool={}, plan=None,
                           asker=kw.pop("asker", None) or bench.asker(), **kw), bench


def test_harbourlights_quote_in_the_text_that_does_not_say_it_is_struck():
    rep, bench = judge()
    assert rep["mechanics"]["action"] == "pass", rep["mechanics"]   # the quote IS in the text
    assert rep["action"] == "fail"
    assert [v["code"] for v in rep["violations"]] == ["claim_not_entailed"], rep["violations"]
    assert rep["violations"][0]["claim_id"] == "c4"
    assert [s["claim_id"] for s in rep["struck"]] == ["c4"]
    assert rep["fact_struck"] is False and rep["refuse_now"] is False
    states = {v["claim_id"]: v["state"] for v in rep["verdicts"]}
    assert states == {"c1": "supported", "c2": "supported", "c3": "supported",
                      "c4": "struck"}, states


def test_the_judge_sees_the_pair_and_nothing_of_the_script():
    rep, bench = judge()
    reqs = bench.requests()
    kinds = [r["kind"] for r in reqs]
    # four claims, each asked twice: a strike (CF-0579) and a follows (CF-0872)
    assert kinds.count("extract") == 1 and kinds.count("entail") == 8, kinds
    for r in reqs:
        if r["kind"] != "entail":
            continue
        assert set(r["payload"]) - {"opinion"} == {"claim", "footing"}, r["payload"]
        blob = r["prompt"]
        assert "s1" not in json.dumps(r["payload"])
        assert "What a bold finale" not in blob and "claim_id" not in blob, blob
        for f in r["payload"]["footing"]:
            assert f["kind"] == "quote" and f["context"], f
    # the reader is shown the finished text and nothing of the writer's list
    ex = next(r for r in reqs if r["kind"] == "extract")
    assert set(ex["payload"]["texts"]) == {"hook", "commentary", "payoff", "on_screen"}
    assert "support" not in ex["prompt"] and "wikipedia:" not in ex["prompt"]


def test_east_of_eden_an_undeclared_exaggeration_is_listed_by_the_reader():
    s = copy.deepcopy(SCRIPT)
    s["commentary"] += " They signed months before anyone outside the production knew."
    s["claims"] = [c for c in s["claims"] if c["claim_id"] != "c4"]
    listed = [e for e in EXTRACTED if "Zorvath" not in e["text"]] + [
        {"where": "commentary", "text": "months before anyone outside the production knew"}]
    rep, _ = judge(s, Bench(extract=listed))
    codes = [v["code"] for v in rep["violations"]]
    assert codes == ["claim_undeclared"], rep["violations"]
    assert "months before anyone" in rep["violations"][0]["text"]
    assert [e["matched"] for e in rep["extracted"]][:2] == [["c1"], ["c2"]]


def test_a_good_script_passes_and_a_rerun_asks_nothing():
    s = copy.deepcopy(SCRIPT)
    s["commentary"] = s["commentary"].replace(" And Zorvath is behind the kill.", "")
    s["claims"] = s["claims"][:3]
    bench = Bench(extract=EXTRACTED[:2] + EXTRACTED[3:])
    rep, _ = judge(s, bench)
    assert rep["action"] == "pass", (rep["violations"], rep["mechanics"]["violations"])
    assert rep["asked"] == 1 + 3 * 2 and rep["cached"] == 0    # CF-0872: follows confirmed
    rep2, _ = judge(s, bench, asker=bench.asker())
    assert rep2["action"] == "pass" and rep2["asked"] == 0 and rep2["cached"] == 7, rep2


# --------------------------------------------- CF-0579: the second opinion
ZORVATH = "Zorvath is behind the kill"


def _entails(bench, claim):
    return [r["payload"].get("opinion") for r in bench.requests()
            if r["kind"] == "entail" and r["payload"]["claim"] == claim]


def test_a_strike_is_asked_twice_and_two_noes_strike():
    bench = Bench(by_opinion={ZORVATH: ["does_not_follow", "not_enough"]})
    rep, _ = judge(bench=bench)
    assert _entails(bench, ZORVATH) == [None, 2]
    row = _row(rep, "c4")
    assert row["state"] == "struck" and row["verdict"] == "does_not_follow", row
    assert [(o["n"], o["verdict"]) for o in row["opinions"]] == [
        (1, "does_not_follow"), (2, "not_enough")], row["opinions"]
    assert len({o["key"] for o in row["opinions"]}) == 2, "each opinion its own cache key"
    assert row["key"] == row["opinions"][0]["key"]
    assert [v["code"] for v in rep["violations"]] == ["claim_not_entailed"]
    # CF-0872: a follows is confirmed too - one more call per claim
    assert all([o["verdict"] for o in _row(rep, c)["opinions"]] == ["follows", "follows"]
               for c in ("c1", "c2", "c3"))
    assert (rep["opinion_calls"], rep["second_opinions"], rep["third_opinions"]) == (4, 4, 0)
    assert rep["asked"] == 1 + 4 * 2, rep["asked"]


def test_a_split_is_settled_by_a_third_and_the_majority_keeps_a_true_claim():
    bench = Bench(by_opinion={ZORVATH: ["not_enough", "follows", "follows"]})
    rep, _ = judge(bench=bench)
    assert _entails(bench, ZORVATH) == [None, 2, 3]
    row = _row(rep, "c4")
    assert row["state"] == "supported" and row["verdict"] == "follows", row
    assert row["reason"] == "canned opinion 2", "the row speaks with a deciding opinion"
    assert [o["verdict"] for o in row["opinions"]] == ["not_enough", "follows", "follows"]
    assert rep["action"] == "pass" and not rep["struck"], rep["violations"]
    # c4 split (+2), each of the three others confirmed (+1)
    assert (rep["opinion_calls"], rep["second_opinions"], rep["third_opinions"]) == (5, 4, 1)


def test_a_split_settled_for_the_strike_strikes():
    bench = Bench(by_opinion={ZORVATH: ["does_not_follow", "follows", "not_enough"]})
    rep, _ = judge(bench=bench)
    row = _row(rep, "c4")
    assert row["state"] == "struck" and len(row["opinions"]) == 3, row
    # two "no" verdicts of different kinds: the first one's
    assert row["verdict"] == "does_not_follow" and row["reason"] == "canned opinion 1"


def test_cf0872_a_follows_is_confirmed_and_a_split_settled_by_a_third():
    # i-play-rocky 0841Z / coyote-vs-acme 1514Z: one `follows` of the writer's
    # check let a borderline claim into the render; the card drew `not_enough`
    # twice on the same question. A `follows` is asked again now.
    bench = Bench(by_opinion={ZORVATH: ["follows", "not_enough", "not_enough"]})
    rep, _ = judge(bench=bench)
    assert _entails(bench, ZORVATH) == [None, 2, 3]
    row = _row(rep, "c4")
    assert row["state"] == "struck" and row["verdict"] == "not_enough", row
    assert row["reason"] == "canned opinion 2"
    assert [v["code"] for v in rep["violations"]] == ["claim_not_enough"]
    # two concurring answers decide - no third call
    bench = Bench(by_opinion={ZORVATH: ["follows", "follows", "not_enough"]})
    rep, _ = judge(bench=bench)
    assert _entails(bench, ZORVATH) == [None, 2]
    assert _row(rep, "c4")["state"] == "supported"
    bench = Bench(by_opinion={ZORVATH: ["follows", "not_enough", "follows"]})
    rep, _ = judge(bench=bench)
    assert _entails(bench, ZORVATH) == [None, 2, 3]
    assert _row(rep, "c4")["state"] == "supported" and _row(rep, "c4")["reason"] == \
        "canned opinion 1"


def test_the_majority_rule():
    def ops(*vs):
        return [{"verdict": v} for v in vs]
    assert cj.decide(ops("follows")) == 0
    assert cj.decide(ops("not_enough", "not_enough")) == 0
    assert cj.decide(ops("not_enough", "follows", "follows")) == 1
    assert cj.decide(ops("not_enough", "follows", "does_not_follow")) == 0
    assert cj.decide(ops("does_not_follow", "not_enough", "not_enough")) == 1


def test_the_second_opinion_is_cached_and_a_rerun_asks_nothing():
    bench = Bench(by_opinion={ZORVATH: ["not_enough", "follows", "not_enough"]})
    rep, _ = judge(bench=bench)
    n = len(bench.requests())
    rep2, _ = judge(bench=bench, asker=bench.asker())
    assert len(bench.requests()) == n and rep2["asked"] == 0 and rep2["cached"] == rep["asked"]
    assert [o["verdict"] for o in _row(rep2, "c4")["opinions"]] == [
        "not_enough", "follows", "not_enough"]
    assert rep2["opinion_calls"] == 2 + 3, "a cached opinion still counts in the price"
    # the first opinion's key is the request a run before CF-0579 made: its cache holds
    first = _row(rep, "c4")["opinions"][0]["key"]
    footing = cj.footing_of(next(r for r in rep["mechanics"]["results"]
                                 if r["claim_id"] == "c4"), cj.claims.support_pieces(TOPIC))
    assert first == cj.request_key("entail", "sonnet", {"claim": ZORVATH, "footing": footing})


def test_the_fact_without_footing_leaves_no_video():
    verdicts = dict(VERDICTS)
    verdicts["Abbott, Faist, Hoon Lee joined, Sept. 2024"] = "not_enough"
    rep, _ = judge(bench=Bench(entail=verdicts))
    assert rep["fact_struck"] is True and rep["refuse_now"] is True
    assert "claim_not_enough" in cj.all_codes(rep)


def test_a_topic_without_text_is_refused_at_once():
    s = copy.deepcopy(SCRIPT)
    topic = dict(TOPIC, support_check={"state": "unreachable"})
    rep = cj.judge_script(s, topic=topic, pool={}, plan=None, asker=Bench().asker())
    assert rep["refuse_now"] is True
    assert "topic_without_support_text" in cj.all_codes(rep)


def test_a_mechanical_failure_is_not_sent_to_the_judge():
    s = copy.deepcopy(SCRIPT)
    s["claims"][3]["support"] = [{"source": "wikipedia:Harbourlights#e8", "quote": "Zorvath killed Hal"}]
    rep, bench = judge(s)
    assert "quote_not_in_source" in cj.all_codes(rep)
    asked = [r["payload"]["claim"] for r in bench.requests() if r["kind"] == "entail"]
    assert "Zorvath is behind the kill" not in asked
    assert {v["claim_id"]: v["state"] for v in rep["verdicts"]}["c4"] == "mechanics_failed"


def test_a_reader_answer_that_is_not_verbatim_is_no_answer():
    bad = [{"where": "commentary", "text": "Zorvath was the killer"}]
    bench = Bench(extract=bad)
    try:
        judge(bench=bench)
    except cj.CannotAsk as exc:
        assert "not verbatim" in str(exc), exc
    else:
        raise AssertionError("a reworded span was taken as a claim")
    assert len([r for r in bench.requests() if r["kind"] == "extract"]) == cj.ATTEMPTS
    assert list((bench.tmp / "cache").glob("*.rejected.json"))


def test_not_logged_in_is_said_not_a_verdict():
    bench = Bench(exit=4, stderr="claim answerer: NOT_LOGGED_IN - log x")
    try:
        judge(bench=bench)
    except cj.CannotAsk as exc:
        assert exc.not_logged_in and "NOT_LOGGED_IN" in str(exc)
    else:
        raise AssertionError("an answerer without a session gave a verdict")


def test_matching_by_overlap():
    declared = [{"claim_id": "a", "where": "commentary",
                 "text": "In September 2024 Hoon Lee joined the cast"},
                {"claim_id": "b", "where": "commentary", "text": "opposite Florence Pugh"}]
    listed = [{"where": "commentary", "text": "Hoon Lee joined the cast"},
              {"where": "commentary",
               "text": "In September 2024 Hoon Lee joined the cast opposite Florence Pugh"},
              {"where": "hook", "text": "Hoon Lee joined the cast"},
              {"where": "commentary", "text": "nobody knew before a single frame leaked"}]
    assert cj.match_extracted(listed, declared) == [["a"], ["a"], [], []]


def test_answerer_reads_the_last_json_object_and_runs_without_tools():
    assert ans.json_object('{"verdict": "does_not_follow"}\nWait.\n{"verdict": "not_enough"}') \
        == {"verdict": "not_enough"}
    assert ans.json_object('```json\n{"claims": []}\n```') == {"claims": []}
    assert ans.json_object("no json here") is None
    argv = ans.claude_argv("claude", "sonnet")
    assert argv[argv.index("--tools") + 1] == "" and "--model" in argv
    assert "--no-session-persistence" in argv


def _fake_claude(tmp, body):
    p = Path(tmp) / "claude"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def test_answerer_exit_codes():
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "r.request.json"
        req.write_text(json.dumps({"prompt": "x"}))
        out = Path(tmp) / "r.answer.json"
        cases = [("cat >/dev/null; echo '{\"verdict\": \"follows\", \"reason\": \"r\"}'", 0),
                 ("cat >/dev/null; echo 'Not logged in. Please run /login' >&2; exit 1", 4),
                 ("cat >/dev/null; echo 'sorry'", 3),
                 ("cat >/dev/null; exit 7", 6)]
        for body, code in cases:
            claude = _fake_claude(tmp, body)
            rc = subprocess.run([sys.executable, str(FR / "claim_answer_claude.py"),
                                 "--request", str(req), "--answer", str(out),
                                 "--claude", str(claude), "--timeout", "20"],
                                capture_output=True, text=True, timeout=60)
            assert rc.returncode == code, (body, rc.returncode, rc.stderr)
            if code == 4:
                assert "NOT_LOGGED_IN" in rc.stderr
        claude = _fake_claude(tmp, "sleep 30")
        rc = subprocess.run([sys.executable, str(FR / "claim_answer_claude.py"),
                             "--request", str(req), "--answer", str(out),
                             "--claude", str(claude), "--timeout", "1"],
                            capture_output=True, text=True, timeout=60)
        assert rc.returncode == 5, rc


def test_cli_exit_codes():
    bench = Bench()
    batch = bench.tmp / "batch"
    batch.mkdir()
    (batch / "01-trend-hunter.json").write_text(json.dumps({"topics": [TOPIC]}))
    (batch / "03-content-researcher.json").write_text(json.dumps({"scripts": [SCRIPT]}))
    run = lambda *a: subprocess.run(  # noqa: E731
        [sys.executable, str(FR / "claim_judge.py"), *a, "--answer-cmd", bench.cmd],
        capture_output=True, text=True, timeout=120)
    r = run(str(batch / "03-content-researcher.json"))
    assert r.returncode == 1 and "claim_not_entailed c4" in r.stdout, (r.stdout, r.stderr)
    assert (batch / "work" / "claim-judge-cache").is_dir()
    assert run(str(batch / "missing.json")).returncode == 3
    bench.write(exit=4, stderr="NOT_LOGGED_IN")
    r = run(str(batch / "03-content-researcher.json"), "--cache-dir", str(bench.tmp / "c2"))
    assert r.returncode == 3 and "NOT_LOGGED_IN" in r.stderr, r.stderr


# ------------------------------------------------------------ CF-0554 reveals
# The Harbourlights finale (Q10): the episode's description is written at 03:13
# UTC, the 0701Z batch checks it 3.8 hours later, the 12:44 rebuild 7.7 hours
# later. The synthetic history and its stand-in API are test_reveal_age.py's.
tra = _load("test_reveal_age_cf0554", ROOT / "tests" / "test_reveal_age.py")
NEWS = {"id": "rss:1", "kind": "rss_summary", "source": "rss",
        "title": "'Harbourlights' Finale: Hal Garrett's Killer Revealed, Zorvath Creates [SPOILER]",
        "url": "https://variety.test/harbourlights", "publication": "Variety",
        "published_at": "2026-10-05T04:00:00Z", "revision_id": None, "revised_at": None,
        "text": "The season finale answers who killed Hal Garrett."}
CAST = {"id": "wikipedia:Harbourlights_(TV_series)", "kind": "work_article", "source": "wikipedia",
        "title": "Harbourlights (TV series)", "url": "https://en.wikipedia.org/wiki/Harbourlights",
        "revision_id": 104, "revised_at": "2026-10-05T06:48:00Z",
        "text": "Kelly Macdonald as Kerry Kane, a sheriff."}
R_TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"},
           "support_text": [dict(tra.PIECE, title="Dirt and Stars"), CAST, NEWS]}
REVEAL = "Kerry killed Hal to protect Noah"
CASTING = "Kelly Macdonald plays sheriff Kerry Kane"
R_SCRIPT = {
    "script_id": "s1", "topic_id": "t1",
    "hook": f"{REVEAL}.", "commentary": f"{CASTING}.", "payoff": "What a finale.",
    "production_fact": {"beat_text": CASTING},
    "claims": [
        {"claim_id": "c1", "where": "hook", "text": REVEAL,
         "support": [{"source": tra.PIECE["id"], "quote": tra.QUOTE}]},
        {"claim_id": "c2", "where": "commentary", "text": CASTING,
         "support": [{"source": CAST["id"], "quote": "Kelly Macdonald as Kerry Kane"}]},
    ],
}
R_EXTRACT = [{"where": "hook", "text": REVEAL}, {"where": "commentary", "text": CASTING}]
R_ENTAIL = {REVEAL: "follows", CASTING: "follows"}
R_REVEAL = {REVEAL: True, CASTING: False}


def reveal_judge(now, news=None, history=None, script=None, down=False):
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=R_REVEAL, news=news or {})
    revs, wiki = tra.revisions(history or tra.HISTORY, down=down)
    rep = cj.judge_script(copy.deepcopy(script or R_SCRIPT), topic=R_TOPIC, pool={}, plan=None,
                          asker=bench.asker(), revisions=revs, now=now)
    return rep, bench, wiki


def _row(rep, cid):
    return next(v for v in rep["verdicts"] if v["claim_id"] == cid)


def test_harbourlights_0701z_a_reveal_on_text_3_8_hours_old_is_struck():
    rep, bench, _ = reveal_judge("2026-10-05T07:01:00Z")
    assert rep["action"] == "fail"
    assert [v["code"] for v in rep["violations"]] == ["reveal_too_fresh"], rep["violations"]
    row = _row(rep, "c1")
    assert row["verdict"] == "follows" and row["state"] == "struck", row
    rv = row["reveal"]
    assert rv["age_h"] == 3.8 and rv["stable"] is False and rv["second_source"] is False, rv
    assert rv["quotes"][0]["state"] == "fresh" and rv["second_source_verdict"] == "not_enough"
    assert [s["claim_id"] for s in rep["struck"]] == ["c1"]
    assert rep["fact_struck"] is False and rep["refuse_now"] is False
    assert "reveal" not in _row(rep, "c2"), "the casting claim is not a reveal"
    # the second source is asked with the news items alone
    news = [r for r in bench.requests() if r["kind"] == "entail"
            and {f["kind"] for f in r["payload"]["footing"]} == {"news"}]
    # (asked twice: a "no" gets a second opinion, CF-0579)
    assert [r["payload"].get("opinion") for r in news] == [None, 2], news
    assert all(r["payload"]["claim"] == REVEAL for r in news)
    assert [o["verdict"] for o in rv["second_source_opinions"]] == ["not_enough"] * 2
    blob = json.dumps(news[0]["payload"]["footing"])
    assert "Variety" in blob and "protect Noah" not in blob and "wikipedia" not in blob, blob


def test_the_1244z_rebuild_on_text_past_6_hours_passes():
    rep, bench, _ = reveal_judge("2026-10-05T12:44:00Z")
    assert rep["action"] == "pass", rep["violations"]
    rv = _row(rep, "c1")["reveal"]
    assert rv["stable"] is True and rv["age_h"] >= 6 and rv["second_source"] is False, rv
    assert not any({f["kind"] for f in r["payload"]["footing"]} == {"news"}
                   for r in bench.requests() if r["kind"] == "entail"), "news asked needlessly"


def test_a_news_item_that_says_it_lets_a_4_hour_old_reveal_through():
    rep, _, _ = reveal_judge("2026-10-05T07:01:00Z", news={REVEAL: "follows"})
    assert rep["action"] == "pass", rep["violations"]
    rv = _row(rep, "c1")["reveal"]
    assert rv["stable"] is False and rv["second_source"] is True and rv["age_h"] == 3.8, rv


def test_a_reveal_taken_out_and_put_back_is_struck_and_the_fact_takes_the_video():
    s = copy.deepcopy(R_SCRIPT)
    s["production_fact"] = {"beat_text": REVEAL}
    rep, _, _ = reveal_judge("2026-10-05T12:44:00Z", history=tra.WITH_REVERT, script=s)
    assert "reveal_too_fresh" in cj.all_codes(rep)
    assert _row(rep, "c1")["reveal"]["quotes"][0]["state"] == "reverted"
    assert rep["fact_struck"] is True and rep["refuse_now"] is True


def test_no_reveal_no_history_and_wikipedia_down_is_not_a_pass():
    calm = dict(R_REVEAL, **{REVEAL: False})
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=calm)
    revs, wiki = tra.revisions(down=True)
    rep = cj.judge_script(copy.deepcopy(R_SCRIPT), topic=R_TOPIC, pool={}, plan=None,
                          asker=bench.asker(), revisions=revs, now="2026-10-05T07:01:00Z")
    assert rep["action"] == "pass" and not wiki.urls, wiki.urls
    rep, _, wiki = reveal_judge("2026-10-05T12:44:00Z", down=True)
    assert wiki.urls and _row(rep, "c1")["reveal"]["quotes"][0]["state"] == "unreachable"
    assert "reveal_too_fresh" in cj.all_codes(rep)


def test_the_real_model_must_say_whether_it_is_a_reveal():
    v1 = {"verdict": "follows", "reason": "r"}
    assert cj.check_entail_answer(v1) == []
    assert cj.check_entail_answer(v1, require_reveal=True)
    assert cj.check_entail_answer(dict(v1, reveal="yes"))
    assert cj.check_entail_answer(dict(v1, reveal=False), require_reveal=True) == []
    os.environ.pop(cj.ANSWER_CMD_ENV, None)
    assert cj.Asker(TMP / "x").default_answerer is True
    assert Bench().asker().default_answerer is False
    assert '"reveal": true | false' in cj.ENTAIL_PROMPT and cj.PROMPT_VERSION >= 2


def test_the_record_name_and_the_code():
    assert cj.CHECK_FIELD == "claims_check"
    assert cj.SKIP_REASON_CODE == "claim_unsupported"
    assert set(cj.FIXES) == set(cj.FAIL_CODES)
    os.environ.pop(cj.ANSWER_CMD_ENV, None)
    assert "claim_answer_claude.py" in cj.answer_cmd_template()


# ------------------------------------------------------------ CF-0636 TVmaze
# An episode description read from the TVmaze API (shared/tvmaze/tvmaze_api.py
# `episode_piece`) is a second source of a fresh reveal, like a news item.
TVMAZE = {"id": "tvmaze:episode:3311111", "kind": "tvmaze_episode", "source": "tvmaze",
          "publication": "TVmaze", "title": "Dirt and Stars", "show": "Harbourlights",
          "url": "https://www.tvmaze.com/episodes/3311111/harbourlights-1x08-dirt-and-stars",
          "revision_id": None, "revised_at": None, "fetched_at": "2026-10-05T06:30:00Z",
          "season": 1, "episode": 8, "air_date": "2026-10-04",
          "license": {"title": "CC BY-SA 4.0"},
          "text": "Kerry confesses that she killed Hal to protect Noah."}
T_TOPIC = {"topic_id": "t1", "support_check": {"state": "ok"},
           "support_text": [dict(tra.PIECE, title="Dirt and Stars"), CAST, TVMAZE]}


def test_tvmaze_episode_description_is_a_second_source_for_a_fresh_reveal():
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=R_REVEAL, news={REVEAL: "follows"})
    revs, _ = tra.revisions(tra.HISTORY)
    rep = cj.judge_script(copy.deepcopy(R_SCRIPT), topic=T_TOPIC, pool={}, plan=None,
                          asker=bench.asker(), revisions=revs, now="2026-10-05T07:01:00Z")
    assert rep["action"] == "pass", rep["violations"]
    rv = _row(rep, "c1")["reveal"]
    assert rv["stable"] is False and rv["second_source"] is True, rv
    asked = [r for r in bench.requests() if r["kind"] == "entail"
             and {f["kind"] for f in r["payload"]["footing"]} == {"news"}]
    footing = asked[0]["payload"]["footing"]
    assert footing == [{"kind": "news", "publication": "TVmaze",
                        "title": "Harbourlights S1E8 «Dirt and Stars» (aired 2026-10-04)",
                        "summary": TVMAZE["text"]}], footing


def test_a_fresh_reveal_without_any_second_source_says_so():
    topic = dict(R_TOPIC, support_text=[dict(tra.PIECE, title="Dirt and Stars"), CAST])
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=R_REVEAL)
    revs, _ = tra.revisions(tra.HISTORY)
    rep = cj.judge_script(copy.deepcopy(R_SCRIPT), topic=topic, pool={}, plan=None,
                          asker=bench.asker(), revisions=revs, now="2026-10-05T07:01:00Z")
    rv = _row(rep, "c1")["reveal"]
    assert rv["second_source"] is False and "TVmaze" in rv["second_source_reason"], rv
    assert "reveal_too_fresh" in cj.all_codes(rep)


def test_a_reveal_quoted_from_tvmaze_alone_is_its_own_second_source():
    s = copy.deepcopy(R_SCRIPT)
    s["claims"][0]["support"] = [{"source": TVMAZE["id"], "quote": "she killed Hal to protect Noah"}]
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=R_REVEAL)
    revs, wiki = tra.revisions(tra.HISTORY)
    rep = cj.judge_script(s, topic=T_TOPIC, pool={}, plan=None, asker=bench.asker(),
                          revisions=revs, now="2026-10-05T07:01:00Z")
    assert rep["action"] == "pass", rep["violations"]
    rv = _row(rep, "c1")["reveal"]
    assert rv["quotes"] == [] and rv["second_source"] is True, rv
    assert "TVmaze" in rv["second_source_reason"], rv
    # the mechanics read the piece like any other: found, its kind and its read time
    sup = next(r for r in rep["mechanics"]["results"] if r["claim_id"] == "c1")["supports"][0]
    assert sup["found"] and sup["piece_kind"] == "tvmaze_episode", sup
    assert sup["fetched_at"] == TVMAZE["fetched_at"] and sup["url"] == TVMAZE["url"], sup
    # the judge sees the quote with its source's kind
    footing = cj.footing_of(next(r for r in rep["mechanics"]["results"] if r["claim_id"] == "c1"),
                            cj.claims.support_pieces(T_TOPIC))
    assert footing[0]["source_kind"] == "tvmaze_episode"


# ---------------------------------------------------------- CF-0637 Wikidata
# A statement read from Wikidata (shared/wikidata/wikidata_api.py
# `statement_piece`): one English sentence a claim may quote - never a fresh
# reveal's second source, and its quote is not aged (no Wikipedia page).
WIKIDATA = {"id": "wikidata:Q110556821:P161:Q230383", "kind": "wikidata_statement",
            "source": "wikidata", "publication": "Wikidata", "title": "Harbourlights - cast member",
            "entity": "Q110556821", "property": "P161", "value": "Q230383",
            "value_label": "Kelly Macdonald", "fact_kind": "casting",
            "url": "https://www.wikidata.org/wiki/Q110556821#P161",
            "revision_id": 2553543430, "revised_at": "2026-10-05T17:06:06Z",
            "fetched_at": "2026-10-08T15:39:50Z", "license": {"title": "CC0 1.0"},
            "text": "Kelly Macdonald is in the cast of Harbourlights as Kerry Kane."}


def test_a_casting_claim_quotes_a_wikidata_statement():
    s = copy.deepcopy(R_SCRIPT)
    s["claims"][1]["support"] = [{"source": WIKIDATA["id"],
                                  "quote": "Kelly Macdonald is in the cast of Harbourlights as Kerry Kane"}]
    topic = dict(R_TOPIC, support_text=R_TOPIC["support_text"] + [WIKIDATA])
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=R_REVEAL, news={REVEAL: "follows"})
    revs, _ = tra.revisions(tra.HISTORY)
    rep = cj.judge_script(s, topic=topic, pool={}, plan=None, asker=bench.asker(),
                          revisions=revs, now="2026-10-05T07:01:00Z")
    assert rep["action"] == "pass", rep["violations"]
    res = next(r for r in rep["mechanics"]["results"] if r["claim_id"] == "c2")
    sup = res["supports"][0]
    assert sup["found"] and sup["piece_kind"] == "wikidata_statement", sup
    assert sup["revision_id"] == WIKIDATA["revision_id"] and sup["url"] == WIKIDATA["url"], sup
    footing = cj.footing_of(res, cj.claims.support_pieces(topic))
    assert footing[0]["source_kind"] == "wikidata_statement"
    assert footing[0]["source_title"] == "Harbourlights - cast member"


def test_a_reveal_on_a_wikidata_statement_alone_has_no_second_source():
    piece = dict(WIKIDATA, id="wikidata:Q1:P9999:abc", text=f"{REVEAL}.")
    s = copy.deepcopy(R_SCRIPT)
    s["claims"][0]["support"] = [{"source": piece["id"], "quote": REVEAL}]
    topic = dict(R_TOPIC, support_text=[CAST, piece])
    bench = Bench(extract=R_EXTRACT, entail=R_ENTAIL, reveal=R_REVEAL)
    revs, _ = tra.revisions(tra.HISTORY)
    rep = cj.judge_script(s, topic=topic, pool={}, plan=None, asker=bench.asker(),
                          revisions=revs, now="2026-10-05T07:01:00Z")
    rv = _row(rep, "c1")["reveal"]
    assert rv["second_source"] is False and rv["stable"] is False, rv
    assert [q["state"] for q in rv["quotes"]] == ["no_page"], rv
    assert "reveal_too_fresh" in cj.all_codes(rep)
    assert cj.WIKIDATA_KIND not in cj.SECOND_SOURCE_KINDS
    assert cj.news_footing(cj.claims.support_pieces(topic)) == []


# ------------------------------------------------------- CF-0728: the line before
# The shape of sophie-adenot (rebuild 2026-10-13T0524Z): a contrast script in
# pairs whose payoff "That award came years before it." was struck at the card
# as claim_not_enough - read alone, "it" is not told. Short synthetic texts.
SA_TEXT = ("Adenot is a French astronaut and a colonel of the air force. Her first "
           "spaceflight began in February 2026 aboard Crew-12. In 2021 she received an award "
           "for her work as an ambassador for gender equality in science.")
SA_TOPIC = {"topic_id": "sa", "support_check": {"state": "ok"}, "support_text": [
    {"id": "wikipedia:Adenot", "kind": "work_article", "title": "Adenot",
     "url": "https://en.wikipedia.org/wiki/Adenot", "revision_id": 7,
     "revised_at": "2026-10-11T00:00:00Z", "text": SA_TEXT}]}
SA_FLIGHT = {"source": "wikipedia:Adenot",
             "quote": "Her first spaceflight began in February 2026 aboard Crew-12"}
SA_AWARD = {"source": "wikipedia:Adenot",
            "quote": "In 2021 she received an award for her work as an ambassador for gender "
                     "equality in science"}
SA_PAYOFF = "That award came years before it."
SA_SCRIPT = {
    "script_id": "sa1", "topic_id": "sa",
    "pattern": {"pattern_id": "contrast", "sides": {"pairs": [
        {"a": "Adenot flew to the station on Crew-12 in February.",
         "b": "In twenty twenty one, an award honoured her work for gender equality."},
        {"a": "The flight is the headline.", "b": SA_PAYOFF}]}},
    "hook": "Adenot flew to the station on Crew-12 in February.",
    "commentary": "In twenty twenty one, an award honoured her work for gender equality.",
    "payoff": "The flight is the headline. " + SA_PAYOFF,
    "production_fact": {"beat_text": "In twenty twenty one, an award honoured her work for "
                                     "gender equality.",
                        "on_screen": "2021 award: gender equality in science"},
    "claims": [
        {"claim_id": "c1", "where": "hook",
         "text": "Adenot flew to the station on Crew-12 in February.", "support": [SA_FLIGHT]},
        {"claim_id": "c2", "where": "commentary",
         "text": "In twenty twenty one, an award honoured her work for gender equality.",
         "support": [SA_AWARD]},
        {"claim_id": "c3", "where": "payoff", "text": SA_PAYOFF, "support": [SA_AWARD, SA_FLIGHT]},
        {"claim_id": "c4", "where": "on_screen", "text": "2021 award: gender equality in science",
         "support": [SA_AWARD]},
    ],
}
SA_EXTRACT = [{"where": c["where"], "text": c["text"]} for c in SA_SCRIPT["claims"]]
SA_ENTAIL = {c["text"]: "follows" for c in SA_SCRIPT["claims"]}


# CF-0808: the hook first, then up to three lines before the claim
SA_CONTEXT = [SA_SCRIPT["hook"], SA_SCRIPT["commentary"], "The flight is the headline."]


def _sa_bench(**kw):
    return Bench(extract=SA_EXTRACT, entail=SA_ENTAIL,
                 needs_context={SA_PAYOFF: SA_CONTEXT}, **kw)


def test_cf0728_the_payoff_is_judged_with_the_line_before_it():
    bench = _sa_bench()
    rep = cj.judge_script(copy.deepcopy(SA_SCRIPT), topic=SA_TOPIC, pool={}, plan=None,
                          asker=bench.asker())
    assert rep["mechanics"]["action"] == "pass", rep["mechanics"]
    assert rep["action"] == "pass", rep["violations"]
    row = _row(rep, "c3")
    assert row["verdict"] == "follows" and row["context"] == SA_CONTEXT, row
    entail = {r["payload"]["claim"]: r for r in bench.requests() if r["kind"] == "entail"}
    req = entail[SA_PAYOFF]
    assert req["payload"]["context"] == SA_CONTEXT
    # the context is marked as not a claim and not footing; the footing is as before
    assert cj.CONTEXT_HEAD in req["prompt"] and "not a claim" in cj.CONTEXT_HEAD
    assert [f["quote"] for f in req["payload"]["footing"]] == [SA_AWARD["quote"],
                                                                SA_FLIGHT["quote"]]
    assert all(f["kind"] == "quote" for f in req["payload"]["footing"])
    # a claim that does not point back is asked as before; the on-screen words have no line
    assert "context" not in entail["Adenot flew to the station on Crew-12 in February."]["payload"]
    assert "context" not in entail["2021 award: gender equality in science"]["payload"]
    # the context is the video's own words only - never the topic's text
    spoken = " ".join(SA_SCRIPT[w] for w in ("hook", "commentary", "payoff"))
    for r in entail.values():
        for line in r["payload"].get("context", []):
            assert line in spoken and line not in SA_TEXT, line


def test_cf0728_read_alone_it_is_not_enough_and_the_judge_says_what_is_missing():
    s = copy.deepcopy(SA_SCRIPT)
    s["payoff"] = SA_PAYOFF                       # the line before it is gone
    s["pattern"]["sides"]["pairs"] = []
    rep = cj.judge_script(s, topic=SA_TOPIC, pool={}, plan=None, asker=_sa_bench().asker())
    assert [v["code"] for v in rep["violations"]] == ["claim_not_enough"], rep["violations"]
    row = _row(rep, "c3")
    assert row["missing"] == "what 'it' refers to", row
    assert all(o.get("missing") == "what 'it' refers to" for o in row["opinions"]), row
    assert "Missing: what 'it' refers to" in rep["violations"][0]["detail"]
    # its context is now the hook and the commentary, not the flight: the stand-in says no
    assert row["context"] == [SA_SCRIPT["hook"], "In twenty twenty one, an award honoured "
                                                 "her work for gender equality."]


def test_cf0728_the_pair_gives_its_first_line_and_a_mid_sentence_claim_its_start():
    texts = {"commentary": "In July she was knighted.", "payoff": SA_PAYOFF}
    pairs = [{"a": "The flight is the headline.", "b": SA_PAYOFF}]
    assert cj.claim_context(SA_PAYOFF, "payoff", texts, pairs) == [
        "The flight is the headline.", "In July she was knighted."]
    assert cj.claim_context(SA_PAYOFF, "payoff", texts) == ["In July she was knighted."]
    d = {"description": "Adenot flew in 2026. Years before the flight, she was honoured."}
    assert cj.claim_context("she was honoured", "description", d) == [
        "Adenot flew in 2026.", "Years before the flight"]
    assert cj.claim_context("Adenot flew in 2026", "description", d) == []     # no pointing word
    assert cj.claim_context("that award", "on_screen", {"on_screen": "x. that award"}) == []
    assert cj.claim_context("Not in the text at all.", "payoff", texts) == []
    assert cj.claim_context(SA_PAYOFF, "payoff", {"payoff": SA_PAYOFF}) == []  # nothing before


def test_cf0728_the_real_model_names_what_is_missing():
    no = {"verdict": "not_enough", "reason": "r", "reveal": False}
    assert cj.check_entail_answer(no, require_reveal=True)
    assert cj.check_entail_answer(dict(no, missing="  "), require_reveal=True)
    assert cj.check_entail_answer(dict(no, missing="the referent of it"),
                                  require_reveal=True) == []
    assert cj.check_entail_answer(no) == []                      # a stand-in may give v3
    assert cj.check_entail_answer(dict(no, missing=3))
    yes = {"verdict": "follows", "reason": "r", "reveal": False}
    assert cj.check_entail_answer(yes, require_reveal=True) == []
    assert '"missing"' in cj.ENTAIL_PROMPT and "CONTEXT" in cj.ENTAIL_PROMPT
    assert cj.PROMPT_VERSION >= 4



def test_cf0737_sentences_go_on_past_an_abbreviation_an_initial_and_a_decimal():
    text = ("In February 2007, it was announced that Example Studios had hired "
            "Dr. J. Smith. The film grossed $27.5 million, about 2.5 million more than "
            "the U.S. tracking! He said “that is it.” Then it ended…  And again")
    assert cj.sentences(text) == [
        "In February 2007, it was announced that Example Studios had hired Dr. J. Smith.",
        "The film grossed $27.5 million, about 2.5 million more than the U.S. tracking!",
        "He said “that is it.”", "Then it ended…", "And again"]
    assert cj.sentences("") == [] and cj.sentences(None) == []
    assert cj.sentences("One. Two? Three!") == ["One.", "Two?", "Three!"]


def test_cf0737_the_context_of_a_pointing_claim_is_the_whole_sentence_before():
    d = {"description": "Example Studios paid $27.5 million for it. That deal made "
                        "the film."}
    assert cj.claim_context("That deal made the film", "description", d) == [
        "Example Studios paid $27.5 million for it."]

# --------------------------------------------- CF-0808: the judge reads the hook
# and up to three substantive lines before a pointing claim; "Two." is no line.
# example-tech 2026-10-19T0844Z topic 023 (part of 022): "It began as Project
# Tailwind, ..." in list narration reached the judge with "Two." (or a line
# about a feature) as its only context and was struck - the subject, Gemini
# Notebook, is named in the hook.
GN_HOOK = ("Gemini Notebook used to be called NotebookLM. Google renamed it on July "
           "sixteenth, twenty twenty-six.")
GN_COMMENTARY = ("One. Audio Overviews arrived in September twenty twenty-four. Two. Short "
                 "Video Overviews then went global, in English. Three. Each notebook now "
                 "gets a secure cloud computer. That computer runs code for data analysis.")
GN_CLAIM = "It began as Project Tailwind, a notebook that learns from documents."
GN_TEXTS = {"hook": GN_HOOK, "commentary": GN_COMMENTARY,
            "payoff": GN_CLAIM + " Now it runs code on them."}


def test_cf0808_what_a_fragment_is():
    for f in ("Two.", "First,", "One.", "Number one.", "3.", "And then?"):
        assert cj.is_fragment(f), f
    for f in ("It flew far.", "Short Video Overviews then went global, in English."):
        assert not cj.is_fragment(f), f
    assert cj.CONTEXT_BEFORE == 3 and cj.FRAGMENT_WORDS == 2


def test_cf0808_list_narration_gives_the_hook_and_three_lines_without_the_markers():
    ctx = cj.claim_context(GN_CLAIM, "payoff", GN_TEXTS)
    assert ctx == [
        "Gemini Notebook used to be called NotebookLM.",
        "Google renamed it on July sixteenth, twenty twenty-six.",
        "Short Video Overviews then went global, in English.",
        "Each notebook now gets a secure cloud computer.",
        "That computer runs code for data analysis."], ctx
    assert not any(cj.is_fragment(x) for x in ctx)
    # the line right before is a marker only: it is skipped, not the whole context
    t = {"hook": GN_HOOK, "commentary": "Two.", "payoff": GN_CLAIM}
    assert cj.claim_context(GN_CLAIM, "payoff", t) == [
        "Gemini Notebook used to be called NotebookLM.",
        "Google renamed it on July sixteenth, twenty twenty-six."]


def test_cf0808_the_hook_is_not_repeated_and_not_added_to_a_claim_in_the_hook():
    # the window reaches into the hook: each hook line once, in the order heard
    t = {"hook": "Gemini Notebook is new. Google built it.",
         "commentary": "Two.", "payoff": GN_CLAIM}
    assert cj.claim_context(GN_CLAIM, "payoff", t) == [
        "Gemini Notebook is new.", "Google built it."]
    t = {"hook": "Gemini Notebook is new. Google built it.", "commentary": "It runs code."}
    assert cj.claim_context("It runs code.", "commentary", t) == [
        "Gemini Notebook is new.", "Google built it."]
    # a claim in the hook: only the lines before it in the hook
    assert cj.claim_context("Google built it.", "hook", t) == ["Gemini Notebook is new."]
    # the title and the description stay inside their own field: no hook
    d = dict(t, description="One. Gemini Notebook is Google's. It began as Project Tailwind.")
    assert cj.claim_context("It began as Project Tailwind", "description", d) == [
        "Gemini Notebook is Google's."]


def test_cf0808_older_lines_go_and_the_pair_comes_after_the_hook():
    t = {"hook": "The hook names it.",
         "commentary": "Line A is long. Line B is long. Line C is long. Line D is long.",
         "payoff": "It ends here."}
    assert cj.claim_context("It ends here.", "payoff", t) == [
        "The hook names it.", "Line B is long.", "Line C is long.", "Line D is long."]
    pairs = [{"a": "Line A is long.", "b": "It ends here."}]
    assert cj.claim_context("It ends here.", "payoff", t, pairs) == [
        "The hook names it.", "Line A is long.", "Line B is long.", "Line C is long.",
        "Line D is long."]


def test_cf0808_the_judge_reads_the_list_claim_with_its_subject_and_the_cache_moves():
    assert cj.PROMPT_VERSION >= 5
    assert "opening" in cj.CONTEXT_HEAD and "not a claim" in cj.CONTEXT_HEAD
    assert "hook" in cj.ENTAIL_PROMPT
    p = cj.entail_prompt(GN_CLAIM, [{"kind": "quote", "quote": "q"}],
                         cj.claim_context(GN_CLAIM, "payoff", GN_TEXTS))
    assert "Gemini Notebook used to be called NotebookLM." in p and '"Two."' not in p
    k = cj.request_key("entail", "m", {"claim": GN_CLAIM})
    old, cj.PROMPT_VERSION = cj.PROMPT_VERSION, 4
    try:
        assert cj.request_key("entail", "m", {"claim": GN_CLAIM}) != k
    finally:
        cj.PROMPT_VERSION = old


# --------------------------------------------- CF-0758: a bare name is the name
# example-tech 1854Z: the reader listed the hook's "here's RTX Spark", no claim
# of the hook covered it, and the only script of the batch was dropped while
# `c1` "Nvidia RTX Spark" (a card's title) followed from its article. The
# stand-in below keeps that shape: the name declared in another field (here
# the title the card hands in), the hook only presenting it.
SPARK_TEXT = ("Nvidia RTX Spark is an Arm-based system on chip developed by Nvidia for "
              "Windows laptops.")
SPARK_TOPIC = {"topic_id": "t2", "support_check": {"state": "ok"}, "support_text": [
    {"id": "wikipedia:Nvidia_RTX_Spark", "kind": "work_article", "title": "Nvidia RTX Spark",
     "url": "https://en.wikipedia.org/wiki/Nvidia_RTX_Spark", "revision_id": 3,
     "revised_at": "2026-10-05T00:00:00Z", "text": SPARK_TEXT}]}
Q_SPARK = {"source": "wikipedia:Nvidia_RTX_Spark",
           "quote": "Nvidia RTX Spark is an Arm-based system on chip"}
SPARK_CHIP = "an Arm-based system on chip for Windows laptops"


def _spark(hook):
    script = {"script_id": "s2", "topic_id": "t2", "hook": hook,
              "commentary": f"It is {SPARK_CHIP}.",
              "claims": [
                  {"claim_id": "c1", "where": "title", "text": "Nvidia RTX Spark",
                   "support": [Q_SPARK]},
                  {"claim_id": "c2", "where": "commentary", "text": SPARK_CHIP,
                   "support": [{"source": "wikipedia:Nvidia_RTX_Spark",
                                "quote": "an Arm-based system on chip developed by Nvidia for "
                                         "Windows laptops"}]}]}
    listed = [{"where": "hook", "text": hook.rstrip(".")},
              {"where": "commentary", "text": SPARK_CHIP},
              {"where": "title", "text": "Nvidia RTX Spark"}]
    bench = Bench(extract=listed, entail={"Nvidia RTX Spark": "follows", SPARK_CHIP: "follows"})
    rep = cj.judge_script(script, topic=SPARK_TOPIC, pool={}, plan=None,
                          extra_texts={"title": "Nvidia RTX Spark"}, asker=bench.asker())
    return rep


def test_cf0758_a_hook_that_only_presents_the_declared_name_is_that_claim():
    rep = _spark("Here's RTX Spark.")
    assert rep["mechanics"]["action"] == "pass", rep["mechanics"]["violations"]
    assert [e["matched"] for e in rep["extracted"]] == [["c1"], ["c2"], ["c1"]], rep["extracted"]
    assert rep["action"] == "pass" and rep["violations"] == [], rep["violations"]


def test_cf0758_a_hook_that_says_more_than_the_name_is_still_undeclared():
    rep = _spark("Here's the fastest chip.")
    assert [v["code"] for v in rep["violations"]] == ["claim_undeclared"], rep["violations"]
    assert rep["violations"][0]["text"] == "Here's the fastest chip"
    assert rep["action"] == "fail"


def test_cf0758_what_a_bare_name_is():
    for span, name in [("here's RTX Spark", "RTX Spark"), ("Here’s RTX Spark!", "RTX Spark"),
                       ("meet the Surface Laptop Ultra", "Surface Laptop Ultra"),
                       ("this is RTX Spark", "RTX Spark"), ("Nvidia RTX Spark.", "Nvidia RTX Spark"),
                       ("Lord of the Rings", "Lord of the Rings")]:
        assert cj.bare_name(span) == name, span
    for span in ["here's the fastest chip", "meet RTX Spark, Nvidia's new chip",
                 "RTX Spark is fast", "CPU: 20-core Grace", "Announced: May 31, 2026",
                 "here is 2026", "here's RTX Spark and the fastest GPU ever made by anyone"]:
        assert cj.bare_name(span) is None, span


def test_cf0758_the_name_crosses_fields_and_nothing_else_does():
    declared = [{"claim_id": "c1", "where": "graphic:g1", "text": "Nvidia RTX Spark"},
                {"claim_id": "c7", "where": "graphic:g3", "text": "CPU: 20-core Grace"},
                {"claim_id": "c9", "where": "commentary",
                 "text": "RTX Spark is the fastest chip Nvidia has made"}]
    listed = [{"where": "hook", "text": "here's RTX Spark"},
              {"where": "hook", "text": "meet Nvidia RTX Spark"},
              {"where": "hook", "text": "here's Grace"},
              {"where": "hook", "text": "here's the fastest chip"},
              {"where": "hook", "text": "here's RTX Spark Ultra"},
              {"where": "hook", "text": "RTX Spark is the fastest chip Nvidia has made"}]
    assert cj.match_extracted(listed, declared) == [["c1"], ["c1"], [], [], [], []]


# ------------------------------------- CF-0780: a change frame is the fact
# example-tech 0839Z: the card of gemini-4-argon was refused on its hook
# "Here's what actually changed in Gemini 4 Argon." - the frame of a list
# whose fourth beat, the video's fact, is "all 12 solved, up from five".
ARGON_FACT = ("In Google's simulated cyberattack tests, Gemini 4 Argon solved all 12 "
              "end-to-end scenarios, up from five in the previous generation.")
ARGON_DECLARED = [
    {"claim_id": "c1", "where": "commentary", "text": "Argon is starting to roll out broadly."},
    {"claim_id": "c7", "where": "commentary",
     "text": "In Google's simulated cyberattack tests, Argon solved all twelve end-to-end "
             "scenarios."},
    {"claim_id": "c8", "where": "commentary", "text": "The previous generation managed five."},
    {"claim_id": "c10", "where": "on_screen",
     "text": "Cyberattack tests: all 12 solved, up from five"}]


def _argon(fact=ARGON_FACT, on_screen="Cyberattack tests: all 12 solved, up from five",
           beat=("Four. In Google's simulated cyberattack tests, Argon solved all twelve "
                 "end-to-end scenarios. The previous generation managed five.")):
    return {"script_id": "s3", "claims": ARGON_DECLARED,
            "production_fact": {"text": fact, "beat_text": beat, "on_screen": on_screen}}


def test_cf0780_what_a_change_frame_is():
    for span, name in [("Here's what actually changed in Gemini 4 Argon.", "Gemini 4 Argon"),
                       ("here’s what changed in the Pixel 11", "Pixel 11"),
                       ("Here is what's new in Android 17", "Android 17"),
                       ("this is what has really changed with Gemini", "Gemini")]:
        assert cj.change_frame_name(span) == name, span
    for span in ["Here's why Gemini 4 Argon is the fastest model",
                 "Here's what changed in Gemini 4 Argon: it beat GPT-6",
                 "Here's what Gemini 4 Argon changed",
                 "Here's what actually changed in the fastest model",
                 "Gemini 4 Argon changed everything", "here's Gemini 4 Argon", None]:
        assert cj.change_frame_name(span) is None, span
    assert cj.is_change("all 12 solved, up from five")
    assert cj.is_change("The previous generation managed five.")
    assert not cj.is_change("Gemini 4 Argon solved all 12 scenarios in Google's tests.")


def test_cf0780_a_change_frame_is_backed_by_a_fact_that_is_a_change():
    listed = [{"where": "hook", "text": "Here's what actually changed in Gemini 4 Argon."}]
    assert cj.match_extracted(listed, ARGON_DECLARED, _argon()) == [["c7", "c8", "c10"]]
    # without the script (the old call) nothing crosses to the fact
    assert cj.match_extracted(listed, ARGON_DECLARED) == [[]]


def test_cf0780_the_frame_still_needs_a_change_its_subject_and_nothing_more():
    frame = [{"where": "hook", "text": "Here's what actually changed in Gemini 4 Argon."}]
    still = _argon(fact="In Google's tests, Gemini 4 Argon solved all 12 scenarios.",
                   on_screen="Cyberattack tests: all 12 solved",
                   beat="Four. In Google's tests, Argon solved all twelve scenarios.")
    assert cj.match_extracted(frame, ARGON_DECLARED, still) == [[]]
    other = [{"where": "hook", "text": "Here's what actually changed in Claude Opus 6."}]
    assert cj.match_extracted(other, ARGON_DECLARED, _argon()) == [[]]
    more = [{"where": "hook", "text": "Here's why Gemini 4 Argon is the safest model"},
            {"where": "hook", "text": "Here's what changed in Gemini 4 Argon: it beat GPT-6"}]
    assert cj.match_extracted(more, ARGON_DECLARED, _argon()) == [[], []]


def test_cf0780_the_judge_passes_the_frame_and_still_refuses_a_new_hook():
    topic = {"topic_id": "t3", "support_check": {"state": "ok"}, "support_text": [
        {"id": "blog:argon", "kind": "news", "title": "Gemini 4 safety",
         "url": "https://blog.example/argon", "text": ARGON_FACT}]}
    claim = {"claim_id": "c1", "where": "commentary", "text": ARGON_FACT,
             "support": [{"source": "blog:argon", "quote": ARGON_FACT}]}

    def run(hook):
        script = {"script_id": "s3", "topic_id": "t3", "hook": hook,
                  "commentary": ARGON_FACT, "claims": [claim],
                  "production_fact": {"text": ARGON_FACT, "beat_text": ARGON_FACT,
                                      "on_screen": None}}
        listed = [{"where": "hook", "text": hook.rstrip(".")},
                  {"where": "commentary", "text": ARGON_FACT}]
        bench = Bench(extract=listed, entail={ARGON_FACT: "follows"})
        return cj.judge_script(script, topic=topic, pool={}, plan=None, asker=bench.asker())

    rep = run("Here's what actually changed in Gemini 4 Argon.")
    assert rep["mechanics"]["action"] == "pass", rep["mechanics"]["violations"]
    assert [e["matched"] for e in rep["extracted"]] == [["c1"], ["c1"]], rep["extracted"]
    assert rep["action"] == "pass" and rep["violations"] == [], rep["violations"]
    rep = run("Here's why Gemini 4 Argon beats every model.")
    assert [v["code"] for v in rep["violations"]] == ["claim_undeclared"], rep["violations"]
    assert rep["action"] == "fail"

# --------------------- CF-0872: a name the quote shortens, named in full nearby
ROCKY_CLAIM = "Stephan James plays Carl Weathers, Sylvester Stallone's co-star who played Apollo Creed."
ROCKY_QUOTE = "Stephan James as Carl Weathers, Sylvester's co-star playing Apollo Creed"
ROCKY_FULL = ("- Anthony Ippolito as Sylvester Stallone, screenwriter of Rocky and the actor who "
              "plays Rocky Balboa")
ROCKY_TEXT = ("I Play Rocky is a 2026 American biographical drama film. It follows the "
              "development and production of the film Rocky (1976). Anthony Ippolito stars as "
              "Sylvester Stallone.\n== Cast ==\n" + ROCKY_FULL + "\n- AnnaSophia Robb as Sasha "
              "Czack, Sylvester's wife\n- " + ROCKY_QUOTE + "\n== Production ==\nIn October "
              "2025, Stephan James was cast as Carl Weathers.")
WD_STALLONE = {"id": "wikidata:Q1:P161:Q2", "kind": "wikidata_statement",
               "title": "I Play Rocky - cast member", "revision_id": 9,
               "text": "Anthony Ippolito is in the cast of I Play Rocky as Sylvester Stallone."}


def _rocky_topic(text=ROCKY_TEXT):
    return {"topic_id": "t2", "support_check": {"state": "ok"}, "support_text": [
        {"id": "wikipedia:I_Play_Rocky", "kind": "work_article", "title": "I Play Rocky",
         "url": "https://en.wikipedia.org/wiki/I_Play_Rocky", "revision_id": 1381956943,
         "revised_at": "2026-10-20T00:00:00Z", "text": text}, WD_STALLONE]}


def _rocky_script(claim=ROCKY_CLAIM, quote=ROCKY_QUOTE):
    return {"script_id": "r1", "topic_id": "t2", "hook": "Here is who plays whom.",
            "commentary": claim, "payoff": "That is the cast.",
            "claims": [{"claim_id": "c2", "where": "commentary", "text": claim,
                        "support": [{"source": "wikipedia:I_Play_Rocky", "quote": quote}]}]}


def _rocky_footing(topic, script):
    mech = cj.claims.check_claims(script, topic=topic, pool={}, plan=None)
    return cj.footing_of(mech["results"][0], cj.claims.support_pieces(topic))


def test_cf0872_the_line_of_the_same_source_that_names_the_person_in_full_is_footing():
    # example-film 0841Z i-play-rocky c2: the quote says "Sylvester's co-star",
    # the claim "Sylvester Stallone's co-star"; the card struck it - "the
    # footing says only 'Sylvester'" - while the same article's cast list
    # names him in full two lines up.
    footing = _rocky_footing(_rocky_topic(), _rocky_script())
    assert [f["quote"] for f in footing] == [ROCKY_QUOTE, ROCKY_FULL], footing
    line = footing[1]
    assert line["section"] == "Cast", "the line under the quote's own section, not the lead"
    assert line["source_title"] == "I Play Rocky" and line["source_kind"] == "work_article"
    bench = Bench(extract=[{"where": "commentary", "text": ROCKY_CLAIM}],
                  needs_footing={ROCKY_CLAIM: "Sylvester Stallone"})
    rep = cj.judge_script(_rocky_script(), topic=_rocky_topic(), pool={}, plan=None,
                          asker=bench.asker())
    row = _row(rep, "c2")
    assert row["state"] == "supported", (row, rep["violations"])
    sent = [r for r in bench.requests() if r["kind"] == "entail"]
    assert sent and all(ROCKY_FULL in json.dumps(r["payload"]["footing"]) for r in sent)


def test_cf0872_another_source_or_the_models_knowledge_names_nobody():
    # the full name only in Wikidata (another piece): nothing is added, the
    # claim stands on its quote alone - and is struck by the same bench
    text = ROCKY_TEXT.replace(ROCKY_FULL + "\n", "").replace(
        " Anthony Ippolito stars as Sylvester Stallone.", "")
    footing = _rocky_footing(_rocky_topic(text), _rocky_script())
    assert [f["quote"] for f in footing] == [ROCKY_QUOTE], footing
    bench = Bench(extract=[{"where": "commentary", "text": ROCKY_CLAIM}],
                  needs_footing={ROCKY_CLAIM: "Sylvester Stallone"})
    rep = cj.judge_script(_rocky_script(), topic=_rocky_topic(text), pool={}, plan=None,
                          asker=bench.asker())
    assert _row(rep, "c2")["state"] == "struck"
    assert [v["code"] for v in rep["violations"]] == ["claim_not_enough"]


def test_cf0872_no_line_for_a_name_the_quote_gives_whole_or_never_mentions():
    # the quote names him whole: the footing is the quote alone (the key unchanged)
    whole = "Anthony Ippolito as Sylvester Stallone, screenwriter of Rocky"
    claim = "Anthony Ippolito plays Sylvester Stallone, the screenwriter of Rocky."
    footing = _rocky_footing(_rocky_topic(), _rocky_script(claim, whole))
    assert [f["quote"] for f in footing] == [whole]
    # a person the quote does not mention at all is not looked up by name
    claim = "Stephan James plays Carl Weathers, Talia Shire's co-star who played Apollo Creed."
    footing = _rocky_footing(_rocky_topic(ROCKY_TEXT + "\n- Kiki Seto as Talia Shire"),
                             _rocky_script(claim))
    assert [f["quote"] for f in footing] == [ROCKY_QUOTE]
    assert cj.claim_names(ROCKY_CLAIM) == ["Stephan James", "Carl Weathers",
                                           "Sylvester Stallone", "Apollo Creed"]
    assert cj.claim_names("And Anthony Ippolito plays him") == ["Anthony Ippolito"]


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

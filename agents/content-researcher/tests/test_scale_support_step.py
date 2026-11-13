#!/usr/bin/env python3
"""CF-0673: `scripts/scale_support_step.py` - the scale stand-ins' numbers
read off their pages into `<batch>/01-scale-support.json` before they are
quoted.

Pinned here, on the pattern file's own Proxima Centauri script
(`patterns/scale.json`, the root's `tests/test_scale_footing.py` GOOD): the
step finds the Sun's diameter and the grapefruit's size on their (stubbed)
Wikipedia pages - written in `{{val}}` / `{{convert}}`, as the live pages
write them - puts them in the continuation, and then `check_claims.py` and
`check_scale.py` both pass the script that quotes them; without the step the
claim rule loses both as `source_not_in_support_text`. A number the page does
not write is `not_on_page`: exit 1 and «change the stand-in, never the
number». A closed outlet and an unreachable page are not confirmed either;
a batch with no such topic cannot be asked (exit 3).

Stand-ins only (CF-0609): the Wikipedia client is a stub over strings, the
channel's fact-sources list is a minimal copy handed in, the claim judge's
model is a canned answer command; files under `_tmproot.tmp_root` (CF-0489).
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import scale_support_step as step  # noqa: E402
import check_claims as cc  # noqa: E402
import check_scale as cs  # noqa: E402

ROOT = step.find_root()
SS = step.load_module(ROOT)
JUDGE = cc.load_judge(ROOT)
RULE = cs.load_rule(ROOT)
_TMP = tmp_root("cr-scale-support-")

SUN_URL = "https://en.wikipedia.org/wiki/Sun"
FRUIT_URL = "https://en.wikipedia.org/wiki/Grapefruit"
PROXIMA_URL = "https://en.wikipedia.org/wiki/Proxima_Centauri"
NASA_URL = "https://science.nasa.gov/sun/facts/"

WIKITEXT = {
    "Sun": "The '''Sun''' is the star at the centre of the [[Solar System]].<ref>x</ref>\n"
           "== Characteristics ==\n"
           "Its diameter is about {{val|1391400|u=km|fmt=commas}} "
           "({{val|864600|u=mi|fmt=commas}}), around 109 times that of "
           "[[Earth]].<ref name=a/> Its mass is about 330,000 times that of Earth.\n"
           "== References ==\n{{reflist}}\n",
    "Grapefruit": "The '''grapefruit''' is a subtropical [[citrus]] tree.\n"
                  "== Description ==\n"
                  "The fruit is generally an oblate spheroid in shape; it ranges "
                  "in diameter from {{convert|10|to|15|cm|in|abbr=on}}.\n"
                  "== History ==\nThe grapefruit was first documented in 1750.\n",
}


class Client:
    """The factory client's `page(title)` over WIKITEXT; counts what it was
    asked; `fail` titles raise as an unreachable host does."""

    def __init__(self, fail=()):
        self.asked, self.fail = [], set(fail)

    def page(self, title, follow_redirect=True):
        self.asked.append(title)
        if title in self.fail:
            raise OSError("connection refused")
        if title not in WIKITEXT:
            return None
        return {"title": title, "url": f"https://en.wikipedia.org/wiki/{title}",
                "revision_id": 100 + len(title), "revised_at": "2026-10-01T00:00:00Z",
                "wikitext": WIKITEXT[title]}


def _policy(verdict, host):
    return {"verdict": verdict, "checked_on": "2026-10-10",
            "checks": [{"robots_url": f"https://{host}/robots.txt", "path": "/",
                        "status": 200, "any_agent": True, "anthropic_blocked": [],
                        "ai_agents_blocked": [], "verdict": verdict}]}


SOURCES = {   # a minimal list in the shape of channels/<id>/fact-sources.json
    "tiers": {
        "1": [{"id": "nasa", "hosts": ["nasa.gov"], "use": "cite_only",
               "ai_policy": _policy("allowed", "nasa.gov")}],
        "2": [{"id": "wikipedia", "hosts": ["wikipedia.org", "api.wikimedia.org"],
               "use": "read_text", "ai_policy": _policy("allowed", "en.wikipedia.org")}],
    },
    "do_not_take": [],
}

TOPIC = {
    "topic_id": "proxima", "support_check": {"state": "ok"},
    "support_text": [{
        "id": "wikipedia:Proxima_Centauri", "kind": "work_article", "source": "wikipedia",
        "title": "Proxima Centauri", "url": PROXIMA_URL, "revision_id": 333,
        "revised_at": "2026-10-02T00:00:00Z",
        "text": "Proxima Centauri is a small red dwarf star. It is 4.24 light-years away "
                "from the Sun, the closest star to the Sun."}],
}
SUN_QUOTE = "Its diameter is about 1,391,400 km"
FRUIT_QUOTE = "it ranges in diameter from 10 to 15 cm"
CLAIM_TEXT = "Proxima is another grapefruit about two thousand eight hundred kilometres away"
SCRIPT = {
    "script_id": "sci-proxima-001", "topic_id": "proxima",
    "pattern": {"pattern_id": "scale", "rhythm_id": "hold"},
    "hook": "Shrink the Sun to a grapefruit, and the nearest star is still past Moscow.",
    "commentary": "Proxima Centauri is 4.24 light-years away. Make the Sun a grapefruit on a "
                  "London street, and " + CLAIM_TEXT + " - past Moscow.",
    "payoff": "And that is the nearest one.",
    "fact": {"text": "Proxima Centauri is 4.24 light-years away from the Sun.",
             "kind": "measurement", "source": "Wikipedia", "url": PROXIMA_URL,
             "quote": "It is 4.24 light-years away from the Sun"},
    "scale": {
        "quantity": {"value": 4.24, "unit": "light-year", "quote": "4.24 light-years away"},
        "reference": {"value": 1391400, "unit": "km", "source_url": SUN_URL,
                      "quote": SUN_QUOTE},
        "familiar": {"object": "grapefruit", "value": 10, "unit": "cm",
                     "source_url": FRUIT_URL, "quote": FRUIT_QUOTE},
        "result": {"value": 2800, "unit": "km",
                   "said_as": "about two thousand eight hundred kilometres"},
    },
    "claims": [{
        "claim_id": "proxima-past-moscow", "where": "commentary", "text": CLAIM_TEXT,
        "support": [
            {"source": "wikipedia:Proxima_Centauri",
             "quote": "It is 4.24 light-years away from the Sun"},
            {"source": "scale:wikipedia:Sun", "quote": SUN_QUOTE},
            {"source": "scale:wikipedia:Grapefruit", "quote": FRUIT_QUOTE},
        ]}],
}

# The claim judge's model, canned: the reader lists the comparison, the judge
# says it follows from its three quotes (test_check_claims.py's stand-in).
FAKE = r'''
import json, sys
req, out, canned = sys.argv[1:4]
r = json.load(open(req)); c = json.load(open(canned))
if r["kind"] == "extract":
    texts = r["payload"]["texts"]
    a = {"claims": [e for e in c["extract"] if e["where"] in texts
                    and e["text"].lower() in texts[e["where"]].lower()]}
else:
    a = {"verdict": c["entail"].get(r["payload"]["claim"], "not_enough"), "reason": "canned"}
json.dump(a, open(out, "w"))
'''

ARGS = ["--topic", "proxima",
        "--reference", SUN_URL, "1391400", "km", "--reference-name", "the Sun's diameter",
        "--familiar", FRUIT_URL, "10", "cm", "--familiar-name", "grapefruit"]


def bench(name):
    d = _TMP / name
    d.mkdir(parents=True)
    (d / "01-trend-hunter.json").write_text(json.dumps({"topics": [TOPIC]}))
    (d / "03-content-researcher.json").write_text(
        json.dumps({"scripts": [copy.deepcopy(SCRIPT)], "skipped": []}))
    return d


def run_step(batch, args=ARGS, client=None):
    lines = []
    code = step.main([str(batch)] + list(args), sources=SOURCES, client=client or Client(),
                     out=lines.append)
    return code, "\n".join(lines)


def claim_codes(batch):
    [(_, report)] = SS.claims.check_batch_file(batch / "03-content-researcher.json")
    return [v["code"] for v in report["violations"]]


def run_check_claims(batch):
    (batch / "fake.py").write_text(FAKE)
    canned = batch / "canned.json"
    canned.write_text(json.dumps({"extract": [{"where": "commentary", "text": CLAIM_TEXT}],
                                  "entail": {CLAIM_TEXT: "follows"}}))
    cmd = f"{sys.executable} {batch / 'fake.py'} {{request}} {{answer}} {canned}"
    lines = []
    res = cc.check_batch(batch / "03-content-researcher.json", root=ROOT, write=True,
                         out=lines.append, judge=JUDGE, answer_cmd=cmd)
    return res, "\n".join(lines)


def run_check_scale(batch):
    lines = []
    res = cs.check_batch(batch / "03-content-researcher.json", root=ROOT, write=True,
                         out=lines.append, rule=RULE)
    return res, "\n".join(lines)


# ------------------------------------------------------------------ tests
def test_without_the_step_the_sun_and_the_grapefruit_have_no_footing():
    """The defect: the claim rule loses both stand-ins."""
    codes = claim_codes(bench("before"))
    assert codes.count(SS.claims.FAIL_SOURCE_UNKNOWN) == 2, codes


def test_the_step_finds_the_stand_ins_and_both_gates_pass():
    batch = bench("proxima")
    client = Client()
    code, text = run_step(batch, client=client)
    assert code == step.EXIT_OK, text
    assert client.asked == ["Sun", "Grapefruit"], client.asked
    assert "piece_id: scale:wikipedia:Sun" in text and \
        "piece_id: scale:wikipedia:Grapefruit" in text, text
    # the passage the quote is copied from is shown, numbers unwrapped
    assert "| " + SUN_QUOTE in text and "from 10 to 15 cm" in text, text
    data = json.loads((batch / SS.CONTINUATION_FILE).read_text())
    pieces = data["topics"]["proxima"]["support_text"]
    assert [p["id"] for p in pieces] == ["scale:wikipedia:Sun", "scale:wikipedia:Grapefruit"]
    assert [r["state"] for r in data["topics"]["proxima"]["requests"]] == ["ok", "ok"]
    # the 01 is never rewritten
    assert len(json.loads((batch / "01-trend-hunter.json").read_text())
               ["topics"][0]["support_text"]) == 1
    assert claim_codes(batch) == []
    (problems, records, refused), text = run_check_claims(batch)
    assert not problems and not refused, text
    assert records["sci-proxima-001"]["action"] == "pass", records
    (problems, records, refused), text = run_check_scale(batch)
    assert not problems and not refused, text
    assert records["sci-proxima-001"]["action"] == "pass", records


def test_a_number_the_page_does_not_write_exits_1_and_asks_for_another_stand_in():
    batch = bench("not-on-page")
    # the page gives «from 10 to 15 cm»: 12 cm sits inside the range but is
    # not written there
    args = [a if a != "10" else "12" for a in ARGS]
    code, text = run_step(batch, args=args)
    assert code == step.EXIT_UNCONFIRMED, text
    assert "NOT_ON_PAGE" in text and "change the stand-in" in text, text
    assert "never the number" in text, text
    data = json.loads((batch / SS.CONTINUATION_FILE).read_text())
    entry = data["topics"]["proxima"]
    assert [r["state"] for r in entry["requests"]] == ["ok", "not_on_page"]
    assert [p["id"] for p in entry["support_text"]] == ["scale:wikipedia:Sun"]


def test_a_closed_outlet_and_an_unreachable_page_are_not_confirmed():
    batch = bench("closed")
    args = ["--topic", "proxima", "--reference", NASA_URL, "1391400", "km",
            "--familiar", FRUIT_URL, "10", "cm"]
    client = Client(fail={"Grapefruit"})
    code, text = run_step(batch, args=args, client=client)
    assert code == step.EXIT_UNCONFIRMED, text
    assert "CLOSED" in text and "cite_only" in text and "UNREACHABLE" in text, text
    assert client.asked == ["Grapefruit"], client.asked     # the closed page is never read


def test_requests_file_and_quote():
    batch = bench("requests-file")
    reqs = [{"part": "reference", "name": "Sun", "source_url": SUN_URL, "value": 1391400,
             "unit": "km", "quote": SUN_QUOTE}]
    f = batch / "requests.json"
    f.write_text(json.dumps(reqs))
    code, text = run_step(batch, args=["--topic", "proxima", "--requests", str(f)])
    assert code == step.EXIT_OK, text


def test_the_question_that_cannot_be_put_is_exit_3():
    batch = bench("no-topic")
    code, _ = run_step(batch, args=["--topic", "nope"] + ARGS[2:])
    assert code == step.EXIT_CANNOT_ANSWER
    assert not (batch / SS.CONTINUATION_FILE).exists()


def test_the_skill_and_the_scale_gate_name_the_step():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    assert "scripts/scale_support_step.py" in skill and "01-scale-support.json" in skill
    assert "piece_id" in skill and "not_on_page" in skill
    fix = cs.FIXES[cs.CLAIM_NUMBER_UNQUOTED]
    assert "01-scale-support.json" in fix and "scale_support_step.py" in fix
    assert step.HINTS.keys() >= set(SS.STATES)


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:            # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

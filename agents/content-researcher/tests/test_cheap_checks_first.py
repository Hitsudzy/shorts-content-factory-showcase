#!/usr/bin/env python3
"""CF-0827: the free checks of step 6 come before the paid claim judge.

ExampleTech 04-20.10: two topics of `2026-10-20T1448Z` (Rivian, Spotify) were
lost to `source_host_unlisted` - a host check that is arithmetic over the file
and the channel config - after the claim judge (`check_claims.py` -> the root's
`shared/factrule/claim_judge.py`, a model call per claim) had already been paid
for them. Pinned here:

  * a topic `check_source_hosts.py --write` refused is not in `scripts[]` any
    more, so the judge is never asked about it;
  * a script whose topic already stands in `skipped[]` (a gate run without
    `--write`, a script written back by hand) is skipped by `check_claims.py`
    itself - `SKIPPED`, nothing asked, nothing written;
  * the skill runs the host check before the claims judge.

Offline: the judge's answer command is a stand-in written here that logs every
request it is handed; no network, no model. The channel config is a stand-in
in a temp root.
"""
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import check_claims as cc  # noqa: E402
import check_source_hosts as csh  # noqa: E402

ROOT = cc.find_root()
JUDGE = cc.load_judge(ROOT)
_TMP = tmp_root("cr-cheap-first-")
SKILL = HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md"
CHANNEL = "test-channel"
CFG = {"video_editor": {"comparison_line": {
    "publishers": {"stroudtimes.com": "Stroud Times"}, "platforms": []}}}

SUMMARY = {"t1": "Kerry killed Hal to protect Noah.", "t2": "Zorblax ships the R3 in March."}


def _topic(tid):
    return {"topic_id": tid, "support_check": {"state": "ok"}, "support_text": [
        {"id": f"wikipedia:{tid}#e1", "kind": "episode_summary", "title": tid,
         "url": "https://stroudtimes.com/a", "revision_id": 1,
         "revised_at": "2026-10-05T00:00:00Z", "text": SUMMARY[tid]}]}


def _script(sid, tid, line, url):
    q = {"source": f"wikipedia:{tid}#e1", "quote": line}
    return {"script_id": sid, "topic_id": tid, "hook": line + ".", "commentary": "",
            "payoff": "", "production_fact": {"beat_text": line, "on_screen": line,
                                              "text": line, "source_url": url},
            "claims": [{"claim_id": "c1", "where": "hook", "text": line, "support": [q]}]}


LISTED = _script("s1", "t1", "Kerry killed Hal to protect Noah", "https://stroudtimes.com/a")
UNLISTED = _script("s2", "t2", "Zorblax ships the R3 in March",
                   "https://en.wikipedia.org/wiki/Rivian")

# Answers every request "follows" and appends the request's payload to a log,
# so the test can see which texts the judge was handed.
FAKE = r'''
import json, sys
req, out, log = sys.argv[1:4]
r = json.load(open(req))
with open(log, "a") as fh:
    fh.write(json.dumps(r["payload"]) + "\n")
if r["kind"] == "extract":
    texts = r["payload"]["texts"]
    a = {"claims": [{"where": w, "text": t.rstrip(".")} for w, t in texts.items()
                    if w == "hook" and t]}
else:
    a = {"verdict": "follows", "reason": "canned", "reveal": False}
json.dump(a, open(out, "w"))
'''


def bench(name, scripts, skipped=()):
    d = _TMP / name
    (d / "channels").mkdir(parents=True, exist_ok=True)
    (d / "channels" / f"{CHANNEL}.json").write_text(json.dumps(CFG))
    (d / "fake.py").write_text(FAKE)
    log = d / "asked.log"
    (d / "01-trend-hunter.json").write_text(json.dumps(
        {"topics": [_topic("t1"), _topic("t2")]}))
    batch = d / "03-content-researcher.json"
    batch.write_text(json.dumps({"batch_id": "b", "channel": CHANNEL, "warnings": [],
                                 "scripts": copy.deepcopy(list(scripts)),
                                 "skipped": list(skipped)}))
    cmd = f"{sys.executable} {d / 'fake.py'} {{request}} {{answer}} {log}"
    return d, batch, cmd, log


def claims(batch, cmd):
    lines = []
    res = cc.check_batch(batch, root=ROOT, write=True, out=lines.append, judge=JUDGE,
                         answer_cmd=cmd, terms={})
    return res, "\n".join(lines), json.loads(batch.read_text())


def asked(log):
    return log.read_text() if log.exists() else ""


def test_a_topic_refused_by_host_never_reaches_the_judge():
    d, batch, cmd, log = bench("hosts-then-claims", [LISTED, UNLISTED])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = csh.main([str(batch), "--root", str(d), "--write"])
    assert code == csh.EXIT_UNLISTED, buf.getvalue()
    data = json.loads(batch.read_text())
    assert [s["script_id"] for s in data["scripts"]] == ["s1"], data
    assert [(e["topic_id"], e["reason_code"]) for e in data["skipped"]] == \
        [("t2", "source_host_unlisted")]
    (problems, records, refused), text, data = claims(batch, cmd)
    assert not problems and not refused and set(records) == {"s1"}, text
    log_text = asked(log)
    assert "Kerry" in log_text, "the judge was never asked about the listed topic"
    assert "Zorblax" not in log_text, "the refused topic reached the paid judge"


def test_a_script_whose_topic_already_stands_in_skipped_is_not_judged():
    gone = {"topic_id": "t2", "reason_code": "source_host_unlisted", "stage": "scripts",
            "reason": "stand-in"}
    d, batch, cmd, log = bench("guard", [LISTED, UNLISTED], skipped=[gone])
    (problems, records, refused), text, data = claims(batch, cmd)
    assert "SKIPPED   s2" in text and "source_host_unlisted" in text, text
    assert set(records) == {"s1"} and not refused and not problems, text
    assert "Zorblax" not in asked(log)
    s2 = [s for s in data["scripts"] if s["script_id"] == "s2"][0]
    assert cc.RECORD_KEY not in s2, "nothing is written for a skipped topic"
    assert data["skipped"] == [gone], "the skipped entry is left as it was"


def test_skipped_topics_reads_only_the_scripts_stage():
    data = {"skipped": [{"topic_id": "a", "reason_code": "x", "stage": "scripts"},
                        {"topic_id": "b", "reason_code": "y", "stage": "render"},
                        {"topic_id": "c", "reason_code": "z"}, "junk", {}]}
    assert cc.skipped_topics(data) == {"a": "x", "c": "z"}


def _step6():
    text = SKILL.read_text()
    start = text.index("\n6. **Hold the batch")
    return text[start:text.index("\n6b. **", start)]


def test_the_skill_runs_the_host_check_before_the_claims_judge():
    step6 = _step6()
    hosts = step6.index("scripts/check_source_hosts.py \\")
    judge = step6.index("scripts/check_claims.py \\")
    assert hosts < judge, "check_source_hosts.py must run before check_claims.py (CF-0827)"
    assert "CF-0827" in step6


def test_the_step_table_lists_the_host_check_before_the_claims_check():
    text = SKILL.read_text()
    table = text[text.index("| script | step |"):text.index("Step 2's refusal run")]
    assert table.index("`check_source_hosts.py`") < table.index("`check_claims.py`")


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

#!/usr/bin/env python3
"""CF-0882: the compliance half of the refill from below the shortlist
(`scripts/judge_below_shortlist.py judge|admit`), and the cut keeping the
admitted rows out of its ranking.

Pinned here, on synthetic batches in a temp factory root:

* `judge` refuses a topic on the machine screen (a forbidden topic), passes a clean one at `clear` and a soft flag at
  `caution`, does not mistake a show's own name for its subject, refuses a
  topic that is not below the shortlist; refusals land once in
  `02 -> refill_refused[]`, `results[]`/`reserve[]` are not touched, and the
  root's queue never offers a refused topic again;
* `admit` writes one `reserve[]` row per topic Trend Hunter gave a pool, with
  the `refill` mark, `reserve_unused` and a reason - once; a topic with no
  pool, or one the shortlist pass judged, is skipped; the `cut` record counts
  the rows (the root's contract), the ledger written is the temp root's;
* `cut_shortlist` over a file with refill rows neither ranks them nor carries
  them into `results[]`, even when the cut has free slots;
* the root's own seam (`shared/below_shortlist.py`: `call_seam` and a whole
  `promote` round) runs this script as a child process and gets what it
  expects - Trend Hunter's half stood in, no network.

No pytest dependency - plain asserts, dual-mode.
"""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE.parent
SCRIPTS = AGENT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import _runlog  # noqa: E402
import cut_shortlist  # noqa: E402
import judge_below_shortlist as jbs  # noqa: E402

TMP = tmp_root("judge-below-shortlist-")
FACTORY = _runlog.factory_root()
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)

froot = TMP / "factory"
CHANNEL = "example-film"
(froot / "channels").mkdir(parents=True)
(froot / "channels" / f"{CHANNEL}.json").write_text(json.dumps(
    {"scope": {"max_titles_per_batch": 3, "target_ready_videos_per_batch": 2}}))
_N = [0]


def _topic(tid, name, headline="", scenes=(), holder=None, network=None, kind="work"):
    return {"topic_id": tid,
            "title_ref": {"name": name, "kind": kind, "type": "tv_series",
                          "rights_holder": holder, "network": network, "person": None},
            "evidence": {"sources": [{"url": f"https://example.org/{tid}", "title": headline}]},
            "scenes": [{"scene_id": f"{tid}-s{i + 1}", "description": d, "tags": []}
                       for i, d in enumerate(scenes)]}


BELOW = [
    _topic("b-clean", "Partition", "Partition season 3 adds two cast members"),
    _topic("b-murder", "Dateline Stories", "Network revisits a real murder in a new special"),
    _topic("b-holder", "Peacemaker", "Peacemaker season 3 is a go", holder="Example Studios"),
    _topic("b-soft", "The Studio", "The Studio faces a lawsuit over its pilot script"),
    _topic("b-name", "Only Murders in the Building",
           "Only Murders in the Building renewed for season 6"),
    _topic("b-scene", "Andor", "Andor wins at the Emmys",
           scenes=("The cast thanks the crew.", "A brutal battle scene is shown at the panel.")),
]


def batch(shortlist=("t1", "t2", "t3", "r1"), results=None, reserve=("r1",), refused=("t2",)):
    _N[0] += 1
    b = froot / "pipeline" / CHANNEL / f"2026-10-18T08{_N[0]:02d}Z"
    b.mkdir(parents=True)
    t01 = {"channel": "example-film", "batch_id": b.name,
           "topics": [_topic(t, f"Show {t}", "news") for t in shortlist],
           "skipped_topics": [{"topic_id": t["topic_id"], "reason_code": "below_shortlist",
                               "rank": 9 + i, "title": t["title_ref"]["name"], "topic": t}
                              for i, t in enumerate(BELOW)]
           + [{"topic_id": "n1", "reason_code": "no_fact"}],
           "search_quota": {"substitution_price_searches": 6}}
    (b / "01-trend-hunter.json").write_text(json.dumps(t01))
    results = results or {t: "clear" for t in ("t1", "t2", "t3")}
    c02 = {"batch_id": b.name, "channel": "example-film", "stage_checked": "01-trend-hunter",
           "results": [{"topic_id": t, "verdict": v,
                        "content_sensitivity_check": {"flagged": False, "notes": "n"}}
                       for t, v in results.items()],
           "reserve": [{"topic_id": r, "verdict": "clear", "reason_code": "reserve_unused",
                        "reason": "spare", "content_sensitivity_check": {"flagged": False}}
                       for r in reserve]}
    c02["cut"] = {"judged": len(results) + len(reserve), "eligible": len(results) + len(reserve),
                  "carried": len(results), "reserve": len(reserve), "refused": 0,
                  "target": 3, "shortlist_size": 4}
    (b / "02-compliance-checker.json").write_text(json.dumps(c02))
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"batch_id": b.name,
         "scripts": [{"script_id": f"{t}-script1", "topic_id": t} for t in ("t1", "t3")],
         "skipped": [{"topic_id": t, "reason_code": "no_source"} for t in refused]}))
    (b / "01b-footage-index.json").write_text(json.dumps(
        {"batch": str(b), "sources_by_topic": {t: [] for t in ("t1", "t2", "t3")},
         "reserve_substitution": {"reserve": list(reserve), "remaining": [],
                                  "substitutions": [], "unmatched": []}}))
    return b


def c02(b):
    return json.loads((b / "02-compliance-checker.json").read_text())


def promote_in_01(b, ids):
    """Trend Hunter's half (its spec): the topic back into `topics[]` with its
    candidates and the `refill` mark, the `below_shortlist` row gone."""
    t = json.loads((b / "01-trend-hunter.json").read_text())
    for tid in ids:
        row = next(r for r in t["skipped_topics"] if r["topic_id"] == tid)
        topic = dict(row["topic"], rank=row["rank"], refill={"task": "CF-0882"})
        topic["evidence"] = dict(topic["evidence"], footage_candidates=[{"url": "u"}] * 3)
        t["topics"].append(topic)
        t["skipped_topics"].remove(row)
        t.setdefault("below_shortlist_refill", []).append(
            {"topic_id": tid, "outcome": "candidates", "searches": 6, "at": "now"})
    (b / "01-trend-hunter.json").write_text(json.dumps(t))


def root_module(name):
    path = FACTORY / "shared" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"root_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def check_cut_contract(d):
    """The root's `tests/test_pipeline_contracts.py::check_compliance_cut`,
    the part a refill row can break."""
    rows = d["reserve"]
    carried = {r.get("topic_id") for r in d.get("results") or []}
    for r in rows:
        for k in ("topic_id", "verdict", "reason_code", "reason"):
            assert k in r, (k, r)
        assert r["verdict"] in ("clear", "caution", "review"), r
        assert r["verdict"] != "review" or isinstance(r.get("publication_hold"), dict), r
        assert r["reason_code"] == "reserve_unused", r
        assert r["reason"].strip(), r
        assert r["topic_id"] not in carried, r
    cut = d["cut"]
    assert cut["reserve"] == len(rows), (cut, len(rows))
    assert cut["carried"] + cut["refused"] == len(d["results"]), cut
    assert cut["carried"] <= cut["target"], cut


# --- judge -------------------------------------------------------------------

def test_judge_refuses_on_the_screen_and_passes_the_clean():
    b = batch()
    before = c02(b)
    rows = {r["topic_id"]: r for r in jbs.judge(b, [t["topic_id"] for t in BELOW] + ["t1"])}
    assert rows["b-clean"]["outcome"] == "eligible" and rows["b-clean"]["verdict"] == "clear"
    assert rows["b-murder"]["outcome"] == "refused" and rows["b-murder"]["verdict"] == "review"
    assert "murder" in rows["b-murder"]["reason"], rows["b-murder"]
    assert rows["b-holder"]["outcome"] == "eligible" and rows["b-holder"]["verdict"] == "clear", \
        rows["b-holder"]
    assert rows["b-soft"]["outcome"] == "eligible" and rows["b-soft"]["verdict"] == "caution"
    assert rows["b-name"]["outcome"] == "eligible" and rows["b-name"]["verdict"] == "clear", \
        rows["b-name"]
    assert rows["b-scene"]["verdict"] == "caution", rows["b-scene"]
    assert rows["t1"]["outcome"] == "refused" and "below_shortlist" in rows["t1"]["reason"]
    assert all(r["decided_by"] == jbs.DECIDED_BY for t, r in rows.items() if t != "t1")
    after = c02(b)
    assert after["results"] == before["results"] and after["reserve"] == before["reserve"]
    refused = {r["topic_id"]: r for r in after["refill_refused"]}
    assert set(refused) == {"b-murder"}, refused
    assert refused["b-murder"]["reason_code"] == jbs.SCREEN_CODE
    for r in refused.values():
        assert r["verdict"] and r["reason"], r


def test_judge_twice_refuses_once_and_the_root_queue_drops_the_refused():
    b = batch()
    ids = ["b-murder", "b-clean"]
    jbs.judge(b, ids, "first")
    jbs.judge(b, ids, "late")
    rr = c02(b)["refill_refused"]
    assert [r["topic_id"] for r in rr] == ["b-murder"] and rr[0]["round"] == "first", rr
    bsl = root_module("below_shortlist")
    q = [x["topic_id"] for x in bsl.queue(b)]
    assert "b-murder" not in q and "b-clean" in q, q


def test_the_verdict_record_is_the_pass_shape():
    b = batch()
    ctx = jbs.Context(b)
    row, outcome, _ = jbs.verdict_row(BELOW[5], None, ctx.blacklist)
    assert outcome == "eligible" and row["verdict"] == "caution"
    cs = row["content_sensitivity_check"]
    assert cs["flagged"] is True and cs["scenes"] == ["b-scene-s2"], cs
    assert row["rights_holder_check"]["affects_verdict"] is False
    row, _, _ = jbs.verdict_row(BELOW[3], None, ctx.blacklist)
    assert row["content_sensitivity_check"]["scenes"] == "whole_topic"
    row, _, _ = jbs.verdict_row(BELOW[0], None, ctx.blacklist)
    assert row["content_sensitivity_check"]["flagged"] is False
    assert "scenes" not in row["content_sensitivity_check"]


def test_a_person_topic_is_screened_by_its_person():
    t = _topic("p1", "Donald Trump", "Late-night host jokes about Trump", kind="person")
    hits = jbs.screen(t)
    assert any(h["category"] == "political flashpoint" for h in hits["hard"]), hits
    assert not jbs.screen(_topic("w1", "The Killing", "The Killing gets a reboot"))["hard"]
    assert not jbs.screen(_topic("w2", "X", "Lead was killed off in the finale"))["hard"]


# --- admit -------------------------------------------------------------------

def test_admit_writes_one_marked_row_per_pooled_topic():
    b = batch()
    promote_in_01(b, ["b-clean", "b-soft"])
    rows, changed, channel = jbs.admit(b, ["b-clean", "b-soft", "b-name", "t1", "r1"], "judge")
    assert changed and channel == "example-film"
    by = {r["topic_id"]: r for r in rows}
    assert by["b-clean"]["outcome"] == by["b-soft"]["outcome"] == "admitted", by
    assert by["b-name"]["outcome"] == "skipped" and "no pool" in by["b-name"]["reason"]
    assert by["t1"]["outcome"] == by["r1"]["outcome"] == "skipped"
    d = c02(b)
    assert [r["topic_id"] for r in d["results"]] == ["t1", "t2", "t3"]
    refill = [r for r in d["reserve"] if r.get("refill")]
    assert [r["topic_id"] for r in refill] == ["b-clean", "b-soft"]
    for r in refill:
        assert r["refill"]["task"] == "CF-0882" and r["refill"]["round"] == "judge", r
        assert r["reason_code"] == "reserve_unused" and "rank" in r["reason"], r
        assert r["rights_holder_check"]["affects_verdict"] is False
    assert {r["topic_id"]: r["verdict"] for r in refill} == {"b-clean": "clear", "b-soft": "caution"}
    assert d["cut"]["reserve"] == 3 and d["cut"]["refill"]["admitted"] == 2, d["cut"]
    check_cut_contract(d)
    rows2, changed2, _ = jbs.admit(b, ["b-clean"], "late")
    assert not changed2 and rows2[0]["outcome"] == "skipped" and "already" in rows2[0]["reason"]
    assert len(c02(b)["reserve"]) == 3


def test_admit_cli_runs_the_checks_and_writes_the_temp_ledger():
    b = batch()
    promote_in_01(b, ["b-scene"])
    res = TMP / "admit-result.json"
    code = jbs.main(["admit", str(b), "--topics", "b-scene", "--round", "first",
                     "--result", str(res)])
    assert code == 0
    doc = json.loads(res.read_text())
    assert doc["topics"][0]["outcome"] == "admitted", doc
    assert (froot / "publish" / "publication-holds.json").is_file()


# --- the cut -----------------------------------------------------------------

def test_the_cut_does_not_rank_a_refill_row_even_with_a_free_slot():
    b = batch(results={"t1": "clear", "t2": "reject", "t3": "clear"}, reserve=())
    promote_in_01(b, ["b-clean"])
    jbs.admit(b, ["b-clean"], "first")
    d = c02(b)
    assert cut_shortlist.judged_results(d) and all(
        not r.get("refill") for r in cut_shortlist.judged_results(d))
    stage = json.loads((b / "01-trend-hunter.json").read_text())
    new, carried, reserved = cut_shortlist.cut_document(d, stage, 3, "test")
    assert "b-clean" not in carried and "b-clean" not in reserved, (carried, reserved)
    assert [r["topic_id"] for r in new["reserve"]] == ["b-clean"]
    assert new["reserve"][0] == d["reserve"][0]
    assert new["cut"]["refill"]["admitted"] == 1 and new["cut"]["reserve"] == 1
    check_cut_contract(new)


# --- the root's seam ---------------------------------------------------------

def test_the_root_seam_runs_this_script():
    bsl = root_module("below_shortlist")
    b = batch()
    rows, err = bsl.call_seam("judge", AGENT, sys.executable, bsl.CC_ENTRY,
                              ["judge", str(b), "--topics", "b-murder,b-clean"],
                              b / bsl.JUDGED_FILE)
    assert err is None, err
    assert {r["topic_id"]: r["outcome"] for r in rows} == {"b-murder": "refused",
                                                           "b-clean": "eligible"}


def test_a_whole_promote_round_through_the_real_compliance_half():
    bsl = root_module("below_shortlist")
    b = batch(reserve=())

    def runner(argv, timeout):
        if argv[1].endswith(bsl.TH_ENTRY):            # Trend Hunter's half, stood in
            ids = argv[argv.index("--topics") + 1].split(",")
            promote_in_01(b, ids)
            Path(argv[argv.index("--result") + 1]).write_text(json.dumps(
                {"topics": [{"topic_id": t, "outcome": "candidates", "searches": 6}
                            for t in ids]}))
            return 0
        return subprocess.run(argv, timeout=timeout, capture_output=True).returncode

    th = TMP / "th-stand-in"
    (th / "scripts").mkdir(parents=True, exist_ok=True)
    (th / bsl.TH_ENTRY).write_text("# stand-in\n")
    rec = bsl.promote(b, "first", AGENT, sys.executable, th, None, root=froot,
                      now=datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc),
                      base={"limit": 100, "margin": 5, "max_batches": 2, "batches": 1,
                            "spent": 40},
                      hold=(0, "none"), runner=runner, out=lambda *_a: None)
    assert rec["outcome"] == "admitted", rec
    assert rec["admitted"] == ["b-clean"], rec
    assert {r["topic_id"]: r["outcome"] for r in rec["judged"]}["b-murder"] == "refused"
    d = c02(b)
    check_cut_contract(d)
    assert [r["topic_id"] for r in bsl.refill_rows(d)] == ["b-clean"]


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

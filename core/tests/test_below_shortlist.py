#!/usr/bin/env python3
"""CF-0882: the refill from below the shortlist (`shared/below_shortlist.py`).

Synthetic batches in a temp factory root; the agents' seams are stand-in
scripts driven through `runner` (no subprocess, no network), the quota ledger
and the schedule are stood in:

* the queue - unspent `below_shortlist` topics of 01 by rank, nothing the
  batch already used (topics[], 02, 01b pools, footage_substitution, a round);
* the price - 01's `substitution_price_searches`, else the facet run's 6;
* the budget - spend + price + margin within 100, the day's second batch held
  back when CF-0830 would still admit it, an earlier round's spend counted;
* the need of a round (N - M) and the named conditions (one pass per round);
* the round - compliance judges, Trend Hunter walks what the day pays for,
  compliance admits what got a pool; `_remaining_reserve` then sees the
  admitted rows and `reserve_refill` holds again; a missing seam, a quota day
  that cannot pay, a refusal - recorded, never an exception;
* the retro replay of a finished batch.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))
from _tmproot import tmp_root  # noqa: E402
import below_shortlist as bsl  # noqa: E402
import run_checks  # noqa: E402
import run_plan  # noqa: E402

TMP = tmp_root("below-shortlist-test-")
(TMP / "channels").mkdir()
(TMP / "channels" / "example-film.json").write_text(json.dumps(
    {"scope": {"max_titles_per_batch": 3, "target_ready_videos_per_batch": 2}}))
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
_N = [0]
CC = TMP / "agents" / "compliance-checker"
TH = TMP / "agents" / "trend-hunter"
for d, e in ((CC, bsl.CC_ENTRY), (TH, bsl.TH_ENTRY)):
    (d / e).parent.mkdir(parents=True, exist_ok=True)
    (d / e).write_text("# stand-in: the tests drive the seam through `runner`\n")


def base(spent=40, batches=1):
    return {"limit": 100, "margin": 5, "max_batches": 2, "batches": batches, "spent": spent}


NO_HOLD = (0, "no second batch")


def batch(below=("b1", "b2", "b3"), refused=("t2",), remaining=(), subs=(), price=None,
          reserve=("r1",), gates=None):
    _N[0] += 1
    b = TMP / "pipeline" / "example-film" / f"2026-10-18T08{_N[0]:02d}Z"
    b.mkdir(parents=True)
    t01 = {"topics": [{"topic_id": t} for t in ("t1", "t2", "t3", "r1")],
           "skipped_topics": [{"topic_id": x, "reason_code": "below_shortlist", "rank": 9 + i,
                               "title": x.upper()} for i, x in enumerate(below)]
           + [{"topic_id": "n1", "reason_code": "no_fact"}],
           "search_quota": ({"substitution_price_searches": price} if price else {})}
    (b / "01-trend-hunter.json").write_text(json.dumps(t01))
    (b / "02-compliance-checker.json").write_text(json.dumps(
        {"results": [{"topic_id": t, "verdict": "clear"} for t in ("t1", "t2", "t3")],
         "reserve": [{"topic_id": r, "verdict": "clear", "reason_code": "reserve_unused"}
                     for r in reserve]}))
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"scripts": [{"script_id": f"{t}-script1", "topic_id": t} for t in ("t1", "t3")],
         "skipped": [{"topic_id": t, "reason_code": "no_source"} for t in refused]}))
    (b / "01b-footage-index.json").write_text(json.dumps(
        {"batch": str(b), "sources_by_topic": {t: [] for t in ("t1", "t2", "t3")},
         "reserve_substitution": {"reserve": list(reserve), "remaining": list(remaining),
                                  "substitutions": list(subs), "unmatched": []}}))
    if gates is not None:
        (b / "06-frame-judge.json").write_text(json.dumps(
            {"videos": [{"script_id": f"{t}-script1", "slug": t,
                         "gate": "pass" if g == "pass" else "reject",
                         "reason_code": None if g == "pass" else g} for t, g in gates.items()]}))
    return b


class Seams:
    """The agents' halves, by the task file's specs."""

    def __init__(self, b, verdicts=None, pools=None, searches=6, admit=True):
        self.b, self.calls = b, []
        self.verdicts = verdicts or {}
        self.pools = pools or {}
        self.searches, self.admit = searches, admit

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        res = Path(argv[argv.index("--result") + 1])
        ids = argv[argv.index("--topics") + 1].split(",")
        if argv[1].endswith(bsl.TH_ENTRY):
            rows = [{"topic_id": t, "outcome": self.pools.get(t, "candidates"),
                     "searches": self.searches} for t in ids]
            # the agent's run log, as trend-hunter writes it: no `round`
            f = self.b / "01-trend-hunter.json"
            t01 = json.loads(f.read_text())
            t01.setdefault("below_shortlist_refill", []).extend(
                dict(r, at="2026-10-28T10:43:33Z", task="CF-0882") for r in rows)
            f.write_text(json.dumps(t01))
        elif argv[2] == "judge":
            rows = [{"topic_id": t, "verdict": self.verdicts.get(t, "clear"),
                     "outcome": "eligible" if self.verdicts.get(t, "clear") != "blocked"
                     else "refused", "reason": "stand-in"} for t in ids]
        else:
            rows = [{"topic_id": t, "outcome": "admitted"} for t in ids]
            if self.admit:
                f = self.b / "02-compliance-checker.json"
                c = json.loads(f.read_text())
                c["reserve"] += [{"topic_id": t, "verdict": "clear", "reason_code": "reserve_unused",
                                  "refill": {"task": "CF-0882", "round": argv[-3]}} for t in ids]
                f.write_text(json.dumps(c))
        res.write_text(json.dumps({"topics": rows}))
        return 0


def promote(b, rnd="first", seams=None, **kw):
    kw.setdefault("base", base())
    kw.setdefault("hold", NO_HOLD)
    return bsl.promote(b, rnd, CC, None, TH, None, root=TMP, now=NOW,
                       runner=seams or Seams(b), out=lambda *_a: None, **kw)


# --- the queue and the price -------------------------------------------------

def test_queue_is_the_unspent_below_shortlist_by_rank():
    b = batch(below=("b1", "b2", "b3", "t1"))
    t = json.loads((b / "01-trend-hunter.json").read_text())
    t["skipped_topics"][0]["rank"] = 20                 # b1 ranked last
    t["footage_substitution"] = {"substitutions": [{"topic_id": "b2", "replaced": "x"}]}
    (b / "01-trend-hunter.json").write_text(json.dumps(t))
    assert [x["topic_id"] for x in bsl.queue(b)] == ["b3", "b1"]


def test_price_from_01_else_the_facet_run():
    assert bsl.price(batch(price=5))[0] == 5
    assert bsl.price(batch())[0] == bsl.FACET_RUN_SEARCHES == 6


# --- the budget --------------------------------------------------------------

def test_budget_spend_price_margin_within_the_day():
    b = batch()
    x = bsl.budget(b, root=TMP, now=NOW, base=base(spent=70), hold=NO_HOLD)
    assert x["room"] == 25 and x["affordable"] == 4, x
    x = bsl.budget(b, root=TMP, now=NOW, base=base(spent=92), hold=NO_HOLD)
    assert x["affordable"] == 0 and x["spent"] + x["margin"] <= 100 + 0 * x["room"], x


def test_budget_holds_back_the_days_second_batch():
    b = batch()
    x = bsl.budget(b, root=TMP, now=NOW, base=base(spent=30), hold=(58, "Reel 2nd"))
    assert x["room"] == 100 - 5 - 30 - 58 and x["affordable"] == 1, x
    assert "придержано 58" in x["line"], x["line"]


def test_budget_counts_an_earlier_rounds_spend_the_ledger_has_not_caught():
    b = batch()
    (b / "work").mkdir()
    (b / bsl.RECORD_FILE).write_text(json.dumps(
        {"rounds": [{"round": "first", "spent_after": 80}]}))
    x = bsl.budget(b, root=TMP, now=NOW, base=base(spent=60), hold=NO_HOLD)
    assert x["spent"] == 80 and x["affordable"] == 2, x


def test_second_batch_hold_only_when_cf0830_would_admit_it():
    later = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
    kw = dict(expected_of=lambda ch: 58, windows_of=lambda ch: [later],
              switch_on=lambda r: True, channels=["example-film"])
    held, why = bsl.second_batch_hold(TMP, NOW, base(spent=30), **kw)
    assert held == 58 and "example-film" in why, why
    held, why = bsl.second_batch_hold(TMP, NOW, base(spent=45), **kw)     # 45+58 > 95
    assert held == 0 and "admissible" in why, why
    held, why = bsl.second_batch_hold(TMP, NOW, base(spent=30, batches=2), **kw)
    assert held == 0 and "already has 2 of 2" in why, why
    held, _ = bsl.second_batch_hold(TMP, NOW, base(spent=30), **dict(kw, switch_on=lambda r: False))
    assert held == 0
    nextday = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)          # after 07:00Z
    held, _ = bsl.second_batch_hold(TMP, NOW, base(spent=30),
                                    **dict(kw, windows_of=lambda ch: [nextday]))
    assert held == 0


# --- the need and the conditions --------------------------------------------

def test_need_is_n_less_m_and_the_condition_holds_once_per_round():
    b = batch(refused=("t2", "t3"), remaining=("r1",))
    k, why = bsl.need(b, "first")
    assert k == 1 and "N=2" in why and "M=1" in why, why
    holds, why = run_checks.check("below_shortlist_refill", b, root=TMP)
    assert holds, why
    promote(b)
    holds, why = run_checks.check("below_shortlist_refill", b, root=TMP)
    assert not holds and "one pass per round" in why, why
    # the admitted topic is reserve now: the late round needs nothing (M=2)
    holds, why = run_checks.check("below_shortlist_refill_late", b, root=TMP)
    assert not holds and "M=2" in why and "admitted from below the shortlist" in why, why


def test_no_need_when_the_reserve_covers_the_refusals():
    b = batch(refused=("t2",), remaining=("r1",))
    holds, why = bsl.check(b, "first")
    assert not holds and "nothing to refill" in why, why


def test_a_rerun_or_rebuild_whose_01b_is_its_parents_needs_nothing():
    b = batch(refused=("t2",), remaining=())
    ix = json.loads((b / "01b-footage-index.json").read_text())
    ix["batch"] = "pipeline/example-film/2026-10-01T0800Z"
    (b / "01b-footage-index.json").write_text(json.dumps(ix))
    k, why = bsl.need(b, "first")
    assert k == 0 and "another batch's" in why, why


def test_no_queue_no_round():
    b = batch(below=())
    holds, why = bsl.check(b, "first")
    assert not holds and "no unspent below_shortlist" in why, why


def test_judge_round_need_reads_reserve_after_judge_without_the_reserve_clause():
    b = batch(refused=(), gates={"t1": "pass", "t3": "judge_footage_defect"})
    k, why = bsl.need(b, "judge", root=TMP, now=NOW,
                      next_batch=lambda r, n: (None, "no batch planned"))
    assert k == 1 and "M=0" in why, why
    holds, _ = run_checks.reserve_after_judge(b, root=TMP, now=NOW,
                                              next_batch=lambda r, n: (None, "-"))
    assert not holds                                      # the reserve is empty


def test_the_plan_knows_the_conditions():
    for name in ("below_shortlist_refill", "below_shortlist_refill_late",
                 "below_shortlist_refill_judge"):
        assert name in run_plan.CONDITIONS and name in run_checks.CHECKS


# --- the round ---------------------------------------------------------------

def test_round_admits_and_the_reserve_round_sees_the_admitted():
    b = batch(refused=("t2",), remaining=())
    holds, _ = run_checks.reserve_refill(b)
    assert not holds                                       # M=0 before
    s = Seams(b, verdicts={"b1": "blocked"})
    rec = promote(b, seams=s)
    assert rec["outcome"] == "admitted" and rec["admitted"] == ["b2"], rec
    assert [j["outcome"] for j in rec["judged"]] == ["refused", "eligible", "eligible"], rec
    assert rec["searches"] == 6 and rec["spent_after"] == 46, rec
    th = [c for c in s.calls if c[1].endswith(bsl.TH_ENTRY)][0]
    assert th[th.index("--max-searches") + 1] == "6", th
    holds, why = run_checks.reserve_refill(b)
    assert holds and "b2" in why and "below the shortlist" in why, why
    # the round is on record and not run twice
    again = promote(b, seams=Seams(b))
    assert again["at"] == rec["at"]
    assert len(json.loads((b / bsl.RECORD_FILE).read_text())["rounds"]) == 1
    # an answered refill topic is no longer reserve
    ix = json.loads((b / "01b-footage-index.json").read_text())
    ix["reserve_substitution"]["substitutions"].append({"topic_id": "b2", "replaced": "t2"})
    (b / "01b-footage-index.json").write_text(json.dumps(ix))
    holds, _ = run_checks.reserve_refill(b)
    assert not holds
    assert "b2" not in [x["topic_id"] for x in bsl.queue(b)]


def test_the_root_puts_the_round_on_what_the_agents_wrote_for_it():
    """CF-0888: compliance is told the round; Trend Hunter's rows in
    `01 -> below_shortlist_refill[]` get it from the root."""
    b = batch(refused=("t2",), remaining=())
    s = Seams(b, verdicts={"b1": "blocked"})
    rec = promote(b, rnd="late", seams=s)
    assert rec["outcome"] == "admitted", rec
    judge = [c for c in s.calls if len(c) > 2 and c[2] == "judge"][0]
    assert judge[judge.index("--round") + 1] == "late", judge
    th = [c for c in s.calls if c[1].endswith(bsl.TH_ENTRY)][0]
    assert "--round" not in th, th          # the agent's seam takes none
    rows = json.loads((b / "01-trend-hunter.json").read_text())["below_shortlist_refill"]
    assert [(r["topic_id"], r["round"]) for r in rows] == [("b2", "late")], rows


def test_stamp_round_keeps_an_agents_own_round_and_other_topics():
    b = batch()
    f = b / "01-trend-hunter.json"
    t01 = json.loads(f.read_text())
    t01["below_shortlist_refill"] = [{"topic_id": "b1", "outcome": "candidates", "round": "first"},
                                     {"topic_id": "b2", "outcome": "candidates"},
                                     {"topic_id": "b3", "outcome": "refused"}]
    f.write_text(json.dumps(t01))
    assert bsl.stamp_round(b, "judge", ["b1", "b2"]) == ["b2"]
    rows = json.loads(f.read_text())["below_shortlist_refill"]
    assert [r.get("round") for r in rows] == ["first", "judge", None]
    assert bsl.stamp_round(b, "judge", ["b2"]) == []          # once
    assert bsl.stamp_round(TMP / "no-such-batch", "first", ["b1"]) == []


def test_round_the_day_does_not_pay_no_seam_called():
    b = batch(refused=("t2",), remaining=())
    s = Seams(b)
    rec = promote(b, seams=s, base=base(spent=90))
    assert rec["outcome"] == "search_quota" and not s.calls, rec


def test_round_takes_no_more_than_the_day_pays():
    b = batch(refused=("t2", "t3"), remaining=())
    s = Seams(b)
    rec = promote(b, seams=s, base=base(spent=84))        # room 11 -> one at 6
    assert rec["need"] == 2 and rec["admitted"] == ["b1"], rec


def test_round_with_no_agent_half_is_recorded_not_raised():
    b = batch(refused=("t2",), remaining=())
    rec = bsl.promote(b, "first", TMP / "nowhere", None, TH, None, root=TMP, now=NOW,
                      base=base(), hold=NO_HOLD, out=lambda *_a: None)
    assert rec["outcome"] == "seam_failed" and "has no" in rec["why"], rec
    holds, _ = run_checks.reserve_refill(b)
    assert not holds


def test_round_thin_pool_is_no_pool():
    b = batch(refused=("t2",), remaining=())
    rec = promote(b, seams=Seams(b, pools={"b1": "refused"}))
    assert rec["outcome"] == "no_pool" and rec["searches"] == 6, rec


def test_cli_check_exit_codes():
    import subprocess
    b = batch(refused=("t2",), remaining=())
    cp = subprocess.run([sys.executable, str(ROOT / "shared" / "below_shortlist.py"), "check",
                         str(b), "--round", "first"], capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0 and cp.stdout.startswith("below_shortlist_refill (first): yes"), \
        cp.stdout + cp.stderr
    cp = subprocess.run([sys.executable, str(ROOT / "shared" / "below_shortlist.py"), "check",
                         str(TMP / "nope"), "--round", "first"], capture_output=True, text=True,
                        timeout=60)
    assert cp.returncode == 2


# --- the retro replay ----------------------------------------------------------

def test_replay_counts_losses_queue_and_quota():
    b = batch(refused=(), remaining=(), gates={"t1": "pass", "t3": "judge_footage_defect"})
    ix = json.loads((b / "01b-footage-index.json").read_text())
    ix["reserve_substitution"]["unmatched"].append(
        {"replaced": "t2", "reason_code": "reserve_exhausted", "at": "researcher_refusal"})
    (b / "01b-footage-index.json").write_text(json.dumps(ix))
    x = bsl.replay_batch(b, day_spent=50)
    assert x["losses"] == 2 and x["queue"] == 3 and x["substitutions"] == 2, x
    assert x["searches"] == 12 and x["by_round"] == {"first": 1, "judge": 1}, x
    x = bsl.replay_batch(b, day_spent=88)
    assert x["substitutions"] == 1 and x["limited_by"] == "quota", x


def test_replay_charges_a_days_earlier_substitutes_to_the_later_batches():
    a = batch(refused=(), remaining=(), gates={"t1": "pass", "t3": "judge_footage_defect"})
    b = batch(refused=(), remaining=(), gates={"t1": "pass", "t3": "judge_footage_defect"})
    for x in (a, b):
        t = json.loads((x / "01-trend-hunter.json").read_text())
        t["search_quota"] = {"spent_searches": 40, "searches_before_stage": 0}
        (x / "01-trend-hunter.json").write_text(json.dumps(t))
    rows = bsl.replay([b, a], root=TMP)           # start order, whatever the call order
    assert [r["batch"].split("/")[1] for r in rows] == [a.name, b.name], rows
    day = rows[0]["day_spent"]
    assert day >= 80 and rows[1]["day_spent"] == day + rows[0]["searches"], rows
    assert sum(r["searches"] for r in rows) + day <= 95, rows


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")

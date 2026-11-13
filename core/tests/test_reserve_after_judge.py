#!/usr/bin/env python3
"""CF-0801 (part of CF-0798, the user's yes of 2026-10-18): the named
condition `reserve_after_judge` of `shared/run_checks.py` - a slot the frame
judge refused is refilled from the reserve once, when the slots carried short
and the round fits in the time left.

The cases of CF-0798, over synthetic batches in a temp factory root (its own
`channels/example-film.json`, `scope.max_titles_per_batch` 3), the clock and
the schedule stood in:

1. the slots are full (every slot has a video through the gate) -> no;
2. one topic refused, the others through, reserve left -> yes;
3. no reserve left -> no;
4. a second round (01b already holds an `at: frame_judge_refusal` record) -> no;
5. too little time to the end of the quota day, or to the next planned
   batch, against the round's estimate -> no, and the reason says so;
6. the estimate is this batch's own stage times, 2 h without them;
plus: no `06` -> no; the CLI's exit codes and line; the plan knows the name.
The funnel side (case 6 of CF-0798) is in tests/test_funnel_after_judge.py.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))
from _tmproot import tmp_root  # noqa: E402
import run_checks  # noqa: E402
import run_plan  # noqa: E402

TMP = tmp_root("reserve-after-judge-test-")
(TMP / "channels").mkdir()
(TMP / "channels" / "example-film.json").write_text(json.dumps(
    {"scope": {"max_titles_per_batch": 3, "target_ready_videos_per_batch": 2}}))
SCRIPT = ROOT / "shared" / "run_checks.py"
# 2026-10-18 12:00Z: the quota day (PDT) ends 2026-10-19T07:00Z - 19 h left
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
_N = [0]


def no_batch(root, now):
    return None, "no batch planned in the schedule"


def batch(gates, remaining=("r1",), subs=(), stages=None):
    """`gates`: {topic: 'pass' | reason_code}; one video per topic."""
    _N[0] += 1
    b = TMP / "pipeline" / "example-film" / f"2026-10-18T08{_N[0]:02d}Z"
    b.mkdir(parents=True)
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"batch_id": b.name, "channel": "example-film",
         "scripts": [{"script_id": f"{t}-script1", "topic_id": t} for t in gates],
         "skipped": []}))
    (b / "01b-footage-index.json").write_text(json.dumps(
        {"batch": str(b), "reserve_substitution": {
            "reserve": ["r0", *remaining], "remaining": list(remaining),
            "substitutions": list(subs), "unmatched": []}}))
    (b / "06-frame-judge.json").write_text(json.dumps(
        {"channel": "example-film", "videos": [
            {"script_id": f"{t}-script1", "slug": t,
             "gate": "pass" if g == "pass" else "reject",
             "reason_code": None if g == "pass" else g} for t, g in gates.items()]}))
    if stages is not None:
        (b / "run-state.json").write_text(json.dumps({"stages": stages}))
    return b


def check(b, now=NOW, nb=no_batch):
    return run_checks.reserve_after_judge(b, root=TMP, now=now, next_batch=nb)


def stage(start, minutes):
    a = datetime.strptime(start, "%H:%M").replace(year=2026, month=10, day=18,
                                                  tzinfo=timezone.utc)
    z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return {"status": "done", "started": z(a), "ended": z(a + timedelta(minutes=minutes))}


def test_1_the_slots_are_full_no():
    b = batch({"t1": "pass", "t2": "pass", "t3": "pass", "t4": "judge_footage_defect"})
    holds, why = check(b)
    assert not holds and "3 topic(s) already have a video" in why, why


def test_2_one_refused_ready_under_the_slots_and_reserve_yes():
    b = batch({"t1": "pass", "t2": "pass", "t3": "judge_footage_defect"})
    holds, why = check(b)
    assert holds, why
    assert why.startswith("N=1 refused (t3 (judge_footage_defect)), ready 2 < 3 "
                          "(scope.max_titles_per_batch), M=1 in reserve"), why
    assert "round ~2 h by default" in why, why


def test_a_topic_counts_as_refused_only_when_none_of_its_videos_passed():
    b = batch({"t1": "pass", "t2": "score_below_threshold"})
    fj = json.loads((b / "06-frame-judge.json").read_text())
    fj["videos"].append({"script_id": "t2-script2", "slug": "t2b", "gate": "pass"})
    (b / "06-frame-judge.json").write_text(json.dumps(fj))
    holds, why = check(b)
    assert not holds and why.startswith("N=0"), why


def test_3_no_reserve_left_no():
    b = batch({"t1": "pass", "t2": "judge_footage_defect"}, remaining=())
    holds, why = check(b)
    assert not holds and "M=0" in why, why


def test_4_a_second_round_no():
    sub = {"topic_id": "r9", "replaced": "t2", "at": "frame_judge_refusal",
           "outcome": "sources", "reason_code": "reserve_substituted"}
    b = batch({"t1": "pass", "t2": "judge_footage_defect", "r9": "judge_footage_defect"},
              subs=[sub])
    holds, why = check(b)
    assert not holds and why.startswith("one round only") and "r9 for t2" in why, why


def test_a_refusal_the_researcher_loop_answered_is_not_n():
    sub = {"topic_id": "r9", "replaced": "t2", "at": "researcher_refusal",
           "outcome": "sources"}
    b = batch({"t1": "pass", "t2": "judge_footage_defect"}, subs=[sub])
    holds, why = check(b)
    assert not holds and why.startswith("N=0"), why


def test_5_too_little_time_to_the_quota_day_end_no_with_the_reason():
    b = batch({"t1": "pass", "t2": "judge_footage_defect"})
    late = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)        # 1 h before 07:00Z
    holds, why = check(b, now=late)
    assert not holds, why
    assert "skipped - time" in why and "1 h 00 min left until the quota day ends " \
                                         "2026-10-19T07:00Z" in why, why


def test_5_the_next_planned_batch_bounds_the_round_too():
    b = batch({"t1": "pass", "t2": "judge_footage_defect"})
    soon = NOW + timedelta(minutes=90)
    holds, why = check(b, nb=lambda root, now: (soon, "next planned batch 2026-10-18T13:30Z"))
    assert not holds and "skipped - time" in why and \
        "1 h 30 min left until next planned batch 2026-10-18T13:30Z" in why, why
    far = NOW + timedelta(hours=8)
    holds, why = check(b, nb=lambda root, now: (far, "next planned batch 2026-10-18T20:00Z"))
    assert holds, why


def test_6_the_estimate_is_this_batchs_own_stage_times():
    stages = {"footage-indexer-reserve-late": stage("15:02", 67),
              "footage-indexer-reserve": {"status": "skipped", "ended": "2026-10-18T11:34:29Z"},
              "content-researcher": stage("10:29", 65),
              "content-researcher-reserve-late": stage("16:09", 25),
              "compliance-scripts": stage("16:35", 1),
              "video-editor": stage("16:36", 21),
              "frame-judge": stage("16:57", 3)}
    b = batch({"t1": "pass", "t2": "judge_footage_defect"}, stages=stages)
    est, why = run_checks.round_estimate(b)
    assert est == (67 + 25 + 1 + 21 + 3) * 60, (est, why)
    assert "footage-indexer-reserve-late 1 h 07 min" in why, why
    # 2 h 30 min before the quota day ends: the measured 1 h 57 min fits
    holds, why = check(b, now=datetime(2026, 10, 19, 4, 30, tzinfo=timezone.utc))
    assert holds, why
    # no reserve round ran: the researcher's own stage stands in, the indexer's
    # part is unmeasured - 2 h by default
    del stages["footage-indexer-reserve-late"]
    (b / "run-state.json").write_text(json.dumps({"stages": stages}))
    est, why = run_checks.round_estimate(b)
    assert est == run_checks.ROUND_DEFAULT_S and "footage-indexer-reserve" in why, why


def test_without_06_no():
    b = batch({"t1": "pass"})
    (b / "06-frame-judge.json").unlink()
    holds, why = check(b)
    assert not holds and why.startswith("no 06-frame-judge.json"), why


def test_the_cli_says_the_decision_and_exits_by_it():
    env = dict(os.environ, FACTORY_ROOT=str(TMP))
    yes = batch({"t1": "pass", "t2": "judge_footage_defect"})
    cp = subprocess.run([sys.executable, str(SCRIPT), "reserve-after-judge", str(yes),
                         "--root", str(TMP)], capture_output=True, text=True, timeout=120, env=env)
    # the real clock and the stand root's schedule (switch off): yes unless the
    # quota day is about to end, which the line names either way
    assert cp.stdout.startswith("reserve_after_judge: "), cp.stdout + cp.stderr
    assert cp.returncode == (0 if "- N=1" in cp.stdout and "skipped" not in cp.stdout else 1)
    no = batch({"t1": "pass", "t2": "judge_footage_defect"}, remaining=())
    cp = subprocess.run([sys.executable, str(SCRIPT), "reserve-after-judge", str(no),
                         "--root", str(TMP)], capture_output=True, text=True, timeout=120, env=env)
    assert cp.returncode == 1 and cp.stdout.startswith("reserve_after_judge: no - "), cp.stdout
    cp = subprocess.run([sys.executable, str(SCRIPT), "reserve-after-judge", str(TMP / "nope")],
                        capture_output=True, text=True, timeout=60, env=env)
    assert cp.returncode == 2, cp.stdout + cp.stderr


def test_the_plan_knows_the_condition_and_check_dispatches_it():
    assert "reserve_after_judge" in run_plan.CONDITIONS
    assert set(run_checks.CHECKS) == set(run_plan.CONDITIONS)
    b = batch({"t1": "pass", "t2": "judge_footage_defect"}, remaining=())
    holds, why = run_checks.check("reserve_after_judge", b, root=TMP)
    assert not holds and "M=0" in why, why


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")

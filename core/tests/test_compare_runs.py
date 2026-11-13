#!/usr/bin/env python3
"""CF-0204: `scripts/compare_runs.py` - a batch run by the executor held
against the last batch run by hand (the same stages, order, output) and the
operator's wait of each (CF-0070).

Synthetic batches only, in a temporary root with a synthetic channel plan; no
real `pipeline/` is read.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))
from _tmproot import tmp_root  # noqa: E402
import compare_runs as cr  # noqa: E402

TMP = tmp_root("compare-runs-test-")
_N = [0]

HAND = ["pool-maintenance", "trend-hunter", "compliance-checker", "footage-indexer",
        "content-researcher", "thin-pool-supplement", "compliance-checker", "video-editor",
        "frame-judge"]
FILES = ["01-trend-hunter.json", "01b-footage-index.json", "02-compliance-checker.json",
         "03-content-researcher.json", "04-compliance-checker.json", "05-video-editor.json",
         "06-frame-judge.json", "RUN_SUMMARY.md", "TRIAGE.md"]

WALL = """# summary

## Where the wall went

| part | time | what it is |
|---|---|---|
| gaps | 0.0s | x |
| busy | {busy} | x |
| waiting for a human | {wait} | x |
| operator | 40m48s | x |
| operator idle | {idle} | x |
| unattributed | {unattr} | x |
| = wall | 3h15m17s | |

## 7. Topic funnel
"""

PLAN = {"version": 1, "batch_dir": "pipeline/{channel}/{batch_id}", "stages": [
    {"id": "supplement", "marker": "thin-pool-supplement", "produces": ["work/supplement-step.json"]},
    {"id": "judge", "marker": "frame-judge", "produces": ["06-frame-judge.json"]},
]}


def _root():
    _N[0] += 1
    root = TMP / f"root{_N[0]}"
    (root / "channels").mkdir(parents=True)
    (root / "channels" / "testchan.json").write_text(json.dumps({"run_plan": PLAN}))
    return root


def batch(root, name, stages, files=FILES, restarted=(), state=None,
          wall=("1h48m44s", "0.0s", "30m57s", "14m48s"), videos=3, ready=2):
    b = root / "pipeline" / "testchan" / name
    b.mkdir(parents=True)
    ev = [{"kind": "marker", "status": "batch-start", "stage": None}]
    for s in stages:
        ev.append({"kind": "marker", "status": "stage-start", "stage": s})
        ev.append({"kind": "script", "status": "start", "stage": s})
        if s in restarted:
            ev.append({"kind": "marker", "status": "stage-done", "stage": s,
                       "note": "restarted (CF-0204): pid 1 died without an exit code"})
            ev.append({"kind": "marker", "status": "stage-start", "stage": s})
        ev.append({"kind": "marker", "status": "stage-done", "stage": s, "note": None})
    ev.append({"kind": "marker", "status": "batch-done", "stage": None})
    (b / "RUN_EVENTS.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))
    for f in files:
        if f == "RUN_SUMMARY.md":
            busy, wait, idle, unattr = wall
            (b / f).write_text(WALL.format(busy=busy, wait=wait, idle=idle, unattr=unattr))
        elif f == "03-content-researcher.json":
            (b / f).write_text(json.dumps({"scripts": [{}, {}, {}, {}]}))
        elif f == "05-video-editor.json":
            (b / f).write_text(json.dumps({"videos": [{"qc": {"passed": i < ready}} for i in range(videos)]}))
        else:
            (b / f).write_text("{}")
    (b / "videos").mkdir()
    for i in range(ready):
        (b / "videos" / f"v{i}.mp4").write_bytes(b"")
    if state is not None:
        (b / "run-state.json").write_text(json.dumps(
            {"channel": "testchan", "root": str(root), "stages": state}))
    return b


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cr.main([str(a) for a in argv])
    return code, buf.getvalue()


def test_the_same_run_is_no_defect():
    root = _root()
    a, b = batch(root, "hand", HAND), batch(root, "exec", HAND, state={})
    code, out = run(a, b, "--root", root)
    assert code == 0, out
    assert "the same stages, order and files" in out
    assert "scripts (03)" in out and "qc passed (05)" in out
    assert cr.output_of(a)[1]["qc passed (05)"] == 2


def test_a_restarted_attempt_is_not_a_stage():
    root = _root()
    a = batch(root, "hand", HAND)
    b = batch(root, "exec", HAND, restarted=("footage-indexer",), state={})
    assert cr.stage_sequence(cr.read_events(b)) == HAND
    code, out = run(a, b, "--root", root)
    assert code == 0, out


def test_a_stage_the_executor_did_not_run_is_a_defect():
    root = _root()
    a = batch(root, "hand", HAND)
    b = batch(root, "exec", [s for s in HAND if s != "video-editor"], state={})
    code, out = run(a, b, "--root", root)
    assert code == 1 and "DEFECT stage video-editor#1: ran by hand, not by the executor" in out, out


def test_a_stage_skipped_on_its_condition_is_a_note_not_a_defect():
    root = _root()
    a = batch(root, "hand", HAND)
    b = batch(root, "exec", [s for s in HAND if s != "thin-pool-supplement"],
              state={"supplement": {"status": "skipped",
                                    "reason": "when: work/supplement-requests/*.json: 0 file(s)"}})
    code, out = run(a, b, "--root", root)
    assert code == 0, out
    assert "note   stage thin-pool-supplement#1: ran by hand, skipped by the plan" in out


def test_an_extra_stage_and_a_changed_order_are_defects():
    root = _root()
    a = batch(root, "hand", HAND)
    swapped = list(HAND)
    i, j = swapped.index("video-editor"), swapped.index("frame-judge")
    swapped[i], swapped[j] = swapped[j], swapped[i]
    b = batch(root, "exec", swapped + ["publisher"], state={})
    r = cr.compare(a, b, root)
    assert any(d.startswith("order:") for d in r["defects"]), r["defects"]
    assert "stage publisher#1: ran by the executor, not by hand" in r["defects"]


def test_the_second_compliance_pass_is_counted_apart():
    root = _root()
    a = batch(root, "hand", HAND)
    one_pass = list(HAND)
    one_pass.remove("compliance-checker")
    b = batch(root, "exec", one_pass, state={})
    r = cr.compare(a, b, root)
    assert "stage compliance-checker#2: ran by hand, not by the executor" in r["defects"], r


def test_a_missing_file_is_a_defect_unless_its_stage_was_skipped():
    root = _root()
    a = batch(root, "hand", HAND)
    b = batch(root, "exec", [s for s in HAND if s != "frame-judge"],
              files=[f for f in FILES if f != "06-frame-judge.json"],
              state={"judge": {"status": "skipped", "reason": "when: stopcock exited 3"}})
    r = cr.compare(a, b, root)
    assert r["defects"] == [], r["defects"]
    assert any("06-frame-judge.json" in n and "judge was skipped" in n for n in r["notes"])
    c = batch(root, "exec2", HAND, files=[f for f in FILES if f != "TRIAGE.md"], state={})
    r = cr.compare(a, c, root)
    assert r["defects"] == ["file TRIAGE.md: by hand only"], r["defects"]


def test_the_operator_wait_is_read_from_where_the_wall_went():
    root = _root()
    a = batch(root, "hand", HAND, wall=("1h00m00s", "1h43m20s", "30m57s", "14m48s"))
    b = batch(root, "exec", HAND, wall=("1h00m00s", "0.0s", "0.0s", "2m00s"), state={})
    r = cr.compare(a, b, root)
    w = r["wall"]["operator_wait_s"]
    assert w["manual"] == 6200 + 1857 + 888 and w["executor"] == 120, w
    assert r["wall"]["manual"]["= wall"] == 3 * 3600 + 15 * 60 + 17
    _, out = run(a, b, "--root", root)
    assert "operator wait" in out and "2h29m05s" in out and "2m00s" in out


def test_durations():
    assert cr.seconds("3h15m17s") == 11717 and cr.seconds("0.0s") == 0
    assert cr.seconds("14m48s") == 888 and cr.seconds("6.9s") == 6.9
    assert cr.seconds("") is None and cr.seconds("n/a") is None


def test_a_directory_without_events_is_a_bad_call():
    root = _root()
    a = batch(root, "hand", HAND)
    empty = root / "pipeline" / "testchan" / "empty"
    empty.mkdir()
    code, out = run(a, empty)
    assert code == 2 and "no RUN_EVENTS.jsonl" in out


def test_json_output():
    root = _root()
    a, b = batch(root, "hand", HAND), batch(root, "exec", HAND, state={})
    code, out = run(a, b, "--root", root, "--json")
    doc = json.loads(out)
    assert code == 0 and doc["stages"]["executor"] == HAND and doc["defects"] == []


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

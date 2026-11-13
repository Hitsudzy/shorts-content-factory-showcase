#!/usr/bin/env python3
"""CF-0422 (part 2): the stages after the Researcher wait for the plan check
after the thin-pool supplement.

Step 6b (`plan_check_loop.py --write`, CF-0411) defers a script whose topic
has an open supplement request instead of dropping it; after
`thin-pool-supplement` the orchestrator runs `plan_check_loop.py <batch>
--write --after-supplement`. Checked here:

* `runlog stage-start compliance-checker` (and the other gated stages) is
  refused (exit 2) while the Researcher's `--pending-after-supplement` names a
  deferred script - the refusal names the script and the exact command;
* it opens once the check after the supplement has settled it;
* `--anyway REASON` goes through and is written (`plan_check_override`);
* a batch with no 03, or a checkout without the Researcher's script, is not
  refused;
* while the supplement step itself is still pending, its own refusal comes
  first and the plan command is not named yet;
* `thin_pool_supplement.py`, done, prints the `--after-supplement` command;
* the contract with the real Researcher's `--pending-after-supplement --json`
  (skipped when the checkout has no `agents/content-researcher`).

The Researcher is played by a stand-in `plan_check_loop.py` under a fake
factory root that reads the same state the real one does:
`work/<slug>/plan_check_loop.json`, `deferred_for_supplement` and
`after_supplement.outcome`.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import supplement  # noqa: E402

from _tmproot import tmp_root   # noqa: E402  (CF-0339)

TMP = tmp_root("plan-after-supplement-test-")
FAKE_ROOT = TMP / "root"           # has the stand-in Researcher script
BARE_ROOT = TMP / "bare"           # has none
BARE_ROOT.mkdir(parents=True, exist_ok=True)
_n = [0]

STAND_IN = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
DONE = ("assembled", "dropped", "environment")
b = Path(sys.argv[1])
assert "--pending-after-supplement" in sys.argv and "--json" in sys.argv, sys.argv
f = b / "03-content-researcher.json"
if not f.exists():
    sys.exit(2)
rows = []
for s in json.loads(f.read_text()).get("scripts") or []:
    st = b / "work" / s["script_id"] / "plan_check_loop.json"
    if not st.exists():
        continue
    st = json.loads(st.read_text())
    out = (st.get("after_supplement") or {}).get("outcome")
    if st.get("deferred_for_supplement") and out not in DONE:
        rows.append({"script_id": s["script_id"], "topic_id": s["topic_id"],
                     "slug": s["script_id"], "deferred_at": "t",
                     "supplement_request": None, "after_supplement": out or "not run"})
print(json.dumps({"batch": str(b), "pending": rows}))
sys.exit(1 if rows else 0)
'''
(FAKE_ROOT / supplement.PLAN_LOOP).parent.mkdir(parents=True, exist_ok=True)
(FAKE_ROOT / supplement.PLAN_LOOP).write_text(STAND_IN)


def batch(deferred=("s-t1",), request=False):
    """A batch whose 03 holds s-t1 and s-t2; `deferred` were deferred at 6b."""
    _n[0] += 1
    b = TMP / "pipeline" / "example-film" / f"2026-09-28T00{_n[0]:02d}Z"
    b.mkdir(parents=True)
    (b / supplement.SCRIPTS_FILE).write_text(json.dumps(
        {"scripts": [{"script_id": f"s-{t}", "topic_id": t} for t in ("t1", "t2")],
         "skipped": [], "warnings": []}))
    for sid in deferred:
        st = b / "work" / sid / "plan_check_loop.json"
        st.parent.mkdir(parents=True)
        st.write_text(json.dumps({"kind": "plan_check_loop", "script_id": sid,
                                  "deferred_for_supplement": {"at": "t"}, "checks": []}))
    if request:
        d = b / supplement.REQUEST_DIR
        d.mkdir(parents=True)
        (d / "t1.json").write_text(json.dumps(
            {"kind": supplement.KIND, "topic_id": "t1", "reason_code": "pool_too_thin"}))
    return b


def settle(b, sid="s-t1", outcome="assembled"):
    st = b / "work" / sid / "plan_check_loop.json"
    doc = json.loads(st.read_text())
    doc["after_supplement"] = {"outcome": outcome}
    st.write_text(json.dumps(doc))


def runlog_cli(bdir, *args, root=FAKE_ROOT):
    env = dict(os.environ, RUNLOG_BATCH=str(bdir), FACTORY_ROOT=str(root),
               RUNLOG_STATE_DIR=str(TMP / "state"))
    env.pop(supplement.API_KEY, None)
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog")] + list(args),
                          capture_output=True, text=True, env=env, timeout=120)


def events(b):
    return [json.loads(l) for l in (b / "RUN_EVENTS.jsonl").read_text().splitlines()
            if l.strip()]


def test_compliance_waits_for_the_plan_check_after_the_supplement():
    b = batch()
    assert runlog_cli(b, "batch-start", "--note", "t").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 2, p.stderr
        assert "CF-0422" in p.stderr and "s-t1" in p.stderr, p.stderr
        assert "s-t2" not in p.stderr, p.stderr
        # /var vs /private/var on macOS: the paths are compared by their tails.
        assert (f"{supplement.PLAN_LOOP} " in p.stderr
                and f"{b.name} --write --after-supplement`" in p.stderr), p.stderr
        for stage in ("video-editor", "frame-judge", "publisher"):
            assert runlog_cli(b, "stage-start", stage).returncode == 2, stage
        # The Researcher's own stages are not gated.
        p = runlog_cli(b, "stage-start", "content-researcher")
        assert p.returncode == 0, p.stderr
        assert runlog_cli(b, "stage-done", "content-researcher").returncode == 0
        # Still waiting for an anchor edit is not settled.
        settle(b, outcome="edit")
        assert runlog_cli(b, "stage-start", "compliance-checker").returncode == 2
        settle(b, outcome="assembled")
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 0, p.stderr
        start = [e for e in events(b) if e.get("status") == "stage-start"][-1]
        assert "plan_check_override" not in start
    finally:
        runlog_cli(b, "batch-done")


def test_nothing_deferred_is_not_refused():
    b = batch(deferred=())
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 0, p.stderr
    finally:
        runlog_cli(b, "batch-done")


def test_anyway_goes_through_and_is_recorded():
    b = batch()
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker", "--anyway", "operator ruled")
        assert p.returncode == 0, p.stderr
        start = [e for e in events(b) if e.get("status") == "stage-start"][-1]
        o = start["plan_check_override"]
        assert o["reason"] == "operator ruled" and o["pending"] == ["s-t1"], o
        assert o["command"].endswith(f"{b} --write --after-supplement"), o
        assert o["task"] == "CF-0422"
    finally:
        runlog_cli(b, "batch-done")


def test_no_03_is_not_refused():
    b = batch()
    (b / supplement.SCRIPTS_FILE).unlink()
    assert supplement.plan_check_pending(b, FAKE_ROOT) is None
    assert supplement.plan_blocks("compliance-checker", b, FAKE_ROOT) is None
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 0, p.stderr
    finally:
        runlog_cli(b, "batch-done")


def test_a_checkout_without_the_researcher_is_not_refused():
    b = batch()
    assert supplement.plan_check_pending(b, BARE_ROOT) is None
    assert runlog_cli(b, "batch-start", root=BARE_ROOT).returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker", root=BARE_ROOT)
        assert p.returncode == 0, p.stderr
    finally:
        runlog_cli(b, "batch-done", root=BARE_ROOT)


def test_the_supplement_step_comes_first():
    b = batch(request=True)
    assert runlog_cli(b, "batch-start").returncode == 0
    try:
        p = runlog_cli(b, "stage-start", "compliance-checker")
        assert p.returncode == 2, p.stderr
        assert "CF-0345" in p.stderr, p.stderr
        assert "--after-supplement" not in p.stderr, p.stderr
        # --anyway past both writes both.
        p = runlog_cli(b, "stage-start", "compliance-checker", "--anyway", "both")
        assert p.returncode == 0, p.stderr
        start = [e for e in events(b) if e.get("status") == "stage-start"][-1]
        assert start["supplement_override"]["reason"] == "both"
        assert start["plan_check_override"]["pending"] == ["s-t1"]
    finally:
        runlog_cli(b, "batch-done")


def _main_out(b, root):
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "thin_pool_supplement.py"),
                        str(b), "--root", str(root)], capture_output=True, text=True,
                       timeout=120, env=dict(os.environ, FACTORY_ROOT=str(root)))
    return p


def test_the_step_done_names_the_next_command():
    b = batch()
    p = _main_out(b, FAKE_ROOT)
    assert p.returncode == 0, p.stderr
    assert "CF-0422" in p.stdout and "s-t1" in p.stdout, p.stdout
    assert f"{b} --write --after-supplement" in p.stdout, p.stdout
    # It only names it: nothing was settled.
    st = json.loads((b / "work" / "s-t1" / "plan_check_loop.json").read_text())
    assert "after_supplement" not in st
    settle(b)
    p = _main_out(b, FAKE_ROOT)
    assert p.returncode == 0 and "--after-supplement" not in p.stdout, p.stdout


def _real_root():
    for r in (ROOT, ROOT.parents[2] if ROOT.parent.name == "worktrees" else None):
        if r is not None and (r / supplement.PLAN_LOOP).is_file():
            return r
    return None


def test_the_real_researcher_answers_the_same_contract():
    real = _real_root()
    if real is None:
        print("     no agents/content-researcher in this checkout - skipped")
        return
    b = batch(deferred=())
    assert supplement.plan_check_pending(b, real) == []
    # The real slug rule: script_id `s-t1` -> work/s-t1.
    st = b / "work" / "s-t1" / "plan_check_loop.json"
    st.parent.mkdir(parents=True)
    st.write_text(json.dumps({"kind": "plan_check_loop", "script_id": "s-t1",
                              "deferred_for_supplement": {"at": "t"}, "checks": []}))
    rows = supplement.plan_check_pending(b, real)
    assert [r["script_id"] for r in rows] == ["s-t1"], rows
    settle(b)
    assert supplement.plan_check_pending(b, real) == []


# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)

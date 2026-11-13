#!/usr/bin/env python3
"""CF-0107 verification: run accounting never lands in a batch a test merely
reads.

The instrumented scripts resolve their batch dir, when RUNLOG_BATCH is not
set, from any path-looking argv element shaped pipeline/<channel>/<batch>
(shared/runlog/runlog.py, lookup rule 3). The e2e tests replay real batch
paths, so one full suite on main left 1596 stray events in the real
pipeline/legacy-film/2026-08-31T2155Z/RUN_EVENTS.jsonl (the channel is
example-film since CF-0180; its batch directories keep the old slug, being a
dated journal that was deliberately not renamed). tests/run_tests.py
now exports RUNLOG_BATCH (and RUNLOG_STATE_DIR) to temp dirs for the whole
suite and, as proof rather than policy, snapshots every real batch's
RUN_EVENTS.jsonl before the suite and fails the run if any appeared, vanished
or changed size after it.

Checks:
  - the leak is real: an instrumented script run on a real-batch-shaped path
    with no RUNLOG_BATCH writes into that batch (so the guard is needed);
  - under the runner the same script records into the runner's temp batch,
    the fake real batch stays clean, the temp batch is gone afterwards, the
    state dir is not ~/.shorts-content-factory, and the guard reports PASS;
  - RUNLOG_BATCH already in the environment is kept, not overridden;
  - a test that does write into a real batch fails the whole run, by name;
  - the guard's default root is this checkout's pipeline/, and this file
    itself changes nothing under it.

The stand-in script uses the same `runlog.script` decorator the real ones
use; nothing here touches the real pipeline/ except reading its snapshot.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
SCRIPTS = AGENT_ROOT / "scripts"
RUNNER = HERE / "run_tests.py"
PY = sys.executable
sys.path.insert(0, str(HERE))

import run_tests  # noqa: E402

LEAKY = f'''
import sys
sys.path.insert(0, {str(SCRIPTS)!r})
from _runlog import runlog


@runlog.script("video-editor", "guard-probe", name="leaky.py")
def cli():
    print("probe ran on", sys.argv[1])


if __name__ == "__main__":
    cli()
'''

# A test file the runner will run: the stand-in on a real-batch-shaped path,
# then a look at where the events went.
PROBE_TEST = '''
import json, os, subprocess, sys
from pathlib import Path
r = subprocess.run([sys.executable, {leaky!r}, {plan!r}], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
batch = os.environ.get("RUNLOG_BATCH")
print("RUNLOG_BATCH =", batch)
print("RUNLOG_STATE_DIR =", os.environ.get("RUNLOG_STATE_DIR"))
events = Path(batch) / "RUN_EVENTS.jsonl"
lines = [json.loads(l) for l in events.read_text().splitlines() if l.strip()]
assert any(e["kind"] == "script" and e.get("step") == "guard-probe" for e in lines), lines
print("events landed in", events)
print("1/1 passed")
'''

# A test file that misbehaves: writes straight into the "real" batch.
LEAKING_TEST = '''
from pathlib import Path
Path({events!r}).write_text('{{"kind": "script", "step": "leak"}}\\n')
print("1/1 passed")
'''


def _fake_factory(tmp):
    """tmp/factory/pipeline/chan/<batch>/work/slug/plan.json - shaped so that
    lookup rule 3 resolves plan.json to <batch>."""
    tmp = Path(tmp).resolve()      # the runner resolves its root; compare like with like
    batch = tmp / "factory" / "pipeline" / "chan" / "2026-01-01T0000Z"
    work = batch / "work" / "slug"
    work.mkdir(parents=True)
    plan = work / "plan.json"
    plan.write_text("{}")
    leaky = Path(tmp) / "leaky.py"
    leaky.write_text(LEAKY)
    return batch, plan, leaky


def _env(tmp, **extra):
    """os.environ without any batch, with a temp state dir (never
    ~/.shorts-content-factory), plus extra."""
    env = dict(os.environ)
    for var in ("RUNLOG_BATCH", "RUNLOG_PARENT", "RUN_TESTS_PIPELINE_ROOT"):
        env.pop(var, None)
    env["RUNLOG_STATE_DIR"] = str(Path(tmp) / "state")
    env.update(extra)
    return env


def _runner(tests_dir, env):
    return subprocess.run([PY, str(RUNNER), "--dir", str(tests_dir)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, env=env, timeout=120)


def _printed(out, key):
    for line in out.splitlines():
        if line.startswith(key + " = "):
            return line[len(key) + 3:]
    raise AssertionError(f"{key} not printed:\n{out}")


def test_the_leak_is_real_without_the_export():
    """Rule 3 does what the guard exists for: no RUNLOG_BATCH + a real-batch
    path in argv = events in that batch, as long as its journal is open. If
    this ever stops holding, the library changed and the guard can be revisited.
    Since CF-0251 the walk no longer writes into a batch without an open
    journal (no batch-start, or closed by batch-done): checked first."""
    with tempfile.TemporaryDirectory() as tmp:
        batch, plan, leaky = _fake_factory(tmp)
        events = batch / "RUN_EVENTS.jsonl"
        r = subprocess.run([PY, str(leaky), str(plan)], capture_output=True, text=True,
                           env=_env(tmp), timeout=60)
        assert r.returncode == 0 and "probe ran on" in r.stdout, r.stdout + r.stderr
        assert not events.exists(), "the walk created a journal for a batch that had none"
        events.write_text(json.dumps({"ts": "2026-01-01T00:00:00.000Z", "kind": "marker",
                                      "stage": None, "status": "batch-start"}) + "\n")
        r = subprocess.run([PY, str(leaky), str(plan)], capture_output=True, text=True,
                           env=_env(tmp), timeout=60)
        assert r.returncode == 0 and "probe ran on" in r.stdout, r.stdout + r.stderr
        assert events.exists(), "the stand-in did not record into the batch its argv names"
        lines = [json.loads(l) for l in events.read_text().splitlines() if l.strip()]
        assert any(e["kind"] == "script" and e["step"] == "guard-probe" for e in lines), lines


def test_no_events_written_into_real_batches():
    # CF-0519: no snapshot of the live pipeline/ here any more - that is the
    # runner's own guard around the whole suite (snapshot_events before and
    # after every file); this test proves the guard on a fake root.
    with tempfile.TemporaryDirectory() as tmp:
        batch, plan, leaky = _fake_factory(tmp)
        fake_root = batch.parent.parent
        events = batch / "RUN_EVENTS.jsonl"
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_probe.py").write_text(
            PROBE_TEST.format(leaky=str(leaky), plan=str(plan)))

        # 1. under the runner: temp batch, fake real batch untouched, guard PASS
        r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root)))
        assert r.returncode == 0, r.stdout
        assert "PASS test_probe.py: 1/1" in r.stdout, r.stdout
        assert f"PASS {run_tests.GUARD_NAME}: 0 RUN_EVENTS.jsonl under {fake_root} unchanged" in r.stdout, r.stdout
        assert not events.exists(), f"the probe recorded into the real-shaped batch:\n{r.stdout}"
        temp_batch = Path(_printed(r.stdout, "RUNLOG_BATCH"))
        assert fake_root not in temp_batch.parents and temp_batch.name.startswith("run-tests-runlog_batch-"), temp_batch
        assert not temp_batch.exists(), f"the runner left its temp batch behind: {temp_batch}"
        assert f"RUNLOG_BATCH={temp_batch} (temp, removed when the suite ends)" in r.stdout, r.stdout
        state = Path(_printed(r.stdout, "RUNLOG_STATE_DIR"))
        assert state == Path(tmp) / "state", state          # kept: the env already set it
        assert f"RUNLOG_STATE_DIR={state} (kept from the environment)" in r.stdout, r.stdout
        assert state != Path.home() / ".shorts-content-factory"

        # 2. RUNLOG_BATCH already in the environment is kept, not overridden
        mine = Path(tmp) / "mine"
        mine.mkdir()
        r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root),
                                    RUNLOG_BATCH=str(mine)))
        assert r.returncode == 0, r.stdout
        assert _printed(r.stdout, "RUNLOG_BATCH") == str(mine), r.stdout
        assert f"RUNLOG_BATCH={mine} (kept from the environment)" in r.stdout, r.stdout
        assert (mine / "RUN_EVENTS.jsonl").exists() and not events.exists()

        # 3. a test that writes into a real batch fails the whole run, by name
        (tests_dir / "test_probe.py").unlink()
        (tests_dir / "test_leaks.py").write_text(LEAKING_TEST.format(events=str(events)))
        r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root)))
        assert r.returncode == 1, r.stdout
        assert "PASS test_leaks.py: 1/1" in r.stdout, r.stdout     # the file itself is green...
        assert (f"FAIL {run_tests.GUARD_NAME}: a test wrote run accounting into a real batch "
                f"under {fake_root} - appeared: {events}") in r.stdout, r.stdout
        assert f"FAILED {run_tests.GUARD_NAME}:" in r.stdout, r.stdout
        assert "TOTAL 1/1 passed in 1 files - 1 FAILED" in r.stdout, r.stdout

        # 4. ...and a changed size is caught the same way
        r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root)))
        assert r.returncode == 0, r.stdout     # same bytes rewritten: nothing changed
        (tests_dir / "test_leaks.py").write_text(
            LEAKING_TEST.format(events=str(events)).replace('"leak"', '"leak-again"'))
        r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root)))
        assert r.returncode == 1 and f"changed: {events} (" in r.stdout, r.stdout



def test_the_guard_watches_this_checkouts_pipeline_by_default():
    saved = os.environ.pop("RUN_TESTS_PIPELINE_ROOT", None)
    try:
        root = run_tests.pipeline_root()
    finally:
        if saved is not None:
            os.environ["RUN_TESTS_PIPELINE_ROOT"] = saved
    assert root is not None and root.name == "pipeline" and root.is_dir(), root
    assert root in AGENT_ROOT.parents or root.parent in AGENT_ROOT.parents, (root, AGENT_ROOT)
    # CF-0519: the shape of the snapshot is checked on a fake root of the
    # same layout, not by walking every live batch - <channel>/<batch>/
    # RUN_EVENTS.jsonl is watched, a skip directory and a deeper file are not.
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "pipeline"
        watched = fake / "some-channel" / "2026-01-01T0000Z" / "RUN_EVENTS.jsonl"
        skipped = fake / run_tests.GUARD_SKIP_DIRS[0] / "2026-01-01T0000Z" / "RUN_EVENTS.jsonl"
        deeper = fake / "some-channel" / "2026-01-01T0000Z" / "work" / "RUN_EVENTS.jsonl"
        for f in (watched, skipped, deeper):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("{}\n")
        assert run_tests.snapshot_events(fake) == {str(watched): 3}


# --------------------------------------------------------------------------
# CF-0482: live batches are not judged, every file isolates itself
# --------------------------------------------------------------------------

APPENDING_TEST = '''
with open({events!r}, "a") as fh:
    fh.write('{{"ts": "2026-01-01T00:00:01Z", "kind": "script", "name": "leak.py", "step": "leak", "pid": 4242}}\\n')
print("1/1 passed")
'''


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _open_batch(batch, last_ts, done=False):
    lines = [{"ts": last_ts, "kind": "marker", "note": "batch-start"},
             {"ts": last_ts, "kind": "script", "name": "plan.py", "pid": 1}]
    if done:
        lines.append({"ts": last_ts, "kind": "marker", "note": "batch-done"})
    (batch / "RUN_EVENTS.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines))


def test_a_live_batch_growing_under_the_suite_is_noted_not_failed():
    """A batch that is open (batch-start, no batch-done) and was written in the
    last LIVE_HOURS grows by its own processes - a running batch, or a
    production one seen through a version worktree's pipeline/* link."""
    from datetime import datetime, timedelta, timezone
    with tempfile.TemporaryDirectory() as tmp:
        batch, plan, leaky = _fake_factory(tmp)
        fake_root = batch.parent.parent
        events = batch / "RUN_EVENTS.jsonl"
        _open_batch(batch, _iso(datetime.now(timezone.utc) - timedelta(minutes=5)))
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_appends.py").write_text(APPENDING_TEST.format(events=str(events)))
        r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root)))
        assert r.returncode == 0, r.stdout
        assert f"NOTE {run_tests.GUARD_NAME}: {events} is a live batch (open" in r.stdout, r.stdout
        assert "(1 live batch(es) not judged)" in r.stdout, r.stdout


def test_a_closed_or_stale_batch_still_fails_and_names_the_file_and_the_writer():
    """Not relaxed: a finished batch, or an open one silent past LIVE_HOURS
    (a crash, not a run), changing under the suite is still a FAIL - now with
    the test file it changed during and the process that wrote."""
    from datetime import datetime, timedelta, timezone
    for done, age in ((True, timedelta(minutes=5)), (False, timedelta(hours=48))):
        with tempfile.TemporaryDirectory() as tmp:
            batch, plan, leaky = _fake_factory(tmp)
            fake_root = batch.parent.parent
            events = batch / "RUN_EVENTS.jsonl"
            _open_batch(batch, _iso(datetime.now(timezone.utc) - age), done=done)
            tests_dir = Path(tmp) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_appends.py").write_text(APPENDING_TEST.format(events=str(events)))
            r = _runner(tests_dir, _env(tmp, RUN_TESTS_PIPELINE_ROOT=str(fake_root)))
            assert r.returncode == 1, (done, age, r.stdout)
            assert f"changed: {events} (" in r.stdout, r.stdout
            assert "during test_appends.py; written by leak.py pid 4242" in r.stdout, r.stdout


def test_judge_drift_reads_live_only_from_the_batch_itself():
    from datetime import datetime, timedelta, timezone
    with tempfile.TemporaryDirectory() as tmp:
        batch, _, _ = _fake_factory(tmp)
        events = batch / "RUN_EVENTS.jsonl"
        now = datetime.now(timezone.utc)
        _open_batch(batch, _iso(now - timedelta(hours=1)))
        size = events.stat().st_size
        with open(events, "a") as fh:
            fh.write('{"ts": "x", "kind": "script", "name": "render.py", "pid": 7}\n')
        before, after = {str(events): size}, {str(events): events.stat().st_size}
        problems, notes = run_tests.judge_drift(before, after, now=now)
        assert problems == [] and len(notes) == 1, (problems, notes)
        problems, notes = run_tests.judge_drift(before, after, now=now + timedelta(hours=30))
        assert len(problems) == 1 and "render.py pid 7" in problems[0], problems


def test_every_test_file_isolates_its_own_run_accounting():
    """A test file run on its own - not under run_tests.py - used to write into
    the real batch whose paths it replays (test_degrade_blocks.py and
    test_rhythm_execution.py into 2026-08-31T2155Z, 2026-09-28..10-02). Every
    test_*.py imports `_isolated_runlog` as its first import."""
    import ast
    missing = []
    for f in sorted(HERE.glob("test_*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        first = next((n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
                      and not (isinstance(n, ast.ImportFrom) and n.module == "__future__")),
                     None)
        if not (isinstance(first, ast.Import) and first.names[0].name == "_isolated_runlog"):
            missing.append(f.name)
    assert not missing, f"first import is not _isolated_runlog in: {missing}"


def test_a_file_run_directly_exports_a_temp_batch():
    """The helper does for one file what the runner does for the suite: with
    no RUNLOG_BATCH in the environment the stand-in script records into a temp
    batch, never into the real-batch-shaped path it was handed."""
    with tempfile.TemporaryDirectory() as tmp:
        batch, plan, leaky = _fake_factory(tmp)
        code = (f"import sys; sys.path.insert(0, {str(HERE)!r}); import _isolated_runlog, os, "
                f"subprocess; r = subprocess.run([sys.executable, {str(leaky)!r}, {str(plan)!r}]); "
                f"print(os.environ['RUNLOG_BATCH']); sys.exit(r.returncode)")
        r = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                           env=_env(tmp), timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        temp_batch = Path(r.stdout.strip().splitlines()[-1])
        assert not (batch / "RUN_EVENTS.jsonl").exists(), "the probe recorded into the real-shaped batch"
        assert not temp_batch.exists(), f"the helper left its temp batch behind: {temp_batch}"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
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

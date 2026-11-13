#!/usr/bin/env python3
"""CF-0251: nobody writes into the journal of a finished batch by accident,
and a test run by hand cannot write into the real pipeline/.

2026-09-07..10-02 some 86 000 lines from tests landed in RUN_EVENTS.jsonl of
finished batches: an agent script handed a path inside a real batch found that
batch by walking up from its argv (runlog lookup rule 3) and appended to it, or
created a journal for a batch that never had one. Pinned here:

  * the walk writes only into an open journal (batch-start, last marker not
    batch-done) - never into a closed batch, never creates a journal;
  * an explicit batch (RUNLOG_BATCH / --batch) that is closed gets its activity
    in RUN_EVENTS.after-close.jsonl, while accounting about the run (usage)
    still lands in the journal, and a stage-start reopens it on purpose;
  * a process descending from a test file writes nothing outside the temp
    dirs, whatever route named the batch.

Everything runs on synthetic batches under a temp tree.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("closed-batch-test-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ["FACTORY_ROOT"] = str(TMP / "root")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)
os.environ.pop("RUNLOG_UNDER_TEST", None)

import runlog  # noqa: E402

CHILD = TMP / "child_script.py"
CHILD.write_text(
    "import sys\n"
    f"sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r})\n"
    "import runlog\n"
    "with runlog.run('video-editor', 'plan'):\n"
    "    pass\n")

_n = [0]


def batch(markers=()):
    """pipeline/<channel>/<id> with the given marker statuses already written."""
    _n[0] += 1
    b = TMP / f"p{_n[0]}" / "pipeline" / "fashion" / f"2026-08-31T2155Z-{_n[0]}"
    (b / "work" / "lisa").mkdir(parents=True)
    for m in markers:
        stage = "video-editor" if m.startswith("stage") else None
        runlog.emit(b, runlog.KIND_MARKER, stage, status=m)
    return b


def lines(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def child(b, env=None, via_argv=True):
    e = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    e.update(env or {})
    argv = [sys.executable, str(CHILD)]
    if via_argv:
        argv.append(str(b / "work" / "lisa" / "plan.json"))
    return subprocess.run(argv, capture_output=True, text=True, env=e, timeout=60)


CLOSED = ("batch-start", "stage-start", "stage-done", "batch-done")


# --------------------------------------------------------------------------

def test_walk_does_not_write_into_a_closed_batch():
    b = batch(CLOSED)
    before = (b / runlog.EVENTS_FILE).read_bytes()
    cp = child(b)
    assert cp.returncode == 0, cp.stderr
    assert (b / runlog.EVENTS_FILE).read_bytes() == before
    assert not (b / runlog.AFTER_CLOSE_FILE).exists()
    assert "CF-0251" in cp.stderr and "closed" in cp.stderr


def test_walk_does_not_create_a_journal():
    b = batch()                                   # looks like a batch, has no journal
    cp = child(b)
    assert cp.returncode == 0, cp.stderr
    assert not (b / runlog.EVENTS_FILE).exists()
    assert not (b / runlog.AFTER_CLOSE_FILE).exists()


def test_walk_still_writes_into_an_open_batch():
    b = batch(("batch-start", "stage-start"))
    cp = child(b)
    assert cp.returncode == 0, cp.stderr
    ev = [e for e in lines(b / runlog.EVENTS_FILE) if e["kind"] == "script"]
    assert [e["status"] for e in ev] == ["start", "done"]


def test_explicit_batch_closed_goes_beside_the_journal():
    b = batch(CLOSED)
    before = (b / runlog.EVENTS_FILE).read_bytes()
    cp = child(b, env={"RUNLOG_BATCH": str(b)}, via_argv=False)
    assert cp.returncode == 0, cp.stderr
    assert (b / runlog.EVENTS_FILE).read_bytes() == before
    after = lines(b / runlog.AFTER_CLOSE_FILE)
    assert [e["status"] for e in after] == ["start", "done"]


def test_accounting_about_a_closed_run_stays_in_the_journal():
    b = batch(CLOSED)
    runlog.emit(b, "usage", "video-editor", params={"tokens": 1})
    assert lines(b / runlog.EVENTS_FILE)[-1]["kind"] == "usage"
    assert not (b / runlog.AFTER_CLOSE_FILE).exists()


def test_stage_start_reopens_on_purpose():
    b = batch(CLOSED + ("stage-start",))
    cp = child(b)                                 # even the walk: the batch is open again
    assert cp.returncode == 0, cp.stderr
    assert [e["status"] for e in lines(b / runlog.EVENTS_FILE) if e["kind"] == "script"] == \
        ["start", "done"]


def test_journal_state_follows_appended_markers():
    b = batch(("batch-start",))
    assert runlog.journal_state(b) == (True, False)
    runlog.emit(b, runlog.KIND_SCRIPT, "x", status="start")
    runlog.emit(b, runlog.KIND_MARKER, None, status="batch-done")
    assert runlog.journal_state(b) == (True, True)
    assert runlog.write_path(b, runlog.KIND_SCRIPT) == b / runlog.AFTER_CLOSE_FILE
    assert runlog.write_path(b, runlog.KIND_MARKER) == b / runlog.EVENTS_FILE
    runlog.emit(b, runlog.KIND_MARKER, "video-editor", status="stage-start")
    assert runlog.journal_state(b) == (True, False)


def test_test_process_cannot_write_outside_temp():
    """The child descends from this test file. With the temp roots narrowed
    to a sibling directory, the batch counts as 'real': nothing is written, by
    the walk or by RUNLOG_BATCH. The same child told it is not under a test
    writes - so the guard, not anything else, held it."""
    b = batch(("batch-start", "stage-start"))
    own_tmp = TMP / "child-tmp"
    own_tmp.mkdir(exist_ok=True)
    before = (b / runlog.EVENTS_FILE).read_bytes()
    for env in ({}, {"RUNLOG_BATCH": str(b)}):
        cp = child(b, env=dict(env, RUNLOG_TEMP_ROOTS=str(own_tmp)))
        assert cp.returncode == 0, cp.stderr
        assert (b / runlog.EVENTS_FILE).read_bytes() == before, env
        assert "test process" in cp.stderr, cp.stderr
    cp = child(b, env={"RUNLOG_TEMP_ROOTS": str(own_tmp), "RUNLOG_UNDER_TEST": "0"})
    assert cp.returncode == 0, cp.stderr
    assert (b / runlog.EVENTS_FILE).read_bytes() != before


def test_system_temp_counts_as_temp():
    """The runners give each file its own TMPDIR while the suite's batch sits
    in the outer temp area - that batch must stay writable."""
    assert runlog._in_temp(TMP)
    assert runlog._in_temp("/tmp/x/pipeline/c/b")


def test_under_test_sees_this_file():
    assert runlog.under_test() is True
    assert os.environ.get("RUNLOG_UNDER_TEST") == "1"


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

#!/usr/bin/env python3
"""CF-0398: a batch runs on `main` of every factory repo, and the code under it
does not move. CF-0479 re-stated "main": the root is clean on `main` or
`release/*`, every agent sits on its pin of `agents.lock.json`, and a root move
that touches only records (tasks/, publish/, the runs table, docs) is no drift.

What is pinned here, on a fake factory built in a temp tree (a root git repo
plus fake `agents/<name>` git repos, and one `agents/` directory that is not a
repo at all) - the real checkout is never read or written:

* `runlog batch-start` exits 2 with one readable line when the root is off
  `main`/`release/*`, an agent is off its lock pin (whatever its branch), an
  agent repo is not in the lock, or a tracked file is modified; untracked files
  and the root's records (pipeline/, rotation/ledger/, tasks/, publish/, docs)
  do not count; a non-git directory is unknown, never refused; the resolved
  pins land in `code_check.lock` and the header;
* `--anyway REASON` starts anyway and the reason lands in the event
  (`code_override`), beside what the check saw (`code_check`);
* a batch outside `<root>/pipeline/` is not checked, and says so;
* `stage-start` / `stage-done` write a moved HEAD as `code_drift` once, and
  never refuse; a root commit touching only records is not drift (CF-0457); the triage counts it as an авария, RUN_SUMMARY prints it;
* `runlog batch-active` answers by exit code - 0 and the directory for an open
  batch, 1 for a closed one, a stale open one is named but not counted, and a
  rebuild is open only while a stage of it is.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("batch-on-main-test-")
STATE = TMP / "state"
os.environ["RUNLOG_STATE_DIR"] = str(STATE)               # never touch ~/.shorts-content-factory
os.environ["RUNLOG_PROJECTS_DIR"] = str(TMP / "none")
os.environ["RUNLOG_TRANSCRIPTS"] = str(TMP / "none")
import runlog   # noqa: E402
import runs_table  # noqa: E402
import summary  # noqa: E402
import triage   # noqa: E402

CLI = [sys.executable, str(ROOT / "scripts" / "runlog")]
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def repo(d):
    d.mkdir(parents=True, exist_ok=True)
    git(d, "init", "-q")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@example.test")
    git(d, "config", "user.name", "t")
    (d / "code.py").write_text("x = 1\n")
    git(d, "add", ".")
    git(d, "commit", "-qm", "c1")
    return d


LOCK = {"agents": {"trend-hunter": {"path": "agents/trend-hunter", "rev": "v1.4"},
                   "video-editor": {"path": "agents/video-editor", "rev": "v1.4"}}}


def factory():
    """A fake root: root repo with tracked pipeline/runs.jsonl, tasks/, ROADMAP.md
    and an agents.lock.json pinning two agent repos to their tag v1.4 (each on
    `main` at that tag), one agents/ directory that is not a repo. Returns
    (root, batch dir)."""
    _n[0] += 1
    root = TMP / f"f{_n[0]}" / "root"
    repo(root)
    (root / "pipeline").mkdir()
    (root / "pipeline" / "runs.jsonl").write_text("")
    (root / "tasks").mkdir()
    (root / "tasks" / "CF-0001.md").write_text("status: open\n")
    (root / "ROADMAP.md").write_text("# Roadmap\n")
    (root / "agents.lock.json").write_text(json.dumps(LOCK, indent=2) + "\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "runs table, tasks, lock")
    for a in ("video-editor", "trend-hunter"):
        git(repo(root / "agents" / a), "tag", "v1.4")
    (root / "agents" / "analyst").mkdir()
    b = root / "pipeline" / "chan" / "2026-09-26T1200Z"
    b.mkdir(parents=True)
    return root, b


def cli(root, *args):
    env = dict(os.environ, FACTORY_ROOT=str(root), RUNLOG_STATE_DIR=str(STATE),
               RUNLOG_TRANSCRIPTS=str(TMP / "none"), RUNLOG_PROJECTS_DIR=str(TMP / "none"))
    env.pop("RUNLOG_BATCH", None)
    env.pop("RUNLOG_PARENT", None)
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=env)


def markers(b):
    return [e for e in runlog.read_events(b) if e.get("kind") == "marker"]


def stop(b):
    runlog.sibling("sampler").stop(b)


# ---------------------------------------------------------------- batch-start

def test_clean_root_and_agents_on_their_pins_start_and_record_the_check():
    root, b = factory()
    th = root / "agents" / "trend-hunter"
    git(th, "checkout", "-q", "--detach", "v1.4")               # detached on the pin: fine
    (root / "untracked.tmp").write_text("cache")               # untracked never counts
    (root / "pipeline" / "runs.jsonl").write_text("{}\n")      # a run record, not code
    (root / "tasks" / "CF-0001.md").write_text("status: closed\n")   # records, not code
    (root / "ROADMAP.md").write_text("# Roadmap, edited\n")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    ev = markers(b)[0]
    chk = ev[runlog.CODE_CHECK_KEY]
    assert chk["checked"] is True and chk["problems"] == [], chk
    assert chk["branches"] == {"root": "main", "agents/analyst": None,
                               "agents/trend-hunter": None, "agents/video-editor": "main"}
    pins = {"agents/trend-hunter": {"rev": "v1.4", "sha": git(th, "rev-parse", "v1.4")},
            "agents/video-editor": {"rev": "v1.4",
                                    "sha": git(root / "agents" / "video-editor", "rev-parse", "v1.4")}}
    assert chk[runlog.CODE_LOCK_KEY] == pins, chk
    assert ev["header"][runlog.HEADER_LOCK_KEY] == pins      # the runs table reads it here
    assert runlog.CODE_OVERRIDE_KEY not in ev


def test_the_runs_row_carries_the_agents_pins():
    pins = {"agents/trend-hunter": {"rev": "v1.4", "sha": "a" * 40},
            "agents/video-editor": {"rev": "v1.4", "sha": "b" * 40}}
    row = runs_table._agents_pins(pins)
    assert row == {"agents/trend-hunter": "v1.4@aaaaaaa", "agents/video-editor": "v1.4@bbbbbbb"}
    assert runs_table._agents_cell(row) == "agents v1.4"
    row["agents/video-editor"] = "main@ccccccc"
    assert runs_table._agents_cell(row) == \
        "agents trend-hunter v1.4@aaaaaaa, video-editor main@ccccccc"
    assert runs_table._agents_pins(None) is None and runs_table._agents_cell(None) is None


def test_refused_on_a_root_branch_that_is_neither_main_nor_release():
    root, b = factory()
    git(root, "checkout", "-qb", "work/CF-0999")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    assert cp.returncode == 2, cp.stdout
    assert "batch-start refused (CF-0479)" in cp.stderr
    assert "root: on branch 'work/CF-0999', not main or release/*" in cp.stderr
    assert "--anyway REASON" in cp.stderr
    assert markers(b) == []                                    # nothing was written


def test_a_release_branch_of_the_root_carries_a_batch():
    root, b = factory()
    git(root, "checkout", "-qb", "release/1.5")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    assert markers(b)[0][runlog.CODE_CHECK_KEY]["branches"]["root"] == "release/1.5"


def test_refused_when_an_agent_is_off_its_pin_whatever_its_branch():
    root, b = factory()
    ve = root / "agents" / "video-editor"
    git(ve, "commit", "-q", "--allow-empty", "-m", "work of the next version on main")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    assert cp.returncode == 2, cp.stdout
    head, pin = git(ve, "rev-parse", "HEAD"), git(ve, "rev-parse", "v1.4")
    assert (f"agents/video-editor: HEAD {head[:12]} (main) is not v1.4 {pin[:12]} "
            f"(agents.lock.json pins v1.4; `scripts/agents sync`)") in cp.stderr, cp.stderr
    lock = json.loads((root / "agents.lock.json").read_text())
    lock["agents"]["video-editor"]["rev"] = "main"            # pinned to the branch: fine
    (root / "agents.lock.json").write_text(json.dumps(lock))
    git(root, "commit", "-qam", "pin video-editor to main")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    assert markers(b)[0][runlog.CODE_CHECK_KEY][runlog.CODE_LOCK_KEY]["agents/video-editor"] \
        == {"rev": "main", "sha": head}


def test_refused_on_a_modified_tracked_file_of_the_root():
    root, b = factory()
    (root / "code.py").write_text("x = 2\n")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    assert cp.returncode == 2
    assert "root: 1 uncommitted tracked file(s) (code.py)" in cp.stderr


def test_an_agent_repo_the_lock_does_not_pin_is_refused_and_so_is_no_lock():
    root, b = factory()
    repo(root / "agents" / "analyst")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    assert cp.returncode == 2
    assert "agents/analyst: a git repo agents.lock.json does not pin" in cp.stderr, cp.stderr
    root, b = factory()
    git(root, "rm", "-q", "agents.lock.json")
    git(root, "commit", "-qm", "no lock")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    assert cp.returncode == 2
    assert ("no agents.lock.json in the root - the agents' revisions cannot be vouched for "
            "(agents/trend-hunter, agents/video-editor)") in cp.stderr, cp.stderr


def test_a_staged_change_is_dirty_too():
    root, b = factory()
    (root / "agents" / "video-editor" / "new.py").write_text("y = 1\n")
    git(root / "agents" / "video-editor", "add", "new.py")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    assert cp.returncode == 2 and "agents/video-editor: 1 uncommitted tracked file(s) (new.py)" \
        in cp.stderr, cp.stderr


def test_anyway_starts_and_writes_the_reason_beside_what_it_went_past():
    root, b = factory()
    git(root, "checkout", "-qb", "work/CF-0999")
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render", "--anyway", "replay of 1722Z")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    ev = markers(b)[0]
    ov = ev[runlog.CODE_OVERRIDE_KEY]
    assert ov["reason"] == "replay of 1722Z"
    assert ov["was"] == ["root: on branch 'work/CF-0999', not main or release/*"]
    line = runlog.drift_headline([], runlog.code_override_of(runlog.read_events(b)))
    assert "started off a clean main" in line and "replay of 1722Z" in line


def test_a_batch_outside_the_factory_pipeline_is_not_checked_and_says_so():
    root, _ = factory()
    git(root, "checkout", "-qb", "work/CF-0999")
    b = TMP / "elsewhere" / "pipeline" / "chan" / "2026-09-26T1300Z"
    b.mkdir(parents=True)
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    chk = markers(b)[0][runlog.CODE_CHECK_KEY]
    assert chk["checked"] is False and "outside" in chk["why"], chk


def test_a_root_that_is_no_git_repo_is_unknown_not_refused():
    _n[0] += 1
    root = TMP / f"plain{_n[0]}"
    b = root / "pipeline" / "chan" / "2026-09-26T1400Z"
    b.mkdir(parents=True)
    cp = cli(root, "batch-start", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    assert markers(b)[0][runlog.CODE_CHECK_KEY]["problems"] == []


# ------------------------------------------------------------------ code drift

def test_a_moved_head_is_written_once_as_code_drift_and_nothing_is_refused():
    root, b = factory()
    assert cli(root, "batch-start", "--batch", str(b), "--no-render").returncode == 0
    ve = root / "agents" / "video-editor"
    was = git(ve, "rev-parse", "HEAD")
    assert cli(root, "stage-start", "trend-hunter", "--batch", str(b), "--no-render").returncode == 0
    (root / "pipeline" / "runs.jsonl").write_text("{}\n")   # the run's own record: not drift
    git(ve, "commit", "-q", "--allow-empty", "-m", "moved under the run")
    now = git(ve, "rev-parse", "HEAD")
    cp = cli(root, "stage-done", "trend-hunter", "--batch", str(b), "--no-render")
    assert cp.returncode == 0 and "code drift (CF-0398)" in cp.stderr, cp.stderr
    assert cli(root, "stage-start", "video-editor", "--batch", str(b), "--no-render").returncode == 0
    stop(b)
    ms = markers(b)
    assert runlog.CODE_DRIFT_KEY not in ms[1]                          # stage-start: nothing moved
    assert ms[2][runlog.CODE_DRIFT_KEY] == [{"repo": "agents/video-editor", "was": was, "now": now}]
    assert runlog.CODE_DRIFT_KEY not in ms[3]                          # the same move, once
    rows = runlog.drift_rows(runlog.read_events(b))
    assert [(r["repo"], r["marker"], r["stage"]) for r in rows] == \
        [("agents/video-editor", "stage-done", "trend-hunter")]


def test_a_root_commit_touching_only_records_is_no_drift_but_code_is():
    """CF-0457: the auto-dev driver files task notes, the publisher writes its
    notes, the docs move - none of that is the code under the run."""
    root, b = factory()
    assert cli(root, "batch-start", "--batch", str(b), "--no-render").returncode == 0
    was = git(root, "rev-parse", "HEAD")
    (root / "tasks" / "CF-0002.md").write_text("status: open\n")
    (root / "ROADMAP.md").write_text("# Roadmap 2\n")
    (root / "publish" / "chan").mkdir(parents=True)
    (root / "publish" / "chan" / "note.md").write_text("note\n")
    (root / "pipeline" / "RUNS.md").write_text("# Runs\n")
    git(root, "add", "tasks", "ROADMAP.md", "publish", "pipeline/RUNS.md")
    git(root, "commit", "-qm", "tasks, roadmap, publish note, runs table")
    cp = cli(root, "stage-start", "trend-hunter", "--batch", str(b), "--no-render")
    assert cp.returncode == 0 and "code drift" not in cp.stderr, cp.stderr
    (root / "code.py").write_text("x = 3\n")
    git(root, "commit", "-qam", "code under the run")
    now = git(root, "rev-parse", "HEAD")
    cp = cli(root, "stage-done", "trend-hunter", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0 and "code drift (CF-0398)" in cp.stderr, cp.stderr
    ms = markers(b)
    assert runlog.CODE_DRIFT_KEY not in ms[1]
    assert ms[2][runlog.CODE_DRIFT_KEY] == [{"repo": "root", "was": was, "now": now}]
    assert runlog.code_paths_moved(root, was, now) == ["code.py"]


def test_triage_counts_code_drift_as_an_avaria_and_the_summary_prints_it():
    evs = [{"ts": "2026-09-26T12:00:00.000Z", "kind": "marker", "status": "batch-start",
            "stage": None, "header": {"git": {"root": {"commit": "a" * 40}}}},
           {"ts": "2026-09-26T12:01:00.000Z", "kind": "marker", "status": "stage-start",
            "stage": "video-editor",
            "code_drift": [{"repo": "root", "was": "a" * 40, "now": "b" * 40}]},
           {"ts": "2026-09-26T12:02:00.000Z", "kind": "marker", "status": "stage-done",
            "stage": "video-editor",
            "code_drift": [{"repo": "root", "was": "b" * 40, "now": "c" * 40}]},
           {"ts": "2026-09-26T12:03:00.000Z", "kind": "marker", "status": "batch-done",
            "stage": None}]
    _n[0] += 1
    b = TMP / f"tri{_n[0]}" / "chan" / "2026-09-26T1200Z"
    b.mkdir(parents=True)
    res = triage.triage(b, events=evs, config={}, ledger={"rules": {}}, gate_results=[])
    drift = [i for i in res["incidents"] if i["kind"] == triage.CODE_DRIFT]
    assert len(drift) == 1 and drift[0]["key"] == "code_drift:root" and drift[0]["count"] == 2
    assert triage.KIND_LABEL[triage.CODE_DRIFT]
    line = runlog.drift_headline(runlog.drift_rows(evs))
    assert line.startswith("**code drift: the code moved 2 time(s) under the run**")
    assert "root aaaaaaa -> bbbbbbb at stage-start video-editor" in line
    text = summary.render(events=evs)
    assert "code drift: the code moved 2 time(s)" in text


def test_the_summary_is_silent_while_the_code_stood_still():
    assert runlog.drift_headline([]) is None


# ---------------------------------------------------------------- batch-active

def _events(b, *statuses, ts="2026-09-26T12:00:00.000Z", stage="video-editor"):
    b.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": ts, "kind": "marker", "status": s,
                         "stage": None if s.startswith("batch") else stage}) for s in statuses]
    (b / runlog.EVENTS_FILE).write_text("\n".join(lines) + "\n")
    return b


def test_batch_active_on_an_open_and_a_closed_batch():
    _n[0] += 1
    root = TMP / f"act{_n[0]}"
    now = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    closed = _events(root / "pipeline" / "chan" / "2026-09-26T0100Z", "batch-start", "batch-done")
    assert runlog.open_batches(root, now=now) == []
    live = _events(root / "pipeline" / "chan" / "2026-09-26T1200Z", "batch-start", "stage-start")
    rows = runlog.open_batches(root, now=now)
    assert [(d, fresh) for d, _, fresh in rows] == [(live, True)]
    assert closed not in [d for d, _, _ in rows]


def test_batch_active_names_a_stale_open_batch_but_does_not_count_it():
    _n[0] += 1
    root = TMP / f"stale{_n[0]}"
    old = _events(root / "pipeline" / "chan" / "2026-08-31T2155Z", "batch-start",
                  ts="2026-08-31T21:55:00.000Z")
    now = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    rows = runlog.open_batches(root, now=now)
    assert [(d, fresh) for d, _, fresh in rows] == [(old, False)]
    assert runlog.sibling("sampler").MAX_HOURS == 24          # the bound is the sampler's cap
    recent = now - timedelta(hours=runlog.sibling("sampler").MAX_HOURS - 1)
    _events(old, "batch-start", ts=runlog.now_z(recent.timestamp()))
    assert [fresh for _, _, fresh in runlog.open_batches(root, now=now)] == [True]


def test_a_rebuild_is_open_only_while_a_stage_of_it_is_and_backfill_never():
    _n[0] += 1
    root = TMP / f"reb{_n[0]}"
    now = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    reb = _events(root / "pipeline" / "rebuilds" / "2026-09-26T1200Z", "batch-start",
                  "stage-start", "stage-done")
    _events(root / "pipeline" / "backfill" / "2026-09-26T1200Z", "batch-start")
    assert runlog.open_batches(root, now=now) == []
    _events(reb, "batch-start", "stage-start", "stage-done", "stage-start")
    assert [d for d, _, _ in runlog.open_batches(root, now=now)] == [reb]


def test_batch_active_cli_exit_codes():
    _n[0] += 1
    root = TMP / f"cli{_n[0]}"
    (root / "pipeline").mkdir(parents=True)
    cp = cli(root, "batch-active")
    assert cp.returncode == 1 and cp.stdout == "" and "no open batch" in cp.stderr
    live = _events(root / "pipeline" / "chan" / "2026-09-26T1200Z", "batch-start",
                   ts=runlog.now_z())
    _events(root / "pipeline" / "chan" / "2026-08-01T0000Z", "batch-start",
            ts="2026-08-01T00:00:00.000Z")
    cp = cli(root, "batch-active")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip().splitlines() == [str(live.resolve())]
    assert "stale, not counted" in cp.stderr and "2026-08-01T0000Z" in cp.stderr
    cp = cli(root, "batch-active", "--root", str(root), "--hours", "0.0001")
    assert cp.returncode in (0, 1)                             # --hours is honoured without error


# ------------------------------------------- CF-0401: a rebuild with no markers

def _script_events(b, *events):
    """Script events only - what a rebuild since 2026-09-23T1053Z writes - with
    a sampler sample after each (samples are not work)."""
    b.mkdir(parents=True, exist_ok=True)
    lines = []
    for ts, status, sid, pid in events:
        lines.append(json.dumps({"ts": runlog.now_z(ts.timestamp()), "machine": runlog.machine_id(),
                                 "kind": "script", "stage": "video-editor", "step": "render",
                                 "status": status, "pid": pid, "id": sid, "parent": None}))
        lines.append(json.dumps({"ts": runlog.now_z(ts.timestamp()), "kind": "sample",
                                 "params": {}}))
    (b / runlog.EVENTS_FILE).write_text("\n".join(lines) + "\n")
    return b


def test_a_working_rebuild_without_markers_is_open():
    """CF-0401: no batch-start, no batch-done, no stage marker - only the events of
    its scripts. It is open while it wrote work within sampler.IDLE_MINUTES."""
    _n[0] += 1
    root = TMP / f"reb-nomark{_n[0]}"
    now = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    idle = timedelta(minutes=runlog.sibling("sampler").IDLE_MINUTES)
    assert idle == timedelta(minutes=10)                  # the sampler's own "run went idle"
    reb = _script_events(root / "pipeline" / "rebuilds" / "2026-09-26T1200Z",
                         (now - idle + timedelta(minutes=1), "start", "a1", 999999),
                         (now - idle + timedelta(minutes=2), "done", "a1", 999999))
    rows = runlog.open_batches(root, now=now)
    assert [(d, fresh) for d, _, fresh in rows] == [(reb, True)]
    # the sampler's samples are not work: a rebuild idle past the bound is closed
    assert runlog.open_batches(root, now=now + idle) == []
    # a markerless dir under a channel is not a rebuild - a batch still needs batch-start
    _script_events(root / "pipeline" / "chan" / "2026-09-26T1200Z",
                   (now, "start", "b1", 999999))
    assert [d for d, _, _ in runlog.open_batches(root, now=now)] == [reb]


def test_a_rebuild_with_a_live_long_script_is_open_past_the_idle_bound():
    """A render may be silent longer than IDLE_MINUTES; its live process holds the
    rebuild open. A script that ended, a reused (younger) pid or a dead pid do not."""
    _n[0] += 1
    root = TMP / f"reb-live{_n[0]}"
    now = datetime.now(timezone.utc)
    started = now - timedelta(minutes=30)
    reb = root / "pipeline" / "rebuilds" / "2026-09-26T1200Z"
    me = os.getpid()
    # CF-0531: patched by hand, not by pytest's monkeypatch - the house harness
    # calls every test with no arguments (before CF-0531 this one sat below the
    # `__main__` block and never ran in tests/run_tests.py).
    real_age = runlog._process_age_s
    try:
        _rebuild_held_open_by_a_live_script(root, now, started, reb, me)
    finally:
        runlog._process_age_s = real_age


def _rebuild_held_open_by_a_live_script(root, now, started, reb, me):
    runlog._process_age_s = lambda pid: 3600
    _script_events(reb, (started, "start", "a1", me))
    assert [d for d, _, _ in runlog.open_batches(root, now=now)] == [reb]
    runlog._process_age_s = lambda pid: 10       # pid reused since
    assert runlog.open_batches(root, now=now) == []
    runlog._process_age_s = lambda pid: 3600
    _script_events(reb, (started, "start", "a1", me), (started, "failed", "a1", me))
    assert runlog.open_batches(root, now=now) == []                      # it ended
    gone = subprocess.Popen(["true"])
    gone.wait()
    _script_events(reb, (started, "start", "a1", gone.pid))
    assert runlog.open_batches(root, now=now) == []                      # its process is gone


def test_batch_active_cli_sees_a_rebuild_without_markers():
    _n[0] += 1
    root = TMP / f"reb-cli{_n[0]}"
    reb = _script_events(root / "pipeline" / "rebuilds" / "2026-09-26T1200Z",
                         (datetime.now(timezone.utc), "start", "a1", 999999))
    cp = cli(root, "batch-active")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip().splitlines() == [str(reb.resolve())]


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

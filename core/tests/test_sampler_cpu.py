#!/usr/bin/env python3
"""CF-0167: the sampler must measure CPU, and must not write a failed probe as a zero.

The first instrumented run (2026-09-09T2031Z) wrote `cpu_total_pct: 0.0`,
`cpu_pipeline_pct: 0.0` and `procs: []` in all 3007 samples: `_ps()` returned
an empty list both when `ps` had listed no process and when `ps` could not run
at all, and `sample()` divided that emptiness by the core count into a real
looking 0 %. Section 6 of RUN_SUMMARY.md then had to call every stage `mixed`.

Two things are nailed down here:
  * a real busy process of the run gives a non-zero `cpu_pipeline_pct` and a
    filled `rss_mb` - both when it is the root of an open `script` event and
    when it is only recognised by the batch directory in its argv;
  * a probe that fails writes `null` plus its name in `probe_errors`, never 0.

Runs in a few seconds: two short busy children, no batch, no pipeline.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("sampler-cpu-test-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import runlog  # noqa: E402
import sampler  # noqa: E402
import summary  # noqa: E402

BURN_S = 6.0
BURN = f"import time\nt = time.time()\nwhile time.time() - t < {BURN_S}: pass\n"


def batch(name):
    b = TMP / name
    b.mkdir(parents=True, exist_ok=True)
    return b


def burn(*extra_argv):
    return subprocess.Popen([sys.executable, "-c", BURN, *[str(a) for a in extra_argv]],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def measure(b):
    """Two samples 0.6 s apart; the second one is measured over a real interval."""
    sampler.sample(b)
    time.sleep(0.6)
    return sampler.sample(b)[0]


def script_event(b, pid):
    runlog.emit(b, runlog.KIND_SCRIPT, "video-editor", step="render", video="burner",
                status=runlog.ST_START, event_id="c0ffee000001", params={"pid": pid})
    # runlog stamps its own pid on the event; the sampler needs the busy child's
    events = b / runlog.EVENTS_FILE
    text = events.read_text().replace(f'"pid": {os.getpid()}', f'"pid": {pid}')
    events.write_text(text)


# --------------------------------------------------------------------------
# a live measurement
# --------------------------------------------------------------------------

def test_a_busy_process_of_the_run_gives_non_zero_cpu_and_a_filled_rss():
    b = batch("by-script-event")
    kid = burn()
    try:
        script_event(b, kid.pid)
        p = measure(b)
        assert p["procs"], f"the run's own busy process was not seen: {p}"
        assert kid.pid in [q["pid"] for q in p["procs"]], p["procs"]
        assert p["cpu_pipeline_pct"] > 0.0, f"a fully busy core reported as {p['cpu_pipeline_pct']}"
        assert p["cpu_total_pct"] is not None and p["cpu_total_pct"] > 0.0, p["cpu_total_pct"]
        for q in p["procs"]:
            assert q["rss_mb"] and q["rss_mb"] > 0.0, f"no rss on {q}"
        assert p["probe_errors"] is None or "libproc" not in p["probe_errors"], p["probe_errors"]
        # one busy process on a multi-core machine: a share of all cores, not of one
        assert 0.0 < p["cpu_pipeline_pct"] <= 100.0
    finally:
        kid.kill()
        kid.wait()


def test_a_process_is_also_recognised_by_the_batch_directory_in_its_argv():
    b = batch("by-argv")
    kid = burn(b)                                   # no script event at all
    try:
        p = measure(b)
        assert [q for q in p["procs"] or [] if q["pid"] == kid.pid], \
            f"argv naming the batch did not match: {p['procs']}"
        assert p["cpu_pipeline_pct"] > 0.0, p
    finally:
        kid.kill()
        kid.wait()


def test_the_sampler_daemon_writes_live_numbers_end_to_end():
    b = batch("daemon")
    kid = burn(b)
    try:
        pid = sampler.start(b, interval=1)
        assert pid, "sampler did not start"
        deadline = time.monotonic() + 8
        rows = []
        while time.monotonic() < deadline:
            rows = [e for e in runlog.read_events(b) if e.get("kind") == sampler.KIND_SAMPLE]
            if len(rows) >= 2:
                break
            time.sleep(0.2)
        assert len(rows) >= 2, f"only {len(rows)} samples in 8 s"
        p = rows[-1]["params"]
        assert p["cpu_total_pct"] > 0.0 and p["cpu_pipeline_pct"] > 0.0, p
        assert p["procs"] and all(q["rss_mb"] > 0.0 for q in p["procs"]), p["procs"]
    finally:
        sampler.stop(b)
        kid.kill()
        kid.wait()


# --------------------------------------------------------------------------
# a failed probe is not a zero
# --------------------------------------------------------------------------

def test_a_process_table_that_cannot_be_read_is_null_and_named_not_zero():
    b = batch("no-proc-table")
    saved = sampler._libproc_rows, sampler._ps, sampler._cpu_total_darwin, sampler._cpu_total_linux
    sampler._libproc_rows = lambda: None
    sampler._ps = lambda: None
    sampler._cpu_total_darwin = lambda: None
    sampler._cpu_total_linux = lambda: None
    try:
        p, _, _ = sampler.sample(b)
    finally:
        (sampler._libproc_rows, sampler._ps,
         sampler._cpu_total_darwin, sampler._cpu_total_linux) = saved
    assert p["cpu_pipeline_pct"] is None, f"a failed probe was written as {p['cpu_pipeline_pct']}"
    assert p["cpu_total_pct"] is None, f"a failed probe was written as {p['cpu_total_pct']}"
    assert p["procs"] is None, p["procs"]
    assert "ps" in p["probe_errors"] and "cpu_total" in p["probe_errors"], p["probe_errors"]
    assert p["cpu_cores"] >= 1 and p["interval_s"] == sampler.INTERVAL_S


def test_ps_that_prints_nothing_usable_is_a_failure_not_an_empty_machine():
    saved = sampler._sh
    sampler._sh = lambda cmd, timeout=4: None                  # ps could not run at all
    try:
        assert sampler._ps() is None
        sampler._sh = lambda cmd, timeout=4: "only-one-column\nand-another\n"
        assert sampler._ps() is None, "unparsable ps output must not look like an empty machine"
        sampler._sh = lambda cmd, timeout=4: "  7 1 12.5 20480 /usr/bin/ffmpeg -i a.mp4\n"
        rows = sampler._ps()
        assert rows == [(7, 1, 12.5, 20.0, "ffmpeg", "/usr/bin/ffmpeg -i a.mp4")], rows
    finally:
        sampler._sh = saved


def test_a_missing_cpu_reading_is_not_read_as_waiting():
    # CF-0167: 0 % means idle, null means "not measured" - only the first is `waiting`
    assert summary.verdict(0.0, 0.0) == "waiting"
    assert summary.verdict(None, 5.0) != "waiting", "a null CPU mean was taken for an idle one"
    assert summary.verdict(None, None) == "no samples"
    assert summary.verdict(None, summary.HW_BOUND_GPU_PCT) == "hardware-bound"


# --------------------------------------------------------------------------
# CF-0339: the daemon closes itself
# --------------------------------------------------------------------------

def a_daemon(name, idle_minutes, interval=0.5, nested=False):
    """A batch with a batch-start event and a live daemon over it. Returns (dir, pid)."""
    b = batch(f"{name}/pipeline/ch/2026-09-24T0000Z") if nested else batch(name)
    runlog.emit(b, runlog.KIND_MARKER, None, status=runlog.M_BATCH_START)
    pid = sampler.start(b, interval=interval, idle_minutes=idle_minutes)
    assert pid, "sampler did not start"
    return b, pid


def wait_for_a_sample(b, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(e.get("kind") == sampler.KIND_SAMPLE for e in runlog.read_events(b)):
            return True
        time.sleep(0.1)
    return False


def wait_gone(pid, timeout=30):
    deadline = time.monotonic() + timeout
    while sampler.pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not sampler.pid_alive(pid)


def test_a_run_with_no_process_and_no_event_of_its_own_stops_its_daemon():
    """The CF-0339 leak in one check. 140 daemons survived a day of test runs
    because nothing they watch for had happened: the temp trees were never
    removed, so each one kept a directory that existed and a pid-file that named
    it, and sampled an idle machine until its 24 h cap. An idle run is over."""
    b, pid = a_daemon("idle", idle_minutes=0.05)          # 3 s of idle is enough
    assert wait_for_a_sample(b), "the daemon wrote no sample at all"
    assert wait_gone(pid), "the daemon outlived a run with no process and no event"
    assert sampler.running(b) is None
    assert not sampler.pid_file(b).exists(), "the pid-file of a finished daemon stayed"
    rows = [e for e in runlog.read_events(b) if e.get("kind") == sampler.KIND_SAMPLE]
    assert rows[-1]["params"].get("idle_exit") is True, rows[-1]["params"]
    assert not any(e["params"].get("idle_exit") for e in rows[:-1]), "every sample says it left"


def test_a_daemon_of_a_busy_run_is_not_cut_short_by_the_idle_rule():
    """The other side of it: the run whose process is alive keeps its sampler,
    which is the whole point of the daemon (CF-0108)."""
    b, pid = a_daemon("idle-busy", idle_minutes=0.03)     # 1.8 s
    kid = burn(b)                                        # argv names the batch: a process of the run
    try:
        time.sleep(3.0)
        assert sampler.pid_alive(pid), "the daemon left a run whose own process was busy"
    finally:
        kid.kill()
        kid.wait()
    assert wait_gone(pid), "and it goes once nothing of the run is left"


def test_a_wiped_batch_stops_its_daemon_and_is_not_re_created():
    """What a test teardown does. runlog.emit() creates the directories it needs,
    so a daemon that emits into its own deleted batch resurrects it and becomes
    immortal - the sample of an interval in which the batch died is dropped."""
    b, pid = a_daemon("wiped", idle_minutes=0, nested=True)
    root = TMP / "wiped"
    assert wait_for_a_sample(b), "the daemon wrote no sample at all"
    shutil.rmtree(root, ignore_errors=True)
    assert wait_gone(pid), "the daemon outlived its batch directory"
    assert not root.exists(), "the daemon re-created the batch it had been writing into"


def test_an_events_file_replaced_under_the_daemon_stops_it():
    """A temp tree wiped and a new run started in its place: same path, another
    file. The daemon follows a file, not a name."""
    b, pid = a_daemon("events-replaced", idle_minutes=0)
    assert wait_for_a_sample(b), "the daemon wrote no sample at all"
    ev = runlog.events_path(b)
    ev.unlink()
    ev.write_text("")                                    # another inode under the same name
    assert wait_gone(pid), "the daemon kept writing into a file that is not its run's"


def test_a_rebuild_closes_its_sampler_on_its_last_stage_done():
    """CF-0339: `pipeline/rebuilds/<ts>` is not a batch (CF-0330, CF-0350), so no
    batch-done marker ever closes it - the rebuild of 2026-09-23T0725Z left its
    daemon appending to a finished run for a day. Its stages close it instead."""
    rb = batch("root/pipeline/rebuilds/2026-09-23T0725Z")
    assert runlog.not_a_batch(rb) and not runlog.not_a_batch(TMP / "root/pipeline/ch/b1")
    runlog.marker(runlog.M_BATCH_START, batch_dir=rb, strict=False)
    pid = sampler.running(rb)
    assert pid, "no sampler over the rebuild"
    runlog.marker(runlog.M_STAGE_START, "video-editor", batch_dir=rb, strict=False)
    runlog.marker(runlog.M_STAGE_DONE, "video-editor", batch_dir=rb, strict=False)
    assert wait_gone(pid), "the rebuild left its sampler running"
    assert sampler.running(rb) is None and not sampler.pid_file(rb).exists()


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    t0 = time.monotonic()
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    for pf in TMP.glob("*/RUN_SAMPLER.pid"):
        sampler.stop(pf.parent)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed ({time.monotonic() - t0:.1f}s)")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""CF-0316: an operation that goes quiet is taken down, the run is not.

The incident: on `example-film/2026-09-19T0116Z` the event
`footage-indexer/index PEiDNOQ_0ms start` was followed by 28h30m40s of nothing,
inside a binary call, with nobody being asked anything. The task asks for four
things and this file checks all four:

1. the ceiling lives in the common layer that launches child calls
   (`runlog.run_child`) - and no call goes out of it without one;
2. the ceiling is the one CF-0112 measured, recalculated for CF-0331 - the
   numbers are pinned here so they cannot be quietly loosened;
3. a taken-down operation carries an outcome code and a line of statistics that
   the post-run triage reads as an авария (CF-0319), not as a funnel loss;
4. the seam itself: a silent operation is killed, the stage goes on to the next
   source, and an honestly long operation is **not** killed.

Point 4 is the one that costs something to get right. A watchdog on duration
kills honest work - 52m40s on one source is normal in this stage - so the
watchdog times *silence*, and the two checks that matter are the pair:
`test_a_silent_operation_is_taken_down` and
`test_an_honestly_long_operation_that_keeps_writing_events_is_spared`, where the
second runs six times longer than its own ceiling and survives.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("watchdog-test-")
# The markers of a batch update the tracked runs table, so this file gets a
# factory root of its own - a test writes into a temp tree, never into the repo.
FAKE_ROOT = TMP / "root"
(FAKE_ROOT / "pipeline").mkdir(parents=True)
os.environ["FACTORY_ROOT"] = str(FAKE_ROOT)
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ["RUNLOG_PROJECTS_DIR"] = str(TMP / "projects")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import funnel      # noqa: E402
import runlog      # noqa: E402
import summary     # noqa: E402
import watchdog    # noqa: E402

# What `scripts/watchdog_threshold.py` printed on the three frozen runs CF-0112
# measured (36 honest `index_footage.py` operations, up to 52m40s each).
MEASURED_SILENCE_MAX_S = 209.5
MEASURED_SILENCE_P90_S = 78.7
# CF-0112's own level-1 maxima, and CF-0331's factor over `shot-full-frame`.
MEASURED_BOUNDED_CALL_MAX_S = 111.3        # shot-split-probe
MEASURED_DOWNLOAD_MAX_S = 494.3            # yt-dlp on the 2 GB source
MEASURED_SCAN_RATIO_MAX = 0.333            # seconds of scan per second of source
CHANNEL_DURATION_CEILING_S = 3600.0        # ingest_batch.duration_ceiling default
FULL_FRAME_SPEEDUP = 5.24                  # CF-0331
INCIDENT_SILENCE_S = 28 * 3600 + 30 * 60 + 40


def batch_dir():
    """An empty batch directory with a journal in it."""
    batch_dir._n = getattr(batch_dir, "_n", 0) + 1
    b = FAKE_ROOT / "pipeline" / "example-film" / f"2026-09-24T{batch_dir._n:04d}Z"
    b.mkdir(parents=True)
    (b / runlog.EVENTS_FILE).write_text("", encoding="utf-8")
    return b


def events_of(b):
    return runlog.read_events(b)


def fast_poll():
    """The watchdog re-reads silence every POLL_S; a test cannot wait 5 s."""
    watchdog.POLL_S = 0.05
    return watchdog.POLL_S


# CF-0666: the honest child's numbers. Under load ~46 the old pair (a 0.9 s
# ceiling, an event every 0.3 s from six 0.3 s sleeps) went red as "killed
# honest work": the ceiling counts from the launch, and a Python start plus the
# runlog import alone took longer than 0.9 s. The ceiling now outlasts a
# loaded start the way CF-0649 sized the sampler test's (4 s at load 10-20,
# here twice that for load ~46), the child talks every HONEST_EVERY_S - about
# 25x inside the ceiling - and goes on talking until it has outlived the
# ceiling by half again, counted from its own first event, so a slow start
# cannot make it finish "too fast to prove anything".
HONEST_CEILING_S = 8.0
HONEST_EVERY_S = 0.3


def live_child_script():
    """A child that behaves like an honest `index_footage.py`: long, and talking.
    argv[1] - for how many seconds it keeps talking, from its first event."""
    p = TMP / "live_child.py"
    if not p.exists():
        p.write_text(
            "import sys, time\n"
            f"sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r})\n"
            "import runlog\n"
            "talk_for = float(sys.argv[1])\n"
            "with runlog.run('footage-indexer', step='index'):\n"
            "    t0 = time.monotonic()\n"
            "    i = 0\n"
            "    while time.monotonic() - t0 < talk_for:\n"
            "        with runlog.child('ffmpeg', argv=['ffmpeg', str(i)]) as fr:\n"
            f"            time.sleep({HONEST_EVERY_S})\n"
            "            fr['rc'] = 0\n"
            "        i += 1\n", encoding="utf-8")
    return p


def sampler_only_script():
    """A child that writes `sample` events and nothing else - CF-0339's trap."""
    p = TMP / "sampler_only.py"
    if not p.exists():
        p.write_text(
            "import sys, time\n"
            f"sys.path.insert(0, {str(ROOT / 'shared' / 'runlog')!r})\n"
            "import runlog\n"
            "for i in range(600):\n"            # 60 s of samples: far past any ceiling
            "    runlog.emit(None, 'sample', 'footage-indexer', status=None)\n"
            "    time.sleep(0.1)\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# 2. the threshold is measured, not invented (task item 2)
# --------------------------------------------------------------------------

def test_every_ceiling_clears_the_measured_worst_case():
    # one call bounded by a shot: CF-0112's worst x 3
    assert watchdog.SHOT_CALL_CEILING_S >= MEASURED_BOUNDED_CALL_MAX_S * 3, "CF-0316/CF-0112"
    assert watchdog.SHOT_CALL_CEILING_S < MEASURED_BOUNDED_CALL_MAX_S * 6, "too loose to fire"
    # a download
    assert watchdog.DOWNLOAD_CEILING_S >= MEASURED_DOWNLOAD_MAX_S * 3, "CF-0316/CF-0112"
    # a whole-file scan is a ratio, never an absolute number: 1262 s on a 2h14m
    # source was honest work, and any flat ceiling below it would have killed it
    assert watchdog.scan_ceiling(8019) >= 1262, "CF-0316: the honest 1262 s scan must survive"
    assert watchdog.SCAN_RATIO >= MEASURED_SCAN_RATIO_MAX * 3


def test_the_operation_ceiling_covers_the_worst_honest_silence_and_still_cuts_the_incident():
    worst_scan = MEASURED_SCAN_RATIO_MAX * CHANNEL_DURATION_CEILING_S          # 1200 s
    unlogged_python = MEASURED_SILENCE_MAX_S - MEASURED_BOUNDED_CALL_MAX_S     # ~98 s
    worst_honest = worst_scan + unlogged_python                               # ~1298 s
    assert watchdog.SILENCE_CEILING_S >= worst_honest * 1.4, "CF-0316: no margin for throttling"
    # ... and against what was actually measured the margin is at least 8x
    assert watchdog.SILENCE_CEILING_S >= MEASURED_SILENCE_MAX_S * 8
    assert watchdog.SILENCE_CEILING_S >= MEASURED_SILENCE_P90_S * 20
    # the incident is cut at least 50x sooner than it actually ended
    assert watchdog.SILENCE_CEILING_S * 50 <= INCIDENT_SILENCE_S, "CF-0316: too loose to help"


def test_the_arithmetic_is_written_down_where_the_next_reader_looks():
    doc = watchdog.__doc__ or ""
    for needle in ("CF-0112", "CF-0331", "5.24", "209.5", "1860", "CF-0339", "CF-0319"):
        assert needle in doc, f"CF-0316: {needle} missing from the derivation"
    tool = (ROOT / "scripts" / "watchdog_threshold.py")
    assert tool.exists(), "CF-0316: the numbers must be reproducible"


def test_ceiling_for_knows_a_class_a_number_and_nothing_else():
    assert watchdog.ceiling_for(None) == watchdog.SILENCE_CEILING_S
    assert watchdog.ceiling_for("shot") == watchdog.SHOT_CALL_CEILING_S
    assert watchdog.ceiling_for("download") == watchdog.DOWNLOAD_CEILING_S
    assert watchdog.ceiling_for(12.5) == 12.5
    assert watchdog.ceiling_for("scan", source_seconds=4000) == 4000.0
    assert watchdog.ceiling_for("scan", source_seconds=1) == watchdog.SCAN_MIN_CEILING_S
    try:
        watchdog.ceiling_for("whatever")
    except ValueError:
        pass
    else:
        raise AssertionError("CF-0316: an unknown class must not silently become the default")


def test_the_outcome_code_names_the_operation():
    assert watchdog.outcome_code(step="index") == "index_timeout"
    assert watchdog.outcome_code(step="fetch") == "fetch_timeout"
    assert watchdog.outcome_code(tool="yt-dlp") == "yt-dlp_timeout"
    assert watchdog.outcome_code() == "operation_timeout"
    # CF-0319: a kill is an авария, not a way a topic left the batch
    for code in ("index_timeout", "fetch_timeout", "operation_timeout"):
        assert code not in funnel.FUNNEL_CODES, "CF-0319: a kill is not a funnel loss"


# --------------------------------------------------------------------------
# 1/4. the seam that launches child calls (task items 1 and 4)
# --------------------------------------------------------------------------

def test_no_call_leaves_the_common_layer_without_a_ceiling():
    b = batch_dir()
    seen = {}
    real = runlog._watched

    def spy(cmd, ceiling_s, bdir, **kw):
        seen["ceiling"] = ceiling_s
        return real(cmd, ceiling_s, bdir, **kw)

    runlog._watched = spy
    try:
        cp = runlog.run_child([sys.executable, "-c", "pass"], batch_dir=b, stage="footage-indexer")
    finally:
        runlog._watched = real
    assert cp.returncode == 0
    assert seen["ceiling"] == watchdog.SILENCE_CEILING_S, "CF-0316: a caller that names no class"


def test_a_silent_operation_is_taken_down():
    fast_poll()
    b = batch_dir()
    cp = runlog.run_child([sys.executable, "-c", "import time; time.sleep(60)"],
                          tool="index_footage.py", stage="footage-indexer", step="index",
                          video="PEiDNOQ_0ms", batch_dir=b, watchdog=0.6, on_timeout="code")
    assert cp.returncode == watchdog.RC_TIMEOUT and cp.timed_out
    assert cp.timeout_code == "index_timeout"
    killed = [e for e in events_of(b) if watchdog.is_kill(e)]
    assert len(killed) == 1, [e.get("status") for e in events_of(b)]
    e = killed[0]
    assert e["status"] == runlog.ST_FAILED and e["rc"] == "index_timeout"
    assert e["watchdog"]["source"] == "PEiDNOQ_0ms"
    assert e["watchdog"]["ceiling_s"] == 0.6 and e["watchdog"]["silent_s"] >= 0.6
    assert e["duration_s"] < 30, "CF-0316: the operation was killed, not waited out"


def test_the_stage_goes_on_to_the_next_source_and_the_run_is_not_dropped():
    fast_poll()
    b = batch_dir()
    with runlog.run("footage-indexer", step="ingest", batch_dir=b):
        first = runlog.run_child([sys.executable, "-c", "import time; time.sleep(60)"],
                                 tool="index_footage.py", step="index", video="hung",
                                 batch_dir=b, watchdog=0.6, on_timeout="code")
        second = runlog.run_child([sys.executable, "-c", "print('next')"],
                                  tool="index_footage.py", step="index", video="next",
                                  batch_dir=b, watchdog=5.0, on_timeout="code",
                                  capture_output=True, text=True)
    assert first.timed_out and second.returncode == 0 and second.stdout.strip() == "next"
    evs = events_of(b)
    stage = [e for e in evs if e["kind"] == runlog.KIND_SCRIPT and e["status"] != "start"]
    assert stage and stage[-1]["status"] == runlog.ST_DONE, "CF-0316: the run must not be dropped"
    rows = watchdog.detect(b)
    assert [r["source"] for r in rows] == ["hung"]
    assert rows[0]["attempt_spent"] is False, "CF-0316: the attempt ceiling is not spent"


def test_an_honestly_long_operation_that_keeps_writing_events_is_spared():
    fast_poll()
    b = batch_dir()
    t0 = time.time()
    ceiling = HONEST_CEILING_S
    cp = runlog.run_child([sys.executable, str(live_child_script()), str(ceiling * 1.5)],
                          tool="index_footage.py", stage="footage-indexer", step="index",
                          video="honest", batch_dir=b, watchdog=ceiling, on_timeout="code",
                          env={**os.environ, runlog.BATCH_ENV: str(b)})
    took = time.time() - t0
    assert cp.returncode == 0 and not getattr(cp, "timed_out", False), (
        f"killed honest work after {took:.1f}s (ceiling {ceiling}s)")
    # the proof is read off the child's own events: it talked for longer than
    # the ceiling, so only its talking - not its total time - kept it alive
    ffmpeg = [e for e in events_of(b) if e.get("tool") == "ffmpeg"]
    assert ffmpeg, "the child wrote no events"
    span = runlog.parse_z(ffmpeg[-1]["ts"]) - runlog.parse_z(ffmpeg[0]["ts"])
    assert span > ceiling * 1.4, (
        f"the child talked {span:.1f}s, not long enough past the {ceiling}s ceiling to prove "
        f"anything ({took:.1f}s in all)")
    assert not watchdog.detect(b), "CF-0316: an operation that talks is not hung"


def test_sampler_samples_are_not_a_sign_of_life():
    """CF-0339: the sampler leaves after ten idle minutes, so its samples cannot
    be what keeps an operation alive - otherwise nothing survives an idle run.

    CF-0649: the silence is counted from the launch, so the ceiling has to
    outlast the child's own Python start - 0.6 s did not on a loaded Mac (load
    10-20): the child was killed before its first sample and the test proved
    nothing. 4 s is ten times a start at load 10, and the child talks in
    samples for 60 s - a watchdog that took them for life would let it run
    out its whole minute."""
    fast_poll()
    b = batch_dir()
    t0 = time.time()
    cp = runlog.run_child([sys.executable, str(sampler_only_script())],
                          tool="index_footage.py", stage="footage-indexer", step="index",
                          video="samples-only", batch_dir=b, watchdog=4.0, on_timeout="code",
                          env={**os.environ, runlog.BATCH_ENV: str(b)})
    took = time.time() - t0
    assert cp.timed_out, "CF-0316: samples must not hold the watchdog off"
    samples = [e for e in events_of(b) if e["kind"] == "sample"]
    assert samples, "the child did write samples"
    assert took < 40, f"killed only after {took:.1f}s - the samples held the watchdog off"


def test_an_explicit_timeout_keeps_the_cf_0128_behaviour():
    b = batch_dir()
    try:
        runlog.run_child([sys.executable, "-c", "import time; time.sleep(60)"],
                         tool="ffmpeg", stage="video-editor", step="render",
                         batch_dir=b, timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("CF-0128: an explicit timeout= still raises TimeoutExpired")
    done = [e for e in events_of(b) if e["status"] == runlog.ST_FAILED]
    assert done and done[-1]["rc"] == "timeout"
    assert not watchdog.is_kill(done[-1]), "the explicit path is not a watchdog kill"


def test_a_kill_raises_unless_the_caller_says_it_can_go_on():
    fast_poll()
    b = batch_dir()
    try:
        runlog.run_child([sys.executable, "-c", "import time; time.sleep(60)"],
                         tool="index_footage.py", stage="footage-indexer", step="index",
                         batch_dir=b, watchdog=0.6)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("CF-0316: a kill must not look like a result to an unprepared caller")
    rows = watchdog.detect(b)
    assert len(rows) == 1 and rows[0]["code"] == "index_timeout"


# --------------------------------------------------------------------------
# 3. the statistics and the post-run triage (task item 3)
# --------------------------------------------------------------------------

def test_a_clean_run_says_nothing_about_the_watchdog():
    b = batch_dir()
    with runlog.run("footage-indexer", step="ingest", batch_dir=b):
        runlog.run_child([sys.executable, "-c", "pass"], batch_dir=b, step="index")
    assert watchdog.detect(b) == []
    assert watchdog.render([]) == [] and watchdog.headline([]) is None


def test_the_kill_reaches_the_summary_as_its_own_line():
    fast_poll()
    b = batch_dir()
    runlog.marker(runlog.M_BATCH_START, "footage-indexer", batch_dir=b, strict=False)
    with runlog.run("footage-indexer", step="ingest", batch_dir=b):
        runlog.run_child([sys.executable, "-c", "import time; time.sleep(60)"],
                         tool="index_footage.py", step="index", video="PEiDNOQ_0ms",
                         batch_dir=b, watchdog=0.6, on_timeout="code")
    runlog.marker(runlog.M_BATCH_DONE, "footage-indexer", batch_dir=b, strict=False)
    text = summary.render(b)
    assert "Operations the watchdog took down (CF-0316)" in text
    assert "`index_timeout`" in text and "PEiDNOQ_0ms" in text
    assert "CF-0319" in text, "the triage has to read it as an авария"
    data = summary.compute(b)
    assert len(data["watchdog"]) == 1 and data["watchdog"][0]["code"] == "index_timeout"


def test_the_cli_reports_what_the_run_lost():
    fast_poll()
    b = batch_dir()
    runlog.run_child([sys.executable, "-c", "import time; time.sleep(60)"],
                     tool="index_footage.py", stage="footage-indexer", step="index",
                     video="PEiDNOQ_0ms", batch_dir=b, watchdog=0.6, on_timeout="code")
    cp = subprocess.run([sys.executable, str(ROOT / "shared" / "runlog" / "runlog.py"),
                         "watchdog", "--batch", str(b), "--json"],
                        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr
    rows = json.loads(cp.stdout)
    assert len(rows) == 1 and rows[0]["code"] == "index_timeout"
    cp = subprocess.run([sys.executable, str(ROOT / "shared" / "runlog" / "runlog.py"),
                         "watchdog", "--batch", str(batch_dir())],
                        capture_output=True, text=True, timeout=120)
    assert "no operation was taken down" in cp.stdout


# --------------------------------------------------------------------------
# CF-0395: an exit is seen at once, not on the next read of the silence
# --------------------------------------------------------------------------

def test_a_short_child_returns_at_once_not_after_a_poll():
    """CF-0395: a 0.2 s ffprobe used to cost the whole POLL_S (5 s)."""
    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    rc, _ = watchdog.wait(proc, 60.0, poll_s=5.0)
    took = time.monotonic() - t0
    assert rc == 0
    assert took < 2.5, f"CF-0395: exit noticed after {took:.2f}s - it waited out the poll"


def test_a_short_run_child_under_the_real_poll_is_not_stretched():
    saved = watchdog.POLL_S
    watchdog.POLL_S = 5.0
    try:
        b = batch_dir()
        t0 = time.monotonic()
        cp = runlog.run_child([sys.executable, "-c", "pass"], tool="ffprobe",
                              stage="footage-indexer", step="probe", batch_dir=b)
        took = time.monotonic() - t0
    finally:
        watchdog.POLL_S = saved
    assert cp.returncode == 0
    assert took < 2.5, f"CF-0395: run_child took {took:.2f}s for a no-op child"


def test_a_silent_child_is_still_cut_at_the_ceiling_with_a_long_poll():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        t0 = time.monotonic()
        rc, silent = watchdog.wait(proc, 0.5, poll_s=5.0)
        took = time.monotonic() - t0
        assert rc is None and silent >= 0.5
        assert took < 3.0, f"CF-0395: the ceiling fired after {took:.2f}s"
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_the_silence_is_still_read_once_per_poll():
    """The wait blocks on the process for at most poll_s at a time, so a child
    that keeps writing events is still seen alive between two reads."""
    class Proc:
        def __init__(self):
            self.waits = []

        def poll(self):
            return 0 if len(self.waits) >= 3 else None

        def wait(self, timeout=None):
            self.waits.append(timeout)
            raise subprocess.TimeoutExpired("x", timeout)

    p = Proc()
    rc, _ = watchdog.wait(p, 60.0, poll_s=0.01)
    assert rc == 0 and p.waits == [0.01, 0.01, 0.01]


def test_an_injected_sleep_still_drives_the_loop():
    """Tests that step the clock by hand keep working (the old contract)."""
    clock = [0.0]
    slept = []

    class Proc:
        def poll(self):
            return None

    def fake_sleep(dt):
        slept.append(dt)
        clock[0] += dt

    rc, silent = watchdog.wait(Proc(), 12.0, poll_s=5.0, now=lambda: clock[0],
                               sleep=fake_sleep)
    assert rc is None and silent >= 12.0
    assert slept == [5.0, 5.0, 2.0]


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
    sys.exit(1 if failed else 0)

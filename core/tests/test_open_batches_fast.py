#!/usr/bin/env python3
"""CF-0656: `runlog.open_batches` (and `runlog batch-active` over it) read the
whole ~460 MB of events and json-parsed every line of every rebuild - 7-40 s on
the live tree. It now reads tails and byte-searches. What is pinned here, on
temp trees only (the live `pipeline/` is never read):

* the same answer as the full read of CF-0398/CF-0401 (the reference copy below
  is the code before CF-0656) on generated batches and rebuilds - markers,
  `child` noise, samples, open/closed/superseded scripts, live and dead pids,
  other machines, broken lines - for a sweep of `now`, with the scan chunk made
  tiny so that every needle and line crosses a chunk boundary;
* the edges: a work event exactly `sampler.IDLE_MINUTES` ago is open, a moment
  later it is not; a live script that wrote nothing since its start holds the
  rebuild open (and not past `hours`); a broken last line is not an event - its
  ts does not count as work and a cut `done` does not close a script; a batch
  whose `batch-done` is far from the end is closed;
* a stand of many big closed rebuilds: the answer is the same, almost nothing
  is parsed, and the time stays in bounds;
* nothing is shared between calls: threads calling it together get the answer
  of a single call (the API calls it from a pool, CC-0039).

CF-0670 added a rule the reference copy did not have, so the reference below
has it too, written apart (an exclusive probe, not `executor_lock`): a run whose
`run-executor.lock` is held is open and fresh. Pinned with real processes that
hold the flock - a stand-in `run_executor.py` and a foreign `holder.py`:

* a rebuild with a live executor and no event for 20 minutes (past
  `sampler.IDLE_MINUTES`) is open, its line «исполнитель жив (pid N)», also on
  `runlog batch-active`'s stderr; a channel batch past `hours` with a live
  executor too; a lock with no events yet as well;
* the executor dead, its lock file left: closed again (no events within IDLE);
* the lock held by a process that is not an executor: open - CF-0667's rule
  «lock держит неизвестный» is a refusal, never a guess, so a second batch does
  not start beside it - with a line that says so;
* the answer equals the reference with the lock rule over a mixed tree.
"""
import fcntl
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("open-batches-fast-test-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")       # never touch ~/.shorts-content-factory
os.environ["RUNLOG_PROJECTS_DIR"] = str(TMP / "none")
os.environ["RUNLOG_TRANSCRIPTS"] = str(TMP / "none")
import runlog   # noqa: E402

_n = [0]
IDLE = timedelta(minutes=runlog.sibling("sampler").IDLE_MINUTES)
HOURS = float(runlog.sibling("sampler").MAX_HOURS)


# ------------------------------------------- the full read before CF-0656

def ref_is_open(path, rebuild):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if b'"batch-start"' not in data:
        return False
    if not rebuild:
        return ref_batch_reopened(data)
    markers = []
    for line in data.splitlines():
        if b'"marker"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("kind") == runlog.KIND_MARKER:
            markers.append(e)
    return bool(runlog._open_stages(markers))


def ref_batch_reopened(data):
    """CF-0739 written apart, by lines: open with no batch-done; after the
    line of the last `"batch-done"` bytes, open while a batch-start or an
    unmatched stage-start follows it."""
    if b'"batch-done"' not in data:
        return True
    lines = data.split(b"\n")
    last = max(i for i, line in enumerate(lines) if b'"batch-done"' in line)
    if last == len(lines) - 1:           # a cut last line: nothing follows it
        return False
    open_ = set()
    for line in lines[last + 1:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("kind") != runlog.KIND_MARKER:
            continue
        if e.get("status") == "batch-start":
            return True
        if e.get("status") == "stage-start":
            open_.add(e.get("stage"))
        elif e.get("status") == "stage-done":
            open_.discard(e.get("stage"))
    return bool(open_)


def ref_rebuild_working(path, now, hours):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    last, open_ = None, {}
    for line in data.splitlines():
        if b'"kind": "sample"' in line:
            continue
        try:
            e = json.loads(line)
            t = runlog.parse_z(e.get("ts"))
        except (ValueError, TypeError, AttributeError, OverflowError):
            continue
        if e.get("kind") == "sample":
            continue
        last = t if last is None else max(last, t)
        if e.get("kind") == runlog.KIND_SCRIPT and e.get("id"):
            if e.get("status") == runlog.ST_START:
                open_[e["id"]] = e
            elif e.get("status") in (runlog.ST_DONE, runlog.ST_FAILED):
                open_.pop(e["id"], None)
    if last is None:
        return None
    idle_s = float(runlog.sibling("sampler").IDLE_MINUTES) * 60.0
    last_dt = datetime.fromtimestamp(last, tz=timezone.utc)
    if (now - last_dt).total_seconds() <= idle_s:
        return last_dt
    for ev in open_.values():
        try:
            if (now.timestamp() - runlog.parse_z(ev.get("ts"))) > hours * 3600:
                continue
        except (ValueError, TypeError, AttributeError, OverflowError):
            continue
        if runlog._script_alive(ev, now):
            return last_dt
    return None


LOCK = "run-executor.lock"


def ref_lock_held(d):
    """CF-0670's new rule, apart from `executor_lock`: an exclusive probe."""
    try:
        fh = open(Path(d) / LOCK, "r")
    except OSError:
        return False
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False


def ref_open_batches(root, now, hours):
    out = []
    pipe = Path(root) / "pipeline"
    dirs = {p.parent for p in pipe.glob(f"*/*/{runlog.EVENTS_FILE}")} | \
        {p.parent for p in pipe.glob(f"*/*/{LOCK}")}
    for path in sorted(d / runlog.EVENTS_FILE for d in dirs):
        chan = path.parent.parent.name
        if chan == "backfill":
            continue
        rebuild = chan == "rebuilds"
        if ref_lock_held(path.parent):                       # CF-0670
            last = runlog._last_ts(path) if path.exists() else \
                datetime.fromtimestamp((path.parent / LOCK).stat().st_mtime, tz=timezone.utc)
            out.append((path.parent, last, True))
            continue
        if not path.exists():
            continue
        if not ref_is_open(path, rebuild=rebuild):
            working = ref_rebuild_working(path, now, hours) if rebuild else None
            if working:
                out.append((path.parent, working, True))
            continue
        last = runlog._last_ts(path)
        fresh = bool(last) and (now - last).total_seconds() <= hours * 3600
        out.append((path.parent, last, fresh))
    return out


# ------------------------------------------------------------------ helpers

def z(dt):
    return runlog.now_z(dt.timestamp())


def ev(dt, kind, status=None, sid=None, pid=None, machine=None, **kw):
    e = {"ts": z(dt), "machine": runlog.machine_id() if machine is None else machine,
         "kind": kind, "stage": kw.pop("stage", "video-editor"), "video": None,
         "step": None, "attempt": None, "status": status, "params": kw.pop("params", None),
         "duration_s": None, "pid": pid, "id": sid, "parent": None}
    e.update(kw)
    return json.dumps(e)


def write(path, lines, tail=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(x + "\n" for x in lines) + tail)
    return path


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class patched:
    """Sets module attributes for the duration of a with-block (the house harness
    calls tests with no arguments - no pytest monkeypatch)."""

    def __init__(self, obj, **attrs):
        self.obj, self.attrs, self.saved = obj, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.saved[k] = getattr(self.obj, k)
            setattr(self.obj, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(self.obj, k, v)


def a_root(tag):
    _n[0] += 1
    return TMP / f"{tag}{_n[0]}"


def gen_rebuild(rng, t0, n, me, dead):
    """A rebuild's events: scripts that start and (mostly) end, child noise,
    samples, an occasional marker, broken lines - in time order with jitter."""
    lines, open_ids, t = [], [], t0
    machines = [runlog.machine_id(), runlog.machine_id(), "other-host-00000000"]
    for i in range(n):
        t += timedelta(seconds=rng.choice([0.2, 1, 5, 30, 120, 900, 4000]))
        jitter = timedelta(seconds=rng.uniform(-0.3, 0))
        r = rng.random()
        if r < 0.25:
            sid = f"s{rng.randrange(40):011x}"
            lines.append(ev(t + jitter, "script", "start", sid, rng.choice([me, dead]),
                            rng.choice(machines), step="render",
                            params={"args": ["scripts/render.py", "--status", "start"]}))
            open_ids.append(sid)
        elif r < 0.45 and open_ids:
            sid = open_ids.pop(rng.randrange(len(open_ids)))
            lines.append(ev(t + jitter, "script", rng.choice(["done", "failed"]), sid, me))
        elif r < 0.75:
            lines.append(ev(t + jitter, "child", rng.choice(["start", "done"]),
                            f"c{i:011x}", me, params={"tool": "ffmpeg", "pid": me,
                                                      "args": ["x" * rng.randrange(200)]}))
        elif r < 0.9:
            lines.append(ev(t + jitter, "sample", params={"cpu": 1}))
        elif r < 0.94:
            lines.append(ev(t, "marker", rng.choice(["batch-start", "stage-start", "stage-done"]),
                            f"m{i:011x}", me))
        elif r < 0.97:
            lines.append('{"ts": "' + z(t) + '", "kind": "child", "status": "do')   # broken
        else:
            lines.append(ev(t + jitter, "script", "progress", f"s{rng.randrange(40):011x}", me))
    return lines, t


# ------------------------------------------------------------- equivalence

def test_rebuilds_answer_as_the_full_read_did():
    rng = random.Random(656)
    me, dead = os.getpid(), dead_pid()
    root = a_root("eq")
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    files = []
    for k in range(24):
        lines, end = gen_rebuild(rng, t0, rng.choice([5, 40, 200]), me, dead)
        tail = rng.choice(["", "", '{"ts": "' + z(end) + '", "kind": "child", "sta'])
        files.append((write(root / "pipeline" / "rebuilds" / f"r{k:02d}" / runlog.EVENTS_FILE,
                            lines, tail), end))
    checked = 0
    with patched(runlog, _process_age_s=lambda pid: 10 ** 7, _SCAN_CHUNK=97):
        for path, end in files:
            for now in (end - timedelta(hours=3), end, end + IDLE, end + IDLE + timedelta(seconds=1),
                        end + timedelta(hours=2), end + timedelta(hours=HOURS - 1),
                        end + timedelta(hours=HOURS + 1), end + timedelta(days=30)):
                for hours in (HOURS, 0.5):
                    want = (ref_is_open(path, True), ref_rebuild_working(path, now, hours))
                    got = (runlog._is_open(path, True), runlog._rebuild_working(path, now, hours))
                    assert got == want, (path, now, hours, got, want)
                    checked += 1
    assert checked == 24 * 8 * 2


def test_batches_answer_as_the_full_read_did():
    rng = random.Random(401)
    root = a_root("eqb")
    t = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    shapes = [["batch-start"], ["batch-start", "batch-done"], ["batch-done"], [],
              ["batch-start", "stage-start", "stage-done"],
              ["batch-start", "batch-done", "stage-start"],                  # CF-0739
              ["batch-start", "batch-done", "stage-start", "stage-done"],
              ["batch-start", "batch-done", "stage-start", "stage-done", "batch-done"],
              ["batch-start", "batch-done", "batch-start"]]
    paths = []
    for k in range(30):
        statuses = rng.choice(shapes)
        lines = [ev(t, "marker", s, f"m{k:011x}") for s in statuses[:1]]
        lines += [ev(t, "child", "done", "c1", params={"x": "y" * rng.randrange(300)})
                  for _ in range(rng.randrange(30))]
        lines += [ev(t, "marker", s, f"n{k:011x}") for s in statuses[1:]]
        lines += [ev(t, "sample") for _ in range(rng.randrange(30))]
        tail = rng.choice(["", '{"ts": "x", "status": "batch-do', '{"status": "batch-done"'])
        paths.append(write(root / "pipeline" / "chan" / f"b{k:02d}" / runlog.EVENTS_FILE,
                           lines, tail))
    for chunk in (13, 97, 1 << 18):
        with patched(runlog, _SCAN_CHUNK=chunk):
            for p in paths:
                assert runlog._is_open(p, False) == ref_is_open(p, False), (p, chunk)
                assert runlog._is_open(p, True) == ref_is_open(p, True), (p, chunk)
    now = t + timedelta(hours=1)
    assert runlog.open_batches(root, now=now, hours=HOURS) == ref_open_batches(root, now, HOURS)


# -------------------------------------------------------------------- edges

def test_a_work_event_exactly_idle_minutes_ago_is_open_and_a_moment_later_not():
    root = a_root("idle")
    t = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    write(reb / runlog.EVENTS_FILE, [ev(t - timedelta(minutes=30), "script", "start", "a1", dead_pid()),
                                     ev(t, "child", "done", "c1"),
                                     ev(t + timedelta(minutes=2), "sample")])
    assert runlog.open_batches(root, now=t + IDLE) == [(reb, t, True)]
    assert runlog.open_batches(root, now=t + IDLE + timedelta(milliseconds=1)) == []


def test_a_live_script_with_no_events_since_its_start_holds_the_rebuild_open():
    root = a_root("silent")
    now = datetime.now(timezone.utc)
    started = now - timedelta(hours=3)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    write(reb / runlog.EVENTS_FILE,
          [ev(started - timedelta(minutes=5), "child", "done", "c0")]
          + [ev(started - timedelta(minutes=4, seconds=-i), "script", "start", f"x{i:011x}", os.getpid())
             for i in range(3)]
          + [ev(started - timedelta(minutes=4, seconds=-i), "script", "done", f"x{i:011x}", os.getpid())
             for i in range(3)]
          + [ev(started, "script", "start", "a1", os.getpid()),
             ev(started + timedelta(seconds=1), "child", "start", "c1", os.getpid())]
          + [ev(started + timedelta(seconds=2), "sample") for _ in range(50)])
    with patched(runlog, _process_age_s=lambda pid: 4 * 3600):
        assert [d for d, _, _ in runlog.open_batches(root, now=now)] == [reb]
        assert runlog.open_batches(root, now=now, hours=2) == []          # older than hours
    with patched(runlog, _process_age_s=lambda pid: 60):                  # the pid was reused
        assert runlog.open_batches(root, now=now) == []


def test_a_broken_last_line_is_not_an_event():
    root = a_root("cut")
    now = datetime.now(timezone.utc)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    old = now - timedelta(hours=1)
    work = [ev(old, "script", "start", "a1", dead_pid()), ev(old, "script", "done", "a1", 1)]
    # a fresh ts at the head of a cut line is not work
    write(reb / runlog.EVENTS_FILE, work, tail='{"ts": "' + z(now) + '", "kind": "child", "st')
    assert runlog.open_batches(root, now=now) == []
    # a cut `done` does not close a live script
    live = [ev(old, "script", "start", "b1", os.getpid())]
    whole = ev(now - timedelta(minutes=30), "script", "done", "b1", os.getpid())
    cut = whole[:-12]
    write(reb / runlog.EVENTS_FILE, live, tail=cut)
    with patched(runlog, _process_age_s=lambda pid: 2 * 3600):
        assert [d for d, _, _ in runlog.open_batches(root, now=now)] == [reb]
        write(reb / runlog.EVENTS_FILE, live + [whole])
        assert runlog.open_batches(root, now=now) == []                    # whole, it closes
    # a batch whose last line is a cut `batch-do...` is still open, as before
    b = root / "pipeline" / "chan" / "2026-10-10T0800Z"
    write(b / runlog.EVENTS_FILE, [ev(old, "marker", "batch-start", "m1")],
          tail='{"ts": "' + z(now) + '", "kind": "marker", "status": "batch-do')
    assert [d for d, _, _ in runlog.open_batches(root, now=now)] == [b]


def test_a_batch_done_far_from_the_end_closes_the_batch():
    root = a_root("far")
    t = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    b = root / "pipeline" / "chan" / "2026-10-10T0800Z"
    write(b / runlog.EVENTS_FILE, [ev(t, "marker", "batch-start", "m1"), ev(t, "marker", "batch-done", "m2")]
          + [ev(t, "sample", params={"x": "y" * 900}) for _ in range(3000)])     # ~3 MB after it
    assert runlog.open_batches(root, now=t) == []


def test_events_slightly_out_of_order_still_give_the_newest():
    root = a_root("order")
    t = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    write(reb / runlog.EVENTS_FILE, [ev(t, "child", "done", "c1"),
                                     ev(t - timedelta(seconds=5), "child", "done", "c2"),
                                     ev(t - timedelta(seconds=1), "sample")])
    assert runlog.open_batches(root, now=t + IDLE) == [(reb, t, True)]


# --------------------------------------------------------------------- stand

class _CountingJson:
    def __init__(self):
        self.loads_calls = 0

    def loads(self, s, *a, **kw):
        self.loads_calls += 1
        return json.loads(s, *a, **kw)

    def __getattr__(self, name):
        return getattr(json, name)


def test_a_stand_of_many_big_rebuilds_stays_fast_and_parses_almost_nothing():
    rng = random.Random(40)
    root = a_root("stand")
    now = datetime.now(timezone.utc)
    me, dead = os.getpid(), dead_pid()
    pad = "p" * 400
    for k in range(30):                                    # closed, days old, ~0.8 MB each
        t = now - timedelta(days=3, hours=k)
        lines = []
        for i in range(1500):
            t += timedelta(seconds=1)
            if i % 5 == 0:
                lines.append(ev(t, "script", "start" if i % 10 == 0 else "done", f"s{i // 10:011x}",
                                rng.choice([me, dead]), params={"pad": pad}))
            else:
                lines.append(ev(t, "child", "done", f"c{i:011x}", me, params={"pad": pad}))
        write(root / "pipeline" / "rebuilds" / f"2026-10-0{k % 9}T{k:04d}Z" / runlog.EVENTS_FILE, lines)
    for k in range(20):                                    # closed batches, done near the end
        lines = [ev(now - timedelta(days=2), "marker", "batch-start", "m1")]
        lines += [ev(now - timedelta(days=2), "child", "done", "c", params={"pad": pad})
                  for _ in range(1000)]
        lines += [ev(now - timedelta(days=2), "marker", "batch-done", "m2")]
        write(root / "pipeline" / "chan" / f"2026-10-0{k % 9}T{k:04d}Z" / runlog.EVENTS_FILE, lines)
    working = root / "pipeline" / "rebuilds" / "2026-10-10T0000Z"
    write(working / runlog.EVENTS_FILE, [ev(now - timedelta(minutes=2), "child", "done", "c")])
    counting = _CountingJson()
    with patched(runlog, json=counting):
        t0 = time.monotonic()
        rows = runlog.open_batches(root, now=now)
        took = time.monotonic() - t0
    assert [d for d, _, _ in rows] == [working]
    assert rows == ref_open_batches(root, now, HOURS)
    assert counting.loads_calls < 200, counting.loads_calls              # the full read: >45 000
    assert took < 2.0, took


def test_threads_calling_together_get_one_answer():
    root = a_root("threads")
    now = datetime.now(timezone.utc)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    write(reb / runlog.EVENTS_FILE, [ev(now - timedelta(minutes=1), "child", "done", "c")])
    write(root / "pipeline" / "chan" / "b1" / runlog.EVENTS_FILE,
          [ev(now, "marker", "batch-start", "m1")])
    write(root / "pipeline" / "chan" / "b2" / runlog.EVENTS_FILE,
          [ev(now, "marker", "batch-start", "m1"), ev(now, "marker", "batch-done", "m2")])
    want = runlog.open_batches(root, now=now)
    assert [d.name for d, _, _ in want] == ["b1", "2026-10-10T0800Z"]
    got, errors = [], []

    def call():
        try:
            for _ in range(20):
                got.append(runlog.open_batches(root, now=now))
        except Exception as e:                                           # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(got) == 160 and all(g == want for g in got)


# ------------------------------------------------- CF-0670: the executor's lock

HOLD_SRC = """import fcntl, os, sys, time
fh = open(sys.argv[1], "a+")
fcntl.flock(fh, fcntl.LOCK_EX)
if sys.argv[2:] != ["nopid"]:
    fh.seek(0); fh.truncate(); fh.write(f"pid {os.getpid()} since now\\n"); fh.flush()
print("held", flush=True)
time.sleep(600)
"""


class holding:
    """A real process that holds `<d>/run-executor.lock` (flock, as the executor
    does): `as_executor` names its script `run_executor.py`, else `holder.py`."""

    def __init__(self, d, as_executor=True, nopid=False):
        self.d, self.name, self.nopid = Path(d), \
            "run_executor.py" if as_executor else "holder.py", nopid

    def __enter__(self):
        src = TMP / "fake" / self.name
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(HOLD_SRC)
        self.d.mkdir(parents=True, exist_ok=True)
        argv = [sys.executable, str(src), str(self.d / LOCK)] + (["nopid"] if self.nopid else [])
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
        assert self.proc.stdout.readline().strip() == "held"
        return self.proc

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()


def test_a_rebuild_whose_live_executor_is_silent_stays_open():
    root = a_root("lock")
    now = datetime.now(timezone.utc)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    quiet = now - timedelta(minutes=20)                    # past IDLE: no work event since
    assert timedelta(minutes=20) > IDLE
    write(reb / runlog.EVENTS_FILE, [ev(quiet, "script", "start", "a1", dead_pid()),
                                     ev(quiet, "script", "done", "a1", 1)])
    assert runlog.open_batches(root, now=now) == []        # the old rules: closed
    h = holding(reb)
    with h as proc:
        rows = runlog.open_batches(root, now=now)
        assert rows == [(reb, runlog._last_ts(reb / runlog.EVENTS_FILE), True)], rows
        assert rows == ref_open_batches(root, now, HOURS)
        assert rows[0].why == f"исполнитель жив (pid {proc.pid})", rows[0].why
        cp = subprocess.run([sys.executable, str(ROOT / "shared" / "runlog" / "runlog.py"),
                             "batch-active", "--root", str(root)],
                            capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0 and cp.stdout.strip() == str(reb), cp
        assert f"исполнитель жив (pid {proc.pid})" in cp.stderr, cp.stderr
        h.stop()                                           # dead: the kernel frees the lock
        assert (reb / LOCK).is_file()                      # the file is left
        assert runlog.open_batches(root, now=now) == []
        assert ref_open_batches(root, now, HOURS) == []


def test_a_live_executor_keeps_a_stale_batch_and_an_eventless_one_open():
    root = a_root("lockb")
    now = datetime.now(timezone.utc)
    b = root / "pipeline" / "chan" / "2026-10-08T0800Z"
    old = now - timedelta(hours=HOURS + 5)
    write(b / runlog.EVENTS_FILE, [ev(old, "marker", "batch-start", "m1")])
    rows = runlog.open_batches(root, now=now)
    assert [(d, f) for d, _, f in rows] == [(b, False)] and rows[0].why == "нет batch-done"
    new = root / "pipeline" / "chan" / "2026-10-10T0900Z"  # the executor took the lock, no event yet
    with holding(b), holding(new):
        rows = runlog.open_batches(root, now=now)
        assert [(d, f) for d, _, f in rows] == [(b, True), (new, True)], rows
        assert rows[1][1] is not None                      # the lock file's mtime
        assert rows == ref_open_batches(root, now, HOURS)
        assert all(r.why.startswith("исполнитель жив (pid ") for r in rows)
    assert [(d, f) for d, _, f in runlog.open_batches(root, now=now)] == [(b, False)]


def test_a_lock_held_by_something_else_counts_open_and_says_so():
    root = a_root("lockx")
    now = datetime.now(timezone.utc)
    reb = root / "pipeline" / "rebuilds" / "2026-10-10T0800Z"
    write(reb / runlog.EVENTS_FILE, [ev(now - timedelta(hours=2), "child", "done", "c1")])
    with holding(reb, as_executor=False) as proc:
        rows = runlog.open_batches(root, now=now)
        assert [(d, f) for d, _, f in rows] == [(reb, True)], rows
        assert f"держит не исполнитель (pid {proc.pid})" in rows[0].why, rows[0].why
    with holding(reb, as_executor=False, nopid=True):
        (reb / LOCK).write_text("")                        # nobody wrote a pid
        rows = runlog.open_batches(root, now=now)
        assert [d for d, _, _ in rows] == [reb] and "pid не записан" in rows[0].why, rows
    assert runlog.open_batches(root, now=now) == []


def test_mixed_tree_with_locks_answers_as_the_reference():
    root = a_root("lockmix")
    now = datetime.now(timezone.utc)
    t = now - timedelta(hours=1)
    pipe = root / "pipeline"
    write(pipe / "chan" / "b1" / runlog.EVENTS_FILE, [ev(t, "marker", "batch-start", "m1")])
    write(pipe / "chan" / "b1-" / runlog.EVENTS_FILE,
          [ev(t, "marker", "batch-start", "m1"), ev(t, "marker", "batch-done", "m2")])
    write(pipe / "chan" / "b1-" / LOCK, ["pid 1 since then"])   # left behind, free
    write(pipe / "rebuilds" / "r1" / runlog.EVENTS_FILE, [ev(t, "child", "done", "c")])
    write(pipe / "rebuilds" / "r2" / LOCK, ["pid 1 since then"])
    write(pipe / "backfill" / "x1" / runlog.EVENTS_FILE, [ev(t, "marker", "batch-start", "m1")])
    with holding(pipe / "rebuilds" / "r1"), holding(pipe / "backfill" / "x1"), \
            holding(pipe / "chan" / "b1-"):
        rows = runlog.open_batches(root, now=now)
        assert [d.name for d, _, _ in rows] == ["b1", "b1-", "r1"], rows
        assert rows == ref_open_batches(root, now, HOURS)
    rows = runlog.open_batches(root, now=now)
    assert [d.name for d, _, _ in rows] == ["b1"] and rows == ref_open_batches(root, now, HOURS)


def test_the_lock_rule_is_the_one_batch_control_reads():
    """One function for both (CF-0670): batch_control's executor is executor_lock's."""
    sys.path.insert(0, str(ROOT / "shared"))
    import batch_control as bc                             # noqa: PLC0415
    import run_executor as rx                              # noqa: PLC0415
    xl = runlog.sibling("executor_lock")
    assert xl.LOCK_FILE == rx.LOCK_FILE == LOCK
    assert bc._xl() is xl
    d = a_root("lockbc") / "pipeline" / "chan" / "b1"
    with holding(d) as proc:
        ex = bc.executor_of(d)
        assert ex["alive"] and ex["pid"] == proc.pid and ex["lock_held"]
        assert xl.holder(d)["state"] == xl.EXECUTOR
    with holding(d, as_executor=False):
        ex = bc.executor_of(d)
        assert not ex["alive"] and ex["lock_held"] and xl.holder(d)["state"] == xl.UNKNOWN
    assert xl.holder(d)["state"] == xl.FREE and not bc.executor_of(d)["lock_held"]


# ------------------------------------------------- CF-0739: reopened after done

def reopened(root, after, tail=""):
    t = datetime(2026, 10, 13, 14, 11, tzinfo=timezone.utc)
    b = root / "pipeline" / "chan" / "2026-10-13T1411Z"
    lines = [ev(t, "marker", "batch-start", "m1", stage=None),
             ev(t, "marker", "stage-start", "m2", stage="footage-indexer"),
             ev(t, "marker", "stage-done", "m3", stage="footage-indexer"),
             ev(t, "marker", "batch-done", "m4", stage=None)]
    lines += [ev(t, "sample", params={"x": "y" * 900}) for _ in range(50)]
    lines += [ev(t + timedelta(minutes=k + 1), "marker", s, f"r{k}", stage=st)
              for k, (s, st) in enumerate(after)]
    write(b / runlog.EVENTS_FILE, lines, tail)
    return b, t + timedelta(minutes=len(after) + 1)


def test_a_stage_start_after_batch_done_reopens_the_batch_while_it_runs():
    """The 2026-10-13T1411Z case: the executor re-runs footage-indexer after
    `batch_control rerun-from` - its stage-start follows the batch-done."""
    b, now = reopened(a_root("reo"), [("stage-start", "footage-indexer")])
    rows = runlog.open_batches(b.parent.parent.parent, now=now)
    assert [r[0] for r in rows] == [b] and rows[0][2]
    assert "footage-indexer" in rows[0].why and "CF-0739" in rows[0].why
    for chunk in (13, 97):                   # needles across chunk boundaries
        with patched(runlog, _SCAN_CHUNK=chunk):
            assert runlog._is_open(b / runlog.EVENTS_FILE, False)


def test_a_rework_whose_stages_closed_again_is_closed():
    """The 2026-09-23T1722Z case: a marker after batch-done alone does not hold
    the batch open forever - every re-run stage closed."""
    b, now = reopened(a_root("reo"), [("stage-start", "video-editor"),
                                       ("stage-done", "video-editor"),
                                       ("stage-start", "frame-judge"),
                                       ("stage-done", "frame-judge")])
    assert runlog.open_batches(b.parent.parent.parent, now=now) == []


def test_a_rerun_that_reached_batch_done_again_is_closed():
    b, now = reopened(a_root("reo"), [("stage-start", "frame-judge"),
                                       ("batch-done", None)])
    assert runlog.open_batches(b.parent.parent.parent, now=now) == []


def test_a_batch_start_after_batch_done_reopens():
    b, now = reopened(a_root("reo"), [("batch-start", None)])
    rows = runlog.open_batches(b.parent.parent.parent, now=now)
    assert [r[0] for r in rows] == [b] and "batch-start" in rows[0].why


def test_batch_active_names_the_reopened_batch():
    b, _now = reopened(a_root("reo"), [("stage-start", "footage-indexer")])
    root = b.parent.parent.parent
    cp = subprocess.run([sys.executable, str(ROOT / "shared" / "runlog" / "runlog.py"),
                         "batch-active", "--root", str(root), "--hours", "1000000"],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == str(b) and "CF-0739" in cp.stderr


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

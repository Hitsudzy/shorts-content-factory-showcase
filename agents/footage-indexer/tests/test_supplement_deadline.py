#!/usr/bin/env python3
"""CF-0429: `ingest_batch.py --supplement --deadline` - a supplement walk that
the wall clock stops keeps what it finished.

Verification run `example-film/2026-09-28T1126Z`: the root step's 30-minute
ceiling (CF-0426) came inside this stage, the root killed `--supplement` at its
timeout, and `01b` - written once, at the end - was never written: 0 of 23
candidates reached the pool. Now: past the deadline nothing new is started,
what is downloaded and indexed is in `01b`, the rest is listed with `outcome:
wall_ceiling`, the exit is 0; a download or index in flight is killed; SIGTERM
is the deadline arriving now; and `01b` is written after every source.

Offline: fetch and index are stand-ins driven by a fake clock, except the three
real-process tests (a `sleep` child stands in for yt-dlp), which take ~1-3 s.
The pool depth is a stand-in too (`USABLE` summed), so the walk's stopping
point does not depend on the Video Editor's gate being importable.
"""
import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import ingest_batch as ib                   # noqa: E402
import pool_depth as pd                     # noqa: E402
import test_thin_pool_supplement as t       # noqa: E402 - CF-0338's world

B, C, D, HELD, TOPIC = t.B, t.C, t.D, t.HELD, t.TOPIC


def fake_depth(tid, vids, cache=None):
    usable = sum(t.USABLE.get(v, 0) for v in vids)
    return pd.TopicDepth(tid, len(vids), usable, usable, 0.0, True, None, [])


class Clock:
    def __init__(self, at=0.0):
        self.t = at

    def __call__(self):
        return self.t


class Timed(t.Fetcher):
    """CF-0338's fetcher, with every download and index costing clock time,
    and the ones named in `killed_*` failing the way a killed child does."""

    def __init__(self, cache, clock, cost=10, index_cost=10, killed_fetch=(),
                 killed_index=(), on_fetch=None, fetch_child=None):
        super().__init__(cache)
        self.clock, self.cost, self.index_cost = clock, cost, index_cost
        self.killed_fetch, self.killed_index = set(killed_fetch), set(killed_index)
        self.on_fetch, self.fetch_child = on_fetch, fetch_child
        self.indexed = []

    def __call__(self, vid, note):
        self.calls.append(vid)
        if self.on_fetch:
            self.on_fetch(vid)
        if self.fetch_child and vid in self.fetch_child:
            rc = self.fetch_child[vid]()
            if rc != 0:
                raise RuntimeError(f"fetch_footage.py exit {rc}")
        self.clock.t += self.cost
        if vid in self.killed_fetch:
            raise RuntimeError("ERROR: yt-dlp exited with -15")
        return ib.FetchResult(str(self.cache / f"{vid}.mp4"), False)

    def index(self, path):
        vid = Path(path).stem
        self.indexed.append(vid)
        self.clock.t += self.index_cost
        if vid in self.killed_index:
            raise ib.IndexFailed(f"index_footage.py left no usable index for {vid}: "
                                 f"exit -15")
        t.synthetic_index(self.cache, vid)


def run(batch, cache, fetcher, *docs, deadline=None, reap=False):
    reqdir = batch / "work" / "supplement-requests"
    reqdir.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(docs):
        json.dump(doc, open(reqdir / f"{i:02d}.json", "w"))
    args = types.SimpleNamespace(supplement=[str(reqdir)], skip_index=False,
                                 deadline=None)
    lines = []
    kw = t.seams(fetcher)
    if deadline is not None:
        kw["deadline"] = deadline
    real = pd.topic_depth
    pd.topic_depth = fake_depth
    try:
        rc = t.quiet(ib.supplement_mode, batch, args, log=lines.append, reap=reap,
                     depth_cache=cache, ceiling=None, **kw)
    finally:
        pd.topic_depth = real
    return rc, json.load(open(batch / ib.REPORT_FILE)), "\n".join(lines)


def cut_of(entry):
    return [(c["video_id"], c["at"]) for c in entry[ib.WALL_CEILING]["candidates"]]


def req3(**kw):
    # 10 held + 25 wanted = 35: B (8) + C (12) + D (20) are all needed.
    return t.request([t.cand(B), t.cand(C), t.cand(D)], shots_wanted=25, **kw)


# ---------------------------------------------------------------------------
# The walk stops at the deadline

def test_no_deadline_walks_the_whole_request_as_before():
    batch, cache = t.world("dl-none")
    clock = Clock()
    f = Timed(cache, clock)
    rc, report, log = run(batch, cache, f, req3())
    assert rc == 0 and f.calls == [B, C, D]
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["outcome"] == "sources" and e["new_sources"] == [B, C, D]
    assert ib.WALL_CEILING not in e and "WALL_CEILING" not in log
    assert "DEADLINE" not in log


def test_a_deadline_in_the_middle_keeps_the_finished_and_lists_the_rest():
    batch, cache = t.world("dl-middle")
    clock = Clock()
    # B: fetch 0->10, index 10->20. C: fetch 20->30, index 30->40 - past 35.
    # The index of C is not killed (the stand-in returns), so C is in; D is
    # never downloaded.
    f = Timed(cache, clock)
    rc, report, log = run(batch, cache, f, req3(),
                          deadline=ib.Deadline(35, clock=clock))
    assert rc == 0
    assert f.calls == [B, C], f.calls          # no download after the deadline
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["new_sources"] == [B, C]
    assert report["sources_by_topic"][TOPIC] == [HELD, B, C]
    assert cut_of(e) == [(D, ib.CUT_BEFORE)]
    w = e[ib.WALL_CEILING]
    assert w["cause"] == "deadline" and w["task"] == "CF-0429"
    assert w["deadline"] == "1970-01-01T00:00:35Z"
    c = w["candidates"][0]
    assert (c["outcome"], c["refused_at"], c["entity"]) == (
        "wall_ceiling", "wall_ceiling", "Sandra Birch")
    assert D not in [x["video_id"] for x in report["failed"]]
    assert e["outcome"] == "sources"           # it did grow; the cut is beside it
    assert "WALL_CEILING (deadline): 1 candidate(s)" in log


def test_a_download_that_ends_past_the_deadline_is_not_indexed():
    batch, cache = t.world("dl-no-index")
    clock = Clock()
    f = Timed(cache, clock)
    # B: fetch 0->10, index 10->20. C: fetch 20->30 - past 25: no index child.
    rc, report, _ = run(batch, cache, f, req3(), deadline=ib.Deadline(25, clock=clock))
    assert f.calls == [B, C] and f.indexed == [B]
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["new_sources"] == [B]
    assert cut_of(e) == [(C, ib.CUT_INDEX), (D, ib.CUT_BEFORE)]
    assert report["failed"] == []              # not a loss: not `already_tried` later


def test_a_download_killed_at_the_deadline_is_not_a_lost_download():
    batch, cache = t.world("dl-killed-fetch")
    clock = Clock()
    f = Timed(cache, clock, killed_fetch=[C])
    rc, report, _ = run(batch, cache, f, req3(), deadline=ib.Deadline(25, clock=clock))
    assert rc == 0 and f.calls == [B, C]
    e = report[ib.SUPPLEMENT_KEY][0]
    assert cut_of(e) == [(C, ib.CUT_DOWNLOAD), (D, ib.CUT_BEFORE)]
    assert report["failed"] == [] and e["failed"] == []


def test_an_index_killed_at_the_deadline_is_not_an_index_failure():
    batch, cache = t.world("dl-killed-index")
    clock = Clock()
    f = Timed(cache, clock, killed_index=[C])
    # C: fetch 20->30 (before 35), index 30->40 and killed.
    rc, report, _ = run(batch, cache, f, req3(), deadline=ib.Deadline(35, clock=clock))
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["new_sources"] == [B]
    assert cut_of(e) == [(C, ib.CUT_INDEX), (D, ib.CUT_BEFORE)]
    assert report["failed"] == [] and report["index_failures"] == []


def test_a_deadline_already_gone_starts_nothing():
    batch, cache = t.world("dl-gone")
    clock = Clock(100)
    f = Timed(cache, clock)
    rc, report, log = run(batch, cache, f, req3(), deadline=ib.Deadline(50, clock=clock))
    assert rc == 0 and f.calls == []
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["outcome"] == ib.WALL_CEILING and e["shots_added"] == 0
    assert cut_of(e) == [(B, ib.CUT_BEFORE), (C, ib.CUT_BEFORE), (D, ib.CUT_BEFORE)]
    assert report["sources_by_topic"][TOPIC] == [HELD]


def test_a_request_the_deadline_cut_is_walked_on_next_time():
    batch, cache = t.world("dl-resume")
    clock = Clock()
    run(batch, cache, Timed(cache, clock), req3(), deadline=ib.Deadline(25, clock=clock))
    f = Timed(cache, Clock())
    rc, report, log = run(batch, cache, f, req3())
    assert "resuming" in log
    assert f.calls == [C, D]                   # B is held now, not fetched again
    assert report["sources_by_topic"][TOPIC] == [HELD, B, C, D]
    first, second = report[ib.SUPPLEMENT_KEY]
    assert first[ib.WALL_CEILING] and ib.WALL_CEILING not in second
    assert second["new_sources"] == [C, D]
    # and a finished request is still walked once
    f3 = Timed(cache, Clock())
    run(batch, cache, f3, req3())
    assert f3.calls == []


def test_01b_is_on_disk_after_every_new_source():
    batch, cache = t.world("dl-flush")
    seen = {}

    def peek(vid):
        doc = json.load(open(batch / ib.REPORT_FILE))
        e = (doc.get(ib.SUPPLEMENT_KEY) or [{}])[-1]
        seen[vid] = (doc["sources_by_topic"][TOPIC], e.get("outcome"))

    f = Timed(cache, Clock(), on_fetch=peek)
    run(batch, cache, f, req3())
    assert seen[B] == ([HELD], None)
    assert seen[C] == ([HELD, B], ib.IN_PROGRESS)
    assert seen[D] == ([HELD, B, C], ib.IN_PROGRESS)


# ---------------------------------------------------------------------------
# Real processes: the watcher kills what is in flight

def sleeper(pidfile, seconds=30):
    """A download stand-in that is a real child, like yt-dlp is."""
    def go():
        p = subprocess.Popen(["sleep", str(seconds)])
        Path(pidfile).write_text(str(p.pid))
        return p.wait()
    return go


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers kill(0); ps knows better
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


def test_the_watcher_kills_a_download_in_flight_at_the_deadline():
    batch, cache = t.world("dl-real")
    pidfile = batch / "sleep.pid"
    f = Timed(cache, Clock(), cost=0, index_cost=0,
              fetch_child={C: sleeper(pidfile)})
    started = time.monotonic()
    rc, report, _ = run(batch, cache, f, req3(),
                        deadline=ib.Deadline(time.time() + 1.0), reap=True)
    took = time.monotonic() - started
    assert rc == 0 and took < 8, took
    assert not alive(int(pidfile.read_text()))
    e = report[ib.SUPPLEMENT_KEY][0]
    assert e["new_sources"] == [B]
    assert cut_of(e) == [(C, ib.CUT_DOWNLOAD), (D, ib.CUT_BEFORE)]


def test_the_watcher_escalates_to_sigkill_after_the_grace():
    sent = []
    d = ib.Deadline(0, clock=lambda: 1.0)
    d.arm(descendants=lambda: [4242], send=lambda pid, sig: sent.append(sig),
          sweep=0.02, grace=0.05)
    time.sleep(0.3)
    d.disarm()
    assert sent[0] == signal.SIGTERM and signal.SIGKILL in sent
    assert d.killed == [4242]


def test_sigterm_is_the_deadline_now_and_01b_is_written():
    root = t.TMP / "dl-sigterm"
    child = subprocess.Popen([sys.executable, __file__, "--child", str(root)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
    pidfile = root / "batch" / "sleep.pid"
    until = time.monotonic() + 30
    while not pidfile.exists() and time.monotonic() < until and child.poll() is None:
        time.sleep(0.05)
    assert pidfile.exists(), child.communicate(timeout=5)
    time.sleep(0.2)
    child.send_signal(signal.SIGTERM)
    out, err = child.communicate(timeout=15)
    assert child.returncode == 0, (child.returncode, out[-500:], err[-1500:])
    assert not alive(int(pidfile.read_text()))
    report = json.load(open(root / "batch" / ib.REPORT_FILE))
    e = report[ib.SUPPLEMENT_KEY][0]
    assert report["sources_by_topic"][TOPIC] == [HELD, B]
    assert e[ib.WALL_CEILING]["cause"] == "sigterm"
    assert e[ib.WALL_CEILING]["deadline"] is None
    assert cut_of(e) == [(C, ib.CUT_DOWNLOAD), (D, ib.CUT_BEFORE)]


def child_main(root):
    """`--child <root>`: a supplement call with no deadline whose download of
    C is a real `sleep 30`, for the parent to SIGTERM."""
    t.TMP = Path(root).parent
    batch, cache = t.world(Path(root).name)
    f = Timed(cache, Clock(), cost=0, index_cost=0,
              fetch_child={C: sleeper(batch / "sleep.pid")})
    rc, _, _ = run(batch, cache, f, req3(), reap=True)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# The CLI

def test_the_deadline_is_epoch_or_iso():
    assert ib.parse_deadline("1790000000") == 1790000000.0
    assert ib.parse_deadline("1790000000.5") == 1790000000.5
    z = ib.parse_deadline("2026-09-28T12:00:00Z")
    assert z == ib.parse_deadline("2026-09-28T12:00:00") == ib.parse_deadline(
        "2026-09-28T15:00:00+03:00")
    try:
        ib.parse_deadline("tomorrow")
    except Exception as e:
        assert "neither epoch seconds nor ISO 8601" in str(e)
    else:
        raise AssertionError("a word is not a deadline")


def test_the_cli_refuses_a_deadline_without_supplement_and_a_bad_one():
    script = HERE.parent / "scripts" / "ingest_batch.py"
    for argv in (["--deadline", "1790000000"],
                 ["--supplement", "x.json", "--deadline", "soon"]):
        out = subprocess.run([sys.executable, str(script), str(t.TMP / "nope")] + argv,
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 2, (argv, out.returncode, out.stderr[-300:])
        assert "deadline" in out.stderr


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child_main(sys.argv[2])
    import shutil
    fails = total = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            total += 1
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                fails += 1
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{total - fails}/{total} passed")
    shutil.rmtree(t.TMP, ignore_errors=True)
    sys.exit(1 if fails else 0)

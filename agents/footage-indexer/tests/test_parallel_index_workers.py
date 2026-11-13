#!/usr/bin/env python3
"""CF-0332: sources are indexed side by side, and nothing else changes.

Pinned here, offline - no ffmpeg, no CLIP, no network, no Vision:

  - `workers=1` is the sequential walk: indexing never overlaps;
  - with N > 1 indexing overlaps (up to N at once) while downloads stay one
    at a time - the CF-0253 pacing is about YouTube, not about this machine;
  - the result of a parallel walk is the result of the sequential one, in the
    same order: fetched, aliases, failed and sources_by_topic, record for record;
  - a source two topics share is indexed once, under its own lock, and the
    second topic finds the first one's index (no two writers on one
    `shots.json` in the shared pool);
  - CF-0281 (`index_failed`) and CF-0316 (a watchdog kill gives the attempt
    back) keep working per source under parallel walks;
  - CF-0302 (the duration ceiling) keeps refusing per candidate;
  - a subprocess started from a worker thread is chained to its own ingest
    event (RUNLOG_PARENT handed down, not read from the process-wide
    os.environ), and os.environ is left as it was found;
  - the worker count is read from the CLI, then the environment, then the
    measured default; a Vision socket per slot only when asked for.

No pytest dependency - plain asserts, run directly.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0332-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from _runlog import runlog  # noqa: E402
import ingest_batch as ib  # noqa: E402


class Cuts:
    @staticmethod
    def compare(a, b):
        return {"distance": 0 if a["cut"] == b["cut"] else 40,
                "offset_seconds": 0.0, "overlap_frames": 8}

    @staticmethod
    def is_duplicate(cmp):
        return cmp["distance"] <= 12


def media(vid, where):
    p = where / f"{vid}.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(b"\x00")
    return p


def fingerprint_of(path):
    stem = Path(path).stem
    # `<cut>~<n>` is a re-upload of `<cut>`
    return {"kind": "dhash", "cut": stem.split("~")[0]}


def topic(tid, ids):
    return {"topic_id": tid, "evidence": {"youtube_video_ids": list(ids)}}


def no_measure(vid, record=None):
    return ib.Measured(None, "metadata", "not measured in this test")


class Meter:
    """Counts how many calls of one kind are running at the same instant."""

    def __init__(self):
        self.lock = threading.Lock()
        self.now = self.peak = 0
        self.calls = []

    @contextlib.contextmanager
    def inside(self, what):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
            self.calls.append(what)
        try:
            yield
        finally:
            with self.lock:
                self.now -= 1


def whole_index(path):
    dest = Path(path).with_suffix(".shots.json")
    dest.write_text(json.dumps({"source": str(path), "model": "m", "shots": [
        {"index": 0, "start": 0.0, "end": 1.0, "embedding": [0.1],
         "is_card": False, "description": ""}]}))


def run(topics, workers, *, bad=(), killed=(), gone=(), measure=no_measure,
        index_s=0.05, fetch_s=0.01, **kw):
    """ingest() with every seam injected; returns (result, meters, out)."""
    where = Path(tempfile.mkdtemp(prefix="pool-", dir=TMP))
    fetches, indexes = Meter(), Meter()

    def fetch(vid, note):
        with fetches.inside(vid):
            time.sleep(fetch_s)
            if vid in gone:
                raise RuntimeError(f"yt-dlp: {vid} is unavailable")
            return ib.FetchResult(str(media(vid, where)), False)

    def index(path):
        vid = Path(path).stem
        with indexes.inside(vid):
            time.sleep(index_s)
            if vid in bad:
                raise ib.IndexFailed(f"index_footage.py left no usable index for {vid}")
            if vid in killed:
                raise ib.IndexTimedOut(f"{vid} went quiet", code="index_timeout",
                                       silent_s=1800.0, ceiling_s=1800.0)
            whole_index(path)

    out = io.StringIO()
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            kw.setdefault("depth_floor", 0)
            result = ib.ingest(topics, {}, "batch-x", skip_index=False,
                               fetch=fetch, index=index, fingerprint=fingerprint_of,
                               sleep=lambda s: None, pause=0,
                               is_cached=lambda vid: False, measure=measure,
                               workers=workers, **kw)
    finally:
        ib.source_fingerprint = real
    return result, fetches, indexes, out.getvalue(), where


TOPICS = [topic("001", ["a1", "a2", "a3"]),
          topic("002", ["b1", "b1~re", "b2", "b3"]),
          topic("003", ["c1", "c2", "c3"]),
          topic("004", ["d1", "d2", "d3"]),
          topic("005", ["e1", "e2"])]


def strip(result, where):
    """The walk's result with the temp paths taken out, so two runs compare."""
    fetched, aliases, skipped, failed, by_topic = result
    s = str(where)

    def clean(x):
        return json.loads(json.dumps(x).replace(s, "<pool>"))
    return clean(fetched), clean(aliases), clean(skipped), clean(failed), by_topic


def test_one_worker_never_overlaps_indexing():
    _, fetches, indexes, _, _ = run(TOPICS, 1)
    assert indexes.peak == 1, indexes.peak
    assert fetches.peak == 1, fetches.peak


def test_n_workers_overlap_indexing_but_not_downloads():
    _, fetches, indexes, _, _ = run(TOPICS, 3, index_s=0.2)
    assert indexes.peak >= 2, f"indexing never overlapped (peak {indexes.peak})"
    assert indexes.peak <= 3, f"more than 3 indexes at once ({indexes.peak})"
    assert fetches.peak == 1, f"downloads overlapped ({fetches.peak})"


def test_parallel_walk_returns_the_sequential_result_in_order():
    kw = dict(bad={"a1", "c2"}, gone={"d1"}, killed={"e1"})
    seq, _, _, _, w1 = run(TOPICS, 1, **kw)
    par, _, _, _, w4 = run(TOPICS, 4, index_s=0.1, **kw)
    a, b = strip(seq, w1), strip(par, w4)
    names = ("fetched", "aliases", "skipped", "failed", "sources_by_topic")
    for name, x, y in zip(names, a, b):
        assert x == y, f"{name} differs:\n  seq {x}\n  par {y}"
    # and the result is not trivially empty
    assert len(a[0]) >= 8 and a[1] and a[3], a


def test_a_shared_source_is_indexed_once():
    topics = [topic("001", ["s1", "x1"]), topic("002", ["s1", "y1"]),
              topic("003", ["s1", "z1"])]
    (fetched, _, _, _, by_topic), _, indexes, _, _ = run(topics, 3, index_s=0.2)
    assert indexes.calls.count("s1") == 1, indexes.calls
    for tid in ("001", "002", "003"):
        assert "s1" in by_topic[tid], by_topic


def test_index_failed_and_watchdog_kill_stay_per_source():
    (fetched, _, _, failed, by_topic), _, _, _, _ = run(
        [topic("001", ["k1", "k2", "k3"]), topic("002", ["f1", "f2", "f3"])], 2,
        killed={"k1"}, bad={"f1"}, max_per_topic=2)
    got = {f["video_id"]: f for f in failed}
    assert got["f1"]["reason_code"] == ib.INDEX_FUNNEL_CODE, got["f1"]
    assert got["k1"][ib.WATCHDOG_CODE_KEY] == "index_timeout", got["k1"]
    # CF-0316: the kill did not spend the attempt, so with a cap of 2 topic 001
    # still reached two sources; CF-0281: 002 spent one on f1 and holds one.
    assert by_topic["001"] == ["k2", "k3"], by_topic
    assert by_topic["002"] == ["f2"], by_topic
    assert got["f1"]["replaced_by"] == ["f2"], got["f1"]


def test_the_duration_ceiling_still_refuses_per_candidate():
    def measure(vid, record=None):
        return ib.Measured(99999.0 if vid.endswith("long") else 60.0,
                           "metadata", None)
    (fetched, _, _, failed, by_topic), _, indexes, _, _ = run(
        [topic("001", ["t1long", "t2", "t3"]), topic("002", ["u1", "u2long", "u3"])],
        2, measure=measure)
    too_long = sorted(f["video_id"] for f in failed
                      if f["reason_code"] == ib.TOO_LONG_CODE)
    assert too_long == ["t1long", "u2long"], failed
    assert "t1long" not in indexes.calls and "u2long" not in indexes.calls
    assert by_topic == {"001": ["t2", "t3"], "002": ["u1", "u3"]}, by_topic


def test_a_worker_child_is_chained_to_its_own_ingest_event():
    """The env a worker thread hands a subprocess names the thread's own
    innermost event, not whatever run() another thread exported last."""
    seen = {}
    real = ib._run_index

    def fake(path):
        env = ib._worker_env()
        seen[Path(path).stem] = (env or {}).get("RUNLOG_PARENT")
        whole_index(path)
        import subprocess
        return subprocess.CompletedProcess([], 0, "", "")

    batch = TMP / "batch-events"
    batch.mkdir(exist_ok=True)
    before = {k: os.environ.get(k) for k in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    ib._run_index = fake
    try:
        with runlog.run("footage-indexer", "ingest", batch_dir=batch, name="t"):
            outer = {k: os.environ.get(k) for k in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
            where = Path(tempfile.mkdtemp(prefix="pool-", dir=TMP))
            out = io.StringIO()
            realfp, ib.source_fingerprint = ib.source_fingerprint, Cuts
            try:
                with contextlib.redirect_stdout(out):
                    ib.ingest([topic("001", ["p1", "p2"]), topic("002", ["q1", "q2"])],
                              {}, "batch-x", fetch=lambda v, n:
                              ib.FetchResult(str(media(v, where)), False),
                              fingerprint=fingerprint_of, sleep=lambda s: None,
                              pause=0, is_cached=lambda v: False, measure=no_measure,
                              depth_floor=0, workers=2)
            finally:
                ib.source_fingerprint = realfp
            after = {k: os.environ.get(k) for k in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    finally:
        ib._run_index = real
    assert after == outer, f"os.environ changed under the walk: {outer} -> {after}"
    assert {k: os.environ.get(k) for k in before} == before
    events = [json.loads(l) for l in (batch / "RUN_EVENTS.jsonl").open()]
    ingest_ids = {e["video"]: e["id"] for e in events
                  if e.get("kind") == "script" and e.get("status") == "start"
                  and e.get("video") in seen}
    assert set(seen) == {"p1", "p2", "q1", "q2"}, seen
    for vid, parent in seen.items():
        assert parent == ingest_ids[vid], (vid, parent, ingest_ids)


def test_the_sequential_path_hands_no_env_down():
    assert ib._worker_env() is None
    assert ib._env_kw() == {}


def test_worker_count_comes_from_cli_then_env_then_default():
    assert ib.index_workers(3, environ={}) == 3
    assert ib.index_workers(None, environ={ib.INDEX_WORKERS_ENV: "4"}) == 4
    assert ib.index_workers(None, environ={}) == ib.DEFAULT_INDEX_WORKERS
    assert ib.index_workers(0, environ={ib.INDEX_WORKERS_ENV: "x"}) == ib.DEFAULT_INDEX_WORKERS
    assert ib.index_workers(1, environ={ib.INDEX_WORKERS_ENV: "4"}) == 1


def test_vision_socket_per_slot_only_when_asked():
    real = ib.VISION_PER_WORKER
    try:
        ib.VISION_PER_WORKER = False
        assert ib.vision_slot_sockets(4) is None
        ib.VISION_PER_WORKER = True
        assert ib.vision_slot_sockets(1) is None
        socks = ib.vision_slot_sockets(3)
        assert len(set(socks)) == 3, socks
        # the CLI's --vision-per-worker wins over the switch, both ways
        assert ib.vision_slot_sockets(3, per_worker=False) is None
        ib.VISION_PER_WORKER = False
        assert len(ib.vision_slot_sockets(2, per_worker=True)) == 2
    finally:
        ib.VISION_PER_WORKER = real


def test_each_slot_gets_its_own_vision_socket():
    seen = {}
    real = ib._run_index

    def fake(path):
        env = ib._worker_env() or {}
        seen[Path(path).stem] = (threading.get_ident(), env.get(ib.VISION_SOCKET_ENV))
        time.sleep(0.05)
        whole_index(path)
        import subprocess
        return subprocess.CompletedProcess([], 0, "", "")

    where = Path(tempfile.mkdtemp(prefix="pool-", dir=TMP))
    ib._run_index = fake
    realfp, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ib.ingest([topic(f"00{i}", [f"v{i}a", f"v{i}b"]) for i in range(4)],
                      {}, "batch-x", fetch=lambda v, n:
                      ib.FetchResult(str(media(v, where)), False),
                      fingerprint=fingerprint_of, sleep=lambda s: None, pause=0,
                      is_cached=lambda v: False, measure=no_measure, depth_floor=0,
                      workers=2, vision_sockets=["/tmp/s0.sock", "/tmp/s1.sock"])
    finally:
        ib._run_index = real
        ib.source_fingerprint = realfp
    by_thread = {}
    for ident, sock in seen.values():
        by_thread.setdefault(ident, set()).add(sock)
    assert all(len(s) == 1 for s in by_thread.values()), by_thread
    assert {next(iter(s)) for s in by_thread.values()} <= {"/tmp/s0.sock", "/tmp/s1.sock"}
    assert len(seen) == 8, seen


if __name__ == "__main__":
    failures = ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)

#!/usr/bin/env python3
"""CF-0715: the walk writes the command center's progress file as it goes
(`<batch>/work/footage-progress.json` through the root's
`footage_progress.Tracker`), and every `pool_depth.topics[]` row carries
`indexed_at`.

Offline: the fetch, the index and the fingerprint are stand-ins, the batch is a
temp directory, nothing under shared/footage/ is read or written.
"""
import contextlib
import io
import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0715-")
from _temp_pool import fence_cache_index  # noqa: E402
fence_cache_index(TMP / "ff-pool")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from _runlog import runlog  # noqa: E402
import ingest_batch as ib  # noqa: E402
import pool_depth as pd  # noqa: E402

fp = runlog.sibling("footage_progress")
_n = [0]


class Cuts:
    @staticmethod
    def compare(a, b):
        return {"distance": 0 if a["cut"] == b["cut"] else 40,
                "offset_seconds": 0.0, "overlap_frames": 8}

    @staticmethod
    def is_duplicate(cmp):
        return cmp["distance"] <= 12


def media(vid):
    p = TMP / "cache" / f"{vid}.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(b"\x00")
    return p


def no_measure(vid, record=None):
    return ib.Measured(None, "metadata", "not measured in this test")


def fetch(bad=()):
    def f(vid, note):
        if vid in bad:
            raise RuntimeError(f"yt-dlp: {vid} is unavailable")
        return ib.FetchResult(str(media(vid)), False)
    return f


def topic(tid, ids):
    return {"topic_id": tid, "evidence": {"youtube_video_ids": list(ids)}}


def batch():
    _n[0] += 1
    d = TMP / f"batch{_n[0]}"
    d.mkdir()
    return d


def run(topics, progress, bad=(), depths=None, verdict=None):
    out, err = io.StringIO(), io.StringIO()
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return ib.ingest(topics, verdict or {}, "batch-x", skip_index=False,
                             fetch=fetch(bad), index=lambda path: None,
                             fingerprint=lambda path: {"kind": "dhash",
                                                       "cut": Path(path).stem},
                             sleep=lambda s: None, pause=0,
                             is_cached=lambda vid: False, measure=no_measure,
                             depth_floor=0, depth_cache=TMP / "no-pool",
                             depths=depths, tracker=progress)
    finally:
        ib.source_fingerprint = real


def rows_of(bd):
    doc = json.loads((bd / "work" / "footage-progress.json").read_text())
    return doc, {t["topic_id"]: t for t in doc["topics"]}


def test_the_walk_writes_the_progress_file():
    bd = batch()
    tr = ib.progress_tracker(bd)
    assert tr is not None, "the root's footage_progress is reachable"
    fetched, aliases, skipped, failed, by_topic = run(
        [topic("t1", ["a", "b"]), topic("t2", ["c", "d", "e"])], tr, bad=("c", "d", "e"))
    doc, rows = rows_of(bd)
    assert doc["schema"] == fp.SCHEMA and doc["needed"] == ib.SOURCES_WANTED
    assert doc["max_attempts"] == ib.MAX_ATTEMPTS_PER_TOPIC
    assert (rows["t1"]["state"], rows["t1"]["collected"], rows["t1"]["attempts"]) == (
        "collecting", 2, 2), rows["t1"]
    assert rows["t1"]["last_video"] == "b"
    assert rows["t2"]["state"] == "refused", rows["t2"]
    assert rows["t2"]["reason_code"] == [s for s in skipped if s["topic_id"] == "t2"][0]["reason_code"]
    assert doc["finished"] is False


def test_settle_from_the_report_finishes_it():
    bd = batch()
    tr = ib.progress_tracker(bd)
    depths = []
    got = run([topic("t1", ["a", "b"]), topic("t2", ["c", "d"])], tr, bad=("c", "d"),
              depths=depths)
    report = ib.build_report(bd, *got, depths=depths)
    tr.settle(report)
    doc, rows = rows_of(bd)
    assert doc["finished"] is True
    assert rows["t1"]["state"] == "collected" and rows["t2"]["state"] == "refused"
    assert rows["t1"]["indexed_at"] == [d for d in depths if d["topic_id"] == "t1"][0]["indexed_at"]
    ans = fp.footage_progress(bd, events=[])
    assert ans["source"] == "file" and ans["counts"] == {"collected": 1, "refused": 1}


def test_a_compliance_skip_is_refused_at_once():
    bd = batch()
    tr = ib.progress_tracker(bd)
    screening = ib.Screening(ran=True, verdict={"t1": "pass"}, reserve={"t2"})
    run([topic("t1", ["a", "b"]), topic("t2", ["c", "d"])], tr, verdict=screening)
    _doc, rows = rows_of(bd)
    assert rows["t2"]["state"] == "refused" and rows["t2"]["reason_code"] == ib.RESERVE_SKIP_CODE, rows


def test_indexed_at_is_when_the_newest_source_got_in():
    depths = []
    run([topic("t1", ["a", "b"]), topic("t2", ["c"])], None, bad=("c",), depths=depths)
    by = {d["topic_id"]: d for d in depths}
    for d in depths:
        assert isinstance(d["indexed_at"], str) and d["indexed_at"].endswith("Z"), d
    # t2 took no source: its row carries the moment it was measured, after t1's admit
    assert by["t1"]["indexed_at"] <= by["t2"]["indexed_at"]


def test_depth_record_keeps_its_keys_and_adds_indexed_at():
    depth = pd.TopicDepth("t", 2, 99, 99, 300.0, True, None, [])
    rec = pd.depth_record(depth, indexed_at="2026-10-13T10:00:00.000Z")
    assert rec["indexed_at"] == "2026-10-13T10:00:00.000Z"
    for k in ("topic_id", "sources", "shots", "usable_shots", "weak_shots",
              "available_shots", "usable_seconds", "floor", "deep_enough",
              "measured", "at_source_floor", "error", "exhausted", "attempts",
              "per_source"):
        assert k in rec, k
    assert pd.depth_record(depth)["indexed_at"].endswith("Z")
    block = pd.pool_depth_report([rec])
    assert block["topics"][0]["indexed_at"] == "2026-10-13T10:00:00.000Z"


def test_no_root_module_means_no_file_and_no_failure():
    real = ib.runlog

    class NoSibling:
        pass
    ib.runlog = NoSibling()
    try:
        assert ib.progress_tracker(batch()) is None
    finally:
        ib.runlog = real


def test_a_tracker_that_raises_never_stops_the_walk():
    class Broken:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise OSError("disk full")
            return boom
    fetched, *_ = run([topic("t1", ["a", "b"])], Broken())
    assert [f["video_id"] for f in fetched] == ["a", "b"]


def test_parallel_walks_note_through_one_lock():
    bd = batch()
    tr = ib.progress_tracker(bd)
    ts = [threading.Thread(target=tr.walking, args=(f"t{i}", 1, 1)) for i in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    _doc, rows = rows_of(bd)
    assert len(rows) == 10


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

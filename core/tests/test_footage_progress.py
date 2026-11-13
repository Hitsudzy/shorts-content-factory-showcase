#!/usr/bin/env python3
"""CF-0715: footage collection per topic for the command center
(shared/runlog/footage_progress.py) - the Footage Indexer's progress file is
written whole through a temporary file, the reader answers from it, lays a
newer 01b report over it, stops what a dead run left unsettled, and falls back
to RUN_EVENTS (read-only, through event_log) and to the report alone for a
batch without the file. Russian lines by funnel.reason_ru. Temp trees only."""
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

import event_log          # noqa: E402
import footage_progress as fp  # noqa: E402
import funnel             # noqa: E402

TMP = tmp_root("cf0715-")
_n = [0]


def _batch(topics=("t1", "t2", "t3")):
    _n[0] += 1
    d = TMP / f"b{_n[0]}"
    d.mkdir()
    (d / fp.TREND_FILE).write_text(json.dumps(
        {"topics": [{"topic_id": t} for t in topics]}))
    return d


def _clock():
    c = [0]

    def now():
        c[0] += 1
        return f"2026-10-13T10:00:{c[0]:02d}.000Z"
    return now


def _report(**kw):
    rep = {
        "sources_by_topic": {"t1": ["a", "b"], "t2": ["c"]},
        "skipped_topics": [{"topic_id": "t2", "reason_code": "no_second_source",
                            "reason": "one source", "stage": "footage-indexer"},
                           {"topic_id": "t3", "reason_code": "reserve_unused",
                            "stage": "footage-indexer"}],
        "two_source_floor": {"wanted": 2, "max_attempts_per_topic": 4},
        "pool_depth": {"floor": 20, "thin": ["t1"], "topics": [
            {"topic_id": "t1", "usable_shots": 12, "floor": 20, "attempts": 3,
             "indexed_at": "2026-10-13T09:59:00.000Z"},
            {"topic_id": "t2", "usable_shots": 4, "floor": 20, "attempts": 4,
             "indexed_at": "2026-10-13T09:58:00.000Z"}]},
    }
    rep.update(kw)
    return rep


def _write_report(bd, rep, mtime=None):
    p = bd / fp.REPORT_FILE
    p.write_text(json.dumps(rep))
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def _ev(i, status, video=None, topic=None, eid=None, **params):
    p = dict(params)
    if topic:
        p["topic"] = topic
    return {"ts": f"2026-10-13T11:00:{i:02d}.000Z", "kind": "script",
            "stage": "footage-indexer", "step": "ingest", "video": video,
            "status": status, "params": p or None, "id": eid or f"e{i}"}


def _journal(bd, events):
    with open(bd / "RUN_EVENTS.jsonl", "w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def _rows(ans):
    return {t["topic_id"]: t for t in ans["topics"]}


# ------------------------------------------------------------------ the writer

def test_the_tracker_writes_the_file_whole_as_the_walk_goes():
    bd = _batch()
    tr = fp.Tracker(bd, needed=2, max_attempts=4, floor=20, now=_clock())
    tr.start(["t1", "t2", "t3"])
    doc = json.loads(fp.progress_path(bd).read_text())
    assert doc["schema"] == fp.SCHEMA and doc["finished"] is False
    assert [t["state"] for t in doc["topics"]] == ["queued"] * 3
    assert doc["max_attempts"] == 4 and doc["floor"] == 20
    tr.skip("t3", "reserve_unused")
    tr.walking("t1", 0, 0)
    tr.walking("t1", 1, 2, video="b")
    doc = json.loads(fp.progress_path(bd).read_text())
    t1 = {t["topic_id"]: t for t in doc["topics"]}["t1"]
    assert (t1["state"], t1["collected"], t1["attempts"], t1["last_video"]) == (
        "collecting", 1, 2, "b"), t1
    assert doc["started_at"] < doc["updated_at"]
    leftovers = [p.name for p in (bd / "work").iterdir() if p.name != "footage-progress.json"]
    assert leftovers == [], leftovers


def test_settle_decides_every_topic_the_report_names():
    bd = _batch()
    tr = fp.Tracker(bd, now=_clock())
    tr.start(["t1", "t2", "t3"])
    tr.walking("t1", 2, 3)
    rep = _report(sources_by_topic={"t1": ["a", "b"], "t2": ["c"], "t4": ["d", "e"]},
                  skipped_topics=[{"topic_id": "t3", "reason_code": "reserve_unused"}])
    rep["two_source_floor"]["kept_on_own_graphics"] = ["t2"]
    tr.settle(rep)
    doc = json.loads(fp.progress_path(bd).read_text())
    rows = {t["topic_id"]: t for t in doc["topics"]}
    assert doc["finished"] is True
    assert rows["t1"]["state"] == "collected" and rows["t1"]["reason_code"] == "pool_too_thin"
    assert rows["t1"]["indexed_at"] == "2026-10-13T09:59:00.000Z"
    assert rows["t1"]["usable_shots"] == 12 and rows["t1"]["attempts"] == 3
    assert rows["t2"]["state"] == "short" and rows["t2"]["reason_code"] == "kept_on_own_graphics"
    assert rows["t3"]["state"] == "refused" and rows["t3"]["reason_code"] == "reserve_unused"
    assert rows["t4"]["state"] == "collected" and rows["t4"]["reason_code"] is None, rows["t4"]
    assert list(rows) == ["t1", "t2", "t3", "t4"]


def test_a_write_that_fails_never_stops_the_walk():
    bd = _batch()
    (bd / "work").write_text("a file where the directory should be")
    tr = fp.Tracker(bd, now=_clock())
    tr.start(["t1"])
    tr.walking("t1", 1, 1)
    tr.settle(_report())
    tr.fail("boom")
    assert fp.tracker(bd) is not None


def test_parallel_walks_leave_a_file_that_reads():
    bd = _batch()
    tr = fp.Tracker(bd)
    tids = [f"t{i}" for i in range(8)]
    tr.start(tids)

    def walk(tid):
        for k in range(15):
            tr.walking(tid, k // 5, k)
    ts = [threading.Thread(target=walk, args=(t,)) for t in tids]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    doc = json.loads(fp.progress_path(bd).read_text())
    assert all(t["attempts"] == 14 and t["collected"] == 2 for t in doc["topics"]), doc
    assert [p.name for p in (bd / "work").iterdir()] == ["footage-progress.json"]


def test_fail_stops_what_is_unsettled():
    bd = _batch()
    tr = fp.Tracker(bd, now=_clock())
    tr.start(["t1", "t2"])
    tr.skip("t2", "not_screened")
    tr.walking("t1", 1, 1)
    tr.fail("KeyboardInterrupt")
    ans = fp.footage_progress(bd, events=[])
    rows = _rows(ans)
    assert rows["t1"]["state"] == "stopped" and rows["t2"]["state"] == "refused"
    assert rows["t1"]["state_ru"] == fp.STATE_RU["stopped"]


# ------------------------------------------------------------------ the reader: the file

def test_the_reader_answers_from_the_file_with_russian_reasons():
    bd = _batch()
    tr = fp.Tracker(bd, now=_clock())
    tr.start(["t1", "t2", "t3"])
    tr.walking("t1", 1, 1, video="a")
    tr.skip("t3", "reserve_unused")
    _journal(bd, [_ev(1, "start", eid="run")])
    ans = fp.footage_progress(bd)
    assert ans["source"] == "file" and ans["running"] is True and ans["finished"] is False
    rows = _rows(ans)
    assert rows["t1"]["state"] == "collecting" and rows["t1"]["collected"] == 1
    assert rows["t1"]["needed"] == 2 and rows["t1"]["reason"] is None
    assert rows["t2"]["state"] == "queued" and rows["t2"]["state_ru"] == "ждёт очереди"
    assert rows["t3"]["reason"] == funnel.reason_ru("reserve_unused") and rows["t3"]["reason"]
    assert ans["counts"] == {"collecting": 1, "queued": 1, "refused": 1}
    assert set(rows["t1"]) >= set(fp.ROW_KEYS) | {"state_ru", "reason"}


def test_an_unfinished_file_of_a_run_that_ended_reads_stopped():
    bd = _batch()
    tr = fp.Tracker(bd, now=_clock())
    tr.start(["t1", "t2"])
    tr.walking("t1", 1, 1)
    _journal(bd, [_ev(1, "start", eid="run"), _ev(2, "failed", eid="run")])
    ans = fp.footage_progress(bd)
    assert ans["running"] is False
    assert {t["state"] for t in ans["topics"]} == {"stopped"}


def test_a_report_newer_than_the_file_is_laid_over_it():
    bd = _batch()
    tr = fp.Tracker(bd, now=_clock())
    tr.start(["t1", "t2", "t3"])
    tr.settle(_report())
    first = _rows(fp.footage_progress(bd))
    assert first["t2"]["state"] == "refused" and first["t2"]["collected"] == 1
    # a supplement pass amended the report afterwards: t2 got its second source
    rep = _report(sources_by_topic={"t1": ["a", "b"], "t2": ["c", "z"]},
                  skipped_topics=[{"topic_id": "t3", "reason_code": "reserve_unused"}])
    _write_report(bd, rep, mtime=time.time() + 60)
    ans = fp.footage_progress(bd)
    rows = _rows(ans)
    assert ans["source"] == "file" and ans["finished"] is True
    assert rows["t2"]["state"] == "collected" and rows["t2"]["collected"] == 2, rows["t2"]
    assert ans["updated_at"] >= rows["t2"]["updated_at"]


def test_a_broken_file_is_said_and_the_events_answer():
    bd = _batch(topics=("t1",))
    (bd / "work").mkdir()
    fp.progress_path(bd).write_text("{half")
    _journal(bd, [_ev(1, "start", eid="run"), _ev(2, "start", "a", "t1", eid="s1")])
    ans = fp.footage_progress(bd)
    assert ans["source"] == "events" and ans["error"] and "footage-progress.json" in ans["error"]
    assert _rows(ans)["t1"]["state"] == "collecting"


# ------------------------------------------------------------------ the reader: the fallbacks

def _walk_events():
    return [
        _ev(1, "start", eid="run"),
        _ev(2, "start", "a", "t1", eid="s1"), _ev(3, "done", "a", "t1", eid="s1"),
        _ev(4, "start", "b", "t1", eid="s2"),
        _ev(5, "done", "b", "t1", eid="s2", fetch_failed="HTTP 403", fetch_rung="first"),
        _ev(6, "start", "c", "t1", eid="s3"),
        _ev(7, "failed", "c", "t1", eid="s3"),
        _ev(8, "start", "d", "t2", eid="s4"),
    ]


def test_events_rebuild_the_progress_of_a_batch_without_the_file():
    bd = _batch()
    _journal(bd, _walk_events())
    ans = fp.footage_progress(bd)
    rows = _rows(ans)
    assert ans["source"] == "events" and ans["running"] is True and not ans["finished"]
    assert (rows["t1"]["attempts"], rows["t1"]["collected"], rows["t1"]["state"]) == (3, 1, "collecting")
    assert rows["t1"]["last_video"] == "c" and rows["t1"]["updated_at"] == "2026-10-13T11:00:07.000Z"
    assert (rows["t2"]["attempts"], rows["t2"]["collected"]) == (1, 0)
    assert rows["t3"]["state"] == "queued"
    assert ans["started_at"] == "2026-10-13T11:00:01.000Z"
    assert ans["updated_at"] == "2026-10-13T11:00:08.000Z"


def test_events_of_a_run_that_ended_without_a_report_read_stopped():
    bd = _batch()
    _journal(bd, _walk_events() + [_ev(9, "failed", eid="run")])
    ans = fp.footage_progress(bd)
    assert ans["running"] is False
    assert {t["state"] for t in ans["topics"]} == {"stopped"}


def test_events_with_a_report_are_settled_by_it():
    bd = _batch()
    _journal(bd, _walk_events() + [_ev(9, "done", eid="run")])
    _write_report(bd, _report())
    ans = fp.footage_progress(bd)
    rows = _rows(ans)
    assert ans["source"] == "events" and ans["finished"] is True
    assert rows["t1"]["state"] == "collected" and rows["t1"]["collected"] == 2
    assert rows["t1"]["reason"] == funnel.reason_ru("pool_too_thin")
    assert rows["t2"]["state"] == "refused" and rows["t2"]["reason"] == funnel.reason_ru("no_second_source")
    assert rows["t3"]["state"] == "refused"


def test_the_events_are_only_read():
    """Loaded through event_log (CF-0718): its cached events refuse writes, so
    a reader that wrote into one would raise here."""
    bd = _batch()
    _journal(bd, _walk_events())
    event_log.clear()
    before = json.dumps(event_log.load_events(bd))
    fp.footage_progress(bd)
    fp.footage_progress(bd, events=event_log.load_events(bd))
    assert json.dumps(event_log.load_events(bd)) == before


def test_other_stages_events_are_not_footage():
    bd = _batch()
    ev = _ev(1, "start", "a", "t1")
    ev["stage"] = "video-editor"
    _journal(bd, [ev])
    assert fp.footage_progress(bd)["source"] == "none"


def test_the_report_alone_answers_an_old_batch():
    bd = _batch()
    _write_report(bd, _report())
    ans = fp.footage_progress(bd)
    assert ans["source"] == "report" and ans["finished"] is True and ans["running"] is False
    assert _rows(ans)["t1"]["indexed_at"] == "2026-10-13T09:59:00.000Z"


def test_nothing_on_disk_is_nothing():
    bd = _batch()
    ans = fp.footage_progress(bd)
    assert ans["source"] == "none" and ans["topics"] == [] and ans["error"] is None


def test_a_legacy_code_is_counted_under_its_current_name():
    bd = _batch(topics=("t1",))
    tr = fp.Tracker(bd)
    tr.start(["t1"])
    tr.skip("t1", "no_dated_source")
    row = _rows(fp.footage_progress(bd, events=[]))["t1"]
    assert row["reason_code"] == "no_source" and row["reason"] == funnel.reason_ru("no_source")


def test_an_unknown_code_has_no_russian_line():
    bd = _batch(topics=("t1",))
    tr = fp.Tracker(bd)
    tr.start(["t1"])
    tr.skip("t1", "made_up_code")
    row = _rows(fp.footage_progress(bd, events=[]))["t1"]
    assert row["reason_code"] == "made_up_code" and row["reason"] is None


def test_the_cli_prints_the_answer():
    import contextlib
    import io
    bd = _batch()
    _write_report(bd, _report())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert fp.main([str(bd)]) == 0
    assert json.loads(buf.getvalue())["source"] == "report"


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

#!/usr/bin/env python3
"""CC-0119 (CF-0718): the API reads a batch's RUN_EVENTS.jsonl through the
factory's cached loader `shared/runlog/event_log.load_events` - the markers
(`GET /api/batches/{c}/{b}/stages`, `api/batches.py` `_markers`, which the
topics read too), the usage report (`GET /api/maintenance/usage/{c}/{b}`,
`api/maintenance.py`) and the summary (`GET /api/batches/{c}/{b}/summary`,
`summary.compute`, the factory's own reader).

In-process (starlette's TestClient) against a stand-in factory root in a
temp dir - a channel config and one batch directory written by the test; the
factory's code is this checkout's; nothing live is read, no network.

What is pinned:

* each path loads twice - the second time after a line was appended to the
  journal - and the second answer shows the new event;
* the second load is the loader's tail read (`event_log.stats()`:
  `tail_reads` up, `full_reads` not), never `runlog.read_events` (patched to
  fail while the routes answer);
* the cached events are read-only (`Event`, a write is a TypeError) and the
  routes answer all the same - nothing in api/ writes into an event row.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

from _tmproot import tmp_root                        # noqa: E402
from api import factory                              # noqa: E402
from api.app import create_app                       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-event-log-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
_N = [0]


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ts(minutes_ago):
    return (datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


def marker(status, stage, minutes_ago, note=None):
    e = {"ts": _ts(minutes_ago), "kind": "marker", "stage": stage, "status": status}
    if note:
        e["note"] = note
    return e


def usage(stage, inp, computed, minutes_ago):
    return {"ts": _ts(minutes_ago), "kind": "usage", "stage": stage, "video": None,
            "model": "opus", "role": "main", "agent": None, "session": "s1", "calls": 2,
            "minutes": 1.0, "first": 1.0, "last": 61.0,
            "computed": computed, "window": None,
            "usage": {"input": inp, "cache_write": 10, "cache_read": 100, "output": 5,
                      "thinking": 0}}


def _lines(events):
    return "".join(json.dumps(e) + "\n" for e in events)


def a_batch():
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    _w(root / "channels" / "reel.json", json.dumps({"channel_id": "reel"}))
    d = root / "pipeline" / "reel" / "2026-10-01T1100Z"
    _w(d / "RUN_EVENTS.jsonl", _lines([
        marker("batch-start", None, 60),
        marker("stage-start", "trend-hunter", 59),
        usage("trend-hunter", 40, "2026-10-01T11:30:00Z", 50),
    ]))
    return root, d


def append(d, *events):
    with open(d / "RUN_EVENTS.jsonl", "a", encoding="utf-8") as fh:
        fh.write(_lines(events))


def client(root):
    return TestClient(create_app(Settings(factory_root=root), token="tok"), client=LOCAL,
                      base_url=BASE)


class NoReadEvents:
    """`runlog.read_events` fails while it is on: the API's paths must not
    reach it (the factory's own loader is `event_log.load_events`)."""

    def __enter__(self):
        self.rl = factory.runlog()
        self.saved = self.rl.read_events

        def no(*a, **k):
            raise AssertionError("runlog.read_events called - not the cached loader")
        self.rl.read_events = no
        return self

    def __exit__(self, *a):
        self.rl.read_events = self.saved


def _el():
    return factory.runlog().sibling("event_log")


def _delta(before):
    now = _el().stats()
    return {k: now[k] - before[k] for k in ("hits", "tail_reads", "full_reads")}


# --------------------------------------------------------------------- the markers
def test_the_markers_read_an_appended_tail():
    root, d = a_batch()
    c = client(root)
    url = "/api/batches/reel/2026-10-01T1100Z/stages"
    with NoReadEvents():
        r = c.get(url)
        assert r.status_code == 200, r.text
        one = r.json()
        assert [m["marker"] for m in one["markers"]] == ["batch-start", "stage-start"], one
        assert one["open_stages"] == ["trend-hunter"] and one["closed"] is False
        before = _el().stats()
        append(d, marker("stage-done", "trend-hunter", 30, note="two topics"),
               marker("batch-done", None, 29))
        two = c.get(url).json()
    assert [m["marker"] for m in two["markers"]] == ["batch-start", "stage-start", "stage-done",
                                                     "batch-done"], two["markers"]
    assert two["markers"][2]["note"] == "two topics"
    assert two["closed"] is True and two["open_stages"] == [], two
    got = _delta(before)
    assert got["tail_reads"] == 1 and got["full_reads"] == 0, got


def test_the_topics_take_the_same_markers():
    """`api/topics.py` reads the markers through `batches._markers` - the
    same loader; the markers it gets are plain dicts."""
    from api import batches
    root, d = a_batch()
    with NoReadEvents():
        marks = batches._markers(d)
        append(d, marker("stage-done", "trend-hunter", 30))
        marks2 = batches._markers(d)
    assert [m["marker"] for m in marks] == ["batch-start", "stage-start"]
    assert [m["marker"] for m in marks2][-1] == "stage-done", marks2
    marks2[-1]["note"] = "a plain dict"                     # the API's own row, writable


# --------------------------------------------------------------------- the usage report
def test_the_usage_report_reads_an_appended_tail():
    root, d = a_batch()
    c = client(root)
    url = "/api/maintenance/usage/reel/2026-10-01T1100Z"
    with NoReadEvents():
        r = c.get(url)
        assert r.status_code == 200, r.text
        one = r.json()
        assert one["ok"] is True and one["computed"] == "2026-10-01T11:30:00Z", one
        assert [x["stage"] for x in one["rows"]] == ["trend-hunter"]
        assert one["totals"]["input"] == 40, one["totals"]
        before = _el().stats()
        append(d, usage("trend-hunter", 41, "2026-10-01T11:45:00Z", 20),
               usage("video-editor", 60, "2026-10-01T11:45:00Z", 19))
        two = c.get(url).json()
    assert two["computed"] == "2026-10-01T11:45:00Z", two
    assert [x["stage"] for x in two["rows"]] == ["trend-hunter", "video-editor"], two["rows"]
    assert two["totals"]["input"] == 101, two["totals"]
    got = _delta(before)
    assert got["tail_reads"] == 1 and got["full_reads"] == 0, got


# --------------------------------------------------------------------- the summary
def test_the_summary_reads_an_appended_tail():
    root, d = a_batch()
    c = client(root)
    url = "/api/batches/reel/2026-10-01T1100Z/summary"
    with NoReadEvents():
        r = c.get(url)
        assert r.status_code == 200, r.text
        one = r.json()
        assert one["data_error"] is None, one["data_error"]
        assert one["data"]["counts"]["events"] == 3, one["data"]["counts"]
        before = _el().stats()
        append(d, marker("stage-done", "trend-hunter", 30))
        two = c.get(url).json()
    assert two["cached"] is False and two["data"]["counts"]["events"] == 4, two["data"]["counts"]
    got = _delta(before)
    assert got["tail_reads"] >= 1 and got["full_reads"] == 0, got


# --------------------------------------------------------------------- read-only rows
def test_the_cached_events_are_read_only():
    root, d = a_batch()
    ev = _el().load_events(d)
    assert ev and all(isinstance(e, dict) for e in ev)
    try:
        ev[0]["kind"] = "changed"
    except TypeError:
        pass
    else:
        raise AssertionError("a cached event took a write")
    assert _el().load_events(d)[0]["kind"] == "marker"
    # the routes answer over those same read-only rows
    c = client(root)
    assert c.get("/api/batches/reel/2026-10-01T1100Z/stages").status_code == 200
    assert c.get("/api/maintenance/usage/reel/2026-10-01T1100Z").status_code == 200


if __name__ == "__main__":
    tests = [(k, fn) for k, fn in list(globals().items()) if k.startswith("test_") and callable(fn)]
    fails = 0
    for k, fn in tests:
        try:
            fn()
            print("ok  ", k)
        except Exception as e:                          # noqa: BLE001
            fails += 1
            print("FAIL", k, type(e).__name__, e)
    print(f"{len(tests) - fails}/{len(tests)} passed")
    sys.exit(1 if fails else 0)

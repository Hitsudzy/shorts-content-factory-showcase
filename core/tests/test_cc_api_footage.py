#!/usr/bin/env python3
"""CC-0119: the Footage Indexer's collection per topic in the command center's
API (`api/footage.py`, `GET /api/batches/{channel}/{batch_id}/footage`, over
the factory's `shared/runlog/footage_progress.footage_progress`, CF-0715).

Everything runs in-process (starlette's TestClient) against a stand-in
factory root in a temp dir: batch directories with a progress file, a
RUN_EVENTS.jsonl, a 01 and a 01b written by the test. The factory's *code*
(footage_progress, funnel, event_log, runlog) is this checkout's, as in
production; nothing of the live factory is read, no network.

What is pinned:

* the contract: the route, GET only, version 0.48.0, `BatchProblem` on 404,
  `BatchFootage` / `FootageTopic` fields, `TopicDepth.indexed_at`;
* `source: "file"` - the progress file's rows as the factory answers them,
  a `last_video` with an absolute path cut by `paths.clean` (outside the
  root `.../<name>`, inside relative); no absolute path in the body;
* `source: "events"` - a batch with no progress file (FI 2.3.2): the
  journal's topics collecting / queued while the run is open;
* `source: "none"` - an empty batch: `topics: []`;
* the answer is kept per state of the files: a second read is `cached`, a
  progress file rewritten (mtime moved) - or a new journal line - computes
  afresh;
* an unknown batch is 404 `unknown_batch` in Russian;
* the module never names a writer (`write_progress`, `Tracker`, `main`, ...).
"""
import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import footage                              # noqa: E402
from api.app import create_app                       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-footage-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
ROUTE = "/api/batches/{channel}/{batch_id}/footage"
FORBIDDEN = {"write_progress", "Tracker", "tracker", "main", "write_text", "write_bytes",
             "unlink", "mkdir", "rename", "replace", "subprocess"}
_N = [0]


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def factory_root():
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    _w(root / "channels" / "reel.json", json.dumps({"channel_id": "reel"}))
    return root


def batch(root, name):
    d = root / "pipeline" / "reel" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def client(root):
    return TestClient(create_app(Settings(factory_root=root), token="tok"), client=LOCAL,
                      base_url=BASE)


def get(root, name):
    r = client(root).get(f"/api/batches/reel/{name}/footage")
    return r.status_code, r.json(), r.text


def _row(tid, state, collected, last_video=None, reason_code=None):
    return {"topic_id": tid, "state": state, "collected": collected, "needed": 2,
            "attempts": collected + 1, "last_video": last_video, "usable_shots": None,
            "floor": None, "indexed_at": None, "reason_code": reason_code,
            "updated_at": "2026-10-13T11:00:05Z"}


def progress(d, topics, finished=False):
    doc = {"schema": "footage-progress/1", "stage": "footage-indexer", "batch": d.name,
           "started_at": "2026-10-13T11:00:00Z", "updated_at": "2026-10-13T11:00:05Z",
           "finished": finished, "needed": 2, "max_attempts": 4, "floor": None,
           "error": None, "topics": topics}
    return _w(d / "work" / "footage-progress.json", json.dumps(doc))


def _ev(i, status, video=None, topic=None, eid=None):
    return {"ts": f"2026-10-13T11:00:{i:02d}.000Z", "kind": "script",
            "stage": "footage-indexer", "step": "ingest", "video": video,
            "status": status, "params": {"topic": topic} if topic else None,
            "id": eid or f"e{i}"}


def journal(d, events):
    _w(d / "RUN_EVENTS.jsonl", "".join(json.dumps(e) + "\n" for e in events))


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_footage_route_get_only():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    assert sorted(spec["paths"][ROUTE]) == ["get"]
    get_ = spec["paths"][ROUTE]["get"]
    assert [p["name"] for p in get_["parameters"]] == ["channel", "batch_id"]
    ref = get_["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/BatchProblem"), ref
    schemas = spec["components"]["schemas"]
    assert set(schemas["BatchFootage"]["properties"]) == {
        "batch", "channel", "batch_id", "source", "file", "started_at", "updated_at",
        "finished", "running", "needed", "topics", "counts", "error", "cached", "poll_s"}
    assert set(schemas["FootageTopic"]["properties"]) == {
        "topic_id", "state", "state_ru", "collected", "needed", "attempts", "last_video",
        "usable_shots", "floor", "indexed_at", "reason_code", "reason", "reason_ru",
        "updated_at"}
    assert "indexed_at" in schemas["TopicDepth"]["properties"]
    assert "indexed_at" not in schemas["TopicDepth"].get("required", [])


def test_the_module_names_no_writer():
    src = (ROOT / "api" / "footage.py").read_text(encoding="utf-8")
    named = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Name):
            named.add(n.id)
        elif isinstance(n, ast.Attribute):
            named.add(n.attr)
    assert not named & FORBIDDEN, named & FORBIDDEN


# --------------------------------------------------------------------- the answer
def test_the_progress_file_is_the_source_and_a_path_is_cut():
    root = factory_root()
    d = batch(root, "2026-10-13T1100Z")
    inside = d / "work" / "fetch" / "vid-a.mp4"
    progress(d, [_row("reel-001", "collected", 2, last_video=str(inside)),
                 _row("reel-002", "collecting", 1, last_video="/Volumes/x/secret/vid-b.mp4"),
                 _row("reel-003", "queued", 0)])
    code, got, text = get(root, "2026-10-13T1100Z")
    assert code == 200, got
    assert got["source"] == "file" and got["batch"] == "reel/2026-10-13T1100Z", got
    assert got["file"] == "work/footage-progress.json" and got["finished"] is False
    assert got["needed"] == 2 and got["cached"] is False and got["poll_s"] == footage.POLL_S
    assert str(root) not in text and str(root.resolve()) not in text, "no absolute path"
    assert "/Volumes/" not in text and "batch_dir" not in got
    rows = {t["topic_id"]: t for t in got["topics"]}
    assert [t["topic_id"] for t in got["topics"]] == ["reel-001", "reel-002", "reel-003"]
    assert rows["reel-001"]["state"] == "collected" and rows["reel-001"]["collected"] == 2
    assert rows["reel-001"]["state_ru"] == "футаж собран"
    assert rows["reel-001"]["last_video"].endswith("work/fetch/vid-a.mp4")
    assert not rows["reel-001"]["last_video"].startswith("/"), rows["reel-001"]
    assert rows["reel-002"]["last_video"] == ".../vid-b.mp4", rows["reel-002"]
    assert rows["reel-003"]["state"] == "queued" and rows["reel-003"]["last_video"] is None
    assert got["counts"] == {"collected": 1, "collecting": 1, "queued": 1}


def test_a_broken_value_in_the_file_reads_null_not_500():
    root = factory_root()
    d = batch(root, "2026-10-13T1101Z")
    bad = _row("reel-001", "collecting", 1)
    bad["collected"] = "two"
    bad["attempts"] = True
    progress(d, [bad])
    code, got, _ = get(root, "2026-10-13T1101Z")
    assert code == 200, got
    t = got["topics"][0]
    assert t["collected"] is None and t["attempts"] is None and t["state"] == "collecting"


def test_a_batch_without_the_file_reads_the_journal():
    root = factory_root()
    d = batch(root, "2026-10-13T1200Z")
    _w(d / "01-trend-hunter.json", json.dumps({"topics": [{"topic_id": "reel-001"},
                                                          {"topic_id": "reel-002"}]}))
    journal(d, [_ev(0, "start", eid="run"),
                _ev(1, "start", video="v1", topic="reel-001", eid="a1"),
                _ev(2, "done", video="v1", topic="reel-001", eid="a1")])
    code, got, _ = get(root, "2026-10-13T1200Z")
    assert code == 200, got
    assert got["source"] == "events" and got["running"] is True and got["finished"] is False
    rows = {t["topic_id"]: t for t in got["topics"]}
    assert rows["reel-001"]["state"] == "collecting" and rows["reel-001"]["collected"] == 1
    assert rows["reel-001"]["attempts"] == 1 and rows["reel-001"]["last_video"] == "v1"
    assert rows["reel-002"]["state"] == "queued"
    assert got["started_at"] == "2026-10-13T11:00:00.000Z"


def test_an_empty_batch_is_none():
    root = factory_root()
    batch(root, "2026-10-13T1300Z")
    code, got, _ = get(root, "2026-10-13T1300Z")
    assert code == 200, got
    assert got["source"] == "none" and got["topics"] == [] and got["counts"] == {}
    assert got["running"] is None and got["error"] is None


def test_the_answer_is_kept_until_a_file_moves():
    root = factory_root()
    d = batch(root, "2026-10-13T1400Z")
    p = progress(d, [_row("reel-001", "collecting", 1)])
    c = client(root)
    url = "/api/batches/reel/2026-10-13T1400Z/footage"
    first = c.get(url).json()
    second = c.get(url).json()
    assert first["cached"] is False and second["cached"] is True, second
    assert second["topics"] == first["topics"]
    # the indexer rewrites the file: a new mtime -> computed afresh
    progress(d, [_row("reel-001", "collected", 2)])
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    third = c.get(url).json()
    assert third["cached"] is False and third["topics"][0]["state"] == "collected", third
    # a new journal line (the run's state) moves it too
    assert c.get(url).json()["cached"] is True
    journal(d, [_ev(0, "start", eid="run"), _ev(9, "done", eid="run")])
    fourth = c.get(url).json()
    assert fourth["cached"] is False, fourth


def test_an_unknown_batch_is_404_in_russian():
    root = factory_root()
    code, got, _ = get(root, "2026-10-13T9999Z")
    assert code == 404 and got["code"] == "unknown_batch", got
    assert got["message"] == "Батча «reel/2026-10-13T9999Z» нет.", got
    r = client(root).get("/api/batches/reel/..%2F..%2Fetc/footage")
    assert r.status_code == 404, r.text


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

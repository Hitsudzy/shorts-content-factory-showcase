#!/usr/bin/env python3
"""CC-0099: a batch's run summary in the command center's API
(`api/run_summary.py`, `GET /api/batches/{channel}/{batch_id}/summary`).

Everything runs in-process (starlette's TestClient) against a stand-in
factory root in a temp dir: batch directories with a RUN_EVENTS.jsonl and a
RUN_SUMMARY.md written by the test. The factory's *code* (`summary.compute`,
runlog) is this checkout's, as in production; nothing of the live factory is
read, no network.

What is pinned:

* the contract: the route, GET only, version 0.48.0, `BatchProblem`;
* `data` is what `runlog summary --json` prints for the batch (its `main`
  run on the same temp batch, the paths cut as the route cuts them), `file`
  the RUN_SUMMARY.md as written, with an absolute path of the root cut;
* missing is «ещё нет», not an error: a batch not closed has `file: null` and
  `file_note`; a batch with no events `data: null` and `data_note`;
* the result is kept per state of the batch: a second read is `cached`, a new
  event computes afresh; a compute that fails is `data_error`, the file still
  answers;
* an unknown batch and a name that is no directory name are 404
  `unknown_batch`; a RUN_SUMMARY.md
  that is a symlink out of the batch is not read;
* the module never names a writer (`write`, `main`, `write_text`, ...).
"""
import ast
import io
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import factory, paths, run_summary          # noqa: E402
from api.app import create_app                       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-run-summary-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
ROUTE = "/api/batches/{channel}/{batch_id}/summary"
FORBIDDEN = {"write", "main", "write_text", "write_bytes", "unlink", "mkdir", "rename",
             "rmtree", "subprocess", "marker", "emit"}
_N = [0]


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ts(minutes_ago):
    return (datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _events(closed=True):
    ev = [{"ts": _ts(60), "kind": "marker", "status": "batch-start", "stage": None},
          {"ts": _ts(59), "kind": "marker", "status": "stage-start", "stage": "trend-hunter"},
          {"ts": _ts(30), "kind": "marker", "status": "stage-done", "stage": "trend-hunter"}]
    if closed:
        ev.append({"ts": _ts(29), "kind": "marker", "status": "batch-done", "stage": None})
    return "".join(json.dumps(e) + "\n" for e in ev)


def factory_root():
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    _w(root / "channels" / "reel.json", json.dumps({"channel_id": "reel"}))
    return root


def batch(root, name, events=None, summary=None):
    d = root / "pipeline" / "reel" / name
    d.mkdir(parents=True, exist_ok=True)
    if events is not None:
        _w(d / "RUN_EVENTS.jsonl", events)
    if summary is not None:
        _w(d / "RUN_SUMMARY.md", summary)
    return d


def client(root):
    return TestClient(create_app(Settings(factory_root=root), token="tok"), client=LOCAL,
                      base_url=BASE)


def get(root, name):
    r = client(root).get(f"/api/batches/reel/{name}/summary")
    return r.status_code, r.json()


def _cli_json(d):
    """What `runlog summary --batch <d> --json` prints, run in-process."""
    out = io.StringIO()
    with redirect_stdout(out):
        rc = factory.run_summary().main(["--batch", str(d), "--json"])
    assert rc == 0
    return json.loads(out.getvalue())


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_summary_route_get_only():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    assert sorted(spec["paths"][ROUTE]) == ["get"]
    get_ = spec["paths"][ROUTE]["get"]
    assert [p["name"] for p in get_["parameters"]] == ["channel", "batch_id"]
    ref = get_["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/BatchProblem"), ref
    props = spec["components"]["schemas"]["BatchRunSummary"]["properties"]
    assert set(props) == {"batch", "channel", "batch_id", "file", "file_note", "data",
                          "data_note", "data_error", "computed_at", "cached", "poll_s",
                          "funnel_reasons_ru"}


def test_the_module_names_no_writer():
    src = (ROOT / "api" / "run_summary.py").read_text(encoding="utf-8")
    named = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Name):
            named.add(n.id)
        elif isinstance(n, ast.Attribute):
            named.add(n.attr)
    assert not named & FORBIDDEN, named & FORBIDDEN


# --------------------------------------------------------------------- the answer
def test_a_closed_batch_is_the_cli_s_json_and_its_file():
    root = factory_root()
    text = f"GAPS: none\n\nread from {root.resolve()}/pipeline/reel/b1/RUN_EVENTS.jsonl\n"
    d = batch(root, "2026-10-01T1100Z", _events(), text)
    code, got = get(root, "2026-10-01T1100Z")
    assert code == 200, got
    assert got["batch"] == "reel/2026-10-01T1100Z" and got["batch_id"] == "2026-10-01T1100Z"
    assert got["data"] == paths.clean(_cli_json(d), root), "data is not runlog summary --json"
    assert got["data"]["times"] and got["data"]["counts"]["events"] == 4
    assert got["data_note"] is None and got["data_error"] is None
    f = got["file"]
    assert f["name"] == "RUN_SUMMARY.md" and f["size"] == len(text.encode())
    assert f["text"].startswith("GAPS: none") and str(root.resolve()) not in f["text"]
    assert "pipeline/reel/b1/RUN_EVENTS.jsonl" in f["text"], f["text"]
    assert got["file_note"] is None and got["poll_s"] == run_summary.POLL_S
    assert got["computed_at"].endswith("Z") and got["cached"] is False
    assert str(root.resolve()) not in json.dumps(got, ensure_ascii=False)


def test_missing_is_yet_not_an_error():
    root = factory_root()
    batch(root, "2026-10-01T1200Z", _events(closed=False))
    code, got = get(root, "2026-10-01T1200Z")
    assert code == 200, got
    assert got["file"] is None and "ещё нет" in got["file_note"], got
    assert got["data"] is not None and got["data_note"] is None
    batch(root, "2026-10-01T1300Z")
    code, got = get(root, "2026-10-01T1300Z")
    assert code == 200, got
    assert got["data"] is None and "ещё нет" in got["data_note"] and got["data_error"] is None
    assert got["file"] is None and got["computed_at"] is None and got["cached"] is False


def test_the_result_is_kept_until_the_batch_changes():
    root = factory_root()
    d = batch(root, "2026-10-01T1400Z", _events(closed=False))
    sm = factory.run_summary()
    calls, orig = [], sm.compute
    sm.compute = lambda *a, **k: calls.append(1) or orig(*a, **k)
    try:
        _, one = get(root, "2026-10-01T1400Z")
        _, two = get(root, "2026-10-01T1400Z")
        assert len(calls) == 1 and two["cached"] is True and two["data"] == one["data"]
        assert two["computed_at"] == one["computed_at"]
        with open(d / "RUN_EVENTS.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _ts(1), "kind": "marker", "status": "batch-done",
                                 "stage": None}) + "\n")
        _, three = get(root, "2026-10-01T1400Z")
        assert len(calls) == 2 and three["cached"] is False
        assert three["data"]["counts"]["events"] == 4
    finally:
        sm.compute = orig


def test_a_failed_compute_is_data_error_and_the_file_still_answers():
    root = factory_root()
    batch(root, "2026-10-01T1500Z", _events(), "# summary\n")
    sm = factory.run_summary()
    orig = sm.compute

    def boom(*a, **k):
        raise ValueError(f"broken at {root.resolve()}/pipeline/reel/x")
    sm.compute = boom
    try:
        code, got = get(root, "2026-10-01T1500Z")
    finally:
        sm.compute = orig
    assert code == 200, got
    assert got["data"] is None and "ValueError" in got["data_error"], got
    assert str(root.resolve()) not in got["data_error"]
    assert got["file"]["text"] == "# summary\n"


def test_an_unknown_batch_a_traversal_and_a_link_out():
    root = factory_root()
    for name in ("2026-01-01T0000Z", ".x", "-x"):
        r = client(root).get(f"/api/batches/reel/{name}/summary")
        assert r.status_code == 404, (name, r.text)
        body = r.json()
        assert body["code"] == "unknown_batch" and set(body) == {"message", "code", "details"}
    outside = _w(TMP / f"outside-{_N[0]}.md", "secret\n")
    d = batch(root, "2026-10-01T1600Z", _events())
    os.symlink(outside, d / "RUN_SUMMARY.md")
    code, got = get(root, "2026-10-01T1600Z")
    assert code == 200 and got["file"] is None and got["file_note"], got


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

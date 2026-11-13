"""CC-0119: GET /api/batches/{channel}/{batch_id} sends no absolute path of
this machine. The executor writes the batch's absolute directory into
run-state.json `batch`, and the processes' exit files, logs and argv, a
stage's reason and a halt reason can name files too - all of `state` goes
through `paths.clean` (inside the root relative, elsewhere `.../<name>`).
The check is generic: every string of the whole answer. Temp trees only."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import TMP, _w, client, factory_tree   # noqa: E402

CH, B = "reel", "2026-10-13T0900Z"
URL = f"/api/batches/{CH}/{B}"
BANNED = ("/home/", "/private/", "/var/folders/", "/tmp/", "/home/")


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def _no_path(root, got):
    bad = [str(TMP), str(TMP.resolve()), str(root), str(root.resolve()), str(Path.home())]
    for s in _strings(got):
        for b in BANNED + tuple(bad):
            assert b not in s, (b, s)


def _state(d, as_written):
    batch = str(as_written)
    return {
        "channel": CH, "batch": batch, "batch_id": B, "status": "failed",
        "created": "2026-10-13T09:00:00Z", "order": ["trend-hunter", "video-editor"],
        "stages": {"trend-hunter": {"status": "done"},
                   "video-editor": {"status": "failed",
                                    "reason": f"step 0 exited 2; log {batch}/logs/ve.s0.a0.log",
                                    "verdict": f"{batch}/05-video-editor.json"}},
        "current": {"stage": "video-editor", "dir": batch},
        "next": None,
        "runs": {"video-editor.s0": {"stage": "video-editor", "pid": 1, "exit": 2,
                                     "exit_file": f"{batch}/logs/ve.s0.a0.exit",
                                     "log": f"{batch}/logs/ve.s0.a0.log",
                                     "argv": ["/usr/bin/python3",
                                              "/home/someone/agents/video-editor/run.py",
                                              "--batch", batch]}},
        "reruns": {}, "needs_human": [{"stage": "video-editor", "key": "x",
                                       "file": "/private/tmp/elsewhere/notes.txt"}],
        "halt_reason": f"stage video-editor failed - see {batch}/logs/ve.s0.a0.log",
        "extra_key": {"nested": [{"path": f"{batch}/deep/inside.json"},
                                 "/home/someone/outside/file.log"]},
    }


def _batch(root, resolved):
    d = root / "pipeline" / CH / B
    d.mkdir(parents=True)
    _w(d / "run-state.json", _state(d, d.resolve() if resolved else d))
    _w(d / "RUN_EVENTS.jsonl", "")
    return d


def _get(root):
    r = client(root).get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def test_state_batch_and_nested_paths_are_cut():
    root = factory_tree()
    _batch(root, resolved=False)
    got = _get(root)
    _no_path(root, got)
    st = got["state"]
    assert st["batch"] == f"pipeline/{CH}/{B}", st["batch"]
    run = st["runs"]["video-editor.s0"]
    assert run["log"] == f"pipeline/{CH}/{B}/logs/ve.s0.a0.log", run
    assert run["exit_file"] == f"pipeline/{CH}/{B}/logs/ve.s0.a0.exit", run
    assert run["argv"][1] == ".../run.py" and run["alive"] is False, run
    assert st["current"]["dir"] == f"pipeline/{CH}/{B}"
    assert st["needs_human"][0]["file"] == ".../notes.txt"
    assert st["extra_key"]["nested"][1] == ".../file.log"
    assert st["status"] == got["status"] == "failed"


def test_a_resolved_tmp_root_is_cut_too():
    """macOS: the temp root is /var/folders/..., resolved /private/var/..."""
    root = factory_tree()
    _batch(root, resolved=True)
    got = _get(root)
    _no_path(root, got)
    assert got["state"]["batch"] == f"pipeline/{CH}/{B}", got["state"]["batch"]
    assert got["dir"] == f"pipeline/{CH}/{B}"


def test_no_state_is_still_null():
    root = factory_tree()
    d = root / "pipeline" / CH / B
    d.mkdir(parents=True)
    _w(d / "RUN_EVENTS.jsonl", "")
    got = _get(root)
    assert got["state"] is None and got["status"] is None
    _no_path(root, got)


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""CC-0098: no absolute path of this machine leaves in a refusal - temp trees
only, no network, the TestClient.

Every refusal of the API leaves through one place, `problem` of
`api/app.py` (the handlers of ChannelFault, BatchFault, WritesRefused and the
factory's own refusals of the questions and requests), and goes through the
one cutter `api/paths.py` `clean`:

* the handlers: a refusal whose `message` and `details` carry the root's
  paths (as given and resolved), the home directory, another absolute path,
  an exception's text - inside the root relative, the root itself
  `.../<name>`, the home `~`, the rest `.../<last part>`; a URL whole, a
  `file:` URL cut;
* the real refusals: an unknown channel (`under <root>`), a write outside the
  working factory (`factory root: <root>`), a launch check that raised with a
  path in its text, an unknown question - the temp root in none of them.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)
os.environ.pop("CC_API_WRITES", None)

from fastapi.testclient import TestClient            # noqa: E402

from _tmproot import tmp_root                        # noqa: E402
from api import batches, channels, factory, paths    # noqa: E402
from api.app import SESSION_HEADER, WritesRefused, create_app   # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-problems-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
H = {"Origin": BASE, SESSION_HEADER: "tok"}
URL = "https://www.googleapis.com/youtube/v3/videos?id=abc&part=status"
_N = [0]


def tree():
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    (root / "channels").mkdir(parents=True)
    (root / "channels" / "reel.json").write_text("{}", encoding="utf-8")
    return root


def make(root, writes_dev=False):
    factory.forget_working_factory()
    app = create_app(Settings(factory_root=root, writes_dev=writes_dev), token="tok")
    return app, TestClient(app, client=LOCAL, base_url=BASE)


def no_abs(body, root):
    text = json.dumps(body, ensure_ascii=False)
    for bad in (str(TMP), str(TMP.resolve()), str(root), str(root.resolve()), str(ROOT),
                str(Path.home())):
        assert bad not in text, (bad, text[:600])
    return text


def _raising(app, path, exc):
    """A route of the test raising `exc` - in front, the handlers are the app's."""
    def boom():
        raise exc
    app.add_api_route(path, boom, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


def test_every_handler_cuts_the_root_and_keeps_a_url():
    root = tree()
    app, c = make(root)
    home = Path.home() / "Library" / "secret" / "token.json"
    lines = [f"FileNotFoundError: [Errno 2] No such file or directory: '{root}/schedule/x.json'",
             f"under {root.resolve()}", f"factory root: {root}", f"see {home}",
             "PermissionError: /opt/elsewhere/deep/thing.py", f"Google said 403 at {URL}",
             f"file://{root}/a/b.txt"]
    faults = {"/__t/channel": channels.ChannelFault(500, "x", f"Не прочитан {root}/c.json",
                                                    lines, errors=[{"file": f"{root}/c.json"}]),
              "/__t/batch": batches.BatchFault(500, "x", f"Ошибка: {root.resolve()}/y", lines),
              "/__t/writes": WritesRefused(f"не git-репозиторий ({root})", root)}
    for path, exc in faults.items():
        _raising(app, path, exc)
    for path in faults:
        r = c.get(path)
        assert r.status_code in (409, 500), (path, r.text)
        body = r.json()
        no_abs(body, root)
        if path != "/__t/writes":
            d = body["details"]
            assert d[0] == "FileNotFoundError: [Errno 2] No such file or directory: " \
                           "'schedule/x.json'", d
            assert d[1] == d[2].replace("factory root: ", "under ") == f"under .../{root.name}"
            assert d[3] == "see ~/Library/secret/token.json", d
            assert d[4] == "PermissionError: .../thing.py" and d[5].endswith(URL), d
            assert d[6].startswith("file:") and d[6].endswith("/b.txt"), d   # a path: cut
        else:
            assert body["details"][:2] == [f"не git-репозиторий (.../{root.name})",
                                           f"factory root: .../{root.name}"], body
    assert c.get("/__t/channel").json()["errors"] == [{"file": "c.json"}]
    assert c.get("/__t/channel").json()["message"] == "Не прочитан c.json"
    assert c.get("/__t/batch").json()["message"] == "Ошибка: y"


def test_the_real_refusals_name_no_root():
    root = tree()
    _, c = make(root)
    r = c.get("/api/channels/nope")                   # «no channels/nope.json under <root>»
    assert r.status_code == 404, r.text
    text = no_abs(r.json(), root)
    assert f"under .../{root.name}" in text, text
    r = c.post("/api/questions/Q1/answer", headers=H, json={"text": "да"})   # not git
    assert r.status_code == 409 and r.json()["code"] == "not_working_factory", r.text
    text = no_abs(r.json(), root)
    assert f"factory root: .../{root.name}" in text, text

    _, c = make(root, writes_dev=True)
    r = c.post("/api/questions/Q9/answer", headers=H, json={"text": "да"})
    assert r.status_code == 404, r.text
    no_abs(r.json(), root)

    class Broken:
        def launch_check(self, *a, **k):
            raise FileNotFoundError(2, "No such file or directory",
                                    str(root.resolve() / "schedule" / "state.json"))
    saved = batches._bs
    batches._bs = lambda: Broken()
    try:
        r = c.post("/api/batches/launch/plan", headers=H, json={"channel": "reel"})
    finally:
        batches._bs = saved
    assert r.status_code == 500 and r.json()["code"] == "schedule_broken", r.text
    no_abs(r.json(), root)
    assert r.json()["details"] == ["FileNotFoundError: [Errno 2] No such file or directory: "
                                   "'schedule/state.json'"], r.json()


def test_clean_is_scrub_with_the_root_named():
    root = tree()
    got = paths.clean({"a": (f"{root}", f"{root}/x"), "b": [URL, 3, None]}, root)
    assert got == {"a": [f".../{root.name}", "x"], "b": [URL, 3, None]}, got
    # the old forms stay: the root alone `.` without `named`
    assert paths.scrub(str(root), paths.prefixes(root)) == "."


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

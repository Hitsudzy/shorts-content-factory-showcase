#!/usr/bin/env python3
"""CC-0003: the command center's API (`api/`).

Everything runs in-process (starlette's TestClient, no socket) against
stand-ins: a factory root, a lock, a README and a built center in a temp dir.
The one file of the live checkout it reads is `api/openapi.json` - the
contract in git, which has to be what the app gives.

What is pinned:

* `api/openapi.json` is byte for byte what the app gives (`python3 -m api
  openapi` rewrites it, `--check` says so);
* the settings come from the environment only - the defaults (127.0.0.1:8790
  - CC-0035, the port of the retired console - this checkout,
  `<root>/frontend/dist`), every override, a bad port; no path of this
  machine in the code;
* the guard: a foreign Host is refused (GET too), a client from elsewhere when
  listening on loopback; a POST needs this Origin (or Referer) and the session
  token of this process; `CC_API_ALLOWED_ORIGINS` / `_HOSTS` add to the lists;
* the built center is served from the same address: its files, index.html for
  the router's paths, 404 for a missing asset or an unknown /api route, never
  a file outside dist; no build -> 503 and the API still answers;
* health; version: the README's version, the lock's pins through
  `agents_lock.status`, the center's version from package.json - and an
  absent lock / build is an answer, not a crash; no absolute path in it
  (CC-0097: `center.dist` relative to the root, `.../<name>` outside it);
  the process itself (CC-0155): `started_at` / `commit_at_start` read once, when
  the app is built, `stale` (+ `stale_paths`) once a later code commit lands in a
  temp git root - a data-only commit keeps it false;
* `CC_BASE_PATH` moves the center and the API together;
* the launchd plist is a filled template, printed only.
"""
import contextlib
import io
import json
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from api import __main__ as cli                      # noqa: E402
from api import auth                                 # noqa: E402
from api.app import SESSION_HEADER, create_app       # noqa: E402
from api.settings import CODE, Settings, SettingsError  # noqa: E402

LOCAL = ("127.0.0.1", 50000)
#: CC-0036: a password's hash (cheap iterations - a test's, not the default)
HASH = auth.hash_password("test-only", iterations=1000)
BASE = "http://127.0.0.1:8790"
ORIGIN = {"Origin": BASE}


def client(settings=None, token=None, peer=LOCAL, base_url=BASE, extra_post=True):
    app = create_app(settings or Settings(), token=token)
    if extra_post:
        # a stand-in action: no route of CC-0003 acts, the guard is what is tested
        @app.post(app.state.settings.api_prefix + "/_probe", include_in_schema=False)
        def _probe():
            return {"done": True}
        # the probe has to sit before the /api catch-all
        app.router.routes.insert(0, app.router.routes.pop())
    return TestClient(app, client=peer, base_url=base_url), app.state.token


def fake_factory(tmp, lock=True, built=True, pkg_version="1.2.3"):
    root = Path(tmp) / "factory"
    root.mkdir()
    (root / "README.md").write_text("# Shorts Content Factory — 9.8, with 9.9 in progress\n",
                                    encoding="utf-8")
    if lock:
        (root / "agents.lock.json").write_text(json.dumps(
            {"agents": {"video-editor": {"path": "agents/video-editor", "rev": "v9.8.0"}},
             "links": {}}), encoding="utf-8")
    fe = root / "frontend"
    (fe / "dist" / "assets").mkdir(parents=True)
    if pkg_version is not None:
        (fe / "package.json").write_text(json.dumps({"name": "cc", "version": pkg_version}),
                                         encoding="utf-8")
    if built:
        (fe / "dist" / "index.html").write_text("<!doctype html><title>center</title>",
                                                encoding="utf-8")
        (fe / "dist" / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (Path(tmp) / "secret.txt").write_text("outside dist", encoding="utf-8")
    return root


# --------------------------------------------------------------------- the contract

def test_openapi_json_in_git_is_what_the_app_gives():
    have = (ROOT / "api" / "openapi.json").read_text(encoding="utf-8")
    want = cli.openapi_text()
    assert have == want, ("api/openapi.json is not what the app gives: run "
                          "`python3 -m api openapi` and commit it (CC-0003)")
    spec = json.loads(have)
    assert spec["info"]["version"] == api.API_VERSION
    for p in ("/api/health", "/api/version", "/api/session"):
        assert p in spec["paths"], p
        assert "403" in spec["paths"][p]["get"]["responses"], p
    assert not [p for p in spec["paths"] if not p.startswith("/api/")], spec["paths"].keys()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["openapi", "--check"]) == 0
    assert "matches" in out.getvalue()


def test_every_schema_name_in_the_contract_is_unique_and_plain():
    """CC-0060: two models of one name (two `GoingBatch` in contract 0.16.0) make
    FastAPI name them by module path with a counter - `api__app__GoingBatch__1`
    and `__2` - and the center's generated types lose the name. Every schema of
    `components.schemas` is a plain identifier, its own title, one per title."""
    spec = json.loads(cli.openapi_text())
    schemas = spec["components"]["schemas"]
    assert schemas
    bad = [k for k in schemas if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", k) or "__" in k
           or k.startswith("api")]
    assert not bad, f"schema names with a module path or a __N suffix: {bad}"
    titles = [v.get("title", k) for k, v in schemas.items()]
    dup = sorted({t for t in titles if titles.count(t) > 1})
    assert not dup, f"two schemas of one title: {dup}"
    assert not [(k, t) for k, t in zip(schemas, titles) if k != t]
    assert "GoingBatch" in schemas and "BlockingBatch" in schemas
    assert set(schemas["GoingBatch"]["properties"]) >= {"batch", "dir", "batch_id", "fresh"}
    assert set(schemas["BlockingBatch"]["properties"]) == {"dir", "why"}
    going = spec["components"]["schemas"]["BatchesGoing"]["properties"]["batches"]
    assert going["items"]["$ref"] == "#/components/schemas/GoingBatch"
    accept = spec["components"]["schemas"]["AcceptResult"]["properties"]["batches"]
    assert accept["items"]["$ref"] == "#/components/schemas/BlockingBatch"


def test_the_contract_does_not_depend_on_the_environment():
    a = cli.openapi_text()
    b = cli.openapi_text(create_app(Settings.from_env({"CC_API_PORT": "9999",
                                                        "CC_API_HOST": "0.0.0.0",
                                                        "CC_PASSWORD_HASH": HASH}), token="t"))
    assert a == b


# --------------------------------------------------------------------- settings

def test_settings_defaults_and_overrides_come_from_the_environment():
    s = Settings.from_env({})
    assert (s.host, s.port, s.base_path) == ("127.0.0.1", 8790, "/")
    assert s.factory_root == CODE and s.frontend_dist == CODE / "frontend" / "dist"
    assert s.api_prefix == "/api" and s.loopback_only
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings.from_env({"CC_API_HOST": "0.0.0.0", "CC_API_PORT": "8800",
                               "CC_PASSWORD_HASH": HASH,   # CC-0036: not loopback - a password
                               "CC_FACTORY_ROOT": tmp, "CC_BASE_PATH": "cc",
                               "CC_API_ALLOWED_HOSTS": "factory:8800, ",
                               "CC_API_ALLOWED_ORIGINS": "http://localhost:5173/"})
        assert (s.host, s.port, s.base_path, s.api_prefix) == ("0.0.0.0", 8800, "/cc/", "/cc/api")
        assert s.factory_root == Path(tmp).resolve()
        assert s.frontend_dist == Path(tmp).resolve() / "frontend" / "dist"
        assert not s.loopback_only
        assert "factory:8800" in s.allowed_hosts() and "127.0.0.1:8800" in s.allowed_hosts()
        assert "http://localhost:5173" in s.allowed_origins()
        s = Settings.from_env({"FACTORY_ROOT": tmp, "CC_FRONTEND_DIST": str(Path(tmp) / "d")})
        assert s.factory_root == Path(tmp).resolve() and s.frontend_dist == Path(tmp).resolve() / "d"
    for bad in ("x", "0", "70000"):
        try:
            Settings.from_env({"CC_API_PORT": bad})
        except SettingsError:
            continue
        raise AssertionError(f"CC_API_PORT={bad} accepted")


def test_no_path_of_this_machine_in_the_code():
    mac = re.compile(r"/home/|/Library/|/opt/homebrew|/usr/local/|/Volumes/|~/Library")
    files = sorted((ROOT / "api").glob("*.py")) + [cli.TEMPLATE]
    hits = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            # the printed install commands name launchd's own folder - not a setting
            if mac.search(line) and "LaunchAgents" not in line:
                hits.append(f"{f.name}:{n}: {line.strip()}")
    assert not hits, hits


# --------------------------------------------------------------------- the guard

def test_health_answers_with_the_security_headers():
    with tempfile.TemporaryDirectory() as tmp:     # a stand-in root, not this checkout
        c, _ = client(Settings(factory_root=Path(tmp)))
        r = c.get("/api/health")
    got = r.json()
    # CC-0058: whether it writes (no git here -> no working factory; tests/test_cc_api_writes.py)
    assert got.pop("writes_reason", "").startswith("не git-репозиторий"), r.text
    assert r.status_code == 200 and got == {"status": "ok", "api": api.API_VERSION,
                                            "writes": False, "writes_dev": False}, r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"


def test_a_foreign_host_is_refused_even_for_get():
    c, _ = client()
    # CC-0035: the center is on 8790 now; its old port 8791 is a foreign Host
    for host in ("evil.example:8790", "127.0.0.1:8791", "localhost", ""):
        r = c.get("/api/health", headers={"Host": host})
        assert r.status_code == 403 and r.json()["guard"] == "host", (host, r.text)
        assert r.headers["x-frame-options"] == "DENY"
    for host in ("localhost:8790", "[::1]:8790", "127.0.0.1:8790"):
        assert c.get("/api/health", headers={"Host": host}).status_code == 200, host
    c, _ = client(Settings(extra_hosts=("factory.lan:8790",)))
    assert c.get("/api/health", headers={"Host": "factory.lan:8790"}).status_code == 200


def test_on_loopback_a_client_from_elsewhere_is_refused():
    c, _ = client(peer=("192.168.1.20", 4000))
    r = c.get("/api/health")
    assert r.status_code == 403 and r.json()["guard"] == "client", r.text
    # listening on every address (a container): the Host check is the guard - and
    # CC-0036: the password (a client from elsewhere logs in; tests/test_cc_api_auth.py)
    s = Settings(host="0.0.0.0", extra_hosts=("factory:8790",), password_hash=HASH)
    c, _ = client(s, peer=("172.17.0.1", 4000), base_url="http://factory:8790")
    r = c.get("/api/health")
    assert r.status_code == 401 and r.json()["code"] == "auth_required", r.text
    r = c.get("/api/health", headers={"Host": "evil.example:8790"})
    assert r.status_code == 403 and r.json()["guard"] == "host", r.text


def test_a_post_needs_this_origin_and_the_session_token():
    c, token = client(token="sekret-1")
    assert c.get("/api/session").json() == {"token": "sekret-1", "header": SESSION_HEADER}
    tok = {SESSION_HEADER: token}

    def post(headers):
        return c.post("/api/_probe", headers=headers)

    r = post(tok)
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    r = post({**tok, "Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    r = post({**tok, "Referer": "http://evil.example/"})
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    r = post({**tok, "Referer": BASE + ".evil.example/"})
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    r = post(ORIGIN)
    assert r.status_code == 403 and r.json()["guard"] == "session", r.text
    r = post({**ORIGIN, SESSION_HEADER: "sekret-2"})
    assert r.status_code == 403 and r.json()["guard"] == "session", r.text
    assert post({**ORIGIN, **tok}).json() == {"done": True}
    assert post({"Referer": BASE + "/channels", **tok}).status_code == 200
    # the Vite dev server is another origin: only when it is named
    dev = {"Origin": "http://localhost:5173", **tok}
    assert post(dev).status_code == 403
    c, token = client(Settings(extra_origins=("http://localhost:5173",)), token="sekret-1")
    assert c.post("/api/_probe", headers=dev).status_code == 200


def test_every_process_has_its_own_token():
    a, ta = client(extra_post=False)
    b, tb = client(extra_post=False)
    assert ta != tb and len(ta) >= 32
    assert a.get("/api/session").json()["token"] == ta


# --------------------------------------------------------------------- the center

def test_the_built_center_is_served_from_the_same_address():
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp)
        c, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        r = c.get("/")
        assert r.status_code == 200 and "<title>center</title>" in r.text, r.text
        assert r.headers["cache-control"] == "no-cache"
        assert c.get("/assets/app.js").text == "console.log(1)"
        # a path of the center's router is the page, not a 404
        assert "<title>center</title>" in c.get("/channels/example-film").text
        assert c.get("/assets/missing.js").status_code == 404
        r = c.get("/api/nothing-here")
        assert r.status_code == 404 and r.json()["detail"].startswith("no such route"), r.text
        # never a file outside dist
        for p in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
            r = c.get(p)
            assert "outside dist" not in r.text, p
        assert c.get("/api/health").status_code == 200


def test_no_build_is_a_503_page_and_the_api_still_answers():
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp, built=False)
        c, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        r = c.get("/")
        assert r.status_code == 503 and "npm run build" in r.text, r.text
        assert c.get("/channels").status_code == 503
        assert c.get("/api/health").status_code == 200


def test_the_base_path_moves_the_center_and_the_api_together():
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp)
        s = Settings.from_env({"CC_FACTORY_ROOT": str(root), "CC_BASE_PATH": "/cc/"})
        c, _ = client(s)
        assert c.get("/cc/api/health").status_code == 200
        assert "<title>center</title>" in c.get("/cc/").text
        assert c.get("/api/health").status_code == 404
        assert c.get("/cc/api/openapi.json").status_code == 200


# --------------------------------------------------------------------- version

def test_version_says_the_factory_the_pins_and_the_center():
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp)
        c, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        v = c.get("/api/version").json()
        assert v["api"] == api.API_VERSION
        assert v["factory"] == {"version": "9.8", "commit": None, "dirty": None}, v["factory"]
        assert v["agents_error"] is None
        [pin] = v["agents"]
        assert (pin["agent"], pin["path"], pin["rev"], pin["ok"], pin["why"]) == \
            ("video-editor", "agents/video-editor", "v9.8.0", False, "not checked out"), pin
        assert v["center"]["version"] == "1.2.3" and v["center"]["built"] is True
        assert v["center"]["built_at"].endswith("Z")
        # CC-0155: no git at start - the process says when, not what it runs
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", v["started_at"]), v
        assert v["commit_at_start"] is None and v["stale"] is None, v
        assert v["stale_paths"] is None, v


def _git(root, *args):
    cp = subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                         "-c", "commit.gpgsign=false", *args],
                        capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    return cp.stdout.strip()


def test_version_says_the_commit_the_process_started_on_and_when_it_is_stale():
    """CC-0155 (CF-0841): `started_at` / `commit_at_start` are read once, when
    the app is built - a commit landing in the root later changes the live
    `factory.commit` and makes the process `stale`, never the two."""
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp)
        _git(root, "init", "-q", "-b", "main")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "one")
        first = _git(root, "rev-parse", "HEAD")
        c, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        v1 = c.get("/api/version").json()
        assert v1["commit_at_start"] == first and len(first) == 40, v1
        assert v1["factory"]["commit"] == first and v1["stale"] is False, v1
        assert v1["started_at"].endswith("Z"), v1
        assert v1["stale_paths"] == [], v1
        # a data-only commit (the center's own writes, a batch's records): not stale
        (root / "records.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
        (root / "README.md").write_text("# Shorts Content Factory — 9.9\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "data")
        data = _git(root, "rev-parse", "HEAD")
        v2 = c.get("/api/version").json()
        assert (v2["started_at"], v2["commit_at_start"]) == (v1["started_at"], first), v2
        assert v2["factory"]["commit"] == data != first, v2
        assert v2["stale"] is False and v2["stale_paths"] == [], v2
        # code lands: stale, the path named
        (root / "api").mkdir()
        (root / "api" / "thing.py").write_text("X = 1\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "code")
        second = _git(root, "rev-parse", "HEAD")
        v3 = c.get("/api/version").json()
        assert (v3["started_at"], v3["commit_at_start"]) == (v1["started_at"], first), v3
        assert v3["factory"]["commit"] == second and v3["stale"] is True, v3
        assert v3["stale_paths"] == ["api/thing.py"], v3
        # a new process (app) starts on the new commit and is not stale
        c2, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        v4 = c2.get("/api/version").json()
        assert v4["commit_at_start"] == second and v4["stale"] is False, v4


def test_version_staleness_needs_both_commits():
    from api import factory
    nowhere = Path("/nonexistent-cc-0155")
    assert factory.process_stale(nowhere, {"commit_at_start": None}, {"commit": "a"}) == \
        (None, None)
    assert factory.process_stale(nowhere, {"commit_at_start": "a"}, {"commit": None}) == \
        (None, None)
    # the same commit: no diff is run (the root is no repository)
    assert factory.process_stale(nowhere, {"commit_at_start": "a"}, {"commit": "a"}) == \
        (False, [])
    # the diff fails: unknown, not stale
    assert factory.process_stale(nowhere, {"commit_at_start": "a"}, {"commit": "b"}) == \
        (None, None)
    from datetime import datetime, timedelta, timezone
    at = datetime(2026, 10, 22, 5, 15, 7, tzinfo=timezone(timedelta(hours=3)))
    assert factory.process_start(Path("/nonexistent-cc-0155"), now=at) == \
        {"started_at": "2026-10-22T02:15:07Z", "commit_at_start": None}


def test_version_without_a_lock_or_a_build_is_an_answer():
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp, lock=False, built=False, pkg_version=None)
        c, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        r = c.get("/api/version")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["agents"] == [] and "agents.lock.json" in v["agents_error"], v
        assert v["center"] == {"version": None, "built": False, "built_at": None,
                               "dist": "frontend/dist"}, v["center"]
        assert v["agents_error"] == "no agents.lock.json in .", v["agents_error"]
        assert str(Path(tmp)) not in r.text and str(Path(tmp).resolve()) not in r.text, r.text


def test_version_gives_no_absolute_path():
    """CC-0097: `center.dist` is relative to the factory root (the form of the
    newer answers, `api/paths.py`), a dist outside the root `.../<its last
    part>`; the temp tree's root is nowhere in the answer."""
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_factory(tmp)
        c, _ = client(Settings(factory_root=root, frontend_dist=root / "frontend" / "dist"))
        r = c.get("/api/version")
        assert r.status_code == 200, r.text
        assert r.json()["center"]["dist"] == "frontend/dist", r.json()["center"]
        # the temp root is no git repository: the reason names it by its last part
        assert r.json()["writes_reason"] == "не git-репозиторий (.../factory)", r.text
        for p in (Path(tmp), Path(tmp).resolve(), root, root.resolve()):
            assert str(p) not in r.text, (p, r.text)
        elsewhere = Path(tmp) / "elsewhere" / "built"
        (elsewhere).mkdir(parents=True)
        c, _ = client(Settings(factory_root=root, frontend_dist=elsewhere))
        r = c.get("/api/version")
        assert r.status_code == 200, r.text
        assert r.json()["center"]["dist"] == ".../built", r.json()["center"]
        assert str(Path(tmp)) not in r.text and str(Path(tmp).resolve()) not in r.text, r.text


# --------------------------------------------------------------------- launchd

def test_the_launchd_plist_is_a_filled_template_and_only_printed():
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings.from_env({"CC_FACTORY_ROOT": tmp, "CC_API_PORT": "8800"})
        text = cli.plist_text(s, python="/x/python3", path_env="/bin", log=str(Path(tmp) / "l"))
    assert "{{" not in text, text
    p = plistlib.loads(text.encode("utf-8"))
    assert p["Label"] == cli.LABEL
    assert p["ProgramArguments"] == ["/x/python3", "-m", "api", "serve"]
    assert p["EnvironmentVariables"]["CC_API_PORT"] == "8800"
    assert p["EnvironmentVariables"]["CC_FACTORY_ROOT"] == str(Path(tmp).resolve())
    assert p["KeepAlive"] is True
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert cli.main(["launchd"]) == 2
    assert "only --print" in err.getvalue()
    assert any("NOT installed" in line for line in cli.install_commands())


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

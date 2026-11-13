#!/usr/bin/env python3
"""CC-0036 (CF-0616): the center from the home network, behind a password.

What is pinned (`api/auth.py`, the guard of `api/app.py`, `api/settings.py`):

* the default is today's: 127.0.0.1:8790, nobody logs in, a client from
  elsewhere is refused by the `client` guard as before;
* a bind that is not loopback without `CC_PASSWORD_HASH`: refused (Russian),
  by the settings, by `create_app` and by `python3 -m api serve`; a bad hash
  line refused too; `CC_BIND` is `CC_API_HOST`'s other name;
* the Mac (127.0.0.1, ::1) never logs in, a password set or not; any other
  client gets 401 `auth_required` on every /api route and the center's files,
  except the login's routes and the login screen's files; X-Forwarded-For is
  not believed;
* login: a wrong password 401 `wrong_password` (after the delay), the right one
  the cookie (HttpOnly, SameSite=Strict, Path, Max-Age 30 days); the cookie
  lets the requests in; the write guards (Origin, X-CC-Session) stay; logout
  ends the session; the session slides and expires;
* 5 wrong passwords from one address in 15 min lock it for 15 min (429
  `locked`, retry_after), other addresses still log in, the lock ends; 30 from
  anywhere lock every non-loopback login; a fake clock, no real wait;
* the hash line's format, verify; `python3 -m api password`; the plist;
* the password is never in a log; the failure's address and time are.

No network, no live data: a temp dist, the TestClient, a fake clock.
"""
import contextlib
import io
import logging
import os
import plistlib
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient            # noqa: E402

from api import __main__ as cli                      # noqa: E402
from api import auth                                 # noqa: E402
from api.app import SESSION_HEADER, create_app       # noqa: E402
from api.settings import Settings, SettingsError     # noqa: E402

PASSWORD = "Home-net-S3cret-xyz"
HASH = auth.hash_password(PASSWORD, iterations=1000)   # cheap - a test's
LAN = "192.168.1.10"
BASE = f"http://{LAN}:8790"
ORIGIN = {"Origin": BASE}
PHONE = ("192.168.1.20", 50000)
LOCAL = ("127.0.0.1", 50000)
TMP = tempfile.TemporaryDirectory(prefix="cc-api-auth-test-")
DIST = Path(TMP.name) / "dist"
(DIST / "assets").mkdir(parents=True)
(DIST / "index.html").write_text("<!doctype html><title>center</title>", encoding="utf-8")
(DIST / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
(DIST / "favicon.svg").write_text("<svg/>", encoding="utf-8")
(DIST / "contract.json").write_text("{}", encoding="utf-8")


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)


def app_for(host=LAN, password_hash=HASH, clock=None, token="tok"):
    clock = clock or Clock()
    s = Settings(host=host, password_hash=password_hash, factory_root=Path(TMP.name),
                 frontend_dist=DIST)
    a = auth.Auth(password_hash, clock=clock, sleep=clock.sleep)
    app = create_app(s, token=token, auth=a)

    @app.post(s.api_prefix + "/_probe", include_in_schema=False)
    def _probe():
        return {"done": True}
    app.router.routes.insert(0, app.router.routes.pop())
    return app, clock


def client(app, peer=PHONE, base_url=BASE):
    return TestClient(app, client=peer, base_url=base_url)


def login(c, password=PASSWORD):
    return c.post("/api/auth/login", json={"password": password}, headers=ORIGIN)


# --------------------------------------------------------------------- the default

def test_the_default_is_unchanged_loopback_and_no_login():
    s = Settings.from_env({})
    assert (s.host, s.port, s.password_hash) == ("127.0.0.1", 8790, None) and s.loopback_only
    app = create_app(Settings(factory_root=Path(TMP.name), frontend_dist=DIST), token="t")
    c = TestClient(app, client=LOCAL, base_url="http://127.0.0.1:8790")
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/auth/state").json() == {"required": False, "logged_in": False}
    assert c.get("/api/session").json()["token"] == "t"
    assert c.get("/").status_code == 200
    # a client from elsewhere: refused by the client guard, as before CC-0036
    r = TestClient(app, client=PHONE, base_url="http://127.0.0.1:8790").get("/api/health")
    assert r.status_code == 403 and r.json()["guard"] == "client", r.text
    # login without a password set: 409 auth_off
    r = c.post("/api/auth/login", json={"password": "x"},
               headers={"Origin": "http://127.0.0.1:8790"})
    assert r.status_code == 409 and r.json()["code"] == "auth_off", r.text


def test_not_loopback_without_a_hash_is_refused_to_start():
    for env in ({"CC_BIND": "0.0.0.0"}, {"CC_BIND": LAN}, {"CC_API_HOST": "::"}):
        try:
            Settings.from_env(env)
        except SettingsError as e:
            assert "CC_PASSWORD_HASH" in str(e) and "пароля нет" in str(e), e
        else:
            raise AssertionError(f"{env} accepted without a hash")
    try:
        create_app(Settings(host="0.0.0.0"), token="t")
    except SettingsError:
        pass
    else:
        raise AssertionError("create_app on 0.0.0.0 without a hash")
    saved = dict(os.environ)
    try:
        os.environ.pop("CC_PASSWORD_HASH", None)
        os.environ.pop("CC_API_HOST", None)
        os.environ["CC_BIND"] = "0.0.0.0"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.main(["serve"]) == 2
        assert "CC_PASSWORD_HASH" in err.getvalue(), err.getvalue()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    # with a hash it starts; CC_BIND is CC_API_HOST's other name
    s = Settings.from_env({"CC_BIND": LAN, "CC_PASSWORD_HASH": HASH})
    assert (s.host, s.password_hash) == (LAN, HASH) and not s.loopback_only
    assert Settings.from_env({"CC_BIND": LAN, "CC_API_HOST": LAN,
                              "CC_PASSWORD_HASH": HASH}).host == LAN
    for env in ({"CC_BIND": LAN, "CC_API_HOST": "0.0.0.0", "CC_PASSWORD_HASH": HASH},
                {"CC_PASSWORD_HASH": "plain-password"},
                {"CC_PASSWORD_HASH": "pbkdf2_sha256:x:abc:def"},
                {"CC_PASSWORD_HASH": "pbkdf2_sha256:1000:c2FsdHNhbHQ:c2hvcnQ"}):
        try:
            Settings.from_env(env)
        except SettingsError:
            continue
        raise AssertionError(f"{env} accepted")
    # a hash on loopback: fine, nobody from elsewhere can reach it anyway
    assert Settings.from_env({"CC_PASSWORD_HASH": HASH}).loopback_only


# --------------------------------------------------------------------- who logs in

def test_the_mac_never_logs_in():
    app, _ = app_for()
    for peer in (LOCAL, ("::1", 5000), ("127.0.0.2", 5000)):
        c = client(app, peer=peer)
        assert c.get("/api/health").status_code == 200, peer
        assert c.get("/api/session").status_code == 200, peer
        assert c.get("/api/auth/state").json() == {"required": False, "logged_in": False}
        assert c.get("/contract.json").status_code == 200


def test_a_client_from_elsewhere_gets_401_without_the_cookie():
    app, _ = app_for()
    c = client(app)
    for path in ("/api/health", "/api/session", "/api/version", "/api/questions",
                 "/api/openapi.json", "/api/nope", "/contract.json", "/assets/../contract.json"):
        r = c.get(path)
        assert r.status_code == 401, (path, r.status_code, r.text)
        assert r.json() == {"detail": "Нужен вход: откройте центр и введите пароль",
                            "code": "auth_required", "retry_after": None}, r.text
    r = c.post("/api/_probe", headers={**ORIGIN, SESSION_HEADER: "tok"})
    assert r.status_code == 401, r.text
    # the login's routes and the login screen's files are open
    assert c.get("/api/auth/state").json() == {"required": True, "logged_in": False}
    for path in ("/", "/index.html", "/batches/some", "/assets/app.js", "/favicon.svg"):
        assert c.get(path).status_code == 200, path
    assert c.get("/assets/missing.js").status_code == 404
    assert c.get("/favicon.ico").status_code == 404     # open, just not in this dist
    # X-Forwarded-For is not believed
    r = c.get("/api/health", headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
    assert r.status_code == 401, r.text
    # the Host check stays first
    r = c.get("/api/auth/state", headers={"Host": "evil.example:8790"})
    assert r.status_code == 403 and r.json()["guard"] == "host", r.text


# --------------------------------------------------------------------- the session

def test_login_wrong_and_right_password_and_the_cookie():
    app, clock = app_for()
    c = client(app)
    r = login(c, "wrong")
    assert r.status_code == 401 and r.json()["code"] == "wrong_password", r.text
    assert r.json()["detail"] == "Неверный пароль" and "set-cookie" not in r.headers
    assert clock.slept == [auth.FAIL_DELAY_S]
    # the login needs this Origin (no X-CC-Session: the page has none yet)
    r = c.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    r = c.post("/api/auth/login", json={"password": PASSWORD},
               headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    assert c.post("/api/auth/login", json={"password": ""}, headers=ORIGIN).status_code == 422
    r = login(c)
    assert r.status_code == 200 and r.json() == {"logged_in": True}, r.text
    cookie = r.headers["set-cookie"]
    m = re.match(r"cc_auth=([A-Za-z0-9_-]{40,}); Max-Age=2592000; Path=/; HttpOnly; "
                 r"SameSite=Strict$", cookie)
    assert m, cookie
    assert "secure" not in cookie.lower()        # plain http on the home network
    assert clock.slept == [auth.FAIL_DELAY_S]    # no wait on the right one


def test_the_cookie_lets_the_requests_in_and_the_write_guards_stay():
    app, _ = app_for()
    c = client(app)
    login(c)
    assert c.get("/api/auth/state").json() == {"required": True, "logged_in": True}
    assert c.get("/api/health").status_code == 200
    assert c.get("/contract.json").status_code == 200
    assert c.get("/api/session").json()["token"] == "tok"
    r = c.post("/api/_probe", headers=ORIGIN)
    assert r.status_code == 403 and r.json()["guard"] == "session", r.text
    r = c.post("/api/_probe", headers={SESSION_HEADER: "tok", "Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    r = c.post("/api/_probe", headers={**ORIGIN, SESSION_HEADER: "tok"})
    assert r.status_code == 200 and r.json() == {"done": True}, r.text
    # another phone without the cookie, or with a made-up one
    other = client(app, peer=("192.168.1.30", 4000))
    assert other.get("/api/health").status_code == 401
    assert other.get("/api/health", headers={"Cookie": "cc_auth=made-up"}).status_code == 401


def test_logout_ends_the_session():
    app, _ = app_for()
    c = client(app)
    token = re.search(r"cc_auth=([^;]+)", login(c).headers["set-cookie"]).group(1)
    r = c.post("/api/auth/logout", headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"logged_in": False}, r.text
    assert r.headers["set-cookie"].startswith("cc_auth=; Max-Age=0; Path=/;"), r.headers
    fresh = client(app)
    assert fresh.get("/api/health", headers={"Cookie": f"cc_auth={token}"}).status_code == 401
    assert c.get("/api/auth/state").json() == {"required": True, "logged_in": False}


def test_the_session_slides_and_expires():
    app, clock = app_for()
    c = client(app)
    login(c)
    clock.t += 20 * 86400
    r = c.get("/api/health")
    assert r.status_code == 200
    assert "cc_auth=" in r.headers.get("set-cookie", ""), r.headers   # set again (> 1 day)
    r = c.get("/api/health")
    assert "set-cookie" not in r.headers                              # not twice a day
    clock.t += 25 * 86400                     # 45 days after the login, 25 after the use
    assert c.get("/api/health").status_code == 200
    clock.t += 30 * 86400 + 1                 # 30 days unused: gone
    assert c.get("/api/health").status_code == 401
    assert c.get("/api/auth/state").json()["logged_in"] is False


# --------------------------------------------------------------------- guessing

def test_five_wrong_passwords_lock_the_address_for_15_minutes():
    app, clock = app_for()
    c = client(app)
    for _ in range(auth.IP_FAILS):
        assert login(c, "nope").status_code == 401
    r = login(c)                            # the right one is not even checked now
    assert r.status_code == 429, r.text
    got = r.json()
    assert got["code"] == "locked" and got["retry_after"] == 900, got
    assert "Слишком много неверных паролей" in got["detail"], got
    assert r.headers["retry-after"] == "900"
    assert len(clock.slept) == auth.IP_FAILS
    # another address still logs in
    assert login(client(app, peer=("192.168.1.31", 4000))).status_code == 200
    clock.t += 10 * 60
    r = login(c)
    assert r.status_code == 429 and r.json()["retry_after"] == 300, r.text
    clock.t += 5 * 60
    assert login(c).status_code == 200      # the lock is over


def test_failures_fall_out_of_the_window_and_a_login_clears_them():
    app, clock = app_for()
    c = client(app)
    for _ in range(auth.IP_FAILS - 1):
        assert login(c, "nope").status_code == 401
    clock.t += auth.WINDOW_S + 1
    assert login(c, "nope").status_code == 401       # 1 in the window, not 5
    for _ in range(auth.IP_FAILS - 2):
        assert login(c, "nope").status_code == 401
    assert login(c).status_code == 200               # 4 in the window: still in; cleared
    for _ in range(auth.IP_FAILS - 1):
        assert login(c, "nope").status_code == 401
    assert login(c).status_code == 200


def test_thirty_wrong_passwords_from_anywhere_lock_every_login_but_the_mac():
    app, clock = app_for()
    n = 0
    for i in range(10):
        c = client(app, peer=(f"192.168.1.{100 + i}", 4000))
        for _ in range(auth.IP_FAILS - 1):
            if n == auth.GLOBAL_FAILS:
                break
            assert login(c, "nope").status_code == 401
            n += 1
    assert n == auth.GLOBAL_FAILS
    fresh = client(app, peer=("192.168.1.250", 4000))
    r = login(fresh)
    assert r.status_code == 429 and r.json()["code"] == "locked", r.text
    assert "со всех адресов" in r.json()["detail"]
    assert login(client(app, peer=LOCAL)).status_code == 200      # the Mac is never locked
    clock.t += auth.LOCK_S
    assert login(fresh).status_code == 200


# --------------------------------------------------------------------- the hash

def test_the_hash_line_format_and_verify():
    line = auth.hash_password(PASSWORD)
    assert re.fullmatch(r"pbkdf2_sha256:600000:[A-Za-z0-9_-]{22}:[A-Za-z0-9_-]{43}", line), line
    assert "$" not in line and PASSWORD not in line
    assert auth.verify_password(PASSWORD, line)
    assert not auth.verify_password(PASSWORD + "x", line)
    assert not auth.verify_password("", line)
    assert not auth.verify_password(PASSWORD, "garbage")
    other = auth.hash_password(PASSWORD, iterations=1000)
    assert other.split(":")[2] != HASH.split(":")[2]       # a salt per hash
    assert auth.verify_password(PASSWORD, other)
    assert auth.parse_hash(other)[0] == 1000
    for bad in ("", "scrypt:1:2:3", "pbkdf2_sha256:1000:abc", "pbkdf2_sha256:0:" + "A" * 22
                + ":" + "A" * 43):
        try:
            auth.parse_hash(bad)
        except auth.HashError:
            continue
        raise AssertionError(bad)


def test_the_password_command_prints_the_hash_line_only():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        assert cli.password_line(stdin=io.StringIO(PASSWORD + "\n"), out=out) == 0
    line = out.getvalue().strip()
    assert line.startswith("CC_PASSWORD_HASH=pbkdf2_sha256:"), line
    assert PASSWORD not in out.getvalue() + err.getvalue()
    assert auth.verify_password(PASSWORD, line.split("=", 1)[1])
    s = Settings.from_env({"CC_BIND": LAN, "CC_PASSWORD_HASH": line.split("=", 1)[1]})
    assert s.password_hash
    answers = iter(["one", "two"])
    out = io.StringIO()
    with contextlib.redirect_stderr(io.StringIO()):
        assert cli.password_line(ask=lambda _p: next(answers), out=out) == 2
        assert cli.password_line(stdin=io.StringIO("\n"), out=out) == 2
    assert out.getvalue() == ""


def test_the_plist_carries_the_hash_only_when_set():
    with tempfile.TemporaryDirectory() as tmp:
        for env, want in (({}, None), ({"CC_BIND": LAN, "CC_PASSWORD_HASH": HASH}, HASH)):
            s = Settings.from_env({"CC_FACTORY_ROOT": tmp, **env})
            p = plistlib.loads(cli.plist_text(s, python="/x/python3", path_env="/bin",
                                              log=str(Path(tmp) / "l")).encode("utf-8"))
            assert p["EnvironmentVariables"].get("CC_PASSWORD_HASH") == want
            assert p["EnvironmentVariables"]["CC_API_HOST"] == s.host


# --------------------------------------------------------------------- the log

def test_the_password_is_never_logged_the_address_and_time_are():
    records = []

    class Keep(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    h = Keep()
    root = logging.getLogger()
    root.addHandler(h)
    old = root.level
    root.setLevel(logging.DEBUG)
    err = io.StringIO()
    try:
        app, clock = app_for()
        c = client(app)
        with contextlib.redirect_stderr(err):
            login(c, PASSWORD + "-typo")
            login(c, PASSWORD)
            login(c, "another-" + PASSWORD)
    finally:
        root.removeHandler(h)
        root.setLevel(old)
    text = "\n".join(records) + err.getvalue()
    assert PASSWORD not in text, text
    fails = [r for r in records if "неверный пароль" in r]
    assert len(fails) == 2, records
    assert "192.168.1.20" in fails[0] and re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", fails[0])


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
    TMP.cleanup()
    sys.exit(1 if failed else 0)

"""CC-0036 (CF-0616): the center from the home network, behind a password.

Off by default: the API listens on 127.0.0.1 and nobody logs in. The user
opts in with two variables of the environment (`api/settings.py`):

    CC_BIND=192.168.1.10                     # the address to listen on (CC_API_HOST's other name)
    CC_PASSWORD_HASH=pbkdf2_sha256:...       # `python3 -m api password` prints the line

A bind that is not loopback without a hash: the API refuses to start.
Outside the home network there is no access (Telegram; Tailscale is its own
thing) - this is the home network only.

Who logs in: a request from loopback (127.0.0.1, ::1 - the Mac itself) never;
any other client needs a session for every /api route and every file of the
center, except the login's own routes and what the login screen loads
(`OPEN_*` below; the guard in `api/app.py` asks `needs_login`). The client is
the TCP peer - `X-Forwarded-For` is never read (uvicorn runs with
`proxy_headers=False`).

The hash: `pbkdf2_sha256:<iterations>:<salt>:<hash>` (salt and hash urlsafe
base64 without padding; 16 random bytes of salt per hash) - stdlib only
(`hashlib.pbkdf2_hmac`; the Mac's python3 has no `hashlib.scrypt`), compared
with `hmac.compare_digest`, no `$` so a shell `.env` keeps it as is. The
plaintext password is never in the environment, a file or a log.

The session: `POST /api/auth/login {password}` -> a cookie `cc_auth`
(`secrets.token_urlsafe(32)`; HttpOnly, SameSite=Strict, Path=<base>,
Max-Age 30 days). Not `Secure`: the home network is plain http - SameSite
and HttpOnly are what there is. The store is this process's memory: token ->
expiry, 30 days sliding (each use moves it; the cookie is set again once a
day), at most `MAX_SESSIONS`; a restart logs everybody out (accepted).

Against guessing: per client address, `IP_FAILS` (5) wrong passwords within
`WINDOW_S` (15 min) lock that address for `LOCK_S` (15 min); `GLOBAL_FAILS`
(30) wrong passwords from anywhere within the window lock every login that is
not from loopback for `LOCK_S`. A locked attempt is not checked at all: 429
{detail, code: locked, retry_after}. Every wrong password waits `FAIL_DELAY_S`
(0.5 s) before the answer, and the checks run one at a time (a lock), so the
counts are exact. Each failure is logged (logger `api.auth`, the server's
log): the address and the time, never the password. In memory, like the
sessions.

Stdlib only: `python3 -m api password` runs before FastAPI is looked for.
"""
import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import datetime, timezone

SCHEME = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
COOKIE = "cc_auth"
SESSION_S = 30 * 24 * 3600
REFRESH_S = 24 * 3600          # the cookie is set again when it is older than this
MAX_SESSIONS = 200
IP_FAILS = 5
GLOBAL_FAILS = 30
WINDOW_S = 15 * 60
LOCK_S = 15 * 60
FAIL_DELAY_S = 0.5
LOOPBACK_CLIENTS = ("127.0.0.1", "::1")

LOG = logging.getLogger("api.auth")


class HashError(ValueError):
    """A `CC_PASSWORD_HASH` that is not `pbkdf2_sha256:<n>:<salt>:<hash>`."""


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password, iterations=ITERATIONS, salt=None):
    """The self-describing line of `CC_PASSWORD_HASH` for this password."""
    if not password:
        raise ValueError("пустой пароль")
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{SCHEME}:{iterations}:{_b64(salt)}:{_b64(dk)}"


def parse_hash(text):
    """(iterations, salt, digest) of a hash line; HashError when it is not one."""
    parts = (text or "").strip().split(":")
    if len(parts) != 4 or parts[0] != SCHEME:
        raise HashError(f"CC_PASSWORD_HASH: не `{SCHEME}:<итерации>:<соль>:<хеш>` - "
                        f"сделайте строку командой `python3 -m api password`")
    try:
        n = int(parts[1])
        salt, dk = _unb64(parts[2]), _unb64(parts[3])
    except ValueError:
        raise HashError("CC_PASSWORD_HASH: итерации, соль или хеш не читаются - "
                        "`python3 -m api password`")
    if n < 1 or len(salt) < 8 or len(dk) != 32:
        raise HashError("CC_PASSWORD_HASH: итерации, соль или хеш не той длины - "
                        "`python3 -m api password`")
    return n, salt, dk


def verify_password(password, line):
    """The password matches the hash line (compare_digest; False on a bad line)."""
    try:
        n, salt, dk = parse_hash(line)
    except HashError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, n)
    return hmac.compare_digest(got, dk)


def is_loopback(client):
    return client in LOOPBACK_CLIENTS or (client or "").startswith("127.")


class Locked(Exception):
    def __init__(self, retry_after, scope):
        super().__init__(scope)
        self.retry_after = max(1, int(retry_after + 0.999))
        self.scope = scope            # "ip" | "all"


class Auth:
    """The sessions and the failed logins of this process. `clock` and `sleep`
    are the tests' (a fake clock, no real wait)."""

    def __init__(self, password_hash=None, clock=time.time, sleep=time.sleep):
        self.password_hash = password_hash or None
        self.clock = clock
        self.sleep = sleep
        self._sessions = {}           # token -> [expires_at, cookie_set_at]
        self._fails = {}              # client -> [times]
        self._global = []             # times of every failure (not loopback)
        self._ip_lock = {}            # client -> locked until
        self._all_lock = 0.0          # every non-loopback login locked until
        self._mu = threading.Lock()   # the stores
        self._login_mu = threading.Lock()   # one login check at a time

    @property
    def enabled(self):
        return bool(self.password_hash)

    def required(self, client):
        """This client has to log in (a hash is set and it is not the Mac)."""
        return self.enabled and not is_loopback(client)

    # ---------------------------------------------------------- sessions
    def check(self, token):
        """(valid, refresh_cookie): the session is live - its expiry slides."""
        if not token:
            return False, False
        now = self.clock()
        with self._mu:
            row = self._sessions.get(token)
            if row is None:
                return False, False
            if row[0] <= now:
                del self._sessions[token]
                return False, False
            row[0] = now + SESSION_S
            refresh = now - row[1] >= REFRESH_S
            if refresh:
                row[1] = now
            return True, refresh

    def _new_session(self):
        now = self.clock()
        token = secrets.token_urlsafe(32)
        with self._mu:
            for t in [t for t, r in self._sessions.items() if r[0] <= now]:
                del self._sessions[t]
            while len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions, key=lambda t: self._sessions[t][0])
                del self._sessions[oldest]
            self._sessions[token] = [now + SESSION_S, now]
        return token

    def logout(self, token):
        with self._mu:
            self._sessions.pop(token or "", None)

    # ---------------------------------------------------------- login
    def _locked_for(self, client, now):
        """Locked (raised) or None; old failures fall out of the window."""
        if is_loopback(client):
            return
        until = self._ip_lock.get(client, 0.0)
        if until > now:
            raise Locked(until - now, "ip")
        self._ip_lock.pop(client, None)
        if self._all_lock > now:
            raise Locked(self._all_lock - now, "all")

    def _failed(self, client, now):
        if is_loopback(client):
            return 0
        cut = now - WINDOW_S
        times = [t for t in self._fails.get(client, []) if t > cut] + [now]
        self._fails[client] = times
        self._global = [t for t in self._global if t > cut] + [now]
        if len(times) >= IP_FAILS:
            self._ip_lock[client] = now + LOCK_S
            self._fails.pop(client, None)
        if len(self._global) >= GLOBAL_FAILS:
            self._all_lock = now + LOCK_S
            self._global = []
        return len(times)

    def login(self, client, password):
        """A new session token; None on a wrong password (after the delay);
        `Locked` while this address or every address is locked."""
        if not self.enabled:
            return None
        with self._login_mu:
            now = self.clock()
            with self._mu:
                self._locked_for(client, now)
            ok = verify_password(password, self.password_hash)
            if ok:
                with self._mu:
                    self._fails.pop(client, None)
            else:
                with self._mu:
                    n = self._failed(client, now)
                stamp = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
                LOG.warning("CC-0036: неверный пароль входа в центр: адрес %s, %s (%d за %d мин)",
                            client, stamp, n, WINDOW_S // 60)
        if not ok:
            self.sleep(FAIL_DELAY_S)
            return None
        return self._new_session()


def cookie_header(token, base_path, max_age=SESSION_S):
    """The Set-Cookie value of a session (empty token, max_age 0: cleared)."""
    return (f"{COOKIE}={token}; Max-Age={max_age}; Path={base_path}; HttpOnly; "
            f"SameSite=Strict")

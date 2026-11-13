#!/usr/bin/env python3
"""CF-0421 (continued by CF-0016, CF-0589): OAuth for the Publisher, installed-app flow.

An API key cannot upload - `videos.insert` takes OAuth only. The client is of
type "Desktop app" in a Google Cloud project of its own; the user signs in in a
browser (`upload.py --authorize`), the refresh token is written to
`PUBLISHER_TOKEN_FILE` outside the checkout with mode 600, and every later run
refreshes the access token from it without a browser.

The browser flow never starts by itself: a run without a usable token stops
and names the authorize command. Signing in is the user's action (CF-0016),
not a side effect of an upload.

CF-0589 - one sign-in for everything, and a week's notice:

* `SCOPES` asks for upload, readonly *and* `yt-analytics.readonly` (the
  Analyst's daily metrics, CF-0020) in one consent. A caller says which scopes
  it needs (`require=`); a token granted without one of them stops with
  `MissingScopeError` - "re-authorize, scope X is missing" - before any call
  to Google, instead of an `invalid_scope` from the API.
* The OAuth app is in Testing, so Google keeps its refresh token for 7 days
  after the consent (`PUBLISHER_TOKEN_LIFETIME_DAYS`). Each authorization
  writes a state file beside the token (`<token>.state.json`, mode 600, no
  token value in it): when it was given, when it is expected to expire, which
  scopes were granted. `status()` turns that into one line and an exit code
  for the operator and the orchestrator (the shape of `publish_queue.py
  tomorrow`); `notify()` asks one question in the journal of questions
  (shared/needs_you.py, CF-0652; until then a line of Notebook NEEDS-YOU.md) -
  only when asked to (`--needs-you`), once per term; a fine token resolves it.
* CF-0607 - the term depends on the app's publishing status
  (`PUBLISHER_OAUTH_MODE`): Testing - 7 days, as above; Production - no fixed
  term (Google drops a refresh token when it is revoked or has not been used
  for six months, https://developers.google.com/identity/protocols/oauth2#expiration),
  so the state of a Production consent carries no `expires_at` and `status`
  says "без фиксированного срока". The state records the mode it was given in.
* An expired or revoked grant (`invalid_grant` on refresh) is
  `TokenExpiredError`: the step stops with `EXIT_REAUTHORIZE`, the batch does
  not fall over.

    python3 agents/publisher/publisher_auth.py status [--now ISO] [--env FILE]
                                                      [--needs-you] [--needs-you-dir DIR]
        # exit 0 - fine; 1 - expires within PUBLISHER_TOKEN_REMIND_HOURS (the
        # reminder); 3 - the user must re-authorize now (expired, revoked, no
        # token, a scope missing, the term unknown); 2 - configuration error

The Google libraries are imported lazily, through `google_libs()`, so the rest
of the Publisher - `--dry-run`, the gate, `status`, the tests - works without
them; the tests hand `load_credentials` a stand-in namespace instead.
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

TASK = "CF-0589"

# youtube.upload - videos.insert; youtube.readonly - channels.list(mine=true),
# the check that the token belongs to the channel we mean to upload to.
UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
# CF-0589: YouTube Analytics API reports for the Analyst (CF-0020).
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
ANALYTICS_SCOPES = UPLOAD_SCOPES + [ANALYTICS_SCOPE]
# What one `--authorize` asks for: every scope any step of the factory needs.
SCOPES = list(ANALYTICS_SCOPES)

# The exact command the user runs to (re)authorize - the Google libraries live
# in the agent's venv, not in the system python.
AUTHORIZE_COMMAND = "agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize"

INSTALL_HINT = ("python3 -m venv agents/publisher/.venv && agents/publisher/.venv/bin/pip install "
                "google-api-python-client google-auth-oauthlib google-auth-httplib2")

EXIT_OK, EXIT_SOON, EXIT_ERROR, EXIT_REAUTHORIZE = 0, 1, 2, 3

OK, SOON, EXPIRED, NO_AUTH, NO_SCOPE, UNKNOWN = (
    "ok", "expires-soon", "expired", "no-auth", "no-scope", "unknown-expiry")

TESTING, PRODUCTION = "testing", "production"
# CF-0607: what a Production refresh token's term is, in the words of
# https://developers.google.com/identity/protocols/oauth2#expiration (checked 2026-10-07).
PRODUCTION_TERM = ("без фиксированного срока: действует, пока доступ не отозван и пока токен "
                   "используется (6 месяцев без использования - истекает)")

MSK = timezone(timedelta(hours=3), "МСК")   # Moscow has had no DST since 2014


class AuthError(Exception):
    pass


class ReauthorizeRequired(AuthError):
    """The user must sign in again - nothing the factory can do by itself.
    A step that gets it stops with `EXIT_REAUTHORIZE` and leaves the batch."""
    exit_code = EXIT_REAUTHORIZE


class MissingScopeError(ReauthorizeRequired):
    def __init__(self, missing, msg=None):
        self.missing = list(missing)
        super().__init__(msg or (
            f"the OAuth token was granted without scope {', '.join(short(s) for s in self.missing)} "
            f"- re-authorize (one sign-in grants every scope; leave every box ticked): "
            f"`{AUTHORIZE_COMMAND}`"))


class TokenExpiredError(ReauthorizeRequired):
    pass


def short(scope):
    return scope.rsplit("/", 1)[-1]


def google_libs():
    """The three Google entry points, imported only when a real call is made."""
    try:
        from google.auth.transport.requests import Request            # noqa: PLC0415
        from google.oauth2.credentials import Credentials             # noqa: PLC0415
        from google_auth_oauthlib.flow import InstalledAppFlow        # noqa: PLC0415
    except ImportError as e:
        raise AuthError(f"Google client libraries are not installed ({e.name}); "
                        f"install them into the agent's venv: {INSTALL_HINT}") from e
    return SimpleNamespace(Request=Request, Credentials=Credentials,
                           InstalledAppFlow=InstalledAppFlow)


def _write_600(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(p, 0o600)


def save_token(path, creds):
    """Write the token JSON with mode 600, its directory with 700."""
    _write_600(path, creds.to_json())


# --------------------------------------------------------------------------
# the token's state: when it was given, when it expires, which scopes
# --------------------------------------------------------------------------

def state_file(cfg):
    """`<token stem>.state.json` beside the token - outside the checkout, like it."""
    token = Path(cfg.token_file)
    return token.with_name(token.stem + ".state.json")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        dt = _parse(now)
        if dt is None:
            raise ValueError(f"--now {now!r}: give an ISO time with a zone")
        return dt
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def read_state(cfg):
    """The state dict, or None when there is none (or it does not parse)."""
    p = state_file(cfg)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def write_state(cfg, state):
    _write_600(state_file(cfg), json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _granted_of(creds):
    for attr in ("granted_scopes", "scopes"):
        val = getattr(creds, attr, None)
        if val:
            return sorted(val.split() if isinstance(val, str) else val)
    return sorted(SCOPES)


def record_authorization(cfg, creds, now=None):
    """After a consent: when it was given, when Google will drop the refresh
    token (Testing: `token_lifetime_days` later; Production: no fixed term,
    `expires_at` null - CF-0607), the mode, the scopes granted. No token value
    is written."""
    now = _now(now)
    mode = getattr(cfg, "oauth_mode", TESTING) or TESTING
    state = {
        "authorized_at": _iso(now),
        "oauth_mode": mode,
        "scopes": _granted_of(creds),
        "set_by": TASK,
    }
    if mode == TESTING:
        state["expires_at"] = _iso(now + timedelta(days=cfg.token_lifetime_days))
        state["lifetime_days"] = cfg.token_lifetime_days
    else:                       # CF-0607: Production - no fixed term
        state["expires_at"] = None
        state["lifetime_days"] = None
    write_state(cfg, state)
    return state


def record_invalid_grant(cfg, now=None):
    """Google refused the refresh token: the state says so, `status` says
    EXPIRED until the next consent.

    CF-0618: `invalid_grant_at` is the *first* refusal since the last consent -
    the revocation mark the deletion of API Data counts its days from
    (Developer Policies III.D.2.b, `api_data.py`); a later refusal does not move
    it. A new consent (`record_authorization`) writes a fresh state without it."""
    state = read_state(cfg) or {}
    if revoked_at(state) is None:
        state["invalid_grant_at"] = _iso(_now(now))
        write_state(cfg, state)
    return state


def revoked_at(state):
    """CF-0618: the revocation mark of a state dict (or None): the first
    `invalid_grant` that is not older than the last consent. CF-0619: a
    revocation from the client (`api_data.py revoke`, `revoked_from_client_at`)
    is a mark too - the earlier of the two counts."""
    if not state:
        return None
    authorized = _parse(state.get("authorized_at"))
    marks = [m for m in (_parse(state.get("invalid_grant_at")),
                         _parse(state.get("revoked_from_client_at")))
             if m is not None and (authorized is None or m >= authorized)]
    return min(marks) if marks else None


def record_client_revocation(cfg, google, now=None, by=None, via=None):
    """CF-0619: the owner revoked the access from the client (`api_data.py
    revoke`): the state keeps the mark and what Google answered (`revoked`,
    `invalid_token`, `no token`) - never a token value. The next consent
    writes a fresh state without it. CF-0701: `by` / `via` (who revoked and
    through what, e.g. "user" / "center"; checked by `api_data._who` before
    anything is done) go into `revoked_from_client_by` / `_via` when given."""
    state = read_state(cfg) or {}
    state["revoked_from_client_at"] = _iso(_now(now))
    state["revoked_from_client_google"] = google
    for key, value in (("by", by), ("via", via)):
        if value is not None:
            state[f"revoked_from_client_{key}"] = value
        else:
            state.pop(f"revoked_from_client_{key}", None)
    write_state(cfg, state)
    return state


def record_api_data_deleted(cfg, record, now=None):
    """CF-0618: the purge after a revocation is written into the state (what,
    when) - the console and the next auto-run read it; the next consent drops
    it with the rest of the old state."""
    state = read_state(cfg) or {}
    state["api_data_deleted"] = dict(record, at=_iso(_now(now)))
    write_state(cfg, state)
    return state


def granted_scopes(cfg):
    """The scopes of the token on disk: the state's list, else the `scopes`
    field of the token JSON (only that field is read), else None."""
    state = read_state(cfg)
    if state and isinstance(state.get("scopes"), list):
        return list(state["scopes"])
    token = Path(cfg.token_file)
    if not token.is_file():
        return None
    try:
        scopes = json.loads(token.read_text(encoding="utf-8")).get("scopes")
    except (ValueError, OSError, AttributeError):
        return None
    if isinstance(scopes, str):
        scopes = scopes.split()
    return list(scopes) if isinstance(scopes, list) and scopes else None


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------

def load_credentials(cfg, authorize=False, libs=None, require=None, now=None):
    """Credentials carrying the scopes `require` (default: the upload's).

    * a token granted without one of them -> MissingScopeError, before Google;
    * a valid token on disk -> used as is;
    * an expired one with a refresh token -> refreshed and written back;
      Google answering `invalid_grant` (the week is over, or the grant was
      revoked) -> TokenExpiredError, recorded in the state;
    * nothing usable and `authorize=False` -> AuthError naming the authorize command;
    * `authorize=True` -> the installed-app flow in a browser for every scope
      of `SCOPES` (the user signs in), the token and its state saved outside
      the checkout."""
    require = list(require or UPLOAD_SCOPES)
    g = libs or google_libs()
    token = Path(cfg.token_file)
    if not authorize:
        if not token.is_file():
            raise AuthError(f"no usable OAuth token at {token} - the user signs in with "
                            f"`{AUTHORIZE_COMMAND}` (opens a browser)")
        granted = granted_scopes(cfg)
        missing = [s for s in require if granted is not None and s not in granted]
        if missing:
            raise MissingScopeError(missing)
        try:
            creds = g.Credentials.from_authorized_user_file(str(token), granted or require)
        except (ValueError, OSError) as e:
            raise AuthError(f"{token}: the token file does not parse ({e}); delete it and run "
                            f"`{AUTHORIZE_COMMAND}`") from e
        if creds is not None and creds.valid:
            return creds
        if creds is not None and creds.expired and creds.refresh_token:
            try:
                creds.refresh(g.Request())
            except Exception as e:                              # noqa: BLE001
                text = str(e)
                if "invalid_grant" in text:
                    record_invalid_grant(cfg, now)
                    raise TokenExpiredError(
                        f"Google refused the refresh token (invalid_grant: the 7-day term of "
                        f"the Testing app is over, or the grant was revoked) - the step stops; "
                        f"the user re-authorizes: `{AUTHORIZE_COMMAND}`") from e
                if "invalid_scope" in text:
                    raise MissingScopeError(require) from e
                raise AuthError(f"refreshing the token failed ({e}) - if it repeats, "
                                f"re-authorize: `{AUTHORIZE_COMMAND}`") from e
            save_token(token, creds)
            return creds
        raise AuthError(f"no usable OAuth token at {token} - the user signs in with "
                        f"`{AUTHORIZE_COMMAND}` (opens a browser)")
    secret = Path(cfg.client_secret_file)
    if not secret.is_file():
        raise AuthError(f"no OAuth client secret at {secret} - download the Desktop-app client "
                        f"JSON from Google Cloud Console (see CF-0421, 'Что нужно от пользователя')")
    flow = g.InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    save_token(token, creds)
    state = record_authorization(cfg, creds, now)
    # the consent is the one moment to say a box was left unticked - for every
    # scope of the factory, not only the caller's
    missing = [s for s in SCOPES if s not in state["scopes"]]
    if missing:
        raise MissingScopeError(missing, (
            f"signed in, but the consent left out {', '.join(short(s) for s in missing)} - "
            f"run `{AUTHORIZE_COMMAND}` again and leave every box ticked"))
    return creds


def analytics_credentials(cfg, libs=None, now=None):
    """What the metrics step (CF-0020) calls: credentials with the Analytics
    scope, or ReauthorizeRequired (MissingScopeError / TokenExpiredError) - the
    step stops with `EXIT_REAUTHORIZE`."""
    return load_credentials(cfg, libs=libs, require=ANALYTICS_SCOPES, now=now)


# --------------------------------------------------------------------------
# status: one line and an exit code
# --------------------------------------------------------------------------

@dataclass
class TokenStatus:
    kind: str
    code: int
    line: str
    expires_at: datetime = None
    hours_left: float = None
    missing: list = field(default_factory=list)
    mode: str = None            # CF-0607: the mode the token was given in (testing / production)

    @property
    def key(self):
        """The term this status is about - one question (CF-0652) per key."""
        if self.expires_at is not None:
            return f"до {_iso(self.expires_at)[:16]}Z {self.kind}"
        return self.kind


def _msk(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M МСК")


def _when(expires, now):
    days = (expires.astimezone(MSK).date() - now.astimezone(MSK).date()).days
    return {0: "сегодня", 1: "завтра"}.get(days, f"через {days} дн.")


def status(cfg, now=None):
    """Where the token stands, in one line. Kinds and codes:
    ok (0) / expires-soon (1, within `token_remind_hours`) / expired, no-auth,
    no-scope, unknown-expiry (3). Never touches the network."""
    now = _now(now)
    token = Path(cfg.token_file)
    fix = f"`{AUTHORIZE_COMMAND}`"
    if not token.is_file():
        return TokenStatus(NO_AUTH, EXIT_REAUTHORIZE,
                           f"OAUTH NO AUTH: нет токена YouTube ({token}) - разрешите доступ "
                           f"(~30 с, браузер): {fix}")
    state = read_state(cfg) or {}
    expires = _parse(state.get("expires_at"))
    refused = revoked_at(state)
    mode = state.get("oauth_mode") or (TESTING if expires is not None else None)
    want = getattr(cfg, "oauth_mode", TESTING) or TESTING
    # CF-0607: a token given in Testing after the app went to Production keeps
    # its 7 days - a new consent drops the term (docs/api-audit/README.md, step 10)
    hint = (f"; токен выдан в режиме Testing, а PUBLISHER_OAUTH_MODE=production - переразрешите, "
            f"чтобы срок снялся: {fix}" if want == PRODUCTION and mode == TESTING else "")
    if refused is not None:
        return TokenStatus(EXPIRED, EXIT_REAUTHORIZE,
                           f"OAUTH EXPIRED: Google отказал токену YouTube {_msk(refused)} "
                           f"(invalid_grant: срок вышел или доступ отозван) - загрузка и метрики "
                           f"стоят до переразрешения (~30 с): {fix}", expires_at=expires,
                           mode=mode)
    if expires is not None and now >= expires:
        return TokenStatus(EXPIRED, EXIT_REAUTHORIZE,
                           f"OAUTH EXPIRED: токен YouTube истёк {_msk(expires)} - загрузка и "
                           f"метрики стоят до переразрешения (~30 с): {fix}", expires_at=expires,
                           hours_left=0.0, mode=mode)
    granted = granted_scopes(cfg)
    missing = [s for s in SCOPES if granted is not None and s not in granted]
    if missing:
        return TokenStatus(NO_SCOPE, EXIT_REAUTHORIZE,
                           f"OAUTH NO SCOPE: у токена YouTube нет scope "
                           f"{', '.join(short(s) for s in missing)} - переразрешите (одно "
                           f"разрешение выдаёт все scope, все галочки оставить): {fix}",
                           expires_at=expires, missing=missing, mode=mode)
    if expires is None and mode == PRODUCTION:
        return TokenStatus(OK, EXIT_OK,
                           f"ok   oauth: токен YouTube (приложение в Production) - {PRODUCTION_TERM} "
                           f"(scope: {', '.join(short(s) for s in SCOPES)})", mode=mode)
    if expires is None:
        return TokenStatus(UNKNOWN, EXIT_REAUTHORIZE,
                           f"OAUTH UNKNOWN EXPIRY: срок токена YouTube неизвестен (выдан до "
                           f"{TASK}, нет {state_file(cfg).name}) - переразрешите, чтобы фабрика "
                           f"знала срок: {fix}", mode=mode)
    left = (expires - now).total_seconds() / 3600
    if left <= cfg.token_remind_hours:
        return TokenStatus(SOON, EXIT_SOON,
                           f"OAUTH EXPIRES SOON: токен YouTube истекает {_when(expires, now)} "
                           f"{_msk(expires)} (через {left:.0f} ч) - переразрешите заранее "
                           f"(~30 с): {fix}{hint}", expires_at=expires, hours_left=left, mode=mode)
    return TokenStatus(OK, EXIT_OK,
                       f"ok   oauth: токен YouTube действует ещё {left:.0f} ч, до {_msk(expires)} "
                       f"(scope: {', '.join(short(s) for s in SCOPES)}; режим Testing){hint}",
                       expires_at=expires, hours_left=left, mode=mode)


# --------------------------------------------------------------------------
# telling the user: NEEDS-YOU (on a flag) and the notifiers
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent.parent

def _notify_bus():
    """CF-0591: the notification bus `shared/notify.py` - None when it cannot be
    loaded: a notification is never on the critical path."""
    try:
        shared = str(ROOT / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus
        return bus
    except Exception:                                            # noqa: BLE001
        return None


def _push(st):
    """CF-0591: one notification per term and state of the token (the bus's
    key is `TokenStatus.key`): "expires tomorrow" and then "expired" are two,
    the same state of the same term asked again is none."""
    bus = _notify_bus()
    if bus is not None:
        bus.on_token(st)


# Extension point: each is called with a TokenStatus that is not ok. The push
# of CF-0591 is registered here (`_push`); the question in the journal below
# stays opt-in through `needs_you=True`. A notifier that raises is said and skipped -
# telling the user is never on the critical path.
NOTIFIERS = [_push]

NEEDS_YOU_TAG = "oauth-token"
# CF-0652: the question lives in the journal of questions (shared/needs_you.py),
# one per term - its key is `oauth-token:<TokenStatus.key>`.
NEEDS_YOU_SOURCE = "publisher-auth"
NEEDS_YOU_PREFIX = f"{NEEDS_YOU_TAG}:"


def _journal():
    """shared/needs_you.py of this checkout."""
    shared = str(ROOT / "shared")
    if shared not in sys.path:
        sys.path.append(shared)
    import needs_you                                            # noqa: PLC0415
    return needs_you


def needs_you_key(st):
    return f"{NEEDS_YOU_PREFIX}{st.key}"


def needs_you_text(st):
    what = {SOON: f"токен истекает {_msk(st.expires_at)}" if st.expires_at else "токен истекает",
            EXPIRED: "токен истёк - загрузка и метрики стоят",
            NO_AUTH: "токена нет",
            NO_SCOPE: f"нет scope {', '.join(short(s) for s in st.missing)}",
            UNKNOWN: "срок токена неизвестен"}.get(st.kind, st.kind)
    return (f"Разрешить доступ YouTube заново (~30 с, приложение в Testing): "
            f"{what} - `{AUTHORIZE_COMMAND}` ({TASK})")


def write_needs_you(st, directory=None, now=None):
    """One question for this term in the journal: already asked -> nothing; a
    question of an older term (or of another state of it) -> resolved, this
    one asked. Telegram is the bus's own token notice (`_push`), so the
    journal does not send a second one. Returns (changed, message)."""
    j = _journal()
    key = needs_you_key(st)
    old = j.resolve(key_prefix=NEEDS_YOU_PREFIX, keep=key, by=NEEDS_YOU_SOURCE,
                    note="новый срок или состояние токена", now=now, directory=directory)
    q, created = j.add(NEEDS_YOU_SOURCE, key, needs_you_text(st), by=NEEDS_YOU_SOURCE,
                       link=None, now=now, notify=False, directory=directory)
    if not created and not old:
        return False, f"NEEDS-YOU: вопрос этого срока уже есть ({q['id']})"
    return True, f"NEEDS-YOU {q['id']}: {q['text']}"


def clear_needs_you(directory=None, now=None):
    """The token is fine again: its questions are resolved. (changed, message)."""
    done = _journal().resolve(key_prefix=NEEDS_YOU_PREFIX, by=NEEDS_YOU_SOURCE,
                              note="токен в порядке", now=now, directory=directory)
    if not done:
        return False, "NEEDS-YOU: вопросов токена нет"
    return True, (f"NEEDS-YOU: токен в порядке, вопрос "
                  f"{', '.join(q['id'] for q in done)} решён")


def notify(st, cfg, needs_you=False, needs_you_dir=None, notifiers=None, now=None):
    """Hand a status to whoever tells the user. Returns the messages said.
    `needs_you_dir` - the journal's directory (default: shared/needs_you.py's)."""
    said = []
    at = _now(now)
    if st.kind == OK:
        if needs_you:
            try:
                changed, msg = clear_needs_you(needs_you_dir, at)
            except Exception as e:                               # noqa: BLE001
                changed, msg = True, f"NEEDS-YOU: не записано ({e.__class__.__name__}: {e})"
            if changed:
                said.append(msg)
        return said
    for fn in (NOTIFIERS if notifiers is None else notifiers):
        try:
            fn(st)
        except Exception as e:                                   # noqa: BLE001
            said.append(f"notifier {getattr(fn, '__name__', fn)}: {e.__class__.__name__}: {e}")
    if needs_you:
        try:
            said.append(write_needs_you(st, needs_you_dir, at)[1])
        except Exception as e:                                   # noqa: BLE001
            said.append(f"NEEDS-YOU: не записано ({e.__class__.__name__}: {e})")
    return said


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description="OAuth token of the Publisher: status and reminder "
                                             "(CF-0589)", allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="one line + exit code: 0 ok, 1 expires soon, "
                                       "3 re-authorize now, 2 error")
    st.add_argument("--env", help="the .env file (default agents/publisher/.env)")
    st.add_argument("--now", help="ISO time with a zone (tests, dry checks)")
    st.add_argument("--needs-you", action="store_true",
                    help="also ask one question per term in the journal of questions "
                         "(shared/needs_you.py, CF-0652); a fine token resolves it")
    st.add_argument("--needs-you-dir", help="the journal's directory (default: $NEEDS_YOU_DIR, "
                                            "else <root>/needs-you)")
    return ap


def main(argv=None, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    import publisher_config                                     # noqa: PLC0415
    try:
        cfg = publisher_config.load(args.env)
        st = status(cfg, args.now)
        said = notify(st, cfg, needs_you=args.needs_you, needs_you_dir=args.needs_you_dir,
                      now=args.now)
    except (publisher_config.ConfigError, ValueError) as e:
        print(f"OAUTH ERROR: {e}", file=out)
        return EXIT_ERROR
    print(st.line, file=out)
    for msg in said:
        print(f"     {msg}", file=out)
    return st.code


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())

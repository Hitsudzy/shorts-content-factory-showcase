#!/usr/bin/env python3
"""CF-0589: the Publisher's OAuth - the Analytics scope, the week of a Testing
app's token, the reminder, the stop on `invalid_grant`.

Nothing here reaches Google or reads a real secret: the OAuth libraries are a
stand-in namespace handed to `publisher_auth.load_credentials`, every token,
state file and the journal of questions is a fixture in a temp dir, the configuration is
read from a temp `.env` with an empty process environment.

What is pinned:

* one `--authorize` asks for upload, readonly and yt-analytics.readonly;
* a token without a needed scope stops with "re-authorize, scope X is missing"
  before any call to Google - and a token without Analytics still uploads;
* the state beside the token: when given, when it expires (the lifetime from
  the settings), the scopes - never the token's value;
* `status`: ok / expires soon ("завтра") / expired / revoked / no token /
  no scope / unknown expiry, one line and an exit code, CLI included;
* NEEDS-YOU (CF-0652: the journal of questions): only with the flag, one
  question per term, the older term resolved, resolved when the token is fine,
  no second Telegram (the bus's token notice is the one);
* the notifiers list is called for a status that is not ok (CF-0591's hook);
* `invalid_grant` on refresh -> TokenExpiredError, recorded, exit 3 from upload.py.
"""
import io
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import publisher_auth as pa         # noqa: E402
import publisher_config             # noqa: E402
import upload                       # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("publisher-oauth-test-")
_n = [0]
T0 = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)        # 12:00 МСК
SECRET = "r-secret-value"


def fixture(extra=""):
    _n[0] += 1
    base = TMP / f"f{_n[0]}"
    (base / "vault").mkdir(parents=True)
    env = base / "x.env"
    env.write_text(f"PUBLISHER_CLIENT_SECRET_FILE={base}/sec/client_secret.json\n"
                   f"PUBLISHER_TOKEN_FILE={base}/sec/youtube.oauth-token.json\n"
                   f"PUBLISHER_CHANNEL_ID=UCtest\n"
                   + extra)
    cfg = publisher_config.load(env, environ={})
    return cfg, env, base


class Creds:
    def __init__(self, valid=True, expired=False, scopes=None, granted=None, refresh_error=None):
        self.valid, self.expired, self.refresh_token = valid, expired, SECRET
        self.scopes = scopes
        self.granted_scopes = granted
        self.refresh_error = refresh_error
        self.refreshed = False

    def refresh(self, request):
        if self.refresh_error:
            raise self.refresh_error
        self.refreshed, self.valid, self.expired = True, True, False

    def to_json(self):
        return json.dumps({"refresh_token": self.refresh_token, "scopes": self.scopes})


def libs(on_disk=None, flow_creds=None):
    log = []

    class Flow:
        @staticmethod
        def from_client_secrets_file(path, scopes):
            log.append(("flow", tuple(scopes)))
            return SimpleNamespace(run_local_server=lambda **kw: (log.append(("browser",)),
                                                                  flow_creds)[1])

    def from_file(path, scopes):
        log.append(("load", tuple(scopes)))
        return on_disk

    return SimpleNamespace(Credentials=SimpleNamespace(from_authorized_user_file=from_file),
                           Request=lambda: "REQ", InstalledAppFlow=Flow), log


def authorize(cfg, now=T0, granted=None):
    cfg.client_secret_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.client_secret_file.write_text("{}")
    g, log = libs(flow_creds=Creds(scopes=list(pa.SCOPES), granted=granted))
    pa.load_credentials(cfg, authorize=True, libs=g, now=now)
    return log


def token_with(cfg, scopes):
    cfg.token_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.token_file.write_text(json.dumps({"refresh_token": SECRET, "scopes": scopes}))


# ---------------------------------------------------------------- scopes

def test_one_authorize_asks_for_upload_readonly_and_analytics():
    cfg, _, _ = fixture()
    log = authorize(cfg)
    assert log[0][0] == "flow" and log[1][0] == "browser"
    asked = set(log[0][1])
    assert pa.ANALYTICS_SCOPE == "https://www.googleapis.com/auth/yt-analytics.readonly"
    assert asked == {pa.ANALYTICS_SCOPE, *pa.UPLOAD_SCOPES}, asked
    assert pa.ANALYTICS_SCOPE in pa.ANALYTICS_SCOPES and set(pa.UPLOAD_SCOPES) < set(pa.ANALYTICS_SCOPES)


def test_a_token_without_analytics_stops_before_google_but_still_uploads():
    cfg, _, _ = fixture()
    token_with(cfg, list(pa.UPLOAD_SCOPES))
    g, log = libs(on_disk=Creds())
    try:
        pa.analytics_credentials(cfg, libs=g)
    except pa.MissingScopeError as e:
        assert "yt-analytics.readonly" in str(e) and pa.AUTHORIZE_COMMAND in str(e), str(e)
        assert e.missing == [pa.ANALYTICS_SCOPE] and e.exit_code == pa.EXIT_REAUTHORIZE
        assert not log, f"Google was reached: {log}"
    else:
        raise AssertionError("a token without the Analytics scope must stop")
    # the upload needs only its two scopes, and the refresh asks for no more
    # than was granted (more would be an invalid_scope from Google)
    g, log = libs(on_disk=Creds())
    pa.load_credentials(cfg, libs=g)
    assert log == [("load", tuple(pa.UPLOAD_SCOPES))], log


def test_a_consent_with_the_analytics_box_unticked_is_said_at_once():
    cfg, _, _ = fixture()
    try:
        authorize(cfg, granted=list(pa.UPLOAD_SCOPES))
    except pa.MissingScopeError as e:
        assert "yt-analytics.readonly" in str(e) and "every box" in str(e)
    else:
        raise AssertionError("a consent without the Analytics box must be said at once")
    assert cfg.token_file.is_file(), "the token is kept - the upload scopes still work"
    assert pa.status(cfg, T0).kind == pa.NO_SCOPE


# ---------------------------------------------------------------- state

def test_authorization_records_given_and_expiry_from_settings_never_the_token():
    cfg, _, _ = fixture("PUBLISHER_TOKEN_LIFETIME_DAYS=5\n")
    assert cfg.token_lifetime_days == 5
    authorize(cfg)
    sf = pa.state_file(cfg)
    assert sf.name == "youtube.oauth-token.state.json" and sf.parent == cfg.token_file.parent
    text = sf.read_text()
    assert SECRET not in text and "refresh_token" not in text
    st = json.loads(text)
    assert st["authorized_at"] == "2026-10-06T09:00:00Z"
    assert st["expires_at"] == "2026-10-11T09:00:00Z"
    assert set(st["scopes"]) == set(pa.SCOPES)
    assert stat.S_IMODE(os.stat(sf).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(cfg.token_file).st_mode) == 0o600


def test_default_lifetime_is_a_week_and_a_bad_setting_is_refused():
    cfg, env, _ = fixture()
    assert cfg.token_lifetime_days == 7 and cfg.token_remind_hours == 24
    for bad in ("0", "-1", "week"):
        try:
            publisher_config.load(env, environ={"PUBLISHER_TOKEN_LIFETIME_DAYS": bad})
        except publisher_config.ConfigError as e:
            assert "PUBLISHER_TOKEN_LIFETIME_DAYS" in str(e)
        else:
            raise AssertionError(f"lifetime {bad!r} must be refused")
    src = (AGENT / "publisher_auth.py").read_text()
    assert "days=7" not in src and "hours=24" not in src, "the week is a setting, not a literal"


# ---------------------------------------------------------------- status

def test_status_ok_soon_tomorrow_and_expired():
    cfg, _, _ = fixture()
    authorize(cfg)                                   # expires 2026-10-13 09:00Z = 12:00 МСК
    st = pa.status(cfg, T0 + timedelta(days=3))
    assert (st.kind, st.code) == (pa.OK, 0) and st.line.startswith("ok   oauth:"), st.line
    assert "96 ч" in st.line and "2026-10-13 12:00 МСК" in st.line
    st = pa.status(cfg, datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc))   # 19:00 МСК
    assert (st.kind, st.code) == (pa.SOON, pa.EXIT_SOON), st.line
    assert "истекает завтра 2026-10-13 12:00 МСК" in st.line and "через 17 ч" in st.line
    assert pa.AUTHORIZE_COMMAND in st.line and "\n" not in st.line
    st = pa.status(cfg, datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc))
    assert st.kind == pa.SOON and "истекает сегодня" in st.line
    st = pa.status(cfg, datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc))
    assert (st.kind, st.code) == (pa.EXPIRED, pa.EXIT_REAUTHORIZE) and "истёк" in st.line


def test_status_no_auth_no_scope_and_unknown_expiry():
    cfg, _, _ = fixture()
    st = pa.status(cfg, T0)
    assert (st.kind, st.code) == (pa.NO_AUTH, 3) and pa.AUTHORIZE_COMMAND in st.line
    token_with(cfg, list(pa.UPLOAD_SCOPES))          # a token from before CF-0589
    st = pa.status(cfg, T0)
    assert (st.kind, st.code) == (pa.NO_SCOPE, 3) and "yt-analytics.readonly" in st.line
    token_with(cfg, list(pa.SCOPES))                 # all scopes, but no state
    st = pa.status(cfg, T0)
    assert (st.kind, st.code) == (pa.UNKNOWN, 3) and "неизвестен" in st.line


def test_reminder_window_comes_from_settings():
    cfg, _, _ = fixture("PUBLISHER_TOKEN_REMIND_HOURS=48\n")
    authorize(cfg)
    assert pa.status(cfg, T0 + timedelta(days=5, hours=1)).kind == pa.SOON
    assert pa.status(cfg, T0 + timedelta(days=4, hours=23)).kind == pa.OK


def test_cli_status_prints_one_line_and_its_exit_code():
    cfg, env, _ = fixture()
    out = io.StringIO()
    assert pa.main(["status", "--env", str(env), "--now", "2026-10-06T09:00:00Z"], out=out) == 3
    assert len(out.getvalue().splitlines()) == 1 and "NO AUTH" in out.getvalue()
    authorize(cfg)
    for now, code in (("2026-10-07T09:00:00Z", 0), ("2026-10-12T12:00:00Z", 1),
                      ("2026-10-14T09:00:00Z", 3)):
        out = io.StringIO()
        assert pa.main(["status", "--env", str(env), "--now", now], out=out) == code, out.getvalue()
        assert len(out.getvalue().splitlines()) == 1, out.getvalue()
    out = io.StringIO()
    assert pa.main(["status", "--env", str(env), "--now", "yesterday"], out=out) == pa.EXIT_ERROR
    assert out.getvalue().startswith("OAUTH ERROR")


# ---------------------------------------------------------------- NEEDS-YOU (CF-0652: the journal)

def _journal():
    sys.path.insert(0, str(ROOT / "shared"))
    import needs_you
    return needs_you


def test_needs_you_only_with_the_flag_and_one_question_per_term():
    cfg, env, base = fixture()
    jd = base / "needs-you"
    nyj = _journal()
    nyj.add("other", "other:1", "something else", directory=jd, notify=False)
    authorize(cfg)
    soon = "2026-10-12T12:00:00Z"
    flag = ["--needs-you", "--needs-you-dir", str(jd)]
    assert pa.main(["status", "--env", str(env), "--now", soon, "--needs-you-dir", str(jd)],
                   out=io.StringIO()) == 1
    assert [q["key"] for q in nyj.live(directory=jd)] == ["other:1"], \
        "without --needs-you the journal is not touched"
    for _ in range(3):
        out = io.StringIO()
        assert pa.main(["status", "--env", str(env), "--now", soon] + flag, out=out) == 1

    def mine(status="live"):
        return nyj.questions(status=status, source=pa.NEEDS_YOU_SOURCE, directory=jd)
    assert len(mine()) == 1, mine()
    q = mine()[0]
    assert pa.AUTHORIZE_COMMAND in q["text"] and "2026-10-13 12:00 МСК" in q["text"]
    assert q["created"] == soon and q["key"].startswith("oauth-token:")
    # the same term going past its end: the old state resolved, one live question saying so
    pa.main(["status", "--env", str(env), "--now", "2026-10-14T09:00:00Z"] + flag,
            out=io.StringIO())
    assert len(mine()) == 1 and "истёк" in mine()[0]["text"], mine()
    # re-authorized: fine again -> resolved; a new term soon -> a new question
    authorize(cfg, now=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc))
    out = io.StringIO()
    pa.main(["status", "--env", str(env), "--now", "2026-10-15T09:00:00Z"] + flag, out=out)
    assert mine() == [] and "решён" in out.getvalue(), out.getvalue()
    assert [q["key"] for q in nyj.live(directory=jd)] == ["other:1"], "another's question stays"
    assert {q["resolved_by"] for q in mine("resolved")} == {pa.NEEDS_YOU_SOURCE}
    pa.main(["status", "--env", str(env), "--now", "2026-10-20T12:00:00Z"] + flag,
            out=io.StringIO())
    assert len(mine()) == 1 and "2026-10-21 13:00 МСК" in mine()[0]["text"], mine()


def test_needs_you_sends_no_second_telegram_and_a_journal_error_is_said():
    cfg, _, base = fixture()
    st = pa.status(cfg, T0)
    jd = base / "j"
    got = []
    said = pa.notify(st, cfg, needs_you=True, needs_you_dir=jd, notifiers=[got.append], now=T0)
    assert len(got) == 1 and said[0].startswith("NEEDS-YOU Q1"), said
    sent = (jd / "questions.jsonl").read_text()
    assert '"op": "add"' in sent
    bad = base / "a-file"
    bad.write_text("x")
    said = pa.notify(st, cfg, needs_you=True, needs_you_dir=bad / "j", notifiers=[], now=T0)
    assert "не записано" in said[0], said


def test_notifiers_are_the_extension_point_for_a_push():
    cfg, _, base = fixture()
    got = []
    pa.notify(pa.status(cfg, T0), cfg, notifiers=[got.append])
    assert [s.kind for s in got] == [pa.NO_AUTH]
    assert not (base / "needs-you").exists(), "no flag - no question"
    authorize(cfg)
    got.clear()
    pa.notify(pa.status(cfg, T0), cfg, notifiers=[got.append])
    assert not got, "an ok token tells nobody"
    assert pa.NOTIFIERS == [pa._push], "CF-0591's push is the one registered notifier"


# ---------------------------------------------------------------- invalid_grant

def test_invalid_grant_stops_the_step_and_is_recorded():
    cfg, _, _ = fixture()
    authorize(cfg)
    refused = Exception("invalid_grant: Token has been expired or revoked.")
    g, _ = libs(on_disk=Creds(valid=False, expired=True, refresh_error=refused))
    later = T0 + timedelta(days=2)
    try:
        pa.analytics_credentials(cfg, libs=g, now=later)
    except pa.TokenExpiredError as e:
        assert isinstance(e, pa.ReauthorizeRequired) and e.exit_code == 3
        assert pa.AUTHORIZE_COMMAND in str(e)
    else:
        raise AssertionError("invalid_grant must be TokenExpiredError")
    st = pa.status(cfg, later + timedelta(hours=1))
    assert (st.kind, st.code) == (pa.EXPIRED, 3) and "invalid_grant" in st.line, st.line
    authorize(cfg, now=later + timedelta(hours=2))
    assert pa.status(cfg, later + timedelta(hours=3)).kind == pa.OK


def test_other_refresh_failures_are_not_a_reauthorize_and_invalid_scope_is_a_scope():
    cfg, _, _ = fixture()
    authorize(cfg)
    g, _ = libs(on_disk=Creds(valid=False, expired=True, refresh_error=OSError("network down")))
    try:
        pa.load_credentials(cfg, libs=g)
    except pa.ReauthorizeRequired:
        raise AssertionError("a network failure is not the user's to fix")
    except pa.AuthError as e:
        assert "network down" in str(e)
    g, _ = libs(on_disk=Creds(valid=False, expired=True,
                              refresh_error=Exception("invalid_scope: Bad Request")))
    try:
        pa.analytics_credentials(cfg, libs=g)
    except pa.MissingScopeError:
        pass
    else:
        raise AssertionError("invalid_scope must be MissingScopeError")
    assert "invalid_grant_at" not in pa.read_state(cfg)


def test_upload_exits_3_with_a_clear_line_when_the_user_must_reauthorize():
    _, env, _ = fixture()

    def factory(cfg, authorize=False):
        raise pa.TokenExpiredError(f"expired - run `{pa.AUTHORIZE_COMMAND}`")
    out = io.StringIO()
    assert upload.main(["--authorize", "--env", str(env)], client_factory=factory, out=out) == 3
    assert out.getvalue().startswith("REAUTHORIZE:") and pa.AUTHORIZE_COMMAND in out.getvalue()


def test_skill_md_says_who_calls_status_and_the_exact_command():
    text = (AGENT / "SKILL.md").read_text(encoding="utf-8")
    assert "publisher_auth.py status" in text and pa.AUTHORIZE_COMMAND in text
    assert "invalid_grant" in text and "--needs-you" in text



# ---------------------------------------------------------------- CF-0607: the app's mode

def test_oauth_mode_is_testing_by_default_and_a_bad_mode_is_refused():
    cfg, env, _ = fixture()
    assert cfg.oauth_mode == "testing"
    assert publisher_config.load(env, environ={"PUBLISHER_OAUTH_MODE": "Production"}).oauth_mode \
        == "production"
    try:
        publisher_config.load(env, environ={"PUBLISHER_OAUTH_MODE": "prod"})
    except publisher_config.ConfigError as e:
        assert "PUBLISHER_OAUTH_MODE" in str(e)
    else:
        raise AssertionError("an unknown mode must be refused")
    example = (AGENT / ".env.example").read_text(encoding="utf-8")
    assert "PUBLISHER_OAUTH_MODE=testing" in example


def test_testing_mode_keeps_the_week_and_the_status_says_testing():
    cfg, _, _ = fixture()
    authorize(cfg)
    st = json.loads(pa.state_file(cfg).read_text())
    assert st["oauth_mode"] == "testing" and st["expires_at"] == "2026-10-13T09:00:00Z"
    s = pa.status(cfg, T0 + timedelta(days=1))
    assert s.kind == pa.OK and s.mode == "testing" and "режим Testing" in s.line
    assert pa.status(cfg, T0 + timedelta(days=8)).kind == pa.EXPIRED


def test_production_mode_has_no_fixed_term_and_never_expires_by_the_clock():
    cfg, _, _ = fixture("PUBLISHER_OAUTH_MODE=production\n")
    authorize(cfg)
    st = json.loads(pa.state_file(cfg).read_text())
    assert st["oauth_mode"] == "production" and st["expires_at"] is None
    for later in (timedelta(days=8), timedelta(days=100)):
        s = pa.status(cfg, T0 + later)
        assert s.kind == pa.OK and s.code == pa.EXIT_OK and s.mode == "production", s.line
        assert "без фиксированного срока" in s.line and "6 месяцев" in s.line
    pa.record_invalid_grant(cfg, T0 + timedelta(days=9))       # revoked - still said
    assert pa.status(cfg, T0 + timedelta(days=10)).kind == pa.EXPIRED


def test_a_testing_token_after_publish_app_keeps_its_week_and_asks_for_a_new_consent():
    cfg, env, _ = fixture()
    authorize(cfg)                                             # given in Testing
    prod = publisher_config.load(env, environ={"PUBLISHER_OAUTH_MODE": "production"})
    s = pa.status(prod, T0 + timedelta(days=1))
    assert s.kind == pa.OK and s.mode == "testing" and "переразрешите" in s.line
    assert pa.status(prod, T0 + timedelta(days=8)).kind == pa.EXPIRED

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

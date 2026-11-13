#!/usr/bin/env python3
"""CF-0618: API Data under the YouTube API Services Developer Policies -
`agents/publisher/api_data.py` and the revocation mark of `publisher_auth`.

Nothing here reaches Google or touches the live `analytics/`, `publish/` or the
token: every root, journal, note, token state and `.env` is a fixture in a temp
dir, YouTube is a stand-in client.

What is pinned:

* the revocation mark is the *first* `invalid_grant` since the consent; a new
  consent clears it;
* a dry run (the CLI's default) deletes nothing and says what it would;
* `--delete` removes only API Data: daily.jsonl, runs.jsonl, summary/ and the
  API rows of the journal (their non-API part kept in `api_data_deleted`), the
  video id in the note and README - never studio/backfill rows, studio.jsonl,
  rights.jsonl;
* `purge --channel` keeps the other channel's data;
* the auto-run deletes only a revocation past PURGE_AFTER_DAYS (inside the
  30-day limit), nothing before it and nothing after a new consent;
* the journal refresh through videos.list: due after REFRESH_DAYS, privacy
  status and api_refreshed_at rewritten, a missing video gets removed_at; a
  row stale for STALE_DAYS is deleted by the auto-run;
* the upload gate refuses an entry whose API row was deleted;
* the console line, the deletion log;
* CF-0619 `revoke`: a dry run changes nothing; `--yes` POSTs the token to
  Google's revoke endpoint (a stand-in `urlopen`, with a timeout), deletes the
  token file and all API Data, logs `revoked from the client`, marks the
  state; Google's 400 (`invalid_token`) does not stop the local deletion; no
  answer from Google stops before anything local; no token -> said so and the
  API Data is deleted all the same; the token value is never in the output,
  the log or the state.
"""
import ast
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import api_data                     # noqa: E402
import publisher_auth as pa         # noqa: E402
import publisher_config             # noqa: E402
import upload_gate                  # noqa: E402
import upload_records               # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("api-data-test-")
_n = [0]
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
CH, CH2 = "example-film", "example-tech"
API_ID, STUDIO_ID, API2_ID = "APIvid12345", "STUvid12345", "TECvid12345"


def _row(ch, slug, vid, source, **kw):
    r = {"channel": ch, "entry_id": f"{ch}/2026-09-29T0900Z/{slug}", "batch_id": "2026-09-29T0900Z",
         "topic_id": "t1", "slug": slug, "video_id": vid, "url": f"https://youtube.com/shorts/{vid}",
         "publish_at": "2026-09-30T22:00:00Z", "publish_tz": "UTC", "publish_day": "2026-10-01",
         "note": f"publish/{ch}/2026-10-01/{slug}.md", "source": source,
         "recorded_at": "2026-09-29T10:00:00Z"}
    if source == "api":
        r.update(uploaded_at="2026-09-29T10:00:00Z", privacy_status="private", title="T")
    r.update(kw)
    assert upload_records.check_row(r) == [], upload_records.check_row(r)
    return r


def fixture(state=None):
    _n[0] += 1
    base = TMP / f"f{_n[0]}"
    root = base / "root"
    pub = root / "publish"
    rows = [_row(CH, "harbourlights", API_ID, "api"), _row(CH, "comet", STUDIO_ID, "studio"),
            _row(CH2, "chips", API2_ID, "api")]
    pub.mkdir(parents=True)
    (pub / "uploads.json").write_text(json.dumps({"uploads": rows}, indent=2))
    for r in rows:
        n = root / r["note"]
        n.parent.mkdir(parents=True, exist_ok=True)
        n.write_text(f"# {r['slug']}\n\n`youtube.com/shorts/{r['video_id']}`\n")
    (pub / "README.md").write_text("".join(f"| `{r['slug']}` | `youtube.com/shorts/{r['video_id']}` |\n"
                                           for r in rows))
    for ch in (CH, CH2):
        a = root / "analytics" / ch
        (a / "summary").mkdir(parents=True)
        for f in ("daily.jsonl", "windows.jsonl", "runs.jsonl", "studio.jsonl", "rights.jsonl"):
            (a / f).write_text('{"x": 1}\n')
        (a / "summary" / "2026-10-01.json").write_text("{}")
    env = base / "x.env"
    env.write_text(f"PUBLISHER_CLIENT_SECRET_FILE={base}/sec/client_secret.json\n"
                   f"PUBLISHER_TOKEN_FILE={base}/sec/youtube.oauth-token.json\n"
                   f"PUBLISHER_CHANNEL_ID=UCtest\n"
                   f"PUBLISHER_NEEDS_YOU_FILE={base}/vault/NEEDS-YOU.md\n")
    cfg = publisher_config.load(env, environ={})
    if state is not None:
        pa.write_state(cfg, state)
    return root, cfg


def _api_files(root, ch=CH):
    a = root / "analytics" / ch
    return {f: (a / f).exists() for f in ("daily.jsonl", "windows.jsonl", "runs.jsonl", "summary",
                                          "studio.jsonl", "rights.jsonl")}


def _journal(root):
    return json.loads((root / "publish" / "uploads.json").read_text())


def _authorized(at=T0 - timedelta(days=10)):
    return {"authorized_at": pa._iso(at), "expires_at": pa._iso(at + timedelta(days=7)),
            "scopes": list(pa.SCOPES)}


# ----------------------------------------------------------------- the mark

def test_the_mark_is_the_first_invalid_grant_and_a_new_consent_clears_it():
    _, cfg = fixture(_authorized())
    pa.record_invalid_grant(cfg, T0)
    pa.record_invalid_grant(cfg, T0 + timedelta(days=3))
    assert pa.revoked_at(pa.read_state(cfg)) == T0
    Path(cfg.token_file).write_text("{}")
    st = pa.status(cfg, T0 + timedelta(days=3))
    assert st.kind == pa.EXPIRED

    class C:
        granted_scopes = list(pa.SCOPES)
    pa.record_authorization(cfg, C(), T0 + timedelta(days=4))
    assert pa.revoked_at(pa.read_state(cfg)) is None
    pa.record_invalid_grant(cfg, T0 + timedelta(days=12))
    assert pa.revoked_at(pa.read_state(cfg)) == T0 + timedelta(days=12)


def test_an_invalid_grant_older_than_the_consent_is_no_mark():
    st = dict(_authorized(T0), invalid_grant_at=pa._iso(T0 - timedelta(days=1)))
    assert pa.revoked_at(st) is None


# ----------------------------------------------------------------- purge on request

def test_a_dry_run_deletes_nothing_and_says_what_it_would():
    root, cfg = fixture()
    before = (root / "publish" / "uploads.json").read_text()
    out = io.StringIO()
    assert api_data.main(["purge", "--all", "--root", str(root)], out=out) == 0
    text = out.getvalue()
    assert "dry run" in text and "daily.jsonl" in text and API_ID in text
    assert all(_api_files(root).values()) and all(_api_files(root, CH2).values())
    assert (root / "publish" / "uploads.json").read_text() == before
    assert API_ID in (root / "publish" / "README.md").read_text()
    assert not (root / "publish" / api_data.LOG).exists()


def test_delete_removes_only_api_data():
    root, cfg = fixture()
    out = io.StringIO()
    assert api_data.main(["purge", "--all", "--delete", "--root", str(root),
                          "--now", "2026-10-02T00:00:00Z"], out=out) == 0
    for ch in (CH, CH2):
        f = _api_files(root, ch)
        assert not f["daily.jsonl"] and not f["runs.jsonl"] and not f["summary"], (ch, f)
        assert not f["windows.jsonl"], (ch, f)          # CF-0624: window rows are API Data too
        assert f["studio.jsonl"] and f["rights.jsonl"], (ch, f)
    doc = _journal(root)
    assert [r["video_id"] for r in doc["uploads"]] == [STUDIO_ID], "the studio row stays whole"
    gone = doc[api_data.DELETED_KEY]
    assert {g["slug"] for g in gone} == {"harbourlights", "chips"}
    for g in gone:
        assert not set(api_data.API_ROW_FIELDS) & set(g), g
        assert g["entry_id"] and g["api_data_deleted_at"] == "2026-10-02T00:00:00Z"
    assert API_ID not in json.dumps(doc) and API2_ID not in json.dumps(doc)
    readme = (root / "publish" / "README.md").read_text()
    assert API_ID not in readme and STUDIO_ID in readme and api_data.SCRUBBED in readme
    assert API_ID not in (root / f"publish/{CH}/2026-10-01/harbourlights.md").read_text()
    assert STUDIO_ID in (root / f"publish/{CH}/2026-10-01/comet.md").read_text()
    assert upload_records.check_journal(root / "publish" / "uploads.json") == []
    log = [json.loads(x) for x in (root / "publish" / api_data.LOG).read_text().splitlines()]
    assert len(log) == 1 and log[0]["reason"].startswith("owner's request")
    assert API_ID not in json.dumps(log), "the log carries no API Data"
    out = io.StringIO()
    api_data.main(["purge", "--all", "--root", str(root)], out=out)
    assert "nothing to delete" in out.getvalue(), "idempotent"


def test_purge_of_one_channel_keeps_the_other():
    root, _ = fixture()
    assert api_data.main(["purge", "--channel", CH, "--delete", "--root", str(root)],
                         out=io.StringIO()) == 0
    assert not _api_files(root, CH)["daily.jsonl"] and all(_api_files(root, CH2).values())
    vids = {r["video_id"] for r in _journal(root)["uploads"]}
    assert vids == {STUDIO_ID, API2_ID}


def test_purge_needs_all_or_a_channel():
    try:
        api_data.main(["purge", "--delete"], out=io.StringIO())
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("purge without --all/--channel ran")


# ----------------------------------------------------------------- the auto-run

def test_auto_deletes_only_a_revocation_past_its_term():
    mark = T0
    root, cfg = fixture(dict(_authorized(), invalid_grant_at=pa._iso(mark)))
    fresh = {"api_refreshed_at": pa._iso(mark + timedelta(days=24))}
    doc = _journal(root)
    for r in doc["uploads"]:
        r.update(fresh)
    (root / "publish" / "uploads.json").write_text(json.dumps(doc))
    early = mark + timedelta(days=api_data.PURGE_AFTER_DAYS) - timedelta(hours=1)
    assert api_data.auto(cfg, root, early, delete=True) == []
    assert all(_api_files(root).values())
    due = mark + timedelta(days=api_data.PURGE_AFTER_DAYS)
    assert api_data.PURGE_AFTER_DAYS < api_data.RETENTION_DAYS == 30
    # the CLI without --delete is a dry run even when due
    out = io.StringIO()
    api_data.main(["auto", "--root", str(root), "--now", pa._iso(due)], out=out, cfg=cfg)
    assert "dry run" in out.getvalue() and all(_api_files(root).values())
    done = api_data.auto(cfg, root, due, delete=True)
    assert len(done) == 1 and done[0][1]["reason"].startswith("revoked")
    assert not _api_files(root)["daily.jsonl"] and _api_files(root)["studio.jsonl"]
    assert [r["video_id"] for r in _journal(root)["uploads"]] == [STUDIO_ID]
    assert pa.read_state(cfg)["api_data_deleted"]["at"] == pa._iso(due)
    line = api_data.status(cfg, root, due)
    assert line["line"].startswith("API Data удалены"), line


def test_auto_does_nothing_without_a_mark_or_after_a_new_consent():
    root, cfg = fixture(dict(_authorized(T0 + timedelta(days=2)),
                             invalid_grant_at=pa._iso(T0)))
    doc = _journal(root)
    for r in doc["uploads"]:
        r["api_refreshed_at"] = pa._iso(T0 + timedelta(days=40))
    (root / "publish" / "uploads.json").write_text(json.dumps(doc))
    late = T0 + timedelta(days=41)
    assert api_data.auto(cfg, root, late, delete=True) == []
    assert all(_api_files(root).values()) and len(_journal(root)["uploads"]) == 3
    root2, cfg2 = fixture(_authorized())
    assert api_data.auto(cfg2, root2, T0, delete=True) == []
    assert all(_api_files(root2).values())


def test_the_console_line_names_the_dates():
    root, cfg = fixture(dict(_authorized(), invalid_grant_at=pa._iso(T0)))
    line = api_data.status(cfg, root, T0 + timedelta(days=1))
    assert line["kind"] == "bad" and "2026-10-26" in line["line"] and "2026-10-31" in line["line"]
    root, cfg = fixture(_authorized())
    doc = _journal(root)
    for r in doc["uploads"]:
        r["api_refreshed_at"] = pa._iso(T0)
    (root / "publish" / "uploads.json").write_text(json.dumps(doc))
    ok = api_data.status(cfg, root, T0 + timedelta(days=1))
    assert ok["kind"] == "ok" and "отзыва доступа нет" in ok["line"], ok
    warn = api_data.status(cfg, root, T0 + timedelta(days=8))
    assert warn["kind"] == "warn" and "не обновлялись" in warn["line"], warn


# ----------------------------------------------------------------- refresh (III.E.4.c)

class FakeYT:
    def __init__(self, statuses):
        self.statuses, self.asked = statuses, []

    def video_statuses(self, ids):
        self.asked.append(list(ids))
        return {v: s for v, s in self.statuses.items() if v in ids}


def test_refresh_rewrites_the_api_fields_and_marks_a_missing_video():
    root, _ = fixture()
    yt = FakeYT({API_ID: {"privacyStatus": "public"}})
    early = datetime(2026, 9, 29, 10, tzinfo=timezone.utc) + timedelta(days=api_data.REFRESH_DAYS - 1)
    assert api_data.refresh_journal(yt, root, now=early)["asked"] == [] and yt.asked == []
    now = early + timedelta(days=1)
    res = api_data.refresh_journal(yt, root, now=now)
    assert sorted(res["asked"]) == sorted([API_ID, API2_ID]) and len(yt.asked) == 1
    assert STUDIO_ID not in yt.asked[0], "a studio row is not API Data - never asked"
    rows = {r["video_id"]: r for r in _journal(root)["uploads"]}
    assert rows[API_ID]["privacy_status"] == "public"
    assert rows[API_ID]["api_refreshed_at"] == pa._iso(now)
    assert rows[API2_ID]["removed_at"] == pa._iso(now) and res["missing"] == [API2_ID]
    assert "api_refreshed_at" not in rows[STUDIO_ID]
    assert upload_records.check_journal(root / "publish" / "uploads.json") == []
    assert api_data.refresh_journal(yt, root, now=now + timedelta(days=1))["asked"] == []


def test_a_row_stale_for_28_days_is_deleted_by_the_auto_run():
    root, cfg = fixture(_authorized())
    doc = _journal(root)
    for r in doc["uploads"]:
        if r["video_id"] == API2_ID:
            r["api_refreshed_at"] = pa._iso(T0 + timedelta(days=20))
    (root / "publish" / "uploads.json").write_text(json.dumps(doc))
    now = datetime(2026, 9, 29, 10, tzinfo=timezone.utc) + timedelta(days=api_data.STALE_DAYS)
    assert api_data.STALE_DAYS < api_data.RETENTION_DAYS
    done = api_data.auto(cfg, root, now, delete=True)
    assert len(done) == 1 and "not refreshed" in done[0][1]["reason"]
    vids = {r["video_id"] for r in _journal(root)["uploads"]}
    assert vids == {STUDIO_ID, API2_ID}, vids
    assert all(_api_files(root).values()), "the stale rule touches no analytics file"


# ----------------------------------------------------------------- the gate

def test_the_gate_refuses_an_entry_whose_api_row_was_deleted():
    root, _ = fixture()
    api_data.main(["purge", "--channel", CH, "--delete", "--root", str(root)], out=io.StringIO())
    doc = _journal(root)
    gone = doc[api_data.DELETED_KEY][0]

    class A:
        @staticmethod
        def row_keys(row):
            return [row["entry_id"]]
    upload_gate._acceptance = lambda: A
    try:
        upload_gate.check_not_uploaded({"entry_id": gone["entry_id"], "slug": "harbourlights"},
                                       doc["uploads"] + doc[api_data.DELETED_KEY])
    except upload_gate.GateError as e:
        assert "already uploaded through the API" in str(e)
    else:
        raise AssertionError("an upload whose id was deleted went through the gate")


def test_upload_py_passes_the_deleted_rows_to_the_gate():
    text = (AGENT / "upload.py").read_text(encoding="utf-8")
    assert 'jdoc.get("api_data_deleted")' in text


# ----------------------------------------------------------------- CF-0619: revoke

REFRESH, ACCESS = "1//refresh-SECRET-value", "ya29.access-SECRET-value"


def _with_token(cfg, data=None):
    Path(cfg.token_file).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.token_file).write_text(json.dumps(data if data is not None else {
        "token": ACCESS, "refresh_token": REFRESH, "client_id": "cid"}))


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _google(answer="ok"):
    """A stand-in for urllib.request.urlopen; returns (fake, calls)."""
    calls = []

    def fake(req, timeout=None):
        calls.append({"url": req.full_url, "data": req.data, "method": req.get_method(),
                      "timeout": timeout})
        if answer == "ok":
            return _Resp()
        if answer == "invalid_token":
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                         io.BytesIO(b'{"error": "invalid_token", '
                                                    b'"error_description": "Token expired"}'))
        if answer == "5xx":
            raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, io.BytesIO(b""))
        raise urllib.error.URLError(f"timed out {REFRESH}")
    return fake, calls


def _revoke(root, cfg, argv=(), answer="ok"):
    fake, calls = _google(answer)
    old = urllib.request.urlopen
    urllib.request.urlopen = fake
    out = io.StringIO()
    try:
        code = api_data.main(["revoke", "--root", str(root), "--now", "2026-10-02T00:00:00Z",
                              *argv], out=out, cfg=cfg)
    finally:
        urllib.request.urlopen = old
    return code, out.getvalue(), calls


def _no_secret(root, cfg, text):
    blobs = [text]
    for f in [root / "publish" / api_data.LOG, pa.state_file(cfg)]:
        if f.exists():
            blobs.append(f.read_text())
    for b in blobs:
        assert REFRESH not in b and ACCESS not in b and "SECRET" not in b, b


def test_revoke_dry_run_changes_nothing():
    root, cfg = fixture(_authorized())
    _with_token(cfg)
    state = pa.state_file(cfg).read_text()
    journal = (root / "publish" / "uploads.json").read_text()
    code, text, calls = _revoke(root, cfg)
    assert code == 0 and calls == [], (code, calls)
    assert "dry run" in text and "--yes" in text and api_data.REVOKE_URL in text
    assert "daily.jsonl" in text and API_ID in text, text
    assert Path(cfg.token_file).exists() and pa.state_file(cfg).read_text() == state
    assert all(_api_files(root).values()) and all(_api_files(root, CH2).values())
    assert (root / "publish" / "uploads.json").read_text() == journal
    assert not (root / "publish" / api_data.LOG).exists()
    _no_secret(root, cfg, text)


def test_revoke_yes_revokes_deletes_the_token_and_api_data_and_logs():
    root, cfg = fixture(_authorized())
    _with_token(cfg)
    code, text, calls = _revoke(root, cfg, ["--yes"])
    assert code == 0, text
    assert len(calls) == 1 and calls[0]["url"] == api_data.REVOKE_URL
    assert calls[0]["method"] == "POST" and calls[0]["timeout"] == api_data.REVOKE_TIMEOUT_S
    assert calls[0]["data"].decode() == "token=" + urllib.parse.quote_plus(REFRESH), \
        "the refresh token is revoked first"
    assert not Path(cfg.token_file).exists()
    for ch in (CH, CH2):
        f = _api_files(root, ch)
        assert not f["daily.jsonl"] and not f["runs.jsonl"] and not f["summary"], (ch, f)
        assert not f["windows.jsonl"], (ch, f)          # CF-0624: window rows are API Data too
        assert f["studio.jsonl"] and f["rights.jsonl"], "Studio data is not API Data"
    assert [r["video_id"] for r in _journal(root)["uploads"]] == [STUDIO_ID]
    log = [json.loads(x) for x in (root / "publish" / api_data.LOG).read_text().splitlines()]
    assert len(log) == 1 and log[0]["reason"] == "revoked from the client", log
    assert log[0]["google"] == "revoked"
    st = pa.read_state(cfg)
    assert st["revoked_from_client_at"] == "2026-10-02T00:00:00Z"
    assert st["revoked_from_client_google"] == "revoked"
    assert st["api_data_deleted"]["reason"] == "revoked from the client"
    assert pa.revoked_at(st) == datetime(2026, 10, 2, tzinfo=timezone.utc)
    assert api_data.status(cfg, root, "2026-10-02T00:00:00Z")["line"].startswith(
        "API Data удалены")
    _no_secret(root, cfg, text)


def test_revoke_with_only_an_access_token_sends_it():
    root, cfg = fixture(_authorized())
    _with_token(cfg, {"token": ACCESS})
    code, text, calls = _revoke(root, cfg, ["--yes"])
    assert code == 0 and calls[0]["data"].decode() == "token=" + urllib.parse.quote_plus(ACCESS)
    _no_secret(root, cfg, text)


def test_google_invalid_token_does_not_stop_the_local_deletion():
    root, cfg = fixture(_authorized())
    _with_token(cfg)
    code, text, calls = _revoke(root, cfg, ["--yes"], answer="invalid_token")
    assert code == 0 and len(calls) == 1, text
    assert "invalid_token" in text and "already invalid" in text, text
    assert not Path(cfg.token_file).exists() and not _api_files(root)["daily.jsonl"]
    log = json.loads((root / "publish" / api_data.LOG).read_text().splitlines()[0])
    assert log["google"] == "invalid_token" and log["reason"] == "revoked from the client"
    assert pa.read_state(cfg)["revoked_from_client_google"] == "invalid_token"
    _no_secret(root, cfg, text)


def test_no_answer_from_google_changes_nothing_local():
    for answer in ("network", "5xx"):
        root, cfg = fixture(_authorized())
        _with_token(cfg)
        code, text, calls = _revoke(root, cfg, ["--yes"], answer=answer)
        assert code == api_data.EXIT_ERROR and len(calls) == 1, (answer, text)
        assert "nothing changed" in text and api_data.GOOGLE_PAGE in text, text
        assert Path(cfg.token_file).exists() and all(_api_files(root).values())
        assert not (root / "publish" / api_data.LOG).exists()
        assert "revoked_from_client_at" not in pa.read_state(cfg)
        _no_secret(root, cfg, text)


def test_revoke_without_a_token_still_deletes_the_api_data():
    root, cfg = fixture(_authorized())
    code, text, calls = _revoke(root, cfg)
    assert code == 0 and calls == [] and "no token file" in text and "daily.jsonl" in text, text
    code, text, calls = _revoke(root, cfg, ["--yes"])
    assert code == 0 and calls == [] and "no token file" in text, text
    assert not _api_files(root)["daily.jsonl"] and not _api_files(root, CH2)["daily.jsonl"]
    log = json.loads((root / "publish" / api_data.LOG).read_text().splitlines()[0])
    assert log["google"] == "no token"
    assert pa.read_state(cfg)["revoked_from_client_google"] == "no token"


def test_a_new_consent_clears_the_client_mark():
    _, cfg = fixture(_authorized())
    pa.record_client_revocation(cfg, "revoked", T0)
    assert pa.revoked_at(pa.read_state(cfg)) == T0

    class C:
        granted_scopes = list(pa.SCOPES)
    pa.record_authorization(cfg, C(), T0 + timedelta(days=1))
    assert pa.revoked_at(pa.read_state(cfg)) is None


def test_every_urlopen_in_api_data_names_its_timeout():
    tree = ast.parse((AGENT / "api_data.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", getattr(n.func, "id", None)) == "urlopen"]
    assert calls, "revoke_at_google posts through urlopen"
    for c in calls:
        assert any(k.arg == "timeout" for k in c.keywords), ast.dump(c)


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

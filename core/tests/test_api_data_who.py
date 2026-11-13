#!/usr/bin/env python3
"""CF-0701: `agents/publisher/api_data.py` for the command center (CC-0028) -
who deleted the API Data, and `revoke` as data.

Nothing here reaches Google or touches the live `analytics/`, `publish/` or the
token: the fixtures are `test_api_data`'s (a temp root, a temp token state),
Google is its stand-in `urlopen`.

What is pinned:

* `apply(extra={"by", "via"})` (the center's purge) writes who deleted into the
  journal row (`api_data_deleted_by` / `_via`) and the log; a bad by/via is
  refused before anything is deleted;
* without by/via (the CLI purge) the journal row has no `api_data_deleted_by`
  - never the task number "CF-0618" any more - and the log record is the old
  one;
* an old journal row with `api_data_deleted_by: "CF-0618"` still reads
  (`who_deleted`, the gate, `check_journal`);
* `auto` marks its deletions `by: "auto"` (journal rows, log, the token
  state's `api_data_deleted`); `auto(by="user", via="center")` writes those;
* `revoke_result`: the structure on success, on Google's refusal
  (invalid_token), on no answer (unreachable - nothing changed), with no token
  file, and the dry run; by/via reach the log, the journal rows and the
  token state (`revoked_from_client_by` / `_via`); a bad by/via is refused
  before Google is asked; the token value is never in it;
* the CLI output of `revoke --yes` is the one it was before CF-0701.
"""
import io
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_api_data as base             # noqa: E402 - its fixtures and the Google stand-in
from test_api_data import (API2_ID, API_ID, CH, CH2, STUDIO_ID, T0, _api_files,  # noqa: E402
                           _authorized, _google, _journal, _no_secret, _with_token, fixture)

api_data, pa, upload_gate, upload_records = (base.api_data, base.pa, base.upload_gate,
                                             base.upload_records)
NOW = "2026-10-02T00:00:00Z"


def _log(root):
    p = root / "publish" / api_data.LOG
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _with_google(answer, fn):
    import urllib.request
    fake, calls = _google(answer)
    old = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        return fn(), calls
    finally:
        urllib.request.urlopen = old


def _refused(fn, what):
    try:
        fn()
    except ValueError as e:
        assert what in str(e), e
    else:
        raise AssertionError(f"{what}: a bad value went through")


BAD = ["", "   ", "a\nb", "x" * 41, 7]


# ----------------------------------------------------------------- apply / purge

def test_the_centers_purge_writes_who_deleted_into_the_row_and_the_log():
    root, _ = fixture()
    p = api_data.plan(root, reason="owner's request (III.E.4.g)")
    rec = api_data.apply(p, NOW, extra={"by": "user", "via": "center"})
    assert rec["by"] == "user" and rec["via"] == "center" and rec["task"] == api_data.TASK
    gone = _journal(root)[api_data.DELETED_KEY]
    assert gone and all(g["api_data_deleted_by"] == "user" and g["api_data_deleted_via"] == "center"
                        for g in gone), gone
    assert all(api_data.who_deleted(g) == {"by": "user", "via": "center", "task": None}
               for g in gone)
    assert _log(root)[0]["by"] == "user" and _log(root)[0]["via"] == "center"


def test_without_by_the_row_names_nobody_and_never_the_task_number():
    root, _ = fixture()
    assert api_data.main(["purge", "--all", "--delete", "--root", str(root), "--now", NOW],
                         out=io.StringIO()) == 0
    gone = _journal(root)[api_data.DELETED_KEY]
    assert gone
    for g in gone:
        assert "api_data_deleted_by" not in g and "api_data_deleted_via" not in g, g
        assert api_data.TASK not in json.dumps(g), g
        assert api_data.who_deleted(g) == {"by": None, "via": None, "task": None}
    rec = _log(root)[0]
    assert set(rec) == {"at", "reason", "channels", "files", "dirs", "entries", "texts", "task"}, \
        "without by/via the log record is the old one"


def test_a_bad_by_or_via_is_refused_before_anything_is_deleted():
    root, _ = fixture()
    journal = (root / "publish" / "uploads.json").read_text()
    for bad in BAD:
        for key in ("by", "via"):
            p = api_data.plan(root)
            _refused(lambda: api_data.apply(p, NOW, extra={key: bad}), key)
    assert (root / "publish" / "uploads.json").read_text() == journal
    assert all(_api_files(root).values()) and not _log(root)


def test_an_old_row_with_the_task_number_still_reads():
    root, _ = fixture()
    old = {"channel": CH, "entry_id": f"{CH}/2026-09-29T0900Z/harbourlights", "slug": "harbourlights",
           "batch_id": "2026-09-29T0900Z", "source": "api", "publish_day": "2026-10-01",
           "note": f"publish/{CH}/2026-10-01/harbourlights.md", "uploaded_at": "2026-09-29T10:00:00Z",
           "api_data_deleted_at": "2026-10-02T00:00:00Z",
           "api_data_deleted_reason": "owner's request (III.E.4.g)",
           "api_data_deleted_by": "CF-0618"}
    doc = _journal(root)
    doc["uploads"] = [r for r in doc["uploads"] if r["video_id"] != API_ID]
    doc[api_data.DELETED_KEY] = [old]
    jpath = root / "publish" / "uploads.json"
    jpath.write_text(json.dumps(doc))
    assert api_data.who_deleted(old) == {"by": None, "via": None, "task": "CF-0618"}
    assert api_data.who_deleted({}) == {"by": None, "via": None, "task": None}
    assert api_data.who_deleted({"api_data_deleted_by": 5}) == {"by": None, "via": None,
                                                                 "task": None}
    assert upload_records.check_journal(jpath) == []
    try:
        upload_gate.check_not_uploaded({"entry_id": old["entry_id"], "slug": "harbourlights"},
                                       doc["uploads"] + doc[api_data.DELETED_KEY])
    except upload_gate.GateError as e:
        assert "already uploaded through the API" in str(e)
    else:
        raise AssertionError("an old deleted row no longer holds the gate")
    # a later purge keeps the old row as it was and adds the new one beside it
    api_data.apply(api_data.plan(root), NOW, extra={"by": "user", "via": "center"})
    gone = _journal(root)[api_data.DELETED_KEY]
    assert gone[0] == old and gone[1]["api_data_deleted_by"] == "user", gone
    assert api_data.status(None, root, NOW)["kind"] == "ok"


# ----------------------------------------------------------------- auto

def _due_mark():
    root, cfg = fixture(dict(_authorized(), invalid_grant_at=pa._iso(T0)))
    doc = _journal(root)
    for r in doc["uploads"]:
        r["api_refreshed_at"] = pa._iso(T0 + timedelta(days=24))
    (root / "publish" / "uploads.json").write_text(json.dumps(doc))
    return root, cfg, T0 + timedelta(days=api_data.PURGE_AFTER_DAYS)


def test_the_auto_run_marks_its_deletions_auto():
    root, cfg, due = _due_mark()
    done = api_data.auto(cfg, root, due, delete=True)
    assert len(done) == 1 and done[0][1]["by"] == "auto" and "via" not in done[0][1]
    gone = _journal(root)[api_data.DELETED_KEY]
    assert gone and all(g["api_data_deleted_by"] == "auto" and "api_data_deleted_via" not in g
                        for g in gone), gone
    assert _log(root)[0]["by"] == "auto"
    st = pa.read_state(cfg)["api_data_deleted"]
    assert st["by"] == "auto" and st["at"] == pa._iso(due), st


def test_auto_from_the_center_writes_by_and_via():
    root, cfg, due = _due_mark()
    done = api_data.auto(cfg, root, due, delete=True, by="user", via="center")
    assert done[0][1]["by"] == "user" and done[0][1]["via"] == "center"
    assert all(g["api_data_deleted_by"] == "user" and g["api_data_deleted_via"] == "center"
               for g in _journal(root)[api_data.DELETED_KEY])
    st = pa.read_state(cfg)["api_data_deleted"]
    assert (st["by"], st["via"]) == ("user", "center"), st


def test_the_stale_rule_of_auto_writes_who_deleted_too():
    root, cfg = fixture(_authorized())
    doc = _journal(root)
    for r in doc["uploads"]:
        if r["video_id"] == API2_ID:
            r["api_refreshed_at"] = pa._iso(T0 + timedelta(days=20))
    (root / "publish" / "uploads.json").write_text(json.dumps(doc))
    now = T0 + timedelta(days=api_data.STALE_DAYS)
    done = api_data.auto(cfg, root, now, delete=True, via="center")
    assert done and done[0][1]["by"] == "auto" and done[0][1]["via"] == "center"
    gone = _journal(root)[api_data.DELETED_KEY]
    assert [g["slug"] for g in gone] == ["harbourlights"]
    assert gone[0]["api_data_deleted_by"] == "auto" and gone[0]["api_data_deleted_via"] == "center"


def test_auto_refuses_a_bad_by_before_deleting():
    root, cfg, due = _due_mark()
    for bad in BAD:
        _refused(lambda: api_data.auto(cfg, root, due, delete=True, by=bad), "by")
        _refused(lambda: api_data.auto(cfg, root, due, delete=True, via=bad), "via")
    assert all(_api_files(root).values()) and not _log(root)
    assert "api_data_deleted" not in pa.read_state(cfg)


# ----------------------------------------------------------------- revoke as data

def _result(answer="ok", token=True, yes=True, **who):
    root, cfg = fixture(_authorized())
    if token:
        _with_token(cfg)
    res, calls = _with_google(answer, lambda: api_data.revoke_result(
        cfg, root, NOW, yes=yes, **who))
    json.dumps(res)                                  # plain data the center can send on
    _no_secret(root, cfg, json.dumps(res))
    return root, cfg, res, calls


def test_revoke_result_on_success():
    root, cfg, res, calls = _result(by="user", via="center")
    assert len(calls) == 1
    assert (res["dry_run"], res["ok"], res["exit"]) == (False, True, api_data.EXIT_OK)
    assert (res["by"], res["via"]) == ("user", "center")
    assert res["google"] == {"answer": "revoked", "detail": "HTTP 200", "url": api_data.REVOKE_URL}
    assert res["token"] == {"file": str(cfg.token_file), "kind": "refresh token", "missing": None,
                            "existed": True, "deleted": True}
    assert not Path(cfg.token_file).exists()
    assert res["state_file"] == str(pa.state_file(cfg)) and res["log"] == "publish/" + api_data.LOG
    assert res["reason"] == api_data.REVOKED_REASON and set(res["channels"]) == {CH, CH2}
    assert any(API_ID in line for line in res["items"]) and len(res["items"]) == 14
    rec = res["deletion"]
    assert rec == _log(root)[0] and rec["google"] == "revoked"
    assert (rec["by"], rec["via"]) == ("user", "center")
    gone = _journal(root)[api_data.DELETED_KEY]
    assert all(g["api_data_deleted_by"] == "user" and g["api_data_deleted_via"] == "center"
               for g in gone)
    st = pa.read_state(cfg)
    assert (st["revoked_from_client_by"], st["revoked_from_client_via"]) == ("user", "center")
    assert st["revoked_from_client_google"] == "revoked"
    assert (st["api_data_deleted"]["by"], st["api_data_deleted"]["via"]) == ("user", "center")


def test_revoke_result_when_google_refuses_the_token():
    root, cfg, res, _ = _result("invalid_token")
    assert res["ok"] and res["exit"] == api_data.EXIT_OK
    assert res["google"]["answer"] == "invalid_token" and "400" in res["google"]["detail"]
    assert res["token"]["deleted"] and res["deletion"]["google"] == "invalid_token"
    assert "by" not in res["deletion"] and res["by"] is None and res["via"] is None
    st = pa.read_state(cfg)
    assert "revoked_from_client_by" not in st and "by" not in st["api_data_deleted"]
    assert all("api_data_deleted_by" not in g for g in _journal(root)[api_data.DELETED_KEY])


def test_revoke_result_when_google_does_not_answer():
    for answer in ("network", "5xx"):
        root, cfg, res, _ = _result(answer, by="user", via="center")
        assert (res["ok"], res["exit"]) == (False, api_data.EXIT_ERROR), res
        assert res["google"]["answer"] == "unreachable" and res["deletion"] is None
        assert res["token"]["existed"] and not res["token"]["deleted"] and res["items"] == []
        assert Path(cfg.token_file).exists() and all(_api_files(root).values()) and not _log(root)
        assert "revoked_from_client_at" not in pa.read_state(cfg)


def test_revoke_result_without_a_token():
    root, cfg, res, calls = _result(token=False, by="user")
    assert calls == [] and res["ok"]
    assert res["google"]["answer"] == "no token" and res["google"]["detail"] is None
    assert res["token"] == {"file": str(cfg.token_file), "kind": None, "missing": "no token file",
                            "existed": False, "deleted": False}
    assert res["deletion"]["google"] == "no token" and res["deletion"]["by"] == "user"
    assert "via" not in res["deletion"] and not _api_files(root)["daily.jsonl"]
    assert pa.read_state(cfg)["revoked_from_client_by"] == "user"


def test_revoke_result_dry_run_changes_nothing():
    root, cfg, res, calls = _result(yes=False, by="user", via="center")
    assert calls == [] and res["dry_run"] and res["ok"] and res["deletion"] is None
    assert res["google"]["answer"] is None and res["token"]["kind"] == "refresh token"
    assert res["token"]["existed"] and not res["token"]["deleted"]
    assert len(res["items"]) == 14 and Path(cfg.token_file).exists() and not _log(root)
    assert "revoked_from_client_at" not in pa.read_state(cfg)


def test_revoke_refuses_a_bad_by_before_asking_google():
    root, cfg = fixture(_authorized())
    _with_token(cfg)
    for bad in BAD:
        for key in ("by", "via"):
            _, calls = _with_google("ok", lambda: _refused(
                lambda: api_data.revoke_result(cfg, root, NOW, yes=True, **{key: bad}), key))
            assert calls == [], "Google was asked before by/via were checked"
    assert Path(cfg.token_file).exists() and all(_api_files(root).values()) and not _log(root)
    out = io.StringIO()                                  # the printing wrapper raises the same
    _refused(lambda: api_data.revoke(cfg, root, NOW, yes=True, out=out, via="a\nb"), "via")


def test_a_later_revocation_without_by_drops_the_old_by():
    _, cfg = fixture(_authorized())
    pa.record_client_revocation(cfg, "revoked", T0, by="user", via="center")
    st = pa.record_client_revocation(cfg, "no token", T0 + timedelta(days=1))
    assert "revoked_from_client_by" not in st and "revoked_from_client_via" not in st


# ----------------------------------------------------------------- the CLI output

GOLDEN_YES = """google  revoked (HTTP 200)
token   <BASE>/sec/youtube.oauth-token.json deleted
state   <BASE>/sec/youtube.oauth-token.state.json: revocation mark 2026-10-02T00:00:00Z
revoked from the client: 14 item(s) deleted
  file  analytics/example-film/daily.jsonl
  file  analytics/example-film/windows.jsonl
  file  analytics/example-film/runs.jsonl
  file  analytics/example-tech/daily.jsonl
  file  analytics/example-tech/windows.jsonl
  file  analytics/example-tech/runs.jsonl
  dir   analytics/example-film/summary/ (0 file(s))
  dir   analytics/example-tech/summary/ (0 file(s))
  row   publish/uploads.json: example-film harbourlights APIvid12345 (source api) -> API fields deleted, the rest kept in `api_data_deleted`
  row   publish/uploads.json: example-tech chips TECvid12345 (source api) -> API fields deleted, the rest kept in `api_data_deleted`
  text  publish/README.md: APIvid12345 -> [id удалён по политике YouTube API, CF-0618]
  text  publish/example-film/2026-10-01/harbourlights.md: APIvid12345 -> [id удалён по политике YouTube API, CF-0618]
  text  publish/README.md: TECvid12345 -> [id удалён по политике YouTube API, CF-0618]
  text  publish/example-tech/2026-10-01/chips.md: TECvid12345 -> [id удалён по политике YouTube API, CF-0618]
log     publish/api-data-deletions.jsonl
"""

GOLDEN_HEADS = {
    ("--yes", "invalid_token", True): [
        "google  refused: the token is already invalid (HTTP 400 invalid_token) - the local "
        "deletion goes on",
        "token   <BASE>/sec/youtube.oauth-token.json deleted"],
    ("--yes", "5xx", True): [
        "Google did not answer the revocation (HTTP 503): nothing changed, the token is kept "
        "for a retry; or revoke on https://myaccount.google.com/permissions"],
    ("--yes", "ok", False): [
        "google  nothing to revoke: no token file (<BASE>/sec/youtube.oauth-token.json) - the "
        "API Data is deleted all the same",
        "state   <BASE>/sec/youtube.oauth-token.state.json: revocation mark 2026-10-02T00:00:00Z"],
    ("", "ok", True): [
        "revoke - dry run (add --yes):",
        "  google  POST https://oauth2.googleapis.com/revoke (refresh token of "
        "<BASE>/sec/youtube.oauth-token.json)",
        "  token   <BASE>/sec/youtube.oauth-token.json -> deleted",
        "  state   <BASE>/sec/youtube.oauth-token.state.json: the revocation mark "
        "(revoked_from_client_at), api_data_deleted",
        "  log     publish/api-data-deletions.jsonl: reason `revoked from the client`",
        "revoked from the client: 14 item(s) would be deleted (dry run - add --yes)"],
}


def _cli(flag, answer, token):
    root, cfg = fixture(_authorized())
    if token:
        _with_token(cfg)
    code, text, _ = base._revoke(root, cfg, [flag] if flag else [], answer=answer)
    return code, text.replace(str(Path(cfg.token_file).parent.parent), "<BASE>")


def test_the_cli_output_of_revoke_is_the_old_one():
    code, text = _cli("--yes", "ok", True)
    assert code == 0 and text == GOLDEN_YES, text
    for (flag, answer, token), head in GOLDEN_HEADS.items():
        code, text = _cli(flag, answer, token)
        assert text.splitlines()[:len(head)] == head, (flag, answer, token, text)
        assert code == (api_data.EXIT_ERROR if answer == "5xx" else 0)


def test_the_cli_refuses_nothing_new_and_prints_an_error_for_a_bad_value():
    # the CLI has no --by/--via: its callers (the owner, the tick) are unchanged;
    # a ValueError inside main is printed as an error with exit 2
    out = io.StringIO()
    root, cfg = fixture(_authorized())
    old = api_data.revoke
    api_data.revoke = lambda *a, **k: api_data.revoke_result(cfg, root, NOW, yes=True, by="")
    try:
        code = api_data.main(["revoke", "--yes", "--root", str(root)], out=out, cfg=cfg)
    finally:
        api_data.revoke = old
    assert code == api_data.EXIT_ERROR and out.getvalue().startswith("error: by=''"), out.getvalue()
    assert STUDIO_ID in (root / "publish" / "uploads.json").read_text()


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v) and getattr(v, "__module__", "") == __name__]
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

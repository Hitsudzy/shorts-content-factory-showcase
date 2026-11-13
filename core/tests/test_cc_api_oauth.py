#!/usr/bin/env python3
"""CC-0028: the publisher's OAuth token and the API Data in the command
center's API (`api/oauth.py`; `GET /api/oauth/token`, `/oauth/api-data`,
`/oauth/revoke`, `POST /api/oauth/api-data/purge/plan {scope, channels}`,
`/oauth/api-data/purge {confirm}`; CC-0082: `POST /api/oauth/revoke/plan`,
`/oauth/revoke {confirm}`, `/oauth/api-data/auto/plan`, `/oauth/api-data/auto
{confirm}`) over the factory's
`agents/publisher/publisher_auth.py` (status, read_state, granted_scopes) and
`agents/publisher/api_data.py` (status, revocation, plan, describe, auto
without delete, apply, the dry revoke; CC-0082: revoke_result, auto with
delete - by user via center).

In-process (starlette's TestClient) against a stand-in factory root in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`, a git repo on main - the
working factory). **Nothing outside the temp dirs is read or written**: the
publisher's `.env` and environment are stand-ins (`oauth.FACTORY_KW`: temp
secret paths outside every git tree, `environ` - never the process's), the
clock is fixed; **no network** - `api_data.revoke_at_google`,
`urllib.request.urlopen`, `publisher_auth.load_credentials` and a socket's
`connect` are replaced by ones that fail the test if reached.

What is pinned:

* the contract: the three GETs and the six POSTs, version 0.48.0,
  `OAuthProblem` on the problems, the shapes of the token, the API Data, the
  plan and the result;
* the module never names the factory's revoking, credential, notifying or
  state-writing functions; `revoke` only in its preview, with `yes=False`;
  `revoke_result` with `yes=True` only in the confirmed revocation, `auto`
  with `delete=True` only in the confirmed deletion by term, both by user via
  center; `apply` only in the confirmed purge;
* **no secret leaves**: a planted access token, refresh token and client
  secret (in the token file and the client's file) appear in no response;
* the token: ok with its term, scopes and state; no token; a refusal mark
  (expired, the revocation's term); a configuration that does not read 409;
* the API Data held (`purge --all`'s plan), the kept files not in it; what
  the auto-run would delete once the revocation's term is past - nothing
  deleted by a GET;
* the revoke's dry run: its lines and `revoke_result` as data, nothing
  reaches Google, nothing changes;
* the revocation (CC-0082): the plan changes nothing; the confirm asks a
  stand-in Google (the real one, `urlopen` and a socket fail the test) and
  answers with the factory's structured result - the token deleted, the API
  Data deleted, the log row, the journal rows and the state say by user via
  center; Google not answering changes nothing; an already invalid token and
  no token go on; nothing to revoke; a plan that changed or emptied;
* the deletion by term (CC-0082): nothing due before the term; past it the
  confirm deletes by user via center (the log row, the journal row, the
  state's `api_data_deleted`); a stale row; a plan that changed;
* the purge: the plan deletes nothing; the confirm deletes what it named, the
  log row says by user via center; a channel of its own; nothing to delete
  (no token); unknown / no channels; a plan that changed (`check_changed`) or
  emptied (`refused`); a spent, expired or foreign token.
"""
import ast
import json
import socket
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import BASE, TMP, _N, _w, client, factory_tree, git  # noqa: E402

import api                                                          # noqa: E402
from api import batches, factory, oauth                             # noqa: E402
from api.app import SESSION_HEADER                                  # noqa: E402

H = {"Origin": BASE, SESSION_HEADER: "tok"}
NOW = "2026-10-11T12:00:00Z"
AUTHORIZED = "2026-10-09T12:00:00Z"           # Testing: 7 days - expires 2026-10-16
ACCESS = "ya29.planted-access-token-41"
REFRESH = "1//planted-refresh-token-42"
CLIENT_SECRET = "GOCSPX-planted-client-secret-43"
SECRETS = (ACCESS, REFRESH, CLIENT_SECRET)
GETS = {"/api/oauth/token", "/api/oauth/api-data", "/api/oauth/revoke"}
PLAN, CONFIRM = "/api/oauth/api-data/purge/plan", "/api/oauth/api-data/purge"
RPLAN, REVOKE = "/api/oauth/revoke/plan", "/api/oauth/revoke"
APLAN, AUTO = "/api/oauth/api-data/auto/plan", "/api/oauth/api-data/auto"
VID, VID_STUDIO = "apiVideo001", "stuVideo002"
#: What `api/oauth.py` never names: revoking, credentials, telling, state writers, files.
FORBIDDEN = {"revoke_at_google", "token_value", "load_credentials", "analytics_credentials",
             "notify", "write_needs_you", "record_authorization", "record_invalid_grant",
             "record_client_revocation", "record_api_data_deleted", "write_state",
             "refresh_journal", "set_switch", "urlopen", "read_text", "read_bytes", "open",
             "write_text", "write_bytes", "unlink", "rmtree", "mkdir", "subprocess"}


def _secrets_dir():
    _N[0] += 1
    return TMP / f"oauth-secrets-{_N[0]}"      # outside every git tree


def _mods():
    c = factory.collect()
    c.journal()
    return c.pubcfg(), c.auth(), c.api_data()


def cfg():
    pc, _, _ = _mods()
    return pc.load(oauth.FACTORY_KW["env_file"], oauth.FACTORY_KW["environ"])


def setup(token=True, state=True):
    s = _secrets_dir()
    oauth.FACTORY_KW.clear()
    oauth.FACTORY_KW.update({
        "now": NOW, "env_file": str(s / "publisher.env"),
        "environ": {"PUBLISHER_TOKEN_FILE": str(s / "token.json"),
                    "PUBLISHER_CLIENT_SECRET_FILE": str(s / "client_secret.json"),
                    "PUBLISHER_OAUTH_MODE": "testing"}})
    _, pa, _ = _mods()
    _w(s / "client_secret.json", {"installed": {"client_id": "planted.apps.example",
                                                "client_secret": CLIENT_SECRET}})
    if token:
        _w(s / "token.json", {"token": ACCESS, "refresh_token": REFRESH,
                              "client_id": "planted.apps.example",
                              "client_secret": CLIENT_SECRET, "scopes": list(pa.SCOPES)})
    if state:
        pa.record_authorization(cfg(), SimpleNamespace(granted_scopes=list(pa.SCOPES)),
                                AUTHORIZED)
    return s


def world():
    """reel: its analytics (API Data and kept Studio reads), an API row and a
    Studio row of the journal, the video id in the note and publish/README.md."""
    root = factory_tree()
    a = root / "analytics" / "reel"
    for f in ("daily.jsonl", "windows.jsonl", "runs.jsonl"):
        _w(a / f, '{"views": 1}\n')
    _w(a / "summary" / "2026-10-10.md", "# summary\n")
    _w(a / "studio.jsonl", '{"read": 1}\n')
    _w(a / "rights.jsonl", '{"r": 1}\n')
    note = "publish/reel/2026-10-10/clip.md"
    _w(root / note, f"# clip\n\nvideo: {VID}\n")
    _w(root / "publish" / "README.md", f"| clip | {VID} |\n| other | {VID_STUDIO} |\n")
    _w(root / "publish" / "uploads.json", {"uploads": [
        {"entry_id": "reel/b1/clip", "channel": "reel", "batch": "b1", "slug": "clip",
         "publish_day": "2026-10-10", "note": note, "source": "api", "video_id": VID,
         "url": f"https://youtu.be/{VID}", "privacy_status": "private",
         "uploaded_at": "2026-10-10T08:00:00Z"},
        {"entry_id": "reel/b1/other", "channel": "reel", "batch": "b1", "slug": "other",
         "publish_day": "2026-10-09", "source": "studio", "video_id": VID_STUDIO,
         "recorded_at": "2026-10-09T08:00:00Z"}]})
    return root


def files(*dirs):
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file() and ".git" not in p.relative_to(d).parts:
                out[str(p)] = p.read_bytes()
    return out


class NoNetwork:
    """Google's revoke, `urlopen`, the credentials and a socket's connect fail
    the test when reached."""

    def __enter__(self):
        _, pa, ad = _mods()
        self.saved = (ad.revoke_at_google, urllib.request.urlopen, pa.load_credentials,
                      socket.socket.connect)

        def boom(*a, **k):
            raise AssertionError("the network / the credentials were reached")
        ad.revoke_at_google = urllib.request.urlopen = pa.load_credentials = boom
        socket.socket.connect = boom
        return self

    def __exit__(self, *exc):
        _, pa, ad = _mods()
        (ad.revoke_at_google, urllib.request.urlopen, pa.load_credentials,
         socket.socket.connect) = self.saved


BODIES = []


def get(c, path, **params):
    r = c.get(path, params=params)
    BODIES.append(r.text)
    return r.status_code, r.json()


def post(c, path, body):
    r = c.post(path, headers=H, json=body)
    BODIES.append(r.text)
    return r.status_code, r.json()


def no_secret(*docs):
    text = "\n".join(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False)
                     for d in docs)
    for s in SECRETS:
        assert s not in text, f"a planted secret {s[:12]}... left the API"


def jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x]


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_routes():
    setup()
    spec = client(factory_tree()).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for p in GETS:
        want = {"get", "post"} if p == REVOKE else {"get"}       # the confirm shares the path
        assert set(spec["paths"][p]) == want, (p, spec["paths"].get(p))
        ref = spec["paths"][p]["get"]["responses"]["409"]["content"]["application/json"]
        assert ref["schema"]["$ref"].endswith("/OAuthProblem"), ref
    for p in (PLAN, CONFIRM, RPLAN, APLAN, AUTO):
        assert set(spec["paths"][p]) == {"post"}, (p, spec["paths"].get(p))
    ref = spec["paths"][PLAN]["post"]["responses"]["422"]["content"]["application/json"]
    assert ref["schema"]["$ref"].endswith("/OAuthProblem"), ref
    sc = spec["components"]["schemas"]
    assert {"kind", "code", "line", "expires_at", "hours_left", "scopes", "token_present",
            "client_secret_present", "state", "authorize_command"} <= set(sc["OAuthToken"]
                                                                          ["properties"])
    assert {"line", "revocation", "held", "due", "rules", "log"} <= set(
        sc["ApiDataState"]["properties"])
    assert {"action", "ok", "plan", "fingerprint", "confirm", "expires_in_s", "by", "via"} <= \
        set(sc["ApiDataPurgePlan"]["properties"])
    assert {"written", "record", "by", "via"} <= set(sc["ApiDataPurgeResult"]["properties"])
    assert {"action", "ok", "why", "result", "plan", "fingerprint", "confirm", "expires_in_s",
            "by", "via"} <= set(sc["OAuthRevokePlan"]["properties"])
    assert {"ok", "written", "why", "result", "plan", "by", "via"} <= set(
        sc["OAuthRevokeResult"]["properties"])
    assert {"dry_run", "ok", "exit", "by", "via", "google", "token", "state_file", "log",
            "reason", "channels", "items", "deletion"} == set(sc["OAuthRevokeOutcome"]
                                                             ["properties"])
    assert {"action", "ok", "due", "revocation", "fingerprint", "confirm", "by", "via"} <= set(
        sc["ApiDataAutoPlan"]["properties"])
    assert {"written", "done", "revocation", "by", "via"} <= set(
        sc["ApiDataAutoResult"]["properties"])
    assert sc["OAuthRevokePreview"]["properties"]["confirm_available"].get("const", True) is True


def test_the_module_never_revokes_nor_touches_credentials():
    tree = ast.parse((ROOT / "api" / "oauth.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & FORBIDDEN, names & FORBIDDEN
    calls = []
    for node in tree.body:
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and \
                    n.func.attr in ("revoke", "revoke_result", "auto", "apply"):
                kw = {k.arg: (k.value.value if isinstance(k.value, ast.Constant) else
                              getattr(k.value, "id", None)) for k in n.keywords}
                calls.append((n.func.attr, getattr(node, "name", None), kw))
    where = {}
    for attr, fn, _ in calls:
        where.setdefault(attr, set()).add(fn)
    assert where == {"revoke": {"revoke_preview"}, "revoke_result": {"_revoke_dry", "revoke"},
                     "auto": {"api_data", "_auto_plans", "auto_delete"},
                     "apply": {"purge"}}, where
    for attr, fn, kw in calls:
        if attr == "revoke":
            assert kw["yes"] is False, (fn, kw)
        if attr == "revoke_result":
            assert kw["yes"] is (fn == "revoke"), (fn, kw)
            assert (kw["by"], kw["via"]) == ("WRITE_BY", "VIA"), (fn, kw)
        if attr == "auto":
            assert kw["delete"] is (fn == "auto_delete"), (fn, kw)
            if fn == "auto_delete":
                assert (kw["by"], kw["via"]) == ("WRITE_BY", "VIA"), (fn, kw)
    assert (oauth.WRITE_BY, oauth.VIA) == ("user", "center")


# --------------------------------------------------------------------- the token
def test_the_token_state_term_scopes_never_its_value():
    s = setup()
    root = world()
    c = client(root)
    before = files(root, s)
    with NoNetwork():
        st, d = get(c, "/api/oauth/token")
    assert st == 200, d
    no_secret(d)
    assert (d["kind"], d["code"], d["oauth_mode"], d["token_mode"]) == \
        ("ok", 0, "testing", "testing"), d
    assert d["expires_at"] == "2026-10-16T12:00:00Z" and d["hours_left"] == 120.0, d
    assert d["line"].startswith("ok   oauth: токен YouTube действует ещё 120 ч"), d["line"]
    assert d["token_present"] and d["client_secret_present"] and d["state_present"], d
    _, pa, _ = _mods()
    assert d["scopes"]["required"] == list(pa.SCOPES) and d["scopes"]["missing"] == [], d
    assert sorted(d["scopes"]["granted"]) == sorted(pa.SCOPES), d
    assert d["scopes"]["short"][pa.ANALYTICS_SCOPE] == "yt-analytics.readonly", d
    assert d["state"]["authorized_at"] == AUTHORIZED and d["state"]["oauth_mode"] == "testing"
    assert d["authorize_command"] == pa.AUTHORIZE_COMMAND
    assert files(root, s) == before


def test_no_token_is_no_auth():
    s = setup(token=False, state=False)
    c = client(world())
    st, d = get(c, "/api/oauth/token")
    assert st == 200 and d["kind"] == "no-auth" and d["code"] == 3, d
    assert not d["token_present"] and d["state"] is None and d["expires_at"] is None, d
    assert d["client_secret_present"] is True, d
    no_secret(d)
    assert not (s / "token.json").exists()


def test_a_refused_token_is_expired_and_its_api_data_due():
    s = setup()
    root = world()
    _, pa, _ = _mods()
    pa.record_invalid_grant(cfg(), "2026-10-10T06:00:00Z")
    c = client(root)
    before = files(root, s)
    st, d = get(c, "/api/oauth/token")
    assert st == 200 and d["kind"] == "expired" and d["code"] == 3, d
    assert d["state"]["invalid_grant_at"] == "2026-10-10T06:00:00Z", d
    st, d = get(c, "/api/oauth/api-data")
    assert st == 200 and d["kind"] == "bad", d
    assert d["revocation"] == {"revoked_at": "2026-10-10T06:00:00Z",
                               "due_at": "2026-11-04T06:00:00Z",
                               "deadline": "2026-11-09T06:00:00Z", "deleted": None}, d
    assert d["due"] == [], d                       # the term is not past yet
    oauth.FACTORY_KW["now"] = "2026-11-05T00:00:00Z"
    st, d = get(c, "/api/oauth/api-data")
    (due,) = d["due"]
    assert due["reason"] == "revoked 2026-10-10T06:00:00Z" and not due["empty"], due
    assert "analytics/reel/daily.jsonl" in due["files"], due
    no_secret(d)
    assert files(root, s) == before                # nothing deleted by a GET


def test_a_configuration_that_does_not_read_is_409():
    setup()
    root = world()
    oauth.FACTORY_KW["environ"] = dict(oauth.FACTORY_KW["environ"],
                                       PUBLISHER_TOKEN_FILE=str(root / "token.json"))
    c = client(root)
    st, d = get(c, "/api/oauth/token")
    assert st == 409 and d["code"] == "config_broken" and set(d) == {"message", "code",
                                                                     "details"}, d
    assert d["message"].startswith("Конфигурация публикатора не читается"), d
    st, d = get(c, "/api/oauth/revoke")
    assert st == 409 and d["code"] == "config_broken", d
    st, d = get(c, "/api/oauth/api-data")          # the API Data is the root's either way
    assert st == 200 and d["config_error"] and d["revocation"] is None, d
    assert d["held"]["rows"], d


# --------------------------------------------------------------------- the API Data
def test_the_api_data_held_kept_files_not_in_it():
    s = setup()
    root = world()
    c = client(root)
    before = files(root, s)
    st, d = get(c, "/api/oauth/api-data")
    assert st == 200, d
    assert d["kind"] == "ok" and d["line"].startswith("API Data: отзыва доступа нет; журнал - 1"), d
    assert d["rules"] == {"retention_days": 30, "purge_after_days": 25, "refresh_days": 7,
                          "stale_days": 28}, d
    h = d["held"]
    assert h["channels"] == ["reel"] and h["empty"] is False, h
    assert sorted(h["files"]) == ["analytics/reel/daily.jsonl", "analytics/reel/runs.jsonl",
                                  "analytics/reel/windows.jsonl"], h
    assert h["dirs"] == ["analytics/reel/summary"], h
    assert [r["video_id"] for r in h["rows"]] == [VID] and h["rows"][0]["slug"] == "clip", h
    assert sorted(t["file"] for t in h["texts"]) == ["publish/README.md",
                                                     "publish/reel/2026-10-10/clip.md"], h
    assert not any("studio.jsonl" in x or "rights.jsonl" in x for x in h["files"] + h["lines"])
    assert VID_STUDIO not in json.dumps(h), h
    assert d["due"] == [] and d["revocation"] is None and d["log"] == \
        "publish/api-data-deletions.jsonl", d
    no_secret(d)
    assert files(root, s) == before


# --------------------------------------------------------------------- the revoke's dry run
def test_the_revoke_preview_is_the_dry_run_nothing_reaches_google():
    s = setup()
    root = world()
    c = client(root)
    before = files(root, s)
    with NoNetwork():
        st, d = get(c, "/api/oauth/revoke")
    assert st == 200, d
    no_secret(d)
    assert d["dry_run"] is True and d["confirm_available"] is True and d["token_present"], d
    res = d["result"]
    assert (res["dry_run"], res["ok"], res["by"], res["via"]) == (True, True, "user", "center")
    assert res["google"]["answer"] is None and res["token"]["kind"] == "refresh token", res
    assert res["token"]["existed"] and not res["token"]["deleted"] and res["deletion"] is None
    assert res["items"] == d["plan"]["lines"] and res["log"] == \
        "publish/api-data-deletions.jsonl", res
    assert d["lines"][0] == "revoke - dry run (add --yes):", d["lines"]
    assert any(ln.strip().startswith("google  POST https://oauth2.googleapis.com/revoke "
                                     "(refresh token of") for ln in d["lines"]), d["lines"]
    assert any(ln.strip().startswith("token ") and ln.endswith("-> deleted")
               for ln in d["lines"]), d["lines"]
    assert d["plan"]["reason"] == "revoked from the client" and d["plan"]["rows"], d
    assert d["google_page"].startswith("https://myaccount.google.com/"), d
    assert files(root, s) == before
    assert (s / "token.json").is_file()


def test_the_revoke_preview_without_a_token():
    setup(token=False, state=False)
    c = client(world())
    with NoNetwork():
        st, d = get(c, "/api/oauth/revoke")
    assert st == 200 and d["token_present"] is False, d
    assert any("nothing to revoke: no token file" in ln for ln in d["lines"]), d["lines"]


# --------------------------------------------------------------------- the purge
def test_the_purge_plan_deletes_nothing_the_confirm_deletes_by_user_via_center():
    s = setup()
    root = world()
    c = client(root)
    before = files(root, s)
    with NoNetwork():
        st, plan = post(c, PLAN, {"scope": "all"})
    assert st == 200, plan
    assert files(root, s) == before
    assert plan["action"] == "api_data_purge" and plan["ok"] is True and plan["why"] is None
    assert plan["confirm"] and plan["expires_in_s"] == 120 and len(plan["fingerprint"]) == 64
    assert (plan["scope"], plan["asked"], plan["by"], plan["via"]) == \
        ("all", None, "user", "center"), plan
    assert plan["plan"]["reason"] == "owner's request (III.E.4.g)", plan
    assert len(plan["plan"]["lines"]) == 7, plan["plan"]["lines"]     # 3 files, 1 dir, 1 row, 2 texts
    with NoNetwork():
        st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert got["written"] is True and (got["by"], got["via"]) == ("user", "center"), got
    a = root / "analytics" / "reel"
    assert not any((a / f).exists() for f in ("daily.jsonl", "windows.jsonl", "runs.jsonl"))
    assert not (a / "summary").exists()
    assert (a / "studio.jsonl").is_file() and (a / "rights.jsonl").is_file()
    j = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    assert [r["video_id"] for r in j["uploads"]] == [VID_STUDIO], j
    (gone,) = j["api_data_deleted"]
    assert gone["entry_id"] == "reel/b1/clip" and "video_id" not in gone, gone
    assert gone["api_data_deleted_reason"] == "owner's request (III.E.4.g)", gone
    assert VID not in (root / "publish" / "README.md").read_text(encoding="utf-8")
    assert VID_STUDIO in (root / "publish" / "README.md").read_text(encoding="utf-8")
    (rec,) = jsonl(root / "publish" / "api-data-deletions.jsonl")
    assert (rec["by"], rec["via"], rec["reason"], rec["entries"], rec["at"]) == \
        ("user", "center", "owner's request (III.E.4.g)", ["reel/b1/clip"], NOW), rec
    assert got["record"] == rec and got["log"] == "publish/api-data-deletions.jsonl", got
    assert (s / "token.json").is_file()            # the purge keeps the token
    no_secret(plan, got)
    # the token is spent; a plan now has nothing to delete - no token
    st, again = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 409 and again["code"] == "confirm_unknown", again
    st, plan = post(c, PLAN, {"scope": "all"})
    assert st == 200 and plan["ok"] is False and plan["confirm"] is None, plan
    assert plan["why"].startswith("Удалять нечего"), plan


def test_the_purge_of_a_channel_and_its_refusals():
    setup()
    root = world()
    _w(root / "analytics" / "demo" / "daily.jsonl", '{"views": 2}\n')
    c = client(root)
    before = files(root)
    st, d = post(c, PLAN, {"scope": "channels", "channels": ["nope"]})
    assert st == 404 and d["code"] == "unknown_channel", d
    st, d = post(c, PLAN, {"scope": "channels", "channels": []})
    assert st == 422 and d["code"] == "no_channels", d
    st, d = post(c, PLAN, {"scope": "everything"})
    assert st == 422, d
    st, plan = post(c, PLAN, {"scope": "channels", "channels": ["demo", "demo"]})
    assert st == 200 and plan["ok"] and plan["asked"] == ["demo"], plan
    assert plan["plan"]["files"] == ["analytics/demo/daily.jsonl"] and not plan["plan"]["rows"]
    assert files(root) == before
    st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert not (root / "analytics" / "demo" / "daily.jsonl").exists()
    assert (root / "analytics" / "reel" / "daily.jsonl").is_file()   # reel untouched
    assert len(json.loads((root / "publish" / "uploads.json").read_text())["uploads"]) == 2


def test_a_plan_that_changed_or_emptied_deletes_nothing():
    setup()
    root = world()
    c = client(root)
    st, plan = post(c, PLAN, {"scope": "channels", "channels": ["reel"]})
    _w(root / "analytics" / "reel" / "summary" / "2026-10-11.md", "# one more\n")
    before = files(root)
    st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "check_changed", got
    assert "ничего не удалено" in got["message"], got
    assert files(root) == before
    assert not (root / "publish" / "api-data-deletions.jsonl").exists()
    # emptied meanwhile (the CLI's own purge)
    st, plan = post(c, PLAN, {"scope": "all"})
    _, _, ad = _mods()
    ad.apply(ad.plan(root, reason="test"), NOW)
    before = files(root)
    st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "refused", got
    assert files(root) == before


def test_a_token_spent_expired_or_foreign_is_refused():
    setup()
    root = world()
    c = client(root)
    before = files(root)
    st, plan = post(c, PLAN, {"scope": "all"})
    clock = batches._clock
    try:
        batches._clock = lambda: clock() + batches.CONFIRM_TTL + 1
        st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    finally:
        batches._clock = clock
    assert st == 409 and got["code"] == "confirm_expired", got
    st, got = post(c, CONFIRM, {"confirm": "nope"})
    assert st == 409 and got["code"] == "confirm_unknown", got
    foreign = batches._issue(root, "launch", "reel", "0" * 64)
    st, got = post(c, CONFIRM, {"confirm": foreign})
    assert st == 409 and got["code"] == "confirm_mismatch", got
    assert "API Data не удалены" in got["message"], got
    st, got = post(c, CONFIRM, {})
    assert st == 422, got
    assert files(root) == before


# --------------------------------------------------------------------- the revocation (CC-0082)
class Google(NoNetwork):
    """NoNetwork, and Google's revoke a stand-in answering `answer` - it
    records the values handed to it; `urlopen` and a socket still fail."""

    def __init__(self, answer="revoked", detail="HTTP 200"):
        self.answer, self.detail, self.got = answer, detail, []

    def __enter__(self):
        super().__enter__()
        _, _, ad = _mods()

        def fake(token, timeout=None):
            self.got.append(token)
            return {"answer": self.answer, "detail": self.detail}
        ad.revoke_at_google = fake
        return self


def state(s):
    return json.loads((s / "token.state.json").read_text(encoding="utf-8"))


def test_the_revoke_plan_changes_nothing_the_confirm_revokes_by_user_via_center():
    s = setup()
    root = world()
    c = client(root)
    before = files(root, s)
    with NoNetwork():
        st, plan = post(c, RPLAN, {})
    assert st == 200, plan
    assert files(root, s) == before
    assert (plan["action"], plan["ok"], plan["why"], plan["by"], plan["via"]) == \
        ("oauth_revoke", True, None, "user", "center"), plan
    assert plan["confirm"] and plan["expires_in_s"] == 120 and len(plan["fingerprint"]) == 64
    assert plan["result"]["dry_run"] is True and plan["result"]["google"]["answer"] is None
    assert plan["plan"]["reason"] == "revoked from the client" and plan["plan"]["rows"], plan
    with Google() as g:
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert g.got == [REFRESH], "the refresh token goes to Google, once"
    assert (got["ok"], got["written"], got["why"], got["by"], got["via"]) == \
        (True, True, None, "user", "center"), got
    res = got["result"]
    assert (res["dry_run"], res["ok"], res["exit"], res["by"], res["via"]) == \
        (False, True, 0, "user", "center"), res
    assert res["google"] == {"answer": "revoked", "detail": "HTTP 200",
                             "url": "https://oauth2.googleapis.com/revoke"}, res
    assert res["token"]["deleted"] is True and res["token"]["kind"] == "refresh token", res
    assert not (s / "token.json").exists()
    a = root / "analytics" / "reel"
    assert not (a / "daily.jsonl").exists() and (a / "studio.jsonl").is_file()
    (rec,) = jsonl(root / "publish" / "api-data-deletions.jsonl")
    assert (rec["by"], rec["via"], rec["google"], rec["reason"], rec["at"]) == \
        ("user", "center", "revoked", "revoked from the client", NOW), rec
    assert res["deletion"] == rec and got["log"] == "publish/api-data-deletions.jsonl", got
    j = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    (gone,) = j["api_data_deleted"]
    assert (gone["api_data_deleted_by"], gone["api_data_deleted_via"]) == ("user", "center")
    st_ = state(s)
    assert (st_["revoked_from_client_at"], st_["revoked_from_client_google"],
            st_["revoked_from_client_by"], st_["revoked_from_client_via"]) == \
        (NOW, "revoked", "user", "center"), st_
    assert (st_["api_data_deleted"]["by"], st_["api_data_deleted"]["via"]) == ("user", "center")
    no_secret(plan, got)
    # CC-0098: the plan's and the revocation's answers through the one cutter - no absolute
    # path (the root, the token file outside it), Google's URL whole
    for doc in (plan, got):
        text = json.dumps(doc, ensure_ascii=False)
        for bad in (str(root), str(root.resolve()), str(s), str(s.resolve())):
            assert bad not in text, (bad, text[:400])
    assert plan["result"]["token"]["file"] == ".../token.json", plan["result"]["token"]
    # spent; the token's state shows who revoked
    st, again = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 409 and again["code"] == "confirm_unknown", again
    st, tok = get(c, "/api/oauth/token")
    assert tok["state"]["revoked_from_client_by"] == "user", tok
    assert tok["state"]["revoked_from_client_via"] == "center", tok
    # nothing left: no token file, no API Data
    with NoNetwork():
        st, plan = post(c, RPLAN, {})
    assert st == 200 and plan["ok"] is False and plan["confirm"] is None, plan
    assert plan["why"].startswith("Отзывать нечего"), plan


def test_google_not_answering_changes_nothing():
    s = setup()
    root = world()
    c = client(root)
    st, plan = post(c, RPLAN, {})
    before = files(root, s)
    with Google("unreachable", "URLError: timed out") as g:
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert g.got == [REFRESH]
    assert (got["ok"], got["written"]) == (False, False), got
    assert got["why"].startswith("Google не ответил на отзыв (URLError: timed out)"), got
    assert "токен сохранён" in got["why"] and got["google_page"] in got["why"], got
    _, _, ad = _mods()
    assert got["result"]["exit"] == ad.EXIT_ERROR and got["result"]["deletion"] is None, got
    assert got["result"]["token"]["deleted"] is False, got
    assert files(root, s) == before
    no_secret(got)


def test_an_invalid_token_or_none_goes_on():
    s = setup()
    root = world()
    c = client(root)
    st, plan = post(c, RPLAN, {})
    with Google("invalid_token", "HTTP 400 invalid_grant"):
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 200 and got["written"] is True, got
    assert got["result"]["google"]["answer"] == "invalid_token", got
    assert not (s / "token.json").exists()
    assert state(s)["revoked_from_client_google"] == "invalid_token"
    # no token file, the API Data there: Google is not asked, the data goes
    s = setup(token=False)
    root = world()
    c = client(root)
    with NoNetwork():
        st, plan = post(c, RPLAN, {})
        assert st == 200 and plan["ok"] is True, plan
        assert plan["result"]["token"]["missing"] == "no token file", plan
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 200 and got["written"] is True, got
    assert got["result"]["google"]["answer"] == "no token", got
    assert not (root / "analytics" / "reel" / "daily.jsonl").exists()
    (rec,) = jsonl(root / "publish" / "api-data-deletions.jsonl")
    assert (rec["google"], rec["by"], rec["via"]) == ("no token", "user", "center"), rec


def test_a_revoke_plan_that_changed_or_emptied_revokes_nothing():
    s = setup()
    root = world()
    c = client(root)
    st, plan = post(c, RPLAN, {})
    _w(root / "analytics" / "reel" / "summary" / "2026-10-11.md", "# one more\n")
    before = files(root, s)
    with NoNetwork():
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "check_changed", got
    assert "ничего не отозвано" in got["message"], got
    assert files(root, s) == before
    # emptied meanwhile: the token file gone, the API Data purged
    st, plan = post(c, RPLAN, {})
    (s / "token.json").unlink()
    _, _, ad = _mods()
    ad.apply(ad.plan(root, reason="test"), NOW)
    before = files(root, s)
    with NoNetwork():
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "refused", got
    assert files(root, s) == before
    # a purge's token is not a revocation's
    _w(root / "analytics" / "reel" / "daily.jsonl", '{"views": 3}\n')
    st, purge = post(c, PLAN, {"scope": "all"})
    with NoNetwork():
        st, got = post(c, REVOKE, {"confirm": purge["confirm"]})
    assert st == 409 and got["code"] == "confirm_mismatch", got
    assert "токен не отозван" in got["message"], got
    st, got = post(c, REVOKE, {})
    assert st == 422, got


def test_a_revoke_with_a_configuration_that_does_not_read_is_409():
    setup()
    root = world()
    oauth.FACTORY_KW["environ"] = dict(oauth.FACTORY_KW["environ"],
                                       PUBLISHER_TOKEN_FILE=str(root / "token.json"))
    c = client(root)
    for path in (RPLAN, APLAN):
        st, d = post(c, path, {})
        assert st == 409 and d["code"] == "config_broken", (path, d)


# --------------------------------------------------------------------- the deletion by term (CC-0082)
def test_nothing_due_before_the_term_past_it_deleted_by_user_via_center():
    s = setup()
    root = world()
    _, pa, _ = _mods()
    pa.record_invalid_grant(cfg(), "2026-10-10T06:00:00Z")
    c = client(root)
    before = files(root, s)
    with NoNetwork():
        st, plan = post(c, APLAN, {})
    assert st == 200, plan
    assert (plan["action"], plan["ok"], plan["due"], plan["confirm"]) == \
        ("api_data_auto", False, [], None), plan
    assert plan["why"].startswith("Удалять по сроку нечего"), plan
    assert plan["revocation"]["due_at"] == "2026-11-04T06:00:00Z", plan
    oauth.FACTORY_KW["now"] = "2026-11-05T00:00:00Z"
    with NoNetwork():
        st, plan = post(c, APLAN, {})
    assert st == 200 and plan["ok"] is True and plan["confirm"], plan
    assert (plan["by"], plan["via"], plan["expires_in_s"]) == ("user", "center", 120), plan
    (due,) = plan["due"]
    assert due["reason"] == "revoked 2026-10-10T06:00:00Z", due
    assert files(root, s) == before
    with NoNetwork():
        st, got = post(c, AUTO, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert (got["written"], got["by"], got["via"]) == (True, "user", "center"), got
    (done,) = got["done"]
    assert done["plan"]["reason"] == due["reason"], done
    (rec,) = jsonl(root / "publish" / "api-data-deletions.jsonl")
    assert (rec["by"], rec["via"], rec["reason"], rec["at"]) == \
        ("user", "center", due["reason"], "2026-11-05T00:00:00Z"), rec
    assert done["record"] == rec, done
    assert not (root / "analytics" / "reel" / "daily.jsonl").exists()
    j = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    (gone,) = j["api_data_deleted"]
    assert (gone["api_data_deleted_by"], gone["api_data_deleted_via"]) == ("user", "center")
    deleted = state(s)["api_data_deleted"]
    assert (deleted["by"], deleted["via"], deleted["reason"]) == \
        ("user", "center", due["reason"]), deleted
    assert got["revocation"]["deleted"]["by"] == "user", got
    assert (s / "token.json").is_file()            # the deletion by term keeps the token
    no_secret(plan, got)
    st, again = post(c, AUTO, {"confirm": plan["confirm"]})
    assert st == 409 and again["code"] == "confirm_unknown", again
    st, plan = post(c, APLAN, {})
    assert st == 200 and plan["ok"] is False, plan


def test_a_stale_row_and_a_plan_that_changed():
    setup()
    root = world()
    j = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    j["uploads"][0]["uploaded_at"] = "2026-09-01T08:00:00Z"   # 40 days without a refresh
    _w(root / "publish" / "uploads.json", j)
    c = client(root)
    st, plan = post(c, APLAN, {})
    assert st == 200 and plan["ok"] is True, plan
    (due,) = plan["due"]
    assert due["reason"] == "not refreshed for 28+ days" and \
        [r["video_id"] for r in due["rows"]] == [VID], due
    assert due["files"] == [], due                 # a stale row: only its API fields
    # changed meanwhile: the row refreshed
    j["uploads"][0]["api_refreshed_at"] = "2026-10-10T08:00:00Z"
    _w(root / "publish" / "uploads.json", j)
    before = files(root)
    st, got = post(c, AUTO, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "refused", got
    assert files(root) == before
    # changed, not emptied: another row went stale
    j["uploads"][0]["api_refreshed_at"] = "2026-09-01T08:00:00Z"
    _w(root / "publish" / "uploads.json", j)
    st, plan = post(c, APLAN, {})
    j["uploads"].append(dict(j["uploads"][0], entry_id="reel/b1/third", slug="third",
                             video_id="apiVideo003"))
    _w(root / "publish" / "uploads.json", j)
    before = files(root)
    st, got = post(c, AUTO, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "check_changed", got
    assert files(root) == before
    st, plan = post(c, APLAN, {})
    st, got = post(c, AUTO, {"confirm": plan["confirm"]})
    assert st == 200 and len(got["done"]) == 1, got
    j = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    assert [r["video_id"] for r in j["uploads"]] == [VID_STUDIO], j
    assert {(g["api_data_deleted_by"], g["api_data_deleted_via"])
            for g in j["api_data_deleted"]} == {("user", "center")}, j


# --------------------------------------------------------------------- the commit (CC-0156)
DELETED = ["analytics/reel/daily.jsonl", "analytics/reel/runs.jsonl",
           "analytics/reel/summary/2026-10-10.md", "analytics/reel/windows.jsonl"]
CHANGED = ["publish/README.md", "publish/api-data-deletions.jsonl",
           "publish/reel/2026-10-10/clip.md", "publish/uploads.json"]


def _committed_world():
    """The world committed - a clean tree; a stray edit of a kept file (a
    batch's) that the deletion must leave out."""
    root = world()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the world")
    _w(root / "analytics" / "reel" / "studio.jsonl", '{"read": 2}\n')
    return root


def _shown(root, ref="HEAD"):
    return sorted(git(root, "show", "--name-only", "--format=", ref).splitlines())


def _clean_but_the_stray(root):
    assert git(root, "status", "--porcelain", "--untracked-files=all") == \
        "M analytics/reel/studio.jsonl"


def test_the_purge_is_committed_and_the_tree_stays_clean():
    """CC-0156: the purge left the journal, README, the note, the deletion log
    (untracked) and the deleted analytics files uncommitted. Now one commit
    of exactly those, the deletions staged, `Cc-Action: api_data_purge`."""
    s = setup()
    root = _committed_world()
    h = git(root, "rev-parse", "HEAD")
    c = client(root)
    with NoNetwork():
        st, plan = post(c, PLAN, {"scope": "all"})
        st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert _shown(root) == sorted(DELETED + CHANGED), _shown(root)
    gone = git(root, "show", "--diff-filter=D", "--name-only", "--format=", "HEAD")
    assert sorted(gone.splitlines()) == DELETED, gone
    _clean_but_the_stray(root)
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith("API Data: удалены по запросу владельца - reel (user, center)"), msg
    assert "Cc-Action: api_data_purge" in msg and "Cc-Channel" not in msg, msg
    assert VID not in msg, "a deleted video id never goes into the commit message"
    assert (s / "token.json").is_file()


def test_the_revocation_is_committed_and_the_tree_stays_clean():
    s = setup()
    root = _committed_world()
    h = git(root, "rev-parse", "HEAD")
    c = client(root)
    with NoNetwork():
        st, plan = post(c, RPLAN, {})
    with Google():
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 200 and got["ok"] is True, got
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert _shown(root) == sorted(DELETED + CHANGED), _shown(root)
    _clean_but_the_stray(root)
    msg = git(root, "log", "-1", "--format=%B")
    assert "Cc-Action: oauth_revoke" in msg and "Google: revoked" in msg and VID not in msg, msg
    assert not (s / "token.json").exists()


def test_google_not_answering_commits_nothing():
    setup()
    root = _committed_world()
    h = git(root, "rev-parse", "HEAD")
    c = client(root)
    with NoNetwork():
        st, plan = post(c, RPLAN, {})
    with Google(answer="unreachable", detail="timed out"):
        st, got = post(c, REVOKE, {"confirm": plan["confirm"]})
    assert st == 200 and got["ok"] is False, got
    assert git(root, "rev-parse", "HEAD") == h
    _clean_but_the_stray(root)


def test_the_deletion_by_term_is_committed_and_the_tree_stays_clean():
    setup()
    root = _committed_world()
    _, pa, _ = _mods()
    pa.record_invalid_grant(cfg(), "2026-10-10T06:00:00Z")
    oauth.FACTORY_KW["now"] = "2026-11-05T00:00:00Z"
    h = git(root, "rev-parse", "HEAD")
    c = client(root)
    with NoNetwork():
        st, plan = post(c, APLAN, {})
        assert plan["confirm"], plan
        st, got = post(c, AUTO, {"confirm": plan["confirm"]})
    assert st == 200, got
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert "analytics/reel/daily.jsonl" in _shown(root), _shown(root)
    assert "publish/api-data-deletions.jsonl" in _shown(root), _shown(root)
    _clean_but_the_stray(root)
    assert "Cc-Action: api_data_auto" in git(root, "log", "-1", "--format=%B")


def test_a_purge_git_refuses_is_refused_and_nothing_stays_staged():
    setup()
    root = _committed_world()
    h = git(root, "rev-parse", "HEAD")
    hooks = TMP / f"refusing-hooks-oauth-{root.name}"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))
    c = client(root)
    with NoNetwork():
        st, plan = post(c, PLAN, {"scope": "all"})
        st, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert st == 409 and got["code"] == "refused", got
    assert "commit_refused" in got["details"], got["details"]
    assert git(root, "rev-parse", "HEAD") == h, "no commit"
    assert git(root, "diff", "--cached", "--name-only") == "", "nothing left staged"
    assert not (root / "analytics" / "reel" / "daily.jsonl").exists(), "the deletion stays"


def test_no_planted_secret_in_any_response():
    """Every body this file's tests got (run in order, this one last)."""
    setup()
    c = client(world())
    with NoNetwork():
        for p in sorted(GETS):
            get(c, p)
        post(c, PLAN, {"scope": "all"})
        post(c, RPLAN, {})
        post(c, APLAN, {})
    no_secret(*BODIES)


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    oauth.FACTORY_KW.clear()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

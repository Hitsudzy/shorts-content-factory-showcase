"""CC-0028: the publisher's OAuth token and the API Data the factory keeps -
the token's state (never its value), its term and scopes, the API Data held,
what the auto-run would delete, the deletion on the owner's request, and what
a revocation from the client would do. Only through the factory's own
functions (`shared/factory_state.py`'s copies of the publisher's modules,
as `api/publish.py` takes them), nothing of the API's own on top:

    agents/publisher/publisher_config.py  load (the paths of the secrets, never
                                          the secrets)
    agents/publisher/publisher_auth.py    status (one line and its kind - reads
                                          the token's file, never the network),
                                          read_state (when given, the term, the
                                          scopes, the revocation marks - no
                                          token value in it), granted_scopes,
                                          SCOPES, AUTHORIZE_COMMAND
    agents/publisher/api_data.py          status, revocation, plan, describe,
                                          is_empty, auto(delete=False) - what
                                          `api_data.py status / purge / auto`
                                          print; apply(extra) - the confirmed
                                          purge; revoke(yes=False) - the dry
                                          run of `api_data.py revoke`;
                                          revoke_result (CC-0082: its dry run,
                                          and yes=True by user via center - the
                                          confirmed revocation); auto(delete=
                                          True, by user, via center) - the
                                          confirmed deletion by term

**Never called**: `revoke_at_google`, `token_value`, `load_credentials`,
`notify`, the state's writers - the revocation and the deletion by term go
through the factory's own `revoke_result` / `auto`, which do them.
`tests/test_cc_api_oauth.py` walks this file's names.

**The revocation** (CC-0082, `revoke_plan`, `revoke`): `revoke_result(yes=False,
by user, via center)` - the factory's dry run as data (what it would revoke at
Google, delete and mark) and the plan of every channel's API Data, a confirm
token (action `oauth_revoke`, 120 s, single use) when there is a token file or
API Data; the confirm spends it, runs the dry run again and compares
(`check_changed`), then `revoke_result(yes=True, by user, via center)` under
the publication write lock - its structured result is the answer (Google's
answer, whether the token was deleted, the deletion record). Google not
answering is `ok: false, written: false`: nothing changed, the token is kept.

**The deletion by term** (CC-0082, `auto_plan`, `auto_delete`):
`auto(delete=False)` - what rules 1-2 would delete now (the revocation's term
past, the stale rows), a confirm token (action `api_data_auto`); the confirm
plans again and compares, then `auto(delete=True, by user, via center)`.

**No secret leaves**: the token's value, its refresh token, the client
secret and the raw content of either file are never read here - the state
file's fields are taken by name (`STATE_FIELDS`), the token's presence is
`is_file()`.

**The purge** (`purge_plan`, `purge`): `plan(root, channels, reason)` - every
channel (`all`) or the ones named - and `describe(p)`: the files, the
directories, the journal rows and the texts the deletion would touch, a
confirm token (`batches` store, action `api_data_purge`, 120 s, single use)
bound to the channels when there is something to delete. The confirm spends
the token, plans again and compares (`check_changed`, nothing deleted), then
`apply(p, now, extra={"by": "user", "via": "center"})` - the deletion log
`publish/api-data-deletions.jsonl` carries who and where. One publication
write at a time (`publish._WRITE`: the journal `publish/uploads.json` is the
publication's).

**The API-upload switch** is `api/publish.py` / `api/publish_net.py`'s
(CC-0064/CC-0066): `GET /publish/api-upload`, `POST
/publish/{channel}/api-upload/switch/plan` and `…/switch`.

**The commit** (CC-0156, the factory's decision of 22.10): the purge, the
deletion by term and the revocation end in one commit of what they changed of
the plan's own paths - the journal `publish/uploads.json`, the texts scrubbed
(`publish/README.md`, the notes), the analytics files and folders deleted
(`analytics/<c>/daily.jsonl`, `runs.jsonl` ... - the deletion staged) and the
deletion log `publish/api-data-deletions.jsonl` (untracked until then -
committed, not ignored); `Cc-Action: api_data_purge | api_data_auto |
oauth_revoke`, no `Cc-Channel` (the API Data is the factory's)
(`api/root_commit.py`: git's word on those paths before the write and after,
only what moved - a batch writes `analytics/` too). The token, its state and
anything else outside those paths are never in it. git's refusal is 409
`refused` (`commit_refused`), the deletion stays in the tree, nothing staged;
a root that is not a git work tree commits nothing.

Every refusal is a `BatchFault` (`{message, code, details}`). `FACTORY_KW`
holds the factory's injection points (`now`, `env_file`, `environ`) - empty
in production; the tests put a clock and a stand-in `.env` there.
"""
import io
from pathlib import Path

from . import batches, factory, paths, publish, root_commit
from .batches import BatchFault, _channel, _digest, _issue, _spend

ACTION = "api_data_purge"
#: CC-0082: the revocation from the client and the deletion by term.
REVOKE, AUTO = "oauth_revoke", "api_data_auto"
#: The token's key: the API Data is the factory's, not one channel's.
KEY = "api-data"
#: The revocation's key: the publisher's one token.
TOKEN_KEY = "oauth-token"
ACTIONS = {ACTION: ("план удаления API Data", "API Data не удалены", "удаления API Data"),
           REVOKE: ("план отзыва токена", "токен не отозван", "отзыва токена"),
           AUTO: ("план удаления API Data по сроку", "API Data не удалены",
                  "удаления API Data по сроку")}
batches.register_actions(ACTIONS)
#: Who and where the center writes into the deletion log (`apply(extra)`).
WRITE_BY, VIA = "user", "center"
#: The reason `api_data.py purge` writes (its `main`).
PURGE_REASON = "owner's request (III.E.4.g)"
#: The token state's fields the center shows - taken by name, nothing else.
STATE_FIELDS = ("authorized_at", "expires_at", "oauth_mode", "lifetime_days", "scopes",
                "invalid_grant_at", "revoked_from_client_at", "revoked_from_client_google",
                "revoked_from_client_by", "revoked_from_client_via", "api_data_deleted")
#: The factory's own injection points - empty in production.
FACTORY_KW = {}


def _mods():
    """(publisher_config, publisher_auth, api_data) - collect's copies; the
    journal goes in first, so `api_data`'s plain `import upload_records`
    finds that one."""
    c = factory.collect()
    c.journal()
    return c.pubcfg(), c.auth(), c.api_data()


def _now(pa):
    return pa._now(FACTORY_KW.get("now"))


def _iso(pa, dt):
    return pa._iso(dt) if dt is not None else None


def _rel(root, p):
    """CC-0097: relative to the root, `.../<its last part>` outside it - never
    the absolute path (`api/paths.py`)."""
    return paths.rel(root, p)


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой: {what}.",
                      [f"{type(e).__name__}: {e}"])


def _cfg(pc):
    """The publisher's configuration - or 409 `config_broken` with its line."""
    try:
        return pc.load(FACTORY_KW.get("env_file"), FACTORY_KW.get("environ"))
    except pc.ConfigError as e:
        raise BatchFault(409, "config_broken", f"Конфигурация публикатора не читается: {e}",
                         [f"ConfigError: {e}"]) from e


# ---------------------------------------------------------------- the token
def token(root):
    """`publisher_auth.py status` (without --needs-you: nothing is told) and
    the state beside the token - never a token value."""
    pc, pa, _ = _mods()
    cfg = _cfg(pc)
    now = _now(pa)
    try:
        st = pa.status(cfg, now)
        state = pa.read_state(cfg)
        granted = pa.granted_scopes(cfg)
    except (ValueError, OSError) as e:
        raise _broken(e, "состояние токена не прочитано") from e
    return {
        "kind": st.kind, "code": st.code, "line": st.line, "now": _iso(pa, now),
        "expires_at": _iso(pa, st.expires_at),
        "hours_left": round(st.hours_left, 1) if st.hours_left is not None else None,
        "oauth_mode": cfg.oauth_mode, "token_mode": st.mode,
        "lifetime_days": cfg.token_lifetime_days, "remind_hours": cfg.token_remind_hours,
        "scopes": {"required": list(pa.SCOPES), "granted": granted,
                   "missing": list(st.missing),
                   "short": {s: pa.short(s) for s in pa.SCOPES}},
        "token_present": Path(cfg.token_file).is_file(),
        "client_secret_present": Path(cfg.client_secret_file).is_file(),
        "state_present": state is not None,
        "state": {k: state.get(k) for k in STATE_FIELDS if k in state} if state else None,
        "authorize_command": pa.AUTHORIZE_COMMAND,
    }


# ---------------------------------------------------------------- the API Data
def _plan_doc(ad, p):
    """A plan of `api_data` as data: what it names, `describe`'s lines."""
    root = p["root"]
    return {"reason": p["reason"], "channels": list(p["channels"]),
            "empty": bool(ad.is_empty(p)),
            "files": [_rel(root, f) for f in p["files"]],
            "dirs": [_rel(root, d) for d in p["dirs"]],
            "rows": [{k: r.get(k) for k in ("entry_id", "channel", "slug", "batch",
                                            "publish_day", "video_id")} for r in p["rows"]],
            "texts": [{"file": _rel(root, t), "video_id": v} for t, v in p["scrub"]],
            "journal": _rel(root, p["journal"]), "lines": ad.describe(p)}


def _scope(root, ad, plans):
    """CC-0156: what the plans' deletion may change in git's eyes, from the
    root - their files and folders, the texts scrubbed, the journal, the log."""
    out = []
    for p in plans:
        out += [*p["files"], *p["dirs"], *(t for t, _ in p["scrub"]), p["journal"]]
    out.append(Path(root) / "publish" / ad.LOG)
    return sorted(set(root_commit.rels(root, out)))


def _counts(docs):
    """How much a deletion touched - counts only: the video ids it deletes are
    API Data and never go into a commit message."""
    n = {k: sum(len(d[k]) for d in docs) for k in ("files", "dirs", "rows", "texts")}
    return (f"Файлов {n['files']}, папок {n['dirs']}, строк журнала {n['rows']}, "
            f"текстов {n['texts']}.")


def _committed(root, action, scope, before, subject, body, done):
    return root_commit.commit_changed(root, None, action, scope, before,
                                      lambda: (subject, body), done)


def _revocation(pa, ad, cfg, now):
    rev = ad.revocation(cfg, now) if cfg is not None else None
    if not rev:
        return None
    return {"revoked_at": _iso(pa, rev["revoked_at"]), "due_at": _iso(pa, rev["due_at"]),
            "deadline": _iso(pa, rev["deadline"]), "deleted": rev["deleted"]}


def api_data(root):
    """`api_data.py status` (its line), the revocation mark, the API Data held
    (`plan` of every channel - what `purge --all` would delete) and what the
    auto-run would delete now (`auto(delete=False)`). Nothing deleted. A
    configuration that does not read is said (`config_error`): the API Data
    is the root's either way, as `purge` reads it without one."""
    pc, pa, ad = _mods()
    now = _now(pa)
    try:
        cfg, config_error = _cfg(pc), None
    except BatchFault as e:
        cfg, config_error = None, e.message
    root = Path(root)
    try:
        st = ad.status(cfg, root, now)
        held = ad.plan(root, reason=PURGE_REASON)
        due = ad.auto(cfg, root, now, delete=False)
        rev = _revocation(pa, ad, cfg, now)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "API Data не прочитаны") from e
    return {"kind": st["kind"], "line": st["line"], "now": _iso(pa, now),
            "config_error": config_error, "revocation": rev,
            "rules": {"retention_days": ad.RETENTION_DAYS,
                      "purge_after_days": ad.PURGE_AFTER_DAYS,
                      "refresh_days": ad.REFRESH_DAYS, "stale_days": ad.STALE_DAYS},
            "held": _plan_doc(ad, held), "due": [_plan_doc(ad, p) for p, _ in due],
            "log": _rel(root, root / "publish" / ad.LOG)}


def revoke_preview(root):
    """`api_data.py revoke` without --yes - its dry run's lines (what it would
    revoke at Google, delete and mark) and the plan of every channel's API
    Data with its reason, and the same dry run as data (`revoke_result`, by
    user via center - what a confirm would do). Nothing reaches Google,
    nothing changes; the revocation itself is `revoke_plan` -> `revoke`."""
    pc, pa, ad = _mods()
    cfg = _cfg(pc)
    now = _now(pa)
    buf = io.StringIO()
    try:
        code = ad.revoke(cfg, Path(root), now, yes=False, out=buf)
        p = ad.plan(Path(root), reason=ad.REVOKED_REASON)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "план отзыва не составлен") from e
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    if code != ad.EXIT_OK:
        raise BatchFault(500, "factory_broken", "План отзыва фабрики не составлен.",
                         [f"api_data.py revoke: exit {code}", *lines])
    return {"dry_run": True, "lines": lines, "token_present": Path(cfg.token_file).is_file(),
            "result": _revoke_dry(root, ad, cfg, now), "plan": _plan_doc(ad, p),
            "google_page": ad.GOOGLE_PAGE, "confirm_available": True}


# ---------------------------------------------------------------- the purge
def _purge_plan(root, ad, channels):
    try:
        return ad.plan(Path(root), channels=channels, reason=PURGE_REASON)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "план удаления API Data не составлен") from e


def _channels(root, scope, names):
    if scope == "all":
        return None
    got = []
    for n in names or []:
        cid = _channel(root, n)
        if cid not in got:
            got.append(cid)
    if not got:
        raise BatchFault(422, "no_channels", "Назовите каналы, API Data которых удалить, "
                                             "или выберите «все каналы».",
                         ["scope channels with an empty list"])
    return got


def _facts(doc):
    return {"action": ACTION, "channels": doc["channels"], "reason": doc["reason"],
            "lines": doc["lines"], "by": WRITE_BY, "via": VIA}


def purge_plan(root, scope, names=None):
    """What `api_data.py purge --all | --channel C` would delete (its dry
    run) and a confirm token bound to the channels - nothing deleted."""
    _, _, ad = _mods()
    chans = _channels(root, scope, names)
    doc = _plan_doc(ad, _purge_plan(root, ad, chans))
    ok = not doc["empty"]
    fp = _digest(_facts(doc))
    out = {"action": ACTION, "ok": ok, "scope": scope, "asked": chans,
           "why": None if ok else "Удалять нечего: API Data этих каналов нет.",
           "plan": doc, "by": WRITE_BY, "via": VIA, "fingerprint": fp, "confirm": None,
           "expires_in_s": None}
    if ok:
        out.update(confirm=_issue(root, ACTION, KEY, fp, {"scope": scope, "channels": chans}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return out


def purge(root, token):
    """The confirmed purge: the token spent, the plan again and the same
    (else `check_changed`), then `apply(extra={by: user, via: center})`."""
    _, pa, ad = _mods()
    if not publish._WRITE.acquire(timeout=publish.WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись публикации - подождите и запросите "
                                      "план заново.",
                         [f"the publication write lock was not free in {publish.WRITE_WAIT} s; "
                          f"the token is not spent"])
    try:
        got = _spend(root, ACTION, KEY, token)
        chans = got["bound"]["channels"]
        p = _purge_plan(root, ad, chans)
        doc = _plan_doc(ad, p)
        if _digest(_facts(doc)) != got["fingerprint"]:
            if doc["empty"]:
                raise BatchFault(409, "refused", "Удалять уже нечего: API Data этих каналов нет.",
                                 ["the plan is empty now"])
            raise BatchFault(409, "check_changed", "API Data изменились с момента плана - "
                                                   "ничего не удалено; посмотрите план заново.",
                             [f"the fingerprint of the {ACTION} plan differs from the plan's"])
        scope = _scope(root, ad, [p])
        before = root_commit.snap(root, scope)
        try:
            rec = ad.apply(p, _now(pa), extra={"by": WRITE_BY, "via": VIA})
        except Exception as e:                                   # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Фабрика ответила ошибкой посреди удаления - "
                                                    "посмотрите publish/ и analytics/, прежде "
                                                    "чем повторять.",
                             [f"{type(e).__name__}: {e}"]) from e
        sha, committed = _committed(
            root, ACTION, scope, before,
            f"API Data: удалены по запросу владельца - {', '.join(doc['channels']) or 'нет каналов'} "
            f"({WRITE_BY}, {VIA})",
            "CC-0156: удаление API Data из центра (oauth.purge, api_data.apply).\n"
            + _counts([doc]), "API Data удалены")
    finally:
        publish._WRITE.release()
    return {"action": ACTION, "written": True, "by": WRITE_BY, "via": VIA, "plan": doc,
            "record": rec, "log": _rel(root, Path(root) / "publish" / ad.LOG),
            "commit": sha, "committed": committed}


# ---------------------------------------------------------------- the revocation (CC-0082)
def _result_doc(root, res):
    """`revoke_result`'s dict - its paths relative to the root where they are
    in it (the token and its state are usually outside). Never a token
    value: the factory's result holds none."""
    out = dict(res)
    out["google"] = dict(res["google"])
    out["token"] = dict(res["token"], file=_rel(root, res["token"]["file"]))
    out["state_file"] = _rel(root, res["state_file"])
    out["channels"] = list(res["channels"])
    out["items"] = list(res["items"])
    return out


def _revoke_dry(root, ad, cfg, now):
    try:
        res = ad.revoke_result(cfg, Path(root), now, yes=False, by=WRITE_BY, via=VIA)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "план отзыва не составлен") from e
    return _result_doc(root, res)


def _revoke_facts(res):
    tok = res["token"]
    return {"action": REVOKE, "token": {k: tok[k] for k in ("kind", "missing", "existed")},
            "channels": res["channels"], "items": res["items"], "by": WRITE_BY, "via": VIA}


def _revoke_ok(res, doc):
    return bool(res["token"]["existed"]) or not doc["empty"]


def revoke_plan(root):
    """What `api_data.py revoke --yes` would do (the factory's dry run as
    data, by user via center) and a confirm token - nothing reaches Google,
    nothing changes. Nothing to revoke (no token file, no API Data): `ok:
    false`, no token."""
    pc, pa, ad = _mods()
    cfg = _cfg(pc)
    now = _now(pa)
    res = _revoke_dry(root, ad, cfg, now)
    doc = _plan_doc(ad, _revoked_plan(root, ad))
    ok = _revoke_ok(res, doc)
    fp = _digest(_revoke_facts(res))
    out = {"action": REVOKE, "ok": ok,
           "why": None if ok else "Отзывать нечего: файла токена нет и API Data нет.",
           "result": res, "plan": doc, "google_page": ad.GOOGLE_PAGE, "by": WRITE_BY,
           "via": VIA, "fingerprint": fp, "confirm": None, "expires_in_s": None}
    if ok:
        out.update(confirm=_issue(root, REVOKE, TOKEN_KEY, fp),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return out


def _revoked_plan(root, ad):
    try:
        return ad.plan(Path(root), reason=ad.REVOKED_REASON)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "план отзыва не составлен") from e


def _write_lock():
    if not publish._WRITE.acquire(timeout=publish.WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись публикации - подождите и запросите "
                                      "план заново.",
                         [f"the publication write lock was not free in {publish.WRITE_WAIT} s; "
                          f"the token is not spent"])


def revoke(root, token):
    """The confirmed revocation: the token spent, the dry run again and the
    same (else `check_changed`; nothing to revoke now - `refused`), then
    `revoke_result(yes=True, by user, via center)` - its structured result.
    Google not answering: `ok: false`, `written: false` - nothing changed."""
    pc, pa, ad = _mods()
    cfg = _cfg(pc)
    _write_lock()
    try:
        got = _spend(root, REVOKE, TOKEN_KEY, token)
        now = _now(pa)
        dry = _revoke_dry(root, ad, cfg, now)
        doc = _plan_doc(ad, _revoked_plan(root, ad))
        if _digest(_revoke_facts(dry)) != got["fingerprint"]:
            if not _revoke_ok(dry, doc):
                raise BatchFault(409, "refused", "Отзывать уже нечего: файла токена нет и API "
                                                 "Data нет.", ["the revocation's plan is empty now"])
            raise BatchFault(409, "check_changed", "Токен или API Data изменились с момента "
                                                   "плана - ничего не отозвано и не удалено; "
                                                   "посмотрите план заново.",
                             [f"the fingerprint of the {REVOKE} plan differs from the plan's"])
        scope = _scope(root, ad, [_revoked_plan(root, ad)])
        before = root_commit.snap(root, scope)
        try:
            res = ad.revoke_result(cfg, Path(root), now, yes=True, by=WRITE_BY, via=VIA)
        except Exception as e:                                   # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Фабрика ответила ошибкой посреди отзыва - "
                                                    "посмотрите токен, publish/ и analytics/, "
                                                    "прежде чем повторять.",
                             [f"{type(e).__name__}: {e}"]) from e
        sha, committed = _committed(
            root, REVOKE, scope, before,
            f"API Data: удалены после отзыва токена - {', '.join(res['channels']) or 'нет каналов'} "
            f"({WRITE_BY}, {VIA})",
            f"CC-0156: отзыв токена из центра (oauth.revoke, api_data.revoke_result).\n"
            f"Google: {res['google'].get('answer')}\n" + _counts([doc]),
            "Токен отозван, API Data удалены")
    finally:
        publish._WRITE.release()
    res = dict(_result_doc(root, res), commit=sha, committed=committed)
    why = None
    if not res["ok"]:
        why = (f"Google не ответил на отзыв ({res['google']['detail']}) - ничего не изменено, "
               f"токен сохранён. Повторите (новый план) или отзовите доступ на "
               f"{ad.GOOGLE_PAGE}.")
    return {"action": REVOKE, "ok": res["ok"], "written": res["ok"], "why": why,
            "by": WRITE_BY, "via": VIA, "result": res, "plan": doc,
            "google_page": ad.GOOGLE_PAGE, "log": res["log"]}


# ---------------------------------------------------------------- the deletion by term (CC-0082)
def _auto_plans(root, ad, cfg, now):
    try:
        return [p for p, _ in ad.auto(cfg, Path(root), now, delete=False)]
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "план удаления по сроку не составлен") from e


def _auto_docs(root, ad, cfg, now, plans=None):
    plans = _auto_plans(root, ad, cfg, now) if plans is None else plans
    try:
        return [_plan_doc(ad, p) for p in plans]
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "план удаления по сроку не составлен") from e


def _auto_facts(docs):
    return {"action": AUTO, "items": [{"reason": d["reason"], "channels": d["channels"],
                                       "lines": d["lines"]} for d in docs],
            "by": WRITE_BY, "via": VIA}


def auto_plan(root):
    """What the auto-run would delete now (`auto(delete=False)`: the
    revocation's term past, the stale rows) and a confirm token when there is
    something - nothing deleted."""
    pc, pa, ad = _mods()
    cfg = _cfg(pc)
    now = _now(pa)
    docs = _auto_docs(root, ad, cfg, now)
    ok = bool(docs)
    fp = _digest(_auto_facts(docs))
    out = {"action": AUTO, "ok": ok,
           "why": None if ok else "Удалять по сроку нечего: срок после отзыва не прошёл, "
                                  "устаревших строк нет.",
           "due": docs, "revocation": _revocation(pa, ad, cfg, now),
           "by": WRITE_BY, "via": VIA, "fingerprint": fp, "confirm": None,
           "expires_in_s": None}
    if ok:
        out.update(confirm=_issue(root, AUTO, KEY, fp), expires_in_s=int(batches.CONFIRM_TTL))
    return out


def auto_delete(root, token):
    """The confirmed deletion by term: the token spent, the plan again and
    the same (else `check_changed`; nothing due now - `refused`), then
    `auto(delete=True, by user, via center)`: the log rows, the journal rows
    and the token state's `api_data_deleted` say who and where."""
    pc, pa, ad = _mods()
    cfg = _cfg(pc)
    _write_lock()
    try:
        got = _spend(root, AUTO, KEY, token)
        now = _now(pa)
        plans = _auto_plans(root, ad, cfg, now)
        docs = _auto_docs(root, ad, cfg, now, plans)
        if _digest(_auto_facts(docs)) != got["fingerprint"]:
            if not docs:
                raise BatchFault(409, "refused", "Удалять по сроку уже нечего.",
                                 ["the plan is empty now"])
            raise BatchFault(409, "check_changed", "API Data изменились с момента плана - "
                                                   "ничего не удалено; посмотрите план заново.",
                             [f"the fingerprint of the {AUTO} plan differs from the plan's"])
        scope = _scope(root, ad, plans)
        before = root_commit.snap(root, scope)
        try:
            done = ad.auto(cfg, Path(root), now, delete=True, by=WRITE_BY, via=VIA)
        except Exception as e:                                   # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Фабрика ответила ошибкой посреди удаления - "
                                                    "посмотрите publish/ и analytics/, прежде "
                                                    "чем повторять.",
                             [f"{type(e).__name__}: {e}"]) from e
        chans = sorted({c for p, _ in done for c in p["channels"]})
        sha, committed = _committed(
            root, AUTO, scope, before,
            f"API Data: удалены по сроку - {', '.join(chans) or 'нет каналов'} "
            f"({WRITE_BY}, {VIA})",
            "CC-0156: удаление API Data по сроку из центра (oauth.auto_delete, api_data.auto)."
            + "".join(f"\n{d['reason']}: " + _counts([d]) for d in docs),
            "API Data удалены по сроку")
    finally:
        publish._WRITE.release()
    return {"action": AUTO, "written": True, "by": WRITE_BY, "via": VIA,
            "done": [{"plan": _plan_doc(ad, p), "record": rec} for p, rec in done],
            "revocation": _revocation(pa, ad, cfg, _now(pa)),
            "log": _rel(root, Path(root) / "publish" / ad.LOG),
            "commit": sha, "committed": committed}

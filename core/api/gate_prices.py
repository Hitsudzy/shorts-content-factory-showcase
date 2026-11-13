"""CC-0100: what a refusal costs, read only - what `scripts/runlog gate-price
[--rule NAME]... [--window N] [--before DAY] --json` gives. Only through the
factory's own functions (`api/factory.py` `gate_price`):

    shared/runlog/gate_price.py   RULES, rule, price (per rule: the window's
                                  batches, the ready videos, the price - the
                                  ready videos it would have killed, None when
                                  no batch could price it -, the verdict, why,
                                  the signature, the decision), headline,
                                  batches (the window), WINDOW, BATCH_ID;
                                  read_ledger, proposals, proposal_line,
                                  _proposal_mode_until_signed - the ledger
                                  `shared/gate-prices.json` as render_stats
                                  reads it

**The answer**: `results` - one `price(rule)` per rule asked (every
registered one by default), serialized as the CLI's `--json` does
(`json.dumps(..., default=str)`), each with its `headline` and the code's
mode (`Rule.mode`, CF-0472); `all_land` - every verdict `enforce` or
`penalty` (the CLI's exit code 0, the one CF-0319's triage reads);
`unregistered` - the ledger's rows with a user's decision and no replay
(what render_stats prints after the measured ones); `proposals` - the
prices proposed for the user's signature, not in force.

**Nothing here writes but the factory's two writers**: `write_ledger`,
`write_stats` and `main` (whose `--write` records the measurements) are
never named - `tests/test_cc_api_gate_prices.py` walks this file's names.
The batches are the root's `pipeline/` (the CLI's $RUNLOG_POOL is not read:
the API reads its factory root), the ledger the root's
`shared/gate-prices.json`.

**The signature and the decision** (CC-0114, the factory's CF-0721):
`gate_price.sign(rule, price, note, by, via, base_sha256=...)` and
`gate_price.decide(rule, mode, task, note, by, via, base_sha256=...)` - the
one writer of a `signature` / `decision` block, called with by="user",
via="center" only after the user pressed the button. Two steps, as the
channel lists' writes (`api/channel_lists.py`):

* **the plan** (`sign_plan` / `decide_plan`): the factory's call with
  `dry_run=True` - nothing written, no lock -, its answer in the CF-0726
  shape (`ok`, `block`, `sha256`, `new_sha256`, `refusals [{code, line,
  message}]` - the factory's code and line, the center's Russian message -,
  `lines`); the base is the GET's `ledger_sha256` when the body carries one,
  else the ledger's sha256 now (`gate_price.ledger_sha256`). A confirm token
  (`batches` store, 120 s, single use; actions `gate_price_sign`,
  `gate_price_decide`, keyed by the rule) only when the dry run is ok,
  bound to the input and the base;
* **the confirm** (`sign` / `decide`): one ledger write of the center at a
  time, the token spent, then the same call for real with the plan's base.
  The factory checks the batches and the base again under its lock
  `shared/.gate-prices.lock` (`check_changed` - «откройте заново») and
  commits the ledger alone itself (`git_commit.write_and_commit`; `not_repo`,
  `commit_refused`). Any refusal is a problem `{message, code, details}`.

The read carries, per rule, what the buttons may do now (`actions`: in the
ledger, its measured price - the floor of a signature -, whether a
signature / a decision would be taken, and if not the code and the Russian
why); the open batches are not read for it - the plan says `batch_open`.
`FACTORY_KW` holds the factory's injection points (`now`, `open_rows`) -
empty in production.

**The cost**: a price reads the stage files of the window's batches (~3 s of
one core for every rule over five batches). One read at a time (`_LOCK`),
kept per state of the window (each batch's stage files' mtime and size) and
of the ledger: a second read of an unchanged window answers at once,
`cached: true`.

The paths in the answer are cut by `api/paths.clean` in the route.
"""
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import batches, factory, paths
from .batches import BatchFault, _digest, _issue, _spend

LEDGER = ("shared", "gate-prices.json")
POOL = "pipeline"
#: The default window (= gate_price.WINDOW - the user's five batches, ROADMAP `## Versioning`).
WINDOW = 5
#: The longest window the center asks for (the CLI's 0 - every batch on disk -
#: is not offered: it reads every batch the factory ever ran).
WINDOW_MAX = 20
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEEP = 8
_KEPT = {}                        # (pool, names, window, before) -> (state, computed_at, doc)
_LOCK = threading.Lock()          # one read at a time - the machine's sake

#: Signing a price / deciding a mode from the center (CC-0114 over CF-0721).
SIGNING = {
    "available": True,
    "what": ("Подписать цену правила (не ниже измеренной в леджере) или записать решение "
             "measure/warn с номером задачи и вашей заметкой - кнопкой, в два шага (план, "
             "подтверждение за 120 с). Пишет сама фабрика (shared/runlog/gate_price.py sign / "
             "decide, CF-0721) от вашего имени через центр и коммитит shared/gate-prices.json; "
             "пока идёт батч, цены не подписываются."),
    "how_today": ("Подпись (`signature`: user, date, price, note, via) и решение (`decision`: "
                  "user, date, mode, task, note, via) в shared/gate-prices.json пишет "
                  "gate_price.sign / gate_price.decide - только после нажатия кнопки в центре, "
                  "by=user, via=center; руками леджер больше не правят."),
    "factory_function": "shared/runlog/gate_price.py sign, decide (CF-0721)",
    "task": "CF-0721",
}

#: Who and where the center signs (CF-0721's by/via).
WRITE_BY, VIA = "user", "center"
#: How long a confirm waits for the factory's ledger lock.
LOCK_WAIT = 15.0
#: One ledger write of the center at a time; how long the next waits.
_WRITE = threading.Lock()
WRITE_WAIT = 30.0
#: The factory's own injection points (`now`, `open_rows`) - empty in production.
FACTORY_KW = {}

#: kind -> (confirm action, the factory block it writes)
KINDS = {"sign": ("gate_price_sign", "signature"), "decide": ("gate_price_decide", "decision")}
ACTIONS = {
    "gate_price_sign": ("план подписи цены", "цена не подписана", "подписи цены правила"),
    "gate_price_decide": ("план решения по правилу", "решение не записано",
                          "решения по правилу"),
}
batches.register_actions(ACTIONS)

_NOTHING = "ничего не записано"
#: The factory's refusal code (gate_price.SIGN_REFUSALS) -> (HTTP status, the Russian message).
REFUSALS = {
    "bad_who": (500, f"Центр подписал запись неверно (by/via) - это ошибка центра, {_NOTHING}."),
    "not_human": (500, f"Подписывает только человек, а имя подписавшего читается как модель, "
                       f"агент или скрипт - это ошибка центра, {_NOTHING}."),
    "bad_via": (500, f"Подпись ставится только из командного центра (via=center) - это ошибка "
                     f"центра, {_NOTHING}."),
    "empty_note": (422, "Нужна ваша заметка - подпись и решение без ваших слов не пишутся."),
    "bad_date": (422, f"Дата не в виде ГГГГ-ММ-ДД - {_NOTHING}."),
    "ledger_unreadable": (500, f"shared/gate-prices.json не читается (не JSON или без таблицы "
                               f"rules) - посмотрите файл, {_NOTHING}."),
    "no_such_rule": (404, "Этого правила нет в леджере shared/gate-prices.json - подписывать "
                          "нечего: цену сначала измеряют (runlog gate-price --write)."),
    "not_signable": (409, "Это правило модели оценок (hard / penalty) - его подписывают вместе "
                          "с таблицей оценок, не здесь."),
    "not_measured": (409, "Цена правила в леджере не измерена - подпись не покрывает то, что "
                          "никто не мерил."),
    "bad_price": (422, "Цена - это число готовых роликов, 0 или больше."),
    "below_measured": (409, "Цена ниже измеренной - такая подпись ничего бы не покрыла; "
                            "подпишите не меньше измеренной."),
    "already_signed": (409, "Правило уже подписано ценой, которая покрывает измеренную: новая "
                            "подпись не нужна, а решение подпись не снимает."),
    "bad_mode": (422, "Решение - только measure (мерить) или warn (предупреждать): отказ "
                      "делает только подпись."),
    "bad_task": (422, "Нужен номер задачи вида CF-0330."),
    "batch_open": (409, "Пока идёт батч, цены не подписываются - батчи читают shared/; "
                        "повторите после батча."),
    "check_changed": (409, f"Леджер цен изменился с тех пор, как вы его открыли - откройте "
                            f"заново, {_NOTHING}."),
    "locked": (409, "Леджер цен сейчас пишет кто-то другой (замер цен или другая подпись) - "
                    "подождите и повторите."),
    "not_repo": (409, f"Корень фабрики - не git-репозиторий: леджер не закоммитить, "
                      f"{_NOTHING}."),
    "commit_refused": (409, "Git не принял коммит леджера - файл возвращён как был."),
    "write_failed": (500, "Леджер не записался - посмотрите диск, прежде чем повторять."),
}
#: Which refusal speaks first when there are several (the factory's order).
ORDER = ("bad_who", "not_human", "bad_via", "empty_note", "bad_date", "ledger_unreadable",
         "no_such_rule", "not_signable", "not_measured", "bad_price", "below_measured",
         "already_signed", "bad_mode", "bad_task", "batch_open", "check_changed", "locked",
         "not_repo", "commit_refused", "write_failed")


def _gp():
    return factory.gate_price()


def _iso(ts=None):
    t = datetime.fromtimestamp(ts, timezone.utc) if ts is not None else datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _names(gp, rules):
    """The rules asked, in the CLI's order - every registered one by default;
    one the factory does not have is 404 `unknown_rule`."""
    names = list(dict.fromkeys(r.strip() for r in (rules or []) if r and r.strip()))
    for n in names:
        try:
            gp.rule(n)
        except KeyError as e:
            raise BatchFault(404, "unknown_rule", f"У фабрики нет правила «{n}».",
                             [e.args[0] if e.args else f"no such rule: {n}"]) from e
    return names or sorted(gp.RULES)


def _before(gp, before):
    b = (before or "").strip() or None
    if b and not (DAY.match(b) or gp.BATCH_ID.match(b)):
        raise BatchFault(422, "bad_before", f"«{b}» - не день и не батч: нужен ГГГГ-ММ-ДД или "
                                            f"id батча (ГГГГ-ММ-ДДTЧЧММZ).",
                         [f"--before {b!r}: YYYY-MM-DD or a batch id"])
    return b


def _state(gp, pool, ledger, window, before):
    """What the prices are read from: the window's batches (each one's stage
    files, mtime and size) and the ledger."""
    out = []
    names = list(gp.funnel.ARTIFACTS) + list(getattr(gp.funnel, "OPTIONAL_ARTIFACTS", ()))
    for b in gp.batches(pool, window, before):
        for n in names:
            try:
                st = (b / n).stat()
            except OSError:
                continue
            out.append((b.parent.name, b.name, n, st.st_mtime_ns, st.st_size))
    try:
        st = ledger.stat()
        out.append(("ledger", st.st_mtime_ns, st.st_size))
    except OSError:
        out.append(("ledger", None))
    return tuple(out)


def _why(code):
    return {"code": code, "message": REFUSALS[code][1]}


def actions(gp, name, ledger_doc):
    """What the buttons may do with `name` now, as far as the ledger says - the
    factory's own checks of `sign` / `decide` on the row (not the batches, not
    the price or the note the user will type): `in_ledger`, `measured_price`
    (the ledger's - the floor of a signature), `signable` (not a score-model
    row), `sign` / `decide` (bool) and, when false, `sign_refusal` /
    `decide_refusal` {code, message}."""
    rows = ledger_doc.get("rules") if isinstance(ledger_doc, dict) else None
    row = rows.get(name) if isinstance(rows, dict) else None
    out = {"in_ledger": isinstance(row, dict), "measured_price": None, "signable": False,
           "sign": False, "sign_refusal": None, "decide": False, "decide_refusal": None}
    if not isinstance(row, dict):
        out.update(sign_refusal=_why("no_such_rule"), decide_refusal=_why("no_such_rule"))
        return out
    measured = gp._measured_price(row)
    out["measured_price"] = measured
    if row.get("mode") in gp.SCORE_MODES:
        out.update(sign_refusal=_why("not_signable"), decide_refusal=_why("not_signable"))
        return out
    out["signable"] = True
    if gp._covers(row.get("signature"), measured):
        out.update(sign_refusal=_why("already_signed"), decide_refusal=_why("already_signed"))
        return out
    out.update(decide=True)
    if measured is None:
        out["sign_refusal"] = _why("not_measured")
    else:
        out["sign"] = True
    return out


def _result(gp, res, ledger_doc):
    doc = json.loads(json.dumps(res, ensure_ascii=False, default=str))
    doc["headline"] = gp.headline(res)
    doc["mode"] = gp.rule(res["rule"]).mode
    doc["actions"] = actions(gp, res["rule"], ledger_doc)
    return doc


def _unregistered(gp, ledger_doc, seen):
    """The ledger's rows with a user's decision and no replay - render_stats'
    choice of them."""
    rows = ledger_doc.get("rules") or {}
    out = []
    for name in sorted(rows):
        row = rows[name]
        if name in seen or name in gp.RULES or not isinstance(row, dict) \
                or not isinstance(row.get("decision"), dict):
            continue
        m = row.get("measured")
        out.append({"rule": name, "note": row.get("note"),
                    "measured": m if isinstance(m, dict) else None,
                    "signature": row["signature"] if isinstance(row.get("signature"), dict)
                    else None,
                    "decision": row["decision"],
                    "actions": actions(gp, name, ledger_doc)})
    return out


def _proposals(gp, ledger_doc):
    rows = gp.proposals(ledger_doc)
    return [{"rule": n, "line": gp.proposal_line(n, rows[n]),
             "mode_until_signed": gp._proposal_mode_until_signed(rows[n])}
            for n in sorted(rows)]


def prices(root, rules=None, window=None, before=None):
    gp = _gp()
    window = gp.WINDOW if window is None else int(window)
    names = _names(gp, rules)
    before = _before(gp, before)
    pool = Path(root) / POOL
    ledger = Path(root).joinpath(*LEDGER)
    key = (str(pool), tuple(names), window, before)
    with _LOCK:
        state = _state(gp, pool, ledger, window, before)
        base = _sha(gp, root)
        kept = _KEPT.get(key)
        if kept and kept[0] == state:
            doc, at, cached = kept[2], kept[1], True
        else:
            try:
                results = [gp.price(gp.rule(n), pool=pool, window=window, before=before,
                                    ledger=ledger) for n in names]
                ledger_doc = gp.read_ledger(ledger)
                doc = {"results": [_result(gp, r, ledger_doc) for r in results],
                       "all_land": all(r["verdict"] in (gp.ENFORCE, gp.PENALTY)
                                       for r in results),
                       "unregistered": _unregistered(gp, ledger_doc, set(names)),
                       "proposals": _proposals(gp, ledger_doc)}
            except BatchFault:
                raise
            except Exception as e:                              # noqa: BLE001
                raise BatchFault(500, "factory_broken", "runlog gate-price не посчиталась - "
                                                        "посмотрите батчи окна и "
                                                        "shared/gate-prices.json.",
                                 [f"{type(e).__name__}: {e}"]) from e
            at, cached = _iso(), False
            _KEPT.pop(key, None)
            _KEPT[key] = (state, at, doc)
            while len(_KEPT) > _KEEP:
                _KEPT.pop(next(iter(_KEPT)))
    return {"rules": sorted(gp.RULES), "asked": names, "window": window, "before": before,
            "window_default": gp.WINDOW, "pool": paths.rel(root, pool),
            "ledger": paths.rel(root, ledger), "ledger_exists": ledger.is_file(),
            "ledger_sha256": base,
            **doc, "signing": SIGNING, "computed_at": at, "cached": cached}


# ------------------------------------------------------------------ the signature (CC-0114)
def _sha(gp, root):
    try:
        return gp.ledger_sha256(root)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Фабрика не посчитала sha256 леджера цен - "
                                                "посмотрите shared/gate-prices.json.",
                         [f"{type(e).__name__}: {e}"]) from e


def _call(root, kind, rule, bound, base, dry_run):
    gp = _gp()
    kw = {k: FACTORY_KW[k] for k in ("now", "open_rows") if k in FACTORY_KW}
    try:
        if kind == "sign":
            return gp.sign(rule, bound["price"], bound["note"], WRITE_BY, VIA,
                           base_sha256=base, root=root, dry_run=dry_run, commit=True,
                           lock_wait=LOCK_WAIT, **kw)
        return gp.decide(rule, bound["mode"], bound["task"], bound["note"], WRITE_BY, VIA,
                         base_sha256=base, root=root, dry_run=dry_run, commit=True,
                         lock_wait=LOCK_WAIT, **kw)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Подпись цены фабрики ответила ошибкой - "
                                                "посмотрите shared/gate-prices.json, прежде чем "
                                                "повторять.",
                         [f"{type(e).__name__}: {e}"]) from e


def _refusals(res):
    return [dict(r, message=REFUSALS.get(r["code"], (500, r["line"]))[1])
            for r in res["refusals"]]


def _first(refs):
    return min(refs, key=lambda r: ORDER.index(r["code"]) if r["code"] in ORDER else len(ORDER))


def _body(kind, rule, res, refs):
    return {"action": KINDS[kind][0], "kind": kind, "rule": rule, "key": res.get("key"),
            "task": res.get("task"), "ok": bool(res["ok"]), "path": res.get("path"),
            "base_sha256": res.get("base_sha256"), "sha256": res.get("sha256"),
            "new_sha256": res.get("new_sha256"), "block": res.get("block"), "refusals": refs,
            "lines": list(res.get("lines") or []), "by": res.get("by"), "via": res.get("via")}


def plan(root, kind, rule, bound, base_sha256=None):
    """The factory's dry run of `sign` / `decide` (by user via center) and a
    confirm token when it would write - nothing written. `bound`: {price,
    note} or {mode, task, note}; `base_sha256`: the GET's `ledger_sha256`, else
    the ledger now."""
    action, _key = KINDS[kind]
    base = base_sha256 if base_sha256 is not None else _sha(_gp(), root)
    res = _call(root, kind, rule, bound, base, dry_run=True)
    refs = _refusals(res)
    out = dict(_body(kind, rule, res, refs), dry_run=True,
               why=_first(refs)["message"] if refs else None, confirm=None, expires_in_s=None)
    if res["ok"]:
        fp = _digest({"action": action, "rule": rule, "bound": bound, "base": base,
                      "new": res["new_sha256"]})
        out.update(confirm=_issue(root, action, rule, fp, {"bound": bound, "base": base}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def confirm(root, kind, rule, token):
    """The confirmed write: the token spent, then the factory's call for real
    with the plan's base - the factory commits the ledger; a refusal is a
    problem, nothing written."""
    action, _key = KINDS[kind]
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая подпись цены - подождите и запросите план "
                                      "заново.",
                         [f"the gate-price write lock was not free in {WRITE_WAIT} s; the token "
                          f"is not spent"])
    try:
        got = _spend(root, action, rule, token)
        res = _call(root, kind, rule, got["bound"]["bound"], got["bound"]["base"],
                    dry_run=False)
    finally:
        _WRITE.release()
    refs = _refusals(res)
    if not res["ok"]:
        first = _first(refs)
        status = REFUSALS.get(first["code"], (500, ""))[0]
        raise BatchFault(status, first["code"], first["message"],
                         paths.clean([f"{r['code']}: {r['line']}" for r in res["refusals"]]
                                     + list(res.get("lines") or []), root))
    return paths.clean(dict(_body(kind, rule, res, refs), dry_run=False,
                            written=bool(res["written"]), commit=res.get("commit")), root)

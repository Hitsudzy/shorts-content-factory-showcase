"""CC-0105: freeing the footage pool of the sources of finished videos - what
`scripts/runlog pool-release --variants` shows and `--delete` does, beside
the CC-0032 cleanups (`/api/maintenance/...`). Only through the factory's own
functions (`shared/runlog/pool_release.py`, CF-0358, `factory.pool_release`):

    plan(root, now, stale_days)   what would go (`release`), what is kept and
                                  why (`keep`, `blocked_by`), what no batch on
                                  disk names (`orphan`), the open batches
    variants(p)                   the user's question in numbers: what further
                                  rules for topics that never became a video
                                  would free - nothing here deletes by them
    delete(p, root, now, by, via, dry_run, rows)
                                  the one writer: the `release` sources' files,
                                  their index entries, a `released` row each in
                                  `shared/footage/release-log.jsonl` (CF-0720:
                                  `by` / `via` on each row, `rows` gets them,
                                  `dry_run=True` the same run with nothing
                                  touched); refused by the factory itself while
                                  a batch is open
    journal_path                  where the rows go

**The read** (`GET /maintenance/pool?stale_days=N`): `plan()` and
`variants()` - what `pool-release --json --variants [--stale-days N]` prints,
the root's absolute path left out, the three lists summed. Nothing written.

**The write** (`POST /maintenance/pool/release/plan {stale_days}` ->
`POST /maintenance/pool/release {confirm}`): the plan is the dry run - the
same `plan()`, the `release` list and a confirm token (action
`pool_release_delete`, 120 s, single use, bound to `stale_days`) when there is
something to free and no batch is open (`factory.open_batches`, what `runlog
batch-active` counts, and the plan's own `open_batches` - `delete` refuses on
any); with a token, `rows` - the `released` rows the factory's dry run
(`delete(..., dry_run=True, rows=)`) says the confirm would write. The
confirm spends the token, asks `factory.open_batches` again
(`batch_open`), runs `plan()` again and compares what it would delete - each
source's id, files, bytes and the status of each of its topics (anything else
`check_changed`; nothing to free now `refused`), then `delete(p, root, by,
via, rows=)`. The
factory's own refusal of an open batch (its `RuntimeError`) is `batch_open`
too. No deletion logic of the API's own: every file goes inside `delete`.

**Who.** `delete(..., by="user", via="center")` (CF-0720) writes both into
each `released` row; the answer says `by: user, via: center` and
`recorded_by: true`.

`FACTORY_KW["now"]` is the factory's clock (a datetime) - empty in
production; the tests put a fixed one there. Every refusal is a `BatchFault`
(`{message, code, details}`), every answer goes out through `api/paths.clean`.
"""
import threading
from pathlib import Path

from . import batches, factory, paths
from .batches import BatchFault, _digest, _issue, _spend

ACTION = "pool_release_delete"
KEY = "footage-pool"
ACTIONS = {ACTION: ("план освобождения пула исходников", "исходники не тронуты",
                    "освобождения пула исходников")}
batches.register_actions(ACTIONS)
WRITE_BY, VIA = "user", "center"
CLI = "scripts/runlog pool-release"
STALE_MAX = 365
WRITE_WAIT = 5.0
_WRITE = threading.Lock()
#: The factory's own injection points - empty in production.
FACTORY_KW = {}

SCRIPT = {"script": CLI, "exposed": "plan_confirm",
          "routes": ["GET /api/maintenance/pool", "POST /api/maintenance/pool/release/plan",
                     "POST /api/maintenance/pool/release"],
          "why": "чтение - его plan() и variants() (--json --variants); план удаления - тот же "
                 "plan(), подтверждение - delete() фабрики после той же проверки; при открытом "
                 "батче отказ"}

ENTRY_KEYS = ("video_id", "files", "bytes", "topics", "newest_batch", "blocked_by",
              "open_batches", "candidate_of", "untopiced_in", "kind")


def _pr():
    return factory.pool_release()


def _broken(e, what="План пула исходников фабрики не составлен."):
    return BatchFault(500, "factory_broken", what, [f"{type(e).__name__}: {e}"])


def _stale(stale_days):
    if stale_days is None:
        return None
    if isinstance(stale_days, bool) or not isinstance(stale_days, int) \
            or not 1 <= stale_days <= STALE_MAX:
        raise BatchFault(422, "invalid", f"stale_days - целое число дней от 1 до {STALE_MAX}.",
                         [f"stale_days {stale_days!r}: not 1..{STALE_MAX}"])
    return stale_days


def _plan(root, stale_days):
    pr = _pr()
    try:
        return pr.plan(root, now=FACTORY_KW.get("now"), stale_days=stale_days)
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e) from e


def _entry(e):
    return {k: e[k] for k in ENTRY_KEYS if k in e}


def _sum(rows):
    return {"sources": len(rows), "bytes": sum(e.get("bytes") or 0 for e in rows)}


def _command(stale_days, *flags):
    return " ".join([CLI, *flags] + ([f"--stale-days {stale_days}"] if stale_days else []))


def _going(root):
    try:
        return [f"{Path(b['dir']).parent.name}/{Path(b['dir']).name}"
                for b in factory.open_batches(root)]
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Не проверено, открыт ли батч - пул не тронут.",
                         [f"runlog.open_batches: {type(e).__name__}: {e}"]) from e


def _journal(root, pr):
    return paths.rel(root, pr.journal_path(Path(root)))


def view(root, stale_days=None):
    """`pool-release --json --variants [--stale-days N]`: the plan and the
    variants - nothing written."""
    stale_days = _stale(stale_days)
    pr = _pr()
    p = _plan(root, stale_days)
    try:
        var = pr.variants(p)
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e) from e
    out = {"command": _command(stale_days, "--json", "--variants"), "at": p["at"],
           "stale_days": p.get("stale_days"), "open_batches": list(p["open_batches"]),
           "release": [_entry(e) for e in p["release"]],
           "keep": [_entry(e) for e in p["keep"]],
           "orphan": [_entry(e) for e in p["orphan"]],
           "unresolved": [{"kind": k, "entry": x} for k, x in p["unresolved"]],
           "pool": dict(p["pool"]),
           "totals": {"release": _sum(p["release"]), "keep": _sum(p["keep"]),
                      "orphan": _sum(p["orphan"])},
           "variants": var, "journal": _journal(root, pr), "delete_action": ACTION}
    return paths.clean(out, root)


def _facts(p, going, stale_days):
    """What the confirm holds the plan to: the sources `delete` would remove
    (each with its files, bytes and its topics' statuses) and the open
    batches - `at` and the kept/orphan lists are not what is deleted."""
    rel = [{"video_id": e["video_id"], "files": list(e["files"]), "bytes": e["bytes"],
            "topics": {t: v.get("status") for t, v in sorted((e.get("topics") or {}).items())}}
           for e in p["release"]]
    return {"action": ACTION, "stale_days": stale_days, "release": rel,
            "open_batches": sorted(p["open_batches"]), "going": sorted(going)}


def release_plan(root, stale_days=None):
    """What `pool-release --delete` would remove, and a confirm token when
    there is something and no batch is open - nothing touched."""
    stale_days = _stale(stale_days)
    pr = _pr()
    p = _plan(root, stale_days)
    going = _going(root)
    facts = _facts(p, going, stale_days)
    fp = _digest(facts)
    opened = sorted(set(going) | set(p["open_batches"]))
    why = None
    if opened:
        why = ("Открыт батч (" + ", ".join(opened) + ") - пул не освобождается, пока он идёт: "
               "стадия исходников пишет тот же index.json.")
    elif not p["release"]:
        why = "Освобождать нечего: ни у одного исходника все темы не закончены."
    out = {"action": ACTION, "ok": why is None, "why": why,
           "command": _command(stale_days, "--delete"), "at": p["at"],
           "stale_days": p.get("stale_days"),
           "release": [_entry(e) for e in p["release"]], "totals": _sum(p["release"]),
           "kept": _sum(p["keep"]), "orphan": _sum(p["orphan"]),
           "open_batches": opened, "journal": _journal(root, pr), "by": WRITE_BY, "via": VIA,
           "recorded_by": True, "rows": [], "fingerprint": fp, "confirm": None,
           "expires_in_s": None}
    if why is None:
        try:
            pr.delete(p, Path(root), now=FACTORY_KW.get("now"), by=WRITE_BY, via=VIA,
                      dry_run=True, rows=out["rows"])
        except RuntimeError as e:
            raise BatchFault(409, "batch_open", "Фабрика отказала: открыт батч - исходники не "
                                                "тронуты.", [f"pool_release.delete: {e}"]) from e
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e) from e
        out.update(confirm=_issue(root, ACTION, KEY, fp, {"stale_days": stale_days}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def release(root, token):
    """The confirmed release: the token spent, no batch open, the same plan
    (else `check_changed`), then the factory's `delete(p, root, by, via)`."""
    pr = _pr()
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Пул уже освобождается - подождите и запросите план "
                                      "заново.",
                         [f"the pool lock was not free in {WRITE_WAIT} s; the token is not spent"])
    try:
        got = _spend(root, ACTION, KEY, token)
        stale_days = got["bound"].get("stale_days")
        going = _going(root)
        if going:
            raise BatchFault(409, "batch_open", "Открыт батч (" + ", ".join(going) + ") - "
                                                "исходники не тронуты; освобождение - после "
                                                "его закрытия.",
                             ["factory.open_batches (runlog batch-active) is not empty"])
        p = _plan(root, stale_days)
        if _digest(_facts(p, going, stale_days)) != got["fingerprint"]:
            if p["open_batches"]:
                raise BatchFault(409, "batch_open", "Открыт батч (" + ", ".join(
                    p["open_batches"]) + ") - исходники не тронуты.",
                                 ["pool_release.plan: open_batches is not empty"])
            if not p["release"]:
                raise BatchFault(409, "refused", "Освобождать уже нечего - исходники не "
                                                 "тронуты.", ["the plan's release is empty now"])
            raise BatchFault(409, "check_changed", "Пул или темы изменились с момента плана - "
                                                   "ничего не удалено; посмотрите план заново.",
                             [f"the fingerprint of the {ACTION} plan differs from the plan's"])
        rows = []
        try:
            gone = pr.delete(p, Path(root), now=FACTORY_KW.get("now"), by=WRITE_BY, via=VIA,
                             rows=rows)
        except RuntimeError as e:
            raise BatchFault(409, "batch_open", "Фабрика отказала: открыт батч - исходники не "
                                                "тронуты.", [f"pool_release.delete: {e}"]) from e
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e, "Фабрика ответила ошибкой посреди удаления - посмотрите "
                             "shared/footage/release-log.jsonl, прежде чем повторять.") from e
    finally:
        _WRITE.release()
    done = [e for e in p["release"] if e["video_id"] in set(gone)]
    return paths.clean({"action": ACTION, "written": True, "by": WRITE_BY, "via": VIA,
                        "recorded_by": True, "stale_days": stale_days, "deleted": list(gone),
                        "totals": _sum(done), "journal": _journal(root, pr), "rows": rows},
                       root)

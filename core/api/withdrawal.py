"""CC-0107: taking a video off for good, on the user's word - what
`runlog pool-release --record-withdrawal <channel>/<batch>/<slug> --answer
"..."` does. Only through the factory's own functions
(`shared/runlog/pool_release.py`, CF-0358, `factory.pool_release`):

    Resolver.topic      the video's topic (the batch's 05, a rebuild through
                        the slug's topic in the other batches)
    read_journal        the rows of `shared/footage/release-log.jsonl`
    topic_status        what the records say of the topic (published,
                        withdrawn, accepted, rejected - and the evidence)
    open_batch_keys     the batches open now (what the plan names as a blocker)
    plan(extra_withdrawn)   the pool's what-if, `--withdrawn` - nothing deleted
    check_answer        CF-0720: the answer's rule alone (`{ok, slug, why}`)
    record_withdrawal   the one writer: the `withdrawn` row, appended (CF-0720:
                        `by` / `via` on the row)

**Where it lives.** The factory's key is `CHANNEL/BATCH/SLUG` and its
Resolver reads it as `pipeline/<channel>/<batch>` - the batch directory of
the acceptance routes (`/api/batches/{channel}/{batch_id}/videos/{slug}/...`,
a rebuild as `rebuilds/<ts>`), not a placed note of `publish/` (a video
taken off may never have reached it). So: `POST
/api/batches/{channel}/{batch_id}/videos/{slug}/withdraw/plan` and
`.../withdraw`.

**The plan** (`withdraw_plan`, nothing written): the entry, its topic, the
topic's status now and with the withdrawal (`topic_status`), the withdrawals
of this entry already recorded, and the pool's what-if - `plan()` with and
without `extra_withdrawn=[entry]` (the same open batches for both): the
sources the withdrawal lets go (`frees` - they go only when `pool-release
--delete` runs, the monthly archive; nothing leaves the disk here) and the
sources of the topic still kept, with what keeps them. No token when the
entry was already withdrawn or its topic does not resolve (the row would
name no topic - the pool would not move). A confirm token (action
`video_withdraw`, 120 s, single use) is bound to the entry.

**The confirm** (`withdraw`): the user's word is required - `answer`, in
Russian (a Cyrillic letter), naming the video (the factory's rule: a
withdrawal is filed only under the video the user named). Both are checked
before the token is spent: the Russian by the API, the name by the
factory's own `check_answer` (not ok: 422 `answer_without_name`, its `why`
in the details). Then the token spent, the plan again (anything different:
`check_changed`), and `record_withdrawal(root, entry, answer, by="user",
via="center")` - the user's words as they are, who and from where on the
row (CF-0720).

**An open batch** does not refuse it: the journal is read by `pool-release`
alone (a batch's stages never read it), and `--delete` itself refuses while
a batch is open; the plan names the open batches that keep a source.

Every refusal is a `BatchFault` (`{message, code, details}`), every answer
goes out through `api/paths.clean`. `FACTORY_KW["now"]` is the factory's
clock (a datetime) - empty in production; the tests put a fixed one there.
"""
import re
import threading

from . import batches, factory, paths
from .batches import SAFE_NAME, BatchFault, _digest, _issue, _spend, batch_dir

ACTION = "video_withdraw"
ACTIONS = {ACTION: ("план снятия ролика", "ролик не снят", "снятия ролика")}
batches.register_actions(ACTIONS)
#: The event `record_withdrawal` writes (`{"event": "withdrawn", ...}`).
EVENT = "withdrawn"
WRITE_BY, VIA = "user", "center"
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
#: One withdrawal at a time; how long a confirm waits for the one going.
WRITE_WAIT = 30.0
_WRITE = threading.Lock()
#: The factory's own injection points - empty in production.
FACTORY_KW = {}


def _pr():
    return factory.pool_release()


def _broken(e):
    return BatchFault(500, "factory_broken", "Фабрика ответила ошибкой - ролик не снят; "
                                             "посмотрите shared/footage/release-log.jsonl.",
                      [f"{type(e).__name__}: {e}"])


def _entry(root, channel, batch_id, slug):
    """The batch directory (404 `unknown_batch`) and the factory's key."""
    batch_dir(root, channel, batch_id)
    if not SAFE_NAME.match(slug or "") or slug in (".", ".."):
        raise BatchFault(404, "unknown_video", f"Ролика «{slug}» в батче «{channel}/{batch_id}» "
                                               f"нет.", [f"{slug!r}: not a slug"])
    return f"{channel}/{batch_id}/{slug}"


def _ids(entries):
    return sorted(e["video_id"] for e in entries)


def _check(root, entry):
    """(out, facts): what the factory says of the entry, and the pool's what-if."""
    pr = _pr()
    now = FACTORY_KW.get("now")
    try:
        topic = pr.Resolver(root).topic(entry)
        before = [r for r in pr.read_journal(root)
                  if r.get("event") == EVENT and r.get("entry_id") == entry]
        default = pr.factory_root()
        status, _u = pr.topic_status(root, now, default_root=default)
        after, _u = pr.topic_status(root, now, extra_withdrawn=(entry,), default_root=default)
        keys = pr.open_batch_keys(root)
        base = pr.plan(root, now=now, open_keys=keys)
        what = pr.plan(root, now=now, extra_withdrawn=(entry,), open_keys=keys)
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e) from e
    was = set(_ids(base["release"]))
    frees = [{k: e.get(k) for k in ("video_id", "files", "bytes")}
             for e in what["release"] if e["video_id"] not in was]
    kept = [{"video_id": e["video_id"], "blocked_by": e.get("blocked_by") or [],
             "open_batches": e.get("open_batches") or [],
             "topics": {t: v.get("status") for t, v in (e.get("topics") or {}).items()}}
            for e in what["keep"] if topic and topic in (e.get("topics") or {})]
    why = None
    if before:
        why = (f"{entry} уже снят окончательно ({before[-1].get('at')}) - записывать нечего.")
    elif not topic:
        why = (f"Тема ролика {entry} не находится (ни 05-video-editor.json батча, ни другие "
               f"батчи её не называют) - снятие ни на что не повлияет; ролик не снят.")
    out = {"ok": why is None, "why": why, "entry_id": entry, "topic_id": topic,
           "status": status.get(topic) if topic else None,
           "status_after": after.get(topic) if topic else None,
           "withdrawn_before": before, "frees": frees,
           "frees_bytes": sum(e.get("bytes") or 0 for e in frees), "kept": kept,
           "open_batches": what.get("open_batches") or [],
           "journal": paths.rel(root, pr.journal_path(root)),
           "by": WRITE_BY, "via": VIA, "deletes_now": False,
           "line": ("Сейчас с диска ничего не уходит: исходники уберёт pool-release --delete "
                    "(месячный архив), когда тема закончена.")}
    facts = {"action": ACTION, "entry": entry, "topic": topic, "before": before,
             "status": out["status"], "status_after": out["status_after"],
             "frees": _ids(frees), "kept": kept, "ok": out["ok"]}
    return out, facts


def withdraw_plan(root, channel, batch_id, slug):
    """What «снять ролик окончательно» would write, and a confirm token bound
    to the entry when it says ok - nothing written."""
    entry = _entry(root, channel, batch_id, slug)
    out, facts = _check(root, entry)
    fp = _digest(facts)
    out = dict(out, action=ACTION, fingerprint=fp, confirm=None, expires_in_s=None)
    if out["ok"]:
        out.update(confirm=_issue(root, ACTION, entry, fp, {"entry": entry}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def _words(answer):
    """The user's answer as it is recorded - the words, stripped."""
    text = (answer or "").strip()
    if not text or not CYRILLIC.search(text):
        raise BatchFault(422, "answer_required", "Снять ролик окончательно можно только вашим "
                                                 "словом: напишите по-русски, что снимаете, и "
                                                 "назовите ролик.",
                         ["answer: empty or without a Cyrillic letter; the token is not spent"])
    return text


def _answer_check(pr, entry, words):
    """The factory's own rule for the answer - `check_answer` (no root, nothing
    written)."""
    try:
        got = pr.check_answer(entry, words)
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e) from e
    if not got.get("ok"):
        raise BatchFault(422, "answer_without_name", f"Ответ не называет ролик «"
                                                     f"{entry.rsplit('/', 1)[-1]}» - снятие "
                                                     f"записывается только под названным "
                                                     f"роликом.",
                         [f"check_answer: {got.get('why')}", "the token is not spent"])


def withdraw(root, channel, batch_id, slug, token, answer):
    """The confirmed withdrawal: the user's Russian answer naming the video
    (checked before the token is spent), the token spent, the same plan
    (else `check_changed`), then `record_withdrawal(root, entry, answer, by,
    via)`."""
    entry = _entry(root, channel, batch_id, slug)
    pr = _pr()
    words = _words(answer)
    _answer_check(pr, entry, words)
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другое снятие ролика - подождите и запросите план "
                                      "заново.",
                         [f"the withdrawal lock was not free in {WRITE_WAIT} s; the token is "
                          f"not spent"])
    try:
        got = _spend(root, ACTION, entry, token)
        out, facts = _check(root, got["bound"]["entry"])
        if _digest(facts) != got["fingerprint"]:
            if not out["ok"]:
                raise BatchFault(409, "refused", out["why"],
                                 ["the check changed since the plan", out["why"]])
            raise BatchFault(409, "check_changed", "Проверка изменилась с момента плана - ролик "
                                                   "не снят; посмотрите план заново.",
                             [f"the fingerprint of the {ACTION} plan differs from the plan's"])
        try:
            row = pr.record_withdrawal(root, entry, words, now=FACTORY_KW.get("now"),
                                       by=WRITE_BY, via=VIA)
        except ValueError as e:
            raise BatchFault(422, "answer_without_name", str(e), [f"ValueError: {e}"]) from e
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e) from e
        return paths.clean({"action": ACTION, "entry_id": entry, "written": True, "row": row,
                            "by": WRITE_BY, "via": VIA,
                            "journal": out["journal"], "frees": out["frees"],
                            "status_after": out["status_after"]}, root)
    finally:
        _WRITE.release()

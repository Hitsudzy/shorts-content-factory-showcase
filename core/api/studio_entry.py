"""CC-0074: entering what Studio was read to say - the write half of the
statistics (`api/analytics.py` stays read only). Only through the factory's
own functions (`api/factory.py` `studio_read`), nothing of the API's own on
top:

    agents/analyst/studio_read.py   parse_read (checks and parses, writes
                                    nothing), record(by, via) (CF-0588, CF-0692)
    agents/analyst/metrics_store.py read_studio, latest_studio - what is stored

**The plan** (`record_plan`): `parse_read(read, channel, root)` - the read
JSON exactly as `studio_read.py parse` takes it (`{channel, read_at, hook,
videos: [{video_id | url, title, period_text, lines, viewed?, swiped?}]}`, see the factory's docstring); its refusal
(`ReadError`) is 422 `read_refused` with the factory's line, nothing written.
The plan is what the factory recognised, as it returns it (per video: hook,
viewed_pct, swiped_pct, period_text, note, warnings, raw_lines ...; the
videos without an id, the read's warnings), each video
with its last stored read (`stored`: `metrics_store.latest_studio`, null when
none). Whether a read will be added, replaced or left unchanged the factory
says only by writing (`merge_studio`'s counts) - the confirm's answer carries
them; the plan does not guess them. A confirm token (`batches` store, action
`studio_read_record`, 120 s, single use) is bound to the channel and the read.

**The confirm** (`record`): the token spent, `parse_read` again on the read the
token is bound to; its fingerprint covers the parse and the bytes of the
channel's `studio.jsonl` and `studio_visits.jsonl` - a
channel config, a journal or a store that changed since the plan is
`check_changed`, nothing written. Then `record(parsed, by="user",
via="center")` - `recorded_by` / `via` in every studio.jsonl row and the visit
line. One Studio write at a time.

**The commit** (CC-0156, the factory's decision of 22.10): the record ends in
one commit of what it changed of the channel's `studio.jsonl` and
`studio_visits.jsonl`, `Cc-Channel: <cid>` / `Cc-Action:
studio_read_record` (`api/root_commit.py`: git's word on the files before and
after, only the files whose bytes moved - a batch writes `analytics/` too).
git's refusal is 409 `refused` (`commit_refused`), the record stays in the
tree, nothing staged; a root that is not a git work tree commits nothing.

Every refusal is a `BatchFault` (`{message, code, details}`). `FACTORY_KW`
holds the factory's clock (`now`, `record`'s `recorded_at`) - empty in
production; the tests put a fixed one there.
"""
import hashlib
import threading

from . import analytics, batches, factory, root_commit
from .batches import BatchFault, _channel, _digest, _issue, _spend

ACTION = "studio_read_record"
ACTIONS = {ACTION: ("план записи чтения Studio", "чтение Studio не записано",
                    "записи чтения Studio канала")}
batches.register_actions(ACTIONS)
#: Who the center writes (`publish.WRITE_BY`) and from where.
WRITE_BY = "user"
VIA = "center"
#: One Studio write at a time; how long a confirm waits for the one going.
WRITE_WAIT = 30.0
_WRITE = threading.Lock()
#: The factory's own injection points - empty in production.
FACTORY_KW = {}


def _sr():
    return factory.studio_read()


def _fp(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _store_bytes(sr, cid, st):
    """sha256 of the channel's files `record` writes (None: not there yet)."""
    ms = sr.store
    return {"studio": _fp(ms.channel_dir(cid, st) / ms.STUDIO),
            "visits": _fp(ms.channel_dir(cid, st) / ms.VISITS)}


def _scope(root, sr, cid, st):
    """The files `record` writes, from the root (CC-0156)."""
    ms = sr.store
    return root_commit.rels(root, [ms.channel_dir(cid, st) / ms.STUDIO,
                                   ms.channel_dir(cid, st) / ms.VISITS])


def _parse(root, cid, read):
    """`parse_read` - the factory's refusal 422, an unreadable journal 409."""
    sr = _sr()
    jr = factory.collect().journal()
    analytics._journal(root)
    try:
        return sr.parse_read(read, cid, root)
    except sr.ReadError as e:
        raise BatchFault(422, "read_refused", str(e), [f"ReadError: {e}"]) from e
    except (jr.JournalError, ValueError) as e:
        raise analytics._fault("journal_unreadable", e) from e
    except OSError as e:
        raise analytics._fault("store_unreadable", e) from e


def _check(root, cid, read):
    """(parsed, facts): the parse and the bytes of the store it would go into."""
    sr = _sr()
    st = analytics._store(root)
    parsed = _parse(root, cid, read)
    return parsed, {"action": ACTION, "channel": cid, "parsed": parsed,
                    "store": _store_bytes(sr, cid, st), "by": WRITE_BY, "via": VIA}


def record_plan(root, channel, read):
    """What «записать» would write (parse_read, nothing written) and a confirm
    token bound to the channel and the read."""
    cid = _channel(root, channel)
    if not isinstance(read, dict):
        raise BatchFault(422, "read_refused", "Чтение Studio - не JSON-объект.",
                         ["the read is not a JSON object"])
    parsed, facts = _check(root, cid, read)
    ms, st = analytics._ms(), analytics._store(root)
    reads = analytics._read(ms.read_studio, cid, st)
    videos = [dict(v, stored=analytics._read(ms.latest_studio, reads, v["video_id"]))
              for v in parsed["videos"]]
    fp = _digest(facts)
    return dict(parsed, videos=videos, action=ACTION, channel=cid, ok=True, why=None,
                recorded_by=WRITE_BY, via=VIA, fingerprint=fp,
                confirm=_issue(root, ACTION, cid, fp, {"read": read}),
                expires_in_s=int(batches.CONFIRM_TTL))


def record(root, channel, token):
    """The confirmed record: the token spent, the parse and the store the same
    as the plan's (else `check_changed`), then `record(by=user, via=center)`."""
    cid = _channel(root, channel)
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись чтения Studio - подождите и "
                                      "запросите план заново.",
                         [f"the Studio write lock was not free in {WRITE_WAIT} s; the token "
                          f"is not spent"])
    try:
        got = _spend(root, ACTION, cid, token)
        parsed, facts = _check(root, cid, got["bound"]["read"])
        if _digest(facts) != got["fingerprint"]:
            raise BatchFault(409, "check_changed", "Чтение или хранилище изменились с момента "
                                                   "плана - чтение Studio не записано; "
                                                   "посмотрите план заново.",
                             ["the fingerprint of parse_read + studio.jsonl + "
                              "studio_visits.jsonl differs from the plan's"])
        sr = _sr()
        scope = _scope(root, sr, cid, analytics._store(root))
        before = root_commit.snap(root, scope)
        try:
            res = sr.record(parsed, root=root, now=FACTORY_KW.get("now"), by=WRITE_BY, via=VIA)
        except sr.ReadError as e:
            raise BatchFault(422, "read_refused", str(e), [f"ReadError: {e}"]) from e
        except sr.store.StoreError as e:
            raise analytics._fault("store_unreadable", e) from e
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Фабрика ответила ошибкой посреди записи "
                                                    "чтения Studio - посмотрите analytics/, "
                                                    "прежде чем повторять.",
                             [f"{type(e).__name__}: {e}"]) from e

        def message():
            st_ = res["studio"] if isinstance(res.get("studio"), dict) else {}
            counts = ", ".join(f"{k} {v}" for k, v in st_.items()
                               if isinstance(v, int) and not isinstance(v, bool))
            return (f"Studio {cid}: чтение {parsed['read_at']} записано ({WRITE_BY}, {VIA})",
                    f"CC-0156: запись чтения Studio из центра (studio_entry.record, "
                    f"studio_read.record).\nХук: {parsed['hook']}"
                    + (f"\nStudio: {counts}" if counts else ""))
        sha, committed = root_commit.commit_changed(root, cid, ACTION, scope, before, message,
                                                    "Чтение Studio записано")
        return {"action": ACTION, "channel": cid, "written": True,
                "read_at": parsed["read_at"], "hook": parsed["hook"],
                "recorded_by": WRITE_BY, "via": VIA, "studio": res["studio"],
                "visit_logged": bool(res["visit_logged"]),
                "commit": sha, "committed": committed}
    finally:
        _WRITE.release()

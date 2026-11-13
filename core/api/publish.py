"""CC-0064: the publication side, read only - the queue of slots, a placed
card and its Studio fields, the pause, the publication holds, the API-upload
switch, the rotation. Only through the factory's own functions
(`api/factory.py`), nothing of the API's own on top:

    agents/publisher/publish_queue.py   queue_channels, slot_config, table,
                                        occupants, next_free, waiting,
                                        pause_state, tomorrow, label, msk_day
                                        (CF-0587: `publish_queue.py show / next /
                                        tomorrow`)
    agents/publisher/channel_pause.py   status, history, open_row; gate - the
                                        line of a registry that does not read
                                        (CF-0569)
    agents/publisher/publish_card.py    placeable / card_status (CF-0747), mark_of, view (`publish_card.py
                                        show`), channel_config, batch_video
                                        (CF-0017)
    agents/publisher/publish_note.py    sections, title_and_description
    agents/publisher/studio_fields.py   locate, prepare, form_fields, streak
                                        (CF-0018)
    agents/publisher/upload_records.py  uploads - the journal `publish/uploads.json`
    agents/publisher/api_switch.py      status, channel_state, warnings, state_path
                                        (CF-0607)
    agents/compliance-checker/scripts/publication_hold.py
                                        read_ledger, open_holds (CF-0318);
                                        check_sign, sign_hold, HoldSignError
                                        (CF-0687, CC-0070)
    shared/runlog/publish_layout.py     card_batch - the note's «Батч» line
    rotation/rotate.py                  distribution_report (with its
                                        awaiting_material, CF-0139/CF-0149) -
                                        what `rotate.py status` prints

(the publisher's modules as `shared/factory_state.py` loads them - one copy
each; the other three by path in `api/factory.py`).

**Nothing here writes.** Every route is a GET. The writers of these modules
(`set_pause`, `clear_pause`, `set_switch`, `place`, `build`, `record`,
`assign`, `reject`, `refuse`, `write_ledger`, `resolve_rights_only`, `merge`),
the model askers (`ask_draft`, `note_claims.check_note`), the notifications
(`tomorrow_notify`, `notify_upload`, `notify_accept`, `shared/notify.py`) and
the upload (`upload.py`) are never named - `tests/test_cc_api_publish.py`
walks this file's names. `studio_fields.prepare` is the reading half of the
Studio path (`prepare`, not `record`): it reads the card, the acceptance log,
the holds, the pause registry and the journal, and writes nothing.

**The queue** (`queue`): the channel's `publisher.slot` as
`slot_config` reads it (times, zone, per day, lead); the slots of `days` days
from today in the channel's zone (`table`: taken by which slug), the nearest
free one past the lead (`next_free`), the videos waiting in `_queue/` and `_reserve/`
(`waiting`), the pause (`pause_state`: the reason and the notices of an
expired pause), tomorrow's line for the orchestrator (`tomorrow`: ok, an empty
slot, paused, no queue - its exit code beside), and every video holding a day
(`occupants`, with where it was found: the day folder or the journal row and
its video id). A channel with no slot: `slot: null`, the slots empty,
`tomorrow` says so. A slot block or a journal that does not read: 409
`queue_broken` with the factory's line. The overview (`queues`) is one line of
the same per channel `queue_channels` names.

**Two videos of one name** (CC-0182, CF-0920): `<slug>~<batch>` is a file's name, never an
address: `batch_id` next to `slug` names the video (`named_note`, `publish_layout.of_batch`);
no batch with two in one place is 409 `namesakes` naming the batches (`namesakes_fault`), never
the last of them.

**A placed card** (`note`): `publish/<channel>/<day|_queue|_reserve>/<slug>.md` as
`studio_fields.locate` finds it (the day picks one of two notes of one name;
with none, the one place of the name not in the upload journal - two or more
such places are 404 `unknown_note` asking for the day, CF-0857), through the one path guard (`factory.contained`); the
factory's short view (`publish_card.view` - what `publish_card.py show`
prints), ready and why (`placeable`: ready or ruled, CF-0747), title and description, the form's
questions off `## Настройки` (`form_fields`), and the Studio fields as
`prepare` gives them - or, when it refuses (the card not ready, no
acceptance, a hold, a pause, already in the journal, no slot, a past slot),
`studio: null` and its line in `studio_refusal`. The batch the note names
(`publish_layout.card_batch`, its «Батч» line) is read with
`publish_card.batch_video`: its script and topic, and the routes of
`api/videos.py` for that video (`card_url`, `videos_url`) - the batch's card is
not parsed twice here.

**The publisher block** (`config`): `publish_card.channel_config` - the
channel's `publisher` block, or its refusal as `error` (the card's templates
live there).

**Studio streak** (`studio`): `studio_fields.streak` over the journal - the
Studio videos in a row with no hand edit, the 2.0 goal (5).

**The pause** (`pause`): `channel_pause.status` (free / paused / expired and
its line), the open row (`open_row`), every row (`history`). A registry that
does not read is 409 `pause_unreadable` - its message is the factory's own
fail-closed line (`gate`: the pause for every channel).

**The holds** (`holds`): `publication_hold.open_holds` (unresolved and
unsigned - what the user is asked to sign) and the ledger as `read_ledger`
reads it (`rows`); a ledger that does not read: `problem` - the factory's line,
both lists empty, fail closed (`is_held` holds every video then). Each row
carries `signable` and `sign_refusal` - `check_sign` of its hold (CC-0070:
whether the center may sign it, the factory's refusal if not).

**The hold's signature** (CC-0070, the user's decision of 11.10, CF-0687) is
the one write on the ledger: `hold_sign_plan` (`check_sign`, nothing written)
and `hold_sign` (`check_sign` again, then `sign_hold(user, note,
via="center")`). The refusals are the factory's (`HoldSignError`: its code,
its Russian line).

**The API-upload switch** (`api_upload`): `api_switch.status` (every channel,
or the one asked: on, its line, history) and `warnings` - what enabling it
would warn about now (the OAuth app's mode, the tick's timer, the token's
status - `publisher_auth.status` reads the token's file, never the network).

**The rotation** (`rotation`): `rotate.distribution_report` for the channel
with the root's ledger (`rotation/ledger/`) and batches (`pipeline/`) - the
eligible pairs, K, the window's counts and spread, the rejections, the
production gap and `awaiting_material` (the topics a refusal closed and
whether what they wait for arrived - `pool.census` of the root's pool). The
channel's config and the pattern vocabulary are the ones `rotate.py` reads
(its own checkout - the factory root in production).

**The commit** (CC-0153, the factory's report of 21.10): every confirmed
write of this file and of `api/publish_net.py` (but the card's build - its
file is under the gitignored `pipeline/` - and the API-upload switch - under
the gitignored `schedule/`) ends in one commit of what it changed in the root
(`_confirm(commit=...)`: git's word on the write's scope before and after,
`publish_stash.commit_paths`, the `Cc-Channel` / `Cc-Action: <action>`
trailers), so the production tree stays clean.

Every refusal is a `BatchFault` (`{message, code, details}`); the message is
the factory's line where the factory has one (an English line of an agent is
shown as it is - the API does not translate). `FACTORY_KW` is the factory's
own injection points (`now`, `env_file`, `environ`, `timer`) - empty in
production; the tests put a clock, a stand-in `.env` and environment there.
"""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import batches, factory, paths, root_commit
from .batches import (PIPELINE_DIR, SAFE_NAME, BatchFault, _channel, _digest, _issue, _spend,
                      batch_dir)

PUBLISH_DIR = "publish"
JOURNAL = "uploads.json"            # = upload_records / studio_fields `_paths`
HOLDS = "publication-holds.json"    # = publication_hold.LEDGER_REL
ROTATION_DIR, LEDGER_DIR = "rotation", "ledger"
DAYS_DEFAULT = 14                   # = `publish_queue.py show --days`
DAYS_MAX = 120                      # = publish_queue.HORIZON_DAYS
NOTE_SUFFIX = ".md"
ACCEPTANCE_LOG = "acceptance-log.json"  # = upload_gate / studio_fields `_paths`, publish_card

#: The factory's own injection points - empty in production.
FACTORY_KW = {}

#: `publish_queue.tomorrow`'s exit codes, by name.
def _tomorrow_states(pq):
    return {pq.EXIT_OK: "ok", pq.EXIT_EMPTY: "empty", pq.EXIT_ERROR: "error",
            pq.EXIT_PAUSED: "paused"}


# ---------------------------------------------------------------- the factory's modules
def _col():
    return factory.collect()


def _pq():
    return _col().queue()


def _cp():
    return _col().pause()


def _rel(root, p):
    """CC-0097: relative to the root, `.../<its last part>` outside it - never
    the absolute path (`api/paths.py`)."""
    return paths.rel(root, p)


def _now(pq):
    return pq.now_utc(FACTORY_KW.get("now"))


def _iso(at):
    return factory.utc_iso(at.timestamp())


def _contained(root, *parts, code, what):
    p = factory.contained(root, *parts)
    if p is None:
        raise BatchFault(409, code, f"{'/'.join(parts)} leads out of the factory root",
                         [f"{what}: {'/'.join(parts)} is a link out of {root} the lock does "
                          f"not declare (factory.contained)"])
    return p


def _journal(root):
    return _contained(root, PUBLISH_DIR, JOURNAL, code="queue_broken", what="the journal")


# ---------------------------------------------------------------- the queue
def _slot(cfg):
    return {"channel": cfg["channel"], "times": [t.strftime("%H:%M") for t in cfg["times"]],
            "tz": cfg["tz"], "per_day": cfg["per_day"],
            "lead_hours": cfg["lead"].total_seconds() / 3600}


def _at(pq, at, cfg):
    return {"at": _iso(at), "local": at.isoformat(), "label": pq.label(at, cfg),
            "day": pq.msk_day(at)}


def _queue_fault(e):
    return BatchFault(409, "queue_broken", str(e), [f"{type(e).__name__}: {e}"])


def _head(pq, root, cid, now, jpath):
    """What the overview and the channel's queue share: the slot, the pause,
    tomorrow, the next free slot, the waiting ones."""
    cfg = pq.slot_config(cid, root)
    reason, notices = pq.pause_state(cid, root, now)
    code, line = pq.tomorrow(cid, root, now, jpath)
    out = {"channel": cid, "slot": _slot(cfg) if cfg else None, "paused": reason,
           "pause_notices": list(notices),
           "tomorrow": {"code": code, "state": _tomorrow_states(pq).get(code, "error"),
                        "line": line},
           "next_free": None, "next_free_error": None,
           "waiting": sorted(pq.waiting(cid, root))}
    if cfg is not None:
        try:
            out["next_free"] = _at(pq, pq.next_free(cid, root, now, jpath, cfg), cfg)
        except pq.QueueError as e:
            out["next_free_error"] = str(e)
    return cfg, out


def _withdrawn(jr, rows, cid):
    """CC-0179 (CF-0918): the channel's journal rows taken off the feed into the
    копилка's reserve - in Studio, no slot, no day; the queue does not count
    them, so they are named beside it."""
    return [{"slug": r.get("slug"), "video_id": r.get("video_id"), "url": r.get("url"),
             "batch_id": r.get("batch_id"), "note": r.get("note"), "withdrawn": r["withdrawn"]}
            for r in rows if r.get("channel") == cid and jr.is_withdrawn(r)
            and not r.get("removed_at")]


def queue(root, channel, days=None):
    """One channel's queue - `publish_queue.py show` / `next` / `tomorrow`;
    CC-0179: `withdrawn` beside it."""
    cid = _channel(root, channel)
    pq = _pq()
    now = _now(pq)
    days = int(days or DAYS_DEFAULT)
    jpath = _journal(root)
    try:
        cfg, out = _head(pq, root, cid, now, jpath)
        slots, occupants = [], []
        if cfg is not None:
            nxt = (out["next_free"] or {}).get("at")
            for r in pq.table(cid, root, now, days, jpath, cfg):
                slot = _at(pq, r["at"], cfg)
                slots.append(dict(slot, taken_by=r["taken_by"], next_free=slot["at"] == nxt))
        for o in pq.occupants(cid, root, jpath):
            occupants.append({"slug": o["slug"], "day": o["day"],
                              "at": _iso(o["at"]) if o["at"] else None,
                              "sources": list(o["sources"])})
    except pq.QueueError as e:
        raise _queue_fault(e) from e
    jr = _col().journal()
    try:
        withdrawn = _withdrawn(jr, jr.uploads(jpath), cid)
    except (jr.JournalError, ValueError) as e:
        raise BatchFault(409, "journal_unreadable", str(e), [f"{type(e).__name__}: {e}"]) from e
    return dict(out, as_of=_iso(now), days=days, journal=_rel(root, jpath),
                slots=slots, occupants=occupants, withdrawn=withdrawn)


def queues(root):
    """Every channel `queue_channels` names, one line each."""
    pq = _pq()
    now = _now(pq)
    jpath = _journal(root)
    rows = []
    for cid in pq.queue_channels(root):
        try:
            _cfg, out = _head(pq, root, cid, now, jpath)
            out["error"] = None
        except pq.QueueError as e:
            out = {"channel": cid, "slot": None, "paused": None, "pause_notices": [],
                   "tomorrow": None, "next_free": None, "next_free_error": None,
                   "waiting": [], "error": str(e)}
        rows.append(out)
    return {"as_of": _iso(now), "channels": rows}


# ---------------------------------------------------------------- the pause
def pause(root, channel):
    """`channel_pause.status` / `open_row` / `history` of the channel."""
    cid = _channel(root, channel)
    cp = _cp()
    now = _now(_pq())
    try:
        st = cp.status(cid, root, now)
        hist = cp.history(cid, root)
        row = cp.open_row(cid, root)
    except cp.PauseError as e:
        reason, _notice = cp.gate(cid, root, now)
        raise BatchFault(409, "pause_unreadable", reason or str(e),
                         [f"PauseError: {e}"]) from e
    return {"channel": cid, "as_of": _iso(now), "state": st["state"], "line": st["line"],
            "row": st["row"], "open_row": row, "history": hist,
            "registry": _rel(root, cp.registry_path(root))}


# ---------------------------------------------------------------- the holds
def holds(root, channel=None):
    """`publication_hold.open_holds` and `read_ledger`; each row with
    `signable` / `sign_refusal` as `check_sign` says them (CC-0070)."""
    cid = _channel(root, channel) if channel else None
    ph = factory.publication_hold()
    p = _contained(root, PUBLISH_DIR, HOLDS, code="holds_unreadable", what="the hold ledger")
    ledger, problem = ph.read_ledger(root=root, path=p)
    rows = [r for r in ledger.get(ph.LEDGER_KEY) or [] if isinstance(r, dict)]
    if cid:
        rows = [r for r in rows
                if factory.resolve_channel(root, str(r.get("channel") or "")) == cid]
    open_, open_problem = ph.open_holds(root=root, path=p, channel=cid)
    return {"channel": cid, "path": _rel(root, p), "exists": p.is_file(),
            "problem": problem or open_problem, "open": _signable_rows(ph, p, open_),
            "rows": _signable_rows(ph, p, rows)}


# ---------------------------------------------------------------- the released holds
#: CC-0169: the window of `released_holds` - days back from now, and how many rows.
RELEASED_DAYS, RELEASED_DAYS_MAX = 14, 90
RELEASED_LIMIT, RELEASED_LIMIT_MAX = 50, 200
#: `shared/runlog/scene_holds` (CF-0846): its keys on a ledger row and its code.
SCENE_RELEASE, SCENE_REOPENED, RELEASE_CODE_KEY = ("scene_release", "scene_release_reopened",
                                                   "resolved_reason_code")
SCENE_CODE = "flagged_scene_not_in_script"


def _moment(s):
    """A UTC ISO string as an aware datetime; None when it does not parse."""
    if not isinstance(s, str) or not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _strs(v):
    return [str(x) for x in v if x is not None] if isinstance(v, list) else []


def _scene_words(scenes, topic):
    return ", ".join(factory.short_scene(s, topic) for s in scenes)


def _release(row):
    """CC-0169: what lifted the row, or put it back - `{state, at, by, code,
    reason, task, flagged_scenes, script_scenes, scripts, flagged_short,
    script_short, signature_needed, line_ru}`; None for a row that is neither.

    `released`: the row is resolved (`resolved_at`) - by the scene rule
    (`resolved_reason_code` flagged_scene_not_in_script, `scene_release`) or by
    anything else (CF-0420, a later pass). `reopened`: the scene rule lifted it
    and put it back (`scene_release_reopened`) - it stands again, unsigned."""
    topic = row.get("topic_id")
    sr = row.get(SCENE_RELEASE) if isinstance(row.get(SCENE_RELEASE), dict) else {}
    ro = row.get(SCENE_REOPENED) if isinstance(row.get(SCENE_REOPENED), dict) else None
    sig = row.get("signature")
    signed = isinstance(sig, dict) and bool(sig.get("user"))
    if row.get("resolved_at"):
        state, at, reason = "released", row.get("resolved_at"), row.get("resolved_reason")
        code = row.get(RELEASE_CODE_KEY)
        by, task = sr.get("by"), sr.get("task")
        flagged, script, scripts = (_strs(sr.get("flagged_scenes")), _strs(sr.get("script_scenes")),
                                    _strs(sr.get("scripts")))
    elif ro is not None and not signed:
        was = ro.get("was") if isinstance(ro.get("was"), dict) else {}
        state, at, reason, code = "reopened", ro.get("at"), ro.get("why"), None
        by, task = ro.get("by") or was.get("by"), ro.get("task") or was.get("task")
        now_scenes = factory.sensitivity_scenes(row.get("content_sensitivity_check"))
        flagged = (list(now_scenes) if isinstance(now_scenes, list)
                   else [] if now_scenes == factory.WHOLE_TOPIC
                   else _strs(was.get("flagged_scenes")))
        script, scripts = _strs(ro.get("script_scenes")), _strs(was.get("scripts"))
    else:
        return None
    fl, sc = _scene_words(flagged, topic), _scene_words(script, topic)
    if state == "reopened":
        line = (f"Удержание снова стоит: флаг на {fl or 'всей теме'}, в ролике {sc or '?'}, "
                f"нужна подпись")
    elif code == SCENE_CODE:
        line = f"Удержание снято: флаг на {fl or '?'}, в ролике {sc or '?'}, подпись не нужна"
    else:
        line = "Удержание снято" + (f": {reason}" if reason else "")
    return {"state": state, "at": at, "by": by, "code": code, "reason": reason, "task": task,
            "flagged_scenes": flagged, "script_scenes": script, "scripts": scripts,
            "flagged_short": [factory.short_scene(s, topic) for s in flagged],
            "script_short": [factory.short_scene(s, topic) for s in script],
            "signature_needed": state == "reopened", "line_ru": line}


def released_holds(root, channel=None, days=RELEASED_DAYS, limit=RELEASED_LIMIT):
    """CC-0169 (CF-0846): the holds lifted - or lifted and put back by the
    scene rule - in the last `days` days (`at`: `resolved_at`, or
    `scene_release_reopened.at`), newest first, at most `limit`. A row whose
    moment does not parse is kept, last. Read only - `read_ledger`, the
    signable state as `holds` gives it (a reopened row may be signed)."""
    cid = _channel(root, channel) if channel else None
    ph = factory.publication_hold()
    p = _hold_ledger(root)
    ledger, problem = ph.read_ledger(root=root, path=p)
    now = _now(_pq())
    since = now - timedelta(days=days)
    found = []
    for r in ledger.get(ph.LEDGER_KEY) or [] if not problem else []:
        if not isinstance(r, dict):
            continue
        if cid and factory.resolve_channel(root, str(r.get("channel") or "")) != cid:
            continue
        rel = _release(r)
        if rel is None:
            continue
        at = _moment(rel["at"])
        if at is not None and at < since:
            continue
        found.append((at, r, rel))
    found.sort(key=lambda x: (x[0] is not None, x[0] or since), reverse=True)
    kept = found[:limit]
    rows = _signable_rows(ph, p, [r for _, r, _ in kept])
    out = [dict(row, release=rel) for row, (_, _, rel) in zip(rows, kept)]
    return {"channel": cid, "path": _rel(root, p), "exists": p.is_file(), "problem": problem,
            "as_of": _iso(now), "since": _iso(since), "days": days, "limit": limit,
            "total": len(found),
            "released": sum(1 for _, _, x in found if x["state"] == "released"),
            "reopened": sum(1 for _, _, x in found if x["state"] == "reopened"),
            "holds": out}


# ---------------------------------------------------------------- the API-upload switch
def api_upload(root, channel=None):
    """`api_switch.status` (every channel, or one) and `warnings`."""
    cid = _channel(root, channel) if channel else None
    sw = _col().api_switch()
    environ = FACTORY_KW.get("environ")
    now = _now(_pq())
    states = sw.status(root, environ, cid)
    warn, warn_error = None, None
    try:
        warn = sw.warnings(cid, root, FACTORY_KW.get("env_file"), environ, now,
                           FACTORY_KW.get("timer"))
    except Exception as e:                                      # noqa: BLE001
        warn_error = f"{type(e).__name__}: {e}"
    return {"channel": cid, "path": _rel(root, sw.state_path(root, environ)),
            "channels": states, "warnings": warn, "warnings_error": warn_error}


# ---------------------------------------------------------------- the rotation
def rotation(root, channel):
    """`rotate.distribution_report` (with `awaiting_material`) of the channel."""
    cid = _channel(root, channel)
    rt = factory.rotate()
    ledger = _contained(root, ROTATION_DIR, LEDGER_DIR, code="rotation_broken",
                        what="the rotation ledger")
    pipeline = _contained(root, PIPELINE_DIR, code="rotation_broken", what="the batches")
    try:
        report = rt.distribution_report(cid, ledger_dir=ledger, pipeline_dir=pipeline,
                                        root=Path(root))
    except Exception as e:                                      # noqa: BLE001
        status = 409 if isinstance(e, (rt.RotationError, rt.LedgerError)) else 500
        raise BatchFault(status, "rotation_broken", str(e), [f"{type(e).__name__}: {e}"]) from e
    return {"channel": cid, "ledger": _rel(root, ledger), "report": report}


# ---------------------------------------------------------------- the publisher block
def config(root, channel):
    """`publish_card.channel_config` - the channel's `publisher` block."""
    cid = _channel(root, channel)
    pc = _col().card()
    try:
        got, _cfg, pub = pc.channel_config(cid, root)
    except pc.CardError as e:
        return {"channel": cid, "ok": False, "publisher": None, "error": str(e)}
    return {"channel": got, "ok": True, "publisher": pub, "error": None}


# ---------------------------------------------------------------- Studio
def studio(root, channel):
    """`studio_fields.streak` over the journal, and how many of the journal's
    rows name this channel (`rows`, the same `channel` field the streak reads;
    0 with no journal). CC-0179: `withdrawn` - those of them taken off the feed."""
    cid = _channel(root, channel)
    sf, jr = factory.studio_fields(), _col().journal()
    jpath = _journal(root)
    try:
        rows = jr.uploads(jpath)
    except (jr.JournalError, ValueError) as e:
        raise BatchFault(409, "journal_unreadable", str(e), [f"{type(e).__name__}: {e}"]) from e
    return {"channel": cid, "journal": _rel(root, jpath), "journal_exists": jpath.is_file(),
            "rows": sum(1 for r in rows if r.get("channel") == cid),
            "withdrawn": _withdrawn(jr, rows, cid), "streak": sf.streak(rows, cid)}


def _unknown_note(channel, slug, day, line):
    """404 `unknown_note`. CC-0167 (CF-0857): a name with two or more places
    not in the upload journal and no day is `studio_fields.locate`'s line
    naming `--day` - the center's word for it is the request's `day`."""
    if "(--day)" in line:
        line += (" - укажите день: папку, где лежит заметка (YYYY-MM-DD, _queue или _reserve; "
                 "в запросе поле day)")
    return BatchFault(404, "unknown_note", line,
                      [f"{PUBLISH_DIR}/{channel}/{day or '<day>'}/{slug}{NOTE_SUFFIX}"])


def _batch_of(root, pc, lay, note, slug, prefix):
    """The batch the note names (`card_batch`) and its video (`batch_video`)."""
    found = lay.card_batch(note)
    if not found:
        return None
    dirname, bid = found
    out = {"path": f"{dirname}/{bid}", "dir": dirname, "batch_id": bid, "channel": None,
           "slug": None, "script_id": None, "topic_id": None, "card_url": None,
           "videos_url": None, "error": None}
    try:
        d = batch_dir(root, dirname, bid)
        ch, script, video, vslug = pc.batch_video(d, slug)
    except BatchFault as e:
        return dict(out, error=e.message)
    except pc.CardError as e:
        return dict(out, error=str(e))
    base = f"{prefix}/batches/{dirname}/{bid}/videos"
    return dict(out, channel=ch, slug=vslug, script_id=video.get("script_id"),
                topic_id=script.get("topic_id"), videos_url=base,
                card_url=f"{base}/{vslug}/card")


# ---------------------------------------------------------------- two videos of one name (CC-0182)
#: CF-0920: the code and the text of a name that is two videos and no batch to tell them.
NAMESAKES = "namesakes"
NAMESAKES_RU = ("Роликов с именем «{slug}» несколько: {places}. Укажите, какой из них, - его батч "
                "(batch_id).")


def namesakes(root, cid, slug, bucket=None):
    """CF-0920: `[{batch_id, bucket}]` - the videos of `slug` in `publish/<cid>/` (in `bucket`
    when given, `publish_layout.WAITING` for the копилка's two folders). The batch is the
    acceptance row's whose `publish_path` names the file, else the note's or the file's own
    (`publish_layout.batch_of`); the suffix is a file's, so it is never the only word."""
    lay, acc = factory.publish_layout(), _col().acceptance()
    pub = Path(root) / PUBLISH_DIR
    try:
        rows = acc.entries(path=pub / ACCEPTANCE_LOG)
    except acc.AcceptanceError:
        rows = []
    folders = (bucket,) if isinstance(bucket, str) else bucket
    out = []
    for e in lay.locate(slug, pub, cid):
        if e["channel"] != cid or (folders is not None and e["bucket"] not in folders):
            continue
        want = lay.rel(cid, e["bucket"], lay.stem_of(e))
        hit = [r for r in rows if r.get("publish_path") == want]
        out.append({"batch_id": hit[-1].get("batch_id") if hit else lay.batch_of(e),
                    "bucket": e["bucket"]})
    return out


def waiting_namesakes(root, cid, slug):
    """`namesakes` of the копилка: `_queue/` and `_reserve/`."""
    return namesakes(root, cid, slug, factory.publish_layout().WAITING)


def namesakes_message(slug, places):
    """The Russian line of a name that is several videos, naming their batches."""
    return NAMESAKES_RU.format(slug=slug, places=", ".join(
        f"{p['batch_id'] or 'батч не записан'} ({p['bucket']})" for p in places))


def namesakes_fault(cid, slug, places):
    return BatchFault(409, NAMESAKES, namesakes_message(slug, places),
                      [f"{p['batch_id']}/{slug}: {PUBLISH_DIR}/{cid}/{p['bucket']}/"
                       for p in places])


def _note_of_batch(root, cid, slug, day, batch_id):
    """The note of the video of `slug` built in `batch_id`, as `publish_card.place` finds a
    video (`publish_layout.of_batch`, CF-0857) - `day` narrows; 404 `unknown_note`. A batch no
    acceptance row names and the file does not name is not that video."""
    lay, acc = factory.publish_layout(), _col().acceptance()
    pub = Path(root) / PUBLISH_DIR
    try:
        rows = acc.entries(path=pub / ACCEPTANCE_LOG)
        entry, why = lay.of_batch(slug, batch_id, pub, cid, day, rows=rows)
    except acc.AcceptanceError as e:
        raise _unknown_note(cid, slug, day, str(e)) from e
    if entry and lay.batch_of(entry) != batch_id \
            and not lay.row_of_batch(rows, slug, (cid, batch_id), accepted_only=False):
        entry, why = None, f"{slug}: no acceptance row and no file of batch {batch_id}"
    if not entry or not entry.get("md"):
        raise _unknown_note(cid, slug, day, why or f"{slug} of batch {batch_id}: no note")
    return entry["md"]


def named_note(root, cid, slug, day=None, batch_id=None, folders=None):
    """`(note, channel, bucket, slug)` of the note a request names, through the one path
    guard; 404 `unknown_note`. CC-0182 (CF-0920): `batch_id` names the video of that batch;
    with none, `day` or `studio_fields.locate` picks a place, and a place that is two
    videos - `<slug>` and `<slug>~<batch>` of one waiting folder - is 409 `namesakes`, never
    the last of them. `folders`: the non-day values `day` may take (default: `_queue`, `_reserve`)."""
    sf, lay = factory.studio_fields(), factory.publish_layout()
    folders = lay.WAITING if folders is None else folders
    if not SAFE_NAME.match(slug or "") or slug.endswith(NOTE_SUFFIX):
        raise _unknown_note(cid, slug, day, f"{slug!r}: not a slug")
    if batch_id is not None and not SAFE_NAME.match(batch_id):
        raise _unknown_note(cid, slug, day, f"{batch_id!r}: not a batch")
    if day is not None and day not in folders and not lay.DAY_RE.match(day):     # CF-0919
        raise _unknown_note(cid, slug, day, f"{day!r}: not a day (YYYY-MM-DD) nor "
                                            f"{' / '.join(folders)}")
    if batch_id is None and day is not None:
        here = namesakes(root, cid, slug, day)
        if len(here) > 1:
            raise namesakes_fault(cid, slug, here)
    try:
        if batch_id is None:
            p, ch, bucket, s = sf.locate(slug, root, cid, day)
        else:
            p, ch, bucket, s = sf.locate(str(_note_of_batch(root, cid, slug, day, batch_id)), root,
                                         cid, None)
    except (sf.FieldsError, lay.LayoutError) as e:
        if "(--day)" in str(e):             # the day is no answer when one folder holds both
            places = namesakes(root, cid, slug)
            if any(sum(q["bucket"] == w["bucket"] for q in places) > 1 for w in places):
                raise namesakes_fault(cid, slug, places) from e
        raise _unknown_note(cid, slug, day, str(e)) from e
    want = factory.contained(root, PUBLISH_DIR, str(ch), str(bucket), Path(p).name)
    if want is None or not want.is_file() or want.resolve() != Path(p).resolve():
        raise _unknown_note(cid, slug, bucket, f"{_rel(root, p)} leads out of {PUBLISH_DIR}/")
    return want, ch, bucket, s


def note(root, channel, slug, day=None, prefix="", batch_id=None):
    """A placed card: the factory's short view, the form, the Studio fields."""
    cid = _channel(root, channel)
    sf, lay = factory.studio_fields(), factory.publish_layout()
    pc, pn = _col().card(), _col().note()
    want, ch, bucket, s = named_note(root, cid, slug, day, batch_id)
    try:
        text = want.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BatchFault(500, "card_broken", str(e), [f"{type(e).__name__}: {e}"]) from e
    rel = _rel(root, want)
    ready, why = pc.placeable(text)                 # CF-0747: ready or ruled
    mark = pc.mark_of(text)
    sec = pn.sections(text)
    title, description = pn.title_and_description(sec)
    form, ask = sf.form_fields(sec.get("Настройки", ""))
    fields, refusal = None, None
    batch = _batch_of(root, pc, lay, want, s, prefix)
    try:
        fields = sf.prepare(str(want), root, ch, bucket, _now(_pq()))
    except sf.FieldsError as e:
        refusal = str(e)
    return {"channel": ch, "day": bucket, "slug": s, "path": rel, "ready": bool(ready),
            "why": why, "status": (mark or {}).get("status"), "title": title,
            "description": description, "view": pc.view(text, rel), "form": form,
            "ask_user": ask, "studio": fields, "studio_refusal": refusal,
            "batch": batch, "mark": mark, "raw": text, "card": _note_card(root, batch, s, text)}


def _note_card(root, batch, slug, text):
    """CC-0127: the placed note's state (card_status of its text) and the last
    build of its batch's video from the center (`api/card_center.py`)."""
    from . import card_center                                   # noqa: PLC0415
    d = None
    if batch and not batch.get("error"):
        try:
            d = batch_dir(root, batch["dir"], batch["batch_id"])
        except BatchFault:
            d = None
    return card_center.card_block(root, d, (batch or {}).get("slug") or slug, text)


# ================================================================ the writes (CC-0065)
#: Who the factory writes: `channel_pause` takes a word (`BY`: user | operator), so the center's mark goes into the reason and the note.
WRITE_BY = "user"
FROM_CENTER = "из центра"
#: One publication write at a time; how long a confirm waits for the one going.
WRITE_WAIT = 30.0
_WRITE = threading.Lock()
#: What a token is of, for the shared refusals of `batches._spend`.
ACTIONS = {
    "pause_set": ("план паузы", "пауза не поставлена", "паузы канала"),
    "pause_clear": ("план снятия паузы", "пауза не снята", "снятия паузы канала"),
    "card_place": ("план выкладки карточки", "карточка не выложена", "выкладки карточки канала"),
    "card_build": ("план сборки карточки", "карточка не собрана", "сборки карточки канала"),
    "rotation_assign": ("план назначения пар", "пары не назначены", "назначения пар канала"),
    "rotation_reject": ("план отказа от пары", "отказ не записан", "отказа от пары канала"),
    "rotation_refuse": ("план отказа за нехваткой материала", "отказ не записан",
                        "отказа за нехваткой материала канала"),
    # CC-0070
    "hold_sign": ("план подписи холда", "холд не подписан", "подписи холда канала"),
}
batches.register_actions(ACTIONS)
MODEL_REFUSED = ("Черновик через модель — не из центра: центр собирает карточку только из "
                 "данного черновика и без проверки утверждений (claims=False). Черновик моделью "
                 "и проверку утверждений делает publish_card.py build у оператора.")


def _marked(text):
    text = (text or "").strip()
    return f"{text} ({FROM_CENTER})" if text else FROM_CENTER


def _issue_plan(root, action, cid, out, facts, bound):
    """The plan's fingerprint (sha256 of `facts`), and a confirm token bound to
    the root, the channel, the action and `bound` when the plan says ok."""
    fp = _digest(facts)
    out = dict(out, action=action, channel=cid, fingerprint=fp, confirm=None, expires_in_s=None)
    if out.get("ok"):
        out.update(confirm=_issue(root, action, cid, fp, bound),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return out


def _confirm(root, channel, action, token, check, act, errors=(), commit=None):
    """One publication write at a time (busy after WRITE_WAIT - the token is
    not spent), the token spent, the plan made again from what the token is
    bound to and the same (`check(bound)` -> (out, facts)), then `act(bound)`
    - the factory's own writer. The factory's refusal (`errors`) is 409
    `refused` with its line; anything else it raises is 500.

    CC-0153: `commit` - `(scope, message(bound, answer) -> (subject, body),
    done)`: what the write may change in the root (paths from the root), git's
    word on it taken before the write and after; what changed is committed in
    one commit (`_commit`, the `Cc-Action: <action>` trailer) and the answer
    carries `commit` / `committed`. A write that raised commits nothing."""
    cid = _channel(root, channel)
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись публикации - подождите и запросите "
                                      "план заново.",
                         [f"the publication write lock was not free in {WRITE_WAIT} s; the "
                          f"token is not spent"])
    try:
        got = _spend(root, action, cid, token)
        out, facts = check(got["bound"])
        if _digest(facts) != got["fingerprint"]:
            if not out.get("ok"):
                raise BatchFault(409, "refused", out.get("why") or "Фабрика отказала.",
                                 ["the check changed since the plan", out.get("why") or ""])
            raise BatchFault(409, "check_changed", f"Проверка изменилась с момента плана - "
                                                   f"{batches._ACTIONS[action][1]}; посмотрите "
                                                   f"план заново.",
                             [f"the fingerprint of the {action} plan differs from the plan's"])
        before = _snap(root, commit[0]) if commit else None
        try:
            answer = act(got["bound"])
        except tuple(errors) as e:
            raise BatchFault(409, "refused", str(e), [f"{type(e).__name__}: {e}"]) from e
        except BatchFault:
            raise
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Фабрика ответила ошибкой посреди записи - "
                                                    "посмотрите состояние, прежде чем повторять.",
                             [f"{type(e).__name__}: {e}"]) from e
        if commit:
            scope, message, done = commit
            touched = _changed(root, scope, before)
            sha, committed = None, []
            if touched:
                subject, body = message(got["bound"], answer)
                sha, committed = _commit(root, cid, action, touched, subject, body, done)
            answer = dict(answer, commit=sha, committed=committed)
        return answer
    finally:
        _WRITE.release()


#: CC-0153: a confirmed write commits what it changed in the root.
PAUSES = "channel-pauses.json"       # = channel_pause.REGISTRY


def card_scope(cid):
    """What a card's placing (and an upload, a Studio record) may change in
    git's eyes - `publish_stash.scope` plus the journal."""
    return [f"{PUBLISH_DIR}/{cid}", f"{PUBLISH_DIR}/README.md",
            f"{PUBLISH_DIR}/acceptance-log.json", f"{PUBLISH_DIR}/{JOURNAL}",
            f"{ROTATION_DIR}/{LEDGER_DIR}/{cid}.csv"]


def rotation_scope(cid):
    """The channel's rotation ledger and its shortage journal (`rotate.refuse`)."""
    return [f"{ROTATION_DIR}/{LEDGER_DIR}/{cid}.csv",
            f"{ROTATION_DIR}/{LEDGER_DIR}/{cid}.shortages.jsonl"]


#: CC-0156: the commit moved to `api/root_commit.py` (unchanged) - every writer
#: of the API commits the same way; these names stay for this file and its tests.
COMMIT_REFUSED = root_commit.COMMIT_REFUSED
_snap = root_commit.snap
_changed = root_commit.changed
_commit = root_commit.commit


# ---------------------------------------------------------------- the pause
def _pause_now(cp, cid, root):
    now = _now(_pq())
    try:
        st = cp.status(cid, root, now)
    except cp.PauseError as e:
        reason, _notice = cp.gate(cid, root, now)
        raise BatchFault(409, "pause_unreadable", reason or str(e), [f"PauseError: {e}"]) from e
    return now, st


def _row_key(row):
    return None if not row else {k: row.get(k) for k in ("pause_id", "until", "by", "reason")}


def _pause_set_check(root, cid, bound):
    cp = _cp()
    now, st = _pause_now(cp, cid, root)
    reason = (bound.get("reason") or "").strip()
    if not reason:
        raise BatchFault(422, "note_required", "Пауза говорит, почему: напишите причину.",
                         ["channel_pause.set_pause: --reason is empty - a pause says why"])
    try:
        until = cp.parse_until(bound.get("until"))
    except cp.PauseError as e:
        raise BatchFault(422, "invalid", f"Срок паузы не читается: {e}", [str(e)]) from e
    replace = bool(bound.get("replace"))
    stands = st["row"] if st["state"] != cp.FREE else None
    why = None
    if until is not None and until <= now:
        why = f"Срок паузы ({until.isoformat()}) уже прошёл - ставить нечего."
    elif stands and not replace:
        why = (f"У канала уже есть пауза: {cp.describe(stands)} - снимите её или замените "
               f"(replace).")
    row = {"channel": cid, "by": WRITE_BY, "reason": _marked(reason),
           "until": until.isoformat() if until else None}
    out = {"ok": why is None, "why": why, "state": st["state"], "line": st["line"],
           "open_row": stands, "row": row, "replace": replace,
           "replaces": stands if replace else None}
    return out, {"action": "pause_set", "channel": cid, "state": st["state"],
                 "open": _row_key(stands), "row": row, "replace": replace, "ok": why is None}


def pause_set_plan(root, channel, reason, until=None, replace=False):
    """What «поставить на паузу» would write: the state now, the row (by
    WRITE_BY, the reason marked «из центра», until), the open pause a replace
    clears; a confirm token when the factory would take it. Nothing written."""
    cid = _channel(root, channel)
    bound = {"reason": reason, "until": until, "replace": bool(replace)}
    out, facts = _pause_set_check(root, cid, bound)
    return _issue_plan(root, "pause_set", cid, out, facts, bound)


def pause_set(root, channel, token):
    """The confirmed pause: `channel_pause.set_pause(by=WRITE_BY)`."""
    cid = _channel(root, channel)
    cp = _cp()

    def act(b):
        row = cp.set_pause(cid, WRITE_BY, _marked(b["reason"]), b.get("until"), root=root,
                           now=FACTORY_KW.get("now"), replace=bool(b.get("replace")))
        return {"action": "pause_set", "channel": cid, "row": row, "pause": pause(root, cid)}

    def message(b, _answer):
        until = f" до {b['until']}" if b.get("until") else ""
        return (f"Пауза {cid}: поставлена{until} ({WRITE_BY}, {FROM_CENTER})",
                f"CC-0153: пауза канала из центра (publish.pause_set, channel_pause.set_pause).\n"
                f"Причина: «{(b.get('reason') or '').strip()}»")
    return _confirm(root, cid, "pause_set", token,
                    lambda b: _pause_set_check(root, cid, b), act, (cp.PauseError,),
                    commit=([f"{PUBLISH_DIR}/{PAUSES}"], message, "Пауза поставлена"))


def _pause_clear_check(root, cid, bound):
    cp = _cp()
    _now_, st = _pause_now(cp, cid, root)
    stands = st["row"] if st["state"] != cp.FREE else None
    why = None if stands else f"{cid}: паузы нет - снимать нечего."
    note = _marked(bound.get("note"))
    out = {"ok": why is None, "why": why, "state": st["state"], "line": st["line"],
           "open_row": stands, "row": dict(stands, cleared_by=WRITE_BY, clear_note=note)
           if stands else None}
    return out, {"action": "pause_clear", "channel": cid, "state": st["state"],
                 "open": _row_key(stands), "note": note}


def pause_clear_plan(root, channel, note=None):
    """What «снять паузу» would do: the open row, cleared by WRITE_BY with the
    note marked «из центра». Nothing written."""
    cid = _channel(root, channel)
    bound = {"note": note}
    out, facts = _pause_clear_check(root, cid, bound)
    return _issue_plan(root, "pause_clear", cid, out, facts, bound)


def pause_clear(root, channel, token):
    """The confirmed lift: `channel_pause.clear_pause(by=WRITE_BY)` - the row stays."""
    cid = _channel(root, channel)
    cp = _cp()

    def act(b):
        row = cp.clear_pause(cid, WRITE_BY, _marked(b.get("note")), root=root,
                             now=FACTORY_KW.get("now"))
        return {"action": "pause_clear", "channel": cid, "row": row, "pause": pause(root, cid)}

    def message(b, _answer):
        return (f"Пауза {cid}: снята ({WRITE_BY}, {FROM_CENTER})",
                f"CC-0153: снятие паузы канала из центра (publish.pause_clear, "
                f"channel_pause.clear_pause).\nЗаметка: «{_marked(b.get('note'))}»")
    return _confirm(root, cid, "pause_clear", token,
                    lambda b: _pause_clear_check(root, cid, b), act, (cp.PauseError,),
                    commit=([f"{PUBLISH_DIR}/{PAUSES}"], message, "Пауза снята"))


# ---------------------------------------------------------------- the card
def _card_batch(root, cid, bound, pc):
    """The batch directory and the video the card is of (`batch_video`)."""
    d = batch_dir(root, bound.get("dir") or cid, bound.get("batch_id") or "")
    try:
        ch, script, _video, slug = pc.batch_video(d, bound.get("slug") or "")
    except pc.CardError as e:
        raise BatchFault(404, "unknown_video", str(e), [f"{type(e).__name__}: {e}"]) from e
    if factory.resolve_channel(root, str(ch)) != cid:
        raise BatchFault(409, "invalid", f"Ролик {slug} - канала {ch}, а не {cid}.",
                         [f"batch_video names channel {ch!r}"])
    return d, script, slug


def _sha(text):
    return None if text is None else _digest({"text": text})


def _read_card(p):
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else None
    except (OSError, UnicodeDecodeError) as e:
        raise BatchFault(500, "card_broken", str(e), [f"{type(e).__name__}: {e}"]) from e


def _place_check(root, cid, bound):
    pc, lay, pq = _col().card(), factory.publish_layout(), _pq()
    d, _script, slug = _card_batch(root, cid, bound, pc)
    day, replace = bound.get("day"), bool(bound.get("replace"))
    src = d / pc.CARD_DIR / f"{slug}{NOTE_SUFFIX}"
    text = _read_card(src)
    ready, why_not = pc.placeable(text) if text is not None else (False, "no card")
    # CC-0167 (CF-0857): the video of THIS batch (its acceptance row's
    # `publish_path`), as `publish_card.place` finds it - not the latest place
    # of the name; `day` narrows to the folder the video lies in now
    pub = Path(root) / PUBLISH_DIR
    try:
        entry, where = lay.of_batch(slug, d.name, pub, cid, day, log_path=pub / ACCEPTANCE_LOG)
    except _col().acceptance().AcceptanceError as e:
        entry, where = None, str(e)
    mp4 = Path(entry["mp4"]) if entry and entry.get("mp4") else None
    dst = mp4.with_suffix(NOTE_SUFFIX) if mp4 else None
    slot, paused, why = None, None, None
    from . import card_center                                   # noqa: PLC0415
    card = card_center.card_block(root, d, slug, text)
    if card["state"] == "building":
        why = (f"{slug}: карточка собирается ({(card['build'] or {}).get('run_id')}) - "
               f"дождитесь итога сборки, потом выкладывайте.")
    elif text is None:
        why = f"{_rel(root, src)}: карточки нет - сначала её собирают."
    elif not ready:
        why = f"Карточка не готова ({why_not}) - в publish/ она не идёт."
    elif mp4 is None or not mp4.is_file():
        why = (f"{slug}: ролика батча {d.name} нет в "
               f"{PUBLISH_DIR}/{cid}/{'' if day is None else day + '/'} - карточка идёт за "
               f"принятым роликом, не впереди него."
               + (f" «День» - папка, где ролик лежит сейчас (день или {lay.QUEUE}), не слот: "
                  f"без дня ролик батча найдётся сам." if day is not None else "")
               + (f" ({where})" if where else ""))
    elif dst.is_file() and not replace:
        why = f"{_rel(root, dst)}: заметка уже там - замена только с replace."
    elif day is None and entry["bucket"] == lay.QUEUE:
        now = _now(pq)
        try:
            if pq.slot_config(cid, root) is not None:
                plan = pq.plan_slot(cid, d.name, slug, root, now)
                at = plan.get("slot")
                slot = {"slot": _iso(at) if at else None, "day": plan.get("day"),
                        "line": plan.get("line"), "note": plan.get("note"),
                        "beyond_horizon": bool(plan.get("beyond_horizon")),
                        "warnings": list(plan.get("warnings") or []),
                        "moves": [{k: (str(v) if isinstance(v, Path) else
                                       _iso(v) if hasattr(v, "timestamp") else v)
                                   for k, v in m.items() if k != "md"}
                                  for m in plan.get("moves") or []]}
        except pq.Paused as e:
            paused = str(e)
        except pq.QueueError as e:
            why = f"{slug}: слота нет - {e}"
    out = {"ok": why is None, "why": why, "batch": _rel(root, d), "slug": slug,
           "card": _rel(root, src), "ready": bool(ready), "not_ready": why_not,
           "bucket": entry["bucket"] if entry else None,
           "target": _rel(root, dst) if dst else None,
           "target_exists": bool(dst and dst.is_file()), "replace": replace, "day": day,
           "slot": slot, "paused": paused, "card_state": card}
    facts = dict(out, card_sha=_sha(text), target_sha=_sha(_read_card(dst)) if dst else None)
    return out, facts


def card_place_plan(root, channel, batch_id, slug, day=None, replace=False, dirname=None):
    """What «выложить карточку» would do: the ready card of the batch, the
    video it follows in publish/<channel>/<bucket>/ (the batch's own video,
    `publish_layout.of_batch` as `publish_card.place` finds it - CF-0857; `day`
    is the folder it lies in now, not the slot), the note it replaces, and
    from `_queue/` the slot `publish_queue.plan_slot` gives (its moves and
    warnings) or the pause that keeps it there. Nothing written."""
    cid = _channel(root, channel)
    lay = factory.publish_layout()
    if day is not None and day != lay.QUEUE and not lay.DAY_RE.match(day):
        raise BatchFault(422, "invalid", f"{day!r}: не день (YYYY-MM-DD) и не {lay.QUEUE}",
                         [f"day {day!r}"])
    bound = {"dir": dirname, "batch_id": batch_id, "slug": slug, "day": day,
             "replace": bool(replace)}
    out, facts = _place_check(root, cid, bound)
    return _issue_plan(root, "card_place", cid, out, facts, bound)


def card_place(root, channel, token):
    """The confirmed placing: `publish_card.place` - the card next to its video,
    from `_queue/` into the nearest free slot (or left there under a pause);
    the factory's report lines as they are."""
    cid = _channel(root, channel)
    pc = _col().card()

    def act(b):
        d, _script, slug = _card_batch(root, cid, b, pc)
        report = []
        p = pc.place(d, slug, channel=cid, day=b.get("day"), replace=bool(b.get("replace")),
                     root=Path(root), now=FACTORY_KW.get("now"), report=report)
        return {"action": "card_place", "channel": cid, "slug": slug, "path": _rel(root, p),
                "report": report}

    def message(b, answer):
        return (f"Карточка {answer['slug']}: выложена в {answer['path']} ({WRITE_BY}, "
                f"{FROM_CENTER})",
                f"CC-0153: выкладка карточки из центра (publish.card_place, publish_card.place)."
                + "".join(f"\n{ln}" for ln in answer.get("report") or []))
    return _confirm(root, cid, "card_place", token, lambda b: _place_check(root, cid, b), act,
                    (pc.CardError,), commit=(card_scope(cid), message, "Карточка выложена"))


def _refuse_model(draft, model):
    if model or draft is None:
        raise BatchFault(409, "model_refused", MODEL_REFUSED,
                         ["publish_card.build with a model (asker) or the claim check is not "
                          "run from the center: pass `draft` and no `model`; nothing was "
                          "called"])


def _build_check(root, cid, bound):
    pc = _col().card()
    d, script, slug = _card_batch(root, cid, bound, pc)
    draft = bound.get("draft")
    problems = pc.validate_draft(draft)
    out_p = d / pc.CARD_DIR / f"{slug}{NOTE_SUFFIX}"
    text = _read_card(out_p)
    ready, why_not = pc.placeable(text) if text is not None else (False, None)
    why = ("Черновик не годится: " + "; ".join(problems)) if problems else None
    out = {"ok": why is None, "why": why, "batch": _rel(root, d), "slug": slug,
           "script_id": script.get("script_id"), "out": _rel(root, out_p),
           "exists": text is not None, "exists_ready": bool(ready) if text is not None else None,
           "draft": draft, "problems": problems, "claims": False,
           "will_be": "not_ready (claims_not_checked): без проверки утверждений карточка не "
                      "готова к выкладке - готовой её делает сборка с моделью у оператора"}
    return out, dict(out, out_sha=_sha(text))


def card_build_plan(root, channel, batch_id, slug, draft=None, model=False, dirname=None):
    """What «собрать карточку» would do: `publish_card.build` from the given
    draft with `claims=False` - the card written to the batch's
    work/publish-card/<slug>.md, not ready (the claim check is not run). A
    draft by the model is refused before anything is called."""
    _refuse_model(draft, model)
    cid = _channel(root, channel)
    bound = {"dir": dirname, "batch_id": batch_id, "slug": slug, "draft": draft}
    out, facts = _build_check(root, cid, bound)
    return _issue_plan(root, "card_build", cid, out, facts, bound)


def card_build(root, channel, token):
    """The confirmed build: `publish_card.build(draft=..., claims=False)` - no
    asker, so no model is asked."""
    cid = _channel(root, channel)
    pc = _col().card()

    def act(b):
        _refuse_model(b.get("draft"), False)
        d, _script, slug = _card_batch(root, cid, b, pc)
        res = pc.build(d, slug, draft=b["draft"], root=Path(root), claims=False,
                       now=FACTORY_KW.get("now"))
        rel = _rel(root, res["path"])
        return {"action": "card_build", "channel": cid, "slug": slug, "status": res["status"],
                "path": rel, "problems": res["problems"], "mark": res["mark"],
                "view": pc.view(res["text"], rel)}
    return _confirm(root, cid, "card_build", token, lambda b: _build_check(root, cid, b), act,
                    (pc.CardError,))


# ---------------------------------------------------------------- the rotation
def _rot_dirs(root):
    ledger = _contained(root, ROTATION_DIR, LEDGER_DIR, code="rotation_broken",
                        what="the rotation ledger")
    pipeline = _contained(root, PIPELINE_DIR, code="rotation_broken", what="the batches")
    return ledger, pipeline


def _file_sha(p):
    try:
        return _digest({"bytes": Path(p).read_bytes().hex()}) if Path(p).is_file() else None
    except OSError as e:
        return f"unreadable: {e}"


def _rot_state(rt, cid, ledger):
    """The ledger and the shortage log as they are now - what a plan is of."""
    return {"ledger": _file_sha(rt._ledger_path(cid, ledger)),
            "shortage": _file_sha(rt._shortage_log_path(cid, ledger))}


def _rot_fault(rt, e):
    status = 409 if isinstance(e, (rt.RotationError, rt.LedgerError)) else 500
    return BatchFault(status, "rotation_broken", str(e), [f"{type(e).__name__}: {e}"])


def _assign_check(root, cid, bound):
    rt = factory.rotate()
    ledger, pipeline = _rot_dirs(root)
    ids = [str(s) for s in bound.get("script_ids") or []]
    batch_id = str(bound.get("batch_id") or "")
    despite = bool(bound.get("despite_shortage"))
    if not ids or not batch_id:
        raise BatchFault(422, "invalid", "Нужны батч и хотя бы один сценарий.",
                         ["batch_id and script_ids are required"])
    try:
        cfg = rt.load_channel(cid)
        rt.rotation_config(cfg)              # K and the window: `assign` refuses without them
        pairs, blocked = rt.eligible_pairs(cfg)
        book = rt.Ledger(rt._ledger_path(cid, ledger))
        rows = book.rows()
        held = {} if despite else {w["script_id"]: w for w in rt.awaiting_material(
            cid, ledger, root=Path(root)) if not w["assignable"]}
        scripts = []
        for s in ids:
            row = book.standing_row_for(s, rows, batch_id)
            if row:
                scripts.append({"script_id": s, "state": "standing",
                                "pattern_id": row["pattern_id"], "rhythm_id": row["rhythm_id"],
                                "seq": int(row["seq"])})
            elif s in held:
                scripts.append({"script_id": s, "state": "held",
                                "retry_when": held[s].get("retry_when"),
                                "pool_says": held[s].get("pool_says")})
            else:
                scripts.append({"script_id": s, "state": "fresh"})
    except Exception as e:                                      # noqa: BLE001
        raise _rot_fault(rt, e) from e
    why = None
    if not pairs:
        why = (f"Канал {cid}: сегодня ни одна пара не исполнима; блокирует "
               f"{', '.join(rt.blocking_tasks(blocked)) or 'не названо'}.")
    elif all(x["state"] == "held" for x in scripts):
        why = ("Все предложенные темы ждут пополнения пула (CF-0149) - назначать нечего; "
               "despite_shortage - если вы посмотрели и не согласны с переписью.")
    out = {"ok": why is None, "why": why, "batch_id": batch_id, "scripts": scripts,
           "despite_shortage": despite, "eligible_pairs": [f"{p}/{r}" for p, r in pairs],
           "ledger": _rel(root, ledger)}
    return out, dict(out, state=_rot_state(rt, cid, ledger))


def rotation_assign_plan(root, channel, batch_id, script_ids, despite_shortage=False):
    """What «назначить пары» would do: per script - standing (its pair returned
    untouched), held by a shortage, or fresh (the rotation draws its pair) -
    and the eligible pairs. Nothing written."""
    cid = _channel(root, channel)
    bound = {"batch_id": batch_id, "script_ids": list(script_ids or []),
             "despite_shortage": bool(despite_shortage)}
    out, facts = _assign_check(root, cid, bound)
    return _issue_plan(root, "rotation_assign", cid, out, facts, bound)


def rotation_assign(root, channel, token):
    """The confirmed assignment: `rotate.assign` under the ledger's lock."""
    cid = _channel(root, channel)
    rt = factory.rotate()

    def act(b):
        ledger, pipeline = _rot_dirs(root)
        res = rt.assign(cid, b["batch_id"], b["script_ids"], ledger_dir=ledger,
                        pipeline_dir=pipeline, despite_shortage=bool(b.get("despite_shortage")),
                        root=Path(root))
        return {"action": "rotation_assign", "channel": cid, "result": res}

    def message(b, _answer):
        return (f"Ротация {cid}: пары назначены батчу {b['batch_id']} ({WRITE_BY}, "
                f"{FROM_CENTER})",
                f"CC-0153: назначение пар из центра (publish.rotation_assign, rotate.assign).\n"
                f"Сценарии: {', '.join(str(x) for x in b.get('script_ids') or [])}"
                + ("\nВопреки нехватке материала." if b.get("despite_shortage") else ""))
    return _confirm(root, cid, "rotation_assign", token, lambda b: _assign_check(root, cid, b),
                    act, (rt.RotationError, rt.LedgerError),
                    commit=(rotation_scope(cid), message, "Пары назначены"))


def _jsonable(v):
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def _reject_check(root, cid, bound):
    rt = factory.rotate()
    ledger, _pipeline = _rot_dirs(root)
    sid = str(bound.get("script_id") or "")
    try:
        ruling = rt.rule_on_rejection(cid, sid, bound.get("reason") or "", ledger,
                                      rejects_rhythm=bool(bound.get("rejects_rhythm")),
                                      batch_id=bound.get("batch_id"))
        why = None
    except (rt.RotationError, rt.LedgerError) as e:
        ruling, why = None, str(e)
    except Exception as e:                                      # noqa: BLE001
        raise _rot_fault(rt, e) from e
    ruling = _jsonable(ruling)
    out = {"ok": why is None, "why": why, "script_id": sid, "batch_id": bound.get("batch_id"),
           "reason": bound.get("reason") or "", "rejects_rhythm": bool(bound.get("rejects_rhythm")),
           "ruling": ruling,
           "verdict": (ruling or {}).get("verdict"),
           "writes": None if ruling is None else (
               "the denial on the standing row (rejection_verdict: denied) - the assignment "
               "stands" if ruling.get("verdict") == "denied" else
               "the rejection upheld on the row and a new row: the replacement pair, "
               "rotation-after-rejection")}
    return out, dict(out, state=_rot_state(rt, cid, ledger))


def rotation_reject_plan(root, channel, script_id, reason, rejects_rhythm=False, batch_id=None):
    """What «отказаться от пары» would do: `rotate.rule_on_rejection` (read
    only) - upheld with the replacement, or denied (written on the row as a
    denial). Nothing written."""
    cid = _channel(root, channel)
    bound = {"script_id": script_id, "reason": reason, "rejects_rhythm": bool(rejects_rhythm),
             "batch_id": batch_id}
    out, facts = _reject_check(root, cid, bound)
    return _issue_plan(root, "rotation_reject", cid, out, facts, bound)


def rotation_reject(root, channel, token):
    """The confirmed rejection: `rotate.reject` under the ledger's lock - the
    ruling written as the plan showed it."""
    cid = _channel(root, channel)
    rt = factory.rotate()

    def act(b):
        ledger, _pipeline = _rot_dirs(root)
        res = rt.reject(cid, b["script_id"], b.get("reason") or "", ledger_dir=ledger,
                        rejects_rhythm=bool(b.get("rejects_rhythm")), batch_id=b.get("batch_id"))
        return {"action": "rotation_reject", "channel": cid, "result": _jsonable(res)}

    def message(b, _answer):
        return (f"Ротация {cid}: отказ от пары {b['script_id']} ({WRITE_BY}, {FROM_CENTER})",
                f"CC-0153: отказ от пары из центра (publish.rotation_reject, rotate.reject).\n"
                f"Причина: «{(b.get('reason') or '').strip()}»")
    return _confirm(root, cid, "rotation_reject", token, lambda b: _reject_check(root, cid, b),
                    act, (rt.RotationError, rt.LedgerError),
                    commit=(rotation_scope(cid), message, "Отказ записан"))


def _deficit_path(root, rel):
    parts = [x for x in str(rel or "").split("/") if x]
    if not parts or parts[0] != PIPELINE_DIR or any(x in (".", "..") for x in parts):
        raise BatchFault(422, "invalid", f"{rel!r}: дефицит - файл батча под {PIPELINE_DIR}/ "
                                         f"(plan.assetless-rung.json)",
                         [f"deficit {rel!r} is not a path under {PIPELINE_DIR}/"])
    return _contained(root, *parts, code="invalid", what="the deficit")


def _refuse_check(root, cid, bound):
    rt = factory.rotate()
    ledger, _pipeline = _rot_dirs(root)
    sid, batch_id = str(bound.get("script_id") or ""), bound.get("batch_id")
    reason = (bound.get("reason") or "").strip()
    p = _deficit_path(root, bound.get("deficit"))
    why, row, anchors = None, None, []
    try:
        deficit = rt.shortage.read_deficit(p)
        anchors = rt.shortage.anchors_from_deficit(deficit)
    except Exception as e:                                      # noqa: BLE001
        deficit, why = None, f"{type(e).__name__}: {e}"
    try:
        book = rt.Ledger(rt._ledger_path(cid, ledger))
        row = book.standing_row_for(sid, None, batch_id)
    except rt.LedgerError as e:
        why = why or f"{e}: назовите batch_id"
    except Exception as e:                                      # noqa: BLE001
        raise _rot_fault(rt, e) from e
    if why is None and len(reason) < rt.MIN_REASON_CHARS:
        why = (f"Отказу нужна письменная причина об этом ролике - не короче "
               f"{rt.MIN_REASON_CHARS} знаков.")
    if why is None and row is None:
        why = f"{(batch_id + '/') if batch_id else ''}{sid}: нет стоящего назначения."
    if why is None and row.get("rejection_verdict"):
        why = (f"seq {row['seq']} уже несёт отказ ({row['rejection_verdict']}) - эту строку "
               f"нельзя закрыть ещё и отказом за нехваткой материала; нужен человек.")
    out = {"ok": why is None, "why": why, "script_id": sid, "batch_id": batch_id,
           "reason": reason, "deficit": _rel(root, p), "anchors": _jsonable(anchors),
           "row": _jsonable(row),
           "writes": "a shortage record, then the row closed (rejection upheld), no replacement"}
    return out, dict(out, deficit_sha=_file_sha(p), state=_rot_state(rt, cid, ledger))


def rotation_refuse_plan(root, channel, script_id, reason, deficit, batch_id=None):
    """What «отказ за нехваткой материала» would do: the standing row closed,
    the shortage record of the planner's deficit (`plan.assetless-rung.json`),
    no replacement. Nothing written."""
    cid = _channel(root, channel)
    bound = {"script_id": script_id, "reason": reason, "deficit": deficit, "batch_id": batch_id}
    out, facts = _refuse_check(root, cid, bound)
    return _issue_plan(root, "rotation_refuse", cid, out, facts, bound)


def rotation_refuse(root, channel, token):
    """The confirmed refusal: `rotate.refuse` under the ledger's lock."""
    cid = _channel(root, channel)
    rt = factory.rotate()

    def act(b):
        ledger, _pipeline = _rot_dirs(root)
        res = rt.refuse(cid, b["script_id"], b.get("reason") or "",
                        deficit_path=str(_deficit_path(root, b.get("deficit"))),
                        ledger_dir=ledger, root=Path(root), batch_id=b.get("batch_id"))
        return {"action": "rotation_refuse", "channel": cid, "result": _jsonable(res)}

    def message(b, _answer):
        return (f"Ротация {cid}: отказ за нехваткой материала {b['script_id']} ({WRITE_BY}, "
                f"{FROM_CENTER})",
                f"CC-0153: отказ за нехваткой материала из центра (publish.rotation_refuse, "
                f"rotate.refuse).\nПричина: «{(b.get('reason') or '').strip()}»")
    return _confirm(root, cid, "rotation_refuse", token, lambda b: _refuse_check(root, cid, b),
                    act, (rt.RotationError, rt.LedgerError, rt.shortage.ShortageError),
                    commit=(rotation_scope(cid), message, "Отказ записан"))


# ---------------------------------------------------------------- the hold's signature (CC-0070)
#: What the center writes as `signature.via` (CF-0687: `sign_hold(via=…)`).
SIGN_VIA = "center"
#: What a signature means - the plan says it before the user confirms.
SIGN_MEANING = ("Подпись снимает холд публикации: вы посмотрели ролик и подтверждаете, что его "
                "можно публиковать.")
#: The HTTP status of a factory refusal by its code (CF-0687 `SIGN_REFUSALS_RU`);
#: every other code is 409.
_SIGN_STATUS = {"no_such_hold": 404, "empty_user": 422, "empty_note": 422}


def _sign_fault(e):
    """`HoldSignError` -> `{message: the factory's Russian line, code: its code,
    details: its English line}`."""
    return BatchFault(_SIGN_STATUS.get(e.code, 409), e.code, e.text_ru,
                      [f"HoldSignError({e.code}): {e}"])


def _hold_ledger(root):
    return _contained(root, PUBLISH_DIR, HOLDS, code="holds_unreadable", what="the hold ledger")


def _sign_state(ph, p, hid):
    """`(signable, refusal)` of one hold - `check_sign`, nothing of our own."""
    try:
        ph.check_sign(p, hid)
    except ph.HoldSignError as e:
        return False, e.as_dict()
    return True, None


def _signable_rows(ph, p, rows):
    """Each row with `signable` and `sign_refusal` as `check_sign` says them.
    One read of the ledger per row (the ledger is a few rows - CF-0318 holds
    one per held topic)."""
    out = []
    for r in rows:
        hid = r.get("hold_id") or ph.hold_id(r.get("channel"), r.get("batch_id"),
                                              r.get("topic_id"))
        ok, refusal = _sign_state(ph, p, hid)
        out.append(dict(r, signable=ok, sign_refusal=refusal,
                        reason_ru=factory.reason_ru(r.get("reason_code")),    # CC-0113
                        sensitivity_scenes=factory.sensitivity_scenes(        # CC-0169
                            r.get("content_sensitivity_check"))))
    return out


def _flagged(row):
    """What compliance-checker recorded on the row, in words - what the row
    has, nothing inferred."""
    lines = [f"Вердикт compliance-checker: {row.get('verdict')!r}"
             + (f" ({row.get('stage_checked')})" if row.get("stage_checked") else "")]
    cs = row.get("content_sensitivity_check")
    if isinstance(cs, dict):
        lines.append("Чувствительность содержания: " + (
            "отмечена" if cs.get("flagged") else "не отмечена")
            + (f" - {cs['notes']}" if cs.get("notes") else ""))
        scenes = factory.sensitivity_scenes(cs)                    # CC-0169 (CF-0846)
        if scenes == factory.WHOLE_TOPIC:
            lines.append("Сцены флага: вся тема")
        elif scenes:
            lines.append("Сцены флага: " + ", ".join(
                factory.short_scene(s, row.get("topic_id")) for s in scenes))
    rh = row.get("rights_holder_check")
    if isinstance(rh, dict):
        risk = f", риск {rh['risk_level']}" if rh.get("risk_level") else ""
        lines.append("Правообладатель (только для сведения, CF-0420): " + (
            "совпадение" if rh.get("matched") else "нет совпадения") + risk
            + (f" - {rh['reason']}" if rh.get("reason") else ""))
    if row.get("reason"):
        lines.append(f"Основание холда: {row['reason']}")
    return lines


def _hold_sign_check(root, cid, bound, want=None):
    """The plan of a signature, made again from the token's bound input:
    `check_sign` (its refusal as it is), the note as `sign_hold` would take it.
    `want` - the hold the confirm's URL names; another one is a mismatch."""
    ph = factory.publication_hold()
    hid = f"{cid}/{bound.get('batch_id') or ''}/{bound.get('topic_id') or ''}"
    if want is not None and want != hid:
        raise BatchFault(409, "confirm_mismatch", f"Подтверждение выдано для подписи холда "
                                                  f"{hid}, а не {want} - холд не подписан.",
                         [f"token of hold_sign {hid}, asked {want}; the token is spent"])
    p = _hold_ledger(root)
    note = str(bound.get("note") or "").strip()
    if not note:
        e = ph.HoldSignError("a signature needs a note", code="empty_note")
        raise _sign_fault(e)
    try:
        got = ph.check_sign(p, hid)
    except ph.HoldSignError as e:
        raise _sign_fault(e) from e
    row = got["row"]
    out = {"ok": True, "why": None, "hold_id": hid, "batch_id": row.get("batch_id"),
           "topic_id": row.get("topic_id"), "script_id": row.get("script_id"),
           "verdict": row.get("verdict"), "flagged": _flagged(row),
           "content_sensitivity_check": row.get("content_sensitivity_check"),
           "sensitivity_scenes": factory.sensitivity_scenes(row.get("content_sensitivity_check")),
           "rights_holder_check": row.get("rights_holder_check"),
           "meaning": SIGN_MEANING, "note": note,
           "signature": {"user": WRITE_BY, "note": note, "via": SIGN_VIA},
           "ledger": _rel(root, p), "ledger_fingerprint": got["fingerprint"], "hold": row}
    return out, {"action": "hold_sign", "channel": cid, "hold_id": hid, "note": note,
                 "ledger": got["fingerprint"]}


def hold_sign_plan(root, channel, batch_id, topic_id, note):
    """What «подписать холд» would write: the hold (`check_sign` - the row as
    the ledger has it), what compliance-checker recorded, what a signature
    means, the signature (user, the note, via center). Nothing written."""
    cid = _channel(root, channel)
    bound = {"batch_id": batch_id, "topic_id": topic_id, "note": note}
    out, facts = _hold_sign_check(root, cid, bound)
    return _issue_plan(root, "hold_sign", cid, out, facts, bound)


def hold_sign(root, channel, batch_id, topic_id, token):
    """The confirmed signature: `check_sign` again (the ledger's sha256 the
    same as the plan's, else `check_changed`), then `sign_hold(user=WRITE_BY,
    note, via=center)`."""
    cid = _channel(root, channel)
    ph = factory.publication_hold()
    want = f"{cid}/{batch_id}/{topic_id}"

    def act(b):
        try:
            got = ph.sign_hold(_hold_ledger(root), want, WRITE_BY, b.get("note"),
                               when=FACTORY_KW.get("now"), via=SIGN_VIA)
        except ph.HoldSignError as e:
            raise _sign_fault(e) from e
        return {"action": "hold_sign", "channel": cid, "hold_id": want, "row": got["row"],
                "fingerprint": got["fingerprint"], "holds": holds(root, cid)}

    def message(b, _answer):
        return (f"Холд {want} подписан ({WRITE_BY}, {SIGN_VIA})",
                f"CC-0153: подпись холда публикации из центра (publish.hold_sign, CF-0687).\n"
                f"Заметка: «{str(b.get('note') or '').strip()}»")
    return _confirm(root, cid, "hold_sign", token,
                    lambda b: _hold_sign_check(root, cid, b, want), act,
                    commit=([f"{PUBLISH_DIR}/{HOLDS}"], message, "Холд подписан"))

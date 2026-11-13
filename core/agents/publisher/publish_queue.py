#!/usr/bin/env python3
"""CF-0587: a channel's publication queue - which slots are taken, the nearest
free one, and the warning when tomorrow's slot is empty.

Grill 2.0 (2026-10-06, Q7): an accepted video (its card built by CF-0017) goes
by itself into the nearest free slot of its channel; the layout
`publish/<channel>/<day>/` (CF-0475) is that queue's picture on disk.

The slot comes from the channel, never from this code -
`channels/<channel>.json` -> `publisher.slot`:

    {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}

`per_day` slots a day at `time` (or `times`, a list with one "HH:MM" per slot)
in the IANA zone `tz`; no slot sooner than `lead_hours` from now (default
DEFAULT_LEAD_HOURS) - a slot an hour away is not one Studio can still be set
for. A channel without the block has no queue.

Taken is what the record says, from two places, never from memory:

* a video in a day folder `publish/<channel>/<YYYY-MM-DD>/` - at the time its
  note's `## Публикация` names, else somewhere on that Moscow day;
* a live row of the upload journal `publish/uploads.json` (CF-0586:
  `upload_records.py`, the one reader) - at its `publish_at`, else on its
  `publish_day`; so a video already scheduled in Studio holds its slot even
  when its folder has been archived (CF-0476) or never existed.

One video found in both is one occupant. An occupant whose time is one of the
channel's slots takes exactly that slot; one with no time (or another time)
takes the first free slot of its Moscow day. The day folder stays the Moscow
day the slot falls on whatever the channel's zone (CF-0475).

Placing (`plan_slot`): the video must be accepted and not on a publication
hold (`publish/acceptance-log.json`, `publish/publication-holds.json` - CF-0328,
CF-0318), the channel must not be paused, and every candidate check must agree.
Two extension points:

* `PAUSE_CHECKS` - CF-0569 (the channel's pause flag, `channel_pause.queue_check`,
  registered below): a callable `(channel, root, now) -> None | reason |
  {"reason"?, "notice"?}`; a reason means nothing is placed (`plan_slot` raises
  `Paused`, `tomorrow` answers PAUSED, exit 3); a notice (an expired pause
  still on record) holds nothing but rides along in `warnings` and in the
  `tomorrow` line;
* `CANDIDATE_CHECKS` - CF-0042 (the pattern window over the published feed,
  `publish_window.candidate_check`, registered below): a callable
  `(channel, slug, slot, root, now, ctx) -> None | {"verdict": "reorder" |
  "warn", "reason": ...}`; `ctx` = `{"batch_id", "moved"}`, `moved` being the
  other videos a reorder would put elsewhere (`{slug: {"slot", "batch_id"}}`).

What a `reorder` does (CF-0042, grill 2.0 2026-10-06): a swap inside the
queue, never a shift of the schedule - publishing less often is worse than
publishing another video. `plan_slot` tries, in order:

1. a swap with a video already planned in a later slot that is not in Studio
   yet (a day folder with no live row of `uploads.json`): it comes forward into
   this slot, the candidate takes its slot - when both fit;
2. another accepted, unheld video waiting in `_queue/` with a ready note
   (`Батч` line) that fits this slot: it goes there, and the candidate takes
   the next free slot if it fits there, else it stays in `_queue/` (the slot
   is filled either way);
3. nothing fits: the candidate goes into the slot anyway, and the plan carries
   a loud warning (`warnings`, printed by `publish_card.py place` for the
   orchestrator) - never silently, never an empty slot.

A video already in Studio (a live journal row) is never moved: its schedule is
set there. A `warn` (no data about a pair, no K configured) lets the slot
through and is carried in `warnings` the same way.

The caller that writes is `publish_card.py place` (the slot into the card's
`## Публикация`, then `publish_layout.assign` moves the pair into the day).

    python3 agents/publisher/publish_queue.py show [--channel C] [--days N] [--now ISO] [--root DIR]
    python3 agents/publisher/publish_queue.py next [--channel C] [--now ISO] [--root DIR]
    python3 agents/publisher/publish_queue.py tomorrow [--channel C] [--now ISO] [--root DIR]
        [--notify]
        # one line per channel for the orchestrator; exit 1 when a slot of
        # tomorrow is empty, 3 when the channel is paused, 0 otherwise;
        # --notify: an empty slot is also one notification (CF-0591) - the
        # same empty slots asked again are not sent again
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:                                             # pragma: no cover
    ZoneInfo, ZoneInfoNotFoundError = None, Exception

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import publish_layout                                           # noqa: E402
import publish_note                                             # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0587"
MSK = "Europe/Moscow"
DEFAULT_LEAD_HOURS = 1
HORIZON_DAYS = 120
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
ZONE_WORD = {MSK: "МСК"}           # how a note writes the zone (publish_note.WHEN)

EXIT_OK, EXIT_EMPTY, EXIT_ERROR, EXIT_PAUSED = 0, 1, 2, 3

def _pause_flag_check(channel, root, now):
    import channel_pause                                        # noqa: PLC0415
    return channel_pause.queue_check(channel, root, now)


# CF-0569: the channel's pause flag. (channel, root, now) -> None | reason | {"reason", "notice"}.
PAUSE_CHECKS = [_pause_flag_check]


def _window_check(channel, slug, slot, root, now, ctx=None):
    import publish_window                                       # noqa: PLC0415 - it imports this module
    return publish_window.candidate_check(channel, slug, slot, root, now, ctx)


# CF-0042: the pattern window. (channel, slug, slot, root, now, ctx) -> None | {"verdict", "reason"}.
CANDIDATE_CHECKS = [_window_check]


class QueueError(Exception):
    pass


class Paused(QueueError):
    pass


def _zone(name):
    if ZoneInfo is None:                                        # pragma: no cover
        raise QueueError("zoneinfo is unavailable (Python < 3.9)")
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise QueueError(f"{name!r} is not an IANA time zone") from e


def _channel_ids():
    spec = importlib.util.spec_from_file_location("channel_ids_publish_queue",
                                                  ROOT / "shared" / "channel_ids.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _acceptance():
    import acceptance                                           # noqa: PLC0415
    return acceptance


HORIZON_TASK = "CF-0918"


def _batch_schedule():
    spec = importlib.util.spec_from_file_location("batch_schedule_publish_queue",
                                                  ROOT / "shared" / "batch_schedule.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def horizon(channel, root=None, now=None):
    """CF-0918 (the user, 04.11: «делать видео вперёд только на 3 дня»): how far
    ahead a video is put into a slot by itself - `{days, last_day, source}`.
    `days` is the channel's `min_feed_days` (`batch_schedule.window_config`:
    DEFAULTS < channels/<id>.json batch_schedule < the center's
    schedule/channel-settings.json); `last_day` the last Moscow day a slot may
    fall on - today (MSK) + `days`. A schedule block that does not read gives
    the default, and `source` says so."""
    now = now_utc(now)
    try:
        bs = _batch_schedule()
        default = bs.DEFAULTS["min_feed_days"]
    except Exception:                                           # noqa: BLE001
        bs, default = None, 3
    days, source = default, "по умолчанию"
    if bs is not None:
        try:
            w = bs.window_config(channel, Path(root or ROOT))
            days, source = w["min_feed_days"], w["source"]
        except Exception as e:                                  # noqa: BLE001
            source = f"по умолчанию ({e})"
    today = datetime.strptime(msk_day(now), "%Y-%m-%d").date()
    return {"days": days, "last_day": (today + timedelta(days=days)).isoformat(),
            "source": source}


def within_horizon(at, hz):
    """True when the slot `at` falls on or before `hz['last_day']` (MSK)."""
    return at is not None and msk_day(at) <= hz["last_day"]


def beyond_line(slug, at, hz, cfg=None):
    return (f"beyond_horizon: {slug} - ближайший свободный слот {label(at, cfg) if at else '-'} "
            f"дальше горизонта канала ({hz['days']} дн., до {hz['last_day']} МСК, "
            f"min_feed_days: {hz['source']}; {HORIZON_TASK}) - ролик остаётся в копилке")


def now_utc(now=None):
    """`now` as an aware datetime: None is the clock, a string is ISO with a zone."""
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise QueueError(f"{now!r} has no zone")
        return now
    try:
        dt = datetime.fromisoformat(str(now).strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise QueueError(f"{now!r} is not an ISO time") from e
    if dt.tzinfo is None:
        raise QueueError(f"{now!r} has no zone - name it (2026-10-06T12:00+03:00 or ...Z)")
    return dt


# --------------------------------------------------------------------------
# the channel's slot
# --------------------------------------------------------------------------

def slot_config(channel, root=None):
    """`{channel, times: [time], tz, zone, per_day, lead}` of the channel's
    `publisher.slot`, or None when the channel has none. QueueError when the
    block is there and wrong."""
    root = Path(root or ROOT)
    ids = _channel_ids()
    path = ids.channel_config_path(channel, root)
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise QueueError(f"{path}: cannot read ({e})") from e
    slot = (cfg.get("publisher") or {}).get("slot")
    if slot is None:
        return None
    where = f"{path}: publisher.slot"
    if not isinstance(slot, dict):
        raise QueueError(f"{where} must be an object")
    per_day = slot.get("per_day", 1)
    if not isinstance(per_day, int) or isinstance(per_day, bool) or per_day < 1:
        raise QueueError(f"{where}.per_day must be an integer >= 1")
    raw = slot.get("times")
    if raw is None:
        if "time" not in slot:
            raise QueueError(f"{where} names no `time`")
        if per_day > 1:
            raise QueueError(f"{where}: {per_day} slots a day need `times`, one HH:MM per slot")
        raw = [slot["time"]]
    if not isinstance(raw, list) or len(raw) != per_day:
        raise QueueError(f"{where}.times must list exactly per_day ({per_day}) HH:MM")
    times = []
    for t in raw:
        m = HHMM.match(str(t).strip())
        if not m:
            raise QueueError(f"{where}: {t!r} is not HH:MM")
        times.append(time(int(m.group(1)), int(m.group(2))))
    if len(set(times)) != len(times):
        raise QueueError(f"{where}: one time twice")
    if "tz" not in slot:
        raise QueueError(f"{where} names no `tz` - a slot without a zone is not a time")
    zone = _zone(slot["tz"])
    lead = slot.get("lead_hours", DEFAULT_LEAD_HOURS)
    if not isinstance(lead, (int, float)) or isinstance(lead, bool) or lead < 0:
        raise QueueError(f"{where}.lead_hours must be a number >= 0")
    return {"channel": cfg.get("channel_id") or path.stem, "times": sorted(times),
            "tz": str(slot["tz"]), "zone": zone, "per_day": per_day,
            "lead": timedelta(hours=lead)}


def queue_channels(root=None):
    """The channels on file that have a slot."""
    out = []
    for ch in publish_layout.known_channels(root or ROOT):
        try:
            if slot_config(ch, root):
                out.append(ch)
        except QueueError:
            out.append(ch)          # a broken block is reported by the command, not hidden
    return out


def slots(cfg, first_day, days):
    """The channel's slots on `days` local days from `first_day`, in order."""
    out = []
    for i in range(days):
        d = first_day + timedelta(days=i)
        for t in cfg["times"]:
            out.append(datetime.combine(d, t, tzinfo=cfg["zone"]))
    return out


def msk_day(at):
    return publish_layout.release_day(at)


def label(at, cfg=None):
    """`2026-10-11 01:00 МСК`; a channel in another zone gets its own time and the
    Moscow one beside it."""
    tz = cfg["tz"] if cfg else MSK
    local = at.astimezone(_zone(tz))
    if tz == MSK:
        return f"{local:%Y-%m-%d %H:%M} МСК"
    m = at.astimezone(_zone(MSK))
    return f"{local:%Y-%m-%d %H:%M} {tz} ({m:%Y-%m-%d %H:%M} МСК)"


# --------------------------------------------------------------------------
# what is taken
# --------------------------------------------------------------------------

def _publish(root):
    return Path(root or ROOT) / "publish"


def _note_time(md):
    try:
        text = Path(md).read_text(encoding="utf-8")
        return publish_note.publish_time(publish_note.sections(text).get("Публикация", ""))
    except (OSError, publish_note.NoteError):
        return None


def occupants(channel, root=None, journal=None):
    """`[{slug, day, at, sources}]` - every video of the channel that holds a
    publication day: the day folders and the live rows of the upload journal,
    one entry per (slug, Moscow day)."""
    pub = _publish(root)
    found = {}

    def add(slug, day, at, source):
        e = found.setdefault((slug, day), {"slug": slug, "day": day, "at": None, "sources": []})
        if at is not None and e["at"] is None:
            e["at"] = at
        if source not in e["sources"]:
            e["sources"].append(source)

    for e in publish_layout.entries(pub, channel):
        if e["channel"] != channel or not publish_layout.DAY_RE.match(e["bucket"]):
            continue
        at = _note_time(e["md"]) if e["md"] else None
        if at is not None and msk_day(at) != e["bucket"]:
            at = None               # the folder is the record of the day; a stray time is not trusted
        add(e["slug"], e["bucket"], at, f"publish/{channel}/{e['bucket']}/")
    jpath = Path(journal) if journal else pub / "uploads.json"
    try:
        rows = upload_records.uploads(jpath, channel)
        # CF-0607: an API upload whose YouTube fields were deleted under the API
        # policy (CF-0618, `api_data_deleted`) is still on the channel - it holds
        # its day like any live row (the slot's time went with the API fields)
        rows += [dict(r, video_id="api_data_deleted") for r in
                 upload_records.read_journal(jpath).get("api_data_deleted") or []
                 if isinstance(r, dict) and r.get("channel") == channel]
    except (upload_records.JournalError, ValueError) as e:
        raise QueueError(f"{jpath}: {e} - the queue does not guess around an unreadable journal") from e
    for r in rows:
        if not upload_records.holds_slot(r):       # removed, or withdrawn into the копилка (CF-0918)
            continue
        at = None
        if r.get("publish_at"):
            try:
                at = now_utc(r["publish_at"])
            except QueueError:
                at = None
        day = r.get("publish_day") or (msk_day(at) if at else None)
        if day:
            add(r.get("slug"), day, at, f"uploads.json:{r.get('video_id')}")
    return sorted(found.values(), key=lambda o: (o["day"], o["slug"] or ""))


def table(channel, root=None, now=None, days=14, journal=None, cfg=None, start=None):
    """The channel's slots from today (its own zone) for `days` days:
    `[{at, day, taken_by}]`, `taken_by` the slug in it or None."""
    cfg = cfg or slot_config(channel, root)
    if cfg is None:
        raise QueueError(f"channel {channel!r} has no publisher.slot in channels/{channel}.json "
                         f"- it has no publication queue")
    now = now_utc(now)
    first = start or now.astimezone(cfg["zone"]).date()
    rows = [{"at": at, "day": msk_day(at), "taken_by": None}
            for at in slots(cfg, first, days)]
    by_day = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    rest = []
    for o in occupants(channel, root, journal):
        day_rows = by_day.get(o["day"])
        if not day_rows:
            continue                # a day outside the table, or one with no slot of this channel
        hit = next((r for r in day_rows if o["at"] is not None and r["at"] == o["at"]
                    and r["taken_by"] is None), None)
        if hit:
            hit["taken_by"] = o["slug"]
        else:
            rest.append(o)
    for o in rest:                  # no time, or not a slot time: the first free slot of its day
        free = [r for r in by_day[o["day"]] if r["taken_by"] is None]
        if free:
            free[0]["taken_by"] = o["slug"]
    return rows


def waiting(channel, root=None):
    """The videos of the копилка, accepted with no slot yet: `publish/<channel>/_queue/`
    and the reserve in `_reserve/` (CF-0919), each name once."""
    out = []
    for e in publish_layout.entries(_publish(root), channel):
        if e["channel"] == channel and e["bucket"] in publish_layout.WAITING \
                and e["slug"] not in out:
            out.append(e["slug"])
    return out


def reserve_entries(channel, root=None, journal=None):
    """CF-0919: `[(entry, row)]` - the reserve of the channel, each withdrawn row
    of the upload journal with its pair: in `_reserve/`, or - a video withdrawn
    before the folder existed (`publish_move.py --migrate-reserve`) - in
    `_queue/`, the note there being of the row's batch. A namesake of another
    batch is a new video, not the reserve (a pair with no note cannot say: it is
    taken for the row's). CF-0920: two pairs of a name in one folder, `<slug>~<batch>`
    (`publish_layout.batch_of`) - each withdrawn row takes the pair of its batch."""
    jpath = Path(journal) if journal else _publish(root) / "uploads.json"
    try:
        rows = upload_records.uploads(jpath, channel)
    except (upload_records.JournalError, ValueError) as e:
        raise QueueError(f"{jpath}: {e} - the queue does not guess around an unreadable journal") from e
    here = {}
    for e in publish_layout.entries(_publish(root), channel):
        if e["channel"] == channel:
            here.setdefault((e["slug"], e["bucket"]), []).append(e)
    out = []
    for r in rows:
        if not upload_records.is_withdrawn(r) or r.get("removed_at"):
            continue
        for bucket in (publish_layout.RESERVE, publish_layout.QUEUE):
            cands = here.get((r.get("slug"), bucket)) or []
            owners = [publish_layout.batch_of(e) for e in cands]
            pick = [e for e, b in zip(cands, owners) if b == r.get("batch_id")] \
                or [e for e, b in zip(cands, owners) if b is None]
            if pick:
                out.append((pick[0], r))
                break
    return out


def reserve(channel, root=None, journal=None):
    """CF-0918: the videos of `waiting` that are the копилка's reserve - in
    Studio already, taken off their slot (a withdrawn row of the upload
    journal, `upload_records.withdraw`). They come back to a day by the
    user's word (`publish_move.py --move`, `publish_stash.py`), not by
    themselves: the batch planner does not count them as the feed's fill."""
    return [e["slug"] for e, _r in reserve_entries(channel, root, journal)]


def queued(channel, root=None, journal=None):
    """CF-0919: the names in `_queue/` that are not the reserve - what can fill
    the feed. Not `waiting` minus `reserve`: a new video may carry the name of a
    reserve one (a hype repeat of a franchise, percy-jackson 04.11)."""
    kept = {(e["stem"], e["bucket"]) for e, _r in reserve_entries(channel, root, journal)}
    return [e["slug"] for e in publish_layout.entries(_publish(root), channel)
            if e["channel"] == channel and e["bucket"] == publish_layout.QUEUE
            and (e["stem"], e["bucket"]) not in kept]


def next_free(channel, root=None, now=None, journal=None, cfg=None):
    """The nearest free slot no sooner than `lead` from now (aware datetime in the
    channel's zone)."""
    cfg = cfg or slot_config(channel, root)
    now = now_utc(now)
    earliest = now + (cfg or {}).get("lead", timedelta(0))
    for r in table(channel, root, now, HORIZON_DAYS, journal, cfg):
        if r["taken_by"] is None and r["at"] >= earliest:
            return r["at"]
    raise QueueError(f"{channel}: no free slot in {HORIZON_DAYS} days")


# --------------------------------------------------------------------------
# the extension points (CF-0569, CF-0042)
# --------------------------------------------------------------------------

def pause_state(channel, root=None, now=None):
    """`(reason, notices)`: the reason the channel is paused (CF-0569) or None,
    and the notices of the pause checks (an expired pause that holds nothing)."""
    notices = []
    for check in PAUSE_CHECKS:
        said = check(channel, root, now)
        if isinstance(said, dict):
            if said.get("notice"):
                notices.append(str(said["notice"]))
            if said.get("reason"):
                return str(said["reason"]), notices
        elif said:
            return str(said), notices
    return None, notices


def paused(channel, root=None, now=None):
    """The reason the channel is paused (CF-0569), or None."""
    return pause_state(channel, root, now)[0]


def check_candidate(channel, slug, slot, root=None, now=None, ctx=None):
    """The objections of the candidate checks (CF-0042) to `slug` in `slot`;
    `ctx` = `{"batch_id", "moved"}` (see the module's docstring)."""
    out = []
    ctx = ctx if ctx is not None else {}
    for check in CANDIDATE_CHECKS:
        said = check(channel, slug, slot, root, now, ctx)
        if said:
            out.append(said if isinstance(said, dict) else {"verdict": "reorder", "reason": str(said)})
    return out


# --------------------------------------------------------------------------
# placing one video
# --------------------------------------------------------------------------

def check_placeable(channel, batch_id, slug, root=None):
    """Stop unless the video is accepted and holds no open publication hold."""
    pub = _publish(root)
    acc = _acceptance()
    try:
        st = acc.state(channel, batch_id, slug, path=pub / "acceptance-log.json",
                       holds_path=pub / "publication-holds.json")
    except acc.AcceptanceError as e:
        raise QueueError(f"{slug}: {e} - fail closed, no slot") from e
    if not st["accepted"]:
        raise QueueError(f"{slug}: not accepted by the user ({st['verdict'] or 'no verdict'} in "
                         f"publish/acceptance-log.json) - no slot")
    if st["held"]:
        raise QueueError(f"{slug}: publication hold {st['hold_id']} stands unsigned "
                         f"({st['hold_reason']}) - a held video gets no slot (CF-0318)")
    return st


def publish_line(at, cfg, now):
    """The `## Публикация` body for a slot: bold in the form publish_note reads."""
    m = at.astimezone(_zone(MSK))
    own = "" if cfg["tz"] == MSK else \
        f" ({at.astimezone(cfg['zone']):%Y-%m-%d %H:%M} {cfg['tz']} по поясу канала)"
    return (f"**{m:%Y-%m-%d %H:%M} МСК**{own} — ближайший свободный слот канала "
            f"`{cfg['channel']}` (очередь {TASK}, `agents/publisher/publish_queue.py`), "
            f"поставлен {now.astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}.")


def _verdicts(objections):
    reorder = [o for o in objections if o.get("verdict") == "reorder"]
    warns = [str(o.get("reason")) for o in objections if o.get("verdict") != "reorder"]
    return reorder, warns


def _fits(channel, slug, slot, root, now, batch_id, moved=None):
    """`(fits, warnings)` of `slug` in `slot` with the `moved` videos elsewhere."""
    reorder, warns = _verdicts(check_candidate(channel, slug, slot, root, now,
                                               {"batch_id": batch_id, "moved": moved or {}}))
    return not reorder, warns


def _move(slug, batch_id, frm, at, cfg, now, md=None):
    return {"slug": slug, "batch_id": batch_id, "from": frm, "slot": at, "day": msk_day(at),
            "line": publish_line(at, cfg, now), "md": md}


def _later_unscheduled(channel, slot, root, now, journal, cfg):
    """Videos planned after `slot` in a day folder and not in Studio yet, in slot order."""
    import publish_window                                       # noqa: PLC0415
    rows = table(channel, root, now, HORIZON_DAYS, journal, cfg)
    occ = {(o["slug"], o["day"]): o for o in occupants(channel, root, journal)}
    entries = {(e["slug"], e["bucket"]): e for e in publish_layout.entries(_publish(root), channel)
               if e["channel"] == channel}
    out = []
    for r in rows:
        if r["taken_by"] is None or r["at"] <= slot:
            continue
        o = occ.get((r["taken_by"], r["day"]))
        e = entries.get((r["taken_by"], r["day"]))
        if not o or not e or any(s.startswith("uploads.json:") for s in o["sources"]):
            continue
        out.append({"slug": r["taken_by"], "at": r["at"], "day": r["day"], "md": e["md"],
                    "batch_id": publish_window.batch_of_entry(channel, e, root)})
    return out


def _waiting_ready(channel, slug, root):
    """Other videos in `_queue/` that could take a slot now: a note naming its
    batch, accepted, no open hold."""
    out = []
    # CF-0918: the reserve comes back only by the user's word; CF-0920: by the file, a
    # withdrawn pair may lie beside a new one of its name until it is migrated
    kept = {e["stem"] for e, _r in reserve_entries(channel, root) if e["bucket"] == publish_layout.QUEUE}
    for e in publish_layout.entries(_publish(root), channel):
        if e["channel"] != channel or e["bucket"] != publish_layout.QUEUE or e["slug"] == slug \
                or e["stem"] in kept:
            continue
        cb = publish_layout.card_batch(e["md"]) if e["md"] else None
        if not cb:
            continue
        try:
            check_placeable(channel, cb[1], e["slug"], root)
        except QueueError:
            continue
        out.append({"slug": e["slug"], "batch_id": cb[1], "md": e["md"]})
    return out


def _reorder(channel, batch_id, slug, slot, root, now, journal, cfg):
    """A plan that keeps `slot` filled and the window whole, or None (see the
    module's docstring: swap with a later unscheduled video, else a substitute
    from `_queue/`)."""
    for y in _later_unscheduled(channel, slot, root, now, journal, cfg):
        ok_y, w_y = _fits(channel, y["slug"], slot, root, now, y["batch_id"],
                          {slug: {"slot": y["at"], "batch_id": batch_id}})
        if not ok_y:
            continue
        ok_x, w_x = _fits(channel, slug, y["at"], root, now, batch_id,
                          {y["slug"]: {"slot": slot, "batch_id": y["batch_id"]}})
        if ok_x:
            return {"slot": y["at"], "moves": [_move(y["slug"], y["batch_id"], y["day"], slot, cfg,
                                                     now, y["md"])],
                    "warnings": w_y + w_x,
                    "note": (f"{TASK_WINDOW}: {slug} и {y['slug']} поменялись местами - "
                             f"{y['slug']} выходит {label(slot, cfg)}, {slug} - {label(y['at'], cfg)}")}
    for z in _waiting_ready(channel, slug, root):
        ok_z, w_z = _fits(channel, z["slug"], slot, root, now, z["batch_id"])
        if not ok_z:
            continue
        moves = [_move(z["slug"], z["batch_id"], publish_layout.QUEUE, slot, cfg, now, z["md"])]
        earliest = now + cfg["lead"]
        nxt = next((r["at"] for r in table(channel, root, now, HORIZON_DAYS, journal, cfg)
                    if r["taken_by"] is None and r["at"] >= earliest and r["at"] != slot), None)
        moved = {z["slug"]: {"slot": slot, "batch_id": z["batch_id"]}}
        ok_x, w_x = _fits(channel, slug, nxt, root, now, batch_id, moved) if nxt else (False, [])
        note = f"{TASK_WINDOW}: в {label(slot, cfg)} выходит {z['slug']} из _queue/ вместо {slug}"
        if ok_x:
            return {"slot": nxt, "moves": moves, "warnings": w_z + w_x,
                    "note": note + f"; {slug} - {label(nxt, cfg)}"}
        return {"slot": None, "moves": moves, "warnings": w_z + [
            f"{slug} остаётся в publish/{channel}/_queue/: в ближайшем свободном слоте "
            f"{label(nxt, cfg) if nxt else '-'} его пара тоже в окне ({TASK_WINDOW}); он встанет "
            f"при следующей постановке"], "note": note}
    return None


TASK_WINDOW = "CF-0042"


def plan_slot(channel, batch_id, slug, root=None, now=None, journal=None):
    """The placement of an accepted video, or a QueueError saying why not:
    `{slot, day, line, cfg, moves, warnings, note}`. `slot` is where `slug`
    goes (None: it stays in `_queue/` because another video took its slot -
    CF-0042), `moves` the other videos a reorder puts elsewhere
    (`[{slug, batch_id, from, slot, day, line, md}]`, applied first by
    `apply_moves`), `warnings` the lines the orchestrator must see."""
    now = now_utc(now)
    cfg = slot_config(channel, root)
    if cfg is None:
        raise QueueError(f"channel {channel!r} has no publisher.slot - it has no queue")
    why, notices = pause_state(channel, root, now)
    if why:
        raise Paused(f"{channel}: publications are paused ({why}) - {slug} gets no slot")
    check_placeable(channel, batch_id, slug, root)
    if any(e["slug"] == slug and r.get("batch_id") in (None, batch_id)
           for e, r in reserve_entries(channel, root, journal)):
        raise QueueError(f"{slug}: in the копилка's reserve - in Studio already (withdrawn, "
                         f"{HORIZON_TASK}); it comes back by `publish_move.py --move "
                         f"{slug}=DAY` or `publish_stash.py`, not by a new placing")
    slot = next_free(channel, root, now, journal, cfg)
    hz = horizon(channel, root, now)
    if not within_horizon(slot, hz):
        line = beyond_line(slug, slot, hz, cfg)
        return {"slot": None, "moves": [], "warnings": [f"PAUSE {n}" for n in notices],
                "note": line, "objections": [], "beyond_horizon": True, "horizon": hz,
                "day": None, "line": None, "cfg": cfg}
    objections = check_candidate(channel, slug, slot, root, now,
                                 {"batch_id": batch_id, "moved": {}})
    reorder, warnings = _verdicts(objections)
    warnings = [f"PAUSE {n}" for n in notices] + warnings
    plan = {"slot": slot, "moves": [], "warnings": warnings, "note": None,
            "objections": objections}
    if reorder:
        alt = _reorder(channel, batch_id, slug, slot, root, now, journal, cfg)
        if alt:
            plan.update(alt, warnings=warnings + alt["warnings"])
        else:
            plan["warnings"] = warnings + [
                f"WINDOW {channel}: {slug} ставится в {label(slot, cfg)} С ПОВТОРОМ ПАРЫ - "
                + "; ".join(str(o.get("reason")) for o in reorder)
                + f" - переставить не с чем (в _queue/ и в незагруженных в Studio слотах нет "
                  f"ролика, который встал бы без повтора); слот не сдвигается ({TASK_WINDOW})"]
    at = plan["slot"]
    if at is not None and not within_horizon(at, hz):
        plan["note"] = "; ".join(x for x in (plan.get("note"), beyond_line(slug, at, hz, cfg)) if x)
        plan["beyond_horizon"], at = True, None
        plan["slot"] = None
    plan["horizon"] = hz
    plan.update(day=msk_day(at) if at else None,
                line=publish_line(at, cfg, now) if at else None, cfg=cfg)
    return plan


# --------------------------------------------------------------------------
# applying a reorder
# --------------------------------------------------------------------------

def replace_section(text, name, body):
    """`text` with the body of its `## name` replaced (appended when absent)."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, ln in enumerate(lines) if re.match(r"^##\s+(.+?)\s*$", ln)
             and not ln.startswith("###")]
    for i in heads:
        if re.match(r"^##\s+" + re.escape(name) + r"\s*$", lines[i]):
            nxt = [j for j in heads if j > i]
            end = nxt[0] if nxt else len(lines)
            tail = "".join(lines[end:])
            return "".join(lines[:i]) + f"## {name}\n{body.rstrip()}\n" + ("\n" + tail if tail else "")
    return text.rstrip("\n") + f"\n\n## {name}\n{body.rstrip()}\n"


def apply_moves(channel, moves, root=None, git=True):
    """Put each video of `moves` into its new slot: the slot into its note's
    `## Публикация`, the pair into the day folder (from `_queue/` by
    `publish_layout.assign`, from another day by `publish_layout.move_day`)."""
    pub = _publish(root)
    done = []
    for m in moves:
        if m.get("md") and Path(m["md"]).is_file():
            md = Path(m["md"])
            md.write_text(replace_section(md.read_text(encoding="utf-8"), "Публикация",
                                          m["line"] + f" Переставлен окном паттернов ({TASK_WINDOW})."),
                          encoding="utf-8")
        if m["from"] == publish_layout.QUEUE:
            publish_layout.assign(m["slug"], channel, m["day"], publish=pub, apply=True, git=git,
                                  stem=Path(m["md"]).stem if m.get("md") else None)
        else:
            publish_layout.move_day(m["slug"], channel, m["from"], m["day"], publish=pub,
                                    apply=True, git=git)
        done.append(f"{m['slug']}: {m['from']} -> {m['day']}")
    return done


# --------------------------------------------------------------------------
# tomorrow
# --------------------------------------------------------------------------

def tomorrow(channel, root=None, now=None, journal=None):
    """`(code, line)` for the orchestrator: the slots between now and the end
    of tomorrow (the channel's zone) - every one of them taken is `ok`."""
    now = now_utc(now)
    cfg = slot_config(channel, root)
    if cfg is None:
        return EXIT_ERROR, f"PUBLISH QUEUE {channel}: no publisher.slot - the channel has no queue"
    why, notices = pause_state(channel, root, now)
    if why:
        return EXIT_PAUSED, (f"PUBLISH QUEUE {channel}: PAUSED - {why}; nothing is placed and "
                             f"tomorrow's slot stays empty")
    code, line, _empty = _tomorrow(channel, root, now, journal, cfg)
    return code, line + "".join(f"\n     PAUSE {n}" for n in notices)


def tomorrow_notify(channel, root=None, now=None, journal=None):
    """`tomorrow` and, when a slot is empty, one notification (CF-0591) keyed by
    the channel and the empty slots: asked again for the same slots it is not
    sent again; a notification is never on the critical path - the code and
    the line are `tomorrow`'s whatever the bus does. Returns `(code, line)`."""
    code, line = tomorrow(channel, root, now, journal)
    if code != EXIT_EMPTY:
        return code, line
    try:
        cfg = slot_config(channel, root)
        _c, _l, empty = _tomorrow(channel, root, now_utc(now), journal, cfg)
        wait = queued(channel, root, journal)
        bus = _notify_bus()
        if bus is not None and empty:
            slots = ", ".join(label(at, cfg) for at in empty)
            bus.send("empty_slot", f"empty_slot:{channel}:" + ",".join(a.isoformat() for a in empty),
                     f"{channel}: пустой слот {slots} - "
                     + (f"в _queue/ ждут {len(wait)}, поставить: publish_card.py place" if wait
                        else "очередь пуста - примите ролик или пересоберите"),
                     channel=channel, link=bus.link_of(channel, "feed"),
                     root=Path(root) if root else None)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY empty_slot {channel}: {e.__class__.__name__}: {e}", file=sys.stderr)
    return code, line


def _notify_bus():
    """CF-0591: the notification bus `shared/notify.py` - None when it cannot be
    loaded: a notification is never on the critical path."""
    try:
        shared = str(ROOT / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus
        return bus
    except Exception:                                            # noqa: BLE001
        return None


def _tomorrow(channel, root, now, journal, cfg):
    today = now.astimezone(cfg["zone"]).date()
    rows = [r for r in table(channel, root, now, 2, journal, cfg)
            if r["at"] > now]
    tom = today + timedelta(days=1)
    rows = [r for r in rows if r["at"].astimezone(cfg["zone"]).date() <= tom]
    empty = [r for r in rows if r["taken_by"] is None]
    if not empty:
        taken = ", ".join(f"{label(r['at'], cfg)} {r['taken_by']}" for r in rows)
        return EXIT_OK, f"ok   {channel}: {taken or 'no slot before the end of tomorrow'}", []
    wait = queued(channel, root, journal)
    return EXIT_EMPTY, (
        f"PUBLISH QUEUE {channel}: EMPTY SLOT " + ", ".join(label(r["at"], cfg) for r in empty)
        + f" - nothing is scheduled there; publish/{channel}/_queue/ holds {len(wait)} "
        + (f"({', '.join(wait)}) - publish_card.py place puts one in" if wait
           else "- accept a video or rebuild one")), [r["at"] for r in empty]


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def _channels(args):
    return [args.channel] if args.channel else queue_channels(args.root)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "next", "tomorrow"):
        p = sub.add_parser(name)
        p.add_argument("--channel")
        p.add_argument("--root")
        p.add_argument("--now")
        if name == "show":
            p.add_argument("--days", type=int, default=14)
        if name == "tomorrow":
            p.add_argument("--notify", action="store_true",
                           help="an empty slot is also one notification (CF-0591, shared/notify.py)")
    args = ap.parse_args(argv)
    code = EXIT_OK
    for ch in _channels(args):
        try:
            if args.cmd == "tomorrow":
                c, line = (tomorrow_notify if args.notify else tomorrow)(ch, args.root, args.now)
                print(line, file=out)
                code = max(code, c)
                continue
            cfg = slot_config(ch, args.root)
            if cfg is None:
                print(f"PUBLISH QUEUE {ch}: no publisher.slot - the channel has no queue", file=out)
                code = max(code, EXIT_ERROR)
                continue
            nxt = next_free(ch, args.root, args.now, cfg=cfg)
            why, notices = pause_state(ch, args.root, args.now)
            if args.cmd == "next":
                print(f"{ch}: next free slot {label(nxt, cfg)} -> publish/{ch}/{msk_day(nxt)}/"
                      + (f" - but PAUSED ({why}): nothing is placed" if why else ""), file=out)
                for n in notices:
                    print(f"  PAUSE {n}", file=out)
                continue
            print(f"{ch}: {cfg['per_day']}/day at {', '.join(t.strftime('%H:%M') for t in cfg['times'])}"
                  f" {cfg['tz']}, lead {cfg['lead']}", file=out)
            for line in ([f"  PAUSED - {why}; nothing is placed"] if why else []) + \
                    [f"  PAUSE {n}" for n in notices]:
                print(line, file=out)
            for r in table(ch, args.root, args.now, args.days, cfg=cfg):
                mark = "<- next free" if r["at"] == nxt else ""
                print(f"  {label(r['at'], cfg):<40} {r['taken_by'] or '-- free --':<28} {mark}",
                      file=out)
            wait = queued(ch, args.root)
            print(f"  _queue/: {len(wait)}" + (f" ({', '.join(wait)})" if wait else ""), file=out)
            kept = reserve(ch, args.root)
            if kept:
                print(f"  _reserve/: {len(kept)} ({', '.join(kept)})", file=out)
        except QueueError as e:
            print(f"PUBLISH QUEUE {ch}: {e}", file=out)
            code = max(code, EXIT_ERROR)
    return code


if __name__ == "__main__":
    sys.exit(main())

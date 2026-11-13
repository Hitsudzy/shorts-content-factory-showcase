#!/usr/bin/env python3
"""CF-0421, CF-0586: the upload journal `publish/uploads.json` and where else an
upload is written down. This module is the journal's one writer and one
reader - the Studio path (CF-0018), the API path (`upload.py`, CF-0421/CF-0585)
and the backfill of the videos that went up before it existed
(`backfill_uploads.py`, CF-0586) all go through `record()`.

1. `publish/uploads.json` - one row per video on the channel, the join key the
   Analyst (2.1, CF-0020/0021) reads. It lives in `publish/` and not in the
   batch for the reason the hold registry does (CF-0318): a batch moves to the
   archive after 31 days, long before the Analyst reads it. The row
   (`check_row()` is the shape):

       channel       channel id (`channels/<id>.json`), the `publish/<channel>/` folder
       entry_id      the acceptance row (`publish/acceptance-log.json`) - required:
                     a video with no acceptance is not written, it is reported
       batch_id, topic_id   copied from that acceptance row
       slug
       video_id      11 characters [A-Za-z0-9_-], YouTube's id; unique in the journal
       url           https://youtube.com/shorts/<video_id>
       publish_at    the publication slot, ISO 8601 *with its offset*
                     (`2026-10-08T01:00:00+03:00`, the API's `...Z`), or null
                     when nobody wrote it down (the backfill says why in `gaps`)
       publish_tz    the IANA zone `publish_at` is written in (`Europe/Moscow` -
                     the channel's Studio zone, GMT+03:00 - or `UTC` from the API)
       publish_day   `YYYY-MM-DD`, the release day in Moscow time - the day
                     folder of CF-0475 (`publish/<channel>/<day>/`)
       note          the video's note / acceptance card (CF-0017):
                     `publish/<channel>/<day>/<slug>.md` or its Archive archive pointer
       source        `studio` (CF-0018: fields filled in Studio, id read back) |
                     `api` (`upload.py`) | `backfill` (`backfill_uploads.py`)
       recorded_at   when the row was written, UTC
       user_edited   (`studio` rows, CF-0018) false when written; true once the
                     user had to correct a field of this video by hand -
                     `mark_user_edited()` / `studio_fields.py edited`. The 2.0
                     exit counts the `studio` rows in a row with no edit
                     (`studio_fields.py streak`)
       optional: superseded_video_ids (earlier uploads of the same video,
       deleted from the channel), gaps, evidence (backfill), removed_at /
       replaced_by (a row whose video was replaced), rescheduled (CF-0856:
       one `{from_at, from_day, from_note, to_at, to_day, to_note, at, by,
       via, task}` per move of its slot, oldest first - `reschedule()`),
       withdrawn (CF-0918: the video was taken off its slot in Studio -
       "Ограниченный доступ" - and back into the копилка; `{at, by, via, task,
       from_at, from_day, from_note, studio}` - `withdraw()`; while it stands
       `publish_at` / `publish_day` are null and `note` is the note in
       `_queue/`: the row holds no slot and no day, `is_withdrawn()`; moving it
       to a day again - `reschedule()` - takes the mark off), and
       the API extras (title, privacy_status, uploaded_at, script_id,
       pattern, ...).

   Writing is idempotent: the same row again (same channel, entry, slug,
   video id and slot) is a no-op; another row with a video id the journal
   already has - live or superseded - is `DuplicateVideoId`; a second live
   video for one acceptance row is refused unless it names the one it
   `replaces`. A row is never deleted - with one exception (CF-0618): the
   YouTube API policy's deletion of API Data (`api_data.py`) moves an
   `api` row out of `uploads` into `api_data_deleted`, without its API fields
   (video id, url, slot, privacy status).
2. the video's note `publish/<channel>/<YYYY-MM-DD>/<slug>.md` (CF-0475) - a
   `## Загрузка через API` line, the prose record a human reads (API path);
3. `publish/README.md` - the video's row of the table gets the upload appended
   to its last cell (API path).

The journal is written first: once `videos.insert` has answered, the video
exists on YouTube, and the machine record of that fact must not depend on a
prose edit succeeding.

CLI (the Studio row, CF-0018 after the fields are checked in Studio):

    python3 agents/publisher/upload_records.py studio --channel example-film \
        --entry example-film/2026-10-01T1313Z/rennick --video-id JWyd0AwT47E \
        --slot 2026-10-08T01:00+03:00 [--replaces OLDVIDEOID] [--dry-run]
    python3 agents/publisher/upload_records.py check     # the whole journal
    python3 agents/publisher/upload_records.py show [--channel C]
"""
import argparse
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:                                             # pragma: no cover
    ZoneInfo, ZoneInfoNotFoundError = None, Exception

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(AGENT))
import publish_layout                                           # noqa: E402
JOURNAL = ROOT / "publish" / "uploads.json"
README = ROOT / "publish" / "README.md"
TASK = "CF-0586"
FORMAT = 2
NOTE = ("CF-0421/CF-0586. One row per video of an accepted acceptance row on the channel: "
        "the join key the Analyst (2.1) reads - channel, entry_id (publish/acceptance-log.json), "
        "slug, video_id, the publication slot (`publish_at` ISO with its offset, `publish_tz`, "
        "`publish_day` = the MSK day folder), the note/card, and how the row got here "
        "(`source`: studio = CF-0018 after the Studio fields were checked; api = "
        "agents/publisher/upload.py; backfill = agents/publisher/backfill_uploads.py from the "
        "README prose and the notes). Written only by agents/publisher/upload_records.py. Kept "
        "in publish/ and not in the batch: batches are moved to the archive after 31 days "
        "(CF-0318). A row is never deleted; a video removed from the channel later keeps its "
        "row and gets `removed_at`.")

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
SOURCES = ("studio", "api", "backfill")
STUDIO_TZ = "Europe/Moscow"          # the channel's Studio zone, GMT+03:00 (README, CF-0018)
MSK = "Europe/Moscow"
IDENTITY = ("channel", "entry_id", "slug", "video_id", "publish_at")
ZONES = {"мск": "Europe/Moscow", "msk": "Europe/Moscow", "europe/moscow": "Europe/Moscow",
         "et": "America/New_York", "america/new_york": "America/New_York", "utc": "UTC"}
_LOCAL_WHEN = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})\s+(\S+)\s*$")


class JournalError(ValueError):
    pass


class DuplicateVideoId(JournalError):
    pass


def _zone(name):
    if ZoneInfo is None:                                        # pragma: no cover
        raise JournalError("zoneinfo is unavailable (Python < 3.9)")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise JournalError(f"{name!r} is not an IANA time zone") from e


def check_video_id(video_id):
    """The id as YouTube gives it: 11 characters of [A-Za-z0-9_-]."""
    vid = str(video_id or "").strip()
    if not VIDEO_ID_RE.match(vid):
        raise JournalError(f"{video_id!r} is not a YouTube video id (11 characters "
                           f"[A-Za-z0-9_-], the part after youtube.com/shorts/)")
    return vid


def parse_slot(text, tz=STUDIO_TZ):
    """`(publish_at, publish_tz, publish_day)` of a slot written with its zone:
    ISO with an offset (`2026-10-08T01:00+03:00`, `...Z`) or
    `YYYY-MM-DD HH:MM <zone>` (`МСК`, `ET`, `UTC`, an IANA name). `publish_at`
    is re-written in `tz`. A time without a zone is refused - a slot is only a
    slot together with its zone."""
    raw = str(text or "").strip()
    when = None
    m = _LOCAL_WHEN.match(raw)
    if m:
        day, hh, mm, zone = m.groups()
        zname = ZONES.get(zone.lower(), zone)
        when = datetime.strptime(f"{day} {int(hh):02d}:{mm}", "%Y-%m-%d %H:%M") \
            .replace(tzinfo=_zone(zname))
    else:
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as e:
            raise JournalError(f"slot {text!r} is neither ISO with an offset nor "
                               f"'YYYY-MM-DD HH:MM <zone>'") from e
        if when.tzinfo is None:
            raise JournalError(f"slot {text!r} has no zone - write the offset "
                               f"(2026-10-08T01:00+03:00) or the zone (2026-10-08 01:00 МСК)")
    local = when.astimezone(_zone(tz))
    return (local.isoformat(timespec="seconds"), tz,
            when.astimezone(_zone(MSK)).date().isoformat())


def _aware(text):
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else None


def check_row(row):
    """[] when `row` has the journal's shape, else the list of what is wrong."""
    problems = []
    if not isinstance(row, dict):
        return ["a row is not an object"]
    if not publish_layout.CHANNEL_RE.match(str(row.get("channel") or "")) \
            or publish_layout.DAY_RE.match(str(row.get("channel") or "")):
        problems.append(f"channel {row.get('channel')!r} is not a channel id")
    if not row.get("entry_id"):
        problems.append("no entry_id - the row must name its acceptance (publish/acceptance-log.json)")
    elif str(row["entry_id"]).rsplit("/", 1)[-1] != row.get("slug"):
        problems.append(f"entry_id {row['entry_id']!r} does not end with the slug {row.get('slug')!r}")
    if not row.get("slug"):
        problems.append("no slug")
    if not VIDEO_ID_RE.match(str(row.get("video_id") or "")):
        problems.append(f"video_id {row.get('video_id')!r} is not 11 characters [A-Za-z0-9_-]")
    if row.get("source") not in SOURCES:
        problems.append(f"source {row.get('source')!r} is not one of {'/'.join(SOURCES)}")
    if not row.get("recorded_at") or _aware(row["recorded_at"]) is None:
        problems.append("recorded_at is missing or has no zone")
    at = row.get("publish_at")
    if at is not None:
        when = _aware(at)
        if when is None:
            problems.append(f"publish_at {at!r} is not ISO with an offset")
        elif not row.get("publish_tz"):
            problems.append("publish_at without publish_tz")
        else:
            try:
                _zone(row["publish_tz"])
                day = when.astimezone(_zone(MSK)).date().isoformat()
                if row.get("publish_day") and row["publish_day"] != day:
                    problems.append(f"publish_day {row['publish_day']} is not the MSK day of "
                                    f"publish_at {at} ({day})")
            except JournalError as e:
                problems.append(str(e))
    if row.get("publish_day") and not publish_layout.DAY_RE.match(str(row["publish_day"])):
        problems.append(f"publish_day {row['publish_day']!r} is not YYYY-MM-DD")
    for vid in row.get("superseded_video_ids") or ():
        if not VIDEO_ID_RE.match(str(vid)):
            problems.append(f"superseded video id {vid!r} is not a YouTube id")
    if "user_edited" in row and not isinstance(row["user_edited"], bool):
        problems.append(f"user_edited {row['user_edited']!r} is not true/false")
    return problems


def same_row(a, b):
    return all(a.get(k) == b.get(k) for k in IDENTITY)


def ids_of(row):
    return [row.get("video_id")] + list(row.get("superseded_video_ids") or ())


def read_journal(path=None):
    p = Path(path or JOURNAL)
    if not p.is_file():
        return {"note": NOTE, "task": TASK, "format": FORMAT, "uploads": []}
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("uploads"), list):
        raise JournalError(f"{p}: no `uploads` list - this is not the upload journal")
    return doc


def uploads(path=None, channel=None):
    """The rows of the journal, of one channel when `channel` is given."""
    rows = read_journal(path)["uploads"]
    return [r for r in rows if channel is None or r.get("channel") == channel]


def _write(doc, p):
    doc["note"], doc["task"], doc["format"] = NOTE, TASK, FORMAT
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_record(row, rows, replaces=None):
    """'added' | 'exists' for `row` against the journal `rows`; JournalError
    (DuplicateVideoId) when it cannot go in. Pure - writes nothing."""
    problems = check_row(row)
    if problems:
        raise JournalError(f"{row.get('slug')}: " + "; ".join(problems))
    vid = row["video_id"]
    for u in rows:
        if u.get("video_id") == vid:
            if same_row(u, row):
                return "exists"
            diff = ", ".join(f"{k} {u.get(k)!r} -> {row.get(k)!r}"
                             for k in IDENTITY if u.get(k) != row.get(k))
            raise DuplicateVideoId(f"{vid} is already in the journal as {u.get('entry_id')} "
                                   f"({u.get('source') or u.get('method')}); differs: {diff}")
        if vid in (u.get("superseded_video_ids") or ()):
            raise DuplicateVideoId(f"{vid} is in the journal as a deleted earlier upload of "
                                   f"{u.get('entry_id')} (live: {u.get('video_id')})")
    for u in rows:
        if (u.get("entry_id") == row["entry_id"] and not u.get("removed_at")
                and u.get("video_id") != vid and u.get("video_id") != replaces
                and u.get("video_id") not in (row.get("superseded_video_ids") or ())):
            raise JournalError(f"{row['entry_id']} already has a live video {u.get('video_id')} "
                               f"- a re-upload names it with --replaces")
    if replaces and not any(u.get("video_id") == replaces for u in rows):
        raise JournalError(f"--replaces {replaces}: no such video in the journal")
    return "added"


def record(row, path=None, replaces=None, now=None):
    """Write `row` into the journal. 'added' or 'exists' (the same row again -
    nothing written); DuplicateVideoId / JournalError when it cannot go in.
    `replaces` - the video id this upload replaces (deleted from the channel):
    that row gets `removed_at` / `replaced_by`, this one `superseded_video_ids`."""
    p = Path(path or JOURNAL)
    doc = read_journal(p)
    row = dict(row)
    if replaces:
        replaces = check_video_id(replaces)
        row["superseded_video_ids"] = sorted(set(row.get("superseded_video_ids") or ()) | {replaces})
    status = plan_record(row, doc["uploads"], replaces=replaces)
    if status == "exists":
        return status
    if replaces:
        for u in doc["uploads"]:
            if u.get("video_id") == replaces:
                u["removed_at"] = now or _now()
                u["replaced_by"] = row["video_id"]
    doc["uploads"].append(row)
    _write(doc, p)
    return status


def append_journal(record_row, path=None):
    """The API path's write (`upload.py`): `record()`."""
    return record(record_row, path)


def make_row(acceptance_row, channel, video_id, source, publish_at=None, publish_tz=None,
             publish_day=None, note=None, recorded_at=None, **extra):
    """A journal row from an acceptance row and what is known of the upload."""
    vid = check_video_id(video_id)
    a = acceptance_row or {}
    row = {
        "channel": channel,
        "entry_id": a.get("entry_id"),
        "batch_id": a.get("batch_id"),
        "topic_id": a.get("topic_id"),
        "slug": a.get("slug"),
        "video_id": vid,
        "url": f"https://youtube.com/shorts/{vid}",
        "publish_at": publish_at,
        "publish_tz": publish_tz if publish_at else None,
        "publish_day": publish_day,
        "note": note,
        "source": source,
        "recorded_at": recorded_at or _now(),
    }
    row.update(extra)
    row.setdefault("task", TASK)
    return row


def placement(ref):
    """`(channel, day, slug)` of a `publish_path` / README cell -
    `publish/<channel>/<day>/<slug>.mp4`, `<channel>/<day>/<slug>.mp4` or its Archive
    archive pointer; None for the flat root, `_queue` or anything else."""
    ref = str(ref or "").strip().strip("`")
    arch = publish_layout.parse_archive_ref(ref)
    if arch:
        f = arch.get("file") or ""
        return (arch["channel"], arch["day"], Path(f).stem) if f else None
    parts = Path(ref).parts
    if parts and parts[0] == "publish":
        parts = parts[1:]
    if len(parts) == 3 and publish_layout.DAY_RE.match(parts[1]) \
            and publish_layout.CHANNEL_RE.match(parts[0]):
        return parts[0], parts[1], Path(parts[2]).stem
    return None


def note_of(ref):
    """The note beside a video reference (`.mp4` -> `.md`); a local path is
    written root-relative (`publish/...`)."""
    ref = str(ref or "").strip().strip("`")
    if not ref:
        return None
    md = re.sub(r"\.mp4$", ".md", ref)
    if publish_layout.is_archived(md) or md.startswith("publish/"):
        return md
    return f"publish/{md}"


def record_studio(channel, video_id, slot, entry=None, slug=None, note=None, replaces=None,
                  tz=STUDIO_TZ, path=None, log_path=None, now=None, dry_run=False, extra=None):
    """CF-0018's row: after the Studio fields were checked against the card,
    the id Studio shows is written here. Returns `(status, row)`; status
    'added' | 'exists' | 'would-add' (dry run). `extra` - more fields of the
    row (not part of its identity); `user_edited` is false unless given."""
    import upload_gate                                          # noqa: E402 (cycle-free, lazy)
    vid = check_video_id(video_id)
    if not entry and not slug:
        raise JournalError("name the video: --entry <channel/batch/slug> or --slug <slug>")
    slug = slug or str(entry).rsplit("/", 1)[-1]
    try:
        acc = upload_gate.resolve_entry(slug, entry=entry, log_path=log_path)
    except upload_gate.GateError as e:
        raise JournalError(str(e)) from e
    if acc.get("verdict") != "accepted":
        raise JournalError(f"{acc.get('entry_id')}: the verdict is {acc.get('verdict')!r}, "
                           f"not accepted - a video the user did not accept is not journalled")
    placed = placement(acc.get("publish_path"))
    row_channel = placed[0] if placed else publish_layout.channel_of_row(acc)
    if row_channel and row_channel != channel:
        raise JournalError(f"{acc.get('entry_id')} publishes on {row_channel!r}, not {channel!r}")
    publish_at, publish_tz, day = parse_slot(slot, tz)
    if placed and placed[1] != day:
        raise JournalError(f"slot {publish_at} is the MSK day {day}, the video lies in the day "
                           f"folder {placed[1]} ({acc.get('publish_path')}) - move it "
                           f"(runlog publish assign) or check the slot")
    row = make_row(acc, channel, vid, "studio", publish_at=publish_at, publish_tz=publish_tz,
                   publish_day=day, note=note or note_of(acc.get("publish_path")),
                   recorded_at=now, **dict({"user_edited": False}, **(extra or {})))
    if dry_run:
        doc = read_journal(path)
        r = dict(row)
        if replaces:
            r["superseded_video_ids"] = [check_video_id(replaces)]
        status = plan_record(r, doc["uploads"], replaces=replaces)
        return ("would-add" if status == "added" else status), r
    return record(row, path, replaces=replaces, now=now), row


def _note_key(ref):
    """A note reference as the journal writes it (`note_of`): root-relative
    `publish/...` or its archive pointer; None for nothing."""
    ref = str(ref or "").strip().strip("`")
    if not ref:
        return None
    return ref if publish_layout.is_archived(ref) or ref.startswith("publish/") \
        else f"publish/{ref}"


def repoint_notes(moves, path=None):
    """CF-0594: notes that moved (a month archived by
    scripts/archive_publish_month.py) - every row whose `note` is a key of
    `moves` (`{old note: new note}`, the old one `publish/<channel>/<day>/<slug>.md`)
    now carries the new one, the archive volume pointer. Live rows, replaced rows
    and the API-Data-deleted rows alike: the note left `publish/` for all of
    them. Nothing else in a row changes. Returns the number of rows changed;
    the journal is written only when that is not zero (no journal - 0)."""
    p = Path(path or JOURNAL)
    if not p.is_file() or not moves:
        return 0
    moves = {_note_key(k): str(v) for k, v in moves.items() if _note_key(k)}
    doc = read_journal(p)
    n = 0
    for key in ("uploads", "api_data_deleted"):
        for row in doc.get(key) or ():
            if not isinstance(row, dict):
                continue
            new = moves.get(_note_key(row.get("note")))
            if new and row.get("note") != new:
                row["note"] = new
                n += 1
    if n:
        _write(doc, p)
    return n


WHO_MAX = 40                # CF-0720: `by` / `via` (the shape of notify._who, CF-0700)


def _who(value, what):
    """CF-0720: `by` / `via` - None (not given) or a short non-empty
    single-line string; anything else is a JournalError and nothing is written."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise JournalError(f"{what}={value!r}: a short non-empty string (e.g. by='user', "
                           f"via='center') or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise JournalError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def mark_user_edited(video_id=None, slug=None, channel=None, edited=True, note=None,
                     path=None, now=None, by=None, via=None, dry_run=False):
    """CF-0018: the user corrected a field of a Studio video by hand (or, with
    `edited=False`, the mark was wrong). The live `studio` row named by its
    video id - or by its slug, when one live row of that name exists - gets
    `user_edited`, `user_edited_at`, `user_edit_note`. Returns the row;
    JournalError when no row or more than one answers.

    CF-0720: `by` / `via` (checked before anything is read or written) go on
    the row as `user_edited_by` / `user_edited_via` when given - a mark
    without them drops the previous mark's pair, so the pair always tells who
    made the mark the row carries now. `dry_run=True` returns the row as the
    mark would leave it (a copy) and writes nothing."""
    by, via = _who(by, "by"), _who(via, "via")
    p = Path(path or JOURNAL)
    doc = read_journal(p)
    if dry_run:
        doc = copy.deepcopy(doc)
    if video_id:
        video_id = check_video_id(video_id)
        mine = [u for u in doc["uploads"] if u.get("video_id") == video_id]
    elif slug:
        mine = [u for u in doc["uploads"] if u.get("slug") == slug and not u.get("removed_at")
                and (channel is None or u.get("channel") == channel)]
    else:
        raise JournalError("name the video: --video-id ID or --slug SLUG")
    if not mine:
        raise JournalError(f"no journal row for {video_id or slug}")
    if len(mine) > 1:
        raise JournalError(f"{slug}: {len(mine)} live rows ({', '.join(u['video_id'] for u in mine)})"
                           f" - name the video with --video-id")
    row = mine[0]
    if row.get("source") != "studio":
        raise JournalError(f"{row.get('video_id')} is a `{row.get('source')}` row - only the Studio "
                           f"path (CF-0018) keeps the no-edit count")
    row["user_edited"] = bool(edited)
    row["user_edited_at"] = now or _now()
    if note:
        row["user_edit_note"] = str(note)
    elif not edited:
        row.pop("user_edit_note", None)
    for key, value in (("user_edited_by", by), ("user_edited_via", via)):
        if value is None:
            row.pop(key, None)
        else:
            row[key] = value
    if not dry_run:
        _write(doc, p)
    return row


RESCHEDULE_TASK = "CF-0856"


def reschedule(video_id, publish_at, note=None, by=None, via=None, path=None, now=None,
               dry_run=False, task=RESCHEDULE_TASK):
    """CF-0856: the slot of a live row moved - the video was rescheduled in
    Studio (by a human or the center, on the user's word) and the factory
    writes it down after (`agents/publisher/publish_move.py`). The row named by
    `video_id` gets `publish_at` (an aware datetime or ISO with an offset,
    written in the row's own `publish_tz`, `...Z` kept for a `UTC` row),
    `publish_day` (its Moscow day) and `note` (when given); the move is
    appended to the row's `rescheduled` - from, to, when, `by`, `via`. Nothing
    else of the row changes. Returns the row (a copy on `dry_run`, which
    writes nothing). JournalError: no live row of that id, a removed row, a
    row with no `publish_tz`, a slot with no zone, bad `by` / `via`."""
    by, via = _who(by, "by"), _who(via, "via")
    vid = check_video_id(video_id)
    p = Path(path or JOURNAL)
    doc = read_journal(p)
    if dry_run:
        doc = copy.deepcopy(doc)
    mine = [u for u in doc["uploads"] if isinstance(u, dict) and u.get("video_id") == vid]
    if not mine:
        raise JournalError(f"no journal row for {vid}")
    row = mine[0]
    if row.get("removed_at"):
        raise JournalError(f"{vid}: the row was removed ({row['removed_at']}) - a removed "
                           f"video has no slot to move")
    back = row.get("withdrawn")
    when = publish_at if isinstance(publish_at, datetime) else _aware(str(publish_at or ""))
    if when is None or when.tzinfo is None:
        raise JournalError(f"{publish_at!r}: the new slot must be ISO with an offset")
    tz = row.get("publish_tz") or STUDIO_TZ
    local = when.astimezone(_zone(tz))
    at = local.isoformat()
    if tz == "UTC" and str(row.get("publish_at") or "").endswith("Z"):
        at = local.strftime("%Y-%m-%dT%H:%M:%SZ")
    day = when.astimezone(_zone(MSK)).date().isoformat()
    step = {"from_at": row.get("publish_at"), "from_day": row.get("publish_day"),
            "from_note": row.get("note"), "to_at": at, "to_day": day,
            "to_note": note if note is not None else row.get("note"),
            "at": now or _now(), "by": by, "via": via, "task": task}
    if back:
        step["from_reserve"] = True                 # CF-0918: back from the копилка
        row.pop("withdrawn", None)
    row["publish_at"], row["publish_tz"], row["publish_day"] = at, tz, day
    if note is not None:
        row["note"] = note
    row["rescheduled"] = list(row.get("rescheduled") or []) + [step]
    problems = check_row(row)
    if problems:
        raise JournalError(f"{vid}: the rescheduled row would be wrong: " + "; ".join(problems))
    if not dry_run:
        _write(doc, p)
    return row


WITHDRAW_TASK = "CF-0918"
WITHDRAWN_STUDIO = "ограниченный доступ"


def is_withdrawn(row):
    """CF-0918: the row's video was taken off its slot into the копилка - it is
    on the channel (its id, not published) but holds no slot and no day."""
    return isinstance(row, dict) and bool(row.get("withdrawn"))


def holds_slot(row):
    """A row that holds a publication slot / day: not removed, not withdrawn."""
    return isinstance(row, dict) and not row.get("removed_at") and not is_withdrawn(row)


def withdraw(video_id, note=None, by=None, via=None, path=None, now=None, dry_run=False,
             task=WITHDRAW_TASK, studio=WITHDRAWN_STUDIO):
    """CF-0918: the video was taken off its slot in Studio (scheduled ->
    "Ограниченный доступ", by a human or the center on the user's word) and
    back into the копилка (`publish_move.py --withdraw`). The row named by
    `video_id` gets `withdrawn` {at, by, via, task, from_at, from_day,
    from_note, studio}, `publish_at` / `publish_day` null (it holds no slot),
    `note` the note in `_reserve/` (CF-0919, when given), and a step in `rescheduled`
    (`to_at` null, `withdrawn` true). Its `publish_tz` stays - the zone a
    return writes the new slot in. `reschedule()` brings it back to a slot.
    Returns the row (a copy on `dry_run`). JournalError: no row of that id, a
    removed row, a row already withdrawn, bad `by` / `via`."""
    by, via = _who(by, "by"), _who(via, "via")
    vid = check_video_id(video_id)
    p = Path(path or JOURNAL)
    doc = read_journal(p)
    if dry_run:
        doc = copy.deepcopy(doc)
    mine = [u for u in doc["uploads"] if isinstance(u, dict) and u.get("video_id") == vid]
    if not mine:
        raise JournalError(f"no journal row for {vid}")
    row = mine[0]
    if row.get("removed_at"):
        raise JournalError(f"{vid}: the row was removed ({row['removed_at']}) - nothing to "
                           f"withdraw")
    if is_withdrawn(row):
        raise JournalError(f"{vid}: already withdrawn into the копилка "
                           f"({row['withdrawn'].get('at')})")
    at = now or _now()
    to_note = note if note is not None else row.get("note")
    row["withdrawn"] = {"at": at, "by": by, "via": via, "task": task,
                        "from_at": row.get("publish_at"), "from_day": row.get("publish_day"),
                        "from_note": row.get("note"), "studio": studio}
    row["rescheduled"] = list(row.get("rescheduled") or []) + [
        {"from_at": row.get("publish_at"), "from_day": row.get("publish_day"),
         "from_note": row.get("note"), "to_at": None, "to_day": None, "to_note": to_note,
         "at": at, "by": by, "via": via, "task": task, "withdrawn": True}]
    row["publish_at"], row["publish_day"] = None, None
    row["note"] = to_note
    problems = check_row(row)
    if problems:
        raise JournalError(f"{vid}: the withdrawn row would be wrong: " + "; ".join(problems))
    if not dry_run:
        _write(doc, p)
    return row


def probe_duration(video):
    """Seconds, via ffprobe; None when ffprobe is missing or says nothing."""
    try:
        cp = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=nw=1:nk=1", str(video)],
                            capture_output=True, text=True, timeout=30)
        return round(float(cp.stdout.strip()), 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def build_record(row, response, body, video, confirmation, uploaded_at, duration=None):
    """The API path's journal row: the CF-0586 shape (`make_row`) from the
    acceptance row (and its CF-0440 profile) and the API's answer, plus the
    API extras - nothing typed."""
    profile = row.get("profile") or {}
    src = profile.get("fact_source") or {}
    status = response.get("status") or {}
    publish_at = status.get("publishAt") or body["status"].get("publishAt")
    file = str(Path(video).resolve().relative_to(ROOT)) if _under_root(video) else str(video)
    placed = placement("/".join(Path(video).parts[-3:]))     # <channel>/<day>/<slug>.mp4
    channel = placed[0] if placed else (publish_layout.channel_of_row(row) or row.get("channel"))
    day = None
    if publish_at:
        publish_at, _, day = parse_slot(publish_at, "UTC")
        publish_at = publish_at.replace("+00:00", "Z")
    return make_row(
        row, channel, response["id"], "api", publish_at=publish_at, publish_tz="UTC",
        publish_day=day or (placed[1] if placed else None),
        note=note_of("/".join(Path(video).parts[-3:])) if placed else None,
        recorded_at=uploaded_at,
        script_id=profile.get("script_id"), pattern=profile.get("pattern"),
        rhythm=profile.get("rhythm"),
        fact_source={"name": src.get("name"), "url": src.get("url")} if src else None,
        duration_seconds=duration,
        title=(body.get("snippet") or {}).get("title"),
        privacy_status=status.get("privacyStatus") or body["status"]["privacyStatus"],
        uploaded_at=uploaded_at, file=file,
        file_bytes=Path(video).stat().st_size if Path(video).is_file() else None,
        confirmed={"answer": confirmation.answer, "at": confirmation.at},
        task="CF-0421")


def _under_root(p):
    try:
        Path(p).resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def _line(record):
    return (f"**Загружен через API {record['uploaded_at'][:10]}** (`agents/publisher/upload.py`, "
            f"CF-0421): приватный с отложенной публикацией на {record['publish_at']} (UTC) - "
            f"`youtube.com/shorts/{record['video_id']}`. Подтверждение пользователя в терминале: "
            f"«{record['confirmed']['answer']}», {record['confirmed']['at']}.")


def append_note(note_path, record):
    p = Path(note_path)
    text = p.read_text(encoding="utf-8").rstrip("\n")
    p.write_text(text + "\n\n## Загрузка через API\n" + _line(record) + "\n", encoding="utf-8")


def _where(record):
    """The folder (CF-0475) of the uploaded file relative to `publish/`:
    `<channel>/<day>`, `<channel>/_queue`, `<channel>/_reserve`, or `""` for the flat root - read off
    `record['file']`."""
    p = Path(str(record.get("file") or ""))
    b, ch = p.parent.name, p.parent.parent.name
    if (b in publish_layout.WAITING or publish_layout.DAY_RE.match(b)) \
            and publish_layout.CHANNEL_RE.match(ch):
        return f"{ch}/{b}"
    return ""


def update_readme(record, readme=None):
    """Append the upload to the video's row of the first table in
    `publish/README.md`; add a row when there is none. The row of the same day
    folder (CF-0475: `| \`<channel>/<day>/<slug>.mp4\` |`) is preferred over another
    row of the same name. Returns 'appended' | 'added' | 'no-table'."""
    p = Path(readme or README)
    lines = p.read_text(encoding="utf-8").split("\n")
    cell = (f"**загружен через API {record['uploaded_at'][:10]}**, отложенная публикация "
            f"{record['publish_at']} UTC, `youtube.com/shorts/{record['video_id']}`")
    at = _where(record)
    hits = (publish_layout.readme_rows(lines, record["slug"], at)
            or publish_layout.readme_rows(lines, record["slug"]))
    if hits:
        i = hits[-1]
        lines[i] = re.sub(r"\s*\|\s*$", "", lines[i]) + f"; {cell} |"
        result = "appended"
    else:
        start = next((i for i, line in enumerate(lines) if line.startswith("| ролик |")), None)
        if start is None:
            return "no-table"
        end = start
        while end + 1 < len(lines) and lines[end + 1].startswith("|"):
            end += 1
        where = (f"{at}/" if at else "") + record["slug"]
        lines.insert(end + 1, f"| `{where}.mp4` | `{record['channel']}/{record['batch_id']}` "
                              f"| метаданные — `{where}.md`; {cell} |")
        result = "added"
    p.write_text("\n".join(lines), encoding="utf-8")
    return result


def _print_row(r, out):
    print(f"{r.get('channel')}  {r.get('publish_day') or '?':10}  {r.get('slug'):28}  "
          f"{r.get('video_id')}  {r.get('publish_at') or '-':25}  {r.get('source'):8}  "
          f"{r.get('entry_id')}" + ("  [removed]" if r.get("removed_at") else ""), file=out)


def check_journal(path=None):
    """Problems of the whole journal: a malformed row, a video id twice."""
    rows = uploads(path)
    problems, seen = [], {}
    replaced = {r.get("video_id"): r.get("replaced_by") for r in rows if r.get("replaced_by")}
    for i, r in enumerate(rows):
        problems += [f"row {i} ({r.get('slug')}): {p}" for p in check_row(r)]
        for vid in ids_of(r):
            if vid != r.get("video_id") and replaced.get(vid) == r.get("video_id"):
                continue                    # the row it replaced (`record(replaces=)`)
            if vid in seen:
                problems.append(f"video id {vid} is in rows {seen[vid]} and {i}")
            seen.setdefault(vid, i)
    return problems


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description="publish/uploads.json - the upload journal (CF-0586)")
    ap.add_argument("--journal", default=None, help="journal path (default publish/uploads.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("studio", help="write the Studio row (CF-0018) after the fields were checked")
    st.add_argument("--channel", required=True)
    st.add_argument("--entry", help="acceptance row <channel>/<batch>/<slug>")
    st.add_argument("--slug", help="the video's name, when it was accepted once")
    st.add_argument("--video-id", required=True)
    st.add_argument("--slot", required=True,
                    help="publication slot with its zone: 2026-10-08T01:00+03:00 or '2026-10-08 01:00 МСК'")
    st.add_argument("--tz", default=STUDIO_TZ, help=f"zone publish_at is written in (default {STUDIO_TZ})")
    st.add_argument("--note", help="note/card path (default: beside the accepted video)")
    st.add_argument("--replaces", help="the video id this upload replaces (deleted from the channel)")
    st.add_argument("--log", help="acceptance log (default publish/acceptance-log.json)")
    st.add_argument("--dry-run", action="store_true")
    sh = sub.add_parser("show", help="print the journal")
    sh.add_argument("--channel")
    sub.add_parser("check", help="check every row and that no video id repeats")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "studio":
            status, row = record_studio(args.channel, args.video_id, args.slot, entry=args.entry,
                                        slug=args.slug, note=args.note, replaces=args.replaces,
                                        tz=args.tz, path=args.journal, log_path=args.log,
                                        dry_run=args.dry_run)
            print(f"{status}: {row['entry_id']} -> {row['video_id']} ({row['publish_at']}, "
                  f"{row['publish_tz']})", file=out)
            return 0
        if args.cmd == "show":
            for r in uploads(args.journal, channel=args.channel):
                _print_row(r, out)
            return 0
        problems = check_journal(args.journal)
        for p in problems:
            print(f"problem: {p}", file=out)
        print(f"{len(uploads(args.journal))} rows, {len(problems)} problems", file=out)
        return 1 if problems else 0
    except JournalError as e:
        print(f"refused: {e}", file=out)
        return 1


if __name__ == "__main__":
    sys.exit(main())

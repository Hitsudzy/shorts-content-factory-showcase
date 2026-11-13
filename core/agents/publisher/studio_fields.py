#!/usr/bin/env python3
"""CF-0018: the Studio path of a publication - the fields an orchestrator fills
in YouTube Studio (through Claude in Chrome), the check of what Studio shows
afterwards, and the journal row with the video id.

The grill of 2026-10-06 (2.0 "Publisher"): the user drags the file(s) into
Studio himself (for quality) and writes "загрузил X"; the orchestrator fills
title / description / tags from the card of CF-0017, schedules the video on
its queue slot (CF-0587), saves, reads the fields back, and only when they
agree with the card writes the row of `publish/uploads.json` (CF-0586). The
"yes" of this path is the acceptance - the user's word about this very video
with its card in front of him (`publish/acceptance-log.json`). The procedure
is `agents/publisher/SKILL.md`, «Путь через Studio (CF-0018)».

    python3 agents/publisher/studio_fields.py prepare <note.md|slug>
        [--channel C] [--day YYYY-MM-DD] [--root DIR] [--now ISO]
            # JSON of the fields; exit 2 = refused (why on stderr-like lines)
    python3 agents/publisher/studio_fields.py verify <note.md|slug> --read READ.json
            # exit 0 `ok`, 1 the mismatches (tell the user before the slot,
            # write nothing), 2 refused
    python3 agents/publisher/studio_fields.py record <note.md|slug> --video-id ID
        --read READ.json [--replaces OLD] [--dry-run]
            # verify again, then upload_records.record_studio (source studio,
            # user_edited false) and publish_window.record_published; idempotent
    python3 agents/publisher/studio_fields.py edited (--video-id ID | --slug S)
        [--note TEXT] [--undo]
            # the user corrected a field of this video by hand
    python3 agents/publisher/studio_fields.py streak [--channel C]
            # Studio videos in a row with no hand edit; the 2.0 exit is 5

**prepare refuses** (exit 2, nothing printed as fields): the note is not a
ready card (`publish_card.card_state`: no marker, built not ready, stale claim
block, title or description edited after the build); no `accepted` row in the
acceptance log, or a publication hold stands (`upload_gate.check_publishable`);
the channel is paused (`upload_gate.check_channel_not_paused`, CF-0569 - before
any schedule is set in Studio); the journal already has a live video of this
acceptance (`--replaces` names the one a re-upload replaces); the card has no
slot in `## Публикация`, or the slot is in the past, or its Moscow day is not
the note's day folder.

**The read JSON** (what the orchestrator copies from the Studio page after
saving - SKILL.md says where each field is read):

    {"title": "...", "description": "...", "tags": ["a", "b"] | "a, b",
     "visibility": "Запланировано",
     "schedule": {"date_text": "8 окт. 2026 г.", "time": "01:00",
                  "zone_text": "(GMT+03:00) Москва"}
       | "publish_at": "2026-10-08T01:00+03:00",
     "made_for_kids": false, "altered_content": false,     # optional
     "video_id": "...", "url": "https://youtube.com/shorts/..."}   # optional

**Normalisation before comparing** (what Studio is known to change on the way
in and out of its form, and nothing else): Unicode NFC; `\\r\\n` / `\\r` ->
`\\n`; no-break and narrow spaces (U+00A0, U+202F, U+2007) -> a space - the
contenteditable description turns double spaces into NBSP + space;
zero-width characters (U+200B/C/D, U+2060, U+FEFF) dropped; trailing spaces of
every line dropped; the whole text stripped; three or more line breaks -> two
(the description DIV's empty lines read back doubled through innerText). The
title is one line: every run of whitespace -> one space. Tags: each stripped,
empty ones dropped, compared as an ordered list. The time is compared as an
instant - a schedule read in another zone (GMT-04:00 New York, the old way)
agrees when it is the same moment.
"""
import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import publish_card                                             # noqa: E402
import publish_layout                                           # noqa: E402
import publish_note                                             # noqa: E402
import upload_gate                                              # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0018"
EXIT_OK, EXIT_MISMATCH, EXIT_REFUSED = 0, 1, 2
STREAK_GOAL = 5                     # grill 2.0: five videos in a row with no hand edit
MSK = "Europe/Moscow"
VISIBILITY = "scheduled"
VISIBILITY_STUDIO = "Запланировать"
SCHEDULED_WORDS = {"scheduled", "schedule", "запланировать", "запланировано", "запланирован",
                   "отложенная публикация", "запланировать публикацию"}
# How Studio's zone list names a city (the label is "(GMT+03:00) Москва").
# A zone missing here gets no label - the offset is still given.
STUDIO_CITY = {"Europe/Moscow": "Москва", "America/New_York": "Нью-Йорк", "UTC": "UTC"}
# The date picker writes the month the way ICU's Russian short format does:
# "26 сент. 2026 г." (docs/publisher-metadata-rules.md, 2026-09-24).
MONTHS_RU = ("янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.",
             "нояб.", "дек.")
MONTH_STEMS = (("янв", 1), ("фев", 2), ("мар", 3), ("апр", 4), ("ма", 5), ("июн", 6),
               ("июл", 7), ("авг", 8), ("сен", 9), ("окт", 10), ("ноя", 11), ("дек", 12))
SPACES = {" ": " ", " ": " ", " ": " "}
ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
DATE_TEXT = re.compile(r"(\d{1,2})\s+([а-яё]+)\.?\s+(\d{4})", re.I)
TIME_TEXT = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
GMT_TEXT = re.compile(r"GMT\s*([+\-−])\s*(\d{1,2}):?(\d{2})?", re.I)

# The form's questions the channel's `## Настройки` line answers
# (`channels/<channel>.json` -> `publisher.settings`). A question the line
# does not answer is null and goes to `ask_user` - never guessed.
FORM = (
    ("made_for_kids", "Аудитория", (
        (re.compile(r"(?<![А-Яа-яё])не\s+для\s+детей", re.I), False,
         "Нет, это видео не для детей"),
        (re.compile(r"(?<![А-Яа-яё])для\s+детей", re.I), True, "Да, это видео для детей"))),
    ("altered_content", "Использование ИИ / изменённый контент (в «Развернуть»)", (
        (re.compile(r"ИИ\s*/\s*синтетический контент:\s*нет", re.I), False, "Нет"),
        (re.compile(r"ИИ\s*/\s*синтетический контент:\s*да", re.I), True, "Да"))),
    ("paid_promotion", "Платная реклама (в «Развернуть»)", (
        (re.compile(r"прямой\s+рекламы\s+нет", re.I), False,
         "Нет, в видео нет прямой рекламы"),
        (re.compile(r"(?:прямая\s+)?реклам\w*\s*:\s*есть", re.I), True,
         "Да, в видео есть прямая реклама"))),
    ("auto_concepts", "«Автоматическое объяснение понятий» (эксперимент, в «Развернуть»)", (
        (re.compile(r"снять\s+«?автоматическое объяснение понятий", re.I), False,
         "снять галочку"),)),
)
LANGUAGE = re.compile(r"Язык(?:\s+видео)?:\s*([^.;\n]+)", re.I)


class FieldsError(Exception):
    """The fields cannot be prepared or the read cannot be compared."""


# ------------------------------------------------------------------ helpers
def _zone(name):
    if ZoneInfo is None:                                        # pragma: no cover
        raise FieldsError("zoneinfo is unavailable (Python < 3.9)")
    return ZoneInfo(name)


def now_utc(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc)
    when = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise FieldsError(f"--now {now!r} has no zone")
    return when.astimezone(timezone.utc)


def _paths(root):
    pub = Path(root) / "publish"
    return {"publish": pub, "log": pub / "acceptance-log.json",
            "holds": pub / "publication-holds.json", "journal": pub / "uploads.json"}


def _rel(path, root):
    try:
        return str(Path(path).absolute().relative_to(Path(root).absolute()))
    except ValueError:
        return str(path)


def _offset(dt):
    off = dt.utcoffset() or timedelta(0)
    sign = "+" if off >= timedelta(0) else "-"
    minutes = abs(int(off.total_seconds())) // 60
    return f"GMT{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def date_picker_text(day):
    return f"{day.day} {MONTHS_RU[day.month - 1]} {day.year} г."


def split_tags(text):
    return [t.strip() for t in re.split(r"[,\n]", text or "") if t.strip()]


# ------------------------------------------------------------------ the card
def locate(ref, root=None, channel=None, day=None):
    """`(note path, channel, day, slug)` of a note given by its path or by its
    slug (`--day` picks one of two notes of the same name)."""
    root = Path(root or ROOT)
    p = Path(ref)
    if p.suffix == ".md":
        if not p.is_absolute():
            p = p if p.is_file() else root / p
        if not p.is_file():
            raise FieldsError(f"{ref}: no such note")
        found = publish_layout.bucket_of(p, _paths(root)["publish"])
        if not found or not found[0]:
            raise FieldsError(f"{p}: not under publish/<channel>/<day>/ - the card is read where "
                              f"`publish_card.py place` put it")
        return p, found[0], found[1], publish_layout.split_name(p.stem)[0]
    e = _of_name(str(ref), root, channel, day)
    if not e or not e.get("md"):
        raise FieldsError(f"{ref}: no note in publish/{channel or '<channel>'}/"
                          f"{day or '<day>'}/ - name the note's path or its slug")
    return Path(e["md"]), e["channel"], e["bucket"], e["slug"]


def _of_name(slug, root, channel=None, day=None):
    """CF-0857: the note of a bare name. A channel reuses names (23.10 Tech
    `anthropic`: one published from `2026-10-23/`, the next one placed on
    `2026-10-26/`), so with no `day` the places of the name already in the
    upload journal (a live row's note or entry) are not the one the Studio
    path fills; one place left - that one, several - refused, name the day
    (`--day`). Every place already in the journal - the latest, as before (the
    journal gate of `prepare` says why)."""
    pub = _paths(root)["publish"]
    if day is not None:
        return publish_layout.find(slug, pub, channel, day)
    places = publish_layout.locate(slug, pub, channel)
    if len(places) < 2:
        return publish_layout.find(slug, pub, channel, None)
    try:
        rows = [u for u in upload_records.uploads(_paths(root)["journal"])
                if u.get("video_id") and not u.get("removed_at")]
    except (upload_records.JournalError, ValueError) as e:
        raise FieldsError(f"{_paths(root)['journal']}: {e} - fail closed") from e
    notes = {str(u.get("note") or "") for u in rows}
    entries = {str(u.get("entry_id") or "") for u in rows}

    def in_journal(e):
        if not e.get("md"):
            return False
        if _rel(e["md"], root) in notes:
            return True
        try:
            mark = publish_card.mark_of(Path(e["md"]).read_text(encoding="utf-8")) or {}
        except OSError:
            return False
        batch = Path(str(mark.get("batch") or "")).name
        return bool(batch) and f"{mark.get('channel') or e['channel']}/{batch}/{slug}" in entries
    open_ = [e for e in places if not in_journal(e)]
    if len(open_) == 1:
        return open_[0]
    if len(open_) > 1:
        raise FieldsError(f"{slug}: {len(open_)} places of this name not in the upload journal ("
                          + ", ".join(_rel(e["md"] or e["mp4"], root) for e in open_)
                          + ") - name the day (--day) or the note's path")
    return places[-1]


def form_fields(settings_text):
    """`({name: {value, studio, label, from}}, [names to ask the user])` from
    the card's `## Настройки` (the channel's `publisher.settings`)."""
    out, ask = {}, []
    for name, label, rules in FORM:
        hit = None
        for rx, value, studio in rules:
            if rx.search(settings_text or ""):
                hit = {"value": value, "studio": studio}
                break
        if hit is None:
            hit = {"value": None, "studio": None,
                   "ask_user": "правила и настройки канала молчат — спросить пользователя, "
                               "ответ записать в channels/<канал>.json → publisher.settings"}
            ask.append(name)
        out[name] = dict(hit, label=label, source="## Настройки (publisher.settings)")
    lang = LANGUAGE.search(settings_text or "")
    out["language"] = {"value": lang.group(1).strip() if lang else None,
                       "label": "Язык видео (в «Развернуть»)",
                       "source": "## Настройки (publisher.settings)"}
    if not lang:
        out["language"]["ask_user"] = "язык не назван в настройках канала — спросить пользователя"
        ask.append("language")
    return out, ask


def schedule_of(at_utc, zone):
    """The slot as Studio's schedule picker takes it, in `zone` (the slot's
    zone from `publisher.slot.tz`): the zone is chosen explicitly - Studio's
    default is the Mac's zone (docs/publisher-metadata-rules.md)."""
    local = at_utc.astimezone(_zone(zone))
    msk = at_utc.astimezone(_zone(MSK))
    city = STUDIO_CITY.get(zone)
    return {
        "publish_at": local.isoformat(timespec="seconds"),
        "publish_at_utc": at_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zone": zone,
        "zone_offset": _offset(local),
        "zone_label": f"({_offset(local)}) {city}" if city else None,
        "date": local.date().isoformat(),
        "date_picker_text": date_picker_text(local.date()),
        "time": local.strftime("%H:%M"),
        "msk": f"{msk:%Y-%m-%d %H:%M} МСК",
        "msk_day": msk.date().isoformat(),
    }


def _slot_zone(channel, root):
    import publish_queue                                        # noqa: PLC0415
    try:
        cfg = publish_queue.slot_config(channel, root)
    except publish_queue.QueueError as e:
        raise FieldsError(str(e)) from e
    return (cfg or {}).get("tz") or MSK


def prepare(ref, root=None, channel=None, day=None, now=None, replaces=None, stage="prepare",
            video_id=None):
    """The fields of one card, as the orchestrator fills them in Studio.

    `stage="record"` is the same reading at the moment of the journal write:
    the gates that guard *setting* a schedule (pause, past slot, already in
    the journal) are skipped there - the video already stands in Studio and
    the journal must say so; the card, the acceptance and the hold still
    refuse."""
    root = Path(root or ROOT)
    paths = _paths(root)
    note, ch, bucket, slug = locate(ref, root, channel, day)
    text = note.read_text(encoding="utf-8")
    ready, why = publish_card.placeable(text)       # ready, or ruled by the user (CF-0747)
    if not ready:
        raise FieldsError(f"{_rel(note, root)}: the card is not ready ({why}) - Studio is filled "
                          f"only from a ready card (publish_card.py, CF-0017)")
    mark = publish_card.mark_of(text) or {}
    if mark.get("slug") and mark["slug"] != slug:
        raise FieldsError(f"{_rel(note, root)}: the card is of {mark['slug']!r}, the file is {slug!r}")
    batch = Path(str(mark.get("batch") or "")).name
    if not batch:
        raise FieldsError(f"{_rel(note, root)}: the card's marker names no batch")
    entry = f"{mark.get('channel') or ch}/{batch}/{slug}"
    try:
        acc = upload_gate.resolve_entry(slug, entry=entry, log_path=paths["log"])
        upload_gate.check_publishable(acc, log_path=paths["log"], holds_path=paths["holds"])
    except upload_gate.GateError as e:
        raise FieldsError(str(e)) from e
    notices = []
    if stage != "record":
        try:
            notice = upload_gate.check_channel_not_paused(ch, root, now)
        except upload_gate.GateError as e:
            raise FieldsError(str(e)) from e
        if notice:
            notices.append(str(notice))
        try:
            rows = upload_records.uploads(paths["journal"])
        except (upload_records.JournalError, ValueError) as e:
            raise FieldsError(f"{paths['journal']}: {e} - fail closed") from e
        live = [u for u in rows if u.get("entry_id") in (acc.get("entry_id"), entry)
                and u.get("video_id") and not u.get("removed_at")
                and u.get("video_id") not in (replaces, video_id)]
        # CF-0607: the same picture as the API path's gate - an API upload whose
        # YouTube id was deleted under the API policy (CF-0618) is still uploaded
        gone = [u for u in upload_records.read_journal(paths["journal"]).get("api_data_deleted")
                or [] if isinstance(u, dict) and u.get("entry_id") in (acc.get("entry_id"), entry)]
        if gone and not replaces:
            try:
                upload_gate.check_not_uploaded(acc, gone)
            except upload_gate.GateError as e:
                raise FieldsError(str(e)) from e
        if live:
            u = live[0]
            raise FieldsError(f"{slug}: already in the journal as {u['video_id']} "
                              f"({u.get('source')}, {u.get('publish_at')}) - a re-upload names "
                              f"the video it replaces with --replaces")
    sec = publish_note.sections(text)
    title, description = publish_note.title_and_description(sec)
    try:
        at = publish_note.publish_time(sec.get("Публикация", ""))
    except publish_note.NoteError as e:
        raise FieldsError(f"{_rel(note, root)}: {e}") from e
    if at is None:
        raise FieldsError(f"{_rel(note, root)}: no slot in `## Публикация` - the card is not in a "
                          f"slot of the queue yet (publish_card.py place, CF-0587)")
    sched = schedule_of(at, _slot_zone(ch, root))
    if publish_layout.DAY_RE.match(str(bucket)) and sched["msk_day"] != bucket:
        raise FieldsError(f"{_rel(note, root)}: the slot {sched['msk']} is not the day folder "
                          f"{bucket} - move it (runlog publish assign) or fix the slot")
    if stage != "record" and at <= now_utc(now):
        raise FieldsError(f"{slug}: the slot {sched['msk']} is in the past - Studio cannot "
                          f"schedule it; take the next free slot (publish_queue.py next)")
    tags = split_tags(sec.get("Теги", ""))
    form, ask = form_fields(sec.get("Настройки", ""))
    video = note.with_suffix(".mp4")
    return {
        "task": TASK,
        "channel": ch,
        "slug": slug,
        "entry_id": acc.get("entry_id") or entry,
        "note": _rel(note, root),
        "video_file": _rel(video, root),
        "file_name": video.name,
        "studio_draft_title": slug,
        "title": title,
        "description": description,
        "tags": tags,
        "tags_input": ", ".join(tags),
        "tags_length": publish_note.tags_length(tags),
        "tags_max": publish_note.TAGS_MAX,
        "visibility": VISIBILITY,
        "visibility_studio": VISIBILITY_STUDIO,
        "schedule": sched,
        "form": form,
        "ask_user": ask,
        "notices": notices,
    }


# ------------------------------------------------------------------ verify
def norm_text(text):
    s = unicodedata.normalize("NFC", str(text or ""))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    for a, b in SPACES.items():
        s = s.replace(a, b)
    s = ZERO_WIDTH.sub("", s)
    s = "\n".join(line.rstrip() for line in s.split("\n")).strip()
    return re.sub(r"\n{3,}", "\n\n", s)


def norm_title(text):
    return re.sub(r"\s+", " ", norm_text(text)).strip()


def norm_tags(tags):
    if isinstance(tags, str):
        tags = split_tags(tags)
    return [norm_title(t) for t in (tags or []) if norm_title(t)]


def parse_read_time(read):
    """The scheduled instant of a read (aware UTC); FieldsError when the read
    names none or names it without a zone."""
    if read.get("publish_at"):
        try:
            when, _tz, _day = upload_records.parse_slot(read["publish_at"], "UTC")
        except upload_records.JournalError as e:
            raise FieldsError(f"read publish_at: {e}") from e
        return datetime.fromisoformat(when).astimezone(timezone.utc)
    sch = read.get("schedule")
    if not isinstance(sch, dict):
        raise FieldsError("the read has neither `publish_at` nor `schedule` - read the time "
                          "back from the Studio page")
    m = DATE_TEXT.search(str(sch.get("date_text") or ""))
    iso = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$", str(sch.get("date") or ""))
    if iso:
        y, mo, d = (int(x) for x in iso.groups())
    elif m:
        d, word, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mo = next((n for stem, n in MONTH_STEMS if word.startswith(stem)), None)
        if mo is None:
            raise FieldsError(f"read date {sch.get('date_text')!r}: unknown month {word!r}")
    else:
        raise FieldsError(f"read schedule has no date ({sch!r})")
    t = TIME_TEXT.match(str(sch.get("time") or ""))
    if not t:
        raise FieldsError(f"read schedule time {sch.get('time')!r} is not HH:MM")
    z = GMT_TEXT.search(str(sch.get("zone_text") or "") + " " + str(sch.get("date_text") or ""))
    if not z:
        raise FieldsError("read schedule has no zone (`(GMT+03:00) ...`) - the time alone is not "
                          "a moment; read the zone off the picker")
    sign = -1 if z.group(1) in "-−" else 1
    off = timedelta(hours=int(z.group(2)), minutes=int(z.group(3) or 0)) * sign
    local = datetime(y, mo, d, int(t.group(1)), int(t.group(2)), tzinfo=timezone(off))
    return local.astimezone(timezone.utc)


def compare(fields, read):
    """`[]` when what Studio shows is the card, else the mismatches -
    `{field, expected, read}` each."""
    if not isinstance(read, dict):
        raise FieldsError("the read is not a JSON object")
    out = []

    def miss(field, expected, got):
        out.append({"field": field, "expected": expected, "read": got})

    if norm_title(read.get("title")) != norm_title(fields["title"]):
        miss("title", fields["title"], read.get("title"))
    if norm_text(read.get("description")) != norm_text(fields["description"]):
        exp, got = norm_text(fields["description"]), norm_text(read.get("description"))
        at = next((i for i, (a, b) in enumerate(zip(exp, got)) if a != b), min(len(exp), len(got)))
        miss("description", exp[max(0, at - 30):at + 30], got[max(0, at - 30):at + 30])
    if "tags" not in read:
        miss("tags", fields["tags"], None)
    elif norm_tags(read["tags"]) != norm_tags(fields["tags"]):
        e, g = norm_tags(fields["tags"]), norm_tags(read["tags"])
        miss("tags", {"missing": [t for t in e if t not in g], "extra": [t for t in g if t not in e],
                      "order": e}, g)
    vis = norm_title(read.get("visibility")).lower()
    if vis not in SCHEDULED_WORDS:
        miss("visibility", fields["visibility_studio"], read.get("visibility"))
    want = datetime.fromisoformat(fields["schedule"]["publish_at"]).astimezone(timezone.utc)
    try:
        got = parse_read_time(read)
    except FieldsError as e:
        miss("publish_at", fields["schedule"]["msk"], str(e))
    else:
        if got != want:
            miss("publish_at", fields["schedule"]["msk"],
                 f"{got.astimezone(_zone(MSK)):%Y-%m-%d %H:%M} МСК")
    for name in ("made_for_kids", "altered_content", "paid_promotion"):
        expected = (fields["form"].get(name) or {}).get("value")
        if name in read and expected is not None and read[name] != expected:
            miss(name, expected, read[name])
    return out


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FieldsError(f"{path}: cannot read the Studio read ({e})") from e


def verify(ref, read, root=None, channel=None, day=None, now=None):
    """`(fields, mismatches)`; the card is read with the record-stage gates
    (the schedule is already set when this runs)."""
    fields = prepare(ref, root, channel, day, now, stage="record")
    return fields, compare(fields, read)


# ------------------------------------------------------------------ record
def video_id_of(read):
    for key in ("video_id", "url"):
        value = str(read.get(key) or "").strip()
        if not value:
            continue
        m = re.search(r"(?:shorts/|youtu\.be/|[?&]v=|/video/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
                      value)
        return m.group(1) if m else value
    return None


def record(ref, video_id, read, root=None, channel=None, day=None, now=None, replaces=None,
           dry_run=False):
    """Verify, then write the Studio row (`upload_records.record_studio`,
    source `studio`, `user_edited` false) and bring the ledger's publication
    columns up to date (`publish_window.record_published`). Returns
    `{status, row, ledger, fields}`; FieldsError on a mismatch - nothing is
    written then."""
    root = Path(root or ROOT)
    paths = _paths(root)
    video_id = upload_records.check_video_id(video_id)
    shown = video_id_of(read)
    if shown and shown != video_id:
        raise FieldsError(f"--video-id {video_id} is not the video the read names ({shown})")
    fields, mism = verify(ref, read, root, channel, day, now)
    if mism:
        raise FieldsError("Studio does not show the card - nothing written: "
                          + "; ".join(m["field"] for m in mism))
    try:
        status, row = upload_records.record_studio(
            fields["channel"], video_id, fields["schedule"]["publish_at"],
            entry=fields["entry_id"], note=fields["note"], replaces=replaces,
            tz=fields["schedule"]["zone"], path=paths["journal"], log_path=paths["log"],
            now=None if now is None else now_utc(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            dry_run=dry_run)
    except upload_records.JournalError as e:
        raise FieldsError(str(e)) from e
    ledger = None
    if not dry_run:
        import publish_window                                   # noqa: PLC0415
        try:
            ledger = publish_window.record_published(fields["channel"], root, now,
                                                     journal=paths["journal"])
        except Exception as e:                                  # noqa: BLE001
            ledger = {"error": f"{e.__class__.__name__}: {e}"}
    return {"status": status, "row": row, "ledger": ledger, "fields": fields}


# ------------------------------------------------------------------ the 2.0 exit
def streak(rows, channel=None):
    """The Studio videos (`source: studio`) in recording order and how many of
    the latest ones in a row carry no hand edit of the user."""
    mine = sorted((r for r in rows if r.get("source") == "studio"
                   and (channel is None or r.get("channel") == channel)),
                  key=lambda r: (str(r.get("recorded_at") or ""), str(r.get("slug") or "")))
    n = 0
    for r in reversed(mine):
        if r.get("user_edited"):
            break
        n += 1
    last = next((r for r in reversed(mine) if r.get("user_edited")), None)
    return {"streak": n, "goal": STREAK_GOAL, "studio_videos": len(mine), "done": n >= STREAK_GOAL,
            "run": [r.get("slug") for r in mine[len(mine) - n:]],
            "last_edited": None if last is None else {
                "slug": last.get("slug"), "video_id": last.get("video_id"),
                "at": last.get("user_edited_at"), "note": last.get("user_edit_note")}}


# ------------------------------------------------------------------ the command
def _print_mismatches(mism, out):
    for m in mism:
        print(f"MISMATCH {m['field']}: card {json.dumps(m['expected'], ensure_ascii=False)} | "
              f"Studio {json.dumps(m['read'], ensure_ascii=False)}", file=out)


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


def notify_upload(fields, root=None, replaces=None):
    """CF-0591: the card is ready for Studio - the user's gate is to drag the
    file in and say "загрузил". One notification per acceptance (a re-upload
    that replaces a video is its own), linked to the file to drag. Never
    raises.

    CF-0857: the factory does not know Studio's drafts (the Studio read,
    `agents/analyst/studio_read.py`, reads published videos' analytics, not the
    Shorts drafts), so the caller says it: `prepare --uploaded` - the Studio
    path, run after the user's «загрузил» - sends nothing. 21 of the 22
    notifications sent up to 23.10 were followed by the Studio record of that
    video within 4-22 minutes: the request reached a user who had already
    uploaded (23.10 Tech `anthropic`, draft n78gsMRH1QQ).

    CF-0925: since 25.10 the driver uploads, not the user - the request «загрузите
    ... и напишите «загрузил»» reached nobody who had to act, and its file path
    is no use on a phone. The event stays in the journal (the center lists it:
    the card is ready for Studio) and on this Mac (`local_only`: log, macos),
    never in Telegram; what the user sees there is the upload itself
    (`notify_uploaded`, after `record`)."""
    try:
        bus = _notify_bus()
        if bus is None:
            return None
        ch = fields.get("channel")
        key = f"upload:{fields.get('entry_id')}" + (f":replaces:{replaces}" if replaces else "")
        video = Path(root or ROOT) / fields.get("video_file", "")
        when = bus.msk_short((fields.get("schedule") or {}).get("publish_at"))
        return bus.send("upload", key,
                        f"{bus.channel_label(ch, root)}: «{fields.get('title') or fields.get('slug')}» "
                        f"готов к заливке в Studio" + (f" на {when}" if when else ""),
                        channel=ch, link=str(video), root=Path(root) if root else None,
                        local_only=True)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY upload: {e.__class__.__name__}: {e}", file=sys.stderr)
        return None


def notify_uploaded(res, root=None):
    """CF-0925: «📤 Reel: «<тайтл>» стоит на 12.11 01:00 (отложенная
    публикация)» - one Telegram line per video put into Studio, after the
    command line's `record` wrote its row (the center's Studio record sends
    none: api/publish_net.py). Key `uploaded:<entry>:<video id>`. Never raises."""
    try:
        bus = _notify_bus()
        if bus is None:
            return None
        import notify_human                                     # noqa: PLC0415 (shared/)
        fields, row = res.get("fields") or {}, res.get("row") or {}
        ch = fields.get("channel") or row.get("channel")
        title = fields.get("title") or notify_human.human_slug(fields.get("slug"))
        when = (fields.get("schedule") or {}).get("publish_at") or row.get("publish_at")
        return bus.send("uploaded", f"uploaded:{row.get('entry_id') or fields.get('entry_id')}:"
                                    f"{row.get('video_id')}",
                        notify_human.uploaded_text(ch, title, when, root=root), channel=ch,
                        link=bus.link_of(ch, "feed"), root=Path(root) if root else None)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY uploaded: {e.__class__.__name__}: {e}", file=sys.stderr)
        return None


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description="CF-0018: the Studio fields of a card, their check "
                                             "and the journal row")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "verify", "record"):
        p = sub.add_parser(name)
        p.add_argument("ref", help="the card: publish/<channel>/<day>/<slug>.md or the slug")
        p.add_argument("--channel")
        p.add_argument("--day", help="YYYY-MM-DD: which of two notes of one name")
        p.add_argument("--root", help="data root (default this checkout)")
        p.add_argument("--now", help="ISO with zone (tests)")
        if name == "prepare":
            p.add_argument("--replaces", help="video id a re-upload replaces")
            p.add_argument("--uploaded", action="store_true",
                           help="CF-0857: the file is already in Studio (the user said "
                                "«загрузил», the Studio path) - no «загрузите» notification")
        else:
            p.add_argument("--read", required=True, help="JSON of what Studio shows")
        if name == "record":
            p.add_argument("--video-id", required=True)
            p.add_argument("--replaces")
            p.add_argument("--dry-run", action="store_true")
    ed = sub.add_parser("edited", help="the user corrected a field of this video by hand")
    ed.add_argument("--video-id")
    ed.add_argument("--slug")
    ed.add_argument("--channel")
    ed.add_argument("--note")
    ed.add_argument("--undo", action="store_true", help="the mark was wrong")
    ed.add_argument("--root")
    st = sub.add_parser("streak", help="Studio videos in a row with no hand edit")
    st.add_argument("--channel")
    st.add_argument("--root")
    st.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).absolute() if getattr(args, "root", None) else ROOT
    journal = _paths(root)["journal"]
    try:
        if args.cmd == "prepare":
            fields = prepare(args.ref, root, args.channel, args.day, args.now,
                             replaces=args.replaces)
            print(json.dumps(fields, ensure_ascii=False, indent=2), file=out)
            if not args.uploaded:
                notify_upload(fields, root, replaces=args.replaces)
            return EXIT_OK
        if args.cmd == "verify":
            _fields, mism = verify(args.ref, read_json(args.read), root, args.channel, args.day,
                                   args.now)
            if mism:
                _print_mismatches(mism, out)
                print(f"{len(mism)} mismatch(es) - tell the user before the slot; nothing written",
                      file=out)
                return EXIT_MISMATCH
            print("ok", file=out)
            return EXIT_OK
        if args.cmd == "record":
            read = read_json(args.read)
            try:
                res = record(args.ref, args.video_id, read, root, args.channel, args.day,
                             args.now, replaces=args.replaces, dry_run=args.dry_run)
            except FieldsError as e:
                _f, mism = verify(args.ref, read, root, args.channel, args.day, args.now) \
                    if "Studio does not show" in str(e) else (None, [])
                _print_mismatches(mism, out)
                print(f"refused: {e}", file=out)
                return EXIT_MISMATCH if mism else EXIT_REFUSED
            row = res["row"]
            if not args.dry_run and res["status"] != "exists":
                notify_uploaded(res, root)                      # CF-0925
            print(f"{res['status']}: {row['entry_id']} -> {row['video_id']} "
                  f"({res['fields']['schedule']['msk']}) {row['url']}", file=out)
            led = res["ledger"] or {}
            if led.get("error"):
                print(f"WARNING ledger publication columns not updated: {led['error']}", file=out)
            for c in led.get("conflicts") or []:
                print(f"WARNING ledger conflict: {json.dumps(c, ensure_ascii=False)}", file=out)
            if led.get("filled"):
                print(f"ledger: {', '.join(led['filled'])}", file=out)
            if led.get("shifted"):
                import publish_window                           # noqa: PLC0415
                print(f"ledger: {publish_window.shifted_line(led['shifted'], args.dry_run)}",
                      file=out)
            s = streak(upload_records.uploads(journal), row["channel"])
            print(f"streak: {s['streak']}/{s['goal']} Studio videos in a row with no hand edit",
                  file=out)
            return EXIT_OK
        if args.cmd == "edited":
            row = upload_records.mark_user_edited(args.video_id, args.slug, args.channel,
                                                  edited=not args.undo, note=args.note,
                                                  path=journal)
            s = streak(upload_records.uploads(journal), row["channel"])
            print(f"{row['video_id']} ({row['slug']}): user_edited={row['user_edited']}; "
                  f"streak {s['streak']}/{s['goal']}", file=out)
            return EXIT_OK
        s = streak(upload_records.uploads(journal), args.channel)
        if args.json:
            print(json.dumps(s, ensure_ascii=False, indent=2), file=out)
        else:
            print(f"streak: {s['streak']}/{s['goal']} Studio videos in a row with no hand edit "
                  f"({s['studio_videos']} via Studio in all"
                  + (f"; last edit: {s['last_edited']['slug']} {s['last_edited']['at']}"
                     if s["last_edited"] else "") + ")"
                  + (" - the 2.0 exit is reached" if s["done"] else ""), file=out)
        return EXIT_OK
    except (FieldsError, upload_records.JournalError) as e:
        print(f"refused: {e}", file=out)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

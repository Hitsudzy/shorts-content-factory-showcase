#!/usr/bin/env python3
"""CF-0588: what the orchestrator reads in YouTube Studio - "viewed vs swiped
away" of the channel's last videos - checked, parsed and stored. The script never goes to Studio itself: the page is read by the
orchestrator through Claude in Chrome on one of three hooks (after "загрузил X",
before a channel's batch, the daily insurance), copied into a JSON file "as read
from the page", and handed here. The procedure is `agents/analyst/SKILL.md`,
«Чтение Studio (CF-0588)».

    python3 agents/analyst/studio_read.py plan   --channel C [--now ISO] [--root DIR]
        # the last N published videos of the channel (N: channels/C.json ->
        # analyst.studio_read.last_videos) with their Studio analytics links
    python3 agents/analyst/studio_read.py parse  READ.json [--channel C]
        # check and parse, print the result as JSON, write nothing; exit 2 = refused
    python3 agents/analyst/studio_read.py record READ.json [--channel C]
        # parse, then: viewed/swiped -> analytics/C/studio.jsonl (metrics_store),
        # one line of analytics/C/studio_visits.jsonl. Idempotent: the same read again adds nothing.
        # [--by WHO --via WHAT] (CF-0692, optional): `recorded_by` / `via` in the rows
        # and the visit line; Python: record(parsed, root, now, by="user", via="center")
    python3 agents/analyst/studio_read.py due [--channel C] [--hook upload|batch-start] [--now ISO]
        # exit 1 and `due C: пора читать (...)` when a read is due, 0 when none is

**The read JSON** ("как прочитано со страницы" - raw lines always, recognised
fields when the orchestrator recognised them; the script recognises the rest):

    {"channel": "example-film", "read_at": "2026-10-06T13:15:00+03:00",
     "hook": "upload" | "batch-start" | "daily" | "manual",
     "ui_language": "ru",                                   # optional, else detected
     "videos": [{"video_id": "VV-UM01wb5c" | "url": "https://studio.youtube.com/video/<id>/...",
                 "title": "...", "period_text": "С момента публикации",
                 "lines": ["Досмотрели", "72,4 %", "Пролистали", "27,6 %"],
                 "viewed": "72,4 %", "swiped": "27,6 %"}],  # viewed/swiped optional
     # CF-0639: today's page is «Продолжили смотреть» / «52,1 %» with no swiped
     # value - `swiped_pct` is then null with no warning (never 100 - viewed); a
     # new video's «недостаточно данных» is stored with a `note`, not a WARN
}]}



`videos` absent - the metrics were not read this visit.

**Refused** (exit 2, nothing written): not JSON, no `channel` / `read_at` (with
its zone) / `hook`, a channel without `channels/<C>.json`, `--channel` other
than the file's, or a video id the journal (`publish/uploads.json`) holds under
another channel - Studio was showing another brand channel.

**Never guessed.** A share that is not recognised (no label, no percent, two
different values for one label, the orchestrator's value against the lines') is
`null` with a WARN line, and the lines are kept as read. A video without an id
is not stored as a metric row; it is named in the visit log with its lines.
"""
import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
PUBLISHER = ROOT / "agents" / "publisher"
for _p in (AGENT, PUBLISHER):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import metrics_store as store                                   # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0588"
MSK = ZoneInfo("Europe/Moscow") if ZoneInfo else timezone(timedelta(hours=3))
SETTINGS_KEYS = ("last_videos", "insurance_hours", "hook_min_gap_hours")
STUDIO_VIDEO_URL = "https://studio.youtube.com/video/{id}/analytics/tab-overview/period-default"

VIDEO_ID_RE = re.compile(r"(?:youtube\.com/shorts/|youtu\.be/|studio\.youtube\.com/video/|[?&]v=)"
                         r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
PCT_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*%")

# CF-0639: since 2026-10 Studio shows the share as «Продолжили смотреть» (en
# «Stayed to watch») in Обзор -> «Интерес к контенту • С момента публикации»,
# often with no swiped value at all; the «Реакция зрителей» card pairs it with
# «Не стали смотреть» (values first, labels after - pass the numbers as fields).
VIEWED_LABELS = ("досмотрели", "посмотрели", "смотрели", "продолжили просмотр",
                 "продолжили смотреть", "viewed", "chose to view", "stayed to watch")
SWIPED_LABELS = ("пролистали", "пролистнули", "не стали смотреть", "swiped away", "swiped")
# CF-0639: a new video (< a day, ~200 views) has no share yet - «Удержание
# аудитории»: «Статистика пока недоступна: недостаточно данных.». A normal state,
# kept as a note, not a WARN.
NOT_ENOUGH_DATA_RE = re.compile(r"недостаточно данных|not enough data", re.IGNORECASE)
NOT_ENOUGH_DATA_NOTE = ("not enough data yet: Studio shows no share for this video "
                        "(«Статистика пока недоступна: недостаточно данных.») - normal for a new video")
_LABELS = sorted([(w, "viewed") for w in VIEWED_LABELS] + [(w, "swiped") for w in SWIPED_LABELS],
                 key=lambda x: -len(x[0]))
LABEL_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w, _ in _LABELS) + r")(?!\w)",
                      re.IGNORECASE)
LABEL_OF = {w: m for w, m in _LABELS}

RU_MONTHS = (("янв", 1), ("фев", 2), ("мар", 3), ("апр", 4), ("мая", 5), ("май", 5), ("июн", 6),
             ("июл", 7), ("авг", 8), ("сен", 9), ("окт", 10), ("ноя", 11), ("дек", 12))
EN_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
DATE_PATTERNS = (
    ("iso", re.compile(r"(\d{4})-(\d{2})-(\d{2})")),
    ("dmy", re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})")),
    ("ru", re.compile(r"(?<!\d)(\d{1,2})\s+([а-яё]{3,8})\.?\s+(\d{4})", re.IGNORECASE)),
    ("en_mdy", re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)),
    ("en_dmy", re.compile(r"(?<!\d)(\d{1,2})\s+([a-z]{3,9})\.?,?\s+(\d{4})", re.IGNORECASE)),
)


class ReadError(ValueError):
    """The read is refused: nothing is written."""


# ------------------------------------------------------------------ text helpers

def clean(text):
    if text is None:
        return ""
    t = unicodedata.normalize("NFC", str(text))
    for ch in (" ", " ", " "):
        t = t.replace(ch, " ")
    for ch in ("​", "‌", "‍", "⁠", "﻿"):
        t = t.replace(ch, "")
    return t.strip()


def lines_of(obj):
    raw = obj.get("lines")
    if raw is None:
        raw = obj.get("text")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.splitlines()
    if not isinstance(raw, list):
        raise ReadError(f"`lines` {raw!r}: give a list of strings or one text")
    return [clean(x) for x in raw if clean(x)]


def pct(value):
    """A share 0..100 from `72,4 %`, `72.4%`, 72.4 - or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        m = PCT_RE.search(clean(value))
        if not m:
            return None
        v = float(m.group(1).replace(",", "."))
    return round(v, 2) if 0 <= v <= 100 else None


def parse_date(text):
    t = clean(text)
    if not t:
        return None
    for kind, rx in DATE_PATTERNS:
        m = rx.search(t)
        if not m:
            continue
        try:
            if kind == "iso":
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif kind == "dmy":
                d, mo, y = int(m[1]), int(m[2]), int(m[3])
            elif kind == "ru":
                word = m[2].lower()
                mo = next((n for p, n in RU_MONTHS if word.startswith(p)), None)
                d, y = int(m[1]), int(m[3])
            elif kind == "en_mdy":
                mo, d, y = EN_MONTHS.get(m[1][:3].lower()), int(m[2]), int(m[3])
            else:
                d, mo, y = int(m[1]), EN_MONTHS.get(m[2][:3].lower()), int(m[3])
            if mo:
                return date(y, mo, d).isoformat()
        except ValueError:
            continue
    return None


def video_id_of(obj):
    vid = clean(obj.get("video_id"))
    if vid:
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            raise ReadError(f"video_id {vid!r}: not an 11-character YouTube id")
        return vid
    m = VIDEO_ID_RE.search(clean(obj.get("url")))
    return m.group(1) if m else None


def _instant(text, what="read_at"):
    try:
        dt = datetime.fromisoformat(clean(text).replace("Z", "+00:00"))
    except ValueError:
        raise ReadError(f"{what} {text!r}: give an ISO time with its zone") from None
    if dt.tzinfo is None:
        raise ReadError(f"{what} {text!r}: no zone")
    return dt.astimezone(timezone.utc)


def _utc_text(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _msk(dt):
    return dt.astimezone(MSK).strftime("%d.%m %H:%M МСК")


def detect_language(texts):
    joined = " ".join(texts)
    if re.search(r"[а-яё]", joined, re.IGNORECASE):
        return "ru"
    if re.search(r"[a-z]", joined, re.IGNORECASE):
        return "en"
    return None


# ------------------------------------------------------------------ viewed / swiped

def labels_in_lines(lines):
    """The metrics whose label is on the page at all ({"viewed", "swiped"} or less)."""
    return {LABEL_OF[m.group(1).lower()] for m in LABEL_RE.finditer("\n".join(lines))}


def shares_from_lines(lines):
    """{"viewed": v|None, "swiped": v|None}, warnings. Each label takes the first
    percent after it and before the next label; a label with two different
    values across the text is ambiguous and stays None."""
    text = "\n".join(lines)
    labels = [(m.start(), m.end(), LABEL_OF[m.group(1).lower()]) for m in LABEL_RE.finditer(text)]
    found = {"viewed": [], "swiped": []}
    warnings = []
    for i, (_, end, metric) in enumerate(labels):
        stop = labels[i + 1][0] if i + 1 < len(labels) else len(text)
        vals = [float(m.group(1).replace(",", ".")) for m in PCT_RE.finditer(text[end:stop])]
        if vals:
            found[metric].append(vals[0])
            if len(vals) > 1:
                warnings.append(f"{metric}: extra percents after the label ignored: {vals[1:]}")
    out = {}
    for metric, vals in found.items():
        uniq = sorted(set(vals))
        if len(uniq) == 1 and 0 <= uniq[0] <= 100:
            out[metric] = round(uniq[0], 2)
        else:
            out[metric] = None
            if len(uniq) > 1:
                warnings.append(f"{metric}: two different values in the lines {uniq} - not chosen")
    return out, warnings


def parse_video(obj, channel, read_at, hook, journal_rows):
    if not isinstance(obj, dict):
        raise ReadError(f"video {obj!r}: not an object")
    lines = lines_of(obj)
    vid = video_id_of(obj)
    from_lines, warnings = shares_from_lines(lines)
    on_page = labels_in_lines(lines)
    not_enough = any(NOT_ENOUGH_DATA_RE.search(ln) for ln in lines)
    shares = {}
    for metric in ("viewed", "swiped"):
        given_raw = obj.get(metric)
        given = pct(given_raw)
        if given_raw not in (None, "") and given is None:
            warnings.append(f"{metric}: {given_raw!r} is not a share")
        seen = from_lines[metric]
        if given is not None and seen is not None and abs(given - seen) > 0.05:
            warnings.append(f"{metric}: recognised {given} but the lines say {seen} - not chosen")
            shares[metric] = None
        else:
            shares[metric] = given if given is not None else seen
        if shares[metric] is None and not any(metric in w for w in warnings):
            # CF-0639: swiped is optional - Studio no longer always shows it, and
            # it is never derived as 100 - viewed. A video Studio has no data for
            # yet is a note, not a warning.
            if metric == "swiped" and "swiped" not in on_page and given_raw in (None, ""):
                continue
            if not_enough and metric not in on_page and given_raw in (None, ""):
                continue
            warnings.append(f"{metric}: not recognised in the lines")
    v, s = shares["viewed"], shares["swiped"]
    if v is not None and s is not None and abs(v + s - 100) > 1.0:
        warnings.append(f"viewed {v} + swiped {s} = {round(v + s, 2)}, not ~100")
    entry = None
    for r in journal_rows:
        if r.get("video_id") == vid and r.get("channel") == channel:
            entry = r.get("entry_id")
    if vid and entry is None:
        warnings.append(f"{vid}: not in publish/uploads.json of {channel}")
    note = NOT_ENOUGH_DATA_NOTE if not_enough and v is None and s is None else None
    row = {"kind": "studio", "channel": channel, "video_id": vid, "entry_id": entry,
           "read_at": _utc_text(read_at), "hook": hook,
           "period_text": clean(obj.get("period_text")) or None,
           "viewed_pct": v, "swiped_pct": s, "raw_lines": lines,
           "warnings": warnings, "note": note, "title": clean(obj.get("title")) or None}
    if row["period_text"] is None and note is None:
        warnings.append("period_text: the period the shares cover was not copied")
    return row


# ------------------------------------------------------------------ settings / journal

def channel_config(channel, root=None):
    p = Path(root or ROOT) / "channels" / f"{channel}.json"
    if not p.is_file():
        raise ReadError(f"channel {channel!r} has no channels/{channel}.json - a typo?")
    return json.loads(p.read_text(encoding="utf-8"))


def studio_settings(channel, root=None):
    cfg = (channel_config(channel, root).get("analyst") or {}).get("studio_read")
    if not isinstance(cfg, dict):
        raise ReadError(f"channels/{channel}.json has no analyst.studio_read "
                        f"({', '.join(SETTINGS_KEYS)})")
    for k in SETTINGS_KEYS:
        v = cfg.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ReadError(f"channels/{channel}.json analyst.studio_read.{k} = {v!r}: "
                            f"give a positive number")
    return cfg


def no_pipeline(channel, root=None):
    """CF-0562: the «конвейера нет» line of a channel whose config says
    `status: no_pipeline` (shared/channel_ids.py, by path), None otherwise."""
    import importlib.util                                       # noqa: PLC0415
    spec = importlib.util.spec_from_file_location(
        "channel_ids_for_studio_read", ROOT / "shared" / "channel_ids.py")
    ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ids)
    try:
        return ids.channel_no_pipeline(channel, root or ROOT)
    except (OSError, ValueError, ids.ChannelIdError):
        return None


def all_channels(root=None):
    return sorted(p.stem for p in (Path(root or ROOT) / "channels").glob("*.json"))


def journal_path(root=None):
    return Path(root or ROOT) / "publish" / "uploads.json"


def store_root(root=None):
    return Path(root or ROOT) / "analytics"


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    return _instant(now, "now")


def last_videos(channel, root=None, now=None):
    """The channel's last N published live videos, newest first."""
    n = int(studio_settings(channel, root)["last_videos"])
    now = _now(now)
    out = []
    for r in upload_records.uploads(journal_path(root), channel=channel):
        if r.get("removed_at") or not r.get("video_id"):
            continue
        at = r.get("publish_at")
        if at:
            when = _instant(at, "publish_at")
        elif r.get("publish_day"):
            when = datetime.fromisoformat(r["publish_day"]).replace(tzinfo=MSK)
        else:
            continue
        if when <= now:
            out.append((when, r))
    out.sort(key=lambda x: x[0], reverse=True)
    return [dict(r, _published=w) for w, r in out[:n]], n


# ------------------------------------------------------------------ parse / record

def parse_read(doc, channel=None, root=None):
    """Check and parse a read; reads the channel config and the upload journal,
    writes nothing (the command center calls it for the plan, CF-0692)."""
    if not isinstance(doc, dict):
        raise ReadError("the read is not a JSON object")
    ch = clean(doc.get("channel"))
    if not ch:
        raise ReadError("no `channel` in the read - which channel was Studio showing?")
    if channel and channel != ch:
        raise ReadError(f"--channel {channel} but the read is of {ch}")
    channel_config(ch, root)
    if not doc.get("read_at"):
        raise ReadError("no `read_at` - when was the page read (ISO with zone)?")
    read_at = _instant(doc["read_at"])
    hook = clean(doc.get("hook"))
    if hook not in store.HOOKS:
        raise ReadError(f"hook {hook!r}: one of {', '.join(store.HOOKS)}")
    journal = upload_records.uploads(journal_path(root))
    warnings = []

    videos, unstored = [], []
    raw_videos = doc.get("videos")
    if raw_videos is None:
        warnings.append("videos: not read this visit (no `videos`)")
        raw_videos = []
    if not isinstance(raw_videos, list):
        raise ReadError("`videos` is not a list")
    for obj in raw_videos:
        row = parse_video(obj, ch, read_at, hook, journal)
        vid = row["video_id"]
        if vid:
            other = sorted({r.get("channel") for r in journal
                            if r.get("video_id") == vid and r.get("channel") != ch})
            if other:
                raise ReadError(f"video {vid} is of channel {other[0]} in publish/uploads.json, "
                                f"not {ch} - Studio was showing another channel; nothing written")
            videos.append(row)
        else:
            unstored.append({"title": row["title"], "raw_lines": row["raw_lines"],
                             "warnings": row["warnings"] + ["no video id - not stored"]})
    seen = {}
    for row in videos:
        if row["video_id"] in seen:
            raise ReadError(f"video {row['video_id']} is twice in one read")
        seen[row["video_id"]] = row

    texts = [ln for v in videos for ln in v["raw_lines"]]
    return {"channel": ch, "read_at": _utc_text(read_at), "hook": hook,
            "ui_language": clean(doc.get("ui_language")) or detect_language(texts),
            "videos": videos, "unstored": unstored,
            "warnings": warnings}


WHO_MAX = 40


def _who(value, what):
    """CF-0692: `by` / `via` of a record - None (not given) or a short
    non-empty single-line string."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReadError(f"{what}={value!r}: a short non-empty string (e.g. by='user', via='center') "
                        f"or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise ReadError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def record(parsed, root=None, now=None, by=None, via=None):
    """Write what `parse_read` returned. `by` / `via` (CF-0692, optional): who
    recorded it and through what - the command center passes by="user",
    via="center" after the user confirmed its plan; they go into every
    studio.jsonl row (`recorded_by`, `via`) and the studio_visits.jsonl line.
    Without them the rows and the visit line are exactly as before."""
    who = {k: v for k, v in (("recorded_by", _who(by, "by")), ("via", _who(via, "via")))
           if v is not None}
    ch = parsed["channel"]
    st = store_root(root)
    at = _utc_text(_now(now))
    rows = [{k: v for k, v in dict(r, recorded_at=at, **who).items() if k in store.STUDIO_KEYS}
            for r in parsed["videos"]]
    counts = store.merge_studio(ch, rows, st)
    visit = {"read_at": parsed["read_at"], "hook": parsed["hook"],
             "ui_language": parsed["ui_language"], "recorded_at": at,
             "videos_read": len(parsed["videos"]) + len(parsed["unstored"]),
             "videos_stored": len(parsed["videos"]),
             "unstored": parsed["unstored"],
             # CF-0639: swiped is optional; a video Studio has no data for yet
             # is "not ready", not "unrecognised"
             "metrics_unrecognised": sorted(r["video_id"] for r in parsed["videos"]
                                            if r["viewed_pct"] is None and not r.get("note")),
             "metrics_not_ready": sorted(r["video_id"] for r in parsed["videos"]
                                         if r.get("note")),
             "warnings": parsed["warnings"]}
    visit.update(who)
    logged = store.append_visit(ch, visit, st)
    return {"studio": counts, "visit_logged": logged}


def _print_parse_warnings(parsed, out):
    for w in parsed["warnings"]:
        out.write(f"WARN {w}\n")
    for r in parsed["videos"]:
        for w in r["warnings"]:
            out.write(f"WARN {r['video_id']}: {w}\n")
        if r.get("note"):
            out.write(f"NOTE {r['video_id']}: {r['note']}\n")
    for u in parsed["unstored"]:
        out.write(f"WARN video {u['title']!r}: no video id - lines kept in the visit log, "
                  f"not stored as a metric\n")


# ------------------------------------------------------------------ due

def due(channel, root=None, now=None, hook=None):
    """(is_due, line). Without a hook: the daily insurance - due when the last
    read is older than insurance_hours (or there is
    none). With a hook: due unless such a read is younger than
    hook_min_gap_hours (two hooks in a row are one visit)."""
    cfg = studio_settings(channel, root)
    now = _now(now)
    last = store.last_visit(channel, store_root(root))
    if last is None:
        why = f"хук {hook}" if hook else "страховка"
        return True, f"due {channel}: пора читать ({why}: ни одного чтения Studio)"
    at = _instant(last["read_at"])
    age_h = (now - at).total_seconds() / 3600
    if hook:
        gap = float(cfg["hook_min_gap_hours"])
        if age_h < gap:
            return False, (f"ok {channel}: хук {hook} - последнее чтение {_msk(at)}, "
                           f"{age_h:.1f} ч назад (< {gap:g} ч), не перечитывать")
        return True, (f"due {channel}: пора читать (хук {hook}; последнее чтение {_msk(at)}, "
                      f"{age_h:.1f} ч назад)")
    window = float(cfg["insurance_hours"])
    if age_h > window:
        return True, (f"due {channel}: пора читать (страховка: >{window:g} ч; последнее чтение "
                      f"{_msk(at)}, {age_h:.1f} ч назад)")
    return False, (f"ok {channel}: последнее чтение {_msk(at)}, {age_h:.1f} ч назад; "
                   f"страховка через {window - age_h:.1f} ч")


# ------------------------------------------------------------------ CLI

def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReadError(f"{path}: {e}") from None


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="studio_read.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "parse", "record", "due"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None, help="the factory root (tests)")
        p.add_argument("--channel", default=None)
        if name in ("parse", "record"):
            p.add_argument("read", help="the read JSON")
        if name in ("plan", "due", "record"):
            p.add_argument("--now", default=None)
        if name == "record":                                    # CF-0692, optional
            p.add_argument("--by", default=None, help="who records it (e.g. user)")
            p.add_argument("--via", default=None, help="through what (e.g. center)")
        if name == "due":
            p.add_argument("--hook", choices=("upload", "batch-start"), default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "plan":
            if not args.channel:
                raise ReadError("plan: --channel")
            vids, n = last_videos(args.channel, args.root, args.now)
            out.write(f"{args.channel}: последние {len(vids)} из N={n} опубликованных роликов\n")
            for r in vids:
                out.write(f"{r['video_id']}  {_msk(r['_published'])}  {r.get('slug') or ''}  "
                          f"{STUDIO_VIDEO_URL.format(id=r['video_id'])}\n")
            return 0
        if args.cmd in ("parse", "record"):
            parsed = parse_read(_load(args.read), args.channel, args.root)
            if args.cmd == "parse":
                out.write(json.dumps(parsed, ensure_ascii=False, indent=1) + "\n")
                _print_parse_warnings(parsed, out)
                return 0
            res = record(parsed, args.root, args.now, by=args.by, via=args.via)
            _print_parse_warnings(parsed, out)
            ch = parsed["channel"]
            c = res["studio"]
            out.write(f"studio {ch} {parsed['read_at']} ({parsed['hook']}): роликов "
                      f"{len(parsed['videos'])} (+{c['added']} ~{c['replaced']} ={c['unchanged']}), "
                      f"без id {len(parsed['unstored'])}"
                      + ("" if res["visit_logged"] else "; это чтение уже записано") + "\n")
            return 0
        if args.cmd == "due":
            names = [args.channel] if args.channel else all_channels(args.root)
            any_due = False
            for ch in names:
                stub = None if args.channel else no_pipeline(ch, args.root)
                if stub:                                        # CF-0562
                    out.write(f"skip {ch}: {stub} - читать в Studio нечего\n")
                    continue
                try:
                    d, line = due(ch, args.root, args.now, args.hook)
                except ReadError as e:
                    if args.channel:
                        raise
                    out.write(f"skip {ch}: {e}\n")
                    continue
                any_due = any_due or d
                out.write(line + "\n")
            return 1 if any_due else 0
    except (ReadError, store.StoreError, upload_records.JournalError) as e:
        out.write(f"refused: {e}\n")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

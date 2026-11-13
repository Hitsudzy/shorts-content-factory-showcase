#!/usr/bin/env python3
"""CF-0020: the Analyst's metrics store - one writer, one reader.

Where and why
-------------
`analytics/<channel>/daily.jsonl` in the root checkout, one line per
(video, day) of YouTube Analytics:

    {"channel": "example-film", "video_id": "VV-UM01wb5c",
     "entry_id": "example-film/2026-09-26T0912Z/primetime", "day": "2026-09-27",
     "age": 0, "views": 120, "engagedViews": 81, "averageViewPercentage": 63.2,
     "averageViewDuration": 21, "likes": 4, "subscribersGained": 1,
     "final": true, "collected_at": "2026-10-06T09:00:00Z"}

* **A daily series, not a running total.** The question the Analyst asks is
  "how did video A do in its first N days against video B in its first N"
  (CF-0021/0022): that needs the same window on every video, and a cumulative
  snapshot taken "on the day of the collection" gives every video a different
  age. The daily rows give the curves and the "final" marks; `age` is the
  day's distance from the publication day (both in Pacific time, the time zone
  YouTube Analytics counts days in), so "first 3 days" is `age < 3`.
* **A window is YouTube's own number, never recombined here** (CF-0624,
  III.E.4.h(i) of the YouTube API policy - "similar, independently calculated
  data"). The daily rows are not summed or averaged into a window; the window
  is its own `reports.query` over `startDate..endDate` without `dimensions`,
  so YouTube computes `averageViewDuration` / `averageViewPercentage` (and the
  counts) of the period itself - `windows.jsonl` below, `window()` reads it.
* **`views` vs `engagedViews`.** Since 2025-03-31 a Shorts view is counted from
  the first frame, with no minimum watch time; `engagedViews` carries the old
  meaning. Videos are compared by `engagedViews` (task CF-0020, 2026-09-18).
  `null` there means the metric could not be fetched (the run log names why),
  not zero.
* **`final`.** YouTube Analytics data lags by ~2-3 days and the last days keep
  changing. A day is final once it is at least `FINAL_LAG_DAYS` before the
  day it was collected on (Pacific). A non-final row is replaced by the next
  collection; a final one is not asked for again (`resume_day()`).
* **Idempotent.** The key is (video_id, day): collecting the same day again
  replaces the row, never adds a second one. The file is rewritten whole,
  sorted, through a temp file and a rename - a run killed half-way leaves the
  old file, never half of a new one. Nothing is ever deleted here: a video
  removed from the channel keeps its rows (the journal's `removed_at` only
  stops further collection). The one deleter is the YouTube API policy's
  (CF-0618, `agents/publisher/api_data.py`): `daily.jsonl`, `windows.jsonl`,
  `runs.jsonl` and `summary/` go after a revocation past its term or on the
  owner's request.
* **Per channel**, a directory each, so a second channel's numbers never mix
  with the first's and a channel can be archived on its own.

`analytics/<channel>/windows.jsonl` (CF-0624) - one line per (video, window)
of YouTube's own totals over a window, asked as such (`reports.query` without
`dimensions`, `filters=video==<id>`):

    {"channel": "example-film", "video_id": "VV-UM01wb5c", "entry_id": "...",
     "window": "first7d", "first_days": 7, "start": "2026-09-26",
     "end": "2026-10-02", "complete": true, "views": 900, "engagedViews": 610,
     "averageViewPercentage": 61.4, "averageViewDuration": 20.3, "likes": 31,
     "subscribersGained": 4, "final": true, "collected_at": "...",
     "source": "youtube-analytics reports.query, no dimensions"}

* **Which windows** - `WINDOW_DAYS`: the first N days of a video, N = 7 (the
  summary's `--first-days` default and `metrics.py show`'s). A reader asking
  for another N finds no row and says so; adding N here makes `collect` ask it.
* **`start..end`** - the publication day (Pacific) to the window's last day
  (`start + N - 1`), cut at the collection's `--day` (yesterday, Pacific, as
  the daily rows): a video younger than N days has `complete: false`.
* **`final`** - complete and its last day final by the same 3-day lag as a
  daily row. A non-final row is asked again by the next `collect` and
  replaced; a final one is never asked again (`window_due()`).
* **No row, no number.** A video with daily rows but no window row (collected
  before CF-0624, or the window not answered yet) has no window: the readers
  say "no YouTube window", they never recompute one from the daily rows.

`analytics/<channel>/runs.jsonl` - append-only, one line per collection run of
the channel: when, up to which day, how many videos were asked, which were
skipped and why (`removed`, `not-yet-published`, `no-data-yet`, ...), which
metrics were unavailable, the outcome. The "пропуск с пометкой" of the task
lives there, so a skipped video is never silent.

`analytics/<channel>/studio.jsonl` (CF-0588) - what was read in YouTube Studio,
kept apart from the API's daily series on purpose: "viewed vs swiped away" of
a Short is not in the API, Studio shows it as a share over a period it names
("Since published", "Last 28 days"), not per day. One row per (video, read):

    {"kind": "studio", "channel": "example-film", "video_id": "VV-UM01wb5c",
     "entry_id": "...", "read_at": "2026-10-06T10:15:00Z", "hook": "upload",
     "period_text": "С момента публикации", "viewed_pct": 72.4,
     "swiped_pct": 27.6, "raw_lines": ["Досмотрели 72,4 %", "Пролистали 27,6 %"],
     "warnings": [], "recorded_at": "2026-10-06T10:16:02Z"}

CF-0692: `recorded_by` / `via` (who recorded the read and through what - the
command center writes `"user"` / `"center"`) follow `recorded_at` only when
`studio_read.record(..., by=, via=)` was given them; a row recorded from the
terminal has neither and is byte-equal to the rows from before. They describe
the write, not the read: re-recording the same read differing only in them (or
in `recorded_at`) is "unchanged" and the first row is kept.

The key is (video_id, read_at): recording the same read again replaces the row,
a later read is a new row (a snapshot of its own time). A share that could not
be recognised is `null` with a warning, and the lines it was looked for in are
kept as read - never guessed. `latest_studio()` gives the last read of a video.
CF-0639: `swiped_pct` is optional (Studio may show only «Продолжили смотреть»)
and is never derived; a video Studio has no data for yet («недостаточно
данных») has both shares `null` and a `note` instead of warnings.

`analytics/<channel>/studio_visits.jsonl` (CF-0588) - append-only, one line per
Studio visit of the channel: when it was read, on which hook, how many videos,
whether the copyright tab was read. `studio_read.py due` reads it. CF-0692: the
same `recorded_by` / `via`, only when given.

The repository is the factory's own data, committed like `publish/uploads.json`.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
STORE = ROOT / "analytics"
TASK = "CF-0020"

DAILY = "daily.jsonl"
WINDOWS = "windows.jsonl"
RUNS = "runs.jsonl"
STUDIO = "studio.jsonl"
VISITS = "studio_visits.jsonl"
STUDIO_TASK = "CF-0588"
HOOKS = ("upload", "batch-start", "daily", "manual")
STUDIO_KEYS = ("kind", "channel", "video_id", "entry_id", "read_at", "hook", "period_text",
               "viewed_pct", "swiped_pct", "raw_lines", "warnings", "note", "recorded_at",
               "recorded_by", "via")
# Written only when set, so rows without them stay byte-equal to older ones:
# `note` (CF-0639); `recorded_by` / `via` (CF-0692: who recorded the read and
# through what, e.g. "user" / "center"; the terminal path sets neither).
STUDIO_OPTIONAL = ("note", "recorded_by", "via")
# About the write, not the read: a re-record differing only in these is "unchanged".
STUDIO_RECORD_META = ("recorded_at", "recorded_by", "via")

# A day this many days (or more) before the collection day is final.
FINAL_LAG_DAYS = 3

COUNT_METRICS = ("views", "engagedViews", "likes", "subscribersGained")
AVERAGE_METRICS = ("averageViewDuration", "averageViewPercentage")
METRICS = ("views", "engagedViews", "averageViewPercentage", "averageViewDuration",
           "likes", "subscribersGained")
ROW_KEYS = ("channel", "video_id", "entry_id", "day", "age") + METRICS + ("final", "collected_at")

WINDOW_TASK = "CF-0624"
# The windows every reader asks for (summary.py DEFAULT_FIRST_DAYS, metrics.py show).
WINDOW_DAYS = (7,)
WINDOW_SOURCE = "youtube-analytics reports.query, no dimensions"
WINDOW_KEYS = ("channel", "video_id", "entry_id", "window", "first_days", "start", "end",
               "complete") + METRICS + ("final", "collected_at", "source")


class StoreError(ValueError):
    pass


def channel_dir(channel, root=None):
    if not channel or "/" in channel or channel.startswith("."):
        raise StoreError(f"channel {channel!r}: not a channel id")
    return Path(root or STORE) / channel


def _day(text):
    try:
        return date.fromisoformat(str(text))
    except ValueError:
        raise StoreError(f"day {text!r}: give YYYY-MM-DD") from None


def is_final(day, collected_on, lag=FINAL_LAG_DAYS):
    """True when `day` is at least `lag` days before `collected_on`."""
    return (_day(collected_on) - _day(day)).days >= lag


def check_row(row):
    if not isinstance(row, dict):
        raise StoreError(f"row {row!r}: not an object")
    for k in ("channel", "video_id", "day", "final", "collected_at"):
        if row.get(k) in (None, ""):
            raise StoreError(f"row {row.get('video_id')}/{row.get('day')}: `{k}` is missing")
    _day(row["day"])
    for m in METRICS:
        v = row.get(m)
        if v is not None and not isinstance(v, (int, float)):
            raise StoreError(f"row {row['video_id']}/{row['day']}: {m}={v!r} is not a number")
    return row


def read_daily(channel, root=None):
    """Every stored row of the channel, in file order (video_id, day)."""
    p = channel_dir(channel, root) / DAILY
    if not p.is_file():
        return []
    rows = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(check_row(json.loads(line)))
        except ValueError as e:
            raise StoreError(f"{p}:{n}: {e}") from e
    return rows


def _key(row):
    return (row["video_id"], row["day"])


def _atomic_write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def merge(channel, rows, root=None):
    """Put `rows` into the channel's file: a (video, day) already there is
    replaced, a new one added. Returns {"added": n, "replaced": n, "unchanged": n}."""
    current = {_key(r): r for r in read_daily(channel, root)}
    counts = {"added": 0, "replaced": 0, "unchanged": 0}
    for row in rows:
        check_row(row)
        if row["channel"] != channel:
            raise StoreError(f"row {row['video_id']}/{row['day']} is of channel "
                             f"{row['channel']!r}, not {channel!r}")
        clean = {k: row.get(k) for k in ROW_KEYS}
        old = current.get(_key(clean))
        if old is None:
            counts["added"] += 1
        elif {k: v for k, v in old.items() if k != "collected_at"} == \
                {k: v for k, v in clean.items() if k != "collected_at"}:
            counts["unchanged"] += 1
        else:
            counts["replaced"] += 1
        current[_key(clean)] = clean
    if rows:
        text = "".join(json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current))
        _atomic_write(channel_dir(channel, root) / DAILY, text)
    return counts


def video_rows(rows, video_id):
    return sorted((r for r in rows if r["video_id"] == video_id), key=lambda r: r["day"])


def resume_day(rows, video_id, first_day):
    """The first day still worth asking for: the day after the last final day
    stored for the video, else `first_day` (its publication day)."""
    days = [r["day"] for r in video_rows(rows, video_id) if r.get("final")]
    first = _day(first_day)
    if not days:
        return first
    return max(first, _day(max(days)) + timedelta(days=1))


def window_name(first_days):
    return f"first{int(first_days)}d"


def window_span(published, first_days, end):
    """(start, end, complete) of the window "first `first_days` days" of a
    video published on `published` (Pacific day), cut at `end`."""
    start = _day(published)
    full = start + timedelta(days=int(first_days) - 1)
    last = min(full, _day(end))
    return start, last, last == full


def check_window_row(row):
    if not isinstance(row, dict):
        raise StoreError(f"window row {row!r}: not an object")
    for k in ("channel", "video_id", "window", "first_days", "start", "end", "final",
              "collected_at"):
        if row.get(k) in (None, ""):
            raise StoreError(f"window row {row.get('video_id')}/{row.get('window')}: "
                             f"`{k}` is missing")
    if row["window"] != window_name(row["first_days"]):
        raise StoreError(f"window row {row['video_id']}: window {row['window']!r} is not "
                         f"first_days={row['first_days']!r}")
    if _day(row["end"]) < _day(row["start"]):
        raise StoreError(f"window row {row['video_id']}/{row['window']}: end before start")
    for m in METRICS:
        v = row.get(m)
        if v is not None and not isinstance(v, (int, float)):
            raise StoreError(f"window row {row['video_id']}/{row['window']}: {m}={v!r} "
                             f"is not a number")
    return row


def read_windows(channel, root=None):
    """Every stored window row of the channel (CF-0624), in file order."""
    p = channel_dir(channel, root) / WINDOWS
    if not p.is_file():
        return []
    rows = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(check_window_row(json.loads(line)))
        except ValueError as e:
            raise StoreError(f"{p}:{n}: {e}") from e
    return rows


def _wkey(row):
    return (row["video_id"], row["window"])


def merge_windows(channel, rows, root=None):
    """Put window rows into the channel's `windows.jsonl`: the same (video,
    window) again replaces, never adds. Returns {"added", "replaced", "unchanged"}."""
    current = {_wkey(r): r for r in read_windows(channel, root)}
    counts = {"added": 0, "replaced": 0, "unchanged": 0}
    for row in rows:
        check_window_row(row)
        if row["channel"] != channel:
            raise StoreError(f"window row {row['video_id']} is of channel {row['channel']!r}, "
                             f"not {channel!r}")
        clean = {k: row.get(k) for k in WINDOW_KEYS}
        old = current.get(_wkey(clean))
        if old is None:
            counts["added"] += 1
        elif {k: v for k, v in old.items() if k != "collected_at"} == \
                {k: v for k, v in clean.items() if k != "collected_at"}:
            counts["unchanged"] += 1
        else:
            counts["replaced"] += 1
        current[_wkey(clean)] = clean
    if rows:
        text = "".join(json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current))
        _atomic_write(channel_dir(channel, root) / WINDOWS, text)
    return counts


def window_due(wrows, video_id, first_days):
    """True unless a final row of the window is stored - a final window is
    never asked again, a missing or non-final one is."""
    name = window_name(first_days)
    return not any(r["video_id"] == video_id and r["window"] == name and r.get("final")
                   for r in wrows)


def window(wrows, video_id, first_days, up_to=None):
    """YouTube's own totals of the video's first `first_days` days - the stored
    row of `windows.jsonl` (CF-0624), or None when there is none. Never a sum
    or a recombined average of the daily rows: no row, no window. With
    `up_to` (a day) a row reaching past it is not that day's window -> None.
    The row comes with `from`/`to` (= start/end) and `days` (its length)."""
    name = window_name(first_days)
    for r in wrows:
        if r["video_id"] == video_id and r["window"] == name:
            if up_to is not None and _day(r["end"]) > _day(up_to):
                return None
            return dict(r, **{"from": r["start"], "to": r["end"],
                              "days": (_day(r["end"]) - _day(r["start"])).days + 1})
    return None


def append_run(channel, record, root=None):
    """One line of the channel's run log (append-only)."""
    p = channel_dir(channel, root) / RUNS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(record, channel=channel, task=TASK), ensure_ascii=False) + "\n")


def read_runs(channel, root=None):
    p = channel_dir(channel, root) / RUNS
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------ Studio (CF-0588)

def _instant(text, what):
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise StoreError(f"{what} {text!r}: give an ISO time with its zone") from None
    if dt.tzinfo is None:
        raise StoreError(f"{what} {text!r}: no zone - a read time without one is ambiguous")
    return dt.astimezone(timezone.utc)


def check_studio_row(row):
    if not isinstance(row, dict):
        raise StoreError(f"studio row {row!r}: not an object")
    if row.get("kind") != "studio":
        raise StoreError(f"studio row {row.get('video_id')}: kind {row.get('kind')!r}, not 'studio'")
    for k in ("channel", "video_id", "read_at", "hook", "recorded_at"):
        if row.get(k) in (None, ""):
            raise StoreError(f"studio row {row.get('video_id')}/{row.get('read_at')}: `{k}` is missing")
    _instant(row["read_at"], "read_at")
    if row["hook"] not in HOOKS:
        raise StoreError(f"studio row {row['video_id']}: hook {row['hook']!r} is not one of {HOOKS}")
    for m in ("viewed_pct", "swiped_pct"):
        v = row.get(m)
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 100):
            raise StoreError(f"studio row {row['video_id']}: {m}={v!r} is not a share 0..100")
    for k in ("recorded_by", "via"):                    # CF-0692: optional, never empty
        if k in row and (not isinstance(row[k], str) or not row[k].strip()):
            raise StoreError(f"studio row {row['video_id']}: {k}={row[k]!r} is not a non-empty string")
    return row


def read_studio(channel, root=None):
    p = channel_dir(channel, root) / STUDIO
    if not p.is_file():
        return []
    rows = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(check_studio_row(json.loads(line)))
        except ValueError as e:
            raise StoreError(f"{p}:{n}: {e}") from e
    return rows


def _studio_key(row):
    return (row["video_id"], _instant(row["read_at"], "read_at").isoformat())


def merge_studio(channel, rows, root=None):
    """Put Studio reads into the channel's `studio.jsonl`; the same (video,
    read_at) again replaces, never adds. Returns {"added", "replaced", "unchanged"}."""
    current = {_studio_key(r): r for r in read_studio(channel, root)}
    counts = {"added": 0, "replaced": 0, "unchanged": 0}
    for row in rows:
        check_studio_row(row)
        if row["channel"] != channel:
            raise StoreError(f"studio row {row['video_id']} is of channel {row['channel']!r}, "
                             f"not {channel!r}")
        # `note` (CF-0639), `recorded_by` / `via` (CF-0692) only when set - rows
        # without them stay byte-equal to the ones from before
        clean = {k: row.get(k) for k in STUDIO_KEYS if k not in STUDIO_OPTIONAL or row.get(k)}
        key = _studio_key(clean)
        old = current.get(key)
        if old is None:
            counts["added"] += 1
        elif {k: v for k, v in old.items() if k not in STUDIO_RECORD_META} == \
                {k: v for k, v in clean.items() if k not in STUDIO_RECORD_META}:
            counts["unchanged"] += 1
            clean = old
        else:
            counts["replaced"] += 1
        current[key] = clean
    if rows:
        text = "".join(json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current))
        _atomic_write(channel_dir(channel, root) / STUDIO, text)
    return counts


def latest_studio(rows, video_id):
    """The last Studio read of the video (by read_at), or None."""
    vr = [r for r in rows if r["video_id"] == video_id]
    return max(vr, key=lambda r: _instant(r["read_at"], "read_at")) if vr else None


def append_visit(channel, record, root=None):
    """One line of the channel's Studio visit log (append-only). A visit with
    the same read_at already logged is not logged twice; returns False then."""
    for v in read_visits(channel, root):
        if _instant(v["read_at"], "read_at") == _instant(record["read_at"], "read_at"):
            return False
    p = channel_dir(channel, root) / VISITS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(record, channel=channel, task=STUDIO_TASK), ensure_ascii=False) + "\n")
    return True


def read_visits(channel, root=None):
    p = channel_dir(channel, root) / VISITS
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def last_visit(channel, root=None):
    """The latest visit (by read_at). None when there is none."""
    vs = read_visits(channel, root)
    return max(vs, key=lambda v: _instant(v["read_at"], "read_at")) if vs else None

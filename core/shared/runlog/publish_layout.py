#!/usr/bin/env python3
"""CF-0475: where a video and its note live in `publish/`.

The user's decisions of 2026-10-01: `publish/` is laid out by channel and by the
day a video goes out, not as one flat heap - and the channel is part of the
path, so two channels never collide.

    publish/<channel>/<YYYY-MM-DD>/<slug>.mp4 + .md   the day it goes out, Moscow
                                                      time (the slot is 01:00 МСК);
                                                      several videos a day are
                                                      several pairs in one folder
    publish/<channel>/_queue/<slug>.mp4 + .md         accepted, no slot yet
    publish/<channel>/_reserve/<slug>.mp4 + .md       CF-0919: the reserve - in Studio,
                                                      taken off its slot (`publish_move.py
                                                      --withdraw`); its name does not
                                                      stand in the way of a new video
    publish/<channel>/_queue|_reserve/<slug>~<batch>.mp4 + .md
                                                      CF-0920: the second video of one name
                                                      in the same waiting folder; a day
                                                      folder never carries the suffix
    publish/README.md, acceptance-log.json,
    publication-holds.json, uploads.json              the journals, at the root -
                                                      their rows carry the channel

`<channel>` is the channel id of `channels/<id>.json` and of the acceptance rows
(a former name resolves to today's id; a `rebuilds/...` row belongs to the
channel the rebuild was made for - with one channel on file, that one). The day
is read from the note's `## Публикация` (`publish_note.publish_time`, converted
to Europe/Moscow), never typed twice. One slug can go out twice (`delver`: the
2026-09-22 render was refused, the 2026-10-01 one went out on 2026-10-07) - the
day folder is what tells the two apart, and every reader asks this module
instead of building `publish/<slug>.mp4` itself.

CF-0920: the suffix is a file's, not a video's. `entries()` answers `slug` (the
name in the journal, the plan, the card - never with the suffix), `stem` (the
file's name) and `batch` (the suffix or None); a reader that names a file uses
`stem`, one that names a video `slug`. `batch_of(entry)` is the batch a pair
belongs to (its note, else the suffix). The pair loses the suffix on its way to
a day folder; the name is taken there - the old LayoutError, the slot is the
queue's to give, and one name per day is what its table counts.

The flat layout of before this task (files straight in `publish/`, no
channel) is still read, so a checkout that has not been migrated yet loses
nothing; `migrate` moves it.

    python3 shared/runlog/publish_layout.py where SLUG [--channel C] [--day D]
                                                  (a video of a past month: "в архиве: <pointer>")
    python3 shared/runlog/publish_layout.py assign SLUG [--channel C] [--day D] [--apply]
                                                  (two videos of a name: SLUG~BATCH, CF-0920)
    python3 shared/runlog/publish_layout.py migrate [--root DIR] [--day SLUG=D ...]
                                                    [--channel SLUG=C ...] [--apply]

`assign` and `migrate` print their plan and change nothing without `--apply`.
A tracked note is moved with `git mv`, so its history follows it; `.mp4` files
are gitignored and are simply renamed.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

ROOT = Path(__file__).resolve().parent.parent.parent
PUBLISH = ROOT / "publish"
PUBLISHER = ROOT / "agents" / "publisher"

QUEUE = "_queue"
RESERVE = "_reserve"            # CF-0919: withdrawn from Studio, apart from the queue
WAITING = (QUEUE, RESERVE)      # the копилка: a video with no slot, in either of the two
FLAT = ""                       # the pre-CF-0475 layout: files straight in publish/
VIDEO, NOTE = ".mp4", ".md"
SUFFIXES = (VIDEO, NOTE)
JOURNALS = ("README.md", "acceptance-log.json", "publication-holds.json", "uploads.json")
# `publish/` holds files that are not a video's note.
NOT_A_SLUG = tuple(Path(j).stem for j in JOURNALS)
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TASK = "CF-0475"
NAME_SEP = "~"                  # CF-0920: <slug>~<batch> - a slug is [a-z0-9-], never this


class LayoutError(Exception):
    pass


def _msk():
    if ZoneInfo is None:                                        # pragma: no cover
        raise LayoutError("zoneinfo is unavailable (Python < 3.9)")
    return ZoneInfo("Europe/Moscow")


def _publish_note():
    if str(PUBLISHER) not in sys.path:
        sys.path.insert(0, str(PUBLISHER))
    import publish_note                                         # noqa: PLC0415
    return publish_note


def _git_read():
    """git_read.py beside this file (CF-0717): reads with optional locks off."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.append(here)
    import git_read                                             # noqa: PLC0415
    return git_read


def _acceptance():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import acceptance                                           # noqa: PLC0415
    return acceptance


# --------------------------------------------------------------------------
# the day and the channel
# --------------------------------------------------------------------------

def release_day(when):
    """`YYYY-MM-DD` of the day a video goes out, in Moscow time. Takes an aware
    datetime, a date, or a `YYYY-MM-DD` / ISO-with-zone string."""
    if isinstance(when, datetime):
        if when.tzinfo is None:
            raise LayoutError(f"{when!r} has no zone - the day of a release is a Moscow day")
        return when.astimezone(_msk()).strftime("%Y-%m-%d")
    if isinstance(when, date):
        return when.strftime("%Y-%m-%d")
    s = str(when or "").strip()
    if DAY_RE.match(s):
        try:
            datetime.strptime(s, "%Y-%m-%d")                    # a real calendar day
        except ValueError as e:
            raise LayoutError(f"{s!r} is not a calendar day") from e
        return s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise LayoutError(f"{when!r} is neither YYYY-MM-DD nor an ISO time") from e
    return release_day(dt)


def note_day(md):
    """The release day a note's `## Публикация` names, or None when it names no
    time. A note that names two different times is a LayoutError."""
    pn = _publish_note()
    try:
        text = Path(md).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        when = pn.publish_time(pn.sections(text).get("Публикация", ""))
    except pn.NoteError as e:
        raise LayoutError(f"{md}: {e}") from e
    return release_day(when) if when else None


# CF-0463: the batch a note describes, in its own words - the line every
# publish note opens with: "Файл: `...` (...). Батч `pipeline/<channel>/<batch>`",
# or for a rebuild "Пересборка `pipeline/rebuilds/<batch>` батча `...`"
# (backrooms, wolfhame) / "… пересборкой `pipeline/rebuilds/<batch>`" (widows-bay)
# - the first such mention; "батча `…`" (the source batch) is not one.
_CARD_BATCH = re.compile(r"(?:[Бб]атч|[Пп]ересборк[а-яё]*)\s+`pipeline/([^/`\s]+)/([^/`\s]+?)/?`")


def card_batch(md):
    """`(channel, batch_id)` the note names on its `Батч \`pipeline/<канал>/<батч>\``
    line (the first one), or None when it names none or cannot be read. The
    version a note describes is this one - never the latest acceptance of the
    name (a rebuild accepted after the video went out does not own its note)."""
    try:
        text = Path(md).read_text(encoding="utf-8")
    except (OSError, TypeError):
        return None
    m = _CARD_BATCH.search(text)
    return (m.group(1), m.group(2)) if m else None


def row_of_batch(rows, slug, batch, accepted_only=True):
    """The rows of `slug` built in `batch` (`(channel, batch_id)` from
    `card_batch`): same batch id, and - when several channels carry it - the
    one whose channel, former name or `batch_artifact` names the note's channel."""
    acc = _acceptance()
    ch, bid = batch
    hits = [r for r in rows if r.get("slug") == slug and r.get("batch_id") == bid
            and (not accepted_only or r.get("verdict") == acc.ACCEPTED)]
    if len(hits) > 1:
        # a row's `channel` is a frozen record (CF-0197): both sides resolved
        # at the door, and the name as written is still tried
        narrow = [r for r in hits
                  if acc.resolve_channel(ch) == acc.resolve_channel(r.get("channel"))
                  or ch in (r.get("channel_as_given"),)
                  or str(r.get("batch_artifact") or "").rstrip("/").endswith(f"{ch}/{bid}")]
        hits = narrow or hits
    return hits


def known_channels(root=None):
    """The channel ids on file: `channels/<id>.json` under the data root."""
    d = Path(root or ROOT) / "channels"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def channel_of_row(row, root=None):
    """The channel a row of the acceptance log publishes on: its `channel`,
    resolved to today's id. A row whose channel is not on file (a `rebuilds`
    batch) belongs to the one channel on file when there is exactly one; None
    when that cannot be said. With no `channels/` at all, the row is taken at
    its word."""
    c = _acceptance().resolve_channel((row or {}).get("channel"), root=root)
    known = known_channels(root)
    if not known or c in known:
        return c or None
    return known[0] if len(known) == 1 else None


def _check_channel(channel):
    if not channel or not CHANNEL_RE.match(str(channel)) or DAY_RE.match(str(channel)):
        raise LayoutError(f"{channel!r} is not a channel id - publish/<channel>/... needs one "
                          f"(channels/<id>.json)")
    return str(channel)


# --------------------------------------------------------------------------
# where things are
# --------------------------------------------------------------------------

def _pub(publish):
    return Path(publish) if publish else PUBLISH


def bucket_dir(publish=None, channel=None, day=None):
    """`publish/<channel>/<day>` for a day, `publish/<channel>/_queue` for none."""
    pub = _pub(publish)
    if day == FLAT and channel is None:
        return pub
    base = pub / _check_channel(channel)
    if day == RESERVE:
        return base / RESERVE
    return base / QUEUE if day in (None, QUEUE) else base / release_day(day)


def channels(publish=None):
    """The channel folders of `publish/`."""
    pub = _pub(publish)
    if not pub.is_dir():
        return []
    return sorted(p.name for p in pub.iterdir()
                  if p.is_dir() and CHANNEL_RE.match(p.name) and not DAY_RE.match(p.name))


def buckets(publish=None, channel=None):
    """`[(channel, bucket, dir)]`: the flat root (channel None), then per
    channel every day folder in date order, `_queue` and `_reserve`. `channel` narrows to
    one channel (the flat root still comes along - it has no channel yet)."""
    pub = _pub(publish)
    if not pub.is_dir():
        return []
    out = [(None, FLAT, pub)]
    for ch in channels(pub):
        if channel is not None and ch != channel:
            continue
        base = pub / ch
        out += sorted((ch, p.name, p) for p in base.iterdir()
                      if p.is_dir() and DAY_RE.match(p.name))
        out += [(ch, name, base / name) for name in WAITING if (base / name).is_dir()]
    return out


def split_name(stem):
    """CF-0920: `(slug, batch or None)` of a file's name: `x~2026-11-04T1006Z`
    is the video `x` of that batch, `x` is `x` alone."""
    slug, sep, batch = str(stem).partition(NAME_SEP)
    return slug, (batch or None) if sep else None


def file_stem(slug, batch=None):
    """CF-0920: the file's name of the video `slug` of `batch` (None: the plain one)."""
    return f"{slug}{NAME_SEP}{batch}" if batch else str(slug)


def stem_of(e):
    return e.get("stem") or e["slug"]


def batch_of(e):
    """CF-0920: the batch a pair belongs to - its note's `Батч` line, else the
    file's suffix; None when neither says."""
    cb = card_batch(e["md"]) if e.get("md") else None
    return cb[1] if cb else e.get("batch")


def free_stem(publish, channel, bucket, slug, batch=None, taken=()):
    """CF-0920: the file's name for a video of `slug` in a waiting folder: the
    plain one while no file holds it, else `<slug>~<batch>`; None when that is
    taken too or the batch is not known. `taken`: names already promised in a plan."""
    d = bucket_dir(publish, channel, bucket)

    def free(stem):
        return stem not in taken and not any((d / f"{stem}{x}").exists() for x in SUFFIXES)
    if free(slug):
        return slug
    named = file_stem(slug, batch) if batch else None
    return named if named and free(named) else None


def entries(publish=None, channel=None):
    """Every video `publish/` carries: `[{slug, stem, batch, channel, bucket, mp4,
    md}]` in bucket order; `stem` and `batch` are the file's name and its suffix
    (CF-0920, the module's docstring). `.mp4` is gitignored, so in a fresh checkout
    an entry may have only its note."""
    out = []
    for ch, name, d in buckets(publish, channel):
        found = {}
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.name.startswith(".") or p.suffix not in SUFFIXES:
                continue
            if p.stem in NOT_A_SLUG:
                continue
            slug, batch = split_name(p.stem)
            e = found.setdefault(p.stem, {"slug": slug, "stem": p.stem, "batch": batch,
                                          "channel": ch, "bucket": name, "mp4": None, "md": None})
            e["mp4" if p.suffix == VIDEO else "md"] = p
        out += [found[k] for k in sorted(found)]
    return out


def slugs(publish=None, channel=None):
    return sorted({e["slug"] for e in entries(publish, channel)})


def _order(e):
    # CF-0919: the reserve first - "the latest" of a name is the video on a day or
    # waiting for one, the reserve only when there is no other
    rank = {FLAT: 0, RESERVE: 1, QUEUE: 3}.get(e["bucket"], 2)
    return (rank, e["bucket"], e["channel"] or "")


def locate(slug, publish=None, channel=None):
    """Every place `slug` is, oldest first (flat, `_reserve`, days, `_queue`)."""
    return sorted((e for e in entries(publish, channel) if e["slug"] == slug), key=_order)


def find(slug, publish=None, channel=None, day=None):
    """The entry of `slug`: on `day` (a day, `_queue` or `_reserve`) when given - the one
    way to tell two versions of one name apart - else the latest one."""
    found = locate(slug, publish, channel)
    if day is not None:
        want = _named_bucket(day)
        found = [e for e in found if e["bucket"] == want]
    return found[-1] if found else None


def card(slug, publish=None, channel=None, day=None):
    e = find(slug, publish, channel, day)
    return e["md"] if e else None


def video(slug, publish=None, channel=None, day=None):
    e = find(slug, publish, channel, day)
    return e["mp4"] if e else None


def _named_bucket(day):
    return None if day is None else day if day in (*WAITING, FLAT) else release_day(day)


def _bucket_words(channel, bucket):
    return f"publish/{prefix(channel, bucket)}" if bucket != FLAT else "publish/"


def at_path(publish_path, publish=None):
    """CF-0857: the entry a `publish_path` (`publish/<channel>/<bucket>/<slug>.mp4`,
    relative to the data root) names, or None - an archive pointer, a path
    outside the layout or a file not on disk."""
    if not publish_path or is_archived(str(publish_path)):
        return None
    pub = _pub(publish)
    p = Path(publish_path)
    p = p if p.is_absolute() else pub.parent / p
    loc = bucket_of(p, pub)
    if loc is None:
        return None
    for e in locate(split_name(p.stem)[0], pub, loc[0]):
        if e["bucket"] == loc[1] and stem_of(e) == p.stem and (e.get("mp4") or e.get("md")):
            return e
    return None


def of_batch(slug, batch_id, publish=None, channel=None, day=None, rows=None, log_path=None):
    """CF-0857: `(entry, why)` - the entry of `slug` *built in `batch_id`*, not
    the latest one of the name. A channel reuses names (23.10 Tech: `anthropic`
    of 20.10 published from `2026-10-23/`, `anthropic` of 23.10 waiting in
    `_queue/`), so the name alone is not the video.

    The acceptance row of the batch says where its video is (`publish_path`,
    CF-0463/CF-0855); with none (an old row, no row at all) the places of the
    name are taken whose path no other row of the name claims and whose note
    names no other batch (`card_batch`), the latest of them. `day` (a day or
    `_queue`) narrows to that bucket: the video of the batch lying elsewhere
    is None with `why` saying where it is. `why` is None when an entry is
    found, an English line otherwise."""
    pub = _pub(publish)
    acc = _acceptance()
    if rows is None:
        rows = acc.entries(path=log_path or pub / "acceptance-log.json")
    want = _named_bucket(day)
    hits = row_of_batch(rows, slug, (channel or "", batch_id), accepted_only=False)
    hits.sort(key=lambda r: r.get("verdict") != acc.ACCEPTED)
    row = hits[0] if hits else None
    why = None
    pp = (row or {}).get("publish_path")
    if pp:
        e = at_path(pp, pub)
        if e is not None and e["slug"] == slug:
            if want is not None and e["bucket"] != want:
                return None, (f"{slug} of batch {batch_id} is in "
                              f"{_bucket_words(e['channel'], e['bucket'])}, not in "
                              f"{_bucket_words(e['channel'] or channel, want)} (its acceptance "
                              f"row {row.get('entry_id')}: {pp})")
            return e, None
        why = (f"{pp} (the publish_path of {row.get('entry_id')}) is "
               + ("in the archive" if is_archived(str(pp)) else "not on disk"))
        if is_archived(str(pp)):
            return None, f"{slug} of batch {batch_id}: {why}"
    claimed = set()
    for r in rows:
        if r in hits or r.get("slug") != slug or not r.get("publish_path"):
            continue
        q = Path(str(r["publish_path"]))
        q = q if q.is_absolute() else pub.parent / q
        claimed |= {q.with_suffix(VIDEO).resolve(), q.with_suffix(NOTE).resolve()}
    places = [e for e in locate(slug, pub, channel) if want is None or e["bucket"] == want]
    keep = []
    for e in places:
        if {Path(x).resolve() for x in (e["mp4"], e["md"]) if x} & claimed:
            continue
        named = batch_of(e)
        if named and named != batch_id:
            continue
        keep.append(e)
    if keep:
        return keep[-1], None
    where = _bucket_words(channel, want) if want is not None else \
        (f"publish/{channel}/" if channel else "publish/")
    line = f"{slug} of batch {batch_id}: no video in {where}"
    if why:
        line += f" - {why}"
    if places:
        line += (f" - only {len(places)} namesake(s) of other batches there ("
                 + ", ".join(_bucket_words(e["channel"], e["bucket"]) for e in places) + ")")
    return None, line


def bucket_of(path, publish=None):
    """`(channel, bucket)` of a file under `publish/` - `(None, "")` for the
    flat root - or None when it is not in the layout."""
    p = Path(path).resolve()
    pub = _pub(publish).resolve()
    if p.parent == pub:
        return (None, FLAT)
    b, ch = p.parent, p.parent.parent
    if ch.parent == pub and CHANNEL_RE.match(ch.name) and not DAY_RE.match(ch.name) \
            and (b.name in WAITING or DAY_RE.match(b.name)):
        return (ch.name, b.name)
    return None


def where(channel, bucket):
    """The folder of a bucket relative to `publish/`: `example-film/2026-10-07`,
    `example-film/_queue`, or `""` for the flat root."""
    return "" if bucket == FLAT and channel is None else f"{channel}/{bucket}"


def prefix(channel, bucket):
    w = where(channel, bucket)
    return f"{w}/" if w else ""


def rel(channel, bucket, slug, suffix=VIDEO):
    """`publish/<channel>/<bucket>/<slug><suffix>`, the form `publish_path` is
    written in."""
    return f"publish/{prefix(channel, bucket)}{slug}{suffix}"


# --------------------------------------------------------------------------
# the archive of past months (CF-0476)
# --------------------------------------------------------------------------
#
# When a month is over its days leave `publish/` for one zip per channel and
# month on the archive volume (`scripts/archive_publish_month.py`). The README
# row and the `publish_path` of such a video then name the file inside the zip:
#
#     Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-25/you-can-see-everything.mp4
#     <volume>  :<archive dir>                  /<channel>  /<month>.zip#<day>     /<slug><suffix>
#
# `<volume>` is the volume's name under /Volumes, so the pointer reads the same
# whether the disk is plugged in or not; `#` separates the zip from the member,
# whose path inside the zip is `<day>/<slug><suffix>`. A video whose rows say
# this is *in the archive*: its absence from `publish/` is not a problem.

ARCHIVE_DIR = "shorts-content-factory-publish"
ARCHIVE_RE = re.compile(r"^(?P<volume>[^:/`|]+):" + re.escape(ARCHIVE_DIR)
                        + r"/(?P<channel>[a-z0-9][a-z0-9-]*)/(?P<month>\d{4}-\d{2})\.zip"
                        r"#(?P<day>\d{4}-\d{2}-\d{2})(?:/(?P<file>[^/`|#]+))?$")


def archive_where(volume, channel, day):
    """The README-cell folder of a day inside its month's zip:
    `Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-25`."""
    day = release_day(day)
    return f"{volume}:{ARCHIVE_DIR}/{_check_channel(channel)}/{day[:7]}.zip#{day}"


def archive_ref(volume, channel, day, slug, suffix=VIDEO):
    """The pointer a README row and `publish_path` carry once the video is in
    the archive: `<archive_where>/<slug><suffix>`."""
    return f"{archive_where(volume, channel, day)}/{slug}{suffix}"


def parse_archive_ref(ref):
    """`{volume, channel, month, day, file, zip, member}` of an archive pointer,
    or None when `ref` is not one (a `publish/...` path, None, ...)."""
    m = ARCHIVE_RE.match(str(ref or "").strip())
    if not m or m.group("month") != m.group("day")[:7]:
        return None
    d = m.groupdict()
    d["zip"] = f"{ARCHIVE_DIR}/{d['channel']}/{d['month']}.zip"
    d["member"] = f"{d['day']}/{d['file']}" if d["file"] else d["day"]
    return d


def is_archived(ref):
    return parse_archive_ref(ref) is not None


def archived(slug=None, log_path=None, channel=None, root=None):
    """The accepted rows whose `publish_path` points into the archive:
    `[{slug, channel, entry_id, ref, ...parse_archive_ref}]`. `slug` narrows to
    one video, `channel` to one channel (the channel in the pointer)."""
    if log_path:
        p = Path(log_path)
    else:
        p = (Path(root) / "publish" if root else PUBLISH) / "acceptance-log.json"
    if not p.is_file():
        return []
    acc = _acceptance()
    out = []
    for r in acc.entries(path=p):
        a = parse_archive_ref(r.get("publish_path"))
        if not a or (slug is not None and r.get("slug") != slug):
            continue
        if channel is not None and a["channel"] != channel:
            continue
        out.append(dict(a, slug=r.get("slug"), entry_id=r.get("entry_id"),
                        ref=r.get("publish_path")))
    return out


def layout_notes(publish=None):
    """What does not sit where the layout says - never a verdict, never an
    exit code: a file still in the flat root, a note in a day folder whose
    `## Публикация` names another day."""
    out = []
    for e in entries(publish):
        if e["bucket"] == FLAT:
            out.append({"slug": e["slug"], "channel": None, "note": "flat",
                        "detail": f"`publish/{e['slug']}` is still in the flat layout - "
                                  f"`runlog publish migrate` puts it into its channel and "
                                  f"day ({TASK})"})
        elif e["bucket"] not in WAITING and e["md"]:
            try:
                d, why = note_day(e["md"]), None
            except LayoutError as err:
                d, why = None, str(err)
            if why or (d and d != e["bucket"]):
                out.append({"slug": e["slug"], "channel": e["channel"], "note": "wrong_day",
                            "detail": why or f"`publish/{where(e['channel'], e['bucket'])}/"
                                             f"{e['slug']}.md` says it goes out on {d}"})
    return out


# --------------------------------------------------------------------------
# README rows and publish_path
# --------------------------------------------------------------------------

def row_re(slug):
    """A row of the README table: `| \\`[<channel>/<bucket>/]<slug>.mp4\\` | ...`."""
    return re.compile(r"^\|\s*`(?:(?P<where>[^`|]+)/)?" + re.escape(slug) + r"\.mp4`\s*\|")


def readme_rows(lines, slug, at=None):
    """Indices of the README rows of `slug`; `at` (a `where()` string, `""`
    for the flat root) narrows them to one folder."""
    rx = row_re(slug)
    out = []
    for i, line in enumerate(lines):
        m = rx.match(line)
        if m and (at is None or (m.group("where") or "") == at):
            out.append(i)
    return out


def repoint_readme(text, slug, old, new, new_stem=None):
    """`(text, n)`: the rows of `slug` (a file's name) under folder `old` now
    name folder `new` (both `where()` strings) - the file cell and the
    `<slug>.md` mention; `new_stem`: and the file's new name (CF-0920)."""
    lines = text.split("\n")
    hits = readme_rows(lines, slug, old)
    po, pn = (f"{old}/" if old else ""), (f"{new}/" if new else "")
    to = new_stem or slug
    for i in hits:
        line = lines[i].replace(f"`{po}{slug}.mp4`", f"`{pn}{to}.mp4`", 1)
        lines[i] = line.replace(f"`{po}{slug}.md`", f"`{pn}{to}.md`")
    return "\n".join(lines), len(hits)


def repoint_log(log_path, slug, old_rel, new_rel, apply=False, batch=None):
    """Rows of `slug` whose `publish_path` is `old_rel` now say `new_rel`.
    None pointing there and `batch` given (`card_batch` of the note that moves,
    CF-0463): the accepted row of that batch, when it carries no path yet,
    gets `new_rel` - the version the note describes is the one that lies there.
    Returns the entry ids. The verdicts are not touched - only where the file is."""
    p = Path(log_path)
    if not p.is_file():
        return []
    acc = _acceptance()
    doc = acc.read_log(p)
    rows = acc.entries(log=doc)
    hit = [r for r in rows if r.get("slug") == slug and r.get("publish_path") == old_rel]
    if not hit and batch:
        hit = [r for r in row_of_batch(rows, slug, batch) if not r.get("publish_path")]
        hit = hit if len(hit) == 1 else []
    for r in hit:
        r["publish_path"] = new_rel
    if hit and apply:
        acc.write_log(rows, path=p, note=doc.get("note"))
    return [r.get("entry_id") for r in hit]


# --------------------------------------------------------------------------
# moving files
# --------------------------------------------------------------------------

def _git_root(path):
    try:
        cp = _git_read().run(["-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(cp.stdout.strip()) if cp.returncode == 0 and cp.stdout.strip() else None


def _tracked(path):
    top = _git_root(Path(path).parent)
    if top is None:
        return None
    cp = _git_read().run(["-C", str(top), "ls-files", "--error-unmatch", "--",
                          str(Path(path).resolve().relative_to(top.resolve()))],
                         capture_output=True, text=True, timeout=30)
    return top if cp.returncode == 0 else None


def move(src, dst, git=True):
    """Move one file; a tracked note goes by `git mv`. Returns 'git mv' | 'mv'."""
    src, dst = Path(src), Path(dst)
    if dst.exists():
        raise LayoutError(f"{dst} is already there - nothing is overwritten")
    dst.parent.mkdir(parents=True, exist_ok=True)
    top = _tracked(src) if git else None
    if top is not None:
        cp = subprocess.run(["git", "-C", str(top), "mv", "--", str(src.resolve()),
                             str(dst.resolve())], capture_output=True, text=True, timeout=60)
        if cp.returncode != 0:
            raise LayoutError(f"git mv {src} {dst}: {cp.stderr.strip()}")
        return "git mv"
    shutil.move(str(src), str(dst))
    return "mv"


def _target_stem(pub, e, ch, bucket, batch):
    """CF-0920: the name the pair of `e` gets in `bucket`: the plain one when
    free; in a waiting folder under a taken name, `<slug>~<batch>`; a day folder
    or no batch to tell it by - None, the caller's refusal."""
    if bucket in WAITING:
        return free_stem(pub, ch, bucket, e["slug"], batch or batch_of(e))
    d = bucket_dir(pub, ch, bucket)
    return None if any((d / f"{e['slug']}{x}").exists() for x in SUFFIXES) else e["slug"]


def _plan(pub, items, batch=None):
    """`items`: `[(entry, channel, bucket, source)]` - each pair to move.
    `batch` (one pair): whose it is when its note does not say (CF-0920).
    `to`: where the last of them goes, `{channel, bucket, stem}` (`note_rel`)."""
    text = (pub / "README.md").read_text(encoding="utf-8") if (pub / "README.md").is_file() else ""
    log = pub / "acceptance-log.json"
    plan = {"moves": [], "readme": [], "readme_missing": [], "log": [], "undetermined": [],
            "applied": False, "to": None}
    for e, ch, bucket, source in items:
        stem, to = stem_of(e), _target_stem(pub, e, ch, bucket, batch)
        if to is None:
            taken = bucket_dir(pub, ch, bucket) / f"{e['slug']}{NOTE}"
            raise LayoutError(f"{taken} is already there - `{e['slug']}` is not moved over it")
        plan["to"] = {"channel": ch, "bucket": bucket, "stem": to}
        for kind in ("mp4", "md"):
            src = e[kind]
            if src is None:
                continue
            dst = bucket_dir(pub, ch, bucket) / f"{to}{src.suffix}"
            plan["moves"].append({"slug": e["slug"], "src": src, "dst": dst, "channel": ch,
                                  "day": bucket, "source": source,
                                  "how": "git mv (tracked) / mv" if kind == "md" else "mv"})
        old, new = where(e["channel"], e["bucket"]), where(ch, bucket)
        _, n = repoint_readme(text, stem, old, new, to)
        if n:
            plan["readme"].append({"slug": stem, "from": old, "to": new, "rows": n,
                                   **({"to_stem": to} if to != stem else {})})
        else:
            plan["readme_missing"].append(
                {"slug": e["slug"], "detail": f"no README row names `{prefix(e['channel'], e['bucket'])}"
                                              f"{stem}.mp4` - add or fix it by hand as "
                                              f"`{new}/{to}.mp4`"})
        o, n2 = rel(e["channel"], e["bucket"], stem), rel(ch, bucket, to)
        ids, whose = repoint_log(log, e["slug"], o, n2, apply=False), None
        if not ids and (e.get("md") or e.get("batch")):
            # CF-0463: the verdict no longer writes a path - the row of the
            # batch the note names (CF-0920: or the file) gets one when its
            # pair is moved into a day
            whose = card_batch(e["md"]) if e.get("md") else None
            whose = whose or ((ch, e["batch"]) if e.get("batch") else None)
            ids = repoint_log(log, e["slug"], o, n2, apply=False, batch=whose) if whose else []
        if ids:
            plan["log"].append({"slug": e["slug"], "from": o, "to": n2, "entries": ids,
                                "batch": whose})
    return plan


def _apply(plan, pub, git):
    for m in plan["moves"]:
        m["how"] = move(m["src"], m["dst"], git=git)
    rp = pub / "README.md"
    if plan["readme"] and rp.is_file():
        text = rp.read_text(encoding="utf-8")
        for r in plan["readme"]:
            text, _ = repoint_readme(text, r["slug"], r["from"], r["to"], r.get("to_stem"))
        rp.write_text(text, encoding="utf-8")
    for r in plan["log"]:
        repoint_log(pub / "acceptance-log.json", r["slug"], r["from"], r["to"], apply=True,
                    batch=r.get("batch"))
    plan["applied"] = True
    return plan


# --------------------------------------------------------------------------
# assign: a slot for a video in the queue
# --------------------------------------------------------------------------

def note_rel(plan):
    """CF-0920: `publish/<channel>/<bucket>/<file>.md` the plan's pair goes to."""
    to = plan["to"]
    return rel(to["channel"], to["bucket"], to["stem"], NOTE)


def _named(hits, stem):
    return [e for e in hits if stem_of(e) == stem] if stem else hits


def assign(slug, channel=None, day=None, publish=None, apply=False, git=True, bucket=QUEUE,
           stem=None):
    """Move `slug` from `<channel>/_queue/` (CF-0919: `bucket` - or `_reserve/`)
    to its day: `day` when given, else
    the day its note's `## Публикация` names. The README row and
    `publish_path` follow. Returns the plan; nothing changes without `apply`.
    CF-0920: `stem` (or `slug` written as `x~batch`) names which of two videos
    of the name; the pair loses the suffix in its day."""
    pub = _pub(publish)
    if NAME_SEP in str(slug):
        slug, stem = split_name(slug)[0], slug
    queued = _named([e for e in locate(slug, pub, channel) if e["bucket"] == bucket], stem)
    if not queued:
        elsewhere = ", ".join(f"publish/{prefix(x['channel'], x['bucket'])}{slug}"
                              for x in locate(slug, pub, channel))
        raise LayoutError(f"`{slug}` is not in any {bucket}/"
                          + (f" of {channel}" if channel else "")
                          + (f" (it is at {elsewhere})" if elsewhere else ""))
    if len({e["channel"] for e in queued}) > 1:
        raise LayoutError(f"`{slug}` waits in the queue of "
                          f"{', '.join(e['channel'] for e in queued)} - pass --channel")
    if len(queued) > 1:
        raise LayoutError(f"`{slug}`: {len(queued)} videos of this name wait in {bucket}/ - name "
                          f"the file: " + " or ".join(stem_of(e) for e in queued))
    e = queued[0]
    if day is None:
        day = note_day(e["md"]) if e["md"] else None
        source = "## Публикация"
        if day is None:
            raise LayoutError(f"`{slug}`: the note names no slot in `## Публикация` - write "
                              f"it there first, or pass --day YYYY-MM-DD")
    else:
        day, source = release_day(day), "--day"
    plan = _plan(pub, [(e, e["channel"], day, source)])
    return _apply(plan, pub, git) if apply else plan


def move_day(slug, channel, from_day, to_day, publish=None, apply=False, git=True):
    """CF-0042: move `slug` from one day folder of `channel` to another - the
    queue's swap of two planned videos (`publish_queue.apply_moves`). The README
    row and `publish_path` follow, as in `assign`."""
    pub = _pub(publish)
    hits = [e for e in locate(slug, pub, channel) if e["bucket"] == from_day]
    if not hits:
        raise LayoutError(f"`{slug}` is not in publish/{channel}/{from_day}/")
    plan = _plan(pub, [(hits[0], hits[0]["channel"], release_day(to_day), "CF-0042 swap")])
    return _apply(plan, pub, git) if apply else plan


def unassign(slug, channel, from_day, publish=None, apply=False, git=True, to=QUEUE, batch=None):
    """CF-0856: take `slug` out of its day folder of `channel` back into
    `_queue/` - a placed video that did not get into Studio
    (`agents/publisher/publish_move.py unplace`) - or, CF-0919, into `_reserve/`
    (`to`: a video withdrawn from Studio, `--withdraw`). The README row and
    `publish_path` follow, as in `assign`. CF-0920: a name taken there - the
    pair goes under `<slug>~<batch>` (`batch`: when its note does not say).
    Returns the plan; nothing changes without `apply`."""
    pub = _pub(publish)
    hits = [e for e in locate(slug, pub, channel) if e["bucket"] == release_day(from_day)]
    if not hits:
        raise LayoutError(f"`{slug}` is not in publish/{channel}/{from_day}/")
    plan = _plan(pub, [(hits[0], hits[0]["channel"], to,
                        "CF-0856 unplace" if to == QUEUE else "CF-0919 withdraw")], batch=batch)
    return _apply(plan, pub, git) if apply else plan


def to_reserve(slug, channel, publish=None, apply=False, git=True, stem=None, batch=None):
    """CF-0919: move `slug` from `<channel>/_queue/` to `<channel>/_reserve/` -
    the migration of a video withdrawn before the reserve had its own folder
    (`publish_move.py --migrate-reserve`, CF-0920: `queue_accepted` when it holds
    the name of a new video). The README row and `publish_path` follow, as in
    `assign`. `stem`: which file of the name; a pair of that name there already -
    the pair goes under `<slug>~<batch>` (`batch`: when its note does not say),
    LayoutError when that cannot be. Returns the plan; nothing changes without
    `apply`."""
    pub = _pub(publish)
    hits = _named([e for e in locate(slug, pub, channel) if e["bucket"] == QUEUE], stem)
    if not hits:
        raise LayoutError(f"`{slug}` is not in publish/{channel}/{QUEUE}/")
    plan = _plan(pub, [(hits[0], hits[0]["channel"], RESERVE, "CF-0919 migrate")], batch=batch)
    return _apply(plan, pub, git) if apply else plan


# --------------------------------------------------------------------------
# migrate: the flat layout of before CF-0475 into channels and days
# --------------------------------------------------------------------------

_README_WHEN = re.compile(r"(\d{4}-\d{2}-\d{2}),?\s+(\d{1,2}):(\d{2})\s+(МСК|ET|UTC)")
_README_ON = re.compile(r"\bна\s+(\d{2})\.(\d{2})\s+(\d{1,2}):(\d{2})\s+МСК")
_README_OUT = re.compile(r"опубликован[аоы]?\*{0,2}\s+(\d{4}-\d{2}-\d{2})")
_ZONE = {"МСК": "Europe/Moscow", "ET": "America/New_York", "UTC": "UTC"}


def readme_day(text, slug):
    """`(day, how)` read off the README row(s) of `slug`: a slot in МСК/ET/UTC
    (`слот 2026-10-02 01:00 МСК`, `на 28.09 01:00 МСК`, `2026-09-24 18:00 ET`),
    else the day it was published (`опубликован 2026-09-23`). `(None, None)`
    when the row names neither."""
    lines = text.split("\n")
    for i in readme_rows(lines, slug):
        row = lines[i]
        m = _README_WHEN.search(row)
        if m:
            d, hh, mm, zone = m.groups()
            local = datetime.strptime(f"{d} {int(hh):02d}:{mm}", "%Y-%m-%d %H:%M").replace(
                tzinfo=ZoneInfo(_ZONE[zone]))
            return release_day(local), f"README: {m.group(0)}"
        m = _README_ON.search(row)
        years = re.findall(r"(\d{4})-\d{2}-\d{2}", row)
        if m and years:
            return release_day(f"{years[0]}-{m.group(2)}-{m.group(1)}"), f"README: {m.group(0)}"
        m = _README_OUT.search(row)
        if m:
            return release_day(m.group(1)), f"README: {m.group(0)}"
    return None, None


def _flat_channel(slug, rows, root):
    """The channel of a flat pair: the channels of the accepted rows that point
    at it (`publish_path` = `publish/<slug>.mp4`), else of any accepted row of
    the name. `(channel, None)` or `(None, why)`."""
    acc = _acceptance()
    mine = [r for r in rows if r.get("slug") == slug and r.get("verdict") == acc.ACCEPTED]
    pointing = [r for r in mine if r.get("publish_path") == rel(None, FLAT, slug)] or mine
    found = sorted({c for c in (channel_of_row(r, root) for r in pointing) if c})
    if len(found) == 1:
        return found[0], None
    if found:
        return None, f"accepted on several channels ({', '.join(found)})"
    known = known_channels(root)
    if len(known) == 1:
        return known[0], None
    return None, "no accepted row names its channel"


def migrate(root=None, apply=False, overrides=None, channel_overrides=None, git=True):
    """Every pair still in the flat root goes into `<channel>/<day>/`. The
    channel from `channel_overrides` (`{slug: channel}`, `""` key for every
    slug), else from its acceptance rows; the day from `overrides`
    (`{slug: day}`), else the note's `## Публикация`, else the README row. A
    pair whose day cannot be read goes into `<channel>/_queue/`; a pair whose
    channel cannot be read stays where it is. Both are named under
    `undetermined`. The README rows and `publish_path` follow. Returns the
    plan; nothing changes without `apply`."""
    root = Path(root) if root else ROOT
    pub = root / "publish"
    if not pub.is_dir():
        raise LayoutError(f"{pub} is not there")
    text = (pub / "README.md").read_text(encoding="utf-8") if (pub / "README.md").is_file() else ""
    overrides = {k: release_day(v) for k, v in (overrides or {}).items()}
    chan_over = {k: _check_channel(v) for k, v in (channel_overrides or {}).items()}
    acc = _acceptance()
    log = pub / "acceptance-log.json"
    rows = acc.entries(path=log) if log.is_file() else []
    items, undetermined = [], []
    for e in entries(pub):
        if e["bucket"] != FLAT:
            continue
        slug = e["slug"]
        ch = chan_over.get(slug) or chan_over.get("")
        if ch is None:
            ch, why_ch = _flat_channel(slug, rows, root)
            if ch is None:
                undetermined.append({"slug": slug, "detail": f"channel unknown: {why_ch} - left "
                                                             f"in place; pass --channel {slug}=<id>"})
                continue
        day, source, why = None, None, "no slot in the note"
        if slug in overrides:
            day, source = overrides[slug], "--day"
        elif e["md"]:
            try:
                day = note_day(e["md"])
            except LayoutError as err:
                why = str(err)
            source = "## Публикация" if day else None
        else:
            why = "no note"
        if day is None:
            day, source = readme_day(text, slug)
        if day is None:
            undetermined.append({"slug": slug,
                                 "detail": f"{why} and no date in the README row - put into "
                                           f"{ch}/{QUEUE}/; pass --day {slug}=YYYY-MM-DD"})
            day, source = QUEUE, None
        items.append((e, ch, day, source))
    plan = _plan(pub, items)
    plan["undetermined"] = undetermined
    return _apply(plan, pub, git) if apply else plan


def render_plan(plan, root=None):
    base = Path(root) if root else ROOT

    def show(p):
        try:
            return str(Path(p).resolve().relative_to(base.resolve()))
        except ValueError:
            return str(p)
    head = "применено" if plan.get("applied") else "СУХОЙ ПРОГОН, ничего не изменено (--apply)"
    lines = [f"{TASK} publish/<канал>/<день>/ ({head}): {len(plan['moves'])} файл(ов)"]
    for m in plan["moves"]:
        src = f" ← {m['source']}" if m.get("source") else ""
        lines.append(f"  {show(m['src'])} -> {show(m['dst'])}  [{m['how']}]{src}")
    for r in plan["readme"]:
        po = f"{r['from']}/" if r["from"] else ""
        lines.append(f"  README: `{po}{r['slug']}.mp4` -> `{r['to']}/{r['slug']}.mp4` "
                     f"({r['rows']} строк(а))")
    for r in plan["readme_missing"]:
        lines.append(f"  README: {r['detail']}")
    for r in plan["log"]:
        frm = (f"нет (строка батча заметки {r['batch'][0]}/{r['batch'][1]})"
               if r.get("batch") else r["from"])
        lines.append(f"  acceptance-log: publish_path {frm} -> {r['to']} "
                     f"({', '.join(r['entries'])})")
    for u in plan["undetermined"]:
        lines.append(f"  НЕ ОПРЕДЕЛЕНО {u['slug']}: {u['detail']}")
    return lines


def _jsonable(x):
    return json.loads(json.dumps(x, default=str, ensure_ascii=False))


def _pairs(values, ap, what):
    out = {}
    for d in values:
        if "=" not in d:
            out[""] = d.strip()
            continue
        k, v = d.split("=", 1)
        out[k.strip()] = v.strip()
    if "" in out and what == "day":
        ap.error("migrate --day takes SLUG=YYYY-MM-DD")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="runlog publish", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("where", "assign", "migrate"))
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--root", help="the data root that holds publish/ (default: this repo)")
    ap.add_argument("--channel", action="append", default=[],
                    help="where/assign: the channel id; migrate: SLUG=CHANNEL (or CHANNEL for "
                         "every pair), repeatable")
    ap.add_argument("--day", action="append", default=[],
                    help="where/assign: YYYY-MM-DD (or _queue for where); "
                         "migrate: SLUG=YYYY-MM-DD, repeatable")
    ap.add_argument("--apply", action="store_true", help="assign/migrate: do it (default: plan)")
    ap.add_argument("--no-git", action="store_true", help="move notes with mv, not git mv")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else ROOT
    pub = root / "publish"
    channel = a.channel[-1] if a.channel else None
    day = a.day[-1] if a.day else None
    try:
        if a.cmd in ("where", "assign") and not a.slug:
            ap.error(f"{a.cmd} needs SLUG")
        if a.cmd == "where":
            found = [find(a.slug, pub, channel, day)] if day else locate(a.slug, pub, channel)
            found = [e for e in found if e]
            # CF-0476: a video of a month that is over is in the archive zip.
            gone = [x for x in archived(a.slug, root=root, channel=channel)
                    if day in (None, x["day"])]
            if a.json:
                print(json.dumps(_jsonable(found + [dict(x, archived=True) for x in gone]),
                                 ensure_ascii=False, indent=2))
            else:
                for e in found:
                    print(f"{where(e['channel'], e['bucket']) or '(flat)'}: "
                          f"mp4 {e['mp4'] or '-'}; md {e['md'] or '-'}")
                for x in gone:
                    print(f"в архиве: {x['ref']} (том {x['volume']}, {x['zip']}, "
                          f"внутри {x['member']})")
            return 0 if found or gone else 1
        if a.cmd == "assign":
            plan = assign(a.slug, channel=channel, day=day, publish=pub, apply=a.apply,
                          git=not a.no_git)
        else:
            plan = migrate(root, apply=a.apply, overrides=_pairs(a.day, ap, "day"),
                           channel_overrides=_pairs(a.channel, ap, "channel"), git=not a.no_git)
        print(json.dumps(_jsonable(plan), ensure_ascii=False, indent=2) if a.json
              else "\n".join(render_plan(plan, root)))
        return 0
    except LayoutError as e:
        sys.stderr.write(f"runlog publish: error: {e}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

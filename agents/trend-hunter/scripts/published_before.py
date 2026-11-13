#!/usr/bin/env python3
"""CF-0019: a topic the factory has already made a video of is not found again
as a new topic in another batch.

What happened (batch `example-film/2026-09-29T0705Z`, finding 5 of its review):
Backrooms (published 28.09) and Wolfhame (29.09) came back as new `topic_id`s.
Backrooms made the five and took a slot, Wolfhame was the reserve. Nothing
compared a topic with `publish/` - not this stage, not compliance.

The rule is two steps (CF-0019, 1.4.7; CF-0865, 2.33). This module is the
first one and the registry both read.

Step 1 - here, at selection (`fact_probe_topics.py`, step 5a), before the fact
probe; a topic has its news, not yet a fact:

  * **same work and same story -> the topic leaves** with
    `reason_code: already_published` in `skipped_topics[]`, so its shortlist
    slot goes to the next topic by the ordinary ladder;
  * **same work, another story** (or a story this module cannot tell) -> the
    topic stays and carries `published_before: [...]`, and the stage report
    says so in a `WARNING published_before` line. The same work alone is not
    a reason to drop a topic;
  * **same franchise, another installment or season** -> kept and marked the
    same way (`relation: same_franchise` / `other_season`), never dropped;
  * a video the user **rejected** is not "made": the latest verdict of each
    *video* counts (its `entry_id`, `<channel>/<batch>/<slug>`), and only
    `accepted` does. One slug is many videos - Tech names a video after the
    product, and `chatgpt` was accepted 16.10, 24.10 and 25.10 0934Z and
    rejected 25.10 0834Z; with the slug as the key that one rejection hid
    every accepted `chatgpt` (CF-0865).

Step 2 - in the Content Researcher, right after the writer picks the fact
(step 2, before steps 3-6 spend anything): a topic marked `published_before`
with `relation: same_work` is compared with each of those published videos -
the fact (`fact.text`, `fact.url`) and the script's text against the
published video's fact and script. A repeat leaves with the same
`reason_code: already_published` in `skipped[]`. Why a second step: the news a
topic was found by is not what its video says. Chatgpt 0834Z of 25.10 had
other articles than chatgpt of 16.10 (story `different`, kept and marked), and
its writer then picked the very fact that closed the 16.10 commentary and
retold that commentary. What the second step reads of each published video is
this module's `load_registry()` record: `entry_id`, `slug`, `channel`,
`batch`, `topic_id`, `video` (`<channel>/<day|_queue>/<slug>.mp4` under
`publish/`), `mp4`/`card` (paths, or None when archived), `fact_url`,
`fact_text`, `batches`, `researcher` (the batch's 03-content-researcher.json)
and `script_ids` (its `scripts[].script_id` of this video). The
`published_before[]` mark of a topic carries `entry_id` and `video` of each
match, to find that record again.

What "the same story" is at step 1. There is no fact yet, so the story a topic
*is* is its news hook - the articles it was discovered by
(`evidence.sources[].url`, `evidence.rss_links`). The published video's hook is
the same list in the `01-trend-hunter.json` of the batch it came from. Measured
on the real case: Backrooms of 0705Z and Backrooms of 0927T0929Z carry the very
same three articles (Variety, Deadline, THR of 26.09), Wolfhame the very same
two - the "new fact" of 0705Z was the writer's, the story was the old one. A
shared article URL is an exact, mechanical test; two different articles about
one event are not caught by it, and are left - kept, marked - for step 2.

Where the published side comes from (read only, the root's files):

  * `publish/acceptance-log.json` -> `acceptances[]`: `entry_id`, `slug`,
    `verdict`, `channel`, `batch_id`, `topic_id`, `batch_artifact`,
    `publish_path`, `profile` (`read_from`, `script_id`, `fact_text`,
    `fact_source`), `answered_at`. The latest row of an `entry_id` is that
    video's verdict (a later row amends an earlier one). Two accepted rows
    naming one `publish_path` are one video replaced in place by a rebuild
    (widows-bay: accepted 22.09, rebuild rejected, rebuild accepted 23.09) -
    the later row is the video.
  * the video's note in `publish/` (CF-0475 layout: `<channel>/<YYYY-MM-DD>/`
    or `<channel>/_queue/`, the flat `publish/<slug>.md` of before it): where
    the row's `publish_path` says, else among the places of the slug no
    other row claims - the one whose note names the row's batch
    (``Батч `pipeline/<channel>/<batch>` ``). Read for the batch and topic
    (``тема `lf-...` ``) of rows that do not carry them, and the fact's
    source URL (`The fact in this video comes from: ...`; the row's
    `profile.fact_source.url` when there is no note - an archived month). A
    note with an `.mp4` and no log row is counted as accepted too - it is in
    `publish/`. The minimal reading of `shared/runlog/publish_layout.py` is
    repeated here, not imported (see PUBLISHED_CODE).
  * the topic itself - `title_ref` and its news - out of
    `<pipeline>/<channel>/<batch>/01-trend-hunter.json` (`topics[]`, or a
    reserve row's `topic`), for the `batch_artifact`, the log's batch and
    every batch the note names (a rebuild names its source batch).
    `PIPELINE_DIR` wins over `<root>/pipeline`, as in the root's tests.

A published video whose topic cannot be found (older rows with no
`topic_id`) is matched by its slug alone - `relation: same_work_unverified`,
story unknown - and only ever marked.

Usage (read-only audit of a batch against `publish/`):

    scripts/published_before.py <batch-dir|01-trend-hunter.json> [--json]

The selection pass (`fact_probe_topics.py`, step 5a) calls `load_registry` and
`judge_topic`; this CLI prints the same decision without writing anything.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _channel_ids import batch_dir, resolve_channel  # noqa: E402  - CF-0197

# `shared/runlog/funnel.py` FUNNEL_CODES - spelled here, the way the other
# codes of this stage are (this repo must not import from the root's tree).
# New in the root vocabulary with CF-0019.
PUBLISHED_CODE = "already_published"
# The mark on a kept topic (and on the refusal row, as its evidence).
MARK_KEY = "published_before"
# `selection.<key>` - what the registry held and what it did to the batch.
SELECTION_KEY = "published"

ACCEPTED = "accepted"
LOG_REL = Path("publish") / "acceptance-log.json"
PUBLISH_REL = Path("publish")
PIPELINE_ENV = "PIPELINE_DIR"
BATCH_FILE = "01-trend-hunter.json"
RESEARCHER_FILE = "03-content-researcher.json"

SAME_WORK = "same_work"
OTHER_SEASON = "other_season"
SAME_FRANCHISE = "same_franchise"
UNVERIFIED = "same_work_unverified"
RELATIONS = (SAME_WORK, OTHER_SEASON, SAME_FRANCHISE, UNVERIFIED)

STORY_SAME = "same"
STORY_OTHER = "different"
STORY_UNKNOWN = "unknown"

_MD_TOPIC = re.compile(r"тема\s+`([^`]+)`")
_MD_BATCH = re.compile(r"`pipeline/([A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+)`")
_MD_FACT = re.compile(r"comes from:[^\n]*?(https?://[^\s`]+)")
_ARTICLES = ("the ", "a ", "an ")


def _tr():
    """topic_relevance, imported late: it imports `fact_probe_topics`, which
    imports this module - a top-level import here would be a cycle."""
    import topic_relevance
    return topic_relevance


# --------------------------------------------------------------------------
# the registry of what was made
# --------------------------------------------------------------------------

def pipeline_dir(root):
    env = os.environ.get(PIPELINE_ENV)
    return Path(env).expanduser() if env else Path(root) / "pipeline"


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def entry_key(row):
    """The video a log row speaks about: its `entry_id` (`<channel>/<batch>/<slug>`,
    CF-0328), else that triple built from the row (an older or hand-made row).
    One slug is many videos - Tech names a video after the product (`chatgpt`
    of 16.10, 24.10 and 25.10 are three) - so the slug alone is no key (CF-0865).
    A former channel id (CF-0197: a row written before a rename) is resolved,
    so one video stays one key whichever name its rows carry."""
    entry = (row or {}).get("entry_id")
    if entry:
        head, sep, rest = str(entry).partition("/")
        return f"{resolve_channel(head) or head}{sep}{rest}" if sep else str(entry)
    slug = row.get("slug") or Path(str(row.get("video") or "")).stem
    if not slug:
        return None
    return f"{resolve_channel(row.get('channel')) or ''}/{row.get('batch_id') or ''}/{slug}"


def latest_verdicts(log):
    """`{entry_key: row}` - the last row of each *video* (`entry_key`) in the
    log, by `answered_at` and then by the order of the rows (a later row
    amends an earlier one of the same video). A rejection of one video of a
    slug does not hide another, accepted video of that slug (CF-0865: the
    rejected `chatgpt` of 25.10 0834Z hid the accepted ones of 16.10 and 24.10)."""
    rows = [r for r in (log or {}).get("acceptances") or [] if isinstance(r, dict)]
    order = sorted(range(len(rows)), key=lambda i: (str(rows[i].get("answered_at") or ""), i))
    latest = {}
    for i in order:
        key = entry_key(rows[i])
        if key:
            latest[key] = rows[i]
    return latest


def _row_slug(row):
    return (row or {}).get("slug") or Path(str((row or {}).get("video") or "")).stem


def _md_facts(text):
    return {"topic_id": (_MD_TOPIC.search(text or "") or [None, None])[1],
            "batches": _MD_BATCH.findall(text or ""),
            "fact_url": _trim_url((_MD_FACT.search(text or "") or [None, None])[1])}


def _trim_url(url):
    """A URL cut out of prose: no trailing punctuation, and a closing
    parenthesis only when the URL opened one (`Backrooms_(film)`)."""
    if not url:
        return None
    url = url.rstrip(".,;:")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def _batch_candidates(row, md, pipe):
    """The 01 files a published video's topic may be read from, best first."""
    rels = []
    artifact = (row or {}).get("batch_artifact")
    if artifact:
        rels.append(str(artifact).removeprefix("pipeline/").strip("/"))
    # A row written before a channel rename carries the former id (CF-0197):
    # resolve it at the read, then find the batch under whichever name its
    # directory still has on disk.
    channel = resolve_channel((row or {}).get("channel"))
    batch_id = (row or {}).get("batch_id")
    if channel and batch_id:
        found = batch_dir(channel, batch_id, pipe)
        rels.append(found.relative_to(Path(pipe)).as_posix() if found
                    else f"{channel}/{batch_id}")
    rels.extend(md.get("batches") or [])
    seen, out = set(), []
    for rel in rels:
        if rel not in seen:
            seen.add(rel)
            out.append(Path(pipe) / rel / BATCH_FILE)
    return out


def find_topic(batch, topic_id):
    """The topic record of `topic_id` in a batch file: `topics[]`, else a
    reserve row's kept `topic` (CF-0313), else a substitution's copy."""
    if not batch or not topic_id:
        return None
    for topic in batch.get("topics") or []:
        if isinstance(topic, dict) and topic.get("topic_id") == topic_id:
            return topic
    for row in batch.get("skipped_topics") or []:
        kept = (row or {}).get("topic") if isinstance(row, dict) else None
        if isinstance(kept, dict) and kept.get("topic_id") == topic_id:
            return kept
    return None


def find_topic_by_slug(batch, slug):
    """For a row with no `topic_id` (the older log rows): the topic of the batch
    whose name the slug starts with - the longest such name, since the slug is
    the work's name plus, sometimes, the angle (`outrider-doune-castle`)."""
    best, size = None, 0
    for topic in (batch or {}).get("topics") or []:
        ref = (topic or {}).get("title_ref") or {}
        name = str(ref.get("name") or "")
        names = [name, name.partition(":")[0] if ":" in name else "",
                 ref.get("parent_work") or ""]
        for mine in filter(None, (_slug_of(n) for n in names)):
            if (slug == mine or slug.startswith(mine + "-")) and len(mine) > size:
                best, size = topic, len(mine)
    return best


def source_urls(topic):
    """The topic's news hook: every article URL it was discovered by."""
    evidence = (topic or {}).get("evidence") or {}
    urls = [s.get("url") for s in evidence.get("sources") or [] if isinstance(s, dict)]
    urls += list(evidence.get("rss_links") or [])
    out = []
    for url in urls:
        if url and url not in out:
            out.append(url)
    return out


def url_key(url):
    """An article URL without scheme, `www.`, query, fragment or trailing
    slash, lowercased - the same article from two feeds is one key."""
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return str(url).strip().lower()
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}".lower()


# --------------------------------------------------------------------------
# where a video lies in publish/ (CF-0475 layout, CF-0865)
# --------------------------------------------------------------------------
#
# The same reading `shared/runlog/publish_layout.py` does (`entries`, `at_path`,
# `of_batch`), kept minimal and local: this repo does not import from the
# root's tree (see PUBLISHED_CODE). The layout:
#
#     publish/<slug>.mp4 + .md                    the flat layout before CF-0475
#     publish/<channel>/<YYYY-MM-DD>/<slug>.*     the day a video goes out
#     publish/<channel>/_queue/<slug>.*           accepted, no slot yet
#
# and an archive pointer (`<volume>:...zip#<day>/<slug>.mp4`) for a video of a
# past month - nothing on disk to read then.

QUEUE = "_queue"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NOT_A_SLUG = ("README", "acceptance-log", "publication-holds", "uploads")
# A note's own batch: "Батч `pipeline/<channel>/<batch>`" or, for a rebuild,
# "Пересборка `pipeline/rebuilds/<batch>`" - the first such mention
# (`publish_layout._CARD_BATCH`).
_CARD_BATCH = re.compile(r"(?:[Бб]атч|[Пп]ересборк[а-яё]*)\s+`pipeline/([^/`\s]+)/([^/`\s]+?)/?`")


def publish_entries(publish):
    """Every video `publish/` carries: `[{slug, channel, bucket, mp4, md}]` -
    the flat root first (channel None, bucket ""), then per channel its day
    folders in date order and `_queue`. `.mp4` is gitignored, so an entry may
    have its note only."""
    publish = Path(publish)
    if not publish.is_dir():
        return []
    dirs = [(None, "", publish)]
    for ch in sorted(p for p in publish.iterdir() if p.is_dir() and not p.name.startswith(".")):
        dirs += sorted((ch.name, d.name, d) for d in ch.iterdir()
                       if d.is_dir() and _DAY.match(d.name))
        if (ch / QUEUE).is_dir():
            dirs.append((ch.name, QUEUE, ch / QUEUE))
    out = []
    for ch, bucket, d in dirs:
        found = {}
        for f in sorted(d.iterdir()):
            if (not f.is_file() or f.name.startswith(".") or f.suffix not in (".mp4", ".md")
                    or f.stem in _NOT_A_SLUG or f.stem.lower() == "readme"):
                continue
            e = found.setdefault(f.stem, {"slug": f.stem, "channel": ch, "bucket": bucket,
                                          "mp4": None, "md": None})
            e["mp4" if f.suffix == ".mp4" else "md"] = f
        out += [found[k] for k in sorted(found)]
    return out


def _is_archived(path):
    return ":" in str(path or "").split("/", 1)[0]


def _card_batch(md):
    try:
        m = _CARD_BATCH.search(Path(md).read_text(encoding="utf-8"))
    except (OSError, TypeError, UnicodeDecodeError):
        return None
    return (m.group(1), m.group(2)) if m else None


def _entry_path(entry):
    return entry.get("mp4") or entry.get("md")


def _same_file(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _at_path(publish_path, root, entries):
    """The entry a row's `publish_path` (relative to the data root) names, or
    None - an archive pointer, or nothing on disk there."""
    if not publish_path or _is_archived(publish_path):
        return None
    p = Path(publish_path)
    p = p if p.is_absolute() else Path(root) / p
    for e in entries:
        if any(f is not None and _same_file(f.with_suffix(""), p.with_suffix(""))
               for f in (e["mp4"], e["md"])):
            return e
    return None


def _entry_of_row(row, root, entries, claimed):
    """The `publish/` entry of one accepted row: where its `publish_path` says,
    else among the places of its slug that no other row claims - the one whose
    note names this row's batch, else (an older row, a note naming no batch)
    the latest one in the row's channel or the flat root. None when nothing on
    disk is this video (archived, or never laid out)."""
    hit = _at_path(row.get("publish_path"), root, entries)
    if hit is not None or _is_archived(row.get("publish_path")):
        return hit
    slug = _row_slug(row)
    mine = [e for e in entries if e["slug"] == slug
            and not any(_same_file(_entry_path(e), c) for c in claimed)]
    batch = row.get("batch_id")
    named = [e for e in mine if e["md"] and batch and (_card_batch(e["md"]) or (None, None))[1] == batch]
    if named:
        return named[-1]
    channel = resolve_channel(row.get("channel"))
    loose = [e for e in mine if e["channel"] in (None, channel)
             and not (e["md"] and _card_batch(e["md"]))]
    return loose[-1] if loose else None


def _researcher_of(row, pipe, root, batches, topic_id):
    """`(path of the 03 the video's script is in, [script ids])`: the row's
    `profile.read_from` / `profile.script_id` (CF-0440), else the first 03 of
    the video's batches that has scripts of its topic."""
    profile = (row or {}).get("profile") or {}
    if profile.get("read_from") and profile.get("script_id"):
        path = Path(root) / profile["read_from"] / RESEARCHER_FILE
        return (str(path) if path.exists() else None), [profile["script_id"]]
    for rel in batches:
        path = Path(pipe) / rel / RESEARCHER_FILE
        data = _read_json(path) or {}
        ids = [s.get("script_id") for s in data.get("scripts") or []
               if isinstance(s, dict) and s.get("script_id")
               and topic_id and s.get("topic_id") == topic_id]
        if ids:
            return str(path), ids
    return None, []


def load_registry(root, pipe=None):
    """-> `{"log": str, "records": [...], "unresolved": [slugs], "errors": [...]}`.

    One record per *video* the factory has made and the user did not turn
    down (one per accepted `entry_id`, CF-0865 - a slug can be several). The
    fields, and what the second step (Content Researcher, after the fact is
    chosen) reads from them:

      `entry_id`        `<channel>/<batch>/<slug>` of the log row
      `slug`, `channel`, `batch`, `topic_id`, `accepted_at` (the row's
      `answered_at`, a day), `recorded_at` (the row's time - a replay keeps
      only the videos accepted before the batch it replays)
      `video`           the video relative to `publish/`
                        (`example-tech/2026-10-19/chatgpt.mp4`), the row's
                        `video` when it is not on disk
      `publish_path`    the row's `publish_path` as written (may be an
                        archive pointer)
      `mp4`, `card`     absolute paths of the video and its note, or None
      `fact_url`        the note's "The fact in this video comes from" URL,
                        else the row's `profile.fact_source.url`
      `fact_text`       the row's `profile.fact_text` (None on older rows)
      `batches`         `<channel>/<batch>` the video is of: the row's batch,
                        its `batch_artifact`, every batch the note names
      `researcher`      the 03-content-researcher.json its script is in, or None
      `script_ids`      the `scripts[].script_id` of that 03 for this video
      `title_ref`, `work`, `source_urls` (the topic's news hook),
      `resolved_from`, `resolved_by`, `origin` (`acceptance-log` |
      `publish-md` - a note with a video in `publish/` and no log row)."""
    root = Path(root)
    pipe = Path(pipe) if pipe else pipeline_dir(root)
    publish = root / PUBLISH_REL
    log_path = root / LOG_REL
    errors = []
    log = _read_json(log_path)
    if log is None and log_path.exists():
        errors.append(f"{LOG_REL} is not readable JSON")
    latest = latest_verdicts(log)
    accepted = [(k, row) for k, row in latest.items() if row.get("verdict") == ACCEPTED]
    entries = publish_entries(publish)
    # Two accepted rows of one file: a rebuild replaced the video in place
    # (widows-bay 22.09 -> 23.09) - the later row is the video.
    by_path = {}
    for key, row in accepted:
        pp = row.get("publish_path")
        if pp:
            by_path[pp] = key
    accepted = [(k, r) for k, r in accepted
                if not r.get("publish_path") or by_path[r["publish_path"]] == k]
    claimed = [root / r["publish_path"] for _, r in accepted
               if r.get("publish_path") and not _is_archived(r["publish_path"])]
    made = []
    for key, row in accepted:
        others = [c for c in claimed if not (row.get("publish_path")
                                              and _same_file(c, root / row["publish_path"]))]
        made.append((key, row, _entry_of_row(row, root, entries, others)))
    taken = [_entry_path(e) for _, _, e in made if e]
    for e in entries:
        if e["mp4"] and e["md"] and not any(_same_file(e["mp4"], t) or _same_file(e["md"], t)
                                            for t in taken):
            made.append((None, {}, e))
    records, unresolved = [], []
    for key, row, entry in made:
        slug = _row_slug(row) or entry["slug"]
        md_path = (entry or {}).get("md")
        try:
            md = _md_facts(md_path.read_text()) if md_path else _md_facts("")
        except OSError:
            md = _md_facts("")
        topic_id = row.get("topic_id") or md["topic_id"]
        topic, found_in = None, None
        resolved_by = "topic_id" if topic_id else "slug"
        candidates = _batch_candidates(row, md, pipe)
        for path in candidates:
            batch = _read_json(path)
            topic = (find_topic(batch, topic_id) if topic_id
                     else find_topic_by_slug(batch, slug))
            if topic is not None:
                topic_id = topic.get("topic_id")
                found_in = path
                break
        batches = [p.parent.relative_to(pipe).as_posix() for p in candidates]
        researcher, script_ids = _researcher_of(row, pipe, root, batches, topic_id)
        profile = row.get("profile") or {}
        ref = (topic or {}).get("title_ref") or None
        if key is None:         # a note with no log row: its own batch names it
            ch_b = _card_batch(md_path) if md_path else None
            key = f"{ch_b[0] if ch_b else entry['channel'] or ''}/{ch_b[1] if ch_b else ''}/{slug}"
        record = {"entry_id": key,
                  "slug": slug,
                  "video": (Path(entry["mp4"] or Path(entry["md"]).with_suffix(".mp4"))
                            .relative_to(publish).as_posix() if entry
                            else row.get("video") or f"{slug}.mp4"),
                  "publish_path": row.get("publish_path"),
                  "mp4": str(entry["mp4"]) if entry and entry["mp4"] else None,
                  "card": str(md_path) if md_path else None,
                  "accepted_at": row.get("answered_at"),
                  "recorded_at": row.get("recorded_at"),
                  "channel": resolve_channel(row.get("channel")) or (entry or {}).get("channel"),
                  "batch": row.get("batch_id"),
                  "batches": batches,
                  "topic_id": topic_id,
                  "title_ref": ref,
                  "work": (ref or {}).get("name"),
                  "source_urls": source_urls(topic),
                  "fact_url": md["fact_url"] or (profile.get("fact_source") or {}).get("url"),
                  "fact_text": profile.get("fact_text"),
                  "researcher": researcher,
                  "script_ids": script_ids,
                  "resolved_from": str(found_in) if found_in else None,
                  "resolved_by": resolved_by if found_in else None,
                  "origin": "acceptance-log" if row else "publish-md"}
        if topic is None and slug not in unresolved:
            unresolved.append(slug)
        records.append(record)
    return {"log": str(log_path), "records": records, "unresolved": unresolved,
            "errors": errors}


# --------------------------------------------------------------------------
# the comparison
# --------------------------------------------------------------------------

def _name_key(ref):
    name = (_tr().normalise((ref or {}).get("name")) or " ").strip()
    for article in _ARTICLES:
        if name.startswith(article) and len(name) > len(article):
            name = name[len(article):]
    return name


def _slug_of(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower().replace("'", "").replace("’", "")).strip("-")


def work_relation(ref, record):
    """How a topic's work stands to a published video's: one of RELATIONS, or
    None when they have nothing to do with each other."""
    if not (ref or {}).get("name"):
        return None
    pub = record.get("title_ref")
    if not pub:
        slug = record.get("slug") or ""
        mine = _slug_of(ref.get("name"))
        if mine and (slug == mine or slug.startswith(mine + "-")):
            return UNVERIFIED
        return None
    mine, theirs = _name_key(ref), _name_key(pub)
    if mine and mine == theirs:
        a, b = ref.get("season"), pub.get("season")
        if a is not None and b is not None and a != b:
            return OTHER_SEASON
        return SAME_WORK
    tr = _tr()
    wide_mine = set(tr.franchise_forms(ref)) | ({mine} if mine else set())
    wide_theirs = set(tr.franchise_forms(pub)) | ({theirs} if theirs else set())
    if tr.franchise_forms(ref) or tr.franchise_forms(pub):
        if wide_mine & wide_theirs:
            return SAME_FRANCHISE
    return None


def match_record(topic, record):
    """-> the `published_before` entry for this pair, or None. A record of the
    topic itself (the batch a video was made from, read again) is no match."""
    if record.get("topic_id") and record.get("topic_id") == (topic or {}).get("topic_id"):
        return None
    relation = work_relation((topic or {}).get("title_ref") or {}, record)
    if relation is None:
        return None
    theirs = {url_key(u): u for u in record.get("source_urls") or []}
    shared = [u for u in source_urls(topic) if url_key(u) in theirs]
    if shared:
        story = STORY_SAME
    elif record.get("source_urls"):
        story = STORY_OTHER
    else:
        story = STORY_UNKNOWN
    return {"slug": record.get("slug"), "video": record.get("video"),
            "entry_id": record.get("entry_id"),
            "work": record.get("work"), "topic_id": record.get("topic_id"),
            "batch": record.get("batch"), "accepted_at": record.get("accepted_at"),
            "relation": relation, "story": story, "shared_sources": shared,
            "fact_url": record.get("fact_url")}


def drops(entry):
    """The one case that takes a topic off: the same work, told from the same
    news. Everything else is a mark (the grill decides the rest, CF-0019)."""
    return entry.get("relation") == SAME_WORK and entry.get("story") == STORY_SAME


def judge_topic(topic, registry):
    """-> `(matches, drop)` for one topic against the registry."""
    matches = []
    for record in (registry or {}).get("records") or []:
        entry = match_record(topic, record)
        if entry is not None:
            matches.append(entry)
    return matches, any(drops(m) for m in matches)


def drop_reason(topic, matches):
    same = [m for m in matches if drops(m)]
    first = same[0]
    return (f"already published: the same work and the same story as publish/{first['video']} "
            f"(topic {first['topic_id']} of batch {first['batch']}, accepted "
            f"{first['accepted_at']}) - {len(first['shared_sources'])} of its news articles are "
            f"this topic's own ({', '.join(first['shared_sources'][:2])}). A new story about the "
            f"same work would have been kept and marked (CF-0019)")


def mark_line(topic, matches):
    ref = (topic or {}).get("title_ref") or {}
    parts = [f"publish/{m['video']} ({m['relation']}, story {m['story']})" for m in matches]
    return (f"WARNING published_before: {topic.get('topic_id')} {ref.get('name')!r} - "
            f"{'; '.join(parts)} - kept: not the same story, CF-0019 drops only that")


# --------------------------------------------------------------------------
# CLI - a read-only audit
# --------------------------------------------------------------------------

def audit(batch, registry):
    """Every topic of a batch (carried and reserve) against the registry."""
    rows = []
    topics = list(batch.get("topics") or [])
    topics += [r["topic"] for r in batch.get("skipped_topics") or []
               if isinstance(r, dict) and isinstance(r.get("topic"), dict)]
    for topic in topics:
        matches, drop = judge_topic(topic, registry)
        if matches:
            rows.append({"topic_id": topic.get("topic_id"),
                         "title": (topic.get("title_ref") or {}).get("name"),
                         "decision": PUBLISHED_CODE if drop else MARK_KEY,
                         "matches": matches})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    ap.add_argument("--root", help="factory root (default: FACTORY_ROOT / the checkout's root)")
    ap.add_argument("--json", action="store_true", help="print the audit as JSON")
    args = ap.parse_args(argv)
    path = Path(args.batch).expanduser()
    path = path / BATCH_FILE if path.is_dir() else path
    batch = _read_json(path)
    if batch is None:
        print(f"no readable {path}", file=sys.stderr)
        return 2
    if args.root:
        root = Path(args.root)
    else:
        from _runlog import factory_root
        root = factory_root()
    registry = load_registry(root)
    rows = audit(batch, registry)
    if args.json:
        print(json.dumps({"registry": {k: registry[k] for k in ("log", "unresolved", "errors")}
                          | {"records": len(registry["records"])}, "topics": rows},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{len(registry['records'])} published videos, unresolved topic: "
              f"{', '.join(registry['unresolved']) or 'none'}")
        for row in rows:
            for m in row["matches"]:
                print(f"{row['topic_id']} {row['title']!r}: {row['decision']} <- "
                      f"publish/{m['video']} {m['relation']} story={m['story']} "
                      f"shared={len(m['shared_sources'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

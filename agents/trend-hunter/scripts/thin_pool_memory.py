#!/usr/bin/env python3
"""CF-0876: a work the Researcher refused with `pool_too_thin` and **zero**
clean shots is not drafted, searched or carried again for the channel's next
few days of batches - unless the footage pool holds a source for it that it
did not hold then.

Where it was found (`docs/notes/cf-0874-reel-thin-pool.md` of the root): the
11 topics ExampleFilm lost to `pool_too_thin` in its four batches of 24-26.10
all had 0 usable shots, and they were four works coming back batch after
batch - Mudform x4 (102 weak shots, the same three sources every time),
James Bond x3 (31 weak, the same four), Glee x2 (35), Young Sheldon x2 (15
and 6). In `2026-10-26T1514Z` the reserve put Young Sheldon and then James
Bond into the slot Mudform left: ~3 slots of 8 a batch spent on works whose
pool was known to be empty. (ExampleTech's repeats - Spotify, MacBook,
Samsung Galaxy three batches running, PHP2Shell five - had no source indexed
at all and are not this memory's: see "What it is not".)

What it reads. Nothing is written for it: the memory is read at the start of
the stage out of the channel's own earlier batches, read-only -
`<pipeline>/<channel>/<batch>/03-content-researcher.json` -> `skipped[]` rows
with `reason_code: pool_too_thin` whose `usable_shots` (the gate's number;
else `01b-footage-index.json` `pool_depth.topics[].usable_shots`) is 0. The
work is named by the batch's `01-trend-hunter.json` (`topics[]` or
`skipped_topics[]`, `title_ref.name` and `person`) and keyed exactly as the
no-fact memory keys it (`no_fact_memory.key_of` / `names_of`: the work's
normalised name, not the topic's headline). Its sources are every video the
batch had for it: `01b` `pool_depth.topics[].per_source[].video_id` and
`sources_by_topic`, and the pool sources Trend Hunter matched to it
(`topics[].pool.matched[]` and `host_show_skipped`). A batch is as old as its
directory name says (`YYYY-MM-DDTHHMMZ`); one older than
`scope.thin_pool_memory_days` days (3 when the channel says nothing; 0 turns
the memory off) is not read. The batch being run is never read.

Why 3 days. In the window (Reel 30.09-26.10, Tech 16-25.10) no work refused
or measured at 0 usable shots ever came back with a clean shot: Mudform held
the same three sources and 0 usable over 24-26.10, Young Sheldon was at 0 on
21.10 and again on 26.10. The works whose pool did grow (Rennick, Spire-Runner,
on 21.09-01.10) had had *no* source at all - a failed fetch, never a
`pool_too_thin` - and recovered the next batch. Three days is ~6 batches of a
channel at two a day: the four repeat works would have cost their first
refusal only, 4 of the 11 slots instead of 11. It is the no-fact memory's
number, and like it, once the days are over the work is asked again - a work
that is refused again starts a new three days.

New sources. A remembered work is let through when the shared footage pool
(`shared/footage/index.json`, matched by `pool_coverage.Pool.matches` - by
title and by the topic a source was fetched for, no download, no search)
holds a video for it that none of the remembered refusals had and that none
of the refusing batches fetched (a source such a batch took in and its sieve
dropped - Glee's `Xw-h3-hp6b0` on 25.10 - was there and gave nothing): a
trailer the pool took in since, for this or another topic. When the remembered list of
matched sources was cut short (`pool.matched[]` keeps 12), a new id counts
only if the pool also holds more matched sources than the refusal did. A pool
that cannot be read lets nobody through on this count - the days still run
out. The release is written down (`released[]` of the memory's block).

What it is not. Only a refusal at **0** clean shots out of at least one
indexed source is remembered: a work with one clean shot or more was thin,
not empty, and is not held back; a work with no source indexed at all
(`pool_depth.topics[].sources` 0) had nothing fetched - Rennick and
Spire-Runner came back with 50 usable shots the next batch, and ExampleTech's
0-source refusals (Spotify, Xbox, Mark Zuckerberg: a company or a person,
not a work) are its own footage path's question - so it is not held back
either; nor is a work lost for anything else (`no_second_source`, `fetch_failed`,
`plan_unassembled`...). A held work's row in `skipped_topics[]` is
`pool_too_thin` (the funnel's word for the loss, given earlier) with
`thin_pool_memory` (the remembered refusal) and `before_scoring: true`; it is
read out of `01-trend-hunter.json`, never out of 03, so holding a work back
does not renew its memory.

Usage (read-only):

    scripts/thin_pool_memory.py <channel> [--days N] [--json]
"""
import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _channel_ids import resolve_channel  # noqa: E402
import no_fact_memory  # noqa: E402  - the key, the clock, the pipeline dir

TASK = "CF-0876"
CODE = "pool_too_thin"
DAYS_KEY = "thin_pool_memory_days"
DEFAULT_DAYS = 3
#: the key of a `skipped_topics[]` row (and of the batch's prescreen block)
MEMORY_KEY = "thin_pool_memory"
BEFORE_SCORING_KEY = no_fact_memory.BEFORE_SCORING_KEY
HUNTER_FILE = "01-trend-hunter.json"
INDEX_FILE = "01b-footage-index.json"
RESEARCHER_FILE = "03-content-researcher.json"
#: `pool_coverage.MATCHED_KEEP` - a longer matched list was cut to this
MATCHED_KEEP = 12

key_of = no_fact_memory.key_of
names_of = no_fact_memory.names_of
parse_time = no_fact_memory.parse_time
_iso = no_fact_memory._iso


def days_of(config):
    """(days, where they came from, a note or None) - `scope.thin_pool_memory_days`."""
    return no_fact_memory.days_of(config, key=DAYS_KEY, default=DEFAULT_DAYS)


def _load(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _rows(doc, key):
    v = (doc or {}).get(key)
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _topics_of(hunter):
    """{topic_id: topic} of a 01-trend-hunter.json: carried topics, and the
    refused ones (their kept `topic`, else a stand-in named by the row)."""
    out = {}
    for t in _rows(hunter, "topics"):
        if t.get("topic_id"):
            out[t["topic_id"]] = t
    for r in _rows(hunter, "skipped_topics"):
        tid = r.get("topic_id")
        if not tid or tid in out:
            continue
        kept = r.get("topic") if isinstance(r.get("topic"), dict) else None
        out[tid] = kept or {"topic_id": tid, "title_ref": {"name": r.get("title")}}
    return out


def refusals_of_batch(batch_dir, at=None):
    """The memory entries one earlier batch gives: one per key of every work
    its Researcher refused with `pool_too_thin` at 0 clean shots."""
    batch_dir = Path(batch_dir)
    researcher = _load(batch_dir / RESEARCHER_FILE)
    rows = [r for r in _rows(researcher, "skipped") if r.get("reason_code") == CODE]
    if not rows:
        return []
    index = _load(batch_dir / INDEX_FILE) or {}
    depth = {t.get("topic_id"): t for t in _rows(index.get("pool_depth") or {}, "topics")}
    by_topic = index.get("sources_by_topic") if isinstance(index.get("sources_by_topic"),
                                                           dict) else {}
    topics = _topics_of(_load(batch_dir / HUNTER_FILE))
    at = at or parse_time(batch_dir.name)
    out, seen = [], set()
    for row in rows:
        tid = row.get("topic_id")
        measured = depth.get(tid) or {}
        usable = row.get("usable_shots")
        if not _whole(usable):
            usable = measured.get("usable_shots")
        if not _whole(usable) or usable != 0:
            continue                      # thin is not empty: never remembered
        indexed = measured.get("sources")
        if not _whole(indexed):
            indexed = len(measured.get("per_source") or [])
        if indexed < 1:
            continue                      # nothing was indexed: a fetch question, not a pool
        topic = topics.get(tid) or {}
        keys = names_of(topic)
        if not keys:
            continue
        pool = topic.get("pool") if isinstance(topic.get("pool"), dict) else {}
        matched = [m.get("video_id") for m in pool.get("matched") or []
                   if isinstance(m, dict) and m.get("video_id")]
        skipped = [v for v in pool.get("host_show_skipped") or [] if isinstance(v, str)]
        ids = set(matched) | set(skipped)
        ids |= {s.get("video_id") for s in measured.get("per_source") or []
                if isinstance(s, dict) and s.get("video_id")}
        ids |= {v for v in by_topic.get(tid) or [] if isinstance(v, str)}
        count = pool.get("sources")
        pool_count = (count if _whole(count) else len(matched)) + len(skipped)
        name = (topic.get("title_ref") or {}).get("name") or row.get("title")
        for key in keys:
            if (key, tid) in seen:
                continue
            seen.add((key, tid))
            out.append({"key": key, "name": name, "batch": batch_dir.name, "topic_id": tid,
                        "refused_at": _iso(at) if at else None, "usable_shots": 0,
                        "weak_shots": measured.get("weak_shots"),
                        "sources": measured.get("sources"),
                        "video_ids": sorted(ids),
                        "pool_matched": pool_count,
                        "pool_complete": not (_whole(count) and count > len(matched))})
    return out


def scan(root, channel, now, days, batch=None):
    """Every entry the channel's batches of the last `days` days give,
    the batch `batch` (the one being run) left out. -> (entries, batches read)."""
    base = no_fact_memory.pipeline_dir(root) / str(channel)
    since = now - timedelta(days=days)
    entries, read = [], []
    try:
        dirs = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return [], []
    for d in dirs:
        if batch and d.name == batch:
            continue
        at = parse_time(d.name)
        if at is None or at < since or at > now:
            continue
        found = refusals_of_batch(d, at)
        read.append(d.name)
        entries.extend(found)
    return entries, read


def pool_matcher(root):
    """-> `ids(topic)`: {video id: the batch it was fetched for, or None} of
    what the shared footage pool matches to a topic now
    (`pool_coverage.Pool.matches`, no screening, no host-show question; the
    batch is the one its `note` names), or None when the pool cannot be read.
    Loaded on first use."""
    cache = {}
    import pool_coverage   # here, not at the top: pool_coverage's imports reach fact_probe_topics

    def ids(topic):
        if "pool" not in cache:
            try:
                cache["pool"] = pool_coverage.Pool(pool_coverage.load_index(root),
                                                   pool_coverage.topic_names(root))
            except Exception:                                   # noqa: BLE001
                cache["pool"] = None
        pool = cache["pool"]
        if pool is None:
            return None
        out = {}
        for e, _ in pool.matches(topic):
            m = pool_coverage._NOTE.search(e.get("note") or "")
            out[e["id"]] = m.group(1) if m else None
        return out
    return ids


def _as_topic(topic):
    """A pool candidate has only `name`; the pool is asked by `title_ref`."""
    topic = topic or {}
    if (topic.get("title_ref") or {}).get("name"):
        return topic
    return {"topic_id": topic.get("topic_id"), "title_ref": {"name": topic.get("name")}}


class Memory:
    """The channel's remembered empty-pool refusals, as of `now`. `pool_ids`
    is `pool_matcher()`'s shape (None: no pool asked - nobody is let through
    for new sources)."""

    def __init__(self, entries, days=DEFAULT_DAYS, now=None, batch=None, channel=None,
                 days_from="default", pool_ids=None, read=None, path=None):
        self.days = int(days)
        self.now = now or no_fact_memory.now_utc()
        self.batch = batch
        self.channel = channel
        self.days_from = days_from
        self.pool_ids = pool_ids
        self.read = list(read or [])
        self.path = str(path) if path else None
        self.released = []
        since = self.now - timedelta(days=self.days)
        self.live = {}
        for entry in entries or []:
            at = parse_time(entry.get("refused_at"))
            if self.days <= 0 or at is None or at < since or at > self.now:
                continue
            if batch and entry.get("batch") == batch:
                continue
            have = self.live.get(entry["key"])
            if have is None:
                self.live[entry["key"]] = dict(entry, refusals=[entry.get("batch")],
                                               video_ids=sorted(entry.get("video_ids") or []))
                continue
            have["video_ids"] = sorted(set(have["video_ids"]) | set(entry.get("video_ids") or []))
            have["pool_matched"] = max(int(have.get("pool_matched") or 0),
                                       int(entry.get("pool_matched") or 0))
            have["pool_complete"] = bool(have.get("pool_complete")) and bool(
                entry.get("pool_complete"))
            if entry.get("batch") not in have["refusals"]:
                have["refusals"].append(entry.get("batch"))
            if parse_time(have.get("refused_at")) < at:
                for k in ("name", "batch", "topic_id", "refused_at", "weak_shots", "sources"):
                    have[k] = entry.get(k)

    def new_sources(self, topic, entry):
        """The pool's video ids for this work that no remembered refusal had
        - and that were not fetched by one of the refusing batches either (a
        source such a batch fetched and sieved out was there and gave nothing).
        Empty: none, or the pool could not be read."""
        if self.pool_ids is None:
            return []
        now = self.pool_ids(_as_topic(topic))
        if not now:
            return []
        if not isinstance(now, dict):
            now = {v: None for v in now}
        had = set(entry.get("video_ids") or [])
        refusing = set(entry.get("refusals") or [entry.get("batch")])
        new = sorted(v for v, fetched_for in now.items()
                     if v not in had and fetched_for not in refusing)
        if new and not entry.get("pool_complete") \
                and len(now) <= int(entry.get("pool_matched") or 0):
            return []          # the remembered list was cut short: a count is the test
        return new

    def hit(self, topic):
        """The remembered refusal that holds this topic (or pool candidate)
        back, or None - also None when the pool has a new source for it."""
        for key in names_of(topic):
            entry = self.live.get(key)
            if entry is None:
                continue
            new = self.new_sources(topic, entry)
            if new:
                self.released.append({"name": (topic.get("title_ref") or {}).get("name")
                                      or topic.get("name"),
                                      "topic_id": topic.get("topic_id"),
                                      "remembered_batch": entry.get("batch"),
                                      "new_sources": new})
                return None
            return entry
        return None

    def block(self):
        return {"task": TASK, "days": self.days, "days_from": self.days_from,
                "as_of": _iso(self.now), "pipeline": self.path,
                "batches_read": len(self.read), "live_entries": len(self.live),
                "released": list(self.released)}


def load(root, channel, config=None, now=None, batch=None, pool_ids=None):
    """The channel's memory as of `now` (default: the clock), read out of its
    earlier batches. `pool_ids` defaults to the shared pool's matcher."""
    days, origin, _ = days_of(config)
    channel = resolve_channel(channel, root)
    now = now or no_fact_memory.now_utc()
    entries, read = scan(root, channel, now, days, batch=batch) if days > 0 else ([], [])
    return Memory(entries, days=days, now=now, batch=batch, channel=channel,
                  days_from=origin, read=read,
                  pool_ids=pool_ids if pool_ids is not None else pool_matcher(root),
                  path=no_fact_memory.pipeline_dir(root) / str(channel))


def remembered_refusal(topic, entry, days):
    """The `skipped_topics[]` row of a work the memory holds back."""
    ref = topic.get("title_ref") or {}
    reason = (f"pool too thin: refused with {CODE} at 0 clean shots "
              f"({entry.get('weak_shots')} weak, {entry.get('sources')} source(s)) in batch "
              f"{entry.get('batch')} ({entry.get('refused_at')}"
              + (f"; {len(entry.get('refusals') or [])} refusals in the window"
                 if len(entry.get("refusals") or []) > 1 else "")
              + f") - within the channel's {DAYS_KEY} ({days}) and the footage pool holds "
              f"no source for it that it did not hold then, so it is neither searched nor "
              f"carried again (CF-0876)")
    return {"topic_id": topic.get("topic_id"), "reason_code": CODE, "reason": reason,
            "stage": "trend-hunter", "title": ref.get("name"), "kind": ref.get("kind") or None,
            "popularity_score": None, MEMORY_KEY: dict(entry), BEFORE_SCORING_KEY: True}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("channel")
    ap.add_argument("--days", type=int, default=None,
                    help=f"override the channel's scope.{DAYS_KEY}")
    ap.add_argument("--root", help="the factory root (default: FACTORY_ROOT / the tree's)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.root:
        root = Path(args.root).expanduser()
    else:
        from _runlog import factory_root
        root = factory_root()
    config = None
    try:
        config = json.loads((root / "channels" / f"{args.channel}.json").read_text())
    except (OSError, ValueError):
        pass
    if args.days is not None:
        config = {"scope": {DAYS_KEY: args.days}}
    mem = load(root, args.channel, config)
    rows = sorted(mem.live.values(), key=lambda e: e.get("refused_at") or "")
    if args.json:
        print(json.dumps({"memory": mem.block(), "live": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"{mem.path}: {len(mem.read)} batch(es) read, {len(rows)} work(s) held back "
              f"for {mem.days} day(s) ({mem.days_from})")
        for e in rows:
            print(f"  {e.get('refused_at')}  {e.get('name')!r}  weak {e.get('weak_shots')}  "
                  f"{len(e.get('video_ids') or [])} source(s)  {e.get('refusals')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

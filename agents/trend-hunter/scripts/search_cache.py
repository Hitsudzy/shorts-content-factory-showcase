#!/usr/bin/env python3
"""CF-0824: the channel's cache of YouTube `search.list` answers.

Why it exists now. The decision of 2026-09-23 was "no cache until a
measurement shows a need" (`search_quota.py`, CF-0368). The measurement came
(`docs/analysis/funnel-2026-10-21.md` of the root): over 04-20.10 the same
`search.list` query was asked again in a later batch of the same channel 36
times on ExampleFilm (14 % of its calls) and 31 times on ExampleTech (13 %) -
a lower bound - and the day's 100 `search.list` calls are what limits the
factory to fewer batches a day than the user wants (two a day, 21.10).

What is cached. One `search.list` call's answer: the ordered video ids,
keyed by the query and the parameters that change the answer (`days` of the
window, `max_results`; `type`, `order` and `part` are the fetcher's
constants). **Never `videos.list`** - it costs 1 unit, and it is where the
view counts, durations and licences come from, which must be read fresh on
every run: a cached search hands its ids to a fresh `videos.list`, so the
scoring pass's view sum is today's even when the list of videos is a day old.

How long an answer is good for, by the article that reads it (the reader's
TTL, not the writer's - a footage answer is also a scoring answer when the
query is the same):

    scoring (the view signal)               `scope.search_cache_scoring_hours`, 24
    footage_search / supplement (footage)   `scope.search_cache_footage_hours`, 72

0 turns the cache off for that kind of read. A value that is not a whole
number >= 0 is the default, and the note says so.

Where it lives. Beside the channel's other memory between batches,
`<pipeline>/<channel>/youtube-search-cache.json` (`PIPELINE_DIR` wins over
`<root>/pipeline`, as for `no-fact-memory.json`) - out of git, shared by the
channel's batches. The fetcher finds it by `--channel`, else by the batch it
runs under (`RUNLOG_BATCH` = `<pipeline>/<channel>/<batch>`, which the
executor exports to the stage): the batch's parent folder - only when the
folder is named as a batch (`2026-10-21T1000Z...`) and is not under
`backfill/` or `rebuilds/`. Neither known - no cache, and the output says so.

    {"task": "CF-0824", "entries": {
        "<key>": {"query": "Cuttle Game trailer", "days": 7, "max_results": 15,
                  "ids": ["abc", ...], "fetched_at": "2026-10-21T10:00:00Z",
                  "article": "footage_search"}}}

Entries older than `KEEP_HOURS` are dropped when the file is written.

What a hit costs. Nothing of the day's quota: the fetcher does not write the
`youtube-api search` run-log event a call writes (that event is what
`search_quota.spend_from_events` and the root's `shared/quota_day.py` count),
and its output's `searches` is the real calls only. A hit is written as a
`youtube-cache search` event and as `cached_searches` in the output, and
`search_quota` keeps it on its own ledger (`cached_search_calls` per article),
never in `spent_searches`.

Usage (read-only):

    scripts/search_cache.py <channel> [--json]
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

TASK = "CF-0824"
FILE_NAME = "youtube-search-cache.json"
PIPELINE_ENV = "PIPELINE_DIR"
BATCH_ENV = "RUNLOG_BATCH"
#: the run-log tool of a cache hit - not `youtube-api`, so nothing that counts
#: the day's spend counts it
CACHE_TOOL = "youtube-cache"
#: the channel keys under `scope` and their defaults (the task of 21.10)
SCORING_KEY = "search_cache_scoring_hours"
FOOTAGE_KEY = "search_cache_footage_hours"
DEFAULT_SCORING_HOURS = 24
DEFAULT_FOOTAGE_HOURS = 72
#: the articles read with the scoring TTL; every other search article
#: (footage_search, supplement) is a footage read
SCORING_ARTICLES = ("scoring",)
#: a batch folder's name, and the folders under `pipeline/` that are no channel
#: (the root's `shared/quota_day.py` skips the same two)
BATCH_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{4}Z")
NOT_CHANNEL_GROUPS = ("backfill", "rebuilds")
#: how long an entry stays in the file at all
KEEP_HOURS = 7 * 24


def now_utc():
    return datetime.now(timezone.utc)


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# the channel's numbers
# --------------------------------------------------------------------------

def _hours(scope, key, default):
    value = scope.get(key)
    if value is None:
        return default, "default", None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 \
            or int(value) != value:
        return default, "default", (f"scope.{key} is {value!r}, not a whole number >= 0; "
                                    f"using {default}")
    return int(value), "channel", None


def ttl_of(config, article):
    """(hours, where it came from, a note or None) of the cache read for one
    article: the scoring TTL for the scoring pass, the footage TTL for every
    other search article."""
    scope = (config or {}).get("scope") or {}
    if article in SCORING_ARTICLES:
        return _hours(scope, SCORING_KEY, DEFAULT_SCORING_HOURS)
    return _hours(scope, FOOTAGE_KEY, DEFAULT_FOOTAGE_HOURS)


def load_config(channel):
    """`channels/<channel>.json` of the factory root, or None (a channel the
    root does not know - a test's stand-in - reads the defaults)."""
    if not channel:
        return None
    try:
        from _channel_ids import channel_config_path
        return json.loads(Path(channel_config_path(channel)).read_text())
    except Exception:  # noqa: BLE001 - no config is the defaults, never a crash
        return None


# --------------------------------------------------------------------------
# where the file is
# --------------------------------------------------------------------------

def pipeline_dir(root=None):
    env = os.environ.get(PIPELINE_ENV)
    if env:
        return Path(env).expanduser()
    if root is None:
        from _runlog import factory_root
        root = factory_root()
    return Path(root) / "pipeline"


def locate(channel=None, batch_dir=None, root=None, environ=None):
    """(cache file, channel) - by `channel` under the pipeline, else by the
    batch the run is under (`batch_dir`, else `RUNLOG_BATCH`): its parent
    folder is the channel's. (None, None) when neither is known."""
    if channel:
        return pipeline_dir(root) / str(channel) / FILE_NAME, str(channel)
    env = environ if environ is not None else os.environ
    batch = batch_dir or env.get(BATCH_ENV)
    if batch:
        batch = Path(batch).expanduser()
        # only a batch folder (`<id>` = `YYYY-MM-DDTHHMMZ...`) of a channel: a
        # temp directory or a rebuild is no channel's, and gets no cache
        if BATCH_ID_RE.match(batch.name) and batch.parent.name \
                and batch.parent.name not in NOT_CHANNEL_GROUPS:
            return batch.parent / FILE_NAME, batch.parent.name
    return None, None


# --------------------------------------------------------------------------
# the file
# --------------------------------------------------------------------------

def query_key(query, days, max_results):
    """The key of one `search.list` call: the query (case and spacing do not
    change YouTube's answer) and the parameters that do."""
    flat = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    return f"{flat}|days={int(days)}|max={int(max_results)}"


def read_entries(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return {}
    rows = data.get("entries") if isinstance(data, dict) else None
    return {k: v for k, v in (rows or {}).items()
            if isinstance(v, dict) and isinstance(v.get("ids"), list)}


class Cache:
    """One channel's cache for one run of the fetcher: what it read, what it
    answered and what it wrote."""

    def __init__(self, path, channel=None, ttl_hours=0, ttl_from="default", note=None,
                 now=None):
        self.path = Path(path) if path else None
        self.channel = channel
        self.ttl_hours = int(ttl_hours or 0)
        self.ttl_from = ttl_from
        self.note = note
        self.now = now or now_utc()
        self.entries = read_entries(self.path) if self.path else {}
        self.fresh = {}
        self.hits = []
        self.misses = 0

    @property
    def on(self):
        return self.path is not None and self.ttl_hours > 0

    def peek(self, query, days, max_results):
        """The cached entry of this call when it is younger than the TTL, else
        None - without recording a hit (CF-0882: what a run would cost is
        asked before the run is made)."""
        if not self.on:
            return None
        key = query_key(query, days, max_results)
        entry = self.fresh.get(key) or self.entries.get(key)
        at = parse_time((entry or {}).get("fetched_at"))
        if entry is None or at is None or at > self.now + timedelta(minutes=5):
            return None
        if self.now - at >= timedelta(hours=self.ttl_hours):
            return None
        return entry

    def get(self, query, days, max_results):
        """The cached entry of this call when it is younger than the TTL, else
        None. Records a hit."""
        entry = self.peek(query, days, max_results)
        if entry is None:
            return None
        age = self.now - parse_time(entry.get("fetched_at"))
        self.hits.append({"query": query, "fetched_at": entry.get("fetched_at"),
                          "age_hours": round(age.total_seconds() / 3600, 2)})
        return entry

    def put(self, query, days, max_results, ids, article=None):
        """Remember one real call's answer (written by `save`)."""
        self.misses += 1
        if self.path is None:
            return
        self.fresh[query_key(query, days, max_results)] = {
            "query": query, "days": int(days), "max_results": int(max_results),
            "ids": list(ids), "fetched_at": _iso(self.now), "article": article}

    def save(self):
        """Merge this run's answers into the file as it stands now (another
        run may have written since this one read it) and drop the old ones.
        A cache that cannot be written is silence - the run's output is right
        either way."""
        if self.path is None or not self.fresh:
            return False
        try:
            entries = read_entries(self.path)
            entries.update(self.fresh)
            since = self.now - timedelta(hours=KEEP_HOURS)
            entries = {k: v for k, v in entries.items()
                       if (parse_time(v.get("fetched_at")) or since) > since}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".search-cache-")
            with os.fdopen(fd, "w") as fh:
                json.dump({"task": TASK, "channel": self.channel, "entries": entries}, fh,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def block(self):
        """What the fetcher's output says about the cache it ran against."""
        return {"task": TASK, "path": str(self.path) if self.path else None,
                "channel": self.channel, "ttl_hours": self.ttl_hours,
                "ttl_from": self.ttl_from, "on": self.on,
                "hits": len(self.hits), "calls": self.misses,
                "hit_queries": self.hits,
                **({"note": self.note} if self.note else {})}


def open_cache(article, channel=None, batch_dir=None, config=None, now=None, off=False,
               root=None, environ=None):
    """The cache of this run: located, its TTL read for `article` off the
    channel's config (`config`, else `channels/<channel>.json`). `off` (the
    fetcher's `--no-cache`) asks nothing of it but still writes the answers."""
    path, found = locate(channel, batch_dir, root=root, environ=environ)
    if config is None:
        config = load_config(found)
    hours, source, note = ttl_of(config, article)
    if path is None:
        note = "no channel known (neither --channel nor RUNLOG_BATCH): no cache"
    if off:
        hours, source = 0, "--no-cache"
    return Cache(path, channel=found, ttl_hours=hours, ttl_from=source, note=note, now=now)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("channel")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    path, _ = locate(args.channel)
    entries = read_entries(path)
    if args.json:
        print(json.dumps({"path": str(path), "entries": entries}, ensure_ascii=False,
                         indent=2))
        return 0
    print(f"{path}: {len(entries)} cached search(es)")
    for v in sorted(entries.values(), key=lambda e: e.get("fetched_at") or ""):
        print(f"  {v.get('fetched_at')}  {v.get('article') or '-':<15} "
              f"{len(v.get('ids') or [])} id(s)  {v.get('query')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

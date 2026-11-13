#!/usr/bin/env python3
"""Fetch recent-video signal for a TV show title from YouTube Data API v3.

For a given title, searches for recent videos discussing it (clip reactions,
recaps, discussion), pulling view counts and top comment snippets as a text
signal for later scene reasoning. Prints JSON to stdout.

Two different jobs run through this script, and they must not be confused
(CF-0129):

  * the **scoring pass** - one bare search on the title, whose view sum is
    `signal.raw.youtube_views_after_exclusions`. The CF-0038 scale is
    calibrated on exactly that quantity, so this pass runs with no facets
    and its numbers stay comparable with every batch ever scored.
  * the **footage pass** - `--facets`, one extra search per facet, whose job
    is to widen the pool of *filmable* material so that a topic has three
    candidate sources of different kinds rather than three reuploads of one
    trailer (`scripts/footage_candidates.py` picks them out of this output).
    Its view sum is a different quantity - more searches find more video -
    and must never be fed to the score.

Requires YOUTUBE_API_KEY: the environment, else this repo's .env (_apikey.py, CF-0360).
Usage:
  fetch_youtube_signal.py "Cuttle Game season 3" [--days 7] [--max-results 15]
  fetch_youtube_signal.py "Cuttle Game season 3" --facets          # the channel's facets
  fetch_youtube_signal.py "Cuttle Game season 3" --facets trailer,interview
  fetch_youtube_signal.py "Cuttle Game season 3" --channel example-film [--no-cache]

CF-0824: a `search.list` call the channel's cache (`search_cache.py`,
`<pipeline>/<channel>/youtube-search-cache.json`) answered within its TTL -
24 h for the scoring pass, 72 h for the footage passes, the channel's
`scope.search_cache_*_hours` - is not made: no request and no
`youtube-api search` event, so the day's quota is not charged for it. The
output's `searches` is the calls really made; `cached_searches` and
`search_cache` say what the cache answered. `videos.list` is never cached:
the view counts are always today's.

CF-0825: the bare `--facets` flag is the channel's footage facets -
`scope.footage_facets` of `channels/<channel>.json` (the channel of
`--channel`, else of `RUNLOG_BATCH`, as for the cache): a list of phrases, `[]`
= the bare query alone (one call), no key = FOOTAGE_FACETS (ExampleFilm's five,
unchanged). `--facets a,b` names them outright and wins over the key. The
output's `facets_from` says which ("--facets", "channel", "default").
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/ - for _runlog
import search_cache  # noqa: E402  - CF-0824
import search_quota  # noqa: E402
from _apikey import MISSING, youtube_api_key  # noqa: E402
from _runlog import runlog  # noqa: E402

BASE = "https://www.googleapis.com/youtube/v3"

# CF-0129: the facets of the footage pass. One search each, on top of the bare
# title, chosen because they are the phrases under which *different kinds of
# footage* are published - a second trailer, a press interview, an episode
# clip, a making-of. The independence a two-source gate asks for is decided
# after download by the CF-0080 fingerprint, and reuploads of one teaser
# collapse into one source (2026-09-03: GyEpwGQIEZw / SJVmeJaS44s, distance
# 1.82), so the only thing discovery can do about it is search where
# differently-shot material lives instead of asking one query for more rows.
FOOTAGE_FACETS = ("trailer", "teaser", "interview", "clip scene", "behind the scenes")

# CF-0825: the channel's own facets for the footage pass, under `scope`. The
# five above were chosen for films and series; on ExampleTech (an iPad, a
# Rivian, Spotify) 72 facet calls over five batches brought next to no second
# source (`docs/analysis/funnel-2026-10-21.md` of the root), so a channel
# names its own - or none, `[]`, the bare query alone.
FACETS_KEY = "footage_facets"
# what argparse holds for a bare `--facets` (no value): "the channel's facets"
CHANNEL_FACETS = "\0channel-facets"

# The label a video carries when the bare title query is what found it.
BARE_FACET = "title"

# The /videos endpoint takes at most 50 ids per call.
STATS_CHUNK = 50

# CF-0302: the parts asked of `/videos`. `contentDetails` carries `duration`,
# which is the only thing that tells a two-hour talk show from a trailer
# before anything is downloaded - on 2026-09-21 `Lv_GOa6HXVA` (8019 s, a news
# podcast with "Trailer" in its title, 46 views) was offered as a `trailer`
# candidate and cost the topic its whole attempt budget in the indexer. It is
# free: the Data API charges `videos.list` **per call**, not per part (1 unit
# either way), so the footage pass keeps costing what it cost.
STATS_PARTS = "snippet,statistics,contentDetails,status"

# CF-0662 (TH-2 of the root's docs/science-footage.md): `status.license` is
# what YouTube itself says the upload is licensed under - `youtube` (the
# standard licence) or `creativeCommon` (CC BY 3.0). Asked in the same call as
# the rest (`status` is one more part of the same 1-unit `videos.list`), and
# written to the record as `yt_license`; None when the answer carries no
# status (a feed entry read without a key, a search written before CF-0662).
YT_LICENSES = ("youtube", "creativeCommon")


def yt_license(item):
    """`status.license` of one `/videos` item, or None when it says nothing
    usable - never a guess."""
    value = ((item or {}).get("status") or {}).get("license")
    return value if value in YT_LICENSES else None

# `PT1H2M3S`, `P1DT2H`, `P0D`. The API answers ISO 8601 durations, and a live
# stream or a premiere that has not started answers `P0D` - which is not a
# zero-second video but "nobody can tell yet", and is read as unknown.
ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$")
DURATION_UNITS = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}


def duration_seconds(raw):
    """`contentDetails.duration` -> whole seconds, or None when the API said
    nothing usable (absent, `P0D`, a week-form `P1W`, anything unparseable).

    None is *not* zero and must never be read as a short video: a candidate
    whose length nobody can tell goes the usual way and is judged on
    everything else (CF-0302)."""
    if not isinstance(raw, str):
        return None
    found = ISO_DURATION_RE.match(raw.strip())
    if not found:
        return None
    total = sum(float(v) * DURATION_UNITS[k]
                for k, v in found.groupdict().items() if v is not None)
    return int(total) or None


def parse_facets(raw):
    """`--facets` -> the list of facet phrases (possibly empty)."""
    return [f.strip() for f in (raw or "").split(",") if f.strip()]


def channel_facets(config):
    """(facets, where they came from, a note or None) of the footage pass for
    a channel's config (`channels/<channel>.json`, None for an unknown one):
    `scope.footage_facets` when it is a list of strings (`[]` included - the
    bare query alone), else FOOTAGE_FACETS - a missing key quietly, a malformed
    one with a note saying so."""
    scope = (config or {}).get("scope") or {}
    if FACETS_KEY not in scope:
        return list(FOOTAGE_FACETS), "default", None
    value = scope.get(FACETS_KEY)
    if isinstance(value, list) and all(isinstance(f, str) for f in value):
        return [f.strip() for f in value if f.strip()], "channel", None
    return list(FOOTAGE_FACETS), "default", (
        f"scope.{FACETS_KEY} is {value!r}, not a list of phrases; "
        f"using {','.join(FOOTAGE_FACETS)}")


def article(facets, env=None, footage=False):
    """Which article of the day's quota this run spends (CF-0368).

    The caller may say so in the environment - the supplement does, because
    its searches are this same script in a subprocess and nothing in the run
    log would otherwise tell them from step 5b's. Nobody having said anything,
    the two jobs this script does are the answer: with facets it is the
    footage pass, bare it is the scoring pass (the difference CF-0129 drew).
    CF-0825: `footage` - the `--facets` flag was given - is the footage pass
    even with no facet at all (a channel's `scope.footage_facets: []`)."""
    return search_quota.article_from_env(
        env, search_quota.ARTICLE_FOOTAGE if (facets or footage)
        else search_quota.ARTICLE_SCORING)


def query_pairs(query, facets, bare=True):
    """`[(label, query)]` - the `search.list` calls one run makes: the bare
    query (unless `bare=False` and there are facets), then one per facet."""
    return ([(BARE_FACET, query)] if bare or not facets else []) + [
        (f, f"{query} {f}") for f in facets]


def calls_needed(query, facets, cache=None, days=7, max_results=15, bare=True):
    """CF-0882: how many `search.list` calls a run would really make - the
    calls of `query_pairs` the cache (`search_cache.Cache`) does not answer.
    Asked before the run (`Cache.peek` records no hit), so a caller with a
    ceiling on the day's calls can decline a run it cannot pay for."""
    return sum(1 for _label, q in query_pairs(query, facets, bare)
               if cache is None or cache.peek(q, days, max_results) is None)


def search_ids(api_key, query, facets, published_after, max_results, spent_on=None,
               bare=True, cache=None, days=None):
    """-> {video_id: [facet label, ...]} over the bare query plus one search
    per facet, in that order. A video found by several searches keeps all of
    their labels; `footage_candidates.py` reads them as a hint about what the
    upload is. `bare=False` (CF-0426, the supplement's person searches) skips
    the bare query: the facets only.

    CF-0824: `cache` (`search_cache.Cache`) answers a call it holds a fresh
    answer to - no request, no `youtube-api search` event (the event the
    day's spend is counted off), a `youtube-cache search` event instead - and
    remembers every real call's ids. `days` is the window the answer is keyed
    on (`published_after` moves every second and is not a key)."""
    found = {}
    spent_on = spent_on or article(facets)
    for label, q in query_pairs(query, facets, bare):
        held = cache.get(q, days, max_results) if cache is not None else None
        if held is not None:
            with runlog.child(search_cache.CACHE_TOOL,
                              argv=[search_cache.CACHE_TOOL, "search", q],
                              params={search_quota.ARTICLE_PARAM: spent_on,
                                      "fetched_at": held.get("fetched_at")}):
                pass
            for vid in held.get("ids") or []:
                labels = found.setdefault(vid, [])
                if label not in labels:
                    labels.append(label)
            continue
        # CF-0107: each Data API call is a `child` event (tool "youtube-api"); a
        # non-2xx answer raises inside the block and lands as `failed`.
        # CF-0368: the event says which article of the quota paid for the call,
        # so the run log can be read by article and not only by total.
        with runlog.child("youtube-api", argv=["youtube-api", "search", q],
                          params={search_quota.ARTICLE_PARAM: spent_on}):
            resp = requests.get(f"{BASE}/search", params={
                "key": api_key,
                "q": q,
                "part": "id,snippet",
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": max_results,
            }, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        ids = []
        for item in data.get("items", []):
            vid = (item.get("id") or {}).get("videoId")
            if not vid:
                continue
            ids.append(vid)
            labels = found.setdefault(vid, [])
            if label not in labels:
                labels.append(label)
        if cache is not None:
            cache.put(q, days, max_results, ids, article=spent_on)
    return found


def fetch_stats(api_key, video_ids, spent_on=None):
    """-> the `/videos` items for every id, in chunks of STATS_CHUNK (the
    endpoint's own ceiling - a facet run routinely gathers more than 50).

    `spent_on` is the article the 1-unit calls belong to (CF-0368);
    `fetch_channel_feeds.Reader.stats` passes the feeds', because the same
    function serves both."""
    items = []
    for i in range(0, len(video_ids), STATS_CHUNK):
        chunk = video_ids[i:i + STATS_CHUNK]
        with runlog.child("youtube-api", argv=["youtube-api", "videos", f"{len(chunk)} ids"],
                          params={search_quota.ARTICLE_PARAM: spent_on} if spent_on else None):
            resp = requests.get(f"{BASE}/videos", params={
                "key": api_key,
                "id": ",".join(chunk),
                "part": STATS_PARTS,
            }, timeout=20)
            resp.raise_for_status()
            items.extend(resp.json().get("items", []))
    return items


def video_record(item, facets):
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    return {
        "video_id": item.get("id"),
        "title": snippet.get("title"),
        "description": (snippet.get("description") or "")[:500],
        "channel_title": snippet.get("channelTitle"),
        # CF-0361: officiality is decided by the channel's id against the
        # channel's registry (channels/<id>/footage-origin.json), not by its name.
        "channel_id": snippet.get("channelId"),
        "published_at": snippet.get("publishedAt"),
        # CF-0302: how long the upload is, read off `contentDetails.duration`.
        # `None` means the API said nothing usable (a live stream, a premiere)
        # and is read downstream as "unknown", never as "short".
        "duration_seconds": duration_seconds((item.get("contentDetails") or {}).get("duration")),
        "view_count": int(stats.get("viewCount", 0)),
        "like_count": int(stats.get("likeCount", 0)) if "likeCount" in stats else None,
        "comment_count": int(stats.get("commentCount", 0)) if "commentCount" in stats else None,
        "facets": list(facets),
        # CF-0662: YouTube's own word on the licence (`status.license`).
        "yt_license": yt_license(item),
    }


def run_signal(query, api_key, days=7, max_results=15, facets_arg=None, no_bare=False,
               channel=None, no_cache=False, max_searches=None):
    """One run of this script, as the dict it prints (main's body).

    `facets_arg` is what `--facets` held: None = the scoring pass,
    CHANNEL_FACETS = the channel's footage facets, a string = named facets.

    CF-0882: `max_searches` is a ceiling on the `search.list` calls this run
    may really make (`calls_needed`, the cache's answers are free). A run that
    would need more is not made at all - no request, no event - and the dict
    says so: `searches: 0`, no videos and `over_budget` with the numbers. Half
    a facet run is not a pool anybody can judge."""
    # CF-0825: a bare `--facets` is the channel's facets, a value names them
    footage = facets_arg is not None
    _, located = search_cache.locate(channel)
    config = search_cache.load_config(located)
    facets_note = None
    if facets_arg == CHANNEL_FACETS:
        facets, facets_from, facets_note = channel_facets(config)
    else:
        facets, facets_from = parse_facets(facets_arg), "--facets"
    published_after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    spent_on = article(facets, footage=footage)
    bare = not (no_bare and facets)
    # CF-0824: the channel's cache of `search.list` answers, TTL by article
    cache = search_cache.open_cache(spent_on, channel=channel, config=config,
                                    off=no_cache)
    over = None
    if max_searches is not None:
        need = calls_needed(query, facets, cache, days, max_results, bare)
        if need > max(0, int(max_searches)):
            over = {"task": "CF-0882", "calls_needed": need,
                    "max_searches": max(0, int(max_searches))}
    found = {}
    if over is None:
        try:
            found = search_ids(api_key, query, facets, published_after, max_results,
                               spent_on=spent_on, bare=bare, cache=cache, days=days)
        finally:
            cache.save()        # the calls made before a failure are paid for - keep them
    # CF-0313: what this run cost in `search.list` calls, said by the only
    # process that knows it for certain. The number is one bare query plus one
    # per facet and has always been derivable from `facets_used`, but the
    # stage now *spends against a remainder* (`search_quota.py`, on the
    # CF-0288 incident), and a budget read off a field that happens to imply
    # it is a budget one changed facet quietly breaks.
    # CF-0824: `searches` is the calls really made - a cache hit is not one,
    # and is said apart as `cached_searches` (`search_quota` keeps it on its
    # own ledger, never in the day's spend).
    head = {"source": "youtube", "query": query, "facets_used": facets,
            "searches": cache.misses, "cached_searches": len(cache.hits),
            "search_cache": cache.block()}
    if footage:
        head["facets_from"] = facets_from
        if facets_note:
            head["facets_note"] = facets_note
    if not bare:
        head["bare"] = False
    if over is not None:
        head["over_budget"] = over
    if not found:
        return {**head, "videos": []}

    videos = [video_record(item, found.get(item.get("id")) or [])
              for item in fetch_stats(api_key, list(found), spent_on=spent_on)]
    videos.sort(key=lambda v: v["view_count"], reverse=True)
    return {**head, "videos": videos}


@runlog.script("trend-hunter", "youtube-signal", name="fetch_youtube_signal.py")
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-results", type=int, default=15)
    parser.add_argument("--facets", nargs="?", const=CHANNEL_FACETS, default=None,
                        help="comma-separated facet phrases for the footage pass "
                             "(bare flag = the channel's scope.footage_facets, without "
                             f"the key {','.join(FOOTAGE_FACETS)}); off by default, "
                             "because the score is calibrated on the bare query's view sum")
    parser.add_argument("--no-bare", action="store_true",
                        help="with --facets: search the facets only, not the bare query "
                             "(CF-0426 - the supplement's person searches)")
    parser.add_argument("--channel",
                        help="the channel whose search cache is used (CF-0824; "
                             "default: the batch of RUNLOG_BATCH)")
    parser.add_argument("--no-cache", action="store_true",
                        help="ask YouTube even for a query the cache holds (its answers "
                             "are still remembered)")
    args = parser.parse_args()

    api_key = youtube_api_key()
    if not api_key:
        print(json.dumps({"error": MISSING}), file=sys.stderr)
        sys.exit(1)

    out = run_signal(args.query, api_key, days=args.days, max_results=args.max_results,
                     facets_arg=args.facets, no_bare=args.no_bare, channel=args.channel,
                     no_cache=args.no_cache)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

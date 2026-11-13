#!/usr/bin/env python3
"""CF-0361 - footage candidates of a topic out of the official channels' own
upload feeds, not out of a YouTube-wide search.

Why. On 2026-09-23 the day's 100 `search.list` calls ran out, and 77 of the 91
the factory had spent went to footage - a facet run per topic (6 searches) and
the supplement (`CF-0343`). The footage we keep is almost always an upload of a
studio or network channel that is already on the registry - the batch's
channel's `channels/<id>/footage-origin.json` (CF-0627) - and a channel's own uploads can be read without
search at all:

  * its **RSS feed** `https://www.youtube.com/feeds/videos.xml?channel_id=<id>`
    - the latest ~15 uploads, **0 units**. Read for every registered channel;
  * its **uploads playlist** (`UU` + the id's tail) through
    `playlistItems.list` - **1 unit per 50 uploads**, for depth. Read only for
    the channels of the topic's rights holder / network (`owners`), the
    licensed distributors (`general`) and any channel whose RSS feed already
    names the work, `--pages` pages each, once per process;
  * `videos.list` on the uploads whose **title** names the work - 1 unit per 50
    ids - for the length and the counts (`fetch_youtube_signal.video_record`,
    the same record the facet run writes).

The search also brought what the feeds cannot: batch 2026-09-23T1722Z's
facet runs handed one topic a political talk show (the idiom), another a
mobile game and other people's reactions, and a reaction channel whose logo
the frame judge refused. An upload of the
rights holder's own channel whose title names the work has none of those.

The output is a signal of the same shape as `fetch_youtube_signal.py`'s
(`source: "youtube-feeds"`, `searches: 0`, every video labelled `feed`), so
`footage_candidates.py` picks from it exactly as it picks from a facet run -
the same `topic_relevance` / `footage_origin` / `footage_sieve` / length
ceiling. It also says whether the feeds were enough: `fallback_search` is true
when they gave fewer than `CANDIDATE_REFUSAL_FLOOR` candidates, i.e. when the
topic would be refused without a search. Only then is the facet run spent, and
its output is handed to `footage_candidates.py` next to this one (two
`--signal` files for one topic are merged).

CF-0661 - when the RSS feed does not answer. One day every
`feeds/videos.xml` URL answered 404 from the factory's machine - every
channel of a registry, in every form (`channel_id=`, `playlist_id=UU...`,
`user=`, with a browser User-Agent or without). A feed that does not answer used to be one line in `channels_failed`
and the channel silently gave nothing - the topic then fell to the facet
search, i.e. to the day's 100 searches. Now a channel whose RSS read failed is
read again through **yt-dlp**, the channel's uploads playlist (`UU` + the id's
tail) as a flat playlist - the same latest `FALLBACK_ENTRIES` uploads the
feed held, id / title / approximate date / channel, **0 units**, no download.
The failed channels go to one yt-dlp call per `FALLBACK_CHUNK` channels, a
single plain request each. What the read was is in every signal's `feed_read`
(how many channels answered by RSS, how many did not and with what, how many
yt-dlp read, how many nobody read, and by which path each candidate came),
which `footage_candidates.py` copies into the topic's
`evidence.footage_feed_read` in `01`, and one `youtube-feeds-read: ...` line in
the run log. A reader handed a fake HTTP layer gets no real yt-dlp unless a
runner is handed in too: a test never starts a process by omission.

Usage:
  fetch_channel_feeds.py "Example Title" --rights-holder "Example Studios" [--network X] > feed.json
  fetch_channel_feeds.py --batch <batch-dir> --out-dir <dir> [--topic <id> ...]

Requires YOUTUBE_API_KEY for `playlistItems.list` / `videos.list` (the environment,
else this repo's .env - `_apikey.py`, CF-0360); the RSS
feeds need no key. `--pages 0` reads the RSS feeds only (0 units, no key).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from _apikey import MISSING, youtube_api_key  # noqa: E402
from _runlog import factory_root, runlog  # noqa: E402
import _channel_ids  # noqa: E402
import footage_candidates as fc  # noqa: E402
import search_quota  # noqa: E402
import footage_origin  # noqa: E402
import topic_relevance  # noqa: E402
from fetch_youtube_signal import BASE, STATS_CHUNK, fetch_stats, video_record  # noqa: E402

RSS_URL = "https://www.youtube.com/feeds/videos.xml"
FEED_FACET = "feed"
SOURCE = "youtube-feeds"
# Pages of 50 read off an owned or general channel's uploads playlist. Two
# pages is ~100 uploads: several weeks of a studio, one to two of ExampleStream.
DEFAULT_PAGES = 2
PAGE_SIZE = 50
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}

# CF-0661: the read of a channel whose RSS feed did not answer.
VIA_RSS = "rss"
VIA_YTDLP = "yt-dlp"
VIA_UPLOADS = "uploads"          # the Data API's uploads playlist (the deep read)
FALLBACK_ENTRIES = 15            # as many uploads as the RSS feed holds
FALLBACK_CHUNK = 15              # channels per yt-dlp call (~2 s a channel, measured 2026-10-10)
FALLBACK_TIMEOUT_SECONDS = 150   # one call; a hung yt-dlp is a failed read, not a hung stage
UPLOADS_URL = "https://www.youtube.com/playlist?list={playlist}"
YTDLP_ENV = "TH_YTDLP"           # an explicit binary wins over the lookup below
# Where the fallback finds yt-dlp when this repo's environment has none (its
# .venv is the home checkout's and was built before CF-0661 added the
# requirement): the footage indexer's copy of the same factory, which pins
# the version the factory already runs (CF-0267).
SIBLING_YTDLP = Path("agents") / "footage-indexer" / ".venv" / "bin" / "yt-dlp"


def ytdlp_path(root=None):
    """The yt-dlp binary the fallback runs, or None: `TH_YTDLP`, this repo's
    environment, PATH, the footage indexer's environment of the same factory."""
    env = os.environ.get(YTDLP_ENV)
    if env:
        return env
    own = Path(sys.executable).parent / "yt-dlp"
    if own.exists():
        return str(own)
    found = shutil.which("yt-dlp")
    if found:
        return found
    try:
        sib = Path(root or factory_root()) / SIBLING_YTDLP
    except RuntimeError:
        return None
    return str(sib) if sib.exists() else None


def uploads_playlist(cid):
    return "UU" + cid[2:] if cid.startswith("UC") else cid


def ytdlp_command(binary, cids, entries=FALLBACK_ENTRIES):
    """One flat read of these channels' uploads playlists: no download, no
    video page, `approximate_date` for the dates the tab only gives as "3 days
    ago", `-i` so one dead channel does not take the others with it."""
    cmd = [str(binary), "--flat-playlist", "--playlist-end", str(entries), "-J", "-i",
           "--no-warnings", "--extractor-args", "youtubetab:approximate_date"]
    return cmd + [UPLOADS_URL.format(playlist=uploads_playlist(c)) for c in cids]


def _iso(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def parse_flat_playlists(stdout):
    """yt-dlp's `-J` output, one JSON per channel read -> {channel_id: [entry]}
    in the RSS entries' shape (`parse_rss`)."""
    out = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        pid = d.get("id") or ""
        cid = d.get("channel_id") or ("UC" + pid[2:] if pid.startswith("UU") else pid)
        if not cid:
            continue
        # `channel` of a yt-dlp line is the uploader's YouTube channel *name*
        # ("NASA", "ExampleStream") - display text off yt-dlp metadata, never a
        # factory channel id out of a batch file, so there is nothing for
        # `_channel_ids.resolve_channel` to resolve (the yt-dlp case of the
        # root's tests/test_former_channel_ids.py NOT_BATCH_CHANNEL, CF-0599).
        name = d.get("channel") or d.get("uploader") or ""
        rows = []
        for e in d.get("entries") or []:
            vid = (e or {}).get("id")
            if not vid:
                continue
            rows.append({"video_id": vid, "title": e.get("title") or "",
                         "channel_id": e.get("channel_id") or cid,
                         "channel_title": e.get("channel") or name,  # the uploader's name, as above
                         "published_at": _iso(e.get("timestamp") or e.get("release_timestamp"))})
        out[cid] = rows
    return out


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class Reader:
    """Reads feeds and playlists once per process and counts the units spent.
    `http` is injectable so the tests run on fixtures without the network;
    so is `runner` (`runner(cmd, timeout) -> CompletedProcess`), the yt-dlp
    fallback of a feed that did not answer (CF-0661). A reader handed a fake
    `http` and no `runner` has no fallback - a test never starts a real
    process by omission."""

    def __init__(self, api_key=None, http=None, runner=None, ytdlp=None):
        self.api_key = api_key
        self.http = http or requests.get
        if runner is None and http is None:
            runner = _run
        self.runner = runner
        self.ytdlp = ytdlp
        self.units = 0
        self.rss = {}        # channel_id -> [entry] or None when it failed
        self.uploads = {}    # (channel_id, pages) -> [entry] or None
        self.failed = []     # channels nobody could read (RSS and fallback), dead uploads
        self.via = {}        # channel_id -> VIA_RSS / VIA_YTDLP / None
        self.rss_errors = {}  # channel_id -> what the RSS read said
        self.fallback_errors = {}  # channel_id -> why the fallback did not read it
        self.fallback_calls = 0

    def _read_rss(self, cid, title=None):
        """One RSS read -> [entry], or None (the error kept in `rss_errors`)."""
        try:
            with runlog.child("youtube-rss", argv=["youtube-rss", "feed", cid],
                              params={search_quota.ARTICLE_PARAM:
                                      search_quota.ARTICLE_FEEDS}):
                resp = self.http(RSS_URL, params={"channel_id": cid}, timeout=20)
                resp.raise_for_status()
                return parse_rss(resp.text)
        except Exception as exc:  # noqa: BLE001 - one dead feed is not a dead run
            status = getattr(getattr(exc, "response", None), "status_code", None)
            self.rss_errors[cid] = {"status": status or _status_of(exc),
                                    "error": str(exc)[:200]}
            return None

    def read_rss(self, cid, title=None):
        """The channel's latest uploads: its RSS feed, else (CF-0661) its
        uploads playlist through yt-dlp."""
        if cid not in self.rss:
            self.prefetch([{"id": cid, "title": title}])
        return self.rss.get(cid) or []

    def prefetch(self, channels):
        """Read every channel not read yet: RSS one by one, then the ones
        whose feed did not answer in one yt-dlp call per `FALLBACK_CHUNK`."""
        dead = []
        for ch in channels:
            cid = ch["id"]
            if cid in self.rss or any(cid == d["id"] for d in dead):
                continue
            entries = self._read_rss(cid, ch.get("title"))
            if entries is None:
                dead.append(ch)
                continue
            self.rss[cid], self.via[cid] = entries, VIA_RSS
        if not dead:
            return
        got = self._fallback([d["id"] for d in dead])
        for ch in dead:
            cid = ch["id"]
            if cid in got:
                self.rss[cid], self.via[cid] = got[cid], VIA_YTDLP
                continue
            self.rss[cid], self.via[cid] = None, None
            self.failed.append({"channel_id": cid, "title": ch.get("title"), "via": VIA_RSS,
                                "error": (self.rss_errors.get(cid) or {}).get("error"),
                                "fallback": self.fallback_errors.get(cid)})

    def _fallback(self, cids):
        """-> {channel_id: [entry]} of the channels yt-dlp read."""
        if self.runner is None:
            for cid in cids:
                self.fallback_errors[cid] = "no fallback (a reader on a fake HTTP layer)"
            return {}
        binary = self.ytdlp or ytdlp_path()
        if not binary:
            for cid in cids:
                self.fallback_errors[cid] = (f"yt-dlp not found ({YTDLP_ENV}, this repo's "
                                             f".venv, PATH, {SIBLING_YTDLP})")
            return {}
        got = {}
        for i in range(0, len(cids), FALLBACK_CHUNK):
            chunk = cids[i:i + FALLBACK_CHUNK]
            read, err = self._ytdlp(binary, chunk)
            got.update(read)
            left = [c for c in chunk if c not in read]
            for cid in left:
                self.fallback_errors[cid] = (err.strip().splitlines()[-1][:200] if err.strip()
                                             else "yt-dlp gave nothing for this channel")
        return got

    def _ytdlp(self, binary, cids):
        cmd = ytdlp_command(binary, cids)
        self.fallback_calls += 1
        try:
            with runlog.child("yt-dlp", argv=["yt-dlp", "flat-playlist", *cids],
                              params={search_quota.ARTICLE_PARAM: search_quota.ARTICLE_FEEDS}) as frame:
                out = self.runner(cmd, FALLBACK_TIMEOUT_SECONDS)
                frame["rc"] = out.returncode
        except subprocess.TimeoutExpired:
            return {}, f"yt-dlp timed out after {FALLBACK_TIMEOUT_SECONDS} s"
        except Exception as exc:  # noqa: BLE001 - a dead fallback is not a dead run
            return {}, f"yt-dlp did not run: {exc}"[:200]
        read = parse_flat_playlists(out.stdout)
        return {c: read[c] for c in cids if c in read}, out.stderr or ""

    def status(self, cids=None):
        """What the read of these channels (all read so far by default) was:
        the `feed_read` block of a signal."""
        cids = list(self.rss) if cids is None else [c for c in cids if c in self.rss]
        statuses = {}
        for c in cids:
            if c in self.rss_errors:
                k = str(self.rss_errors[c].get("status") or "error")
                statuses[k] = statuses.get(k, 0) + 1
        unread = [c for c in cids if self.via.get(c) is None]
        return {"channels": len(cids),
                "rss_answered": sum(1 for c in cids if self.via.get(c) == VIA_RSS),
                "rss_failed": sum(1 for c in cids if c in self.rss_errors),
                "rss_failed_by_status": statuses,
                "fallback": VIA_YTDLP,
                "fallback_read": sum(1 for c in cids if self.via.get(c) == VIA_YTDLP),
                "unread": len(unread),
                "unread_reasons": sorted({self.fallback_errors.get(c) or "?" for c in unread})}

    def read_uploads(self, cid, pages, title=None):
        key = (cid, pages)
        if key in self.uploads:
            return self.uploads[key] or []
        if pages <= 0 or not self.api_key:
            return []
        entries, token = [], None
        try:
            for _ in range(pages):
                params = {"key": self.api_key, "playlistId": "UU" + cid[2:],
                          "part": "snippet", "maxResults": PAGE_SIZE}
                if token:
                    params["pageToken"] = token
                with runlog.child("youtube-api", argv=["youtube-api", "playlistItems", cid],
                                  params={search_quota.ARTICLE_PARAM:
                                          search_quota.ARTICLE_FEEDS}):
                    resp = self.http(f"{BASE}/playlistItems", params=params, timeout=20)
                    self.units += 1
                    resp.raise_for_status()
                    data = resp.json()
                for item in data.get("items") or []:
                    sn = item.get("snippet") or {}
                    vid = (sn.get("resourceId") or {}).get("videoId")
                    if vid:
                        entries.append({"video_id": vid, "title": sn.get("title"),
                                        "channel_id": sn.get("channelId") or cid,
                                        "channel_title": sn.get("channelTitle"),
                                        "published_at": sn.get("publishedAt")})
                token = data.get("nextPageToken")
                if not token:
                    break
        except Exception as exc:  # noqa: BLE001
            self.failed.append({"channel_id": cid, "title": title, "via": "uploads",
                                "error": str(exc)[:200]})
        self.uploads[key] = entries
        return entries

    def stats(self, ids):
        if not ids or not self.api_key:
            return []
        self.units += (len(ids) + STATS_CHUNK - 1) // STATS_CHUNK
        # CF-0368: 1 unit a call and never a `search.list`, whichever stage's
        # step this reader happens to be running under - the supplement reads
        # feeds in its own process (CF-0369) and the article is the feeds' all
        # the same.
        return fetch_stats(self.api_key, ids, spent_on=search_quota.ARTICLE_FEEDS)


def _status_of(exc):
    m = re.search(r"\b([45]\d\d)\b", str(exc))
    return int(m.group(1)) if m else None


def status_line(st):
    """The run log's one line about the feeds (CF-0661): a feed that did not
    answer is said, not left as "0 candidates"."""
    codes = ", ".join(f"HTTP {k} x{v}" if k.isdigit() else f"{k} x{v}"
                      for k, v in sorted(st.get("rss_failed_by_status", {}).items()))
    line = (f"youtube-feeds-read: RSS {st['rss_answered']}/{st['channels']}"
            + (f" ({codes})" if codes else ""))
    if st.get("rss_failed"):
        line += f"; {st['fallback']} {st['fallback_read']}/{st['rss_failed']}"
    line += f"; unread {st['unread']}"
    if st.get("unread"):
        line += f" ({'; '.join(st.get('unread_reasons') or [])})"[:300]
    return line


def log_status(reader, cids=None):
    """Say what the feed read was: stderr and one child event of that name in
    the run log (RUN_LOG.txt prints a child by its tool name)."""
    status_of = getattr(reader, "status", None)
    if status_of is None:
        return None
    st = status_of(cids)
    if not st.get("channels"):
        return st
    line = status_line(st)
    print(line, file=sys.stderr)
    try:
        with runlog.child(line[:240], argv=["youtube-feeds-read"],
                          params={search_quota.ARTICLE_PARAM: search_quota.ARTICLE_FEEDS,
                                  "feed_read": st}):
            pass
    except Exception:  # noqa: BLE001 - the journal line never fails the read
        pass
    return st


def parse_rss(text):
    """-> [{video_id, title, channel_id, channel_title, published_at}] of one
    channel feed."""
    root = ET.fromstring(text)
    out = []
    for entry in root.findall("a:entry", NS):
        vid = entry.findtext("yt:videoId", default="", namespaces=NS)
        if not vid:
            continue
        out.append({"video_id": vid,
                    "title": entry.findtext("a:title", default="", namespaces=NS),
                    "channel_id": entry.findtext("yt:channelId", default="", namespaces=NS),
                    "channel_title": entry.findtext("a:author/a:name", default="",
                                                    namespaces=NS),
                    "published_at": entry.findtext("a:published", default="",
                                                   namespaces=NS)})
    return out


def names_in_title(entry, forms):
    """The feed entry's **title** names the work. Title only, not the
    description: an official channel is never sieved downstream, so a ExampleStream
    round-up whose description lists the work would otherwise walk in as its
    footage."""
    field, _ = topic_relevance.names_work({"title": entry.get("title")}, forms)
    return bool(field)


def topic_houses(topic, channel, root=None):
    """CF-0662 (TH-1): the publishing houses whose feeds carried this topic -
    its `evidence.rss_links` and `evidence.sources[].url` mapped by the
    channel's feed map (`sources.rss.feeds[].site` -> `house`, the scorer's
    `feed_houses`). A link of no listed site is skipped, not guessed; a
    channel config that does not read gives no houses.

    CF-0753: a link is the house of the feed that carried it when the topic's
    `evidence.sources[].feed` says which (an aggregator's entry - Hacker News -
    links off its own site), by its domain otherwise
    (`score_candidates.attribute_links`). A company's own feed (`kind:
    vendor`) counts here too: it adds no house to the score, but its owner's
    official channels are exactly the ones to read."""
    import score_candidates
    ev = (topic or {}).get("evidence") or {}
    links = list(ev.get("rss_links") or []) + [s.get("url") for s in ev.get("sources") or []
                                               if isinstance(s, dict) and s.get("url")]
    if not links or not channel:
        return []
    try:
        path = Path(_channel_ids.channel_config_path(str(channel), root=root))
        config = json.loads(path.read_text(encoding="utf-8"))
        score_candidates.feed_houses(config)            # a config that does not read
    except Exception:                                   # noqa: BLE001
        return []
    link_feeds = score_candidates.topic_link_feeds(topic)
    houses = []
    for link in links:
        found = score_candidates.attribute_links([link], config, link_feeds)
        for house in sorted(found["houses"] | found["vendor_feeds"]):
            if house not in houses:
                houses.append(house)
    return houses


def topic_feed(title_ref, reader, pages=DEFAULT_PAGES, config=None, limits=None, houses=None):
    """-> the signal of one topic out of the feeds (the shape of
    `fetch_youtube_signal.py`'s output plus what the feeds were).

    CF-0662: `houses` (default `title_ref["houses"]`) are the publishing houses
    the topic came from; an official channel they own is read deep, as the
    rights holder's is."""
    config = footage_origin._require(config)
    title_ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    houses = list(houses if houses is not None else title_ref.get("houses") or [])
    forms = topic_relevance.work_forms(title_ref)
    owned, general = footage_origin.feed_channels(title_ref.get("rights_holder"),
                                                  title_ref.get("network"), config,
                                                  houses=houses)
    units_before = reader.units
    registry = [ch for entry in config["official_channels"]
                for ch in entry.get("channels") or []]
    prefetch = getattr(reader, "prefetch", None)
    if prefetch is not None:
        prefetch(registry)      # CF-0661: the dead feeds go to yt-dlp together
    via = getattr(reader, "via", {})
    seen, matched, named_it, came_by = 0, {}, [], {}
    for entry in config["official_channels"]:
        for ch in entry.get("channels") or []:
            hit = False
            for e in reader.read_rss(ch["id"], ch.get("title")):
                seen += 1
                if names_in_title(e, forms):
                    matched.setdefault(e["video_id"], e)
                    came_by.setdefault(e["video_id"], via.get(ch["id"]) or VIA_RSS)
                    hit = True
            if hit:
                named_it.append({"id": ch["id"], "title": ch.get("title"),
                                 "pattern": entry["pattern"]})
    # Read deep: the rights holder's and network's channels, the licensed
    # distributors, and any registered channel whose latest uploads already
    # name the work - on 2026-09-23T1722Z American Dread Story had no rights
    # holder in its title_ref, and its FX teaser sat below FX's 15 latest
    # uploads (all #AHS shorts) where only the playlist reaches.
    deep, ids = [], set()
    for ch in owned + general + named_it:
        if ch["id"] not in ids:
            ids.add(ch["id"])
            deep.append(ch)
    for ch in deep:
        for e in reader.read_uploads(ch["id"], pages, ch.get("title")):
            seen += 1
            if names_in_title(e, forms):
                matched.setdefault(e["video_id"], e)
                came_by.setdefault(e["video_id"], VIA_UPLOADS)
    items = reader.stats(list(matched))
    if items:
        videos = [video_record(item, [FEED_FACET]) for item in items]
    else:
        # No key (`--pages 0` run) or the stats call failed: the feed entry is
        # still a candidate, with no length and no counts - unknown, not short.
        videos = [dict(e, description="", duration_seconds=None, view_count=0,
                       like_count=None, comment_count=None, facets=[FEED_FACET],
                       yt_license=None)
                  for e in matched.values()]
    videos.sort(key=lambda v: v.get("view_count") or 0, reverse=True)
    candidates, _ = fc.select_candidates(videos, title_ref, limits=limits, config=config)
    found = len(candidates)
    fallback = found < fc.CANDIDATE_REFUSAL_FLOOR
    status_of = getattr(reader, "status", None)
    feed_read = status_of([ch["id"] for ch in registry]) if status_of else None
    if feed_read is not None:
        # CF-0661: by which path the matches and the candidates came, so a
        # topic with no feed candidate says whether the feeds were read at all.
        feed_read["matched_via"] = _count_by(came_by.get(v) for v in matched)
        feed_read["candidates_via"] = _count_by(came_by.get(c.get("video_id"))
                                                for c in candidates)
    return {
        "source": SOURCE, "query": title_ref.get("name"), "facets_used": [],
        "searches": 0, "api_units": reader.units - units_before,
        "channels": {"rss": sum(len(e.get("channels") or [])
                                for e in config["official_channels"]),
                     "uploads": [c["title"] for c in deep],
                     "owned": [c["title"] for c in owned],
                     "houses": houses,
                     "named_the_work": [c["title"] for c in named_it]},
        "feed_entries_seen": seen, "matched": len(matched),
        "candidates_found": found, "fallback_search": fallback,
        "fallback_reason": (f"the feeds gave {found} candidate(s), fewer than "
                            f"{fc.CANDIDATE_REFUSAL_FLOOR}: run the facet search "
                            f"(fetch_youtube_signal.py --facets) and hand both files "
                            f"to footage_candidates.py" if fallback else None),
        "feed_read": feed_read,
        "videos": videos,
    }


def _count_by(values):
    out = {}
    for v in values:
        out[v or "?"] = out.get(v or "?", 0) + 1
    return out


def batch_topics(batch, only=None, root=None):
    """-> (topic_id, title_ref) per topic with a name; the ref carries the
    topic's publishing houses (`houses`, CF-0662) when its links name any."""
    channel = fc._batch_channel(batch)
    for topic in batch.get("topics") or []:
        tid = topic.get("topic_id")
        if only and tid not in only:
            continue
        if (topic.get("title_ref") or {}).get("name"):
            ref = topic["title_ref"]
            houses = topic_houses(topic, channel, root=root)
            yield tid, (dict(ref, houses=houses) if houses else ref)


@runlog.script("trend-hunter", "youtube-feeds", name="fetch_channel_feeds.py")
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query", nargs="?")
    ap.add_argument("--rights-holder")
    ap.add_argument("--network")
    ap.add_argument("--batch", help="batch dir or 01-trend-hunter.json: one signal per topic")
    ap.add_argument("--out-dir", help="with --batch: where feed-<topic_id>.json go")
    ap.add_argument("--topic", action="append", help="with --batch: only these topic ids")
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                    help=f"uploads-playlist pages of {PAGE_SIZE} per owned/general channel "
                         f"(1 unit each; 0 = RSS only, no key needed)")
    ap.add_argument("--house", action="append",
                    help="without --batch: a publishing house the story came from "
                         "(sources.rss.feeds[].house, e.g. nasa) - its official channels "
                         "are read deep (CF-0662)")
    ap.add_argument("--channel",
                    help="the channel whose official footage channels are read (CF-0627); "
                         "with --batch it is the batch's `channel`, required otherwise")
    args = ap.parse_args(argv)
    key = youtube_api_key()
    if args.pages > 0 and not key:
        print(json.dumps({"error": MISSING + " (or pass --pages 0)"}),
              file=sys.stderr)
        return 1
    batch = None
    if args.batch:
        path = fc._batch_path(args.batch)
        batch = json.loads(Path(path).read_text())
    channel = args.channel or (fc._batch_channel(batch) if batch is not None else None)
    reader = Reader(api_key=key)
    try:
        config = footage_origin.load_config(channel)
    except footage_origin.ConfigError as exc:
        print(json.dumps({"error": f"footage origin: {exc}"}), file=sys.stderr)
        return 2
    if batch is not None:
        limits = fc.channel_ceiling(fc._batch_channel(batch))
        out_dir = Path(args.out_dir or Path(path).parent / "work" / "feeds")
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = []
        for tid, ref in batch_topics(batch, set(args.topic or [])):
            sig = topic_feed(ref, reader, pages=args.pages, config=config, limits=limits)
            target = out_dir / f"feed-{tid}.json"
            target.write_text(json.dumps(sig, ensure_ascii=False, indent=2))
            summary.append({"topic_id": tid, "name": ref.get("name"), "file": str(target),
                            "matched": sig["matched"], "candidates": sig["candidates_found"],
                            "fallback_search": sig["fallback_search"],
                            "api_units": sig["api_units"],
                            "candidates_via": (sig.get("feed_read") or {}).get("candidates_via")})
        st = log_status(reader)
        print(json.dumps({"api_units": reader.units, "searches": 0, "feed_read": st,
                          "channels_failed": reader.failed, "topics": summary},
                         ensure_ascii=False, indent=2))
        return 0
    if not args.query:
        ap.error("a title, or --batch")
    ref = {"name": args.query, "rights_holder": args.rights_holder, "network": args.network}
    if args.house:
        ref["houses"] = list(args.house)
    sig = topic_feed(ref, reader, pages=args.pages, config=config)
    log_status(reader)
    sig["channels_failed"] = reader.failed
    print(json.dumps(sig, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

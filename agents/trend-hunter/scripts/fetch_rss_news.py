#!/usr/bin/env python3
"""Fetch recent entries from a list of entertainment-trade feeds. Prints JSON to stdout.

No API key needed. Reads the feeds of `--channel <id>` - the channel's
`sources.rss.feeds`, through the root's `shared/channel_data.py`
(`channel_data.feed_urls`, CF-0634): a channel whose feeds break the AI-bot rule
(docs/channel-data.md of the root, «Sources and the AI-bot rule») is a refusal,
exit 2, and nothing is fetched. `--feeds <url ...>` names the feeds by hand
instead (a replay, a single feed); one of the two is required - there is no
default channel (CF-0213).

CF-0007: `--days` used to be a filter over whatever the feed's front page
happened to hold, not a depth request. Variety/Deadline/THR each serve exactly
10-12 items on `/feed/`, covering roughly three *hours* of publishing - so
`--days 14` and `--days 3` returned the same ~32 entries and the flag was a
silent no-op. This script now keeps walking a source backwards until the
requested window is actually covered:

  1. the declared RSS feed's first page (always, cheapest, gives the feed title);
  2. if that does not reach back to the cutoff, the site's WordPress REST
     collection (`/wp-json/wp/v2/posts`, 100 posts per request) - all three
     trades run WordPress and leave it open;
  3. if REST is unavailable, `?paged=N` on the RSS feed itself (10-12 per
     request), which every WordPress feed supports.

Whatever is *not* covered is reported, never silently truncated: see the
`coverage` and `warnings` keys in the output.

CF-0059: the per-feed telemetry (`strategy`, `requests_made`, `stopped_because`,
`max_requests`) is part of the output contract and is meant to be carried into
the batch file verbatim - see `batch_discovery_record()`. The request ceiling
is derived from that telemetry, not guessed; see DEFAULT_MAX_REQUESTS_PER_FEED.

Usage:
  fetch_rss_news.py --channel example-film [--days 3]
  fetch_rss_news.py --feeds https://variety.com/feed/ https://deadline.com/feed/ [--days 3]
  fetch_rss_news.py --feeds ... --days 14 --max-requests-per-feed 20
  fetch_rss_news.py --feeds ... --no-deep      # old single-page behaviour
"""
import argparse
import calendar
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import feedparser
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402

# --------------------------------------------------------------------------
# Access stance - decided in CF-0045 (2026-09-03), implemented by CF-0059.
# Read this before changing the user agent, the request ceiling or the
# field list below; they are three parts of one position.
#
# What the trades' robots.txt actually say (re-read 2026-09-03; Variety,
# Deadline and THR carry the same file): under `User-agent: *` the only
# Disallows are /wp-admin/, site search (?s=, /search), ?replytocom, /genre/
# and preview URLs. Neither /feed/ nor /wp-json/ is disallowed for `*` - they
# are open by robots.txt's default, not by an explicit Allow line. A blanket
# `Disallow: /` exists only under named agents: anthropic-ai, ClaudeBot,
# Claude-Web, GPTBot, ChatGPT-User, CCBot, PerplexityBot, Google-Extended,
# Bytespider and the rest of the training/retrieval crawler list. A site that
# wanted its REST collection closed to everyone would write
# `Disallow: /wp-json/` under `*`; none of the three has.
#
# What this script relies on: that `*` rule, under its own honest name.
# Not a browser disguise, and not one of the blocked names either - the named
# blocks target crawlers that build corpora or index the site, and this tool
# does neither.
#
# What it takes: title, link, publication date and an excerpt cut to
# DEFAULT_SUMMARY_CHARS. REST_FIELDS below is the entire list; article bodies
# are never requested. This is topic selection by headline, not material for
# retelling.
#
# What it sends: at most DEFAULT_MAX_REQUESTS_PER_FEED requests per feed per
# run, DEFAULT_DELAY apart, and the ceiling is derived from a measured run -
# see that constant. The same stance applies unchanged to any feed added to
# the pool: a source that disallows its feed for `*` does not get read,
# whatever it says about named agents.
#
# Vulture (added by CF-0060, robots.txt read 2026-09-03): the same shape.
# Under `User-agent: *` vulture.com disallows only /search/, /search.html,
# /newyork/, /contactus/ and *?origSession=* - the feed is open by default.
# The blanket `Disallow: /` blocks are under named agents (anthropic-ai,
# ClaudeBot, Claude-Web, Claude-User, Claude-SearchBot, GPTBot-class crawlers,
# python-requests, Scrapy, ...), none of which this script is. The feed is
# served from feeds.feedburner.com, whose own robots.txt is a redirect stub;
# the position is taken on the publisher's file. There is no REST collection
# and FeedBurner ignores ?paged=N, so the feed costs exactly 2 requests a run
# (front page + one page-2 probe that the `added == 0` guard turns into
# `source_exhausted`) and covers ~1 day. Measured, and pinned by
# tests/test_feed_depth.py on the captured response.
# --------------------------------------------------------------------------
DEFAULT_USER_AGENT = "shorts-content-factory/trend-hunter (personal research tool)"

DEFAULT_DAYS = 3

# CF-0789: how far back a channel's discovery reaches is the channel's
# (`sources.rss.discovery_days` of `channels/<channel>.json`); a channel that
# says nothing takes DEFAULT_DAYS, ExampleFilm's measured window (CF-0059).
# A small channel's feeds hold few entries a day (ExampleScience 2026-10-17:
# 102 entries over eight feeds in three days, against ExampleFilm's ~470), and
# a wider window is volume that costs no search call. The bounds keep a typo
# from becoming a month of fetching: 14 days is the deepest window the
# request ceiling below was derived for.
DAYS_KEY = ("sources", "rss", "discovery_days")
MIN_DAYS, MAX_DAYS = 1, 14

# Emergency stop on requests per feed per run - NOT a working limit. Derived
# from measurement (CF-0059, 2026-09-03): `--days 14`, the deepest window the
# skill asks for, against the three configured trades, all three stopping on
# `covered`:
#
#   Variety    9 requests (1 feed page + 8 REST pages)   772 posts in window
#   Deadline   9 requests (1 + 8)                        754
#   THR        7 requests (1 + 6)                        564
#
# So the real need is 1 + ceil(posts_in_window / REST_PAGE_SIZE): ~55 posts a
# day per trade, 9 requests. 12 is that plus a third - room for ~80 posts a
# day (a festival or awards week) before the stop engages - and a hard bound of
# 12 * 100 = 1,200 posts per feed per run, against the 2,500 the previous,
# never-measured 25 allowed. The skill's default `--days 3` needs 3-4.
#
# If a configured feed ever stops on `max_requests` instead of `covered` /
# `source_exhausted` on a normal window, this number is under the need:
# re-measure (the batch's `discovery.rss.coverage` rows are the instrument)
# and raise it HERE. Passing a bigger --max-requests-per-feed is fine for one
# run, but a ceiling that only holds because everyone overrides it is the
# situation CF-0045 objected to. On the `?paged=N` fallback (10-12 posts a
# request) 12 requests reach ~2 days; that path is a degraded mode and says
# so in `warnings`.
DEFAULT_MAX_REQUESTS_PER_FEED = 12

# Deliberately uncapped - CF-0059 looked at this. The request ceiling already
# bounds a feed at DEFAULT_MAX_REQUESTS_PER_FEED * REST_PAGE_SIZE entries; a
# second default would be a second statement of the same intent, free to
# drift from the first. The flag stays for one-off runs.
DEFAULT_MAX_ENTRIES_PER_FEED = 0  # 0 = no cap
DEFAULT_DELAY = 0.5
DEFAULT_TIMEOUT = 20
DEFAULT_SUMMARY_CHARS = 500

REST_PATH = "/wp-json/wp/v2/posts"
REST_PAGE_SIZE = 100
REST_FIELDS = "id,date_gmt,link,title,excerpt"
# WordPress filters `after` against the post's *site-local* date while we work
# in UTC (the trades run US Pacific, so up to 8h of skew). Ask for a day more
# than needed and cut exactly on date_gmt ourselves.
REST_AFTER_MARGIN = timedelta(days=1)

# Feed paths we are willing to swap for the site-wide REST collection. A
# section feed (e.g. /v/film/feed/) must NOT be swapped - the REST collection
# at the site root is a *wider* set, and silently widening someone's chosen
# section is exactly the kind of quiet scope change CF-0007 is about.
SITEWIDE_FEED_PATHS = {"", "/feed", "/feed/rss2", "/rss"}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def clean_text(value, limit=None):
    """Tags out, entities decoded, whitespace collapsed.

    RSS `description` arrives as plain CDATA text while the REST `excerpt`
    arrives wrapped in `<p>...</p>\\n` with `&#8216;`-style entities. Both
    paths feed the same field, so both get normalised the same way - otherwise
    entries look different depending on which transport happened to fetch them.
    """
    if not value:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit] if limit else text


def normalize_link(link):
    """Canonical form for dedup: scheme, www., trailing slash, query, fragment
    all dropped. The same post reached via RSS and via REST differs in exactly
    those places."""
    if not link:
        return ""
    parsed = urlparse(str(link).strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/").lower()
    return f"{netloc}{path}"


def normalize_title(title):
    return _WS_RE.sub(" ", clean_text(title).lower()).strip()


def rest_endpoint_for(feed_url):
    """The site-wide WordPress REST posts collection for a site-wide feed URL,
    or None when this feed is section-scoped (see SITEWIDE_FEED_PATHS)."""
    parsed = urlparse(feed_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.path.rstrip("/") not in SITEWIDE_FEED_PATHS:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, REST_PATH, "", "", ""))


def paged_feed_url(feed_url, page):
    parsed = urlparse(feed_url)
    query = parsed.query
    extra = f"paged={page}"
    query = f"{query}&{extra}" if query else extra
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


class HttpClient:
    """One session, one user agent, one timeout, a floor on the gap between
    requests. Tests substitute an object with the same `get(url, params=None)`."""

    def __init__(self, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT, delay=DEFAULT_DELAY):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.timeout = timeout
        self.delay = delay
        self._last_at = None

    def get(self, url, params=None):
        if self._last_at is not None:
            wait = self.delay - (time.monotonic() - self._last_at)
            if wait > 0:
                time.sleep(wait)
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        finally:
            self._last_at = time.monotonic()
        return response


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def entry_date(entry):
    """The entry's publication date as feedparser parsed it (a UTC
    struct_time), or None.

    CF-0708: `published_parsed` (RSS 2.0 `pubDate`, Atom `published`) first,
    then `updated_parsed`. An RSS 1.0 / RDF feed dates its items with
    `dc:date`, and feedparser 6 files that under `updated`, never under
    `published` - so Nature's feed (`nature.com/nature.rss`) came out with
    75 entries and not one date, its entries were kept past the window as
    undated, and `evidence_sources.py` refused the only source of a topic
    (`published_at` missing). On such a feed `dc:date` *is* the item's date.
    An Atom entry with no `published` has only `updated`, which is the
    closest date the feed gives."""
    return entry.get("published_parsed") or entry.get("updated_parsed") or None


def parse_rss(raw, feed_url, summary_chars):
    """-> (feed_title, [entry, ...]). Each entry carries a `_dt` datetime (or
    None) that is stripped before output.

    CF-0071: every entry also carries `feed_url` - the address it was read
    from, verbatim from `--feeds` - next to `feed`, the channel title. The
    batch's `evidence.sources[]` (see evidence_sources.py) needs both: the
    title is the outlet's masthead, the URL is the one the channel config
    lists, and neither is recoverable from the other or from the link.
    """
    parsed = feedparser.parse(raw)
    feed_title = parsed.feed.get("title") or feed_url
    entries = []
    for entry in parsed.entries:
        published = None
        stamp = entry_date(entry)
        if stamp:
            # feedparser's struct_time is already UTC; `time.mktime` would read
            # it as host-local time and shift every RSS date by the machine's
            # UTC offset (CF-0071 caught `17:24:15 +0000` landing as 14:24:15).
            # REST's `date_gmt` used to paper over it for the trades; Vulture
            # and the `?paged=N` fallback have no REST and showed the shift.
            published = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)
        entries.append({
            "feed": feed_title,
            "feed_url": feed_url,
            "title": clean_text(entry.get("title")),
            "link": entry.get("link"),
            "summary": clean_text(entry.get("summary"), summary_chars),
            "published_at": published.isoformat() if published else None,
            "_dt": published,
        })
    return feed_title, entries


def parse_rest(items, feed_title, summary_chars, feed_url=None):
    entries = []
    for item in items:
        raw_date = item.get("date_gmt")
        published = None
        if raw_date:
            try:
                published = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
            except ValueError:
                published = None
        entries.append({
            "feed": feed_title,
            "feed_url": feed_url,
            "title": clean_text((item.get("title") or {}).get("rendered")),
            "link": item.get("link"),
            "summary": clean_text((item.get("excerpt") or {}).get("rendered"), summary_chars),
            "published_at": published.isoformat() if published else None,
            "_dt": published,
        })
    return entries


# --------------------------------------------------------------------------
# per-feed collection
# --------------------------------------------------------------------------

class FeedCollector:
    def __init__(self, feed_url, cutoff, client, seen_links, *, max_requests, max_entries,
                 summary_chars, deep=True):
        self.feed_url = feed_url
        self.cutoff = cutoff
        self.client = client
        self.seen_links = seen_links          # shared across feeds
        self.seen_titles = set()              # per feed only: cross-outlet
                                              # coverage of one story is real
                                              # signal, not a duplicate
        self.by_link = {}                     # link key -> entry already kept
        self.max_requests = max_requests
        self.max_entries = max_entries
        self.summary_chars = summary_chars
        self.deep = deep

        self.entries = []
        self.feed_title = feed_url
        self.requests_made = 0
        self.strategy = "rss-single"
        self.stopped_because = None
        self.error = None
        self.reached_cutoff = False

    # -- bookkeeping -------------------------------------------------------

    def _budget_left(self):
        return self.max_requests - self.requests_made

    def _entries_full(self):
        return self.max_entries and len(self.entries) >= self.max_entries

    def _absorb(self, candidates, authoritative_dates=False):
        """Keep entries newer than the cutoff (undated entries are kept - the
        old script kept them too). Returns how many were new.

        `authoritative_dates` marks the WordPress REST transport, whose
        `date_gmt` really is GMT. The trades' RSS `pubDate` is not reliably
        so - Variety has been observed serving the same post as
        `01 Sep 2026 17:24:15 -0400` and `02 Sep 2026 00:24:15 +0000`, three
        hours apart - so when REST re-sees a post RSS already gave us, its
        timestamp replaces the feed's rather than being discarded with the
        duplicate. Otherwise `published_at` would mean something slightly
        different depending on which transport happened to reach a post first.
        """
        added = 0
        for entry in candidates:
            published = entry["_dt"]
            if published is not None and published < self.cutoff:
                self.reached_cutoff = True
                continue
            link_key = normalize_link(entry["link"])
            title_key = normalize_title(entry["title"])
            if link_key and link_key in self.seen_links:
                kept = self.by_link.get(link_key)
                if kept is not None and authoritative_dates and published is not None:
                    kept["_dt"] = published
                    kept["published_at"] = published.isoformat()
                continue
            if not link_key and title_key and title_key in self.seen_titles:
                continue
            if link_key:
                self.seen_links.add(link_key)
                self.by_link[link_key] = entry
            if title_key:
                self.seen_titles.add(title_key)
            self.entries.append(entry)
            added += 1
            if self._entries_full():
                break
        return added

    def _get(self, url, params=None):
        self.requests_made += 1
        return self.client.get(url, params=params)

    # -- transports --------------------------------------------------------

    def _drain_wp_rest(self, endpoint):
        """Returns True when the REST collection answered at least once (so it
        is the transport for this feed), False to fall back to RSS paging."""
        after = (self.cutoff - REST_AFTER_MARGIN).strftime("%Y-%m-%dT%H:%M:%S")
        page = 1
        total_pages = None
        answered = False

        while True:
            if self._budget_left() <= 0:
                if answered:
                    self.stopped_because = "max_requests"
                return answered
            try:
                response = self._get(endpoint, params={
                    "per_page": REST_PAGE_SIZE,
                    "page": page,
                    "after": after,
                    "orderby": "date",
                    "order": "desc",
                    "_fields": REST_FIELDS,
                })
            except Exception as exc:  # network-level; fall back if we never got a page
                if not answered:
                    return False
                self.stopped_because = "fetch_error"
                self.error = f"{type(exc).__name__}: {exc}"
                return True

            if response.status_code != 200:
                if not answered:
                    return False
                # page number past the end of the filtered collection
                self.stopped_because = "source_exhausted"
                return True
            try:
                body = response.json()
            except ValueError:
                if not answered:
                    return False
                self.stopped_because = "fetch_error"
                self.error = "REST response was not JSON"
                return True
            if not isinstance(body, list):
                if not answered:
                    return False
                self.stopped_because = "source_exhausted"
                return True

            answered = True
            self.strategy = "wp-rest"
            header_pages = (response.headers or {}).get("X-WP-TotalPages")
            if header_pages:
                try:
                    total_pages = int(header_pages)
                except (TypeError, ValueError):
                    pass

            if not body:
                self.stopped_because = "source_exhausted"
                return True

            self._absorb(parse_rest(body, self.feed_title, self.summary_chars,
                                    feed_url=self.feed_url),
                         authoritative_dates=True)

            if self.reached_cutoff:
                self.stopped_because = "covered"
                return True
            if self._entries_full():
                self.stopped_because = "max_entries"
                return True
            if total_pages is not None and page >= total_pages:
                self.stopped_because = "source_exhausted"
                return True
            page += 1

    def _drain_rss_pages(self):
        page = 2
        while True:
            if self._budget_left() <= 0:
                self.stopped_because = "max_requests"
                return
            try:
                response = self._get(paged_feed_url(self.feed_url, page))
            except Exception as exc:
                self.stopped_because = "fetch_error"
                self.error = f"{type(exc).__name__}: {exc}"
                return
            if response.status_code >= 400:
                self.stopped_because = "source_exhausted"
                return

            _, candidates = parse_rss(response.content, self.feed_url, self.summary_chars)
            if not candidates:
                self.stopped_because = "source_exhausted"
                return
            for entry in candidates:
                entry["feed"] = self.feed_title
            added = self._absorb(candidates)

            if self.reached_cutoff:
                self.stopped_because = "covered"
                return
            if self._entries_full():
                self.stopped_because = "max_entries"
                return
            if added == 0:
                # the source is looping/repeating rather than going deeper.
                # This is the whole cost of a feed that does not page at all:
                # FeedBurner (Vulture, CF-0060) answers ?paged=2 with the
                # front page again, and this stop turns that into one probe
                # request instead of a walk to max_requests.
                self.stopped_because = "source_exhausted"
                return
            page += 1

    # -- entry point -------------------------------------------------------

    def run(self):
        try:
            response = self._get(self.feed_url)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}")
            self.feed_title, page_one = parse_rss(response.content, self.feed_url, self.summary_chars)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.stopped_because = "fetch_error"
            return self

        self._absorb(page_one)

        if self.reached_cutoff:
            self.stopped_because = "covered"
        elif self._entries_full():
            self.stopped_because = "max_entries"
        elif not self.deep:
            self.stopped_because = "deep_disabled"
        elif not page_one:
            self.stopped_because = "source_exhausted"
        else:
            endpoint = rest_endpoint_for(self.feed_url)
            if not (endpoint and self._drain_wp_rest(endpoint)):
                if self.strategy == "rss-single":
                    self.strategy = "rss-paged"
                self._drain_rss_pages()

        if self.stopped_because is None:
            self.stopped_because = "source_exhausted"
        return self

    # -- reporting ---------------------------------------------------------

    def coverage(self, now, requested_days):
        dated = [e["_dt"] for e in self.entries if e["_dt"]]
        oldest = min(dated) if dated else None
        newest = max(dated) if dated else None
        covered_days = round((now - oldest).total_seconds() / 86400.0, 2) if oldest else 0.0
        return {
            "feed": self.feed_title,
            "feed_url": self.feed_url,
            "strategy": self.strategy,
            "requests_made": self.requests_made,
            "max_requests": self.max_requests,
            "entries": len(self.entries),
            "newest_at": newest.isoformat() if newest else None,
            "oldest_at": oldest.isoformat() if oldest else None,
            "requested_days": requested_days,
            "covered_days": covered_days,
            "window_complete": self.stopped_because == "covered",
            "stopped_because": self.stopped_because,
            "error": self.error,
        }


STOP_REASON_HINT = {
    "source_exhausted": "the source ran out of archive at this depth",
    "max_requests": "hit --max-requests-per-feed; the ceiling is an emergency stop, so a "
                    "configured feed hitting it on a normal window means the default is under "
                    "the need - re-measure and raise DEFAULT_MAX_REQUESTS_PER_FEED (CF-0059)",
    "max_entries": "hit --max-entries-per-feed; raise it to go deeper",
    "deep_disabled": "--no-deep was passed, only the feed's front page was read",
    "fetch_error": "the fetch failed",
}


def build_warnings(coverages):
    warnings = []
    for cov in coverages:
        if cov["error"]:
            warnings.append(
                f"{cov['feed']}: fetch failed ({cov['error']}) - this source contributed "
                f"{cov['entries']} entries, treat the batch as incomplete")
            continue
        if cov["window_complete"]:
            continue
        hint = STOP_REASON_HINT.get(cov["stopped_because"], cov["stopped_because"])
        warnings.append(
            f"{cov['feed']}: requested {cov['requested_days']} days, actually covered "
            f"{cov['covered_days']} ({cov['entries']} entries in {cov['requests_made']} "
            f"of max {cov['max_requests']} requests) - {hint}")
    return warnings


def build_output(collectors, now, cutoff, requested_days, max_requests_per_feed):
    """The one JSON object this script prints. Kept separate from main() so
    tests can build it from fixture-driven collectors."""
    coverages = [c.coverage(now, requested_days) for c in collectors]

    entries = [e for c in collectors for e in c.entries]
    for entry in entries:
        entry.pop("_dt", None)
    entries.sort(key=lambda e: e["published_at"] or "", reverse=True)

    return {
        "source": "rss",
        "generated_at": now.isoformat(),
        "requested_days": requested_days,
        "window_start": cutoff.isoformat(),
        "max_requests_per_feed": max_requests_per_feed,
        "total_requests": sum(c["requests_made"] for c in coverages),
        "coverage": coverages,
        "warnings": build_warnings(coverages),
        "entries": entries,
    }


# The per-feed fields the batch file must keep (CF-0059). Everything else in a
# coverage row is welcome too; these are the ones the ceiling is judged by.
DISCOVERY_TELEMETRY_FIELDS = ("feed_url", "strategy", "requests_made", "max_requests",
                              "stopped_because")


def batch_discovery_record(output):
    """What `01-trend-hunter.json` keeps of this script's run: everything but
    the entries themselves, verbatim, under `discovery.rss`.

    CF-0059: five batches were written before this and not one of them kept
    `requests_made` / `stopped_because` / `strategy`, so when CF-0045 asked
    whether the request ceiling matched the need, nobody could answer without
    re-running the fetch. Same reason CF-0038 made `signal.raw` mandatory -
    the next question of this kind gets answered by reading a batch.
    """
    return {key: value for key, value in output.items() if key != "entries"}


def channel_days(channel, root=None):
    """(days, origin, note) for a channel's discovery window: its
    `sources.rss.discovery_days`, else DEFAULT_DAYS. A value that is not a
    whole number in [MIN_DAYS, MAX_DAYS] takes the default and says why."""
    try:
        from _channel_data import channel_data, factory_root
        cid = channel_data.channel_id(channel, root=root)
        base = Path(root) if root else factory_root()
        config = json.loads((base / "channels" / f"{cid}.json").read_text())
    except Exception as exc:   # the feeds' own call refuses an unreadable channel
        return DEFAULT_DAYS, "default", f"channel config not read ({exc})"
    value = config
    for key in DAYS_KEY:
        value = value.get(key) if isinstance(value, dict) else None
    if value is None:
        return DEFAULT_DAYS, "default", None
    if isinstance(value, bool) or not isinstance(value, int) \
            or not MIN_DAYS <= value <= MAX_DAYS:
        return DEFAULT_DAYS, "default", (f"{'.'.join(DAYS_KEY)} is {value!r}, not a whole "
                                         f"number of days in [{MIN_DAYS}, {MAX_DAYS}]")
    return value, "channel", None


def channel_feeds(channel, parser=None, root=None):
    """CF-0634: the feed URLs of the channel, as the root's channel data gives
    them (`channel_data.feed_urls` - every feed, `headline_only` and
    `read_text` alike: selection reads them all). A channel without feeds, or
    whose feeds break the AI-bot rule, or that cannot be read, is a refusal
    (exit 2 through `parser.error`), never an empty fetch."""
    from _channel_data import channel_data
    try:
        urls = channel_data.feed_urls(channel, root=root)
    except (channel_data.ChannelDataError, FileNotFoundError, RuntimeError, ValueError) as exc:
        message = f"the feeds of channel {channel!r} cannot be had: {exc}"
    else:
        if urls:
            return urls
        message = (f"channel {channel!r} has no feeds (`sources.rss.feeds` is empty) - "
                   f"there is nothing to collect topics from")
    if parser is None:
        raise SystemExit(message)
    parser.error(message)


@runlog.script("trend-hunter", "fetch-rss", name="fetch_rss_news.py")
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--channel",
                       help="the batch's channel: its feeds come from the channel's data "
                            "(channel_data.feed_urls, CF-0634)")
    which.add_argument("--feeds", nargs="+",
                       help="feed URLs by hand, instead of a channel's (a replay, one feed)")
    parser.add_argument("--days", type=int, default=None,
                        help="how far back to actually reach, in days (default: the "
                             "channel's sources.rss.discovery_days, else "
                             f"{DEFAULT_DAYS}; CF-0789)")
    parser.add_argument("--max-requests-per-feed", type=int, default=DEFAULT_MAX_REQUESTS_PER_FEED,
                        help="emergency stop on HTTP requests per feed, derived from a measured "
                             "run - see the constant's comment (default %(default)s)")
    parser.add_argument("--max-entries-per-feed", type=int, default=DEFAULT_MAX_ENTRIES_PER_FEED,
                        help="cap on entries kept per feed, 0 = no cap (default %(default)s)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help="minimum seconds between requests (default %(default)s)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--summary-chars", type=int, default=DEFAULT_SUMMARY_CHARS)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--no-deep", action="store_true",
                        help="read only each feed's front page (pre-CF-0007 behaviour)")
    args = parser.parse_args(argv)
    feeds = args.feeds or channel_feeds(args.channel, parser)
    days_note = None
    if args.days is not None:
        days_from = "flag"
    elif args.channel:
        args.days, days_from, days_note = channel_days(args.channel)
    else:
        args.days, days_from = DEFAULT_DAYS, "default"

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    client = HttpClient(user_agent=args.user_agent, timeout=args.timeout, delay=args.delay)

    seen_links = set()
    collectors = []
    for feed_url in feeds:
        # CF-0107: one `child` event per feed (tool "rss") - the network time of
        # the run is here, not in the script's own code. A feed that failed
        # entirely (coverage.error) is recorded as failed, rc 1.
        with runlog.child("rss", argv=["rss", feed_url]) as event:
            collector = FeedCollector(
                feed_url, cutoff, client, seen_links,
                max_requests=args.max_requests_per_feed,
                max_entries=args.max_entries_per_feed,
                summary_chars=args.summary_chars,
                deep=not args.no_deep,
            ).run()
            event["rc"] = 1 if collector.error else 0
        collectors.append(collector)

    output = build_output(collectors, now, cutoff, args.days, args.max_requests_per_feed)
    output["requested_days_from"] = days_from
    if days_note:
        output["warnings"].append(f"discovery window: {days_note}; took {args.days} days")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    for line in output["warnings"]:
        print(f"warning: {line}", file=sys.stderr)


if __name__ == "__main__":
    main()

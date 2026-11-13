#!/usr/bin/env python3
"""The assumptions the CF-0007 fix rests on, checked against the live trades.

Everything else in this directory replays captured responses. This one asks
the real sources whether the shape of the world still matches: the trade feeds
still serve a front page measured in hours, and the WordPress REST collection
they are read through is still open. If either stops being true, the fix
quietly degrades and this is what says so.

Skips (prints and returns, does not fail the suite) when the network or a
source is unreachable - offline is not a regression.

CF-0610: the whole file is live (docs/test-hygiene.md §3) - the plain run of
tests/run_tests.py skips it with one line, `run_tests.py --live` starts it
with the network open.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import fetch_rss_news as rss  # noqa: E402

LIVE_TEST = ("asks the real trades (variety, deadline, hollywoodreporter, vulture) "
             "whether the CF-0007 assumptions still hold")

FEEDS = [
    "https://variety.com/feed/",
    "https://deadline.com/feed/",
    "https://www.hollywoodreporter.com/feed/",
]


def _client():
    return rss.HttpClient(timeout=20, delay=0.5)


def test_front_pages_are_still_hours_deep():
    """Measured 2026-09-02: 10/12/10 entries, 2.7-3.6 hours each. If a trade
    ever starts serving days on its front page, the escalation below becomes
    unnecessary for it - worth knowing either way."""
    client = _client()
    seen_any = False
    for feed in FEEDS:
        try:
            response = client.get(feed)
            if response.status_code != 200:
                print(f"  skip {feed}: HTTP {response.status_code}")
                continue
            _, entries = rss.parse_rss(response.content, feed, 500)
        except Exception as exc:
            print(f"  skip {feed}: {type(exc).__name__}")
            continue
        dates = [e["_dt"] for e in entries if e["_dt"]]
        if not dates:
            print(f"  skip {feed}: no dated entries")
            continue
        seen_any = True
        span = max(dates) - min(dates)
        print(f"  {feed}: {len(entries)} entries, {span.total_seconds() / 3600:.1f}h span")
        assert len(entries) <= 30, (
            f"{feed} now serves {len(entries)} items on its front page - the CF-0007 "
            "assumption that a trade front page is a fixed handful no longer holds")
    if not seen_any:
        print("  skip test_front_pages_are_still_hours_deep (no source reachable)")


def test_wordpress_rest_collection_is_still_open():
    """The fix reaches a 14-day window in ~25 requests because of this. If a
    trade closes /wp-json, that source silently falls back to `?paged=N` at
    10-12 posts a request and will hit the politeness cap long before 14 days
    - the run's own warnings will say so, but this is the early notice."""
    client = _client()
    reachable = 0
    after = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    for feed in FEEDS:
        endpoint = rss.rest_endpoint_for(feed)
        assert endpoint, feed
        try:
            response = client.get(endpoint, params={
                "per_page": rss.REST_PAGE_SIZE, "page": 1, "after": after,
                "orderby": "date", "order": "desc", "_fields": rss.REST_FIELDS})
        except Exception as exc:
            print(f"  skip {endpoint}: {type(exc).__name__}")
            continue
        if response.status_code != 200:
            print(f"  NOTE {endpoint}: HTTP {response.status_code} - this source is on the "
                  "slow RSS-paging path now")
            continue
        body = response.json()
        assert isinstance(body, list) and body, endpoint
        assert {"date_gmt", "link", "title", "excerpt"} <= set(body[0]), \
            f"{endpoint} changed shape: {sorted(body[0])}"
        reachable += 1
        print(f"  {endpoint}: {len(body)} posts/request, "
              f"{response.headers.get('X-WP-TotalPages')} pages for a 2-day window")
    if not reachable:
        print("  skip test_wordpress_rest_collection_is_still_open (no source reachable)")


def test_a_two_day_window_beats_the_front_page_on_a_live_source():
    """The end-to-end claim, live: asking for two days really does return more
    than the ~10 items the front page holds."""
    feed = FEEDS[0]
    now = datetime.now(timezone.utc)
    try:
        shallow = rss.FeedCollector(feed, now - timedelta(days=2), _client(), set(),
                                    max_requests=25, max_entries=0, summary_chars=500,
                                    deep=False).run()
        deep = rss.FeedCollector(feed, now - timedelta(days=2), _client(), set(),
                                 max_requests=25, max_entries=0, summary_chars=500).run()
    except Exception as exc:
        print(f"  skip test_a_two_day_window_beats_the_front_page_on_a_live_source: "
              f"{type(exc).__name__}")
        return
    if shallow.error or deep.error:
        print(f"  skip test_a_two_day_window_beats_the_front_page_on_a_live_source: "
              f"{shallow.error or deep.error}")
        return
    print(f"  {feed}: front page {len(shallow.entries)} entries -> "
          f"2-day walk {len(deep.entries)} entries in {deep.requests_made} requests "
          f"({deep.strategy})")
    assert len(deep.entries) > len(shallow.entries) * 3, (
        f"a 2-day walk returned {len(deep.entries)} against a front page of "
        f"{len(shallow.entries)} - CF-0007 is back")
    assert deep.stopped_because == "covered", deep.stopped_because


VULTURE = "https://feeds.feedburner.com/nymag/vulture"


def test_vulture_feed_is_still_a_front_page_that_does_not_page():
    """CF-0060 rests on three facts about the live Vulture feed, all measured
    2026-09-03: the FeedBurner address answers (the site-side /rss, /feed,
    /rss/index.xml are 404), it serves ~20 items, and `?paged=2` is the same
    page - which is what keeps the feed at 2 requests a run. If FeedBurner
    ever starts paging, the feed gets deeper *and* dearer, and the ceiling
    arithmetic in CF-0059 should be re-read."""
    client = _client()
    try:
        page1 = client.get(VULTURE)
        page2 = client.get(rss.paged_feed_url(VULTURE, 2))
    except Exception as exc:
        print(f"  skip test_vulture_feed_is_still_a_front_page_that_does_not_page: {type(exc).__name__}")
        return
    if page1.status_code != 200:
        print(f"  skip {VULTURE}: HTTP {page1.status_code}")
        return
    title, entries = rss.parse_rss(page1.content, VULTURE, 500)
    assert title == "Vulture", title
    assert 10 <= len(entries) <= 40, f"{VULTURE} now serves {len(entries)} items on its front page"
    assert all(rss.normalize_link(e["link"]).startswith("vulture.com/") for e in entries)
    if page2.status_code == 200:
        _, entries2 = rss.parse_rss(page2.content, VULTURE, 500)
        links1 = {rss.normalize_link(e["link"]) for e in entries}
        links2 = {rss.normalize_link(e["link"]) for e in entries2}
        assert links2 <= links1, (
            "FeedBurner started paging: page 2 has new items, so Vulture now costs more than "
            "2 requests and reaches deeper - re-measure (CF-0059/CF-0060)")
    dates = [e["_dt"] for e in entries if e["_dt"]]
    span = (max(dates) - min(dates)).total_seconds() / 3600
    print(f"  {VULTURE}: {len(entries)} entries, {span:.1f}h span, paged=2 HTTP {page2.status_code}")


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        print(f"--- {name}")
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)

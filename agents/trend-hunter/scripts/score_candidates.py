#!/usr/bin/env python3
"""Trend Hunter candidate scoring — absolute scales, no within-batch normalisation.

CF-0038 (implements the decision recorded in CF-0005). Before this, both signal
components were min-max normalised inside the batch's own candidate pool. That
had two recorded failures:

  * one viral outlier took 100.0 and flattened everyone else (2026-08-30T2329Z:
    Spire-Runner's 43.7M view sum pushed all eleven other candidates under 28, so
    exactly one topic cleared min_popularity_score=40), and
  * the lowest candidate got 0.0 on every component by construction, whatever
    its real signal (2026-08-30T1759Z: a title with 1.4M genuine views scored
    0.0 because it was last in a three-candidate pool).

Both come from the same root: a pool-relative scale. The top is always 100 and
the bottom always 0, so `min_popularity_score` filtered by rank position, not by
popularity — a batch of twelve weak topics passed it exactly like a batch of
twelve strong ones.

Here both components are absolute. A score means the same thing in every batch,
and a batch of three is measured with the same ruler as a batch of thirty.

    youtube_view_signal = clamp(0, 100, 100 * log10(V / V_FLOOR)
                                          / log10(V_CEIL / V_FLOOR))
    rss_mention_signal  = clamp(0, 100, 100 * houses / house_ceil)
    popularity_score    = w_yt * youtube_view_signal + w_rss * rss_mention_signal

CF-0060 (implements the decision recorded in CF-0046): `houses` is the number
of distinct *publishing houses* whose feeds carried the topic, not the number
of feed entries. Variety, Deadline and THR are all Penske Media (PMC); three
entries there are one editorial decision, not three. Counting entries let a
story with zero video audience clear the threshold on PMC coverage alone
(40.0 exactly: AMC Leawood Films on 2026-08-31, Entourage on 2026-09-02).
The feed -> house map lives in the channel config (`sources.rss.feeds[].house`),
so the code never has to know who owns whom; see `feed_houses()`.

The constants are calibrated on all five pre-CF-0060 batches plus the fresh
2026-09-03 pool; the working and the per-candidate measurements are in
tasks/CF-0038-absolute-log-scoring.md and tasks/CF-0060-*.md, and the same
reconstructed batches are the fixture behind tests/test_scoring_scale.py.

Usage (replay a written batch against the current scale):
    scripts/score_candidates.py ~/shorts-content-factory/pipeline/<ch>/<batch>
Count houses for a candidate's links (what SKILL.md step 2 does):
    scripts/score_candidates.py --houses <link> [<link> ...] --channel-config <ch> \
        --rss /tmp/trend-hunter-rss.json
"""
import argparse
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog, factory_root  # noqa: E402
from _channel_ids import MissingChannelError, channel_config_arg, resolve_channel  # noqa: E402

AGENT_ROOT = Path(__file__).resolve().parent.parent
# channels/ sits at the project root, shared with every other agent (README
# "Layout"). Found the way `_runlog` finds it - `FACTORY_ROOT`, else the
# nearest ancestor holding shared/runlog/runlog.py - and not by counting two
# directories up from the agent: that arithmetic is right in the normal
# checkout and wrong in a worktree (`agents/trend-hunter/.claude/worktrees/
# <x>/scripts/`), where it lands on `.claude/` and every channel config
# lookup fails (CF-0264, seen on the worktree of that task).
try:
    PROJECT_ROOT = factory_root()
except RuntimeError:                                    # pragma: no cover
    PROJECT_ROOT = AGENT_ROOT.parent.parent

# --- calibrated constants (CF-0038, 2026-09-02; CF-0060, 2026-09-03) ----------

# Below the floor a title has no video audience worth filming: 5,000 views
# summed over the whole 7-day search is not an audience. Calibrated against the
# 42 candidates in the five existing batches — it sits above everything those
# batches themselves labelled dead ("12 views across the entire search",
# "almost no video signal") and below every candidate any batch actually
# shipped as a topic on video signal (lowest: 132,228).
V_FLOOR = 5_000

# At/above the ceiling the signal saturates. 41 of those 42 candidates top out
# at 7.16M; the one above it is the documented fan-edit outlier (43.7M). A
# ceiling just above the strongest genuine signal is what makes the outlier
# clamp at 100 instead of redefining the scale for everyone else.
V_CEIL = 10_000_000

# The house ceiling - how many distinct publishing houses saturate the RSS
# signal - is the channel's (CF-0627, CF-0561): `sources.rss.house_ceil` of
# `channels/<id>.json`, beside the feeds whose `house` it counts (for
# example-film 2: PMC - Variety, Deadline, THR - and Lupa Systems - Vulture;
# two houses carrying a story is full saturation of the independent
# confirmation that is actually available). NOT auto-derived from the feeds:
# changing the house list changes what a score means and forces
# min_popularity_score to be re-derived, so it is a deliberate edit of that
# field, and tests/test_scoring_scale.py fails when the feeds and the field
# disagree. CF-0060 moved this from 3 feed *entries* to 2 *houses* - see the
# module docstring for why. Read with `house_ceil_of(config)`; there is no
# default ceiling, as there is no default channel.
HOUSE_CEIL_PATH = ("sources", "rss", "house_ceil")


def house_ceil_of(config):
    """`sources.rss.house_ceil` of a loaded channel config - a positive int,
    or ValueError naming the field (no factory default, CF-0627)."""
    node = config
    for key in HOUSE_CEIL_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, bool) or not isinstance(node, int) or node < 1:
        raise ValueError(f"the channel config has no `{'.'.join(HOUSE_CEIL_PATH)}` (a "
                         f"positive integer) - the house ceiling is the channel's (CF-0627)")
    return node

# Points added per 10x in views: 100 / log10(V_CEIL / V_FLOOR).
POINTS_PER_DECADE = 100.0 / math.log10(V_CEIL / V_FLOOR)

DEFAULT_WEIGHTS = {"youtube_view_signal": 0.6, "rss_mention_signal": 0.4}


def youtube_view_signal(views, floor=V_FLOOR, ceil=V_CEIL):
    """0-100 from a total view count, absolute log scale, clamped at both ends.

    `views` is the view sum over the gathered videos AFTER false-positive
    exclusions (see SKILL.md step 4) — an unfiltered sum is a different quantity
    and this scale is not calibrated for it.
    """
    if views is None:
        raise ValueError("views is required; a missing YouTube signal is not the same as zero")
    if views <= floor:
        return 0.0
    if views >= ceil:
        return 100.0
    return 100.0 * math.log10(views / floor) / math.log10(ceil / floor)


def rss_mention_signal(houses, ceil):
    """0-100 from the number of distinct publishing houses whose feeds carried
    the topic (CF-0060). Not entries, not feeds: a house is one editorial
    will, and PMC's three trades running the same story is one confirmation.

    Linear, not log: the range is 1..`ceil` (the channel's house ceiling,
    `house_ceil_of`), well under a decade.

    There is deliberately no floor subtraction (CF-0038). A candidate is
    discovered *by* an RSS entry, so `houses` is never 0 and a `(n-1)`-style
    scale would hand the single-house baseline a hard 0 — reproducing, as an
    absolute rule, the exact zero-floor defect the absolute scale exists to
    remove. One house is a real (if minimal) fact about the world and scores
    50.0 on a two-house ceiling.
    """
    if houses is None:
        raise ValueError("houses is required")
    if houses < 0:
        raise ValueError("houses cannot be negative")
    return max(0.0, min(100.0, 100.0 * houses / ceil))


def popularity_score(views, houses, entries=None, weights=None, floor=V_FLOOR, ceil=V_CEIL,
                     *, rss_ceil):
    """Composite 0-100. `weights` defaults to the channel config's 0.6/0.4.
    `rss_ceil` is the channel's house ceiling (`house_ceil_of(config)`).

    `houses` is what gets scored; `entries` (distinct feed entries naming the
    title) is carried in `raw` for the record only - it is what the pre-CF-0060
    scale scored, and keeping it is what lets the two be compared later.
    """
    w = weights or DEFAULT_WEIGHTS
    yt = youtube_view_signal(views, floor, ceil)
    rss = rss_mention_signal(houses, rss_ceil)
    total = w["youtube_view_signal"] * yt + w["rss_mention_signal"] * rss
    return {
        "popularity_score": round(total, 1),
        "components": {
            "youtube_view_signal": round(yt, 1),
            "rss_mention_signal": round(rss, 1),
        },
        "raw": {
            "youtube_views_after_exclusions": views,
            "distinct_rss_houses": houses,
            "distinct_rss_entries": entries,
        },
    }


def views_needed_for(score, houses, weights=None, floor=V_FLOOR, ceil=V_CEIL,
                     *, rss_ceil):
    """Inverse: view count a candidate carried by `houses` houses needs to
    reach `score`.

    This is how min_popularity_score was chosen and how it should be re-read
    whenever the constants or the feed list move — a threshold on an absolute
    scale is a claim about view counts, and this prints the claim.
    Returns None when the RSS component alone already clears the score.
    """
    w = weights or DEFAULT_WEIGHTS
    from_rss = w["rss_mention_signal"] * rss_mention_signal(houses, rss_ceil)
    needed_yt = (score - from_rss) / w["youtube_view_signal"]
    if needed_yt <= 0:
        return None
    if needed_yt >= 100:
        return float("inf")
    return floor * 10 ** (needed_yt / 100.0 * math.log10(ceil / floor))


# --- publishing houses (CF-0060) ---------------------------------------------

def channel_config_path(channel):
    # CF-0197: a former id - typed, or read out of a batch file written
    # before the rename, where the field is frozen at the old name -
    # resolves here, so every caller of load_channel_config() is covered.
    return PROJECT_ROOT / "channels" / f"{resolve_channel(channel)}.json"


def load_channel_config(channel_or_path):
    # CF-0198: a path that is not there is "no such file", never an id.
    path = channel_config_arg(channel_or_path, by_id=channel_config_path)
    return json.load(open(path))


def feed_houses(config):
    """site domain -> house id, from `sources.rss.feeds[]` in a channel config.

    Each feed is `{"url", "site", "house"}`: `url` is where the entries are
    fetched from (Vulture's is a FeedBurner address), `site` is the domain the
    entries' links live on, `house` is who owns the newsroom. Entries are
    attributed by their link's domain, not by feed title - titles drift
    ("Page 2 – Variety") and a FeedBurner feed title says nothing about
    ownership.
    """
    feeds = ((config.get("sources") or {}).get("rss") or {}).get("feeds") or []
    mapping = {}
    for feed in feeds:
        if not isinstance(feed, dict):
            raise ValueError(
                f"feed {feed!r} is a bare URL; since CF-0060 each feed is an object with "
                "url/site/house so that mentions can be counted per publishing house")
        for key in ("url", "site", "house"):
            if not feed.get(key):
                raise ValueError(f"feed {feed.get('url', feed)!r} is missing {key!r}")
        site = feed["site"].lower()
        mapping[site[4:] if site.startswith("www.") else site] = feed["house"]
    return mapping


def distinct_houses_in_config(config):
    return len(set(feed_houses(config).values()))


def house_for_link(link, site_map):
    """House id for an entry link, by domain. Raises on a domain the channel
    config does not list: that is a config that has fallen behind the feeds,
    and silently counting it as nothing would hide exactly that."""
    host = urlparse(str(link).strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for site, house in site_map.items():
        if host == site or host.endswith("." + site):
            return house
    raise ValueError(f"{link}: domain {host!r} is not a `site` of any feed in the channel config")


def houses_for_links(links, site_map):
    """Set of house ids for a candidate's RSS links."""
    return {house_for_link(link, site_map) for link in links}


def distinct_houses(links, site_map):
    return len(houses_for_links(links, site_map))


# --- houses by the feed that carried the entry (CF-0753) ----------------------
#
# The domain rule above is right for a newsroom's own feed and wrong for an
# aggregator: Hacker News (`news.ycombinator.com/rss`, house `ycombinator` in
# example-tech.json) links each entry to the story itself - research.meta.ai,
# citizenlab.ca, support.withings.com - so no `site` can ever list them. Three
# `--houses` calls died on such links in example-tech/2026-10-15T1854Z and two
# in 2026-10-16T0702Z, and with them the house count of a real candidate.
# The feed an entry was read from is known at fetch time (`fetch_rss_news.py`
# writes `feed_url` on every entry), so that is what attributes it - the same
# rule `candidate_pool.py` counts by (CF-0772). The domain is the fallback for
# a link with no fetch to look it up in (a replay of an old batch). A link
# that neither places is reported, never a crash and never a guess.

VENDOR_KIND = "vendor"   # a company's own newsroom (the root's CF-0770 marker)


def feed_table(config):
    """feed url -> {"house", "vendor"} from `sources.rss.feeds[]`. A feed of
    `kind: "vendor"` (a company's own newsroom) is not a house of the news
    (the root's `sources.rss.house_ceil_note`, `candidate_pool.py`)."""
    feeds = ((config.get("sources") or {}).get("rss") or {}).get("feeds") or []
    return {feed["url"]: {"house": feed.get("house"),
                          "vendor": str(feed.get("kind") or "").lower() == VENDOR_KIND}
            for feed in feeds if isinstance(feed, dict) and feed.get("url")}


def entry_feeds(entries):
    """link key -> feed url, from `fetch_rss_news.py` entries (`link`,
    `feed_url`). Keys are `fetch_rss_news.normalize_link`, so `www.`, scheme,
    a trailing slash and a query do not break the match."""
    from fetch_rss_news import normalize_link
    out = {}
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("link") and entry.get("feed_url"):
            out.setdefault(normalize_link(entry["link"]), entry["feed_url"])
    return out


def attribute_links(links, config, link_feeds=None):
    """-> {"houses", "vendor_feeds", "unattributed"} for a candidate's links.

    `link_feeds` maps a link to the feed URL that carried it (`entry_feeds()`
    over the fetch, or a topic's `evidence.sources[].feed`). Each link goes,
    in order: to its feed's house when the feed is known (a vendor feed's
    house lands in `vendor_feeds`, not `houses`); else to the house of the
    `site` its domain is on (a vendor feed's site likewise); else to
    `unattributed`. Counting an unattributed link as nothing is reported, so
    the caller says it - it no longer takes the candidate's other houses with
    it the way the ValueError did."""
    from fetch_rss_news import normalize_link
    by_feed = feed_table(config)
    site_map = feed_houses(config)
    vendor_sites = set()
    for feed in ((config.get("sources") or {}).get("rss") or {}).get("feeds") or []:
        if isinstance(feed, dict) and str(feed.get("kind") or "").lower() == VENDOR_KIND:
            site = str(feed.get("site") or "").lower()
            vendor_sites.add(site[4:] if site.startswith("www.") else site)
    link_feeds = {normalize_link(k): v for k, v in (link_feeds or {}).items() if k and v}
    houses, vendor, unattributed = set(), set(), []
    for link in links:
        feed = by_feed.get(link_feeds.get(normalize_link(link)) or "")
        if feed and feed.get("house"):
            (vendor if feed["vendor"] else houses).add(feed["house"])
            continue
        try:
            house = house_for_link(link, site_map)
        except ValueError:
            if link not in unattributed:
                unattributed.append(link)
            continue
        host = urlparse(str(link).strip()).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        is_vendor = any(host == s or host.endswith("." + s) for s in vendor_sites)
        (vendor if is_vendor else houses).add(house)
    return {"houses": houses, "vendor_feeds": vendor, "unattributed": unattributed}


def topic_link_feeds(topic):
    """link -> feed url out of a batch topic's `evidence.sources[]` (CF-0071:
    one record per `rss_links` entry, `feed` the URL it was read from)."""
    sources = ((topic or {}).get("evidence") or {}).get("sources") or []
    return {s["url"]: s["feed"] for s in sources
            if isinstance(s, dict) and s.get("url") and s.get("feed")}


def load_rss_entries(path):
    """The entries of a saved `fetch_rss_news.py` output (`{"entries": [...]}`)."""
    data = json.load(open(Path(path).expanduser()))
    return (data.get("entries") if isinstance(data, dict) else data) or []


# --- CLI ----------------------------------------------------------------------

def _print_scale(threshold, rss_ceil):
    print(f"V_FLOOR={V_FLOOR:,}  V_CEIL={V_CEIL:,}  house_ceil={rss_ceil}")
    print(f"{POINTS_PER_DECADE:.1f} points per 10x views")
    for n in range(1, rss_ceil + 2):
        need = views_needed_for(threshold, n, rss_ceil=rss_ceil)
        where = "passes on coverage alone" if need is None else f"needs {need:,.0f}+ views"
        print(f"  {n} house(s) -> to reach {threshold}: {where}")


def _replay(batch_dir, threshold, config_arg):
    path = Path(batch_dir).expanduser() / "01-trend-hunter.json"
    if not path.exists():
        print(f"no 01-trend-hunter.json in {batch_dir}", file=sys.stderr)
        return 1
    batch = json.load(open(path))
    # CF-0197: resolved here as well as inside channel_config_path() - at the
    # door is where the frozen `channel` field of a batch written before the
    # rename comes in, and a reader should not have to know which of the two
    # functions further down happens to look at it. A --channel-config path
    # passes through untouched: it is nobody's former id.
    # CF-0213: no channel to fall back to - a batch without a `channel` field
    # and no --channel-config is a refusal, never the first channel's scope.
    # The batch's field is resolved in the same statement it is read in (the
    # root's tests/test_former_channel_ids.py holds every such read to that).
    channel = config_arg or (resolve_channel(batch.get("channel"))
                             if batch.get("channel") else None)
    if not channel:
        print(f"{path} has no `channel` field and no --channel-config was given; "
              f"there is no default channel (CF-0213)", file=sys.stderr)
        return 2
    config = load_channel_config(resolve_channel(channel))
    feed_houses(config)   # a feed without url/site/house is a refusal (CF-0060)
    try:
        rss_ceil = house_ceil_of(config)
    except ValueError as exc:
        print(f"{channel}: {exc}", file=sys.stderr)
        return 2

    rows = []
    derived = 0
    exclusions, unrecorded = [], []
    for topic in batch.get("topics", []):
        # CF-0272. `youtube_views_after_exclusions` is a sum with something
        # taken out of it, and until this task nothing said what. A replay that
        # prints the sum and not the exclusions cannot tell a topic nothing was
        # excluded from apart from a topic whose false positives were never
        # noticed - which is how Wren Hollow carried 5.2M views of another
        # show's promos through two batches.
        recorded = (topic.get("evidence") or {}).get("excluded_evidence")
        name = topic["title_ref"]["name"]
        if recorded is None:
            unrecorded.append(name)
        elif recorded:
            exclusions.append((name, recorded))
    for topic in batch.get("topics", []):
        raw = (topic.get("signal") or {}).get("raw") or {}
        views = raw.get("youtube_views_after_exclusions")
        houses = raw.get("distinct_rss_houses")
        links = (topic.get("evidence") or {}).get("rss_links") or []
        if houses is None and links:
            # pre-CF-0060 batch: the house count is recoverable from the
            # cited links, the view count is not
            houses = len(attribute_links(links, config, topic_link_feeds(topic))["houses"])
            derived += 1
        name = topic["title_ref"]["name"]
        if views is None or houses is None:
            rows.append((name, None, None, topic["signal"].get("popularity_score"), None))
            continue
        rows.append((name, views, houses, topic["signal"].get("popularity_score"),
                     popularity_score(views, houses, raw.get("distinct_rss_entries"),
                                      rss_ceil=rss_ceil)["popularity_score"]))

    print(f"{batch.get('batch_id')}  ({len(rows)} topics)")
    missing = 0
    for name, views, houses, was, now in sorted(rows, key=lambda r: -(r[4] or -1)):
        if views is None:
            missing += 1
            print(f"  {name[:44]:44}  no signal.raw recorded — cannot rescore")
            continue
        mark = "*" if now >= threshold else " "
        print(f" {mark} {name[:44]:44} {views:>11,} h={houses}  was={was}  now={now}")
    for name, records in exclusions:
        removed = sum(int(r.get("view_count") or 0) for r in records if isinstance(r, dict))
        print(f"\n  {name[:44]}: {len(records)} upload(s) excluded from the view sum"
              f"{f' (-{removed:,} views)' if removed else ''}")
        for record in records:
            if isinstance(record, dict):
                print(f"      {record.get('reason_code') or 'excluded'} "
                      f"{record.get('video_id')} {str(record.get('title'))[:58]!r}")
    if unrecorded:
        print(f"\n{len(unrecorded)} topic(s) carry no evidence.excluded_evidence at all: "
              f"{', '.join(n[:28] for n in unrecorded)}. The scored view sum is a sum "
              f"*after* exclusions, so a topic without the field does not say whether "
              f"anything was taken out of it (CF-0272). Recompute it with "
              f"scripts/topic_relevance.py over the scoring pass's own search output.")
    if derived:
        print(f"\n{derived} topic(s) predate distinct_rss_houses; their house count was "
              f"derived from evidence.rss_links against the channel config.")
    if missing:
        print(f"\n{missing} topic(s) predate signal.raw; the batch cannot be replayed "
              f"from its own file. Raw view/mention counts are part of the schema "
              f"exactly so this stops happening.")
    return 0


def _main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch_dir", nargs="?",
                    help="pipeline batch directory holding 01-trend-hunter.json")
    ap.add_argument("--threshold", type=float, default=40.0)
    ap.add_argument("--channel-config", default=None,
                    help="channel id or path to its JSON (with a batch: the batch's "
                         "`channel` when not given; with --houses or the bare scale: required). There is "
                         "no default channel (CF-0213)")
    ap.add_argument("--houses", nargs="+", metavar="LINK",
                    help="print the distinct publishing houses behind these entry links "
                         "and exit")
    ap.add_argument("--rss", default=None, metavar="FETCH_JSON",
                    help="with --houses: the saved fetch_rss_news.py output; each link is "
                         "then the house of the feed that carried it (an aggregator such "
                         "as Hacker News links off its own site), the link's domain only "
                         "when the fetch does not hold it (CF-0753)")
    args = ap.parse_args()

    if args.houses:
        if not args.channel_config:
            print("--houses needs --channel-config <channel id or path>: the houses are "
                  "the channel's feeds; there is no default channel (CF-0213)",
                  file=sys.stderr)
            return 2
        config = load_channel_config(args.channel_config)
        # CF-0753: with the fetch's output each link is the house of the feed
        # that carried it (an aggregator's entry links off its own site); a
        # link nothing places is listed and warned about, never a crash.
        link_feeds = entry_feeds(load_rss_entries(args.rss)) if args.rss else None
        found = attribute_links(args.houses, config, link_feeds)
        houses = found["houses"]
        print(json.dumps({"distinct_rss_houses": len(houses), "houses": sorted(houses),
                          "distinct_rss_entries": len(set(args.houses)),
                          "vendor_feeds": sorted(found["vendor_feeds"]),
                          "unattributed_links": found["unattributed"]}))
        if found["unattributed"]:
            print(f"score_candidates.py: {len(found['unattributed'])} link(s) carried by no "
                  f"feed{' of the fetch' if args.rss else ' (no --rss given)'} and on no feed's "
                  f"`site` - counted as no house: {', '.join(found['unattributed'])}. "
                  f"Pass --rss <fetch_rss_news output>, or say it in the step-8 report "
                  f"(CF-0753)", file=sys.stderr)
        return 0
    if not args.batch_dir:
        if not args.channel_config:
            print("the scale needs --channel-config <channel id or path>: its house ceiling "
                  "is the channel's (sources.rss.house_ceil); there is no default channel "
                  "(CF-0213, CF-0627)", file=sys.stderr)
            return 2
        _print_scale(args.threshold, house_ceil_of(load_channel_config(args.channel_config)))
        return 0
    return _replay(args.batch_dir, args.threshold, args.channel_config)


@runlog.script("trend-hunter", "score", name="score_candidates.py")
def cli():
    """The command-line entry: _main()'s return code becomes the exit code
    inside the run event, so a non-zero result is recorded as `failed` (CF-0107)."""
    try:
        code = _main()
    except (FileNotFoundError, MissingChannelError) as exc:
        # CF-0198 / CF-0213: a channel that cannot be read is a one-line
        # refusal naming what was looked for, not a traceback.
        print(f"score_candidates.py: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    cli()

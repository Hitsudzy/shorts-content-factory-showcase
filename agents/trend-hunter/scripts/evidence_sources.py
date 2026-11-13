#!/usr/bin/env python3
"""`evidence.sources[]` for `01-trend-hunter.json` - the documentary trail
behind `evidence.rss_links` (CF-0071, Trend Hunter part).

`rss_links` is a list of URLs and nothing else. The headline, the outlet and
the date are in the feed on the way in and were lost on the way out, and
without them the Content Researcher's cheapest proof method (a rendered
quote of the headline) cannot be built. This script carries them across,
mechanically, from the RSS fetch's own output - nothing is looked up.

The contract, from inserts/proof.json `evidence_contract` (quoted, not
paraphrased):

    "url":          "str, the article URL exactly as the feed gave it - the
                     same string that appears in evidence.rss_links"
    "title":        "str, the headline as the feed carried it, untouched -
                     not rewritten, not shortened, not title-cased"
    "publication":  "str, the outlet's name as it is shown to a reader
                     ('Variety', 'Deadline', 'The Hollywood Reporter',
                     'Vulture') - the masthead a rendered_quote names, not
                     the domain and not the house"
    "published_at": "str, ISO 8601 date or datetime of publication as the
                     feed gave it (pubDate / date_gmt), 'YYYY-MM-DD' at least
                     - the date a rendered_quote shows"
    "feed":         "str, the feed URL the entry was read from - one of the
                     channel config's sources.rss.feeds[].url, so that the
                     publisher pool of headless_browser is decidable from
                     the record"

    rule: "One object per rss_link, in the same order, with the same url
           string - the two lists describe the same evidence and are
           checked against each other."
    rule: "Every field is what the feed carried. Nothing is looked up,
           inferred or rewritten at this stage: a title the feed did not
           give is a missing title, and a source with a missing title or
           date is one the writer cannot make a rendered_quote from."
    compatibility: "Additive. `evidence.rss_links` stays a list of URL
           strings exactly as today [...]; `evidence.sources` is a parallel
           list of objects, one per link, with sources[].url == rss_links
           (same strings, same order)."

CF-0533 adds a sixth key, `summary`: the entry's RSS summary (the
`fetch_rss_news.py` `summary`, ~500 characters by default), carried as the
fetch gave it, or `null` when the feed gave none. It is not part of the
proof contract above (the writer still builds a rendered_quote from the
five keys), it is the text a scene is checked against: every scene names
one `source_url` from this list and `scripts/check_scenes.py` requires each
proper name of the scene's description to be in that source's `title` or
`summary`. The hunter saw the summary when it wrote the scene, so the
batch keeps it - otherwise nobody downstream can check what the scene was
built from. A record written before CF-0533 has the five keys only and is
still accepted by `check_topic`.

CF-0638 (the user's decision of 08.10, CF-0557 Q1 variant b: the feeds are for
choosing topics, the writer gets no excerpt of them): the summary is written
only for an entry of a feed whose `use` is `read_text` - the channel's
`channel_data.support_feed_urls`, asked once a run (`text_feeds_of`); for any
other feed (`headline_only`) the record carries `summary: null`, and the
headline, outlet, date and feed stay for the proof. No list (a channel that
cannot be asked) is no feed at all: closed, not open. The Content Researcher
reads `01-trend-hunter.json` whole (its step 4 writes from "the topic's
evidence"), so a value not written here is one the writer never sees. The one
mechanical reader of the summary left - the fact-to-scene fit (the root's
`fact_scene.world_texts`, CF-0548) - was replayed without it over example-film's
batches: no topic loses its fit (`docs/news-facts-2026-10.md`). `--check` with
the channel's list names a summary of another feed.

Where each value comes from: the RSS fetch's entries (`fetch_rss_news.py`
output, `/tmp/trend-hunter-rss.json` in the skill). `title` and
`published_at` are the entry's own; `feed` is the entry's `feed_url`;
`publication` is the entry's `feed` - the feed's page-1 `<channel><title>`,
which for every configured outlet is its masthead ("Variety", "Deadline",
"The Hollywood Reporter", "Vulture"). A feed that declares no title gets
`publication: null` rather than a domain: the channel config carries no
display names, and inventing one here is exactly what the contract forbids.

A link with no entry in the fetch, or an entry without a title or date,
becomes a record with `null` in those fields and is counted in the
problems this script prints - never dropped (the lists must stay parallel)
and never filled in. The root suite's `check_evidence_sources` rejects such
a record, so the batch is not complete until the count is zero or the link
is removed from `rss_links` as uncitable.

Usage (from the agent root, after the batch file has its rss_links):
  scripts/evidence_sources.py <batch-dir|01-trend-hunter.json> \\
      --rss /tmp/trend-hunter-rss.json --write        # fill sources in place
  scripts/evidence_sources.py <batch-dir|file> --check  # validate only
  ... --channel example-film | --channel path/to/channel.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
from _channel_data import channel_data  # noqa: E402  - CF-0638
from fetch_rss_news import normalize_link  # noqa: E402
from score_candidates import load_channel_config  # noqa: E402

EVIDENCE_ITEM_KEYS = ("url", "title", "publication", "published_at", "feed")
# CF-0533: the RSS summary the scene check reads. Additive - a pre-CF-0533
# record without it is valid; a record with it carries a string or null.
SUMMARY_KEY = "summary"
SOURCE_RECORD_KEYS = EVIDENCE_ITEM_KEYS + (SUMMARY_KEY,)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# --------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------

def configured_feed_urls(config):
    """The channel's `sources.rss.feeds[].url` - the only values `feed` may take."""
    feeds = ((config.get("sources") or {}).get("rss") or {}).get("feeds") or []
    return [f["url"] if isinstance(f, dict) else f for f in feeds]


def publication_of(entry):
    """The outlet's shown name: the feed's channel title, which `parse_rss`
    puts in `entry["feed"]` (page-1 title, so `Page 2 - Variety` never gets
    here). `parse_rss` falls back to the feed URL when a feed declares no
    title; that is not a masthead, so it becomes None, not a domain."""
    name = (entry.get("feed") or "").strip()
    if not name or name == entry.get("feed_url") or name.startswith(("http://", "https://")):
        return None
    return name


def index_entries(entries):
    """link -> entry, by the exact string first and by `normalize_link` as a
    fallback (the skill copies links out of the fetch verbatim, but a trailing
    slash or `www.` must not lose the trail). First occurrence wins."""
    exact, loose = {}, {}
    for entry in entries:
        link = entry.get("link")
        if not link:
            continue
        exact.setdefault(link, entry)
        loose.setdefault(normalize_link(link), entry)

    def lookup(url):
        return exact.get(url) or loose.get(normalize_link(url))
    return lookup


def text_feeds_of(channel, root=None):
    """CF-0638: the channel's feeds whose summary may be written
    (`channel_data.support_feed_urls`, `use: read_text`); [] when the channel
    cannot be asked - closed, never open."""
    try:
        return list(channel_data.support_feed_urls(channel, root=root))
    except (channel_data.ChannelDataError, FileNotFoundError, RuntimeError,
            ValueError, KeyError, TypeError):
        return []


def source_from_entry(url, entry, text_feeds=None):
    """One `sources[]` record. `url` is the rss_links string itself, never the
    entry's link, so the two lists stay byte-identical even when the lookup
    matched loosely. Empty strings are missing values and become None.
    `summary` only of a feed in `text_feeds` (CF-0638), else None."""
    if entry is None:
        return {"url": url, "title": None, "publication": None, "published_at": None, "feed": None,
                "summary": None}
    return {
        "url": url,
        "title": (entry.get("title") or None),
        "publication": publication_of(entry),
        "published_at": (entry.get("published_at") or None),
        "feed": (entry.get("feed_url") or None),
        "summary": ((entry.get("summary") or None)
                    if entry.get("feed_url") in set(text_feeds or ()) else None),
    }


def build_sources(rss_links, entries, ctx="topic", text_feeds=None):
    """-> (sources, problems). `sources` is parallel to `rss_links`, one record
    per link in the same order. `problems` here names only the links the
    fetch never saw (their record is all-null); a record with a null title,
    date, publication or feed is `check_topic`'s to report, so that a batch
    built here and a batch checked later get the same lines."""
    lookup = index_entries(entries)
    sources, problems = [], []
    for i, url in enumerate(rss_links):
        entry = lookup(url)
        sources.append(source_from_entry(url, entry, text_feeds))
        if entry is None:
            problems.append(f"{ctx} sources[{i}]: no entry for {url} in the RSS fetch - "
                            f"not citable from this batch")
    return sources, problems


def fill_batch(batch, rss_output, feeds=None, text_feeds=None):
    """Set `evidence.sources` on every topic of a batch from the RSS fetch's
    entries. Returns the problems found (building + checking). Topics without
    `rss_links` get `sources: []`, which is parallel to an empty list.
    `text_feeds`: the feeds whose summary is written (CF-0638) - none when
    not given."""
    entries = rss_output.get("entries") or []
    problems = []
    for topic in batch.get("topics") or []:
        evidence = topic.setdefault("evidence", {})
        links = evidence.get("rss_links") or []
        ctx = f"topic {topic.get('topic_id', '?')}"
        sources, found = build_sources(links, entries, ctx, text_feeds)
        evidence["sources"] = sources
        problems.extend(found)
        problems.extend(check_topic(topic, ctx, feeds, text_feeds))
    return problems


# --------------------------------------------------------------------------
# checking - the same rules the root suite's check_evidence_sources applies,
# reported as a list rather than raised, so a batch shows all of its gaps
# --------------------------------------------------------------------------

def check_topic(topic, ctx="topic", feeds=None, text_feeds=None):
    """-> [problem, ...]; empty means every record is complete and parallel.
    A topic with no `sources` at all is not checked (the field is additive).
    With `text_feeds` (CF-0638) a summary of a feed outside it is a problem.
    """
    evidence = topic.get("evidence") or {}
    sources = evidence.get("sources")
    if sources is None:
        return []
    links = evidence.get("rss_links") or []
    if not isinstance(sources, list):
        return [f"{ctx}: evidence.sources is not a list"]
    problems = []
    if len(sources) != len(links):
        problems.append(f"{ctx}: {len(sources)} sources for {len(links)} rss_links - one object per link")
    for i, (record, link) in enumerate(zip(sources, links)):
        sctx = f"{ctx} sources[{i}]"
        if not isinstance(record, dict):
            problems.append(f"{sctx}: not an object")
            continue
        if set(record) not in (set(EVIDENCE_ITEM_KEYS), set(SOURCE_RECORD_KEYS)):
            problems.append(f"{sctx}: keys {sorted(record)} != {sorted(SOURCE_RECORD_KEYS)}")
            continue
        summary = record.get(SUMMARY_KEY)
        if summary is not None and not isinstance(summary, str):
            problems.append(f"{sctx}: summary is not a string or null")
        elif (summary is not None and text_feeds is not None
              and record.get("feed") not in set(text_feeds)):
            problems.append(f"{sctx}: summary of feed {record.get('feed')!r}, which is not a "
                            f"read_text feed of the channel - its text never reaches the "
                            f"writer (CF-0638); write null")
        if record["url"] != link:
            problems.append(f"{sctx}: url {record['url']!r} is not rss_links[{i}] {link!r}")
        for key in ("title", "publication", "feed"):
            value = record[key]
            if not (isinstance(value, str) and value.strip()):
                what = "missing" if value is None else "empty"
                problems.append(f"{sctx}: {key} is {what}"
                                + (" - unusable for a rendered_quote" if key == "title" else ""))
        date = record["published_at"]
        if date is None:
            problems.append(f"{sctx}: published_at is missing - unusable for a rendered_quote")
        elif not (isinstance(date, str) and ISO_DATE_RE.match(date)):
            problems.append(f"{sctx}: published_at {date!r} is not ISO 8601")
        feed = record["feed"]
        if isinstance(feed, str) and feed:
            if not feed.startswith("http"):
                problems.append(f"{sctx}: feed {feed!r} is not a feed URL")
            elif feeds is not None and feed not in feeds:
                problems.append(f"{sctx}: feed {feed!r} is not in the channel's sources.rss.feeds")
    return problems


def check_batch(batch, feeds=None, text_feeds=None):
    problems = []
    for topic in batch.get("topics") or []:
        problems.extend(check_topic(topic, f"topic {topic.get('topic_id', '?')}", feeds,
                                    text_feeds))
    return problems


def unusable_count(problems):
    """How many records the writer cannot make a rendered_quote from - counted
    per record, not per line, so an all-null record is one, not three."""
    return len({p.split(": ", 1)[0] for p in problems if "unusable" in p or "no entry" in p})


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _batch_path(arg):
    path = Path(arg).expanduser()
    return path / "01-trend-hunter.json" if path.is_dir() else path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    ap.add_argument("--rss", help="the RSS fetch's JSON output (fetch_rss_news.py stdout)")
    ap.add_argument("--channel", help="channel name or config path; defaults to the batch's `channel`")
    ap.add_argument("--write", action="store_true", help="write sources into the batch file in place")
    ap.add_argument("--check", action="store_true", help="validate the batch's existing sources only")
    args = ap.parse_args(argv)

    path = _batch_path(args.batch)
    if not path.exists():
        print(f"no {path}", file=sys.stderr)
        return 2
    batch = json.load(open(path))
    feeds = None
    text_feeds = []
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in its `channel` field - the file is a dated record and
    # is not rewritten - so resolve it before the config is looked up.
    channel = resolve_channel(args.channel or batch.get("channel"))
    if channel:
        try:
            feeds = configured_feed_urls(load_channel_config(channel))
        except FileNotFoundError as exc:
            print(f"warning: channel config not found ({exc}); `feed` not checked against the pool",
                  file=sys.stderr)
        # CF-0638: the summary only of the channel's read_text feeds
        text_feeds = text_feeds_of(channel)

    if args.check or not args.rss:
        if not args.check:
            print("no --rss given: checking the batch's existing sources only", file=sys.stderr)
        problems = check_batch(batch, feeds, text_feeds)
    else:
        rss_output = json.load(open(args.rss))
        problems = fill_batch(batch, rss_output, feeds, text_feeds)
        if args.write:
            with open(path, "w") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        else:
            print(json.dumps({t.get("topic_id"): t["evidence"]["sources"]
                              for t in batch.get("topics") or []}, ensure_ascii=False, indent=2))

    topics = batch.get("topics") or []
    total = sum(len((t.get("evidence") or {}).get("sources") or []) for t in topics)
    print(f"{path.name}: {len(topics)} topics, {total} sources, "
          f"{unusable_count(problems)} unusable for a proof, {len(problems)} problems", file=sys.stderr)
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    return 1 if problems else 0


@runlog.script("trend-hunter", "evidence-sources", name="evidence_sources.py")
def cli(argv=None):
    """The command-line entry: main()'s return code becomes the exit code
    *inside* the run event, so a non-zero result is recorded as `failed`
    (CF-0107). Tests call main() directly and leave no event."""
    sys.exit(main(argv))


if __name__ == "__main__":
    cli()

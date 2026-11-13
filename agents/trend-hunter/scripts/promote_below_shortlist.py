#!/usr/bin/env python3
"""CF-0882: Trend Hunter's half of the refill from below the shortlist - step
5b for topics the root's refill round (`shared/below_shortlist.py`, seam
`footage`) picked from `below_shortlist`, as many as `--max-searches` pays for.

Why. Over 20-27.10 the reserve (`02 -> reserve[]`, shortlist 8 - cut 5 = 3
topics) burned on the same refusals; 14 refused topics went unreplaced and 6
slots stayed empty (`reserve_exhausted`) while 36 viable topics sat below the
shortlist untouched. The root's round now takes the next of them when a
reserve round of the Footage Indexer runs out; compliance judges them on the
fly (`agents/compliance-checker/scripts/judge_below_shortlist.py judge`), this
script walks the eligible ones through step 5b, and compliance admits the ones
that got a pool (`... admit`) into `02 -> reserve[]`.

Per topic, in the order given (CF-0313's substitution, the same code):

1. the `below_shortlist` row of `01 -> skipped_topics[]` and the topic it
   keeps (`footage_candidates.restore_reserve_topic`);
2. the official channels' feeds first (`fetch_channel_feeds.topic_feed`,
   CF-0361/CF-0661/CF-0662 - no `search.list`, a topic the feeds cover costs
   0 searches);
3. only when the feeds give fewer than the floor (`fallback_search`), the
   channel's facet run (`fetch_youtube_signal.run_signal`, the facets of
   `scope.footage_facets`, the channel's search cache CF-0824) - every call
   inside the run-log wrapper (`youtube-api search`), so the day's spend that
   the root reads (`shared/quota_day.py`) stays true. Never more than
   `--max-searches` calls in all: a topic whose run the rest does not pay for
   is `quota`, with no search at all (half a facet run is no pool);
4. the same sieves and floor as every topic of 5b
   (`footage_candidates._walk_substitute`: CF-0272/0297/0302/0309, the
   own-graphics footing CF-0689).

A topic with a pool moves into `01 -> topics[]` (its record with
`evidence.footage_candidates`, `rank` kept, `"refill": {"task": "CF-0882"}`)
and its `below_shortlist` row leaves `skipped_topics[]`; a refused one keeps
its row, with `refill_outcome: refused` and `refill_reason`. Every topic gets
one row in `01 -> below_shortlist_refill[]` (`{topic_id, outcome, searches,
at, reason}`), and what was spent goes into `01 -> search_quota` (the topic's
key for the facet run, `<topic>:feeds` for the feed read).

A second call for the same topic searches nothing: a promoted topic answers
`candidates`, a refused one `refused`, with 0 searches.

Result (`--result`): `{"topics": [{"topic_id", "outcome":
"candidates"|"refused"|"quota"|"error", "searches", "reason"}]}`; exit 0 when
the result was written.

Usage:
  promote_below_shortlist.py <batch-dir> --topics id1,id2 --max-searches K \\
      --result <path>
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from _apikey import youtube_api_key  # noqa: E402
from _runlog import runlog  # noqa: E402
import footage_candidates as fc  # noqa: E402
import search_cache  # noqa: E402
import search_quota  # noqa: E402

TASK = "CF-0882"
TREND_FILE = "01-trend-hunter.json"
BELOW_CODE = fc.RESERVE_CODE                 # "below_shortlist"
LOG_KEY = "below_shortlist_refill"           # 01 -> below_shortlist_refill[]
REFILL_MARK = "refill"                       # shared/below_shortlist.py REFILL_MARK
FEEDS_KEY_SUFFIX = ":feeds"                  # the feed read's key in search_quota

CANDIDATES = "candidates"                    # shared/below_shortlist.py WITH_POOL
REFUSED = "refused"
QUOTA = "quota"
ERROR = "error"

DEFAULT_DAYS = 7                             # fetch_youtube_signal.py --days default
MAX_RESULTS = 15                             # fetch_youtube_signal.py --max-results default


def _now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _ids(raw):
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def below_row(t01, tid):
    for row in t01.get("skipped_topics") or []:
        if isinstance(row, dict) and row.get("reason_code") == BELOW_CODE \
                and row.get("topic_id") == tid:
            return row
    return None


def in_topics(t01, tid):
    return next((t for t in t01.get("topics") or []
                 if isinstance(t, dict) and t.get("topic_id") == tid), None)


def channel_days(channel):
    """`scope.popularity_window_days` of the channel - the window step 5b's
    facet runs search (SKILL step 5b), else the fetcher's default."""
    scope = (search_cache.load_config(channel) or {}).get("scope") or {}
    days = scope.get("popularity_window_days")
    return days if isinstance(days, int) and not isinstance(days, bool) and days > 0 \
        else DEFAULT_DAYS


# --------------------------------------------------------------------------
# the two reads of step 5b - injectable, so a test never reaches the network
# --------------------------------------------------------------------------

class Feeds:
    """The official channels' feeds of the batch's channel, one reader for
    the whole call (`fetch_channel_feeds.topic_feed`)."""

    def __init__(self, channel, api_key=None):
        import fetch_channel_feeds as fcf  # noqa: PLC0415 - imports requests
        import footage_origin  # noqa: PLC0415
        self.fcf = fcf
        self.channel = channel
        self.pages = fcf.DEFAULT_PAGES if api_key else 0
        self.reader = fcf.Reader(api_key=api_key)
        self.config = footage_origin.load_config(channel)
        self.limits = fc.channel_ceiling(channel)

    def __call__(self, topic):
        ref = dict(topic.get("title_ref") or {})
        houses = self.fcf.topic_houses(topic, self.channel)
        if houses:
            ref["houses"] = houses
        return self.fcf.topic_feed(ref, self.reader, pages=self.pages, config=self.config,
                                   limits=self.limits)

    def close(self):
        try:
            self.fcf.log_status(self.reader)
        except Exception:  # noqa: BLE001 - accounting never breaks the refill
            pass


def facet_search(channel, api_key):
    """-> `search(name, max_searches)`: the channel's facet run
    (`fetch_youtube_signal.run_signal --facets`), capped."""
    import fetch_youtube_signal as yt  # noqa: PLC0415
    days = channel_days(channel)

    def search(name, max_searches):
        if not api_key:
            raise RuntimeError("no YOUTUBE_API_KEY (environment or this repo's .env)")
        return yt.run_signal(name, api_key, days=days, max_results=MAX_RESULTS,
                             facets_arg=yt.CHANNEL_FACETS, channel=channel,
                             max_searches=max_searches)
    return search


# --------------------------------------------------------------------------
# one topic
# --------------------------------------------------------------------------

def _log(t01, tid, outcome, searches, reason, at):
    rows = t01.setdefault(LOG_KEY, [])
    row = {"topic_id": tid, "outcome": outcome, "searches": searches, "at": at,
           "reason": reason, "task": TASK}
    for i, have in enumerate(rows):
        if isinstance(have, dict) and have.get("topic_id") == tid:
            row["searches"] = int(have.get("searches") or 0) + searches
            rows[i] = row
            return row
    rows.append(row)
    return row


def walk(t01, tid, budget, feeds, search, batch_dir=None, limits=None):
    """Step 5b over one topic from below the shortlist. -> (outcome, searches
    made, reason, spend unknown). `budget` is the `search.list` calls still
    allowed; a facet run that broke half-way made calls nobody counted, so
    the caller stops searching after it (`spend unknown`)."""
    row = below_row(t01, tid)
    if row is None:
        have = in_topics(t01, tid)
        if have is not None and have.get(REFILL_MARK):
            return CANDIDATES, 0, "already moved into topics[] from below the shortlist", False
        if have is not None:
            return ERROR, 0, "in topics[] already - not a topic below the shortlist", False
        return (ERROR, 0, f"no {BELOW_CODE} row for it in {TREND_FILE} -> skipped_topics[]",
                False)
    if row.get("refill_outcome") == REFUSED:
        return (REFUSED, 0, row.get("refill_reason") or "refused by an earlier refill walk",
                False)
    topic, restored = fc.restore_reserve_topic(row)
    if topic is None:
        return ERROR, 0, ("the row keeps no topic to put back (no `topic`, no title, "
                          "no probe)"), False
    name = (topic.get("title_ref") or {}).get("name") or row.get("title") or tid
    notes = []
    quota = search_quota.quota_block(t01)

    def settle():
        search_quota.settle(quota, batch_dir=batch_dir)
        t01[search_quota.QUOTA_KEY] = quota

    feed = None
    if feeds is not None:
        try:
            feed = feeds(topic)
        except Exception as exc:  # noqa: BLE001 - a dead feed read falls to the search
            notes.append(f"feeds unread ({type(exc).__name__}: {exc})")
    if feed:
        # the feeds' 1-unit calls, on the feeds' own article (CF-0361/CF-0368)
        search_quota.count_searches(quota, {tid + FEEDS_KEY_SUFFIX: feed},
                                    article=search_quota.ARTICLE_FEEDS)
    signal = feed
    searches = 0
    if feed is None or feed.get("fallback_search"):
        if search is None:
            settle()
            return ERROR, 0, "the feeds were not enough and no facet search is wired", False
        try:
            found = search(name, budget)
        except Exception as exc:  # noqa: BLE001
            settle()
            return ERROR, 0, f"facet run failed: {type(exc).__name__}: {exc}", True
        over = found.get("over_budget")
        if over:
            settle()
            return QUOTA, 0, (f"the facet run is {over.get('calls_needed')} search.list "
                              f"call(s), {over.get('max_searches')} left of what the day "
                              f"pays for this round (--max-searches)"
                              + (f"; the feeds gave {feed.get('candidates_found')} "
                                 f"candidate(s)" if feed else "")), False
        searches = search_quota.searches_of(found)
        signal = fc.merge_signals(feed, found) if feed else found
        # step 5b's facet run, on the footage article (CF-0313/CF-0368)
        search_quota.count_searches(quota, {tid: found}, article=search_quota.ARTICLE_FOOTAGE)
    settle()

    # The sieves and the floor on a scratch batch: the refusal there is
    # `no_source` in its own skipped_topics, and this batch's row must stay a
    # `below_shortlist` row (refused -> the row stays, marked).
    scratch = {k: v for k, v in t01.items() if k not in ("topics", "skipped_topics")}
    scratch["topics"], scratch["skipped_topics"] = [topic], []
    outcome, walked = fc._walk_substitute(scratch, topic, signal, fc.FOOTAGE_CANDIDATE_FLOOR,
                                          limits)
    notes.extend(walked)
    evidence = topic.setdefault("evidence", {})
    if (signal or {}).get("feed_read"):
        evidence["footage_feed_read"] = signal["feed_read"]      # CF-0661, as fill_batch
    n = len(evidence.get("youtube_video_ids") or [])
    if outcome != fc.OUTCOME_CANDIDATES:
        refusal = next((r for r in scratch["skipped_topics"] if r.get("topic_id") == tid), {})
        reason = refusal.get("reason") or "; ".join(notes) or "step 5b refused it"
        row["refill_outcome"] = REFUSED
        row["refill_reason"] = reason
        row["refill_task"] = TASK
        return REFUSED, searches, reason, False
    topic[REFILL_MARK] = {"task": TASK, "restored": restored}
    if row.get("rank") is not None:
        topic["rank"] = row.get("rank")
    fc._promote(t01, row, topic)
    return CANDIDATES, searches, (f"{n} footage candidate(s), {searches} search(es)"
                                  + (f"; {'; '.join(notes)}" if notes else "")), False


def promote(batch_dir, ids, max_searches, feeds=None, search=None):
    """Walk `ids` in order; write 01 once. -> the result rows."""
    batch_dir = Path(batch_dir)
    path = batch_dir / TREND_FILE
    t01 = _read(path)
    if not isinstance(t01, dict):
        return [{"topic_id": t, "outcome": ERROR, "searches": 0,
                 "reason": f"no readable {TREND_FILE}"} for t in ids]
    budget = max(0, int(max_searches))
    limits = fc.channel_ceiling(fc._batch_channel(t01))
    rows, changed = [], False
    at = _now_z()
    for tid in ids:
        outcome, n, reason, unknown = walk(t01, tid, budget, feeds, search,
                                           batch_dir=batch_dir, limits=limits)
        budget = 0 if unknown else max(0, budget - n)
        repeat = n == 0 and outcome in (CANDIDATES, REFUSED) and any(
            isinstance(r, dict) and r.get("topic_id") == tid and r.get("outcome") == outcome
            for r in t01.get(LOG_KEY) or [])
        if not repeat:
            _log(t01, tid, outcome, n, reason, at)
            changed = True
        rows.append({"topic_id": tid, "outcome": outcome, "searches": n, "reason": reason})
    if changed:
        _write_json(path, t01)
    return rows


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------

def parse(argv=None):
    ap = argparse.ArgumentParser(
        prog="promote_below_shortlist.py",
        description="CF-0882: step 5b for topics from below the shortlist "
                    "(shared/below_shortlist.py, seam `footage`).")
    ap.add_argument("batch", help="the batch directory (holds 01-trend-hunter.json)")
    ap.add_argument("--topics", required=True, help="topic ids, comma-separated, in order")
    ap.add_argument("--max-searches", type=int, required=True,
                    help="search.list calls this call may make in all (the day's quota)")
    ap.add_argument("--result", required=True, help="where the result JSON goes")
    return ap.parse_args(argv)


@runlog.script("trend-hunter", "below-shortlist-refill", name="promote_below_shortlist.py")
def main(argv=None, feeds=None, search=None):
    ns = parse(argv)
    batch_dir = Path(ns.batch)
    ids = _ids(ns.topics)
    t01 = _read(batch_dir / TREND_FILE)
    channel = fc._batch_channel(t01) if isinstance(t01, dict) else None
    owned = None
    if feeds is None and search is None and isinstance(t01, dict):
        key = youtube_api_key()
        try:
            owned = feeds = Feeds(channel, key)
        except Exception as exc:  # noqa: BLE001 - no feeds: the search alone
            print(f"feeds unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        search = facet_search(channel, key)
    try:
        rows = promote(batch_dir, ids, ns.max_searches, feeds=feeds, search=search)
    finally:
        if owned is not None:
            owned.close()
    _write_json(ns.result, {"task": TASK, "batch": str(batch_dir), "at": _now_z(),
                            "max_searches": ns.max_searches,
                            "searches": sum(r["searches"] for r in rows), "topics": rows})
    for r in rows:
        print(f"{r['topic_id']}: {r['outcome']} ({r['searches']} search(es)) - {r['reason']}")
    return 0


def cli(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if not any(a in ("-h", "--help") for a in raw):
        first = next((a for a in raw if not a.startswith("-")), None)
        if first and Path(first).is_dir():
            # the run log of the batch the round is for (the plan sets it too)
            os.environ.setdefault("RUNLOG_BATCH", str(Path(first).resolve()))
    return main(raw)


if __name__ == "__main__":
    sys.exit(cli())

#!/usr/bin/env python3
"""How many YouTube `search.list` calls this batch has spent, and what is left
of the day (CF-0313, on the incident CF-0288 recorded).

Why a counter exists at all. `search.list` is the one call of this stage that
is rationed twice over: 100 units of the project's 10,000/day *and* a hard
`defaultSearchListPerDayPerProject` of **100 calls a day**, reset at Pacific
midnight (07:00 UTC in summer). The second limit is the binding one: a batch
is ~20 scoring searches plus 6 per shortlisted title (CF-0129 FOOTAGE_FACETS,
one bare query and five facets), so ~68 of the 100, and on 2026-09-19T0116Z
the second batch of one Pacific day hit 429 on the fourth title and five of
eight shortlisted topics came out of step 5b with no candidates at all.

Nothing in this stage counted the calls before CF-0313 - the 429 was the first
news of the limit - and the substitution CF-0313 adds is the first thing here
that *chooses* to spend quota: a topic refused at step 5b for want of
candidates hands its slot to the next reserve topic, and walking that topic
through step 5b is another facet run. So the number of substitutions a batch
may make is not a literal: it is what is left of the day divided by the price
of one, and both numbers are written into the artifact
(`01-trend-hunter.json` -> `search_quota`) rather than reasoned about in a
head.

Two independent counts, and the larger wins:

  * **from the searches handed in.** Every `fetch_youtube_signal.py` output
    says what it cost - `searches` since CF-0313, and before that one plus
    `facets_used`, which is the same number for every search this stage has
    ever run. This count is per topic, so a second pass over the same batch
    re-counts nothing: the topic is already in the ledger.
  * **from the run log.** `fetch_youtube_signal.search_ids` wraps every call
    in `runlog.child("youtube-api", argv=["youtube-api", "search", q])`, so a
    batch directory that has a `RUN_EVENTS.jsonl` already holds the truth for
    everything run under it - the scoring pass included, which no signal file
    handed to step 5b would ever show.

Whatever the day spent *outside* this batch's accounting - an earlier batch of
the same Pacific day, a scoring pass whose events went elsewhere - is
`--searches-spent` on the caller's command line and is added to both.
Cross-batch bookkeeping is CF-0288's, not this module's: this one refuses to
guess, it only refuses to lose what it can see.

CF-0368: the same spend, by article
-----------------------------------
One total cannot answer the question the user actually has - *would a cache or
a per-article division buy anything* - so the count is kept four ways:

    scoring          one bare `search.list` per candidate topic, plus its
                     `videos.list`; the pass the CF-0038 scale is calibrated on
    footage_feeds    CF-0361/CF-0369, footage off the official channels' feeds:
                     `playlistItems`/`videos`/`channels` at 1 unit a call, and
                     the free RSS reads. **A different currency**: no
                     `search.list` call, so no claim at all on the day's 100
    footage_search   step 5b's facet run, 6 calls a topic (CF-0129)
    supplement       CF-0343, the searches of a thin pool's entities; the feed
                     reads it makes first are the feeds' article

Every row is the larger of what the signals cost and what the run log recorded
for it - CF-0313's rule applied a row at a time - and `spent_searches` is the
rows plus `searches_before_stage`, so the split and the total cannot disagree.
An article is read off a call three ways, in this order: the `article` the
caller put on the event (`ARTICLE_ENV`, the only thing that can tell the
supplement's subprocess search from step 5b's - both are
`fetch_youtube_signal.py --facets`), the step it ran under, and its parent
script's `--facets`. A call the log cannot place is charged to
`UNPLACED_ARTICLE` and counted in `unplaced_search_calls`: an unplaceable call
must make the measurement look worse, never cheaper.

This is a **measurement, not a budget**. Nothing here caps an article and
nothing refuses a call because an article ran dry - the cache and the division
of the day between articles wait until this measurement shows a shortage
(decision 2026-09-23). The only refusal in this file's orbit is CF-0313's, on
the day's total, and CF-0368 adds none.

CF-0824: the cache the measurement asked for
--------------------------------------------
The measurement did show the need (`docs/analysis/funnel-2026-10-21.md` of
the root: 13-14 % of a channel's `search.list` calls over 04-20.10 repeated
a query of an earlier batch), and `fetch_youtube_signal.py` now answers such
a query from the channel's cache (`search_cache.py`; 24 h for the scoring
pass, 72 h for the footage passes). A cached answer is **not a call**: the
fetcher writes no `youtube-api search` event for it (a `youtube-cache search`
one instead) and leaves it out of its output's `searches`. This module keeps
it apart, as `cached_search_calls` on each article's row and on the block -
never in `search_calls` or `spent_searches`, so the root's
`shared/quota_day.py` (which sums `spent_searches` and the `youtube-api
search` events) sees only what was really spent.

`summary_line` is the line `RUN_SUMMARY.md` carries. It is rendered here and
shipped to the root inside a `quota` run-log event (`record_event`), because
`shared/runlog/summary.py` reads `RUN_EVENTS.jsonl` and nothing else, and
because the root has no business knowing what a facet run is.
"""
import json
from pathlib import Path

# `defaultSearchListPerDayPerProject`: the API's own per-day cap on
# `search.list` calls, measured the hard way on 2026-09-19 (CF-0288).
SEARCH_CALLS_PER_DAY = 100
# What one of those calls costs of the 10,000-unit daily quota. The two limits
# are counted in different currencies and only one of them binds; the units
# are written down beside the calls because the budget in SKILL.md step 5b is
# stated in units.
UNITS_PER_SEARCH = 100
# The Pacific midnight the counters reset at, in UTC. Summer time; it is a
# string in the record rather than a computation, because this module never
# decides *when* - it counts what it was handed.
RESET_AT = "07:00Z (Pacific midnight, summer)"

# One footage pass over one topic: the bare query plus
# `fetch_youtube_signal.FOOTAGE_FACETS`. Spelled as a number here and checked
# against that tuple by the tests, so that adding a facet moves the price.
FACET_RUN_SEARCHES = 6

QUOTA_KEY = "search_quota"
# CF-0823: the scoring searches the fact check before scoring did not spend -
# copied off the batch's `prescreen.totals` (fact_probe_topics.py
# --before-scoring, refill_topics.py) by `quota_block` and shown on the
# scoring article's row as `saved_search_calls`. Not part of any spend.
SAVED_KEY = "scoring_saved"
PRESCREEN_KEY = "prescreen"
EVENTS_FILE = "RUN_EVENTS.jsonl"
SEARCH_TOOL = "youtube-api"
SEARCH_VERB = "search"
# The free half of a feed read: `youtube-rss` children cost no unit at all
# (`https://www.youtube.com/feeds/videos.xml` is not the Data API). Counted
# anyway, because a feeds row that reads 40 channels for 4 units is the whole
# point of the CF-0368 measurement.
FEED_TOOL = "youtube-rss"
# CF-0824: a `search.list` call the channel's cache answered
# (`search_cache.CACHE_TOOL`, spelled here so this module keeps importing
# nothing of the stage's). Never a spend: counted on its own row,
# `cached_search_calls`, beside the calls. The root's `shared/quota_day.py`
# counts `youtube-api` `search` children only, so it never sees these.
CACHE_TOOL = "youtube-cache"
CACHED_FIELD = "cached_searches"     # what a fetch output says it got from the cache
CACHED_LEDGER = "cached_by_key"
# What one non-`search.list` Data API call costs: `playlistItems.list`,
# `videos.list` and `channels.list` are 1 unit each, whatever parts are asked
# for (CF-0302 measured that on `videos.list`).
UNITS_PER_CALL = 1

# --------------------------------------------------------------------------
# CF-0368: the four articles of the YouTube spend
# --------------------------------------------------------------------------
# What the stage spends the project's day on, told apart rather than summed.
# The split is a *measurement*, not a budget: nothing here caps an article or
# refuses a call because an article ran dry (decision 2026-09-23 - no cache
# and no per-article division until a measurement shows one is needed).
ARTICLE_SCORING = "scoring"            # the bare title search of the scoring pass
ARTICLE_FEEDS = "footage_feeds"        # CF-0361/CF-0369: footage off the official feeds
ARTICLE_FOOTAGE = "footage_search"     # CF-0129 step 5b: the facet run of a topic
ARTICLE_SUPPLEMENT = "supplement"      # CF-0343: the thin pool's supplement
ARTICLES = (ARTICLE_SCORING, ARTICLE_FEEDS, ARTICLE_FOOTAGE, ARTICLE_SUPPLEMENT)

# Why the feeds are an article of their own and not a line of the footage one:
# they are paid for in a different currency. `playlistItems`/`videos`/
# `channels` cost 1 unit of the 10,000-a-day and are **not** `search.list`, so
# they do not touch the `defaultSearchListPerDayPerProject` cap of 100 calls
# that is the binding limit of this stage (CF-0288). A feed read of 40
# channels costs what two thirds of one search call costs.
ARTICLE_WHAT = {
    ARTICLE_SCORING: "the scoring pass - one bare `search.list` per candidate topic, "
                     "plus its `videos.list` for the view counts",
    ARTICLE_FEEDS: "footage off the official channels' feeds (CF-0361, CF-0369) - "
                   "`playlistItems`/`videos`/`channels`, 1 unit each, and the free RSS "
                   "reads; no `search.list` call and so no claim on the day's 100",
    ARTICLE_FOOTAGE: "the footage pass of step 5b (CF-0129) - one facet run per topic",
    ARTICLE_SUPPLEMENT: "the supplement of a thin pool (CF-0343) - the searches of its "
                        "entities, and the feed reads it makes are the feeds' article",
}
ARTICLE_LABEL = {ARTICLE_SCORING: "scoring", ARTICLE_FEEDS: "footage feeds",
                 ARTICLE_FOOTAGE: "footage search", ARTICLE_SUPPLEMENT: "supplement"}
# The currency each article is charged in. Only the first spends `search.list`.
SEARCH_ARTICLES = (ARTICLE_SCORING, ARTICLE_FOOTAGE, ARTICLE_SUPPLEMENT)

# A `search.list` call the run log holds but cannot place - no script event
# above it, or one whose arguments say nothing (every row of a hand-written
# test log). It is charged to the article that spends the most rather than
# dropped, and the count of such calls is written down beside it: an
# unplaceable call must make the measurement look *worse*, never cheaper.
UNPLACED_ARTICLE = ARTICLE_FOOTAGE

# How an out-of-process call says which article it belongs to. The supplement
# runs `fetch_youtube_signal.py` as a subprocess (`footage_supplement.command`)
# and step 5b runs the same script by hand, so the run log cannot tell them
# apart by what it sees: the caller puts the article in the environment and the
# fetcher copies it onto its `youtube-api` events (CF-0368).
ARTICLE_ENV = "TREND_HUNTER_QUOTA_ARTICLE"
ARTICLE_PARAM = "article"

# The run-log steps whose Data API calls are a feed read whatever endpoint they
# hit: `fetch_channel_feeds.py` itself, and the supplement's in-process reader.
FEED_STEPS = ("youtube-feeds",)
SIGNAL_STEP = "youtube-signal"
FACETS_FLAG = "--facets"
# What a feed signal calls itself (`fetch_channel_feeds.SOURCE`), spelled here
# so this module keeps importing nothing of the stage's.
FEED_SOURCE = "youtube-feeds"

# The kind of run-log event this module writes for the root's RUN_SUMMARY line
# (CF-0368). `shared/runlog/summary.py` reads RUN_EVENTS.jsonl and nothing
# else, so the split has to be in the events to reach the summary - and the
# event carries the rendered line as well as the rows, so the root prints it
# without knowing this stage's vocabulary.
EVENT_KIND = "quota"
STAGE = "trend-hunter"
ARTICLE_TASK = "CF-0368"

ARTICLE_NOTE = (
    "CF-0368. The same spend, told apart by what it was spent on: `scoring` / "
    "`footage_feeds` / `footage_search` / `supplement`. A measurement, not a "
    "budget - no article is capped and no call is refused because an article "
    "ran dry (2026-09-23). `search_calls` is the only currency the day's "
    + str(SEARCH_CALLS_PER_DAY) + "-call cap counts; `api_units` is the "
    "1-unit-a-call currency of `playlistItems`/`videos`/`channels`, which the "
    "feeds are paid in and which that cap does not touch. Each row is the "
    "larger of what the signals cost and what the run log recorded for it, "
    "the same rule the totals have followed since CF-0313.")

NOTE = (
    "CF-0313. The `search.list` calls this batch is known to have spent, and "
    "what is left of the day's " + str(SEARCH_CALLS_PER_DAY) + " (CF-0288). "
    "`substitutions_affordable` is how many more topics step 5b may pull out "
    "of the reserve to refill a slot it emptied: the remainder divided by "
    "`substitution_price_searches`, never a literal. `searches_by_topic` is "
    "per topic and so survives a second pass over the same batch; "
    "`searches_before_stage` is what the same quota day spent outside this "
    "batch's own accounting and is the operator's word (`--searches-spent`), "
    "because no cross-batch ledger exists yet - that is CF-0288.")


def searches_of(signal):
    """What one `fetch_youtube_signal.py` output cost in `search.list` calls.

    `searches` is written by the fetcher since CF-0313. An older file (every
    footage search on disk today) says only which facets it used, and the call
    count is one bare query plus one per facet - which is what the fetcher has
    always done.
    """
    if not isinstance(signal, dict):
        return 0
    count = signal.get("searches")
    # CF-0361: 0 is a real answer - a feed signal (`fetch_channel_feeds.py`)
    # spent no search - and only a missing or malformed count falls back.
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        # CF-0426: a `--no-bare` run searched the facets only.
        count = (0 if signal.get("bare") is False else 1) + len(signal.get("facets_used") or [])
    return count


def cached_of(signal):
    """How many of one fetch output's searches the cache answered (CF-0824;
    0 for every output written before it)."""
    if not isinstance(signal, dict):
        return 0
    n = signal.get(CACHED_FIELD)
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0


def _events_path(batch_dir):
    if not batch_dir:
        return None
    path = Path(batch_dir)
    path = path if path.name == EVENTS_FILE else path / EVENTS_FILE
    return path if path.is_file() else None


def _empty_rows():
    return {a: {"search_calls": 0, "api_calls": 0, "api_units": 0, "free_calls": 0,
                "cached_search_calls": 0, "steps": {}} for a in ARTICLES}


def article_of_event(row, scripts):
    """Which article one `youtube-api` / `youtube-rss` child event belongs to,
    or None when the log cannot place it.

    Three things are asked, in the order they can be trusted:

      * the call's own `params.article` - the caller said so out loud
        (`ARTICLE_ENV`), which is the only way to tell the supplement's
        subprocess search from step 5b's, both being `fetch_youtube_signal.py`
        with facets;
      * its step - `youtube-feeds` is a feed read whatever endpoint it hit,
        and so is any Data API call that is not a `search.list` under the
        stage's own step (the supplement reads feeds in process);
      * its parent script's arguments - `--facets` is the footage pass and a
        bare query is the scoring pass, which is the difference
        `fetch_youtube_signal.py` has documented since CF-0129.
    """
    params = row.get("params")
    if isinstance(params, dict):
        said = params.get(ARTICLE_PARAM)
        if said in ARTICLES:
            return said
    step = row.get("step")
    if step in FEED_STEPS:
        return ARTICLE_FEEDS
    argv = row.get("argv")
    verb = argv[1] if isinstance(argv, list) and len(argv) > 1 else None
    if row.get("tool") == FEED_TOOL:
        return ARTICLE_FEEDS
    if verb and verb != SEARCH_VERB and step and step != SIGNAL_STEP:
        # A 1-unit call outside the fetcher: the supplement's own reader, which
        # runs inside `footage_candidates.py` and reads nothing but feeds.
        return ARTICLE_FEEDS
    parent = scripts.get(row.get("parent")) or {}
    if parent.get("step") == SIGNAL_STEP or step == SIGNAL_STEP:
        params = parent.get("params")
        if isinstance(params, dict):
            return ARTICLE_FOOTAGE if params.get(FACETS_FLAG) else ARTICLE_SCORING
    return None


def spend_from_events(batch_dir):
    """What this batch's run log says was spent, split by article, or None when
    there is no run log to read (a test, a batch run with no `RUNLOG_BATCH`, a
    directory that is not a batch).

    None is not zero: "nobody wrote a run log" and "the run log says no search
    was made" are the two states the caller has to tell apart, exactly as
    `skipped_topics` absent differs from `skipped_topics: []` in the funnel.

    -> `{"by_article": {article: row}, "search_calls": n, "api_units": u,
    "unplaced_search_calls": k}`. A call the log cannot place is charged to
    `UNPLACED_ARTICLE` and counted again in `unplaced_search_calls`, so the
    reader can see how much of the split is inference.
    """
    path = _events_path(batch_dir)
    if path is None:
        return None
    rows, scripts = _empty_rows(), {}
    unplaced = 0
    cached = 0
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or '"start"' not in line:
                    continue
                if SEARCH_TOOL not in line and FEED_TOOL not in line \
                        and CACHE_TOOL not in line and '"script"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("status") != "start":
                    continue
                if row.get("kind") == "script":
                    if row.get("id"):
                        scripts[row["id"]] = {"step": row.get("step"),
                                              "params": row.get("params")}
                    continue
                if row.get("kind") != "child":
                    continue
                tool = row.get("tool")
                if tool == CACHE_TOOL:
                    # CF-0824: answered by the cache - not a call, not a spend
                    params = row.get("params") if isinstance(row.get("params"), dict) else {}
                    said = params.get(ARTICLE_PARAM)
                    if said not in ARTICLES:
                        said = article_of_event({**row, "tool": SEARCH_TOOL}, scripts) \
                            or UNPLACED_ARTICLE
                    rows[said]["cached_search_calls"] += 1
                    cached += 1
                    continue
                if tool not in (SEARCH_TOOL, FEED_TOOL):
                    continue
                article = article_of_event(row, scripts)
                argv = row.get("argv")
                verb = argv[1] if isinstance(argv, list) and len(argv) > 1 else None
                is_search = tool == SEARCH_TOOL and verb == SEARCH_VERB
                if article is None:
                    if not is_search:
                        continue      # an unplaceable 1-unit call is not guessed at
                    unplaced += 1
                    article = UNPLACED_ARTICLE
                row_of = rows[article]
                if tool == FEED_TOOL:
                    row_of["free_calls"] += 1
                elif is_search:
                    row_of["search_calls"] += 1
                else:
                    row_of["api_calls"] += 1
                    row_of["api_units"] += UNITS_PER_CALL
                step = row.get("step") or "-"
                row_of["steps"][step] = row_of["steps"].get(step, 0) + 1
    except OSError:
        return None
    return {"by_article": rows,
            "search_calls": sum(r["search_calls"] for r in rows.values()),
            "api_units": sum(r["api_units"] for r in rows.values()),
            "unplaced_search_calls": unplaced,
            "cached_search_calls": cached}


def searches_from_events(batch_dir):
    """The `search.list` calls recorded under this batch directory, or None
    when there is no run log to read. The total of `spend_from_events`, kept
    as its own name because it is what the day's 100-call cap counts."""
    spend = spend_from_events(batch_dir)
    return None if spend is None else spend["search_calls"]


def quota_block(batch=None):
    """The batch's `search_quota` block, fresh or as it stands. Always the
    same shape once this has run - "nothing was counted" and "nobody ever
    counted" must not read alike."""
    block = (batch or {}).get(QUOTA_KEY)
    if not isinstance(block, dict):
        block = {"task": "CF-0313"}
    # CF-0368: the two ledgers beside the call count - which article each key
    # of it belongs to, and the 1-unit calls that key spent. Both are per key
    # for the same reason the call count is: a second pass over the same batch
    # hands in the same signals and must not be charged twice.
    for key in ("searches_by_topic", "articles_by_key", "api_units_by_key", CACHED_LEDGER):
        if not isinstance(block.get(key), dict):
            block[key] = {}
    for key in ("searches_before_stage", "substitutions_made"):
        if not isinstance(block.get(key), int) or isinstance(block.get(key), bool):
            block[key] = 0
    totals = (((batch or {}).get(PRESCREEN_KEY) or {}).get("totals"))
    if isinstance(totals, dict):
        block[SAVED_KEY] = {
            "task": "CF-0823",
            "search_calls": int(totals.get("search_calls_saved") or 0),
            "refused_by_probe": int(totals.get("refused_by_probe") or 0),
            "refused_by_memory": (int(totals.get("refused_by_memory") or 0)
                                  + int(totals.get("skipped_by_memory_at_refill") or 0)),
            "note": "candidates refused by the fact check before their scoring search - "
                    "one bare search.list each the scoring article did not spend"}
    return block


def article_of(signal, default=ARTICLE_FOOTAGE):
    """Which article one fetch output belongs to, by what the file says about
    itself. A feed signal says `source: youtube-feeds` and `searches: 0` with
    an `api_units` beside it (CF-0361), and that is the whole difference: it
    spent the other currency. Anything else is the caller's article."""
    if not isinstance(signal, dict):
        return default
    if signal.get("source") == FEED_SOURCE:
        return ARTICLE_FEEDS
    if signal.get("searches") == 0 and signal.get("api_units") is not None:
        return ARTICLE_FEEDS
    return default


def units_of(signal):
    """The 1-unit Data API calls one fetch output cost (`api_units`, written
    by `fetch_channel_feeds.py` since CF-0361). 0 when the file does not say -
    a search output has never carried the number, and its `videos.list` calls
    are counted off the run log instead of guessed at here."""
    if not isinstance(signal, dict):
        return 0
    units = signal.get("api_units")
    if isinstance(units, bool) or not isinstance(units, int) or units < 0:
        return 0
    return units


def count_searches(block, by_key, article=ARTICLE_FOOTAGE):
    """Put what these searches cost into the ledger, per topic. A key already
    counted keeps its number: the same signal handed in twice is one facet run
    that was paid for once.

    `article` is the article the caller is spending on (CF-0368); a signal that
    says it is a feed read is charged to the feeds whatever the caller says,
    because the currency is the file's fact, not the caller's."""
    ledger = block["searches_by_topic"]
    articles = block.setdefault("articles_by_key", {})
    units = block.setdefault("api_units_by_key", {})
    for key, signal in (by_key or {}).items():
        if key is None:
            continue
        cost = signal if isinstance(signal, int) else searches_of(signal)
        key = str(key)
        ledger[key] = max(int(ledger.get(key) or 0), int(cost))
        articles[key] = article_of(signal, article)
        spent_units = units_of(signal)
        if spent_units:
            units[key] = max(int(units.get(key) or 0), spent_units)
        hits = 0 if isinstance(signal, int) else cached_of(signal)
        if hits:
            led = block.setdefault(CACHED_LEDGER, {})
            led[key] = max(int(led.get(key) or 0), hits)
    return block


def charge(block, key, article, searches=0, api_units=0, cached=0):
    """Add one more pass's spend to the ledger under its own key (CF-0368).

    Additive where `count_searches` is idempotent, because the two describe
    different things: a signal handed in twice is the same facet run, while a
    second supplement run of the same topic is a second set of calls that were
    really made."""
    key = str(key)
    if searches:
        led = block["searches_by_topic"]
        led[key] = int(led.get(key) or 0) + int(searches)
    if api_units:
        units = block.setdefault("api_units_by_key", {})
        units[key] = int(units.get(key) or 0) + int(api_units)
    if cached:
        # CF-0824: what the cache answered of this pass - its own ledger
        led = block.setdefault(CACHED_LEDGER, {})
        led[key] = int(led.get(key) or 0) + int(cached)
    if searches or api_units or cached:
        block.setdefault("articles_by_key", {})[key] = (
            article if article in ARTICLES else UNPLACED_ARTICLE)
    return block


def _from_signals(block):
    """The ledger read by article -> `{article: {"search_calls", "api_units"}}`."""
    rows = {a: {"search_calls": 0, "api_units": 0, "cached_search_calls": 0}
            for a in ARTICLES}
    articles = block.get("articles_by_key") or {}
    units = block.get("api_units_by_key") or {}
    for key, hits in (block.get(CACHED_LEDGER) or {}).items():
        article = articles.get(key)
        rows[article if article in ARTICLES else UNPLACED_ARTICLE]["cached_search_calls"] += \
            int(hits or 0)
    for key, calls in (block.get("searches_by_topic") or {}).items():
        article = articles.get(key)
        rows[article if article in ARTICLES else UNPLACED_ARTICLE]["search_calls"] += int(calls or 0)
    for key, spent in units.items():
        article = articles.get(key)
        rows[article if article in ARTICLES else ARTICLE_FEEDS]["api_units"] += int(spent or 0)
    return rows


def by_article(block, batch_dir=None):
    """The four articles as one block: per article the larger of what the
    signals cost and what the run log recorded, in both currencies.

    The rule is CF-0313's, applied a row at a time instead of to one total -
    which is also why the rows can add up to more than the old
    `max(signals, events)` did: a footage pass the signals know about and a
    scoring pass only the run log knows about are two spends, and summing the
    two counts' maximum lost one of them."""
    sig = _from_signals(block)
    spend = spend_from_events(batch_dir)
    ev = (spend or {}).get("by_article") or {}
    rows = {}
    for name in ARTICLES:
        s, e = sig[name], ev.get(name) or {}
        calls = max(s["search_calls"], int(e.get("search_calls") or 0))
        units = max(s["api_units"], int(e.get("api_units") or 0))
        hits = max(s["cached_search_calls"], int(e.get("cached_search_calls") or 0))
        rows[name] = {
            "article": name,
            "what": ARTICLE_WHAT[name],
            "spends_search_calls": name in SEARCH_ARTICLES,
            "against_daily_search_cap": bool(calls),
            "search_calls": calls,
            "search_units": calls * UNITS_PER_SEARCH,
            "api_calls": int(e.get("api_calls") or 0),
            "api_units": units,
            "free_calls": int(e.get("free_calls") or 0),
            "units": calls * UNITS_PER_SEARCH + units,
            # CF-0824: answered by the channel's cache - in no spend
            "cached_search_calls": hits,
            "from_signals": dict(s),
            "from_run_events": (dict(e) if spend is not None else None),
        }
    # CF-0823: what the fact check before scoring kept off the scoring article
    rows[ARTICLE_SCORING]["saved_search_calls"] = int(
        (block.get(SAVED_KEY) or {}).get("search_calls") or 0)
    return rows, spend


def settle(block, batch_dir=None, before=None, price=FACET_RUN_SEARCHES,
           limit=SEARCH_CALLS_PER_DAY):
    """Recompute what is spent, what is left, and how many substitutions the
    remainder pays for. Called after every change to the ledger, so the three
    numbers can never drift from the rows they are a view of."""
    if before is not None:
        block["searches_before_stage"] = max(0, int(before))
    from_signals = sum(int(v or 0) for v in block["searches_by_topic"].values())
    # CF-0368: the articles are settled first, because the total is now their
    # sum - one file read for both, the run log being the expensive part.
    rows, spend = by_article(block, batch_dir)
    from_events = None if spend is None else spend["search_calls"]
    by_art = sum(r["search_calls"] for r in rows.values())
    spent = max(from_signals, from_events or 0, by_art) + block["searches_before_stage"]
    remaining = max(0, int(limit) - spent)
    price = max(1, int(price))
    block.update({
        "daily_limit_searches": int(limit),
        "units_per_search": UNITS_PER_SEARCH,
        "resets_at": RESET_AT,
        "searches_from_signals": from_signals,
        "searches_from_run_events": from_events,
        "spent_searches": spent,
        "spent_units": spent * UNITS_PER_SEARCH,
        "remaining_searches": remaining,
        "remaining_units": remaining * UNITS_PER_SEARCH,
        "substitution_price_searches": price,
        "substitution_price_units": price * UNITS_PER_SEARCH,
        "substitutions_affordable": remaining // price,
        "note": NOTE,
        # CF-0368. The same spend, by article. `spent_api_units` is the other
        # currency and is *not* part of `spent_units`: one is 100 units a call
        # against a cap of 100 calls, the other is 1 unit a call against
        # nothing this stage has ever come near.
        "articles_task": ARTICLE_TASK,
        "by_article": rows,
        "spent_api_units": sum(r["api_units"] for r in rows.values()),
        "spent_units_all": spent * UNITS_PER_SEARCH + sum(r["api_units"] for r in rows.values()),
        "unplaced_search_calls": (None if spend is None
                                  else spend["unplaced_search_calls"]),
        # CF-0824: the searches the channel's cache answered - not in
        # `spent_searches`, which is what the root's quota day sums
        "cached_search_calls": sum(r["cached_search_calls"] for r in rows.values()),
        "articles_note": ARTICLE_NOTE,
    })
    block["summary_line"] = summary_line(block)
    return block


def can_afford(block, price=None):
    """Is there room in the day for one more substitution?"""
    price = price or block.get("substitution_price_searches") or FACET_RUN_SEARCHES
    return block.get("remaining_searches", 0) >= price


def line(block):
    """The one line the CLIs print about the day's quota."""
    events = block.get("searches_from_run_events")
    return (f"search quota: {block.get('spent_searches')} of "
            f"{block.get('daily_limit_searches')} search call(s) spent "
            f"({block.get('spent_units')} units), {block.get('remaining_searches')} left "
            f"= {block.get('substitutions_affordable')} substitution(s) at "
            f"{block.get('substitution_price_searches')} each"
            + (f"; {events} counted in {EVENTS_FILE}" if events else "")
            + (f"; {block['searches_before_stage']} spent before this stage"
               if block.get("searches_before_stage") else ""))


# --------------------------------------------------------------------------
# CF-0368: what the run summary says
# --------------------------------------------------------------------------

def summary_line(block):
    """The one line about the day's YouTube spend, by article - the line
    `RUN_SUMMARY.md` carries (CF-0368).

    Rendered here rather than in the root, and shipped inside the run-log
    event, so that the summary prints the stage's own words: the root has no
    business knowing what a facet run is or why the feeds are a currency of
    their own."""
    rows = block.get("by_article") or {}
    parts = []
    for name in ARTICLES:
        row = rows.get(name) or {}
        calls = int(row.get("search_calls") or 0)
        units = int(row.get("api_units") or 0)
        what = f"{calls} call(s)" if name in SEARCH_ARTICLES else ""
        hits = int(row.get("cached_search_calls") or 0)
        if hits:
            what += f" + {hits} cached"
        if units or not what:
            what = (what + ", " if what else "") + f"{units} unit(s)"
        parts.append(f"{ARTICLE_LABEL[name]} {what}")
    spent = int(block.get("spent_searches") or 0)
    tail = ""
    if block.get("searches_before_stage"):
        tail += f", {block['searches_before_stage']} of them before this stage"
    if block.get("cached_search_calls"):
        tail += (f", {block['cached_search_calls']} search(es) answered from the channel's "
                 f"cache (not spent)")
    if block.get("unplaced_search_calls"):
        tail += (f", {block['unplaced_search_calls']} call(s) the run log could not "
                 f"place (charged to {ARTICLE_LABEL[UNPLACED_ARTICLE]})")
    return (f"YouTube quota: {spent} of {block.get('daily_limit_searches')} search call(s) "
            f"({block.get('spent_units')} units) plus {block.get('spent_api_units')} unit(s) "
            f"of 1-unit calls - " + " · ".join(parts)
            + f"; {block.get('remaining_searches')} call(s) left, resets {block.get('resets_at')}"
            + tail)


def article_lines(block):
    """One stderr line per article, for the CLIs that print the ledger."""
    rows = block.get("by_article") or {}
    out = []
    for name in ARTICLES:
        row = rows.get(name) or {}
        steps = ((row.get("from_run_events") or {}).get("steps")) or {}
        out.append(
            f"  {ARTICLE_LABEL[name]:<14} {row.get('search_calls', 0)} search call(s), "
            f"{row.get('api_calls', 0)} unit call(s) = {row.get('api_units', 0)} unit(s), "
            f"{row.get('free_calls', 0)} free rss read(s), {row.get('units', 0)} unit(s) in all"
            + (f", {row['cached_search_calls']} search(es) from the cache"
               if row.get("cached_search_calls") else "")
            + (f" [{', '.join(f'{k} x{v}' for k, v in sorted(steps.items()))}]" if steps else ""))
    return out


def event_payload(block):
    """The `quota` run-log event's body: the rows the root may render itself,
    small enough to sit on one event line."""
    rows = block.get("by_article") or {}
    return {
        "task": ARTICLE_TASK,
        "spent_searches": block.get("spent_searches"),
        "daily_limit_searches": block.get("daily_limit_searches"),
        "spent_units": block.get("spent_units"),
        "spent_api_units": block.get("spent_api_units"),
        "remaining_searches": block.get("remaining_searches"),
        "resets_at": block.get("resets_at"),
        "unplaced_search_calls": block.get("unplaced_search_calls"),
        "cached_search_calls": block.get("cached_search_calls"),
        "by_article": {n: {k: (rows.get(n) or {}).get(k)
                           for k in ("search_calls", "search_units", "api_calls",
                                     "api_units", "free_calls", "units",
                                     "cached_search_calls")}
                       for n in ARTICLES},
    }


def record_event(block, runlog=None, batch_dir=None, step=None):
    """Write the `quota` event the root's RUN_SUMMARY line is made of, and
    return it (None when there is no run log to write to).

    `shared/runlog/summary.py` reads `RUN_EVENTS.jsonl` and nothing else, so a
    number that is only in `01-trend-hunter.json` never reaches the summary.
    The event carries the rendered line as well as the rows: the root prints
    `line` of the last `quota` event of the batch and is done.

    Accounting never breaks a run - a missing or broken runlog is silence."""
    if runlog is None:
        return None
    try:
        return runlog.emit(batch_dir, EVENT_KIND, STAGE, step=step,
                           status="done", params={"task": ARTICLE_TASK},
                           line=summary_line(block), quota=event_payload(block))
    except Exception:  # noqa: BLE001 - see the docstring
        return None


def article_from_env(env=None, default=None):
    """The article the caller put in the environment (`ARTICLE_ENV`), or
    `default` when there is none or it is not one of the four. Used by
    `fetch_youtube_signal.py`, which cannot otherwise tell whose search it is
    running - the supplement's or step 5b's."""
    import os
    said = (env if env is not None else os.environ).get(ARTICLE_ENV)
    return said if said in ARTICLES else default


def with_article(env, article):
    """A copy of `env` with the article in it, for a subprocess that will do
    the spending (`footage_supplement.run_search`)."""
    out = dict(env)
    if article in ARTICLES:
        out[ARTICLE_ENV] = article
    return out

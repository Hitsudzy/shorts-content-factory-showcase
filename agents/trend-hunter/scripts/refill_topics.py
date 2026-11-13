#!/usr/bin/env python3
"""CF-0756: the hunter refills the batch to its target - rounds over the same
candidate pool until the fact rule leaves `target_topics` topics, within a cap.

Where it was found. The first ExampleTech batch
(`pipeline/example-tech/2026-10-15T1854Z`): ~220 news items over three days,
twelve candidates scored, five above the threshold, and the fact rule took
four of them off (`no_fact`) - the batch went on with one topic, so at most
one video. The hunter chose once and never went back to the pool it had
gathered. The user's decision of 15.10: repeat until there are 5 topics
(3 at least), within 3 rounds or 40 search calls.

What this script is. The stage is an LLM operator, and scoring a candidate is
the operator's work (step 3's one bare search, step 4's score, the threshold,
the `title_ref` the probe needs) - so the loop is the operator's too, and this
script is the part of it that must not be reasoned about in a head: *whether*
another round runs, *which* candidates it takes and *how many*, and what the
batch file says about it afterwards. One call after every pass of
`fact_probe_topics.py --write`:

    scripts/refill_topics.py <batch-dir> [--pool <file>] [--searches-spent N] --write

prints `{"action": "score", "round": k, "candidates": [...]}` - score these,
add the ones above the threshold to `topics[]`, run the probe again, call this
again - or `{"action": "done", "stopped_because": ...}` - go on to step 5b
with what the batch has.

The pool. Every candidate step 2 found, at `<batch-dir>/work/candidate-pool.json`
(`--pool` overrides) - written by `candidate_pool.py build` for the channels
it builds (CF-0772: every entry that names something), by the operator at
step 4 for the others:

    {"candidates": [{"name": "...", "popularity_score": 66.3 | null,
                     "distinct_rss_houses": 1, "distinct_rss_entries": 2,
                     "rss_links": ["..."], "topic_id": "..." | null}, ...]}

A candidate marked `out_of_scope` (CF-0772, `candidate_pool.py mark`) is
never taken. A candidate with a score was evaluated by the first pass and is never taken
again (it is in the batch, or it was below the threshold); nor is one whose
name or `topic_id` is already a topic, a refusal, or the pick of an earlier
round. The rest are taken in descending order of what is known of their score
before the search is paid for - the RSS half of it (`distinct_rss_houses`,
then `distinct_rss_entries`), then the order of the pool.

How many a round takes:

    need  = target - topics carried
    yield = topics carried / candidates evaluated so far   (floor 0.1; 0.5 when nothing was)
    take  = min(max(need, ceil(need / yield)),             what the yield says it costs
                ceil(searches left in the cap / rounds left),   the cap spread over the rounds
                searches left in the cap,
                the day's quota left after the footage reserve,
                candidates left in the pool)

Every pick costs one `search.list` (the scoring pass's bare query, CF-0038),
so `searched` is the picks' count - or, where the batch has a run log, the
scoring article's calls since the refill began (`search_quota.spend_from_events`),
whichever is larger: a measurement must never come out cheaper than the plan.
The day's quota is `search_quota.settle` over the batch (the same 100 a day
step 5b's `substitutions_affordable` divides), less a reserve of one facet run
(`FACET_RUN_SEARCHES`, 6) for each of the `target_topics` the footage step
will need - a refill that spends the footage's searches makes a batch of
topics with no footage.

CF-0789: the scored count is a target too. On the funnel of 2026-10-18
ExampleTech's batches carried 5 / 2 / 14 candidates into the probe and
ExampleScience's 6 / 3, ExampleFilm's 9-17 - and a batch at its five topics
stopped refilling with 108 candidates of its pool never searched
(example-tech 2026-10-16T0839Z), so it had no reserve for a slot a later stage
empties. `scope.min_scored_candidates` (default 12, ExampleFilm's floor since
2026-10-04) is how many candidates the probe must have judged - cleared the
threshold and been asked for their fact, counted over every pass - before the
refill may stop on `target_met`. A round then takes the larger of what the
topic target and what the scored target need; the scored half is
`ceil(scored still needed / pass rate)`, the pass rate being the batch's own
(scored / evaluated, same floor and unknown value as the yield). The caps, the
rounds and the footage reserve of the quota bound it exactly as before.

Where the candidates came from and what they cost (CF-0789,
`refill.sources`): per house of the channel's feeds (`sources.rss.feeds[]`,
by the candidate's `houses` when the pool names them, else by its links'
hosts against the feeds' `site`) the pool's candidates, the out-of-scope ones,
the ones evaluated (one scoring search each), scored (judged by the probe) and
viable (carried or the shortlist's reserve); per feed the entries and HTTP
requests of the fetch (`discovery.rss.coverage`); and the totals with the
scoring searches in calls and API units.

When it stops (`refill.stopped_because`, first that holds):

    target_met   the batch carries `target_topics` and the probe has judged
                 `min_scored_candidates`
    pool_empty   no candidate of the pool is left to evaluate
    rounds       `max_refill_rounds` rounds ran
    search_cap   `max_refill_search_calls` search calls were spent on it
    quota        the day's quota, less the footage reserve, pays for none

Below the target the batch goes on with what it has; below `min_topics` the
summary line says WARNING, and the stage report and the `stage-done` note
quote it. The fact rule is the probe's and is not touched here: a refilled
topic is judged by the same `fact_probe_topics.py` pass as the first five.

CF-0823: the fact is asked before the search. A round's picks are drafted
and put through `fact_probe_topics.py --before-scoring` first; a pick that
pass refuses (`no_fact`, `before_scoring: true`) is never searched, so it
costs the cap nothing: a round's `searches_planned` is its picks less those,
`yield` and the pass rate are over the searched candidates only, and
`scored` (the CF-0789 target) counts no refusal made before the search - the
minimum is reached with candidates that were searched and judged, the next
candidates of the pool making up for the ones the fact took off, never a
lower minimum. A round takes `ceil(want / survival)` picks, `survival` being
the batch's own share of pre-checked candidates that passed (floor
`SURVIVAL_FLOOR`), within the very same caps - a pick is still at most one
search. A candidate the channel's `no_fact` memory holds back
(`no_fact_memory.py`, `scope.no_fact_memory_days`) is not picked at all; the
ones a round skipped for it, that it would have taken, are
`refill.memory_skipped` and count as searches not spent in
`batch.prescreen.totals`. `refill.sources` counts per house the candidates
`prescreened` (refused before their search) apart from `evaluated`.

CF-0876: a work the channel's thin-pool memory holds back
(`thin_pool_memory.py`, `scope.thin_pool_memory_days`: refused
`pool_too_thin` at 0 clean shots in its last days of batches, no new source
in the shared pool since) is not picked either - a slot the batch has to
fill is not handed to a work whose pool is known to be empty. The ones a
round skipped for it are `refill.thin_pool_skipped` and count as searches
not spent in `batch.prescreen.totals`.

The four numbers are the channel's (`scope.target_topics`, `scope.min_topics`,
`scope.max_refill_rounds`, `scope.max_refill_search_calls` of
`channels/<channel>.json`), read the way `shortlist_size` is; a key that is
absent takes the default below and says so in `refill.params.from`.
`target_topics` above `scope.shortlist_size` is clamped to it: the probe never
carries more than the shortlist, so a larger target could never be met.
"""
import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import runlog  # noqa: E402
from _channel_ids import MissingChannelError  # noqa: E402
import fact_probe_topics as fp  # noqa: E402
import no_fact_memory  # noqa: E402  - CF-0823
import thin_pool_memory  # noqa: E402  - CF-0876
import search_quota  # noqa: E402

STAGE = "trend-hunter"
TASK = "CF-0756"
REFILL_KEY = "refill"
POOL_REL = Path("work") / "candidate-pool.json"

# the channel's keys (under `scope`) and their defaults (the user's 15.10)
TARGET_KEY = "target_topics"
MIN_KEY = "min_topics"
ROUNDS_KEY = "max_refill_rounds"
SEARCH_CAP_KEY = "max_refill_search_calls"
MIN_SCORED_KEY = "min_scored_candidates"      # CF-0789
#: CF-0789: ExampleFilm's level - the fewest candidates its batches carried
#: into the probe since 2026-10-04 (12, 12, 15, 16; docs/notes/funnel-2026-10-18.md).
DEFAULT_MIN_SCORED = 12
DEFAULTS = {TARGET_KEY: 5, MIN_KEY: 3, ROUNDS_KEY: 3, SEARCH_CAP_KEY: 40,
            MIN_SCORED_KEY: DEFAULT_MIN_SCORED}
SOURCES_KEY = "sources"
SOURCES_TASK = "CF-0789"
UNATTRIBUTED = "unattributed"

STOP_TARGET = "target_met"
STOP_POOL = "pool_empty"
STOP_ROUNDS = "rounds"
STOP_SEARCH_CAP = "search_cap"
STOP_QUOTA = "quota"
STOP_REASONS = (STOP_TARGET, STOP_ROUNDS, STOP_SEARCH_CAP, STOP_QUOTA, STOP_POOL)

ACTION_SCORE = "score"
ACTION_DONE = "done"

SEARCHES_PER_PICK = 1          # the scoring pass's bare `search.list` (CF-0038)
YIELD_FLOOR = 0.1
YIELD_UNKNOWN = 0.5
#: CF-0823: the least share of pre-checked candidates taken to pass the fact
#: check when a round's picks are sized (a round never takes more than 1/x of
#: what it needs searched on account of it - and never past the caps)
SURVIVAL_FLOOR = 0.25
PRESCREENED = "prescreened"


class RefillError(ValueError):
    """The batch or the pool cannot be refilled as they stand."""


# --------------------------------------------------------------------------
# the channel's numbers
# --------------------------------------------------------------------------

def params_of(config, shortlist_size=fp.DEFAULT_SHORTLIST_SIZE):
    """The four numbers from a channel config (`scope`), with the defaults.
    -> (params, notes); `params["from"]` says per key "channel" or "default"."""
    scope = (config or {}).get("scope") or {}
    params, origin, notes = {}, {}, []
    for key, default in DEFAULTS.items():
        value = scope.get(key)
        if value is None:
            params[key], origin[key] = default, "default"
            continue
        try:
            number = int(value)
            if isinstance(value, bool) or number < 0:
                raise ValueError
        except (TypeError, ValueError):
            params[key], origin[key] = default, "default"
            notes.append(f"scope.{key} is {value!r}, not a whole number >= 0; "
                         f"using {default}")
            continue
        params[key], origin[key] = number, "channel"
    size = max(0, int(shortlist_size))
    if params[TARGET_KEY] > size:
        notes.append(f"scope.{TARGET_KEY} {params[TARGET_KEY]} is above the shortlist "
                     f"({size}) the probe carries at most; the target is {size}")
        params[TARGET_KEY] = size
    if params[MIN_KEY] > params[TARGET_KEY]:
        notes.append(f"scope.{MIN_KEY} {params[MIN_KEY]} is above the target "
                     f"{params[TARGET_KEY]}; the minimum is the target")
        params[MIN_KEY] = params[TARGET_KEY]
    params["from"] = origin
    return params, notes


def channel_config(channel, root=None):
    """`channels/<channel>.json` as a dict, or None when there is none."""
    try:
        return json.loads(fp.channel_config_path(channel, root).read_text())
    except (OSError, ValueError):
        return None


def channel_params(channel, root=None):
    """`params_of` over `channels/<channel>.json` (the config lives in the
    root repository; this stage only reads it). No config: the defaults."""
    size, size_note = fp.shortlist_size_of(channel, root=root)
    notes = [size_note] if size_note else []
    config = channel_config(channel, root)
    if config is None:
        config = {}
        notes.append(f"no channel config for {channel!r}; the refill takes its defaults")
    params, more = params_of(config, size)
    return params, notes + more


def load_memory(channel, config, batch_id, root=None):
    """The channel's `no_fact` memory (CF-0823) as of now, its own batch's
    entries left out."""
    return no_fact_memory.load(root or fp.factory_root(), channel, config, batch=batch_id)


def load_thin_memory(channel, config, batch_id, root=None):
    """The channel's thin-pool memory (CF-0876) as of now, read out of its
    earlier batches, its own batch left out."""
    return thin_pool_memory.load(root or fp.factory_root(), channel, config, batch=batch_id)


def feeds_of(config):
    """`sources.rss.feeds[]` of a channel config (objects only)."""
    feeds = (((config or {}).get("sources") or {}).get("rss") or {}).get("feeds") or []
    return [f for f in feeds if isinstance(f, dict)]


# --------------------------------------------------------------------------
# the pool
# --------------------------------------------------------------------------

def load_pool(path):
    """The candidate pool file -> its list of candidates (each with a `name`)."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise RefillError(f"no candidate pool at {path} - step 4 writes every candidate "
                          f"step 2 found there (CF-0756)")
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise RefillError(f"{path}: not JSON ({exc})")
    rows = data.get("candidates") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise RefillError(f"{path}: no `candidates` list")
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            raise RefillError(f"{path}: candidates[{i}] has no name")
        out.append(row)
    return out


def _int(value):
    try:
        return int(value) if not isinstance(value, bool) else 0
    except (TypeError, ValueError):
        return 0


def is_scored(candidate):
    score = candidate.get("popularity_score")
    return (isinstance(score, (int, float)) and not isinstance(score, bool)) \
        or candidate.get("scored") is True


def _names_of_topic(topic):
    ref = (topic or {}).get("title_ref") or {}
    return [ref.get("name"), ref.get("person"), (topic or {}).get("title")]


def judged(batch):
    """(names, ids) the batch has already judged: its topics, its refusals
    (the reserve rows' topics too) and every earlier round's picks."""
    names, ids = set(), set()

    def add(name):
        if isinstance(name, str) and name.strip():
            names.add(fp.normalise(name))

    for topic in batch.get("topics") or []:
        ids.add(topic.get("topic_id"))
        for name in _names_of_topic(topic):
            add(name)
    for row in batch.get("skipped_topics") or []:
        if not isinstance(row, dict):
            continue
        ids.add(row.get("topic_id"))
        add(row.get("title"))
        for name in _names_of_topic(row.get(fp.RESERVE_TOPIC_KEY)):
            add(name)
    for rnd in (batch.get(REFILL_KEY) or {}).get("round_log") or []:
        for pick in rnd.get("taken") or []:
            add(pick.get("name"))
            ids.add(pick.get("topic_id"))
    ids.discard(None)
    return names, ids


def untaken(pool, batch, memory=None, held=None, thin_memory=None, thin_held=None):
    """The candidates a round may still take, best first. With the channel's
    `no_fact` memory (CF-0823) a candidate it holds back is not among them;
    `held`, a list, gets `(candidate, entry, its place in the order)` for
    each, the place counted among every candidate the order had. The
    thin-pool memory (CF-0876) is asked the same way, into `thin_held`."""
    names, ids = judged(batch)
    left = []
    for index, cand in enumerate(pool):
        if is_scored(cand):
            continue
        if cand.get("out_of_scope"):   # CF-0772: the operator's scope mark - never searched
            continue
        if cand.get("topic_id") and cand.get("topic_id") in ids:
            continue
        if fp.normalise(cand["name"]) in names:
            continue
        left.append((index, cand))
    left.sort(key=lambda pair: (-_int(pair[1].get("distinct_rss_houses")),
                                -_int(pair[1].get("distinct_rss_entries")), pair[0]))
    out = []
    for place, (_, cand) in enumerate(left):
        entry = memory.hit(cand) if memory is not None else None
        if entry is not None:
            if held is not None:
                held.append((cand, entry, place))
            continue
        thin = thin_memory.hit(cand) if thin_memory is not None else None
        if thin is not None:
            if thin_held is not None:
                thin_held.append((cand, thin, place))
            continue
        out.append(cand)
    return out


_ID = re.compile(r"^(.*?)(\d+)$")


def next_topic_ids(batch, count):
    """`count` fresh topic ids in the batch's own numbering (prefix + the
    next numbers past every id the batch has used), or Nones."""
    _, ids = judged(batch)
    best, top, width = None, 0, 3
    for tid in ids:
        m = _ID.match(str(tid))
        if not m:
            continue
        if best is None or int(m.group(2)) > top:
            best, top, width = m.group(1), int(m.group(2)), len(m.group(2))
    if best is None:
        return [None] * count
    return [f"{best}{str(top + i).zfill(width)}" for i in range(1, count + 1)]


# --------------------------------------------------------------------------
# the day's quota
# --------------------------------------------------------------------------

def quota_view(batch, batch_dir=None, before=None, target=DEFAULTS[TARGET_KEY]):
    """What the day has left for the refill: `search_quota.settle` over a copy
    of the batch's block (nothing of it is written here - step 5b owns it),
    less one facet run for each topic of the target."""
    block = search_quota.quota_block(copy.deepcopy(batch))
    search_quota.settle(block, batch_dir=batch_dir, before=before)
    remaining = int(block.get("remaining_searches") or 0)
    reserve = search_quota.FACET_RUN_SEARCHES * max(0, int(target))
    spend = search_quota.spend_from_events(batch_dir)
    scoring = None
    if spend is not None:
        scoring = int(((spend.get("by_article") or {}).get(search_quota.ARTICLE_SCORING)
                       or {}).get("search_calls") or 0)
    return {"remaining_searches": remaining, "spent_searches": block.get("spent_searches"),
            "searches_before_stage": block.get("searches_before_stage"),
            "reserved_for_footage": reserve,
            "reserve_rule": f"{search_quota.FACET_RUN_SEARCHES} search calls (one facet run) "
                            f"for each of the {int(target)} target topics",
            "left_for_refill": max(0, remaining - reserve),
            "scoring_search_calls": scoring}


# --------------------------------------------------------------------------
# what the probe has judged, and where the candidates came from (CF-0789)
# --------------------------------------------------------------------------

def _stage_rows(batch):
    return [row for row in batch.get("skipped_topics") or []
            if isinstance(row, dict) and row.get("stage", STAGE) == STAGE]


def judged_status(batch):
    """{topic_id or normalised name: "carried" | "reserve" | "refused"} for
    every topic the probe has judged, over every pass."""
    status = {}

    def put(topic, value, title=None):
        keys = [topic.get("topic_id")] if isinstance(topic, dict) else []
        names = _names_of_topic(topic) if isinstance(topic, dict) else []
        for name in names + [title]:
            if isinstance(name, str) and name.strip():
                keys.append(fp.normalise(name))
        for key in keys:
            if key and key not in status:
                status[key] = value

    for topic in batch.get("topics") or []:
        put(topic, "carried")
    for row in _stage_rows(batch):
        value = "reserve" if row.get("reason_code") == fp.OVERFLOW_CODE else "refused"
        if row.get(fp.BEFORE_SCORING_KEY):
            value = PRESCREENED      # CF-0823: refused before its search
        put(row.get(fp.RESERVE_TOPIC_KEY) or row, value, row.get("title"))
        if row.get("topic_id") and row["topic_id"] not in status:
            status[row["topic_id"]] = value
    return status


def scored_count(batch):
    """How many candidates the probe has judged, over every pass: the topics
    carried and this stage's refusals, one per topic - not a refusal made
    before the candidate was searched (CF-0823), and not a draft still
    waiting for its score."""
    seen, count = set(), 0
    rows = [(t, None) for t in batch.get("topics") or [] if not fp.is_unscored(t)]
    rows += [(r.get(fp.RESERVE_TOPIC_KEY) or r, r.get("title")) for r in _stage_rows(batch)
             if not r.get(fp.BEFORE_SCORING_KEY)]
    for topic, title in rows:
        keys = {topic.get("topic_id")} if isinstance(topic, dict) else set()
        if not keys - {None}:
            for name in _names_of_topic(topic) + [title]:
                if isinstance(name, str) and name.strip():
                    keys.add(fp.normalise(name))
                    break
        keys.discard(None)
        if not keys or keys & seen:
            continue
        seen |= keys
        count += 1
    return count


def _host(link):
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#:]+)", str(link or "").strip().lower())
    host = m.group(1) if m else ""
    return host[4:] if host.startswith("www.") else host


def _house_of_link(link, feeds):
    host = _host(link)
    if not host:
        return None
    for feed in feeds:
        site = str(feed.get("site") or "").lower()
        site = site[4:] if site.startswith("www.") else site
        if site and (host == site or host.endswith("." + site)):
            return feed.get("house")
    return None


def houses_of_candidate(cand, feeds):
    """The houses a candidate came from: the pool's own `houses` (CF-0772's
    pool counts them by the feed that carried the entry) and its company feeds,
    else its links' hosts against the feeds' `site`; none -> `unattributed`."""
    houses = [h for h in (cand.get("houses") or []) if h]
    houses += [h for h in (cand.get("vendor_feeds") or []) if h and h not in houses]
    if not houses:
        for link in cand.get("rss_links") or []:
            house = _house_of_link(link, feeds)
            if house and house not in houses:
                houses.append(house)
    return houses or [UNATTRIBUTED]


def _feed_house(url, feeds):
    for feed in feeds:
        if feed.get("url") == url:
            return feed.get("house")
    return None


def sources_ledger(batch, pool, feeds, block):
    """CF-0789: where the batch's candidates came from and what they cost."""
    status = judged_status(batch)
    picked = {fp.normalise(p.get("name") or "") for rnd in block.get("round_log") or []
              for p in rnd.get("taken") or []}
    picked_ids = {p.get("topic_id") for rnd in block.get("round_log") or []
                  for p in rnd.get("taken") or []} - {None}
    zero = {"candidates": 0, "out_of_scope": 0, PRESCREENED: 0, "evaluated": 0, "scored": 0,
            "viable": 0}
    by_house, totals = {}, dict(zero)
    for cand in pool:
        name = fp.normalise(cand.get("name") or "")
        state = status.get(cand.get("topic_id")) or status.get(name)
        prescreened = state == PRESCREENED and not is_scored(cand)
        evaluated = (bool(state) or is_scored(cand) or name in picked
                     or (cand.get("topic_id") in picked_ids)) and not prescreened
        marks = {"candidates": 1,
                 "out_of_scope": 1 if cand.get("out_of_scope") else 0,
                 PRESCREENED: 1 if prescreened else 0,
                 "evaluated": 1 if evaluated and not cand.get("out_of_scope") else 0,
                 "scored": 1 if state and state != PRESCREENED else 0,
                 "viable": 1 if state in ("carried", "reserve") else 0}
        for key, value in marks.items():
            totals[key] += value
        for house in houses_of_candidate(cand, feeds):
            row = by_house.setdefault(house, dict(zero))
            for key, value in marks.items():
                row[key] += value
    coverage = (((batch.get("discovery") or {}).get("rss") or {}).get("coverage")) or []
    feed_rows = []
    for row in coverage:
        if not isinstance(row, dict):
            continue
        feed_rows.append({"feed": row.get("feed"), "feed_url": row.get("feed_url"),
                          "house": _feed_house(row.get("feed_url"), feeds),
                          "entries": _int(row.get("entries")),
                          "requests": _int(row.get("requests_made")),
                          "covered_days": row.get("covered_days"),
                          "stopped_because": row.get("stopped_because")})
    measured = (block.get("quota") or {}).get("scoring_search_calls")
    calls = max(totals["evaluated"], _int(measured)) if measured is not None \
        else totals["evaluated"]
    totals.update({
        "rss_entries": sum(r["entries"] for r in feed_rows),
        "rss_requests": sum(r["requests"] for r in feed_rows),
        "scoring_search_calls": calls,
        "scoring_search_calls_from": "run_log" if measured is not None
                                     and _int(measured) > totals["evaluated"] else "pool",
        "scoring_api_units": calls * search_quota.UNITS_PER_SEARCH,
        "untouched": (totals["candidates"] - totals["out_of_scope"] - totals["evaluated"]
                      - totals[PRESCREENED]),
    })
    return {"task": SOURCES_TASK,
            "note": "a candidate several houses carried counts under each of them; "
                    "prescreened = refused by the fact check before its search (CF-0823), "
                    "evaluated = one scoring search, scored = judged by the fact probe, "
                    "viable = carried or the shortlist's reserve",
            "feeds": feed_rows,
            "by_house": dict(sorted(by_house.items())),
            "totals": totals}


# --------------------------------------------------------------------------
# the round
# --------------------------------------------------------------------------

def _asked_at(batch):
    return (((batch.get("selection") or {}).get("fact_probe") or {}).get("asked_at"))


def _carried_ids(batch):
    return [t.get("topic_id") for t in batch.get("topics") or []]


def _judged_count(batch):
    return len(batch.get("topics") or []) + len(batch.get("skipped_topics") or [])


def refused_counts(batch):
    counts = {}
    for row in batch.get("skipped_topics") or []:
        if isinstance(row, dict) and row.get("stage", STAGE) == STAGE:
            code = row.get("reason_code") or "?"
            counts[code] = counts.get(code, 0) + 1
    return counts


def _pick_row(cand, topic_id):
    row = {"name": cand.get("name"),
           "distinct_rss_houses": _int(cand.get("distinct_rss_houses")),
           "distinct_rss_entries": _int(cand.get("distinct_rss_entries")),
           "topic_id": topic_id}
    if cand.get("rss_links"):
        row["rss_links"] = list(cand["rss_links"])
    return row


def _stop_text(block):
    p, reason = block["params"], block.get("stopped_because")
    q = block.get("quota") or {}
    if reason == STOP_TARGET:
        return (f"the target is met: {block.get('topics')} topic(s), "
                f"{block.get('scored')} scored of {p.get(MIN_SCORED_KEY)}")
    if reason == STOP_ROUNDS:
        return f"the cap of {p[ROUNDS_KEY]} refill round(s) ran out"
    if reason == STOP_SEARCH_CAP:
        return f"the cap of {p[SEARCH_CAP_KEY]} refill search call(s) ran out"
    if reason == STOP_QUOTA:
        return (f"the day's search quota has {q.get('remaining_searches')} call(s) left and "
                f"{q.get('reserved_for_footage')} are the footage's ({q.get('reserve_rule')})")
    if reason == STOP_POOL:
        return (f"no unevaluated candidate left in the pool of "
                f"{(block.get('pool') or {}).get('candidates')}")
    return "a round is open"


def summary_line(block):
    p = block["params"]
    line = (f"refill ({TASK}): {block['topics']} topic(s) of target {p[TARGET_KEY]} "
            f"(min {p[MIN_KEY]}), {block.get('scored')} scored of "
            f"{p.get(MIN_SCORED_KEY)} - {block['rounds']} round(s), {block['searched']} of "
            f"{p[SEARCH_CAP_KEY]} search call(s), +{block['added']} topic(s)")
    saved = int(block.get(PRESCREENED) or 0) + len(block.get("memory_skipped") or [])
    if saved:
        line += (f", {block.get(PRESCREENED) or 0} pick(s) refused before scoring and "
                 f"{len(block.get('memory_skipped') or [])} held back by the no_fact memory "
                 f"(CF-0823)")
    thin = len(block.get("thin_pool_skipped") or [])
    if thin:
        line += f", {thin} held back by the thin-pool memory (CF-0876)"
    if block.get("stopped_because"):
        line += f"; stopped: {block['stopped_because']} ({_stop_text(block)})"
    else:
        line += f"; round {block['rounds']} open"
    if block.get("below_min"):
        line = (f"WARNING below_min_topics {line} - the batch goes on with "
                f"{block['topics']}, fewer than the channel's minimum {p[MIN_KEY]}")
    elif block.get("below_scored"):
        line += (f" - below the channel's {MIN_SCORED_KEY} {p.get(MIN_SCORED_KEY)}: "
                 f"{block.get('scored')} scored")
    return line


def _prescreened_keys(batch):
    """(ids, names) of the candidates refused before their search (CF-0823)."""
    ids, names = set(), set()
    for row in _stage_rows(batch):
        if row.get(fp.BEFORE_SCORING_KEY):
            if row.get("topic_id"):
                ids.add(row["topic_id"])
            if isinstance(row.get("title"), str) and row["title"].strip():
                names.add(fp.normalise(row["title"]))
    return ids, names


def _round_searches(batch, block):
    """CF-0823: a pick refused before its search costs none - each round's
    `searches_planned` is its picks less those (recounted on every call, so a
    round's number falls once its pre-scoring pass has run)."""
    ids, names = _prescreened_keys(batch)
    total = 0
    for rnd in block.get("round_log") or []:
        taken = rnd.get("taken") or []
        refused = sum(1 for pick in taken
                      if pick.get("topic_id") in ids
                      or fp.normalise(pick.get("name") or "") in names)
        rnd["picks"] = len(taken)
        rnd[PRESCREENED] = refused
        rnd["searches_planned"] = (len(taken) - refused) * SEARCHES_PER_PICK
        total += refused
    return total


def _survival(batch):
    """The batch's own share of pre-checked candidates that passed the fact
    check (CF-0823), or None when none was pre-checked."""
    totals = ((batch.get(fp.PRESCREEN_KEY) or {}).get("totals")) or {}
    judged = (int(totals.get("passed") or 0) + int(totals.get("refused_by_probe") or 0)
              + int(totals.get("refused_by_memory") or 0))
    if not judged:
        return None
    return max(SURVIVAL_FLOOR, int(totals.get("passed") or 0) / judged)


def _note_memory_skips(batch, block, skipped, number):
    """Write the candidates a round passed over for the `no_fact` memory into
    the refill block and the batch's pre-scoring ledger (CF-0823)."""
    rows = block.setdefault("memory_skipped", [])
    have = {fp.normalise(r.get("name") or "") for r in rows}
    for cand, entry in skipped:
        key = fp.normalise(cand.get("name") or "")
        if key in have:
            continue
        have.add(key)
        rows.append({"name": cand.get("name"), "round": number,
                     "refused_at": entry.get("refused_at"), "batch": entry.get("batch"),
                     "subreason": entry.get("subreason")})
    if rows:
        pre = fp.prescreen_block(batch)
        pre["refill_memory_skipped"] = list(rows)
        fp.prescreen_totals(pre)


def _note_thin_skips(batch, block, skipped, number):
    """The same for the thin-pool memory (CF-0876): `refill.thin_pool_skipped`
    and the pre-scoring ledger's `refill_thin_pool_skipped`."""
    rows = block.setdefault("thin_pool_skipped", [])
    have = {fp.normalise(r.get("name") or "") for r in rows}
    for cand, entry in skipped:
        key = fp.normalise(cand.get("name") or "")
        if key in have:
            continue
        have.add(key)
        rows.append({"name": cand.get("name"), "round": number,
                     "refused_at": entry.get("refused_at"), "batch": entry.get("batch"),
                     "weak_shots": entry.get("weak_shots"),
                     "refusals": len(entry.get("refusals") or [])})
    if rows:
        pre = fp.prescreen_block(batch)
        pre["refill_thin_pool_skipped"] = list(rows)
        fp.prescreen_totals(pre)


def _totals(block, batch, quota):
    block[PRESCREENED] = _round_searches(batch, block)
    planned = sum(int(r.get("searches_planned") or 0) for r in block["round_log"])
    measured = None
    before = block.get("scoring_search_calls_before")
    now = quota.get("scoring_search_calls")
    if before is not None and now is not None:
        measured = max(0, now - before)
    start = set(block.get("carried_before") or [])
    added = [tid for tid in _carried_ids(batch) if tid not in start]
    block.update({
        "topics": len(batch.get("topics") or []),
        "scored": scored_count(batch),
        "rounds": len(block["round_log"]),
        "searched_planned": planned,
        "searched_measured": measured,
        "searched": max(planned, measured or 0),
        "added": len(added),
        "added_topic_ids": added,
        "refused": refused_counts(batch),
        "quota": quota,
    })


def next_round(batch, pool, params, quota, pool_path=None, none_passed=False, feeds=None,
               memory=None, thin_memory=None):
    """One step of the loop over the batch (changed in place: `batch["refill"]`).
    -> the action for the operator: `score` with the round's candidates, or
    `done` with why. Calling it twice without a probe in between changes
    nothing and hands back the same open round. `memory` is the channel's
    `no_fact_memory.Memory` (CF-0823): a candidate it holds back is not
    picked; nor is one `thin_memory` (`thin_pool_memory.Memory`, CF-0876)
    holds back."""
    if not isinstance(batch.get("selection"), dict):
        raise RefillError("the batch has no `selection` - run fact_probe_topics.py --write "
                          "first; the refill counts what the fact rule left")
    block = batch.get(REFILL_KEY)
    if not isinstance(block, dict) or "round_log" not in block:
        block = {"task": TASK,
                 "carried_before": _carried_ids(batch),
                 "topics_before": len(batch.get("topics") or []),
                 "evaluated_before": sum(1 for c in pool if is_scored(c)),
                 "scoring_search_calls_before": quota.get("scoring_search_calls"),
                 "round_log": [], "stopped_because": None, "open_round": None}
        batch[REFILL_KEY] = block
    block["params"] = {k: params[k] for k in DEFAULTS}
    block["params"]["from"] = dict(params.get("from") or {})
    target, rounds_cap, cap = params[TARGET_KEY], params[ROUNDS_KEY], params[SEARCH_CAP_KEY]
    min_scored = int(params.get(MIN_SCORED_KEY) or 0)

    # an open round closes once the probe has judged what it added
    open_no = block.get("open_round")
    if open_no:
        rnd = block["round_log"][open_no - 1]
        block[SOURCES_KEY] = sources_ledger(batch, pool, feeds or [], block)
        probed = (_asked_at(batch) != rnd.get("probe_asked_at")
                  or _judged_count(batch) != rnd.get("judged_at_open"))
        # CF-0823: every pick refused before its search - nothing to score
        p_ids, p_names = _prescreened_keys(batch)
        all_prescreened = bool(rnd.get("taken")) and all(
            pick.get("topic_id") in p_ids or fp.normalise(pick.get("name") or "") in p_names
            for pick in rnd["taken"])
        if not probed and not none_passed and not all_prescreened:
            _totals(block, batch, quota)
            block["summary_line"] = summary_line(block)
            return {"action": ACTION_SCORE, "round": open_no, "reopened": True,
                    "candidates": rnd["taken"], "searches_planned": rnd["searches_planned"],
                    "note": f"round {open_no} is still open: score its candidates, add those "
                            f"above the threshold to topics[], run fact_probe_topics.py "
                            f"--write, then call this again (--none-passed when not one "
                            f"cleared the threshold)"}
        at_open = set(rnd.get("carried_at_open") or [])
        rnd.update({"closed_by": ("prescreen" if all_prescreened
                                  else "probe" if probed else "none_passed"),
                    "topics_after": len(batch.get("topics") or []),
                    "added_topic_ids": [t for t in _carried_ids(batch) if t not in at_open]})
        block["open_round"] = None

    held, thin_held = [], []
    pool_left = untaken(pool, batch, memory=memory, held=held, thin_memory=thin_memory,
                        thin_held=thin_held)
    _totals(block, batch, quota)
    block["pool"] = {"path": str(pool_path) if pool_path else None,
                     "candidates": len(pool),
                     "evaluated_before": block.get("evaluated_before"),
                     "out_of_scope": sum(1 for c in pool if c.get("out_of_scope")),
                     "left": len(pool_left)}
    carried, scored = block["topics"], block["scored"]
    cap_left = max(0, cap - block["searched"])
    rounds_left = max(0, rounds_cap - block["rounds"])
    quota_left = int(quota.get("left_for_refill") or 0)

    if carried >= target and scored >= min_scored:
        stop = STOP_TARGET
    elif not pool_left:
        stop = STOP_POOL
    elif rounds_left == 0:
        stop = STOP_ROUNDS
    elif cap_left < SEARCHES_PER_PICK:
        stop = STOP_SEARCH_CAP
    elif quota_left < SEARCHES_PER_PICK:
        stop = STOP_QUOTA
    else:
        stop = None
    if stop:
        block["stopped_because"] = stop
        block["below_min"] = carried < params[MIN_KEY]
        block["below_scored"] = scored < min_scored
        block[SOURCES_KEY] = sources_ledger(batch, pool, feeds or [], block)
        block["summary_line"] = summary_line(block)
        return {"action": ACTION_DONE, "stopped_because": stop,
                "line": block["summary_line"]}

    need = max(0, target - carried)
    need_scored = max(0, min_scored - scored)
    evaluated = (block.get("evaluated_before") or 0) + block["searched_planned"]
    yld = (max(carried / evaluated, YIELD_FLOOR) if evaluated else YIELD_UNKNOWN)
    pass_rate = (min(1.0, max(scored / evaluated, YIELD_FLOOR)) if evaluated
                 else YIELD_UNKNOWN)
    want = max(max(need, math.ceil(need / yld)) if need else 0,
               math.ceil(need_scored / pass_rate) if need_scored else 0, 1)
    survival = _survival(batch)
    if survival:
        # CF-0823: some picks will not pass the fact check and will not be
        # searched - take enough that the survivors cover the need
        want = math.ceil(want / survival)
    take = min(want, math.ceil(cap_left / rounds_left), cap_left // SEARCHES_PER_PICK,
               quota_left // SEARCHES_PER_PICK, len(pool_left))
    picks = pool_left[:take]
    held_places = {place for _, _, place in held + thin_held}
    out_places = [p for p in range(len(pool_left) + len(held) + len(thin_held))
                  if p not in held_places]
    last = out_places[take - 1] if take else -1
    skipped = [(cand, entry) for cand, entry, place in held if place < last]
    thin_skipped = [(cand, entry) for cand, entry, place in thin_held if place < last]
    ids = next_topic_ids(batch, len(picks))
    taken = [_pick_row(c, tid) for c, tid in zip(picks, ids)]
    number = block["rounds"] + 1
    block["round_log"].append({
        "round": number, "topics_before": carried, "need": need,
        "yield": round(yld, 3), "scored_before": scored, "need_scored": need_scored,
        "pass_rate": round(pass_rate, 3), "taken": taken,
        "searches_planned": len(taken) * SEARCHES_PER_PICK,
        "survival": round(survival, 3) if survival else None,
        "memory_skipped": [c.get("name") for c, _ in skipped],
        "thin_pool_skipped": [c.get("name") for c, _ in thin_skipped],
        "carried_at_open": _carried_ids(batch),
        "judged_at_open": _judged_count(batch),
        "probe_asked_at": _asked_at(batch),
        "closed_by": None})
    _note_memory_skips(batch, block, skipped, number)
    _note_thin_skips(batch, block, thin_skipped, number)
    block["open_round"] = number
    block["stopped_because"] = None
    block["below_min"] = None
    block["below_scored"] = None
    _totals(block, batch, quota)
    block["pool"]["left"] = len(pool_left) - len(taken)
    block[SOURCES_KEY] = sources_ledger(batch, pool, feeds or [], block)
    block["summary_line"] = summary_line(block)
    return {"action": ACTION_SCORE, "round": number, "candidates": taken,
            "searches_planned": len(taken) * SEARCHES_PER_PICK,
            "memory_skipped": [c.get("name") for c, _ in skipped],
            "thin_pool_skipped": [c.get("name") for c, _ in thin_skipped],
            "note": "draft these, run fact_probe_topics.py --before-scoring --write, score "
                    "only the drafts it leaves in topics[] (CF-0823)",
            "line": block["summary_line"]}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    ap.add_argument("--pool", help=f"the candidate pool (default <batch-dir>/{POOL_REL})")
    ap.add_argument("--searches-spent", type=int, default=None,
                    help="search.list calls the same quota day spent outside this batch "
                         "(search_quota's searches_before_stage)")
    ap.add_argument("--none-passed", action="store_true",
                    help="close the open round although the probe did not run: not one "
                         "of its candidates cleared the threshold")
    ap.add_argument("--write", action="store_true", help="write the refill block")
    args = ap.parse_args(argv)

    path = fp._batch_path(args.batch)
    if not path.exists():
        print(f"no {path}", file=sys.stderr)
        return 2
    batch = json.loads(path.read_text())
    try:
        channel = fp.channel_of(batch)
    except MissingChannelError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 2
    params, notes = channel_params(channel)
    config = channel_config(channel)
    feeds = feeds_of(config)
    # CF-0823: the channel's no_fact memory - a candidate it holds is not picked
    memory = load_memory(channel, config, path.parent.name)
    # CF-0876: the channel's thin-pool memory - a work it holds is not picked
    thin_memory = load_thin_memory(channel, config, path.parent.name)
    pool_path = Path(args.pool).expanduser() if args.pool else path.parent / POOL_REL
    try:
        pool = load_pool(pool_path)
        quota = quota_view(batch, path.parent, before=args.searches_spent,
                           target=params[TARGET_KEY])
        action = next_round(batch, pool, params, quota, pool_path=pool_path,
                            none_passed=args.none_passed, feeds=feeds, memory=memory,
                            thin_memory=thin_memory)
    except RefillError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 2
    if args.write:
        path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(action, ensure_ascii=False, indent=2))
    print(batch[REFILL_KEY]["summary_line"], file=sys.stderr)
    for note in notes:
        print(f"  {note}", file=sys.stderr)
    return 0


@runlog.script(STAGE, "refill", name="refill_topics.py")
def cli(argv=None):
    """main()'s return code becomes the exit code inside the run event."""
    sys.exit(main(argv))


if __name__ == "__main__":
    cli()

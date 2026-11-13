#!/usr/bin/env python3
"""CF-0264: the production fact is asked for at **topic selection**, not after
the footage has been downloaded.

CF-0438 (grill of 2026-09-29) widened what is asked for: any kind of fact, from
the batch's channel's source list (`<root>/channels/<id>/fact-sources.json`,
CF-0627; read through `_channel_data`). Item 2 below still runs
the probe, but only to resolve the topic's article; the candidates are then
searched for in every section of that article and in the batch's own news
(`fact_search.py`), each is checked by `fact_rule.check_candidates` (Q4), the
checked list is written onto the topic as `fact_candidates` for the writer, and
the topic leaves - with `no_fact`, no longer `no_production_fact` - only when
not one candidate passes and every source answered. Where the text below says
"no_article / no_section / ... take the topic off", read "left no candidate".

The measurement behind this (grill of 2026-09-17, decision of CF-0260, log in
Notebook `Operator-Notes/grill-me-logs/2026-09-17 - Правило факта и
темы-персоны (CF-0260)`): the batch of 2026-09-16T2148Z selected five topics
and lost three of them to the channel's refusal rule - no production fact, no
video - *after* the indexer had downloaded and indexed six sources for them,
~36 minutes of 48. The rule itself is not softened here and never is: the
channel's stance is "retell the story and add one concrete fact about how the
thing was made", and a topic with no findable fact is not a story this channel
tells. What moves is the moment the question is asked.

So this script sits between scoring (step 5) and the footage fan-out (step
5b), over the batch file the stage has already drafted, and does three things
in this order, all of them over the candidates **in descending score**:

  1. **Persons.** A story about a person is this channel's story in its own
     right (CF-0439, `channels/example-film/stance.json` -> `persons`): a
     person-topic no longer needs a named work, and nothing is refused here.
     Until CF-0439 a person-topic whose own news named no work left with
     `person_without_work` (CF-0260/CF-0264) - that refusal was a consequence
     of the production-only fact (a biography has no Production section) and
     went with it. What stays is the other half of that rule: a work may
     never be inferred from a filmography. The fact is looked up for the work
     only when *the topic's own news leads* (the RSS headlines and summaries
     behind `evidence.sources` / `evidence.rss_links`) print it - then
     `title_ref.name` is that work and `title_ref.person` the person, as
     before. Otherwise the subject of the fact is the person: `title_ref.name`
     is (or becomes) the person's name, and a work the news did not print is
     taken out of `title_ref.name` with a note in the stage report ("Michael
     J. Fox received an ovation at the Emmys" plus a fact about the shooting
     schedule of *Shrinking* is a fact about the wrong thing). The check is
     mechanical: the work's own string has to occur in the leads. A fact about
     a real person is held to the rule's stricter requirement (a major outlet,
     never a rumour, "X said that...": `fact_rule.check_candidate`), which this
     change does not touch.

  2. **The probe - a hard filter, not a weight.** Every surviving candidate is
     asked about through the Content Researcher's own lookup
     (`agents/content-researcher/scripts/fact_probe.py`, CF-0263) with what
     the topic is known to be (type, year, season, network, and the parent
     work its own news name, for a spin-off or a sequel). One subprocess for
     the whole list, so the pacing is shared. An outcome of `no_article`,
     `no_section`, `no_candidates` or `wrong_article` takes the topic off the
     batch with `no_production_fact` and the probe's own record beside it -
     which article the search resolved to, how many candidates, why it was the
     wrong article.

     **The filter is on `usable`, not on `has_fact`.** `source_unreachable` is
     not "this topic has no fact": it is "we could not ask". A shortlist
     filtered on `has_fact` would empty itself during a Wikipedia outage and
     the batch would look like a day with no news. A topic the source could
     not be asked about stays, carries its `source_unreachable` record, and
     the writer's own refusal rule (CF-0185) judges it later, as it did before
     this script existed.

  2b. **The support text (CF-0551).** Every topic the fact rule kept is read
     for the text its story may be told from (`support_text.py`: the work's
     Wikipedia article whole, its season's article, the episode descriptions,
     and the news leads' RSS summaries as fetched) and carries it as
     `topics[].support_text` with `topics[].support_check`. A topic with no
     text for its own event - no article of its own, or the episode its news
     is about with no description yet - leaves with `no_support_text`, before
     the cut, so its slot is the next topic's (CF-0546 Q7). Wikipedia that
     could not be asked is not "no text": the topic stays, marked
     `unreachable`. The reserve rows keep the whole topic, support text
     included, so a substitute at step 5b carries it too.

  3. **The shortlist.** The first `scope.shortlist_size` viable topics, in
     score order - since CF-0325 in **score x pool** order: `pool_coverage.py`
     reads what `shared/footage` already holds for each viable topic, writes
     it as `topics[].pool`, and a topic with a pool gets a bounded bonus
     (x1 .. x1.5, never below its bare score; see that module). The number lives in the channel config next to
     `max_titles_per_batch` and defaults to 8 when it is absent. Trend Hunter
     no longer cuts to five: compliance judges the whole shortlist and the cut
     to `max_titles_per_batch` happens after it (CF-0265), because on
     2026-09-16 Spire-Runner took a slot, compliance took it off, and there was
     no replacement. Everything past the cut is `below_shortlist` in
     `skipped_topics[]` - above the popularity threshold, with a fact, and not
     used; DoD 1.4.4 item 1 allows no silent loss, including this one.

     Since CF-0313 (2026-09-22) such a row carries `rank` and the topic
     record itself under `topic`, because the reserve is no longer only an
     audit trail: a topic `footage_candidates.py` refuses at step 5b takes
     its slot out of the batch, and the next reserve topic by rank is put
     back into `topics[]` in its place. A summary cannot be put back - the
     whole `title_ref` decides what compliance judges - so the cut keeps
     what it cuts.

  1b. **Already made (CF-0019).** Between the persons and the probe, every
     topic is compared with the videos the factory has made and the user
     accepted (`published_before.py`: `publish/acceptance-log.json`,
     `publish/<slug>.md`, the topic read back out of its source batch's `01`).
     The same work told from the same news - a shared article URL - leaves
     with `already_published` and is not probed; the same work with another
     story, another season or another installment of the franchise stays and
     carries `published_before: [...]`, and the stage report quotes its
     `WARNING published_before` line. A rejected video is not "made".

Every refusal is a `skipped_topics[]` record with `reason_code`, `reason`,
`stage` (the vocabulary of `shared/runlog/funnel.py` FUNNEL_CODES) and, when
the probe ran, the probe's answer under `fact_probe`. Every carried topic
keeps its own answer in `topic["fact_probe"]`, so the Content Researcher reads
the fact out of the same article this stage was answered from.

Usage (from the agent root, after the batch file has its scored topics and
before the footage fan-out):

    scripts/fact_probe_topics.py <batch-dir|01-trend-hunter.json> \\
        --rss /tmp/trend-hunter-rss.json --write
    scripts/fact_probe_topics.py <batch-dir|file> --check     # validate only

Order, and what it costs. The probe is free (Wikipedia, no key) and the
footage fan-out is not: one facet run is 6 searches x 100 quota units. So the
probe runs **first**, over every scored candidate, and `footage_candidates.py`
runs only over the shortlist that survived it. A 15-candidate probe is ~1
minute and 0 quota; a shortlist of 8 then costs 4,800 units of footage search
instead of the 3,000 five titles cost - and the three titles of 2026-09-16
that were indexed for nothing cost more than that difference.

CF-0823: the fact before the *scoring* search, too. The scoring pass pays one
`search.list` a candidate (CF-0038), and over 04-20.10 ExampleTech paid it for
24 candidates this pass then refused with `no_fact` - Character.AI five times
in five batches. So the same fact pass now runs once more, earlier, over the
drafted candidates the scoring has not searched yet:

    scripts/fact_probe_topics.py <batch-dir> --rss <rss.json> --before-scoring --write

It takes the topics of `topics[]` that have no `signal.popularity_score`
(the drafts of the candidates about to be scored), holds back every one the
channel's memory of `no_fact` refusals names (`no_fact_memory.py`: refused in
the last `scope.no_fact_memory_days` days, 3 by default - not probed, not
searched), and puts the rest through exactly the fact search above (persons,
the probe, Wikipedia / Wikidata / the batch's news / the company's own post,
the rule) - without the support text, the publish registry, the pool or the
cut, which are the full pass's. A candidate no fact passes for leaves with
`no_fact` and `before_scoring: true` before a search is paid for it (CF-0876:
a work the channel's thin-pool memory holds - refused `pool_too_thin` at 0
clean shots in its last days of batches, `thin_pool_memory.py` - leaves the
same way as `pool_too_thin` with `thin_pool_memory`); the rest
stay in `topics[]`, marked `prescreen`, and are scored. `prescreen` at the top
of the batch counts it: the candidates pre-checked, refused by the probe and
by the memory, and `search_calls_saved`. With `--write` every `no_fact` of a
pass (this one's and the full pass's) is added to the memory.
"""
import argparse
import copy
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import runlog, factory_root  # noqa: E402
from _channel_ids import MissingChannelError, resolve_channel  # noqa: E402
from _factrule import fact_rule  # noqa: E402
from _channel_data import channel_data  # noqa: E402  - CF-0627
import fact_search  # noqa: E402
import pool_coverage  # noqa: E402
import published_before  # noqa: E402  - CF-0019
import support_text  # noqa: E402  - CF-0551
import vendor_page  # noqa: E402  - CF-0757
import no_fact_memory  # noqa: E402  - CF-0823
import thin_pool_memory  # noqa: E402  - CF-0876

# --------------------------------------------------------------------------
# the vocabulary
# --------------------------------------------------------------------------
# What a topic is. Not guessed: a topic whose `title_ref` does not say is a
# topic this stage refuses to judge, because "person or work" decides which
# rule applies and a wrong guess here is the CF-0260 failure exactly.
WORK_KIND = "work"
PERSON_KIND = "person"
KINDS = (WORK_KIND, PERSON_KIND)

# `shared/runlog/funnel.py` FUNNEL_CODES - spelled here rather than imported,
# the same way footage_candidates.py spells `no_source`: this repo is a nested
# checkout and must not import from the root's tree.
#
# `no_production_fact` already exists there (CF-0185). It is the code for all
# four no-fact outcomes on purpose: the funnel counts *why a topic left the
# batch*, and the four outcomes are four diagnoses of one cause. Which of them
# it was is never lost - it is `fact_probe.outcome` on the record, with the
# article the search resolved to beside it.
# CF-0438: the code is `no_fact` now (any kind of fact, not only production),
# and it is the rule's own constant rather than a string spelled here. The old
# word is still *read* - `fact_rule.canonical_code()` - in batches written
# before CF-0438, and never written again.
FACT_REFUSAL_CODE = fact_rule.REFUSAL_CODE
# CF-0439: no longer written - the stance dropped the refusal (a story about a
# person is the channel's own). Kept as a name because batches written before
# 2026-09-29 carry it in `skipped_topics[]` and the funnel still counts them.
PERSON_REFUSAL_CODE = "person_without_work"     # CF-0264, retired by CF-0439
OVERFLOW_CODE = "below_shortlist"               # CF-0264, new in the root vocabulary
SUPPORT_REFUSAL_CODE = support_text.REFUSAL_CODE  # CF-0551: "no_support_text"
SUPPORT_KEY = support_text.SUPPORT_KEY            # topics[].support_text
SUPPORT_CHECK_KEY = support_text.CHECK_KEY        # topics[].support_check
STAGE = "trend-hunter"

# CF-0313. A `below_shortlist` row is the only refusal of this stage that is
# not a refusal at all - it is the reserve, and since CF-0313 the reserve is
# *used*: a topic `footage_candidates.py` refuses at step 5b (`no_source`,
# fewer than CANDIDATE_REFUSAL_FLOOR candidates) hands its shortlist slot to
# the next reserve topic by rank. Two things that pass has to have and no
# record here carried before:
#
#   `rank`  - where the topic stood in the score order, so the queue is the
#             shortlist's own order and not the order the rows happen to lie
#             in. It is in the `reason` text as well, as prose, and prose is
#             not something another script should parse.
#   `topic` - the topic record itself, whole. Until CF-0313 the cut simply
#             dropped it: `topics[]` kept the first N and the row kept a
#             summary (title, kind, score, the probe's answer), which is
#             enough to audit a loss and not enough to put the topic back in
#             the batch - `title_ref` alone decides what compliance judges and
#             what the writer looks up. So the cut now keeps what it cut.
#
# An artifact written before CF-0313 carries neither (the batches on disk are
# the regression corpus for that): `footage_candidates.restore_reserve_topic`
# rebuilds what it can from the summary and `fact_probe.asked`, and says on
# the substitution record that it did.
RANK_KEY = "rank"
RESERVE_TOPIC_KEY = "topic"

# fact_probe.py's own words (CF-0263). The first four are "no fact"; the last
# is "we could not ask", which is not the same thing and never filters.
#
# CF-0323: they are no longer spelled here. The refusal this stage applies and
# the one `agents/content-researcher/scripts/fact_refusal.py` applies after the
# footage is indexed were two similar predicates over the same five words, and
# whenever this one was the milder the difference was paid for with a full
# indexing run. There is one rule now - `scripts/fact_rule.py`, loaded through
# `_factrule` from the root's shared layer when the root has it - and these
# names are that module's, re-exported so the rest of this file and its tests
# read as they did.
OK_OUTCOME = fact_rule.STATUS_OK
NO_FACT_OUTCOMES = fact_rule.NOT_FOUND_STATUSES + (fact_rule.STATUS_WRONG_ARTICLE,)
UNREACHABLE_OUTCOME = fact_rule.STATE_UNREACHABLE

# The key a carried topic's record gets the rule's own answer under, and the
# one the Content Researcher reads instead of asking the source a second time
# (`fact_rule.re_ask`). `settled: true` on it means this exact rule has already
# judged this topic at the earliest stage that could observe it.
DECISION_KEY = "fact_rule"

# CF-0438. The checked fact candidates of a topic, best first, in `01` - the
# list the Content Researcher takes its fact from at step 2 instead of
# searching again (`fact_rule.best_candidate`) - and the record of where this
# stage looked for them (`fact_search.search_topic`'s `asked` + `error`).
CANDIDATES_KEY = fact_rule.CANDIDATES_FIELD
SEARCH_KEY = "fact_search"

# CF-0559. How many requests the pass sent to Wikipedia, per topic and in all
# - under `selection.wikipedia`. The fact search and the support text read
# through one shared client and its cache (`support_text.client_for`), so the
# topic's article is asked for once; `network` is what went past the cache.
# The probe's article search (the researcher's `fact_probe.py`, a process of
# its own) is not in it - that is `selection.fact_probe.requests`.
WIKIPEDIA_KEY = "wikipedia"
# CF-0636: the same for TVmaze (the episode descriptions of the support text,
# `support_text.tvmaze_event`) - under `selection.tvmaze`, apart from
# Wikipedia's, the topics that asked it and what went past its cache.
TVMAZE_KEY = "tvmaze"
# CF-0637: the same for Wikidata (the work's statements: fact candidates in
# `fact_search.search_topic`, pieces in `support_text.support_topic`, one
# lookup a topic for both) - under `selection.wikidata`, apart from Wikipedia's.
WIKIDATA_KEY = "wikidata"
# CF-0757: the companies' own pages read for a fact (`vendor_page.py`) - under
# `selection.vendor_page`, apart from Wikipedia's, only for a topic that had
# no passing candidate after Wikipedia, Wikidata and the batch's news.
VENDOR_KEY = vendor_page.SELECTION_KEY

# The channel's number, next to `max_titles_per_batch` in `scope`. The default
# is what the grill of 2026-09-17 decided (8) and is used when the config has
# not got the key yet - reading it absent as "cut to five" would put the cut
# back in this stage, which is the thing CF-0265 exists to take out of it.
SHORTLIST_KEY = "shortlist_size"
DEFAULT_SHORTLIST_SIZE = 8

# CF-0213: there is no channel a batch without a `channel` field belongs to.
# It used to be the first channel's id here, which would have cut a second
# channel's batch by the first one's shortlist size and refusal switch.

# The probe, in the Content Researcher's tree. Resolved from the factory root
# (`FACTORY_ROOT`, else the nearest ancestor holding shared/runlog/runlog.py -
# `_runlog.factory_root`), never copied here: the selection rule for sentences,
# the three-request ceiling and the one-second floor between requests live in
# one place, and a second implementation of them would be a second rule.
PROBE_REL = Path("agents") / "content-researcher" / "scripts" / "fact_probe.py"
PROBE_VENV_REL = Path("agents") / "content-researcher" / ".venv" / "bin" / "python"
# Seconds of ceiling on the subprocess: the probe paces itself at >= 1 s
# between requests and spends at most 6 requests on a title with a parent, so
# 12 s a topic is twice its worst case. Capped well under the five minutes no
# command in this process is allowed to exceed.
PROBE_SECONDS_PER_TOPIC = 12
PROBE_TIMEOUT_FLOOR = 30
PROBE_TIMEOUT_CEILING = 240


class ProbeUnavailable(RuntimeError):
    """The probe could not be run at all (missing, crashed, unreadable answer).
    Not the same as a topic without a fact - see `usable` in the docstring."""


# --------------------------------------------------------------------------
# the topic's own news leads
# --------------------------------------------------------------------------

_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "“": '"',
                              "”": '"', "–": "-", "—": "-"})


def normalise(text):
    """Lowercased, curly punctuation flattened, everything that is not a letter
    or a digit collapsed to one space, with a space at each end so that a
    substring test is a whole-word test."""
    if not text:
        return " "
    flat = str(text).translate(_APOSTROPHES).lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", flat).strip() + " "


def rss_index(rss_output):
    """`{link: entry}` out of a `fetch_rss_news.py` output, so a topic's
    `rss_links` can be read back as the headlines and summaries they were."""
    index = {}
    for entry in (rss_output or {}).get("entries") or []:
        link = entry.get("link")
        if link:
            index[link] = entry
    return index


def leads_of_topic(topic, index=None):
    """The news this topic was discovered by: one record per source, with
    whatever the batch kept of it (`evidence.sources` always has the headline;
    the RSS output adds the summary). This is the only text the person rule is
    allowed to read - a work named nowhere here is a work nobody wrote about."""
    evidence = topic.get("evidence") or {}
    leads, seen = [], set()
    for source in evidence.get("sources") or []:
        url = source.get("url")
        entry = (index or {}).get(url) or {}
        leads.append({"url": url,
                      "title": source.get("title") or entry.get("title"),
                      "summary": entry.get("summary")})
        if url:
            seen.add(url)
    for url in evidence.get("rss_links") or []:
        if url in seen:
            continue
        entry = (index or {}).get(url) or {}
        leads.append({"url": url, "title": entry.get("title"),
                      "summary": entry.get("summary")})
        seen.add(url)
    return leads


def lead_text(leads):
    """The leads as one normalised haystack."""
    parts = []
    for lead in leads or []:
        parts.append(normalise(lead.get("title")))
        parts.append(normalise(lead.get("summary")))
    return " ".join(parts)


def named_in_leads(work, leads):
    """Is this work *named* in the topic's own leads? Whole words, punctuation
    and case ignored ("'Rennick' Spinoff" names `Rennick`), and nothing else:
    no filmography, no knowledge of who was in what. A title the news did not
    print cannot pass this, which is the point."""
    needle = normalise(work).strip()
    if not needle:
        return False
    return f" {needle} " in lead_text(leads)


# --------------------------------------------------------------------------
# reading a topic
# --------------------------------------------------------------------------

def score_of(topic):
    value = ((topic.get("signal") or {}).get("popularity_score"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def in_score_order(topics):
    """Descending score, ties in the order the stage wrote them (stable)."""
    return sorted(topics, key=lambda t: -score_of(t))


POOL_KEY = pool_coverage.POOL_KEY


def rank_of(topic):
    """What the shortlist is cut on (CF-0325): hype x pool, i.e.
    `topics[].pool.rank_score` when the pool was asked, else the bare
    popularity score - so a batch written before CF-0325, or one where the pool
    was not asked, is ordered exactly as it was."""
    value = (topic.get(POOL_KEY) or {}).get("rank_score")
    if value is None:
        return score_of(topic)
    try:
        return float(value)
    except (TypeError, ValueError):
        return score_of(topic)


def in_rank_order(topics):
    """Descending hype x pool, ties in score order (stable)."""
    return sorted(topics, key=lambda t: -rank_of(t))


def rank_by_pool(viable, pool, notes):
    """Write `topics[].pool` onto every viable topic and return them in rank
    order. The pool is a bounded bonus (`pool_coverage` docstring): a topic
    it knows nothing about keeps its score, and a pool that cannot be asked
    leaves the score order as it was - the error is a note, never a refusal."""
    if pool is None or not viable:
        return list(viable), None
    try:
        records = pool.coverage(viable)
    except Exception as exc:
        notes.append(f"the footage pool could not be asked ({type(exc).__name__}: {exc}); "
                     f"the shortlist is cut on the score alone (CF-0325)")
        return list(viable), {"asked": False, "error": f"{type(exc).__name__}: {exc}"}
    errors = set()
    for topic in viable:
        rec = records.get(topic.get("topic_id"))
        if rec is None:
            continue
        rec["factor"] = round(pool_coverage.factor_of(rec.get("coverage")), 3)
        score = score_of(topic)
        rec["rank_score"] = pool_coverage.rank_score(score if score >= 0 else None, rec)
        topic[POOL_KEY] = rec
        if rec.get("error"):
            errors.add(rec["error"])
    for err in sorted(errors):
        notes.append(f"footage pool: {err} - ranked on what could be read (CF-0325)")
    ranked = in_rank_order(viable)
    moved = [t.get("topic_id") for i, t in enumerate(ranked) if viable[i] is not t]
    return ranked, {
        "asked": True, "rule": pool_coverage.RULE, "weight": pool_coverage.POOL_WEIGHT,
        "formula": "rank_score = popularity_score * (1 + weight * coverage), coverage = "
                   "min(1, usable / floor) (min(1, sources / 2) when usable is unmeasured)",
        "with_pool": sum(1 for t in viable if (t.get(POOL_KEY) or {}).get("sources")),
        "measured": all((t.get(POOL_KEY) or {}).get("measured") for t in viable),
        "reordered": bool(moved), "error": "; ".join(sorted(errors)) or None}


def kind_of(topic):
    return ((topic.get("title_ref") or {}).get("kind") or "").strip().lower()


def about_the_person(topic):
    """A person-topic whose subject is the person rather than a work (CF-0439)."""
    return fact_search.is_about_person(topic.get("title_ref"))


# CF-0812: the most of a topic's own text handed to the probe as `news`. The
# probe only looks in it for an edition's words ("first generation", "1999",
# "sequel"), which a headline or the first lines of a summary carry. The 34
# topics of the twelve Reel/Tech batches before 2026-10-19 ran 100-4400
# characters (median ~530), so the cap only trims an outlier's long summaries.
NEWS_CAP = 4000


def topic_news(topic, index=None, cap=NEWS_CAP):
    """The topic's own text, as the probe's edition check reads it (CF-0812):
    the tool / model of a tech topic, the topic's title, its scene
    descriptions and its news leads (headlines, RSS summaries - `leads_of_topic`).
    Never anything Wikipedia said. At most `cap` characters; None when empty."""
    ref = topic.get("title_ref") if isinstance(topic.get("title_ref"), dict) else {}
    parts = [ref.get("tool"), ref.get("model"), topic.get("title")]
    parts += [s.get("description") for s in topic.get("scenes") or []
              if isinstance(s, dict)]
    parts.append(news_text_of(leads_of_topic(topic, index)))
    text = "\n".join(str(p).strip() for p in parts
                      if p not in (None, "") and str(p).strip())
    return text[:cap] or None


def probe_request(topic, index=None):
    """The topic as fact_probe.py asks about it. The field names are
    `production_facts.topics_of_batch`'s, so the probe reads a batch file and
    this adapter ask exactly the same question. `news` (CF-0812) is the
    topic's own text, `topic_news`: the probe holds an edition-qualified
    article ("Tesla Roadster (first generation)") to it, and without it an
    edition only the news names reads as another edition. `index` is
    `rss_index(rss)`, so the leads carry their summaries."""
    ref = topic.get("title_ref") or {}
    if about_the_person(topic):
        # CF-0439: the subject is the person, and `type` / `year` / `network`
        # describe a work - held against a biography they would only turn it
        # into `wrong_article`. The name alone is asked, verifying nothing
        # (no `news` either: a sequel word in it would only hold a biography
        # to an edition it never had).
        return {"topic_id": topic.get("topic_id"), "name": ref.get("name"),
                "type": None, "year": None, "season": None, "network": None,
                "parent": None, "news": None}
    return {"topic_id": topic.get("topic_id"),
            "name": ref.get("name"),
            "type": ref.get("type"),
            "year": ref.get("year"),
            "season": ref.get("season"),
            "network": ref.get("network") or ref.get("studio") or ref.get("rights_holder"),
            "parent": ref.get("parent_work") or ref.get("parent"),
            "news": topic_news(topic, index)}


def asked_of(request):
    """A request as a topic's stored answer echoes it: without `news`, which
    is the topic's own text already in the batch (the probe does not echo it
    either)."""
    return {k: v for k, v in (request or {}).items() if k != "news"}


# --------------------------------------------------------------------------
# the person rule (item 1)
# --------------------------------------------------------------------------

def person_work_problem(topic, leads):
    """`None` when a person-topic's `title_ref.name` is either the person
    (the story is about them) or a work the topic's own news print; else what
    is wrong with it - a work taken from somewhere other than the news, i.e.
    from a filmography. A work-topic is not this rule's business.

    CF-0439: an absent work is no longer a problem (it used to be the
    `person_without_work` refusal); an inferred one still is."""
    if kind_of(topic) != PERSON_KIND:
        return None
    ref = topic.get("title_ref") or {}
    person = (ref.get("person") or "").strip()
    work = (ref.get("name") or "").strip()
    if not work or normalise(work) == normalise(person):
        return None
    if not named_in_leads(work, leads):
        return (f"person topic ({person or 'unnamed'}): {work!r} is not named in the "
                f"topic's own {len(leads)} news lead(s), so it was not taken from the news; "
                f"a work may not be inferred from a filmography (CF-0264) - the fact is "
                f"looked up for the person instead (CF-0439)")
    return None


def person_subject(topic, leads):
    """Settle what a person-topic's fact is looked up for (CF-0439), in place.

    A work its own news print stays the subject. Otherwise the subject is the
    person: `title_ref.name` becomes the person's name, and the note returned
    says which work was taken out and why. `None` when there is nothing to
    report (a work-topic, a work the news named, or a topic already about the
    person)."""
    if kind_of(topic) != PERSON_KIND:
        return None
    ref = topic.setdefault("title_ref", {})
    work = (ref.get("name") or "").strip()
    problem = person_work_problem(topic, leads)
    if work and not problem:
        return None
    ref["name"] = (ref.get("person") or "").strip()
    return problem


def parent_note(topic, leads):
    """A spin-off or a sequel may borrow its parent's fact only when the parent
    is named in the topic itself (Q3/Q4 of the grill). A parent that is not in
    the leads is dropped from the question rather than silently trusted."""
    ref = topic.get("title_ref") or {}
    parent = (ref.get("parent_work") or ref.get("parent") or "").strip()
    if not parent or named_in_leads(parent, leads):
        return None
    return (f"parent work {parent!r} is not named in this topic's own news leads, so the "
            f"probe was asked without it (a parent's fact is honest only when the topic's "
            f"own news name the parent - CF-0260 Q3)")


# --------------------------------------------------------------------------
# the probe (item 2)
# --------------------------------------------------------------------------

def probe_script(root=None):
    return (Path(root) if root else factory_root()) / PROBE_REL


def probe_python(root=None):
    venv = (Path(root) if root else factory_root()) / PROBE_VENV_REL
    return venv if venv.exists() else Path(sys.executable)


def run_probe(requests, limit=1, root=None, batch_dir=None):
    """Ask the Content Researcher's probe about this list, in one subprocess so
    that one client paces the whole run. Returns the parsed answer (the whole
    envelope: `source`, `asked_at`, `requests`, `probes[]`).

    Raises `ProbeUnavailable` when the probe could not be run or its answer
    could not be read. A non-zero exit is *not* that: exit 2 still prints the
    JSON, with `source_unreachable` on the topics it could not reach, and that
    answer is a perfectly good answer."""
    script = probe_script(root)
    if not script.exists():
        raise ProbeUnavailable(f"no probe at {script}")
    cmd = [str(probe_python(root)), str(script), "--topics", "-", "--limit", str(limit)]
    timeout = min(PROBE_TIMEOUT_CEILING,
                  max(PROBE_TIMEOUT_FLOOR, PROBE_SECONDS_PER_TOPIC * len(requests)))
    try:
        cp = runlog.run_child(cmd, tool="fact_probe.py", stage=STAGE, step="fact-probe",
                              batch_dir=batch_dir, params={"topics": len(requests),
                                                           "limit": limit},
                              input=json.dumps(requests), text=True,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ProbeUnavailable(f"the probe did not answer within {timeout}s")
    except OSError as exc:
        raise ProbeUnavailable(f"the probe could not be started: {exc}")
    try:
        return json.loads(cp.stdout)
    except ValueError:
        raise ProbeUnavailable(f"the probe answered rc={cp.returncode} with no readable "
                               f"JSON: {(cp.stderr or cp.stdout or '').strip()[:200]}")


def unreachable_answer(requests, detail):
    """The answer to write when the probe itself could not be run: every topic
    `source_unreachable`, and so every topic **usable**. Our own outage is not
    a batch of topics without facts (CF-0185's third state)."""
    return {"source": None, "asked_at": None, "requests": 0,
            "probes": [{"topic_id": r.get("topic_id"), "asked": asked_of(r),
                        "outcome": UNREACHABLE_OUTCOME, "has_fact": False, "usable": True,
                        "article": None, "article_url": None, "candidates": 0,
                        "parent_work": None, "detail": detail, "requests": 0}
                       for r in requests]}


def probe_records(answer, requests):
    """`{topic_id: record}`, each record carrying the envelope's `source` and
    `asked_at` so that a topic's stored answer says on its own where and when
    it came from."""
    by_name = {normalise((r.get("name") or "")): r.get("topic_id") for r in requests}
    out = {}
    for probe in (answer or {}).get("probes") or []:
        topic_id = probe.get("topic_id") or by_name.get(normalise((probe.get("asked") or {})
                                                                  .get("name")))
        record = dict(probe)
        record["source"] = answer.get("source")
        record["asked_at"] = answer.get("asked_at")
        out[topic_id] = record
    return out


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

def refusal_record(topic, code, reason, probe=None, candidates=None, search=None):
    """A `skipped_topics[]` row: the three fields the funnel reads
    (`topic_id`, `reason_code`, `reason`) plus `stage`, what the topic was,
    where it stood in the scoring, and the probe's own answer when one was
    given - a refusal nobody can audit afterwards is a topic that vanished."""
    ref = topic.get("title_ref") or {}
    return {"topic_id": topic.get("topic_id"),
            "reason_code": code,
            "reason": reason,
            "stage": STAGE,
            "title": ref.get("name"),
            "kind": kind_of(topic) or None,
            "popularity_score": score_of(topic) if score_of(topic) >= 0 else None,
            "fact_probe": probe,
            **({CANDIDATES_KEY: candidates} if candidates is not None else {}),
            **({SEARCH_KEY: search} if search is not None else {})}


EDITION_MISMATCH = "edition"
_EDITION_DETAIL = "about another edition"


def other_edition(probe):
    """Did the probe refuse the article as another edition (CF-0812)? Its
    `article_check.mismatch` says so when the answer carries it; the probe's
    stdin answer carries only `detail`, worded by `edition_check`."""
    check = (probe or {}).get("article_check") or {}
    if check.get("mismatch") == EDITION_MISMATCH:
        return True
    return _EDITION_DETAIL in str((probe or {}).get("detail") or "")


def fact_reason(probe, checked=None, search=None):
    """Why a topic left for `no_fact`: what the article search answered, where
    else this stage looked, how many candidates it found and why none passed."""
    outcome = probe.get("outcome")
    where = probe.get("article") or "-"
    detail = f"; {probe['detail']}" if probe.get("detail") else ""
    if other_edition(probe):
        # CF-0812: the article found is another edition's ("Tesla Roadster
        # (first generation)" for the new Roadster) - said in so many words,
        # the reason code stays `no_fact`
        text = (f"no fact: the article {probe.get('source') or 'the article search'} "
                f"found is about another edition than the topic's own news - "
                f"answered {outcome!r}{detail}")
    else:
        text = (f"no fact: {probe.get('source') or 'the article search'} answered "
                f"{outcome!r} (article: {where}){detail}")
    if search is not None:
        # CF-0757: a row that says where it looked (`vendor_page`'s hosts, or
        # why none could be read) prints it in brackets
        asked = ", ".join(f"{a.get('source')}={a.get('outcome')}"
                          f"({a.get('candidates', 0)})"
                          + (f"[{a['where']}]" if a.get("where") else "")
                          for a in search.get("asked") or [])
        fails = {}
        for cand in checked or []:
            for code in (cand.get(fact_rule.CHECK_KEY) or {}).get("failures") or []:
                fails[code] = fails.get(code, 0) + 1
        why = ", ".join(f"{k} x{v}" for k, v in sorted(fails.items())) or "none found"
        text += (f"; searched {asked}; {len(checked or [])} candidate(s), none passes the "
                 f"fact rule ({why})")
    return text


def news_text_of(leads):
    """The topic's own news as one text - what a fact must add to (Q4)."""
    return "\n".join(" ".join(x for x in (lead.get("title"), lead.get("summary")) if x)
                      for lead in leads or [])


def search_facts(topic, record, rss_entries, own_urls, sources, client=None,
                 text_feeds=None, wikidata=None):
    """The default finder: `fact_search.search_topic`. Tests hand in their own.
    `text_feeds` - the feeds whose entries may be a news candidate (CF-0638);
    `select_batch` binds the channel's. `wikidata` - the channel's Wikidata
    reader `(client, module, properties)` (CF-0637); `select_batch` binds the
    supporter's, None when the channel's list does not let it be read."""
    return fact_search.search_topic(topic, record, rss_entries, own_urls, sources,
                                    fact_rule, client=client, text_feeds=text_feeds,
                                    wikidata=wikidata)


def news_feeds_of(batch, supporter=None, root=None):
    """The feeds whose entries may be a fact candidate (CF-0638): the
    supporter's `text_feeds` when it has asked the channel already
    (`make_supporter`), else the batch's channel's
    `channel_data.support_feed_urls` (`use: read_text`). A channel that
    cannot be asked - none named, a refusal of the AI-bot rule - is no feed
    at all: closed, never open."""
    feeds = getattr(supporter, "text_feeds", None)
    if feeds is not None:
        return set(feeds)
    try:
        return set(channel_data.support_feed_urls(channel_of(batch, root=root), root=root))
    except (channel_data.ChannelDataError, MissingChannelError, FileNotFoundError,
            RuntimeError, ValueError, KeyError, TypeError):
        return set()


# --------------------------------------------------------------------------
# the pass over the batch
# --------------------------------------------------------------------------

def precheck(topics):
    """What has to be true before any of this can be decided."""
    problems = []
    for topic in topics:
        where = f"topic {topic.get('topic_id', '?')}"
        ref = topic.get("title_ref") or {}
        kind = kind_of(topic)
        if not ref.get("name") and not (kind == PERSON_KIND and (ref.get("person") or "").strip()):
            problems.append(f"{where}: title_ref.name is empty - nothing to probe")
        if kind not in KINDS:
            problems.append(
                f"{where} ({ref.get('name')!r}): title_ref.kind is {kind or 'missing'!r}; "
                f"say what this topic is - {WORK_KIND!r} or {PERSON_KIND!r} (CF-0264). "
                f"The person rule applies to one and not the other, so this stage does "
                f"not guess it")
        if kind == PERSON_KIND and not (ref.get("person") or "").strip():
            problems.append(f"{where}: kind is {PERSON_KIND!r} but title_ref.person is empty - "
                            f"name the person, and put the work its news name (if any) in "
                            f"title_ref.name")
    return problems


def unscored_problems(topics):
    """CF-0823: a draft the pre-scoring pass let through is scored before the
    full pass judges it - the cut is in score order, and a topic with no score
    would sink to the bottom of it for a reason nobody wrote down."""
    return [f"topic {t.get('topic_id', '?')} ({(t.get('title_ref') or {}).get('name')!r}): "
            f"passed the fact check before scoring and has no signal.popularity_score - "
            f"score it (step 3) or take it out of topics[] when it is below the "
            f"threshold, then run the full pass (CF-0823)"
            for t in topics if t.get("prescreen") and is_unscored(t)]


def select_batch(batch, rss=None, shortlist_size=DEFAULT_SHORTLIST_SIZE,
                 probe=run_probe, limit=1, root=None, batch_dir=None,
                 finder=search_facts, sources=None, enabled=True, pool=None,
                 published=None, supporter=None, wiki_client=None, text_feeds=None,
                 vendor=None):
    """Persons, then what was already made, then the probe, then the support
    text, then the shortlist - all in score order.

    `text_feeds` are the feeds whose entries may be a fact candidate
    (CF-0638): only those entries are handed to the finder, and the default
    finder is told them. None: `news_feeds_of` (the supporter's, else the
    channel's `read_text` feeds, else none). The leads of a topic - its own
    news, the selection - are read off every feed as before.

    `wiki_client` is the shared Wikipedia client the fact search reads the
    topic's article through (CF-0559) - the CLI hands in the one its
    supporter reads through, so the article is asked for once and the
    requests per topic are counted (`selection.wikipedia`). None with the
    default finder: an uncached shared client of the pass's own.

    `supporter(topic, probe_record, leads, index) -> (pieces, check)` reads a
    topic's support text (CF-0551, `support_text.support_topic` over the shared
    Wikipedia client). None means "not asked" - what a test that has nothing to
    do with it passes; the CLI always asks unless told `--no-support`.

    `vendor` (CF-0757) is the pass's `vendor_page.PageClient`: a topic with
    no passing candidate after Wikipedia, Wikidata and the batch's news has
    the company's own post read for one (`vendor_page.lookup` - a tier-1
    outlet whose `ai_policy.verdict` is `allowed`, through
    `source_gate.read_vendor_page`). None asks no page - what a test that has
    nothing to do with it passes; the CLI always opens one.

    `published` is `published_before.load_registry()` - the videos the factory
    has made and the user accepted (CF-0019). None means "not asked" and is
    what a test that has nothing to do with it passes; the CLI always asks.

    Returns `(problems, notes)`. On any problem the batch is left exactly as it
    was: a batch that cannot be judged is not a batch to cut."""
    topics = batch.get("topics") or []
    problems = precheck(topics) + unscored_problems(topics)
    if problems:
        return problems, []
    # CF-0627 (CF-0561): the outlets and the kinds of fact are the batch's
    # channel's list (`channels/<id>/fact-sources.json`, read through the
    # root's `shared/channel_data.py`), never a factory-wide one. A list that
    # cannot be had, or one without the channel's `kinds` (`kinds_of`), leaves
    # the batch exactly as it was.
    try:
        if sources is None:
            sources = channel_data.fact_sources(channel_of(batch, root=root), root=root)
        fact_rule.kinds_of(sources)
    except (channel_data.ChannelDataError, FileNotFoundError, RuntimeError,
            ValueError) as exc:
        return [f"no fact source list of the batch's channel "
                f"(channels/<id>/fact-sources.json): {exc} - the fact rule "
                f"has nothing to judge candidates by (CF-0438, CF-0627)"], []

    index = rss_index(rss)
    notes, refused = [], []
    ordered = in_score_order(topics)

    # 1. persons
    carried = []
    for topic in ordered:
        leads = leads_of_topic(topic, index)
        note = person_subject(topic, leads)
        if note:
            notes.append(f"{topic.get('topic_id')}: {note}")
        note = parent_note(topic, leads)
        if note:
            notes.append(f"{topic.get('topic_id')}: {note}")
            for key in ("parent_work", "parent"):
                (topic.get("title_ref") or {}).pop(key, None)
        carried.append(topic)

    # 1b. already made (CF-0019): the same work told from the same news
    # leaves before the probe - its slot goes to the next topic by the
    # ordinary ladder; the same work with another story stays, marked.
    published_block = None
    if published is not None:
        kept, dropped, marked = [], 0, 0
        for topic in carried:
            matches, drop = published_before.judge_topic(topic, published)
            if drop:
                row = refusal_record(topic, published_before.PUBLISHED_CODE,
                                     published_before.drop_reason(topic, matches))
                row[published_before.MARK_KEY] = matches
                refused.append(row)
                dropped += 1
                continue
            if matches:
                topic[published_before.MARK_KEY] = matches
                notes.append(published_before.mark_line(topic, matches))
                marked += 1
            kept.append(topic)
        carried = kept
        published_block = {"asked": True, "log": published.get("log"),
                           "videos": len(published.get("records") or []),
                           "unresolved": list(published.get("unresolved") or []),
                           "errors": list(published.get("errors") or []),
                           "dropped": dropped, "marked": marked}
        for error in published_block["errors"]:
            notes.append(f"published registry: {error} - topics were compared with what "
                         f"could be read (CF-0019)")

    # 2. the probe, one subprocess for the whole list
    requests = [probe_request(t, index) for t in carried]
    if requests:
        try:
            answer = probe(requests, limit=limit, root=root, batch_dir=batch_dir)
        except ProbeUnavailable as exc:
            notes.append(f"the fact probe could not be run ({exc}); every topic is recorded "
                         f"{UNREACHABLE_OUTCOME} and none is dropped for it - say so in the "
                         f"stage report, because this batch was not actually filtered")
            answer = unreachable_answer(requests, str(exc))
        records = probe_records(answer, requests)
    else:
        answer, records = {"probes": []}, {}

    rss_entries = (rss or {}).get("entries") if rss is not None else None
    # CF-0757: every entry of the pool, any feed - its *links* are where a
    # company's post is found (OpenAI News, Google DeepMind...); its text is
    # never a candidate (that is the page's, read through the vendor door)
    pool_entries = list(rss_entries or [])
    # CF-0638: a feed's text becomes a fact only off a `read_text` feed; the
    # entries of a `headline_only` one choose topics (the leads above) and
    # are not handed to the fact search at all.
    if text_feeds is None:
        text_feeds = news_feeds_of(batch, supporter, root=root)
    text_feeds = set(text_feeds)
    if rss_entries is not None:
        rss_entries = [e for e in rss_entries if e.get("feed_url") in text_feeds]
    # CF-0637: the supporter's Wikidata client (opened only when the
    # channel's list names the outlet) is the fact search's too - one lookup
    # a topic for both, one cache
    wd_reader = getattr(supporter, "wikidata_reader", None)
    if finder is search_facts:
        finder = functools.partial(search_facts, text_feeds=text_feeds, wikidata=wd_reader)
    client = wiki_client
    if client is None and getattr(finder, "func", finder) is search_facts:
        client = fact_search.default_client()
    viable = []
    support_counts, support_requests = {}, [0]
    wiki_per_topic = {}
    tvmaze_per_topic = {}
    wikidata_per_topic = {}
    vendor_per_topic = {}
    for topic in carried:
        record = records.get(topic.get("topic_id"))
        if record is None:
            record = unreachable_answer([probe_request(topic, index)],
                                        "the probe returned no answer for this topic")["probes"][0]
            notes.append(f"{topic.get('topic_id')}: the probe returned no answer for it; "
                         f"recorded {UNREACHABLE_OUTCOME}")
        topic["fact_probe"] = record
        # CF-0438. The probe only resolves the article now; the fact itself
        # is searched for in every section of it and in the batch's own news,
        # every candidate is checked by the rule (Q4), and the topic leaves
        # only when none passes and every source answered.
        leads = leads_of_topic(topic, index)
        own_urls = {lead.get("url") for lead in leads if lead.get("url")}
        counted = client is not None
        sent0, wire0 = fact_search.requests_of(client) if counted else (0, 0)
        found = finder(topic, record, rss_entries, own_urls, sources, client=client)
        wd_asked = next((a for a in found.get("asked") or []
                         if a.get("source") == fact_search.WIKIDATA_SOURCE), None)
        if wd_asked is not None:
            wikidata_per_topic[topic.get("topic_id")] = {
                "item": wd_asked.get("item"), "reason": wd_asked.get("detail"),
                "candidates": wd_asked.get("candidates") or 0, "pieces": 0,
                "sent": wd_asked.get("requests") or 0,
                "network": wd_asked.get("network") or 0}
        sent1 = fact_search.requests_of(client)[0] if counted else 0
        wiki = {"fact_search": sent1 - sent0, "support_text": 0,
                "network": (fact_search.requests_of(client)[1] - wire0) if counted else 0}
        wiki_per_topic[topic.get("topic_id")] = wiki
        checked = fact_rule.check_candidates(found.get("candidates"), sources,
                                             news_text=news_text_of(leads))
        # CF-0737: a sentence cut short is no fact, whatever the rule said
        checked = fact_search.refuse_cut_facts(checked, fact_rule.CHECK_KEY)
        v_newsroom = []      # CF-0810: releases found on the vendor's newsroom index
        if vendor is not None and not any((c.get(fact_rule.CHECK_KEY) or {}).get("passes")
                                          for c in checked):
            # CF-0757: nothing passed - the company's own post, before no_fact.
            # Its candidates are judged by the same rule, with the same news.
            found = dict(found)
            v_cands, v_asked = vendor_page.lookup(
                topic, leads, pool_entries, sources, fact_rule, vendor, fact_search.names_work,
                news_text=news_text_of(leads),
                about_person=fact_search.is_about_person(topic.get("title_ref")))
            found["candidates"] = list(found.get("candidates") or []) + v_cands
            found["asked"] = list(found.get("asked") or []) + [v_asked]
            checked = fact_search.refuse_cut_facts(
                fact_rule.check_candidates(found["candidates"], sources,
                                           news_text=news_text_of(leads)),
                fact_rule.CHECK_KEY)
            v_newsroom = [r["url"] for r in v_asked.get("pages") or []
                          if r.get("how") == vendor_page.VIA_NEWSROOM
                          and r.get("outcome") not in (vendor_page.OUTCOME_CAP,
                                                       vendor_page.OUTCOME_UNREACHABLE)]
            vendor_per_topic[topic.get("topic_id")] = {
                "outcome": v_asked["outcome"], "where": v_asked["where"],
                "pages": [r["url"] for r in v_asked["pages"]],
                # CF-0810: `newsroom` when the posts came off the vendor's index
                "via": v_asked.get("via"),
                "newsroom": [r["index"] for r in v_asked.get("newsroom") or []],
                "candidates": v_asked["candidates"],
                "passing": sum(1 for c in checked if c.get("vendor_page")
                               and (c.get(fact_rule.CHECK_KEY) or {}).get("passes")),
                "sent": v_asked["requests"], "network": v_asked["network"]}
        search = {"asked": found.get("asked") or [], "error": found.get("error"),
                  "found": len(checked),
                  "passing": sum(1 for c in checked
                                 if (c.get(fact_rule.CHECK_KEY) or {}).get("passes")),
                  # CF-0559: the page requests the article read sent
                  "requests": wiki["fact_search"]}
        topic[CANDIDATES_KEY] = checked[:fact_search.KEEP_MAX]
        topic[SEARCH_KEY] = search
        # CF-0323. The state is derived from what the source answered - the
        # status and the candidate count - and not read off the probe's own
        # `usable` flag. Same predicate as the writer's refusal, same three
        # states, same `wrong_article`, and the same "an empty candidate list
        # is part of the emptiness". The decision is written onto the record so
        # that nothing downstream has to ask the question again: `settled` is
        # true for every state but `source_unreachable`, which is the one
        # answer that can change between two askings.
        state, decided = fact_rule.judge(
            fact_rule.answer_of_candidates(checked, found.get("error")), STAGE, enabled)
        record[DECISION_KEY] = decided
        if not fact_rule.drops(state, enabled):
            # CF-0551: the support text - what the story may be told from. A
            # topic with none for its own event leaves here, before the
            # shortlist, so its slot is the next topic's by the same ladder.
            if supporter is not None:
                sent2 = fact_search.requests_of(client)[0] if counted else 0
                if vendor is not None and sources:
                    # CF-0771: a topic with no article of its own is told from
                    # its company's post - the pass's page client, its cache
                    # (a post the fact search read is not asked again); CF-0810:
                    # a release it found on the vendor's newsroom index too
                    supporter.vendor_reader = (
                        lambda t, ls, found=tuple(v_newsroom): support_text.vendor_pieces(
                            t, ls, pool_entries, sources, vendor,
                            now=batch.get("generated_at"), newsroom=list(found)))
                pieces, check = supporter(topic, record, leads, index)
                wiki["support_text"] = (fact_search.requests_of(client)[0] - sent2
                                        if counted else 0)
                if counted:
                    wiki["network"] = fact_search.requests_of(client)[1] - wire0
                topic[SUPPORT_KEY] = pieces
                topic[SUPPORT_CHECK_KEY] = check
                wdr = check.get("wikidata")
                if isinstance(wdr, dict):
                    # CF-0637: the support text's statements (the lookup the
                    # fact search made, reused)
                    row = wikidata_per_topic.setdefault(
                        topic.get("topic_id"), {"candidates": 0, "sent": 0, "network": 0})
                    row.update(item=wdr.get("item"), reason=wdr.get("reason"),
                               pieces=wdr.get("pieces") or 0,
                               sent=row["sent"] + (wdr.get("requests") or 0),
                               network=row["network"] + (wdr.get("network") or 0))
                vrec = check.get("vendor_page")
                if isinstance(vrec, dict):
                    # CF-0771: the posts read for the text, counted with the fact's
                    row = vendor_per_topic.setdefault(
                        topic.get("topic_id"), {"outcome": None, "where": None, "pages": [],
                                                "candidates": 0, "passing": 0,
                                                "sent": 0, "network": 0})
                    row["support_text"] = {"outcome": vrec.get("outcome"),
                                           "where": vrec.get("where"),
                                           "pieces": vrec.get("pieces") or 0}
                    row["sent"] += vrec.get("requests") or 0
                    row["network"] += vrec.get("network") or 0
                tv = check.get("tvmaze")
                if isinstance(tv, dict):
                    # CF-0636: TVmaze's requests, apart from Wikipedia's
                    tvmaze_per_topic[topic.get("topic_id")] = {
                        "sent": tv.get("requests") or 0, "network": tv.get("network") or 0,
                        "used": bool(tv.get("used"))}
                support_counts[check["state"]] = support_counts.get(check["state"], 0) + 1
                support_requests[0] += check.get("requests") or 0
                if check["state"] == support_text.STATE_NO_TEXT:
                    row = refusal_record(topic, SUPPORT_REFUSAL_CODE,
                                         support_text.refusal_reason(topic, check),
                                         probe=record)
                    row[SUPPORT_CHECK_KEY] = check
                    refused.append(row)
                    continue
                if check["state"] == support_text.STATE_UNREACHABLE:
                    notes.append(f"{topic.get('topic_id')}: support text unreachable "
                                 f"({check.get('detail')}) - carried without it; say so in "
                                 f"the stage report (CF-0551)")
            viable.append(topic)
        else:
            topic.pop(CANDIDATES_KEY, None)
            topic.pop(SEARCH_KEY, None)
            refused.append(refusal_record(topic, FACT_REFUSAL_CODE,
                                          fact_reason(record, checked, search),
                                          probe=record,
                                          candidates=checked[:fact_search.KEEP_MAX],
                                          search=search))

    # 3. the shortlist - cut on hype x pool (CF-0325) when the pool was asked
    viable, pool_block = rank_by_pool(viable, pool, notes)
    order = "by score x pool (CF-0325)" if (pool_block or {}).get("asked") else "by score"
    size = max(0, int(shortlist_size))
    shortlist, overflow = viable[:size], viable[size:]
    for rank, topic in enumerate(overflow, start=size + 1):
        row = refusal_record(
            topic, OVERFLOW_CODE,
            f"viable but past the shortlist: rank {rank} of {len(viable)} {order}, and the "
            f"channel's {SHORTLIST_KEY} is {size} (CF-0264). Not a fault of the topic - "
            f"unused reserve, and since CF-0313 the reserve is what refills a slot step 5b "
            f"empties", probe=topic.get("fact_probe"))
        # CF-0313: the rank as a number, and the topic itself - see RANK_KEY.
        row[RANK_KEY] = rank
        row[RESERVE_TOPIC_KEY] = copy.deepcopy(topic)
        refused.append(row)

    batch["topics"] = shortlist
    batch.setdefault("skipped_topics", []).extend(refused)
    counts = {}
    for row in refused:
        counts[row["reason_code"]] = counts.get(row["reason_code"], 0) + 1
    batch["selection"] = {
        "stage": STAGE, SHORTLIST_KEY: size, "scored": len(topics),
        "viable": len(viable), "carried": len(shortlist), "refused": counts,
        "fact_probe": {"source": answer.get("source"), "asked_at": answer.get("asked_at"),
                       "requests": answer.get("requests"), "limit": limit,
                       "probed": len(requests)},
        # CF-0323: which rule judged this batch, where that rule was loaded
        # from, and how many of the carried topics it settled. An unsettled
        # topic is one the source could not be asked about - the only kind the
        # writer's own lookup is still expected to judge later.
        DECISION_KEY: {"rule": fact_rule.RULE_ID, "version": fact_rule.RULE_VERSION,
                       "origin": fact_rule.ORIGIN,
                       "settled": sum(1 for t in shortlist
                                      if ((t.get("fact_probe") or {}).get(DECISION_KEY)
                                          or {}).get("settled")),
                       "unsettled": sum(1 for t in shortlist
                                        if not ((t.get("fact_probe") or {}).get(DECISION_KEY)
                                                or {}).get("settled")),
                       "refused": counts.get(FACT_REFUSAL_CODE, 0),
                       "switch": "on" if enabled else "off",
                       # CF-0438: how many carried topics stand on a passing
                       # candidate, and which source list judged them.
                       "with_fact": sum(1 for t in shortlist
                                        if (t.get(SEARCH_KEY) or {}).get("passing")),
                       "sources_version": (sources or {}).get("version")},
    }
    # CF-0551: what the support-text pass found, and whether it ran at all.
    batch["selection"][SUPPORT_KEY] = {
        "asked": supporter is not None, "states": support_counts,
        "requests": support_requests[0],
        "refused": counts.get(SUPPORT_REFUSAL_CODE, 0),
        "carried_with_text": sum(1 for t in shortlist
                                 if support_text.has_wikipedia_text(t.get(SUPPORT_KEY))),
        # CF-0771: carried on the company's own post, no article of their own
        "carried_with_vendor_text": sum(
            1 for t in shortlist if not support_text.has_wikipedia_text(t.get(SUPPORT_KEY))
            and support_text.has_vendor_text(t.get(SUPPORT_KEY)))}
    # CF-0559: Wikipedia requests per topic - the stage report gives them.
    networks = [w["network"] for w in wiki_per_topic.values()]
    batch["selection"][WIKIPEDIA_KEY] = {
        "counted": client is not None,
        "client": "shared/wikipedia/wikipedia_api.py",
        "cached": isinstance(getattr(client, "network", None), dict),
        "network": sum(networks),
        "sent": sum(w["fact_search"] + w["support_text"] for w in wiki_per_topic.values()),
        "topics": len(wiki_per_topic),
        "max_network_per_topic": max(networks) if networks else 0,
        "per_topic": wiki_per_topic}
    # CF-0636: TVmaze's requests per topic, counted apart from Wikipedia's
    # (only the topics about an episode ask it).
    tv_info = getattr(supporter, "tvmaze", None) or {}
    tv_networks = [w["network"] for w in tvmaze_per_topic.values()]
    batch["selection"][TVMAZE_KEY] = {
        "asked": bool(tv_info.get("asked")),
        "refusal": tv_info.get("refusal"),
        "client": "shared/tvmaze/tvmaze_api.py",
        "network": sum(tv_networks),
        "sent": sum(w["sent"] for w in tvmaze_per_topic.values()),
        "topics": len(tvmaze_per_topic),
        "used": sum(1 for w in tvmaze_per_topic.values() if w["used"]),
        "max_network_per_topic": max(tv_networks) if tv_networks else 0,
        "per_topic": tvmaze_per_topic}
    # CF-0637: Wikidata's requests per topic, counted apart from Wikipedia's
    # (one lookup a topic, the fact search's, reused by the support text).
    wd_info = getattr(supporter, "wikidata", None) or {}
    wd_rows = list(wikidata_per_topic.values())
    wd_networks = [w.get("network") or 0 for w in wd_rows]
    batch["selection"][WIKIDATA_KEY] = {
        "asked": bool(wd_info.get("asked")),
        "refusal": wd_info.get("refusal"),
        "client": "shared/wikidata/wikidata_api.py",
        "network": sum(wd_networks),
        "sent": sum(w.get("sent") or 0 for w in wd_rows),
        "topics": len(wd_rows),
        "used": sum(1 for w in wd_rows if w.get("candidates") or w.get("pieces")),
        "max_network_per_topic": max(wd_networks) if wd_networks else 0,
        "per_topic": wikidata_per_topic}
    # CF-0757: the companies' own pages, per topic that asked them
    v_rows = list(vendor_per_topic.values())
    v_networks = [w["network"] for w in v_rows]
    batch["selection"][VENDOR_KEY] = {
        "asked": vendor is not None,
        "client": "scripts/vendor_page.py",
        "network": sum(v_networks),
        "sent": sum(w["sent"] for w in v_rows),
        "topics": len(v_rows),
        "used": sum(1 for w in v_rows if w["passing"]),
        # CF-0771: topics whose support text is their company's post
        "text_used": sum(1 for w in v_rows if (w.get("support_text") or {}).get("pieces")),
        "max_network_per_topic": max(v_networks) if v_networks else 0,
        "per_topic": vendor_per_topic}
    if pool_block is not None:
        batch["selection"][POOL_KEY] = pool_block
    if published_block is not None:
        batch["selection"][published_before.SELECTION_KEY] = published_block
    return [], notes


# --------------------------------------------------------------------------
# CF-0823: the fact before the scoring search
# --------------------------------------------------------------------------

PRESCREEN_KEY = "prescreen"                  # batch["prescreen"] and topics[].prescreen
PRESCREEN_TASK = "CF-0823"
BEFORE_SCORING_KEY = no_fact_memory.BEFORE_SCORING_KEY
MEMORY_ROW_KEY = no_fact_memory.MEMORY_KEY
THIN_MEMORY_KEY = thin_pool_memory.MEMORY_KEY       # CF-0876


def is_unscored(topic):
    """A draft the scoring pass has not searched yet: no popularity score."""
    value = (topic.get("signal") or {}).get("popularity_score")
    return not (isinstance(value, (int, float)) and not isinstance(value, bool))


def prescreen_totals(block):
    """The ledger of every pre-scoring pass of the batch, and what it saved:
    each candidate refused before its scoring search (by the probe, or held
    back by the memory - in a pass or at the refill's pick) is one bare
    `search.list` the scoring article did not spend."""
    passes = block.get("passes") or []
    by_probe = sum(len(p.get("refused_by_probe") or []) for p in passes)
    by_memory = sum(len(p.get("held_by_memory") or []) for p in passes)
    at_pick = len(block.get("refill_memory_skipped") or [])
    # CF-0876: works the thin-pool memory held back, in a pass or at a pick
    by_thin = sum(len(p.get("held_by_thin_pool") or []) for p in passes)
    thin_pick = len(block.get("refill_thin_pool_skipped") or [])
    totals = {
        "prescreened": sum(int(p.get("drafts") or 0) for p in passes),
        "probed": sum(int(p.get("probed") or 0) for p in passes),
        "refused_by_probe": by_probe,
        "refused_by_memory": by_memory,
        "skipped_by_memory_at_refill": at_pick,
        "refused_by_thin_pool_memory": by_thin,
        "skipped_by_thin_pool_memory_at_refill": thin_pick,
        "passed": sum(len(p.get("passed") or []) for p in passes),
        "unsettled": sum(len(p.get("unsettled") or []) for p in passes),
    }
    totals["filtered_before_scoring"] = by_probe + by_memory + at_pick + by_thin + thin_pick
    totals["search_calls_saved"] = totals["filtered_before_scoring"]
    totals["api_units_saved"] = totals["search_calls_saved"] * PRESCREEN_UNITS_PER_SEARCH
    block["totals"] = totals
    block["summary_line"] = (
        f"fact before scoring ({PRESCREEN_TASK}): {totals['prescreened']} candidate(s) "
        f"pre-checked, {by_probe} refused by the probe, {by_memory + at_pick} held back by "
        f"the no_fact memory"
        + (f", {by_thin + thin_pick} held back by the thin-pool memory (CF-0876)"
           if by_thin + thin_pick else "")
        + f" - {totals['search_calls_saved']} scoring search call(s) not spent")
    return totals


#: the price of the scoring pass's bare search (search_quota.UNITS_PER_SEARCH)
PRESCREEN_UNITS_PER_SEARCH = 100


def prescreen_block(batch):
    block = batch.get(PRESCREEN_KEY)
    if not isinstance(block, dict):
        block = {"task": PRESCREEN_TASK, "passes": []}
        batch[PRESCREEN_KEY] = block
    block.setdefault("passes", [])
    return block


def prescreen_batch(batch, rss=None, probe=run_probe, limit=1, root=None, batch_dir=None,
                    finder=search_facts, sources=None, enabled=True, wiki_client=None,
                    text_feeds=None, vendor=None, memory=None, thin_memory=None):
    """The fact pass over the drafts the scoring has not searched yet
    (CF-0823), before their search is paid for. The scored topics of the
    batch are not touched. `memory` is the channel's `no_fact_memory.Memory`
    (None: no memory - what a test that has nothing to do with it passes);
    `thin_memory` is the channel's `thin_pool_memory.Memory` (CF-0876): a work
    refused `pool_too_thin` at 0 clean shots in its last days of batches, with
    no new source in the pool since, leaves as a `pool_too_thin` row
    (`thin_pool_memory`, `before_scoring: true`) without a probe or a search.

    The fact search is `select_batch`'s own, run over the drafts alone with no
    support text, no publish registry, no pool and no cut - so a candidate is
    refused here exactly when the full pass would refuse it for want of a
    fact, and for nothing else. Returns `(problems, notes)`; on a problem the
    batch is left as it was."""
    topics = batch.get("topics") or []
    drafts = [t for t in topics if is_unscored(t) and PRESCREEN_KEY not in t]
    if not drafts:
        return [], ["no unscored draft in topics[] - nothing to check before scoring "
                    "(CF-0823)"]
    problems = precheck(drafts)
    if problems:
        return problems, []
    held, held_thin, to_probe = [], [], []
    for topic in drafts:
        entry = memory.hit(topic) if memory is not None else None
        if entry is not None:
            held.append(no_fact_memory.remembered_refusal(topic, entry, memory.days))
            continue
        thin = thin_memory.hit(topic) if thin_memory is not None else None
        if thin is not None:
            held_thin.append(thin_pool_memory.remembered_refusal(topic, thin, thin_memory.days))
            continue
        to_probe.append(topic)
    notes, refused, passed = [], [], list(to_probe)
    selection = {}
    if to_probe:
        sub = {k: v for k, v in batch.items()
               if k not in ("topics", "skipped_topics", "selection", PRESCREEN_KEY)}
        sub["topics"] = list(to_probe)
        problems, notes = select_batch(
            sub, rss=rss, shortlist_size=len(to_probe), probe=probe, limit=limit, root=root,
            batch_dir=batch_dir, finder=finder, sources=sources, enabled=enabled, pool=None,
            published=None, supporter=None, wiki_client=wiki_client, text_feeds=text_feeds,
            vendor=vendor)
        if problems:
            return problems, notes
        passed = sub.get("topics") or []
        refused = sub.get("skipped_topics") or []
        selection = sub.get("selection") or {}
    for row in refused:
        row[BEFORE_SCORING_KEY] = True
    asked_at = (selection.get("fact_probe") or {}).get("asked_at")
    unsettled = []
    for topic in passed:
        decided = (topic.get("fact_probe") or {}).get(DECISION_KEY) or {}
        topic[PRESCREEN_KEY] = {"task": PRESCREEN_TASK, "passed": True,
                                "settled": bool(decided.get("settled")),
                                "asked_at": asked_at}
        if not decided.get("settled"):
            unsettled.append(topic.get("topic_id"))
    gone = {row.get("topic_id") for row in refused + held + held_thin}
    batch["topics"] = [t for t in topics if t.get("topic_id") not in gone]
    batch.setdefault("skipped_topics", []).extend(held + held_thin + refused)
    block = prescreen_block(batch)
    if memory is not None:
        block["memory"] = memory.block()
    if thin_memory is not None:
        block[THIN_MEMORY_KEY] = thin_memory.block()
    block["passes"].append({
        "asked_at": asked_at, "drafts": len(drafts), "probed": len(to_probe),
        "held_by_memory": [{"topic_id": r.get("topic_id"), "name": r.get("title"),
                            "refused_at": r[MEMORY_ROW_KEY].get("refused_at"),
                            "batch": r[MEMORY_ROW_KEY].get("batch"),
                            "subreason": r[MEMORY_ROW_KEY].get("subreason")} for r in held],
        "held_by_thin_pool": [{"topic_id": r.get("topic_id"), "name": r.get("title"),
                               "batch": r[THIN_MEMORY_KEY].get("batch"),
                               "refused_at": r[THIN_MEMORY_KEY].get("refused_at"),
                               "weak_shots": r[THIN_MEMORY_KEY].get("weak_shots"),
                               "refusals": len(r[THIN_MEMORY_KEY].get("refusals") or [])}
                              for r in held_thin],
        "refused_by_probe": [{"topic_id": r.get("topic_id"), "name": r.get("title"),
                              "subreason": no_fact_memory.subreason_of(r)} for r in refused],
        "passed": [t.get("topic_id") for t in passed],
        "unsettled": unsettled,
        "requests": {"fact_probe": (selection.get("fact_probe") or {}).get("requests"),
                     "wikipedia_network": (selection.get(WIKIPEDIA_KEY) or {}).get("network"),
                     "vendor_page_network": (selection.get(VENDOR_KEY) or {}).get("network")},
    })
    prescreen_totals(block)
    for row in held:
        notes.append(f"{row.get('topic_id')}: {row.get('title')!r} held back by the no_fact "
                     f"memory ({row[MEMORY_ROW_KEY].get('refused_at')}, "
                     f"{row[MEMORY_ROW_KEY].get('subreason')}) - not probed, not searched")
    for row in held_thin:
        notes.append(f"{row.get('topic_id')}: {row.get('title')!r} held back by the thin-pool "
                     f"memory (pool_too_thin at 0 clean shots in "
                     f"{row[THIN_MEMORY_KEY].get('batch')}) - not probed, not searched")
    for row in refused:
        notes.append(f"{row.get('topic_id')}: {row.get('title')!r} refused before scoring "
                     f"(no_fact, {no_fact_memory.subreason_of(row)}) - its search is not spent")
    return [], notes


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def check_batch(batch, rss=None, shortlist_size=DEFAULT_SHORTLIST_SIZE):
    """Is this artifact one this stage could have written? Every carried topic
    probed and usable, every person-topic on itself or on a work its own news named, every
    refusal with a code and a reason, and no topic both carried and refused."""
    problems = list(precheck(batch.get("topics") or []))
    problems += unscored_problems(batch.get("topics") or [])
    index = rss_index(rss)
    support_asked = bool(((batch.get("selection") or {}).get(SUPPORT_KEY) or {}).get("asked"))
    topics = batch.get("topics") or []
    if len(topics) > shortlist_size:
        problems.append(f"{len(topics)} topics carried, and the shortlist is {shortlist_size} "
                        f"({SHORTLIST_KEY}) - this stage no longer selects past it")
    scores = [rank_of(t) for t in topics]
    if scores != sorted(scores, reverse=True):
        problems.append("topics[] is not in descending score order - the shortlist is the "
                        "first N *by score* (CF-0264), score x pool where `pool` is written "
                        "(CF-0325)")
    for topic in topics:
        where = f"topic {topic.get('topic_id', '?')}"
        record = topic.get("fact_probe")
        if not isinstance(record, dict):
            problems.append(f"{where}: no fact_probe - a topic is selected only after the "
                            f"fact was asked for (CF-0264)")
            continue
        # CF-0323: judged by the rule, not by the record's `usable` flag - the
        # check has to refuse exactly the batch the pass above would not have
        # written, and a flag is the other implementation's conclusion.
        if CANDIDATES_KEY in topic:
            # CF-0438: judged by its checked candidates, as the pass judged it.
            # A batch written before CF-0438 has no candidates and is judged
            # by its probe below, as it was then.
            checked = topic.get(CANDIDATES_KEY)
            search = topic.get(SEARCH_KEY) or {}
            if not isinstance(checked, list):
                problems.append(f"{where}: {CANDIDATES_KEY} is not a list")
                continue
            for i, cand in enumerate(checked):
                missing = [k for k in fact_rule.CANDIDATE_KEYS
                           if not isinstance(cand, dict) or k not in cand]
                if missing or not isinstance(cand.get(fact_rule.CHECK_KEY), dict):
                    problems.append(f"{where}: {CANDIDATES_KEY}[{i}] lacks "
                                    f"{missing or [fact_rule.CHECK_KEY]} (CF-0438)")
            state = fact_rule.classify(fact_rule.answer_of_candidates(checked,
                                                                      search.get("error")))
            decided = record.get(DECISION_KEY) or {}
            if fact_rule.drops(state, decided.get("switch", "on") == "on"):
                problems.append(f"{where}: no candidate in {CANDIDATES_KEY} passes the fact "
                                f"rule and every source answered ({state}) - a topic with no "
                                f"fact is not selected")
        else:
            state = fact_rule.classify(fact_rule.answer_of_probe(record))
            if fact_rule.drops(state):
                problems.append(f"{where}: fact_probe.outcome is {record.get('outcome')!r} "
                                f"({state}) - a topic with no fact is not selected")
        if record.get("outcome") == OK_OUTCOME and not record.get("article"):
            problems.append(f"{where}: fact_probe says {OK_OUTCOME!r} but names no article - "
                            f"the writer has to read the same article this stage was answered "
                            f"from")
        if kind_of(topic) == PERSON_KIND:
            leads = leads_of_topic(topic, index)
            reason = person_work_problem(topic, leads)
            if reason:
                problems.append(f"{where}: {reason}")
        # CF-0551: when the pass read the support text, a carried topic has it
        # - or Wikipedia could not be asked, which is said, not hidden.
        if support_asked:
            check = topic.get(SUPPORT_CHECK_KEY)
            pieces = topic.get(SUPPORT_KEY)
            if not isinstance(check, dict) or not isinstance(pieces, list):
                problems.append(f"{where}: no {SUPPORT_KEY} / {SUPPORT_CHECK_KEY} - the pass "
                                f"read the support text and this topic carries none (CF-0551)")
            elif check.get("state") == support_text.STATE_NO_TEXT:
                problems.append(f"{where}: {SUPPORT_CHECK_KEY}.state is no_text - such a topic "
                                f"leaves with {SUPPORT_REFUSAL_CODE} (CF-0551)")
            elif (check.get("state") == support_text.STATE_OK
                  and not support_text.has_story_text(pieces)):
                problems.append(f"{where}: {SUPPORT_CHECK_KEY} says ok and {SUPPORT_KEY} has no "
                                f"Wikipedia text nor the company's own post - the news "
                                f"summaries alone are not support text (CF-0551, CF-0771)")
        # CF-0019: a mark that says "the same work, the same story" is a topic
        # the pass would have taken off.
        for entry in topic.get(published_before.MARK_KEY) or []:
            if isinstance(entry, dict) and published_before.drops(entry):
                problems.append(f"{where}: {published_before.MARK_KEY} says the same work and "
                                f"the same story as publish/{entry.get('video')} - such a "
                                f"topic leaves with {published_before.PUBLISHED_CODE} (CF-0019)")
    carried = {t.get("topic_id") for t in topics}
    skipped = batch.get("skipped_topics")
    if skipped is not None and not isinstance(skipped, list):
        return problems + ["skipped_topics is not a list"]
    for i, row in enumerate(skipped or []):
        ctx = f"skipped_topics[{i}]"
        if not isinstance(row, dict) or not row.get("topic_id"):
            problems.append(f"{ctx}: no topic_id")
            continue
        if not (row.get("reason") or "").strip():
            problems.append(f"{ctx} ({row['topic_id']}): no reason - a refusal without a "
                            f"reason is a silent loss")
        if not row.get("reason_code"):
            problems.append(f"{ctx} ({row['topic_id']}): no reason_code (shared/runlog/"
                            f"funnel.py FUNNEL_CODES)")
        # CF-0313. The reserve row is the one record another stage reads back
        # *into* the batch, so what it carries is checked - leniently, the way
        # CF-0297 and CF-0302 treat their own younger fields: a batch written
        # before CF-0313 carries no `topic` at all and is not red for it
        # (`footage_candidates.restore_reserve_topic` rebuilds what it can),
        # but a `topic` that is there and is about somebody else is a fault
        # nobody downstream could survive.
        if row.get("reason_code") == OVERFLOW_CODE and RESERVE_TOPIC_KEY in row:
            kept = row.get(RESERVE_TOPIC_KEY)
            if not isinstance(kept, dict):
                problems.append(f"{ctx} ({row['topic_id']}): {RESERVE_TOPIC_KEY} is not the "
                                f"topic record (CF-0313) - the reserve is put back into "
                                f"topics[] from it")
            elif kept.get("topic_id") != row["topic_id"]:
                problems.append(f"{ctx} ({row['topic_id']}): {RESERVE_TOPIC_KEY}.topic_id is "
                                f"{kept.get('topic_id')!r} - the kept record is another topic")
            elif not ((kept.get("title_ref") or {}).get("name") or "").strip():
                problems.append(f"{ctx} ({row['topic_id']}): {RESERVE_TOPIC_KEY} has no "
                                f"title_ref.name - a topic put back into the batch from this "
                                f"row would have nothing for compliance to judge")
        if (fact_rule.canonical_code(row.get("reason_code")) == FACT_REFUSAL_CODE
                and not row.get("fact_probe")):
            problems.append(f"{ctx} ({row['topic_id']}): {FACT_REFUSAL_CODE} must carry the "
                            f"probe's own answer - which article the search resolved to and "
                            f"what it said (CF-0264); a refusal nobody can audit is a topic "
                            f"that merely vanished")
        if (row.get("reason_code") == published_before.PUBLISHED_CODE
                and not any(isinstance(e, dict) and published_before.drops(e)
                            for e in row.get(published_before.MARK_KEY) or [])):
            problems.append(f"{ctx} ({row['topic_id']}): {published_before.PUBLISHED_CODE} "
                            f"must carry the published video it repeats under "
                            f"{published_before.MARK_KEY} - same work, same story (CF-0019)")
        if (row.get("reason_code") == SUPPORT_REFUSAL_CODE
                and not isinstance(row.get(SUPPORT_CHECK_KEY), dict)):
            problems.append(f"{ctx} ({row['topic_id']}): {SUPPORT_REFUSAL_CODE} must carry "
                            f"the support check it was refused on - what was asked and why "
                            f"there was no text (CF-0551)")
        if row["topic_id"] in carried:
            problems.append(f"{ctx} ({row['topic_id']}): also in topics[] - a topic is either "
                            f"carried or refused, not both")
    return problems


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _batch_path(arg):
    path = Path(arg).expanduser()
    return path / "01-trend-hunter.json" if path.is_dir() else path


def channel_of(batch, root=None):
    """The channel a batch belongs to, by its *current* id (CF-0197).

    The door of this stage. The `channel` field inside a batch file is frozen
    on the day the batch was written and is never rewritten - a batch from
    before CF-0180 carries the old id forever - so taking it at face value
    sends every lookup after it to `channels/<old id>.json`, which does not
    exist, and the stage silently falls back to its default shortlist size
    instead of reading the channel's. Resolved here as well as inside
    `channel_config_path()` (the same belt-and-braces as `score_candidates.py`)
    so that anything else this function's answer is handed to - a note, a
    runlog line, a path - already has the current name.

    CF-0213: a batch without a `channel` field is a refusal
    (`MissingChannelError`), never the first channel's.
    """
    # One statement, read and resolved together: the root's guard
    # (tests/test_former_channel_ids.py) holds a `.get("channel")` to a
    # resolver in the same statement.
    channel = (resolve_channel(batch.get("channel"), root=root)
               if str(batch.get("channel") or "").strip() else None)
    if channel is None:
        raise MissingChannelError(
            f"batch {batch.get('batch_id')!r} has no `channel` field; there is no "
            f"default channel (CF-0213) - the hunter writes it in step 7's schema")
    return channel


def channel_config_path(channel, root=None):
    root = Path(root) if root else factory_root()
    return root / "channels" / f"{resolve_channel(channel, root=root)}.json"


def shortlist_size_of(channel, root=None):
    """`scope.shortlist_size` from the channel config, or the default when the
    key (or the config) is not there. The config lives in the root repository
    and this stage only ever reads it."""
    try:
        config = json.loads(channel_config_path(channel, root).read_text())
    except (OSError, ValueError):
        return DEFAULT_SHORTLIST_SIZE, f"no channel config for {channel!r}"
    scope = config.get("scope") or {}
    if SHORTLIST_KEY not in scope:
        return DEFAULT_SHORTLIST_SIZE, (
            f"channels/{resolve_channel(channel, root=root)}.json has no scope.{SHORTLIST_KEY}; "
            f"using {DEFAULT_SHORTLIST_SIZE} (CF-0264 - the key is CF-0265's to add)")
    try:
        return int(scope[SHORTLIST_KEY]), None
    except (TypeError, ValueError):
        return DEFAULT_SHORTLIST_SIZE, f"scope.{SHORTLIST_KEY} is not a number; using default"


def refusal_enabled(channel, root=None):
    """`production_fact_refusal.enabled` of the channel config - the switch is
    the channel's, the rule is the root's. An absent block or config reads as
    on, as this stage has always dropped (CF-0264); the Content Researcher's
    fail-closed reader is the other end's business."""
    try:
        config = json.loads(channel_config_path(channel, root).read_text())
    except (OSError, ValueError):
        return True
    block = config.get("production_fact_refusal")
    if not isinstance(block, dict) or "enabled" not in block:
        return True
    return block.get("enabled") is True


def make_supporter(batch_dir, batch, wp=None, transport=None, client=None, root=None,
                   tm=None, tv_transport=None, tv_client=None,
                   wd=None, wd_transport=None, wd_client=None):
    """The CLI's support-text reader (CF-0551): the root's shared Wikipedia
    client, cached in `<batch>/work/wikipedia-cache/`, one client for the
    whole pass so the pacing is shared; air dates compared with the batch's
    own time. `client` is that client when the caller has built it already
    (CF-0559: the CLI hands the same one to the fact search).

    CF-0634: the feeds whose excerpt may be a support piece are the batch's
    channel's `channel_data.support_feed_urls` (`use: read_text`), asked once
    here. A channel whose sources break the AI-bot rule is refused there
    (`ChannelDataError`) - the stage stops rather than hand on an excerpt
    nobody cleared.

    CF-0636: TVmaze's episode descriptions, through the root's shared client
    (`_tvmaze.py`), cached in `<batch>/work/tvmaze-cache/`, its gate
    `source_gate.check` with the channel's fact-sources list - only when that
    list names the outlet `use: read_text`, `allowed`
    (`support_text.tvmaze_refusal`). A channel without it, or a list that
    cannot be read, asks TVmaze nothing: `supporter.tvmaze` says so (`asked`
    false and `refusal`) - not an outage. `tv_transport` / `tv_client` are the
    tests' seams (recorded answers; a test never goes to the network).

    CF-0637: Wikidata the same way (`_wikidata.py`, `<batch>/work/
    wikidata-cache/`, the gate the channel's list) - opened once a pass only
    when the list names the outlet `wikidata` `read_text` / `allowed`
    (`support_text.wikidata_refusal`), read for the outlet's `properties`.
    `supporter.wikidata_reader` is `(client, module, properties)` - the fact
    search's too (`select_batch` binds it), so a topic's item is looked up
    once; `supporter.wikidata` says whether it was asked. `wd_transport` /
    `wd_client` are the tests' seams."""
    if wp is None:
        from _wikipedia import wikipedia_api as wp
    channel = channel_of(batch, root=root)
    text_feeds = set(channel_data.support_feed_urls(channel, root=root))
    if client is None:
        client = support_text.client_for(batch_dir, wp, transport=transport)
    now = batch.get("generated_at")
    if tm is None:
        from _tvmaze import tvmaze_api as tm
    try:
        sources = channel_data.fact_sources(channel, root=root)
        refusal = support_text.tvmaze_refusal(sources, tm)
    except (channel_data.ChannelDataError, FileNotFoundError, RuntimeError,
            ValueError) as exc:
        sources, refusal = None, f"the channel's fact-sources list could not be read: {exc}"
    tv = None
    if refusal is None:
        tv = tv_client or support_text.tvmaze_client_for(batch_dir, tm, sources,
                                                         transport=tv_transport)
    if wd is None:
        from _wikidata import wikidata_api as wd
    wdc, wd_props = None, {}
    if sources is None:
        wd_refusal = refusal
    else:
        wd_refusal = support_text.wikidata_refusal(sources, wd)
        if wd_refusal is None:
            wd_props = wd.properties_of(support_text.wikidata_outlet(sources, wd))
            if not wd_props:
                wd_refusal = "the channel's wikidata outlet names no `properties` to read"
    if wd_refusal is None:
        wdc = wd_client or support_text.wikidata_client_for(batch_dir, wd, sources,
                                                            transport=wd_transport)

    def supporter(topic, record, leads, index):
        return support_text.support_topic(topic, record, client, wp, index=index,
                                          leads=leads, now=now, text_feeds=text_feeds,
                                          tv=tv, tm=tm if tv is not None else None,
                                          wdc=wdc, wd=wd if wdc is not None else None,
                                          wd_properties=wd_props,
                                          vendor_reader=supporter.vendor_reader)
    # CF-0771: bound by `select_batch` to its page client and the channel's
    # list when it has them; None reads no company post
    supporter.vendor_reader = None
    supporter.text_feeds = text_feeds
    supporter.tvmaze = {"asked": tv is not None, "refusal": refusal,
                        "client": "shared/tvmaze/tvmaze_api.py"}
    supporter.tv_client = tv
    supporter.wikidata = {"asked": wdc is not None, "refusal": wd_refusal,
                          "client": "shared/wikidata/wikidata_api.py",
                          "properties": list(wd_props)}
    supporter.wikidata_reader = (wdc, wd, wd_props) if wdc is not None else None
    return supporter


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    ap.add_argument("--rss", help="the fetch_rss_news.py output of this batch - the leads "
                                  "the person rule reads (headlines alone are read out of "
                                  "evidence.sources when this is not given)")
    ap.add_argument("--limit", type=int, default=1,
                    help="fact candidates to collect per topic (default 1: the question is "
                         "whether one exists)")
    ap.add_argument("--shortlist-size", type=int, default=None,
                    help=f"override scope.{SHORTLIST_KEY} from the channel config")
    ap.add_argument("--no-pool", action="store_true",
                    help="cut on the score alone, without asking the footage pool (CF-0325)")
    ap.add_argument("--no-published", action="store_true",
                    help="do not compare the topics with publish/ (CF-0019) - for replays only")
    ap.add_argument("--no-support", action="store_true",
                    help="do not read the topics' support text (CF-0551) - for replays only")
    ap.add_argument("--before-scoring", action="store_true",
                    help="CF-0823: the fact pass over the unscored drafts only, before their "
                         "scoring search - no support text, registry, pool or cut")
    ap.add_argument("--no-memory", action="store_true",
                    help="do not read or write the channel's no_fact memory (CF-0823), "
                         "nor read its thin-pool memory (CF-0876) - "
                         "for replays only")
    ap.add_argument("--write", action="store_true", help="write the selection into the batch file")
    ap.add_argument("--check", action="store_true", help="validate the batch's selection only")
    args = ap.parse_args(argv)

    path = _batch_path(args.batch)
    if not path.exists():
        print(f"no {path}", file=sys.stderr)
        return 2
    batch = json.load(open(path))
    rss = json.load(open(Path(args.rss).expanduser())) if args.rss else None
    try:
        channel_of(batch)
    except MissingChannelError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 2

    notes = []
    size = args.shortlist_size
    if size is None:
        size, note = shortlist_size_of(channel_of(batch))
        if note:
            notes.append(note)

    channel = channel_of(batch)
    memory = None
    if not args.check and not args.no_memory:
        try:
            config = json.loads(channel_config_path(channel).read_text())
        except (OSError, ValueError):
            config = None
        _, _, days_note = no_fact_memory.days_of(config)
        if days_note:
            notes.append(days_note)
        memory = no_fact_memory.load(factory_root(), channel, config,
                                     batch=path.parent.name)
    thin_memory = None
    if args.before_scoring and not args.check and not args.no_memory:
        # CF-0876: works the channel's earlier batches refused pool_too_thin
        # at 0 clean shots - read out of those batches, nothing is written
        _, _, thin_note = thin_pool_memory.days_of(config)
        if thin_note:
            notes.append(thin_note)
        thin_memory = thin_pool_memory.load(factory_root(), channel, config,
                                            batch=path.parent.name)
    skipped_before = len(batch.get("skipped_topics") or [])

    if args.check:
        problems = check_batch(batch, rss=rss, shortlist_size=size)
    elif args.before_scoring:
        from _wikipedia import wikipedia_api as wp
        wiki_client = support_text.client_for(path.parent, wp)
        vendor = vendor_page.client_for(path.parent)
        problems, filled = prescreen_batch(batch, rss=rss, limit=args.limit,
                                           batch_dir=path.parent,
                                           enabled=refusal_enabled(channel),
                                           wiki_client=wiki_client, vendor=vendor,
                                           memory=memory, thin_memory=thin_memory)
        notes.extend(filled)
        if problems:
            print("nothing was changed - the drafts cannot be judged as they stand",
                  file=sys.stderr)
        elif args.write:
            with open(path, "w") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        else:
            print(json.dumps({PRESCREEN_KEY: batch.get(PRESCREEN_KEY),
                              "skipped_topics": batch.get("skipped_topics")[skipped_before:]},
                             ensure_ascii=False, indent=2))
    else:
        pool = None if args.no_pool else pool_coverage.Pool.load(factory_root(),
                                                                 channel_of(batch))
        published = (None if args.no_published
                     else published_before.load_registry(factory_root()))
        # CF-0559: one shared Wikipedia client for the pass - the fact search
        # and the support text read through it and its cache, so a topic's
        # article is asked for once.
        from _wikipedia import wikipedia_api as wp
        wiki_client = support_text.client_for(path.parent, wp)
        supporter = (None if args.no_support
                     else make_supporter(path.parent, batch, wp=wp, client=wiki_client))
        # CF-0757: the companies' own pages, one client for the pass, cached
        # in the batch (a refill round reads none of them again)
        vendor = vendor_page.client_for(path.parent)
        problems, filled = select_batch(batch, rss=rss, shortlist_size=size, limit=args.limit,
                                        batch_dir=path.parent,
                                        enabled=refusal_enabled(channel_of(batch)), pool=pool,
                                        published=published, supporter=supporter,
                                        wiki_client=wiki_client, vendor=vendor)
        notes.extend(filled)
        if problems:
            print("nothing was changed - the batch cannot be judged as it stands",
                  file=sys.stderr)
        elif args.write:
            with open(path, "w") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        else:
            print(json.dumps({"selection": batch.get("selection"),
                              "topics": [{"topic_id": t.get("topic_id"),
                                          "title": (t.get("title_ref") or {}).get("name"),
                                          "fact_probe": t.get("fact_probe"),
                                          POOL_KEY: t.get(POOL_KEY),
                                          CANDIDATES_KEY: t.get(CANDIDATES_KEY)}
                                         for t in batch.get("topics") or []],
                              "skipped_topics": batch.get("skipped_topics")},
                             ensure_ascii=False, indent=2))

    if not args.check and not problems and args.write and memory is not None:
        # CF-0823: this pass's no_fact refusals, for the channel's next batches
        added = no_fact_memory.record(factory_root(), channel,
                                      (batch.get("skipped_topics") or [])[skipped_before:],
                                      path.parent.name)
        if added:
            notes.append(f"no_fact memory: {len(added)} refusal(s) recorded in "
                         f"{memory.path} for {memory.days} day(s) (CF-0823)")
    if args.before_scoring and not args.check:
        block = batch.get(PRESCREEN_KEY) or {}
        print(f"{path.name}: {block.get('summary_line', 'nothing pre-checked')}; "
              f"{len(problems)} problems", file=sys.stderr)
        for line in notes + problems:
            print(f"  {line}", file=sys.stderr)
        return 1 if problems else 0
    selection = batch.get("selection") or {}
    print(f"{path.name}: {len(batch.get('topics') or [])} topics carried of "
          f"{selection.get('scored', '?')} scored, shortlist {size}, "
          f"{len(batch.get('skipped_topics') or [])} refused, {len(problems)} problems",
          file=sys.stderr)
    for line in notes + problems:
        print(f"  {line}", file=sys.stderr)
    return 1 if problems else 0


@runlog.script(STAGE, "fact-probe", name="fact_probe_topics.py")
def cli(argv=None):
    """The command-line entry: main()'s return code becomes the exit code
    *inside* the run event, so a non-zero result is recorded as `failed`
    (CF-0107). Tests call main() directly and leave no event."""
    sys.exit(main(argv))


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
"""CF-0323: the fact refusal, as one rule instead of two.
CF-0438: any kind of fact, from a wide list of sources, checked against four
requirements - see the section "CF-0438: the fact itself" at the bottom.

The defect (grill of 2026-09-22). `no_production_fact` is the funnel's first
killer - 29 topics of 101 across ten instrumented runs. Two stages decide it:

  * Trend Hunter, at selection, on the probe's `usable` flag
    (`fact_probe_topics.py`, CF-0264) - before compliance and before a single
    second of footage is downloaded;
  * Content Researcher, after the footage is indexed, on its own reading of the
    channel's `production_fact_refusal` block
    (`agents/content-researcher/scripts/fact_refusal.py`, CF-0185).

The two were written six weeks apart from the same idea and are *not* the same
predicate (the differences are listed below). Whenever the cheap one is the
milder of the two, the difference is paid for in full: the topic passes
selection, compliance judges it, the indexer downloads and CLIPs its sources,
and the expensive one kills it afterwards. In the frozen corpus that is exactly
what `example-film/2026-09-16T2148Z` shows - 6 of its 8 downloaded sources
belonged to the three topics the researcher then refused.

This module is the rule itself, with no stage in it. Both ends call it and
neither spells the predicate again:

    state = classify(answer_of_probe(record))     # Trend Hunter, at selection
    state = classify(answer_of_lookup(lookup))    # Content Researcher, later
    drops(state, enabled=rule.enabled)            # the same answer for both

**Where the rule is meant to live.** Its home is the factory root's shared
layer (`<root>/shared/factrule/fact_rule.py`); this file is that module, and
`_factrule.py` next to it loads the root's copy when the root has one and this
one when it has not. The reason it is written here first is that the root and
the researcher are separate checkouts with their own sandboxes: this half lands
the rule and its caller, the next half moves this file to the root verbatim and
points `fact_refusal.py` at it. Until that happens the hunter judges by this
rule and the researcher by its own, which is the state the corpus was measured
in - so the loader says which copy answered (`ORIGIN`), and no reader has to
guess.

**The three states are the researcher's, name for name** (`fact_refusal.py`
STATE_FOUND / STATE_NOT_FOUND / STATE_UNREACHABLE / STATE_NO_RULE), because a
shared rule with its own vocabulary would be a third dialect rather than one
rule. `not_found` is the only state that drops a topic, and only with the
channel's switch on; an unreachable source never drops one in either switch
position - that is CF-0185's third state and this module refuses it explicitly
rather than by a config value alone.

**What the two implementations actually disagreed about**, and what this file
settles - each line is a topic the hunter carried and the researcher would kill,
or the reverse:

  1. `usable` was read off the probe's own answer instead of being derived.
     `fact_probe.py` sets `usable = has_fact`, and `has_fact` is
     `status == "ok"`. A record whose `usable` key is missing, null or stale -
     a batch written by an older probe, a record rebuilt by
     `footage_candidates.restore_reserve_topic` from a summary - read as false
     and took a topic off the batch with no outcome behind it. Here the state
     comes from `status` and `candidates`, which every record carries.
  2. The researcher drops on `status in not_found_statuses` **and** an empty
     `candidates` list; the hunter dropped on the status alone. The statuses
     `production_facts.py` can return with a non-empty candidate list is today
     the empty set (`wrong_article` is set before the candidates are collected
     and `no_candidates` means there were none), so this corner has cost
     nothing yet - but it is the one direction in which the hunter was the
     *stricter* of the two, and a rule that is strict by accident is a rule
     that drops a topic nobody decided to drop.
  3. `wrong_article` is one of the emptinesses in both, and in neither is it in
     the channel's `not_found.statuses`: the root's schema pins that list to
     the three names CF-0184 returned, so both ends add CF-0263's fifth answer
     themselves. Spelled once here (`STATUS_WRONG_ARTICLE`) instead of twice.
  4. `source_unreachable` - the one real difference in kind, and the only one
     the corpus can still produce. It is `usable` at the hunter (a Wikipedia
     outage must not empty a shortlist) and `found` at the researcher, but the
     researcher **re-asks**: its own lookup runs hours later, when the source
     may well answer, and the answer may be `no_article`. That topic passes
     selection, is indexed, and is killed afterwards - the whole defect of this
     task in one state. So this module marks it and only it as *unsettled*
     (`settled()` below): every other state is decided once, at the earliest
     stage that observed it, and is not to be judged a second time.

**Item 2 of the task - "not re-checked further down the pipeline" - is this
pair of functions.** `settled(state)` says whether the answer can still change;
`decision()` is the record a stage writes onto the topic saying which rule
judged it, in which state, and whether anything downstream may re-open it. A
topic carrying `settled: true` has been judged by this exact rule and a later
stage refusing it again is re-judging one question twice. A topic carrying
`settled: false` was never actually asked (the source was unreachable, or no
probe ran at all), and re-asking it later is the only honest thing to do.

Stdlib only - plus `sentences.py` beside it, loaded by path at import
(CF-0737) - no I/O, no config reading: the channel's switch and its code
strings are read by the caller and handed in. A rule that reached for a config
of its own would be a second reader of the same block.
"""

# The module's own name for itself, written onto every decision record. A stage
# that finds a decision from another version on a topic knows it is not looking
# at its own rule's answer.
RULE_ID = "production_fact_refusal"
RULE_VERSION = "CF-0438"

# Where this copy was loaded from. `_factrule.py` overwrites it with the root's
# path when the root has the module; left as-is it says the agent's own copy
# answered. Never a decision input - only something a report can print.
ORIGIN = "agents/trend-hunter/scripts/fact_rule.py"

# ---------------------------------------------------------------- the states
# fact_refusal.py's four names, character for character.
STATE_FOUND = "found"
STATE_NOT_FOUND = "not_found"
STATE_UNREACHABLE = "source_unreachable"
STATE_NO_RULE = "no_rule"
STATES = (STATE_FOUND, STATE_NOT_FOUND, STATE_UNREACHABLE, STATE_NO_RULE)

# ------------------------------------------------------------ the vocabulary
# What the lookup answers with (production_facts.py STATUS_*). The first is a
# fact; the next three are the channel block's `not_found.statuses`; the fifth
# is CF-0263's, which no channel may add to that list because the root's schema
# pins it - so both ends carry it themselves, and now in one place.
STATUS_OK = "ok"
NOT_FOUND_STATUSES = ("no_article", "no_section", "no_candidates")
STATUS_WRONG_ARTICLE = "wrong_article"

# How an answer says "we could not ask". `fact_probe.py` writes the state's own
# name as its outcome; `production_facts.py` raises and the caller builds a
# record with `error` on it.
UNREACHABLE_STATUSES = ("unreachable", STATE_UNREACHABLE)
UNREACHABLE_KEYS = ("unreachable", "error")

# The funnel's code for the loss (`shared/runlog/funnel.py` FUNNEL_CODES, and
# the channel block's `when_enabled.reason_code`). Spelled here so that the two
# stages cannot drift apart on the word either; a channel that renamed it would
# hand its own string in, the way it hands the switch in.
#
# CF-0438: the code is `no_fact` - the rule no longer asks for a production
# fact, it asks for any fact. Batches written before carry the old word, and
# every reader maps it through `canonical_code()`; the old word is never
# written again.
REFUSAL_CODE = "no_fact"
LEGACY_REFUSAL_CODES = ("no_production_fact",)
WARNING_CODE = "production_fact_not_found"


def canonical_code(code):
    """The code a reader counts under: `no_production_fact` (before CF-0438)
    reads as `no_fact`; every other code, and None, comes back as it went in."""
    return REFUSAL_CODE if code in LEGACY_REFUSAL_CODES else code


# --------------------------------------------------------------- the answers
def answer_of_probe(record):
    """A `fact_probe.py` record (CF-0263) as this rule reads it.

    `outcome` is the status and `candidates` is already a count. `usable` and
    `has_fact` are deliberately *not* read: they are the other implementation's
    conclusion, and reading a conclusion is how the two rules drifted."""
    record = record or {}
    return {"status": record.get("outcome"),
            "candidates": record.get("candidates") or 0,
            "error": record.get("detail") if record.get("outcome") in UNREACHABLE_STATUSES
            else None,
            "article": record.get("article")}


def answer_of_lookup(lookup, candidates_field="candidates"):
    """A `production_facts.py` result (or a `fact_refusal.py` lookup entry) as
    this rule reads it. `candidates_field` is the channel block's
    `not_found.candidates_field`, because that is where the researcher takes
    it from."""
    lookup = lookup or {}
    candidates = lookup.get(candidates_field)
    count = len(candidates) if isinstance(candidates, (list, tuple)) else (candidates or 0)
    error = None
    for key in UNREACHABLE_KEYS:
        if lookup.get(key):
            error = lookup[key]
            break
    article = lookup.get("article")
    if isinstance(article, dict):
        article = article.get("title")
    return {"status": lookup.get("status"), "candidates": count,
            "error": error, "article": article}


def is_unreachable(answer):
    """True when this answer says the source could not be asked - the state
    that never drops a topic and the only one that is not settled."""
    answer = answer or {}
    if answer.get("status") in UNREACHABLE_STATUSES:
        return True
    return bool(answer.get("error"))


# ------------------------------------------------------------------ the rule
def classify(answer, not_found_statuses=NOT_FOUND_STATUSES):
    """Which state this answer is in.

    `not_found_statuses` is the channel's list (`not_found.statuses`); the
    default is the three the root's schema pins. `wrong_article` is added to
    whatever list comes in, for the reason in the module docstring: a channel
    decides whether it refuses, not what the lookup's vocabulary is."""
    if answer is None:
        return STATE_UNREACHABLE      # nobody asked: not a topic without a fact
    if is_unreachable(answer):
        return STATE_UNREACHABLE
    empty = tuple(not_found_statuses or ()) + (STATUS_WRONG_ARTICLE,)
    if answer.get("status") in empty and not answer.get("candidates"):
        return STATE_NOT_FOUND
    return STATE_FOUND


def drops(state, enabled=True):
    """Whether this state takes the topic off the batch. Only `not_found`, and
    only with the channel's switch on. The unreachable source is refused here
    explicitly and not by a config value: it is the one thing the rule may
    never do."""
    if state != STATE_NOT_FOUND:
        return False
    return bool(enabled)


def usable(answer, enabled=True, not_found_statuses=NOT_FOUND_STATUSES):
    """The selection-side reading: may this topic stay on the batch? The exact
    complement of `drops(classify(...))`, so that the shortlist filter and the
    writer's refusal cannot answer one topic differently."""
    return not drops(classify(answer, not_found_statuses), enabled)


def settled(state):
    """Is this answer final - may a later stage stop asking?

    Everything but the unreachable source is. `source_unreachable` is the one
    state whose answer can change between two askings, so it is the one state a
    later stage is allowed - and required - to re-ask. This is item 2 of
    CF-0323: the check belongs to the earliest stage at which it is observable,
    and an observation that was never made is not one."""
    return state in (STATE_FOUND, STATE_NOT_FOUND)


def decision(state, stage, enabled=True, answer=None):
    """What a stage writes onto a topic after judging it: which rule answered,
    in which state, at which stage, and whether anything downstream may re-open
    the question.

    The record downstream reads is `settled`: true means this exact rule has
    already judged this topic and a second refusal for the same reason would be
    the same question asked twice, at a stage where the answer costs a full
    indexing run. False means the source could not be asked, and the topic is
    carried precisely so that someone asks again later."""
    record = {"rule": RULE_ID, "version": RULE_VERSION, "state": state,
              "decided_by": stage, "settled": settled(state),
              "drops": drops(state, enabled), "switch": "on" if enabled else "off"}
    if answer is not None:
        record["status"] = answer.get("status")
        record["candidates"] = answer.get("candidates") or 0
    return record


def judge(answer, stage, enabled=True, not_found_statuses=NOT_FOUND_STATUSES):
    """`(state, decision)` in one call - what both call sites actually want."""
    state = classify(answer, not_found_statuses)
    return state, decision(state, stage, enabled, answer)


def re_ask(decision_record):
    """Should this stage ask the source about a topic another stage already
    judged? Only when nothing settled it - no decision record at all (a batch
    written before this rule, or a topic nobody probed), or one whose state was
    `source_unreachable`.

    This is the function the Content Researcher calls before running its own
    lookup, and the whole of the saving: a topic the hunter settled is not
    looked up again, not refused again, and never pays for its own indexing to
    learn what was already known at selection."""
    if not isinstance(decision_record, dict):
        return True
    if decision_record.get("rule") != RULE_ID:
        return True
    return not decision_record.get("settled")


# ======================================================================
# CF-0438: the fact itself
# ======================================================================
# Grill 2026-09-29 ("формат канала и почему на фактах"). The format is "tell
# the story and warm it with a fact", and the kind of fact is not limited: a
# production detail, a box-office number, a casting story, a scandal, news
# about the people in it. What the fact is *for* is that the video is ours -
# authored, and so monetisable - and that is what the requirements below hold
# it to (Q4). Where it may come from is a config file, not this code (Q5) -
# the channel's (`channels/<id>/fact-sources.json`, CF-0561); the caller reads
# it (the root through `shared/channel_data.py` `fact_sources(channel)`, or
# `load_sources(path)`) and hands it in, the way the channel's switch is
# handed in. There is no common list (CF-0631).
#
# CF-0627 (CF-0561): the kinds of fact are channel data too. They are `kinds`
# of the channel's fact-sources list (`channels/<id>/fact-sources.json`, read
# by the root through `shared/channel_data.py` `fact_sources(channel)`), so the
# `sources` a caller hands in carries them, and `check_candidate(s)` read them
# from there - a list without `kinds` is refused (`kinds_of`), never judged by
# a default. `normalize_kind(kind, kinds)` takes the channel's kinds;
# `fact_record()` takes the kind the check settled (`check.kind`).
#
# The contract both stages share:
#
#   Trend Hunter (selection) - searches every source for candidates, then
#       checked = check_candidates(candidates, sources, news_text=<topic news>)
#       topic["fact_candidates"] = checked          # written into 01
#       state, decided = judge(answer_of_candidates(checked, error), STAGE)
#     and drops the topic only when `drops(state)`: no candidate passes and
#     nothing was unreachable.
#   Content Researcher (step 2) - reads `topic["fact_candidates"]` from 01 and
#     takes `best_candidate(checked)` instead of searching again; the fact it
#     writes into 03 is `fact_record(best)`, which carries `kind` on to the
#     publication record (CF-0440).
#
# A candidate is a dict:
#   text          the fact, one or two sentences, in the source's language
#   kind          one of the channel's `kinds` (anything else reads as "other")
#   source        the outlet's name as a reader would say it ("Variety")
#   url           where the fact is written - required
#   primary_url   the original, when `url` retells it (required on tier 2)
#   source_type   optional: "creator_interview" / "studio_press" - the two
#                 source kinds that are taken from any host (see the config)
#   quote         the direct speech, required for "creator_interview"
#   attribution   optional: who reported/said it ("Variety reported") - a
#                 fact about a real person needs it, or the text must say it
#   about_person  optional bool: a claim about a real person; defaults to
#                 True for the kinds in PERSON_KINDS
#   specifics     optional list: the number/name/date the finder saw in it
#   section       optional: the Wikipedia section, the article's rubric
# Unknown keys are kept as they are.
#
# CF-0660 (grill «Каналы ИИ и Наука» Q14: «a preprint without „not
# peer-reviewed“» is refused, so a preprint *with* it is a fact). An outlet of
# the channel's list may say `"preprint": true` - a preprint server, whose
# text has not been peer-reviewed. A candidate standing on one (its `url`, or
# its `primary_url`) passes as any other of its tier, and its check carries
# `needs_caveat: true` (the key is there only then), which `fact_record()`
# carries on into 03's `fact`. The caveat itself is the video's words, not
# the fact's: the script check (`shared/factrule/claims.py`,
# `preprint_without_caveat`) refuses a script whose `fact.needs_caveat` is
# true and whose narration and plate say nowhere that it is not
# peer-reviewed. A fact that needs no caveat ranks before one that does.
#
# CF-0566 (grill «Каналы ИИ и Наука» Q17, ExampleTech: «бенчмарк вендора -
# по данным X», «утечки только как цитата»). Two more flags of the same kind,
# both the channel's list's and both said by the video, not by the fact:
#   `attributed_kinds` - kinds (a subset of `kinds`) whose fact is its
#     publisher's own claim, a vendor's benchmark above all. A candidate of
#     one passes as any other and its check carries `needs_attribution: true`;
#     claims.py refuses the script (`fact_without_attribution`) unless its
#     narration or plate says whose claim it is («according to OpenAI»). It
#     ranks after a fact that needs no attribution.
#   `leaks_need_source: true` - every check of the channel carries
#     `leaks_need_source: true`, and claims.py refuses a sentence of the video
#     that tells a leak without naming who reported it (`leak_without_source`).
#     A leak itself is never the fact: it has no tier-1 original, so it fails
#     the source rule like any retelling without its primary.
# `fact_record()` carries both flags on into 03's `fact`.
#
# CF-0737 (`example-film/2026-10-13T1411Z`, Justice League). The hunter split
# «... it was announced that Example Studios had hired ...» at «Bros.»,
# and «In February 2007, it was announced that Example Studios» passed every
# requirement above. A fact is a whole sentence: one that ends on a title or
# an initial a name follows, or whose last "that" clause stops at a name with
# no verb, fails `cut_short`, and its check carries the reason under
# `cut_short` (the key is there only then). The two shapes are
# `sentences.cut_short` - the sentence rules of the whole factory, loaded by
# path from this file's own directory, so a repository that keeps a copy of
# this file keeps a copy of `sentences.py` beside it.

import importlib.util as _ilu
import json as _json
import re as _re
import sys as _sys
from pathlib import Path as _Path
from urllib.parse import urlsplit as _urlsplit


def _load_sentences():
    """`sentences.py` beside this file, by path (no bare import: the rule is
    loaded by path from every repository)."""
    path = _Path(__file__).resolve().with_name("sentences.py")
    name = "factory_sentences_cf0737@" + str(path)
    if name not in _sys.modules:
        spec = _ilu.spec_from_file_location(name, path)
        module = _ilu.module_from_spec(spec)
        _sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del _sys.modules[name]
            raise
    return _sys.modules[name]


_sentences = _load_sentences()

# The key of a channel's fact-sources list that holds its kinds of fact.
KINDS_KEY = "kinds"
KIND_OTHER = "other"
# The kinds that are by nature a claim about a real person: the Q4 rumour
# requirement applies to them unless the candidate says `about_person: false`.
PERSON_KINDS = ("scandal", "people_news")

CANDIDATE_KEYS = ("text", "kind", "source", "url")
CANDIDATE_OPTIONAL_KEYS = ("primary_url", "source_type", "quote", "attribution",
                           "about_person", "specifics", "section")
# The field of `01-trend-hunter.json` -> `topics[]` that carries the checked
# candidates, best first, and the key each candidate's verdict sits under.
CANDIDATES_FIELD = "fact_candidates"
CHECK_KEY = "check"
# What goes on from the chosen candidate into 03 and the publication record.
FACT_KEYS = ("text", "kind", "source", "url", "primary_url", "source_type",
             "quote", "attribution", "section", "tier", "needs_caveat",
             "needs_attribution", "leaks_need_source")
# CF-0660: the flag of an outlet of the list that is a preprint server, and
# the flag of a fact standing on one - the script must say it is not
# peer-reviewed (`shared/factrule/claims.py`).
PREPRINT_KEY = "preprint"
NEEDS_CAVEAT_KEY = "needs_caveat"
# CF-0566: the kinds of a channel's list whose fact is said as its owner's
# claim, the flag of such a fact, and the channel's flag that a leak is told
# only with its outlet named (`shared/factrule/claims.py` reads both flags).
ATTRIBUTED_KINDS_KEY = "attributed_kinds"
NEEDS_ATTRIBUTION_KEY = "needs_attribution"
LEAKS_NEED_SOURCE_KEY = "leaks_need_source"

SOURCE_TYPES = ("creator_interview", "studio_press")

# Why a candidate fails. A candidate passes with an empty list.
FAIL_NO_TEXT = "no_text"
FAIL_NO_URL = "no_url"
FAIL_SOURCE_BANNED = "source_banned"
FAIL_SOURCE_UNLISTED = "source_unlisted"
FAIL_TIER2_WITHOUT_PRIMARY = "tier2_without_primary"
FAIL_INTERVIEW_WITHOUT_QUOTE = "interview_without_quote"
FAIL_NO_SPECIFICS = "no_specifics"
FAIL_RETELLS_NEWS = "retells_news"
FAIL_PERSON_NOT_MAJOR_OUTLET = "person_not_major_outlet"
FAIL_PERSON_UNATTRIBUTED = "person_unattributed"
FAIL_CUT_SHORT = "cut_short"            # CF-0737: the sentence was cut short
FAIL_CODES = (FAIL_NO_TEXT, FAIL_NO_URL, FAIL_SOURCE_BANNED, FAIL_SOURCE_UNLISTED,
              FAIL_TIER2_WITHOUT_PRIMARY, FAIL_INTERVIEW_WITHOUT_QUOTE,
              FAIL_NO_SPECIFICS, FAIL_RETELLS_NEWS, FAIL_PERSON_NOT_MAJOR_OUTLET,
              FAIL_PERSON_UNATTRIBUTED, FAIL_CUT_SHORT)
# The key of a check that holds why its fact reads as cut short (CF-0737).
CUT_SHORT_KEY = "cut_short"

# "Adds what the news does not carry": at least this share of the fact's
# content words (and numbers) must be absent from the topic's news text.
RETELL_NOVEL_SHARE = 0.25

_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december",
           "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря")
_ATTRIBUTION = _re.compile(
    r"\b(reported|reports|reporting|said|says|told|according to|announced|"
    r"confirmed|stated|claimed|alleged|alleges|wrote|revealed|"
    r"сообщил\w*|сообщает|заявил\w*|по данным|по словам|рассказал\w*|"
    r"пишет|написал\w*|подтвердил\w*|утверждает|утверждал\w*)\b",
    _re.IGNORECASE)
_WORD = _re.compile(r"[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+", _re.UNICODE)
_STOP = frozenset("""the and that this with from for was were are has have had
its his her their they them been will would into over after before about
than then when which while also just more most such only film movie series
show season episode что это как для его она они был была были который
которая которые после перед также фильм сериал""".split())


# ---------------------------------------------------------------- the config
def load_sources(path):
    """A channel's source list (Q5) from its file, `channels/<id>/fact-
    sources.json` (CF-0561). There is no default and no common list
    (CF-0631): the caller names the channel's file. Raises FileNotFoundError
    when there is no file: a stage without the list has no rule to judge by
    and must say so, not judge by an empty one."""
    with open(_Path(path), encoding="utf-8") as fh:
        return _json.load(fh)


def validate_sources(cfg):
    """Problems with a source list, as sentences; empty when it is usable."""
    if not isinstance(cfg, dict):
        return ["the source list is not an object"]
    problems = []
    tiers = cfg.get("tiers")
    if not isinstance(tiers, dict) or not tiers.get("1"):
        problems.append("`tiers.1` is missing or empty")
        tiers = tiers if isinstance(tiers, dict) else {}
    seen = {}
    groups = list(tiers.items()) + [("do_not_take", cfg.get("do_not_take") or [])]
    for tier, rows in groups:
        if tier not in ("1", "2", "do_not_take"):
            problems.append(f"`tiers.{tier}`: only tiers 1 and 2 exist")
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("id") or not row.get("hosts"):
                problems.append(f"{tier}: an entry without `id` or `hosts`: {row!r}")
                continue
            for host in row["hosts"]:
                if host in seen:
                    problems.append(f"host {host!r} is listed twice ({seen[host]} and {tier})")
                seen[host] = tier
            if PREPRINT_KEY in row:
                if not isinstance(row[PREPRINT_KEY], bool):
                    problems.append(f"{tier}[{row['id']}]: `{PREPRINT_KEY}` is "
                                    f"{row[PREPRINT_KEY]!r}, not true or false")
                elif row[PREPRINT_KEY] and tier == "do_not_take":
                    problems.append(f"do_not_take[{row['id']}]: `{PREPRINT_KEY}` marks an "
                                    f"outlet a fact may stand on - a banned host is none")
                elif row[PREPRINT_KEY] and row.get("major_outlet"):
                    problems.append(f"{tier}[{row['id']}]: a `{PREPRINT_KEY}` server is not "
                                    f"a `major_outlet` - a claim about a real person does "
                                    f"not stand on text nobody has reviewed")
    for row in cfg.get("any_host") or []:
        if row.get("source_type") not in SOURCE_TYPES:
            problems.append(f"any_host: unknown source_type {row.get('source_type')!r}")
    try:
        kinds = kinds_of(cfg)
    except ValueError as exc:
        problems.append(str(exc))
        kinds = None
    if ATTRIBUTED_KINDS_KEY in cfg:
        attributed = cfg[ATTRIBUTED_KINDS_KEY]
        if not isinstance(attributed, list) or not all(isinstance(k, str) for k in attributed):
            problems.append(f"`{ATTRIBUTED_KINDS_KEY}` is not a list of kinds")
        elif kinds is not None and set(attributed) - set(kinds):
            problems.append(f"`{ATTRIBUTED_KINDS_KEY}` names kinds the list does not have: "
                            f"{sorted(set(attributed) - set(kinds))}")
    if LEAKS_NEED_SOURCE_KEY in cfg and not isinstance(cfg[LEAKS_NEED_SOURCE_KEY], bool):
        problems.append(f"`{LEAKS_NEED_SOURCE_KEY}` is {cfg[LEAKS_NEED_SOURCE_KEY]!r}, "
                        f"not true or false")
    return problems


def kinds_of(sources):
    """The channel's kinds of fact - `kinds` of its fact-sources list, as a
    tuple. Raises ValueError when the list has none: a channel that has not
    said what kinds of fact it tells has no rule to name a kind by, and must
    say so rather than have every fact read as `other`."""
    kinds = sources.get(KINDS_KEY) if isinstance(sources, dict) else None
    if not isinstance(kinds, (list, tuple)) or not kinds or not all(
            isinstance(k, str) and k.strip() for k in kinds):
        raise ValueError(f"the fact-sources list has no `{KINDS_KEY}` list of "
                         f"strings - the channel's kinds of fact (CF-0627)")
    return tuple(kinds)


def _split(url):
    try:
        parts = _urlsplit(url) if url else None
        return ((parts.hostname or "").lower(), (parts.path or "").lower()) if parts else ("", "")
    except ValueError:
        return "", ""


def _matches(host, hosts):
    return any(host == h or host.endswith("." + h) for h in hosts)


def source_of(url, sources):
    """Where this URL stands in the list: `{"id", "tier", "major_outlet",
    "preprint", "banned", "host"}`. `tier` is 1 or 2 for a listed host, None
    otherwise; `preprint` the outlet's CF-0660 flag; `banned` is the
    `do_not_take` entry's id, or None."""
    host, path = _split(url)
    out = {"id": None, "tier": None, "major_outlet": False, "preprint": False,
           "banned": None, "host": host}
    if not host:
        return out
    sources = sources or {}
    for row in sources.get("do_not_take") or []:
        if _matches(host, row.get("hosts") or []):
            within = row.get("path_contains")
            if not within or any(p in path for p in within):
                out["banned"] = row.get("id")
                return out
    for tier in ("1", "2"):
        for row in (sources.get("tiers") or {}).get(tier) or []:
            if _matches(host, row.get("hosts") or []):
                out.update(id=row.get("id"), tier=int(tier),
                           major_outlet=bool(row.get("major_outlet")),
                           preprint=row.get(PREPRINT_KEY) is True)
                return out
    return out


# ------------------------------------------------------------ the candidate
def attributed_kinds_of(sources):
    """CF-0566: the channel's kinds whose fact is said as its owner's claim
    (`attributed_kinds`), as a tuple; () when the list names none."""
    kinds = sources.get(ATTRIBUTED_KINDS_KEY) if isinstance(sources, dict) else None
    return tuple(k for k in kinds or () if isinstance(k, str))


def normalize_kind(kind, kinds):
    """Every fact has a kind (item 5 of CF-0438): one of the channel's `kinds`
    (CF-0627) as it is, anything else - missing, misspelt, new - as `other`."""
    kind = kind.strip().lower() if isinstance(kind, str) else ""
    return kind if kind in tuple(kinds) else KIND_OTHER


def has_specifics(text, specifics=None):
    """A number, a date or a name - not an opinion. The finder's own
    `specifics`, when given, count if they are really in the text."""
    text = text or ""
    low = text.lower()
    if specifics and any(isinstance(s, str) and s.strip() and s.strip().lower() in low
                         for s in specifics):
        return True
    if _re.search(r"\d", text):
        return True
    if any(_re.search(r"\b" + m + r"\b", low) for m in _MONTHS):
        return True
    # A proper name: a capitalised word that does not open a sentence.
    for sentence in _re.split(r"(?<=[.!?])\s+", text.strip()):
        words = _WORD.findall(sentence)
        if any(w[:1].isupper() and len(w) > 1 for w in words[1:]):
            return True
    return False


def _content_words(text):
    return {w.lower() for w in _WORD.findall(text or "")
            if w[0].isdigit() or (len(w) >= 4 and w.lower() not in _STOP)}


def retells_news(text, news_text):
    """True when the fact adds nothing the news does not already say: fewer
    than RETELL_NOVEL_SHARE of its content words are new. No news text -
    nothing to compare against - is never a retelling."""
    if not news_text:
        return False
    words = _content_words(text)
    if not words:
        return False
    novel = words - _content_words(news_text)
    return len(novel) / len(words) < RETELL_NOVEL_SHARE


def is_attributed(candidate):
    """"X сообщил, что…": the claim names who made it."""
    if (candidate.get("attribution") or "").strip():
        return True
    return bool(_ATTRIBUTION.search(candidate.get("text") or ""))


def about_person(candidate, kinds):
    """Is this a claim about a real person? The candidate's own flag when it
    has one, otherwise the kind decides (PERSON_KINDS) - the kind as the
    channel's `kinds` name it."""
    flag = candidate.get("about_person")
    if isinstance(flag, bool):
        return flag
    return normalize_kind(candidate.get("kind"), kinds) in PERSON_KINDS


def check_candidate(candidate, sources, news_text=None):
    """The requirements of Q4 against one candidate. Returns
    `{"passes", "failures", "kind", "tier", "source_id", "about_person"}`,
    and `needs_caveat: True` when the fact stands on a preprint (CF-0660),
    `needs_attribution: True` when its kind is one of the list's
    `attributed_kinds` and `leaks_need_source: True` when the list says so
    (CF-0566), `cut_short: <why>` when the text is a sentence cut short
    (CF-0737);
    `failures` holds codes from FAIL_CODES, in the order they were found.
    `sources` is the channel's fact-sources list; its `kinds` name the kind
    (`kinds_of` - a list without them raises ValueError)."""
    kinds = kinds_of(sources)
    candidate = candidate or {}
    fails = []
    text = (candidate.get("text") or "").strip()
    url = (candidate.get("url") or "").strip()
    stype = candidate.get("source_type")
    quote = (candidate.get("quote") or "").strip()
    here = source_of(url, sources)
    primary = source_of(candidate.get("primary_url"), sources) if candidate.get("primary_url") else None
    any_host = {r.get("source_type"): r for r in (sources or {}).get("any_host") or []}
    tier = here["tier"]

    if not text:
        fails.append(FAIL_NO_TEXT)
    # 1. a source with a link, from the list
    if not here["host"]:
        fails.append(FAIL_NO_URL)
    elif here["banned"]:
        fails.append(FAIL_SOURCE_BANNED)
    elif tier is None:
        if stype in any_host:
            tier = int(any_host[stype].get("tier") or 1)
            if any_host[stype].get("requires") == "quote" and not quote:
                fails.append(FAIL_INTERVIEW_WITHOUT_QUOTE)
        else:
            fails.append(FAIL_SOURCE_UNLISTED)
    elif tier == 2 and not (primary and primary["tier"] == 1):
        fails.append(FAIL_TIER2_WITHOUT_PRIMARY)
    # 2. specifics, not an opinion
    if text and not has_specifics(text, candidate.get("specifics")):
        fails.append(FAIL_NO_SPECIFICS)
    # 3. adds what the news does not carry
    if text and retells_news(text, news_text):
        fails.append(FAIL_RETELLS_NEWS)
    # 4. about a real person: not a rumour - a major outlet, "X reported that"
    person = about_person(candidate, kinds)
    if person:
        own_words = stype == "creator_interview" and bool(quote)
        major = here["major_outlet"] or bool(primary and primary["major_outlet"])
        if not major and not own_words:
            fails.append(FAIL_PERSON_NOT_MAJOR_OUTLET)
        if not own_words and not is_attributed(candidate):
            fails.append(FAIL_PERSON_UNATTRIBUTED)
    # 5. a whole sentence, not one cut at an abbreviation or an initial
    # (CF-0737) - last, where the hunter's `refuse_cut_facts` put it first
    cut = _sentences.cut_short(text) if text else None
    if cut:
        fails.append(FAIL_CUT_SHORT)
    out = {"passes": not fails, "failures": fails,
           "kind": normalize_kind(candidate.get("kind"), kinds),
           "tier": tier, "source_id": here["id"], "about_person": person}
    if cut:
        out[CUT_SHORT_KEY] = cut
    # CF-0660: a fact on a preprint - its own link or the original it retells -
    # is a fact only with "not peer-reviewed" in the video (claims.py).
    if here["preprint"] or bool(primary and primary["preprint"]):
        out[NEEDS_CAVEAT_KEY] = True
    # CF-0566: whose claim it is, and how a leak may be told, are the video's
    # words - claims.py holds the script to them.
    if out["kind"] in attributed_kinds_of(sources):
        out[NEEDS_ATTRIBUTION_KEY] = True
    if (sources or {}).get(LEAKS_NEED_SOURCE_KEY) is True:
        out[LEAKS_NEED_SOURCE_KEY] = True
    return out


def _rank(entry):
    check = entry.get(CHECK_KEY) or {}
    return (not check.get("passes"), bool(check.get(NEEDS_CAVEAT_KEY)),
            bool(check.get(NEEDS_ATTRIBUTION_KEY)), check.get("tier") or 9,
            not _re.search(r"\d", entry.get("text") or ""))


def check_candidates(candidates, sources, news_text=None):
    """Every candidate with its verdict under `check` and `kind` normalised,
    the passing ones first (no caveat needed before a preprint's, CF-0660; tier 1
    before tier 2; a number before none) - the
    list Trend Hunter writes into `topics[].fact_candidates`."""
    out = []
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        entry = dict(cand)
        entry[CHECK_KEY] = check_candidate(cand, sources, news_text)
        entry["kind"] = entry[CHECK_KEY]["kind"]
        out.append(entry)
    return sorted(out, key=_rank)


def best_candidate(checked):
    """The best passing candidate of a checked list, or None. Works on the
    list as read back from 01 - the order is re-established, not trusted."""
    passing = [c for c in checked or [] if (c.get(CHECK_KEY) or {}).get("passes")]
    return sorted(passing, key=_rank)[0] if passing else None


def answer_of_candidates(checked, error=None):
    """A checked list as `classify()` reads it. Any passing candidate is a
    fact (`ok`). None passing *and* a source that could not be asked
    (`error`) is `source_unreachable` - the topic is carried, not dropped.
    None passing with every source answered is `no_candidates` - the one
    answer that drops a topic, under REFUSAL_CODE."""
    passing = [c for c in checked or [] if (c.get(CHECK_KEY) or {}).get("passes")]
    if passing:
        return {"status": STATUS_OK, "candidates": len(passing), "error": None,
                "article": None}
    if error:
        return {"status": STATE_UNREACHABLE, "candidates": 0, "error": error,
                "article": None}
    return {"status": "no_candidates", "candidates": 0, "error": None, "article": None}


def fact_record(candidate, kinds=None):
    """What the chosen fact carries on into 03 and the publication record:
    the FACT_KEYS that are present, `kind`, `tier`, `needs_caveat`
    (CF-0660), `needs_attribution` and `leaks_need_source` (CF-0566) as the
    check settled them (`check.kind` is the channel's kind, CF-0627). A candidate the rule
    has not checked takes its kind from `kinds` (the channel's, when the
    caller hands them in) or, without them, keeps its own kind cleaned
    (`other` when it has none) - the stage that made it answers for it
    against its channel's kinds."""
    if not candidate:
        return None
    check = candidate.get(CHECK_KEY) or {}
    rec = {k: candidate[k] for k in FACT_KEYS if candidate.get(k) not in (None, "")}
    if check.get("kind"):
        rec["kind"] = check["kind"]
    elif kinds is not None:
        rec["kind"] = normalize_kind(candidate.get("kind"), kinds)
    else:
        kind = candidate.get("kind")
        rec["kind"] = (kind.strip().lower() if isinstance(kind, str) else "") or KIND_OTHER
    tier = check.get("tier")
    if tier:
        rec["tier"] = tier
    if check.get(NEEDS_CAVEAT_KEY):
        rec[NEEDS_CAVEAT_KEY] = True
    for key in (NEEDS_ATTRIBUTION_KEY, LEAKS_NEED_SOURCE_KEY):   # CF-0566
        if check.get(key):
            rec[key] = True
    return rec

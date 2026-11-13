#!/usr/bin/env python3
"""CF-0185 (part 2): what this stage does with a topic that has no fact.

CF-0183 made `production_fact` a required field of every script, CF-0184 built
the lookup that goes and finds one. This module is the third piece: the rule
that says what happens to a **topic** whose lookup came back empty. It is the
teeth behind the obligation - a channel that cannot refuse a topic has no
requirement either, only a wish.

**The rule lives in the channel config, not here.** `production_fact_refusal`
in `channels/<channel>.json` is where a channel says whether it refuses, in
what words, and what the refusal is called; this file only reads it and acts
on it. Reading goes through the root's own reader,
`patterns/validate_patterns.py::production_fact_refusal()`, and is
**fail-closed**: a block that is absent, illegal or switched off is no rule at
all and drops nothing. The safe direction here is *not refusing* - a reader
that treated an unparseable contract as a rule in force would take topics off
a batch on a text nobody could read.

**Three states, not two.** The distinction is the whole point of the design:

1. `not_found` - the source was asked and answered one of the emptinesses the
   block names (`not_found.statuses`), or CF-0263's `wrong_article` (see the
   constant below - it is one emptiness the channel block cannot name because
   the root's schema pins that list), with no candidates. Switch off: the
   topic goes on and the emptiness is recorded as a warning. Switch on: the
   topic leaves the batch through `skipped[]` with the block's own reason code
   and a `fact_lookup` that says what was asked and what came back.
2. `source_unreachable` - we could not ask at all (the lookup raised
   `WikipediaError`; its CLI exits 2 and prints `wikipedia unavailable`).
   **Never drops a topic, in either switch position** - the block pins
   `source_unreachable.drops_topic` to false, and this module refuses to drop
   on it even if some future block said otherwise. A run that could not ask
   must never look like a title with no facts.
3. `found` - the rule has nothing to say: a fact was found, or the emptiness
   is not one of the named ones (a lookup that was never run, a status the
   block does not name). The topic is written, `production_fact` is required
   of the script as before and `check_production_fact.py` judges it exactly as
   before. That check reads a script; this rule reads a topic.

**One rule, and a topic is judged by it once** (CF-0323, 2026-09-23). The
predicate above is no longer written in this file: it is
`<root>/shared/factrule/fact_rule.py`, and the Trend Hunter's selection filter
calls the same module with the same channel switch. That closes the two ways
the same question used to get two answers:

* the two stages read the emptiness differently (the hunter on the probe's own
  `usable` flag, this file on `status` plus the candidate list), so a topic the
  cheap stage carried could be killed here - after compliance had judged it and
  after the indexer had downloaded and CLIPped its footage. That is the defect
  the grill of 2026-09-22 measured: `no_production_fact` was the funnel's first
  killer, and in `example-film/2026-09-16T2148Z` three such topics had spent 6 of
  the batch's 8 indexed sources before this rule saw them;
* the same topic was asked about twice. The hunter now writes its answer onto
  the topic (`fact_probe.fact_rule`), and `fact_rule.re_ask()` says whether this
  stage may re-open it: `found` and `not_found` are settled - observed once, at
  the earliest stage where they were observable - and only `source_unreachable`
  (or no decision at all) is re-asked. **A topic the hunter settled is never
  refused here.** If our own lookup comes back empty for one, that is not a
  title without a fact, it is two askings of one article disagreeing hours
  apart, and it is recorded as a warning (`when_disabled.warning_code`, with the
  hunter's own decision record in the entry) while the topic goes on. The safety
  net is unchanged and is where it always was: `production_fact` stays a
  required field of every script and `check_production_fact.py` (CF-0183) judges
  the script that gets written.

**Codes are never spelled here.** `warning_code` and `reason_code` are taken
out of the block (`when_disabled` / `when_enabled`), and the statuses that
count as an emptiness out of `not_found.statuses`. The same goes for the
source: this module never names Wikipedia - it says `fact_source`, because the
source can change to the dumps or to something else entirely without this file
being touched.

**The empty-batch guard.** `empty_batch_guard.min_scripts_after_refusal` is
the one case the rule's own text says must not happen: the rule may not empty
a batch by itself. When refusals would leave fewer topics than that floor, the
plan comes back with `stop: True` - the stage writes no batch, writes the
skips with their codes and their `fact_lookup`, and says in its report that no
eligible title returned a fact, which is a statement about the **source**, not
about the topics. The CLI exits 1 in that case.

**It judges only the topics that reached this stage** (`CF-0287`). Since
`CF-0265` the batch is narrowed before the footage is fetched: the slice leaves
the reserve behind and the indexer drops what it could not index, and each of
those is written down once, by the indexer, in `01b-footage-index.json ->
skipped_topics[]`. A topic that never reached the writer is not the writer's to
explain a second time, so `--indexed` takes that file and drops those topics
from the judged set - without it the rule could ask `skipped[]` for a topic no
footage was ever fetched for, and `--check` would call its absence a defect.
`--cleared` does the same for the compliance verdict and stays for a batch with
no index beside it.

A verdict is no longer one of the ways a topic fails to reach this stage
(`CF-0318`, 2026-09-22). Until then the slice refused a `review` and the
indexer skipped it under `compliance_review`; now it takes a slot, is fetched
like any other topic, and **is owed a script here** - what it cannot do is be
uploaded without a human's signature, and that is written down at the upload,
not here (`PRODUCTION_VERDICTS` below). A batch frozen before that day still
carries `compliance_review` entries in its `skipped_topics[]`, and `--indexed`
still drops those topics on a replay: no footage was ever fetched for them, so
the rule would be inventing a defect by asking about them. The code is read
there, never written.

**And it judges the topics the reserve sent in** (`CF-0306`). A topic lost
after compliance frees its slot, and the indexer refills it from
`02-compliance-checker.json -> reserve[]`, fetching the substitute like any
other topic of the batch. `02` is not rewritten, so the substitute is in
`reserve[]` and not in `results[]`: reading `results[]` alone would leave a
topic that reached this stage with footage unjudged by the rule, and `--check`
would then call its `skipped[]` entry an entry for a topic nobody asked about.
The same `--indexed` file answers this too - `reserve_substitution.
substitutions[]`, the ones with `outcome: "sources"` - and the verdict comes
from `reserve[]`, where compliance wrote it.

Usage::

    # the switch as this checkout has it, over a lookup run
    python3 scripts/production_facts.py --from-batch <batch>/01-trend-hunter.json \
        --json > /tmp/lookups.json
    python3 scripts/fact_refusal.py --lookups /tmp/lookups.json \
        --channel <channel> --topics <batch>/01-trend-hunter.json \
        --cleared <batch>/02-compliance-checker.json \
        --indexed <batch>/01b-footage-index.json

    # the source could not be asked at all (that CLI exited 2)
    python3 scripts/fact_refusal.py --channel <channel> \
        --topics <batch>/01-trend-hunter.json --unreachable "wikipedia unavailable: ..."

    # after the batch is written: the rule's verdict against the file
    python3 scripts/fact_refusal.py --lookups /tmp/lookups.json --channel <channel> \
        --topics <batch>/01-trend-hunter.json --check <batch>/03-content-researcher.json

Exit codes: 0 - the stage proceeds; 1 - the guard stops the stage, or `--check`
found the written batch disagreeing with the rule; 2 - usage.

Stdlib only; no venv in this repository.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _factrule import fact_rule  # noqa: E402
from _channel_ids import channel_config_path  # noqa: E402
from check_narration_budget import find_root, validator  # noqa: E402

# CF-0323: the predicate below this line is not written here any more.
#
# It was, and the Trend Hunter's selection filter had its own reading of the
# same question, and the two were not the same rule: a topic the cheap stage
# carried and this one refused paid for compliance and for a full indexing run
# before anyone said no to it (grill of 2026-09-22; `example-film/2026-09-16T2148Z`
# spent 6 of its 8 downloaded sources on three such topics). The rule now lives
# once, at `<root>/shared/factrule/fact_rule.py`, with no stage and no config
# reading in it: the channel's switch and its statuses are handed in by the
# caller, which is this file's job and stays here. `scripts/_factrule.py`
# finds it the way `_runlog.py` finds the accounting library.
#
# What is re-exported below are names, not second definitions - every module
# and test that already says `fact_refusal.STATE_NOT_FOUND` keeps saying it,
# and there is exactly one string behind it.

# The three states. `FOUND` is the state in which this rule has nothing to
# say - a fact, or an emptiness the block does not name.
STATE_FOUND = fact_rule.STATE_FOUND
STATE_NOT_FOUND = fact_rule.STATE_NOT_FOUND
STATE_UNREACHABLE = fact_rule.STATE_UNREACHABLE
# No rule readable at all (absent, illegal or a root out of reach): every
# topic proceeds and nothing is recorded, because there is no code to record
# it under and inventing one here is exactly what the contract forbids. The
# shared rule carries this name too, and never returns it: no-rule is a fact
# about this stage's reading of a config, and the config reading is here.
STATE_NO_RULE = fact_rule.STATE_NO_RULE

# How a lookup says "I could not ask". `production_facts.py` raises
# `WikipediaError` and its CLI exits 2 rather than returning a status, so an
# unreachable source reaches this module as a lookup built by `unreachable()`
# below (or by the caller, with any of these markers).
UNREACHABLE_STATUSES = fact_rule.UNREACHABLE_STATUSES
UNREACHABLE_KEYS = fact_rule.UNREACHABLE_KEYS

# CF-0263, and the one exception to "codes are never spelled here".
#
# The lookup gained a fifth answer on 2026-09-17: `wrong_article` - it found
# an article, and the article is about something other than this topic
# (`Michael J. Fox` is a person; `Wren Hollow (film series)` is the films and
# not the Example Network series). For this rule that is an emptiness like the other
# three: no fact about *this* topic was found, and the grill that decided it
# said so in as many words ("для правила отказа он равен отсутствию факта").
#
# It is not added to the channel's `not_found.statuses` because that list is
# pinned by the root's own schema (patterns/validate_patterns.py
# FACT_REFUSAL_STATUSES) to exactly the three names CF-0184 returned, and a
# channel may not add to it - which is the right shape: a channel decides
# *whether* it refuses, not what the lookup's vocabulary is. Nothing in the
# root changes for this. The loss still leaves the batch under the block's own
# `when_enabled.reason_code` - the funnel's own word for it - and which of the
# emptinesses it was is in `fact_lookup.status` and in the sentence a human
# reads - so the refusal is still auditable and the funnel still has one code
# for it.
#
# CF-0323: because no channel may name it, both ends had to name it
# themselves, and for six weeks both did - one constant here and one in
# `fact_probe_topics.py`. The exception is now spelled once, in the shared
# rule, and this is the name that reads it.
STATUS_WRONG_ARTICLE = fact_rule.STATUS_WRONG_ARTICLE

# CF-0318 (2026-09-22): the verdicts of a topic this stage owes a script to -
# who gets MADE. `review` is in here since that day. Until then the name was
# `CLEARED_VERDICTS = ("clear", "caution")` and it answered two questions at
# once, because they had the same answer: who is written, and who may be
# uploaded. The user decided (grill of 2026-09-22, Q8) that **without a human's
# approval only the publication of a video is forbidden - the video itself must
# be made**, and the two answers parted. This file keeps the first one only.
#
# The second one does not live here at all, deliberately. A `review` topic is
# held at the upload, and where it is held is written down twice by
# `agents/compliance-checker/scripts/publication_hold.py`: a `publication_hold`
# block on the batch artifact's row, and a durable line in
# `publish/publication-holds.json` at the factory root, which is the authority
# and which outlives the batch directory. Nothing here reads the hold and
# nothing here should: this stage decides what to write, not what to upload, so
# a second spelling of `("clear", "caution")` in this file could only rot.
#
# The legal side is untouched. `review` is still `review`, still earned the
# same way, and still says a human has not signed off - CF-0318 moved what it
# blocks, not how hard it is to earn.
PRODUCTION_VERDICTS = ("clear", "caution", "review")

# CF-0323: where the stage that judged a topic first writes what the rule
# answered - on the probe's own record, under this key
# (`agents/trend-hunter/scripts/fact_probe_topics.py` DECISION_KEY, the same
# five letters, checked against it by tests/test_fact_refusal.py). It is the
# one thing this file reads out of `01-trend-hunter.json` that is not a title:
# `fact_rule.re_ask()` reads it and says whether this stage may ask the same
# question again. The key name is the wire between two stages and is spelled
# in both of them; the rule module itself carries no name for it, which is the
# one thing about CF-0323 left to tidy (see the task's record).
DECISION_KEY = "fact_rule"

# CF-0306: where the Footage Indexer writes the reserve topics it pulled in to
# fill a slot lost after compliance, and the one `outcome` that means the topic
# really arrived here with footage behind it. The other three outcomes - the
# indexer refused the substitute, the shortlist names no candidate list for it,
# or it was not walked at all - are a substitution that never became a topic of
# this batch. Their words are the indexer's vocabulary and are deliberately not
# copied here: one of them is spelled the same as a lookup status of this
# file's own rule, and the only outcome this file acts on is the one above.
SUBSTITUTION_KEY = "reserve_substitution"
SUBSTITUTION_ARRIVED = "sources"


# ============================================================ the rule
class Rule:
    """A channel's `production_fact_refusal` block, as this stage reads it.

    `enabled` is the root reader's answer, not this file's: it is True only
    when `production_fact_refusal(cfg)` handed the block back, which it does
    only for a legal block with the switch on. A legal block with the switch
    off still gives a Rule - the off position is not silence, it writes
    warnings - and an illegal one gives no Rule at all (`load_rule` returns
    None).
    """

    def __init__(self, block, enabled):
        self.block = block or {}
        self.enabled = bool(enabled)

    def _node(self, key):
        node = self.block.get(key)
        return node if isinstance(node, dict) else {}

    @property
    def fact_source(self):
        return self.block.get("fact_source") or "the fact source"

    @property
    def not_found_statuses(self):
        statuses = self._node("not_found").get("statuses")
        return tuple(statuses) if isinstance(statuses, list) else ()

    @property
    def candidates_field(self):
        return self._node("not_found").get("candidates_field") or "candidates"

    @property
    def warning_code(self):
        return self._node("when_disabled").get("warning_code")

    @property
    def reason_code(self):
        return self._node("when_enabled").get("reason_code")

    @property
    def unreachable_drops_topic(self):
        """What the block says about the unreachable source. Read and
        reported, never obeyed when it is true: `drops()` below refuses that
        state whatever the block says, and the root's schema pins it false."""
        return self._node("source_unreachable").get("drops_topic") is True

    @property
    def min_scripts(self):
        value = self._node("empty_batch_guard").get("min_scripts_after_refusal")
        return value if isinstance(value, int) and not isinstance(value, bool) else 1

    @property
    def position(self):
        return "on" if self.enabled else "off"


def load_rule(channel=None, root=None, cfg=None):
    """The rule in force for a channel, or None when there is none.

    None - meaning *no refusal and no warning* - when the root cannot be
    reached, the channel has no config, the block is absent, or the block does
    not pass the root's own schema. That is the fail-closed direction the
    contract asks for: an unreadable rule refuses nothing.

    `cfg` is the test seam: a config dict judged instead of the one on disk,
    so that either position of the switch can be exercised without moving the
    one the checkout is committed with.
    """
    module = validator(root)
    if module is None:
        return None
    if cfg is None:
        if not channel:
            # CF-0633: no channel named, no rule - the root holds no channel
            # to fall back to, and this function answers "nothing to read"
            # with None (fail-closed: an unreadable rule refuses nothing).
            return None
        # CF-0197: a former channel id resolves here, or an operator naming
        # the channel by its old name gets "no refusal rule" in silence -
        # this function answers a missing config with None, on purpose.
        path = channel_config_path(channel, Path(root or find_root()))
        if not path.exists():
            return None
        try:
            cfg = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
    if not isinstance(cfg, dict):
        return None
    block = cfg.get(module.FACT_REFUSAL_KEY)
    if not isinstance(block, dict):
        return None
    if module.validate_production_fact_refusal_block(cfg):
        return None                       # illegal block: no rule at all
    return Rule(block, module.production_fact_refusal(cfg) is not None)


# ============================================================ the three states
def topic_id(lookup):
    return lookup.get("topic_id")


def title_of(lookup):
    """The title the source was asked about, as a human reads it."""
    query = lookup.get("query") or {}
    name = query.get("name") or lookup.get("title") or "?"
    if query.get("season"):
        return f"{name} (season {query['season']})"
    if query.get("year"):
        return f"{name} ({query['year']})"
    return name


def is_unreachable(lookup):
    """True when this lookup says the source could not be asked."""
    return fact_rule.is_unreachable(fact_rule.answer_of_lookup(lookup))


def unreachable(topic, error):
    """A lookup entry for a title the source could not be asked about - what
    the caller builds when `production_facts.py` exited 2 and there is no
    result to read."""
    return {"topic_id": topic.get("topic_id"),
            "query": {"name": topic.get("name"), "year": topic.get("year"),
                      "season": topic.get("season")},
            "status": STATE_UNREACHABLE,
            "error": str(error),
            "candidates": []}


def classify(lookup, rule):
    """Which of the three states this lookup is in. Needs a rule: what counts
    as an emptiness is the block's list, never this file's."""
    if rule is None:
        raise ValueError("classify() needs a rule - the statuses that count as "
                         "'no fact' are the channel block's, not this module's")
    return fact_rule.classify(
        fact_rule.answer_of_lookup(lookup, rule.candidates_field),
        rule.not_found_statuses)


def drops(state, rule):
    """Whether this state takes the topic off the batch.

    Only `not_found`, and only with the switch on. The unreachable source is
    refused by the rule explicitly rather than by the block's value alone: it
    is the one thing the rule may never do, and the shared module says so in
    its own body, for both stages at once."""
    return fact_rule.drops(state, enabled=bool(rule and rule.enabled))


# ============================================================ what gets written
def _lookup_record(lookup, rule):
    """`fact_lookup`: what the source was asked and what it answered. The
    audit trail the root's contract requires on every skip carrying the
    block's refusal code - a refusal nobody can check afterwards is a topic
    that merely vanished."""
    query = lookup.get("query") or {}
    record = {"source": rule.fact_source,
              "asked": {"name": query.get("name"), "year": query.get("year"),
                        "season": query.get("season")},
              "status": lookup.get("status"),
              "candidates": len(lookup.get(rule.candidates_field) or [])}
    article = lookup.get("article")
    if article:
        record["article"] = article.get("title") if isinstance(article, dict) else article
    # CF-0263: which work the answer is actually about. `parent_work` says the
    # fact came from the parent the topic names, and the detail of a
    # `wrong_article` says why the article that was found is not this topic's
    # - without them a skip records a status and leaves the reader to guess
    # which article it was about.
    if lookup.get("parent_work"):
        record["parent_work"] = lookup["parent_work"]
    # CF-0828: a lookup that found no article because every candidate was a
    # disambiguation page says so in `sub_reason`; the status is unchanged.
    if lookup.get("sub_reason"):
        record["sub_reason"] = lookup["sub_reason"]
    detail = (lookup.get("article_check") or {}).get("detail")
    if detail:
        record["article_check"] = detail
    if lookup.get("error"):
        record["error"] = lookup["error"]
    # CF-0438: the answer was the hunter's candidates out of 01, not a new
    # asking - `source` above is then the block's name for the rule's source.
    if lookup.get("taken_from"):
        record["taken_from"] = lookup["taken_from"]
    if isinstance(lookup.get("requests"), int):
        record["requests"] = lookup["requests"]
    return record


def warning_entry(lookup, rule, state):
    """One entry of `warnings[]` - the topic goes on, the emptiness is on the
    record. Exactly the keys the block's `when_disabled.entry_keys` names."""
    if state == STATE_UNREACHABLE:
        detail = (f"{rule.fact_source} could not be asked about "
                  f"{title_of(lookup)!r}"
                  + (f": {lookup['error']}" if lookup.get("error") else "")
                  + ". Nothing is known about this title's facts - the source "
                    "was unreachable, which is not the same as a title with no "
                    "fact, and no topic is dropped for it in either switch "
                    "position.")
    else:
        detail = (f"{rule.fact_source} answered {lookup.get('status')!r} for "
                  f"{title_of(lookup)!r} with no candidates: no fact "
                  f"to write. The channel's refusal switch is off, so the topic "
                  f"is written anyway and this is the record of what it would "
                  f"have cost with the switch on.")
    return {"topic_id": topic_id(lookup),
            "warning_code": rule.warning_code,
            "detail": detail}


def settled_entry(lookup, rule, decided):
    """One entry of `warnings[]` for a topic the selection stage already
    settled (CF-0323) - the refusal this file would otherwise have issued,
    withheld and written down instead.

    It carries the block's `when_disabled.warning_code`, like every other
    warning, because the topic is in exactly that position: it proceeds, and
    the emptiness is on the record. What it adds is `fact_rule` - the decision
    the earlier stage wrote onto the topic - so that a reader can see that the
    question was asked before the footage was paid for, what was answered
    then, and why this stage did not answer it a second time."""
    detail = (f"{rule.fact_source} answered {lookup.get('status')!r} for "
              f"{title_of(lookup)!r} with no candidates, but this topic was "
              f"already judged at selection by the same rule "
              f"({decided.get('rule')} {decided.get('version')}, "
              f"{decided.get('decided_by')}) and settled as "
              f"{decided.get('state')!r} - the source answered "
              f"{decided.get('status')!r} then. The refusal is not issued here: "
              f"one question answered twice, hours apart, is a disagreement "
              f"between two askings of one article, not a title without a fact, "
              f"and the topic has already been paid for in footage by the time "
              f"this stage runs. The script still owes a fact and "
              f"check_production_fact.py still judges it (CF-0183).")
    return {"topic_id": topic_id(lookup),
            "warning_code": rule.warning_code,
            "detail": detail,
            "fact_rule": dict(decided)}


def skip_entry(lookup, rule):
    """One entry of `skipped[]` - the topic leaves the batch. Exactly the keys
    the block's `when_enabled.entry_keys` names, `fact_lookup` among them."""
    reason = (f"No fact found: {rule.fact_source} was asked about "
              f"{title_of(lookup)!r} and answered {lookup.get('status')!r} with "
              f"no candidates. The channel's refusal rule is on, so the topic "
              f"is dropped - no script was written for it and no footage was "
              f"read for it.")
    if lookup.get("off_scene_only"):
        reason += (f" Every candidate that passed the fact rule is about something "
                   f"other than the topic's scenes - another segment of the same "
                   f"broadcast, another topic's work, nobody of the scene "
                   f"({lookup.get('off_scene')} candidate(s), CF-0548): a fact about the "
                   f"neighbouring story is no fact for this one.")
    if lookup.get("status") == STATUS_WRONG_ARTICLE:
        detail = (lookup.get("article_check") or {}).get("detail")
        reason += (f" What it found is about a different work"
                   + (f" - {detail}" if detail else "")
                   + ": a fact off the wrong article passes every checker "
                     "downstream, so it counts here as no fact at all.")
    return {"topic_id": topic_id(lookup),
            "reason_code": rule.reason_code,
            "reason": reason,
            "fact_lookup": _lookup_record(lookup, rule)}


# ============================================================ the plan
def plan(lookups, rule, decisions=None):
    """What the rule makes of a batch's lookups.

    Returns a dict the stage acts on:

    ``rule``      `on` / `off` / None (no readable rule)
    ``states``    one `{topic_id, state, status}` per lookup, in order, with
                  `settled_by` on the ones an earlier stage had already judged
    ``warnings``  entries for `warnings[]` in 03-content-researcher.json
    ``skipped``   entries for `skipped[]` there
    ``proceed``   the topic ids that still get a script
    ``settled``   the topic ids carried because selection had settled them -
                  the refusals this stage withheld (CF-0323)
    ``stop``      True when the guard will not let the batch be written
    ``stop_reason``  the sentence that says so, or None

    `decisions` is `{topic_id: the decision record the earlier stage wrote}`,
    i.e. `fact_rule_decisions(01-trend-hunter.json)`. Its only effect is to
    withhold a refusal: a topic `fact_rule.re_ask()` calls settled is never
    dropped here, whatever our own lookup came back with, and the emptiness is
    written as a warning instead (see `settled_entry`). Without it - a batch
    written before CF-0323, or a caller that has no `01` to hand - every topic
    is judged exactly as it was before, which is the honest reading: nothing
    says the question was ever asked.

    The guard counts **topics the rule leaves**, which is the most scripts
    that could still come out of the batch; a batch that loses scripts later
    for other reasons is those checks' business, not this one's.
    """
    decisions = decisions or {}
    out = {"rule": None if rule is None else rule.position,
           "states": [], "warnings": [], "skipped": [], "proceed": [],
           "settled": [],
           "stop": False, "stop_reason": None,
           "min_scripts": rule.min_scripts if rule else None,
           "warning_code": rule.warning_code if rule else None,
           "reason_code": rule.reason_code if rule else None}
    for lookup in lookups:
        if rule is None:
            out["states"].append({"topic_id": topic_id(lookup),
                                  "state": STATE_NO_RULE,
                                  "status": lookup.get("status")})
            out["proceed"].append(topic_id(lookup))
            continue
        state = classify(lookup, rule)
        decided = decisions.get(topic_id(lookup))
        # CF-0323, item 2 of the task: the check belongs to the earliest stage
        # at which it is observable, and is not made a second time further down
        # the pipeline. `re_ask` is false only for a topic this exact rule
        # already settled - every state but `source_unreachable`, which is the
        # one answer that can change between two askings.
        settled = not fact_rule.re_ask(decided)
        row = {"topic_id": topic_id(lookup), "state": state,
               "status": lookup.get("status")}
        if settled:
            row["settled_by"] = decided.get("decided_by")
        out["states"].append(row)
        if state == STATE_FOUND:
            out["proceed"].append(topic_id(lookup))
            continue
        if drops(state, rule):
            # CF-0548: candidates that were there but are about no scene of the
            # topic are not "an article answering differently hours later" -
            # they are the hunter's own candidates, judged against the scenes
            # the hunter wrote after it settled. The refusal is issued.
            if settled and not lookup.get("off_scene_only"):
                # The refusal this stage would have issued, withheld: it was
                # answered before compliance and before the footage, and the
                # topic is here because that answer carried it.
                out["warnings"].append(settled_entry(lookup, rule, decided))
                out["settled"].append(topic_id(lookup))
                out["proceed"].append(topic_id(lookup))
                continue
            out["skipped"].append(skip_entry(lookup, rule))
            continue
        out["warnings"].append(warning_entry(lookup, rule, state))
        out["proceed"].append(topic_id(lookup))
    if out["skipped"] and len(out["proceed"]) < rule.min_scripts:
        out["stop"] = True
        out["stop_reason"] = (
            f"the refusal rule leaves {len(out['proceed'])} topic(s), under the "
            f"floor of {rule.min_scripts} this channel set "
            f"(empty_batch_guard.min_scripts_after_refusal): "
            f"{len(out['skipped'])} of {len(out['states'])} eligible title(s) "
            f"came back from {rule.fact_source} without a fact. That "
            f"is a statement about the source, not about the topics. The stage "
            f"stops here: the skips below are the record, and no batch of "
            f"nothing is written.")
    return out


def batch_fields(decision):
    """What the plan contributes to 03-content-researcher.json. `warnings` is
    written even when empty - `[]`, not a missing field - so that a batch says
    it had nothing to warn about rather than leaving it unanswerable."""
    return {"warnings": list(decision["warnings"])}


# ============================================================ the report
def report_lines(decision, rule):
    """The lines the stage prints for a human. The warnings are here by
    contract: the off position of the switch is visible in the report or it is
    not visible anywhere."""
    lines = []
    if decision["rule"] is None:
        lines.append("production fact refusal: no readable rule for this channel "
                     "- nothing is refused and nothing is warned about")
        return lines
    lines.append(
        f"production fact refusal: switch {decision['rule']} "
        f"({rule.fact_source}); {len(decision['states'])} topic(s) judged, "
        f"{len(decision['warnings'])} warning(s), {len(decision['skipped'])} "
        f"dropped, {len(decision['proceed'])} proceeding")
    if decision.get("settled"):
        lines.append(
            f"  KEPT {len(decision['settled'])} topic(s) were settled at "
            f"selection by the same rule and are not refused a second time "
            f"(CF-0323): {', '.join(decision['settled'])}. Each is a warning "
            f"below, with the decision that carried it.")
    for entry in decision["warnings"]:
        lines.append(f"  WARN {entry['topic_id']} [{entry['warning_code']}]: "
                     f"{entry['detail']}")
    for entry in decision["skipped"]:
        lines.append(f"  DROP {entry['topic_id']} [{entry['reason_code']}]: "
                     f"{entry['reason']}")
    if decision["stop"]:
        lines.append(f"  STOP {decision['stop_reason']}")
    return lines


# ============================================================ after the batch
def verify(decision, data):
    """Problems with a written batch, judged against the plan.

    What it catches is a stage that read the rule and then wrote something
    else: a warning that never reached `warnings[]`, a dropped topic that was
    written anyway or skipped under some other code, a refusal with no
    `fact_lookup` behind it. Returns a list of sentences; empty means the file
    says what the rule decided.
    """
    problems = []
    if decision["rule"] is None:
        return problems
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        problems.append("warnings: missing or not a list - a batch judged by the "
                        "refusal rule carries `warnings[]`, `[]` when there is "
                        "nothing to warn about (CF-0185)")
        warnings = []
    seen_warnings = {(w.get("topic_id"), w.get("warning_code")) for w in warnings
                     if isinstance(w, dict)}
    for entry in decision["warnings"]:
        if (entry["topic_id"], entry["warning_code"]) not in seen_warnings:
            problems.append(f"warnings: {entry['topic_id']} has no "
                            f"{entry['warning_code']!r} entry - the lookup came "
                            f"back empty and the batch does not say so")
    skipped = {s.get("topic_id"): s for s in data.get("skipped", [])
               if isinstance(s, dict)}
    written = {s.get("topic_id") for s in data.get("scripts", [])}
    for entry in decision["skipped"]:
        tid = entry["topic_id"]
        if tid in written:
            problems.append(f"scripts: {tid} was written, but the refusal rule "
                            f"drops it - a topic with no fact gets no "
                            f"script")
        skip = skipped.get(tid)
        if skip is None:
            problems.append(f"skipped: {tid} is not in `skipped[]` - a dropped "
                            f"topic leaves the batch visibly, with its code, "
                            f"never by quietly not being there")
            continue
        if skip.get("reason_code") != entry["reason_code"]:
            problems.append(f"skipped {tid}: reason_code is "
                            f"{skip.get('reason_code')!r}, the rule drops it as "
                            f"{entry['reason_code']!r}")
        if not skip.get("fact_lookup"):
            problems.append(f"skipped {tid}: no `fact_lookup` - what the source "
                            f"was asked and what it answered is what makes the "
                            f"refusal auditable afterwards")
    for tid in decision["proceed"]:
        skip = skipped.get(tid)
        if skip is not None and skip.get("reason_code") == decision["reason_code"]:
            problems.append(f"skipped {tid}: dropped as "
                            f"{decision['reason_code']!r}, but the rule does not "
                            f"drop it - only an emptiness the block names, with "
                            f"the switch on, does")
    return problems


# ============================================================ the CLI
def _read_json(path):
    if str(path) == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path).read_text())


def load_lookups(path):
    """The `--json` output of production_facts.py: a list of results, or an
    object with `results`."""
    data = _read_json(path)
    if isinstance(data, dict):
        data = data.get("results", [])
    if not isinstance(data, list):
        raise ValueError("lookups: expected a list of results (the --json "
                         "output of production_facts.py)")
    return data


def topics_of(path):
    """`[{topic_id, name, year, season}]` out of a 01-trend-hunter.json."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import production_facts
    return production_facts.topics_of_batch(path)


def fact_rule_decisions(path):
    """`{topic_id: decision}` out of a 01-trend-hunter.json - what the shared
    rule answered about each topic at selection (CF-0323).

    The hunter writes it onto the topic, under the probe's own record
    (`fact_probe.fact_rule`), because that is where the answer it was derived
    from lives; `selection.fact_rule` is the same thing counted up for the
    batch and is not read here. A batch written before CF-0323 carries none of
    this and the dict comes back empty, which is the right answer for it: the
    question was never asked, so nothing here was settled and `plan()` judges
    every topic itself."""
    data = _read_json(path)
    out = {}
    for topic in (data.get("topics") or ()):
        if not isinstance(topic, dict) or not topic.get("topic_id"):
            continue
        probe = topic.get("fact_probe")
        decided = probe.get(DECISION_KEY) if isinstance(probe, dict) else None
        if isinstance(decided, dict):
            out[topic["topic_id"]] = decided
    return out


def attach_topic_ids(lookups, topics):
    """Join lookups to topic ids by the title that was asked about -
    production_facts.py's result carries the query, not the topic."""
    by_name = {}
    for topic in topics:
        by_name.setdefault((topic.get("name") or "").strip().lower(), topic)
    out = []
    for lookup in lookups:
        lookup = dict(lookup)
        if not lookup.get("topic_id"):
            name = ((lookup.get("query") or {}).get("name") or "").strip().lower()
            topic = by_name.get(name)
            if topic:
                lookup["topic_id"] = topic.get("topic_id")
        out.append(lookup)
    return out


def compliance_verdicts(path):
    """`topic_id -> verdict` over the whole of `02-compliance-checker.json`.

    Both lists, because since CF-0265 compliance judges the entire shortlist
    and then cuts it: `results[]` are the topics the cut carried, `reserve[]`
    are the ones it judged just as carefully and held back. A reserve topic has
    a real verdict (`2026-09-21T0358Z` holds two `clear` ones) - it is held for
    want of a slot, not for want of a judgment."""
    data = _read_json(path)
    verdicts = {}
    for key in ("results", "reserve"):
        for row in (data.get(key) or ()):
            if isinstance(row, dict) and row.get("topic_id"):
                verdicts.setdefault(row["topic_id"], row.get("verdict"))
    return verdicts


def substituted_topic_ids(path):
    """The reserve topics that took the slot of a topic lost after compliance
    and arrived here with footage (CF-0306), read from
    `01b-footage-index.json -> reserve_substitution.substitutions[]`.

    Only `outcome == "sources"`: a substitution the indexer itself refused, one
    `01-trend-hunter.json` names no candidates for, or one it did not walk at
    all has no footage behind it and is no topic of this stage. Reserve the
    indexer never drew on stays out by construction - it is in `reserve[]` and
    in `remaining[]`, never in `substitutions[]`."""
    data = _read_json(path)
    block = data.get(SUBSTITUTION_KEY) or {}
    return [s.get("topic_id") for s in (block.get("substitutions") or ())
            if isinstance(s, dict) and s.get("topic_id")
            and s.get("outcome") == SUBSTITUTION_ARRIVED]


def cleared_topic_ids(path, indexed=None):
    """The topics this stage owes a script to - the only ones this rule judges
    (`applies_to` in the block).

    CF-0318: that is every verdict in `PRODUCTION_VERDICTS`, `review` included.
    The name of this function and of its `--cleared` flag is older than the
    rule it now reads: it is kept because it is the spelling in `SKILL.md`, in
    every run this stage has recorded, and in the root's own
    `tests/test_pipeline_contracts.py`, and renaming a flag would silently
    change behaviour in an orchestration nobody would think to reread. Read
    "cleared" as "cleared for production": a `review` topic gets a script and
    is held at the upload instead (see `PRODUCTION_VERDICTS` above). A topic
    with no verdict at all, or one `02` never judged, is still not written -
    the reader is fail-closed, as everything else in this file is.

    CF-0306: that is no longer `results[]` alone. When a topic is lost after
    compliance, the indexer refills its slot from `reserve[]` and fetches the
    substitute like any other topic of the batch - but `02` is not rewritten,
    so the substitute stays in `reserve[]` and never appears in `results[]`.
    Hand this the batch's `01b-footage-index.json` as `indexed` and those
    topics join the judged set, each with the verdict compliance gave it where
    it stands (`reserve[]`). A substitute `02` says nothing about at all is not
    judged here."""
    data = _read_json(path)
    out = [r.get("topic_id") for r in data.get("results", [])
           if r.get("verdict") in PRODUCTION_VERDICTS]
    if not indexed:
        return out
    verdicts = compliance_verdicts(path)
    for tid in substituted_topic_ids(indexed):
        if tid not in out and verdicts.get(tid) in PRODUCTION_VERDICTS:
            out.append(tid)
    return out


def topics_dropped_before_this_stage(path):
    """The topics the slice and the indexer took off the batch (CF-0265), read
    from `01b-footage-index.json -> skipped_topics[]`.

    They are accounted for there, under the indexer's own codes, and no
    footage was fetched for them; this stage never saw them, so the refusal
    rule has nothing to say about them and `skipped[]` of `03` does not carry
    them (CF-0287). A file with no `skipped_topics` drops nothing - an index
    written before the cut says nothing about what the cut took."""
    data = _read_json(path)
    return [e.get("topic_id") for e in (data.get("skipped_topics") or [])
            if isinstance(e, dict)]


def build_parser():
    parser = argparse.ArgumentParser(
        description="CF-0185: the channel's refusal rule applied to a batch's "
                    "production-fact lookups.")
    parser.add_argument("--lookups", help="the --json output of production_facts.py "
                                          "(`-` for stdin)")
    parser.add_argument("--channel", default=None,
                        help="channel id, i.e. channels/<id>.json (required, "
                             "CF-0633: the root holds no default channel)")
    parser.add_argument("--root", default=None, help="shorts-content-factory checkout")
    parser.add_argument("--topics", help="a 01-trend-hunter.json, to join lookups "
                                         "to topic ids")
    parser.add_argument("--cleared", help="a 02-compliance-checker.json - judge only "
                                          "the topics this stage owes a script "
                                          "to: `results[]` at `clear`, `caution` "
                                          "or `review` (CF-0318), plus the "
                                          "reserve topics `--indexed` says were "
                                          "substituted in (CF-0306)")
    parser.add_argument("--indexed", help="a 01b-footage-index.json - judge only "
                                          "the topics that reached this stage, "
                                          "i.e. without the ones its "
                                          "`skipped_topics[]` already accounts "
                                          "for (CF-0287), and with the reserve "
                                          "topics its `reserve_substitution` "
                                          "brought in (CF-0306)")
    parser.add_argument("--unreachable", metavar="MESSAGE",
                        help="the source could not be asked at all (production_facts.py "
                             "exited 2): every topic is carried as unreachable")
    parser.add_argument("--check", metavar="BATCH_FILE",
                        help="a written 03-content-researcher.json - does it say "
                             "what the rule decided")
    parser.add_argument("--json", action="store_true", help="the whole plan")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.lookups and not args.unreachable:
        build_parser().print_usage()
        print("give --lookups, or --unreachable when the source could not be asked",
              file=sys.stderr)
        return 2
    if not args.channel:
        # CF-0633: without a channel there is no rule to read, and a run that
        # silently refused nothing would look like a batch where every fact
        # was found.
        print("give --channel: the channel whose fact rule this batch runs under",
              file=sys.stderr)
        return 2
    if args.unreachable and not args.topics:
        print("--unreachable needs --topics: without a lookup file the titles "
              "come from the batch", file=sys.stderr)
        return 2
    topics = topics_of(args.topics) if args.topics else []
    if args.unreachable:
        lookups = [unreachable(topic, args.unreachable) for topic in topics]
    else:
        lookups = attach_topic_ids(load_lookups(args.lookups), topics)
    if args.cleared:
        wanted = set(cleared_topic_ids(args.cleared, args.indexed))
        lookups = [l for l in lookups if topic_id(l) in wanted]
    if args.indexed:
        gone = set(topics_dropped_before_this_stage(args.indexed))
        lookups = [l for l in lookups if topic_id(l) not in gone]
    rule = load_rule(channel=args.channel, root=args.root)
    # CF-0323: the same `--topics` file the ids were joined from carries what
    # the selection stage decided about each topic. No new flag for it: the
    # decision is written on the topic, and the topic file is already here.
    decisions = fact_rule_decisions(args.topics) if args.topics else {}
    decision = plan(lookups, rule, decisions)
    for line in report_lines(decision, rule):
        print(line)
    problems = []
    if args.check:
        problems = verify(decision, _read_json(args.check))
        for problem in problems:
            print(f"  FAIL {problem}")
        if not problems:
            print(f"  ok   {args.check}: the batch says what the rule decided")
    if args.json:
        print(json.dumps(decision, ensure_ascii=False, indent=1))
    return 1 if (decision["stop"] or problems) else 0


@runlog.script("content-researcher", "fact-refusal", name="fact_refusal.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event (1 = the guard stopped the stage or the written batch
    disagrees with the rule, 2 = usage), so a stage stopped by the guard is
    recorded as `failed` rather than as a quiet short batch (CF-0107)."""
    sys.exit(main())


if __name__ == "__main__":
    cli()

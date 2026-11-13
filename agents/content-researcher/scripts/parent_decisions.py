#!/usr/bin/env python3
"""CF-0312: which topics of a repeat batch the parent already decided, and
which of them the parent's decision still covers.

The hole
--------
A repeat batch re-runs a parent's topics in a directory of its own. Until this
script the rule was the one CF-0287 wrote for a repeat that starts at *this*
stage: `01`, `01b` and `02` are the parent's files copied across, so the pool
in front of the writer is byte for byte the parent's pool, and a topic the
parent already decided simply does not appear in the repeat's `03` - not as a
script and not in `skipped[]`. The root's contract test reads the repeat by the
mismatch between `03`'s `batch_id` and `02`'s, opens the parent's `03` and asks
nothing about a topic the parent's book answers for.

`example-film/2026-09-21T1541Z` is the repeat that rule does not fit. It is a
repeat **from the indexer**: only `01` and `02` are copies, and the Footage
Indexer ran again and wrote the repeat its own `01b`. Two things follow, and
both of them broke.

1. **The funnel has no parent.** `shared/runlog/funnel.py` reads one batch
   directory. Harbourlights (`lf-2026-09-21-002`) was left out of `03` under the
   old rule, and the funnel printed `unexplained 1 - 1 SILENT (no stage said
   why)` - a silent loss, which is the one thing DoD 1.4.4 p. 1 forbids. The
   contract test was happy at the same moment, because it alone knows how to
   find the parent. A record only one of the two readers can read is not a
   record.
2. **The pool is not the parent's any more.** A new indexing run means a new
   `sources_by_topic`: the pool-depth walk (CF-0304) may have deepened it and
   the source sieve (CF-0299) may have taken sources out of it. Of the seven
   topics `1541Z` indexed, five came out with a different set of canonical
   sources than `0358Z` gave them. A parent refusal that was *about the pool*
   - `pool_too_thin`, `no_second_source` - says nothing at all about a topic
   whose pool has changed underneath it. Harbourlights' pool happened to be
   identical (both of CF-0304's extra sources were refused by the sieve), and
   that identity was established by the operator reading two files side by
   side. That is the check this script makes machine work.

What it does
------------
For every topic in this batch's inbox it prints one line with one of five
verdicts, and with `--write` it writes the first of them into `03`:

* `decided_in_parent` - the parent's `03` refused this topic and this batch's
  canonical pool for it is the same set the parent had. The parent's decision
  stands, and it is written here as a `skipped[]` entry carrying **the parent's
  own code** plus a pointer to where the parent said it. No new code enters
  the vocabulary (`tests/test_pipeline_contracts.py` `SKIP_CODES`), and no
  reader needs to know this batch has a parent to read the entry.
* `pool_changed` - the parent decided it, and this batch indexed a different
  set of canonical sources for it. The parent's decision does **not** carry
  over; the topic is judged here, from scratch, like any other.
* `rule_changed` - the parent refused it under a code the rule no longer
  refuses on (`pool_too_thin`, CF-0330: the pool gates warn since the user's
  decision of 2026-09-23). Judged here, like `pool_changed` Also (CF-0807) a parent's
  `nothing_to_check` / `thin_scene` for a topic THIS batch's `01b` keeps on
  own graphics (`_own_graphic.kept_on_own_graphics`; the cadence gate's own
  `thin_scene`, which carries `anchor_cadence`, still carries over): a kept
  topic is never refused for want of a pool (CF-0806).
* `not_in_parent` - the parent's `03` has no record of the topic at all (a
  reserve topic the repeat promoted, a topic the parent never indexed). Judged
  here.
* `delivered_in_parent` - the parent *wrote a script* for it and the pool is
  unchanged. Nothing is written for this one and the script exits 4. There is
  no funnel code for "made in the parent batch" and this task does not add
  one: filing a shipped video under `held_back` is what `2026-09-20T1610Z`
  did, and it counts a delivered video as a loss. A topic the parent delivered
  must be taken off *before* this stage - it does not belong in the repeat's
  inbox - and that is a decision for the operator, not for this script.

Finding the parent
------------------
`batch-start --note` is prose and is not read here. The machine trace is the
one CF-0287 already found: a copied `01-trend-hunter.json` /
`02-compliance-checker.json` carries the **parent's** `batch_id` while the
directory it sits in is the repeat's. `1541Z` carries `2026-09-21T0358Z` in
both. So:

* `--parent <batch-id|dir>` wins when it is given;
* otherwise the trace is read, and `01` and `02` must agree - a directory
  whose two copied heads name two different batches is not something to guess
  about, and the script asks for `--parent` (exit 3);
* **with no trace and no flag the rule does not apply at all.** Every topic is
  judged here and nothing is written. A batch that is not demonstrably a repeat
  never borrows somebody's verdict.
* `--no-parent` sets a trace aside on purpose: a **re-run to check new code on
  the same material** (the orchestrator copies a closed batch's `01`/`02`/`01b`
  into a new directory so the writer and the editor write those topics again
  under today's rules). The copied heads still name the parent, and without the
  flag every topic the parent decided or delivered would be taken off - the
  2026-09-28T1112Z check of the 0929Z fixes came out with 0 scripts exactly so.
  With it every topic of the inbox is `judged_here_by_flag` (or `judged_here`
  if this batch's own `03` already has it), nothing is written from the parent
  and the run exits 0. It does not combine with `--parent`.

Usage::

    # what this batch's inbox owes, against the parent found in the trace
    python3 scripts/parent_decisions.py \\
        ~/shorts-content-factory/pipeline/example-film/2026-09-21T1541Z

    # the same, with the parent named by hand, and the records written
    python3 scripts/parent_decisions.py <batch-dir> \\
        --parent 2026-09-21T0358Z --write

    # a check re-run of a closed batch's topics under new code: borrow nothing
    python3 scripts/parent_decisions.py <batch-dir> --no-parent

Exit codes: 0 nothing owed, 1 records are owed and `--write` was not given,
3 the question could not be answered (files missing, the trace contradicts
itself), 4 a topic the parent delivered is sitting in this batch's inbox.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runlog import runlog  # noqa: E402
# One copy of the collapse, the Editor's own (CF-0080). Two sources are "the
# same source" here exactly when `check_two_sources.py` and `source_gate.py`
# say they are - a re-upload must not read as a pool that changed.
from check_two_sources import alias_map, canonical  # noqa: E402
import _gate_warning as gw  # noqa: E402
from _factrule import fact_rule  # noqa: E402
from merge_batch_file import dump, merge, write_atomically  # noqa: E402
from _channel_ids import channel_config_path, resolve_channel  # noqa: E402
# CF-0807 (the tail of CF-0806): a topic this batch's 01b keeps on own graphics
# is never refused for want of a pool - and a parent's such refusal is not
# borrowed either.
import check_own_graphic_skips as ogs  # noqa: E402
from _own_graphic import kept_on_own_graphics  # noqa: E402

EXIT_OK, EXIT_OWED, EXIT_CANNOT_ANSWER, EXIT_DELIVERED = 0, 1, 3, 4

BATCH_FILE = "03-content-researcher.json"
INDEX_FILE = "01b-footage-index.json"
COMPLIANCE_FILE = "02-compliance-checker.json"
TREND_FILE = "01-trend-hunter.json"

# The key that makes the entry self-sufficient: the parent's batch id, on the
# entry itself, so `shared/runlog/funnel.py` needs to know nothing about
# repeats to read it and the root's contract test needs no second file open.
PARENT_KEY = "decided_in_parent"
PARENT_REASON_KEY = "parent_reason"
PARENT_SCRIPT_KEY = "parent_script_id"
PARENT_POOL_KEY = "parent_pool"
# This batch's own measurement of the same pool, when its indexer made one
# (CF-0304). It is here so the record can be read without opening `01b`.
DEPTH_KEY = "pool_depth_here"
# `stage` in every other `skipped[]` entry this repo writes is the funnel's
# step, not the agent's name (`check_anchor_coverage.py` FUNNEL_STAGE and its
# three siblings). A parent-decided entry is a loss at the same step and says
# the same word.
FUNNEL_STAGE = "scripts"

DECIDED, POOL_CHANGED, NOT_IN_PARENT, DELIVERED, JUDGED_HERE = (
    "decided_in_parent", "pool_changed", "not_in_parent", "delivered_in_parent",
    "judged_here")
# CF-0330: a parent refusal under a code the rule has since stopped refusing
# on. It is judged here from scratch, like `pool_changed` - the verdict was
# about the gate, and the gate is not the same any more.
RULE_CHANGED = "rule_changed"
# `--no-parent`: the operator said this run borrows nothing from any parent
# (a check re-run of a closed batch's topics under new code). A verdict word
# only - it is printed, never written, so no code enters `SKIP_CODES`.
BY_FLAG = "judged_here_by_flag"


def rule_changed_codes():
    """The parent codes that no longer carry over (CF-0330). `pool_too_thin`
    is the code of the pool gates the user returned to a warning on
    2026-09-23: a parent that refused a topic as `pool_too_thin` did so under
    a rule that now lets the same topic through with a warning, so borrowing
    that refusal would re-impose the price the user did not sign. Empty when
    the gates are switched back (`_gate_warning.WARN_GATES`).
    `no_second_source` is deliberately not here: its gate follows the
    channel's `two_source_gate` mode, and the same code is also the Footage
    Indexer's for a topic that never got two sources at all."""
    return frozenset({"pool_too_thin"}) if gw.warns(gw.GATE_ANCHOR_POOL) else frozenset()

TASK = "CF-0312"


class CannotAnswer(Exception):
    """The question could not be put, which is never a verdict on a topic."""


# --------------------------------------------------------------------------
# the batch directory and its files
# --------------------------------------------------------------------------

def batch_dir(target):
    """The batch directory, whether the caller named it or named its `03`."""
    p = Path(target)
    return p.parent if p.suffix == ".json" else p


def batch_name(batch_id):
    """The directory name inside a `batch_id`. The stages do not agree on the
    shape - `02` writes `2026-09-21T0358Z` and `03` writes
    `example-film/2026-09-21T0358Z` - and this is the root contract test's own
    `_batch_name()`, so both readers cut the same way."""
    return str(batch_id or "").rstrip("/").split("/")[-1]


def read_json(path, required=True):
    path = Path(path)
    if not path.exists():
        if required:
            raise CannotAnswer(f"{path} is not there")
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError as exc:
        raise CannotAnswer(f"{path} is not readable JSON: {exc}")


# --------------------------------------------------------------------------
# who the parent is
# --------------------------------------------------------------------------

def parent_from_trace(directory):
    """`(parent name, the sentence about how it was found)`.

    The parent name is `None` when this directory carries no trace of one -
    which is the common case and not an error: an ordinary batch's `01` and
    `02` name the directory they sit in.
    """
    here = Path(directory).name
    named = {}
    for fname in (COMPLIANCE_FILE, TREND_FILE):
        path = Path(directory) / fname
        if not path.exists():
            continue
        name = batch_name(read_json(path).get("batch_id"))
        if name:
            named[fname] = name
    if not named:
        raise CannotAnswer(
            f"neither {COMPLIANCE_FILE} nor {TREND_FILE} is in {directory} with a "
            f"`batch_id` - there is nothing here to read a parent out of; name one "
            f"with --parent or run without it and judge every topic here")
    carried = {n for n in named.values() if n != here}
    if not carried:
        return None, (f"no parent: {', '.join(sorted(named))} carry this batch's own id "
                      f"({here}), so this is not a repeat of anything")
    if len(carried) > 1:
        raise CannotAnswer(
            "the copied heads of this batch name two different parents - "
            + "; ".join(f"{f} says {n}" for f, n in sorted(named.items()))
            + ". Nothing is guessed from that: name the parent with --parent")
    parent = carried.pop()
    disagreeing = sorted(f for f, n in named.items() if n != parent)
    if disagreeing:
        raise CannotAnswer(
            f"{', '.join(disagreeing)} carry this batch's own id ({here}) while "
            + "; ".join(f"{f} says {n}" for f, n in sorted(named.items()) if n == parent)
            + f". A half-copied head is not a trace to trust: name the parent with --parent")
    return parent, (f"parent {parent}, read off the copied "
                    f"{', '.join(sorted(named))} (their `batch_id` is the parent's, "
                    f"this directory is {here})")


def resolve_parent(directory, flag=None):
    """`(parent directory or None, the sentence)`. The flag wins over the
    trace; with neither, the rule does not apply."""
    directory = Path(directory)
    if flag:
        name = batch_name(flag) if "/" not in str(flag).rstrip("/") else None
        path = Path(flag) if name is None else directory.parent / name
        if not path.is_dir():
            raise CannotAnswer(f"--parent {flag}: {path} is not a directory")
        return path, f"parent {path.name}, named with --parent"
    name, why = parent_from_trace(directory)
    if not name:
        return None, why
    path = directory.parent / name
    if not path.is_dir():
        raise CannotAnswer(
            f"{why}, but {path} is not on this disk. The parent's own `03` is where "
            f"its decisions are: fetch the batch or judge every topic here")
    return path, why


# --------------------------------------------------------------------------
# the inbox, and the pool of a topic
# --------------------------------------------------------------------------

def rows(data, key):
    value = data.get(key)
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def substituted_ids(index):
    """CF-0306: the reserve topics the indexer promoted into a freed slot and
    got footage for. They are in the inbox although `02` never heard of them."""
    subs = (index.get("reserve_substitution") or {}).get("substitutions")
    return {s["topic_id"] for s in (subs if isinstance(subs, list) else [])
            if isinstance(s, dict) and s.get("topic_id") and s.get("outcome") == "sources"}


def inbox(compliance, index):
    """The topics this stage owes an answer for, by the root contract's own
    arithmetic (`check_researcher_accounts_for_every_topic`): everything `02`
    judged, plus the substitutions, minus the topics `01b` took off."""
    subs = substituted_ids(index)
    eligible = {r["topic_id"] for r in rows(compliance, "results") if r.get("topic_id")} | subs
    refused_before = {r["topic_id"] for r in rows(index, "skipped_topics")
                      if r.get("topic_id") and r["topic_id"] not in subs}
    return eligible - refused_before


def pool_of(index, topic_id):
    """The set of canonical sources this batch indexed for the topic, or
    `None` when the topic is in no `sources_by_topic` at all.

    `None` and `set()` are two different answers and the difference matters: a
    topic the parent never indexed has no pool to compare against, while a
    topic whose every source the sieve took out has an empty one.
    """
    by_topic = index.get("sources_by_topic")
    if not isinstance(by_topic, dict) or topic_id not in by_topic:
        return None
    ids = by_topic.get(topic_id)
    aliases = alias_map(index)
    return {canonical(str(v), aliases) for v in (ids if isinstance(ids, list) else []) if v}


def show_pool(pool):
    if pool is None:
        return "no pool"
    return ", ".join(sorted(pool)) if pool else "empty pool"


# The parent codes that are a verdict on the *footage*, not on the writing.
# They are the ones a re-indexing run can invalidate without changing which
# sources the topic has, so they get the second look below.
POOL_CODES = ("pool_too_thin", "no_second_source")


def depth_record(index, topic_id):
    """CF-0304's measurement of one topic's pool in `01b pool_depth.topics[]`,
    or `None` when this batch's indexer did not measure it (every batch before
    `2026-09-21T1541Z` has no such block at all).

    The same canonical sources are not the same pool: the sources are fetched
    again and indexed again, and the shots that survive the Editor's pre-cut
    gate are counted again. The set of sources is what CF-0299's sieve and
    CF-0304's walk actually move, which is why it is what this script compares
    - but where the indexer has also measured the depth, the measurement is
    read, because a pool that has since become deep enough is a pool the
    parent's `pool_too_thin` no longer describes.
    """
    depth = index.get("pool_depth")
    if not isinstance(depth, dict):
        return None
    for rec in depth.get("topics") or []:
        if isinstance(rec, dict) and rec.get("topic_id") == topic_id and rec.get("measured") is not False:
            return rec
    return None


# --------------------------------------------------------------------------
# the verdict, per topic
# --------------------------------------------------------------------------

def parent_records(parent_batch):
    """`{topic_id: (kind, entry)}` out of the parent's `03`, `kind` being
    `"skipped"` or `"scripts"`."""
    out = {}
    for key in ("scripts", "skipped"):
        for entry in rows(parent_batch, key):
            tid = entry.get("topic_id")
            if tid:
                out[tid] = (key, entry)
    return out


def judge(topic_id, here_index, parent_index, parent_book, written_here):
    """One topic's verdict, as a dict ready to print and to write."""
    pool = pool_of(here_index, topic_id)
    parent_pool = pool_of(parent_index, topic_id)
    kind, entry = parent_book.get(topic_id, (None, None))
    rec = {"topic_id": topic_id, "pool": pool, "parent_pool": parent_pool,
           "parent_kind": kind, "parent_entry": entry}
    if topic_id in written_here:
        rec["verdict"] = JUDGED_HERE
        rec["note"] = "already written or skipped in this batch's own 03"
        return rec
    if kind is None:
        rec["verdict"] = NOT_IN_PARENT
        rec["note"] = ("the parent's 03 has no record of this topic - it is this "
                       "batch's to judge like any other")
        return rec
    if parent_pool is None or pool != parent_pool:
        rec["verdict"] = POOL_CHANGED
        rec["note"] = (f"the parent decided it on a different pool "
                       f"({show_pool(parent_pool)}) than this batch indexed "
                       f"({show_pool(pool)}) - its decision does not carry over "
                       f"and the topic is judged here from scratch")
        return rec
    depth = depth_record(here_index, topic_id)
    rec["depth"] = depth
    if (kind == "skipped" and entry.get("reason_code") in POOL_CODES
            and depth is not None and depth.get("deep_enough") is True):
        rec["verdict"] = POOL_CHANGED
        rec["note"] = (
            f"the parent refused it as `{entry.get('reason_code')}` and the sources are "
            f"the same ({show_pool(pool)}), but this batch's own indexer measured the pool "
            f"deep enough ({depth.get('usable_shots')} usable shot(s) against a floor of "
            f"{depth.get('floor')}, 01b pool_depth.topics[]) - the footage was indexed "
            f"again and the parent's verdict is no longer about it. Judged here")
        return rec
    if kind == "skipped" and ogs.is_barred(entry, kept_on_own_graphics(here_index)):
        # CF-0807: the parent's `nothing_to_check` / `thin_scene` (not the
        # cadence gate's own, which carries `anchor_cadence`) said "no pool";
        # this batch's 01b keeps the topic on own graphics (CF-0806), so the
        # refusal is not this batch's to copy - check_own_graphic_skips.py
        # would refuse the copy anyway.
        rec["verdict"] = RULE_CHANGED
        rec["note"] = (
            f"the parent refused it as `{entry.get('reason_code')}`, but this batch's "
            f"01b keeps the topic on its own graphics (own_graphic_footing.kept[] / "
            f"two_source_floor.kept_on_own_graphics, CF-0806) - a kept topic is never "
            f"refused for want of a pool, so the parent's verdict does not carry over "
            f"and the topic is judged here (CF-0807)")
        return rec
    if kind == "skipped" and entry.get("reason_code") in rule_changed_codes():
        rec["verdict"] = RULE_CHANGED
        rec["note"] = (
            f"the parent refused it as `{entry.get('reason_code')}` on this same pool "
            f"({show_pool(pool)}), but that code is a warning now, not a refusal (CF-0330, "
            f"the user 2026-09-23) - the parent's verdict does not carry over and the topic "
            f"is judged here")
        return rec
    if kind == "scripts":
        rec["verdict"] = DELIVERED
        rec["note"] = (f"the parent wrote {entry.get('script_id') or 'a script'} for it on "
                       f"this same pool. There is no funnel code for a topic made in "
                       f"another batch and this stage will not invent one - take the topic "
                       f"off before the writer instead of filing a delivered video as a loss")
        return rec
    rec["verdict"] = DECIDED
    rec["note"] = (f"the parent refused it as `{entry.get('reason_code')}` on this same "
                   f"pool ({show_pool(pool)}) - the refusal stands and is recorded here"
                   + (f"; this batch's indexer measured that pool again and it is still "
                      f"under the floor ({depth.get('usable_shots')} usable shot(s) "
                      f"against {depth.get('floor')})"
                      if depth is not None and depth.get("deep_enough") is False else ""))
    return rec


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------

def skip_entry(rec, parent_name):
    """The `skipped[]` entry a `decided_in_parent` verdict writes.

    The parent's entry is copied whole and then added to, rather than picked
    over field by field. That is deliberate: the root's contract test asks
    `no_fact` for `fact_lookup` and `nothing_to_check` for
    `checked`, and a copy that kept only the three fields every entry has
    would be red under exactly the codes whose evidence matters most. What the
    parent wrote about this refusal is what this refusal is.
    """
    entry = dict(rec["parent_entry"])
    # CF-0438: a parent written before the rename says `no_production_fact`;
    # the word is read, never written again - the copy carries `no_fact`.
    if entry.get("reason_code") is not None:
        entry["reason_code"] = fact_rule.canonical_code(entry["reason_code"])
    parent_sentence = (entry.get("reason") or "").strip()
    pool = rec["pool"]
    entry["topic_id"] = rec["topic_id"]
    entry["stage"] = FUNNEL_STAGE
    entry[PARENT_KEY] = parent_name
    entry[PARENT_POOL_KEY] = sorted(pool or [])
    depth = rec.get("depth")
    if depth is not None:
        entry[DEPTH_KEY] = {k: depth.get(k) for k in
                            ("usable_shots", "usable_seconds", "floor", "deep_enough",
                             "exhausted", "sources", "shots")}
    if entry.get("script_id"):
        entry[PARENT_SCRIPT_KEY] = entry.pop("script_id")
    if parent_sentence:
        entry[PARENT_REASON_KEY] = parent_sentence
    entry["reason"] = (
        f"{rec['topic_id']} was decided in {parent_name} and is not judged again here: "
        f"this batch indexed the same {len(pool or [])} canonical source(s) the parent "
        f"had ({show_pool(pool)}), so the parent's `{entry.get('reason_code')}` refusal "
        f"is about this batch's pool too. The parent's own sentence, verbatim: "
        f"{parent_sentence or '(none recorded)'} "
        f"[{TASK}: a repeat from the indexer writes its own 01b, so the parent's verdict "
        f"is carried over only where the pool is unchanged, and it is recorded here "
        f"rather than left to a reader who can find the parent]")
    return entry


# The three head fields of a `03` that come out of the channel config rather
# than out of a batch file (SKILL, Inputs and step 5).
HEAD_FROM_CHANNEL = ("language", "voice_profile", "stance")


def fresh_head(directory, root=None):
    """The head a `03` gets when this script is the first to write it.

    Before this, the first `--write` on a batch with no `03` yet wrote
    `{"batch_id": null, "skipped": [...]}` - and `check_narration_budget.py`,
    run over that file in step 6, stopped on `no channel field`. The head is
    what the stage itself writes (SKILL step 5): `batch_id` is this batch's
    directory - never a copied head's, which in a repeat is the parent's -
    `channel` is the one the copied `02`/`01` name, resolved through a rename
    (CF-0197), and `language`/`voice_profile`/`stance` are the channel config's
    own fields, where the writer reads them. A channel config that cannot be
    found leaves those three out rather than guessing them; `language` then
    falls back to what `01` says."""
    directory = Path(directory)
    heads = [read_json(directory / f, required=False) for f in (COMPLIANCE_FILE, TREND_FILE)]
    channel = next((resolve_channel(h.get("channel"), root) for h in heads if h.get("channel")), None)
    head = {"batch_id": directory.name}
    if channel:
        head["channel"] = channel
    config = {}
    if channel:
        try:
            config = json.loads(Path(channel_config_path(channel, root)).read_text())
        except (OSError, ValueError):
            config = {}
    for key in HEAD_FROM_CHANNEL:
        value = config.get(key)
        if value is None and key == "language":
            value = next((h.get("language") for h in heads if h.get("language")), None)
        if value is not None:
            head[key] = value
    head["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return head


def fragment(batch, records, parent_name, directory=None, root=None):
    """The `merge_batch_file.py` fragment carrying only these entries. With
    no `03` on disk yet (`batch` empty) the fragment becomes the file, so it
    carries the whole head (`fresh_head`); beside an existing `03` it carries
    that file's `batch_id` and nothing else of the head, as before."""
    head = ({"batch_id": batch.get("batch_id")} if batch or directory is None
            else fresh_head(directory, root))
    return {**head, "skipped": [skip_entry(r, parent_name) for r in records]}


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def by_flag(directory, topics, written_here, out):
    """`--no-parent`: every topic judged here, a record per topic, nothing
    borrowed. The trace is still read, only to say what was set aside."""
    try:
        traced, _why = parent_from_trace(directory)
    except CannotAnswer:
        traced = None
    set_aside = (f"parent {traced} named by the copied heads is set aside"
                 if traced else "no parent in the trace either")
    out(f"{directory.name}: --no-parent - {set_aside}; this is a re-run to check new "
        f"code on the same material, and every topic is judged here")
    verdicts = []
    for t in topics:
        if t in written_here:
            rec = {"topic_id": t, "verdict": JUDGED_HERE,
                   "note": "already written or skipped in this batch's own 03"}
        else:
            rec = {"topic_id": t, "verdict": BY_FLAG,
                   "note": "--no-parent: no verdict is borrowed, judge it here"}
        verdicts.append(rec)
        out(f"  {t}: {rec['verdict']} - {rec['note']}")
    return EXIT_OK, verdicts


def report(target, parent=None, write=False, out=print, no_parent=False, root=None):
    """`(exit code, the verdicts)`. Prints one line per topic of the inbox.

    `no_parent` is `--no-parent`: nothing is borrowed and nothing is written,
    whatever the trace says. `root` is the factory root the channel config is
    read under when a first `--write` has to create the `03`'s head."""
    if no_parent and parent:
        raise CannotAnswer("--no-parent and --parent contradict each other: either "
                           "this batch borrows its parent's verdicts or it borrows none")
    directory = batch_dir(target)
    here_path = directory / BATCH_FILE
    here_index = read_json(directory / INDEX_FILE)
    compliance = read_json(directory / COMPLIANCE_FILE)
    book = read_json(here_path, required=False)
    written_here = ({s.get("topic_id") for s in rows(book, "scripts")}
                    | {s.get("topic_id") for s in rows(book, "skipped")})
    topics = sorted(inbox(compliance, here_index))
    if no_parent:
        return by_flag(directory, topics, written_here, out)

    parent_dir, why = resolve_parent(directory, parent)
    out(f"{directory.name}: {why}")
    if parent_dir is None:
        for t in topics:
            mark = "judged here" if t in written_here else "TO JUDGE"
            out(f"  {t}: {mark} - no parent, so no verdict is borrowed")
        return EXIT_OK, []

    parent_index = read_json(parent_dir / INDEX_FILE)
    parent_book = parent_records(read_json(parent_dir / BATCH_FILE))
    parent_name = parent_dir.name

    verdicts = [judge(t, here_index, parent_index, parent_book, written_here) for t in topics]
    for rec in verdicts:
        out(f"  {rec['topic_id']}: {rec['verdict']} - {rec['note']}")

    decided = [r for r in verdicts if r["verdict"] == DECIDED]
    delivered = [r for r in verdicts if r["verdict"] == DELIVERED]
    if write and decided:
        merged, lines = merge(book, fragment(book, decided, parent_name,
                                             directory=directory, root=root))
        write_atomically(here_path, dump(merged))
        out(f"  wrote {here_path}: {len(decided)} topic(s) into skipped[] under the "
            f"parent's own code, each carrying `{PARENT_KEY}: {parent_name}`")
        for line in lines:
            out(line)
    elif decided:
        out(f"  note: {len(decided)} topic(s) are decided in {parent_name} and nothing was "
            f"recorded - re-run with --write, or the funnel reads them as silent drops")
    if delivered:
        return EXIT_DELIVERED, verdicts
    if decided and not write:
        return EXIT_OWED, verdicts
    return EXIT_OK, verdicts


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", help="the batch directory, or its "
                                      "03-content-researcher.json")
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--parent", metavar="BATCH",
                     help="the parent batch's id or directory. Given, it wins over the "
                          "copied `batch_id` trace; with neither, no verdict is borrowed")
    who.add_argument("--no-parent", action="store_true",
                     help="a re-run to check new code on the same material: borrow no "
                          "parent's verdict whatever the copied heads say, judge every "
                          "topic here, write nothing from a parent. Not with --parent")
    parser.add_argument("--write", action="store_true",
                        help="write the `decided_in_parent` topics into this batch's "
                             "03-content-researcher.json -> skipped[] (via "
                             "merge_batch_file.py, so nothing already there is lost)")
    parser.add_argument("--json", action="store_true",
                        help="print the verdicts as JSON instead of lines")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    lines = []
    try:
        code, verdicts = report(args.batch, parent=args.parent, write=args.write,
                                out=lines.append, no_parent=args.no_parent)
    except CannotAnswer as exc:
        print(f"parent_decisions.py: {exc}", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if args.json:
        print(json.dumps([{k: (sorted(v) if isinstance(v, set) else v)
                           for k, v in r.items() if k != "parent_entry"}
                          for r in verdicts], indent=2, ensure_ascii=False))
    else:
        for line in lines:
            print(line)
    return code


@runlog.script("content-researcher", "parent-decisions", name="parent_decisions.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()

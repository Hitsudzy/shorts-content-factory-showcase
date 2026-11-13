#!/usr/bin/env python3
"""CF-0265: the cut to the batch target, after compliance has judged the whole
shortlist.

The decision (user, grill of 2026-09-17, Q8; log: Notebook
`Operator-Notes/grill-me-logs/2026-09-17 — Правило факта и темы-персоны
(CF-0260).md`). On 2026-09-16 Trend Hunter capped the batch at
`max_titles_per_batch` itself: five topics went to compliance, Spire-Runner came
back `review` on a Sony rights match (correctly - CF-0232), and the batch ran
on four. The slot was not refilled because by the time the rights were judged
there was nothing left to refill it from.

So the cap moved. Trend Hunter now hands out an ordered shortlist of up to
`scope.shortlist_size` viable topics, already fact-probed (CF-0264), compliance
judges **every** one of them, and this script - run once, right after the
verdicts are written and step 4b (`rights_holder_info.py`, CF-0420) has settled them - takes the
first `scope.max_titles_per_batch` topics the gate lets into production, in the
shortlist's own order, and records the rest as unused reserve.

Which verdicts those are changed on 2026-09-22 (CF-0318)
--------------------------------------------------------
Until then `clear`/`caution` filled the slots and a `review` was refused here,
because the indexer would have refused it anyway. The user decided (grill of
2026-09-22, Q8) that **without a human's approval only the publication of a
video is forbidden - the video itself must be made**, so a `review` topic now
takes a slot - after the publishable topics since CF-0335 - and its video
carries a publication hold instead
(`scripts/publication_hold.py`, which runs right after this script). That is
why one name became two: `PRODUCTION_VERDICTS` decides who fills a slot,
`PUBLISH_VERDICTS` decides who may be uploaded without a signature, and the
single name they were carved out of could not answer both questions once they
stopped having the same answer.

Why a script and not a step in the pass
---------------------------------------
Same reason as `blooper_relaxation.py` beside it: a cut made in a model's head
while it writes verdicts is a cut nobody can reproduce, and it would put the
batch target inside the rights judgement, where it does not belong. The rights
logic stays in the pass; the arithmetic of "how many fit" is here, reads its
number from the channel config, and writes down what it did.

What the cut does and does not touch
------------------------------------
* It never changes a verdict. `review` stays `review` and stays in `results[]`
  with the whole reading that earned it - CF-0318 moved what a `review` blocks,
  not how hard it is to earn one. A held topic is **not** reserve and a reserve
  topic is not held: one has a slot and may not be published, the other has no
  slot and would be publishable if it had one.
* `caution` is eligible, exactly like `clear`, and since CF-0318 so is `review`
  (`PRODUCTION_VERDICTS`). `PUBLISH_VERDICTS` is the older, narrower pair; the
  cut uses it for one thing only - which topics get the slots first (CF-0335,
  next point) - and never to refuse a topic. Whether a video may go up is
  answered at the upload, not here.
* Order is the shortlist's - `01-trend-hunter.json` `topics[]`, which is Trend
  Hunter's score order - and is not re-sorted by verdict, with exactly one
  exception. A `caution` ranked second goes on ahead of a `clear` ranked
  seventh: `clear` and `caution` are one class, the publishable one.
  The exception (CF-0335, user's answer of 2026-09-23 to CF-0318, "0318 - B"):
  inside the cut the publishable topics (`PUBLISH_VERDICTS`) take the slots
  first and the held ones (`review`) take what is left, each class keeping its
  shortlist order. A `review` that no slot is left for goes to `reserve[]`
  exactly like a `clear` ranked past the target. Why: since CF-0318 a `review`
  holds a slot, and under plain rank order a held topic pushed a publishable
  one out of the batch - 19 of 73 slots across the sixteen frozen batches were
  held. `results[]` and `reserve[]` are still written in shortlist order; only
  who gets a slot changed.
* Nothing is deleted. Every topic the pass judged leaves this script carrying
  its full verdict record, in `results[]` or in `reserve[]`.

Where the reserve goes, and why it leaves `results[]`
-----------------------------------------------------
`results[]` is read by three stages that were written before this cut existed,
and two of them would take a reserve topic for a topic going on:

* `agents/content-researcher/scripts/fact_refusal.py::cleared_topic_ids` and
  the root's `tests/test_pipeline_contracts.py` both treat every `results[]`
  row as a topic the Researcher owes a script or a skip for. A reserve topic
  left in `results[]` would make the contract demand a script for a topic the
  batch deliberately did not run.
* `shared/runlog/funnel.py` reads `results[].verdict` for the `after
  compliance` step.

So the reserve moves out of `results[]` into `reserve[]`, with the whole
verdict record intact plus `reason_code` and a `reason` that stands on its own.
An untouched reader iterating `results[]` therefore sees exactly the topics
that go on - the file it has always seen. Since CF-0318 that includes the
`review` topics, which go on and carry a `publication_hold` block instead of
leaving the batch.

The one reader this is not enough for is
`agents/footage-indexer/scripts/ingest_batch.py`: it iterates
`01-trend-hunter.json` `topics[]` (all eight) and uses the compliance file only
as a lookup (`verdicts()`, and `v == "review"` was its only skip until
CF-0318 removed it), so a topic with no verdict is fetched rather than
skipped. That repo needs its own small change - `verdicts()` reading
`reserve[]` too - and it is CF-0265's other half,
not this script's business.

`reserve: []` is written even when nothing was reserved, and `cut` is written
always. Present-and-empty means "the cut ran and reserved nothing"; absent
means "the cut never ran" - the same distinction the funnel already draws
between a missing `skipped_topics` and an empty one.

Fail closed the way this repo fails closed
------------------------------------------
What cannot be read has not been written (`blooper_relaxation.py`,
`assetless_rung.py`). With no readable `scope.max_titles_per_batch` there is no
target, so there is no cut: every eligible topic carries on, exactly as before
CF-0265, `cut.target` is `null` and `cut.target_from` says why. The alternative
- inventing a number and refusing topics by it - would be a refusal nobody
decided.
"""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _channel_ids import channel_config_path, resolve_channel  # noqa: E402
from _runlog import runlog  # noqa: E402
from _cli import screen  # noqa: E402

# The verdicts that take a slot in the batch - who gets MADE (CF-0318).
# `review` is in here since 2026-09-22: it no longer takes the topic off the
# batch, it holds the upload.
PRODUCTION_VERDICTS = ("clear", "caution", "review")

# The verdicts that may be PUBLISHED with no human signature. Who may enter the
# batch is `PRODUCTION_VERDICTS` above; this pair only decides who gets a slot
# FIRST (CF-0335, user's decision of 2026-09-23: publishable topics fill the cut
# before held ones). It is also written into the `publish_verdicts` field of the
# `cut` summary, so the record says which pair the batch was cut under.
#
# Where the same pair is spelled: `shared/runlog/funnel.py` PUBLISH_VERDICTS and
# `publication_hold.PUBLISH_VERDICTS` beside this file - spelled again rather
# than imported, like they spell it: the three files are in three repositories
# and share only the artifact. `tests/test_publication_hold.py` is what holds
# this copy and that one together.
#
# Where it is deliberately NOT spelled: the Content Researcher. Its
# `fact_refusal.py` used to carry this pair under a third name, and since
# CF-0318 it carries only `PRODUCTION_VERDICTS = ("clear", "caution", "review")`
# - the wider question, who gets a script written. It has no narrow pair at all,
# because the researcher never decides what may be uploaded: for a `review` that
# is answered by the `publication_hold` block on the row and by the row in
# `publish/publication-holds.json`, read at the upload by CF-0017/CF-0018 and by
# nothing earlier.
PUBLISH_VERDICTS = ("clear", "caution")

# CF-0232 made it a recorded refusal; CF-0318 made the record a publication
# hold instead of a lost topic. Named here so the docstring above, the reason
# text below and `publication_hold.HOLD_VERDICTS` cannot drift apart.
REVIEW_VERDICT = "review"

# `channels/<id>.json` -> `scope`. The batch target is read, never written and
# never defaulted: see "Fail closed" above.
SCOPE_KEY = "scope"
TARGET_KEY = "max_titles_per_batch"
SHORTLIST_KEY = "shortlist_size"

# The artifact's own keys.
RESULTS_KEY = "results"
RESERVE_KEY = "reserve"
# CF-0882: the mark on a reserve row the refill from below the shortlist
# admitted (scripts/judge_below_shortlist.py, the root's shared/below_shortlist.py).
REFILL_MARK = "refill"
CUT_KEY = "cut"

# The code a reserve topic carries into the funnel. The grill's own words for
# it were "неиспользованный запас"; `reserve_unused` is that, and it is
# deliberately not `below_batch_target` - the topic is not below anything, it
# passed every gate this batch has; there was simply no slot left.
RESERVE_CODE = "reserve_unused"

# The pass this cut belongs to. The Content Researcher pass
# (`04-compliance-checker.json`) has no shortlist and no batch target - by then
# the topics are scripts - so the script refuses to run against it.
STAGE_CHECKED = "01-trend-hunter"

ORDER_BASIS = "01-trend-hunter.json topics[] (the shortlist's own order)"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# the batch target
# --------------------------------------------------------------------------
def batch_target(channel):
    """`(target, where)` - the channel's `scope.max_titles_per_batch` and the
    sentence naming where it came from. `target` is None when the config, the
    block or the key cannot be read, and `where` then says which of the three
    it was: no target means no cut."""
    path = channel_config_path(channel)
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return None, f"{path} could not be read ({exc}) - no target, so no cut"
    scope = config.get(SCOPE_KEY)
    if not isinstance(scope, dict):
        return None, f"{path} carries no `{SCOPE_KEY}` object - no target, so no cut"
    raw = scope.get(TARGET_KEY)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        return None, (f"{path} `{SCOPE_KEY}.{TARGET_KEY}` is {raw!r}, not a count - "
                      f"no target, so no cut")
    return raw, f"channels/{channel}.json {SCOPE_KEY}.{TARGET_KEY}"


def shortlist_size(stage_doc):
    """`selection.shortlist_size` as Trend Hunter wrote it (CF-0264), or None -
    a batch selected before that task has no `selection` block at all, and that
    is nothing said rather than a size of zero."""
    selection = stage_doc.get("selection") if isinstance(stage_doc, dict) else None
    if not isinstance(selection, dict):
        return None
    size = selection.get(SHORTLIST_KEY)
    return size if isinstance(size, int) and not isinstance(size, bool) else None


def topic_order(stage_doc):
    """The shortlist's order: the topic ids of `01-trend-hunter.json`
    `topics[]`, in the order the file carries them."""
    order = []
    topics = stage_doc.get("topics") if isinstance(stage_doc, dict) else None
    if isinstance(topics, list):
        for topic in topics:
            if isinstance(topic, dict) and topic.get("topic_id"):
                order.append(topic["topic_id"])
    return order


# --------------------------------------------------------------------------
# the cut
# --------------------------------------------------------------------------
def _clean(row):
    """A reserve row as the pass wrote it: the cut's own two fields taken back
    off. Running the cut twice must not read its own output as the pass's."""
    out = {k: v for k, v in row.items() if k not in ("reason_code", "reason")}
    return out


def judged_results(doc):
    """Every result the pass wrote, reserve rows merged back in - the list the
    cut is computed from.

    This is what makes the script idempotent, and it is not a trick: the cut
    has exactly one input, the verdicts, and `results[] + reserve[]` is that
    input whether the cut has run before or not. A second run over the same
    verdicts therefore reproduces the same cut, and a run after step 4b
    lowered a rights-only `review` to `clear` (CF-0420) produces the cut those new
    verdicts earn.

    A reserve row the refill from below the shortlist admitted (CF-0882,
    marked `refill`) is not one of them: the pass over the shortlist never
    judged it, it came in after the cut to answer a lost slot, and a re-run
    of the cut that ranked it would hand it a slot as a topic waiting for its
    script. `refill_rows` keeps it, and the cut writes it back to `reserve[]`
    untouched.
    """
    rows = []
    for key in (RESULTS_KEY, RESERVE_KEY):
        value = doc.get(key)
        if isinstance(value, list):
            rows.extend(_clean(r) if key == RESERVE_KEY else dict(r)
                        for r in value if isinstance(r, dict)
                        and not (key == RESERVE_KEY and r.get(REFILL_MARK)))
    return rows


def refill_rows(doc):
    """The `reserve[]` rows the refill from below the shortlist admitted
    (CF-0882), as they are - the cut neither ranks nor rewrites them."""
    value = doc.get(RESERVE_KEY) if isinstance(doc, dict) else None
    return [dict(r) for r in value or [] if isinstance(r, dict) and r.get(REFILL_MARK)] \
        if isinstance(value, list) else []


def in_shortlist_order(rows, order):
    """`rows` sorted into the shortlist's order. A row whose topic the
    shortlist does not name keeps its own order, after the named ones: it
    cannot be ranked, and dropping it would be the silent loss this whole
    mechanism exists to prevent."""
    rank = {tid: i for i, tid in enumerate(order)}
    named = [r for r in rows if r.get("topic_id") in rank]
    rest = [r for r in rows if r.get("topic_id") not in rank]
    named.sort(key=lambda r: rank[r["topic_id"]])
    return named + rest


def reserve_reason(row, rank, eligible_total, target, target_from, size):
    """The sentence a reader of `reserve[]` gets with no other file open."""
    verdict = row.get("verdict") or "?"
    of = f" of {size}" if size else ""
    where = (f"rank {rank}{of} in the shortlist" if rank else
             "not named in 01-trend-hunter.json topics[], so it ranks after every topic "
             "that is")
    first = ("the publishable topics take the slots first and the held ones take "
             "what is left (CF-0335), and there was none left"
             if verdict == REVIEW_VERDICT else
             f"the first {target} eligible topic(s), publishable ones first "
             f"(CF-0335), filled the batch")
    return (f"Eligible and unused: verdict {verdict!r}, {where}, "
            f"and {first} "
            f"({eligible_total} of the shortlist were eligible). The batch target is "
            f"{target} ({target_from}). Not a refusal and not a fault of the topic - it "
            f"passed compliance and the batch simply had no slot left for it; nothing "
            f"downstream runs on it (CF-0265, grill of 2026-09-17). A `{REVIEW_VERDICT}` "
            f"topic that got a slot is not this: since CF-0318 it is made, and what it "
            f"carries is a publication hold on its video "
            f"(publish/publication-holds.json), not a lost slot.")


def cut_document(doc, stage_doc, target, target_from):
    """`(doc, carried, reserved)` - the compliance output with the cut applied.

    `carried` and `reserved` are the topic ids, in shortlist order. With
    `target` None nothing is reserved (see "Fail closed" in the module
    docstring) and the record says so.
    """
    out = copy.deepcopy(doc)
    order = topic_order(stage_doc)
    rows = in_shortlist_order(judged_results(out), order)
    size = shortlist_size(stage_doc)

    eligible = [r for r in rows if (r.get("verdict") or "") in PRODUCTION_VERDICTS
                and r.get("topic_id")]
    # CF-0335 (user, 2026-09-23, "0318 - B"): publishable topics fill the
    # slots first, held ones take what is left - each class in shortlist order.
    # The one re-sort by verdict CF-0265 allows; see "Order" in the docstring.
    priority = sorted(eligible, key=lambda r: (r.get("verdict") or "") not in PUBLISH_VERDICTS)
    keep_set = {r["topic_id"] for r in
                (priority if target is None else priority[:target])}
    keep_ids = [r["topic_id"] for r in eligible if r["topic_id"] in keep_set]
    reserve_ids = [r["topic_id"] for r in eligible if r["topic_id"] not in keep_set]

    verdict_by_id = {r.get("topic_id"): (r.get("verdict") or "") for r in rows}
    results, reserved = [], []
    for row in rows:
        tid = row.get("topic_id")
        if tid in reserve_ids:
            rank = order.index(tid) + 1 if tid in order else 0
            row = dict(row)
            row["reason_code"] = RESERVE_CODE
            row["reason"] = reserve_reason(row, rank, len(eligible), target,
                                           target_from, size)
            reserved.append(row)
        else:
            results.append(row)

    refill = refill_rows(doc)
    out[RESULTS_KEY] = results
    out[RESERVE_KEY] = reserved + refill
    out[CUT_KEY] = {
        "task": "CF-0265",
        "cut_at": _now(),
        "order": ORDER_BASIS,
        # CF-0335: inside the cut, `publish_verdicts` first, then the rest of
        # `production_verdicts`, each in shortlist order.
        "publishable_first": True,
        SHORTLIST_KEY: size,
        "judged": len(rows),
        "eligible": len(eligible),
        "carried": len(keep_ids),
        "reserve": len(reserved) + len(refill),
        "refused": len(rows) - len(eligible),
        "held": sum(1 for tid in keep_ids
                    if (verdict_by_id.get(tid) or "") == REVIEW_VERDICT),
        "target": target,
        "target_from": target_from,
        "reason_code": RESERVE_CODE,
        # `pass_verdicts` keeps its name and its meaning inside this record -
        # the verdicts that passed the cut - which since CF-0318 is the
        # production set. The two names beside it say which question each
        # answers, because the record is read long after the change.
        "pass_verdicts": list(PRODUCTION_VERDICTS),
        "production_verdicts": list(PRODUCTION_VERDICTS),
        "publish_verdicts": list(PUBLISH_VERDICTS),
    }
    if refill:
        # CF-0882: `reserve` counts every row of `reserve[]` (the root's
        # contract); this says how many of them came from below the shortlist.
        out[CUT_KEY][REFILL_MARK] = {"task": "CF-0882", "admitted": len(refill)}
    return out, keep_ids, [r["topic_id"] for r in reserved]


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------
USAGE = ("usage: cut_shortlist.py <02-compliance-checker.json> "
         "<01-trend-hunter.json> [channel] [--dry-run]")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rc = screen(argv, USAGE, flags=("--dry-run",))  # CF-0777
    if rc is not None:
        return rc
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    if len(argv) < 2:
        print(USAGE)
        return 2
    out_path, stage_path = Path(argv[0]), Path(argv[1])
    try:
        doc = json.loads(out_path.read_text())
        stage_doc = json.loads(stage_path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read the batch: {exc}")
        return 2
    stage = doc.get("stage_checked")
    if stage and stage != STAGE_CHECKED:
        print(f"refusing: {out_path.name} was written about {stage!r}, and the cut "
              f"belongs to the {STAGE_CHECKED} pass only - the batch target counts "
              f"topics, not scripts")
        return 2

    # CF-0197: a batch written before the channel was renamed carries the old
    # id frozen in its `channel` field, so resolve it before the config is
    # looked up.
    channel = resolve_channel(
        argv[2] if len(argv) > 2 else doc.get("channel", "example-film"))
    target, target_from = batch_target(channel)
    if target is None:
        print(f"no cut: {target_from}. Every eligible topic carries on, exactly as "
              f"before CF-0265 - a refusal nobody decided is worse than a batch that "
              f"is too wide.")

    new_doc, carried, reserved = cut_document(doc, stage_doc, target, target_from)
    record = new_doc[CUT_KEY]
    for tid in carried:
        print(f"{tid}: carried")
    for tid in reserved:
        print(f"{tid}: reserve ({RESERVE_CODE}) - judged and eligible, no slot left")
    for row in new_doc[RESULTS_KEY]:
        verdict = row.get("verdict") or ""
        if verdict == REVIEW_VERDICT:
            print(f"{row.get('topic_id')}: carried and HELD - verdict 'review', so "
                  f"the video is made and is not published without a signature "
                  f"(CF-0318; run scripts/publication_hold.py next)")
        elif verdict not in PRODUCTION_VERDICTS:
            print(f"{row.get('topic_id')}: refused, verdict "
                  f"{verdict!r} - stays in results[] and takes no slot")
    if not dry_run:
        out_path.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{record['judged']} judged, {record['eligible']} eligible, "
          f"{record['carried']} carried ({record['held']} of them held for "
          f"publication), {record['reserve']} reserve, "
          f"{record['refused']} refused; target {record['target']} "
          f"({record['target_from']})"
          + (" (dry run, nothing written)" if dry_run else ""))
    return 0


@runlog.script("compliance-checker", "cut-shortlist", name="cut_shortlist.py")
def cli():
    """The command-line entry (CF-0107 accounting, same shape as
    blooper_relaxation.py): main()'s return code becomes the exit code inside
    the run event, so a usage error (2) is recorded as `failed`. The cut is
    pure Python over the channel config and two batch files - no model call,
    no external binary - so there is no `child` event."""
    sys.exit(main())


if __name__ == "__main__":
    cli()

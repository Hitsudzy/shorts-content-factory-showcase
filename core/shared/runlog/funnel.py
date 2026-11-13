#!/usr/bin/env python3
"""CF-0232: the topic funnel of one batch - selected -> after compliance ->
with two sources -> scripts -> ready - with a reason code on every loss.

DoD 1.4.4 item 1: `fetched: 5` in 01b-footage-index.json reads like "five
topics" when the batch actually started from eight and compliance took three
off it with a `review` verdict. A batch that loses more than a third of its
topics before the first footage request and says so nowhere is a refusal
indistinguishable from a measurement (the class of CF-0167 and CF-0175). This
module is the place that says it.

Read from the batch's stage artifacts, never from RUN_EVENTS.jsonl - the
events say when a stage ran, the artifacts say what it decided:

    01-trend-hunter.json        topics[]                  -> the shortlist
                                skipped_topics[]          } -> before selection
                                selection{}               }
                                footage_substitution{}    } (CF-0313)
                                search_quota{}            }
    02-compliance-checker.json  cut{}, reserve[]          -> selected
                                results[].verdict         -> after compliance
    01b-footage-index.json      sources_by_topic{}        } -> with two sources
                                failed[].reason_code      } (CF-0281)
                                reserve_substitution{}    -> selected (CF-0306)
                                pool_depth.thin[]         -> scripts (CF-0304)
    03-content-researcher.json  scripts[], skipped[]      -> scripts
    04-compliance-checker.json  results[].verdict         } -> after compliance 2
                                results[].contribution_check.verdict
    05-video-editor.json        videos[], refusals[]      -> ready

The rule that makes a silent loss impossible. At every step each item is
judged twice: did it meet this step's bar (`cond`), and does the next stage's
artifact carry it (`present`)?

    bar met,     carried on  -> survives
    bar met,     dropped     -> lost, under the code the dropping stage
                                recorded; when no stage recorded anything,
                                `unexplained` - and the summary says so out loud
    bar missed,  dropped     -> lost, under this step's own code
    bar missed,  carried on  -> `carried_on`: the item went past a bar it did
                                not clear, because nothing in the batch that ran
                                enforced that bar. Counted and named, never
                                folded into the survivors (CF-0118:
                                `two_source_gate` was `measure` until
                                2026-09-16, so every batch written before that
                                date carries such topics; CF-0129 turned the
                                gate to `enforce` and made the indexer refuse a
                                one-source topic, so in a batch run since, the
                                same topic is `lost` under its code instead).

A topic Trend Hunter itself refused is not in `topics[]` at all - it never
reached the selection - so it cannot be a step of the chain. It is read from
`01-trend-hunter.json` `skipped_topics[]` and reported as a loss of the
`selected` step, under the code the stage wrote (CF-0129, 2026-09-16: the stage
refuses a topic it found no footage candidate for at all, `no_source`). A batch
from before that date has no such field, and that is read as nothing said
rather than nothing lost - the difference is spelled out in the section.

**What `selected` counts since 2026-09-17 (CF-0264 / CF-0265, decision
CF-0260).** Until then Trend Hunter cut to `scope.max_titles_per_batch` itself,
so `01-trend-hunter.json` -> `topics[]` *was* the selection and `selected`
counted it. Now the stage hands out a shortlist of up to
`scope.shortlist_size` (8) topics, compliance judges the whole shortlist, and
`cut_shortlist.py` carries the first `scope.max_titles_per_batch` (5) with a
passing verdict into the batch, recording the rest in
`02-compliance-checker.json` -> `reserve[]` and the arithmetic in `cut`. Two
consequences, both deliberate:

* `selected` counts **what the cut carried**, not the shortlist, and the
  shortlist's size is printed beside it. Counting the shortlist would make
  every batch read as "8 selected -> 3 ready" and turn a deliberate spare into
  a 62 % loss - the mirror image of the `fetched: 5` overstatement this module
  exists to stop. The target sentence the channel is read against stays
  "5 selected -> 3 ready" and stays true.
* The topics the cut had no slot for are **reserve, not loss**: they are in
  `RESERVE_CODES`, in their own column, in `f["reserve"]`, and in no `losses`
  count. A topic compliance refused is still a loss, and is still in the
  chain - what changed is that the cut now gives its slot to the next eligible
  topic instead of letting the batch run short, which is exactly what happened
  on 2026-09-16 when Spire-Runner took a slot, compliance refused it and nothing
  replaced it. Reserve topics were also the reason `not_screened` needed
  narrowing: a topic in `topics[]` with no row in `results[]` used to read as
  "nobody judged it", and after the cut that description fits every spare.
  They leave `selected` before that step runs, so the code keeps its meaning.

A batch carrying none of the three marks (`selection`, `cut`, a
`skipped_topics[]` code from `SHORTLIST_CODES`) is read exactly as it was
before this change, down to the headline - the batches on disk are the
regression corpus for that.

**A spare that was spent is not a spare (CF-0306, the user's decision of
2026-09-21).** The cut used to be the only place a reserve topic could be used,
so a topic lost *after* it left the batch one short: on 2026-09-21 the cut
carried five, the indexer lost Silent Tide and the Researcher lost three more,
and The Long Voyage and Outrider sat in `reserve[]` untouched while the batch
shipped one script. The indexer now refills the freed slot from the reserve -
on its own pass, inside the sieve, or on the orchestrator's second call with
`--reserve-for` - and writes `01b-footage-index.json` ->
`reserve_substitution`. Here that block does three things and no more:

* the substituted topic is counted in `selected` and walks every step below
  like any other topic of the batch, so the headline's "N of M topics lost"
  counts M from what really entered the batch;
* it leaves the `held in reserve` column and `f["reserve"]`, because a spare
  that took a slot is held back from nothing;
* the swap is drawn where the batch's membership is decided - the `selected`
  step - as `reserve_substituted` in `carried_on`, with the topic it replaced,
  the stage that lost it and the code it was lost under; a slot the empty
  reserve could not fill is `reserve_exhausted` in `lost`. Neither is counted
  in `losses`: see `SUBSTITUTION_CODES`. The verdict of a substituted topic is
  read from `reserve[]`, where compliance left it, since promoting a topic does
  not rewrite `02-compliance-checker.json`.

**The same refill one stage earlier, and the first slot with a price on it
(CF-0313, 2026-09-22).** Trend Hunter refuses a topic at step 5b when its
footage sieves leave fewer than two candidates (CF-0309, `no_source`), and that
emptied a shortlist slot nobody refilled: the `below_shortlist` reserve sat
unused and the batch went to compliance a topic short. The stage now takes the
next reserve topic by rank, walks it through 5b like any other, and writes
`01-trend-hunter.json` -> `footage_substitution`. The `before_selection` step
reads it, the way `selected` reads the indexer's block, and it draws three
kinds of row and no more:

* a refill that happened (`promoted: true`) is `reserve_substituted` in
  `carried_on`, saying who took whose slot and what the slot was lost to. The
  substitute is already in `topics[]`, so it is counted in the step like any
  other topic and nothing here adds it a second time;
* a slot nobody filled is `lost`, under the code the stage wrote:
  `reserve_exhausted` when the reserve was used up, `search_quota_exhausted`
  when the day's `search.list` calls would not pay for the facet run
  (`search_quota` beside the block carries the arithmetic). Neither is counted
  in `losses` - SUBSTITUTION_CODES says why;
* a substitution *decided* and not executed (`outcome: pending_search`) is a
  row of its own: the slot is still empty, the topic is in no `topics[]` and in
  no count, and the entry names the search that finishes it. A decision the
  funnel drew as a refill would be a batch the record says is full and the
  disk says is not.

**The second compliance pass is a step of its own (CF-0269, 2026-09-18).**
`04-compliance-checker.json` judges the written scripts, and it judges them
twice: the sensitivity verdict (`clear|caution|review`, the same
vocabulary the first pass uses) and, since CF-0181, the contribution check
(`contribution_check.verdict`, `pass|block`, nothing softer). Until now the
funnel read only the first of the two, and only as a side condition of the
`ready` step. On `example-film/2026-09-17T1901Z` that cost the batch its
explanation: `lf-2026-09-17-006-script1` was blocked with
`fact_in_the_story`, the Editor honoured the block and wrote nothing about the
script, and the funnel printed `not_built` - "05-video-editor.json lists
neither a video nor a refusal" - which is the observer's inference about a
stage that was never asked to run, exactly the sentence CF-0254 took away from
the Editor. So the pass gets a step between `scripts` and `ready`:

    verdict that does not go on           -> lost, `compliance_review`
    contribution_check.verdict == block   -> lost, `contribution_blocked`,
                                             with the check's own failure
                                             code(s) in the reason and its whole
                                             row in `detail`
    otherwise (including no row at all)   -> on to the Editor

and `ready` judges only what this step cleared, so `not_built` goes back to
meaning what it says: a script the Editor *was* free to build and neither
built nor refused.

**A `review` holds the publication, not the production (CF-0318, the user's
decision, grill of 2026-09-22).** This module is the reason the task exists: it
counted `compliance_review` at **19 topics of 101 across ten instrumented
runs**, second only to `no_production_fact` (29), and every one of those was a
video nobody had refused to make - the gate was waiting for an approval from a
human who is not there while a batch runs. The user decided that without a
human's approval only the **upload** is forbidden. So a `review` topic keeps its
slot, is fetched, written and rendered like any other, and its video carries a
hold instead: a `publication_hold` block on the compliance row and a row in
`publish/publication-holds.json`, which Publisher (CF-0017/CF-0018) must treat
as a hard stop until the user signs it. Three consequences here:

* `review` + a hold **passes** `after_compliance` (and the second pass, and the
  cut before them). It is in `items`, counted in the step, and in neither
  `lost` nor `carried_on` - `carried_on` would be the worse of the two errors:
  a video made exactly as intended, signed as a topic that slipped past a
  refusal;
* the count of held videos is a line of its own - `f["held"]`, the step's
  `held` list, its own table column and its own sentence in the headline. It is
  in no `losses` total and in no "went past a bar they did not clear" count. A
  batch that made five videos of which one may not go up has not had the run
  the bare chain describes, and the difference is not a loss;
* **a batch judged before 2026-09-22 reads exactly as it always did.** There
  `review` really was a refusal, the topic really did die at the indexer, and
  the funnel says so, under `compliance_review`, with a sentence naming the
  rule it ran under. What tells the two apart is the presence of the hold
  block on the row - never the verdict, which is the same word in both. A
  funnel that re-read old runs under the new rule would be announcing that ten
  recorded batches were mistaken about what they did, which is the one thing a
  record of what happened may not do.

**Whether the Editor owes a `refusals[]` entry for a blocked script: no**
(CF-0269, the question CF-0254 left open). The loss belongs to the stage that
decided it. A refusal is a record of a decision, and the Editor made none - it
was never handed the script. Requiring an entry would make the Editor restate
compliance's verdict as if it were its own, and a second writer of the same
loss is how a loss gets double-counted or, worse, recorded two ways. The
`refusals[]` contract keeps the scope CF-0254 gave it: scripts the Editor took
and refused itself, before the render.

Like `before_selection`, this step is **drawn only when it has something to
say** - when the pass refused or waved past at least one script. When it
refused nothing its count is the `scripts` count and the row would add a
number that is already there, while changing the headline of every batch on
disk; so a batch whose second pass blocked nothing renders exactly as it did
before CF-0269, which the batches on disk are again the regression corpus for.
The losses and the step are the same condition: when the step is absent there
are none.

`carried_on` is why the funnel counts are not a monotone chain: on
2026-09-09 every one of the five surviving topics had exactly one source, so
"with two sources" is 0 while "scripts" is 5. That is the batch's truth, and
hiding it behind a decreasing sequence of numbers would be the same lie
`fetched: 5` told.

What this module deliberately does not decide:

* **Independence of sources.** The count is the number of ids the indexer
  registered under a topic in `sources_by_topic` - one per canonical cut, since
  a re-upload of the same cut is filed under `aliases[]` by the CF-0080
  fingerprint and never registered as a source. So the independence verdict is
  the indexer's and the count is read as it stands; what the funnel does not do
  is second-guess that verdict, or re-measure a fingerprint from a run log.
* **Whether a pattern was delivered.** `pattern_delivered: null` on a video
  that passed QC is a shortfall of a delivered video, not a lost topic, and it
  belongs to DoD 1.4.4 item 3 (CF-0233 / CF-0245). The funnel names such
  videos in a line under the table - visible, but not counted as a loss.
  `pattern_undeliverable` is in the vocabulary for the refusal those tasks
  will write **before** the render: as a `skipped[]` entry of
  03-content-researcher.json, or as a `refusals[]` entry of
  05-video-editor.json (`{"script_id", "reason_code", "reason"}`) for a script
  the Editor refuses without rendering it.
* **Whether a video is long enough.** CF-0293 reads the verdict the Editor
  already wrote (`videos[].duration.narration.video_length`, the root's
  `judge_video_length()` record since CF-0158) and never re-derives it: the
  band belongs to the channel config and the arithmetic to
  patterns/validate_patterns.py, and a second opinion computed here is exactly
  the drift CF-0158 was built to prevent. A video under the band (`short`,
  30-45 s) is named under the table with its length - a delivered video with a
  shortfall, not a lost topic, the same standing `pattern_delivered: null`
  has. A video under the hard floor (30 s) is not delivered at all: the
  Editor refuses the plan before the render, and the script leaves the batch
  as a `video_too_short` loss in the table.
* **Time.** Stage timing is summary.stage_times() and CF-0252.

    funnel.funnel(batch_dir)        the whole funnel as data
    funnel.render(f)                the Markdown section
    funnel.headline(f)              the one-line form, for the top of RUN_SUMMARY
    runlog funnel [--batch DIR] [--json]

Stdlib only, like everything under shared/runlog/.
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["FUNNEL_CODES", "RESERVE_CODES", "SUBSTITUTION_CODES", "SUBSTITUTION_KEY",
           "RESERVE_SUBSTITUTED", "RESERVE_EXHAUSTED", "POOL_DEPTH_KEY",
           "AFTER_JUDGE_AT", "AFTER_JUDGE_RU", "after_judge_rows",
           "SEARCH_QUOTA_EXHAUSTED", "FOOTAGE_SUBSTITUTION_KEY", "SEARCH_QUOTA_KEY",
           "FOOTAGE_EVIDENCE_QUOTA", "REASONS_RU", "reason_ru",
           "PENDING_SEARCH",
           "SHORTLIST_CODES", "PASS_VERDICTS", "PRODUCTION_VERDICTS", "PUBLISH_VERDICTS",
           "REVIEW_VERDICT", "PUBLICATION_HOLD_KEY", "COMPLIANCE_HOLD", "HOLD_CODES",
           "OWN_GRAPHIC_KEPT", "OWN_GRAPHIC_KEY", "KEPT_CODES",
           "CONTRIBUTION_KEY", "CONTRIBUTION_BLOCK", "TWO_SOURCE_FLOOR", "VIDEO_TOO_SHORT",
           "VIDEO_LENGTH_PATH", "VIDEO_LENGTH_SHORT", "STEPS", "ALL_STEPS",
           "OPTIONAL_STEPS", "BEFORE_SELECTION", "AFTER_COMPLIANCE_2", "ARTIFACTS",
           "UNEXPLAINED", "NO_FACT", "LEGACY_CODES", "canonical_code", "TARGET_READY_KEY", "MAX_TITLES_KEY", "SHORTLIST_KEY", "funnel",
           "headline", "render", "read_artifacts", "target_of",
           "FRAME_JUDGE", "FRAME_JUDGE_FAILED", "FRAME_JUDGE_FILE", "OPTIONAL_ARTIFACTS",
           "FRAME_JUDGE_SCHEMA", "FRAME_JUDGE_VERDICTS_SCHEMA", "FRAME_JUDGE_PACK_SCHEMA",
           "FRAME_VERDICTS", "BLOCKING_VERDICTS", "NEUTRAL_VERDICT", "JUDGE_RULES",
           "FRAME_JUDGE_SCHEMA_V1", "FRAME_JUDGE_SCHEMAS",
           "JUDGE_REPAIRS_KEY", "JUDGE_REPAIRED", "JUDGE_REPAIR_FAILED", "judge_repairs",
           "JUDGE_REPAIR_BLOCK_KEYS", "REFILL_SCREEN", "REFILL_REFUSAL_CODES",
           "REFILL_REASONS_RU", "refill_reason_ru", "BELOW_SHORTLIST_REFILL_KEY",
           "REFILL_RECORD_FILE", "REFILL_REFUSED_KEY", "REFILL_ROUNDS", "REFILL_OUTCOMES_RU",
           "below_shortlist_refill", "refill_line",
           "GATE_PASS", "GATE_REJECT", "GATE_INCOMPLETE", "GATE_STATES",
           "INDEX_FAILED", "SOURCE_FOREIGN", "SOURCE_BURNED_TEXT", "SIEVE_CODES",
           "HOST_SHOW", "SIEVE_REFUSAL_CODES", "HOST_SHOW_KEY", "SOURCE_REASONS_RU",
           "host_show_counts",
           "SOURCE_TOO_LONG", "RIGHTS_EXCLUSION",
           "PLAN_UNASSEMBLED", "SCORE_BELOW_THRESHOLD", "SCORE_GATE",
           "code_of", "AFTER_CLOSE_KEY", "after_close_of", "run_spans",
           "JUDGE_FOREIGN_CORE", "FOREIGN_CORE_RULE", "FOREIGN_CORE_MODES",
           "FOREIGN_CORE_DEFAULT_MODE", "FOREIGN_CORE_FAIL", "FOREIGN_SHARE_MAX",
           "FOREIGN_HOOK_SECONDS", "foreign_core", "JUDGE_FOOTAGE_DEFECT",
           "JUDGE_WRONG_PERSON_RULE"]

# --------------------------------------------------------------------------
# the vocabulary of loss codes - one string per way a topic leaves a batch
# --------------------------------------------------------------------------
# Every loss in the funnel carries one of these in `reason_code`. The five the
# grill of 2026-09-16 named are here under their own names; the rest are the
# codes the stages already write (tests/test_pipeline_contracts.py SKIP_CODES)
# plus the ones this module needs to keep a drop from being silent.
#
# `pool_too_thin` is written by the Researcher's coverage gate (CF-0233/CF-0274)
# (and its siblings `check_block_capacity.py`, CF-0284, and `check_alternate_sides.py`,
# CF-0285) and, since CF-0282, by the Editor's anchor preflight (gate `anchor_preflight`);
# `pattern_undeliverable` by the Editor's plan gates. Both entered the vocabulary
# before any batch carried them, for the reason
# `no_production_fact` was (CF-0185): the day CF-0233 or CF-0245 writes one, a
# batch using the code has to be legal here rather than rejected by the
# contract that exists to record it.
#
# `source_host_unlisted` (CF-0259, 2026-09-17) is the one addition with a loss
# already behind it: example-film/2026-09-16T2148Z lost its only video when the
# Editor's source badge refused the host stroudtimes.com, in neither of the
# channel's two lists (CF-0164/CF-0166) - after the TTS and the alignment had
# been paid for. The check now runs in the Researcher, before the TTS
# (agents/content-researcher/scripts/check_source_hosts.py), and appends its
# refusal to `03-content-researcher.json` -> `skipped[]`, so the loss lands on
# the `scripts` step the same way `no_production_fact` does.
#
# CF-0264/CF-0265 (2026-09-17, decision CF-0260) add three, and two of them are
# not losses at all. `person_without_work` is a refusal: a person topic whose
# own news names no work has nothing to look a production fact up for, and a
# work may not be inferred from a filmography. The other two are *reserve* -
# a topic that was good enough and for which there was no slot:
# `below_shortlist` past `scope.shortlist_size` at Trend Hunter,
# `reserve_unused` past `scope.max_titles_per_batch` at the cut that follows
# compliance. They are in this vocabulary because a stage writes them and an
# unknown code is a contract defect (see `unknown_codes`), and they are in
# RESERVE_CODES because counting them as losses would be the mirror of the lie
# `fetched: 5` told: a batch that deliberately keeps a spare would read as a
# batch that lost one.
#
# `contribution_blocked` (CF-0269, 2026-09-18) is the second pass' other
# verdict. `check_contribution.py` answers `pass` or `block` and nothing
# softer, and it writes its own reason codes into
# `contribution_check.failures[].reason_code` (`fact_in_the_story`,
# `fact_not_concrete`, `fact_is_filler`, `fact_unsourced`,
# `source_is_the_story`). Those five stay *out* of this vocabulary on purpose:
# they name why one check failed, not how a script left the batch, and the
# funnel's codes are the second kind. They are named in the loss' `reason` and
# carried verbatim in its `detail`, so nothing about the block is paraphrased
# away - what the vocabulary gains is one code for one way out of the batch.
# `video_too_short` (CF-0293, 2026-09-20, the user's decision on CF-0283) is
# the ceiling's mirror, and the first code this vocabulary has for a length.
# The channel now has two floors: under `narration_budget.total_seconds_min`
# (45 s) a video is SHORT - it is made, it warns, and since this task it is
# counted in the section below the table, because a short video is a delivered
# video with a shortfall and not a topic lost. Under
# `narration_budget.total_seconds_hard_min` (30 s) there is no video: the plan
# is refused before the render and the script leaves the batch carrying this
# code. It enters the vocabulary before any batch carries it, for the reason
# `pattern_undeliverable` and `no_production_fact` did - the day the Editor's
# gate writes one, a batch using the code has to be legal here rather than
# reported as an unknown code by the module that exists to record it.
# `frame_judge_failed` (CF-0298, 2026-09-20, the user's decision) is the first
# code for a finished video that a *reader* refused. DoD item 3 - every phrase
# backed by its picture - had no checker in the chain at all (CF-0291): the
# similarity floor of CF-0290 answers "does this frame look like the anchor",
# which is not "is this frame about what the narrator is saying", and on
# `delver.mp4` it said `ok` over three blocks of a different film. The frame
# judge (`.claude/skills/frame-judge/SKILL.md`) reads the finished frames
# against the narration and `scripts/frame_judge_gate.py` executes the rule.
# One code, not four: `foreign`, `contradicts` and a foreign caption burned into
# the picture are three things the judge *saw*, and they travel under their own
# names inside `06-frame-judge.json` and in the loss' `reason` - but they are one
# way out of the batch, which is what this vocabulary counts (the same line
# `contribution_blocked` draws around the contribution check's own five codes).
# `index_failed` (CF-0281, 2026-09-21) is the second half of `fetch_failed`,
# split off because the two are fixed in different places. A source that
# YouTube never handed over is `fetch_failed` and nothing here can change that;
# a source that came down cleanly, sits in `shared/footage`, and has no index
# behind it is this factory's own failure - and until CF-0281 the indexer wrote
# the source `done` anyway, so the loss reached this module wearing the word
# for YouTube's refusal (`example-film/2026-09-18T1058Z`, `HEaXDIrGhS4`). The
# indexer now records it in `01b-footage-index.json` -> `failed[]` with
# `reason_code: index_failed` (and `refused_at: index`), and the `two_sources`
# step below reads that field rather than counting every row as a failed fetch.
# A topic whose candidates were lost to both causes stays `fetch_failed` - the
# code names how the topic left, and the sentence names both.
#
# CF-0299 (2026-09-21) adds the third way a source can be lost inside the
# indexer, and the first one whose cause is visible in the footage itself: the
# source came down, was indexed, its shots were described - and the source
# sieve (`agents/footage-indexer/scripts/source_sieve.py`) then refused the
# whole source for what those descriptions say is in it. `source_foreign` is a
# source that shows somebody else's work (`9a7i4LHHZNs`: the Gold Delver comic
# trailer registered as a second source for a topic about a different Delver),
# `source_burned_text` a source carrying foreign captions the 9:16 crop cannot
# take off the picture (`bYKJxZYd66o`: a vertical interview Short with its
# subtitles in the middle of the frame, which reached a finished render and
# was caught only by the frame judge). The sieve writes these into
# `01b-footage-index.json` -> `failed[]` with `refused_at: sieve`, the same
# place and shape `index_failed` uses, so `_failed_codes` below reads them
# without a second path. Both are this factory's own doing in the sense that
# the stage decided them - unlike `fetch_failed` - but neither is a defect:
# they are the sieve working, which is why they keep their own words instead
# of being folded into `index_failed`.
#
# CF-0435 (grill of 2026-09-29, Q19 step 4) narrows the sieve to one of them:
# a source is refused whole only as somebody else's film (`source_foreign`).
# A burned-text majority keeps the source now - its burned shots stay out one
# by one inside the indexer and never reach `failed[]` - so new batches no
# longer write `source_burned_text`. The code stays here, in `SIEVE_CODES` and
# in the funnel's vocabulary, because every batch sieved from CF-0299 to
# CF-0435 carries it and must read as the refusal it was; nothing requires a
# batch to write it.
#
# `source_too_long` (CF-0302, 2026-09-21) is the fourth, and the only one
# decided before anything was downloaded at all. A candidate whose length is
# over the ceiling its nature is held to (`sources.youtube.max_source_duration_seconds`
# in the channel config) is refused on its metadata: the 2 h 14 min talk show
# `Lv_GOa6HXVA` was taken as a second source for a Silent Tide topic because
# the word "trailer" sits in its title, and indexing it would have run about
# thirteen hours - it was killed by hand and the topic died of the attempt it
# had cost. The indexer now asks for the duration first and writes the refusal
# into `01b-footage-index.json` -> `failed[]` with `refused_at: metadata` and
# `attempt_spent: false`, the same place and shape the sieve codes use. It is
# not a failed fetch (nothing was fetched) and not a failed index (nothing was
# indexed), which is why it gets its own word rather than borrowing one of
# those two - and, like the sieve's codes, it is the stage working rather than
# a defect.
#
# `plan_unassembled` (CF-0411, 2026-09-28, the user's decision on
# example-film/2026-09-27T0929Z, a batch of 0 videos) is the Video Editor's own
# plan gates moved to the Researcher. Step 6b of the Researcher's skill
# (`agents/content-researcher/scripts/plan_check_loop.py --write`) runs the
# Editor's gates over every script - TTS, resolve, plan, no render
# (`agents/video-editor/scripts/plan_check.py check`) - and a script they
# refuse gets up to 3 rounds (`content_researcher.plan_check_rounds`, CF-0430) of editing
# its `visual_anchors` only. Still unassembled, the topic leaves
# `03-content-researcher.json` -> `scripts[]` for `skipped[]` with this code,
# `stage: "scripts"`, the refusal kinds of the gates in `kinds[]` and the
# rounds in `plan_check{}` - so it is a loss of the `scripts` step, read the
# same way `source_host_unlisted` is. It is not a new gate: the refusals are
# the ones `pattern_undeliverable` / `pool_too_thin` / `no_second_source`
# already named at the Editor, now spent before compliance-2 and the render
# rather than after. One code, not one per kind, for the reason
# `frame_judge_failed` gives: the kinds are why the gates refused, this is how
# the topic left the batch. The refusal sidecars are moved out of the Editor's
# reach (`work/<slug>/plan_check.rounds/dropped/`), so the same loss is never
# counted a second time at `ready`.
PLAN_UNASSEMBLED = "plan_unassembled"
# CF-0434 (grill 2026-09-29, Q11, Q17, Q20-Q21): the score model (CF-0432,
# shared/score/score.py) is counted at every stage, and a video whose real
# penalties already put it under the threshold N goes no further - at the
# Researcher's 6b after its rounds, at the Editor after the plan, the render or
# QC, at the frame judge. One code for all of them, whatever the stage: "under
# N" is one outcome, and the funnel counts it apart from every other refusal so
# a batch can say how many videos the score itself stopped. The stage is in the
# record (`stage` / `numbers.stage` / `score.stopped_at`), not in the word.
#
# Written first as `held_back` with `gate: score_below_threshold` (parts A and
# B of CF-0434 landed before this code existed); `code_of()` reads that pair as
# this code, so those batches are counted here too.
SCORE_BELOW_THRESHOLD = "score_below_threshold"
SCORE_GATE = "score_below_threshold"
FRAME_JUDGE_FAILED = "frame_judge_failed"
# CF-0539: the frame judge's `foreign` under the core of the story - see
# foreign_core() below.
JUDGE_FOREIGN_CORE = "judge_foreign_core"
# CF-0646: the frame judge saw footage the user does not want shown - a thin
# strip, people cut by the frame, soap (`score.hard.footage_defect`, signed
# 2026-10-09); refused whatever the score, rebuilt once by the operator.
JUDGE_FOOTAGE_DEFECT = "judge_footage_defect"
VIDEO_TOO_SHORT = "video_too_short"
CLAIM_UNSUPPORTED = "claim_unsupported"     # CF-0553 (shared/factrule/claim_judge.SKIP_REASON_CODE)
INDEX_FAILED = "index_failed"
SOURCE_FOREIGN = "source_foreign"
SOURCE_BURNED_TEXT = "source_burned_text"   # historical since CF-0435: read, no longer written
SIEVE_CODES = (SOURCE_FOREIGN, SOURCE_BURNED_TEXT)
# CF-0817 (2.19, the user's yes of 2026-10-20 under vanguards-doomsday): the
# sieve's guard refuses a held source somebody already found to be another
# people's host show - a podcast, an interview, a talk show - before its shots
# are read (`source_sieve.host_show_refusals`), and writes it into `01b` ->
# `failed[]` with `reason_code: host_show` (`refused_at: sieve`). A loss of the
# sieve's kind, so the `two_sources` step reads it beside the two words above
# rather than as a download YouTube refused. It is a word of the source, not of
# the topic: a topic that lost everything that way is refused by the indexer as
# `source_foreign` (somebody else's material), and the funnel counts it there -
# `host_show` is in neither FUNNEL_CODES nor the indexer's topic refusal list
# (`tests/test_pipeline_contracts.py` INDEX_REFUSAL_CODES). The same word marks
# Trend Hunter's dropped candidates (`evidence.footage_candidates_dropped`) and
# the indexer's pool refusals (`01b` -> `pool_sources`); the funnel counts all
# three under HOST_SHOW_KEY for the headline.
HOST_SHOW = "host_show"
SIEVE_REFUSAL_CODES = SIEVE_CODES + (HOST_SHOW,)
HOST_SHOW_KEY = "host_show"
SOURCE_TOO_LONG = "source_too_long"
# `rights_exclusion`: a source the factory may not take - refused on rights
# before any media moves (the licence refusals below). The word itself stays
# the indexer's (and the Trend Hunter's): it is read here, never a code of the
# funnel's own.
RIGHTS_EXCLUSION = "rights_exclusion"
# CF-0663: the refusal on rights the indexer writes before any media
# moves - a candidate whose licence the channel does not take (NC / ND /
# non-free, or the Trend Hunter's own `licence.accepted: false`, CF-0662) goes
# into `01b` -> `failed[]` with `reason_code: licence_refused`, `refused_at:
# candidate`, `attempts: []`, `attempt_spent: false`, and its `rights` record
# beside it. It is no download YouTube refused, so it is not `fetch_failed`:
# the funnel counts it under `rights_exclusion` - the one word of this
# vocabulary for a source the factory may not take - last in the priority,
# because it cost the topic nothing.
LICENCE_REFUSED = "licence_refused"
# CF-0665: its sibling for an archive file (NASA / Commons) the indexer fetches
# directly - the licence read again from the archive just before the download
# is not the one the candidate was judged on, so the file is refused there
# with both versions (`licence_was`, `licence_now`) and `attempt_spent: false`.
# Nothing came down and the topic paid nothing: the same word and the same
# place in the priority as `licence_refused`.
LICENCE_CHANGED = "licence_changed"
LICENCE_CODES = (LICENCE_REFUSED, LICENCE_CHANGED)
# CF-0306, the user's decision of 2026-09-21. Until it, the cut (CF-0265) was
# the only place a reserve topic could be used: a topic lost *after* the cut -
# at the indexer, at the sieve, at the Researcher - left the batch one short
# with two cleared spares sitting unused, which is what happened to
# `example-film/2026-09-21T0358Z` (five carried, four lost after compliance, The
# Odyssey and Outrider untouched in `reserve[]`, one script shipped). The
# indexer now refills the freed slot from the reserve and records each refill
# in `01b-footage-index.json` -> `reserve_substitution`. Neither word is a
# reserve code: `reserve_substituted` is a topic that is *in* the batch, and
# `reserve_exhausted` is not a topic at all but a slot nothing could fill.
RESERVE_SUBSTITUTED = "reserve_substituted"
RESERVE_EXHAUSTED = "reserve_exhausted"
SUBSTITUTION_KEY = "reserve_substitution"
# CF-0801 (part of CF-0798, the user's yes of 2026-10-18): the third place a
# slot falls free is the frame judge. The indexer's `--reserve-for
# --after-judge` (CF-0799) records the substitute with `at:
# frame_judge_refusal` and a reason starting «после судьи кадра»; it is a
# `reserve_substituted` like any other (one row in `selected` -> carried_on),
# the refused topic stays the frame judge's loss under its own code, and the
# substitute's own fate is read off 03/05/06 like any topic's.
AFTER_JUDGE_AT = "frame_judge_refusal"
AFTER_JUDGE_RU = "после судьи кадра"
# CF-0313, 2026-09-22. The same refill, one stage earlier and with a price on
# it. Trend Hunter refuses a topic at step 5b when fewer than
# `CANDIDATE_REFUSAL_FLOOR` footage candidates survive its sieves (CF-0309,
# `no_source`), and until CF-0313 that emptied a shortlist slot nobody filled -
# the `below_shortlist` reserve of CF-0264 sat there while the batch went to
# compliance one topic short. The stage now takes the next reserve topic by
# rank, walks it through 5b like any other, and writes
# `01-trend-hunter.json` -> `footage_substitution`.
#
# What is new here is the third way a slot can stay empty, and it is not about
# the topic at all: walking a reserve topic through 5b costs one facet run (6
# `search.list` calls) out of a hard 100 a day (CF-0288), a batch is already
# ~68 of them, and when the day will not pay for another run the slot is left
# alone. `search_quota_exhausted` is that, and it is deliberately not
# `no_source`: nothing was looked for, so calling it "no footage" would record
# a limit of ours as a fact about the topic - the class of misreading this
# whole module exists to stop. It is in SUBSTITUTION_CODES with the other two:
# the topic whose slot it was is already counted once, under its own code, at
# the step that lost it.
SEARCH_QUOTA_EXHAUSTED = "search_quota_exhausted"
FOOTAGE_SUBSTITUTION_KEY = "footage_substitution"
SEARCH_QUOTA_KEY = "search_quota"
# CF-0317 / CF-0714. The other half of a spent search day, and the opposite
# classification. `search_quota_exhausted` is a *slot*: a topic was already lost
# at 5b under its own code and the day would not pay for the facet run of the
# reserve topic that would have refilled it. `footage_evidence_quota` is a
# *topic*: it reached step 5b with no facet search behind it on a day that would
# not pay for one, so Trend Hunter (`footage_candidates.no_search_yet`) takes
# it out of `topics[]` into `skipped_topics[]` under this code instead of
# holding the batch for the reset (the user's rule of 2026-09-22, "no stage
# waits for a person": `no_waiting.POINTS` `hunter_quota_resume`, whose outcome
# reads "counted in the funnel as a loss"). Nothing else counts it - no
# reserve topic takes its slot (a refill costs the same facet run the day
# cannot buy, and `footage_candidates.our_losses()` reads `no_source` only) -
# so it is a loss of the `before_selection` step like `no_source`, counted in
# `losses` and in the headline, and in neither RESERVE_CODES nor
# SUBSTITUTION_CODES. It is still not `no_source`: no footage was looked for,
# and the name keeps a limit of ours from reading as a fact about the topic.
# Not a new refusal for CF-0320's ledger either: the topic carries no footage
# evidence, so it could not have become a ready video in this batch without the
# wait the rule forbids. On disk until 2026-10-13 it was never written - it
# appears the day the YouTube Search quota runs out.
FOOTAGE_EVIDENCE_QUOTA = "footage_evidence_quota"
# `footage_substitution.substitutions[].outcome`, the one value of the four
# that means the decision has not been executed: the facet search the substitute
# needs is a network call `footage_candidates.py` does not make, so the entry is
# written, the topic stays outside `topics[]`, and the run that has the search
# completes the same entry (it is never written twice).
PENDING_SEARCH = "pending_search"
POOL_DEPTH_KEY = "pool_depth"
UNEXPLAINED = "unexplained"
# CF-0438 (grill 2026-09-29): the fact rule takes any kind of fact now, and its
# refusal is `no_fact`. Batches written before carry `no_production_fact`; the
# funnel reads that word as `no_fact` (`canonical_code()`), so an old batch is
# counted under the new name and never reported as an unknown code. The old
# word is not in FUNNEL_CODES: nothing may write it any more.
NO_FACT = "no_fact"
# CF-0823/CF-0873: `fact_probe.source` of a refusal Trend Hunter took from its
# no-fact memory (agents/trend-hunter/scripts/no_fact_memory.py).
NO_FACT_MEMORY_SOURCE = "no_fact_memory"
# CF-0876: the dict a `pool_too_thin` row of 01 `skipped_topics[]` carries when
# Trend Hunter held the work back from its thin-pool memory before scoring
# (agents/trend-hunter/scripts/thin_pool_memory.py MEMORY_KEY).
THIN_POOL_MEMORY_KEY = "thin_pool_memory"
# CF-0708: `no_dated_source` was never a word of this vocabulary. The Trend
# Hunter's model coined it on `example-science/2026-10-12T2001Z` for a topic
# whose only news link it dropped as uncitable (`evidence_sources.py`: the
# Nature entry had no `published_at`) - which is a topic with no source, the
# stage's own `no_source`. The batch on disk keeps the word, so the funnel reads
# it under `no_source`; nothing may write it: the Trend Hunter's finished-batch
# check (`scripts/skipped_codes.py`, run by `check_scenes.py --check`) refuses
# any `skipped_topics[]` code outside FUNNEL_CODES, old words included.
LEGACY_CODES = {"no_production_fact": NO_FACT, "no_dated_source": "no_source"}


def canonical_code(code):
    """The name a recorded code is counted under: a pre-CF-0438 word mapped to
    its current one, everything else (and None) as it came."""
    return LEGACY_CODES.get(code, code)


def code_of(entry):
    """The code a recorded `skipped[]` / `refusals[]` / judge row is counted
    under: `canonical_code()` of its `reason_code`, and - the transition of
    CF-0434 - `held_back` with `gate: score_below_threshold` read as
    `score_below_threshold`."""
    if not isinstance(entry, dict):
        return None
    code = canonical_code(entry.get("reason_code"))
    if code == "held_back" and entry.get("gate") == SCORE_GATE:
        return SCORE_BELOW_THRESHOLD
    return code


FUNNEL_CODES = (
    "not_screened",             # selected, but 02-compliance-checker.json has no verdict for it
    "compliance_review",        # a compliance verdict took it off the batch: outside PRODUCTION_VERDICTS, or `review` in a batch judged before CF-0318 gave `review` a publication hold instead of a refusal
    RIGHTS_EXCLUSION,           # CF-0663: every evidence video refused by the indexer for a licence the channel does not take (`licence_refused`)
    "fetch_failed",             # its evidence video(s) failed to download (removed, unavailable, ...)
    INDEX_FAILED,               # CF-0281: its evidence video(s) came down and no index was written - ours, not YouTube's
    SOURCE_FOREIGN,             # CF-0299: its evidence video(s) were indexed and the sieve refused them - the shots showed somebody else's work
    SOURCE_BURNED_TEXT,         # CF-0299: same, refused for foreign text burned into the picture that the 9:16 crop does not take off (batches before CF-0435 only)
    SOURCE_TOO_LONG,            # CF-0302: its evidence video(s) were refused before any download - longer than the ceiling their nature is held to
    "no_source",                # no source was registered for it and no failure was recorded either
    FOOTAGE_EVIDENCE_QUOTA,     # CF-0317: dropped by Trend Hunter at 5b with no footage search behind it, on a day whose YouTube Search quota would not pay for one - a loss of a topic, not an empty slot (CF-0714)
    "no_second_source",         # fewer registered sources than TWO_SOURCE_FLOOR
    "pool_too_thin",            # fewer usable samples in the pool than the pattern's anchors
    "nothing_to_check",         # the stage had no material specific to the topic
    "thin_scene",               # no scene of the topic carried enough to write
    "held_back",                # the stage held the topic back by its own judgement
    SCORE_BELOW_THRESHOLD,      # CF-0434: its real penalties put it under the score threshold N - at 6b after the rounds, at the Editor or at the frame judge
    NO_FACT,                    # CF-0185/CF-0438: no fact behind the topic that passes the fact rule (was `no_production_fact`)
    "person_without_work",      # CF-0264: a person topic whose own news names no work to look a fact up for
    "already_published",        # CF-0019: the channel already published (or accepted) a video on the same work and the same news story - a repeat, refused before selection; CF-0865: also the Researcher's refusal after the fact (03 skipped[], stage scripts) - the same source, fact or text as an accepted video of the work
    "no_support_text",          # CF-0551: no support text for the topic's own event - no Wikipedia article of its own, or the episode its news is about has no description yet - refused before selection
    "below_shortlist",          # CF-0264: viable, but past scope.shortlist_size - unused reserve, not a refusal
    "reserve_unused",           # CF-0265: judged clear/caution, but the cut to the batch target had no slot left
    RESERVE_SUBSTITUTED,        # CF-0306: it was in reserve and took the slot of a topic the batch lost - a participant, not a spare
    RESERVE_EXHAUSTED,          # CF-0306: a slot came free and the reserve was empty - an empty slot, not a topic
    SEARCH_QUOTA_EXHAUSTED,     # CF-0313: a slot came free, the reserve had a topic, and the day's search calls would not pay for its footage search
    "pattern_undeliverable",  # refused before the render: the assigned pattern cannot be delivered
    "source_host_unlisted",     # refused before TTS: the host of the fact's source is in neither of the channel's two badge lists
    "story_claim_failed",       # CF-0533: the retelling's claims about real people failed the rule after the one rewrite (check_story_claims.py) - a loss of the scripts step
    "scale_unsupported",        # CF-0565: the scale comparison's arithmetic or footing failed after the one rewrite (check_scale.py) - a loss of the scripts step
    "plot_claim_failed",        # CF-0543: the retelling's claims about the plot (who killed / betrayed whom, who is whom, who died) had no link in their source after the one rewrite (check_story_claims.py) - a loss of the scripts step
    CLAIM_UNSUPPORTED,          # CF-0553: a claim of the finished text had no footing - the independent reader listed it undeclared, or the judge found its quote does not say it - after the one rewrite (or at once when it is the video's own fact): check_claims.py at the scripts step; the second compliance pass' check_claims_gate.py blocks with it too
    PLAN_UNASSEMBLED,           # CF-0411: the Editor's gates built no plan out of the script at the Researcher's step 6b, after the anchor-edit rounds - a loss of the `scripts` step
    "contribution_blocked",     # CF-0269: the second pass' contribution check (CF-0181) blocked the written script
    VIDEO_TOO_SHORT,            # CF-0293: refused before the render - under the channel's hard floor (30 s)
    "not_built",                # a cleared script the Editor neither rendered nor refused
    "qc_failed",                # rendered, and QC did not pass it
    "needs_you",                # rendered, and the Editor stopped on a NEEDS-YOU line
    FRAME_JUDGE_FAILED,         # CF-0298: rendered, QC passed it, and the frame judge did not - since CF-0434 only an unfinished judgement (a video under N is `score_below_threshold`)
    JUDGE_FOOTAGE_DEFECT,       # CF-0646: rendered, and the frame judge named a footage defect on the hard list (`score.hard.footage_defect`: thin_strip, cut_subject, smeared) - refused whatever its score, the operator rebuilds the topic once
    JUDGE_FOREIGN_CORE,         # CF-0539: rendered, over N after the judge, and refused by `frame_judge.foreign_core` - a picture of something else under the hook, or over FOREIGN_SHARE_MAX of the judged time (only in the channel's mode `fail`)
    UNEXPLAINED,                # no stage recorded anything: the loss the funnel exists to surface
    "compliance_review_hold",   # CF-0318: judged `review` and held from PUBLICATION - it kept its slot, its video is made, and it may not go up until the user signs. Not a loss
    "kept_on_own_graphics",     # CF-0689: under the source floor and kept by the Footage Indexer because the topic stands on the graphics the Editor draws itself (ExampleTech's `own_graphic` origin). Passes `two_sources`. Not a loss
)

# CF-0714: every word above in Russian, for the command center - the factory
# gives the line, the center never translates a code itself (the pattern of
# CF-0657's CHECK_REASONS_RU and CF-0676's REFUSALS_RU). One row per code of
# FUNNEL_CODES, no more and no less (tests/test_funnel.py checks both), so a new
# code arrives with its sentence. The sentence says what happened to the topic
# or the video in plain words; the English reason of the row stays the record.
REASONS_RU = {
    "not_screened": "тема попала в батч, а проверка прав её не оценила",
    "compliance_review": "проверка прав сняла тему с батча",
    RIGHTS_EXCLUSION: "источники темы не взяты по правам: лицензия, которую канал не принимает",
    "fetch_failed": "исходные видео темы не скачались",
    INDEX_FAILED: "исходники скачались, а индекс кадров не построился - сбой у нас",
    SOURCE_FOREIGN: "в исходниках оказалась чужая работа - кадры отсеяны",
    SOURCE_BURNED_TEXT: "в исходниках вшит чужой текст, который кроп не убирает",
    SOURCE_TOO_LONG: "исходные видео длиннее допустимого - не скачивались",
    "no_source": "для темы не нашлось футажа",
    FOOTAGE_EVIDENCE_QUOTA: "футаж для темы не искали: дневная квота поиска YouTube "
                            "кончилась, и тема ушла из батча, а не ждала сброса квоты",
    "no_second_source": "всё из одного источника",
    "pool_too_thin": "пул тоньше сценария",
    "nothing_to_check": "у стадии не было материала по теме",
    "thin_scene": "ни в одной сцене темы не хватило материала на сценарий",
    "held_back": "стадия придержала тему по своему суждению",
    SCORE_BELOW_THRESHOLD: "оценка ниже порога после штрафов",
    NO_FACT: "за темой не нашлось факта, проходящего правило фактов",
    "person_without_work": "тема о человеке, а в его новостях нет работы",
    "already_published": "ролик о той же работе с той же новостью или тем же фактом уже есть",
    "no_support_text": "о событии темы нет опорного текста (статьи или описания эпизода)",
    "below_shortlist": "запасная тема: в короткий список не вошла по рангу - не отказ",
    "reserve_unused": "запасная тема: прошла проверку, но места в батче не осталось - не отказ",
    RESERVE_SUBSTITUTED: "запасная тема заняла место выбывшей - участвует в батче",
    RESERVE_EXHAUSTED: "место выбывшей темы пустует: запас кончился",
    SEARCH_QUOTA_EXHAUSTED: "место выбывшей темы пустует: квота поиска YouTube не "
                            "оплатила поиск футажа для замены",
    "pattern_undeliverable": "назначенный шаблон ролика не собрать",
    "source_host_unlisted": "сайт источника факта нет ни в одном списке канала",
    "story_claim_failed": "утверждения пересказа о реальных людях не прошли проверку",
    "scale_unsupported": "сравнение масштаба не подтвердилось арифметикой или источником",
    "plot_claim_failed": "утверждения о сюжете не нашли опоры в источнике",
    CLAIM_UNSUPPORTED: "утверждение готового текста без опоры в источнике",
    PLAN_UNASSEMBLED: "монтажный план из сценария не собрался",
    "contribution_blocked": "вторая проверка прав заблокировала сценарий",
    VIDEO_TOO_SHORT: "ролик короче нижней границы канала",
    "not_built": "сценарий прошёл проверку, а ролик не собран и не отклонён",
    "qc_failed": "ролик собран и не прошёл контроль качества",
    "needs_you": "ролик собран, монтаж остановился на вопросе к человеку",
    FRAME_JUDGE_FAILED: "судья кадров не закончил оценку ролика",
    JUDGE_FOOTAGE_DEFECT: "судья кадров нашёл брак футажа из жёсткого списка",
    JUDGE_FOREIGN_CORE: "под началом ролика или в большой его доле - чужие кадры",
    UNEXPLAINED: "ни одна стадия не записала, почему тема выбыла",
    "compliance_review_hold": "ролик сделан и ждёт подписи перед публикацией - не потеря",
    "kept_on_own_graphics": "источников меньше нормы, тема держится на своей графике - не потеря",
}


# CF-0817: words a stage writes on a single source (a `failed[]` row, a
# dropped footage candidate, a pool refusal) that are not topic codes and so
# have no row in REASONS_RU. The center attaches `reason_ru` to any row with a
# `reason_code` (api/factory.with_reason_ru), so a source refused as a host
# show reads in Russian there too. A topic lost to one is counted under its
# topic code (`host_show` -> `source_foreign`), never under this word.
SOURCE_REASONS_RU = {
    HOST_SHOW: "чужой ведущий в кадре (подкаст, интервью, шоу) - источник не взят",
}


# CF-0888: the codes compliance writes on `02 -> refill_refused[]` when it
# judges a topic from below the shortlist on the fly (CF-0882, the agent's
# scripts/judge_below_shortlist.py `_refuse`): `refill_screen` - the machine
# screen found a forbidden-topic term. Not a topic-loss code (a refused one was
# never in the batch), so it lives beside REASONS_RU and not in FUNNEL_CODES.
REFILL_SCREEN = "refill_screen"
REFILL_REFUSAL_CODES = (REFILL_SCREEN,)
REFILL_REASONS_RU = {
    REFILL_SCREEN: "запасная тема из-под короткого списка не прошла проверку на лету: "
                   "в сценах или заголовках запретная тема канала",
}


def reason_ru(code):
    """The Russian line of a recorded code for the center: the row of its
    current name (`canonical_code`), then - CF-0817 - the row of a source-level
    word (SOURCE_REASONS_RU), then - CF-0888 - the row of a refill refusal
    (REFILL_REASONS_RU), or None for a word outside the vocabulary - an
    unknown code is a contract defect to show as such, not to translate."""
    c = canonical_code(code)
    return REASONS_RU.get(c) or SOURCE_REASONS_RU.get(c) or REFILL_REASONS_RU.get(c)


def refill_reason_ru(code):
    """CF-0888: the Russian line of a `02 -> refill_refused[]` code - the
    refill's own sentence first, then `reason_ru`."""
    return REFILL_REASONS_RU.get(canonical_code(code)) or reason_ru(code)


def host_show_counts(th, idx):
    """CF-0817: the sources refused as somebody else's host show, by where -
    `dropped` (Trend Hunter's `topics[].evidence.footage_candidates_dropped[]`
    rows with `reason_code: host_show`), `at_pool` (the indexer's pool check,
    `01b` -> `pool_sources.topics[].sources[]` refused under `host_show`) and
    `at_sieve` (the sieve's guard, `01b` -> `failed[]`). Each is a count of
    distinct (topic, video) pairs; None when all three are zero, so a batch
    before CF-0817 or one with no host show says nothing."""
    dropped, at_pool, at_sieve = set(), set(), set()
    for t in _rows(th, "topics"):
        ev = t.get("evidence") if isinstance(t.get("evidence"), dict) else {}
        for r in ev.get("footage_candidates_dropped") or ():
            if isinstance(r, dict) and r.get("reason_code") == HOST_SHOW:
                dropped.add((t.get("topic_id"), r.get("video_id") or r.get("id")))
    pool = (idx or {}).get("pool_sources") if isinstance(idx, dict) else None
    for tid, b in ((pool or {}).get("topics") or {}).items() if isinstance(pool, dict) else ():
        for r in (b or {}).get("sources") or () if isinstance(b, dict) else ():
            if isinstance(r, dict) and r.get("reason_code") == HOST_SHOW:
                at_pool.add((tid, r.get("video_id")))
    for f in _rows(idx, "failed"):
        if f.get("reason_code") == HOST_SHOW:
            at_sieve.add((f.get("topic_id"), f.get("video_id")))
    out = {"dropped": len(dropped), "at_pool": len(at_pool), "at_sieve": len(at_sieve)}
    return out if any(out.values()) else None


# The codes above that are a topic held back for want of a slot rather than a
# topic lost. They are named, counted and rendered - in their own column, never
# in `losses` and never in the "N of M topics lost" headline (CF-0265).
RESERVE_CODES = ("below_shortlist", "reserve_unused")

# CF-0306's two codes, which are neither losses nor reserve. They are named and
# drawn in the table like everything else, and they are in no `losses` count:
# a refilled slot is not a loss (the topic is in `selected` and walks the whole
# chain), and an empty one is a loss the funnel has already counted once -
# under the code of the topic that vacated it, at the step that lost it.
# Counting either would be the mirror of the `fetched: 5` overstatement, and
# `reserve_substituted` is kept out of the headline's "went past a bar they did
# not clear" for the same reason: a substituted topic cleared everything asked
# of it. CF-0313 adds a third on the same terms and for the same arithmetic -
# a slot left unfilled because the day's search quota would not pay for the
# footage search is an empty slot, not a topic, and the topic that vacated it
# is counted at the step that lost it.
SUBSTITUTION_CODES = (RESERVE_SUBSTITUTED, RESERVE_EXHAUSTED, SEARCH_QUOTA_EXHAUSTED)

# The codes only CF-0264's selection pass writes into
# `01-trend-hunter.json` -> `skipped_topics[]`. Their presence (or a `selection`
# summary, or a `cut` in the compliance artifact) is what tells the funnel it is
# reading a batch that ran under the shortlist, and so whether the
# `before_selection` step exists at all - a batch written before 2026-09-17 has
# none of the three and is read exactly as it was before this change.
# CF-0019 adds `already_published`: the same pass checks each candidate against
# the channel's published/accepted videos before the fact probe and refuses a
# repeat of the same work and the same story. It is a loss, not a reserve code.
# CF-0551 adds `no_support_text`: after the fact, the same pass reads the
# topic's support text (Wikipedia: the work, its season, the episode
# descriptions) and refuses a topic with none for its own event. A loss.
SHORTLIST_CODES = ("person_without_work", "below_shortlist", NO_FACT, "already_published",
                   "no_support_text")

# Two questions with two answers since CF-0318 (the user's decision, grill of
# 2026-09-22): *who gets made* and *who may be uploaded*. Until then one name
# answered both, because until then they had the same answer - `review` was "a
# refusal, not a queue" (grill of 2026-09-16): nobody looks at a batch while it
# runs, so a topic parked for review was a topic dropped. This module put a
# price on that reading - `compliance_review` cost 19 topics of 101 across ten
# instrumented runs, second only to `no_production_fact` - and the user decided
# that without a human's approval only the **publication** of a video is
# forbidden. The video itself is made without one.
#
# The verdict is not milder for it. `review` is still `review`, still earned by
# a rights-holder match at `high` or a real sensitivity flag, and the video that
# comes out of a `review` topic is still not publishable. What moved is what it
# blocks: the topic keeps its slot and carries a `publication_hold` block on its
# row plus a row in `publish/publication-holds.json`
# (agents/compliance-checker/scripts/publication_hold.py), which Publisher
# (CF-0017/CF-0018) must treat as a hard stop until the user signs it.
PRODUCTION_VERDICTS = ("clear", "caution", "review")
PUBLISH_VERDICTS = ("clear", "caution")
# The old name, kept and narrowed to the one question it can still answer on its
# own: who may go up with no signature. Two other repositories spell the same
# pair rather than import it - `cut_shortlist.PUBLISH_VERDICTS` and
# `publication_hold.PUBLISH_VERDICTS`; the three files share only the artifact.
# No step of the funnel reads it any more: a step asks `_goes_on()`, which is
# the production question plus the hold.
PASS_VERDICTS = PUBLISH_VERDICTS
REVIEW_VERDICT = "review"

# CF-0318: the block the compliance pass stamps on a held row
# (`publication_hold.MARK_KEY`) and the code it carries
# (`publication_hold.REASON_CODE` - deliberately not `compliance_review`, which
# is the code of a topic the gate *lost*).
#
# The presence of the block is also the only thing that tells this module which
# rule a batch was judged under, and that matters more than it looks: a `review`
# row with no block is a row from before 2026-09-22, when the verdict really did
# take the topic off at the indexer. Such a row is still read - and still
# counted - exactly as it always was. Reading every old `review` as a hold would
# be the funnel declaring ten recorded runs mistaken after the fact, which is
# the one thing a record of what happened may never do.
PUBLICATION_HOLD_KEY = "publication_hold"
COMPLIANCE_HOLD = "compliance_review_hold"

# The codes that are a video held back from publication rather than a topic
# lost. Named, counted and drawn in their own column and their own line, never
# in `losses` and never in the "N of M topics lost" headline - the same standing
# RESERVE_CODES has, and for the mirror-image reason: a reserve topic has no
# slot and would be publishable if it had one, a held topic has a slot and a
# finished video and may not be published.
HOLD_CODES = (COMPLIANCE_HOLD,)

# CF-0689, 2026-10-12: a topic under the source floor that the Footage Indexer
# did not refuse, because its channel's base footage is the graphics the Video
# Editor draws from the script's facts (`own_graphic`, ExampleTech) and Trend
# Hunter counted enough quotable facts under it
# (`evidence.own_graphic_footing.meets_floor`). The indexer records each one in
# `01b-footage-index.json` -> `own_graphic_footing.kept[]` (with the refusal it
# replaces) and lists the ids in `two_source_floor.kept_on_own_graphics`. The
# funnel counts it as passing `two_sources` - it passed the floor the channel
# sets - and names it beside the step in a list of its own, the same standing
# HOLD_CODES has: counted in the step, in no `losses`, never silent. Only a
# topic on that list is exempt; every other topic under the floor is read
# exactly as before.
OWN_GRAPHIC_KEY = "own_graphic_footing"
OWN_GRAPHIC_KEPT = "kept_on_own_graphics"
KEPT_CODES = (OWN_GRAPHIC_KEPT,)

# What a `compliance_review` row gets said about it when the verdict was
# `review` and the row carries no hold. Without this sentence the funnel would
# print, on a batch from 2026-09-21, a code whose current meaning contradicts
# what that batch did.
OLD_REVIEW_NOTE = (
    ". Judged before CF-0318 (2026-09-22): the row carries no "
    "`" + PUBLICATION_HOLD_KEY + "`, so in this batch a `review` did take the topic off - "
    "which is what the run recorded and what this line says. A `review` judged since keeps "
    "its slot and holds the upload instead"
)

# CF-0181 / CF-0269: the second verdict a compliance row can carry - the
# contribution check, on its own scale. `pass` or `block`, "nothing softer, and
# separate from the rights/risk verdict" (check_contribution.py), because
# CF-0043 refused to flag a weak contribution for a human to look at. So a row
# may read `verdict: clear` and still be a refusal, which is precisely how
# `lf-2026-09-17-006-script1` went missing: the funnel read one of the two.
CONTRIBUTION_KEY = "contribution_check"
# CF-0553: a claim without footing. Written by the Researcher's check_claims.py
# into 03 skipped[] (stage `scripts`) and by the second compliance pass'
# check_claims_gate.py as `contribution_check.failures[].reason_code` of a
# block; a block whose every failure is this one is counted under this code,
# not as `contribution_blocked`.
CONTRIBUTION_BLOCK = "block"

# CF-0129 / DoD 1.4.4 item 2, and patterns/validate_patterns.py
# VIDEO_EDITOR_GATE_MIN_REQUIRED - the same 2. Spelled again rather than
# imported: shared/runlog/ is stdlib-only and does not reach into patterns/.
TWO_SOURCE_FLOOR = 2

# CF-0293 item 3: where a finished video's length verdict sits inside a
# `videos[]` entry of `05-video-editor.json`. The Editor has written it since
# CF-0158 - `judge_video_length()`'s whole record, the root's arithmetic, not
# a second opinion - and until this task nothing read it back out: a batch
# could deliver three videos under the band and the summary said nothing.
#
# The two strings are the root's `VIDEO_LENGTH_VERDICTS`, spelled here for the
# same reason TWO_SOURCE_FLOOR is: shared/runlog/ is stdlib-only and does not
# reach into patterns/. tests/test_funnel.py checks them against
# patterns/validate_patterns.py, so a divergence is a failing test, not drift.
VIDEO_LENGTH_PATH = ("duration", "narration", "video_length")
VIDEO_LENGTH_SHORT = "short"        # under total_seconds_min: made, warned, counted here
VIDEO_LENGTH_IN_BAND = "in_band"

# CF-0232, grill of 2026-09-16: the two numbers a channel aims its batch with -
# `channels/<id>.json` -> `scope`. The funnel is the only code in the root that
# reads `target_ready_videos_per_batch`, on purpose: it is a target to read the
# last step against, never a floor to pad a batch up to. A batch may deliver
# fewer, and a video that cannot carry its pattern is refused rather than
# counted (DoD 1.4.4 item 3).
TARGET_READY_KEY = "target_ready_videos_per_batch"
MAX_TITLES_KEY = "max_titles_per_batch"
# CF-0264: how many viable topics Trend Hunter hands out, in scoring order. Not
# a target - the target is still MAX_TITLES_KEY, and the cut down to it happens
# after compliance (CF-0265). Read here only to say the shortlist's size beside
# the selected count.
SHORTLIST_KEY = "shortlist_size"

ARTIFACTS = ("01-trend-hunter.json", "02-compliance-checker.json", "01b-footage-index.json",
             "03-content-researcher.json", "04-compliance-checker.json", "05-video-editor.json")

# CF-0298: the frame judge's artifact, and the vocabulary written into it. It is
# read *beside* ARTIFACTS rather than added to it on purpose: every batch before
# 2026-09-20 was never judged, and a missing 06 there is "nobody looked", not a
# hole in the record - listing it in `missing` would put a line about an absent
# artifact under every old batch's funnel and read like a defect. A batch with no
# 06 keeps exactly the shape it had before this task.
FRAME_JUDGE_FILE = "06-frame-judge.json"
OPTIONAL_ARTIFACTS = (FRAME_JUDGE_FILE,)
FRAME_JUDGE_SCHEMA = "frame-judge/2"                # what the gate script writes
# CF-0434: `/2` scores the verdicts (score.judge_* in shared/gate-prices.json)
# and refuses only a video whose score falls under N; `/1` (2026-09-20 ..
# 2026-09-29) refused on any `contradicts`, `foreign` or foreign text. Both are
# read - an old batch keeps the record it was judged under.
FRAME_JUDGE_SCHEMA_V1 = "frame-judge/1"
FRAME_JUDGE_SCHEMAS = (FRAME_JUDGE_SCHEMA_V1, FRAME_JUDGE_SCHEMA)
FRAME_JUDGE_VERDICTS_SCHEMA = "frame-judge-verdicts/1"   # what the judge hands the gate
FRAME_JUDGE_PACK_SCHEMA = "frame-judge-pack/1"      # what the Editor's packer builds

# The judge's four words, in the order they run from "the picture carries the
# sentence" to "the picture is not about this title at all". `neutral` is
# counted and never rejects (the user's decision of 2026-09-20): a reaction shot
# under a factual line is weak, not wrong, and a gate that refused it would
# refuse most of the footage this channel legally has.
FRAME_VERDICTS = ("backs", "neutral", "contradicts", "foreign")
BLOCKING_VERDICTS = ("contradicts", "foreign")     # the `/1` rule; `/2` prices them
NEUTRAL_VERDICT = "neutral"
# CF-0434 (grill 2026-09-29, task item 4): what each word costs is the price
# table's, not the judge's and not this module's - these are only the rule
# names. `backs` costs nothing. Foreign on-screen text the judge writes down
# (`foreign_text`) is priced as `foreign` on that entry until the grill on
# burned-in text (ROADMAP 1.4.7: "`foreign` от судьи до гриля «вшитый текст» -
# штраф, а не отказ"); an entry that is both is charged once.
JUDGE_RULES = {"neutral": "score.judge_neutral", "contradicts": "score.judge_contradicts",
               "foreign": "score.judge_foreign"}
# CF-0877 (wicker 0841Z, the-gilded-age 0836Z, both refused by the user as
# `wrong_person_on_name`): a `contradicts` whose mismatch is `person` - the line
# names someone and the frame shows another person - is its own kind with its
# own price, `score.judge_wrong_person` (x2 in the hook), charged in place of
# `score.judge_contradicts` on that entry. Signed by the user on 2026-10-27 and in
# shared/gate-prices.json#rules; a table without the row in `rules` charges
# `score.judge_contradicts` exactly as before (scripts/frame_judge_gate.py).
JUDGE_WRONG_PERSON_RULE = "score.judge_wrong_person"

# What the gate script writes into each judged video's `gate` field.
# `incomplete` is not a softer `reject`: it means the judgement itself is
# unfinished (an entry of the pack with no verdict), and an unfinished
# judgement cannot say a video is ready - so it takes the video off `ready`,
# with its own sentence. Since CF-0434 a `reject` is a score under N
# (`score_below_threshold`), and `frame_judge_failed` is left to `incomplete`
# alone (and to the `/1` records written before).
GATE_PASS, GATE_REJECT, GATE_INCOMPLETE = "pass", "reject", "incomplete"
GATE_STATES = (GATE_PASS, GATE_REJECT, GATE_INCOMPLETE)

# CF-0539 (WNL of example-film/2026-10-05T0701Z): three `foreign` entries - an
# interview of the host on another talk show's set under "Taylor Sterling walks
# into the monologue", "a full Studio 8H crowd" - cost 36 points and the video
# passed at E 64 over N 40. A price can never refuse a picture of the wrong
# show once the rest of the video is clean, so the gate gets a rule of its own,
# `frame_judge.foreign_core`, read off the verdict rows alone (the gate script
# and the price replay of shared/runlog/gate_price.py call this one function):
#
#   a `foreign` entry that starts in the hook (before FOREIGN_HOOK_SECONDS, the
#   score model's hook) - the first seconds are where the story is promised;
#   or the `foreign` entries covering FOREIGN_SHARE_MAX of the judged time or
#   more (the union of the spans, so a meme over a block is not counted twice).
#
# Only the verdict `foreign` counts: foreign on-screen text keeps its own road
# (priced as foreign until the grill on burned-in text). The threshold, from
# every judged batch on disk (2026-10-05): the videos the user accepted carried
# at most 6 % foreign (backrooms of rebuilds/2026-09-27T1757Z, 2.8 s of 47.4 s;
# american-dread-story 2210Z, 5 %) and none of them in the hook; the ones the
# user refused for the picture carried 22 % (vanguards-doomsday 0705Z) and 41 %
# (vanguards-endgame-encore 1248Z); WNL 0701Z carries 33 % with block-0 in the
# hook. 15 % sits in that gap with more than twice the accepted maximum below it.
# "A scene anchor under foreign" was measured too and is NOT a rule: it would
# have refused both accepted videos above (their one foreign block carried an
# anchor). The mode is the channel's (`frame_judge.foreign_core.mode`, `warn`
# until the user signs the refusal - CF-0320), never this module's.
FOREIGN_CORE_RULE = "frame_judge.foreign_core"
FOREIGN_CORE_FAIL, FOREIGN_CORE_WARN = "fail", "warn"
FOREIGN_CORE_MODES = (FOREIGN_CORE_WARN, FOREIGN_CORE_FAIL)
FOREIGN_CORE_DEFAULT_MODE = FOREIGN_CORE_WARN
FOREIGN_SHARE_MAX = 0.15
FOREIGN_HOOK_SECONDS = 5.0      # shared/score/score.py HOOK_SECONDS, spelled again: no import cycle


def _span_of(r):
    s, e = r.get("start"), r.get("end")
    ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (s, e))
    return (float(s), float(e)) if ok and e > s else None


def _union_seconds(spans):
    total, cur = 0.0, None
    for s, e in sorted(spans):
        if cur is None or s > cur[1]:
            if cur is not None:
                total += cur[1] - cur[0]
            cur = [s, e]
        else:
            cur[1] = max(cur[1], e)
    return total + (cur[1] - cur[0] if cur else 0.0)


def foreign_core(rows, share_max=FOREIGN_SHARE_MAX, hook_seconds=FOREIGN_HOOK_SECONDS):
    """CF-0539: what `frame_judge.foreign_core` reads off one video's verdict
    rows (`verdict`, `entry`, `start`, `end` - the rows of `06-frame-judge.json`
    `videos[].verdicts`, one per judged entry):

        {"rule", "hook_entries", "foreign_entries", "foreign_seconds",
         "judged_seconds", "share", "share_max", "hook_seconds", "refuses", "why"}

    `refuses` is the rule's answer whatever the mode; the mode is the caller's."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    foreign = [r for r in rows if r.get("verdict") == "foreign"]
    hook = [r.get("entry") for r in foreign
            if _span_of(r) is not None and _span_of(r)[0] < hook_seconds]
    fsec = _union_seconds([x for x in map(_span_of, foreign) if x])
    total = _union_seconds([x for x in map(_span_of, rows) if x])
    share = round(fsec / total, 4) if total else None
    over = share is not None and share >= share_max
    why = []
    if hook:
        why.append(f"`foreign` in the hook (before {hook_seconds:g} s): {', '.join(hook)}")
    if over:
        why.append(f"`foreign` over {fsec:.1f} s of {total:.1f} s judged - {share:.0%}, "
                   f"at or over {share_max:.0%}")
    return {"rule": FOREIGN_CORE_RULE, "hook_entries": hook,
            "foreign_entries": [r.get("entry") for r in foreign],
            "foreign_seconds": round(fsec, 2), "judged_seconds": round(total, 2),
            "share": share, "share_max": share_max, "hook_seconds": hook_seconds,
            "refuses": bool(hook or over),
            "why": ("; ".join(why) + " - a picture of something else under the core of "
                    "the story (CF-0539)") if why else None}


# The five steps of DoD 1.4.4 item 1, in order: key -> the label a reader sees.
# One place, because the funnel's JSON (`steps[].step`) and its table have to
# agree about what the steps are called, and CF-0252 reads the same result.
STEPS = (
    ("selected", "selected"),
    ("after_compliance", "after compliance"),
    ("two_sources", f"with {TWO_SOURCE_FLOOR} sources"),
    ("scripts", "scripts"),
    ("ready", "ready"),
)

# CF-0265, 2026-09-17: one step *before* the five, and it is drawn only for a
# batch that ran under the shortlist. Until 2026-09-17 Trend Hunter cut to
# `max_titles_per_batch` itself, so `topics[]` *was* the selection and there was
# nothing between the stage and `selected` to draw. Since CF-0264 the stage
# hands out up to `scope.shortlist_size` (8) topics and the selection happens
# after compliance, so "before selection" is a real place with its own
# survivors (the shortlist), its own refusals (`person_without_work`,
# `no_production_fact`, `no_source`) and its own reserve (`below_shortlist`).
# A batch with none of the CF-0264 marks does not get the step and renders
# exactly as it did before - the old batches on disk are the regression corpus
# for that (tests/test_funnel.py).
BEFORE_SELECTION = ("before_selection", "before selection")

# CF-0269, 2026-09-18: one step *between* `scripts` and `ready`, drawn on the
# same terms - only for a batch whose second compliance pass refused a script
# (or waved one past). `04-compliance-checker.json` was already read for its
# rights/risk verdict, but only inside the `ready` step and never for its
# contribution verdict, so a script the contribution check blocked came out as
# `not_built` - the Editor's silence read as the Editor's decision. The pass
# now owns its own row, and `ready` starts from what it cleared.
AFTER_COMPLIANCE_2 = ("after_compliance_2", "after compliance 2")

# CF-0298, 2026-09-20: one step *after* `ready`, drawn only for a batch that was
# judged - a batch carrying `06-frame-judge.json`. `ready` still means what it
# always meant (the Editor rendered it and QC passed it); what changed is that
# the batch no longer ends there. The last step of a judged batch is this one,
# so "N selected -> M ready" in the headline counts what survived the judge, and
# a video whose picture was about another film is not in it. A batch written
# before this task has no 06, gets no row, and reads exactly as it did.
FRAME_JUDGE = ("frame_judge", "frame judge")

# The three steps that exist only for the batches that need them; every other
# step is in every funnel. Named so that a reader of `steps[]` (and the tests)
# has one place to ask whether a missing row is a defect or a batch that had
# nothing to put in it.
OPTIONAL_STEPS = (BEFORE_SELECTION[0], AFTER_COMPLIANCE_2[0], FRAME_JUDGE[0])


def _all_steps(mandatory):
    """The five mandatory steps with the three optional ones spliced in where
    each is drawn. Spelled as a splice rather than an index so that inserting a
    step into STEPS cannot silently move `after compliance 2` somewhere else."""
    out = [BEFORE_SELECTION]
    for step in mandatory:
        out.append(step)
        if step[0] == "scripts":
            out.append(AFTER_COMPLIANCE_2)
        if step[0] == "ready":
            out.append(FRAME_JUDGE)
    return tuple(out)


ALL_STEPS = _all_steps(STEPS)
STEP_LABELS = dict(ALL_STEPS)


# --------------------------------------------------------------------------
# reading the artifacts
# --------------------------------------------------------------------------

def read_artifacts(batch_dir):
    """{name: parsed dict} for every artifact of ARTIFACTS present and readable,
    plus ("_missing", ...) and ("_errors", ...). Never raises.

    OPTIONAL_ARTIFACTS are read on the same terms but never land in `_missing`:
    absent means the stage did not run for this batch, which is a thing to say
    in its own step and not a hole in the record (CF-0298)."""
    out, missing, errors = {}, [], []
    bd = Path(batch_dir) if batch_dir else None
    for name in ARTIFACTS + OPTIONAL_ARTIFACTS:
        optional = name in OPTIONAL_ARTIFACTS
        if bd is None or not (bd / name).is_file():
            if not optional:
                missing.append(name)
            continue
        p = bd / name
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append(f"{name}: unreadable ({e})")
            continue
        if not isinstance(d, dict):
            errors.append(f"{name}: not an object")
            continue
        out[name] = d
    out["_missing"], out["_errors"] = missing, errors
    return out


def _channel_ids():
    """shared/channel_ids.py, loaded by path (CF-0231 / tests/
    test_module_path_loading.py: `shared` is a guarded directory and a bare
    `import channel_ids` would only work by accident of how we were reached)."""
    path = Path(__file__).resolve().parents[1] / "channel_ids.py"
    try:
        spec = importlib.util.spec_from_file_location("channel_ids_for_funnel", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                   # noqa: BLE001
        return None


def target_of(batch_dir, artifacts=None, root=None):
    """{"channel", "config", "ready", "max_titles"} from the channel's config, or
    None when it cannot be found. The channel is the `channel` field the batch
    froze into its own artifacts, and it is resolved through `former_channel_ids`
    *at the door* - in the same statement that reads the field, so a former id is
    never held in a local and looked up later (CF-0197): the 2026-09-09 batch
    says `legacy-film` and the config is `example-film.json`. The directory
    name a batch sits under is a frozen record for the same reason and gets the
    same treatment."""
    A = artifacts if artifacts is not None else {}
    cid = _channel_ids()
    # CF-0801: `root` - the factory root a caller already holds (the run
    # executor's, for `run_checks reserve_after_judge`); None reads the env's.
    root = root if root is not None else runlog.factory_root()
    if cid is None or not (Path(root) / "channels").is_dir():
        return None
    channel = None
    try:
        for art in ("01-trend-hunter.json", "02-compliance-checker.json",
                    "05-video-editor.json"):
            channel = cid.resolve_channel((A.get(art) or {}).get("channel"), root=root)
            if channel:
                break
        if not channel and batch_dir:
            channel = cid.resolve_channel(Path(batch_dir).parent.name, root=root)
        if not channel:
            return None
        p = cid.channel_config_path(channel, root=root)
        scope = (json.loads(Path(p).read_text(encoding="utf-8")) or {}).get("scope") or {}
    except Exception:                                   # noqa: BLE001
        return None
    ready, cap = scope.get(TARGET_READY_KEY), scope.get(MAX_TITLES_KEY)
    if ready is None and cap is None:
        return None
    return {"channel": channel, "config": f"channels/{channel}.json",
            "ready": ready, "max_titles": cap, "shortlist": scope.get(SHORTLIST_KEY)}


def _rows(d, key):
    v = (d or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _substitutions(idx):
    """CF-0306: ({topic_id: its substitution row}, [the unmatched rows]) of
    `01b-footage-index.json` -> `reserve_substitution`.

    The indexer writes the block whenever a slot came free after the cut and it
    refilled the slot from the reserve - on its own first pass, inside the
    sieve (CF-0299), or on the second call the orchestrator makes with
    `--reserve-for` after a Researcher refusal. `substitutions[]` is who took
    whose place and why the place came free; `unmatched[]` is a slot the
    reserve could not fill (`reserve_exhausted`). Every batch before 2026-09-21
    carries no block at all, and its absence is what keeps such a batch reading
    exactly as it did - the batches on disk are the regression corpus for that.
    """
    block = (idx or {}).get(SUBSTITUTION_KEY)
    if not isinstance(block, dict):
        return {}, []
    subs = {s["topic_id"]: s for s in _rows(block, "substitutions") if s.get("topic_id")}
    return subs, _rows(block, "unmatched")


def _footage_substitutions(th):
    """CF-0313: ([the refills], [the decisions nothing has executed yet],
    [the slots nobody filled]) of `01-trend-hunter.json` ->
    `footage_substitution`.

    The split is `promoted`, and it is the stage's own word rather than a
    reading of `outcome`: `promoted: true` means the substitute is in
    `topics[]` and has walked step 5b (whatever came of that walk), and
    `promoted: false` means the slot is still empty - either because the facet
    search has not been run (`outcome: pending_search`) or because the reserve
    row held no topic to put back (`unusable_record`, whose slot went on down
    the queue and is answered by another row of the block). `unmatched[]` is
    the slot nothing could be offered for at all, with its own code.

    Every batch before 2026-09-22 carries no block, and its absence is what
    keeps such a batch reading exactly as it did - the live batches are the
    regression corpus for that."""
    block = (th or {}).get(FOOTAGE_SUBSTITUTION_KEY)
    if not isinstance(block, dict):
        return [], [], []
    subs = _rows(block, "substitutions")
    return ([s for s in subs if s.get("promoted")],
            [s for s in subs if not s.get("promoted")],
            _rows(block, "unmatched"))


def _pool_depth(idx):
    """CF-0304: ({topic_id: its depth record}, {the ids in `thin[]`}) of
    `01b-footage-index.json` -> `pool_depth`.

    A thin pool is not a refusal - the topic goes to the Researcher exactly as
    it would have - it is the indexer saying the refusal is likely and that its
    cause is the footage rather than the writing. The funnel never re-derives
    it: `thin[]` is the indexer's own list and the record beside it carries the
    numbers (`usable_shots`, `floor`) and why the walk for more footage stopped
    (`exhausted`).
    """
    block = (idx or {}).get(POOL_DEPTH_KEY)
    if not isinstance(block, dict):
        return {}, set()
    recs = {r["topic_id"]: r for r in _rows(block, "topics") if r.get("topic_id")}
    thin = block.get("thin") if isinstance(block.get("thin"), list) else []
    return recs, {t for t in thin if isinstance(t, str)}


def _verdicts(d, keys=("topic_id", "script_id")):
    """{the row's id: the whole result row} of a compliance artifact, keyed by the
    first of `keys` the row carries.

    The order is the caller's, because the two passes are asked different
    questions: the first pass judges topics and is looked up by `topic_id`, the
    second judges written scripts and is looked up by `script_id`. Until
    2026-09-17 a second-pass row carried only `script_id`, so a fixed
    "topic_id or script_id" happened to answer both - and then
    `example-film/2026-09-17T1901Z` wrote both ids into every row of
    `04-compliance-checker.json`, the lookup started keying that artifact by
    topic, and every `v04.get(script_id)` came back `None`: the whole second
    pass read as "no verdict for this script" and its refusals fell through to
    the Editor's step as `not_built` (CF-0269). A richer artifact must not be
    able to blind a reader of it, so the key is now named rather than guessed."""
    out = {}
    for r in _rows(d, "results"):
        k = next((r[k] for k in keys if r.get(k)), None)
        if k:
            out[k] = r
    return out


# CF-0917 (example-tech/2026-11-04T0835Z): the contract between the Researcher's
# 03 and the second compliance pass' 04. Every script of `03 -> scripts[]` owes
# a row of `04 -> results[]` under its own `script_id`, and - the claims gate of
# CF-0553 being step 5a of the compliance SKILL on every channel, "not
# optional" - a `claims_gate` on that row. The 0835Z operator keyed its three
# rows by the topic id (`lf-2026-11-04-016` for `...-016-script1`), wrote no
# `claims_gate`, and closed `done`; the Editor found "no row for the -script1
# ids", rendered nothing and closed, and the funnel read the three scripts as
# unjudged-and-cleared, then lost them at 05 as SILENT. Read by the executor
# (shared/run_checks.py compliance_rows: the stage is failed, not done) and by
# the triage (the break is the compliance pass's, not the Editor's).
CLAIMS_GATE_KEY = "claims_gate"         # = check_claims_gate.GATE_KEY (compliance-checker)
COMPLIANCE_ROWS_KEY = "compliance_rows"  # funnel(): _rows_record() - the missing rows
SCRIPTS_04_FILE = "04-compliance-checker.json"


def compliance_rows_break(cr, c04, strict=True, claims_gate=True):
    """What `04` (`c04`) owes `03` (`cr`) and does not give, or None when it
    keeps the contract (or one of the two is not there to compare):

        {"scripts": n, "rows": n, "missing": [script ids of 03 with no row],
         "extra": [row ids naming no script of 03], "no_claims_gate": [script
         ids whose row lacks it], "line": one sentence}

    `strict` False (a pass that merges new rows into an existing 04, the judge
    round's `updates`) leaves `extra` out of the verdict: a row of a script the
    round replaced is harmless. `claims_gate` False leaves the gate out."""
    if not isinstance(cr, dict) or not isinstance(c04, dict):
        return None
    sids = [s.get("script_id") for s in _rows(cr, "scripts") if s.get("script_id")]
    rows = _rows(c04, "results")
    by = {r["script_id"]: r for r in rows if r.get("script_id")}
    missing = [s for s in sids if s not in by]
    extra = sorted({r.get("script_id") or r.get("topic_id") or "?" for r in rows
                    if r.get("script_id") not in sids})
    no_gate = ([s for s in sids if s in by and not isinstance(by[s].get(CLAIMS_GATE_KEY), dict)]
               if claims_gate else [])
    if not (missing or no_gate or (strict and extra)):
        return None
    bits = []
    if missing:
        bits.append(f"{len(missing)} of {len(sids)} script(s) of 03 have no row under their "
                    f"script_id ({', '.join(missing[:4])}{' ...' if len(missing) > 4 else ''})")
    if extra:
        bits.append(f"{len(extra)} row(s) name no script of 03 ({', '.join(extra[:4])}"
                    f"{' ...' if len(extra) > 4 else ''})")
    if no_gate:
        bits.append(f"{len(no_gate)} row(s) carry no `{CLAIMS_GATE_KEY}` "
                    f"({', '.join(no_gate[:4])}{' ...' if len(no_gate) > 4 else ''}) - "
                    f"check_claims_gate.py --write did not write them (CF-0553)")
    return {"scripts": len(sids), "rows": len(rows), "missing": missing, "extra": extra,
            "no_claims_gate": no_gate,
            "line": f"{SCRIPTS_04_FILE} does not answer 03-content-researcher.json: "
                    + "; ".join(bits)}


def _rows_record(cr, c04, cleared, v04):
    """The funnel's COMPLIANCE_ROWS_KEY: compliance_rows_break(strict=False,
    claims_gate=False) - the rows a script is lost for want of; a row without
    its `claims_gate` loses nothing here, the executor fails the stage on it
    (run_checks.compliance_rows) - plus `cleared_with_row` - the scripts 04 judged and let through, i.e. what
    the Editor had to build. Empty with `missing` set means the Editor was
    starved by the broken 04, not by its own doing (the triage reads that)."""
    brk = compliance_rows_break(cr, c04, strict=False, claims_gate=False)
    if brk is not None:
        brk["cleared_with_row"] = [s for s in cleared if s in v04]
    return brk


def _risk(row):
    """"rights high", "sensitivity flagged", ... - why the verdict came out that way.
    The two checks do not report the same way: `rights_holder_check` carries a
    `risk_level`, `content_sensitivity_check` usually only `flagged` (see the
    2026-09-09 batch, where the two content-sensitivity `review`s carry no level
    at all and would read as "no reason given" if only the level were looked at)."""
    bits = []
    for key, short in (("rights_holder_check", "rights"),
                       ("content_sensitivity_check", "sensitivity")):
        c = row.get(key)
        if not isinstance(c, dict):
            continue
        lvl = c.get("risk_level")
        if lvl:
            bits.append(f"{short} {lvl}")
        elif c.get("flagged") or c.get("matched"):
            bits.append(f"{short} flagged")
    return ", ".join(bits)


def _hold_mark(row):
    """CF-0318: the `publication_hold` block on a compliance row, or None.

    None has two meanings and the funnel needs both: the row is not held
    (`clear`, `caution`), or the row is a `review` from a batch judged before
    2026-09-22, when a `review` was a refusal. The second is why this is read
    off the row and never inferred from the verdict - the verdict alone cannot
    say which rule the batch ran under, and guessing it would rewrite what ten
    recorded runs did."""
    mark = row.get(PUBLICATION_HOLD_KEY) if isinstance(row, dict) else None
    return mark if isinstance(mark, dict) else None


def _goes_on(row):
    """Whether a compliance row lets its topic (or script) walk on.

    `clear`/`caution` always did. `review` does since CF-0318 **when the row
    carries the hold that says so** - the hold is the record that the topic kept
    its slot, and a `review` without one is a topic the batch really did lose.
    A verdict outside both sets never does. Nothing here asks whether the video
    may be published: that is `PUBLISH_VERDICTS`, one question further on, and
    the whole point of the task is that the two questions stopped having the
    same answer."""
    if not isinstance(row, dict):
        return False
    verdict = row.get("verdict") or ""
    if verdict in PUBLISH_VERDICTS:
        return True
    return verdict in PRODUCTION_VERDICTS and _hold_mark(row) is not None


def _hold_row(item, row, stage):
    """The funnel row for a held video (CF-0318). It is not a loss: it names a
    topic that took its slot, was fetched, written and rendered like any other,
    and whose only difference is that it may not be uploaded unsigned. The
    sentence carries the ledger key, because the ledger outlives the batch
    directory - `scripts/monthly_archive.py` zips the batch onto Archive
    and deletes it after 30 days, and Publisher is milestone 2.0."""
    mark = _hold_mark(row) or {}
    verdict, risk = row.get("verdict") or "?", _risk(row)
    return _loss(
        item, COMPLIANCE_HOLD,
        f"compliance verdict {verdict!r}" + (f" ({risk})" if risk else "")
        + " - held from PUBLICATION, not from production (CF-0318, the user's decision of "
          "2026-09-22): the topic kept its slot and its video is made, and the video may not "
          f"go up until the user signs `{mark.get('hold_id') or item}` in "
          f"`{mark.get('ledger') or 'publish/publication-holds.json'}`. Not a loss of the batch "
          "and not reserve - the slot was taken and the work was done",
        stage, detail=row)


def _refusal(row, on="", then=""):
    """(code, reason) for a compliance row that does not go on (CF-0599).

    Every refusal is `compliance_review`; `on` is what was judged
    ("" for a topic, " on the written script" for compliance 2), `then` what
    the step adds about the refusal (it goes before the pre-CF-0318 note)."""
    verdict, risk = row.get("verdict") or "?", _risk(row)
    return "compliance_review", (f"compliance verdict {verdict!r}{on}"
                                 + (f" ({risk})" if risk else "") + then
                                 + (OLD_REVIEW_NOTE if verdict == REVIEW_VERDICT else ""))


def _own_graphic_kept(d):
    """-> {topic_id: the indexer's kept record (or {})} for the topics the
    Footage Indexer kept on own graphics (CF-0689). Read from both places it
    writes them - `own_graphic_footing.kept[]` and
    `two_source_floor.kept_on_own_graphics` - so a report carrying either one
    still exempts the topic and nothing else."""
    d = d or {}
    out = {}
    block = d.get(OWN_GRAPHIC_KEY)
    for r in (block.get("kept") if isinstance(block, dict) else None) or []:
        if isinstance(r, dict) and r.get("topic_id"):
            out[r["topic_id"]] = r
    floor = d.get("two_source_floor")
    for t in (floor.get(OWN_GRAPHIC_KEPT) if isinstance(floor, dict) else None) or []:
        if isinstance(t, str) and t:
            out.setdefault(t, {})
    return out


def _kept_row(item, n, rec):
    """The funnel row for a topic kept on own graphics (CF-0689). Not a loss:
    the topic passed `two_sources` on the floor its channel sets."""
    rep = rec.get("refusal_it_replaces") if isinstance(rec.get("refusal_it_replaces"), dict) \
        else {}
    facts = rec.get("quotable_facts")
    reason = (f"kept on own graphics: {n} registered source(s) under the floor of "
              f"{TWO_SOURCE_FLOOR}, and the channel's base footage is the graphics the Video "
              f"Editor draws from the script's facts (`own_graphic`"
              + (f", origin `{rec['origin']}`" if rec.get("origin") else "") + ")"
              + (f"; {facts} quotable fact(s), floor {rec.get('floor')}" if facts is not None
                 else "")
              + (f"; the refusal it replaces: `{rep['reason_code']}`" if rep.get("reason_code")
                 else "")
              + " - 01b-footage-index.json own_graphic_footing.kept[] (CF-0689). Passes the "
                "step, not a loss")
    return _loss(item, OWN_GRAPHIC_KEPT, reason, "01b-footage-index.json",
                 recorded_code=rep.get("reason_code"), detail=rec or None)


def _sources_by_topic(d):
    v = (d or {}).get("sources_by_topic")
    if not isinstance(v, dict):
        return {}
    return {k: (list(x) if isinstance(x, list) else []) for k, x in v.items()}


def _failed_ids(d):
    return {f.get("video_id") for f in _rows(d, "failed") if f.get("video_id")}


def _failed_by_topic(d):
    """{topic_id: [video_id]} for the failures that name their topic. CF-0129
    part 2 writes `topic_id` into `failed[]`; before that the list carried only
    the id of the video, and a failure could only be matched to a topic through
    the topic's own evidence ids (which is still the fallback)."""
    out = {}
    for f in _rows(d, "failed"):
        tid, vid = f.get("topic_id"), f.get("video_id")
        if tid and vid:
            out.setdefault(tid, []).append(vid)
    return out


def _failed_codes(d):
    """{video_id: reason_code} over `01b-footage-index.json` -> `failed[]`.

    CF-0281: the indexer writes one of two words there - `fetch_failed` for a
    source YouTube never handed over, `index_failed` for one that came down and
    could not be indexed. Before CF-0281 the list carried only the first case
    and older rows may carry no `reason_code` at all, so a row without one is
    read as the failed fetch it was.

    CF-0299 adds the third case, and it is the only one that is not a failure:
    a source that came down, indexed and described cleanly, and was then taken
    off the topic by the source sieve for what those descriptions say is in it
    - `source_foreign` or `source_burned_text` (`refused_at: sieve`). It lands
    in the same list because the effect on the topic is the same - the source
    is gone and backs no phrase - but it is a third word here, and the
    `two_sources` step below keeps it a third branch.

    CF-0663: `licence_refused` is the indexer's refusal of a candidate whose
    licence the channel does not take, also before any media moved and also
    with no attempt spent - read under its own word here, counted as
    `rights_exclusion` by the `two_sources` step. CF-0665: so is
    `licence_changed`, an archive file whose licence read again before the
    direct download was not the one it was judged on."""
    return {f["video_id"]: (f.get("reason_code") or "fetch_failed")
            for f in _rows(d, "failed") if f.get("video_id")}


def _evidence_ids(topic):
    e = topic.get("evidence")
    ids = (e or {}).get("youtube_video_ids") if isinstance(e, dict) else None
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def _recorded(entries, key):
    """{id: {"reason_code", "reason"}} from a `skipped[]` / `refusals[]` list."""
    out = {}
    for e in entries:
        k = e.get(key)
        if k:
            out[k] = {"reason_code": code_of(e) or None,
                      "reason": (e.get("reason") or "").strip() or None}
    return out


def _slug(v):
    return Path(v.get("output_path") or "").stem or v.get("script_id") or "?"


# CF-0416: the explicit admission to the judge. The Editor (agents/video-editor
# `write_batch_metadata.py`) writes `videos[].judge_admitted_despite: [rule...]`
# when QC refused a video only on rules the channel lists as cosmetic
# (`channels/<id>.json -> video_editor.qc_cosmetic_rules`). `qc.passed` stays
# honest (false), and so may `needs_you` (kaijura, 0929Z: the attempt cap ran
# out on a cosmetic refusal) - the field is the one thing that says "judge it
# anyway". Nobody downstream re-decides what is cosmetic: the list is read.
JUDGE_ADMITTED_KEY = "judge_admitted_despite"


def judge_admitted(v):
    """The rules a video was admitted to the judge despite - [] for none."""
    x = (v or {}).get(JUDGE_ADMITTED_KEY)
    if not isinstance(x, list):
        return []
    return [r.strip() for r in x if isinstance(r, str) and r.strip()]


def qc_clean(v):
    """QC passed it and the Editor did not stop on a NEEDS-YOU line."""
    return (v.get("qc") or {}).get("passed") is True and not v.get("needs_you")


def judge_candidate(v):
    """A video of `05-video-editor.json` the judge owes a verdict on and the
    funnel counts at `ready`: QC passed with no NEEDS-YOU line, or a non-empty
    `judge_admitted_despite` - whatever `qc.passed` and `needs_you` say then."""
    return qc_clean(v) or bool(judge_admitted(v))


# --------------------------------------------------------------------------
# the funnel
# --------------------------------------------------------------------------

def _video_length(v):
    """CF-0293: the `judge_video_length()` record inside one `videos[]` entry,
    or None when the entry carries none (every batch before 2026-09-09, and
    any run whose Editor could not reach the factory root)."""
    node = v
    for key in VIDEO_LENGTH_PATH:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _loss(item, code, reason, stage, recorded_code=None, detail=None):
    """One loss (or one `carried_on`). `detail` is the stage's own record of the
    decision, verbatim - for a compliance drop that is the whole `results[]` row,
    so the verdict that took the topic off the batch is in the funnel's JSON and
    not only paraphrased in its prose (grill of 2026-09-16)."""
    code, recorded_code = canonical_code(code), canonical_code(recorded_code)
    return {"item": item, "reason_code": code, "reason": reason, "stage": stage,
            "recorded_code": recorded_code if recorded_code and recorded_code != code else None,
            "detail": detail}


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


# Why the indexer's walk for more footage stopped, in words (CF-0304).
WALK_STOPPED = {
    "no_more_candidates": "and it had no candidate left to deepen the pool with",
    "attempt_cap": "and it stopped on the CF-0129 attempt cap with candidates still unused",
}


def _thin_pool_noted(row, topic, depth_of, thin_ids):
    """CF-0304, beside CF-0306: a `pool_too_thin` refusal the indexer had
    already seen coming says so.

    `pool_depth.thin[]` is the indexer's warning that a topic holds its two
    canonical sources and still has fewer usable shots than the floor - not a
    refusal (the topic goes to the Researcher exactly as it would have), but the
    reading that the refusal, if it comes, is about the footage and not about
    the writing. When the Researcher then refuses the topic for want of
    coverage, the two records are about the same thing and the funnel is the
    only place they meet; without this sentence an operator reads
    `pool_too_thin` and cannot tell a thin pool nobody could have deepened from
    a pool nobody measured. The numbers are the indexer's own - nothing is
    re-derived here.
    """
    if row["reason_code"] != "pool_too_thin" or topic not in thin_ids:
        return row
    rec = depth_of.get(topic) or {}
    n, floor_, why = rec.get("usable_shots"), rec.get("floor"), rec.get("exhausted")
    weak, avail = rec.get("weak_shots"), rec.get("available_shots")
    note = ("the indexer had already measured this pool as thin and said so in "
            "01b-footage-index.json pool_depth.thin[]"
            + (f": {n} usable shot(s) against a floor of {floor_}"
               if isinstance(n, int) and isinstance(floor_, int) else "")
            # CF-0435: `usable_shots` are the clean ones only; a pool that also
            # holds weak shots (soft usability rules, a price on screen rather
            # than a refusal) says so, or it reads emptier than it was
            + (f" (+{weak} weak, {avail} available, CF-0435)"
               if isinstance(weak, int) and weak > 0 and isinstance(avail, int) else "")
            + (", " + WALK_STOPPED.get(why, f"and the walk stopped on {why!r}") if why else "")
            + " - the refusal is the pool this topic was given, not the writing (CF-0304)")
    row["reason"] = f"{row['reason']} - {note}" if row.get("reason") else note
    return row


# CF-0881: the one repair pass of a video the judge refused for a defect in
# one or two blocks (shared/judge_repair.py) - `06 -> repairs[]`, one record per
# video, outcome `repaired` (its row was replaced by the ready one) or
# `repair_failed` (the refusal stands).
JUDGE_REPAIRS_KEY = "repairs"
JUDGE_REPAIRED, JUDGE_REPAIR_FAILED = "repaired", "repair_failed"


# CF-0888: what the center shows of one repaired block - read here so it never
# opens `06 -> repairs[]` itself. `kind`/`why` are the judge's defect the block
# was re-picked for (shared/judge_repair.defect_targets), `at` the time of the
# repair record the block belongs to.
JUDGE_REPAIR_BLOCK_KEYS = ("block", "entry", "kind", "why", "start", "end")


def judge_repairs(fj):
    """CF-0881: `{repaired, repair_failed, videos}` of `06 -> repairs[]`, or
    None when the batch had no repair pass. CF-0888: each video carries `at`
    (when its repair was recorded) and `block_details[]` - per block `{block,
    entry, kind, why, start, end, at}`; `blocks` stays the bare entry list."""
    recs = _rows(fj, JUDGE_REPAIRS_KEY) if isinstance(fj, dict) else []
    if not recs:
        return None

    def details(r):
        return [dict({k: b.get(k) for k in JUDGE_REPAIR_BLOCK_KEYS}, at=r.get("at"))
                for b in r.get("blocks") or [] if isinstance(b, dict)]

    return {JUDGE_REPAIRED: sum(1 for r in recs if r.get("outcome") == JUDGE_REPAIRED),
            JUDGE_REPAIR_FAILED: sum(1 for r in recs if r.get("outcome") == JUDGE_REPAIR_FAILED),
            "videos": [{"item": r.get("script_id"), "slug": r.get("slug"),
                        "outcome": r.get("outcome"), "reason": r.get("reason"),
                        "at": r.get("at"),
                        "blocks": [b.get("entry") for b in r.get("blocks") or []
                                   if isinstance(b, dict)],
                        "block_details": details(r),
                        "before": (r.get("before") or {}).get("reason_code"),
                        "after": (r.get("after") or {}).get("score_line")}
                       for r in recs]}


# --------------------------------------------------------------------------
# CF-0888: the below-shortlist refill rounds (CF-0882, shared/below_shortlist.py)
# --------------------------------------------------------------------------
# Three records hold one round: the root's `work/below-shortlist-refill.json ->
# rounds[]` (need, queue, budget, what was judged/walked/admitted, the outcome),
# Trend Hunter's `01 -> below_shortlist_refill[]` (the step-5b walk of each
# topic) and compliance's `02 -> refill_refused[]` (a topic refused on the fly).
# The funnel joins them so the center never opens the three files itself.
BELOW_SHORTLIST_REFILL_KEY = "below_shortlist_refill"   # the funnel's key and 01's
REFILL_RECORD_FILE = "work/below-shortlist-refill.json"  # below_shortlist.RECORD_FILE
REFILL_REFUSED_KEY = "refill_refused"                    # 02 -> refill_refused[]
REFILL_ROUNDS = ("first", "late", "judge")               # below_shortlist.ROUNDS
REFILL_ADMITTED = "admitted"
REFILL_OUTCOMES_RU = {
    REFILL_ADMITTED: "запасные темы из-под короткого списка взяты в батч",
    "not_needed": "добор не понадобился: запаса хватило",
    "queue_empty": "добирать было не из чего: под коротким списком не осталось тем",
    "search_quota": "добор не оплачен: дневная квота поиска YouTube не тянет подстановку",
    "none_eligible": "проверка на лету не пропустила ни одной темы из-под короткого списка",
    "no_pool": "для тем добора поиск футажа ничего не нашёл",
    "seam_failed": "сбой у агента на шаге добора - батч шёл без добора",
}


def _topic(r):
    return r.get("topic_id") or r.get("id") if isinstance(r, dict) else None


def _read_json(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def below_shortlist_refill(record, th=None, c02=None):
    """CF-0888: the refill rounds of one batch, or None when it had none.

        {"rounds": [{round, at, at_code, outcome, outcome_ru, why, need, queue,
                     searches, spent_after, budget_line, judged[], eligible,
                     footage[], admitted[], refused[]}],
         "admitted", "searches", "refused", "unattributed": {footage, refused}}

    `footage[]` is Trend Hunter's walk (`01 -> below_shortlist_refill[]`, its
    `at` and `reason`), `refused[]` compliance's refusals with `reason_ru`. A
    row is given to a round by its own `round`, else by the round whose record
    judged (refusals) or walked (footage) that topic; a row no round claims is
    under `unattributed` - never dropped."""
    recs = [r for r in _rows(record, "rounds") if r.get("round")]
    walks = [r for r in _rows(th, BELOW_SHORTLIST_REFILL_KEY) if _topic(r)]
    refusals = [r for r in _rows(c02, REFILL_REFUSED_KEY) if _topic(r)]
    if not (recs or walks or refusals):
        return None
    judged_in, walked_in = {}, {}
    for rec in recs:
        for x in _rows(rec, "judged"):
            judged_in.setdefault(_topic(x), rec["round"])
        for x in _rows(rec, "footage"):
            walked_in.setdefault(_topic(x), rec["round"])
    rounds = {rec["round"]: rec for rec in recs}
    out = {}

    def slot(rnd):
        if rnd not in out:
            rec = rounds.get(rnd) or {}
            b = rec.get("budget") if isinstance(rec.get("budget"), dict) else {}
            out[rnd] = {
                "round": rnd, "at": rec.get("at"), "at_code": rec.get("at_code"),
                "outcome": rec.get("outcome"),
                "outcome_ru": REFILL_OUTCOMES_RU.get(rec.get("outcome")),
                "why": rec.get("why"), "need": rec.get("need"),
                "queue": len(rec.get("queue") or []), "searches": rec.get("searches") or 0,
                "spent_after": rec.get("spent_after"), "budget_line": b.get("line"),
                "judged": [{k: x.get(k) for k in ("topic_id", "verdict", "outcome", "reason")}
                           for x in _rows(rec, "judged")],
                "footage": [{"topic_id": _topic(x), "outcome": x.get("outcome"),
                             "searches": x.get("searches"), "reason": x.get("reason"),
                             "at": None} for x in _rows(rec, "footage")],
                "admitted": [t for t in rec.get("admitted") or [] if isinstance(t, str)],
                "refused": []}
            out[rnd]["eligible"] = sum(1 for x in out[rnd]["judged"]
                                       if x.get("outcome") == "eligible")
        return out[rnd]

    for rec in recs:
        slot(rec["round"])
    unattributed = {"footage": [], "refused": []}
    for w in walks:
        tid = _topic(w)
        rnd = w.get("round") or walked_in.get(tid)
        row = {"topic_id": tid, "outcome": w.get("outcome"), "searches": w.get("searches"),
               "reason": w.get("reason"), "at": w.get("at")}
        if not rnd:
            unattributed["footage"].append(row)
            continue
        fs = slot(rnd)["footage"]
        have = next((x for x in fs if x["topic_id"] == tid), None)
        if have is None:
            fs.append(row)
        else:                       # the agent's own row is the fuller one
            have.update({k: v for k, v in row.items() if v is not None})
    for r in refusals:
        tid = _topic(r)
        code = r.get("reason_code")
        row = {"topic_id": tid, "reason_code": code, "reason_ru": refill_reason_ru(code),
               "reason": r.get("reason"), "verdict": r.get("verdict"), "at": r.get("at")}
        rnd = r.get("round") or judged_in.get(tid)
        (slot(rnd)["refused"] if rnd else unattributed["refused"]).append(row)
    order = {n: i for i, n in enumerate(REFILL_ROUNDS)}
    rows = sorted(out.values(), key=lambda x: (order.get(x["round"], len(order)),
                                               x.get("at") or ""))
    return {"rounds": rows,
            "admitted": sum(len(x["admitted"]) for x in rows),
            "searches": sum(x["searches"] or 0 for x in rows),
            "refused": sum(len(x["refused"]) for x in rows) + len(unattributed["refused"]),
            "unattributed": unattributed}


def refill_line(r):
    """CF-0888: the one line of the text report on the refill rounds."""
    if not r:
        return None
    bits = []
    for x in r["rounds"]:
        b = f"{x['round']}: {x['outcome'] or 'not recorded by the root'}"
        if x.get("need") is not None:
            b += f", need {x['need']}"
        if x["judged"]:
            b += f", judged {len(x['judged'])} ({x['eligible']} eligible)"
        if x["footage"]:
            b += f", walked {len(x['footage'])}"
        if x["admitted"]:
            b += f", admitted {', '.join(x['admitted'])}"
        if x["refused"]:
            b += ", refused " + ", ".join(f"{y['topic_id']} `{y['reason_code']}`"
                                          for y in x["refused"])
        if x["searches"]:
            b += f", {x['searches']} search(es)"
        bits.append(b)
    un = r["unattributed"]
    if un["footage"] or un["refused"]:
        bits.append(f"no round for {len(un['footage'])} walk(s) and {len(un['refused'])} "
                    f"refusal(s)")
    return (f"below-shortlist refill (CF-0882): {len(r['rounds'])} round(s), "
            f"{r['admitted']} admitted, {r['refused']} refused, {r['searches']} search(es) - "
            + "; ".join(bits))


def _frame_judge(fj, ready, videos):
    """CF-0298: (survivors, losses, summary) of the frame judge over the videos
    QC passed, or (ready, [], None) when the batch was never judged.

    Never re-judges anything and never re-derives the rule: `gate` is the
    verdict `scripts/frame_judge_gate.py` already computed from the judge's
    `verdicts.json`, and this function reads it exactly the way CF-0293 reads
    the Editor's length verdict. A second opinion here would be a second gate.

    A video the artifact has no row for is *not judged* - it stays in `ready`
    and is named in the summary. Silence is not a pass, but it is not a refusal
    either, and the way to notice it is to say how many videos nobody looked at.
    """
    if not isinstance(fj, dict):
        return list(ready), [], None
    rows = _rows(fj, "videos")
    by_id = {r["script_id"]: r for r in rows if r.get("script_id")}
    by_slug = {r["slug"]: r for r in rows if r.get("slug")}
    recorded_skips = {r.get("script_id") or r.get("slug"): r
                      for r in _rows(fj, "not_judged") if r.get("script_id") or r.get("slug")}
    survivors, lost, not_judged, neutral_entries = [], [], [], []
    counts = dict.fromkeys(("judged", "passed", "rejected", "incomplete", "not_judged"), 0)
    tally = dict.fromkeys(FRAME_VERDICTS, 0)
    tally["foreign_text"] = 0
    unreadable = 0
    for sid in ready:
        slug = _slug(videos.get(sid) or {})
        row = by_id.get(sid) or by_slug.get(slug)
        if row is None:
            counts["not_judged"] += 1
            rec = recorded_skips.get(sid) or recorded_skips.get(slug) or {}
            not_judged.append({"item": sid, "slug": slug,
                               "reason": (rec.get("reason") or "").strip() or
                               f"{FRAME_JUDGE_FILE} carries no record for this video"})
            survivors.append(sid)
            continue
        counts["judged"] += 1
        unreadable += _count((row.get("pack") or {}).get("unreadable_frames"))
        for v in _rows(row, "verdicts"):
            word = v.get("verdict")
            if word in tally:
                tally[word] += 1
            if word == NEUTRAL_VERDICT:
                neutral_entries.append({"item": sid, "slug": slug, "entry": v.get("entry"),
                                        "why": (v.get("why") or "").strip() or None})
            if (v.get("foreign_text") or "").strip():
                tally["foreign_text"] += 1
        gate = row.get("gate")
        if gate == GATE_PASS:
            counts["passed"] += 1
            survivors.append(sid)
            continue
        counts["rejected" if gate == GATE_REJECT else "incomplete"] += 1
        reason = (row.get("reason") or "").strip()
        if not reason:
            reason = (f"the frame judge did not pass {slug} (gate {gate!r}) and "
                      f"{FRAME_JUDGE_FILE} carries no sentence saying why")
        lost.append(_loss(sid, row.get("reason_code") or FRAME_JUDGE_FAILED, reason,
                          FRAME_JUDGE_FILE, recorded_code=row.get("reason_code"), detail=row))
    summary = {"schema": fj.get("schema"), "judged_at": fj.get("judged_at"),
               "counts": counts, "verdicts": tally, "unreadable_frames": unreadable,
               "not_judged": not_judged, "neutral_entries": neutral_entries,
               # CF-0707: the gate's sentence when 05 owed the judge nothing
               "nothing_to_judge": (fj.get("nothing_to_judge") or "").strip() or None,
               # CF-0881: the repair pass after the judge
               "repairs": judge_repairs(fj)}
    return survivors, lost, summary


# --------------------------------------------------------------------------
# CF-0376: what the run returned, and what was rebuilt after it closed
# --------------------------------------------------------------------------
# `example-film/2026-09-23T1722Z` closed at 00:45:33Z with one video through the
# judge; three and a half hours (and five code changes) later two more were
# rebuilt *in the same directory*, into the same 05-video-editor.json and the
# same RUN_EVENTS.jsonl, and the funnel read them as the run's output
# (`ready 4 -> frame judge 3`). The artifacts carry the final state of a video,
# never when it reached it; the events and the Editor's `merge_log[]` do. So a
# video whose last render (or first merge into 05) lies outside every
# `batch-start .. batch-done` span of the batch is work done after the run
# closed: it stays on the record, on a line of its own, and never in `ready`.
# A batch with no `batch-done` (an open run, a rebuild directory) splits nothing.
AFTER_CLOSE_KEY = "after_close"
RENDER_STEP = "render"


def _ts(v):
    """POSIX seconds of an event ts or a merge_log `at` (`...Z` or `+00:00`), else None."""
    if not isinstance(v, str) or not v:
        return None
    t = v.strip()
    if t.endswith("+00:00"):
        t = t[:-6]
    try:
        return runlog.parse_z(t)
    except ValueError:
        return None


def run_spans(events):
    """([(start, end)] of the batch's own runs, the first `batch-done` ts or None).
    A `batch-start` with no `batch-done` after it is open to the end."""
    spans, start, first_done = [], None, None
    for e in events:
        if e.get("kind") != "marker":
            continue
        which, t = e.get("status"), _ts(e.get("ts"))
        if t is None:
            continue
        if which == runlog.M_BATCH_START and start is None:
            start = t
        elif which == runlog.M_BATCH_DONE:
            first_done = t if first_done is None else first_done
            spans.append((start if start is not None else float("-inf"), t))
            start = None
    if start is not None:
        spans.append((start, float("inf")))
    return spans, first_done


def _inside(t, spans):
    return any(a <= t <= b for a, b in spans)


def after_close_of(events, ve, videos):
    """{script_id: row} for the videos of 05-video-editor.json that were built
    after the run closed (CF-0376), or {} when the batch never closed.

    A row: `{item, slug, built_at, basis, reason}`. `basis` says which record
    put it there - `render` (its last `render done` event is outside every run
    span) or `merge_log` (05 first lists it in a merge written after the
    close); `reason` is the `note` of the `stage-start` that opened the
    after-close work naming the video (or the first after-close note at all),
    None when nobody wrote one."""
    spans, closed = run_spans(events or [])
    if closed is None or not videos:
        return {}
    last_render, notes = {}, []
    for e in events:
        t = _ts(e.get("ts"))
        if t is None:
            continue
        if (e.get("kind") == "script" and e.get("step") == RENDER_STEP
                and e.get("status") == "done" and e.get("video")):
            last_render[e["video"]] = (t, e.get("ts"))
        elif (e.get("kind") == "marker" and e.get("status") == runlog.M_STAGE_START
              and t > closed and not _inside(t, spans) and (e.get("note") or "").strip()):
            notes.append(e["note"].strip())
    first_merge = {}
    for m in _rows(ve, "merge_log"):
        t = _ts(m.get("at"))
        if t is None:
            continue
        for sid in m.get("videos") or []:
            if sid not in first_merge or t < first_merge[sid][0]:
                first_merge[sid] = (t, m.get("at"))
    out = {}
    for sid, v in videos.items():
        slug = _slug(v)
        basis = built = None
        r = last_render.get(slug)
        if r and r[0] > closed and not _inside(r[0], spans):
            basis, built = RENDER_STEP, r[1]
        else:
            m = first_merge.get(sid)
            if r is None and m and m[0] > closed and not _inside(m[0], spans):
                basis, built = "merge_log", m[1]
        if basis is None:
            continue
        reason = next((n for n in notes if slug in n), notes[0] if notes else None)
        out[sid] = {"item": sid, "slug": slug, "built_at": built, "basis": basis,
                    "reason": reason}
    return out


def _step(key, items, lost, carried_on, basis=None, reserve=None, held=None, kept=None):
    """One row of the funnel. `reserve` (CF-0265) sits beside `lost` and never
    inside it: a topic held back for want of a slot is not a topic the batch
    lost, and the difference has to survive into the table, the codes and the
    headline.

    `held` (CF-0318) sits beside both and is different from either: the topic is
    **in** `items`, counted in the step it passed, because it passed it - it was
    made. What it may not do is be published. It gets a list of its own for the
    same reason the reserve got one: a number that is neither a loss nor silence
    has to be somewhere, or the next reader infers it, and the inference will be
    one of the two wrong ones.

    `kept` (CF-0689) has the standing `held` has, one step earlier: the topic
    is in `items` because it passed - on the floor its channel sets (own
    graphics) rather than the source count - and the list says so."""
    return {"step": key, "label": STEP_LABELS[key], "count": len(items), "items": list(items),
            "lost": lost, "carried_on": carried_on, "reserve": list(reserve or []),
            "held": list(held or []), OWN_GRAPHIC_KEPT: list(kept or []), "basis": basis}


def funnel(batch_dir=None, artifacts=None, events=None):
    """The topic funnel of one batch:

        {"available", "missing", "errors", "steps": [...], "losses": {code: n},
         "unexplained": [...], "unknown_codes": [...], "silent",
         "pattern_missing": [...], "pre_selection": {...}, "ready": [...]}

    `available` is False when the batch carries no stage artifact at all - a
    run whose events exist but whose JSONs are gone or were never written.
    Never raises; an artifact that will not parse becomes a line in `errors`.

    `events` (CF-0376) are the batch's RUN_EVENTS; read from `batch_dir` when
    not given. They decide one thing only: which videos were built after the
    run closed and so are not the run's output (`after_close`).
    """
    A = artifacts if artifacts is not None else read_artifacts(batch_dir)
    missing, errors = A.get("_missing") or [], list(A.get("_errors") or [])
    th, c02 = A.get("01-trend-hunter.json"), A.get("02-compliance-checker.json")
    idx, cr = A.get("01b-footage-index.json"), A.get("03-content-researcher.json")
    c04, ve = A.get("04-compliance-checker.json"), A.get("05-video-editor.json")
    if not any(x is not None for x in (th, c02, idx, cr, c04, ve)):
        return {"available": False, "missing": missing, "errors": errors, "steps": [],
                "losses": {}, "unexplained": [], "unknown_codes": [], "silent": False,
                "pattern_missing": [], "judge_admitted": [],
                "pre_selection": {"recorded": None, "lost": []},
                "reserve": [], "shortlist": None, "cut": None, "frame_judge": None,
                "ready": [], "target": None, AFTER_CLOSE_KEY: None,
                BELOW_SHORTLIST_REFILL_KEY: None}

    v02 = _verdicts(c02, ("topic_id", "script_id"))
    v04 = _verdicts(c04, ("script_id", "topic_id"))
    topics = _rows(th, "topics")
    # 1. selected. Without 01 the batch's own compliance pass is the widest
    #    record of what was on the table; say which it was.
    if topics:
        selected = [t.get("topic_id") for t in topics if t.get("topic_id")]
        basis = "01-trend-hunter.json topics[]"
    else:
        selected = sorted(v02)
        basis = "02-compliance-checker.json results[] (01-trend-hunter.json is missing)"
    ev_ids = {t.get("topic_id"): _evidence_ids(t) for t in topics if t.get("topic_id")}
    # CF-0129: Trend Hunter's own refusals. `None` = the artifact carries no
    # `skipped_topics` at all (every batch before 2026-09-16), which is nothing
    # said and not an empty list; `[]` = the stage said it refused nothing.
    th_recorded = None if th is None else isinstance(th.get("skipped_topics"), list)
    th_skipped = _recorded(_rows(th, "skipped_topics"), "topic_id")
    # CF-0264/CF-0265, 2026-09-17. `selection` is Trend Hunter's own summary of
    # the pass that produced the shortlist; `cut` and `reserve[]` are the record
    # of the cut to the batch target that now happens *after* compliance. All
    # three are absent from every batch written before 2026-09-17, and their
    # absence is what keeps such a batch reading exactly as it did.
    selection = th.get("selection") if isinstance((th or {}).get("selection"), dict) else None
    cut = c02.get("cut") if isinstance((c02 or {}).get("cut"), dict) else None
    reserve_rows = _rows(c02, "reserve")
    reserve_ids = [r.get("topic_id") for r in reserve_rows if r.get("topic_id")]
    reserve_set = set(reserve_ids)
    # CF-0313: Trend Hunter's own refill of a slot it emptied at step 5b, and
    # the day's search quota that paid for it (or did not). Read here so that
    # the block alone is enough to draw the `before_selection` step: a batch
    # carrying it ran under the shortlist by construction, and a funnel that
    # needed a second mark to believe it could drop every row of the block.
    foot_filled, foot_open, foot_unmatched = _footage_substitutions(th)
    quota = th.get(SEARCH_QUOTA_KEY) if isinstance((th or {}).get(SEARCH_QUOTA_KEY),
                                                   dict) else None
    shortlisted = bool(selection) or bool(cut) or bool(
        foot_filled or foot_open or foot_unmatched) or any(
        canonical_code(r.get("reason_code")) in SHORTLIST_CODES
        for r in _rows(th, "skipped_topics"))
    # CF-0306, the user's decision of 2026-09-21: a topic lost *after* the cut
    # no longer leaves the batch one short - the indexer refills the freed slot
    # from the reserve and records who took whose place. Two consequences here.
    # The substituted topic is a participant: it stays in `selected`, walks
    # every step below like any other topic, and leaves the "held in reserve"
    # column, because a spare that was used is not a spare. And its compliance
    # verdict is in `reserve[]` rather than in `results[]` - promoting a reserve
    # topic does not rewrite `02-compliance-checker.json` - so the verdict is
    # taken from there, or step 2 would read a topic compliance judged `clear`
    # as `not_screened` and the funnel would invent a hole exactly where a hole
    # was filled. Nothing here judges anything: the row is the one compliance
    # wrote, read from the list the cut left it in.
    subs, sub_unmatched = _substitutions(idx)
    for tid in subs:
        if tid in v02:
            continue
        row = next((r for r in reserve_rows if r.get("topic_id") == tid), None)
        if row is not None:
            v02[tid] = row

    srcs = _sources_by_topic(idx)
    failed = _failed_ids(idx)
    failed_of = _failed_by_topic(idx)
    failed_why = _failed_codes(idx)
    failed_rec = {f["video_id"]: f for f in _rows(idx, "failed") if f.get("video_id")}  # CF-0599
    idx_skipped = _recorded(_rows(idx, "skipped_topics"), "topic_id")
    graphic_kept = _own_graphic_kept(idx)  # CF-0689
    cr_skipped = _recorded(_rows(cr, "skipped"), "topic_id")
    scripts = _rows(cr, "scripts")
    by_topic = {}
    for s in scripts:
        if s.get("topic_id") and s.get("script_id"):
            by_topic.setdefault(s["topic_id"], []).append(s["script_id"])
    videos = {v.get("script_id"): v for v in _rows(ve, "videos") if v.get("script_id")}
    refusals = _recorded(_rows(ve, "refusals"), "script_id")

    steps, losses, unexplained, unknown, held, holds = [], {}, [], set(), [], []

    def _vocabulary(row):
        for c in (row["reason_code"], row["recorded_code"]):
            if c and c not in FUNNEL_CODES:
                unknown.add(c)

    def note(loss):
        code = loss["reason_code"]
        losses[code] = losses.get(code, 0) + 1
        if code == UNEXPLAINED:
            unexplained.append(loss)
        _vocabulary(loss)

    def hold(row):
        """A reserve row: named and checked against the vocabulary like any
        other, but never counted in `losses` (CF-0265)."""
        held.append(row)
        _vocabulary(row)

    def holdback(row):
        """A publication hold (CF-0318): named and checked against the
        vocabulary like any other row, and counted in no `losses`. The topic is
        in the batch and its video gets made; what it may not do is go up
        without the user's signature."""
        holds.append(row)
        _vocabulary(row)

    def recorded_loss(item, where, stage):
        """The code the dropping stage wrote, or `unexplained` when none did."""
        rec = where.get(item) or {}
        code = rec.get("reason_code") or UNEXPLAINED
        reason = rec.get("reason")
        if code == UNEXPLAINED and not reason:
            reason = (f"no stage recorded why it left the batch - it is in neither the "
                      f"output nor the skips of {stage}")
        return _loss(item, code, reason, stage, recorded_code=rec.get("reason_code"))

    # 1a. before selection -- 01-trend-hunter.json skipped_topics[] / selection.
    #     Until 2026-09-17 these topics hung off the `selected` step: they are in
    #     no `topics[]` and so in no step's count, and `topics[]` *was* the
    #     selection. Since CF-0264 the stage hands out a shortlist and the
    #     selection happens after compliance, so a batch that carries the
    #     shortlist marks gets a step of its own here and the survivors of that
    #     step are the shortlist (`shortlisted` below). A batch without the marks
    #     keeps the old shape exactly.
    shortlist = list(selected)
    sel_set = set(selected)
    pre_lost, pre_reserve = [], []
    for tid in sorted(th_skipped):
        if tid in sel_set:
            # Both lists carrying it contradicts the contract (a refused topic
            # is taken out of `topics[]`); `topics[]` wins and the topic is
            # followed down the chain rather than counted lost here.
            continue
        rec = th_skipped[tid]
        code = rec.get("reason_code") or UNEXPLAINED
        why = rec.get("reason")
        head = ("viable, and past `scope.shortlist_size`: unused reserve of the shortlist Trend "
                "Hunter handed out, not a refusal of the topic"
                if code in RESERVE_CODES else
                "refused before selection, so it is not in topics[]")
        row = _loss(tid, code,
                    head + (f" - 01-trend-hunter.json: {why}" if why else
                            " - and 01-trend-hunter.json recorded no reason for it"),
                    "01-trend-hunter.json", recorded_code=rec.get("reason_code"))
        (pre_reserve if code in RESERVE_CODES else pre_lost).append(row)
    for x in pre_lost:
        note(x)
    for x in pre_reserve:
        hold(x)
    # CF-0873: what the refusals before selection cost. Since CF-0823 (v2.20)
    # Trend Hunter probes every draft for a fact *before* scoring (20-23 drafts
    # where it used to probe the 12-17 it scored) and re-refuses a work its
    # no-fact memory holds without asking again - both are counted above under
    # `no_fact`, so the count grew from 1-3 to 4-6 a batch while not one slot of
    # the shortlist went with them: in every Reel batch since 2026-10-01 the
    # shortlist was filled to `selection.shortlist_size` with viable topics to
    # spare. The headline says which of the two it was, so a growing `no_fact`
    # is not read as topics the batch lost (docs/notes/cf-0873-no-fact-growth.md).
    th_rows = {r.get("topic_id"): r for r in _rows(th, "skipped_topics")}
    pre_remembered = sorted(x["item"] for x in pre_lost
                            if _remembered_refusal(th_rows.get(x["item"])))
    want = (selection or {}).get("shortlist_size")
    pre_filled_shortlist = (len(shortlist) >= want if shortlisted and isinstance(want, int)
                            and not isinstance(want, bool) and want > 0 else None)
    # CF-0313: what the stage did about the slots its own step-5b refusals
    # emptied. Three kinds of row, and every one of them is about a *slot*
    # rather than about a topic's fate - the topics are counted above, under
    # the codes the stage wrote, and none of these rows is counted again.
    pre_filled, pre_empty = [], []
    for s in foot_filled:
        tid = s.get("topic_id") or "?"
        gone, why = s.get("replaced") or "?", (s.get("reason") or "").strip()
        outcome, n = s.get("outcome"), s.get("candidates")
        price = s.get("price_searches")
        pre_filled.append(_loss(
            tid, s.get("reason_code") or RESERVE_SUBSTITUTED,
            f"{tid} took the shortlist slot of {gone}, which this stage refused at step 5b "
            f"with {str(s.get('replaced_reason_code') or '?')!r} - it was viable and only past "
            f"`scope.shortlist_size`"
            + (f" (rank {s['rank']})" if isinstance(s.get("rank"), int) else "")
            + f", so it went back into topics[] and walked 5b like any other topic of the batch"
            + (f" ({outcome}" + (f", {n} candidate(s)" if isinstance(n, int) else "")
               + (f", {price} search call(s)" if isinstance(price, int) else "") + ")"
               if outcome else "")
            + (". 5b refused the substitute too, so its own refusal is counted above under its "
               "own code and the slot went on to the next reserve topic"
               if outcome == "refused" else "")
            + " (CF-0313)" + (f" - 01-trend-hunter.json: {why}" if why else ""),
            "01-trend-hunter.json", recorded_code=s.get("reason_code"), detail=s))
    for s in foot_open:
        tid, gone = s.get("topic_id") or "?", s.get("replaced") or "?"
        why = (s.get("reason") or "").strip()
        pending = s.get("outcome") == PENDING_SEARCH
        head = (f"the slot {gone} left at step 5b "
                f"({str(s.get('replaced_reason_code') or '?')!r}) is still empty: "
                + (f"{tid} was decided for it and its footage search has not been run - a "
                   f"decision without execution. The topic is in no topics[] and in no count "
                   f"above; running the search named below completes this same entry rather "
                   f"than writing a second one (CF-0313)"
                   if pending else
                   f"the reserve row {tid} held no topic to put back, so nothing was carried "
                   f"and the slot went on to the next reserve topic, which another row of "
                   f"`{FOOTAGE_SUBSTITUTION_KEY}` answers (CF-0313)"))
        pre_empty.append(_loss(gone, s.get("reason_code") or RESERVE_SUBSTITUTED,
                               head + (f" - 01-trend-hunter.json: {why}" if why else ""),
                               "01-trend-hunter.json", recorded_code=s.get("reason_code"),
                               detail=s))
    for u in foot_unmatched:
        gone, code = u.get("replaced") or "?", u.get("reason_code") or RESERVE_EXHAUSTED
        why = (u.get("reason") or "").strip()
        head = (f"the slot {gone} left at step 5b "
                f"({str(u.get('replaced_reason_code') or '?')!r}) stayed empty: "
                + ("the day's `search.list` calls would not pay for the facet run a substitute "
                   "costs, so nothing was looked for - a limit of ours and not a fact about "
                   "any topic, which is why it is not `no_source` (CF-0288, CF-0313). A re-run "
                   "after the quota resets refills the slot"
                   if code == SEARCH_QUOTA_EXHAUSTED else
                   "step 5a left no `below_shortlist` topic this batch had not already spent, "
                   "so the batch goes to compliance one topic short. A shortlist too short for "
                   "what this batch refused, not a refusal of any stage - `scope.shortlist_size` "
                   "is the number to raise (CF-0313)")
                + f". Not a second loss of {gone}: it is counted once above, under its own code")
        pre_empty.append(_loss(gone, code,
                               head + (f" - 01-trend-hunter.json: {why}" if why else ""),
                               "01-trend-hunter.json", recorded_code=u.get("reason_code"),
                               detail=u))
    # Checked against the vocabulary like every other row and counted in no
    # total - the same standing CF-0306's two rows have (SUBSTITUTION_CODES).
    for x in pre_filled + pre_empty:
        _vocabulary(x)
    if th_recorded:
        basis = (basis or "") + f"; skipped_topics[] {len(pre_lost)} refused before selection"
    if shortlisted:
        pre_basis = basis
        if selection:
            bits = [f"{selection[k]} {k}" for k in ("scored", "viable", "carried")
                    if isinstance(selection.get(k), int)]
            if bits:
                pre_basis += "; selection: " + ", ".join(bits)
        if pre_filled or pre_empty:
            waiting = len([s for s in foot_open if s.get("outcome") == PENDING_SEARCH])
            pre_basis += (f"; {FOOTAGE_SUBSTITUTION_KEY}: {len(pre_filled)} refilled, "
                          f"{len(pre_empty)} empty"
                          + (f", {waiting} awaiting a footage search" if waiting else ""))
        if quota:
            pre_basis += (f"; search quota {quota.get('spent_searches')}/"
                          f"{quota.get('daily_limit_searches')} spent")
        steps.append(_step("before_selection", shortlist, pre_lost + pre_empty, pre_filled,
                           pre_basis, reserve=pre_reserve))
        pre_lost_of_selected = []
    else:
        pre_lost_of_selected = pre_lost

    # 1b. selected. With a `cut` in the compliance artifact (CF-0265) the
    #     selection is the cut's output, not `topics[]`: the shortlist is up to
    #     `scope.shortlist_size` (8) topics, compliance judges all of them, and
    #     the cut carries the first `scope.max_titles_per_batch` (5) with a
    #     passing verdict into the batch. So `selected` counts what the cut
    #     carried - which is what makes "5 selected -> 3 ready" still the
    #     sentence the channel's target is read against - while the shortlist's
    #     size stays visible in the basis beside it. A topic compliance refused
    #     is a loss of this step; a topic the cut had no slot for is reserve and
    #     not a loss at all.
    #
    #     Since CF-0306 a *fourth* kind of row belongs here, and it belongs
    #     here because this is the step where the batch's membership is
    #     decided: a reserve topic that took the slot of a topic lost later on
    #     (`reserve_substituted`, in `carried_on`), and a slot that came free
    #     with the reserve already used up (`reserve_exhausted`, in `lost`).
    #     Neither is counted in `losses` - see SUBSTITUTION_CODES.
    cut_lost, cut_reserve, cut_filled, cut_empty = [], [], [], []
    if cut or reserve_set or subs:
        # CF-0318: what the cut refuses is a verdict outside PRODUCTION_VERDICTS -
        # and a `review` that carries no `publication_hold`, which is every
        # `review` of every batch judged before 2026-09-22. `_goes_on` is both
        # conditions in one place so the cut, the two compliance steps and the
        # table cannot come to three different answers about the same row.
        refused_at_cut = [t for t in selected
                          if t in v02 and not _goes_on(v02[t])]
        selected = [t for t in selected
                    if (t not in reserve_set or t in subs) and t not in refused_at_cut]
        for t in refused_at_cut:
            row = v02[t]
            code, reason = _refusal(
                row, then=" - judged on the shortlist and refused before the cut, so the cut "
                          "gave its slot to the next eligible topic (CF-0265)")
            cut_lost.append(_loss(t, code, reason, "02-compliance-checker.json", detail=row))
        for r in reserve_rows:
            tid = r.get("topic_id")
            if not tid or tid in subs:
                # CF-0306: it was in reserve and it is in the batch. A spare
                # that took a slot is held back from nothing, so it leaves this
                # column and `f["reserve"]` on its own - no separate arithmetic
                # anywhere has to remember to subtract it.
                continue
            why = (r.get("reason") or "").strip()
            cut_reserve.append(_loss(
                tid, r.get("reason_code") or "reserve_unused",
                "judged " + repr(r.get("verdict") or "?")
                + " and held in reserve: the cut to the batch target had no slot left for it, so "
                  "it is not a loss of the batch"
                + (f" - 02-compliance-checker.json: {why}" if why else ""),
                "02-compliance-checker.json", recorded_code=r.get("reason_code"), detail=r))
        # CF-0306: who took whose place, and which place nobody could take.
        # The sentence names the topic that was lost, the stage that lost it
        # and the code it was lost under, so the swap can be read here without
        # opening `01b-footage-index.json` - and the whole substitution row is
        # in `detail`, the same standing a compliance drop's `results[]` row has.
        verdict_of = {r.get("topic_id"): r.get("verdict") for r in reserve_rows}
        for tid in sorted(subs):
            s = subs[tid]
            verdict = verdict_of.get(tid) or (v02.get(tid) or {}).get("verdict") or "?"
            if s.get("at") == AFTER_JUDGE_AT:
                # CF-0801: the slot came free at the frame judge - after the
                # cut, the scripts and the render - and was refilled in the
                # same run, one round (CF-0798)
                gone = s.get("replaced_slug") or s.get("replaced_script_id")
                cut_filled.append(_loss(
                    tid, RESERVE_SUBSTITUTED,
                    f"{AFTER_JUDGE_RU}: judged {verdict!r} and held in reserve until the "
                    f"frame judge refused {s.get('replaced')}"
                    + (f" ({gone})" if gone else "")
                    + f" with {str(s.get('replaced_reason_code') or '?')!r} - it took that "
                      f"slot in the same run and went through the index, the script, the "
                      f"cut and the judge like any other topic (CF-0798, one round)",
                    "01b-footage-index.json", detail=s))
                continue
            cut_filled.append(_loss(
                tid, RESERVE_SUBSTITUTED,
                f"judged {verdict!r} and held in reserve until {s.get('replaced')} was lost "
                f"at {str(s.get('replaced_stage') or '?')!r} with "
                f"{str(s.get('replaced_reason_code') or '?')!r} - it took that slot and was "
                f"fetched like any other topic of the batch (CF-0306)",
                "01b-footage-index.json", detail=s))
        for u in sub_unmatched:
            gone = u.get("replaced") or "?"
            cut_empty.append(_loss(
                gone, u.get("reason_code") or RESERVE_EXHAUSTED,
                f"the slot {gone} left at {str(u.get('replaced_stage') or '?')!r} with "
                f"{str(u.get('replaced_reason_code') or '?')!r} stayed empty: the reserve was "
                f"used up, so the batch ran one topic short of what the cut carried. Not a "
                f"refusal of any stage and not a second loss of {gone} - a shortlist too short "
                f"for what this batch lost (CF-0306; raise `scope.shortlist_size` if it repeats)",
                "01b-footage-index.json", recorded_code=u.get("reason_code"), detail=u))
        basis = "02-compliance-checker.json cut[]"
        nums = [f"{cut[k]} {k}" for k in ("judged", "eligible", "carried", "reserve", "refused")
                if cut and isinstance(cut.get(k), int)] if cut else []
        if nums:
            basis += ": " + ", ".join(nums)
        elif not cut:
            basis = ("02-compliance-checker.json results[] minus reserve[] "
                     "(the artifact carries `reserve` but no `cut` summary)")
        basis += f"; shortlist of {len(shortlist)}"
        refills = ([f"{len(cut_filled)} slot(s) refilled from reserve"] if cut_filled else []) \
            + ([f"{len(cut_empty)} left empty (reserve exhausted)"] if cut_empty else [])
        if refills:
            basis += "; " + ", ".join(refills) + " (CF-0306)"
    for x in cut_lost:
        note(x)
    for x in cut_reserve:
        hold(x)
    # CF-0306's two rows are checked against the vocabulary like every other row
    # and counted in no total: neither a refill nor an empty slot is a loss this
    # funnel has not already counted (SUBSTITUTION_CODES says why).
    for x in cut_filled + cut_empty:
        _vocabulary(x)
    steps.append(_step("selected", selected, pre_lost_of_selected + cut_lost + cut_empty,
                       cut_filled, basis, reserve=cut_reserve))

    # 2. after compliance -- 02-compliance-checker.json. `not_screened` here
    #    means nobody judged the topic, and that is exactly what a reserve topic
    #    would have looked like until CF-0265: it is in `topics[]`, it has a
    #    verdict, and its row lives in `reserve[]` rather than in `results[]`.
    #    Step 1b takes those topics out of `selected` before this loop runs, so
    #    the code keeps meaning what it says - a topic nothing judged - instead
    #    of turning every spare the cut kept into a bookkeeping hole.
    #
    #    CF-0318 (the user's decision, grill of 2026-09-22): a `review` carrying
    #    a `publication_hold` **passes this step**. It is not a loss and it is
    #    not a topic that "went past a bar it did not clear" either - it cleared
    #    the bar the gate now sets, which is production. Until this task the
    #    funnel wrote it into `lost` (or, when a later stage had seen the topic,
    #    into `carried_on`, which is worse: a correctly made video signed as a
    #    topic that slipped past a refusal). What it may not do is be published,
    #    and that is `held` - counted, named, in no `losses` total.
    after, lost, carried, on_hold = [], [], [], []
    for t in selected:
        row = v02.get(t)
        # Being listed in a stage's skips is not carrying on: a topic only went
        # past the bar if footage was actually registered for it or a script written.
        seen_next = bool(srcs.get(t)) or t in by_topic
        if row is None:
            code, reason = "not_screened", ("02-compliance-checker.json carries no verdict for "
                                            "this topic")
        elif _goes_on(row):
            after.append(t)
            if _hold_mark(row):
                on_hold.append(_hold_row(t, row, "02-compliance-checker.json"))
            continue
        else:
            code, reason = _refusal(row)
        (carried if seen_next else lost).append(
            _loss(t, code, reason, "02-compliance-checker.json", detail=row))
        if seen_next:
            after.append(t)
    for x in lost + carried:
        note(x)
    for x in on_hold:
        holdback(x)
    steps.append(_step("after_compliance", after, lost, carried,
                       "02-compliance-checker.json results[].verdict "
                       f"in {list(PUBLISH_VERDICTS)}, or {REVIEW_VERDICT!r} carrying a "
                       f"`{PUBLICATION_HOLD_KEY}` (CF-0318)"
                       + (f"; {len(on_hold)} held from publication" if on_hold else ""),
                       held=on_hold))

    # 3. with two sources -- 01b-footage-index.json
    two, lost, carried, on_graphics = [], [], [], []
    for t in after:
        got = srcs.get(t)
        n = len(got or [])
        if n >= TWO_SOURCE_FLOOR:
            two.append(t)
            continue
        if t in graphic_kept:
            # CF-0689: the indexer kept it below the floor because it stands
            # on own graphics - it passed the floor its channel sets.
            two.append(t)
            row = _kept_row(t, n, graphic_kept[t])
            _vocabulary(row)
            on_graphics.append(row)
            continue
        went_on = t in by_topic
        rec = idx_skipped.get(t) or {}
        if n:
            code = "no_second_source"
            reason = (f"{n} registered source(s), floor is {TWO_SOURCE_FLOOR} "
                      f"(CF-0129; canonical sources, a re-upload of the same cut is an alias "
                      f"by the CF-0080 fingerprint and not a source)")
        else:
            mine = sorted(set(failed_of.get(t) or [])
                          | {i for i in ev_ids.get(t) or [] if i in failed})
            if mine:
                # CF-0281: `failed[]` no longer means one thing. A source the
                # indexer downloaded and could not index is our own failure and
                # is fixed here; one YouTube refused is not. The code follows
                # the whole of the topic's loss - `index_failed` only when
                # every candidate was lost that way - and the sentence names
                # both causes whenever both happened, so a mixed loss is never
                # rounded down to one of them.
                #
                # CF-0299 makes it a three-way split, in the same priority the
                # indexer's own `ingest_batch.topic_refusal` uses: a download
                # YouTube refused outranks our missing index, and both outrank
                # a source the sieve took, because the first two are defects
                # and the third is the stage working as designed. Without this
                # branch a topic whose every source was indexed and then taken
                # by the sieve reads as `fetch_failed` - the one word that is
                # certainly wrong about it, since YouTube handed every one of
                # them over.
                #
                # CF-0302 makes it four-way and puts the new code last in the
                # same priority: a candidate refused on its metadata cost this
                # topic nothing at all - no download, no index, not even one of
                # its four attempts - so it may not outrank a loss that did.
                unindexed = [i for i in mine if failed_why.get(i) == INDEX_FAILED]
                sieved = [i for i in mine if failed_why.get(i) in SIEVE_REFUSAL_CODES]
                too_long = [i for i in mine if failed_why.get(i) == SOURCE_TOO_LONG]
                # CF-0663: refused for its licence before anything was asked
                # of YouTube (`refused_at: candidate`, no attempt spent) - last
                # in the priority, counted under `rights_exclusion` when it is
                # all the topic lost.
                # CF-0665: an archive file whose licence changed by the time
                # it was to be downloaded is refused the same way.
                unlicensed = [i for i in mine if failed_why.get(i) in LICENCE_CODES]
                done = set(unindexed) | set(sieved) | set(too_long) | set(unlicensed)
                unfetched = [i for i in mine if i not in done]

                def _also_sieved(text):
                    if not sieved:
                        return text
                    return text + (f"; {len(sieved)} of them were indexed and then taken by "
                                   f"the source sieve ({', '.join(sieved)}) - the footage "
                                   f"itself was not this topic's, which is neither a failed "
                                   f"fetch nor a failed index (CF-0299)")

                def _also_too_long(text):
                    text = _also_unlicensed(text)
                    if not too_long:
                        return text
                    return text + (f"; {len(too_long)} of them were refused before any "
                                   f"download as too long to index ({', '.join(too_long)}) - "
                                   f"nothing was fetched and no attempt was spent on them "
                                   f"(CF-0302)")

                def _licence_name(x):
                    if isinstance(x, dict):
                        return x.get("short_name") or x.get("licence")
                    return x if isinstance(x, str) and x.strip() else None

                def _licence(i):
                    rec = failed_rec.get(i) or {}
                    if rec.get("reason_code") == LICENCE_CHANGED:
                        # CF-0665: the licence it was judged on -> the one the
                        # archive says now
                        was = _licence_name(rec.get("licence_was")) or "?"
                        now = _licence_name(rec.get("licence_now")) or "?"
                        if isinstance(rec.get("licence_now"), dict) and \
                                rec["licence_now"].get("non_free"):
                            now += " non-free"
                        return f"{i} (licence changed: {was} -> {now})"
                    rights = rec.get("rights") if isinstance(rec.get("rights"), dict) else {}
                    name = rights.get("short_name") or rights.get("licence")
                    return f"{i} ({name})" if name else i

                def _also_unlicensed(text):
                    if not unlicensed:
                        return text
                    return text + (f"; {len(unlicensed)} of them were refused for their "
                                   f"licence ({', '.join(_licence(i) for i in unlicensed)}) - "
                                   f"a licence the channel does not take, nothing was asked "
                                   f"of YouTube and no attempt was spent on them (CF-0663)")

                if unfetched:
                    code = "fetch_failed"
                    reason = f"every evidence video failed to fetch: {', '.join(unfetched)}"
                    if unindexed:
                        reason += (f"; {len(unindexed)} of them came down and could not be "
                                   f"indexed instead ({', '.join(unindexed)}) - our failure, "
                                   f"not YouTube's (CF-0281)")
                    reason = _also_too_long(_also_sieved(reason))
                elif unindexed:
                    code = INDEX_FAILED
                    reason = ("every evidence video came down and could not be indexed: "
                              f"{', '.join(unindexed)} - the file is in the cache and the "
                              f"index is not, which is this factory's failure and not "
                              f"YouTube's (CF-0281)")
                    reason = _also_too_long(_also_sieved(reason))
                elif sieved:
                    # Sieve only. The code is the one the sieve wrote for the
                    # first source it took, and each id is named beside the
                    # word for what was seen in it, so the sentence says which
                    # source went and why without a second file being opened.
                    # CF-0817: `host_show` is a word of the source - the topic
                    # it took is counted as somebody else's material.
                    code = failed_why.get(sieved[0], SOURCE_FOREIGN)
                    if code == HOST_SHOW:
                        code = SOURCE_FOREIGN
                    reason = ("every evidence video was indexed and then refused by the "
                              "footage-origin sieve: "
                              + ", ".join(f"{i} ({failed_why.get(i) or SOURCE_FOREIGN})"
                                          for i in sieved)
                              + " - the sources came down and indexed cleanly, and the shot "
                                "descriptions say the footage is not this topic's (CF-0299)")
                    hosts = [i for i in sieved if failed_why.get(i) == HOST_SHOW]
                    if hosts:
                        reason += (f"; {', '.join(hosts)} refused without reading the shots "
                                   f"as somebody else's host show - a podcast, interview "
                                   f"or talk show (CF-0817)")
                    # a half the ceiling refused was never indexed at all, so
                    # the sentence above may not be left to speak for it
                    reason = _also_too_long(reason)
                elif too_long:
                    # CF-0302: the ceiling only. Nothing about this topic was
                    # ever fetched: every candidate it offered was answered by
                    # its own metadata and left where it was, which is why the
                    # sentence says what the length was rather than what a
                    # download or an index did.
                    code = SOURCE_TOO_LONG
                    reason = ("every evidence video was refused before any download as too "
                              "long to index: " + ", ".join(too_long)
                              + " - longer than the ceiling the nature of each is held to "
                                "(channel config sources.youtube.max_source_duration_seconds), "
                                "so nothing was fetched and no attempt was spent on them "
                                "(CF-0302)")
                    reason = _also_unlicensed(reason)
                else:
                    # CF-0663: the licence only. Every candidate the topic
                    # offered carries a licence the channel does not take, and
                    # the indexer refused each before anything was asked of
                    # YouTube - a refusal on rights, not a failed fetch.
                    code = RIGHTS_EXCLUSION
                    changed = [i for i in unlicensed if failed_why.get(i) == LICENCE_CHANGED]
                    if len(changed) == len(unlicensed):
                        tail = (" - the licence read again from the archive before the "
                                "download was not the one the candidate was judged on, so "
                                "nothing came down and no attempt was spent on them (CF-0665)")
                    else:
                        tail = (" - a licence the channel does not take (NC / ND / "
                                "non-free, or refused by the Trend Hunter), so nothing was "
                                "asked of YouTube and no attempt was spent on them (CF-0663)")
                        if changed:
                            tail += ("; the archive's licence of "
                                     f"{', '.join(changed)} changed before the download "
                                     "(CF-0665)")
                    reason = ("every evidence video was refused for its licence: "
                              + ", ".join(_licence(i) for i in unlicensed) + tail)
            else:
                # A failure that names neither this topic nor an id this
                # topic offered is not this topic's failed fetch. Naming the
                # count and stopping there beats guessing which loss it was.
                code = "no_source"
                reason = "no source registered under this topic"
                reason += (f"; the {len(failed)} fetch(es) that failed this run were none of its "
                           f"evidence videos" if failed else
                           " and no fetch failure recorded either")
        # The indexer's own sentence about this topic, under either code: since
        # CF-0129 it refuses a topic it could not get a second source for and
        # records why (`skipped_topics[]`, with the attempts it spent), and that
        # sentence belongs beside the funnel's count of what it registered.
        if rec.get("reason"):
            reason += f" - 01b-footage-index.json: {rec['reason']}"
        # The code the stage that dropped it wrote - the indexer's first: since
        # CF-0129 it is the stage that refuses here, and the writer's skip, when
        # there is one, is about a topic the indexer had already refused.
        rec_code = rec.get("reason_code") or (cr_skipped.get(t) or {}).get("reason_code")
        (carried if went_on else lost).append(
            _loss(t, code, reason, "01b-footage-index.json", recorded_code=rec_code))
        if went_on:
            two.append(t)
    for x in lost + carried:
        note(x)
    steps.append(_step("two_sources", two, lost, carried,
                       f"01b-footage-index.json sources_by_topic[] >= {TWO_SOURCE_FLOOR}"
                       + (f"; {len(on_graphics)} kept on own graphics "
                          f"(own_graphic_footing.kept[], CF-0689)" if on_graphics else ""),
                       kept=on_graphics))

    # 4. scripts -- 03-content-researcher.json. From here on the item is a script_id.
    written, lost = [], []
    depth_of, thin_ids = _pool_depth(idx)
    for t in two:
        ids = by_topic.get(t)
        if ids:
            written += ids
            continue
        row = recorded_loss(t, cr_skipped, "03-content-researcher.json")
        lost.append(_thin_pool_noted(row, t, depth_of, thin_ids))
    for x in lost:
        note(x)
    steps.append(_step("scripts", written, lost, [],
                       "03-content-researcher.json scripts[] (one item per script_id)"))

    # 5. after compliance 2 -- 04-compliance-checker.json (CF-0269). The pass
    #    judges a written script twice and either judgement takes it off the
    #    batch: the rights/risk verdict (`clear|caution|review`, the same
    #    vocabulary the first pass uses) and the contribution check
    #    (`contribution_check.verdict`, `pass|block`, CF-0181). Reading only the
    #    first is what made `lf-2026-09-17-006-script1` come out as
    #    `not_built`: `verdict: clear`, `contribution_check.verdict: block`, and
    #    an Editor that honoured the block by writing nothing.
    #
    #    A script with no row at all goes on unjudged, exactly as before: a
    #    second pass that did not run is not a refusal, and the batches from
    #    before it existed are read as they always were. A script that was
    #    refused and built anyway is `carried_on`, under the same rule as
    #    every other bar in this module - counted in the step it reaches, never
    #    folded into the survivors.
    #
    #    CF-0318 reaches this pass too, and reaches it in the same shape: a
    #    `review` on a written script that carries a `publication_hold` clears
    #    the step and is held from publication. The contribution check is asked
    #    *after* that and is not softened by it - a `block` is a refusal on its
    #    own scale, and a held script it blocks is a script that was never made,
    #    which no hold has anything to say about.
    cleared, lost, carried, on_hold = [], [], [], []
    for sid in written:
        row = v04.get(sid)
        if row is None:
            cleared.append(sid)
            continue
        contribution = row.get(CONTRIBUTION_KEY)
        contribution = contribution if isinstance(contribution, dict) else {}
        if not _goes_on(row):
            code, reason = _refusal(row, " on the written script")
        elif (contribution.get("verdict") or "") == CONTRIBUTION_BLOCK:
            code = "contribution_blocked"
            codes = [c for c in (f.get("reason_code")
                                 for f in _rows(contribution, "failures")) if c]
            if codes and set(codes) == {CLAIM_UNSUPPORTED}:
                code = CLAIM_UNSUPPORTED      # CF-0553: only the claims gate blocked it
            why = (contribution.get("reason") or "").strip()
            reason = ("the contribution check blocked the script"
                      + (" (" + ", ".join(sorted(set(codes))) + ")" if codes else "")
                      + " - a `block` is a refusal on its own scale and does not soften into "
                        "the rights verdict, which here is "
                      + repr(row.get("verdict") or "?")
                      + (f"; 04-compliance-checker.json: {why}" if why else ""))
        else:
            cleared.append(sid)
            if _hold_mark(row):
                on_hold.append(_hold_row(sid, row, "04-compliance-checker.json"))
            continue
        built = sid in videos
        (carried if built else lost).append(
            _loss(sid, code, reason, "04-compliance-checker.json", detail=row))
        if built:
            cleared.append(sid)
    for x in lost + carried:
        note(x)
    for x in on_hold:
        holdback(x)
    if lost or carried or on_hold:
        steps.append(_step("after_compliance_2", cleared, lost, carried,
                           "04-compliance-checker.json results[].verdict in "
                           f"{list(PUBLISH_VERDICTS)} (or {REVIEW_VERDICT!r} with a "
                           f"`{PUBLICATION_HOLD_KEY}`, CF-0318) and {CONTRIBUTION_KEY}.verdict "
                           f"not {CONTRIBUTION_BLOCK!r}"
                           + (f"; {len(on_hold)} held from publication" if on_hold else ""),
                           held=on_hold))

    # 6. ready -- 05-video-editor.json, over what the second pass cleared. A
    #    script it blocked never reached the Editor, so the Editor owes no
    #    `refusals[]` entry for it (CF-0269) and `not_built` keeps meaning a
    #    script the Editor was free to build and neither built nor refused.
    ready, lost, pattern_missing = [], [], []
    short_videos, length_unrecorded = [], []
    admitted = []    # CF-0416: ready on `judge_admitted_despite`, not on qc.passed
    # CF-0376: a video built after the run closed is not the run's output -
    # whatever state its record is in now, it leaves the chain here and is
    # shown on a line of its own (`after_close`), never as ready and never as
    # a loss the run made.
    if events is None and batch_dir is not None:
        try:
            events = runlog.sibling("event_log").load_events(batch_dir)   # CF-0718
        except OSError:
            events = []
    late = after_close_of(events, ve, videos)
    after_close = []
    for sid in cleared:
        v = videos.get(sid)
        if v is not None and sid in late:
            after_close.append(dict(late[sid], ready_now=bool(
                judge_admitted(v) or (not v.get("needs_you")
                                      and (v.get("qc") or {}).get("passed") is True))))
            continue
        if v is None:
            if sid in refusals:
                lost.append(recorded_loss(sid, refusals, "05-video-editor.json"))
            elif ve is None:
                lost.append(_loss(sid, UNEXPLAINED,
                                  "05-video-editor.json is missing, so nothing records what "
                                  "became of this script", "05-video-editor.json"))
            else:
                lost.append(_loss(sid, "not_built",
                                  "05-video-editor.json lists neither a video nor a refusal for "
                                  "this script", "05-video-editor.json"))
            continue
        admitted_despite = judge_admitted(v)
        if admitted_despite:
            admitted.append({"item": sid, "slug": _slug(v), "rules": admitted_despite})
        elif v.get("needs_you"):
            lost.append(_loss(sid, "needs_you", f"the Editor stopped on a NEEDS-YOU line: "
                                                f"{str(v.get('needs_you'))[:160]}",
                              "05-video-editor.json"))
            continue
        if not admitted_despite and (v.get("qc") or {}).get("passed") is not True:
            lost.append(_loss(sid, "qc_failed",
                              f"rendered as {_slug(v)}, QC did not pass it",
                              "05-video-editor.json"))
            continue
        ready.append(sid)
        if v.get("pattern_delivered") in (None, "", False):
            pattern_missing.append({"item": sid, "slug": _slug(v),
                                    "requested": v.get("pattern_requested")})
        # CF-0293 item 3: the short mark, read - never re-derived. The length
        # and the verdict are the Editor's record of the root's own
        # arithmetic; recomputing a band here would give the factory a second
        # opinion on the number it agreed on, which is the defect CF-0158
        # spent its whole design avoiding.
        vl = _video_length(v)
        if vl is None:
            length_unrecorded.append({"item": sid, "slug": _slug(v)})
        elif vl.get("verdict") == VIDEO_LENGTH_SHORT:
            short_videos.append({"item": sid, "slug": _slug(v),
                                 "total_seconds": vl.get("total_seconds"),
                                 "band": vl.get("band"),
                                 "hard_min": vl.get("hard_min"),
                                 "deviation": vl.get("deviation")})
    for x in lost:
        note(x)
    steps.append(_step("ready", ready, lost, [],
                       "05-video-editor.json videos[] with qc.passed and no needs_you, "
                       "or with a non-empty judge_admitted_despite (CF-0416)"
                       + (f"; {len(after_close)} built after the run closed are not "
                          f"counted (CF-0376)" if after_close else "")))

    # 7. frame judge -- 06-frame-judge.json, over what QC passed (CF-0298). The
    #    row exists only for a judged batch; without it `ready` is the last step
    #    exactly as before. With it, `ready` keeps meaning "rendered and QC
    #    passed" and this step is what the batch actually delivered, so the
    #    headline's last number is the judged one: a video whose picture was
    #    about a different film is not a ready video, and DoD item 3 is not a
    #    thing anyone can be counted as having met while it is on the list.
    fj_ready, fj_lost, fj_summary = _frame_judge(A.get(FRAME_JUDGE_FILE), ready, videos)
    if fj_summary is not None:
        for x in fj_lost:
            note(x)
        steps.append(_step("frame_judge", fj_ready, fj_lost, [],
                           f"{FRAME_JUDGE_FILE} videos[] with gate {GATE_PASS!r}"))
        kept = set(fj_ready)
        # The shortfalls below describe *delivered* videos, so a video the judge
        # took off the batch is not one of them: it would be counted as both a
        # loss and a short delivery.
        short_videos = [s for s in short_videos if s["item"] in kept]
        length_unrecorded = [s for s in length_unrecorded if s["item"] in kept]
        pattern_missing = [p for p in pattern_missing if p["item"] in kept]
        ready = fj_ready

    return {"available": True, "missing": missing, "errors": errors, "steps": steps,
            "losses": dict(sorted(losses.items(), key=lambda kv: (-kv[1], kv[0]))),
            "unexplained": unexplained, "unknown_codes": sorted(unknown),
            "silent": bool(unexplained), "pattern_missing": pattern_missing,
            # CF-0917: what 04 owes 03 and does not give (the second compliance
            # pass broke its contract), or None - the triage files it as that
            # pass's авария, and the headline names it beside SILENT.
            COMPLIANCE_ROWS_KEY: _rows_record(cr, c04, cleared, v04),
            # CF-0416: how an admitted video reached `ready` - kept whole even
            # when the judge then refused it (that refusal is its own loss).
            "judge_admitted": admitted,
            # CF-0293: delivered videos with a length shortfall - not losses.
            # `length_unrecorded` keeps "0 short" from reading as "none came
            # out short" on a batch where nothing measured the length at all.
            "short_videos": short_videos, "length_unrecorded": length_unrecorded,
            # CF-0873: refused again from the no-fact memory (not asked
            # again), and whether the shortlist still filled to its size (None
            # = unknown) - only where the stage refused something before
            # selection, so a batch that refused nothing reads as it did.
            "pre_selection": {"recorded": th_recorded, "lost": pre_lost,
                              **({"remembered": pre_remembered,
                                  "shortlist_filled": pre_filled_shortlist,
                                  "spare": len(pre_reserve),
                                  "shortlist_size": want if pre_filled_shortlist is not None
                                  else None} if pre_lost else {})},
            "reserve": held, "shortlist": len(shortlist) if shortlisted else None,
            # CF-0318: the videos that were made and may not be published. Not a
            # loss, not reserve, and not silence - the third thing, which is why
            # it is a list of its own rather than a flag on a loss row.
            "held": holds,
            # CF-0689: topics that passed `two_sources` on own graphics.
            OWN_GRAPHIC_KEPT: [r for s in steps for r in s.get(OWN_GRAPHIC_KEPT) or []],
            "cut": cut,
            # CF-0298: what the frame judge did, or None for a batch nobody
            # judged. `neutral` lives here as a count and never as a loss.
            "frame_judge": fj_summary,
            "ready": [{"item": s, "slug": _slug(videos[s])} for s in ready],
            # CF-0376: built after the run closed - on the record, not the run's
            # output. None when the batch never closed (nothing to split by).
            AFTER_CLOSE_KEY: (after_close if run_spans(events or [])[1] is not None
                              else None),
            "target": target_of(batch_dir, A),
            # CF-0817: sources refused as somebody else's host show, or None.
            HOST_SHOW_KEY: host_show_counts(th, idx),
            # CF-0888: the below-shortlist refill rounds (CF-0882), or None.
            BELOW_SHORTLIST_REFILL_KEY: below_shortlist_refill(
                A[REFILL_RECORD_FILE] if REFILL_RECORD_FILE in A else
                (_read_json(Path(batch_dir) / REFILL_RECORD_FILE) if batch_dir else None),
                th, c02)}


# --------------------------------------------------------------------------
# the text
# --------------------------------------------------------------------------

def _pct(part, whole):
    return f"{round(100.0 * part / whole, 1):g}" if whole else "0"


def _selected_step(f):
    """The `selected` step, wherever it sits. The headline's "N of M topics
    lost" and the target sentence are both read against *the selection*, never
    against `steps[0]`: since CF-0265 there can be a step before it, and a
    shortlist of eight standing in for a batch of five would be the same
    overstatement `fetched: 5` was, only pointing the other way."""
    for s in f.get("steps") or []:
        if s["step"] == "selected":
            return s
    return (f.get("steps") or [None])[0]


def _substitution_rows(f):
    """CF-0306 / CF-0313: ([the refills], [the slots nothing could fill]) of a
    funnel.

    Both are written twice in the chain and read the same way here: the
    indexer's refills live in the `selected` step (CF-0306) and Trend Hunter's
    in `before_selection` (CF-0313), and in both places a refill is
    `reserve_substituted` in `carried_on` while an empty slot is
    `reserve_exhausted` in `lost`. Both lists are empty for every batch written
    before 2026-09-21, so every sentence built from them disappears for those
    batches rather than printing a zero."""
    steps = f.get("steps") or []
    return ([r for s in steps for r in s.get("carried_on") or []
             if r.get("reason_code") == RESERVE_SUBSTITUTED],
            [r for s in steps for r in s.get("lost") or []
             if r.get("reason_code") == RESERVE_EXHAUSTED])


def after_judge_rows(f):
    """CF-0801: the refills of the reserve round after the frame judge - the
    `reserve_substituted` rows whose 01b record is `at: frame_judge_refusal`."""
    filled, _ = _substitution_rows(f or {})
    return [r for r in filled if (r.get("detail") or {}).get("at") == AFTER_JUDGE_AT]


def _unpaid_slots(f):
    """CF-0313: ([the slots the day's search quota did not pay for],
    [the slots whose substitution is decided and not executed]).

    The second list is the `reserve_substituted` rows that stand in `lost`
    rather than in `carried_on` - a decision with nothing behind it yet. It is
    drawn apart from the refills on purpose: a batch whose record says a slot
    is filled while the topic is in no `topics[]` is exactly the overstatement
    this module exists to stop, one step further on."""
    steps = f.get("steps") or []
    lost = [r for s in steps for r in s.get("lost") or []]
    return ([r for r in lost if r.get("reason_code") == SEARCH_QUOTA_EXHAUSTED],
            [r for r in lost if r.get("reason_code") == RESERVE_SUBSTITUTED])


def _remembered_refusal(rec):
    """CF-0873: a `skipped_topics[]` row Trend Hunter refused from one of its
    memories of an earlier batch, and neither probed nor searched again in this
    one: the no-fact memory (CF-0823 - refused `no_fact` before) or, since
    CF-0876, the thin-pool memory (`thin_pool_memory` - refused `pool_too_thin`
    at 0 clean shots before, and the pool holds no new video for the work)."""
    if not isinstance(rec, dict):
        return False
    probe = rec.get("fact_probe") if isinstance(rec.get("fact_probe"), dict) else {}
    return (probe.get("source") == NO_FACT_MEMORY_SOURCE
            or isinstance(rec.get("fact_memory"), dict)
            or isinstance(rec.get(THIN_POOL_MEMORY_KEY), dict))


def _pre_selection_cost(pre_sel):
    """CF-0873: the words after "N refused before selection" - how many were
    repeats from a memory of an earlier batch (no-fact CF-0823, thin pool
    CF-0876), and whether the shortlist still filled."""
    notes = []
    remembered = pre_sel.get("remembered") or []
    if remembered:
        notes.append(f"{len(remembered)} remembered from an earlier batch (no_fact CF-0823 / "
                     f"thin pool CF-0876), not asked again")
    notes.extend(_pre_selection_slots(pre_sel))
    return f" ({'; '.join(notes)})" if notes else ""


def _pre_selection_slots(pre_sel):
    """CF-0873: did the refusals before selection cost the batch a slot? Not
    when the shortlist still filled to its size, and not when viable topics were
    left over past it (`below_shortlist`): a slot empty later is then somebody
    else's doing. Only a shortlist under its size with nothing spare says yes."""
    filled, size = pre_sel.get("shortlist_filled"), pre_sel.get("shortlist_size")
    spare = pre_sel.get("spare") or 0
    if filled is True:
        return [f"the shortlist still filled to {size}, so they cost no slot"]
    if filled is False and spare:
        return [f"{spare} viable topic(s) left over past the shortlist, so they cost no slot"]
    if filled is False:
        return [f"the shortlist stayed under {size} with no viable topic to spare"]
    return []


def headline(f):
    """One line for the top of RUN_SUMMARY, beside the GAPS line: the chain, the
    losses by code, and - loudly - any loss nobody explained."""
    if not f or not f.get("available"):
        return "FUNNEL: no stage artifacts in the batch directory - no topic funnel"
    steps = f["steps"]
    chain = " -> ".join(f"{s['label']} {s['count']}" for s in steps)
    first, last = _selected_step(f)["count"], steps[-1]["count"]
    bits = [f"FUNNEL: {chain}"]
    if first:
        bits.append(f"{first - last} of {first} topics lost ({_pct(first - last, first)} %)")
    pre_sel = f.get("pre_selection") or {}
    pre = len(pre_sel.get("lost") or [])
    if pre:
        bits.append(f"{pre} refused before selection" + _pre_selection_cost(pre_sel))
    reserve = f.get("reserve") or []
    if reserve:
        bits.append(f"{len(reserve)} held in reserve, not lost")
    # CF-0318: beside the reserve and for the same reason - a batch of five that
    # made five videos of which one may not be uploaded has not had the run the
    # bare chain describes, and the difference is not a loss.
    on_hold = f.get("held") or []
    if on_hold:
        bits.append(f"{len(on_hold)} held from publication, made and unpublishable "
                    f"until signed")
    # CF-0689: under the source floor and in the batch - not a loss.
    on_graphics = f.get(OWN_GRAPHIC_KEPT) or []
    if on_graphics:
        bits.append(f"{len(on_graphics)} kept on own graphics, not lost")
    # CF-0306: beside the reserve, and for the same reason - a batch of five
    # that lost two and refilled both is not the batch the bare chain describes.
    filled, empty = _substitution_rows(f)
    if filled:
        late = after_judge_rows(f)
        bits.append(f"{len(filled)} slot(s) refilled from reserve"
                    + (f" ({len(late)} {AFTER_JUDGE_RU})" if late else "")
                    + ", in the batch and not spare")
    if empty:
        bits.append(f"{len(empty)} slot(s) left empty, reserve exhausted")
    # CF-0313: the two ways a slot can be empty without the reserve being out.
    unpaid, undone = _unpaid_slots(f)
    if unpaid:
        bits.append(f"{len(unpaid)} slot(s) left empty, the day's search quota is spent")
    if undone:
        bits.append(f"{len(undone)} slot(s) awaiting the footage search that fills them")
    short = f.get("short_videos") or []
    if short:
        # CF-0293: on the headline beside the reserve, and for the same
        # reason - it is not a loss and may not be counted as one, but a batch
        # that delivered three videos of which two are under the band has not
        # had the run the number `ready 3` describes.
        lens = ", ".join(f"{s['slug']} {s['total_seconds']:g}s" for s in short
                         if s.get("total_seconds") is not None)
        bits.append(f"{len(short)} of {last} ready came out short"
                    + (f" ({lens})" if lens else ""))
    late = f.get(AFTER_CLOSE_KEY) or []
    if late:
        # CF-0376: beside the chain and never in it - the run did not return these.
        bits.append(f"after close: {len(late)} built after the run closed, not counted "
                    f"({', '.join(r['slug'] for r in late)})")
    if f["losses"]:
        bits.append("losses: " + ", ".join(f"{k} {v}" for k, v in f["losses"].items()))
    hs = f.get(HOST_SHOW_KEY)
    if hs:
        # CF-0817: not a loss of its own - a topic it emptied is in `losses`
        # under `source_foreign` - but the count of what the rule kept out.
        bits.append(f"host shows refused {sum(hs.values())} (CF-0817: "
                    f"{hs['dropped']} candidates dropped, {hs['at_pool']} at the pool, "
                    f"{hs['at_sieve']} at the sieve)")
    # A substituted topic is in `carried_on` because that is where the record of
    # how it entered the batch belongs, and it cleared every bar it was asked to
    # clear - so it is not one of the topics this sentence is about (CF-0306).
    carried = sum(len([r for r in s["carried_on"]
                       if r["reason_code"] not in SUBSTITUTION_CODES]) for s in steps)
    if carried:
        bits.append(f"{carried} went past a bar they did not clear")
    if f["silent"]:
        bits.append(f"**{len(f['unexplained'])} SILENT** (no stage said why)")
    rows = f.get(COMPLIANCE_ROWS_KEY) or {}
    if rows.get("missing"):
        # CF-0917: why they are silent - 04 has no row for them
        bits.append(f"{len(rows['missing'])} script(s) with no row in {SCRIPTS_04_FILE} "
                    f"(the second compliance pass broke its contract, CF-0917)")
    return " - ".join(bits)


def _after_close_lines(f):
    """CF-0376: the videos built after the run closed, under the ready list."""
    late = f.get(AFTER_CLOSE_KEY) or []
    if not late:
        return []
    rows = []
    for r in late:
        state = "ready now" if r.get("ready_now") else "not ready now"
        rows.append(f"`{r['item']}` ({r['slug']}) built {r.get('built_at') or '?'} "
                    f"[{r['basis']}], {state}"
                    + (f" - reason: {r['reason']}" if r.get("reason")
                       else " - reason: not recorded"))
    return [f"**after close: {len(late)}** - built in this directory after the run's "
            f"`batch-done`, so not the run's output and in neither `ready` nor the frame "
            f"judge's count (CF-0376): " + "; ".join(rows), ""]


def _block_word(b):
    """CF-0888: `block-2 thin_strip` - a repaired block and its defect."""
    return " ".join(str(x) for x in (b.get("entry") or b.get("block"), b.get("kind")) if x)


def _frame_judge_lines(f):
    """CF-0298: what the frame judge saw, under the ready list. `neutral` is the
    number this paragraph exists for - it is not a loss and so appears in no
    table above, and a batch quietly drifting from `backs` to `neutral` is a
    batch whose pictures are getting weaker with nothing anywhere saying so."""
    fj = f.get("frame_judge")
    if not fj:
        return ["frame judge: not run for this batch - no `" + FRAME_JUDGE_FILE + "`. "
                "Every batch before 2026-09-20 predates the stage (CF-0298); for a later "
                "one this means DoD item 3 went unchecked, not that it passed.", ""]
    c, v = fj["counts"], fj["verdicts"]
    if fj.get("nothing_to_judge") and not c["judged"] and not c["not_judged"]:
        # CF-0707: the stage ran and wrote its record; there was no video to judge.
        return [f"frame judge: ran, {fj['nothing_to_judge']}.", ""]
    bits = [f"{c['judged']} video(s) judged: {c['passed']} passed, {c['rejected']} rejected"]
    if c["incomplete"]:
        bits.append(f"{c['incomplete']} judged only in part")
    if c["not_judged"]:
        bits.append(f"{c['not_judged']} not judged")
    L = ["**frame judge (DoD item 3): " + ", ".join(bits) + "**. Entries: "
         + ", ".join(f"{v[w]} `{w}`" for w in FRAME_VERDICTS)
         + (f", {v['foreign_text']} carrying foreign on-screen text (DoD item 2)"
            if v["foreign_text"] else "")
         + (f". Any `{'`/`'.join(BLOCKING_VERDICTS)}` or foreign text took the video off "
            f"`ready` under `{FRAME_JUDGE_FAILED}`; `{NEUTRAL_VERDICT}` is counted here and "
            f"never rejects (the user's decision of 2026-09-20, `{FRAME_JUDGE_SCHEMA_V1}`)."
            if fj.get("schema") == FRAME_JUDGE_SCHEMA_V1 else
            f". Every `contradicts`/`neutral`/`foreign` (and foreign text) is a penalty of "
            f"the score model; a video leaves `ready` only when its score after the judge "
            f"is under N (`{SCORE_BELOW_THRESHOLD}`), or under `{FRAME_JUDGE_FAILED}` when "
            f"its judgement is unfinished (CF-0434).")]
    if fj["unreadable_frames"]:
        L[-1] += f" {fj['unreadable_frames']} frame(s) of the packs could not be read."
    L.append("")
    if fj["neutral_entries"]:
        L += ["neutral: " + "; ".join(
            f"{e['slug']} `{e['entry']}`" + (f" - {(e['why'] or '').replace('|', '/')}"
                                             if e.get("why") else "")
            for e in fj["neutral_entries"]), ""]
    rp = fj.get("repairs")
    if rp:
        L += [f"repair after the judge (CF-0881): {rp[JUDGE_REPAIRED]} `{JUDGE_REPAIRED}`, "
              f"{rp[JUDGE_REPAIR_FAILED]} `{JUDGE_REPAIR_FAILED}` - " + "; ".join(
                  f"{x['slug']} ({', '.join(_block_word(b) for b in x.get('block_details') or []) or ', '.join(x['blocks'])}, was `{x['before']}`): {x['outcome']}"
                  + (f" - {(x['reason'] or '').replace('|', '/')[:200]}" if x.get("reason") else "")
                  for x in rp["videos"]), ""]
    if fj["not_judged"]:
        L += ["not judged: " + "; ".join(f"`{n['item']}` ({n['slug']}) - {n['reason']}"
                                         for n in fj["not_judged"])
              + ". Counted as ready: nobody looked, which is not the same as a refusal - "
                "but it is also not a check that ran.", ""]
    return L


def render(f, level="##", number=7):
    """The Markdown section."""
    L = [f"{level} {number}. Topic funnel", ""]
    if not f or not f.get("available"):
        L += ["No stage artifact (`01-trend-hunter.json` ... `05-video-editor.json`) is in the "
              "batch directory, so there is no funnel to draw: the events say when the stages "
              "ran, the artifacts say what they decided (CF-0232).", ""]
        return L
    steps = f["steps"]
    first = _selected_step(f)["count"]
    reserve = f.get("reserve") or []
    on_hold = f.get("held") or []
    # The reserve column exists only when something is in it: a batch that ran
    # before the cut (CF-0265) draws the table it always drew. CF-0318's column
    # is there on the same terms, and it is a column and not a share of `lost
    # here` because the topic is counted in `topics` - it passed the step.
    L += ["| step | topics | lost here |" + (" held in reserve |" if reserve else "")
          + (" held from publication |" if on_hold else "")
          + " carried on | measured from |",
          "|---|---|---|---|---|" + ("---|" if reserve else "") + ("---|" if on_hold else "")]
    for s in steps:
        def codes(rows):
            if not rows:
                return "-"
            n = {}
            for r in rows:
                n[r["reason_code"]] = n.get(r["reason_code"], 0) + 1
            return ", ".join(f"`{k}` {v}" for k, v in sorted(n.items()))
        L.append(f"| {s['label']} | {s['count']} | {codes(s['lost'])} | "
                 + (f"{codes(s.get('reserve') or [])} | " if reserve else "")
                 + (f"{codes(s.get('held') or [])} | " if on_hold else "")
                 + f"{codes(s['carried_on'])} | {s['basis'] or '-'} |")
    L.append("")
    last = steps[-1]["count"]
    L.append(f"{first} topic(s) selected, {last} ready: "
             f"{first - last} lost ({_pct(first - last, first)} %). "
             f"`ready` counts a video the Editor rendered and QC passed; a topic in "
             f"`carried on` did not clear that step's bar and went on anyway, because nothing "
             f"in the batch that ran enforced it - it is counted in the step it reaches, never "
             f"in the one it failed. (`video_editor.two_source_gate` was `measure` until "
             f"2026-09-16, CF-0118, `enforce` from then, CF-0129, and `measure` again since "
             f"2026-09-23, CF-0330 - the Editor records and renders. Since 2026-09-16 a topic "
             f"under the source floor is refused by the indexer (`no_second_source`) and "
             f"appears in `lost here` rather than in `carried on`.)")
    L.append("")
    if reserve:
        n_cut = len([r for r in reserve if r["reason_code"] == "reserve_unused"])
        n_short = len(reserve) - n_cut
        sl = f.get("shortlist")
        L += [f"`selected` is what the cut carried, not the shortlist: since CF-0264 Trend "
              f"Hunter hands out up to `scope.shortlist_size` topics"
              + (f" (here {sl})" if sl else "")
              + f", compliance judges all of them, and the cut that follows it (CF-0265) carries "
                f"the first `scope.max_titles_per_batch` with a passing verdict into the batch. "
                f"{len(reserve)} topic(s) are in reserve - "
              + (f"{n_short} past the shortlist, " if n_short else "")
              + f"{n_cut} past the cut - and they are **not** losses: the batch kept a spare "
                f"rather than dropped a topic, and counting them as lost would misread the "
                f"target the same way `fetched: 5` did, only in the other direction. They carry "
                f"a code all the same (`below_shortlist`, `reserve_unused`), because an "
                f"unrecorded spare and an unrecorded loss are the same hole in the bookkeeping "
                f"(DoD 1.4.4 item 1). A topic compliance refused **is** a loss and stands in the "
                f"table above; what changed on 2026-09-17 is that the cut gives its slot to the "
                f"next eligible topic instead of letting the batch run one short - on 2026-09-16 "
                f"Spire-Runner took a slot, compliance refused it, and nothing replaced it.", ""]
    if on_hold:
        L += [f"**{len(on_hold)} video(s) are held from publication, not from production** "
              f"(CF-0318, the user's decision of 2026-09-22). A `review` verdict used to take "
              f"the topic off the batch at the indexer - nobody looks at a batch while it runs, "
              f"so a topic parked for review was a topic dropped - and this table put a price "
              f"on that: `compliance_review` cost 19 topics of 101 across ten instrumented "
              f"runs, second only to `no_production_fact`. The user decided that without a "
              f"human's approval only the **upload** is forbidden, so the topic now keeps its "
              f"slot and the video is made. The verdict is not milder for it: it is still "
              f"`review`, earned by the same rights match or sensitivity flag, and the video "
              f"may not go up until the user signs its row. Held here: "
              + "; ".join(f"`{r['item']}` ({(r.get('detail') or {}).get('verdict')})"
                          for r in on_hold)
              + f". The mark is in two places, and they are not a duplicate: a "
                f"`{PUBLICATION_HOLD_KEY}` block on the row of the compliance artifact, so the "
                f"batch explains itself, and a row in `publish/publication-holds.json`, which "
                f"is the authority - `scripts/monthly_archive.py` ZIPS a batch onto "
                f"Archive and deletes it after 30 days and Publisher (CF-0017/CF-0018) is milestone 2.0, "
                f"so the reader of this mark arrives after the batch directory is gone. "
                f"`signature` is a human's: the user signs by hand, or the command center "
                f"writes it on the user's explicit action with a note (`sign_hold`, CF-0687); "
                f"no other code writes one (the rule `shared/gate-prices.json` follows, CF-0320). These rows are in no "
                f"`losses` total and in no \"went past a bar\" count: the bar the gate sets is "
                f"production, and they cleared it.", ""]
    all_filled, all_empty = _substitution_rows(f)
    unpaid, undone = _unpaid_slots(f)
    # CF-0313: the same two words are now written by two stages, and each
    # paragraph has to speak about the rows its own stage wrote - a refill Trend
    # Hunter made is not in `01b-footage-index.json` and saying so would send a
    # reader to the wrong file.
    filled = [r for r in all_filled if r.get("stage") != "01-trend-hunter.json"]
    empty = [r for r in all_empty if r.get("stage") != "01-trend-hunter.json"]
    th_filled = [r for r in all_filled if r.get("stage") == "01-trend-hunter.json"]
    th_empty = [r for r in all_empty if r.get("stage") == "01-trend-hunter.json"]
    if th_filled or th_empty or unpaid or undone:
        L += [f"**A slot Trend Hunter emptied at step 5b is refilled there** (CF-0313, "
              f"2026-09-22). A topic whose footage sieves leave fewer than two candidates is "
              f"refused by the stage itself (`no_source`, CF-0309), and until this task its "
              f"shortlist slot stayed empty while the `below_shortlist` reserve sat unused. The "
              f"stage now takes the next reserve topic by rank, walks it through step 5b like "
              f"any other and records the swap in `01-trend-hunter.json` -> "
              f"`{FOOTAGE_SUBSTITUTION_KEY}`, which is what the `before selection` step above "
              f"draws."
              + (f" {len(th_filled)} slot(s) were refilled: "
                 + "; ".join(f"`{r['item']}` for `{(r.get('detail') or {}).get('replaced')}`"
                             for r in th_filled)
                 + " - the substitute is in `topics[]`, is counted in the step's own number and "
                   "is judged by compliance on its first pass like any other topic." if th_filled
                 else "")
              + (f" {len(undone)} substitution(s) are decided and not executed "
                 f"(`{PENDING_SEARCH}`): the facet search a substitute needs is a network call "
                 f"the stage does not make, so the topic is in no `topics[]` and the slot is "
                 f"still empty. It stands in `lost here` and never among the refills - a record "
                 f"saying the batch is full while the disk says it is not is the "
                 f"overstatement this module exists to stop." if undone else "")
              + (f" {len(unpaid)} slot(s) were not refilled for want of quota "
                 f"(`{SEARCH_QUOTA_EXHAUSTED}`): a substitution is one facet run against the "
                 f"day's 100 `search.list` calls (CF-0288), and when the day will not pay for "
                 f"it nothing is looked for. That is a limit of ours, not a fact about the "
                 f"topic, which is why it is neither `no_source` nor a `losses` count - the "
                 f"topic whose slot it was is counted once, above, under its own code."
                 if unpaid else "")
              + (f" {len(th_empty)} slot(s) found the reserve already spent "
                 f"(`{RESERVE_EXHAUSTED}`): `scope.shortlist_size` is the number to raise."
                 if th_empty else ""), ""]
    if filled or empty:
        L += [f"**The reserve was used** (CF-0306, the user's decision of 2026-09-21). Until "
              f"then the cut was the only place a spare could be spent, so a topic lost "
              f"*after* it - at the indexer, at the sieve, at the Researcher - left the batch "
              f"one short with cleared spares sitting unused: on 2026-09-21 four of five "
              f"carried topics were lost that way and The Long Voyage and Outrider were never "
              f"touched. The indexer now refills the freed slot from the reserve and records "
              f"the swap in `01b-footage-index.json` -> `reserve_substitution`."
              + (f" {len(filled)} slot(s) were refilled here: "
                 + "; ".join(f"`{r['item']}` for `{(r.get('detail') or {}).get('replaced')}` "
                             f"(`{(r.get('detail') or {}).get('replaced_reason_code')}` at "
                             f"`{(r.get('detail') or {}).get('replaced_stage')}`)"
                             for r in filled)
                 + ". A refilled slot is **not** a loss and **not** reserve: the topic is "
                   "counted in `selected`, walks every step below like any other, and is out "
                   "of the `held in reserve` column - which is why it stands in `carried on` "
                   "with its own code rather than in a count of something." if filled else "")
              + (f" {len(empty)} slot(s) could not be refilled (`{RESERVE_EXHAUSTED}`): the "
                 f"reserve was used up, so the batch ran short of what the cut carried. That "
                 f"is a shortlist too small for what this batch lost, not a refusal of any "
                 f"stage - `scope.shortlist_size` is the number to raise - and it is counted "
                 f"in no `losses` total, because the topic whose slot it was is already "
                 f"counted once under its own code at the step that lost it." if empty else ""),
              ""]
    ac2 = next((s for s in steps if s["step"] == "after_compliance_2"), None)
    if ac2:
        blocked = len([r for r in ac2["lost"] + ac2["carried_on"]
                       if r["reason_code"] == "contribution_blocked"])
        L += [f"`after compliance 2` is the second compliance pass "
              f"(`04-compliance-checker.json`), which judges the written scripts and judges "
              f"each of them twice: the rights/sensitivity verdict, on the same "
              f"`clear|caution|review` scale the first pass uses, and the contribution check "
              f"(`{CONTRIBUTION_KEY}.verdict`, `pass|block`, CF-0181). Either one takes the "
              f"script off the batch, and a row can read `verdict: clear` and still be a "
              f"refusal"
              + (f" - {blocked} here did" if blocked else "")
              + ". Before CF-0269 the funnel read only the first of the two, and only inside "
                "the `ready` step, so a blocked script came out as `not_built` - the Editor's "
                "silence read as the Editor's decision, which is the observer's inference "
                "CF-0254 took away from the Editor. The Editor writes no `refusals[]` entry "
                "for such a script and is not meant to: it was never handed the script, so it "
                "made no decision to record, and the loss belongs to the stage that did "
                "(CF-0269). The step is drawn only when this pass refused something; a batch "
                "whose scripts all cleared it reads exactly as it did before.", ""]
    pre = f.get("pre_selection") or {}
    pre_lost = pre.get("lost") or []
    if pre_lost:
        L += [f"Before the chain: {len(pre_lost)} topic(s) refused by Trend Hunter itself "
              f"(`01-trend-hunter.json` -> `skipped_topics[]`), so they are in no `topics[]` "
              f"and in none of the counts above - they are in the losses by code and in the "
              f"table below, with the code the stage wrote (CF-0129). A topic with no footage "
              f"candidate at all is refused there rather than carried to the indexer."
              + (" They are the `before selection` step, whose own count is the shortlist that "
                 "survived them (CF-0265)." if f.get("shortlist") else "")
              + (f" {len(pre['remembered'])} of them Trend Hunter refused from its no-fact "
                 f"memory (`no-fact-memory.json`, CF-0823): refused `no_fact` in an earlier "
                 f"batch and not asked again in this one - a repeat, not a new refusal"
                 f" (or, since CF-0876, held back by its thin-pool memory: refused "
                 f"`pool_too_thin` at 0 clean shots in an earlier batch, `thin_pool_memory`)."
                 if pre.get("remembered") else "")
              + "".join(f" Slots (`selection.shortlist_size`, CF-0873): {w}."
                        for w in _pre_selection_slots(pre)), ""]
    elif pre.get("recorded"):
        L += ["Trend Hunter refused no topic before selection "
              "(`01-trend-hunter.json` -> `skipped_topics[]` is empty).", ""]
    elif pre.get("recorded") is False:
        L += ["`01-trend-hunter.json` carries no `skipped_topics[]`: the field arrived on "
              "2026-09-16 with CF-0129, so for this batch nothing is *said* about what Trend "
              "Hunter refused before selection - which is not the same as nothing having been "
              "refused, and the counts above start at what it did select.", ""]
    t = f.get("target")
    if t:
        want, cap = t.get("ready"), t.get("max_titles")
        bits = []
        if want is not None:
            bits.append(f"{want} ready video(s)")
        if cap is not None:
            bits.append(f"at most {cap} selected topic(s)")
        L += [f"This channel aims a batch at " + " from ".join(bits)
              + f" (`{t['config']}` -> `scope`). This batch selected {first} and ended on "
                f"{last}."
              + (f" The selection was cut from a shortlist of {f['shortlist']} "
                 f"(`scope.{SHORTLIST_KEY}`"
                 + (f" is {t['shortlist']}" if t.get("shortlist") is not None else "")
                 + "), which is a pool and not a target." if f.get("shortlist") else "")
              + f" The target is read against the funnel and never padded up to: a "
                f"batch may deliver fewer, and a topic that cannot carry its pattern is "
                f"refused with a code rather than counted (grill of 2026-09-16).", ""]
    if f["silent"]:
        L += [f"**silent losses: {len(f['unexplained'])}** - no stage recorded why these left "
              f"the batch. This is the defect DoD 1.4.4 item 1 forbids; the funnel can name the "
              f"hole but not fill it.", ""]
    else:
        L += ["silent losses: none - every loss above carries a code.", ""]
    rows = [(st["label"], r, kind) for st in steps
            for kind, rs in (("lost", st["lost"]), ("carried on", st["carried_on"]),
                             ("held in reserve", st.get("reserve") or []),
                             ("held from publication", st.get("held") or []),
                             ("kept on own graphics", st.get(OWN_GRAPHIC_KEPT) or []))
            for r in rs]
    if rows:
        L += ["| step | item | outcome | code | recorded as | why |",
              "|---|---|---|---|---|---|"]
        for label, r, kind in rows:
            rec = f"`{r['recorded_code']}`" if r["recorded_code"] else "-"
            why = (r["reason"] or "-").replace("|", "/")
            L.append(f"| {label} | `{r['item']}` | {kind} | `{r['reason_code']}` | "
                     f"{rec} | {why} |")
        L.append("")
    if f["ready"]:
        L.append("ready: " + ", ".join(f"`{r['item']}` ({r['slug']})" for r in f["ready"]))
        L.append("")
    rl = refill_line(f.get(BELOW_SHORTLIST_REFILL_KEY))
    if rl:
        L += [rl, ""]
    L += _after_close_lines(f)
    L += _frame_judge_lines(f)
    # CF-0293 item 3: how many of the batch's videos came out short, and how
    # long each one is. Under the ready list rather than in the table, on the
    # same terms as `pattern_delivered: null` above: the video exists and QC
    # passed it, so it is a shortfall of a delivered video and not a lost
    # topic. It is here so that (a) the operator reading a run sees at once
    # that a batch of three delivered two videos the channel does not want to
    # be making, and (b) the Analyst (2.1) has length beside the batch it
    # belongs to when it puts length against retention.
    short = f.get("short_videos") or []
    unrecorded = f.get("length_unrecorded") or []
    ready_n = last
    if short:
        n = len(short)
        lo = next((s["band"][0] for s in short if s.get("band")), None)
        hard = next((s["hard_min"] for s in short if s.get("hard_min") is not None), None)
        rows = ", ".join(
            f"{s['slug']} {s['total_seconds']:g}s"
            + (f" ({s['deviation']:+g}s)" if s.get("deviation") is not None else "")
            for s in short if s.get("total_seconds") is not None)
        L += [f"**short videos: {n} of {ready_n} ready** - " + rows
              + (f". Under the channel's {lo:g}s floor"
                 f"{f' and above its {hard:g}s hard floor' if hard is not None else ''}, "
                 if lo is not None else ". ")
              + "which is a video the channel still publishes and does not want to be "
                "making (CF-0158's band, CF-0293's decision of 2026-09-20: under 45 s the "
                "video is kept, with a warning and counted"
              + (f"; under {hard:g}s it is refused before the render and leaves the batch "
                 f"as `{VIDEO_TOO_SHORT}` in the table above" if hard is not None else "")
              + "). Not a loss - the video exists and QC passed it. The length is the "
                "Editor's own record (`videos[].duration.narration.video_length`), read "
                "here and not re-derived.", ""]
    elif unrecorded and len(unrecorded) == ready_n and ready_n:
        L += [f"short videos: not measured - none of the {ready_n} ready video(s) carries "
              f"`duration.narration.video_length`. The field arrived with CF-0158 "
              f"(2026-09-08), so for an older batch nothing *says* how long its videos "
              f"came out, which is not the same as none of them being short.", ""]
    elif ready_n:
        L += [f"short videos: none - every one of the {ready_n} ready video(s) landed inside "
              f"the channel's band"
              + (f" ({len(unrecorded)} of them carry no length record and are not counted "
                 f"either way)" if unrecorded else "") + ".", ""]
    if f["pattern_missing"]:
        n = len(f["pattern_missing"])
        L += [f"Of the ready videos, {n} "
              + ("carries" if n == 1 else "carry")
              + " `pattern_delivered: null`: "
              + ", ".join(f"{p['slug']} (requested `{p['requested'] or '?'}`)"
                          for p in f["pattern_missing"])
              + ". Not counted as a loss - the video exists and passed QC; this is the shortfall "
                "of DoD 1.4.4 item 3 (CF-0233 / CF-0245), and a topic that cannot deliver its "
                "pattern is meant to be refused **before** the render with "
                "`pattern_undeliverable`.", ""]
    if f.get("judge_admitted"):
        L += ["Admitted to the judge despite a QC refusal the channel counts as cosmetic "
              "(`judge_admitted_despite`, CF-0416): "
              + ", ".join(f"{a['slug']} ({', '.join(a['rules'])})" for a in f["judge_admitted"])
              + ". `qc.passed` stays false in 05-video-editor.json; the judge's verdict is "
                "what decides.", ""]
    if f["unknown_codes"]:
        L += ["Code(s) outside the funnel's vocabulary: "
              + ", ".join(f"`{c}`" for c in f["unknown_codes"])
              + f". The vocabulary is funnel.FUNNEL_CODES; a stage writing a code the root does "
                f"not know is a contract to fix, not a loss to hide.", ""]
    if f["missing"]:
        L += ["Artifact(s) absent from the batch directory: "
              + ", ".join(f"`{m}`" for m in f["missing"])
              + " - the steps they measure stand on what the neighbouring stages recorded.", ""]
    for e in f["errors"]:
        L += [f"Artifact unreadable: {e}", ""]
    return L


def main(argv=None):
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import runlog                                                   # noqa: PLC0415
    ap = argparse.ArgumentParser(prog="runlog funnel",
                                 description="the topic funnel of one batch (CF-0232)")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    bdir = runlog.find_batch_dir(ns.batch)
    if bdir is None:
        sys.stderr.write("runlog funnel: error: no batch directory (use --batch DIR)\n")
        return 2
    f = funnel(bdir)
    if ns.json:
        print(json.dumps(f, ensure_ascii=False, indent=2, default=str))
    else:
        print(headline(f))
        print()
        print("\n".join(render(f)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

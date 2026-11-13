#!/usr/bin/env python3
"""CF-0411 (part 2): a script leaves this stage only once the Video Editor's
own gates have built a plan out of it.

Why
---
Batch `example-film/2026-09-27T0929Z` shipped 0 videos. Three of its five
scripts passed this stage's pre-checks (`check_block_capacity`,
`check_anchor_coverage`: "ok") and then died at the Editor after the voice and
the resolve were paid for - Backrooms on `pattern_ceiling` (3.8 blocks/min
against a floor of 15.39), Wolfhame on the cut-clip gate refusing every free
shot. The rebuild saved them by editing the **anchors only**, never the
narrator's text, against the refusals of the real resolve and plan. The
user's decision of 2026-09-28: that loop runs **inside this stage**. The
pre-checks stay as the cheap filter; the verdict "buildable" is the real
plan's.

What it does
------------
For every script of `03-content-researcher.json` (or the ones `--script-id`
names) it runs the Editor's `scripts/plan_check.py check` on the Editor's venv
- TTS, alignment, anchor spec, `resolve_anchors.py`, `build_render_plan.py`,
no render - reads the verdict `work/<slug>/plan_check.json` and prints one of:

  ASSEMBLED      the Editor built a plan; the script goes on (compliance pass 2,
                 then the Editor renders that very plan).
  EDIT ANCHORS   not built; the lines under it say, per refusal, what to change
                 in the script's `visual_anchors` - and only there - before the
                 next run of this same command.
  DROPPED        not built and no round left (or a refusal no anchor can fix):
                 with `--write` the topic leaves `scripts[]` for `skipped[]` as
                 `plan_unassembled`.
  ENVIRONMENT    plan_check.py could not answer (a tool crashed, a file is
                 missing) - nothing about the script. It goes on as before
                 this file existed: the Editor finds no verdict it can reuse
                 and builds it the old way.

The rules
---------
* **Rounds.** The first check is free; after it the writer has
  `content_researcher.plan_check_rounds` anchor-edit rounds (the channel config
  at the factory root, `channels/<channel>.json`; DEFAULT_ROUNDS = 3 when the
  key is absent, CF-0430). A round is one more run of this command on a script
  that was not built **and whose inputs changed** - an anchor edit, or a new
  pool. When the last round is spent and the plan is still not built, the topic
  is dropped. A run that ended in ENVIRONMENT spends nothing.
* **A rerun with nothing edited spends nothing** (CF-0430, the user's decision
  of 28.09 on `example-film/2026-09-28T1126Z`, option A: forbidden by mechanics,
  not by a sentence). Until then such a rerun spent a round "so the stage
  always closes", and a round burned on no edit is a video lost for nothing.
  Now, when the Editor's `plan_check.py` answers `UNCHANGED since round N` (its
  inputs - text, anchors, pool, pattern - are the last check's) on a script it
  did not build, the check is not counted: the run prints
  `UNCHANGED - edit the script first` (`_rewrite_guard.UNCHANGED`, the word the
  step-6 gates print), exits 1 as the last run did, and records the rerun as
  `unchanged_reruns` in `plan_check_loop.json`. The stage still closes: the
  last round spent, a refusal no anchor can fix, or `--final` (the writer has
  no edit left) drops what is still not built - with or without an edit.
* **An anchor-edit pass that changed nothing is a spent round** (CF-0793,
  batch `example-film/2026-10-18T0841Z`: four passes of the run plan's
  `plan-check-anchor-edit` handler left frisco-king's anchors as the last
  check had them, each rerun was UNCHANGED and spent nothing, the stage ran
  out of reruns and the batch failed with three scripts ready). The run plan
  reruns this command after the handler with `PLAN_CHECK_EDIT_PASS=1` (or
  `--edit-pass`): when such a run is UNCHANGED and no check was made since
  the run that handed the script to the pass (`edit_pass_from_check` in the
  leg's state), the pass is recorded as a check (`unchanged_edit_pass`) and
  spends its round - so every pass spends at least one round and the loop
  closes within `plan_check_rounds` passes. A pass that edited and ran this
  command itself spent its round there; the rerun after it spends nothing
  more. Without the flag (the writer's own reruns) CF-0430 holds unchanged.
* **The text is not touched.** The narrator's text (hook, commentary, payoff)
  passed every text gate of step 6 - budget, production fact, proofs, cadence
  - and none of them runs again here. So this command snapshots it on the
  first check (`work/<slug>/plan_check_loop.json`) and, when a later run finds
  it changed, **rolls it back** to the snapshot (`--write`) before the check:
  the anchor edits of that round are kept and checked against the text the
  gates cleared, the voice is reused (no TTS paid), and the rollback is
  recorded and printed. CF-0852: the records step 6 writes on that text
  (`TEXT_RECORDS`: the fact and its beat, `claims[]`, the graphics, the
  gates' verdicts) are snapshotted with it and rolled back with it - the text
  alone rolled back under a beat and claims quoting the rewritten words
  (example-tech `2026-10-23T0831Z`), and the root contract went red. A rollback keeps the video; dropping the topic for an
  operator slip would lose it for nothing the gates did not already clear.
  When there is no snapshot to go back to - the verdict says the text differs
  from its round 1 (`text_changed`) - the guard drops the topic instead: the
  voice was built from a text none of this stage's gates judged, and nothing
  here can tell which of the two was meant.
* **The records quote the text the check is built on** (CF-0860,
  example-film `2026-10-24T0840Z`: the claims judge's rewrite, the cadence and
  the number density rewrote the fact's sentence after
  `check_production_fact.py` had passed - `claims[]` went along, the fact's
  beat did not; the snapshot took that, wildwood's video went out with no
  fact line and the root contract went red). Before every check a
  `production_fact.beat_text` that is not in the commentary is re-anchored
  to the commentary's words the fact is spoken in now
  (`check_production_fact.reanchor_beat()`; `BEAT RE-ANCHORED`, in 03 and in
  the snapshot's records with `--write`). A beat no sentence carries, or a
  `claims[]` entry whose words are not in its field (the root's
  `shared/factrule/claims.py` reading, the root contract's own), is not
  checked and spends nothing: `TEXT RECORDS OUT OF SYNC`, exit 1, no
  snapshot kept - the gate that owns the record runs again on the text as it
  stands (`check_claims.py --write`, `check_production_fact.py`), then this
  command. Nothing is refused here.
* **The first pass is decided after the frame judge** (CF-0902,
  example-film `2026-10-30T1033Z`). When `01b` carries a substitution at
  `frame_judge_refusal`, this command checks only the scripts of those
  substitute topics; every other script prints `FROZEN` and is neither
  re-planned nor dropped - pine-park's judged video lost its plan.json to a
  re-plan two hours after the render, and the claims judge then stamped a
  failing record onto a script nobody owned any more (`_judge_round.py`).
* **The claims are held to the plan this loop built** (CF-0933, example-tech
  `2026-11-11T0956Z`: nvidia's plan was built and the stage closed twelve
  seconds later; the shot claims, `pending: no_plan` through step 6, were
  never held to it, the reserve round found `shot_not_under_words` and
  compliance blocked the video). After the checks, every script ASSEMBLED
  has its claims run through the root's mechanics against
  `work/<slug>/plan.json` (`claims_on_plan()`): `CLAIMS ON THE PLAN ok`, or
  a shot claim the plan does not put under its words - with `--write`
  `check_claims.py`'s ladder runs for that one script (the record stamped, a
  free fix first), the shots the plan does put there are listed, and the run
  exits 1. The text stays locked: re-bind the claim's shot (claims[] only),
  or an anchor edit that moves the shot under its words, or take the shot
  support out; `--final` refuses the topic as `claim_unsupported`. In the
  reserve round a first-pass script is `NOT OWNED` - said, never written
  (`_judge_round.not_owned()`); the check after the supplement owns what it
  settles.
* **One loss, counted once.** A dropped topic is recorded here, in
  `03 -> skipped[]`, and nowhere else: plan_check.py also left a refusal
  sidecar (`work/<slug>/plan_check.refusal.json`, and `plan.refusal.json`
  beside it) that the Editor's `write_batch_metadata.py` collects from
  `work/*/*.refusal.json` whether or not the script is still in `scripts[]` -
  so a drop moves every `*.refusal.json` of that work directory into
  `work/<slug>/plan_check.rounds/dropped/`, out of that glob's reach. The
  verdict `plan_check.json` stays where it is; the `skipped[]` entry names it.
* **A thin pool waits for its supplement** (CF-0422, the decision of CF-0338:
  a thin pool is answered by more footage, the topic is not given up). This
  step runs inside the writer's stage; the thin-pool supplement step
  (`scripts/thin_pool_supplement.py` at the factory root, CF-0345) runs after
  it. A script that is not built while its topic has an *open* supplement
  request (`_supplement_request.open_request()`: a request file in
  `work/supplement-requests/` or its `consumed/`, and the step's record
  `work/supplement-step.json` has not finished the topic - `done` or
  `skipped`) is not dropped and spends no round: it is `DEFERRED (supplement
  pending)` - `deferred_for_supplement` in its `plan_check_loop.json` and, with
  `--write`, in a `plan_check` block on the script in 03 - and stays in
  `scripts[]`. A later run here does not check it again. After the supplement
  step the orchestrator runs `--after-supplement`: only the deferred scripts,
  on the pool 03 names now (the step's recheck rewrites the script's
  `anchor_coverage_pool.indexes` from 01b's `sources_by_topic`, which the
  indexer's `--supplement` extends; plan_check.py reads it there when no
  `--index` is given, and a changed pool is a new round there, never
  `UNCHANGED`), a first check free and then `plan_check_rounds` anchor-edit
  rounds of their own - and only now is a plan still not built dropped as
  `plan_unassembled`. A refusal no footage can fix (`narration_ceiling`) and
  the text guard drop at once, request or not. `--pending-after-supplement`
  answers, read-only, whether any deferred script still waits for that check.
* **A visual claim the resolve did not picture is a warning** (CF-0412, the
  user's decision of 2026-09-28: a warning only). After every check the
  narrator's lines that point at one picture ("that one-second shot of X in
  the trailer", "you can see ...") are held against this round's real
  resolve (`_visual_claim.py`): an anchor refused as `absent` / `cut_gate` /
  `background` / `typographic`, closed on the topic-footage rung, or pictured
  with something its phrase does not name leaves the line uncovered. The
  claims go to `work/<slug>/visual_claims.json` beside the plan (for the frame
  judge's pack) and, with `--write`, to 03 `warnings[]` as
  `visual_claim_uncovered` / gate `visual_claim_plan` (replaced every check,
  cleared when none is left or the topic is dropped). Nothing else changes:
  no round, no drop, no exit code - and the text stays locked here.
* **An anchor is not a block** (CF-0428, `example-film/2026-09-28T1126Z`:
  vanguards 11 -> 18 anchors, 7 blocks both rounds). A pace under the floor
  carries the Editor's `supply` and `fixable_by_anchors`
  (`build_render_plan.cadence_supply()`). `fixable_by_anchors: false`
  (`pool_too_thin`: the pool's `blocks_max` is under `blocks_needed`) spends
  no round - deferred while a supplement request is open, dropped otherwise
  or after the supplement. The other codes set the hint (`pattern_hint`):
  REPLACE the unfilled phrases, alternate `side`, or ADD onto unused shots;
  every REPLACE / ADD candidate comes from the Editor's
  `storyboard.pool_capacity.unused` (`candidate_shots`), the raw index only
  for a storyboard older than CF-0428.
* **The score decides, the penalty log is the hint** (CF-0433, the grill of
  2026-09-29 "делать из того, что дают"; the model is CF-0432's
  `shared/score`). A pace under the pattern's floor, a block over the hold
  band and a picture under the 0.22 similarity floor no longer refuse a plan:
  they cost points (`score.pace_below_floor`, `score.hold_band_exceeded`,
  `score.low_similarity`), and `pattern_ceiling` refuses only a plan whose
  score fell under N. The loop reads the block - `plan_check.json -> score`
  for a built plan, the refusal's deficit (`pattern_ceiling.score`) for one
  refused on it - and records `score` (points, tier, N, short_by, by_rule) on
  every check and on a `skipped[]` entry. ASSEMBLED prints the score and
  spends nothing on it. A plan under N gets the penalty log as its hint (one
  line per price, one lever per rule), and the decision is the score's and
  `fixable_by_anchors`': a plan short of N by more points than the anchor
  edits can win back (the three rules' charges, less the pace's when the pool
  cannot reach the floor) or carrying a hard-list finding is dropped with no
  round spent (`score_unreachable()`); otherwise it gets its rounds (<= 3,
  CF-0430). CF-0447 (2026-09-30): more blocks than the top of the pattern's
  block band is a price too (`score.block_band_exceeded`, 2 a block, cap 10);
  under it the hint adds the cadence gate's `Axis: ...` sentence for this
  speech (`anchor_cadence.block_band.axis`, CF-0417), and on the `speech` axis
  those points are not counted as the anchors' to win back (the text is
  locked here).
* **Early stop on the score, one line for it** (CF-0434, the same grill, Q11
  / Q17 / Q20 / Q21 / Q28). Only penalties that already happened count - the
  Editor's plan stage priced them on the real voice; nothing here adds a
  forecast. Every check reads the Editor's score log of the round
  (`work/<slug>/plan.score.json`, the Video Editor's `score_log.py`, stage
  `plan`) besides the verdict, so a plan refused under N on the similarity
  floor alone (gate `unresolved_anchor`, no deficit file) is read as a score
  too. Under N with a round left: the penalty log opens with the Editor's
  one-line summary (`[score] F · 58 — −15 похожесть (1 блок), ...`) and the
  round is spent as any other. Under N with no round left (or no anchor edit
  that can lift it): the topic leaves `scripts[]` at **tier F** under the
  score model's loss - `reason_code: score_below_threshold`, `gate:
  score_below_threshold` (the Editor's `plan_refusal.GATE_SCORE` and the funnel
  code it maps to; `held_back` + that gate is the older spelling the root's
  `funnel.code_of()` still reads) - with
  `tier`, `score_line` and the score beside the rounds. A drop for anything
  else (a refusal no anchor fixes, the text guard, a plan with no score under
  N) keeps `plan_unassembled`. A script that goes on carries, with `--write`,
  `score_after_6b` (points, tier, N, short_by, by_rule, the round) and
  `score_line` in 03: the score it left for the Editor with.

Usage::

    python3 scripts/plan_check_loop.py <batch-dir> --write
    python3 scripts/plan_check_loop.py <batch-dir> --write --script-id <id>
    python3 scripts/plan_check_loop.py <batch-dir> --write --after-supplement
    python3 scripts/plan_check_loop.py <batch-dir> --pending-after-supplement [--json]

Exit codes: 0 every script built (or none to check - with
`--after-supplement`, no deferred script waits); 1 at least one script
waits for an anchor edit (or, CF-0933, a claims edit against the plan) (edit, then run the same command again - a rerun
with nothing edited is `UNCHANGED`, spends nothing and exits 1 again - unless
it follows an anchor-edit pass, CF-0793; close with `--final`); 5 at least
one script is deferred for the thin-pool supplement and nothing waits for an
edit (the stage is closed; the check after the supplement is owed); 4 at
least one topic was dropped and nothing waits for an edit or the supplement;
3 plan_check.py could not answer for at least one script (it goes on as
before) and nothing else is pending; 2 bad usage / unreadable batch file.
`--pending-after-supplement`: 0 nothing pending, 1 at least one deferred
script not settled by `--after-supplement` (listed), 2 bad usage.
6 BUSY (CF-0485): another run of this command is checking one of the same
topics right now - this run touched nothing (no voice, no resolve, no clip
deleted, nothing written); wait for that run's verdict, do not start a third.

One run per topic (CF-0485)
---------------------------
Batch `example-film/2026-10-01T2210Z`: the stage's agent started this command
once with a shell `&` and, 7 s later, once more as a background command; both
ran `resolve_anchors.py` in `work/spire-runner-fresh-dawn`, the second cut and
deleted the clips the first one's `build_render_plan` was reading, and the
first plan died on a missing clip. So every topic this run will check is
locked first - `work/<slug>/.plan_check_loop.lock`, an exclusive
`fcntl.flock` held for the whole run, the holder's pid / start / argv written
inside for the message. The kernel drops a flock when its process dies, so a
crashed or killed run leaves no lock behind - only a file with a dead pid,
which the next run simply takes over. All the topics are taken before the
first check, or none: a run that finds one held releases what it took, prints
`BUSY` with the holder, and exits 6.

A topic too thin for a script (CF-0845)
---------------------------------------
The plain `--write` pass (the stage's step 6b, in the first call and in the
reserve call alike; never `--after-supplement`) first runs the root's
`shared/runlog/thin_topic.py` `write()` on the batch: every script of a topic
whose `01b pool_depth.topics[].usable_shots` is under the channel's
`content_researcher.min_usable_shots_for_script` leaves `scripts[]` for
`skipped[]` as `pool_too_thin` (`gate: min_usable_shots`) and is never checked
- one `THIN POOL:` line each, and the run exits 4 when nothing else is
pending. A root without the module prints a WARN and the loop runs as before.
CF-0850: the same root pass also records a thin topic the stage was handed
and never wrote (step 2's `--check` listed it) - in `skipped[]` as
`pool_too_thin` without a `script_id` - so the pass is run even when the call
wrote no script; before, such a topic left 03 with no record at all
(example-tech/2026-10-22T0833Z, `-017`).
"""
import argparse
import contextlib
import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import merge_batch_file as mbf  # noqa: E402
import _supplement_request as supreq  # noqa: E402
import _gate_warning as gw  # noqa: E402
import _visual_claim as vc  # noqa: E402 - CF-0412
import _rewrite_guard as rg  # noqa: E402 - CF-0430: the one UNCHANGED word
import _score  # noqa: E402 - CF-0433/CF-0434: the score model's door
import check_production_fact as cpf  # noqa: E402 - CF-0547: the early fact anchor's price
from _runlog import runlog, factory_root  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
import _judge_round as jr  # noqa: E402 - CF-0902: the first pass is decided after the judge

BATCH_FILE = "03-content-researcher.json"
VERDICT = "plan_check.json"
STATE = "plan_check_loop.json"
ROUNDS_DIR = "plan_check.rounds"
DROPPED_DIR = "dropped"
REFUSAL_SUFFIX = ".refusal.json"  # plan_refusal.SUFFIX, the glob the Editor collects

EDITOR_REL = Path("agents") / "video-editor"
PLAN_CHECK_REL = Path("scripts") / "plan_check.py"
EDITOR_PY_REL = Path(".venv") / "bin" / "python3"

CONFIG_BLOCK = "content_researcher"
ROUNDS_KEY = "plan_check_rounds"
# CF-0430 (the user's decision of 28.09 on 1126Z: 2 rounds did not pull
# Primetime/Vanguards/Day Drinker/Kaijura through): 3 when the channel does
# not say. The channel's own key wins; the root sets example-film's to 3 too.
DEFAULT_ROUNDS = 3
DEFAULT_TIMEOUT_SECONDS = 3600

REASON_CODE = "plan_unassembled"
# CF-0434: a plan under N that no round is left to lift leaves under the score
# model's loss - the Video Editor's `plan_refusal.GATE_SCORE` and the funnel
# code that gate maps to (`plan_refusal.code_for(GATE_SCORE)`), so the same
# fact reads the same at 6b and after the render. Mirrored, not imported: the
# Editor's scripts/ cannot share a sys.path with this repo's `_score`. The code
# is the funnel's own `score_below_threshold` (`shared/runlog/funnel.py`
# SCORE_BELOW_THRESHOLD); the first writes of CF-0434 used `held_back` with this
# gate, and `funnel.code_of()` reads that pair as the same loss.
SCORE_GATE = "score_below_threshold"
SCORE_REASON_CODE = "score_below_threshold"
SCORE_TIER_LOST = "F"
# the Editor's score log of the video (score_log.py, `<plan stem>.score.json`)
SCORE_LOG = "plan.score.json"
# what a script that goes on carries in 03
SCRIPT_SCORE_FIELD = "score_after_6b"
SCRIPT_LINE_FIELD = "score_line"   # the field name 05 uses for the same line
SCORE_STAGE = "6b"
FUNNEL_STAGE = "scripts"
TEXT_FIELDS = ("hook", "commentary", "payoff")
# CF-0852: the records step 6 writes *on* that text - the fact's beat and the
# claims quote it verbatim, the graphics are text the viewer reads (claims are
# keyed on them), the gates' verdicts are stamped on it. They are snapshotted
# with the text and rolled back with it: a rollback of the text alone left
# example-tech 2026-10-23T0831Z iphone-duo with a commentary that said "Both
# screens share..." under a beat_text and a claim that said "Duo screens
# share..." - the root contract (beat_text / claims verbatim in their field)
# red, and a video whose fact pointed at no words.
TEXT_RECORDS = ("production_fact", "fact", "claims", "claims_check", "story_claims",
                "story_claims_check", "graphics", "hook_opener_id", "sourcing_caveat",
                "number_density", "narration", "estimated_spoken_duration_seconds")
TEXT_RECORDS_STATE_KEY = "text_records"

# plan_check.py's exit codes (its own module docstring)
PC_ASSEMBLED, PC_ENVIRONMENT, PC_REFUSED = 0, 1, 2

EXIT_OK, EXIT_EDIT, EXIT_BAD_USAGE, EXIT_CANNOT_ANSWER, EXIT_DROPPED = 0, 1, 2, 3, 4
# CF-0422: at least one script was not built but waits for the thin-pool
# supplement instead of being dropped, and nothing waits for an anchor edit.
EXIT_DEFERRED = 5
# CF-0485: another run holds one of this run's topics; nothing was touched.
EXIT_BUSY = 6
LOCK = ".plan_check_loop.lock"

# CF-0422: a topic with an open thin-pool supplement request is not dropped on
# the pool it has now - it is deferred until the supplement step has run.
DEFERRED = "deferred_for_supplement"
SCRIPT_FIELD = "plan_check"   # the block on the script in 03 that says so
DEFERRED_TASK = "CF-0422"

# CF-0793: the run that follows an anchor-edit pass (the run plan's rerun after
# its `plan-check-anchor-edit` handler sets this variable; `--edit-pass` says
# the same). UNCHANGED on such a run, with no check made since the last run
# that handed the script to the pass, means the pass edited nothing - that
# pass is a spent round, or the stage spins until its reruns run out.
EDIT_PASS_ENV = "PLAN_CHECK_EDIT_PASS"
# where the leg records how many checks it had when it last handed the script
# to an anchor-edit pass (the first check of the leg, or an --edit-pass run)
EDIT_PASS_MARK = "edit_pass_from_check"
EDIT_PASS_SPENT = "unchanged_edit_pass"

# A refusal of these kinds is not the anchors' to fix: the voice is too long
# for the channel, and the text may not change here.
UNFIXABLE_BY_ANCHORS = ("narration_ceiling",)

STOPWORDS = set("""a an the of in on at to and or with for from by over under into onto as is
are was were be it its this that these those his her their our your one two out up down
off near behind front side shot close closeup close-up wide view looking look some very""".split())


# --------------------------------------------------------------------------
# small helpers

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def write_json(path, doc):
    mbf.write_atomically(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def slugify(name):
    """plan_check.py's own slug rule - the work directory both sides use."""
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s or None


def slug_of(script):
    return slugify(((script or {}).get("title_ref") or {}).get("name")) or \
        slugify((script or {}).get("script_id"))


def narration_text(script):
    """The text plan_check.py synthesizes: the three spoken sections on one line."""
    return " ".join(script.get(k) for k in TEXT_FIELDS if script.get(k))


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_snapshot(script):
    return {k: script.get(k) for k in TEXT_FIELDS}


def text_records(script):
    """CF-0852: the records written on the text, as they stand - only the
    keys the script has (a key absent here is taken off on rollback)."""
    return {k: copy.deepcopy(script[k]) for k in TEXT_RECORDS if k in script}


# --------------------------------------------------------------------------
# CF-0860: the records written on the text quote the text as it stands

CLAIMS_RULE_REL = Path("shared") / "factrule" / "claims.py"
SYNC_TASK = "CF-0860"
_CLAIMS_RULE = []


def load_claims_rule(root=None):
    """The root's `shared/factrule/claims.py` (its `norm`, `viewer_texts`) -
    the very reading of "verbatim" the root contract holds `claims[]` to - or
    None when this checkout has no root with it (the claims are then not
    held here, and the run says so)."""
    if root is None and _CLAIMS_RULE:
        return _CLAIMS_RULE[0]
    mod = None
    try:
        path = Path(root or factory_root()) / CLAIMS_RULE_REL
        if path.is_file():
            spec = importlib.util.spec_from_file_location("_plan_check_loop_claims", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - a root we cannot read holds nothing here
        mod = None
    if root is None:
        _CLAIMS_RULE.append(mod)
    return mod


def claims_out_of_sync(script, cl):
    """`claims[]` entries whose words are not in the field they name, as the
    root contract reads it (test_pipeline_contracts.check_claims_shape)."""
    claims = script.get("claims")
    if cl is None or not isinstance(claims, list):
        return []
    texts = cl.viewer_texts(script)
    out = []
    for i, c in enumerate(claims):
        if not isinstance(c, dict) or c.get("where") in cl.GIVEN_BY_CALLER:
            continue
        where, text = c.get("where"), c.get("text")
        if not isinstance(text, str):
            continue
        if where not in texts:
            out.append(f"claims[{i}] ({c.get('claim_id')}): names `{where}`, which the script "
                       f"does not have")
        elif cl.norm(text).strip(cl._EDGE_PUNCT) not in cl.norm(texts[where]):
            out.append(f"claims[{i}] ({c.get('claim_id')}, {where}): {text!r} is not in the "
                       f"{where}")
    return out


def records_in_sync(batch_file, sid, slug, script, state, write, out, claims_rule=None):
    """CF-0860, example-film 2026-10-24T0840Z: step 6's later gates rewrote the
    fact's sentence in the commentary after check_production_fact.py had
    passed, `claims[]` with it and `production_fact.beat_text` not; 6b took
    the snapshot as it stood, the Editor found no beat (wildwood went out
    with no fact line) and the root contract went red. Before anything is
    paid for:

    * a beat that is not in the commentary is re-anchored to the
      commentary's words the fact is spoken in now
      (`check_production_fact.reanchor_beat`) - with `--write` in 03 and in
      the snapshot's records, so a later rollback restores the repaired beat;
    * a beat no sentence carries, or a claim whose words are not in its
      field, is not repairable here: the script is not checked and nothing
      is spent (`TEXT RECORDS OUT OF SYNC`, exit 1) - the gate that owns it
      runs again on the text as it stands, then this command.

    Returns the script (as re-read after a repair), or None when the script
    must not be checked."""
    problems = []
    fact = script.get(cpf.FIELD)
    commentary = script.get(cpf.COMMENTARY_KEY)
    old = fact.get("beat_text") if isinstance(fact, dict) else None
    if isinstance(old, str) and old.strip() and isinstance(commentary, str) \
            and old not in commentary:
        new, how = cpf.reanchor_beat(fact, commentary)
        if new is None:
            problems.append(f"{cpf.FIELD}.beat_text {old!r} is not in the commentary and it "
                            f"cannot be re-anchored ({how}) - write beat_text as the "
                            f"commentary's words the fact is spoken in, rerun "
                            f"check_production_fact.py")
        elif write:
            doc = load_batch(batch_file)
            current = script_by_id(doc, sid)
            current[cpf.FIELD]["beat_text"] = new
            mbf.write_atomically(batch_file, mbf.dump(doc))
            records = state.get(TEXT_RECORDS_STATE_KEY)
            if isinstance(records, dict) and cpf.FIELD in records:
                records[cpf.FIELD] = copy.deepcopy(current[cpf.FIELD])
            script = current
            out(f"  BEAT RE-ANCHORED {sid} ({slug}): {cpf.FIELD}.beat_text {old!r} was not in "
                f"the commentary (the text was rewritten after check_production_fact.py) - "
                f"now {new!r}, the words the fact is spoken in ({how}; {SYNC_TASK})")
        else:
            out(f"  BEAT OUT OF SYNC {sid} ({slug}): {cpf.FIELD}.beat_text {old!r} is not in the "
                f"commentary - --write re-anchors it to {new!r} ({how}; {SYNC_TASK})")
    cl = claims_rule if claims_rule is not None else load_claims_rule()
    if cl is None:
        out(f"  WARN {sid} ({slug}): the root's {CLAIMS_RULE_REL} is not on this disk - "
            f"claims[] not held to the text here ({SYNC_TASK})")
    problems += claims_out_of_sync(script, cl)
    if not problems:
        return script
    out(f"  TEXT RECORDS OUT OF SYNC {sid} ({slug}): not checked, nothing spent - the records "
        f"step 6 wrote on the text quote words the narrator does not say ({SYNC_TASK}):")
    for p in problems:
        out(f"    - {p}")
    out(f"    The text was edited after the gate that wrote them. Run that gate again on the "
        f"text as it stands - check_claims.py --write for claims[], check_production_fact.py "
        f"for the beat (fix the field it names) - then this command. A Video Editor plan on "
        f"such a script puts the fact line and the claims on nothing.")
    return None


# --------------------------------------------------------------------------
# CF-0933: the claims against the plan this loop built
#
# Batch `example-tech/2026-11-11T0956Z` (nvidia, `lf-2026-11-11-002-script1`):
# a shot claim (Q8, `{"shot_id": ...}`) is `pending: no_plan` through step 6 -
# no block exists before 6b. This loop built nvidia's plan (11:22:48Z) and the
# stage closed twelve seconds later; nobody held the claims to that plan. The
# reserve round's `check_claims.py --write` then found `shot_not_under_words`
# (c7, c9, c10) on a script it did not own, compliance's claims gate (which
# judges 03 against the plan itself) blocked it, and the topic was lost though
# the writer could have re-bound the shot. So the loop checks it, after the
# plans are built: for every script it ASSEMBLED, the root's mechanics
# (`shared/factrule/claims.py`) against `work/<slug>/plan.json`. A shot claim
# the plan does not put under its words goes to `check_claims.py`'s ladder for
# that script (`--write`: the record is stamped, a free fix first) and the run
# exits 1 - the stage does not close on a record that fails against the plan
# it leaves with. `--final` (no edit left) refuses it as `claim_unsupported`.
CLAIMS_TASK = "CF-0933"
CLAIMS_STATE_KEY = "claims_on_plan"
# claims.FAIL_SHOT_NOT_UNDER_WORDS / claims.FAIL_SHOT_UNLOCATED: the verdicts
# only a plan gives (before it the shot claim is `pending: no_plan`).
PLAN_CLAIM_CODES = ("shot_not_under_words", "shot_placement_unknown")
CLAIM_CANDIDATES = 4


def _claims_judge(root):
    """(check_claims module, the root's claim judge) or raises its
    CannotAnswer - loaded only when a built plan is there to hold claims to."""
    import check_claims as cc   # noqa: PLC0415 - the writer's ladder, this repo's
    return cc, cc.load_judge(root)


def plan_claim_fails(violations):
    return [v for v in violations or [] if isinstance(v, dict)
            and v.get("code") in PLAN_CLAIM_CODES]


def recorded_plan_fails(script, record_key="claims_check"):
    """The plan-only failures the script's record still carries (a record
    stamped on an earlier plan, or on an earlier binding)."""
    rec = script.get(record_key)
    if not isinstance(rec, dict) or rec.get("action") != "fail":
        return []
    return plan_claim_fails((rec.get("mechanics") or {}).get("violations"))


def fail_names(violations):
    return ", ".join(f"{v.get('code')} {v.get('claim_id')}" if v.get("claim_id")
                     else str(v.get("code")) for v in violations)


def claim_candidates(report, violation, pool):
    """The shots the plan does put under the failing claim's words - what the
    claim can be re-bound to, with the Indexer's description."""
    out = []
    for r in (report or {}).get("results") or []:
        if r.get("claim_id") != violation.get("claim_id"):
            continue
        for sup in r.get("supports") or []:
            if sup.get("kind") != "shot":
                continue
            for b in sup.get("blocks") or []:
                for shot in b.get("shots") or []:
                    if shot != sup.get("shot_id") and shot not in [c[0] for c in out]:
                        out.append((shot, (pool or {}).get(shot)))
    return out[:CLAIM_CANDIDATES]


def ladder_lines(script, report, fails, pool):
    """What the writer may do about a shot claim the plan does not picture -
    the text stays locked in this loop."""
    out = []
    for v in fails:
        claim = next((c for c in script.get("claims") or []
                      if isinstance(c, dict) and c.get("claim_id") == v.get("claim_id")), {})
        out.append(f"    - {v.get('code')} {v.get('claim_id')} ({claim.get('where')}): "
                   f"{claim.get('text')!r} - {v.get('detail') or 'the shot is not under these words'}")
        for shot, desc in claim_candidates(report, v, pool):
            out.append(f"        under these words now: {shot}"
                       + (f" - {desc!r}" if desc else ""))
    out.append("    The text stays as step 6 cleared it. In this order: (1) RE-BIND the shot - "
               "set the claim's `support` shot_id to a shot the plan puts under its words "
               "(listed above) whose description shows what the words say; (2) or put that "
               "shot under the words with an anchor edit (`visual_anchors` - its phrase on "
               "those words, a new plan round); (3) or take the shot support out of the claim "
               "when a quote still carries it. Then run this command again (a free fix first, "
               "then the claims' one-edit ladder, CF-0807). No edit left: --final refuses the "
               f"topic as `claim_unsupported` ({CLAIMS_TASK}).")
    return out


def _sync_snapshot_records(work, script):
    """The rollback snapshot keeps `claims[]` and `claims_check` as they stand
    after the check: a later rollback must not bring back a binding (or a
    no_plan record) this check has already ruled on. Only while the text is
    the snapshot's - a changed text is the rollback's business."""
    state_path = work / STATE
    state = read_json(state_path)
    if not isinstance(state, dict):
        return None
    records = state.get(TEXT_RECORDS_STATE_KEY)
    if isinstance(records, dict) and state.get("text_snapshot") == text_snapshot(script):
        for key in ("claims", "claims_check"):
            if key in script:
                records[key] = copy.deepcopy(script[key])
    return state


def _note_claims(batch, script, outcome, fails):
    work = batch / "work" / slug_of(script)
    state = _sync_snapshot_records(work, script)
    if state is None:
        return
    state[CLAIMS_STATE_KEY] = {"task": CLAIMS_TASK, "outcome": outcome,
                               "codes": [fail_names([v]) for v in fails],
                               "at": now()}
    write_json(work / STATE, state)


def refuse_on_plan(batch_file, sid, cc, fails, out):
    """`--final` with a shot claim still not under its words: the topic leaves
    `scripts[]` for `skipped[]` as `claim_unsupported` (the record beside it)."""
    doc = load_batch(batch_file)
    script = script_by_id(doc, sid)
    if script is None:
        return False
    record = script.get(cc.RECORD_KEY) if isinstance(script.get(cc.RECORD_KEY), dict) else {}
    entry = cc.skip_entry(script, record)
    entry["reason"] = (f"{sid}: a shot claim is not under its words in the plan step 6b built "
                       f"({fail_names(fails)}) and the writer had no edit left (--final) - a "
                       f"claim the picture does not show is not voiced ({CLAIMS_TASK})")
    doc["scripts"] = [s for s in doc.get("scripts") or [] if s.get("script_id") != sid]
    doc.setdefault("skipped", []).append(entry)
    mbf.write_atomically(batch_file, mbf.dump(doc))
    out(f"  REFUSED {sid}: `{cc.SKIP_REASON_CODE}` - {fail_names(fails)} still not under their "
        f"words and --final: no edit left; moved to skipped[] ({CLAIMS_TASK})")
    return True


def claims_on_plan(args, batch, batch_file, sids, out=print, root=None):
    """CF-0933: hold the claims of the scripts this run ASSEMBLED to the plan
    it built. Returns {script_id: outcome}: `ok`, `edit` (the run exits 1),
    `refused` (moved to skipped[]), `not_owned` (the reserve round's, said and
    not written), `environment` (the judge could not be asked), `no_plan`."""
    if not sids:
        return {}
    root = Path(root) if root else _root_or_none()
    doc = load_batch(batch_file)
    current = [s for s in doc.get("scripts") or [] if s.get("script_id") in sids]
    if not current:
        return {}
    try:
        cc, judge = _claims_judge(root)
    except Exception as exc:  # noqa: BLE001 - CannotAnswer, or no root on this disk
        out(f"  WARN claims not held to the plan: {exc} ({CLAIMS_TASK})")
        return {}
    cl = judge.claims
    # the check after the supplement settles a first-pass script 6b deferred:
    # it is that pass's own business, whatever round is on now
    unowned = {} if getattr(args, "after_supplement", False) else jr.not_owned(batch, current)
    topics = cl.topics_of(batch)
    results = {}
    for script in current:
        sid, slug = script.get("script_id"), slug_of(script)
        plan = cl.plan_of(script, batch)
        if plan is None:
            out(f"  CLAIMS ON THE PLAN {sid} ({slug}): no plan.json under work/ names it - the "
                f"shot claims stay pending ({CLAIMS_TASK})")
            results[sid] = "no_plan"
            continue
        pool = cl.pool_of(script, batch, root) if root else cl.pool_of(script, batch)
        report = cl.check_claims(script, topic=topics.get(script.get("topic_id")),
                                 pool=pool, plan=plan)
        fails = plan_claim_fails(report.get("violations"))
        stale = recorded_plan_fails(script, cc.RECORD_KEY)
        if sid in unowned:
            out(f"  NOT OWNED {sid} ({slug}) "
                + (f"(fails: {fail_names(fails)})" if fails else "(the claims hold on the plan)")
                + f": {unowned[sid]} - nothing written")
            results[sid] = "not_owned"
            continue
        shots = sum(1 for r in report.get("results") or [] for sup in r.get("supports") or []
                    if sup.get("kind") == "shot")
        if not fails and not stale:
            out(f"  CLAIMS ON THE PLAN ok {sid} ({slug}): {shots} shot claim(s), each under "
                f"its words in the plan ({CLAIMS_TASK})")
            results[sid] = "ok"
            if args.write:
                _note_claims(batch, script, "ok", [])
            continue
        if fails:
            out(f"  CLAIMS ON THE PLAN {sid} ({slug}): {len(fails)} shot claim(s) the plan does "
                f"not put under their words - {fail_names(fails)} ({CLAIMS_TASK})")
        else:
            out(f"  CLAIMS ON THE PLAN {sid} ({slug}): the record still says "
                f"{fail_names(stale)}, the plan now holds them - the record is judged again")
        if not args.write:
            out(f"    not recorded: run with --write (check_claims.py --write --script-id {sid})")
            results[sid] = "edit" if fails else "ok"
            continue
        if not fails:
            rec = script.get(cc.RECORD_KEY)
            if isinstance(rec, dict) and rec.get(cc.PREJUDGE_KEY) and not [
                    v for v in (rec.get("mechanics") or {}).get("violations") or []
                    if v.get("code") not in PLAN_CLAIM_CODES] and not rec.get("violations"):
                # the record failed on the plan alone and the plan changed under the
                # same words: not the rerun the UNCHANGED guard is for
                fresh = load_batch(batch_file)
                cur = script_by_id(fresh, sid)
                cur[cc.RECORD_KEY].pop(rg.HASH_KEY, None)
                mbf.write_atomically(batch_file, mbf.dump(fresh))
        lines = []
        try:
            _, records, refused = cc.check_batch(batch_file, root=root, write=True,
                                                 out=lines.append, judge=judge,
                                                 script_ids={sid}, own={sid})
        except cc.CannotAnswer as exc:
            out(f"    CANNOT ANSWER: check_claims.py could not put the question ({exc}) - "
                f"the record is not settled; run check_claims.py --write --script-id {sid} "
                f"once the judge answers ({CLAIMS_TASK})")
            results[sid] = "environment"
            continue
        for line in lines[1:]:
            out(f"    | {line.strip()}")
        current_doc = load_batch(batch_file)
        now_script = script_by_id(current_doc, sid)
        if refused or now_script is None:
            out(f"  REFUSED {sid}: `{cc.SKIP_REASON_CODE}` - the claims' ladder is spent "
                f"({fail_names(fails or stale)}); moved to skipped[] ({CLAIMS_TASK})")
            results[sid] = "refused"
            continue
        if (records.get(sid) or {}).get("action") == "pass":
            out(f"  CLAIMS ON THE PLAN ok {sid} ({slug}): judged again, the record passes")
            results[sid] = "ok"
            _note_claims(batch, now_script, "ok", [])
            continue
        left = recorded_plan_fails(now_script, cc.RECORD_KEY)
        others = [c for c in cc.codes_of(now_script.get(cc.RECORD_KEY) or {})
                  if c not in PLAN_CLAIM_CODES]
        if args.final:
            results[sid] = "refused" if refuse_on_plan(
                batch_file, sid, cc, left or [{"code": c} for c in others], out) else "edit"
            continue
        if left:
            for line in ladder_lines(now_script, report, left, pool):
                out(line)
        if others:
            out(f"    The record also fails on {', '.join(others)} (the lines above): fix what "
                f"they name in claims[] - the text stays locked in this loop - then run this "
                f"command again; --final refuses the topic as `claim_unsupported`.")
        results[sid] = "edit"
        _note_claims(batch, now_script, "edit", left + [{"code": c} for c in others])
    return results


# --------------------------------------------------------------------------
# the channel's ceiling

def rounds_allowed(channel, root=None, config_path=None):
    """(rounds, source). The channel's `content_researcher.plan_check_rounds`,
    else DEFAULT_ROUNDS - a channel config that predates the key, or a test
    root with no config at all, runs the default."""
    path = Path(config_path) if config_path else None
    if path is None and channel:
        try:
            import _channel_ids
            path = _channel_ids.channel_config_path(channel, root=root)
        except Exception:  # noqa: BLE001 - the default is the answer
            base = Path(root) if root else _root_or_none()
            path = base / "channels" / f"{channel}.json" if base else None
    cfg = read_json(path) if path else None
    block = (cfg or {}).get(CONFIG_BLOCK) if isinstance(cfg, dict) else None
    value = block.get(ROUNDS_KEY) if isinstance(block, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value, f"{path}#{CONFIG_BLOCK}.{ROUNDS_KEY}"
    return DEFAULT_ROUNDS, f"default {DEFAULT_ROUNDS} (no {CONFIG_BLOCK}.{ROUNDS_KEY} in {path})"


def _root_or_none():
    try:
        return factory_root()
    except RuntimeError:
        return None


def editor_paths(root=None, plan_check=None, editor_python=None):
    base = Path(root) if root else _root_or_none()
    editor = base / EDITOR_REL if base else None
    pc = Path(plan_check) if plan_check else (editor / PLAN_CHECK_REL if editor else None)
    py = Path(editor_python) if editor_python else (editor / EDITOR_PY_REL if editor else None)
    return pc, py


# --------------------------------------------------------------------------
# hints: what to change in `visual_anchors`, per refusal kind

def _words(text):
    return {w for w in re.findall(r"[a-z]{3,}", str(text or "").lower()) if w not in STOPWORDS}


def pool_shots(indexes):
    """(label, description, seconds, words) of every shot the pool offers a
    picture from: no title cards, no burned text, nothing off topic."""
    out = []
    for ix in indexes or []:
        doc = read_json(ix)
        if not isinstance(doc, dict):
            continue
        vid = Path(str(ix)).name.split(".shots.json")[0]
        for s in doc.get("shots") or []:
            desc = (s.get("description") or "").strip()
            if not desc or s.get("is_card") or s.get("burned_text") or s.get("on_topic") is False:
                continue
            secs = round(float(s.get("end") or 0) - float(s.get("start") or 0), 1)
            out.append((f"{vid}#{s.get('index')}", desc, secs, _words(desc)))
    return out


CAPACITY_SOURCE = "pool_capacity"   # the Editor's own list of free usable shots
INDEX_SOURCE = "index"              # the raw shot indexes (a storyboard before CF-0428)


def capacity_shots(verdict, work):
    """CF-0428: the shots an anchor edit can still land on, as the Editor
    measured them this round - `storyboard.pool_capacity.unused` (every shot
    past the gates no phrase moves - burned text, cached usability, retired,
    the cut clip - and not already on screen), else the `supply.unused_shots`
    a pace-floor refusal names. Same tuples as `pool_shots()`, cards left
    out. None when neither is there (a storyboard older than CF-0428): the
    caller falls back to the raw index, which also offers shots the Editor
    will refuse or has already used."""
    story = read_json(Path(work) / "storyboard.json") if work else None
    cap = (story or {}).get("pool_capacity") if isinstance(story, dict) else None
    entries = cap.get("unused") if isinstance(cap, dict) else None
    if not isinstance(entries, list):
        entries = next(((r.get("supply") or {}).get("unused_shots")
                        for r in (verdict or {}).get("refusals") or []
                        if isinstance((r.get("supply") or {}).get("unused_shots"), list)), None)
    if not isinstance(entries, list):
        return None
    out = []
    for u in entries:
        desc = " ".join(str(u.get("description") or "").split())
        if not desc or u.get("is_card"):
            continue
        out.append((str(u.get("shot")), desc, u.get("seconds"), _words(desc)))
    return out


def candidate_shots(verdict, work, script):
    """(shots, source): the Editor's free usable shots when it measured them,
    else every described shot of the pool's indexes (the old source)."""
    cap = capacity_shots(verdict, work)
    if cap is not None:
        return cap, CAPACITY_SOURCE
    return pool_shots((verdict or {}).get("indexes") or pool_of(script)), INDEX_SOURCE


def candidates_for(phrase, shots, top=5):
    want = _words(phrase)
    ranked = sorted(shots, key=lambda s: (-len(want & s[3]), -(s[2] or 0)))
    return ranked[:top]


def voice_seconds(verdict):
    words = read_json(((verdict.get("artifacts") or {}).get("words") or {}).get("path") or "")
    if isinstance(words, list) and words:
        try:
            return float(words[-1].get("end"))
        except (TypeError, ValueError, AttributeError):
            return None
    return None


# CF-0428: build_render_plan.cadence_supply()'s codes - why a pace is under
# its floor, and so what (if anything) an anchor edit can do about it
SUPPLY_POOL_TOO_THIN = "pool_too_thin"
SUPPLY_ANCHORS_UNFILLED = "anchors_unfilled"
SUPPLY_SIDE_RUNS = "same_side_runs"
SUPPLY_TOO_FEW_ANCHORS = "too_few_anchors"
SUPPLY_UNMEASURED = "unmeasured"
# the codes whose remedy is a new picture for an anchor: the unused shots follow
SUPPLY_WANTS_SHOTS = (SUPPLY_ANCHORS_UNFILLED, SUPPLY_TOO_FEW_ANCHORS)
SUPPLY_SHOTS_LISTED = 8


def supply_hint(r):
    """CF-0428: the pace-floor hint in the numbers of the Editor's `supply`,
    or None when the refusal carries none (a verdict older than CF-0428, or
    `unmeasured`) - the caller then falls back to the count arithmetic.

    The old hint said "ADD ~N anchors ... every anchor is at least one block"
    of every pace under the floor; `example-film/2026-09-28T1126Z` showed it
    false both ways: vanguards went 11 -> 18 anchors and stayed at 7 blocks
    (the pool had 8 usable shots, 16 phrases found no free one), backrooms
    had 11 anchors in 6 same-side runs on `alternate` (a block is a side
    change)."""
    sp = r.get("supply")
    if not isinstance(sp, dict) or sp.get("code") in (None, SUPPLY_UNMEASURED):
        return None
    code = sp["code"]
    cap = sp.get("pool_capacity") or {}
    n, need, span = sp.get("blocks"), sp.get("blocks_needed"), sp.get("span_seconds")
    head = (f"{r.get('measured')} blocks/min: {n} block(s) over {span} s, the floor "
            f"{r.get('band_min')}/min wants at least {need}")
    if code == SUPPLY_POOL_TOO_THIN:
        return [f"{head}; the pool can put at most {cap.get('blocks_max')} on screen "
                f"({cap.get('eligible')} of its {cap.get('shots')} shots pass every gate a "
                f"phrase cannot move, {cap.get('used')} already on screen), i.e. "
                f"{sp.get('max_rate_per_minute')} blocks/min at best - NOT FIXABLE BY "
                f"ANCHORS: an anchor no free shot answers adds no block. Widen the pool or "
                f"assign another pattern"]
    if code == SUPPLY_ANCHORS_UNFILLED:
        unfilled = sp.get("anchors_without_block") or []
        return [f"{head}; {len(unfilled)} anchor(s) left no block - no free shot answered the "
                f"phrase, and an anchor that resolves to nothing adds nothing to the pace. "
                f"REPLACE these phrases with shots from the unused list below (keep beat_text "
                f"on the same words): " + "; ".join(f"«{p}»" for p in unfilled)]
    if code == SUPPLY_SIDE_RUNS:
        runs = sp.get("side_runs")
        return [f"{head}; on `alternate` a block is a side change: {sp.get('anchor_count')} "
                f"anchor(s) in {runs} same-side run(s) are {runs} block(s), and an anchor added "
                f"on its neighbour's side adds none. ALTERNATE the anchors' `side` so the "
                f"same-side runs number at least {need} (the anchor count is not the lever)"]
    if code == SUPPLY_TOO_FEW_ANCHORS:
        more = max(1, (need or 0) - (n or 0))
        return [f"{head}; every anchor filled a block and the pool has "
                f"{cap.get('unused_total')} usable shot(s) not yet on screen (up to "
                f"{cap.get('blocks_max')} blocks) - ADD about {more} anchor(s), each onto a "
                f"shot from the unused list below (an anchor on a shot already on screen adds "
                f"no block)"]
    return None


def pattern_hint(r, verdict, script):
    param, measured = r.get("parameter"), r.get("measured")
    lo, hi = r.get("band_min"), r.get("band_max")
    band = f"{lo}..{hi}"
    if not isinstance(measured, (int, float)):
        return [f"the plan is outside the pattern's band ({band}): {r.get('reason')}"]
    blocks = r.get("blocks") or []
    tail = f" (blocks named: {blocks})" if blocks else ""
    by_supply = supply_hint(r)
    if by_supply:
        return [line + tail for line in by_supply]
    if param == "block_rate_per_minute":
        secs = voice_seconds(verdict) or \
            ((script.get("narration") or {}).get("estimated_seconds"))
        if isinstance(secs, (int, float)) and secs > 0:
            now_blocks = measured * secs / 60.0
            if isinstance(lo, (int, float)) and measured < lo:
                need = math.ceil(lo * secs / 60.0 - now_blocks)
                return [f"{measured} blocks/min over {secs:.1f} s of voice is ~{now_blocks:.0f} "
                        f"block(s); the floor {lo}/min wants at least {math.ceil(lo * secs / 60.0)}"
                        f" - ADD about {need} anchor(s): give separate moments of the narration "
                        f"their own anchor on a distinct shot not yet on screen, and split an "
                        f"anchor whose beat_text runs over several sentences into one per "
                        f"sentence{tail}"
                        + ("" if not (r.get("supply") or {}).get("code") else
                           " (whether the pool can reach the floor is unmeasured: the "
                           "storyboard carries no pool_capacity)")]
            if isinstance(hi, (int, float)) and measured > hi:
                drop = math.ceil(now_blocks - hi * secs / 60.0)
                return [f"{measured} blocks/min over {secs:.1f} s of voice is ~{now_blocks:.0f} "
                        f"block(s); the ceiling {hi}/min allows {math.floor(hi * secs / 60.0)} - "
                        f"REMOVE about {drop} anchor(s): merge neighbouring beats into one "
                        f"anchor with a longer beat_text{tail}"]
    if param in ("block_count",) and isinstance(lo, (int, float)) and measured < lo:
        return [f"{measured} block(s) against {band}: ADD {math.ceil(lo - measured)} anchor(s){tail}"]
    if param in ("block_count",) and isinstance(hi, (int, float)) and measured > hi:
        return [f"{measured} block(s) against {band}: REMOVE {math.ceil(measured - hi)} "
                f"anchor(s){tail}"]
    return [f"{param} measured {measured} against {band} ({r.get('cause')}): the anchors' "
            f"count and spacing are the lever{tail}"]


# CF-0433: the score model (shared/score, CF-0432) - what each price of the
# plan's log asks of the anchors, the only thing this loop may change.
SCORE_LEVERS = {
    "score.pace_below_floor": (
        "the pace is under the pattern's floor - more blocks: see the pattern_ceiling "
        "line above for whether anchors can add them (supply / fixable_by_anchors)"),
    "score.hold_band_exceeded": (
        "a block is held over the hold band's top - give its words one more anchor on a "
        "distinct shot, or move the anchor that ends it earlier"),
    "score.low_similarity": (
        "the picture scored under the 0.22 similarity floor - REPLACE the phrase of that "
        "anchor with a shot the pool has (keep beat_text on the same words)"),
    # CF-0447: the block band's top is a price, not a refusal (2026-09-30).
    "score.block_band_exceeded": (
        "the plan is cut into more blocks than the top of the pattern's block band - the "
        "cadence gate's Axis line (anchors / cut / speech) says which lever moves it; on "
        "the speech axis no anchor edit does, and the text is locked here"),
}

# CF-0447: the rule whose lever the cadence gate (check_anchor_cadence.py, 6b)
# already worked out on this very speech - `anchor_cadence.block_band.axis`
# (CF-0417's `Axis: ...` sentence) and `.cause`.
RULE_BLOCK_BAND = "score.block_band_exceeded"
CADENCE_KEY = "anchor_cadence"
CAUSE_SPEECH = "speech"


def cadence_axis(script):
    """`(axis sentence, cause)` the cadence gate wrote on this script for a
    layout over the block band's top, or `(None, None)`."""
    rec = (script or {}).get(CADENCE_KEY) if isinstance(script, dict) else None
    band = rec.get("block_band") if isinstance(rec, dict) else None
    if not isinstance(band, dict):
        return None, None
    return band.get("axis"), band.get("cause") or rec.get("block_band_cause")


def score_of(verdict):
    """CF-0433: the plan's score block for this verdict, or None.

    `plan_check.json -> score` is the plan's own block when a plan was written.
    A plan refused on the score (`pattern_ceiling`, cause `score`) writes none;
    its block is in the deficit the refusal names (`plan.pattern-ceiling.json
    -> pattern_ceiling.score`), or on the refusal itself."""
    v = verdict or {}
    if isinstance(v.get("score"), dict):
        return v["score"]
    for r in v.get("refusals") or []:
        if r.get("kind") != "pattern_ceiling":
            continue
        if isinstance(r.get("score"), dict):
            return r["score"]
        deficit = read_json(r.get("deficit") or "") if r.get("deficit") else None
        block = ((deficit or {}).get("pattern_ceiling") or {}).get("score")
        if isinstance(block, dict):
            return block
    # CF-0434: the Editor's score log of the round (plan_check.py moves
    # `plan.*.json` away before every round, so one found is this round's) -
    # the only place a plan refused under N on similarity alone keeps its block
    block = (v.get("_score_log") or {}).get("score")
    return block if isinstance(block, dict) else None


def score_log_of(work):
    """CF-0434: `{path, score, score_line}` of the Editor's score log beside
    the plan (`work/<slug>/plan.score.json`), or None."""
    path = Path(work) / SCORE_LOG
    doc = read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("score"), dict):
        return None
    return {"path": str(path), "score": doc["score"], "score_line": doc.get("score_line")}


def score_line(verdict):
    """CF-0434: the one line of the plan's score - the Editor's own
    (`score_log.summary_line()`: `B · 74 — −9 похожесть (3 блока), ...`), read
    off the block (`line`) or the score log of the round; else the root's
    `shared/score/score.py summary_line()` on the block (the same format, via
    `_score.summary_line()`), and the English `_score.summary()` only when the
    root model cannot be loaded. None with no score."""
    block = score_of(verdict)
    if not isinstance(block, dict) or block.get("score") is None:
        return None
    if block.get("line"):
        return block["line"]
    log = (verdict or {}).get("_score_log") or {}
    if log.get("score_line") and (log.get("score") or {}).get("score") == block.get("score"):
        return log["score_line"]
    return _score.summary_line(block)


def score_stops(block):
    """CF-0434: the Editor's `score_log.stops()` - the score was computed and
    its points are under N. The hard list is not this (tier F in the log, and
    its own gate refuses)."""
    if not isinstance(block, dict):
        return False
    pts, thr = block.get("score"), block.get("threshold")
    return isinstance(pts, (int, float)) and isinstance(thr, (int, float)) and pts < thr


def loss_code(verdict, by_score=True):
    """CF-0434: `(reason_code, gate)` of a drop - the score model's loss when
    the plan's real score is under N, else `plan_unassembled` (no gate)."""
    if by_score and score_stops(score_of(verdict)):
        return SCORE_REASON_CODE, SCORE_GATE
    return REASON_CODE, None


def score_summary(block):
    """`{score, tier, threshold, passed, short_by, by_rule}` - what a check
    record and a skipped[] entry keep of the block (the log stays in the
    verdict)."""
    if not isinstance(block, dict) or block.get("score") is None:
        return None
    thr, pts = block.get("threshold"), block.get("score")
    short = (round(thr - pts, 2) if isinstance(thr, (int, float))
             and isinstance(pts, (int, float)) and pts < thr else 0)
    return {"score": pts, "tier": block.get("tier"), "threshold": thr,
            "passed": block.get("passed"), "short_by": short,
            "by_rule": {k: v.get("charged") for k, v in (block.get("by_rule") or {}).items()}}


def score_unreachable(verdict, script=None):
    """CF-0433: the sentence for a plan under N that no anchor edit can lift
    over it, or None.

    The points an anchor edit can win back are the prices of this stage's
    three rules (SCORE_LEVERS) - and not the pace's when the Editor says the
    pool cannot reach the floor (`fixable_by_anchors: false`). A score under
    N by more than that is a verdict the anchors do not move: no round is
    spent on it. The hard list is never the anchors' (a hard finding is F at
    any score)."""
    block = score_of(verdict)
    s = score_summary(block)
    if s is None or s["passed"] is not False:
        return None
    if block.get("hard"):
        return (f"{score_head(block)}, hard list "
                f"{', '.join(h.get('rule', '?') for h in block['hard'])}: no anchor edit "
                f"clears a hard finding")
    levers = dict(s["by_rule"])
    if pool_ceiling(verdict) is not None:
        levers.pop("score.pace_below_floor", None)
    if cadence_axis(script)[1] == CAUSE_SPEECH:
        # CF-0447: the cadence gate found no placement of anchors under the
        # top on this speech, and the text is locked here.
        levers.pop(RULE_BLOCK_BAND, None)
    winnable = -sum(v for k, v in levers.items() if k in SCORE_LEVERS and v)
    if winnable >= s["short_by"]:
        return None
    return (f"{score_head(block)}; the prices anchor edits can win back come to {winnable} "
            f"point(s) - not enough to reach N")


def score_head(block):
    s = score_summary(block)
    if s is None:
        return None
    return (f"score {s['score']}/{block.get('start', 100)} ({s['tier']}) against N="
            f"{s['threshold']}" + (f" - {s['short_by']} point(s) short" if s["short_by"] else ""))


def score_hint(block, script=None):
    """CF-0433: the plan's penalty log as the writer's hint - one line per
    price, and once per rule what an anchor edit can do about it. Empty when
    there is no log. CF-0447: under `score.block_band_exceeded` the cadence
    gate's Axis sentence for this script (`anchor_cadence.block_band.axis`)."""
    if not isinstance(block, dict) or not block.get("log"):
        return []
    lines = [f"    [score] {block['line']}"] if block.get("line") else []
    lines.append(f"    [score] {score_head(block)}; the penalty log (win back the points with "
                 f"anchor edits only):")
    for e in sorted(block["log"], key=lambda e: e.get("price") or 0):
        where = ", ".join(f"{k} {v}" for k, v in (e.get("where") or {}).items()) or "video"
        lines.append(f"        {e.get('price')} {e.get('rule')} ({where})"
                     + (f": {str(e.get('note'))[:160]}" if e.get("note") else ""))
    for rule in sorted({e.get("rule") for e in block["log"]}):
        if rule in SCORE_LEVERS:
            lines.append(f"      {rule.split('.', 1)[-1]}: {SCORE_LEVERS[rule]}")
        if rule == RULE_BLOCK_BAND:
            axis, _cause = cadence_axis(script)
            if axis:
                lines.append(f"      block_band_exceeded, the cadence gate on this speech "
                             f"(anchor_cadence.block_band.axis): {axis}")
    return lines


def hints(verdict, script, shots, source=INDEX_SOURCE):
    """Lines telling the writer what to change - anchors only, never the text.
    `shots`/`source` are `candidate_shots()`'s (CF-0428). CF-0433: the plan's
    penalty log closes the list (`score_hint()`)."""
    lines = []
    anchors = {a.get("anchor_id"): a for a in script.get("visual_anchors") or []}
    for r in verdict.get("refusals") or []:
        kind = r.get("kind")
        where = " ".join(x for x in (
            f"anchor {r['anchor_id']}" if r.get("anchor_id") else "",
            f"block {r['block']}" if r.get("block") is not None else "") if x)
        head = f"    [{kind}]" + (f" {where}" if where else "")
        phrase = r.get("phrase") or (anchors.get(r.get("anchor_id")) or {}).get("phrase")
        if kind == "pattern_ceiling":
            for line in pattern_hint(r, verdict, script):
                lines.append(f"{head}: {line}")
            sp = r.get("supply") or {}
            if sp.get("code") in SUPPLY_WANTS_SHOTS:
                named = sp.get("unused_shots") or ([
                    {"shot": label, "seconds": secs, "description": desc}
                    for label, desc, secs, _ in shots[:SUPPLY_SHOTS_LISTED]]
                    if source == CAPACITY_SOURCE else [])
                for u in named[:SUPPLY_SHOTS_LISTED]:
                    lines.append(f"        {u.get('shot')} ({u.get('seconds')} s) "
                                 f"{str(u.get('description') or '')[:140]}")
                if not named:
                    lines.append("        (the Editor named no unused usable shot)")
            continue
        if kind in ("cut_gate", "absent"):
            why = ("the cut-clip gate refused every candidate (framing / brightness are "
                   "measured on the cut clip)" if kind == "cut_gate"
                   else "no shot of the pool pictures it")
            lines.append(f"{head}: «{phrase}» - {why}. REPLACE the phrase with a shot "
                         f"the pool has (keep beat_text on the same words):")
        elif kind in ("background", "typographic"):
            rung = "procedural background" if kind == "background" else "typographic card"
            lines.append(f"{head}: the block fell to the {rung} rung - no video frame. Give its "
                         f"words an anchor on a video shot"
                         + (f" (now «{phrase}»)" if phrase else "") + ":")
        elif kind == "anchors_dropped":
            lines.append(f"{head}: no anchor's beat_text was found in the voice - copy each "
                         f"beat_text word for word out of hook / commentary / payoff")
            continue
        elif kind in UNFIXABLE_BY_ANCHORS:
            lines.append(f"{head}: {str(r.get('reason') or '')[:200]} - no anchor edit fixes "
                         f"the length of the voice, and the text may not change here")
            continue
        else:
            lines.append(f"{head}: {str(r.get('reason') or '')[:300]}"
                         + (f" (reason_code {r['reason_code']})" if r.get("reason_code") else ""))
            continue
        for label, desc, secs, _ in candidates_for(phrase or "", shots):
            lines.append(f"        {label} ({secs} s) {desc[:140]}")
        if not shots:
            lines.append("        (no usable shot of the pool is left off screen - the Editor's "
                         "pool_capacity; a new phrase finds no new picture here)"
                         if source == CAPACITY_SOURCE else
                         "        (the pool's shot indexes could not be read)")
    block = score_of(verdict)
    line = score_line(verdict)
    lines += score_hint(dict(block, line=line) if isinstance(block, dict) and line else block,
                        script)
    return lines


# --------------------------------------------------------------------------
# the batch file

def load_batch(path):
    doc = read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("scripts", []), list):
        raise SystemExit(f"PLAN CHECK LOOP: ERROR: {path} is not a readable {BATCH_FILE}")
    return doc


def script_by_id(doc, sid):
    for s in doc.get("scripts") or []:
        if s.get("script_id") == sid:
            return s
    return None


def rollback_text(batch_file, sid, snapshot, records=None):
    """Restore the text of the first check and (CF-0852) every record written
    on it, `records` as `text_records()` took them then. `records` None - a
    snapshot taken before CF-0852 - restores the text alone, as it did."""
    doc = load_batch(batch_file)
    s = script_by_id(doc, sid)
    for k in TEXT_FIELDS:
        if snapshot.get(k) is None:
            s.pop(k, None)
        else:
            s[k] = snapshot[k]
    if records is not None:
        for k in TEXT_RECORDS:
            if k in records:
                s[k] = copy.deepcopy(records[k])
            else:
                s.pop(k, None)
    mbf.write_atomically(batch_file, mbf.dump(doc))


def mark_script(batch_file, sid, block):
    """CF-0422: the script's own `plan_check` block in 03 - what the loop
    decided about a script that is still in `scripts[]` (deferred for the
    supplement, and how the check after it ended). A block replaces the one
    before it; the script's text and anchors are not touched."""
    doc = load_batch(batch_file)
    s = script_by_id(doc, sid)
    if s is None:
        return None
    s[SCRIPT_FIELD] = block
    mbf.write_atomically(batch_file, mbf.dump(doc))
    return block


def mark_score(batch_file, sid, verdict, outcome):
    """CF-0434: the score a script leaves step 6b with - `score_after_6b`
    and `score_line` on the script in 03 (replaced every check, so the last
    one stands). Nothing is written when the Editor priced nothing."""
    summary = score_summary(score_of(verdict))
    if summary is None:
        return None
    doc = load_batch(batch_file)
    s = script_by_id(doc, sid)
    if s is None:
        return None
    line = score_line(verdict)
    # CF-0547: an anchor whose picture arrives ahead of the fact's first word,
    # measured on this round's voice (work/<slug>/words.json). Recorded on the
    # script as `fact_anchor_early`; charged into the score only once the
    # user's signature put `score.fact_anchor_early` in the price table's
    # `rules` - until then the record says what it would cost.
    fa = cpf.fact_anchor_record(s, cpf.words_of(Path(batch_file).resolve().parent, s))
    if fa is None:
        s.pop(cpf.LEAD_RECORD, None)
    else:
        s[cpf.LEAD_RECORD] = fa
        # CF-0583: once signed, the Editor prices the same rule in plan.json
        # (video-editor scripts/fact_anchor.py) - and that block IS
        # score_of(verdict). Added here only when the Editor's block lacks it:
        # one finding of the rule per script, never two.
        editor = list((score_of(verdict) or {}).get("findings") or [])
        if fa["findings"] and not any((f or {}).get("rule") == cpf.SCORE_RULE for f in editor):
            rescored = _score.score_block(editor + fa["findings"])
            summary = score_summary(rescored) or summary
            line = _score.summary_line(rescored)
    block = dict(summary, stage=SCORE_STAGE, outcome=outcome,
                 round=(verdict or {}).get("round"), verdict=(verdict or {}).get("_path"))
    s[SCRIPT_SCORE_FIELD] = block
    s[SCRIPT_LINE_FIELD] = line
    mbf.write_atomically(batch_file, mbf.dump(doc))
    return block


def pool_ceiling(verdict):
    """CF-0428: the `pattern_ceiling` refusal the Editor marked
    `fixable_by_anchors: false` (its `supply.code` is `pool_too_thin`: the
    pool cannot put the floor's blocks on screen whatever the anchors say),
    or None."""
    for r in (verdict or {}).get("refusals") or []:
        if r.get("kind") == "pattern_ceiling" and r.get("fixable_by_anchors") is False:
            return r
    return None


def not_fixable_why(verdict):
    """CF-0428: the sentence a drop for a verdict no anchor edit clears carries
    - the pool's most blocks against the floor's, when the Editor measured
    them (`supply`)."""
    r = pool_ceiling(verdict)
    if r is None:
        return ("not fixable by anchors: the Editor's verdict says no edit of visual_anchors "
                "clears it (fixable_by_anchors: false)")
    sp = r.get("supply") or {}
    cap = sp.get("pool_capacity") or {}
    return (f"not fixable by anchors ({sp.get('code') or 'fixable_by_anchors: false'}): the pool "
            f"can put at most {cap.get('blocks_max')} block(s) on screen "
            f"({sp.get('max_rate_per_minute')} blocks/min at best) and the pattern's floor "
            f"{r.get('band_min')}/min wants {sp.get('blocks_needed')} over "
            f"{sp.get('span_seconds')} s - widen the pool or assign another pattern")


def edit_rounds_used(checks):
    """The anchor-edit rounds spent: every check after the free first one. A
    check that ended deferred for the supplement spends nothing (CF-0422)."""
    return max(0, len([c for c in checks or [] if not c.get("deferred")]) - 1)


def skip_entry(script, verdict, state, rounds, why, moved, by_score=True):
    kinds = sorted({r.get("kind") for r in (verdict or {}).get("refusals") or [] if r.get("kind")})
    first = ((verdict or {}).get("refusals") or [{}])[0]
    after = state.get("after_supplement")
    all_checks = (state.get("checks") or []) + ((after or {}).get("checks") or [])
    edits = edit_rounds_used((after or {}).get("checks") if after else state.get("checks"))
    code, gate = loss_code(verdict, by_score)
    block = score_of(verdict)
    line = score_line(verdict)
    last = (f"last refusal [{', '.join(kinds) or 'none'}]: "
            f"{str(first.get('reason') or '')[:400]}")
    if gate:
        reason = (f"{script.get('script_id')}: the plan's real score is under N at step 6b and "
                  f"no anchor-edit round is left to lift it (CF-0434, early stop - tier "
                  f"{SCORE_TIER_LOST}): {line} - {why}; {last}")
    else:
        reason = (f"{script.get('script_id')}: the Video Editor's own gates built no plan out of "
                  f"this script before the render (CF-0411) - {why}; {last}")
    entry = {
        "topic_id": script.get("topic_id"),
        "reason_code": code,
        "reason": reason,
        "stage": FUNNEL_STAGE,
        "script_id": script.get("script_id"),
        "kinds": kinds,
    }
    if gate:
        entry["gate"] = gate
    if isinstance(block, dict) and block.get("score") is not None:
        # CF-0434: the score the topic left with, in the Editor's one line
        entry["tier"] = SCORE_TIER_LOST if gate else block.get("tier")
        entry[SCRIPT_LINE_FIELD] = line
    entry["plan_check"] = {
            "verdict": (verdict or {}).get("_path"),
            "round": (verdict or {}).get("round"),
            "rounds_allowed": rounds,
            "anchor_edit_rounds_used": edits,
            "text_changed": bool((verdict or {}).get("text_changed")),
            "text_rolled_back": any(c.get("text_rolled_back") for c in all_checks),
            "deferred_for_supplement": state.get(DEFERRED),
            "after_supplement": bool(after),
            # CF-0428: whether the anchors were the lever at all, and the
            # pool's numbers when the Editor said they were not
            "fixable_by_anchors": (verdict or {}).get("fixable_by_anchors"),
            "supply": (pool_ceiling(verdict) or {}).get("supply"),
            # CF-0433: the plan's score at the drop, when the Editor priced it
            "score": score_summary(score_of(verdict)),
            "refusals": [{k: r.get(k) for k in ("kind", "gate", "block", "anchor_id", "phrase")}
                         for r in (verdict or {}).get("refusals") or []],
            "refusal_sidecars_moved_to": moved,
            "score_log": ((verdict or {}).get("_score_log") or {}).get("path"),
    }
    return entry


def move_sidecars(work):
    """Every `*.refusal.json` directly in work/<slug>/ -> plan_check.rounds/dropped/:
    the Editor's metadata collects `work/*/*.refusal.json`, and this loss is
    already `03 -> skipped[]`'s."""
    found = sorted(work.glob(f"*{REFUSAL_SUFFIX}"))
    if not found:
        return None
    dest = work / ROUNDS_DIR / DROPPED_DIR
    dest.mkdir(parents=True, exist_ok=True)
    for p in found:
        shutil.move(str(p), str(dest / p.name))
    return str(dest)


def drop(batch_file, doc_batch_id, script, verdict, state, rounds, why, work, write,
         by_score=True):
    if not write:
        return None
    moved = move_sidecars(work)
    entry = skip_entry(script, verdict, state, rounds, why, moved, by_score)
    base = load_batch(batch_file)
    gw.clear(base, [script.get("topic_id")], vc.GATE_PLAN)   # CF-0412: no video, no warning
    merged, _ = mbf.merge(base, {"batch_id": doc_batch_id, "skipped": [entry]})
    mbf.write_atomically(batch_file, mbf.dump(merged))
    return entry


# --------------------------------------------------------------------------
# CF-0412: the narrator's visual claims, on the real resolve

VISUAL_CLAIM_MEASURE = ("step 6b: the real resolve - plan_check.json refusals and the "
                        "storyboard's unresolved_anchors (the topic-footage rung included)")


def _block_of(storyboard, phrase):
    """plan_check.py's own rule: a block's intent is its anchor's phrase,
    sometimes with the resolver's note appended."""
    for i, b in enumerate((storyboard or {}).get("blocks") or []):
        intent = (b.get("intent") or "").strip()
        if phrase and (intent == phrase or intent.startswith(phrase + " (")):
            return i
    return None


def visual_claims(batch_file, work, script, verdict, write, out):
    """The narrator's lines that point at a picture this round's real resolve
    did not give (`_visual_claim`): a warning only - the text is locked in this
    loop and nothing is owed on it. Written, every check, to
    `work/<slug>/visual_claims.json` beside the plan (for the frame judge's
    pack) and, with `write`, into 03 `warnings[]` under gate
    `visual_claim_plan` - replacing this step's earlier entry for the topic,
    or clearing it when no claim is left uncovered."""
    storyboard = read_json(work / "storyboard.json") or {}
    claims = vc.judge(script, vc.plan_status(verdict, storyboard.get("unresolved_anchors")))
    for c in claims:
        c["block"] = _block_of(storyboard, next(
            (a.get("phrase") for a in script.get("visual_anchors") or []
             if a.get("anchor_id") == c.get("anchor_id")), None))
    write_json(work / vc.SIDECAR, {
        "kind": "visual_claims", "task": "CF-0412", "decision": vc.DECISION,
        "script_id": script.get("script_id"), "topic_id": script.get("topic_id"),
        "round": verdict.get("round"), "verdict": verdict.get("_path"),
        "measured_on": VISUAL_CLAIM_MEASURE, "at": now(), "claims": claims})
    e = vc.entry(script, claims, vc.GATE_PLAN, stage_note=VISUAL_CLAIM_MEASURE)
    if write:
        doc = load_batch(batch_file)
        gw.clear(doc, [script.get("topic_id")], vc.GATE_PLAN)
        gw.record(doc, [e] if e else [])
        mbf.write_atomically(batch_file, mbf.dump(doc))
    if e:
        out(vc.line(e) + ("" if write else " [not recorded: run with --write]"))
    return claims


# --------------------------------------------------------------------------
# one script

# CF-0900 (`example-film/2026-10-30T1033Z`): the stage stopped a running loop
# with `pkill -f plan_check_loop` to edit a script. SIGTERM took the loop down
# and nothing else: plan_check.py runs in a session of its own (the ceiling's
# kill above needs it), so it and its resolve_anchors.py lived on as orphans,
# writing work/<slug> under nobody - and resolve died on its last print into
# the loop's closed pipe (`BrokenPipeError`, a crash in the triage). A stop of
# the loop is now a stop of the tree: the sessions still running are killed
# as on the ceiling, and the loop exits through its own `finally` (topic locks
# released, runlog `failed`) instead of vanishing mid-line.
STOP_SIGNALS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGHUP", "SIGINT")
                     if hasattr(signal, n))
_LIVE_CHECKS = set()   # the plan_check.py sessions of this run still running


def kill_live_checks():
    """Kill every plan_check.py session this run started and has not reaped,
    with whatever runs under it (resolve_anchors.py, ffmpeg)."""
    for proc in list(_LIVE_CHECKS):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass


def _on_stop(signum, _frame):
    kill_live_checks()
    try:
        name = signal.Signals(signum).name
    except ValueError:
        name = str(signum)
    print(f"PLAN CHECK LOOP: STOPPED by {name} - plan_check.py and its resolve were killed "
          f"with it; no verdict of this run is recorded for a script it was checking. "
          f"Rerun the same command for those (CF-0900)", file=sys.stderr)
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def stop_takes_the_tree():
    """While the loop runs plan_check.py, a SIGTERM / SIGHUP / SIGINT to it
    kills the plan_check.py sessions too (CF-0900). The previous handlers come
    back on exit; off the main thread (no signals there) it is a no-op."""
    saved = {}
    try:
        for sig in STOP_SIGNALS:
            saved[sig] = signal.signal(sig, _on_stop)
    except ValueError:      # not the main thread
        pass
    try:
        yield
    finally:
        for sig, handler in saved.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, TypeError):
                pass


def run_plan_check(args, py, pc, batch, sid, slug, channel):
    argv = [str(py), str(pc), "check", str(batch), "--script-id", sid, "--slug", slug]
    if channel:
        argv += ["--channel", channel]
    if args.adopt_voice:
        argv += ["--adopt-voice"]
    # Its own session, so a kill on the ceiling takes the whole tree down:
    # plan_check.py runs resolve_anchors.py, which runs ffmpeg - killing only
    # the direct child left both running (seen on the first real run).
    with runlog.child("plan_check.py", argv=argv) as fr:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        _LIVE_CHECKS.add(proc)
        try:
            try:
                stdout, stderr = proc.communicate(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
                proc.communicate()
                fr["rc"] = "timeout"
                return PC_ENVIRONMENT, (f"plan_check.py passed the {args.timeout:.0f}s ceiling - "
                                        f"killed with its children")
        finally:
            _LIVE_CHECKS.discard(proc)
        fr["rc"] = proc.returncode
    return proc.returncode, (stdout or "") + (stderr or "")


# CF-0422: how a check after the supplement can end and let the script go on
# its way - built, dropped, or no answer (it goes on as before, like step 6b's
# own ENVIRONMENT). `edit` is not an end: the writer is still in its rounds; nor
# is `would_drop` - a run without --write recorded nothing, the script is
# still in scripts[] and the check is still owed.
AFTER_CONCLUDED = ("assembled", "dropped", "environment")


def load_state(work, script):
    return read_json(work / STATE) or {"kind": "plan_check_loop",
                                       "script_id": script.get("script_id"),
                                       "topic_id": script.get("topic_id"),
                                       "slug": slug_of(script), "checks": []}


def after_outcome(state):
    return (state.get("after_supplement") or {}).get("outcome")


def pending_after_supplement(state):
    """Deferred for the supplement and not yet settled by the check after it."""
    return bool(state.get(DEFERRED)) and after_outcome(state) not in AFTER_CONCLUDED


def pool_of(script):
    return list((script.get("anchor_coverage_pool") or {}).get("indexes") or [])


def one_script(args, batch, batch_file, doc, script, rounds, py, pc, out):
    sid = script.get("script_id")
    tid = script.get("topic_id")
    slug = slug_of(script)
    work = batch / "work" / slug
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / STATE
    state = load_state(work, script)
    after = bool(getattr(args, "after_supplement", False))
    deferred = state.get(DEFERRED)
    text = narration_text(script)
    rolled_back = False
    ab = None

    def mark(extra):
        """The script's `plan_check` block in 03 (--write only)."""
        if args.write and state.get(DEFERRED):
            mark_script(batch_file, sid, dict({"status": DEFERRED}, **state[DEFERRED], **extra))

    # --- CF-0422: a deferred script waits for the supplement, not for an edit
    if deferred and not after:
        settled = after_outcome(state)
        if settled in AFTER_CONCLUDED:
            out(f"  {settled.upper()} {sid} ({slug}): settled by the check after the "
                f"supplement - not checked again")
            return settled
        req = supreq.open_request(batch, tid)
        if (script.get(SCRIPT_FIELD) or {}).get("status") != DEFERRED:
            mark({})
        out(f"  DEFERRED (supplement pending) {sid} ({slug}): deferred at check "
            f"{deferred.get('check')} for the thin-pool supplement of topic {tid} - "
            + (f"request {req['path']} ({req['phase']}); not checked again here: after "
               f"thin-pool-supplement the orchestrator runs this command with "
               f"--after-supplement" if req else
               "the supplement step has finished this topic: run this command with "
               "--write --after-supplement"))
        return "deferred"
    if after:
        req = supreq.open_request(batch, tid)
        if req:
            out(f"  DEFERRED (supplement pending) {sid} ({slug}): the thin-pool supplement has "
                f"not finished topic {tid} yet (request {req['path']}, {req['phase']}) - run "
                f"scripts/thin_pool_supplement.py <batch> first; nothing checked, nothing spent")
            return "deferred"
        ab = state.setdefault("after_supplement", {"task": DEFERRED_TASK, "started_at": now(),
                                                   "checks": []})
        ab["rounds_allowed"] = rounds
        checks = ab["checks"]
        if not checks:
            before, now_pool = deferred.get("indexes") or [], pool_of(script)
            new = [p for p in now_pool if p not in before]
            ab["indexes_at_deferral"], ab["indexes"] = before, now_pool
            out(f"  AFTER SUPPLEMENT {sid} ({slug}): the pool held {len(before)} shot index(es) "
                f"at the deferral and holds {len(now_pool)} now ({len(new)} new) - checked on "
                f"it with {rounds} anchor-edit round(s) of its own")
    else:
        state["rounds_allowed"] = rounds
        checks = state["checks"]

    def finish(outcome, block_extra=None):
        state["outcome"] = outcome
        if ab is not None:
            ab["outcome"], ab["at"] = outcome, now()
            if block_extra is not None:
                mark(dict({"after_supplement": {"outcome": outcome, "checks": len(checks),
                                                "at": ab["at"]}}, **block_extra))
        write_json(state_path, state)
        return outcome

    # --- the text guard, before anything is paid for
    snap = state.get("text_snapshot")
    if snap is None:
        previous = read_json(work / VERDICT) or {}
        baseline = previous.get("baseline_text_sha256") or previous.get("text_sha256")
        if baseline and baseline != sha256_text(text):
            verdict = dict(previous, text_changed=True, _path=str(work / VERDICT))
            why = ("the narrator's text is not the one the first plan check was built from "
                   "and no snapshot of that text is left to roll back to (text guard)")
            entry = drop(batch_file, doc.get("batch_id"), script, verdict, state, rounds, why,
                         work, args.write, by_score=False)
            state["outcome"] = "dropped" if entry else "would_drop"
            write_json(state_path, state)
            out(f"  DROPPED {sid} ({slug}): TEXT CHANGED before this loop's first check - {why}"
                + ("" if entry else " [not recorded: run with --write]"))
            return "dropped"
        state["text_snapshot"] = text_snapshot(script)
        state[TEXT_RECORDS_STATE_KEY] = text_records(script)
        state["text_sha256"] = sha256_text(text)
    elif text_snapshot(script) != snap:
        if not args.write:
            out(f"  TEXT CHANGED {sid} ({slug}): the narrator's text differs from the one the "
                f"first check was built from - not checked; run with --write to roll it back")
            return "edit"
        records = state.get(TEXT_RECORDS_STATE_KEY)
        rollback_text(batch_file, sid, snap, records)
        doc = load_batch(batch_file)
        script = script_by_id(doc, sid)
        rolled_back = True
        out(f"  TEXT ROLLED BACK {sid} ({slug}): hook / commentary / payoff restored to the "
            f"text step 6 cleared"
            + (" with the records written on it (fact, claims, graphics, the gates' "
               "verdicts - CF-0852)" if records is not None else
               " (a snapshot from before CF-0852: the records written on the text are "
               "not restored - rerun the text gates of step 6)")
            + " - only visual_anchors change in this loop; the anchor edits are kept and "
              "checked")

    # --- CF-0860: the fact's beat and the claims quote this very text
    script = records_in_sync(batch_file, sid, slug, script, state, args.write, out)
    if script is None:
        return "out_of_sync"

    code, text_out = run_plan_check(args, py, pc, batch, sid, slug,
                                    resolve_channel(args.channel or doc.get("channel")))
    for line in text_out.splitlines():
        if line.startswith("PLAN CHECK") or line.lstrip().startswith(("REFUSED", "refusal ->")):
            out(f"    | {line}")
    verdict = read_json(work / VERDICT)
    if code not in (PC_ASSEMBLED, PC_REFUSED) or not isinstance(verdict, dict) \
            or verdict.get("environment_error"):
        tail = " / ".join(text_out.strip().splitlines()[-2:])[:300]
        out(f"  ENVIRONMENT {sid} ({slug}): plan_check.py exit {code} - not an answer about the "
            f"script; it goes on as before (the Editor builds it the old way). {tail}")
        return finish("environment", {"status": "environment_after_supplement"})
    verdict["_path"] = str(work / VERDICT)
    # CF-0434: the Editor's score log of this round, beside the plan
    score_log = score_log_of(work)
    if score_log:
        verdict["_score_log"] = score_log
    unchanged = "UNCHANGED since round" in text_out
    leg = ab if ab is not None else state
    first_of_leg = not checks
    # CF-0430: the Editor's inputs are the last check's and it built nothing -
    # this run is not a check. Nothing is appended, so no round is spent; the
    # first check of a loop (or of the after-supplement leg) always counts.
    idle = unchanged and not verdict.get("assembled") and bool(checks)
    # CF-0793: ... unless this run follows an anchor-edit pass and no check was
    # made since the run that handed the script to that pass: the pass changed
    # nothing, and a pass that changes nothing is a spent round (batch
    # example-film/2026-10-18T0841Z: four passes, none spent, the stage ran out
    # of reruns and the batch failed with three scripts ready). A pass that
    # edited and ran this command itself has spent its round there already.
    edit_pass = bool(getattr(args, "edit_pass", False))
    handed_at = leg.get(EDIT_PASS_MARK)
    pass_idle = idle and edit_pass and (handed_at is None or len(checks) <= handed_at)
    check = {
        "at": now(), "round": verdict.get("round"), "assembled": bool(verdict.get("assembled")),
        "kinds": sorted({r.get("kind") for r in verdict.get("refusals") or []}),
        "anchors_sha256": verdict.get("anchors_sha256"), "unchanged": unchanged,
        "text_rolled_back": rolled_back,
        # CF-0433: the plan's score this round (shared/score) - None when the
        # Editor priced nothing (no plan and no score refusal)
        "score": score_summary(score_of(verdict)),
        "score_line": score_line(verdict)}
    if pass_idle:
        check[EDIT_PASS_SPENT] = True
        checks.append(check)
        idle = False
    elif idle:
        leg[rg.RERUNS_KEY] = int(leg.get(rg.RERUNS_KEY) or 0) + 1
    else:
        checks.append(check)
    tag = " after the supplement" if after else ""
    check["visual_claims_uncovered"] = len(
        visual_claims(batch_file, work, script, verdict, args.write, out))

    def dropped(entry):
        return finish("would_drop" if after and not entry else "dropped")

    if verdict.get("text_changed"):
        why = ("the verdict says the voice was built from a text that differs from round 1's "
               "(text guard: anchors may change in this loop, the text may not)")
        entry = drop(batch_file, doc.get("batch_id"), script, verdict, state, rounds, why, work,
                     args.write, by_score=False)
        out(f"  DROPPED {sid} ({slug}): TEXT CHANGED{tag} - {why} -> skipped[] as "
            f"`{REASON_CODE}`" + ("" if entry else " [not recorded: run with --write]"))
        return dropped(entry)

    if verdict.get("assembled"):
        # CF-0433: built means at or over N - the prices are said, nothing is
        # rewritten for them (a round is for a plan that was not built).
        head = score_head(score_of(verdict))
        out(f"  ASSEMBLED {sid} ({slug}) check {len(checks)}{tag}, plan_check round "
            f"{verdict.get('round')}: the Editor's plan is built - the script goes on"
            + (f"; {head}" if head else ""))
        line = score_line(verdict)
        if line:
            out(f"    SCORE after 6b: {line}")
        if args.write:
            mark_score(batch_file, sid, verdict, "assembled")
        return finish("assembled", {"status": "assembled_after_supplement"})

    edits_used = edit_rounds_used(checks)
    kinds = sorted({r.get("kind") for r in verdict.get("refusals") or []})
    unfixable = [k for k in kinds if k in UNFIXABLE_BY_ANCHORS]
    # CF-0428: the Editor says no anchor edit clears it (a pace floor the pool
    # cannot reach, `supply.code: pool_too_thin`) - no round is spent on it.
    # Before the supplement an open request still defers it (more footage is
    # exactly what it needs); after it, or with no request, it is dropped now.
    # CF-0433: and the score - a plan under N by more points than the anchor
    # edits can win back (score_unreachable()) is not a round either.
    by_score = None if unfixable else score_unreachable(verdict, script)
    not_by_anchors = not unfixable and (verdict.get("fixable_by_anchors") is False
                                        or pool_ceiling(verdict) is not None
                                        or by_score is not None)

    # --- CF-0422: an open supplement request defers the verdict to the pool it brings
    if not after and not unfixable:
        req = supreq.open_request(batch, tid)
        if req:
            check["deferred"] = True
            if idle:   # a deferral is recorded, and spends nothing either way
                checks.append(check)
            state[DEFERRED] = {"task": DEFERRED_TASK, "at": now(), "check": len(checks),
                               "kinds": kinds, "verdict": verdict["_path"],
                               "supplement_request": req["path"],
                               "supplement_phase": req["phase"],
                               "indexes": list(verdict.get("indexes") or pool_of(script))}
            mark({})
            out(f"  DEFERRED (supplement pending) {sid} ({slug}): not built [{', '.join(kinds)}] "
                f"on the pool it has now, and topic {tid} has an open thin-pool supplement "
                f"request ({req['path']}, {req['phase']}) - not dropped, no round spent "
                f"(CF-0338: a thin pool is answered by more footage). After thin-pool-supplement "
                f"the orchestrator runs this command with --write --after-supplement; that "
                f"check decides" + ("" if args.write else " [03 not marked: run with --write]"))
            return finish(DEFERRED)

    if pass_idle:
        out(f"  {rg.UNCHANGED}: {sid} ({slug}){tag} - the anchor-edit pass before this run "
            f"changed no visual_anchor (the anchors are the ones check {len(checks) - 1} was "
            f"built from), so the pass is a spent round (CF-0793): {edits_used} of {rounds}")
    if unfixable or not_by_anchors or edits_used >= rounds or args.final:
        by_pool = (verdict.get("fixable_by_anchors") is False
                   or pool_ceiling(verdict) is not None)
        why = (f"{', '.join(unfixable)}: no anchor edit fixes it" if unfixable else
               not_fixable_why(verdict) if not_by_anchors and by_pool else
               f"not fixable by anchors (score): {by_score}" if not_by_anchors else
               "--final: the writer has no anchor edit left" if args.final and edits_used < rounds
               else f"{edits_used} anchor-edit round(s){tag} spent of {rounds}"
               + (" (the last anchor-edit pass changed nothing)" if pass_idle else ""))
        entry = drop(batch_file, doc.get("batch_id"), script, verdict, state, rounds, why, work,
                     args.write)
        code, gate = loss_code(verdict)
        out(f"  DROPPED {sid} ({slug}): not built{tag}, {why} [{', '.join(kinds)}] -> skipped[] "
            f"as `{code}`" + (f" (gate {gate}, tier {SCORE_TIER_LOST})" if gate else "")
            + f"; verdict {work / VERDICT}"
            + ("" if entry else " [not recorded: run with --write]"))
        line = score_line(verdict)
        if line:
            out(f"    SCORE after 6b: {line}")
        for line in hints(verdict, script, []):
            if line.startswith("    ["):
                out(line)
        return dropped(entry)

    left = rounds - edits_used
    again = "this command again (with --after-supplement)" if after else "this command again"
    if idle:
        out(f"  {rg.UNCHANGED}: {sid} ({slug}){tag} - visual_anchors are the ones check "
            f"{len(checks)} was built from (plan_check round {verdict.get('round')}), so this "
            f"run is not a check and spent nothing: still not built [{', '.join(kinds)}], "
            f"{left} anchor-edit round(s) left of {rounds}. Change visual_anchors in "
            f"{BATCH_FILE}, then run {again}; if there is no edit left to make, close it with "
            f"--final")
    out(f"  EDIT ANCHORS {sid} ({slug}){tag}: not built [{', '.join(kinds)}] - {left} anchor-edit "
        f"round(s) left of {rounds}"
        + (" (unchanged: no round spent)" if idle else "")
        + f". Change only visual_anchors in {BATCH_FILE}, then run {again}; if no anchor "
        f"edit can lift it, close it now with --final --script-id {sid} - an anchor-edit "
        f"pass that ends with neither is charged a round anyway (CF-0793):")
    shots, source = candidate_shots(verdict, work, script)
    if source == CAPACITY_SOURCE:
        out(f"    candidates: the Editor's pool_capacity - {len(shots)} usable shot(s) not yet "
            f"on screen (burned text, cached usability, retired and cut-clip refusals left out)")
    for line in hints(verdict, script, shots, source):
        out(line)
    if args.write:
        mark_score(batch_file, sid, verdict, "edit")
    if first_of_leg or edit_pass:
        # CF-0793: the script goes to an anchor-edit pass with this many checks
        leg[EDIT_PASS_MARK] = len(checks)
    return finish("edit", {} if after else None)


# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("batch", help="the batch directory (holds 03-content-researcher.json)")
    p.add_argument("--script-id", action="append", default=[],
                   help="check only this script (repeatable); default: every script in 03")
    p.add_argument("--write", action="store_true",
                   help="record: roll the text back, move a dropped topic to skipped[]")
    p.add_argument("--final", action="store_true",
                   help="the writer has no anchor edit left: drop what is still not built "
                        "(the way to close the loop without an edit - a plain rerun with "
                        "nothing edited is UNCHANGED and spends nothing, CF-0430)")
    p.add_argument("--edit-pass", action="store_true",
                   default=os.environ.get(EDIT_PASS_ENV, "") not in ("", "0"),
                   help=f"CF-0793: this run follows an anchor-edit pass (the run plan sets "
                        f"{EDIT_PASS_ENV}=1 on its reruns): UNCHANGED with no check since the "
                        f"run that handed the script to the pass spends a round")
    p.add_argument("--rounds", type=int, default=None,
                   help="override the channel's content_researcher.plan_check_rounds")
    p.add_argument("--channel", default=None, help="default: 03's `channel`")
    p.add_argument("--channel-config", default=None, help="default: <root>/channels/<channel>.json")
    p.add_argument("--plan-check", default=None,
                   help="default: <root>/agents/video-editor/scripts/plan_check.py")
    p.add_argument("--editor-python", default=None,
                   help="default: <root>/agents/video-editor/.venv/bin/python3")
    p.add_argument("--adopt-voice", action="store_true",
                   help="passed to plan_check.py: trust a voice.wav + words.json already in "
                        "work/<slug>/ whose narration.txt is this exact text (a batch voiced "
                        "before CF-0411)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                   help="ceiling on one script's plan_check.py, seconds")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--after-supplement", action="store_true",
                      help="CF-0422: check only the scripts deferred for the thin-pool "
                           "supplement, on the pool it brought, with rounds of their own; a "
                           "plan still not built now is dropped as plan_unassembled")
    mode.add_argument("--pending-after-supplement", action="store_true",
                      help="CF-0422: read-only - list the deferred scripts the check after the "
                           "supplement has not settled; exit 0 none, 1 some")
    p.add_argument("--json", action="store_true",
                   help="with --pending-after-supplement: print the list as JSON")
    return p


def pending(batch, doc):
    """CF-0422: `[{script_id, topic_id, slug, deferred_at, after_supplement}]` of
    the scripts still in `scripts[]` that were deferred for the supplement and
    that the check after it has not settled (not run yet, or still waiting for
    an anchor edit)."""
    out = []
    for s in doc.get("scripts") or []:
        slug = slug_of(s)
        state = read_json(batch / "work" / slug / STATE) if slug else None
        if isinstance(state, dict) and pending_after_supplement(state):
            out.append({"script_id": s.get("script_id"), "topic_id": s.get("topic_id"),
                        "slug": slug, "deferred_at": state[DEFERRED].get("at"),
                        "supplement_request": state[DEFERRED].get("supplement_request"),
                        "after_supplement": after_outcome(state) or "not run"})
    return out


def pending_main(args, batch, doc):
    rows = pending(batch, doc)
    if args.json:
        print(json.dumps({"batch": str(batch), "pending": rows}, indent=2, ensure_ascii=False))
    else:
        for r in rows:
            print(f"  PENDING {r['script_id']} ({r['slug']}) topic {r['topic_id']}: deferred for "
                  f"the thin-pool supplement at {r['deferred_at']}, the check after it: "
                  f"{r['after_supplement']}")
        print(f"PLAN CHECK LOOP: {len(rows)} script(s) deferred for the supplement and not "
              f"settled by `--after-supplement`"
              + (" - run `plan_check_loop.py <batch> --write --after-supplement` after "
                 "thin-pool-supplement" if rows else ""))
    return EXIT_EDIT if rows else EXIT_OK


# CF-0845 (the user's signature of 2026-10-21, Q8): a topic whose pool holds
# fewer clean usable shots than the channel's
# `content_researcher.min_usable_shots_for_script` (10 on Reel and Tech) is not
# checked here at all - the root's rule takes its scripts out of `scripts[]`
# into `skipped[]` as `pool_too_thin` before the first `plan_check.py`, so no
# voice, resolve or plan is paid for it and its slot goes to the reserve. The
# rule and the count (`01b pool_depth.topics[].usable_shots`) live at the root,
# `shared/runlog/thin_topic.py`; this repo keeps no copy and loads it by path,
# like `_factrule.py` loads the fact rule. A root without the module (the agent
# pinned beside an older root) is a warning and the loop as before.
THIN_TOPIC_REL = Path("shared") / "runlog" / "thin_topic.py"
THIN_TOPIC_TASK = "CF-0845"


def load_thin_topic(root=None):
    """-> `(module, None)`, or `(None, why)` when the root or its
    `shared/runlog/thin_topic.py` is not there or does not load."""
    root = root or _root_or_none()
    if root is None:
        return None, "the factory root was not found (set FACTORY_ROOT)"
    path = Path(root) / THIN_TOPIC_REL
    if not path.is_file():
        return None, f"no {THIN_TOPIC_REL} at the factory root {root} (an older root)"
    try:
        spec = importlib.util.spec_from_file_location("thin_topic_for_content_researcher", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:                                          # noqa: BLE001
        return None, f"{path} did not load ({type(e).__name__}: {e})"
    if not callable(getattr(mod, "write", None)):
        return None, f"{path} has no write() (an older root)"
    return mod, None


def thin_topic_gate(batch, out=print, root=None):
    """The root's drop before the first plan check, on the batch's 03.
    -> the `skipped[]` entries it added ([] when nothing moved, or when the
    rule could not be run - then a warning and nothing is taken out)."""
    root = root or _root_or_none()
    mod, why = load_thin_topic(root)
    if mod is None:
        out(f"PLAN CHECK LOOP: WARN: thin-topic gate ({THIN_TOPIC_TASK}) not run - {why}; "
            f"every topic goes to the plan check as before")
        return []
    try:
        rows, added = mod.write(batch, root)
    except (Exception, SystemExit) as e:                            # noqa: BLE001
        msg = e.code if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
        out(f"PLAN CHECK LOOP: WARN: thin-topic gate ({THIN_TOPIC_TASK}) failed - {msg}; "
            f"nothing taken out, every topic goes to the plan check as before")
        return []
    for a in added:
        out(f"  THIN POOL: {a.get('script_id') or a.get('topic_id')} -> skipped[] "
            f"`{a.get('reason_code')}` ({a.get('usable_shots')} usable shot(s) < "
            f"{a.get('min_usable_shots')}, {a.get('floor_from')}) - not checked, no "
            f"supplement, the slot goes to the reserve ({THIN_TOPIC_TASK})")
    return added


def _lock_holder(path):
    """What the holder wrote into the lock file (pid, started, argv), or {}."""
    try:
        data = json.loads(Path(path).read_text() or "{}")
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def lock_topics(batch, slugs):
    """CF-0485: an exclusive flock on `work/<slug>/.plan_check_loop.lock` for
    every slug, all or none. Returns `(fds, None)` on success - keep the fds
    open for the whole run - or `([], (slug, holder))` when one is held by a
    live run (whatever was taken meanwhile is released). A file left by a dead
    run carries no lock (the kernel dropped it with the process) and is simply
    taken over."""
    fds = []
    for slug in sorted(set(slugs)):
        work = batch / "work" / slug
        work.mkdir(parents=True, exist_ok=True)
        path = work / LOCK
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = _lock_holder(path)
            os.close(fd)
            unlock_topics(fds)
            return [], (slug, holder)
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"pid": os.getpid(), "started": now(),
                                 "argv": sys.argv}).encode())
        fds.append(fd)
    return fds, None


def unlock_topics(fds):
    for fd in fds:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def main(argv=None):
    args = build_parser().parse_args(argv)
    batch = Path(args.batch).expanduser().resolve()
    batch_file = batch / BATCH_FILE
    if not batch_file.exists():
        print(f"PLAN CHECK LOOP: ERROR: no {batch_file}", file=sys.stderr)
        return EXIT_BAD_USAGE
    doc = load_batch(batch_file)
    if args.pending_after_supplement:
        return pending_main(args, batch, doc)
    channel = resolve_channel(args.channel or doc.get("channel"))
    if args.rounds is not None and args.rounds >= 0:
        rounds, source = args.rounds, "--rounds"
    else:
        rounds, source = rounds_allowed(channel, config_path=args.channel_config)

    thin = []
    if args.write and not args.after_supplement:
        # CF-0845: the plain pass of 6b (the first call and the reserve call
        # alike) - before the lock and before the first plan_check.py.
        thin = thin_topic_gate(batch)
        if thin:
            doc = load_batch(batch_file)
    wanted = set(args.script_id)
    scripts = [s for s in doc.get("scripts") or [] if not wanted or s.get("script_id") in wanted]
    missing = wanted - {s.get("script_id") for s in scripts}
    if args.after_supplement:
        waiting = {r["script_id"] for r in pending(batch, doc)}
        scripts = [s for s in scripts if s.get("script_id") in waiting]
        if not scripts:
            print(f"PLAN CHECK LOOP: {batch.name} - no script deferred for the thin-pool "
                  f"supplement waits for its check: nothing to do")
            return EXIT_OK
    decided = jr.frozen(batch, scripts)
    if decided:
        # CF-0902: the round after the frame judge plans its substitutes only. A
        # first-pass script was rendered (or refused) and judged from the plan
        # in its work directory; re-planning it overwrote that plan under a video
        # already judged, and the claims judge then read the new one.
        for sid in sorted(decided):
            print(f"  FROZEN    {sid}: {decided[sid]} - not re-planned, its work/ untouched")
        scripts = [s for s in scripts if s.get("script_id") not in decided]
        if not scripts:
            print(f"PLAN CHECK LOOP: {batch.name} - every script named is the first pass's "
                  f"after the frame judge: nothing to do ({jr.TASK})")
            return EXIT_OK
    pc, py = editor_paths(plan_check=args.plan_check, editor_python=args.editor_python)
    if not pc or not Path(pc).exists() or not py or not Path(py).exists():
        print(f"PLAN CHECK LOOP: CANNOT ANSWER: the Editor's plan_check.py ({pc}) or its venv "
              f"({py}) is missing - every script goes on as before", file=sys.stderr)
        return EXIT_CANNOT_ANSWER

    fds, busy = lock_topics(batch, [slug_of(s) for s in scripts if slug_of(s)])
    if busy:
        slug, holder = busy
        print(f"PLAN CHECK LOOP: BUSY: another plan_check_loop.py (pid {holder.get('pid', '?')}, "
              f"started {holder.get('started', '?')}) is checking work/{slug} of {batch.name} "
              f"right now - this run touched nothing. Wait for that run's verdict and read "
              f"it; do not start this command again while it runs (CF-0485)",
              file=sys.stderr)
        return EXIT_BUSY
    try:
        with stop_takes_the_tree():     # CF-0900: a stop of the loop is a stop of its tree
            return checked(args, batch, batch_file, scripts, missing, rounds, source, py, pc,
                           thin=len(thin),
                           unwritten=sum(1 for a in thin if not a.get("script_id")))
    finally:
        unlock_topics(fds)


def checked(args, batch, batch_file, scripts, missing, rounds, source, py, pc, thin=0,
            unwritten=0):
    print(f"PLAN CHECK LOOP: {batch.name} - {len(scripts)} script(s)"
          + (" deferred for the supplement" if args.after_supplement else "")
          + f", anchor-edit rounds allowed {rounds} ({source})")
    for sid in sorted(missing):
        print(f"  not in scripts[]: {sid} (already dropped, or never written)")

    outcomes, built = [], []
    for script in scripts:
        doc = load_batch(batch_file)
        current = script_by_id(doc, script.get("script_id"))
        if current is None:
            continue
        outcome = one_script(args, batch, batch_file, doc, current, rounds, py, pc, print)
        outcomes.append({"would_drop": "dropped", DEFERRED: "deferred",
                         "out_of_sync": "edit"}.get(outcome, outcome))
        if outcome == "assembled":
            built.append(current.get("script_id"))

    # CF-0933: the claims against the plans just built, before the stage can close
    claims = claims_on_plan(args, batch, batch_file, built)
    for sid, res in claims.items():
        if res in ("edit", "refused", "environment"):
            outcomes.remove("assembled")
            outcomes.append({"refused": "dropped"}.get(res, res))

    counts = {k: outcomes.count(k)
              for k in ("assembled", "edit", "dropped", "environment", "deferred")}
    if thin:
        print(f"PLAN CHECK LOOP: {thin - unwritten} script(s) taken out before the check as "
              f"`pool_too_thin` ({THIN_TOPIC_TASK})"
              + (f", {unwritten} thin topic(s) never written recorded in skipped[] the same "
                 f"way (CF-0850)" if unwritten else ""))
    print(f"PLAN CHECK LOOP: {counts['assembled']} built, {counts['edit']} wait for an anchor "
          f"edit, {counts['deferred']} deferred for the thin-pool supplement, "
          f"{counts['dropped']} dropped (`{REASON_CODE}` or a claim refused on the plan), "
          f"{counts['environment']} could not be answered"
          + (f"; claims on the plan: {sum(1 for r in claims.values() if r == 'edit')} wait for "
             f"an edit ({CLAIMS_TASK})" if claims else ""))
    if counts["edit"]:
        return EXIT_EDIT
    if counts["deferred"]:
        return EXIT_DEFERRED
    if counts["dropped"] or thin:
        return EXIT_DROPPED
    if counts["environment"]:
        return EXIT_CANNOT_ANSWER
    return EXIT_OK


@runlog.script("content-researcher", "plan-check", name="plan_check_loop.py")
def cli():
    """The command-line entry (CF-0107): one start/done under step `plan-check`,
    and one `child` event per script (`tool: plan_check.py`) - the voice, the
    resolve and the plan, the expensive part of this stage since CF-0411."""
    sys.exit(main())


if __name__ == "__main__":
    # CF-0422: the read-only question asks nothing of the stage's runlog - it
    # is asked from outside the stage (the root's gate before compliance).
    if "--pending-after-supplement" in sys.argv[1:]:
        sys.exit(main())
    cli()

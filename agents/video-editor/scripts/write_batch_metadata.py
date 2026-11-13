#!/usr/bin/env python3
"""Assemble the batch's 05-video-editor.json from the plans and gate results.

`style_delivered`, `degradation` and `qc` are written on every run, including
clean ones. The Analyst will eventually correlate response against style, and a
run that does not record what it actually produced is a run that cannot be
learned from later.

CF-0041 adds the same shape for the pattern vocabulary: `pattern_requested` /
`pattern_delivered`, `rhythm_requested` / `rhythm_delivered`, and the cadence
that actually came out as numbers. The asymmetry matters more here than it does
for style, because degradation can quietly dissolve a rhythm: a video ordered as
`hold` whose held key frame was degraded has no hold in it, and recording the
order as if it were the outcome would teach the Analyst about a rhythm that was
never on screen. `build_render_plan.py` decides the verdict - it is the stage
that knows which blocks degraded - and this file reports it.

CF-0067 adds the third pair of the same shape, `meme_requested` /
`meme_delivered` (inserts/meme.json `metadata`), copied from plan["meme"]
and always present - `[]`/`[]` on a plan that ran no layer - plus this
layer's provenance records under `videos[].inserts[]`, merged beside
whatever the underlay layer (CF-0014) already wrote there for the same
video: its records and its `underlay` summary are kept from an existing
05-video-editor.json, the meme layer's own records are replaced, the way
underlay.write_stage_record() merges in the other direction.

CF-0068 adds the fourth pair, `sound_requested` / `sound_delivered`
(inserts/sound.json `metadata`), copied from plan["sound"] and always present
the same way, with the sound layer's provenance (`layer: "sound"`) merged
into the same `inserts[]` beside the meme's and the underlay's - each layer
replaces only its own records on a rerun.

CF-0127 makes `videos[].underlay` this stage's own record rather than
something only a previous write could carry: a plan that ran the layer
(every plan since CF-0127) answers for it through the factory's
`underlay.write_stage_record()` - `{applied, reason, id, file, treatment,
library, note}` plus its provenance (`layer: "underlay"`) in the same
`inserts[]` - and replaces what an earlier write of the record said, applied
or not.

CF-0434 adds the score log: `videos[].score` (the whole log of the video -
every real penalty, per stage, the remainder, the tier) and
`videos[].score_line` (one line, `B · 74 — −9 похожесть (3 блока), ...`), both
from `score_log.record_fields()` - the call a rebuild's record (CF-0416) makes
too. A video the score stopped under N is not in `videos[]`: its
`<plan stem>.score.refusal.json` puts it in `refusals[]` with the same line. Only a plan with no `underlay` key at all (built before the layer
existed) keeps the existing record untouched.

CF-0116 adds `comparison_line_delivered`: what our on-screen line actually
said and when, one entry per line the render carried ({fact_id, text,
start_s, end_s, block_index, source_url, source_url_from}), copied from
plan["comparison_lines"] and always present - `[]` on a video that carried
none. Symmetric with `pattern_delivered` (CF-0041) rather than with the
insert pairs: nothing requests this line - a fact that can carry one gets
one - so there is a delivered side and no requested side, and the reasons a
fact got none are the plan's notes. (CF-0186 moved the line off the
cancelled comparison beat and onto the script's `production_fact`; the field
name here is unchanged because the factory root reads it.)

CF-0117 adds `end_card_delivered`: the card that closed the video -
`{seconds, start_s, text, text_source, variant, logo_path}`, copied from
plan["end_card"] and always present, with `null` in all six keys on a plan
that predates the card or that was built without a `--channel`. Symmetric
with `pattern_delivered` too, and for the same reason: nothing requests the
card, every video gets one. `text_source` names the stance document and the
field the phrase came from (CF-0063), so the record can be checked against
the source rather than believed.

CF-0141 adds `ending_delivered` beside it: the channel's own finished clip -
`{path, seconds, source, variant}`, copied from the same plan["end_card"]
and always present, with `null` in all four keys on a video that closed on a
drawn card instead. The two fields are a pair, and exactly one of them is
filled on any video: `end_card_delivered` nulls out when the ending was the
channel's clip, `ending_delivered` nulls out when it was the floor the code
draws. Two fields rather than one renamed field so that a batch produced
before CF-0141 keeps meaning what it said.

CF-0153 adds `bed`: which background bed played - `{source,
ambient_name, ambient_path, ambient_source, ambient_loops,
ambient_gain_db}`, copied from plan["audio"]["bed"] and always present,
with `null` in all six keys on a plan that records no bed and in the four
`ambient_*` on a bed the generator made. CF-0165 adds `bed_db` and
`bed_db_source` (cli | config | default) beside them: at what level it
played and whether that level was the channel's setting, a flag somebody
typed, or the default nobody chose. `qc.bed` further down is how loud
the bed was; this is what it was. Before it, a video mixed with the
channel's own ambient file (CF-0153) and one mixed with the generated bed
left identical batch records.
CF-0271 adds four more, on the same promise of always-present keys:
`ambient_rotation_index` / `ambient_rotation_size` / `ambient_chosen_by`
(which of the channel's rotating beds played, out of how many, by what rule -
`null` on a channel that brings a single file), and `bed_substituted` - the
reason code when the generated bed played instead of the channel's file
(`no_channel_bed`, `operator_forced_generated`), `null` when nothing was
substituted. That last one is the field this task was filed over: a video
shipped on the generator 7 dB louder than the channel's chosen level, and the
record said only `source: "generated"`, which looks the same as an ordinary
run of a channel that has no bed.

CF-0071 adds the proof pair, `proof_requested` / `proof_delivered`
(inserts/proof.json `metadata`), copied from plan["proof"] the same way,
its provenance (`layer: "proof"`) merged into the same `inserts[]` and also
listed under `proofs[]` (the field the root's check_proof_provenance reads),
and `proof_capture_telemetry` when headless_browser was attempted.

CF-0118 adds `two_source_gate`: `{passed, count, required, canonical_ids,
aliased_away, mode, blocks_by_source, unidentified_blocks, note}`, copied
from plan["two_source_gate"] and always present - how many *independent*
footage sources are on screen (CF-0080 canonical ids, so three uploads of
one trailer count once) against the floor of two, and whether the channel
was measuring or enforcing. A plan built before the gate existed carries
`passed: null` / `mode: null`, never `true`. A measured gate contributes
nothing to `rhythm_shortfalls`: that stays CF-0057's rhythm record, and the
only gate deficit that is ever written belongs to a plan the `enforce` mode
refused (`plan.two-source-gate.json`, which no metadata run sees).

CF-0136 adds `picture`: `{blocks, picture_blocks, assetless_blocks,
assetless_seconds, longest_assetless_run_seconds, hold_ordered_seconds, runs}`,
copied from plan["rhythm"]["picture"] - how much of the video had anything on
screen at all. Its deficits reach `rhythm_shortfalls` as two new kinds,
`picture_absent_run` (a stretch of assetless blocks longer than the ordered
hold) and `picture_absent_blocks` (every assetless block, no threshold), so a
video that delivered its cadence over 25 stubs out of 30 no longer reports
`rhythm_delivered_fully: true`. A plan built before this carries `picture:
null`.

CF-0137 adds two more. `emergency_reuse` (from
plan["rhythm"]["emergency_reuse"]) is the one shot repeat a video is allowed
to spend rather than ship a block with no picture - `{budget, used, reuses}`,
and a third kind, `emergency_reuse`, in `rhythm_shortfalls`, because a
montage that showed the same frame twice is a video short of *material*, not
a video short of cadence. `assetless_rung` (from plan["assetless_rung"]) is
the gate under it: with the channel flag off - the default everywhere - a
block with no picture refuses the plan outright, so a video that reaches this
file at all passed. What happens to a refused video's registry entry is
CF-0139's.

CF-0290 adds `unresolved_anchors`, copied from plan["unresolved_anchors"],
which `build_render_plan.py` copies from the storyboard: one record per anchor
`resolve_anchors.gate_verdict()` could not call resolved, with the phrase and
the gates' own reasons. `null` on a plan from before the change, `[]` on a
video whose every anchor had a picture. It is the field DoD ролика item 3 is
audited by, and the one `unresolved_anchor` (plan_refusal) refuses a plan on
when a record in it says the block was filled under the similarity floor.

CF-0030 makes the file additive. It used to be written whole on every call,
so the natural pattern - one call per video, as each video comes out of the
loop - silently dropped every earlier record (batch 2026-08-31T2155Z lost
two of three videos; 2026-09-03T2037Z was hand-merged by the orchestrator to
avoid it). Now an existing `05-video-editor.json` is loaded and the output is
the union by `script_id`: this call's videos replace the records with the same
id (whole-record replace, on top of the per-layer `inserts[]`/`underlay`
merges above, which are fed from the record being replaced), every other
record is kept verbatim in its original position, new ids are appended in
`--video` order. The batch-level fields this stage owns (`batch_id`,
`channel`, `generated_at`, `pipeline_version`) are the current call's; any
other top-level field an earlier writer left - the orchestrator's
`merge_note`, notes - is preserved untouched, and `merge_log[]` gets one
`{at, videos, mode}` entry per call so a reader can see the file was built
incrementally. Every call says on stderr what it did with what was there.
`--replace-all` is the explicit way back to whole-file semantics, and the
only way past a `05-video-editor.json` that cannot be parsed: an unreadable
file is a hard error, never an overwrite. The write itself is a temp file in
the batch directory plus a rename, so a crash cannot leave half a file where
the registry's only recovery source should be (CF-0049).

CF-0254 adds the other half of the file: `refusals[]`. A script the Editor
refused *before* the render has no plan and no mp4, so it could never be a
`--video`, and the stage's convention used to be that it therefore had no
entry here at all - which is why batch 2026-09-16T2148Z, whose only script was
refused at the source badge gate, has no 05-video-editor.json and reads in the
funnel as `unexplained` / SILENT, the one outcome DoD 1.4.4 item 1 forbids.
The convention is now the other one: **a refused video has an entry in
`refusals[]` and no entry in `videos[]`**, `{script_id, reason_code, reason}`
plus the gate and the time (plan_refusal.py owns the shape). This call finds
those records by itself - each gate wrote one beside where its plan would have
been, under `<batch>/work/<slug>/` - so the operator runs this stage's last
step the same way whether the batch produced three videos or none, and
`--video` is no longer required. `--refusal` names one explicitly, for a plan
built outside the batch layout. A script that has a video record here is not
refused, whatever a stale sidecar from an earlier attempt says: the render
answered the question (the caller retries a rejected asset with another
candidate), so the video wins and the refusal is dropped at merge.

CF-0270 adds the one exception, and it is an exception to that last sentence
only. A refusal carrying `supersedes_video` was made on a *rebuild* of the plan
after a render - post-QC degradation reaches the Editor as `--degrade-block`,
and the pattern ceiling gate can refuse that rebuild. The mp4 beside it is the
attempt the refusal rejects, not a later attempt that answered the question, so
the video record is dropped instead of the refusal.

CF-0399 adds `code_shas` to every record this call writes: the code of the
factory at the moment this video's record was built, one entry per repo the
batch runs on (`runlog.factory_repos()`, CF-0398 - `root`, then every
`agents/<name>`), each `{"commit": <HEAD sha>, "dirty": bool}` - the shape of
the run header's `git` entries - or `null` for a directory that is not a git
repo. It is read from the repos' current HEAD, never from the `batch-start`
header: a rebuild after the run is built by whatever code is there then, and
that is what its record has to say. `dirty` is true when a tracked file was
modified or staged (untracked files never count; for the root, the records a
run writes itself - `runlog.RUN_DATA_PATHS` - do not either), so a video built
from uncommitted code is visible as such; `null` when the status could not be
read. `agents/video-editor` is the checkout this script runs from, which is
the code that built the video even when that is a worktree. A record this call
does not rewrite keeps the set it was written with. `code_shas: null` means
the factory's repos could not be read at all (no runlog library).

CF-0416 makes a rebuild's record this call's too. A rebuild
(`pipeline/rebuilds/<ts>`) is closed with the same
`write_batch_metadata.py pipeline/rebuilds/<ts> --video ...` as a batch, into
its own `pipeline/rebuilds/<ts>/05-video-editor.json` - with `videos[].score` /
`score_line` like any record. Its `channel` is the source batch's, read off the
copied `03-content-researcher.json` (else `01-trend-hunter.json`), never the
directory name `rebuilds` (`--channel` still wins), and the top-level
`rebuild_of` says which batch it was copied from: `{channel, batch_id, path,
read_from}` (`path` the source directory under `pipeline/` when it is still on
disk, else null), `null` on an ordinary batch. Before this a rebuild had no
05, and the frame-judge stage of `1757Z` hand-assembled one with `channel:
"rebuilds"`.

CF-0416 also ends the edit of `qc.passed`. `qc.failed_rules` names the rule of
each failure (`qc_cosmetic.rules_of`: `meme_caption_blank_blocks`,
`panel_cut_blocks`, ... or the gate's short name), `qc.cosmetic_rules` /
`qc.cosmetic_rules_source` the channel's list of cosmetic rules
(`channels/<id>.json#video_editor.qc_cosmetic_rules`, default
`["meme_caption_blank_blocks"]`). A video whose QC failed on those rules only
carries `judge_admitted_despite: [<rules>]` - the frame judge's candidate list
reads it - and `qc.passed` stays `false`; a video that passed, or failed on
anything else, has no such field.

Usage:
    write_batch_metadata.py <batch-dir> --video <script_id> <plan.json> <video.mp4>
      [--video ...] [--refusal <plan.refusal.json>] [--style-requested motion]
      [--replace-all | --new-only | --repair]

CF-0802 adds `--new-only`, the reserve round after the frame judge: the call
may only add entries for scripts 05 does not hold yet (`pending_scripts.py
<batch>` lists them). A `--video`/`--refusal` for a script_id already in
`videos[]` or `refusals[]` is refused (exit 2, nothing written), the refusal
sidecars of those scripts are not re-read, and a missing or unreadable 05 is
refused too. The merge itself is CF-0030's; `merge_log[].mode` says
`new-only`.

CF-0881 adds `--repair`, the one repair pass after the frame judge
(`repair_blocks.py`): the call may only rewrite rows `videos[]` already holds
- a `--video` whose script_id is not there (a new one, or one in
`refusals[]`) is refused, exit 2, nothing written; so is a `--refusal`, a
call with no `--video`, a missing or unreadable 05, and `--replace-all` or
`--new-only` beside it. The row is replaced in place (CF-0030's merge, its
position kept) and carries `repair` - `<plan dir>/repair/record.json` as
`repair_blocks.py` wrote it (`{task, at, blocks, replaced, changed_blocks}`).
No refusal sidecar is read in this mode: `refusals[]` stays as it is.
`merge_log[].mode` says `repair`; the retired-shot registry is synced as on
every write.
"""
import argparse
import contextlib
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# CF-0132: the qc gate is a sibling script; run_script() puts it under
# SIBLING_SCRIPT_TIMEOUT_SECONDS. `check=False` because the fallback
# below is for a gate that answered nothing - a gate that never
# answered raises instead, and must not arrive as that same verdict.
from common import run_script
import ambient_bed
import assetless_rung
import attempts
import batch_layout  # CF-0246: outputs stay in the batch directory
import comparison_line
import footage_credits  # CF-0664: videos[].footage_credits
import proof_quote_cap  # CF-0567: videos[].proof_quote_cap
import end_card
import meme_layer
import plan_refusal
import score_log  # CF-0434: the score log in videos[]
import proof_layer
import qc_cosmetic  # CF-0416: cosmetic QC failures, admission to the judge
import retired_shots
import sound_layer
import source_gate
import underlay_layer
import video_preview  # CF-0674: videos/<slug>.jpg beside the mp4
import voice_profile
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197, CF-0416

RUNGS = ["motion", "stills", "typographic"]


def qc_report(video, plan):
    out = run_script("qc_render.py", video, plan, "--json", check=False)
    return json.loads(out.stdout) if out.stdout.strip() else {"passed": False,
                                                              "failures": ["qc did not run"]}


def video_record(script_id, plan, mp4, qc, requested, existing_inserts=None,
                 existing_underlay=None, ledger=None, voice=None, cosmetic=None):
    """One videos[] record of 05-video-editor.json from a plan and its QC
    verdict. `requested` is the style ordered (None = the delivered one);
    `existing_inserts`/`existing_underlay` are what a previous write of the
    same record carried, so another layer's provenance survives a rerun.
    `ledger` (CF-0098) is the video's attempts.json, mirrored as `attempts`,
    `attempt_cap`, `attempts_exhausted` and `needs_you` - [] / None / False /
    None for a video that has no ledger. `voice` (CF-0188) is the channel's
    resolved voice profile; None means no channel was named, which reads as
    the default voice - the same reading synthesize_voiceover.py gives.
    `cosmetic` (CF-0416) is qc_cosmetic.load()'s answer for the channel;
    None reads as qc_cosmetic.DEFAULT_RULES."""
    delivered = plan["style"]
    if cosmetic is None:
        cosmetic = qc_cosmetic.load(None)
    requested = requested or delivered

    # CF-0031: degradation is per-block, not per-video, so the record has
    # to say which blocks and why - not collapse to one "style_delivered"
    # covering a whole video that may be mostly untouched. `degraded_blocks`
    # comes straight from build_render_plan.py's --degrade-block (fed from
    # qc_render.py's frozen_blocks()); it is empty on a clean run and on
    # the escape-valve whole-video rung drop (handled below, unchanged).
    degraded_blocks = plan.get("degraded_blocks", [])
    degradation = []
    if degraded_blocks:
        for d in degraded_blocks:
            degradation.append({
                "block_index": d["index"],
                "from": d["from"],
                "to": d["to"],
                "reason": d.get("reason") or "failed post-render QC",
            })
        n = len(degraded_blocks)
        total = len(plan.get("blocks", []))
        delivered = f"{requested} (mixed: {n}/{total} block(s) degraded)"
    elif requested != delivered:
        # Whole-video fallback, still supported for the case CF-0031
        # explicitly carves out: per-block degradation left zero
        # surviving clip/still blocks, so the whole plan genuinely
        # dropped a rung (or more) rather than one segment of it.
        try:
            span = RUNGS[RUNGS.index(requested):RUNGS.index(delivered) + 1]
            for a, b in zip(span, span[1:]):
                degradation.append({"from": a, "to": b,
                                    "reason": "; ".join(plan.get("notes", []))
                                              or "no usable asset for this rung"})
        except ValueError:
            degradation.append({"from": requested, "to": delivered,
                                "reason": "styles are not on the same chain"})

    # CF-0041. Absent on a plan built before this existed, and absent is
    # not "even": a plan that never recorded a rhythm cannot claim one, so
    # the fields say null rather than guessing the baseline.
    r = plan.get("rhythm") or {}
    cadence = r.get("cadence") or {}
    # CF-0071: the proof pair (inserts/proof.json `metadata`) - always both
    # lists, [] when the plan ran no layer, the same promise as the meme's -
    # plus this layer's provenance records under `proofs` and, when
    # headless_browser was attempted, `proof_capture_telemetry`.
    proof_requested, proof_delivered, proof_records, proof_telemetry = proof_layer.stage_fields(plan)
    # CF-0193: recomputed from the pair rather than copied, so a plan built
    # before the fields existed answers too - the pair is what a video really
    # shipped and the three fields are a reading of it, not a second source.
    proof_short = proof_layer.proof_shortfalls(proof_requested, proof_delivered)
    # CF-0067: the pair is always present ([] when the plan ran no layer -
    # inserts/meme.json `metadata`: absence never has to be interpreted),
    # and this layer's provenance is merged beside any other layer's.
    meme_requested, meme_delivered, meme_inserts = meme_layer.stage_fields(plan)
    # CF-0068: the fourth pair, same promise.
    sound_requested, sound_delivered, sound_inserts = sound_layer.stage_fields(plan)
    # CF-0116 / CF-0186: the delivered side of the on-screen fact line, always a
    # list. A rerun over the same plan writes the same list - the plan is the
    # only source, nothing here accumulates.
    comparison_lines = comparison_line.stage_fields(plan)
    # CF-0117: what the end card actually delivered - the seconds, where it
    # started, the phrase (null when the channel signs with none, CF-0186)
    # and the file it was read from, the variant
    # and the logo (null on the typographic one). Always present, all six
    # keys: a plan that predates the card, or one built without a --channel
    # to read the phrase from, gets the six keys with null in each rather
    # than a missing field. `text_source` is the point of the record - it is
    # what lets a reader check the card against the stance document instead
    # of trusting that the phrase was not typed in somewhere.
    end_card_delivered = end_card.stage_fields(plan)
    # CF-0141: and the other half of the same answer - the channel's clip.
    # Both are always written; exactly one of them carries values.
    ending_delivered = end_card.ending_stage_fields(plan)

    record = {
        "script_id": script_id,
        "output_path": str(Path(mp4).resolve()),
        "style_requested": requested,
        "style_delivered": delivered,
        "degradation": degradation,
        "proof_requested": proof_requested,
        "proof_delivered": proof_delivered,
        "proofs": proof_records,
        # CF-0193, the same three fields CF-0192 gave the pattern and for the
        # same reason: a proof ordered and not on the screen leaves a code and
        # a decision here, never a silence. `proof_delivered_fully` is true
        # when nothing was ordered - a video nobody asked a proof of is not
        # short of one.
        "proof_not_delivered": proof_layer.proof_not_delivered_code(proof_short),
        "proof_shortfalls": proof_short,
        "proof_delivered_fully": not proof_short,
        "pattern_requested": r.get("pattern_requested"),
        "pattern_delivered": r.get("pattern_delivered"),
        # CF-0192: the reason code beside the verdict, so the assignment
        # registry (CF-0040/CF-0049) joins on a fact instead of guarding a
        # fiction. Absent on a plan built before this existed: `null` reads
        # there as "not recorded", which is what it is - and on a plan that
        # has the field, `null` means delivered and nothing else.
        "pattern_not_delivered": r.get("pattern_not_delivered"),
        "pattern_shortfalls": r.get("pattern_shortfalls", []),
        "pattern_delivered_fully": r.get("pattern_delivered_fully"),
        # CF-0245: what the editor did about a block held past the top of the
        # hold band - trimmed it to the band and handed the remainder on, or
        # refused because the next block had no footage for it. Carried here
        # beside `pattern_shortfalls` because the pair is the whole answer: an
        # entry with `applied: false` next to a `hold_outside_band` shortfall
        # is the montage saying it could not fix that one without freezing a
        # frame (CF-0249), which is a different fact from a video nobody tried
        # to fix. Empty list on a plan that had no over-band block, and on one
        # built before the trim existed - the distinction that matters to a
        # reader is carried by the shortfall beside it, not by this list's
        # absence.
        "hold_band_trims": r.get("hold_band_trims", []),
        # CF-0276: the band asked of the *layout*, before any clip was cut.
        # Carried whole rather than as a boolean because the two numbers in it
        # are what the Analyst and the writer's side of this defect need:
        # `breaches` (empty on a layout that fitted) and
        # `lead_before_first_anchor`, the screen time in front of the script's
        # first anchor. `null` on a plan built before the layout answered -
        # not an empty record, which would read as "the layout fitted".
        "hold_ceiling": r.get("hold_ceiling"),
        "rhythm_requested": r.get("rhythm_requested"),
        "rhythm_delivered": r.get("rhythm_delivered"),
        "opening_requested": r.get("opening_requested"),
        "opening_delivered": r.get("opening_delivered"),
        "cadence": cadence,
        "rhythm_deviations": r.get("deviations", []),
        # CF-0057: a rhythm can be in the video and still not be fully
        # executed - `alternate` that crossed the axis exactly where the
        # script did and then held one frame for 15s inside a run. The
        # deviations list carries the sentence; these two carry the same
        # thing as numbers, which is what the Analyst (CF-0023) joins on.
        # Absent on a plan built before this existed: `null`, not `true` -
        # a plan that never measured its runs cannot claim they were short
        # or that they were fine.
        "rhythm_delivered_fully": r.get("rhythm_delivered_fully"),
        "rhythm_shortfalls": r.get("rhythm_shortfalls", []),
        # CF-0118: how many independent footage sources (CF-0080 canonical,
        # so three uploads of one trailer count once) are actually on
        # screen, and in which mode that was judged. Always present, copied
        # from plan["two_source_gate"] - a plan built before the gate
        # existed gets `passed: null` / `mode: null` rather than an absent
        # key, because a video that never counted its sources cannot claim
        # it had two. This record is the whole of what a `measure` run
        # reports: `rhythm_shortfalls` above stays CF-0057's rhythm list and
        # gets no `two_source_gate` entry, because a measured plan was
        # returned to nobody. The deficit exists only where the gate
        # enforced, and there the plan was refused - it is in that batch's
        # `plan.two-source-gate.json`, not in any video's metadata.
        "two_source_gate": source_gate.stage_fields(plan),
        # CF-0567: the vendor quotes against the channel's caps, and a demo's
        # own footage - `null` on a plan built before CF-0567.
        proof_quote_cap.FIELD: proof_quote_cap.stage_fields(plan),
        "side_runs": r.get("side_runs"),
        # CF-0120: which crossings of the axis were assembled from several
        # distinct shots, and out of what - the provenance that tells the
        # Analyst a side stopped being one frozen frame because the montage
        # cut inside it, not because the run got shorter. `[]` on a video
        # where every crossing had one shot long enough, `null` on a plan
        # built before this existed: same distinction as `side_runs` above.
        "swing_block_shots": r.get("swing_block_shots"),
        # CF-0136: the same measurement for the other failure - how many of
        # this video's blocks put anything on screen at all, and the longest
        # stretch that put nothing there. `null` on a plan built before this
        # existed, never a zero: a plan that never counted its assetless
        # blocks cannot claim it had none. The deficits themselves are two
        # more kinds in `rhythm_shortfalls` above, carried like the rest.
        "picture": r.get("picture"),
        # CF-0137: the video's one emergency shot repeat, if it spent it -
        # which block, which shot, where else that shot is on screen. `null`
        # on a plan built before this existed, never `{"used": 0}`: a plan
        # that never had the rung cannot claim it did not need it. The
        # deficit itself is an `emergency_reuse` entry in
        # `rhythm_shortfalls` above, carried like every other kind.
        "emergency_reuse": r.get("emergency_reuse"),
        # CF-0137: whether any block of this video shipped with no picture
        # at all, and whether the channel allows the per-block assetless
        # rung. Always present (`assetless_rung.stage_fields()` fills in a
        # `passed: null` record for a plan built before the gate), because a
        # video that was never checked must not read as a video that passed.
        # A *refused* video has no plan and therefore no entry in `videos[]` -
        # since CF-0254 it has one in `refusals[]` instead, carrying the gate's
        # code and sentence, beside the machine-readable deficit the gate wrote
        # (`plan.assetless-rung.json`, `plan.two-source-gate.json`).
        "assetless_rung": assetless_rung.stage_fields(plan),
        # CF-0330: every gate this video went past with a warning instead of a
        # refusal (the user, 2026-09-23) - the plan's own records, gate id,
        # funnel code, sentence and numbers. `[]` when nothing warned, `null`
        # on a plan built before warnings existed.
        plan_refusal.WARNINGS_FIELD: (plan or {}).get(plan_refusal.WARNINGS_FIELD),
        "held_frames": r.get("held_frames", []),
        comparison_line.DELIVERED_FIELD: comparison_lines,
        # CF-0664 (VE-1): one row per judged footage source the blocks really
        # show, in order of first use - its licence, the credit (a concrete
        # line only when the file carried one, or a vendor quote's channel title
        # - CF-0686; else `credit: null` and
        # `credit_missing`), `attribution`, `on_screen`/`where`, `share_alike`,
        # `license_url`, `source_url`, and the on-screen credit drawn over it
        # (`overlay`). The Publisher's card reads it (PUB-1). `[]` when no
        # source on screen was judged (ExampleFilm), `null` on a plan built
        # before CF-0664.
        footage_credits.FIELD: footage_credits.stage_fields(plan),
        # CF-0567: the factory's own recordings on screen (no credit row) -
        # page, host, the Space's licence, blocks; `[]` when none, `null` on
        # a plan built before CF-0567.
        footage_credits.OWN_CAPTURES_FIELD: footage_credits.own_capture_stage_fields(plan),
        end_card.DELIVERED_FIELD: end_card_delivered,
        end_card.ENDING_DELIVERED_FIELD: ending_delivered,
        "meme_requested": meme_requested,
        "meme_delivered": meme_delivered,
        # CF-0138: the other half of the meme layer, and deliberately not
        # inside the pair above. The pair is the answer to what the *writer*
        # asked for (inserts/meme.json `absent_means`: a script with no
        # reactions gets two empty lists, and that promise is not being
        # bent); this is the rung of the CF-0137 ladder where a block with no
        # picture is given one nobody asked for. Which blocks were holes,
        # which the library closed and why the rest went on. Always present -
        # `hole_fill_fields()` fills in a record for a plan built before the
        # rung existed, so a video that was never offered it does not read as
        # a video that had no holes.
        "meme_hole_fill": meme_layer.hole_fill_fields(plan),
        "sound_requested": sound_requested,
        "sound_delivered": sound_delivered,
        "inserts": proof_layer.merge_inserts(
            sound_layer.merge_inserts(
                meme_layer.merge_inserts(existing_inserts, meme_inserts), sound_inserts),
            proof_records),
        "duration": plan["duration"],
        # CF-0290: the anchors the resolver could not picture, exactly as the
        # storyboard wrote them and the plan carried them. A shipped video is
        # the only place DoD ролика item 3 can be audited after the fact - the
        # batch's work/ directory does not survive the rotation - and until now
        # delver.mp4 was recorded with `degradation: []`, `needs_you: null` and
        # nothing at all about the two phrases whose pictures were of something
        # else. `[]` says the resolver looked and found none; a missing key
        # (plan from before CF-0290) is `null` and says nobody asked.
        "unresolved_anchors": plan.get("unresolved_anchors"),
        # CF-0153 (section E): which bed played. `qc.bed` below is how
        # loud it was; this is what it was - the generator, or the
        # channel's own ambient file by name, where that file was found,
        # how many times it had to loop and how far it was lifted to sit
        # where the generated bed sits. Six keys, always all of them.
        "bed": ambient_bed.bed_record_fields(plan),
        "qc": {
            "passed": qc["passed"],
            "failures": qc.get("failures", []),
            "notes": qc.get("notes", []),
            # CF-0416: the rule each failure is on (qc_cosmetic.rules_of),
            # in the order of `failures`, and the channel's cosmetic list it
            # was read against - `judge_admitted_despite` below is decided
            # from exactly these, and `passed` above is never rewritten.
            qc_cosmetic.RULES_FIELD: qc_cosmetic.rules_of(qc.get("failures", [])),
            "cosmetic_rules": list(cosmetic["rules"]),
            "cosmetic_rules_source": cosmetic["source"],
            "thresholds": plan.get("qc_thresholds", {}),
            # CF-0025: the bed's measurement travels into the batch record.
            # It did not before, so `bed_rms_db` read as absent in all four
            # entries of 2026-09-03T2037Z's report while two of the four had
            # a real number in work/<slug>/qc.log and two were genuinely
            # null - three different states that all looked the same here.
            "bed": {k: qc.get("measured", {}).get(k) for k in
                    ("bed_rms_db", "bed_rms_window", "bed_rms_floor_db",
                     "bed_declared")},
            # CF-0327 / CF-0320: what the panel gate measured and which mode
            # it ran in. The batch record is the frozen artefact `runlog
            # gate-price --rule video_editor.panel_in_frame` replays over, so
            # the measurement has to be here on every video - including the
            # ones the gate passed, which are exactly the videos a price is
            # the count of. A `null` is a render from before this gate and
            # reads as `no basis`, never as a price of zero.
            "panel_in_frame": {
                "mode": qc.get("measured", {}).get("panel_gate_mode"),
                "blocks": qc.get("measured", {}).get("panel_blocks"),
                "cut_blocks": qc.get("measured", {}).get("panel_cut_blocks"),
                # CF-0894: sequence cuts' cut-off panels, measured only
                "cut_sequence_blocks": qc.get("measured", {}).get(
                    "panel_cut_sequence_blocks"),
            },
        },
        # CF-0188: built from the channel's own voice_profile through the
        # same resolver the synthesis used, not a literal typed in here. It
        # was a literal until the field became real, and a literal is a claim
        # about a wav nobody checked - a channel that changed its voice would
        # still have been recorded as reading in am_puck.
        "voice_profile_used": voice_profile.describe(voice or voice_profile.resolve(None)),
        "assets": [
            {
                "kind": b["asset"]["kind"],
                "src": b["asset"].get("src"),
                "resolution": b["asset"].get("source_size"),
                "roi_source": b["asset"].get("roi_source"),
                "coverage": b["asset"].get("coverage"),
                # CF-0327: where the window was pointed, and the shot's own
                # inset panel when it has one. `focus` travels because a
                # replay of the panel gate over this record has to be able to
                # rebuild the delivered window, and until now the one number
                # that fixes it was only in the batch's `work/`, which the
                # rotation deletes.
                "focus": b["asset"].get("focus"),
                "panel": b["asset"].get("panel"),
                "intent": b.get("intent", ""),
                # A card has no file and no measurements - what it is, is
                # its text. A still marked held_frame is one the rhythm
                # asked for, not one degradation produced; without the flag
                # the two are the same row here (CF-0041).
                "text": b["asset"].get("text"),
                "card_kind": b["asset"].get("card_kind"),
                "held_frame": bool(b.get("held_frame")),
                "side": b.get("side"),
                "insert": (b.get("insert") or {}).get("kind"),
                # CF-0068: the id of the sound whose anchor fell in this block
                # (recorded, never chosen - the block's picture is unchanged).
                "sound": (b.get("sound") or {}).get("asset_id"),
            }
            for b in plan["blocks"]
        ],
    }
    # CF-0098: how many times this video was built and whether the stage
    # gave up on it. `needs_you` is the stage's own stop signal - the record
    # carries it so the operator's report and the batch agree on which video
    # is waiting for a human.
    record.update(attempts.record_fields(ledger))
    # CF-0416: QC failed, and only on rules the channel calls cosmetic - the
    # video is a candidate for the frame judge, said by this field and never
    # by `qc.passed: true`. No field at all on a video that passed QC or that
    # failed on anything else.
    admitted = qc_cosmetic.admitted_despite(qc, cosmetic)
    if admitted:
        record[qc_cosmetic.FIELD] = admitted
    if proof_telemetry is not None:
        record["proof_capture_telemetry"] = proof_telemetry
    # CF-0127: the second plane's own record, written by the factory's
    # `underlay.write_stage_record()` (the module that owns the shape):
    # `underlay` - applied, why, which file, how it was treated - and this
    # layer's provenance merged into the `inserts[]` above beside the meme's,
    # the sound's and the proof's. A plan that ran the layer answers for it,
    # applied or not, and replaces whatever a previous write of this record
    # said about the underlay; only a plan built before the layer existed
    # (no `underlay` key at all) falls back to what was already there.
    if plan.get("underlay") is not None:
        underlay_layer.write_stage_record(record, plan)
    elif existing_underlay is not None:
        record["underlay"] = existing_underlay
    return record


def ledger_for_plan(plan_path):
    """The attempts.json beside a plan under <batch>/work/<slug>/, else None."""
    found = attempts.batch_context(plan_path)
    if not found:
        return None
    batch_dir, slug = found
    if not attempts.ledger_path(batch_dir, slug).exists():
        return None
    return attempts.load(batch_dir, slug)


DEST_NAME = "05-video-editor.json"
MERGE_LOG_FIELD = "merge_log"
CODE_FIELD = "code_shas"

# CF-0416: a rebuild (`pipeline/rebuilds/<ts>`) is a batch copied from another
# one, and its directory's parent names no channel. The copied records do:
# `03`/`01` are copied byte for byte, so their `channel` and `batch_id` are the
# source batch's. `rebuild_of` is the top-level field that says so.
REBUILDS_GROUP = "rebuilds"
REBUILD_FIELD = "rebuild_of"
REBUILD_SOURCE_RECORDS = ("03-content-researcher.json", "01-trend-hunter.json")


def rebuild_source(batch_dir):
    """CF-0416: `{channel, batch_id, path, read_from}` of the batch a rebuild
    was copied from, read off the rebuild's copied `03`/`01`; None for a batch
    that is not under `pipeline/rebuilds/`, and `{channel: None, ...}` for a
    rebuild whose copied records name no channel (the caller says so aloud).

    `channel` is the current id (a record frozen under a former id is
    resolved, CF-0197); `path` is the source batch directory relative to the
    factory root when it is still on disk under either name, else None."""
    batch_dir = Path(batch_dir).resolve()
    if batch_dir.parent.name != REBUILDS_GROUP:
        return None
    for name in REBUILD_SOURCE_RECORDS:
        try:
            doc = json.loads((batch_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        channel = resolve_channel(str(doc.get("channel") or ""))
        if not channel:
            continue
        frozen = str(doc["channel"])
        source = doc.get("batch_id")
        path = None
        pipeline = batch_dir.parent.parent
        for cand in dict.fromkeys((frozen, channel)):
            if source and (pipeline / cand / str(source)).is_dir():
                path = f"{pipeline.name}/{cand}/{source}"
                break
        return {"channel": channel, "batch_id": source, "path": path, "read_from": name}
    return {"channel": None, "batch_id": None, "path": None, "read_from": None}
# This repo's own label in runlog.factory_repos() and its checkout: the one
# this script runs from (a worktree included), not <root>/agents/video-editor.
EDITOR_LABEL = "agents/video-editor"
EDITOR_REPO = Path(__file__).resolve().parent.parent


def code_shas(root=None):
    """CF-0399: {label: {"commit", "dirty"} | None} of every factory repo, read
    now. None when the runlog library (factory_repos/repo_state, CF-0398) is
    not there. Never raises - the record of a video must not be lost to it."""
    repos_of = getattr(runlog, "factory_repos", None)
    state_of = getattr(runlog, "repo_state", None)
    if repos_of is None or state_of is None:
        return None
    try:
        repos = [(label, EDITOR_REPO if label == EDITOR_LABEL else d)
                 for label, d in repos_of(root)]
        # One git process costs ~0.2 s here and a repo takes four; read the
        # repos side by side so a call costs one repo, not the factory.
        with ThreadPoolExecutor(max_workers=max(1, len(repos))) as pool:
            states = list(pool.map(lambda r: state_of(*r), repos))
        out = {}
        for (label, _), st in zip(repos, states):
            if not st.get("git"):
                out[label] = None
                continue
            dirty = st.get("dirty")
            out[label] = {"commit": st.get("head"),
                          "dirty": None if dirty is None else bool(dirty)}
        return out
    except Exception as e:                                  # noqa: BLE001
        print(f"METADATA: WARNING: code SHAs not read (CF-0399): "
              f"{e.__class__.__name__}: {e}", file=sys.stderr)
        return None


class UnreadableMetadata(Exception):
    """An existing 05-video-editor.json that cannot be merged into.

    Raised instead of overwriting: this file is the only recovery source for
    the registry's production columns (CF-0049), so "I could not read it" must
    never resolve to "so I replaced it". `--replace-all` is the way past it.
    """


def read_existing(dest):
    """The existing 05-video-editor.json as (document, videos[]).

    Anything that is not this stage's document - unparseable JSON, a top level
    that is not an object, no `videos` list, a record with no `script_id` to
    merge on, a `refusals` that is not a list (CF-0254) - raises
    UnreadableMetadata."""
    try:
        with open(dest) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        raise UnreadableMetadata(str(e)) from e
    if not isinstance(doc, dict):
        raise UnreadableMetadata(f"top level is {type(doc).__name__}, not an object")
    videos = doc.get("videos")
    if not isinstance(videos, list):
        raise UnreadableMetadata("no `videos` list")
    for i, v in enumerate(videos):
        if not isinstance(v, dict) or not v.get("script_id"):
            raise UnreadableMetadata(f"videos[{i}] has no script_id to merge on")
    refusals = doc.get(plan_refusal.FIELD)
    if refusals is not None and not isinstance(refusals, list):
        raise UnreadableMetadata(f"`{plan_refusal.FIELD}` is "
                                 f"{type(refusals).__name__}, not a list")
    return doc, videos


def merge_videos(existing, written):
    """The union by `script_id`: (videos, replaced_ids).

    A record this call wrote replaces the existing record with the same id
    whole - field for field, the new one wins, including fields the old one
    had and the new one does not. What survives from the old record does so
    through `video_record()`, which was fed its `inserts[]` and `underlay`
    (each layer replaces only its own provenance records; a plan built before
    the underlay layer keeps the existing summary) - so the per-layer merges
    happen inside the replacing record, not around it.

    Everything else keeps its content and its position. Ids this call wrote
    that the file did not have are appended in `--video` order. An existing
    file carrying the same id twice (a hand-merge accident) collapses to one
    record only where this call replaces that id."""
    new = {v["script_id"]: v for v in written}
    out, replaced = [], []
    for v in existing:
        sid = v.get("script_id")
        if sid in new:
            if sid in replaced:
                continue    # this id is already in `out`, replaced once
            replaced.append(sid)
            out.append(new[sid])
        else:
            out.append(v)
    for v in written:
        if v["script_id"] not in replaced:
            out.append(v)
    return out, replaced


def write_atomic(dest, doc):
    """Temp file in the destination's own directory, fsync, rename.

    A crash mid-write leaves either the old file or the new one, never a
    truncated one - and no temp file behind."""
    fd, tmp = tempfile.mkstemp(dir=str(Path(dest).parent), prefix=f".{Path(dest).name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def bad_video_args(videos):
    """CF-0778: what is wrong with the `--video SCRIPT_ID PLAN MP4` triples,
    one line each; empty when nothing is.

    Batch example-tech/2026-10-16T0839Z called this stage four times with
    `--video "lf-...-001-script1 homeview" <batch>/work//plan.json
    <batch>/videos/.mp4`: the operator's loop held "<script_id> <slug>" in
    one variable and split it with `set -- $pair`, which zsh does not do for
    an unquoted parameter - so the id carried the slug and the slug was
    empty. The call died on a bare FileNotFoundError for `work//plan.json`.
    It is refused here instead, before anything is read or written, with the
    cause named. Of the files, only the plan is required to exist here -
    the record is built from it; the mp4 path is checked for its shape only."""
    out = []
    for script_id, plan, mp4 in videos:
        if not script_id.strip():
            out.append(f"--video has an empty script id (plan {plan!r})")
        elif any(c.isspace() for c in script_id):
            out.append(
                f"--video script id {script_id!r} contains whitespace - the script id "
                f"and the slug were passed as one word (zsh does not split an "
                f"unquoted $var; pass <script_id> <plan> <mp4> as three words)")
        for what, path in (("plan", plan), ("mp4", mp4)):
            # `//` past a leading `//` is an empty path segment: a slug that
            # was empty when the path was built (`work/$slug/plan.json`).
            if "//" in path.lstrip("/") or Path(path).stem in ("", ".mp4"):
                out.append(f"--video {what} path {path!r} has an empty segment - "
                           f"the slug was empty when it was built "
                           f"(expected work/<slug>/plan.json, videos/<slug>.mp4)")
        if not Path(plan).is_file():
            out.append(f"--video plan {plan!r} does not exist")
    return out


NEW_ONLY_MODE = "new-only"
REPAIR_MODE = "repair"
REPAIR_FIELD = "repair"
REPAIR_TASK = "CF-0881"
# beside the plan: what repair_blocks.py re-picked, stamped on the row
REPAIR_RECORD = Path("repair") / "record.json"


def repair_guard(batch_dir, args):
    """CF-0881: the `script_id`s of videos[] this call rewrites, or exit 2
    with nothing written. The repair pass after the frame judge replaces the
    row of a video it re-rendered - never adds one, never touches a refusal."""
    dest = Path(batch_dir) / DEST_NAME
    lines = []
    for flag, on in (("--replace-all", args.replace_all), ("--new-only", args.new_only)):
        if on:
            lines.append(f"{flag} and --repair together: the repair pass rewrites the "
                         f"rows of the videos it re-rendered and nothing else")
    if args.refusal:
        lines.append("--refusal with --repair: the repair pass records re-rendered "
                     "videos only - refusals[] stays as the first pass wrote it")
    if not args.video:
        lines.append("--repair with no --video: nothing to rewrite")
    have = set()
    if not dest.exists():
        lines.append(f"{dest} does not exist - --repair rewrites a row of a first "
                     f"pass, and there is none")
    else:
        try:
            _doc, vids = read_existing(dest)
        except UnreadableMetadata as e:
            lines.append(f"{dest} cannot be merged into ({e})")
        else:
            have = {v["script_id"] for v in vids}
            for script_id, _, _ in args.video:
                if script_id not in have:
                    lines.append(f"--video {script_id}: videos[] of 05 holds no row for "
                                 f"it - a repair rewrites a rendered video's row, it "
                                 f"never adds one")
    if lines:
        for line in lines:
            print(f"METADATA: ERROR: {line}", file=sys.stderr)
        print("METADATA: ERROR: nothing written (CF-0881, --repair)", file=sys.stderr)
        sys.exit(2)
    return {sid for sid, _, _ in args.video}


def repair_record(plan_path, now=None):
    """CF-0881: the row's `repair` field - `<plan dir>/repair/record.json`
    when repair_blocks.py wrote one, else the bare stamp."""
    p = Path(plan_path).parent / REPAIR_RECORD
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = None
    if not isinstance(rec, dict):
        rec = {"task": REPAIR_TASK, "at": now, "blocks": None}
    rec.setdefault("task", REPAIR_TASK)
    rec.setdefault("at", now)
    return rec


def new_only_guard(batch_dir, args):
    """CF-0802: the `script_id`s 05 already holds (videos[] and refusals[]),
    or exit 2 with nothing written when this call would rewrite one of them.

    The reserve round after the frame judge renders only the scripts 05 has
    no entry for (`pending_scripts.py`); every entry already there is the
    first pass's, and the frame judge has judged its video. A `--video` or
    `--refusal` naming one of those ids is the model about to replace a
    judged record silently - refused, not skipped. A missing 05 (no first
    pass), an unreadable one, or `--replace-all` beside `--new-only` is
    refused the same way."""
    dest = Path(batch_dir) / DEST_NAME
    lines = []
    if args.replace_all:
        lines.append("--replace-all and --new-only together: the round after the "
                     "frame judge never rewrites the whole file")
    held = set()
    if not dest.exists():
        lines.append(f"{dest} does not exist - --new-only merges into a first "
                     f"pass, and there is none (run without --new-only)")
    else:
        try:
            doc, vids = read_existing(dest)
        except UnreadableMetadata as e:
            lines.append(f"{dest} cannot be merged into ({e})")
        else:
            held = {v["script_id"] for v in vids}
            held |= {r.get("script_id") for r in doc.get(plan_refusal.FIELD) or []
                     if isinstance(r, dict) and r.get("script_id")}
    for script_id, _, _ in args.video:
        if script_id in held:
            lines.append(f"--video {script_id}: 05 already holds an entry for it - "
                         f"the first pass is final, it is not re-rendered or rewritten")
    for path in args.refusal:
        rec = plan_refusal.read(path)
        if rec is not None and rec["script_id"] in held:
            lines.append(f"--refusal {path}: 05 already holds an entry for "
                         f"{rec['script_id']} - the first pass is final")
    if lines:
        for line in lines:
            print(f"METADATA: ERROR: {line}", file=sys.stderr)
        print("METADATA: ERROR: nothing written (CF-0802, --new-only) - this mode "
              "only adds the scripts `pending_scripts.py <batch>` lists",
              file=sys.stderr)
        sys.exit(2)
    return held


def main():
    p = argparse.ArgumentParser()
    p.add_argument("batch_dir")
    # CF-0254: not required any more. A batch whose every script was refused
    # before the render has no plan and no mp4 to name here, and it is exactly
    # the batch whose 05-video-editor.json has to exist - `refusals[]` is the
    # whole of what it says.
    p.add_argument("--video", nargs=3, action="append", metavar=("SCRIPT_ID", "PLAN", "MP4"),
                   default=[])
    p.add_argument("--refusal", action="append", default=[], metavar="REFUSAL_JSON",
                   help="CF-0254: a `<plan>.refusal.json` written by a gate of "
                        "build_render_plan.py. Repeatable, and rarely needed: every "
                        "such file under <batch>/work/*/ is found without it.")
    p.add_argument("--style-requested", default=None)
    p.add_argument("--channel", default=None)
    p.add_argument("--batch-id", default=None)
    p.add_argument("--retired-shots", default=None, metavar="PATH",
                   help="CF-0397: the channel's retired-shots registry. Default "
                        "pipeline/<channel>/retired-shots.json for a batch under "
                        "pipeline/; a batch parked anywhere else writes none.")
    p.add_argument("--acceptance-log", default=None, metavar="PATH",
                   help="CF-0523: the user's verdicts the retired-shots sync reads. "
                        "Default $ACCEPTANCE_LOG, else <root>/publish/acceptance-log.json")
    p.add_argument("--replace-all", action="store_true",
                   help="CF-0030: write the whole file from this call alone, dropping every "
                        "record the existing file has. The only way past an unreadable file.")
    p.add_argument("--new-only", action="store_true",
                   help="CF-0802: the reserve round after the frame judge. Every entry "
                        "05 already holds is final: a --video or --refusal for a "
                        "script_id 05 names in videos[] or refusals[] is refused (exit 2, "
                        "nothing written), and the refusal sidecars of those scripts are "
                        "not re-read. Needs an existing, readable 05.")
    p.add_argument("--repair", action="store_true",
                   help="CF-0881: the repair pass after the frame judge "
                        "(repair_blocks.py). Each --video must be a row videos[] "
                        "already holds; it is rewritten in place and carries "
                        "`repair` (<plan dir>/repair/record.json). No refusal "
                        "sidecar is read; anything else is refused (exit 2).")
    args = p.parse_args()
    batch_dir = Path(args.batch_dir)
    # CF-0778: a malformed `--video` (an empty slug, an id carrying the slug)
    # stops here with its cause, not later on a FileNotFoundError.
    bad = bad_video_args(args.video)
    if bad:
        for line in bad:
            print(f"METADATA: ERROR: {line}", file=sys.stderr)
        print("METADATA: ERROR: nothing written (CF-0778) - call it as "
              "`--video <script_id> <batch>/work/<slug>/plan.json "
              "<batch>/videos/<slug>.mp4`", file=sys.stderr)
        sys.exit(2)
    # CF-0246: a plan or mp4 in a checkout's work/ or videos/ instead of the
    # batch is the 2026-09-15T1034Z shape - relative paths resolved against
    # the operator's working directory. Refused before anything is read or
    # written, so the record never points outside the batch.
    leaked = batch_layout.leaked_paths(
        batch_dir, [p for _, plan, mp4 in args.video for p in (plan, mp4)])
    if leaked:
        print(batch_layout.leak_message(batch_dir, leaked), file=sys.stderr)
        sys.exit(2)
    # CF-0802: in the round after the frame judge the first pass is final -
    # refused here, before anything is read or written, when a call would
    # rewrite an entry 05 already holds.
    # CF-0881: the repair pass rewrites only the rows of what it re-rendered.
    repairing = repair_guard(batch_dir, args) if args.repair else None
    held = new_only_guard(batch_dir, args) if args.new_only else None
    # CF-0254: the gates' own records - every sidecar under <batch>/work/*/,
    # plus any named on the line for a plan built outside that layout. Read
    # before anything else so that a call with neither videos nor refusals
    # stops here: an empty 05-video-editor.json is a file that says a batch
    # produced nothing *and* refused nothing, which no run of this stage can
    # honestly claim.
    # CF-0794: a video whose score log stopped under N with no refusal
    # sidecar (a stage priced it after its own check) gets the score's own
    # refusal now, so collect() below finds it with every other one.
    for side in ([] if repairing is not None else score_log.ensure_refusals(batch_dir)):
        print(f"METADATA: score refusal written (CF-0794): {side}", file=sys.stderr)
    # CF-0881: no sidecar is read on a repair - refusals[] stays as it is
    refused = [] if repairing is not None else plan_refusal.collect(batch_dir)
    if held is not None:
        # CF-0802: a first-pass script's sidecar is answered by the entry 05
        # already holds for it; re-reading it here would rewrite that entry.
        refused = [r for r in refused if r["script_id"] not in held]
    seen = {r["script_id"] for r in refused} | (held or set())
    for path in args.refusal:
        rec = plan_refusal.read(path)
        if rec is None:
            print(f"METADATA: ERROR: {path} is not a refusal record "
                  f"(CF-0254: {{script_id, reason_code, reason}})", file=sys.stderr)
            sys.exit(2)
        if rec["script_id"] not in seen:
            refused.append(rec)
            seen.add(rec["script_id"])
    if not args.video and not refused and held is not None:
        print(f"METADATA: ERROR: --new-only with no --video and no refusal of a new "
              f"script under {batch_dir / 'work'} - nothing to add (CF-0802). When "
              f"`pending_scripts.py <batch>` lists nothing, the stage closes with "
              f"stage-done and writes no metadata.", file=sys.stderr)
        sys.exit(2)
    if not args.video and not refused:
        print(f"METADATA: ERROR: no --video and no refusal record under "
              f"{batch_dir / 'work'} - there is nothing to write. A batch that "
              f"rendered nothing has to carry the gates' refusals (CF-0254); if "
              f"the plans were built elsewhere, name them with --refusal.",
              file=sys.stderr)
        sys.exit(2)
    if len(args.video) == 1:
        # CF-0107: one video -> its slug and attempt on the event; several
        # videos -> the event is the batch's, video null.
        runlog.annotate(**video_attempt(args.video[0][1]))

    written = []

    dest = batch_dir / DEST_NAME
    # CF-0030: the existing file is the starting point, not something to
    # replace. Read it before anything expensive runs, so an unreadable file
    # stops the call instead of being discovered after the QC pass.
    existing_doc, existing_videos = {}, []
    dropped = None      # --replace-all: what the discarded file held, for the record
    if dest.exists():
        try:
            doc, vids = read_existing(dest)
        except UnreadableMetadata as e:
            if not args.replace_all:
                print(f"METADATA: ERROR: {dest} exists and cannot be merged into ({e}); "
                      f"refusing to overwrite it - this file is the only recovery source "
                      f"for the assignment registry (CF-0049). Fix it, or pass "
                      f"--replace-all to write it from this call alone.", file=sys.stderr)
                sys.exit(2)
            dropped = f"an unreadable file ({e})"
        else:
            if args.replace_all:
                dropped = f"{len(vids)} existing record(s)"
            else:
                existing_doc, existing_videos = doc, vids
    previous = {v["script_id"]: v for v in existing_videos}

    # CF-0416: a rebuild writes its own record by this same call, and its
    # channel is the source batch's - read off the copied 03/01, never the
    # directory name `rebuilds` (the frame-judge stage of 1757Z had to
    # hand-assemble a record whose `channel` said "rebuilds"). `--channel`
    # still wins when given.
    rebuild = rebuild_source(batch_dir)
    channel = args.channel or resolve_channel((rebuild or {}).get("channel"))
    if rebuild is not None and not channel:
        print(f"METADATA: WARNING: {batch_dir} is a rebuild, but neither "
              f"{' nor '.join(REBUILD_SOURCE_RECORDS)} names a channel - the record "
              f"says channel {REBUILDS_GROUP!r}; pass --channel", file=sys.stderr)
    channel_id = channel or batch_dir.parent.name
    # CF-0416: which QC failures are cosmetic for this channel - a video
    # whose QC failed only on those is admitted to the frame judge through
    # `judge_admitted_despite`, never through `qc.passed`.
    cosmetic = qc_cosmetic.load(channel_id)
    for r in cosmetic["dropped"]:
        print(f"METADATA: WARNING: {cosmetic['source']} names {r!r} cosmetic - "
              f"never cosmetic (CF-0416: the hard list, or a failure QC could "
              f"not name); ignored", file=sys.stderr)

    # CF-0188: resolved once for the whole batch - every video of a batch is
    # read by the same channel in the same voice. A config that says something
    # unusable about its voice stops the write instead of being recorded as
    # the default voice it is not.
    try:
        voice = voice_profile.load(channel)
    except voice_profile.VoiceProfileError as e:
        print(f"METADATA: ERROR: channel {channel!r}: {e}", file=sys.stderr)
        sys.exit(2)

    # CF-0399: the code that built this call's videos, read once - every
    # record written now was built by the same HEADs.
    code = code_shas() if args.video else None

    for script_id, plan_path, mp4 in args.video:
        plan = json.load(open(plan_path))
        qc = qc_report(mp4, plan_path)
        # CF-0674: the preview frame the command centre shows, beside the mp4,
        # after the render and its QC - every batch and every rebuild ends
        # here. Said, never fatal: the API falls back to the judge's sheet.
        # CF-0681: only beside an mp4 under batch_dir - a live monitor records
        # a real batch's mp4 into a temp batch_dir and must leave its
        # videos/ as it found it.
        try:
            shot = video_preview.write_for_batch(batch_dir, mp4, plan_path)
        except Exception as e:  # noqa: BLE001 - a preview never costs the record
            shot = {"path": None, "reason": f"{type(e).__name__}: {e}"}
        if shot.get("path"):
            print(f"METADATA: preview -> {shot['path']} ({shot['at']:g} s, "
                  f"{shot['bytes'] // 1000} KB, {shot['why']})", file=sys.stderr)
        elif shot.get("skipped"):
            print(f"METADATA: preview not written for {script_id}: {shot['reason']}",
                  file=sys.stderr)
        else:
            print(f"METADATA: WARNING: no preview for {script_id} (CF-0674): "
                  f"{shot['reason']}", file=sys.stderr)
        before = previous.get(script_id) or {}
        written.append(video_record(script_id, plan, mp4, qc, args.style_requested,
                                    existing_inserts=before.get("inserts"),
                                    existing_underlay=before.get("underlay"),
                                    ledger=ledger_for_plan(plan_path),
                                    voice=voice, cosmetic=cosmetic))
        written[-1][CODE_FIELD] = code
        # CF-0434: the score log of the video - `score` (the whole log: every
        # finding and what it cost, per stage, the remainder, the tier) and
        # `score_line` (the one line the run summary and the message to the
        # user carry). Read off `<plan stem>.score.json`, which the qc_report
        # call just above brought up to this render.
        written[-1].update(score_log.record_fields(plan_path, plan))
        if repairing is not None:
            written[-1][REPAIR_FIELD] = repair_record(
                plan_path, datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # CF-0434: a video the score stopped after QC has a refusal sidecar now
    # (`<plan stem>.score.refusal.json`), possibly written by the qc_report
    # call of this very loop - read the sidecars again so it is not missed.
    for rec in ([] if repairing is not None else plan_refusal.collect(batch_dir)):
        if rec["script_id"] not in seen:
            refused.append(rec)
            seen.add(rec["script_id"])

    videos, replaced = merge_videos(existing_videos, written)
    # CF-0270: the one case where the mp4 is not the fact. A gate that fires on
    # a *rebuild* - the pattern ceiling gate, fed a post-QC degradation through
    # `--degrade-block` - refuses a script whose earlier attempt is already
    # rendered and on disk. That mp4 is the render the refusal is about, so
    # letting it win here would publish exactly the video the gate refused, and
    # 05-video-editor.json would carry a ready video for a script the funnel is
    # simultaneously told was held back. The refusal says so with
    # `supersedes_video` and the video record goes, from this call's own
    # `--video` and from whatever an earlier call left behind alike.
    superseded = plan_refusal.superseded_video_ids(refused)
    rejected_videos = [v["script_id"] for v in videos if v["script_id"] in superseded]
    videos = [v for v in videos if v["script_id"] not in superseded]
    # CF-0254: the same union for the other list, minus every script that has a
    # video record - a refusal from an attempt that was retried and rendered is
    # answered by the mp4 beside it, and leaving both would tell the funnel two
    # different things about one script. `--replace-all` starts from nothing
    # here too; the sidecars on disk are re-read either way.
    kept_refusals = [] if args.replace_all else (existing_doc.get(plan_refusal.FIELD) or [])
    refusals, stale = plan_refusal.merge(kept_refusals, refused,
                                         video_ids=[v["script_id"] for v in videos])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.replace_all:
        mode = "replace-all" if dest.exists() else "create"
    elif repairing is not None:
        mode = REPAIR_MODE
    elif args.new_only:
        mode = NEW_ONLY_MODE
    else:
        mode = "merge" if dest.exists() else "create"

    # Everything an earlier writer left at the top level survives, in place -
    # the orchestrator's `merge_note` above all (CF-0030's hand-merge of
    # 2026-09-03T2037Z): this stage owns four fields and has no business
    # deleting the rest. `--replace-all` starts from nothing, which is what it
    # is for. `merge_log` is this stage's own and grows by one entry per call.
    out = {k: v for k, v in existing_doc.items()
           if k not in ("videos", MERGE_LOG_FIELD, plan_refusal.FIELD)}
    out["batch_id"] = args.batch_id or batch_dir.name
    out["channel"] = channel_id
    # CF-0416: the batch a rebuild was copied from - null on an ordinary batch.
    out[REBUILD_FIELD] = rebuild
    out["generated_at"] = now
    out["pipeline_version"] = "v3-remotion"
    out[MERGE_LOG_FIELD] = list(existing_doc.get(MERGE_LOG_FIELD) or []) + [
        {"at": now, "videos": [v["script_id"] for v in written], "mode": mode,
         plan_refusal.FIELD: [r["script_id"] for r in refused]}]
    out["videos"] = videos
    # CF-0254: always written, `[]` on a batch that refused nothing - the
    # funnel reads absence as "this stage records no refusals", which was true
    # of every batch before this and must not stay true of one written now.
    out[plan_refusal.FIELD] = refusals

    write_atomic(dest, out)
    print(f"metadata -> {dest} ({len(videos)} video(s), {len(refusals)} refusal(s))")
    # CF-0246: the batch as it now stands - no mp4 left in a checkout's
    # videos/, one mp4 under <batch>/videos/ per record. Said, not refused:
    # the record above is already the truth about what was built.
    for finding in batch_layout.check(batch_dir):
        print(f"METADATA: WARNING: LAYOUT: {finding}", file=sys.stderr)
    # CF-0397 / CF-0443: a video of videos[] that goes to the user (the frame
    # judge takes it, its score is not under N, the judge did not reject it)
    # retires its shots for the channel; a QC-failed, NEEDS-YOU or tier-F one
    # does not. Synced to videos[] as just written, so a video this call
    # dropped (CF-0270) gives its shots back, and every write reads the
    # acceptance log: a video the user rejected gives its shots back too.
    # After the stage record, never instead of it: a registry that cannot be
    # written is said out loud and does not cost the batch its
    # 05-video-editor.json.
    try:
        synced = retired_shots.sync_from_batch(
            batch_dir, videos, plans={sid: pp for sid, pp, _ in args.video},
            registry=args.retired_shots, channel=out["channel"],
            acceptance_log=args.acceptance_log)
    except (retired_shots.RegistryError, OSError) as e:
        print(f"METADATA: ERROR: retired shots not recorded (CF-0397): {e}",
              file=sys.stderr)
        synced = None
    if synced:
        reg, added, removed = synced
        print(f"METADATA: retired shots -> {reg} (+{len(added)} delivered video(s), "
              f"-{len(removed)} dropped, {len(synced.held)} held, "
              f"{len(synced.returned)} returned)", file=sys.stderr)
        for slug, why in sorted(synced.held.items()):
            print(f"METADATA: shots not retired (CF-0443): {slug} - {why}",
                  file=sys.stderr)
        for eid in synced.returned:
            print(f"METADATA: shots returned to the pool (CF-0443): {eid}",
                  file=sys.stderr)
    if args.replace_all:
        print(f"METADATA: --replace-all: wrote {len(written)} record(s) as the whole file, "
              f"dropped {dropped or 'nothing (no file was there)'}", file=sys.stderr)
    else:
        print(f"METADATA: merged {len(existing_videos)} existing + {len(written)} written "
              f"({len(replaced)} replaced)", file=sys.stderr)
    # CF-0254: the refused scripts, by name, before the per-video lines. An
    # operator whose batch produced no video at all sees here what the funnel
    # will read - and a refusal the render later answered is said out loud as
    # dropped rather than disappearing between two runs of this stage.
    for rec in refusals:
        print("  " + plan_refusal.report_line(rec), file=sys.stderr)
    for sid in stale:
        print(f"  refusal dropped: {sid} has a video record in this batch - the "
              f"attempt that was refused was retried and rendered", file=sys.stderr)
    for sid in rejected_videos:
        print(f"  video dropped: {sid} was refused on a rebuild after that render "
              f"(CF-0270) - the mp4 on disk is the attempt the refusal rejects, "
              f"not a video this batch delivers", file=sys.stderr)
    for v in written:
        if v.get(score_log.LINE_FIELD):
            print(f"  SCORE: {v['script_id']} {v[score_log.LINE_FIELD]}", file=sys.stderr)
        if not v["qc"]["passed"]:
            if v.get(qc_cosmetic.FIELD):
                print(f"  QC FAILED (cosmetic, admitted to the frame judge): "
                      f"{v['script_id']} {', '.join(v[qc_cosmetic.FIELD])} "
                      f"({qc_cosmetic.FIELD}; qc.passed stays false)", file=sys.stderr)
            else:
                print(f"  QC FAILED: {v['script_id']}", file=sys.stderr)
        if v.get("needs_you"):
            print("  " + attempts.ledger_needs_you_line(v["script_id"], v),
                  file=sys.stderr)
        elif v.get("attempts"):
            # CF-0415: attempts and QC degradations against their own caps.
            used = v.get("attempts_used", len(v["attempts"]))
            line = f"  ATTEMPTS: {v['script_id']} {used}/{v['attempt_cap']}"
            if v.get("qc_degrades_used"):
                line += f", qc degrades {v['qc_degrades_used']}/{v.get('qc_degrade_cap')}"
            print(line, file=sys.stderr)
        for w in v.get(plan_refusal.WARNINGS_FIELD) or []:
            print("  " + plan_refusal.warning_line(w), file=sys.stderr)
        g = v.get("two_source_gate") or {}
        if g.get("passed") is False:
            print(f"  TWO-SOURCE GATE FAILED ({g.get('mode')}): {v['script_id']} "
                  f"{g.get('count')}/{g.get('required')} independent source(s)"
                  + (f" - {', '.join(g['canonical_ids'])}" if g.get("canonical_ids") else ""),
                  file=sys.stderr)
        if v["degradation"]:
            print(f"  DEGRADED: {v['script_id']} "
                  f"{v['style_requested']} -> {v['style_delivered']}", file=sys.stderr)
        if v["rhythm_requested"] and v["rhythm_delivered"] != v["rhythm_requested"]:
            print(f"  RHYTHM NOT DELIVERED: {v['script_id']} "
                  f"{v['rhythm_requested']} -> {v['rhythm_delivered']}; "
                  + "; ".join(v["rhythm_deviations"]), file=sys.stderr)
        elif v["rhythm_shortfalls"]:
            # CF-0057: delivered, and still not all of it. Said out loud on its
            # own line rather than folded into the one above - the two are
            # different findings and the operator has to be able to tell a
            # rhythm that is missing from one that is present but standing
            # still.
            for s in v["rhythm_shortfalls"]:
                # CF-0118: nothing this factory writes today puts a
                # `two_source_gate` record in this list - a measured gate
                # reports on `two_source_gate` and an enforced one refuses
                # the plan outright, so there is no metadata for it to reach.
                # A plan carrying one is a plan from a build that did append
                # it; it is still shown, and labelled for what it is rather
                # than as a short rhythm, because printing a sourcing
                # failure as `RHYTHM SHORT` is the one reading that would
                # mislead.
                # CF-0137: and `emergency_reuse` is a third reading again.
                # The rhythm was delivered and the block has a picture; what
                # is short is the *material*, and the operator's next move is
                # to widen the footage pool, not to look at the cadence.
                # Printing that as `RHYTHM SHORT` would send them to the
                # wrong place, exactly as the gate line above would.
                label = ("SOURCE SHORT" if s.get("kind") == source_gate.DEFICIT_KIND
                         else "MATERIAL SHORT" if s.get("kind") == "emergency_reuse"
                         else "RHYTHM SHORT")
                print(f"  {label}: {v['script_id']} {s['kind']} - "
                      f"{s['note']}", file=sys.stderr)
        for rec in v.get(comparison_line.DELIVERED_FIELD, []):
            print(f"  COMPARISON LINE: {v['script_id']} {rec['fact_id']} "
                  f"{rec['start_s']:.2f}-{rec['end_s']:.2f}s - {rec['text']!r}",
                  file=sys.stderr)
        for req, ans in zip(v["meme_requested"], v["meme_delivered"]):
            if ans["outcome"] != meme_layer.OUTCOME_PLACED:
                print(f"  MEME NOT PLACED: {v['script_id']} {req['beat_id']} "
                      f"({req['intent']}) - {ans['outcome']}"
                      + (f" ({ans['reason']})" if ans.get("reason") else ""),  # CF-0811
                      file=sys.stderr)
        # CF-0138: a line of its own, and never `MEME NOT PLACED`'s. Nothing
        # was requested here and nothing failed; what happened is that a hole
        # in the montage was covered by a picture from the library, and an
        # operator accepting the video has to be told - it is the one insert
        # on screen that no writer chose and no beat explains.
        for rec in (v.get("meme_hole_fill") or {}).get("filled") or []:
            print(f"  INSERT IN A HOLE: {v['script_id']} block "
                  f"{rec['block_index']} {rec['asset_id']} - nobody asked for "
                  f"this insert; it stands in for footage that never arrived "
                  f"(score {rec['score']}, lead {rec['lead']})", file=sys.stderr)
        # CF-0193: the line now carries the decision as well as the code, and
        # a refusal-grade one says so in the word REFUSED - an operator
        # reading this list should not have to know REFUSAL_OUTCOMES by heart.
        for sf in v.get("proof_shortfalls") or []:
            refused = sf.get("decision") == proof_layer.DECISION_REFUSE
            print(f"  PROOF NOT PLACED{' (REFUSED)' if refused else ''}: "
                  f"{v['script_id']} {sf['proof_id']} - "
                  f"{sf['code']}: {sf['note']}", file=sys.stderr)
        for req, ans in zip(v["sound_requested"], v["sound_delivered"]):
            if ans["outcome"] != sound_layer.OUTCOME_PLACED:
                print(f"  SOUND NOT PLACED: {v['script_id']} {req['beat_id']} "
                      f"({req['intent']}) - {ans['outcome']}", file=sys.stderr)


@video_script("video-editor", "metadata", name="write_batch_metadata.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(). One video on the
    command line -> both halves of the pair carry its slug and the ledger's
    attempt (`video_script` reads them off the line before the start is
    written); several -> the event is the batch's and `video` stays null,
    the rule main()'s own annotate() already followed. main() stays bare for
    in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

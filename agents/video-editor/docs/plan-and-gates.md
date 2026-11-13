# The plan and its gates

What is checked before a script is paid for and before the render, and
where the montage plan is built. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

## Asking before the script is paid for (CF-0140)

The ladder above runs *after* TTS: the voiceover is synthesised, the plan is
built, the anchors are resolved, and only then does "there is nothing to show
here" arrive. `scripts/anchor_coverage.py` asks the same question of a pool
without resolving anything, so the Content Researcher's validator can refuse
an unpicturable anchor while the only thing spent is a rewritten script
(CF-0123's order; the validator and the stage order itself are that agent's
half of CF-0140).

```
anchor_coverage.py <anchors.json|-> --index <shots.json> [--index ...]
    [--min-score 0.22] [--top 10] [--score-floor F] [--strict]
    [--min-delivery-height 720] [--min-coverage C] [--max-black B]
    [--matcher-python PATH] [--out report.json] [--quiet]
```

One JSON object on stdout (or `--out`), a per-anchor `verdict` of `covered` /
`weak` / `absent`, a `cause` from the CF-0139 shortage vocabulary
(`no_footage` / `footage_unusable`) on every `absent` one, and exit 0 / 2 -
2 meaning the pool cannot carry this script. `preflight()` and `assess()` are
importable for a caller that would rather not go through JSON. Full field
list in `tasks/CF-0140-anchor-coverage-preflight-before-tts.md`.

The one thing that makes it worth anything is that it owns no judgement of its
own. The candidates come from `resolve_anchors.match()`, the screening from
`resolve_anchors.precut_refusal()` - the mark / span / cached-usability chain
lifted out of `fill()`, which is now the only copy of it in the repository and
is what `fill()`, `cut_usable()` and the preflight all ask - and the verdict
from `resolve_anchors.gate_verdict()`, CF-0088's own post-gate answer.
`tests/test_anchor_coverage_preflight.py` pins that both ways: the source has
one gate with three callers, and replacing that one function moves the
preflight's answer and a real `resolve_anchors.main()` run's answer together.

`absent` is therefore certain and `covered` is not a guarantee - the real
`usable()` runs on a cut clip and needs ffmpeg and the source file, and the
reuse cap, the swing rules and the opening's spent frames are facts about a
video that does not exist yet. The one of those that is decidable early is the
cap: `contention()` matches anchors against the distinct samples that survived
screening, and reports how many blocks must go without a picture because one
sample may be shown once (CF-0121), less CF-0137's single emergency repeat.
It never blames a particular anchor for it, because which anchor loses depends
on a block plan there is none of yet.

## The anchors are the script's now (CF-0140)

The preflight above is only worth something if the phrases it screens are the
phrases that get resolved. Until CF-0140 they were not: the Editor invented its
anchors at step 4, *after* TTS, so the pool was being asked about wording nobody
would use. Since CF-0140 the Content Researcher writes them - `visual_anchors[]`
in `03-content-researcher.json`: `anchor_id`, `phrase` (the frame, in words),
`beat_text` (a verbatim substring of a counted section) and an optional `side` -
and `scripts/script_anchors.py` is this repository's side of that contract:

```
script_anchors.py preflight <03-content-researcher.json> --script-id <id> \
    --index <shots.json> [--index ...] [--strict] [--out report.json] [--quiet]
script_anchors.py spec <03-content-researcher.json> --script-id <id> \
    --words <words.json> --out <anchors.json> [--style motion] [--opening-card TEXT]
```

`preflight` runs **before `synthesize_voiceover.py`** with the `--index` list
this video will be resolved with, and it is not a duplicate of the Content
Researcher's gate: that one asks about every fetched source, while this stage
resolves against the pool compliance pass 2 (`04-compliance-checker.json`)
actually cleared, which is regularly narrower. Neither side can set
`--min-score` or `--top`; both run on `resolve_anchors.py`'s constants.

`spec` copies each `phrase` verbatim and turns `beat_text` into a word index
through `meme_layer.locate_beat()` - the repository's one beat locator, shared
with the meme, sound and proof layers, given the anchor's own section so that a
payoff echoing the hook does not land on the hook.

Three refusals, and all three are decisions rather than defaults:

* **no `visual_anchors`** (old scripts on disk still have none) - exit 2, the
  script goes back. Writing them here instead would be the pre-CF-0140
  behaviour restored silently, and the run would look identical to a compliant
  one;
* **a `beat_text` that is not in the alignment** - that anchor is dropped and
  named, never given a guessed index; a frame placed on a moment the writer did
  not ask for is a rewritten phrase by another route. Since CF-0235 the line
  says *which* of the two drops it is, because they call for opposite actions:
  `ANCHOR DROPPED [beat_missing_in_script]` - the narration does not say those
  words either, so the script goes back to the writer; `ANCHOR DROPPED
  [beat_unmatched_in_alignment]` - the script says them character for character
  and our forced alignment lost them, which is ours to fix and costs the writer
  nothing. Both carry `meme_layer.beat_failure()`'s evidence (coverage in the
  script, coverage in the alignment, and the stretch that came closest as it
  was heard), and both are the same codes the proof, meme and sound layers
  answer with. All anchors dropped, or two anchors landing on one word
  (`beat_collision`, a zero-second stretch asked to hold two pictures), and the
  script goes back - the hand-back line counts the drops by reason, so the
  report says whether the script or the aligner is at fault;
* **a preflight refusal here** - until CF-0330 (see below), exit 2 before any
  synthesis; now a warning and exit 0. Not a phrase
  reworded locally, and not the CF-0137 ladder: that ladder answers a block
  that could not be filled once a plan exists, and this is the pool being
  unable to picture the script before a second of speech has been paid for.

`tests/test_script_anchors.py` pins all three, plus the phrase arriving at the
matcher byte for byte and the skill documenting the preflight ahead of the TTS.

## Three gates warn instead of refusing (CF-0330)

The user, 2026-09-23. Two videos he had accepted for publication were rebuilt
on the current code (`pipeline/rebuilds/2026-09-23T0330Z`) and both were
refused before the render: `everyday-sorcery-2` by `anchor_preflight` /
`pool_too_thin` (one anchor with no survivor, best candidate 0.2198 against a
floor of 0.22) and `widows-bay` by `assetless_rung` / `pattern_undeliverable`
(3 of 24 blocks with no picture). `two_source_gate` had been priced by CF-0320
at 2 of 5 ready videos. None of the three prices was signed; all three warn.

A warning is the refusal's own record - gate id, funnel code, sentence, numbers
(`plan_refusal.warning()`) - with `severity: "warn"`, and the run goes on:

    gate               code                    where the warning goes
    anchor_preflight   pool_too_thin           work/<slug>/anchor_preflight.warning.json, exit 0
    assetless_rung     pattern_undeliverable   plan["warnings"]; holes stay asset.kind procedural
    two_source_gate    no_second_source        plan["warnings"] in `measure` mode

`build_render_plan.py` reads the preflight's warning from the video's work
directory, so `plan["warnings"]` holds all of them, and `write_batch_metadata.py`
carries it to `videos[].warnings`. Nothing warned is ever in `refusals[]`.
A block with no picture renders on the procedural background for its span -
the rung CF-0031 built and Video.jsx has always painted - and the
`plan.assetless-rung.json` deficit is still written beside the plan for the
rotation. `two_source_gate`'s mode stays the channel's
(`channels/<channel>.json` in the factory root): a channel that still says
`enforce` refuses until that file goes back to `measure`.

## A refusal before the render is a record too (CF-0282)

The refusals CF-0254 arranged are the plan builder's. The two gates that stop a
script *earlier* - this preflight, before the TTS, and `narration_length.py` on
the finished wav, before the plan - ended in a headline on stderr and exit 2,
and nothing on disk said what became of the script: `write_batch_metadata.py`
never heard of it, `05-video-editor.json` had no row for it, and the root's
funnel printed `not_built` - "the Editor neither rendered nor refused it" -
about a script the Editor had refused out loud and cheaply. Batch
`example-film/2026-09-18T1058Z` is both: `lf-2026-09-18-003-script1` (South
Park) refused by the preflight at 23 anchors against 7 distinct usable samples,
16 of them with no picture, over a pool of 2 sources / 16 shots; and the Hunger
Games script refused by the ceiling at 61.64 s, whose record a later rescue
pass wrote by hand.

Both now go through `plan_refusal`, the CF-0254 mechanism unchanged - one gate
table, one sidecar shape, one merge:

    gate id            funnel code     sidecar                        written by
    anchor_preflight   pool_too_thin   <report stem>.refusal.json     script_anchors.py preflight
    narration_ceiling  held_back       voice.refusal.json             narration_length.py
    unresolved_anchor  pool_too_thin   plan.refusal.json              build_render_plan.py

`unresolved_anchor` (CF-0290) is the third gate under that code and the one
the storyboard itself triggers: a block whose picture scores under the
similarity floor. **What the operator does about it is material, never a
rebuild.** The reason names each phrase and the score it got; the remedy is
either footage that depicts those phrases or anchors rewritten against what
the pool does have, and `anchor_coverage.py` is what says which. Re-running
the plan changes nothing, because the storyboard is where the picture was
chosen. A storyboard resolved by this checkout cannot reach this gate at all -
`resolve_anchors.screen_pool()` refuses such a candidate before it is cut - so
one that does was built before CF-0290 or outside this repo, and re-resolving
it here is the repair. The gate runs first in `build_render_plan.py`, before
the words are loaded and before the voice is probed: it reads the storyboard
and nothing else, so a plan that may not be written costs one file read.

`pool_too_thin` is the root's own sentence for this finding - "fewer usable
samples in the pool than the pattern's anchors" - and it stays true for all
three ways the preflight refuses (`sample_contention`, `absent_anchors`,
`weak_anchors`); which one it was is in the record's `numbers.refused_because`.
Beside the three keys the funnel reads, the record carries `numbers`: the
counts the gate refused on, so a reader a week later does not have to reopen
the stage's report and a query over a run of batches can count them. The same
counts are in the `reason` sentence, because the funnel prints that sentence
with nothing beside it but the code.

The sidecars land under `<batch>/work/<slug>/`, which is the only thing
`plan_refusal.collect()` asks, so `write_batch_metadata.py <batch>` picks them
up with no flag and writes `refusals[]` for a script that produced no plan at
all - and that command is the operator's step right after either refusal.
Without `--out` the preflight has no work directory to write into and says
`REFUSAL NOT RECORDED` rather than leaving the loss silent; the ceiling says
the same without `--script-id`, since a record keyed on no script is not a
record. `tests/test_pre_render_refusal_record.py` pins both ends, with that
batch's own `anchor_preflight.json` as the fixture and the root's funnel
reporting the Pine Park loss as `pool_too_thin` instead of `not_built`.

## The plan is built before the handoff (CF-0411, 2026-09-28)

Batch `example-film/2026-09-27T0929Z` shipped nothing: three of its five scripts
died in this stage after the voice and the resolve were paid for. Backrooms was
predicted at 17.72 blocks/min by the writer's `check_block_capacity` and measured
at 3.8 by `build_render_plan.py` (`pattern_ceiling`); Wolfhame was "21/21 covered"
twice and the cut-clip gate then refused all 55 free shots (framing and brightness
are measured on the cut clip, the cache on a probe frame - `CL1EFACsWag:46`, cache
52.4, clip 18). The rebuild `rebuilds/2026-09-27T1757Z` saved both by editing the
anchors, never the narrator's text, against the refusals of the real resolve and
plan. The user's decision of 2026-09-28: that loop runs inside the writer's stage,
and a script does not leave it until these gates have built a plan from it.

`scripts/plan_check.py` is that one entry point, run by the Content Researcher:

    plan_check.py check <batch> --script-id <id> [--slug <slug>] [--channel <id>]
                  [--index <shots.json> ...] [--narration-file <txt>]
                  [--lead-silence <s>] [--style <style>] [--adopt-voice] [--force]

It runs this stage's own commands - `synthesize_voiceover.py`,
`narration_length.py`, `align_words.py`, `script_anchors.py spec`,
`resolve_anchors.py --order work/<slug>/order.json --channel <id>`,
`build_render_plan.py --channel --script --script-id --estimated-seconds` - as
separate processes into `<batch>/work/<slug>/`, and stops before
`render_video.py` (no attempt is begun). Defaults: the slug is the `title_ref`
name slugified (`backrooms`, `kaijura-minus-zero`), the channel is 03's, the
pool is the script's own `anchor_coverage_pool.indexes`, the text is hook +
commentary + payoff on one line (`meme_layer.narration_text`, CF-0261). Exit 0
assembled, 2 not assembled, 1 the environment.

An all-graphic script (CF-0814) - every anchor a `graphic_id`, CF-0689/CF-0806 -
names no pool: with no `--index` and `indexes: []` in 03 the resolve and the
plan run with no `--index` and build the video from the script's `graphics[]`;
the verdict carries `no_pool: true` and a `no_pool` note (the pool's gates had
nothing to measure). An empty pool under any anchor that asks the pool is
still exit 1, "which pool is it?" - as it is in `resolve_anchors.py` and
`script_anchors.py preflight`, which take no `--index` on the same terms.

The verdict is `work/<slug>/plan_check.json`:

    assembled              plan.json written and no refusal below
    refusals[]             {kind, gate, block, anchor_id, phrase, reason, ...}
                           kind: pattern_ceiling | plan_refused | background |
                           typographic | cut_gate | absent | narration_ceiling |
                           anchors_dropped
    notes[]                non-blocking: a covered shortfall, the plan's warnings
    text_sha256            sha256 of the text synthesized
    anchors_sha256         sha256 of the script's visual_anchors (canonical JSON)
    baseline_text_sha256   round 1's text; text_changed = text_sha256 != it
    anchors_changed        against the previous round
    round, tts.reused, indexes, inputs, steps[], artifacts{voice, words,
    anchors, storyboard, plan, order: {path, sha256}}, refusal, environment_error

`background` is a block on the procedural rung (`assetless_rung.blocks`, or
`asset.kind: procedural` not filled by an insert); `typographic` a block
`degraded_blocks[].to == typographic` (a whole video in the flat typographic
style is not a hole); `cut_gate` a storyboard `unresolved_anchors` entry whose
candidates died on the cut clip (`failed usable() on the cut clip`); `absent`
any other unresolved anchor (under the floor, pre-filtered) - one record per anchor, the cut clip winning the name; a shortfall carried
into the next block is a note. A script not assembled also gets
`work/<slug>/plan_check.refusal.json` - a `plan_refusal` record under the first
refusal's gate, with `before_render: true`, `refused_by: plan_check` and
`kinds` - which `write_batch_metadata.py` collects into `refusals[]` like any
other refusal of this stage (it is newer than the builder's own
`plan.refusal.json`, so it is the one kept for the script).

A rerun after the anchors were edited pays for no voice: `voice.key.json` keys
the wav and the alignment on the text's sha256 plus the channel's voice
(`voice_profile.load`) and the lead silence, and they are reused while it holds
(`tts.reused: true`). A changed text is synthesized again and says
`TEXT CHANGED` with `text_changed: true` - the writer's loop reads that as its
guard. Every round first moves the previous round's `plan.json`, `plan.*.json`
sidecars and deficits, verdict and refusal into
`work/<slug>/plan_check.rounds/round-<n>/` (the storyboard and anchors are
copied), so a stale refusal never sits beside a new verdict. Nothing changed
since the last round: nothing runs (`UNCHANGED`; `--force` to run anyway).
`--adopt-voice` trusts a `voice.wav` + `words.json` voiced before this file
existed when their `narration.txt` is exactly the text.

This stage reads it with

    plan_check.py reuse <batch> --script-id <id> [--slug <slug>] [--index <cleared shots.json> ...]

    0  REUSE     assembled, text/anchors/artifacts unchanged, every source the
                 plan uses is in the cleared --index list -> render plan.json
    2  REFUSED BEFORE THE RENDER - not rendered; the sidecar is on disk
    3  NO PLAN CHECK (or it ended on an environment error) -> build as before
    4  STALE     text/anchors/artifacts moved, or compliance pass 2 cleared a
                 narrower pool than the plan uses -> build as before (the voice
                 is still reusable)

A batch or a rebuild without verdicts behaves exactly as before.
`tests/test_plan_check.py` pins both sides, with the real Backrooms refusal
and deficit of 0929Z as the fixture.

## The on-screen theme is the channel's (CF-0572)

Every colour and face the render draws - captions, watermark, the source
badge and fact strip, the quote card (in Remotion and the rendered_quote PNG),
the end card, the split ground, the procedural ground's palettes - is the
channel's `theme` (`channels/<id>.json`, the root's `docs/channel-data.md`
«The theme»). `build_render_plan.py` writes it into `plan.theme` (without
`picked`/`note`, `scripts/channel_theme.py`); a named channel without a valid
theme gets no plan. A plan built without `--channel` carries `theme: null`
and a note, like the watermark - and `Video.jsx` refuses to render it
(`lib/theme.js requireTheme`): there is no default palette, ExampleFilm's
included. `THEME` in `Video.jsx` keeps sizes only. `render_quote.py` takes
`theme=` (the proof layer passes the planned channel's; the CLI `--channel`).

ExampleFilm's theme is the values the code used to carry, and its frames are
the same: `tests/test_theme_equivalence.py` compares the composition's markup
and the quote PNGs with what 3732fb7 drew; `tests/test_theme_guard.py` keeps
the palette out of the code.

## A held or long picture is read as it is shown (CF-0646)

The user's review of `example-film/2026-10-08T1824Z` found two pictures every
check had passed: rink-rivals 21 s held a 2.39:1 frame for 5 s as a strip
23.5 % of the screen's height (`blur_fill`) with only the players' legs in it,
and delver 12 / 18 s held frames of a source with no native detail, cropped to
9:16 and stretched x1.78. `blur_fill` takes a picture out of every "is the
subject cut" gate and nothing asked how thin it then is; CF-0465 reads a held
frame at source scale, not at the scale it stands on screen.

`scripts/held_screen.py` reads every held frame as shown and stamps it onto
its block / cut (`held_screen`, while the PNG is there): the picture's height
share on screen, the indexer's sharpness of the delivered window resized to
its screen size, how much of its finest detail the source keeps through a
half-scale round trip (an upscaled source keeps most), and macOS Vision's body
pose (a body with leg joints and no head joint, no face: the head is out of
frame). The plan builder's `held_screen_gate` (after `held_soft_gate`) writes
`plan["held_screen"]` with three rules:

| rule | fires on |
|---|---|
| `score.thin_picture` | a picture under 25 % of the screen's height held still, or moving 3 s or more; a contained clip standing nearly still 3 s or more under 33 % (CF-0650) |
| `score.held_cut_subject` | a held picture with a headless body and no face |
| `score.held_soft_stretch` | a held cover frame, 2 s or more, under 0.53 at screen scale, from a source keeping >= 0.36 of its detail (not a frame CF-0465 already charges) |

Calibrated on 11 videos / 217 pictures (the batch, 0701Z's rejected delver and
eight accepted videos): they fire on rink-rivals block 8 (thin + cut), delver
blocks 5 and 7 and the two held frames the user named in 0701Z's delver, and on
no picture of an accepted video. A soft *moving* clip (delver block 9) is not
separable from accepted ones by any pixel reading tried and is the frame
judge's. Warn until the user signs a row (`proposed_rows()`; CF-0320): the
record says `warn`, a note is written, nothing is charged. The calibration
reads plans read-only: `scripts/held_screen.py <plan.json>...`.

### A clip that barely moves is a held picture (CF-0650)

The rebuild `rebuilds/2026-10-09T1208Z`, rink-rivals's first pass (as in
1824Z), showed block 7 `UcIvQYYW4PY:4` - 1920x1080 on its blurred frame,
0.317 of the screen's height - standing nearly still for 3.64 s. The frame
judge refused the video (`thin_strip`); `held_screen` had passed it: the
share was over 0.25 and the clip was "moving". Now a candidate - a contained
picture under 0.4 of the height on screen 3 s or more - has its motion read
the judge's way (`clip_motion`: grey frames 0.5 s apart over the block's
window, the median of the consecutive pairs' mean absolute difference,
letterbox rows dropped), stamped onto the block / cut as `screen_motion`
while the clip is there (`stamp_motion`, in `held_screen_gate`). Under 4.5
grey levels the clip stands still and breaks `score.thin_picture` under 0.33
(16:9 shown whole is 0.316-0.318, 3:2 is 0.375). Only candidates are decoded
(none on most plans; 0.1-0.4 s each).

| picture | seconds | share | motion | |
|---|---|---|---|---|
| rink-rivals 1824Z / 1208Z first pass block 7, `UcIvQYYW4PY:4` | 3.64 | 0.317 | 2.27 | thin |
| 1208Z final block 7, `cFP-IWif0wc:39` (the operator's second pick) | 3.64 | 0.318 | 33.18 | - |
| 1208Z final block 9, `UcIvQYYW4PY:5` | 7.17 | 0.317 | 19.55 | - |
| accepted delver 1427Z block 3.4 / 4, `ZLXL1L0TfsI:31` / `:18` | 3.14 / 5.12 | 0.317 | 6.98 / 7.19 | - |
| accepted east-of-eden 0701Z block 10 | 2.47 | 0.281 | 3.73 | under 3 s |
| accepted harbourlights 0701Z blocks 2 / 11 / 28 | 1.6-1.7 | 0.23-0.28 | 0.9-2.8 | under 3 s |

A held frame keeps 0.25: the accepted east-of-eden 0701Z holds a 2:1 frame
(0.281) for 3.32 s. No accepted video of the CF-0646 calibration gains a
finding; the re-cut (below) takes the new finding like any other.

## What held_screen flags is re-cut before the render (CF-0648)

The rebuild `rebuilds/2026-10-09T1208Z` fixed CF-0646's findings by hand:
`resolve_anchors.py --exclude-candidate BLOCK` (CF-0367), the plan again, at
most twice per block - delver block 7 `wIM1PDRvKSE:55` -> `:22` -> `:21`,
rink-rivals block 8 `ADi1iextoUM:4` -> `:2` (a strip again) ->
`cFP-IWif0wc:34`, mudform blocks 11 and 14. `scripts/held_recut.py` does it
inside the plan builder's command-line run, after the plan is written:

* **What.** A finding of `score.thin_picture`, `score.held_cut_subject` or
  `score.held_soft_stretch` on a shot the storyboard block shows from its own
  pool (a card, an opening are left), whose anchor has had fewer than 2 such
  re-cuts (`excluded_candidates[].by == "held_screen"`) and whose walk left a
  candidate unreached (`length_supply.not_reached`; unknown on an older
  storyboard - tried).
* **How.** The storyboard records its resolve command (`resolve_call`,
  exclusion flags out); the loop snapshots the storyboard, the plan's files
  and the clips, runs it with `--exclude-candidate BLOCK=SHOT ...
  --exclude-by held_screen`, and builds the plan again with its own command
  line one round deeper (`CF0648_HELD_RECUT_ROUND`, at most 2 rounds per
  build).
* **Kept or put back.** The new plan stands when it was built and scores
  higher (the three rules' signed prices are in the score), or the same with
  fewer findings; otherwise everything is restored and the plan says so.
  `plan["held_recut"]` lists each round: what was asked, what was left and
  why, `outcome` (`kept`, `reverted`, `resolve_failed`, `round_cap`).
* **Off.** `--no-held-recut` (measurement), `CF0648_HELD_RECUT_OFF=1`, a
  storyboard without `resolve_call` (re-cut by hand, as before), and any
  in-process call of `main()` (tests).

On 1824Z it asks for delver block 7 (`:55`, soft stretch) and rink-rivals
block 8 (`ADi1iextoUM:4`, thin + cut subject) and for nothing on the accepted
vanguards-doomsday or on the rebuild's final plans. Each round costs a resolve
and a plan (1.5-8 min on 1824Z / 1208Z), only on a plan with a finding.

## Own capture and the vendor's quote (CF-0567)

On ExampleTech the footage is the factory's own screen recording of the tool
(`scripts/capture_tool.py`, `own_capture-<id>`), and a vendor's official clip
is a short quote beside it. Two gates of `build_render_plan.py` hold that,
right after the two-source gate, on the final blocks
(`scripts/proof_quote_cap.py`):

| gate | funnel code | refuses |
|---|---|---|
| `proof_quote_cap` | `held_back` | `[quote_too_long]` a quote over `proof_quotes.max_seconds_per_quote`; `[too_many_quotes]` over `max_quotes_per_video`; `[quotes_over_video_total]` over `max_seconds_per_video`; `[quote_is_the_base]` quotes over half the footage seconds (`never_the_base`) |
| `demo_own_capture` | `pattern_undeliverable` | `[demo_not_own_capture]` a plan of the `demo` pattern whose own recording is not over half the footage seconds (CF-0689/CF-0690: own graphics count toward the half; the tool must be on screen - a recording or an `api_chat`) |

A quote is a run of touching blocks showing one source whose rights record
says `role: proof_quote`, or names the origin (`vendor_official`) or a channel
id of an `official_channels` entry with that role. A channel with no
`proof_quotes` (ExampleFilm, ExampleScience) is not measured at all: the plan
carries `proof_quote_cap` with `applies: false`, nothing is read.

The two-source gate counts *borrowed* sources only: our recording is listed
apart (`own_capture_ids`), two recordings are not two sources, a video of
nothing but recordings is entirely ours, and a video whose recordings are on
screen at least as long as its borrowed footage passes. The plan's
`own_captures[]` keeps the page, the host and the Space's licence of every
recording on screen; none of them gets a credit row or an on-screen credit.
The whole of it, the recorder's refusals and its sidecar: SKILL.md, «Own
capture and vendor quotes».

## Own graphics (CF-0689)

ExampleTech's base footage is graphics the factory draws itself in Remotion
from the script's facts - no rights risk, automatic, nothing invented. The
rule of what a graphic may say is the root's `shared/own_graphic.py` (loaded
by path, `_root_shared.root_module("own_graphic")`); the editor applies it.

**The order.** The script carries `graphics[]` (`{graphic_id, template, data,
values: [{path, text, claim_ids}], source_label}`) and places each graphic
with a `visual_anchors[]` entry that has `graphic_id` instead of a pool
`phrase` (`beat_text` as always). Six templates: `spec_card`, `comparison`,
`price_date`, `benchmark` (its `source_label` is required), `timeline`,
`how_it_works`.

**Through the stage.**

* `script_anchors.py` - a graphic anchor needs no `phrase`; the preflight asks
  the pool only about the others (an all-graphic script passes without a
  pool, `graphic_anchors` in the record); the spec carries the anchor's
  `graphic_id` and, under `graphics`, the order of every graphic placed.
* `resolve_anchors.py` - the matcher is asked for pool anchors only. A segment
  a graphic anchor drives is one block `asset_kind: "own_graphic"`,
  `graphic: <the order>`, `graphic_id`, `shot: null`, no cut, no gate, no
  ledger take; it spans the segment the rhythm gives the anchor (its word to
  the next anchor's). A run the rhythm cut in two keeps one animation:
  `graphic_offset` is the seconds it already ran. A count-card or side-by-side
  opening gives way to a graphic on the first anchor (a rhythm note says so).
  CF-0923: a swing segment (a declared `alternate` makes one per crossing,
  so a run of same-side anchors is one segment) draws *every* graphic its
  anchors place, each from its own word less `LEAD_SECONDS`
  (`graphic_shots()`), not only the first; a piece under
  `MIN_SWING_CUT_SECONDS` folds into its longer neighbour, whose graphic
  stays - except the video's opening segment, whose first graphic is the
  hook: it holds at least that floor at the next piece's expense and a short
  neighbour folds into it. `hold`, `staccato` and `even` keep one graphic per
  segment.
* Render (CF-0923): while a comparison line (source badge + fact strip) is on
  screen with a graphic block - its window meets the block's span, crossfades
  included - the graphic's content box starts `CLEAR_GAP` below the line's
  lowest box and the panel is scaled down to fit it
  (`render/src/lib/graphicClear.js`; `tests/test_graphic_clear_geometry.py`).
* `build_render_plan.py` - the block's asset is `{kind: "own_graphic",
  graphic_id, template, data, source_label, caption, lang, offset_seconds}`
  (+ `bars` on a benchmark: each score's share of the largest, read by
  `parse_numbers`); `caption` is the source line in the channel's language
  (`According to X` / `По данным X`). `plan["own_graphics"]` lists each
  graphic on screen: its blocks, seconds, source line and `viewer_text`
  (only on a plan that has one). The order is checked again here
  (`scripts/own_graphic_plan.py`): `order_errors`, `adds_text`, an anchor
  naming no graphic of `graphics[]` (`graphic_not_ordered`), an id that is
  not the order's (`graphic_id_mismatch`) - any of them refuses the plan:

| gate | funnel code | refuses |
|---|---|---|
| `own_graphic` | `held_back` | `graphic_malformed`, `graphic_unknown_template`, `graphic_benchmark_unattributed`, `graphic_adds_text` (the root's codes), `graphic_not_ordered`, `graphic_id_mismatch`, `own_graphic_rule_missing` - "OWN GRAPHIC REFUSED", one line per block |

  A graphic is never degraded (`--degrade-block` on it is ignored with a
  note) and never routed to `procedural`/`typographic`; under a whole-video
  `typographic` style it stays `own_graphic` and Video.jsx draws it over the
  procedural ground (a note on the plan says so).

**No credit.** A graphic names no source: `own_graphic` is not in
`source_gate.FOOTAGE_KINDS`, so `block_sources()` is `[]` - no
`footage_credits` row, no credit overlay, nothing for the Publisher's credit
lines.

**Gates.** The two-source gate counts graphics as ours beside the
recordings: a video of nothing but graphics (and recordings) is entirely
ours (`applies: false`), and one whose own footage (`own_capture_seconds +
own_graphic_seconds`) is on screen at least as long as its borrowed footage
passes (`own_graphic_blocks`, `own_graphic_seconds` on the record). The
proof-quote cap adds `own_graphic_seconds` to `footage_seconds` (so
`never_the_base` measures a quote against a graphic base) and to the demo's
own share - but a `demo` still needs the tool on screen: a recording
(`own_capture_seconds > 0`) or, CF-0690, the model's own answer through its
API (`api_demo_seconds > 0`, below); other graphics alone are not a demo.

**Never a still.** `rhythm.PICTURE_KINDS` holds `own_graphic` and
`FROZEN_KINDS` does not; the still share (`still_share.py`) does not count
it - and that is earned, not a name on an exempt list: `qc_render.py`
probes every own-graphic block's render like a clip (`probe_targets`, the
top band, `longest_still_run` against `MAX_HELD_RUN`), and a graphic that
stands still is a fault (`freeze_verdict`: no source can explain it, no
`held_pose` escape). The templates keep moving for the whole block
(`render/src/graphics/CircuitTraces.jsx`: pulses along the traces and two
sheens half a sweep apart; measured on a render, the probe band's motion
never fell under 6.6 against the 1.0 floor). `meme_layer.NO_FOOTAGE_KINDS`
and `qc_render._NO_INSERT_LAYER_KINDS` hold the kind: no cutout and no
insert over a graphic.

**What is drawn** (`render/src/components/GraphicLayer.jsx`,
`render/src/graphics/*.jsx`): the channel's `bg`/`card_ground` and the
circuit-board ground, the template's content in the safe area above the
caption band (`graphics/kit.js contentBox`), animated in (rows staggered,
bars growing to `bars`, arrows drawing, the timeline's spine drawing down),
and `caption` at the foot. Every string on the frame is a string of `data`
or the caption - no label, unit, date or word of the template's own, no
count-up through numbers that are not the value. Colours only from
`plan.theme`.

**The frame judge** (`frame_judge_pack.py`): an own-graphic block carries an
overlay `{"kind": "own_graphic", "graphic_id", "template", "text":
viewer_text, "note"}`, `source.own_graphic: true`, and
`manifest.ours_on_screen.own_graphic` lists its blocks and what each graphic
says - all of it ours, still judged against the narration.

## A demo via API - the `api_chat` graphic (CF-0690)

The user's decision of 12.10: a ExampleTech story about a new model may show
that model's REAL answer to one of the channel's fixed neutral prompts, asked
through its official API by the Trend Hunter (`fetch_api_demo.py`, the
Gemini API free tier) and kept as the topic's `api_demo_record`
`{record_id: "api-demo-<topic>", protocol}` in `01-trend-hunter.json` (and
the cache `<batch>/work/api_demo/api-demo-<topic>.json`). The script orders
it as the seventh own-graphic template, `api_chat` (root
`shared/own_graphic.py`; the rule of the record is root
`shared/api_demo.py`): data `{model_label ≤48, prompt ≤160, answer ≤280 (the
channel's `api_demo.max_answer_chars`), date?}`, line breaks allowed in the
prompt and the answer, the top-level `record_id`, no `values`, no
`source_label`. The asset kind stays `own_graphic`; the credit, the
two-source gate and the still probe treat it like any own graphic.

**The asset** adds `record_id` and `chat_timing` to the own-graphic asset:

    {kind: "own_graphic", graphic_id, template: "api_chat",
     data: {model_label, prompt, answer, date?}, source_label: null,
     caption: null, lang, offset_seconds, record_id,
     chat_timing: {type_start, type_seconds, think_seconds, reveal_seconds,
                   answer_full_at, run_seconds, hold_seconds, scaled}}

`plan["own_graphics"]` rows of a chat carry `record_id` too.

**The clock** (`own_graphic_plan.chat_timing`, stamped by
`stamp_chat_timing` once every block is final): the prompt types from
`type_start` 0.5 s, a think pulse, the answer revealed word by word, then
held. Unhurried: typing `len(prompt)/40` s (0.8-3.0), thinking 0.9 s,
revealing `words/6` s (1.0-4.0). The clock is scaled to the whole run of
blocks the graphic spans (a run the rhythm cut in two shares one clock,
`offset_seconds` carrying it on) so that the whole answer stands at least
`HOLD_MIN` 1.5 s before the run ends - each part squeezed towards its floor
(typing 0.4, thinking 0.35, revealing 0.6). A run shorter than
0.5 + 1.35 + 1.5 = 3.35 s cannot show the whole answer for 1.5 s and refuses
the plan (`api_chat_too_short`, the script's chat anchor needs a longer
phrase).

**The backstop** (`own_graphic_plan.problems(gid, graphic, config,
protocols)`): `build_render_plan.api_chat_context` reads, only when the
storyboard places a chat, the channel's `api_demo` block of its
footage-origin.json and the protocols the chats name (the batch's
`01-trend-hunter.json` topics' `api_demo_record`, else the cache file of that
`record_id`); then `order_errors(graphic, config=block)` and the root's
`own_graphic.chat_problems` (= `api_demo.chat_problems` + a `date` that must
be the day the call was answered). Any finding refuses the plan under the
own-graphic gate ("OWN GRAPHIC REFUSED"), nothing drawn in its place:

| code | refuses |
|---|---|
| `api_demo_no_record` | no protocol for the `record_id` (none in the batch or the cache), or not a protocol |
| `api_demo_bad_finish` | the call was skipped or refused |
| `api_demo_prompt_mismatch` | `data.prompt` is not the protocol's prompt character for character |
| `api_demo_answer_rewritten` | `data.answer` is neither the answer nor `api_demo.shown_answer(answer, max_answer_chars)` |
| `api_demo_model_mismatch` | `data.model_label` is not "<display name> · via API" of the API's own modelVersion through the channel's model list (no list - no label) |
| `graphic_value_not_in_footing` | `data.date` is not the day the call was answered |
| `graphic_malformed` | the order's shape (caps, keys) |
| `api_chat_too_short` | the run cannot hold the whole answer 1.5 s |

**The demo gate.** `proof_quote_cap.judge` records `api_demo_seconds` (the
own-graphic blocks whose template is `api_chat`, part of
`own_graphic_seconds`). A `demo` passes when `own_capture_seconds +
api_demo_seconds` is above zero (the tool on screen: a recording, or the
model answering) and capture + graphics are over half of the footage (the
driver's decision of 12.10: the chat shows the real tool). Graphics with
neither a chat nor a recording are still refused `demo_not_own_capture`.

**What is drawn** (`render/src/graphics/ApiChat.jsx`): our own neutral chat
on the own-graphic panel in the channel's theme - no logo, no avatar, no
vendor look. The header is `model_label` (and `date`), with a breathing
accent dot; our prompt bubble (right) types the prompt character by
character behind a caret; three dots pulse in the answer bubble (left) while
the model "thinks"; the answer comes in word by word and is held. The strings
are the data strings exactly - no quotes, no "…" of ours (only a "…" the
cut answer itself carries), line breaks kept (`pre-wrap`). The rest of a
string still coming in is laid out invisible, so the bubbles never grow and
the panel never jumps; the reserved answer bubble has no fill (a faint
outline only) until its first word, so the "thinking" box is not a big empty
panel. Type is fitted to the actual strings (`chatSizes`): from prompt 54 /
answer 64 / label 44 px down, together, until the full prompt and the full
answer - wrapped as the browser would (`wrapLines`, Helvetica's advances by
glyph class) - fit the inner box above the caption band; floors 26 / 30. A
one-line chat is drawn at 54/64; the four-line poem of the tests at 40/47;
the worst case (157-character prompt, 277-character answer) at 31/37. On a
render the text stays inside y 356-1146, x 190-787 of the 300-1219 / 125-851
box. The circuit traces keep running through the hold (probe-band motion
measured at 4.1-4.3 against the 1.0 floor, no still run, `frozen_blocks` empty).

**The frame judge**: the chat's overlay is still `kind: own_graphic`, plus
`template: "api_chat"`, `record_id` and `API_CHAT_NOTE` - our own chat,
declared, the model's verbatim answer on our record: no `foreign_text`, and
the answer is never read as a fact the video states.


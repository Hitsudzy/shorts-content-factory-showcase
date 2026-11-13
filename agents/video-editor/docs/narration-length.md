# Narration length and the ceilings

How long a script may be, and the ceilings a video is cut to. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

## The rate every length hangs on (CF-0188, CF-0261) — and why it is no longer what sizes a script (CF-0279)

**Read this section together with the next one.** Since CF-0279 the length of a
script that has not been synthesized yet is not `words / words_per_second` at
all — it is `scripts/estimate_narration.py`, which asks Kokoro itself. The rate
below is still measured, still re-measured when the voice moves, and still the
number `patterns/validate_patterns.py` checks a block order against; what it is
no longer allowed to be is the thing that decides whether a script fits in 60
seconds.

`narration_budget.words_per_second` in `channels/<id>.json` is the number the
whole pipeline measures itself against: Content Researcher sizes the script from
it, `patterns/validate_patterns.py` refuses an unplayable block order by it, and
`narration_length.py` gates the finished wav against it. It is a MEASUREMENT,
and `scripts/measure_speaking_rate.py <batch-dir> --channel <id> [--json <out>]`
is how it is taken again by the same method - it synthesizes every video of a
batch and reports the median of words / wav seconds.

It measures **one voice at one speed reading one layout**. The layout is the
part CF-0261 found the hard way: Kokoro synthesizes one chunk per line, and each
chunk pays its own phrase-final lengthening and padding, so the same 181 words
read 44.50 s on one line and 58.92 s as five paragraphs - 4.07 w/s against
3.07 w/s, one voice, one speed, only the line breaks moved. The narration
reaches the voice as one line (`meme_layer.narration_text()` joins hook,
commentary and payoff with a single space); scripts written before 2026-09-16
reached it as paragraphs, nobody was watching that variable, and the rate on
record stayed 3.02 while the pipeline had moved to 3.88. The cost was two
batches estimated at 50.3 s and 49.3 s of voice that came out at 38.55 s and
38.40 s, both finished videos under the 45 s floor.

So the rate is re-measured when the voice changes, when the speed changes, **and
when the shape of the narration changes** - and the evidence for it is kept:
`synthesize_voiceover.py` writes the text it read to `work/<slug>/narration.txt`,
verbatim, beside `voice.wav`. That file is what `measure_speaking_rate.py` reads
first; for a batch made before it existed the tool rebuilds the narration from
`<batch>/03-content-researcher.json` through `meme_layer.narration_text()`,
matching each `work/<slug>/` to its script by the `script_id` the editor left in
`anchors.json` (or, failing that, by the wording the slug is drawn from, and it
skips rather than guesses when that is ambiguous). Before CF-0261 the tool had
only the first path and exited 2 on every batch of the period whose rate had
drifted.

## The chunk cliff, and the estimate that replaced the rate (CF-0279)

Kokoro does not read at a constant rate, and the reason is structural rather
than acoustic. `KPipeline.en_tokenize` cuts the text into chunks as soon as the
next token would take the phoneme count past **510**, synthesizes each chunk on
its own, and every boundary pays its own phrase-final lengthening and padding.
The three scripts CF-0261 measured the 3.88 w/s rate on were 144–152 words, all
**2 chunks**; the 182–200 word budget CF-0261 then derived from that rate is
**3–4 chunks**. Batch `2026-09-18T1058Z` read at 3.38–3.66 w/s, one video went
over the 60 s ceiling, and the rescue rewrite — 183 words, inside the word
budget, estimated at 47.2 s — came out at 55.67 s and went over the ceiling
again. Eight words came out of it and it got 0.8 s shorter, because it stayed in
the same number of chunks.

No words-and-chunks formula fixes that. The same corpus holds two 183-word,
3-chunk scripts that read **51.77 s and 55.67 s** — 3.9 s apart, indistinguishable
to any model built out of word counts. A least-squares fit of
`seconds = words / 4.75 + 7.38 × (chunks − 1)` over the seven wavs on disk is
still ±2.6 s; the flat rate is ±5.7 s.

So the estimate is not a fit. **`scripts/estimate_narration.py` runs the
synthesis's own arithmetic and stops before the expensive half**: the same g2p,
the same `en_tokenize` chunking, and the same prosody-predictor forward pass that
`synthesize_voiceover.py` runs — then it sums the predicted durations instead of
calling the decoder. The wav's length is exactly `sum(pred_dur) × 600 / 24000`
seconds, because `KModel.forward_with_tokens` builds the decoder's alignment out
of that same `pred_dur`. Against all seven videos on disk read by `am_puck@1.10`
the predicted length equals the recorded wav **to the centisecond**, including
the two that are 3.9 s apart. The stated tolerance is 0.05 s and it covers frame
rounding, nothing else.

    scripts/estimate_narration.py --channel example-film --text-file narration.txt
    scripts/estimate_narration.py --channel example-film --batch 03-content-researcher.json

JSON out: `words`, `chunks`, `chunk_phonemes`, `chunk_seconds`,
`estimated_seconds`, `tolerance_seconds`, and — with `--channel` — the finished
video's `estimated_total_seconds`, `narration_band` and an advisory `verdict`
(the addition and the band are `narration_length.py`'s, asked for rather than
copied). Exit 0 estimate produced, 2 bad input or config, **3 the engine is not
available here** — a caller that gets 3 refuses, and never falls back to
dividing by a constant. Cold ≈ 8–11 s (import, weights, voice pack), warm ≈ 1.2 s
per script, which is why `--batch` takes a whole Content Researcher document and
builds each narration through `meme_layer.narration_text()` itself.

**A chunk over the ceiling (CF-0931).** `en_tokenize` can let a chunk through
one phoneme over 510 (after a cut it re-counts the carried-over tokens from
their stripped phoneme string and loses a space). The synthesis
(`KPipeline.__call__`) does not fail on it — it reads `ps[:510]`. The estimator
used to crash there (`IndexError` on the 510-row voice pack), which stopped the
content-researcher stage of example-tech/2026-11-11T0841Z. It now measures the
same truncated chunk the synthesis reads and marks the record:
`overflow` (bool, always), `overflow_words_lost` (bool, always) and, only when
there is one, `overflow_chunks: [{chunk, text, phonemes, limit, dropped,
words_lost}]`. `words_lost: false` means the cut takes only punctuation (in the
batch above: the closing full stop) — every word is read. `words_lost: true`
means the reading would clip spoken words: the caller sends the script back to
be split, it is not read.

`scripts/fit_narration_model.py --channel example-film` is the reproducible check:
it walks every `pipeline/<channel>/<batch>/work/**/voice.wav` read by the
channel's current voice (a batch that does not record its voice, or records
another one, is skipped and said so), prints the residual table of the estimate
against the flat rate and the chunks fit, and with `--write-fixture` rewrites
`tests/fixtures/narration-estimate-2026-09.json`, which
`tests/test_narration_estimate.py` pins — together with the kokoro version, the
510-phoneme ceiling and the frame arithmetic, so a kokoro upgrade fails a test
instead of a batch.

**The gate on the finished audio did not move.** `narration_length.py` still
judges the real `voice.wav` against the 60 s ceiling and the 45–60 s band and was
not loosened by any of this: the estimate is what a script is written against,
the wav is what a video is held to.

`scripts/rhythm.py` owns the block plan (CF-0041): the four montage rhythms
(`even`, `hold`, `staccato`, `alternate`), the acceleration curve, and the
measurement that decides afterwards whether the ordered rhythm is actually in the
finished video. Pure arithmetic over anchor and word times — no ffmpeg, no CLIP,
no filesystem — so it is testable without a render. With no `--order` the plan is
`even`, which is the behaviour that existed before patterns.

The plan's `rhythm` record answers two separate questions, not one (CF-0057).
`rhythm_delivered` says whether the ordered rhythm is in the video at all;
`rhythm_delivered_fully` and `rhythm_shortfalls` say whether it was fully
executed. They can disagree, and that is the point: an `alternate` that crossed
the axis at every crossing the script wrote, and then stood on a single frame for
15s inside one of those crossings, is both `alternate` and short. `side_runs`
carries the same measurement for every run, including the ones that are fine, so
the Analyst can ask how long this pattern leaves the picture on one side without
re-deriving it from block boundaries.

"Fully executed" includes the picture arriving at all (CF-0136, deciding
CF-0123). A segment no candidate could fill is still cut on time, on the
assetless rung (CF-0085) - so the cadence is exactly what was ordered and
`rhythm_delivered` says so honestly, while the montage those cuts existed for
is not on screen. Until CF-0136 that produced no shortfall entry at all and
`rhythm_delivered_fully` came back `true` on a plan that was 25 stubs out of
30. Two kinds now record it: `picture_absent_run`, a stretch of consecutive
assetless blocks longer than the *ordered* `key_frame_hold_seconds` (the same
threshold `long_side_run_held` is read against - no new number is invented),
and `picture_absent_blocks`, every assetless block with no threshold at all,
because degradation scattered one block at a time makes no run and is no less
undelivered for it. `picture` carries the numbers behind both - `picture_blocks`,
`assetless_blocks`, `longest_assetless_run_seconds` and the runs - on every
rhythm and on the plans where nothing is missing, the way `side_runs` does.
Both fields reach `05-video-editor.json` through `write_batch_metadata.py`.

The accepted price, decided in CF-0123: on a batch like `2026-09-03T2037Z`,
where all four videos had degraded blocks (2/15, 7/15, 2/6, 4/12),
`rhythm_delivered_fully` is now `false` almost always. That is the field
telling the truth about the footage supply, not a regression - and it is why
the deficit went into the second field instead of into `rhythm_delivered`,
which would have taught the Analyst that the rhythm itself failed.

## The ceiling the boundaries are cut to (CF-0276)

A pattern's drawn `key_frame_hold_seconds` band used to be read twice, and
both times too late to move a boundary: `verify_pattern()` judges the finished
plan (CF-0192) and `trim_to_hold_band()` moves one boundary of an already-cut
montage (CF-0245). The block layout itself knew only the ceiling the *rhythm*
carries. So the first thing that ever noticed a layout the pattern could not
carry was the refusal in the next section - standing in front of the render
with the only remedies that exist by then, widen the pool or reassign the
pattern.

On `mormon-wives-comeback` neither was the answer. `rhythm.plan_segments()`
laid that script out as 15 staccato blocks whose longest was **3.40s**, inside
contrast's 1.5-3.5s band with room to spare. The video shipped with a first
block of **4.86s**. The whole of the difference is that the script's first
anchor lands 2.70s in, and `resolve_anchors.py` pulled block 0's start back to
0.00s *after* the layout was finished - after every ceiling this pipeline
applies. 2.16s of segment plus 2.70s of lead-in.

Two things follow, and the second is the point:

* `_base_segments()` opens segment 0 at 0.00s. The video starts with a picture
  whatever the script does, so that head is screen time the layout has to fit,
  not a correction applied once the layout can no longer answer for it. The
  old pull-back stays for the case its comment actually names - a segment that
  resolved to no block at all. `_plan_hold()` now picks its key frame by
  spoken time (`_spoken_dur()`), because otherwise a script whose first anchor
  lands 10.80s in (`you-can-see-everything`, 2026-09-09) has its held frame
  placed on the hole in its own anchor coverage rather than on the writing;
* `plan_segments(pattern=...)` is held to the drawn band as a last pass, after
  the acceleration that could otherwise break it. `drawn` only - CF-0039's
  rule, one copy of it now in `rhythm.hold_band()`, which `build_render_plan`
  re-exports so the layout and the trim cannot read two different bands.

What the ceiling may do to a boundary is the whole content of it. It may draw
a new one inside a stretch the rhythm merely happened to divide that way -
`even`'s beats, `staccato`'s items, a `hold`'s punctuation. It may not touch a
boundary the rhythm **named**: a declared `alternate` crossing (splitting one
invents a swing the script never wrote, the same grounds
`_plan_alternate_declared()` refuses the ordered block count on) or a `hold`'s
key frame (the boundary is the instruction). And it never reaches the band by
cutting under `MIN_ORDERED_BLOCK_SECONDS`.

Where it may not cut, it says so with numbers instead, in
`storyboard.rhythm.hold_ceiling` - carried into the plan and into
`05-video-editor.json` - before a single clip is cut:

* `breaches[]`, one per block still over the band, each with `measured`,
  `band_min`/`band_max`, `outside_by`, the block's `role` and a `code`:
  `boundary_is_the_rhythm` or `no_room_to_cut`;
* `lead_before_first_anchor`, written whether or not anything breached. It is
  the screen time in front of the script's first anchor - the number behind
  this whole defect - and it is only measurable here. After this change the
  montage no longer fails visibly on it, so a record that appeared only on
  failures would have made the writer's side of it (CF-0233, CF-0277)
  invisible exactly when the editor stopped stumbling over it.

`null` there, not an empty record, on a plan built before the layout answered:
a montage that never measured its own ceiling must not read as one that
fitted.

The measured result on the batch this was found in: 16 blocks, longest 3.40s,
cv 0.165, **zero** degraded blocks, `pattern_delivered: "contrast"`,
`rhythm_delivered: "staccato"`, no deviations and no trims - where today's
`main` refuses the same storyboard before the render. Nothing in the section
below changed; that gate simply is not the first to notice any more, and on
this topic it has nothing left to refuse.

## The ceiling a degradation breaks (CF-0270)

Degradation is per block and it is cheap by design (CF-0031): a clip that
cannot carry its block becomes a still, the video keeps its cadence, and
`degraded_blocks` says what happened. The one thing it may not do is leave a
video that no longer delivers the pattern it was assigned, and ship it anyway.

`example-film/2026-09-17T1901Z` / `mormon-wives-comeback` is that case - and
CF-0276 above has since taken this particular montage away from it: that block
0 was 4.86s only because 2.70s of lead-in were added to it after the layout,
and it is now cut in two before any clip is fetched. The gate below is
unchanged and is still the answer for a block that is honestly over the band;
what follows describes the run as it was when the gate was built.
`contrast` draws a 1.5-3.5s hold band. Block 0 ran 4.86s against a 2.17s clip,
so it was degraded clip -> still before the render; CF-0245's trim could not
hand the 1.36s overshoot to block 1, whose clip runs 1.867s against the 3.59s
an extended block would play of it; two more blocks were degraded after QC.
The video came back `pattern_delivered: null`, `qc.passed: true`, three render
attempts spent, and was recorded ready - against DoD 1.4.4 item 3, which says
a ready video delivers its assigned pattern and a topic that cannot is refused
with a code **before** the render.

So the pattern judge now has a gate behind it. After
`rhythm.pattern_shortfalls()` has spoken - the one pattern verdict in this
repo (CF-0192), read here and never re-derived - three things end the plan,
and they have to be true **of one and the same block**:

* the pattern's hold band was **ordered** (`mode: "drawn"`) and the video is
  over its top. An `emergent` envelope is an observation and never refuses a
  video (CF-0039); it only stops the video *claiming* the pattern, which is
  the whole of what an observation may cost. A video under the band's floor is
  a different fault, and one no boundary move can repair;
* the block that is over it - the one whose span *is* `cadence.longest`,
  matched on the number both the shortfall and the trim record carry - was
  degraded. That is what makes the measurement literal instead of
  conservative: the cadence treats every block as a hold, and a block playing
  real footage for 4.86s is not holding a key frame for 4.86s. The degradation
  is what turns it into one, and `key_frame_hold_seconds` is precisely how
  long one frame may be held;
* CF-0245's trim was asked about that block and the obstacle was **footage** -
  `next_block_has_no_clip` or `next_clip_too_short`. That is the ladder's own
  shape: replacement first, refusal second, so the refusal belongs where a
  replacement would have been the answer and the pool did not have one.

Three things it deliberately leaves alone, because something else already owns
each of them:

* `rhythm_not_as_ordered`, which sits in the same shortfall list. It is
  CF-0057's subject, recorded and shipped for dozens of batches, and widening
  this gate to it would refuse most of them;
* a block over the band whose picture still moves. CF-0245 looked at exactly
  that and decided to ship it long rather than freeze it shorter, and
  `pattern_delivered: null` already says what it is;
* the structural trim refusals - `no_next_block` (the last block runs to the
  end of the audio and has no next anchor at all) and
  `next_block_would_leave_band` (handing the remainder on would move the
  failure rather than end it). No clip in any pool answers either, so the
  ladder has no first rung to have failed; those are anchor-coverage faults
  (CF-0129/CF-0232/CF-0233) in a montage's clothes, and refusing on them would
  take out a large share of the corpus for a reason this stage cannot act on.

The remedy order is **replacement, then refusal**, and the replacement rung is
already spent by the time a storyboard reaches this stage: `resolve_anchors.py`
sorts each block's pool long-enough-first (`available_seconds(c) < need`), so a
block gets a clip that covers it and only holds a frame when no candidate in
the pool does. A storyboard whose block outruns its clip is the pool's answer,
not an unasked question, and this stage has neither the footage index nor the
cutter to ask it again. What it does instead is write the number down: the
deficit's `replacement[]` says which block would have needed how many more
seconds of footage, so widening the pool is an actionable next step rather than
a guess. (A pattern whose hold band this montage cannot hold is the other
answer, and it belongs to whoever assigns the pattern.)

The refusal itself is CF-0254's: gate `pattern_ceiling`, funnel code
`pattern_undeliverable`, `plan.refusal.json` beside where the plan would have
been, a `plan.pattern-ceiling.json` deficit with every number the decision was
made on, and exit 2 - **no plan, so no render, so zero attempts spent**. On the
real batch above the gate fires on attempt 1, before the first frame.

One thing it has that no other gate does. A post-QC degradation comes back to
this stage as `--degrade-block` on a *rebuild* of the plan, which means an
attempt has already been rendered and its mp4 is on disk. CF-0254's merge rule
is that a video wins over a refusal for the same `script_id` - a refused
attempt that was retried and rendered is answered by the mp4 beside it. Here it
is the other way round: that mp4 is the render this refusal rejects (the
rebuild exists *because* it failed QC), and letting it win would publish
exactly the video the gate refused. Such a refusal carries
`supersedes_video: true`, `plan_refusal.superseded_video_ids()` names those
scripts, and `write_batch_metadata.py` drops the video record before the merge
- so `merge()` keeps its one rule and the exception lives in one place with a
name. The funnel then reads one answer about that script, not two.

## The ceiling the writing breaks (CF-0303)

The second bullet above - *the block that is over the band was degraded* - is
what kept the same gate silent on `2026-09-21T0358Z`, `coach-hale-stadiums`.
`contrast` draws 1.5-3.5s; the Content Researcher's pre-TTS pass (CF-0277) put
the longest block at 3.405s with zero breaches and passed the script; the wav
was then made, the words were aligned, and the *same* layout rule on the real
speech put blocks 6, 7, 13 and 15 at 3.6 / 3.76 / 3.52 / 4.54s. Nothing was
degraded - every picture moves - so the plan wrote `pattern_delivered: null`,
`pattern_not_delivered: "hold_outside_band"` and went to the render, which is
the thing DoD 1.4.4 item 3 exists to stop.

So `pattern_ceiling_break()` now has **three causes and one gate** (the third
is CF-0310, below), and the record says which one it is in `cause`:

* `degradation` (CF-0270): the three conditions above. The picture froze
  because no clip in the pool covered the block, and `replacement[]` says how
  much footage would have ended it;
* `layout` (CF-0303): nothing froze, and the *layout itself* is over the
  ceiling. The evidence is `storyboard.rhythm.hold_ceiling.breaches` -
  written by `resolve_anchors.py` from the real alignment, before a single
  clip was cut, with each block's `measured`, `outside_by`, `role` and the
  `code` that says why the layout could not cut it shorter. The gate re-derives
  none of it; it reads the shortfall for "is this video over the top at all"
  and that record for "which blocks, and why were they left there".

Both end in the same refusal - gate `pattern_ceiling`, funnel code
`pattern_undeliverable`, `plan.refusal.json`, `plan.pattern-ceiling.json`,
exit 2, zero attempts spent - because both end in the same sentence: a video
that cannot deliver the pattern it was assigned does not get rendered. What
differs is the remedy, and the `layout` cause writes both halves of it: where
`replacement[]` carries numbers, a longer clip for the *next* block would let
CF-0245's trim move the boundary and end the breach; where the trim refused
with `no_next_block` or `next_block_has_no_clip`, no pool answers, and the
stretch between those two anchors has to be written shorter or given another
anchor. The refusal's last line names the stage that can do it, and says on
what that stage decided: the Researcher's pass measured an *estimate* of the
speech (word *k* at `k/rate`, CF-0279 - there is no alignment before TTS is
paid for), and the layout it approved and the one above are the same rule on
different inputs.

## The other band (CF-0310)

A pattern has two cadence parameters and this gate was guarding one of them.
`2026-09-21T1541Z`, `outrider-doune-castle`: `explainer` / `even`, 10 blocks,
`pattern_delivered: null`, `pattern_not_delivered: "block_count_outside_band"` -
rendered, through QC, past the frame judge, to the user. So `cadence` is the
third cause, on the same gate and the same refusal. It needs no second
condition: a block count is the number of resolved anchors, fixed in the
storyboard before a clip was cut, and no trim and no replacement clip moves it.
The remedy is the script, so the record carries the same `estimate_record` the
`layout` cause does.

How far it reaches was **measured**, over every plan in `pipeline/` on
2026-09-22, rather than argued:

* it does not fire on an `emergent` envelope. Ten of the eleven plans on disk
  that carry a pattern have at least one shortfall and only `delver` has none,
  so "any `pattern_not_delivered` refuses" refuses 10 of 11 - mostly on
  `explainer`'s two emergent envelopes and on `rhythm_not_as_ordered`, which
  is CF-0057's subject. CF-0039's rule survives all three causes;
* it does not fire **under the floor of a band stated as a count**. A count is
  a pace times a length, so a count floor is a length requirement written in
  blocks - `moment-breakdown.json` says as much, its floor of 6 being where "a
  35-60 second video" still has enough picture changes - and refusing a short
  video on it would repeat the defect this task is about. Three real layouts
  are under a drawn count floor and none is over a ceiling. A count **over**
  the ceiling does fire: more blocks than the pattern allows is about the
  cutting, since a longer video would need more still.

What actually refuses `outrider-doune-castle` is therefore not a gate but the
band. Its 10 blocks over 28.7s are 20.91 blocks/min, inside the 15.39-47.88
the eight videos `explainer`'s envelope was frozen over actually ran; the
count 12-33 was measured on 40.0-46.8s of blocks and carries those lengths
inside it. `rhythm.cadence()` reports `blocks_per_minute` for that reason and
`rhythm.block_count_parameter()` reads whichever shape the root's pattern file
states - `block_count`, or `block_rate_per_minute` with the code
`block_rate_outside_band`. A rate has the length divided out, so on a rate this
cause refuses at both ends. Until `patterns/` changes nothing moves: the
shipped plans are judged to exactly the codes they shipped with.

## The floor of that band is an order (CF-0314, 2026-09-22)

`patterns/` changed. The root now states `explainer`'s pace band as
`mode: "floor_drawn"` - **the floor 15.39 blocks/min is an order, the ceiling
47.88 stays an observation** (the user's decision of 2026-09-22). Below the
floor an explainer is a slide show: `lf-2026-09-09-006` (`coach-hale`,
2026-09-09) is 3 blocks over 40.4s, 4.46 blocks/min, 13-second frames - and it
shipped signed `pattern_delivered: "explainer"`. Above the ceiling nothing is
wrong: a faster cut is not a defect, and no plan in the factory's history is
there anyway (the maximum on disk is 47.88, the ceiling's own source).

Three things in this repo follow from that word, and no new mechanism does -
the refusal is CF-0310's `cadence` cause, unchanged:

* `rhythm.cadence_band_refuses()` has a third branch: a **pace under the
  floor** refuses, a pace over the ceiling does not, and a *count* in this
  mode refuses at neither end (a count floor is the length requirement CF-0310
  was filed about, and "a floor is a floor" would bring length-dependence back
  through the new mode). The comparison is made at
  `rhythm.BLOCK_RATE_DECIMALS`, the grid `cadence()` rounds to and `patterns/`
  is written on - `amc-leawood-films` is 15.389548 blocks/min and *is* where
  15.39 came from, so a full-precision comparison would refuse the video the
  band was measured from;
* a pace **over the ceiling** is recorded as a shortfall and does **not**
  unsay `pattern_delivered` - `rhythm.shortfall_denies_delivery()` is the one
  place that distinguishes a shortfall which withdraws the claim from one that
  stands beside it, and this is its only carve-out (floor_drawn, the pace,
  over the top). CF-0192 nulled the field because the claim was made *without*
  a measurement; here the measurement exists and says something the user has
  decided is not a defect. The plan reads `pattern_delivered: "explainer"`
  with `pattern_delivered_fully: false` and the number in the list, which is
  the same split CF-0057 made for the rhythm;
* an **unknown** mode is no longer silence. It used to be a `continue`, so the
  day the root invented a third word this repo stopped measuring the pace at
  all and would have signed plans it had not checked - CF-0192's defect
  arriving from the other side. It is now a shortfall,
  `band_mode_unreadable`, which withdraws the claim, names the word it read,
  and refuses nothing: not knowing a word is no evidence that the video is
  bad, and a judge that raises takes the batch with it.

The refusal an operator reads names the pace, the floor, whose decision the
floor is, and that the ceiling above it is an observation that refuses
nothing - because "outside the drawn band 15.39-47.88" would invite him to
read the ceiling as an order too.

**The one tolerance on the band's top.** `rhythm.over_band_top()` is now the
only place a hold band's top is compared - the judge, CF-0245's trim and both
causes of this gate call it - and it allows
`rhythm.HOLD_BAND_TOP_TOLERANCE_SECONDS`, which is half a frame of the
composition (0.017s at 30 fps). Not a slack: `Video.jsx` puts every block on
that grid with `Math.round` and the crossfade is a whole number of frames, so
the hold a viewer sees is `round(span * fps)` frames, and an overshoot below
half a frame shows no extra frame at all. It is exact because every drawn band
top in `patterns/` lands on a whole frame at 30 fps, and it flips nothing in
the corpus: the smallest overshoot on disk is 0.02s at the block level and
0.4s at the video level.

## What a pace does to the ending's ceiling (CF-0315, 2026-09-22)

The ending clip's structural ceiling (CF-0141, section C) is the other place a
block envelope is read, and it was reading the old shape. `end_card.
structural_ceiling()` takes the validator's feasibility arithmetic -
`key_frame_hold_seconds.max + (blocks - 1) * MIN_BLOCK_SECONDS`, the shortest
narration a pattern can be built in - over every pattern the channel admits,
and `target_total_seconds` minus the largest of those floors is the longest
ending the channel can afford. It asked each pattern for `block_count.min`
inside a `try` whose `except KeyError: continue` dropped `explainer` without a
word the day CF-0310 restated its envelope as a pace, so the one guard on the
ending's length quietly stopped consulting the most demanding pattern in the
vocabulary.

**A pace is turned into a number of blocks by solving the formula for its own
fixed point, and by importing no length from anywhere.** The narration has to
carry the blocks (`L >= hold.max + (n - 1) * MIN_BLOCK`) and the floor pace has
to be met (`L <= 60n / rate.min`); both hold from `n = ceil((hold.max -
MIN_BLOCK) / (60/rate.min - MIN_BLOCK))` upward. On `explainer` that is 3
blocks and **9.20s** of narration - two blocks would need 8.60s and the floor
pace holds two blocks to 7.80s. So `moment-breakdown` (12.00s) binds and
example-film's ceiling is **43.00s**, where the count band gave 40.40s. The rise
is CF-0310's measurement arriving here rather than a relaxation: the count
floor of 12 was observed on videos 40-47s long and carried their length inside
it. Nothing on disk moves - the one ending runs 5.167s, as do all seven plans
that carry one. The two readings that were weighed and rejected, with their
numbers, are in the note above `structural_ceiling()`: a count taken at the
channel's shortest video (8 blocks, ceiling 42.80s) imports the very length
CF-0310 removed, and leaving `explainer` out entirely (43.00s here) would leave
a channel that admits it alone with no ceiling at all.

**The number now comes with the patterns it was made of.**
`structural_ceiling()` answers with a reading - `seconds`, `binding_pattern`,
`counted` (each pattern's floor, its blocks, its band and that band's mode) and
`skipped` (each pattern that gave no number, with a code and a reason) - and
`end_card.ceiling_sentence()` puts it in one line, in the refusal and in the
operator's notes on the plans that **pass**, which is the only place a dropped
pattern would ever be noticed. An unreadable band mode is one of those codes
and is rhythm's own word, `band_mode_unreadable`: named, never raised, and the
ceiling still derived from the patterns that could be read.

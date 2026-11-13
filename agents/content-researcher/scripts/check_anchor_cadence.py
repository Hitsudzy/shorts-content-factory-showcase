#!/usr/bin/env python3
"""CF-0233: a floor under the number of anchors, asked before TTS is paid for.

The hole
--------
Nothing anywhere held a script to a number of anchors. The SKILL said "at
least one" and "about one per block"; CF-0140's preflight asks whether the
pool can picture every anchor the script named, never how many it named. So
batch `2026-09-09T2031Z` shipped scripts with 3 / 3 / 3 / 2 anchors where
`2026-08-30T2329Z` and `2026-08-31T2155Z` had 12-15, the speech did not
shorten (40.4s against 40.0-46.8s), and the same 40 seconds of narration were
carried by three frames instead of nineteen to thirty-three. Median block:
18.22s against 1.10-3.52s. The collapse crossed the whole pipeline and no
check named it; it was found by a human reading eight plans in a row.

CF-0192's measurement is the reason this is a writing rule and not a pool
rule: the single index handed to `coach-hale` (`xmbppMd75PE`) held 60 shots, 51
of them usable. The pool was not the bottleneck for even one shot. The
bottleneck was that the script asked for three pictures.

The rule: the gap, not the count
--------------------------------
Grill of 2026-09-16 (Notebook `Operator-Notes/grill-me-logs/2026-09-16 -
Пул источников (CF-0129, 0232, 0233, 0245).md`). A floor on the *count* is
the wrong quantity - an anchor is not an end in itself, and 5 anchors over 22
blocks still tore a 13.52s block open on `2026-09-15T1034Z`. The quantity that
is actually about the defect is **how long the speech runs between one frame
and the next**:

    every stretch of narration between two neighbouring anchors - and the
    stretch before the first and after the last - must be no longer than the
    top of the pattern's `key_frame_hold_seconds`.

`key_frame_hold_seconds` is "the longest block in the finished video"
(`patterns/validate_patterns.py`), so this is the pattern's own statement of
how long one picture may stand. A gap longer than it is a block longer than
the pattern allows, before a single frame has been resolved.

Where the band comes from
-------------------------
`patterns/<pattern_id>.json` -> `parameters.key_frame_hold_seconds.max`, read
through the root's own `validate_patterns.load_patterns()` (see
`hold_ceiling()`). **No copy of those numbers lives in this file.** They are
list 2.5, contrast 3.5, explainer 8.0, moment-breakdown 9.0 today; the day a
pattern's band moves, this gate moves with it and nobody has to remember that
a second copy exists. A root that cannot be reached is exit 3 - "cannot
judge" - never a pass and never a refusal.

The arithmetic, and the count it implies
----------------------------------------
Speech is `counted_sections` of the channel's `narration_budget` - the same
sections TTS reads and the same ones `check_narration_budget.py` counts -
concatenated in that order and split on whitespace. An anchor's position is
the number of those words before its `beat_text` starts (`beat_text` is
already pinned to be a verbatim substring of a counted section by
`check_anchor_coverage.check_anchor`). Words become seconds through the
rate of this script's own reading - `narration.estimated_words_per_second`,
which `check_narration_budget.py` writes from Kokoro's own duration predictor
(CF-0279) - falling back to the channel's median `words_per_second` on a batch
that was never written. The estimate is preferred because the median is off by
up to 5.67 s on the wavs we have, and this gate refuses at 2.5 s.

The whole narration is therefore cut into `len(anchors) + 1` stretches and
every one of them is held to the ceiling. Including the first and the last is
deliberate: with only the gaps *between* anchors checked, a script could put
three anchors in its last four seconds and leave 36 seconds of speech on the
opening block, which is the very shape this task exists to stop. The opening
block is a block and the pattern's ceiling is about blocks.

So the floor on the count follows from the rule instead of being declared:
`min_anchors = ceil(speech_seconds / ceiling) - 1`. For `list` at 40s of
speech that is 15 anchors (the grill's ">= 16" by the looser division of
40 / 2.5), well inside that pattern's own `block_count` of 12-24.

The second reading of the same rule: the layout itself
------------------------------------------------------
CF-0277. A stretch is not a block. The Editor lays the blocks out from the
anchors and then **merges** some of them, and the two rhythms that merge do it
on purpose:

  * `hold` grows one segment into the held key frame by swallowing whole
    neighbouring stretches until it reaches the `key_frame_hold_seconds` the
    script drew (`rhythm._plan_hold()`). A passage the writing dwells on that
    is *shorter* than the drawn hold therefore eats the next stretch whole,
    and the held block can land above the band top with every single gap
    inside it;
  * a declared `alternate` makes **one block per crossing of the axis**
    (`rhythm._plan_alternate_declared()`), so a block is the whole speech of a
    run of same-side anchors, however many gaps that is.

CF-0276 gave the layout the band as a ceiling on itself, and it cuts a block
back where the rhythm allows a new boundary. Where it may not - a declared
crossing, a held key frame - it writes the overshoot down instead
(`rhythm.ceiling_report()`, codes `boundary_is_the_rhythm` and
`no_room_to_cut`). Those are exactly the blocks no montage can fix, and until
this task nothing asked about them before the voice was paid for: on the
batches on disk four scripts pass the gap reading and are laid out with such a
block (`lf-2026-09-16-005-script1` 10.66 s against moment-breakdown's 9.0,
`lf-2026-09-17-004-script1` 5.81 s against contrast's 3.5,
`lf-2026-09-18-003-script1` 4.65 s and `lf-2026-09-19-008-script1` 3.93 s
against list's 2.5). Two of them reached a real storyboard - after TTS - and
the wav agreed with the estimate to a hundredth (10.63 s) and to a second
(2.92 s).

So the gate reads its own rule twice: once over the stretches, which needs
nothing but this file, and once over the layout the Editor will actually cut,
which is asked of `rhythm.plan_segments(pattern=...)` through
`scripts/plan_blocks.py` on the Editor's venv (CF-0284's call, one child
process for the whole batch). No arithmetic about merging, ceilings or block
boundaries is written here; what is written here is what the writer must do
about it. The layout reading applies only where the pattern *orders* a band
(`mode: drawn`) - CF-0039's rule, kept: an `emergent` envelope is an
observation, and a script is not rewritten to fit an observation.

The margin: the layout is measured on an estimate, not on a voice
-----------------------------------------------------------------
CF-0303. Both readings above are made before TTS, so both are made on `word k
at k / rate` - and that estimate is right about the *total* speech (49.153s
against a 49.15s wav) and wrong about the *share* each block gets (longest
block 3.405s estimated, 4.54s spoken). `lf-2026-09-21-007-script1` passed
this gate at 3.405s under contrast's 3.5s top and was refused after the voice
was paid for, which is the defect CF-0303 is. So a block only passes when it is
under the top **with a margin**: `HOLD_MARGIN_BAND_FRACTION` of the band's
width, double that on the last block. The subtraction and the comparison happen
in `plan_blocks.py`, on the Editor's venv and with the Editor's own
`rhythm.over_band_top()`, for the same reason the layout does: one comparison
with the top of a band in the factory, not two.

The estimate is right about the whole and wrong about the share, and those are
different errors:

    coach-hale-stadiums  49.153s estimated -> 49.15s of wav   (the total)
    delver              44.129s estimated -> 44.125s          (the total)
    outrider-doune-castle  28.699s estimated -> 28.7s       (the total, CF-0311)
    coach-hale-stadiums  longest block 3.405s -> 4.54s        (the share)
    delver              longest block 8.116s -> 8.955s        (the share)
    outrider-doune-castle  last block 7.722s -> 10.08s      (the share, CF-0311)

Per block, over the three videos whose layouts can be lined up (n = 27, the
third added by CF-0311): median +0.061s, p90 +1.504s, maximum +3.2s, minimum
-4.036s. A budget on the total cannot stand in for a margin on the block: the
total is already right, on all three.

Why a *share of the width* and not a number of seconds: the drift does not
scale with the band, but the room to give does. 1.2s - the drift's own size -
leaves `contrast` a 2.3s ceiling over a 1.5s floor and would refuse nearly
everything, while `moment-breakdown` would not notice it.

Where 0.125 comes from: the whole corpus of live batches, every script whose
pattern draws a band, replanned with today's planner (`scripts/plan_blocks.py`,
the layout of CF-0276) and set beside the outcome the video actually had.

  script                        pattern           longest est.   top-margin  outcome
  lf-2026-09-15-001-script1   contrast 1.5-3.5        2.733        3.250   no video
  lf-2026-09-15-002-script1   list 1.0-2.5           15.650        2.312   over the top already
  lf-2026-09-15-003-script1   list 1.0-2.5            1.913        2.312   shipped, not delivered
  lf-2026-09-15-004-script1   moment-breakdown 4-9    7.377        8.375   shipped, not delivered
  lf-2026-09-16-005-script1   moment-breakdown 4-9   10.656        8.375   over the top already
  lf-2026-09-17-004-script1   contrast 1.5-3.5        5.814        3.250   over the top already
  lf-2026-09-17-012-script1   contrast 1.5-3.5        2.733        3.250   shipped, not delivered
  lf-2026-09-18-003-script1   list 1.0-2.5            4.645        2.312   over the top already
  lf-2026-09-18-006-script1   list 1.0-2.5            1.913        2.312   no video
  lf-2026-09-18-008-script1   moment-breakdown 4-9    8.940        8.375   REFUSED (1058Z draft)
  lf-2026-09-18-006-script1   list 1.0-2.5            1.222        2.312   no video
  lf-2026-09-18-008-script1   moment-breakdown 4-9    8.116        8.375   SHIPPED, DELIVERED
  lf-2026-09-19-008-script1   list 1.0-2.5            3.932        2.312   over the top already
  lf-2026-09-21-007-script1   contrast 1.5-3.5        3.405        3.250   REFUSED (this task)

Two rows decide the number, and they pull opposite ways:

  * `lf-2026-09-18-008-script1` of `2026-09-18T2232Z` (`delver`) is the ONE
    video in the corpus that delivered its pattern, and it may not be refused
    in hindsight. Its estimate is 8.116s under a 9.0s top, so the margin may not
    exceed 0.901s - a fraction of at most 0.1802 of that band's 5.0s width. (Its
    real longest block came out 8.955s against the 9.0s top: it delivered by
    0.045s. The row that forbids a bigger margin is itself a hair's breadth.)
  * `lf-2026-09-21-007-script1` (`coach-hale-stadiums`) has to be caught. Its
    estimate is 3.405s under a 3.5s top, so the margin must exceed 0.112s - a
    fraction above 0.056 of that band's 2.0s width.

0.125 is a round number near the middle of `(0.056, 0.1802]`. The 0.25 the
Editor's half of CF-0303 proposed is outside it: on `moment-breakdown` that is a
1.25s margin and a 7.75s ceiling, and it refuses `delver` - the one video that
worked - by 0.366s. The corpus checks the number the other way round too: the
topic `lf-2026-09-18-008` was written twice, at 8.940s in `2026-09-18T1058Z`
(no video) and at 8.116s in `2026-09-18T2232Z` (delivered), and 0.125 refuses
the first draft and passes the second - the distinction the corpus made on its
own.

Why the LAST block gets double. It is where the drift lands: +1.504s on
`delver`, +1.135s on `coach-hale-stadiums` and +2.358s on
`outrider-doune-castle` (CF-0311's third measurement), the largest of any block
in all three videos, against a median of +0.061s over all 27. The block that
ends the speech opens at a word the estimate puts 1.511s (`coach-hale-stadiums`),
1.724s (`delver`) and 2.357s (`outrider-doune-castle`) LATER than the wav does,
so the tail after it comes out short by just that. A fifth to a third of that lag is pure bookkeeping:
`estimated_words_per_second` is words divided by the WHOLE wav, and a wav begins
with silence (0.223-0.238s on the four wavs on disk - a remarkably fixed number)
and ends with more (0.365-0.790s - not a fixed number at all). Spreading that
silence over the words instead of leaving it at the two ends puts every word
progressively later, by the full lead+tail by the end of the script: 0.459s of
the 1.511s, 0.266s of the 1.724s. The rest - two thirds to four fifths - is that
speech is simply not spoken at a constant rate.

That bookkeeping error is deliberately NOT corrected in `anchor_times()`. The
correction needs the tail as a constant and the tail varies by a factor of two
over the only four wavs there are, which is more than the correction is worth;
buying at most 0.46s of a 1.5s error would move every anchor time of every
script, and `anchor_times()` is what the gap rule above,
`check_block_capacity.py` and `check_alternate_sides.py` are all measured in. A
margin is the right shape for an error this size and this uncertain; a
correction is not. Double is what the corpus allows rather than what it demands:
on the fourteen scripts above it changes no verdict at all, and `delver`'s last
block at 7.451s clears the 7.75s ceiling it implies. (The Editor's half proposed
0.5 here; that ceiling is 6.5s and refuses `delver` outright.)

The honest limit of all of it: THREE videos have a layout comparable block by
block - CF-0276 changed what a block is, so older ones cannot be lined up - and
exactly one video in the corpus delivered its pattern. This is a bound the data
does not contradict, not a measured threshold. The procedure for re-measuring it
is written down in `tasks/CF-0303-*.md`; run it on the next batches and move the
number if they say so.

CF-0311 ran that procedure on the third video, `outrider-doune-castle` of
`2026-09-21T1541Z`, and **0.125 does not move**. The fourteen rows above are
every script whose pattern *draws* a hold band, and `outrider` is not one of
them - `explainer`'s `key_frame_hold_seconds` is emergent, so no margin was
subtracted for it and it bounds the fraction from neither side. What it does
change is the drift it is a measurement of: the last-block error is bigger than
either video CF-0303 had (+2.358s, where the doubled margin is 0.5s on
`contrast` and 1.25s on `moment-breakdown`), and the error is not one-signed -
`outrider`'s opening block came out 2.298s SHORTER than the estimate while its
last came out 2.358s longer, the same shape `delver` has at -4.036s and +3.2s.
Two things follow and both are already what this file does: the margin belongs
on the last block above all, and it is a correction for an error whose size is
known and whose sign per block is not, which is why it is not a budget the
writer is asked to hit.

The other band (CF-0310)
------------------------
A pattern states two things about its cutting, and until CF-0310 this gate
read one of them. `key_frame_hold_seconds` says how long one picture may
stand; the block band says how many blocks the video is cut into - as a count
(`block_count`, drawn by `list`, `contrast`, `moment-breakdown`) or, since
CF-0310, as a pace (`block_rate_per_minute`, `explainer`'s observed
15.39-47.88 blocks/min). `outrider-doune-castle` (`2026-09-21T1541Z`) passed
this gate, was voiced, cut, rendered, judged and sent to the user carrying
`pattern_delivered: null` on that second band, because no stage asked about it
before the render.

It is now read on the same layout, and every part of the question is the
Editor's: `rhythm.cadence()` measures, `rhythm.block_count_parameter()` says
which shape the pattern states it in - no `if "block_count" in ...` is written
in this repository - and `rhythm.cadence_band_refuses()` decides whether a
shortfall is one a stage may refuse on (one table, three modes and two shapes
of band, all of it in the Editor since CF-0314). A refusal here and the
Editor's refusal after the render are the same rule read one wav apart.

**What this reading is, exactly.** It counts the rhythm's segments, and the
Editor's judge counts the render plan's picture blocks - inside one segment
`resolve_anchors.py` hands out as many shots as the pool affords and each
becomes a block. On `outrider` that is 3 against 10 (6.27 against 20.91
blocks/min); on `2026-09-09`'s `coach-hale`, 3 against 3. The spread is
1.0x-3.7x over the four `even` videos on disk and it is the *pool's*, which
this pass does not know - so no margin fraction is invented here, unlike
CF-0303's under the hold top: a share of a band nobody measured is the number
CF-0195 exists to refuse.

What is measured is the direction of the error: the delivered count is never
below the segment count. So a layout over the band's top is over it in the
finished video too and refusing on it costs nothing false, while a layout
under a floor says nothing about the cutting at all. The gate therefore
acts when the Editor's predicate says refuse AND the reading carries it
(`block_band.reading_supports_refusal`) - a condition that can only soften a
verdict, never add one, and holds no copy of the band rule. Since CF-0447
(the user's decision of 2026-09-30) it acts by PRICING the layout, not by
refusing it: `score.block_band_exceeded`, 2 points for each block over the
top, cap 10 (`block_band.blocks_over`, `block_band.priced_here`); the record
keeps `refused_here` / `block_band_refused`, always false.

The reading is written to `anchor_cadence.block_band` - the path the Editor's
own refusal names (`build_render_plan.BLOCK_BAND_RECORD_PATH`) when it has to
say that nobody measured this band before the TTS. Outside an *observed*
envelope nothing is refused (CF-0039) and the line is printed anyway: "outside
and nobody was told" is the whole history above.

**The floor that was ordered (CF-0314, the user's decision of 2026-09-22).**
`explainer`'s rate band is `floor_drawn` since that day: below its floor the
video is a slideshow and the plan is refused before the render, above its
ceiling it is merely cut faster than the seven measured videos and that is not
a defect. Nothing about THIS gate's ladder changes - the floor is still a floor,
this stage still counts the rhythm's segments, and `reading_supports_refusal`
still says no - so a layout under it is passed here and refused one wav later.
What changes is what the operator is told: not "recorded, not refused" and
nothing else, but that the Editor will refuse the finished plan as
`pattern_undeliverable` if its pace is still under the floor, with the TTS
already paid for. A mode word neither repository knows is its own line as well
(`band_mode_unreadable`, the Editor's code) - the band is there, it was not
read, and that is not the same record as "inside".

One message, and the one stretch it could not aim (CF-0311)
-----------------------------------------------------------
`lf-2026-09-21-007-script2` of `2026-09-21T1541Z` - the best-sourced topic of
its batch, two sources of real scenes and 106 usable shots - was refused as
`thin_scene` after its one rewrite, on a tail of speech 0.223 s over
`contrast`'s top. Two explanations were possible and only one survives the
artifacts:

  * *the gate was silent about a reading until the next run.* It is not: every
    one of the four readings above is made on **every** run and printed in one
    report - `report_lines()` walks every over-long stretch, every layout
    breach, every margin breach and the block band, and `judge_script()`
    computes all of them whether or not an earlier one already fired. There is
    no reading this gate saves for the second attempt.
  * *the rewrite created the tail.* It did not. The batch's `RUN_LOG.txt` has
    `check-anchor-cadence` at 21:44:33Z (exit 1) and 21:46:16Z (exit 4) with no
    `check-budget` between them - and `check_narration_budget.py --write` is
    what puts `narration.estimated_words_per_second` on a script, so the
    narration was not rewritten between the two attempts: 34.574 s of speech
    before and after, and only `visual_anchors` changed, 8 -> 13. Anchors that
    are only added can only make every stretch shorter, so the tail was at
    least its final 3.723 s on the first run too, and was named there.

So the defect is not what the report left out. It is that a stretch reading is
the only one of the four that hands the writer a *count* - "13 anchors where
the band implies at least 9" - and a count aims nothing at an edge. The
operator did what the first report asked: added five anchors, one of them on
the payoff. Its `beat_text` began at the top of the payoff, and the speech
after it was still over the top. An interior stretch is aimed by its own two
ends, which the report names; an edge stretch has one end and a deadline in the
speech that nothing computed.

That deadline is now computed and quoted (`edge_address()`,
`record["edge_anchors"]`): for the tail, the end of the speech less the
ceiling the LAST block is held to (CF-0303's doubled margin, because the anchor
that fixes the stretch also has to survive the layout reading on the same run),
and the words of the narration from that second on - which at these bands is
the payoff entire. On the refused draft: no earlier than 31.574 s, word 119 of
130, where the draft's last anchor sat at word 116. The lead before the first
anchor gets the same sentence against the plain margin ceiling.

Whether the rewrite should have been counted at all was asked of the same
corpus: over the live batches `2026-09-15`..`2026-09-21`, three topics were
refused by this gate (`lf-2026-09-19-010`, `lf-2026-09-19-007`,
`lf-2026-09-21-007`) and **none** of them is a case of a second failure by a
reading the first report had not named - all three died on the stretch reading,
which on two of them provably fired on the first attempt as well (the third's
narration was rewritten between the attempts, so its first report cannot be
reconstructed - and nothing suggests it was any other reading). A rule that
forgave a rewrite spent against an unnamed reading would therefore have saved
nothing, and the ladder below is unchanged. What is changed is that the
question is answerable next time without reading a run log:
`record["attempts"]` keeps one entry per failure with the readings it named
(`readings_named`, `readings_new_this_attempt`), and the refusal sentence the
funnel copies says whether the reading that refused the topic was named before.

The tail, named (CF-0353)
------------------------
`everyday-sorcery-2` (`lf-2026-09-15-002-script1`) reached the voice in the
rebuild `pipeline/rebuilds/2026-09-23T1344Z` and was refused by the Editor at
`pattern_ceiling`: the last block, 13.52 s of speech after the last anchor
against `list`'s 1.0-2.5 s, with nowhere to hand the rest (`no_next_block`).
The question was already here. Both readings above ask it - the stretch
`v5 -> end` (15.301 s) and the layout's block 21 (`hold`, 15.65 s,
`boundary_is_the_rhythm`) - and so do the lead and every gap in between: the
start and the middle need nothing new. The script had simply never met this
gate: it was written on 2026-09-15, before CF-0233 and CF-0277 existed, and a
rebuild copies `03` byte for byte and runs the pool gates only.

What is added is a name for the one stretch of them that no montage and no
trim can rescue, `anchor_cadence.tail`: the blocks of the Editor's own layout
that carry the last anchor, whether any of them is over what the layout and
margin readings hold it to, the Editor's code it will be refused with, and the
two ways out - one more anchor in the final (the address the edge reading
already computes) or at least N fewer words after the last anchor (the excess
at this script's rate). It is not a fifth reading and spends no rewrite of its
own: every block it names is already a `layout_block` or `estimate_margin`
failure. And it separates two scripts the stretch reading does not:
`widows-bay` (`lf-2026-09-15-003-script1`, `staccato`) has a 13.934 s tail
too, but the Editor lays it out as eight blocks of 1.64-1.91 s, and that video
went out; `everyday-sorcery-2` (`hold`) lays its tail out as ONE block.

What a failure costs: one rewrite, then the topic
-------------------------------------------------
**Since CF-0447 (2026-09-30) nothing in this gate fails a script on the
rhythm.** CF-0433 priced the hold band's readings, CF-0447 priced the block
band's top (`score.block_band_exceeded`); the only rewrite left is a malformed
field (`problems`, which never spends a round), and the score decides in 6b's
rounds (`plan_check_loop.py`). The ladder below is kept as the record of what
it was, and `failed_attempts` / `attempts` still carry what older runs wrote.

A failure of either reading is the writer's, they are the same failure of the
same band, and the writer is given exactly one more try for both together:

  * **first failure** -> `action: "rewrite"`, exit 1. The script is rewritten
    with more anchors (the report prints which stretch is too long and how
    many anchors the rule implies) or with the passage under the block moved
    (it prints which block, which anchors it covers, and what to change about
    them), and the gate is run again.
  * CF-0417: over the block band's top the report says WHICH lever - too many
    anchors, the layout cutting sparse ones, or a speech no placement fits -
    with the count the Editor's planner accepts on this very speech
    (`band_search()`). Since CF-0447 that top is a price and this sentence is
    its hint (`Axis: ...` in the note of `score.block_band_exceeded` and in
    `block_band.axis`), read by 6b's rounds when the score is under N; the
    extra round for a cause that moved is gone with the refusal.
  * **second failure** -> `action: "refuse"`, exit 4. The topic leaves the
    batch: with `--write` the script is removed from `scripts[]` and a
    `{topic_id, reason_code: "thin_scene", reason, stage: "scripts"}` entry is
    appended to `skipped[]`, which is where CF-0232's funnel reads the loss of
    a topic at the `scripts` step. Nothing is rewritten a third time - a scene
    that twice could not be told in more than three moments is a scene that
    did not carry enough to write, and every rewrite costs a model call.

The count of failures lives in the artifact itself
(`anchor_cadence.failed_attempts`), so it survives between runs, which is the
only place it can live: each run of this gate is a new process.

`thin_scene` and not `pattern_undeliverable`: the second is the Video Editor's
code for a plan that could not be built (CF-0245), written after the render
plan exists. This refusal happens before TTS, and what it is about is the
writing.

The other refusal, and why it is not this one
---------------------------------------------
A pool with fewer distinct usable samples than the script has anchors is a
pool defect, answered as `pool_too_thin` **without** a rewrite - that gate is
CF-0140's preflight, `check_anchor_coverage.py`, because the pool is what it
already reads (a warning since CF-0330, not a refusal; this gate's own
`thin_scene` is about the writing and is unchanged). Rewriting a script because the pool is thin is a model call
that cannot help. The two must not be confused, which is why they live in two
files with two codes.

Usage:

    python3 scripts/check_anchor_cadence.py <03-content-researcher.json>
    python3 scripts/check_anchor_cadence.py <03-content-researcher.json> --write

Exit codes:

    0  every script's anchors sit inside the pattern's hold band
    1  at least one script is rewritten (its first failure), or its
       `visual_anchors` / narration cannot be read as a cadence at all
    2  usage
    3  cannot judge: no reachable factory root, no `key_frame_hold_seconds`
       for the drawn pattern, no channel budget, or the Video Editor's block
       planner could not be asked (CF-0277). Nothing is claimed about any
       script - fix the environment and run again.
    4  a topic was refused (`thin_scene`) and, with `--write`, recorded. There
       is nothing to rewrite; the batch goes on with fewer scripts.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

from check_narration_budget import find_root, load_budget, validator  # noqa: E402
from check_anchor_coverage import (  # noqa: E402
    FIELD, FALLBACK_SECTIONS, CannotAnswer, counted_sections)
from _planner import DEFAULT_TIMEOUT, planner_paths, run_planner  # noqa: E402
import _rewrite_guard as rg  # noqa: E402
import _score  # noqa: E402 - CF-0433: the score model (shared/score)
import _speech_fit as sf  # noqa: E402 - CF-0446: the rotation's floor under the hold

RECORD_KEY = "anchor_cadence"
HOLD_KEY = "key_frame_hold_seconds"
SKIP_REASON_CODE = "thin_scene"
FUNNEL_STAGE = "scripts"

# CF-0310: the other band's reading, written beside `layout` on the same
# record. The Editor names this path in the refusal it hands the operator
# after the render (`build_render_plan.BLOCK_BAND_RECORD_PATH`) - "nobody
# measured this band before the TTS" is the whole history of
# `outrider-doune-castle` - so the path is one string, pinned against the
# Editor's own constant by tests/test_block_band.py.
BLOCK_BAND_KEY = "block_band"
# CF-0447: the price in words, for the hint only - the number itself is the
# root's `shared/gate-prices.json -> score.block_band_exceeded`.
BLOCK_BAND_PRICE_WORDS = "2 points a block (cap 10)"
BLOCK_BAND_RECORD_PATH = "03-content-researcher.json#scripts[].anchor_cadence.block_band"

# CF-0314: the band's modes, as words this file only ever READS - the band is
# judged by `rhythm` inside `plan_blocks.py` and arrives here as a record. They
# are spelled out because the sentence handed to a human has to say what kind of
# number it just quoted: `drawn` was ordered, `emergent` was only observed, and
# on `floor_drawn` the two ends are not the same thing - the floor is an order
# (the user's decision of 2026-09-22) and the ceiling above it is an
# observation. `band_mode_unreadable` is the Editor's own code for a mode word
# nobody in this pipeline knows; it is the difference between "not checked" and
# "inside", and it is printed rather than swallowed. All four mirror
# `rhythm.BAND_MODE_*` / `rhythm.PATTERN_BAND_MODE_UNREADABLE` and are pinned
# against that module by tests/test_block_band.py.
BAND_MODE_DRAWN = "drawn"
BAND_MODE_EMERGENT = "emergent"
BAND_MODE_FLOOR_DRAWN = "floor_drawn"
BAND_MODE_UNREADABLE_CODE = "band_mode_unreadable"

VERDICT_FITS, VERDICT_OVER = "fits", "over"
# CF-0433 (grill 2026-09-29, "делать из того, что дают"): the hold band is a
# price, not a refusal. A script whose layout breaks it passes, priced.
VERDICT_PRICED = "priced"
ACTION_PASS, ACTION_REWRITE, ACTION_REFUSE = "pass", "rewrite", "refuse"

# CF-0311: the four readings this gate makes of the one band, named. They are
# all made on every run and all printed in one report (see "One message" in the
# docstring); the names exist so the record can say WHICH of them fired on
# which attempt, which is the only way the question "was the refusal already
# named on the first run" is answerable off disk a batch later.
READING_STRETCH = "stretch"
READING_BLOCK = "layout_block"
READING_MARGIN = "estimate_margin"
READING_BAND = "block_band"

# CF-0311: the two stretches a new anchor is addressed at by time rather than
# by count - the speech before the first anchor and the speech after the last.
EDGE_LEAD, EDGE_TAIL = "lead", "tail"

# CF-0233: one rewrite, then the topic goes. Not a knob - the number is the
# decision of the grill of 2026-09-16, and a config able to raise it is a
# config able to spend an unbounded number of model calls on a scene that has
# nothing more in it.
REWRITES_ALLOWED = 1

# CF-0417: why a layout is over the block band's top - the lever the rewrite is
# pointed at, read off the Editor's own planner (`band_search()`):
#   anchors - more anchors than the top allows by themselves: write fewer;
#   cut     - the anchors would fit, the layout cut the stretches between them
#             into more blocks (staccato's cap, hold's "nothing as long as the
#             hold"): fewer anchors makes it worse, the probed placement fixes it;
#   speech  - no placement of anchors brings this speech under the top at the
#             drawn order: the lever is the length of the speech (or the
#             assignment), not the anchors.
# CF-0447 (the user's decision of 2026-09-30): over the top is a price now
# (`score.block_band_exceeded`, 2 a block over, cap 10), never a refusal, so
# the cause is a HINT in the penalty log - the lever to win the points back
# in 6b's rounds if the score is under N. CF-0417's extra round for a cause
# that moved between attempts is gone with the refusal it extended: this gate
# refuses nothing now (a malformed field is a rewrite that spends no round),
# so there is no ladder left for it to lengthen.
CAUSE_ANCHORS, CAUSE_CUT, CAUSE_SPEECH = "anchors", "cut", "speech"

EXIT_OK, EXIT_REWRITE, EXIT_USAGE, EXIT_CANNOT_JUDGE, EXIT_REFUSED = 0, 1, 2, 3, 4

# --------------------------------------------------------------------------
# CF-0303: the margin the estimate is held under
# --------------------------------------------------------------------------
# Both readings of the band happen before TTS, so both are measured on an
# estimate of the speech, and the estimate gets the total right and the share of
# each block wrong. These two numbers are the correction for that; the evidence
# behind them - the whole live corpus set beside what each video actually did,
# the two rows that bound the fraction from either side, and why the last block
# gets double - is in the module docstring, under "The margin". They are not
# knobs: raising one refuses scripts that worked, lowering it lets through the
# plan the Editor now refuses after the voice has been paid for.
HOLD_MARGIN_BAND_FRACTION = 0.125
HOLD_MARGIN_LAST_BLOCK_FRACTION = 2 * HOLD_MARGIN_BAND_FRACTION

START, END = "start", "end"


class CannotJudge(CannotAnswer):
    """The environment could not answer. Never a refusal of a script.

    A subclass of the stage's own base since CF-0277, for two reasons that are
    the same reason: `_planner.py` raises the base (it cannot import any gate's
    subclass without a cycle), and `check_block_capacity.py` has always called
    `speech_rate()` from here inside its own `except CannotAnswer` while this
    class stood outside that hierarchy - so a batch with no rate escaped it as
    a traceback instead of exit 3.
    """


# --------------------------------------------------------------------------
# the band, from the root's patterns and nowhere else
# --------------------------------------------------------------------------

def hold_ceiling(pattern_id, root=None):
    """`(seconds, source)` - the top of this pattern's `key_frame_hold_seconds`.

    Read out of `patterns/<pattern_id>.json` through the root's own
    `validate_patterns.load_patterns()`, so the pattern set this gate holds
    scripts to is the same object the validator, the rotation and the render
    plan use. Raises `CannotJudge` rather than falling back on a number: a
    literal here is the copy this task was told not to make.
    """
    vp = validator(root)
    if vp is None or not hasattr(vp, "load_patterns"):
        raise CannotJudge(
            f"no reachable patterns/validate_patterns.py under {Path(root or find_root())} - "
            f"the hold band of a pattern is only written down there, and this gate carries "
            f"no copy of it")
    try:
        patterns = vp.load_patterns()
    except Exception as exc:  # noqa: BLE001 - an unreadable pattern set is not a verdict
        raise CannotJudge(f"patterns/ would not load: {exc}")
    pattern = patterns.get(pattern_id)
    if pattern is None:
        raise CannotJudge(
            f"no pattern {pattern_id!r} in {sorted(patterns)} - a script drawn on a pattern "
            f"this checkout does not have cannot be held to its hold band")
    band = ((pattern.get("parameters") or {}).get(HOLD_KEY)) or {}
    top = band.get("max")
    if not isinstance(top, (int, float)) or isinstance(top, bool) or top <= 0:
        raise CannotJudge(
            f"patterns/{pattern_id}.json#parameters.{HOLD_KEY}.max is {top!r} - without the "
            f"top of the hold band there is no gap rule")
    return float(top), f"patterns/{pattern_id}.json#parameters.{HOLD_KEY}.max"


def speech_rate(script, channel, root=None):
    """`(words_per_second, source)` - the rate this script's words are turned
    into seconds at.

    CF-0279 put a better answer above the channel's median and left the median
    where it was. Three steps, first that applies:

    1. **This script's own rate**, `narration.estimated_words_per_second`,
       written by `check_narration_budget.py` from the estimator's reading of
       this very text. It is the right number and by a wide margin: Kokoro
       cuts the text into chunks of at most 510 phonemes and pays for every
       boundary, so two scripts of the same length read 3.9 s apart and the
       channel median is off by up to 5.67 s on the wavs we have. This gate
       divides a gap by that rate and refuses at the pattern's hold band,
       which on the tightest pattern is a couple of seconds, so a tenth of a
       rate decides whether a stretch is refused. The budget check runs
       before this one in step 6 and with `--write` puts the number there.
    2. the channel's median, `narration_budget.words_per_second` - what a
       script checked without `--write` is judged at, and an average over a
       corpus rather than a reading of this text;
    3. the rate the batch itself recorded. An old batch measured at another
       rate should be replayed at the rate it was written under.
    """
    estimated = (script.get("narration") or {}).get("estimated_words_per_second")
    if isinstance(estimated, (int, float)) and not isinstance(estimated, bool) and estimated > 0:
        return float(estimated), (f"{Path('03-content-researcher.json').name}"
                                  f"#narration.estimated_words_per_second (CF-0279: this "
                                  f"script's own reading, not the channel median)")
    if channel:
        try:
            budget = load_budget(channel, root)
            rate = budget.get("words_per_second")
            if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
                return float(rate), f"channels/{channel}.json#narration_budget.words_per_second"
        except (FileNotFoundError, KeyError, ValueError):
            pass
    recorded = (script.get("narration") or {}).get("words_per_second")
    if isinstance(recorded, (int, float)) and not isinstance(recorded, bool) and recorded > 0:
        return float(recorded), f"{Path('03-content-researcher.json').name}#narration.words_per_second"
    raise CannotJudge(
        f"no words_per_second for channel {channel!r} and none recorded on the script - "
        f"words cannot be turned into seconds and no gap can be judged")



# --------------------------------------------------------------------------
# where the anchors sit in the speech
# --------------------------------------------------------------------------

def narration_words(script, sections):
    """`(texts, offsets, total)` over the sections the voice reads, in the
    order the channel lists them - the same tokens
    `check_narration_budget.py` and `validate_patterns.narration_word_count`
    count, so a position is measured in the units the budget is measured in."""
    texts, offsets, total = [], {}, 0
    for section in sections:
        text = script.get(section)
        text = text if isinstance(text, str) else ""
        offsets[section] = total
        total += len(text.split())
        texts.append((section, text))
    return texts, offsets, total


def anchor_word_index(anchor, texts, offsets):
    """How many spoken words come before this anchor's `beat_text`, or None.

    The first occurrence in the first counted section that holds it - the same
    resolution order `check_anchor()` uses to accept the beat at all. None
    means the beat is not in the speech, which is `check_anchor_coverage.py`'s
    refusal and not this file's: reported here as a problem, never silently
    treated as position zero.
    """
    beat = anchor.get("beat_text")
    if not isinstance(beat, str) or not beat.strip():
        return None
    for section, text in texts:
        at = text.find(beat)
        if at >= 0:
            return offsets[section] + len(text[:at].split())
    return None


def gaps(positions, total_words, rate, ceiling):
    """Every stretch of speech the anchors cut the narration into.

    `positions` is `[(anchor_id, word_index), ...]`, any order; the stretches
    are `start -> first`, each neighbouring pair, and `last -> end`. One
    record per stretch, with the seconds it lasts and whether it is over the
    ceiling, so a report can name the stretch the writer has to break up
    rather than only the count.
    """
    ordered = sorted(positions, key=lambda p: p[1])
    bounds = [(START, 0)] + ordered + [(END, total_words)]
    out = []
    for (left, a), (right, b) in zip(bounds, bounds[1:]):
        words = max(0, b - a)
        seconds = round(words / rate, 3)
        out.append({"from": left, "to": right, "words": words, "seconds": seconds,
                    "over": seconds > ceiling + 1e-9})
    return out


def min_anchors(speech_seconds, ceiling):
    """The floor on the count the gap rule implies - reported, never checked
    on its own. `n` anchors cut the speech into `n + 1` stretches, so covering
    `speech_seconds` in stretches of at most `ceiling` needs
    `ceil(speech / ceiling) - 1` of them."""
    if speech_seconds <= 0:
        return 0
    return max(1, math.ceil(speech_seconds / ceiling - 1e-9) - 1)


# --------------------------------------------------------------------------
# CF-0311: an edge stretch is answered with an address, not with a count
# --------------------------------------------------------------------------

# How many words of the narration the address quotes. Long enough that the
# operator recognises the sentence, short enough that the line is read: at
# `contrast`'s 3.0s last-block ceiling and example-film's rate the whole tail is
# eleven words, so this quotes the payoff entire and truncates nothing that
# matters.
ADDRESS_WORDS = 16


def edge_ceiling(edge, ceiling, margin_report):
    """`(seconds, source)` - the length the next draft must put this edge under.

    Not the band's top. The gap rule refuses over the top, but a draft written
    AT the top is laid out on it and then fails CF-0303's margin on the very
    same run - and the first and last stretch are the two blocks that margin is
    largest on. So the address is aimed at the margin ceiling the layout
    reading already computed, `plan_blocks.margin_report()`'s own subtraction on
    the Editor's venv (the last block's for the tail, the plain one for the
    lead), and falls back to the top itself only where there is no drawn band to
    take a margin of - where CF-0039 says nothing is ordered anyway.
    """
    report = margin_report if isinstance(margin_report, dict) else {}
    if report.get("asked"):
        key = "last_block_ceiling_seconds" if edge == EDGE_TAIL else "ceiling_seconds"
        seconds = report.get(key)
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
            margin = report.get("last_block_margin_seconds" if edge == EDGE_TAIL
                                else "margin_seconds")
            return float(seconds), (
                f"the {ceiling}s top less the {margin}s margin the estimate is held under "
                f"(CF-0303" + (", doubled on the block that ends the speech)"
                               if edge == EDGE_TAIL else ")"))
    return float(ceiling), ("the band's top itself - this pattern draws no band for the "
                            "layout to be held under, so there is no margin to subtract")


def word_address(deadline_seconds, rate, words, total_words, edge):
    """`(word_index, quoted)` - the word the deadline falls on, and the speech
    around it.

    An anchor's position is the number of spoken words before its `beat_text`
    (`anchor_word_index`), so the deadline in seconds becomes a deadline in
    words at the same `k / rate` the whole gate is measured in, and the quote is
    the text the next draft has to pin a `beat_text` inside. For the tail that
    is the speech from the deadline to the end - the payoff, entire, at every
    band this channel writes; for the lead it is the speech up to the deadline.
    """
    if total_words <= 0 or rate <= 0:
        return None, ""
    if edge == EDGE_TAIL:
        index = min(total_words - 1, max(0, math.ceil(deadline_seconds * rate - 1e-9)))
        chosen = words[index:index + ADDRESS_WORDS]
        return index, " ".join(chosen) + (" ..." if index + ADDRESS_WORDS < total_words else "")
    index = min(total_words - 1, max(0, math.floor(deadline_seconds * rate + 1e-9)))
    start = max(0, index + 1 - ADDRESS_WORDS)
    return index, ("... " if start > 0 else "") + " ".join(words[start:index + 1])


def edge_address(stretch, words, total_words, rate, speech_seconds, ceiling, pattern_id,
                 margin_report):
    """Where the next anchor has to sit for an edge stretch to fit, or None.

    The defect CF-0311 is: a stretch reading says WHICH stretch is too long and
    how many anchors the band implies over the whole script, and on the two edge
    stretches that is not an aim. `lf-2026-09-21-007-script2` was rewritten
    from 8 anchors to 13, an anchor was put on the payoff as the report asked,
    the anchor's `beat_text` began at the top of the payoff, and the speech
    after it was still 3.723s - the topic's second failure and its last. An
    interior stretch is aimed by its own two ends, which the report already
    names; an edge stretch has only one end, and the other end is a deadline in
    the speech that nothing computed.
    """
    edge = (EDGE_LEAD if stretch["from"] == START else
            EDGE_TAIL if stretch["to"] == END else None)
    if edge is None:
        return None
    seconds, source = edge_ceiling(edge, ceiling, margin_report)
    deadline = round(speech_seconds - seconds if edge == EDGE_TAIL else seconds, 3)
    index, quoted = word_address(deadline, rate, words, total_words, edge)
    out = {"edge": edge, "from": stretch["from"], "to": stretch["to"],
           "seconds": stretch["seconds"], "hold_ceiling_seconds": ceiling,
           "ceiling_seconds": round(seconds, 3), "ceiling_source": source,
           "deadline_seconds": deadline, "word_index": index, "words": quoted}
    out.update(edge_window(edge, stretch, deadline, speech_seconds, ceiling, margin_report,
                           rate, words, total_words))
    out["remedy"] = edge_remedy(out, pattern_id, speech_seconds)
    return out


def edge_window(edge, stretch, deadline, speech_seconds, ceiling, margin_report, rate, words,
                total_words):
    """The OTHER end of an edge address (CF-0364): the window, not one bound.

    The deadline above says how late the lead's new anchor may start (how early
    the tail's). It does not say how EARLY it may start, and that end is not
    free: the new anchor opens a stretch of its own up to the anchor that was
    already there, and that stretch is held to the same band. Both refused
    rewrites of `example-film/2026-09-23T1722Z` (Delver, Ray Gunn) put the new
    lead anchor on word 0 - "no later than 3.25s" was obeyed - and the stretch
    from it to the old first anchor was the whole 4.098s / 4.645s that had
    been refused. The window is `[old first anchor - interior ceiling,
    deadline]` for the lead and `[deadline, old last anchor + interior
    ceiling]` for the tail; the interior ceiling is the margin one (CF-0303),
    because the stretch becomes a block of the layout. An empty window is said
    as such: one anchor cannot close that edge at all.
    """
    report = margin_report if isinstance(margin_report, dict) else {}
    inner = report.get("ceiling_seconds") if report.get("asked") else None
    if not (isinstance(inner, (int, float)) and not isinstance(inner, bool) and inner > 0):
        inner = ceiling
    inner = float(inner)
    if edge == EDGE_TAIL:
        last = speech_seconds - stretch["seconds"]
        lo, hi = deadline, round(last + inner, 3)
    else:
        lo, hi = round(stretch["seconds"] - inner, 3), deadline
        lo = max(0.0, lo)
    first_word = min(total_words - 1, max(0, math.ceil(lo * rate - 1e-9)))
    last_word = min(total_words - 1, max(0, math.floor(hi * rate + 1e-9)))
    closes = lo <= hi + 1e-9 and first_word <= last_word
    quote = (" ".join(words[first_word:last_word + 1][:ADDRESS_WORDS])
             + (" ..." if last_word + 1 - first_word > ADDRESS_WORDS else "")) if closes else ""
    return {"window_from_seconds": lo, "window_to_seconds": hi,
            "interior_ceiling_seconds": round(inner, 3),
            "window_words": [first_word, last_word] if closes else None,
            "window_text": quote, "one_anchor_closes": closes}


def edge_remedy(address, pattern_id, speech_seconds):
    """The one sentence an edge stretch is rewritten by: a time, and the words
    that fall on it."""
    if address["edge"] == EDGE_TAIL:
        where = (f"no EARLIER than {address['deadline_seconds']}s - the end of the speech "
                 f"({speech_seconds}s) less the {address['ceiling_seconds']}s this gate holds "
                 f"the block that ends it to ({address['ceiling_source']})")
        what = (f"word {address['word_index']} of the counted narration, and the speech from "
                f"there to the end is: «{address['words']}»")
        head = (f"the speech after the last anchor ({address['from']} -> end) runs "
                f"{address['seconds']}s against {pattern_id}'s "
                f"{address['hold_ceiling_seconds']}s hold band")
    else:
        where = (f"no LATER than {address['deadline_seconds']}s - the "
                 f"{address['ceiling_seconds']}s this gate holds the block that opens the "
                 f"speech to ({address['ceiling_source']})")
        what = (f"word {address['word_index']} of the counted narration, and the speech up to "
                f"there is: «{address['words']}»")
        head = (f"the speech before the first anchor (start -> {address['to']}) runs "
                f"{address['seconds']}s against {pattern_id}'s "
                f"{address['hold_ceiling_seconds']}s hold band")
    if not address.get("one_anchor_closes", True):
        # CF-0364: the two ceilings together are shorter than the stretch.
        return (f"{head}. More anchors elsewhere do not touch it, and ONE anchor does not close "
                f"it either: it has to start {where}, and no more than "
                f"{address['interior_ceiling_seconds']}s from the anchor already there "
                f"(between {address['window_from_seconds']}s and "
                f"{address['window_to_seconds']}s, which is no window at all). Put TWO new "
                f"anchors on this end - the first within "
                f"{address['interior_ceiling_seconds']}s of the anchor already there, the "
                f"second at the address above ({what}) - or cut the speech of this end")
    window = (f" and no {'LATER' if address['edge'] == EDGE_TAIL else 'EARLIER'} than "
              f"{address['window_to_seconds'] if address['edge'] == EDGE_TAIL else address['window_from_seconds']}s"
              f" - the new anchor opens a stretch of its own to the anchor already there, "
              f"held to the {address['interior_ceiling_seconds']}s ceiling too (CF-0364), so "
              f"the window is {address['window_from_seconds']}-{address['window_to_seconds']}s, "
              f"words {address['window_words'][0]}-{address['window_words'][1]}: "
              f"«{address['window_text']}»") if address.get("window_words") else ""
    return (f"{head}. More anchors elsewhere do not touch it: this end of the script is fixed "
            f"by ONE anchor, and it has to start {where}{window}. The deadline is {what}. Pin "
            f"an anchor's `beat_text` to a moment inside that window - one the pool can "
            f"picture - rather than to the sentence it opens with, which is where the draft "
            f"this gate refused put it")


def anchor_times(script, sections, channel, root=None):
    """`(anchor_starts, total, word_starts, sides, rate, rate_source)`.

    Word *k* at `k / rate`, with `rate` this script's own words-per-second
    (CF-0279). This is the one thing the Editor's planner cannot be asked for:
    before TTS there is no wav and no alignment, so the anchor times are an
    estimate and everything downstream of them inherits its error. Measured
    against the Editor's real `words.json` on `2026-09-18T2232Z`, an anchor
    lands within 0.64 s on average (Famine Trials), 0.79 s (Delver), 1.74 s
    (Traitors) of where the wav put it.

    Written for `check_block_capacity.py` (CF-0284) and moved here by CF-0277,
    when this gate began asking the Editor for the same layout; that module
    re-exports the name. The seconds are the units the gap rule is already in,
    so there is one estimator and not two.
    """
    texts, offsets, words = narration_words(script, sections)
    if words <= 0:
        raise CannotJudge(
            f"{script.get('script_id')}: the counted sections hold no words - there is no "
            f"speech to cut into blocks")
    rate, rate_source = speech_rate(script, channel, root)
    anchors = script.get(FIELD)
    if not isinstance(anchors, list) or not anchors:
        raise CannotJudge(f"{script.get('script_id')}: no `{FIELD}`")
    positions = []
    for anchor in anchors:
        at = anchor_word_index(anchor, texts, offsets)
        if at is None:
            raise CannotJudge(
                f"{script.get('script_id')}: anchor {anchor.get('anchor_id')!r} has a "
                f"`beat_text` that is not in the speech, so it has no position and this "
                f"script has no block plan - `check_anchor_coverage.py` refuses that before "
                f"this gate is reached, and nothing here is claimed about the script")
        positions.append(at)
    sides = [a.get("side") if a.get("side") in ("a", "b") else None for a in anchors]
    return ([p / rate for p in positions], words / rate,
            [i / rate for i in range(words)], sides if any(sides) else None,
            rate, rate_source)


# --------------------------------------------------------------------------
# CF-0277: the same rule, read off the layout the Editor will cut
# --------------------------------------------------------------------------

# Which of the Editor's block roles a breach lands on decides what the writer
# has to change, and the roles are the Editor's vocabulary (`rhythm.py`), read
# here the way `check_block_capacity.py` already reads them - never redefined.
ROLE_HOLD, ROLE_SWING = "hold", "swing"


def layout_entry(script, sections, channel, root=None):
    """This script as one entry of `plan_blocks.py`'s payload, or None.

    None when the script cannot be placed in time at all - no anchors, no
    speech, a `beat_text` that is not spoken. Those are already `problems` of
    the gap reading, reported as such, and a script with no positions has no
    layout to judge either.
    """
    try:
        starts, total, word_starts, sides, _rate, _src = anchor_times(
            script, sections, channel, root)
    except CannotAnswer:
        return None
    return {"script_id": script.get("script_id"), "anchor_starts": starts,
            "total": total, "word_starts": word_starts,
            "order": script.get("pattern"), "anchor_sides": sides}


def drawn_hold(script, constants):
    """The hold the layout grows the key frame to: this script's own drawn
    `key_frame_hold_seconds`, or the Editor's default when it drew none.

    The default travels back with the plan (`plan_blocks.constants()`) rather
    than being written down here, for the same reason none of the rest of the
    Editor's numbers are.
    """
    drawn = ((script.get("pattern") or {}).get("parameters") or {}).get(HOLD_KEY)
    if isinstance(drawn, (int, float)) and not isinstance(drawn, bool) and drawn > 0:
        return float(drawn)
    fallback = (constants or {}).get("default_hold_seconds")
    return float(fallback) if isinstance(fallback, (int, float)) else None


def remedy(breach, block, script, ceiling, want_hold, declared_sides, split=None):
    """What the writer has to change, in the units the writer writes in.

    One sentence per shape of the defect, and each of them is mechanically
    reachable - the point of printing numbers at all is that the next draft can
    be aimed rather than guessed (CF-0140's blind cycle).
    """
    named = covered_anchors(block, script)
    role = breach.get("role")
    if role == ROLE_HOLD:
        hold = f"{want_hold}s" if want_hold else "the hold it drew"
        head = (f"this is the frame the `hold` rhythm holds, and the layout grows it by "
                f"swallowing whole stretches until it reaches {hold}: the passage your "
                f"script dwells on longest is shorter than that, so the next stretch went "
                f"in whole and the held block came out {breach['measured']}s")
        if want_hold is not None and want_hold >= ceiling - 1e-9:
            # The drawn hold sits on the top of the band, so there is exactly one
            # stretch length that works. Worth saying plainly: at that point the
            # next draft is not obviously the remedy, and the route out of an
            # assignment that does not fit already exists.
            return (f"{head}. The hold this script drew is the top of the band itself, so the "
                    f"passage has to land on {hold} exactly - anything under it swallows the "
                    f"next stretch, anything over it is outside the band. Write that passage "
                    f"AT {hold} and not under; if the scene will not sit still that long, it "
                    f"is the assignment that does not fit and the rotation's rejection is the "
                    f"honest move (`rotation/rotate.py reject`, the route "
                    f"`check_narration_budget.py` already points at). It covers {named}")
        return (f"{head}. Write that passage as ONE stretch of between {hold} and "
                f"{ceiling}s - move the anchor that ends it later, or drop the anchor that "
                f"splits it. It covers {named}")
    if role == ROLE_SWING and declared_sides:
        side = block.get("side")
        head = (f"this is one crossing of the axis - every anchor in it is on side "
                f"{side!r}, so the block is the whole {breach['measured']}s that run of "
                f"anchors speaks, and a crossing is a boundary the montage may not cut. ")
        if split and split.get("found"):
            # CF-0364: the side and the time, asked of the Editor's own layout.
            return head + split_sentence(split) + f"It covers {named}"
        return (head + split_sentence(split)
                + f"Cross the axis inside it: give one of these anchors the other side, or "
                f"move the crossing so that no run of one side speaks longer than "
                f"{ceiling}s. It covers {named}")
    if role == ROLE_SWING:
        return (f"this `alternate` declares no sides, so the montage swings on parity and "
                f"every block is a crossing it may not cut - including this {breach['measured']}s "
                f"one. Declare the axis on the anchors (`{FIELD}[].side`, which "
                f"`check_alternate_sides.py` asks for in its own right): with the sides "
                f"written the blocks are your crossings and you can keep each of them under "
                f"{ceiling}s. It covers {named}")
    return (f"the layout could not cut this {breach['measured']}s block back under "
            f"{ceiling}s ({breach.get('code')}). Put a new frame inside it - an anchor at a "
            f"moment in it the pool can picture - so the montage has a boundary to cut on. "
            f"It covers {named}")


def covered_anchors(block, script):
    """`anchor_id (beat_text)` for the anchors a block covers, at most four."""
    ids = [(script.get(FIELD) or [])[i] for i in (block.get("anchors") or [])
           if i < len(script.get(FIELD) or [])]
    return ", ".join(f"{a.get('anchor_id') or '?'} ({a.get('beat_text') or ''!r})"
                     for a in ids[:4]) + (" ..." if len(ids) > 4 else "")


def margin_remedy(entry, block, script, pattern_id):
    """What the writer has to change about a block that is merely too CLOSE.

    Written to be read alone, because this is the one sentence in the whole
    gate the rewrite is aimed by, and the number it has to be aimed at is not
    the band's top. Says the block, what the estimate makes it, the top, the
    margin, and what the margin is - a script rewritten at the top itself comes
    back over it after TTS, which is the whole of CF-0303.
    """
    seat = ("the LAST block" if entry.get("last_block")
            else f"block {entry['block']}")
    last = (" - the block that ends the speech, which the estimate gets wrong by more than "
            "any other (+1.504s and +1.135s on the two videos whose layouts can be lined "
            "up, against a median of +0.06s), which is why its margin is double"
            if entry.get("last_block") else "")
    return (f"{seat} is {entry['seconds']}s by the estimate of the speech{last}. That is "
            f"inside {pattern_id}'s {entry['band_max']}s top, but {entry['outside_by']}s over "
            f"the {entry['ceiling']}s this gate holds the estimate to - the top less a "
            f"{entry['margin']}s margin. The margin is not spare room: it is the correction "
            f"for the estimate itself (CF-0303). The speech is estimated at "
            f"`word / words_per_second`, which gets the TOTAL right to a hundredth of a "
            f"second and the share of each block wrong by a median of +0.06s and up to "
            f"+3.2s - the longest block of `coach-hale-stadiums` was estimated at 3.405s and "
            f"read by the voice as 4.54s, and the Editor now refuses such a plan before the "
            f"render. So write this passage to land under {entry['ceiling']}s, NOT under "
            f"{entry['band_max']}s: move the anchor that ends it earlier, or put a new "
            f"anchor inside it at a moment the pool can picture. It covers "
            f"{covered_anchors(block, script)}")


def margin_reading(plan, script, blocks_by_index, breached):
    """`(entry list, report)` - the blocks too close to the top to survive TTS.

    A block already over the top is reported by `layout_reading()` as a breach
    and is not repeated here: it is the same block and a louder problem, and
    two lines about one block is how a report stops being read.
    """
    report = plan.get("margin") or None
    if not report or not report.get("asked"):
        return [], report
    pattern_id = ((script.get("pattern") or {}).get("pattern_id"))
    out = []
    for entry in report.get("blocks") or []:
        if entry.get("block") in breached:
            continue
        block = blocks_by_index.get(entry.get("block")) or {}
        out.append(dict(entry, anchors=list(block.get("anchors") or []),
                        remedy=margin_remedy(entry, block, script, pattern_id)))
    return out, report


def band_wording(band):
    """How a block band names itself in a sentence handed to a human.

    One phrasing for the three places that write that sentence (the pass/fail
    reason, the report line and the remedy), because they are read as one
    message and a band that is a "drawn band" in one of them and an "observed
    envelope" in the next is a band the reader has to go and look up.

    CF-0314: a `floor_drawn` band is neither word. Its floor was ordered and its
    ceiling was only measured, so the phrase says both - the reader of this line
    is deciding whether the number he is looking at costs him a rewrite or is
    simply on the record.
    """
    mode, lo, hi = band.get("mode"), band.get("band_min"), band.get("band_max")
    if mode == BAND_MODE_FLOOR_DRAWN:
        return f"ordered floor {lo} / observed ceiling {hi}"
    word = "drawn band" if mode == BAND_MODE_DRAWN else "observed envelope"
    return f"{word} {lo}-{hi}"


def band_verdict_note(band):
    """Why a layout outside the band is not being refused here.

    `emergent` is CF-0039 and has no second half. A drawn end - CF-0314's
    ordered floor included - does refuse somewhere, so the sentence is the
    reading's own (`block_band.reading_note`), which says where and at whose
    cost.
    """
    if band.get("mode") == BAND_MODE_EMERGENT:
        return "an observed envelope records what past videos did and never fails one (CF-0039)"
    return (band.get("reading_note")
            or "the Editor's own rule does not refuse on this end of a band")


def block_band_remedy(band, script, search=None):
    """What the writer can change about a layout over the block band's top.

    Since CF-0447 this is the hint beside a price, not the reason of a
    refusal: the layout costs `score.block_band_exceeded` and the script goes
    on; the sentence says the measurement, the band, the unit, and the lever -
    which is not the prose - for 6b's rounds when the score is under N.

    It is written only over a top (see `block_band_reading()`), so "over its
    top by" is always true of it - but WHICH band it is over is
    `band_wording()`'s to say and not a word fixed here, because CF-0314 gave
    the bands a third mode.
    """
    pid, unit = band.get("pattern_id"), band.get("unit") or ""
    tail = f" {unit}" if unit else ""
    return (
        f"the layout is {band.get('blocks')} block(s) over "
        f"{band.get('block_span_seconds')}s of speech, which is {band.get('measured')}{tail} "
        f"against {pid}'s {band_wording(band)}{tail} - "
        f"over its top by {band.get('outside_by')}{tail}: not refused (CF-0447) - "
        f"`score.block_band_exceeded` costs {BLOCK_BAND_PRICE_WORDS}, "
        f"{blocks_over(band)} block(s) over here. To win the points back this is not a sentence "
        f"to rewrite: the number is the anchors. {band_search_sentence(search, band, script)} - and land "
        f"UNDER the top with room rather than on it, because the finished video is never cut "
        f"into fewer blocks than this reading counts (inside one block the Editor hands out as "
        f"many shots as the pool affords, and each is a block of its own: 3 here became 10 on "
        f"`outrider-doune-castle`). If the scene cannot be told in that few moments and the "
        f"score is under N, the assignment is what does not fit - reject it "
        f"(`rotation/rotate.py reject`) rather than draft it again. The reading is recorded "
        f"at {BLOCK_BAND_RECORD_PATH}")


def block_band_reading(plan, script, search=None):
    """CF-0310: the pattern's block band, read before the TTS, and the verdict.

    `plan_blocks.block_band_report()` is where the measurement and the Editor's
    two predicates are; this adds the one sentence a human is handed and the
    single boolean the ladder below turns on:

        the Editor's own `rhythm.cadence_band_refuses()` said refuse, AND
        this stage's reading can carry the refusal.

    The second half is the correction for measuring an estimate (CF-0303's job,
    a different quantity): the number here counts the rhythm's segments and the
    Editor's judge counts the render plan's picture blocks, which on
    `outrider-doune-castle` is 3 against 10. The delivered count is never
    *below* it, so a reading over the band's top is one the finished video is
    over too - and a reading under a floor is not evidence about the cutting at
    all. It can only soften this gate's refusal, never add one, and no copy of
    the band rule is made here.

    CF-0314 makes that softening visible for the first time. `explainer`'s floor
    is an ORDER since 2026-09-22, so the Editor's predicate now answers "refuse"
    about a layout this stage measures under it - `outrider-doune-castle` at
    6.27 blocks/min against a floor of 15.39 - and `refused_here` is still
    false, because 6.27 is three segments and the Editor will count ten picture
    blocks. Nothing is refused here on a number this reading cannot carry; what
    changed is the sentence, which now says that the same floor is checked again
    after the wav is paid for (`block_band.reading_note`, written by
    `plan_blocks.block_band_report()`).
    """
    band = plan.get(BLOCK_BAND_KEY)
    if not isinstance(band, dict):
        return {"asked": False, "pattern_read": bool(plan.get("pattern_read")),
                "refuses": False,
                "why": ("the Editor's block planner answered without a `block_band` - this "
                        "checkout of plan_blocks.py is older than CF-0310, and the band was "
                        "not read")}
    out = dict(band)
    over = bool(band.get("refuses") and band.get("reading_supports_refusal"))
    # CF-0447: over the top is priced, never refused here - `refused_here`
    # stays in the record, always false, so a reader of an older record and a
    # reader of this one ask the same key.
    out["refused_here"] = False
    out["priced_here"] = over
    if over:
        out["blocks_over"] = blocks_over(band)
        out["remedy"] = block_band_remedy(band, script, search)
        out["axis"] = band_search_sentence(search, band, script)
        if search:
            # CF-0417: which lever, and the count the Editor's planner accepts.
            out[BAND_SEARCH_KEY] = search
            out["cause"] = search.get("cause")
    return out


def blocks_over(band):
    """CF-0447: the blocks over the band's top - the units of
    `score.block_band_exceeded` (priced per block). A count band: the
    measurement less the top. A rate band: the blocks less as many as the top
    allows over this span, rounded up. At least 1 - the reading is over."""
    blocks, hi = band.get("blocks"), band.get("band_max")
    scale = _band_scale(band)
    if blocks is None or hi is None or not scale:
        return 1
    allowed = float(hi) / scale
    return max(1, int(math.ceil(float(blocks) - allowed - 1e-9)))


def block_band_finding(band):
    """CF-0447: the price of a layout over the block band's top, in the score
    model's shape. The note carries the Axis hint (CF-0417) - it is what the
    writer reads in the penalty log when 6b's score is under N."""
    unit = band.get("unit") or ""
    tail = f" {unit}" if unit else ""
    note = (f"{band.get('blocks')} block(s) = {band.get('measured')}{tail} against "
            f"{band.get('pattern_id')}'s {band_wording(band)}{tail}, "
            f"{band.get('blocks_over')} block(s) over the top (layout estimate). "
            f"{band.get('axis') or ''}").strip()
    return _score.finding(_score.RULE_BLOCK_BAND_EXCEEDED,
                          {"pattern": band.get("pattern_id")},
                          band.get("blocks_over") or 1, False, note)


def layout_reading(script, plan, ceiling, constants, splits=None):
    """The Editor's own layout for this script, and what it says about the band.

    `plan` is one entry of `plan_blocks.py`'s answer. Returns the record that
    goes on the script, or raises `CannotJudge` when the planner could not
    build a layout at all - a script whose blocks are unknown has not been
    passed by this gate.
    """
    blocks = plan.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise CannotJudge(
            f"{script.get('script_id')}: the Editor's planner returned no layout"
            + (f" ({plan.get('error')})" if plan.get("error") else "")
            + " - without it the pattern's band can only be read off the gaps, and a gate "
              "that could not put its question has not passed the script")
    report = plan.get("ceiling") or {}
    band = report.get("band") or None
    by_index = {b["index"]: b for b in blocks}
    want_hold = drawn_hold(script, constants)
    declared = bool(plan.get("declared_sides_usable"))
    top = float(band["max"]) if band and band.get("max") is not None else ceiling
    breaches = []
    for b in report.get("breaches") or []:
        block = by_index.get(b.get("block")) or {}
        breaches.append({
            "block": b.get("block"),
            "role": b.get("role"),
            "anchors": list(block.get("anchors") or []),
            "seconds": b.get("measured"),
            "band_max": b.get("band_max"),
            "outside_by": b.get("outside_by"),
            "code": b.get("code"),
            "note": b.get("note"),
            "remedy": remedy(b, block, script, top, want_hold, declared,
                             split=(splits or {}).get(b.get("block"))),
        })
        if (splits or {}).get(b.get("block")):
            breaches[-1][SPLIT_KEY] = splits[b.get("block")]
    # CF-0303: the second question about the same top - not "is this block over
    # it" but "is this block close enough to it that the voice will put it over".
    margins, margin_report = margin_reading(
        plan, script, by_index, {b["block"] for b in breaches})
    return {
        "asked": True,
        "pattern_read": bool(plan.get("pattern_read")),
        "band": band,
        "blocks": len(blocks),
        "longest_block_seconds": max(b.get("seconds") or 0.0 for b in blocks),
        "last_block_seconds": blocks[-1].get("seconds"),
        "margin": margin_report,
        "margin_breaches": margins,
        "lead_before_first_anchor": report.get("lead_before_first_anchor"),
        "declared_sides_usable": declared,
        "drawn_hold_seconds": want_hold,
        "breaches": breaches,
        "source": ("rhythm.plan_segments(pattern=...) + rhythm.ceiling_report(), through "
                   "plan_blocks.py on the Video Editor's venv (CF-0276/CF-0277)"),
    }


# --------------------------------------------------------------------------
# CF-0353: the tail after the last anchor, named
# --------------------------------------------------------------------------

TAIL_KEY = "tail"
# The Editor's words for what happens to this tail after the TTS: the plan is
# refused at `pattern_ceiling` (`build_render_plan.GATE_PATTERN_CEILING`), and
# the trim that would have saved it is `no_next_block` - the last block has no
# neighbour to hand its remainder to. Quoted, not imported: they name the
# consequence in the report, nothing here branches on them.
EDITOR_TAIL_GATE = "pattern_ceiling"
EDITOR_TAIL_TRIM_CODE = "no_next_block"


def tail_reading(plan, layout, stretches, positions, rate, pattern_id):
    """Whether the speech after the last anchor is handed out in blocks inside
    the pattern's band - the question the Editor asks at `pattern_ceiling`
    one wav too late (CF-0353, `everyday-sorcery-2`).

    Nothing is computed about blocks here. The tail's blocks are the blocks of
    the Editor's own layout (`plan_blocks.py`) that carry the last anchor, and
    whether one of them is over is what the layout and margin readings already
    decided (`layout["breaches"]`, `layout["margin_breaches"]`) - this record
    only puts those verdicts on the one stretch whose failure the Editor cannot
    trim: there is no block after it. The channel's ending clip does not
    absorb any of it either - it follows the speech, the layout's blocks span
    the speech alone (`block_span_seconds`), so the tail is held exactly as the
    Editor will hold it.

    `deliverable` is None when the layout was not asked - "not checked" is a
    record of its own, not a pass.
    """
    if not layout.get("asked") or not positions:
        return {"asked": False, "deliverable": None,
                "why": "the layout was not built, so the tail was not read"}
    blocks = plan.get("blocks") or []
    last = max((a for b in blocks for a in (b.get("anchors") or [])), default=None)
    tail_blocks = [b for b in blocks if last is not None and last in (b.get("anchors") or [])]
    stretch = stretches[-1] if stretches else {}
    over = {b["block"]: b for b in layout.get("breaches") or []}
    close = {b["block"]: b for b in layout.get("margin_breaches") or []}
    margin = layout.get("margin") or {}
    bad = []
    for b in tail_blocks:
        hit = over.get(b["index"]) or close.get(b["index"])
        if not hit:
            continue
        # The ceiling a tail block is held to: the margin's when one was asked
        # (the last block's doubled margin, CF-0303), the band's top otherwise.
        ceiling = (hit.get("ceiling") if hit.get("ceiling") is not None else
                   (margin.get("last_block_ceiling_seconds") if b is blocks[-1]
                    else margin.get("ceiling_seconds")) or hit.get("band_max"))
        excess = round((b.get("seconds") or 0.0) - float(ceiling), 3)
        bad.append({"block": b["index"], "role": b.get("role"),
                    "seconds": b.get("seconds"), "ceiling_seconds": ceiling,
                    "excess_seconds": excess,
                    "code": hit.get("code") or READING_MARGIN,
                    "last_block": b is blocks[-1]})
    worst = max(bad, key=lambda x: x["excess_seconds"], default=None)
    words_to_cut = math.ceil(worst["excess_seconds"] * rate) if worst else 0
    anchor_id = positions[-1][0]
    record = {
        "asked": True,
        "last_anchor": anchor_id,
        "speech_after_last_anchor_seconds": stretch.get("seconds"),
        "words_after_last_anchor": stretch.get("words"),
        "blocks": len(tail_blocks),
        "block_seconds": [b.get("seconds") for b in tail_blocks],
        "longest_block_seconds": max((b.get("seconds") or 0.0 for b in tail_blocks),
                                     default=None),
        "over": bad,
        "deliverable": not bad,
    }
    if bad:
        record.update({
            "editor_gate": EDITOR_TAIL_GATE,
            "editor_trim_code": EDITOR_TAIL_TRIM_CODE if worst["last_block"] else None,
            "words_to_cut": words_to_cut,
            "remedy": (
                f"the speech after the last anchor ({anchor_id} -> end, "
                f"{stretch.get('seconds')}s, {stretch.get('words')} words) is laid out as "
                f"{len(tail_blocks)} block(s) and block {worst['block']} ({worst['role']}) "
                f"comes out {worst['seconds']}s against the {worst['ceiling_seconds']}s this "
                f"gate holds it to"
                + (f" - no trim saves it (`{EDITOR_TAIL_TRIM_CODE}`: it is the last block, "
                   f"there is no next one to hand the {worst['excess_seconds']}s to)"
                   if worst["last_block"] else "")
                + f". After the TTS the Editor prices that block (`score.hold_band_exceeded`, "
                  f"CF-0433); `{EDITOR_TAIL_GATE}` refuses the plan only if the video's whole "
                  f"score falls under N"
                + f". Either put one more anchor into the final (the address above), or "
                  f"shorten the speech after {anchor_id} by at least {words_to_cut} word(s) "
                  f"({worst['excess_seconds']}s at {rate} words/s)"),
        })
    return record


# --------------------------------------------------------------------------
# one script
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# CF-0364: the side a new anchor goes on, asked of the layout
# --------------------------------------------------------------------------
# `example-film/2026-09-23T1722Z` lost Delver (`lf-2026-09-23-002`, contrast
# on `alternate`) on its one rewrite: the report said block 0 was one crossing
# of the axis at 7.573s and "give one of these anchors the other side"; the
# rewrite added a hook anchor v0 on side 'a' in front of v1 on side 'a', and a
# declared `alternate` makes one block per RUN of one side - the two anchors
# were glued into the same block and the boundary never appeared. The sentence
# named no side and no time, and the rule it relied on (same side = same block)
# is the Editor's, not the writer's.
#
# So the gate asks the Editor. For every swing block over the band on a script
# whose sides the Editor uses, it plans the script again with ONE hypothetical
# anchor on every word inside that block, on each side, in one child process
# for the whole batch, and keeps the placements under which the Editor's own
# layout cuts that stretch into pieces inside the band and makes nothing else
# worse. When no single anchor does it (the lead: the speech before the first
# anchor is absorbed into the first block, so it takes a crossing BEFORE the old
# first anchor - two new anchors), it asks again with pairs. The side and the
# words that come back are the Editor's answer, not a rule written down here.

SPLIT_KEY = "split"
# The overlap below which a probe block is not counted as a piece of the
# stretch it was asked about - the layout opens a block a little before its
# anchor's word, so a neighbouring block may touch the span by a hair.
SPLIT_OVERLAP_SECONDS = 0.05
# A cap on the pair probes asked for one block, so a long run cannot turn one
# child process into a minute of arithmetic; beyond it the candidate words are
# thinned evenly. 2000 pair layouts of a 45s script are well under a second.
SPLIT_MAX_PAIR_PROBES = 2000
SPLIT_PROBE_MARK = "#cf0364-probe:"


def _probe_entry(entry, inserts, tag):
    """`entry` with `inserts` = [(seconds, side), ...] added, in time order."""
    starts = list(entry["anchor_starts"]) + [t for t, _ in inserts]
    sides = list(entry.get("anchor_sides") or [None] * len(entry["anchor_starts"]))
    sides += [s for _, s in inserts]
    order = sorted(range(len(starts)), key=lambda i: starts[i])
    return dict(entry, script_id=f"{entry['script_id']}{SPLIT_PROBE_MARK}{tag}",
                anchor_starts=[starts[i] for i in order],
                anchor_sides=[sides[i] for i in order])


def _pieces(blocks, lo, hi):
    return [b for b in blocks
            if min(b.get("end") or 0.0, hi) - max(b.get("start") or 0.0, lo)
            > SPLIT_OVERLAP_SECONDS]


def _judge_probe(plan, target, others_worst, top, positions, new_words, total_words, rate,
                 ceiling):
    """What one probe layout did to the target block, or None if it has none."""
    blocks = plan.get("blocks") if isinstance(plan, dict) else None
    if not isinstance(blocks, list) or not blocks:
        return None
    lo, hi = target["start"], target["end"]
    pieces = _pieces(blocks, lo, hi)
    inside = {id(b) for b in pieces}
    rest = [b.get("seconds") or 0.0 for b in blocks if id(b) not in inside]
    margin = plan.get("margin") or {}
    over_margin = {m.get("block") for m in margin.get("blocks") or []}
    worst = max((b.get("seconds") or 0.0 for b in pieces), default=0.0)
    ceil_m = margin.get("ceiling_seconds") if margin.get("asked") else None
    # The stretches this probe leaves inside the target's span, on the gap
    # rule's own words: a split the layout accepts and the stretch reading
    # refuses would be the next rewrite's failure.
    stretch_ok = True
    ordered = sorted([p for _, p in positions] + list(new_words))
    bounds = [0] + ordered + [total_words]
    for a, b in zip(bounds, bounds[1:]):
        t0, t1 = a / rate, b / rate
        if min(t1, hi) - max(t0, lo) > SPLIT_OVERLAP_SECONDS and (b - a) / rate > ceiling + 1e-9:
            stretch_ok = False
    return {
        "splits": len(pieces) >= 2,
        "pieces_seconds": [b.get("seconds") for b in pieces],
        "worst_piece_seconds": round(worst, 3),
        "inside_top": worst <= top + 1e-9,
        "under_margin": not any(b.get("index") in over_margin for b in pieces),
        "margin_ceiling_seconds": ceil_m,
        "not_worse_elsewhere": max(rest, default=0.0) <= max(others_worst, ceil_m or top) + 1e-3,
        "stretch_ok": stretch_ok,
    }


def _probe_rank(r, n_anchors):
    valid = r["splits"] and r["inside_top"] and r["not_worse_elsewhere"]
    return (valid, valid and r["under_margin"], valid and r["stretch_ok"], -n_anchors,
            -r["worst_piece_seconds"])


def _valid(r):
    return r["splits"] and r["inside_top"] and r["not_worse_elsewhere"]


def _quote(words, first, last):
    chosen = words[first:last + 1]
    return " ".join(chosen[:ADDRESS_WORDS]) + (" ..." if len(chosen) > ADDRESS_WORDS else "")


def _window(results, key_of, fixed, k, words_n):
    """The contiguous run of words around `k` on which the probe keyed by
    `key_of(word)` is as good as the chosen one (valid, and under the margin
    when the chosen one is)."""
    def good(j):
        r = results.get(key_of(j))
        return (bool(r) and _valid(r)
                and (r["under_margin"] or not fixed["under_margin"])
                and (r["stretch_ok"] or not fixed["stretch_ok"])
                and (fixed["under_margin"]
                     or r["worst_piece_seconds"] <= fixed["worst_piece_seconds"] + 1e-6))

    lo = hi = k
    while lo - 1 >= 0 and good(lo - 1):
        lo -= 1
    while hi + 1 < words_n and good(hi + 1):
        hi += 1
    return lo, hi


def split_targets(plan):
    """The swing blocks over the band on a plan whose sides the Editor uses."""
    if not isinstance(plan, dict) or not plan.get("declared_sides_usable"):
        return []
    blocks = {b.get("index"): b for b in plan.get("blocks") or []}
    out = []
    for br in (plan.get("ceiling") or {}).get("breaches") or []:
        block = blocks.get(br.get("block"))
        if br.get("role") == ROLE_SWING and block:
            out.append(block)
    return out


def split_search(scripts, plans, sections, channel, root, paths, timeout, run=None):
    """`{script_id: {block_index: proposal}}` - CF-0364, see the section head.

    `run(entries)` is the planner call (`run_planner` with this gate's margin
    fractions); a probe the planner answers nothing for is skipped, never read
    as a split. Returns `{}` for a batch with nothing to split.
    """
    run = run or (lambda entries: run_planner(
        entries, paths, timeout, margin_fraction=HOLD_MARGIN_BAND_FRACTION,
        last_margin_fraction=HOLD_MARGIN_LAST_BLOCK_FRACTION)[0])
    jobs = []
    for script in scripts:
        sid = script.get("script_id")
        targets = split_targets(plans.get(sid))
        if not targets:
            continue
        try:
            starts, total_s, word_starts, sides, rate, _src = anchor_times(
                script, sections, channel, root)
            ceiling, _ = hold_ceiling((script.get("pattern") or {}).get("pattern_id"), root)
        except CannotAnswer:
            continue
        texts, _offsets, total_words = narration_words(script, sections)
        words = [w for _section, text in texts for w in text.split()]
        entry = {"script_id": sid, "anchor_starts": starts, "total": total_s,
                 "word_starts": word_starts, "order": script.get("pattern"),
                 "anchor_sides": sides}
        ids = [(a.get("anchor_id") or f"#{i}") for i, a in enumerate(script.get(FIELD) or [])]
        positions = [(ids[i], round(t * rate)) for i, t in enumerate(starts)]
        plan = plans[sid]
        top = float(((plan.get("ceiling") or {}).get("band") or {}).get("max") or ceiling)
        for target in targets:
            lo, hi = target.get("start") or 0.0, target.get("end") or 0.0
            taken = {p for _, p in positions}
            cand = [k for k, t in enumerate(word_starts) if lo - 1e-9 <= t < hi and k not in taken]
            touching = {id(b) for b in _pieces(plan.get("blocks") or [], lo, hi)}
            others = [b.get("seconds") or 0.0
                      for b in plan.get("blocks") or [] if id(b) not in touching]
            jobs.append({"sid": sid, "entry": entry, "target": target, "cand": cand,
                         "positions": positions, "rate": rate, "total_words": total_words,
                         "words": words, "top": top, "ceiling": ceiling,
                         "others_worst": max(others, default=0.0),
                         "run_side": target.get("side")})
    if not jobs:
        return {}

    def ask(probe_sets):
        entries, keys = [], []
        for j, job in enumerate(jobs):
            for tag, inserts in probe_sets[j]:
                entries.append(_probe_entry(job["entry"], inserts, f"{job['target']['index']}:{tag}"))
                keys.append((j, tag))
        if not entries:
            return {}
        try:
            answered = run(entries)
        except CannotAnswer:
            return {}
        out = {}
        for (j, tag), e in zip(keys, entries):
            job = jobs[j]
            new_words = [k for k in tag_words(tag)]
            r = _judge_probe(answered.get(e["script_id"]), job["target"], job["others_worst"],
                             job["top"], job["positions"], new_words, job["total_words"],
                             job["rate"], job["ceiling"])
            if r:
                out[(j, tag)] = r
        return out

    def tag_words(tag):
        return [int(p[:-1]) for p in tag.split("+")]

    ws = {j: job["entry"]["word_starts"] for j, job in enumerate(jobs)}
    singles = ask({j: [(f"{k}{s}", [(ws[j][k], s)]) for k in job["cand"] for s in "ab"]
                   for j, job in enumerate(jobs)})
    need_pairs = {j for j in range(len(jobs))
                  if not any(_valid(r) for (jj, _t), r in singles.items() if jj == j)}
    pair_sets = {}
    for j, job in enumerate(jobs):
        pair_sets[j] = []
        if j not in need_pairs:
            continue
        cand = job["cand"]
        while len(cand) > 2 and len(cand) * (len(cand) - 1) > SPLIT_MAX_PAIR_PROBES:
            cand = cand[::2]
        for x, k1 in enumerate(cand):
            for k2 in cand[x + 1:]:
                for s1, s2 in (("a", "b"), ("b", "a")):
                    pair_sets[j].append((f"{k1}{s1}+{k2}{s2}",
                                         [(ws[j][k1], s1), (ws[j][k2], s2)]))
    pairs = ask(pair_sets) if need_pairs else {}

    found = {}
    for j, job in enumerate(jobs):
        mine = [(tag, r) for (jj, tag), r in list(singles.items()) + list(pairs.items())
                if jj == j]
        same_side_split = any(
            _valid(r) for (jj, tag), r in singles.items()
            if jj == j and tag.endswith(job["run_side"] or "?"))
        proposal = {"block": job["target"]["index"],
                    "block_seconds": job["target"].get("seconds"),
                    "run_side": job["run_side"],
                    "span_seconds": [round(job["target"].get("start") or 0.0, 3),
                                     round(job["target"].get("end") or 0.0, 3)],
                    "probes": len([1 for (jj, _t) in singles if jj == j])
                    + len(pair_sets.get(j) or []),
                    "same_side_splits": same_side_split,
                    "source": ("rhythm.plan_segments(pattern=...) through plan_blocks.py, "
                               "planned again with the new anchor(s) in (CF-0364)")}
        if not mine:
            proposal.update({"found": False, "anchors": []})
            found.setdefault(job["sid"], {})[job["target"]["index"]] = proposal
            continue
        tag, best = max(mine, key=lambda tr: _probe_rank(tr[1], len(tr[0].split("+"))))
        parts = tag.split("+")
        results = {t: r for t, r in mine}
        anchors = []
        for i, part in enumerate(parts):
            k, side = int(part[:-1]), part[-1]

            def key_of(w, i=i, side=side):
                return "+".join(f"{w}{side}" if n == i else p for n, p in enumerate(parts))
            w0, w1 = _window(results, key_of, best, k, len(job["words"]))
            anchors.append({"side": side, "word": k,
                            "seconds": round(ws[j][k], 3),
                            "window_words": [w0, w1],
                            "window_seconds": [round(ws[j][w0], 3), round(ws[j][w1], 3)],
                            # at least six words, so a one-word window is recognisable
                            "text": _quote(job["words"], w0, max(w1, w0 + 5))})
        single = [r for (jj, _t), r in singles.items() if jj == j]
        proposal.update({"found": _valid(best), "anchors": anchors,
                         "best_single_worst_seconds": (
                             min(r["worst_piece_seconds"] for r in single) if single else None),
                         "pieces_seconds": best["pieces_seconds"],
                         "worst_piece_seconds": best["worst_piece_seconds"],
                         "inside_top": best["inside_top"],
                         "under_margin": best["under_margin"],
                         "margin_ceiling_seconds": best["margin_ceiling_seconds"],
                         "stretch_ok": best["stretch_ok"]})
        found.setdefault(job["sid"], {})[job["target"]["index"]] = proposal
    return found


def split_sentence(split):
    """The sentence a verified proposal is handed out in."""
    if not split:
        return ""
    run_side = split.get("run_side")
    same = (f"A new anchor on the SAME side {run_side!r} does not split it - the Editor glues "
            f"neighbouring anchors of one side into one block, which is how the rewrite of "
            f"Delver (`example-film/2026-09-23T1722Z`) kept its block whole (CF-0364). ")
    if not split.get("anchors"):
        return same + ("The layout could not be asked with a new anchor in, so no side or time "
                       "is proposed here. ")
    several = len(split["anchors"]) > 1

    def one(a):
        w0, w1 = a["window_words"]
        where = (f"on side {a['side']!r} at {a['seconds']}s (word {a['word']}")
        if w0 != w1:
            where += (f"; {'with the other one kept, ' if several else ''}any word "
                      f"{w0}-{w1}, {a['window_seconds'][0]}-{a['window_seconds'][1]}s, works")
        return where + f": «{a['text']}»)"
    pieces = " + ".join(f"{p}s" for p in split.get("pieces_seconds") or [])
    if not split.get("found"):
        return same + (f"No one or two new anchors split it inside the band in the Editor's "
                       f"layout: the best found ({'; '.join(one(a) for a in split['anchors'])}) "
                       f"still leaves {split.get('worst_piece_seconds')}s. Shorten this run's "
                       f"speech instead. ")
    if not several:
        lead = "Put the new anchor "
    else:
        why = (" - the speech before the first anchor belongs to the first block, so the "
               "crossing has to come BEFORE that anchor" if split.get("block") == 0 else
               " - on the other side it is glued to the neighbouring run of that side instead")
        lead = (f"One new anchor cannot split it inside the band (the best single one still "
                f"leaves {split.get('best_single_worst_seconds')}s{why}). Put TWO, sides "
                f"crossing: ")
    body = "; then ".join(one(a) for a in split["anchors"])
    tail = (f"all of them under the {split.get('margin_ceiling_seconds')}s ceiling"
            if split.get("under_margin") else
            f"inside the band, but the worst piece, {split.get('worst_piece_seconds')}s, is "
            f"still over the {split.get('margin_ceiling_seconds')}s ceiling - shorten that "
            f"passage too")
    return (same + lead + body + f". Asked with {'them' if several else 'it'} in, the "
            f"Editor's own layout cuts this stretch into {pieces} - {tail}. ")


# --------------------------------------------------------------------------
# CF-0417: over the block band's top - which lever, and how many anchors
# --------------------------------------------------------------------------
# `example-film/2026-09-27T0929Z` lost American Dread Story here. Its first
# draft had 14 anchors and the layout 33 blocks, over `list`'s drawn top: the
# drawn rhythm was `staccato` with a 1.8s cap, and staccato cuts every stretch
# longer than the cap into pieces. The message said "write fewer of them"; the
# rewrite went the other way (an anchor every six words, 28 anchors, 28 blocks)
# and the second failure was the topic's last. Neither draft could have
# passed: 49s of speech under a 1.8s cap is at least 28 blocks whatever the
# anchors, so the lever was the length of the speech - and nothing said so.
#
# So, as for the swing split (CF-0364), the gate asks the Editor instead of
# writing a rule about the layout down here: the script is planned again on
# its own speech with N evenly spaced anchors for every N up to past the top
# (and, on `hold`, with the passage it holds kept as one stretch and the rest
# spaced shorter than it - an even spacing is the worst case there, every
# block as long as the hold is cut in two). What comes back is the cause and
# a count the Editor's own layout puts inside the band. When no placement
# fits, the speech is shortened in the probe (its first K words) until one
# does, and that K is the word count handed out.

BAND_SEARCH_KEY = "band_search"
BAND_PROBE_MARK = "#cf0417-probe:"
# Past the band's top by this many anchors, so "more anchors cost fewer
# blocks" (staccato, hold) is seen on both sides of the top.
BAND_SEARCH_PAST_TOP = 4
BAND_SEARCH_MAX_PROBES = 2500
BAND_SEARCH_SPEECH_STEPS = 30


def _band_scale(band):
    """The band's unit per block (1 for a count, 60/span for a rate)."""
    blocks, measured = band.get("blocks"), band.get("measured")
    if not blocks or measured is None:
        return None
    return float(measured) / float(blocks)


def _band_room(band):
    """The band's top less CF-0303's share of its width: 'under the top with
    room', as a number of the band's own unit."""
    lo, hi = band.get("band_min"), band.get("band_max")
    if lo is None or hi is None:
        return None
    return float(hi) - HOLD_MARGIN_BAND_FRACTION * (float(hi) - float(lo))


def _even_words(n, total_words, start=0):
    """`n` anchor words spread evenly over [start, start + total_words)."""
    return sorted({start + round(i * total_words / n) for i in range(n)})


def _hold_shape(total_words, h0, hold_w, pw):
    """Anchor words that keep [h0, h0 + hold_w) as one stretch and space the
    rest every `pw` words on both sides of it."""
    ks = {0, h0}
    end = h0 + hold_w
    if end < total_words:
        ks.add(end)
    k = h0 - pw
    while k > 0:
        ks.add(k)
        k -= pw
    k = end + pw
    while k < total_words:
        ks.add(k)
        k += pw
    return sorted(x for x in ks if 0 <= x < total_words)


def _probe_verdict(plan):
    """`(measured, refused, findings)` off one probe's plan, or None."""
    bb = plan.get(BLOCK_BAND_KEY) if isinstance(plan, dict) else None
    if not isinstance(bb, dict) or bb.get("measured") is None:
        return None
    refused = bool(bb.get("refuses") and bb.get("reading_supports_refusal"))
    return bb.get("measured"), refused, len(plan.get("score_findings") or [])


def band_search(scripts, plans, sections, channel, root, paths, timeout, run=None):
    """`{script_id: search}` for every script whose layout is over the block
    band's top - see the section head. Probes only; the verdict is still the
    plan's. A script the planner answers nothing for gets no search."""
    run = run or (lambda entries: run_planner(
        entries, paths, timeout, margin_fraction=HOLD_MARGIN_BAND_FRACTION,
        last_margin_fraction=HOLD_MARGIN_LAST_BLOCK_FRACTION)[0])
    jobs = []
    for script in scripts:
        sid = script.get("script_id")
        plan = plans.get(sid)
        band = plan.get(BLOCK_BAND_KEY) if isinstance(plan, dict) else None
        if not (isinstance(band, dict) and band.get("refuses")
                and band.get("reading_supports_refusal")):
            continue
        scale = _band_scale(band)
        if not scale:
            continue
        try:
            starts, total_s, word_starts, sides, rate, _src = anchor_times(
                script, sections, channel, root)
        except CannotAnswer:
            continue
        texts, _offsets, total_words = narration_words(script, sections)
        words = [w for _section, text in texts for w in text.split()]
        entry = {"script_id": sid, "anchor_starts": starts, "total": total_s,
                 "word_starts": word_starts, "order": script.get("pattern"),
                 "anchor_sides": sides}
        positions = [round(t * rate) for t in starts]
        top_blocks = int(math.ceil(float(band["band_max"]) / scale))
        hold = [b for b in plan.get("blocks") or [] if b.get("role") == ROLE_HOLD]
        h0 = None
        if hold and hold[0].get("anchors"):
            first = hold[0]["anchors"][0]
            if isinstance(first, int) and 0 <= first < len(positions):
                h0 = positions[first]
        rhythm = (script.get("pattern") or {}).get("rhythm_id")
        jobs.append({"sid": sid, "entry": entry, "band": band, "scale": scale,
                     "rate": rate, "words": words, "total_words": total_words,
                     "anchors": len(starts), "top_blocks": top_blocks, "h0": h0,
                     "rhythm": rhythm, "sided": bool(sides)})
    if not jobs:
        return {}

    def entry_for(job, ks, tag, n_words=None):
        e = job["entry"]
        ws = e["word_starts"] if n_words is None else e["word_starts"][:n_words]
        total = e["total"] if n_words is None else n_words / job["rate"]
        sides = [("a" if i % 2 == 0 else "b") for i in range(len(ks))] if job["sided"] else None
        return dict(e, script_id=f"{e['script_id']}{BAND_PROBE_MARK}{tag}",
                    anchor_starts=[ws[k] for k in ks], total=total, word_starts=ws,
                    anchor_sides=sides)

    def ask(batch):
        if not batch:
            return {}
        try:
            answered = run([e for _k, e in batch])
        except CannotAnswer:
            return {}
        out = {}
        for key, e in batch:
            v = _probe_verdict(answered.get(e["script_id"]))
            if v:
                out[key] = v
        return out

    # 1. this speech: even spacing, and the held passage on `hold`.
    shapes = []
    for j, job in enumerate(jobs):
        W = job["total_words"]
        for n in range(2, min(W, job["top_blocks"] + BAND_SEARCH_PAST_TOP) + 1):
            ks = _even_words(n, W)
            shapes.append(((j, "even", n, None), entry_for(job, ks, f"even{n}")))
        if job["rhythm"] == ROLE_HOLD and job["h0"] is not None:
            pairs = [(hw, pw) for hw in range(3, min(W - job["h0"], W // 3) + 1)
                     for pw in range(2, hw)]
            while len(pairs) > BAND_SEARCH_MAX_PROBES:
                pairs = pairs[::2]
            for hw, pw in pairs:
                ks = _hold_shape(W, job["h0"], hw, pw)
                shapes.append(((j, "hold", len(ks), (hw, pw)),
                               entry_for(job, ks, f"hold{hw}x{pw}")))
    answered = ask(shapes)

    def rank(job, key, v):
        measured, refused, findings = v
        lo, hi = job["band"].get("band_min"), job["band"].get("band_max")
        room = _band_room(job["band"])
        inside = lo is not None and lo <= measured <= hi
        return (not refused, inside and (room is None or measured <= room + 1e-9), inside,
                -findings, -abs(key[2] - job["anchors"]))

    found = {}
    for j, job in enumerate(jobs):
        mine = [(k, v) for k, v in answered.items() if k[0] == j]
        if not mine:
            # The planner answered no probe (an older plan_blocks.py, a fake):
            # nothing is known, and "no placement fits" would be a claim.
            continue
        even = {k[2]: v[0] for k, v in mine if k[1] == "even"}
        fits = [(k, v) for k, v in mine if not v[1]]
        best = max(fits, key=lambda kv: rank(job, kv[0], kv[1])) if fits else None
        blocks_measured = job["band"].get("measured")
        search = {
            "asked": True, "anchors": job["anchors"], "measured": blocks_measured,
            "unit": job["band"].get("unit"), "band_min": job["band"].get("band_min"),
            "band_max": job["band"].get("band_max"), "target_top": _band_room(job["band"]),
            "rhythm_id": job["rhythm"], "probes": len(mine),
            "min_measured": min((v[0] for _k, v in mine), default=None),
            "even": {str(n): m for n, m in sorted(even.items())},
            "fit": None, "speech": None,
            "source": ("rhythm.plan_segments(pattern=...) through plan_blocks.py, planned "
                       "again on this speech with the anchors placed as below (CF-0417)"),
        }
        if best:
            (_j, shape, n, extra), (measured, _r, findings) = best
            W = job["total_words"]
            fit = {"shape": shape, "anchors": n, "measured": measured,
                   "priced_findings": findings,
                   "with_room": rank(job, best[0], best[1])[1]}
            if shape == "even":
                fit.update({"every_words": round(W / n, 1),
                            "every_seconds": round(W / n / job["rate"], 2)})
            else:
                hw, pw = extra
                h0 = job["h0"]
                fit.update({"hold_words": [h0, h0 + hw - 1],
                            "hold_seconds": round(hw / job["rate"], 2),
                            "hold_text": _quote(job["words"], h0, h0 + hw - 1),
                            "every_words": pw,
                            "every_seconds": round(pw / job["rate"], 2)})
            search["fit"] = fit
        anchors_measure = job["anchors"] * job["scale"]
        if not best:
            search["cause"] = CAUSE_SPEECH
        elif anchors_measure > float(job["band"]["band_max"]) + 1e-9:
            search["cause"] = CAUSE_ANCHORS
        else:
            search["cause"] = CAUSE_CUT
        found[job["sid"]] = search

    # 2. nothing fits this speech: shorten it (its first K words) until N
    # evenly spaced anchors land inside the band with room.
    short_jobs = [j for j, job in enumerate(jobs)
                  if (found.get(job["sid"]) or {}).get("cause") == CAUSE_SPEECH]
    batch = []
    for j in short_jobs:
        job = jobs[j]
        W = job["total_words"]
        step = max(1, W // BAND_SEARCH_SPEECH_STEPS)
        for k_words in range(W - step, max(W // 2, 2) - 1, -step):
            for n in range(2, min(k_words, job["top_blocks"]) + 1):
                ks = _even_words(n, k_words)
                batch.append(((j, k_words, n), entry_for(job, ks, f"cut{k_words}n{n}",
                                                         n_words=k_words)))
    short = ask(batch)
    for j in short_jobs:
        job = jobs[j]
        room = _band_room(job["band"])
        lo = job["band"].get("band_min")
        ok = [(k, v) for k, v in short.items() if k[0] == j and not v[1]
              and (room is None or v[0] <= room + 1e-9) and (lo is None or v[0] >= lo)]
        if not ok:
            continue
        (_j, k_words, n), (measured, _r, _f) = max(
            ok, key=lambda kv: (kv[0][1], -abs(kv[0][2] - job["anchors"])))
        found[job["sid"]]["speech"] = {
            "max_words": k_words, "max_seconds": round(k_words / job["rate"], 1),
            "words_now": job["total_words"], "anchors": n, "measured": measured,
            "every_words": round(k_words / n, 1)}
    return found


def band_search_sentence(search, band, script=None):
    """The lever, in the words the writer acts on (CF-0417).

    CF-0446: when the script's drawn hold is under the floor the rotation
    issued its pair with (`pattern.speech_fit.hold_floor_seconds`), raising the
    hold to that floor is the first lever - under it the channel's expected
    speech is more blocks than the band's top whatever the anchors - and the
    usual lever (fewer anchors, the probed placement, a shorter speech) comes
    after it. Without a floor, or with the hold at or over it, the sentence is
    exactly what it was."""
    lever = _band_lever(search, band)
    under = sf.hold_under_floor((script or {}).get("pattern"))
    if not under:
        return lever
    drawn, floor = under
    return (f"Axis: the hold first - the drawn key_frame_hold_seconds {drawn:.2f}s is under "
            f"the floor {floor:.2f}s the rotation issued this pair with "
            f"(pattern.speech_fit.hold_floor_seconds, CF-0446): raise `key_frame_hold_seconds` "
            f"to {floor:.2f} (step 6's budget check does it with --write) and run this gate "
            f"again - under that floor the expected speech is more blocks than the band's top "
            f"whatever the anchors. Only if it is still over after that: {lever}")


def _band_lever(search, band):
    """CF-0417's lever sentence, as it was before CF-0446."""
    if not search or not search.get("asked"):
        return ("Every anchor is at least one block, and on a pattern whose hold is short "
                "each stretch longer than the hold is cut into two or more, so the lever is "
                "how many moments this scene is told in. Write fewer of them")
    unit = band.get("unit") or ""
    tail = f" {unit}" if unit else ""
    lo, hi = band.get("band_min"), band.get("band_max")
    n_now, measured = search.get("anchors"), band.get("measured")
    rhythm = search.get("rhythm_id") or "its rhythm"
    fit, cause = search.get("fit"), search.get("cause")

    def fit_words(f):
        if f["shape"] == "hold":
            how = (f"{f['anchors']} anchors - the passage you hold, «{f['hold_text']}» (words "
                   f"{f['hold_words'][0]}-{f['hold_words'][1]}, {f['hold_seconds']}s), as ONE "
                   f"stretch, and the others about every {f['every_words']} words "
                   f"(~{f['every_seconds']}s), each shorter than that hold")
        else:
            how = (f"{f['anchors']} anchors spaced evenly, one about every "
                   f"{f['every_words']} words (~{f['every_seconds']}s)")
        room = "" if f.get("with_room") else " (on the top, without room - the closest found)"
        return (f"asked again on this very speech, the Editor's planner cuts {how} into "
                f"{f['measured']}{tail}, inside {lo}-{hi}{room}")

    if cause == CAUSE_ANCHORS:
        return (f"Axis: the count of anchors - your {n_now} anchors are over the top on their "
                f"own, and every anchor is at least one block. Write fewer of them: "
                f"{fit_words(fit)}")
    if cause == CAUSE_CUT:
        return (f"Axis: the cutting, not the count - FEWER anchors will NOT bring it down. "
                f"Your {n_now} anchors became {measured}{tail} because the Editor's layout "
                f"(`{rhythm}`) cuts the stretches between them into pieces: every stretch "
                f"longer than the drawn hold is cut into two or more (on `hold`, every block "
                f"as long as the held one is). Place them instead as probed: {fit_words(fit)}")
    speech = search.get("speech")
    most = max((int(k) for k in search.get("even") or {}), default=2)
    held = " and with the held passage kept whole" if rhythm == ROLE_HOLD else ""
    head = (f"Axis: the length of the speech - no placement of anchors fits it. Asked again "
            f"on this very speech with 2 to {most} evenly spaced anchors{held}, "
            f"the Editor's planner (`{rhythm}` under the drawn hold) never cuts it into fewer "
            f"than {search.get('min_measured')}{tail}, over the top of {lo}-{hi}. Neither "
            f"fewer nor more anchors answer it")
    if speech:
        return (head + f": cut the speech to at most {speech['max_words']} words "
                f"(~{speech['max_seconds']}s, now {speech['words_now']}) - there "
                f"{speech['anchors']} anchors about every {speech['every_words']} words land at "
                f"{speech['measured']}{tail} - and run the budget check again; if that is under "
                f"the channel's narration floor, the assignment is what does not fit")
    return head + ": the assignment is what does not fit"


def previous_failures(script):
    """Failed attempts already recorded on this script. A record written by an
    older run with no count is one failure, not zero: the record only exists
    because a run wrote it."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 1 if record.get("verdict") == VERDICT_OVER else 0


def previous_attempts(script):
    """CF-0311: what earlier runs of this gate named on this script.

    An empty list on a script written before this task, which is honest: the
    older record kept the count of failures and not what they were about, so
    "nothing is known" and "nothing was named" have to look the same and the
    first refusal after an upgrade says so by saying nothing.
    """
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return []
    attempts = record.get("attempts")
    return [a for a in attempts if isinstance(a, dict)] if isinstance(attempts, list) else []


SCORE_KEY = "score"


def score_findings(plan, breaches, over, problems):
    """CF-0433: the findings this estimate prices, in the score model's shape.

    The Editor's own answer first: `plan_blocks.py` asks `rhythm.pace_findings()`
    and `rhythm.hold_band_findings()` over the very layout judged here and
    returns them as `score_findings`. A planner older than CF-0433 answers
    without the key, and then the hold band is priced off what this gate has:
    one finding per breached block of the layout, or - with no layout at all -
    one per stretch of speech over the band."""
    if problems:
        return []
    if isinstance(plan, dict) and isinstance(plan.get("score_findings"), list):
        return [dict(f) for f in plan["score_findings"]]
    out = []
    for b in breaches or []:
        out.append(_score.finding(
            _score.RULE_HOLD_BAND_EXCEEDED, {"block": b.get("block")}, 1, False,
            f"block {b.get('block')} {b.get('seconds')}s over the band top "
            f"{b.get('band_max')}s (layout estimate)"))
    if not out:
        for g in over or []:
            out.append(_score.finding(
                _score.RULE_HOLD_BAND_EXCEEDED, {"stretch": f"{g['from']}->{g['to']}"}, 1,
                False, f"{g['seconds']}s of speech between two anchors (estimate)"))
    return out


def judge_script(script, channel, root=None, sections=None, plan=None, constants=None,
                 splits=None, band_search=None):
    """`(record, problems)` for one script.

    `problems` are the reasons this script cannot be judged as a cadence at
    all - no anchors, a beat that is not in the speech, no narration. They are
    a rewrite (exit 1) like a failed gap, but they are not counted as a gap
    failure and never spend the topic's one rewrite: a malformed field is a
    different mistake from a scene told in three frames.

    `plan` (CF-0277) is this script's entry of `plan_blocks.py`'s answer - the
    layout the Editor will cut, with `rhythm.ceiling_report()` on it. It is the
    second reading of the one rule, and a breach in it is the *same* failure as
    a gap over the band: one rewrite, then the topic. `check_batch()` always
    supplies it; None means the caller asked without it, and then only the
    stretches are read.
    """
    sections = tuple(sections or counted_sections(channel, root))
    pattern = script.get("pattern") or {}
    pattern_id = pattern.get("pattern_id")
    if not pattern_id:
        raise CannotJudge(
            "no `pattern.pattern_id` - the hold band is the pattern's, so a script with no "
            "drawn pattern cannot be held to one")
    ceiling, ceiling_source = hold_ceiling(pattern_id, root)
    rate, rate_source = speech_rate(script, channel, root)

    texts, offsets, total = narration_words(script, sections)
    speech_seconds = round(total / rate, 3)

    anchors = script.get(FIELD)
    problems, positions = [], []
    if not isinstance(anchors, list) or not anchors:
        problems.append(f"{FIELD}: missing or empty - a script with no anchors has no cadence "
                        f"to judge (CF-0140 refuses it in its own right)")
        anchors = []
    for i, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            problems.append(f"{FIELD}[{i}]: must be an object")
            continue
        at = anchor_word_index(anchor, texts, offsets)
        if at is None:
            problems.append(
                f"{FIELD}[{i}].beat_text: not in the counted narration "
                f"({', '.join(sections)}) - without a position in the speech this anchor's "
                f"gap cannot be measured")
            continue
        positions.append((anchor.get("anchor_id") or f"#{i}", at))
    if total <= 0:
        problems.append(f"narration: the counted sections ({', '.join(sections)}) hold no "
                        f"words - there is no speech to spread over the anchors")

    stretches = gaps(positions, total, rate, ceiling) if positions and total > 0 else []
    worst = max((g for g in stretches), key=lambda g: g["seconds"], default=None)
    over = [g for g in stretches if g["over"]]
    floor = min_anchors(speech_seconds, ceiling)

    # The second reading. A script the gap rule could not place has no layout
    # either, and its `problems` already say so.
    layout = ({"asked": False, "breaches": [], "margin_breaches": []}
              if plan is None or problems
              else layout_reading(script, plan, ceiling, constants, splits))
    # CF-0310: the pattern's OTHER band, on the same layout - how many blocks,
    # or at what pace. Read before the TTS for the first time; the plan that
    # went to the user with `pattern_delivered: null` passed this gate because
    # nothing here asked the question.
    band_read = ({"asked": False, "pattern_read": False, "refuses": False,
                  "refused_here": False,
                  "why": ("the layout was not built, so the block band was not read - a "
                          "record of `not checked`, not of `inside`")}
                 if plan is None or problems else block_band_reading(plan, script, band_search))
    # CF-0447: over the block band's top is a price (`score.block_band_exceeded`),
    # not a refusal; CF-0417's lever stays as the hint of that price.
    band_over = bool(band_read.get("priced_here"))
    band_cause = band_read.get("cause") if band_over else None
    breaches = layout.get("breaches") or []
    worst_block = max(breaches, key=lambda b: b["seconds"] or 0.0, default=None)
    # CF-0303: blocks under the top but over the top less the margin.
    margins = layout.get("margin_breaches") or []
    worst_margin = max(margins, key=lambda b: b["outside_by"] or 0.0, default=None)
    # CF-0353: the stretch the Editor cannot trim, read off the same layout.
    tail = (tail_reading(plan, layout, stretches, positions, rate, pattern_id)
            if plan is not None and not problems else
            {"asked": False, "deliverable": None,
             "why": "the layout was not built, so the tail was not read"})

    # CF-0311: the two stretches that are answered with a time and the words
    # that fall on it instead of with a count of anchors.
    spoken = [w for _section, text in texts for w in text.split()]
    addresses = [a for a in (edge_address(g, spoken, total, rate, speech_seconds, ceiling,
                                          pattern_id, layout.get("margin"))
                             for g in over) if a]

    failed_before = previous_failures(script)
    attempts_before = previous_attempts(script)
    # CF-0433 / CF-0447: no reading fails the script any more - the hold
    # band's three readings and the block band's top are priced and listed
    # apart (`readings_priced`). `named` stays in the record, always empty.
    named = []
    priced_readings = [code for code, fired in ((READING_STRETCH, bool(over)),
                                                (READING_BLOCK, bool(breaches)),
                                                (READING_MARGIN, bool(margins)),
                                                (READING_BAND, band_over))
                       if fired]
    named_before = sorted({c for a in attempts_before for c in (a.get("named") or [])})
    new_readings = []
    rewrites_allowed = REWRITES_ALLOWED

    # CF-0433: the hold band's readings (the stretches, the layout's blocks,
    # the estimate's margin, the tail) are priced now, never refused: each
    # block the Editor's own rhythm.hold_band_findings() finds over the top is
    # `score.hold_band_exceeded` (-2, cap -10), and a pace under an ordered
    # floor is `score.pace_below_floor` (plan_blocks.score_findings()), and
    # since CF-0447 the block band's TOP (rhythm.cadence_band_refuses()) is
    # `score.block_band_exceeded` (-2 a block over, cap -10) - unless the
    # Editor's planner already priced it in its own findings (charged once).
    findings = score_findings(plan, breaches, over, problems)
    if band_over and not problems and not any(
            f.get("rule") == _score.RULE_BLOCK_BAND_EXCEEDED for f in findings):
        findings.append(block_band_finding(band_read))
    score = _score.score_block(findings)
    hold_said = []
    if over:
        first = over[0]
        hold_said.append(
            f"{len(over)} stretch(es) of speech run longer than {pattern_id}'s "
            f"{ceiling}s hold band, the longest {worst['seconds']}s "
            f"({worst['from']} -> {worst['to']}): {len(positions)} anchor(s) over "
            f"{speech_seconds}s of narration, where the band implies at least {floor}. "
            f"First one over: {first['from']} -> {first['to']}, {first['seconds']}s")
    if addresses:
        # CF-0311. The count above is the whole script's; an edge stretch is
        # not aimed by it.
        hold_said.append(addresses[0]["remedy"] if len(addresses) == 1 else
                         ". ".join(a["remedy"] for a in addresses))
    if breaches:
        hold_said.append(
            f"{len(breaches)} block(s) of the layout the Editor will cut run longer than "
            f"{pattern_id}'s {ceiling}s hold band and the montage may not cut them back "
            f"(CF-0276) - the longest is block {worst_block['block']} "
            f"({worst_block['role']}) at {worst_block['seconds']}s, over the top by "
            f"{worst_block['outside_by']}s: {worst_block['remedy']}")
    if margins:
        mr = layout.get("margin") or {}
        hold_said.append(
            f"{len(margins)} block(s) of the layout are inside {pattern_id}'s {ceiling}s "
            f"hold band but over the {mr.get('ceiling_seconds')}s the estimate is held to "
            f"({mr.get('last_block_ceiling_seconds')}s for the last block, CF-0303) - the "
            f"worst is block {worst_margin['block']} ({worst_margin['role']}) at "
            f"{worst_margin['seconds']}s: the voice may put it over the top, and then it "
            f"is priced like the rest")
    if tail.get("deliverable") is False:
        hold_said.append(tail["remedy"])
    if band_over:
        # CF-0447. The other band of the same pattern: its top is a price too.
        hold_said.append(
            f"the layout is outside {pattern_id}'s drawn "
            f"{band_read.get('parameter')} band: "
            f"{band_read.get('measured')} {band_read.get('unit')} against "
            f"{band_read.get('band_min')}-{band_read.get('band_max')}, over the top by "
            f"{band_read.get('outside_by')} ({band_read.get('blocks')} block(s) over "
            f"{band_read.get('block_span_seconds')}s of speech) - "
            f"score.block_band_exceeded for {band_read.get('blocks_over')} block(s) over. "
            f"{band_read.get('remedy')}")
    priced = (f"not refused (CF-0433/CF-0447: the hold band and the block band's top are "
              f"prices) - score {_score.summary(score)} before the "
              f"TTS - {'. '.join(hold_said) or 'the pace is under the pattern floor'}"
              if hold_said or findings else None)

    if problems:
        verdict, action = None, ACTION_REWRITE
        reason = f"{len(problems)} problem(s) with the field; not counted as a gap failure"
        failed = failed_before
    else:
        verdict = VERDICT_PRICED if priced else VERDICT_FITS
        action, failed = ACTION_PASS, failed_before
        if priced:
            reason = priced
        else:
            reason = (f"{len(positions)} anchor(s) over {speech_seconds}s of narration, "
                      f"longest stretch {worst['seconds'] if worst else 0.0}s inside "
                      f"{pattern_id}'s {ceiling}s hold band (at least {floor} implied)")
            if layout.get("asked"):
                reason += (f"; the Editor's layout is {layout['blocks']} block(s), longest "
                           f"{layout['longest_block_seconds']}s, none of them outside the band "
                           f"the montage may not cut")
                mr = layout.get("margin") or {}
                if mr.get("asked"):
                    reason += (f", and none of them over the {mr['ceiling_seconds']}s the "
                               f"estimate is held to ({mr['last_block_ceiling_seconds']}s for "
                               f"the last block, CF-0303)")
        # CF-0310: the block band is said on a pass too, and in both
        # directions. A layout outside an OBSERVED envelope is not a failure -
        # CF-0039 - but "outside and nobody was told" is exactly how
        # `outrider-doune-castle` reached the user, so it is in the sentence.
        if band_read.get("asked"):
            side = "inside" if band_read.get("inside") else "OUTSIDE"
            reason += (f"; the layout's {band_read.get('measured')} "
                       f"{band_read.get('unit')} ({band_read.get('blocks')} block(s) over "
                       f"{band_read.get('block_span_seconds')}s) is {side} {pattern_id}'s "
                       f"{band_wording(band_read)}")
            if not band_read.get("inside") and not band_over:
                reason += f" - recorded, not refused ({band_verdict_note(band_read)})"

    # CF-0311: one entry per failure of the band, kept. The record of an
    # attempt is otherwise overwritten by the next run of the same gate - which
    # is why "was this refusal named on the first run?" could not be answered
    # off the live batches of 09-15..09-21 for one of the three topics they
    # refused, and had to be argued from the run log instead.
    attempts = (attempts_before + [{
        "attempt": failed, "named": named, "new_here": new_readings, "action": action,
        "anchors": len(positions),
        "worst_stretch": (f"{worst['from']} -> {worst['to']}" if over and worst else None),
        "edges_addressed": [a["edge"] for a in addresses],
        "band_cause": band_cause,
        "reason": reason,
    }] if verdict == VERDICT_OVER else attempts_before)

    record = {
        "pattern_id": pattern_id,
        "hold_ceiling_seconds": ceiling,
        "hold_ceiling_source": ceiling_source,
        "counted_sections": list(sections),
        "words": total,
        "words_per_second": rate,
        "words_per_second_source": rate_source,
        "speech_seconds": speech_seconds,
        "anchors": len(positions),
        "min_anchors": floor,
        "max_gap_seconds": worst["seconds"] if worst else None,
        "gaps": stretches,
        # CF-0311: the address of the anchor an over-long edge stretch needs -
        # a time in the speech and the words that fall on it, not a count.
        "edge_anchors": addresses,
        # CF-0277: the same rule read off the layout, not off the stretches.
        "layout": layout,
        "layout_breaches": len(breaches),
        "max_block_seconds": layout.get("longest_block_seconds"),
        # CF-0303: the margin under the top the estimate is held to, and the
        # blocks that are inside the band but not inside it.
        "layout_margin_breaches": len(margins),
        "margin_ceiling_seconds": (layout.get("margin") or {}).get("ceiling_seconds"),
        "margin_band_fraction": HOLD_MARGIN_BAND_FRACTION,
        # CF-0353: the speech after the last anchor, on the Editor's layout.
        TAIL_KEY: tail,
        "tail_deliverable": tail.get("deliverable"),
        # CF-0310: the pattern's other band, at the path the Editor's refusal
        # names (BLOCK_BAND_RECORD_PATH). Written on every judged script,
        # including when it could not be read - "not checked" is a record.
        BLOCK_BAND_KEY: band_read,
        "block_band_measured": band_read.get("measured"),
        "block_band_inside": band_read.get("inside"),
        # CF-0447: always false now - over the top is priced (`block_band_priced`,
        # `block_band_blocks_over`); the key stays for the readers of old records.
        "block_band_refused": False,
        "block_band_priced": band_over,
        "block_band_blocks_over": band_read.get("blocks_over") if band_over else 0,
        "verdict": verdict,
        "failed_attempts": failed,
        "rewrites_allowed": rewrites_allowed,
        # CF-0417: the lever of the block band's overshoot (anchors / cut /
        # speech) - since CF-0447 the hint of its price, not of a refusal.
        "block_band_cause": band_cause,
        # CF-0311: which of this gate's four readings fired, and which of them
        # no earlier attempt had named. The ladder does not turn on this - see
        # "What a failure costs" in the docstring - it is recorded so the next
        # decision about the ladder is made on the batches and not on a memory.
        "readings_named": named,
        "readings_new_this_attempt": new_readings,
        # CF-0433: the hold band's readings that fired and were priced, and the
        # score log of this stage's estimate (shared/score, CF-0432).
        "readings_priced": priced_readings,
        SCORE_KEY: score,
        "attempts": attempts,
        "action": action,
        "reason": reason,
    }
    return record, problems


def skip_entry(script, record):
    """The `skipped[]` entry a refusal writes.

    CF-0232's shape exactly - `{topic_id, reason_code, reason, stage}` - and
    the `reason` is written to be read alone, because the funnel copies it
    verbatim into its `detail` column.
    """
    return {
        "topic_id": script.get("topic_id"),
        "reason_code": SKIP_REASON_CODE,
        "reason": (f"{script.get('script_id')}: {record['reason']}"),
        "stage": FUNNEL_STAGE,
        "anchor_cadence": {k: record[k] for k in
                           ("pattern_id", "hold_ceiling_seconds", "speech_seconds",
                            "anchors", "min_anchors", "max_gap_seconds", "max_block_seconds",
                            "layout_breaches", "layout_margin_breaches",
                            "margin_ceiling_seconds", "block_band_measured",
                            "block_band_inside", "block_band_refused", "block_band_priced",
                            "block_band_blocks_over", "failed_attempts")},
    }


# --------------------------------------------------------------------------
# the batch
# --------------------------------------------------------------------------

def report_lines(script, record, problems):
    sid = script.get("script_id")
    if problems:
        head = f"  FAIL   {sid}: {len(problems)} problem(s) with the cadence question itself"
        return [head] + [f"    - {p}" for p in problems]
    mark = {ACTION_PASS: "ok    ", ACTION_REWRITE: "REWRITE", ACTION_REFUSE: "REFUSE"}[
        record["action"]]
    lines = [f"  {mark} {sid}: {record['reason']}"]
    if record["action"] != ACTION_PASS or record.get("readings_priced"):
        addressed = {(a["from"], a["to"]): a for a in record.get("edge_anchors") or []}
        for gap in record["gaps"]:
            if gap["over"]:
                lines.append(f"    over: {gap['from']} -> {gap['to']}  {gap['seconds']}s "
                             f"({gap['words']} words) > {record['hold_ceiling_seconds']}s")
                # CF-0311: the edge stretches, and only they, are answered with
                # an address - the count the summary gives does not aim them.
                address = addressed.get((gap["from"], gap["to"]))
                if address:
                    lines.append(f"      anchor needed "
                                 f"{'no earlier' if address['edge'] == EDGE_TAIL else 'no later'}"
                                 f" than {address['deadline_seconds']}s (word "
                                 f"{address['word_index']}), under the "
                                 f"{address['ceiling_seconds']}s ceiling: "
                                 f"«{address['words']}»")
                    # CF-0364: and the other end of the window.
                    if address.get("window_words"):
                        lines.append(f"      window {address['window_from_seconds']}-"
                                     f"{address['window_to_seconds']}s (words "
                                     f"{address['window_words'][0]}-"
                                     f"{address['window_words'][1]}): "
                                     f"«{address['window_text']}»")
                    elif address.get("one_anchor_closes") is False:
                        lines.append(f"      no window: one anchor cannot close this end - "
                                     f"two anchors, or cut its speech")
        for b in (record.get("layout") or {}).get("breaches") or []:
            lines.append(f"    over: block {b['block']} ({b['role']}, anchors {b['anchors']})  "
                         f"{b['seconds']}s > {b['band_max']}s, +{b['outside_by']}s "
                         f"[{b['code']}]")
            lines.append(f"      {b['note']}")
            sp = b.get(SPLIT_KEY) or {}
            if sp.get("anchors"):
                # CF-0364: the side, first - it is the half a rewrite gets wrong.
                lines.append("      split: " + ("" if sp.get("found") else "(best, not enough) ")
                             + "; ".join(f"side {a['side']!r} at {a['seconds']}s (word "
                                         f"{a['word']}, window {a['window_words'][0]}-"
                                         f"{a['window_words'][1]})"
                                         for a in sp["anchors"])
                             + f" -> {sp.get('pieces_seconds')}"
                             + f"; same side {sp.get('run_side')!r} splits it: "
                             + ("yes" if sp.get("same_side_splits") else "no"))
            lines.append(f"      what to change: {b['remedy']}")
        # CF-0303: one line per block that is merely too close to the top, and
        # the aimed sentence once, for the worst of them. Eight copies of the
        # same paragraph is how a report stops being read.
        close = (record.get("layout") or {}).get("margin_breaches") or []
        for b in close:
            seat = "the LAST block" if b.get("last_block") else f"block {b['block']}"
            lines.append(f"    close: {seat} ({b['role']}, anchors {b['anchors']})  "
                         f"{b['seconds']}s > {b['ceiling']}s (= {b['band_max']}s top less a "
                         f"{b['margin']}s margin), +{b['outside_by']}s [estimate_margin]")
        if close:
            worst = max(close, key=lambda b: b["outside_by"] or 0.0)
            lines.append(f"      the margin is the correction for the estimate of the speech "
                         f"(CF-0303), not spare room: aim the rewrite at the ceiling above, "
                         f"not at the {worst['band_max']}s top")
            lines.append(f"      what to change: {worst['remedy']}")
    tail = record.get(TAIL_KEY) or {}
    if tail.get("deliverable") is False:
        lines.append(f"    tail: {tail['last_anchor']} -> end  "
                     f"{tail['speech_after_last_anchor_seconds']}s in {tail['blocks']} "
                     f"block(s) {tail['block_seconds']} - not handed out inside the band "
                     f"[{tail['editor_gate']}"
                     + (f"/{tail['editor_trim_code']}" if tail.get("editor_trim_code") else "")
                     + f"], cut >= {tail['words_to_cut']} word(s) or anchor the final")
    # CF-0310: the other band, printed whenever the layout is outside it -
    # on a pass too. An observed envelope refuses nothing, and the operator
    # still has to see that the video being written is not cut like the
    # pattern it was assigned: that is the one line nobody had on
    # `outrider-doune-castle`.
    band = record.get(BLOCK_BAND_KEY) or {}
    # CF-0314: a mode word neither repository knows is louder than silence and
    # quieter than a refusal - the band is there, it was not read, and nothing
    # is claimed about the layout. The operator sees which word stopped it.
    if not band.get("asked") and band.get("code") == BAND_MODE_UNREADABLE_CODE:
        lines.append(f"    band: not read - {band.get('why')} "
                     f"[{BAND_MODE_UNREADABLE_CODE}]")
    if band.get("asked") and not band.get("inside"):
        unit = band.get("unit") or ""
        lines.append(
            f"    band: {band.get('blocks')} block(s) over "
            f"{band.get('block_span_seconds')}s = {band.get('measured')} {unit}, outside "
            f"{band.get('pattern_id')}'s {band_wording(band)} "
            f"{unit} by {band.get('outside_by')} [{band.get('code')}]")
        if band.get("priced_here"):
            # CF-0447: a price, not a refusal - the lever is the hint.
            lines.append(f"      priced, not refused: score.block_band_exceeded x "
                         f"{band.get('blocks_over')} block(s) over the top; to win the points "
                         f"back: {band['remedy']}")
        else:
            lines.append(f"      recorded, not refused - {band_verdict_note(band)}"
                         f". The reading is at {BLOCK_BAND_RECORD_PATH}")
    return lines


def check_batch(batch_file, write=False, root=None, channel=None, script_id=None, out=print,
                editor_python=None, planner=None, editor_scripts=None, patterns=None,
                timeout=DEFAULT_TIMEOUT):
    """Judge every script of the batch. `(problems, refused, records, unjudged)`.

    `problems` are rewrites, `refused` are the topics that left the batch,
    `unjudged` are the scripts the question could not be asked about at all -
    no drawn pattern, no hold band, no rate. Those are collected per script
    rather than raised, so a replay over an old batch still judges the scripts
    it can and names the ones it cannot; the run as a whole is still exit 3,
    because a gate that could not judge a script has not passed it.

    With `write`, the record goes onto every judged script, a refused script
    is moved out of `scripts[]` into `skipped[]`, and the file is rewritten
    once at the end - the record of a refusal is the point of the run, so it
    is written whatever the verdicts were.
    """
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotJudge(f"cannot read {batch_file}: {exc}")
    # CF-0197: the channel id frozen in an old batch may no longer exist.
    channel = channel or resolve_channel(data.get("channel"), root)
    sections = tuple(counted_sections(channel, root)) if channel else FALLBACK_SECTIONS

    scripts = [s for s in data.get("scripts", [])
               if script_id is None or s.get("script_id") == script_id]
    # CF-0430: a script whose text and anchors are the ones this gate last
    # asked to rewrite is not judged again - nothing is spent, the answer is
    # the last one (`_rewrite_guard`).
    held = []
    scripts, _unchanged, same = rg.split(scripts, RECORD_KEY, sections, held.append, write)

    # CF-0277: one child process for the whole batch, before any script is
    # judged - the layout the Editor will cut, under the pattern's own drawn
    # ceiling. A script that cannot be placed in time contributes no entry and
    # is judged on its stretches alone, which is all its `problems` allow.
    entries = [e for e in (layout_entry(s, sections, channel, root) for s in scripts) if e]
    paths = planner_paths(root, editor_python, planner, editor_scripts, patterns)
    plans, constants = (run_planner(entries, paths, timeout,
                                    margin_fraction=HOLD_MARGIN_BAND_FRACTION,
                                    last_margin_fraction=HOLD_MARGIN_LAST_BLOCK_FRACTION)
                        if entries else ({}, {}))

    # CF-0364: the swing blocks over the band, planned again with a new anchor
    # in - which side and which words actually split them. Probes only; the
    # verdicts below are still made on the plans above.
    splits = (split_search(scripts, plans, sections, channel, root, paths, timeout)
              if plans else {})
    # CF-0417: over the block band's top - the cause and the count of anchors
    # the Editor's own layout puts inside it, planned again on each speech.
    searches = (band_search(scripts, plans, sections, channel, root, paths, timeout)
                if plans else {})

    out(f"{batch_file}: {len(scripts)} script(s); channel {channel}; "
        f"speech = {', '.join(sections)}; the band is held twice - over the stretches of "
        f"narration and over the Editor's own layout "
        f"(`rhythm.plan_segments(pattern=...)` through {paths['planner'].name} on its venv, "
        f"CF-0276/CF-0277), and the layout is held under the top less a margin of "
        f"{HOLD_MARGIN_BAND_FRACTION} of the band's width "
        f"({HOLD_MARGIN_LAST_BLOCK_FRACTION} on the last block) because the layout is "
        f"measured on an ESTIMATE of the speech (CF-0303); the same layout is held to the "
        f"pattern's block band, in whichever shape it states it, and refused on the Editor's "
        f"own `rhythm.cadence_band_refuses()` (CF-0310). Since CF-0433 the hold band and a "
        f"pace under the floor are priced (score.hold_band_exceeded, score.pace_below_floor), "
        f"and since CF-0447 the block band's top too (score.block_band_exceeded, 2 a block "
        f"over, cap 10, with the lever of CF-0417 as its hint) - nothing here sends a "
        f"script back on the rhythm; the score decides in 6b's rounds (plan_check_loop)")
    for line in held:
        out(line)

    problems, refused, records, unjudged = list(same), [], {}, []
    for script in scripts:
        try:
            record, own = judge_script(script, channel, root, sections,
                                       plan=plans.get(script.get("script_id")),
                                       constants=constants,
                                       splits=splits.get(script.get("script_id")),
                                       band_search=searches.get(script.get("script_id")))
        except CannotAnswer as exc:
            out(f"  ?      {script.get('script_id')}: cannot judge - {exc}")
            unjudged.append(f"{script.get('script_id')}: {exc}")
            continue
        records[script.get("script_id")] = record
        for line in report_lines(script, record, own):
            out(line)
        if own:
            problems += [f"{script.get('script_id')}: {p}" for p in own]
        elif record["action"] == ACTION_REWRITE:
            problems.append(f"{script.get('script_id')}: {record['reason']}")
        elif record["action"] == ACTION_REFUSE:
            refused.append(script)
        if write:
            script[RECORD_KEY] = rg.stamp(record, script, sections)

    if write:
        if refused:
            ids = {id(s) for s in refused}
            data["scripts"] = [s for s in data.get("scripts", []) if id(s) not in ids]
            data.setdefault("skipped", [])
            for script in refused:
                data["skipped"].append(skip_entry(script, records[script.get("script_id")]))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        out(f"  wrote {path}: `{RECORD_KEY}` on {len(scripts)} script(s)"
            + (f", {len(refused)} topic(s) moved to skipped[] as `{SKIP_REASON_CODE}`"
               if refused else ""))
    elif refused:
        out(f"  note: {len(refused)} topic(s) are refused but nothing was recorded - "
            f"re-run with --write so the funnel sees the loss")
    return problems, refused, records, unjudged


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--write", action="store_true",
                    help="record the verdict on every script, and move a refused topic into "
                         "skipped[] (this is what the funnel reads)")
    ap.add_argument("--script-id", default=None, help="judge one script instead of the batch")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    ap.add_argument("--channel", default=None, help="override the batch's own channel id")
    ap.add_argument("--out", default=None, help="write the records here as JSON")
    ap.add_argument("--editor-python", default=None,
                    help="interpreter for the Video Editor's block planner (default: its "
                         ".venv). The layout reading of the band runs there, never here")
    ap.add_argument("--planner", default=None,
                    help="path to plan_blocks.py (default: this repository's)")
    ap.add_argument("--editor-scripts", default=None,
                    help="the Video Editor's scripts/ (default: the checkout's)")
    ap.add_argument("--patterns", default=None,
                    help="the factory root's patterns/ (default: the checkout's). The drawn "
                         "band the layout is cut to is read from there by the Editor's own "
                         "`rhythm.load_pattern()`")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = ap.parse_args(argv)
    try:
        problems, refused, records, unjudged = check_batch(
            args.batch_file, write=args.write,
            root=Path(args.root).resolve() if args.root else None,
            channel=args.channel, script_id=args.script_id,
            editor_python=args.editor_python, planner=args.planner,
            editor_scripts=args.editor_scripts, patterns=args.patterns,
            timeout=args.timeout)
    except CannotAnswer as exc:
        print(f"check_anchor_cadence.py: {exc}", file=sys.stderr)
        print("nothing is claimed about the scripts; do not rewrite anything on this run",
              file=sys.stderr)
        return EXIT_CANNOT_JUDGE
    if args.out:
        Path(args.out).write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    if unjudged:
        # Ahead of the rewrites on purpose: a run that could not judge every
        # script has not passed the batch, whatever it said about the rest,
        # and the remedy is the environment rather than a rewrite.
        print(f"\n{len(unjudged)} script(s) could not be judged:", file=sys.stderr)
        for u in unjudged:
            print(f"  - {u}", file=sys.stderr)
        print("fix these and run again; nothing is claimed about them", file=sys.stderr)
        return EXIT_CANNOT_JUDGE
    if problems:
        print(f"\n{len(problems)} script(s) to rewrite:")
        for p in problems:
            print(f"  - {p}")
        return EXIT_REWRITE
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}` - the second "
              f"failure of this band, over a stretch or over a block, is the topic's "
              f"last; there is nothing to rewrite")
        return EXIT_REFUSED
    return EXIT_OK


@runlog.script("content-researcher", "check-anchor-cadence", name="check_anchor_cadence.py")
def cli():
    """The command-line entry (CF-0107). Exit 1 (a rewrite), 3 (cannot judge)
    and 4 (a topic refused) are all recorded as `failed`, which is correct: a
    gate that stops a script before TTS is the record this task exists to
    produce."""
    sys.exit(main())


if __name__ == "__main__":
    cli()

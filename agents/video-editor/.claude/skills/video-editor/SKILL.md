---
name: video-editor
description: Turn a Content Researcher script into a finished vertical video — source assets, synthesize voiceover, build a captioned montage in one of three styles. Use when invoked as "/video-editor <channel> <batch-id> <script-id>".
---

You are the **Video Editor** agent in a YouTube shorts-content-factory pipeline. You take one compliance-cleared script and produce a finished 9:16 video.

You do **not** decide what to say — that is written. You do **not** re-check compliance — that happened twice upstream. You are agnostic to subject matter: nothing here knows or cares that the channel is about television. You **do** read the script, because a montage assembled without understanding the words is how v2 put the word "ATE" over the top of a man's head.

## Pipeline v3 — Remotion engine (current, rebuilt 2026-08-30)

v2 composed frames with raw ffmpeg `filter_complex`. Its defects were not bugs but the ceiling of that tool: centre crops that ignored faces, a `zoompan` whose unset `x`/`y` defaulted to the top-left corner and decapitated every shot, a frozen blurred third of the frame, cuts on equal time slices, no transitions, and two lossy encoding passes. Composition now happens in Remotion; ffmpeg keeps the work it is good at.

**Division of labour — do not blur it:**
- **ffmpeg** — asset preparation (trimming clips, extracting frames, cropping, normalising) and all audio.
- **Remotion** (`render/`) — frame composition, captions, transitions, final render and mux.
- Kokoro TTS and whisper word-alignment are unchanged from v2.

What a render costs on this machine is measured per kind of block in `docs/render-speed.md` (generated from `work/cf0052-measure/measured.json`; the old "about 2× realtime" was never true, CF-0052). One encoding pass, so bitrate is ~4x v2's at the same content.

### Styles

Style is an input, not a property of the channel. A channel config carries the *set* of styles it allows; the request picks one. Always record which style was delivered — the Analyst will need to correlate style against response, and that correlation is impossible to reconstruct later.

- **`motion`** — real footage in movement. Highest ceiling, needs `yt-dlp` and a usable source.
- **`stills`** — photographs with subject-aware cropping and Ken Burns.
- **`typographic`** — kinetic text over a procedural background. **Zero external assets by design**: it is the floor of the *whole-video* chain, so it must be incapable of failing for want of a file. It is not a floor a single block falls to — CF-0137 below closed that route.

**`asset_kind: card` is not `typographic`** (CF-0041). Both render without a file; only one of them is a fallback. A card is a text frame the factory draws on purpose — the `count_card` opening puts the number a list promises on screen in the first second — so it has no source file, no rights to clear, no `qc_asset`, no `smart_crop` and nothing to degrade *from*; `--degrade-block` on a card is refused in writing. `typographic` is where a *video* lands when its footage failed — and, until CF-0137 below closed it, where a single block landed when its own footage did. If the two were one kind, `style_delivered` could not tell a video that chose a card from one that ran out of footage, which is why CF-0015 asked for the separate kind.

**Degradation is a chain, and it is loud**: `motion → stills → typographic` — that is the chain for a whole *video*; a block has one rung to fall, `clip → still`, because the third one is gated shut (CF-0137 below). Re-cut once at the block's current rung, then drop — but the drop is **per block, never per video** (CF-0031) — and every rebuild you render counts against one of the video's two ceilings (CF-0098/CF-0415, below): a rebuild whose only change is the degradation QC itself named is a **QC degrade** and spends `max_qc_degrades_per_video`; every other rebuild — a re-cut, a re-resolve, a degradation QC did not name — spends the **attempt cap**. `qc_render.py`'s `frozen_blocks()` names the exact `(block_index, motion_score)` pairs that failed the post-render motion probe; only those indices move down a rung, via `build_render_plan.py --degrade-block "IDX:TARGET:REASON"` (e.g. `--degrade-block "4:still:motion 0.32 below threshold"`), while every other block keeps the asset it already had. A video finishing with 18 motion blocks and 1 still block is the *correct* outcome of a single frozen block — not a bug to fix by flattening the other 18.

One re-cut at the block's *current* rung before it drops (the cap leaves no room for two): re-cut the same anchor against a different candidate first, and only degrade that one block's `asset_kind` (clip → still, or, if a still itself cannot pass, still → typographic — which on today's channels means the plan is refused rather than degraded, CF-0137 below) once both attempts fail. Never re-render the whole plan in a simpler style just because one segment failed — that was the CF-0031 defect: a single frozen title-card block turned an entire 19-block motion video into an all-stills video, discarding 18 good motion blocks that never failed anything.

**A `subject` failure is not a degradation (CF-0294)**: `qc_render.py` also checks DoD item 7 on the finished file — a block whose plan promised a person (`roi_source: faces`, `fit: cover`) has to show a face in the render, or the source has to explain why it does not. The failure names the block, the timecode and how much of the nearest face the block's window kept (`the crop landed off the subject`, gate short name `subject`). Dropping that block a rung does not fix it — the framing is wrong, not the motion: re-cut the anchor against another candidate, and if the block keeps coming back on the same shot, say so in the report rather than degrading the video around it. A block the gate excuses (`the source has no face here either`) is a note, not a failure, and needs nothing.

**The re-cut lever (CF-0367): `resolve_anchors.py ... --exclude-candidate BLOCK`.** "Re-cut the anchor against another candidate" is one flag: add it to the same `resolve_anchors.py` command that built the storyboard (same OUTPUT path - it reads the storyboard it replaces), with BLOCK as `qc_render.py` numbers it (`6`), or `6=EmOTDswBfgE:28` to name one shot of a multi-shot block. That block's shot is refused **for that anchor only**, ahead of every other gate, and the anchor is filled by its next candidate through the ordinary `fill()` — the repeat guard (CF-0337), burned text (CF-0351/0354), the entity guard (CF-0348) and the `even` budget (CF-0370) all apply as to a first choice. Exclusions carry over to the next re-cut, so the second one cannot bring the first rejected shot back. Stderr says what moved: `RECUT: block 6: A -> B`, and `RECUT: block k changed too: ...` when the freed or taken shot shifted a later block under the one-use ledger — copy those lines into the report. Then rebuild the plan, the soundtrack and render as usual: the render is an attempt like any other (`recut:<block=shot>` in the ledger), inside the cap. **When:** a `subject` failure (the face is really off the picture), or a block frame-judge or a human rejected for its picture, where another candidate of the same anchor could answer the phrase. **Not when:** the gate's failure is about the footage itself (frozen → `--degrade-block`), or `unresolved_anchor`/`pool_too_thin` (there is no next candidate — the storyboard's `rejected_candidates` for that phrase tell you before you spend an attempt; an anchor left with nothing is refused by the plan, not filled). `RECUT NOT APPLIED` (exit, storyboard untouched) means the block is not filled from the candidate pool at all (an opening split, a card).

**A face only the whole frame resolves is not a framing miss (CF-0367).** When the window keeps the source's face whole and the render shows none, `qc_render.py` asks Vision once more about the source cut to that window (same pixels, nothing resampled). A face there that the render lost is a failure (`yet the delivered picture shows none`); no face there either means Vision only finds it with the rest of the frame around it — a profile, a small or dim face — and the block is a note (`the empty answer is the detector's, not the framing's`), not a failure. `2026-09-23T1722Z`/american-dread-story block 6: a strict profile at confidence 0.583 in a held 1080x1080 frame, 100% inside the window, invisible to Vision in the window's own crop — and on screen for the viewer. Do not re-cut for that note.

**The one legitimate whole-video drop**: after per-block degradation, if a plan comes back with *zero* surviving `clip`/`still` blocks — i.e. the source material itself is bad, not one segment of it — then and only then re-run `build_render_plan.py` with a plain `--style` on the *original, undegraded* storyboard to drop the whole video a rung. `build_render_plan.py` prints exactly this signal (`ALL BLOCKS DEGRADED: zero surviving clip/still blocks...`) when it applies. This is the escape valve, not the default path. With the per-block assetless rung off — which is every channel today — that state is not reachable: the only way to zero surviving clip/still blocks is blocks dropped to `typographic`, and the CF-0137 gate below refuses the plan (exit 2) before this line is printed. The signal survives for a channel that switched the rung on; everywhere else the refusal is the end of the road and its answer is material.

Every drop — per-block or, in that one case, whole-video — is written to `degradation` in the batch metadata (`write_batch_metadata.py` reads `plan["degraded_blocks"]`: block index, from, to, reason) *and* said out loud in the report. `style_delivered` reflects a mixed result too (e.g. `motion (mixed: 1/19 block(s) degraded)`) rather than silently reporting the simplest style present. Never substitute silently, and never let one bad block's fix erase the report of what actually shipped.

**CF-0330 (the user, 2026-09-23): the three pool gates warn, they do not refuse.** `anchor_preflight` / `pool_too_thin` (step 3), the assetless rung / `pattern_undeliverable` (rung 4 below) and the two-source gate all record a warning — the same gate id, funnel code, sentence and numbers a refusal carried, with `severity: "warn"` — and the video goes on. The warnings ride `plan["warnings"]` into `05-video-editor.json` → `videos[].warnings`; they are never in `refusals[]`. Reason: the rebuild of 2026-09-23 refused both videos the user had accepted for publication (`everyday-sorcery-2` on a best candidate of 0.2198 against a floor of 0.22, `widows-bay` on 3 of 24 blocks with no picture), and the two-source gate was priced by CF-0320 at 2 of 5 ready videos. Where the prose below says "refuses" about these three, read "warns"; the measurement it describes is unchanged. **Do not stop a video on one of these warnings, and do not hand the script back for one** — carry the `WARNING` lines into the report.

**A block with no picture does not reach a shipped video (CF-0137)** — *the rule until CF-0330; the ladder below still runs, and its bottom rung is now a warning (4).* The bottom of the chain above is `typographic` *as a style*; the bottom of a *block* whose anchor resolved to nothing is a different thing, and CF-0123 (grill 2026-09-07) called it brak. In batch `2026-09-03T2037Z` the per-block assetless rung — `asset.kind: procedural` dropped into the middle of the footage — arrived in runs of 2.1 to 14.3 consecutive blocks and took 14–38 % of the running time of three videos out of four. That is a hole in the montage, not a degradation of it. A block that resolved to nothing now climbs a ladder, in this order:

1. **An insert from the library** — `CF-0138`, not implemented yet. The rung is named so that CF-0138 has a place to land; today it is never taken.
1b. **The topic's own footage (CF-0337) — before any repeat.** On every channel where rung 3 is off (every channel today; `resolve_anchors.py --channel <id>` reads the switch, no `--channel` = off), an ordered block nothing matched gets the best **unused** shot of the topic: first the phrase's own candidates the 0.22 floor refused, nearest first, then any shot of any source passed with `--index`. Every regular gate applies (ledger, usable(), swing rules). Recorded as `topic_fill: {rung, shot, score, reason}` on the block and in `unresolved_anchors`. Pass **every** source of the topic as `--index` — the rung can only reach what it is given. Only when no source has an unused usable shot left does the block go further down; the answer to that is material (CF-0338), never a background.
1c. **A supplement shot without its entity is never placed (CF-0348).** A thin-pool supplement source (`01b-footage-index.json`: `fetched[].supplement.entity`, sieve record `judged_by: entity`) is another film or an interview fetched *for* an entity; its shots in the sieve's `off_topic_shots`, or with `shows_entity: false`, are neither the topic nor the entity. `resolve_anchors.py` (`entity_guard.py`; the report is found above `--clips-dir`, or pass `--footage-index`) drops them before any rung - regular match, split opening, topic footage, emergency repeat - and `fill()` refuses them again; they are listed in `rejected_candidates` with CF-0348. `qc_render.py` FAILs a plan that carries one anyway (`entity` gate). Ordinary sources are untouched.
1d. **A shot with somebody else's burned-in text is never placed (CF-0351).** A shot the describer marked `burned_text: true` in `shared/footage/<id>.shots.json` (a caption outside the bottom band, a title or name card, an end card - CF-0299) is refused by the same chokepoint as 1c, for *every* source: dropped before any rung, never offered by the topic rung, refused again by `fill()`, listed in `rejected_candidates` with CF-0351. `qc_render.py` reads each plan shot's entry from `--footage-dir` (default `shared/footage`) by its `<id>:<n>` and FAILs a block whose shot carries `burned_text: true` (`burned_text` gate) - the same read makes `shows_entity: false` of 1c visible to it. The frame judge still looks at the finished frames; this keeps a known card out before the render.
1e. **An unanswered card counts as text (CF-0354).** Two thirds of the pool was indexed before the describer was asked about burned-in text, so `burned_text` is simply absent there and 1d refused only what was marked (block 0 of everyday-sorcery-2 then took `QE0W5UW2qxE:20`, a card reading "MovieLink" with no flag). A shot with `is_card: true` whose `burned_text` is missing or `null` is refused by the same chokepoint and FAILs `qc_render` under the same `burned_text` gate, until the describer marks it `false`. A non-card without the flag still passes - an unasked shot is not a refused one; filling the flag over the old pool is footage-indexer work. Priced on the two accepted videos (outrider-doune-castle 1541Z, widows-bay 1053Z): 0 of 34 shots.
1f. **A block that retells the event takes the event's own footage (CF-0545).** When the script retells a hunter scene that names a moment on screen (monologue, episode, finale, cameo - not "X says/reveals", not a box office figure), an *interview of another production* (nature `interview` by the hunter, a supplement request or the title in `shared/footage/index.json`, on a channel that is not the work's own) is taken out of every anchor whose words do not say "interview" / "podcast" / "talk show" / "late night" or the interview's show or host - before any rung, and `fill()` refuses it again (`event_footage.py`; `rejected_candidates` with CF-0545). WNL 0701Z: *Late Night with Sam Meadows* under the monologue. The storyboard's `event_footage` says whether the rule was on and why; `short[]` names the blocks the event's own footage did not carry - they go down the ladder, never back to the interview, and the `WARNING: event footage (CF-0545)` line goes into the report: the pool wants a supplement of the event's footage (CF-0345). The rule is the factory root's `shared/event_footage.py` (CF-0575; `scripts/event_footage.py` loads it, no copy) - the Content Researcher asks for that supplement before the voice (`event_footage_short`). See `docs/empty-block-ladder.md`.
2. **The emergency shot repeat** — exactly **one per video** (`rhythm.MAX_EMERGENCY_REUSE_PER_VIDEO = 1`), one single repetition and not one per block that wants one. Spent in `resolve_anchors.py`, where the pool and the `ShotLedger` are, and taken only from the block's **own** candidate pool — the shots the CF-0121 reuse cap refused for this phrase — never an arbitrary shot from elsewhere: a phrase that matched nothing at all does not raise this rung, it goes straight to 3/4. Refused next to its own first showing (`alternation_report()` counts an adjacent repeat as a failure of alternation) and refused outright inside a swing block, where CF-0074 does not bend — there the alternative simply changes from a filler to a refusal. Ordered segments only: on `even` an unresolved site is carried to the next anchor by `settle_unresolved()` (CF-0124) and never becomes an assetless block, so there is nothing to spend the budget on. Recorded as the `emergency_reuse` shortfall — which shot, which blocks, why — and carried out to `videos[].emergency_reuse` and to a `MATERIAL SHORT` line in the report.
3. **The per-block assetless rung — and only on a channel that switched it on.** `channels/<channel>.json` → `assetless_block_rung: {"enabled": ...}`, beside `insert_layers`, read by `scripts/assetless_rung.py`. Off by default, off on every channel today, and off on channels that do not exist yet: an absent, null or unreadable key is `false`. There is deliberately **no CLI override** — the two-source gate has `--two-source-gate`, this has nothing, because a flag on the command line is how permission to publish a hole gets bought quietly. Turning it on is a channel's editorial decision, not a render knob, which is also why it does not sit under `video_editor` with `max_attempts_per_video`.
4. **The planner warns (CF-0330; until 2026-09-23 it refused).** The block stays on the procedural rung — `asset.kind: procedural`, which Video.jsx paints as the ProceduralBg for exactly that block's span, the deterministic render the rung has had since CF-0031 — the plan is written, `ASSETLESS BLOCKS - WARNING, the plan is written [pattern_undeliverable/assetless_rung]` goes to stderr, a warning record with the blocks, their seconds and the block total goes into `plan["warnings"]`, `plan["assetless_rung"]` says `passed: false, warned: true`, and `plan.assetless-rung.json` is still written beside the plan for CF-0139's rotation. The rest of this item is how the refusal worked, kept because the deficit file is the same: the planner used to exit 2, write no plan, and drop `plan.assetless-rung.json` where the plan would have been — the same move as CF-0118's `plan.two-source-gate.json`, and for the same reason: blocks, seconds, reasons and `passed: false` in a record you can read instead of stderr you have to parse. What the registry then does with the refusal is CF-0139's; since CF-0254 the refusal is also one line in the batch's own `05-video-editor.json` → `refusals[]` (`pattern_undeliverable` — the pattern's blocks could not be filled), so the funnel at the root can say why this script produced no video. **The answer to the shortage is still material, not a rebuild** — the warning is what tells the operator to widen the pool; do not re-run in a simpler whole-video style to make it go away.

**No repeat and no look-alike within 5 s (CF-0337, `scripts/repeat_guard.py`).** Every pick — regular, topic rung, emergency repeat — is refused when the same shot, or a shot of the same source whose clip correlates >= 0.85 (three 32x18 greyscale frames), ended less than 5 s before. `qc_render.py` fails the render on the same two rules (`repeated picture`) and on any `procedural` block of a plan whose channel has rung 3 off (`procedural background`) — the second net after the planner's warning.

**The refusal happens before the render, not after.** `qc_render.py` does not know the word `degraded` at all: it probes the finished file, so by the time it could notice a procedural background the frames have already been paid for. The gate sits in `build_render_plan.py` on the finished block list, next to the two-source gate and ahead of the expensive layers, so a refused video costs one plan-building run and no frames. It judges by `rhythm.has_picture()` on the blocks (CF-0136), not by `degraded_blocks` — a new branch that forgets to write its degradation record still does not slip past it. `--degrade-block "IDX:typographic:REASON"`, the other per-block route onto this rung and the one `qc_render.py` feeds, goes through the same gate; rungs 1-2 do not exist at that stage, so for it the ladder is the channel switch or the refusal.

**No threshold, and none to invent.** It was proposed that a video be refused only past some share of assetless running time ("more than 25 %", "a run longer than 6 s"). CF-0137 refused that: with the rung off the rule is boolean — the hole is there or it is not — and one assetless block refuses the plan. Stretching a neighbouring block over the gap is not the way out either: that is what CF-0085 removed and CF-0131 found in an already-published video, 74 % of a block a frozen last frame.

**A refusal says whether there was ever a picture to lose (CF-0150).** `degraded_from` names the rung a hole fell from; it cannot say whether the pool had anything to fill it with, and after CF-0139 fixed the classifier all 15 shortage records of batch `2026-09-03T2037Z` came back `footage_unusable` — "the frame exists, we cannot take it" — including the Clooney water taxi, whose only offer scored 0.116 against a 0.22 floor. Beside `degraded_from` there is now a third fact, taken in `resolve_anchors.candidate_supply()` where the candidates are actually enumerated and carried to `plan.assetless-rung.json` → `assetless_rung.anchors[].candidate_supply`. Three codes and a `null`, in the shape CF-0193 gave `meme_layer.beat_failure()` — a diagnosis with the evidence to check it by: `pool_offered_nothing` (the matcher merged no candidate at all), `pool_offered_off_topic` (candidates were ranked and the best is under `--min-score` — nothing here depicts the anchor; **buy material, do not loosen the gate**), `pool_offered_refused` (a candidate stood at or over the floor and the gates or a failed cut took every one — ours to fix, not the pool's), and `null` when the pool delivered. The key is written on **every** block, `null` included: an *absent* key means a plan older than CF-0150, and `rotation/shortage.py` reads historic records. Taken before the emergency repeat of rung 2, deliberately — a picture shown twice is not a picture the pool supplied. On the real Clooney footage today: 11 anchors, 6 delivered, 4 `pool_offered_refused` (best offers 0.28–0.38, all taken by the gates), 1 `pool_offered_off_topic` — the water taxi, and the only one of the eleven whose answer is footage.

**The flat style is untouched.** `--style typographic` never consults this gate (`assetless_rung.style_typographic()` is the one comparison that tells them apart, which is why the gate is asked after the plan's style is known). A whole video *chosen* to have no footage is CF-0015's rotation working as designed; what CF-0123 called brak is the tearing, not the look.

### The attempt cap (CF-0098)

The stage's cost grows with rebuilds, not with the length of a video: batch `2026-09-03T2037Z` spent 27M tokens on four videos whose machine render time was 5–6 minutes each, because every retry pulled the render plan, Remotion's output and the QC report back into the operator's context (Clooney: 42 minutes, 9.2M cache reads; the first Wren Hollow operator died on its session limit). The ceiling used to be a sentence in this file. Now it is a number and a script:

- **One render = one ledger entry.** `render_video.py` calls `attempts.py begin` on the video's ledger (`<batch>/work/<slug>/attempts.json`) before Remotion runs; `qc_render.py` calls `end` with the verdict. You do not call either by hand on the normal path — the wrappers do, so the count cannot be skipped. A render that fails ends its own entry as `render_failed` — or `render_broken` when no frame was drawn (CF-0305, below). Every render gets its own number `n` and its own log; what it *spends* is its `kind`.
- **Two ceilings (CF-0415, the user's decision of 2026-09-28).** A render whose **only** change is the degradation QC itself suggested is `kind: qc_degrade` and spends `video_editor.max_qc_degrades_per_video` (default 3). Everything else is `kind: attempt` and spends `video_editor.max_attempts_per_video` (default 3) — both read from `channels/<channel>.json`, the default when the key is absent. You do not declare the kind; `render_video.py` works it out (`attempts.classify()`), and all three must hold for a `qc_degrade`:
  1. the previous render ended `qc_failed` with a `qc_hint` — what QC itself names. Today only the `frozen` gate names one: `<idx>:still` for every index in `frozen_clip_blocks` (the summary prints it as `qc hint: --degrade-block <idx>:still:...`). A `subject` failure is a re-cut, `bed`/`caption`/… are fixes — none of them is a hint;
  2. the plan's `degraded_blocks` add at least one of those tags, only those, and take none back (`--degrade-block 3:typographic` against a `3:still` hint is not the hint);
  3. the plan's `build_inputs.digest` equals the previous render's — `build_render_plan.py` fingerprints every input but `--degrade-block` (the storyboard, words, voice and script by content, every other flag by value). **A re-resolve, a re-cut or a changed flag is a new digest, and the render is an attempt however many `--degrade-block` flags ride along.** So: after a `frozen` failure, rebuild the plan from the *same* storyboard with the *same* flags plus the hinted `--degrade-block`s — that is the cheap path; fold nothing else into that rebuild.
  The reason is read off the ledger and the plan (`first`, `qc_degrade:<idx:to>`, `degraded:<idx:to>` for a degradation QC did not name, `recut:<block=shot>`, `qc_failed:<gate>`, `render_failed`, `render_broken`, `operator`); `render_video.py --reason` overrides the text (`assets_rejected` when a rebuild follows a refused plan), never the kind.
- **At a cap, `render_video.py` exits 3 without rendering** and prints one line:
  `NEEDS-YOU <slug>: attempt cap <N> reached - last failure: <result> (attempt <n>): <detail>`
  or, for a fourth QC degrade, `NEEDS-YOU <slug>: qc degrade cap <N> reached - ...`. A video whose attempts are used up still takes the degradation QC named while the degrade cap has room — the failure is a stop only when nothing is left to begin, and then it prints the same line right away. **That line is the end of the video for this run.** Copy it into the report, move on to the next video; there is no "one more try", not with `--verbose`, not with a different candidate, not by deleting the ledger. `needs_you` is written into the ledger and `write_batch_metadata.py` carries it into `05-video-editor.json` (`attempts[]` — every render, with `kind`, `counted`, `qc_hint`, and on a render failure `error`/`error_signature`/`frames_rendered` — `attempt_cap`, `attempts_used`, `qc_degrade_cap`, `qc_degrades_used`, `attempts_exhausted`, `needs_you`), so the batch record says which videos are waiting for a human and which ceiling stopped them.
- **A render the tool broke before the first frame is not an attempt (CF-0305, the user's decision of 2026-09-21).** When Remotion dies before it prints `Rendered N/M` with N ≥ 1 (bundling, composition, the first asset fetch), or the mix fails before Remotion runs, `render_video.py` ends the entry as `render_broken` with `counted: false`, the error line (`error`) and its normalised form (`error_signature` — times, tmp/job paths, pids, ports, hex ids taken out); the summary's first line is `render BROKEN ... (before the first frame - not counted against the cap; ...)`. It spends no attempt: retry once if you have a reason to think it was transient. **The second `render_broken` in a row with the same signature is a stop**: `NEEDS-YOU <slug>: render_broken - the same failure twice in a row before the first frame, not counted against the cap: render_broken (render <n>, not counted): remotion exit <rc>: <error line>` — copy it into the report and move on; the tool is broken and a third run cannot change that. The stop names the error, not a cap, and it is lifted by the fix, not by `--cap`: a later `render_video.py` on the same batch begins normally once the video-editor checkout's code (HEAD or its uncommitted diff of `scripts/`/`render/src`) or the plan's `build_inputs` digest differs from the broken renders' (the old stop moves to `lifted_needs_you[]` in the ledger). A failure **after** frames were drawn is `render_failed` and counts as before (summary: `render FAILED ... (after <k> frame(s); ...)`), and so does every `qc_failed`. An entry without `counted` (every ledger written before CF-0305) counts.
- **The same render failure twice in a row is a stop too, and both renders count (CF-0518, the user's decision of 2026-10-04).** A `render_failed` right after a render that failed with the same `error_signature` (frame numbers and the batch's work dir are taken out of it as well - 0358Z died at frame 512 on one unstaged clip after 507, 508 and 509 frames drawn) means the video runs into the same asset: `NEEDS-YOU <slug>: render_stuck_on_asset - the same render failure twice in a row (after <a> and <b> frame(s)), the video runs into the same asset (<path>): render_failed (attempt <n>): remotion exit <rc>: <error line>`, with attempts left or not - copy it into the report and move on. Both renders keep `counted: true` (the stop does not give attempts back); the ledger's `needs_you` carries `error`, `error_signature`, `renders`, `frames_rendered` (both), `asset` (the path the error line names, or null), `toolchain`, `build_inputs`. A `render_broken` followed or preceded by a `render_failed` with the same signature is this stop as well; two `render_broken` stay the stop above. The pair is the two renders right in a row - a `qc_failed` or a `qc_degrade` between them breaks it - and no closeness of the frame counts is asked. It is lifted like `render_broken`: by a change to the code or to the plan (`build_inputs` - re-stage or re-resolve the asset and rebuild the plan), never by `--cap`.
- **Logs live on disk, not in your context.** By default (`--summary`, alias `--quiet`) `render_video.py`, `build_soundtrack.py` and `qc_render.py` append their full output to `<batch>/logs/<slug>-attempt-<n>.log` (one header per step) and print at most 20 lines: the verdict, the return code, the attempt number, every failed block with its motion score, the path to the log. **Read the summary only.** Open the log file only when the summary names a failed block or a return code you cannot act on, and then only the part about that block (`grep -n` the block label, not `cat`). `--verbose` restores the old firehose for a human at a terminal — never use it inside the loop. `qc_render.py --json` still prints the whole result, for `write_batch_metadata.py`; `frozen_clip_blocks` is in the summary too, so you do not need `--json` to decide what to degrade.

### Run accounting (CF-0107)

Every batch keeps `RUN_EVENTS.jsonl` in its directory, and `RUN_LOG.txt` beside it is **generated** from those events (`runlog render`; every marker command re-renders it) - never write or edit `RUN_LOG.txt` by hand. The batch directory is `~/shorts-content-factory/pipeline/<channel>/<batch-id>/` - the one `write_batch_metadata.py` takes as `<batch_dir>`, whose `work/<slug>/` holds every video's plan and CF-0098 ledger. The batch is already open by the time you are invoked (the orchestrator wrote `batch-start`; you never do, and you never write `batch-done` either) - a rebuild through the executor too (`batch_control.py rebuild()` opened it, CF-0668); only a rebuild run by hand is opened by its operator: see **Rebuild (Пересборка)** below. The first act of every invocation, before any script runs:

```bash
RUNLOG=~/shorts-content-factory/scripts/runlog
export RUNLOG_BATCH=~/shorts-content-factory/pipeline/<channel>/<batch-id>
"$RUNLOG" stage-start video-editor --batch "$RUNLOG_BATCH"
```

**`<channel>` in that path is the channel's current id (CF-0197).** A renamed channel keeps its old batch directories under the old name - `pipeline/legacy-film/` is still there and still correct - so new batches go under the new name and the history stays where it was written. The whole convention (who writes where, who reads both, how a former id resolves) is written once in the root `README.md`, section **"Renamed channels and their batch directories"**. Read it there; do not restate it here, and do not "fix" a path that points at the old directory.

**Every path of this stage is in the batch, written absolute** (CF-0246): `"$RUNLOG_BATCH"/work/<slug>/...` and `"$RUNLOG_BATCH"/videos/<slug>.mp4`. The `work/<slug>/` and `videos/<slug>.mp4` written below are shorthand for those - no script resolves them against the batch, they resolve against your current directory, and on `2026-09-15T1034Z` that was the agent checkout: the batch got no `videos/` and three mp4 landed in `agents/video-editor/videos/`. `write_batch_metadata.py` now refuses that call (exit 2, `OUTPUT OUTSIDE THE BATCH`); move the files into the batch and call it again with batch paths.

Keep `RUNLOG_BATCH` exported for the whole invocation, every video of it: every script below writes its own `start`/`done` (or `failed` - a non-zero exit, with the code: `render_video.py`'s exit 3 at the cap, `build_render_plan.py`'s exit 2 on rejected assets, `narration_length.py`'s exit 2 over the ceiling and `qc_asset.py`'s exit 1 on a refused asset are `failed` events with `error: SystemExit: <code>`, verdicts rather than crashes) event under it as stage `video-editor`, with `video` = the slug read off `work/<slug>/` in the path the script works on and `attempt` = the number in the ledger (`work/<slug>/attempts.json`). **Every attempt is its own event chain, numbered by the ledger**: `render_video.py`'s event carries the number `attempts.py begin` hands it, `qc_render.py`'s the one it ends, and a rebuild's `resolve` / `plan` / `soundtrack` carry the ledger's latest number - the attempt they repair (null before the first render). No script counts attempts itself, so the events and `05-video-editor.json` can never disagree about the number. The slug and the number sit on the `done`/`failed` line (they are learned after the `start` line is written). Without the variable a script only warns on stderr (`[runlog] no batch dir ...`) and records nothing - its output is unchanged. The last act of every invocation, after your report in chat:

```bash
"$RUNLOG" stage-done video-editor --batch "$RUNLOG_BATCH" --note "<N> videos rendered, <K> needs-you, <A> attempts"
```

`N` is the videos whose final `qc_render.py` passed, `K` the ones that ended on a `NEEDS-YOU` line, `A` the sum of `attempts` over the ledgers (`attempts.py show <batch> <slug>` prints each video's). An invocation that stops early - an over-ceiling narration handed back to Content Researcher, a lost source - still ends with `stage-done`, with a `--note` saying why; the failure itself is already in `RUN_EVENTS.jsonl` as a `failed` script or child event with its error line.

### Rebuild (Пересборка) - under the executor, or by hand (CF-0668, CF-0669; CF-0398, CF-0401, CF-0416)

A rebuild (`pipeline/rebuilds/<ts>`) remakes chosen videos of a finished batch and yields a video that can be published, so it runs only on `main` of every factory repo and the code does not move under it (the user's rule of 2026-09-26, root `docs/running-a-batch.md`, **"A batch runs on `main` only, and the code under it does not move"**). It never gets a `batch-done` (CF-0339), and it is closed by its own `05-video-editor.json` (CF-0416): `write_batch_metadata.py <rebuild dir> --video <script_id> work/<slug>/plan.json videos/<slug>.mp4` per video, exactly step 9 below - the channel comes off the copied `03`/`01` (never `rebuilds`; `--channel` wins) and the top-level `rebuild_of` `{channel, batch_id, path, read_from}` names the source batch. Nobody writes or edits a 05 by hand for the frame judge. There are two ways in; the prompt tells you which.

**Under the executor (CF-0668) - the prompt carries a `rebuild:` argument and the line `This batch is a rebuild (CF-0668, mode <mode>) of <channel>/<batch>: only the videos ...`.** `shared/batch_control.py rebuild()` made the directory, copied the records, **opened the batch itself** (`runlog batch-start --note "rebuild <mode> of ..."`) and resumed `run_executor.py` on it; the stages before yours are `skipped` as copied. So:

- **Do not open the batch** - no `batch-start`, no `--anyway`, no `batch-done`. Your stage markers are yours as on any batch (`stage-start`/`stage-done video-editor`, Run accounting above): `RUNLOG_BATCH` is the batch directory the prompt names.
- **Mode `reedit`** (`from: video-editor`): `03`/`04` hold only the chosen videos, and `work/<slug>/` is the source's, copied **without** its attempts ledger (`attempts.json`) and judge frames - the voice, the words, the anchors and the storyboard are the source's, so steps 0b-3 and the speech and anchor half of step 4 are not run again, and the attempt cap starts at attempt 1. Per video, in this order:
  1. **Re-resolve before the plan, with the exclusions.** `exclude_candidates` is `none` or `<slug>: --exclude-candidate <B> [--exclude-candidate <B>=<SOURCE>:<SHOT> ...]; <slug>: ...` - the user's rejected pictures, numbered as the source's storyboard numbers its blocks (checked against it by `rebuild_check`). Run the storyboard's resolve command with this batch's paths plus those flags and `--exclude-by user` - the re-cut lever above (CF-0367), same OUTPUT `"$RUNLOG_BATCH"/work/<slug>/storyboard.json`. The command is the copied storyboard's `resolve_call.argv` with every path of the source batch (`run-state.json` → `rebuild.of.path`, relative to the factory root; the `of <channel>/<batch>` of the prompt line) rewritten to `"$RUNLOG_BATCH"`, or, on a storyboard older than CF-0648 with no `resolve_call`, step 4's `resolve_anchors.py` with this batch's paths. **Never run a copied `resolve_call` as written** - its OUTPUT is the source batch's storyboard. Re-resolve a video with no exclusions too: that writes this batch's own `resolve_call`, which the plan's held-screen re-cut needs (below). Copy the `RECUT:` lines into the report. **A block with no other candidate** (`RECUT NOT APPLIED`, or the anchor's `rejected_candidates` / `length_supply` show nothing left) is said in the report as such - `<slug> block <B>: no replacement, <why>` - never forced with `--score-floor`/`--min-score` or a hand-picked shot.
  2. **Read `notes` before you choose.** `notes` is `none` or the user's words (a general text, then `<slug>: <note>` per video). A note that names a picture the exclusions do not already cover is a re-cut of that block like the ones above (a block a human rejected for its picture, CF-0367) - say in the report which note you turned into which `--exclude-candidate`. A note this stage cannot answer - the text, an anchor (the writer's, CF-0140), the pool - goes into the report as unanswered; do not reword or re-anchor by hand.
  3. **Then steps 6-9 as usual**: the plan (`build_render_plan.py`; its held-screen re-cut, CF-0648, runs inside it as on any batch - off the storyboard's fresh `resolve_call`; one still copied from the source says `held_recut.outcome: resolve_call_elsewhere` on the plan and runs nothing, which means step 1 was skipped), the soundtrack, the render, QC and the degradation loop, `write_batch_metadata.py` with `rebuild_of` from the copied `03`.
- **Mode `rewrite`** (`from: content-researcher`): the scripts in `03` are new and `work/` is empty, so the whole Procedure runs as on a batch; `notes` are read the same way (step 2 above), and `write_batch_metadata.py` takes `rebuild_of` off the new `03` (it carries the source `batch_id` of the copied `01`).

**By hand - an operator re-running this stage's scripts on a copied batch.** From the factory root: open it with `scripts/runlog batch-start --batch pipeline/rebuilds/<ts> --note "<why>"` (refused, exit 2, unless every repo is on a clean `main`; `--anyway "<reason>"` only when the user explicitly asked to see uncommitted code, and say so in the report); wrap the editor's scripts in `scripts/runlog stage-start`/`stage-done video-editor --batch pipeline/rebuilds/<ts>` with `RUNLOG_BATCH` exported to the same directory; re-cut, plan, render and QC as in `reedit` above; close it with `write_batch_metadata.py` as above, never `batch-done`. The rebuild's `REBUILD.md` note records the `batch-start` (and any `--anyway` reason).

What the scripts write, so you can read `RUN_EVENTS.jsonl` (or `runlog tail`) back:

| script | `step` | `video` / `attempt` read off | `child` events (`tool`) |
|---|---|---|---|
| `script_anchors.py` | `anchors` | the output (`--out`: the report before TTS, the anchors file after alignment) | `match_anchors.py` in `preflight` (the same CLIP call the resolve makes; none in `spec`) |
| `synthesize_voiceover.py` | `tts` | the output `voice.wav` | `kokoro` twice: the model load, the synthesis (`params`: voice, speed, chars). Also writes `work/<slug>/narration.txt` — the text it read, verbatim (CF-0261) |
| `narration_length.py` | `narration` | `voice.wav` | none; exit 2 over the ceiling is a `failed` event |
| `align_words.py` | `align` | the output `words.json` | `whisper.cpp` |
| `resolve_anchors.py` | `resolve` | the output storyboard | `match_anchors.py` (the Footage Indexer's matcher), `ffmpeg` (usability probe frames, the hold frame), `qc_asset.py`, `prepare_clip.py` |
| `prepare_clip.py` | `prepare-clip` | the output clip (`work/<slug>/clips/`) | `ffprobe` (frame size), `ffmpeg` (letterbox cropdetect, the caption-probe cut, the cut itself), `detect_text_band.py` |
| `detect_text_band.py` | `text-band` | the source | `ffmpeg` (sampled frames), `vision` (`text_regions` per frame) |
| `qc_asset.py` | `qc-asset` | the image | `vision` (`text_regions`, `find_roi`); exit 1 = the asset was refused, a `failed` event |
| `smart_crop.py` | `smart-crop` | the image | `vision` (`find_roi`: faces, then saliency; `text_regions`) |
| `build_render_plan.py` | `plan` | the output plan | `ffmpeg` (one probe frame per clip), `qc_asset.py --with-framing` per asset (a nested `script` event of its own; its verdict's `framing` is the asset's `smart_crop.analyse()`, so `smart_crop.py` runs only for a verdict without it - CF-0649); with `--script` the proof, meme and sound layers run in-process, so their `chrome`, `clip`, `ffmpeg`, `ffprobe` children land under this event |
| `proof_layer.py` / `meme_layer.py` / `sound_layer.py` | `proof` / `meme` / `sound` | the plan | only when run standalone; `chrome` (via `capture_page`), `clip` (the text embedding in the Footage Indexer's venv), `ffmpeg` (gif -> mp4), `ffprobe` (streams) |
| `capture_page.py` | `capture` | the output file | `chrome` (`capture_page.mjs` over CDP; the CF-0071 timeout is a `failed` child with `rc: timeout`) |
| `capture_tool.py` | `capture` | none (it records into the pool, not a video's work dir) | `chrome` (`capture_tool.mjs`, the screencast), `ffmpeg` (the frames into the mp4) |
| `render_quote.py` | `quote` | the output card | none (Pillow) |
| `build_soundtrack.py` | `soundtrack` | the plan; the ledger's latest attempt | `ffmpeg` (one decode per sound file, the mix) |
| `render_video.py` | `render` | the plan; **the attempt `begin()` hands out** | `remotion` (`npx remotion render` - Chrome and ffmpeg inside it - through `quiet.run_logged`, the whole render one child; none at all when exit 3 refuses at the cap) |
| `qc_render.py` | `qc` | the plan; the attempt it ends | `ffprobe` (streams), `ffmpeg` (silence, peak and RMS passes, the frames of the luma / motion / caption probes) |
| `write_batch_metadata.py` | `metadata` | the plan when there is one `--video`, else null (the batch's event) | `qc_render.py` per video (also a nested `script` event chained under this one) |
| `attempts.py` | `attempts` | the slug argument; `n` after `begin` / `end` / `show` | none - it marks the attempt boundary itself |

| `tool` | what it is | where it is called |
|---|---|---|
| `ffmpeg` | frame grabs, cuts, probes, the mix | `common.ffmpeg()` / `grab_frame()`; `resolve_anchors.py`, `prepare_clip.py`, `build_render_plan.probe_frame()`, `build_soundtrack.py` (`read_mono`, the mix), `qc_render.py` (every measurement), `detect_text_band.py`, `meme_layer.py` (gif -> mp4) |
| `ffprobe` | durations, sizes, streams | `common.media_duration()` / `image_size()`; `prepare_clip.py`, `qc_render.probe()`, `meme_layer.has_audio_track()`, `sound_layer.stream_kinds()` |
| `kokoro` | TTS, in-process | `synthesize_voiceover.py` (load, synth) |
| `whisper.cpp` | word timings | `align_words.py` (`whisper-cli`) |
| `remotion` | the render | `render_video.py` -> `quiet.run_logged(tool="remotion")` |
| `chrome` | the proof capture; the own-capture recording (CF-0567) | `capture_page.py` (`capture_page.mjs`, Remotion's chrome-headless-shell); `capture_tool.py` (`capture_tool.mjs`) |
| `vision` | macOS Vision, in-process | `smart_crop.find_roi()` (faces / saliency), `detect_text_band.text_regions()` (the text scan), `vision_client._request()` (every request the warm worker answers, `params.via: worker`); `params.probe` names the probe. The worker itself is never an event: it is spawned without the batch and outlives every script - the caller's request child is its time |
| `clip` | the CLIP text embedding | `meme_layer.py`, run in the Footage Indexer's venv |
| `qc_asset.py`, `smart_crop.py`, `prepare_clip.py`, `detect_text_band.py`, `match_anchors.py`, `qc_render.py` | sibling scripts run as subprocesses | `common.run_script()` and the direct calls in `resolve_anchors.py`, `prepare_clip.py`, `build_render_plan.py`, `write_batch_metadata.py`: the child is the caller's wall time on it, the nested `script` event (parent = the caller's id, via `RUNLOG_PARENT`) is the script's own, with its own children |

Every child carries `parent` (the script event's id), the same `stage`/`step`/`video`/`attempt` as its script, `argv` and `rc`; `rc != 0` (or `timeout`) is a `failed` child. Render time is the `remotion` children, the gate's time is `vision` + `qc_asset.py` / `smart_crop.py`, the voice is `kokoro` + `whisper.cpp` - that split, per attempt, is what the events exist for.

### Mode `new-only` - the reserve round after the frame judge (CF-0802)

The run plan's `video-editor-judge` stage invokes this skill with `mode: new-only`. It runs after the frame judge refused a video and the reserve round brought a substitute topic in: the Researcher wrote its script into `03`, compliance judged only it into `04`, and this stage renders **only the scripts nobody has rendered or refused yet**. Every entry `05-video-editor.json` already holds - a video in `videos[]` or a refusal in `refusals[]` - is the first pass's and is **final**: the frame judge has judged those videos, and a second render under the same id would hand it a different video it already passed or refused. Without `mode: new-only` nothing below applies and the stage is the full Procedure as always.

1. **Open the stage** as always (Procedure step 0: `export RUNLOG_BATCH=...`, `"$RUNLOG" stage-start video-editor --batch "$RUNLOG_BATCH"`).
2. **List what is pending** - deterministic, no judgement of yours:
   `.venv/bin/python scripts/pending_scripts.py <batch>`
   prints, one per line in `03`'s order, the `script_id`s of `03` whose `04` row clears them (the funnel's rule: `clear`/`caution`, or `review` with a `publication_hold`; never a `contribution_check` `block`; never a script `04` has no row for) and that `05` names in neither `videos[]` nor `refusals[]`. The count goes to stderr. **Exit 2** means `05` is not there (no first pass) or a file cannot be read: stop, put the line in the report, and close the stage with `"$RUNLOG" stage-done video-editor --batch "$RUNLOG_BATCH" --note "new-only refused: <the PENDING: ERROR line>"` - do not fall back to the full mode on your own. The `scripts` argument of the invocation says the same thing in words; the listing is what you act on.
3. **Nothing listed** - close at once: `"$RUNLOG" stage-done video-editor --batch "$RUNLOG_BATCH" --note "0 new videos (new-only, nothing pending)"`. No script runs, `05` is not written.
4. **Otherwise render only the listed scripts**, each through the usual per-script steps of the Procedure (0b plan-check reuse, 1-8: voice, anchors, plan, the score stop, render, QC and its degrade loop, the CF-0794 rule that a video the plan or the score refused is not rendered and not QC'd), and record each one as it finishes with step 9's call **plus `--new-only`**:
   `write_batch_metadata.py <batch> --new-only --video <script_id> <batch>/work/<slug>/plan.json <batch>/videos/<slug>.mp4`, or `write_batch_metadata.py <batch> --new-only` for a script refused before the render (its sidecar is found under `work/<slug>/` as always).
   The merge is CF-0030's, by `script_id`. With `--new-only` the call **refuses** (exit 2, nothing written) a `--video` or `--refusal` for a `script_id` that `05` already holds, refuses when `05` does not exist or with `--replace-all`, and does not re-read the refusal sidecars of the first pass's scripts; `merge_log[-1].mode` says `new-only`. An exit 2 from it is the guard doing its job: you named a script that is not yours in this mode - fix the call, never drop `--new-only` to get past it.
5. **Never touch what `05` already holds**: no re-render, no rebuild, no re-score, no `--degrade-block` on a first-pass video, no `qc_render.py` on its mp4, no `write_batch_metadata.py` without `--new-only` in this mode. A first-pass video that looks wrong to you is a line in the report, not work for this stage.
6. **Close the stage** with Procedure step 10's `stage-done`, its note saying the mode: `--note "<N> videos rendered, <R> refused before the render, <K> needs-you, <A> attempts (new-only, <P> pending)"`, where `P` is the count step 2 listed.

### The repair after the frame judge - a machine stage, not this skill (CF-0881)

The run plan's stage `judge-repair-editor` (root `shared/judge_repair.py run-editor`) calls `scripts/repair_blocks.py <batch> --request <batch>/work/repair-requests.json --result <batch>/work/repair-results.json` itself; no operator runs it. Per video the judge refused for a defect in one or two blocks it excludes the refused shot on that block (`resolve_anchors.py --exclude-candidate <block>=<shot> --exclude-by judge_repair`, the storyboard's own `resolve_call` - the topic's indexed pool only, no YouTube search) or takes the refused meme off the plan, builds the plan by the plan check's own command, renders (`--reason judge_repair`, an attempt of the ledger), QCs, re-packs `work/<slug>/frame-judge/` and rewrites the video's `05` row in place with `write_batch_metadata.py --repair` (refuses anything but a row `videos[]` already holds; the row carries `repair`). Snapshot in `work/<slug>/repair/before/` + `before.mp4`; any outcome short of `rendered` (`no_replacement`, `render_failed`, `qc_failed`, `failed`) puts the batch back as the judge refused it. One pass; the root's judge then looks at the changed blocks only. If you meet `work/<slug>/repair/` in a batch you are building, it is that stage's record - leave it.

### Tools

All in `scripts/`, run via `.venv/bin/python`:

| script | what it does |
|---|---|
| `script_anchors.py` | CF-0140: the script's `visual_anchors[]` — `preflight` asks the pool before TTS (`anchor_coverage.py`), `spec` turns each `beat_text` into the word index `resolve_anchors.py` takes. Writes no anchor of its own |
| `anchor_coverage.py` | CF-0140: can the pool picture these phrases — `covered`/`weak`/`absent` per anchor plus the CF-0121 contention, judged by the resolver's own functions. Also called from the Content Researcher's gate |
| `synthesize_voiceover.py` | Kokoro TTS in the **channel's** voice — `--channel <id>` reads `voice_profile` out of `channels/<id>.json` (CF-0188); `am_puck` @ 0.95 is what a channel carrying no profile object reads in |
| `narration_length.py` | gate `voice.wav` + end card against the channel's 55s target / 60s ceiling (CF-0087) |
| `measure_speaking_rate.py` | CF-0188/CF-0261: re-measure `narration_budget.words_per_second` on a real batch — `measure_speaking_rate.py <batch-dir> --channel <id> [--json <out>]`. Reads each video's `work/<slug>/narration.txt`, falling back to the batch's `03-content-researcher.json` through `meme_layer.narration_text()` for batches made before that file was recorded. Run it when the voice, the speed, **or the layout of the narration** changes |
| `align_words.py` | whisper-cpp over Kokoro's own output → real word timings |
| `smart_crop.py` | macOS Vision: faces, then attention saliency → where the subject is |
| `qc_asset.py` | gate on one asset **before** montage |
| `detect_text_band.py` | Vision text recognition → where a source's burned-in captions sit |
| `fetch_footage.py` | yt-dlp into the shared cache, recording provenance |
| `prepare_clip.py` | cut a segment, auto-crop burned-in captions |
| `build_render_plan.py` | storyboard + timings + assets → the render plan |
| `plan_check.py` | CF-0411: `check` - steps 3-6 of the procedure (TTS → length → align → spec → resolve → plan, **no render**) for one script, run by the Content Researcher; verdict `work/<slug>/plan_check.json`, voice reused across anchor-only rounds. `reuse` - this stage's question before step 1: render the checked plan (0), skip a script refused before the render (2), build as before (3 none / 4 stale) |
| `batch_layout.py` | CF-0246: the stage's outputs stay in the batch - `python3 scripts/batch_layout.py <batch>` after the stage: no mp4 in any checkout's `videos/`, every `05` record's mp4 under `<batch>/videos/`, no unrecorded mp4 (one superseded by a refusal is fine); exit 0 / 1. `write_batch_metadata.py` refuses a `--video` whose plan or mp4 sits in a checkout's `work/` or `videos/` (exit 2, `OUTPUT OUTSIDE THE BATCH`) and prints the same findings as `WARNING: LAYOUT:` lines |
| `repair_blocks.py` | CF-0881: the repair after the frame judge (above) - the root's machine stage calls it, one pass; `write_batch_metadata.py --repair` is its record |
| `pending_scripts.py` | CF-0902: `--first-pass` - the cleared scripts of `03` for the full mode, no `05` needed (stderr: the ones held back and why); `render_refusal()` is `render_video.py`'s `NOT CLEARED` stop (exit 5). CF-0802: `pending_scripts.py <batch>` - the cleared scripts of `04` (the funnel's rule) that `05` names in neither `videos[]` nor `refusals[]`, one per line in `03`'s order; nothing when none; exit 2 without a `05` (no first pass). The listing of **Mode `new-only`** above |
| `still_share.py` | CF-0418: the share of the running time in pictures (cards, posters, proof cards, whole-frame memes; a frame held from a video is not in it) and, apart, the soft share with frames held past 2x their shot and 2 s (`score.stretched_still_share`) - `measure()` for the plan builder's `still_share_over_half` gate and the `score.still_share` price; `python3 scripts/still_share.py work/<slug>/plan.json` prints one plan's |
| `proof_layer.py` | CF-0071: the script's `proofs[]` -> a proof insert on the block where the voice says the video's one fact (CF-0243), the `proof_requested`/`proof_delivered` pair, provenance, capture telemetry (run by `build_render_plan.py --script`, ahead of the meme layer) |
| `render_quote.py` | CF-0071 `rendered_quote`: the quotation typeset as our own 1080x1350 card (Pillow, theme colours) |
| `capture_page.py` + `capture_page.mjs` | CF-0071 `headless_browser`: pool/robots/rate/budget policy, then Remotion's chrome-headless-shell over CDP captures the article header |
| `capture_tool.py` + `capture_tool.mjs` | CF-0567: the own-capture recorder - a short screen recording of a public page (the tool a Tech story is about) as `own_capture-<id>.mp4` + `own_capture-<id>.own_capture.json`; see «Own capture and vendor quotes» below |
| `proof_quote_cap.py` | CF-0567: a vendor's official clip held to the channel's `proof_quotes` caps, and a demo held to its own recording; run by `build_render_plan.py` (gates `proof_quote_cap`, `demo_own_capture`) |
| `meme_layer.py` | CF-0067: the script's `reactions[]` → a meme overlay per placed block, the `meme_requested`/`meme_delivered` pair, provenance (run by `build_render_plan.py --script`) |
| `sound_layer.py` | CF-0068: the script's `sounds[]` → a `sound` record on the block holding each anchor, the `sound_requested`/`sound_delivered` pair, provenance (run by `build_render_plan.py --script`, mixed by `build_soundtrack.py`) |
| `underlay_layer.py` | CF-0127: the muted loop from `shared/inserts/loops/` into the frame's lower band — `plan["underlay"]` and `plan["secondary_source"]`, provenance (run by `build_render_plan.py --channel`, before the block loop because it changes `layout`) |
| `source_gate.py` | CF-0118: how many *independent* footage sources the blocks use (CF-0080 canonical ids - three uploads of one trailer count once), and the gate over it; run by `build_render_plan.py`, and standalone over any plan or storyboard for a measurement |
| `render_video.py` | stage assets into the call's own job dir `render/jobs/<slug>-<pid>-<hex>/` (CF-0340, `--public-dir`; parallel renders do not collide), run Remotion; begins the attempt (CF-0098: exit 3 + `NEEDS-YOU` at the cap), output to `<batch>/logs/<slug>-attempt-<n>.log` |
| `qc_render.py` | gate on the finished file; ends the attempt, ≤20-line summary (`--json` for the full result); `--footage-dir` defaults to `$FOOTAGE_DIR`, else the factory's `shared/footage` - the same rule as `build_render_plan.py` (CF-0523) |
| `attempts.py` | CF-0098: the attempt ledger — `begin`/`end`/`show <batch> <slug>`; the cap from `channels/<channel>.json#video_editor.max_attempts_per_video` (default 3) |
| `quiet.py` | CF-0098: the shared `--summary`/`--quiet`/`--verbose` behaviour of the three noisy wrappers; `run_logged()` is also where the `remotion` child event is written (CF-0107) and where the render's ceiling lives (CF-0135: `quiet.ceiling()` off `common.media_timeout()`, covering the reading of the child's pipe as well as the wait - a caller passes `media_seconds=`, never a number of its own) |
| `_runlog.py` | CF-0107: finds the root's `shared/runlog` library for every script (`FACTORY_ROOT`, else the ancestor walk; a silent stand-in when there is none) and reads the slug + the attempt the work belongs to off a path (`video_attempt()`). CF-0177: `video_script()` is the entry-point decorator every script of this stage wears - it resolves both off the command line before the `start` event is written, so the per-video events pair and the attempts per video can be counted |

### Anchoring - the picture arrives with the word

Blocks are no longer written by hand, and since CF-0140 **neither are the
anchors**. An anchor is a moment in the narration that has to be *seen*, with a
phrase describing the frame it wants — and it is written by the **Content
Researcher**, into `03-content-researcher.json` as `visual_anchors[]`
(`anchor_id`, `phrase`, `beat_text`, optional `side`), before TTS, so that its
own step 6 can hold every phrase against the footage pool while a refusal still
costs only a rewrite. Your part is mechanical: `script_anchors.py spec` copies
the phrase verbatim and turns `beat_text` into the word index the alignment
gives it (step 4). `resolve_anchors.py` then matches the phrases against the
footage index (see the Footage Indexer skill), cuts the shots, and derives the
blocks - each anchor holds the frame until the next takes over, landing ~0.35s
ahead of its word so the eye arrives before the ear confirms.

**Do not write, add or reword an anchor here.** The preflight answered for the
writer's exact wording, and CLIP is that literal: "a wooden cottage house by a
lake" scored 0.188 and "two people sitting on a deck overlooking a lake with
trees" scored 0.264, on the same shot. Rewording is how a checked script turns
back into an unchecked one, silently. The only edit this stage makes is a
*removal*, and the script makes it: an anchor whose words are not in the
voiceover.

Two rules decide whether an anchor can be answered at all. They are still this
skill's rules, but they are now addressed to the **writer** (and repeated in the
Content Researcher's SKILL.md, where the anchors are written):

- **Describe the frame, not the concept.** "a wooden cottage house by a lake"
  scored 0.188 and missed; "two people sitting on a deck overlooking a lake with
  trees" scored 0.264 and hit - on the same shot. No house is in frame.
- **Only anchor things that can be photographed.** "The rivalry was never the
  point" has no picture. Leave those stretches to whichever anchor is holding.

Anchors are soft: a weak best match is still used, but recorded in
`unresolved_anchors`. That report is the point - a gap is now a fact upstream
can act on, and the agreed answer is to go and fetch more footage (or fall back
to `typographic` for that stretch), never to quietly show something else.

`resolve_anchors.py` gates each candidate cut before accepting it and falls
through to the next-best match, because CLIP ranks by resemblance and knows
nothing about usability - it once returned a frame that was 98% black. Probe
offsets there match the plan builder's exactly: a shot that fades in reads as
usable at one instant and as a black frame at another.

A cached usability measurement (CF-0029) only ever lets a candidate skip that
gate's cost, never the gate. And it is believed only when the index says it was
measured by the code running now (CF-0048) - the whole footage pool was once
measured seven hours before `smart_crop.py` changed how animated frames are
framed, and the pre-filter spent a day discarding good title cards on numbers
nothing would produce any more. If a run prints `cached usability was measured
by ...`, that is the fallback working: those candidates are being cut and
checked for real. It costs time, and the pool is owed a deliberate
`footage-indexer/scripts/remeasure_usability.py`.

**A weak shot is ranked and priced, not refused (CF-0435, grill 2026-09-29 Q16/Q19).** The usability bundle - framing under 0.65, mean luma under 28, a delivery height under 720 - used to take a shot out at three places (the pre-cut filter on the cache, `usable()` on the cut clip, the plan's asset gate), and `example-film/2026-09-29T0929Z` reached the writer with 294 of its 699 shots. Now (`scripts/shot_score.py`):
- **The pre-cut filter refuses only the hard list**: a black frame (over `MAX_BLACK_CLIPS` 0.90, a lit card excused) or an empty one (no subject) on a *fresh* cache (`cached_hard_refusal()`, the sentence `pre-filtered by cached shot usability, not cut - black_frame (...)`), and `text_cut_by_crop` (CF-0275 - cut words on screen are foreign text, not a weak shot). **The root's shot rule (CF-0791)** is asked right after it: `shared/score/shot_guard.py` `shot_refusal()` - a panel of somebody else's text *inside* the window (cached `text_regions` >= 13, our own screen recording exempt by kind; the NASA-lecture slides of Science's voyager-1) and a source under 600 px on the short side - in the mode of `channels/<id>.json -> video_editor.shot_guard` (read once per run from `--channel`; `anchor_coverage.py --channel` the same). `fail` refuses with the root's own sentence (`text_panel_in_window: ...` / `under_resolution_floor: ...`) in `rejected_candidates`, and an anchor left with nothing is the usual unresolved anchor; `warn` (every channel until the user signs `fail`) keeps the shot and the storyboard's `shot_guard` record lists what was found on the shots shown; a root without the module refuses nothing and says so on stderr. `burned_text: true` stays `entity_guard`'s (CF-0351), a supplement shot without its entity too (CF-0348, somebody else's film). `cached_verdict()` is still the old bundle's opinion, kept for `remeasure_usability.py`'s report; the pre-filter no longer acts on it.
- **Every rung's pool is ranked** inside `fill()` (and the split opening): clean shots first, weak ones behind them by their usability score - the Footage Indexer's `shot_usability.of()` (`footage-indexer/scripts/shot_usability.py`), derived on the fly from what the shot stores; the old pool carries no `usability` field and is not re-measured for one. A stale cache ranks on the describer's flags alone. The order the caller gave (similarity, length) holds among equally usable shots. **With a clean candidate in the pool the clean one is cut**; a weak one is cut when nothing cleaner survives the gates.
- **`usable()` on the cut clip and the plan's asset gate sink a picture only on a hard failure** (subject, black over the clip ceiling, our caption crop through the faces CF-0092, a hung tool). A verdict failing only `coverage` / `luma` / `resolution` prints `QC SOFT ... shown and priced (CF-0435)` (the plan: `block N: weak picture, shown and priced`) and the clip goes on screen.
- **`on_topic: false` is a price, not an exclusion** (a shot that shows a supplement's entity is not off the topic).
- **The price.** The storyboard carries `usability: {task, soft: [rule...], penalty, score}` on each weak block and cut - the soft rules the real clip failed plus `off_topic_shot` from the flag; the cache only ranks, the clip is what is priced. `build_render_plan.py` adds what its own frame found and charges the plan stage one finding per rule per **distinct shot on screen**: `score.low_framing` −3 (cap −12), `score.low_brightness` −3 (cap −12), `score.low_resolution` −2 (cap −8), `score.off_topic_shot` −4 (cap −16). QC's `off_topic_shot` (a supplement shot without its entity) is not charged again for a block or shot the plan already charged it on (`score_log.plan_charged`).
- **The cache key did not move**: the classification lives in `shot_score.py`, outside `USABILITY_SOURCES` and outside what the probe reaches, and no threshold the probe reaches (`common.MIN_COVERAGE`, qc_asset's) changed - the pool's 5840 stamps (`edcd5ade6f17`) stay current, nothing is re-measured.
- **A wide view of a place is not low framing (CF-0352).** For a frame with no face Vision's subject box is a saliency box, and on a general view of a building or a landscape that box is most of the frame - the 9:16 window keeps 0.29-0.40 of it on every such shot (everyday-sorcery-2 v4, the white house: three pool shots at 0.33-0.40). When the **anchor names a place** (`scripts/wide_place.py` `is_place_anchor()`: a place word - house, street, skyline, forest, hills... - and no word for a person, creature or vehicle, no close-up, no capitalised name) and the **shot's box is not `faces`**, coverage is no rule: its own matches (not the topic-rung stand-ins) rank without `low_framing`, `usable()` takes the coverage failure off the cut clip's verdict (`QC WIDE PLACE ... (CF-0352)`), the record carries an **unpriced warning** `warn: [wide_place_shot]` with `wide_place: {coverage, roi_source}`, and `build_render_plan.py` does the same on its own probe for a marked picture (`block N: a wide view of a place ... (CF-0352)`) - no `score.low_framing`, no `blur_fill`, the picture goes out `cover` as the view it is. A face keeps the 0.65 floor whatever the anchor (a crop that cuts the hero is a defect). Nothing new is priced; a price for `wide_place_shot`, if one is ever wanted, is a proposal for signature (CF-0320).

**Presentation instead of a price - the penalty is what the viewer sees (CF-0436, grill 2026-09-29 Q26).** Part of a weak shot is fixed by how it is shown, and `build_render_plan.py` decides it on its own probe frame (`present_picture()`, the model in `shot_score.py`):
- **`blur_fill`** - a picture failing framing (`coverage` on the plan's frame, or `low_framing` in the resolver's `usability` record) is shown **whole across the width**, over a blurred (48 px), enlarged (x1.15), dimmed (x0.55) copy of the same frame. The asset (or sequence cut) goes out `fit: "contain"` with `presentation.blur_fill = {rect, blur_px, bg_scale, bg_dim}` - `rect` is the picture's box in output px, contained in the insert box (`meme_captions.insert_box`), so it ends above the caption band. No Ken Burns, no punch, no zoom. Nothing is cropped away, so `crop_cuts_subject` and the panel gate stand down for it (as for any contained picture).
- **`luma_lift`** - a picture failing `luma` (mean under 28) is multiplied up in brightness to 40, gain capped at x3 (`presentation.luma_lift = {gain, luma_before, luma_after}`; CSS `brightness()` in `AssetLayer.jsx`, the same arithmetic as `qc_asset.lifted_luma()` on the probe). A lift the capped gain cannot bring over 28 (or that nobody could measure) is not taken - the picture goes on screen as it is, priced.
- **The Editor's choice is by points**: a presentation is taken only when its price (`score.presentation_blur_fill` / `score.presentation_luma_lift` in `shared/gate-prices.json`, default 1 while the table has no row) is below the soft rule it removes (`score.low_framing` / `score.low_brightness`, 3). The resolver ranks the same way (`viewer_rank_key`): a fixable weak shot ranks at its presentation's price, so a sharper shot shown `blur_fill` can beat a duller one shown as it is. A shown picture pays **the presentation, not the rule** on the plan stage (`plan_findings(presented=...)`, `presentation_findings`); a presentation key the root's table does not carry yet is left out of the log (`_score.has_rule`). The plan's notes say `block N: shown blur_fill ... / luma_lift xG (mean luma A -> B) - priced ... instead of ... (CF-0436)`. Cards are never presented (already whole; their darkness is excused); split halves are not either.
- **QC sees the presentation.** The motion gate measures a `blur_fill` picture on its `rect` (`qc_render.picture_vf`), not on the top band - the band above it is the blurred ground, which barely moves, and a moving shot must not read as a still there. Every `luma_lift` picture is measured on the render (`lifted_blocks`: mean of three samples over its span, region = `rect` or the insert box); still under 28 there costs `score.low_brightness` on the QC stage (the plan charged the lift, not the darkness). The QC report carries `measured.lifted_blocks`.

**A blurry shot ranks behind a sharp one; a held frame is the shot's sharpest moment (CF-0452, kaijura-minus-zero refused 2026-09-30T1248Z as `blurry_footage`).** The measure is the Footage Indexer's (`footage-indexer/scripts/sharpness.py`, the shot's `sharpness_cached` with `measured_by: CF-0452/...`; another measure's record is not read), loaded by path like `shot_usability`; without it nothing changes and nothing is measured. In `scripts/shot_score.py`:
- **Rank, not price.** `rank()`'s key is `(hard, -usability score, blur_rank)`: a shot with `low_sharpness` (in the pool record's `warn` before the price is signed, `soft` after; or the verdict of its own fresh record) goes behind a sharp one **of the same score**, the sharper of two blurry ones first; among sharp shots the matcher's order stands. The score still comes first - a blurry clean shot beats an off-topic one.
- **The old pool is measured on the fly, top candidates only**: a shot of the first `SHARPNESS_PROBES_PER_RANK` (3) with no fresh record is measured (`sharpness.of_shot`, ~1-2 s) and the order is taken again; a shot is measured once per run (a failed measure counts as "not blurry" and is not retried), cards and missing sources never, and at most `SHARPNESS_PROBES_PER_RUN` (60) per run - worst case about 1-2 min on a video, typically far less (a probe per block's top, repeated shots memoised). Nothing is written back to the pool (it is transient, CF-0358).
- **A held frame** (`resolve_anchors.hold_frame(..., used=)`) is lifted at the shot's `best_at` when its record is fresh - from the clip when the moment is inside it, else from a 0.5 s snippet of the source cut with the clip's own caption crop; RUN_LOG says `HELD AT SHARPEST ...` and the block/cut carries `held_from {at, sharpness, from}`. A held block is judged again with `verdict(held=True)` (`held_usability`). Any failure falls back to the old middle frame.
- **The price is the root's.** Until `score.low_sharpness` is signed (`sharpness.mode()["signed"]`) the storyboard's `usability` record carries it in `warn` with the value and the floor, penalty 0; signed, it moves into `soft` at the table's price and `plan_findings()` charges it - only while `shared/gate-prices.json` has the row (`_score.has_rule`). This repo never writes that row (CF-0320).

**The resolver and the plan gate answer the same question the same way (CF-0296).** Coverage means "how much of the subject the *delivered* window keeps", so under `contain` - which is every `is_card` shot - it is reported and not judged: the whole frame is on screen and what a card has to keep is its text (`MIN_CARD_TEXT_KEPT`, step 6). Judging a contained card by a 9:16 `cover` window is what refused the whole Famine Trials video of `2026-09-19T0116Z` over two title cards the resolver had passed at 1.0. The third block of that refusal was CF-0004's animation classifier at its old 0.5 line, flipping between the resolver's probe frames (0.510-0.582, excused) and the planner's probe of the same moment (0.497, refused); `ANIMATION_CONFIDENCE` is 0.75 now, measured into the empty gap between live-action frames and the animated ones the excuse exists for. **If a shot is legitimately under the floor, it must fail at the resolver**, where CF-0290's ladder can still hand the block another candidate, a held frame or typography - a video is not lost whole for three blocks out of 23. (Since CF-0435 "under the floor" of coverage, luma or resolution is a price, not a failure, at both places - see above; the two still answer the same way.)

**One sample, one use (CF-0121).** `rhythm.MAX_SHOT_REUSE = 1`. A shot of a
source appears **once** in a video - the user's decision in `CF-0074`
(2026-09-05: no repeats by frame), which withdrew the licence in `CF-0026`'s
"2-3 times is the limit, and only when the script asks for it". A sample is the
`(source, shot)` pair, and it is the same sample however it reaches the screen:
as a clip, as a frame held out of that clip, as one side of a `side_by_side`
opening, or as the still a degradation cut from it.

**A frame that is not of the phrase is not a picture of it (CF-0290).** `resolve_anchors.py` screens every anchor's pool against the similarity floor (`--min-score`, 0.22) before it orders, budgets or cuts anything, so an under-floor candidate is never offered to a block in any rhythm. What that means in practice: a block whose only relevant shot is *shorter* than the block now takes that shot and holds its frame (`still`, `held_frame: true`) instead of reaching for a long shot of something else — similarity first, and "long enough first" surviving only as the order among the candidates that do depict the phrase. An anchor with nothing above the floor gets no picture and falls down the ladder below; it does not get a filler. The plan-builder's `unresolved_anchor` gate (step 6) is the backstop for a storyboard that carries one anyway, and `anchor_coverage.py`'s `weak` verdict (step 3) is the same rule one stage earlier and far cheaper — it now refuses the script instead of noting it, with or without `--strict`, because a weak anchor is an anchor the resolver will leave empty.

**CF-0433 (grill 2026-09-29, «делать из того, что дают»): the floor is a price, not a wall.** The paragraph above is the history. Today, when nothing at or above 0.22 fills a block, `resolve_anchors.py` takes the best candidate under the floor **by rank** (`below_floor_pool()`: score first, never length) through every regular gate, marks the block `below_floor: {phrase, score, min_score}`, and writes the "using it anyway" record with `best_used_score`. The plan prices it `score.low_similarity` (−3 a block, cap −15) in `plan["score"]`; topic-footage blocks (`topic_fill`) are not priced. There is no second, lower floor: `--score-floor` (CF-0088, unset in production) is the only outright refusal under the price. The number 0.22 has one home, `scripts/_score.py` → `SIMILARITY_FLOOR` (`resolve_anchors.DEFAULT_MIN_SCORE` and `build_render_plan.DEFAULT_SIMILARITY_FLOOR` are aliases).

**The score of the plan (CF-0433, model CF-0432).** Three rules that used to refuse the plan now cost points: `score.pace_below_floor` (pace under the pattern's floor, −2 per started block/min short, cap −12; the CF-0310/CF-0428 record rides as `rhythm.pace_below_floor` with `supply` / `fixable_by_anchors`), `score.hold_band_exceeded` (a block over a drawn hold band's top, −2 a block, cap −10; the CF-0270/CF-0303 record rides as `rhythm.hold_ceiling_break`; **CF-0859**: on a band that is not drawn - explainer's emergent 8.0 s top - the same rule is charged for a *held* picture past the top, one per block, at the plan stage before `late_score_stop()`: `rhythm.held_frame_over_band_findings()` via `build_render_plan.held_frame_band_gate()`, the held picture counted as the root's `held_frame_durations()` does (a `still` or `held_frame` cut by its `seconds`, a whole still / held-frame block by its length, a moving clip never); vanguards-doomsday 0840Z, a sharp still held 10.10 s, pays −2 on block 2. Never on a drawn band - the whole block is charged there already) and, on top of it, `score.tail_over_band_top` (CF-0490, signed 2026-10-02: the last block that still carries speech, held over a drawn hold band's top - −6 per second over, cap −66, one finding per video, `rhythm.tail_over_band_top_findings()`; everyday-sorcery-2 1034Z, a 13.52 s last block against `list`'s 2.5 s top, is 11.02 s over), `score.fact_anchor_early` (CF-0583, the user's signature 2026-10-06 on CF-0547's price: a visual anchor whose beat begins before `production_fact.beat_text` and runs into it puts the fact's picture on screen ahead of the fact's words - −2 per second of the lead over 2 s in this voice's `words.json`, cap −10, one finding per video, `scripts/fact_anchor.py`, read off `--script`/`--script-id`; never a refusal, the Researcher's step 6 repair line is what fixes it; WNL 0701Z, 6.02 s ahead, is −8), `score.low_similarity` (above). `build_render_plan.py` writes `plan["score"]` = `shared/score/score.py`'s block (`start, score, tier, threshold, passed, hard, log, by_rule, prices_status`) plus the `findings` it was taken from. The plan is refused on them only when `score < threshold` (N is the price table's `score.threshold` - 40 since 2026-10-01, CF-0462; it was 60 when this was written): `pattern_ceiling` when a pace, hold or block-band price is in the log (deficit `plan.pattern-ceiling.json` carries `score`), else `unresolved_anchor`. **A drawn block band's top is a price too since CF-0447** (the user, 2026-09-30; it was the last non-hard refusal of the plan): more blocks, or a faster rate, than the pattern allows is `score.block_band_exceeded`, −2 per block over the top, cap −10, one finding per video on the plan stage (`rhythm.block_band_findings()`; a rate band is counted in blocks over the top). primetime of `1126Z` (25 at `list` 12–24) pays −2, Famine Trials (42) the cap; the CF-0310 record rides as `rhythm.block_band_break` (with `supply` / `fixable_by_anchors`). Charged once: the Researcher's 6b price (`check_anchor_cadence`, `verdict: priced`) is its estimate before the TTS in `03` and is not in this video's score log — the plan prices the real count. A picture that freezes while the voice goes on is `score.frozen_block`, qc_render's to measure on the render. `plan_check.py` copies `plan["score"]` into its verdict as `score` and files an under-floor anchor as a `low_similarity` note, not a refusal.

**A block too short to read is a price, not a refusal (CF-0453).** The resolver's `anchor sits N s before the next one - too tight to read` (a block built under `MIN_ANCHOR_GAP_SECONDS` = 1.6 s; the record now carries `too_tight: {segment, t, seconds, min_gap}`) measures a rhythm segment's span — the pattern's hold cuts it (list/hold 1.1 s, staccato under 1.92 s), so no anchor edit moves it. `plan_check.py` files it as a `too_tight` note (it used to fall into `absent` and killed Primetime and AHS of `2026-09-30T1248Z` after three rounds of 6b). The plan prices it as `score.block_too_short` (`rhythm.block_too_short_findings()`, one per noted block) **once the root's price table carries the row** — until the user signs it (CF-0320) the plan writes a note with the proposed cost (1 a block, cap 5) and the score leaves it out. A refusal on it is only the score under N.

**The score log and the early stop (CF-0434, grill 2026-09-29 Q11/Q17/Q20/Q21/Q28).** Every stage of yours writes its **real** penalties (never a forecast) into one log per video, `work/<slug>/plan.score.json` (`scripts/score_log.py`), and checks what is left: `plan` - `build_render_plan.py` (pace, hold band, similarity, weak shots on screen CF-0435; stderr `SCORE after plan: <line>`); `render` - `render_video.py` after a good render (the file's length: `score.short_length` at 30-45 s, hard outside 30-60 s; the frame: hard `render_defect` when not 1080x1920); `qc` - `qc_render.py` (frozen block −31 ×2 in the hook, crop cutting the hero −61, panel partly cut −4 (cap −12) - but an inset panel kept under `score_log.PANEL_SLIVER` = 27.5 % in frame is the crop's −61, at or over it the panel's −4 (CF-0493, the user's 2026-10-03 signature), abstract background −8, repeated shot −16 ×2 in the hook, supplement shot without its entity `off_topic_shot` −4, no bed −3, face under a card 0 - the prices are `shared/gate-prices.json`'s as of 2026-10-04, the table wins over this list; burned-in foreign text, a long silence or clipping, a missing stream / wrong frame / picture adrift are the hard list). Recording a stage replaces it and forgets every later stage: a rebuilt plan starts the render and QC over, a QC-degrade render replaces the QC that judged the old one. **Under N (the table's threshold, 40 since CF-0462 of 2026-10-01; 60 before) after any stage the video is F and goes no further**: the stage writes `work/<slug>/plan.score.refusal.json` (gate and funnel code `score_below_threshold`, `supersedes_video`), `qc_render.py` exits **4** with a `SCORE F after qc: <line>` line and suggests no degradation, and `render_video.py` refuses to start a render (no attempt spent) for a plan whose log is already under N (exit 4, `SCORE F ... not rendered`). Do not rebuild or re-render such a video - put the line in the report and go to the next one. Under N at the plan stage is the plan refusal above (no plan, no render); the prices the plan's last gates add after that check (the still share, `score.thin_picture`, `score.held_moving_face`, the one-source line) are asked once more before the plan is written, and under N that is `SCORE UNDER THE THRESHOLD after the plan's last gates - plan not written`, exit 2, sidecar `work/<slug>/plan.score.refusal.json` (CF-0794: street-fighter, example-film 2026-10-18T0841Z, went F · 36,08 on exactly those, its plan was written anyway and the script vanished from 05). **A video the score refused before the render has no mp4 - never run `qc_render.py` on it** (on a missing file it now exits 2, or 4 with the `SCORE F` line when the log is under N, and records nothing); its refusal is already on disk and step 9 files it. **The hard list stays what it was**: a hard finding makes the tier F in the log, and the gate that found it refuses (or fails QC) exactly as before - the early stop is only `points < N`. **At or over N nothing changes** (Q14): the video is delivered to the user as before, its tier only shown. `write_batch_metadata.py` writes `videos[].score` (the whole log: `start, score, tier, threshold, passed, hard, log, by_rule, stages[{stage, findings, charged, score_after, tier_after}], stopped_at, findings`) and `videos[].score_line` - one line, `B · 74 — −9 похожесть (3 блока), −6 темп, −5 кадрирование (2 шота), −6 судья: 1 contradicts` - and prints `SCORE: <id> <line>`; put that line beside every video in your report. `python3 scripts/score_log.py work/<slug>/plan.json` prints the log of one video.

**A one-frame block is not one shot stretched (CF-0480, DoD 1.5.1 item 1; vanguards-doomsday 1313Z, refused for stop-frames: 7 of 7 blocks held off one source x2.4-x3.9).** `resolve_anchors.py`: when a one-frame block of an ordered rhythm (`max_shots` 1, not a swing) gets one shot that would stand for more than twice its length (and the block is over 2 s - `still_share`'s stretched line), or would hold a frame under `held_sharpness.FLOOR` (CF-0465's proposal), the block is cut into up to 3 shots of its own phrase (the matched pool, or its candidates under the floor - never the topic's footage): a `sequence`, boundary untouched, the last cut held for what is left, and the held cut is the sharpest one long enough for the tail. The shots the later one-frame blocks would take first are left to them. The block records `stretch_split` (`rung`, `why`, `got`); `short: true` when the pool had no second shot. `build_render_plan.py` (`pool_holds_gate`, after the held-soft gate): `plan.pool_holds`; when `short` blocks leave the video over 50 % stretched, a **warning** `pool_holds_video` (funnel `pool_too_thin`) naming the topic's supplement request - a new refusal, unsigned (CF-0320), so the plan is written. `still_share.held_sources` notes when one upload is behind every held frame (`score.held_one_source` - signed at 0 points since CF-0490, so the line is in the log and costs nothing). `--no-stretch-split` is a measurement switch (price the split on an old batch), never a deliverable run.

**A face held still out of a moving shot (CF-0481; vanguards-doomsday 1313Z, "стоп-кадры в движении").** `build_render_plan.py` (`held_motion_gate`, after the held-soft gate) reads every held frame against its source shot, on the fly and only for the plan (`held_motion.py`, never the pool): the tile-p95 motion of the shot +-0.5 s around the held moment (the held picture matched to its frame) and the largest Vision face on the picture. A frame with motion >= 5 and a face >= 0.02 of the picture is frozen motion; the plan records `held_motion` per held block / cut and `plan.held_motion` (`frozen_seconds`, `over_seconds` over `ALLOW` 12 s). Over it is `score.held_moving_face`, charged since the user signed the row (CF-0490): −16 per second over, cap −64 (before the signature it was a warning and a note, CF-0320; `held_motion.py --row` prints the row).

**A soft frame held still (CF-0465; kaijura-minus-zero 1248Z, "много смазанного материала").** `build_render_plan.py` (`held_soft_gate`, before the two gates above) reads the very picture the render holds - the `held_frame` still, a sequence's held cut, a clip degraded to its frame - with the indexer's focus measure (`held_sharpness.py`, no motion excuse), stamps `held_sharpness` on the block / cut while the PNG is there, and writes `plan["held_sharpness"]`. A held frame under `held_sharpness.FLOOR` = 0.53 is `score.held_soft_frame`, −5 per second on screen, cap −30 (signed), with a `HELD SOFT FRAME: <line>` on stderr and a note. `held_sharpness.py PLAN` prints the reading of any plan. `held_motion.py PLAN` prints the reading of any plan.

**Pictures over half of the running time - the hard list (CF-0418, the user 2026-09-28 / 2026-09-30).** `build_render_plan.py` measures, last of all (after the proof card is bound to its line and the end card is on), how much of the running time - the composition, end card included - is a **picture**: a still from an image file (ken burns over it too), the factory's `card` / `typographic` frame, a proof card (`insert.kind: proof`, over its own `start_s`-`end_s`), a meme picture over the whole frame (`insert.kind: meme`, placement `whole` or unset, not animated), an end card that is a logo and not the channel's clip. **A frame held from a video is not in this share** (`held_frame`, a clip degraded to `_degraded_still_<i>.png`), nor moving footage, nor an animated or cut-out meme, nor the `blur_fill` / `luma_lift` presentation of a video shot (CF-0436). One count, `scripts/still_share.py` (`measure()`; `python3 scripts/still_share.py work/<slug>/plan.json` prints it), feeds both rules of the model: over 25 % the zero-priced `score.still_share` per p.p. joins the plan stage of the score log; **over the channel's `video_editor.max_still_share` (0.5 when unset)** it is `score.hard.still_share_over_half` - tier F - and the plan is refused: `PICTURES OVER THE STILL SHARE - plan not written`, gate `still_share_over_half`, funnel code `score_below_threshold`, deficit `work/<slug>/plan.still-share.json` (share, threshold, blocks, spans; the soft share and the held frames beside them). The written plan carries the record as `plan["still_share"]`. **A stretched held frame is priced apart, never refused (the user, 2026-09-30, after kaijura v3 passed the hard share at 30.7 % on frames held off ~1 s shots for 3-8 s):** a `held_frame` block or held cut, or a clip degraded to its frame, is *stretched* when its shot stands on screen **more than 2x as long as the shot runs in its source (`end - cut_at` of its `shots.json` entry) and more than 2 s** (`STRETCH_MIN_RATIO`, `STRETCH_MIN_SECONDS`; a held tail of a sequence adds the cut of the same shot before it to its screen time, and only the tail counts). Pictures + stretched held frames make the **soft share** (`plan["still_share"]["stretched"]`: share, p.p. over, penalty, spans); over 50 % it costs `score.stretched_still_share`, **0.5 point per p.p. over 50 %, capped at 20** (the user's price after calibration, 2026-09-30; was 1 / cap 40), on the plan stage of the score log - the score decides what follows (CF-0434's early stop), this gate does not refuse on it. The finding is written only once the root's price table carries the rule (`_score.has_rule`). A 1.2x hold, a 1.5 s one, a held frame whose shot is not found (listed `unmeasured` under `held`) count nowhere. The plan builder stamps each held frame's source length onto its block / cut as `shot_seconds` (off `--index` and `$FOOTAGE_DIR`), so the plan answers after the pool is gone. The answer is upstream, in the writer's anchor loop (`plan_check.py` files it as kind `still_share`): anchors onto moving shots, or a meme request dropped - never a rebuild of the same storyboard.

*What changed is not the number.* A repeat used to be this stage's **sink**:
when the pool ran dry the shortage drained into a second and third showing, and
only a fourth surfaced in `unresolved_anchors`. There is no sink now. An anchor
whose best candidate is spent falls through to the next distinct sample and,
failing that, into `unresolved_anchors` and a typographic block (`CF-0085`). So
a thin pool now *shows* as missing pictures instead of hiding as familiar ones
— and when it does, the answer is a wider pool (`CF-0105`, Trend Hunter /
Footage Indexer), never a higher cap.

*Where it bites.* One `rhythm.ShotLedger` per video, and it is the only code
that reads the constant (a test greps for that, so a new selection path cannot
write its own `>= MAX_SHOT_REUSE`). Every path asks it: an ordinary block's
fill loop, `even`'s several cuts inside one anchor's stretch (`CF-0028`), both
sides of a `side_by_side` opening and each side's own run of cuts (`CF-0075`),
and whatever `CF-0120`'s multi-shot swing block turns out to be. The opening
resolves against a `fork()` - an opening that proves undeliverable, or a cut
trimmed off when the other side runs out first, was never on screen and does
not count as a use - and `main()` takes the delivered cuts on the real ledger,
which is what keeps the body off them. Two things that look like exceptions and
are not: a held frame is the same picture still on screen, so it is one use,
not two; and clip → still degradation lifts the frame from **that block's own**
asset and replaces it, so the sample goes from moving to motionless in the one
place it was already going to be. Degradation has no candidate pool and never
picks a sample; the rung below (`typographic`) is where a block with nothing of
its own left goes.

*What it costs, measured* (batch `2026-09-03T2037Z`, all four videos
re-resolved at cap 3 and at cap 1; `work/cf0121-measure/` held the
storyboards and `table.json` - archived by CF-0498 into `Archive:shorts-content-factory-cleanup-1.6/video-editor-code-2026-10-03.zip`):

| video | rhythm | `unresolved_anchors` | held-frame blocks | `typographic` blocks | distinct shots | showings |
|---|---|---|---|---|---|---|
| clooney-venice-lion | `even` | 9 → **10** | 0 → 0 | 0 → 0 | 9 → 11 | 14 → 11 |
| wren-hollow-christmas | `alternate` | 3 → 3 | 0 → **2** | 0 → 0 | 10 → 16 | 16 → 16 |
| ink-teaser-cards | `hold` | 0 → 0 | 11 → 11 | 0 → 0 | 12 → 14 | 14 → 14 |
| raygun-sneak-peek | `staccato` | 88 → **98** | 1 → 0 | 39 → **49** | 5 → 5 | 15 → **5** |

Repeat showings go to zero in all four. The cost lands exactly where the pool
is thin: `raygun`'s single 6-shot source under 54 staccato segments loses ten
more segments to the typographic rung and drops from 15 pictures to 5, while
`ink`'s 60-shot index absorbs the whole change with two fresh samples in place
of two repeats and no unresolved anchor at all. Read the columns as *deltas*,
not as absolutes: `CF-0055`'s caption-band gate refuses that batch's indexes
(stamped `06d254410f58` against today's `6b4256f1d3ac`), so the measurement
stubs the cutter and the asset gate — no clip was cut, and a candidate that
would have lost to its caption crop or to `usable()` did not lose here.

### Rhythm — the shape of the cut

The block plan is **built here**, not received. Content Researcher draws a
(pattern, rhythm) pair and its parameters and writes them into
`03-content-researcher.json` as an *order*; it does not send a block plan and
must not, because boundaries depend on which anchors resolved and are re-cut
again by per-block degradation. `scripts/rhythm.py` turns the order plus the
anchor times into segments; `resolve_anchors.py --order <file|json>` fills them.

| rhythm | what it does to the cut |
|---|---|
| `even` | one anchor, one block, boundaries where the narration put them, as many fill shots per anchor as it takes. The pre-pattern behaviour, unchanged — running with **no** `--order` is exactly this. |
| `hold` | fewer blocks than anchors; the passage the writing already dwells on longest becomes the held block, grown to `key_frame_hold_seconds`, and nothing else is allowed to be as long. |
| `staccato` | the only rhythm with **no 0.35s lead** — the picture changes *on* the item word. Each stretch is divided into equal pieces under the `key_frame_hold_seconds` ceiling. |
| `alternate` | A-B-A-B across the two sides of the comparison. The sides are the ones the **script** declared (CF-0050): `pattern.sides` in `03-content-researcher.json` names the axis, each anchor carries `side: "a"`/`"b"`, and one block is cut per crossing of the axis — the drawn block count yields to that. Two footage *sources* are the fallback when the script declared nothing, and then the block count is rounded to the pair as before. |

**Acceleration to the payoff** is a curve over block length applicable to any of
the four, not a fifth rhythm: strength `s` means the last block is ordered at
`(1 - s)` of the first, the total never moves (the voiceover owns it), and the
moved boundaries snap to word starts.

**An ordered rhythm holds a frame rather than reshaping its cadence.** On `even`
a clip too short for its block carries the shortfall into the next anchor
(CF-0028); on the other three that would destroy the only thing the rhythm was
asked for, so the block is delivered as one frame lifted out of its own clip and
marked `held_frame`. What such a one-shot block was offered is on the storyboard
block as `length_supply` (CF-0278): every candidate at or over the length it
needed (`long_enough`, with `available_seconds`, `score`, `rung`, `rank` and the
outcome - cut, refused with its reason, or not reached) and the shorter ones the
fill actually tried (`too_short_tried`); a degradation refusal copies it for the
blocks it names and prints one line per block, so "the pool had nothing long
enough" is read off the record, not off the sort (since CF-0435 the walk is in
usability rank, so long-enough-first holds only among shots of one score). A held frame is judged at the *clip* black ceiling, not the
stills one — it is a frame of a shot that already passed, and judging it as a
photograph rejects it for being as dark as the shot it came from. On `hold` this
is not a fallback at all, it is the rhythm.

**`alternate` against the defect it resembles.** CF-0034 measured a real video
where shots 43 and 36 alternated over four consecutive blocks — the same
*adjacent pair*, twice, with both shots well inside the reuse cap of 3 in force
then (CF-0026), so the cap could never have caught it. The difference is mechanical, not a matter
of intent: a candidate that would repeat an adjacent pair already used, or that
is simply the previous block's shot again, is refused at selection time;
`rhythm.repeated_adjacent_pairs()` re-measures it on the finished plan, and a
video where it is non-zero does not get `rhythm_delivered: alternate`. The
reuse cap is untouched and `alternate` gets no exemption from it - and the two
checks stay separate now that CF-0121 has taken the cap down to one use, which
would refuse *that* sequence too: the cap counts one shot's showings, the pair
rule counts a pair recurring, and an A-B-A-B built out of four distinct shots
satisfies any per-shot cap while still reading as stuck.

**A rhythm that ordered a second footage set and has not got one falls back in
writing.** `alternate` on a batch that declares no sides *and* whose second
source cannot supply a usable shot is built as `even`, with the reason in the
storyboard's `rhythm.notes` — not as an A-B-A-B drawn from one pool, which is
how the defect above arrives from the other end. A script that declared its own
sides does not need a second source at all: that is the whole point of CF-0050,
and `rhythm.sides_from` in the storyboard says which of the two answers this
video was cut on.

### The opening block

Four kinds, all buildable since CF-0050, and three of them have a precondition
that `rhythm.resolve_opening()` checks before the opening may be claimed. A
missing precondition falls back to `hook_over_footage` **in writing** — the
reason goes in `rhythm.notes` and `opening_delivered` never echoes an order that
was not carried out.

| opening | what it needs | how it is built |
|---|---|---|
| `hook_over_footage` | nothing | today's opening; nothing distinguishes block 0 but being first |
| `count_card` | `anchors.opening_card.text` — `script_anchors.py spec --opening-card "..."` writes it (the card's words are the Editor's; the anchors are not) | `asset_kind: card`, drawn by `CardLayer.jsx` (CF-0041) |
| `cold_frame` | a voiceover that starts late | **synthesize with `--lead-silence`.** The block plan is not touched: the picture is already up from 0.00s, and the beat is the voice arriving late. `align_words.py` shifts every timing on its own because it transcribes that same file, and the budget already counts the beat because the budget is measured off it. |
| `side_by_side` | both sides resolved to footage | `asset_kind: split`, two clips stacked by `SplitLayer.jsx`. Either side unresolved and the opening is not built at all — the clip cut for the surviving side is deleted. |

**A cold frame is spent from the duration budget, not added to it.** A 0.7s beat
is 0.7s less narration in a 35-60s video; `plan["duration"]` carries
`lead_silence` and `spoken` next to `actual` so that shows up as a deliberate
spend rather than as a script that mysteriously came in short.

**The `side_by_side` halves are framed for the half, not for the frame.** Each
is 1080x957 (1.13:1), which is *wider* than the 9:16 window every other block is
cropped to, so `focus` and `zoom` are recomputed by asking `smart_crop.py` about
the half's own aspect rather than by adjusting numbers meant for the whole
frame. Stacked rather than left-and-right because a vertical split leaves each
side 0.28:1 against 2.35:1 footage — 12% of each shot's width.

**A `side_by_side` half is a sequence, and it never stands still past
`rhythm.OPENING_MAX_STATIC_SECONDS` (2.5s, CF-0075).** The opening is laid over
the script's whole first run — 12.12s on `wren-hollow-lockhart`, against clips
of 1.09s and 3.8s — and holding a frame for the difference put a motionless
split on screen exactly where the viewer decides whether to stay. Now each side
plays its distinct clips back to back (`split[*].cuts`, no shot twice anywhere
in the opening), holds its last frame for at most the ceiling, and the opening
ends where the first side runs out of both (`rhythm.opening_length()`); the
rest of the run is filled as an ordinary block of that side, with the
opening's shots refused there, so it degrades through the normal chain rather
than freezing. `SplitLayer.jsx` mounts each cut as its own `Sequence`. The
deficit is written where CF-0057's side runs are: `plan["rhythm"]["side_runs"]
["opening"]` carries per-side `motion_seconds` / `static_seconds` /
`longest_static_seconds` against `run_seconds`, `truncated_seconds` and
`ceiling_seconds`, and `rhythm_shortfalls` gets a `kind: opening_static_held`
entry (`side: both`, `over_by_seconds`, `truncated_seconds`, per-side numbers)
whenever the opening stood past the ceiling or handed part of its run back —
recorded whatever rhythm was ordered. A held tail inside the ceiling that
finishes the run is the ceiling working and is only in `side_runs.opening`.

**Record the order and the fact, and never let one stand in for the other.**
`build_render_plan.py` writes `plan["rhythm"]`: `pattern_requested` /
`pattern_delivered`, `rhythm_requested` / `rhythm_delivered`, the cadence as
numbers, and the deviations. A video ordered as `hold` whose held key frame was
degraded is **not** a hold, and `rhythm_delivered` comes back `null` with the
reason rather than echoing the order — otherwise the Analyst learns about a
rhythm that was never on screen. Degradation cannot break `staccato` or
`alternate`'s boundaries (it swaps an asset, it never moves a cut) but it does
break `alternate`'s side sequence, because a block with no picture is on neither
side.

### The on-screen line (CF-0116, CF-0157, CF-0186)

While the voice speaks the video's one **fact** - since CF-0439 a concrete,
verifiable fact of any kind the story itself does not carry (production, box
office, release, casting, reception, scandal, people news, an unscripted
moment), not only one about the production - the frame carries
our own short wording of that fact and a badge naming the source it came
from. `scripts/comparison_line.py` plans it,
`render/src/components/ComparisonLine.jsx` draws it, and it runs last in
`build_render_plan.py` because it reads the finished plan.

**CF-0186 changed what it is about.** CF-0116 built this as the visible half
of `CF-0043` - our wording of the divergence between what was announced and
what the footage shows, one line per `comparison.checks[]`. That position is
cancelled (`CF-0181`), and `CF-0183` replaces the comparison beat in the
script with a fact beat. **This layer does not read `comparison.checks[]` at
all any more, and there is no fallback to it**: a line keyed to a cancelled
position is that position surviving. Until `CF-0183` lands, scripts carry no
fact, the layer plans nothing and says so in a note - a state, not a failure.

**The field is `production_fact` - the contract's name, kept although the fact
is now of any kind - and three of its keys are read here.**
`beat_text` is the *locator*: the verbatim substring of the narration that
speaks the fact, whose word range `meme_layer.locate_beat()` finds in
`words.json` (that range is the window). It is never drawn - it is the
narration itself, so on screen it would be a second copy of the subtitles.
`on_screen` is the *text*: our wording of the fact for the frame, at most
`comparison_line.FACT_MAX_CHARS` (60) characters; with none, the fact's own
`text` is drawn while it fits that budget, and never a truncation of it.
`source_url` is the *address* the badge points at. Nothing here writes a line
the script did not write: no `beat_text` means no line.

**Either half may be missing.** A fact with no source keeps its line and
takes no numeral; a fact with no wording that fits the frame keeps its badge.
With neither there is nothing to put up and the line is not planned
(`nothing_to_draw`).

**The names stay `comparison_line` / `comparison_lines`.** The module, the
plan field, `comparison_line_delivered` and the config switch
`video_editor.comparison_line.enabled` are read by the factory root, so
renaming them is a root change and not this repo's. Nothing they carry
describes the cancelled position; the identifiers are naming debt.

**The window = movement + rest + movement (CF-0157).** The *rest* starts on
the beat's first word, ends on its last, has a floor of **2.0 s**
(`comparison_line.MIN_SECONDS`) and is clipped to the video's duration. The
movement is added **around** it - `MOVE_IN_SECONDS` 0.42 in front,
`MOVE_OUT_SECONDS` 0.30 behind - so the card is already still when the voice
reaches the fact. The floor is on the rest and never on the window: a 0.42 s
arrival and a 0.30 s exit taken out of a 2.0 s window would leave 1.28 s to
read, less than the user had just called enough. The record carries both
pairs (`hold_start_s`/`hold_end_s` and `start_s`/`end_s`, the mounted range).

Two lines never share a frame, and the collision is measured on the full
window, movement included - a card that is still sliding out is on the frame.
The order of surrender is by what it costs the viewer: first the next line's
*arrival* is shortened (`_shorten_arrival`), then this line's *exit*
(`_clip_to`), and only then its rest, which is the only one of the three made
of words.

**A second layer, not a caption.** The captions keep running underneath;
`hiddenCaptionRanges` (CF-0071's insert suppression) is untouched by this
line - our text over our footage is not a document that carries its own words.
Typography is fixed from video to video and deliberately unlike the captions:
a kicker card under the watermark at the top of the safe area, left-aligned,
sentence case, `0.42 x captionSize` semibold, white on a translucent band with
a `theme.accent` rule down its left edge.

**The motion (CF-0157).** The card slides in from off the left edge and
leaves the same way, both non-linear: the arrival is an expo-out
(`Easing.bezier(0.16, 1, 0.3, 1)` - most of the distance at once, then a
settle, so it lands rather than drifts), the exit its mirror
(`Easing.bezier(0.7, 0, 0.84, 0)` - it sits, then goes). No spring and no
overshoot: on a card that carries a source an overshoot reads as a toy. The
lengths come from the plan (`move_in_s`, `move_out_s`), because they are what
the window was built out of; the component may spend them but never the rest,
so if the mounted range is short (CF-0117 clips the last line to the end
card) it is the movement that gives way.

*Checked against the edit*: `work/cf0157-check/movement_vs_accents.py` (archived by
CF-0498 into `Archive:shorts-content-factory-cleanup-1.6/video-editor-code-2026-10-03.zip`) puts
each line's four movement events beside the cuts `build_soundtrack.accents()`
sounds on (`blocks[1:].start`, a 0.34 s transient each). Within 0.08 s the
movement and the accent are one event, which is wanted; the zone that would
read as a mistimed cut is 0.08-0.34 s after one. On the only real corpus that
carries lines (`2026-09-03T2037Z/raygun-sneak-peek`, three lines) the nearest
approach is +0.74 s - 12/12 events clear. The line does not enter on every
cut and nothing snaps it to one; whether it *should* be snapped when it does
land in the ambiguous zone is a judgement for the user, not a measurement.

**What the card is: a pointer to a source (CF-0157).** The user's own
definition of the element - "we found this information here; if you are
curious, look into it yourself using this data". An invitation to a source,
not a verdict on the claim, which is why a **tick** ("we vouch") and a
**question mark** ("we doubt") were both rejected *on meaning*.

What is drawn instead is a **numbered reference**: a boxed numeral in the
accent colour and the word `SOURCE`. A footnote marker is the one device
whose whole job is provenance - it asserts nothing about the sentence it
hangs on, it is an address, and the reader who wants it follows it while the
reader who does not carries on. The numeral is load-bearing, not decoration:
it is the key that joins the card to its entry in the description
(`CF-0017`) - the card says `[2]`, the description says `[2] <url>`.
`comparison_line.number_references()` assigns it 1..n in the order the lines
come up, and only to a line that actually carries a badge - an address *and*
a publication to name; a line without both gets no `ref`, and the component
then draws no badge at all and makes no promise - the fact strip stands on
its own (CF-0186). The numbering closes up over the
lines it skips, because a gap in it would be a `[2]` the description cannot
answer.

**Two lists of hosts, three answers (CF-0166).** The host of `source_url` is
read against the publication names
(`video_editor.comparison_line.publishers` over
`comparison_line.DEFAULT_PUBLISHERS`) and against the platforms
(`...comparison_line.platforms` over `DEFAULT_PLATFORMS`: youtube.com,
youtu.be, x.com, twitter.com, reddit.com, tiktok.com, instagram.com,
facebook.com). A name draws a badge. A platform draws none: the reason is
recorded as its own (`source_is_platform`) and the line takes no reference -
a place where a video sits is not who vouches for the fact, and a badge
reading "YouTube" would answer the badge's own promise with the name of a
warehouse. **CF-0186: that costs the badge and not the line** - the fact on
the strip is ours and does not depend on who hosts the source. A host in **neither** list still
stops the stage and names both remedies, because that is the one case where
silence would hide something: a real newsroom missing from the table. Adding
a platform is a config edit, never a code change.

**No URL is on the frame.** Not the full one, not a host, not a path segment.
The label reads `SOURCE ↓ DESC` and that is
where the link is clickable rather than copied off a moving frame. (The
2026-09-08 plan to print host + first path segment - and with it the edit to
`inserts/proof.json` - was withdrawn by the user the same day.) The proof
contract is therefore untouched: when `CF-0071` placed a proof on the same
beat its `source_url` still rides on this line's record
(`source_url_from: "proof"`), a fact with only its own `source_url` records
that (`"script"`), and both go to the description **in full**. The
obligation on the far end is `CF-0017`'s - the description must carry the
source block this card promises. Nothing is published before publisher exists, so there is
no window in which the card lies to a living viewer, which is why there is no
gate here.

**Provenance.** `plan["comparison_lines"]` is the list Remotion reads (the
whole plan is the composition's props) and the same list
`write_batch_metadata.py` copies onto `videos[].comparison_line_delivered` -
`{fact_id, text, start_s, end_s, hold_start_s, hold_end_s, move_in_s,
move_out_s, ref, publisher, panel_w, block_index, source_url,
source_url_from}`, always present, `[]` when the video carried none.
Symmetric with `pattern_delivered` (CF-0041) and not with the insert pairs:
nothing requests this line - a fact that can carry one gets one - so there is
a delivered side and no requested side.

**The user's condition (from `CF-0043`, not a preference).** If the line reads
cringe on a real render, the *form* goes back to the user through
`needs-you` - it is not re-designed inside a task. The first render carrying
the line is shown to the user before the task closes; `CF-0116` closed with
that render (`work/cf0116-sample/`, the three real lines of
`2026-09-03T2037Z/raygun-sneak-peek`). **The condition rides on every change
of the form**: `CF-0157` rebuilt the card as a numbered reference and gave it
the eased slide, so its render goes back to the user the same way
(`work/cf0157-sample/`, archived by CF-0498 into `Archive:shorts-content-factory-cleanup-1.6/video-editor-code-2026-10-03.zip`) before that task
closes.

### The end card (CF-0117)

Every video ends on the channel signing it: a full-frame card holding the
channel's logo and its signature phrase for the seconds `CF-0087` budgets,
after the last word of the narration. `scripts/end_card.py` plans it,
`render/src/components/EndCard.jsx` draws it, and it runs **last** in
`build_render_plan.py` - it starts where the narration ends, so nothing may
still move that number after it.

**The phrase is read, never written - and there may be none (CF-0186).**
`channels/<channel>.json` names its stance document in `stance` (relative to
`channels/`, CF-0063); the text is `signature_phrase.text` there. The card is
worth having only because it is identical in every video, and that promise is
only real if there is one copy of the phrase. So there is no default and no
fallback - if you ever find yourself typing a phrase into code, that is the
bug.

**example-film has no phrase at all.** CF-0181 removed `signature_phrase` from
its stance document with the position it belonged to, and CF-0186 made that a
state rather than an error: the channel's `ending.mp4` already carries its
slogans drawn into it (MOVIES · TV · FACTS, NEW SHORTS EVERY DAY), and a
second slate set in code right before it says the same thing twice. So
`signature_phrase()` returns `(None, None)` on a stance with no phrase, and
the card is planned without one: the channel's logo, or - with no logo - its
own name at the size the phrase used to hold. With no phrase, no logo and no
name there is nothing to draw and **no card is planned at all**
(`plan_end_card()` returns `None`); the seconds go back to the narration.

What is still a refusal: a channel that *names* a stance document it does not
have, or one that cannot be read, and a config with no `end_card_seconds`.
Those get **no plan at all** - `END CARD NOT PLANNED - plan not written`,
exit 2, the same answer a rejected asset gets. That is the one thing here
that does not degrade to a note. `tests/test_end_card.py` proves the phrase
is read by planning a card on a temp channel whose stance says something
else, and proves the phraseless card on three more.

**The length is the constant, not a judgement.**
`narration_budget.end_card_seconds` in the channel config (CF-0087) - 3 s
today. The card comes *out of* `target_total_seconds`, not on top of it: the
narration is written to `55 - 3` seconds and `narration_length.judge()`
already reserves the same three at the TTS gate. A config without the key
raises rather than picking a number.

**Where it starts:** the end of the voice-over (`plan["audio"]["duration"]`,
which is also the last block's end - `build_render_plan.py` runs the last
block to the end of the audio). That is the number the budget's arithmetic
means; the last *word* ends a fraction earlier and starting there would open
a hole nobody budgeted.

**The logo, and the floor under it.** `channels/<channel_id>/logo.png` (or
`.svg`/`.jpg`/`.jpeg`/`.webp`), beside the stance document in the channel's
own directory; `video_editor.end_card.logo` in the channel config overrides
the convention with any path. No file, or a named file that is not there ->
`variant: "typographic"`, the phrase large with the channel name under it.
Same argument as the `typographic` style: the last frame of a video is the
worst possible place to discover a missing asset, so the card that depends on
no file is the one that always works. **example-film has no logo today**
(branding is Publisher's, CF-0016), so typographic is what actually ships -
that is the floor doing its job, not a failure to report.

**The frame is the card's.** The watermark is hidden under it (the watermark
is the channel's mark riding on somebody else's footage; the card *is* the
channel's mark, full frame - two of them read as a template), the captions'
hidden ranges include the card's span, and a CF-0116 on-screen line is cut
off at the card's first frame. Both of those ranges end at the frame the card
*mounts* on, not at `start_s`: the card is mounted `CROSSFADE` (0.35 s) early
so it dissolves out of the footage, and a range that stopped at `start_s`
would leave our own text on screen for the whole dissolve. The captions are
the cheap half - the last word ends before the narration does, so nothing is
suppressed in practice. The line is the half that bites: `comparison_line.py`
clamps a line to `duration.actual`, which *is* `card.start_s`, and holds it
to a 2.0 s floor besides, so the last beat's annotation reliably runs to the
narration's last frame. The ground is a lifted slate rather than
`theme.bg`: three held seconds of near-black read as the video having ended,
and `qc_render.py`'s own black-run gate would fail it. 0.3 s fade in, a small
settling rise, no fade out - the card holds to the last frame.

**Three numbers now differ, and each has its own job.**
`duration.actual` is the voice-over (the CF-0087 target band, the deviation,
the on-screen line's window - all judgements about the narration).
`duration.composition` = actual + card is the length of the file: `Root.jsx`
sizes the composition from it, `build_soundtrack.py` mixes to it and
`qc_render.py` measures the picture against it. Do not "fix" a plan by
setting `actual` to the longer number.

**The bed continues and fades; there is no voice under the card.**
`build_soundtrack.py` pads the voice with silence to `duration.composition`
(`amix=duration=first` takes its length from that input - without the pad the
mix stops on the last word) and fades the bed out across the card in the
filter graph, one `afade` that covers a supplied `--music` track as well as
the generated bed. The duck releases on the last word, so the bed lifts to
about -25 dB as the card comes up and reaches about -44 dB at the last frame.

**Provenance.** `plan["end_card"]` is what Remotion draws, and
`write_batch_metadata.py` copies it onto `videos[].end_card_delivered` -
`{seconds, start_s, text, text_source, variant, logo_path}`, always all six
keys, `null`-filled on a plan built before the card or without a
`--channel`. `text_source` is the point of the record: it names the file and
field, so the card can be **checked** against the stance instead of
believed.

**Manual runs write into the batch you name.** Running `end_card.py`,
`build_soundtrack.py` or `build_render_plan.py` by hand on a real batch path
without `RUNLOG_BATCH` set makes CF-0107's lookup fall back to the batch in
the path and append accounting events to a real batch's `RUN_EVENTS.jsonl`
(it happened in CF-0116). Prefix a one-off with `RUNLOG_BATCH=$(mktemp -d)`;
inside the stage the variable is already exported (Run accounting above), and
the test runner exports its own.

**The user's condition (from `CF-0043`, carried forward).** If the card
reads cringe on a real render, the *form* goes back to the user through
`needs-you` - it is not re-designed inside a task. The first render carrying
the card is shown to the user before the task closes; `CF-0117` closed with
that render (`work/cf0117-sample/`, the tail of
`2026-09-03T2037Z/clooney-venice-lion`). The clause it used to cite
(`stance.json#signature_phrase.revisit_clause`) went with the phrase in
CF-0181; the condition itself is a rule about form and did not.

### Proof placement (CF-0071)

The contract is `inserts/proof.json` in the factory root; `scripts/proof_layer.py`
executes it and this section only says where the step sits. **Whether the layer
runs is read from the channel, never asserted here** - `insert_layers.proof.enabled`
plus `capture_method` in `channels/<channel>.json`, which `proof_layer.layer_switch()`
answers as one pair. A channel with the switch off, or on with no `capture_method`,
answers every request `layer_off` and its plan is built exactly as it would be
without the layer. That is a fact about one config file and it expires when that
file changes, so open the file for the channel in front of you rather than
carrying an answer over from another one.

**Nothing in the root is waiting to be flipped.** Both accepted methods
(`headless_browser`, `rendered_quote`) are `executable_today: true`,
`implemented_by: CF-0071`, in `inserts/proof.json`, and `proof_layer.allowed` on
the patterns is flipped as well: since 9f11061 every real pattern (explainer,
moment-breakdown, list, contrast) carries `allowed: true` with its reason, so
`pattern_refused` no longer occurs on them - only on a pattern that is missing
or refuses. A `layer_off` today therefore means the channel said so, not that
the mechanism is unbuilt.

**The request.** The writer's `proofs[]` in `03-content-researcher.json` (at most
2): `proof_id`, `verbatim_text` (<= 72 chars), `source` (url, publication, title,
published_at, handle) and `capture_method_hint`. A proof has no beat of its own
and **no id of what it supports** (`CF-0223` deleted `check_id`, `CF-0243`
deleted the lookup): it sits on `script.production_fact`, whose `beat_text` is
located in `words.json` the way the meme layer locates a reaction
(`meme_layer.locate_beat`) and whose `source_url` is the document it shows. A
script carries exactly one fact, so the fact *is* the claim and the url is what
joins a delivered proof back to it.

**The place** (`placement.priority`): the block holding the beat's first word,
then any other block the beat overlaps, then a block whose narration quotes the
wording, the handle or the date exactly - nowhere else. Every candidate must last
at least 3.0s **and** at least `len(verbatim_text) / 12` s, and carry no other
insert. **CF-0012's M1 does not apply**: an anchorless block is not a reason to
reach for a proof - it is evidence for one sentence, not a filler. Runs *before*
the meme layer, so a meme that could go anywhere its beat overlaps never takes
the proof's one block.

**The chain** (`capture_priority`): the channel's `capture_method` names the top.
`headless_browser` means headless_browser then rendered_quote; `rendered_quote`
means rendered_quote alone. A post (`source.handle` set) or a writer's hint
`rendered_quote` enters at rendered_quote - headless never touches X. The chain
moves on a **fetch failure only**: host outside the channel's
`sources.rss.feeds[].site` pool (+www), x.com/twitter.com/t.co, robots.txt `*`
disallow under our honest User-Agent, non-200, off-pool redirect, timeout, no
`<h1>` in the DOM (a wall or a challenge page), per-host budget spent
(`capture_page.py`; the browser is Remotion's own chrome-headless-shell driven
by `capture_page.mjs` - 640x1136 @2x, DOM loaded + network idle, fixed
overlays hidden by CSS, nothing clicked or accepted, region `article_header`).
A capture that **arrived and failed the gate stops the chain**: outcome
`illegible`, block built without an insert, never a rendered_quote in its place
(`degradation.never_substitute`).

**The gate** (`proof_layer.check_proof_gates`, not `inspect_asset()`):
`no_upscale` (>= 1080px wide natively), `text_present`, `legibility`,
`attribution_visible`. `near_black`, `roi_coverage`, `subject_present` and
`MIN_SHORT_SIDE` are skipped by name - a 1280x300 header capture is not 300px
footage.

**Gating lines vs furniture** (`inserts/proof.json` `legibility`, refined
2026-09-06 after the first real Variety header measured its headline at 45-54px
and its masthead at 17-23px). Every Vision-recognised line is measured on the
delivered `contain` framing, but the 39px floor (half our 78px caption) applies
only to the lines that carry the proof. For `headless_browser` those are the
lines matching the capture's sidecar `<capture>.proof_text.json` (`{h1,
standfirst}`, written beside the PNG by `capture_page.py` from the rendered DOM
- the `<h1>`'s textContent, the standfirst only on the
`article_header_with_standfirst` region; the gate takes it as input and never
re-fetches). A line matches (`proof_layer.line_gates_proof_text`) when, both
sides casefolded with punctuation and quotes stripped, it is a substring of the
h1/standfirst or >= 0.6 of its tokens appear there in order; lines under 4
characters never match. Navigation, subscribe prompts, breadcrumbs, the
dateline, the byline and the masthead are furniture: measured, recorded, never
gating. For `rendered_quote` every drawn line gates (the card carries nothing
else). Fewer than 1 gating line recognised is `illegible` (the machine did not
read the proof text); `max_lines` (6) counts gating lines. Whenever a capture or
a card was measured (`placed`, `capture_failed_fell_back`, `illegible`) the
delivered entry carries `legibility: {gating_min_px, gating_lines,
furniture_min_px, lines_total}` in delivered-frame pixels - the furniture number
is kept because the next question is whether to crop it before delivery.

**Honesty rules for `rendered_quote`** (`render_quote.py`): our typography and
colours (the Remotion theme), an accent bar and nothing else - no chrome, logo,
avatar, verification mark, reply/like furniture or screenshot-like frame; the
card shows `verbatim_text` unedited, the outlet or the @handle, and the date.
`source_url` rides on the block's insert for the CF-0065/CF-0116 sourcing line
(not rendered by this repo yet). A source missing any of url / published_at /
publication-or-handle is `source_incomplete` before anything is fetched.

**Composition**: `insert: {kind: "proof", capture_path, fit: contain,
background: black, captions: hidden}` beside the block's own `asset`, which is
untouched; our captions go quiet over the span (`Video.jsx` reads `block.insert`).

**Outcomes** (`proof_delivered[].outcome`, one per request, in order): `placed`,
`capture_failed_fell_back` (both placed - `block_index`/`file` set), `layer_off`,
`pattern_refused`, `fact_not_found`, `beat_missing_in_script`,
`beat_unmatched_in_alignment`, `beat_no_alignment`, `too_long`, `no_block`,
`source_incomplete` (decided before any capture: `attempted: []`),
`capture_failed`, `illegible` (after one: `capture_method_used` = the last method
tried).

**A proof ordered and not delivered is a record, never a silence (CF-0193).**
Every unplaced request leaves an entry in `proof_shortfalls` - `code`,
`proof_id`, a `note`, and `decision`: `refuse` or `ship_without_proof` - with
`proof_not_delivered` carrying the first code and `proof_delivered_fully` the
boolean, the three fields CF-0192 gave the pattern. The two beat diagnoses
carry `evidence` too: the fragment searched for, the nearest fragment actually
heard and its word index, and how much of the beat is covered in the script
and in the alignment. Before this a beat the alignment did not give back ended
`beat_not_found` with `attempted: []` and a sentence in the notes, and the
video shipped - two of the three proofs ever ordered ended exactly there, and
in all four unlocatable beats on disk the words were in the script character
for character. A `fact_not_found` answer carries `evidence.missing` instead:
which part of the anchor is absent (`production_fact`, `source_url` or
`beat_text`), so a refusal over a missing fact names what to fix and is never
dressed up as a beat the narration does not say (CF-0243).

`fact_not_found` and `beat_missing_in_script` mean the request points at
something that does not exist, so `scripts/proof_beat_gate.py` refuses the
plan (exit 2, `plan.proof-beat.json` beside where the plan would have been) -
rung 4 of the CF-0137 ladder, and the reason a script that contradicts itself
never becomes a video. Everything else ships with the shortfall on the record.

`proof_capture_telemetry` (`requests_by_host`, `fetch_failures`) is
written whenever headless_browser was attempted. Provenance per placed proof
goes to `05-video-editor.json` `proofs[]` (and `inserts[]` with `layer: "proof"`):
the nine required fields plus `archive_url` when not still live, `rights_holder`
= `author_or_outlet`, `licence: null`, `blacklist_check` recorded and never gating.

### Meme placement (CF-0067)

The reaction meme is a factory mechanism switched per channel
(`insert_layers.meme.enabled` in `channels/<channel>.json` - read it for the
channel in front of you; a switch is a fact of one config file and this
section does not carry one channel's answer over to the next) and tolerated
per pattern (`meme_layer.allowed` in `patterns/<id>.json`: explainer,
moment-breakdown and list yes, contrast no).
The contract is `inserts/meme.json` in the factory root and this section is
not a copy of it - read the file; `scripts/meme_layer.py` executes it and
`build_render_plan.py --script <03-content-researcher.json> --script-id <id>
--channel <channel>` runs it after every block is built. Nothing here is a
step you take by hand: the writer's half is the script's `reactions[]`
(`beat_id`, `intent`, `beat_text`, optional `query`), yours is the file, and
neither side does the other's job - a script that names a file is treated as
one that named only the intent.

**Where a meme may go (M2, mechanical).** Only a block lasting at least 3.0s
(`placement.min_block_seconds`; the median block is 1.54s, so this is a rare
block by construction), and only a block that overlaps the beat's words in
`words.json` - the beat is located the way a comparison check's `beat_text`
is, by its words in the alignment. The request is never moved to a long block
elsewhere. A block already carrying a proof is not a candidate either - one
`insert` per block.

**No block at the floor: the meme gets a span (CF-0811).** When no single
block at the floor overlaps the beat - on `list` that is every request, its
hold ceiling `key_frame_hold_seconds` 2.5s is under the 3.0s floor - the
request is not answered `no_block`. `meme_layer.build_span()` lays the meme
from the **beat's first word** over the consecutive blocks it needs, to the
first block boundary at least `placement.min_block_seconds` after that word
(read from the spec; capped at `placement.max_block_seconds`). The blocks are
not cut or merged - every index the plan already wrote stays true - the same
meme goes on each of them as `insert`, windowed to its part (`start_s`/
`end_s`) and carrying one `span` record (`blocks`, `start_s`, `end_s`,
`seconds`, `beat_start_s`); the renderer draws them as one picture (no
dissolve inside the span, one motion and one GIF loop on the span's clock).
The first block keeps its own picture up to the word, unless that head is
shorter than `rhythm.MIN_ORDERED_BLOCK_SECONDS` (a flash), when the meme takes
it. The pattern's hold ceiling is not asked of the span - it was asked of the
blocks, and a span is one picture by design. A span is always the whole meme,
never a cutout. It stays inside the commentary (never from the hook, never
past the payoff's first word - `meme_layer.commentary_bounds()`) and never
covers a pinned block: one with an `insert` already (a proof, an earlier
meme) or a `card`, `own_graphic` or `split`. When that makes the floor
impossible the answer is `no_block` **with `reason`**, one of
`meme_layer.NO_BLOCK_REASONS`: `no_room_before_payoff` (under the floor from
the word to the payoff), `pinned_block_in_span`, `beat_outside_commentary`,
`no_block_at_beat` (nothing on screen at the word), `max_inserts_reached`.
A bare `no_block` is no longer written. The writer's half (content-researcher
CF-0811 part a) guarantees the words: from the beat's first word to the end of
the commentary at least ceil(3.0 s x the script's words per second).

**Which of them (M1, priority).** A block with **no picture on it** takes the
meme first; then the block containing the beat's first word; then any other
overlapping block at the floor. The meme earns its place by fixing the plan's
weakest frame before it decorates its strongest.

"No picture" is one predicate and not three: `rhythm.has_picture()` is false
for the block, or `degraded_blocks` records it `from: unfilled` - the same
question the CF-0137 gate refuses over, so a hole M1 declines is exactly a
hole that gate will refuse the plan for. `asset.kind: procedural` is the usual
shape of one, not the definition; a block with no `asset` key at all is the
same hole to a viewer (CF-0138).

**How such a block reaches this layer at all** is not obvious, and was worth a
ticket of its own (CF-0146). The CF-0137 gate refuses a plan holding one, and
it is asked *above* this layer - which would leave M1 addressed to a state
production never reaches. But when a library insert could conceivably close
every hole - `meme_layer.hole_fill_feasible()`, two config switches and the
block lengths, no library and no CLIP - that refusal is **deferred to just
below this layer and re-asked there**, on blocks this layer may have filled
(CF-0138). That deferral is M1's whole route, and it does not read the
`assetless_block_rung` flag: M1 is live on a channel with the rung **off**,
which is every channel. Where the probe says the hole could never have been
filled (under the 3s floor, the layer off, the pattern refusing, more holes
than the insert budget) the plan is refused above this layer and M1 is indeed
never asked - correctly, because nothing here could have helped.

M1 is the *requested* half of that rescue: the writer asked for a meme on a
beat, and among the blocks that beat overlaps, the hole gets it. The half with
no request behind it is CF-0138's own pass over every remaining hole, taken
after every request is answered. Both are checked rather than remembered -
`tests/test_meme_priority_reachable.py` pins all three links of the chain,
because the M1 ordering tests run on a fixture channel with the rung switched
*on* and would all stay green if the deferral were removed.

**Whether there is an answer at all (M4, CF-0143).** Two floors, and the
walk stops at the first candidate that fails either - which is the `no_asset`
that hands the block to the degradation chain rather than taking the least
wrong picture:

* the candidate's own score ≥ `selection.min_similarity`, and
* its **lead over the field**: its score minus the score `selection.lead_rank`
  places below it ≥ `selection.min_lead`.

The numbers are measured, not chosen - `scripts/measure_insert_lead.py` runs
30 queries whose right answer is in the library against 30 that have none, on
the 101-entry library CF-0115 filled. What that says (right picks kept /
wrong ones taken): the shipped `min_similarity: 0.2` alone 1.00/0.84 - it
refused nothing, every wrong query still had a leader over 0.2; the score
alone at 0.26, 0.96/0.14; the lead alone, 0.91/0.16; **both, 0.96/0.05**. So
neither floor is redundant. The lead is measured to the **third** place, not
the second, because the library holds near-duplicates on purpose
(facepalm-man/facepalm-old-man, spirerunner-pointing/spirerunner-triple) and a
*correct* pick sits 0.004-0.016 above its own twin; against the second place
the same measurement gives 0.70/0.03. Re-run the script after the library
grows - the floors are properties of a library, not of CLIP. CF-0402
(2026-10-04) re-ran it on the 28-entry library with a relabelled set, scoring
the walk's pick after the stretch gate: both floors 0.78/0.045, the score
alone the same, and 0.26 no longer the middle of a plateau (0.255-0.259 gives
0.81/0.045). The numbers stay as `inserts/meme.json` has them until the user
signs a change (CF-0320); the script's docstring has the full table.

Two things the measurement says that are not threshold problems: the eleven
`default_query` strings are the weakest queries in the set (five refused at
these numbers, three of them losing the right picture), which is the argument
for the writer's own `query`; and the same rule does **not** transfer to the
sound layer or the underlay - a sound is ranked by an integer count of
matched tags where a tie means two right answers, and an underlay loop is
picked by rotation with no relevance judgement at all. Both module docstrings
carry the reasoning.

**Meaning rule M3 - not verified.** The meme carries a reaction the narration
does not say. Only its *negative* half is checked, mechanically: Vision
(accurate mode, `detect_text_band.sample_text_regions`) reads the text on the
candidate file, and if that text restates the words spoken over the block
(`words.json` over the block's span) the candidate is skipped
(`meaning_negative_half`) and the walk continues. The *positive* half - that
the reaction adds something the words leave unsaid - is the writer's and is
only answerable from published videos (the Analyst's question). **Never report
M3 as measured**; report it as "negative half checked, positive half
unverified", which is what `inserts/meme.json` `meaning_rule.status` says.

**The file.** `embed_texts([query])` (the writer's `query`, else the intent's
`default_query` - the text embedded is what `meme_requested[].query` records)
→ `rank_by_embedding` over the whole library - **no blacklist check**: a meme
carries no rights-holder entry (CF-0389), so nothing is cut before the ranking → the candidates walked through the meme's own gate:
M4's two floors (below), distinct per video, file present, still or GIF (no audio
track - a file with sound is CF-0068's), the stretch it gets fitted `contain`
into the insert box (`meme_layer.meme_box()`: CF-0394's box above the caption
band, 1080x1219 at 1080x1920) ≤ `inserts/meme.json`
`asset_floor.max_upscale_factor` (2.25, read from the contract - CF-0392: the
file's short side is not measured, a landscape meme is bound by its width;
**`MIN_SHORT_SIDE = 720` is untouched and not applied here**), M3's negative half. The general gate's `subject_present`,
`roi_coverage`, `near_black` are skipped by name: a meme is a drawing as often
as a face and is contained, not cropped into.

**Composition.** `contain` on black, no Ken Burns, no punch, no smart-crop;
our captions are hidden for the block's span (`Video.jsx` hides them over
any block with an `insert`); since CF-0811 the insert is drawn over a
`sequence` and a `procedural` block too (`AssetLayer.jsx` asks it before
them - until 2026-10-19 a meme there was in the plan and never on screen; a
card, an own graphic and the split still return first); a GIF is looped to the block at its own length
(`meme_layer.py` cuts a silent mp4 beside the plan, `AssetLayer.jsx` loops it)
and cut at the block's end. The meme is an overlay: the block keeps its own
`asset`, its length, its rhythm fields, and is built exactly as it would be
without one - a failed request changes nothing in the plan but the record.

**The record.** `meme_requested`/`meme_delivered` on every `videos[]` record
of `05-video-editor.json`, always both, `[]`/`[]` when the script asked for
nothing - symmetric with `pattern_requested`/`pattern_delivered`. Outcomes are
a closed list: `placed | layer_off | pattern_refused | beat_missing_in_script
| beat_unmatched_in_alignment | beat_no_alignment | no_block | no_asset`;
`block_index`/`asset_id`/`score` are set exactly when `placed` (on a span,
`block_index` is its first block and the answer carries `span`); a `no_block`
carries `reason` (CF-0811, above). Memes on screen = answers with `outcome:
placed`; one provenance record per placed meme, on that `block_index`. The three
beat codes are `meme_layer.beat_failure()`'s, shared with the proof and sound
layers (CF-0235 - `beat_not_found` answered "the video never says this" and
"our aligner lost it" with one word, and only the second is ours to fix); an
answer carrying one of them also carries `evidence`, the fragment searched
for and the stretch that came closest as it was heard. `beat_not_found` is
read from older records and never written. One `inserts_lib.provenance_record` per file placed and per file
the gate skipped goes to `videos[].inserts[]` with `layer: "meme"`,
`beat_id` and `score`, beside the underlay's records; `rights_holder` is the
index's value and may be null, and `blacklist_check` says `applied: false`
("not applied to memes", CF-0389) - never report that as a skip or a pass. `build_render_plan.py`
prints one `MEME <beat_id> (<intent>): <outcome>` line per request; say the
outcome in the report the same way, and never write `placed` for a meme that
is not on screen.

### Sound placement (CF-0068)

The sound insert is the audio member of the insert family: a recognisable
sound of at most 1.5 s from `shared/inserts/sounds/`, mixed into the
soundtrack at one moment of the commentary. Switched per channel
(`insert_layers.sound.enabled`; example-film has it **off**) and tolerated
per pattern (`sound_layer.allowed`: explainer, list, moment-breakdown yes,
contrast no). The contract is `inserts/sound.json` in the factory root and
this section is not a copy of it - read the file; `scripts/sound_layer.py`
executes it, `build_render_plan.py --script ... --script-id ... --channel ...`
runs it right after the meme layer, and `build_soundtrack.py` mixes what it
placed. The writer's half is the script's `sounds[]` (`beat_id`, `intent`,
`beat_text` - no `query`, no file; a separate namespace from `reactions[]`,
never joined by id even when a beat carries both), yours is the file.

**Library empty until CF-0115.** `shared/inserts/sounds/index.json` has no
entries today, so every request on a channel with the switch on is answered
`no_asset` - a fact for CF-0115 to read, not a defect. `inserts/validate_inserts.py`
`LIBRARY_BLOCK_LAYERS["sound"]` stays `executable_today: false` until the
library is filled; do not flip it from here.

**The moment (S1).** `at_seconds` is the start of the beat's first word in
`words.json` - the same lookup the meme makes (`meme_layer.locate_beat`),
no offset, no better word; not located is one of the three beat codes
(CF-0235), never a guessed moment. The block
index is the block whose span contains the moment: **recorded, never
chosen** - a sound is not moved to a block.

**The slot (S2, S4).** `[at_seconds, at_seconds + duration_s]`, the file's
own length, at most `MAX_SOUND_SECONDS = 1.5` (inserts_lib's, imported, hard
cut in the mix). Refused as `no_slot` when the slot would cross into the
payoff's first word or past the voice end, when the anchor is inside the hook
(`protected_sections`), when it is inside `SOUND_MIN_GAP_SECONDS = 4.0` of an
earlier placed sound (script order wins, anchor to anchor), or past
`SOUND_MAX_PER_VIDEO = 2`. Never moved to a freer moment.

**The file.** `inserts_lib.eligible` first (a high-risk rights holder is
skipped before it can rank; the skip is written to provenance with the block
and moment it was skipped for) → the entries answering the intent by tag
(`selection.intent_vocabulary`: a tag equals an entry tag, or with
underscores as spaces occurs as whole words in its description; no stemming,
no embedding, no score) ordered by match count then id → the gate walked in
that order: file present, sound suffix, **re-measured** duration in
`[0.1, 1.5]` s, the slot inside the commentary, an audio stream and no video
stream (a file with a picture is a clip and is never placed), distinct per
video, S3. First pass wins; none is `no_asset`. The record carries
`matched_tags` instead of a score.

**Meaning rule S3 - not verified.** The sound punctuates a reaction the
narration does not voice. Only its *negative* half is checked, mechanically:
a word spoken over the slot equal to a matched tag (`oof` said over the
`oof` file) skips that candidate (`meaning_negative_half`) and the walk goes
on. The *positive* half is the writer's and only answerable from published
videos. **Never report S3 as measured**; report it as "negative half
checked, positive half unverified" (`inserts/sound.json` `meaning_rule.status`).

**The mix.** `build_soundtrack.py` reads `plan["sound"]["placed"]` and lays
each file on a fourth input (`inserts`): trimmed at the ceiling, faded
`SOUND_FADE_IN_MS = 5` / `SOUND_FADE_OUT_MS = 40` (out only where it was
cut), gained so its loudness sits `SOUND_LEVEL_REL_VOICE_DB = -3.0` under the
whole voice track's (gated RMS, one number per video), peaks capped at
`SOUND_PEAK_CEILING_DBFS = -1.0`. The bed is sidechain-ducked under it with
the same compressor the voice keys (`SOUND_DUCKS_BED`); **the voice is never
ducked** (`SOUND_DUCKS_VOICE = False` - the narration is the product, and a
hole in it would move every layer timed against it). Captions stay visible.
No stretch, no pitch, no loop. A plan with no placed sound runs the
three-input graph exactly as before: nothing about a missing sound changes
the mix, a block, or a caption. Constants live in `common.py`.

**The gate.** `qc_render.py` `MIN_SOUND_RMS_DB = -30.0`: RMS of the mix minus
the voice-only render (the plan's `audio.src`, the voice's share scaled by
the limiter's auto-level) over each placed slot, the bed gate's instrument;
below the floor the render **fails** as a mix defect - a sound recorded as
placed that cannot be heard is the lie the pair exists to prevent.
Reported under `measured.sound_rms_db`.

**The record.** `sound_requested`/`sound_delivered` on every `videos[]`
record, always both, `[]`/`[]` when the script asked for nothing. Outcomes
are a closed list: `placed | layer_off | pattern_refused |
beat_missing_in_script | beat_unmatched_in_alignment | beat_no_alignment |
no_slot | no_asset` (the same three beat codes, with the same `evidence`;
`beat_not_found` is read from older records and never written);
`block_index`/`asset_id`/`at_seconds` set exactly when `placed`. One provenance record per file placed and per file skipped goes
to `videos[].inserts[]` with `layer: "sound"`, `beat_id`, `at_seconds`,
`matched_tags`, beside the meme's and the underlay's (each layer replaces
only its own on a rerun). `build_render_plan.py` prints one
`SOUND <beat_id> (<intent>): <outcome>` line per request; say the outcome in
the report the same way. Nothing here is validated on a real video yet
(`inserts/sound.json` `validated.status`): the first batch on a test config
with a filled library is the first measurement.

### The underlay in the second plane (CF-0127)

The brainrot underlay: a **muted** loop from `shared/inserts/loops/` in the lower band of the frame, under the main content, chosen per video by rotation. The decision is the factory's — `shared/inserts/underlay.py` (`plan_underlay`), CF-0014's `## Решение` of 2026-09-05 — and `scripts/underlay_layer.py` is our half: it calls that module and turns the answer into two plan fields. It needs no script and no pattern (the channel switch and the library rotation are the whole of it), so it runs on **every** plan that has a `--channel`.

**Where the band is.** `layout.secondary`, the named slot `render/src/lib/layout.js` already resolved and `SecondaryZone.jsx` already drew — the empty slot CF-0014 was written about. Applied, it takes `underlay_layer.SECONDARY_HEIGHT` (0.28) of the frame off the bottom of `main`; not applied, it stays `null` and `main` keeps the whole height, which is every video before this and every video on a channel with the switch off. Not a wash behind the picture: `main` is `cover` over the whole frame, so a plane *behind* it would be hidden by every block that has a picture. Everything else stays above the band — captions, the on-screen line, block inserts, the watermark, the end card.

**Decided before the blocks**, unlike the meme, sound and proof layers, which are overlays on finished blocks. The band changes `main`'s height and `main` is what every block is framed and cropped against (`split_half_size()` frames CF-0050's halves against it), so `build_render_plan.py` runs this one right after the voice-over's length is known, before the block loop. If you ever move it later, the crops of a two-plane video get framed against a one-plane frame.

**It stops at the end card.** The loop is sized against `duration.actual` — the narration — never the composition, and `Video.jsx` mounts the band in a `Sequence` that ends at the frame the card is *mounted* on (`cardFrom`, `CROSSFADE` before `start_s`). The card owns the frame it is on (CF-0117); a loop still moving under the channel's signature reads as the file not having ended. Measured on the sample: at t=6.0 s the band's `signalstats` are identical to a render with the layer off.

**A channel with this switch off has decided something, and that is not a gap.** Read the switch where it lives — `insert_layers.underlay.enabled` in `channels/<channel>.json`, with that channel's own argument beside it in `reason`. The grounds belong to the channel and are not restated here, because a copy of them here goes stale silently: the reason on `example-film` was rewritten by `CF-0189` once `CF-0181` cancelled the position the old wording leaned on, and the sentence that used to stand in this paragraph was still repeating it. So **prove this layer on a test config**, never by editing the real channel file: copy the config, flip the switch in the copy, point `FACTORY_ROOT` at a root whose `shared/inserts/loops/` has entries — the real one has none, which is `library_empty`, a fact and not a defect (CF-0115 filled `shared/inserts/memes/` with 101 entries and stopped there; `shared/inserts/loops/index.json` still carries `entries: []`) — and run from there. That is what `work/cf0127-sample/` is, and `tests/test_underlay_wiring.py` builds the same thing in a temp dir. Every manual run of any of this gets `RUNLOG_BATCH=$(mktemp -d)` in front of it (Run accounting above): a bare run resolves a batch out of the paths in argv and writes events into a real batch it was only reading.

**The record.** `plan["underlay"]` on every plan — `{applied, reason, entry, path, media, treatment{audio, fit, loops_needed}, inserts[], library{}, note}` — and, only when a loop was applied, `plan["secondary_source"]` (`{kind: "clip"|"still", src, muted, loop, fit, loops_needed, object_fit, span}`, the prop the component draws) plus the band in `plan["layout"]`. `reason` is a closed list: `applied | layer_disabled | library_empty | all_skipped | file_missing`. In `05-video-editor.json`, `videos[].underlay` carries `{applied, reason, id, file, treatment, library, note}` and one provenance record per file placed or skipped goes to `videos[].inserts[]` with `layer: "underlay"`, beside the meme's, the sound's and the proof's — each layer replaces only its own on a rerun, and a plan that ran this layer answers for it, applied or not. `build_render_plan.py` prints one `UNDERLAY: ...` line; put it in the report the way you put the others, including the empty case — a video with no underlay is a fact, not a silence, and never a failed video.

### Plan built before the handoff (CF-0411)

The Content Researcher no longer hands over a script this stage has not built a plan from (the user, 2026-09-28, after `example-film/2026-09-27T0929Z` lost 3 of 5 scripts here after the voice was paid for: Backrooms at 3.8 blocks/min against a predicted 17.72, Wolfhame's 55 free shots all refused by the cut-clip gate). In its stage, after the text gates, it runs `scripts/plan_check.py check <batch> --script-id <id>` - this stage's own commands, in `<batch>/work/<slug>/`, stopping before `render_video.py` - and on a refusal edits **only the anchors** and runs it again (1-2 rounds; the voice is not paid again while the text is unchanged, and `text_changed` in the verdict says when it was). What it leaves behind is exactly what you would have built: `voice.wav`, `narration.txt`, `words.json`, `anchors.json`, `order.json`, `storyboard.json`, `clips/`, `plan.json`, plus `plan_check.json` (the verdict: `assembled`, `refusals[]` by block and anchor, the text and anchor hashes it was built from) and, when it did not assemble, `plan_check.refusal.json`. Older rounds are under `plan_check.rounds/`.

Step 0b reads it. A reused plan is rendered and checked (steps 7-8) and recorded (step 9) like any plan of yours - the attempt cap, the degradation loop on `qc_render.py`'s flagged blocks and the metadata are unchanged; a `--degrade-block` rebuild after QC reruns `build_render_plan.py` on the same storyboard as always. A script refused there is not yours to rescue: the writer already spent its rounds on the anchors, and the refusal names the blocks and anchors for the report. You are not given the right to edit anchors in this stage - that stayed with the writer (CF-0140); the check moved the loop to the one role that may.

### Procedure

0. **Open the stage** — `export RUNLOG_BATCH=...` and `"$RUNLOG" stage-start video-editor` (see Run accounting above), before the first script of the invocation. Invoked with `mode: new-only`, the scripts below are only the ones **Mode `new-only`** above lists, and every metadata call carries `--new-only`. In the full mode the scripts below are only the ones `.venv/bin/python scripts/pending_scripts.py <batch> --first-pass` lists (CF-0902): the scripts of `03` whose `04` row clears them by the same rule - `clear`/`caution`, or `review` with a `publication_hold`; never a `contribution_check` `block` (the claims gate's `claim_unsupported` is one); never a script `04` has no row for. Its stderr names each script it held back and why; a held-back script is not yours - `04` is its record, so nothing goes into `05` for it. `render_video.py` holds the same line mechanically: a plan whose script `04` does not clear exits 5 with `NOT CLEARED` before any attempt (batch `example-film/2026-10-30T1033Z` rendered pine-park a minute after the claims gate blocked it).
0b. **Ask whether the writer already built this script's plan (CF-0411)** — for every script, before step 1:
   `plan_check.py reuse <batch> --script-id <id> --index <shots.json> [--index ...]`, with the same cleared `--index` list step 3 would use.
   **Exit 0 `REUSE`** — the Content Researcher ran this stage's own steps 3-6 (`plan_check.py check`: TTS, length, alignment, spec, resolve, plan - no render) and the plan was assembled; the text, the anchors and every artifact are the ones it checked, and every source the plan uses is in your cleared list. Do **not** synthesize, resolve or build again - go straight to step 7 with `work/<slug>/plan.json` (the slug is in the line). **Exit 2 `REFUSED BEFORE THE RENDER`** — the plan did not assemble there (`pattern_ceiling`, a `background`/`typographic` block, the cut-clip gate, an `absent` anchor, pictures over the still share (`still_share`, CF-0418), ...) and the writer's anchor rounds did not fix it: do not render it and do not rebuild it; its refusal is already on disk (`work/<slug>/plan_check.refusal.json`, `before_render: true`) and `write_batch_metadata.py <batch>` carries it into `refusals[]` like your own - put the line in the report. **Exit 3 `NO PLAN CHECK`** (every batch and rebuild older than CF-0411) or **exit 4 `STALE`** (the script, an artifact, or the cleared pool moved since the check) — the procedure below exactly as before; on a stale check the voice is usually still reusable, but that is the writer's tool's call, not yours. See **Plan built before the handoff** below.
1. **Load the script** — `hook`, `scene_direction`, `commentary`, `payoff`.
2. **Restructure the narration for prosody** — short sentences, `...` for a beat, `—` for a parenthetical, numbers spelled out. This matters more than voice choice.
3. **Ask the pool whether it can picture this script — before you pay for the speech** (CF-0140):
   `script_anchors.py preflight <batch>/03-content-researcher.json --script-id <id> --index <shots.json> [--index ...] --out work/<slug>/anchor_preflight.json`.
   **`--out` is not optional in a batch** (CF-0282): the report is where the warning record is written beside (`work/<slug>/anchor_preflight.warning.json`, CF-0330), and `build_render_plan.py` reads it from that directory into `plan["warnings"]`; a preflight run without `--out` can only say on stderr that nothing was recorded.

   **The preflight asks the Researcher's text gates first** (CF-0356, `scripts/text_gates.py`). A rebuild copies `03` byte for byte, so a script written before a text gate existed reaches this stage with no record of it — `everyday-sorcery-2` (`pipeline/rebuilds/2026-09-23T1344Z`, written 2026-09-15) carried no `anchor_cadence` at all and its 15.3 s tail after the last anchor was found by `build_render_plan.py`, after the voice. Now, before the pool is asked: a script whose record carries the reading this stage depends on (`anchor_cadence.layout`) with the gate's own `pass` goes on and nothing is run; otherwise the preflight runs **the Researcher's own gate** (`check_anchor_cadence.py --script-id <id> --out work/<slug>/text_gates.check_anchor_cadence.json`, read-only, never `--write`) and judges its fresh record the same way. A gate that does not pass is exit 2 — `SCRIPT DID NOT PASS THE TEXT GATES: do not synthesize` — with the gate's own sentence (the `tail:` remedy, the `anchor needed` address) in `work/<slug>/text_gates.json` and a refusal `work/<slug>/text_gates.refusal.json` (gate `text_gates`, code `thin_scene`): run `write_batch_metadata.py <batch>` as for any refusal here, and the script goes back to the Content Researcher — do not reword it yourself. A gate that could not judge is exit 1 (the environment). The list of gates is `text_gates.REQUIRED`, judged only while the Researcher's SKILL step table still lists the gate; the record key and the `pass` action are read from the gate's source, not copied. **Since CF-0370 the list also asks `block_capacity.picture_band`** (the pattern's block band counted in pictures, CF-0365): it is judged by its own action — `pass` and `note` go on, `reject` is the same exit 2 — never by the record's, which is usually `warn` (CF-0330). A script older than that reading goes on with a note (`not_recorded`): the gate replays the pool from the coverage preflight's `--reports`, which this stage does not have, and the resolver now budgets the `even` chain under a drawn block-count top itself (a capped segment holds its last picture as a `held_frame` still instead of chaining past the top; `rhythm.block_band_cap` in the storyboard), with `pattern_ceiling` standing after it.

   **CF-0330 (the user, 2026-09-23): an uncovered pool is a warning, not a stop.** When the pool does not cover every anchor the preflight prints `ANCHORS NOT COVERED - WARNING, the script goes on [pool_too_thin/anchor_preflight]`, writes the warning (the counts, the floor, and for each uncovered anchor its phrase, cause and best offered score) and **exits 0 — synthesize and go on**. An anchor that still finds nothing at resolve time becomes a block on the procedural rung, which warns in its turn (see the ladder above). The paragraphs below describe what the preflight measures and how it used to refuse; wherever they say "refusal", "exit 2" or "hand back" about the pool, CF-0330 replaced that with the warning. Exit 2 is left only for a script with no `visual_anchors` at all.

   **A `weak` anchor counts as uncovered here** (CF-0290; a warning since CF-0330) — an anchor the pool ranked candidates for and whose best one is under the similarity floor. It used to pass with a note, on the reading that the resolver would use the frame anyway; the resolver does not any more, so passing it would buy a voiceover for a block that will have no picture. `weak` and `absent` keep their separate names because the remedy differs: `weak` wants footage that *depicts* the phrase (or the phrase rewritten), `absent` wants footage that survives the usability gates.
   The `--index` list has to be **exactly** the one step 4's `resolve_anchors.py` will get for this video — the same files, no extras "to be safe": the answer is only about the pool you actually resolve against, and that pool is regularly **narrower** than the batch's, because compliance pass 2 (`04-compliance-checker.json`, already on disk when you start) clears only some of the fetched sources. That is why this run is not a duplicate of the Content Researcher's own gate: it passed there against every fetched source. No `--min-score`, no `--top` — neither is settable here, both sides run on `resolve_anchors.py`'s constants.
   **An all-graphic script has no `--index` at all (CF-0814).** When every anchor places one of the script's own graphics (`graphic_id`, CF-0689/CF-0806 - the writer's `anchor_coverage_pool` says `anchors: 0`, `indexes: []`), the cleared list is empty and is passed empty: `plan_check.py check|reuse`, `script_anchors.py preflight`, `resolve_anchors.py` and `build_render_plan.py` all run with no `--index`, the plan is built from the script's `graphics[]` alone, and the pool's gates have nothing to measure (`plan_check.json` carries `no_pool: true` and a `no_pool` note). An empty pool under an anchor that asks the pool (a `phrase`, no `graphic_id`) is still an error - "which pool is it?" - in all three tools; Tech `2026-10-19T0844Z` lost both its scripts to that error raised on an all-graphic script.
   **(Before CF-0330) Exit 2 meant do not synthesize.** The script goes back to Content Researcher with the report: the `absent` anchors with their `cause`, the contention line, and each anchor's `samples` — the shots the pool *can* show, which is what a rewrite aims at. Do not reword a phrase to make it pass (the preflight answered for the writer's wording, and yours has never been checked by anything), do not resolve anyway and let the holes fall down the CF-0137 ladder: that ladder is for a block that could not be filled once a plan exists, and spending the synthesis, the plan and the montage on a script already known to have a hole is exactly what this task removes. Exit 1 is the environment (a stale caption-band cache, an unindexed source) — fix what it names and ask again; it says nothing about the script.
   **(Before CF-0330) A refusal here was a record, and you owed the batch one command for it** (CF-0282) — today the same numbers go into the warning instead. Exit 2 writes `work/<slug>/anchor_preflight.refusal.json` beside the report — gate `anchor_preflight`, funnel code `pool_too_thin`, the counts it refused on (anchors, distinct usable samples, anchors with no picture, the sources judged) — and prints `REFUSAL RECORDED [...]`. **Run `write_batch_metadata.py <batch>` before you move on to the next script**, so the refusal is in `05-video-editor.json` → `refusals[]` while you are still in the batch: without it the root's funnel reads the script as `not_built` (the observer's guess about a stage that said nothing) instead of under this stage's own code. That is what `example-film/2026-09-18T1058Z` shows for `lf-2026-09-18-003-script1` — 23 anchors, 7 distinct samples, refused out loud, and `not_built 1` in the run summary. Put the `REFUSAL RECORDED` line in the report too.
   Then **synthesize voiceover**, then **gate its length** (`narration_length.py`, CF-0087) before going further:
   `narration_length.py work/<slug>/voice.wav --channel <channel> --script <batch>/03-content-researcher.json --script-id <id>`.
   Over the target (55s) but at or under the ceiling (60s) — `NARRATION OVER TARGET`, logged, carry on. Over the ceiling — exit 2: stop here, no anchors, no footage; hand the script back to Content Researcher with the voice length and the `NARRATION ESTIMATE` delta so the text gets cut, don't render an over-length video and catch it later. **That exit also writes `work/<slug>/voice.refusal.json`** (CF-0282 — gate `narration_ceiling`, code `held_back`, the seconds it measured), so the same command applies here: `write_batch_metadata.py <batch>` before the next script. It needs the `--script-id` above to key the record on; run without it and the gate says `REFUSAL NOT RECORDED` and writes nothing. Then **align words**.
4. **Take the anchors from the script** (CF-0140 — you no longer write them; see Anchoring above):
   `script_anchors.py spec <batch>/03-content-researcher.json --script-id <id> --words work/<slug>/words.json --out work/<slug>/anchors.json`.
   It copies `scripts[].visual_anchors[]`: `phrase` **verbatim**, `word_index` = the first word of `beat_text` in the alignment, `side` as written. **You may not add an anchor and you may not reword one** — a phrase you improved is a question the preflight never answered, and you are back to anchoring blind. A script that needs different moments goes back to Content Researcher; that is cheaper than everything downstream of here. An anchor whose `beat_text` is not in the voiceover is **dropped** by the script and never given a guessed index — put every dropped line in the report, and read *which* drop it is, because they call for opposite actions (CF-0235): `ANCHOR DROPPED [beat_missing_in_script]` means the narration does not say those words either and the script goes back to the writer; `ANCHOR DROPPED [beat_unmatched_in_alignment]` means the script says them character for character and step 2's restructuring or the forced alignment lost them — ours to fix, and the writer is owed nothing. Each line carries the coverage in the script, the coverage in the alignment and the nearest stretch actually heard, so the report can be checked rather than believed. A script with no `visual_anchors` at all, or one whose anchors all drop, exits 2 and goes back: writing them here yourself is the pre-CF-0140 behaviour and it makes the preflight guard phrases nobody uses.
   Then resolve with `resolve_anchors.py`, passing `--order` with the pair the rotation assigned
   (see Rhythm above). For a hand-built storyboard instead: This is the one step that is yours to think about rather than execute. One block per unit of meaning, each carrying `word_range`, `intent`, `asset_query`, `asset_kind`, `emphasis_words`.
   **Look at every candidate asset before you assign it.** Not the filename — the picture. The first v3 draft mapped six frames to six blocks by guessing from filenames and got nearly all of them wrong, including one frame that was a screenshot of a YouTube page. A proof is not attached here by hand: `build_render_plan.py --script` runs the proof layer on the finished blocks (see Proof placement above).
5. **Acquire assets.** `fetch_footage.py` for clips (prefer the rights holder's own channel; when you cannot, `--official` stays off and Compliance Checker will see it). `prepare_clip.py --auto-crop` to cut segments — always auto-crop, official clips routinely carry their own burned-in subtitles and stacking ours on top was a real v1 defect.
6. **Build the plan** (`build_render_plan.py --channel <channel> --estimated-seconds <narration.estimated_seconds> --script <batch>/03-content-researcher.json --script-id <id>`). The last two run the proof layer (see Proof placement above), the meme layer (see Meme placement above) and the sound layer (see Sound placement above) - without them the plan carries the empty pairs and no insert, so pass them on every build. It runs the asset gate itself and **refuses to write a plan containing a rejected asset**. Substitute a candidate and rerun; after two attempts, drop that block a rung with `--degrade-block` (see Degradation above) — not the whole plan. It also plans the end card last (see The end card above): `--channel` is what supplies the phrase and the 3s constant, and a channel whose stance file cannot answer refuses the plan with `END CARD NOT PLANNED`, exit 2 - fix the channel, do not type the phrase anywhere. It also runs the underlay layer (see The underlay in the second plane above) on `--channel` alone, before the block loop rather than after it, because an applied underlay changes the frame the blocks are cropped against; on a channel with the switch off - which is every channel today - it writes `plan["underlay"]` with `layer_disabled` and changes nothing else. It also runs the two-source gate (see The two-source gate below) on the finished blocks, before any of the expensive layers: today's channel is in `measure` mode, so it writes the verdict and one stderr line and refuses nothing - copy that line into the report. It also re-checks step 3's narration-length gate against the same 55s/60s lines (`NARRATION OVER TARGET` logs and writes the plan; over the 60s ceiling refuses to write one) — same story either way, no new decision to make here.
   **Every gate here that refuses the whole plan leaves a record, not just stderr** (CF-0254). The ones that still refuse — `UNDER-FLOOR PICTURE` / `PATTERN CEILING BROKEN` only when the plan's score is under N (CF-0433; see "The score of the plan"), narration over the ceiling, rejected assets, the two-source gate in `enforce` (see CF-0330 below: the user's decision is `measure`, and the switch is the channel's), the blooper borders, a proof request pointing at nothing, `SOURCE BADGE NOT PLANNED`, `END CARD NOT PLANNED`, `PICTURES OVER THE STILL SHARE` (CF-0418), `SCORE UNDER THE THRESHOLD after the plan's last gates` (CF-0794, sidecar `plan.score.refusal.json`) — each print `<GATE> - plan not written:` as they always did and then write `work/<slug>/plan.refusal.json`: `{script_id, reason_code, reason}` with the gate's own sentence, plus the gate id and the time. You do not carry that file anywhere; step 9 finds it. What you do carry is the last line the gate prints, `refusal -> <path> (<code>: <script_id>)`, into the report.
   **`UNDER-FLOOR PICTURE` — gate `unresolved_anchor`, funnel code `pool_too_thin` (CF-0290; since CF-0433 a price, `score.low_similarity`, and a refusal only when the plan's score is under N — the rest of this paragraph is the history).** The storyboard says in its own `unresolved_anchors` that a block was filled below the similarity floor: a frame of something else went on screen under the phrase, which DoD ролика item 3 forbids outright (`example-film/2026-09-18T2232Z`/delver.mp4 — two of ten blocks played Tom Carver in an interview chair under a rotunda podium and a wheelchair on a film set, and it shipped). **The answer is material, not a rebuild, and not a flag.** Rebuilding the plan changes nothing: the picture was chosen in step 4, not here. Either the pool widens for those phrases or the script's anchors are rewritten against what the pool does have — `anchor_coverage.py` (step 3) names which anchors and with what evidence, and a re-resolve of the script in this checkout is what repairs an old storyboard, because `resolve_anchors.py` will no longer offer such a candidate to a block at all. Do not reach for `--score-floor`, `--min-score` or `--degrade-block` to get past this line.

7. **Render** (`render_video.py`). This begins the video's attempt (see The attempt cap above). **Exit 3 with a `NEEDS-YOU` line means the cap is reached (or, `render_broken`, the tool failed the same way twice before the first frame; or, `render_stuck_on_asset`, the same render failure twice in a row - CF-0518): stop this video, put the line in the report, go to the next one.** **Exit 4 with a `SCORE F` line (CF-0434) means the video's score log is already under N: nothing was rendered and no attempt spent - stop this video, put the line in the report, and skip step 8: there is no mp4 to check.** The refusal `work/<slug>/plan.score.refusal.json` (code `score_below_threshold`) is on disk - the stage that stopped the video wrote it, and if none had, `render_video.py` writes it on this exit (CF-0794); the line names it. Go straight to step 9 for this video with **no `--video`** - the call finds the sidecar by itself; do not pass `--refusal` for it. After a good render the summary adds `score after render: <line>`, or a `SCORE F after render` line - run step 8 anyway (it ends the attempt) and stop there. Read only the summary it prints; the render log is on disk.
   **The render plays the mix, and builds it when nobody did (CF-0423).** Do not pass `--audio` on the normal path: without it `render_video.py` plays the mix recorded on the plan (`audio.bed.mix`) or, when there is none - every freshly built or rebuilt plan - runs `build_soundtrack.py` itself against the channel the plan was built for (`audio.channel`, or the channel its `audio.bed_rotation` names), into `work/<slug>/mix.wav`, inside the same attempt. The summary says which: `mix: built ... for channel ...` with the bed and its place in the rotation, or `mix: ... (recorded on the plan ...)`. Until this task the mix was a step you had to remember between 6 and 7, and from `2026-09-23T1722Z` to `2026-09-27T1757Z` it was forgotten on every video but one: six videos shipped the bare voice with dead air between phrases and no lofi bed. A mix that fails ends the attempt as `render_failed` (`no render: mix failed: ...`). `--bare-voice` renders the voice alone for a diagnostic and `qc_render.py` fails it; `--audio <file>` still overrides for a hand-made mix.
8. **Check the render** (`qc_render.py`) - only a render that exists: never for a video step 6 or 7 refused (CF-0794). On a missing, empty or unreadable file it says so in one `QC: ERROR:` line naming the file and exits 2 (4, with the `SCORE F` line and the refusal path, when the score had already stopped the video); that is your call naming the wrong file, not a QC verdict. It ends the attempt, records the `qc` stage of the score log (see The score log and the early stop) and prints a summary — the frozen blocks with their motion scores are in it (`--json` when you need the whole result): any indices there feed straight back into step 6's `--degrade-block`, one flag per index, and only those blocks get rebuilt — on the same storyboard with the same flags, so the render is a QC degrade and not an attempt (CF-0415, The attempt cap above). Loop 6→7→8 on just the flagged blocks until clean, until zero clip/still blocks survive (see Degradation's escape valve), until step 7 refuses with `NEEDS-YOU`, or until QC exits 4 with `SCORE F` (CF-0434: the score is under N, the video goes no further and no hint is given) — whichever comes first; the third is not a failure of yours to work around. Also read `held_source_blocks`: those read as stills too, but the clip they were cut from is a still in the same place — held footage, not a hung render (CF-0004). They are *not* failures and must not be degraded; the reason is copied into the QC notes so the relaxation is on the record.
9. **Write batch metadata** to `05-video-editor.json` — `style_requested`/`style_delivered`, `degradation` (per block: index, from, to, reason), `pattern_requested`/`pattern_delivered`, `rhythm_requested`/`rhythm_delivered`, `proof_requested`/`proof_delivered` with the proof layer's provenance under `proofs[]` and `inserts[]` and `proof_capture_telemetry` when a page was fetched (see Proof placement above), `meme_requested`/`meme_delivered` with this layer's provenance under `inserts[]` (see Meme placement above), `sound_requested`/`sound_delivered` with the sound layer's provenance under the same `inserts[]` (see Sound placement above), `underlay` with the second plane's own provenance under the same `inserts[]` (CF-0127: applied or not, and why - see The underlay in the second plane above), `cadence` (block count and every block length as numbers), `score` / `score_line` (CF-0434: the video's score log and its one line), `end_card_delivered` (CF-0117: the card's seconds, where it started, the phrase and the stance file it came from, the variant and the logo), `two_source_gate` (CF-0118: how many independent footage sources are on screen, which ones, and in which mode that was judged), `footage_credits` (CF-0664: one row per judged source on screen - licence, credit or `credit_missing`, `attribution`, `on_screen`/`where`, `share_alike`, `license_url`, `source_url`, `overlay`; `[]` on ExampleFilm, copied from the plan), `own_captures` (CF-0567: our own recordings on screen - page, host, the Space's licence, blocks; `[]` when none), `proof_quote_cap` (CF-0567: the vendor quotes against the caps; `applies: false` on a channel without `proof_quotes`), `qc`, `duration`, `assets`, and (CF-0098) `attempts[]`/`attempt_cap`/`attempts_exhausted`/`needs_you` read off the ledger beside the plan. Mandatory even on a clean run, and on a rebuild (CF-0416, see Rebuild above).
   **A cosmetic QC refusal is admitted to the frame judge by a field, never by `qc.passed` (CF-0416).** `qc.failed_rules` names the rule of every failure, in order (`meme_caption_blank_blocks`, `panel_cut_blocks`, `subject_offscreen_blocks`, `frozen_clip_blocks`, `background_hole_blocks`, `repeated_pictures`, else the gate's short name: `caption`, `bed`, ...). The channel's cosmetic list is `channels/<id>.json#video_editor.qc_cosmetic_rules` (default `["meme_caption_blank_blocks"]`; a hard-list rule - stream, frame, length, black, silence, clipping, burned-in text - or an unnamed failure is never cosmetic, and is dropped with a warning), copied onto `qc.cosmetic_rules`/`qc.cosmetic_rules_source`. When every failure is on that list the record carries `judge_admitted_despite: [<rules>]` and stderr says `QC FAILED (cosmetic, admitted to the frame judge)`; `qc.passed` stays `false`, `needs_you` stays what the ledger says. The frame judge takes such a video as a candidate. A video that failed on anything else has no field, and still nobody writes `qc.passed: true` into a 05. The finding itself costs `score.meme_caption_blank` per block once the price table carries that rule.
   **The same call keeps the channel's retired shots (CF-0397, CF-0443).** `pipeline/<channel>/retired-shots.json` takes the shots of a video that goes to the user - the frame judge takes it (`qc.passed` with no `needs_you`, or `judge_admitted_despite`), `score.passed` is not false, and the judge's `06` (once there) did not reject it; a QC-failed, NEEDS-YOU or tier-F video keeps its shots on offer for the next videos, and stderr says `shots not retired (CF-0443): <slug> - <why>`. Every write also reads the acceptance log - `write_batch_metadata.py --acceptance-log PATH`, else `$ACCEPTANCE_LOG` (the file itself; tests point it at a temp path, CF-0523), else `<root>/publish/acceptance-log.json`: a video the user rejected gives its shots back (`returned{}` in the registry, with the reason, stderr `shots returned to the pool`), an accepted one keeps them retired. Nothing to do on your side - put a `not retired` / `returned` line in the report when the call prints one; never edit the registry by hand (`scripts/retired_shots.py backfill` rebuilds it).
   **Call it per video, as each video finishes** — `write_batch_metadata.py <batch> --video <script_id> work/<slug>/plan.json videos/<slug>.mp4` — and do not save the call up for the end of the batch. **The three values after `--video` are three separate words** (CF-0778): batch `example-tech/2026-10-16T0839Z` looped over `"<script_id> <slug>"` pairs and split each with `set -- $pair` - zsh does not split an unquoted parameter, so `$1` carried both and `$2` was empty, and four calls went out as `--video "lf-...-001-script1 homeview" <batch>/work//plan.json <batch>/videos/.mp4`. Write the call out per video with literal values, or, in a loop, split explicitly (`sid=${pair%% *}; slug=${pair#* }`). The script refuses such a call (exit 2, `METADATA: ERROR: ... contains whitespace` / `... has an empty segment` / `... does not exist`, nothing written) - fix the call and run it again; it is not a crash of the stage. Since CF-0030 the file merges by `script_id`: the record for the video you just wrote replaces its own record whole, every other record in the file is kept verbatim and in place, a new id is appended, and each call prints `METADATA: merged N existing + M written (K replaced)` on stderr so you can see what the file now holds. Nothing has to be written into `work/<slug>/05-video-editor.json` and merged by hand afterwards (that was the CF-0030 workaround of `2026-09-03T2037Z`), and an orchestrator's `merge_note` in an older file survives the next call untouched. A file that cannot be parsed is a hard error, not an overwrite — fix the file; `--replace-all` (write the whole file from this call alone, dropping every other record) is the deliberate way past it and says on stderr what it dropped. This file is the only source the assignment registry recovers its production columns from (CF-0049): a video missing from it reads as never produced.
   **You owe this file even when the batch produced no video at all** (CF-0254). The old convention here said the opposite — a refused video has no plan and no mp4, so it has no entry, so a batch whose every script was refused got no `05-video-editor.json` written. That is what happened to `example-film/2026-09-16T2148Z`, whose one script was refused at the source badge gate, and the root's funnel read the batch as a loss with **no explanation at all** (`unexplained`, SILENT), which DoD 1.4.4 item 1 forbids. The convention is now: **a refused video has an entry in `refusals[]` and no entry in `videos[]`.** So end the stage with `write_batch_metadata.py <batch>` — `--video` is optional and you pass one per video as before, none when there were none. The call finds every refusal sidecar under `work/<slug>/` — `plan.refusal.json` from step 6, `plan.score.refusal.json` from the score's early stop (CF-0434; a log under N whose stage did not write it gets it written by this call, off the log as it was stored, `METADATA: score refusal written (CF-0794)`), and since CF-0282 `anchor_preflight.refusal.json` and `voice.refusal.json` from the two gates of step 3 that refuse a script before it ever reaches a plan — writes them into `refusals[]` (`{script_id, reason_code, reason}` plus the gate and the time), prints one `REFUSED (no video): <script_id> [<code>/<gate>] <reason>` line per refusal, and stops with an error if there is neither a video nor a refusal to record — an empty file claiming a batch produced nothing *and* refused nothing is the one thing it will not write. A script that was refused on one attempt and rendered on a later one is **not** refused: the video record wins and the stale refusal is dropped, said out loud as `refusal dropped: <script_id>`. `--refusal <path>` names one explicitly, for a plan built outside `<batch>/work/`.
10. **Report back and send the file.** The human has to actually watch it. Then, as the very last act, `"$RUNLOG" stage-done video-editor --batch "$RUNLOG_BATCH" --note "<N> videos rendered, <R> refused before the render, <K> needs-you, <A> attempts"` (see Run accounting above) - `RUN_LOG.txt` is rendered from the events, not written by you.

### The gate

Brak the agent can detect must never reach a human. Two gates, and both are hard.

**Before montage** (`qc_asset.py`): resolution floor (default 720px short side); Vision must find a face or a salient object; near-black share under 35%; a focus-aware crop must retain at least 65% of the subject. **With more than one face in the frame, "the subject" is a person (CF-0292):** the window is built around one face rather than centred between them, and the 65% is the share of the *best-served* face the delivered window keeps — a window on the gap between two people scores near zero and the shot is refused for `cover`, where the union-box measure it replaced reported 0.895 for a frame with no face in it (`2026-09-18T2232Z`/delver.mp4, the block the viewer rejected as "only the hosts' legs"). Nothing changes for one face, for a saliency box, or for a group the window holds whole.

The floor is a parameter, and relaxing it is *recorded*, never hidden — a source below it still renders, but the plan carries a note naming the upscale factor.

A gate tool that does not answer is a gate failure too (CF-0077). `qc_asset.py`, `smart_crop.py` and the ffmpeg probe-frame grab run under `common.ASSET_TOOL_TIMEOUT_SECONDS` (240 s - above `qc_asset.py`'s slowest honest path, two Vision requests against a wedged worker at 5 + 60 s each before the local fallback) and `PROBE_FRAME_TIMEOUT_SECONDS` (60 s); `smart_crop.py` is only reached when `qc_asset.py`'s verdict carries no `framing` (CF-0649: the gate already computed it, a second cold process per block was most of a plan's time); past the ceiling the tool is killed and the asset is rejected on the ordinary `ASSETS REJECTED` path with a failure line naming the tool, the asset and the ceiling (`failed: ["tool_timeout"]`), and a stderr line saying which tool hung on what. A probe that comes back with **no frame** - the clip gone, empty, unreadable or shorter than the point asked for - takes the same path (CF-0483): the asset is rejected with `no_probe_frame` and one line naming the clip, the offset and why (`[build_render_plan] no probe frame out of <clip> at <t> s (<why>) - treated as a gate failure`), never a traceback that takes the whole plan down; substitute a candidate as for any rejected asset. A hang looks like "still computing" and eats the window; a rejection costs one substitution. `tests/run_tests.py` keeps the same rule for the test pool: a file past `RUN_TESTS_FILE_TIMEOUT` (default 600 s, `0` = no ceiling) has its process group killed and is reported FAILED by name with the ceiling.

**After render** (`qc_render.py`): resolution matches the request; picture within 0.25s of what the plan says it should be (`duration.composition` - the narration *plus* the end card, CF-0117; the voice alone on a plan with no card); no black run over 0.4s; no silence over 2.5s; no audio clipping; every block declaring moving footage actually moves; and the renderer still supplies what makes captions legible.

Two of those are asked twice, and for the same reason: the finished file alone cannot tell a deliberate thing from a broken one. A motionless block is checked against the clip it was cut from (CF-0004) — held footage, not a hung render. A silence over the limit is checked against what the plan declared (CF-0050): it is excused only when the plan says this video opens on a cold frame, the silence really is at the head and no longer than declared, **and a measurement of the frame under it shows a picture is actually there**. A black frame under a silent lead fails both gates at once, which is the right answer — that is a video opening on nothing. Every excusal is written into the QC notes with the measurement that bought it, exactly as CF-0004's are.

That last one guards the design, not the pixels, and the reason is worth keeping. **Caption legibility cannot be measured from a rendered frame** — every region you could sample contains the captions themselves and they dominate it. Band luminance, edge density and band-versus-frame darkening were each tried and each was contaminated by the glyphs; the band reads as *busier* than its own source footage, because the letters are the edges.

It does not need measuring. White fill with a heavy black stroke floors contrast at **4.61:1 against any background luminance** — worst case at luma 117, where the fill's and the stroke's contrast meet — which clears WCAG's 3:1 bar for large text. No footage can break it. A first attempt at a contrast gate was therefore decorative: its threshold sat below the metric's own floor, so it could never fail.

What can break legibility is an edit to the renderer. So the gate checks stroke width and type size as drawn (the theme's numbers scaled by `captionBand.js` `CAPTION_SCALE`), and fails when either is weakened. There is no scrim to check since CF-0394 (2026-09-25): the user took it out along with the old large band - small type, at most two lines, fixed just above the bottom dead zone, and a meme or proof card fitted above the band rather than the band rising over it (`docs/on-screen-rules.md`, "The caption band is fixed"). The measured contrast is still recorded on every run — not as a gate, but so erosion is visible in the record.

Each check exists because something shipped. The near-black check in particular is there because Vision cheerfully identified the thumbnails in a YouTube page screenshot as a salient object; saliency alone does not recognise junk.

### The footage credit (CF-0664)

`build_render_plan.py` reads each source's rights record the Footage Indexer wrote (`01b-footage-index.json` `fetched[].rights`, found beside the plan or named by `--footage-index`; else `<id>.shots.json` `source_rights` of the pool / `--index`) and writes `plan["footage_credits"]` (one row per **judged** source the finished blocks show, in order of first use) and `plan["credit_overlays"]`: a small credit (`© ESA/Hubble · CC BY 4.0`) over the blocks of a source whose origin wants it on the picture (`on_screen: true` - ESA, ESA/Hubble, ESO), top corner opposite the watermark, the theme's `muted`, off under the end card. Nothing is invented: an unjudged source (ExampleFilm) or one with no record gets neither; a `credit` from `footage_origins` is the origin's rule, not a line - the row says `credit: null` + `credit_missing`, the overlay names the origin and the licence. One stderr line per overlay, `FOOTAGE CREDIT <from>-<to>s on block(s) [...]: '<text>'` - copy it into the report. The frame judge's pack lists the credit as ours (`ours_on_screen.footage_credits`).

### Own capture and vendor quotes (CF-0567)

ExampleTech's footage is the factory's **own screen recording** of the tool the news is about (the root's `docs/tech-footage.md`; the «демо» pattern), with at most a short **quote** from the vendor's official channel beside it. Three things in this repo carry that.

**The recorder** - `scripts/capture_tool.py` (policy) + `capture_tool.mjs` (Remotion's chrome-headless-shell over CDP, `Page.startScreencast`):

```
.venv/bin/python scripts/capture_tool.py <https url> <out_dir> --channel <id> \
    [--steps steps.json] [--space <owner>/<space>] [--max-seconds 30] [--id <id>]
```

Before any page is opened it refuses (exit 1, `reason` in the JSON): `not_https`; `host_not_listed` / `host_closed` (the root's `footage_licence.capture_allowed(url, footage_origin(channel))` - only a `capture_hosts` host whose `use` is `capture`); `sign_in_host` (any host whose `sign_in` is true, whatever its `use` - signed-in capture is CF-0688, not this recorder); `robots_disallowed` / `robots_unread` (the exact host's robots.txt re-read for the exact path: the root's `source_policy.check_url` - closed to `*` or one of Anthropic's agents, an unreadable file is not permission - and the factory's own User-Agent); for a Space (`hf.space`) `space_not_named` (pass `--space <owner>/<space>`; it must be the app host's own name), `space_card_unread`, `space_not_public`, `space_no_licence` (the public card `https://huggingface.co/api/spaces/<owner>/<space>`, no key, must name a `license`); `bad_steps`. After the take, a page that ended off the capture host is `redirect_off_host` and nothing is kept.

Steps are a JSON list, played in order, nothing else is done to the page (no injected text, no hidden overlays, never a password field): `{"do": "wait", "seconds": 2}`, `{"do": "scroll", "by": 600, "seconds": 1.5}`, `{"do": "click", "selector": "#run"}`, `{"do": "type", "selector": "textarea", "text": "a red fox"}`, `{"do": "press", "key": "Enter"}` (Enter | Tab), `{"do": "wait_for", "selector": ".result img", "seconds": 20}`. A take is at most `CAPTURE_MAX_SECONDS` (60 s) whatever is asked (default 30 s), plus a 1 s hold of the result; 540x960 CSS px at 2x, assembled at 30 fps into a 1080x1920 H.264 mp4 - the delivered frame, nothing to crop.

Out: `<out_dir>/own_capture-<id>.mp4` and the sidecar `<out_dir>/own_capture-<id>.own_capture.json` - `schema`, `id` (`own_capture:<id>`), `file_id`, `file`, `origin: own_capture`, `licence: own_capture`, `found_by: {how: screen_capture, ref: capture_hosts}`, `url`, `final_url`, `host`, `capture_host`, `host_entry` (use, sign_in, the policy's verdicts), `capture_allowed`, `robots` (the read and its verdict, `factory_ua_allowed`, `any_agent_allowed`, `read_at`), `space` (`id`, `licence`, `api_url`, `read_at`; null off `hf.space`), `steps`, `steps_done`, `duration_s`, `max_seconds`, `capped`, `fps`, `width`, `height`, `frames`, `captured_at`, `user_agent`, `channel`, `recorder`. `<id>` is `<page slug>-<UTC stamp>` (`acme-fox-demo-20261011t120000z`). The Footage Indexer ingests the recording as `own_capture:<id>` and keeps the sidecar beside `<id>.mp4` in the pool (its FI step).

**The `own_capture` source kind.** On disk, in clip names and in `shot` keys a recording is `own_capture-<id>` (`_clip_names.OWN_CAPTURE_PREFIX`, read like `nasa-`/`commons-`). It is our footage: no `footage_credits` row and no on-screen credit (`footage_credits.plan_credits`), but the plan keeps the page - `plan["own_captures"]` (`video_id`, `url`, `host`, `capture_host`, `host_entry`, `space`, `space_licence`, `captured_at`, `blocks`, `seconds_on_screen`; `record_from: sidecar | rights | null`, nulls when nothing was recorded, never invented), one stderr line each: `OWN CAPTURE <id> on block(s) [...] (<s>s): <url>`. The frame judge's pack marks every block of a recording (`overlays[].kind: own_capture_ui`, `source.own_capture: true`, `ours_on_screen.own_capture`): the tool's interface text is the footage, not foreign burned-in text - a third party's content the page shows is still judged as usual. The root's frame-judge SKILL reads those fields. **Its text is not refused either** (FI 14c4ff4 marks the recording's shots `source_kind: own_capture`, keeps `burned_text: true` under `usability.exempt`): `entity_guard.refusal()` (CF-0351 burned text, CF-0354 the unanswered card) and `resolve_anchors.text_cut_refusal()` (CF-0275) exempt a shot by its kind - `_clip_names.is_own_capture_shot()`, the `own_capture-` id or `source_kind` - and the storyboard lists every such shot under `own_capture_exempt` with the sentence; every other source is refused exactly as before.

**The two-source gate and own capture.** A recording is not a borrowed source: two recordings of two pages are **not** two sources (`canonical_ids`/`count` hold borrowed sources only; `own_capture_ids`, `own_capture_blocks`, `own_capture_seconds`, `borrowed_seconds` beside them). A video of nothing but recordings is entirely ours - the gate does not apply. A video whose recordings are on screen at least as long as its borrowed footage is not a compilation of anybody's upload and passes, saying so; under that, the borrowed sources are counted as always. Reel and Science plans hold no `own_capture-` id and read exactly as before.

**The proof-quote cap** (`proof_quote_cap.py`, on the final blocks right after the two-source gate). A source is a vendor quote when its rights record carries `role: proof_quote`, or the `footage_origin` of a `proof_quote` official channel (`vendor_official`), or a `channel_id` of one; one quote is a run of touching blocks of the same source. Held to the channel's `proof_quotes`: `[quote_too_long]` (one quote over `max_seconds_per_quote`, 5 s), `[too_many_quotes]` (over `max_quotes_per_video`, 2), `[quotes_over_video_total]` (over `max_seconds_per_video`, 8 s), `[quote_is_the_base]` (quotes more than half of all footage seconds, `never_the_base`) - refused as `PROOF-QUOTE CAP BROKEN`, gate `proof_quote_cap`, funnel `held_back`. A plan of the `demo` pattern whose own recording is not more than half of its footage is refused as `DEMO WITHOUT ITS OWN RECORDING`, gate `demo_own_capture`, `[demo_not_own_capture]`, funnel `pattern_undeliverable`. `plan["proof_quote_cap"]` carries the record on every plan (`applies: false` and nothing read on a channel without `proof_quotes` - ExampleFilm, ExampleScience - and a pattern other than `demo`).

### The two-source gate (CF-0118)

A video whose entire picture comes from one upload is, in YouTube's own words, a "compilation with no original content added" - the thing the policy names as not even eligible for the Creator Pool. Alternating sides (CF-0050) is a *preference* built on the same requirement; this is the prohibition under it, and it is checked before anything is rendered.

**What counts as one source.** Not a `video_id` - the *canonical* source after CF-0080's dedup. Search returns re-uploads, and three uploads of one teaser are one trailer however many ids they carry (batch `2026-09-03T2037Z`: topics 002/004/006/007 each got three uploads of the same trailer; `GyEpwGQIEZw` and `SJVmeJaS44s`, the two sources of the Wren Hollow video, measure at fingerprint distance **1.82** against a duplicate threshold of 12.0 - one teaser, not two sources). `scripts/source_gate.py` holds the whole definition:

- a block's source is the `shot` key (`<video_id>:<n>`) or the video id in the cut clip's own filename, collapsed through the batch's alias table (`01b-footage-index.json` `aliases[]`, `work/footage-aliases.json`, or a plain `--alias-groups` grouping for a batch that predates CF-0080);
- the count is of sources the blocks **use**, never of what the pool offered - a five-upload pool the resolver never reached buys nothing, because what a viewer sees is what the policy is about;
- a block degraded to `typographic`/`procedural` (CF-0031) keeps its `shot` for the rhythm's sake but shows our own type, so its former source is **not** counted;
- a video with no borrowed footage at all (every block typographic - the bottom rung of the degradation chain) is not a compilation of anybody's material: the gate does not apply and never refuses it.

**Two modes, and the channel decides.** `video_editor.two_source_gate` in `channels/<channel>.json`, **default `measure`** when the key is absent (either the bare string, or `{"mode": "enforce", "required": 3}` to raise the floor):

- `measure` - the verdict is written into the plan and the batch record, one line goes to stderr, nothing is rejected, and **nothing is added to `rhythm_shortfalls`**. This is what the channel runs today. A measured gate *records*; it does not return a script, so it produces no deficit: `rhythm_shortfalls` stays CF-0057's list of *rhythm* deficits, which is what the Analyst reads to tell a rhythm that is standing still from one that is missing.
- **CF-0330 (the user, 2026-09-23): this gate is a warning** — `measure`. A measured failure now also writes a warning record (`two_source_gate` / `no_second_source`, the count, the floor, the canonical ids) into `plan["warnings"]`. The mode is still read from the channel file (the factory root's `channels/<channel>.json`), and a channel that still says `enforce` refuses as below until that file is switched back — do not override it with `--two-source-gate` in a batch; report it.
- `enforce` - a plan with fewer than two independent sources is **returned**: `TWO-SOURCE GATE FAILED - plan not written` on stderr, exit 2 (the same path a rejected asset takes), and the machine-readable deficit is written to `work/<slug>/plan.two-source-gate.json` (`kind: "two_source_gate"`, the CF-0057 shortfall shape) - there is no plan file to carry it, and the script has to come back with a deficit you can read rather than a paragraph you have to parse. This is the only mode that produces a deficit record at all, and that file is the only place it lives.

`--two-source-gate measure|enforce` overrides the channel for one run of `build_render_plan.py`; `--alias-groups`, `--footage-index`, `--footage-aliases` say where the duplicates are known from (by default the batch's own `01b-footage-index.json` and `work/footage-aliases.json` are found off the output path).

**Do not flip the default on your own.** Item 3 of CF-0118 is a rule, not a formality: measure first, and if fewer than half the scripts pass, **widen the pool** (Trend Hunter / Footage Indexer - a second independent upload per topic) rather than switching the gate on. Measured over every plan on disk (14 plans, 5 batches), with `GyEpwGQIEZw`/`SJVmeJaS44s` collapsed:

| batch | video | sources used | gate |
|---|---|---|---|
| 2026-08-28T2016Z | corn | 0 (6 blocks, no id in the filenames) | fail |
| 2026-08-30T1759Z | rink-rivals | 0 (6 blocks, no id in the filenames) | fail |
| 2026-08-30T2329Z | coyote-vs-acme | 2 - `H-43VeYGiPM` 16b, `kMsiD1Nky5I` 17b | **pass** |
| 2026-08-30T2329Z | rink-rivals | 3 - `O-H6lLsEsTI` 9b, `UcIvQYYW4PY` 7b, `ADi1iextoUM` 3b | **pass** |
| 2026-08-30T2329Z | leanne | 1 - `H6RXVb_J5J4` 27b | fail |
| 2026-08-30T2329Z | everyday-sorcery-2 | 2 - `Ho10_4IX1jE` 24b, `iSWP2feb4rw` 2b | **pass** |
| 2026-08-30T2329Z | the-long-voyage | 2 - `Mzw2ttJD2qQ` 19b, `f_bKjZeJBBI` 12b | **pass** |
| 2026-08-31T2155Z | amc-leawood-films | no footage at all (12 procedural blocks) | n/a |
| 2026-08-31T2155Z | rapid-reckless-neon-drift | 2 - `6fcoM7Q348Q` 9b, `x9wMFCMXCRE` 3b | **pass** |
| 2026-08-31T2155Z | wren-hollow-lockhart | 1 - `ZZ_urA56pJE` 21b | fail |
| 2026-09-03T2037Z | raygun-sneak-peek (001) | 1 - `pOY-Q5DXfcI` 4b | fail |
| 2026-09-03T2037Z | wren-hollow-christmas (002) | **1** - `GyEpwGQIEZw` 8b (`SJVmeJaS44s` is the same teaser) | fail |
| 2026-09-03T2037Z | clooney-venice-lion (003) | 1 - `W4mvmBXg9Nc` 8b | fail |
| 2026-09-03T2037Z | ink-teaser-cards (004) | 1 - `eokBqEFiVHs` 12b | fail |

Every pair of sources behind a passing plan was checked with footage-indexer's own `source_fingerprint.py --compare`, and all of them come back distinct (15.05 - 29.05 against the 12.0 duplicate threshold; `H-43VeYGiPM`/`kMsiD1Nky5I` at 15.05 on 21 overlapping frames is the narrowest, so coyote-vs-acme is the least comfortable pass on the list). One pair of rink-rivals's three (`ADi1iextoUM`/`UcIvQYYW4PY`) was not measured - that video has three sources and would pass on any two of them.

**5 of 13 plans with footage pass - 38 %** (45 % if the two oldest batches, whose clip filenames carry no source id at all, are set aside as unmeasurable). On the batch the task named, `2026-09-03T2037Z`, **0 of 4 pass**: `004-script1`, which the task expected to be the one survivor, uses a single trailer (`eokBqEFiVHs`) in all twelve of its footage blocks - it is 002 that had two ids on screen, and CF-0080's fingerprint says those two are one teaser. **Under 50 %: the gate stays in `measure` and the pool widens first.** The number to re-run before proposing `enforce` is in the CF-0118 report's `## Полный прогон`.

**In the record.** `plan["two_source_gate"]` and `videos[].two_source_gate` in `05-video-editor.json` carry `{passed, applies, count, required, canonical_ids, aliased_away, mode, blocks_by_source, unidentified_blocks, note}` on **every** plan, pass or fail, in either mode - a plan built before the gate existed reads `passed: null`, never `true`. That record is the whole of the gate's finding: `rhythm_shortfalls`, `rhythm_delivered_fully` and the rhythm deviations stay about the rhythm alone and never mention the gate - a measured gate has recorded a fact, not raised a deficit anyone was asked to fix, and a failing one under `enforce` has already refused the plan and left its deficit in `plan.two-source-gate.json`. (`write_batch_metadata.py` still labels a `two_source_gate` entry `SOURCE SHORT` rather than `RHYTHM SHORT` if it meets one in a plan written by an older build.) Put the gate's line in the report the way you put the rhythm's: how many independent sources, which ones, and which blocks came from where.

### Layout

Named slots with adjustable geometry: `main`, `secondary`, `caption_band`. Named, so the gate and the degradation chain can refer to them. A null `secondary` returns its height to `main` — full-bleed, which is still the default on every channel. Since CF-0127 the slot is filled by the brainrot underlay when the channel switches it on (see The underlay in the second plane above); it is also where a reaction or an ad would go, and what goes in an ad slot is Publisher's business.

**Captions are phrases with the spoken word highlighted**, not one word alone. v2 showed single words ("IT", "ATE", "BITE") and gave the eye nothing to read ahead into.

Watch the stroke when adjusting caption spacing: a 9px text stroke grows each glyph outward by 9px per side and will swallow a flex `gap` under about `0.3em`, gluing words together.

**Safe zones** are the intersection of every platform's UI overlay. One master file serves Shorts, TikTok and Reels; everything meaningful stays inside the intersection. The zones are a parameter, so per-platform variants later are a setting, not a rewrite.

**Duration is a target, not an outcome.** The agent adjusts pacing and shot count toward the requested range; when the script simply has too few words, it says so upward rather than shipping whatever came out. Starting target: 35-60s.

Output resolution and duration are variables everywhere. Vertical is the only format the factory publishes, but nothing is hardcoded to 1080x1920.

## Notes and traps

- **You do not write anchors any more** (CF-0140). They come from the script's `visual_anchors[]`, and `script_anchors.py spec` copies them; the only change this stage makes is dropping one whose words are not in the voiceover. Two things that look like helpfulness and are not: rewording a phrase so it matches something in the pool (the preflight answered for the writer's wording; yours was checked by nothing) and writing anchors for a script that declared none (that is the behaviour this whole task removed, and it leaves no trace in the run). Both go back to Content Researcher instead.
- **The attempt cap is not advice** (CF-0098). `render_video.py` exit 3 + `NEEDS-YOU` is the stage giving up on a video on purpose; the ledger and `05-video-editor.json` record it. Deleting `attempts.json` to get another render is the one thing this section exists to forbid. Logs are in `<batch>/logs/`; if you find yourself reading a whole one, you are spending the tokens the cap was built to save.
- **Remotion caches its headless browser inside the project's `node_modules/.remotion/`**, not globally. A fresh `npm install` in a new project directory re-downloads ~175MB, which takes about five minutes and looks exactly like a hang (the process sits near 4% CPU). Copy the directory from an existing project instead of waiting.
- **Assets must be staged into a public directory the bundle serves.** The Remotion bundle is served over http and Chrome refuses `file://` references from an http origin — absolute paths render as blank frames, silently. `render_video.py` handles this: every call stages into **its own job directory** `render/jobs/<slug>-<pid>-<hex>/` (`public/` with a copy of `render/public/fonts/` and the staged `job/` files, handed to Remotion as `--public-dir`, and `props.json` beside it) and removes only that directory when it is done, success or failure (CF-0340). Directories left by a killed render are swept by the next render's start once they are a day old and their pid is gone. Never stage by hand into `render/public/` and never `rm -rf render/jobs` — the directories there are other renders in progress.
- **Renders may run in parallel (CF-0340).** Until this task every render wiped and refilled one shared `render/public/job/`, so a second render started beside the first deleted its assets and overwrote its props: batch `0705Z` lost Harbourlights attempt 1 to a 404 on an asset, CF-0336 saw `durationInFrames NaN`. Now nothing a render writes is shared. What still is: **the machine's CPU** — each Remotion takes half the cores by default, so three at once each run roughly three times slower and eat into their own time ceiling (`quiet.ceiling()`, 300 s + 8 s per composition second); run at most two at once, or pass `--concurrency` to split the cores — and **the video's own ledger and attempt log**, so never two renders of the *same* video at once (`attempts.begin()` closes a still-open attempt of that video as `abandoned` before it hands out the next number). Remotion's webpack cache under `render/node_modules/.cache` is shared and safe to share. A render running in the background is still one attempt: wait for it (one `until` on its output file or process), do not abandon it and start another.
- **Stopping your own background render: by PID, never by pattern (CF-0905).** In `example-tech/2026-10-31T0840Z` the stage started a render loop with `nohup bash /tmp/ve_run.sh &`, saw a wrong argument order in it four seconds later and stopped it with `pkill -f ve_run.sh; pkill -f render_video.py`. A pattern reaches every matching process on this machine - another channel's batch renders here too - and it reached render_video.py alone: build_soundtrack.py, its child, went on as an orphan, wrote `mix.wav` and `audio.bed` under the render already restarted, and died on a `BrokenPipeError` (RUN_LOG: `render ... started (no end recorded)`, then `soundtrack ... failed`). render_video.py now takes its children with it on SIGTERM/SIGHUP/SIGINT (build_soundtrack.py with its ffmpeg, Remotion with node and Chrome), ends the attempt `abandoned` with the stop named and exits 143 with a `failed` line - but only the processes you started are yours to stop. So keep the PID of what you start (`nohup bash loop.sh > out 2>&1 & echo $! > loop.pid`), and to stop it take its child first, then the loop: `L=$(cat loop.pid); K=$(pgrep -P $L); kill $L $K` (`pgrep -P` lists the children of *your* PID - not a pattern). Better still, do not stop a render to fix a later step of your loop: let it finish, then run the step by hand. A stopped render is still an attempt spent (`abandoned` counts, as before).
- **Caption detection is advisory, not authoritative.** `detect_text_band.py` looks for a text band that holds a steady position across sampled frames, which correctly finds real burned-in subtitles and correctly ignores scattered signage. It cannot separate a *static* in-scene text from a caption: a press-conference shot with jerseys held at chest height reads as captioned and loses ~28% of the frame. Read what `prepare_clip.py` reports; if a crop looks wrong for the shot, pass `--crop-bottom` explicitly or pick a different segment. Detect on the **cut segment**, never the whole source - a trailer carrying a subtitle on two shots reads as clean across the whole file.
- **Every block needs its own `Sequence`.** Mounted as a plain layer spanning the composition, a clip's internal playback starts at frame 0 of the *video*, so by the time its block is visible the clip has run out and sits frozen on a last frame. Five of six shots rendered as stills this way and looked, correctly, like a bad mix of video and photos. `qc_render.py` now probes each clip block for motion at three points and fails if it is still at all of them.
- **A still render is not automatically a broken render** (CF-0004). A hung block and a genuinely held shot — an animated held pose, a locked-off two-shot, a title card — are the same pixels: no change at all. Across the 20 cached trailers in `shared/footage`, 8.1% of all 0.3s windows fall under the gate's motion floor and 3.4% are essentially frozen, so this is common footage, not an edge case. `qc_render.py` therefore re-checks each still-reading block against **the clip it was cut from**: playback that ran past the clip's end is the CF-0031 fault and stays a failure; a clip that moves where the render does not stays a failure; a clip that is a still there too is reported in `held_source_blocks` and passes. Anything it cannot check (missing clip, unreadable frame) stays a failure — the gate fails closed. Last resort, for a block a human has actually looked at: `"held_pose": true` on the block's `asset` in `plan.json`, which is reported as an override rather than as a measurement.
- **`qc_render.RENDER_CROSSFADE` is a copy of `Video.jsx`'s `CROSSFADE`.** The source-side check has to know that each block's `Sequence` starts a crossfade *early*, or every probe lands on the wrong source frame. `test_frozen_block_source_check.py` asserts the two still agree; if you change the crossfade in the renderer, change it there too.
- **Always pass `-nostdin` to ffmpeg.** Without it ffmpeg swallows the caller's stdin, which silently corrupts any shell loop feeding clip timings on a pipe. All scripts here do this; keep it that way.
- **Reconcile the alignment against the written text** (`align_words.py --text work/<slug>/narration.txt`). Whisper is used for *when*, never for *what*: it transcribed "Rink Rivals" as "He did rivalry" and "season one" as "season 1", and those tokens are what gets burned on screen. Without reconciliation the caption shows the mis-hearing. Pass the `narration.txt` the TTS step just recorded beside the wav rather than a temp file of your own (CF-0261): it is the same text by construction, and it stays on disk afterwards, which is what makes the batch re-measurable.
- **`ffmpeg` and full-range YUV**: extracting stills from some downloaded footage fails under the mjpeg encoder ("Non full-range YUV is non-standard"). Write PNG instead of JPG.
- **Voice**: the channel's, not this skill's (CF-0188). `channels/<id>.json` → `voice_profile` is an object — `{engine: "kokoro", voice, speed, lang}` — and `synthesize_voiceover.py --channel <id>` reads it; `--voice`/`--speed` still win on the command line, which is how a voice is auditioned. A channel whose `voice_profile` is still the legacy string, or absent, reads in `am_puck` @ 0.95 — the voice every batch up to CF-0188 was read in and the voice `words_per_second` was measured on. **Changing the voice changes the speaking rate**, and the rate is what the whole word budget hangs on: re-measure `words_per_second` on a real batch (`measure_speaking_rate.py <batch-dir> --channel <id>`) and write it back into `narration_budget`, or the videos quietly change length. **So does changing the SHAPE of the narration** (CF-0261), and that one nobody was watching: Kokoro synthesizes one chunk per line, so the same 181 words read 44.50 s on one line and 58.92 s as five paragraphs — a quarter, on one voice at one speed. The narration reaches the voice as one line (`meme_layer.narration_text()` joins hook, commentary and payoff with a single space); pressing the sections apart into paragraphs is a legitimate prosody decision and it invalidates `words_per_second` exactly as a new voice does. That is what cost two batches their DoD: estimated at 50.3 s and 49.3 s of voice, delivered at 38.55 s and 38.40 s, both finished videos under the 45 s floor. Prosody comes from text structure, not from the voice. Kokoro is local and free; try another Kokoro voice long before considering a paid provider.
- **Platform**: Intel Mac pinned to `torch==2.2.2` (no newer macOS x86_64 wheels) → `transformers==4.44.2`, `numpy<2`. Don't "fix" these without reading why. `ffmpeg-full` is keg-only at `/usr/local/opt/ffmpeg-full/bin/`.
- **The watermark is the channel's `display_name` (CF-0212).** `build_render_plan.py --channel <id>` reads it out of `channels/<id>.json` (`scripts/channel_watermark.py`) and writes it in capitals - what `Watermark.jsx` draws, `ExampleFilm` -> `EXAMPLE_FILM`. There is no `--watermark-text` and no default name: a named channel without a `display_name` is refused before any work (`watermark: channel ... has no display_name`), and a plan built without `--channel` gets `watermark: null` and a note - no mark rather than another channel's. `--watermark-position` stays a flag; the corner is not the channel's identity.
- **Sound** — `build_soundtrack.py` mixes the bed and cut accents under the voice - and, since CF-0068, the plan's placed sound inserts as a fourth input (see Sound placement above) - then `render_video.py` uses the mix (since CF-0423 it runs the mixer itself when the plan has none; `--audio` only overrides) - which since CF-0117 runs to the end of the end card, not to the end of the voice. The default bed is **generated locally from sine partials and shaped noise**, with nothing to clear: a bed sits under every video, so a badly-licensed track puts the whole catalogue under one claim rather than one video. Same argument as `typographic` — the option that cannot fail depends on no external asset. `--music <file>` swaps in a licensed track, and the licence is then the caller's to hold. Ducking is measured at about 6.4 dB deep; the limiter (`alimiter=limit=0.88`) auto-levels every mix to 0 dBFS, and the render's audio stage sets the delivered peak (−3.0 to −3.9 dB on the shipped mp4s), so the −0.5 dB clipping gate belongs on the render, not on the mix.
- **The bed's audibility target, and where it is measured (CF-0025).** Everything about the bed's level is measured **above 200 Hz** (`common.BED_AUDIBLE_BAND_HZ`) — the low edge of what a phone or laptop speaker actually radiates. This is not a detail: the bed shipped for a whole milestone with 95% of its energy under 100 Hz, so it read a healthy −32 dBFS broadband and −58 dBFS in the band anyone can hear, and raising `--bed-db` moved the meter without changing what the user heard. In that band the bed lands at **−26 to −34 dBFS in the gaps between sentences and about −36 dBFS under speech** (measured on all eight videos of `2026-09-03T2037Z`, `2026-08-31T2155Z` and `the-long-voyage`), i.e. 13–14 dB under the narration's own level in the same band — present between sentences, not competing for the consonants. `qc_render.py` gates it in **one of two named windows**, and the window is always in the report as `bed_rms_window`: `word_gaps` (inter-word gaps over 0.4 s, clear of the bed's 1.5 s fades, floor `MIN_BED_RMS_DB` = −38) or, when the narration has no such pause — which is four of those eight videos — `under_speech` (the body between the fades, with the voice subtracted in the power domain, floor `MIN_BED_DUCKED_RMS_DB` = −44, one duck lower). Pre-roll and post-roll are never windows: both sit inside a fade. **`bed_rms_db: null` is now a QC failure** whenever `plan["audio"]["bed"]` says a bed was mixed — the old gate returned `null` on any narration without a long pause and then checked nothing, which is exactly how four videos shipped with a bed nobody could hear. A plan with **no** `audio.bed` is not measured on the level, but it is not waved through either (CF-0423): a plan built for a channel (`audio.channel` or `audio.bed_rotation`) and carrying no `audio.bed` was rendered without a mix and **fails** as `no bed in the mix`, and so does any render whose body - clear of the bed's fades and of the channel's ending clip - has three or more 100 ms frames of dead air (under `NO_BED_DB` = −70 dB broadband, which no ducked bed ever reaches: the mixed mp4s bottom out at −46, the bare-voice ones carry 16–23 such frames), whatever the plan says. `bed_declared`, `bed_expected`, `bed_missing` and `bed_silent_frames` in the measurements say which you got. Since CF-0423 `render_video.py` builds the mix itself, so on the normal path the plan always carries `audio.bed` by the time the gate reads it. To check a mix without a render: `qc_render.py <mix.wav> <plan.json> --audio-only` runs the audio gates only, on the same thresholds, marks the result `audio_only: true`, and deliberately touches neither the attempt ledger nor the attempt log — it is a check on the mix, not a verdict on a render.
- **The bed's level is the channel's setting, not a flag (CF-0165).** What a *supplied* bed (CF-0153: `channels/<channel_id>/ambient.<ext>`, the file the channel brings) is mixed at comes from `video_editor.ambient.bed_db` in the channel config — `-25` for `example-film`, chosen by ear on 2026-09-09 — and from nowhere else. A channel without the key mixes at `ambient_bed.DEFAULT_BED_DB` (−18.0), which is exactly what `--bed-db` used to default to, so nothing that exists today moves. `--bed-db` still overrides it and is how you **audition** a level; the answer then goes into the config, because a level that lives in one command line is lost on the next run. The plan says which it was: `audio.bed.bed_db_source` is `cli`, `config` or `default`. **The channel's number never reaches the generated bed** — `BED_TARGET_GAPS_DB` / `BED_TARGET_SPEECH_DB` were calibrated on the generator's flat carpet, and a brought-in file is structural (sparse crackles read as events, not as average power), which is why the same number sounds louder on it; so `--music generated`, and a channel whose file is missing, stay where CF-0025 put them. At −25 on this channel's fire the bed measures −37.1 dB (`cf0141-fullrun`, `word_gaps`, floor −38.0), −43.0 dB (`wren-hollow-christmas`, `under_speech`, floor −44.0) and −37.0 dB (`raygun-sneak-peek`, `word_gaps`, floor −38.0): **about 1.0 dB of headroom, systematically, on all three.** If `qc_render` starts failing the bed after any change to the mix graph, the voice or the file, that is where it comes from — raise `bed_db` in the channel config, never the gate's floor (decision 3 of CF-0153). One measured point on one file: it is not generalised to brought-in beds as a class, and a second channel with a file measures its own.
- **The bed is a rotation of three, and the choice is the plan's (CF-0271).** `example-film` names `video_editor.ambient.beds` — three CC0 lofi tracks in `channels/example-film/beds/`, one loudness, `bed_db` unchanged at −25. Which one plays is decided in `build_render_plan.py` from the `script_id` (sha256, so a re-mix and a second render attempt of the same video get the same bed) and written on the plan as `audio.bed_rotation`; `build_soundtrack.py` executes it. **If the mix refuses with "the channel rotates 3 beds … rebuild the plan", rebuild the plan first** — the plan you are mixing against was built before the rotation, and the mixer will not choose a bed of its own. The mix report names the track and its place in the rotation (`rotation: 2 of 3, chosen by sha256(script_id)`), and so do `05-video-editor.json` (`bed.ambient_rotation_index` / `_size` / `ambient_chosen_by`) and the runlog (`bed: morning-coffee.mp3 [2/3]`).
- **A generated bed is now a loud event, and you have to notice it (CF-0271).** A video once shipped on the generator at −18 dB where the channel had chosen −25, and nothing in the report said so. The two routes to it — no channel bed (`no_channel_bed`) and `--music generated` (`operator_forced_generated`) — now print a `SUBSTITUTED:` line in the mix summary, annotate the run (`bed: GENERATED <code>`, so it is in `RUN_EVENTS.jsonl` and the run summary) and set `bed_substituted` in `05-video-editor.json`. **Do not close a batch on a video whose `bed_substituted` is not `null`** without saying so to the user: the bed it shipped with is not the one the channel chose, and it is 7 dB louder. The level split itself is deliberate and stays (CF-0165).
- Don't substitute placeholder visuals silently if sourcing fails. Say so, like every other agent in this pipeline.

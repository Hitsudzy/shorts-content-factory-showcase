# The background bed (CF-0153)

The music under the narration and the mix the render builds. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

The bed under a video is **a finished file the channel brings with it**, like
the ending clip (CF-0141):

```
channels/<channel_id>/ambient.<ext>     wav flac aif aiff m4a mp3 aac ogg opus
```

beside `stance.json` and `ending.mp4`. `video_editor.ambient.path` in the
channel config overrides the convention with any path, and a config that names
a file it does not have refuses the mix rather than falling back.

**Or three files (CF-0271).** `video_editor.ambient.beds` is a *list*, and the
channel then rotates: `example-film` plays one of three CC0 lofi tracks from
`channels/example-film/beds/`. `beds` and `path` together are refused (they are
one decision said twice), and a list with a missing file in it is refused by
index - a rotation that quietly shrank would put a bed nobody chose under
every video whose hash landed on the hole.

Which of them plays is decided **once, in the plan**:
`build_render_plan.py` hashes the `script_id` (`ambient_bed.bed_index()`,
sha256 - not the built-in `hash()`, which is salted per process and would hand
the same video a different bed on its second render attempt) and writes
`audio.bed_rotation`: the list, the chosen file, its index, the key and the
rule, so the choice can be rechecked rather than believed.
`build_soundtrack.py` only executes it, and a rotating channel under a plan
that carries no choice **refuses with "rebuild the plan"** instead of choosing
a second time - two places choosing would mean rebuilding a plan could change
the sound of a video that was already approved. The spread is binomial and not
round-robin (90 videos over three beds is 30 ± 4.5): nobody counts how often a
lofi track played, and the alternative is per-attempt state. `--music <file>`
and `--music generated` bypass the rotation entirely.

What the file has to be, all of it checked before ffmpeg is started
(`scripts/ambient_bed.py`, `AmbientBedError`):

* **at least 8 s** (`AMBIENT_MIN_SECONDS`). Longer than the video is fine and
  is not truncated audibly - it is simply cut at the composition's length.
  Shorter than the video is **looped**, with a 0.75 s equal-power crossfade at
  every seam, so a 12 s recording covers a 60 s video with no click and no dip.
  Under 8 s it is refused: at that length the loop stops being texture and
  becomes a pulse of its own.
* **real energy above 200 Hz.** The file is levelled to the bed the generator
  would have produced, measured in the band a phone speaker actually radiates
  (`BED_AUDIBLE_BAND_HZ`); a file that would need more than 24 dB of lift to
  get there is refused as the wrong file rather than lifted with its own noise
  floor. This is CF-0025's defect stated as an entry condition.
* **anything else** - sample rate, channels, codec, how hot it was mastered -
  is converted or normalised and is not your problem. The finished level is
  the same whoever mixed the file.

No file: the generator, exactly as before. It is the floor for a channel that
does not have one yet and it is deliberately not repaired (decision 2 of
2026-09-08); the fan-noise character the user rejected is the price of a bed
that depends on no asset.

**And the generator now says when it played (CF-0271).** A video of
`2026-09-17T1901Z` shipped on the generated bed at −18 dB where the channel
had chosen −25, and the only trace was a `source: "generated"` field that
looks the same on an ordinary run. Both routes to it now carry a reason code -
`no_channel_bed` (the run asked the channel and it had none) and
`operator_forced_generated` (`--music generated`) - into three places: the run
report (a `SUBSTITUTED` line), the runlog
(`runlog.annotate(bed="GENERATED <code>")`, so it lands in `RUN_EVENTS.jsonl`
and the run summary, beside `two_source_gate=` and `assetless_rung=`) and the
plan's `audio.bed.substituted`, which reaches `05-video-editor.json` as
`bed_substituted`. `null` means nothing was substituted. The −18/−25 split is
unchanged and deliberate (CF-0165): the complaint was never that −18 is the
wrong level, it was that nobody was told.

The mixer needs a channel to ask:

```
build_soundtrack.py voice.wav plan.json mixed.wav --channel example-film
build_soundtrack.py voice.wav plan.json mixed.wav          # no channel -> generator
build_soundtrack.py ... --channel example-film --music generated   # A/B the floor
build_soundtrack.py ... --music /path/to/one.wav           # a one-off, same machinery
```

A call without `--channel` mixes exactly as every call did before CF-0153.

## The render builds the mix (CF-0423)

The mix used to be a step of its own between the plan and the render, and
`render_video.py` without `--audio` rendered the bare voiceover. From
`example-film/2026-09-23T1722Z` to the rebuild `2026-09-27T1757Z` the step was
skipped on every video but kaijura-minus-zero: paper-dragon,
american-dread-story, you-can-see-everything, backrooms and wolfhame (and
delver before them) shipped with dead air between phrases and none of the lofi
bed their plans had chosen - and `qc_render.py` passed them, because a plan
with no `audio.bed` "claimed no bed".

Now:

- `build_render_plan.py` writes `audio.channel` (its `--channel`) beside
  `audio.bed_rotation`;
- `render_video.py <plan> <out>` with no `--audio` plays the mix recorded on
  the plan (`audio.bed.mix`) or runs `build_soundtrack.py` itself against the
  plan's channel (`audio.channel`, or the channel the rotation's chosen file
  lives under - which also gives the factory root the plan was built against)
  into `<plan dir>/mix.wav`, inside the attempt it has just begun. A plan that
  names no channel renders as before; `--bare-voice` renders the voice alone
  on purpose; `--audio` still overrides;
- `qc_render.py` fails `no bed in the mix` when the plan was built for a
  channel and carries no `audio.bed`, and - whatever the plan says - when the
  body of the render (clear of the bed's fades and of the ending clip) has
  `NO_BED_MIN_FRAMES` = 3 or more 100 ms frames under `NO_BED_DB` = −70 dB
  broadband. The mixed mp4s never go under −46 dB there; the bare-voice ones
  carry 16–23 such frames. Measurements: `bed_expected`, `bed_missing`,
  `bed_silent_frames`. Locked by `tests/test_bed_reaches_the_render.py`, on a
  real cut of `publish/backrooms.mp4` and on the whole plan → mix → render path.

`plan["audio"]["bed"]` records which bed played and, for a supplied one,
`ambient`: the file's name and path, whether the config, the convention or the
rotation found it (`ambient_source`, and `rotation` for the third), how many
times it looped and how far it was lifted; on a rotation also which of the
list it was and by what rule. Those facts reach the batch record as
`videos[].bed` (`ambient_bed.bed_record_fields()`, `BED_RECORD_KEYS` - always
all of them, `null` where there is nothing to say).

## The mix ends at the channel's loudness (CF-0695)

Nothing used to measure loudness: on 2026-10-12 a Tech voice-over-bed sample
read −22.5 LUFS and a full preview render −17.2 LUFS with its true peak at
+0.02 dBFS. YouTube turns a loud upload down and never a quiet one up, so a
quiet Short just plays quieter than its neighbours. The user's answer (Q35,
2026-10-12): −14 LUFS on every channel.

- **Where the target lives.** `channels/<channel>.json` →
  `video_editor.loudness: {target_lufs, true_peak_db}`. Absent (all three
  Example channels today) = −14 LUFS integrated, true peak ≤ −1 dBTP. Either
  field may be left out; a value out of range (target in [−30, −5], peak in
  [−9, 0]) stops the mix by name before ffmpeg runs (`LoudnessConfigError`)
  and is refused by the root validator too.
- **The voice stem is compressed first** (`loudness.compress_voice()`, every
  channel). `acompressor` 3:1, peak detection, attack 5 ms, release 200 ms,
  soft knee, threshold 6 dB over the voice's own integrated loudness (so it
  adapts per video); the loudness it took is measured and given back as
  makeup, so the voice keeps its place against the bed. The stem is
  `_voice.wav`; it feeds the graph and keys the duck, and qc_render.py
  subtracts it (not the bare voice) when it measures the bed under speech.
  How hard it worked is recorded: share of voiced 10 ms windows turned down
  by more than 1 dB, mean / p95 / max gain reduction.
- **Then one static gain and a capped limiter** (`loudness.master()`). The
  graph writes a float mono premaster (`_premaster.wav`); it is measured as
  it will sound in both channels (ebur128 `dualmono`), moved by one static
  gain and passed through a 4× oversampled `alimiter` whose ceiling is the
  target peak less 0.5 dB of margin for the render's AAC encode. The limiter
  may take at most **4 dB** off the peaks; a mix that would need more is
  raised only that far and the rest is recorded as `shortfall_db`, never
  squashed. Not `loudnorm`: its dynamic mode reached −14 on the preview by
  squeezing the loudness range from 11.9 to 5.6 LU.
- **The mix is dual-mono stereo at unity.** The render used to up-mix the
  mono mix at −3 dB per channel: the same integrated loudness, but every
  peak 3 dB under what it was allowed (render −4.4 vs mix −1.5 dBTP on the
  demo). The master pass now writes both channels itself, each the whole mix
  at 0 dB; the render plays a stereo file as it is, so the mix's true peak
  is the render's (−1.5 / −1.5 dBTP measured).
- **The ending clip.** Its own track is played by the render over silence in
  our mix (CF-0141), so it is levelled separately by a static `volume` that
  `EndCard.jsx` passes to Remotion (`audio.loudness.ending.volume`, wired in
  `Video.jsx`) - to where the mix *landed* (`ending.target_lufs`), which is
  the target when the mix reaches it; a mix left short would otherwise jump
  up by the shortfall in the last five seconds. No limiter there, so the gain
  is capped where the clip's own true peak meets the ceiling. The three
  Example endings read −10.4…−10.8 LUFS with true peaks −0.4…+0.2 dBTP, so
  at the target they play about 3.2–3.6 dB down.
- **The record.** `plan["audio"]["loudness"]`: `target_lufs`,
  `true_peak_db`, `source` (config | default), `before` / `after`
  (`integrated_lufs`, `true_peak_db`, `lra_lu`), `gain_db`, `wanted_db`,
  `limiter_gr_db`, `limiter_cap_db`, `shortfall_db`, `landed_off_by_lu`,
  `passes`, `voice` (the compressor's params, before/after, makeup,
  peak-to-loudness before/after, `gr`) and `ending` (the clip's `before`,
  `gain_db`, `volume`, `target_lufs`, `shortfall_db`). The run report prints
  `voice:`, `loudness:` and `ending clip:` lines, `SHORT by N dB` when the
  cap held.
- **The check.** `qc_render.py` measures the finished file whole (mix and
  ending together - what the viewer hears) into `measured.loudness`, and when
  the plan records a loudness pass and the file is more than ±1 LU off the
  target or its true peak is over the ceiling, adds a **note** (`loudness off
  target: …`), not a failure. The pass already aims at the target and records
  its own shortfall; a miss is something to look at, not a fault worth a
  re-render. A plan without `audio.loudness` is not judged.
- **The bed targets** (`BED_TARGET_GAPS_DB`, `BED_TARGET_SPEECH_DB`) are
  levels in the graph's own output, i.e. the premaster. In the delivered mix
  the bed reads those plus `gain_db` (and a mono fold-down of the stereo mix
  reads 3 dB more); its level against the voice is unchanged.

Measured on the 2026-10-12 Tech demo (Kokoro voice, `tokyo-sunset` at
`bed_db` −28, ExampleTech's ending; re-mixed and re-rendered through
Remotion). Before: the render read −18.1 LUFS whole, LRA 12.5 LU, true peak
0.0 dBTP - a −22.0 LUFS body and an ending 11 LU louder at −10.9. The voice:
−23.0 LUFS, peaks −2.4 dBTP (peak-to-loudness 20.6 dB); compressed at −17.0
dB, makeup +2.2 dB → −23.0 LUFS, −3.7 dBTP (19.3 dB), LRA 2.6 → 1.9 LU; 34 %
of voiced 10 ms windows turned down by more than 1 dB, mean 1.0 dB, p95 4.1
dB, max 6.7 dB. The compressor evens the envelope but hardly moves the
peak-to-loudness ratio - the peaks are sub-millisecond waveform crest, which
only a limiter holds. The premaster (as dual-mono): −18.9 LUFS, −2.6 dBTP;
+4.9 dB static gain, limiter 3.8 dB at the highest peak, no shortfall → mix
−14.2 LUFS, −1.5 dBTP, LRA 2.4 LU. The ending at −3.4 dB (volume 0.6761).
The render: **−14.2 LUFS whole, true peak −1.5 dBTP, LRA 2.2 LU** (body
−14.2, ending −14.3); qc_render passes with no loudness note.

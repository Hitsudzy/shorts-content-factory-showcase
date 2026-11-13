#!/usr/bin/env python3
"""Mix the finished audio: voice, a music bed ducked under it, and cut accents.

A video that is voice over silence reads as homemade more than any framing
problem does. This adds the two cheapest fixes - a bed and an accent on scene
changes - without introducing the risk that comes with them.

That risk is the reason for the default. A music bed sits under *every* video,
so a badly-licensed track does not cost one claim, it puts the whole catalogue
under one. The default bed is therefore **generated here from nothing**: sine
partials and shaped noise, no sample, no library, nothing to clear. It is the
same argument as the `typographic` style - the option that cannot fail is the
one that depends on no external asset.

**CF-0153 moved the bed off the generator for a channel that has a file.** The
argument above still holds for the generator - it is the floor, and it is what
a channel without a file gets, unrepaired (decision 2 of 2026-09-08) - but the
bed a real channel plays is now a finished file the channel brings with it,
`channels/<channel_id>/ambient.<ext>`, exactly as the ending clip is
(CF-0141). The rights argument is answered by the same construction: the user
brings the file, nothing is fetched. Everything about finding, checking,
looping and levelling that file is in `ambient_bed.py`; what happens here is
that the bed input of the graph below is that file instead of `bed()`, at a
level chosen so the mix lands where it always did. `--channel` is what makes
the lookup possible: a call without one has no channel to ask and mixes with
the generator, off exactly the inputs it always used.

A licensed track can also be passed with --music <file>, which goes through
the same preparation as a channel's own file.

CF-0068 adds the fourth input, `inserts`: one mono track of silence with each
sound the plan placed (plan["sound"]["placed"], written by sound_layer.py)
laid at its at_seconds - trimmed to MAX_SOUND_SECONDS (a hard cut, never a
stretch or a loop), faded 5 ms in and 40 ms out where it was cut, gained so
its loudness sits SOUND_LEVEL_REL_VOICE_DB under the whole voice track's,
peaks capped at SOUND_PEAK_CEILING_DBFS. The bed is sidechain-ducked under
it with the same compressor the voice already keys; the voice is never
ducked (inserts/sound.json `mix`: the narration is the product). A plan with
no placed sound - the layer off, every request refused, a file gone from
disk - runs the three-input graph exactly as before, so the layer's absence
is byte-identical to its never having existed (`degradation`).

Usage:
    build_soundtrack.py <voice.wav> <plan.json> <out.wav>
      [--channel <id|path.json>] [--root <factory root>]
      [--music channel|generated|<file>]
      [--bed-db <dB>] [--accent-db -20]

CF-0165 moved the bed's level into the channel too: `video_editor.ambient
.bed_db` is what a supplied bed is mixed at (`-18.0` when the channel says
nothing, so a channel without the key does not move), and `--bed-db` is the
flag for auditioning a level rather than the place one is kept. The generator
keeps its own calibrated level whatever the channel says - see
`ambient_bed.bed_db()`.

CF-0271 made the bed a rotation and the substitution loud. A channel may name
`video_editor.ambient.beds` - a list - and then *which* of them plays is the
plan's decision, not this script's: `build_render_plan.py` hashes the
`script_id` and writes `audio.bed_rotation`, and this script reads it back,
checks it still names a bed the channel offers, and mixes it. A rotating
channel under a plan that carries no choice is an `AmbientBedError` ("rebuild
the plan"), never a bed picked here. And in the two cases where the generator
plays instead of a file - no channel bed, or `--music generated` typed by hand
- the run now says so out loud: `runlog.annotate(bed="GENERATED <code>")`, a
SUBSTITUTED line in the report and `bed.substituted` on the plan, which
`05-video-editor.json` carries as `bed_substituted`. The -18/-25 split itself
is unchanged (CF-0165): the complaint this task was raised about was not that
-18 is the wrong level, it was that nobody was told.

CF-0695 ends the mix on a loudness pass. The graph writes a float premaster
(`_premaster.wav`); loudness.master() measures it (EBU R128, true peak) and
brings it to the channel's `video_editor.loudness` target - -14 LUFS
integrated, true peak <= -1 dBTP by default - with one static gain and a
4x-oversampled limiter allowed at most 4 dB of work; past that the shortfall
is recorded rather than the mix squashed. The channel's ending clip, which the
render plays over silence in this mix, gets the matching static volume
(`audio.loudness.ending.volume`). Everything measured - before, after, gain,
limiter, shortfall - is `audio.loudness` on the plan; see loudness.py.
"""
import argparse
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np

from common import (BED_AUDIBLE_BAND_HZ, BED_FADE_SECONDS, SOUND_DUCKS_BED,
                    SOUND_DUCKS_VOICE, SOUND_FADE_IN_MS, SOUND_FADE_OUT_MS,
                    SOUND_LEVEL_REL_VOICE_DB, SOUND_PEAK_CEILING_DBFS,
                    # CF-0132: both ffmpeg passes here go through the helper,
                    # so a wedged decode or mix ends with CF-0077's sentence
                    # instead of eating the batch window.
                    audio_duration, ffmpeg, ffmpeg_stderr)
import ambient_bed
import loudness
import meme_layer
import sound_layer
import quiet
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

SR = 44100
# The sidechain compressor the voice keys the bed with; the sound keys the
# bed with the same one (CF-0068), so a duck reads the same under both.
DUCK = "sidechaincompress=threshold=0.03:ratio=4:attack=8:release=350:makeup=1"

# A minor triad plus its octave, low and slow. Chosen to sit under speech rather
# than beside it: no attack, no melody, nothing that competes for attention.
SEMITONES = [0, 3, 7, 12]
ROOT_HZ = 58.27  # A#1

# CF-0025: the chord is voiced *twice*, and the second voicing is the one that
# is actually heard. Measured on the shipped 2026-09-03T2037Z beds, the single
# low voicing put 95.2% of the bed's energy under 100 Hz and 0.0% over 300 Hz -
# the band a phone or laptop speaker cannot radiate at all - so the bed read
# -25.7 dBFS on a broadband meter and -57.5 dBFS in the band a listener's
# device reproduces (measured by tapping the bed straight out of the graph
# below, on wren-hollow-christmas and raygun-sneak-peek). Raising --bed-db moved the first number and not the second,
# which is why the first CF-0025 fix (-24 -> -16 dB) changed the measurement by
# 8 dB and changed what the user heard by nothing.
#
# So: the low voicing stays, at less weight, for body on headphones; the same
# chord two octaves up (ROOT_HZ * 4 = 233.1 Hz, partials to 932 Hz) carries the
# bed on a speaker. 233 Hz sits above a male speaking fundamental rather than on
# top of it, and the pad is still a slow chord with no attack and no melody.
BED_SUB_WEIGHT = 0.45     # the original low voicing, kept for body
BED_MID_MULTIPLE = 4      # ROOT_HZ * 4 = A#3, the voicing that carries
BED_MID_WEIGHT = 0.8
# The air layer, band-shaped rather than boxcar-smoothed. The old 512-tap
# boxcar at 44.1 kHz is a low-pass with its first null at 86 Hz, so the
# "breath of air over the top" was infrasonic rumble; this puts it where the
# phrase meant, with a pink tilt and a slow drift so it reads as room and not
# as hiss.
BED_AIR_WEIGHT = 0.8
BED_AIR_BAND_HZ = (250.0, 2500.0)
# What the bed has to hit in the finished mix, measured above
# BED_AUDIBLE_BAND_HZ (common.py). qc_render.py owns the floors; these are the
# targets the mixer aims at, and each floor sits about 6 dB under its target.
# Measured through the graph below at the default --bed-db on all eight videos
# of 2026-09-03T2037Z, 2026-08-31T2155Z and the-long-voyage: the bed lands at
# -26.3 to -33.6 dBFS in the gaps between sentences and -35.5 to -36.2 dBFS
# under speech, against the voice's own >200 Hz level of -22.4 to -23.7 dBFS.
# So the bed sits 13-14 dB under the narration where it is speaking and lifts
# 6.4 dB (the duck's measured depth) in the gaps - the ordinary window for
# music under narration: present in the gaps, not competing for the
# consonants. The spread in the gaps is the duck's 350 ms release against how
# long each script's pauses are, not a difference in the mix.
# qc_render.py's floors sit 4-8 dB below what these deliver.
#
# CF-0165: **these two are the generator's calibration and describe a
# generated bed.** They were measured on a flat noise carpet, and a file a
# channel brings is structural - sparse transients take attention that an even
# carpet of the same RMS does not - so the same number reads louder on it. A
# channel that sets `video_editor.ambient.bed_db` moves its supplied bed away
# from these targets on purpose; what that landed at on the one file there is
# to measure is recorded in ambient_bed.py, next to the setting, as a measured
# point and not as a second constant. Nothing generalises it to brought-in
# files as a class yet - one file is not a class.
#
# CF-0695: and they are levels in the graph's own output - the premaster. The
# loudness pass after it moves the whole mix by one static gain
# (`audio.loudness.gain_db`), bed included, so in the delivered mix the bed
# reads these plus that gain; its level *relative to the voice* is untouched.
BED_TARGET_GAPS_DB = -31.0      # bed in a voice-free gap, >200 Hz, in the mix
BED_TARGET_SPEECH_DB = -38.0    # bed under speech, >200 Hz, in the mix


def _air(n, rng, lo, hi, t):
    """Band-shaped noise: white noise given a spectral envelope in the
    frequency domain (no scipy in this venv, and an FFT envelope is exact
    where a boxcar convolution is a guess), pink-tilted inside the band, with
    a slow amplitude drift over it."""
    spectrum = np.fft.rfft(rng.normal(0, 1, n))
    f = np.fft.rfftfreq(n, 1 / SR)
    env = 1 / np.sqrt(1 + (np.maximum(f, 1e-6) / hi) ** 2)       # off above hi
    env *= (f / lo) / np.sqrt(1 + (f / lo) ** 2)                  # off below lo
    env *= 1 / np.sqrt(np.maximum(f, 20.0) / lo)                  # pink in band
    air = np.fft.irfft(spectrum * env, n=n)
    air /= np.abs(air).max() + 1e-9
    return air * (0.6 + 0.4 * np.sin(2 * np.pi * 0.023 * t + 1.7))


def bed(seconds, seed=7, fade_out_seconds=BED_FADE_SECONDS):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.linspace(0, seconds, n, endpoint=False)
    out = np.zeros(n)

    for weight, multiple in ((BED_SUB_WEIGHT, 1), (BED_MID_WEIGHT, BED_MID_MULTIPLE)):
        for i, semi in enumerate(SEMITONES):
            f = ROOT_HZ * multiple * (2 ** (semi / 12))
            # Slight detune and a slow amplitude drift keep it from sounding like
            # a test tone; every voice moves at its own rate so they never pulse
            # together, and the two voicings are offset from each other too.
            detune = 1 + rng.uniform(-0.0015, 0.0015)
            drift = 0.55 + 0.45 * np.sin(
                2 * np.pi * (0.031 + i * 0.017) * t + i + multiple)
            out += weight * (0.5 ** i) * drift * np.sin(2 * np.pi * f * detune * t)
            out += weight * 0.22 * (0.5 ** i) * drift * np.sin(
                2 * np.pi * f * 2 * detune * t)

    out += BED_AIR_WEIGHT * _air(n, rng, *BED_AIR_BAND_HZ, t)

    out /= np.abs(out).max() + 1e-9

    fade = int(SR * BED_FADE_SECONDS)
    out[:fade] *= np.linspace(0, 1, fade)
    # CF-0117: the tail fade is a parameter because the end card moved it into
    # the filter graph. Under a card the bed has to fade over the card's own
    # seconds - and over a supplied track too, which this generator never
    # touches - so the graph does it in one place and passes 0 here rather
    # than fading the same tail twice at two different lengths.
    fade_out = int(SR * max(0.0, fade_out_seconds))
    if fade_out:
        out[-fade_out:] *= np.linspace(1, 0, fade_out)
    return out


def accents(seconds, times, seed=11):
    """A soft impact on each cut. Filtered noise with a fast decay over a low
    body tone - felt at the edit rather than heard as a sound effect."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n)
    length = int(0.34 * SR)
    env = np.exp(-np.linspace(0, 9, length))
    body = np.sin(2 * np.pi * 74 * np.linspace(0, 0.34, length)) * np.exp(
        -np.linspace(0, 5, length))

    for at in times:
        start = int(at * SR)
        if start < 0 or start + length > n:
            continue
        hiss = rng.normal(0, 1, length)
        hiss = np.convolve(hiss, np.ones(48) / 48, mode="same")
        hit = 0.6 * hiss / (np.abs(hiss).max() + 1e-9) * env + 0.9 * body
        out[start:start + length] += hit

    peak = np.abs(out).max()
    return out / peak if peak > 0 else out


def read_mono(path):
    """Any audio file as float samples at SR, mono - decoded by ffmpeg, so
    the sound library's ogg/mp3/flac need no reader of their own."""
    # `text=False`: the answer is raw float32 on stdout. No media_seconds:
    # media_timeout()'s base alone is the ceiling for a decode, and it is the
    # honest one here - the longest thing this ever reads is one video's voice
    # track, and a decode costs a fraction of the encode the slope was
    # measured on. Asking ffprobe how long every sound sample is, once per
    # sample, would cost more than the ceiling it bought.
    out = ffmpeg("-i", str(path), "-vn", "-f", "f32le", "-ac", "1", "-ar", str(SR), "-",
                 text=False)
    if out.returncode != 0:
        raise RuntimeError(ffmpeg_stderr(out).strip()[-300:])
    return np.frombuffer(out.stdout, dtype="<f4").astype(np.float64)


def rms_db(samples, gate_db=-50.0):
    """Loudness as gated RMS in dBFS: samples in 100 ms frames, frames below
    `gate_db` (silence between sentences, the tail of a sample) left out, so
    a voice track with long pauses is measured on its speech. -inf on
    silence. The same instrument for the voice and the sound, which is what
    a level *relative* to the voice needs."""
    if samples.size == 0:
        return -math.inf
    frame = max(1, int(0.1 * SR))
    n = (samples.size // frame) * frame
    frames = samples[:n].reshape(-1, frame) if n else samples.reshape(1, -1)
    powers = np.mean(frames ** 2, axis=1)
    with np.errstate(divide="ignore"):
        levels = 10 * np.log10(powers)
    kept = powers[levels > gate_db]
    if kept.size == 0:
        kept = powers
    mean = float(np.mean(kept))
    return 10 * math.log10(mean) if mean > 0 else -math.inf


def _lib_max_sound_seconds():
    """MAX_SOUND_SECONDS from inserts_lib - the one place the ceiling lives.
    1.5 when the factory root is not reachable (a bare checkout of this
    repo), which is the value the spec pins and validate_inserts enforces."""
    try:
        return float(sound_layer._lib(sound_layer.factory_root()).MAX_SOUND_SECONDS)
    except Exception:  # noqa: BLE001
        return 1.5


def inserts_track(seconds, placed, voice_level):
    """The fourth input: silence with every placed sound laid at its
    at_seconds, each trimmed to the ceiling, faded, gained to
    SOUND_LEVEL_REL_VOICE_DB under `voice_level` and peak-capped. Returns
    (samples, [report lines]); a file that cannot be read is skipped with a
    line and changes nothing else (degradation: block_without_insert)."""
    n = int(seconds * SR)
    out = np.zeros(n)
    lines = []
    ceiling = int(_lib_max_sound_seconds() * SR)
    fade_in = int(SOUND_FADE_IN_MS * SR / 1000)
    fade_out = int(SOUND_FADE_OUT_MS * SR / 1000)
    ceiling_lin = 10 ** (SOUND_PEAK_CEILING_DBFS / 20)
    for p in placed:
        try:
            samples = read_mono(p["file"])
        except Exception as e:  # noqa: BLE001
            lines.append(f"sound {p.get('beat_id')}: {p.get('asset_id')} not mixed - {e}")
            continue
        cut = samples.size > ceiling
        samples = samples[:ceiling].copy()
        if samples.size == 0:
            lines.append(f"sound {p.get('beat_id')}: {p.get('asset_id')} is empty - not mixed")
            continue
        k = min(fade_in, samples.size)
        samples[:k] *= np.linspace(0, 1, k, endpoint=False)
        if cut:
            k = min(fade_out, samples.size)
            samples[-k:] *= np.linspace(1, 0, k)
        level = rms_db(samples)
        if math.isfinite(level) and math.isfinite(voice_level):
            samples *= 10 ** ((voice_level + SOUND_LEVEL_REL_VOICE_DB - level) / 20)
        peak = float(np.abs(samples).max())
        if peak > ceiling_lin:
            samples *= ceiling_lin / peak
        start = int(float(p["at_seconds"]) * SR)
        if start < 0 or start >= n:
            lines.append(f"sound {p.get('beat_id')}: at {p['at_seconds']}s is outside the "
                         f"{seconds:.2f}s voice - not mixed")
            continue
        end = min(n, start + samples.size)
        out[start:end] += samples[:end - start]
        lines.append(f"sound {p.get('beat_id')}: {p.get('asset_id')} at {float(p['at_seconds']):.2f}s, "
                     f"{samples.size / SR:.2f}s{' (cut at the ceiling)' if cut else ''}, "
                     f"{rms_db(samples):.1f} dB vs voice {voice_level:.1f} dB")
    return out, lines


def write_wav(path, samples):
    data = np.clip(samples, -1, 1)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((data * 32767).astype("<i2").tobytes())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("voice")
    p.add_argument("plan")
    p.add_argument("output")
    # CF-0153: three values, and the default is the channel's own file.
    #   `channel`    (default) the channel's ambient bed when it has one -
    #                channels/<channel_id>/ambient.<ext> or
    #                video_editor.ambient.path - and the generator when it does
    #                not. Needs --channel to have a channel to ask; without one
    #                there is nothing to look up and the generator is what runs,
    #                which is why every call that predates CF-0153 still mixes
    #                exactly as it did.
    #   `generated`  the generator, always, whatever the channel has. The way to
    #                A/B the channel's file against the floor without moving it.
    #   <file>       that file as the ambient, through the same preparation.
    p.add_argument("--music", default="channel",
                   help="'channel' (default: the channel's ambient file, else the "
                        "generator), 'generated' (always the generator, rights-clean "
                        "by construction), or a file")
    p.add_argument("--channel",
                   help="channel id under <root>/channels or a path to a .json - "
                        "where the ambient bed is looked up (CF-0153)")
    p.add_argument("--root", help="factory root (default $FACTORY_ROOT or the checkout)")
    # CF-0025: -18, and not comparable to the -16 it replaces - the bed's
    # spectrum changed under it. The old bed needed -16 to be measurable at
    # all because 95% of its energy was under 100 Hz; the new one puts about
    # 22 dB more into the band a speaker reproduces, so a *lower* broadband
    # level lands 22 dB louder where it counts (and 1.6 dB quieter in the
    # rumble). See BED_TARGET_GAPS_DB / BED_TARGET_SPEECH_DB.
    #
    # CF-0165: no default here any more. Unset means "ask the channel" -
    # video_editor.ambient.bed_db, and ambient_bed.DEFAULT_BED_DB (-18.0, the
    # number this line used to hold) when the channel says nothing. The flag
    # stays as the way to audition a level; it is not where a chosen level is
    # kept, which is the whole point of the task.
    p.add_argument("--bed-db", type=float, default=None,
                   help="override the bed's level in dB (default: the channel's "
                        f"{ambient_bed.CHANNEL_BED_DB_KEY} for a supplied bed, else "
                        f"{ambient_bed.DEFAULT_BED_DB})")
    p.add_argument("--accent-db", type=float, default=-20.0)
    quiet.add_args(p)
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.plan))  # CF-0107: slug + the attempt the mix belongs to

    plan = json.load(open(args.plan))
    seconds = audio_duration(args.voice)
    # CF-0117: the mix is as long as the *composition*, not as long as the
    # voice. The end card holds the frame after the last word with no voice
    # under it, and the bed goes with it: silence there would read as the file
    # having ended and the player having stalled. `duration.composition` is
    # what end_card.apply_to_plan() wrote (narration + the CF-0087 constant);
    # a plan without a card carries none and mixes exactly as before, to the
    # voice's own length.
    card = plan.get("end_card") or {}
    total = float((plan.get("duration") or {}).get("composition") or seconds)
    total = max(total, seconds)
    card_seconds = round(total - seconds, 3) if total > seconds + 1e-6 else 0.0
    work = Path(args.output).parent
    # CF-0098: this script is quiet on success (a handful of lines) - the
    # noise is ffmpeg's stderr on a failed mix, which goes to the attempt's
    # log when the plan has one. No attempt is begun here: the mix is part of
    # the same attempt the following render_video.py begins, so its lines
    # land in the latest attempt's log (or the first one's, before any).
    ctx = quiet.Context.for_plan(args.plan)
    log = None
    if ctx is not None:
        latest = ctx.latest()
        n = latest["n"] if latest and latest.get("result") is None else \
            (latest["n"] + 1 if latest else 1)
        import attempts as _attempts
        log = _attempts.log_path(ctx.batch_dir, ctx.slug, n)

    # No tail fade in the samples when there is a card: the graph fades the
    # bed over the card's seconds below, and doing it in both places would
    # duck the last second and a half twice. The same number goes to the
    # ambient file's preparation, so the two sources fade alike.
    bed_fade_out = 0.0 if card_seconds else BED_FADE_SECONDS
    # CF-0165: the channel is read once, here, because two things now come out
    # of it - which file the bed is (CF-0153) and at what level it plays.
    channel_cfg, root = None, None
    if args.channel:
        root = Path(args.root).resolve() if args.root else meme_layer.factory_root()
        channel_cfg = meme_layer.load_channel(args.channel, root)
    # CF-0695: and a third - the loudness the finished mix is brought to.
    # Read before anything is mixed so a broken key stops the run by name
    # (LoudnessConfigError) instead of after a minute of ffmpeg.
    target_lufs, true_peak_db, loudness_source = loudness.settings(channel_cfg)
    # CF-0153: which file the bed is. Resolved before anything is mixed, and a
    # channel that names an ambient it cannot produce stops here with an
    # AmbientBedError rather than falling back to the generator - see that
    # module for why the fallback would be the wrong kindness.
    # CF-0271: and *which* file, when the channel brings a rotation. The choice
    # is not made here - `build_render_plan.py` made it from the script_id and
    # wrote it on the plan; this reads it back and checks it against what the
    # channel offers now. A channel that rotates under a plan that carries no
    # choice stops with an AmbientBedError telling the operator to rebuild the
    # plan, rather than choosing a bed of its own off the slug: two places
    # choosing would mean rebuilding a plan could change the audio of a video
    # that was already approved.
    ambient_file, ambient_source = None, None
    rotation = None          # the plan's audio.bed_rotation, when one applies
    substituted = None       # why the generator played, when it did
    if args.music == "generated":
        # The operator asked for the generator by hand. Legitimate (it is how
        # the channel's own file is A/B'd against the floor) and until CF-0271
        # completely silent: it mixes at DEFAULT_BED_DB, not at the channel's
        # level, and the only trace was `bed.source: "generated"` in a record
        # that looks the same on an ordinary run.
        substituted = ambient_bed.BED_SUBSTITUTED_OPERATOR
    elif args.music == "channel":
        if args.channel:
            beds = ambient_bed.ambient_beds(channel_cfg, root, args.channel)
            if beds and beds[0][1] == ambient_bed.AMBIENT_SOURCE_ROTATION:
                rotation = (plan.get("audio") or {}).get("bed_rotation")
                ambient_file = ambient_bed.bed_from_rotation(
                    rotation, beds, plan_hint=f" ({args.plan})")
                ambient_source = ambient_bed.AMBIENT_SOURCE_ROTATION
            elif beds:
                ambient_file, ambient_source = beds[0]
        if ambient_file is None:
            # No --channel, or a channel with no bed at all. This is the
            # substitution the task was raised about: the video shipped with
            # the generator at -18 dB where the channel had chosen -25, and
            # nothing said so. The level split stays (CF-0165 calibrated the
            # generator on its own noise carpet); the silence does not.
            substituted = ambient_bed.BED_SUBSTITUTED_NO_CHANNEL_BED
    else:
        ambient_file = Path(args.music)
        ambient_source = ambient_bed.AMBIENT_SOURCE_CLI
        if not ambient_file.exists():
            raise ambient_bed.AmbientBedError(
                f"--music names {args.music!r} and there is no file at {ambient_file}")

    ambient = None
    bed_gain_db = 0.0
    if ambient_file is None:
        bed_path = work / "_bed.wav"
        write_wav(bed_path, bed(total, fade_out_seconds=bed_fade_out))
        bed_src, licence = str(bed_path), "generated locally - nothing to clear"
    else:
        # The reference the file is levelled against is the bed this same mix
        # would otherwise have generated, at this same length and with this
        # same fade - so a channel with a file and a channel without one reach
        # qc_render.py's floors identically and the gate needs no changes
        # (decision 3). See ambient_bed.prepare().
        bed_path = work / "_ambient.wav"
        ambient = ambient_bed.prepare(ambient_file, total, bed_path,
                                      bed(total, fade_out_seconds=bed_fade_out),
                                      source=ambient_source,
                                      fade_out_seconds=bed_fade_out)
        bed_src, bed_gain_db = str(bed_path), ambient["gain_db"]
        licence = (f"supplied: {ambient['name']} - the channel's own file "
                   f"({ambient_source}); licence is the caller's to hold")
        # CF-0271: the rotation's own three facts travel with the file, so the
        # batch record can say which of the channel's beds played without
        # anyone re-hashing the script_id to find out.
        ambient["rotation_index"] = rotation.get("index") if rotation else None
        ambient["rotation_size"] = len(rotation.get("beds") or []) if rotation else None
        ambient["chosen_by"] = rotation.get("chosen_by") if rotation else None
    # CF-0271: one line in the run's own accounting, by the convention
    # build_render_plan.py annotates its gates with - which bed played, and in
    # capitals when it was not the one the channel asked for. The substitution
    # this task exists to stop is now an event in RUN_EVENTS.jsonl and a line
    # in the run report, not a field nobody opens.
    if substituted:
        bed_annotation = ambient_bed.substitution_annotation(substituted)
    elif ambient and ambient.get("rotation_size"):
        bed_annotation = (f"{ambient['name']} "
                          f"[{(ambient['rotation_index'] or 0) + 1}/{ambient['rotation_size']}]")
    else:
        bed_annotation = ambient["name"]
    runlog.annotate(bed=bed_annotation)
    # CF-0165: at what level. The channel's own number applies to the file the
    # channel brought and to nothing else - the generator keeps the level
    # CF-0025 calibrated it at, so `--music generated` stays comparable to
    # every measurement ever made on it, and a channel whose file is missing
    # falls back to the generator at the generator's level rather than at a
    # number chosen by ear for a different sound. `--bed-db` beats both.
    # See ambient_bed.bed_db() for why the split, and for the measured point.
    bed_db_value, bed_db_source = ambient_bed.bed_db(
        channel_cfg if ambient is not None else None, cli_value=args.bed_db)
    # What the graph actually puts on the bed input. The level above is the
    # level the *bed itself* is mixed at, and the ambient's normalising gain is
    # added to it rather than baked into the samples: a file that needs lifting
    # would otherwise clip the int16 intermediate, and the level goes on
    # meaning the one thing it has always meant.
    bed_volume_db = round(bed_db_value + bed_gain_db, 3)

    # Cuts, not the punches: an accent belongs to a change of picture. The first
    # block starts with the video, where a hit would land on nothing.
    cuts = [b["start"] for b in plan["blocks"][1:]]
    accent_path = work / "_accents.wav"
    if not cuts:
        write_wav(accent_path, np.zeros(int(total * SR)))
    else:
        write_wav(accent_path, accents(total, cuts))

    # CF-0068: the fourth input. Only when a sound was placed and read -
    # otherwise the three-input graph below is untouched, so a plan without
    # a sound mixes byte-identically to one built before the layer existed.
    placed = sound_layer.placed_sounds(plan)
    sound_lines, inserts_path = [], None
    if placed:
        voice_level = rms_db(read_mono(args.voice))
        track, sound_lines = inserts_track(total, placed, voice_level)
        if np.any(track):
            inserts_path = work / "_inserts.wav"
            write_wav(inserts_path, track)

    # The bed is ducked by the voice itself, so it lifts in the gaps between
    # sentences and stays out of the way under them.
    #
    # CF-0117: two fragments carry the end card, and they are built once here
    # for both graphs below.
    #   `pad`   the voice is padded with silence to the composition's length.
    #           `amix=duration=first` takes its length from this input, so
    #           without the pad the whole mix would still stop on the last
    #           word and the card would play over nothing. The pad is silence
    #           keying the sidechain, so the duck releases and the bed comes
    #           up under the card - which is the intent: no voice, the bed
    #           alone, then out.
    #   `fade`  the bed fades to nothing across the card, from the card's
    #           start to the end of the file. In the graph rather than in
    #           bed() because a supplied --music track has to fade the same
    #           way, and one fade in one place cannot disagree with itself.
    #
    # CF-0141: and a third shape, for the ending that actually ships. When the
    # video closes on the channel's own clip the bed does not play under it at
    # all - it is brought to silence *by* the clip's first frame and stays
    # there. Decision 2: the clip arrives with a track mixed for it, and that
    # track is what the viewer hears; a bed under it would be this factory
    # scoring somebody else's finished piece. So the fade moves earlier by its
    # own length instead of spanning the ending, and the mix over the ending
    # interval is silence - which is also what makes the render gate's
    # excusal of that interval safe to read (decision 3): there is nothing of
    # ours there to measure.
    #
    # The fade is BED_FADE_SECONDS, the bed's own tail fade, and not the
    # ending's length: how long a bed takes to leave is a property of the bed,
    # and tying it to the clip would make a 12 s ending fade the bed out from
    # the middle of the last sentence.
    is_clip = (card.get("variant") == "clip") if card_seconds else False
    card_start = float(card.get("start_s") or seconds) if card_seconds else None
    pad = f",apad=whole_dur={total:.3f}" if card_seconds else ""
    if not card_seconds:
        fade = ""
        bed_fade_from = bed_fade_seconds = None
    elif is_clip:
        bed_fade_seconds = min(BED_FADE_SECONDS, max(0.05, card_start))
        bed_fade_from = max(0.0, card_start - bed_fade_seconds)
        fade = f",afade=t=out:st={bed_fade_from:.3f}:d={bed_fade_seconds:.3f}"
    else:
        bed_fade_from, bed_fade_seconds = card_start, card_seconds
        fade = f",afade=t=out:st={card_start:.3f}:d={card_seconds:.3f}"
    # CF-0695: the voice goes in through a gentle compressor (3:1, threshold
    # 6 dB over its own loudness, its loudness given back as makeup) - the
    # voice stem, `_voice.wav`, recorded as audio.loudness.voice. It keys the
    # duck as before; only its envelope is evened. See loudness.compress_voice().
    voice_stem = work / "_voice.wav"
    try:
        voice_rec = loudness.compress_voice(args.voice, voice_stem, SR, seconds=seconds)
    except RuntimeError as e:
        print(f"voice compression failed: {e}", file=sys.stderr)
        sys.exit("mixing failed")
    inputs = ["-i", str(voice_stem), "-i", bed_src, "-i", str(accent_path)]
    if inserts_path is None:
        graph = (
            f"[1:a]volume={bed_volume_db}dB,aformat=channel_layouts=mono{fade}[bed];"
            f"[2:a]volume={args.accent_db}dB,aformat=channel_layouts=mono[acc];"
            f"[0:a]aformat=channel_layouts=mono{pad},asplit=2[v1][vkey];"
            f"[bed][vkey]{DUCK}[duck];"
            f"[v1][duck][acc]amix=inputs=3:duration=first:normalize=0[mix];"
            # Leave headroom under the render gate's -0.5 dB clipping check,
            # rather than landing just inside it.
            f"[mix]alimiter=limit=0.88[out]"
        )
    else:
        # The sound keys the bed the way the voice does (SOUND_DUCKS_BED) and
        # never touches the voice (SOUND_DUCKS_VOICE is False: [v1] goes to
        # the mix exactly as above). The constants are asserted, not read,
        # because the graph *is* the decision and a flag flipped without
        # rewriting it would be a lie about what was mixed.
        assert SOUND_DUCKS_BED and not SOUND_DUCKS_VOICE
        inputs += ["-i", str(inserts_path)]
        graph = (
            f"[1:a]volume={bed_volume_db}dB,aformat=channel_layouts=mono{fade}[bed];"
            f"[2:a]volume={args.accent_db}dB,aformat=channel_layouts=mono[acc];"
            f"[3:a]aformat=channel_layouts=mono,asplit=2[ins][inskey];"
            f"[0:a]aformat=channel_layouts=mono{pad},asplit=2[v1][vkey];"
            f"[bed][vkey]{DUCK}[duck1];"
            f"[duck1][inskey]{DUCK}[duck];"
            f"[v1][duck][acc][ins]amix=inputs=4:duration=first:normalize=0[mix];"
            f"[mix]alimiter=limit=0.88[out]"
        )
    # The mix runs the length of the composition (`amix=duration=first` off
    # the padded voice), so that is the material the ceiling is derived from.
    #
    # CF-0695: the graph's output is the *premaster* now - float, so a gain
    # up from it loses nothing to the int16 floor - and the file at
    # args.output is that premaster brought to the channel's loudness by
    # loudness.master() below: one static gain, a 4x-oversampled limiter
    # holding the true peak under the ceiling and allowed at most
    # loudness.MAX_LIMITER_GR_DB of work. Never `loudnorm`: it reached -14 on
    # the 2026-10-12 preview by squeezing the loudness range from 11.9 to
    # 5.6 LU.
    premaster = work / "_premaster.wav"
    result = ffmpeg(*inputs, "-filter_complex", graph, "-map", "[out]",
                    "-ar", str(SR), "-ac", "1", "-c:a", "pcm_f32le", str(premaster),
                    media_seconds=total)
    # The argv as it was actually run - built by the helper now, read back off
    # the CompletedProcess, so the log still shows the command and not a
    # reconstruction of it.
    cmd = list(result.args)
    quiet.append_text(log, "$ " + " ".join(cmd) + "\n" + result.stderr +
                      f"=== end build_soundtrack rc={result.returncode} ===\n",
                      step="build_soundtrack (ffmpeg mix)", slug=ctx.slug if ctx else None)
    if result.returncode != 0:
        if args.summary and log is not None:
            tail = [l for l in result.stderr.splitlines() if l.strip()][-quiet.TAIL_LINES:]
            quiet.summary([f"soundtrack FAILED  rc={result.returncode}  (ffmpeg mix)"]
                          + [f"  | {t}" for t in tail], log)
        else:
            print(result.stderr, file=sys.stderr)
        sys.exit("mixing failed")

    # CF-0695: the loudness pass. The mix over the ending clip's interval is
    # silence (CF-0141), which EBU R128's gate leaves out, so what is measured
    # here is the part of the file this factory mixed; the clip's own track is
    # levelled to the same target by the static volume the render plays it at
    # (`audio.loudness.ending.volume`, read by EndCard.jsx), and qc_render.py
    # measures the two together in the finished file.
    try:
        level = loudness.master(premaster, args.output, target_lufs, true_peak_db,
                                SR, seconds=total)
    except RuntimeError as e:
        quiet.append_text(log, f"loudness pass failed: {e}\n",
                          step="build_soundtrack (loudness)",
                          slug=ctx.slug if ctx else None)
        print(f"loudness pass failed: {e}", file=sys.stderr)
        sys.exit("mixing failed")
    ending_level = None
    if is_clip and card.get("path") and Path(card["path"]).exists():
        # The clip is levelled to where the mix *landed*, not to the bare
        # target: when the limiter cap leaves the mix short, an ending at the
        # full target would jump up by the shortfall in the last five seconds
        # (measured on the 2026-10-12 demo: body -17.5, ending -14.1 LUFS).
        # One level through the whole video first; the target when reached.
        landed = (level.get("after") or {}).get("integrated_lufs")
        ending_target = min(target_lufs, landed) if landed is not None else target_lufs
        ending_level = loudness.ending_level(card["path"], ending_target, true_peak_db,
                                             seconds=card_seconds)
        ending_level["target_lufs"] = round(ending_target, 2)
    level.update({"source": loudness_source, "ending": ending_level,
                  "voice": voice_rec,
                  "measured_on": "the mix as the render plays it (dual-mono "
                                 "stereo, the voice at 0 dB in both channels); "
                                 "the ending clip's own track separately"})

    # CF-0025: the plan records that a bed was mixed and at what level, so
    # qc_render.py can tell "the bed measured -40 dB" from "no bed was ever
    # mixed" - and can fail the second case instead of reporting `null` and
    # gating on nothing, which is how a silent bed shipped four videos. Same
    # pattern as end_card.apply_to_plan() / sound_layer.apply_to_plan(): the
    # step that did the work writes what it did back onto the plan. A plan
    # that cannot be written (a read-only re-mix off a shipped batch) says so
    # and changes nothing else - the mix is already on disk.
    #
    # CF-0153 (section E): `source` used to be read off the CLI argument, so a
    # run that asked for the channel's file and got the generator (no
    # --channel, or a channel without one) would still have been recorded as
    # `supplied`. It is read off what was actually mixed now, and when that is
    # a file, `ambient` says which file, where it was found, how many times it
    # was looped and how far it was lifted to sit where the generated bed
    # sits. `null` on a generated bed, always present, so absence never has to
    # be interpreted - the same promise the end card's delivered record makes.
    plan.setdefault("audio", {})["bed"] = {
        "src": bed_src,
        "source": "generated" if ambient is None else "supplied",
        "ambient": ambient,
        "bed_db": bed_db_value,
        # CF-0165: and where that number came from - cli | config | default.
        # A level nobody can trace is how the user's choice got lost once
        # already; the plan now says whether the mix obeyed the channel or a
        # flag somebody typed.
        "bed_db_source": bed_db_source,
        # CF-0271: why the generator played, when it did - `no_channel_bed`
        # (the run asked the channel and the channel had none) or
        # `operator_forced_generated` (--music generated). `null` when the
        # channel's own file played, so the unusual run is legible by a value
        # being there rather than by comparing two fields that look alike.
        "substituted": substituted,
        # And which of the channel's beds this was, as the plan chose it: the
        # mixer copies the choice rather than making one.
        "rotation": rotation,
        "bed_volume_db": bed_volume_db,
        "duck": DUCK,
        "audible_band_hz": BED_AUDIBLE_BAND_HZ,
        "target_gaps_db": BED_TARGET_GAPS_DB,
        "target_speech_db": BED_TARGET_SPEECH_DB,
        "fade_out_s": bed_fade_seconds or BED_FADE_SECONDS,
        # CF-0141: when the video ends on the channel's clip the bed is not
        # merely quieter over it - it is gone before it starts. The gate
        # reads this to know that silence there is the mix doing what it was
        # told, and the batch record keeps the number that was actually used.
        "silent_from_s": round(card_start, 3) if is_clip else None,
        "ending_variant": card.get("variant") if card_seconds else None,
        "mix": str(Path(args.output).resolve()),
    }
    # CF-0695: before/after, the gain, the limiter's work and any shortfall -
    # what qc_render.py compares the finished file against.
    plan["audio"]["loudness"] = level
    bed_recorded = True
    try:
        json.dump(plan, open(args.plan, "w"), indent=2)
    except OSError as e:  # noqa: BLE001
        bed_recorded = False
        bed_record_error = str(e)

    looped = "" if ambient is None else (
        f"looped {ambient['loops']}x with a {ambient['crossfade_s']:.2f}s crossfade"
        if ambient["loops"] > 1 else "used whole")
    report = [f"soundtrack -> {args.output}",
              f"  bed: {licence}",
              *([f"  SUBSTITUTED: the generated bed played, not the channel's file "
                 f"({substituted}) - mixed at {bed_db_value} dB "
                 f"({bed_db_source}), the generator's own calibrated level "
                 f"(CF-0165), and recorded as bed.substituted on the plan"]
                if substituted else []),
              *([f"  rotation: {ambient['rotation_index'] + 1} of "
                 f"{ambient['rotation_size']}, chosen by {ambient['chosen_by']} "
                 f"from {rotation.get('key')!r} in the plan"]
                if ambient and ambient.get("rotation_size") else []),
              *([f"  ambient: {ambient['path']} - {ambient['file_seconds']:.2f}s "
                 f"{looped} to cover {total:.2f}s, lifted {ambient['gain_db']:+.1f} dB "
                 f"to the generated bed's {ambient['reference_band_rms_db']:.1f} dB "
                 f"above {BED_AUDIBLE_BAND_HZ:.0f} Hz"] if ambient else []),
              (f"  ending: the mix runs {total:.2f}s "
               f"({seconds:.2f}s voice + {card_seconds:.2f}s clip), the voice is "
               f"padded with silence and the bed is faded to nothing over the "
               f"{bed_fade_seconds:.2f}s before {card_start:.2f}s - the clip's "
               f"own track is what plays over it"
               if card_seconds and is_clip else
               f"  end card: the mix runs {total:.2f}s "
               f"({seconds:.2f}s voice + {card_seconds:.2f}s card), the voice is "
               f"padded with silence and the bed fades out across the card"
               if card_seconds else
               f"  end card: none in the plan - the mix is the voice's "
               f"{seconds:.2f}s"),
              f"  accents: {len(cuts)} at scene changes",
              _voice_line(voice_rec),
              _loudness_line(level),
              *([_ending_line(ending_level)] if ending_level else []),
              f"  inserts: {len(placed)} sound(s) placed by the plan, "
              f"{'mixed as the fourth input' if inserts_path else 'none mixed'}",
              (f"  bed level: {bed_db_value} dB ({bed_db_source}), recorded on "
               f"the plan as audio.bed - the QC gate measures it in the mix"
               if bed_recorded else
               f"  bed level: {bed_db_value} dB ({bed_db_source}), NOT recorded "
               f"on the plan "
               f"({bed_record_error}) - qc_render.py will not know a bed was "
               f"mixed")]
    report += [f"    {line}" for line in sound_lines]
    quiet.append_text(log, "\n".join(report) + "\n")
    if args.summary and log is not None:
        quiet.summary(report, log)
    else:
        for line in report:
            print(line)


def _fmt(m):
    if not m or m.get("integrated_lufs") is None:
        return "unmeasurable"
    tp = m.get("true_peak_db")
    return (f"{m['integrated_lufs']:.1f} LUFS, TP {tp:+.1f} dBTP, "
            f"LRA {m.get('lra_lu') or 0:.1f} LU" if tp is not None else
            f"{m['integrated_lufs']:.1f} LUFS")


def _loudness_line(level):
    """CF-0695: one report line for the loudness pass."""
    head = (f"  loudness: {_fmt(level['before'])} -> {_fmt(level['after'])} "
            f"(target {level['target_lufs']} LUFS / {level['true_peak_db']} dBTP, "
            f"{level['source']}; static gain {level['gain_db']:+.1f} dB, limiter "
            f"{level['limiter_gr_db']:.1f} dB)")
    if level.get("shortfall_db"):
        head += (f" - SHORT by {level['shortfall_db']:.1f} dB: the limiter cap "
                 f"({loudness.MAX_LIMITER_GR_DB:.0f} dB) was reached rather than "
                 f"squash the mix")
    return head


def _voice_line(v):
    """CF-0695: one report line for the voice stem's compressor."""
    if v.get("skipped"):
        return f"  voice: {v['skipped']} - mixed uncompressed"
    gr = v.get("gr") or {}
    return (f"  voice: compressed {v['params']['ratio']:.0f}:1 over "
            f"{v['params']['threshold_db']:.1f} dB, makeup {v['makeup_db']:+.1f} dB; "
            f"peak-to-loudness {v['plr_before_db']} -> {v['plr_after_db']} dB; "
            f"{100 * (gr.get('compressed_share') or 0):.0f}% of voiced 10 ms windows "
            f"compressed, mean {gr.get('mean_gr_db')} dB, max {gr.get('max_gr_db')} dB")


def _ending_line(ending):
    if ending.get("unmeasured"):
        return f"  ending clip: {ending['unmeasured']} - played at volume 1.0"
    return (f"  ending clip: {_fmt(ending['before'])}, played by the render at "
            f"{ending['gain_db']:+.1f} dB (volume {ending['volume']}) to sit at "
            f"{ending.get('target_lufs')} LUFS with the mix"
            + (f" - SHORT by {ending['shortfall_db']:.1f} dB (its own true peak "
               f"caps the gain)" if ending.get("shortfall_db") else ""))


@video_script("video-editor", "soundtrack", name="build_soundtrack.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

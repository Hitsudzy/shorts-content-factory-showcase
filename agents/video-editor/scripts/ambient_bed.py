#!/usr/bin/env python3
"""CF-0153: the background bed is a file the channel brings with it.

CF-0025 made the generated bed audible and the user listened to it: it reads
as a cooling fan. Above 500 Hz the generator is very nearly pure noise, and a
phone speaker radiates exactly that band best. The measurement is in CF-0025;
the conclusion was the user's and is not re-derived here.

So the bed follows the ending clip (CF-0141): **a finished file the channel
brings with it**, sitting beside `stance.json` and `ending.mp4` in the
channel's own directory. What it is depends on the channel's subject - a
barely-there film projector for cinema and television, rain for spoken
stories - which is a decision about the channel, not a thing this repository
can synthesise. `build_soundtrack.py` still generates a bed for a channel that
has no file; that generator is **not** repaired (decision 2), it is the floor
for channels that do not exist yet.

Three decisions of 2026-09-08, recorded so nothing here re-opens them:

  1. **Source.** The user brings the file and puts it beside `ending.mp4`.
     Nothing is generated, searched for on a stock site or fetched.
  2. **Floor.** No file -> the generator, byte-identically to today.
  3. **The gate does not judge taste.** The file was approved once, when the
     channel was set up - the same logic as decision 3 of CF-0141.
     `qc_render.bed_audibility_db()` is untouched and goes on answering the
     one question it was built for: does the bed sit at the level it should.

**What this module refuses, and when.** Everything below happens *before* the
mix runs, off ffprobe and the decoded samples, and every refusal is an
`AmbientBedError` naming the file and what is wrong with it. The doctrine is
`EndCardError`'s (CF-0141): the behaviour of a channel asset is written down,
not discovered while ffmpeg is running.

  * the config names a file that is not on disk;
  * the file carries no audio stream, or ffprobe cannot read it at all;
  * it is shorter than `AMBIENT_MIN_SECONDS`;
  * it holds no usable energy above `BED_AUDIBLE_BAND_HZ` (see
    `AMBIENT_MAX_GAIN_DB`).

**Short files loop, they are not refused** (section B of the task). Both were
open; looping is what shipped, and the reasoning is in `loop_to()`.

**CF-0271: the channel may bring three files instead of one.** The user heard
the single bed under a run of videos and asked for a rotation, so
`video_editor.ambient.beds` is a list and `ambient_beds()` reads it. Which one
plays is a pure function of the `script_id` (`bed_index()`), decided in
`build_render_plan.py` and recorded on the plan as `audio.bed_rotation`;
`build_soundtrack.py` only executes that choice. Nothing else about a bed
changed: the same gate, the same level, the same preparation, one of three
files instead of one of one.

Not a CLI. `build_soundtrack.py` is the only caller.
"""
import hashlib
import math
from pathlib import Path

import numpy as np

from common import (BED_AUDIBLE_BAND_HZ, BED_FADE_SECONDS, ffmpeg,
                    ffmpeg_stderr, probe_json)

# The mixer's sample rate. Imported by build_soundtrack.py rather than the
# other way round would be a cycle, so it is stated once here and asserted
# against build_soundtrack.SR by the tests.
SR = 44100

# Where the channel's ambient file lives by convention: its own directory,
# beside `stance.json`, `logo.png` and `ending.mp4`. `video_editor.ambient
# .path` overrides it, exactly as `video_editor.ending.path` overrides the
# ending clip. The stem is fixed and the extension is not - the user brings
# whatever their source gave them, and ffmpeg decodes all of these.
AMBIENT_STEM = "ambient"
AMBIENT_EXTS = (".wav", ".flac", ".aif", ".aiff", ".m4a", ".mp3", ".aac",
                ".ogg", ".opus")

AMBIENT_SOURCE_CONFIG = "config"          # video_editor.ambient.path
AMBIENT_SOURCE_CONVENTION = "convention"  # channels/<channel_id>/ambient.<ext>
AMBIENT_SOURCE_CLI = "cli"                # --music <file>, a one-off
AMBIENT_SOURCE_ROTATION = "rotation"      # video_editor.ambient.beds, one of several

# CF-0271: the rotation form of the same setting. The user listened to one bed
# under sixty videos and asked for three, so `video_editor.ambient` may name a
# *list*:
#
#     "video_editor": {"ambient": {"beds": ["channels/c/beds/a.mp3", ...]}}
#
# `path` (one file) and `beds` (a rotation) are the same decision said two
# ways, and a config that says both has not decided - see ambient_beds().
AMBIENT_BEDS_KEY = "beds"

# The floor on the supplied file's own length, and the reason for it. A bed
# runs under the whole video (55-70 s), so a file shorter than that has to
# repeat; the question section B leaves open is whether it repeats or is
# refused, and the answer is that it repeats above this floor and is refused
# below it.
#
# 8 s, because that is where a loop stops being texture and starts being a
# rhythm. A crossfaded loop of rain or projector hiss is inaudible as a loop -
# the material is stationary, and the seam is the only event in it. A 2 s file
# repeats seven times in a 15 s stretch, and *that* is a pulse the ear locks
# on to, sitting under a narration it has nothing to do with. The floor is not
# a measurement (it is the shortest file a stock ambient is ever delivered as,
# and shorter than any usable one); it is the line under which looping stops
# being the harmless answer, and a channel that hits it has brought a sound
# effect where a bed was asked for.
AMBIENT_MIN_SECONDS = 8.0

# The seam. Equal-power (sqrt) crossfade over this many seconds at every
# repeat, so the loop point has no click and no dip in level. Long enough that
# a transient landing on the seam is smeared rather than cut, short enough not
# to eat a quarter of a minimum-length file.
AMBIENT_CROSSFADE_SECONDS = 0.75

# The prepared file is written at this peak. It is not the level the bed plays
# at - that is set in the mix graph, see `gain_db` in prepare() - it is only
# headroom, so that an int16 intermediate cannot clip before the graph gets
# to decide anything.
AMBIENT_PEAK = 0.9

# How far the normaliser may lift the supplied file to reach the generated
# bed's level in the audible band. A file that needs more than this has
# essentially nothing above BED_AUDIBLE_BAND_HZ - which is precisely the
# defect CF-0025 found in the generator, and lifting it 30 dB would raise its
# hiss with it. Refused instead: it is the wrong file, not a quiet one.
AMBIENT_MAX_GAIN_DB = 24.0

# CF-0165: at what level the *supplied* file is mixed, and where that number
# lives. `--bed-db` was a hardcoded default in build_soundtrack.py, so the
# level the user picked by ear (2026-09-09, three steps auditioned, -25 chosen
# for example-film) lived in one command line and would have been lost on
# the next run. It is a channel setting now, beside the file it applies to:
#
#     "video_editor": {"ambient": {"bed_db": -25}}
#
# Absent -> DEFAULT_BED_DB, which is today's number, so a channel without the
# key mixes exactly as it did. `--bed-db` still wins over both: it is the
# debug flag for auditioning a level, not where the decision is kept.
#
# **The key belongs to the supplied file and not to the generator** (step 2 of
# CF-0165). BED_TARGET_GAPS_DB / BED_TARGET_SPEECH_DB in build_soundtrack.py
# were calibrated on the generator - a flat noise carpet - and a brought-in
# file is structural: the fire this channel brought has sparse clicks in it,
# and at equal RMS transients take attention that an even carpet does not.
# That is why the same number reads louder. So the generator keeps its own
# calibration and a channel's number moves only the file it was chosen on;
# a run forced back to the generator (`--music generated`) is unaffected and
# stays comparable to every measurement CF-0025 made.
#
# One measured point, deliberately not generalised into a constant for
# brought-in files as a class - there is exactly one such file to measure. At
# -25 on legacy-film' ambient.mp3 the bed lands (qc_render.py's own
# instrument, >200 Hz, in the finished mix): cf0141-fullrun -37.1 dB
# (`word_gaps`, floor -38.0), wren-hollow-christmas -43.0 dB
# (`under_speech`, floor -44.0), raygun-sneak-peek -37.0 dB (`word_gaps`,
# floor -38.0) - about 1.0 dB of headroom on all three, systematically. If
# qc_render starts failing the bed, that is where it comes from, and the fix
# is this number, never the gate's floor (decision 3 of CF-0153). The run and
# slug names above (cf0141-fullrun, wren-hollow-christmas, raygun-sneak-peek;
# the run's directory work/cf0141-fullrun/ is archived by CF-0498 into
# Archive:shorts-content-factory-cleanup-1.6/video-editor-code-2026-10-03.zip)
# are what was measured on 2026-09-09, under the channel's former id
# legacy-film; they date the measurement and were left as they were when
# the channel became example-film (CF-0180).
DEFAULT_BED_DB = -18.0
CHANNEL_BED_DB_KEY = "video_editor.ambient.bed_db"

BED_DB_SOURCE_CLI = "cli"          # --bed-db, an audition, not a decision
BED_DB_SOURCE_CONFIG = "config"    # video_editor.ambient.bed_db
BED_DB_SOURCE_DEFAULT = "default"  # DEFAULT_BED_DB

# What a number in that key may be. Not taste - taste is the user's and was
# settled by ear - only the range in which the key means what it says. Above
# 0 dB the file is mixed louder than the reference bed it was levelled to and
# the int16 intermediate clips; under -60 dB the bed is inaudible and every
# render fails the gate. Either is a typo, and a typo here is exactly the
# silent 7 dB this task exists to stop.
BED_DB_RANGE = (-60.0, 0.0)


class AmbientBedError(Exception):
    """The channel's ambient file cannot be used, and the mix is not run.

    Deliberately not a fallback to the generator: a channel that names an
    ambient and cannot produce a usable one is a broken channel, exactly as
    with the ending clip, and quietly substituting the fan noise the user
    rejected would hide the fault in the one place nobody looks - the audio of
    a video that otherwise passed.
    """


def ambient_path(channel_cfg, root, channel=None):
    """(path, source) for the channel's ambient file, or (None, None).

    `video_editor.ambient.path` first - the config's own answer, resolved
    against the factory root when relative, and *not* silently dropped when it
    points at nothing. Then the convention `channels/<channel_id>/ambient.<ext>`,
    the extensions tried in AMBIENT_EXTS order. Neither is not an error: that
    is the channel that falls back to the generated bed (decision 2).
    """
    ve = (channel_cfg or {}).get("video_editor") or {}
    named = (ve.get("ambient") or {}).get("path") if isinstance(ve, dict) else None
    if isinstance(named, str) and named.strip():
        p = Path(named.strip())
        if not p.is_absolute():
            p = Path(root) / p
        if not p.exists():
            raise AmbientBedError(
                f"the channel config names video_editor.ambient.path {named!r} and "
                f"there is no file at {p} - a channel that says it has an ambient bed "
                f"and cannot produce it is not a channel without one, and the "
                f"generated bed is not quietly substituted for the file the channel "
                f"named")
        return p, AMBIENT_SOURCE_CONFIG
    channel_id = (channel_cfg or {}).get("channel_id")
    if not channel_id:
        return None, None
    base = Path(channel).resolve().parent if channel and str(channel).endswith(".json") \
        else Path(root) / "channels"
    for ext in AMBIENT_EXTS:
        cand = base / str(channel_id) / f"{AMBIENT_STEM}{ext}"
        if cand.exists():
            return cand, AMBIENT_SOURCE_CONVENTION
    return None, None


def ambient_beds(channel_cfg, root, channel=None):
    """[(path, source)] - every file the channel offers as a bed, in order.

    CF-0271. The same four-step doctrine as `ambient_path()`, widened by one
    step at the top:

      1. `video_editor.ambient.beds` - a list, resolved against the factory
         root when relative. Every entry has to be on disk: a rotation with a
         hole in it is a run of videos carrying a bed nobody chose, so a named
         and missing file raises here exactly as it does for `path`, instead
         of quietly shrinking the rotation or falling through to the
         generator.
      2. `video_editor.ambient.path` - the single-file form, read by
         `ambient_path()` and unchanged: other channels and every batch built
         before this task still mix as they did.
      3. Both keys at once - `AmbientBedError`. The root refuses this too
         (`VIDEO_EDITOR_EXCLUSIVE_KEYS`), and that is not a reason for the
         Editor to assume someone validated the config before handing it over.
      4. Neither - the convention, then the generator, as before. `[]` is the
         channel with no bed at all, not an error (decision 2 of CF-0153).

    The list keeps its config order, because the choice below indexes into it
    and an order that shuffled would make the recorded index unverifiable.
    """
    ve = (channel_cfg or {}).get("video_editor") or {}
    # Spelt out rather than built from AMBIENT_BEDS_KEY because the root's
    # tests/test_video_editor_channel_assets.py reads this accessor out of
    # this file's source to prove the two repositories agree on the key
    # (CF-0098); the same is true of the `path` line under it.
    listed = (ve.get("ambient") or {}).get("beds") if isinstance(ve, dict) else None
    named = (ve.get("ambient") or {}).get("path") if isinstance(ve, dict) else None
    if listed is None:
        path, source = ambient_path(channel_cfg, root, channel)
        return [] if path is None else [(path, source)]
    if isinstance(named, str) and named.strip():
        raise AmbientBedError(
            f"the channel config names both video_editor.ambient.path ({named!r}) and "
            f"video_editor.ambient.{AMBIENT_BEDS_KEY} ({len(listed) if isinstance(listed, list) else listed!r} "
            f"entries) - one file and a rotation are the same decision said twice, and "
            f"which of the two plays would be decided by the order this code happens to "
            f"read them in. Keep one")
    if isinstance(listed, str) or not isinstance(listed, (list, tuple)):
        raise AmbientBedError(
            f"video_editor.ambient.{AMBIENT_BEDS_KEY} is {listed!r}, which is not a list "
            f"of files. One file goes in video_editor.ambient.path; a rotation is a list")
    if not listed:
        raise AmbientBedError(
            f"video_editor.ambient.{AMBIENT_BEDS_KEY} is an empty list - a channel that "
            f"says it rotates beds and offers none is not a channel without a bed, and "
            f"the generated bed is not quietly substituted for the rotation the channel "
            f"named")
    beds = []
    for i, entry in enumerate(listed):
        if not isinstance(entry, str) or not entry.strip():
            raise AmbientBedError(
                f"video_editor.ambient.{AMBIENT_BEDS_KEY}[{i}] is {entry!r}, which is not "
                f"a path to a file")
        p = Path(entry.strip())
        if not p.is_absolute():
            p = Path(root) / p
        if not p.exists():
            raise AmbientBedError(
                f"the channel config names video_editor.ambient.{AMBIENT_BEDS_KEY}[{i}] "
                f"{entry!r} and there is no file at {p} - a rotation with a hole in it "
                f"would put a bed nobody chose under every video whose hash lands on the "
                f"hole, and the generated bed is not quietly substituted for a file the "
                f"channel named")
        beds.append((p, AMBIENT_SOURCE_ROTATION))
    return beds


# How the rotating bed is chosen, written next to the choice on the plan so a
# reader can *recheck* it rather than believe it: "index 2" says which file
# played and says nothing about why that one.
BED_CHOSEN_BY_SCRIPT_ID = "sha256(script_id)"


def bed_index(count, key):
    """Which of `count` beds plays under the video keyed `key`.

    sha256 of the key, and deliberately **not** the built-in `hash()`: that is
    salted per process (`PYTHONHASHSEED`), so the same video would draw a
    different bed on its second render attempt - `video_editor
    .max_attempts_per_video` is 3 and `qc_render` sends videos back to the mix
    - and a remix a month later would draw a third. This function is the whole
    rotation mechanism precisely because it is pure: same key, same file, any
    attempt, any machine, any year, with no registry to keep and nothing to
    backfill. (The bed is not assigned through `rotation/` for the reasons
    written into CF-0271: that registry hands out (pattern, rhythm) pairs
    before the script is written, with refusals and a no-repeat window, and a
    bed is none of those things.)

    Uniformity is binomial, not round-robin: 90 videos over three beds is
    30 +/- 4.5. That is a deliberate trade - nobody counts how often a lofi
    track played, and the alternative is per-attempt state.
    """
    if count <= 0:
        raise AmbientBedError("no beds to choose from")
    digest = hashlib.sha256(str(key).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % int(count)


def choose_bed(beds, key):
    """Which bed plays under `key`. Pure function: see bed_index()."""
    return beds[bed_index(len(beds), key)]


def rotation_record(beds, key, chosen_by=BED_CHOSEN_BY_SCRIPT_ID):
    """`plan["audio"]["bed_rotation"]` - the choice and enough to recheck it.

    `beds` is what ambient_beds() returned. Paths are absolute, as every other
    path on the plan is (`audio.src`, `audio.bed.ambient.path`), so that the
    mixer resolves nothing twice and a copy of the plan means the same files.
    """
    paths = [str(Path(p).resolve()) for p, _ in beds]
    i = bed_index(len(paths), key)
    return {"beds": paths, "chosen": paths[i], "index": i,
            "key": str(key), "chosen_by": chosen_by}


def bed_from_rotation(rotation, beds, plan_hint=""):
    """The file `rotation` chose, checked against what the channel offers now.

    Raises rather than choosing for itself, on this module's usual doctrine: a
    plan built before the rotation existed does not carry the choice, and
    guessing one here would mean two places decide which bed plays and a
    rebuild of the plan could silently change the audio of a video that was
    already approved.
    """
    have = {str(Path(p).resolve()) for p, _ in beds}
    if not isinstance(rotation, dict) or not rotation.get("chosen"):
        raise AmbientBedError(
            f"the channel rotates {len(have)} beds (video_editor.ambient."
            f"{AMBIENT_BEDS_KEY}) and the plan carries no audio.bed_rotation, so which "
            f"one plays under this video was never decided. build_render_plan.py makes "
            f"that choice from the script_id; rebuild the plan{plan_hint}. The bed is "
            f"not chosen here instead - two places choosing would mean a rebuilt plan "
            f"could change the sound of a video that was already approved")
    chosen = str(Path(rotation["chosen"]).resolve())
    if chosen not in have:
        raise AmbientBedError(
            f"the plan's audio.bed_rotation chose {rotation['chosen']} and the channel "
            f"does not offer it any more (video_editor.ambient.{AMBIENT_BEDS_KEY} names "
            f"{len(have)} file(s)). The rotation changed under a plan that had already "
            f"chosen from it; rebuild the plan{plan_hint}")
    return Path(chosen)


def bed_db(channel_cfg, cli_value=None):
    """(level, source) for the supplied bed: `--bed-db`, else the channel's
    `video_editor.ambient.bed_db`, else DEFAULT_BED_DB.

    A key that is present and is not a usable number raises rather than
    falling back, on this module's usual doctrine (`ambient_path`): a channel
    that states a level and states it wrongly is a broken channel, and quietly
    mixing 7 dB louder than the user chose is the failure CF-0165 was written
    about - one nobody hears until the video is finished.
    """
    if cli_value is not None:
        return float(cli_value), BED_DB_SOURCE_CLI
    ve = (channel_cfg or {}).get("video_editor") or {}
    ambient = ve.get("ambient") if isinstance(ve, dict) else None
    value = ambient.get("bed_db") if isinstance(ambient, dict) else None
    if value is None:
        return DEFAULT_BED_DB, BED_DB_SOURCE_DEFAULT
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise AmbientBedError(
            f"the channel config sets {CHANNEL_BED_DB_KEY} to {value!r}, which is not "
            f"a level in dB. Leave the key out to mix at {DEFAULT_BED_DB} dB; a bed "
            f"level is a number the channel decided by ear, and guessing at what a "
            f"broken one meant is how the decision gets lost")
    lo, hi = BED_DB_RANGE
    if not lo <= float(value) <= hi:
        raise AmbientBedError(
            f"the channel config sets {CHANNEL_BED_DB_KEY} to {value} dB, outside "
            f"{lo:.0f}..{hi:.0f} dB. Over {hi:.0f} the bed is mixed louder than the "
            f"reference it was levelled to and clips the intermediate; under {lo:.0f} "
            f"no listener and no gate can find it")
    return float(value), BED_DB_SOURCE_CONFIG


def probe_ambient(path):
    """{seconds, has_audio, sample_rate, channels, codec} for the file.

    A file ffprobe cannot read at all raises, rather than answering zeros that
    would then be compared against the floor and reported as a short file.
    """
    try:
        info = probe_json(path)
    except Exception as e:  # noqa: BLE001 - any probe failure is the same answer
        raise AmbientBedError(f"the ambient file {path} cannot be probed ({e})") from e
    streams = info.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise AmbientBedError(
            f"the ambient file {path} carries no audio stream - it is the bed under "
            f"the whole video, and a file with no track in it would play as the "
            f"silence CF-0025 was raised about")
    try:
        seconds = float(audio.get("duration") or (info.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        raise AmbientBedError(f"the ambient file {path} reports no duration") from None
    return {
        "seconds": round(seconds, 6),
        "has_audio": True,
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "codec": audio.get("codec_name") or "",
    }


def check_ambient(probe, path):
    """Raise AmbientBedError unless the file can carry a bed.

    One check today - the length floor - and it is here rather than inline in
    the mixer for the reason CF-0141 gives: what a channel asset has to be is
    a written rule, checked before anything runs, not a surprise in the middle
    of an ffmpeg graph.

    Note what is deliberately *not* checked: sample rate, channel count,
    codec, loudness, spectrum, taste. The first three are ffmpeg's problem and
    are converted on decode; loudness is normalised (prepare()); taste was
    settled once when the user approved the file (decision 3).
    """
    if probe["seconds"] < AMBIENT_MIN_SECONDS:
        raise AmbientBedError(
            f"the ambient file {path} runs {probe['seconds']:.2f}s and the floor is "
            f"{AMBIENT_MIN_SECONDS:.0f}s. A shorter file is not looped: under a 60 s "
            f"narration it would repeat often enough to read as a pulse of its own, "
            f"which is a rhythm nobody wrote. Bring a longer recording of the same "
            f"sound")


def decode_mono(path, seconds=None):
    """The file as mono float samples at SR, through ffmpeg.

    One decode of the whole file, not a stream: the longest ambient anyone
    would bring is minutes, and the loop below needs the samples in memory
    anyway. Format, sample rate and channel count are converted *here* and
    only here - unlike the ending clip, whose format is checked and never
    converted (CF-0141, decision 5), because a clip's frames are what the
    viewer sees while a bed's samples are raw material for a mix that
    resamples everything to SR regardless.
    """
    result = ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                    "-f", "f32le", "-", text=False, media_seconds=seconds or 0.0)
    if result.returncode != 0 or not result.stdout:
        raise AmbientBedError(
            f"the ambient file {path} could not be decoded "
            f"(ffmpeg rc={result.returncode}): "
            f"{ffmpeg_stderr(result).strip().splitlines()[-1] if ffmpeg_stderr(result).strip() else 'no output'}")
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)


def loop_to(samples, n, crossfade=None):
    """`samples` repeated to exactly `n` samples, with an equal-power seam.

    Section B of CF-0153 left the choice open between looping a short file and
    refusing it. Both, in the end, and the line between them is
    AMBIENT_MIN_SECONDS: above it the file loops, below it check_ambient()
    refuses. The reasoning is the material. A bed is stationary texture - rain,
    projector, room - and for stationary texture a crossfaded loop is
    inaudible: there is no melody to restart and no phrase to repeat, so the
    only artefact a loop can produce is the seam itself, and an equal-power
    crossfade removes that. Refusing every file shorter than the video, by
    contrast, would mean a channel could only be given a bed by someone with a
    70-second recording, and every re-cut of the narration would then have to
    be checked against it - the length of the video would become a property of
    the bed, which is backwards.

    Equal power (sqrt ramps) rather than linear: the two copies at the seam
    are uncorrelated, so their powers add and a linear pair would dip 3 dB in
    the middle of every seam - an audible breath, once per loop, which is
    exactly the periodic event looping is supposed not to introduce.
    """
    m = int(samples.size)
    if m == 0:
        raise AmbientBedError("the ambient file decoded to no samples at all")
    if m >= n:
        return np.array(samples[:n], dtype=np.float64), 1
    c = int(SR * (AMBIENT_CROSSFADE_SECONDS if crossfade is None else crossfade))
    c = max(1, min(c, m // 2))
    stride = m - c
    copies = int(math.ceil((n - m) / stride)) + 1
    ramp = np.linspace(0.0, 1.0, c, endpoint=False)
    fade_in, fade_out = np.sqrt(ramp), np.sqrt(1.0 - ramp)
    out = np.zeros(n + m)
    for k in range(copies):
        seg = np.array(samples, dtype=np.float64)
        if k:                      # every copy but the first fades in
            seg[:c] *= fade_in
        if k < copies - 1:         # every copy but the last fades out
            seg[-c:] *= fade_out
        at = k * stride
        out[at:at + m] += seg
    return out[:n], copies


def band_rms_db(samples, lo=BED_AUDIBLE_BAND_HZ):
    """RMS in dBFS of `samples` above `lo`, the band CF-0025 established as
    the only one that matters: a phone or laptop speaker radiates nothing
    under about 200 Hz, and a bed measured broadband was 25 dB louder on the
    meter than in the air. Brick-wall in the frequency domain - this is a
    measurement, not a filter anyone listens to, and there is no scipy in this
    venv (the same reason `_air()` shapes its noise with an FFT).
    """
    if samples.size == 0:
        return -math.inf
    spectrum = np.fft.rfft(samples)
    spectrum[np.fft.rfftfreq(samples.size, 1 / SR) < lo] = 0
    band = np.fft.irfft(spectrum, n=samples.size)
    rms = math.sqrt(float(np.mean(band ** 2)))
    return 20 * math.log10(rms) if rms > 0 else -math.inf


def _write_wav(path, samples):
    """Mono 16-bit at SR - the same shape build_soundtrack.write_wav() writes.
    Local so that this module has no import cycle with its only caller; the
    tests assert the two agree on rate, width and channels."""
    import wave
    data = np.clip(samples, -1, 1)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((data * 32767).astype("<i2").tobytes())


def prepare(path, seconds, out_path, reference, source=AMBIENT_SOURCE_CONVENTION,
            fade_out_seconds=BED_FADE_SECONDS, probe=None):
    """Turn the channel's file into the bed this mix will use, and say what
    was done to it.

    Returns the record that goes on the plan (section E). The prepared wav is
    at `out_path`, `gain_db` is what the mix graph must add to `--bed-db` for
    it, and everything else is provenance.

    The four steps, and why each is here rather than in the graph:

      1. **decode** to mono at SR - one format for one mixer.
      2. **loop** to the composition's length (loop_to()). The bed runs under
         the whole video; a source that stops early would leave the tail in
         the silence CF-0025 was raised about.
      3. **fade** in, and out when the caller has no card to fade over -
         exactly the shape `build_soundtrack.bed()` gives the generated bed,
         so the two sources are interchangeable from the graph's point of
         view and the fade is decided in one place (CF-0117).
      4. **normalise to the generated bed's own level in the audible band.**
         This is section C. The mix graph puts the bed 13-14 dB under the
         narration and ducks it, and it does that to whatever it is handed:
         hand it a file mastered 10 dB hotter than the generator and the whole
         chain lands 10 dB off, so BED_TARGET_GAPS_DB / BED_TARGET_SPEECH_DB
         would hold for the generator and for nothing else. The reference is
         not a constant but the bed *this same mix would otherwise have
         generated*, measured above BED_AUDIBLE_BAND_HZ over the same body
         window - which is the band the targets are stated in and the band
         `qc_render.bed_audibility_db()` measures. So a channel with a file
         and a channel without one arrive at the gate at the same level by
         construction, and the gate needs no changes at all (decision 3).

    The gain is *not* baked into the samples. The file is written at
    AMBIENT_PEAK and the gain is returned for the graph's `volume` filter: a
    file that needs +8 dB would otherwise clip an int16 intermediate, and
    nothing about the level of a bed is worth losing samples over.
    """
    src = Path(path)
    probe = probe or probe_ambient(src)
    check_ambient(probe, src)
    n = int(round(seconds * SR))
    looped, copies = loop_to(decode_mono(src, probe["seconds"]), n)

    fade_in_n = min(int(SR * BED_FADE_SECONDS), looped.size)
    looped[:fade_in_n] *= np.linspace(0, 1, fade_in_n)
    fade_out_n = min(int(SR * max(0.0, fade_out_seconds)), looped.size)
    if fade_out_n:
        looped[-fade_out_n:] *= np.linspace(1, 0, fade_out_n)

    peak = float(np.abs(looped).max())
    if peak <= 0:
        raise AmbientBedError(f"the ambient file {src} is digital silence")
    looped *= AMBIENT_PEAK / peak

    # The body: what is left with both fades cut off, measured on the ambient
    # and on the reference over the same window so the two levels are
    # comparable. A file shorter than its own fades cannot happen -
    # AMBIENT_MIN_SECONDS is 8 s against 1.5 s of fade - but the mix can be,
    # and then the whole array is the body.
    lo, hi = fade_in_n, looped.size - fade_out_n
    if hi - lo < SR // 2:
        lo, hi = 0, looped.size
    ambient_db = band_rms_db(looped[lo:hi])
    reference_db = band_rms_db(np.asarray(reference, dtype=np.float64)[lo:hi])
    if not math.isfinite(ambient_db) or not math.isfinite(reference_db):
        raise AmbientBedError(
            f"the ambient file {src} has no energy at all above "
            f"{BED_AUDIBLE_BAND_HZ:.0f} Hz - the band a phone speaker is the only "
            f"one to radiate, and the band the bed is measured in. A file that is "
            f"all sub-bass is the defect CF-0025 found in the generated bed, not a "
            f"replacement for it")
    gain_db = reference_db - ambient_db
    if gain_db > AMBIENT_MAX_GAIN_DB:
        raise AmbientBedError(
            f"the ambient file {src} reads {ambient_db:.1f} dB above "
            f"{BED_AUDIBLE_BAND_HZ:.0f} Hz and would have to be lifted "
            f"{gain_db:.1f} dB to sit where the generated bed sits "
            f"({reference_db:.1f} dB), over the {AMBIENT_MAX_GAIN_DB:.0f} dB "
            f"ceiling. That much lift raises the file's own noise floor with it: "
            f"this is the wrong file, not a quiet one")

    _write_wav(out_path, looped)
    return {
        "path": str(src.resolve()),
        "name": src.name,
        "source": source,
        "file_seconds": probe["seconds"],
        "codec": probe["codec"],
        "sample_rate": probe["sample_rate"],
        "channels": probe["channels"],
        "loops": copies,
        "crossfade_s": AMBIENT_CROSSFADE_SECONDS if copies > 1 else 0.0,
        "prepared": str(Path(out_path).resolve()),
        "prepared_seconds": round(looped.size / SR, 3),
        "gain_db": round(gain_db, 2),
        "band_rms_db": round(ambient_db, 2),
        "reference_band_rms_db": round(reference_db, 2),
        "audible_band_hz": BED_AUDIBLE_BAND_HZ,
        "min_seconds": AMBIENT_MIN_SECONDS,
    }


# CF-0153 (section E): what the batch record carries about the bed that
# played. Six keys, always all of them - `null` in each on a plan that records
# no bed at all, and the four `ambient_*` null on a generated one - so a reader
# never has to interpret an absent field. Same promise as CF-0141's
# `ENDING_DELIVERED_KEYS`, and for the same reason: a video mixed with the
# channel's own file and a video mixed with the generator used to leave
# identical batch records, and telling them apart afterwards meant going back
# to the plan on disk.
# CF-0165 adds the level and where it came from, for the same reason the six
# above exist: the batch record is where a finished run is reviewed, and "at
# what level, decided by whom" was answerable only by opening the plan.
# CF-0271 adds four more, and the reason is the task itself: a video shipped
# with the generated bed at -18 dB instead of the channel's file at -25, and
# the batch record said `source: "generated"` - true, and nobody reads a field
# that looks the same on the ordinary run. `bed_substituted` says *why* the
# generator played, and is `null` exactly when nothing was substituted, so the
# unusual run is legible by the presence of a value rather than by comparing
# two fields. The three `ambient_rotation_*` / `ambient_chosen_by` keys carry
# the rotation's choice into the same record, `null` on a single-file channel.
BED_RECORD_KEYS = ("source", "ambient_name", "ambient_path", "ambient_source",
                   "ambient_loops", "ambient_gain_db", "bed_db", "bed_db_source",
                   "ambient_rotation_index", "ambient_rotation_size",
                   "ambient_chosen_by", "bed_substituted")

# Why the generated bed played when a file was asked for. Constants because
# the root's contract test reads them, and because a code somebody typed twice
# in two spellings is a code nobody can grep the runlog for.
BED_SUBSTITUTED_NO_CHANNEL_BED = "no_channel_bed"          # --music channel, channel has none
BED_SUBSTITUTED_OPERATOR = "operator_forced_generated"     # --music generated, by hand
BED_SUBSTITUTION_CODES = (BED_SUBSTITUTED_NO_CHANNEL_BED, BED_SUBSTITUTED_OPERATOR)

# What `runlog.annotate(bed=...)` says on a substituted run, by the convention
# build_render_plan.py already uses for `two_source_gate=`, `assetless_rung=`
# and `blooper_gate=`: a short upper-case verdict the run report can be read
# for without opening a plan.
def substitution_annotation(code):
    return f"GENERATED {code}"


def bed_record_fields(plan):
    """`videos[].bed` for write_batch_metadata.py, off the plan's audio.bed -
    which build_soundtrack.py wrote from what it actually mixed, not from what
    the CLI asked for."""
    bed = ((plan or {}).get("audio") or {}).get("bed")
    if not isinstance(bed, dict):
        return dict.fromkeys(BED_RECORD_KEYS)
    ambient = bed.get("ambient") if isinstance(bed.get("ambient"), dict) else {}
    return {
        "source": bed.get("source"),
        "ambient_name": ambient.get("name"),
        "ambient_path": ambient.get("path"),
        "ambient_source": ambient.get("source"),
        "ambient_loops": ambient.get("loops"),
        "ambient_gain_db": ambient.get("gain_db"),
        "bed_db": bed.get("bed_db"),
        "bed_db_source": bed.get("bed_db_source"),
        # CF-0271: which of the rotation played, out of how many, and by what
        # rule - `null` on a channel that brings a single file, which is what
        # "this channel does not rotate" looks like in the record.
        "ambient_rotation_index": ambient.get("rotation_index"),
        "ambient_rotation_size": ambient.get("rotation_size"),
        "ambient_chosen_by": ambient.get("chosen_by"),
        "bed_substituted": bed.get("substituted"),
    }

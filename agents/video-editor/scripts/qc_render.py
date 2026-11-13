#!/usr/bin/env python3
"""Check a finished video before a human is asked to look at it.

qc_asset.py guards the input side; this guards the output. Between them they
cover the failure modes the first batch shipped: dead frames, audio that does
not line up with the picture, a soundtrack that clips or drops silent, and a
background bed mixed too quiet to actually hear.

Usage: qc_render.py <video.mp4> <plan.json> [--json]
Exit code 0 = passed, 1 = failed, 4 = the score is under N (CF-0434),
2 = no video to check: missing, empty or unreadable by ffprobe (CF-0794).

CF-0434: every run but --audio-only records its real penalties as the `qc`
stage of the video's score log (`<plan stem>.score.json`, score_log.py) and
checks the remainder. Under N the video goes no further: the refusal
`<plan stem>.score.refusal.json` is written, no degradation is suggested, and
the result carries `score`, `score_line`, `score_stop`.
"""
import argparse
import json
import re
import tempfile
import sys
from pathlib import Path

import assetless_rung  # CF-0442: insert_has_picture(), one line for both gates
import attempts
import quiet
import score_log  # CF-0434: the video's score log and the early stop
import safe_area
import repeat_guard  # CF-0337
import entity_guard  # CF-0348
import inset_panel  # CF-0327
import loudness  # CF-0695: the finished file's loudness against its target
import meme_captions  # CF-0379
import still_share  # CF-0523: footage_dirs(), the pool's one lookup rule
import video_plan_args  # CF-0815: `plan video` read as `video plan`; a plan that is not JSON is a sentence
from repo_paths import FACTORY_ROOT  # CF-0351: where shared/footage lives
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197

import math

from common import (BED_AUDIBLE_BAND_HZ, BED_FADE_SECONDS, RENDER,
                    # CF-0294: the coverage floor every stage shares, the
                    # fallback for a plan that records no qc_thresholds.
                    MIN_COVERAGE,
                    luma_pixels, media_duration,
                    # CF-0132: every subprocess this gate starts goes through
                    # a common.py helper now, so it runs under CF-0128's
                    # ceilings instead of waiting forever. This gate runs on
                    # every video of every batch, which is what made the hole
                    # here worse than the others.
                    ffmpeg, grab_frame, probe_json,
                    # CF-0131: the freeze geometry moved to common.py so that
                    # build_render_plan.py refuses, before the render, exactly
                    # the blocks this gate would fail after it. Re-exported
                    # under the names this module has always used them by.
                    PROBE_FRACTIONS, PROBE_GAP, RENDER_CROSSFADE,
                    CLIP_TAIL_TOLERANCE, LAST_FRAME_EPSILON, MAX_HELD_RUN,
                    source_time, probe_times, probe_exhausted)
from qc_asset import MIN_MEAN_LUMA

# CF-0434: the real penalties so far put the video under N - it goes no further.
EXIT_SCORE_F = 4
MAX_BLACK_RUN = 0.4          # seconds of full-black the eye reads as a glitch
MAX_SILENCE_RUN = 2.5        # seconds of dead air
DURATION_TOLERANCE = 0.25    # seconds of drift between picture and voice
MAX_PEAK_DB = -0.5           # anything above this is clipping
MIN_BLOCK_MOTION = 1.0       # mean luma change over 0.3s; below this a clip is a still
# CF-0025: both floors are measured above BED_AUDIBLE_BAND_HZ - see
# bed_audibility_db(). The first keeps its -38.0 from the first CF-0025 fix,
# now meaning something a listener can hear rather than a broadband number the
# ear disagreed with; the mixer aims 7 dB over it (BED_TARGET_GAPS_DB = -31).
# The second is that floor minus the duck's measured depth (6.4 dB on the four
# 2026-09-03T2037Z mixes, rounded), because under speech the bed is *supposed*
# to be ducked - failing it at the same number would fail every correct mix.
# Both floors were checked against the eight shipped mixes of
# 2026-09-03T2037Z, 2026-08-31T2155Z and the-long-voyage: every one of them - the
# batches the user could not hear a bed in - reads -41.5 to -52.9 dB here and
# fails, and every one re-mixed with the current code reads -26.3 to -36.2 and
# passes. The two populations do not overlap and the nearest miss is 4.4 dB.
MIN_BED_RMS_DB = -38.0       # bed in a voice-free gap; below this it reads as silent
MIN_BED_DUCKED_RMS_DB = -44.0  # bed under speech, where the duck has it 6 dB down
MIN_SOUND_RMS_DB = -30.0     # CF-0068: a placed sound below this over its slot was not heard
# CF-0423: the pauses between phrases of a render with no bed in it at all.
# Measured broadband per 100 ms frame of the body (clear of the bed's fades
# and of the channel's ending clip) on example-film's mp4s: the four mixed with
# a bed (widows-bay, outrider-doune-castle, kaijura-minus-zero,
# mormon-wives-comeback) never go under -46 dB - the bed is ducked under
# speech, not removed - while the four rendered from the bare voice
# (backrooms, wolfhame, paper-dragon, delver) fall to the TTS's own floor and to
# digital zero (-300) in the pauses: 16 to 23 frames each under -70 dB. The
# line sits 24 dB under the quietest bed frame; anything under it is not a
# quiet bed, it is no bed.
NO_BED_DB = -70.0
# Frames under NO_BED_DB inside the body before a render is called bed-less:
# three, so that one stray frame (a decoder's priming, a cut) never fails a
# video that has its bed.
NO_BED_MIN_FRAMES = 3

# CF-0004: a block that reads as a still is only a *fault* if the source clip
# does not read as a still in the same place. PROBE_FRACTIONS, PROBE_GAP and
# RENDER_CROSSFADE govern that second look and are imported above - CF-0131
# moved them to common.py, unchanged, so the planner can apply the same test
# one stage earlier instead of inventing a threshold of its own.
# Deliberately the same number as MIN_BLOCK_MOTION, and it has to stay that
# way: the question this answers is "is the still the render shows a still that
# is really in the footage?", so the footage is judged still by exactly the bar
# that judged the render still. Anything else would be a second, unexplained
# threshold. Measured on all 20 cached trailers in shared/footage (10,740
# windows of 0.3s, CF-0004): 78.5% sit above 3.0, 8.1% fall under 1.0, and 3.4%
# under 0.1 - held frames are common enough in real trailers that the render
# gate cannot treat every one of them as a fault.
MIN_SOURCE_MOTION = MIN_BLOCK_MOTION

RENDER_PROBE_VF = "crop=iw:ih*0.36:0:0,scale=200:-2"
SOURCE_PROBE_VF = "scale=200:-2"

# CF-0050: a `side_by_side` block has two pictures stacked, so the render-side
# motion probe cannot sample both from the same band - each half is measured
# in its own band (split_probe_vf).
#
# CF-0712: that band used to be the top 36% of each half (a fixed
# `crop=iw:ih*0.18`), carried over from the full-frame band "for the same
# reason, above the caption band". Since CF-0394 the caption band sits low in
# the frame (its foot on the bottom dead zone), so the reason held for neither
# half: the top half lies wholly above the band, and the bottom half's 36%
# reached ~57 px *into* it (captions changing words could pass a frozen side b
# as moving). On the top half it was worse than arbitrary: 345 px of a 957 px
# picture is the sky of a landscape shot. sophie-adenot (example-science
# 2026-10-12T2001Z) block 0 side a - an aurora seen from orbit, the planet
# moving under it - read 0.65-0.94 in that band (black space with a sliver of
# aurora) and 9-10 over the whole half; the clip itself moves from its first
# frame (2.0-2.5 per frame at 96 px, one key frame, no held frames). The
# second look (freeze_verdict) then compared the whole source frame (9.9)
# against that band and called a faithful render "frozen", -62 for the hook,
# and the video was refused at 24 from a plan of 86. So a half is now probed
# over all of it that lies clear of the caption band - SplitLayer.jsx's own
# geometry (main zone, seam, halves) and captionBand.js's band, both read from
# the plan the way the rest of this gate reads them (meme_captions).
SPLIT_SEAM_PX_DEFAULT = 6   # build_render_plan.SPLIT_SEAM_PX, SplitLayer.jsx `?? 6`
SPLIT_SIDES = 2
_DEFAULT_PLAN_GEOMETRY = {"output": {"width": 1080, "height": 1920}}


def split_probe_band(plan, j, seam=None):
    """CF-0712: `(top, height)` in output px of the band side `j` (0 = the
    upper half) of a split block is probed in: the half as SplitLayer.jsx
    lays it out in the main zone, minus the caption band - the part above the
    band when there is one, else the part below it. `plan` may be None (a
    caller with a bare block): the 1080x1920 frame with no secondary zone."""
    plan = plan if (plan or {}).get("output") else _DEFAULT_PLAN_GEOMETRY
    _, zy, _, zh = meme_captions.main_zone(plan)
    seam = SPLIT_SEAM_PX_DEFAULT if seam is None else int(seam)
    half_h = (zh - seam) // 2
    top = zy + (0 if j == 0 else half_h + seam)
    bottom = top + half_h
    _, band_y, _, band_h = meme_captions.band_box(plan)
    band_bottom = band_y + band_h
    if band_bottom <= top or band_y >= bottom:
        return top, half_h
    above, below = band_y - top, bottom - band_bottom
    if above > 0:
        return top, above
    if below > 0:
        return band_bottom, below
    return top, half_h   # the band covers the whole half: nothing better to look at


def split_probe_vf(plan, j, seam=None):
    """CF-0712: the render probe filter of side `j` of a split block - its
    split_probe_band(), at the gate's usual 200 px."""
    top, height = split_probe_band(plan, j, seam)
    if top % 2:   # an even crop, kept inside the band (never onto the seam)
        top, height = top + 1, height - 1
    height = max(2, height - height % 2)
    return f"crop=iw:{height}:0:{top},scale=200:-2"

# CF-0050: how a deliberate silent beat is told from dead air. Same shape as
# CF-0004's answer to the same class of question one gate over: the render alone
# cannot separate the two, so the verdict is drawn from a second source that
# can. There the second source was the clip the block was cut from; here it is
# the plan's declaration plus a measurement of whether the declaration was
# actually carried out - a lead the plan asked for, sitting where it said it
# would, with the picture really on screen under it.
SILENCE_HEAD_TOLERANCE = 0.15   # seconds; a lead starts at the head or nowhere
SILENCE_LEAD_TOLERANCE = 0.35   # seconds of slack around the declared length
# The frame under a cold open is judged by the floor every source asset has to
# clear (qc_asset.MIN_MEAN_LUMA), not by a number invented here. The claim being
# checked is "the beat is on the picture"; a frame too dark to be an acceptable
# asset is not a picture the audience is being shown in silence.
MIN_COLD_FRAME_LUMA = MIN_MEAN_LUMA

# Caption legibility cannot be verified from a rendered frame: every region you
# could measure contains the captions themselves, and they dominate it. Measured
# three ways - band luminance, edge density, and band-versus-frame darkening -
# each was contaminated by the glyphs.
#
# It does not need measuring. White fill with a heavy black stroke floors the
# contrast at 4.61:1 against *any* background luminance (worst case at luma 117,
# where fill and stroke contrast meet). That is above WCAG's 3:1 bar for large
# text, so no footage can break it.
#
# What can break it is an edit to the renderer. So the guard is on the design
# invariant that supplies the guarantee, not on the pixels that follow from it.
#
# CF-0394 (2026-09-25): the floor on the type is the size the user picked from
# four rendered candidates - 50 px, `theme.captionSize` (78) scaled by
# captionBand.js CAPTION_SCALE - and there is no scrim to guard any more: the
# user took it out, and the 4.61:1 floor above never depended on it.
MIN_STROKE_PX = 5
MIN_CAPTION_FONT_PX = 48


# CF-0132: how long the file a whole-file pass has to chew is, remembered.
# Every measuring pass below is ceilinged off its material (a fixed ceiling is
# what turns a long honest mix into a false failure), and this gate makes half
# a dozen of them over the same render - the ceiling must not cost an ffprobe
# each time. media_duration() carries its own ceiling, so a wedged probe here
# still raises rather than answering 0.0.
_MEDIA_SECONDS = {}


def media_seconds(path):
    key = str(path)
    if key not in _MEDIA_SECONDS:
        _MEDIA_SECONDS[key] = media_duration(path)
    return _MEDIA_SECONDS[key]


def measure(path, *args):
    """One whole-file ffmpeg pass whose answer is the filter's own log line -
    blackdetect, silencedetect, astats. `log_level="info"` because the default
    `error` would swallow exactly the lines being read."""
    return ffmpeg(*args, "-f", "null", "-",
                  log_level="info", media_seconds=media_seconds(path))


def detect(path, filt):
    """Every run `filt` found, as {start, end, duration} - not just how long
    each one was.

    One parser for both of the filters this gate leans on. `blackdetect` and
    `silencedetect` print the same three numbers in the same shape (the black
    one on a single line, the silent one across two), and until CF-0141 this
    function read only the duration off `blackdetect` while a second,
    near-identical parser existed a few lines below to read positions off
    `silencedetect` - two regexes for one grammar, and the black gate simply
    had no idea *where* its runs were.

    That was affordable while every black run was equally damning. CF-0141
    ends that: the last seconds of the video are the channel's own finished
    clip, and by decision 3 the gates do not judge them at all - it is
    material the user approved before it reached the factory, and these gates
    exist to catch faults of *assembly*, of which there is none there. Deciding
    whether a run falls in that interval or in the body of the video is
    impossible from a duration alone.

    A run whose start is never closed (a file that ends mid-run without the
    filter printing its end) is dropped, exactly as before.
    """
    audio = "silencedetect" in filt
    key = "silence" if audio else "black"
    out = measure(path, "-i", path, "-vn" if audio else "-an",
                  "-af" if audio else "-vf", filt)
    found, start = [], None
    for m in re.finditer(rf"{key}_(start|end):\s*(-?\d+\.?\d*)"
                         rf"(?:\s*\|?\s*{key}_duration:\s*(\d+\.?\d*))?",
                         out.stderr):
        kind, value, duration = m.group(1), float(m.group(2)), m.group(3)
        if kind == "start":
            start = value
        elif start is not None:
            found.append({"start": round(start, 3), "end": round(value, 3),
                          "duration": round(float(duration) if duration
                                            else value - start, 3)})
            start = None
    return found


def silence_runs(path):
    """Every silent stretch, with where it sits. A deliberate lead (CF-0050)
    is told from dead air partly by *where* it is."""
    return detect(path, "silencedetect=n=-45dB:d=1.0")


# --------------------------------------------------------------------------
# CF-0141: the interval the gates do not judge
# --------------------------------------------------------------------------
#
# Decision 3 of 2026-09-08, and it is a decision about what these gates are
# for rather than a relaxation of them. The last seconds of every video of
# this channel are a finished mp4 the channel brought with it - generated,
# watched and approved by the user before it ever reached the factory. The
# gates here catch faults of assembly: a block that rendered black, a mix
# that lost its bed, a caption over an unreadable band. In that interval
# there is no assembly to have gone wrong, and every one of these
# measurements would be measuring somebody else's finished work against
# rules it never agreed to. A clip that opens on a black frame or holds a
# beat of silence is a choice its author made.
#
# The excusal is never silent. Every run this drops is reported as a note,
# which is CF-0004's rule for the motion gate applied here: a relaxation is
# only acceptable if it is visible.


def ending_interval(plan):
    """(start, end) of the channel's ending clip, or None.

    Only for `variant: "clip"`. A drawn end card (CF-0117) is this repo's own
    render and is judged like every other frame it produces - which is how the
    card's ground came to be a lifted slate rather than the composition's
    near-black background in the first place.
    """
    card = (plan or {}).get("end_card") or {}
    if card.get("variant") != "clip":
        return None
    try:
        start = float(card["start_s"])
        seconds = float(card["seconds"])
    except (KeyError, TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return (start, start + seconds)


def outside(run, interval):
    """`run` with `interval` cut out of it: a list of the pieces that remain.

    A run that straddles the seam is not excused whole. The part of it in the
    body of the video is still the body of the video, and a black stretch that
    begins two seconds before the ending and runs into it is exactly the fault
    this gate exists for - the picture died early and the clip covered the
    evidence.
    """
    if interval is None:
        return [run]
    lo, hi = interval
    parts = []
    for a, b in ((run["start"], min(run["end"], lo)), (max(run["start"], hi), run["end"])):
        if b - a > 1e-6:
            parts.append({"start": round(a, 3), "end": round(b, 3),
                          "duration": round(b - a, 3)})
    return parts


def declared_lead(plan):
    """The silent beat this plan says the video opens on, or 0.0.

    Read off `rhythm.opening_delivered`, not off the duration record alone: the
    seconds are only a declared beat when the plan also says the opening that
    was actually built is the one that spends them. A voiceover that merely
    happens to start late is not a cold frame and gets no excusal.
    """
    rec = plan.get("rhythm") or {}
    if rec.get("opening_delivered") != "cold_frame":
        return 0.0
    return float((plan.get("duration") or {}).get("lead_silence") or 0.0)


def frame_luma(video, at, tmp, tag):
    """Mean luma of one rendered frame, 0-255. None when it cannot be read."""
    from PIL import Image

    out = Path(tmp) / f"{tag}.png"
    if not grab_frame(video, at, out, extra_vf="scale=200:-2"):
        return None
    with Image.open(out) as im:
        px = luma_pixels(im.convert("L"))
    return sum(px) / len(px)


def silence_verdict(run, plan, video, tmp, tag, check_frame=True):
    """Decide whether a silent stretch is dead air or the beat that was ordered.

    The same shape as freeze_verdict() one gate over, and deliberately so: the
    audio alone cannot tell a `cold_frame` opening from a video that lost its
    voice, exactly as the render alone cannot tell a held shot from a hung one.
    Both are settled by a second source the signal itself does not contain.

    Three things have to hold, and each is checked rather than assumed:

      * the plan declared a cold frame at all, and said how long;
      * this run is that lead - it starts at the head of the file and does not
        run past what was declared. A silence in the middle of a video is never
        the opening beat, however long the opening beat was;
      * **there is a picture under it.** This is the whole claim: `cold_frame`
        is "the frame sits silent for a beat", not "nothing happens for a
        beat". A black or near-black frame under the silence is both gates
        failing at once - the black-run gate says the picture is missing and
        this one refuses to excuse the silence over it - which is the right
        answer, because that combination is a video that opens on nothing.

    Returns (fault, reason, measured_luma).
    """
    lead = declared_lead(plan)
    if not lead:
        return True, "the plan declares no cold-frame opening", None
    if run["start"] > SILENCE_HEAD_TOLERANCE:
        return True, (f"starts at {run['start']:.2f}s, not at the head - a "
                      f"cold-frame lead is the first thing in the file"), None
    if run["end"] > lead + SILENCE_LEAD_TOLERANCE:
        return True, (f"runs to {run['end']:.2f}s, past the {lead:.2f}s lead the "
                      f"plan declared - the extra silence is not the opening beat"), None
    if not check_frame:
        # CF-0025: an --audio-only run has no picture to look at. The two
        # checks that do not need one still ran (the lead is declared, and it
        # sits at the head), so the beat is accepted and the report says which
        # half of the verdict was skipped rather than implying a frame was seen.
        return False, (f"the {lead:.2f}s cold-frame lead the plan declared, at "
                       f"the head where it said it would be - the frame under "
                       f"it was not checked (audio-only run)"), None
    luma = frame_luma(video, min(lead / 2, run["end"] / 2), tmp, tag)
    if luma is None:
        return True, "the frame under the lead could not be read", None
    if luma < MIN_COLD_FRAME_LUMA:
        return True, (f"the frame under the silent lead is {luma:.0f} of 255 "
                      f"(< {MIN_COLD_FRAME_LUMA}) - this is silence over nothing, "
                      f"not a frame held before the hook"), round(luma, 1)
    return False, (f"the {lead:.2f}s cold-frame lead the plan declared, with the "
                   f"picture up under it (mean luma {luma:.0f}) - a held beat, "
                   f"not dead air"), round(luma, 1)


def peak_db(path, until=None):
    """The loudest sample in the file, or in its first `until` seconds.

    CF-0141: `until` is the start of the channel's ending clip. The clipping
    gate is a judgement on what this factory mixed; past that point the
    loudest sample belongs to a finished file the user approved, and decision
    3 keeps the gates off it. Without the bound, a hot ending would fail the
    render for a fault the render does not have and cannot fix.
    """
    out = measure(path, "-i", path, "-vn",
                  *(["-t", f"{until:.3f}"] if until else []),
                  "-af", "astats=measure_overall=Peak_level")
    peaks = [float(m) for m in re.findall(r"Peak level dB:\s*(-?\d+\.?\d*)", out.stderr)]
    return max(peaks) if peaks else None


MEASURE_SR = 22050   # the bed lives in 200 Hz - 2.5 kHz; half rate is plenty


def _samples(path, sr=MEASURE_SR):
    """`path`'s audio as float samples at `sr`, mono. One decode."""
    out = ffmpeg("-i", str(path), "-vn", "-f", "f32le", "-ac", "1", "-ar", str(sr), "-",
                 text=False, media_seconds=media_seconds(path))
    if out.returncode != 0:
        return None
    import numpy as np
    return np.frombuffer(out.stdout, dtype="<f4").astype(np.float64)


def _audible_band(x, fc=BED_AUDIBLE_BAND_HZ, order=4, sr=MEASURE_SR):
    """`x` with everything a small speaker cannot radiate taken out: a 4th
    order (24 dB/octave) high-pass at `fc`, applied as a magnitude envelope in
    the frequency domain. Steep on purpose - the defect this gate exists to
    catch was a bed whose energy sat an octave and a half below `fc`, and a
    2-pole slope leaks 21 dB of that back in."""
    import numpy as np
    if x.size == 0:
        return x
    spectrum = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / sr)
    with np.errstate(divide="ignore"):
        env = 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-9)) ** (2 * order))
    return np.fft.irfft(spectrum * env, n=x.size)


def _power_db(power):
    return -math.inf if power <= 0 else 10 * math.log10(power)


def _frame_powers(x, ms=100, sr=MEASURE_SR):
    import numpy as np
    k = max(1, int(sr * ms / 1000))
    n = (x.size // k) * k
    if n == 0:
        return np.zeros(0)
    return np.mean(x[:n].reshape(-1, k) ** 2, axis=1)


def _word_gaps(plan, body):
    """Gaps *between* words, longer than 0.4s, inside `body`.

    CF-0050: between words, so the sampling starts at the first word rather
    than at 0.0. The head of the file is not a gap in the narration - and on a
    `cold_frame` opening it is a beat someone asked for, which this gate would
    otherwise report as a bed mixed at -131 dB.

    CF-0025: and inside `body`, the stretch clear of the bed's own 1.5s fades
    at each end. A gap that lands in a fade measures the fade, not the mix, and
    the fades are where the pre-roll and the end card live - which is why
    neither of those is a fallback window here.
    """
    words = plan.get("words") or []
    if not words:
        return []
    lo, hi = body
    gaps, prev_end = [], words[0]["start"]
    for w in words:
        if w["start"] - prev_end > 0.4:
            start, end = max(prev_end, lo), min(w["start"], hi)
            if end - start > 0.4:
                gaps.append((start, min(end, start + 1.5)))
        prev_end = max(prev_end, w["end"])
    return gaps[:6]


def _silent_frames(path, plan):
    """CF-0423: how many 100 ms frames of the body are dead air - under
    NO_BED_DB broadband - as (count, seconds of body measured), or None when
    the file carries no audio or is too short to have a body.

    The body is what the bed covers at full presence: after the bed's fade-in
    and before its fade-out, and never past the first frame of the channel's
    ending clip (the mix is silent there by design, CF-0141). A mixed bed is
    ducked under speech but never reaches zero inside it, so one silent frame
    there is already a render without a bed; the count needs no word timing,
    because the pauses that give a bare voice away are mostly shorter than the
    0.4 s `word_gaps` window (backrooms, 2026-09-27T1757Z: no pause over 0.4 s
    at all, 22 dead frames)."""
    import numpy as np
    mix = _samples(path)
    if mix is None or mix.size == 0:
        return None
    ending = ending_interval(plan)
    if ending is not None:
        mix = mix[:max(0, int(ending[0] * MEASURE_SR))]
    duration = mix.size / MEASURE_SR
    lo, hi = BED_FADE_SECONDS, duration - BED_FADE_SECONDS
    if hi - lo < 1.0:
        return None
    powers = _frame_powers(mix[int(lo * MEASURE_SR):int(hi * MEASURE_SR)])
    floor = 10 ** (NO_BED_DB / 10)
    return int(np.sum(powers < floor)), round(hi - lo, 2)


def _voice_stem(plan):
    """The voice as it went into the mix. CF-0695: build_soundtrack.py
    compresses the voice stem before mixing it and records the stem at
    `audio.loudness.voice.path`; subtracting the uncompressed voice from a
    mix built on the compressed one would count the compressor's work as
    bed. Falls back to `audio.src`, the bare voiceover, when there is no
    stem on disk (a plan from before the pass, a fixture)."""
    audio = plan.get("audio") or {}
    stem = ((audio.get("loudness") or {}).get("voice") or {}).get("path")
    if stem and Path(stem).exists():
        return stem
    return audio.get("src")


def bed_audibility_db(path, plan):
    """How loud the background bed is in the finished mix, in the band a
    listener's device can actually reproduce.

    Two things were wrong with the first version of this gate, and CF-0025's
    live example showed both. It measured broadband, so a bed with 95% of its
    energy under 100 Hz read a healthy -32 dBFS while being 25 dB down in the
    band a phone speaker radiates - the meter and the ear disagreed for a whole
    milestone. And it returned None whenever the narration had no pause longer
    than 0.4s, which is most of them: two of the four videos in
    2026-09-04T0657Z reported `bed_rms_db: null`, and None gated on nothing at
    all. A bed mixed silent passed QC clean.

    So the level is measured above BED_AUDIBLE_BAND_HZ, and there are two
    windows with a floor each - whichever is available, named in the result:

      `word_gaps`     gaps over 0.4s between words, clear of the bed's fades.
                      No voice there, so the mix *is* the bed; the duck has
                      released, so this is the bed at its loudest.
                      Floor MIN_BED_RMS_DB.
      `under_speech`  the body of the file with the voice taken out in the
                      power domain: per 100 ms frame, the least-squares slope
                      of mix-power on voice-power is the voice's gain through
                      the limiter, and the *median* residual over the frames
                      is the bed under speech. The median, not the mean or the
                      intercept, because the accents sit in a handful of frames
                      and would otherwise be counted as bed - measured against
                      the bed tapped straight out of the mixer's own graph on
                      the four 2026-09-03T2037Z voices, the median lands within
                      0.6 dB, where the intercept runs 1.4 dB high and drifts.
                      Floor MIN_BED_DUCKED_RMS_DB, about 6 dB lower, which is
                      the duck's measured depth.

    Needs the voice for the second window: plan["audio"]["src"], the bare
    voiceover, exactly as sound_audibility_db() uses it. Returns
    {rms_db, window, floor_db, seconds, voice_subtracted} - or None only when
    the file carries no audio and no voice can be found either, which the
    caller turns into a failure whenever the plan says a bed was mixed.
    """
    import numpy as np
    mix = _samples(path)
    if mix is None or mix.size == 0:
        return None
    # CF-0141: never past the first frame of the channel's ending clip. Two
    # separate reasons, and either one alone would be enough. The mix is
    # deliberately silent there (build_soundtrack.py fades the bed out before
    # the clip rather than under it), so the `under_speech` window would find
    # a residual of nothing and report a bed that had vanished; and the render
    # carries the clip's own track over that interval, which decision 3 says
    # this gate does not measure at all.
    ending = ending_interval(plan)
    if ending is not None:
        mix = mix[:max(0, int(ending[0] * MEASURE_SR))]
        if mix.size == 0:
            return None
    duration = mix.size / MEASURE_SR
    body = (BED_FADE_SECONDS, duration - BED_FADE_SECONDS)
    if body[1] - body[0] < 1.0:      # too short to have a body between the fades
        body = (0.0, duration)
    band = _audible_band(mix)

    gaps = _word_gaps(plan, body)
    if gaps:
        parts = [band[int(a * MEASURE_SR):int(b * MEASURE_SR)] for a, b in gaps]
        parts = [p for p in parts if p.size]
        if parts:
            sampled = np.concatenate(parts)
            return {"rms_db": _power_db(float(np.mean(sampled ** 2))),
                    "window": "word_gaps", "floor_db": MIN_BED_RMS_DB,
                    "seconds": round(sampled.size / MEASURE_SR, 2),
                    "voice_subtracted": False}

    voice = _voice_stem(plan)
    if not (voice and Path(voice).exists()):
        return None
    voiced = _samples(voice)
    if voiced is None or voiced.size == 0:
        return None
    lo, hi = int(body[0] * MEASURE_SR), int(body[1] * MEASURE_SR)
    mix_p = _frame_powers(band[lo:hi])
    voice_p = _frame_powers(_audible_band(voiced)[lo:hi])
    k = min(mix_p.size, voice_p.size)
    if k < 10:
        return None
    mix_p, voice_p = mix_p[:k], voice_p[:k]
    gain, _ = np.linalg.lstsq(np.vstack([voice_p, np.ones(k)]).T, mix_p,
                              rcond=None)[0]
    residual = float(np.median(mix_p - gain * voice_p))
    return {"rms_db": _power_db(residual), "window": "under_speech",
            "floor_db": MIN_BED_DUCKED_RMS_DB,
            "seconds": round(k * 0.1, 2), "voice_subtracted": True}


def _rms_db_over(path, start=0.0, seconds=None):
    """RMS level in dBFS of `path` over [start, start + seconds] (the whole
    file when `seconds` is None) - the bed gate's instrument (ffmpeg
    astats), one interval."""
    out = measure(path, "-ss", str(start),
                  *(["-t", str(seconds)] if seconds is not None else []),
                  "-i", str(path), "-vn", "-af", "astats=measure_overall=RMS_level")
    m = re.search(r"RMS level dB:\s*(-?\d+\.?\d*|-inf)", out.stderr)
    if not m:
        return None
    return -math.inf if m.group(1) == "-inf" else float(m.group(1))


def sound_audibility_db(path, plan):
    """CF-0068: one measurement per sound the plan placed - the RMS of the
    final mix minus the voice-only render over the sound's slot, in dBFS,
    subtracted in the power domain (robust to a sample of latency between
    the two files, which a sample-wise difference is not). The voice-only
    render is the plan's own audio.src - the bare voiceover render_video.py
    replaced with the mix; without it the mix's own level over the slot
    stands in and is said so. The voice does not arrive in the mix at unity:
    build_soundtrack.py's alimiter auto-levels the whole mix (about +1.1 dB
    at limit=0.88), so the voice's share of the slot is scaled by the
    mix-to-voice power ratio over the whole file before it is subtracted -
    a ratio the bed and accents inflate slightly, which makes the gate
    stricter, never looser.

    CF-0025: this one is still measured *broadband*, where the bed's is
    measured above BED_AUDIBLE_BAND_HZ, so MIN_SOUND_RMS_DB and
    MIN_BED_RMS_DB are no longer two readings of one meter and must not be
    compared. That is deliberate and not an oversight: a placed sound is a
    recognisable thing with its own spectrum, mostly in the band a speaker
    reproduces already, and the failure this gate catches is a sound that was
    not mixed at all. The bed's failure was the opposite - present, loud on a
    broadband meter, and in a band nobody's device can radiate.

    Returns [{beat_id, asset_id, at_seconds, rms_db, voice_subtracted,
    voice_gain_db}]; [] on a plan with no placed sound.
    """
    placed = (plan.get("sound") or {}).get("placed") or []
    voice = _voice_stem(plan)
    voice = voice if voice and Path(voice).exists() else None
    gain = None
    if placed and voice is not None:
        # CF-0141: the mix-to-voice ratio is taken over the narration alone.
        # Past its end the render carries the ending clip's own track, which
        # this gate does not measure (decision 3) - folded into the whole-file
        # ratio it would pass for the limiter's gain on the voice and shift
        # every placed sound's level by however loud somebody else's ending
        # happens to be.
        ending = ending_interval(plan)
        until = ending[0] if ending is not None else None
        whole_mix = _rms_db_over(path, 0.0, until)
        whole_voice = _rms_db_over(voice, 0.0, until)
        if whole_mix is not None and whole_voice is not None and math.isfinite(whole_voice):
            gain = whole_mix - whole_voice
    out = []
    for p in placed:
        start = float(p["at_seconds"])
        seconds = min(float(p.get("duration_s") or 1.5), 1.5)
        mix = _rms_db_over(path, start, seconds)
        if mix is None:
            continue
        level, subtracted = mix, False
        if gain is not None:
            v = _rms_db_over(voice, start, seconds)
            if v is not None:
                voice_power = 0.0 if v == -math.inf else 10 ** ((v + gain) / 10)
                residual = 10 ** (mix / 10) - voice_power
                level = 10 * math.log10(residual) if residual > 0 else -math.inf
                subtracted = True
        out.append({"beat_id": p.get("beat_id"), "asset_id": p.get("asset_id"),
                    "at_seconds": start, "rms_db": round(level, 1) if math.isfinite(level) else None,
                    "voice_subtracted": subtracted,
                    "voice_gain_db": round(gain, 2) if gain is not None else None})
    return out


def pair_motion(video, at, tmp, tag, vf, until=None):
    """Mean luma change between two frames, at 200px wide.

    One definition, used on the render and on the source clip alike, so the two
    numbers in a freeze verdict are measured the same way and can be compared.
    `until` defaults to PROBE_GAP later; the source-side probe passes it
    explicitly when the gap would run off the end of a short clip.
    """
    from PIL import Image, ImageChops

    shots = []
    for k, t in enumerate((at, at + PROBE_GAP if until is None else until)):
        out = Path(tmp) / f"{tag}_{k}.png"
        if not grab_frame(video, t, out, extra_vf=vf):
            return None
        shots.append(Image.open(out).convert("L"))
    px = luma_pixels(ImageChops.difference(shots[0], shots[1]))
    return sum(px) / len(px)


def freeze_verdict(block, probe_times, tmp, tag):
    """Decide whether a motionless block is a render fault or motionless footage.

    CF-0031's bug and a deliberately held shot produce the identical pixel
    signal in the render - nothing changes for the whole visible span - so the
    render alone cannot separate them. The clip the block was cut from can:

      * the render hung because playback ran past the end of the clip. That is
        CF-0031's actual mechanism, and it is a fact about the plan, not a
        picture: the block asks for more seconds of footage than the file holds.
      * the clip moves where the render does not. Whatever the cause, the block
        is not showing the footage it declared.
      * the clip is itself motionless there - a locked-off shot, a title card,
        an animated held pose (CF-0004). The render is faithful; failing it
        would be failing the footage for being what it is.

    Returns (fault: bool, reason: str, source_motion: float|None). Anything it
    cannot check - a missing clip, an unreadable frame - stays a fault: the
    gate exists to stop bad renders reaching a human, so it fails closed.
    """
    asset = block["asset"]
    # CF-0893: a sequence cut's span (probe_targets) carries the second its
    # clip clock starts at - read the clip on that clock, not on the span's.
    clock = ({**block, "start": block["clock_start"]}
             if isinstance(block.get("clock_start"), (int, float)) else block)

    # CF-0689: a graphic the factory draws has no source to explain a still -
    # it is built to move for its whole block, so standing still is a fault.
    # No held_pose escape either: nothing about a drawn graphic is held footage.
    if asset.get("kind") == "own_graphic":
        return (True, f"own graphic {asset.get('graphic_id')} stood still in the render - "
                      f"a graphic the factory draws keeps moving for its whole block "
                      f"(CF-0689); a slideshow of stills is not a video", None)

    # Escape valve (CF-0004): an editor who has looked at the block can mark it
    # in the plan. Deliberate, visible in the plan file, and reported as an
    # override rather than as a measurement.
    if asset.get("held_pose"):
        return False, "held_pose is set in the plan - accepted on the editor's say-so", None

    src = asset.get("src")
    if not src or not Path(src).exists():
        return True, "source clip is missing, so the freeze cannot be explained", None
    clip_seconds = media_duration(src)
    if not clip_seconds:
        return True, "source clip has no readable duration", None

    moving, still = [], []
    for probe, t in enumerate(probe_times):
        ts = source_time(clock, t)
        # Past the last frame, or with too little clip left to measure a pair:
        # OffthreadVideo holds the last frame, so of course the render is still
        # here. Every clip block ends this way by design (the Sequence is a
        # crossfade longer than the clip), which is why only a block that is
        # exhausted at *every* probe is a fault. CF-0131: this is the one test
        # build_render_plan.py runs ahead of the render, so it lives in
        # common.py and is called, not restated, on both sides.
        if probe_exhausted(ts, clip_seconds):
            continue
        # The render's own second frame is whatever the clip has PROBE_GAP
        # later, or its last frame if the clip ends first - OffthreadVideo
        # holds it. Mirror that, or a short clip reads as unreadable rather
        # than as the still it actually shows.
        until = min(ts + PROBE_GAP, clip_seconds - LAST_FRAME_EPSILON)
        m = pair_motion(src, ts, tmp, f"{tag}_src{probe}", SOURCE_PROBE_VF,
                        until=until)
        if m is None:
            return True, f"source clip is unreadable at {ts:.2f}s", None
        (moving if m >= MIN_SOURCE_MOTION else still).append(m)

    if not moving and not still:
        needed = source_time(clock, block["end"])
        return True, (f"the clip runs {clip_seconds:.2f}s but the block plays it to "
                      f"{needed:.2f}s - playback ran out and held the last frame"), None
    if moving:
        return True, (f"the source clip moves here (source motion {max(moving):.2f}) "
                      f"but the render does not"), round(max(moving), 2)
    return False, (f"the source clip is motionless here too (source motion "
                   f"{max(still):.2f}) - held footage, not a render fault"), round(max(still), 2)


def block_label(record):
    """"block 7", or "block 0 side a" when the picture is one half of a split."""
    side = record.get("side")
    return f"block {record['index']}" + (f" side {side}" if side else "")


def blur_fill_rect(holder):
    """CF-0436: the output-px rectangle a `blur_fill` picture is shown whole
    in (build_render_plan.py writes it, AssetLayer.jsx draws it), or None for
    a picture without that presentation."""
    detail = ((holder or {}).get("presentation") or {}).get("blur_fill")
    rect = detail.get("rect") if isinstance(detail, dict) else None
    try:
        x, y = int(rect["x"]), int(rect["y"])
        w, h = int(rect["width"]), int(rect["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if w < 2 or h < 2:
        return None
    return x, y, w, h


def picture_vf(holder):
    """CF-0436: the render probe filter of one picture. The top band
    (RENDER_PROBE_VF) for every picture that fills the frame; for a
    `blur_fill` picture its own rectangle - the band above it is the blurred
    ground, which barely moves by construction, and measuring motion there
    would read a moving shot as a still."""
    rect = blur_fill_rect(holder)
    if rect is None:
        return RENDER_PROBE_VF
    x, y, w, h = rect
    return f"crop={w - w % 2}:{h - h % 2}:{x}:{y},scale=200:-2"


def sequence_cuts(block):
    """The cuts of a `sequence` block laid out on their own screen time, as
    `[(k, cut, on, start, end)]` - one per cut, in order.

    Read the way the renderer mounts them: Video.jsx mounts the block
    RENDER_CROSSFADE early (clamped at zero for the opening block) and
    AssetLayer.jsx starts cut k `sum(seconds of the cuts before it)` after
    that mount, the last cut running to the block's end; a sequence with no
    cuts is drawn as its own one cut. `on` is when cut k is mounted - the
    zero of its own clip clock (`source_clock()`) - and `start`-`end` is the
    part of it inside the block's own start-end, the stretch a gate judges
    (the crossfade is the neighbouring block's picture too). `end <= start`
    for a cut that never reaches the block's own seconds.

    CF-0893: the freeze and brightness gates walked the cuts from
    `block.start`, so every boundary they probed sat RENDER_CROSSFADE after
    the real one and the last 0.35 s of cut k's window was cut k+1's picture.
    One layout now, shared by every gate that judges a sequence cut by cut
    (frozen_blocks via probe_targets, lifted_pictures, subject_pictures,
    panel_blocks)."""
    asset = block.get("asset") or {}
    cuts = asset.get("cuts") or [{**asset, "kind": "clip"}]
    b_start, b_end = float(block["start"]), float(block["end"])
    mount = max(0.0, b_start - RENDER_CROSSFADE)
    out, acc = [], 0.0
    for k, cut in enumerate(cuts):
        on = mount + acc
        acc += float((cut.get("seconds") if isinstance(cut, dict) else 0.0) or 0.0)
        off = b_end if k == len(cuts) - 1 else mount + acc
        out.append((k, cut, on, max(b_start, on), min(b_end, off)))
    return out


def source_clock(view, on):
    """`view` (one cut's on-screen span) anchored so that
    common.source_time() reads the cut's clip at the right second:
    source_time(b, t) = start_seconds + t - max(0, b.start - CROSSFADE), so an
    anchor of `on + CROSSFADE` makes that `t - on`, the cut's own clock."""
    return {**view, "start": on + RENDER_CROSSFADE}


def probe_targets(block, index, plan=None):
    """What in this block has to be checked for moving, and where to look.

    One entry per picture: `(block-shaped dict, render probe filter, tag,
    side)`. An ordinary clip block is one picture in the top band of the frame,
    which is what the gate has always assumed. A `side_by_side` block (CF-0050)
    is two, stacked, and neither of them lives in that band - sampling it would
    measure the top half twice and never look at the bottom one at all. Each
    half is handed back as a block of its own so freeze_verdict() can ask the
    same question about the same clip in the same way; nothing about the
    CF-0004 verdict changes, only where the render is sampled.

    CF-0120: a `sequence` block is several pictures one after another inside
    one crossing of the axis, so it is checked the same way but along time
    instead of across the frame - each clip cut is handed back as a block of
    its own, spanning exactly the composition seconds that cut is on screen.
    Without that, the probes would all land inside whichever cut happened to
    cover them and a frozen second picture would never be looked at. Every
    record still names the block's own index, because that is what
    `--degrade-block` acts on; the tag says which cut it was.

    Anything with no moving footage to check - a still, a card, a procedural
    background - yields nothing, exactly as before.

    CF-0689: an `own_graphic` block is checked like a clip - the top band of
    the render must keep moving (CircuitTraces' pulses, the rows coming in);
    a graphic that stands still for MAX_HELD_RUN is a fault (freeze_verdict),
    which is the only reason the still share does not count it as a picture.
    """
    kind = block["asset"].get("kind")
    if kind == "clip":
        return [(block, picture_vf(block["asset"]), f"b{index}", None)]
    if kind == "own_graphic":
        return [(block, RENDER_PROBE_VF, f"b{index}", None)]
    if kind == "sequence":
        # CF-0893: each cut over its own screen time (sequence_cuts()), not
        # walked from block.start - and read against its own clip clock
        # (`clock_start`, freeze_verdict()).
        out = []
        for k, cut, on, s, e in sequence_cuts(block):
            if not isinstance(cut, dict) or cut.get("kind") != "clip" or e <= s:
                continue
            out.append(({**block, "start": s, "end": e,
                         "asset": {**cut, "kind": "clip"},
                         "clock_start": on + RENDER_CROSSFADE},
                        picture_vf(cut), f"b{index}c{k}", None))
        return out
    if kind == "split":
        # CF-0712: each half in its own band, from the plan's geometry.
        seam = block["asset"].get("seam_px")
        halves = (block["asset"].get("sides") or [])[:SPLIT_SIDES]
        return [({**block, "asset": half}, split_probe_vf(plan, j, seam),
                 f"b{index}{half.get('side', j)}", half.get("side"))
                for j, half in enumerate(halves)
                if half.get("kind") == "clip"]
    return []


def motion_timeline(video, vf, seconds=None):
    """Motion across the whole render, sampled end to end instead of at points.

    Returns `[(window_start, motion), ...]` - one entry per PROBE_GAP window,
    `motion` being the mean luma change across that window at 200px wide.
    That is pair_motion()'s definition, unchanged: the frames are PROBE_GAP
    apart, the same `vf` crops the same band, the scale is the same, and the
    number is the same mean absolute luma difference. Only the sampling
    changes - a continuous sweep rather than three probes - because the
    question CF-0249 added ("how long is the motionless stretch") cannot be
    answered by three points no matter how they are placed.

    One ffmpeg pass for the whole video, not two frame grabs per window: a
    40-second render is ~130 windows, and grabbing 260 frames one seek at a
    time would cost more than the render's own QC put together. `tblend`
    differences consecutive frames of the decimated stream and `signalstats`
    prints the mean of the result; `metadata=print:file=-` puts it on stdout,
    so the pass stays at ffmpeg's `error` log level.
    """
    result = ffmpeg("-i", video, "-an", "-vf",
                    f"fps={1 / PROBE_GAP},{vf},tblend=all_mode=difference,"
                    f"signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
                    "-f", "null", "-", media_seconds=seconds)
    out, at = [], None
    for line in (result.stdout or "").splitlines():
        stamp = re.search(r"pts_time:([0-9.]+)", line)
        if stamp:
            at = float(stamp.group(1))
            continue
        value = re.search(r"YAVG=([0-9.]+)", line)
        if value and at is not None:
            # The frame at `at` is the difference between the frames at
            # `at - PROBE_GAP` and `at`, so the window it measures starts a
            # gap earlier - that is the composition time a probe of this
            # window would be taken at.
            out.append((round(at - PROBE_GAP, 3), float(value.group(1))))
            at = None
    return out


def longest_still_run(timeline, start, end):
    """The longest motionless stretch inside `[start, end]`, as
    `(run_start, run_end, motions_in_the_block)`.

    A window counts as this block's only if it lies wholly inside the block -
    a window straddling a cut would measure the cut, not the block. `motions`
    comes back with it so the caller can still ask CF-0004's original
    question (did *anything* in this block move) off the same measurement.
    """
    windows = [(s, m) for s, m in timeline
               if s >= start - 1e-6 and s + PROBE_GAP <= end + 1e-6]
    best = (0.0, 0.0)
    run = None
    for s, m in windows:
        if m < MIN_BLOCK_MOTION:
            run = (run[0] if run else s, s + PROBE_GAP)
            if run[1] - run[0] > best[1] - best[0]:
                best = run
        else:
            run = None
    return best[0], best[1], [m for _, m in windows]


def frozen_blocks(video, plan):
    """Catch a clip block that renders as a still.

    Every block was mounted as a layer spanning the whole composition, so each
    clip's internal playback began at frame 0 of the video and had already run
    out by the time its block was visible - five of six shots came out frozen on
    a last frame, and nothing in the gate noticed. A block that declares moving
    footage has to actually move.

    CF-0004: "has to move" was too strong. Held footage - an animated pose, a
    locked-off two-shot, a title card - is motionless on purpose and read as
    the same fault. Each still-reading block is therefore checked a second time
    against the clip it was cut from (freeze_verdict), and only the ones the
    footage cannot account for are faults. Returns one record per still-reading
    block; `fault` says which kind it is.

    CF-0249: "motionless wherever you look" was still too weak, because it is
    an aggregate over the block and a block can be half alive. dtf-st-louis
    block 0 ran 0.0-9.4s on a 4.03s clip: the probe at 25% landed on real
    footage, max() passed, and 5.37s of held last frame shipped to the user.
    So each block is now swept end to end and judged on the *length of its
    longest motionless stretch* (MAX_HELD_RUN). max() is untouched and still
    failing what it always failed - CF-0004's reason for it (a slow dark shot
    is near-still for a third of a second) is a reason to keep it, not to
    replace it with a minimum or a mean, and the sweep only adds the case it
    cannot see. The second look then aims at the motionless stretch itself
    rather than at the block, so a half-frozen block is explained by what the
    clip was doing *while the picture was stuck*.
    """
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        # One sweep per band that gets looked at (the ordinary top band, and
        # CF-0050's two halves), reused by every block that shares it.
        timelines = {}
        # What the sweep has to chew, for common.media_timeout()'s ceiling.
        seconds = max((b["end"] for b in plan["blocks"]), default=0.0)
        for i, block in enumerate(plan["blocks"]):
            for blk, vf, tag, side in probe_targets(block, i, plan):
                if vf not in timelines:
                    timelines[vf] = motion_timeline(video, vf, seconds)
                # A block too short to hold a single probe is still not judged
                # - by QC or by the planner (common.probe_times).
                if not probe_times(blk):
                    continue
                # CF-0459: only what the viewer sees of this picture is
                # judged. A card that hides it whole leaves nothing to judge
                # (the band under a proof is black and the clip is not on
                # screen); a card over part of it leaves the open pieces.
                covers = freeze_covers(block, blk, plan)
                pieces = (open_pieces(blk, covers) if covers
                          else [(blk["start"], blk["end"])])
                run_start = run_end = 0.0
                motions = []
                for a, b in pieces:
                    rs, re_, ms = longest_still_run(timelines[vf], a, b)
                    motions += ms
                    if re_ - rs > run_end - run_start:
                        run_start, run_end = rs, re_
                if not motions:
                    continue
                run_seconds = run_end - run_start
                # Two ways to read as a still, and the block only has to be
                # one of them: nothing in it moves at all (CF-0004's rule,
                # unchanged), or it stops moving for MAX_HELD_RUN together
                # (CF-0249, the half-frozen block).
                if max(motions) >= MIN_BLOCK_MOTION and run_seconds < MAX_HELD_RUN:
                    continue
                window = {"start": run_start, "end": run_end}
                sampled = probe_times(window) or probe_times(blk)
                still = [m for s, m in timelines[vf]
                         if run_start - 1e-6 <= s
                         and s + PROBE_GAP <= run_end + 1e-6] or motions
                fault, reason, source_motion = freeze_verdict(
                    blk, sampled, tmp, tag)
                cut_tag = re.fullmatch(r"b\d+c(\d+)", tag)
                results.append({"index": i, "side": side,
                                # CF-0549: which cut of a sequence block stuck
                                # (probe_targets' tag) - what --degrade-block
                                # stills, the block's other cuts keep moving.
                                **({"cut": int(cut_tag.group(1))} if cut_tag else {}),
                                "motion": round(max(still), 2),
                                # CF-0249: how long the picture was stuck and
                                # where, so a half-frozen block reads as one
                                # in the log and in the batch record instead
                                # of as a block-wide verdict it never was.
                                "still_run": round(run_seconds, 2),
                                "still_run_at": round(run_start, 2),
                                "fault": fault, "reason": reason,
                                "source_motion": source_motion,
                                # CF-0459: said on the record, so a still on a
                                # partly covered block reads as a judgement of
                                # the part the card left open.
                                **({"judged_span": [[round(a, 2), round(b, 2)]
                                                    for a, b in pieces],
                                    **_cover_fields(covers)} if covers else {})})
    return results


LIFT_PROBE_FRACTIONS = (0.25, 0.5, 0.75)   # CF-0436: where a lifted picture is sampled


def lifted_pictures(plan):
    """CF-0436: every picture of the plan shown `luma_lift`, as
    `(block index, cut index or None, start, end, holder)` - a block's own
    asset, or a sequence cut for the composition seconds it is on screen."""
    out = []
    for i, block in enumerate(plan.get("blocks") or []):
        asset = block.get("asset") or {}
        if asset.get("kind") == "sequence":
            # CF-0893: each cut over its own screen time (sequence_cuts()).
            for k, cut, _on, s, e in sequence_cuts(block):
                if (isinstance(cut, dict) and e > s
                        and (cut.get("presentation") or {}).get("luma_lift")):
                    out.append((i, k, s, e, cut))
        elif (asset.get("presentation") or {}).get("luma_lift"):
            out.append((i, None, float(block["start"]), float(block["end"]), asset))
    return out


def lift_region_vf(holder, plan):
    """The part of the rendered frame a lifted picture occupies: its
    blur_fill rectangle, else the main zone down to the insert box's foot
    (above the caption band, so our white captions are not measured as the
    picture's light)."""
    rect = blur_fill_rect(holder)
    if rect is None:
        try:
            import meme_captions
            x, y, w, h = meme_captions.insert_box(plan)
        except Exception:
            out = plan.get("output") or {}
            x, y = 0, 0
            w, h = out.get("width") or 1080, int((out.get("height") or 1920) * 0.6)
        rect = (int(x), int(y), int(w), int(h))
    x, y, w, h = rect
    return f"crop={w - w % 2}:{h - h % 2}:{x}:{y},scale=200:-2"


def region_luma(video, at, vf, tmp, tag):
    """Mean luma of one region of one rendered frame, 0-255, or None."""
    from PIL import Image

    out = Path(tmp) / f"{tag}.png"
    if not grab_frame(video, at, out, extra_vf=vf):
        return None
    with Image.open(out) as im:
        px = luma_pixels(im.convert("L"))
    return sum(px) / len(px)


def lifted_blocks(video, plan):
    """CF-0436: a `luma_lift` picture measured on the render - the brightness
    gate judges what the viewer gets, after the lift. One record per lifted
    picture: the plan's two numbers (the probe before and after the gain) and
    the render's, `fault` when the rendered picture is still under the
    qc_asset floor (MIN_MEAN_LUMA). A fault costs `score.low_brightness` on
    the QC stage (score_log.qc_findings) - the plan charged the lift, not the
    darkness, so the darkness is charged once, where it was seen.

    `luma_render` is the mean of LIFT_PROBE_FRACTIONS samples across the
    picture's span, not one frame: on 0929Z's gQf4Vya5PbI:3 the shot itself
    cuts to black 1.25 s in, and one sample decides nothing about what the
    viewer got over the block. The samples are kept on the record."""
    out = []
    pics = lifted_pictures(plan)
    if not pics:
        return out
    with tempfile.TemporaryDirectory() as tmp:
        for i, k, start, end, holder in pics:
            lift = holder["presentation"]["luma_lift"]
            vf = lift_region_vf(holder, plan)
            samples = []
            for n, f in enumerate(LIFT_PROBE_FRACTIONS):
                v = region_luma(video, round(start + (end - start) * f, 3), vf,
                                tmp, f"lift{i}_{k}_{n}")
                if v is not None:
                    samples.append(round(v, 1))
            luma = sum(samples) / len(samples) if samples else None
            at = round(start + (end - start) / 2, 3)
            rec = {"index": i, "cut": k, "at": at, "gain": lift.get("gain"),
                   "luma_plan_before": lift.get("luma_before"),
                   "luma_plan_after": lift.get("luma_after"),
                   "luma_render": None if luma is None else round(luma, 1),
                   "luma_samples": samples,
                   "floor": MIN_MEAN_LUMA}
            rec["fault"] = luma is not None and luma < MIN_MEAN_LUMA
            out.append(rec)
    return out


# CF-0294: DoD item 7 - "the hero of the shot is in the frame" - judged on the
# finished video, the way items 1, 2, 5 and 6 are.
#
# The defect this exists for shipped in 2026-09-18T2232Z delver.mp4: the last
# block (35.17-44.12s, a wide two-shot) framed a 9:16 window on the gap between
# two seated people and delivered their knees. CF-0292 fixed the cause on the
# planner's side; this is the watchdog that would have caught it anyway, and
# it has to be independent of the plan's arithmetic to be worth anything - the
# plan of that very block reports `coverage: 0.895` and believes it.
#
# So the primary signal is pixels of the delivered video: Vision is asked for
# faces on a frame of the finished mp4. Measured on all eight blocks of that
# render, the separation is total - every one of the seven blocks the user
# accepted yields exactly one face (0.15-0.61 of the frame high, captions,
# watermark and the bottom scrim over the picture notwithstanding), and the
# rejected block yields none at any of the three sample points. The overlays
# were the reason to doubt this approach and they turned out not to matter:
# they sit below the faces, and Vision reads what is left.
#
# Only a block whose plan *promised* a face is asked the question
# (`roi_source: faces`), and a block that shows none is not failed on that
# alone. Two things can put no face in a correctly framed picture: footage
# where the person turned away mid-block, and a window that missed them. The
# source tells the two apart - the same second look freeze_verdict() takes for
# the same kind of ambiguity - and the number that decides it is CF-0292's
# `smart_crop.subject_coverage()`, called on a *fresh* detection of the source
# frame against the window the block is actually framed with. On delver block
# 7 that reads 0.515 against the plan's own 0.65 floor: the window kept half
# of the nearer face, which is the defect said in numbers.
SUBJECT_PROBE_FRACTIONS = (0.5, 0.25, 0.75)


def min_subject_coverage(plan):
    """The coverage floor this plan was built with, or the shared default.

    `qc_thresholds.min_coverage` is what build_render_plan.py accepted its
    assets under (and what `--min-coverage` relaxes), so the gate on the far
    end of the render judges by the same number rather than by one of its own.
    A plan carrying no thresholds - built before they were recorded, or a test
    fixture - falls back to common.MIN_COVERAGE, which is that default.
    """
    return float((plan.get("qc_thresholds") or {}).get("min_coverage")
                 or MIN_COVERAGE)


def detect_faces(path):
    """Vision's faces on one image as `{"roi", "parts", "size"}`, or None.

    None means "no face here", not "nothing here": find_roi() falls back to
    attention saliency when it finds no face, and a salient box is not a
    person. Only the `faces` source answers the question this gate asks.
    """
    import smart_crop  # lazy: pulls in Vision/Quartz, and --audio-only never needs it
    roi, size, source, _single, parts = smart_crop.find_roi(str(path))
    if source != "faces" or not parts:
        return None
    return {"roi": roi, "parts": parts, "size": size}


def delivered_frame(video, at, tmp, tag):
    """One frame of the FINISHED video at composition time `at`.

    Returns the PNG written into `tmp`, or None when the frame could not be
    read. This is the one place in the repo that says what "a frame of the
    render" is: the CF-0294 subject gate reads its faces off it, and
    CF-0298's frame_judge_pack.py builds the judge's contact sheets out of
    it. Two gates that ask a question about the delivered picture have to be
    looking at the same picture, taken the same way, or their answers cannot
    be compared - which is why this is a function and not two grab_frame()
    calls that happen to agree today.
    """
    out = Path(tmp) / f"{tag}.png"
    if not grab_frame(video, at, out):
        return None
    return out


def delivered_face(video, at, tmp, tag):
    """Is there a face in the finished picture at composition time `at`?

    True/False, or None when the frame could not be read at all.
    """
    frame = delivered_frame(video, at, tmp, tag)
    if frame is None:
        return None
    return detect_faces(frame) is not None


def source_frame(block, at, tmp, tag):
    """The picture the block's own *source* holds at composition time `at`, as
    a PNG path, or None when it cannot be looked at.

    Its own function since CF-0327: two gates now ask the source what it was
    showing - the subject gate (is the face in the window) and the panel gate
    (is the shot's inset panel in the window) - and they have to be looking at
    the same frame, taken the same way, for the same reason delivered_frame()
    is one function and not two grab_frame() calls that agree today.
    """
    asset = block["asset"]
    src = asset.get("src")
    if not src or not Path(src).exists():
        return None
    if asset.get("kind") == "still":
        return Path(src)        # the held frame itself; nothing to seek into
    ts = source_time(block, at)
    clip_seconds = media_duration(src)
    if not clip_seconds:
        return None
    # Past the end, OffthreadVideo holds the last frame - so that is the
    # picture the viewer is being shown, and that is the frame to judge.
    # Same reading of the renderer as freeze_verdict()'s.
    frame = Path(tmp) / f"{tag}_src.png"
    if not grab_frame(src, min(ts, clip_seconds - LAST_FRAME_EPSILON), frame):
        return None
    return frame


def promised_subject(block, at, tmp, tag, aspect=(9, 16)):
    """What the source was showing at composition time `at`, and how much of
    the nearest face the window this block is framed with keeps.

    Returns `(faces, coverage, frame, found)`: the number of faces the source
    frame has there and CF-0292's `subject_coverage()` of them against the
    delivered window, or `(0, None, frame, None)` when the source has no face
    there either, or `(None, None, None, None)` when the source could not be
    looked at. `frame` is the source picture that was asked (CF-0367:
    window_face() asks it again, about the window alone) and `found` is
    detect_faces()' answer about it (CF-0550: closeup_share() sizes the faces
    against the window from it, without a second Vision call).

    The detection is made here and now rather than read off the plan on
    purpose - the plan's own `coverage` is exactly the number that was wrong
    in the case this gate exists for, and a watchdog that trusts it watches
    nothing.
    """
    import smart_crop
    frame = source_frame(block, at, tmp, tag)
    if frame is None:
        return None, None, None, None
    asset = block["asset"]
    found = detect_faces(frame)
    if not found:
        return 0, None, frame, None
    size, parts = found["size"], found["parts"]
    info = {"source_size": {"width": size[0], "height": size[1]},
            "roi": smart_crop.roi_dict(found["roi"]), "roi_source": "faces",
            # analyse()'s own rule: one face *is* the ROI, so parts are only
            # carried when there is a choice to be made between them.
            "roi_parts": ([smart_crop.roi_dict(p) for p in parts]
                          if len(parts) > 1 else None)}
    focus = (asset["focus"]["x"], asset["focus"]["y"])
    coverage = smart_crop.subject_coverage(info, focus, asset.get("zoom", 1.0),
                                           aspect[0], aspect[1],
                                           asset.get("fit", "cover"))
    return len(parts), coverage, frame, found


# CF-0367: the one case the second look above cannot explain - the source has
# a face, the window keeps all of it, and the finished picture has none - has
# two causes that look identical from here. Either the render did not show
# what the window holds (a real fault), or Vision only finds that face with
# the rest of the frame around it, and the window - which *is* the delivered
# picture - is simply a picture it does not resolve. Batch 2026-09-23T1722Z,
# american-dread-story block 6: a strict profile in a 1080x1080 held frame,
# found at confidence 0.583 as a 155px face at (208, 274), wholly inside the
# 608px window at x=125; the same pixels cut to that window
# (CGImageCreateWithImageInRect, nothing resampled) show Vision no face, and
# neither do the render's frames at 23.3/24.09/25.09/26.09s - while a look at
# the frame shows the same profile on screen. The gate was convicting the
# framing for the detector's limit. So the window is asked on its own: a face
# there that the render lost is a fault; no face there either is not judged.
def detect_faces_in(path, rect):
    """Faces Vision finds on `rect` of the image at `path` - a list, empty for
    none - or None when the crop could not be looked at. World-touching, so
    it is its own function, the way detect_faces() is."""
    import smart_crop
    try:
        return smart_crop.faces_in_rect(str(path), rect)
    except (Exception, SystemExit):
        return None


def window_face(block, frame, aspect=(9, 16)):
    """Does the source frame, cut to the window this block is framed with,
    show Vision a face? True/False, or None when it could not be asked."""
    import smart_crop
    asset = block["asset"]
    if frame is None:
        return None
    try:
        # The frame's own size first: it is the picture being cut, and
        # promised_subject() measured its coverage on exactly that size.
        from PIL import Image
        with Image.open(frame) as im:
            w, h = im.size
    except Exception:
        size = asset.get("source_size") or {}
        w, h = size.get("width"), size.get("height")
    if not (w and h):
        return None
    rect = smart_crop.delivered_window((w, h), (asset["focus"]["x"], asset["focus"]["y"]),
                                       asset.get("zoom", 1.0), aspect[0], aspect[1],
                                       asset.get("fit", "cover"))
    found = detect_faces_in(frame, rect)
    if found is None:
        return None
    return bool(found)


# CF-0550: the face too big to be found. Rebuild 2026-10-05T1244Z, harbourlights
# block 13 (20.65-21.58s, shot -gp7j-DhWDU:20, "Close-up of a man's tense
# face", zoom 1.32): the source has the face, the window keeps 81% of it and
# Vision finds it in the window's own cut of the source - and none of the
# three delivered frames shows Vision a face, so the gate failed the video
# (-61, crop_cuts_subject) and the rebuild spent an attempt. Replayed with
# `remotion still` on the same window (the attempt-1 mp4 was overwritten):
# the face in the window is 485px wide against a 462px window - wider than
# the delivered frame - and the caption band (1248-1382px) runs across its
# mouth and chin. The plain crop with no overlays is found at 1032px of
# 1080; with the band over it, Vision answers saliency at every scale
# (x0.5, x0.33, x0.25). It has no "too big" answer - it just says nothing.
#
# Two second looks, both only on the one path that is about to fail a block
# (source face, window keeps it, window shows it, render shows none):
#
#   - the delivered frame again, at half size in the middle of a black
#     canvas twice its size (pad_frame()): the face is then an ordinary one
#     with room around it. On the harbourlights frames this finds it at 20.88s and
#     21.11s (not at 21.35s). A face found that way is a face - no record.
#   - when even that is empty and the best-served face, cut to the window, is
#     at least CLOSEUP_FACE_SHARE of the delivered frame's width or height,
#     the block is not judged: the geometry says the face fills the frame,
#     the window's own pixels say Vision sees it there, and the only thing
#     between that and the render is the detector's reach. Said in a note,
#     the way CF-0367's detector-context case is.
#
# 0.75: the faces this gate has measured on accepted renders are 0.15-0.61 of
# the frame (CF-0294's delver table: 326-493px of 1080), all found; harbourlights
# block 13 is 1.0. A face three quarters of the frame wide is past every face
# the gate's evidence covers, and is a close-up nobody frames by accident.
CLOSEUP_FACE_SHARE = 0.75
PAD_FRAME_SCALE = 0.5


def pad_frame(path, dest, scale=PAD_FRAME_SCALE):
    """The image at `path` shrunk by `scale` into the middle of a black
    canvas of its own size, written to `dest` - the delivered picture with
    room around it (CF-0550). Returns `dest`, or None when it could not be
    made. PIL only; detect_faces() is asked about it by the caller."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            sw, sh = max(1, round(w * scale)), max(1, round(h * scale))
            canvas = Image.new("RGB", (w, h), (0, 0, 0))
            canvas.paste(im.resize((sw, sh), Image.LANCZOS),
                         ((w - sw) // 2, (h - sh) // 2))
            canvas.save(dest)
        return Path(dest)
    except Exception:  # noqa: BLE001 - no padded look is no excuse bought
        return None


def detect_faces_padded(path):
    """detect_faces() on pad_frame() of the image at `path`, or None when it
    finds none or the padded copy could not be made. World-touching, so it is
    its own function, the way detect_faces_in() is."""
    padded = pad_frame(path, Path(path).with_name(Path(path).stem + "_pad.png"))
    if padded is None:
        return None
    try:
        return detect_faces(padded)
    except (Exception, SystemExit):
        return None


def closeup_share(block, found, aspect=(9, 16)):
    """CF-0550: how much of the delivered frame the biggest face of `found`
    (detect_faces() of the source frame) fills once cut to the window this
    block is framed with - the larger of its width and height shares of the
    window, 0.0 when no face reaches the window, None when unmeasurable."""
    import smart_crop
    asset = block["asset"]
    if not found or not asset.get("focus"):
        return None
    w, h = found["size"]
    wx, wy, ww, wh = smart_crop.delivered_window(
        (w, h), (asset["focus"]["x"], asset["focus"]["y"]),
        asset.get("zoom", 1.0), aspect[0], aspect[1], asset.get("fit", "cover"))
    if ww <= 0 or wh <= 0:
        return None
    best = 0.0
    for x, y, fw, fh in found["parts"]:
        iw = min(x + fw, wx + ww) - max(x, wx)
        ih = min(y + fh, wy + wh) - max(y, wy)
        if iw > 0 and ih > 0:
            best = max(best, iw / ww, ih / wh)
    return best


# CF-0363: the part of a block an insert hides. AssetLayer.jsx's InsertLayer
# puts a proof capture or a meme on an opaque black box over the block's whole
# picture zone - the block's own asset is still in the plan (the storyboard
# contract keeps it for the part the card is not up for) but nobody sees it
# under the card. Batch 2026-09-23T1722Z: paper-dragon block 3 is a proof card
# for its whole 14.11-20.33s and american-dread-story block 9 a meme for its
# whole span; the gate asked both for a face, found a page of text and a
# triangle, and failed videos that were exactly what the plan asked for.
#
# An uncovered stretch shorter than this is not judged either: it is the
# card's own dissolve in or out, not a shot anyone reads a face off.
SUBJECT_MIN_OPEN_S = 0.2
_EDGE_EPS = 1e-6


# AssetLayer.jsx returns for these asset kinds before it reaches InsertLayer.
# CF-0689: GraphicLayer (own_graphic) returns before it too - a graphic
# carries no insert over itself.
# CF-0811: a `sequence` and a `procedural` block are no longer among them -
# AssetLayer asks the insert first now, so a meme on a stretch-split block or
# in a hole is drawn (before 2026-10-19 it was in the plan and never on
# screen). A bare marker on them still is not: insert_has_picture() below.
_NO_INSERT_LAYER_KINDS = ("card", "split", "own_graphic")
# Where InsertLayer's opaque box is drawn over moving footage (freeze_covers).
_INSERT_OVER_FOOTAGE_KINDS = ("clip", "sequence")


def insert_window(block):
    """`(start, end)` of the composition time an opaque insert hides this
    block's picture for, or None when nothing does.

    Read the way the renderer reads it (AssetLayer.jsx insertSpan): an insert
    with its own `start_s`/`end_s` is up for that window (clamped to the block),
    one without is the whole block. Only an insert with a picture behind it
    counts - a bare marker with no file is a request answered `no_asset`, the
    same line assetless_rung.filled_by_insert() draws - and only an opaque one:
    InsertLayer paints its box black, so any background except an explicit
    `transparent`/`none` hides what is under it.

    CF-0460: and only where the renderer actually draws that box. A cutout
    meme (AssetLayer.jsx isCutout) is a figure laid on the block's own
    picture, which stays on screen - not a cover. A card, a split and an own
    graphic return before InsertLayer, so an insert in their plan is never
    drawn and hides nothing (a sequence and a procedural background did too,
    until CF-0811 moved the insert above them in AssetLayer.jsx). CF-0459 drew the same line
    for the freeze gate (freeze_covers()); without it here the face gate
    took such a block as covered and judged none of it.
    """
    ins = block.get("insert")
    if not assetless_rung.insert_has_picture(ins):
        return None
    if _is_cutout(ins):
        return None
    if (block.get("asset") or {}).get("kind") in _NO_INSERT_LAYER_KINDS:
        return None
    if str(ins.get("background", "black")).lower() in ("transparent", "none"):
        return None
    start, end = block["start"], block["end"]
    s, e = ins.get("start_s"), ins.get("end_s")
    if isinstance(s, (int, float)) and isinstance(e, (int, float)):
        s, e = max(start, s), min(end, e)
        if e <= s:
            return None
        return s, e
    return start, end


def cover_windows(block, plan=None):
    """CF-0442: every stretch of this block's picture a card of the plan
    hides, as `[{"kind", "layer", "window": (s, e)}]` clamped to the block,
    in the order the renderer stacks them.

    CF-0363 knew one card - the block's own opaque `insert` (a proof, a
    meme). Video.jsx lays two more over the blocks, and the gate has to see
    them the same way or it convicts the card's own design:

      comparison_line  plan["comparison_lines"], each up for its
                       `start_s`-`end_s` over whatever block is under it. The
                       badge and the fact strip sit where a centred face
                       usually is (comparisonGeometry.js: y = 260 and the
                       strip below it). Batch 2026-09-29T0705Z, harbourlights
                       block 4 (12.64-15.36s): the face is in the picture,
                       the line (12.26-15.60s) is on it, and the gate failed
                       a video the user then accepted - a card over a face is
                       the norm, not a defect (the user, 2026-09-28).
      end_card         plan["end_card"] from its `start_s`: the channel's
                       mark, full frame.

    Time only, not geometry: the gate asks whether a face can be seen, and
    under any of these cards the honest answer is "not by design", which is
    silence, never an accusation (see subject_blocks()).
    """
    start, end = block["start"], block["end"]
    out = []
    w = insert_window(block)
    if w is not None:
        out.append({"kind": block["insert"].get("kind", "insert"),
                    "layer": "insert", "window": w})
    for line in (plan or {}).get("comparison_lines") or []:
        if not isinstance(line, dict):
            continue
        s, e = line.get("start_s"), line.get("end_s")
        if not (isinstance(s, (int, float)) and isinstance(e, (int, float))):
            continue
        s, e = max(start, s), min(end, e)
        if e > s:
            out.append({"kind": "comparison_line", "layer": "comparison_line",
                        "window": (s, e)})
    card = (plan or {}).get("end_card")
    if isinstance(card, dict) and isinstance(card.get("start_s"), (int, float)):
        s = max(start, card["start_s"])
        if end > s:
            out.append({"kind": "end_card", "layer": "end_card",
                        "window": (s, end)})
    return out


def open_pieces(block, covers):
    """CF-0459: every stretch of the block none of `covers` is over, as
    `[(start, end), ...]` in time order - the complement of their windows
    inside the block. Empty when the cards leave nothing open."""
    start, end = block["start"], block["end"]
    pieces, cur = [], start
    for s, e in sorted(c["window"] for c in covers):
        if s > cur:
            pieces.append((cur, s))
        cur = max(cur, e)
    if end > cur:
        pieces.append((cur, end))
    return pieces


def _is_cutout(ins):
    """AssetLayer.jsx isCutout(): a meme cut out and laid on the block's own
    picture rather than on a black box - the picture stays on screen."""
    cut = ins.get("cutout") if isinstance(ins, dict) else None
    return bool(ins.get("kind") == "meme" and isinstance(cut, dict)
                and cut.get("rect") and cut.get("image") and cut.get("render_src")
                and ins.get("placement") in ("cutout_on_subject",
                                             "cutout_in_corner"))


def freeze_covers(block, target, plan=None):
    """CF-0459: the cards that hide one picture of `frozen_blocks()` whole,
    as cover_windows() records over `target`'s own span.

    Narrower than cover_windows() on purpose, because a freeze is read off a
    band of the frame, not off a face:

      insert           a proof or a meme on its opaque black box over the
                       whole picture zone (AssetLayer.jsx InsertLayer,
                       "fitted whole on black") - the clip under it is not on
                       screen, so its motion is not either. Only where the
                       renderer mounts it: over a `clip` or (CF-0811) a
                       `sequence` block (a split and a card return before
                       InsertLayer), and not a
                       cutout meme, which sits on the picture rather than
                       over it (AssetLayer.jsx isCutout).
      end_card         the channel's mark, full frame.

    The comparison line is *not* one: it is a badge and a strip across part
    of the band (comparisonGeometry.js), the clip keeps playing around it, and
    a clip frozen under it is a frozen picture the viewer sees. Counting it
    would stop judging every block the line runs over (0200Z
    you-can-see-everything block 8), which is a weaker gate, not a fix.
    """
    keep = []
    for c in cover_windows(target, plan):
        if c["layer"] == "end_card":
            keep.append(c)
        elif (c["layer"] == "insert"
              and (block.get("asset") or {}).get("kind") in _INSERT_OVER_FOOTAGE_KINDS
              and not _is_cutout(block.get("insert"))):
            keep.append(c)
    return keep


def open_span(block, plan=None):
    """The longest stretch of the block the viewer sees its own asset in:
    `(start, end, covers)` with `covers` the cover_windows() over it (empty
    when nothing is), or `(None, None, covers)` when the cards leave nothing
    worth judging.

    The longest piece rather than the pieces stitched together: a probe that
    lands on the seam of two pieces lands on the card's edge.
    """
    start, end = block["start"], block["end"]
    covers = cover_windows(block, plan)
    if not covers:
        return start, end, covers
    pieces = open_pieces(block, covers)
    if not pieces:
        return None, None, covers
    a, b = max(pieces, key=lambda ab: ab[1] - ab[0])
    if b - a < SUBJECT_MIN_OPEN_S - _EDGE_EPS:
        return None, None, covers
    return a, b, covers


def _cover_fields(covers):
    """What a subject record says about the cards over its block: every one
    under `covered_by`, and CF-0363's `insert_kind`/`insert_window` kept for
    the insert, so a reader of the old record reads the same thing."""
    fields = {"covered_by": [{"kind": c["kind"], "layer": c["layer"],
                              "window": [round(c["window"][0], 2),
                                         round(c["window"][1], 2)]}
                             for c in covers]}
    ins = next((c for c in covers if c["layer"] == "insert"), None)
    if ins is not None:
        fields["insert_kind"] = ins["kind"]
        fields["insert_window"] = fields["covered_by"][covers.index(ins)]["window"]
    return fields


def _cover_phrase(covers):
    parts = []
    for c in covers:
        s, e = c["window"]
        what = (f"a {c['kind']} insert" if c["layer"] == "insert"
                else "the comparison line" if c["layer"] == "comparison_line"
                else "the end card")
        parts.append(what if len(covers) == 1 else f"{what} ({s:.2f}-{e:.2f}s)")
    return " and ".join(parts) + (" covers" if len(covers) == 1 else " cover")


def _framed_on_a_face(asset):
    """Is this picture framed on a face with a crop that can lose it - the
    only pictures subject_blocks() judges (see its docstring)."""
    return (asset.get("roi_source") == "faces" and bool(asset.get("focus"))
            and asset.get("fit", "cover") == "cover"
            # AssetLayer.jsx draws a blur_fill picture whole over its own
            # blurred copy (BlurFill) whatever its `fit` says: contained.
            and not (asset.get("presentation") or {}).get("blur_fill"))


# CF-0892: a `sequence` block was judged as if its first cut were the whole
# block. build_render_plan.py mirrors the first cut's fields onto the
# sequence asset (src, fit, focus, roi_source), so the gate saw "a cover
# picture framed on a face" and probed the middle of the block - which lies
# in a later cut - against the *first* cut's clip held on its last frame.
# Batch example-film/2026-10-28T1505Z, all three refused F on this alone
# (-61): ali-g-who-iz-i block 13 (36.07s - cut 1, a contained 1920x800
# strip, against cut 0's 1920x590 source), the-gilded-age block 8 (22.53s -
# cut 1, a contained wide shot of the staircase, against cut 0's two faces)
# and crystal-lake block 5 (21.49s - cut 3, contained, against cut 0's face at
# x=1767 of 1920, "0% kept" by a window that was never on screen there). A
# contained cut is never judged (the whole shot is on screen), and a cut is
# judged against its own clip, at its own second, with its own framing.
def subject_pictures(block):
    """The pictures of one block the subject gate asks for a face, as
    `[(cut index or None, view, src_block)]`: `view` is the picture's own
    on-screen span (`start`/`end`) with its own `asset`, `src_block` the same
    picture anchored so that common.source_time() reads its clip at the
    right second. Empty when nothing on screen is framed on a face.

    A plain block is itself. A `sequence` is each of its cuts for the
    composition seconds that cut is on screen, read the way the renderer
    mounts them: Video.jsx mounts the block RENDER_CROSSFADE early (clamped
    at zero) and AssetLayer.jsx starts cut k `sum(seconds of the cuts
    before it)` (whole frames) after that mount, the last cut running to the
    block's end. Only the part of a cut inside the block's own start-end is
    judged - the crossfade is someone else's picture too."""
    asset = block.get("asset") or {}
    if asset.get("kind") != "sequence":
        return [(None, block, block)] if _framed_on_a_face(asset) else []
    out = []
    for k, cut, on, s, e in sequence_cuts(block):
        if (not isinstance(cut, dict) or not _framed_on_a_face(cut)
                or cut.get("kind") not in ("clip", "still")
                or e - s < SUBJECT_MIN_OPEN_S - _EDGE_EPS):
            continue
        view = {**block, "start": s, "end": e, "asset": cut}
        out.append((k, view, source_clock(view, on)))
    return out


def subject_blocks(video, plan):
    """Catch a block that was framed on a face and delivered none (DoD 7).

    One record per block that showed no face - nothing is recorded for a block
    that did, the way frozen_blocks() records only blocks that read as stills.
    `fault` says whether the missing face is the framing's doing or the
    footage's.

    A block is only asked at all when its plan asset says `roi_source: faces`
    and carries the framing to reproduce (`focus`). Anything else - an old
    plan without those fields, a card, a procedural background, a split,
    whose pictures live on its sides rather than on the block - is not
    judged (a sequence is judged on its cuts, CF-0892, below). That is deliberate: this gate refuses videos, so a
    field it cannot read is silence, never an accusation.

    `fit: contain` is not judged either, and for a stronger reason than
    silence: a contained picture is *entirely* on screen, so no crop can have
    lost anybody and there is nothing here to catch. Asking anyway produces
    false failures, which is not a guess - 2026-09-03T2037Z ink-teaser-cards
    block 13 is a 1920x960 title card letterboxed into 1080x1920, and the
    72px face in its source arrives 41px wide, under what Vision resolves.
    The gate read "no face" on a picture that shows the whole shot.

    CF-0363: nor is the part of a block an opaque insert (a proof card, a
    meme) sits over - there is no face under a card to be seen, by design.
    A block covered for its whole span gets a record with `covered: True`
    and no frame is looked at; a block covered for part of it is sampled
    only over its longest uncovered stretch (open_span()).

    CF-0442: "a card" is any card of the plan, not only `block.insert` - the
    comparison line and the end card too (cover_windows()). The covered
    record is what the score log prices as `card_over_face` (0); a fault on
    the open part stays `crop_cuts_subject`.

    CF-0892: a `sequence` is judged cut by cut (subject_pictures()) - each
    cut framed on a face, over its own seconds, against its own clip; a
    contained cut not at all. A block still yields one record: its first fault,
    else its first note.
    """
    floor = min_subject_coverage(plan)
    # The window is reproduced against the aspect the video is actually
    # delivered in, taken off the plan rather than assumed - delivered_window()
    # only uses the ratio, and 9:16 is a default for a fixture without an
    # `output`, not a constant of this gate.
    out = plan.get("output") or {}
    aspect = (out.get("width") or 9, out.get("height") or 16)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, block in enumerate(plan["blocks"]):
            records = []
            for k, view, src_block in subject_pictures(block):
                record = _judge_subject(video, plan, i, k, view, src_block,
                                        tmp, floor, aspect)
                if record is not None:
                    records.append(record)
            # One record per block, as before CF-0892: a sequence whose two
            # cuts both lost the face is one crossing the viewer saw, one
            # case - its first fault, else its first note (a card over it).
            faults = [r for r in records if r.get("fault")]
            if faults or records:
                results.append((faults or records)[0])
    return results


def _judge_subject(video, plan, i, k, block, src_block, tmp, floor, aspect):
    """One picture of subject_blocks(): the record it earns, or None when
    the delivered picture shows a face (or the picture is not judged).
    `block` is the picture's own on-screen span (a whole block, or one cut
    of a sequence), `src_block` the same picture anchored so that
    common.source_time() reads its own clip at the right second."""
    asset = block["asset"]
    tag = f"subj{i}" if k is None else f"subj{i}c{k}"
    first, last, covers = open_span(block, plan)
    if first is None:
        s0 = min(c["window"][0] for c in covers)
        e0 = max(c["window"][1] for c in covers)
        return {"index": i, **({} if k is None else {"cut": k}),
                "at": round((s0 + e0) / 2, 2),
                "coverage": None, "source_faces": None,
                "floor": floor, "fault": False, "covered": True,
                **_cover_fields(covers),
                "reason": f"{_cover_phrase(covers)} "
                          f"the block's picture for "
                          f"{s0:.2f}-{e0:.2f}s, the whole "
                          f"{'block' if k is None else 'cut'}, "
                          f"so there is no face to see by "
                          f"design and the block was not "
                          f"judged"}
    span = last - first
    mid = first + span * SUBJECT_PROBE_FRACTIONS[0]
    # The middle of the block first, and two more samples only if it
    # came up empty. A block that is fine costs one frame; a face that
    # happens to be turned away at one instant of a moving clip is not
    # convicted on that instant.
    seen, unreadable = False, False
    probed = []     # CF-0550: the frames asked, for a padded look
    for n, f in enumerate(SUBJECT_PROBE_FRACTIONS):
        got = delivered_face(video, first + span * f, tmp,
                             f"{tag}_{n}")
        if got is None:
            unreadable = True
            break
        probed.append(Path(tmp) / f"{tag}_{n}.png")
        if got:
            seen = True
            break
    if seen:
        return None
    record = {"index": i, "at": round(mid, 2), "coverage": None,
              "source_faces": None, "floor": floor}
    if k is not None:
        record["cut"] = k
    if covers:
        # Said on the record, so a fault on a partly covered block
        # reads as a judgement of the part the card left open.
        record["judged_span"] = [round(first, 2), round(last, 2)]
        record.update(_cover_fields(covers))
    if unreadable:
        return {**record, "fault": True,
                "reason": "the finished picture could not be "
                          "read here, so nothing checked "
                          "whether the subject is in it"}
    faces, coverage, frame, found = promised_subject(
        src_block, mid, tmp, tag, aspect=aspect)
    record["source_faces"] = faces
    record["coverage"] = None if coverage is None else round(coverage, 3)
    if faces is None:
        return {**record, "fault": True,
                "reason": f"no face in the delivered picture and the "
                          f"source ({asset.get('src')}) could not be "
                          f"checked to explain it"}
    elif faces == 0:
        return {**record, "fault": False,
                "reason": "the source has no face here either - the "
                          "shot turned away, which is footage, not a "
                          "framing fault"}
    elif coverage < floor:
        return {**record, "fault": True,
                "reason": f"the source has {faces} face(s) here and the "
                          f"window this block is framed with keeps only "
                          f"{coverage:.0%} of the best-served one "
                          f"(< {floor:.0%}) - the crop landed off the "
                          f"subject"}
    else:
        held = window_face(src_block, frame, aspect=aspect)
        if held is False:
            # CF-0367: the window itself shows Vision nobody, so
            # neither can the picture made of it - not judged, and
            # said so, the way a turned-away face is.
            return {**record, "fault": False,
                    "detector_context": True,
                    "reason": f"the source has {faces} face(s) here "
                              f"and the window keeps {coverage:.0%} "
                              f"of the best-served one, but Vision "
                              f"finds it only with the whole frame "
                              f"around it - the source cut to this "
                              f"window shows it no face either, so "
                              f"the empty answer is the detector's, "
                              f"not the framing's, and the block was "
                              f"not judged (CF-0367)"}
        if held and any(detect_faces_padded(p) for p in probed):
            # CF-0550: the delivered picture does show a face, once
            # it has room around it - a face is a face.
            return None
        share = closeup_share(src_block, found, aspect=aspect) if held else None
        if share is not None and share >= CLOSEUP_FACE_SHARE:
            return {**record, "fault": False,
                    "detector_context": True,
                    "extreme_closeup": True,
                    "face_share": round(share, 3),
                    "reason": f"the source has {faces} face(s) here, "
                              f"the window keeps {coverage:.0%} of the "
                              f"best-served one and shows Vision that "
                              f"face, which fills {share:.0%} of the "
                              f"delivered frame - an extreme close-up "
                              f"Vision does not resolve on the render "
                              f"(captions across it, no room around "
                              f"it, nor at half size), so the empty "
                              f"answer is the detector's, not the "
                              f"framing's, and the block was not "
                              f"judged (CF-0550)"}
        return {**record, "fault": True,
                "reason": f"the source has {faces} face(s) here and the "
                          f"window keeps {coverage:.0%} of the "
                          f"best-served one, yet the delivered picture "
                          f"shows none" +
                          ("" if held else " (and the window alone "
                           "could not be checked)")}


def panel_blocks(video, plan):   # noqa: ARG001 - see the docstring's last line
    """CF-0327: catch a block that delivered a sliver of an inset panel.

    The defect the user found on `mormon-wives-comeback` at 29 s: a shot with
    an on-screen panel - a split screen, an article, a phone being read out -
    framed so that a quarter of that panel arrives pressed against the left
    edge of the frame and the rest is gone. For a second and a half the viewer
    is shown that there was something to see and not shown it.

    One record per block whose source carries a panel, `fault` true only for
    the `cut` verdict: a panel wholly on screen and a panel wholly off it are
    both fine, and this gate has exactly one opinion, which is about the state
    between them (inset_panel.py).

    Measured on the *source* against the window the block is framed with, the
    way promised_subject() measures the subject and for the same reason: the
    delivered frame alone cannot say how much of a panel is missing, because
    what is missing is not in it.

    Not judged, and silent about it: a picture with no `focus` (a card, a
    procedural background, a split), a `contain` or `blur_fill` delivery (the
    whole source is on screen, so nothing is cut by construction), and - CF-0363
    - the stretch an opaque insert covers, which is sampled through open_span()
    exactly as the subject gate samples it.

    CF-0894: a `sequence` is judged cut by cut, on the layout every gate
    reads it with (sequence_cuts()) - each cropped cut over its own seconds,
    against its own clip at its own second, with its own framing. Its rows
    carry `cut`; whether a cut's fault refuses and costs like a plain
    block's is configuration (inset_panel.sequence_cuts_judged(), main()).

    `video` is taken and not read. The signature is frozen_blocks()' and
    subject_blocks()' on purpose - main() calls the three the same way - and
    this one reads the source rather than the render because the render cannot
    answer its question, not because it is a different kind of gate.
    """
    out = plan.get("output") or {}
    aspect = (out.get("width") or 9, out.get("height") or 16)
    floor = inset_panel.floor_of(plan)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, block in enumerate(plan["blocks"]):
            for k, view, src_block in panel_pictures(block):
                record = _judge_panel(i, k, view, src_block, tmp, floor, aspect)
                if record is not None:
                    results.append(record)
    return results


def split_panel_faults(panels, plan):
    """CF-0894: panel_blocks()' faults as `(judged, measured_only)` - the
    rows the gate's mode and the score act on (`panel_cut_blocks`), and the
    sequence cuts' faults kept apart while the plan does not have them
    judged (inset_panel.sequence_cuts_judged())."""
    judged_seq = inset_panel.sequence_cuts_judged(plan)
    faults = [p for p in panels if p.get("fault")]
    judged = [p for p in faults if judged_seq or p.get("cut") is None]
    apart = [p for p in faults if not judged_seq and p.get("cut") is not None]
    return judged, apart


def _cropped(asset):
    """A picture the window can cut: framed (`focus`), delivered `cover`,
    and not a blur_fill (AssetLayer.jsx draws that one whole whatever its
    `fit` says)."""
    return (isinstance(asset, dict) and bool(asset.get("focus"))
            and asset.get("fit", "cover") == "cover"
            and asset.get("kind") in ("clip", "still")
            and not (asset.get("presentation") or {}).get("blur_fill"))


def panel_pictures(block):
    """CF-0894: the pictures of one block the panel gate measures, as
    `[(cut index or None, view, src_block)]` - subject_pictures()' shape:
    `view` the picture's on-screen span with its own `asset`, `src_block`
    the same picture anchored on its own clip clock (source_clock())."""
    asset = block.get("asset") or {}
    if asset.get("kind") != "sequence":
        return [(None, block, block)] if _cropped(asset) else []
    out = []
    for k, cut, on, s, e in sequence_cuts(block):
        if not _cropped(cut) or e <= s:
            continue
        view = {**block, "start": s, "end": e, "asset": cut}
        out.append((k, view, source_clock(view, on)))
    return out


def _judge_panel(i, k, view, src_block, tmp, floor, aspect):
    """One picture of panel_blocks(): its row, or None when the picture
    carries no panel (or cannot be looked at)."""
    asset = view["asset"]
    first, last, _window = open_span(view)
    if first is None:
        return None
    at = round((first + last) / 2, 2)
    tag = f"panel{i}" if k is None else f"panel{i}c{k}"
    frame = source_frame(src_block, at, tmp, tag)
    if frame is None:
        return None
    panel = inset_panel.find_panel(frame)
    if not panel:
        return None
    size = frame_size(frame) or (
        (asset.get("source_size") or {}).get("width"),
        (asset.get("source_size") or {}).get("height"))
    if not size or not all(size):
        return None
    window = inset_panel.window_for(size, asset["focus"]["x"],
                                    asset["focus"]["y"],
                                    asset.get("zoom", 1.0),
                                    asset.get("fit", "cover"), aspect)
    visible = inset_panel.visible_fraction(panel, window, size)
    seen = inset_panel.verdict(visible, floor)
    record = {"index": i, **({} if k is None else {"cut": k}),
              "at": at, "panel": panel, "floor": floor,
              "visible": visible, "verdict": seen,
              "fault": seen == inset_panel.CUT}
    what = "block" if k is None else f"cut {k} of this block"
    if record["fault"]:
        record["reason"] = (
            f"the shot carries an inset panel across "
            f"{panel['x0']:.2f}-{panel['x1']:.2f} of its width (its borders run "
            f"down {panel['rows']:.0%} of the frame) and the window this {what} "
            f"is framed with keeps {visible:.0%} of it (< {floor:.0%}) - the "
            f"viewer gets a strip of it against the edge of the frame")
    else:
        record["reason"] = (
            f"the shot's inset panel ({panel['x0']:.2f}-{panel['x1']:.2f} of its "
            f"width) is delivered {seen} at {visible:.0%}")
    return record


def meme_caption_blocks(video, plan):
    """CF-0379: a block showing an insert that promises our captions, with
    words being spoken over it and nothing of ours on the frame.

    The defect the user found on 2026-09-24: while a reaction meme was up our
    word-by-word captions were gone for its whole length - the renderer hid
    them for any insert at all (CF-0071's rule, which belongs to the proof
    layer). The plan's half of the fix is `inserts/meme.json` saying
    `our_captions: "shown"`; the renderer's half is the captions staying on
    (since CF-0394 in their one fixed band, with the meme fitted above it). This is the gate that reads the
    pixels and says whether both halves arrived.

    One record per block whose insert says `captions: "shown"`, `fault` true
    only for the `blank` verdict. A proof insert is not judged here at all -
    it hides the captions on purpose and its reason is intact - and neither is
    a stretch of an insert with no word spoken over it: there is no caption
    due there, and accusing the gap between two phrases of having lost a line
    is how a gate earns its way into being switched off.

    Measured on the delivered frame, inside the band the renderer puts the
    captions in (meme_captions.band_box mirrors captionBand.js). `video` is read, unlike panel_blocks() - the question
    here is exactly what reached the file.
    """
    from PIL import Image

    words = plan.get("words") or []
    floor = meme_captions.floor_of(plan)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, block in enumerate(plan["blocks"]):
            if not meme_captions.captioned_insert(block):
                continue
            first, last = meme_captions.insert_span(block)
            at = meme_captions.spoken_moment(words, first, last)
            if at is None:
                continue
            x, y, w, h = meme_captions.band_box(plan, block["insert"])
            if w <= 0 or h <= 0:
                continue
            f = Path(tmp) / f"memecap{i}.png"
            if not grab_frame(video, at, f, extra_vf=f"crop={w}:{h}:{x}:{y}"):
                continue
            with Image.open(f) as im:
                px = luma_pixels(im.convert("L"))
            # CF-0572: "caption-white" is the channel's caption fill.
            ink = meme_captions.ink_fraction(px, white=meme_captions.ink_luma(plan))
            seen = meme_captions.verdict(ink, floor)
            record = {"index": i, "at": at, "kind": (block["insert"] or {}).get("kind"),
                      "band": {"x": x, "y": y, "w": w, "h": h},
                      "ink": round(ink, 5), "floor": floor, "verdict": seen,
                      "fault": seen == meme_captions.BLANK}
            if record["fault"]:
                record["reason"] = (
                    f"the block carries a {record['kind']} insert that leaves our "
                    f"captions on, a word is being spoken at {at}s, and the caption "
                    f"band at y {y}-{y + h} is {ink:.3%} caption-white "
                    f"(< {floor:.3%}) - the viewer is shown a picture with no line")
            else:
                record["reason"] = (
                    f"the block's {record['kind']} insert is captioned at {at}s - "
                    f"{ink:.2%} of the band at y {y}-{y + h} is caption-white")
            results.append(record)
    return results


def frame_size(path):
    """`(width, height)` of an image, or None. The frame's own size rather
    than the plan's claim about it - window_face() reads it the same way, and
    for the same reason: the window was measured against these pixels."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:                                   # noqa: BLE001
        return None


def caption_design_guard():
    """Check the renderer still supplies what makes captions legible.

    Cheap, deterministic, and it fails exactly when the real risk appears -
    someone thinning the stroke or shrinking the type. Both are read as drawn:
    the theme's numbers scaled by captionBand.js CAPTION_SCALE (CF-0394).
    """
    failures = []
    captions = RENDER / "src" / "components" / "Captions.jsx"
    video = RENDER / "src" / "Video.jsx"
    band = RENDER / "src" / "lib" / "captionBand.js"
    if not captions.exists() or not video.exists() or not band.exists():
        return ["renderer sources not found - cannot verify caption legibility"]

    src = captions.read_text() + video.read_text()
    scale_m = re.search(r"CAPTION_SCALE\s*=\s*([0-9.]+)", band.read_text())
    scale = float(scale_m.group(1)) if scale_m else 1.0

    stroke = re.search(r"captionStroke:\s*(\d+)", src)
    drawn = max(1, round(int(stroke.group(1)) * scale)) if stroke else None
    if drawn is None or drawn < MIN_STROKE_PX:
        failures.append(
            f"caption stroke is {drawn if drawn is not None else 'absent'}px "
            f"(< {MIN_STROKE_PX}px) - the stroke is what guarantees contrast on "
            f"any background; without it legibility depends on the footage")

    size = re.search(r"captionSize:\s*(\d+)", src)
    drawn = round(int(size.group(1)) * scale) if size else None
    if drawn is None or drawn < MIN_CAPTION_FONT_PX:
        failures.append(
            f"caption size is {drawn if drawn is not None else 'absent'}px "
            f"(< {MIN_CAPTION_FONT_PX}px) - too small for a phone at arm's length")
    return failures


def relative_luminance(mean_srgb):
    """WCAG relative luminance from a mean 0-255 channel value."""
    c = mean_srgb / 255
    lin = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return lin


def caption_contrast(video, plan, samples=8):
    """Contrast behind the captions, measured where they actually sit.

    Recorded, not gated: the stroke floors it (see MIN_STROKE_PX), and since
    CF-0394 there is no scrim under the band - this is where a change that
    erodes the floor would become visible on real footage.
    """
    from PIL import Image

    # The band Captions.jsx draws in - meme_captions.band_box, the mirror of
    # captionBand.js (CF-0394: fixed, its foot on the bottom dead zone).
    left, band_y, band_w, band_h = meme_captions.band_box(plan)

    # The narration's own length, never the composition's - so the samples
    # stop at the last word and none of them lands on the tail. That was
    # already true for CF-0117's drawn card (there are no captions over it),
    # and CF-0141 makes it load-bearing: past this point the frame is the
    # channel's own ending clip, which carries no captions of ours and is not
    # judged by these gates at all (decision 3). Sampling `duration
    # .composition` here would measure the contrast of a caption band that is
    # not there, on footage nobody asked us to grade.
    duration = plan["audio"]["duration"]
    worst = None
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(samples):
            t = duration * (i + 0.5) / samples
            f = Path(tmp) / f"cap{i}.png"
            if not grab_frame(video, t, f,
                              extra_vf=f"crop={band_w}:{band_h}:{left}:{band_y}"):
                continue
            with Image.open(f) as im:
                px = luma_pixels(im.convert("L").resize((80, 40)))
            mean = sum(px) / len(px)
            lum = relative_luminance(mean)
            # White fill against the band, and black stroke against it.
            white = 1.05 / (lum + 0.05)
            black = (lum + 0.05) / 0.05
            best = max(white, black)
            if worst is None or best < worst[0]:
                worst = (best, round(t, 2), round(mean, 1))
    return worst


# CF-0794: the exit of a run that has no video to judge - a usage error, not
# a QC verdict (1) and not a score stop (4).
EXIT_NO_VIDEO = 2


def _no_video_exit(args, message, rc, extra=None, error="no_video"):
    """Print `message` (a JSON record under --json, so write_batch_metadata's
    qc_report reads a verdict and not an empty stdout) and exit `rc`.
    CF-0815: `error` is "no_plan" when it is the plan that cannot be read."""
    if getattr(args, "json", False):
        rec = {"passed": False, "video": str(args.video), "failures": [message],
               "error": error}
        rec.update(extra or {})
        json.dump(rec, sys.stdout, indent=2)
        print()
    else:
        print(f"QC: {message}")
    print(f"QC: ERROR: {message}", file=sys.stderr)
    sys.exit(rc)


def probe_or_exit(args):
    """CF-0794: ffprobe's reading of the video, or a clean exit.

    street-fighter (example-film 2026-10-18T0841Z) was stopped by its score
    before the render, so videos/street-fighter.mp4 never existed; the
    operator ran this gate on it anyway, ffprobe answered rc 1 with an empty
    JSON object and the run died on `KeyError: 'streams'`. Now:

    - a plan whose score log is already under N: the video was refused
      before the render. The refusal sidecar is made sure of (written when
      no stage wrote it) and the run exits 4, the score stop's own code,
      with the `SCORE F` line - nothing is recorded, there is nothing to QC;
    - no file / an empty file / a file ffprobe cannot read: a sentence
      naming the file, exit 2 (EXIT_NO_VIDEO), no traceback."""
    video = Path(args.video)
    if not args.audio_only:
        block = score_log.current(args.plan)
        if block is not None and score_log.stops(block) and not video.is_file():
            side = score_log.refusal_path(args.plan)
            side = (str(side) if side.exists() else
                    score_log.check(args.plan, block, score_log.script_id_for(args.plan),
                                    block.get("stopped_at") or score_log.STAGE_PLAN))
            line = score_log.stop_line(block, block.get("stopped_at") or "plan", side)
            _no_video_exit(args, f"{line} - refused before the render, there is no "
                                 f"video {video} to check", EXIT_SCORE_F,
                           extra={"score_stop": side, "score_line": block.get("line")})
    if not video.exists():
        _no_video_exit(args, f"no video at {video} - nothing to check (was it "
                             f"rendered? render_video.py's exit says why not)", EXIT_NO_VIDEO)
    if not video.is_file() or video.stat().st_size == 0:
        _no_video_exit(args, f"{video} is not a video file (empty or not a file) - "
                             f"nothing to check", EXIT_NO_VIDEO)
    try:
        info = probe_json(video)
    except Exception as e:  # noqa: BLE001 - a timeout or bad JSON is the same answer
        info, why = None, f"{type(e).__name__}: {e}"
    else:
        why = "ffprobe found no streams"
    if not isinstance(info, dict) or not isinstance(info.get("streams"), list) \
            or not info["streams"]:
        _no_video_exit(args, f"ffprobe cannot read {video} ({why}) - nothing to check",
                       EXIT_NO_VIDEO)
    return info


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("plan")
    p.add_argument("--json", action="store_true",
                   help="the full result as JSON on stdout (write_batch_metadata.py)")
    # CF-0025: the audio gates on a mix, without a render. build_soundtrack.py
    # takes seconds where render_video.py takes hours, so a change to the mix
    # can be validated on every video of a batch instead of on one re-render.
    # It is a *narrower* run, never a looser one: the same functions, the same
    # thresholds, only the picture gates skipped, and the result says so.
    p.add_argument("--audio-only", action="store_true",
                   help="a mix (.wav), not a render: run the audio gates only")
    # CF-0351: the plan names `<id>:<n>`, not the shot's entry; the entry -
    # `burned_text`, `shows_entity` - is read from here.
    # CF-0523: the default follows `$FOOTAGE_DIR` the way build_render_plan.py
    # does (one rule, still_share.footage_dirs), so a test's synthetic ids are
    # not looked up in the live pool.
    p.add_argument("--footage-dir",
                   default=str((still_share.footage_dirs()
                                or [FACTORY_ROOT / "shared" / "footage"])[0]),
                   help="where <id>.shots.json live (default %(default)s: "
                        "$FOOTAGE_DIR, else shared/footage)")
    quiet.add_args(p)
    args = p.parse_args()
    # CF-0815: Tech 2026-10-19T0844Z called this with `plan.json <slug>.mp4`
    # and died on UnicodeDecodeError reading the mp4 as the plan. The swapped
    # pair is read the right way round (same files, same checks, same verdict),
    # and a plan that still is not a JSON object is a sentence, exit 2.
    args.video, args.plan, swapped = video_plan_args.ordered(args.video, args.plan)
    if swapped:
        print(f"QC: note: {video_plan_args.swap_note(args.video, args.plan)}",
              file=sys.stderr)
    runlog.annotate(**video_attempt(args.plan))  # CF-0107: slug + the attempt this verdict ends

    try:
        plan = video_plan_args.load_plan(args.plan)
    except video_plan_args.PlanUnreadable as e:
        _no_video_exit(args, str(e), EXIT_NO_VIDEO, error="no_plan")
    # CF-0794: no video to judge is said in a sentence, never a KeyError.
    info = probe_or_exit(args)
    # CF-0098: a plan under <batch>/work/<slug>/ has a ledger; this run ends
    # the attempt render_video.py began and appends its output to that
    # attempt's log. Without an open attempt (qc re-run on a finished video,
    # write_batch_metadata.py's own call) nothing is recorded or logged.
    # CF-0025: never on an --audio-only run. That run is a check on the mix,
    # not a verdict on a render, so it must not end the attempt render_video.py
    # began or write into its log - a mix re-measured on a real batch would
    # otherwise mark that attempt finished without a render having been judged.
    ctx = None if args.audio_only else quiet.Context.for_plan(args.plan)
    if ctx is not None:
        ctx.load()
        if ctx.attempt is None:
            ctx = None
    streams = {s["codec_type"]: s for s in info["streams"] if s.get("codec_type")}

    failures, notes = [], []

    # CF-0329: a safe area narrower than the player's own cut means the left
    # (or right) edge of everything we draw is gone before anybody watches it -
    # which is what happened to every video this factory made before
    # 2026-09-23. The plan is refused here rather than measured: no sampling of
    # pixels can recover a strip the phone never shows.
    for side, have, need in safe_area.survives_the_cut(plan.get("safe_zones")):
        failures.append(
            f"safe zone {side}={have} is inside the player's own cut "
            f"({need} per side on the narrowest screen we render for, "
            f"1:{1 / safe_area.NARROWEST_SCREEN_ASPECT:.2f}) - the graphic "
            f"layer would be clipped off-screen before anyone watches it "
            f"(CF-0329; this plan predates the fix, rebuild it)")

    if "video" not in streams and not args.audio_only:
        failures.append("no video stream")
    if "audio" not in streams:
        failures.append("no audio stream")

    if "video" in streams and not args.audio_only:
        w, h = int(streams["video"]["width"]), int(streams["video"]["height"])
        want = plan["output"]
        if (w, h) != (want["width"], want["height"]):
            failures.append(f"resolution {w}x{h} != requested "
                            f"{want['width']}x{want['height']}")

    # CF-0337: the two defects the user rejected widows-bay for, read off
    # the plan this video was rendered from (the render cannot tell a
    # procedural background from a picture, and the plan can).
    hole_blocks, repeats = [], None
    if not args.audio_only:
        hole_blocks = background_holes(plan)
        if hole_blocks:
            failures.append(
                f"{len(hole_blocks)} block(s) on the procedural background "
                f"(block(s) {hole_blocks}) on a channel that switched the "
                f"per-block assetless rung off - a hole is filled with the "
                f"topic's own footage, never a background; with none left "
                f"the topic needs material (CF-0337, CF-0338)")
        # CF-0348: a supplement source's shot without its entity is not
        # material of this topic, whichever rung placed it (DoD 4).
        # CF-0351: nor is any shot with somebody else's burned-in text; both
        # flags come from the shot's shots.json entry, read by its id.
        report_path = entity_guard.find_report(args.plan)
        off_entity = entity_guard.plan_violations(
            plan, entity_guard.supplements(
                entity_guard.load_report(report_path) if report_path else None),
            shots_of=entity_guard.shot_reader(args.footage_dir))
        for v in off_entity:
            what = ("shot with burned-in text" if "CF-0351" in v["reason"]
                    else "supplement shot without the entity")
            failures.append(
                f"{what}: block {v['block']} ({v['shot']}) - {v['reason']}")
        repeats = repeat_guard.plan_violations(plan)
        for v in repeats["violations"]:
            if v.get("copy"):
                # CF-0461: two uploads of one video - the same shot at any
                # distance, so no window in the line.
                failures.append(
                    f"repeated picture: blocks {v['blocks'][0]} and "
                    f"{v['blocks'][1]} ({v['shots'][0]}, {v['shots'][1]}) "
                    f"show the same footage from two sources "
                    f"({v['similarity']:.3f} >= "
                    f"{repeats['copy_similarity']} frame by frame) "
                    f"{v['gap']:.2f}s apart (a copy, CF-0461)")
                continue
            what = ("the same shot" if v["kind"] == "repeat" else
                    f"a look-alike of the same source "
                    f"({v['similarity']:.3f} >= "
                    f"{repeats['near_duplicate_similarity']})")
            failures.append(
                f"repeated picture: blocks {v['blocks'][0]} and "
                f"{v['blocks'][1]} ({v['shots'][0]}, {v['shots'][1]}) show "
                f"{what} {v['gap']:.2f}s apart (< "
                f"{repeats['min_gap_seconds']:.0f}s, CF-0337)")
        if repeats["unmeasured"]:
            notes.append(f"{repeats['unmeasured']} block clip(s) could not be "
                         f"read - the look-alike rule was not applied to them, "
                         f"only the same-shot rule (CF-0337)")

    v_dur = float(info["format"]["duration"])
    a_dur = plan["audio"]["duration"]
    # CF-0117: the picture is the narration *plus* the end card, and the plan
    # says how long that is (`duration.composition`, written by
    # end_card.apply_to_plan). A plan without a card - built before CF-0117,
    # or without a --channel to read the phrase from - carries no such field
    # and is still checked against the voice-over alone, exactly as before.
    expected = float((plan.get("duration") or {}).get("composition") or a_dur)
    if abs(v_dur - expected) > DURATION_TOLERANCE:
        failures.append(f"picture runs {v_dur:.2f}s but the plan says "
                        f"{expected:.2f}s"
                        + (f" (voiceover {a_dur:.2f}s + end card "
                           f"{expected - a_dur:.2f}s)" if expected > a_dur + 1e-9
                           else " (the voiceover)")
                        + f" ({v_dur - expected:+.2f}s adrift)")

    # CF-0141: the channel's own ending clip is not judged (decision 3), so
    # every run below is measured with that interval cut out of it - a run
    # wholly inside it disappears, one that straddles the seam keeps the part
    # that is in the body of the video, and both facts are said out loud.
    ending = ending_interval(plan)
    blacks = [] if args.audio_only else detect(args.video, "blackdetect=d=0.1:pix_th=0.10")
    long_black, excused_black = [], []
    for run in blacks:
        parts = outside(run, ending)
        if ending is not None and (not parts or parts[0]["duration"] < run["duration"]):
            excused_black.append(run)
        long_black.extend(p for p in parts if p["duration"] > MAX_BLACK_RUN)
    if long_black:
        failures.append(f"{len(long_black)} black stretch(es), longest "
                        f"{max(b['duration'] for b in long_black):.2f}s "
                        f"(> {MAX_BLACK_RUN}s), first at "
                        f"{min(b['start'] for b in long_black):.2f}s")
    for run in excused_black:
        notes.append(f"black of {run['duration']:.2f}s at {run['start']:.2f}s falls in "
                     f"the channel's ending clip ({ending[0]:.2f}-{ending[1]:.2f}s) and "
                     f"was not judged - the clip is finished material the user approved "
                     f"before the factory saw it (CF-0141 decision 3)")

    # CF-0050: a silence long enough to fail is checked a second time against
    # what the plan declared, exactly as a motionless block is checked against
    # the clip it was cut from. A declared cold-frame lead with the picture up
    # under it is not dead air; anything else still is.
    silences = silence_runs(args.video)
    declared_silence = []
    long_silence = []
    excused_silence = []
    with tempfile.TemporaryDirectory() as tmp:
        for k, whole in enumerate(silences):
            parts = outside(whole, ending)
            if ending is not None and (not parts or
                                       parts[0]["duration"] < whole["duration"]):
                excused_silence.append(whole)
            # The body of the video, judged as before. A silence that runs
            # into the ending is judged on the part that is ours - and the
            # mix *is* silent from the clip's first frame by design
            # (build_soundtrack.py fades the bed out before it), so without
            # this every video of the channel would report one long dead-air
            # stretch that is the soundtrack doing exactly what it was told.
            run = parts[0] if parts else None
            if run is None or run["duration"] <= MAX_SILENCE_RUN:
                continue
            fault, reason, luma = silence_verdict(run, plan, args.video, tmp,
                                                  f"sil{k}",
                                                  check_frame=not args.audio_only)
            (long_silence if fault else declared_silence).append(
                {**run, "reason": reason, "frame_luma": luma})
    if long_silence:
        failures.append(
            f"{len(long_silence)} silent stretch(es) over {MAX_SILENCE_RUN}s: " +
            ", ".join(f"{r['duration']:.2f}s at {r['start']:.2f}s - {r['reason']}"
                      for r in long_silence))
    # A relaxation is only acceptable if it is visible - the rule CF-0004 set
    # for the motion gate, applied to this one.
    for r in declared_silence:
        notes.append(f"silence of {r['duration']:.2f}s at {r['start']:.2f}s was "
                     f"not failed - {r['reason']}")
    for r in excused_silence:
        notes.append(f"silence of {r['duration']:.2f}s at {r['start']:.2f}s falls in "
                     f"the channel's ending clip ({ending[0]:.2f}-{ending[1]:.2f}s) and "
                     f"was not judged - the clip carries its own track and the mix is "
                     f"deliberately silent under it (CF-0141 decisions 2 and 3)")

    stills = [] if args.audio_only else frozen_blocks(args.video, plan)
    frozen = [s for s in stills if s["fault"]]
    held = [s for s in stills if not s["fault"]]
    if frozen:
        failures.append(
            "clip blocks rendered as stills: " +
            ", ".join(f"{block_label(s)} (still for {s['still_run']}s from "
                      f"{s['still_run_at']}s, motion {s['motion']}) - {s['reason']}"
                      for s in frozen))
    # CF-0004: a relaxation is only acceptable if it is visible. Every block the
    # motion gate would have failed and no longer does gets said out loud here,
    # and write_batch_metadata.py copies these notes into the batch record.
    for s in held:
        notes.append(f"{block_label(s)}: reads as a still for {s['still_run']}s "
                     f"from {s['still_run_at']}s (motion {s['motion']}) "
                     f"but was not failed - {s['reason']}")

    # CF-0436: a lifted picture is judged on its lifted brightness.
    lifted = [] if args.audio_only else lifted_blocks(args.video, plan)
    for s in lifted:
        where = f"block {s['index']}" + (f" (cut {s['cut']})" if s["cut"] is not None else "")
        if s["luma_render"] is None:
            notes.append(f"{where}: luma_lift x{s['gain']} - the rendered frame "
                         f"could not be read at {s['at']}s (CF-0436)")
        elif s["fault"]:
            notes.append(f"{where}: luma_lift x{s['gain']} left the picture at mean "
                         f"luma {s['luma_render']} on the render (< {MIN_MEAN_LUMA}) - "
                         f"priced as a dark shot (CF-0436)")
        else:
            notes.append(f"{where}: luma_lift x{s['gain']} - mean luma "
                         f"{s['luma_plan_before']} on the source, {s['luma_render']} "
                         f"on the render (CF-0436)")

    # CF-0294: DoD item 7. Same shape as the two gates above it - a
    # measurement on the render, a second look that can excuse it, and every
    # relaxation said out loud.
    subjects = [] if args.audio_only else subject_blocks(args.video, plan)
    offscreen = [s for s in subjects if s["fault"]]
    covered = [s for s in subjects if s.get("covered")]
    turned_away = [s for s in subjects
                   if not s["fault"] and not s.get("covered")]
    if offscreen:
        failures.append(
            "blocks framed on a face with no face in the picture: " +
            ", ".join(f"block {s['index']} at {s['at']}s - {s['reason']}"
                      for s in offscreen))
    for s in turned_away:
        notes.append(f"block {s['index']} at {s['at']}s shows no face although it "
                     f"was framed on one, and was not failed - {s['reason']}")
    for s in covered:
        notes.append(f"block {s['index']} at {s['at']}s was framed on a face and "
                     f"not judged by the subject gate - {s['reason']}")

    # CF-0327: the shot's own inset panel, delivered whole or not at all.
    # A new refusal, so its mode is configuration and not code (CF-0320): until
    # `runlog gate-price --rule video_editor.panel_in_frame` has said what it
    # costs in ready videos, a channel can carry it as a warning by setting
    # `qc_thresholds.panel_in_frame_mode`. Measured either way - a mode that
    # silenced the measurement would make the price unmeasurable, which is the
    # whole failure CF-0320 exists to stop.
    panels = [] if args.audio_only else panel_blocks(args.video, plan)
    panel_mode = inset_panel.mode_of(plan)
    # CF-0894: a sequence cut's cut-off panel is measured, and refuses and
    # costs like a plain block's only once the channel says so
    # (inset_panel.sequence_cuts_judged) - until then it is a row apart and
    # a note, never a new refusal nobody priced.
    panels_cut, panels_cut_seq = split_panel_faults(panels, plan)
    for p in panels_cut_seq:
        notes.append(f"block {p['index']} (cut {p['cut']}) at {p['at']}s delivers "
                     f"{p['visible']:.0%} of the shot's inset panel - measured "
                     f"only, a sequence cut is not judged by the panel gate "
                     f"until {inset_panel.SEQUENCE_KEY} is set (CF-0894) - "
                     f"{p['reason']}")
    if panels_cut and panel_mode == inset_panel.MODE_FAIL:
        failures.append(
            "blocks delivering a cut-off inset panel: " +
            ", ".join(f"block {p['index']} at {p['at']}s - {p['reason']}"
                      for p in panels_cut))
    elif panels_cut and panel_mode != inset_panel.MODE_OFF:
        for p in panels_cut:
            notes.append(f"block {p['index']} at {p['at']}s delivers "
                         f"{p['visible']:.0%} of the shot's inset panel and was not "
                         f"failed - the panel gate runs as `{panel_mode}` on this "
                         f"plan ({inset_panel.MODE_KEY}) - {p['reason']}")

    # CF-0379: a meme up and not one word of ours drawn under it. A new
    # refusal, so its mode is configuration and not code (CF-0320, as CF-0327
    # did for the panel): until `runlog gate-price --rule
    # video_editor.meme_captions` has said what it costs in ready videos, a
    # channel can carry it as a warning through
    # `qc_thresholds.meme_captions_mode`. Measured in every mode - the rows
    # are what the price is replayed from.
    meme_caps = [] if args.audio_only else meme_caption_blocks(args.video, plan)
    meme_caption_mode = meme_captions.mode_of(plan)
    meme_caps_blank = [m for m in meme_caps if m["fault"]]
    if meme_caps_blank and meme_caption_mode == meme_captions.MODE_FAIL:
        failures.append(
            "blocks showing an insert with none of our captions under it: " +
            ", ".join(f"block {m['index']} at {m['at']}s - {m['reason']}"
                      for m in meme_caps_blank))
    elif meme_caps_blank and meme_caption_mode != meme_captions.MODE_OFF:
        for m in meme_caps_blank:
            notes.append(f"block {m['index']} at {m['at']}s shows an insert with "
                         f"nothing of ours in the caption band and was not failed - "
                         f"the meme-caption gate runs as `{meme_caption_mode}` on "
                         f"this plan ({meme_captions.MODE_KEY}) - {m['reason']}")

    if not args.audio_only:
        failures.extend(caption_design_guard())
    # Kept as a recorded number, not a gate: it cannot drop below 4.61:1 by
    # construction, but a future change that erodes it becomes visible here.
    contrast = None if args.audio_only else caption_contrast(args.video, plan)

    peak = peak_db(args.video, until=ending[0] if ending is not None else None)
    if peak is not None and peak > MAX_PEAK_DB:
        # CF-0025: on a mix rather than a render this is not a fault and must
        # not be reported as one. build_soundtrack.py ends on
        # `alimiter=limit=0.88`, and alimiter auto-levels its output back to
        # 0 dBFS by default - so every mix peaks at or just under 0 dB, and the
        # delivered peak is set afterwards by the render's audio stage (the
        # four 2026-09-03T2037Z mp4s came out at -3.0 to -3.9 dB from mixes at
        # 0.0 to -0.9). The clipping gate belongs on the render.
        # (CF-0695: since the loudness pass the mix itself ends at or under
        # its true-peak ceiling, -1.5 dBTP by default, so this note now
        # appears only on a mix built before that pass or by hand.)
        (notes if args.audio_only else failures).append(
            f"audio peaks at {peak:.2f} dB - clipping" if not args.audio_only else
            f"the mix peaks at {peak:.2f} dB, over the {MAX_PEAK_DB} dB clipping "
            f"floor - expected on a mix (alimiter auto-levels to 0 dBFS) and "
            f"not checked here; the render's own peak is what that gate reads")

    # CF-0695: the finished file's loudness, whole - the mix *and* the ending
    # clip's own track, because that is what the viewer hears and what the
    # player's normalisation reads. Judged only when build_soundtrack.py
    # recorded a loudness pass on the plan (`audio.loudness`), the same
    # discipline as the bed: a plan that claims nothing is not accused. The
    # price is a note, not a failure: the pass itself already aims at the
    # target and records any shortfall, so a miss here is a measurement to
    # look at (an ending clip whose own peaks capped its gain, an encode that
    # lifted the true peak), not a defect that should cost a re-render.
    loud_declared = (plan.get("audio") or {}).get("loudness")
    loud = None
    if loud_declared:
        loud = loudness.measure(args.video, media_seconds=media_seconds(args.video))
        verdict = loudness.qc_verdict(
            loud, loud_declared.get("target_lufs", loudness.DEFAULT_TARGET_LUFS),
            loud_declared.get("true_peak_db", loudness.DEFAULT_TRUE_PEAK_DB),
            shortfall_db=loud_declared.get("shortfall_db"))
        if verdict:
            notes.append(verdict)

    # CF-0025: `null` is not an answer. If build_soundtrack.py recorded a bed on
    # the plan (audio.bed) and this gate cannot produce a number for it, that is
    # a failure in itself - the previous version returned None on any narration
    # without a 0.4s pause and then gated on nothing, which is how two of four
    # videos shipped with `bed_rms_db: null` and nobody was told.
    declared = (plan.get("audio") or {}).get("bed")
    # CF-0423: and a plan built for a channel *expects* one. build_render_plan
    # writes the channel (`audio.channel`) and the bed it chose from the
    # channel's rotation (`audio.bed_rotation`, CF-0271); a plan that carries
    # either and no `audio.bed` was rendered without a mix - the bare voice,
    # digital silence between phrases. That is how six example-film videos
    # shipped with no lofi bed at all (2026-09-23T1722Z .. 2026-09-27T1757Z)
    # while this gate said "nothing here claims one was mixed". Absence of the
    # mixer's record on a plan that asked for a bed is not an absence of claim.
    audio = plan.get("audio") or {}
    rotation = audio.get("bed_rotation") or {}
    expected = bool(rotation.get("chosen") or resolve_channel(audio.get("channel")))
    # Only a *declared* bed is judged. build_soundtrack.py records one on every
    # plan it mixes, so every video this pipeline produces is gated; a plan
    # that carries no record - built before CF-0025, or a synthetic fixture
    # with no bed in it at all - is not accused of having lost something it
    # never claimed. Same discipline as the insert pairs: absence is reported,
    # never interpreted. That is also why the number is not measured at all in
    # that case: measuring means decoding the plan's voice, and on a plan that
    # declares no bed there is nothing the answer could be compared against.
    bed = bed_audibility_db(args.video, plan) if (declared or expected) else None
    # CF-0423: whatever the plan says, pauses of dead air are no bed.
    # Measured in the voice-free gaps only (no voice to decode), so a fixture
    # that declares nothing costs one decode and is judged on what it plays.
    silent = _silent_frames(args.video, plan)
    no_bed = bool(silent and silent[0] >= NO_BED_MIN_FRAMES)
    said_silent = (f"{silent[0]} frame(s) of 100 ms of dead air (under "
                   f"{NO_BED_DB:.0f} dB) in {silent[1]:.1f}s of body"
                   if silent else "")
    if not declared and expected:
        chosen = Path(rotation["chosen"]).name if rotation.get("chosen") else None
        failures.append(
            f"no bed in the mix: the plan was built for channel "
            f"{resolve_channel(audio.get('channel')) or '(from its rotation)'}"
            f"{f' and chose {chosen} from its rotation' if chosen else ''}, but no "
            f"mix is recorded on it (audio.bed) - the render carries the bare "
            f"voice"
            + (f" ({said_silent} - the pauses between phrases)" if no_bed else "")
            + " - render_video.py builds the mix itself since CF-0423 (bed not mixed)")
    elif no_bed:
        failures.append(
            f"no bed in the mix: {said_silent} - the pauses between phrases "
            f"are dead air, not a quiet bed (bed not mixed)")
    elif not declared:
        notes.append("no bed is recorded on the plan (audio.bed), so the "
                     "background bed was not measured - nothing here claims "
                     "one was mixed")
    elif bed is None and declared:
        failures.append(
            f"the plan says a bed was mixed (audio.bed: {declared.get('source')} "
            f"at {declared.get('bed_db')} dB) but its level could not be "
            f"measured - no voice-free gap and no readable plan audio.src to "
            f"subtract the narration with, so nothing here checked whether it "
            f"is audible (bed not measured)")
    elif bed is not None and declared and bed["rms_db"] < bed["floor_db"]:
        where = ("voice gaps" if bed["window"] == "word_gaps"
                 else "the ducked body under speech")
        failures.append(
            f"background bed reads {bed['rms_db']:.1f} dB RMS over "
            f"{bed['seconds']:.1f}s of {where}, above {BED_AUDIBLE_BAND_HZ:.0f} Hz "
            f"- below the {bed['floor_db']} dB audibility floor for that window "
            f"(mixed too quiet to hear on a phone speaker)")

    # CF-0068: a sound recorded as placed has to be heard where it was placed,
    # or the record is the one lie the requested/delivered pair exists to
    # prevent - so this is a failure, not a note (inserts/sound.json
    # mix.audibility.on_failure).
    sound_levels = sound_audibility_db(args.video, plan)
    for sl in sound_levels:
        level = sl["rms_db"] if sl["rms_db"] is not None else -math.inf
        if level < MIN_SOUND_RMS_DB:
            failures.append(f"sound {sl['beat_id']} ({sl['asset_id']}) reads "
                            f"{level:.1f} dB RMS over its slot at {sl['at_seconds']:.2f}s"
                            f"{'' if sl['voice_subtracted'] else ' (voice not subtracted)'} - "
                            f"below the {MIN_SOUND_RMS_DB} dB audibility floor "
                            f"(placed but not heard: mix defect)")

    if plan.get("duration", {}).get("deviation"):
        notes.append(f"duration {a_dur:.1f}s is outside the requested target "
                     f"{plan['duration']['target'][0]:.0f}-"
                     f"{plan['duration']['target'][1]:.0f}s "
                     f"({plan['duration']['deviation']:+.1f}s) - the script is "
                     f"too short, which is upstream's call, not a render fault")
    notes.extend(plan.get("notes", []))

    result = {
        "video": args.video,
        # CF-0025: never absent, so a reader of a report can tell a narrower
        # run from a full one without inferring it from what is missing.
        "audio_only": bool(args.audio_only),
        "passed": not failures,
        "failures": failures,
        "notes": notes,
        "measured": {
            # CF-0337
            "background_hole_blocks": hole_blocks,
            "repeated_pictures": (repeats or {}).get("violations", []),
            "duration": round(v_dur, 3),
            "audio_duration": a_dur,
            "peak_db": peak,
            # CF-0695: EBU R128 of the whole finished file, or None when the
            # plan records no loudness pass.
            "loudness": loud,
            # CF-0025: the level, and - always - the window it was measured
            # in, so a number that looks low can be read against the right
            # floor without re-deriving which fallback ran.
            "bed_rms_db": (round(bed["rms_db"], 1)
                           if bed and math.isfinite(bed["rms_db"]) else None),
            "bed_rms_window": bed["window"] if bed else None,
            "bed_rms_floor_db": bed["floor_db"] if bed else None,
            "bed_rms_seconds": bed["seconds"] if bed else None,
            "bed_voice_subtracted": bed["voice_subtracted"] if bed else None,
            "bed_declared": bool(declared),
            # CF-0423: the plan was built for a channel, so a bed was due.
            "bed_expected": expected,
            "bed_missing": bool((expected and not declared) or no_bed),
            "bed_silent_frames": silent[0] if silent else None,
            # CF-0068: one row per placed sound, [] when the plan placed none.
            "sound_rms_db": sound_levels,
            "frozen_clip_blocks": [s["index"] for s in frozen],
            # CF-0436: every luma_lift picture measured on the render.
            "lifted_blocks": lifted,
            # CF-0004: blocks that read as stills and were accepted anyway,
            # with the source measurement that excused each one. Empty on a
            # run where nothing was relaxed.
            "held_source_blocks": [
                {"index": s["index"], "side": s.get("side"),
                 "motion": s["motion"],
                 # CF-0249: an excused still is excused for a length of time,
                 # and the batch record has to carry it - "held for 2.0s" and
                 # "held for 6.0s" are not the same relaxation.
                 "still_run": s["still_run"], "still_run_at": s["still_run_at"],
                 "source_motion": s["source_motion"], "reason": s["reason"]}
                for s in held],
            # CF-0294: one row per block framed on a face that delivered
            # none, `fault` telling the framing's doing from the footage's,
            # with the coverage the second look measured. Empty on a render
            # where every such block showed a face - the ordinary case.
            "subject_offscreen_blocks": offscreen,
            "subject_turned_away_blocks": turned_away,
            # CF-0363: blocks an opaque insert covers whole - not judged, and
            # said so rather than dropped.
            "subject_covered_blocks": covered,
            # CF-0327: one row per block whose shot carries an inset panel,
            # with the share of it the delivered window keeps and the verdict
            # (`whole` / `absent` / `cut`). Recorded on every render, in every
            # mode, because `runlog gate-price` prices this rule by replaying
            # these rows over the frozen batches - a measurement only written
            # when the gate fires could never be priced (CF-0320).
            # CF-0379: one row per block whose insert leaves our captions on,
            # with the caption-white share measured in the band the renderer
            # raised for it and the verdict (`ink` / `blank`). Written on
            # every render in every mode, for the same reason the panel rows
            # are: `runlog gate-price --rule video_editor.meme_captions`
            # prices this rule by replaying these rows over the frozen
            # batches (CF-0320).
            "meme_caption_blocks": meme_caps,
            "meme_caption_blank_blocks": meme_caps_blank,
            "meme_caption_gate_mode": meme_caption_mode,
            "panel_blocks": panels,
            "panel_cut_blocks": panels_cut,
            # CF-0894: cut-off panels on sequence cuts while they are only
            # measured - what their price will be replayed from.
            "panel_cut_sequence_blocks": panels_cut_seq,
            "panel_gate_mode": panel_mode,
            "caption_contrast": {"ratio": round(contrast[0], 2), "at": contrast[1],
                                 "band_luma": contrast[2]} if contrast else None,
            "black_runs": len(blacks),
            "silence_runs": len(silences),
            # CF-0050: silences long enough to fail that the plan accounted
            # for, with the frame measurement that excused each one. Empty on
            # a run where nothing was relaxed.
            "declared_silence": declared_silence,
        },
    }

    # CF-0434: the QC stage of the video's score log - this verdict's real
    # penalties (score_log.qc_findings), and the remainder after the plan,
    # the render and this. Under N the video goes no further: the refusal is
    # written beside the plan, no degradation is suggested and the exit is 4.
    # The hard list is not this - a hard finding makes the tier F in the log,
    # and the failure that carries it refuses exactly as it always did. Never
    # on --audio-only: a mix is not the video.
    stopped = None
    if not args.audio_only:
        block = score_log.record(args.plan, score_log.STAGE_QC,
                                 score_log.qc_findings(result, plan))
        stopped = score_log.check(args.plan, block, score_log.script_id_for(args.plan),
                                  score_log.STAGE_QC)
        result["score"] = {k: v for k, v in block.items() if k != "line"}
        result["score_line"] = block.get("line")
        result["score_stop"] = stopped

    rc = EXIT_SCORE_F if stopped else (0 if result["passed"] else 1)
    text_report = [f"{'PASS' if result['passed'] else 'FAIL'}  {Path(args.video).name}"]
    text_report += [f"  FAIL: {f}" for f in failures]
    text_report += [f"  note: {n}" for n in notes]
    if result.get("score_line"):
        text_report.append("  " + (score_log.stop_line({**result["score"], "line": result["score_line"]},
                                                       score_log.STAGE_QC, stopped)
                                   if stopped else f"score: {result['score_line']}"))

    capped = False
    if ctx is not None:
        quiet.append_text(ctx.log, "\n".join(text_report) + "\n" +
                          json.dumps(result, indent=2) + "\n",
                          step="qc_render", attempt=ctx.attempt["n"], slug=ctx.slug)
        if result["passed"]:
            ctx.end(attempts.RESULT_OK)
        else:
            # CF-0415: the degradation this verdict suggests, recorded on
            # the attempt - the next render that applies exactly it (and
            # nothing else) is a `qc_degrade`, not an attempt.
            # CF-0434: a video stopped under N is not rebuilt - no hint.
            _, capped = ctx.end(attempts.RESULT_QC_FAILED,
                                detail="; ".join(failures),
                                failed_gates=failed_gates(failures),
                                qc_hint=([] if stopped else
                                         attempts.qc_hint_tags(s["index"] for s in frozen)),
                                qc_frozen=([] if stopped else
                                           attempts.qc_frozen_records(frozen)))
        result["attempt"] = {"n": ctx.attempt["n"], "cap": ctx.ledger["attempt_cap"],
                             "kind": attempts.kind_of(ctx.attempt),
                             "qc_hint": ctx.attempt.get("qc_hint") or [],
                             "qc_degrades_used": len(attempts.qc_degrades(ctx.ledger)),
                             "qc_degrade_cap": attempts.qc_degrade_cap(ctx.ledger),
                             "log": str(ctx.log),
                             "attempts_exhausted": attempts.exhausted(ctx.ledger)}

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    elif not args.summary or ctx is None:
        for line in text_report:
            print(line)
    else:
        quiet.summary(qc_summary(result, ctx, rc, frozen), ctx.log)
    if capped and not args.json:
        print(ctx.needs_you_line())
    sys.exit(rc)


# CF-0098: the short names an attempt's `failed_gates` carries, so the next
# attempt's reason can say `qc_failed:frozen` instead of a paragraph.
GATE_KEYWORDS = (
    ("no video stream", "stream"), ("no audio stream", "stream"),
    ("resolution", "resolution"), ("adrift", "duration"),
    ("black stretch", "black"), ("silent stretch", "silence"),
    ("rendered as stills", "frozen"), ("clipping", "clipping"),
    ("framed on a face", "subject"),   # CF-0294
    ("inset panel", "panel"),          # CF-0327
    # CF-0351: before "caption" - its reason names a caption too.
    ("burned-in text", "burned_text"),
    ("background bed", "bed"), ("a bed was mixed", "bed"),
    ("sound ", "sound"),
    # CF-0379: before the general "caption" - a meme with no line under it is
    # its own rule (video_editor.meme_captions) and is priced as one.
    ("none of our captions", "meme_caption"),
    ("caption", "caption"),
    ("procedural background", "background"),   # CF-0337
    ("repeated picture", "repeat"),            # CF-0337
    ("without the entity", "entity"),          # CF-0348
)


def background_holes(plan):
    """CF-0337: the blocks painted as the procedural background on a plan
    whose channel switched the per-block assetless rung off. The flat
    `typographic` style is a whole-video choice (CF-0015) and never counts;
    a plan that recorded no rung verdict is read as the rung off, which is
    what an unconfigured channel gets (assetless_rung.DEFAULT_ENABLED)."""
    if plan.get("style") == "typographic":
        return []
    rung = plan.get("assetless_rung") or {}
    if rung.get("rung_enabled") or rung.get("style_typographic"):
        return []
    # A block whose frame a library insert took whole (CF-0138) shows a
    # picture, whatever is painted under it.
    return [i for i, b in enumerate(plan.get("blocks") or [])
            if isinstance(b.get("asset"), dict)
            and b["asset"].get("kind") == "procedural"
            and not assetless_rung.filled_by_insert(b)]


def failure_gate(failure):
    """The short gate name of one failure line (GATE_KEYWORDS), `other` when
    no keyword matches. CF-0416: qc_cosmetic.rule_of() reads it per line."""
    low = str(failure).lower()
    return next((g for key, g in GATE_KEYWORDS if key in low), "other")


def failed_gates(failures):
    gates = []
    for f in failures:
        name = failure_gate(f)
        if name not in gates:
            gates.append(name)
    return gates


def qc_summary(result, ctx, rc, frozen):
    """The <= 20 lines the operator reads instead of the report: verdict,
    return code, attempt number, every failed block with its score, the
    count of notes (the notes themselves are in the log)."""
    label = quiet.attempt_label(ctx.attempt, ctx.ledger)
    lines = [f"qc {'PASS' if result['passed'] else 'FAIL'}  rc={rc}  {label}  "
             f"{Path(result['video']).name}"]
    if frozen:
        lines.append("  frozen blocks (index: motion): " +
                     ", ".join(f"{block_label(s)}: {s['motion']}" for s in frozen))
    for f in result["failures"]:
        lines.append(f"  FAIL: {f}")
    hint = (result.get("attempt") or {}).get("qc_hint") or []
    if hint:
        # CF-0415: the rebuild that applies exactly this is a qc_degrade and
        # spends the degrade cap, not an attempt.
        att = result["attempt"]
        lines.append("  qc hint: " + " ".join(f"--degrade-block {t}:..." for t in hint)
                     + f"  (qc degrade, {att['qc_degrades_used']}/{att['qc_degrade_cap']} "
                     "used - not an attempt)")
    if result["notes"]:
        lines.append(f"  notes: {len(result['notes'])} (in the log)")
    if result["measured"].get("held_source_blocks"):
        lines.append(f"  held source blocks (not failures): "
                     + ", ".join(str(h["index"]) for h in result["measured"]["held_source_blocks"]))
    # CF-0434: the score after this render, or the stop.
    if result.get("score_stop"):
        lines.append("  " + score_log.stop_line(
            {**result["score"], "line": result["score_line"]}, score_log.STAGE_QC,
            result["score_stop"]))
    elif result.get("score_line"):
        lines.append(f"  score: {result['score_line']}")
    return lines


@video_script("video-editor", "qc", name="qc_render.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

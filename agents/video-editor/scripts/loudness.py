#!/usr/bin/env python3
"""CF-0695: every finished video lands at the same loudness - -14 LUFS
integrated, true peak no higher than -1 dBTP - by a static gain.

Why at all. Until this task nothing in the pipeline measured loudness: a Tech
voice-over-bed sample came out at -22.5 LUFS, a full preview render at -17.2
LUFS with its true peak at +0.02 dBFS. YouTube turns a loud upload down to its
reference and never turns a quiet one up, so a quiet Short simply plays
quieter than the one before it in the feed. The user's answer to Q35
(2026-10-12): -14 LUFS on every channel.

Why a static gain and not `loudnorm`. The preview was normalised once with
ffmpeg's dynamic loudnorm, and it reached -14.1 LUFS by compressing the
loudness range from 11.9 LU to 5.6 LU - it rode the voice up and down. A
static gain moves the whole mix by one number, so everything the mix decided
(the bed ducked under the voice, the accents, the ending's own level) keeps
its proportions. The only thing beside the gain is a true-peak-safe limiter
(4x oversampled), and it is allowed to take at most MAX_LIMITER_GR_DB off the
peaks: a mix that would need more than that to reach the target is brought as
close as the cap allows and the rest is recorded as `shortfall_db`, never
squashed to get there.

Two places, one target. The soundtrack is mixed by build_soundtrack.py; the
channel's ending clip carries its own track and is played by the render
(render/src/components/EndCard.jsx, CF-0141 decision 2) over silence in our
mix. The final file is both, so both are levelled to the same target: the mix
here by gain + limiter, the ending by a static `volume` the render applies
(`audio.loudness.ending.volume`), capped so the clip's own true peak stays
under the ceiling - there is no limiter in the render to lean on, so that cap
is hard, and a shortfall there is recorded too. qc_render.py then measures
the finished file as a whole, which is what the viewer hears.

Stereo at unity. The render used to play the mono mix into its stereo file
at -3 dB per channel (Remotion/ffmpeg's equal-power up-mix): the same
integrated loudness, but every peak 3 dB under the ceiling it was allowed -
measured on the 2026-10-12 demo, render -4.4 vs mix -1.5 dBTP. So the master
pass writes the mix as **dual-mono stereo**, the voice at 0 dB in both
channels: the render plays a stereo file as it is, and the mix's true peak
is the render's. The premaster (mono) is measured with ebur128 `dualmono`,
i.e. as it will sound once duplicated into both channels.

The voice stem. A TTS voice arrives with a 20 dB peak-to-loudness ratio
(Kokoro on the demo: -23.0 LUFS, peaks -2.4 dBFS), and a static gain alone
cannot take that to -14 under -1 dBTP. compress_voice() runs every channel's
voice through a gentle compressor before the mix (VOICE_RATIO:1, attack
VOICE_ATTACK_MS, release VOICE_RELEASE_MS, threshold VOICE_THRESHOLD_REL_LU
over the voice's own integrated loudness, so it adapts to each video) and
gives back the loudness it took as makeup, so the voice sits against the bed
exactly where the mix put it before. Measured on the demo voice the
compressor evens the envelope but hardly moves the peak-to-loudness ratio
(20.6 -> 19.3 dB): the peaks are sub-millisecond waveform crest, which only a
limiter holds. That is the master limiter's job, inside its cap.

The key: `video_editor.loudness` in the channel config, an object
{target_lufs, true_peak_db}; either may be left out, the whole block too, and
the default is DEFAULT_TARGET_LUFS / DEFAULT_TRUE_PEAK_DB. A value present and
out of range refuses by name (LoudnessConfigError), the ambient bed_db
doctrine: a typo here moves every video of the channel by however many dB the
typo says.
"""
import math
import re
from pathlib import Path

from common import ffmpeg

CHANNEL_LOUDNESS_KEY = "video_editor.loudness"
TARGET_LUFS_FIELD = "target_lufs"
TRUE_PEAK_FIELD = "true_peak_db"

DEFAULT_TARGET_LUFS = -14.0
DEFAULT_TRUE_PEAK_DB = -1.0
# What a value may be - the range where it still means a delivery loudness.
TARGET_LUFS_RANGE = (-30.0, -5.0)
TRUE_PEAK_RANGE = (-9.0, 0.0)

SOURCE_CONFIG = "config"
SOURCE_DEFAULT = "default"

# The most the limiter may take off the peaks to reach the target. Past this
# the mix is no longer "the mix, louder" but a different, squashed mix.
MAX_LIMITER_GR_DB = 4.0
# The limiter's own ceiling sits this far under the delivered ceiling: the
# render re-encodes the mix to AAC, and a lossy encode lifts true peaks by a
# few tenths of a dB. Half a dB is the usual margin.
ENCODE_MARGIN_DB = 0.5
# CF-0695: the voice stem's compressor (compress_voice()). Gentle by design:
# 3:1 over a threshold 6 dB above the voice's own integrated loudness, peak
# detection, 5 ms attack, 200 ms release, a soft knee.
VOICE_RATIO = 3.0
VOICE_ATTACK_MS = 5.0
VOICE_RELEASE_MS = 200.0
VOICE_KNEE = 2.0
VOICE_THRESHOLD_REL_LU = 6.0
# a 10 ms window counts as "compressed" when its level came down by more
# than this (the voice-stem statistics on the plan)
VOICE_GR_COUNTS_DB = 1.0
VOICE_WINDOW_S = 0.010
VOICED_FLOOR_DB = -45.0
# How close the master pass has to land before it stops correcting. The
# limiter shaves a little loudness off the peaks it touches, so the first
# pass can land a fraction under; one more pass with the difference added
# closes it.
LAND_TOLERANCE_LU = 0.3
MAX_PASSES = 3
# qc_render.py: a finished file further than this from its target is flagged.
QC_TOLERANCE_LU = 1.0
# The rate the limiter runs at: 4x the mix's, so the peaks it holds are the
# inter-sample (true) peaks a meter at 4x oversampling reads, not just the
# sample values.
OVERSAMPLE = 4


class LoudnessConfigError(ValueError):
    """`video_editor.loudness` is present and is not a usable target."""


def settings(channel_cfg):
    """(target_lufs, true_peak_db, source) for a channel config (or None).

    `source` is `config` when the channel names either number, else
    `default`."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    block = ve.get("loudness") if isinstance(ve, dict) else None
    if block is None:
        return DEFAULT_TARGET_LUFS, DEFAULT_TRUE_PEAK_DB, SOURCE_DEFAULT
    if not isinstance(block, dict):
        raise LoudnessConfigError(
            f"{CHANNEL_LOUDNESS_KEY} must be an object "
            f"{{{TARGET_LUFS_FIELD}, {TRUE_PEAK_FIELD}}}, got {block!r}")
    out = []
    for field, default, (lo, hi) in ((TARGET_LUFS_FIELD, DEFAULT_TARGET_LUFS, TARGET_LUFS_RANGE),
                                     (TRUE_PEAK_FIELD, DEFAULT_TRUE_PEAK_DB, TRUE_PEAK_RANGE)):
        value = block.get(field)
        if value is None:
            out.append(default)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not (lo <= value <= hi):
            raise LoudnessConfigError(
                f"{CHANNEL_LOUDNESS_KEY}.{field} must be a number in "
                f"[{lo}, {hi}], got {value!r}")
        out.append(float(value))
    source = SOURCE_CONFIG if any(block.get(f) is not None
                                  for f in (TARGET_LUFS_FIELD, TRUE_PEAK_FIELD)) \
        else SOURCE_DEFAULT
    return out[0], out[1], source


_SUMMARY = {
    "integrated_lufs": r"I:\s*(-?\d+(?:\.\d+)?|-inf)\s*LUFS",
    "lra_lu": r"LRA:\s*(-?\d+(?:\.\d+)?)\s*LU\b",
    "true_peak_db": r"Peak:\s*(-?\d+(?:\.\d+)?|-inf)\s*dBFS",
}


def measure(path, start=None, until=None, media_seconds=None, dualmono=False):
    """EBU R128 of `path`'s audio (optionally only [start, until)):
    {integrated_lufs, true_peak_db, lra_lu}, each None when ffmpeg did not
    report it, -inf (as None) on silence. Returns None when the file has no
    audio at all or ffmpeg failed."""
    args = []
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path), "-vn"]
    if until is not None:
        length = until - (start or 0.0)
        if length <= 0:
            return None
        args += ["-t", f"{length:.3f}"]
    out = ffmpeg(*args, "-af", "ebur128=peak=true" + (":dualmono=true" if dualmono else ""),
                 "-f", "null", "-",
                 log_level="info", media_seconds=media_seconds)
    if out.returncode != 0:
        return None
    text = out.stderr
    cut = text.rfind("Summary:")
    if cut < 0:
        return None
    text = text[cut:]
    got = {}
    for key, rx in _SUMMARY.items():
        m = re.search(rx, text)
        if not m or m.group(1) == "-inf":
            got[key] = None
        else:
            got[key] = float(m.group(1))
    # ffmpeg reports an all-silent integrated loudness as -70 (the absolute
    # gate) - there is nothing to level.
    if got["integrated_lufs"] is not None and got["integrated_lufs"] <= -69.9:
        got["integrated_lufs"] = None
    return got


def ceiling_db(true_peak_db):
    """The true-peak ceiling a levelled file has to hold: the delivered
    ceiling less the encode margin."""
    return true_peak_db - ENCODE_MARGIN_DB


def plan_gain(before, target_lufs, true_peak_db, limiter=True):
    """The static gain for a measured `before`, and what it costs.

    {gain_db, wanted_db, limiter_gr_db, shortfall_db, ceiling_db}. With
    `limiter` the peaks may be held down by up to MAX_LIMITER_GR_DB; without
    one (the ending clip, played by the render) the gain is capped where the
    clip's own true peak meets the ceiling."""
    ceiling = ceiling_db(true_peak_db)
    wanted = target_lufs - before["integrated_lufs"]
    tp = before.get("true_peak_db")
    if tp is None:
        tp = -math.inf
    allowance = MAX_LIMITER_GR_DB if limiter else 0.0
    cap = ceiling - tp + allowance
    gain = min(wanted, cap)
    gr = max(0.0, tp + gain - ceiling) if limiter else 0.0
    return {"gain_db": round(gain, 2), "wanted_db": round(wanted, 2),
            "limiter_gr_db": round(gr, 2),
            "shortfall_db": round(max(0.0, wanted - gain), 2),
            "ceiling_db": round(ceiling, 2)}


def _master_graph(gain_db, ceiling_db, sr):
    limit = 10 ** (ceiling_db / 20.0)
    return (f"volume={gain_db:.2f}dB,aresample={sr * OVERSAMPLE},"
            f"alimiter=limit={limit:.5f}:level=0:latency=1:attack=5:release=60,"
            f"aresample={sr},pan=stereo|c0=c0|c1=c0")


def master(premaster, output, target_lufs, true_peak_db, sr, seconds=None):
    """Bring the mono `premaster` to the target by static gain + the capped
    limiter, write `output` as dual-mono stereo (`sr`, 16-bit - the voice at
    0 dB in both channels, which is how the render plays it), and return:

    {target_lufs, true_peak_db, before, after, gain_db, wanted_db,
     limiter_gr_db, shortfall_db, ceiling_db, passes}

    `before`/`after` are measure() dicts. A premaster with nothing to measure
    (silence) is copied through at unity and says so (`gain_db` 0, `after`
    equal to `before`). Raises RuntimeError when ffmpeg fails."""
    before = measure(premaster, media_seconds=seconds, dualmono=True)
    if before is None or before["integrated_lufs"] is None:
        out = ffmpeg("-i", str(premaster), "-af", "pan=stereo|c0=c0|c1=c0",
                     "-ar", str(sr), "-ac", "2",
                     "-c:a", "pcm_s16le", str(output), media_seconds=seconds)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[-300:])
        return {"target_lufs": target_lufs, "true_peak_db": true_peak_db,
                "before": before, "after": before, "gain_db": 0.0,
                "wanted_db": None, "limiter_gr_db": 0.0, "shortfall_db": None,
                "ceiling_db": round(ceiling_db(true_peak_db), 2),
                "passes": 0, "unmeasurable": True}
    plan = plan_gain(before, target_lufs, true_peak_db)
    gain = plan["gain_db"]
    tp = before.get("true_peak_db")
    # The most gain the limiter cap allows, whatever a correction asks for.
    max_gain = plan["ceiling_db"] - (tp if tp is not None else -math.inf) \
        + MAX_LIMITER_GR_DB
    after, passes = None, 0
    for passes in range(1, MAX_PASSES + 1):
        out = ffmpeg("-i", str(premaster), "-af",
                     _master_graph(gain, plan["ceiling_db"], sr),
                     "-ar", str(sr), "-ac", "2", "-c:a", "pcm_s16le", str(output),
                     media_seconds=seconds)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[-300:])
        after = measure(output, media_seconds=seconds)
        if after is None or after["integrated_lufs"] is None:
            break
        miss = target_lufs - after["integrated_lufs"]
        if abs(miss) <= LAND_TOLERANCE_LU:
            break
        # Never past the cap computed from the premaster: a correction that
        # would push the limiter beyond MAX_LIMITER_GR_DB is not taken.
        nxt = round(min(gain + miss, max_gain), 2)
        if abs(nxt - gain) < 0.05:
            break
        gain = nxt
    gr = max(0.0, (tp if tp is not None else -math.inf) + gain - plan["ceiling_db"])
    shortfall = (round(target_lufs - after["integrated_lufs"], 2)
                 if after and after["integrated_lufs"] is not None else None)
    return {"target_lufs": target_lufs, "true_peak_db": true_peak_db,
            "before": before, "after": after, "gain_db": round(gain, 2),
            "wanted_db": plan["wanted_db"], "limiter_gr_db": round(gr, 2),
            "limiter_cap_db": MAX_LIMITER_GR_DB,
            # The part of the target the cap would not reach. Recorded from the
            # plan (what the cap withheld); `after` says where it landed.
            "shortfall_db": plan["shortfall_db"],
            "landed_off_by_lu": shortfall,
            "ceiling_db": plan["ceiling_db"], "channels": "dual-mono stereo",
            "passes": passes}


def ending_level(path, target_lufs, true_peak_db, seconds=None):
    """The static volume the render plays the channel's ending clip at.

    {path, before, gain_db, wanted_db, shortfall_db, ceiling_db, volume} -
    `volume` is the linear factor EndCard.jsx hands Remotion. No limiter is
    available there, so the gain is capped where the clip's true peak meets
    the ceiling. A clip whose audio cannot be measured plays at 1.0 and the
    record says why (`unmeasured`)."""
    before = measure(path, media_seconds=seconds)
    if before is None or before["integrated_lufs"] is None:
        return {"path": str(path), "before": before, "gain_db": 0.0,
                "volume": 1.0, "unmeasured": "no measurable audio in the clip"}
    plan = plan_gain(before, target_lufs, true_peak_db, limiter=False)
    return {"path": str(path), "before": before, "gain_db": plan["gain_db"],
            "wanted_db": plan["wanted_db"], "shortfall_db": plan["shortfall_db"],
            "ceiling_db": plan["ceiling_db"],
            "volume": round(10 ** (plan["gain_db"] / 20.0), 4)}


def qc_verdict(measured, target_lufs, true_peak_db, shortfall_db=None):
    """The QC sentence for a finished file's measure(), or None when it is on
    target. A miss beyond QC_TOLERANCE_LU or a true peak over the ceiling."""
    if not measured or measured.get("integrated_lufs") is None:
        return (f"loudness could not be measured on the finished file "
                f"(target {target_lufs} LUFS) - nothing checked it")
    i, tp = measured["integrated_lufs"], measured.get("true_peak_db")
    problems = []
    if abs(i - target_lufs) > QC_TOLERANCE_LU:
        problems.append(f"integrated {i:.1f} LUFS, {i - target_lufs:+.1f} LU off the "
                        f"{target_lufs:.0f} LUFS target (tolerance "
                        f"+-{QC_TOLERANCE_LU:.0f} LU)")
    if tp is not None and tp > true_peak_db:
        problems.append(f"true peak {tp:+.1f} dBTP over the {true_peak_db:.0f} dBTP "
                        f"ceiling")
    if not problems:
        return None
    why = (f" - the mix recorded a {shortfall_db:.1f} dB shortfall (the limiter "
           f"cap of {MAX_LIMITER_GR_DB:.0f} dB was reached rather than squash the "
           f"mix)" if shortfall_db else "")
    return "loudness off target: " + "; ".join(problems) + why


def _read_mono(path, sr):
    import numpy as np
    out = ffmpeg("-i", str(path), "-vn", "-f", "f32le", "-ac", "1", "-ar", str(sr), "-",
                 text=False)
    if out.returncode != 0:
        return None
    return np.frombuffer(out.stdout, dtype="<f4")


def voice_gr_stats(raw, compressed, makeup_db, sr):
    """How hard the compressor worked, from the stem before and after it:
    per VOICE_WINDOW_S window of voice (raw level over VOICED_FLOOR_DB), the
    gain reduction is raw level - (compressed level - makeup). Returns
    {compressed_share, mean_gr_db, max_gr_db, p95_gr_db, windows}."""
    import numpy as np
    w = max(1, int(VOICE_WINDOW_S * sr))
    n = min(raw.size, compressed.size) // w
    if n == 0:
        return None
    a = np.sqrt((raw[:n * w].reshape(n, w).astype(np.float64) ** 2).mean(1) + 1e-12)
    b = np.sqrt((compressed[:n * w].reshape(n, w).astype(np.float64) ** 2).mean(1) + 1e-12)
    level = 20 * np.log10(a)
    voiced = level > VOICED_FLOOR_DB
    if not voiced.any():
        return None
    gr = (level - (20 * np.log10(b) - makeup_db))[voiced]
    return {"compressed_share": round(float((gr > VOICE_GR_COUNTS_DB).mean()), 3),
            "mean_gr_db": round(float(gr.mean()), 2),
            "p95_gr_db": round(float(np.percentile(gr, 95)), 2),
            "max_gr_db": round(float(gr.max()), 2),
            "windows": int(voiced.sum())}


def compress_voice(voice, output, sr, seconds=None):
    """The voice stem, gently compressed, written to `output` (mono float).

    The threshold is VOICE_THRESHOLD_REL_LU over the voice's own integrated
    loudness, so a quiet and a loud voice are worked alike; the makeup gives
    back exactly the integrated loudness the compressor took (measured, not
    guessed), so the voice keeps its place against the bed. Returns the
    record: {params, before, after, makeup_db, plr_before_db, plr_after_db,
    gr: voice_gr_stats(), path}. A voice with nothing measurable is copied
    through unprocessed and says so (`skipped`)."""
    before = measure(voice, media_seconds=seconds)
    if before is None or before["integrated_lufs"] is None:
        out = ffmpeg("-i", str(voice), "-ac", "1", "-ar", str(sr), "-c:a", "pcm_f32le",
                     str(output), media_seconds=seconds)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[-300:])
        return {"path": str(output), "before": before, "skipped": "no measurable voice",
                "makeup_db": 0.0}
    threshold_db = before["integrated_lufs"] + VOICE_THRESHOLD_REL_LU
    thr = min(1.0, max(0.000976563, 10 ** (threshold_db / 20.0)))
    comp = (f"acompressor=threshold={thr:.6f}:ratio={VOICE_RATIO}:"
            f"attack={VOICE_ATTACK_MS}:release={VOICE_RELEASE_MS}:knee={VOICE_KNEE}:"
            f"detection=peak:makeup=1")
    raw_path = Path(output).with_name(Path(output).stem + "_nomakeup.wav")
    out = ffmpeg("-i", str(voice), "-af", comp, "-ac", "1", "-ar", str(sr),
                 "-c:a", "pcm_f32le", str(raw_path), media_seconds=seconds)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-300:])
    mid = measure(raw_path, media_seconds=seconds)
    makeup = 0.0
    if mid and mid["integrated_lufs"] is not None:
        makeup = round(before["integrated_lufs"] - mid["integrated_lufs"], 2)
    out = ffmpeg("-i", str(raw_path), "-af", f"volume={makeup:.2f}dB", "-c:a", "pcm_f32le",
                 str(output), media_seconds=seconds)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-300:])
    after = measure(output, media_seconds=seconds)
    gr = None
    raw_x, comp_x = _read_mono(voice, sr), _read_mono(output, sr)
    if raw_x is not None and comp_x is not None:
        gr = voice_gr_stats(raw_x, comp_x, makeup, sr)
    try:
        raw_path.unlink()
    except OSError:
        pass

    def plr(m):
        if not m or m.get("integrated_lufs") is None or m.get("true_peak_db") is None:
            return None
        return round(m["true_peak_db"] - m["integrated_lufs"], 2)
    return {"path": str(output),
            "params": {"ratio": VOICE_RATIO, "attack_ms": VOICE_ATTACK_MS,
                       "release_ms": VOICE_RELEASE_MS, "knee": VOICE_KNEE,
                       "detection": "peak",
                       "threshold_db": round(threshold_db, 2),
                       "threshold_rel_lu": VOICE_THRESHOLD_REL_LU},
            "before": before, "after": after, "makeup_db": makeup,
            "plr_before_db": plr(before), "plr_after_db": plr(after), "gr": gr}

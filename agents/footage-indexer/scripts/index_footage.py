#!/usr/bin/env python3
"""Break a footage file into shots and index them for retrieval.

Nothing in this pipeline knew what its footage contained. Crops knew where a
subject sat in frame; nothing knew whether the frame held a rink or a kitchen.
Shots were assigned to lines of narration by eye, which is why "a real lake
house" landed over a close-up on the ice.

This produces, once per source and reusable by every video that draws on it:
  - shot boundaries with timestamps
  - a CLIP embedding per shot, so an arbitrary phrase can be matched against it
  - a numbered contact sheet, so a human or an LLM can write a plain-language
    description for each shot - embeddings are for matching, descriptions are
    for whoever has to write to the footage

Usage: index_footage.py <video> [--threshold 0.25] [--max-shots 60]
Writes <video>.shots.json and <video>.contact.jpg beside the source.
"""
import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = "/usr/local/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE = "/usr/local/opt/ffmpeg-full/bin/ffprobe"
MODEL = "openai/clip-vit-base-patch32"
MIN_SHOT_SECONDS = 0.8

# CF-0082: truncating to the first `max_shots` shots (the old behaviour)
# drops everything after the cap, and for a source with more cuts than the
# cap allows that is reliably the source's *tail* - exactly where a release-
# date card, a distributor logo card or a rating card lives. Measured on a
# real batch: BROAzK8oP9U/_LE1L4Huyys lost the UK "ONLY IN CINEMAS JANUARY"
# end card past 108.8s because the first 60 detected shots didn't even reach
# two minutes, and 47P9fKmWbEs (45 minutes) was indexed only to 188s.
#
# This costs nothing extra: shot_boundaries() already scans the *entire*
# file to find every cut regardless of max_shots - the cap only decides
# which already-detected shots go on to the expensive per-shot work (frame
# extraction, CLIP embedding, usability/caption/card-text probes). Reserving
# a slice of that same budget for the last few shots - instead of raising
# the cap, which would raise that per-shot cost project-wide (CF-0052/
# CF-0080-class expense) - fixes the loss for free.
#
# A fixed count, not a fraction of the budget: end cards cluster in the
# final few shots no matter how long the source or how large the cap is - a
# 20% reserve on --max-shots 200 would burn 40 shots on the tail for no
# reason. Halved for small caps (below 2x this) so the head is never
# starved down to nothing.
TAIL_SHOTS_RESERVED = 8

# Usability (resolution/subject/black-fraction/luma) and caption-band presence
# are properties of the shot itself, not of whichever anchor later tries it
# (CF-0029) - measured once here instead of recomputed from scratch by every
# candidate resolve_anchors.py tries against every anchor. Video Editor owns
# both the Vision worker (macOS Vision needs pyobjc, which this venv does not
# have) and the qc_asset.py logic these values are checked against, so this
# reaches into its scripts dir rather than duplicating either.
#
# Neither measurement lives in this file any more. The usability half moved to
# usability_probe.py (CF-0048) and the caption half to caption_probe.py
# (CF-0055), for the same two reasons: remeasure_usability.py and
# remeasure_captions.py run them over an existing index without re-deriving
# shots, and cache_fingerprint.py / caption_cache.py hash them to decide
# whether a cached measurement was made by today's code - so each has to be a
# file that changes when its measurement changes, and not when the contact
# sheet or the card pass does.
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting (script + child events)
from _fi_paths import sibling_scripts  # noqa: E402 - CF-0267: unique name, see _fi_paths.py
import source_rights  # noqa: E402 - CF-0663: the source's rights record in shots.json
import screen_recording  # noqa: E402 - CF-0567: an own capture's shots carry their kind
import shot_usability  # noqa: E402 - CF-0567: an own capture's shots are never cards
import verdict_profile  # noqa: E402 - CF-0163's merged-shot signal (pure, no video/Vision)

VIDEO_EDITOR_SCRIPTS = sibling_scripts("video-editor")  # CF-0267: from the root, not by counting `..`
sys.path.insert(0, str(VIDEO_EDITOR_SCRIPTS))
import detect_text_band  # noqa: E402 - sample_text_regions(), for the card-text probe
import caption_cache  # noqa: E402 - the caption probe plus the stamp saying who made it
from prepare_clip import detect_letterbox  # noqa: E402 - the card probe crops bars the way the usability probe does (CF-0093)
import shot_schema  # noqa: E402 - the optional time marks (tile_at/moment_at, CF-0106)
import source_fingerprint  # noqa: E402 - the re-upload fingerprint kept in the header (CF-0080)
from usability_probe import extract_full_frames, probe_usability  # noqa: E402
import usability_probe  # noqa: E402 - QC_ASPECT, and the smart_crop import shim it carries
import smart_crop  # noqa: E402 - the renderer's cover window around a person (CF-0413)
import vision_client  # noqa: E402 - faces on a card-reading frame (CF-0413)
import card_frame  # noqa: E402 - per-frame "card text or caption?" judgement (CF-0093)
import sharpness  # noqa: E402 - CF-0452: how sharp the shot is, measured once here
from card_frame import CARD_TEXT_AREA_THRESHOLD  # noqa: E402,F401 - kept importable from here


def duration(path):
    out = runlog.run_child(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        tool="ffprobe", capture_output=True, text=True)
    return float(out.stdout.strip())


def shot_boundaries(path, threshold, source_seconds=None):
    """Scene-change timestamps from ffmpeg's own scene score.

    CF-0316: `source-scenedetect` is the one call in this script that reads the
    **whole** file, so it is the watchdog's `scan` class: a ceiling of 1.0 x the
    source's own seconds, never below 120 s. An absolute number here would kill
    honest work - CF-0112 measured 1262 s of real scanning on a 2h14m source -
    and it is this call that sets the worst honest silence the operation ceiling
    is built from (it writes nothing while it runs). `source_seconds` is the
    length `build_shots()` has already measured; without it the class falls back
    to its 120 s floor, so no call goes out unbounded either way.
    """
    out = runlog.run_child(
        [FFMPEG, "-hide_banner", "-nostdin", "-i", str(path),
         "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        tool="ffmpeg", watchdog="scan", source_seconds=source_seconds,
        capture_output=True, text=True)
    return [float(t) for t in re.findall(r"pts_time:(\d+\.?\d*)", out.stderr)]


def build_shots(path, threshold, max_shots, split=True, stats=None, profiles=None):
    """Shot list for `path`. `stats`, if given, receives split_heterogeneous()'s
    counters (probed / split / sub_shots / long_left). `profiles` (CF-0163) is
    the recorded verdict profiles for this source, or None."""
    total = duration(path)
    # CF-0316: the length measured above is handed to the whole-file scan, so its
    # watchdog ceiling is this source's own seconds and not a flat number.
    cuts = ([0.0] + [t for t in shot_boundaries(path, threshold, source_seconds=total)
                     if 0 < t < total] + [total])
    shots = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a >= MIN_SHOT_SECONDS:
            shots.append({"start": round(a, 3), "end": round(b, 3)})
    # A source with no detectable cuts is still one usable shot.
    if not shots:
        shots = [{"start": 0.0, "end": round(total, 3)}]
    # CF-0105: the cap is applied on both sides of the split. Before, so that
    # the heterogeneity probe (one decode of the shot's span plus a CLIP
    # batch) only runs on shots that would be indexed anyway - a 45-minute
    # source has hundreds of long shots past the cap and probing them would
    # be pure waste. After, because sub-shots are ordinary shots and count
    # against the same budget; cap_shots() reserves the tail on that second
    # pass exactly as it did on the first, so a split never re-starves the
    # end cards CF-0082 rescued (see tests/test_split_merged_shots.py).
    shots = cap_shots(shots, max_shots)
    if split:
        shots, split_stats = split_heterogeneous(path, shots, profiles=profiles)
        if stats is not None:
            stats.update(split_stats)
    return cap_shots(shots, max_shots)


# CF-0105: one `select='gt(scene,0.25)'` pass glues dark and fast montages
# into 13-60s shots (VkxDzRS37JE s2, yaCHj96d1PA s0/s6, M9NWvGZViCg s0,
# 8JQ45AWDgPE s0 in run 2026-09-03T2037Z) - ffmpeg's scene score is a mean
# absolute pixel difference, so a cut between two *dark* frames scores low no
# matter how different the pictures are. The embedding and the contact-sheet
# tile come from the shot's midpoint, the description is written from the
# tile, and resolve_anchors cuts from the head - so for a merged shot the
# frame the script is checked against is never the one on screen (CF-0081).
#
# Fixed at the source: a shot whose pictures really differ is re-cut into
# sub-shots, each getting its own embedding, tile and description. Lowering
# --threshold globally is not an option - it shatters static scenes and
# inflates indexing time (3h19m for 23 sources already, CF-0052) - so a
# cheap two-signal probe decides *which* shots get the second, more
# sensitive pass, and static shots are never touched.
#
# Every number below was read off the real pool, not guessed: 18 long shots
# probed with 8 uniform samples each (12 merged montages from CF-0081's
# batch, 6 static/near-static controls - two press-conference/reaction-cam
# shots of 51-56s, a 58s single-clip news short, a distributor card, two
# single-scene dialogue shots). Table in CF-0105's task file.

# Shots shorter than this are taken as-is. The task's starting point was 8s,
# but one of CF-0081's five control frames - Snape's cloak, the tail of
# SJVmeJaS44s s24 - lives in a 4.3s merged shot (three sub-0.25 cuts inside,
# CLIP min-pair 0.49). The pool has 181 shots of 4-8s against 150 above 8s,
# and the probe on a 4-8s span costs about a second, so the lower floor is
# cheap; the expensive part (per-sub-shot probes) is bounded by --max-shots
# either way.
SPLIT_MIN_SECONDS = 4.0

# Uniform samples per probed shot - fixed, not scaled with duration, so the
# CLIP dispersion below stays comparable to the numbers it was calibrated
# against (a min over 28 pairs; more samples would only ever lower it).
SPLIT_SAMPLES = 8

# Signal 1 - CLIP dispersion: the minimum pairwise cosine similarity between
# the samples' image embeddings. Measured: merged montages 0.395-0.604 (one
# outlier at 0.676, caught by signal 2); genuinely static shots 0.933-0.937;
# the 58s single-clip news short 0.676. Below this the shot is heterogeneous.
SPLIT_CLIP_MIN_SIM = 0.65

# Signal 2 - luma step: the largest brightness change between the median of
# the SPLIT_LUMA_WINDOW seconds before a frame and the median of the window
# after it (YAVG, 16-235), over every frame of the span. This is what catches
# the fade-to-black between two scenes that never produces a single high-
# scoring frame, and the cut between two dark frames of different content.
#
# The task's starting formulation - the jump between two *neighbouring
# samples* - measured a false positive on the first static source tried:
# W4mvmBXg9Nc s0, Clooney walking to his seat at a press conference, drifts
# its exposure 79 -> 95 -> 104 across 15s with no frame scoring even 0.05,
# and the sample-to-sample difference (15.4) still cleared the gate and put
# three midpoint cuts into a one-take shot. A windowed median step measures
# *speed*: the same drift moves it by a few units, a real cut by the full
# swing, and a one-frame photo flash not at all.
#
# Re-read off the same 18 shots plus that one: one-take controls 0.3-1.5;
# the Clooney shot 11.6 (its opening fade-in from black, and a pan onto the
# bright backdrop at 10s - the fastest exposure change measured on a shot
# that must stay whole); merged montages 12.5-53.5, of which the weakest
# that *needs* this signal (CLIP min-pair above SPLIT_CLIP_MIN_SIM) is
# pOY-Q5DXfcI s0 at 18.7 - the Raygun dancer-to-interview fade. 12 sits
# just above the pan and well below the fade.
SPLIT_LUMA_WINDOW = 0.5
SPLIT_LUMA_STEP = 12.0

# The second, local scene-detection pass runs only inside a shot the two
# signals flagged, so it can afford to be far more sensitive than the global
# 0.25. Measured inside the flagged shots: the real cuts sit at 0.10-0.25
# (the CHRISTMAS card in SJVmeJaS44s s38 enters at 0.152, the Tulsa King gun
# in yaCHj96d1PA s0 at 0.186, the cuts inside VkxDzRS37JE s2 at 0.16-0.20);
# 0.05 would also admit in-shot motion (130 hits in one 58s commentary shot
# against 53 at 0.1, mostly sub-0.2s clusters that MIN_SHOT_SECONDS merges).
SPLIT_THRESHOLD = 0.10

# Floor for the per-frame scene scores the probe records alongside the
# samples. Anything above it is remembered so that a luma-jump interval with
# no cut above SPLIT_THRESHOLD can still be cut at its strongest frame
# rather than at the interval's midpoint.
SPLIT_SCORE_FLOOR = 0.03

# CF-0163 - signal 3, the verdict profile. The two signals above are blind to
# a join that keeps the palette and the global composition and moves only the
# subject: CLIP dispersion reads the two scenes as the same picture, and the
# luma step never moves. The pool was re-indexed after CF-0105 and those joins
# are still inside shots - CF-0156 found them by watching `usable()`'s verdict
# jump along a clip and going to the frames.
#
# So this signal is not taken here at all: it is *read* from a verdict profile
# recorded against a real planner window (`--verdict-profiles`, the files
# CF-0155/CF-0156's probe already writes; schema in verdict_profile.py). The
# reason is cost, measured on CF-0156's own 24-shot sample from the timings it
# recorded: 17.7 frames per shot at 0.80s of Vision per frame, 17.5s per shot
# all in. On this pool's ~330 shots of SPLIT_MIN_SECONDS or longer that is
# ~1.6h against the ~3.3h the whole index takes (CF-0052) - not more expensive
# than indexing, but half of it again, for a signal that only speaks about
# shots the cheap probe already looked at and let through. Paying it inside
# every index would tax every source for the few that are merged; taking it
# from a profile the pool re-measure produces anyway (CF-0093) costs nothing
# and splits exactly the same shots. When no profile is supplied the indexer
# behaves exactly as it did after CF-0105.
#
# What the signal decides is in verdict_profile.py, thresholds and all; the
# only number that belongs here is how far from a seam a cut counts as the
# same join.

# A profile locates a seam only to within its own sampling step (0.5s in every
# profile recorded so far), while the local scene pass finds the same join to
# the frame. So a seam with a cut already within this of it is dropped in
# favour of that cut - one join, cut once, at the better-placed of the two.
# That also collapses a run of neighbouring seams (Ho10_4IX1jE s011 flips on
# three transitions in a row while the composition changes twice) into the
# first of them.
SPLIT_SEAM_WINDOW = 0.5


def clip_model():
    """The CLIP image/text model, loaded once per process.

    Loaded three times before CF-0105 (embed(), flag_cards(), and now the
    split probe); each load is a couple of seconds and the weights are
    identical, so this memoises them.
    """
    if not hasattr(clip_model, "_cached"):
        import warnings
        warnings.filterwarnings("ignore")
        from transformers import CLIPModel, CLIPProcessor, CLIPTokenizer
        # CF-0107: the weight load is its own `child` (tool clip, step embed).
        with runlog.child("clip", argv=["clip", "load", MODEL], step="embed"):
            clip_model._cached = (CLIPModel.from_pretrained(MODEL).eval(),
                                  CLIPProcessor.from_pretrained(MODEL),
                                  CLIPTokenizer.from_pretrained(MODEL))
    return clip_model._cached


def probe_shot_span(path, start, end, out_dir, samples=SPLIT_SAMPLES):
    """One decode of [start, end): `samples` uniform frames (scaled like
    extract_frames), every frame whose scene score clears SPLIT_SCORE_FLOOR,
    and the mean luma of every frame.

    Returns (frame_paths, frame_times, scores, lumas) with times in source
    seconds; scores and lumas are lists of (time, value). A single pass with
    a split filter graph rather than `samples` separate `-ss` seeks plus a
    detection pass: measured on a 30s 1080p span, 3.7s against roughly 12s
    before the luma branch was added. The luma branch works on a 16x16
    downscale, so signalstats itself costs nothing; the decode dominates.

    CF-0238: the scene branch passes *every* frame (`gte(scene,0)`) and the
    SPLIT_SCORE_FLOOR is applied when the file is parsed. With the floor
    inside `select`, a span where no frame reached it (a static one-take
    shot - any codec, VP9 only showed it first) left the `[so]` null output
    with no frame at all, ffmpeg 9 then cannot open its encoder and exits
    234 - an honest "no cut here" written as a crash, while a real crash
    read as "no cut here" because the empty file looked the same. Now the
    branch is never empty, so a non-zero exit, or a scene or luma file with
    nothing in it, is the detector failing, and this raises ProbeFailed
    instead of returning an empty series. Results are the same numbers as
    before: the scene score is computed against the previous *input* frame
    whatever the threshold is, so filtering afterwards selects the same set.
    """
    span = max(0.0, end - start)
    step = span / samples
    out_dir = Path(out_dir)
    scores_file = out_dir / "scores.txt"
    luma_file = out_dir / "luma.txt"
    pattern = out_dir / "sample_%02d.png"
    # Samples sit mid-interval ((i + 0.5) * step, as probe_card_text() does),
    # not at interval starts: the first frame of a span is the cut itself -
    # a transition frame, or a black one - and sampling it dragged the CLIP
    # dispersion of a one-take shot from 0.68 down to 0.43 during
    # calibration, the wrong side of SPLIT_CLIP_MIN_SIM.
    pick = (f"if(isnan(prev_selected_t),gte(t,{0.5 * step:.4f}),"
            f"gte(t,prev_selected_t+{step:.4f}))")
    out = runlog.run_child(
        [FFMPEG, "-hide_banner", "-nostdin", "-v", "error",
         "-ss", str(start), "-t", str(span), "-i", str(path),
         "-filter_complex",
         f"[0:v]split=3[s][f][l];"
         f"[s]select='gte(scene,0)',metadata=print:file={scores_file}[so];"
         f"[f]select='{pick}',scale=336:-2[fo];"
         f"[l]scale=16:16,signalstats,"
         f"metadata=print:key=lavfi.signalstats.YAVG:file={luma_file}[lo]",
         "-map", "[so]", "-an", "-f", "null", "-",
         "-map", "[lo]", "-an", "-f", "null", "-",
         "-map", "[fo]", "-fps_mode", "passthrough", "-frames:v", str(samples), str(pattern)],
        tool="ffmpeg", capture_output=True)
    rc = getattr(out, "returncode", 0)
    if rc:
        err = (getattr(out, "stderr", b"") or b"")
        err = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err)
        tail = err.strip().splitlines()[-1:] or ["no stderr"]
        raise ProbeFailed(f"ffmpeg exited {rc}: {tail[0][:160]}")

    def parse(file, key):
        text = file.read_text() if file.exists() else ""
        times = [float(t) + start for t in re.findall(r"pts_time:(\d+\.?\d*)", text)]
        vals = [float(v) for v in re.findall(rf"{re.escape(key)}=(\d+\.?\d*)", text)]
        return list(zip(times, vals))

    frames = sorted(out_dir.glob("sample_*.png"))
    # The select above passes the first frame at or after each (i + 0.5) *
    # step, so the nominal time is within one frame of the real one.
    times = [start + (i + 0.5) * step for i in range(len(frames))]
    every = parse(scores_file, "lavfi.scene_score")
    lumas = parse(luma_file, "lavfi.signalstats.YAVG")
    # Both branches see every decoded frame, so with frames decoded an empty
    # series is a detector that did not run - never "no cut".
    if frames and not every:
        raise ProbeFailed("scene detector wrote no scores")
    if frames and not lumas:
        raise ProbeFailed("luma branch wrote no values")
    return frames, times, [(t, v) for t, v in every if v >= SPLIT_SCORE_FLOOR], lumas


class ProbeFailed(RuntimeError):
    """CF-0238: the split probe did not measure this shot - kept apart from a
    probe that measured it and found no cut."""


# A cut placed by split_points() can land on the first frame of a fade-in
# from black - the CHRISTMAS card in SJVmeJaS44s s38 enters at 139.31 as a
# scene-score cut *to black* and then takes 1.6s to fade up, so the sub-shot's
# head (which is what resolve_anchors cuts from, and what the usability probe
# looks at) would be a black frame while its tile and description show the
# card. YAVG is limited-range luma, 16 = black; a frame at or below 20 is
# black for this purpose, and the head moves to the first frame that clears
# black by a visible margin, but only within a fade's worth of seconds - a
# scene that simply *is* that dark keeps its cut where the detector put it.
SPLIT_BLACK_YAVG = 20.0
SPLIT_BLACK_CLEAR_YAVG = 24.0
SPLIT_BLACK_LEAD_MAX_SECONDS = 2.0


def skip_black_lead(cut, lumas):
    """Move `cut` forward past a black lead-in, if there is one. Pure."""
    after = [(t, y) for t, y in lumas if t >= cut]
    if not after or after[0][1] > SPLIT_BLACK_YAVG:
        return cut
    for t, y in after:
        if t - cut > SPLIT_BLACK_LEAD_MAX_SECONDS:
            break
        if y >= SPLIT_BLACK_CLEAR_YAVG:
            return t
    return cut


def sample_dispersion(frames):
    """Minimum pairwise CLIP cosine similarity over the sample frames - the
    first heterogeneity signal in raw form."""
    import torch
    from PIL import Image

    model, proc, _ = clip_model()
    images = [Image.open(f).convert("RGB") for f in frames]
    with torch.no_grad(), runlog.child("clip", argv=["clip", "dispersion", str(len(images))],
                                       step="embed"):
        vecs = model.get_image_features(**proc(images=images, return_tensors="pt"))
        vecs = vecs / vecs.norm(dim=-1, keepdim=True)
        sims = vecs @ vecs.T
    n = len(images)
    return min((float(sims[i, j]) for i in range(n) for j in range(i + 1, n)), default=1.0)


def luma_steps(lumas, window=SPLIT_LUMA_WINDOW):
    """Per-frame brightness *steps*: for every frame, the difference between
    the median luma of the `window` seconds after it and the `window`
    seconds before it. Returns [(time, step)], frames without a full window
    on both sides omitted. Pure.

    A median over half a second, not a frame-to-frame or sample-to-sample
    difference: a hard cut or a fade through black moves it by the full
    swing, a camera pan or an exposure drift by a few units over the same
    span, and a single photo-flash frame not at all.

    The median makes the step's *magnitude* robust but its *location* a
    plateau (every frame within half a window of a hard cut sees the same
    two medians), so each step is reported at the frame with the largest
    frame-to-frame change within half a window of it - for a hard cut,
    exactly the first frame of the new scene, which is where a head belongs.
    """
    from statistics import median
    n = len(lumas)
    deltas = [0.0] + [abs(lumas[i][1] - lumas[i - 1][1]) for i in range(1, n)]
    steps = []
    lo = hi = 0
    for i in range(n):
        t = lumas[i][0]
        while lo < i and lumas[lo][0] < t - window:
            lo += 1
        while hi < n and lumas[hi][0] < t + window:
            hi += 1
        before = [y for _, y in lumas[lo:i]]
        after = [y for _, y in lumas[i:hi]]
        if not before or not after or lumas[lo][0] > t - window * 0.8 \
                or lumas[hi - 1][0] < t + window * 0.8:
            continue
        step = abs(median(after) - median(before))
        near = [j for j in range(lo, hi) if abs(lumas[j][0] - t) <= window / 2]
        steepest = max(near, key=lambda j: deltas[j])
        steps.append((lumas[steepest][0], step))
    return steps


def heterogeneity(min_sim, steps, seams=()):
    """Is a shot heterogeneous, and why. `steps` is luma_steps()'s output,
    `seams` is verdict_profile.source_seams()'s - the seam times a recorded
    verdict profile puts inside this shot, empty when none was supplied.
    Pure so the tests can drive it without ffmpeg, CLIP or Vision."""
    max_step = max((s for _, s in steps), default=0.0)
    seams = list(seams)
    return {"min_sim": round(min_sim, 3), "max_luma_step": round(max_step, 1),
            "clip": min_sim < SPLIT_CLIP_MIN_SIM, "luma": max_step >= SPLIT_LUMA_STEP,
            # CF-0163: the third signal is a count, not a measurement, because
            # verdict_profile.py has already applied its own thresholds to
            # every transition - what arrives here is seams, not evidence.
            "verdict": len(seams) >= verdict_profile.MERGED_MIN_SEAMS,
            "seams": [round(t, 3) for t in seams]}


def split_points(start, end, scores, steps, seams=()):
    """Where to cut a heterogeneous shot.

    Every frame whose local scene score clears SPLIT_THRESHOLD is a cut. A
    luma step clearing SPLIT_LUMA_STEP with no such cut within a window of
    it (the fade-to-black case - no single frame scores high, and two dark
    frames of different content score low) is a cut at the step's own peak.
    A CF-0163 seam with no cut within SPLIT_SEAM_WINDOW of it is a cut at the
    seam - the join the first two signals are blind to, where the picture
    keeps its palette and its layout and only the subject moves.
    Pure - the tests feed it synthetic series.
    """
    cuts = sorted(t for t, s in scores if s >= SPLIT_THRESHOLD and start < t < end)
    peaks = sorted(((s, t) for t, s in steps if s >= SPLIT_LUMA_STEP and start < t < end),
                   reverse=True)
    for _, t in peaks:
        if all(abs(t - c) > SPLIT_LUMA_WINDOW for c in cuts):
            cuts.append(t)
    for t in sorted(seams):
        if start < t < end and all(abs(t - c) > SPLIT_SEAM_WINDOW for c in cuts):
            cuts.append(t)
    return sorted(set(cuts))


def partition(start, end, cuts, min_seconds=MIN_SHOT_SECONDS):
    """Sub-shots of [start, end] cut at `cuts`, never shorter than
    `min_seconds`. Unlike build_shots(), which *drops* an interval shorter
    than MIN_SHOT_SECONDS, a short piece here is merged into its neighbour:
    the parent shot covered this span before the split, and splitting must
    not lose any of it.
    """
    kept = [start]
    for c in sorted(cuts):
        if c - kept[-1] >= min_seconds and end - c >= min_seconds:
            kept.append(c)
    edges = kept + [end]
    return [{"start": round(a, 3), "end": round(b, 3)} for a, b in zip(edges, edges[1:])]


def split_heterogeneous(path, shots, log=None, profiles=None):
    """Re-cut every shot of SPLIT_MIN_SECONDS or longer whose pictures
    really differ. Sub-shots replace the parent in place, so the result is
    an ordinary flat shot list; the caller assigns `index` afterwards.

    `profiles` (CF-0163) is verdict_profile.load_dir()'s output for this
    source, or None. It costs nothing here - the seams were decided when the
    profile was recorded - so it is also consulted on shots too short for the
    CLIP/luma probe, and on shots whose probe failed.

    Returns (shots, stats) where stats counts probed/split/sub-shots and the
    long shots left intact - the last number is what CF-0106 sizes itself by.
    """
    log = log or (lambda msg: print(msg, file=sys.stderr))
    out = []
    stats = {"probed": 0, "split": 0, "sub_shots": 0, "long_left": 0,
             # CF-0163: how much of the above the verdict profile is
             # responsible for. `verdict_only` is the number the task is
             # about - shots CF-0105's two signals looked at and let through.
             "verdict_seams": 0, "verdict_only": 0, "verdict_flagged": 0,
             # CF-0238: probes that did not measure their shot (ffmpeg exit,
             # empty scene/luma series, too few samples). Those shots keep the
             # whole-file detector's cut and carry `split_probe_failed`. An
             # index written before CF-0238 has no such key: unknown, not 0.
             "probe_failed": 0}
    failed_at = []
    for shot in shots:
        start, end = shot["start"], shot["end"]
        seams = verdict_profile.source_seams(
            verdict_profile.within(profiles, start, end))
        seams = [t for t in seams if start < t < end]
        stats["verdict_seams"] += len(seams)
        if end - start < SPLIT_MIN_SECONDS and not seams:
            out.append(shot)
            continue
        min_sim, scores, frame_lumas, probe_error = 1.0, [], [], None
        if end - start >= SPLIT_MIN_SECONDS:
            stats["probed"] += 1
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    frames, times, scores, frame_lumas = probe_shot_span(path, start, end, tmp)
                    if len(frames) < 2:
                        raise RuntimeError(f"only {len(frames)} sample frame(s) extracted")
                    min_sim = sample_dispersion(frames)
            except Exception as e:
                # A probe that fails leaves the shot exactly as the detector
                # found it - the pre-CF-0105 behaviour, never a lost shot.
                # Unless a profile already named seams inside it (CF-0163):
                # those were measured elsewhere and do not need this probe.
                # CF-0238: and it is recorded as a failure - on the shot, in
                # split_stats and on the script's run event - never as a shot
                # where the probe found no cut.
                reason = f"{e.__class__.__name__}: {e}"[:200]
                stats["probe_failed"] += 1
                failed_at.append({"start": start, "end": end, "error": reason})
                log(f"  split probe failed for shot {start}-{end}: {e}")
                if not seams:
                    out.append(dict(shot, split_probe_failed=reason))
                    continue
                probe_error = reason
                min_sim, scores, frame_lumas = 1.0, [], []
        steps = luma_steps(frame_lumas)
        verdict = heterogeneity(min_sim, steps, seams)
        pieces = []
        if verdict["clip"] or verdict["luma"] or verdict["verdict"]:
            cuts = [skip_black_lead(c, frame_lumas)
                    for c in split_points(start, end, scores, steps, seams)]
            pieces = partition(start, end, cuts)
        if len(pieces) > 1:
            stats["split"] += 1
            stats["sub_shots"] += len(pieces)
            only = verdict["verdict"] and not (verdict["clip"] or verdict["luma"])
            stats["verdict_only"] += 1 if only else 0
            log(f"  split {start}-{end} ({end - start:.1f}s) into {len(pieces)}: "
                f"min_sim={verdict['min_sim']} luma_step={verdict['max_luma_step']}"
                + (f" seams={verdict['seams']}" if seams else ""))
            out.extend(dict(p, split_probe_failed=probe_error) if probe_error else p
                       for p in pieces)
        else:
            # CF-0163: a join the profile is sure of, that MIN_SHOT_SECONDS
            # refuses to cut on, is still a fact about this shot - the
            # description written from one tile does not describe the rest of
            # it, and Content Researcher reads that description. Recorded on
            # the shot rather than dropped.
            if seams:
                shot["merged_seams"] = verdict["seams"]
                stats["verdict_flagged"] += 1
            out.append(dict(shot, split_probe_failed=probe_error) if probe_error else shot)
        stats["long_left"] += sum(1 for p in (pieces or [shot])
                                  if p["end"] - p["start"] >= LONG_SHOT_SECONDS)
    if failed_at:
        # CF-0238: the degradation goes onto the script's own done event in
        # RUN_EVENTS.jsonl (the failed ffmpeg child is there already).
        runlog.annotate(split_probe_failed=len(failed_at),
                        split_probe_failed_first=failed_at[0])
    return out, stats


# What "still long after the split" means for the count split_heterogeneous()
# reports: the shots CF-0106's in-shot point cut has to cover. The task's own
# figure, kept separate from SPLIT_MIN_SECONDS so that lowering the probe
# floor does not silently move the goalposts of that report.
LONG_SHOT_SECONDS = 8.0


def cap_shots(shots, max_shots):
    """Apply --max-shots without starving the source's tail (CF-0082).

    `shots[:max_shots]` (the old body of this function) always kept a run
    of consecutive early shots and dropped everything after - which for a
    source with more cuts than the cap allows is reliably the tail, where
    end/date/logo cards live. Keep both ends instead: head gets the rest of
    the budget, tail gets a fixed reservation (halved when the cap itself
    is too small to give both ends a fair share).
    """
    if len(shots) <= max_shots:
        return shots
    tail_n = min(TAIL_SHOTS_RESERVED, max_shots // 2, len(shots))
    head_n = max_shots - tail_n
    return shots[:head_n] + (shots[-tail_n:] if tail_n else [])


def tile_time(shot):
    """Where a shot's tile and embedding frame are sampled: its midpoint.

    Recorded on the shot as `tile_at` (CF-0106) because it is not the head:
    for a 20-second shot the describer is looking at second 10 and
    resolve_anchors cuts from second 0 (CF-0081's mechanism). One place to
    change if the sampling ever moves, so the recorded number cannot drift
    from the frame actually taken."""
    return round(shot["start"] + (shot["end"] - shot["start"]) / 2, 3)


def extract_frames(path, shots, out_dir):
    frames = []
    for i, shot in enumerate(shots):
        mid = tile_time(shot)
        f = out_dir / f"shot_{i:03d}.png"
        runlog.run_child(
            [FFMPEG, "-y", "-nostdin", "-v", "error", "-ss", str(mid), "-i", str(path),
             "-frames:v", "1", "-vf", "scale=336:-2", str(f)],
            tool="ffmpeg", capture_output=True)
        frames.append(f if f.exists() else None)
    return frames


def embed(frames):
    import torch
    from PIL import Image

    model, proc, _ = clip_model()

    images, keep = [], []
    for i, f in enumerate(frames):
        if f is None:
            continue
        images.append(Image.open(f).convert("RGB"))
        keep.append(i)

    # CF-0107: the embedding pass is one `child` per source (tool clip, step
    # embed) - the CPU half of "download or CLIP?".
    with torch.no_grad(), runlog.child("clip", argv=["clip", "embed", str(len(images))],
                                       step="embed"):
        inputs = proc(images=images, return_tensors="pt")
        vecs = model.get_image_features(**inputs)
        vecs = vecs / vecs.norm(dim=-1, keepdim=True)

    out = {}
    for idx, i in enumerate(keep):
        out[i] = [round(float(v), 5) for v in vecs[idx]]
    return out


# Trailers are full of these, and they are never what a line of narration is
# about. CLIP sees them as clearly as it sees a rink, so they can be flagged
# once at index time instead of excluded by hand for every video.
CARD_PHRASES = [
    "a title card with large text on a solid colour background",
    "an end card with a logo and a release date",
    "a blank screen with subtitles and no picture",
]
CARD_THRESHOLD = 0.26

# CF-0010: real shots and real cards overlap on CLIP-phrase similarity alone
# (measured 0.208-0.26 for real shots, 0.254-0.286 for cards, on the same
# trailer CARD_THRESHOLD was calibrated against - and 0.17-0.2314 vs. real
# shots up to 0.2593 on a ExampleStream sitcom clip, where three genuine title
# cards ("GET READY Y'ALL", "HER FRESH START", "IS JUST GETTING STARTED")
# scored below CARD_THRESHOLD and passed as ordinary footage). A shot still
# above CARD_THRESHOLD is trusted on CLIP alone, same as before - that band
# already measures clean on every source checked (see the task file). Below
# it and down to CARD_THRESHOLD_LOW, a shot is only counted as a card if
# probe_card_text() also finds persistent, large on-screen text.
#
# CARD_THRESHOLD_LOW cannot be dropped much further than this: an early
# attempt set it at 0.20 and a 0.96s real shot on the sitcom clip - a woman
# walking past a wall-mounted arcade sign, "CAPTAIN BOINKY'S ARCADE" legible
# at CLIP sim 0.2062 - passed both gates (persistent enough across its own
# few samples, plenty of text area) and got flagged. Real signage in a real
# shot is exactly the false-positive risk a text-only signal has, and CLIP
# similarity that low does not actually mean "looks like a card" - it is
# indistinguishable from this clip's own ordinary-shot noise (up to 0.2314
# with no text at all). 0.22 clears every real shot measured on both test
# sources (highest false-candidate: 0.2314, with no text hit) while still
# admitting every genuine card found below CARD_THRESHOLD (lowest: 0.2272).
# That gap is real but not wide - a source with dialogue-shot noise reaching
# higher than 0.2314 could still slip a real shot through if it also carries
# persistent large text; re-tune from measured data if one turns up, not by
# guessing.
CARD_THRESHOLD_LOW = 0.22

# CARD_TEXT_AREA_THRESHOLD (how much text a frame needs before it says
# anything about cards) lives in card_frame.py since CF-0093, next to the two
# measurements that then decide whether that text is a card's or a caption's.

# Same bar detect_text_band.py's own caption detector uses for a persistent
# band (MIN_HIT_RATE) - a card's text can be on screen for only part of a
# long shot (a studio logo fading in mid-shot, not held the whole span), so
# this asks for the signal to show up in *some* samples, not most of them.
CARD_TEXT_MIN_HIT_RATE = 0.25

# CF-0093: a shot above CARD_THRESHOLD is no longer trusted on CLIP alone
# when the text probe has seen the opposite. ScKvReYRZ-A s0 (a vertical Le
# Monde talking head with French subtitles) scores 0.2631 - a hair over the
# threshold - and 1RnyZgfN-JY s11 (a captioned trailer wide) 0.2674: CLIP
# reads "subtitles on a plain picture" as close to its own "a blank screen
# with subtitles" phrase. When at least this share of a shot's sampled
# frames carry caption-sized text on a picture, and none carry card text,
# the shot is captioned footage. Half, not CARD_TEXT_MIN_HIT_RATE: the veto
# overrides a signal that was right on every card measured, so it has to be
# the shot's dominant reading, not an occasional one. A shot whose frames say
# nothing (no text, a logo animation) is still a card on CLIP alone.
CAPTION_VETO_RATE = 0.5


# CF-0331: ceiling on the one-call frame grab below. The call decodes one
# shot's span - a few seconds - and measured 1.4-2.1 s for a 20-sample shot on
# pool sources, so this is a hang guard, not a budget.
SPAN_GRAB_TIMEOUT_S = 120

# CF-0740 L1: the card-text probe's frames are shrunk to at most this height
# before Vision reads them. Accurate-mode OCR costs by the pixel, and on the
# CPU-pinned worker (CF-0711) card-text was ~56 % of the Vision service time of
# a pass (docs/notes/cf-0740-indexing-time.md). Every card verdict is relative
# to the frame - card_frame.py measures text as shares of the frame's width and
# height, the colour histogram first resizes to ANALYSIS_WIDTH, the face that
# makes branding a fraction of the frame height - so a 1080p frame read at
# 720p keeps its verdict, give or take text under ~12 px. A frame already at
# or below the cap goes through untouched (no resampling at all: the width
# expression keeps `iw` there, and ffmpeg's scale passes an unchanged frame
# through). The scale sits after the picker, so only the picked frames are
# scaled, not every decoded one.
#
# FI_CARD_TEXT_MAX_H overrides it for a measurement run: another height, or 0
# for no cap - the full-resolution frames of before CF-0740 (the baseline).
# Card rates carry no fingerprint (they are not in cache_fingerprint.py's or
# caption_cache.py's sources), so the cap moves no cache key and nothing in
# the pool is re-measured: a source indexed before it keeps its rates.
CARD_TEXT_MAX_H = 720
CARD_TEXT_MAX_H_ENV = "FI_CARD_TEXT_MAX_H"


def card_text_max_height(environ=None):
    """The height cap the card-text frames get: $FI_CARD_TEXT_MAX_H, else
    CARD_TEXT_MAX_H. 0 (or below) is no cap -> None. Anything unreadable falls
    back to the default rather than stopping an index."""
    raw = (os.environ if environ is None else environ).get(CARD_TEXT_MAX_H_ENV, "")
    try:
        value = int(str(raw).strip())
    except ValueError:
        return CARD_TEXT_MAX_H
    return value if value > 0 else None


def card_text_scale(max_height):
    """The ffmpeg filter that caps a frame at `max_height` keeping its aspect
    (width rounded to even), and leaves a frame at or below the cap exactly as
    it is. None when there is no cap."""
    if not max_height:
        return None
    h = int(max_height)
    return f"scale=w='if(gt(ih,{h}),-2,iw)':h='min({h},ih)'"


_FROM_ENV = object()


def grab_span_samples(video_path, start, duration_s, samples, bars, out_dir,
                      max_height=_FROM_ENV):
    """`samples` frames of [start, start + duration_s), cropped to `bars`, at
    the (i + 0.5) / samples grid probe_card_text() samples on - in ONE ffmpeg
    call. Returns the frame paths, in time order.

    CF-0331: this was `samples` separate `ffmpeg -ss t -i src -frames:v 1`
    calls, 8 to 20 process starts per shot - roughly 15 000 over the three
    runs CF-0112 measured, 33.5 % of the whole stage's machine work, which
    made process start, not decoding, the indexer's wall. One call over the
    span is the same trick shot-thumbs and probe_shot_span() already use.

    The frames are the same frames, not merely equivalent ones. Input-seeking
    to t hands out the first frame whose timestamp is at or after t; `-ss
    start` rebases the filter clock to the span's own start, so `select` on
    the same grid picks that same frame. Verified pixel-exact (PIL RGB bytes,
    sha256) on real pool sources, cropped and uncropped, short shots and long.

    The grid is absolute - `selected_n`, not the `prev_selected_t` of
    probe_shot_span(): with prev_selected_t each selected frame's own
    timestamp carries its rounding into the next threshold, and that drifts
    over 20 samples.

    Two frames of the grid can only land on one source frame when step falls
    below a frame interval, i.e. duration_s / samples < 1 / fps. The loop
    answered that with the same frame twice, this returns the two neighbours;
    MIN_SHOT_SECONDS (0.8) keeps step at or above 0.1 s for indexing, so it
    takes a `samples` override well past a hundred to reach.

    CF-0740: the picked frames are capped at `max_height` (default: the
    CARD_TEXT_MAX_H / $FI_CARD_TEXT_MAX_H cap; None for full resolution).
    """
    step = duration_s / samples if samples else 0.0
    pick = f"select='gte(t,(selected_n+0.5)*{step:.6f})'"
    if max_height is _FROM_ENV:
        max_height = card_text_max_height()
    # CF-0740 L1: crop, pick, then shrink - the bars come off at full size,
    # and only the picked frames are scaled.
    chain = [f for f in (bars, pick, card_text_scale(max_height)) if f]
    pattern = str(Path(out_dir) / "ct%02d.png")
    cmd = [FFMPEG, "-y", "-nostdin", "-v", "error",
           "-ss", str(start), "-t", str(duration_s), "-i", str(video_path),
           "-vf", ",".join(chain),
           "-fps_mode", "passthrough", "-frames:v", str(samples), pattern]
    try:
        runlog.run_child(cmd, tool="ffmpeg",
                         params={"samples": samples,
                                 "span": f"{start:.2f}-{start + duration_s:.2f}"},
                         capture_output=True, timeout=SPAN_GRAB_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # The loop swallowed a failed grab too (no check, no raise): the probe
        # judges the frames it got, and no frames at all means zero rates, not
        # a crashed index.
        pass
    return sorted(Path(out_dir).glob("ct*.png"))


class LetterboxMemo:
    """CF-0740 L6: one cropdetect per shot instead of two.

    extract_full_frames() (the usability frame) and probe_card_text() both ask
    detect_letterbox() about the same shot with the same (start, duration) -
    two identical cropdetect decodes per shot, 40-60 s of ffmpeg CPU a source.
    detect_letterbox() is a pure function of (source, start, window): the
    same arguments give the same crop. This keeps each answer for one index
    run, so the second ask is a lookup.

    It lives here, not in usability_probe.py, on purpose: that file's
    extract_full_frames() is a root of the usability fingerprint
    (cache_fingerprint.USABILITY_ROOTS), and editing it would stale every
    usable_cached in the pool - the old pool is never re-measured.
    shared_letterbox() below hands the memo to extract_full_frames() by its
    module name for the length of the call instead.
    """

    def __init__(self):
        self.answers = {}
        self.decodes = 0

    @staticmethod
    def key(source, start, duration):
        return (str(source), round(float(start), 6), round(float(duration), 6))

    def known(self, source, start, duration):
        return self.key(source, start, duration) in self.answers

    def __call__(self, source, start, duration):
        k = self.key(source, start, duration)
        if k not in self.answers:
            self.decodes += 1
            # Looked up at call time, so a test's stand-in for
            # index_footage.detect_letterbox is the one that runs.
            self.answers[k] = detect_letterbox(source, start, duration)
        return self.answers[k]


@contextlib.contextmanager
def shared_letterbox(memo):
    """usability_probe.extract_full_frames() asks `memo` for its crops while
    this is open; the module's own detect_letterbox is put back after. The
    code and bytes of usability_probe.py are untouched - same function, same
    arguments, same answer - so its fingerprint does not move."""
    saved = usability_probe.detect_letterbox
    usability_probe.detect_letterbox = memo
    try:
        yield memo
    finally:
        usability_probe.detect_letterbox = saved


def probe_card_text(video_path, start, end, samples=None, letterbox=None):
    """Multi-frame, accurate-mode Vision text scan of one shot's span - the
    second signal flag_cards() combines with CLIP similarity (CF-0010).

    Returns {"card": rate, "caption": rate}: the share of sampled frames on
    which card_frame.classify_frame() read the text as a card's, and the
    share on which it read it as a caption on a picture (CF-0093). Before
    CF-0093 this was a single rate of frames with enough text of any kind,
    which is what flagged every captioned photo and game still as a card.

    Frames are cropped to the source's own picture with the same
    detect_letterbox() call usability_probe.py makes: a vertical short
    pillarboxed inside 16:9 (UaWVjS5SId4 s28: 748 of 1920 columns are
    picture) would otherwise measure its text area against black bars and
    its dominant colour *as* the bars.

    `samples` overrides the duration-scaled sample count - for
    remeasure_cards.py's sampled dry runs, not for indexing.

    `letterbox` (CF-0740) is main()'s LetterboxMemo: the usability frame's
    cropdetect already answered for this span, so the probe reuses it and
    runs no second decode. Without it (remeasure scripts) it asks
    detect_letterbox() itself, as before.

    Modelled on detect_text_band.detect_captions()'s sampling loop (several
    frames across the span, not one frame trusted alone - CF-0010's first,
    naive attempt at this signal sampled a shot's single midpoint frame and
    missed every card whose text was mid-fade exactly there) but diverges
    from it in the two ways a caption detector's own design does not fit
    card detection:
      - fast recognition level (detect_text_band.text_boxes()'s choice,
        made because caption detection only needs a box's *position*) reads
        forest and armour texture as text at high confidence - confirmed on
        this same footage during the original investigation. Accurate mode
        (level=0, a real transcription pass, not just glyph detection) does
        not: sampled across every real (non-card) shot tried during this
        fix's own validation, it found nothing, on either the trailer
        CARD_THRESHOLD was calibrated against or an unrelated sitcom clip.
      - captions are judged by *where* text sits (a band held low in frame,
        because that is where burned-in subtitles live); a title/end card's
        text can be anywhere - centred, a corner logo, a lower third - so
        this sums each frame's total text area instead of clustering boxes
        by vertical position.

    Sample count scales with the shot's own duration rather than staying
    fixed at 8: a brief studio-logo flash inside a long shot is easy to miss
    at a low, fixed sample count purely by where the samples land, not
    because the signal isn't there - measured on this same footage, a
    studio logo pair visible for roughly 3 of a 16.6s shot's
    seconds was missed at 8 samples and reliably caught from 16 on.
    """
    duration_s = max(0.0, end - start)
    if samples is None:
        samples = max(8, min(20, round(duration_s)))
    span = f"{start:.2f}-{end:.2f}"
    if letterbox is not None and letterbox.known(str(video_path), start, duration_s):
        bars = letterbox(str(video_path), start, duration_s)
    else:
        with runlog.child("ffmpeg", argv=["ffmpeg", "cropdetect", str(video_path), span]):
            bars = (letterbox or detect_letterbox)(str(video_path), start, duration_s)
    counts = {"card": 0, "caption": 0, "branding": 0}
    sampled = 0
    with tempfile.TemporaryDirectory() as tmp:
        # CF-0107: the frame grabs and the Vision scans used to interleave per
        # sample; they run in two passes now so each is one `child` event per
        # shot (tool ffmpeg with the sample count, tool vision with the frames
        # scanned) instead of 2 x samples events. Same frames, same verdicts.
        frames = grab_span_samples(video_path, start, duration_s, samples, bars, tmp)
        with runlog.child("vision", argv=["vision", "card-text", str(video_path), span],
                          step="probe", params={"frames": len(frames)}):
            for frame in frames:
                sampled += 1
                regions = detect_text_band.sample_text_regions(frame, level=0)
                verdict = card_frame.classify_frame(frame, regions)["verdict"]
                # CF-0413: only a frame that reads as a card is asked about
                # faces - one more Vision request there, none anywhere else.
                if verdict == "card" and card_frame.is_branding(regions, person_in_frame(frame)):
                    verdict = "branding"
                if verdict:
                    counts[verdict] += 1
    if not sampled:
        return {"card": 0.0, "caption": 0.0, "branding": 0.0}
    return {k: v / sampled for k, v in counts.items()}


def person_in_frame(frame):
    """CF-0413: the person card_frame.is_branding() needs, or None.

    Vision's faces on `frame` through the same find_roi() the usability
    probe asks, and the 9:16 window the renderer would point at them -
    smart_crop.focus_point() + delivered_window() at `cover`, exactly as
    usability_probe.text_against_window() builds it, so "beside the person"
    means "outside what the reel shows of this frame", not a second copy of
    the framing rules. None when the frame has no face (saliency, animation
    or nothing): without a person there is no branding reading, and the
    frame stays whatever classify_frame() said.

    Cost, measured on three 3oy35kY7guU interview shots at 12 samples, every
    frame card-reading: 0.8-1.6 s a shot over the probe's 11.7-15.0 s, i.e.
    0.07-0.13 s a frame through the warm worker; nothing on frames that do
    not read as a card.
    """
    vision = vision_client.find_roi(str(frame), usability_probe.QC_ASPECT)
    if vision.get("roi_source") != "faces":
        return None
    size = (vision["source_size"]["width"], vision["source_size"]["height"])
    faces = vision.get("roi_parts") or [vision["roi"]]
    aspect_w, aspect_h = (int(v) for v in usability_probe.QC_ASPECT.split(":"))
    x, y, w, h = smart_crop.delivered_window(
        size, smart_crop.focus_point(vision), vision.get("zoom", 1.0),
        aspect_w, aspect_h, "cover")
    return {"face_height": max(f["height"] for f in faces) / size[1],
            "window": (x / size[0], y / size[1], w / size[0], h / size[1])}


def card_verdict(sim, card_text_rate, caption_rate=0.0, branding_rate=0.0):
    """The is_card decision for one shot, from its best CLIP card-phrase
    similarity and probe_card_text()'s two rates.

    CF-0010: high CLIP similarity is sufficient alone (it was never wrong at
    this level, only overconfident lower down). Below that, both signals
    have to agree: a real shot that happens to carry some large text (a
    book, a sign) is exactly the false-positive risk an OCR-only signal
    would have, and CLIP similarity that low is exactly the false-negative
    risk a CLIP-only signal has - each one covers the other's blind spot.

    CF-0093: "sufficient alone" now has one exception - a shot whose sampled
    frames mostly showed caption-sized text on a picture, and never a card's
    text, is captioned footage whatever CLIP made of it (CAPTION_VETO_RATE).

    CF-0413: a frame whose card text is branding beside a person
    (card_frame.is_branding) is no longer card text - it cannot carry a shot
    across CARD_TEXT_MIN_HIT_RATE - and for the veto it is what a caption
    frame is, text on a picture: `branding_rate` adds to `caption_rate`.
    """
    if sim >= CARD_THRESHOLD:
        captioned = (caption_rate + branding_rate >= CAPTION_VETO_RATE
                     and card_text_rate < CARD_TEXT_MIN_HIT_RATE)
        return not captioned
    return sim >= CARD_THRESHOLD_LOW and card_text_rate >= CARD_TEXT_MIN_HIT_RATE


def flag_cards(vectors, text_hit_rates, caption_hit_rates=None, branding_hit_rates=None):
    import torch

    model, _, tok = clip_model()
    with torch.no_grad(), runlog.child("clip", argv=["clip", "text", "card-phrases"], step="embed"):
        text = model.get_text_features(**tok(CARD_PHRASES, padding=True, return_tensors="pt"))
        text = text / text.norm(dim=-1, keepdim=True)

    caption_hit_rates = caption_hit_rates or {}
    branding_hit_rates = branding_hit_rates or {}
    flags = {}
    for i, vec in vectors.items():
        sims = (torch.tensor(vec) @ text.T).tolist()
        flags[i] = card_verdict(max(sims), text_hit_rates.get(i, 0.0),
                                caption_hit_rates.get(i, 0.0),
                                branding_hit_rates.get(i, 0.0))
    return flags


def contact_sheet(frames, dest, cols=6):
    """Numbered grid of every shot.

    Built with ffmpeg's `tile`, which pads an incomplete last row on its own -
    hand-rolled hstack/vstack fails there, because vstack demands rows of equal
    width. Each tile carries its shot index: the sheet exists so someone can say
    "shot 7 is the cottage interior", and unlabelled tiles make that useless.
    """
    tiles = [(i, f) for i, f in enumerate(frames) if f is not None]
    if not tiles:
        return None

    numbered = Path(tiles[0][1]).parent / "numbered"
    numbered.mkdir(exist_ok=True)
    for seq, (i, f) in enumerate(tiles):
        runlog.run_child(
            [FFMPEG, "-y", "-nostdin", "-v", "error", "-i", str(f),
             "-vf", f"scale=280:158:force_original_aspect_ratio=decrease,"
                    f"pad=280:158:(ow-iw)/2:(oh-ih)/2,"
                    f"drawtext=text='{i}':fontcolor=white:fontsize=30:box=1:"
                    f"boxcolor=black@0.75:boxborderw=6:x=8:y=8",
             str(numbered / f"n_{seq:03d}.png")],
            tool="ffmpeg", capture_output=True)

    rows = (len(tiles) + cols - 1) // cols
    runlog.run_child(
        [FFMPEG, "-y", "-nostdin", "-v", "error",
         "-framerate", "1", "-i", str(numbered / "n_%03d.png"),
         "-vf", f"tile={cols}x{rows}:margin=4:padding=4:color=black",
         "-frames:v", "1", str(dest)],
        tool="ffmpeg", capture_output=True)
    return dest if Path(dest).exists() else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--threshold", type=float, default=0.25)
    p.add_argument("--max-shots", type=int, default=60)
    p.add_argument("--no-split", action="store_true",
                   help="skip CF-0105's re-cut of heterogeneous long shots "
                        "(for before/after timing, not for production indexes)")
    p.add_argument("--verdict-profiles", metavar="DIR",
                   help="CF-0163: directory of recorded verdict profiles "
                        "(<source>_s<NNN>.json). Shots the profile shows a join "
                        "inside are cut there - the joins CLIP dispersion and the "
                        "luma step are blind to. Matched by span, not by name.")
    args = p.parse_args()

    video = Path(args.video)
    runlog.annotate(video=video.stem)   # CF-0107: the source id on this script's event
    profiles = None
    if args.verdict_profiles:
        profiles = verdict_profile.load_dir(args.verdict_profiles, video.stem)
        print(f"  {len(profiles)} verdict profile(s) for {video.stem} "
              f"from {args.verdict_profiles}")
    split_stats = {}
    shots = build_shots(video, args.threshold, args.max_shots,
                        split=not args.no_split, stats=split_stats, profiles=profiles)

    with tempfile.TemporaryDirectory() as tmp:
        frames = extract_frames(video, shots, Path(tmp))
        vectors = embed(frames)
        sheet = contact_sheet(frames, video.with_suffix(".contact.jpg"))
        # CF-0107: extract_full_frames() lives in usability_probe.py, whose
        # bytes are part of the usability fingerprint (CF-0048) - so its loop
        # of one ffmpeg per shot (plus a cropdetect each) is one `child` here,
        # at the call site, rather than per call inside it.
        # CF-0740: the cropdetect each full frame runs is kept and handed to
        # probe_card_text() below - one decode per shot, not two.
        letterbox = LetterboxMemo()
        with runlog.child("ffmpeg", argv=["ffmpeg", "full-frames", str(video)],
                          params={"shots": len(shots)}), shared_letterbox(letterbox):
            full_frames = extract_full_frames(video, shots, Path(tmp))

        n_usability_failed = n_caption_failed = n_card_text_failed = 0
        n_sharpness_failed = 0
        text_hit_rates = {}
        caption_hit_rates = {}
        branding_hit_rates = {}
        for i, shot in enumerate(shots):
            shot["index"] = i
            shot["embedding"] = vectors.get(i)
            # Filled in by whoever reads the contact sheet. Left empty on purpose:
            # an unwritten description is visibly missing, a guessed one is not.
            shot["description"] = ""
            # CF-0106: the timecode that tile (and the embedding) came from,
            # so the description can be read as "about second N", not "about
            # the head". `moment_at` - the mark resolve_anchors cuts from - is
            # deliberately NOT written here: only whoever writes the
            # description can say the described moment is not the head, and
            # stamping every midpoint would just move every cut to the middle
            # (see shot_schema.py).
            shot[shot_schema.TILE_AT] = tile_time(shot)

            # CF-0029: usable_cached/crop_bottom_cached are the shot's own
            # properties, measured once here and reused by resolve_anchors.py
            # as a pre-filter (usability) or a direct substitute for a fresh
            # detect_text_band.py call (captions) - never a silent failure: a
            # probe that raises just leaves that one field off this shot, and
            # every caller already treats a missing cache as "check for real".
            # Both are stamped with the code that took them (CF-0048, CF-0055)
            # so that a later reader can tell a current measurement from one
            # some other version of this pipeline made.
            full_frame = full_frames[i]
            if full_frame is not None:
                try:
                    # CF-0107: one `vision` child per shot; probe_usability()
                    # itself is in the fingerprinted usability_probe.py.
                    with runlog.child("vision", argv=["vision", "usability", str(full_frame)],
                                      step="probe"):
                        shot["usable_cached"] = probe_usability(full_frame)
                except Exception as e:
                    n_usability_failed += 1
                    print(f"  usability probe failed for shot {i}: {e}", file=sys.stderr)
            try:
                caption_cache.measure(shot, video)
            except Exception as e:
                n_caption_failed += 1
                print(f"  caption-band probe failed for shot {i}: {e}", file=sys.stderr)
            # CF-0452: the shot's sharpness (`sharpness_cached`), new material
            # only - the old pool is never re-measured (CF-0410). A field of
            # its own, not a key of usable_cached, so the usability
            # fingerprint (CF-0048) is untouched. One ffmpeg per shot.
            try:
                with runlog.child("ffmpeg", argv=["ffmpeg", "sharpness", str(video)],
                                  step="sharpness"):
                    rec = sharpness.stamp(shot, video, n=sharpness.INDEX_FRAMES)
                if rec.get("value") is None:
                    n_sharpness_failed += 1
            except Exception as e:
                n_sharpness_failed += 1
                print(f"  sharpness probe failed for shot {i}: {e}", file=sys.stderr)
            # CF-0010: flag_cards() needs every shot's text-hit-rate computed
            # before it can decide any single shot's is_card, so this is
            # collected in its own dict rather than written straight onto
            # the shot - a probe that raises just leaves that shot's rate at
            # 0.0 (flag_cards() then falls back to CLIP alone for it, same
            # as before this fix existed).
            try:
                rates = probe_card_text(video, shot["start"], shot["end"],
                                        letterbox=letterbox)
                text_hit_rates[i] = rates["card"]
                caption_hit_rates[i] = rates["caption"]
                shot["card_text_hit_rate"] = round(rates["card"], 3)
                # CF-0093: kept on the shot for the same reason as the card
                # rate - so a reader can see why a high-CLIP shot was not
                # flagged without re-running the probe.
                shot["caption_hit_rate"] = round(rates["caption"], 3)
                # CF-0413: frames whose card text was branding beside a
                # person - kept for the same reason, so a reader can see why
                # a shot full of headline-sized text is not a card.
                branding_hit_rates[i] = rates.get("branding", 0.0)
                shot["branding_hit_rate"] = round(branding_hit_rates[i], 3)
            except Exception as e:
                n_card_text_failed += 1
                print(f"  card-text probe failed for shot {i}: {e}", file=sys.stderr)

        cards = flag_cards(vectors, text_hit_rates, caption_hit_rates, branding_hit_rates)
        for i, shot in enumerate(shots):
            shot["is_card"] = bool(cards.get(i))

    dest = video.with_suffix(".shots.json")
    # CF-0105: the split counters ride along at the top level (every reader
    # takes data["shots"] and ignores the rest) so the pool-wide calibration
    # table - split / sub-shots / still longer than LONG_SHOT_SECONDS - can be
    # summed from the indexes instead of re-run.
    index = {"source": str(video), "model": MODEL, "split_stats": split_stats,
             "shots": shots}
    # CF-0080: the content fingerprint ingest_batch.py deduplicates re-uploads
    # with, kept in the header so the next batch compares against this index
    # without decoding the file again. Loaded from the sidecar when ingest
    # already took it; taken here otherwise. Never a reason to fail an index.
    try:
        index["fingerprint"] = source_fingerprint.load_or_make(video)
    except Exception as e:
        print(f"  fingerprint failed for {video.name}: {e} - dedup will re-take it",
              file=sys.stderr)
    # CF-0663: the source's rights record (licence, credit, origin), as the
    # fetch kept it on the cache entry - so a shot reused from the pool carries
    # its source's credit. Null when the entry has none (a source fetched
    # before CF-0663, or one never fetched through the cache): never invented.
    index[source_rights.SHOTS_KEY] = cached_rights(video)
    # CF-0567: every shot of an own capture carries its kind, so the cam-rip
    # rule (`screen_recording.exempt`) sees it on a bare shot too.
    screen_recording.mark_kind(index, video_id=video.stem,
                               rights=index[source_rights.SHOTS_KEY])
    # CF-0567: and none of its shots is a title card (the card probe's answer
    # stays as `card_detected`).
    shot_usability.exempt_cards(index)
    # Cheap and should never fire - but a time mark outside its shot is the
    # kind of number that silently cuts the wrong clip, so it is refused
    # here, before the file exists, rather than discovered in a render. Runs
    # on the final list - sub-shots from CF-0105's split included, each of
    # which got its own tile_at in the loop above like any other shot.
    shot_schema.require_valid(index, dest)
    # CF-0281: written whole or not at all. On 2026-09-19 the machine went down
    # inside an index of PEiDNOQ_0ms; an unguarded write leaves a file that
    # exists, opens and is not an index, which the next run reads as a cache hit.
    shot_schema.write_index(dest, index)
    n_cards = sum(1 for s_ in shots if s_["is_card"])
    print(f"{len(shots)} shots -> {dest}"
          + (f" ({n_cards} flagged as title/end cards)" if n_cards else ""))
    if split_stats:
        print(f"  split: {split_stats['split']} of {split_stats['probed']} probed long shots "
              f"re-cut into {split_stats['sub_shots']} sub-shots; "
              f"{split_stats['long_left']} shot(s) still >= {LONG_SHOT_SECONDS:g}s")
        if split_stats.get("verdict_seams"):
            print(f"  verdict profile: {split_stats['verdict_seams']} seam(s); "
                  f"{split_stats['verdict_only']} shot(s) cut on them alone, "
                  f"{split_stats['verdict_flagged']} flagged `merged_seams` "
                  f"(too short to cut)")
    if split_stats.get("probe_failed"):
        # CF-0238 / DoD 1.6.2 item 1: a degraded split is said, not implied.
        print(f"  split probe failed for {split_stats['probe_failed']} long shot(s) - "
              f"their bounds are the whole-file detector's only, each flagged "
              f"`split_probe_failed` in the index", file=sys.stderr)
    if sheet:
        print(f"contact sheet -> {sheet}")
    missing = [s["index"] for s in shots if not s["embedding"]]
    if missing:
        print(f"  no frame extracted for shots: {missing}", file=sys.stderr)
    if n_usability_failed:
        print(f"  usability probe failed for {n_usability_failed} shot(s) - "
              f"resolve_anchors.py falls back to its real check for those", file=sys.stderr)
    if n_caption_failed:
        print(f"  caption-band probe failed for {n_caption_failed} shot(s) - "
              f"prepare_clip.py falls back to detecting fresh for those", file=sys.stderr)
    if n_card_text_failed:
        print(f"  card-text probe failed for {n_card_text_failed} shot(s) - "
              f"flag_cards() falls back to CLIP similarity alone for those", file=sys.stderr)
    if n_sharpness_failed:
        print(f"  sharpness not read for {n_sharpness_failed} shot(s) (flat or "
              f"unreadable frames) - low_sharpness is not judged on those",
              file=sys.stderr)


def cached_rights(video):
    """CF-0663: the `rights` of the cache entry for `video`, else None. A cache
    index that does not read is no reason to fail an index."""
    try:
        import fetch_footage
        return source_rights.from_cache(video, fetch_footage.load_index().get("entries"))
    except Exception as e:
        print(f"  rights not read for {Path(video).name}: {e}", file=sys.stderr)
        return None


@runlog.script("footage-indexer", "index", name="index_footage.py")
def cli():
    """CF-0107: start/done|failed around main() (video = the source's stem,
    annotated inside). `main()` stays bare for in-process callers."""
    sys.exit(main())


if __name__ == "__main__":
    cli()

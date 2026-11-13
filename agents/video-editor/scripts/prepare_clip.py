#!/usr/bin/env python3
"""Cut a segment out of cached footage, ready to be montaged.

ffmpeg does the asset preparation; Remotion does the composition. Keeping the
split there means the trimming, cropping and normalising happen once, cheaply,
instead of inside a per-frame browser render.

Burned-in captions are cropped automatically (see detect_text_band.py) unless a
crop is given explicitly - it was a recurring v1 defect to stack our captions
on the source's own.

Usage:
    prepare_clip.py <source.mp4> <start> <duration> <out.mp4>
      [--crop-bottom 0.33 | --auto-crop] [--fps 30]
"""
import argparse
import json
import sys
import re
import tempfile
from pathlib import Path

# CF-0132: every child this cutter starts runs under a common.py ceiling now.
# image_size() answers video_size()'s question with the same ffprobe command it
# already ran - calling it moves nothing into common.py, which is what the note
# on video_size() below is about.
from common import ffmpeg, ffmpeg_stderr, image_size, run_script
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
# CF-0177: `video_script` is this repo's entry-point decorator (the pairing
# per-video events need). It is the same cross-repo import as `video_attempt`
# below, so a shim without it - the indexer's - falls back instead of failing;
# the decorated CLI never runs outside this repo.
try:
    from _runlog import video_script  # noqa: E402
except ImportError:  # pragma: no cover - only the other repo's shim
    video_script = runlog.script
# CF-0159: `video_attempt` is video-editor's own addition to the shim, and this
# module is imported across repositories (agents/footage-indexer). Requiring the
# addition at module level made that import fail with the indexer's own _runlog
# already in sys.modules, so the indexer would not start at all. It is needed on
# the CLI path only, which never runs outside this repo, so it is imported there.


def video_size(path):
    """(width, height) of the first video stream, or None if ffprobe cannot
    say. CF-0062: the frame the caption crop is taken from is reported to the
    gate so it can tell a low-res source from a clip this crop made low-res.

    Kept as this module's own name on purpose: common.py is in the caption
    cache's code fingerprint (CF-0055) and this does not change how a caption
    band is measured, only what is said about applying it. CF-0132: the body
    is now common.image_size(), which runs the same ffprobe command under
    FFPROBE_TIMEOUT_SECONDS and raises rather than answering None on a hang -
    a None here reads as "ffprobe cannot say", and a wedged probe is not
    that."""
    return image_size(path)


# CF-0072: cropdetect's running bounding box only ever widens as it sees more
# frames (reset=0, its default) - a false crop from a near-black title-card
# margin or a dark scene collapses to the true, wider answer only once enough
# frames have let a highlight touch the border. The window used to be
# `min(duration, 4)`, i.e. a function of whatever length the rhythm happened
# to ask THIS clip to be, so the same shot could pass or fail the resolution
# floor depending on a parameter that says nothing about the picture: 3.0s
# read ZZ_urA56pJE shot 50 as crop=892:686 (fails the 720px floor), 3.08s read
# the same shot, same start, as the full 1280:720 frame.
#
# Measured on the ~250 `is_card` shots in shared/footage against a per-source
# long-window reference (see CF-0072's task note for the script and numbers):
# a fixed window is not worse in aggregate than the old duration-tied one, and
# it is the only one of the three candidates the task offered that actually
# closes the reported instability - shots 42/46/50 of ZZ_urA56pJE all needed
# >=5.5s of analysis before the false crop gave way to the source's real,
# stable answer (confirmed bar-free by a 20s scan). Raising `limit` instead
# was measured and rejected: no value fixed those three (limit 16-48 all gave
# the same false crop), and limit>=40 introduced a *new* false crop on shot 50
# that wasn't there at 24. Limiting the fix to `is_card` shots was rejected
# too - 42 and 46 are plain shots, not cards, so a card-only carve-out would
# leave the same instability live for ordinary footage.
LETTERBOX_WINDOW = 6.0


def detect_letterbox(source, start, duration):
    """Find the source's own black bars with ffmpeg's cropdetect.

    Trailers are routinely delivered letterboxed - a 2.39:1 image inside a 16:9
    frame. Those bars are not content: left in, they trip the gate's dead-pixel
    check and they waste the crop budget that the subject needs.

    `duration` is accepted for call-site compatibility but no longer sizes the
    analysis window - see LETTERBOX_WINDOW above for why.
    """
    out = ffmpeg("-ss", str(start), "-i", source,
                 "-t", str(LETTERBOX_WINDOW), "-vf", "cropdetect=limit=24:round=2",
                 "-f", "null", "-",
                 # cropdetect prints its answer at ffmpeg's `info` level, and
                 # the pass chews LETTERBOX_WINDOW seconds however long the
                 # source is - that window is what the ceiling is derived from.
                 log_level="info", media_seconds=LETTERBOX_WINDOW)
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out.stderr)
    if not crops:
        return None
    w, h, x, y = (int(v) for v in crops[-1])
    return f"crop={w}:{h}:{x}:{y}"


def detect_crop(source):
    # SIBLING_SCRIPT_TIMEOUT_SECONDS (run_script's default), not the tighter
    # ASSET_TOOL_TIMEOUT_SECONDS build_render_plan.py gives qc_asset.py:
    # detect_text_band.py asks Vision about several frames of a clip, not one
    # frame, so the gate tools' measured chain is not this script's.
    out = run_script("detect_text_band.py", source, "--json", check=False)
    if out.returncode != 0 or not out.stdout.strip():
        return 0.0
    return json.loads(out.stdout).get("crop_bottom", 0.0)


# CF-0092: the thickest caption band a *live* (non-`is_card`) shot is ever
# cropped for. detect_text_band.py's band is any text that keeps its place
# in the lower 45% of the frame (LOWER_REGION 0.55), and on a studio shot
# that is exactly where the desk's lettering and the name plates sit: run
# 2026-09-03T2037Z read CNBC's "La Biennale di Venezia" backdrop as a
# 37-45% caption band on every W4mvmBXg9Nc shot, took the lower 40% off,
# and left the heads on the bottom edge - static in-scene text, not
# subtitles. A subtitle track does not start that high: on the pool's
# captioned live sources the band tops out at 0.28-0.33 (x9wMFCMXCRE's
# three-line lines, ZZ_urA56pJE s46), and the pool's 176 live bands are
# bimodal around a 0.28-0.34 valley - 110 at 0.07-0.26 (one- and two-line
# subtitles), 64 at 0.36-0.45 (the CNBC desk, 12 of 13 W4mvmBXg9Nc shots;
# UaWVjS5SId4's 18 of 22; trailer title text mid-frame). Above this a
# live shot's band is treated as scene text and left alone - the same
# "text this high is set dressing" judgement LOWER_REGION already makes,
# drawn where a live frame's subtitles actually stop. The ceiling is a
# consumer's rule, not a measurement: it changes what is *done* with
# `crop_bottom_cached`, not the number, so the caption cache stays valid
# (CF-0055's fingerprint deliberately leaves this file out).
#
# Cards are exempt: a card's whole point is dense text, its band is judged
# by CF-0103's own threshold-and-guard, and `--card` says which is which.
MAX_LIVE_CAPTION_CROP = 0.33


def live_caption_crop(crop_bottom, card=False, ceiling=MAX_LIVE_CAPTION_CROP):
    """(crop to apply, crop refused): a live shot's caption crop above the
    ceiling is not applied at all - refused, not capped, because a band
    that thick on a live frame is evidence of scene text, and cutting a
    third of the frame off anyway would still take the faces with it.
    `None` (no crop known) and a card's crop pass through untouched."""
    if crop_bottom is None or card or crop_bottom <= ceiling:
        return crop_bottom, None
    return 0.0, crop_bottom


# CF-0103: the thinnest caption band a *card* (`is_card`) shot keeps. A title
# or end card's bottom lettering is its own design - the cast list under the
# logo, the release date, the studio line - and it is thick: the pool's clean
# cards measure 0.3133 (iJz9yl4ljys s0) to 0.4717 unclamped. Somebody else's
# subtitles burned into a card are thin: one to three lines at the bottom,
# 0.082 (x9wMFCMXCRE s8/s9) to 0.2911 (FfYCVp8hLcg s1). So a card's band
# above this is kept (the card is cut at full height) and a band at or
# below it is cropped like any subtitle. CF-0061's decision, variant 2.
#
# Calibrated on 8 clean cards and the pool's 2 subtitled sources
# (x9wMFCMXCRE, FfYCVp8hLcg): the gap is 0.2911 ... 0.3133, and 0.30 sits in
# it. That is a gap of one subtitle line's height measured on two sources -
# RE-CHECK IT when a THIRD SUBTITLED SOURCE enters the pool
# (scripts/measure_card_bands.py prints the gap and where this constant falls
# in it). Two things this number is not: it is not a judgement on a
# full-screen list (detect_text_band.py's FULLSCREEN_TEXT_LINES guard refuses
# that measurement before it gets here, x9wMFCMXCRE s3), and it is not a
# measurement - like MAX_LIVE_CAPTION_CROP it only changes what is *done*
# with `crop_bottom_cached`, so it does not enter the caption cache's
# fingerprint (CF-0055 leaves this file out on purpose).
CARD_OWN_BAND = 0.30


def card_caption_crop(crop_bottom, floor=CARD_OWN_BAND):
    """(crop to apply, band kept): a card's band thicker than the floor is
    the card's own lettering and is not cropped - kept, and reported so the
    storyboard can say so. `None` (no crop known) and a thin band pass
    through untouched."""
    if crop_bottom is None or crop_bottom <= floor:
        return crop_bottom, None
    return 0.0, crop_bottom


def caption_crop(crop_bottom, card=False):
    """What prepare_clip.py actually does with a caption band, live shot or
    card: (crop to apply, band withheld or None, why). `why` is
    "scene_text" for a live shot's band over MAX_LIVE_CAPTION_CROP (CF-0092)
    and "card_own_band" for a card's band over CARD_OWN_BAND (CF-0103) -
    the two rules never both apply, `card` picks which one is asked."""
    if card:
        applied, kept = card_caption_crop(crop_bottom)
        return applied, kept, "card_own_band" if kept else None
    applied, refused = live_caption_crop(crop_bottom)
    return applied, refused, "scene_text" if refused else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("start", type=float)
    p.add_argument("duration", type=float)
    p.add_argument("output")
    p.add_argument("--crop-bottom", type=float, default=None)
    p.add_argument("--auto-crop", action="store_true")
    p.add_argument("--no-letterbox-crop", action="store_true",
                   help="keep the source's own black bars (they are removed by default)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--card", action="store_true",
                   help="this segment comes from a shot the index flagged as a title/"
                        "end card (CF-0092): its caption band is kept above "
                        f"{CARD_OWN_BAND:.0%} of the frame - that thick, it is the "
                        "card's own lettering (CF-0103) - and cropped below it. "
                        "Without it the band is a live shot's and is refused above "
                        f"{MAX_LIVE_CAPTION_CROP:.0%} of the frame - that thick, it is "
                        "the scene's own text, not subtitles.")
    args = p.parse_args()
    from _runlog import video_attempt  # CF-0159: CLI-only, see the import above
    runlog.annotate(**video_attempt(args.output))  # CF-0107: slug from work/<slug>/clips/..

    crop_bottom = args.crop_bottom

    # Detect on the cut segment, not on the whole source. A trailer that carries
    # a subtitle on only a few shots reads as "no burned-in captions" across the
    # whole file while the one segment we actually took still has a line in it.
    if crop_bottom is None and args.auto_crop:
        with tempfile.TemporaryDirectory() as tmp:
            probe = str(Path(tmp) / "segment.mp4")
            ffmpeg("-ss", str(args.start), "-i", args.source,
                   "-t", str(args.duration), "-an", "-c:v", "libx264",
                   "-crf", "28", "-preset", "ultrafast", probe,
                   check=True, media_seconds=args.duration)
            crop_bottom = detect_crop(probe)
    elif crop_bottom is None:
        crop_bottom = 0.0
    # CF-0092: whichever way the band was found - cached, detected here, or
    # typed - a live shot is not cut for a band thicker than its subtitles
    # could be. Reported below so the caller (resolve_anchors.cut()) can
    # record the refusal on the storyboard instead of it reading as "no
    # captions". CF-0103: and a card is not cut for a band thicker than
    # subtitles could be - that band is the card's own lettering.
    crop_bottom, withheld, why = caption_crop(crop_bottom, args.card)
    refused = withheld if why == "scene_text" else None
    kept = withheld if why == "card_own_band" else None

    vf = []
    # CF-0062: the frame the caption crop is about to be taken from - after
    # the source's own bars are off, before the band is. Reported below so
    # that a gate rejecting the clip on resolution can say whether the
    # source was low-res or this crop made it so; reconstructing it from
    # the cropped height is off by up to 3px because of the floor-to-even
    # below, which is exactly enough to lose a 720px source at a 720px floor.
    before = video_size(args.source)
    if not args.no_letterbox_crop:
        bars = detect_letterbox(args.source, args.start, args.duration)
        if bars:
            vf.append(bars)
            w, h, _, _ = (int(v) for v in bars[len("crop="):].split(":"))
            before = (w, h)
    if crop_bottom > 0:
        vf.append(f"crop=iw:floor(ih*{1 - crop_bottom}/2)*2:0:0")
    vf.append(f"fps={args.fps}")

    result = ffmpeg(
        "-ss", str(args.start), "-i", args.source,
        "-t", str(args.duration),
        "-vf", ",".join(vf),
        "-an",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        args.output,
        # The cut this script exists for: veryfast libx264 over `duration`
        # seconds, which is exactly the pass FFMPEG_SECONDS_PER_MEDIA_SECOND
        # was measured on.
        media_seconds=args.duration)
    if result.returncode != 0:
        print(ffmpeg_stderr(result), file=sys.stderr)
        sys.exit(1)

    print(f"clip -> {args.output} "
          f"({args.duration:.1f}s from {args.start:.1f}s, "
          f"letterbox {'removed' if len(vf) > 1 or (vf and vf[0].startswith('crop') and crop_bottom == 0) else 'none'}, "
          f"captions cropped {crop_bottom:.0%}, crop_bottom={crop_bottom:.4f}, "
          f"frame_before_captions="
          f"{f'{before[0]}x{before[1]}' if before else 'unknown'}"
          + (f", caption_crop_refused={refused:.4f} (live shot, band > "
             f"{MAX_LIVE_CAPTION_CROP:.0%} of the frame reads as scene text, CF-0092)"
             if refused else "")
          + (f", card_band_kept={kept:.4f} (card, band > {CARD_OWN_BAND:.0%} "
             f"of the frame is the card's own lettering, CF-0103)"
             if kept else "") + ")")


@video_script("video-editor", "prepare-clip", name="prepare_clip.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

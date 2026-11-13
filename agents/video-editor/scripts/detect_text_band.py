#!/usr/bin/env python3
"""Find the band of a frame occupied by burned-in captions.

Official clips very often ship with their own subtitles burned into the
picture. v1 stacked our captions on top of them and produced double text; the
workaround was a hand-tuned crop margin per clip, which broke whenever the
source's caption ran to two lines.

Vision's text recogniser locates the text instead of guessing at it. Several
frames are sampled because a caption is not on screen the whole time - a band
is only treated as caption furniture if text keeps landing in it.

The band's thickness is reported unclamped (CF-0103) and refused outright when
the text covers the frame instead of lying in a band - see FULLSCREEN_TEXT_LINES.

Usage: detect_text_band.py <video-or-image> [--samples 8] [--json]
"""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

# CF-0132: the grab is common.py's, under PROBE_FRAME_TIMEOUT_SECONDS - a
# wedged grab now says so instead of quietly contributing no frame to the band.
# CF-0225: grab_frames(), not grab_frame() - the eight frames of one shot come
# out of one decode pass instead of eight independent seeks.
from common import grab_frames, media_duration
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
# module is imported across repositories - agents/footage-indexer/scripts/
# index_footage.py takes sample_text_regions() from here, having already put
# *its* _runlog in sys.modules. Requiring the addition at module level made that
# import fail, so the indexer would not start at all. It is needed on the CLI
# path only, which never runs outside this repo, so it is imported there.

# Quartz/Vision are imported lazily inside text_boxes(), not at module level
# (CF-0029): index_footage.py imports detect_captions() (pure Python, sample
# timing + clustering only) from footage-indexer's own venv, which has no
# pyobjc - a top-level `import Quartz` would make the whole module
# unimportable there, even though that caller never reaches text_boxes()
# directly (it goes through vision_client, which talks to the warm worker).

# A caption sits low in frame. Text higher than this is set dressing, signage
# or a chyron we have no business cropping away.
LOWER_REGION = 0.55
MIN_HIT_RATE = 0.25

# A caption holds the same band frame after frame. Text belonging to the scene -
# a jersey name, a sponsor board, a sign on a wall - moves with whatever it is
# printed on. Without this, a draft-day press conference reads as captioned and
# the detector eats nearly half the frame.
MAX_BAND_SPREAD = 0.06

# CF-0103: a band is only a band if the text *lies* in it. The thickness of
# the lower band is the feature that tells a title card's own bottom lettering
# (thick) from somebody else's burned-in subtitles (thin) - see CARD_OWN_BAND
# in prepare_clip.py - and that feature is meaningless on a frame the text
# covers top to bottom: a full-screen sponsor list or credits roll puts text
# at every height, the lower-region filter above sees only its bottom half,
# and the "band" it reports is just wherever LOWER_REGION happened to slice
# the list. x9wMFCMXCRE shot 3 is exactly that: 24-26 lines of sponsors from
# 0.05 down to 0.95 on six of eight frames, reported as a band from 0.5685.
#
# The band's *top* cannot be the guard. Shot 3's cluster top is 0.5685, and
# the thickest genuine card band in the pool (0.4717 unclamped, i.e. top
# 0.5583 - CF-0061's table) sits *above* it; any line drawn between them
# would also cut real bands. What does separate them is the text above the
# lower region: a card keeps at most a logo or a headline up there (one or
# two lines, iJz9yl4ljys shot 0 has one), a list has a stack of lines. So the
# guard counts distinct text lines whose top is above LOWER_REGION, held in
# at least MIN_HIT_RATE of the frames (the k-th largest per-frame count, the
# same persistence rule the band itself has to meet), and rejects the
# measurement at FULLSCREEN_TEXT_LINES or more. Calibrated on the fixtures
# in tests/fixtures/card_bands/ (real Vision boxes of 47 pool cards,
# 2026-09-06): shot 3 holds 14 such lines, every genuine band - 17 clean
# cards, 30 subtitled ones - holds 0-5 (DSB38pFgM9Y s0 is the 5). 8 is
# closer to the cards than to the list on purpose: a title block of five
# to seven lines is a plausible card, and eight lines held in the upper 55%
# of a frame is a line pitch of 0.07 or less, which is a list. A rejected
# measurement is "no band" (crop_bottom 0.0), which is what the pipeline
# does with any shot that carries no caption furniture.
FULLSCREEN_TEXT_LINES = 8


def merged_lines(boxes):
    """Distinct text lines of one frame: (top, bottom) boxes merged where
    they overlap vertically. Vision splits one line of a list into several
    boxes (a name, a gap, a title) that share a top; counting boxes would
    count a two-column list twice."""
    lines = []
    for top, bottom in sorted(boxes):
        if lines and top <= lines[-1][1]:
            lines[-1] = (lines[-1][0], max(lines[-1][1], bottom))
        else:
            lines.append((top, bottom))
    return lines


def held_in_enough_frames(values, sampled):
    """The value at least MIN_HIT_RATE of `sampled` frames reach: the k-th
    largest of the per-frame values, k = ceil(sampled * MIN_HIT_RATE). One
    frame's worth of scene text does not make a full-screen list, exactly as
    one frame's caption does not make a band."""
    k = max(1, math.ceil(sampled * MIN_HIT_RATE))
    ordered = sorted(values, reverse=True)
    return ordered[k - 1] if len(ordered) >= k else 0


def text_regions(image_path, level=1):
    """CF-0107: one `vision` child event per in-process text scan, probe
    `text_regions` with the recognition level. Silent inside
    vision_worker.py - the client's request child accounts for it there."""
    with runlog.child("vision", argv=["vision", "text_regions", str(image_path)],
                      params={"probe": "text_regions", "level": level}):
        return _text_regions(image_path, level)


def _text_regions(image_path, level=1):
    """Local, in-process Vision text scan for one frame - what actually runs
    inside vision_worker.py, and what vision_client falls back to if the
    worker cannot be reached at all (CF-0029).

    `level` is Vision's own VNRequestTextRecognitionLevel: 1 (fast) reads
    position only and is what caption detection below has always used - it
    does not need to know *what* the text says, only where it sits, and fast
    mode is materially cheaper. 0 (accurate) actually transcribes, at a real
    cost in latency; CF-0010 needs it for title/end-card detection, where
    fast mode's speed-over-accuracy trade produces false positives on
    scene texture (forest/armour) that a real transcription pass does not.

    Returns dicts with width/height (not just the top/bottom text_boxes()
    exposes) - card detection judges text by how much of the frame it
    covers, which needs the box's full extent, not just its vertical band.

    At level=0 (accurate), each dict also carries "text": Vision's top
    transcription candidate for that region. Fast mode leaves it "" -
    position-only recognition never runs the language model a real
    transcription needs. CF-0071's proof gates (attribution_visible,
    text_present) are the first callers that read it; everything that
    predates them only ever looked at the geometry keys, so this is
    additive and does not change their behaviour.
    """
    import Quartz
    import Vision
    p = str(image_path)
    url = Quartz.CFURLCreateFromFileSystemRepresentation(
        None, p.encode("utf-8"), len(p.encode("utf-8")), False)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None or Quartz.CGImageSourceGetCount(src) == 0:
        return []
    image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(level)
    import vision_compute  # CF-0711: CPU on an Intel Mac, never the iGPU
    vision_compute.pin(req)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, {})
    ok, _ = handler.performRequests_error_([req], None)
    if not ok:
        return []

    regions = []
    for obs in (req.results() or []):
        bb = obs.boundingBox()
        # Vision's origin is bottom-left; convert to "fraction from the top".
        top = 1.0 - bb.origin.y - bb.size.height
        text = ""
        if level == 0:
            candidates = obs.topCandidates_(1)
            if candidates:
                text = str(candidates[0].string())
        regions.append({
            "top": top, "bottom": top + bb.size.height,
            "left": bb.origin.x, "width": bb.size.width, "height": bb.size.height,
            "text": text,
        })
    return regions


def text_boxes(image_path):
    """Fast-mode text_regions(), reduced to the (top, bottom) tuples caption
    detection has always used. Kept as its own function - not just an inline
    call - because vision_worker.py's "text_boxes" op and vision_client's
    fallback both still expect exactly this shape (CF-0029 predates level/
    width and nothing downstream of them needs to change for CF-0010)."""
    return [(r["top"], r["bottom"]) for r in text_regions(image_path, level=1)]


def sample_text_boxes(image_path):
    """text_boxes(), routed through the warm Vision worker when one is
    reachable (CF-0029) - this is what the sampling loop below actually
    calls, so every caption probe benefits from Vision staying warm across
    the whole run instead of cold-starting per frame."""
    import vision_client
    return vision_client.text_boxes(image_path)


def sample_text_regions(image_path, level=0):
    """text_regions(), routed through the warm Vision worker (CF-0010) -
    what probe_card_text() in index_footage.py calls for each sampled frame.
    Defaults to accurate mode since that is the only caller today; pass
    level=1 explicitly for a fast-mode caller that still wants area/width."""
    import vision_client
    return vision_client.text_regions(image_path, level=level)


def detect_captions(source, start=0.0, end=None, samples=8):
    """Sample `samples` frames of `source` between `start` and `end` and
    decide whether a persistent caption band is present.

    Generalised (CF-0029) so the same logic can probe either a whole clip
    (start=0, end=None -> the file's own duration, exactly today's CLI
    behaviour) or one shot's span within a longer source video, which is
    what index_footage.py now does once per shot at index time instead of
    resolve_anchors.py re-detecting it on every candidate cut from that shot.
    """
    src = Path(source)
    return {"source": str(src), **band_from_frames(sample_frames(src, start, end, samples))}


def sample_frames(source, start=0.0, end=None, samples=8):
    """The per-frame text boxes detect_captions() decides on: one list of
    (top, bottom) per sampled frame, whole frame, unfiltered - the band is
    read from the lower region, the guard from what is above it. Its own
    function (CF-0103) so measure_card_bands.py can dump exactly what the
    detector saw, and the tests can replay it.

    Which frames (CF-0225 states this explicitly, because the caption cache's
    freshness fingerprint is these bytes - CF-0055/CF-0107): `samples` frames
    of the span [start, end), one decode pass, nominally at
    `start + (k + 0.5) * span / samples` for k in 0..samples-1 - the centres
    of `samples` equal slices, which is the ladder the eight-seek version
    asked for frame by frame. Non-video sources are one frame: the image
    itself.

    The pass is grab_frames() (CF-0155), i.e. one input seek to the first
    moment and an `fps=1/step` filter for the rest, instead of eight
    `-ss t -i src -frames:v 1` seeks that each re-opened and re-decoded the
    file. Measured on three pool shots (2026-09-14) that is 4.78 s -> 0.84 s
    of frame extraction per shot, 5.86 s -> 1.93 s including the Vision scan:
    3.0x, and the decoding, not the recognition, was the bill.

    One thing does move, and it is why this rewrite invalidates the cache
    rather than merely speeding it up: with eight seeks each frame landed on
    its own exact timecode, while one pass lands the *whole ladder* wherever
    ffmpeg's single seek plus the fps filter put its first frame. Measured on
    the same three shots the ladder sits 0.41-0.45 of one step later than the
    nominal one above - spacing unchanged, phase shifted by up to half a slot,
    so the frames are near `(k + 0.9) * span / samples` in the worst case
    seen and the last one still falls inside the shot (0.99 of the span).
    That offset is a property of the source's GOP structure, not a constant
    worth compensating for, and no downstream rule depends on hitting an
    exact moment - the band is whatever text holds its position across the
    sampled frames.

    A span that is not positive yields no frames rather than eight grabs at
    one timecode: `fps=1/0` is not a request ffmpeg can serve, and the only
    real source of a zero span - media_duration() returning 0.0 for a file it
    cannot read - produced no frames on the old path either, because every
    one of its eight seeks failed.
    """
    src = Path(source)
    if src.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        return [list(sample_text_boxes(src))]
    if end is None:
        end = media_duration(src)

    step = (end - start) / samples if samples > 0 else 0.0
    if step <= 0:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        grabbed = grab_frames(src, start + step / 2, step, samples,
                              str(Path(tmp) / "f%02d.png"))
        return [list(sample_text_boxes(frame)) for frame in grabbed]


def band_from_frames(frames):
    """Decide on a caption band from sampled frames' text boxes - the pure
    half of detect_captions(), replayable without Vision or ffmpeg.

    `frames` is a list (one entry per sampled frame) of (top, bottom) boxes
    as fractions of frame height from the top. Returns the dict
    detect_captions() has always returned, minus "source".
    """
    sampled = len(frames)
    hits = [b for boxes in frames for b in boxes if b[0] >= LOWER_REGION]

    # Look for a persistent band rather than demanding every hit agree. A shot
    # can carry a caption *and* a sign on the wall; scattered scene text must not
    # veto a real caption, and a crowd of drifting text must not fake one.
    tops = sorted(h[0] for h in hits)
    best_cluster, best_top = [], None
    for anchor in tops:
        cluster = [t for t in tops if anchor <= t <= anchor + MAX_BAND_SPREAD]
        if len(cluster) > len(best_cluster):
            best_cluster, best_top = cluster, anchor

    cluster_rate = len(best_cluster) / max(1, sampled)

    # CF-0103: how many distinct lines of text stand above the lower region,
    # in enough frames to be furniture rather than a passing sign.
    upper_lines = held_in_enough_frames(
        [sum(1 for line in merged_lines(boxes) if line[0] < LOWER_REGION)
         for boxes in frames], sampled)

    if not hits or cluster_rate < MIN_HIT_RATE:
        return {"captions_found": False, "crop_bottom": 0.0,
                "samples": sampled, "hits": len(hits),
                "largest_band_cluster": len(best_cluster),
                "upper_lines": upper_lines,
                "reason": "no text band holds a steady position across frames - reads as "
                          "scene text (signage, jerseys), not burned-in captions"}

    top = best_top
    if upper_lines >= FULLSCREEN_TEXT_LINES:
        return {"captions_found": False, "crop_bottom": 0.0,
                "samples": sampled, "hits": len(hits),
                "largest_band_cluster": len(best_cluster),
                "fullscreen_text": True, "band_top": round(top, 4),
                "upper_lines": upper_lines,
                "reason": f"text covers the frame ({upper_lines} lines above the lower "
                          f"region, guard at {FULLSCREEN_TEXT_LINES}) rather than lying "
                          f"in a band at the bottom - a list or a credits roll, not "
                          f"captions (CF-0103)"}

    # A little margin below the highest text line, so a two-line caption in
    # a frame we did not sample still falls inside the crop. Unclamped since
    # CF-0103: the old `min(0.45, ...)` saturated exactly on the thick bands
    # of title cards, which are the ones prepare_clip.py's CARD_OWN_BAND now
    # has to tell apart from subtitles by their thickness.
    crop_bottom = round(max(0.0, 1.0 - top) + 0.03, 4)
    return {"captions_found": True,
            "crop_bottom": crop_bottom, "band_top": round(top, 4),
            "samples": sampled, "hits": len(hits),
            "upper_lines": upper_lines}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("--samples", type=int, default=8)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    from _runlog import video_attempt  # CF-0159: CLI-only, see the import above
    runlog.annotate(**video_attempt(args.source))  # CF-0107

    result = detect_captions(args.source, samples=args.samples)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        if result["captions_found"]:
            print(f"burned-in captions from {result['band_top']:.0%} down; "
                  f"crop bottom {result['crop_bottom']:.0%} "
                  f"({result['hits']} hits over {result['samples']} frames)")
        else:
            print(f"no burned-in captions detected "
                  f"({result['hits']} hits over {result['samples']} frames"
                  f"{', ' + result['reason'] if result.get('reason') else ''})")


@video_script("video-editor", "text-band", name="detect_text_band.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

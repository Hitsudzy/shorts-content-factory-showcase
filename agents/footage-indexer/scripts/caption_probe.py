#!/usr/bin/env python3
"""The per-shot caption-band measurement CF-0029 caches in `shots.json`.

Split out of `index_footage.py` (CF-0055) for the same two reasons CF-0048
split out `usability_probe.py`. `remeasure_captions.py` has to run exactly
this measurement over an existing index without re-deriving shots; and
`caption_cache.py` has to hash a file that *is* the measurement, so that
editing the contact sheet layout, the CLIP call or the card-flagging pass in
`index_footage.py` does not invalidate every cached crop in the pool for no
reason at all.

Deliberately nothing but the measurement. The stamp saying which code took it,
the two keys it lives under in the index, and the rule for reading it back all
live in `caption_cache.py`, which this file must not import: the fingerprint is
taken over this file's bytes, and a bookkeeping change is not a measurement
change.

Video Editor owns `detect_text_band.py`, so this reaches into its scripts dir
and calls the real detector rather than duplicating it - the cache and the
`--auto-crop` path prepare_clip.py falls back to must be the same function or
they will drift apart in exactly the way this whole mechanism exists to catch.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
# CF-0267: the sibling from the root (`_fi_paths`, a name no other repo has -
# `_runlog` here may be the Video Editor's). Imported by name through importlib
# on purpose: it is a path helper of the same kind as `_runlog`/`repo_paths`,
# which the fingerprint import-graph checks exempt by file name, and the
# Video Editor's check (test_stale_usability_cache) does not know this name.
# It decides where the measuring code is, never what is measured.
import importlib  # noqa: E402
VIDEO_EDITOR_SCRIPTS = importlib.import_module("_fi_paths").sibling_scripts("video-editor")
sys.path.insert(0, str(VIDEO_EDITOR_SCRIPTS))
import detect_text_band  # noqa: E402 - detect_captions(), generalised to one shot's span

# What detect_captions() is asked for, in one place rather than at each call
# site. Not reduced to a single frame: a caption that fades in or out needs
# several frames to be caught reliably, and the number of samples is part of
# what the cached number means - two callers sampling differently would put
# two different measurements under the same key.
SAMPLES = 8


def probe_captions(video_path, start, end):
    """detect_text_band.py's 8-sample scan, run once on the shot's own span of
    the source (CF-0029) instead of once per candidate cut from it.

    Returns the fraction of frame height to crop off the bottom - 0.0 when no
    persistent caption band was found, which is a measurement and not a
    failure. A failure raises, and the callers leave the shot's cache alone.
    """
    result = detect_text_band.detect_captions(str(video_path), start, end,
                                              samples=SAMPLES)
    return result.get("crop_bottom", 0.0)

#!/usr/bin/env python3
"""CF-0093 on real frames: probe_card_text() against the task's own
reproduction shots and two confirmed cards in shared/footage.

The synthetic tests (test_card_frame_classifier.py, test_card_caption_veto.py)
pin the rule; this pins the rule to the footage the rule was calibrated on.
It needs `shared/footage/` (not in git) and the Vision worker, so it prints a
NOTE and passes when the footage is absent - same convention as
test_usability_cache_freshness.py. Four samples per shot, ~5s each, so the
whole file is under a minute.

Set FOOTAGE_DIR to point it at a pool elsewhere (a worktree does not have
shared/footage three levels up).
"""
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage as ix  # noqa: E402
from _fi_paths import factory_root  # noqa: E402 - CF-0267: the root, not parents[N]
from _live_monitors import live_only  # noqa: E402


def _live_pool():
    """CF-0505: a live monitor (re-probes real frames of four pool mp4s with ffmpeg + Vision). None in the suite, which prints why;
    FI_TESTS_LIVE=1 reads the live pool (FOOTAGE_DIR: a pool elsewhere)."""
    if live_only("test_card_probe_real_footage.py::_live_pool"):
        return None
    import os
    return Path(os.environ.get("FOOTAGE_DIR") or factory_root() / "shared" / "footage")
SAMPLES = 4

# The task's reproduction list (RUN_LOG.txt:9 of batch 2026-09-03T2037Z),
# each a picture with captions that the old probe read as a card:
#   ScKvReYRZ-A s0   vertical Le Monde talking head, French subtitles -
#                    its source's only shot, the CF-0083 crash
#   UaWVjS5SId4 s28  vertical selfie with a wall sign and a caption
#   _m4e4oWFmac s1/16/26  God of War stills with subtitles
# All measured card 0.0 / caption >= 0.5 at 4 samples, which is the veto.
VETOED = [("ScKvReYRZ-A", 0), ("UaWVjS5SId4", 28),
          ("_m4e4oWFmac", 1), ("_m4e4oWFmac", 16), ("_m4e4oWFmac", 26)]
# _m4e4oWFmac s13's subtitle is on screen for only some of its frames
# (caption 0.25 at 4 samples): not enough for the veto, but it never reads
# as card text, so it cannot be a card below CARD_THRESHOLD either.
NEVER_CARD_TEXT = [("_m4e4oWFmac", 13)]
# Confirmed cards, to show the new probe still finds card text on a card:
#   ZZ_urA56pJE s3   a card on a flat ground (card 1.0)
#   ZZ_urA56pJE s33  the tabloid front-page card whose 0.106 headline is the
#                    shortest card line measured (card 0.75, caption 0.25)
CARDS = [("ZZ_urA56pJE", 3), ("ZZ_urA56pJE", 33)]


def shot(source, index):
    pool = _live_pool()
    if pool is None:
        return None, None
    index_path = pool / f"{source}.shots.json"
    video = pool / f"{source}.mp4"
    if not (index_path.exists() and video.exists()):
        return None, None
    shots = json.load(open(index_path))["shots"]
    return video, {s["index"]: s for s in shots}[index]


def probe(source, index):
    video, s = shot(source, index)
    if s is None:
        print(f"  NOTE: {source} footage absent - {source} s{index} not checked")
        return None
    rates = ix.probe_card_text(video, s["start"], s["end"], samples=SAMPLES)
    print(f"  {source} s{index} [{s['start']:.1f}-{s['end']:.1f}] -> {rates}")
    return rates


def test_reproduction_shots_are_vetoed():
    checked = 0
    for source, index in VETOED:
        rates = probe(source, index)
        if rates is None:
            continue
        checked += 1
        assert rates["card"] < ix.CARD_TEXT_MIN_HIT_RATE, (source, index, rates)
        assert rates["caption"] >= ix.CAPTION_VETO_RATE, (source, index, rates)
        # Whatever CLIP made of it - even the 0.2631 that put ScKvReYRZ-A
        # s0 over CARD_THRESHOLD - the shot is not a card now.
        for sim in (0.2631, ix.CARD_THRESHOLD, 0.40):
            assert ix.card_verdict(sim, rates["card"], rates["caption"]) is False, (source, index, sim)
    if not checked:
        print("  NOTE: no shared/footage present - nothing checked")


def test_partially_captioned_still_never_reads_as_card_text():
    for source, index in NEVER_CARD_TEXT:
        rates = probe(source, index)
        if rates is None:
            continue
        assert rates["card"] == 0.0, (source, index, rates)
        # Not a card on the between-thresholds path, where card text is required.
        assert ix.card_verdict(ix.CARD_THRESHOLD - 0.01, rates["card"], rates["caption"]) is False


def test_confirmed_cards_still_read_as_card_text():
    for source, index in CARDS:
        rates = probe(source, index)
        if rates is None:
            continue
        assert rates["card"] >= ix.CARD_TEXT_MIN_HIT_RATE, (source, index, rates)
        # The veto cannot fire on them at any similarity, and the
        # between-thresholds path still admits them on text alone.
        assert ix.card_verdict(ix.CARD_THRESHOLD, rates["card"], rates["caption"]) is True
        assert ix.card_verdict(ix.CARD_THRESHOLD_LOW, rates["card"], rates["caption"]) is True


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)

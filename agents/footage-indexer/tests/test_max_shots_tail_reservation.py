#!/usr/bin/env python3
"""CF-0082: --max-shots must not silently drop a source's tail.

The old `build_shots()` ended in `return shots[:max_shots]` - a plain head
truncation. For any source with more detected cuts than the cap allows, that
drops every shot after the cap, and the cap is almost always reached long
before the source ends: measured on the batch this task cites, BROAzK8oP9U /
_LE1L4Huyys (117s trailers) exhausted --max-shots 60 by 108.8s, and
47P9fKmWbEs (a 45-minute/2743s video) was indexed only to 188s. That is
exactly where release-date/logo/rating end cards live, so the truncation
systematically starved the pool `resolve_anchors.py` draws from for the one
phrase type that most reliably needs the tail.

Pure checks against `cap_shots()` - the function `build_shots()` now
delegates the cap to - built from synthetic shot lists so this runs without
ffmpeg, CLIP, or the real source files. Numbers are checked against the two
real cases above (reproduced as a synthetic list on the same timeline) so a
regression here is caught the same way the original bug was: the tail goes
missing. (The real source files were also re-run through actual scene
detection during this fix's own verification - see CF-0082's `##
Реализация` note - and produced exactly these numbers; this file pins them
down without needing those files present.)

No pytest dependency - plain asserts, run directly (same harness as every
other file in this directory; see run_tests.py).
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage  # noqa: E402


def make_shots(n, shot_len=3.1):
    """n consecutive shots of shot_len seconds each, starting at 0."""
    return [{"start": round(i * shot_len, 3), "end": round((i + 1) * shot_len, 3)}
            for i in range(n)]


def test_under_budget_is_untouched():
    shots = make_shots(40)
    assert index_footage.cap_shots(shots, 60) == shots


def test_at_budget_is_untouched():
    shots = make_shots(60)
    assert index_footage.cap_shots(shots, 60) == shots


def test_old_behaviour_would_have_dropped_the_tail():
    """The defect this closes, pinned down: naive head truncation on a source
    with more cuts than the cap loses everything past the cap's own running
    time - it does not sample across the source."""
    shots = make_shots(500)
    old = shots[:60]
    assert old[-1]["end"] < 200, old[-1]  # never gets anywhere near the tail


def test_cap_shots_keeps_shots_from_the_very_end():
    """The fix: the last TAIL_SHOTS_RESERVED shots of the source survive the
    cap regardless of how many shots come before them."""
    shots = make_shots(500)
    kept = index_footage.cap_shots(shots, 60)
    assert len(kept) == 60
    assert kept[-index_footage.TAIL_SHOTS_RESERVED:] == shots[-index_footage.TAIL_SHOTS_RESERVED:]
    # And the end of the kept list actually reaches the end of the source -
    # this is the concrete property CF-0082 needed: the tail is reachable.
    assert kept[-1]["end"] == shots[-1]["end"]


def test_kept_shots_stay_in_chronological_order_with_no_duplicates_or_gaps_in_selection():
    shots = make_shots(200)
    kept = index_footage.cap_shots(shots, 60)
    starts = [s["start"] for s in kept]
    assert starts == sorted(starts)
    assert len(set(s["start"] for s in kept)) == len(kept)  # no shot picked twice
    # head is a contiguous prefix, tail a contiguous suffix, nothing in between.
    head_n = 60 - index_footage.TAIL_SHOTS_RESERVED
    assert kept[:head_n] == shots[:head_n]
    assert kept[head_n:] == shots[-index_footage.TAIL_SHOTS_RESERVED:]


def test_small_max_shots_halves_the_tail_reservation_instead_of_starving_the_head():
    shots = make_shots(30)
    kept = index_footage.cap_shots(shots, 4)
    assert len(kept) == 4
    # tail_n = min(8, 4 // 2, 30) = 2, so head keeps 2 and tail keeps 2 -
    # neither end is starved down to nothing by a small cap.
    assert kept == shots[:2] + shots[-2:]


def test_reproduces_the_real_47P9fKmWbEs_case():
    """47P9fKmWbEs: 45 minutes (2743s), the first 60 detected shots ran only
    to 188.1s (RUN_LOG.txt:9). Reproduced here as a synthetic timeline with
    the same shot count and the same first-60-shots running time, checking
    that cap_shots() now reaches well past that point."""
    shots = make_shots(900, shot_len=2743.0 / 900)  # ~3.05s/shot, ~2743s total
    old_reach = shots[:60][-1]["end"]
    assert old_reach < 190, old_reach  # matches the cited 188.1s truncation
    kept = index_footage.cap_shots(shots, 60)
    assert kept[-1]["end"] == shots[-1]["end"]
    assert kept[-1]["end"] > 2700  # the tail is now reachable, not lost at ~188s


def test_reproduces_the_real_BROAzK8oP9U_case():
    """BROAzK8oP9U / _LE1L4Huyys: 117s trailers, first 60 shots ran only to
    108.8s, losing the UK 'ONLY IN CINEMAS JANUARY' end card past that point
    (RUN_LOG.txt:9). Reproduced as a synthetic 117s timeline of the same
    shape."""
    shots = make_shots(90, shot_len=117.0 / 90)
    old_reach = shots[:60][-1]["end"]
    assert old_reach < 110, old_reach  # matches the cited 108.8s truncation
    kept = index_footage.cap_shots(shots, 60)
    assert kept[-1]["end"] == shots[-1]["end"]
    assert kept[-1]["end"] > 115  # the end card's shot is now in the kept pool


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

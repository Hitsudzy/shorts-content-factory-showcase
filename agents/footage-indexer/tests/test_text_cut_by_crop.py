#!/usr/bin/env python3
"""CF-0275: the cache can see a 9:16 crop slicing somebody else's text.

The defect, found by watching a finished video (batch
`example-film/2026-09-17T1901Z`, `mormon-wives-comeback.mp4`, 26-31 s): two
split-screen shots of `-3NpUXI5juI` where a commentary host sits in the right
half of a 16:9 frame and an article (shot 9) or a phone screenshot (shot 54)
fills the left half. `cover` to 9:16 keeps a 608-px strip centred on the
host's face, so the article is not removed - it is sliced down the middle, and
the montage shows half-words under our own captions. Every gate read the shot
as fine: `roi_coverage` 0.754/0.661 (the face survives, which is the point),
`card_text_hit_rate` 0.0 (text is half the frame but does not dominate it),
`caption_hit_rate` 1.0 (which only ever moves the bottom edge).

Two kinds of test here, and they check different things:

  the arithmetic - what counts as a severed region, and the difference
    between "measured, this frame has no text" and "this index never asked".
    Synthetic regions, no Vision, no frames, instant.

  the agreement - on the real source this was found on, does the measurement
    put the same shots at the top that a human (and the description model)
    call split-screen? Threshold-free on purpose: picking the number that
    rejects a shot is Video Editor's half of CF-0275, and a threshold asserted
    here would be a second, unowned copy of it. What is asserted is that a
    threshold *exists* - that the split-screen panels and the ordinary
    talking heads of one video do not overlap.

CF-0275 item 3: a description beginning "Split-screen" is a signal, not a
rule - the descriptions are written by a model, and 84 shots of this pool
begin that way while most of them are perfectly usable (a photo in the left
half is not text and is not sliced into half-words). So the signal is used
here only in the direction that can be checked: nothing the measurement ranks
above the ordinary band may be an ordinary shot. The converse - that every
split-screen measures high - is false by construction and is asserted false,
so that a later reader does not "fix" it into a rule.

No pytest dependency - plain asserts, run directly.
"""
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import usability_probe  # noqa: E402
import smart_crop  # noqa: E402 - on sys.path via usability_probe's Video Editor bootstrap

from _fi_paths import factory_root  # noqa: E402 - CF-0267: the root, not parents[N]
from _live_monitors import live_only  # noqa: E402


def _live_pool():
    """CF-0505: a live monitor (re-measures real frames of -3NpUXI5juI.mp4). None in the suite, which prints why;
    FI_TESTS_LIVE=1 reads the live pool (FOOTAGE_DIR: a pool elsewhere)."""
    if live_only("test_text_cut_by_crop.py::_live_pool"):
        return None
    import os
    return Path(os.environ.get("FOOTAGE_DIR") or factory_root() / "shared" / "footage")

# The source the defect was found on. Both classes of shot live in this one
# file, so the comparison below costs one video's frame extraction.
SOURCE = "-3NpUXI5juI"
# Split-screen shots whose left half is an article or a website screenshot -
# text, and sliced. 9 and 54 are the two the viewer actually complained about
# and are mandatory; 4 and 20 are the same construction elsewhere in the same
# video.
PANEL_SHOTS = [4, 9, 20]
# The one the *count* of severed regions cannot see (see below), kept apart
# from the others because it is asserted on differently.
ORPHANED_PANEL_SHOT = 54
# Ordinary shots of the same video: the host talking to camera, some of them
# carrying her own SUBSCRIBE banner. These must stay below the panels.
ORDINARY_SHOTS = [37, 40, 42, 59]

_MEASURED = {}


def frame_size(width=1920, height=1080):
    return {"width": width, "height": height}


def stub_vision(roi, width=1920, height=1080, source="faces"):
    """The shape vision_client.find_roi() returns, enough for the window."""
    return {"source_size": frame_size(width, height), "roi_source": source,
            "roi": {"x": roi[0], "y": roi[1], "width": roi[2], "height": roi[3]},
            "roi_coverage": 1.0, "zoom": 1.0}


def region(left, width, top=0.4, height=0.03):
    return {"left": left, "width": width, "top": top,
            "bottom": top + height, "height": height, "text": ""}


def measure(regions, vision):
    """text_against_window() with Vision's scan replaced by `regions`."""
    original = usability_probe.vision_client.text_regions
    usability_probe.vision_client.text_regions = lambda *a, **k: regions
    try:
        return usability_probe.text_against_window("nowhere.png", vision)
    finally:
        usability_probe.vision_client.text_regions = original


def test_the_window_is_the_one_the_renderer_is_pointed_at():
    """Not the per-frame optimum `analyse()["crop"]` reports - no render ever
    uses that (CF-0155). The window has to be build_render_plan.framing()'s,
    which is smart_crop.focus_point() + delivered_window() at fit: cover.

    Pinned against the real plan of the batch this defect was found on:
    `plan.json` records focus (0.6214, 0.3937) for `-3NpUXI5juI:9` and
    (0.5305, 0.3974) for shot 54, both at fit `cover`, zoom 1.0 - and the
    probe's own live measurement of those frames produced (0.624, 0.3956) and
    (0.5305, 0.3979). This test cannot re-derive Vision's ROI, so it checks
    the other half: given a focus, the strip this measurement judges against
    is the strip the renderer shows.
    """
    vision = stub_vision((795, 301, 806, 382))
    focus = smart_crop.focus_point(vision)
    window = smart_crop.delivered_window((1920, 1080), focus, 1.0, 1080, 1920, "cover")
    x, _, width, height = window
    assert round(width) == 608 and round(height) == 1080, window
    # A region wholly inside that strip is kept; the same region shifted to
    # the left half of the frame is not - which is the whole defect.
    inside = measure([region(x / 1920 + 0.01, 0.1)], vision)
    assert inside["text_outside_crop"] == 0.0, inside
    outside = measure([region(0.05, 0.1)], vision)
    assert outside["text_outside_crop"] == 1.0, outside


def test_only_a_region_the_edge_runs_through_counts_as_cut():
    """A region wholly outside the window is dropped cleanly and reads fine;
    a region the edge crosses is a half-word. The measurement has to tell
    those apart, and must not be fooled by a region that merely touches the
    edge - Vision's box is a little wider than its glyphs, so a line ending
    exactly at the edge routinely reports a fraction of a percent on the far
    side (CUT_EDGE_EPSILON)."""
    vision = stub_vision((795, 301, 806, 382))
    x, _, width, _ = smart_crop.delivered_window(
        (1920, 1080), smart_crop.focus_point(vision), 1.0, 1080, 1920, "cover")
    left_edge = x / 1920

    straddling = region(left_edge - 0.1, 0.2)      # half in, half out
    far_outside = region(0.01, 0.05)               # never shown
    fully_inside = region(left_edge + 0.02, 0.05)  # untouched
    grazing = region(left_edge - 0.0005, 0.1)      # ~1% of it on the far side

    both = measure([straddling, far_outside, fully_inside], vision)
    assert both["text_regions"] == 3
    assert both["text_cut_by_crop"] == round(1 / 3, 4), both
    # In frame area, only the straddling box counts - 0.2 x 0.03 of the frame.
    assert abs(both["text_cut_area"] - 0.006) < 1e-4, both

    assert measure([grazing], vision)["text_cut_by_crop"] == 0.0
    assert measure([far_outside], vision)["text_cut_by_crop"] == 0.0
    assert measure([fully_inside], vision)["text_cut_by_crop"] == 0.0


def test_the_count_share_alone_is_not_the_signal():
    """Why `text_cut_area` sits next to `text_cut_by_crop` rather than being
    left out: a share of a count is meaningless at the counts Vision returns.

    Measured on the real pool - `-3NpUXI5juI` shots 40 and 42 are ordinary
    talking heads whose single recognised region is the host's own SUBSCRIBE
    banner, severed by the crop. One severed region out of one is 1.0, a
    higher number than either shot of the actual defect (0.30 and 0.0). In
    frame area the same banner is 0.017 against shot 9's 0.097. This test
    reproduces that arithmetic on synthetic regions so the reason the second
    number exists cannot be deleted by accident."""
    vision = stub_vision((795, 301, 806, 382))
    x, _, _, _ = smart_crop.delivered_window(
        (1920, 1080), smart_crop.focus_point(vision), 1.0, 1080, 1920, "cover")
    left_edge = x / 1920

    one_banner = measure([region(left_edge - 0.05, 0.1, height=0.02)], vision)
    # Shot 9's shape: six body lines the edge runs through, and a headline
    # column further left that the window misses entirely.
    a_sliced_article = measure(
        [region(left_edge - 0.3, 0.4, top=0.3 + 0.05 * i, height=0.035)
         for i in range(6)]
        + [region(0.05, 0.15, top=0.2 + 0.03 * i, height=0.025)
           for i in range(14)], vision)
    assert one_banner["text_cut_by_crop"] > a_sliced_article["text_cut_by_crop"]
    assert one_banner["text_cut_area"] < a_sliced_article["text_cut_area"]


def test_no_text_is_measured_not_missing():
    """"This frame has no text" and "this index never asked" are opposite
    answers for the reader, and it tells them apart by the key's presence -
    the same rule CF-0047 set for `card_ink_fraction`. So a frame with no
    text still gets `text_regions: 0` and explicit nulls, never a missing
    key."""
    nulls = ("text_area", "text_outside_crop", "text_cut_by_crop",
             "text_cut_area")
    measured = measure([], stub_vision((795, 301, 806, 382)))
    assert measured["text_regions"] == 0
    for key in nulls:
        assert key in measured and measured[key] is None, measured
    # A box with no area at all is not a box Vision is known to return, but
    # dividing by its area in the middle of a four-hour pool remeasure is not
    # how anyone should find out that it can.
    degenerate = measure([region(0.3, 0.0, height=0.0)],
                         stub_vision((795, 301, 806, 382)))
    assert degenerate["text_regions"] == 1
    for key in nulls:
        assert degenerate[key] is None, degenerate


def shots_of_the_reproduction():
    """Live probe of the shots this defect was found on, measured once.

    Slow on purpose (real ffmpeg + real Vision, ~90 s for the eight shots) and
    small on purpose - the same trade `test_usability_cache_freshness.py`
    makes. Returns {} when the pool is absent, and the tests below say so out
    loud rather than passing quietly.
    """
    if _MEASURED:
        return _MEASURED
    pool = _live_pool()
    if pool is None:
        return {}
    index_path, video = pool / f"{SOURCE}.shots.json", pool / f"{SOURCE}.mp4"
    if not (index_path.exists() and video.exists()):
        return {}
    by_index = {s["index"]: s for s in json.load(open(index_path))["shots"]}
    wanted = PANEL_SHOTS + [ORPHANED_PANEL_SHOT] + ORDINARY_SHOTS
    picked = [by_index[i] for i in wanted if i in by_index]
    assert len(picked) == len(wanted), "the index no longer has those shots"
    with tempfile.TemporaryDirectory() as tmp:
        frames = usability_probe.extract_full_frames(video, picked, Path(tmp))
        for shot, frame in zip(picked, frames):
            assert frame is not None, f"no frame extracted for shot {shot['index']}"
            _MEASURED[shot["index"]] = (usability_probe.probe_usability(frame), shot)
    return _MEASURED


def test_the_sliced_panels_measure_above_every_ordinary_shot():
    """The separation Video Editor's threshold needs to exist, on the source
    the defect was found on. Threshold-free: which number rejects a shot is
    CF-0275's other half and is not decided here.

    Shot 54 is asserted separately and deliberately. Its panel is not sliced
    at all - the window's left edge lands just past the end of the phone
    screenshot's text, so `text_cut_area` is 0.0 and the crop keeps two whole
    UI labels ("Share", "Open panel") with 97 % of the panel's text gone. That
    is the same defect to a viewer and a different one to the arithmetic, and
    pretending one number catches both is how a gate ends up trusted for
    something it cannot do.
    """
    measured = shots_of_the_reproduction()
    if not measured:
        print(f"  NOTE: {SOURCE} footage absent - nothing checked")
        return
    panels = {i: measured[i][0] for i in PANEL_SHOTS}
    ordinary = {i: measured[i][0] for i in ORDINARY_SHOTS}
    worst_ordinary = max(m["text_cut_area"] or 0.0 for m in ordinary.values())
    best_panel = min(m["text_cut_area"] for m in panels.values())
    assert best_panel > worst_ordinary, (
        f"the sliced panels no longer stand apart from the ordinary shots of "
        f"{SOURCE}: panels {[(i, m['text_cut_area']) for i, m in panels.items()]} "
        f"vs ordinary {[(i, m['text_cut_area']) for i, m in ordinary.items()]}")

    orphaned = measured[ORPHANED_PANEL_SHOT][0]
    assert orphaned["text_cut_area"] == 0.0, (
        f"shot {ORPHANED_PANEL_SHOT} used to sever nothing - if it does now, "
        f"the frame or the window moved: {orphaned}")
    assert orphaned["text_outside_crop"] > 0.9, orphaned
    assert orphaned["text_regions"] > max(m["text_regions"] for m in ordinary.values()), (
        f"shot {ORPHANED_PANEL_SHOT}'s panel is only visible to the reader as "
        f"a lot of text, almost all of it outside the window: {orphaned}")


def test_the_split_screen_description_agrees_with_the_measurement():
    """CF-0275 item 3, and only in the direction that can be checked.

    A description beginning "Split-screen" is written by a model and cannot be
    a rule. It can be an agreement check: nothing the measurement ranks above
    the ordinary band of this video may be a shot nobody would call a
    split-screen.

    The converse is asserted *false* on purpose. 84 shots of this pool are
    described "Split-screen" and most are fine - a photo in the left half is
    not text, is not sliced into half-words, and must not be rejected. A
    later reader who turns this into "split-screen implies unusable" would
    throw away half the usable footage of a commentary channel.
    """
    measured = shots_of_the_reproduction()
    if not measured:
        print(f"  NOTE: {SOURCE} footage absent - nothing checked")
        return
    worst_ordinary = max(measured[i][0]["text_cut_area"] or 0.0
                         for i in ORDINARY_SHOTS)
    for index in PANEL_SHOTS + [ORPHANED_PANEL_SHOT]:
        description = (measured[index][1].get("description") or "")
        assert description.lower().startswith("split-screen"), (
            f"shot {index} measures as a sliced panel but is not described as "
            f"a split-screen: {description[:80]!r}")
    for index in ORDINARY_SHOTS:
        description = (measured[index][1].get("description") or "")
        assert not description.lower().startswith("split-screen"), (
            f"shot {index} is used here as an ordinary shot: {description[:80]!r}")

    index_path = _live_pool() / f"{SOURCE}.shots.json"
    described = [s for s in json.load(open(index_path))["shots"]
                 if (s.get("description") or "").lower().startswith("split-screen")]
    assert len(described) > len(PANEL_SHOTS) + 1, (
        "this video is mostly split-screens - if it were not, the check below "
        "would prove nothing")
    # Shot 8's left half is an old photograph and shot 31's is two women
    # posing: split-screens by description, nothing sliced into half-words.
    # Whichever of them is measured must stay in the ordinary band, and the
    # signal must therefore not become a rule.
    quiet = [s["index"] for s in described if s["index"] in measured
             and (measured[s["index"]][0]["text_cut_area"] or 0.0) <= worst_ordinary]
    assert ORPHANED_PANEL_SHOT in quiet, (
        "shot 54 is a split-screen the cut measurement is silent about - if "
        "that stops being true, the reader's rule can be simplified")


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

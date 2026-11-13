#!/usr/bin/env python3
"""CF-0105: a long shot whose pictures really differ is re-cut; a static one
is left alone.

One `select='gt(scene,0.25)'` pass glues dark and fast montages into 13-60s
shots (CF-0081: VkxDzRS37JE s2, yaCHj96d1PA s0/s6, M9NWvGZViCg s0,
8JQ45AWDgPE s0). ffmpeg's scene score is a mean absolute pixel difference,
so two dark frames of entirely different content score low - and a fade
through black never produces a single high-scoring frame at all. The
embedding and tile come from the shot's midpoint, resolve_anchors cuts from
its head, so the frame the script is checked against never reaches the
screen.

Three layers here:
  - pure checks on the gate (heterogeneity), the cut placement
    (split_points, skip_black_lead) and the partition, fed the numbers the
    thresholds were calibrated against, so a threshold moved by hand trips
    them the way the real pool would;
  - the cap interaction (CF-0082): sub-shots count against --max-shots and
    the tail reservation survives the second cap;
  - two synthetic sources built with ffmpeg's lavfi generators (no real
    footage needed): two contrasting patterns joined by a fade through
    black, which the 0.25 detector reads as one shot and the split re-cuts;
    and a static 12s shot, which the split leaves as exactly one shot. These
    need ffmpeg and the CLIP weights - both are what the indexer itself
    needs, and the repo venv has them.

No pytest dependency - plain asserts, run directly (same harness as every
other file in this directory; see run_tests.py).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage as ix  # noqa: E402


# --- the gate ---------------------------------------------------------------

def series(segments, fps=25.0, t0=0.0):
    """Per-frame (time, YAVG) for a list of (seconds, luma) plateaus."""
    out, t = [], t0
    for secs, y in segments:
        for _ in range(int(round(secs * fps))):
            out.append((round(t, 4), float(y)))
            t += 1 / fps
    return out


def test_static_one_take_shot_is_homogeneous():
    """W4mvmBXg9Nc s3 (56s press conference) and UaWVjS5SId4 s11 (51s
    reaction cam), as measured: CLIP min-pair 0.933 / 0.958, luma steps
    within 1.5 / 0.3."""
    flat = ix.luma_steps(series([(20, 133.0), (20, 134.5)]))
    assert max(s for _, s in flat) <= 1.5
    v = ix.heterogeneity(0.933, flat)
    assert not v["clip"] and not v["luma"], v
    v = ix.heterogeneity(0.958, ix.luma_steps(series([(51, 79.5)])))
    assert not v["clip"] and not v["luma"], v


def test_dark_montage_is_caught_by_clip_even_with_flat_luma():
    """VkxDzRS37JE s2-style dark montage as CLIP sees it (min-pair 0.441)
    with a luma series that never steps - the gate must not need both."""
    v = ix.heterogeneity(0.441, ix.luma_steps(series([(30, 27.0)])))
    assert v["clip"] and not v["luma"], v


def test_luma_step_catches_what_clip_alone_misses():
    """pOY-Q5DXfcI s0 (Raygun: dancer on a dark stage fading into an
    interview): CLIP min-pair 0.68 sits *above* SPLIT_CLIP_MIN_SIM; the
    18.7 luma step is what flags it. Modelled as a 1s fade through black."""
    fade = [(1 / 25, 40 - i * 24 / 25) for i in range(25)]
    lumas = series([(5, 40.0)] + fade + [(1, 16.0)] + [(5, 42.0)])
    v = ix.heterogeneity(0.68, ix.luma_steps(lumas))
    assert not v["clip"] and v["luma"], v
    assert 12.5 <= v["max_luma_step"] <= 26, v


def test_a_pan_or_exposure_drift_is_not_a_step():
    """W4mvmBXg9Nc s0 (Clooney walking to his seat): exposure drifts
    79 -> 95 -> 104 over 15s with no scene score above 0.05. The first,
    sample-to-sample formulation flagged it (15.4) and put three midpoint
    cuts into a one-take shot; the windowed median step must not."""
    ramp = [(1 / 25, 79 + i * 25 / 250) for i in range(250)]  # +25 over 10s
    v = ix.heterogeneity(0.671, ix.luma_steps(series(ramp + [(5, 104.0)])))
    assert not v["luma"] and not v["clip"], v
    assert v["max_luma_step"] < 3, v


def test_a_single_flash_frame_is_not_a_step():
    lumas = series([(3, 80.0), (1 / 25, 200.0), (3, 80.0)])
    v = ix.heterogeneity(0.9, ix.luma_steps(lumas))
    assert not v["luma"], v
    assert v["max_luma_step"] == 0.0, v


def test_a_hard_cut_between_dark_scenes_is_a_full_step():
    lumas = series([(3, 22.0), (3, 40.0)])
    steps = ix.luma_steps(lumas)
    t, s = max(steps, key=lambda x: x[1])
    assert abs(s - 18.0) < 0.01 and abs(t - 3.0) < 0.05, (t, s)


# --- cut placement ----------------------------------------------------------

def test_scene_cuts_above_the_local_threshold_are_kept():
    scores = [(10.5, 0.05), (12.0, 0.152), (15.0, 0.09), (18.0, 0.24), (20.0, 0.3)]
    cuts = ix.split_points(10.0, 20.0, scores, [])
    assert cuts == [12.0, 18.0], cuts  # 0.05/0.09 below threshold; 20.0 is the end


def test_luma_step_without_a_scene_cut_is_cut_at_its_peak():
    """A fade through black: no frame clears SPLIT_THRESHOLD; the step's
    own peak is the cut."""
    scores = [(13.2, 0.04), (13.9, 0.06), (14.4, 0.035)]
    steps = [(13.0, 4.0), (13.5, 14.0), (13.6, 15.5), (13.7, 14.0), (14.0, 3.0)]
    cuts = ix.split_points(10.0, 20.0, scores, steps)
    assert cuts == [13.6], cuts


def test_luma_step_defers_to_a_scene_cut_within_a_window():
    scores = [(14.2, 0.2), (14.6, 0.05)]
    steps = [(14.0, 20.0), (14.5, 18.0), (16.0, 13.0)]
    cuts = ix.split_points(10.0, 20.0, scores, steps)
    assert cuts == [14.2, 16.0], cuts  # 14.0/14.5 are within 0.5s of the scene cut


def test_black_lead_is_skipped_only_when_the_fade_clears():
    """SJVmeJaS44s s38: the CHRISTMAS card enters as a cut to black at 139.31
    and fades up over 1.6s (YAVG 16 -> 28). The head moves to the first
    frame clearing black; a hard cut onto a bright frame stays put; a scene
    that stays black for longer than a fade keeps its cut."""
    fade = [(139.31 + i * 0.04, 16 + i * 0.3) for i in range(60)]
    moved = ix.skip_black_lead(139.31, fade)
    assert 139.31 < moved <= 140.6, moved
    assert fade[[t for t, _ in fade].index(moved)][1] >= ix.SPLIT_BLACK_CLEAR_YAVG
    bright = [(139.31 + i * 0.04, 90.0) for i in range(60)]
    assert ix.skip_black_lead(139.31, bright) == 139.31
    black = [(139.31 + i * 0.04, 16.0) for i in range(100)]
    assert ix.skip_black_lead(139.31, black) == 139.31


# --- partition --------------------------------------------------------------

def test_partition_never_loses_coverage_or_makes_a_sliver():
    pieces = ix.partition(10.0, 20.0, [12.0, 12.3, 19.7])
    assert pieces == [{"start": 10.0, "end": 12.0}, {"start": 12.0, "end": 20.0}], pieces
    assert pieces[0]["start"] == 10.0 and pieces[-1]["end"] == 20.0
    for a, b in zip(pieces, pieces[1:]):
        assert a["end"] == b["start"]


def test_partition_with_no_cuts_is_the_shot_itself():
    assert ix.partition(10.0, 20.0, []) == [{"start": 10.0, "end": 20.0}]


# --- the cap (CF-0082) -----------------------------------------------------

def test_sub_shots_count_against_the_cap_and_the_tail_survives(monkeypatch=None):
    """build_shots(): cap, split, cap again. A 90-shot source with a long
    head shot that splits into 30 pieces must still end on the source's
    last shots (the end cards CF-0082 rescued), and stay within the cap."""
    total = 117.0
    raw = [(round(i * 1.3, 3), round((i + 1) * 1.3, 3)) for i in range(90)]  # 90 x 1.3 = 117
    raw[0] = (0.0, 40.0)  # one merged 40s head shot, as in 8JQ45AWDgPE s0
    raw = [(a, b) for a, b in raw if a >= 40.0 or a == 0.0]  # 60 shots: at the cap
    assert raw[-1][1] == total

    seen = {}

    def fake_split(path, shots, log=None, profiles=None):
        seen["probed"] = len(shots)
        out = []
        for s in shots:
            if s["end"] - s["start"] >= 30:
                edges = [s["start"] + k * (s["end"] - s["start"]) / 30 for k in range(31)]
                out.extend({"start": round(a, 3), "end": round(b, 3)}
                           for a, b in zip(edges, edges[1:]))
            else:
                out.append(s)
        return out, {"probed": 1, "split": 1, "sub_shots": 30, "long_left": 0}

    saved = (ix.duration, ix.shot_boundaries, ix.split_heterogeneous)
    ix.duration = lambda p: total
    ix.shot_boundaries = lambda p, t, **kw: [b for a, b in raw[:-1]]
    ix.split_heterogeneous = fake_split
    try:
        stats = {}
        shots = ix.build_shots("fake.mp4", 0.25, 60, stats=stats)
    finally:
        ix.duration, ix.shot_boundaries, ix.split_heterogeneous = saved

    assert seen["probed"] <= 60, seen  # the probe only ever sees capped shots
    assert len(shots) == 60, len(shots)
    assert shots[-1]["end"] == total  # tail reserved on the second cap too
    tail = shots[-ix.TAIL_SHOTS_RESERVED:]
    assert [ (s["start"], s["end"]) for s in tail] == raw[-ix.TAIL_SHOTS_RESERVED:], tail
    assert shots[0]["start"] == 0.0 and shots[0]["end"] - shots[0]["start"] < 2  # head was split
    assert stats["sub_shots"] == 30


def test_a_source_under_the_cap_keeps_every_sub_shot():
    saved = (ix.duration, ix.shot_boundaries, ix.split_heterogeneous)
    ix.duration = lambda p: 30.0
    ix.shot_boundaries = lambda p, t, **kw: [10.0]
    ix.split_heterogeneous = lambda p, shots, log=None, profiles=None: (
        [{"start": 0.0, "end": 4.0}, {"start": 4.0, "end": 10.0}, {"start": 10.0, "end": 30.0}],
        {"probed": 2, "split": 1, "sub_shots": 2, "long_left": 1})
    try:
        shots = ix.build_shots("fake.mp4", 0.25, 60)
    finally:
        ix.duration, ix.shot_boundaries, ix.split_heterogeneous = saved
    assert [s["start"] for s in shots] == [0.0, 4.0, 10.0]


# --- caches (item 6) --------------------------------------------------------

def test_split_does_not_change_the_cache_fingerprints():
    """Sub-shots are new shots with no usable_cached/crop_bottom_cached, so
    caption_cache.require_fresh re-measures them on its own. Old indexes
    must not become stale: neither fingerprint hashes this file."""
    import cache_fingerprint
    import caption_cache
    hashed = [Path(p).name for p in (*cache_fingerprint.USABILITY_SOURCES,
                                     *caption_cache.CAPTION_SOURCES)]
    assert "index_footage.py" not in hashed, hashed


# --- synthetic sources ------------------------------------------------------

def make_source(dest, kind):
    """kind='merged': 6s of testsrc2, a 1s fade to black, a 1s fade up into
    6s of colour bars - two contrasting scenes the 0.25 detector reads as
    one shot because nothing ever changes fast. kind='static': 12s of colour
    bars, nothing to split."""
    size = "s=320x180:r=25"
    if kind == "merged":
        cmd = [ix.FFMPEG, "-y", "-nostdin", "-v", "error",
               "-f", "lavfi", "-i", f"testsrc2={size}:d=7",
               "-f", "lavfi", "-i", f"smptebars={size}:d=7",
               "-filter_complex",
               "[0:v]fade=t=out:st=6:d=1[a];[1:v]fade=t=in:st=0:d=1[b];[a][b]concat=n=2:v=1:a=0",
               "-pix_fmt", "yuv420p", str(dest)]
    else:
        cmd = [ix.FFMPEG, "-y", "-nostdin", "-v", "error",
               "-f", "lavfi", "-i", f"smptebars={size}:d=12",
               "-pix_fmt", "yuv420p", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def test_synthetic_fade_through_black_is_one_shot_to_the_detector_and_is_split():
    if not Path(ix.FFMPEG).exists():
        print("  NOTE: ffmpeg absent - nothing checked")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = make_source(Path(tmp) / "merged.mp4", "merged")
        total = ix.duration(src)
        assert 13.5 < total < 14.5, total
        # The fixture is only worth anything if the global pass really
        # glues it: no cut at 0.25 anywhere.
        assert ix.build_shots(src, 0.25, 60, split=False) == [{"start": 0.0, "end": round(total, 3)}]
        stats = {}
        shots = ix.build_shots(src, 0.25, 60, stats=stats)
    assert stats["probed"] == 1 and stats["split"] == 1, stats
    assert len(shots) >= 2, shots
    assert shots[0]["start"] == 0.0 and shots[-1]["end"] == round(total, 3)
    for a, b in zip(shots, shots[1:]):
        assert a["end"] == b["start"], (a, b)
    # Scene A runs to 6.0, black from ~6.8 to ~7.2, scene B from ~8.0. Some
    # cut has to fall inside the transition, and B's own shot must open
    # past the black (skip_black_lead), not on it.
    boundaries = [s["start"] for s in shots[1:]]
    assert any(6.0 <= b <= 8.3 for b in boundaries), boundaries
    assert shots[0]["end"] >= 5.5, shots[0]
    assert stats["long_left"] == 0, stats


def test_synthetic_static_shot_is_probed_and_left_alone():
    if not Path(ix.FFMPEG).exists():
        print("  NOTE: ffmpeg absent - nothing checked")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = make_source(Path(tmp) / "static.mp4", "static")
        total = ix.duration(src)
        stats = {}
        shots = ix.build_shots(src, 0.25, 60, stats=stats)
    assert stats["probed"] == 1 and stats["split"] == 0, stats
    assert shots == [{"start": 0.0, "end": round(total, 3)}], shots
    assert stats["long_left"] == 1, stats


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

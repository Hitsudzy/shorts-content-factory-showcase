#!/usr/bin/env python3
"""CF-0650: a contained clip that barely moves is read like a held one by
`score.thin_picture`.

The rebuild 2026-10-09T1208Z, rink-rivals first pass, block 7: the clip
`UcIvQYYW4PY:4` (1920x1080 shown whole on its blurred frame - 0.317 of the
screen's height) stood nearly still for 3.64 s (frame-to-frame 2.27 grey
levels at 0.5 s steps); the frame judge threw the video out (`thin_strip`)
and `held_screen` had passed it - the rule took a share under 0.25 and a
moving picture. Pinned here: the motion measure (the judge's: grey frames
0.5 s apart, the median of the pairs' mean absolute difference), the rule's
edges on the calibration's numbers (the still clip caught; the operator's
second pick `cFP-IWif0wc:39` at 33.18 and the accepted delver 1427Z clips at
6.98 / 7.19 not; the accepted near-still clips are all under 3 s; held
frames keep their 0.25), that only candidates are measured, the stamp, the
gate's wiring and the re-cut picking the finding up (CF-0648).

Fixtures only - nothing here reads pipeline/; the one decode runs on clips
ffmpeg draws into a temp directory. No pytest dependency.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0650-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import held_screen as hsc  # noqa: E402

# 16:9 shown whole: the rect build_render_plan gives a 1920x1080 clip
RECT_169 = {"blur_fill": {"rect": {"x": 0, "y": 306, "width": 1080, "height": 608},
                          "blur_px": 48, "bg_scale": 1.15, "bg_dim": 0.55}}
RECT_239 = {"blur_fill": {"rect": {"x": 0, "y": 384, "width": 1080, "height": 452}}}
RECT_21 = {"blur_fill": {"rect": {"x": 0, "y": 420, "width": 1080, "height": 540}}}


def asset(name, kind="clip", fit="contain", w=1920, h=1080, presentation=RECT_169):
    a = {"kind": kind, "src": f"/x/clips/{name}.{'mp4' if kind == 'clip' else 'png'}",
         "start_seconds": 0, "fit": fit, "focus": {"x": 0.5, "y": 0.5}, "zoom": 1.0,
         "source_size": {"width": w, "height": h}}
    if presentation:
        a["presentation"] = presentation
    return a


def plan(blocks):
    out, t = [], 0.0
    for sec, a, extra in blocks:
        out.append({"start": round(t, 3), "end": round(t + sec, 3), "asset": a,
                    **(extra or {})})
        t += sec
    return {"blocks": out}


# the calibration's motion per clip name (grey levels)
MOTION = {"ucIv4": 2.27, "cfp39": 33.18, "ucIv5": 19.55, "zlxl31": 6.98,
          "zlxl18": 7.19, "eoe10": 3.73, "lant11": 1.70, "lant2": 0.88,
          "still375": 1.0, "cover": 1.0, "long239": 11.0}


class Motion:
    def __init__(self):
        self.calls = []

    def __call__(self, src, start, seconds):
        name = Path(src).stem if src else None
        self.calls.append(name)
        m = MOTION.get(name)
        return None if m is None else {"motion": m, "max": m * 2, "pairs": 6}


def no_measure(path, target):
    return {}


def calibration():
    """The calibration's nearest pictures on both sides of the rule."""
    return plan([
        (3.64, asset("ucIv4"), None),                              # 0 still 16:9, 3.64 s: thin
        (3.64, asset("cfp39", w=848, h=480), None),                # 1 moving 16:9: no
        (7.17, asset("ucIv5"), None),                              # 2 moving 16:9, long: no
        (3.14, asset("zlxl31"), None),                             # 3 accepted, 6.98: no
        (5.12, asset("zlxl18"), None),                             # 4 accepted, 7.19: no
        (2.47, asset("eoe10", presentation=RECT_21), None),        # 5 accepted near-still 2:1, < 3 s
        (1.61, asset("lant11", presentation=RECT_239), None),      # 6 accepted near-still 2.39:1, < 3 s
        (3.32, asset("eoe12", "still", presentation=RECT_21),
         {"held_frame": True}),                                    # 7 accepted held 2:1: no
        (3.20, asset("still375", w=1620, h=1080, presentation=None), None),  # 8 3:2: over the line
        (4.00, asset("cover", fit="cover", presentation=None), None),        # 9 cover: no candidate
        (3.20, asset("long239", presentation=RECT_239), None),     # 10 thin moving, the old rule
    ])


def test_the_motion_is_the_median_pair_difference_over_the_lit_rows():
    import numpy as np
    rng = np.random.default_rng(3)
    base = rng.integers(40, 200, (108, 192)).astype(np.float32)
    still = np.stack([base + rng.normal(0, 1.0, base.shape) for _ in range(7)])
    got = hsc.frames_motion(still)
    assert got["pairs"] == 6 and got["motion"] < hsc.MOTION_STILL, got
    moving = np.stack([np.roll(base, 6 * k, axis=1) for k in range(7)])
    assert hsc.frames_motion(moving)["motion"] > 3 * hsc.MOTION_STILL
    # one cut in a still clip does not make it move: the median, not the mean
    cut = still.copy()
    cut[4:] = np.roll(cut[4:], 40, axis=1)
    got = hsc.frames_motion(cut)
    assert got["motion"] < hsc.MOTION_STILL < got["max"], got
    # letterbox bars are not picture: the same motion with bars or without
    barred = np.zeros((7, 160, 192), np.float32)
    barred[:, 26:134] = moving
    assert abs(hsc.frames_motion(barred)["motion"]
               - hsc.frames_motion(moving)["motion"]) < 0.01
    assert hsc.frames_motion(still[:1]) is None and hsc.frames_motion(None) is None


def test_the_still_clip_is_thin_and_the_accepted_ones_are_not():
    m = Motion()
    rec = hsc.record(calibration(), measure_fn=no_measure, motion_fn=m)
    got = sorted((f["block"], f["rule"]) for f in rec["findings"])
    assert got == [(0, hsc.RULE_THIN), (10, hsc.RULE_THIN)], got
    f0 = next(f for f in rec["findings"] if f["block"] == 0)
    assert f0["seconds"] == 3.64 and "nearly still" in f0["why"] and "2.27" in f0["why"]
    assert "CF-0650" in f0["why"]
    by = {x["block"]: x for x in rec["thin_moving"]}
    assert by[0]["still"] is True and by[0]["share"] == 0.317
    read = {x["block"]: x["motion"] for x in rec["motion_read"]}
    assert read == {1: 33.18, 2: 19.55, 3: 6.98, 4: 7.19, 8: 1.0}, read
    # the held frame keeps its line: 2:1 held 3.32 s breaks nothing
    assert rec["frames"][0]["share"] == 0.281 and rec["frames"][0]["rules"] == []
    assert rec["thresholds"]["still_share"] == hsc.STILL_SHARE
    assert rec["motion_measured_by"] == hsc.MOTION_BY


def test_the_lines_sit_between_the_calibrations_numbers():
    # 16:9 shown whole (0.316-0.318) is under the still line, 3:2 (0.375) is not
    assert 0.318 < hsc.STILL_SHARE < 0.375
    # the still clip 2.27, the accepted slowest moving one 6.98
    assert 2.27 < hsc.MOTION_STILL < 6.98
    # the accepted near-still clips (east-of-eden 2.47 s, harbourlights 1.61 s) are short
    assert 2.47 < hsc.LONG_SECONDS <= 3.14
    assert hsc.THIN_SHARE == 0.25 and hsc.MOTION_STEP == 0.5


def test_only_the_candidates_are_decoded():
    m = Motion()
    hsc.record(calibration(), measure_fn=no_measure, motion_fn=m)
    # not the short clips, not the cover one, not the held frame
    assert sorted(m.calls) == sorted(["ucIv4", "cfp39", "ucIv5", "zlxl31", "zlxl18",
                                      "still375", "long239"]), m.calls


def test_an_unreadable_clip_is_not_still():
    rec = hsc.record(calibration(), measure_fn=no_measure,
                     motion_fn=lambda src, start, seconds: None)
    assert sorted(f["block"] for f in rec["findings"]) == [10]
    assert hsc.clip_motion("/nonexistent/x.mp4", 0.0, 3.0) is None


def test_stamp_motion_writes_the_holder_and_record_reads_it_back():
    p = calibration()
    m = Motion()
    assert hsc.stamp_motion(p, motion_fn=m) == 7
    rec0 = p["blocks"][0][hsc.MOTION_FIELD]
    assert rec0["measured_by"] == hsc.MOTION_BY and rec0["motion"] == 2.27
    assert rec0["task"] == "CF-0650"
    assert hsc.stamp_motion(p, motion_fn=m) == 0

    def boom(src, start, seconds):
        raise AssertionError("record must read the stamp, not decode again")
    rec = hsc.record(p, measure_fn=no_measure, motion_fn=boom)
    assert sorted(f["block"] for f in rec["findings"]) == [0, 10]


def test_a_still_cut_of_a_sequence_is_read_in_its_own_window():
    cuts = [dict(asset("cfp39", w=848, h=480), seconds=1.2, held_frame=False, shot="c:39"),
            dict(asset("ucIv4"), seconds=3.5, start_seconds=1.0, held_frame=False,
                 shot="u:4")]
    p = plan([(4.7, {"kind": "sequence", "cuts": cuts}, None)])
    seen = []

    def m(src, start, seconds):
        seen.append((Path(src).stem, start, round(seconds, 3)))
        return Motion()(src, start, seconds)
    rec = hsc.record(p, measure_fn=no_measure, motion_fn=m)
    assert seen == [("ucIv4", 1.0, 3.5)], seen
    assert [(f["block"], f["cut"], f["rule"]) for f in rec["findings"]] == \
        [(0, 1, hsc.RULE_THIN)]


def test_the_gate_stamps_the_motion_before_it_reads_the_record():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    gate = src[src.index("\ndef held_screen_gate("):]
    gate = gate[:gate.index("\ndef ", 1)]
    assert gate.index("held_screen.stamp(") < gate.index("held_screen.stamp_motion(") \
        < gate.index("held_screen.record(")


def test_the_recut_picks_the_still_clip_up():
    import held_recut as hr
    rec = hsc.record(calibration(), measure_fn=no_measure, motion_fn=Motion())
    blocks = [{"shot": f"S:{i}"} for i in range(11)]
    story = {"blocks": [{"shot": f"S:{i}", "word_range": [i * 5, i * 5],
                         "length_supply": {"not_reached": 2}} for i in range(11)],
             "excluded_candidates": []}
    todo, _skipped = hr.wanted({"blocks": blocks, "held_screen": rec}, story)
    assert [(t["block"], t["shot"], t["rules"]) for t in todo] == \
        [(0, "S:0", [hsc.RULE_THIN]), (10, "S:10", [hsc.RULE_THIN])], todo


def _draw(path, source):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
                    "-t", "3.6", "-pix_fmt", "yuv420p", str(path)],
                   check=True, capture_output=True, timeout=60)


def test_clip_motion_decodes_the_window_at_half_second_steps():
    if not shutil.which("ffmpeg"):
        print("SKIP: no ffmpeg here")
        return
    with tempfile.TemporaryDirectory() as tmp:
        still, moving = Path(tmp) / "still.mp4", Path(tmp) / "moving.mp4"
        _draw(still, "testsrc2=size=320x180:rate=25,trim=end_frame=1,loop=loop=-1:size=1")
        _draw(moving, "testsrc2=size=320x180:rate=25")
        s = hsc.clip_motion(str(still), 0.0, 3.6)
        mv = hsc.clip_motion(str(moving), 0.0, 3.6)
        assert s is not None and mv is not None, (s, mv)
        assert 5 <= s["pairs"] <= 8, s
        assert s["motion"] < hsc.MOTION_STILL < mv["motion"], (s, mv)
        short = hsc.clip_motion(str(moving), 1.0, 1.0)
        assert short is not None and short["pairs"] <= 2, short


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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

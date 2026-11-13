#!/usr/bin/env python3
"""CF-0536: a split block does not hold a face frozen mid-motion.

delver of `example-film/2026-10-05T0701Z`, rejected 2026-10-05 ("неудачный
стоп кадр на 15с, 21с"): block 3 played three shots of its phrase (4.99 s of
an 11.2 s block) and held the last one - a face in the middle of a movement,
`held_motion` motion 7.43, face 0.087 - for 6.21 s; block 2 held a 1.28 s
shot for 2.46 s. CF-0480 stopped a split at three shots. Pinned here:

* a held frame is the calmest sharp moment of its shot (`held_moment`), and
  the calmest frame of the clip when the shot has no sharpness record
  (`hold_frame` -> `calm_moment`, `held_motion.calmest_moment`);
* a split goes on past three shots while its tail would be held stretched or
  on a frozen face longer than FROZEN_HOLD_MAX_SECONDS (`split_wants_more`,
  `extend_split`), up to STRETCH_SPLIT_MAX_SHOTS_LONG;
* a one-frame block whose one shot would hold a frozen face that long is split
  (`frozen_hold_wanted`);
* a split holds a frame that is not frozen before a sharper frozen one
  (`sharpest_last(frozen_of=)`).

Fixtures only - nothing here reads pipeline/. No pytest dependency.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0536-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402
import held_motion  # noqa: E402
import held_sharpness  # noqa: E402
import still_share  # noqa: E402

TMP = tmp_root("cf0536-")
MEASURE = "CF-0452/crete-tiles-p90/v1"
PUNCT = {"role": "punctuation", "max_shots": 1, "side": None}
SWING = {"role": "swing", "max_shots": 1, "side": "a"}


class _Fresh:
    def is_fresh(self, r):
        return isinstance(r, dict) and r.get("measured_by") == MEASURE


def _with_sharp(fn):
    saved = dict(shot_score._MEMO)
    shot_score._MEMO["sharp"] = _Fresh()
    try:
        return fn()
    finally:
        shot_score._MEMO.clear()
        shot_score._MEMO.update(saved)


def _rec(frames, best_at=1.0, best=0.75):
    return {"measured_by": MEASURE, "value": 0.6, "best": best, "best_at": best_at,
            "frames": frames}


# ------------------------------------------------ where a frame is held

def test_the_held_floor_is_the_plans_held_floor():
    assert shot_score.HELD_SHARP_FLOOR == held_sharpness.FLOOR
    assert ra.FROZEN_HOLD_MAX_SECONDS == still_share.STRETCH_MIN_SECONDS == 2.0
    assert ra.STRETCH_SPLIT_MAX_SHOTS_LONG > ra.STRETCH_SPLIT_MAX_SHOTS


def test_the_calmest_sharp_moment_is_held_not_the_sharpest():
    def go():
        # sharpest at 1.0 mid-motion; 2.0 calm and sharp enough; 3.0 calmer but soft
        u = {"sharpness": _rec([[1.0, 0.75, 9.0], [2.0, 0.60, 1.0], [3.0, 0.50, 0.2]])}
        assert shot_score.held_moment(u) == (2.0, 0.60)
        # a tie on motion: the sharper
        u = {"sharpness": _rec([[1.0, 0.70, 1.0], [2.0, 0.60, 1.0]])}
        assert shot_score.held_moment(u) == (1.0, 0.70)
        # no motion reading ranks behind a measured one
        u = {"sharpness": _rec([[1.0, 0.80, None], [2.0, 0.60, 4.0]])}
        assert shot_score.held_moment(u) == (2.0, 0.60)
        # nothing over the floor, or no samples: best_at, as before (CF-0452)
        u = {"sharpness": _rec([[1.0, 0.50, 9.0], [2.0, 0.40, 1.0]], best_at=1.0, best=0.5)}
        assert shot_score.held_moment(u) == (1.0, 0.5)
        assert shot_score.held_moment({"sharpness": _rec([])}) == (1.0, 0.75)
    _with_sharp(go)


class _Grabs:
    def __init__(self):
        self.grabs = []

    def grab(self, source, at, dest, extra_vf=None):
        self.grabs.append(at)
        Path(dest).write_bytes(b"png")
        return True


def _hold(calm):
    g = _Grabs()
    saved = ra.grab_frame, ra.calm_moment
    ra.grab_frame, ra.calm_moment = g.grab, (lambda clip: calm)
    try:
        used = {"shot": 37, "seconds": 2.74}
        ok = ra.hold_frame(str(TMP / "clip.mp4"), 2.74, TMP / "held.png", used=used)
        return ok, g.grabs, used
    finally:
        ra.grab_frame, ra.calm_moment = saved


def test_without_a_record_the_calmest_frame_of_the_clip_is_held():
    ok, grabs, used = _hold(0.62)
    assert ok and grabs == [0.62], grabs
    assert used["held_calm"] == {"task": "CF-0536", "at": 0.62}
    # unreadable clip: the middle, as before
    ok, grabs, used = _hold(None)
    assert ok and grabs == [1.37] and "held_calm" not in used


def test_calmest_moment_reads_the_still_part_of_the_clip():
    import numpy as np
    rng = np.random.default_rng(0)
    moving = rng.integers(0, 255, size=(10, held_motion.GRID_H, held_motion.GRID_W))
    still = np.full((10, held_motion.GRID_H, held_motion.GRID_W), 120)
    frames = np.concatenate([moving, still, moving]).astype(np.uint8)
    saved = held_motion._decode, held_motion._fps
    held_motion._decode = lambda src, a, b: frames
    held_motion._fps = lambda src: 10.0
    try:
        at = held_motion.calmest_moment("clip.mp4")
    finally:
        held_motion._decode, held_motion._fps = saved
    assert at is not None and 1.0 < at < 2.0, at
    # a clip that moves all through has no calm moment: its middle stays
    held_motion._decode = lambda src, a, b: np.concatenate([moving, moving]).astype(np.uint8)
    try:
        assert held_motion.calmest_moment("clip.mp4") is None
    finally:
        held_motion._decode = saved[0]
    held_motion._decode = lambda src, a, b: frames[:2]
    try:
        assert held_motion.calmest_moment("clip.mp4") is None
    finally:
        held_motion._decode = saved[0]


# ------------------------------------------- when a split takes more shots

def _u(clip, seconds):
    return {"clip": clip, "seconds": seconds, "key": (f"/p/{clip}.mp4", 1), "shot": 1}


def test_a_stretched_tail_wants_the_next_shot():
    # delver 0701Z block 3: 0.98 + 1.27 + 2.74 of 11.2 s - 6.21 s left
    used = [_u("a", 0.98), _u("b", 1.27), _u("c", 2.74)]
    assert ra.split_wants_more(used, 11.2) == "stretched"
    # block 2: 0.83 + 1.04 + 1.28 of 5.61 - 2.46 s on a 1.28 s cut
    assert ra.split_wants_more([_u("a", 0.83), _u("b", 1.04), _u("c", 1.28)], 5.61) \
        == "stretched"
    # a short tail past a short cut is not stretched (2 s line)
    assert ra.split_wants_more([_u("a", 0.5), _u("b", 0.5)], 1.9) is None
    # nothing held
    assert ra.split_wants_more([_u("a", 2.0), _u("b", 2.0)], 4.1) is None


def test_a_tail_held_on_a_frozen_face_wants_the_next_shot():
    used = [_u("a", 1.0), _u("b", 4.0)]          # tail 3.0, only b can hold it
    assert ra.split_wants_more(used, 8.0, lambda u: True) == "frozen"
    assert ra.split_wants_more(used, 8.0, lambda u: False) is None
    assert ra.split_wants_more(used, 8.0) is None
    # one calm cut among the long-enough ones is enough
    used = [_u("a", 3.5), _u("b", 4.0)]          # tail 3.0, both fit
    assert ra.split_wants_more(used, 10.5, lambda u: u["clip"] == "b") is None
    # a frozen tail of 2 s or less may be held
    assert ra.split_wants_more([_u("a", 1.0), _u("b", 4.0)], 6.9, lambda u: True) is None


def _with_frozen(rec, fn):
    saved = ra.frozen_frame
    ra.frozen_frame = lambda u, clips_dir, si, cache: rec
    try:
        return fn()
    finally:
        ra.frozen_frame = saved


def test_a_one_frame_block_holding_a_frozen_face_is_split():
    frozen = {"frozen": True, "motion": 7.43, "face_area": 0.0874}
    u = _u("a", 3.0)
    rec = _with_frozen(frozen, lambda: ra.frozen_hold_wanted(u, 5.5, PUNCT, TMP, 3, {}))
    assert rec and rec["why"] == "frozen_frame" and rec["wanted"] == ra.STRETCH_SPLIT_MAX_SHOTS
    assert rec["frozen_by"] == "CF-0536" and rec["held_motion"]["motion"] == 7.43
    # held 2 s or less, not frozen, a swing: no split
    assert _with_frozen(frozen, lambda: ra.frozen_hold_wanted(u, 4.9, PUNCT, TMP, 3, {})) is None
    assert _with_frozen({"frozen": False}, lambda: ra.frozen_hold_wanted(
        u, 5.5, PUNCT, TMP, 3, {})) is None
    assert _with_frozen(None, lambda: ra.frozen_hold_wanted(u, 5.5, PUNCT, TMP, 3, {})) is None
    assert _with_frozen(frozen, lambda: ra.frozen_hold_wanted(u, 5.5, SWING, TMP, 3, {})) is None


def test_the_frozen_probe_is_measured_once_and_removed():
    calls = []
    saved = ra.hold_frame, ra.held_motion_probe

    def hold(clip, seconds, dest, used=None):
        Path(dest).write_bytes(b"png")
        return True

    def probe(u, png):
        calls.append(png)
        assert Path(png).exists()
        return {"frozen": True, "motion": 7.0, "face_area": 0.05}
    ra.hold_frame, ra.held_motion_probe = hold, probe
    try:
        cache = {}
        u = _u(str(TMP / "a03_x_s037.mp4"), 2.74)
        assert ra.frozen_frame(u, TMP, 3, cache)["frozen"] is True
        assert ra.frozen_frame(u, TMP, 3, cache)["frozen"] is True
    finally:
        ra.hold_frame, ra.held_motion_probe = saved
    assert len(calls) == 1 and not Path(calls[0]).exists()


def test_a_split_holds_a_calm_frame_before_a_sharper_frozen_one():
    values = {"/c/a03_a.mp4": 0.8, "/c/a03_b.mp4": 0.6, "/c/a03_c.mp4": 0.7}
    saved = ra.hold_frame, held_sharpness.frame_value

    def hold(clip, seconds, dest, used=None):
        Path(dest).write_bytes(b"png")
        return True

    def value(path):
        for clip, v in values.items():
            if Path(clip).stem in str(path):
                return v
        return None
    ra.hold_frame, held_sharpness.frame_value = hold, value
    try:
        used = [_u("/c/a03_a.mp4", 3.0), _u("/c/a03_b.mp4", 3.5), _u("/c/a03_c.mp4", 3.2)]
        frozen = lambda u: u["clip"].endswith("a.mp4")   # noqa: E731
        out, _ = ra.sharpest_last(list(used), TMP, 3, need=12.7, frozen_of=frozen)
        assert out[-1]["clip"] == "/c/a03_c.mp4", out
        # a tail of 2 s or less: sharpness alone, as before
        out, _ = ra.sharpest_last(list(used), TMP, 3, need=11.6, frozen_of=frozen)
        assert out[-1]["clip"] == "/c/a03_a.mp4", out
    finally:
        ra.hold_frame, held_sharpness.frame_value = saved


# ------------------------------------------------------------------ wiring

def _loop():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    return src.split("for si, seg in enumerate(segments):")[1]


def test_the_split_goes_on_and_holds_a_calm_frame():
    loop = _loop()
    assert "or frozen_hold_wanted(used[0], need, seg, clips_dir, si," in loop
    assert "used, capped = extend_split(used, capped, rest)" in loop
    body = loop.split("def extend_split(")[1].split("used, capped = stretch_split(")[0]
    assert "split_wants_more(used, need, frozen_of)" in body
    assert "cap=STRETCH_SPLIT_MAX_SHOTS_LONG - len(cur)" in body
    assert 'split["more"]' in body and 'split["more_short"]' in body
    # the phrase's own pool first, then its candidates under the floor - and
    # the block is then priced like one filled under the floor (CF-0433)
    assert "for pool_n, src in enumerate((rest, unders)):" in body
    assert "below_floor_pool(m[\"candidates\"], args.min_score" in body
    assert 'split["more"]["below_floor"]' in body
    after = loop.split('used, capped = stretch_split(used, capped, pool, "match")')[1]
    assert 'if split and (split.get("more") or {}).get("below_floor"):' in after[:2500]
    fill = loop.split("def fill(")[1].split("def stretch_split(")[0]
    assert 'stop = fill_cont.get("stop")' in fill
    assert "if split and (stop(used) if stop else need - covered <= span):" in fill
    assert "sharpest_last(used, clips_dir, si, need,\n" in loop
    assert "frozen_of=frozen_of)" in loop
    assert 'split["held_motion"]' in loop


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
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

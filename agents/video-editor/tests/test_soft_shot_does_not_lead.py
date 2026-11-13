#!/usr/bin/env python3
"""CF-0537: a blurry shot does not lead a one-shot block on length.

delver of `example-film/2026-10-05T0701Z` (2026-10-05, "6секунда выглядит будто
экранка"): block 1 (5.97-11.81 s) was `ZLXL1L0TfsI:15`, a trailer shot of a
1920x786 scope source, `low_sharpness` 0.5099 under the 0.57 floor - warned,
the price unsigned, so its usability score stayed 1.0. It was the only shot of
the phrase long enough for the block, and CF-0517's length lead put it ahead
of every sharp shorter one. Now a blurry shot ranks with the short ones: behind
a sharp shot of its usability score. An order, not a price.

Fixtures only - nothing here reads pipeline/. No pytest dependency.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0537-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import shot_score  # noqa: E402


def _rank(keys, short, lead_floor=None):
    saved = shot_score.rank_key
    shot_score.rank_key = lambda shot, fresh=True, video=None, wide=False: keys[shot]
    try:
        return shot_score.rank(list(keys), lambda c: c, lead=lambda c: c in short,
                               lead_floor=lead_floor)
    finally:
        shot_score.rank_key = saved


def test_a_blurry_long_shot_goes_behind_a_sharp_short_one():
    # delver 0701Z block 1: the blurry long one (blur 2 - 0.5099) led
    keys = {"long_blurry": (0, -1.0, 1.4901), "short_sharp": (0, -1.0, 0.0),
            "short_sharp_2": (0, -1.0, 0.0)}
    got = _rank(keys, short={"short_sharp", "short_sharp_2"})
    assert got == ["short_sharp", "short_sharp_2", "long_blurry"], got


def test_a_sharp_long_shot_still_leads():
    keys = {"short_sharp": (0, -1.0, 0.0), "long_sharp": (0, -0.97, 0.0),
            "long_blurry": (0, -1.0, 1.45)}
    got = _rank(keys, short={"short_sharp"})
    assert got == ["long_sharp", "short_sharp", "long_blurry"], got


def test_among_blurry_ones_the_sharper_then_the_long_one():
    keys = {"short_softer": (0, -1.0, 1.48), "long_soft": (0, -1.0, 1.45),
            "short_soft": (0, -1.0, 1.45)}
    got = _rank(keys, short={"short_softer", "short_soft"})
    assert got == ["long_soft", "short_soft", "short_softer"], got


def test_usability_still_comes_before_sharpness():
    # a priced weak shot is not lifted over a clean blurry one: the usability
    # score orders first (CF-0436), blur only within one score
    keys = {"short_weak": (0, -0.94, 0.0), "long_blurry": (0, -1.0, 1.49)}
    assert _rank(keys, short={"short_weak"}) == ["long_blurry", "short_weak"]


def test_hard_stays_last_and_the_floor_still_holds():
    keys = {"hard_long": (1, -1.0, 0.0), "long_low": (0, -0.4, 0.0),
            "short_clean": (0, -1.0, 0.0)}
    got = _rank(keys, short={"short_clean"}, lead_floor=0.5)
    assert got == ["short_clean", "long_low", "hard_long"], got


def test_without_lead_the_order_is_the_usability_one():
    saved = shot_score.rank_key
    keys = {"a": (0, -1.0, 1.49), "b": (0, -1.0, 0.0)}
    shot_score.rank_key = lambda shot, fresh=True, video=None, wide=False: keys[shot]
    try:
        assert shot_score.rank(["a", "b"], lambda c: c) == ["b", "a"]
    finally:
        shot_score.rank_key = saved


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

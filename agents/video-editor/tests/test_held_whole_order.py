#!/usr/bin/env python3
"""CF-0648: a one-shot block that cannot be split prefers motion to a frame
held for the whole block - and the anchor's own short shot to a soft clip.

delver 2026-10-08T1824Z, block 7 (2.91 s, a swing): the walk put the short
wIM1PDRvKSE:55 (1.17 s, "two older men in suits") ahead of every long-enough
candidate, because those were all `low_sharpness` (CF-0537: a blurry shot
does not lead on length) - and the block held a still for 2.91 s, x1.78, the
user's "мыльный растянутый кадр". The operator's re-cuts ended on
wIM1PDRvKSE:21, whose description IS the phrase. What these tests hold:

  * `shot_score.rank(mild_from=)`: a long shot blurry at or above the line
    keeps its lead over the short ones, behind every sharp long one; under
    the line CF-0537 stands;
  * `shot_score.rank(pinned=)`: the anchor's own short shot goes ahead of
    the short ones and a mildly blurry long one, never ahead of a sharp long
    one, and only while it is itself usable and not blurry;
  * `split_reachable()`: a swing, an `even` block, a block too short to
    split and --no-stretch-split hold a short shot whole; an ordered
    one-frame block does not;
  * `rank_by_usability(held_whole=)` on the delver block 7 replica: the
    anchor first, then the mildly blurry long shot; without it the old order;
  * `length_supply` says which runs walked held-whole and how many
    candidates were never reached.

No network, no pool: the indexer's modules are stubs (CF-0613).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0648-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402

MEASURE = "CF-0452/crete-tiles-p90/v1"
FLOOR = 0.57
TMP = tmp_root("cf0648-")
VIDEO = TMP / "vid00000000.mp4"
VIDEO.write_bytes(b"not a real video - nothing opens it")
IDX = "/idx/v.shots.json"


def rec(value):
    return {"task": "CF-0452", "measured_by": MEASURE, "value": value,
            "best": value, "best_at": 0.5, "motion": 0.0,
            "motion_excused": False, "frames": [], "floor": FLOOR}


class StubSharpness:
    RULE = "low_sharpness"
    MIN_SHARPNESS = FLOOR

    def __init__(self):
        self.calls = []

    def is_fresh(self, r):
        return isinstance(r, dict) and r.get("measured_by") == MEASURE

    def verdict(self, r, held=False):
        v = r["best"] if held else r["value"]
        return None if v >= FLOOR else {"rule": self.RULE, "value": v,
                                        "floor": FLOOR, "held": held}

    def of_shot(self, shot, video):
        self.calls.append(shot["index"])
        return rec(0.9)

    def mode(self):
        return {"mode": "warn", "price": 3, "price_key": "score.low_sharpness",
                "signed": False}


class StubUsability:
    def of(self, shot, measurements=True):
        return shot.get("u") or {"soft": [], "hard": [], "warn": [], "score": 1.0}

    def prices(self):
        return {"low_framing": 3, "low_brightness": 3, "low_resolution": 2,
                "off_topic_shot": 4}


def install():
    shot_score._MEMO.clear()
    shot_score._MEMO["sharp"] = StubSharpness()
    shot_score._MEMO["mod"] = StubUsability()
    shot_score._SHARP.clear()
    shot_score._SHARP_RUN["probes"] = 0


def shot(n, seconds, sharp=0.9, description="", u=None):
    s = {"index": n, "start": 0.0, "end": seconds, "description": description,
         "sharpness_cached": rec(sharp)}
    if u:
        s["u"] = u
    return s


def cand(n, seconds, score=0.25):
    return {"shot": n, "index": IDX, "source": str(VIDEO), "start": 0.0,
            "end": seconds, "score": score, "card": False}


def lut_of(shots):
    return {(IDX, s["index"]): s for s in shots}


def ranked(pool, shots, need, **kw):
    install()
    lut = lut_of(shots)
    return [c["shot"] for c in shot_score.rank(
        pool, lambda c: lut.get((c["index"], c["shot"])),
        video_of=lambda c: c["source"],
        lead=lambda c: ra.available_seconds(c) < need,
        lead_floor=ra.LENGTH_LEAD_MIN_USABILITY, **kw)]


# --- shot_score.rank: the two tiers ----------------------------------------

def test_without_the_new_keys_a_blurry_long_shot_ranks_with_the_short_ones():
    shots = [shot(0, 1.2), shot(1, 9.0, sharp=0.56)]
    pool = [cand(0, 1.2, 0.27), cand(1, 9.0, 0.23)]
    assert ranked(pool, shots, 3.0) == [0, 1]           # CF-0537 as it was


def test_a_mildly_blurry_long_shot_keeps_its_lead_where_the_block_holds_whole():
    shots = [shot(0, 1.2), shot(1, 9.0, sharp=0.56), shot(2, 9.0, sharp=0.51)]
    pool = [cand(0, 1.2, 0.27), cand(1, 9.0, 0.23), cand(2, 9.0, 0.24)]
    got = ranked(pool, shots, 3.0, mild_from=ra.MILD_BLUR_LEAD_FROM)
    # 0.56 leads; 0.51 (the user's "экранка" line) still ranks with the short
    assert got[0] == 1 and got.index(0) < got.index(2), got


def test_a_sharp_long_shot_stays_ahead_of_the_mild_one_and_of_the_anchor():
    shots = [shot(0, 1.2, description="a man speaks"), shot(1, 9.0, sharp=0.56),
             shot(2, 9.0)]
    pool = [cand(0, 1.2, 0.30), cand(1, 9.0, 0.25), cand(2, 9.0, 0.22)]
    got = ranked(pool, shots, 3.0, mild_from=ra.MILD_BLUR_LEAD_FROM,
                 pinned=lambda c: c["shot"] == 0)
    assert got == [2, 0, 1], got


def test_the_anchor_short_goes_ahead_of_other_shorts_and_a_mild_long_one():
    shots = [shot(0, 1.2), shot(1, 1.5), shot(2, 9.0, sharp=0.56)]
    pool = [cand(0, 1.2, 0.27), cand(1, 1.5, 0.24), cand(2, 9.0, 0.23)]
    got = ranked(pool, shots, 3.0, mild_from=ra.MILD_BLUR_LEAD_FROM,
                 pinned=lambda c: c["shot"] == 1)
    assert got == [1, 2, 0], got


def test_without_a_mild_long_shot_the_anchor_does_not_jump_the_short_ones():
    # east-of-eden 0701Z block 11 (accepted): no long shot to prefer, so the
    # held frame keeps the picture the old order gave it
    weak = {"soft": [{"rule": "low_framing", "price": 3}], "hard": [], "warn": [],
            "score": 0.97}
    shots = [shot(0, 1.7), shot(1, 1.1, u=weak), shot(2, 9.0, sharp=0.51)]
    pool = [cand(0, 1.7, 0.22), cand(1, 1.1, 0.32), cand(2, 9.0, 0.23)]
    kw = dict(mild_from=ra.MILD_BLUR_LEAD_FROM, pinned=lambda c: c["shot"] == 1)
    assert ranked(pool, shots, 2.55, **kw) == ranked(pool, shots, 2.55)
    assert ranked(pool, shots, 2.55, **kw)[0] == 0


def test_a_blurry_or_unusable_anchor_is_not_pinned():
    weak = {"soft": [{"rule": "off_topic_shot", "price": 60}], "hard": [],
            "warn": [], "score": 0.4}
    shots = [shot(0, 1.2), shot(1, 1.5, sharp=0.45), shot(2, 1.4, u=weak)]
    pool = [cand(0, 1.2, 0.27), cand(1, 1.5, 0.24), cand(2, 1.4, 0.23)]
    got = ranked(pool, shots, 3.0, mild_from=ra.MILD_BLUR_LEAD_FROM,
                 pinned=lambda c: c["shot"] in (1, 2))
    assert got[0] == 0, got


# --- the resolver's side ---------------------------------------------------

def test_anchor_match_reads_the_phrase_in_the_description():
    phrase = "a man in a decorated military uniform speaks"
    assert ra.anchor_match(phrase, "a man in a decorated military uniform speaks") == 1.0
    host = ("Close-up of a man with brown hair in a black v-neck sweater smiling "
            "broadly, seated in a grey armchair")
    assert ra.anchor_match(phrase, host) < ra.ANCHOR_MATCH
    assert ra.anchor_match(phrase, None) == 0.0 and ra.anchor_match("", "x") == 0.0


def test_split_reachable_follows_the_stretch_split_conditions():
    ordered = {"max_shots": 1, "role": "beat"}
    assert ra.split_reachable(ordered, 3.0) is True
    assert ra.split_reachable(ordered, 1.8) is False          # too short to split
    assert ra.split_reachable({"max_shots": 1, "role": "swing"}, 3.0) is False
    assert ra.split_reachable({"max_shots": None, "role": "beat"}, 3.0) is False
    assert ra.split_reachable({"max_shots": 2, "role": "beat"}, 3.0) is False
    assert ra.split_reachable(ordered, 3.0,
                              SimpleNamespace(no_stretch_split=True)) is False


def delver_block_7():
    """The 1824Z pool of block 7 as the walk met it (the retired ones out)."""
    phrase = "a man in a decorated military uniform speaks"
    lf = {"soft": [{"rule": "low_framing", "price": 3}], "hard": [], "warn": [],
          "score": 0.97}
    shots = [shot(55, 1.168, description="two older men in suits pass each other"),
             shot(22, 1.519, description="an older man in a suit looks up in alarm"),
             shot(43, 1.268, description="a man at a lectern"),
             shot(21, 1.468, description=phrase),
             shot(9, 13.314, sharp=0.5335, description="a man in a black sweater smiling"),
             shot(7, 5.939, sharp=0.5104, description="a man in a black sweater talking"),
             shot(27, 4.571, sharp=0.5098, description="a man with a popcorn bucket"),
             shot(40, 11.027, sharp=0.5666, u=lf,
                  description="a man in a maroon robe stands in a room")]
    pool = [cand(55, 1.168, 0.2688), cand(22, 1.519, 0.2641), cand(43, 1.268, 0.2424),
            cand(21, 1.468, 0.2421), cand(9, 13.314, 0.22), cand(7, 5.939, 0.2243),
            cand(27, 4.571, 0.2279), cand(40, 11.027, 0.2318)]
    return phrase, shots, pool


def test_delver_block_7_takes_the_anchor_where_it_used_to_take_shot_55():
    phrase, shots, pool = delver_block_7()
    install()
    lut = lut_of(shots)
    old = [c["shot"] for c in ra.rank_by_usability(pool, lut, need=2.91)]
    assert old[0] == 55, old
    install()
    new = [c["shot"] for c in ra.rank_by_usability(pool, lut, need=2.91, phrase=phrase,
                                                   held_whole=True)]
    # the anchor, then the mildly blurry long shot, then the rest
    assert new[:2] == [21, 40], new
    assert new.index(9) > new.index(55), new


def test_held_whole_without_a_phrase_or_need_changes_nothing():
    phrase, shots, pool = delver_block_7()
    lut = lut_of(shots)
    install()
    base = [c["shot"] for c in ra.rank_by_usability(pool, lut)]
    install()
    assert [c["shot"] for c in ra.rank_by_usability(pool, lut, phrase=phrase,
                                                    held_whole=True)] == base


def test_length_supply_records_held_whole_and_the_unreached():
    a, b, c = cand(1, 9.0), cand(2, 1.0), cand(3, 1.2)
    run = ra.fill_run([a, b, c], [(a, 0)], [{"reason": "retired"}],
                      length_first=True, held_whole=True)
    run2 = ra.fill_run([b], [(b, 1)], [{"reason": "retired"}], length_first=True)
    got = ra.length_supply(3.0, [run, run2])
    assert got["held_whole"] == [True, False], got
    assert got["not_reached"] == 1, got           # shot 3 only; 2 was cut in run 2


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e!r}")
    shot_score._MEMO.clear()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

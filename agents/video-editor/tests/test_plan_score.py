#!/usr/bin/env python3
"""CF-0433: the pace floor, the hold band and the similarity floor are prices.

The grill of 2026-09-29 ("делать из того, что дают") and the score model of
CF-0432 (`shared/score/score.py`, prices in `shared/gate-prices.json`). The
repeat of `example-film/2026-09-28T1126Z` lost four topics on three rules that
refused outright:

  vanguards-endgame-encore  9.64 blocks/min against explainer's floor 15.39
  backrooms                7.18 blocks/min against the same floor
  primetime                block 13 at 2.75 s, 0.25 s over list's 2.5 s top
  (a fourth)               block 0 at 12.3 s under a 3.5 s band

and `0929Z` had dozens of candidates at 0.144-0.218 against the 0.22 floor.
Pinned here: the findings each rule produces, their prices on the live table,
the rounding that decides the edge, and that a missing model never refuses.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0433-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import _score  # noqa: E402
import rhythm  # noqa: E402

FD = rhythm.BAND_MODE_FLOOR_DRAWN


def rate(measured, mode=FD, lo=15.39, hi=47.88):
    return {"code": rhythm.PATTERN_BLOCK_RATE_OUTSIDE_BAND, "pattern_id": "explainer",
            "mode": mode, "measured": measured, "band_min": lo, "band_max": hi}


def blocks(durations, key=("start", "end")):
    out, t = [], 0.0
    for d in durations:
        out.append({key[0]: round(t, 3), key[1]: round(t + d, 3)})
        t += d
    return out


def pattern(top, mode="drawn", pid="list"):
    return {"pattern_id": pid, "parameters": {
        "key_frame_hold_seconds": {"mode": mode, "min": 1.0, "max": top}}}


def test_the_rule_names_are_the_price_tables():
    assert rhythm.SCORE_PACE_BELOW_FLOOR == _score.RULE_PACE_BELOW_FLOOR
    assert rhythm.SCORE_HOLD_BAND_EXCEEDED == _score.RULE_HOLD_BAND_EXCEEDED
    mod = _score.module()
    if mod is None:
        print(f"SKIP: {_score.error()}")
        return
    model = mod.load_model()
    for rule in _score.STAGE_RULES:
        assert model["rules"][rule]["mode"] == "penalty", rule


def test_a_pace_under_the_floor_is_priced_per_started_block_per_minute():
    [f] = rhythm.pace_findings([rate(9.64)])      # vanguards: 5.75 short
    assert f["units"] == 6 and f["rule"] == "score.pace_below_floor", f
    [f] = rhythm.pace_findings([rate(15.38)])     # one hundredth short
    assert f["units"] == 1, f
    assert rhythm.pace_findings([rate(15.389548)]) == [], (
        "amc-leawood-films is where 15.39 came from - the grid decides")
    assert rhythm.pace_findings([rate(60.0)]) == []
    assert rhythm.pace_findings([rate(4.46, mode="emergent")]) == []
    assert rhythm.pace_findings([rate(4.46, mode="drawn")])[0]["units"] == 11


def test_a_pace_under_the_floor_no_longer_refuses_and_a_drawn_top_still_does():
    assert not rhythm.cadence_band_refuses(rate(7.18))
    assert not rhythm.cadence_band_refuses(rate(7.18, mode="drawn"))
    assert rhythm.cadence_band_refuses(rate(60.0, mode="drawn"))
    count_over = {"code": rhythm.PATTERN_BLOCK_COUNT_OUTSIDE_BAND, "mode": "drawn",
                  "measured": 38, "band_min": 12, "band_max": 24}
    assert rhythm.cadence_band_refuses(count_over)


def test_a_block_over_the_hold_band_is_one_finding_per_block():
    # primetime's shape: block 1 at 2.75 s against a 2.5 s top
    found = rhythm.hold_band_findings(blocks([2.0, 2.75, 2.5, 12.3]), pattern(2.5))
    assert [f["where"]["block"] for f in found] == [1, 3], found
    assert all(f["rule"] == "score.hold_band_exceeded" and f["units"] == 1 for f in found)
    assert found[0]["hook"] is True and found[1]["hook"] is False
    # a storyboard's _start/_end work the same
    sb = blocks([2.0, 2.75], key=("_start", "_end"))
    assert len(rhythm.hold_band_findings(sb, pattern(2.5))) == 1
    # half a frame of tolerance, the same comparison as every other reader
    tol = rhythm.HOLD_BAND_TOP_TOLERANCE_SECONDS
    assert rhythm.hold_band_findings(blocks([2.5 + tol]), pattern(2.5)) == []
    # an emergent envelope orders nothing (CF-0039)
    assert rhythm.hold_band_findings(blocks([12.3]), pattern(3.5, "emergent")) == []
    assert rhythm.hold_band_findings(blocks([12.3]), None) == []


def test_the_1126z_losses_price_out_inside_the_threshold():
    """The four refusals of the repeat, priced on the live table: none of
    them alone - nor all three rules at their caps together - reaches N."""
    if _score.module() is None:
        print(f"SKIP: {_score.error()}")
        return
    vanguards = _score.score_block(rhythm.pace_findings([rate(9.64)]))
    assert vanguards["score"] == 88 and vanguards["passed"], vanguards
    backrooms = _score.score_block(rhythm.pace_findings([rate(7.18)]))
    assert backrooms["score"] == 88 and backrooms["log"][0]["capped"], backrooms
    primetime = _score.score_block(
        rhythm.hold_band_findings(blocks([2.0] * 13 + [2.75]), pattern(2.5)))
    assert primetime["score"] == 98, primetime
    worst = _score.score_block(
        rhythm.pace_findings([rate(1.0)])
        + rhythm.hold_band_findings(blocks([12.0] * 8), pattern(3.5))
        + [_score.finding(_score.RULE_LOW_SIMILARITY, {"block": i}) for i in range(8)])
    assert worst["score"] == 100 - 12 - 10 - 15 == 63 and worst["passed"], worst
    assert not _score.refuses(worst)


def test_under_the_threshold_refuses_and_a_missing_model_never_does():
    if _score.module() is None:
        print(f"SKIP: {_score.error()}")
        return
    ledger = _score.module().read_ledger()
    ledger = dict(ledger, score=dict(ledger["score"], threshold=95,
                                     tiers={"S": 97, "A": 95}))
    block = _score.score_block(rhythm.pace_findings([rate(9.64)]), ledger)
    assert block["score"] == 88 and block["passed"] is False, block
    assert _score.refuses(block)
    assert any("pace_below_floor" in line for line in _score.lines(block))
    assert not _score.refuses({"findings": [], "score": None, "passed": None,
                               "error": "no root"})
    assert not _score.refuses(None)


def test_an_unknown_rule_is_an_error_not_a_free_pass():
    mod = _score.module()
    if mod is None:
        print(f"SKIP: {_score.error()}")
        return
    try:
        _score.score_block([_score.finding("score.no_such_rule")])
    except mod.ScoreModelError:
        return
    raise AssertionError("an unknown rule was scored")


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

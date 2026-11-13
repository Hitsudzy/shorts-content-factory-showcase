#!/usr/bin/env python3
"""CF-0119: no half of a contrast pair is longer than one anchor and its hold.

CF-0050 gave the sides of `alternate` to the script - one block per crossing of
the axis - which makes the length of a block a property of the writing. CF-0057
measured the consequence: a run of one side longer than the drawn
`key_frame_hold_seconds` is almost always delivered as a frame that stops
moving (15.17 s on the one real alternate plan), and at contrast's 1.5-3.5 s
band a run of two anchors leaves the band on 7 scripts out of 11, of three on
11 out of 11. CF-0074 chose to fix that in the writing, so the check runs on
the script: `patterns/validate_patterns.py check_contrast_pairs`, before there
is a montage to blame.

What these tests pin, beyond the two cases the task asked for:

* the band is read, never written. Its seconds come from the parameter
  `contrast.side_length.seconds_from` names - the order's drawn value, or the
  pattern band's maximum when nothing was drawn - and its words from the
  channel's `narration_budget.words_per_second`. A doctored copy of either
  number moves the verdict, which is the only way to know the check is not
  quietly carrying literals.
* a finding is machine-readable and names the pair and the side, because the
  answer to the writer is "rewrite that half", not "the script is long".
* the CLI exits non-zero on a batch that has to come back, the same path
  `check-orders` uses for an order that does not fit the voice (CF-0086).

Cross-agent for the same reason as test_pattern_vocabulary.py: Content
Researcher writes the pairs and runs the check, Video Editor cuts on them.
"""
import json
import math
import sys
import tempfile
from _tmproot import tmp_root   # noqa: E402  (CF-0378: this file's temp trees go at exit)
_TMP = tmp_root("contrast-pairs-test-")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))

import validate_patterns as vp  # noqa: E402

# CF-0633: the module holds no channel; these tests read example-film's numbers.
CHANNEL = "example-film"
WORDS_PER_SECOND, WORDS_PER_SECOND_SOURCE = vp.narration_rate(CHANNEL)
WORDS_PER_SECOND_MIN, WORDS_PER_SECOND_MAX = vp.rate_envelope(vp.load_narration_budget(CHANNEL))

CONTRAST = vp.load_patterns()["contrast"]
# Seven words: about 1.9 s at the 3.66 w/s CF-0279 re-measured, inside the band
# at any drawn hold from 1.92 s up (it was 1.81 s at CF-0261's 3.88, 2.32 s at
# the 3.02 of CF-0188 and 2.6 s at the 2.75 before it), and inside the size the
# writing instruction asks for (10-12 words is the top of the band - 12 at this
# rate, 13 at the last one; the instruction is written as a band, so only its
# prose had to follow).
HALF_A = "The trailer promised a whole new city"
HALF_B = "The episode shows one alley and scaffolding"


def _pair(a=HALF_A, b=HALF_B):
    return {"a": a, "b": b}


def _script(pairs, hold=3.5, pattern_id="contrast"):
    """A synthetic 03-content-researcher.json script, cut down to what the
    pair check reads: the order (for the drawn hold) and the declared sides."""
    return {
        "script_id": "t-script1",
        "topic_id": "t-topic1",
        "hook": "Two versions of one finale",
        "scene_direction": {"description": "trailer plates against episode plates"},
        "commentary": " ".join(str(h) for p in pairs for h in (p.get("a"), p.get("b"))
                               if isinstance(h, str)),
        "payoff": "The gap is the point",
        "pattern": {
            "pattern_id": pattern_id,
            "rhythm_id": "alternate",
            "assigned_by": "rotation",
            "parameters": {
                "block_count": 12,
                "key_frame_hold_seconds": hold,
                "opening_block": "hook_over_footage",
                "acceleration_to_payoff": {"enabled": False, "strength": None},
            },
            "sides": {
                "axis": "what the trailer promised against what the episode shipped",
                "a": "trailer plates, wide and graded blue",
                "b": "episode plates, interiors on the same set",
                "pairs": pairs,
            },
        },
    }


def _findings(report, kind=vp.PAIR_TOO_LONG):
    return [f for f in report["findings"] if f["kind"] == kind]


# --------------------------------------------------------------------------
# the two cases CF-0119 asked for
# --------------------------------------------------------------------------

def test_a_half_of_three_anchors_is_rejected_with_the_pair_number_and_the_side():
    """The defect CF-0057 measured, spelled the way a writer spells it: the
    commentary stays on side b for three anchors before crossing back."""
    pairs = [_pair(), _pair(), _pair()]
    pairs[1] = {"a": HALF_A,
                "b": ["The episode shows one alley and scaffolding",
                      "The second set never appears at all",
                      "The cast list is three names shorter"]}
    report = vp.check_contrast_pairs(_script(pairs), CONTRAST, channel=CHANNEL)
    assert report["verdict"] == "return_for_rewrite", report
    found = _findings(report)
    assert len(found) == 1, report["findings"]
    f = found[0]
    assert f["pair"] == 2 and f["side"] == "b", f
    assert f["anchors"] == 3, f
    assert f["words"] == 21, f
    assert f["seconds"] == round(21 / WORDS_PER_SECOND, 2), f
    assert f["band"]["max_anchors_per_side"] == 1, f
    # The finding carries the whole band, so a reader of the batch file does
    # not have to re-derive what the half was measured against.
    assert f["band"]["max_seconds"] == 3.5 and f["band"]["seconds_source"] == "order"
    assert "pair 2 side b" in f["note"], f["note"]
    # The other two pairs are measured all the same - the report is a
    # measurement of every half, not a stop at the first defect.
    assert [r["pair"] for r in report["pairs"]] == [1, 2, 3]
    assert report["pairs"][0]["a"]["anchors"] == 1


def test_one_anchor_a_side_passes():
    report = vp.check_contrast_pairs(_script([_pair(), _pair(), _pair(), _pair()]),
                                     CONTRAST, channel=CHANNEL)
    assert report["verdict"] == "ok", report
    assert report["findings"] == []
    assert len(report["pairs"]) == 4
    for row in report["pairs"]:
        for side in ("a", "b"):
            assert row[side]["anchors"] == 1 and row[side]["words"] == 7


# --------------------------------------------------------------------------
# the band is read from the pattern and the channel, not written here
# --------------------------------------------------------------------------

def test_the_seconds_ceiling_is_the_hold_the_order_drew():
    """Same pairs, two orders. The band follows `key_frame_hold_seconds`
    because that is the number a rhythm shortfall is measured against - a
    script whose order drew 1.5 s has less room for a half than one that drew
    3.5 s, and the check says so instead of averaging the band."""
    # The half is sized to sit just over the looser hold at the channel's
    # current rate, because "just over" is the case worth pinning. The rate has
    # been re-measured three times under this test - 3.02 -> 3.88 (CF-0261) ->
    # 3.66 (CF-0279) - and the word count that buys "just over" moves with it:
    # 11 words then, 14 at 3.88, and 13 now (12 words read in 3.28 s and fit
    # under a 3.5 s hold, 13 read in 3.55 s and do not). The case is the same
    # one; only its size is the rate's.
    half = ("One two three four five six seven eight nine ten eleven twelve "
            "thirteen")  # 13 words, 3.55s
    pairs = [{"a": half, "b": half}]
    loose = vp.check_contrast_pairs(_script(pairs, hold=3.5), CONTRAST, channel=CHANNEL)
    tight = vp.check_contrast_pairs(_script(pairs, hold=1.5), CONTRAST, channel=CHANNEL)
    assert loose["verdict"] == "return_for_rewrite"  # 3.55s over 3.5s, barely
    assert tight["verdict"] == "return_for_rewrite"
    assert loose["band"]["max_seconds"] == 3.5 and tight["band"]["max_seconds"] == 1.5
    assert loose["band"]["max_words"] == 12 and tight["band"]["max_words"] == 5
    # And the same words pass under the looser hold once they are one anchor
    # of ordinary length.
    ok = vp.check_contrast_pairs(_script([_pair()], hold=3.5), CONTRAST, channel=CHANNEL)
    assert ok["verdict"] == "ok", ok
    assert vp.check_contrast_pairs(_script([_pair()], hold=1.5),
                                   CONTRAST, channel=CHANNEL)["verdict"] == "return_for_rewrite"


def test_an_undrawn_hold_falls_back_to_the_pattern_band_maximum():
    script = _script([_pair()])
    script["pattern"]["parameters"]["key_frame_hold_seconds"] = None
    report = vp.check_contrast_pairs(script, CONTRAST, channel=CHANNEL)
    assert report["band"]["seconds_source"] == "pattern"
    assert report["band"]["max_seconds"] == \
        CONTRAST["parameters"]["key_frame_hold_seconds"]["max"]


def test_moving_the_hold_band_in_a_copy_of_the_pattern_moves_the_verdict():
    """The pattern file is the band's only home. A doctored copy with a
    shorter hold rejects a half the real pattern accepts, which is what
    "not hard-coded" has to mean."""
    script = _script([_pair()])
    script["pattern"]["parameters"]["key_frame_hold_seconds"] = None  # use the band
    assert vp.check_contrast_pairs(script, CONTRAST, channel=CHANNEL)["verdict"] == "ok"
    shrunk = json.loads(json.dumps(CONTRAST))
    shrunk["parameters"]["key_frame_hold_seconds"]["max"] = 1.0
    report = vp.check_contrast_pairs(script, shrunk, channel=CHANNEL)
    assert report["verdict"] == "return_for_rewrite", report
    assert report["band"]["max_seconds"] == 1.0
    assert _findings(report)[0]["seconds"] > 1.0


def test_moving_the_anchor_ceiling_in_a_copy_moves_the_verdict():
    # Two anchors of ordinary length are also over the seconds ceiling, which
    # would prove nothing about the anchor rule - so these two are short
    # enough (4 words together, 1.45s) that only the anchor count is in play.
    two = {"a": ["Trailer promised", "City promised"], "b": "Episode shows one alley"}
    assert vp.check_contrast_pairs(_script([two]), CONTRAST, channel=CHANNEL)["verdict"] == \
        "return_for_rewrite"
    relaxed = json.loads(json.dumps(CONTRAST))
    relaxed["side_length"]["max_anchors_per_side"] = 2
    assert vp.check_contrast_pairs(_script([two]), relaxed, channel=CHANNEL)["verdict"] == "ok"




# --------------------------------------------------------------------------
# what the check refuses to do, and what it leaves alone
# --------------------------------------------------------------------------

def test_a_script_on_another_pattern_is_not_checked():
    report = vp.check_contrast_pairs(_script([_pair()], pattern_id="list"), CONTRAST, channel=CHANNEL)
    assert report["verdict"] == "not_applicable"
    assert report["findings"] == [] and report["band"] is None


def test_a_contrast_script_with_no_declared_pairs_is_reported_not_rewritten():
    """Batches written before CF-0119 carry no `pairs`. Nothing was measured,
    so nothing is rejected - but the report says so rather than saying ok."""
    script = _script([_pair()])
    del script["pattern"]["sides"]["pairs"]
    report = vp.check_contrast_pairs(script, CONTRAST, channel=CHANNEL)
    assert report["verdict"] == "no_pairs_declared", report
    assert report["findings"] == []
    assert "pattern.sides.pairs" in report["reason"]


def test_a_pair_with_a_missing_half_is_a_finding_of_its_own():
    report = vp.check_contrast_pairs(_script([_pair(), {"a": HALF_A}]), CONTRAST, channel=CHANNEL)
    assert report["verdict"] == "return_for_rewrite"
    unmatched = _findings(report, vp.PAIR_UNMATCHED)
    assert len(unmatched) == 1 and unmatched[0]["pair"] == 2
    assert unmatched[0]["side"] == "b" and unmatched[0]["anchors"] == 0


def test_a_pattern_without_a_side_length_block_raises_rather_than_guessing():
    bare = json.loads(json.dumps(CONTRAST))
    del bare[vp.SIDE_LENGTH_KEY]
    try:
        vp.check_contrast_pairs(_script([_pair()]), bare, channel=CHANNEL)
    except ValueError as e:
        assert vp.SIDE_LENGTH_KEY in str(e) and "CF-0119" in str(e), e
    else:
        raise AssertionError("a pattern with no band must not be checked against a default")


def test_a_broken_side_length_block_is_a_vocabulary_error():
    """The band is validated where every other pattern field is - one bad key
    is caught by `validate_patterns.py` rather than by the check at write
    time."""
    assert vp.validate_side_length(CONTRAST) == []
    for mutation, needle in (
            ({"max_anchors_per_side": 0}, "max_anchors_per_side"),
            ({"seconds_from": "block_countt"}, "seconds_from"),
            ({"seconds_from": "opening_block"}, "seconds_from"),
            ({"words_per_second_from": ""}, "words_per_second_from"),
            ({"max_side_seconds": 3.5}, "unknown key"),
    ):
        broken = json.loads(json.dumps(CONTRAST))
        broken[vp.SIDE_LENGTH_KEY].update(mutation)
        errs = vp.validate_side_length(broken)
        assert errs and any(needle in e for e in errs), (mutation, errs)
        assert vp.validate_pattern(broken, stem="contrast"), mutation


# --------------------------------------------------------------------------
# the pattern file itself, and the CLI the writer runs
# --------------------------------------------------------------------------

def test_the_written_rule_and_the_band_agree_with_each_other():
    """The 10-12 words in the writing instruction are not a third number: they
    are the top of the hold band at the channel's rate. If either moves and
    the prose does not, this fails - which is what CF-0261 caught it doing when
    the rate went 3.02 -> 3.88 and the prose still said 8-10, and what CF-0279
    caught again when the rate came back to 3.66."""
    band = vp.side_length_band(CONTRAST, channel=CHANNEL)
    assert 10 <= band["max_words"] <= 12, band
    prose = " ".join(CONTRAST["writing_instruction"])
    assert "10-12 words" in prose
    assert "one anchor" in prose
    assert "check-pairs" in prose  # the writer is told how to run it
    assert vp.SIDE_LENGTH_KEY in prose
    assert CONTRAST[vp.SIDE_LENGTH_KEY]["seconds_from"] == "key_frame_hold_seconds"


def test_the_vocabulary_still_validates_with_the_new_block():
    assert vp.validate_vocabulary() == []
    assert vp.main([]) == 0


def test_check_pairs_cli_returns_the_batch_for_rewrite_with_a_non_zero_exit():
    """The same path an order that does not fit the voice comes back on
    (`check-orders`, CF-0086): exit 1 means the script goes back to the
    writer, exit 2 means the command was called wrong."""
    tmp = Path(tempfile.mkdtemp(dir=_TMP))
    long_half = {"a": [HALF_A, HALF_B, HALF_A], "b": HALF_B}
    bad = tmp / "bad.json"
    bad.write_text(json.dumps({"batch_id": "x", "channel": CHANNEL,
                               "scripts": [_script([_pair(), long_half])]}))
    good = tmp / "good.json"
    good.write_text(json.dumps({"batch_id": "x", "channel": CHANNEL, "scripts": [_script([_pair()] * 3)]}))
    other = tmp / "other.json"
    other.write_text(json.dumps({"batch_id": "x", "channel": CHANNEL,
                                 "scripts": [_script([_pair()], pattern_id="list")]}))
    assert vp.main(["check-pairs", str(bad)]) == 1
    assert vp.main(["check-pairs", str(good)]) == 0
    assert vp.main(["check-pairs", str(other)]) == 0
    assert vp.main(["check-pairs"]) == 2
    rows = list(vp.check_pairs(json.loads(bad.read_text())["scripts"], channel=CHANNEL))
    assert [r["verdict"] for r in rows] == ["return_for_rewrite"]


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

#!/usr/bin/env python3
"""CF-0446: the rotation checks the pair against the expected speech at issue.

AHS, batch 2026-09-27T0929Z: list on staccato, a 1.8 s block ceiling, ~49 s of
speech - at least 28 blocks whatever the anchors, against a band of 12-24. The
user's decision of 2026-10-02: the pair is checked against the channel's
expected speech length when it is issued, and a pair that does not fit is
passed over for the next one in rotation order; with nothing fitting, the
closest pair is issued with an explicit speech target, never a refusal.

Run: python3 tests/test_rotation_speech_fit.py
"""

import json
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "rotation"))
sys.path.insert(0, str(ROOT / "shared"))

import validate_patterns as vp  # noqa: E402
import rotate  # noqa: E402
from ledger import Ledger, ledger_path  # noqa: E402

CHANNEL = "example-film"
AHS_SPEECH = 49.0
AHS_CEILING = 1.8


@contextmanager
def scratch():
    d = Path(tempfile.mkdtemp(prefix="cf0446-"))
    (d / "pipeline").mkdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@contextmanager
def list_hold_ceiling(ceiling):
    """The live vocabulary with `list`'s hold band topped at `ceiling` - the
    AHS ceiling made the pair's own, so the rotation sees what the draw saw."""
    real = vp.load_patterns

    def patched():
        pats = json.loads(json.dumps(real()))
        pats["list"]["parameters"]["key_frame_hold_seconds"]["max"] = ceiling
        pats["list"]["parameters"]["key_frame_hold_seconds"]["min"] = min(
            pats["list"]["parameters"]["key_frame_hold_seconds"]["min"], ceiling)
        return pats

    vp.load_patterns = patched
    try:
        yield
    finally:
        vp.load_patterns = real


@contextmanager
def channel_speech(seconds=None, allowed=None):
    """The live channel, with its target set so the narration is `seconds`."""
    real = rotate.load_channel

    def patched(channel):
        cfg = real(channel)
        if seconds is not None:
            budget = cfg["narration_budget"]
            budget["target_total_seconds"] = seconds + vp.tail_seconds(budget)
        if allowed is not None:
            cfg["patterns"]["allowed_pattern_ids"] = list(allowed)
        return cfg

    rotate.load_channel = patched
    try:
        yield
    finally:
        rotate.load_channel = real


def test_ahs_0929z_staccato_under_1_8s_on_49s_does_not_fit_12_24():
    r = rotate.speech_fits_band(AHS_SPEECH, AHS_CEILING, (12, 24))
    assert r["min_blocks"] == 28 and not r["fits"], r
    pattern = json.loads(json.dumps(vp.load_patterns()["list"]))
    pattern["parameters"]["key_frame_hold_seconds"]["max"] = AHS_CEILING
    fit = rotate.pair_speech_fit(pattern, "staccato", AHS_SPEECH, vp.load_rhythms(),
                                 words_per_second=3.66)
    assert fit["checked"] and not fit["fits"], fit
    assert fit["min_blocks"] == 28 and fit["block_count_band"] == [12, 24], fit
    # 24 blocks x 1.8 s: the speech the pair can carry, and in words.
    assert fit["speech_target_seconds"] == 43.2, fit
    assert fit["speech_target_words"] == 158, fit
    assert "28 blocks" in fit["reason"], fit["reason"]


def test_a_compatible_pair_fits_and_names_the_hold_floor_the_ahs_draw_went_under():
    assert rotate.speech_fits_band(AHS_SPEECH, 2.5, (12, 24))["fits"]
    fit = rotate.pair_speech_fit(vp.load_patterns()["list"], "staccato", AHS_SPEECH,
                                 vp.load_rhythms())
    assert fit["checked"] and fit["fits"], fit
    assert fit["min_blocks"] == 20, fit
    # ceil(49 / 24) on the 0.01 grid: a hold drawn under it - AHS drew 1.8 -
    # needs more than 24 blocks.
    assert fit["hold_floor_seconds"] == 2.05, fit
    assert AHS_CEILING < fit["hold_floor_seconds"]


def test_a_speech_too_short_for_the_band_floor_does_not_fit():
    r = rotate.speech_fits_band(5.0, 2.5, (12, 24))
    assert r["max_blocks"] == 8 and not r["fits"], r


def test_patterns_without_a_count_band_are_not_checked_rather_than_passed_silently():
    fit = rotate.pair_speech_fit(vp.load_patterns()["explainer"], "even", AHS_SPEECH)
    assert fit["fits"] and not fit["checked"], fit


def test_every_live_pair_fits_the_live_channel_at_the_top_of_its_bands():
    cfg = rotate.load_channel(CHANNEL)
    speech, _ = rotate.expected_speech_seconds(cfg)
    assert abs(speech - cfg["narration_budget"]["narration_seconds"]) < 0.01, speech
    pairs, _ = rotate.eligible_pairs(cfg)
    fits = rotate._speech_fits(cfg, pairs, speech)
    assert all(f["fits"] for f in fits.values()), [f for f in fits.values() if not f["fits"]]


def test_assign_passes_over_the_unfit_pairs_and_keeps_the_rest_even():
    """With list topped at 1.8 s, both list pairs are unfit on 49 s; the
    rotation turns over the six that fit, never issues a list pair, keeps
    the no-repeat window on what it turns over, and spreads evenly over it."""
    with channel_speech(AHS_SPEECH), list_hold_ceiling(AHS_CEILING), scratch() as d:
        scripts = [f"s{i:02d}" for i in range(1, 25)]
        out = rotate.assign(CHANNEL, "B", scripts, ledger_dir=d, pipeline_dir=d / "pipeline")
        issued = [(a["pattern_id"], a["rhythm_id"]) for a in out]
        assert not [p for p in issued if p[0] == "list"], issued
        counts = Counter(issued)
        assert len(counts) == 6 and max(counts.values()) - min(counts.values()) <= 1, counts
        for i in range(len(issued) - 3):
            assert len(set(issued[i:i + 4])) == 4, (i, issued[i:i + 4])
        skipped = [s for a in out for s in a["speech_fit"]["skipped"]]
        assert skipped, "the rotation over every pair reaches a list pair at least once"
        assert all(s["pair"].startswith("list/") and "28 blocks" in s["reason"]
                   for s in skipped), skipped
        assert all(not a["speech_fit"]["no_compatible_pair"] for a in out)
        assert all(a["speech_fit"]["fits"] for a in out)
        # Idempotent re-run still reports the fit of the standing pair.
        again = rotate.assign(CHANNEL, "B", scripts[:1], ledger_dir=d,
                              pipeline_dir=d / "pipeline")
        assert again[0]["speech_fit"]["fits"] and not again[0]["reassigned"], again
        assert len(Ledger(ledger_path(CHANNEL, d)).rows()) == 24


def test_assign_with_no_fitting_pair_issues_the_closest_with_a_speech_target():
    """Only list admitted, both pairs unfit: issued anyway (not refused), and
    the assignment carries the speech length the script has to be written to."""
    with channel_speech(AHS_SPEECH, allowed=["list"]), list_hold_ceiling(AHS_CEILING), \
            scratch() as d:
        out = rotate.assign(CHANNEL, "B", ["s1", "s2", "s3"], ledger_dir=d,
                            pipeline_dir=d / "pipeline")
        assert all(a["assigned"] for a in out), out
        for a in out:
            sf = a["speech_fit"]
            assert sf["no_compatible_pair"] and not sf["fits"], sf
            assert sf["speech_target_seconds"] == 43.2, sf
            assert "43.2s" in sf["note"], sf["note"]
        # The rotation still alternates between the two.
        assert len({(a["pattern_id"], a["rhythm_id"]) for a in out[:2]}) == 2, out


def test_the_replacement_after_an_upheld_rejection_is_not_an_unfit_pair():
    """CF-0446 part 2: `reject` draws its replacement through the same speech
    check as `assign`. Four scripts assigned with list unfit, the last one
    refused: the rotation over every pair would hand back an unused list pair
    (precondition, asserted), the speech-checked draw hands back a pair that
    fits, says what it walked past, and the ledger row is that pair."""
    with channel_speech(AHS_SPEECH), list_hold_ceiling(AHS_CEILING), scratch() as d:
        scripts = ["s1", "s2", "s3", "s4"]
        out = rotate.assign(CHANNEL, "B", scripts, ledger_dir=d, pipeline_dir=d / "pipeline")
        refused = (out[-1]["pattern_id"], out[-1]["rhythm_id"])
        history = [(a["pattern_id"], a["rhythm_id"]) for a in out[:-1]]
        pairs, _ = rotate.eligible_pairs(rotate.load_channel(CHANNEL))
        unchecked = rotate.choose_pair(history, pairs, 4, 30, exclude=[refused])
        assert unchecked[0] == "list", (
            f"precondition: the unchecked rotation would hand back {unchecked}, not a list "
            f"pair - the fixture has moved and this test no longer tests the replacement")
        ruling = rotate.reject(CHANNEL, "s4", "the fact has no single visual thread to hold "
                               "over this pattern's blocks", ledger_dir=d)
        assert ruling["verdict"] == "upheld", ruling
        rep = ruling["replacement"]
        assert rep[0] != "list" and rep != refused, ruling
        sf = ruling["speech_fit"]
        assert sf["fits"] and not sf["no_compatible_pair"], sf
        assert sf["skipped"] and all(s["pair"].startswith("list/") for s in sf["skipped"]), sf
        assert ruling["assignment"]["speech_fit"] == sf, ruling["assignment"]
        rows = Ledger(ledger_path(CHANNEL, d)).rows()
        assert (rows[-1]["pattern_id"], rows[-1]["rhythm_id"]) == tuple(rep), rows[-1]
        assert rows[-1]["assigned_by"] == "rotation-after-rejection", rows[-1]


def test_a_replacement_with_no_fitting_pair_left_carries_a_speech_target():
    """Only list admitted, both pairs unfit: the rejection is still upheld (not
    refused for want of a fitting pair) and the replacement says what speech
    length it has to be written to."""
    with channel_speech(AHS_SPEECH, allowed=["list"]), list_hold_ceiling(AHS_CEILING), \
            scratch() as d:
        rotate.assign(CHANNEL, "B", ["s1"], ledger_dir=d, pipeline_dir=d / "pipeline")
        ruling = rotate.reject(CHANNEL, "s1", "the fact has no single visual thread to hold "
                               "over this pattern's blocks", ledger_dir=d)
        assert ruling["verdict"] == "upheld", ruling
        sf = ruling["speech_fit"]
        assert sf["no_compatible_pair"] and sf["speech_target_seconds"] == 43.2, sf
        assert "speech target" in ruling["explanation"], ruling["explanation"]


def test_a_denied_rejection_draws_nothing_and_carries_no_speech_fit():
    with channel_speech(AHS_SPEECH), list_hold_ceiling(AHS_CEILING), scratch() as d:
        rotate.assign(CHANNEL, "B", ["s1"], ledger_dir=d, pipeline_dir=d / "pipeline")
        rotate.reject(CHANNEL, "s1", "the fact has no single visual thread to hold over "
                      "this pattern's blocks", ledger_dir=d)
        again = rotate.reject(CHANNEL, "s1", "and the replacement is no better for this "
                              "fact either, honestly", ledger_dir=d)
        assert again["verdict"] == "denied" and again["rule"] == "R3", again
        assert again["speech_fit"] is None and again["replacement"] is None, again


def test_without_a_narration_budget_nothing_is_checked_and_the_rotation_is_unchanged():
    real = rotate.load_channel

    def no_budget(channel):
        cfg = real(channel)
        cfg.pop("narration_budget")
        return cfg

    rotate.load_channel = no_budget
    try:
        with scratch() as d:
            out = rotate.assign(CHANNEL, "B", ["s1"], ledger_dir=d,
                                pipeline_dir=d / "pipeline")
            assert out[0]["speech_fit"]["checked"] is False, out
    finally:
        rotate.load_channel = real


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

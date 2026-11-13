#!/usr/bin/env python3
"""CF-0565: the `scale` pattern's arithmetic is recomputed, not taken on trust.

`patterns/validate_patterns.py check_scale_footing` holds a scale script's
`script.scale` record to the rules in `patterns/scale.json` `scale_footing`:
every number is in its own quote, the scaled number is the video's fact, the
result is recomputed, and what the voice says for it does not overstate it.
Stand-in scripts only - no batch, no network.
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))

import validate_patterns as vp  # noqa: E402

PATTERN = vp.load_patterns()["scale"]

# The pattern file's own example, with its arithmetic: a 10 cm grapefruit (the
# small end of Wikipedia's «from 10 to 15 cm») for a Sun 1,391,400 km across
# (Wikipedia's Sun); Proxima Centauri at 4.24 light-years comes to about
# 2,883 km - said as «about 2,800 kilometres», past Moscow (2,500 km).
GOOD = {
    "script_id": "sci-test-001",
    "pattern": {"pattern_id": "scale", "rhythm_id": "hold"},
    "hook": "Shrink the Sun to a grapefruit, and the nearest star is still past Moscow.",
    "commentary": "Proxima Centauri, the nearest star, is 4.24 light-years away. Make the "
                  "Sun a grapefruit on a London street, and Proxima is another grapefruit "
                  "about 2,800 kilometres away - past Moscow.",
    "payoff": "And that is the nearest one.",
    "fact": {"text": "Proxima Centauri is 4.24 light-years from the Sun.",
             "kind": "measurement", "source": "NASA", "url": "https://science.nasa.gov/x",
             "quote": "Proxima Centauri, the closest star to our Sun, is 4.24 light-years away"},
    "scale": {
        "quantity": {"value": 4.24, "unit": "light-year",
                     "quote": "is 4.24 light-years away"},
        "reference": {"value": 1391400, "unit": "km",
                      "quote": "Its diameter is about 1,391,400 km",
                      "source_url": "https://en.wikipedia.org/wiki/Sun"},
        "familiar": {"object": "grapefruit", "value": 10, "unit": "cm",
                     "quote": "it ranges in diameter from 10 to 15 cm",
                     "source_url": "https://en.wikipedia.org/wiki/Grapefruit"},
        "result": {"value": 2800, "unit": "km", "said_as": "about 2,800 kilometres"},
    },
}


def check(script):
    return vp.check_scale_footing(script, PATTERN)


def kinds(report):
    return [f["kind"] for f in report["findings"]]


def test_the_worked_example_passes_and_is_recomputed():
    r = check(GOOD)
    assert r["verdict"] == "ok", r
    assert abs(r["computed"] - 2883.0) < 1.0, r["computed"]


def test_another_pattern_is_not_this_checks_business():
    s = copy.deepcopy(GOOD)
    s["pattern"]["pattern_id"] = "explainer"
    del s["scale"]
    assert check(s)["verdict"] == "not_applicable"


def test_a_scale_script_without_its_record_is_returned():
    s = copy.deepcopy(GOOD)
    del s["scale"]
    r = check(s)
    assert r["verdict"] == "return_for_rewrite" and kinds(r) == ["scale_record_missing"]


def test_a_number_not_in_its_quote_is_an_invented_number():
    s = copy.deepcopy(GOOD)
    s["scale"]["familiar"]["value"] = 12          # the quote says 10 to 15, not 12
    s["scale"]["result"]["value"] = 3400
    s["scale"]["result"]["said_as"] = "about 3,400 kilometres"
    s["commentary"] = s["commentary"].replace("2,800", "3,400")
    r = check(s)
    assert "scale_number_not_quoted" in kinds(r), r


def test_the_scaled_number_has_to_be_the_videos_fact():
    s = copy.deepcopy(GOOD)
    s["fact"]["quote"] = "Proxima Centauri is a red dwarf"
    s["fact"]["text"] = "Proxima Centauri is a red dwarf."
    assert "scale_quantity_not_from_fact" in kinds(check(s))


def test_a_wrong_result_is_caught_by_the_recompute():
    s = copy.deepcopy(GOOD)
    s["scale"]["result"]["value"] = 3400          # rounded up - 17.9 % over
    s["scale"]["result"]["said_as"] = "about 3,400 kilometres"
    s["commentary"] = s["commentary"].replace("2,800", "3,400")
    r = check(s)
    assert "scale_result_off" in kinds(r) and "scale_overstated" in kinds(r), r


def test_said_as_has_to_be_what_the_voice_says():
    s = copy.deepcopy(GOOD)
    s["commentary"] = s["commentary"].replace("about 2,800 kilometres", "far away")
    assert "scale_said_as_not_spoken" in kinds(check(s))


def test_mixed_measures_and_unknown_units_are_refused_not_waved_through():
    s = copy.deepcopy(GOOD)
    s["scale"]["reference"]["unit"] = "kg"
    assert "scale_unit_unknown" in kinds(check(s))
    s = copy.deepcopy(GOOD)
    s["scale"]["familiar"]["unit"] = "football pitches"
    assert "scale_unit_unknown" in kinds(check(s))


def test_the_intuition_this_check_exists_for_is_caught():
    """The first draft of the pattern file said «Voyager is past Moscow» on
    this very scale; Voyager's 25 billion km comes to about 1.8 km."""
    s = copy.deepcopy(GOOD)
    s["fact"] = {"text": "Voyager 1 is 25 billion kilometers from Earth.", "kind": "measurement",
                 "source": "NASA", "url": "https://science.nasa.gov/x",
                 "quote": "Voyager 1 is 25 billion kilometers from Earth"}
    s["scale"]["quantity"] = {"value": 25e9, "unit": "km",
                              "quote": "25 billion kilometers from Earth"}
    s["scale"]["result"] = {"value": 2500, "unit": "km", "said_as": "about 2,500 kilometres"}
    s["commentary"] = "Make the Sun a grapefruit, and Voyager is about 2,500 kilometres away."
    r = check(s)
    assert "scale_result_off" in kinds(r) and abs(r["computed"] - 1.797) < 0.01, r


def test_numbers_in_reads_the_sources_ways_of_writing_them():
    assert vp.numbers_in("1.39 million km and 25 billion kilometers") == [1.39e6, 25e9]
    assert vp.numbers_in("about 2,100 kilometres, 12 cm") == [2100.0, 12.0]


def test_numbers_in_reads_numbers_said_in_words():
    """CF-0673: «Write for the ear» has the voice say numbers in words."""
    assert vp.numbers_in("about three thousand four hundred kilometres") == [3400.0]
    assert vp.numbers_in("a grapefruit about twelve centimetres across") == [12.0]
    assert vp.numbers_in("about two and a half thousand kilometres") == [2500.0]
    assert vp.numbers_in("one point three nine million kilometres") == [1.39e6]
    assert vp.numbers_in("forty-two, three hundred and forty, a hundred metres") == \
        [42.0, 340.0, 100.0]
    # the digits' own multiplier is never read again as a word number
    assert vp.numbers_in("1.39 million km, then twenty five billion") == [1.39e6, 25e9]
    assert vp.numbers_in("millions of stars") == []


def _said(script, said_as):
    s = copy.deepcopy(script)
    s["scale"]["result"]["said_as"] = said_as
    s["commentary"] = (f"Proxima Centauri, the nearest star, is 4.24 light-years away. Make the "
                       f"Sun a grapefruit on a London street, and Proxima is another grapefruit "
                       f"{said_as} - past Moscow.")
    return s


def test_the_proxima_example_said_in_words_passes():
    """The pattern file's own Proxima Centauri example, said for the ear."""
    r = check(_said(GOOD, "about two thousand eight hundred kilometres"))
    assert r["verdict"] == "ok", r


def test_an_overstatement_said_in_words_is_caught():
    """Before CF-0673 a said_as in words carried no number the check could
    read, so «about four thousand kilometres» over a recompute of 2,883 km
    passed as not overstated."""
    r = check(_said(GOOD, "about four thousand kilometres"))
    assert kinds(r) == ["scale_overstated"], r
    assert "4000" in r["findings"][0]["note"]
    # within the tolerance in words is not an overstatement
    assert check(_said(GOOD, "about three thousand two hundred kilometres"))["verdict"] == "ok"
    # an inexact overstatement: just past the 15 % band (2883 x 1.15 = 3315) -
    # the old 12 cm example's own number, now an overstatement
    r = check(_said(GOOD, "some three thousand four hundred kilometres"))
    assert kinds(r) == ["scale_overstated"], r


def test_a_familiar_size_written_in_words_in_its_quote_is_read():
    s = copy.deepcopy(GOOD)
    s["scale"]["familiar"]["quote"] = "it ranges in diameter from ten to fifteen centimetres"
    assert check(s)["verdict"] == "ok"


def test_the_tolerance_is_the_pattern_files_number():
    tol, never = vp._scale_rules(PATTERN)
    assert (tol, never) == (PATTERN["scale_footing"]["rules"]["arithmetic_tolerance"], True)


def test_the_cli_exits_one_on_a_finding_and_zero_when_clean():
    bad = copy.deepcopy(GOOD)
    bad["script_id"] = "sci-test-002"
    del bad["scale"]
    with tempfile.TemporaryDirectory() as d:
        ok_path, bad_path = Path(d) / "ok.json", Path(d) / "bad.json"
        ok_path.write_text(json.dumps({"scripts": [GOOD]}))
        bad_path.write_text(json.dumps({"scripts": [GOOD, bad]}))
        cmd = [sys.executable, str(ROOT / "patterns" / "validate_patterns.py"), "check-scale"]
        ok = subprocess.run(cmd + [str(ok_path)], capture_output=True, text=True, timeout=60)
        no = subprocess.run(cmd + [str(bad_path)], capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert no.returncode == 1 and "scale_record_missing" in no.stdout, no.stdout


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

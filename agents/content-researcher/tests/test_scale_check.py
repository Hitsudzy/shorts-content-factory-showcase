#!/usr/bin/env python3
"""CF-0565: `scripts/check_scale.py` - the stage's half of the «масштаб»
pattern (`patterns/validate_patterns.py check_scale_footing` is the root's).

Pinned here: a scale script whose arithmetic recomputes and whose comparison
is declared in `claims[]` with all three numbers quoted passes; a broken
recompute is a REWRITE, an unchanged rerun spends nothing, and a second
failure after an edit is refused into `skipped[]` as `scale_unsupported`; a
rewrite that fixes it passes; a missing record is a field to fix, not an
attempt; the claim half (undeclared, a number without a quote); and a batch
with no scale script (every Reel batch, every other pattern) is not touched -
not even rewritten on disk.

Stand-ins only: the scripts are written here, the batch file lives in a temp
tree; the rule is the root's pattern code, never a live batch."""
import copy
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
import check_scale as cs  # noqa: E402

ROOT = cs.find_root()
RULE = cs.load_rule(ROOT)
_TMP = tmp_root("cr-scale-")

# The pattern file's own worked example (patterns/scale.json; the root's
# tests/test_scale_footing.py GOOD): a 10 cm grapefruit (the small end of
# Wikipedia's «from 10 to 15 cm») for a Sun 1,391,400 km across (Wikipedia's
# Sun) puts Proxima Centauri, 4.24 light-years away, about 2,883 km off -
# said as «about two thousand eight hundred kilometres», past Moscow.
GOOD = {
    "script_id": "sci-test-001",
    "topic_id": "sci-topic-001",
    "pattern": {"pattern_id": "scale", "rhythm_id": "hold"},
    "hook": "Shrink the Sun to a grapefruit, and the nearest star is still past Moscow.",
    "commentary": "Proxima Centauri, the nearest star, is 4.24 light-years away. Make the "
                  "Sun a grapefruit on a London street, and Proxima is another grapefruit "
                  "about two thousand eight hundred kilometres away - past Moscow.",
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
        "result": {"value": 2800, "unit": "km",
                   "said_as": "about two thousand eight hundred kilometres"},
    },
    "claims": [{
        "claim_id": "c1", "where": "commentary",
        "text": "Proxima is another grapefruit about two thousand eight hundred kilometres "
                "away",
        "support": [
            {"source": "nasa:proxima",
             "quote": "Proxima Centauri, the closest star to our Sun, is 4.24 light-years away"},
            {"source": "wikipedia:Sun", "quote": "Its diameter is about 1,391,400 km"},
            {"source": "wikipedia:Grapefruit",
             "quote": "it ranges in diameter from 10 to 15 cm"},
        ],
    }],
}

CONTRAST = {
    "script_id": "reel-test-001", "topic_id": "reel-topic-001",
    "pattern": {"pattern_id": "contrast", "rhythm_id": "alternate"},
    "hook": "Everyone saw the trailer.", "commentary": "Nobody saw the set.",
    "payoff": "That is the show.", "claims": [],
}


def write_batch(*scripts, channel="example-science"):
    d = Path(tempfile.mkdtemp(dir=_TMP))
    path = d / "03-content-researcher.json"
    path.write_text(json.dumps({"batch_id": "t", "channel": channel,
                                "scripts": [copy.deepcopy(s) for s in scripts]}, indent=1))
    return path


def run(path, write=True):
    lines = []
    problems, records, refused = cs.check_batch(path, root=ROOT, write=write,
                                                out=lines.append, rule=RULE)
    return problems, records, refused, "\n".join(lines)


def load(path):
    return json.loads(path.read_text())


def kinds(record):
    return sorted({f["kind"] for f in record["findings"]})


def broken():
    s = copy.deepcopy(GOOD)
    # «past Moscow» said as 340 km: a factor of ten off the recompute.
    s["scale"]["result"]["value"] = 340
    return s


def test_names_are_the_contracts():
    assert cs.SKIP_REASON_CODE == "scale_unsupported"
    assert cs.FUNNEL_STAGE == "scripts" and cs.REWRITES_ALLOWED == 1
    vp, pattern = RULE
    assert cs.PATTERN_ID == vp.SCALE_PATTERN_ID
    assert pattern["scale_footing"]["record"] == "script." + cs.SCALE_FIELD


def test_a_root_without_the_rule_cannot_answer():
    empty = Path(tempfile.mkdtemp(dir=_TMP))
    try:
        cs.load_rule(empty)
    except cs.CannotAnswer as exc:
        assert "validate_patterns.py" in str(exc)
    else:
        raise AssertionError("a root without patterns/validate_patterns.py answered")


def test_the_worked_example_passes_and_is_recorded():
    path = write_batch(GOOD)
    problems, records, refused, text = run(path)
    rec = records["sci-test-001"]
    assert not problems and not refused, text
    assert rec["action"] == "pass" and rec["failed_attempts"] == 0, rec
    assert abs(rec["computed"] - 2883.0) < 1.0, rec
    on_disk = load(path)["scripts"][0][cs.RECORD_KEY]
    assert on_disk["action"] == "pass" and on_disk["script_hash"].startswith("sha256:")


def test_a_broken_recompute_is_one_rewrite_then_refused_into_skipped():
    path = write_batch(broken())
    problems, records, refused, text = run(path)
    rec = records["sci-test-001"]
    assert problems and not refused and "REWRITE" in text, text
    assert kinds(rec) == ["scale_result_off"] and rec["failed_attempts"] == 1, rec

    # the same script again: nothing judged, nothing spent
    problems, records, refused, text = run(path)
    assert "UNCHANGED" in text and not records and not refused, text
    rec = load(path)["scripts"][0][cs.RECORD_KEY]
    assert rec["failed_attempts"] == 1 and rec["unchanged_reruns"] == 1, rec

    # an edit that is still wrong: the topic leaves the batch
    data = load(path)
    data["scripts"][0]["scale"]["result"]["value"] = 34000
    path.write_text(json.dumps(data))
    problems, records, refused, text = run(path)
    assert not problems and len(refused) == 1 and "REFUSE" in text, text
    data = load(path)
    assert data["scripts"] == [], data
    (skip,) = data["skipped"]
    assert skip["reason_code"] == "scale_unsupported" and skip["stage"] == "scripts", skip
    assert skip["topic_id"] == "sci-topic-001" and skip[cs.RECORD_KEY]["failed_attempts"] == 2


def test_a_rewrite_that_fixes_it_passes_and_keeps_the_count():
    path = write_batch(broken())
    run(path)
    data = load(path)
    data["scripts"][0]["scale"]["result"]["value"] = 2800
    path.write_text(json.dumps(data))
    problems, records, refused, text = run(path)
    rec = records["sci-test-001"]
    assert not problems and not refused and rec["action"] == "pass", text
    assert rec["failed_attempts"] == 1, rec


def test_an_overstated_said_as_is_sent_back():
    s = copy.deepcopy(GOOD)
    s["commentary"] = s["commentary"].replace("about two thousand eight hundred kilometres",
                                            "about 4,500 kilometres")
    s["scale"]["result"]["said_as"] = "about 4,500 kilometres"
    s["claims"][0]["text"] = "Proxima is another grapefruit about 4,500 kilometres away"
    _, records, _, text = run(write_batch(s))
    assert "scale_overstated" in kinds(records["sci-test-001"]), text


def test_a_missing_record_is_a_field_to_fix_not_an_attempt():
    s = copy.deepcopy(GOOD)
    del s["scale"]
    path = write_batch(s)
    problems, records, refused, text = run(path)
    assert problems and not records and not refused and "FAIL" in text, text
    assert cs.RECORD_KEY not in load(path)["scripts"][0]


def test_the_comparison_has_to_be_declared_in_claims():
    s = copy.deepcopy(GOOD)
    s["claims"] = []
    _, records, _, text = run(write_batch(s))
    assert kinds(records["sci-test-001"]) == [cs.CLAIM_UNDECLARED], text


def test_every_number_of_the_comparison_stands_on_a_quote():
    s = copy.deepcopy(GOOD)
    s["claims"][0]["support"] = s["claims"][0]["support"][:2]      # no grapefruit quote
    _, records, _, text = run(write_batch(s))
    rec = records["sci-test-001"]
    assert kinds(rec) == [cs.CLAIM_NUMBER_UNQUOTED], text
    assert any("familiar" in f["note"] for f in rec["findings"]), rec


def test_a_scale_quantity_not_from_the_fact_is_sent_back():
    s = copy.deepcopy(GOOD)
    s["scale"]["quantity"]["quote"] = "it is 4.24 light-years from here"
    _, records, _, _ = run(write_batch(s))
    assert "scale_quantity_not_from_fact" in kinds(records["sci-test-001"])


def test_other_patterns_and_reel_batches_are_not_touched():
    path = write_batch(CONTRAST, channel="example-film")
    before = path.read_bytes()
    problems, records, refused, text = run(path)
    assert not problems and not records and not refused, text
    assert "0 scale script(s) of 1" in text, text
    assert path.read_bytes() == before, "a batch without a scale script was rewritten"


def test_a_mixed_batch_judges_only_the_scale_script():
    path = write_batch(CONTRAST, broken())
    problems, records, refused, text = run(path)
    assert list(records) == ["sci-test-001"] and len(problems) == 1, text
    data = load(path)
    assert cs.RECORD_KEY not in data["scripts"][0]


def test_cli_exit_codes():
    assert cs.main([str(write_batch(GOOD)), "--write", "--root", str(ROOT)]) == cs.EXIT_OK
    path = write_batch(broken())
    assert cs.main([str(path), "--write", "--root", str(ROOT)]) == cs.EXIT_REWRITE
    data = load(path)
    data["scripts"][0]["scale"]["result"]["value"] = 34000
    path.write_text(json.dumps(data))
    assert cs.main([str(path), "--write", "--root", str(ROOT)]) == cs.EXIT_REFUSED
    missing = Path(tempfile.mkdtemp(dir=_TMP)) / "none.json"
    assert cs.main([str(missing), "--root", str(ROOT)]) == cs.EXIT_CANNOT_ANSWER


def test_the_skill_writes_the_record_and_runs_the_gate():
    skill = (HERE.parent / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    # step 5: the record, read from the pattern file
    assert "`script.scale`" in skill and "scale_footing.fields" in skill
    assert "patterns/scale.json" in skill
    # step 5: the comparison declared as a claim with all three numbers
    assert "**The comparison is a claim**" in skill and "each of the three numbers" in skill
    # step 6: the gate, its step name, its ladder and its refusal code
    assert "scripts/check_scale.py" in skill and "`check-scale`" in skill
    assert "validate_patterns.py check-scale" in skill
    assert "`scale_unsupported`" in skill
    # the batch is not finished until it exits 0 (or 4) on every scale script
    finished = skill[skill.index("A batch is not finished until"):]
    finished = finished[:finished.index("\n")]
    assert "`check_scale.py` (on every `scale` script; or 4, a topic refused as " \
           "`scale_unsupported` and recorded)" in finished


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

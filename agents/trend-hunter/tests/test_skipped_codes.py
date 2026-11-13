#!/usr/bin/env python3
"""CF-0708: `skipped_topics[]` codes are the funnel's words - a coined one
(`no_dated_source`, example-science 2026-10-12T2001Z) stops the finished-batch
check instead of reaching the funnel as an unknown code. Stand-in batches in
temp directories only; the vocabulary is the factory root's funnel.py."""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import check_scenes as cs  # noqa: E402
import skipped_codes as sc  # noqa: E402

# the row as the 2001Z stage's model wrote it
COINED = {"topic_id": "lf-2026-10-12-005", "reason_code": "no_dated_source",
          "stage": "trend-hunter", "title": "Artemis II", "kind": "work",
          "popularity_score": 59.3,
          "reason": ("its only news source is a Nature entry whose feed gives no publication "
                     "date (evidence_sources: published_at missing - unusable for a proof); "
                     "dropped from the topic")}


def _batch(*rows):
    return {"batch_id": "2026-10-12T2001Z", "channel": "example-science", "topics": [],
            "skipped_topics": [dict(r) for r in rows]}


def test_the_vocabulary_is_the_roots_funnel():
    codes, legacy = sc.vocabulary()
    for code in ("no_source", "no_fact", "below_shortlist", "already_published",
                 "no_support_text"):
        assert code in codes, code
    assert "no_dated_source" not in codes
    assert legacy.get("no_dated_source") == "no_source", legacy
    assert legacy.get("no_production_fact") == "no_fact", legacy


def test_the_2001z_row_is_refused_and_told_to_write_no_source():
    problems = sc.check_batch(_batch(COINED))
    assert len(problems) == 1 and "no_dated_source" in problems[0], problems
    assert "'no_source'" in problems[0], problems


def test_a_freshly_coined_word_is_refused():
    problems = sc.check_batch(_batch(dict(COINED, reason_code="no_dated_proof")))
    assert len(problems) == 1 and "outside the funnel's vocabulary" in problems[0], problems
    assert "`no_source`" in problems[0], problems


def test_a_row_with_no_code_is_refused():
    row = dict(COINED)
    row.pop("reason_code")
    problems = sc.check_batch(_batch(row))
    assert len(problems) == 1 and "no reason_code" in problems[0], problems


def test_the_fixed_row_and_the_stages_own_codes_pass():
    rows = [dict(COINED, reason_code="no_source"),
            {"topic_id": "t2", "reason_code": "no_fact", "reason": "x", "stage": "trend-hunter"},
            {"topic_id": "t3", "reason_code": "below_shortlist", "reason": "x",
             "stage": "trend-hunter"}]
    assert sc.check_batch(_batch(*rows)) == []
    assert sc.check_batch({"topics": []}) == [], "a batch with no skipped_topics says nothing"


def test_the_cli_and_check_scenes_check_both_stop_on_the_coined_code():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        path = tmp / "01-trend-hunter.json"
        path.write_text(json.dumps(_batch(COINED)))
        assert sc.main([str(tmp)]) == 1
        assert cs.main([str(tmp), "--check"]) == 1
        path.write_text(json.dumps(_batch(dict(COINED, reason_code="no_source"))))
        assert sc.main([str(tmp)]) == 0
        assert cs.main([str(tmp), "--check"]) == 0
        assert sc.main([str(tmp / "missing")]) == 2


# --------------------------------------------------------------------------
# the stage's own codes pass, whatever the funnel knows (CF-0708 follow-up)
# --------------------------------------------------------------------------

def test_every_code_the_stages_scripts_write_is_found_and_passes():
    codes, unresolved = sc.stage_codes()
    assert unresolved == [], unresolved
    for code in ("no_source", "footage_evidence_quota", "no_fact", "below_shortlist",
                 "already_published", "no_support_text"):
        assert code in codes, (code, sorted(codes))
    rows = [{"topic_id": f"t{i}", "reason_code": c, "reason": "x", "stage": "trend-hunter"}
            for i, c in enumerate(sorted(codes))]
    assert sc.check_batch(_batch(*rows)) == []


def test_every_writer_constant_passes_the_guard():
    """The constants the writers of `skipped_topics[]` name - imported from the
    modules themselves - are all found by `stage_codes()` and all pass."""
    import fact_probe_topics as fpt
    import footage_candidates as fc
    import published_before as pb
    constants = {
        "footage_candidates.REFUSAL_CODE": fc.REFUSAL_CODE,
        "footage_candidates.EVIDENCE_QUOTA_CODE": fc.EVIDENCE_QUOTA_CODE,
        "fact_probe_topics.FACT_REFUSAL_CODE": fpt.FACT_REFUSAL_CODE,
        "fact_probe_topics.OVERFLOW_CODE": fpt.OVERFLOW_CODE,
        "fact_probe_topics.SUPPORT_REFUSAL_CODE": fpt.SUPPORT_REFUSAL_CODE,
        "published_before.PUBLISHED_CODE": pb.PUBLISHED_CODE,
        "check_scenes.FACT_REFUSAL_CODE": cs.FACT_REFUSAL_CODE,
    }
    own = sc.own_codes()
    for name, code in constants.items():
        assert code in own, (name, code, sorted(own))
        row = {"topic_id": "t1", "reason_code": code, "reason": "x", "stage": "trend-hunter"}
        assert sc.check_batch(_batch(row)) == [], (name, code)


def test_the_quota_day_batch_passes_check_scenes_check():
    """The regression the follow-up names: on the day the search quota runs
    out, footage_candidates.py writes `footage_evidence_quota` (CF-0317) and
    the finished-batch check must pass. Since CF-0714 the root's funnel knows
    the word (a loss of the topic), so the CLI names no note for it; against a
    root that predates CF-0714 it still passes, with the note."""
    import contextlib
    import io
    codes, _legacy = sc.vocabulary()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "01-trend-hunter.json").write_text(json.dumps(_batch(
            {"topic_id": "t5", "reason_code": "footage_evidence_quota", "stage": "trend-hunter",
             "reason": "the day's searches would not pay for its facet run"})))
        assert cs.main([str(tmp), "--check"]) == 0
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert sc.main([str(tmp)]) == 0
    noted = "note: 'footage_evidence_quota'" in err.getvalue()
    assert noted == ("footage_evidence_quota" not in codes), err.getvalue()


def test_the_reading_follows_a_new_writer_and_names_what_it_cannot_follow():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "w.py").write_text(
            'import other\n'
            'NEW_CODE = "brand_new_refusal"\n'
            'def drop(batch, tid, reason, code=NEW_CODE):\n'
            '    batch.setdefault("skipped_topics", []).append(\n'
            '        {"topic_id": tid, "reason_code": code, "reason": reason})\n'
            'def go(batch, x):\n'
            '    drop(batch, "a", "r", code=other.SECOND)\n'
            '    drop(batch, "b", "r", code=x)\n'
            '    batch["slots"].append({"topic_id": None, "reason_code": x})\n')
        (tmp / "other.py").write_text('SECOND = "second_refusal"\n')
        codes, unresolved = sc.stage_codes(tmp)
        assert set(codes) == {"brand_new_refusal", "second_refusal"}, codes
        assert len(unresolved) == 1 and "w.py:8" in unresolved[0], unresolved


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)

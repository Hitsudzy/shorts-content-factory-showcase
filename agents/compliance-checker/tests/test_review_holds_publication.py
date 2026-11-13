#!/usr/bin/env python3
"""CF-0318 (DoD 1.4.5): a `review` verdict holds the publication, not the
production.

This file replaces `tests/test_review_is_a_refusal.py`, and the replacement is
the point rather than a rename. CF-0232 (2026-09-16) settled that nobody looks
at a `review` and that the verdict is written down instead of dropping the
topic silently - that half stands and is pinned below. What it got wrong was
*where* the refusal lands: the indexer took the topic off the batch, so a topic
nobody was waiting on died before a frame of it existed, and the instrumented
funnel priced that at **19 topics of 101 across ten runs**. The user decided on
2026-09-22 (Q8) that without a human only the **publication** is forbidden -
the video must be made.

So this file pins, on the text a model actually reads:

* the wording that told the agent a `review` takes the topic off the batch is
  gone, and so is the older wording promising a human queue (CF-0232's own
  test guarded that, and losing it here would let it creep back);
* the dated amendment that replaced it is present with its date, its task and
  its grill log (CF-0190's convention);
* the two places the hold is written are named, and the script that writes it
  is a step in the procedure rather than something the model does by hand;
* the legal side is not softened: `review` is still earned by a `high`-risk
  match or a real sensitivity concern, and the SKILL still forbids capping one
  by hand;
* the output contract the funnel depends on is still stated.

No pytest dependency - plain asserts, dual-mode, same style as
tests/test_publication_hold.py.
"""
import re
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SKILL = AGENT_ROOT / ".claude" / "skills" / "compliance-checker" / "SKILL.md"

# The funnel's code for a topic the gate LOST, in the root repo. A held topic
# is not lost and must not carry it (`shared/runlog/funnel.py`).
FUNNEL_LOSS_CODE = "compliance_review"
HOLD_CODE = "compliance_review_hold"
LEDGER = "publish/publication-holds.json"
STAGE_FILES = ("02-compliance-checker.json", "04-compliance-checker.json")


def _skill() -> str:
    assert SKILL.is_file(), SKILL
    return SKILL.read_text()


def test_the_wording_that_took_the_topic_off_the_batch_is_gone():
    """Both generations of it: CF-0232's "the topic leaves the batch", and the
    human-queue wording CF-0232 itself removed."""
    text = _skill()
    for gone in (
        # CF-0318 removes these.
        "In an autonomous batch this takes the topic off the batch",
        "each one is a topic leaving the batch",
        "a `review` takes the whole topic off the batch",
        "a review verdict is a recorded refusal (CF-0232)",
        "Content Researcher was told to skip `review` topics",
        # CF-0232 removed these; they must not come back.
        "the orchestrator/human decides",
        "should go back to the human",
        "flagged for human review",
        'the one exception to "never silently drop, always defer to a human"',
    ):
        assert gone not in text, (
            f"SKILL.md still says {gone!r} - CF-0318 decided a `review` blocks "
            f"the publication, not the production")


def test_the_dated_amendment_is_there_with_its_sources():
    """CF-0190's convention: the decision, its date, and where it was taken."""
    text = _skill()
    assert ("## A `review` verdict holds the publication, not the production "
            "(2026-09-22, CF-0318)" in text)
    assert "The user decided on **2026-09-22**" in text
    assert "grill-me-logs/2026-09-22" in text, "the grill log is not linked"
    assert "CF-0232" in text, (
        "the amendment should say which decision it revises, and which half of "
        "it still stands")
    assert "19 topics of 101" in text, (
        "the number that motivated the change belongs in the record - a rule "
        "changed without its price is a rule nobody can re-argue")


def test_the_verdict_itself_is_not_softened():
    """The legal side does not move. Only what the verdict blocks moves."""
    text = _skill()
    # CF-0420 (2026-09-28): the rights-holder match left the verdict; the
    # content-sensitivity side did not move.
    assert "`review` — a real content-sensitivity concern" in text
    assert "A rights-holder match, at any risk level, is still `clear` (CF-0420)" in text
    assert '"affects_verdict": false' in text
    for kept in (
        "Don't cap a `review` at `caution` by hand",
        "don't leave one unwritten",
        'don\'t invent a "pending human" state',
    ):
        assert kept in text, f"SKILL.md no longer says {kept!r}"
    assert re.search(r"The verdict is not milder", text), (
        "the amendment must say in so many words that the verdict did not get "
        "easier - only its consequence changed")


def test_the_hold_is_named_in_both_places_and_written_by_the_script():
    text = _skill()
    assert LEDGER in text, f"SKILL.md does not name the ledger {LEDGER}"
    assert "publication_hold" in text, "the block stamped on the row is not named"
    assert HOLD_CODE in text, f"SKILL.md does not name the hold's code {HOLD_CODE!r}"
    assert "scripts/publication_hold.py" in text
    assert "4d." in text, (
        "writing the holds must be a numbered step of the procedure, not a "
        "remark - a step a model can skip is a hold nobody writes")
    assert "Never write either by hand" in text


def test_the_ledger_is_justified_by_the_archive_job_and_named_for_publisher():
    """Why *there* and not in the batch - the reason has to survive in the text,
    because the next reader will wonder why a second file exists."""
    text = _skill()
    assert "archive_old_batches.sh" in text
    assert "31 days" in text
    for task in ("CF-0017", "CF-0018"):
        assert task in text, f"{task} is not named as a reader of the ledger"
    assert "docs/publisher-metadata-rules.md" in text


def test_the_signature_is_the_users_and_only_the_users():
    text = _skill()
    assert "`signature` is the only field a human decides" in text
    assert "CF-0320" in text, (
        "the rule is borrowed from the gate-price ledger and should say so")
    assert "a signature written by the code that needs it is not a signature" in text
    # CF-0687: the one exception is named with its limits - the user's action
    # in the center, a note, `via: center` - and the pass still never signs.
    for needle in ("CF-0687", "sign_hold", "pressed the button", '"via": "center"',
                   "not_signable", "still never sign anything"):
        assert needle in text, f"the CF-0687 exception does not say {needle!r}"


def test_a_held_topic_does_not_carry_the_funnels_loss_code():
    text = _skill()
    assert FUNNEL_LOSS_CODE in text and "shared/runlog/funnel.py" in text
    assert "## 7. Topic funnel" in text
    for stage in STAGE_FILES:
        assert stage in text, f"{stage} is not named as a funnel stage"
    assert re.search(r"`clear` and `caution` are the passing verdicts", text), (
        "SKILL.md should still say which verdicts pass the funnel")
    assert "A held topic is not lost" in text, (
        "sharing `compliance_review` between a lost topic and a held one would "
        "make the funnel unreadable")
    assert "Never silently drop a topic" in text


def test_the_results_entry_the_funnel_reads_is_still_specified():
    """`detail` is a verbatim `results[]` entry: verdict plus both checks."""
    text = _skill()
    start = text.index("**Write output.**")
    block = text[start:text.index("```", text.index("```json", start) + 7)]
    for field in ('"results"', '"verdict"', '"rights_holder_check"',
                  '"content_sensitivity_check"'):
        assert field in block, (
            f"the output block no longer writes {field} - the funnel copies "
            f"this entry into its `detail` field, so the row loses the "
            f"verdict it is supposed to record")
    assert "`results[]`" in text and "`detail`" in text


def test_the_two_procedures_both_run_the_hold_script():
    """A `review` can be raised at either pass, and the 04 pass used to be
    told it would never see one."""
    text = _skill()
    for stage_file in STAGE_FILES:
        assert f'publication_hold.py \\\n     "$RUNLOG_BATCH/{stage_file}"' in text, (
            f"the {stage_file} pass does not run the hold script")


def test_held_is_reported_and_is_not_reserve():
    text = _skill()
    assert "**Reserve is not held.**" in text
    assert "a video that does not exist, the other is a video that exists and may not go up" in text
    assert "`held` is how many of the carried topics came in at `review`" in text


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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

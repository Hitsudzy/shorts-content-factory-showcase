#!/usr/bin/env python3
"""CF-0265: the cut to the batch target, after compliance judged the shortlist.

The acceptance criterion of the task, in tests: a shortlist of eight carries
five in shortlist order and records the rest as unused reserve. Plus the three
shapes that decide whether the cut can be run unattended - a batch with fewer
eligible topics than the target, a batch from before shortlists existed, and
the same batch cut twice.

CF-0318 changed who is eligible. Until 2026-09-22 a `review` was refused here
and took no slot; the user decided that only the **publication** of a video
needs a human, so a `review` now fills a slot like any other verdict and the
hold travels with its video (`scripts/publication_hold.py`,
`tests/test_publication_hold.py`). The tests below that used to pin "a review
never carries" now pin the opposite, and the two of them that pin the boundary
- that it is still not reserve, and that the cut still never touches a verdict
- are unchanged in substance.

CF-0335 changed who gets a slot FIRST. The user's answer to CF-0318 on
2026-09-23 ("0318 - B"): inside the cut the publishable topics (`clear`,
`caution`) take the slots in shortlist order, and the held ones (`review`)
take what is left, in shortlist order too; a `review` with no slot left goes
to `reserve[]` like a `clear` ranked past the target. It is the one re-sort by
verdict CF-0265 allows, and the tests under "publishable first" pin it.

The two things these tests are really guarding are not the arithmetic:

* **`results[]` must never carry a reserve row.** Three readers written before
  this cut existed treat every `results[]` row as a topic that goes on -
  `agents/content-researcher/scripts/fact_refusal.py::cleared_topic_ids`, the
  root's `tests/test_pipeline_contracts.py` (which demands the Researcher write
  or skip each one) and `shared/runlog/funnel.py`. A reserve topic left among
  them is the silent slot CF-0265 exists to close, only pointing the other way.
* **A `review` is not reserve.** Since CF-0318 neither is a loss, but they are
  still two different states and must not be folded together: a held topic has
  a slot and a video that may not be uploaded without a signature, a reserve
  topic has no slot and nothing runs on it at all. Reading the two out as one
  list is the confusion CF-0265 exists to stop, and the hold is the thing
  CF-0318 exists to make findable.

No pytest dependency - plain asserts, dual-mode, same style as
tests/test_blooper_relaxation.py.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _tmproot import tmp_root  # noqa: E402  CF-0489: removed at exit
_TMP = tmp_root("cut-shortlist-")

import _channel_ids  # noqa: E402
import cut_shortlist as cut  # noqa: E402

SKILL = AGENT_ROOT / ".claude" / "skills" / "compliance-checker" / "SKILL.md"
CHANNEL = "example-film"
TARGET = 5
TARGET_FROM = f"channels/{CHANNEL}.json scope.max_titles_per_batch"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def a_result(tid, verdict):
    """A verdict record of the shape the Trend Hunter pass writes - both
    checks included, because the funnel copies the whole entry into the
    `detail` of the row it records (CF-0232)."""
    return {"topic_id": tid, "verdict": verdict,
            "rights_holder_check": {"matched": verdict != "clear",
                                    "risk_level": "high" if verdict == "review" else "medium",
                                    "reason": f"blacklist reading for {tid}"},
            "content_sensitivity_check": {"flagged": False, "notes": f"notes for {tid}"}}


def a_batch(verdicts, shortlist=True):
    """`(compliance_doc, stage_doc)` for a shortlist of `len(verdicts)` topics,
    in the order given - which is the shortlist's order."""
    ids = [f"t{i}" for i in range(1, len(verdicts) + 1)]
    stage = {"batch_id": "B", "channel": CHANNEL,
             "topics": [{"topic_id": t, "title_ref": {"rights_holder": None}} for t in ids]}
    if shortlist:
        stage["selection"] = {"stage": "trend-hunter", "shortlist_size": len(ids),
                              "carried": len(ids)}
    doc = {"batch_id": "B", "channel": CHANNEL, "stage_checked": "01-trend-hunter",
           "checked_at": "2026-09-17T20:00:00Z", "disclaimer": "...",
           "results": [a_result(t, v) for t, v in zip(ids, verdicts)]}
    return doc, stage


def run_cut(doc, stage, target=TARGET):
    return cut.cut_document(doc, stage, target, TARGET_FROM)


def ids(rows):
    return [r["topic_id"] for r in rows]


# --------------------------------------------------------------------------
# the acceptance criterion
# --------------------------------------------------------------------------
def test_eight_with_one_review_carries_five_publishable_first():
    """The criterion of CF-0265 as CF-0318 and CF-0335 leave it: eight judged,
    five carried. Seven of them are publishable, so the five slots go to the
    first five publishable topics in shortlist order and the `review` at rank
    2 waits in `reserve[]` - it would have been made had a slot been left
    (CF-0318), and a held video may not push out one that can go up
    (CF-0335)."""
    doc, stage = a_batch(["clear", "review", "caution", "clear", "caution",
                          "clear", "caution", "clear"])
    out, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t3", "t4", "t5", "t6"], carried
    assert reserved == ["t2", "t7", "t8"], reserved
    assert ids(out["results"]) == ["t1", "t3", "t4", "t5", "t6"], ids(out["results"])
    assert ids(out["reserve"]) == ["t2", "t7", "t8"], (
        "reserve[] stays in shortlist order - only who got a slot changed")
    record = out["cut"]
    assert (record["judged"], record["eligible"], record["carried"],
            record["reserve"], record["refused"]) == (8, 8, 5, 3, 0), record
    assert record["held"] == 0, record
    assert record["publishable_first"] is True
    assert record["target"] == TARGET and record["target_from"] == TARGET_FROM
    assert record["shortlist_size"] == 8
    assert record["production_verdicts"] == ["clear", "caution", "review"]
    assert record["publish_verdicts"] == ["clear", "caution"]


def test_a_review_takes_a_slot_that_is_left_and_is_not_reserve():
    """CF-0318: the topic goes into production when a slot is left after the
    publishable ones (CF-0335). CF-0265's boundary survives - held is not
    reserve, and the cut still does not touch a verdict."""
    doc, stage = a_batch(["review", "clear", "clear", "clear", "clear", "blocked",
                          "clear", "clear"])
    out, carried, reserved = run_cut(doc, stage, target=7)
    assert carried[0] == "t1", (
        "a `review` no longer takes the topic off the batch: without a human "
        "only the publication is forbidden (user, grill of 2026-09-22)")
    assert "t1" not in reserved
    held = [r for r in out["results"] if r["topic_id"] == "t1"][0]
    assert held["verdict"] == "review", "the cut must never touch a verdict"
    assert "reason_code" not in held, (
        "the cut writes its reserve code and nothing else; the hold is written "
        "by scripts/publication_hold.py, in its own block")
    assert carried == ["t1", "t2", "t3", "t4", "t5", "t7", "t8"], carried
    assert reserved == [], reserved
    assert out["cut"]["held"] == 1


def test_order_is_the_shortlists_and_never_the_verdicts():
    """A `caution` ranked second goes on ahead of a `clear` ranked seventh:
    the shortlist is Trend Hunter's score order, and the cut is not a second
    opinion on which topic is better."""
    doc, stage = a_batch(["caution"] * 5 + ["clear"] * 3)
    out, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t2", "t3", "t4", "t5"]
    assert reserved == ["t6", "t7", "t8"]


def test_caution_is_eligible():
    doc, stage = a_batch(["caution"] * 8)
    _, carried, reserved = run_cut(doc, stage)
    assert len(carried) == 5 and len(reserved) == 3


# --------------------------------------------------------------------------
# publishable first (CF-0335, user's answer to CF-0318 of 2026-09-23: "B")
# --------------------------------------------------------------------------
def test_a_review_ranked_above_a_publishable_topic_yields_the_last_slot():
    """The task's own test: a `review` ranks above a publishable topic and the
    slots do not stretch to both. The publishable one is in the cut, the
    `review` is in `reserve[]` - with its verdict and whole reading untouched
    and the same `reserve_unused` code a `clear` past the target carries."""
    doc, stage = a_batch(["clear", "clear", "clear", "clear", "review",
                          "clear", "caution", "clear"])
    out, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t2", "t3", "t4", "t6"], carried
    assert reserved == ["t5", "t7", "t8"], reserved
    row = [r for r in out["reserve"] if r["topic_id"] == "t5"][0]
    assert row["verdict"] == "review", "the cut must never touch a verdict"
    assert row["rights_holder_check"]["risk_level"] == "high"
    assert row["reason_code"] == cut.RESERVE_CODE
    assert "CF-0335" in row["reason"] and "rank 5" in row["reason"], row["reason"]
    assert out["cut"]["held"] == 0


def test_the_smallest_shape_one_slot_two_topics():
    doc, stage = a_batch(["review", "caution"])
    out, carried, reserved = run_cut(doc, stage, target=1)
    assert carried == ["t2"] and reserved == ["t1"], (carried, reserved)


def test_held_topics_fill_what_is_left_in_their_own_rank_order():
    """Three publishable, three held, five slots: the three publishable take
    theirs, then the two best-ranked `review` topics - not any two - and the
    third `review` is reserve. `results[]` is written in shortlist order."""
    doc, stage = a_batch(["review", "review", "clear", "review", "clear",
                          "caution", "blocked", "blocked"])
    out, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t2", "t3", "t5", "t6"], carried
    assert reserved == ["t4"], reserved
    assert ids(out["results"]) == ["t1", "t2", "t3", "t5", "t6", "t7", "t8"]
    assert out["cut"]["held"] == 2


def test_clear_and_caution_are_one_class_and_keep_their_rank_order():
    """The exception is `review` alone: a `caution` is never put behind a
    `clear` - the publishable class keeps the shortlist's order inside it."""
    doc, stage = a_batch(["caution", "review", "clear", "caution", "clear",
                          "caution", "clear", "clear"])
    _, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t3", "t4", "t5", "t6"], carried
    assert reserved == ["t2", "t7", "t8"], reserved


def test_no_target_still_carries_every_held_topic():
    """Fail closed stays fail closed: with no target nothing is reserved, so
    the re-sort has nothing to decide."""
    doc, stage = a_batch(["review", "clear", "review"])
    out, carried, reserved = run_cut(doc, stage, target=None)
    assert carried == ["t1", "t2", "t3"] and reserved == []


# --------------------------------------------------------------------------
# the shapes that must not surprise an unattended run
# --------------------------------------------------------------------------
def test_fewer_eligible_than_the_target_carries_all_and_reserves_none():
    """A verdict outside the production set is the only thing that takes a
    slot away now. `blocked` is not a verdict this pass writes - it stands in
    for whatever a future one might, and for a corrupt row."""
    doc, stage = a_batch(["clear", "blocked", "caution", "blocked", "blocked",
                          "blocked", "blocked", "blocked"])
    out, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t3"] and reserved == []
    assert out["reserve"] == [], (
        "an empty `reserve[]` is written, not omitted: present-and-empty means the "
        "cut ran and reserved nothing, absent means it never ran")
    assert out["cut"]["eligible"] == 2 and out["cut"]["carried"] == 2
    assert out["cut"]["refused"] == 6 and out["cut"]["held"] == 0


def test_a_batch_of_nothing_but_review_still_fills_the_batch():
    """The shape the user's decision turns on: before CF-0318 this batch made
    no video at all. It now makes five, none of them publishable unsigned -
    and the record says so out loud, because five held videos is a fact the
    user has to see."""
    doc, stage = a_batch(["review"] * 8)
    out, carried, reserved = run_cut(doc, stage)
    assert carried == ["t1", "t2", "t3", "t4", "t5"], carried
    assert out["cut"]["held"] == 5 and out["cut"]["refused"] == 0


def test_an_old_shape_batch_passes_through_unchanged():
    """Five topics, no `selection` block - every batch written before CF-0264.
    The cut is a no-op on it: nothing moves, and the record says the shortlist
    size was never written rather than inventing one."""
    doc, stage = a_batch(["clear", "caution", "clear", "caution", "clear"],
                         shortlist=False)
    before = copy.deepcopy(doc["results"])
    out, carried, reserved = run_cut(doc, stage)
    assert out["results"] == before, "no topic may move in an old-shape batch"
    assert reserved == [] and out["reserve"] == []
    assert carried == ["t1", "t2", "t3", "t4", "t5"]
    assert out["cut"]["shortlist_size"] is None
    assert out["cut"]["judged"] == 5 and out["cut"]["refused"] == 0


def test_running_the_cut_twice_changes_nothing():
    doc, stage = a_batch(["clear", "review", "caution", "clear", "caution",
                          "clear", "caution", "clear"])
    once, carried1, reserved1 = run_cut(doc, stage)
    twice, carried2, reserved2 = run_cut(copy.deepcopy(once), stage)
    assert (carried1, reserved1) == (carried2, reserved2)
    for key in ("results", "reserve"):
        assert once[key] == twice[key], f"{key} moved on the second run"
    assert {k: v for k, v in once["cut"].items() if k != "cut_at"} == \
           {k: v for k, v in twice["cut"].items() if k != "cut_at"}


def test_a_relaxed_review_is_re_cut_from_the_verdicts_not_from_the_last_cut():
    """The blooper relaxation (CF-0190) runs before the cut, but if it is ever
    run after one, the cut re-reads `results[] + reserve[]` and gives the slot
    to the topic that now earns it - it never reads its own output as the
    pass's word."""
    doc, stage = a_batch(["blocked", "clear", "clear", "clear", "clear", "clear",
                          "clear", "clear"])
    once, carried, reserved = run_cut(doc, stage)
    assert carried == ["t2", "t3", "t4", "t5", "t6"] and reserved == ["t7", "t8"]
    once["results"][0]["verdict"] = "caution"          # what a later pass may make it
    again, carried, reserved = run_cut(once, stage)
    assert carried == ["t1", "t2", "t3", "t4", "t5"], carried
    assert reserved == ["t6", "t7", "t8"], reserved
    assert again["cut"]["refused"] == 0


def test_a_relaxed_review_keeps_its_slot_and_stops_being_held():
    """The blooper relaxation (CF-0190) caps a rights-holder `review` at
    `caution`. Under CF-0318 that no longer decides whether the topic is made
    - it was going to be made either way - it decides whether the video needs
    a signature before it goes up."""
    doc, stage = a_batch(["review", "clear", "clear", "clear", "blocked",
                          "blocked", "blocked", "blocked"])
    once, carried, _ = run_cut(doc, stage)
    assert carried[0] == "t1" and once["cut"]["held"] == 1, carried
    once["results"][0]["verdict"] = "caution"          # what the relaxation caps it to
    again, carried, _ = run_cut(once, stage)
    assert carried[0] == "t1", "the relaxation must not cost the topic its slot"
    assert again["cut"]["held"] == 0


def test_no_target_means_no_cut():
    """Fail closed the way this repo fails closed: an unreadable
    `scope.max_titles_per_batch` is not a licence to refuse topics."""
    doc, stage = a_batch(["clear"] * 8)
    out, carried, reserved = run_cut(doc, stage, target=None)
    assert len(carried) == 8 and reserved == []
    assert out["cut"]["target"] is None


def test_a_topic_the_shortlist_does_not_name_is_not_lost():
    doc, stage = a_batch(["clear"] * 8)
    doc["results"].append(a_result("stray", "clear"))
    stray_stage = copy.deepcopy(stage)
    out, carried, reserved = run_cut(doc, stray_stage)
    assert "stray" in carried + reserved, "a judged topic may never fall out of the file"
    assert reserved[-1] == "stray", (
        "a topic the shortlist does not rank cannot be ranked ahead of one it does")
    assert out["cut"]["judged"] == 9


# --------------------------------------------------------------------------
# the contract the downstream readers stand on
# --------------------------------------------------------------------------
def test_reserve_rows_keep_the_whole_verdict_record_and_say_why():
    doc, stage = a_batch(["clear"] * 8)
    out, _, _ = run_cut(doc, stage)
    for row in out["reserve"]:
        for key in ("topic_id", "verdict", "rights_holder_check",
                    "content_sensitivity_check"):
            assert key in row, f"reserve row lost {key}"
        assert row["reason_code"] == cut.RESERVE_CODE == "reserve_unused"
        reason = row["reason"]
        # Self-contained: a reader of `reserve[]` with no other file open has
        # to get the verdict, the rank, the target and that this is not a
        # refusal out of this one sentence.
        for fragment in ("rank", "shortlist", str(TARGET), TARGET_FROM,
                         "Not a refusal", "CF-0265"):
            assert fragment in reason, (fragment, reason)


def test_results_and_reserve_never_hold_the_same_topic():
    doc, stage = a_batch(["clear", "review", "caution", "clear", "caution",
                          "clear", "caution", "clear"])
    out, _, _ = run_cut(doc, stage)
    assert not (set(ids(out["results"])) & set(ids(out["reserve"])))
    assert len(ids(out["results"])) + len(ids(out["reserve"])) == 8


def test_every_results_verdict_is_still_one_of_the_three():
    """The root's `tests/test_pipeline_contracts.py::test_compliance_checker_stage`
    asserts exactly this set. The cut must not invent a `reserve` verdict to
    carry the state in - the state lives in which list the row is in."""
    doc, stage = a_batch(["clear", "review", "caution", "clear", "caution",
                          "clear", "caution", "clear"])
    out, _, _ = run_cut(doc, stage)
    for row in out["results"] + out["reserve"]:
        assert row["verdict"] in ("clear", "caution", "review"), row


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------
def _temp_root(target=TARGET):
    """A miniature factory root the script reads its target from, through
    FACTORY_ROOT. The real config is never edited by a test."""
    tmp = Path(tempfile.mkdtemp(prefix="cut-shortlist-", dir=_TMP))
    (tmp / "channels").mkdir()
    (tmp / "shared").mkdir()
    # The readers this script imports both look under the root: `_runlog.py`
    # for shared/runlog/runlog.py and `_channel_ids.py` for
    # shared/channel_ids.py. Symlinks keep the miniature root a plausible one.
    (tmp / "shared" / "runlog").symlink_to(_channel_ids.ROOT / "shared" / "runlog")
    (tmp / "shared" / "channel_ids.py").symlink_to(
        _channel_ids.ROOT / "shared" / "channel_ids.py")
    scope = {} if target is None else {"max_titles_per_batch": target}
    (tmp / "channels" / f"{CHANNEL}.json").write_text(
        json.dumps({"channel": CHANNEL, "scope": scope}, ensure_ascii=False))
    return tmp


def _write_batch(tmp, doc, stage):
    batch = tmp / "pipeline" / CHANNEL / "B"
    batch.mkdir(parents=True)
    out_path = batch / "02-compliance-checker.json"
    stage_path = batch / "01-trend-hunter.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False))
    stage_path.write_text(json.dumps(stage, ensure_ascii=False))
    return out_path, stage_path


def _run_cli(tmp, args):
    env = dict(os.environ, FACTORY_ROOT=str(tmp))
    env.pop("RUNLOG_BATCH", None)
    return subprocess.run([sys.executable, str(SCRIPTS / "cut_shortlist.py"), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_the_command_line_writes_the_cut_into_the_file():
    tmp = _temp_root()
    # Four publishable, two held: the four take their slots, the `review` at
    # rank 2 takes the fifth, the `review` at rank 7 has none left (CF-0335).
    doc, stage = a_batch(["clear", "review", "caution", "blocked", "blocked",
                          "clear", "review", "clear"])
    out_path, stage_path = _write_batch(tmp, doc, stage)
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL])
    assert proc.returncode == 0, proc.stderr
    assert "t7: reserve (reserve_unused)" in proc.stdout, proc.stdout
    assert "t2: carried and HELD" in proc.stdout, proc.stdout
    assert ("8 judged, 6 eligible, 5 carried (1 of them held for publication), "
            "1 reserve, 2 refused" in proc.stdout), proc.stdout
    written = json.loads(out_path.read_text())
    assert ids(written["results"]) == ["t1", "t2", "t3", "t4", "t5", "t6", "t8"], (
        "results[] keeps the refused rows and the shortlist order")
    assert ids(written["reserve"]) == ["t7"]
    assert written["cut"]["target"] == TARGET
    assert written["cut"]["target_from"] == TARGET_FROM


def test_the_command_line_with_no_target_writes_no_cut():
    tmp = _temp_root(target=None)
    doc, stage = a_batch(["clear"] * 8)
    out_path, stage_path = _write_batch(tmp, doc, stage)
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL])
    assert proc.returncode == 0, proc.stderr
    assert "no cut" in proc.stdout, proc.stdout
    written = json.loads(out_path.read_text())
    assert len(written["results"]) == 8 and written["reserve"] == []


def test_dry_run_writes_nothing():
    tmp = _temp_root()
    doc, stage = a_batch(["clear"] * 8)
    out_path, stage_path = _write_batch(tmp, doc, stage)
    before = out_path.read_text()
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL, "--dry-run"])
    assert proc.returncode == 0, proc.stderr
    assert out_path.read_text() == before
    assert "dry run, nothing written" in proc.stdout


def test_the_command_line_refuses_the_content_researcher_pass():
    """`04-compliance-checker.json` has no shortlist and no batch target - by
    then the topics are scripts, and the cut has already happened."""
    tmp = _temp_root()
    doc, stage = a_batch(["clear"] * 8)
    doc["stage_checked"] = "03-content-researcher"
    out_path, stage_path = _write_batch(tmp, doc, stage)
    proc = _run_cli(tmp, [str(out_path), str(stage_path), CHANNEL])
    assert proc.returncode == 2, proc.stdout
    assert "refusing" in proc.stdout
    assert json.loads(out_path.read_text()) == doc, "the file must be left alone"


def test_usage_error_is_exit_2():
    tmp = _temp_root()
    proc = _run_cli(tmp, [])
    assert proc.returncode == 2
    assert "usage:" in proc.stdout


# --------------------------------------------------------------------------
# SKILL.md - the text the agent actually reads
# --------------------------------------------------------------------------
def _skill():
    assert SKILL.is_file(), SKILL
    return SKILL.read_text()


def test_the_skill_says_the_pass_judges_the_whole_shortlist():
    text = _skill()
    assert "shortlist" in text.lower(), "SKILL.md never mentions the shortlist"
    for fragment in ("cut_shortlist.py", "CF-0265", "reserve"):
        assert fragment in text, f"SKILL.md does not mention {fragment}"
    assert "max_titles_per_batch" in text, (
        "SKILL.md should name the number the cut reads, so the agent does not "
        "invent one")


def test_the_skill_puts_the_cut_after_the_rights_holder_step():
    """CF-0420's step 4b can turn a rights-only `review` into a `clear`, which
    moves the topic from the held class into the publishable one (CF-0335). A
    cut taken before that would order the batch on a verdict that no longer
    stands. (Until CF-0420 this was the blooper relaxation's place.)"""
    text = _skill()
    step = text.index("rights_holder_info.py \\")
    cut_at = text.index("cut_shortlist.py \\")
    assert step < cut_at, (
        "the cut must be run after step 4b - 4b settles the verdicts, the cut "
        "decides who fits")


def test_the_skill_says_the_agent_does_not_cut_by_hand():
    text = _skill()
    for fragment in ("2026-09-17", "Spire-Runner"):
        assert fragment in text, (
            f"SKILL.md should carry {fragment} - the decision's date and the slot "
            f"that was lost are why the cut moved here")


def test_the_skill_names_the_one_exception_to_the_order():
    """CF-0265's "never re-sorted by verdict" is revised in one place, and the
    SKILL has to say where and on whose decision."""
    text = _skill()
    for fragment in ("CF-0335", "2026-09-23", "publishable"):
        assert fragment in text, f"SKILL.md does not mention {fragment}"
    assert "never re-sorts by verdict" not in text, (
        "the old absolute wording is what CF-0335 revises")


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

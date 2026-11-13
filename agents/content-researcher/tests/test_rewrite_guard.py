#!/usr/bin/env python3
"""CF-0430: a step-6 gate re-run on an unchanged script spends nothing.

`scripts/_rewrite_guard.py` is the one rule the five gates that count attempts
share. These tests pin the rule itself - what the hash is taken over, when a
record counts as "the rewrite this gate asked for, not made", what the run
says - and that every one of the five gates goes through it rather than
carrying a copy. Each gate's own suite drives the rule through that gate's
real `check_batch()` (`test_cf0430_*`).
"""
import json
import os
import sys
import tempfile
from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-rewrite-guard-")
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(dir=_TMP))

import _rewrite_guard as rg  # noqa: E402
import _unchanged  # noqa: E402

GATES = ("check_narration_budget.py", "check_anchor_coverage.py", "check_block_capacity.py",
         "check_alternate_sides.py", "check_anchor_cadence.py")


def _script(**over):
    s = {"script_id": "s1", "topic_id": "t1",
         "hook": "one two three", "commentary": "four five six seven", "payoff": "eight nine",
         "visual_anchors": [{"anchor_id": "v0", "phrase": "a door", "beat_text": "four five"},
                            {"anchor_id": "v1", "phrase": "a key", "beat_text": "eight"}],
         "pattern": {"pattern_id": "list", "rhythm_id": "hold"},
         "narration": {"estimated_words_per_second": 2.5}}
    s.update(over)
    return s


def _asked(script, key="anchor_cadence", **over):
    """The record a gate's `--write` left: a rewrite asked of this very text."""
    record = rg.stamp(dict({"action": "rewrite", "failed_attempts": 1,
                            "reason": "stretch v0 -> v1 is 9.1s over the band"}, **over),
                      script)
    script[key] = record
    return record


# --------------------------------------------------------------------------
# the hash
# --------------------------------------------------------------------------

def test_the_hash_is_the_text_and_the_anchors():
    base = rg.script_hash(_script())
    assert base.startswith("sha256:") and len(base) == len("sha256:") + 64
    for field, value in (("hook", "one two four"), ("commentary", "four five six"),
                         ("payoff", "eight ten")):
        assert rg.script_hash(_script(**{field: value})) != base, field
    moved = _script()
    moved["visual_anchors"][1]["beat_text"] = "nine"
    assert rg.script_hash(moved) != base, "an anchor moved is a rewrite"
    renamed = _script()
    renamed["visual_anchors"][0]["phrase"] = "an open door"
    assert rg.script_hash(renamed) != base, "an anchor re-aimed is a rewrite"
    added = _script()
    added["visual_anchors"].append({"anchor_id": "v2", "phrase": "x", "beat_text": "six"})
    assert rg.script_hash(added) != base


def test_whitespace_is_not_a_rewrite():
    base = rg.script_hash(_script())
    assert rg.script_hash(_script(payoff="eight  nine ")) == base
    assert rg.script_hash(_script(hook="one\ntwo three")) == base


def test_the_hash_ignores_what_the_gates_write_and_the_draw():
    """A gate writes its record, the budget writes `narration`, the fit
    rewrites `pattern` - none of that is the writer's rewrite, and a hash that
    moved with it would let every re-run through."""
    s = _script()
    base = rg.script_hash(s)
    s["anchor_cadence"] = {"action": "rewrite", "failed_attempts": 1}
    s["narration"] = {"estimated_words_per_second": 3.1, "action": "pass"}
    s["pattern"] = {"pattern_id": "list", "voice_fit": {"verdict": "recomputed"}}
    s["scene_direction"] = {"description": "changed"}
    assert rg.script_hash(s) == base


def test_the_hash_does_not_move_when_the_file_is_written_again():
    s = _script()
    again = json.loads(json.dumps(s, indent=2, sort_keys=True))
    assert rg.script_hash(again) == rg.script_hash(s)
    reordered = dict(reversed(list(s.items())))
    reordered["visual_anchors"] = [dict(reversed(list(a.items())))
                                   for a in s["visual_anchors"]]
    assert rg.script_hash(reordered) == rg.script_hash(s)


def test_a_channels_own_section_is_hashed_when_the_gate_names_it():
    s = _script(outro="bye")
    edited = _script(outro="bye now")
    assert rg.script_hash(s) == rg.script_hash(edited), "not a section anyone reads"
    assert (rg.script_hash(s, ("hook", "outro")) != rg.script_hash(edited, ("hook", "outro")))
    # the order the channel lists its sections in is not a change
    assert rg.script_hash(s, ("outro", "hook")) == rg.script_hash(s, ("hook", "outro"))


# --------------------------------------------------------------------------
# which record the rule applies to
# --------------------------------------------------------------------------

def test_only_a_rewrite_of_this_very_text_is_unchanged():
    s = _script()
    record = _asked(s)
    assert rg.unchanged(s, "anchor_cadence") is record
    assert rg.unchanged(s, "block_capacity") is None, "another gate's record is not this one"
    _unchanged.edit(s)
    assert rg.unchanged(s, "anchor_cadence") is None, "edited: judged again"


def test_a_pass_a_warning_and_a_rejected_draw_are_judged_again():
    for action in ("pass", "warn", "refuse", "reject", "reject_assignment", "accept_short"):
        s = _script()
        _asked(s, action=action)
        assert rg.unchanged(s, "anchor_cadence") is None, action


def test_a_record_written_before_this_task_is_judged_as_before():
    s = _script()
    s["anchor_cadence"] = {"action": "rewrite", "failed_attempts": 1}
    assert rg.unchanged(s, "anchor_cadence") is None


# --------------------------------------------------------------------------
# what the run does with it
# --------------------------------------------------------------------------

def test_split_sets_the_unchanged_aside_and_says_so():
    kept, asked = _script(script_id="a"), _script(script_id="b")
    _asked(asked)
    lines = []
    judge, unchanged, problems = rg.split([kept, asked], "anchor_cadence",
                                          out=lines.append)
    assert judge == [kept] and unchanged == [asked]
    assert problems == [f"b: {rg.UNCHANGED} (last run: stretch v0 -> v1 is 9.1s over the band)"]
    assert len(lines) == 1 and rg.UNCHANGED in lines[0] and "UNCHANGED b:" in lines[0]
    assert "failed_attempts stays 1" in lines[0]
    assert rg.RERUNS_KEY not in asked["anchor_cadence"], "a read-only run writes nothing"


def test_write_counts_the_refused_rerun_and_never_the_attempt():
    s = _script()
    record = _asked(s)
    for n in (1, 2, 3):
        rg.split([s], "anchor_cadence", out=lambda *_: None, write=True)
        assert record[rg.RERUNS_KEY] == n
        assert record["failed_attempts"] == 1


# --------------------------------------------------------------------------
# one rule, not five copies
# --------------------------------------------------------------------------

def test_every_gate_that_counts_attempts_goes_through_the_one_rule():
    for name in GATES:
        src = (AGENT_ROOT / "scripts" / name).read_text()
        assert "import _rewrite_guard as rg" in src, name
        assert "rg.split(" in src and "rg.stamp(" in src, name
        assert "hashlib" not in src, f"{name}: the hash is _rewrite_guard's, not a copy"
        assert rg.UNCHANGED not in src, f"{name}: the word is _rewrite_guard's, not a copy"


def test_the_skill_states_the_rule_in_step_6():
    skill = (AGENT_ROOT / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
    step6 = skill[skill.index("6. **Hold the batch to the budget"):skill.index("6b. **")]
    assert rg.UNCHANGED in step6, "the word the gates print"
    for needle in ("CF-0430", "script_hash", "unchanged_reruns", "_rewrite_guard.py",
                   "A rerun without an edit spends nothing"):
        assert needle in step6, needle
    for gate in GATES:
        assert gate in step6, gate


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

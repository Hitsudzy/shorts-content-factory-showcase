#!/usr/bin/env python3
"""CF-0370: under `even`, a drawn block-count top budgets the chain - the rest
of a segment is held, not cut into more blocks.

`you-can-see-everything` (example-film/2026-09-23T1722Z, lf-2026-09-23-004,
`moment-breakdown`/`even`): 10 segments, trailer shots of ~1.86 s, and the
resolver chained 1-4 shots per segment - 22 blocks against the drawn band
6-12, refused `pattern_ceiling` after the wav.

Pinned here:
- which bands budget the chain (drawn count only) and the budget arithmetic;
- the greedy budget on 004's real per-segment shot counts lands at the top;
- the resolver asks for the budget only on unordered segments, and a capped
  segment holds its last picture instead of carrying the shortfall;
- the storyboard record and its numbers when the layout alone is over the top.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors  # noqa: E402
import rhythm  # noqa: E402


def _pattern(mode="drawn", lo=6, hi=12, key="block_count"):
    return {"pattern_id": "moment-breakdown",
            "parameters": {key: {"mode": mode, "min": lo, "max": hi}}}


# 004 as the resolver cut it: shots per segment, in segment order (storyboard
# word_range groups 0, 11, 18, 44, 52, 68, 89, 108, 142, 157).
SHOTS_004 = [1, 1, 3, 1, 3, 4, 2, 2, 3, 2]


def test_only_a_drawn_count_band_budgets_the_chain():
    assert rhythm.block_count_ceiling(_pattern()) == 12
    assert rhythm.block_count_ceiling(_pattern(mode="emergent")) is None
    assert rhythm.block_count_ceiling(_pattern(mode="floor_drawn")) is None
    assert rhythm.block_count_ceiling(_pattern(key="block_rate_per_minute")) is None
    assert rhythm.block_count_ceiling(None) is None
    assert rhythm.block_count_ceiling({"parameters": {}}) is None


def test_the_budget_leaves_every_later_segment_one_picture():
    assert rhythm.even_shot_budget(None, 0, 9) is None
    assert rhythm.even_shot_budget(12, 0, 9) == 3
    assert rhythm.even_shot_budget(12, 5, 6) == 1
    # never fewer than one: a segment with no picture is a hole, not a hold
    assert rhythm.even_shot_budget(12, 11, 3) == 1


def test_the_budget_never_leaves_a_hold_over_the_hold_band():
    # 004's segment 8 after an unfilled anchor was carried into it: 9.49 s
    # against moment-breakdown's hold top 9.0 - one held frame would be a
    # hold break, so it gets two pictures even at the count's last slot.
    assert rhythm.even_shot_budget(12, 11, 0, seconds=9.49, hold_top=9.0) == 2
    assert rhythm.even_shot_budget(12, 11, 0, seconds=8.9, hold_top=9.0) == 1
    # half a frame over the top is not a frame the viewer sees (CF-0303)
    assert rhythm.even_shot_budget(12, 11, 0, seconds=9.01, hold_top=9.0) == 1
    assert rhythm.even_shot_budget(12, 0, 9, seconds=20.0, hold_top=9.0) == 3


def test_004_under_the_budget_is_inside_the_band():
    assert sum(SHOTS_004) == 22
    top, blocks = 12, 0
    for si, natural in enumerate(SHOTS_004):
        budget = rhythm.even_shot_budget(top, blocks, len(SHOTS_004) - si - 1)
        blocks += min(natural, budget)
    assert 6 <= blocks <= 12, blocks


def test_the_real_pattern_file_budgets_moment_breakdown():
    pattern = rhythm.load_pattern("moment-breakdown", resolve_anchors.PATTERNS_DIR)
    if pattern is None:
        return  # a checkout without the factory root beside it
    assert rhythm.block_count_ceiling(pattern) == 12
    assert rhythm.block_count_ceiling(
        rhythm.load_pattern("explainer", resolve_anchors.PATTERNS_DIR)) is None


def _loop():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    return src.split("for si, seg in enumerate(segments):")[1].split(
        "# If the earliest anchor(s) never produced a block")[0]


def test_the_resolver_budgets_only_unordered_segments_and_holds():
    loop = _loop()
    assert ("if band_top is not None and not is_ordered_segment(seg):" in loop)
    cap = loop.index("rhythm.even_shot_budget(")
    fill = loop.index("def fill(pool, reuse_key=None, length_first=False):")
    assert cap < fill, "the budget has to be set before the chain is cut"
    # the held branch sits before the CF-0028 carry and takes the span over
    hold = loop.index("if capped_by_band and t < end and len(used) >= budget")
    carry = loop.index("if t < end and blocks:\n            # Candidates ran out")
    assert hold < carry
    assert "t = end" in loop[hold:carry]
    # and a hold over the pattern's hold band is not made
    assert loop.index("over_hold = (") < hold
    assert "not over_hold" in loop[hold:carry]
    # the last picture's span, for the CF-0337 repeat guard, is the block's
    assert "last_slot = budget == 1 or (capped_by_band" in loop


def test_the_record_says_the_layout_alone_is_over_the_top():
    segs = [{}] * 14
    rec = resolve_anchors.block_band_report(12, _pattern(), segs, [{}] * 14, [])
    assert rec["layout_over_top_by"] == 2 and rec["over_top_by"] == 2, rec
    assert resolve_anchors.block_band_report(None, _pattern(), segs, [], []) is None


def test_a_capped_entry_carries_the_hold_in_numbers():
    u = {"key": ("/f/jsw92T7KpqM.mp4", 48), "shot": 48, "seconds": 1.2}
    held = resolve_anchors.band_cap_entry(5, 1, 1, 13.95, 18.93, 13.95, u,
                                          True, "still")
    assert held["held_seconds"] == 4.98 and not held["hold_failed"], held
    failed = resolve_anchors.band_cap_entry(5, 1, 1, 13.95, 18.93, 13.95, u,
                                            False, "clip")
    assert failed["hold_failed"] and failed["held_seconds"] == 0.0, failed
    assert "FAILED" in resolve_anchors.band_cap_note(failed)
    played = resolve_anchors.band_cap_entry(
        5, 2, 2, 13.95, 18.93, 17.9, {**u, "seconds": 1.1}, False, "clip")
    assert not played["hold_failed"] and played["last_block_seconds"] == 1.03


# --------------------------------------------------------------------------
# item 2: the refusal text says what the count is on `even`
# --------------------------------------------------------------------------

def _short(measured=22):
    return {"kind": "pattern_shortfall",
            "code": rhythm.PATTERN_BLOCK_COUNT_OUTSIDE_BAND,
            "pattern_id": "moment-breakdown", "parameter": "block_count",
            "mode": "drawn", "measured": measured, "band_min": 6, "band_max": 12,
            "outside_by": measured - 12, "note": f"{measured} blocks"}


def _brp():
    import build_render_plan
    return build_render_plan


def test_an_even_break_before_the_budget_sends_it_back_to_the_resolver():
    brp = _brp()
    rec = brp.pattern_ceiling_break([_short()], [], [], None, None, "even")
    lines = brp.pattern_ceiling_lines(rec)
    text = " ".join(lines)
    assert "number of resolved anchors" not in text, lines
    assert "no trim moves it" not in lines[1], lines[1]
    assert "22 shots the resolver chained" in lines[1], lines[1]
    assert "re-run this video from the resolver" in lines[-1], lines[-1]


def test_an_even_break_over_the_layout_says_it_in_segments():
    brp = _brp()
    cap = resolve_anchors.block_band_report(12, _pattern(), [{}] * 14,
                                            [{}] * 14, [])
    rec = brp.pattern_ceiling_break([_short(14)], [], [], None, cap, "even")
    lines = brp.pattern_ceiling_lines(rec)
    assert "the layout itself has 14 segments" in lines[1], lines[1]
    assert "2 over the top" in lines[1], lines[1]
    assert brp.PICTURE_BAND_RECORD_PATH in lines[-1], lines[-1]


def test_an_ordered_break_still_counts_the_layout():
    brp = _brp()
    rec = brp.pattern_ceiling_break([_short()], [], [], None, None, "hold")
    lines = brp.pattern_ceiling_lines(rec)
    assert "number of segments the rhythm laid the anchors out in" in lines[1]
    assert "no trim moves it" in lines[1], lines[1]
    assert "plan_blocks.py" in lines[-1], lines[-1]
    assert "number of anchors the script resolved" not in \
        " ".join(brp.CADENCE_BAND_NOTES)


def test_the_planner_hands_the_storyboard_record_to_the_gate():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    # CF-0428 added the storyboard and the blocks (the pool bound) after it.
    assert ('story_rhythm.get("block_band_cap"),\n'
            '                                    story_rhythm.get("rhythm_built"),\n'
            '                                    story=story, blocks=blocks)'
            ) in src


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

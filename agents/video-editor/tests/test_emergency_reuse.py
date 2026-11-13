#!/usr/bin/env python3
"""CF-0137: the emergency shot repeat - one per video, and recorded as a
shortage of material.

CF-0123 declared the per-block assetless rung brak, which leaves a block whose
anchor resolved to nothing without an answer. The ladder CF-0137 builds for it
is: a library insert (CF-0138, not here yet), then *one* repetition of a shot
the video has already shown, then the assetless rung only where the channel
switched it on, then the planner refusing the plan (tests/test_assetless_rung_
gate.py).

This file pins the second rung and its three limits:

  * one per **video**, not per shot and not per block. The counter is
    `MAX_EMERGENCY_REUSE_PER_VIDEO`, a different shape from `MAX_SHOT_REUSE`
    on purpose - raising the latter to 2 would license a second showing of
    every shot in the video, which is the CF-0026 defect;
  * never adjacent to its own first use, because `alternation_report()` reads
    a repeated adjacent pair as a swing that did not happen (CF-0034);
  * never inside a swing block at all - CF-0074 ("only distinct shots inside
    a swing block") is not reopened; what changes there is the alternative,
    from a stand-in to the planner's refusal.

and the record: an `emergency_reuse` entry in `rhythm_shortfalls`, a
`plan["rhythm"]["emergency_reuse"]` report, and `videos[].emergency_reuse` in
the batch metadata. A repeat nobody can see downstream is a material shortage
hidden rather than reported, which is the thing CF-0123 was about.

Pure arithmetic over block lists plus one in-process
`write_batch_metadata.video_record()`. No footage, no CLIP, no ffmpeg. No
pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors  # noqa: E402
import rhythm  # noqa: E402
import write_batch_metadata  # noqa: E402

HOLD = 2.5


def order(rhythm_id="staccato", pattern_id="explainer", **params):
    base = {"block_count": None, "key_frame_hold_seconds": HOLD,
            "opening_block": "hook_over_footage",
            "acceleration_to_payoff": {"enabled": False, "strength": None}}
    base.update(params)
    return {"pattern_id": pattern_id, "rhythm_id": rhythm_id, "parameters": base}


def block(shot, seconds=2.0, start=0.0, role="beat", reuse=None, side=None):
    b = {"start": round(start, 3), "end": round(start + seconds, 3),
         "asset": {"kind": "clip", "path": f"{shot}.mp4"}, "shot": shot,
         "rhythm_role": role, "side": side}
    if reuse is not None:
        b["emergency_reuse"] = reuse
    return b


def laid_out(*specs):
    """Blocks end to end. Each spec is (shot, reuse_reason or None)."""
    out, t = [], 0.0
    for shot, reason in specs:
        rec = None if reason is None else {"shot": shot, "reason": reason}
        out.append(block(shot, 2.0, t, reuse=rec))
        t += 2.0
    return out


# --------------------------------------------------------------------------
# the budget: one per video, and a different shape from MAX_SHOT_REUSE
# --------------------------------------------------------------------------

def test_the_budget_is_one_per_video_and_the_second_ask_is_refused():
    """The whole point of item 2.2: 'exactly one for the entire video: one
    single repetition, not one repetition per shot'. The second block that
    wants one is refused, and the refusal names the video, not the shot."""
    b = rhythm.EmergencyReuseBudget()
    assert b.max_uses == 1, b.max_uses
    assert b.available() and b.remaining == 1
    assert b.allow("beat", ("a.mp4", 3)) is None
    b.take({"shot": "a:3", "block": 5, "reason": "nothing left"})
    assert b.spent == 1 and b.remaining == 0
    assert not b.available()
    refusal = b.allow("beat", ("b.mp4", 7))
    assert refusal and "already spent" in refusal, refusal
    # and a caller that ignores the refusal cannot spend it anyway
    try:
        b.take({"shot": "b:7"})
    except rhythm.RhythmError:
        pass
    else:
        raise AssertionError("a spent budget let a second repeat through")
    assert b.spent == 1, b.records()


def test_the_constant_is_a_video_counter_and_max_shot_reuse_is_untouched():
    """Item 5: the budget lives beside `MAX_SHOT_REUSE` and is deliberately
    of another shape. `ShotLedger` must not have learned about it - if the
    two ever became the same number, one emergency repeat would turn into a
    licence for every shot in the video to appear twice (CF-0026 / CF-0121).
    """
    assert rhythm.MAX_SHOT_REUSE == 1, rhythm.MAX_SHOT_REUSE
    assert rhythm.MAX_EMERGENCY_REUSE_PER_VIDEO == 1
    ledger = rhythm.ShotLedger()
    assert ledger.max_uses == rhythm.MAX_SHOT_REUSE
    ledger.take(("a.mp4", 1))
    assert ledger.blocked(("a.mp4", 1)), "the per-sample cap stopped holding"
    src = (SCRIPTS / "rhythm.py").read_text()
    ledger_src = src.split("class ShotLedger:")[1].split("\n# ---")[0]
    assert "MAX_EMERGENCY_REUSE_PER_VIDEO" not in ledger_src, (
        "ShotLedger reads the emergency budget - the per-sample cap and the "
        "per-video counter have been collapsed into one number")


def test_a_repeat_may_not_sit_next_to_its_own_first_use():
    """CF-0074/CF-0034: a repeated adjacent pair is what
    `alternation_report()` counts as a failed swing, so the one repeat may
    not be spent buying a picture by breaking the cadence it was to save."""
    b = rhythm.EmergencyReuseBudget()
    assert b.allow("beat", ("a.mp4", 3), prev_keys={("a.mp4", 3)}) == \
        rhythm.REUSE_REFUSED_ADJACENT
    # a different shot in the previous block is fine
    assert b.allow("beat", ("a.mp4", 3), prev_keys={("b.mp4", 9)}) is None
    # the refusal costs nothing: the video still has its repeat
    assert b.available() and b.spent == 0


def test_inside_a_swing_block_the_repeat_is_refused_outright():
    """Item 3: CF-0074 does not unwind. Inside a swing the alternative
    changes from a stand-in to the planner's refusal - so the budget says no
    even when it is completely unspent and the shot is nowhere near."""
    b = rhythm.EmergencyReuseBudget()
    assert b.allow("swing", ("a.mp4", 3), prev_keys=set()) == \
        rhythm.REUSE_REFUSED_SWING
    assert "CF-0074" in rhythm.REUSE_REFUSED_SWING
    assert b.available(), "a swing refusal must not spend the video's repeat"


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------

def test_the_report_reads_the_first_use_back_off_the_plan():
    """`emergency_reuse_report()` does not trust the resolver's own note for
    where the shot's other showing is - it points at a block of the plan that
    shipped, and checks the adjacency rule against it."""
    blocks = laid_out(("s:1", None), ("s:2", None), ("s:3", None),
                      ("s:1", "every candidate failed to cut"))
    rep = rhythm.emergency_reuse_report(blocks)
    assert rep["budget"] == 1 and rep["used"] == 1, rep
    r = rep["reuses"][0]
    assert r["block"] == 3 and r["shot"] == "s:1", r
    assert r["also_in_blocks"] == [0], r
    assert r["adjacent_to_first_use"] is False, r
    assert r["reason"] == "every candidate failed to cut", r
    assert r["seconds"] == 2.0, r
    # a clean plan still carries the record, it just spent nothing
    clean = rhythm.emergency_reuse_report(laid_out(("s:1", None), ("s:2", None)))
    assert clean == {"budget": 1, "used": 0, "reuses": []}, clean


def test_the_report_catches_a_repeat_that_did_land_next_to_its_first_use():
    """`adjacent_to_first_use` is a check on the shipped plan, not a field
    somebody fills in - it is how a resolver bug that got past
    `EmergencyReuseBudget.allow()` is found afterwards."""
    blocks = laid_out(("s:1", None), ("s:1", "no shot in any index"))
    r = rhythm.emergency_reuse_report(blocks)["reuses"][0]
    assert r["adjacent_to_first_use"] is True, r


def test_the_repeat_is_a_shortfall_of_the_rhythm_not_of_the_picture():
    """The block has a picture, so none of CF-0136's kinds fires and
    `rhythm_delivered` is untouched. What fell short is the material, and
    `rhythm_delivered_fully` has to say so - otherwise the repeat is a defect
    the metadata hides, which is the whole failure CF-0123 was about."""
    blocks = laid_out(("s:1", None), ("s:2", None), ("s:3", None),
                      ("s:1", "every remaining candidate was already used"))
    shortfalls = rhythm.rhythm_shortfalls(order(), blocks)
    kinds = [s["kind"] for s in shortfalls]
    assert kinds == ["emergency_reuse"], kinds
    s = shortfalls[0]
    assert s["block"] == 3 and s["shot"] == "s:1", s
    assert s["also_in_blocks"] == [0], s
    assert s["budget"] == 1 and s["used"] == 1, s
    assert "needs material" in s["note"], s["note"]
    # no picture kind fires: every block has one
    assert rhythm.picture_absent_shortfalls(order(), blocks) == []
    # and the video is delivered-but-not-fully, the CF-0057 shape
    delivered, _ = rhythm.verify_rhythm(order(), blocks)
    assert bool(delivered) and bool(shortfalls), (delivered, kinds)


def test_the_batch_metadata_carries_the_repeat_to_the_analyst():
    """Item 4: the signal has to reach outside the plan. `videos[].
    emergency_reuse` is the record, and a plan built before CF-0137 says
    `null` rather than claiming it needed no repeat."""
    blocks = laid_out(("s:1", None), ("s:2", None), ("s:1", "no shot in any index"))
    plan = {
        "script_id": "cf-0137",
        "style": "motion",
        "duration": {"actual": 6.0, "target": [1, 60], "deviation": 0},
        "blocks": blocks,
        "rhythm": {
            "rhythm_requested": "staccato", "rhythm_delivered": "staccato",
            "rhythm_shortfalls": rhythm.rhythm_shortfalls(order(), blocks),
            "rhythm_delivered_fully": False,
            "emergency_reuse": rhythm.emergency_reuse_report(blocks),
        },
    }
    qc = {"passed": True, "verdict": "pass", "checks": []}
    v = write_batch_metadata.video_record("cf-0137", plan, "video.mp4", qc, "motion")
    assert v["emergency_reuse"]["used"] == 1, v["emergency_reuse"]
    assert v["emergency_reuse"]["reuses"][0]["shot"] == "s:1"
    assert [s["kind"] for s in v["rhythm_shortfalls"]] == ["emergency_reuse"]

    bare = json.loads(json.dumps(plan))
    bare["rhythm"].pop("emergency_reuse")
    old = write_batch_metadata.video_record("cf-0137", bare, "video.mp4", qc, "motion")
    assert old["emergency_reuse"] is None, old["emergency_reuse"]


# --------------------------------------------------------------------------
# the resolver climbs the rung
# --------------------------------------------------------------------------

def test_the_resolver_holds_the_ladder_in_the_documented_order():
    """The rung is climbed in resolve_anchors.py, before `unfilled_block()`
    is reached: the emergency attempt has to sit between the gate verdict and
    `settle_unresolved()`, or a block that could have been repeated goes to
    the assetless rung anyway. Structural, because the behavioural version
    needs real footage."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    loop = src.split("for si, seg in enumerate(segments):")[1].split("def block_for")[0]
    attempt = loop.index("reuse_budget.allow(")
    # The *last* settle site is the one after the gate verdict - the branch a
    # block with candidates that all failed reaches, which is where the rung
    # exists. (The earlier site is "no shot in any index": nothing that block
    # matches is on screen anywhere, so there is nothing to repeat, and its
    # answer stays the assetless rung and rung 4 under it.)
    settle = loop.rindex("settled = settle_unresolved(")
    assert attempt < settle, (
        "the emergency repeat is attempted after the block has already been "
        "settled onto the assetless rung")
    # only where an assetless block would actually be produced
    assert "if not used and is_ordered_segment(seg):" in loop, (
        "the emergency repeat is no longer restricted to ordered segments - "
        "on `even` there is no assetless block to save, only CF-0124's carry")
    # and the cap may only be bypassed through the named key
    fill = src.split("def fill(pool, reuse_key=None, length_first=False):")[1].split("return used, capped")[0]
    assert "ledger.blocked(shot_key) and shot_key != reuse_key" in fill, (
        "fill() no longer refuses every blocked candidate but the one the "
        "budget named")


def test_the_marker_survives_the_storyboard_into_the_plan_and_its_report():
    """`carry_rhythm()` is the one place a storyboard field becomes a plan
    field, and plan.json is the only artefact write_batch_metadata.py and
    qc_render.py read. A repeat the resolver recorded and the planner dropped
    would be a material shortage that disappears between two stages - which is
    exactly the class of failure CF-0123 was about."""
    import build_render_plan  # noqa: E402 - imported here, it is heavy
    rec = {"shot": "pool:3", "reason": "every candidate was already used"}
    carried = build_render_plan.carry_rhythm(
        {"rhythm_role": "beat", "side": None, "shot": "pool:3",
         "held_frame": False, "emergency_reuse": rec})
    assert carried["emergency_reuse"] == rec, carried
    # ... and a block that spent none carries no key at all, so the report
    # counts only real repeats.
    clean = build_render_plan.carry_rhythm(
        {"rhythm_role": "beat", "shot": "pool:4", "held_frame": False})
    assert "emergency_reuse" not in clean, clean
    # The stderr line the planner prints off that report, formatted here so a
    # missing field in the record is caught by this suite rather than by a
    # NameError in the middle of a real run.
    plan_blocks = laid_out(("pool:3", None), ("pool:5", None),
                           ("pool:3", "every candidate was already used"))
    for r in rhythm.emergency_reuse_report(plan_blocks)["reuses"]:
        line = (f"EMERGENCY REPEAT block {r['block']}: shot {r['shot']} shown "
                f"again ({r['seconds']:.2f}s), already in block(s) "
                f"{r['also_in_blocks']} - this video needs material (CF-0137)")
        assert "pool:3" in line and "block 2" in line, line


def test_an_unfilled_block_still_reads_as_the_assetless_rung():
    """The rung below is untouched by CF-0137: when no repeat can be spent,
    `unfilled_block()` is still what the resolver produces, and it is still
    `asset_kind: typographic` for build_render_plan.py to refuse or render
    (tests/test_assetless_rung_gate.py decides which)."""
    anchor = {"phrase": "p", "word_index": 3, "emphasis_words": []}
    b = resolve_anchors.unfilled_block(anchor, {"role": "beat"}, 1.0, 2.4, "why")
    assert b["asset_kind"] == "typographic" and b["shot"] is None, b
    assert "emergency_reuse" not in b, b


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

#!/usr/bin/env python3
"""CF-0085: an ordered rhythm's unfillable segment stays a bounded block.

The defect is from run 2026-09-03T2037Z, Raygun (001): one source in the
pool, four usable shots, `staccato` ordered at 20 blocks with a 1.4s cap over
a 69.7s voice. Every segment that no candidate could fill was merged into the
previous block by `blocks[-1]["_end"] = end`, 25 of them in a row, and the
video shipped with 6 blocks, two of them 31.6s and 33s - the opposite of the
cadence ordered. An ordered rhythm gets a `typographic` block at the
planner's own bounds instead, which
build_render_plan.py renders on the assetless rung and records under
`degraded_blocks`.

CF-0124 finished the other half: `even` no longer stretches either. Its
segment has no bounds worth keeping, so there is no block to make of it - but
holding the previous clip past its own footage freezes it, so the span is
carried into the next anchor (CF-0028's remedy, same defect). Only the last
segment, with no next anchor and a voice that still has to be covered, keeps
the stretch.

Pure checks on `resolve_anchors.settle_unresolved()` plus one real
build_render_plan.py run on a storyboard carrying such blocks. No footage, no
CLIP, no index. No pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import resolve_anchors  # noqa: E402
import rhythm  # noqa: E402

# The Raygun shape: a 69.7s voice with anchors at the density the real script
# had (26 anchors, about one every 2.7s), ordered as staccato at 20 blocks
# with a 1.4s cap - the numbers RUN_LOG.txt:38-43 recorded.
VOICE_SECONDS = 69.7
ANCHOR_STARTS = [round(0.9 + i * 2.7, 2) for i in range(26)]
STACCATO = {"pattern_id": "explainer", "rhythm_id": "staccato",
            "parameters": {"block_count": 20, "key_frame_hold_seconds": 1.4}}
CAP = 1.4


def _anchor(i):
    return {"word_index": i, "phrase": f"anchor {i}", "emphasis_words": []}


def _clip_block(seg):
    """A block a real clip filled, the way main() lays one down."""
    return {"word_range": [0, 0], "intent": "clip", "asset_kind": "clip",
            "asset": "/nowhere/a00.mp4", "rhythm_role": seg["role"],
            "side": None, "shot": "src:1", "held_frame": False,
            "_start": seg["start"], "_end": seg["end"]}


def _staccato_segments():
    segs = rhythm.plan_segments(ANCHOR_STARTS, VOICE_SECONDS, STACCATO)
    assert all(s["max_shots"] == 1 for s in segs), "staccato plans one shot per block"
    return segs


def test_a_single_unresolved_staccato_segment_is_its_own_bounded_block():
    """The one-segment case: the previous block keeps its end, the unfilled
    segment becomes a typographic block spanning exactly what the plan said."""
    segs = _staccato_segments()
    blocks = [_clip_block(segs[0])]
    prev_end = blocks[0]["_end"]
    seg = segs[1]
    settled = resolve_anchors.settle_unresolved(
        blocks, _anchor(1), seg, seg["start"], seg["end"],
        "every candidate failed to cut", has_next=True)
    assert settled == resolve_anchors.SETTLED_BLOCK, settled
    assert len(blocks) == 2, blocks
    assert blocks[0]["_end"] == prev_end, "the previous block was stretched"
    b = blocks[1]
    assert b["asset_kind"] == "typographic", b
    assert (b["_start"], b["_end"]) == (round(seg["start"], 3), round(seg["end"], 3)), b
    assert b["_end"] - b["_start"] <= CAP * 1.25 + 1e-6, "not bounded by the planner"
    assert b["side"] is None and b["shot"] is None and b["held_frame"] is False
    assert b["rhythm_role"] == seg["role"]
    assert b["unfilled_reason"] == "every candidate failed to cut"
    assert "asset" not in b, "an unfilled block has no file to point at"


def test_twenty_five_consecutive_unresolved_segments_stay_twenty_five_blocks():
    """The Raygun run itself: everything after the first block fails. Before
    the fix that was one block of ~68s; now it is the planned cadence, with
    every unfilled segment at its own planned length."""
    segs = _staccato_segments()
    blocks = [_clip_block(segs[0])]
    for i, seg in enumerate(segs[1:], start=1):
        # `has_next` is the carry test CF-0124 added for `even`; an ordered
        # segment has bounds of its own and ignores it, including on the last
        # segment - which is what "still covers the voice" below proves.
        resolve_anchors.settle_unresolved(
            blocks, _anchor(i), seg, seg["start"], seg["end"],
            "every remaining candidate was already used 3x elsewhere in this video",
            has_next=i + 1 < len(segs) - 1)
    assert len(blocks) == len(segs), (len(blocks), len(segs))
    lengths = [b["_end"] - b["_start"] for b in blocks]
    assert max(lengths) <= CAP * 1.25 + 1e-6, (
        f"a block grew to {max(lengths):.2f}s against a {CAP}s cap: {lengths}")
    # Block i is segment i, no block absorbed its neighbour.
    for b, s in zip(blocks, segs):
        assert (b["_start"], b["_end"]) == (round(s["start"], 3), round(s["end"], 3)), (b, s)
    assert blocks[-1]["_end"] == round(VOICE_SECONDS, 3), "the plan still covers the voice"
    # And the cadence the verifier reads is staccato's, not a 31s hold.
    plan_shaped = [{"start": b["_start"], "end": b["_end"],
                    "asset": {"kind": "clip" if b["asset_kind"] == "clip" else "procedural"}}
                   for b in blocks]
    c = rhythm.cadence(plan_shaped)
    assert c["cv"] <= rhythm.STACCATO_MAX_CV, c
    assert c["longest"] <= CAP * 1.25, c


def test_a_run_with_no_block_yet_still_starts_with_a_bounded_block():
    """The hole at the leading edge: nothing was resolved before this segment,
    so there is no previous block to stretch - and none is invented."""
    segs = _staccato_segments()
    blocks = []
    seg = segs[0]
    resolve_anchors.settle_unresolved(
        blocks, _anchor(0), seg, seg["start"], seg["end"], "no shot in any index",
        has_next=True)
    assert len(blocks) == 1 and blocks[0]["asset_kind"] == "typographic", blocks


def test_hold_and_alternate_segments_get_the_same_bounded_block():
    """The rule keys on the segment's own `max_shots: 1`, which every ordered
    rhythm sets, not on the rhythm id."""
    for rid in ("hold", "alternate"):
        order = {"rhythm_id": rid, "parameters": {"key_frame_hold_seconds": 3.0}}
        segs = rhythm.plan_segments(ANCHOR_STARTS[:6], 16.0, order,
                                    anchor_sides=["a", "b", "a", "b", "a", "b"])
        blocks = [_clip_block(segs[0])]
        seg = segs[1]
        assert resolve_anchors.settle_unresolved(
            blocks, _anchor(1), seg, seg["start"], seg["end"], "x",
            has_next=True) == resolve_anchors.SETTLED_BLOCK, rid
        assert blocks[0]["_end"] == segs[0]["end"], rid
        assert blocks[1]["asset_kind"] == "typographic", rid
        assert blocks[1]["side"] is None, "an unfilled swing carries no side"


def test_even_carries_a_fully_unresolved_segment_into_the_next_anchor():
    """`even` hands the segment to the next anchor instead of stretching:
    no new block, and the previous one keeps the end it earned (CF-0124)."""
    segs = rhythm.plan_segments(ANCHOR_STARTS[:4], 12.0, {"rhythm_id": "even"})
    assert all(s["max_shots"] is None for s in segs)
    blocks = [_clip_block(segs[0])]
    seg = segs[1]
    settled = resolve_anchors.settle_unresolved(
        blocks, _anchor(1), seg, seg["start"], seg["end"],
        "every candidate failed to cut", has_next=True)
    assert settled == resolve_anchors.SETTLED_CARRY, settled
    assert len(blocks) == 1, "even grew a new block it never had"
    assert blocks[0]["_end"] == segs[0]["end"], (
        "the previous block was stretched over the gap")


def test_the_last_even_segment_still_stretches_because_there_is_nowhere_to_carry():
    """The tail is the one place the old answer stands: no next anchor to carry
    into, and the plan still has to reach the end of the voice."""
    segs = rhythm.plan_segments(ANCHOR_STARTS[:4], 12.0, {"rhythm_id": "even"})
    blocks = [_clip_block(segs[0])]
    seg = segs[-1]
    settled = resolve_anchors.settle_unresolved(
        blocks, _anchor(3), seg, seg["start"], seg["end"], "x", has_next=False)
    assert settled == resolve_anchors.SETTLED_STRETCH, settled
    assert len(blocks) == 1
    assert blocks[0]["_end"] == round(seg["end"], 3), blocks


def test_a_run_of_unresolved_even_segments_reaches_the_next_real_block():
    """The Raygun shape on `even`, with footage again before the end.

    The caller's own bookkeeping is replayed here (`carry_start` into the next
    segment's `start`), because what the fix is worth is only visible over a
    run of segments: before it the first block swallowed every one of them and
    froze on its last frame. Now the whole run reaches the next anchor that
    resolves, which covers it with a picture that moves, and the plan is still
    gapless.
    """
    segs = rhythm.plan_segments(ANCHOR_STARTS[:8], 22.0, {"rhythm_id": "even"})
    blocks = [_clip_block(segs[0])]
    first_end = blocks[0]["_end"]
    carry_start = None
    for i, seg in enumerate(segs[1:-1], start=1):
        start = carry_start if carry_start is not None else seg["start"]
        carry_start = None
        settled = resolve_anchors.settle_unresolved(
            blocks, _anchor(i), seg, start, seg["end"], "x", has_next=True)
        assert settled == resolve_anchors.SETTLED_CARRY, (i, settled)
        carry_start = start
    assert len(blocks) == 1, "even invented blocks for segments with no picture"
    assert blocks[0]["_end"] == first_end, (
        f"the first block was stretched to {blocks[0]['_end']} over six "
        f"segments it has no footage for")
    # The last anchor resolves, and its block opens where the run of unfilled
    # segments began - six segments earlier, with no gap and no freeze.
    last = segs[-1]
    assert carry_start == segs[1]["start"], carry_start
    blocks.append(_clip_block({"role": last["role"], "start": carry_start,
                               "end": last["end"]}))
    assert blocks[1]["_start"] == blocks[0]["_end"], blocks
    assert blocks[-1]["_end"] == round(22.0, 3), "the plan still covers the voice"


def test_an_unresolved_even_tail_is_the_one_span_still_covered_by_a_stretch():
    """The limit of the carry, written down rather than left to be rediscovered.

    When nothing resolves from some anchor to the end of the voice, the carry
    walks the whole run to the last segment - and there it has nowhere left to
    go, so the previous block stretches over all of it exactly as it did before
    CF-0124. That is not the carry failing: the span has to be covered by
    something, and the only alternatives are a picture that does not exist and
    an assetless block for `even`, which is a question about what `even`
    delivers (CF-0123), not about geometry.
    """
    segs = rhythm.plan_segments(ANCHOR_STARTS[:8], 22.0, {"rhythm_id": "even"})
    blocks = [_clip_block(segs[0])]
    carry_start = None
    for i, seg in enumerate(segs[1:], start=1):
        start = carry_start if carry_start is not None else seg["start"]
        carry_start = None
        settled = resolve_anchors.settle_unresolved(
            blocks, _anchor(i), seg, start, seg["end"], "x",
            has_next=i + 1 < len(segs))
        if settled == resolve_anchors.SETTLED_CARRY:
            carry_start = start
    assert len(blocks) == 1, blocks
    assert blocks[0]["_end"] == round(22.0, 3), (
        "the tail was left uncovered - the plan has to reach the voice's end")


def test_main_settles_both_unresolved_sites_the_same_way():
    """A block with no picture is not the previous shot of anything, and a
    carried span has to reach `carry_start`: the source, not a test double, has
    to say so at both places where it settles a segment."""
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    calls = src.count(
        "settled = settle_unresolved(blocks, a, seg, start, end, reason, has_next)\n"
        "            if settled == SETTLED_BLOCK:\n"
        "                prev_shot = None\n"
        # CF-0137: and the shots of the block that just ended, which the
        # emergency repeat reads to keep itself off its own first use.
        "                prev_keys = set()\n"
        "            elif settled == SETTLED_CARRY:\n")
    assert calls == 2, f"expected both unresolved sites to settle alike, found {calls}"
    assert src.count("                carry_start = start\n") == 2, (
        "an unresolved site drops the span it was told to carry (CF-0124)")
    # Between the segment loop's head and block_for() (where both unresolved
    # sites sit) nothing may stretch the previous block directly any more.
    loop_head = src.split("for si, seg in enumerate(segments):")[1].split("def block_for")[0]
    assert 'blocks[-1]["_end"]' not in loop_head, (
        "an unresolved site still stretches the previous block")


# --------------------------------------------------------------------------
# build_render_plan.py renders the block it was handed
# --------------------------------------------------------------------------

# CF-0137: a channel config with the per-block assetless rung switched *on*.
# Since CF-0137 the rung is off by default on every channel, and
# build_render_plan.py refuses to write a plan that would ship a block with no
# picture (tests/test_assetless_rung_gate.py pins the refusal). The behaviour
# tested here is what happens *when the rung is allowed*, so these runs hand
# the planner a channel that allows it - the same "runs on a test config with
# the switch on, never on the real channel file" convention the insert layers
# use.
def _rung_on_channel(tmp):
    path = Path(tmp) / "rung-on-channel.json"
    path.write_text(json.dumps({
        "channel_id": "test-rung-on",
        "display_name": "Test Channel", "theme": STAND_IN_THEME,
        "assetless_block_rung": {
            "enabled": True,
            "reason": "test config only - CF-0137's rung is off on every real "
                      "channel, and this exercises the branch under it"},
    }))
    return ["--channel", str(path)]


def _silent_wav(path, seconds=6.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        # Not dead silence: leading_silence() would otherwise read the whole
        # file as lead, and a plan over an empty voice is not what is tested.
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = 2000 if (i // 40) % 2 else -2000
            frames += int(v).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def test_build_render_plan_renders_an_unfilled_block_on_the_assetless_rung():
    """End to end through the real script: a storyboard with a deliberate
    card and two unfilled staccato blocks builds, the unfilled ones come out
    `procedural` at their own bounds, and they are recorded as degradations
    by shortage - not as cards, which are on purpose."""
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
                  "end": round(0.9 + i * 0.5, 2)} for i in range(10)]
        (tmp / "words.json").write_text(json.dumps(words))
        segs = [(0.0, 1.4), (1.4, 2.8), (2.8, 4.2)]
        story = {
            "script_id": "cf-0085",
            "style": "motion",
            "resolved_from_anchors": True,
            "rhythm": {"pattern_requested": "explainer",
                       "rhythm_requested": "staccato", "rhythm_built": "staccato",
                       "parameters": {"block_count": 3, "key_frame_hold_seconds": 1.4},
                       "opening_requested": "count_card",
                       "opening_delivered": "count_card", "anchor_count": 3},
            "blocks": [
                {"word_range": [0, 0], "intent": "count card", "asset_kind": "card",
                 "card": {"kind": "count_card", "text": "3"}, "emphasis_words": [],
                 "rhythm_role": "opening_card", "side": None, "shot": None,
                 "held_frame": False, "_start": segs[0][0], "_end": segs[0][1]},
                resolve_anchors.unfilled_block(_anchor(1), {"role": "beat"},
                                               *segs[1], "every candidate failed to cut"),
                resolve_anchors.unfilled_block(_anchor(2), {"role": "beat"},
                                               *segs[2], "no shot in any index"),
            ],
            "unresolved_anchors": [], "rejected_candidates": [],
        }
        (tmp / "storyboard.json").write_text(json.dumps(story))
        out = tmp / "plan.json"
        result = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "motion", "--target-duration", "1", "60",
             *_rung_on_channel(tmp)],
            capture_output=True, text=True, cwd=tmp)
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        kinds = [b["asset"]["kind"] for b in plan["blocks"]]
        assert kinds == ["card", "procedural", "procedural"], kinds
        assert (plan["blocks"][1]["start"], plan["blocks"][1]["end"]) == segs[1], plan["blocks"][1]
        assert plan["blocks"][1].get("rhythm_role") == "beat"
        assert "side" not in plan["blocks"][1] or plan["blocks"][1]["side"] is None
        degraded = plan["degraded_blocks"]
        assert [d["index"] for d in degraded] == [1, 2], degraded
        assert all(d["from"] == "unfilled" and d["to"] == "typographic" for d in degraded), degraded
        assert degraded[0]["reason"] == "every candidate failed to cut", degraded
        assert degraded[1]["reason"] == "no shot in any index", degraded
        # The cadence survived the shortage: three bounded blocks, not one.
        assert plan["rhythm"]["cadence"]["block_count"] == 3, plan["rhythm"]["cadence"]
        assert "DEGRADED block 1: unfilled -> typographic" in result.stderr, result.stderr[-1500:]


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

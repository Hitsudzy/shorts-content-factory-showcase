#!/usr/bin/env python3
"""CF-0136: a picture that never arrived is a shortfall of the rhythm.

The hole CF-0123 found. `rhythm_shortfalls()` knew two kinds and both of them
are about a picture that is *present and standing still* - the `side_by_side`
opening frozen past its ceiling (CF-0075) and a declared run delivered as one
unchanging frame (CF-0057). Neither fires on a block with no picture at all,
so a plan whose blocks went to the assetless rung produced no entry, and
`rhythm_delivered_fully` - contract: "True only when the rhythm is in the
video *and* nothing about it fell short" - came back True on a video that was
25 stubs out of 30. The cadence really was as ordered (CF-0085 made sure a
footage shortage no longer collapses the timeline), so `rhythm_delivered`
saying `staccato` is honest; what was missing was the second field noticing
that the montage those 30 cuts existed for was not there.

Variant A of CF-0123, on CF-0057's precedent: `rhythm_delivered` is untouched,
and the deficit goes into `rhythm_shortfalls` as two new kinds -
`picture_absent_run` (a stretch of consecutive assetless blocks longer than
the *ordered* `key_frame_hold_seconds`, the same threshold `long_side_run_held`
is read against, so nothing is invented) and `picture_absent_blocks` (every
assetless block, no threshold, because a run cannot see degradation that is
scattered).

Mostly pure arithmetic over block lists. One end-to-end run of
build_render_plan.py on a synthetic 30-block storyboard, and one in-process
write_batch_metadata.video_record() over its plan. No footage, no CLIP, no
ffmpeg. No pytest - plain asserts, run directly.
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
import write_batch_metadata  # noqa: E402

HOLD = 2.5


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


def order(rhythm_id="staccato", pattern_id="explainer", **params):
    base = {"block_count": None, "key_frame_hold_seconds": HOLD,
            "opening_block": "hook_over_footage",
            "acceleration_to_payoff": {"enabled": False, "strength": None}}
    base.update(params)
    return {"pattern_id": pattern_id, "rhythm_id": rhythm_id, "parameters": base}


def blocks_of(*kinds, seconds=2.0):
    """Blocks laid end to end, one per kind. `None` is a block with no `asset`
    key at all - a shape older plans carry, and no more a picture than
    `procedural` is."""
    out, t = [], 0.0
    for kind in kinds:
        b = {"start": round(t, 3), "end": round(t + seconds, 3),
             "rhythm_role": "item"}
        if kind is not None:
            b["asset"] = {"kind": kind}
        out.append(b)
        t += seconds
    return out


def kinds_of(shortfalls):
    return [s["kind"] for s in shortfalls]


def only(shortfalls, kind):
    got = [s for s in shortfalls if s["kind"] == kind]
    assert len(got) == 1, f"expected exactly one {kind}, got {kinds_of(shortfalls)}"
    return got[0]


# --------------------------------------------------------------------------
# 1. the run: the threshold is the ordered hold, and nothing else
# --------------------------------------------------------------------------

def test_a_stub_run_over_the_ordered_hold_is_its_own_entry():
    b = blocks_of("clip", "procedural", "procedural", "clip")  # 4.0s of nothing
    run = only(rhythm.rhythm_shortfalls(order(), b), "picture_absent_run")
    assert run["blocks"] == [1, 2], run
    assert (run["start"], run["end"], run["seconds"]) == (2.0, 6.0, 4.0), run
    assert run["hold_ordered_seconds"] == HOLD, run
    assert run["hold_seconds_source"] == "order", run
    assert run["over_by_seconds"] == 1.5, run
    assert "CF-0136" in run["note"], run["note"]


def test_a_stub_run_inside_the_ordered_hold_is_not_a_run():
    """The hold is what the picture was allowed to stay unchanged for. Under
    it there is no *run* shortfall - exactly as `long_side_run_held` reads a
    short freeze as the hold working as ordered. The block itself is still
    recorded by the other kind; that is what the other kind is for."""
    b = blocks_of("clip", "procedural", "clip", seconds=2.0)  # one 2.0s stub
    short = rhythm.rhythm_shortfalls(order(), b)
    assert kinds_of(short) == ["picture_absent_blocks"], short


def test_the_threshold_is_the_ordered_hold_not_an_invented_constant():
    """The same blocks, two different orders. If this test can be made to pass
    with a number that is not in the order, the threshold has been invented."""
    b = blocks_of("clip", "procedural", "procedural", "clip")
    tight = rhythm.rhythm_shortfalls(order(key_frame_hold_seconds=2.5), b)
    loose = rhythm.rhythm_shortfalls(order(key_frame_hold_seconds=6.0), b)
    assert "picture_absent_run" in kinds_of(tight), tight
    assert "picture_absent_run" not in kinds_of(loose), (
        "a 4.0s hole was called short against an ordered hold of 6.0s")
    assert only(loose, "picture_absent_blocks")["blocks"] == [1, 2], loose


def test_consecutive_stubs_are_one_run_and_a_picture_between_them_ends_it():
    """How a viewer meets them: two stubs back to back are one uninterrupted
    stretch of nothing, whatever the cut between them says - and a block that
    does put something on screen ends that stretch."""
    b = blocks_of("procedural", "procedural", "clip", "procedural", "procedural")
    runs = rhythm.assetless_runs(b)
    assert [r["blocks"] for r in runs] == [[0, 1], [3, 4]], runs
    assert [r["seconds"] for r in runs] == [4.0, 4.0], runs


# --------------------------------------------------------------------------
# 2. the blocks: no threshold, because scattered degradation makes no run
# --------------------------------------------------------------------------

def test_scattered_stubs_make_no_run_and_are_recorded_all_the_same():
    """CF-0123's argument for the second kind, in miniature. Alternating one
    stub with one clip produces no stretch longer than the ordered hold, so
    the run kind is silent - and half the video has no picture in it. A
    threshold here would not be conservative, it would be the original bug."""
    b = blocks_of(*(["procedural", "clip"] * 8))
    short = rhythm.rhythm_shortfalls(order(), b)
    assert kinds_of(short) == ["picture_absent_blocks"], (
        f"a scattered shortage produced {kinds_of(short)}")
    rec = short[0]
    assert rec["blocks"] == list(range(0, 16, 2)), rec
    assert rec["assetless_blocks"] == 8 and rec["picture_blocks"] == 8, rec
    assert rec["block_seconds"] == [2.0] * 8, rec
    assert rec["seconds"] == 16.0, rec
    assert rec["longest_assetless_run_seconds"] == 2.0, rec


def test_one_stub_is_enough_because_the_contract_is_not_a_threshold():
    b = blocks_of("clip", "clip", "procedural", "clip")
    rec = only(rhythm.rhythm_shortfalls(order(), b), "picture_absent_blocks")
    assert rec["blocks"] == [2] and rec["assetless_blocks"] == 1, rec
    assert rec["total_blocks"] == 4 and rec["picture_blocks"] == 3, rec


def test_the_blocks_entry_is_one_aggregate_not_one_per_block():
    """Deliberate: every entry in this list becomes a sentence in
    `deviations` and its own `RHYTHM SHORT` line on stderr, and 25 of those
    is noise where a record is wanted. Nothing is lost - the indices and
    their seconds are both in the one entry."""
    b = blocks_of(*(["procedural"] * 25 + ["clip"] * 5))
    short = rhythm.rhythm_shortfalls(order(), b)
    assert kinds_of(short).count("picture_absent_blocks") == 1, kinds_of(short)
    rec = only(short, "picture_absent_blocks")
    assert rec["blocks"] == list(range(25)), rec
    assert len(rec["block_seconds"]) == len(rec["blocks"]), rec


# --------------------------------------------------------------------------
# 3. what counts as a picture, and under which rhythms this is read
# --------------------------------------------------------------------------

def test_a_card_is_a_picture_and_a_stub_is_not():
    """`card` is drawn text the editor put there on purpose (CF-0041 refuses
    to call it a degradation); `procedural` is the assetless rung a block
    falls to when no candidate could fill it (CF-0085). The two look similar
    on screen and are opposite facts about the video."""
    assert rhythm.rhythm_shortfalls(order(), blocks_of("card", "card")) == []
    assert kinds_of(rhythm.rhythm_shortfalls(
        order(), blocks_of("clip", "typographic"))) == ["picture_absent_blocks"]
    assert kinds_of(rhythm.rhythm_shortfalls(
        order(), blocks_of("clip", None))) == ["picture_absent_blocks"], (
        "a block with no asset key at all was counted as a picture")
    for kind in rhythm.PICTURE_KINDS:
        assert rhythm.rhythm_shortfalls(order(), blocks_of(kind, kind)) == [], kind


def test_a_plan_with_a_picture_in_every_block_has_no_picture_shortfall():
    b = blocks_of(*(["clip"] * 10))
    assert rhythm.rhythm_shortfalls(order(), b) == []
    rep = rhythm.picture_report(b, HOLD)
    assert rep["assetless_blocks"] == 0 and rep["picture_blocks"] == 10, rep
    assert rep["longest_assetless_run_seconds"] is None, rep
    assert rep["runs"] == [], rep


def test_it_is_recorded_under_every_rhythm_not_only_alternate():
    """`side_runs` and `alternation` are `alternate`'s own records; a footage
    shortage is not a property of the cadence it lands in. The real case
    CF-0123 was written from is a `staccato`."""
    b = blocks_of("clip", "procedural", "procedural", "clip")
    for rid in ("even", "hold", "staccato", "alternate"):
        short = rhythm.rhythm_shortfalls(order(rhythm_id=rid), b)
        assert kinds_of(short) == ["picture_absent_run", "picture_absent_blocks"], \
            f"{rid}: {kinds_of(short)}"
        assert all(s["rhythm_id"] == rid for s in short), short


def test_the_kinds_that_were_here_first_keep_their_places():
    """The new entries are appended, not interleaved: `wren-hollow-lockhart`
    is pinned block by block against this list in
    tests/test_openings_and_sides.py, and a reader that reached for
    `shortfalls[0]` must still find what it found before."""
    b = blocks_of("clip", "procedural", "procedural", "clip")
    short = rhythm.rhythm_shortfalls(order(rhythm_id="alternate"), b)
    assert kinds_of(short)[-2:] == ["picture_absent_run", "picture_absent_blocks"]
    assert not any(k in ("opening_static_held", "long_side_run_held")
                   for k in kinds_of(short)[-2:])


def test_the_numbers_sit_next_to_the_runs_in_the_picture_report():
    b = blocks_of("clip", "procedural", "procedural", "clip", "procedural")
    rep = rhythm.picture_report(b, HOLD)
    assert rep["blocks"] == 5 and rep["picture_blocks"] == 2, rep
    assert rep["assetless_blocks"] == 3, rep
    assert rep["assetless_seconds"] == 6.0, rep
    assert rep["longest_assetless_run_seconds"] == 4.0, rep
    assert [r["blocks"] for r in rep["runs"]] == [[1, 2], [4]], rep
    # No order at all still answers, and says the hold is not the order's.
    bare = rhythm.picture_report(b)
    assert bare["hold_ordered_seconds"] == rhythm.DEFAULT_HOLD_SECONDS, bare
    assert bare["hold_seconds_source"] == "default", bare


# --------------------------------------------------------------------------
# 4. end to end: the 25-of-30 plan, and what the Analyst reads
# --------------------------------------------------------------------------

BLOCK_SECONDS = 1.4
BLOCK_COUNT = 30
STUBS = 25


def _silent_wav(path, seconds, rate=16000):
    """Not dead silence - leading_silence() would read the whole file as lead."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = 2000 if (i // 40) % 2 else -2000
            frames += int(v).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _anchor(i):
    return {"word_index": i, "phrase": f"anchor {i}", "emphasis_words": []}


def _twentyfive_of_thirty_storyboard():
    """The Raygun shape of run 2026-09-03T2037Z, at the ratio CF-0123 argued
    from: 30 staccato blocks, 25 of which no candidate could fill. The five
    that did resolve are `card` blocks rather than clips so the storyboard
    needs no footage on disk - a card is a picture, which is the only property
    this test reads off them.
    """
    blocks, t = [], 0.0
    for i in range(BLOCK_COUNT):
        start, end = round(t, 3), round(t + BLOCK_SECONDS, 3)
        if i % 6 == 5:  # five cards, one every sixth block
            blocks.append({"word_range": [0, 0], "intent": "count card",
                           "asset_kind": "card",
                           "card": {"kind": "count_card", "text": str(i)},
                           "emphasis_words": [], "rhythm_role": "item",
                           "side": None, "shot": None, "held_frame": False,
                           "_start": start, "_end": end})
        else:
            blocks.append(resolve_anchors.unfilled_block(
                _anchor(i), {"role": "item"}, start, end,
                "every candidate failed to cut"))
        t = end
    assert sum(1 for b in blocks if b["asset_kind"] != "card") == STUBS
    return {
        "script_id": "cf-0136",
        "style": "motion",
        "resolved_from_anchors": True,
        "rhythm": {"pattern_requested": "explainer",
                   "rhythm_requested": "staccato", "rhythm_built": "staccato",
                   "parameters": {"block_count": BLOCK_COUNT,
                                  "key_frame_hold_seconds": BLOCK_SECONDS},
                   "opening_requested": "hook_over_footage",
                   "opening_delivered": "hook_over_footage",
                   "anchor_count": BLOCK_COUNT},
        "blocks": blocks,
        "unresolved_anchors": [], "rejected_candidates": [],
    }


def _build_the_plan(tmp):
    voice_seconds = BLOCK_COUNT * BLOCK_SECONDS
    # Exactly as long as the blocks cover: a longer wav leaves a tail the
    # planner has to stretch the last block over, and a 1.9s block against
    # a 1.4s staccato cap would make this a cadence test by accident.
    _silent_wav(tmp / "voice.wav", voice_seconds)
    # A dense word grid on purpose: block boundaries are snapped to word
    # starts, and on a sparse grid that snap alone pushes a 1.4s staccato
    # block past its own cap - which would make this a test about cadence
    # drift instead of about the picture.
    words = [{"word": f"w{i}", "start": round(0.05 + i * 0.1, 2),
              "end": round(0.13 + i * 0.1, 2)}
             for i in range(int(voice_seconds / 0.1) - 1)]
    (tmp / "words.json").write_text(json.dumps(words))
    (tmp / "storyboard.json").write_text(
        json.dumps(_twentyfive_of_thirty_storyboard()))
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    out = tmp / "plan.json"
    r = subprocess.run(
        [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
         str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
         "--style", "motion", "--target-duration", "1", "120",
         *_rung_on_channel(tmp)],
        capture_output=True, text=True, cwd=tmp)
    assert r.returncode == 0, r.stderr[-2500:]
    return json.loads(out.read_text()), r


def test_a_plan_that_is_twentyfive_stubs_of_thirty_is_not_a_delivered_rhythm():
    """CF-0136's acceptance, end to end through the real planner.

    `rhythm_delivered` stays `staccato` - the timeline is exactly what was
    ordered and saying otherwise would teach the Analyst that staccato failed,
    which is false (CF-0123 variant A, and it is why
    tests/test_rhythm_execution.py's
    test_staccato_is_not_broken_by_degradation_because_boundaries_do_not_move
    is still green). `rhythm_delivered_fully` is what turns False, and the two
    new entries say why."""
    with tempfile.TemporaryDirectory() as tmp:
        plan, r = _build_the_plan(Path(tmp))
        rec = plan["rhythm"]
        kinds = [b["asset"]["kind"] for b in plan["blocks"]]
        assert kinds.count("procedural") == STUBS, kinds
        assert len(plan["blocks"]) == BLOCK_COUNT, len(plan["blocks"])

        assert rec["rhythm_delivered"] == "staccato", rec["deviations"]
        assert rec["rhythm_delivered_fully"] is False, (
            "a plan that is 25 stubs out of 30 reported a fully delivered "
            "rhythm - the exact contract breach CF-0123 found")
        got = kinds_of(rec["rhythm_shortfalls"])
        assert "picture_absent_run" in got, got
        assert got.count("picture_absent_blocks") == 1, got

        rec_blocks = only(rec["rhythm_shortfalls"], "picture_absent_blocks")
        assert rec_blocks["assetless_blocks"] == STUBS, rec_blocks
        assert rec_blocks["picture_blocks"] == BLOCK_COUNT - STUBS, rec_blocks
        assert rec_blocks["total_blocks"] == BLOCK_COUNT, rec_blocks

        assert rec["picture"]["assetless_blocks"] == STUBS, rec["picture"]
        assert rec["picture"]["picture_blocks"] == BLOCK_COUNT - STUBS, rec["picture"]
        assert rec["picture"]["longest_assetless_run_seconds"] is not None
        assert rec["picture"]["hold_seconds_source"] == "order", rec["picture"]

        # The sentence reaches the human list too, not only the machine one.
        assert any("CF-0136" in d for d in rec["deviations"]), rec["deviations"]


def test_the_batch_metadata_carries_the_picture_record_to_the_analyst():
    """`05-video-editor.json` is what CF-0023 reads; a measurement that stops
    at plan.json is a measurement the Analyst never sees."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        plan, _ = _build_the_plan(tmp)
        mp4 = tmp / "video.mp4"
        mp4.write_bytes(b"\x00")
        qc = {"passed": True, "failures": [], "notes": []}
        v = write_batch_metadata.video_record("cf-0136", plan, str(mp4), qc, "motion")
        assert v["rhythm_delivered"] == "staccato", v["rhythm_deviations"]
        assert v["rhythm_delivered_fully"] is False, v
        assert "picture_absent_blocks" in kinds_of(v["rhythm_shortfalls"]), v
        assert v["picture"]["assetless_blocks"] == STUBS, v["picture"]
        assert v["picture"]["picture_blocks"] == BLOCK_COUNT - STUBS, v["picture"]

        # A plan from before this existed cannot claim it had a picture
        # everywhere - `null`, never a zero (the rule `two_source_gate` and
        # `rhythm_delivered_fully` are both held to).
        bare = json.loads(json.dumps(plan))
        bare["rhythm"].pop("picture")
        old = write_batch_metadata.video_record("cf-0136", bare, str(mp4), qc, "motion")
        assert old["picture"] is None, old["picture"]


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

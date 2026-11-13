#!/usr/bin/env python3
"""CF-0245: a block held past the top of the pattern's hold band is trimmed to
the band, and the remainder goes to the next block - when, and only when, the
next block has the footage to play it.

The one of batch example-film/2026-09-15T1034Z's four pattern failures that
belongs to the editor. `dtf-st-louis` (moment-breakdown / even) held its
longest block 9.40s against the drawn band 4.0-9.0s: over by 0.40s, with the
other three failures being a thin pool - a topic that got one or two sources,
the same narration spread over fewer pictures - which CF-0129/CF-0232/CF-0233
fix upstream and which nothing here touches.

What these tests hold in place:

  * the band is read from the factory root's pattern file and never copied
    into this repo (the rule CF-0233 put on the researcher's side of the same
    numbers), and only a `drawn` band moves a boundary - CF-0039's `emergent`
    envelope is an observation, and cutting differently because of it would
    turn it into an order;
  * the trim moves exactly one internal boundary. The video's length, the
    words and every other block are untouched: CF-0195's guard is about
    widening an envelope to fit a broken corpus, and this is the montage
    changing instead of the envelope;
  * every refusal. No next block, a next block with no clip of its own, a
    next clip that cannot cover the extended span, an extension that would
    take the next block out of the same band - each refuses, says so with the
    numbers, and leaves the plan exactly as it was. That is the substance of
    the task: handing the remainder to a clip that does not have it is how you
    build CF-0249's half-frozen block, which is the defect that reached a
    viewer on this very video;
  * the rule is deliberately stricter than the two freeze gates, so a block
    that absorbs a remainder holds no frame at all - pinned here with the
    negative control that the gates themselves would have allowed more;
  * and the real numbers of the batch: on dtf-st-louis's own plan the trim
    *refuses*, because the next block's clip runs 2.033s against the 2.78s an
    extended block would play of it.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
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

import build_render_plan as brp  # noqa: E402
import common  # noqa: E402
import rhythm  # noqa: E402
from common import FFMPEG  # noqa: E402

# The band this whole task is about, as the factory root writes it.
MOMENT_MIN, MOMENT_MAX = 4.0, 9.0

EMERGENT = {"pattern_id": "explainer",
            "parameters": {
                "block_count": {"mode": "emergent", "min": 12, "max": 33},
                "key_frame_hold_seconds": {"mode": "emergent",
                                           "min": 2.5, "max": 8.0}}}


def moment():
    """moment-breakdown's shape, with the numbers the pattern file carries."""
    return {"pattern_id": "moment-breakdown",
            "parameters": {
                "block_count": {"mode": "drawn", "min": 6, "max": 12},
                "key_frame_hold_seconds": {"mode": "drawn",
                                           "min": MOMENT_MIN, "max": MOMENT_MAX}}}


def block(start, end, kind="clip", asset="clip.mp4", **kw):
    return {"word_range": [0, 0], "intent": "a block", "asset_kind": kind,
            "asset": asset, "emphasis_words": [], "rhythm_role": "beat",
            "side": None, "shot": "src:1", "held_frame": False,
            "_start": start, "_end": end, **kw}


def spans(blocks):
    return [round(b["_end"] - b["_start"], 3) for b in blocks]


def probe(seconds):
    """A stand-in for common.media_duration: every clip runs `seconds`."""
    if isinstance(seconds, dict):
        return lambda path: seconds[Path(path).name]
    return lambda path: seconds


# --------------------------------------------------------------------------
# Where the numbers come from
# --------------------------------------------------------------------------

def test_the_band_is_read_from_the_factory_root():
    """The pattern vocabulary lives in the root and is read from there. A copy
    of these numbers inside this repo is the CF-0003 failure - two copies of a
    threshold are two thresholds - and CF-0233 put the same rule on the
    researcher's side of the same band."""
    assert not (AGENT_ROOT / "patterns").exists(), (
        "the pattern vocabulary must not be copied into this agent's repo - "
        "build_render_plan.PATTERNS_DIR reads the factory root")
    pattern = brp.load_pattern("moment-breakdown")
    assert pattern is not None, (
        f"moment-breakdown.json was not readable at {brp.PATTERNS_DIR} - "
        f"without it the trim cannot know the band and refuses everything")
    band = brp.hold_band(pattern)
    assert band["min"] == MOMENT_MIN and band["max"] == MOMENT_MAX, band


def test_only_a_drawn_band_moves_a_boundary():
    """CF-0039 kept: an `emergent` range is an observation of what past videos
    did. A video outside it declines to claim the pattern (CF-0192) and is not
    recut, because recutting for an observation makes it an order."""
    assert brp.hold_band(EMERGENT) is None
    blocks = [block(0.0, 9.4), block(9.4, 12.0)]
    records = brp.trim_to_hold_band(blocks, EMERGENT, 12.0,
                                    clip_seconds=probe(20.0))
    assert records == [], records
    assert spans(blocks) == [9.4, 2.6], spans(blocks)


def test_an_unreadable_pattern_file_trims_nothing():
    """A checkout with no factory root above it (load_pattern -> None) has no
    band to trim to, and inventing one here is what this repo refuses to do."""
    blocks = [block(0.0, 9.4), block(9.4, 12.0)]
    assert brp.trim_to_hold_band(blocks, None, 12.0,
                                 clip_seconds=probe(20.0)) == []
    assert spans(blocks) == [9.4, 2.6]


def test_a_word_range_storyboard_is_left_alone():
    """Without explicit times the planner reads a block's bounds off the word
    alignment, and a boundary there is a word rather than a number this may
    move."""
    blocks = [{"word_range": [0, 4], "asset_kind": "clip", "asset": "a.mp4"},
              {"word_range": [5, 9], "asset_kind": "clip", "asset": "b.mp4"}]
    assert brp.trim_to_hold_band(blocks, moment(), 30.0,
                                 clip_seconds=probe(20.0)) == []
    assert "_start" not in blocks[0]


# --------------------------------------------------------------------------
# The trim itself
# --------------------------------------------------------------------------

def test_the_long_block_is_trimmed_and_the_next_one_gets_the_remainder():
    blocks = [block(0.0, 9.4), block(9.4, 12.0), block(12.0, 16.4)]
    records = brp.trim_to_hold_band(blocks, moment(), 16.4,
                                    clip_seconds=probe(3.6))
    assert len(records) == 1, records
    rec = records[0]
    assert rec["applied"] is True and rec["code"] == brp.HOLD_TRIM_APPLIED, rec
    assert rec["measured"] == 9.4 and rec["remainder"] == 0.4
    assert rec["trimmed_to"] == MOMENT_MAX and rec["next_block"] == 1
    assert spans(blocks) == [9.0, 3.0, 4.4], spans(blocks)
    # One boundary moved, and the blocks still tile the video with no gap and
    # no overlap - the trim is a montage change, not a re-plan.
    assert blocks[0]["_end"] == blocks[1]["_start"] == 9.0
    assert blocks[1]["_end"] == blocks[2]["_start"] == 12.0
    assert blocks[2]["_end"] == 16.4, "the last block's end is the audio's"


def test_the_trimmed_cadence_is_inside_the_band_and_the_shortfall_is_gone():
    """The point of the whole task, measured by the function that decides it:
    CF-0192's `pattern_shortfalls`, on the cadence the trim produced."""
    blocks = [block(0.0, 9.4)] + [block(9.4 + i * 2.6, 12.0 + i * 2.6)
                                  for i in range(5)]
    before = [{"start": b["_start"], "end": b["_end"]} for b in blocks]
    order = {"pattern_id": "moment-breakdown", "rhythm_id": "even",
             "parameters": None}
    short = rhythm.pattern_shortfalls(order, before, "even", moment())
    assert [s["code"] for s in short] == [rhythm.PATTERN_HOLD_OUTSIDE_BAND], short
    assert short[0]["measured"] == 9.4 and short[0]["outside_by"] == 0.4

    brp.trim_to_hold_band(blocks, moment(), 22.4, clip_seconds=probe(3.6))
    after = [{"start": b["_start"], "end": b["_end"]} for b in blocks]
    assert rhythm.cadence(after)["longest"] == MOMENT_MAX
    assert rhythm.pattern_shortfalls(order, after, "even", moment()) == []
    # The envelope did not move an inch (CF-0195): same band, same block
    # count, same total length - a different montage inside it.
    assert len(after) == len(before)
    assert after[-1]["end"] == before[-1]["end"]


def test_the_extended_block_holds_no_frame_at_all():
    """The condition is stricter than either freeze gate on purpose: a block
    that absorbs a remainder plays no frame past the end of its clip, so
    neither CF-0131's `clip_shortfall` nor CF-0249's `held_tail` can have
    anything to say about it afterwards."""
    blocks = [block(0.0, 9.4), block(9.4, 12.0)]
    records = brp.trim_to_hold_band(blocks, moment(), 12.0,
                                    clip_seconds=probe(3.6))
    assert records[0]["applied"] is True, records
    extended = {"start": blocks[1]["_start"], "end": blocks[1]["_end"],
                "asset": {"start_seconds": 0}}
    assert common.clip_shortfall(extended, 3.6) is None
    assert common.held_tail(extended, 3.6) is None
    assert records[0]["next_clip_needed"] <= 3.6


def test_the_strictness_is_deliberate_and_the_gates_would_have_allowed_more():
    """The negative control for the rule above. dtf-st-louis's own next block
    is 0.75s short of what an extended span would play, which `held_tail()`
    forgives (it is under MAX_HELD_RUN) - so a rule that only asked the gate
    would have trimmed here and put three quarters of a second of frozen
    picture in the montage. It refuses instead."""
    blocks = [block(0.0, 9.4), block(9.4, 11.43), block(11.43, 12.77)]
    records = brp.trim_to_hold_band(blocks, moment(), 12.77,
                                    clip_seconds=probe(2.033))
    assert records[0]["code"] == brp.HOLD_TRIM_NEXT_CLIP_TOO_SHORT
    would_be = {"start": 9.0, "end": 11.43, "asset": {"start_seconds": 0}}
    assert common.held_tail(would_be, 2.033) is None, (
        "if the gate had an opinion here the rule would not need to be "
        "stricter than it - this is the case the strictness exists for")
    assert common.source_time(would_be, 11.43) - 2.033 > 0.7


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------

def test_the_last_block_has_no_next_anchor_to_hand_the_remainder_to():
    """Trimming it would leave 0.4s of video with no picture, or freeze the
    previous one over them, which is the defect (CF-0249). Left long, and the
    pattern goes undelivered with `hold_outside_band` - a recorded failure is
    the right outcome here, not a repaired montage."""
    blocks = [block(0.0, 3.0), block(3.0, 12.4)]
    records = brp.trim_to_hold_band(blocks, moment(), 12.4,
                                    clip_seconds=probe(20.0))
    assert [r["code"] for r in records] == [brp.HOLD_TRIM_NO_NEXT_BLOCK]
    assert records[0]["applied"] is False
    assert records[0]["measured"] == 9.4 and records[0]["remainder"] == 0.4
    assert spans(blocks) == [3.0, 9.4], spans(blocks)


def test_a_next_block_with_no_clip_of_its_own_is_refused():
    """A still, a drawn card, an assetless block, a swing block cut from
    several shots and a side-by-side half: none of them is a clip whose file
    can simply be played longer. A still has no footage to play at all, and a
    multi-picture block would have to be recut, which is a cut rather than a
    boundary."""
    for kind in ("still", "card", "typographic", "sequence", "split"):
        blocks = [block(0.0, 9.4), block(9.4, 12.0, kind=kind)]
        records = brp.trim_to_hold_band(blocks, moment(), 12.0,
                                        clip_seconds=probe(20.0))
        assert [r["code"] for r in records] == [brp.HOLD_TRIM_NEXT_HAS_NO_CLIP], (
            f"{kind}: {records}")
        assert records[0]["next_asset_kind"] == kind
        assert spans(blocks) == [9.4, 2.6], f"{kind}: {spans(blocks)}"


def test_a_next_block_already_being_degraded_is_refused():
    """--degrade-block on the next index means its clip is dropped to a still
    further down this same run (CF-0031), so the footage the trim would be
    counting on is not going to be played."""
    blocks = [block(0.0, 9.4), block(9.4, 12.0)]
    records = brp.trim_to_hold_band(blocks, moment(), 12.0, degraded={1},
                                    clip_seconds=probe(20.0))
    assert [r["code"] for r in records] == [brp.HOLD_TRIM_NEXT_HAS_NO_CLIP]
    assert spans(blocks) == [9.4, 2.6]


def test_a_next_clip_that_cannot_cover_the_extended_span_is_refused():
    """The grill's condition, in numbers: the clip is not long enough for what
    it is being handed, so the trim would buy the band's compliance with a
    frozen frame."""
    blocks = [block(0.0, 9.4), block(9.4, 12.0)]
    records = brp.trim_to_hold_band(blocks, moment(), 12.0,
                                    clip_seconds=probe(2.8))
    rec = records[0]
    assert rec["code"] == brp.HOLD_TRIM_NEXT_CLIP_TOO_SHORT
    assert rec["next_clip_seconds"] == 2.8 and rec["next_clip_needed"] == 3.35
    assert "CF-0249" in rec["note"]
    assert spans(blocks) == [9.4, 2.6]


def test_an_unprobeable_next_clip_is_refused():
    """A file ffprobe cannot read comes back as 0.0 seconds (media_duration),
    and a length nobody could measure is not a length to plan on."""
    blocks = [block(0.0, 9.4), block(9.4, 12.0)]
    records = brp.trim_to_hold_band(blocks, moment(), 12.0,
                                    clip_seconds=probe(0.0))
    assert records[0]["code"] == brp.HOLD_TRIM_NEXT_CLIP_TOO_SHORT
    assert spans(blocks) == [9.4, 2.6]


def test_a_trim_that_would_push_the_next_block_out_of_the_band_is_refused():
    """Otherwise the trim moves the failure one block to the right and calls
    it fixed."""
    blocks = [block(0.0, 9.4), block(9.4, 18.2)]
    records = brp.trim_to_hold_band(blocks, moment(), 18.2,
                                    clip_seconds=probe(20.0))
    rec = records[0]
    assert rec["code"] == brp.HOLD_TRIM_NEXT_WOULD_LEAVE_BAND
    assert rec["next_span"] == 8.8 and rec["next_span_extended"] == 9.2
    assert spans(blocks) == [9.4, 8.8]


def test_two_long_blocks_in_a_row_are_each_decided_on_their_own():
    """The second long block is the first one's neighbour: it is refused as a
    receiver (it would leave the band), and then judged in its own right."""
    blocks = [block(0.0, 9.4), block(9.4, 19.4), block(19.4, 24.0)]
    records = brp.trim_to_hold_band(blocks, moment(), 24.0,
                                    clip_seconds=probe(20.0))
    assert [r["block"] for r in records] == [0, 1]
    assert records[0]["code"] == brp.HOLD_TRIM_NEXT_WOULD_LEAVE_BAND
    assert records[1]["code"] == brp.HOLD_TRIM_APPLIED
    assert spans(blocks) == [9.4, 9.0, 5.6], spans(blocks)


# --------------------------------------------------------------------------
# The real plan of batch example-film/2026-09-15T1034Z
# --------------------------------------------------------------------------

def test_dtf_st_louis_refuses_on_its_own_numbers():
    """The video that motivated the task, on its own measurements, so the
    answer stays checkable after `work/` is gone.

    Block 0 spans 0.00-9.40s (the resolver pulled its start back to 0 because
    the script's first anchor sits at 5.72s - 3 anchors for 39s of narration,
    which is the thin pool CF-0233 fixes upstream, not something a boundary
    can repair). Its neighbour is another cut of the *same* anchor: block 1
    spans 9.40-11.43s and its clip
    `clips/a00_dPmklyud1P8_s031.mp4` runs 2.033s - cut to the 2.03s it was
    asked for and no longer, so it has nothing spare. The extended block would
    play 2.78s of it.

    So the trim refuses here, and dtf-st-louis keeps `hold_outside_band`. That
    is the honest answer: the 0.40s of overshoot has nowhere to go that is not
    a frozen frame, and the block's real defect is the 5.37s freeze CF-0249
    already catches - not 0.40s of band."""
    real = [(0.0, 9.4, 4.033), (9.4, 11.43, 2.033), (11.43, 12.77, 1.833),
            (12.77, 15.77, 3.0), (15.77, 18.77, 3.0), (18.77, 19.69, 1.433),
            (19.69, 22.52, 2.833), (22.52, 25.42, 2.9), (25.42, 33.72, 8.3),
            (33.72, 36.79, 3.066), (36.79, 39.625, 3.333)]
    blocks = [block(s, e, asset=f"clip{i}.mp4")
              for i, (s, e, _) in enumerate(real)]
    lengths = {f"clip{i}.mp4": c for i, (_, _, c) in enumerate(real)}
    records = brp.trim_to_hold_band(blocks, moment(), 39.625,
                                    clip_seconds=probe(lengths))
    assert len(records) == 1, records
    rec = records[0]
    assert rec["block"] == 0 and rec["measured"] == 9.4
    assert rec["remainder"] == 0.4 and rec["band_max"] == MOMENT_MAX
    assert rec["code"] == brp.HOLD_TRIM_NEXT_CLIP_TOO_SHORT
    assert rec["applied"] is False
    assert rec["next_clip_seconds"] == 2.033 and rec["next_clip_needed"] == 2.78
    assert spans(blocks) == [round(e - s, 3) for s, e, _ in real], (
        "nothing in the plan may move when the trim refuses")


# --------------------------------------------------------------------------
# Through the real planner
# --------------------------------------------------------------------------

def _ffmpeg(*args):
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", *args], check=True)


def _moving(path, seconds):
    _ffmpeg("-f", "lavfi",
            "-i", f"testsrc2=duration={seconds}:size=540x960:rate=25",
            "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _silent_wav(path, seconds):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * seconds))
    return str(path)


def test_the_written_plan_carries_the_moved_boundary_and_the_record():
    """End to end through the real planner: the boundary the trim moved is the
    boundary every stage below it sees - the block the renderer is handed, the
    cadence the pattern verdict is taken on, and the record in
    `rhythm.hold_band_trims` that says what was done and why.

    Two sources, because CF-0129 switched the two-source gate to `enforce`."""
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav", 12.0)
        (tmp / "words.json").write_text(json.dumps(
            [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(20)]))
        # Block 0 is over the band by 0.4s and has the footage for its own
        # length; block 1's clip is 3.6s against the 2.6s it was planned at,
        # so it can take the remainder without holding a frame.
        long_clip = _moving(tmp / "aaaaaaaaaaa.mp4", 9.8)
        next_clip = _moving(tmp / "bbbbbbbbbbb.mp4", 3.6)

        def sb(shot, asset, start, end):
            return {"word_range": [0, 0], "intent": "clip", "asset_kind": "clip",
                    "asset": asset, "emphasis_words": [], "rhythm_role": "beat",
                    "side": None, "shot": shot, "held_frame": False,
                    "_start": start, "_end": end}

        (tmp / "storyboard.json").write_text(json.dumps({
            "script_id": "cf-0245", "style": "motion",
            "resolved_from_anchors": True,
            "rhythm": {"pattern_requested": "moment-breakdown",
                       "rhythm_requested": "even", "rhythm_built": "even",
                       "parameters": {"block_count": 2,
                                      "key_frame_hold_seconds": 6.5},
                       "opening_requested": None, "opening_delivered": None,
                       "anchor_count": 2},
            "blocks": [sb("aaaaaaaaaaa:1", long_clip, 0.0, 9.4),
                       sb("bbbbbbbbbbb:1", next_clip, 9.4, 12.0)],
            "unresolved_anchors": [], "rejected_candidates": [],
        }))
        out = tmp / "plan.json"
        result = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "motion", "--target-duration", "1", "60"],
            capture_output=True, text=True, cwd=tmp)
        assert result.returncode == 0, result.stderr[-3000:]
        plan = json.loads(out.read_text())

        bounds = [(b["start"], b["end"]) for b in plan["blocks"]]
        assert bounds[0] == (0.0, 9.0), bounds
        assert bounds[1][0] == 9.0, bounds
        assert plan["rhythm"]["cadence"]["longest"] == MOMENT_MAX
        # Both blocks are still clips: the extended one was not degraded by
        # the CF-0249 gate, which is the whole condition the trim applies on.
        assert [b["asset"]["kind"] for b in plan["blocks"]] == ["clip", "clip"], (
            plan["degraded_blocks"])
        trims = plan["rhythm"]["hold_band_trims"]
        assert len(trims) == 1 and trims[0]["applied"] is True, trims
        assert trims[0]["code"] == brp.HOLD_TRIM_APPLIED
        assert trims[0]["remainder"] == 0.4
        assert not [s for s in plan["rhythm"]["pattern_shortfalls"]
                    if s["code"] == rhythm.PATTERN_HOLD_OUTSIDE_BAND], (
            plan["rhythm"]["pattern_shortfalls"])
        assert any("CF-0195" in n for n in plan["notes"]), plan["notes"]

        # ...and it reaches the artefact the Analyst reads (CF-0023). A record
        # that stops at plan.json is a record nobody downstream ever sees.
        mp4 = _moving(tmp / "rendered.mp4", 1.0)
        meta = subprocess.run(
            [py, str(SCRIPTS / "write_batch_metadata.py"), str(tmp),
             "--video", "cf-0245", str(out), mp4,
             "--style-requested", "motion"],
            capture_output=True, text=True, cwd=tmp)
        assert meta.returncode == 0, meta.stderr[-3000:]
        video = json.loads(
            (tmp / "05-video-editor.json").read_text())["videos"][0]
        assert video["hold_band_trims"] == trims, video["hold_band_trims"]


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

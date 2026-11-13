#!/usr/bin/env python3
"""CF-0120: several distinct shots inside one swing block, instead of a frozen
frame.

CF-0050 made a swing block one *crossing of the script's axis*, so its length
is a property of the writing: four consecutive anchors on one side are one
block covering all four. CF-0057 recorded what that costs when the side has no
clip that long - the run comes out as a single held frame - and the first
`contrast` batch after CF-0119 (legacy-film/2026-09-09T2031Z, script
`lf-2026-09-09-004-script1` - the channel is example-film since CF-0180, but
the dated batch directory and the already-minted `lf-` script id were both
deliberately left as they were) measured it for real: side `a` held for 18.27s
on one frame against an ordered hold of 3.0s.

The fix is *inside* the block and nowhere else. The boundary does not move, no
new block is introduced, and `swap_ratio` - which is measured over block sides
- reads exactly what it read before. What changes is how the block is filled:
distinct shots of that side, back to back, through the same `fill()` chain
`even` uses (CF-0028) and under the same one-sample-one-use ledger (CF-0121).

Two exit criteria from the task, and they are the first two tests here:

  * a 7s swing block with three short clips comes out as three *different*
    shots;
  * with one shot available it degrades down the chain that already exists
    (still, then typographic) rather than showing that shot twice.

Synthetic and fast, on the real fill loop - the matcher, the cutter and the
gate are doubles, exactly as in test_shot_reuse_once.py, whose harness this
borrows.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import qc_render  # noqa: E402
import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402

IDX = "/nowhere/pool.shots.json"
SRC = "/nowhere/pool.mp4"
MIN_SCORE = 0.22
HOLD_SECONDS = 3.0


# --------------------------------------------------------------------------
# harness (test_shot_reuse_once.py's, with the sides and the order it needs)
# --------------------------------------------------------------------------

def _index(n, seconds):
    return {"source": SRC,
            "shots": [{"index": i, "start": i * 100.0, "end": i * 100.0 + seconds}
                      for i in range(n)]}


@contextlib.contextmanager
def _patched(candidates, index_data, words, duration):
    saved = {k: getattr(ra, k) for k in
             ("match", "cut", "usable", "hold_frame", "audio_duration",
              "leading_silence", "load_words")}
    shot_span = {s["index"]: (s["start"], s["end"]) for s in index_data[IDX]["shots"]}

    def fake_match(indexes, phrases, min_score, top, python):
        out = []
        for ph in phrases:
            cands = [{"shot": s, "score": sc, "start": shot_span[s][0],
                      "end": shot_span[s][1], "card": False, "promoted": False,
                      "index": IDX, "source": SRC} for s, sc in candidates]
            out.append({"phrase": ph, "found": True, "discriminative": True,
                        "margin": 0.1, "candidates": cands})
        return out, index_data

    def fake_cut(source, start, duration_, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_usable(clip, seconds, *a, **kw):
        return True, []

    def fake_hold_frame(clip, seconds, dest, used=None):
        Path(dest).write_bytes(b"")
        return True

    ra.match, ra.cut, ra.usable, ra.hold_frame = (
        fake_match, fake_cut, fake_usable, fake_hold_frame)
    ra.audio_duration = lambda path: duration
    ra.leading_silence = lambda path: 0.0
    ra.load_words = lambda path: words
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(ra, k, v)


def _run(anchors, candidates, n_shots=6, shot_seconds=2.5, n_words=30,
         duration=15.0):
    words = [{"word": "w", "start": 0.4 + 0.5 * i, "end": 0.8 + 0.5 * i}
             for i in range(n_words)]
    index_data = {IDX: _index(n_shots, shot_seconds)}
    with tempfile.TemporaryDirectory() as tmp, \
            _patched(candidates, index_data, words, duration):
        tmp = Path(tmp)
        spec = tmp / "anchors.json"
        spec.write_text(json.dumps({"script_id": "t", "anchors": anchors}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(spec), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", str(MIN_SCORE),
                "--rhythm", "alternate", "--hold-seconds", str(HOLD_SECONDS)]
        err = io.StringIO()
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                ra.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text()), err.getvalue()


def anchor(word_index, phrase, side):
    return {"word_index": word_index, "phrase": phrase, "emphasis_words": [],
            "side": side}


# A crossing of ~6.5s: the first anchor opens the video on side `a`, the second
# crosses to `b` at word 14 (7.40s - 0.35s of lead).
CROSSING = [anchor(1, "the cottage", "a"), anchor(14, "the lake", "b")]

# Deep enough that the second crossing has footage of its own - the first one
# spending three shots must not be what leaves side `b` without a picture.
POOL = [(1, 0.31), (2, 0.29), (3, 0.27), (4, 0.25), (5, 0.23)]


def first_block(story):
    return story["blocks"][0]


def all_shots(story):
    return [s for b in story["blocks"] for s in rhythm.block_shots(b)]


# --------------------------------------------------------------------------
# the two exit criteria
# --------------------------------------------------------------------------

def test_a_seven_second_swing_block_is_cut_from_three_different_shots():
    """The task's first exit criterion. Three 2.5s clips, one crossing, and
    the crossing keeps its own boundary: one block, three pictures."""
    story, err = _run(CROSSING, POOL)
    b = first_block(story)
    assert b["asset_kind"] == "sequence", (
        f"the crossing came out as {b['asset_kind']!r} - the whole point is "
        f"that it is no longer one picture: {b}")
    assert b["side"] == "a" and b["rhythm_role"] == "swing", b
    assert len(b["cuts"]) == 3, b["cuts"]
    assert [c["shot"] for c in b["cuts"]] == ["pool:1", "pool:2", "pool:3"], b["cuts"]
    assert len({c["shot"] for c in b["cuts"]}) == 3, (
        "the same shot was recut into the same block - CF-0121 says a sample "
        "is used once, and CF-0074 says only distinct shots go inside a swing")
    assert not any(c.get("held_frame") for c in b["cuts"]), (
        "the shots cover the crossing, so nothing in it should be standing still")
    assert b["_start"] == 0.0 and 6.0 <= b["_end"] <= 7.5, (b["_start"], b["_end"])
    # And the cuts really do lay end to end, from the head of the block to the
    # crossing - `at` is where in the block each picture starts.
    at = 0.0
    for c in b["cuts"]:
        assert abs(c["at"] - at) < 0.001, (c, at)
        at += c["seconds"]
    # The pictures cover the block, head to crossing - stated against the
    # block's own span rather than against a literal. CF-0276 made that span
    # start at 0.00s in the *layout*; before it, the crossing was laid out
    # from its anchor and block 0's start was dragged back to zero afterwards,
    # so these cuts covered 6.50s of a 7.05s block and the last one stood
    # still for the remaining 0.55s - the CF-0249 defect in miniature, built
    # by the same appended head this task is about.
    span = b["_end"] - b["_start"]
    assert abs(at - span) < 0.05, (at, span, b["cuts"])


def test_one_block_per_crossing_is_exactly_what_it_was():
    """No new boundary. Three shots inside the crossing must not become three
    blocks - that would put two same-side blocks next to each other, which
    `alternation_report()` reads as a swing that never happened, and it would
    move `swap_ratio` for a change that is only about what is inside a block."""
    story, _ = _run(CROSSING, POOL)
    sides = [b.get("side") for b in story["blocks"]]
    assert sides == ["a", "b"], sides
    assert story["rhythm"]["planned_block_count"] == 2, story["rhythm"]


def test_with_one_shot_available_the_block_degrades_instead_of_repeating():
    """The task's second exit criterion. One usable sample in the whole pool:
    the crossing gets it once, as a held frame (the `still` rung that already
    existed), and the video never shows it a second time to fill the rest."""
    story, err = _run(CROSSING, [(1, 0.31)])
    b = first_block(story)
    assert b["asset_kind"] == "still" and b["held_frame"] is True, b
    assert b["shot"] == "pool:1", b
    # CF-0337: the blocks after it are no longer left to the background -
    # the topic-footage rung fills them with the pool's *other* shots. What
    # this test pins is unchanged: no sample is shown twice.
    shots = all_shots(story)
    assert shots[0] == "pool:1" and len(shots) == len(set(shots)), (
        f"a sample was shown more than once to fill the crossing: {shots}")
    assert all(x.get("topic_fill") for x in story["blocks"][1:]
               if x.get("shot")), story["blocks"]
    assert not [x for x in story["blocks"] if x.get("asset_kind") == "sequence"
                and not x.get("topic_fill")], (
        "there was nothing to sequence - one shot is one picture")
    # And the shortage is reported rather than absorbed.
    assert any("one sample, one use" in r["reason"]
               for r in story["rejected_candidates"]), story["rejected_candidates"]
    reasons = [u["reason"] for u in story["unresolved_anchors"]]
    assert any("already used" in r for r in reasons), reasons


def test_the_side_runs_out_of_shots_and_its_last_picture_is_what_holds():
    """Two shots for a ~6.5s crossing: both are cut, and the tail is a frame
    of the *second* one - the picture still on screen (CF-0075's reading of a
    half's hold), never a third shot's still and never the first one again."""
    story, _ = _run(CROSSING, [(1, 0.31), (2, 0.29)])
    b = first_block(story)
    assert b["asset_kind"] == "sequence", b
    kinds = [c["kind"] for c in b["cuts"]]
    assert kinds == ["clip", "clip", "still"], b["cuts"]
    assert b["cuts"][-1]["held_frame"] is True, b["cuts"]
    assert b["cuts"][-1]["shot"] == b["cuts"][-2]["shot"] == "pool:2", b["cuts"]
    assert b["swing_block_shots"] == ["pool:1", "pool:2"], b["swing_block_shots"]
    assert all_shots(story).count("pool:1") == 1, all_shots(story)


# --------------------------------------------------------------------------
# what the measurement now says about such a block (CF-0057 / CF-0034)
# --------------------------------------------------------------------------

def _plan_block(side, cuts, start, end, **extra):
    """A render-plan block of the shape build_render_plan.py emits."""
    return {"start": start, "end": end, "side": side, "rhythm_role": "swing",
            "shot": cuts[0]["shot"], "asset": {"kind": "sequence", "cuts": cuts},
            **extra}


def _cut(shot, seconds, kind="clip", held=False):
    return {"kind": kind, "src": f"/clips/{shot}.mp4", "seconds": seconds,
            "shot": shot, "held_frame": held}


ORDER = rhythm.normalize_order({"pattern_id": "contrast", "rhythm_id": "alternate",
                                "parameters": {"key_frame_hold_seconds": HOLD_SECONDS}})


def test_a_long_run_cut_from_several_shots_is_no_longer_a_shortfall():
    """The measurement CF-0120 was opened on. The same 18.27s run on side `a`,
    once it is three pictures instead of one held frame, is not
    `long_side_run_held` any more - and the record says why, per picture."""
    blocks = [_plan_block("a", [_cut("pool:7", 7.0), _cut("pool:8", 7.0),
                                _cut("pool:9", 4.27)], 0.0, 18.27),
              _plan_block("b", [_cut("pool:2", 6.0)], 18.27, 24.27)]
    runs = rhythm.delivered_side_runs(blocks)
    assert runs[0]["pictures"] == 3, runs[0]
    assert runs[0]["frozen"] is False and runs[0]["single_held_frame"] is False, runs[0]
    assert runs[0]["shots"] == ["pool:7", "pool:8", "pool:9"], runs[0]
    assert [s for s in rhythm.rhythm_shortfalls(ORDER, blocks)
            if s["kind"] == "long_side_run_held"] == []


def test_the_same_run_held_on_one_frame_is_still_the_shortfall_it_was():
    """The control arm: CF-0057's record is not weakened, only made able to
    see a montage where there is one. One frozen picture over 18.27s is still
    reported exactly as the real batch reported it."""
    blocks = [{"start": 0.0, "end": 18.27, "side": "a", "rhythm_role": "swing",
               "shot": "pool:7", "held_frame": True,
               "asset": {"kind": "still", "src": "/clips/held.png"}},
              _plan_block("b", [_cut("pool:2", 6.0)], 18.27, 24.27)]
    short = [s for s in rhythm.rhythm_shortfalls(ORDER, blocks)
             if s["kind"] == "long_side_run_held"]
    assert len(short) == 1, short
    assert short[0]["seconds"] == 18.27 and short[0]["over_by_seconds"] == 15.27, short[0]


def test_swap_ratio_is_measured_over_blocks_and_does_not_move():
    """A crossing filled from three shots is still one crossing. The number
    the pattern is judged on has to be blind to what is inside a block."""
    many = [_plan_block("a", [_cut("pool:1", 2.0), _cut("pool:2", 2.0),
                              _cut("pool:3", 2.0)], 0.0, 6.0),
            _plan_block("b", [_cut("pool:4", 6.0)], 6.0, 12.0),
            _plan_block("a", [_cut("pool:5", 6.0)], 12.0, 18.0)]
    one = [_plan_block("a", [_cut("pool:1", 6.0)], 0.0, 6.0), many[1], many[2]]
    assert (rhythm.alternation_report(many)["swap_ratio"]
            == rhythm.alternation_report(one)["swap_ratio"] == 1.0)
    assert rhythm.alternation_report(many)["sides"] == ["a", "b", "a"]
    # The shots, though, are counted per picture: the side really does have
    # three distinct ones now, which is what ALTERNATE_MIN_DISTINCT_PER_SIDE
    # is asking about.
    assert rhythm.alternation_report(many)["distinct_shots_per_side"]["a"] == 4


def test_the_pair_rule_is_measured_by_shots_not_by_blocks():
    """CF-0120 item 4. CF-0034's defect is two pictures the viewer sees in the
    same order twice; after this task two of those pictures can sit inside one
    block, so counting one shot per block would hide the very repeat the check
    exists to catch."""
    hidden = [_plan_block("a", [_cut("pool:1", 2.0), _cut("pool:2", 2.0),
                                _cut("pool:1", 2.0), _cut("pool:2", 2.0)],
                          0.0, 8.0)]
    assert rhythm.alternation_report(hidden)["repeated_adjacent_pairs"] == 1, (
        rhythm.alternation_report(hidden))
    clean = [_plan_block("a", [_cut("pool:1", 2.0), _cut("pool:2", 2.0),
                               _cut("pool:3", 2.0)], 0.0, 6.0)]
    assert rhythm.alternation_report(clean)["repeated_adjacent_pairs"] == 0


def test_a_block_with_no_picture_still_breaks_the_chain_of_pairs():
    """Flattening the shots must not make two pictures adjacent that the
    viewer never saw next to each other - an assetless block sits between
    them."""
    blocks = [_plan_block("a", [_cut("pool:1", 2.0), _cut("pool:2", 2.0)], 0.0, 4.0),
              {"start": 4.0, "end": 6.0, "side": None,
               "asset": {"kind": "procedural"}},
              _plan_block("a", [_cut("pool:2", 2.0), _cut("pool:1", 2.0)], 6.0, 10.0)]
    rep = rhythm.alternation_report(blocks)
    assert rep["shots"] == ["pool:1", "pool:2", None, "pool:2", "pool:1"], rep["shots"]
    assert rep["repeated_adjacent_pairs"] == 0, rep


# --------------------------------------------------------------------------
# provenance and the freeze gate
# --------------------------------------------------------------------------

def test_the_provenance_names_the_shots_of_every_multi_shot_crossing():
    """CF-0120 item 5: what `05-video-editor.json` carries, so the Analyst can
    see where a side is more than one picture without reading the block list."""
    blocks = [_plan_block("a", [_cut("pool:1", 3.0), _cut("pool:2", 2.0),
                                _cut("pool:2", 1.5, kind="still", held=True)],
                          0.0, 6.5),
              _plan_block("b", [_cut("pool:4", 6.0)], 6.5, 12.5)]
    rec = rhythm.swing_block_shots(blocks)
    assert len(rec) == 1, rec
    assert rec[0] == {"index": 0, "side": "a", "shots": ["pool:1", "pool:2"],
                      "pictures": 3, "seconds": 6.5, "held_tail_seconds": 1.5}, rec[0]
    # And it reaches the side-run report the metadata copies.
    report = rhythm.side_run_report(blocks, HOLD_SECONDS)
    assert report["swing_block_shots"] == rec


def test_every_cut_of_a_sequence_block_is_probed_for_being_frozen():
    """qc_render.py samples a block at fractions of its own span; with several
    pictures in one block those fractions would all land inside whichever cut
    happens to cover them, and a frozen second picture would never be looked
    at. Each cut is handed back as a block of its own instead."""
    block = _plan_block("a", [_cut("pool:1", 3.0), _cut("pool:2", 2.0),
                              _cut("pool:2", 1.5, kind="still", held=True)],
                        0.0, 6.5)
    targets = qc_render.probe_targets(block, 4)
    assert [t[2] for t in targets] == ["b4c0", "b4c1"], targets
    assert [(t[0]["start"], t[0]["end"]) for t in targets] == [(0.0, 3.0), (3.0, 5.0)], (
        [(t[0]["start"], t[0]["end"]) for t in targets])
    assert [t[0]["asset"]["src"] for t in targets] == ["/clips/pool:1.mp4",
                                                       "/clips/pool:2.mp4"]
    # A still is not moving footage and is not checked, exactly as before.
    assert all(t[0]["asset"]["kind"] == "clip" for t in targets)


def test_the_shot_budget_is_a_property_of_how_long_the_crossing_is():
    """One picture per MIN_SWING_CUT_SECONDS, never fewer than one - so a
    short crossing behaves exactly as it did before this task."""
    assert rhythm.swing_shot_budget(1.0) == 1
    assert rhythm.swing_shot_budget(rhythm.MIN_SWING_CUT_SECONDS) == 1
    assert rhythm.swing_shot_budget(7.0) == 4
    assert rhythm.swing_shot_budget(18.27) == 11


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

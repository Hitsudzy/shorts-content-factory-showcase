#!/usr/bin/env python3
"""CF-0367: `resolve_anchors.py --exclude-candidate BLOCK` - the re-cut lever.

SKILL.md has long said "re-cut the same anchor against a different candidate
first" before a block drops a rung, and no tool did it: on
pipeline/example-film/2026-09-23T1722Z the operator had american-dread-story
block 6 refused by qc_render and no way to ask for another picture for that
one anchor. The flag reads the storyboard it replaces, refuses that block's
shot for that anchor only - inside fill(), so the replacement passes every
gate a first choice does - and says what else moved.

On the real fill loop with the matcher, cutter and gate doubled, through
test_multi_shot_swing_block.py's harness.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402
import test_multi_shot_swing_block as h  # noqa: E402

ANCHORS = [h.anchor(1, "the cottage", "a"), h.anchor(14, "the lake", "b")]
POOL = [(1, 0.31), (2, 0.29), (3, 0.27), (4, 0.25)]


def _resolve(tmp, extra=(), pool=POOL):
    """One resolve into `tmp/storyboard.json` (kept between calls, which is
    what a re-cut reads). Long shots, so every block is one picture."""
    words = [{"word": "w", "start": 0.4 + 0.5 * i, "end": 0.8 + 0.5 * i}
             for i in range(30)]
    index_data = {h.IDX: h._index(6, 20.0)}
    spec = tmp / "anchors.json"
    spec.write_text(json.dumps({"script_id": "t", "anchors": ANCHORS}))
    out = tmp / "storyboard.json"
    argv = ["resolve_anchors.py", str(spec), str(tmp / "words.json"),
            str(tmp / "voice.wav"), str(out), "--index", h.IDX,
            "--clips-dir", str(tmp / "clips"), "--min-score", str(h.MIN_SCORE),
            "--rhythm", "alternate", "--hold-seconds", str(h.HOLD_SECONDS),
            *extra]
    err = io.StringIO()
    with h._patched(pool, index_data, words, 15.0):
        saved, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                ra.main()
        finally:
            sys.argv = saved
    return json.loads(out.read_text()), err.getvalue()


def _shots(story):
    return [rhythm.block_shots(b) for b in story["blocks"]]


def test_the_block_is_recut_under_its_next_candidate_and_only_that_anchor_loses_it():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        first, _ = _resolve(tmp)
        assert _shots(first) == [["pool:1"], ["pool:2"]], _shots(first)
        story, err = _resolve(tmp, ["--exclude-candidate", "0"])
        # Block 0's anchor may not have pool:1 again; it takes the next one.
        assert _shots(story)[0] == ["pool:2"], _shots(story)
        # The exclusion is the anchor's, not the video's: pool:1 is free
        # again, and the next anchor is entitled to it under the one-use
        # ledger - which moves block 1, said out loud.
        assert _shots(story)[1] == ["pool:1"], _shots(story)
        ex = story["excluded_candidates"]
        assert [(e["block"], e["word_index"], e["shot"]) for e in ex] == \
            [(0, 1, "pool:1")], ex
        rej = [r for r in story["rejected_candidates"] if "CF-0367" in r["reason"]]
        assert [(r["phrase"], r["shot"]) for r in rej] == [("the cottage", 1)], rej
        rc = story["recut"]
        assert rc["blocks"] == [{"block": 0, "before": ["pool:1"],
                                 "after": ["pool:2"]}], rc
        assert rc["changed_elsewhere"] == [{"block": 1, "before": ["pool:2"],
                                            "after": ["pool:1"]}], rc
        assert "RECUT: block 0: pool:1 -> pool:2" in err, err
        assert "RECUT: block 1 changed too" in err, err


def test_a_second_recut_keeps_the_first_exclusion():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _resolve(tmp)
        _resolve(tmp, ["--exclude-candidate", "0"])
        story, _ = _resolve(tmp, ["--exclude-candidate", "0"])
        assert _shots(story)[0] == ["pool:3"], _shots(story)
        assert [e["shot"] for e in story["excluded_candidates"]] == \
            ["pool:1", "pool:2"], story["excluded_candidates"]


def test_the_named_form_must_be_a_shot_the_block_shows():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _resolve(tmp)
        story, _ = _resolve(tmp, ["--exclude-candidate", "0=pool:1"])
        assert _shots(story)[0] == ["pool:2"]
        try:
            _resolve(tmp, ["--exclude-candidate", "0=pool:4"])
        except SystemExit as e:
            assert "not pool:4" in str(e), e
        else:
            raise AssertionError("a shot the block does not show was accepted")


def test_without_a_storyboard_to_recut_it_refuses():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _resolve(Path(tmp), ["--exclude-candidate", "0"])
        except SystemExit as e:
            assert "resolve it once first" in str(e), e
        else:
            raise AssertionError("a re-cut with nothing to re-cut ran")


def test_an_exclusion_that_did_not_land_is_not_written():
    """exclusion_misses() is the check before the write: an excluded shot
    still on its own anchor's block means the re-cut did not happen."""
    blocks = [{"word_range": [1, 1], "shot": "pool:1"},
              {"word_range": [14, 14], "shot": "pool:1"}]
    ex = [{"block": 0, "word_index": 1, "shot": "pool:1"}]
    assert [m["still_on_block"] for m in ra.exclusion_misses(ex, blocks)] == [0]
    ex = [{"block": 0, "word_index": 99, "shot": "pool:1"}]
    assert ra.exclusion_misses(ex, blocks) == []


def test_an_empty_pool_leaves_the_block_without_a_picture_not_the_old_one():
    """The only candidate refused and nothing behind it: the anchor is not
    handed its rejected picture back - it resolves to nothing, and the plan's
    own gates decide what that costs (a refusal, on today's channels)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        first, _ = _resolve(tmp, pool=[(1, 0.31)])
        assert _shots(first)[0] == ["pool:1"], _shots(first)
        story, _ = _resolve(tmp, ["--exclude-candidate", "0"], pool=[(1, 0.31)])
        on_anchor = [rhythm.block_shots(b) for b in story["blocks"]
                     if b.get("word_range", [None])[0] == 1]
        assert all("pool:1" not in s for s in on_anchor), story["blocks"]
        assert any(u["phrase"] == "the cottage"
                   for u in story["unresolved_anchors"]), story["unresolved_anchors"]
        assert not ra.exclusion_misses(story["excluded_candidates"],
                                       story["blocks"])


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

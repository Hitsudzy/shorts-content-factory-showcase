#!/usr/bin/env python3
"""CF-0517: a one-shot block walks its pool length first, usability second.

CF-0435's usability rank (`rank_by_usability()` -> `shot_score.rank()`, key
`(hard, -score, blur)`) ran inside every fill() and overrode the
long-enough-first sort a one-shot block had made: a short "clean" shot in
front of a long, slightly weaker one won the block, and the block held a
frame (`length_supply.long_enough[].outcome == "not_reached"`). The user's
decision of 2026-10-04 is length first, then usability. What these tests hold
in place:

  * `rank_by_usability(need=)`: every shot long enough for the block goes
    ahead of every shorter one, usability ordering each group; a hard shot
    stays last however long it is; without `need` (a multi-shot block) and
    with no long-enough shot in the pool the order is the usability one;
  * `shot_score.rank(lead=)` puts the lead key between the hard tier and the
    score; under `lead_floor` (LENGTH_LEAD_MIN_USABILITY, 0.5 - the user's
    decision of 2026-10-04, 22:25) a long shot does not lead;
  * fill() asks for it on a one-shot block's match, side retry and topic
    rung - not on the under-floor rung (CF-0433) and not on a stretch split's
    extra cuts (CF-0480);
  * end to end through main(): the long weaker shot is cut and plays (no
    held frame), and `length_supply` records it `cut` at rank 0 of a run
    that walked `length_first`.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import inspect
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import cache_fingerprint  # noqa: E402
import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402

IDX = "/idx/v.shots.json"
SRC = "/src/vid00000000.mp4"


def cached(**kw):
    c = {"roi_source": "face", "roi_coverage": 0.9, "black_fraction": 0.02,
         "mean_luma": 80.0, "short_side": 1080, "width": 1920, "height": 1080,
         "measured_by": cache_fingerprint.usability_fingerprint()}
    c.update(kw)
    return c


def shot(n, end, cache=None, start=0.0, **kw):
    s = {"index": n, "start": start, "end": end, "on_topic": True,
         "burned_text": False, "usable_cached": cached(**(cache or {}))}
    s.update(kw)
    return s


def cand(n, end, score=0.30, start=0.0):
    return {"shot": n, "start": start, "end": end, "score": score, "card": False,
            "promoted": False, "index": IDX, "source": SRC}


def need_indexer():
    if shot_score.indexer() is None:
        print("SKIP: footage-indexer's shot_usability.py is not beside the main checkout")
        return False
    return True


def order(pool, lut, need=None):
    return [c["shot"] for c in ra.rank_by_usability(pool, lut, need=need)]


# --- the rank -----------------------------------------------------------------
def test_a_long_weaker_shot_goes_ahead_of_a_short_clean_one():
    """The CF-0517 shape: shot 1 is clean and 1.2 s, shot 2 is 6 s with a
    framing price - the old rank cut shot 1 and held its frame for a 3 s
    block."""
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, 1.2), (IDX, 2): shot(2, 6.0, {"roi_coverage": 0.4})}
    pool = [cand(1, 1.2, 0.31), cand(2, 6.0, 0.30)]
    assert order(pool, lut) == [1, 2], "without need the usability order stands"
    assert order(pool, lut, need=3.0) == [2, 1]


def test_usability_still_orders_the_long_enough_ones_and_the_short_ones():
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, 6.0, {"roi_coverage": 0.4}), (IDX, 2): shot(2, 5.0),
           (IDX, 3): shot(3, 1.0, {"roi_coverage": 0.4}), (IDX, 4): shot(4, 1.5)}
    pool = [cand(1, 6.0, 0.40), cand(2, 5.0, 0.35), cand(3, 1.0, 0.33), cand(4, 1.5, 0.30)]
    assert order(pool, lut, need=3.0) == [2, 1, 4, 3]


def test_no_long_enough_shot_keeps_the_old_order():
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, 1.2, {"roi_coverage": 0.4}), (IDX, 2): shot(2, 1.5),
           (IDX, 3): shot(3, 2.0, on_topic=False)}
    pool = [cand(1, 1.2, 0.40), cand(2, 1.5, 0.35), cand(3, 2.0, 0.30)]
    assert order(pool, lut, need=3.0) == order(pool, lut) == [2, 1, 3]


def test_a_hard_shot_stays_last_however_long():
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, 9.0, burned_text=True), (IDX, 2): shot(2, 1.2)}
    pool = [cand(1, 9.0, 0.40), cand(2, 1.2, 0.30)]
    assert shot_score.rank_key(lut[(IDX, 1)])[0] == 1, "fixture: shot 1 must be hard"
    assert order(pool, lut, need=3.0) == [2, 1]


@contextlib.contextmanager
def _keys(by_shot):
    """`shot_score.rank_key` answering a fixed key per shot number - a soft
    price this low cannot be built from today's price table (3/3/2/4 points),
    and the floor is about the price, not about which rules make it up."""
    saved = shot_score.rank_key
    shot_score.rank_key = lambda shot, fresh=True, video=None, wide=False: \
        by_shot[shot["index"]]
    try:
        yield
    finally:
        shot_score.rank_key = saved


def test_a_long_shot_under_the_floor_does_not_beat_a_short_clean_one():
    """The user's 0.5 floor (2026-10-04, 22:25): a long shot priced at 0.0
    against a short one at 0.98 - the short one first, as the old rank had
    it; a long one at the floor itself still leads."""
    assert ra.LENGTH_LEAD_MIN_USABILITY == 0.5
    lut = {(IDX, 1): shot(1, 6.0), (IDX, 2): shot(2, 1.2), (IDX, 3): shot(3, 5.0)}
    pool = [cand(1, 6.0, 0.40), cand(2, 1.2, 0.35)]
    with _keys({1: (0, -0.0, 0.0), 2: (0, -0.98, 0.0), 3: (0, -0.5, 0.0)}):
        assert order(pool, lut, need=3.0) == [2, 1]
        assert order(pool, lut) == [2, 1]
        assert order(pool + [cand(3, 5.0, 0.30)], lut, need=3.0) == [3, 2, 1]


def test_the_floor_reads_the_score_not_the_length():
    """Under the floor a long shot is ranked with the short ones by its score:
    a short shot at 0.3 stays behind a long one at 0.4."""
    lut = {(IDX, 1): shot(1, 6.0), (IDX, 2): shot(2, 1.2)}
    with _keys({1: (0, -0.4, 0.0), 2: (0, -0.3, 0.0)}):
        assert order([cand(2, 1.2, 0.40), cand(1, 6.0, 0.30)], lut, need=3.0) == [1, 2]


def test_the_length_reads_from_the_cut_point():
    """A moment mark moves the cut: what counts is `available_seconds()`."""
    if not need_indexer():
        return
    marked = cand(1, 10.0, 0.31)
    marked["moment_at"] = 8.5      # ~1.5 s left after the cut point
    lut = {(IDX, 1): shot(1, 10.0), (IDX, 2): shot(2, 4.0, {"roi_coverage": 0.4})}
    assert ra.available_seconds(marked) < 3.0
    assert order([marked, cand(2, 4.0, 0.30)], lut, need=3.0) == [2, 1]


def test_shot_score_rank_puts_the_lead_between_hard_and_score():
    seen = []
    pool = ["a", "b", "c"]
    keys = {"a": (0, -1.0, 0.0), "b": (0, -0.5, 0.0), "c": (1, -1.0, 0.0)}
    saved = shot_score.rank_key
    shot_score.rank_key = lambda shot, fresh=True, video=None, wide=False: keys[shot]
    try:
        plain = shot_score.rank(pool, lambda c: c)
        led = shot_score.rank(pool, lambda c: c, lead=lambda c: seen.append(c) or c == "a")
    finally:
        shot_score.rank_key = saved
    assert plain == ["a", "b", "c"]
    assert led == ["b", "a", "c"], led      # "a" too short: behind "b"; "c" hard: last
    assert set(seen) == set(pool)


# --- the wiring ---------------------------------------------------------------
def _loop():
    src = inspect.getsource(ra.main)
    return src


def test_fill_asks_for_length_first_on_the_one_shot_rungs_only():
    loop = _loop()
    assert "def fill(pool, reuse_key=None, length_first=False):" in loop
    assert ("pool = rank_by_usability(pool, shots_lut, place,\n"
            "                                     need=need if length_first else None,\n"
            "                                     phrase=a[\"phrase\"], held_whole=held_whole)") in loop
    # CF-0648: the held-whole order only on a length-first walk
    assert "held_whole = length_first and not split_reachable(seg, need, args)" in loop
    # the match, the side retry and the topic rung
    assert loop.count("fill(pool, length_first=budget == 1)") == 2, loop.count(
        "fill(pool, length_first=budget == 1)")
    assert "used, _ = fill(tpool, length_first=budget == 1)" in loop
    # CF-0433: under the floor by rank, never by length; CF-0480: a split's
    # extra cuts go on from the first one by rank.
    assert "used, capped = fill(bpool)\n" in loop
    assert "more, more_capped = fill(rest)\n" in loop


def test_the_record_says_which_order_each_run_walked():
    a, b = cand(1, 6.0), cand(2, 1.0)
    first = ra.fill_run([a, b], [(a, 0)], [], length_first=True)
    under = ra.fill_run([b], [(b, 0)], [])
    rec = ra.length_supply(3.0, [first, under])
    assert rec["rung_order"] == [ra.LENGTH_ORDER_FIRST, ra.LENGTH_ORDER_RANK], rec
    assert ra.length_supply(3.0, [])["rung_order"] == []


# --- end to end through main() --------------------------------------------------
@contextlib.contextmanager
def _patched(index_shots, candidates):
    saved = {k: getattr(ra, k) for k in
             ("match", "cut", "usable", "audio_duration", "leading_silence", "load_words")}
    index_data = {IDX: {"source": SRC, "shots": index_shots}}
    by = {s["index"]: s for s in index_shots}

    def fake_match(indexes, phrases, min_score, top, python):
        cands = [{"shot": n, "score": sc, "start": by[n]["start"], "end": by[n]["end"],
                  "card": False, "promoted": False, "index": IDX, "source": SRC}
                 for n, sc in candidates]
        cands = ra.order_candidates(cands, 0)
        return [{"phrase": ph, "found": True, "discriminative": True, "margin": 0.1,
                 "candidates": list(cands)} for ph in phrases], index_data

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    ra.match, ra.cut = fake_match, fake_cut
    ra.usable = lambda clip, seconds, *a, **kw: (True, [])
    ra.audio_duration = lambda path: 6.0
    ra.leading_silence = lambda path: 0.0
    ra.load_words = lambda path: [{"word": "w", "start": 0.4 + 0.5 * i,
                                   "end": 0.8 + 0.5 * i} for i in range(10)]
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(ra, k, v)


def _run_main(index_shots, candidates):
    with tempfile.TemporaryDirectory() as tmp, _patched(index_shots, candidates):
        tmp = Path(tmp)
        anchors = tmp / "anchors.json"
        anchors.write_text(json.dumps({"script_id": "t", "anchors": [
            {"word_index": 1, "phrase": "a wooden water taxi", "emphasis_words": []}]}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(anchors), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", "0.22",
                "--rhythm", "staccato", "--no-stretch-split"]
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                ra.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text())


def test_main_cuts_the_long_weaker_shot_and_records_it():
    """A one-shot block, shot 1 clean and 1.0 s ahead of shot 2 at 30 s with a
    framing price: the block gets shot 2 and plays it, no frame held."""
    if not need_indexer():
        return
    story = _run_main([shot(1, 1.0), shot(2, 30.0, {"roi_coverage": 0.4})],
                      [(1, 0.31), (2, 0.30)])
    b = story["blocks"][0]
    assert b["shot"].endswith(":2"), b
    assert b["held_frame"] is False, b
    rec = b["length_supply"]
    assert rec["rung_order"][0] == ra.LENGTH_ORDER_FIRST, rec
    by = {e["shot"]: e for e in rec["long_enough"]}
    long_one = next(e for e in by.values() if e["shot"].endswith(":2"))
    assert long_one["outcome"] == ra.LENGTH_CUT and long_one["rank"] == 0, rec
    assert all(not e["shot"].endswith(":1") for e in rec["long_enough"]), rec


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

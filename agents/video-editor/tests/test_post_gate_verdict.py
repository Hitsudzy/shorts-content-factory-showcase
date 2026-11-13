#!/usr/bin/env python3
"""CF-0088: `unresolved_anchors` tells the truth after the gates, and `--top`
says when it filtered nothing.

Two findings from run 2026-09-03T2037Z, both about what the resolver reports:

  * Wren Hollow, attempt 1 (RUN_LOG.txt:26): the matcher's first picks lost
    to their cached caption crop and cached usability, the block was filled
    with whatever was left, and `unresolved_anchors` said nothing - `found`
    had been settled on the matcher's best score before any gate ran. The
    verdict is now `resolve_anchors.gate_verdict()`, taken on what `fill()`
    actually used, and it carries each gate's own line per refused shot.
  * Raygun (RUN_LOG.txt:37): a 4-shot pool under the default `--top 10` -
    every shot offered under every phrase, no record of it. The run now
    warns via `resolve_anchors.top_exhausts_pool()`, on stderr and on the
    storyboard's `warnings`.

Pure checks on the two helpers, plus real `main()` runs with the matcher,
the cutter and the clip gate replaced by doubles - so the wiring from a
gate's refusal to the report is what is tested, not a reimplementation of
it. No footage, no CLIP, no ffmpeg. No pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors  # noqa: E402

MIN_SCORE = 0.22
SRC = "/nowhere/pool.mp4"
IDX = "/nowhere/pool.shots.json"


def rej(shot, score, reason):
    return {"phrase": "p", "shot": shot, "score": score, "reason": reason}


# --------------------------------------------------------------------------
# gate_verdict(): pure
# --------------------------------------------------------------------------

def test_best_over_threshold_refused_by_gate_and_weak_survivor_is_unresolved():
    """The Wren Hollow shape: shot 38 (0.31) lost to its caption crop, shot
    24 (0.28) to cached usability, shot 7 (0.15) was cut. Pre-CF-0088 this
    was `found` and silent; now it is unresolved and names both refusals."""
    used = [{"shot": 7, "score": 0.15}]
    rejected = [rej(38, 0.31, "failed usable() on the cut clip: height 640 < 720 (CF-0062)"),
                rej(24, 0.28, "pre-filtered by cached shot usability, not cut")]
    v = resolve_anchors.gate_verdict("p", used, rejected, 0, 3, MIN_SCORE)
    assert v is not None, "a sub-threshold survivor behind refused stronger matches was reported found"
    assert v["found_after_gate"] is False
    assert v["best_used_score"] == 0.15
    assert "0.150" in v["reason"] and "using it anyway" in v["reason"], v["reason"]
    assert "2 candidate(s) over the threshold were refused by the gates" in v["reason"], v["reason"]
    assert "shot 38: failed usable() on the cut clip: height 640 < 720 (CF-0062)" in v["reason"]
    assert "shot 24: pre-filtered by cached shot usability" in v["reason"]
    assert [r["shot"] for r in v["gate_rejections"]] == [38, 24]


def test_every_candidate_refused_carries_each_gates_own_line():
    rejected = [rej(3, 0.30, "failed usable() on the cut clip: mean luma 0.05 < 0.20"),
                rej(5, 0.25, "prepare_clip.py failed to cut it"),
                rej(9, 0.10, "would cut to 0.40s - too short to read")]
    v = resolve_anchors.gate_verdict("p", [], rejected, 0, 3, MIN_SCORE)
    assert v["found_after_gate"] is False
    assert v["reason"].startswith("every candidate failed a gate - "), v["reason"]
    for line in ("shot 3: failed usable() on the cut clip: mean luma 0.05 < 0.20",
                 "shot 5: prepare_clip.py failed to cut it",
                 "shot 9: would cut to 0.40s - too short to read"):
        assert line in v["reason"], (line, v["reason"])
    assert len(v["gate_rejections"]) == 3
    assert "failed to cut" not in v["reason"].replace("failed to cut it", ""), \
        "the old blanket wording is back"


def test_a_survivor_over_threshold_is_found_whatever_was_refused_ahead_of_it():
    """Normal case: gates refused a stronger shot but the one used still
    clears --min-score - that is a found anchor, not an unresolved one."""
    used = [{"shot": 2, "score": 0.27}]
    rejected = [rej(1, 0.33, "pre-filtered by cached shot usability, not cut")]
    assert resolve_anchors.gate_verdict("p", used, rejected, 0, 2, MIN_SCORE) is None
    assert resolve_anchors.gate_verdict("p", used, [], 0, 1, MIN_SCORE) is None


def test_reuse_cap_wording_is_kept_when_that_is_the_whole_story():
    rejected = [rej(1, 0.3, "already used 3x elsewhere in this video (CF-0026 cap)")] * 2
    v = resolve_anchors.gate_verdict("p", [], rejected, 2, 2, MIN_SCORE)
    assert v["reason"].startswith("every remaining candidate was already used"), v["reason"]


def test_weak_survivor_with_nothing_stronger_refused_says_only_that():
    """The pre-CF-0088 `not found` case, now taken after the gate: nothing
    scored over the threshold, so there is nobody to blame a gate for."""
    v = resolve_anchors.gate_verdict("p", [{"shot": 1, "score": 0.12}],
                                     [rej(4, 0.11, "pre-filtered by cached shot usability, not cut")],
                                     0, 2, MIN_SCORE)
    assert v is not None and "using it anyway" in v["reason"]
    assert "refused by the gates" not in v["reason"], v["reason"]
    assert v["gate_rejections"] == []


# --------------------------------------------------------------------------
# top_exhausts_pool(): pure
# --------------------------------------------------------------------------

def _index(n_plain, n_cards=0, source=SRC):
    shots = [{"index": i, "start": i * 3.0, "end": i * 3.0 + 3.0} for i in range(n_plain)]
    shots += [{"index": n_plain + j, "start": 0.0, "end": 3.0, "is_card": True}
              for j in range(n_cards)]
    return {"source": source, "shots": shots}


def test_small_pool_under_default_top_warns():
    """Raygun: 4 shots, --top 10."""
    w = resolve_anchors.top_exhausts_pool({IDX: _index(4)}, 10)
    assert len(w) == 1, w
    assert "--top 10 >= 4 candidate shot(s) in pool.mp4" in w[0], w[0]
    assert "filtered nothing" in w[0] and "CF-0088" in w[0]


def test_pool_exactly_top_is_still_no_filter():
    assert len(resolve_anchors.top_exhausts_pool({IDX: _index(10)}, 10)) == 1
    assert resolve_anchors.top_exhausts_pool({IDX: _index(11)}, 10) == []


def test_pool_larger_than_top_is_silent_and_cards_do_not_count():
    assert resolve_anchors.top_exhausts_pool({IDX: _index(40)}, 10) == []
    # 8 plain shots plus 5 cards: the matcher ranks a plain phrase over the 8.
    assert len(resolve_anchors.top_exhausts_pool({IDX: _index(8, n_cards=5)}, 10)) == 1
    assert resolve_anchors.top_exhausts_pool({IDX: _index(4)}, 1) == []


def test_each_index_is_judged_on_its_own():
    w = resolve_anchors.top_exhausts_pool(
        {IDX: _index(40), "/nowhere/b.json": _index(3, source="/nowhere/b.mp4")}, 10)
    assert len(w) == 1 and "b.mp4" in w[0], w


# --------------------------------------------------------------------------
# main(): the wiring, with the matcher / cutter / gate replaced
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _patched(candidates, gate, n_plain_shots=4):
    """Run main() against doubles. `candidates`: [(shot, score)] the matcher
    returns for the one anchor; `gate(shot) -> (ok, failures)` is what
    usable() says about that shot's cut clip."""
    saved = {k: getattr(resolve_anchors, k) for k in
             ("match", "cut", "usable", "audio_duration", "leading_silence", "load_words")}
    index_data = {IDX: _index(n_plain_shots)}
    shot_len = {s["index"]: (s["start"], s["end"]) for s in index_data[IDX]["shots"]}

    def fake_match(indexes, phrases, min_score, top, python):
        cands = [{"shot": s, "score": sc, "start": shot_len[s][0], "end": shot_len[s][1],
                  "card": False, "promoted": False, "index": IDX, "source": SRC}
                 for s, sc in candidates]
        cands = resolve_anchors.order_candidates(cands, 0)
        return [{"phrase": ph, "found": bool(cands) and max(c["score"] for c in cands) >= min_score,
                 "discriminative": True, "margin": 0.1, "candidates": cands}
                for ph in phrases], index_data

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        # `card` (CF-0092) only picks the caption-crop ceiling inside the real
        # cut(); these tests never look at the crop, so accept and ignore it.
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_usable(clip, seconds, *a, **kw):
        shot = int(Path(clip).stem.rsplit("_s", 1)[1])
        return gate(shot)

    resolve_anchors.match = fake_match
    resolve_anchors.cut = fake_cut
    resolve_anchors.usable = fake_usable
    resolve_anchors.audio_duration = lambda path: 6.0
    resolve_anchors.leading_silence = lambda path: 0.0
    resolve_anchors.load_words = lambda path: [{"word": "w", "start": 0.4 + 0.5 * i,
                                                "end": 0.8 + 0.5 * i} for i in range(10)]
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(resolve_anchors, k, v)


def _run_main(candidates, gate, extra_args=(), n_plain_shots=4):
    with tempfile.TemporaryDirectory() as tmp, _patched(candidates, gate, n_plain_shots):
        tmp = Path(tmp)
        anchors = tmp / "anchors.json"
        anchors.write_text(json.dumps({"script_id": "t", "anchors": [
            {"word_index": 1, "phrase": "a wooden lake house", "emphasis_words": []}]}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(anchors), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", str(MIN_SCORE),
                *extra_args]
        err = io.StringIO()
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                resolve_anchors.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text()), err.getvalue()


def _found_records(story):
    return [u for u in story["unresolved_anchors"] if "found_after_gate" in u]


def test_main_best_match_refused_by_the_clip_gate_is_recorded_with_the_gates_reason():
    """Shot 1 (0.31) fails usable() on its cut clip and shot 2 (0.15) is under
    the similarity floor. The record says why in the gate's own words.

    CF-0290 took shot 2 off screen (the block got no picture); CF-0433 (grill
    2026-09-29) puts it back as the best the pool had, marked `below_floor`
    for the plan to price (`score.low_similarity`). The subject of the test is
    untouched: the record names the gate that refused the better match, in the
    gate's own sentence, with its own fields - now in the "using it anyway"
    record gate_verdict() was written with.
    """
    story, err = _run_main([(1, 0.31), (2, 0.15)],
                           lambda s: (False, ["height 640 < 720 after crop (CF-0062)"])
                           if s == 1 else (True, []))
    assert [b["shot"] for b in story["blocks"]] == ["pool:2"], story["blocks"]
    assert story["blocks"][0]["below_floor"] == {
        "phrase": "a wooden lake house", "score": 0.15, "min_score": MIN_SCORE}
    recs = _found_records(story)
    assert len(recs) == 1, story["unresolved_anchors"]
    r = recs[0]
    assert r["found_after_gate"] is False and r["best_used_score"] == 0.15
    assert "using it anyway" in r["reason"], r["reason"]
    assert "shot 1: failed usable() on the cut clip: height 640 < 720 after crop (CF-0062)" \
        in r["reason"], r["reason"]
    crop = [g for g in r["gate_rejections"] if g["shot"] == 1][0]
    assert crop["lost_to_crop"] is True, "the gate's own fields are kept"


def test_main_every_candidate_refused_is_unresolved_with_every_reason():
    story, err = _run_main([(1, 0.31), (2, 0.25)],
                           lambda s: (False, [f"mean luma too low on shot {s}"]))
    assert story["blocks"] == [], story["blocks"]
    recs = _found_records(story)
    assert len(recs) == 1, story["unresolved_anchors"]
    reason = recs[0]["reason"]
    assert reason.startswith("every candidate failed a gate - "), reason
    assert "shot 1: failed usable() on the cut clip: mean luma too low on shot 1" in reason
    assert "shot 2: failed usable() on the cut clip: mean luma too low on shot 2" in reason
    assert reason == recs[0]["reason"]
    assert len(recs[0]["gate_rejections"]) == 2


def test_main_candidate_that_passes_is_found_and_the_report_is_unchanged():
    story, err = _run_main([(1, 0.31), (2, 0.31)], lambda s: (True, []))
    assert story["blocks"][0]["shot"] == "pool:1"
    assert _found_records(story) == [], story["unresolved_anchors"]
    assert "UNRESOLVED" not in err, err
    assert story["rejected_candidates"] == []


def test_main_a_candidate_under_the_similarity_floor_is_never_offered():
    """CF-0290: the second shot used to be the fallback for this block; now it
    is refused in front of `fill()`, by name and score, and the block that the
    0.31 shot fills is unresolved-free all the same."""
    story, err = _run_main([(1, 0.31), (2, 0.15)], lambda s: (True, []))
    assert story["blocks"][0]["shot"] == "pool:1"
    assert _found_records(story) == [], story["unresolved_anchors"]
    refused = story["rejected_candidates"]
    assert len(refused) == 1 and refused[0]["shot"] == 2, refused
    # CF-0433: held back, not refused outright - a block the 0.31 shot fills
    # never reaches it.
    assert "under the 0.22 similarity floor - held back (CF-0290)" \
        in refused[0]["reason"], refused[0]["reason"]
    assert "below_floor" not in story["blocks"][0]


def test_main_small_pool_under_default_top_warns_on_stderr_and_in_the_storyboard():
    story, err = _run_main([(1, 0.31)], lambda s: (True, []), n_plain_shots=4)
    assert len(story["warnings"]) == 1, story["warnings"]
    assert "--top 10 >= 4 candidate shot(s) in pool.mp4" in story["warnings"][0]
    assert "WARNING: --top 10 >= 4 candidate shot(s)" in err, err


def test_main_explicit_top_at_or_over_pool_size_warns_too():
    story, err = _run_main([(1, 0.31)], lambda s: (True, []), extra_args=["--top", "4"],
                           n_plain_shots=4)
    assert len(story["warnings"]) == 1 and "--top 4 >= 4" in story["warnings"][0]


def test_main_pool_larger_than_top_does_not_warn():
    story, err = _run_main([(1, 0.31)], lambda s: (True, []), n_plain_shots=40)
    assert story["warnings"] == [], story["warnings"]
    assert "WARNING" not in err, err
    story, err = _run_main([(1, 0.31)], lambda s: (True, []), extra_args=["--top", "3"],
                           n_plain_shots=4)
    assert story["warnings"] == [] and "WARNING" not in err


def test_main_score_floor_refuses_weak_candidates_outright():
    """With --score-floor the 0.15 shot is never cut; with the 0.31 one also
    refused by the gate, the anchor is unresolved and both refusals named."""
    story, err = _run_main([(1, 0.31), (2, 0.15)],
                           lambda s: (False, ["dark"]) if s == 1 else (True, []),
                           extra_args=["--score-floor", "0.2"])
    assert story["blocks"] == [], story["blocks"]
    recs = _found_records(story)
    assert len(recs) == 1
    assert "shot 2: scores 0.150, under --score-floor 0.2 - never offered (CF-0088)" \
        in recs[0]["reason"], recs[0]["reason"]
    assert "shot 1: failed usable() on the cut clip: dark" in recs[0]["reason"]
    # And without `--score-floor`: CF-0290 took shot 2 off screen, CF-0433
    # admits it again as the best the pool had, marked for the plan's price
    # (`score.low_similarity`). `--score-floor` stays the outright refusal.
    story, _ = _run_main([(1, 0.31), (2, 0.15)],
                         lambda s: (False, ["dark"]) if s == 1 else (True, []))
    assert [b["shot"] for b in story["blocks"]] == ["pool:2"], story["blocks"]
    assert story["blocks"][0]["below_floor"]["score"] == 0.15
    assert _found_records(story)[0]["best_used_score"] == 0.15


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

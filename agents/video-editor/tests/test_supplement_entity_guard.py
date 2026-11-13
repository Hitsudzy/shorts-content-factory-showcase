#!/usr/bin/env python3
"""CF-0348: a thin-pool supplement source's shot without its entity is never
placed - by the regular match, the topic-footage rung (CF-0337), the
emergency repeat (CF-0137) or the split opening - and `qc_render` fails a
plan that carries one anyway.

The case from CF-0344: a video about Everyday Sorcery 2 whose pool was topped
up with Ocean's 8 for Sandra Birch. A frame of Ocean's 8 with Bullock is
material of the topic; a frame of Ocean's 8 without her is somebody else's
film. Ordinary sources are untouched.

Pure checks on `entity_guard`, `resolve_anchors.topic_pool()` and the places
the resolver and qc_render call them (the behavioural run needs real
footage).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import entity_guard  # noqa: E402
import resolve_anchors  # noqa: E402

OWN = "OwnTrailer1"    # the topic's own trailer (11-char id)
SUP = "Oceans8Clip"    # the supplement source, fetched for Sandra Birch
OWN_IDX, SUP_IDX = f"/c/{OWN}/shots.json", f"/c/{SUP}/shots.json"

# Supplement shots: 0 and 2 show Bullock; 1 is in the sieve's off_topic_shots;
# 3 carries the describer's shows_entity: false (and is not in the list).
REPORT = {
    "fetched": [
        {"video_id": OWN, "topic_id": "t1"},
        {"video_id": SUP, "topic_id": "t1",
         "supplement": {"entity": "Sandra Birch"}},
    ],
    "source_sieve": {"sources": [
        {"video_id": OWN, "topic_id": "t1", "verdict": "kept"},
        {"video_id": SUP, "topic_id": "t1", "verdict": "kept",
         "judged_by": "entity", "entity": "Sandra Birch",
         "entity_shots": 2, "off_topic_shots": [1]},
    ]},
}


def _index(vid, n, flags=None):
    flags = flags or {}
    return {"source": f"/footage/{vid}.mp4",
            "shots": [{"index": i, "start": float(2 * i),
                       "end": float(2 * i) + 2.0, **flags.get(i, {})}
                      for i in range(n)]}


def _data():
    return {OWN_IDX: _index(OWN, 2),
            SUP_IDX: _index(SUP, 4, {0: {"shows_entity": True},
                                     1: {"shows_entity": False},
                                     2: {"shows_entity": True},
                                     3: {"shows_entity": False}})}


def _cand(idx, vid, shot, score):
    return {"index": idx, "shot": shot, "score": score, "start": 0.0,
            "end": 3.0, "source": f"/footage/{vid}.mp4"}


SUPS = entity_guard.supplements(REPORT)
OFF = {(SUP, 1), (SUP, 3)}


# --------------------------------------------------------------------------
# which shots
# --------------------------------------------------------------------------

def test_only_the_supplement_source_is_under_the_rule():
    assert set(SUPS) == {SUP}, SUPS
    assert SUPS[SUP]["entity"] == "Sandra Birch"
    assert SUPS[SUP]["off"] == {1}


def test_off_topic_shot_and_shows_entity_false_are_refused_entity_shots_not():
    shots = _data()[SUP_IDX]["shots"]
    src = f"/footage/{SUP}.mp4"
    got = {n for n in range(4)
           if entity_guard.refusal(src, n, shots[n], SUPS)}
    assert got == {1, 3}, got
    # the sieve's list alone refuses shot 1 even without the shots.json entry
    assert entity_guard.refusal(f"{SUP}:1", "1", None, SUPS)


def test_an_ordinary_source_is_untouched_even_with_the_flag():
    shot = {"index": 0, "shows_entity": False}
    assert entity_guard.refusal(f"/footage/{OWN}.mp4", 0, shot, SUPS) is None
    assert entity_guard.supplements(None) == {}
    assert entity_guard.refusal(f"/footage/{SUP}.mp4", 1, None, {}) is None


# --------------------------------------------------------------------------
# the rungs
# --------------------------------------------------------------------------

def test_the_regular_match_never_sees_an_off_entity_shot():
    matches = [{"phrase": "the heist crew", "found": True, "candidates": [
        _cand(SUP_IDX, SUP, 1, 0.31), _cand(SUP_IDX, SUP, 3, 0.29),
        _cand(SUP_IDX, SUP, 2, 0.24), _cand(OWN_IDX, OWN, 0, 0.23)]},
        {"phrase": "a crew without her", "found": True, "candidates": [
            _cand(SUP_IDX, SUP, 1, 0.30)]}]
    refused = entity_guard.screen_matches(matches, _data(), SUPS, 0.22)
    assert [(c["shot"]) for c in matches[0]["candidates"]] == [2, 0]
    assert {(r["phrase"], r["shot"]) for r in refused} == {
        ("the heist crew", 1), ("the heist crew", 3),
        ("a crew without her", 1)}, refused
    assert all("CF-0348" in r["reason"] for r in refused)
    # a phrase left with nothing is no longer "found"
    assert matches[1]["candidates"] == [] and matches[1]["found"] is False
    # and so the emergency repeat - which draws only on the block's own
    # screened candidates - has nothing of it to repeat either


def test_an_empty_block_gets_the_entity_shot_never_the_one_without():
    """The pool of the topic = its own source + the supplement. The own
    source is spent; the empty block's topic rung reaches the supplement and
    takes a shot with Bullock - the ones without her are not in the pool at
    all, in any order, from either of its two halves."""
    data = _data()
    cands = [_cand(SUP_IDX, SUP, 1, 0.21), _cand(SUP_IDX, SUP, 2, 0.20),
             _cand(OWN_IDX, OWN, 0, 0.19)]
    pool = resolve_anchors.topic_pool(cands, data, 0.22, None, SUPS)
    keys = [(Path(c["source"]).stem, c["shot"]) for c in pool]
    assert not OFF & set(keys), keys
    assert (SUP, 0) in keys and (SUP, 2) in keys, keys
    used = {(OWN, 0), (OWN, 1)}              # the topic's own source is spent
    pick = next(k for k in keys if k not in used)
    assert pick in {(SUP, 0), (SUP, 2)}, pick
    # without the guard the rung *would* have offered them - the test bites
    bare = resolve_anchors.topic_pool(cands, data, 0.22, None)
    assert OFF <= {(Path(c["source"]).stem, c["shot"]) for c in bare}


def test_fill_asks_the_guard_for_every_pick_and_main_screens_first():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    fill = src.split("def fill(pool, reuse_key=None, length_first=False):")[1].split(
        "return used, capped")[0]
    assert "entity_guard.refusal(cand[\"source\"], cand[\"shot\"]" in fill
    # CF-0904: a cut is laid down by take() - a fresh one at `if take(c):`,
    # a held one (it passed every gate before it was held) by take_held().
    assert fill.index("entity_guard.refusal(") < fill.index("if take(c):")
    assert fill.index("entity_guard.refusal(") < fill.index("held = c")
    main = src.split("def main():")[1]
    # screened right after the match, before the split opening and the loop
    screen = main.index("entity_guard.screen_matches(matches")
    assert screen < main.index("build_split_opening(")
    assert screen < main.index("for si, seg in enumerate(segments):")
    assert "topic_pool(m[\"candidates\"], index_data, args.min_score,\n" \
           "                               args.score_floor, sups)" in main


def test_the_report_is_found_above_the_clips_dir():
    with tempfile.TemporaryDirectory() as d:
        batch = Path(d)
        clips = batch / "work" / "slug" / "clips"
        clips.mkdir(parents=True)
        (batch / "01b-footage-index.json").write_text(json.dumps(REPORT))
        f = entity_guard.find_report(clips)
        assert f == (batch / "01b-footage-index.json").resolve(), f
        assert entity_guard.find_report(batch / "work" / "slug" / "plan.json") == f


# --------------------------------------------------------------------------
# qc_render
# --------------------------------------------------------------------------

def test_a_plan_with_an_off_entity_shot_is_named_block_by_block():
    plan = {"blocks": [
        {"shot": f"{OWN}:0", "asset": {"kind": "clip"}},
        {"shot": f"{SUP}:2", "asset": {"kind": "clip"}},
        {"shot": f"{SUP}:1", "asset": {"kind": "clip"}},
        {"asset": {"kind": "side_by_side", "halves": [
            {"src": f"clips/open_a_{OWN}_s001.mp4"},
            {"src": f"clips/open_b_{SUP}_s001.mp4"}]}},
        {"asset": {"kind": "procedural"}},
    ]}
    v = entity_guard.plan_violations(plan, SUPS)
    assert [(x["block"], x["shot"]) for x in v] == [
        (2, f"{SUP}:1"), (3, f"{SUP}:1")], v
    assert entity_guard.plan_violations(plan, {}) == []


def test_qc_render_fails_on_it():
    src = (SCRIPTS / "qc_render.py").read_text()
    assert "entity_guard.plan_violations(\n            plan," in src
    assert src.index("entity_guard.find_report(args.plan)") < src.index(
        "repeat_guard.plan_violations(plan)")
    assert '("without the entity", "entity")' in src


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

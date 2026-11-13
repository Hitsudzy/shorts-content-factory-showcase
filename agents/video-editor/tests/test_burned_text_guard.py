#!/usr/bin/env python3
"""CF-0351: a shot the describer marked `burned_text: true` (somebody else's
caption, title or end card - footage-indexer shot_schema, CF-0299) is never
placed, from any source, and `qc_render` fails a plan that carries one.

The case from CF-0346: block 0 of everyday-sorcery-2 was `Ho10_4IX1jE:43`, a
"Nora Kingsley" name card on black from a trailer. The same shots.json read
makes a supplement shot's `shows_entity: false` visible to qc_render too
(before, the plan carried no shot entry and qc saw only `off_topic_shots`).
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
import qc_render  # noqa: E402
import resolve_anchors  # noqa: E402

OWN = "OwnTrailer1"
SUP = "Oceans8Clip"
OWN_IDX, SUP_IDX = f"/c/{OWN}/shots.json", f"/c/{SUP}/shots.json"
REPORT = {"fetched": [{"video_id": SUP, "supplement": {"entity": "Sandra Birch"}}]}
SUPS = entity_guard.supplements(REPORT)


def _index(vid, n, flags):
    return {"source": f"/footage/{vid}.mp4",
            "shots": [{"index": i, "start": float(2 * i),
                       "end": float(2 * i) + 2.0, **flags.get(i, {})}
                      for i in range(n)]}


def _data():
    # own source: 1 is a name card (burned text), 2 describer said no text
    # supplement: 0 shows the entity; 1 does not; 2 shows it but is a card
    return {OWN_IDX: _index(OWN, 3, {1: {"burned_text": True, "is_card": True},
                                     2: {"burned_text": False}}),
            SUP_IDX: _index(SUP, 3, {0: {"shows_entity": True},
                                     1: {"shows_entity": False},
                                     2: {"shows_entity": True,
                                         "burned_text": True}})}


def _cand(idx, vid, shot, score):
    return {"index": idx, "shot": shot, "score": score, "start": 0.0,
            "end": 3.0, "source": f"/footage/{vid}.mp4"}


def test_refusal_reads_the_flag_on_any_source():
    d = _data()
    assert "CF-0351" in entity_guard.refusal(
        f"/footage/{OWN}.mp4", 1, d[OWN_IDX]["shots"][1], {})
    assert entity_guard.refusal(f"/footage/{OWN}.mp4", 2,
                                d[OWN_IDX]["shots"][2], {}) is None
    assert entity_guard.refusal(f"/footage/{OWN}.mp4", 0,
                                d[OWN_IDX]["shots"][0], None) is None
    # an unasked shot (no flag) is not a refused one
    assert entity_guard.refusal(f"/footage/{OWN}.mp4", 1, None, {}) is None


def test_the_match_screen_runs_without_any_supplement():
    matches = [{"phrase": "Nora Kingsley", "found": True, "candidates": [
        _cand(OWN_IDX, OWN, 1, 0.31), _cand(OWN_IDX, OWN, 0, 0.24)]},
        {"phrase": "the name card", "found": True, "candidates": [
            _cand(OWN_IDX, OWN, 1, 0.30)]}]
    refused = entity_guard.screen_matches(matches, _data(), {}, 0.22)
    assert [c["shot"] for c in matches[0]["candidates"]] == [0]
    assert [(r["phrase"], r["shot"]) for r in refused] == [
        ("Nora Kingsley", 1), ("the name card", 1)], refused
    assert all("burned_text" in r["reason"] for r in refused)
    assert matches[1]["candidates"] == [] and matches[1]["found"] is False


def test_the_topic_rung_never_offers_it():
    d = _data()
    cands = [_cand(OWN_IDX, OWN, 1, 0.21), _cand(SUP_IDX, SUP, 0, 0.20)]
    for sups in (None, SUPS):
        pool = resolve_anchors.topic_pool(cands, d, 0.22, None, sups)
        keys = {(Path(c["source"]).stem, c["shot"]) for c in pool}
        assert (OWN, 1) not in keys and (SUP, 2) not in keys, keys
        assert (OWN, 0) in keys and (OWN, 2) in keys and (SUP, 0) in keys


def test_fill_asks_the_same_question():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    fill = src[src.index("off_entity = entity_guard.refusal(cand"):]
    assert fill.index("rejected_candidates.append") < fill.index("continue")


def _footage(tmp):
    for vid, idx in ((OWN, OWN_IDX), (SUP, SUP_IDX)):
        (Path(tmp) / f"{vid}.shots.json").write_text(json.dumps(_data()[idx]))
    return entity_guard.shot_reader(tmp)


def test_qc_sees_both_flags_through_shots_json():
    plan = {"blocks": [
        {"shot": f"{OWN}:0"},
        {"shot": f"{OWN}:1", "is_card": True},              # the name card
        {"shot": f"{SUP}:0"},
        {"shot": f"{SUP}:1"},                               # without Bullock
        {"asset": {"kind": "side_by_side", "halves": [
            {"src": f"clips/open_a_{OWN}_s002.mp4"},
            {"src": f"clips/open_b_{SUP}_s002.mp4"}]}},      # card half
        {"shot": "Unknown0000:5"},                          # no shots.json
        {"asset": {"kind": "procedural"}},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        reader = _footage(tmp)
        v = entity_guard.plan_violations(plan, SUPS, shots_of=reader)
        got = [(x["block"], x["shot"], "CF-0351" in x["reason"]) for x in v]
        assert got == [(1, f"{OWN}:1", True), (3, f"{SUP}:1", False),
                       (4, f"{SUP}:2", True)], got
        # the burned card counts with no supplement at all
        v2 = entity_guard.plan_violations(plan, {}, shots_of=reader)
        assert [(x["block"], x["shot"]) for x in v2] == [
            (1, f"{OWN}:1"), (4, f"{SUP}:2")], v2
    # and before CF-0351, without the entry, qc saw neither
    assert entity_guard.plan_violations(plan, SUPS) == []


def test_qc_render_wires_it_and_names_the_gate():
    src = (SCRIPTS / "qc_render.py").read_text()
    assert "shots_of=entity_guard.shot_reader(args.footage_dir)" in src
    assert "--footage-dir" in src
    reason = entity_guard.refusal(f"{OWN}:1", 1, {"burned_text": True}, {})
    msg = f"shot with burned-in text: block 1 ({OWN}:1) - {reason}"
    assert qc_render.failed_gates([msg]) == ["burned_text"]


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

#!/usr/bin/env python3
"""CF-0354: a shot with `is_card: true` and no answer on `burned_text`
(the key missing or null - two thirds of the pool was indexed before the
describer was asked, CF-0299) counts as burned-in text: refused on every
rung, and `qc_render` fails a plan that carries one, until the describer
marks it `false`. A non-card without the flag still passes.

The case from CF-0351: after `Ho10_4IX1jE:43` was refused, block 0 of
everyday-sorcery-2 took `QE0W5UW2qxE:20` - `is_card: true`, "a retro website
interface ... reading MovieLink", no `burned_text` key at all.
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

VID = "QE0W5UW2qxE"
IDX = f"/c/{VID}/shots.json"
SRC = f"/footage/{VID}.mp4"
# 0 plain non-card, no flag     -> passes (an unasked shot is not refused)
# 1 card, no burned_text key    -> refused (the MovieLink case)
# 2 card, burned_text: null     -> refused
# 3 card, burned_text: false    -> passes (the describer answered)
# 4 card, burned_text: true     -> refused by CF-0351 as before
# 5 non-card, burned_text: null -> passes
FLAGS = {1: {"is_card": True},
         2: {"is_card": True, "burned_text": None},
         3: {"is_card": True, "burned_text": False},
         4: {"is_card": True, "burned_text": True},
         5: {"is_card": False, "burned_text": None}}


def _data():
    return {IDX: {"source": SRC, "shots": [
        {"index": i, "start": float(2 * i), "end": float(2 * i) + 2.0,
         **FLAGS.get(i, {})} for i in range(6)]}}


def _shot(i):
    return _data()[IDX]["shots"][i]


def test_refusal_counts_an_unanswered_card_as_text():
    for sups in ({}, None):
        got = {i: entity_guard.refusal(SRC, i, _shot(i), sups) for i in range(6)}
        assert got[0] is None and got[3] is None and got[5] is None, got
        for i in (1, 2):
            assert "CF-0354" in got[i] and "CF-0351" in got[i], got[i]
            assert "is_card" in got[i]
        assert "CF-0351" in got[4] and "CF-0354" not in got[4]
    # no entry at all - still not a refused shot
    assert entity_guard.refusal(SRC, 1, None, {}) is None


def test_the_match_screen_and_the_topic_rung_drop_it():
    matches = [{"phrase": "MovieLink", "found": True, "candidates": [
        {"index": IDX, "shot": i, "score": 0.30 - 0.01 * i, "start": 0.0,
         "end": 3.0, "source": SRC} for i in range(6)]}]
    refused = entity_guard.screen_matches(matches, _data(), {}, 0.22)
    assert [c["shot"] for c in matches[0]["candidates"]] == [0, 3, 5]
    assert sorted(r["shot"] for r in refused) == [1, 2, 4], refused
    cands = [{"index": IDX, "shot": i, "score": 0.21, "start": 0.0,
              "end": 3.0, "source": SRC} for i in range(6)]
    pool = resolve_anchors.topic_pool(cands, _data(), 0.22, None, {})
    assert sorted(c["shot"] for c in pool) == [0, 3, 5], pool


def test_qc_fails_it_under_the_burned_text_gate():
    plan = {"blocks": [{"shot": f"{VID}:{i}"} for i in range(6)]}
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / f"{VID}.shots.json").write_text(json.dumps(_data()[IDX]))
        v = entity_guard.plan_violations(
            plan, {}, shots_of=entity_guard.shot_reader(tmp))
    assert [x["block"] for x in v] == [1, 2, 4], v
    msgs = [f"shot with burned-in text: block {x['block']} ({x['shot']}) - "
            f"{x['reason']}" for x in v]
    assert qc_render.failed_gates(msgs) == ["burned_text"]
    # qc_render labels it by the CF-0351 mark in the reason
    src = (SCRIPTS / "qc_render.py").read_text()
    assert '"CF-0351" in v["reason"]' in src
    assert all("CF-0351" in x["reason"] for x in v)


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

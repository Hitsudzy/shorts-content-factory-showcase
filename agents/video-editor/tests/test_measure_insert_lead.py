#!/usr/bin/env python3
"""CF-0402: scripts/measure_insert_lead.py measures what the layer does.

The CF-0143 measurement scored the raw CLIP leader. Since CF-0392 the layer's
walk steps over a leader the stretch gate refuses and offers the request to
the next rank, with that rank's own lead - so the measurement's `accepts()`
and `pick()` have to be that walk, and its labelled set has to point at
pictures the library holds and the gate lets through. These tests pin both
without the CLIP encoder:

- `lead()` is meme_layer.lead_over_field() at any rank;
- a cut leader that clears both floors hands the request to the next rank,
  measured with that rank's own lead; one that fails a floor ends the walk;
- every id HITS expects is in the factory library and not stretch-cut - the
  check that would have caught 82 of 104 expected ids pointing at deleted
  memes (CF-0402) the day they were deleted.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import measure_insert_lead as mil  # noqa: E402
import meme_layer as ml  # noqa: E402
import repo_paths  # noqa: E402


def test_lead_is_the_layers_lead_at_every_rank():
    ranked = [(0.31, "a"), (0.30, "b"), (0.28, "c"), (0.25, "d")]
    as_layer = [(s, {"id": i}) for s, i in ranked]
    for i in range(len(ranked) + 1):
        for k in (1, 2, 3, 4, 6):
            assert mil.lead(ranked, k, i) == ml.lead_over_field(as_layer, i, k), (i, k)


def test_a_cut_leader_that_clears_the_floors_passes_the_request_on():
    # "cut" leads by 0.04 over the third place; "b" - the pick - leads "d"
    # by 0.03, its own lead, not the leader's.
    ranked = [(0.30, "cut"), (0.29, "b"), (0.26, "c"), (0.26, "d"), (0.20, "e")]
    assert mil.pick(ranked, {"cut"}) == 1
    assert mil.accepts(ranked, 0.26, 0.02, 3, {"cut"})
    # The pick's own lead is what is floored: 0.03 < 0.035 refuses it.
    assert not mil.accepts(ranked, 0.26, 0.035, 3, {"cut"})
    # Without the gate the leader itself is placed.
    assert mil.pick(ranked) == 0 and mil.accepts(ranked, 0.26, 0.035, 3)


def test_a_cut_leader_that_fails_a_floor_ends_the_walk():
    # The cut leader is level with the field: select() breaks on the lead
    # floor there and never reaches "b", however clear "b" stands.
    level = [(0.30, "cut"), (0.30, "x"), (0.30, "b"), (0.10, "c"), (0.05, "d")]
    assert not mil.accepts(level, 0.26, 0.02, 3, {"cut"})
    # The same field with "x" gone from it: the cut leader now stands clear,
    # and "b" is placed on its own lead over "d".
    clear = [(0.30, "cut"), (0.30, "b"), (0.10, "c"), (0.05, "d")]
    assert mil.accepts(clear, 0.26, 0.02, 3, {"cut"})


def test_nothing_is_picked_when_every_candidate_is_cut():
    ranked = [(0.4, "a"), (0.3, "b")]
    assert mil.pick(ranked, {"a", "b"}) is None
    assert not mil.accepts(ranked, 0.0, 0.0, 3, {"a", "b"})


def test_hits_point_at_pictures_the_library_holds_and_can_place():
    root = Path(repo_paths.FACTORY_ROOT)
    index = json.loads((root / "shared" / "inserts" / "memes" / "index.json").read_text())
    entries = index["entries"]
    ids = {e["id"] for e in entries}
    expected = {eid for _q, want in mil.HITS for eid in want}
    gone = sorted(expected - ids)
    assert not gone, (f"HITS expects memes no longer in {root}/shared/inserts/memes: {gone} - "
                      "relabel HITS and re-run measure_insert_lead.py --scan (CF-0402)")
    cut = mil.stretch_cut(root, entries)
    assert not expected & cut, f"HITS expects pictures the stretch gate cuts: {sorted(expected & cut)}"
    # Labels stay disjoint: a query is a hit or a miss, never both.
    assert not {q for q, _ in mil.HITS} & set(mil.MISSES)


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

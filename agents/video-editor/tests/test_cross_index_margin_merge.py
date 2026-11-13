#!/usr/bin/env python3
"""CF-0227: `margin: null` from one index must not poison the cross-index merge.

`match_anchors.py` answers per index, and for an index that has no candidate at
all for a phrase it emits the CF-0083 empty-pool record: `found: false`,
`discriminative: false`, `matches: []`, and **`margin: null`** - null because
there was nothing to measure a margin against, not because the margin was zero.
Three of the pool's 47 sources are all-card (`DSB38pFgM9Y`, `ScKvReYRZ-A`,
`lZ-zoZ8lI4I`), so every ordinary phrase gets that record from them.

`resolve_anchors.match()` merged the per-index answers with
`r[i].get("margin", 0)`, which substitutes the 0 only when the key is *absent*.
The key is present and null, so `max` got a None/float mix and died with
`TypeError: '>' not supported between instances of 'NoneType' and 'float'` -
the crash CF-0151 hit when it ran the coverage preflight over the whole pool in
one command. It never reproduced on a single index because `max` of a one-item
iterable returns that item without comparing anything: a one-index run got a
silent `margin: None` instead of a stack.

The tests below pin both halves of the answer: the nulls are dropped rather
than read as zero (0.0 is a real, flat margin a source can honestly have), and
the merged margin stays null when no index had anything to measure.

The matcher is a double - no CLIP, no subprocess, no model load. The index
files are real temp files only because `match()` loads them for `index_data`.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors  # noqa: E402

PHRASES = ["a woman walking through a doorway"]
MIN_SCORE = 0.22


class _Out:
    def __init__(self, stdout):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def _record(margin, matches):
    """One per-index matcher record, in the shape match_anchors.py emits."""
    return {"phrase": PHRASES[0], "card_phrase": [],
            "found": bool(matches) and matches[0]["score"] >= MIN_SCORE,
            "discriminative": margin is not None and margin >= 0.05,
            "margin": margin, "advice": None, "matches": matches}


def _match(m):
    return {"shot": 0, "start": 0.0, "end": 4.0, "score": 0.31,
            "card": False, "promoted": False, **m}


def _run(per_index_records):
    """Run the real `match()` against a stubbed matcher, one temp index file
    per record. Returns the merged list."""
    saved = resolve_anchors.run_tool
    with tempfile.TemporaryDirectory() as td:
        indexes = []
        payload = {}
        for n, rec in enumerate(per_index_records):
            p = Path(td) / f"src{n}.shots.json"
            p.write_text(json.dumps({
                "source": f"/nowhere/src{n}.mp4",
                "shots": [{"index": 0, "start": 0.0, "end": 4.0}]}))
            indexes.append(str(p))
            payload[str(p)] = [rec]
        resolve_anchors.run_tool = lambda *a, **kw: _Out(json.dumps(
            {"indexes": indexes, "min_score": MIN_SCORE, "min_margin": 0.05,
             "cards": [], "max_promoted_cards": 3,
             "results_by_index": payload}))
        try:
            merged, _ = resolve_anchors.match(
                indexes, PHRASES, MIN_SCORE, 10, "/nowhere/python")
        finally:
            resolve_anchors.run_tool = saved
    return merged


def test_a_null_margin_beside_a_real_one_does_not_crash_the_merge():
    """The CF-0151 crash itself: an all-card index (null) plus an ordinary one
    (0.0841). Two indexes is the smallest pool that can hit it, and it is a
    routine batch pool - six of the fourteen anchor-resolved videos on record
    resolved against two or three sources."""
    merged = _run([
        _record(None, []),                       # all-card source
        _record(0.0841, [_match({"score": 0.31})]),
    ])
    assert len(merged) == 1
    assert merged[0]["margin"] == 0.0841


def test_the_null_is_dropped_not_read_as_zero():
    """A negative margin from a real source must still win over a null. Read as
    0, the null would beat it and the report would claim a margin no index
    measured - `max(None -> 0, -0.012)` is 0."""
    merged = _run([
        _record(None, []),
        _record(-0.0120, [_match({"score": 0.19})]),
    ])
    assert merged[0]["margin"] == -0.0120


def test_the_widest_real_margin_still_wins_across_indexes():
    """The pre-CF-0227 behaviour on a pool with no nulls is unchanged: the
    strongest verdict across indexes, which is what the merge is for."""
    merged = _run([
        _record(0.0410, [_match({"score": 0.24})]),
        _record(0.0930, [_match({"score": 0.37})]),
        _record(0.0570, [_match({"score": 0.28})]),
    ])
    assert merged[0]["margin"] == 0.0930


def test_nulls_everywhere_stay_null_rather_than_becoming_a_flat_zero():
    """A pool of nothing but all-card sources measured nothing, and that is not
    a margin of zero. Null here is the matcher's own answer carried through;
    `resolve_anchors.py`'s unresolved-anchor line prints it as-is."""
    merged = _run([_record(None, []), _record(None, [])])
    assert merged[0]["margin"] is None
    assert merged[0]["candidates"] == []
    assert merged[0]["found"] is False


def test_one_index_with_a_null_no_longer_slips_through_silently():
    """The reason this never showed up before: `max` of a single None returns
    None without comparing, so a one-index run produced `margin: None` with no
    error. It still produces None - but now by the rule above, not by accident,
    and the same rule holds once a second index arrives."""
    merged = _run([_record(None, [])])
    assert merged[0]["margin"] is None


def test_the_merge_reads_margin_without_a_numeric_default():
    """A guard on the *form*, not the case (CF-0077's precedent). `.get(key, 0)`
    over a value the producer writes as null is the defect class; the only
    producer in either repo that writes a numeric key as None is
    match_anchors.py's empty-pool record, and this is its only reader that
    aggregates. If a numeric default comes back to this line, the crash comes
    back with it."""
    import ast
    tree = ast.parse((SCRIPTS / "resolve_anchors.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "match")
    reads = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get" and n.args
             and isinstance(n.args[0], ast.Constant) and n.args[0].value == "margin"]
    assert reads, "match() no longer reads `margin` at all - retarget this guard"
    for r in reads:
        assert len(r.args) == 1, (
            f"resolve_anchors.py:{r.lineno} reads `margin` with a default again; "
            "null is not a margin of zero (CF-0227)")


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

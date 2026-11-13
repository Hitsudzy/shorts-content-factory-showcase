#!/usr/bin/env python3
"""CF-0411: `content_researcher.plan_check_rounds` - the ceiling on the anchor-edit
rounds the Content Researcher's step 6b (`plan_check_loop.py`) allows before it
drops a script as `plan_unassembled`, and its schema.

The key is read outside this repository
(agents/content-researcher/scripts/plan_check_loop.py::rounds_allowed), which
falls back to its default on a value it cannot use - so the schema here is the
only place a `"2"` or a `-1` is caught instead of running as the default.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "inserts"))

import validate_patterns as vp  # noqa: E402
import validate_inserts as vi  # noqa: E402

KEY = vp.CONTENT_RESEARCHER_KEY
ROUNDS = vp.CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY
CTX = "channel.json"




def _errs(block):
    return vp.validate_content_researcher_block({KEY: block}, ctx=CTX)




def test_the_schemas_default_matches_the_readers():
    """CF-0430: plan_check_loop.DEFAULT_ROUNDS is 3 in agents/content-researcher;
    the schema names the same default in its refusal text."""
    assert vp.CONTENT_RESEARCHER_DEFAULT_PLAN_CHECK_ROUNDS == 3
    assert "default 3" in _errs({ROUNDS: -1})[0]


def test_absent_block_and_absent_key_are_legal():
    assert vp.validate_content_researcher_block({}, ctx=CTX) == []
    assert _errs({}) == []
    assert _errs({"note": "x"}) == []


def test_legal_values():
    for n in (0, 1, 2, 3, 4):
        assert _errs({ROUNDS: n}) == [], n


def test_values_the_reader_would_silently_replace_are_refused():
    for bad in ("2", -1, 1.5, True, None):
        errs = _errs({ROUNDS: bad})
        assert errs and ROUNDS in errs[0], bad


def test_typo_and_wrong_shape_are_refused():
    assert _errs({"plan_check_round": 2})
    assert vp.validate_content_researcher_block({KEY: 2}, ctx=CTX)




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

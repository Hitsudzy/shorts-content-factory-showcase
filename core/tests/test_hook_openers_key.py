#!/usr/bin/env python3
"""CF-0424: `content_researcher.hook_openers` and
`content_researcher.hook_opener_min_gap_videos` - the channel's library of hook
openers ('The most talked-about {x}...', 'Nobody noticed...') and the rotation
gap (one opener at most once in every N consecutive videos), and their schema.

Both keys are read outside this repository (agents/content-researcher), so the
schema here is the only place an opener without an id, a duplicated id, an
empty template or a gap of `"5"` is caught before a run reads past it.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "inserts"))

import validate_patterns as vp  # noqa: E402
import validate_inserts as vi  # noqa: E402

KEY = vp.CONTENT_RESEARCHER_KEY
OPENERS = vp.CONTENT_RESEARCHER_HOOK_OPENERS_KEY
GAP = vp.CONTENT_RESEARCHER_HOOK_OPENER_GAP_KEY
CTX = "channel.json"
GOOD = [{"id": "nobody-noticed", "template": "Nobody noticed that {fact}"},
        {"id": "most-important", "template": "This is the most important thing about {x}: {fact}"}]




def _errs(block):
    return vp.validate_content_researcher_block({KEY: block}, ctx=CTX)






def test_absent_keys_are_legal():
    assert _errs({}) == []
    assert _errs({vp.CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY: 2}) == []


def test_legal_values():
    assert _errs({OPENERS: GOOD, GAP: 5}) == []
    for n in (0, 1, 5, 20):
        assert _errs({GAP: n}) == [], n
    assert _errs({OPENERS: GOOD, "hook_openers_note": "x",
                  "hook_opener_min_gap_videos_note": "y"}) == []


def test_empty_or_wrong_shaped_library_is_refused():
    for bad in ([], {}, "nobody-noticed", None, [["a", "b"]]):
        errs = _errs({OPENERS: bad})
        assert errs and OPENERS in errs[0], bad


def test_bad_ids_are_refused():
    for bad_id in (None, "", "Nobody Noticed", "nobody_noticed", 3, "-x"):
        errs = _errs({OPENERS: [{"id": bad_id, "template": "t"}]})
        assert errs and ".id" in errs[0], bad_id
    dup = [GOOD[0], {"id": GOOD[0]["id"], "template": "Other {x}"}]
    errs = _errs({OPENERS: dup})
    assert errs and "twice" in errs[0]


def test_empty_template_and_unknown_opener_key_are_refused():
    for bad_tpl in (None, "", "   ", 5):
        errs = _errs({OPENERS: [{"id": "a", "template": bad_tpl}]})
        assert errs and ".template" in errs[0], bad_tpl
    errs = _errs({OPENERS: [{"id": "a", "template": "t", "weight": 2}]})
    assert errs and "unknown" in errs[0]


def test_gap_values_the_reader_would_silently_replace_are_refused():
    for bad in ("5", -1, 1.5, True, None):
        errs = _errs({GAP: bad})
        assert errs and GAP in errs[0], bad


def test_typo_is_refused():
    assert _errs({"hook_opener": GOOD})
    assert _errs({"hook_opener_min_gap": 5})




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

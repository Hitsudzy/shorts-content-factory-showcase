#!/usr/bin/env python3
"""CF-0578 (the root half of CF-0542): `content_researcher.number_density` -
how many figures a narration may carry per sentence and per 10 words, and what
the writer's check does over it - and its schema.

The key is read outside this repository
(agents/content-researcher/scripts/check_number_density.py::settings), and the
reader quietly runs an unknown mode as `measure` and passes a number through
unchecked - so the schema here is the only place an `"enforce "`, a `"1"` or a
`-1` is caught before a run reads past it.
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
ND = vp.CONTENT_RESEARCHER_NUMBER_DENSITY_KEY
PER_SENT = vp.CONTENT_RESEARCHER_NUMBER_DENSITY_PER_SENTENCE_KEY
PER_10 = vp.CONTENT_RESEARCHER_NUMBER_DENSITY_PER_10_WORDS_KEY
CTX = "channel.json"
READER = ROOT / "agents" / "content-researcher" / "scripts" / "check_number_density.py"




def _errs(nd):
    return vp.validate_content_researcher_block({KEY: {ND: nd}}, ctx=CTX)




def test_absent_key_and_absent_sub_keys_are_legal():
    """Absent means the reader's defaults - the whole key or any sub-key."""
    assert vp.validate_content_researcher_block({KEY: {}}, ctx=CTX) == []
    assert _errs({}) == []
    assert _errs({"mode": "off"}) == []
    assert _errs({PER_SENT: 2}) == []
    assert _errs({PER_10: 0.25, "note": "prose", "mode_note": "prose"}) == []


def test_legal_values():
    for mode in ("measure", "enforce", "off"):
        assert _errs({"mode": mode, PER_SENT: 1, PER_10: 0.4}) == [], mode
    for n in (0, 1, 2, 5):
        assert _errs({PER_SENT: n}) == [], n
    for x in (0, 0.0, 0.25, 0.4, 1, 3.5):
        assert _errs({PER_10: x}) == [], x


def test_wrong_mode_is_refused():
    for bad in ("Measure", "enforce ", "warn", "", None, 1, True, ["measure"]):
        errs = _errs({"mode": bad})
        assert errs and ".mode" in errs[0], bad


def test_negative_or_wrong_typed_per_sentence_is_refused():
    for bad in (-1, 1.5, "1", True, None):
        errs = _errs({PER_SENT: bad})
        assert errs and PER_SENT in errs[0], bad


def test_negative_or_wrong_typed_per_10_words_is_refused():
    for bad in (-0.1, -1, "0.4", True, None, float("nan"), float("inf")):
        errs = _errs({PER_10: bad})
        assert errs and PER_10 in errs[0], bad


def test_wrong_shape_and_typos_are_refused():
    for bad in (None, 1, "measure", [], ["measure", 1, 0.4]):
        errs = _errs(bad)
        assert errs and ND in errs[0], bad
    assert _errs({"max_figures_per_sentense": 1})
    assert _errs({"max_figures_per_10words": 0.4})
    assert vp.validate_content_researcher_block({KEY: {"number_densty": {}}}, ctx=CTX)


def test_schema_agrees_with_the_reader():
    """Mode names and sub-key names are the reader's own, when it is checked out
    beside the root (agents/ is the agents.lock.json checkout)."""
    if not READER.exists():
        return
    sys.path.insert(0, str(READER.parent))
    import check_number_density as cnd  # noqa: E402
    assert cnd.BLOCK == KEY and cnd.KEY == ND
    assert tuple(cnd.MODES) == vp.CONTENT_RESEARCHER_NUMBER_DENSITY_MODES
    assert set(cnd.DEFAULTS) == set(vp.CONTENT_RESEARCHER_NUMBER_DENSITY_READ_KEYS)
    assert _errs(dict(cnd.DEFAULTS)) == []




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

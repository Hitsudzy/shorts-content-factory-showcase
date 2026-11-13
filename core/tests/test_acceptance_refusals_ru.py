#!/usr/bin/env python3
"""CF-0676: every refusal of the acceptance record has a stable code and a
Russian line for the command center (`shared/runlog/acceptance.py`
REFUSALS_RU), the way the channel checks have theirs (CF-0657).

The English text - `str(e)` - stays what it was; journals and the other
acceptance tests read it. The center shows `e.text_ru` and keys on `e.code`
instead of matching English phrases. A raise added without its code, with a
code that has no Russian row, or with a line that needs a value the raise does
not pass fails here - by reading the module's source, so a refusal no test
reaches is caught too. Stand-ins only: verdicts go into lists in memory and a
tmp batch directory that holds nothing.
"""
import ast
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "tests"))

import acceptance  # noqa: E402
from _tmproot import tmp_root  # noqa: E402

TMP = tmp_root("acceptance-refusals-ru-")
SRC = Path(acceptance.__file__).read_text(encoding="utf-8")
CYRILLIC = re.compile(r"[а-яё]", re.I)
CH, BATCH = "example-film", "2026-09-23T1722Z"

# The phrases api/videos.py translated before CF-0676 (its REFUSALS_RU) and the
# codes they are now - the center drops its table for these.
API_PHRASES = {
    "does not name this video": {"answer_without_name", "answer_is_position"},
    "a rejection with no reason": {"rejection_without_reason"},
    "needs a `reason_code`": {"rejection_without_code"},
    "an acceptance carries no `reason_code`": {"acceptance_with_code"},
    "already carries a verdict": {"verdict_already_given"},
    "no topic_id": {"topic_not_found"},
    "not among the videos shown": {"video_not_shown"},
}


def _raises():
    """[(line, code or None, {keyword names})] of every AcceptanceError(...) in the module."""
    out = []
    for node in ast.walk(ast.parse(SRC)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "AcceptanceError"):
            kw = {k.arg: k.value for k in node.keywords}
            code = kw.get("code")
            out.append((node.lineno,
                        code.value if isinstance(code, ast.Constant) else
                        (code.id if isinstance(code, ast.Name) else None),
                        set(kw) - {"code"}))
    return out


def _codes_of_name(name):
    """The string constants assigned to a local name (`code = "..."`) in the module."""
    found = set()
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                found.add(node.value.value)
    return found


def _fields(template):
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def test_every_raise_names_a_code_with_a_russian_row():
    raises = _raises()
    assert len(raises) >= 30, raises
    used = set()
    for line, code, given in raises:
        assert code, f"acceptance.py:{line}: AcceptanceError without code="
        codes = {code} if code in acceptance.REFUSALS_RU else _codes_of_name(code)
        assert codes, f"acceptance.py:{line}: code {code!r} has no Russian row"
        for c in codes:
            assert c in acceptance.REFUSALS_RU, f"acceptance.py:{line}: {c!r} has no Russian row"
            need = _fields(acceptance.REFUSALS_RU[c])
            assert need <= given, f"acceptance.py:{line}: {c} needs {sorted(need - given)}"
        used |= codes
    stray = sorted(set(acceptance.REFUSALS_RU) - used)
    assert not stray, f"Russian rows no refusal raises: {stray}"


def test_rows_are_short_russian_and_codes_stable():
    for code, line in acceptance.REFUSALS_RU.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), code
        assert line.strip() and CYRILLIC.search(line), (code, line)
        assert not re.search(r"\b(?:CF|CC)-\d", line), (code, line)
        assert ".py" not in line and ".json" not in line, (code, line)
        assert len(line) < 200, code


def test_a_code_without_its_row_cannot_be_raised():
    try:
        acceptance.AcceptanceError("x", code="no_such_refusal")
    except KeyError:
        pass
    else:
        raise AssertionError("a refusal with no Russian row was built")
    try:
        acceptance.AcceptanceError("x")
    except TypeError:
        return
    raise AssertionError("a refusal with no code was built")


def _refused(*args, **kw):
    kw.setdefault("code_shas", acceptance.CODE_SHAS_UNKNOWN)
    kw.setdefault("batch_dir", TMP)
    try:
        acceptance.record(*args, **kw)
    except acceptance.AcceptanceError as e:
        assert e.as_dict() == {"code": e.code, "text_ru": e.text_ru, "text": str(e)}
        return e
    raise AssertionError(f"recorded: {args} {kw}")


def test_the_refusals_the_center_translated_carry_their_codes_and_the_slug():
    acc, rej = acceptance.ACCEPTED, acceptance.REJECTED
    cases = [
        _refused(CH, BATCH, "paper-dragon", acc, "the Emmy one is good", rows=[]),
        _refused(CH, BATCH, "paper-dragon", acc, "2", rows=[]),
        _refused(CH, BATCH, "paper-dragon", rej, "paper-dragon no", rows=[]),
        _refused(CH, BATCH, "paper-dragon", rej, "paper-dragon no", rows=[], reason="blurry"),
        _refused(CH, BATCH, "paper-dragon", acc, "paper-dragon yes", rows=[],
                 reason_code="blurry_footage"),
        _refused(CH, BATCH, "paper-dragon", acc, "paper-dragon yes", rows=[],
                 shown=["other-video"]),
        _refused(CH, BATCH, "paper-dragon", acc, "paper-dragon yes", rows=[],
                 strict_topic=True),
    ]
    rows = []
    acceptance.record(CH, BATCH, "paper-dragon", acc, "paper-dragon yes", rows=rows,
                      topic_id="t1", code_shas=acceptance.CODE_SHAS_UNKNOWN, batch_dir=TMP)
    cases.append(_refused(CH, BATCH, "paper-dragon", rej, "paper-dragon no", rows=rows,
                          reason="blurry", reason_code="blurry_footage", topic_id="t1"))
    for phrase, codes in API_PHRASES.items():
        hit = [e for e in cases if phrase in str(e)]
        assert hit, phrase
        for e in hit:
            assert e.code in codes, (phrase, e.code)
            assert CYRILLIC.search(e.text_ru), e.text_ru
            if "{slug}" in acceptance.REFUSALS_RU[e.code]:
                assert "«paper-dragon»" in e.text_ru, e.text_ru
    assert cases[1].code == "answer_is_position"


def test_values_reach_the_russian_line():
    e = _refused(CH, BATCH, "paper-dragon", "maybe", "paper-dragon maybe", rows=[])
    assert e.code == "verdict_unknown" and "«maybe»" in e.text_ru, e.text_ru
    try:
        acceptance.parse_key("example-film/only-two")
    except acceptance.AcceptanceError as e2:
        assert e2.code == "key_malformed" and "«example-film/only-two»" in e2.text_ru
        assert "канал/батч/ролик" in e2.text_ru, e2.text_ru
    else:
        raise AssertionError("a two-part key passed for three")
    try:
        acceptance.place({"entry_id": "a/b/c", "slug": "c", "verdict": acceptance.REJECTED,
                          "reason": "мутный кадр"}, TMP / "c.mp4", publish_dir=TMP / "pub")
    except acceptance.AcceptanceError as e3:
        assert e3.code == "place_not_accepted" and "мутный кадр" in e3.text_ru, e3.text_ru
    else:
        raise AssertionError("a rejected video was placed")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""CF-0752: the Russian reasons for the fact rule's refusal codes
(`shared/factrule/fact_rule_ru.py`, asked for by the command center, CC-0119).

The dictionary must cover every code of `fact_rule.FAIL_CODES` and nothing
else, each reason must be readable Russian, and an unknown code must come back
unchanged rather than raise. Offline; the modules are loaded by path.
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FR = ROOT / "shared" / "factrule"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fact_rule = _load("fact_rule_for_ru_test", FR / "fact_rule.py")
ru = _load("fact_rule_ru_for_test", FR / "fact_rule_ru.py")


def test_the_dictionary_covers_every_fail_code_and_nothing_else():
    assert set(ru.FAIL_CODES_RU) == set(fact_rule.FAIL_CODES), (
        sorted(set(ru.FAIL_CODES_RU) ^ set(fact_rule.FAIL_CODES)))
    assert ru.FAIL_CODES == fact_rule.FAIL_CODES


def test_every_reason_is_non_empty_russian():
    bad = {code: text for code, text in ru.FAIL_CODES_RU.items()
           if not isinstance(text, str) or not text.strip()
           or not re.search(r"[А-Яа-яЁё]", text)
           or re.search(r"[A-Za-z]", text)}
    assert not bad, bad


def test_reason_ru_gives_the_reason_for_a_known_code():
    for code in fact_rule.FAIL_CODES:
        assert ru.reason_ru(code) == ru.FAIL_CODES_RU[code]
    assert ru.reason_ru("cut_short") == "предложение обрезано"


def test_reason_ru_returns_an_unknown_code_unchanged():
    assert ru.reason_ru("no_such_code") == "no_such_code"
    assert ru.reason_ru("") == ""
    assert ru.reason_ru(None) is None
    assert ru.reason_ru(["x"]) == ["x"]


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

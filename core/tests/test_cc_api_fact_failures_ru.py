"""CC-0119 (CF-0752): the Russian reason beside every fact-rule failure code
the API sends - `FactCandidate.failures_ru`, `[{code, ru}]` parallel to
`failures`. `ru` is `shared/factrule/fact_rule_ru.reason_ru(code)`; a code the
factory has no word for (reason_ru gives it back) is `ru: null`. Temp trees
only (`test_cc_api_batch_topics.tree`)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batch_topics import URL, client, tree   # noqa: E402
from test_cc_api_batches import _w                        # noqa: E402

import api                                                # noqa: E402
from api import factory as _factory                       # noqa: E402


def _codes():
    return list(_factory.fact_rule().FAIL_CODES)


def _with_failures(d, failures_by_candidate):
    """Rewrite reel-001's fact_candidates in 01 with the given checks."""
    p = d / "01-trend-hunter.json"
    doc = json.loads(p.read_text())
    t = doc["topics"][0]
    t["fact_candidates"] = [
        {"text": f"fact {i}", "kind": "other", "source": "S", "url": "https://s.example/x",
         "section": None, "check": chk, "scenes": []}
        for i, chk in enumerate(failures_by_candidate)]
    _w(p, doc)


def _cands(root):
    r = client(root).get(f"{URL}/reel-001")
    assert r.status_code == 200, r.text
    return r.json()["fact"]["candidates"]


def test_the_contract_carries_failures_ru():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    spec = spec["components"]["schemas"]
    props = spec["FactCandidate"]["properties"]
    assert "failures_ru" in props
    assert set(spec["FactFailureRu"]["properties"]) == {"code", "ru"}
    assert spec["FactFailureRu"]["required"] == ["code"]


def test_every_fail_code_comes_in_russian():
    codes = _codes()
    assert "cut_short" in codes and len(codes) == 11
    root, d = tree(upto=1)
    _with_failures(d, [{"passes": False, "failures": codes}])
    c = _cands(root)[0]
    assert c["failures"] == codes
    assert [x["code"] for x in c["failures_ru"]] == codes, "parallel, same order"
    ru = _factory.fact_rule_ru().FAIL_CODES_RU
    for x in c["failures_ru"]:
        assert x["ru"] == ru[x["code"]] and x["ru"] != x["code"], x
        assert any("Ѐ" <= ch <= "ӿ" for ch in x["ru"]), x


def test_an_unknown_code_is_null():
    root, d = tree(upto=1)
    _with_failures(d, [{"passes": False, "failures": ["tier", "no_url", "made_up_code"]}])
    c = _cands(root)[0]
    assert [x["code"] for x in c["failures_ru"]] == ["tier", "no_url", "made_up_code"]
    assert c["failures_ru"][0]["ru"] is None and c["failures_ru"][2]["ru"] is None
    assert c["failures_ru"][1]["ru"] == _factory.fact_rule_ru().reason_ru("no_url")


def test_old_data_still_works():
    """A candidate with no check, a check with no failures, a non-string code."""
    root, d = tree(upto=1)
    _with_failures(d, [None, {"passes": True}, {"passes": False, "failures": [7]}])
    a, b, c = _cands(root)
    assert a["failures"] == [] and a["failures_ru"] == [] and a["passes"] is None
    assert b["failures"] == [] and b["failures_ru"] == [] and b["passes"] is True
    assert c["failures"] == ["7"] and c["failures_ru"] == [{"code": "7", "ru": None}]


def test_the_untouched_fixture_unknown_tier_is_null():
    root, _ = tree(upto=7, status="done")
    cands = _cands(root)
    assert cands[0]["failures_ru"] == []
    assert cands[1]["failures_ru"] == [{"code": "tier", "ru": None}]


def test_a_factory_without_the_dictionary_sends_null():
    saved = _factory.FACT_RULE_RU_REL
    _factory.FACT_RULE_RU_REL = "shared/factrule/no_such_file.py"
    try:
        assert _factory.fact_failures_ru(["no_url"]) == [{"code": "no_url", "ru": None}]
        root, d = tree(upto=1)
        _with_failures(d, [{"passes": False, "failures": ["no_url"]}])
        assert _cands(root)[0]["failures_ru"] == [{"code": "no_url", "ru": None}]
    finally:
        _factory.FACT_RULE_RU_REL = saved


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

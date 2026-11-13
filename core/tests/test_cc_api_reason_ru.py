#!/usr/bin/env python3
"""CC-0113: the funnel's codes in Russian from the factory (CF-0714,
`shared/runlog/funnel.py` `REASONS_RU` / `reason_ru`), never from a table of
the API's own.

What is pinned:

* `factory.reason_ru` is the funnel's: every code of REASONS_RU comes through
  word for word, a legacy name by its current one (`canonical_code`), an
  unknown code, an empty one and a non-string are null;
* `factory.with_reason_ru` puts `reason_ru` beside every `reason_code` of a
  nested answer, keeps a row's own `reason_ru` and never writes its input;
* the batch topics (CC-0091, `GET .../topics`, `.../topics/{id}`): every
  skipped topic of every code carries the factory's line as `reason_ru` and in
  its state's line; an unknown code is null and its line says the code;
* `api/topics.py` has no Russian table of codes left (no dict literal that
  maps a funnel code to a Russian string, no REASON_RU);
* the footage progress row's `reason_ru` is the factory's own `reason`;
* the run summary: `data.funnel` rows with `reason_ru` and
  `funnel_reasons_ru` over losses, unknown codes and rows - the kept data
  untouched;
* the footage wanted: `reasons_ru` - the funnel's line first, else
  footage_wanted's own REASONS, else null.

Temp trees only (the stand-in factory of tests/test_cc_api_batches.py); no
network, no live data, nothing timing-sensitive.
"""
import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import _w, client, factory_tree   # noqa: E402

from api import analytics, factory, footage, run_summary   # noqa: E402

CH, B = "reel", "2026-10-14T0900Z"


def fn():
    return factory.funnel()


def test_reason_ru_is_the_funnel_s():
    f = fn()
    assert set(f.REASONS_RU) == set(f.FUNNEL_CODES), "the factory's own check (test_funnel)"
    for code, line in f.REASONS_RU.items():
        assert factory.reason_ru(code) == line, code
    for old, new in f.LEGACY_CODES.items():
        assert factory.reason_ru(old) == f.REASONS_RU[new], old
    for bad in ("never_a_code", "", None, 7, ["no_fact"]):
        assert factory.reason_ru(bad) is None, bad
    assert factory.reasons_ru(["no_fact", "never_a_code", None, ""]) == \
        {"no_fact": f.REASONS_RU["no_fact"], "never_a_code": None}


def test_with_reason_ru_walks_and_never_writes():
    doc = {"a": {"reason_code": "no_fact", "x": [{"reason_code": "qc_failed"},
                                                  {"reason_code": None}, "s"]},
           "own": {"reason_code": "no_fact", "reason_ru": "своё"},
           "n": {"reason_code": 5}, "plain": {"k": 1}}
    keep = copy.deepcopy(doc)
    got = factory.with_reason_ru(doc)
    assert doc == keep, "the input is never written"
    ru = fn().REASONS_RU
    assert got["a"]["reason_ru"] == ru["no_fact"], got
    assert [r.get("reason_ru") for r in got["a"]["x"][:2]] == [ru["qc_failed"], None], got
    assert got["a"]["x"][2] == "s" and got["own"]["reason_ru"] == "своё", got
    assert got["n"]["reason_ru"] is None and "reason_ru" not in got["plain"], got


def _batch(root, codes):
    d = root / "pipeline" / CH / B
    _w(d / "01-trend-hunter.json", {
        "generated_at": "2026-10-14T09:00:00Z", "language": "en", "topics": [],
        "skipped_topics": [{"topic_id": f"t-{i}", "title": f"T{i}", "kind": "work",
                            "reason_code": c, "reason": f"english {c}", "stage": "trend-hunter"}
                           for i, c in enumerate(codes)]})
    return d


def test_the_batch_topics_say_every_code_by_the_factory_s_words():
    f = fn()
    codes = [c for c in f.REASONS_RU if c != "below_shortlist"] + ["never_a_code"]
    root = factory_tree()
    _batch(root, codes + ["below_shortlist"])
    c = client(root)
    got = c.get(f"/api/batches/{CH}/{B}/topics").json()
    rows = {r["reason_code"]: r for r in got["skipped"]}
    assert set(rows) == set(codes) | {"below_shortlist"}, sorted(rows)
    for code in codes[:-1]:
        r = rows[code]
        assert r["reason_ru"] == f.REASONS_RU[code], (code, r)
        assert r["state"]["reason_ru"] == f.REASONS_RU[code], (code, r)
        assert r["state"]["line"] == f"отсеяна: {f.REASONS_RU[code]}", (code, r)
        assert r["reason"] == f"english {code}", r            # the record stays as written
    unk = rows["never_a_code"]
    assert unk["reason_ru"] is None and unk["state"]["reason_ru"] is None, unk
    assert unk["state"]["line"] == "отсеяна: never_a_code", unk
    bs = rows["below_shortlist"]
    assert bs["state"]["line"] == "не вошла в шорт-лист", bs
    assert bs["reason_ru"] == f.REASONS_RU["below_shortlist"], bs
    one = c.get(f"/api/batches/{CH}/{B}/topics/t-0").json()
    assert one["skipped"]["reason_ru"] == f.REASONS_RU[codes[0]], one["skipped"]


def test_topics_keeps_no_table_of_its_own():
    src = (ROOT / "api" / "topics.py").read_text(encoding="utf-8")
    assert "REASON_RU" not in src
    codes = set(fn().FUNNEL_CODES) | set(fn().LEGACY_CODES)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):          # a code -> a Russian string constant
            worded = {k.value for k, v in zip(node.keys, node.values)
                      if isinstance(k, ast.Constant) and k.value in codes
                      and isinstance(v, ast.Constant) and isinstance(v.value, str)
                      and any("а" <= ch.lower() <= "я" for ch in v.value)}
            assert not worded, sorted(worded)


def test_the_footage_row_s_reason_ru_is_the_factory_s_reason():
    r = footage._row({"topic_id": "t", "state": "refused", "reason_code": "no_source",
                      "reason": fn().reason_ru("no_source")})
    assert r["reason_ru"] == r["reason"] == fn().REASONS_RU["no_source"], r
    r = footage._row({"topic_id": "t", "state": "collecting", "reason_code": None,
                      "reason": None})
    assert r["reason_ru"] is None, r


def test_the_run_summary_funnel_in_russian():
    root = factory_tree()
    (root / "pipeline" / CH / B).mkdir(parents=True)
    data = {"header": {"batch": B},
            "funnel": {"losses": {"no_fact": 2, "never_a_code": 1},
                       "unknown_codes": ["never_a_code"],
                       "steps": [{"step": "selected",
                                  "lost": [{"item": "t-1", "reason_code": "qc_failed",
                                            "reason": "qc"}],
                                  "reserve": [{"item": "t-2", "reason_code": "reserve_unused"}]}]}}
    kept = copy.deepcopy(data)
    orig = run_summary._data
    run_summary._data = lambda d: (data, None, None, "2026-10-14T09:00:00Z", True)
    try:
        got = run_summary.summary(root, CH, B)
    finally:
        run_summary._data = orig
    ru = fn().REASONS_RU
    assert data == kept, "the kept data is never written"
    assert got["funnel_reasons_ru"] == {"no_fact": ru["no_fact"], "never_a_code": None,
                                        "qc_failed": ru["qc_failed"],
                                        "reserve_unused": ru["reserve_unused"]}, got
    step = got["data"]["funnel"]["steps"][0]
    assert step["lost"][0]["reason_ru"] == ru["qc_failed"], step
    assert step["reserve"][0]["reason_ru"] == ru["reserve_unused"], step
    run_summary._data = lambda d: (None, "ещё нет", None, None, False)
    try:
        got = run_summary.summary(root, CH, B)
    finally:
        run_summary._data = orig
    assert got["funnel_reasons_ru"] == {} and got["data"] is None, got


def test_the_footage_wanted_reasons_in_russian():
    class FW:
        REASONS = {"anchor_short": "монтаж: кадров якоря хватило не на весь блок",
                   "no_second_source": "все блоки из одного источника"}
    rep = {"by_reason": {"no_second_source": 2, "anchor_short": 1},
           "rows": [{"reasons": {"anchor_short": 1, "never_a_code": 3}}, {"reasons": None}, "x"]}
    got = analytics._wanted_ru(FW, rep)
    assert got == {"no_second_source": fn().REASONS_RU["no_second_source"],   # the funnel's first
                   "anchor_short": FW.REASONS["anchor_short"],                # else its own
                   "never_a_code": None}, got
    assert analytics._wanted_ru(object(), {"by_reason": None, "rows": None}) == {}
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    assert "reasons_ru" in sch["FootageWanted"]["properties"]
    assert "funnel_reasons_ru" in sch["BatchRunSummary"]["properties"]
    for name, props in ((n, s.get("properties", {})) for n, s in sch.items()):
        if "reason_code" in props and name not in ("AcceptIn", "VideoAcceptance"):
            assert "reason_ru" in props, name     # the acceptance's own dictionary (CF-0319)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, f in tests:
        try:
            f()
            print(f"PASS {name}")
        except Exception as e:                       # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

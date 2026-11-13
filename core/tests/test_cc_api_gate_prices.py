#!/usr/bin/env python3
"""CC-0100: what a refusal costs, read only (`scripts/runlog gate-price
[--rule]... [--window] [--before] --json`) - `GET /api/gate-prices`
(`api/gate_prices.py` over `shared/runlog/gate_price.py`).

In-process (the TestClient) against a stand-in factory root in a temp dir:
two batches under its `pipeline/reel/` in the shapes the funnel reads (two
ready videos), its own `shared/gate-prices.json`, and a stand-in rule put into
the factory's registry for the test (it refuses one script, always with a
basis). Nothing outside the temp dir is read for the prices and nothing at all
is written.

What is pinned:

* the contract: the route, GET only, version 0.48.0, `GatePriceProblem` on
  the problems, the answer's shape; the module never names the factory's
  writers (`write_ledger`, `write_stats`, `main`) nor a write of its own;
* the price: the stand-in rule kills one of the two ready videos - price 1,
  `warn`, the killed slug, its headline and the code's mode; a signature in
  the ledger at that price turns it into `enforce`, the decision is read; the
  ledger's row with a decision and no replay is `unregistered`, a proposal is
  in `proposals`; `signing` says it is available (CC-0114, CF-0721) and
  each rule's `actions` what the buttons may do; nothing written;
* the cache: the same window again is `cached`; a ledger changed since is
  priced afresh;
* every registered rule over the stand-in window answers (no basis is an
  answer); no absolute path leaves;
* refusals: an unknown rule 404 `unknown_rule`, a `before` that is neither a
  day nor a batch 422 `bad_before`.
"""
import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("RUNLOG_POOL", None)

from test_cc_api_batches import _w, client, factory_tree                    # noqa: E402

import api                                                                   # noqa: E402
from api import factory, gate_prices                                         # noqa: E402

URL = "/api/gate-prices"
B1, B2 = "2026-10-01T1000Z", "2026-10-02T1000Z"
TEST_RULE = "test.cc_kills_s2"
FORBIDDEN = {"write_ledger", "write_stats", "main", "write_text", "write_bytes", "open",
             "unlink", "rename", "rmtree", "mkdir", "subprocess"}


def gp():
    return factory.gate_price()


class stand_in_rule:
    """A rule in the factory's registry for the block: a basis on every
    batch, refusing exactly `s2`."""

    def __enter__(self):
        g = gp()
        g.RULES[TEST_RULE] = g.Rule(TEST_RULE, g.WHAT_VIDEO,
                                    lambda A: g.basis("a stand-in rule", {"s2": "because"}),
                                    note="CC-0100 stand-in", mode="warn")
        return self

    def __exit__(self, *exc):
        gp().RULES.pop(TEST_RULE, None)


def batch(root, bid):
    d = root / "pipeline" / "reel" / bid
    scripts = {"t1": ["s1"], "t2": ["s2"]}
    docs = {
        "01-trend-hunter.json": {"batch_id": bid, "topics": [{"topic_id": t} for t in scripts]},
        "02-compliance-checker.json": {"batch_id": bid, "results": [
            {"topic_id": t, "verdict": "clear"} for t in scripts]},
        "01b-footage-index.json": {"batch": bid, "fetched": [], "skipped_topics": [],
                                   "failed": [], "sources_by_topic": {
                                       t: [f"{t}-a", f"{t}-b"] for t in scripts}},
        "03-content-researcher.json": {"batch_id": bid, "skipped": [], "scripts": [
            {"script_id": s, "topic_id": t} for t, ss in scripts.items() for s in ss]},
        "04-compliance-checker.json": {"batch_id": bid, "results": [
            {"script_id": s, "verdict": "clear"} for ss in scripts.values() for s in ss]},
        "05-video-editor.json": {"batch_id": bid, "refusals": [], "videos": [
            {"script_id": s, "output_path": f"/x/{s}.mp4", "qc": {"passed": True}}
            for ss in scripts.values() for s in ss]},
    }
    for name, doc in docs.items():
        _w(d / name, doc)
    return d


def ledger(root, signed_at=None):
    rules = {TEST_RULE: {"what": "video", "signature": None},
             "by_hand.rule": {"what": "video", "note": "priced by hand",
                              "measured": {"at": "2026-09-23T0330Z", "why": "1 of 2"},
                              "signature": None,
                              "decision": {"user": "u", "date": "2026-09-23", "mode": "warn",
                                           "task": "CF-0330", "note": "a warning"}}}
    if signed_at is not None:
        rules[TEST_RULE]["signature"] = {"user": "u", "date": "2026-10-03",
                                         "price": signed_at, "note": "ok"}
    _w(root / "shared" / "gate-prices.json", {
        "note": "stand-in", "rules": rules,
        "proposals": {"rows": {"score.p": {"proposed": {"price": 2, "per": "block"},
                                           "measured": {"accepted_lose": 0,
                                                        "rejected_lose": 1},
                                           "mode_until_signed": "warn", "task": "CF-0472"}}}})


def world():
    root = factory_tree()
    batch(root, B1)
    batch(root, B2)
    ledger(root)
    return root


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def get(c, **params):
    r = c.get(URL, params=params)
    return r.status_code, r.json()


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_route():
    root = world()
    spec = client(root).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    assert set(spec["paths"][URL]) == {"get"}, spec["paths"][URL]
    for code in ("404", "422", "500"):
        ref = spec["paths"][URL]["get"]["responses"][code]["content"]["application/json"]
        assert ref["schema"]["$ref"].endswith("/GatePriceProblem"), ref
    props = spec["components"]["schemas"]["GatePrices"]["properties"]
    assert {"rules", "asked", "window", "before", "results", "all_land", "unregistered",
            "proposals", "signing", "ledger", "pool", "cached", "computed_at"} <= set(props)
    res = spec["components"]["schemas"]["GatePriceResult"]["properties"]
    assert {"rule", "what", "batches", "ready", "price", "verdict", "why", "signature",
            "decision", "headline", "mode"} <= set(res)
    assert gate_prices.WINDOW == gp().WINDOW


def test_the_module_never_writes():
    tree = ast.parse((ROOT / "api" / "gate_prices.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & FORBIDDEN, names & FORBIDDEN
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
               and isinstance(n.value, str)}
    assert "--write" not in strings


# --------------------------------------------------------------------- the price
def test_the_price_of_a_rule_over_the_window_nothing_written():
    root = world()
    c = client(root)
    before = files(root)
    with stand_in_rule():
        s, d = get(c, rule=TEST_RULE)
    assert s == 200, d
    assert d["asked"] == [TEST_RULE] and TEST_RULE in d["rules"], d
    assert (d["window"], d["window_default"], d["before"]) == (5, 5, None), d
    assert (d["pool"], d["ledger"], d["ledger_exists"]) == \
        ("pipeline", "shared/gate-prices.json", True), d
    [r] = d["results"]
    assert r["rule"] == TEST_RULE and r["what"] == "video" and r["mode"] == "warn", r
    assert r["window"] == [f"reel/{B1}", f"reel/{B2}"], r["window"]
    assert (r["ready"], r["price"], r["measured_on"], r["of"]) == (4, 2, 2, 2), r
    assert r["verdict"] == "warn" and r["signature"] is None, r
    assert [k["slug"] for k in r["batches"][0]["killed"]] == ["s2"], r["batches"][0]
    assert r["batches"][0]["ready"] == ["s1", "s2"], r["batches"][0]
    assert r["headline"].startswith(f"GATE PRICE: {TEST_RULE} - 2 of 4"), r["headline"]
    assert d["all_land"] is False, d
    assert [{k: v for k, v in u.items() if k != "actions"} for u in d["unregistered"]] == [{
        "rule": "by_hand.rule", "note": "priced by hand",
        "measured": {"at": "2026-09-23T0330Z", "why": "1 of 2"}, "signature": None,
        "decision": {"user": "u", "date": "2026-09-23", "mode": "warn", "task": "CF-0330",
                     "note": "a warning"}}], d["unregistered"]
    [pr] = d["proposals"]
    assert pr["rule"] == "score.p" and pr["mode_until_signed"] == "warn", pr
    assert pr["line"].startswith("score.p (CF-0472): -2 per block"), pr
    # CC-0114: the factory signs now (CF-0721) - the routes are in test_cc_api_gate_sign.py
    assert d["signing"]["available"] is True and d["signing"]["task"] == "CF-0721", d["signing"]
    assert "sign" in d["signing"]["factory_function"], d["signing"]
    assert r["actions"]["in_ledger"] is True and r["actions"]["sign"] is False, r["actions"]
    assert r["actions"]["sign_refusal"]["code"] == "not_measured", r["actions"]
    assert d["unregistered"][0]["actions"]["decide"] is True, d["unregistered"]
    assert d["ledger_sha256"], d
    assert d["cached"] is False and d["computed_at"], d
    assert str(root) not in json.dumps(d, ensure_ascii=False)
    assert files(root) == before


def test_the_same_window_is_kept_a_changed_ledger_is_priced_again():
    root = world()
    c = client(root)
    with stand_in_rule():
        s, first = get(c, rule=TEST_RULE)
        assert s == 200 and first["cached"] is False, first
        s, again = get(c, rule=TEST_RULE)
        assert s == 200 and again["cached"] is True, again
        assert again["results"] == first["results"]
        ledger(root, signed_at=2)
        st = (root / "shared" / "gate-prices.json").stat()
        os.utime(root / "shared" / "gate-prices.json", ns=(st.st_atime_ns,
                                                             st.st_mtime_ns + 10 ** 9))
        s, signed = get(c, rule=TEST_RULE)
    assert s == 200 and signed["cached"] is False, signed
    [r] = signed["results"]
    assert r["verdict"] == "enforce" and r["signature"]["price"] == 2, r
    assert signed["all_land"] is True, signed


def test_a_window_and_before_narrow_it():
    root = world()
    c = client(root)
    with stand_in_rule():
        s, d = get(c, rule=TEST_RULE, window=1)
        assert s == 200 and d["results"][0]["window"] == [f"reel/{B2}"], d
        s, d = get(c, rule=TEST_RULE, before="2026-10-02")
        assert s == 200 and d["results"][0]["window"] == [f"reel/{B1}"], d
        s, d = get(c, rule=TEST_RULE, before=B1)
    assert s == 200 and d["results"][0]["window"] == [] and \
        d["results"][0]["price"] is None, d


def test_every_registered_rule_answers_over_the_stand_in_window():
    root = world()
    c = client(root)
    before = files(root)
    s, d = get(c)
    assert s == 200, d
    assert d["asked"] == sorted(gp().RULES) == d["rules"], d
    assert {r["rule"] for r in d["results"]} == set(d["rules"]), d
    assert all(r["verdict"] in ("enforce", "warn", "penalty") for r in d["results"]), d
    assert isinstance(d["all_land"], bool)
    assert str(root) not in json.dumps(d, ensure_ascii=False)
    assert files(root) == before


# --------------------------------------------------------------------- refusals
def test_an_unknown_rule_or_a_bad_before_is_refused():
    root = world()
    c = client(root)
    s, d = get(c, rule="no.such.rule")
    assert s == 404 and d["code"] == "unknown_rule", d
    assert set(d) == {"message", "code", "details"} and "no.such.rule" in d["message"], d
    s, d = get(c, before="вчера")
    assert s == 422 and d["code"] == "bad_before", d
    assert set(d) == {"message", "code", "details"}, d
    s, d = get(c, window=0)
    assert s == 422, d


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

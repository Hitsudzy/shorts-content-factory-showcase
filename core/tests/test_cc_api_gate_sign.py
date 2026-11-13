#!/usr/bin/env python3
"""CC-0114 (the factory's CF-0721): the user's signature under a gate's price
and decision on its mode from the center - `POST /api/gate-prices/{rule}/sign
/plan` -> `.../sign {confirm}`, `.../decide/plan` -> `.../decide {confirm}`
(`api/gate_prices.py` over `shared/runlog/gate_price.py` sign / decide).

In-process (the TestClient) against a stand-in factory root in a temp dir
(`test_cc_api_batches.factory_tree`, a git repository): its own
`shared/gate-prices.json` with a measured rule, a hand-priced one, a signed
one and a score-model row, committed. The open batches are handed in
(`gate_prices.FACTORY_KW["open_rows"]`) - nothing of the live factory is
read or written.

What is pinned:

* the read: `signing.available` true, `ledger_sha256` the file's, each
  rule's `actions` (sign / decide, the refusal's code and Russian message);
* the plan is the factory's dry run (by user via center) - nothing written -
  with a token only when ok; the confirm writes the block and the factory
  commits exactly the ledger; the token is single use and of its own kind;
* refusals: below_measured, not_measured, already_signed, not_signable,
  bad_mode, bad_task, empty_note - in the plan, no token, a Russian `why`;
  batch_open («батчи читают shared/») and check_changed in the plan and again
  at the confirm (409, nothing written);
* the contract: the four routes, guarded writes, the problem's codes.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("RUNLOG_POOL", None)

from test_cc_api_batches import H, _w, client, factory_tree, git              # noqa: E402

from api import gate_prices                                                   # noqa: E402

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
LEDGER = ("shared", "gate-prices.json")
MEASURED, HAND, SIGNED, SCORE = "m.rule", "hand.rule", "signed.rule", "score.rule"


def _measured(price):
    return {"at": "2026-10-10T1000Z", "window": [], "ready": 4, "price": price,
            "measured_on": 2, "of": 2, "verdict": "warn", "why": "stand-in"}


def world():
    root = factory_tree()
    _w(root.joinpath(*LEDGER), {"note": "stand-in", "rules": {
        MEASURED: {"what": "video", "measured": _measured(2), "signature": None},
        HAND: {"what": "video", "note": "priced by hand", "signature": None},
        SIGNED: {"what": "video", "measured": _measured(1),
                 "signature": {"user": "u", "date": "2026-10-01", "price": 3, "note": "ok"}},
        SCORE: {"what": "video", "mode": "hard", "measured": _measured(0), "signature": None},
    }})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the ledger")
    gate_prices.FACTORY_KW.clear()
    gate_prices.FACTORY_KW.update({"now": NOW, "open_rows": []})
    return root


def ledger(root):
    return json.loads(root.joinpath(*LEDGER).read_text(encoding="utf-8"))


def sha(root):
    return hashlib.sha256(root.joinpath(*LEDGER).read_bytes()).hexdigest()


def post(c, path, body):
    r = c.post(path, headers=H, json=body)
    return r.status_code, r.json()


def sign_plan(c, rule=MEASURED, price=2, note="подписываю", **kw):
    return post(c, f"/api/gate-prices/{rule}/sign/plan", dict(price=price, note=note, **kw))


def decide_plan(c, rule=HAND, mode="warn", task="CF-0330", note="пусть предупреждает", **kw):
    return post(c, f"/api/gate-prices/{rule}/decide/plan",
                dict(mode=mode, task=task, note=note, **kw))


# --------------------------------------------------------------------- the read
def test_the_read_says_what_each_rule_can_do_now():
    root = world()
    c = client(root)
    r = c.get("/api/gate-prices")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["signing"]["available"] is True and d["signing"]["task"] == "CF-0721", d["signing"]
    assert "батч" in d["signing"]["what"], d["signing"]
    assert d["ledger_sha256"] == sha(root), d["ledger_sha256"]
    rows = gate_prices.factory.gate_price().read_ledger(root.joinpath(*LEDGER))
    gp = gate_prices.factory.gate_price()
    a = gate_prices.actions(gp, MEASURED, rows)
    assert (a["in_ledger"], a["measured_price"], a["signable"], a["sign"], a["decide"]) == \
        (True, 2, True, True, True) and a["sign_refusal"] is None, a
    a = gate_prices.actions(gp, HAND, rows)
    assert (a["sign"], a["decide"], a["sign_refusal"]["code"]) == (False, True, "not_measured"), a
    a = gate_prices.actions(gp, SIGNED, rows)
    assert (a["sign"], a["decide"]) == (False, False), a
    assert a["sign_refusal"]["code"] == a["decide_refusal"]["code"] == "already_signed", a
    a = gate_prices.actions(gp, SCORE, rows)
    assert (a["signable"], a["sign_refusal"]["code"]) == (False, "not_signable"), a
    a = gate_prices.actions(gp, "no.rule", rows)
    assert (a["in_ledger"], a["sign_refusal"]["code"]) == (False, "no_such_rule"), a
    assert a["sign_refusal"]["message"] == gate_prices.REFUSALS["no_such_rule"][1]
    # every result of the read carries its actions
    assert all("actions" in res for res in d["results"]), d["results"][0]


# --------------------------------------------------------------------- sign
def test_sign_plan_is_a_dry_run_and_the_confirm_commits_the_ledger():
    root = world()
    c = client(root)
    before, head = root.joinpath(*LEDGER).read_bytes(), git(root, "rev-parse", "HEAD")
    s, plan = sign_plan(c, base_sha256=sha(root))
    assert s == 200 and plan["ok"] is True and plan["dry_run"] is True, plan
    assert (plan["action"], plan["kind"], plan["rule"], plan["key"], plan["task"]) == \
        ("gate_price_sign", "sign", MEASURED, "signature", "CF-0721"), plan
    assert (plan["by"], plan["via"], plan["path"]) == ("user", "center",
                                                      "shared/gate-prices.json"), plan
    assert plan["block"] == {"user": "user", "date": "2026-10-13", "price": 2,
                             "note": "подписываю", "via": "center"}, plan["block"]
    assert plan["confirm"] and plan["expires_in_s"] == 120 and plan["why"] is None, plan
    assert plan["base_sha256"] == plan["sha256"] == sha(root) != plan["new_sha256"], plan
    assert root.joinpath(*LEDGER).read_bytes() == before
    assert git(root, "rev-parse", "HEAD") == head
    s, res = post(c, f"/api/gate-prices/{MEASURED}/sign", {"confirm": plan["confirm"]})
    assert s == 200 and res["ok"] is True and res["written"] is True, res
    assert res["dry_run"] is False and res["sha256"] == res["new_sha256"] == sha(root), res
    assert ledger(root)["rules"][MEASURED]["signature"] == plan["block"]
    assert res["commit"] and git(root, "rev-parse", "HEAD") == res["commit"] != head
    assert git(root, "show", "--name-only", "--format=", "HEAD").split() == \
        ["shared/gate-prices.json"]
    assert git(root, "status", "--porcelain") == ""
    assert str(root) not in json.dumps(res, ensure_ascii=False)
    # the token is spent
    s, d = post(c, f"/api/gate-prices/{MEASURED}/sign", {"confirm": plan["confirm"]})
    assert s == 409 and d["code"] == "confirm_unknown", d
    # the rule is signed now: a second signature is refused in the plan
    s, plan = sign_plan(c)
    assert s == 200 and plan["ok"] is False and plan["confirm"] is None, plan
    assert [r["code"] for r in plan["refusals"]] == ["already_signed"], plan
    assert plan["why"] == gate_prices.REFUSALS["already_signed"][1], plan


def test_decide_plan_and_confirm_write_the_decision():
    root = world()
    c = client(root)
    s, plan = decide_plan(c)
    assert s == 200 and plan["ok"] is True and plan["key"] == "decision", plan
    assert plan["block"] == {"user": "user", "date": "2026-10-13", "mode": "warn",
                             "task": "CF-0330", "note": "пусть предупреждает",
                             "via": "center"}, plan["block"]
    # a sign token is not a decide's
    s, other = sign_plan(c)
    s, d = post(c, f"/api/gate-prices/{HAND}/decide", {"confirm": other["confirm"]})
    assert s == 409 and d["code"] == "confirm_mismatch", d
    s, res = post(c, f"/api/gate-prices/{HAND}/decide", {"confirm": plan["confirm"]})
    assert s == 200 and res["written"] is True and res["commit"], res
    assert ledger(root)["rules"][HAND]["decision"] == plan["block"]
    assert git(root, "status", "--porcelain") == ""


def test_the_factorys_refusals_in_the_plan_carry_russian_and_no_token():
    root = world()
    c = client(root)
    before = root.joinpath(*LEDGER).read_bytes()
    cases = [
        (sign_plan(c, price=1), "below_measured"),
        (sign_plan(c, rule=HAND), "not_measured"),
        (sign_plan(c, rule=SIGNED, price=5), "already_signed"),
        (sign_plan(c, rule=SCORE, price=0), "not_signable"),
        (sign_plan(c, price=-1), "bad_price"),
        (sign_plan(c, note="  "), "empty_note"),
        (sign_plan(c, rule="no.rule"), "no_such_rule"),
        (decide_plan(c, mode="enforce"), "bad_mode"),
        (decide_plan(c, task="later"), "bad_task"),
        (decide_plan(c, rule=SIGNED), "already_signed"),
        (sign_plan(c, base_sha256="0" * 64), "check_changed"),
    ]
    for (s, plan), code in cases:
        assert s == 200 and plan["ok"] is False and plan["confirm"] is None, (code, plan)
        codes = [r["code"] for r in plan["refusals"]]
        assert code in codes, (code, codes)
        for r in plan["refusals"]:
            assert r["message"] == gate_prices.REFUSALS[r["code"]][1] and r["line"], r
        assert plan["why"] in {gate_prices.REFUSALS[k][1] for k in codes}, plan
    assert root.joinpath(*LEDGER).read_bytes() == before
    assert set(gate_prices.REFUSALS) == set(gate_prices.factory.gate_price().SIGN_REFUSALS)
    # a price that is not a whole number is the route's own 422
    s, d = sign_plan(c, price=2.5)
    assert s == 422, d


def test_an_open_batch_refuses_the_plan_and_the_confirm():
    root = world()
    c = client(root)
    batch = (str(root / "pipeline" / "reel" / "2026-10-13T1000Z"), NOW, True)
    gate_prices.FACTORY_KW["open_rows"] = [batch]
    s, plan = sign_plan(c)
    assert s == 200 and plan["ok"] is False and plan["confirm"] is None, plan
    assert [r["code"] for r in plan["refusals"]] == ["batch_open"], plan
    assert "батчи читают shared/" in plan["why"], plan
    gate_prices.FACTORY_KW["open_rows"] = []
    s, plan = sign_plan(c)
    assert s == 200 and plan["confirm"], plan
    gate_prices.FACTORY_KW["open_rows"] = [batch]
    before, head = root.joinpath(*LEDGER).read_bytes(), git(root, "rev-parse", "HEAD")
    s, d = post(c, f"/api/gate-prices/{MEASURED}/sign", {"confirm": plan["confirm"]})
    assert s == 409 and d["code"] == "batch_open", d
    assert set(d) == {"message", "code", "details"} and "батчи читают shared/" in d["message"]
    assert root.joinpath(*LEDGER).read_bytes() == before
    assert git(root, "rev-parse", "HEAD") == head
    assert str(root) not in json.dumps(d, ensure_ascii=False)


def test_a_ledger_changed_since_the_plan_is_check_changed():
    root = world()
    c = client(root)
    s, plan = sign_plan(c)
    assert s == 200 and plan["confirm"], plan
    doc = ledger(root)
    doc["rules"][HAND]["note"] = "moved"
    _w(root.joinpath(*LEDGER), doc)
    changed = root.joinpath(*LEDGER).read_bytes()
    s, d = post(c, f"/api/gate-prices/{MEASURED}/sign", {"confirm": plan["confirm"]})
    assert s == 409 and d["code"] == "check_changed", d
    assert "откройте заново" in d["message"], d
    assert root.joinpath(*LEDGER).read_bytes() == changed


# --------------------------------------------------------------------- the contract
def test_the_routes_are_guarded_writes_in_the_contract():
    from test_cc_api_writes import GUARDED
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    for kind in ("sign", "decide"):
        for path, model in ((f"/api/gate-prices/{{rule}}/{kind}/plan", "GateWritePlan"),
                            (f"/api/gate-prices/{{rule}}/{kind}", "GateWriteResult")):
            assert ("POST", path) in GUARDED, path
            op = spec["paths"][path]["post"]["responses"]
            assert op["200"]["content"]["application/json"]["schema"]["$ref"].endswith(model)
            assert "/GatePriceProblemW" in json.dumps(op["409"]), (path, op["409"])
    codes = set(spec["components"]["schemas"]["GatePriceProblemW"]["properties"]["code"]["enum"])
    assert set(gate_prices.REFUSALS) | {"busy", "confirm_unknown", "confirm_expired",
                                        "confirm_mismatch", "factory_broken"} == codes, codes
    props = spec["components"]["schemas"]["GatePrices"]["properties"]
    assert "ledger_sha256" in props
    assert "actions" in spec["components"]["schemas"]["GatePriceResult"]["properties"]
    assert spec["components"]["schemas"]["GateSigning"]["properties"]["available"]["type"] == \
        "boolean"


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

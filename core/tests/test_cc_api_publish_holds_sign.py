#!/usr/bin/env python3
"""CC-0070: the center signs a content-sensitivity publication hold on the
user's behalf (the user's decision of 11.10) - two steps, as the publication
writes of `api/publish.py` (CC-0065):

    POST /api/publish/{c}/holds/{batch_id}/{topic_id}/sign/plan  {note}
        publication_hold.check_sign - nothing written, a confirm token
    POST /api/publish/{c}/holds/{batch_id}/{topic_id}/sign       {confirm}
        check_sign again, then sign_hold(user, note, via="center")

and `GET /api/publish/holds` carries `signable` / `sign_refusal` per row
(`check_sign`).

In-process (starlette's TestClient) against stand-in factory roots in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`): the ledger is the temp
root's `publish/publication-holds.json`, written here; no network, nothing
outside the temp dir.

What is pinned: the plan writes nothing and says the hold, what
compliance-checker recorded and what a signature means; the confirm writes
`signature {user, date, note, via: center}` and the hold leaves `open`; each
factory refusal reaches the client with its code and its Russian line
verbatim; an empty note is the factory's `empty_note`; tokens unknown,
expired, of another hold or another action are refused and nothing is
written; a ledger that moved between plan and confirm is `check_changed`, a
hold signed meanwhile is `already_signed`; a read-only copy refuses both
routes before any factory call.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import TMP, H, _w, client, factory_tree, git    # noqa: E402
from test_cc_api_publish import BATCH, NOW, files, setup                 # noqa: E402

from api import batches, factory, publish                                 # noqa: E402

NOTE = "посмотрел ролик целиком - сцена нейтральная, публиковать можно"
SENS = {"flagged": True, "notes": "Scene shows a staged car crash - check before publishing."}
RIGHTS = {"matched": True, "risk_level": "high", "reason": "matches Zenith Studios / Example Animation"}


def ph():
    return factory.publication_hold()


def post(c, path, body=None):
    r = c.post(path, headers=H, json=body if body is not None else {})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def row(topic, channel="reel", **kw):
    return dict({"hold_id": f"{channel}/{BATCH}/{topic}", "channel": channel,
                 "batch_id": BATCH, "topic_id": topic, "script_id": f"{topic}-script1",
                 "verdict": "review", "stage_checked": "03-content-researcher",
                 "reason_code": "compliance_review_hold",
                 "reason": "Compliance verdict 'review' on content-sensitivity flag.",
                 "content_sensitivity_check": SENS, "rights_holder_check": None,
                 "resolved_at": None, "resolved_reason": None, "signature": None}, **kw)


def ledger_path(root):
    return root / "publish" / "publication-holds.json"


def ledger(root):
    return json.loads(ledger_path(root).read_text(encoding="utf-8"))["holds"]


def world():
    root = factory_tree()
    _w(ledger_path(root), {"note": "test", "task": "CF-0318", "holds": [
        row("t-open"), row("t-two"),
        row("t-signed", signature={"user": "user", "date": "2026-10-03", "note": "ok"}),
        row("t-done", resolved_at="2026-10-02T00:00:00Z", resolved_reason="снят"),
        row("t-rights", content_sensitivity_check={"flagged": False}, rights_holder_check=RIGHTS),
        row("t-other", channel="demo")]})
    return root


def base(topic, channel="reel"):
    return f"/api/publish/{channel}/holds/{BATCH}/{topic}/sign"


def refusal_text(code, **values):
    return ph().SIGN_REFUSALS_RU[code].format_map(values)


# --------------------------------------------------------------------- plan -> confirm
def test_plan_then_confirm_signs_via_the_center():
    setup()
    root = world()
    c = client(root)
    before = files(root)
    code, plan = post(c, f"{base('t-open')}/plan", {"note": f"  {NOTE}  "})
    assert code == 200, plan
    assert (plan["action"], plan["channel"], plan["ok"], plan["hold_id"]) == \
        ("hold_sign", "reel", True, f"reel/{BATCH}/t-open"), plan
    assert plan["confirm"] and plan["expires_in_s"] == int(batches.CONFIRM_TTL), plan
    assert (plan["batch_id"], plan["topic_id"], plan["script_id"], plan["verdict"]) == \
        (BATCH, "t-open", "t-open-script1", "review"), plan
    assert plan["content_sensitivity_check"] == SENS and plan["hold"]["topic_id"] == "t-open"
    assert any("Чувствительность содержания: отмечена" in s and SENS["notes"] in s
               for s in plan["flagged"]), plan["flagged"]
    assert plan["meaning"] == publish.SIGN_MEANING and "посмотрели ролик" in plan["meaning"]
    assert plan["note"] == NOTE, plan
    assert plan["signature"] == {"user": "user", "note": NOTE, "via": "center"}, plan
    assert plan["ledger"] == "publish/publication-holds.json", plan
    assert plan["ledger_fingerprint"] == ph().check_sign(ledger_path(root),
                                                         f"reel/{BATCH}/t-open")["fingerprint"]
    assert files(root) == before, "a plan writes nothing"

    code, done = post(c, base("t-open"), {"confirm": plan["confirm"]})
    assert code == 200, done
    sig = {"user": "user", "date": NOW, "note": NOTE, "via": "center"}
    assert done["action"] == "hold_sign" and done["hold_id"] == f"reel/{BATCH}/t-open", done
    assert done["row"]["signature"] == sig, done
    stored = {r["topic_id"]: r for r in ledger(root)}
    assert stored["t-open"]["signature"] == sig, stored["t-open"]
    assert stored["t-two"]["signature"] is None, "only the one hold is signed"
    held, why = ph().is_held("reel", BATCH, "t-open", root=root)
    assert held is False and "via center" in why, why
    assert "t-open" not in {r["topic_id"] for r in done["holds"]["open"]}, done["holds"]
    # the token is spent
    code, again = post(c, base("t-open"), {"confirm": plan["confirm"]})
    assert code == 409 and again["code"] == "confirm_unknown", again


def test_the_holds_say_which_are_signable():
    setup()
    root = world()
    c = client(root)
    r = c.get("/api/publish/holds", params={"channel": "reel"}, headers=H)
    assert r.status_code == 200, r.text
    h = r.json()
    by = {x["topic_id"]: x for x in h["rows"]}
    assert by["t-open"]["signable"] is True and by["t-open"]["sign_refusal"] is None
    assert by["t-signed"]["signable"] is False and \
        by["t-signed"]["sign_refusal"]["code"] == "already_signed"
    assert by["t-done"]["sign_refusal"]["code"] == "already_resolved"
    assert by["t-rights"]["sign_refusal"]["code"] == "not_signable"
    assert by["t-rights"]["sign_refusal"]["text_ru"] == refusal_text(
        "not_signable", hold_id=f"reel/{BATCH}/t-rights")
    assert {x["topic_id"]: x["signable"] for x in h["open"]} == \
        {"t-open": True, "t-two": True, "t-rights": False}, h["open"]


# --------------------------------------------------------------------- the factory's refusals
def test_each_refusal_is_the_factory_s_code_and_line():
    setup()
    root = world()
    c = client(root)
    before = files(root)
    cases = {
        "t-none": (404, "no_such_hold", {"hold_id": f"reel/{BATCH}/t-none"}),
        "t-signed": (409, "already_signed", {"hold_id": f"reel/{BATCH}/t-signed",
                                             "user": "user", "date": "2026-10-03"}),
        "t-done": (409, "already_resolved", {"hold_id": f"reel/{BATCH}/t-done",
                                             "why": "снят 2026-10-02T00:00:00Z"}),
        "t-rights": (409, "not_signable", {"hold_id": f"reel/{BATCH}/t-rights"}),
    }
    for topic, (status, code_, values) in cases.items():
        code, r = post(c, f"{base(topic)}/plan", {"note": NOTE})
        assert code == status and r["code"] == code_, (topic, r)
        assert r["message"] == refusal_text(code_, **values), (topic, r)
        assert r["details"] and "HoldSignError" in r["details"][0], r
    # an empty note - the factory's own line
    for note in ("", "   "):
        code, r = post(c, f"{base('t-open')}/plan", {"note": note})
        assert code == 422 and r["code"] == "empty_note", r
        assert r["message"] == refusal_text("empty_note"), r
    # the ledger does not read
    ledger_path(root).write_text("[", encoding="utf-8")
    code, r = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    assert code == 409 and r["code"] == "ledger_unreadable", r
    assert r["message"].startswith("Журнал холдов не читается"), r
    ledger_path(root).unlink()
    code, r = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    assert code == 404 and r["code"] == "no_such_hold", r
    # an unknown channel is the API's own
    code, r = post(c, f"{base('t-open', 'nope')}/plan", {"note": NOTE})
    assert code == 404 and r["code"] == "unknown_channel", r


def test_the_factory_s_refusal_at_the_write_reaches_the_client():
    """`sign_hold`'s own `empty_user` - the center's user stood in by an empty
    one - comes back as the factory says it; nothing written."""
    setup()
    root = world()
    c = client(root)
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    assert code == 200, plan
    before = ledger_path(root).read_bytes()
    saved = publish.WRITE_BY
    publish.WRITE_BY = "  "
    try:
        code, r = post(c, base("t-open"), {"confirm": plan["confirm"]})
    finally:
        publish.WRITE_BY = saved
    assert code == 422 and r["code"] == "empty_user", r
    assert r["message"] == refusal_text("empty_user"), r
    assert ledger_path(root).read_bytes() == before


# --------------------------------------------------------------------- tokens, a changed ledger
def test_tokens_expired_of_another_hold_or_action():
    setup()
    root = world()
    c = client(root)
    before = ledger_path(root).read_bytes()
    code, r = post(c, base("t-open"), {"confirm": "nope"})
    assert code == 409 and r["code"] == "confirm_unknown", r
    # expired
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    real = batches._clock
    batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
    try:
        code, r = post(c, base("t-open"), {"confirm": plan["confirm"]})
    finally:
        batches._clock = real
    assert code == 409 and r["code"] == "confirm_expired", r
    # the plan of one hold presented to another
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    code, r = post(c, base("t-two"), {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    assert "t-open" in r["message"] and "t-two" in r["message"], r
    # of another channel
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    code, r = post(c, base("t-other", "demo"), {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    # a pause's token is not a signature's, and back
    code, pplan = post(c, "/api/publish/reel/pause/set/plan", {"reason": "нарушение"})
    code, r = post(c, base("t-open"), {"confirm": pplan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    code, r = post(c, "/api/publish/reel/pause/set", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    assert "подписи холда канала reel" in r["message"], r
    assert ledger_path(root).read_bytes() == before, "no refused token wrote"


def test_a_ledger_that_moved_is_check_changed_a_hold_signed_meanwhile_already_signed():
    setup()
    root = world()
    c = client(root)
    # another hold signed between plan and confirm: the ledger's bytes moved
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    ph().sign_hold(ledger_path(root), f"reel/{BATCH}/t-two", "user", "из консоли",
                   via="console")
    code, r = post(c, base("t-open"), {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "check_changed", r
    assert {x["topic_id"]: x["signature"] for x in ledger(root)}["t-open"] is None
    # this very hold signed meanwhile: the factory's refusal, not a second signature
    code, plan = post(c, f"{base('t-open')}/plan", {"note": NOTE})
    ph().sign_hold(ledger_path(root), f"reel/{BATCH}/t-open", "user", "из консоли",
                   via="console")
    code, r = post(c, base("t-open"), {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "already_signed", r
    assert r["message"].startswith(f"Холд reel/{BATCH}/t-open уже подписан"), r
    assert {x["topic_id"]: x["signature"] for x in ledger(root)}["t-open"]["via"] == "console"


# --------------------------------------------------------------------- the commit (CC-0153)
def _committed_world():
    """The world with its ledger committed - a clean tree before the signature."""
    root = world()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the holds")
    assert git(root, "status", "--porcelain") == ""
    return root


def _sign(c, topic="t-open"):
    code, plan = post(c, f"{base(topic)}/plan", {"note": NOTE})
    assert code == 200 and plan["confirm"], plan
    return post(c, base(topic), {"confirm": plan["confirm"]})


def test_the_signature_is_committed_and_the_tree_stays_clean():
    """CC-0153 (21.10): the signature wrote the ledger and left it uncommitted -
    the production tree went dirty. Now one commit of exactly the ledger, with
    the `Cc-Channel` / `Cc-Action` trailers, as the other center writes."""
    setup()
    root = _committed_world()
    h = git(root, "rev-parse", "HEAD")
    code, done = _sign(client(root))
    assert code == 200, done
    assert git(root, "status", "--porcelain") == "", "the tree is clean after the signature"
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert git(root, "show", "--name-only", "--format=", "HEAD") == \
        "publish/publication-holds.json"
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith(f"Холд reel/{BATCH}/t-open подписан (user, center)"), msg
    assert f"Заметка: «{NOTE}»" in msg, msg
    assert "Cc-Channel: reel" in msg and "Cc-Action: hold_sign" in msg, msg
    trailers = git(root, "log", "-1", "--format=%(trailers:key=Cc-Action,valueonly)")
    assert trailers == "hold_sign", trailers
    committed = json.loads(git(root, "show", "HEAD:publish/publication-holds.json"))["holds"]
    assert {r["topic_id"]: r["signature"] for r in committed}["t-open"]["via"] == "center"


def test_a_commit_git_refuses_is_refused_and_nothing_stays_staged():
    setup()
    root = _committed_world()
    h = git(root, "rev-parse", "HEAD")
    hooks = TMP / f"refusing-hooks-{root.name}"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))
    code, r = _sign(client(root))
    assert code == 409 and r["code"] == "refused", r
    assert r["message"] == publish.COMMIT_REFUSED.format(done="Холд подписан"), r
    assert "commit_refused" in r["details"], r["details"]
    assert git(root, "rev-parse", "HEAD") == h, "no commit"
    assert git(root, "diff", "--cached", "--name-only") == "", "nothing left staged"
    # the signature itself is in the tree, uncommitted - git status says so
    assert git(root, "status", "--porcelain") == "M publish/publication-holds.json"
    assert {x["topic_id"]: x["signature"] for x in ledger(root)}["t-open"]["via"] == "center"


# --------------------------------------------------------------------- the contract
def test_the_contract_carries_the_routes_and_the_codes():
    import api
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for suffix, model in (("/plan", "HoldSignPlan"), ("", "HoldSignResult")):
        op = spec["paths"][f"/api/publish/{{channel}}/holds/{{batch_id}}/{{topic_id}}/sign"
                           f"{suffix}"]
        assert set(op) == {"post"}, op
        ok = op["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ok["$ref"].endswith(f"/{model}"), ok
        for status in ("404", "409", "422"):
            ref = op["post"]["responses"][status]["content"]["application/json"]["schema"]
            assert "/PublishWriteProblem" in json.dumps(ref), (status, ref)
    schemas = spec["components"]["schemas"]
    codes = set(schemas["PublishWriteProblem"]["properties"]["code"]["enum"])
    assert set(ph().SIGN_REFUSALS_RU) <= codes, set(ph().SIGN_REFUSALS_RU) - codes
    assert set(schemas["HoldSignRefusal"]["properties"]["code"]["enum"]) == \
        set(ph().SIGN_REFUSALS_RU)
    assert "hold_sign" in schemas["HoldSignPlan"]["properties"]["action"]["enum"] or \
        "hold_sign" in json.dumps(schemas["PublishPlanBase"])
    assert {"signable", "sign_refusal"} <= set(schemas["HoldRow"]["properties"])


# --------------------------------------------------------------------- the read-only copy
def test_a_read_only_copy_refuses_the_signature_before_the_factory():
    setup()
    root = world()
    wt = TMP / f"wt-holds-sign-{root.name}"
    git(root, "worktree", "add", "-q", "-b", "dev-holds-sign", str(wt))
    c = client(wt)
    before = files(wt)
    called = []
    saved = {n: getattr(publish, n) for n in ("hold_sign_plan", "hold_sign")}
    for n in saved:
        setattr(publish, n, lambda *a, _n=n, **k: called.append(_n))
    try:
        for path in (f"{base('t-open')}/plan", base("t-open")):
            code, r = post(c, path, {"note": NOTE, "confirm": "x"})
            assert code == 409 and r["code"] == "not_working_factory", (path, r)
    finally:
        for n, f in saved.items():
            setattr(publish, n, f)
    assert called == []
    assert files(wt) == before


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""CC-0114: the user's «да» to the meme bank's candidates in the center
(`api/memes.py` `accept_plan` / `accept`) over the desk's own functions
(CF-0725, `scripts/meme_desk.py`):

    POST /api/memes/{c}/candidates/accept/plan  {ids?, details?} - plan_accept
                                                (by user via center), a token
    POST /api/memes/{c}/candidates/accept       {confirm, answer} -
                                                check_accept_answer, then
                                                accept_candidates
    GET  /api/memes/{c}/candidates              accept {available, fingerprint,
                                                counts, ready, other_bank},
                                                each row's status

In-process (starlette's TestClient) against the stand-in roots of
`tests/test_cc_api_memes.py` `world()` (temp dir under `_tmproot`): the
candidate list and its files are written into the temp `memes-tech` bank
here. No network, no ffprobe, no embedding: the desk's `media_size` and
`_embed_run` are replaced by stand-ins (the desk's docstring: "Tests replace
this").

What is pinned: the GET says the yes is open with the state's fingerprint and
statuses; the plan writes nothing, carries the factory's accept / refused
(each per-id reason: in_bank, not_downloaded, outside_bank, other_bank,
no_source_url, over_ceiling, media_failed) and the answer it wants, and a
token only when someone would be accepted; the confirm takes the user's
answer as typed (not a «да» - 422 bad_answer, the token kept), writes the
entries by user via center with `details`, embeds once, and a second confirm
of the same plan is refused; a list that moved since the plan is the desk's
list_changed, nothing written; stale / foreign / unknown tokens; unknown ids
404; no absolute path in an answer; the routes are guarded writes; the
contract.
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

from test_cc_api_batches import TMP, _w, client, git                # noqa: E402
from test_cc_api_memes import _png, desk, get, send, world          # noqa: E402
from test_cc_api_meme_candidates import cand                        # noqa: E402
from test_cc_api_publish import files                               # noqa: E402

from api import batches                                             # noqa: E402

TECH = ("shared", "inserts", "memes-tech")
PLAN, CONFIRM = "/api/memes/tech/candidates/accept/plan", "/api/memes/tech/candidates/accept"
#: Sizes the stand-in ffprobe answers; any other file is 800x800 (1.35x - passes).
SIZES = {"big-one.png": (100, 100)}
BROKEN = {"broken.png"}
EMBEDS = []


def _media_size(path):
    name = Path(path).name
    if name in BROKEN:
        raise SystemExit("ffprobe failed: not an image")
    return SIZES.get(name, (800, 800))


def _embed_run(name, lib_root):
    EMBEDS.append(name)
    return {"done": True, "line": "embedded 1 meme", "error": None, "en": None, "fatal": False}


def stand_ins():
    """The desk's ffprobe and embedding replaced for this file's tests (put
    back by `@isolated`)."""
    d = desk()
    d.media_size = _media_size
    d._embed_run = _embed_run
    EMBEDS.clear()


def isolated(fn):
    """Run `fn` with the stand-ins, the desk's own functions put back after."""
    def run():
        d = desk()
        saved = (d.media_size, d._embed_run)
        try:
            return fn()
        finally:
            d.media_size, d._embed_run = saved
    run.__name__ = fn.__name__
    return run


def _c(cid, **over):
    return cand(cid, 800, 800, True, **dict({"url": f"https://i.imgflip.com/{cid}.png"},
                                            **over))


def accept_world():
    """memes-tech with a candidate of every kind: two ready, one already in the
    bank, one not downloaded, one stretched past the ceiling, one ffprobe
    cannot read, one without a url, one whose file leads out of the bank; a
    reel_tail one."""
    stand_ins()
    root = world()
    bank = root.joinpath(*TECH)
    for name in ("ready-one", "ready-two", "big-one", "broken", "no-url"):
        _png(bank / f"{name}.png", 64, 64)
    away = TMP / f"away-{root.name}.png"
    _png(away)
    (bank / "outside.png").symlink_to(away)
    data = {"listed": "2026-10-12", "candidates": [
        _c("ready-one"), _c("ready-two"), _c("tech-old"), _c("not-there"), _c("big-one"),
        _c("broken"), _c("no-url", url=None), _c("outside")],
        "reel_tail": {"candidates": [_c("tail-one")]}}
    _w(bank / "candidates.json", data)
    return root


def index(root):
    return json.loads((root.joinpath(*TECH) / "index.json").read_text(encoding="utf-8"))


@isolated
def test_the_get_says_the_yes_is_open_with_the_states_fingerprint():
    root = accept_world()
    before = files(root)
    code, r = get(client(root), "/api/memes/tech/candidates")
    assert code == 200, r
    st = desk().candidates_state("tech", root=root / "shared" / "inserts", repo=root)
    a = r["accept"]
    assert a["available"] is True and a["reason"] is None, a
    assert a["fingerprint"] == st["fingerprint"] and a["fingerprint"].startswith("sha256:")
    assert len(a["fingerprint"]) == len("sha256:") + 16
    assert a["counts"] == st["counts"] and a["counts"]["ready"] == 5, a["counts"]
    assert a["ready"] == ["ready-one", "ready-two", "big-one", "broken", "no-url"], a["ready"]
    assert a["other_bank"] == ["tail-one"], a
    by = {c["id"]: c for c in r["candidates"]}
    assert (by["ready-one"]["status"], by["ready-one"]["bank_file"]) == ("ready", "ready-one.png")
    assert by["tech-old"]["status"] == "in_bank" and by["not-there"]["bank_file"] is None
    assert by["not-there"]["status"] == "not_downloaded"
    assert by["outside"]["status"] == "outside_bank"
    assert str(root) not in json.dumps(r) and str(TMP) not in json.dumps(r)
    assert files(root) == before


@isolated
def test_the_get_without_a_list_says_why_not():
    stand_ins()
    root = world()
    code, r = get(client(root), "/api/memes/reel/candidates")
    assert code == 200 and r["accept"]["available"] is False, r
    assert r["accept"]["reason"] == r["missing"] and "«да»" in r["missing"], r["accept"]


@isolated
def test_the_plan_writes_nothing_and_says_each_refusal():
    root = accept_world()
    c = client(root)
    before = files(root)
    ids = ["ready-one", "ready-two", "tech-old", "not-there", "big-one", "broken", "no-url",
           "outside", "tail-one"]
    code, plan = send(c, "POST", PLAN, {"ids": ids})
    assert code == 200, plan
    assert files(root) == before                                       # a dry run
    assert plan["action"] == "meme_candidates_accept" and plan["channel"] == "tech", plan
    assert (plan["by"], plan["via"], plan["dry_run"], plan["downloads"]) == \
        ("user", "center", True, 0), plan
    assert plan["accept"] == ["ready-one", "ready-two"], plan["accept"]
    reasons = {r["id"]: r["reason"] for r in plan["refused"]}
    assert reasons == {"tech-old": "in_bank", "not-there": "not_downloaded",
                       "big-one": "over_ceiling", "broken": "media_failed",
                       "no-url": "no_source_url", "outside": "outside_bank",
                       "tail-one": "other_bank"}, reasons
    assert all(r["text"] for r in plan["refused"])
    assert plan["answer"]["must_contain"] == "да" and plan["answer"]["must_not_contain"] == \
        ["нет"] and "ready-one" in plan["answer"]["prompt"], plan["answer"]
    assert plan["ok"] is True and plan["confirm"] and plan["expires_in_s"] == 120, plan
    st = desk().candidates_state("tech", root=root / "shared" / "inserts", repo=root)
    assert plan["fingerprint"] == st["fingerprint"]
    assert str(root) not in json.dumps(plan) and str(TMP) not in json.dumps(plan), plan


@isolated
def test_nobody_to_accept_gets_no_token():
    root = accept_world()
    code, plan = send(client(root), "POST", PLAN, {"ids": ["tech-old", "not-there"]})
    assert code == 200 and plan["ok"] is False and plan["confirm"] is None, plan
    assert plan["accept"] == [] and plan["why"].startswith("Принять некого"), plan
    assert plan["answer"]["prompt"] is None


@isolated
def test_the_yes_takes_them_in_by_user_via_center_with_the_users_text():
    root = accept_world()
    c = client(root)
    details = {"ready-one": {"description": "A smug cat on a keyboard.",
                             "tags": ["cat", "smug"], "notes": "из центра"}}
    _, plan = send(c, "POST", PLAN, {"ids": ["ready-one", "ready-two"], "details": details})
    assert plan["details"] == details, plan["details"]
    code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": "Да, беру"})
    assert code == 200, r
    assert r["accepted"] == ["ready-one", "ready-two"] and r["unchanged"] is False, r
    assert (r["by"], r["via"], r["dry_run"], r["answer"]) == \
        ("user", "center", False, "Да, беру"), r
    assert r["embedding"]["done"] is True and EMBEDS == ["memes-tech"], (r, EMBEDS)
    idx = {e["id"]: e for e in index(root)["entries"]}
    one, two = idx["ready-one"], idx["ready-two"]
    assert one["description"] == "A smug cat on a keyboard." and one["tags"] == ["cat", "smug"]
    assert one["review"] == "pending" and "by user" in one["notes"] and \
        "via center" in one["notes"] and "'Да, беру'" in one["notes"], one
    assert "из центра" in one["notes"] and "rewrite them on the desk" not in one["notes"]
    assert "rewrite them on the desk" in two["notes"], two          # no details: the factory's
    journal = root.joinpath(*TECH) / "_desk" / "candidates_accepted.jsonl"
    row = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert (row["by"], row["via"], row["answer"]) == ("user", "center", "Да, беру"), row
    assert str(root) not in json.dumps(r)
    # the same plan again: the token is spent
    code, again = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": "да"})
    assert code == 409 and again["code"] == "confirm_unknown", again


@isolated
def test_the_yes_is_committed_and_the_tree_stays_clean():
    """CC-0156: the yes wrote <bank>/index.json and left it uncommitted. Now one
    commit of what it changed of the bank's tracked files, the trailers."""
    root = accept_world()
    gi = root / ".gitignore"
    gi.write_text(gi.read_text(encoding="utf-8") + "shared/inserts/*/*\n"
                  "!shared/inserts/*/index.json\n!shared/inserts/*/candidates.json\n",
                  encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the banks")
    h = git(root, "rev-parse", "HEAD")
    c = client(root)
    _, plan = send(c, "POST", PLAN, {"ids": ["ready-one"]})
    code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": "Да, беру"})
    assert code == 200, r
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert git(root, "show", "--name-only", "--format=", "HEAD") == \
        "shared/inserts/memes-tech/index.json"
    assert git(root, "status", "--porcelain", "--untracked-files=all") == ""
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith("Мемы tech: кандидаты приняты в банк (user, center)"), msg
    assert "Cc-Channel: tech" in msg and "Cc-Action: meme_candidates_accept" in msg, msg
    assert "Ответ: «Да, беру»" in msg, msg


@isolated
def test_a_new_plan_after_an_accept_is_needed():
    root = accept_world()
    c = client(root)
    _, first = send(c, "POST", PLAN, {"ids": ["ready-one"]})
    _, second = send(c, "POST", PLAN, {"ids": ["ready-two"]})
    assert send(c, "POST", CONFIRM, {"confirm": first["confirm"], "answer": "да"})[0] == 200
    before = files(root)
    code, r = send(c, "POST", CONFIRM, {"confirm": second["confirm"], "answer": "да"})
    assert code == 409 and r["code"] == "list_changed", r
    assert r["message"] and r["details"] and str(root) not in json.dumps(r), r
    assert files(root) == before


@isolated
def test_an_answer_that_is_not_a_yes_keeps_the_token():
    root = accept_world()
    c = client(root)
    _, plan = send(c, "POST", PLAN, {"ids": ["ready-one"]})
    before = files(root)
    for answer in ("", "ок", "да нет наверное", "нет"):
        code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": answer})
        assert code == 422 and r["code"] == "bad_answer", (answer, r)
        assert r["message"].startswith("Кандидаты не приняты"), r
    assert files(root) == before
    code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"]})          # no answer
    assert code == 422, r
    code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": "да"})
    assert code == 200 and r["accepted"] == ["ready-one"], r


@isolated
def test_a_list_that_moved_since_the_plan_is_list_changed():
    root = accept_world()
    c = client(root)
    _, plan = send(c, "POST", PLAN, {"ids": ["ready-one"]})
    p = root.joinpath(*TECH) / "candidates.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["candidates"].append(_c("late-one"))
    _w(p, data)
    before = files(root)
    code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": "да"})
    assert code == 409 and r["code"] == "list_changed", r
    assert files(root) == before and EMBEDS == []


@isolated
def test_tokens_expired_foreign_and_unknown():
    root = accept_world()
    c = client(root)
    _, plan = send(c, "POST", PLAN, {"ids": ["ready-one"]})
    real = batches._clock
    batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
    try:
        before = files(root)
        code, r = send(c, "POST", CONFIRM, {"confirm": plan["confirm"], "answer": "да"})
    finally:
        batches._clock = real
    assert code == 409 and r["code"] == "confirm_expired", r
    assert files(root) == before
    _, plan = send(c, "POST", PLAN, {"ids": ["ready-one"]})
    code, r = send(c, "POST", "/api/memes/reel/candidates/accept",
                   {"confirm": plan["confirm"], "answer": "да"})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    _, apply_plan = send(c, "POST", "/api/memes/tech/apply/plan")
    code, r = send(c, "POST", CONFIRM, {"confirm": apply_plan["confirm"], "answer": "да"})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    code, r = send(c, "POST", CONFIRM, {"confirm": "made-up", "answer": "да"})
    assert code == 409 and r["code"] == "confirm_unknown", r
    assert files(root) == before


@isolated
def test_the_plans_refusals_reach_the_client():
    root = accept_world()
    c = client(root)
    code, r = send(c, "POST", PLAN, {"ids": ["no-such-one"]})
    assert code == 404 and r["code"] == "unknown_id" and "no-such-one" in r["message"], r
    code, r = send(c, "POST", PLAN, {"ids": []})
    assert code == 422 and r["code"] == "bad_ids", r
    code, r = send(c, "POST", PLAN, {"ids": ["ready-one", "ready-one"]})
    assert code == 422 and r["code"] == "bad_ids", r
    code, r = send(c, "POST", PLAN, {"ids": ["ready-one"],
                                     "details": {"ready-two": {"description": "x"}}})
    assert code == 422 and r["code"] == "bad_details", r
    code, r = send(c, "POST", "/api/memes/reel/candidates/accept/plan", {})
    assert code == 409 and r["code"] == "no_candidates", r
    code, r = send(c, "POST", "/api/memes/nope/candidates/accept/plan", {})
    assert code == 404 and r["code"] == "unknown_channel", r
    for body in (r,):
        assert set(body) == {"message", "code", "details"}, body


@isolated
def test_without_ids_every_ready_one_is_planned():
    root = accept_world()
    code, plan = send(client(root), "POST", PLAN, None)
    assert code == 200, plan
    assert plan["accept"] == ["ready-one", "ready-two"], plan
    assert set(plan["ids"]) == {"ready-one", "ready-two", "big-one", "broken", "no-url"}, plan


def test_the_writes_are_guarded_and_in_the_contract():
    import api
    from test_cc_api_writes import GUARDED
    assert {("POST", "/api/memes/{channel}/candidates/accept/plan"),
            ("POST", "/api/memes/{channel}/candidates/accept")} <= GUARDED
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for path, model in ((PLAN, "MemeAcceptPlan"), (CONFIRM, "MemeAcceptResult")):
        op = spec["paths"][path.replace("/tech/", "/{channel}/")]["post"]
        ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/" + model), ref
        assert "/MemesProblem" in json.dumps(op["responses"]["422"]), op["responses"]
    codes = set(spec["components"]["schemas"]["MemesProblem"]["properties"]["code"]["enum"])
    assert {"bad_answer", "list_changed", "no_fingerprint", "no_candidates", "bad_ids",
            "bad_details"} <= codes, codes
    reasons = spec["components"]["schemas"]["MemeAcceptRefused"]["properties"]["reason"]["enum"]
    assert set(reasons) == {"in_bank", "not_downloaded", "outside_bank", "other_bank",
                            "no_source_url", "over_ceiling", "media_failed"}, reasons
    body = spec["components"]["schemas"]["MemeAcceptIn"]
    assert set(body["required"]) == {"confirm", "answer"}, body


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

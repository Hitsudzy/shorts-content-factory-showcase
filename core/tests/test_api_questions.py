#!/usr/bin/env python3
"""CF-0652: the questions in the command center's API (`api/`) -
`GET /api/questions`, `POST /api/questions/{id}/answer|resolve` - over a temp
factory root's journal of questions (shared/needs_you.py); in-process
(starlette's TestClient), no socket, nothing of the live journal read.

Pinned: the list is the journal's (live by default, every status on asking, a
bad status 422); answer and resolve go through the journal's own functions,
under the guard (no session -> 403, nothing written); an unknown question 404,
a resolved one 409, an empty answer 422; the routes are in api/openapi.json.
CC-0058: answer and resolve write - only in the working factory (the tree is a
repo whose main checkout is on `main`); a tree that is not one gets 409
`not_working_factory` and nothing written.
CC-0086 (CF-0703): every question carries its suggested answer (null/false for
an old one); an answer from the center is `via="center"`, `accepted_suggestion`
when it is the question's current suggestion read fresh (a text that is it, or
`accept: true` - the API takes the suggestion itself); an accept of a changed
suggestion (`suggested_at`) is 409 `check_changed`, of none 409 `no_suggestion`,
nothing written.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from fastapi.testclient import TestClient            # noqa: E402

import needs_you as ny                               # noqa: E402
from api.app import SESSION_HEADER, create_app       # noqa: E402
from api.settings import Settings                    # noqa: E402

BASE = "http://127.0.0.1:8790"


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                        env=env, timeout=30)
    assert cp.returncode == 0, (args, cp.stderr)


def as_working_factory(root):
    """CC-0058: the tree as the working factory - a repo on `main` with one commit
    (`agents_lock.is_working_factory`); hooks off, nothing global read."""
    hooks = root.parent / "no-hooks"
    hooks.mkdir()
    git(root.parent, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
        git(root, "config", k, v)
    git(root, "commit", "-q", "--allow-empty", "-m", "the start")


def world(tmp, working=True):
    root = Path(tmp) / "factory"
    root.mkdir()
    if working:
        as_working_factory(root)
    ny.add("monitor", "alert:example-film:E1", "нарушение", channel="example-film",
           root=root, notify=False, now="2026-10-10T10:00:00Z")
    q, _ = ny.add("archive", "archive:x", "старое", root=root, notify=False)
    ny.resolve(q["id"], root=root)
    app = create_app(Settings(factory_root=root, frontend_dist=root / "dist"), token="tok")
    c = TestClient(app, client=("127.0.0.1", 50000), base_url=BASE)
    return root, c


POST = {"Origin": BASE, SESSION_HEADER: "tok"}


def test_get_questions_live_by_default_and_every_status_on_asking():
    with tempfile.TemporaryDirectory() as tmp:
        root, c = world(tmp)
        r = c.get("/api/questions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "live" and [q["id"] for q in body["questions"]] == ["Q1"], body
        q = body["questions"][0]
        assert q["channel"] == "example-film" and q["status"] == "open" and q["text"] == "нарушение"
        assert q["created"] == "2026-10-10T10:00:00Z" and q["source"] == "monitor"
        assert [q["id"] for q in c.get("/api/questions?status=all").json()["questions"]] == \
            ["Q1", "Q2"]
        assert [q["id"] for q in c.get("/api/questions?status=resolved").json()["questions"]] == \
            ["Q2"]
        assert c.get("/api/questions?status=bogus").status_code == 422


def test_answer_and_resolve_through_the_journal_under_the_guard():
    with tempfile.TemporaryDirectory() as tmp:
        root, c = world(tmp)
        r = c.post("/api/questions/Q1/answer", json={"text": "оспорить"})
        assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
        r = c.post("/api/questions/Q1/answer", json={"text": "оспорить"},
                   headers={"Origin": BASE})
        assert r.status_code == 403 and r.json()["guard"] == "session", r.text
        assert ny.get("Q1", root)["status"] == "open", "a refused POST wrote nothing"
        r = c.post("/api/questions/q1/answer", json={"text": "оспорить", "by": "center"},
                   headers=POST)
        assert r.status_code == 200 and r.json()["status"] == "answered", r.text
        got = ny.get("Q1", root)
        assert got["answer"] == "оспорить" and got["answered_by"] == "center", got
        r = c.post("/api/questions/Q1/resolve", json={"note": "встречное подано"}, headers=POST)
        assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
        assert ny.get("Q1", root)["note"] == "встречное подано"
        assert c.post("/api/questions/Q1/resolve", json={}, headers=POST).status_code == 409
        assert c.post("/api/questions/Q1/answer", json={"text": "x"},
                      headers=POST).status_code == 409
        assert c.post("/api/questions/Q9/answer", json={"text": "x"},
                      headers=POST).status_code == 404
        assert c.post("/api/questions/Q9/resolve", json={}, headers=POST).status_code == 404
        assert c.post("/api/questions/Q2/answer", json={"text": ""},
                      headers=POST).status_code == 422


def test_outside_the_working_factory_answer_and_resolve_are_refused():
    """CC-0058: no working factory (here: no git) -> 409 not_working_factory, the
    journal untouched; reading the questions still answers."""
    with tempfile.TemporaryDirectory() as tmp:
        root, c = world(tmp, working=False)
        journal = ny.journal_path(root)
        before = journal.read_bytes()
        for path, body in (("/api/questions/Q1/answer", {"text": "оспорить"}),
                           ("/api/questions/Q1/resolve", {"note": "встречное подано"})):
            r = c.post(path, json=body, headers=POST)
            assert r.status_code == 409, r.text
            b = r.json()
            assert b["code"] == "not_working_factory", b
            assert b["message"].startswith("Только смотреть: не git-репозиторий"), b
        assert journal.read_bytes() == before
        assert c.get("/api/questions").status_code == 200
        assert c.get("/api/health").json()["writes"] is False


def test_the_routes_are_in_the_contract():
    import json
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    for path in ("/api/questions", "/api/questions/{qid}/answer", "/api/questions/{qid}/resolve"):
        assert path in spec["paths"], path


# ---------------------------------------------------------------- CC-0086: the suggested answer
def suggest_world(tmp):
    root, c = world(tmp)
    ny.suggest("Q1", "оспорить", why="контент наш", by="claude", root=root,
               now="2026-10-10T11:00:00Z")
    return root, c


def last_op(root):
    import json
    lines = ny.journal_path(root).read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_the_list_carries_the_suggestion_and_old_questions_none():
    with tempfile.TemporaryDirectory() as tmp:
        root, c = suggest_world(tmp)
        ny.add("archive", "archive:y", "без предложения", root=root, notify=False)
        qs = {q["id"]: q for q in c.get("/api/questions").json()["questions"]}
        q1, q3 = qs["Q1"], qs["Q3"]
        assert (q1["suggestion"], q1["suggestion_why"], q1["suggested_by"], q1["suggested_at"]) \
            == ("оспорить", "контент наш", "claude", "2026-10-10T11:00:00Z"), q1
        assert q1["answered_via"] is None and q1["accepted_suggestion"] is False
        for k in ("suggestion", "suggestion_why", "suggested_by", "suggested_at", "answered_via"):
            assert q3[k] is None, (k, q3)
        assert q3["accepted_suggestion"] is False


def test_a_text_answer_is_accepted_only_when_it_is_the_current_suggestion():
    with tempfile.TemporaryDirectory() as tmp:
        root, c = suggest_world(tmp)
        r = c.post("/api/questions/Q1/answer", json={"text": "  оспорить \n"}, headers=POST)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["answer"] == "оспорить" and b["answered_via"] == "center", b
        assert b["accepted_suggestion"] is True, b
        op = last_op(root)
        assert op["via"] == "center" and op["accepted_suggestion"] is True, op
        r = c.post("/api/questions/Q1/answer", json={"text": "не оспаривать"}, headers=POST)
        b = r.json()
        assert r.status_code == 200 and b["accepted_suggestion"] is False, b
        op = last_op(root)
        assert op["via"] == "center" and "accepted_suggestion" not in op, op
        got = ny.get("Q1", root)
        assert got["answer"] == "не оспаривать" and got["answered_via"] == "center"
        assert got["accepted_suggestion"] is False
        # the client's word is not taken: the suggestion it saw was replaced
        ny.suggest("Q1", "подождать", root=root, now="2026-10-10T12:00:00Z")
        r = c.post("/api/questions/Q1/answer", json={"text": "оспорить"}, headers=POST)
        assert r.status_code == 200 and r.json()["accepted_suggestion"] is False, r.text
        # a question without a suggestion: no accepted answer, whatever the text
        q, _ = ny.add("archive", "archive:z", "ещё", root=root, notify=False)
        r = c.post(f"/api/questions/{q['id']}/answer", json={"text": "да"}, headers=POST)
        assert r.status_code == 200 and r.json()["accepted_suggestion"] is False, r.text
        assert r.json()["answered_via"] == "center"


def test_accept_answers_with_the_fresh_suggestion():
    with tempfile.TemporaryDirectory() as tmp:
        root, c = suggest_world(tmp)
        r = c.post("/api/questions/Q1/answer",
                   json={"accept": True, "suggested_at": "2026-10-10T11:00:00Z"}, headers=POST)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["answer"] == "оспорить" and b["accepted_suggestion"] is True, b
        assert b["answered_via"] == "center" and b["answered_by"] == "user", b
        op = last_op(root)
        assert op["answer"] == "оспорить" and op["accepted_suggestion"] is True, op
        # without suggested_at: whatever the question suggests now
        ny.suggest("Q1", "подождать", root=root, now="2026-10-10T12:00:00Z")
        r = c.post("/api/questions/Q1/answer", json={"accept": True}, headers=POST)
        assert r.status_code == 200 and r.json()["answer"] == "подождать", r.text


def test_accept_refusals_write_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root, c = suggest_world(tmp)
        ny.suggest("Q1", "подождать", root=root, now="2026-10-10T12:00:00Z")
        q, _ = ny.add("archive", "archive:z", "без предложения", root=root, notify=False)
        before = ny.journal_path(root).read_bytes()
        r = c.post("/api/questions/Q1/answer",
                   json={"accept": True, "suggested_at": "2026-10-10T11:00:00Z"}, headers=POST)
        assert r.status_code == 409 and r.json()["code"] == "check_changed", r.text
        r = c.post(f"/api/questions/{q['id']}/answer", json={"accept": True}, headers=POST)
        assert r.status_code == 409 and r.json()["code"] == "no_suggestion", r.text
        r = c.post("/api/questions/Q2/answer", json={"accept": True}, headers=POST)
        assert r.status_code == 409 and "resolved" in r.json()["detail"], r.text
        r = c.post("/api/questions/Q9/answer", json={"accept": True}, headers=POST)
        assert r.status_code == 404, r.text
        for body in ({"accept": True, "text": "подождать"}, {}, {"text": "   "},
                     {"accept": False}):
            r = c.post("/api/questions/Q1/answer", json=body, headers=POST)
            assert r.status_code == 422, (body, r.text)
        r = c.post("/api/questions/Q1/answer", json={"text": "да", "by": "x" * 41}, headers=POST)
        assert r.status_code == 422, r.text
        assert ny.journal_path(root).read_bytes() == before
        # a refused accept under no session wrote nothing either
        r = c.post("/api/questions/Q1/answer", json={"accept": True}, headers={"Origin": BASE})
        assert r.status_code == 403
        assert ny.journal_path(root).read_bytes() == before


def test_the_suggestion_is_in_the_contract():
    import json
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    for k in ("suggestion", "suggestion_why", "suggested_by", "suggested_at", "answered_via",
              "accepted_suggestion"):
        assert k in sch["Question"]["properties"], k
    assert {"text", "by", "accept", "suggested_at"} <= set(sch["AnswerIn"]["properties"])
    assert "code" in sch["Problem"]["properties"]


def test_a_stored_old_console_link_is_the_centers_route():
    """CC-0120 (CF-0735): a question stored with a link to the 2.2 console
    (8790) goes out with the center's route (`notify.center_link`)."""
    saved = {k: os.environ.pop(k, None) for k in ("NOTIFY_CENTER_URL", "NOTIFY_DASHBOARD_URL")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root, c = world(tmp)
            ny.add("publisher-auth", "auth:x", "токен", channel="example-film",
                   link="http://127.0.0.1:8790/#ch-example-film-acceptance", root=root,
                   notify=False)
            got = {q["key"]: q["link"] for q in c.get("/api/questions").json()["questions"]}
    finally:
        os.environ.update({k: v for k, v in saved.items() if v is not None})
    assert got["auth:x"] == "http://127.0.0.1:8790/videos?channel=example-film", got
    assert got["alert:example-film:E1"] is None, got


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

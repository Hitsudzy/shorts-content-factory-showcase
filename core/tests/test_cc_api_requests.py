#!/usr/bin/env python3
"""CC-0018: the requests to the operator in the command center's API (`api/`) -
`GET /api/requests[/{rid}]`, `POST /api/requests`, `POST /api/requests/{rid}/close|cancel`
- over a temp factory root's queue (shared/operator_requests.py, CF-0684);
in-process (starlette's TestClient), no socket, no network, nothing of the live
queue read or written (`REQUESTS_DIR` points at a temp directory too, and stays
empty: the API names its factory root).

Pinned:
* ask -> list -> one: `by: "user"`, the text, channel and context kept; the
  list is `live` by default, every status on asking, an unknown one the
  factory's `status_unknown` (422, `text_ru`);
* the refusals: input 422 (`text_empty`, `text_too_long`, `context_invalid`),
  no such request 404 (`not_found`), a step the state does not allow 409
  (`not_answered`, `already_cancelled`, `already_closed`, `cancel_answered`) -
  always `{detail, code, text_ru}`, the factory's `RequestError.as_dict()`,
  nothing written; every code of the factory has its HTTP, and the contract's
  `RequestProblem.code` is exactly the factory's table;
* the API never takes, answers or resends a request and never reaches the
  notification bus - those are the operator session's (the CLI); no such route;
* under the guard (no session -> 403); outside the working factory every write
  is 409 `not_working_factory`, the journal untouched, reading still answers;
* the routes are in api/openapi.json, version 0.48.0.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient            # noqa: E402

from api import API_VERSION, factory                 # noqa: E402
from api.app import SESSION_HEADER, RequestProblem, create_app   # noqa: E402
from api.settings import Settings                    # noqa: E402

opr = factory.operator_requests()
BASE = "http://127.0.0.1:8790"
POST = {"Origin": BASE, SESSION_HEADER: "tok"}
CONTEXT = {"screen": "video", "channel": "example-film", "batch": "2026-10-10T0000Z",
           "video": "delver"}


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


class World:
    def __init__(self, tmp, working=True):
        self.tmp = Path(tmp)
        self.root = self.tmp / "factory"
        self.root.mkdir()
        if working:
            as_working_factory(self.root)
        self.env_dir = self.tmp / "requests-env"
        self.env_dir.mkdir()
        self.saved = os.environ.get("REQUESTS_DIR")
        os.environ["REQUESTS_DIR"] = str(self.env_dir)
        factory.forget_working_factory()
        app = create_app(Settings(factory_root=self.root, frontend_dist=self.root / "dist"),
                         token="tok")
        self.app = app
        self.c = TestClient(app, client=("127.0.0.1", 50000), base_url=BASE)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.saved is None:
            os.environ.pop("REQUESTS_DIR", None)
        else:
            os.environ["REQUESTS_DIR"] = self.saved
        factory.forget_working_factory()

    @property
    def journal(self):
        return opr.journal_path(root=self.root)

    def ops(self):
        if not self.journal.exists():
            return []
        return [json.loads(x) for x in self.journal.read_text(encoding="utf-8").splitlines()
                if x.strip()]

    def answered(self, text="переделай обложку"):
        """A request taken and answered by the operator, through the module (the
        CLI's functions) - the notifier a stub, no bus."""
        r = opr.add(text, "user", root=self.root, now="2026-10-11T09:00:00Z")
        opr.next(root=self.root, now="2026-10-11T09:01:00Z")
        opr.answer(r["id"], "сделано", root=self.root, now="2026-10-11T09:02:00Z",
                   notifier=lambda r, key: {"status": "sent", "key": key,
                                            "backends": {"telegram": "ok"}})
        return r["id"]


def refused(r, status, code):
    """A refusal of the factory as the API answers it: `{detail, code, text_ru}`."""
    assert r.status_code == status, (status, r.status_code, r.text)
    b = r.json()
    assert set(b) == {"detail", "code", "text_ru"}, b
    assert b["code"] == code and b["text_ru"] and b["detail"], b
    return b


# --------------------------------------------------------------------- reading and asking
def test_ask_list_and_one():
    with tempfile.TemporaryDirectory() as tmp, World(tmp) as w:
        r = w.c.post("/api/requests", headers=POST, json={
            "text": "переделай, потому что\nзвук тихий", "channel": "example-film",
            "context": CONTEXT})
        assert r.status_code == 200, r.text
        got = r.json()
        assert (got["id"], got["n"], got["status"], got["created_by"]) == \
            ("R1", 1, "open", "user"), got
        assert got["text"] == "переделай, потому что\nзвук тихий", got
        assert got["channel"] == "example-film" and got["context"] == CONTEXT, got
        assert got["answer"] is None and got["notify"] is None and got["taken_by"] is None, got
        assert w.journal == w.root / "requests" / "requests.jsonl" and w.journal.exists()
        assert list(w.env_dir.iterdir()) == [], "the API writes its factory root's queue"
        r = w.c.post("/api/requests", headers=POST, json={"text": "ещё одна"})
        assert r.status_code == 200 and r.json()["context"] is None, r.text
        assert r.json()["channel"] is None, r.text

        body = w.c.get("/api/requests").json()
        assert body["status"] == "live" and [x["id"] for x in body["requests"]] == ["R1", "R2"]
        assert w.c.get("/api/requests/R1").json() == got
        assert w.c.get("/api/requests/r1").json()["id"] == "R1"
        assert w.c.post("/api/requests/R2/cancel", headers=POST).status_code == 200
        for status, ids in (("live", ["R1"]), ("open", ["R1"]), ("cancelled", ["R2"]),
                            ("all", ["R1", "R2"]), ("taken", []), ("answered", []),
                            ("closed", [])):
            body = w.c.get(f"/api/requests?status={status}").json()
            assert body["status"] == status and [x["id"] for x in body["requests"]] == ids, \
                (status, body)
        b = refused(w.c.get("/api/requests?status=bogus"), 422, "status_unknown")
        assert "bogus" in b["text_ru"], b


def test_an_answered_request_reads_with_its_notify_and_closes():
    with tempfile.TemporaryDirectory() as tmp, World(tmp) as w:
        rid = w.answered()
        got = w.c.get(f"/api/requests/{rid}").json()
        assert got["status"] == "answered" and got["answer"] == "сделано", got
        assert got["answered_by"] == "operator" and got["taken_by"] == "operator", got
        n = got["notify"]
        assert n["status"] == "sent" and n["attempt"] == 1 and n["reason"] is None, n
        assert n["key"] == f"request:{rid}:answer", n
        assert [x["id"] for x in w.c.get("/api/requests?status=answered").json()["requests"]] \
            == [rid]
        r = w.c.post(f"/api/requests/{rid}/close", headers=POST)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "closed" and r.json()["closed_by"] == "user", r.text
        assert w.c.get("/api/requests").json()["requests"] == []


# --------------------------------------------------------------------- the refusals
def test_input_refusals_are_422_and_write_nothing():
    with tempfile.TemporaryDirectory() as tmp, World(tmp) as w:
        w.c.post("/api/requests", headers=POST, json={"text": "первая"})
        before = w.journal.read_bytes()
        refused(w.c.post("/api/requests", headers=POST, json={"text": ""}), 422, "text_empty")
        refused(w.c.post("/api/requests", headers=POST, json={"text": "  \n "}), 422,
                "text_empty")
        b = refused(w.c.post("/api/requests", headers=POST, json={"text": "я" * 4001}), 422,
                    "text_too_long")
        assert "4000" in b["text_ru"], b
        b = refused(w.c.post("/api/requests", headers=POST, json={
            "text": "с контекстом", "context": {"x": "я" * 4001}}), 422, "context_invalid")
        assert b["text_ru"].startswith("Контекст просьбы не записать"), b
        # a malformed body never reaches the factory: FastAPI's own validation error
        r = w.c.post("/api/requests", headers=POST, json={})
        assert r.status_code == 422 and isinstance(r.json()["detail"], list), r.text
        assert w.journal.read_bytes() == before


def test_unknown_and_state_refusals():
    with tempfile.TemporaryDirectory() as tmp, World(tmp) as w:
        for r in (w.c.get("/api/requests/R9"), w.c.post("/api/requests/R9/close", headers=POST),
                  w.c.post("/api/requests/R9/cancel", headers=POST)):
            b = refused(r, 404, "not_found")
            assert "R9" in b["text_ru"], b
        assert w.ops() == []
        w.c.post("/api/requests", headers=POST, json={"text": "открытая"})
        refused(w.c.post("/api/requests/R1/close", headers=POST), 409, "not_answered")
        assert w.c.post("/api/requests/R1/cancel", headers=POST).json()["cancelled_by"] == "user"
        refused(w.c.post("/api/requests/R1/cancel", headers=POST), 409, "already_cancelled")
        refused(w.c.post("/api/requests/R1/close", headers=POST), 409, "already_cancelled")
        # taken by the operator: still cancellable by the user
        w.c.post("/api/requests", headers=POST, json={"text": "взятая"})
        assert opr.next(root=w.root)["id"] == "R2"
        refused(w.c.post("/api/requests/R2/close", headers=POST), 409, "not_answered")
        assert w.c.post("/api/requests/R2/cancel", headers=POST).json()["status"] == "cancelled"
        rid = w.answered()
        refused(w.c.post(f"/api/requests/{rid}/cancel", headers=POST), 409, "cancel_answered")
        assert w.c.post(f"/api/requests/{rid}/close", headers=POST).status_code == 200
        before = w.journal.read_bytes()
        refused(w.c.post(f"/api/requests/{rid}/close", headers=POST), 409, "already_closed")
        refused(w.c.post(f"/api/requests/{rid}/cancel", headers=POST), 409, "already_closed")
        assert w.journal.read_bytes() == before, "a refusal writes nothing"


def test_every_factory_code_has_its_http_and_is_in_the_contract():
    codes = set(opr.REFUSALS_RU)
    contract = set(RequestProblem.model_fields["code"].annotation.__args__)
    assert contract == codes, contract ^ codes
    want = {"not_found": 404}
    want.update({c: 422 for c in ("text_empty", "text_too_long", "answer_empty",
                                  "answer_too_long", "by_missing", "context_invalid",
                                  "status_unknown")})
    want.update({c: 409 for c in ("not_taken", "already_answered", "not_answered",
                                  "already_closed", "already_cancelled", "cancel_answered",
                                  "no_answer", "already_delivered")})
    assert set(want) == codes, set(want) ^ codes
    assert {c: factory.request_http(c) for c in codes} == want
    # the wrapper turns each into {detail, code, text_ru} with the factory's text
    for code in codes:
        def boom(code=code):
            raise opr.RequestError("x", code=code, id="R1", limit=4000, why="w",
                                   status="s", known="k")
        got, err = factory._request_call(boom)
        assert got is None and err[0] == want[code], (code, err)
        assert err[1] == {"detail": "x", "code": code,
                          "text_ru": opr.REFUSALS_RU[code].format(
                              id="R1", limit=4000, why="w", status="s", known="k")}, err


# --------------------------------------------------------------------- what the API never does
def test_the_api_never_takes_answers_resends_nor_notifies():
    with tempfile.TemporaryDirectory() as tmp, World(tmp) as w:
        rid = w.answered()                         # the operator's, before the trap
        calls = []
        saved = {n: getattr(opr, n) for n in ("next", "answer", "resend", "_deliver", "_push",
                                               "_bus")}

        def trap(name):
            def f(*a, **k):
                calls.append(name)
                raise AssertionError(f"the API called operator_requests.{name}")
            return f
        for n in saved:
            setattr(opr, n, trap(n))
        try:
            ops_before = len(w.ops())
            assert w.c.post("/api/requests", headers=POST,
                            json={"text": "новая", "context": CONTEXT}).status_code == 200
            assert w.c.post("/api/requests", headers=POST, json={"text": "вторая"}).status_code \
                == 200
            for st in factory.REQUEST_STATUSES:
                assert w.c.get(f"/api/requests?status={st}").status_code == 200
            assert w.c.get(f"/api/requests/{rid}").status_code == 200
            assert w.c.post(f"/api/requests/{rid}/close", headers=POST).status_code == 200
            assert w.c.post("/api/requests/R2/cancel", headers=POST).status_code == 200
            refused(w.c.post("/api/requests/R3/close", headers=POST), 409, "not_answered")
            # no route answers, takes or resends - whatever the method
            for path in (f"/api/requests/{rid}/answer", "/api/requests/next",
                         f"/api/requests/{rid}/resend", f"/api/requests/{rid}/take"):
                r = w.c.post(path, headers=POST, json={"text": "ответ"})
                assert r.status_code in (404, 405), (path, r.status_code, r.text)
        finally:
            for n, f in saved.items():
                setattr(opr, n, f)
        assert calls == [], calls
        assert [o["op"] for o in w.ops()[ops_before:]] == ["add", "add", "close", "cancel"]
        assert {o["by"] for o in w.ops()[ops_before:]} == {"user"}
    paths = [r.path for r in w.app.routes if getattr(r, "path", "").startswith("/api/requests")]
    assert sorted(set(paths)) == ["/api/requests", "/api/requests/{rid}",
                                  "/api/requests/{rid}/cancel", "/api/requests/{rid}/close"], paths


# --------------------------------------------------------------------- the guard, only reading
def test_writes_are_under_the_guard():
    with tempfile.TemporaryDirectory() as tmp, World(tmp) as w:
        r = w.c.post("/api/requests", json={"text": "без сессии"})
        assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
        r = w.c.post("/api/requests", json={"text": "без сессии"}, headers={"Origin": BASE})
        assert r.status_code == 403 and r.json()["guard"] == "session", r.text
        assert w.ops() == [], "a refused POST wrote nothing"


def test_outside_the_working_factory_every_write_is_refused():
    """CC-0058: no working factory (here: no git) -> 409 not_working_factory, the
    journal untouched; reading the requests still answers."""
    with tempfile.TemporaryDirectory() as tmp, World(tmp, working=False) as w:
        opr.add("из CLI", "user", root=w.root)
        before = w.journal.read_bytes()
        for path, body in (("/api/requests", {"text": "попросить"}),
                           ("/api/requests/R1/close", None), ("/api/requests/R1/cancel", None)):
            r = w.c.post(path, json=body, headers=POST)
            assert r.status_code == 409, (path, r.text)
            b = r.json()
            assert b["code"] == "not_working_factory", b
            assert b["message"].startswith("Только смотреть: не git-репозиторий"), b
        assert w.journal.read_bytes() == before
        assert [x["id"] for x in w.c.get("/api/requests").json()["requests"]] == ["R1"]
        assert w.c.get("/api/requests/R1").status_code == 200
        assert w.c.get("/api/health").json()["writes"] is False


# --------------------------------------------------------------------- the contract
def test_the_routes_are_in_the_contract():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert API_VERSION == "0.79.0" and spec["info"]["version"] == "0.79.0", spec["info"]
    paths = spec["paths"]
    assert set(paths["/api/requests"]) == {"get", "post"}, paths["/api/requests"]
    assert set(paths["/api/requests/{rid}"]) == {"get"}
    for a in ("close", "cancel"):
        assert set(paths[f"/api/requests/{{rid}}/{a}"]) == {"post"}
    assert not [p for p in paths if p.startswith("/api/requests") and
                any(x in p for x in ("answer", "next", "resend", "take"))]
    status = [p for p in paths["/api/requests"]["get"]["parameters"] if p["name"] == "status"]
    assert status[0]["schema"]["enum"] == list(factory.REQUEST_STATUSES), status
    schemas = spec["components"]["schemas"]
    assert set(schemas["RequestProblem"]["properties"]) == {"detail", "code", "text_ru"}
    assert set(schemas["OperatorRequest"]["properties"]) == {
        "id", "n", "text", "channel", "context", "created", "created_by", "updated", "status",
        "taken_by", "taken_at", "answer", "answered_by", "answered_at", "closed_by",
        "closed_at", "cancelled_by", "cancelled_at", "notify"}
    assert set(schemas["OperatorRequestIn"]["properties"]) == {"text", "channel", "context"}


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

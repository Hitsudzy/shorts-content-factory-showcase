#!/usr/bin/env python3
"""CC-0127: the publication card without the operator in the center
(`api/card_center.py` over `agents/publisher/card_center.py`, CF-0747):

    GET  /api/publish/{c}/cards/{slug}?batch_id=     card_info
    POST /api/publish/{c}/cards/{slug}/build/plan    the center's plan, nothing started
    POST /api/publish/{c}/cards/{slug}/build         card_build_launch by user via center
    GET  /api/publish/{c}/cards/build/{run_id}       card_build_result
    POST /api/publish/{c}/cards/{slug}/ruling/plan   ruling_plan + not_repo / dirty
    POST /api/publish/{c}/cards/{slug}/ruling        ruling_confirm + one commit of touched

Pinned: a card taken by the user's ruling (`ruled`) counts as placeable
wherever the API read `card_state` (the batch video's card and list, a placed
note, card/place, the копилка) and the state block rides along; a build going
makes the state `building` and refuses card/place and the копилка's placement
(`card_building`); the rebuild's plan starts nothing and refuses a bad draft,
a build going and an unknown video; its confirm calls the launcher with the
plan's batch and draft by user via center (THE LAUNCHER IS A STAND-IN - no
test starts a build or a model); the outcome of a run by its code in Russian
with poll_s while it runs, another channel's run 404; the ruling's plan shows
the failing claims and says the ruling covers only the video's own claims,
writes nothing, refuses empty words, a ready card and a dirty note; its
confirm writes the ruling, places the card next to the video and commits
exactly what it touched; a changed card is check_changed, a commit git refuses
commit_refused; every refusal code has a Russian line; the acceptance's
`queued.card_build` reaches the answer; the routes are guarded writes.
CC-0174 (CF-0891): `queued.card_build.why` - why the build did not start -
reaches it with no absolute path, `why: null` without one.

In-process (TestClient) against a stand-in factory root in a temp dir
(`tests/test_cc_api_publish_writes.py` `card_world`). PUBLISH_CARD_AUTOBUILD=0
and the build state under each temp root. No live data, no network, no model.
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
os.environ.pop("PUBLISH_CARD_STATE_DIR", None)
os.environ["PUBLISH_CARD_AUTOBUILD"] = "0"          # no card build by accident (CF-0747)

from test_cc_api_batches import H, TMP, _w, client, git                 # noqa: E402
from test_cc_api_publish import BATCH, SLUG, card_text, setup           # noqa: E402
from test_cc_api_publish_writes import card_world                       # noqa: E402

import api                                                              # noqa: E402
from api import card_center, factory, publish_stash, videos             # noqa: E402
from api.app import CARD_BUILD_REFUSAL_CODES, CARD_RULING_CODES          # noqa: E402

CH = "reel"
GITIGNORE = "/schedule/\npipeline/*\npublish/*.mp4\npublish/**/*.mp4\n"
FAILING = [{"code": "claim_unsupported", "where": "claims/commentary", "video": True,
            "text": "It took ten years to make."}]


def pc():
    return factory.collect().card()


def failing_text():
    """A card built not ready only because a claim of the video's own narration
    failed (the shape CF-0747 writes: the marker's claims verdict and failing)."""
    text = card_text(status="not_ready", publish_line="Слот не назначен.")
    mark = pc().mark_of(text)
    old = json.dumps(mark, ensure_ascii=False, sort_keys=True)
    mark.update(problems=["claim_unsupported"], claims={"verdict": "failed"},
                failing=FAILING, built_at="2026-10-06T09:00:00Z")
    return text.replace(old, json.dumps(mark, ensure_ascii=False, sort_keys=True))


def ruled_text(words="ролик мы берем"):
    text = failing_text()
    mark = pc().mark_of(text)
    ruling = {"rule": pc().RULING_TASK, "words": words, "by": "user", "via": "center",
              "at": "2026-10-06T10:00:00Z", "failing": FAILING, "built_at": mark["built_at"],
              "fingerprint": pc().note_claims.fingerprint(text)}
    return pc()._replace_section(text, pc().RULING_SECTION, pc().ruling_section(ruling))


def world(text=None):
    setup()
    root, d = card_world()
    if text is not None:
        (d / "work" / "publish-card" / f"{SLUG}.md").write_text(text, encoding="utf-8")
    _w(root / ".gitignore", GITIGNORE)
    _w(root / "publish" / "uploads.json", {"uploads": []})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the card world")
    card_center.FACTORY_KW.clear()
    publish_stash.FACTORY_KW.clear()
    publish_stash.FACTORY_KW.update({"now": "2026-10-06T12:00:00+03:00", "open_rows": []})
    return root, d


def get(c, path):
    r = c.get(path)
    return r.status_code, r.json()


def post(c, path, body=None):
    r = c.post(path, headers=H, json=body if body is not None else {})
    return r.status_code, r.json()


def head(root):
    return git(root, "rev-parse", "HEAD")


def run_record(root, d, run_id, code=None, pid=None, channel=CH, slug=SLUG):
    """A build's record and log as card_center writes them - no process."""
    runs = root / "schedule" / "publish-card" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    log = runs / f"{run_id}.log"
    _w(runs / f"{run_id}.json", {
        "run_id": run_id, "task": "CF-0747", "started_at": "2026-10-06T09:30:00Z",
        "by": "user", "via": "center", "auto": False, "channel": channel, "slug": slug,
        "batch_id": BATCH, "batch_dir": str(d), "root": str(root), "script_id": None,
        "draft": None, "pid": pid, "argv": [], "log": str(log)})
    log.write_text("card_center: build ...\n" + (f"PUBLISH_CARD_RESULT: {code}\n" if code else ""),
                   encoding="utf-8")
    if code:
        _w(runs / f"{run_id}.result.json", {
            "run_id": run_id, "code": code, "detail": "", "state": code if code in (
                "ready", "not_ready") else None, "why": None, "reasons": [], "path": None,
            "finished_at": "2026-10-06T09:35:00Z"})
    return log


class Launcher:
    """The stand-in of `card_center.launcher` - records the call, starts nothing."""

    def __init__(self, answer=None):
        self.calls, self.answer = [], answer

    def __enter__(self):
        self.saved = card_center.launcher
        card_center.launcher = self
        return self

    def __call__(self, *a):
        self.calls.append(a)
        return self.answer or {"ok": True, "launched": True, "skipped": None,
                               "run_id": f"{SLUG}-20261006T093000Z", "pid": 4242,
                               "log": "/nowhere/run.log", "draft": None,
                               "card": {"state": "ready", "path": None}, "refusals": [],
                               "lines": [f"{SLUG}: карточка собирается"]}

    def __exit__(self, *exc):
        card_center.launcher = self.saved


def cyr(text):
    return any("а" <= ch <= "я" for ch in str(text).lower())


# ----------------------------------------------------------------- the contract
def test_the_contract_and_the_russian_texts():
    root, _d = world()
    spec = client(root).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    base = "/api/publish/{channel}/cards"
    assert "get" in spec["paths"][base + "/{slug}"]
    assert "get" in spec["paths"][base + "/build/{run_id}"]
    for tail in ("/build/plan", "/build", "/ruling/plan", "/ruling"):
        assert "post" in spec["paths"][base + "/{slug}" + tail], tail
    cc = factory.card_center()
    assert set(cc.BUILD_REFUSALS) <= set(card_center.BUILD_RU)
    assert set(CARD_BUILD_REFUSAL_CODES) == set(card_center.BUILD_RU)
    assert set(cc.RULING_REFUSALS) <= set(card_center.RULING_RU)
    assert set(CARD_RULING_CODES) == set(card_center.RULING_RU)
    assert set(card_center.OUTCOME_RU) == set(cc.OUTCOMES)
    for table in (card_center.BUILD_RU, card_center.RULING_RU):
        for code, (_s, text) in table.items():
            assert cyr(text), code
    assert all(cyr(t) for t in card_center.OUTCOME_RU.values())
    assert "card_building" in publish_stash.PLACE_RU and cyr(publish_stash.PLACE_RU[
        "card_building"][1])


def test_the_writes_need_the_session():
    root, _d = world()
    c = client(root)
    for tail in ("/build/plan", "/build", "/ruling/plan", "/ruling"):
        r = c.post(f"/api/publish/{CH}/cards/{SLUG}{tail}", json={"confirm": "x", "words": "y"})
        assert r.status_code == 403, (tail, r.text)


# ----------------------------------------------------------------- ruled counts as placeable
def test_a_ruled_card_is_placeable_wherever_the_center_reads_a_card():
    root, d = world(ruled_text())
    c = client(root)
    assert pc().card_status(ruled_text())["state"] == "ruled"
    s, card = get(c, f"/api/batches/{CH}/{BATCH}/videos/{SLUG}/card")
    assert s == 200 and card["ready"] is True and card["why"] is None, card
    assert card["card"]["state"] == "ruled" and card["card"]["placeable"], card["card"]
    assert card["card"]["ruling"]["words"] == "ролик мы берем", card["card"]
    assert card["card"]["state_ru"] == "карточка принята решением пользователя"
    s, lst = get(c, f"/api/batches/{CH}/{BATCH}/videos")
    v = [x for x in lst["videos"] if x["slug"] == SLUG][0]
    assert v["card"]["ready"] is True and v["card"]["card"]["state"] == "ruled", v["card"]
    s, info = get(c, f"/api/publish/{CH}/cards/{SLUG}?batch_id={BATCH}")
    assert s == 200 and info["state"] == "ruled" and info["placeable"], info
    assert info["path"] == f"pipeline/{CH}/{BATCH}/work/publish-card/{SLUG}.md", info
    s, info2 = get(c, f"/api/publish/{CH}/cards/{SLUG}")          # the batch from the record
    assert s == 200 and info2["batch_id"] == BATCH, info2
    s, stash = get(c, f"/api/publish/{CH}/stash")
    sv = [x for x in stash["videos"] if x["slug"] == SLUG][0]
    assert sv["card"]["state"] == "ruled" and sv["card"]["placeable"], sv["card"]
    assert sv["card"]["ready"] is False, "machine-ready stays strict"
    s, plan = post(c, f"/api/publish/{CH}/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert s == 200 and plan["ok"] and plan["ready"], plan
    assert plan["card_state"]["state"] == "ruled", plan
    s, done = post(c, f"/api/publish/{CH}/card/place", {"confirm": plan["confirm"]})
    assert s == 200, done
    note = root / done["path"]
    assert pc().card_status(note.read_text(encoding="utf-8"))["state"] == "ruled"
    day = Path(done["path"]).parent.name
    s, n = get(c, f"/api/publish/{CH}/notes/{SLUG}?day={day}")
    assert s == 200 and n["ready"] and n["card"]["state"] == "ruled", n.get("card")
    # a card failing on the video's claims, not ruled: not placeable
    root, d = world(failing_text())
    c = client(root)
    s, card = get(c, f"/api/batches/{CH}/{BATCH}/videos/{SLUG}/card")
    assert card["ready"] is False and card["card"]["state"] == "not_ready", card["card"]
    assert card["card"]["reasons"] == ["claim_unsupported"], card["card"]
    s, plan = post(c, f"/api/publish/{CH}/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert s == 200 and not plan["ok"] and "не готова" in plan["why"], plan


def test_a_build_going_is_building_and_refuses_the_placing():
    root, d = world()
    c = client(root)
    run_record(root, d, f"{SLUG}-20261006T093000Z", pid=os.getpid())     # alive, no result
    s, info = get(c, f"/api/publish/{CH}/cards/{SLUG}?batch_id={BATCH}")
    assert s == 200 and info["state"] == "building", info
    assert info["build"]["code"] == "running" and info["build"]["word"] == "карточка собирается"
    assert info["build"]["log"] == f"schedule/publish-card/runs/{SLUG}-20261006T093000Z.log"
    s, plan = post(c, f"/api/publish/{CH}/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert s == 200 and not plan["ok"] and "собирается" in plan["why"], plan
    s, sp = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": [SLUG]})
    assert s == 200 and not sp["ok"], sp
    codes = [r["code"] for it in sp["items"] for r in it["refusals"]]
    assert "card_building" in codes, sp["items"]
    msg = [r["message"] for it in sp["items"] for r in it["refusals"]
           if r["code"] == "card_building"][0]
    assert msg == publish_stash.PLACE_RU["card_building"][1]
    s, bp = post(c, f"/api/publish/{CH}/cards/{SLUG}/build/plan", {"batch_id": BATCH})
    assert s == 200 and not bp["ok"] and bp["confirm"] is None, bp
    assert [r["code"] for r in bp["refusals"]] == ["running"], bp
    assert bp["why"] == card_center.BUILD_RU["running"][1]


# ----------------------------------------------------------------- the rebuild
def test_the_rebuild_plan_starts_nothing_and_the_confirm_calls_the_launcher():
    root, d = world(ruled_text())
    c = client(root)
    h = head(root)
    with Launcher() as L:
        s, plan = post(c, f"/api/publish/{CH}/cards/{SLUG}/build/plan", {"batch_id": BATCH})
        assert s == 200 and plan["ok"] and plan["confirm"], plan
        assert plan["expires_in_s"] == 120 and plan["action"] == "card_build_launch", plan
        assert plan["with_draft"] is False and "моделью" in plan["what"], plan
        assert plan["card"]["state"] == "ruled" and "снимает решение" in plan["replaces"], plan
        assert (plan["by"], plan["via"]) == ("user", "center")
        assert L.calls == [], "a plan starts nothing"
        assert not (root / "schedule" / "publish-card" / "runs").exists()
        s, r = post(c, f"/api/publish/{CH}/cards/{SLUG}/build", {"confirm": plan["confirm"]})
        assert s == 200, r
        assert L.calls == [(CH, SLUG, "user", "center", BATCH, None, root)], L.calls
        assert r["launched"] and r["run_id"] == f"{SLUG}-20261006T093000Z", r
        assert r["result_url"] == f"/api/publish/{CH}/cards/build/{SLUG}-20261006T093000Z"
        assert r["poll_s"] == card_center.POLL_S
        s, again = post(c, f"/api/publish/{CH}/cards/{SLUG}/build", {"confirm": plan["confirm"]})
        assert s == 409 and again["code"] == "confirm_unknown", again
        # a draft: the model only checks the claims; a bad draft refused, no token
        draft = {"title": "Paper Dragon took ten years", "about": "Why it took ten years.",
                 "hashtags": ["PaperDragon", "Film", "BoxOffice"], "tags": ["paper dragon"]}
        s, plan = post(c, f"/api/publish/{CH}/cards/{SLUG}/build/plan",
                       {"batch_id": BATCH, "draft": draft})
        assert s == 200 and plan["ok"] and plan["with_draft"] and "черновика" in plan["what"]
        s, r = post(c, f"/api/publish/{CH}/cards/{SLUG}/build", {"confirm": plan["confirm"]})
        assert s == 200 and L.calls[-1][5] == draft, L.calls[-1]
        s, bad = post(c, f"/api/publish/{CH}/cards/{SLUG}/build/plan",
                      {"batch_id": BATCH, "draft": {"title": ""}})
        assert s == 200 and not bad["ok"] and bad["confirm"] is None, bad
        assert bad["refusals"][0]["code"] == "bad_draft" and bad["problems"], bad
        s, nope = post(c, f"/api/publish/{CH}/cards/nope/build/plan", {"batch_id": BATCH})
        assert s == 404 and nope["code"] == "unknown_video" and cyr(nope["message"]), nope
        s, nope = post(c, f"/api/publish/{CH}/cards/nope/build/plan", {})
        assert s == 422 and nope["code"] == "batch_required", nope
        # a token of one video does not start another's build
        s, plan = post(c, f"/api/publish/{CH}/cards/{SLUG}/build/plan", {"batch_id": BATCH})
        s, r = post(c, f"/api/publish/{CH}/cards/other/build", {"confirm": plan["confirm"]})
        assert s == 409 and r["code"] == "confirm_mismatch", r
        n = len(L.calls)
    assert n == 2 and head(root) == h, "the build commits nothing"
    # the factory's refusal of the launch: in Russian, its line in details
    root, d = world()
    c = client(root)
    with Launcher({"ok": False, "launched": False, "refusals": [
            {"code": "spawn_failed", "line": "сборка не стартовала (no python)"}],
            "lines": []}):
        s, plan = post(c, f"/api/publish/{CH}/cards/{SLUG}/build/plan", {"batch_id": BATCH})
        s, r = post(c, f"/api/publish/{CH}/cards/{SLUG}/build", {"confirm": plan["confirm"]})
    assert s == 500 and r["code"] == "spawn_failed", r
    assert r["message"] == card_center.BUILD_RU["spawn_failed"][1]
    assert any("no python" in x for x in r["details"]), r


def test_the_outcome_of_a_build_by_its_code():
    root, d = world()
    c = client(root)
    for i, code in enumerate(("ready", "not_ready", "refused", "not_asked", "error")):
        rid = f"{SLUG}-20261006T09300{i}Z"
        run_record(root, d, rid, code=code)
        s, r = get(c, f"/api/publish/{CH}/cards/build/{rid}")
        assert s == 200 and r["code"] == code and r["done"], r
        assert r["text_ru"] == card_center.OUTCOME_RU[code] and r["poll_s"] is None, r
        assert r["word"] == factory.card_center().OUTCOME_WORDS[code], r
        assert str(root) not in json.dumps(r), r
    rid = f"{SLUG}-20261006T093009Z"
    run_record(root, d, rid, pid=os.getpid())
    s, r = get(c, f"/api/publish/{CH}/cards/build/{rid}")
    assert s == 200 and r["code"] == "running" and not r["done"], r
    assert r["poll_s"] == card_center.POLL_S and r["text_ru"] == card_center.OUTCOME_RU["running"]
    s, r = get(c, f"/api/publish/{CH}/cards/build/{SLUG}-20991231T000000Z")
    assert s == 404 and r["code"] == "unknown_run", r
    s, r = get(c, f"/api/publish/{CH}/cards/build/not-a-run")
    assert s == 422 and r["code"] == "bad_run", r
    rid = f"{SLUG}-20261006T093010Z"
    run_record(root, d, rid, code="ready", channel="demo")
    s, r = get(c, f"/api/publish/{CH}/cards/build/{rid}")
    assert s == 404 and r["code"] == "unknown_run", r


# ----------------------------------------------------------------- the ruling
def test_the_ruling_plan_then_confirm_commits_exactly_what_it_touched():
    root, d = world(failing_text())
    c = client(root)
    h = head(root)
    card = d / "work" / "publish-card" / f"{SLUG}.md"
    before = card.read_bytes()
    s, plan = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan",
                   {"batch_id": BATCH, "words": "ролик мы берем"})
    assert s == 200 and plan["ok"] and plan["confirm"] and plan["expires_in_s"] == 120, plan
    assert plan["failing"] == FAILING, plan["failing"]
    assert "только утверждений самого ролика" in plan["scope"], plan["scope"]
    assert plan["path"] == f"publish/{CH}/_queue/{SLUG}.md", plan
    assert plan["state"] == "not_ready" and plan["sha256"], plan
    assert card.read_bytes() == before and not (root / plan["path"]).exists(), "nothing written"
    s, r = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling", {"confirm": plan["confirm"]})
    assert s == 200, r
    assert r["written"] and r["state"] == "ruled" and r["base_sha256"] == plan["sha256"], r
    assert sorted(r["touched"]) == sorted([f"pipeline/{CH}/{BATCH}/work/publish-card/{SLUG}.md",
                                           f"publish/{CH}/_queue/{SLUG}.md"]), r["touched"]
    assert r["committed"] == [f"publish/{CH}/_queue/{SLUG}.md"], r["committed"]
    assert r["commit"] == head(root) and git(root, "rev-parse", "HEAD~1") == h
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith(f"Карточка: {SLUG} принята решением пользователя (user, center)"), msg
    assert "Cc-Action: card_ruling" in msg and "ролик мы берем" in msg, msg
    assert git(root, "status", "--porcelain", "--", "publish") == ""
    note = (root / r["path"]).read_text(encoding="utf-8")
    assert "## Решение пользователя" in note and "ролик мы берем" in note
    assert pc().card_status(note)["state"] == "ruled"
    s, info = get(c, f"/api/publish/{CH}/cards/{SLUG}?batch_id={BATCH}")
    assert info["state"] == "ruled" and info["ruling"]["by"] == "user", info
    # ruled already: the factory takes new words over the same failing claims (its rule)
    s, again = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan",
                    {"batch_id": BATCH, "words": "ещё раз"})
    assert s == 200 and again["state"] == "ruled" and again["failing"] == FAILING, again


def test_the_ruling_refusals():
    # a ready card: nothing to rule
    root, d = world()
    c = client(root)
    s, p = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan",
                {"batch_id": BATCH, "words": "берём"})
    assert s == 200 and not p["ok"] and p["refusals"][0]["code"] == "card_ready", p
    assert p["why"] == card_center.RULING_RU["card_ready"][1]
    # empty words
    root, d = world(failing_text())
    c = client(root)
    s, p = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan", {"batch_id": BATCH, "words": " "})
    assert s == 200 and not p["ok"] and p["refusals"][0]["code"] == "bad_words", p
    # a dirty note in publish/
    note = root / "publish" / CH / "_queue" / f"{SLUG}.md"
    note.write_text("a hand edit\n", encoding="utf-8")
    s, p = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan", {"batch_id": BATCH, "words": "да"})
    assert s == 200 and not p["ok"] and p["refusals"][0]["code"] == "dirty", p
    note.unlink()
    # the card changed between the plan and the confirm
    s, p = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan", {"batch_id": BATCH, "words": "да"})
    assert p["ok"], p
    card = d / "work" / "publish-card" / f"{SLUG}.md"
    card.write_text(card.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    s, r = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "check_changed", r
    assert "## Решение пользователя" not in card.read_text(encoding="utf-8")
    # unknown video 404
    s, r = post(c, f"/api/publish/{CH}/cards/nope/ruling/plan", {"batch_id": BATCH, "words": "да"})
    assert s == 404 and r["code"] == "unknown_video", r


def test_a_commit_git_refuses_is_commit_refused_and_nothing_stays_staged():
    root, d = world(failing_text())
    hooks = TMP / f"refusing-hooks-{root.name}"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))
    c = client(root)
    h = head(root)
    s, p = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling/plan", {"batch_id": BATCH, "words": "да"})
    assert p["ok"], p
    s, r = post(c, f"/api/publish/{CH}/cards/{SLUG}/ruling", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "commit_refused", r
    assert r["message"] == card_center.RULING_RU["commit_refused"][1]
    assert head(root) == h and git(root, "diff", "--cached", "--name-only") == ""
    assert str(root) not in json.dumps(r)


# ----------------------------------------------------------------- the acceptance's build
def test_the_acceptance_s_card_build_reaches_the_answer():
    q = {"code": "placed", "text_ru": "в копилке", "publish_path": "publish/reel/_queue/x.mp4",
         "ok": True, "skipped": False, "refused": False, "changed": True,
         "card_build": {"ok": True, "launched": False, "skipped": "off", "run_id": None,
                        "log": None, "refusals": []}}
    out = videos._queued(TMP, q)
    assert out["card_build"] == {"ok": True, "launched": False, "skipped": "off",
                                 "run_id": None, "log": None, "refusals": [], "error": None,
                                 "why": None}
    q["card_build"] = {"ok": False, "launched": False, "refusals": ["spawn_failed"],
                       "error": "OSError: x"}
    assert videos._queued(TMP, q)["card_build"]["refusals"] == ["spawn_failed"]
    q.pop("card_build")
    assert videos._queued(TMP, q)["card_build"] is None
    from api.app import AcceptQueued
    assert "card_build" in AcceptQueued.model_fields
    assert os.environ["PUBLISH_CARD_AUTOBUILD"] == "0"


def test_the_card_build_s_why_reaches_the_answer_with_no_path():
    """CC-0174 (CF-0891): `card_build.why` - the refusal's own line - goes out
    through `paths.clean`; a row without it has `why: null`."""
    from api.app import AcceptCardBuild, AcceptQueued
    root = Path("/x/root")
    line = (f"card_not_ready: {root}/publish/reel/_queue/x.card.md is not ready; "
            f"busy: a build runs")
    q = {"code": "placed", "text_ru": "в копилке", "publish_path": "publish/reel/_queue/x.mp4",
         "ok": True, "skipped": False, "refused": False, "changed": True,
         "card_build": {"ok": False, "launched": False, "skipped": None, "run_id": None,
                        "log": None, "refusals": ["card_not_ready", "busy"], "why": line}}
    cb = videos._queued(root, q)["card_build"]
    assert cb["refusals"] == ["card_not_ready", "busy"]
    assert cb["why"] == ("card_not_ready: publish/reel/_queue/x.card.md is not ready; "
                         "busy: a build runs"), cb
    assert str(root) not in json.dumps(cb)
    AcceptQueued.model_validate(videos._queued(root, q))
    assert AcceptCardBuild.model_validate(cb).why == cb["why"]
    q["card_build"] = {"ok": True, "launched": True, "skipped": None, "run_id": "r1",
                       "log": "publish/reel/_cards/r1.log", "refusals": []}
    cb = videos._queued(root, q)["card_build"]
    assert cb["why"] is None and cb["launched"] is True
    assert AcceptCardBuild.model_validate(cb).why is None
    assert AcceptCardBuild.model_fields["why"].default is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

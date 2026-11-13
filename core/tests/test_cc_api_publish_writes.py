#!/usr/bin/env python3
"""CC-0065: the publication writes of the command center's API
(`api/publish.py`), two steps each - a plan (read only) and a confirm token of
the batches' own store (`api/batches.py` `_issue` / `_spend`: single use,
CONFIRM_TTL, bound to the root, the channel, the action and the plan's input):

    POST /api/publish/{c}/pause/set/plan | pause/set      channel_pause.set_pause
    POST /api/publish/{c}/pause/clear/plan | pause/clear  channel_pause.clear_pause
    POST /api/publish/{c}/card/place/plan | card/place    publish_card.place
    POST /api/publish/{c}/card/build/plan | card/build    publish_card.build(draft, claims=False)
    POST /api/publish/{c}/rotation/assign/plan | assign   rotate.assign
    POST /api/publish/{c}/rotation/reject/plan | reject   rotate.reject (rule_on_rejection)
    POST /api/publish/{c}/rotation/refuse/plan | refuse   rotate.refuse

In-process (starlette's TestClient) against stand-in factory roots in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`: the main checkout on
`main` - the working factory). **Nothing outside the temp dir is written**:
the clock is fixed, the publisher's `.env` and environment are stand-ins, the
rotation's channel config is the temp root's (`rotate.load_channel` turned to
it), no model is asked (a build with a model is refused before any call), no
network.

What is pinned: each action's plan writes nothing and its confirm changes the
state the way the factory does; a token unknown, used, expired, of another
action or another channel is refused and nothing is written; a plan whose
world changed is `check_changed` (or the factory's refusal when it would
refuse now); a read-only copy (a worktree on another branch) answers 409
`not_working_factory` before any factory call; none of the writes moves HEAD; the rotation's three writes, plan and
confirm, run with the network refused and no child process but git.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import TMP, H, _w, client, factory_tree, git    # noqa: E402
from test_cc_api_publish import (BATCH, DAY, SLUG, acceptance, card_text, files,  # noqa: E402
                                 setup)
from test_cc_api_videos import make_batch                                 # noqa: E402

from api import batches, factory, publish                                 # noqa: E402

NOW = "2026-10-06T12:00:00+03:00"
REASON = "нарушение от студии X - смотрим"


def post(c, path, body=None):
    r = c.post(path, headers=H, json=body if body is not None else {})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def head(root):
    return git(root, "rev-parse", "HEAD")


def actions(root, since):
    """CC-0153: the `Cc-Action` trailers of the commits since `since`, newest first."""
    out = git(root, "log", "--format=%(trailers:key=Cc-Action,valueonly)", f"{since}..HEAD")
    return [ln for ln in out.splitlines() if ln.strip()]


def registry(root):
    p = root / "publish" / "channel-pauses.json"
    return json.loads(p.read_text(encoding="utf-8"))["pauses"] if p.is_file() else []


def plan_and_confirm(c, base, body):
    code, plan = post(c, f"{base}/plan", body)
    assert code == 200, plan
    assert plan["ok"] and plan["confirm"], plan
    assert plan["expires_in_s"] == int(batches.CONFIRM_TTL), plan
    return plan, post(c, base, {"confirm": plan["confirm"]})


# --------------------------------------------------------------------- the pause
def test_pause_set_and_clear_plan_then_confirm():
    setup()
    root = factory_tree()
    c = client(root)
    h0 = head(root)
    before = files(root)
    code, plan = post(c, "/api/publish/reel/pause/set/plan",
                      {"reason": REASON, "until": "2026-10-20"})
    assert code == 200, plan
    assert (plan["action"], plan["channel"], plan["state"], plan["ok"]) == \
        ("pause_set", "reel", "free", True), plan
    assert plan["row"] == {"channel": "reel", "by": "user", "reason": f"{REASON} (из центра)",
                           "until": "2026-10-20T00:00:00+03:00"}, plan
    assert files(root) == before, "a plan writes nothing"
    code, done = post(c, "/api/publish/reel/pause/set", {"confirm": plan["confirm"]})
    assert code == 200, done
    rows = registry(root)
    assert len(rows) == 1 and rows[0]["by"] == "user" and rows[0]["reason"] == \
        f"{REASON} (из центра)" and rows[0]["until"] == "2026-10-20T00:00:00+03:00", rows
    assert done["row"]["pause_id"] == rows[0]["pause_id"], done
    assert done["pause"]["state"] == "paused", done
    # the token is spent
    code, again = post(c, "/api/publish/reel/pause/set", {"confirm": plan["confirm"]})
    assert code == 409 and again["code"] == "confirm_unknown", again
    # a second pause: refused in the plan, no token; with replace - the old row cleared
    code, plan = post(c, "/api/publish/reel/pause/set/plan", {"reason": "другая причина"})
    assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
    assert "уже есть пауза" in plan["why"], plan
    # the clear
    plan, (code, done) = plan_and_confirm(c, "/api/publish/reel/pause/clear",
                                          {"note": "нарушение снят"})
    assert plan["state"] == "paused" and plan["row"]["clear_note"] == "нарушение снят (из центра)"
    assert code == 200, done
    rows = registry(root)
    assert len(rows) == 1 and rows[0]["cleared_by"] == "user" and \
        rows[0]["clear_note"] == "нарушение снят (из центра)" and rows[0]["cleared_at"], rows
    assert done["pause"]["state"] == "free", done
    # nothing to clear now: the plan says so, no token
    code, plan = post(c, "/api/publish/reel/pause/clear/plan", {})
    assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
    # CC-0153: each confirmed write is one commit of the registry - the tree stays clean
    assert actions(root, h0) == ["pause_clear", "pause_set"], actions(root, h0)
    assert git(root, "status", "--porcelain", "--untracked-files=all") == ""
    assert git(root, "show", "--name-only", "--format=", "HEAD") == \
        "publish/channel-pauses.json"
    assert git(root, "log", "-1", "--format=%s").startswith("Пауза reel: снята (user")


def test_pause_needs_a_reason_and_a_readable_until():
    setup()
    root = factory_tree()
    c = client(root)
    code, r = post(c, "/api/publish/reel/pause/set/plan", {"reason": "  "})
    assert code == 422 and r["code"] == "note_required", r
    code, r = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON, "until": "завтра"})
    assert code == 422 and r["code"] == "invalid", r
    code, r = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON,
                                                            "until": "2026-10-01"})
    assert code == 200 and not r["ok"] and "уже прошёл" in r["why"], r
    code, r = post(c, "/api/publish/nope/pause/set/plan", {"reason": REASON})
    assert code == 404 and r["code"] == "unknown_channel", r
    assert registry(root) == []


def test_a_token_unknown_expired_of_another_action_or_channel():
    setup()
    root = factory_tree()
    c = client(root)
    code, r = post(c, "/api/publish/reel/pause/set", {"confirm": "nope"})
    assert code == 409 and r["code"] == "confirm_unknown", r
    # expired
    code, plan = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON})
    real = batches._clock
    batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
    try:
        code, r = post(c, "/api/publish/reel/pause/set", {"confirm": plan["confirm"]})
    finally:
        batches._clock = real
    assert code == 409 and r["code"] == "confirm_expired", r
    # of another action: a set's token presented to the clear
    code, plan = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON})
    code, r = post(c, "/api/publish/reel/pause/clear", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    assert "паузы канала reel" in r["message"] and "снятия паузы канала reel" in r["message"], r
    # of another channel
    code, plan = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON})
    code, r = post(c, "/api/publish/demo/pause/set", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    # a batch's token is not a pause's
    t = batches._issue(root, "launch", "reel", "x")
    code, r = post(c, "/api/publish/reel/pause/set", {"confirm": t})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    assert registry(root) == [], "no refused token wrote"


def test_a_pause_whose_world_changed_is_refused():
    setup()
    root = factory_tree()
    c = client(root)
    code, plan = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON})
    # somebody else paused it meanwhile (the factory's own writer, the CLI's way)
    publish._cp().set_pause("reel", "operator", "руками из консоли", root=root, now=NOW)
    code, r = post(c, "/api/publish/reel/pause/set", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "refused" and "уже есть пауза" in r["message"], r
    assert len(registry(root)) == 1
    # a clear planned, then the row's until changed by a replace: check_changed
    code, plan = post(c, "/api/publish/reel/pause/clear/plan", {})
    publish._cp().set_pause("reel", "operator", "заменена", until="2026-11-01", root=root,
                            now="2026-10-06T12:00:05+03:00", replace=True)
    code, r = post(c, "/api/publish/reel/pause/clear", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "check_changed", r
    assert registry(root)[-1]["cleared_at"] is None


# --------------------------------------------------------------------- the card
PUBLISHER = {"title_suffix": " #shorts", "title_max_chars": 100, "about_max_chars": 450,
             "source_line": "The fact in this video comes from: {source} · {url}",
             "fact_check_line": "On screen: “{wording}” — {source} · {url}",
             "fact_check_line_same_source": "On screen: “{wording}”",
             "attribution_line": "Episode info: {source} ({license}) · {url}",
             "hashtags": {"min": 3, "max": 4, "constant": []}, "tags_constant": [],
             "strength_words_extra": [], "settings": ["Не для детей."],
             "draft_language": "English"}
DRAFT = {"title": "Paper Dragon took ten years", "about": "Why it took ten years.",
         "hashtags": ["PaperDragon", "Film", "BoxOffice"], "tags": ["paper dragon", "film"]}


def card_world():
    """reel with a full publisher block; the batch, its ready card; the accepted
    video waiting in publish/reel/_queue/."""
    root = factory_tree()
    cfg = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    cfg["publisher"] = dict(PUBLISHER, slot=cfg["publisher"]["slot"])
    cfg["language"] = "en"
    _w(root / "channels" / "reel.json", cfg)
    d = make_batch(root, "reel", BATCH, (SLUG,))
    url = "https://en.wikipedia.org/wiki/Paper_Dragon"
    _w(d / "03-content-researcher.json", {"channel": "reel", "batch_id": BATCH, "scripts": [
        {"script_id": f"t-{SLUG}-script1", "topic_id": f"t-{SLUG}",
         "production_fact": {"source_url": url}, "fact": {"source": "Wikipedia", "url": url}}]})
    _w(d / "work" / "publish-card" / f"{SLUG}.md", card_text(publish_line="Слот не назначен."))
    q = root / "publish" / "reel" / "_queue"
    q.mkdir(parents=True)
    (q / f"{SLUG}.mp4").write_bytes(b"\0")
    _w(root / "publish" / "acceptance-log.json", {"acceptances": [acceptance(SLUG, day="_queue")]})
    return root, d


def test_card_place_from_the_queue_into_the_next_slot():
    setup()
    root, d = card_world()
    c = client(root)
    h0 = head(root)
    before = files(root)
    code, plan = post(c, "/api/publish/reel/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert code == 200 and plan["ok"], plan
    assert (plan["ready"], plan["bucket"], plan["target"], plan["target_exists"]) == \
        (True, "_queue", f"publish/reel/_queue/{SLUG}.md", False), plan
    assert plan["slot"]["day"] == "2026-10-07" and plan["slot"]["slot"] == \
        "2026-10-06T22:00:00Z", plan
    assert files(root) == before, "a plan writes nothing"
    code, done = post(c, "/api/publish/reel/card/place", {"confirm": plan["confirm"]})
    assert code == 200, done
    assert done["path"] == f"publish/reel/2026-10-07/{SLUG}.md", done
    placed = root / "publish" / "reel" / "2026-10-07"
    assert (placed / f"{SLUG}.md").is_file() and (placed / f"{SLUG}.mp4").is_file()
    assert not (root / "publish" / "reel" / "_queue" / f"{SLUG}.mp4").exists()
    assert "**2026-10-07 01:00 МСК**" in (placed / f"{SLUG}.md").read_text(encoding="utf-8")
    assert any("окно паттернов не проверено" in ln for ln in done["report"]), done
    # CC-0153: one commit of what the placing changed - nothing left behind in publish/
    assert actions(root, h0) == ["card_place"], actions(root, h0)
    assert git(root, "status", "--porcelain", "--untracked-files=all", "--", "publish") == ""
    shown = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert f"publish/reel/2026-10-07/{SLUG}.md" in shown, shown
    assert "Cc-Channel: reel" in git(root, "log", "-1", "--format=%B")
    # placed: the plan of it again has nothing to follow in _queue/ - the latest entry is the day's,
    # and its note is there: without replace, refused
    code, plan = post(c, "/api/publish/reel/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert code == 200 and not plan["ok"] and "заметка уже там" in plan["why"], plan


def test_card_place_refusals_and_a_changed_card():
    setup()
    root, d = card_world()
    c = client(root)
    card = d / "work" / "publish-card" / f"{SLUG}.md"
    code, plan = post(c, "/api/publish/reel/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert plan["ok"], plan
    card.write_text(card_text(publish_line="Слот не назначен.").replace("Ten Years", "Ten Years!"),
                    encoding="utf-8")                          # a hand edit: not ready now
    code, r = post(c, "/api/publish/reel/card/place", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "refused" and "не готова" in r["message"], r
    assert (root / "publish" / "reel" / "_queue" / f"{SLUG}.mp4").is_file()
    assert not (root / "publish" / "reel" / "_queue" / f"{SLUG}.md").exists()
    code, plan = post(c, "/api/publish/reel/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
    code, r = post(c, "/api/publish/reel/card/place/plan", {"batch_id": BATCH, "slug": "nope"})
    assert code == 404 and r["code"] == "unknown_video", r
    code, r = post(c, "/api/publish/reel/card/place/plan",
                   {"batch_id": BATCH, "slug": SLUG, "day": "tomorrow"})
    assert code == 422 and r["code"] == "invalid", r
    # the pause keeps it in _queue/: the plan says so, the place leaves it there
    card.write_text(card_text(publish_line="Слот не назначен."), encoding="utf-8")
    publish._cp().set_pause("reel", "operator", "нарушение", root=root, now=NOW)
    code, plan = post(c, "/api/publish/reel/card/place/plan", {"batch_id": BATCH, "slug": SLUG})
    assert plan["ok"] and plan["paused"] and plan["slot"] is None, plan
    code, done = post(c, "/api/publish/reel/card/place", {"confirm": plan["confirm"]})
    assert code == 200 and done["path"] == f"publish/reel/_queue/{SLUG}.md", done
    assert any(ln.startswith("PAUSED") for ln in done["report"]), done


def test_card_build_from_the_given_draft_without_the_claim_check():
    setup()
    root, d = card_world()
    c = client(root)
    h0 = head(root)
    before = files(root)
    code, plan = post(c, "/api/publish/reel/card/build/plan",
                      {"batch_id": BATCH, "slug": SLUG, "draft": DRAFT})
    assert code == 200 and plan["ok"] and plan["claims"] is False and plan["exists"], plan
    assert files(root) == before
    code, done = post(c, "/api/publish/reel/card/build", {"confirm": plan["confirm"]})
    assert code == 200, done
    assert done["status"] == "not_ready" and done["mark"]["draft"] == "given", done
    assert [p["code"] for p in done["problems"]] == ["claims_not_checked"], done
    text = (d / "work" / "publish-card" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert "Paper Dragon took ten years #shorts" in text
    assert head(root) == h0
    # a draft the factory does not take: the plan says why, no token
    code, plan = post(c, "/api/publish/reel/card/build/plan",
                      {"batch_id": BATCH, "slug": SLUG, "draft": {"title": ""}})
    assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
    assert "`title` must be a non-empty string" in plan["why"], plan


def test_card_build_with_the_model_is_refused_and_nothing_is_called():
    setup()
    root, d = card_world()
    c = client(root)
    pc = factory.collect().card()
    called = []
    saved = {n: getattr(pc, n) for n in ("build", "ask_draft", "batch_video", "validate_draft")}
    for n in saved:
        setattr(pc, n, lambda *a, _n=n, **k: called.append(_n))
    before = files(root)
    try:
        for body in ({"batch_id": BATCH, "slug": SLUG},
                     {"batch_id": BATCH, "slug": SLUG, "model": True},
                     {"batch_id": BATCH, "slug": SLUG, "draft": DRAFT, "model": True}):
            code, r = post(c, "/api/publish/reel/card/build/plan", body)
            assert code == 409 and r["code"] == "model_refused", r
            assert r["message"].startswith("Черновик через модель — не из центра"), r
    finally:
        for n, f in saved.items():
            setattr(pc, n, f)
    assert called == [] and files(root) == before


# --------------------------------------------------------------------- the rotation
ROT_REASON = ("the list pattern needs five parallel items and this fact has two - the "
              "pair cannot carry it")
DEFICIT = {"assetless_rung": {
    "kind": "assetless_blocks_refused", "rung_enabled": False, "style": "montage",
    "style_typographic": False, "applies": True, "blocks": [2, 4], "block_count": 2,
    "seconds": 8.0, "reasons": ["block carries no picture at all",
                                "block carries no picture at all"],
    "passed": False, "note": "2 block(s) would ship with no picture"}}
SCRIPTS = ["t-a-script1", "t-b-script1", "t-c-script1"]


def test_card_place_commits_only_what_it_changed():
    """CC-0153: a change in the scope the placing did not make stays out of the
    commit (git's word before and after, a dirty file only when its bytes moved)."""
    setup()
    root, _d = card_world()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the card world")
    stray = root / "publish" / "reel" / "stray.md"
    stray.write_text("a hand note\n", encoding="utf-8")
    c = client(root)
    h0 = head(root)
    plan, (code, done) = plan_and_confirm(c, "/api/publish/reel/card/place",
                                          {"batch_id": BATCH, "slug": SLUG})
    assert code == 200, done
    assert actions(root, h0) == ["card_place"], actions(root, h0)
    shown = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "publish/reel/stray.md" not in shown and f"publish/reel/2026-10-07/{SLUG}.md" in shown
    assert git(root, "status", "--porcelain", "--untracked-files=all", "--", "publish") == \
        "?? publish/reel/stray.md"

class rotation_world:
    """reel with three patterns and K=1 in the temp root; `rotate.load_channel`
    reads the temp root's channels/ (the factory's own code reads its checkout's)."""

    def __enter__(self):
        self.root = factory_tree()
        cfg = json.loads((self.root / "channels" / "reel.json").read_text(encoding="utf-8"))
        cfg["patterns"] = {"allowed_pattern_ids": ["explainer", "list", "contrast"],
                           "rotation": {"no_repeat_window_k": 1, "distribution_window": 3}}
        _w(self.root / "channels" / "reel.json", cfg)
        self.rt = factory.rotate()
        self.real = self.rt.load_channel
        root, rt = self.root, self.rt
        self.rt.load_channel = lambda ch: json.loads(
            (root / "channels" / f"{rt.resolve_channel(ch)}.json").read_text(encoding="utf-8"))
        return self

    def __exit__(self, *exc):
        self.rt.load_channel = self.real

    def ledger(self):
        p = self.root / "rotation" / "ledger" / "reel.csv"
        return p.read_text(encoding="utf-8") if p.is_file() else ""


def test_rotation_assign_then_reject_then_refuse():
    setup()
    with rotation_world() as w:
        root, c = w.root, client(w.root)
        h0 = head(root)
        before = files(root)
        code, plan = post(c, "/api/publish/reel/rotation/assign/plan",
                          {"batch_id": BATCH, "script_ids": SCRIPTS})
        assert code == 200 and plan["ok"], plan
        assert [x["state"] for x in plan["scripts"]] == ["fresh"] * 3, plan
        assert len(plan["eligible_pairs"]) >= 2, plan
        assert files(root) == before, "a plan writes nothing"
        code, done = post(c, "/api/publish/reel/rotation/assign", {"confirm": plan["confirm"]})
        assert code == 200, done
        res = done["result"]
        assert [r["script_id"] for r in res] == SCRIPTS and all(r["assigned"] for r in res), res
        assert w.ledger().count("\n") == 4, w.ledger()          # the header and three rows
        # assigned: the plan of the same says standing, and the confirm returns them untouched
        code, plan = post(c, "/api/publish/reel/rotation/assign/plan",
                          {"batch_id": BATCH, "script_ids": SCRIPTS[:1]})
        assert plan["scripts"][0]["state"] == "standing", plan
        # reject the last one: the ruling of rule_on_rejection, then reject writes it
        code, plan = post(c, "/api/publish/reel/rotation/reject/plan",
                          {"script_id": SCRIPTS[2], "reason": ROT_REASON, "batch_id": BATCH})
        assert code == 200 and plan["ok"] and plan["verdict"] == "upheld", plan
        repl = plan["ruling"]["replacement"]
        code, done = post(c, "/api/publish/reel/rotation/reject", {"confirm": plan["confirm"]})
        assert code == 200, done
        got = done["result"]
        assert got["verdict"] == "upheld" and got["replacement"] == repl, got
        assert got["assignment"]["seq"] == 4, got
        assert "rotation-after-rejection" in w.ledger()
        # a second rejection of the same script: R3 - the ruling says denied
        code, plan = post(c, "/api/publish/reel/rotation/reject/plan",
                          {"script_id": SCRIPTS[2], "reason": ROT_REASON, "batch_id": BATCH})
        assert code == 200 and plan["verdict"] == "denied", plan
        # refuse the first one for want of material, with the planner's deficit
        dpath = f"pipeline/reel/{BATCH}/work/t-a/plan.assetless-rung.json"
        _w(root / dpath, DEFICIT)
        code, plan = post(c, "/api/publish/reel/rotation/refuse/plan",
                          {"script_id": SCRIPTS[0], "reason": ROT_REASON, "deficit": dpath,
                           "batch_id": BATCH})
        assert code == 200 and plan["ok"] and plan["row"]["seq"] == "1", plan
        code, done = post(c, "/api/publish/reel/rotation/refuse", {"confirm": plan["confirm"]})
        assert code == 200, done
        assert done["result"]["verdict"] == "upheld" and done["result"]["replacement"] is None
        assert (root / "rotation" / "ledger").is_dir()
        # refused: the row is closed, a second refusal is refused in the plan
        code, plan = post(c, "/api/publish/reel/rotation/refuse/plan",
                          {"script_id": SCRIPTS[0], "reason": ROT_REASON, "deficit": dpath,
                           "batch_id": BATCH})
        assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
        # CC-0153: each confirmed write is one commit of the channel's ledger
        assert actions(root, h0) == ["rotation_refuse", "rotation_reject",
                                     "rotation_assign"], actions(root, h0)
        left = [ln for ln in git(root, "status", "--porcelain", "--untracked-files=all", "--",
                                 "rotation").splitlines()
                if not ln.endswith(".lock")]      # the factory's .gitignore has *.lock (CF-0416)
        assert left == [], left
        assert "rotation/ledger/reel.csv" in git(root, "show", "--name-only", "--format=",
                                                 "HEAD").splitlines()


def test_rotation_refusals_and_a_changed_ledger():
    setup()
    with rotation_world() as w:
        root, c = w.root, client(w.root)
        code, plan = post(c, "/api/publish/reel/rotation/assign/plan",
                          {"batch_id": BATCH, "script_ids": SCRIPTS[:1]})
        # the ledger moves under the plan (another assignment, the CLI's way)
        w.rt.assign("reel", "2026-10-04T0900Z", ["t-z-script1"],
                    ledger_dir=root / "rotation" / "ledger",
                    pipeline_dir=root / "pipeline", root=root)
        code, r = post(c, "/api/publish/reel/rotation/assign", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert "t-a-script1" not in w.ledger()
        # nothing standing to reject: the factory's refusal (R1) - no token
        code, plan = post(c, "/api/publish/reel/rotation/reject/plan",
                          {"script_id": "t-none", "reason": ROT_REASON})
        assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
        assert "has no standing assignment to reject" in plan["why"], plan
        # a refusal: a short reason, a deficit outside pipeline/, a deficit that is not there
        code, plan = post(c, "/api/publish/reel/rotation/refuse/plan",
                          {"script_id": "t-z-script1", "reason": "short",
                           "deficit": "pipeline/reel/x/plan.assetless-rung.json"})
        assert code == 200 and not plan["ok"], plan
        code, r = post(c, "/api/publish/reel/rotation/refuse/plan",
                       {"script_id": "t-z-script1", "reason": ROT_REASON,
                        "deficit": "../etc/passwd"})
        assert code == 422 and r["code"] == "invalid", r
        code, r = post(c, "/api/publish/reel/rotation/assign/plan",
                       {"batch_id": BATCH, "script_ids": []})
        assert code == 422 and r["code"] == "invalid", r
        # a channel without patterns.rotation: the factory's line
        code, r = post(c, "/api/publish/demo/rotation/assign/plan",
                       {"batch_id": BATCH, "script_ids": SCRIPTS})
        assert code == 409 and r["code"] == "rotation_broken", r


class no_network:
    """The rotation's writes are local files only: while inside, a socket that
    connects or resolves a name raises (and is written down), and every child
    process is written down - only `git` is let through (the working-factory
    check reads the branch)."""

    def __enter__(self):
        import socket
        self.socket = socket
        self.saved = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo,
                      socket.create_connection, subprocess.Popen.__init__)
        self.net, self.procs = [], []
        real_popen = self.saved[4]

        def refuse(*a, **k):
            self.net.append(repr(a[1:] if a else k))
            raise OSError("network refused in the rotation's no-network test")

        def popen(proc, args, *a, **k):
            argv = [args] if isinstance(args, (str, bytes)) else list(args)
            self.procs.append(argv)
            if not argv or Path(str(argv[0])).name != "git":
                raise OSError(f"a child process in the rotation's write: {args!r}")
            return real_popen(proc, args, *a, **k)

        socket.socket.connect = refuse
        socket.socket.connect_ex = refuse
        socket.getaddrinfo = refuse
        socket.create_connection = refuse
        subprocess.Popen.__init__ = popen
        return self

    def __exit__(self, *exc):
        s = self.socket
        (s.socket.connect, s.socket.connect_ex, s.getaddrinfo, s.create_connection,
         subprocess.Popen.__init__) = self.saved


def test_the_rotation_writes_go_to_no_network():
    """CC-0065: «refuse - сначала подтвердить, что без сети» - assign, reject
    and refuse, plan and confirm, run through with the network refused and no
    child process but git; each confirm wrote the ledger."""
    setup()
    with rotation_world() as w:
        root, c = w.root, client(w.root)
        dpath = f"pipeline/reel/{BATCH}/work/t-a/plan.assetless-rung.json"
        _w(root / dpath, DEFICIT)
        with no_network() as nn:
            _plan, (code, r) = plan_and_confirm(c, "/api/publish/reel/rotation/assign",
                                                {"batch_id": BATCH, "script_ids": SCRIPTS})
            assert code == 200, r
            _plan, (code, r) = plan_and_confirm(c, "/api/publish/reel/rotation/reject",
                                                {"script_id": SCRIPTS[2], "reason": ROT_REASON,
                                                 "batch_id": BATCH})
            assert code == 200, r
            _plan, (code, r) = plan_and_confirm(c, "/api/publish/reel/rotation/refuse",
                                                {"script_id": SCRIPTS[0], "reason": ROT_REASON,
                                                 "deficit": dpath, "batch_id": BATCH})
            assert code == 200 and r["result"]["replacement"] is None, r
        assert nn.net == [], nn.net
        assert all(Path(str(p[0])).name == "git" for p in nn.procs), nn.procs
        assert w.ledger().count("\n") == 5, w.ledger()   # header, three, the replacement
        assert "rotation-after-rejection" in w.ledger()


def test_the_rotation_tokens_and_a_ledger_that_moved_under_reject_and_refuse():
    setup()
    with rotation_world() as w:
        root, c = w.root, client(w.root)
        ledger_dir = root / "rotation" / "ledger"
        plan, (code, r) = plan_and_confirm(c, "/api/publish/reel/rotation/assign",
                                           {"batch_id": BATCH, "script_ids": SCRIPTS})
        assert code == 200, r
        # a used token is unknown; nothing more is written
        led = w.ledger()
        code, r = post(c, "/api/publish/reel/rotation/assign", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "confirm_unknown", r
        # an assign's token is not a reject's, nor a refuse's; a pause's is not the rotation's
        # (a token presented to the wrong action is spent: each try gets a fresh plan)
        for action in ("reject", "refuse"):
            code, plan = post(c, "/api/publish/reel/rotation/assign/plan",
                              {"batch_id": BATCH, "script_ids": ["t-d-script1"]})
            assert code == 200 and plan["ok"], plan
            code, r = post(c, f"/api/publish/reel/rotation/{action}",
                           {"confirm": plan["confirm"]})
            assert code == 409 and r["code"] == "confirm_mismatch", (action, r)
        code, p = post(c, "/api/publish/reel/pause/set/plan", {"reason": REASON})
        code, r = post(c, "/api/publish/reel/rotation/assign", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        # of another channel
        code, plan = post(c, "/api/publish/reel/rotation/reject/plan",
                          {"script_id": SCRIPTS[1], "reason": ROT_REASON, "batch_id": BATCH})
        assert code == 200 and plan["ok"], plan
        code, r = post(c, "/api/publish/demo/rotation/reject", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        assert w.ledger() == led, "no refused token wrote"
        # a reject planned, then the ledger moved (the CLI rejected another script):
        # check_changed, the plan's row untouched
        code, plan = post(c, "/api/publish/reel/rotation/reject/plan",
                          {"script_id": SCRIPTS[1], "reason": ROT_REASON, "batch_id": BATCH})
        assert code == 200 and plan["ok"], plan
        w.rt.reject("reel", SCRIPTS[2], ROT_REASON, ledger_dir=ledger_dir, batch_id=BATCH)
        moved = w.ledger()
        code, r = post(c, "/api/publish/reel/rotation/reject", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert w.ledger() == moved
        # a refuse planned, then the deficit file changed under it: check_changed
        dpath = f"pipeline/reel/{BATCH}/work/t-a/plan.assetless-rung.json"
        _w(root / dpath, DEFICIT)
        code, plan = post(c, "/api/publish/reel/rotation/refuse/plan",
                          {"script_id": SCRIPTS[0], "reason": ROT_REASON, "deficit": dpath,
                           "batch_id": BATCH})
        assert code == 200 and plan["ok"], plan
        d2 = json.loads(json.dumps(DEFICIT))
        d2["assetless_rung"].update(blocks=[2], block_count=1, reasons=d2["assetless_rung"]
                                    ["reasons"][:1], note="1 block(s) would ship with no picture")
        _w(root / dpath, d2)
        code, r = post(c, "/api/publish/reel/rotation/refuse", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert w.ledger() == moved
        # a refuse that a rejection beat to the row: the upheld rejection stood up a
        # replacement row for the script - another row than the plan's: check_changed
        code, plan = post(c, "/api/publish/reel/rotation/refuse/plan",
                          {"script_id": SCRIPTS[0], "reason": ROT_REASON, "deficit": dpath,
                           "batch_id": BATCH})
        assert code == 200 and plan["ok"], plan
        w.rt.reject("reel", SCRIPTS[0], ROT_REASON, ledger_dir=ledger_dir, batch_id=BATCH)
        moved = w.ledger()
        code, r = post(c, "/api/publish/reel/rotation/refuse", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert w.ledger() == moved


# --------------------------------------------------------------------- the read-only copy
def test_a_read_only_copy_refuses_every_publication_write_before_the_factory():
    setup()
    root = factory_tree()
    wt = TMP / f"wt-publish-writes-{root.name}"
    git(root, "worktree", "add", "-q", "-b", "dev-publish", str(wt))
    c = client(wt)
    before = files(wt)
    called = []
    saved = {n: getattr(publish, n) for n in WRITE_FUNCS}
    for n in WRITE_FUNCS:
        setattr(publish, n, lambda *a, _n=n, **k: called.append(_n))
    try:
        for path in WRITE_ROUTES:
            code, r = post(c, path.replace("{channel}", "reel"), {})
            assert code == 409 and r["code"] == "not_working_factory", (path, r)
    finally:
        for n, f in saved.items():
            setattr(publish, n, f)
    assert called == []
    assert files(wt) == before


WRITE_FUNCS = ("pause_set_plan", "pause_set", "pause_clear_plan", "pause_clear",
               "card_place_plan", "card_place", "card_build_plan", "card_build",
               "rotation_assign_plan", "rotation_assign", "rotation_reject_plan",
               "rotation_reject", "rotation_refuse_plan", "rotation_refuse")
WRITE_ROUTES = tuple(f"/api/publish/{{channel}}/{a}{s}" for a in (
    "pause/set", "pause/clear", "card/place", "card/build", "rotation/assign",
    "rotation/reject", "rotation/refuse") for s in ("/plan", ""))


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

#!/usr/bin/env python3
"""CC-0058: the command center's API writes only in the working factory.

The rule is the factory's (`shared/agents_lock.py` `is_working_factory`,
CF-0677): the main checkout, on `main`. Anywhere else - a development copy
(`.worktrees/cc-api`, `release-<v>`), another branch, a detached HEAD, no git -
every route that writes answers `409 {message, code: not_working_factory,
details}` («Только смотреть: <причина>») before the factory is asked; the
developer's `CC_API_WRITES=dev` lets it write (a warning at the start and on
every such write). Reading stays: every GET, `POST /channels/{c}/check`,
`POST /channels` with `dry_run: true`.

What is pinned:

* every non-GET route of the app either depends on `require_writes` or is in
  the allow-list below - a future write route cannot be forgotten;
* the trees (temp, git only): the main checkout on main writes; a `git
  worktree`, another branch, a detached HEAD, no git - refused, each with the
  factory's reason, and nothing of the factory is called; the dev flag writes
  and says so; check and a dry run answer everywhere;
* `/health` and `/version`: `writes`, `writes_reason`, `writes_dev`;
* `CC_API_WRITES`: `dev` or nothing; the answer is kept a few seconds only (a
  branch switched under the API is seen).

No network, no live data: stand-in trees in a temp dir, the TestClient.
"""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)     # the state goes under each temp root
os.environ.pop("CC_API_WRITES", None)

from fastapi.routing import APIRoute                 # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import (batches, card_center, channel_lists, channels, ending, factory,  # noqa: E402
                 maintenance, meme_jobs, memes, notifications, notify_send, oauth, pool, publish,
                 publish_move, publish_net, publish_stash, studio_center,
                 studio_entry, videos, withdrawal)
from api.app import SESSION_HEADER, WRITES_LOG, create_app   # noqa: E402
from api.settings import Settings, SettingsError     # noqa: E402
import test_cc_api_channels as tc                    # noqa: E402
from test_cc_api_new_channel import NEW              # noqa: E402

TMP = tmp_root("cc-api-writes-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
H = {"Origin": BASE, SESSION_HEADER: "tok"}
PREFIX = "/api"

#: Non-GET routes that do not depend on `require_writes`, and why. Anything
#: new that is not here must be guarded.
ALLOWED = {
    ("POST", "/api/channels/{channel}/check"): "the factory's verdict on a candidate, "
                                               "nothing written",
    ("POST", "/api/channels"): "a new channel - `dry_run` writes nothing; a real create "
                               "calls require_writes in the route",
    # CC-0036: the login - a session of this process's memory, nothing of the factory
    ("POST", "/api/auth/login"): "the password -> a session cookie, nothing written",
    ("POST", "/api/auth/logout"): "a session ended, nothing written",
    **{(m, "/api/{rest:path}"): "the 404 of an unknown /api route"
       for m in ("POST", "PUT", "PATCH", "DELETE")},
}
#: The write routes of 0.16.0 - every one guarded (a route renamed or dropped
#: shows up here, not silently).
GUARDED = {
    ("POST", "/api/questions/{qid}/answer"), ("POST", "/api/questions/{qid}/resolve"),
    # CC-0018: the requests to the operator - ask, close, cancel (by: user)
    ("POST", "/api/requests"), ("POST", "/api/requests/{rid}/close"),
    ("POST", "/api/requests/{rid}/cancel"),
    ("PUT", "/api/channels/{channel}"), ("POST", "/api/channels/{channel}/history/{commit}/revert"),
    ("POST", "/api/schedule/switch"), ("PUT", "/api/schedule/channels/{channel}"),
    ("POST", "/api/batches/launch/plan"), ("POST", "/api/batches/launch"),
    ("POST", "/api/batches/{channel}/{batch_id}/stop/plan"),
    ("POST", "/api/batches/{channel}/{batch_id}/stop"),
    ("POST", "/api/batches/{channel}/{batch_id}/resume/plan"),
    ("POST", "/api/batches/{channel}/{batch_id}/resume"),
    ("POST", "/api/batches/{channel}/{batch_id}/rebuild/plan"),
    # CC-0123: «повторить со стадии» (CF-0739) - the plan and the confirm
    ("POST", "/api/batches/{channel}/{batch_id}/rerun-from/plan"),
    ("POST", "/api/batches/{channel}/{batch_id}/rerun-from"),
    # CC-0114 / CC-0120 / CC-0122, guarded since they shipped and never listed
    # here: the ending render, the Studio read, the копилка
    ("POST", "/api/channels/{channel}/ending/plan"), ("POST", "/api/channels/{channel}/ending"),
    ("POST", "/api/studio/read/plan"), ("POST", "/api/studio/read"),
    ("POST", "/api/publish/{channel}/stash/place/plan"),
    ("POST", "/api/publish/{channel}/stash/place"),
    ("POST", "/api/publish/{channel}/stash/repair/plan"),
    ("POST", "/api/publish/{channel}/stash/repair"),
    # CC-0165: moving placed videos / taking them back into the копилка (publish_move,
    # move_confirm by user via center, CF-0856) - plan and confirm
    ("POST", "/api/publish/{channel}/move/plan"),
    ("POST", "/api/publish/{channel}/move/confirm"),
    # CC-0127: the card from the center (CF-0747) - «Собрать заново» and the user's ruling,
    # plan and confirm
    ("POST", "/api/publish/{channel}/cards/{slug}/build/plan"),
    ("POST", "/api/publish/{channel}/cards/{slug}/build"),
    ("POST", "/api/publish/{channel}/cards/{slug}/ruling/plan"),
    ("POST", "/api/publish/{channel}/cards/{slug}/ruling"),
    ("POST", "/api/batches/{channel}/{batch_id}/rebuild"),
    ("POST", "/api/batches/{channel}/{batch_id}/videos/{slug}/acceptance"),
    # CC-0065: the publication writes, plan and confirm alike
    *{("POST", f"/api/publish/{{channel}}/{a}{s}") for a in (
        "pause/set", "pause/clear", "card/place", "card/build", "rotation/assign",
        "rotation/reject", "rotation/refuse") for s in ("/plan", "")},
    # CC-0066: the API-upload switch, the upload, the Studio record
    *{("POST", f"/api/publish/{{channel}}/{a}{s}") for a in (
        "api-upload/switch", "upload", "studio/record") for s in ("/plan", "")},
    # CC-0070: the hold's signature (publication_hold.sign_hold, via center)
    ("POST", "/api/publish/{channel}/holds/{batch_id}/{topic_id}/sign/plan"),
    ("POST", "/api/publish/{channel}/holds/{batch_id}/{topic_id}/sign"),
    # CC-0024: the meme desk - the draft of marks, apply (plan and confirm)
    ("PUT", "/api/memes/{channel}/marks"), ("POST", "/api/memes/{channel}/apply/plan"),
    ("POST", "/api/memes/{channel}/apply"),
    # CC-0114: the user's «да» to the bank's candidates (plan_accept / accept_candidates by
    # user via center, CF-0725) - plan and confirm
    ("POST", "/api/memes/{channel}/candidates/accept/plan"),
    ("POST", "/api/memes/{channel}/candidates/accept"),
    # CC-0075: the desk's background jobs (start_job by user via center, CF-0755) - the
    # cutout and the trim, plan and confirm
    ("POST", "/api/memes/{channel}/cutout/plan"), ("POST", "/api/memes/{channel}/cutout"),
    ("POST", "/api/memes/{channel}/trim/plan"), ("POST", "/api/memes/{channel}/trim"),
    # CC-0076: the adds, the sheet and the embed (start_job by user via center, CF-0760)
    *{("POST", f"/api/memes/{{channel}}/{a}{x}") for a in ("add-image", "add-gif", "sheet",
                                                            "embed") for x in ("/plan", "")},
    # CC-0074: entering a Studio read (studio_read.record by user via center)
    ("POST", "/api/analytics/{channel}/studio/record/plan"),
    ("POST", "/api/analytics/{channel}/studio/record"),
    # CC-0026: a reminder (notify.add_reminder by user) - plan and confirm
    ("POST", "/api/notify/reminders/plan"), ("POST", "/api/notify/reminders"),
    # CC-0081: the cancel of a reminder (notify.cancel_reminder by user via center)
    ("POST", "/api/notify/reminders/{rid}/cancel/plan"),
    ("POST", "/api/notify/reminders/{rid}/cancel"),
    # CC-0109: a test message to every delivery channel that is on (notify.send_test as
    # `notify.py test --send`) - plan and confirm
    ("POST", "/api/notify/test-send/plan"), ("POST", "/api/notify/test-send"),
    # CC-0028: the purge of API Data (api_data.apply by user via center) - plan and confirm
    ("POST", "/api/oauth/api-data/purge/plan"), ("POST", "/api/oauth/api-data/purge"),
    # CC-0082: the revocation (api_data.revoke_result by user via center) and the deletion
    # by term (api_data.auto delete by user via center) - plan and confirm
    ("POST", "/api/oauth/revoke/plan"), ("POST", "/api/oauth/revoke"),
    ("POST", "/api/oauth/api-data/auto/plan"), ("POST", "/api/oauth/api-data/auto"),
    # CC-0032: the cleanup of the batch journals (cleanup_batch_journals.plan / delete,
    # by user via center) - plan and confirm
    ("POST", "/api/maintenance/journals/plan"), ("POST", "/api/maintenance/journals"),
    # CC-0105: freeing the footage pool (pool_release.plan / delete) - plan and confirm
    ("POST", "/api/maintenance/pool/release/plan"), ("POST", "/api/maintenance/pool/release"),
    # CC-0106: the hand edit of a Studio video and its undo (upload_records.mark_user_edited,
    # by user via center; the plan its dry run) - plan and confirm
    *{("POST", f"/api/publish/{{channel}}/studio/edited{a}{s}") for a in ("", "/undo")
      for s in ("/plan", "")},
    # CC-0107: taking a video off for good on the user's word (pool_release.record_withdrawal,
    # by user via center) - plan and confirm
    ("POST", "/api/batches/{channel}/{batch_id}/videos/{slug}/withdraw/plan"),
    ("POST", "/api/batches/{channel}/{batch_id}/videos/{slug}/withdraw"),
    # CC-0104: the month archive (archive_publish_month --publish-only, --dry-run --json the
    # plan, --by user --via center the run) - plan and confirm
    ("POST", "/api/maintenance/archive/plan"), ("POST", "/api/maintenance/archive"),
    # CC-0114: a channel's own lists through the factory's checked writers (CF-0726:
    # write_fact_sources, write_footage_origin, affiliate.write_table,
    # by user via center; the plan the dry run) - plan and confirm
    *{("POST", f"/api/channels/{{channel}}/{n}{s}")
      for n in ("fact-sources", "footage-origin", "affiliate")
      for s in ("/plan", "")},
    # CC-0114: the user's signature under a gate's price and decision on its mode
    # (gate_price.sign / decide, CF-0721, by user via center; the plan the dry run) -
    # plan and confirm
    *{("POST", f"/api/gate-prices/{{rule}}/{k}{s}") for k in ("sign", "decide")
      for s in ("/plan", "")},
}


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                        env=env, timeout=30)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def make(settings_root, writes_dev=False):
    factory.forget_working_factory()
    app = create_app(Settings(factory_root=settings_root, writes_dev=writes_dev), token="tok")
    return app, TestClient(app, client=LOCAL, base_url=BASE)


def non_get_routes(app):
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith(PREFIX + "/"):
            for m in sorted(r.methods - {"GET", "HEAD"}):
                yield m, r


def guarded_by_dependency(app, route):
    return app.state.require_writes in [d.call for d in route.dependant.dependencies]


def filled(path):
    return path.replace("{qid}", "Q1").replace("{rid}", "R1").replace("{channel}", "reel").replace(
        "{commit}", "0" * 12).replace("{batch_id}", "2026-10-10T0000Z").replace("{slug}", "delver")


class Spy:
    """Every function of the factory a write route calls, replaced by one that
    records the call: a refused write must not reach any of them."""

    NAMES = {channels: ("save", "revert", "create"),
             batches: ("switch", "set_settings", "launch_plan", "launch", "stop_plan", "stop",
                       "resume_plan", "resume", "rebuild_plan", "rebuild", "rerun_plan",
                       "rerun_from"),
             videos: ("accept",),
             publish: ("pause_set_plan", "pause_set", "pause_clear_plan", "pause_clear",
                       "card_place_plan", "card_place", "card_build_plan", "card_build",
                       "rotation_assign_plan", "rotation_assign", "rotation_reject_plan",
                       "rotation_reject", "rotation_refuse_plan", "rotation_refuse"),
             memes: ("save", "apply_plan", "apply", "accept_plan", "accept"),
             meme_jobs: ("cutout_plan", "cutout", "trim_plan", "trim", "add_image_plan",
                         "add_image", "add_gif_plan", "add_gif", "sheet_plan", "sheet",
                         "embed_plan", "embed"),
             studio_entry: ("record_plan", "record"),
             notifications: ("reminder_plan", "reminder_add", "reminder_cancel_plan",
                             "reminder_cancel"),
             oauth: ("purge_plan", "purge", "revoke_plan", "revoke", "auto_plan", "auto_delete"),
             maintenance: ("journals_plan", "journals_clean", "archive_plan", "archive_run"),
             pool: ("release_plan", "release"),
             publish_net: ("studio_edited_plan", "studio_edited", "studio_edited_undo_plan",
                           "studio_edited_undo"),
             withdrawal: ("withdraw_plan", "withdraw"),
             channel_lists: ("plan", "write"),
             notify_send: ("test_send_plan", "test_send"),
             ending: ("render_plan", "render"),
             studio_center: ("read_plan", "read"),
             publish_stash: ("place_plan", "place", "repair_plan", "repair"),
             publish_move: ("move_plan", "move"),
             card_center: ("build_plan", "build", "ruling_plan", "ruling", "launcher"),
             factory: ("answer_question", "resolve_question", "request_add", "request_close",
                       "request_cancel")}

    def __init__(self, through=False):
        self.through = through          # the working factory: a call is expected

    def __enter__(self):
        self.calls, self.saved = [], []
        for mod, names in self.NAMES.items():
            for n in names:
                self.saved.append((mod, n, getattr(mod, n)))
                setattr(mod, n, self._rec(n))
        return self

    def _rec(self, n):
        def rec(*a, **k):
            self.calls.append(n)
            if self.through:
                raise batches.BatchFault(503, "refused", f"spy: {n} reached")
            raise AssertionError(f"{n} called - the guard let a write through")
        return rec

    def __exit__(self, *exc):
        for mod, n, f in self.saved:
            setattr(mod, n, f)


def assert_refused(r, reason_start):
    assert r.status_code == 409, r.text
    b = r.json()
    assert b["code"] == "not_working_factory", b
    assert b["message"] == f"Только смотреть: {b['details'][0]}", b
    assert b["details"][0].startswith(reason_start), b
    assert set(b) == {"message", "code", "details"}, b


# --------------------------------------------------------------------- the trees
def worktree_of(root, name="dev"):
    wt = TMP / f"wt-{root.name}-{name}"
    git(root, "worktree", "add", "-q", "-b", name, str(wt))
    return wt


# --------------------------------------------------------------------- the routes
def test_every_non_get_route_is_guarded_or_allowed():
    app, _ = make(TMP)
    seen, unguarded = set(), []
    for m, r in non_get_routes(app):
        key = (m, r.path)
        seen.add(key)
        if guarded_by_dependency(app, r):
            assert key not in ALLOWED, f"{key} is guarded and in the allow-list - pick one"
            continue
        if key not in ALLOWED:
            unguarded.append(key)
    assert not unguarded, (f"non-GET routes neither depending on require_writes nor in "
                           f"ALLOWED (CC-0058): {unguarded}")
    assert set(ALLOWED) <= seen, f"stale allow-list rows: {set(ALLOWED) - seen}"
    guarded = {k for k in seen if k not in ALLOWED}
    assert guarded == GUARDED, (guarded ^ GUARDED)


def test_outside_the_working_factory_every_write_is_refused_before_the_factory():
    root = tc.factory_tree()
    wt = worktree_of(root)
    _, c = make(wt)
    before = sorted(p.relative_to(wt).as_posix() for p in wt.rglob("*") if ".git" not in p.parts)
    with Spy() as spy:
        for m, path in sorted(GUARDED):
            # an empty body: the guard answers before the body is even validated
            r = c.request(m, filled(path), headers=H, json={})
            assert_refused(r, "это рабочая копия разработки")
        # a well-formed one too - the switch the live smoke sends
        assert_refused(c.post("/api/schedule/switch", headers=H, json={"on": False, "note": ""}),
                       "это рабочая копия разработки")
        r = c.post("/api/channels", headers=H, json=NEW)      # a real create
        assert_refused(r, "это рабочая копия разработки")
    assert spy.calls == [], spy.calls
    after = sorted(p.relative_to(wt).as_posix() for p in wt.rglob("*") if ".git" not in p.parts)
    assert after == before
    assert git(wt, "status", "--porcelain") == ""


def test_the_main_checkout_on_main_writes():
    root = tc.factory_tree()
    _, c = make(root)
    h = c.get("/api/health").json()
    assert (h["writes"], h["writes_reason"], h["writes_dev"]) == (True, None, False), h
    with Spy(through=True) as spy:
        for m, path in sorted(GUARDED):
            r = c.request(m, filled(path), headers=H, json={})
            # past the guard: the route's own body check (422) or the (spied) factory
            assert r.status_code in (422, 503), (path, r.status_code, r.text)
            if r.status_code == 503:
                assert r.json()["message"].startswith("spy: "), r.text
        r = c.post("/api/schedule/switch", headers=H, json={"on": False, "note": ""})
        assert r.status_code == 503, r.text
    assert {"switch", "save", "revert", "stop_plan", "resume_plan", "set_settings",
            "resolve_question"} <= set(spy.calls), spy.calls
    # a real write goes through: the channel's edit, one commit
    d = c.get("/api/channels/reel").json()
    r = c.put("/api/channels/reel", headers=H, json={
        "base": d["revision"], "config_text": tc.edit_text(d["config_text"], '"en"', '"de"')})
    assert r.status_code == 200, r.text
    assert '"de"' in (root / "channels" / "reel.json").read_text()


def test_another_branch_is_refused():
    root = tc.factory_tree()
    git(root, "checkout", "-q", "-b", "feature")
    _, c = make(root)
    h = c.get("/api/health").json()
    assert h["writes"] is False and h["writes_reason"] == "основной чекаут не на main (feature)"
    with Spy() as spy:
        assert_refused(c.put("/api/channels/reel", headers=H, json={"config_text": "{}"}),
                       "основной чекаут не на main")
    assert spy.calls == []


def test_a_detached_head_is_refused():
    root = tc.factory_tree()
    git(root, "checkout", "-q", "--detach")
    _, c = make(root)
    assert c.get("/api/health").json()["writes_reason"].startswith("HEAD отделён")
    with Spy() as spy:
        assert_refused(c.post("/api/batches/launch/plan", headers=H, json={"channel": "reel"}),
                       "HEAD отделён")
    assert spy.calls == []


def test_no_git_is_refused():
    root = TMP / "no-git"
    (root / "channels").mkdir(parents=True)
    _, c = make(root)
    with Spy() as spy:
        assert_refused(c.post("/api/questions/Q1/answer", headers=H, json={"text": "да"}),
                       "не git-репозиторий")
    assert spy.calls == []


def test_the_dev_flag_writes_and_says_so():
    root = tc.factory_tree()
    wt = worktree_of(root, "devflag")
    got = []

    class Catch(logging.Handler):
        def emit(self, record):
            got.append(record.getMessage())

    h = Catch(level=logging.WARNING)
    WRITES_LOG.addHandler(h)
    try:
        _, c = make(wt, writes_dev=True)
        assert any("CC_API_WRITES=dev" in g and "flag is on" in g for g in got), got  # the start
        hl = c.get("/api/health").json()
        assert hl["writes"] is True and hl["writes_dev"] is True, hl
        assert hl["writes_reason"].startswith("это рабочая копия разработки"), hl
        v = c.get("/api/version").json()
        assert (v["writes"], v["writes_dev"]) == (True, True) and v["writes_reason"], v
        got.clear()
        d = c.get("/api/channels/reel").json()
        r = c.put("/api/channels/reel", headers=H, json={
            "base": d["revision"], "config_text": tc.edit_text(d["config_text"], '"en"', '"de"')})
        assert r.status_code == 200, r.text
        assert any("PUT /api/channels/reel" in g for g in got), got          # every write
    finally:
        WRITES_LOG.removeHandler(h)


def test_check_and_a_dry_run_answer_everywhere():
    root = tc.factory_tree()
    git(root, "checkout", "-q", "-b", "elsewhere")
    for tree in (root, worktree_of(root, "reads")):
        _, c = make(tree)
        assert c.get("/api/health").json()["writes"] is False
        text = (tree / "channels" / "reel.json").read_text()
        r = c.post("/api/channels/reel/check", headers=H,
                   json={"config_text": tc.edit_text(text, '"en"', '"de"')})
        assert r.status_code == 200, r.text
        r = c.post("/api/channels", headers=H, json={**NEW, "dry_run": True})
        assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
        assert not (tree / "channels" / "history.json").exists()
        for get in ("/api/channels", "/api/channels/reel", "/api/schedule", "/api/version"):
            assert c.get(get).status_code == 200, get


# --------------------------------------------------------------------- settings, the kept answer
def test_the_flag_is_dev_or_nothing():
    assert Settings.from_env({}).writes_dev is False
    assert Settings.from_env({"CC_API_WRITES": ""}).writes_dev is False
    assert Settings.from_env({"CC_API_WRITES": "dev"}).writes_dev is True
    for bad in ("1", "yes", "true", "DEV"):
        try:
            Settings.from_env({"CC_API_WRITES": bad})
        except SettingsError as e:
            assert "CC_API_WRITES" in str(e)
        else:
            raise AssertionError(f"CC_API_WRITES={bad!r} accepted")


def test_the_answer_is_kept_a_few_seconds_only():
    root = tc.factory_tree()
    factory.forget_working_factory()
    assert factory.working_factory(root, now=100.0) == (True, "")
    git(root, "checkout", "-q", "-b", "moved")
    assert factory.working_factory(root, now=101.0) == (True, ""), "kept within the TTL"
    t = 100.0 + factory.WORKING_FACTORY_TTL_S + 0.1
    assert factory.working_factory(root, now=t) == (False, "основной чекаут не на main (moved)")
    assert 0 < factory.WORKING_FACTORY_TTL_S <= 30


def test_a_rule_that_fails_is_a_no():
    real = factory.agents_lock

    class Broken:
        @staticmethod
        def is_working_factory(root):
            raise OSError("git is gone")

    factory.forget_working_factory()
    factory.agents_lock = lambda: Broken
    try:
        ok, why = factory.working_factory(TMP)
    finally:
        factory.agents_lock = real
        factory.forget_working_factory()
    assert ok is False and "git is gone" in why, why


def test_the_contract_carries_the_fields_and_the_problem():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    s = spec["components"]["schemas"]
    for m in ("Health", "Version"):
        assert {"writes", "writes_reason", "writes_dev"} <= set(s[m]["required"]), s[m]
    code = s["WritesProblem"]["properties"]["code"]
    assert code.get("enum", [code.get("const")]) == ["not_working_factory"], code
    assert sorted(s["WritesProblem"]["required"]) == ["code", "details", "message"]
    for m, path in GUARDED | {("POST", "/api/channels")}:
        schema = spec["paths"][path][m.lower()]["responses"]["409"]["content"][
            "application/json"]["schema"]
        refs = [x["$ref"] for x in schema.get("anyOf", [schema])]
        assert any(x.endswith("/WritesProblem") for x in refs), (m, path, refs)


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

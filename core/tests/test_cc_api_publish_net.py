#!/usr/bin/env python3
"""CC-0066: the publication writes of the command center's API that may reach
beyond this machine (`api/publish_net.py`), plan -> confirm as CC-0065's:

    POST /api/publish/{c}/api-upload/switch/plan | switch   api_switch.set_switch
    POST /api/publish/{c}/upload/plan | upload              upload.run (dry run | real)
    POST /api/publish/{c}/studio/record/plan | record       studio_fields.record

In-process (starlette's TestClient) against stand-in factory roots in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`). **Nothing leaves the
machine and nothing outside the temp dir is written**: every test runs with
the network refused (`no_network` of CC-0065's tests: a socket that connects
or resolves raises and is written down; no child process but git), the
clock is fixed, the publisher's `.env` is a temp file, the YouTube client is
a stand-in (`FACTORY_KW["client_factory"]`), `publisher_auth.load_credentials`
is a stub that fails the test if it is called, and the notification bus
(`notify`) is a stand-in that writes down every send.

What is pinned: the switch's plan writes nothing and carries the warnings;
turning it on takes a note and «аудит подтверждаю» (else 422, nothing
written); off takes neither; a no-pipeline channel and «already so» get no
token; a moved state file is `check_changed`. The upload's plan refuses
while the switch is off (the factory's line) and never makes a client; the
confirm takes the user's «да» (else 422 before the token is spent), runs
`upload.run` with the stand-in client - the switch gate and the card gate
are the factory's - and writes the journal row, the note's record, the
README row; a client of another channel uploads nothing. The Studio record
writes the row once, its plan shows the mismatches; no notification is sent.
A read-only copy refuses all six before the factory.
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

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import TMP, _w, client, factory_tree, git          # noqa: E402
from test_cc_api_publish import (DESCRIPTION, SLUG, TAGS, TITLE, _names,      # noqa: E402
                                 card_text, files, setup, world)
from test_cc_api_publish_writes import head, no_network, post                # noqa: E402

from api import factory, publish, publish_net                               # noqa: E402

AUDIT = "аудит подтверждаю"
NOTE = "пройден аудит YouTube API, письмо от 2026-10-05"


CHANNEL_ID = "UCtestchannelreel"
VID = "NEWVID12345"


class Req:
    """A resumable request of the stand-in client: one chunk, YouTube's answer."""

    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def next_chunk(self):
        self.calls += 1
        return None, self.answer


class Client:
    def __init__(self, ids=(CHANNEL_ID,)):
        self.ids, self.calls = list(ids), []

    def my_channel_ids(self):
        self.calls.append("channels")
        return self.ids

    def insert_request(self, video, body):
        self.calls.append(("insert", Path(video).name, body))
        return Req({"id": VID, "status": {"privacyStatus": "private",
                                          "publishAt": body["status"]["publishAt"]}})


class Factory:
    """`upload.run`'s `client_factory`: the stand-in client, counted."""

    def __init__(self, client=None, raises=None):
        self.client, self.raises, self.made = client or Client(), raises, []

    def __call__(self, cfg, authorize=False):
        self.made.append((cfg.channel_id, authorize))
        if self.raises is not None:
            raise self.raises
        return self.client


class stubs:
    """The publisher's credentials and the notification bus, stood in: a call
    of `publisher_auth.load_credentials` is written down and raises; every
    `notify.send` (the stand-in module, and the real one's if it is loaded) is
    written down and sends nothing."""

    def __enter__(self):
        import types
        self.auth = factory.collect().auth()
        self.saved_auth = self.auth.load_credentials
        self.creds, self.sent = [], []

        def no_creds(*a, **k):
            self.creds.append((a, k))
            raise AssertionError("publisher_auth.load_credentials called in a test")

        def send(*a, **k):
            self.sent.append((a, k))
            return {"status": "stub"}
        self.auth.load_credentials = no_creds
        self.real = sys.modules.get("notify")
        self.saved_send = {}
        if self.real is not None:
            for name in ("send", "on_token"):
                if hasattr(self.real, name):
                    self.saved_send[name] = getattr(self.real, name)
                    setattr(self.real, name, send)
        else:
            stub = types.ModuleType("notify")
            stub.send = stub.on_token = send
            sys.modules["notify"] = stub
        return self

    def __exit__(self, *exc):
        self.auth.load_credentials = self.saved_auth
        if self.real is not None:
            for name, f in self.saved_send.items():
                setattr(self.real, name, f)
        else:
            sys.modules.pop("notify", None)


def upload_world(on=True):
    """reel: the placed accepted card of test_cc_api_publish's world, publish/README.md,
    a temp .env with the channel id, the switch on (by the user, the CLI's way)."""
    root = world()
    (root / "publish" / "README.md").write_text(
        "# Ролики для публикации\n\n| ролик | батч | вердикт пользователя |\n|---|---|---|\n",
        encoding="utf-8")
    env = Path(publish.FACTORY_KW["env_file"])
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text(f"PUBLISHER_CLIENT_SECRET_FILE={env.parent}/client_secret.json\n"
                   f"PUBLISHER_TOKEN_FILE={env.parent}/token.json\n"
                   f"PUBLISHER_CHANNEL_ID={CHANNEL_ID}\n", encoding="utf-8")
    if on:
        factory.collect().api_switch().set_switch(
            "reel", True, "user", "тест: после аудита", root=root, env_file=str(env), environ={},
            timer={"installed": True})
    return root


def journal(root):
    return json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))["uploads"]


def switch_file(root):
    p = root / "schedule" / "api-upload.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# --------------------------------------------------------------------- the switch
def test_the_switch_on_takes_a_note_and_the_audit_words_off_takes_neither():
    setup()
    root = factory_tree()
    c = client(root)
    h0 = head(root)
    before = files(root)
    with no_network() as nn:
        code, r = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": " "})
        assert code == 422 and r["code"] == "note_required", r
        code, plan = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": NOTE})
        assert code == 200 and plan["ok"] and plan["confirm"], plan
        assert (plan["action"], plan["channel"], plan["on"], plan["state"]["on"]) == \
            ("api_upload_switch", "reel", True, False), plan
        assert plan["row"] == {"channel": "reel", "on": True, "by": "user",
                               "note": f"{NOTE} (из центра)"}, plan
        assert plan["audit_phrase"] == AUDIT and plan["path"] == "schedule/api-upload.json"
        w = " | ".join(plan["warnings"])
        assert "Testing" in w and "подставной" in w and "нет токена" in w, plan["warnings"]
        assert files(root) == before, "a plan writes nothing"
        # without the words (or with others): 422, nothing written, the token spent
        for audit in (None, "да", "аудит"):
            code, r = post(c, "/api/publish/reel/api-upload/switch",
                           {"confirm": plan["confirm"], "audit": audit})
            if audit is None:
                assert code == 422 and r["code"] == "audit_unconfirmed", r
                assert AUDIT in r["message"], r
            else:
                assert code == 409 and r["code"] == "confirm_unknown", r
        assert switch_file(root) is None
        # with them (any case, any spaces): on, a history row by the user with the warnings
        code, plan = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": NOTE})
        code, done = post(c, "/api/publish/reel/api-upload/switch",
                          {"confirm": plan["confirm"], "audit": "  Аудит   ПОДТВЕРЖДАЮ "})
        assert code == 200, done
        assert done["on"] is True and done["changed"] is True and done["state"]["on"], done
        assert "ВКЛЮЧЕНА" in done["state"]["line"], done
        doc = switch_file(root)
        assert doc["channels"]["reel"]["on"] is True and doc["channels"]["reel"]["by"] == "user"
        row = doc["history"][-1]
        assert (row["action"], row["by"], row["note"], row["task"]) == \
            ("enable", "user", f"{NOTE} (из центра)", "CF-0607"), row
        assert row["warnings"] == plan["warnings"] == done["warnings"], row
        # on already: no token
        code, again = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": NOTE})
        assert code == 200 and not again["ok"] and again["confirm"] is None, again
        assert "уже включена" in again["why"], again
        # off: no note, no words, no warnings
        code, plan = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": False})
        assert code == 200 and plan["ok"] and plan["warnings"] is None, plan
        assert plan["audit_phrase"] is None and plan["row"]["note"] == "из центра", plan
        code, done = post(c, "/api/publish/reel/api-upload/switch", {"confirm": plan["confirm"]})
        assert code == 200 and done["on"] is False and done["changed"], done
        doc = switch_file(root)
        assert doc["channels"]["reel"]["on"] is False and len(doc["history"]) == 2, doc
        assert doc["history"][-1]["action"] == "disable"
        # a channel with no pipeline is not turned on; an unknown one is 404
        code, r = post(c, "/api/publish/demo/api-upload/switch/plan", {"on": True, "note": NOTE})
        assert code == 200 and not r["ok"] and "нечего грузить" in r["why"], r
        code, r = post(c, "/api/publish/nope/api-upload/switch/plan", {"on": True, "note": NOTE})
        assert code == 404 and r["code"] == "unknown_channel", r
    assert nn.net == [], nn.net
    assert all(Path(str(p[0])).name == "git" for p in nn.procs), nn.procs
    assert head(root) == h0, "the switch is state, not a commit"


def test_the_switch_whose_file_moved_is_check_changed_and_a_broken_file_409():
    setup()
    root = factory_tree()
    c = client(root)
    sw = factory.collect().api_switch()
    kw = dict(root=root, env_file=publish.FACTORY_KW["env_file"], environ={},
              timer={"installed": True})
    with no_network() as nn:
        code, plan = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": NOTE})
        assert plan["ok"], plan
        # the CLI turned it on and off meanwhile: the history moved, the state is the same
        sw.set_switch("reel", True, "user", "из терминала", **kw)
        sw.set_switch("reel", False, "operator", None, **kw)
        moved = switch_file(root)
        code, r = post(c, "/api/publish/reel/api-upload/switch",
                       {"confirm": plan["confirm"], "audit": AUDIT})
        assert code == 409 and r["code"] == "check_changed", r
        assert switch_file(root) == moved
        # a token of another action or channel
        code, plan = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": NOTE})
        code, r = post(c, "/api/publish/reel/pause/set", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        code, p = post(c, "/api/publish/reel/pause/set/plan", {"reason": "нарушение, смотрим"})
        code, r = post(c, "/api/publish/reel/api-upload/switch",
                       {"confirm": p["confirm"], "audit": AUDIT})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        assert switch_file(root) == moved
        # a state file that does not read: 409 with the factory's line, nothing written
        (root / "schedule" / "api-upload.json").write_text("{", encoding="utf-8")
        code, r = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": False})
        assert code == 409 and r["code"] == "switch_unreadable", r
        assert "ВЫКЛЮЧЕННОЙ" in r["message"], r
    assert nn.net == [], nn.net


# --------------------------------------------------------------------- the upload
def test_the_upload_plan_waits_for_the_switch_and_never_makes_a_client():
    setup()
    f = Factory()
    publish.FACTORY_KW.update(client_factory=f, sleep=lambda s: None)
    with stubs() as sb, no_network() as nn:
        root = upload_world(on=False)
        c = client(root)
        before = files(root)
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
        assert "API-загрузка для reel выключена" in plan["why"] and not plan["switch"]["on"], plan
        assert plan["summary"] is None and plan["dry_run"] == [], plan
        factory.collect().api_switch().set_switch(
            "reel", True, "user", "тест", root=root, env_file=publish.FACTORY_KW["env_file"],
            environ={}, timer={"installed": True})
        before = files(root)
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        assert code == 200 and plan["ok"] and plan["confirm"], plan
        assert (plan["action"], plan["slug"], plan["day"], plan["entry_id"]) == \
            ("api_upload", SLUG, "2026-10-08", f"reel/2026-10-05T0900Z/{SLUG}"), plan
        assert plan["note"] == f"publish/reel/2026-10-08/{SLUG}.md" and plan["switch"]["on"]
        assert plan["body"]["status"] == {"privacyStatus": "private",
                                          "publishAt": "2026-10-07T22:00:00Z",
                                          "selfDeclaredMadeForKids": False,
                                          "containsSyntheticMedia": False}, plan["body"]
        assert plan["publish_at"] == "2026-10-07T22:00:00Z" and plan["channel_id"] == CHANNEL_ID
        assert SLUG in plan["summary"] and CHANNEL_ID in plan["summary"], plan["summary"]
        assert "YouTube Terms of Service" in plan["tos_notice"] and "«да»" in plan["question"]
        assert "нет токена" in plan["token"], plan["token"]
        assert plan["dry_run"][-1] == "dry run: nothing sent, no credentials read", plan
        assert files(root) == before, "a plan writes nothing"
        # a slug that is not there; a bad day
        code, r = post(c, "/api/publish/reel/upload/plan", {"slug": "nope"})
        assert code == 404 and r["code"] == "unknown_note", r
        code, r = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG, "day": "вчера"})
        assert code == 404 and r["code"] == "unknown_note", r
    assert f.made == [] and sb.creds == [] and sb.sent == [], (f.made, sb.creds, sb.sent)
    assert nn.net == [], nn.net


def test_the_upload_takes_the_user_s_yes_and_runs_upload_with_the_stand_in_client():
    setup()
    f = Factory()
    publish.FACTORY_KW.update(client_factory=f, sleep=lambda s: None)
    with stubs() as sb, no_network() as nn:
        root = upload_world()
        c = client(root)
        h0 = head(root)
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        assert plan["ok"], plan
        before = files(root)
        # no «да»: 422, the token is not spent, nothing called
        for answer in ("", "ок", "давай"):
            code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                          "answer": answer})
            assert code == 422 and r["code"] == "answer_required", r
        code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"]})
        assert code == 422, r                       # the answer is required by the model
        assert files(root) == before and f.made == []
        code, done = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                         "answer": " Да "})
        assert code == 200, done
        assert f.made == [(CHANNEL_ID, False)], f.made
        assert [x if isinstance(x, str) else x[:2] for x in f.client.calls] == \
            ["channels", ("insert", f"{SLUG}.mp4")], f.client.calls
        assert f.client.calls[1][2] == plan["body"], "the body of the plan is the one sent"
        row = done["row"]
        assert (row["video_id"], row["source"], row["entry_id"], row["channel"]) == \
            (VID, "api", plan["entry_id"], "reel"), row
        assert row["confirmed"]["answer"] == "Да" and row["publish_at"] == "2026-10-07T22:00:00Z"
        assert [r for r in journal(root) if r.get("video_id") == VID] == [row]
        assert done["shown"].startswith(plan["summary"].rstrip()), done["shown"]
        assert "YouTube Terms of Service" in done["shown"] and "Введите «да»" in done["shown"]
        assert any(ln.startswith(f"uploaded: ") and VID in ln for ln in done["lines"]), done
        note = (root / "publish" / "reel" / "2026-10-08" / f"{SLUG}.md").read_text(
            encoding="utf-8")
        assert VID in note, "the note carries the record"
        assert VID in (root / "publish" / "README.md").read_text(encoding="utf-8")
        # the token is spent; a new plan: already uploaded, no token
        code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                      "answer": "да"})
        assert code == 409 and r["code"] == "confirm_unknown", r
        code, again = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        assert code == 200 and not again["ok"] and "already uploaded" in again["why"], again
        # CC-0153: one commit of what the upload wrote - the journal, the note, the README
        assert git(root, "rev-parse", "HEAD~1") == h0, "one commit on top"
        msg = git(root, "log", "-1", "--format=%B")
        assert "Cc-Action: api_upload" in msg and "Cc-Channel: reel" in msg, msg
        mine = ["publish/uploads.json", "publish/README.md",
                f"publish/reel/2026-10-08/{SLUG}.md"]
        assert set(mine) <= set(git(root, "show", "--name-only", "--format=",
                                    "HEAD").splitlines())
        assert git(root, "status", "--porcelain", "--untracked-files=all", "--", *mine) == ""
    assert sb.creds == [] and sb.sent == [], (sb.creds, sb.sent)
    assert nn.net == [], nn.net
    assert all(Path(str(p[0])).name in ("git", "ffprobe") for p in nn.procs), nn.procs


def test_the_upload_refusals_a_switch_turned_off_and_a_world_that_moved():
    setup()
    publish.FACTORY_KW.update(sleep=lambda s: None)
    with stubs() as sb, no_network() as nn:
        root = upload_world()
        c = client(root)
        sw = factory.collect().api_switch()
        kw = dict(root=root, env_file=publish.FACTORY_KW["env_file"], environ={},
                  timer={"installed": True})
        # a client of another channel: refused before the question, nothing uploaded
        other = Factory(Client(ids=("UCsomeoneelse",)))
        publish.FACTORY_KW["client_factory"] = other
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        before = files(root)
        code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                      "answer": "да"})
        assert code == 409 and r["code"] == "refused" and "nothing uploaded" in r["message"], r
        assert other.client.calls == ["channels"] and files(root) == before
        # the token expired at Google: 409 reauthorize
        up = factory.upload()
        publish.FACTORY_KW["client_factory"] = Factory(
            raises=up.publisher_auth.ReauthorizeRequired("invalid_grant (подставной)"))
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                      "answer": "да"})
        assert code == 409 and r["code"] == "reauthorize", r
        f = Factory()
        publish.FACTORY_KW["client_factory"] = f
        # the switch turned off after the plan: the factory's refusal, no client made
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        sw.set_switch("reel", False, "operator", None, **kw)
        code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                      "answer": "да"})
        assert code == 409 and r["code"] == "refused" and "выключена" in r["message"], r
        sw.set_switch("reel", True, "user", "снова", **kw)
        # the journal moved under the plan: check_changed
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        jp = root / "publish" / "uploads.json"
        doc = json.loads(jp.read_text(encoding="utf-8"))
        doc["uploads"].append(dict(doc["uploads"][0], slug="another", video_id="AnOtHeRvId1",
                                   entry_id="reel/X/another"))
        _w(jp, doc)
        code, r = post(c, "/api/publish/reel/upload", {"confirm": plan["confirm"],
                                                      "answer": "да"})
        assert code == 409 and r["code"] == "check_changed", r
        assert f.made == []
        # a card that is not ready: the card gate's line in the plan, no token
        p = root / "publish" / "reel" / "2026-10-08" / f"{SLUG}.md"
        p.write_text(card_text(status="draft"), encoding="utf-8")
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        assert code == 200 and not plan["ok"] and "card is not ready" in plan["why"], plan
        # no README: the record would not land - no token
        p.write_text(card_text(), encoding="utf-8")
        (root / "publish" / "README.md").unlink()
        code, plan = post(c, "/api/publish/reel/upload/plan", {"slug": SLUG})
        assert code == 200 and not plan["ok"] and "README.md" in plan["why"], plan
    assert f.made == [] and sb.creds == [] and sb.sent == []
    assert nn.net == [], nn.net


# --------------------------------------------------------------------- the Studio record
STUDIO_VID = "StUdIoVid01"


def studio_read(**over):
    r = {"title": TITLE, "description": DESCRIPTION, "tags": list(TAGS),
         "visibility": "Запланировано",
         "schedule": {"date_text": "8 окт. 2026 г.", "time": "01:00",
                      "zone_text": "(GMT+03:00) Москва"},
         "url": f"https://youtube.com/shorts/{STUDIO_VID}"}
    r.update(over)
    return r


def test_the_studio_record_plan_shows_the_mismatches_then_the_confirm_writes_the_row_once():
    setup()
    with stubs() as sb, no_network() as nn:
        root = world()
        c = client(root)
        h0 = head(root)
        before = files(root)
        body = {"slug": SLUG, "video_id": STUDIO_VID, "read": studio_read(title="Something else")}
        code, plan = post(c, "/api/publish/reel/studio/record/plan", body)
        assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
        assert [m["field"] for m in plan["mismatches"]] == ["title"], plan["mismatches"]
        assert "ничего не записано" in plan["why"], plan
        # another video than the read names: the factory's refusal
        code, plan = post(c, "/api/publish/reel/studio/record/plan",
                          dict(body, read=studio_read(), video_id="AnOtHeRvId1"))
        assert code == 200 and not plan["ok"] and STUDIO_VID in plan["why"], plan
        code, plan = post(c, "/api/publish/reel/studio/record/plan", dict(body, read=studio_read()))
        assert code == 200 and plan["ok"] and plan["confirm"], plan
        assert (plan["action"], plan["status"], plan["day"], plan["mismatches"]) == \
            ("studio_record", "would-add", "2026-10-08", []), plan
        assert (plan["row"]["video_id"], plan["row"]["source"], plan["row"]["user_edited"]) == \
            (STUDIO_VID, "studio", False), plan["row"]
        assert files(root) == before, "a plan writes nothing"
        code, done = post(c, "/api/publish/reel/studio/record", {"confirm": plan["confirm"]})
        assert code == 200 and done["status"] == "added", done
        rows = [r for r in journal(root) if r.get("video_id") == STUDIO_VID]
        assert len(rows) == 1 and rows[0]["entry_id"] == f"reel/2026-10-05T0900Z/{SLUG}", rows
        assert rows[0]["source"] == "studio" and rows[0]["publish_at"] == \
            "2026-10-08T01:00:00+03:00", rows
        assert done["row"]["video_id"] == STUDIO_VID and done["streak"]["streak"] == 2, done
        # recorded: the plan of it again has nothing to write
        code, again = post(c, "/api/publish/reel/studio/record/plan", dict(body, read=studio_read()))
        assert code == 200 and not again["ok"] and "exists" in again["why"], again
        # CC-0153: the row is one commit of the journal - the tree stays clean there
        assert git(root, "rev-parse", "HEAD~1") == h0, "one commit on top"
        assert "Cc-Action: studio_record" in git(root, "log", "-1", "--format=%B")
        assert "publish/uploads.json" in git(root, "show", "--name-only", "--format=",
                                             "HEAD").splitlines()
        assert git(root, "status", "--porcelain", "--", "publish/uploads.json") == ""
    assert sb.sent == [] and sb.creds == [], (sb.sent, sb.creds)
    assert nn.net == [], nn.net


def test_the_studio_record_whose_journal_moved_is_check_changed():
    setup()
    with stubs() as sb, no_network() as nn:
        root = world()
        c = client(root)
        body = {"slug": SLUG, "video_id": STUDIO_VID, "read": studio_read()}
        code, plan = post(c, "/api/publish/reel/studio/record/plan", body)
        assert plan["ok"], plan
        jp = root / "publish" / "uploads.json"
        doc = json.loads(jp.read_text(encoding="utf-8"))
        doc["uploads"][0]["user_edited"] = False
        _w(jp, doc)
        moved = jp.read_bytes()
        code, r = post(c, "/api/publish/reel/studio/record", {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert jp.read_bytes() == moved
        # an upload plan's token is not a record's
        code, p = post(c, "/api/publish/reel/api-upload/switch/plan", {"on": True, "note": NOTE})
        code, r = post(c, "/api/publish/reel/studio/record", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        assert jp.read_bytes() == moved
    assert sb.sent == [] and nn.net == []


# --------------------------------------------------------------------- the module, a read-only copy
#: What `api/publish_net.py` never names: the bus, the credentials, the YouTube
#: client, a child process, a file of its own.
FORBIDDEN = {"notify", "send", "notify_upload", "_notify_bus", "notify_accept", "on_token",
             "load_credentials", "default_client", "YouTubeClient", "youtube_client_factory",
             "subprocess", "open", "write_text", "write_bytes", "unlink", "rename", "rmtree",
             "mkdir", "write_ledger", "resolve_rights_only", "clear_holds"}
#: Each writer, named only in its own functions.
WRITERS = {"set_switch": {"api_upload_switch"}, "run": {"_upload_check", "api_upload"},
           "record": {"_record_check", "studio_record"}}


def test_the_module_names_no_bus_no_credentials_and_each_writer_in_its_place():
    tree = ast.parse((ROOT / "api" / "publish_net.py").read_text(encoding="utf-8"))
    hit = _names(tree) & FORBIDDEN
    assert not hit, hit
    where = {}
    for node in tree.body:
        for w in _names(node) & set(WRITERS):
            where.setdefault(w, set()).add(getattr(node, "name", type(node).__name__))
    assert where == WRITERS, where
    # the plan's run is a dry run with the refusing client factory
    runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "run"]
    kws = [{k.arg: k.value for k in r.keywords} for r in runs]
    assert len(runs) == 2, runs
    assert any(isinstance(k.get("client_factory"), ast.Name)
               and k["client_factory"].id == "_no_client" for k in kws), kws


def test_a_read_only_copy_refuses_the_switch_the_upload_and_the_record_before_the_factory():
    setup()
    root = factory_tree()
    wt = TMP / f"wt-publish-net-{root.name}"
    git(root, "worktree", "add", "-q", "-b", "dev-publish-net", str(wt))
    c = client(wt)
    before = files(wt)
    called = []
    saved = {n: getattr(publish_net, n) for n in NET_FUNCS}
    for n in NET_FUNCS:
        setattr(publish_net, n, lambda *a, _n=n, **k: called.append(_n))
    try:
        for path in NET_ROUTES:
            code, r = post(c, path.replace("{channel}", "reel"), {})
            assert code == 409 and r["code"] == "not_working_factory", (path, r)
    finally:
        for n, f in saved.items():
            setattr(publish_net, n, f)
    assert called == []
    assert files(wt) == before


NET_FUNCS = ("api_upload_switch_plan", "api_upload_switch", "api_upload_plan", "api_upload",
             "studio_record_plan", "studio_record")
NET_ROUTES = tuple(f"/api/publish/{{channel}}/{a}{s}" for a in (
    "api-upload/switch", "upload", "studio/record") for s in ("/plan", ""))


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

#!/usr/bin/env python3
"""CC-0006: the channels of the command center's API (`api/channels.py`).

Everything runs in-process (starlette's TestClient) against a stand-in
factory: a temp git repository with two channels of its own - `reel` (a
pipeline, a position, a run plan, a `video_editor` block) and `demo` (a stub,
«конвейера нет») - and batch directories written by the test. The live
checkout's channels, pipeline and git are never read or written; the factory's
*code* (the validators, runlog) is this checkout's, as in production.

What is pinned:

* the factory's checks of one config are the table `validate_vocabulary`
  walks (`inserts/validate_inserts.py` CHANNEL_CHECKS / channel_config_errors),
  and a field's description is the config's own prose (`channel_fields`);
* reading: the list, a channel (its file byte for byte, its position, its
  fields with their notes and checks, the checks' verdict now, the lock);
* saving: check -> write -> one commit of the touched file(s) only, subject
  «Канал <имя>: изменено <поле> (из центра)»; another staged or modified file
  of the repo is neither committed nor touched; every refusal (invalid, not
  JSON, nothing changed, stale `base`, a hand edit not in git, `channel_id`
  changed) writes nothing and commits nothing, with a Russian message;
* the block: a batch of this channel (under a former id too) or a rebuild
  refuses the edit; another channel's batch or a stale one does not;
* history and revert: the commits of the channel's files, which of them are
  the center's, which can be reverted; a revert is a new commit that undoes one
  edit, checked like a save; an edit whose lines changed again, a commit with
  other files, an unknown commit are refused;
* the guard: a PUT without the session token is refused.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

from _tmproot import tmp_root                        # noqa: E402
from api import channels as ch                       # noqa: E402
from api import factory                              # noqa: E402
from api.app import SESSION_HEADER, create_app       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-channels-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
ch.BATCH_TTL = 0.0                     # the tests write batches between two calls:
ch.BATCH_WAIT = 600.0                  # every read rescans and waits for it (CC-0041)

THEME = {
    "bg": "#040C09", "accent": "#34D399", "accent2": "#C97A3D", "text": "#F5F1E9",
    "muted": "#B3C4B9", "card_ground": ["#0D3324", "#08201A", "#040C09"],
    "end_card_ground": ["#1D3E30", "#142B22", "#0C1A14"],
    "badge": {"paper": "#E3EADD", "ink": "#10261B", "ink_muted": "#5B7262", "rule": "#C0CEBC",
              "accent": "#C97A3D", "accent_ink": "#FFFFFF"},
    "font": {"display": "\"Arial Black\", \"Helvetica Neue\", sans-serif",
             "text": "\"Helvetica Neue\", Helvetica, Arial, sans-serif",
             "card": "Helvetica, Arial, sans-serif",
             "badge": "\"Courier Prime\", \"IBM Plex Mono\", monospace"},
    "note": "a stand-in palette",
}

RUN_PLAN = {
    "version": 1, "batch_dir": "pipeline/{channel}/{batch_id}",
    "stages": [{"id": "hello", "title": "a stand-in stage", "kind": "machine", "owner": "root",
                "marker": None, "role": None,
                "steps": [{"argv": ["python3", "{root}/scripts/hello.py"], "ok_exit": [0]}]}],
}


def reel_config():
    return {
        "channel_id": "reel", "former_channel_ids": ["old-reel"], "display_name": "Reel",
        "theme": THEME, "language": "en",
        "video_editor": {"note": "the editor's ceilings", "max_attempts_per_video": 3,
                         "max_attempts_per_video_note": "renders of one video before needs_you"},
        "stance": "reel/stance.json", "stance_note": "the position",
        "batch_schedule": {"enabled": False},
        "run_plan": json.loads(json.dumps(RUN_PLAN)),
    }


def demo_config():
    return {"channel_id": "demo", "display_name": "Demo", "theme": THEME,
            "status": "no_pipeline", "status_note": "a stub - its conveyor is milestone 9.9.9",
            "batch_schedule": {"enabled": False}}


STANCE = {"channel_id": "reel", "position": {"thesis": "one fact", "thesis_note": "why"}}


def git(root, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and cp.returncode != 0:
        raise AssertionError(f"git {args}: {cp.stderr}")
    return cp.stdout.strip()


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


_N = [0]


def factory_tree():
    """A stand-in factory root, one commit of everything."""
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    (root / "channels" / "reel").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "channels" / "reel.json").write_text(dump(reel_config()), encoding="utf-8")
    (root / "channels" / "reel" / "stance.json").write_text(dump(STANCE), encoding="utf-8")
    (root / "channels" / "demo.json").write_text(dump(demo_config()), encoding="utf-8")
    (root / "notes.md").write_text("other file\n", encoding="utf-8")
    (root / "agents.lock.json").write_text(json.dumps({"agents": {}, "links": {}}),
                                           encoding="utf-8")
    hooks = root.parent / f"no-hooks-{_N[0]}"
    hooks.mkdir()
    git(root.parent, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
        git(root, "config", k, v)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the start")
    return root


def client(root, writes_dev=False):
    # CC-0058: `writes_dev` is the developer's CC_API_WRITES=dev - only for a tree
    # that is no working factory on purpose (a test of the factory's own refusal)
    app = create_app(Settings(factory_root=root, writes_dev=writes_dev), token="tok")
    return TestClient(app, client=LOCAL, base_url=BASE)


H = {"Origin": BASE, SESSION_HEADER: "tok"}


def head(root):
    return git(root, "rev-parse", "HEAD")


def files_of(root, rev="HEAD"):
    return git(root, "show", "--name-only", "--format=", rev).splitlines()


def edit_text(text, old, new):
    assert old in text, old
    return text.replace(old, new, 1)


def write_batch(root, chan, batch="2026-10-10T0900Z", hours_ago=0.0, rebuild=False):
    d = root / "pipeline" / ("rebuilds" if rebuild else chan) / batch
    d.mkdir(parents=True, exist_ok=True)
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = {"ts": ts, "kind": "marker", "marker": "batch-start", "stage": "batch"}
    if rebuild:
        ev = {"ts": ts, "kind": "script", "status": "done", "id": "x"}
    (d / "RUN_EVENTS.jsonl").write_text(json.dumps(ev) + "\n", encoding="utf-8")
    return d


# --------------------------------------------------------------------- the contract

def test_the_contract_in_git_names_the_channel_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    want = {"/api/channels": ["get", "post"], "/api/channels/{channel}": ["get", "put"],
            "/api/channels/{channel}/check": ["post"],
            "/api/channels/{channel}/history": ["get"],
            "/api/channels/{channel}/history/{commit}/revert": ["post"]}
    for path, methods in want.items():
        assert path in spec["paths"], path
        assert sorted(spec["paths"][path]) == sorted(methods), (path, spec["paths"][path].keys())
        for m in methods:
            resp = spec["paths"][path][m]["responses"]
            assert "403" in resp, (path, m)
            if path != "/api/channels":
                schema = resp["409"]["content"]["application/json"]["schema"]
                got = sorted(s["$ref"].rsplit("/", 1)[1] for s in schema.get("anyOf", [schema]))
                # CC-0058: a write route's 409 may also be `not_working_factory`
                want = ["ChannelProblem"] + (["WritesProblem"] if m in ("put", "post")
                                             and not path.endswith("/check") else [])
                assert got == want, (path, m, got)
    codes = spec["components"]["schemas"]["ChannelProblem"]["properties"]["code"]["enum"]
    assert {"invalid", "batch_running", "conflict", "dirty", "not_revertible"} <= set(codes)


# --------------------------------------------------------------------- the factory's checks

def test_one_config_is_checked_by_the_table_validate_vocabulary_walks():
    vi = factory.validate_inserts()
    names = [c for _, c, _ in vi.CHANNEL_CHECKS]
    assert names[:3] == ["channel_theme_errors", "channel_source_policy_errors",
                         "no_pipeline_reason"], names
    for _, c, _ in vi.CHANNEL_CHECKS:
        assert callable(vi._channel_check(c)), c
    root = factory_tree()
    cfg = reel_config()
    path = root / "channels" / "reel.json"
    assert vi.channel_config_errors(cfg, path) == []
    cfg["video_editor"]["max_attempts_per_video"] = 0
    errs = vi.channel_config_errors(cfg, path)
    assert errs == vi._channel_check("validate_video_editor_block")(cfg, ctx="reel.json"), errs
    assert errs and errs[0].startswith("reel.json.video_editor.max_attempts_per_video:"), errs
    # a stub: its blocks are not checked, a half-stub is an error
    stub = demo_config()
    stub["video_editor"] = {"max_attempts_per_video": 0}
    assert vi.channel_config_errors(stub, root / "channels" / "demo.json") == []
    stub["run_plan"] = json.loads(json.dumps(RUN_PLAN))
    assert any("run_plan" in e for e in vi.channel_config_errors(stub, root / "channels/demo.json"))


def test_the_vocabulary_walk_says_what_the_table_says():
    vi = factory.validate_inserts()
    root = factory_tree()
    bad = reel_config()
    bad["video_editor"]["max_attempts_per_video"] = "three"
    (root / "channels" / "reel.json").write_text(dump(bad), encoding="utf-8")
    keep = vi.CHANNELS_DIR
    try:
        vi.CHANNELS_DIR = root / "channels"
        errs = vi.validate_vocabulary()
    finally:
        vi.CHANNELS_DIR = keep
    mine = vi.channel_config_errors(bad, root / "channels" / "reel.json")
    assert mine and all(e in errs for e in mine), (mine, errs)


def test_a_field_is_described_by_the_config_s_own_prose():
    rows = factory.config_fields(reel_config())
    by = {".".join(r["path"]): r for r in rows}
    r = by["video_editor.max_attempts_per_video"]
    assert r["note"] == "renders of one video before needs_you" and r["kind"] == "number"
    assert r["checked_by"] == ["validate_video_editor_block"] and not r["prose"]
    assert by["video_editor"]["note"] == "the editor's ceilings"
    assert by["video_editor.max_attempts_per_video_note"]["prose"] is True
    assert by["video_editor.note"]["prose"] is True
    assert by["theme"]["checked_by"] == ["channel_theme_errors"]
    assert by["theme.card_ground"]["kind"] == "array"
    assert "theme.card_ground.0" not in by          # an array is one field
    assert by["language"]["checked_by"] == [] and by["language"]["note"] is None


# --------------------------------------------------------------------- reading

def test_the_list_says_every_channel():
    root = factory_tree()
    r = client(root).get("/api/channels")
    assert r.status_code == 200, r.text
    rows = {c["id"]: c for c in r.json()["channels"]}
    assert set(rows) == {"demo", "reel"}
    assert rows["reel"]["display_name"] == "Reel" and rows["reel"]["former_ids"] == ["old-reel"]
    assert rows["reel"]["stance"] is True and rows["reel"]["no_pipeline"] is None
    assert rows["demo"]["no_pipeline"].startswith("конвейера нет") and not rows["demo"]["stance"]
    assert not rows["reel"]["locked"] and rows["reel"]["error"] is None


def test_a_channel_is_its_files_its_fields_its_checks_and_its_lock():
    root = factory_tree()
    c = client(root)
    r = c.get("/api/channels/reel")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["config_text"] == (root / "channels" / "reel.json").read_text(encoding="utf-8")
    assert d["config"] == reel_config() and d["stance"] == STANCE
    assert d["config_path"] == "channels/reel.json"
    assert d["stance_path"] == "channels/reel/stance.json"
    assert d["errors"] == [] and {k: d["lock"][k] for k in ("locked", "message", "batches")} \
        == {"locked": False, "message": None, "batches": []}
    assert {"block": "run_plan", "check": "run_plan.validate", "on_stub": False} in d["checks"]
    files = {(f["file"], ".".join(f["path"])) for f in d["fields"]}
    assert ("config", "video_editor.max_attempts_per_video") in files
    assert ("stance", "position.thesis") in files
    assert c.get("/api/channels/old-reel").json()["id"] == "reel"     # a former id
    nope = c.get("/api/channels/nope")
    assert nope.status_code == 404 and nope.json()["code"] == "unknown_channel"
    assert "нет" in nope.json()["message"]


def test_check_gives_the_factory_s_verdict_and_writes_nothing():
    root = factory_tree()
    c = client(root)
    before = (root / "channels" / "reel.json").read_bytes()
    bad = reel_config()
    bad["video_editor"]["max_attempts_per_video"] = 0
    r = c.post("/api/channels/reel/check", headers=H, json={"config": bad})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["ok"] is False
    assert v["errors"][0]["field"] == "video_editor.max_attempts_per_video", v
    bad = reel_config()
    bad["run_plan"]["stages"][0]["steps"][0]["argv"] = ["python3", "{root}/scripts/nope.py"]
    v = c.post("/api/channels/reel/check", headers=H, json={"config": bad}).json()
    assert not v["ok"] and v["errors"][0]["field"] == "run_plan", v
    assert c.post("/api/channels/reel/check", headers=H, json={}).json() == {"ok": True,
                                                                            "errors": []}
    assert (root / "channels" / "reel.json").read_bytes() == before


# --------------------------------------------------------------------- saving

def test_a_save_is_one_commit_of_the_channel_file_only():
    root = factory_tree()
    c = client(root)
    d = c.get("/api/channels/reel").json()
    # the rest of the repo: a modified file and a staged one, neither the center's
    (root / "notes.md").write_text("changed by hand\n", encoding="utf-8")
    (root / "staged.md").write_text("staged by hand\n", encoding="utf-8")
    git(root, "add", "staged.md")
    text = edit_text(d["config_text"], '"max_attempts_per_video": 3', '"max_attempts_per_video": 4')
    start = head(root)
    r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "config_text": text})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["subject"] == "Канал Reel: изменено video_editor.max_attempts_per_video (из центра)"
    assert s["changed"] == ["video_editor.max_attempts_per_video"]
    assert s["commit"] == head(root) and git(root, "rev-parse", "HEAD^") == start
    assert files_of(root) == ["channels/reel.json"]
    assert (root / "channels" / "reel.json").read_text(encoding="utf-8") == text   # as sent
    msg = git(root, "log", "-1", "--format=%B")
    assert "Cc-Channel: reel" in msg and "Cc-Action: edit" in msg
    st = git(root, "status", "--porcelain")
    assert "M notes.md" in st and "A  staged.md" in st, st
    assert (root / "notes.md").read_text(encoding="utf-8") == "changed by hand\n"
    assert s["channel"]["revision"] != d["revision"]
    assert git(root, "branch", "--show-current") == "main"


def test_the_commit_is_the_factory_s_helper():
    """CC-0057: a save is written and committed by `shared/runlog/git_commit.
    write_and_commit` (CF-0675), the message with its `Cc-*` trailers as is;
    a commit git refuses is `git_failed` with git's words, the file put back."""
    root = factory_tree()
    c = client(root)
    gc = factory.git_commit()
    assert Path(gc.__file__).resolve() == (ROOT / "shared" / "runlog" / "git_commit.py").resolve()
    seen, real = [], gc.write_and_commit
    gc.write_and_commit = lambda r, w, m: seen.append((r, sorted(map(str, w)), m)) or real(r, w, m)
    try:
        d = c.get("/api/channels/reel").json()
        text = edit_text(d["config_text"], '"max_attempts_per_video": 3',
                         '"max_attempts_per_video": 5')
        r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "config_text": text})
        assert r.status_code == 200, r.text
        assert len(seen) == 1 and seen[0][1] == [str(root / "channels" / "reel.json")], seen
        assert "Cc-Channel: reel" in seen[0][2] and r.json()["commit"] == head(root)
        hooks = Path(git(root, "config", "core.hooksPath"))
        (hooks / "pre-commit").write_text("#!/bin/sh\necho refused-by-hook >&2\nexit 1\n")
        (hooks / "pre-commit").chmod(0o755)
        d = c.get("/api/channels/reel").json()
        start, before = head(root), (root / "channels" / "reel.json").read_bytes()
        text = edit_text(d["config_text"], '"max_attempts_per_video": 5',
                         '"max_attempts_per_video": 6')
        r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "config_text": text})
        (hooks / "pre-commit").unlink()
        assert r.status_code == 500 and r.json()["code"] == "git_failed", r.text
        assert r.json()["details"][0].startswith("git commit ") and \
            "refused-by-hook" in r.json()["details"][1], r.json()["details"]
        assert (root / "channels" / "reel.json").read_bytes() == before and head(root) == start
        assert git(root, "status", "--porcelain") == ""
    finally:
        gc.write_and_commit = real


def test_an_object_save_and_a_position_save():
    root = factory_tree()
    c = client(root)
    d = c.get("/api/channels/reel").json()
    cfg = dict(d["config"], language="de")
    stance = json.loads(json.dumps(d["stance"]))
    stance["position"]["thesis"] = "two facts"
    r = c.put("/api/channels/reel", headers=H,
              json={"base": d["revision"], "config": cfg, "stance": stance, "note": "why"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["changed"] == ["language", "позиция.position.thesis"], s["changed"]
    assert sorted(files_of(root)) == ["channels/reel.json", "channels/reel/stance.json"]
    assert json.loads((root / "channels/reel/stance.json").read_text())["position"]["thesis"] \
        == "two facts"
    assert "why" in git(root, "log", "-1", "--format=%b")
    # the position alone
    d = s["channel"]
    st = edit_text(d["stance_text"], "two facts", "three facts")
    r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "stance_text": st})
    assert r.status_code == 200, r.text
    assert files_of(root) == ["channels/reel/stance.json"]
    assert r.json()["subject"] == "Канал Reel: изменено позиция.position.thesis (из центра)"
    # a stub has no position to save
    r = c.put("/api/channels/demo", headers=H, json={"stance": STANCE})
    assert r.status_code == 422 and r.json()["code"] == "no_stance"


def test_every_refusal_writes_nothing_and_commits_nothing():
    root = factory_tree()
    c = client(root)
    d = c.get("/api/channels/reel").json()
    start, before = head(root), (root / "channels" / "reel.json").read_bytes()

    def refused(body, status, code):
        r = c.put("/api/channels/reel", headers=H, json=body)
        assert r.status_code == status and r.json()["code"] == code, (code, r.status_code, r.text)
        assert head(root) == start, code
        assert (root / "channels" / "reel.json").read_bytes() == before, code
        msg = r.json()["message"]
        assert msg and any("а" <= ch_ <= "я" for ch_ in msg.lower()), msg      # Russian
        return r.json()

    text = d["config_text"]
    bad = refused({"base": d["revision"], "config_text": edit_text(
        text, '"max_attempts_per_video": 3', '"max_attempts_per_video": 0')}, 422, "invalid")
    assert bad["errors"][0]["field"] == "video_editor.max_attempts_per_video", bad
    assert bad["details"] and "must be an integer" in bad["details"][0]
    refused({"base": d["revision"], "config_text": text[:-5]}, 422, "not_json")
    refused({"base": d["revision"], "config_text": "[1, 2]"}, 422, "not_json")
    refused({"base": d["revision"], "config_text": text}, 400, "nothing_changed")
    refused({"base": "0" * 16, "config_text": edit_text(text, '"en"', '"de"')}, 409, "conflict")
    refused({"base": d["revision"], "config_text": edit_text(
        text, '"channel_id": "reel"', '"channel_id": "reel2"')}, 422, "forbidden_change")
    refused({"base": d["revision"], "config_text": edit_text(
        text, '"reel/stance.json"', '"reel/other.json"')}, 422, "forbidden_change")
    # a hand edit git does not have: never overwritten, never committed
    hand = edit_text(text, '"language": "en"', '"language": "fr"')
    (root / "channels" / "reel.json").write_text(hand, encoding="utf-8")
    before = hand.encode("utf-8")
    d2 = c.get("/api/channels/reel").json()
    dirty = refused({"base": d2["revision"], "config_text": edit_text(hand, '"fr"', '"de"')},
                    409, "dirty")
    assert any("channels/reel.json" in x for x in dirty["details"]), dirty


def test_outside_git_a_save_is_refused():
    root = factory_tree()
    import shutil
    shutil.rmtree(root / ".git")
    edit = {"config_text": edit_text((root / "channels" / "reel.json").read_text(), '"en"',
                                     '"de"')}
    # CC-0058: no git -> no working factory: the API refuses before the factory is asked
    r = client(root).put("/api/channels/reel", headers=H, json=edit)
    assert r.status_code == 409 and r.json()["code"] == "not_working_factory", r.text
    assert r.json()["message"].startswith("Только смотреть: не git-репозиторий"), r.text
    # with the developer's flag the write goes on - and the factory's own refusal holds
    c = client(root, writes_dev=True)
    d = c.get("/api/channels/reel").json()
    r = c.put("/api/channels/reel", headers=H, json={**edit, "base": d["revision"]})
    assert r.status_code == 500 and r.json()["code"] == "not_a_repo", r.text
    assert '"en"' in (root / "channels" / "reel.json").read_text()


def test_a_save_needs_the_session():
    root = factory_tree()
    c = client(root)
    r = c.put("/api/channels/reel", headers={"Origin": BASE}, json={"config_text": "{}"})
    assert r.status_code == 403 and r.json()["guard"] == "session"


# --------------------------------------------------------------------- the block

def test_a_batch_of_this_channel_blocks_the_edit():
    root = factory_tree()
    c = client(root)
    d = c.get("/api/channels/reel").json()
    body = {"base": d["revision"], "config_text": edit_text(d["config_text"], '"en"', '"de"')}
    start = head(root)
    for chan in ("reel", "old-reel"):                  # a former id is the same channel
        bdir = write_batch(root, chan)
        r = c.put("/api/channels/reel", headers=H, json=body)
        assert r.status_code == 409 and r.json()["code"] == "batch_running", r.text
        assert "Идёт батч канала reel" in r.json()["message"], r.json()
        assert r.json()["batches"][0]["channel"] == "reel"
        lk = c.get("/api/channels/reel").json()["lock"]
        assert lk["locked"] and lk["batches"][0]["dir"] == str(bdir)
        assert c.get("/api/channels").json()["channels"][1]["locked"] is True
        (bdir / "RUN_EVENTS.jsonl").write_text(
            (bdir / "RUN_EVENTS.jsonl").read_text() + json.dumps(
                {"ts": "2026-10-10T10:00:00Z", "kind": "marker", "marker": "batch-done"}) + "\n")
    assert head(root) == start
    # another channel's batch, a stale one: not this channel's block
    write_batch(root, "demo", batch="b-demo")
    write_batch(root, "reel", batch="b-stale", hours_ago=48)
    assert not c.get("/api/channels/reel").json()["lock"]["locked"]
    assert c.get("/api/channels/demo").json()["lock"]["locked"]
    r = c.put("/api/channels/reel", headers=H, json=body)
    assert r.status_code == 200, r.text


def test_a_rebuild_blocks_every_channel():
    root = factory_tree()
    c = client(root)
    write_batch(root, None, batch="2026-10-10T0800Z", rebuild=True)
    lk = c.get("/api/channels/reel").json()["lock"]
    assert lk["locked"] and lk["batches"][0]["rebuild"] and "пересборка" in lk["message"]
    d = c.get("/api/channels/demo").json()
    r = c.put("/api/channels/demo", headers=H, json={
        "base": d["revision"], "config_text": edit_text(d["config_text"], '"Demo"', '"Demo 2"')})
    assert r.status_code == 409 and r.json()["code"] == "batch_running"


# --------------------------------------------------------------------- history and revert

def _save(c, root, old, new, field="config_text"):
    d = c.get("/api/channels/reel").json()
    r = c.put("/api/channels/reel", headers=H,
              json={"base": d["revision"], field: edit_text(d[field], old, new)})
    assert r.status_code == 200, r.text
    return r.json()


def test_history_says_whose_edits_and_what_can_be_reverted():
    root = factory_tree()
    c = client(root)
    a = _save(c, root, '"en"', '"de"')
    # a hand commit with another file of the factory
    cfg = (root / "channels" / "reel.json").read_text()
    (root / "channels" / "reel.json").write_text(edit_text(cfg, '"Reel"', '"Reel!"'))
    (root / "notes.md").write_text("with it\n")
    git(root, "commit", "-q", "-am", "by hand")
    hand = head(root)
    h = c.get("/api/channels/reel/history").json()
    assert h["files"] == ["channels/reel.json", "channels/reel/stance.json"]
    e = h["entries"]
    assert [x["commit"] for x in e] == [hand, a["commit"], git(root, "rev-list", "--max-parents=0",
                                                                "HEAD")]
    assert e[0]["from_center"] is False and e[0]["revertible"] is False and e[0]["why_not"]
    assert sorted(e[0]["files"]) == ["channels/reel.json", "notes.md"]
    assert e[1]["from_center"] and e[1]["action"] == "edit" and e[1]["revertible"]
    assert e[1]["subject"] == a["subject"]
    assert c.get("/api/channels/reel/history?limit=1").json()["entries"][0]["commit"] == hand
    assert c.get("/api/channels/reel/history?limit=0").status_code == 422


def test_revert_undoes_one_edit_by_a_new_commit():
    root = factory_tree()
    c = client(root)
    a = _save(c, root, '"en"', '"de"')
    b = _save(c, root, '"max_attempts_per_video": 3', '"max_attempts_per_video": 5')
    d = c.get("/api/channels/reel").json()
    r = c.post(f"/api/channels/reel/history/{a['commit'][:10]}/revert", headers=H,
               json={"base": d["revision"]})
    assert r.status_code == 200, r.text
    v = r.json()
    short = git(root, "rev-parse", "--short", a["commit"])
    assert v["subject"] == f"Канал Reel: возвращено language - отмена правки {short} (из центра)"
    assert v["changed"] == ["language"] and files_of(root) == ["channels/reel.json"]
    cfg = json.loads((root / "channels" / "reel.json").read_text())
    assert cfg["language"] == "en" and cfg["video_editor"]["max_attempts_per_video"] == 5
    msg = git(root, "log", "-1", "--format=%B")
    assert f"Cc-Reverts: {a['commit']}" in msg and "Cc-Action: revert" in msg
    e = {x["commit"]: x for x in c.get("/api/channels/reel/history").json()["entries"]}
    assert e[a["commit"]]["reverted_by"] == v["commit"] and not e[a["commit"]]["revertible"]
    assert e[v["commit"]]["action"] == "revert" and e[v["commit"]]["reverts"] == a["commit"]
    assert e[b["commit"]]["revertible"]


def test_a_revert_that_cannot_stand_alone_is_refused():
    root = factory_tree()
    c = client(root)
    a = _save(c, root, '"en"', '"de"')
    _save(c, root, '"de"', '"fr"')                  # the same line again
    start = head(root)
    r = c.post(f"/api/channels/reel/history/{a['commit']}/revert", headers=H)
    assert r.status_code == 409 and r.json()["code"] == "not_revertible", r.text
    assert "более поздние" in r.json()["message"]
    # a commit with other files of the factory
    (root / "notes.md").write_text("x\n")
    cfg = (root / "channels" / "reel.json").read_text()
    (root / "channels" / "reel.json").write_text(edit_text(cfg, '"Reel"', '"Reel!"'))
    git(root, "commit", "-q", "-am", "by hand")
    hand = head(root)
    r = c.post(f"/api/channels/reel/history/{hand}/revert", headers=H)
    assert r.status_code == 409 and r.json()["code"] == "not_revertible"
    # a commit that is not the channel's, an unknown one
    (root / "notes.md").write_text("y\n")
    git(root, "commit", "-q", "-am", "notes only")
    for rev in (head(root), "deadbeef"):
        r = c.post(f"/api/channels/reel/history/{rev}/revert", headers=H)
        assert r.status_code == 404 and r.json()["code"] == "unknown_commit", r.text
    # the first version of the file
    first = git(root, "rev-list", "--max-parents=0", "HEAD")
    r = c.post(f"/api/channels/reel/history/{first}/revert", headers=H)
    assert r.status_code == 409 and r.json()["code"] == "not_revertible"
    assert head(root) != start and git(root, "log", "-1", "--format=%s") == "notes only"
    assert len(git(root, "rev-list", f"{start}..HEAD").splitlines()) == 2   # only the test's own


def test_a_revert_is_checked_and_blocked_like_a_save():
    root = factory_tree()
    c = client(root)
    # by hand, a valid config gets an invalid value; the next commit fixes it
    cfg = (root / "channels" / "reel.json").read_text()
    (root / "channels" / "reel.json").write_text(
        edit_text(cfg, '"max_attempts_per_video": 3', '"max_attempts_per_video": 0'))
    git(root, "commit", "-q", "-am", "by hand, broken")
    fix = _save(c, root, '"max_attempts_per_video": 0', '"max_attempts_per_video": 2')
    start = head(root)
    r = c.post(f"/api/channels/reel/history/{fix['commit']}/revert", headers=H)
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    assert head(root) == start
    a = _save(c, root, '"en"', '"de"')
    write_batch(root, "reel")
    r = c.post(f"/api/channels/reel/history/{a['commit']}/revert", headers=H)
    assert r.status_code == 409 and r.json()["code"] == "batch_running"
    r = c.post(f"/api/channels/reel/history/{a['commit']}/revert", headers={"Origin": BASE})
    assert r.status_code == 403


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

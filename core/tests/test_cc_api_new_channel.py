#!/usr/bin/env python3
"""CC-0008: a new channel from the command center (`GET /api/channels/template`,
`POST /api/channels` -> `api/channels.py` `create` -> `shared/new_channel.py`).

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_channels.py`: a temp git repository with `reel` (former
id `old-reel`) and `demo`; batch directories written by the test. The live
checkout's channels, pipeline and git are never read or written.

What is pinned:

* the contract names the routes, version 0.5.0 or later; `template` is a route, not a
  channel;
* the template answer: the inputs with defaults and notes, the files, off the
  schedule, the lock;
* a dry run says the files and the checks and writes nothing - a refused input
  is `ok: false` with its field, still 200;
* a create is one commit of the three new files only, «Канал <имя>: создан (из
  центра)», `Cc-Channel` / `Cc-Action: create`; another staged file stays
  staged and out of it; the channel is then listed, a stub, valid, editable
  through the CC-0006 editor, its history says the create cannot be reverted;
* refusals write nothing and commit nothing: a refused input (taken id, former
  id, reserved, bad form) 422 `invalid`; any batch or rebuild going 409
  `batch_running`; outside git `not_a_repo`; a failed commit leaves no file
  and no directory behind; no session 403.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import api                                            # noqa: E402
from test_cc_api_channels import (                    # noqa: E402
    BASE, H, client, factory_tree, files_of, git, head, write_batch, TMP)

NEW = {"channel_id": "history", "display_name": "ExampleHistory"}
PATHS = ["channels/history.json", "channels/history/brand/description.md",
         "channels/history/stance.json"]


def tree_files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if ".git" not in p.relative_to(root).parts)


def test_the_contract_names_the_new_channel_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION
    assert tuple(int(x) for x in api.API_VERSION.split(".")) >= (0, 5, 0), api.API_VERSION
    assert sorted(spec["paths"]["/api/channels"]) == ["get", "post"]
    assert sorted(spec["paths"]["/api/channels/template"]) == ["get"]
    post = spec["paths"]["/api/channels"]["post"]["responses"]
    for code in ("403", "409", "422"):
        assert code in post, code
    schema = post["409"]["content"]["application/json"]["schema"]
    # CC-0058: a create (not a dry run) outside the working factory is `not_working_factory`
    assert sorted(s["$ref"].rsplit("/", 1)[1] for s in schema["anyOf"]) == \
        ["ChannelProblem", "WritesProblem"], schema
    action = spec["components"]["schemas"]["HistoryEntry"]["properties"]["action"]
    assert "create" in json.dumps(action)


def test_the_template_is_the_factory_s_and_says_the_lock():
    root = factory_tree()
    c = client(root)
    r = c.get("/api/channels/template")
    assert r.status_code == 200, r.text
    t = r.json()
    assert [i["name"] for i in t["inputs"]] == ["channel_id", "display_name", "language"]
    assert t["inputs"][2]["default"] == "en" and all(i["note"] for i in t["inputs"])
    assert t["status"] == "no_pipeline" and t["batch_schedule"]["enabled"] is False
    assert [f["path"] for f in t["files"]] == ["channels/{id}.json", "channels/{id}/stance.json",
                                               "channels/{id}/brand/description.md"]
    assert t["config"]["channel_id"] == "{{channel_id}}"
    assert t["lock"]["locked"] is False
    write_batch(root, "demo")
    assert c.get("/api/channels/template").json()["lock"]["locked"] is True


def test_a_dry_run_says_the_files_and_writes_nothing():
    root = factory_tree()
    c = client(root)
    before, start = tree_files(root), head(root)
    r = c.post("/api/channels", headers=H, json=dict(NEW, dry_run=True))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["dry_run"] and d["commit"] is None and d["channel"] is None
    assert sorted(f["path"] for f in d["files"]) == PATHS
    cfg = json.loads(next(f["text"] for f in d["files"] if f["path"] == PATHS[0]))
    assert cfg["display_name"] == "ExampleHistory" and cfg["batch_schedule"]["enabled"] is False
    r = c.post("/api/channels", headers=H, json={"channel_id": "old-reel",
                                                 "display_name": "Demo", "dry_run": True})
    assert r.status_code == 200 and not r.json()["ok"], r.text
    assert sorted(e["field"] for e in r.json()["errors"]) == ["channel_id", "display_name"]
    assert r.json()["files"] == []
    assert tree_files(root) == before and head(root) == start


def test_a_create_is_one_commit_of_the_new_files_only():
    root = factory_tree()
    c = client(root)
    (root / "notes.md").write_text("staged by hand\n", encoding="utf-8")
    git(root, "add", "notes.md")
    start = head(root)
    r = c.post("/api/channels", headers=H, json=dict(NEW, language="de"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and not d["dry_run"] and d["subject"] == "Канал ExampleHistory: создан (из центра)"
    assert git(root, "rev-parse", "HEAD^") == start and d["commit"] == head(root)
    assert sorted(files_of(root)) == PATHS
    msg = git(root, "log", "-1", "--format=%B")
    assert "Cc-Channel: history" in msg and "Cc-Action: create" in msg
    assert git(root, "diff", "--cached", "--name-only") == "notes.md"   # still staged, not committed
    assert git(root, "status", "--porcelain", "--", "channels") == ""
    ch = d["channel"]
    assert ch["id"] == "history" and ch["no_pipeline"].startswith("конвейера нет")
    assert ch["errors"] == [] and ch["stance"]["channel_id"] == "history"
    assert ch["config"]["language"] == "de"
    ids = [x["id"] for x in c.get("/api/channels").json()["channels"]]
    assert ids == ["demo", "history", "reel"]
    # the CC-0006 editor takes it from here
    body = {"base": ch["revision"],
            "config_text": ch["config_text"].replace('"language": "de"', '"language": "en"')}
    r = c.put("/api/channels/history", headers=H, json=body)
    assert r.status_code == 200, r.text
    hist = c.get("/api/channels/history/history").json()["entries"]
    assert [e["action"] for e in hist] == ["edit", "create"]
    assert hist[1]["revertible"] is False and "создан" in hist[1]["why_not"]
    # and the same id again is taken
    r = c.post("/api/channels", headers=H, json=dict(NEW, display_name="Другое"))
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text


def test_every_refusal_writes_nothing_and_commits_nothing():
    root = factory_tree()
    c = client(root)
    before, start = tree_files(root), head(root)
    for body in ({"channel_id": "reel", "display_name": "New"},
                 {"channel_id": "old-reel", "display_name": "New"},
                 {"channel_id": "template", "display_name": "New"},
                 {"channel_id": "Bad Id", "display_name": "New"},
                 {"channel_id": "fresh", "display_name": "Reel"},
                 {"channel_id": "fresh", "display_name": "New", "language": "english"}):
        r = c.post("/api/channels", headers=H, json=body)
        assert r.status_code == 422 and r.json()["code"] == "invalid", (body, r.text)
        assert r.json()["errors"] and all(e["field"] for e in r.json()["errors"]), r.text
        assert r.json()["message"].startswith("Фабрика не приняла новый канал")
    assert c.get("/api/channels/template").status_code == 200   # a route, not a channel
    for chan, rebuild in (("demo", False), (None, True)):
        bdir = write_batch(root, chan, batch=f"b-{chan}", rebuild=rebuild)
        r = c.post("/api/channels", headers=H, json=NEW)
        assert r.status_code == 409 and r.json()["code"] == "batch_running", r.text
        assert "code_drift" in r.json()["message"] and r.json()["batches"]
        shutil.rmtree(bdir)              # done (a rebuild has no batch-done marker)
    r = c.post("/api/channels", headers={"Origin": BASE}, json=NEW)
    assert r.status_code == 403
    after = [p for p in tree_files(root) if p.split("/")[0] != "pipeline"]
    assert after == before and head(root) == start
    # a commit that fails (a hook refuses it) leaves nothing behind
    hooks = Path(git(root, "config", "core.hooksPath"))
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    r = c.post("/api/channels", headers=H, json=NEW)
    assert r.status_code == 500 and r.json()["code"] == "git_failed", r.text
    assert not (root / "channels" / "history").exists()
    assert not (root / "channels" / "history.json").exists()
    assert git(root, "status", "--porcelain") == "" and head(root) == start
    (hooks / "pre-commit").unlink()
    assert c.post("/api/channels", headers=H, json=NEW).status_code == 200


def test_outside_git_a_create_is_refused():
    root = TMP / "not-a-repo-new"
    (root / "channels").mkdir(parents=True)
    (root / "agents.lock.json").write_text(json.dumps({"agents": {}, "links": {}}))
    # CC-0058: no git -> no working factory: refused before the factory is asked
    r = client(root).post("/api/channels", headers=H, json=NEW)
    assert r.status_code == 409 and r.json()["code"] == "not_working_factory", r.text
    assert tree_files(root) == ["agents.lock.json", "channels"]
    # with the developer's flag the factory's own refusal holds
    r = client(root, writes_dev=True).post("/api/channels", headers=H, json=NEW)
    assert r.status_code == 500 and r.json()["code"] == "not_a_repo", r.text
    assert tree_files(root) == ["agents.lock.json", "channels"]


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

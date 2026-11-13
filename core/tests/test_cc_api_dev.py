#!/usr/bin/env python3
"""CC-0124: the development tasks (`api/dev.py`, `GET /api/dev/tasks`,
`/api/dev/tasks/{id}`, `/api/dev/roadmap`).

In-process (starlette's TestClient) against temp factories: a root repo with
its `agents.lock.json` (the center module at `front/`, not the default path),
CF tasks in `tasks/` and `tasks/archive/v1.0/`, a ROADMAP, a version line
`release/1.1` checked out by a worktree; a center repo at `front/` whose
checkout is detached behind `main`, CC tasks and its ROADMAP. No real
factory, no network.

What is pinned:

* the contract: three GET routes, version 0.66.0, the models' fields;
* parsing: the frontmatter (a quoted value unquoted, «—» null, `blocked_by` a
  list, an unknown key in `extra`), the checklist counts (a fenced line left
  out), an archived task, a file without frontmatter and INDEX.md left out;
* git, not the tree: an uncommitted edit is not seen; the center's `main`
  is read, not its detached checkout; the version line wins over `main` and
  says so (`branch`), a task only on it is there;
* filters (comma lists) and the search (case-insensitive, every word, id /
  title / body); 422 for an unknown project;
* one task: body, items, related ids (existing ones only, not itself), the
  commits whose subject names it (a look-alike id and a body-only mention
  left out), newest first, from both repos; 404 for an unknown id;
* the roadmap: milestones in order, DONE dates (`**код DONE` is not one),
  sprints, the ids of tables and of top-level list items in order, an
  unversioned section only when it has tasks; read from the version line;
* the kept answer: a repeat call runs `for-each-ref` only; a new commit on
  `main` is seen on the next call;
* no absolute path out (a body's `/home/...` cut, `/api/dev/tasks` kept);
  read only: every file of the trees (`.git` too) is the same after.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import dev                                  # noqa: E402
from api.app import create_app                       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-dev-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
_N = [0, 0]


def git(d, *args, date=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, env=env)
    assert cp.returncode == 0, f"git {args}: {cp.stderr}"
    return cp.stdout.strip()


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(d, msg, files=None):
    for rel, text in (files or {}).items():
        _w(d / rel, text)
    _N[1] += 1
    git(d, "add", "-A")
    git(d, "commit", "-q", "--allow-empty", "-m", msg,
        date=f"2026-10-01T10:{_N[1] // 60:02d}:{_N[1] % 60:02d}+00:00")
    return git(d, "rev-parse", "HEAD")


def _repo(d, files, msg="the start"):
    for rel, text in files.items():
        _w(d / rel, text)
    hooks = d.parent / f".no-hooks-{d.name}"
    hooks.mkdir(parents=True, exist_ok=True)
    git(d.parent, "init", "-q", "-b", "main", str(d))
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
        git(d, "config", k, v)
    return _commit(d, msg)


def fm(**kw):
    lines = ["---"] + [f"{k}: {v}" for k, v in kw.items()] + ["---", ""]
    return "\n".join(lines)


CF1 = fm(id="CF-0001", title='"Альфа: задача с «кавычками»"', type="task", status="in-progress",
         milestone='"1.1"', dod="тесты зелёные", repo="agents/video-editor", created="2026-10-01",
         closed="", owner="driver") + """## Описание
Связана с `CF-0002` и `CC-0001`; `CF-0999` нет; сама CF-0001 себя не считает.
Логи лежат в /home/someone/secret/run.log, маршрут `/api/dev/tasks` остаётся.
Слово ПОИСКОВОЕ здесь.

## Чеклист
- [x] первый пункт
- [ ] второй пункт
```
- [x] в блоке кода - не пункт
```
"""
CF2 = fm(id="CF-0002", title="Бета", type="bug", status="open", milestone="1.0.1", repo="—",
         created="2026-09-01", closed="", **{"blocked_by": "[CF-0001]"}) + "Текст беты.\n"
CF3 = fm(id="CF-0003", title="Старая", type="techdebt", status="done", milestone="1.0",
         repo="", created="2026-08-01", closed="2026-08-02") + "- [x] сделано\n"
ROADMAP_F = """# Roadmap

## Versioning

Прочее, `CF-0001` в тексте не задача вехи.

## 1.0 — Старое — **DONE 2026-08-31**

- `CF-0003` — старая задача
  - `CF-0001` — вложенный пункт, не задача

### 1.0.1 — Спринт — **DONE 2026-08-30**

| Task | DoD | Repo |
|---|---|---|
| `CF-0002` — бета, поглощает `CF-0001` | 1 | — |

### Hotfixes — после 1.0 — **DONE 2026-09-01**

| `CF-0003` — снова | 1 | — |

## 1.1 — Новое (New) — **код DONE 2026-10-12 (v1.1)**; ждёт батча

| Task | DoD | Repo |
|---|---|---|
| `CF-0001` — альфа | 1 | — |

## Notes — no tasks here

Просто текст.

## tooling — outside

- `CF-0002` — инструмент
"""
CC1 = fm(id="CC-0001", title="Центр: первая", type="task", status="open", milestone="0.2",
         repo="", created="2026-10-10", closed="") + "Про CF-0001.\n"
CC2 = fm(id="CC-0002", title="Центр: архивная", type="task", status="done", milestone="0.1",
         repo="центр", created="2026-10-09", closed="2026-10-10") + "Готово.\n"
ROADMAP_C = """# ROADMAP центра

## 0.1 — Основа (показ 1) — **DONE 2026-10-10**

| Задача | Где |
|---|---|
| `CC-0002` — архивная | центр |

## 0.2 — Дальше

| Задача | Где |
|---|---|
| `CC-0001` — первая | центр |
"""


def make_tree(release=True, center=True):
    """A temp factory (see the module's doc). -> root."""
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    lock = {"agents": {"alpha": {"path": "agents/alpha", "rev": "v1"}},
            "modules": {"frontend": {"path": "front", "rev": "main", "build": "npm",
                                     "contract": "api/openapi.json"}}}
    _repo(root, {"README.md": "# Test Factory — 1.1\n", ".gitignore": "/front/\n/.wt/\n",
                 "agents.lock.json": json.dumps(lock, indent=2),
                 "ROADMAP.md": ROADMAP_F,
                 "tasks/INDEX.md": "# Index\n| CF-0001 | x |\n",
                 "tasks/CF-0001-alpha.md": CF1, "tasks/CF-0002-beta.md": CF2,
                 "tasks/archive/v1.0/CF-0003-old.md": CF3,
                 "tasks/archive/v1.0/CF-0004-no-frontmatter.md": "## Статус попытки\nбез шапки\n"})
    _commit(root, "CF-0001: first step")
    _commit(root, "CF-00010 is a look-alike")
    _commit(root, "an unrelated subject\n\nCF-0001 only in the body")
    _commit(root, "WIP CF-0001: item 2 (CC-0001 too)")
    if release:
        git(root, "branch", "release/1.1")
        git(root, "worktree", "add", "-q", str(root / ".wt" / "release-1.1"), "release/1.1")
        wt = root / ".wt" / "release-1.1"
        _commit(wt, "CF-0005: filed on the version line", {
            "tasks/CF-0002-beta.md": CF2.replace("status: open", "status: in-progress"),
            "tasks/CF-0005-new.md": fm(id="CF-0005", title="Только на линии версии",
                                       type="task", status="open", milestone="1.1",
                                       created="2026-10-02", closed="") + "Новая.\n",
            "ROADMAP.md": ROADMAP_F.replace("| `CF-0001` — альфа | 1 | — |",
                                            "| `CF-0001` — альфа | 1 | — |\n"
                                            "| `CF-0005` — новая | 1 | — |")})
    # an uncommitted edit of the working tree - the API reads git, not this
    _w(root / "tasks" / "CF-0001-alpha.md", CF1.replace("in-progress", "WORKING-TREE"))
    if center:
        front = root / "front"
        _repo(front, {"package.json": "{}", "ROADMAP.md": ROADMAP_C,
                      "tasks/CC-0001.md": CC1.replace("status: open", "status: draft"),
                      "tasks/archive/0.1/CC-0002.md": CC2})
        _commit(front, "CC-0001: center work", {"tasks/CC-0001.md": CC1})
        git(front, "checkout", "-q", "--detach", "HEAD~1")    # the prod checkout lags main
    return root


_TREES = {}


def tree():
    if "main" not in _TREES:
        _TREES["main"] = make_tree()
    return _TREES["main"]


_CLIENTS = {}


def client(root):
    """One app per root (building the app is the slow part of a request here)."""
    if root not in _CLIENTS:
        _CLIENTS[root] = TestClient(create_app(Settings(factory_root=root), token="tok"),
                                    client=LOCAL, base_url=BASE)
    return _CLIENTS[root]


def get(root, url, code=200):
    r = client(root).get(url)
    assert r.status_code == code, (url, r.status_code, r.text[:400])
    return r.json()


def _snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = Path(dp) / f
            rel = p.relative_to(root).as_posix()
            st = p.lstat()
            out[rel] = (os.readlink(p) if p.is_symlink()
                        else hashlib.sha256(p.read_bytes()).hexdigest(), st.st_mtime_ns)
    return out


def _no_abs(got):
    text = json.dumps(got, ensure_ascii=False)
    for bad in (str(TMP), str(TMP.resolve()), str(ROOT), str(Path.home()), "/home/"):
        assert bad not in text, (bad, text[:400])


class GitCalls:
    """Counts the git subcommands run (git_read.run looks subprocess.run up at call time)."""

    def __enter__(self):
        self.saved, self.calls = subprocess.run, []

        def run(args, *a, **kw):
            if args and args[0] == "git":
                rest = [x for x in args[1:]]
                i = 0
                while i < len(rest) and rest[i].startswith("-"):
                    i += 2 if rest[i] == "-C" else 1
                self.calls.append(rest[i] if i < len(rest) else None)
            return self.saved(args, *a, **kw)
        subprocess.run = run
        return self

    def __exit__(self, *a):
        subprocess.run = self.saved


def _ids(got):
    return [t["id"] for t in got["tasks"]]


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_dev_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for path in ("/api/dev/tasks", "/api/dev/tasks/{task_id}", "/api/dev/roadmap"):
        assert sorted(spec["paths"][path]) == ["get"], path
    params = [p["name"] for p in spec["paths"]["/api/dev/tasks"]["get"]["parameters"]]
    assert params == ["project", "milestone", "status", "type", "repo", "q"], params
    sch = spec["components"]["schemas"]
    assert set(sch["DevTasks"]["properties"]) == {"tasks", "count", "total", "sources"}
    assert set(sch["DevTaskRow"]["properties"]) == {
        "id", "title", "type", "status", "milestone", "repo", "created", "closed", "dod",
        "blocked_by", "extra", "project", "archived", "archive", "path", "branch", "checklist"}
    assert set(sch["DevTask"]["properties"]) - set(sch["DevTaskRow"]["properties"]) == {
        "body", "items", "related", "commits"}
    assert set(sch["DevCommit"]["properties"]) == {"sha", "date", "subject", "project"}
    assert set(sch["DevMilestone"]["properties"]) == {"version", "title", "heading", "done",
                                                      "tasks", "sprints"}
    assert set(sch["DevRoadmap"]["properties"]) == {"project", "branch", "sha", "error",
                                                    "milestones"}


# --------------------------------------------------------------------- the list
def test_the_list_parses_the_frontmatter_and_the_checklist():
    dev.forget()
    got = get(tree(), "/api/dev/tasks")
    assert _ids(got) == ["CF-0001", "CF-0002", "CF-0003", "CF-0005", "CC-0001", "CC-0002"], got
    assert got["count"] == got["total"] == 6
    rows = {t["id"]: t for t in got["tasks"]}
    a = rows["CF-0001"]
    assert a["title"] == "Альфа: задача с «кавычками»" and a["milestone"] == "1.1", a
    assert a["status"] == "in-progress", "the uncommitted edit is not read"
    assert a["checklist"] == {"done": 1, "total": 2}, a["checklist"]
    assert a["dod"] == "тесты зелёные" and a["repo"] == "agents/video-editor"
    assert a["closed"] is None and a["extra"] == {"owner": "driver"}, a
    assert (a["project"], a["archived"], a["archive"], a["path"], a["branch"]) == \
        ("factory", False, None, "tasks/CF-0001-alpha.md", "main"), \
        "the same file on the version line: main's row"
    assert "body" not in a
    b = rows["CF-0002"]
    assert b["repo"] is None and b["blocked_by"] == ["CF-0001"] and b["type"] == "bug", b
    old = rows["CF-0003"]
    assert old["archived"] is True and old["archive"] == "v1.0" and old["repo"] is None, old
    assert old["path"] == "tasks/archive/v1.0/CF-0003-old.md" and old["checklist"]["done"] == 1
    cc2 = rows["CC-0002"]
    assert (cc2["project"], cc2["archived"], cc2["archive"], cc2["branch"]) == \
        ("center", True, "0.1", "main"), cc2
    src = [(s["project"], s["repo"], s["branch"], bool(s["sha"]), s["error"])
           for s in got["sources"]]
    assert src == [("factory", ".", "main", True, None),
                   ("factory", ".", "release/1.1", True, None),
                   ("center", "front", "main", True, None)], src
    _no_abs(got)


def test_git_is_read_not_the_checkouts():
    got = {t["id"]: t for t in get(tree(), "/api/dev/tasks")["tasks"]}
    assert got["CC-0001"]["status"] == "open", "the center's main, not its detached checkout"
    b = got["CF-0002"]
    assert b["status"] == "in-progress" and b["branch"] == "release/1.1", b
    assert got["CF-0005"]["branch"] == "release/1.1"
    assert got["CF-0001"]["branch"] == "main"


def test_without_a_version_line_main_only():
    root = make_tree(release=False)
    dev.forget()
    got = dev.tasks(root, project="factory")
    assert _ids(got) == ["CF-0001", "CF-0002", "CF-0003"]
    assert [s["branch"] for s in got["sources"] if s["project"] == "factory"] == ["main"]
    assert {t["branch"] for t in got["tasks"]} == {"main"}


def test_a_missing_center_repo_is_said_the_factory_still_answers():
    root = make_tree(release=False, center=False)
    dev.forget()
    got = dev.tasks(root)
    assert _ids(got) == ["CF-0001", "CF-0002", "CF-0003"]
    c = [s for s in got["sources"] if s["project"] == "center"]
    assert len(c) == 1 and c[0]["sha"] is None and c[0]["error"] and c[0]["repo"] == "front", c
    _no_abs(got)
    rm = dev.roadmap(root, project="center")["roadmaps"]
    assert rm[0]["milestones"] == [] and rm[0]["error"], rm


def test_filters_and_search():
    root = tree()
    assert _ids(get(root, "/api/dev/tasks?project=center")) == ["CC-0001", "CC-0002"]
    assert _ids(get(root, "/api/dev/tasks?status=open,done")) == \
        ["CF-0003", "CF-0005", "CC-0001", "CC-0002"]
    assert _ids(get(root, "/api/dev/tasks?type=bug")) == ["CF-0002"]
    assert _ids(get(root, "/api/dev/tasks?milestone=1.1")) == ["CF-0001", "CF-0005"]
    assert _ids(get(root, "/api/dev/tasks?repo=agents/video-editor,центр")) == \
        ["CF-0001", "CC-0002"]
    assert _ids(get(root, "/api/dev/tasks?project=factory&status=in-progress")) == \
        ["CF-0001", "CF-0002"]
    assert _ids(get(root, "/api/dev/tasks?q=поисковое")) == ["CF-0001"], "body, any case"
    assert _ids(get(root, "/api/dev/tasks?q=ЦЕНТР:")) == ["CC-0001", "CC-0002"], "title"
    assert _ids(get(root, "/api/dev/tasks?q=cf-0003")) == ["CF-0003"], "id"
    assert _ids(get(root, "/api/dev/tasks?q=центр архивная")) == ["CC-0002"], "every word"
    got = get(root, "/api/dev/tasks?q=нигде-нет")
    assert got["tasks"] == [] and got["count"] == 0 and got["total"] == 6
    bad = get(root, "/api/dev/tasks?project=nope", 422)
    assert bad["code"] == "bad_project" and bad["message"], bad


# --------------------------------------------------------------------- one task
def test_one_task_body_checklist_related_commits():
    got = get(tree(), "/api/dev/tasks/CF-0001")
    assert got["id"] == "CF-0001" and got["checklist"] == {"done": 1, "total": 2}
    assert got["body"].startswith("## Описание\n"), got["body"][:80]
    assert got["items"] == [{"text": "первый пункт", "done": True},
                            {"text": "второй пункт", "done": False}], got["items"]
    assert [(r["id"], r["project"], r["status"]) for r in got["related"]] == \
        [("CF-0002", "factory", "in-progress"), ("CC-0001", "center", "open")], got["related"]
    subjects = [c["subject"] for c in got["commits"]]
    assert subjects == ["WIP CF-0001: item 2 (CC-0001 too)", "CF-0001: first step"], subjects
    assert all(c["project"] == "factory" and len(c["sha"]) == 40 and c["date"]
               for c in got["commits"])
    assert got["commits"][0]["date"] > got["commits"][1]["date"]
    cc = get(tree(), "/api/dev/tasks/cc-0001")
    assert [(c["subject"], c["project"]) for c in cc["commits"]] == [
        ("CC-0001: center work", "center"), ("WIP CF-0001: item 2 (CC-0001 too)", "factory")], cc
    assert [r["id"] for r in cc["related"]] == ["CF-0001"]


def test_an_unknown_task_is_404():
    got = get(tree(), "/api/dev/tasks/CF-0999", 404)
    assert got["code"] == "unknown_task" and "CF-0999" in got["message"], got
    assert get(tree(), "/api/dev/tasks/CF-0004", 404)["code"] == "unknown_task", \
        "a file without frontmatter is no task"


def test_no_absolute_path_leaves_an_api_path_stays():
    got = get(tree(), "/api/dev/tasks/CF-0001")
    assert ".../run.log" in got["body"] and "`/api/dev/tasks`" in got["body"], got["body"]
    _no_abs(got)
    s = dev._texter(tree())(f"{tree()}/tasks/x.md, {Path.home()}/n.txt, /private/tmp/a/b.png")
    assert s == "tasks/x.md, ~/n.txt, .../b.png", s


# --------------------------------------------------------------------- the roadmap
def test_the_roadmap_in_order():
    got = get(tree(), "/api/dev/roadmap")
    f, c = got["roadmaps"]
    assert (f["project"], f["branch"], f["error"]) == ("factory", "release/1.1", None), f
    ms = [(m["version"], m["title"], m["done"], m["tasks"]) for m in f["milestones"]]
    assert ms == [("1.0", "Старое", "2026-08-31", ["CF-0003"]),
                  ("1.1", "Новое (New)", None, ["CF-0001", "CF-0005"]),
                  (None, "tooling — outside", None, ["CF-0002"])], ms
    sp = [(s["version"], s["title"], s["done"], s["tasks"]) for s in f["milestones"][0]["sprints"]]
    assert sp == [("1.0.1", "Спринт", "2026-08-30", ["CF-0002"]),
                  (None, "Hotfixes — после 1.0", "2026-09-01", ["CF-0003"])], sp
    assert f["milestones"][1]["heading"].startswith("1.1 — Новое (New) — **код DONE")
    assert (c["project"], c["branch"]) == ("center", "main")
    assert [(m["version"], m["done"], m["tasks"]) for m in c["milestones"]] == \
        [("0.1", "2026-10-10", ["CC-0002"]), ("0.2", None, ["CC-0001"])]
    only = get(tree(), "/api/dev/roadmap?project=center")["roadmaps"]
    assert [r["project"] for r in only] == ["center"]
    assert get(tree(), "/api/dev/roadmap?project=x", 422)["code"] == "bad_project"
    _no_abs(got)


def test_parse_helpers():
    assert dev.parse_task("no frontmatter\n") is None
    fmd, body = dev.parse_task('---\nid: CF-0001\ntitle: "a \\"b\\""\nx: \'it\'\'s\'\n'
                               'repo: —\n---\n\nbody\n')
    assert fmd == {"id": "CF-0001", "title": 'a "b"', "x": "it's", "repo": None}, fmd
    assert body == "body\n"
    assert dev._heading("2.3.2 — ExampleScience — **код DONE 2026-10-12 (v2.3)**; DoD 4") == \
        ("2.3.2", "ExampleScience", None)
    assert dev._heading("1.6 — Уборка — sprints 1.6.1–1.6.6 — **DONE 2026-10-04**") == \
        ("1.6", "Уборка — sprints 1.6.1–1.6.6", "2026-10-04")
    assert dev._heading("2.4 — Дальше — **DONE 2026-10-14 (v2.4)**; заметка") == \
        ("2.4", "Дальше", "2026-10-14")


# --------------------------------------------------------------------- kept, read only
def test_a_repeat_call_costs_one_ref_read_a_new_commit_is_seen():
    root = make_tree(release=False)
    dev.forget()
    dev.tasks(root)
    with GitCalls() as g:
        dev.tasks(root, q="бета")
        dev.roadmap(root)
    assert g.calls == ["for-each-ref"] * 4, g.calls      # factory + center, two calls
    with GitCalls() as g:
        dev.task(root, "CF-0001")
        dev.task(root, "CF-0001")
    assert g.calls.count("log") == 2, g.calls             # factory + center, once
    assert "ls-tree" not in g.calls and "cat-file" not in g.calls, g.calls
    _commit(root, "CF-0006: filed", {"tasks/CF-0006-six.md": fm(
        id="CF-0006", title="Шестая", type="task", status="open", milestone="1.1",
        created="2026-10-03", closed="") + "x\n"})
    with GitCalls() as g:
        got = dev.tasks(root, project="factory")
    assert "CF-0006" in _ids(got) and g.calls.count("ls-tree") == 1, g.calls
    assert dev.task(root, "CF-0006")["commits"][0]["subject"] == "CF-0006: filed"


def test_read_only():
    root = tree()
    before = _snapshot(root)
    dev.forget()
    get(root, "/api/dev/tasks")
    get(root, "/api/dev/tasks?q=альфа&status=in-progress")
    get(root, "/api/dev/tasks/CF-0001")
    get(root, "/api/dev/tasks/CC-0001")
    get(root, "/api/dev/tasks/CF-0999", 404)
    get(root, "/api/dev/roadmap")
    assert _snapshot(root) == before
    app = client(root).app
    methods = {(r.path, m) for r in app.routes if "/dev/" in getattr(r, "path", "")
               for m in getattr(r, "methods", ())}
    assert methods == {("/api/dev/tasks", "GET"), ("/api/dev/tasks/{task_id}", "GET"),
                       ("/api/dev/roadmap", "GET")}, methods


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

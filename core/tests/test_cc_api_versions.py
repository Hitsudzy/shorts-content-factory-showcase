#!/usr/bin/env python3
"""CC-0030: versions and the agents (`api/versions.py`, `GET /api/versions`).

In-process (starlette's TestClient) against temp factory roots: a root repo
with its own `agents.lock.json`, two tiny agent repos under `agents/`, a
center module with a built `dist/` and its stamp, a broken link of
`links.root` - no real factory, no network. `scripts/agents status` runs for
real once (`test_the_whole_view_of_a_temp_factory`, against the temp root - a
few git calls on a handful of files), so the pairing of its lines with the
rows is pinned on the CLI's real format; everywhere else a stand-in answers
for it (`versions.run_status`).

What is pinned:

* the contract: the route, GET only, version 0.48.0, the models' fields;
* the whole view: an agent on its pin (`ok`, its line `ok   agents/alpha
  ...`, mark ok), one with a modified tracked file (`dirty`, `why`, mark
  DIFF), the module's row with its build stamp, built from another commit -
  WARN, a broken link of
  `links.root` as a root DIFF line - said, not hidden - and the exit code 1;
  the factory's README version, HEAD, branch, main, branch_ok; the center's
  version and its dist relative to the root; no absolute path anywhere;
* the kept answer: a second request within 30 s does not run the CLI again
  (`cached: true`, the same `checked_at`), `?fresh=true` does, an old one
  is checked again; two requests at once run one check;
* the CLI that does not start or does not answer: `status.error`, the rows
  still there; no lock: `lock.error` (no absolute path), no rows, exit 2;
* read only: the trees are the same after; the git reads take no optional
  lock (GIT_OPTIONAL_LOCKS=0, CC-0098) - a stale index is not rewritten.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import versions                             # noqa: E402
from api.app import create_app                       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-versions-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
_N = [0]


def git(d, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, env=env)
    assert cp.returncode == 0, f"git {args}: {cp.stderr}"
    return cp.stdout.strip()


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")


def _repo(d, files, tag=None):
    for rel, text in files.items():
        _w(d / rel, text)
    hooks = d.parent / f".no-hooks-{d.name}"
    hooks.mkdir(parents=True, exist_ok=True)
    git(d.parent, "init", "-q", "-b", "main", str(d))
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid"),
                 ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                 ("core.hooksPath", str(hooks))):
        git(d, "config", k, v)
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "the start")
    if tag:
        git(d, "tag", tag)
    return git(d, "rev-parse", "HEAD")


_TREES = {}


def factory_tree(lock=True):
    """The temp factory below, made once per `lock` - every test only reads
    it (the whole view pins that), and a tree is a couple of dozen git calls."""
    if lock not in _TREES:
        _TREES[lock] = _make_tree(lock)
    return _TREES[lock]


def _make_tree(lock):
    """A temp factory: the root on main, agents/alpha pinned to its tag v1 and
    on it, agents/beta pinned to main with a modified file, frontend built
    from another commit than its HEAD (a WARN), a broken link of
    `links.root`."""
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    doc = {"agents": {"alpha": {"path": "agents/alpha", "rev": "v1"},
                      "beta": {"path": "agents/beta", "rev": "main"}},
           "modules": {"frontend": {"path": "frontend", "rev": "main", "build": "npm",
                                    "contract": "api/openapi.json"}},
           "links": {"root": ["shared/inserts/*/*"]}}
    files = {"README.md": "# Test Factory — 9.9, with 9.10 in progress\n",
             ".gitignore": "/agents/\n/frontend/\n/shared/inserts/\n"}
    if lock:
        files["agents.lock.json"] = json.dumps(doc, indent=2)
    _repo(root, files)
    _repo(root / "agents" / "alpha", {"a.py": "A = 1\n"}, tag="v1")
    git(root / "agents" / "alpha", "checkout", "-q", "--detach", "v1")
    _repo(root / "agents" / "beta", {"b.py": "B = 1\n"})
    _w(root / "agents" / "beta" / "b.py", "B = 2\n")
    _repo(root / "frontend", {"package.json": json.dumps({"version": "0.0.7"}),
                                     ".gitignore": "/dist/\n"})
    _w(root / "frontend" / "dist" / "index.html", "<!doctype html>")
    _w(root / "frontend" / "dist" / ".factory-build.json",
       {"module": "frontend", "rev": "main", "sha": "0" * 40, "contract": "api/openapi.json",
        "contract_sha256": None, "built_by": "scripts/agents sync (CF-0651)"})
    link = root / "shared" / "inserts" / "memes" / "gone.png"
    link.parent.mkdir(parents=True)
    os.symlink(str(TMP / "nowhere" / "gone.png"), link)
    return root


def client(root):
    s = Settings(factory_root=root, frontend_dist=root / "frontend" / "dist")
    return TestClient(create_app(s, token="tok"), client=LOCAL, base_url=BASE)


class FakeProc:
    """A stand-in for the started `scripts/agents status`."""

    def __init__(self, out="", err="", code=0, delay=0.0, hang=False):
        self.out, self.err, self.returncode = out, err, code
        self.delay, self.hang, self.killed = delay, hang, False

    def communicate(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("agents", timeout)
        time.sleep(self.delay)
        return self.out, self.err

    def kill(self):
        self.killed = True


class Stub:
    """Patches `versions.run_status`; counts the runs."""

    def __init__(self, make):
        self.make, self.runs, self.saved = make, 0, None

    def __enter__(self):
        self.saved = versions.run_status

        def run(root):
            self.runs += 1
            return self.make(root)
        versions.run_status = run
        versions.forget()
        return self

    def __exit__(self, *a):
        versions.run_status = self.saved
        versions.forget()


def _snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = Path(dp) / f
            rel = p.relative_to(root).as_posix()
            out[rel] = os.readlink(p) if p.is_symlink() else \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _no_abs(got):
    text = json.dumps(got, ensure_ascii=False)
    for bad in (str(TMP), str(TMP.resolve()), str(ROOT), str(Path.home())):
        assert bad not in text, (bad, text[:400])


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_versions_route():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    assert sorted(spec["paths"]["/api/versions"]) == ["get"]
    get = spec["paths"]["/api/versions"]["get"]
    assert [p["name"] for p in get["parameters"]] == ["fresh"], get["parameters"]
    sch = spec["components"]["schemas"]
    assert set(sch["Versions"]["properties"]) == {"checked_at", "cached", "ttl_s", "api",
                                                  "factory", "lock", "agents", "modules",
                                                  "status", "center"}
    assert {"agent", "rev", "sha", "head", "branch", "dirty", "ok", "why", "line",
            "mark"} <= set(sch["AgentState"]["properties"])
    assert {"build", "built", "api", "line", "mark"} <= set(sch["ModuleState"]["properties"])
    assert set(sch["StatusLine"]["properties"]) == {"text", "mark", "of", "subject"}
    assert {"exit_code", "ok", "lines", "stderr", "error"} <= \
        set(sch["AgentsStatus"]["properties"])
    assert {"version", "commit", "branch", "main", "dirty", "branch_ok", "release_tag",
            "versions_in_work"} <= set(sch["VersionsFactory"]["properties"])


# --------------------------------------------------------------------- the whole view
def test_the_whole_view_of_a_temp_factory():
    root = factory_tree()
    before = _snapshot(root)
    versions.forget()
    r = client(root).get("/api/versions")
    assert r.status_code == 200, r.text
    got = r.json()
    _no_abs(got)
    assert got["api"] == "0.79.0" and got["cached"] is False and got["ttl_s"] == 30.0
    assert got["checked_at"].endswith("Z") and "T" in got["checked_at"], got["checked_at"]
    assert got["lock"] == {"path": "agents.lock.json", "error": None}

    alpha, beta = got["agents"]
    assert alpha["agent"] == "alpha" and alpha["ok"] is True and alpha["dirty"] == []
    assert alpha["rev"] == "v1" and alpha["head"] == alpha["sha"] and alpha["branch"] is None
    assert alpha["mark"] == "ok" and alpha["line"].split()[:3] == ["ok", "agents/alpha", "v1"]
    assert beta["ok"] is False and beta["dirty"] == ["b.py"], beta
    assert beta["branch"] == "main" and "uncommitted" in beta["why"], beta["why"]
    assert beta["mark"] == "DIFF" and beta["line"].startswith("DIFF agents/beta"), beta["line"]

    (fe,) = got["modules"]
    assert fe["module"] == "frontend" and fe["built"] is False and fe["ok"] is False
    assert fe["build"]["sha"] == "0" * 40 and fe["build"]["rev"] == "main", fe["build"]
    assert fe["why"].startswith("built from 000000000000, not HEAD"), fe["why"]
    assert fe["mark"] == "WARN" and fe["line"].startswith("WARN frontend"), fe

    st = got["status"]
    assert st["command"] == "scripts/agents status" and st["exit_code"] == 1, st
    assert st["ok"] is False and st["error"] is None
    ofs = [(ln["of"], ln["subject"], ln["mark"]) for ln in st["lines"]]
    assert ofs[:3] == [("agent", "alpha", "ok"), ("agent", "beta", "DIFF"),
                       ("module", "frontend", "WARN")], ofs
    roots = [ln for ln in st["lines"] if ln["of"] == "root"]
    assert len(roots) == 1 and roots[0]["mark"] == "DIFF" and roots[0]["subject"] is None
    assert roots[0]["text"].startswith("DIFF shared/inserts/memes/gone.png -> .../gone.png"), \
        roots[0]["text"]
    assert "its target is missing" in roots[0]["text"]

    f = got["factory"]
    assert f["version"] == "9.9" and f["git"] is True and f["branch"] == "main"
    assert f["commit"] == git(root, "rev-parse", "HEAD") == f["main"] and f["dirty"] == []
    assert f["branch_ok"] is True
    assert f["release_tag"] is None and f["versions_in_work"] == []    # no tag, no worktree
    assert got["center"]["version"] == "0.0.7" and got["center"]["built"] is True
    assert got["center"]["dist"] == "frontend/dist" and got["center"]["built_at"]
    assert _snapshot(root) == before                       # read only
    versions.forget()


def test_the_git_reads_rewrite_no_index():
    """CC-0098: `git status` refreshes a stale index and writes it back (an
    index.lock in the factory's `.git` while a batch commits) unless optional
    locks are off - the center's reads, in process and through `scripts/agents
    status`, run with GIT_OPTIONAL_LOCKS=0: the stat of tracked files changed
    under every repo, the check leaves every `.git/index` as it was; a plain
    `git status` after it does rewrite one (the trap is real)."""
    root = _make_tree(True)
    repos = [root, root / "agents" / "alpha", root / "agents" / "beta", root / "frontend"]
    old = time.time() - 100
    for f in ("README.md", "agents/alpha/a.py", "frontend/package.json"):
        os.utime(root / f, (old, old))                 # the content the same, the stat not
    was = os.environ.get("GIT_OPTIONAL_LOCKS")
    before = {str(d): (d / ".git" / "index").read_bytes() for d in repos}
    versions.forget()
    r = client(root).get("/api/versions", params={"fresh": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["agents"][0]["ok"] is True, r.json()["agents"]
    after = {str(d): (d / ".git" / "index").read_bytes() for d in repos}
    assert after == before, [d for d in before if after[d] != before[d]]
    assert os.environ.get("GIT_OPTIONAL_LOCKS") == was     # as it was after the read
    git(root / "agents" / "alpha", "status", "--porcelain")
    assert (root / "agents" / "alpha" / ".git" / "index").read_bytes() != \
        before[str(root / "agents" / "alpha")], "a plain git status should rewrite it"
    versions.forget()


# ------------------------------------------------- the release and the versions (CC-0119)
def _release_tree():
    """A temp factory whose root carries release tags and version worktrees:
    v9.8 on the first commit of main, v9.9.1 and v9.10 on its tip (the order
    is the version's, not the text's), v9.11 and `nightly` off main only;
    live worktrees of release/9.10, release/9.2 and cc/api, one of release/9.3
    whose directory is gone (prunable)."""
    root = _make_tree(True)
    git(root, "tag", "v9.8")
    _w(root / "NOTES.md", "two\n")
    git(root, "add", "NOTES.md")
    git(root, "commit", "-q", "-m", "two")
    git(root, "tag", "v9.9.1")
    git(root, "tag", "v9.10")
    git(root, "branch", "release/9.11")
    git(root, "branch", "release/9.2")
    git(root, "branch", "release/9.3")
    git(root, "branch", "cc/api")
    wts = TMP / f"wt-{root.name}"
    for br in ("release/9.10", "release/9.2", "release/9.3", "cc/api"):
        git(root, "worktree", "add", "-q", *(["-b", br] if br == "release/9.10" else []),
            str(wts / br.replace("/", "-")), *([] if br == "release/9.10" else [br]))
    wt11 = wts / "release-9.11"
    git(root, "worktree", "add", "-q", str(wt11), "release/9.11")
    _w(wt11 / "NEXT.md", "next\n")
    git(wt11, "add", "NEXT.md")
    git(wt11, "commit", "-q", "-m", "next")
    git(wt11, "tag", "v9.11")
    git(wt11, "tag", "nightly")
    git(root, "worktree", "remove", "--force", str(wt11))
    import shutil
    shutil.rmtree(wts / "release-9.3")                  # its directory gone: prunable
    return root, wts


def test_the_release_tag_and_the_versions_in_work_are_the_factorys():
    """CF-0716: `factory.release_tag` is `runlog.release_tag` - the greatest
    v-tag reachable from main (v9.10 over v9.9.1 and v9.8; v9.11 sits on a
    branch only), read from main and not from HEAD, so a version's worktree
    answers the same; `factory.versions_in_work` is
    `agents_lock.versions_in_work` - the release/* branches with a live
    worktree in version order (9.2 before 9.10), the prunable 9.3, the
    branch release/9.11 without a worktree and cc/api left out."""
    root, wts = _release_tree()
    with Stub(lambda r: FakeProc()):
        got = client(root).get("/api/versions").json()
    _no_abs(got)
    f = got["factory"]
    assert f["release_tag"] == "v9.10", f
    assert f["versions_in_work"] == ["release/9.2", "release/9.10"], f
    rl, al = versions.factory.runlog(), versions.factory.agents_lock()
    assert f["release_tag"] == rl.release_tag(root)          # nothing of the API's own
    assert f["versions_in_work"] == al.versions_in_work(root)
    wt = wts / "release-9.10"
    _w(wt / "WIP.md", "wip\n")
    git(wt, "add", "WIP.md")
    git(wt, "commit", "-q", "-m", "wip")
    git(wt, "tag", "v9.12")                                   # on HEAD of the worktree, not main
    with Stub(lambda r: FakeProc()):
        w = client(wt).get("/api/versions").json()["factory"]
    assert w["release_tag"] == "v9.10" and w["branch"] == "release/9.10", w
    assert w["versions_in_work"] == ["release/9.2", "release/9.10"], w


def test_no_git_root_has_no_release():
    root = TMP / f"plain-{_N[0]}"
    _w(root / "README.md", "# Plain — 1.0\n")
    _w(root / "agents.lock.json", {"agents": {}})
    with Stub(lambda r: FakeProc()):
        got = client(root).get("/api/versions").json()
    assert got["factory"]["git"] is False, got["factory"]
    assert got["factory"]["release_tag"] is None and got["factory"]["versions_in_work"] == []


# --------------------------------------------------------------------- the kept answer
def test_the_answer_is_kept_and_fresh_checks_again():
    root = factory_tree()
    out = "ok   agents/alpha    v1    abc   detached\n"
    with Stub(lambda r: FakeProc(out=out, code=0)) as s:
        c = client(root)
        a = c.get("/api/versions").json()
        b = c.get("/api/versions").json()
        assert s.runs == 1 and a["cached"] is False and b["cached"] is True
        assert a["checked_at"] == b["checked_at"]
        d = c.get("/api/versions", params={"fresh": "true"}).json()
        assert s.runs == 2 and d["cached"] is False
        assert d["status"]["ok"] is True and d["status"]["exit_code"] == 0
        assert d["agents"][0]["line"] == out.strip() and d["agents"][1]["line"] is None
        assert d["agents"][1]["mark"] is None


def test_an_old_answer_is_checked_again():
    root = factory_tree()
    s = Settings(factory_root=root, frontend_dist=root / "frontend" / "dist")
    with Stub(lambda r: FakeProc()) as st:
        versions.versions(s.factory_root, s.frontend_dist, now=1000.0)
        assert versions.versions(s.factory_root, s.frontend_dist, now=1029.0)["cached"]
        assert st.runs == 1
        assert not versions.versions(s.factory_root, s.frontend_dist, now=1031.0)["cached"]
        assert st.runs == 2


def test_two_requests_at_once_run_one_check():
    root = factory_tree()
    s = Settings(factory_root=root, frontend_dist=root / "frontend" / "dist")
    got = []
    with Stub(lambda r: FakeProc(delay=0.3)) as st:
        ts = [threading.Thread(target=lambda: got.append(
            versions.versions(s.factory_root, s.frontend_dist))) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        assert st.runs == 1 and len(got) == 3, (st.runs, len(got))
        assert sorted(g["cached"] for g in got) == [False, True, True]


# --------------------------------------------------------------------- failures said
def test_a_cli_that_does_not_answer_or_start_is_said():
    root = factory_tree()
    with Stub(lambda r: FakeProc(hang=True)):
        got = client(root).get("/api/versions").json()
        assert got["status"]["exit_code"] is None and got["status"]["ok"] is False
        assert "did not answer" in got["status"]["error"], got["status"]
        assert [a["agent"] for a in got["agents"]] == ["alpha", "beta"]
        assert all(a["line"] is None for a in got["agents"])

    def boom(r):
        raise OSError("no such interpreter")
    with Stub(boom):
        got = client(root).get("/api/versions").json()
        assert "did not start" in got["status"]["error"], got["status"]
        assert got["agents"][0]["ok"] is True


def test_no_lock_is_said_without_a_path():
    root = factory_tree(lock=False)
    err = f"agents status: no agents.lock.json in {root}\n"
    with Stub(lambda r: FakeProc(err=err, code=2)):
        got = client(root).get("/api/versions").json()
    _no_abs(got)
    assert got["agents"] == [] and got["modules"] == []
    assert got["lock"]["error"] == "no agents.lock.json in .", got["lock"]
    assert got["status"]["exit_code"] == 2 and got["status"]["lines"] == []
    assert got["status"]["stderr"] == "agents status: no agents.lock.json in .", got["status"]


def test_scrub_cuts_every_absolute_path():
    root = TMP / "some-root"
    pre = [(str(root), ""), (str(TMP), "../")]
    s = versions._scrub(f"{root}/a/b -> {TMP}/x/y; {root}; /elsewhere/deep/file.png and "
                        f"{Path.home()}/notes.txt, scripts/agents ok/diff", pre)
    assert s == "a/b -> ../x/y; .; .../file.png and ~/notes.txt, scripts/agents ok/diff", s


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

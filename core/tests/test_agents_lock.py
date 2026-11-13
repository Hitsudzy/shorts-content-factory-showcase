#!/usr/bin/env python3
"""CF-0479: the agents are libraries pinned in `agents.lock.json`, and
`scripts/agents sync|status|pin` puts a checkout on the lock.

Everything here runs on a fake factory in a temp tree - a working-copy root repo
with its own `agents/ve` repo (tag `v1.4` one commit behind its `main`) and
ignored things the code borrows (a footage pool, real batches, a venv). The real
checkout is never read or written. Pinned:

* in the working copy, sync checks the pin out in the agent's own repo - a tag
  detached, so the agent's `main` stays free for a version worktree; a second
  sync does nothing;
* sync refuses, and leaves the agent as it was, when a tracked file is modified
  or when leaving HEAD would orphan a commit;
* in a root worktree (`release/<v>`) sync `git worktree add`s the agent from the
  working copy's repo - a branch pin as the branch - and links the ignored paths
  of the lock, never over a tracked or existing file; the working copy's agent is
  not touched;
* `status` says where the checkout differs (exit 1), `pin` refuses a rev that
  does not resolve and writes one that does;
* CF-0584 (the v1.8 release wiped the working copy's `.venv` of two agents):
  a release worker's `git add -A` took the agent's `.venv` link in (`.venv/`
  ignores only a directory, a symlink is a file to git), and the working copy's
  `sync` checked that tag out - git overwrites ignored paths by default, so the
  real venv became a link to its own path. Now a checkout never overwrites an
  ignored path, a path ignored only as a directory is not linked, the working
  copy links nothing to itself, and `status` names a tracked `links` path and a
  broken or self-pointing link.
* CF-0651: a second root worktree (`.worktrees/cc-api`) gets a branch pin that
  another worktree already holds as the branch's sha, detached, and moves with
  it on the next sync; the links are made whatever another agent's problem.
* CF-0651: a module of the lock (the command center, `frontend`) is checked
  out like an agent and built by a stand-in npm once per commit and API
  contract; without Node the agents still sync and the module names the fix;
  `status` warns about a module (exit 0) unless `--strict`.
* CF-0705: sync in a development copy removes the links it made whose file
  left the working copy (a dropped meme) - nothing else; status says so.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from _tmproot import tmp_root   # noqa: E402

import agents_lock  # noqa: E402

TMP = tmp_root("agents-lock-test-")
CLI = [sys.executable, str(ROOT / "scripts" / "agents")]
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def repo(d, files):
    d.mkdir(parents=True, exist_ok=True)
    git(d, "init", "-q")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@example.test")
    git(d, "config", "user.name", "t")
    for rel, text in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    git(d, "add", ".")
    git(d, "commit", "-qm", "c1")
    return d


LOCK = {"agents": {"ve": {"path": "agents/ve", "rev": "v1.4"}},
        "links": {"root": ["shared/footage", "pipeline/*"], "agents": {"*": [".venv"]}}}


def factory(agent_ignore=".venv\n"):
    """Working copy W: root repo (lock, .gitignore, tracked pipeline/RUNS.md),
    agent repo agents/ve with tag v1.4 at c1 and main at c2, ignored footage,
    a real batch and the agent's venv. -> (W, sha of v1.4, sha of main)."""
    _n[0] += 1
    w = TMP / f"f{_n[0]}" / "w"
    repo(w, {"agents.lock.json": json.dumps(LOCK, indent=2) + "\n",
             ".gitignore": "agents/*\nshared/footage\npipeline/*\n!pipeline/RUNS.md\n",
             "pipeline/RUNS.md": "# Runs\n", "code.py": "x = 1\n"})
    ve = repo(w / "agents" / "ve", {".gitignore": agent_ignore, "lib.py": "v = 1\n"})
    git(ve, "tag", "v1.4")
    tag = git(ve, "rev-parse", "HEAD")
    (ve / "lib.py").write_text("v = 2\n")
    git(ve, "commit", "-qam", "c2 - work of the next version")
    dev = git(ve, "rev-parse", "HEAD")
    (ve / ".venv" / "bin").mkdir(parents=True)
    (ve / ".venv" / "bin" / "python3").write_text("#!/bin/sh\n")
    (w / "shared" / "footage").mkdir(parents=True)
    (w / "shared" / "footage" / "clip.mp4").write_text("mp4")
    (w / "pipeline" / "chan" / "2026-10-01T1313Z").mkdir(parents=True)
    return w, tag, dev


def cli(*args):
    env = dict(os.environ)
    env.pop("FACTORY_ROOT", None)
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=env)


# ------------------------------------------------------------------ the lock

def test_the_factory_lock_pins_every_agent_and_reads_back():
    lock = agents_lock.load(ROOT)
    names = [n for n, _, _ in agents_lock.entries(lock)]
    assert names == ["compliance-checker", "content-researcher", "footage-indexer",
                     "trend-hunter", "video-editor"], names
    assert all(p == f"agents/{n}" for n, p, _ in agents_lock.entries(lock))
    assert ".venv" in agents_lock.agent_links(lock, "video-editor")
    assert "shared/footage" in agents_lock.root_links(lock)
    (name, rel, _, ent), = agents_lock.module_entries(lock)        # CF-0651: the center
    assert (name, rel, ent["build"], ent["contract"]) == ("frontend", "frontend", "npm",
                                                          "api/openapi.json")


def test_a_malformed_lock_is_refused_with_its_reason():
    _n[0] += 1
    d = TMP / f"bad{_n[0]}"
    d.mkdir(parents=True)
    try:
        agents_lock.load(d)
        raise AssertionError("a missing lock must raise")
    except agents_lock.LockError as e:
        assert "no agents.lock.json" in str(e)
    assert agents_lock.load(d, required=False) is None
    (d / agents_lock.LOCK_NAME).write_text(json.dumps({"agents": {"x": {"path": "../x",
                                                                         "rev": "v1"}}}))
    try:
        agents_lock.load(d)
        raise AssertionError("a path outside the root must raise")
    except agents_lock.LockError as e:
        assert "outside the root" in str(e)


# --------------------------------------------------------- the working copy

def test_sync_in_the_working_copy_detaches_the_agent_on_its_tag_and_is_idempotent():
    w, tag, dev = factory()
    ve = w / "agents" / "ve"
    assert [r["ok"] for r in agents_lock.status(w)] == [False]       # on main = c2
    actions, problems = agents_lock.sync(w)
    assert problems == [], problems
    assert len(actions) == 1 and "checkout -q --no-overwrite-ignore --detach" in actions[0], \
        actions
    assert git(ve, "rev-parse", "HEAD") == tag
    assert subprocess.run(["git", "-C", str(ve), "symbolic-ref", "-q", "HEAD"]).returncode == 1
    assert git(ve, "rev-parse", "main") == dev                        # main kept its work
    assert agents_lock.sync(w) == ([], [])
    assert [r["ok"] for r in agents_lock.status(w)] == [True]
    assert not (w / "shared" / "footage").is_symlink()               # nothing linked in W


def test_sync_refuses_a_modified_tracked_file_and_leaves_it_alone():
    w, tag, dev = factory()
    ve = w / "agents" / "ve"
    (ve / "lib.py").write_text("v = 'unsaved work'\n")
    actions, problems = agents_lock.sync(w)
    assert actions == [] and len(problems) == 1, (actions, problems)
    assert "1 uncommitted tracked file(s) (lib.py)" in problems[0], problems
    assert "never overwrites" in problems[0]
    assert git(ve, "rev-parse", "HEAD") == dev
    assert (ve / "lib.py").read_text() == "v = 'unsaved work'\n"


def test_sync_refuses_to_orphan_a_commit_on_a_detached_head():
    w, tag, dev = factory()
    ve = w / "agents" / "ve"
    git(ve, "checkout", "-q", "--detach")
    git(ve, "commit", "-q", "--allow-empty", "-m", "on no branch")
    lost = git(ve, "rev-parse", "HEAD")
    _, problems = agents_lock.sync(w)
    assert len(problems) == 1 and "no branch or tag holds" in problems[0], problems
    assert git(ve, "rev-parse", "HEAD") == lost


def test_a_rev_that_does_not_resolve_is_a_problem_not_a_crash():
    w, _, _ = factory()
    agents_lock.save(w, dict(LOCK, agents={"ve": {"path": "agents/ve", "rev": "v9.9"}}))
    _, problems = agents_lock.sync(w)
    assert len(problems) == 1 and "'v9.9' is not a revision" in problems[0], problems
    row = agents_lock.status(w)[0]
    assert row["ok"] is False and "not a revision" in row["why"], row


# ------------------------------------------------------- a version worktree

def test_sync_in_a_version_worktree_adds_agent_worktrees_and_links_ignored_paths():
    w, tag, dev = factory()
    agents_lock.sync(w)                                    # W's agent detached on v1.4
    r = w.parent / "release-1.5"
    git(w, "worktree", "add", "-q", "-b", "release/1.5", str(r))
    assert agents_lock.working_copy(r) == w.resolve()
    agents_lock.pin(r, "ve", "main")                       # the version builds on ve's main
    git(r, "commit", "-qam", "pin ve to main for 1.5")
    assert json.loads((r / "agents.lock.json").read_text())["agents"]["ve"]["rev"] == "main"
    assert [x["ok"] for x in agents_lock.status(r)] == [False]
    actions, problems = agents_lock.sync(r)
    assert problems == [], problems
    rve = r / "agents" / "ve"
    assert (rve / ".git").is_file()                        # a worktree, no copied history
    assert git(rve, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(rve, "rev-parse", "HEAD") == dev
    assert git(w / "agents" / "ve", "rev-parse", "HEAD") == tag   # W's agent untouched
    for rel in ("shared/footage", "pipeline/chan", "agents/ve/.venv"):
        t = r / rel
        assert t.is_symlink() and t.resolve() == (w / rel).resolve(), rel
    assert not (r / "pipeline" / "RUNS.md").is_symlink()   # tracked: never replaced
    assert (r / "shared" / "footage" / "clip.mp4").read_text() == "mp4"
    assert git(r, "status", "--porcelain") == ""           # links are ignored, the tree clean
    assert git(rve, "status", "--porcelain") == ""         # the agent's `.venv` link too
    assert all(x["ok"] for x in agents_lock.status(r))
    assert agents_lock.sync(r) == ([], [])                 # idempotent
    # a worker commits in the version's agent: it lands on ve's main, W stays on v1.4
    (rve / "lib.py").write_text("v = 3\n")
    git(rve, "commit", "-qam", "c3")
    assert git(w / "agents" / "ve", "rev-parse", "main") == git(rve, "rev-parse", "HEAD")
    assert git(w / "agents" / "ve", "rev-parse", "HEAD") == tag


def test_a_second_root_worktree_gets_a_branch_pin_detached_and_follows_it():
    """CF-0651: `.worktrees/cc-api` beside `.worktrees/release-<v>` - both pin
    the agents to `main`, and git lets one worktree hold a branch. The second
    gets the branch's sha detached, a later sync moves it with the branch, and
    the links are made even when another agent of the lock is a problem."""
    w, tag, dev = factory()
    agents_lock.sync(w)
    r = w.parent / "release-2.3"
    git(w, "worktree", "add", "-q", "-b", "release/2.3", str(r))
    agents_lock.pin(r, "ve", "main")
    git(r, "commit", "-qam", "pin ve to main")
    assert agents_lock.sync(r)[1] == []
    assert git(r / "agents" / "ve", "symbolic-ref", "--short", "HEAD") == "main"
    c = w.parent / "cc-api"
    git(w, "worktree", "add", "-q", "-b", "cc/api", str(c), "release/2.3")
    lock = agents_lock.load(c)
    lock["agents"]["gone"] = {"path": "agents/gone", "rev": "main"}   # no repo in W
    agents_lock.save(c, lock)
    actions, problems = agents_lock.sync(c)
    assert len(problems) == 1 and "agents/gone: no git repo" in problems[0], problems
    cve = c / "agents" / "ve"
    assert any("worktree add -q --detach" in a for a in actions), actions
    assert git(cve, "rev-parse", "HEAD") == dev
    assert subprocess.run(["git", "-C", str(cve), "symbolic-ref", "-q", "HEAD"]).returncode == 1
    for rel in ("shared/footage", "pipeline/chan", "agents/ve/.venv"):
        assert (c / rel).is_symlink(), rel
    row = [x for x in agents_lock.status(c) if x["agent"] == "ve"][0]
    assert row["ok"], row                                  # detached on the pin's sha is ok
    # the version's worker commits on ve's main: cc-api is behind until its next sync
    rve = r / "agents" / "ve"
    (rve / "lib.py").write_text("v = 3\n")
    git(rve, "commit", "-qam", "c3")
    new = git(rve, "rev-parse", "HEAD")
    row = [x for x in agents_lock.status(c) if x["agent"] == "ve"][0]
    assert not row["ok"] and "detached" in row["why"], row
    actions, problems = agents_lock.sync(c)
    assert problems == [problems[0]] and "gone" in problems[0], problems
    assert any("checkout -q --no-overwrite-ignore --detach" in a for a in actions), actions
    assert git(cve, "rev-parse", "HEAD") == new
    assert git(rve, "symbolic-ref", "--short", "HEAD") == "main"   # the version keeps its branch
    assert agents_lock.sync(r)[1] == []                    # and its own sync leaves it there
    assert git(rve, "symbolic-ref", "--short", "HEAD") == "main"


def test_sync_in_a_worktree_refuses_a_foreign_directory_in_the_agents_place():
    w, _, _ = factory()
    r = w.parent / "release-x"
    git(w, "worktree", "add", "-q", "-b", "release/x", str(r))
    (r / "agents" / "ve").mkdir(parents=True)
    (r / "agents" / "ve" / "notes.txt").write_text("somebody's")
    _, problems = agents_lock.sync(r)
    assert len(problems) == 1 and "not a git repo - move it away" in problems[0], problems
    assert (r / "agents" / "ve" / "notes.txt").read_text() == "somebody's"


# ------------------------------------------------------------------- CF-0584

def venv_ok(ve):
    py = ve / ".venv" / "bin" / "python3"
    return not (ve / ".venv").is_symlink() and py.is_file()


def test_the_working_copy_links_nothing_to_itself():
    w, _, _ = factory()
    ve = w / "agents" / "ve"
    alias = w.parent / "ve-alias"
    os.symlink(str(ve), str(alias))
    (w / "agents" / "ve" / ".env").write_text("K=v\n")
    for src in (ve, alias):
        assert agents_lock._link(src, ve, [".venv", ".env"], False) == ([], [])
    assert venv_ok(ve) and not (ve / ".env").is_symlink()


def test_a_path_ignored_only_as_a_directory_is_not_linked_but_named():
    w, _, _ = factory(agent_ignore=".venv/\n")
    agents_lock.sync(w)
    r = w.parent / "release-1.5"
    git(w, "worktree", "add", "-q", "-b", "release/1.5", str(r))
    actions, problems = agents_lock.sync(r)
    rve = r / "agents" / "ve"
    assert len(problems) == 1 and "only as a directory" in problems[0] \
        and "without the slash" in problems[0], problems
    assert not os.path.lexists(rve / ".venv")
    assert git(rve, "status", "--porcelain") == ""          # nothing for `git add -A`
    assert (r / "shared" / "footage").is_symlink()          # the rest is linked
    cp = cli("status", "--root", str(r))
    assert cp.returncode == 1 and "only as a directory" in cp.stdout, cp.stdout


def test_the_release_ritual_never_overwrites_the_working_copys_venv():
    """v1.8 as it went (06.10): a release worker commits the agent's `.venv`
    link, the agent is tagged, then in W - merge, sync; then the agent's
    worktree and the root worktree are removed with --force."""
    w, tag, _ = factory()
    ve = w / "agents" / "ve"
    agents_lock.sync(w)
    r = w.parent / "release-1.5"
    git(w, "worktree", "add", "-q", "-b", "release/1.5", str(r))
    agents_lock.pin(r, "ve", "main")
    git(r, "commit", "-qam", "pin ve to main")
    assert agents_lock.sync(r)[1] == []
    rve = r / "agents" / "ve"
    assert (rve / ".venv").is_symlink()
    git(rve, "add", "-f", ".venv")                          # what `.venv/` let `add -A` do
    git(rve, "commit", "-qm", "work (with the venv link)")
    cp = cli("status", "--root", str(r))                    # the release check catches it
    assert cp.returncode == 1 and "git tracks .venv" in cp.stdout, cp.stdout
    git(ve, "tag", "v1.5", "main")
    agents_lock.pin(r, "ve", "v1.5")
    git(r, "commit", "-qam", "pin ve to v1.5")
    git(w, "merge", "-q", "--no-ff", "release/1.5", "-m", "release 1.5")
    actions, problems = agents_lock.sync(w)                 # step 1: sync in W
    assert actions == [] and len(problems) == 1, (actions, problems)
    assert "nothing was overwritten" in problems[0] and "CF-0584" in problems[0], problems
    assert venv_ok(ve) and git(ve, "rev-parse", "HEAD") == tag
    git(ve, "worktree", "remove", "--force", str(rve))      # step 2
    git(ve, "worktree", "prune")
    git(w, "worktree", "remove", "--force", str(r))         # step 3
    git(w, "worktree", "prune")
    assert venv_ok(ve)


def test_status_names_a_self_pointing_and_a_broken_link():
    w, _, _ = factory()
    ve = w / "agents" / "ve"
    agents_lock.sync(w)
    import shutil
    shutil.rmtree(ve / ".venv")
    os.symlink(str(ve / ".venv"), str(ve / ".venv"))        # what v1.8 left in W
    os.symlink(str(w / "nowhere"), str(w / "pipeline" / "gone"))
    row, = agents_lock.status(w)
    assert not row["ok"] and ".venv" in row["why"] and "points at itself" in row["why"], row
    cp = cli("status", "--root", str(w))
    assert cp.returncode == 1, cp.stdout
    assert "points at itself" in cp.stdout, cp.stdout
    assert "DIFF pipeline/gone -> " in cp.stdout and "target is missing" in cp.stdout, cp.stdout


def test_sync_removes_the_links_whose_working_copy_file_is_gone():
    """CF-0705: the user dropped 10 memes in the center, their files left the
    working copy, and the version worktree kept 10 links into nowhere - status
    exit 1, and removing them by hand was refused. sync removes exactly those:
    a symlink it made whose target left the working copy. A live link, a loop,
    a dead link elsewhere and anything in the working copy stay."""
    w, _, _ = factory()
    agents_lock.sync(w)
    (w / "pipeline" / "drop").mkdir()
    r = w.parent / "release-2.4"
    git(w, "worktree", "add", "-q", "-b", "release/2.4", str(r))
    assert agents_lock.sync(r)[1] == []
    rve = r / "agents" / "ve"
    for rel in ("pipeline/chan", "pipeline/drop", "agents/ve/.venv"):
        assert (r / rel).is_symlink(), rel
    import shutil
    shutil.rmtree(w / "pipeline" / "drop")                  # the file left the working copy
    shutil.rmtree(w / "agents" / "ve" / ".venv")
    os.symlink(str(r / "pipeline" / "loop"), str(r / "pipeline" / "loop"))   # CF-0584 loop
    os.symlink(str(w / "nowhere"), str(r / "pipeline" / "other"))  # not a link sync made
    os.symlink(str(w / "nowhere"), str(w / "pipeline" / "wdead"))  # in the working copy
    cp = cli("status", "--root", str(r))
    assert cp.returncode == 1 and "DIFF pipeline/drop -> " in cp.stdout \
        and "sync removes it (CF-0705)" in cp.stdout, cp.stdout
    assert agents_lock.dead_links(w, r, ["pipeline/*"]) == [
        ("pipeline/drop", str(w.resolve() / "pipeline" / "drop"))]
    cp = cli("sync", "--dry-run", "--root", str(r))           # the dry run names, removes nothing
    assert cp.returncode == 0, cp.stderr
    assert f"would: unlink {r.resolve() / 'pipeline' / 'drop'}" in cp.stdout, cp.stdout
    assert f"would: unlink {rve.resolve() / '.venv'}" in cp.stdout, cp.stdout
    assert os.path.lexists(r / "pipeline" / "drop") and os.path.lexists(rve / ".venv")
    actions, problems = agents_lock.sync(r)
    assert problems == [], problems
    assert len([a for a in actions if a.startswith("unlink ")]) == 2, actions
    assert not os.path.lexists(r / "pipeline" / "drop")
    assert not os.path.lexists(rve / ".venv")
    assert (r / "pipeline" / "chan").is_symlink() and (r / "pipeline" / "chan").exists()
    assert (r / "shared" / "footage" / "clip.mp4").read_text() == "mp4"
    assert os.path.islink(r / "pipeline" / "other")           # pointing elsewhere: kept
    assert os.path.islink(w / "pipeline" / "wdead")           # the working copy: untouched
    assert not os.path.lexists(r / "pipeline" / "wdead")      # and its dead link not lent on
    assert agents_lock.dead_links(w, w, ["pipeline/*"]) == []
    assert agents_lock.sync(w)[1] == [] and os.path.islink(w / "pipeline" / "wdead")
    cp = cli("status", "--root", str(r))                      # only the loop is left to name
    assert cp.returncode == 1 and "pipeline/loop" in cp.stdout \
        and "points at itself" in cp.stdout and "pipeline/drop" not in cp.stdout, cp.stdout
    assert os.path.islink(r / "pipeline" / "loop")
    os.unlink(r / "pipeline" / "loop")                        # the test's own temp link
    os.unlink(r / "pipeline" / "other")
    cp = cli("status", "--root", str(r))
    assert cp.returncode == 0, cp.stdout                      # the DoD: exit 0, no hand cleaning
    assert agents_lock.sync(r) == ([], [])                    # idempotent


# ------------------------------------------------- a module: the command center

NPM = """#!/bin/sh
echo "$*" >> "$(dirname "$0")/npm.log"
case "$1" in
  ci) mkdir -p node_modules ;;
  run) mkdir -p dist && echo built > dist/index.html ;;
esac
"""


def fakebin(with_node=True):
    """A stand-in for Node: `npm` that logs its calls and makes node_modules/ and
    dist/ - no network, no real npm. Without node - an empty PATH directory."""
    _n[0] += 1
    b = TMP / f"bin{_n[0]}"
    b.mkdir(parents=True)
    if with_node:
        for name, text in (("node", "#!/bin/sh\nexit 0\n"), ("npm", NPM)):
            (b / name).write_text(text)
            (b / name).chmod(0o755)
    return b


def npm_log(b):
    p = b / "npm.log"
    return p.read_text().splitlines() if p.exists() else []


def with_center(w):
    """Add a fake center repo `frontend` on its `main` to W's lock (`modules`)."""
    fe = repo(w / "frontend", {".gitignore": "node_modules/\ndist/\n",
                               "package.json": '{"name": "cc", "scripts": {"build": "x"}}\n'})
    lock = agents_lock.load(w)
    lock["modules"] = {"frontend": {"path": "frontend", "rev": "main"}}
    agents_lock.save(w, lock)
    with open(w / ".gitignore", "a") as fh:
        fh.write("/frontend/\n")                         # as the root's .gitignore (CF-0651)
    git(w, "commit", "-qam", "pin the center")
    return fe


def test_a_module_is_validated_like_an_agent():
    w, _, _ = factory()
    for mods, why in (({"ve": {"rev": "main"}}, "both an agent and a module"),
                      ({"frontend": {"path": "frontend"}}, "has no `rev`"),
                      ({"frontend": {"rev": "main", "build": "make"}}, "unknown `build`"),
                      ({"frontend": {"rev": "main", "contract": "../api.json"}}, "outside the root")):
        agents_lock.save(w, dict(LOCK, modules=mods))
        try:
            agents_lock.load(w)
            raise AssertionError(f"{mods} must be refused")
        except agents_lock.LockError as e:
            assert why in str(e), (mods, e)
    agents_lock.save(w, dict(LOCK, modules={"frontend": {"rev": "main"}}))
    (_, rel, rev, ent), = agents_lock.module_entries(agents_lock.load(w))
    assert (rel, rev, ent["build"], ent["contract"]) == ("frontend", "main", "npm",
                                                         "api/openapi.json")


def test_sync_builds_the_center_once_per_commit_and_contract_and_status_warns_only():
    w, tag, _ = factory()
    fe = with_center(w)
    b = fakebin()
    agents_lock.TOOL_PATH = str(b)
    try:
        actions, problems = agents_lock.sync(w)
        assert problems == [], problems
        assert any(a.startswith("build ") and "frontend (not built): npm ci && npm run build"
                   in a for a in actions), actions
        assert npm_log(b) == ["ci", "run build"]
        stamp = agents_lock.build_stamp(w, "frontend")
        assert stamp["sha"] == git(fe, "rev-parse", "HEAD") and stamp["contract_sha256"] is None
        row, = agents_lock.module_status(w)
        assert row["ok"] and row["built"] and row["api"] is False, row
        cp = cli("status", "--root", str(w))
        assert cp.returncode == 0, cp.stdout
        assert "ok   frontend" in cp.stdout and "no API" in cp.stdout, cp.stdout
        assert agents_lock.sync(w) == ([], [])             # built: nothing to do
        assert npm_log(b) == ["ci", "run build"]
        # the root gets its API contract: the center was built under another one
        (w / "api").mkdir()
        (w / "api" / "openapi.json").write_text('{"openapi": "3.1.0"}\n')
        row, = agents_lock.module_status(w)
        assert not row["ok"] and "another api/openapi.json" in row["why"], row
        cp = cli("status", "--root", str(w))
        assert cp.returncode == 0 and "WARN frontend" in cp.stdout, cp.stdout   # a warning
        assert "no API" not in cp.stdout, cp.stdout
        assert cli("status", "--strict", "--root", str(w)).returncode == 1
        assert agents_lock.sync(w)[1] == []
        assert len(npm_log(b)) == 4
        assert agents_lock.build_stamp(w, "frontend")["contract_sha256"] == \
            agents_lock.contract_sha(w)
        assert agents_lock.module_status(w)[0]["ok"]
        # a new commit of the center: behind its pin until sync, then rebuilt
        (fe / "app.ts").write_text("x\n")
        git(fe, "add", ".")
        git(fe, "commit", "-qm", "c2")
        row, = agents_lock.module_status(w)
        assert not row["ok"] and "built from" in row["why"], row
        assert agents_lock.sync(w)[1] == [] and len(npm_log(b)) == 6
    finally:
        agents_lock.TOOL_PATH = None


def test_without_node_the_agents_sync_and_the_center_names_the_fix():
    w, tag, _ = factory()
    with_center(w)
    agents_lock.TOOL_PATH = str(fakebin(with_node=False))
    try:
        actions, problems = agents_lock.sync(w)
    finally:
        agents_lock.TOOL_PATH = None
    assert git(w / "agents" / "ve", "rev-parse", "HEAD") == tag     # the agent is synced
    assert len(problems) == 1, problems
    assert problems[0].startswith("frontend: not built - node, npm not found on PATH"), problems
    assert "install Node.js" in problems[0] and "the agents are synced" in problems[0]
    row, = agents_lock.module_status(w)
    assert not row["ok"] and "not built" in row["why"], row
    cp = cli("status", "--root", str(w))
    assert cp.returncode == 0 and "WARN frontend" in cp.stdout, cp.stdout


def test_a_version_worktree_gets_the_center_detached_beside_the_working_copys_main():
    """W's center is on its `main` (the center's driver works there): the
    version worktree gets main's sha detached and builds it; before its sync the
    missing center is a WARN, not a DIFF."""
    w, _, _ = factory()
    fe = with_center(w)
    agents_lock.sync(w, dry_run=True)
    r = w.parent / "release-2.3"
    git(w, "worktree", "add", "-q", "-b", "release/2.3", str(r))
    row, = agents_lock.module_status(r)
    assert not row["ok"] and "not checked out" in row["why"], row
    b = fakebin()
    agents_lock.TOOL_PATH = str(b)
    try:
        acts, problems = agents_lock.sync(r, dry_run=True)
        assert problems == [] and any("(after the checkout)" in a for a in acts), acts
        cp = cli("status", "--root", str(r))
        assert "WARN frontend" in cp.stdout and "not checked out" in cp.stdout, cp.stdout
        assert "DIFF frontend" not in cp.stdout, cp.stdout
        actions, problems = agents_lock.sync(r)
    finally:
        agents_lock.TOOL_PATH = None
    assert problems == [], problems
    rfe = r / "frontend"
    assert git(rfe, "rev-parse", "HEAD") == git(fe, "rev-parse", "main")
    assert git(fe, "symbolic-ref", "--short", "HEAD") == "main"      # W's center untouched
    assert npm_log(b) == ["ci", "run build"] and (rfe / "dist" / "index.html").is_file()
    assert git(r, "status", "--porcelain") == "", "frontend/ must be ignored by the root"
    assert agents_lock.module_status(r)[0]["ok"]


def test_pin_sets_a_modules_rev():
    w, _, _ = factory()
    fe = with_center(w)
    git(fe, "tag", "v0.1")
    agents_lock.pin(w, "frontend", "v0.1")
    lock = agents_lock.load(w)
    assert lock["modules"]["frontend"]["rev"] == "v0.1" and "frontend" not in lock["agents"]


# ------------------------------------------------------------- README pins

PIN_README = ("# F — 2.4\n\n## Version\n\n<!-- agents-lock:begin -->\n| agent | pin |\n|---|---|\n"
              "| `ve` | `main` |\n<!-- agents-lock:end -->\n\nAfter the table.\n")


def _pins(text):
    return re.findall(r"^\| `([^`]+)` \| `([^`]+)` \|$", text, re.M)


def test_pin_rewrites_the_readme_pin_table_in_the_same_action():
    # CF-0702: at 2.3 the lock went to v2.3 and the README table stayed `main`
    w, _, _ = factory()
    (w / "README.md").write_text(PIN_README, encoding="utf-8")
    agents_lock.pin(w, "ve", "v1.4")
    text = (w / "README.md").read_text(encoding="utf-8")
    assert _pins(text) == [("ve", "v1.4")], text
    assert text.startswith("# F — 2.4\n") and text.endswith("<!-- agents-lock:end -->\n\nAfter the table.\n")
    fe = with_center(w)
    git(fe, "tag", "v0.1")
    agents_lock.pin(w, "frontend", "v0.1")                    # a module: after the agents
    assert _pins((w / "README.md").read_text(encoding="utf-8")) == [("ve", "v1.4"), ("frontend", "v0.1")]
    assert agents_lock.write_readme_pins(w) is False          # already the lock


def test_readme_pins_without_a_table_are_left_alone():
    w, _, _ = factory()
    assert agents_lock.write_readme_pins(w) is None           # no README
    (w / "README.md").write_text("# F\n\nno table\n", encoding="utf-8")
    agents_lock.pin(w, "ve", "main")
    assert (w / "README.md").read_text(encoding="utf-8") == "# F\n\nno table\n"
    assert agents_lock.write_readme_pins(w) is None


def test_the_factory_readme_table_is_what_readme_pins_table_writes():
    assert agents_lock.write_readme_pins(ROOT, check=True) is False, \
        "README's agents-lock table is not agents.lock.json: scripts/agents readme"


# ------------------------------------------------------------------------- CLI

def test_cli_status_exit_codes_and_pin_refusal():
    w, tag, _ = factory()
    cp = cli("status", "--root", str(w))
    assert cp.returncode == 1 and "DIFF agents/ve" in cp.stdout, cp.stdout + cp.stderr
    assert cli("sync", "--root", str(w)).returncode == 0
    cp = cli("status", "--root", str(w))
    assert cp.returncode == 0 and "ok   agents/ve" in cp.stdout, cp.stdout
    cp = cli("pin", "ve", "v0.0-nope", "--root", str(w))
    assert cp.returncode == 2 and "is not a revision" in cp.stderr, cp.stderr
    assert agents_lock.load(w)["agents"]["ve"]["rev"] == "v1.4"
    cp = cli("pin", "ve", tag[:12], "--root", str(w))
    assert cp.returncode == 0, cp.stderr
    assert agents_lock.load(w)["agents"]["ve"]["rev"] == tag[:12]
    # CF-0702: `readme` rewrites the table from the lock, `--check` only says so
    cp = cli("readme", "--root", str(w))
    assert cp.returncode == 2 and "no agents-lock table" in cp.stderr, cp.stderr
    (w / "README.md").write_text(PIN_README, encoding="utf-8")
    cp = cli("readme", "--check", "--root", str(w))
    assert cp.returncode == 1 and "differs" in cp.stdout, cp.stdout
    assert cli("readme", "--root", str(w)).returncode == 0
    assert _pins((w / "README.md").read_text(encoding="utf-8")) == [("ve", tag[:12])]
    cp = cli("readme", "--check", "--root", str(w))
    assert cp.returncode == 0 and "is the lock" in cp.stdout, cp.stdout


# ------------------------------------------------- the working factory (CF-0677)

def test_only_the_main_checkout_on_main_is_the_working_factory():
    _n[0] += 1
    base = TMP / f"wf{_n[0]}"
    w = repo(base / "w", {"code.py": "x = 1\n"})
    assert agents_lock.is_working_factory(w) == (True, "")

    wt = base / "release-2.3"
    git(w, "worktree", "add", "-q", "-b", "release/2.3", str(wt))
    ok, why = agents_lock.is_working_factory(wt)
    assert not ok and "рабочая копия разработки" in why and str(wt.resolve()) in why, why
    git(w, "worktree", "remove", "--force", str(wt))
    assert agents_lock.is_working_factory(w)[0]

    git(w, "checkout", "-q", "-b", "feature")
    ok, why = agents_lock.is_working_factory(w)
    assert not ok and why == "основной чекаут не на main (feature)", why

    sha = git(w, "rev-parse", "HEAD")
    git(w, "checkout", "-q", "--detach", sha)
    ok, why = agents_lock.is_working_factory(w)
    assert not ok and why == f"HEAD отделён ({sha[:12]})", why

    plain = base / "plain"
    plain.mkdir()
    ok, why = agents_lock.is_working_factory(plain)
    assert not ok and "не git-репозиторий" in why and str(plain.resolve()) in why, why
    # a plain directory inside the working factory answers for itself, not its parent
    (w / "sub").mkdir()
    git(w, "checkout", "-q", "main")
    assert agents_lock.is_working_factory(w)[0]
    assert not agents_lock.is_working_factory(w / "sub")[0]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

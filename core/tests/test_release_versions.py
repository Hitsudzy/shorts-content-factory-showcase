#!/usr/bin/env python3
"""CF-0716: what the command center's /api/versions asks of the factory about
its versions, on temp git repos only (the real checkout is never read):

* `runlog.release_tag(root)` - the greatest release tag (`v<n>.<n>...`) that
  `main` reaches, by version order: not a tag only HEAD of another branch
  reaches, not a suffixed tag, not by date or commit distance; None without
  `main`, without a tag, outside a repo; the same answer from a worktree;
* `agents_lock.versions_in_work(root)` - the `release/<v>` branches with a
  worktree, by version (2.10 after 2.4); a branch without a worktree, another
  branch's worktree and a prunable worktree are not counted; [] when none;
* both through their CLIs with --json.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

import agents_lock  # noqa: E402
import runlog  # noqa: E402

TMP = tmp_root("release-versions-test-")
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def commit(d, msg):
    (d / "f.txt").write_text(msg)
    git(d, "add", ".")
    git(d, "commit", "-qm", msg)


def repo(name=None):
    _n[0] += 1
    d = TMP / (name or f"r{_n[0]}")
    d.mkdir(parents=True)
    git(d, "init", "-q")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@example.test")
    git(d, "config", "user.name", "t")
    commit(d, "c1")
    return d


def cli(script, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args],
                          capture_output=True, text=True, timeout=60)


# ------------------------------------------------------------------ release_tag

def test_release_key_orders_by_version_and_rejects_suffixes():
    assert runlog.release_key("v2.3") < runlog.release_key("v2.3.1") < runlog.release_key("v2.10")
    assert runlog.release_key("v2.4-rc1") is None and runlog.release_key("2.4") is None
    assert runlog.release_key("vx") is None and runlog.release_key(None) is None


def test_release_tag_is_the_greatest_release_main_reaches():
    d = repo()
    git(d, "tag", "v2.3.10")
    commit(d, "c2")
    git(d, "tag", "-a", "v2.3.9", "-m", "annotated, newer commit, lower version")
    git(d, "tag", "v2.4-rc1")
    git(d, "tag", "nightly")
    assert runlog.release_tag(d) == "v2.3.10"
    # a tag only another branch reaches is no release, HEAD there or not
    git(d, "checkout", "-qb", "release/2.4")
    commit(d, "c3")
    git(d, "tag", "v2.4")
    assert runlog.release_tag(d) == "v2.3.10"
    git(d, "checkout", "-q", "main")
    git(d, "merge", "-q", "--ff-only", "release/2.4")
    assert runlog.release_tag(d) == "v2.4"


def test_release_tag_answers_the_same_from_a_worktree():
    d = repo()
    git(d, "tag", "v1.0")
    git(d, "branch", "release/1.1")
    w = TMP / f"wt{_n[0]}"
    git(d, "worktree", "add", "-q", str(w), "release/1.1")
    commit(w, "work")
    git(w, "tag", "v1.1")                      # on the version branch only
    assert runlog.release_tag(w) == "v1.0" == runlog.release_tag(d)


def test_release_tag_is_none_without_main_tag_or_repo():
    d = repo()
    assert runlog.release_tag(d) is None       # no tag
    git(d, "tag", "v1.0")
    git(d, "branch", "-m", "main", "trunk")
    assert runlog.release_tag(d) is None       # no main
    plain = d / "sub"
    plain.mkdir()
    assert runlog.release_tag(plain) is None   # a plain dir does not answer with its parent
    assert runlog.release_tag(TMP / "missing") is None


def test_runlog_release_tag_cli():
    d = repo()
    cp = cli("runlog", "release-tag", "--root", str(d), "--json")
    assert cp.returncode == 1 and json.loads(cp.stdout) == {"release_tag": None}, cp
    git(d, "tag", "v3.1")
    cp = cli("runlog", "release-tag", "--root", str(d))
    assert cp.returncode == 0 and cp.stdout.strip() == "v3.1", cp
    cp = cli("runlog", "release-tag", "--root", str(d), "--json")
    assert json.loads(cp.stdout) == {"release_tag": "v3.1"}, cp


# ------------------------------------------------------------- versions_in_work

def test_versions_in_work_are_release_branches_with_a_worktree_by_version():
    d = repo()
    assert agents_lock.versions_in_work(d) == []
    for b in ("release/2.10", "release/2.4", "release/2.5", "release/1.9", "cc-api"):
        git(d, "branch", b)
    for b, name in (("release/2.10", "r210"), ("release/2.4", "r24"), ("cc-api", "cc")):
        git(d, "worktree", "add", "-q", str(TMP / f"{name}-{_n[0]}"), b)
    # a version worktree whose directory is gone is prunable - no work
    gone = TMP / f"r19-{_n[0]}"
    git(d, "worktree", "add", "-q", str(gone), "release/1.9")
    shutil.rmtree(gone)
    assert agents_lock.versions_in_work(d) == ["release/2.4", "release/2.10"]
    # any checkout of the repo answers the same
    assert agents_lock.versions_in_work(TMP / f"cc-{_n[0]}") == ["release/2.4", "release/2.10"]


def test_the_main_checkout_on_a_release_branch_counts_and_no_repo_is_empty():
    d = repo()
    git(d, "checkout", "-qb", "release/3.0")
    assert agents_lock.versions_in_work(d) == ["release/3.0"]
    plain = d / "sub"
    plain.mkdir()
    assert agents_lock.versions_in_work(plain) == []
    assert agents_lock.versions_in_work(TMP / "missing") == []


def test_agents_versions_cli():
    d = repo()
    git(d, "branch", "release/2.4")
    git(d, "worktree", "add", "-q", str(TMP / f"cli-{_n[0]}"), "release/2.4")
    cp = cli("agents", "versions", "--root", str(d), "--json")
    assert cp.returncode == 0 and json.loads(cp.stdout) == {"versions_in_work": ["release/2.4"]}, cp
    cp = cli("agents", "versions", "--root", str(d))
    assert cp.returncode == 0 and cp.stdout.strip() == "release/2.4", cp


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

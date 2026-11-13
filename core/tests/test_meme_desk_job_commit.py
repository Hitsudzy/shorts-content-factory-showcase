#!/usr/bin/env python3
"""CF-0847: a background job of the meme desk commits its own paths when it
ends done - start_job(commit=True), the switch the center turns on instead of
swapping the desk's JOB_ARGV (CC-0156 -> CC-0158).

On a temp git repo only (test_meme_desk_jobs.world moved inside it, the
factory's .gitignore lines for the insert library, its own hooks folder):
* commit=True + done: one commit of exactly the bank's changed files, with
  `Cc-Channel` / `Cc-Action: meme_<kind>`; a stray dirty file (tracked or
  not, another bank's index) stays out and stays dirty; the state file's and
  job_status' `commit` is {status: committed, sha, committed};
* git refuses (a pre-commit hook exiting 1): `cc-commit: refused ...` in the
  job's output (its log), `commit` {status: refused, detail}, the job stays
  done, nothing staged, the write stays in the tree;
* commit=False (the default) - no commit, as before; a failed job commits
  nothing; a commit that is not a bool is bad_params;
* git_commit.status / commit_paths, the root helper the desk uses.
No network, no Vision, no claude: the job's work is the trim with stand-ins.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
import git_commit as gc  # noqa: E402
import meme_desk as desk  # noqa: E402
from _tmproot import tmp_root  # noqa: E402
from test_meme_desk_background_jobs import WHO, quiet_run, started  # noqa: E402
from test_meme_desk_jobs import stand_ins, world  # noqa: E402

TMP = tmp_root("meme-desk-job-commit-")
BANK = "shared/inserts/memes-tech"
IGNORE = ("shared/inserts/*/*\n!shared/inserts/*/index.json\n"
          "!shared/inserts/*/candidates.json\n")


def git(repo, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                        env=env, timeout=60)
    if check and cp.returncode:
        raise AssertionError(f"git {args}: {cp.stderr}")
    return cp.stdout


def repo_world(tmp):
    """(repo, kw): world's repo with the inserts library at shared/inserts/,
    a git repo with everything committed, hooks in its own folder."""
    t, repo, inserts = world(tmp, escape=False)
    lib_root = repo / "shared" / "inserts"
    lib_root.parent.mkdir(parents=True)
    shutil.move(str(inserts), str(lib_root))
    (repo / ".gitignore").write_text(IGNORE + "schedule/\n")
    (repo / "notes.txt").write_text("v1\n")
    (repo / "hooks").mkdir()
    git(repo, "init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("core.hooksPath", "hooks"),
                 ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    return repo, dict(root=lib_root, repo=repo)


def stray(repo):
    """A tracked file edited by hand, an untracked one, another bank's index."""
    (repo / "notes.txt").write_text("hand edit\n")
    (repo / "loose.txt").write_text("untracked\n")
    other = repo / "shared" / "inserts" / "memes" / "index.json"
    other.write_text(other.read_text() + "\n")


def run_trim(kw, **extra):
    with stand_ins():
        r = started("trim_blank", {}, kw, bank="memes-tech", **extra)
        code, out, err = quiet_run(r["state_file"])
    return r, code, out, err


def test_a_done_job_commits_only_its_own_paths_with_the_trailers():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        repo, kw = repo_world(tmp)
        stray(repo)
        head0 = git(repo, "rev-parse", "HEAD").strip()
        r, code, out, err = run_trim(kw, commit=True)
        assert code == 0, (out, err)
        s = json.loads(Path(r["state_file"]).read_text())
        assert s["state"] == "done" and s["commit_on_done"] is True, s
        head = git(repo, "rev-parse", "HEAD").strip()
        assert head != head0 and git(repo, "rev-parse", "HEAD~1").strip() == head0
        assert s["commit"] == {"status": "committed", "sha": head,
                               "committed": [f"{BANK}/index.json"]}, s["commit"]
        files = git(repo, "show", "--name-only", "--format=", "HEAD").split()
        assert files == [f"{BANK}/index.json"], files
        msg = git(repo, "log", "-1", "--format=%B")
        assert msg.startswith("Мемы tech: задача trim_blank готова (user, center)"), msg
        assert "Задача: " + r["job_id"] in msg
        trailers = git(repo, "log", "-1", "--format=%(trailers:only,unfold)").split("\n")
        assert [x for x in trailers if x] == ["Cc-Channel: tech", "Cc-Action: meme_trim"], trailers
        assert f"cc-commit: committed {head[:12]}: {BANK}/index.json" in out, out
        dirty = git(repo, "status", "--porcelain", "--untracked-files=all")
        for p in ("notes.txt", "loose.txt", "shared/inserts/memes/index.json"):
            assert p in dirty, dirty
        assert f"{BANK}/index.json" not in dirty and not git(repo, "diff", "--cached")
        st = desk.job_status(r["job_id"], bank="memes-tech", **kw)
        assert st["commit"] == s["commit"] and st["commit_on_done"] is True


def test_a_refused_commit_is_said_and_the_job_stays_done():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        repo, kw = repo_world(tmp)
        hook = repo / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho 'no commits today' >&2\nexit 1\n")
        hook.chmod(0o755)
        head0 = git(repo, "rev-parse", "HEAD").strip()
        r, code, out, err = run_trim(kw, commit=True)
        assert code == 0, (out, err)
        s = json.loads(Path(r["state_file"]).read_text())
        assert s["state"] == "done" and s["error"] is None, s
        c = s["commit"]
        assert c["status"] == "refused" and "no commits today" in c["detail"], c
        assert f"{BANK}/index.json" in c["detail"] and "sha" not in c
        assert "cc-commit: refused - " in out and f"job {r['job_id']}: done" in out, out
        assert git(repo, "rev-parse", "HEAD").strip() == head0
        assert not git(repo, "diff", "--cached"), "the refusal left something staged"
        assert f" M {BANK}/index.json" in git(repo, "status", "--porcelain")


def test_without_the_switch_and_for_a_failed_job_nothing_is_committed():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        repo, kw = repo_world(tmp)
        head0 = git(repo, "rev-parse", "HEAD").strip()
        r, code, out, _ = run_trim(kw)                          # commit=False: as before
        s = json.loads(Path(r["state_file"]).read_text())
        assert code == 0 and s["state"] == "done" and s["commit_on_done"] is False
        assert s["commit"] is None and "cc-commit" not in out
        assert git(repo, "rev-parse", "HEAD").strip() == head0
        assert f" M {BANK}/index.json" in git(repo, "status", "--porcelain")
        git(repo, "checkout", "-q", "--", f"{BANK}/index.json")
        # a failed job (its id gone before the run) - no commit, no outcome
        with stand_ins():
            r = started("trim_blank", {"id": "banded"}, kw, bank="memes-tech", commit=True)
            idx_path = kw["root"] / "memes-tech" / "index.json"
            idx = json.loads(idx_path.read_text())
            idx["entries"] = [e for e in idx["entries"] if e["id"] != "banded"]
            idx_path.write_text(json.dumps(idx))
            code, out, _ = quiet_run(r["state_file"])
        s = json.loads(Path(r["state_file"]).read_text())
        assert code == 1 and s["state"] == "failed" and s["commit"] is None, s
        assert "cc-commit" not in out
        assert git(repo, "rev-parse", "HEAD").strip() == head0
        # the switch is a bool
        try:
            desk.start_job("trim_blank", {}, bank="memes-tech", commit="yes", **WHO, **kw)
        except desk.MemeDeskError as e:
            assert e.code == "bad_params", e.code
        else:
            raise AssertionError("start_job took commit='yes'")


def test_nothing_changed_and_no_git_is_nothing():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        repo, kw = repo_world(tmp)
        head0 = git(repo, "rev-parse", "HEAD").strip()
        with stand_ins():                     # the embedding job writes no tracked byte here
            r = started("embed", {}, kw, bank="memes-tech", commit=True)
            code, out, _ = quiet_run(r["state_file"])
        s = json.loads(Path(r["state_file"]).read_text())
        assert code == 0 and s["commit"] == {"status": "nothing"}, s
        assert "cc-commit: nothing to commit" in out
        assert git(repo, "rev-parse", "HEAD").strip() == head0
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:      # world without git
        _t, repo, inserts = world(tmp, escape=False)
        kw = dict(root=inserts, repo=repo)
        r, code, out, _ = run_trim(kw, commit=True)
        s = json.loads(Path(r["state_file"]).read_text())
        assert code == 0 and s["state"] == "done" and s["commit"]["status"] == "nothing", s


def test_git_commit_status_and_commit_paths():
    with tempfile.TemporaryDirectory(dir=TMP) as tmp:
        repo, _kw = repo_world(tmp)
        (repo / "notes.txt").write_text("v2\n")
        (repo / "new.txt").write_text("n\n")
        (repo / "shared" / "inserts" / "memes" / "x.png").write_bytes(b"png")  # ignored
        st = gc.status(repo, ["."])
        assert st == {"notes.txt": " M", "new.txt": "??"}, st
        sha, rels = gc.commit_paths(repo, ["new.txt", "shared/inserts/memes/x.png"], "m\n")
        assert rels == ["new.txt"] and sha == git(repo, "rev-parse", "HEAD").strip()
        assert gc.status(repo, ["."]) == {"notes.txt": " M"}
        assert gc.commit_paths(repo, [], "m\n") == (None, [])
        (repo / "new.txt").unlink()
        sha2, rels = gc.commit_paths(repo, ["new.txt"], "gone\n")
        assert rels == ["new.txt"] and sha2 != sha
        assert "new.txt" not in git(repo, "ls-files")


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

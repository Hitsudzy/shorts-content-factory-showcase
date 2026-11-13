#!/usr/bin/env python3
"""CF-0516: scripts/cleanup_cf0516_leftovers.sh removes exactly the leftovers of
batch 2026-09-15T1034Z from the editor's production checkout - the four
work/<slug>/ and their logs/<slug>-attempt-N.log (plus cf0141-fullrun's) - and
only with --delete, a closed batch, the production checkout as the target and
none of those files still tracked at its HEAD.

Everything runs in a fixture factory in a temp dir (git repo agents/video-editor,
a stand-in runlog whose batch-active exit code the test picks), never the real one.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import subprocess
import sys
import traceback
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cleanup_cf0516_leftovers.sh"
GIT_ID = ["-c", "user.email=cf0516@test", "-c", "user.name=cf0516",
          "-c", "commit.gpgsign=false"]
SLUGS = ["dtf-st-louis", "everyday-sorcery-2", "widows-bay", "spirerunner-fresh-dawn"]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *GIT_ID, *args], capture_output=True,
                        text=True, timeout=30)
    assert cp.returncode == 0, f"git {' '.join(args)}: {cp.stderr}"
    return cp.stdout


def factory(batch_rc=1, tracked=False):
    root = Path(tmp_root("cf0516-")).resolve()
    agent = root / "agents" / "video-editor"
    (agent / "scripts").mkdir(parents=True)
    (agent / "scripts" / "attempts.py").write_text("# stand-in\n")
    (agent / ".gitignore").write_text("logs/\n*.wav\n")
    for s in SLUGS:
        (agent / "work" / s).mkdir(parents=True)
        (agent / "work" / s / "plan.json").write_text("{}\n")
        (agent / "work" / s / "voice.wav").write_bytes(b"\0" * 4096)
    (agent / "work" / "cf0052-measure").mkdir()
    (agent / "work" / "cf0052-measure" / "CHECKLIST.md").write_text("keep\n")
    (agent / "logs").mkdir()
    for name in ["dtf-st-louis-attempt-1.log", "widows-bay-attempt-3.log",
                 "cf0141-fullrun-attempt-2.log", "other-attempt-1.log"]:
        (agent / "logs" / name).write_text("log\n")
    git(agent, "init", "-q")
    git(agent, "add", "scripts", ".gitignore", "work/cf0052-measure")
    if tracked:
        git(agent, "add", *[f"work/{s}/plan.json" for s in SLUGS])
    git(agent, "commit", "-q", "-m", "fixture")
    runlog = root / "runlog"
    runlog.write_text(f"#!/bin/bash\nexit {batch_rc}\n")
    runlog.chmod(0o755)
    return root, agent


def run(root, *args, agent_dir=None):
    env = dict(os.environ, FACTORY_ROOT=str(root), RUNLOG=str(root / "runlog"))
    env.pop("AGENT_DIR", None)
    if agent_dir:
        env["AGENT_DIR"] = str(agent_dir)
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                          env=env, timeout=60)


def untouched(agent):
    return all((agent / "work" / s).exists() for s in SLUGS) and \
        (agent / "logs" / "dtf-st-louis-attempt-1.log").exists()


def test_dry_run_lists_paths_and_deletes_nothing():
    root, agent = factory(batch_rc=0)
    cp = run(root)
    assert cp.returncode == 0, cp.stderr
    for s in SLUGS:
        assert f"work/{s}" in cp.stdout, cp.stdout
    for name in ["dtf-st-louis-attempt-1.log", "widows-bay-attempt-3.log",
                 "cf0141-fullrun-attempt-2.log"]:
        assert f"logs/{name}" in cp.stdout, cp.stdout
    assert "other-attempt-1.log" not in cp.stdout
    assert "cf0052-measure" not in cp.stdout
    assert "сухой прогон" in cp.stdout and "батч: открыт" in cp.stdout
    assert untouched(agent)


def test_delete_refused_while_a_batch_is_open():
    root, agent = factory(batch_rc=0)
    cp = run(root, "--delete")
    assert cp.returncode == 1 and "батч открыт" in cp.stderr, (cp.stdout, cp.stderr)
    assert untouched(agent)


def test_delete_refused_when_batch_state_is_unknown():
    root, agent = factory(batch_rc=3)
    cp = run(root, "--delete")
    assert cp.returncode == 1 and "неизвестно" in cp.stderr, (cp.stdout, cp.stderr)
    assert untouched(agent)


def test_delete_refused_while_the_files_are_still_tracked():
    root, agent = factory(batch_rc=1, tracked=True)
    cp = run(root, "--delete")
    assert cp.returncode == 1 and "ещё в git" in cp.stderr, (cp.stdout, cp.stderr)
    assert untouched(agent)
    assert git(agent, "status", "--porcelain", "--untracked-files=no") == ""


def test_delete_refused_on_a_worktree_or_another_dir():
    root, agent = factory(batch_rc=1)
    wt = root / "wt"
    git(agent, "worktree", "add", "-q", "--detach", str(wt))
    cp = run(root, "--delete", agent_dir=wt)
    assert cp.returncode == 1 and "не боевой чекаут" in cp.stderr, cp.stderr
    assert untouched(agent)


def test_delete_removes_exactly_the_leftovers():
    root, agent = factory(batch_rc=1)
    cp = run(root, "--delete")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    for s in SLUGS:
        assert not (agent / "work" / s).exists()
    assert (agent / "work" / "cf0052-measure" / "CHECKLIST.md").exists()
    assert sorted(p.name for p in (agent / "logs").iterdir()) == ["other-attempt-1.log"]
    again = run(root, "--delete")
    assert again.returncode == 0 and "удалять нечего" in again.stdout, again.stdout


def test_empty_logs_dir_is_removed():
    root, agent = factory(batch_rc=1)
    (agent / "logs" / "other-attempt-1.log").unlink()
    cp = run(root, "--delete")
    assert cp.returncode == 0, cp.stderr
    assert not (agent / "logs").exists()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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

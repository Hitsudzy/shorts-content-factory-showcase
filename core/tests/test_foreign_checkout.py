#!/usr/bin/env python3
"""CF-0492: a batch run from a version worktree (`.worktrees/release-<v>`,
CF-0479) next to the main checkout.

The case of 2026-10-02T1748Z: the batch was opened by `batch-start` from the
worktree, an operator called `runlog stage-start` from the main checkout, and
the marker compared *that* checkout's HEADs with the header - `code_drift` on
the root and all five agents while the code under the run stood still. The
triage of the worktree then numbered six tasks after its own lagging `tasks/`
and would have re-issued numbers `main` already had.

What is pinned here, on a fake factory in a temp tree (a root repo with a
`release/1.6` worktree, each tree with its own agent repos; the real checkout
is never read or written):

* batch-start writes the checkout path beside the HEADs (`header.git.checkout`);
* a marker from the other checkout writes no `code_drift` but a
  `foreign_checkout` warning; a real move in the batch's own tree still is
  drift, whichever checkout the marker runs from;
* a batch without a recorded path (opened before CF-0492) is read as before;
* the triage numbers its tasks past the union of the tree's `tasks/` and
  `main`'s, and sees an open triage key filed only on `main`.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("foreign-checkout-test-")
STATE = TMP / "state"
os.environ["RUNLOG_STATE_DIR"] = str(STATE)
os.environ["RUNLOG_PROJECTS_DIR"] = str(TMP / "none")
os.environ["RUNLOG_TRANSCRIPTS"] = str(TMP / "none")
import runlog   # noqa: E402
import triage   # noqa: E402

CLI = [sys.executable, str(ROOT / "scripts" / "runlog")]
LOCK = {"agents": {"video-editor": {"path": "agents/video-editor", "rev": "v1.4"}}}
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def repo(d, content="x = 1\n"):
    d.mkdir(parents=True, exist_ok=True)
    git(d, "init", "-q")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@example.test")
    git(d, "config", "user.name", "t")
    (d / "code.py").write_text(content)
    git(d, "add", ".")
    git(d, "commit", "-qm", "c1")
    return d


def agent(tree, content):
    a = repo(tree / "agents" / "video-editor", content)
    git(a, "tag", "v1.4")
    return a


def factory():
    """(main checkout, release worktree, batch dir in the worktree). The two
    trees carry different agent repos (different commits of the same pin), the
    worktree is on `release/1.6`, `tasks/` of main is ahead of the branch's."""
    _n[0] += 1
    main = TMP / f"f{_n[0]}" / "root"
    repo(main)
    (main / ".gitignore").write_text("agents/*/\n.worktrees/\n")
    (main / "pipeline").mkdir()
    (main / "pipeline" / "runs.jsonl").write_text("")
    (main / "tasks").mkdir()
    (main / "tasks" / "CF-0479-x.md").write_text("---\nid: CF-0479\nstatus: done\n---\n")
    (main / "agents.lock.json").write_text(json.dumps(LOCK, indent=2) + "\n")
    git(main, "add", ".")
    git(main, "commit", "-qm", "tasks, lock")
    wt = main / ".worktrees" / "release-1.6"
    git(main, "worktree", "add", "-q", "-b", "release/1.6", str(wt))
    # main moves on: new tasks and new code the worktree does not have
    for i in range(480, 486):
        (main / "tasks" / f"CF-0{i}-y.md").write_text(f"---\nid: CF-0{i}\nstatus: open\n---\n")
    (main / "code.py").write_text("x = 2\n")
    git(main, "add", ".")
    git(main, "commit", "-qm", "main moves on")
    agent(main, "main = 1\n")
    agent(wt, "release = 1\n")
    b = wt / "pipeline" / "chan" / "2026-10-02T1748Z"
    b.mkdir(parents=True)
    return main, wt, b


def cli(root, *args):
    env = dict(os.environ, FACTORY_ROOT=str(root), RUNLOG_STATE_DIR=str(STATE),
               RUNLOG_TRANSCRIPTS=str(TMP / "none"), RUNLOG_PROJECTS_DIR=str(TMP / "none"))
    env.pop("RUNLOG_BATCH", None)
    env.pop("RUNLOG_PARENT", None)
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=env)


def markers(b):
    return [e for e in runlog.read_events(b) if e.get("kind") == "marker"]


def stop(b):
    runlog.sibling("sampler").stop(b)


# ------------------------------------------------------------------ item 1

def test_batch_start_records_its_checkout_beside_the_heads():
    main, wt, b = factory()
    cp = cli(wt, "batch-start", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0, cp.stderr
    ms = markers(b)
    assert ms[0][runlog.CODE_CHECK_KEY]["checked"] is True
    assert ms[0]["header"]["git"]["checkout"] == str(wt.resolve())
    assert runlog.header_checkout(runlog.read_events(b)) == str(wt.resolve())


def test_a_marker_from_the_main_checkout_is_a_warning_not_code_drift():
    main, wt, b = factory()
    assert cli(wt, "batch-start", "--batch", str(b), "--no-render").returncode == 0
    cp = cli(main, "stage-start", "video-editor", "--batch", str(b), "--no-render")
    assert cp.returncode == 0, cp.stderr
    assert "code drift (CF-0398)" not in cp.stderr, cp.stderr
    assert "foreign checkout (CF-0492)" in cp.stderr, cp.stderr
    # a marker from the batch's own checkout says nothing of the kind
    cp2 = cli(wt, "stage-done", "video-editor", "--batch", str(b), "--no-render")
    cp3 = cli(main, "batch-done", "--batch", str(b), "--no-render")
    stop(b)
    assert cp3.returncode == 0 and "code drift (CF-0398)" not in cp3.stderr, cp3.stderr
    assert cp2.returncode == 0 and "foreign checkout" not in cp2.stderr, cp2.stderr
    ms = markers(b)
    assert runlog.CODE_DRIFT_KEY not in ms[1]
    assert ms[1][runlog.FOREIGN_CHECKOUT_KEY] == {"batch": str(wt.resolve()),
                                                  "caller": str(main.resolve())}
    assert runlog.FOREIGN_CHECKOUT_KEY not in ms[2]
    assert runlog.drift_rows(runlog.read_events(b)) == []
    # the triage sees no авария in it
    res = triage.triage(b, events=runlog.read_events(b), config={}, ledger={"rules": {}},
                        gate_results=[])
    assert not [i for i in res["incidents"] if i["kind"] == triage.CODE_DRIFT]


def test_a_real_move_in_the_batch_tree_is_drift_from_either_checkout():
    main, wt, b = factory()
    assert cli(wt, "batch-start", "--batch", str(b), "--no-render").returncode == 0
    was = git(wt, "rev-parse", "HEAD")
    (wt / "code.py").write_text("x = 3\n")
    git(wt, "commit", "-qam", "code under the run")
    now = git(wt, "rev-parse", "HEAD")
    ve = wt / "agents" / "video-editor"
    awas = git(ve, "rev-parse", "HEAD")
    git(ve, "commit", "-q", "--allow-empty", "-m", "agent moved under the run")
    anow = git(ve, "rev-parse", "HEAD")
    cp = cli(main, "stage-start", "video-editor", "--batch", str(b), "--no-render")
    stop(b)
    assert cp.returncode == 0 and "code drift (CF-0398)" in cp.stderr, cp.stderr
    assert markers(b)[1][runlog.CODE_DRIFT_KEY] == [
        {"repo": "root", "was": was, "now": now},
        {"repo": "agents/video-editor", "was": awas, "now": anow}]


def test_a_batch_without_a_recorded_checkout_is_read_as_before():
    main, wt, b = factory()
    assert cli(wt, "batch-start", "--batch", str(b), "--no-render").returncode == 0
    stop(b)
    evs = runlog.read_events(b)
    for e in evs:
        if e.get("status") == "batch-start":
            e["header"]["git"].pop("checkout")
    assert runlog.header_checkout(evs) is None
    assert runlog.foreign_checkout(evs, root=main) is None
    (wt / "code.py").write_text("x = 4\n")
    git(wt, "commit", "-qam", "code under the run")
    # as before CF-0492: the caller's checkout is read, and the batch dir must
    # sit under its pipeline/
    assert [d["repo"] for d in runlog.code_drift(evs, b, root=wt)] == ["root"]
    assert runlog.code_drift(evs, b, root=main) == []


# ------------------------------------------------------------------ item 2

def _incident(key="code_drift:root"):
    return {"batch": "chan/2026-10-02T1748Z", "incidents": [
        {"key": key, "kind": triage.CODE_DRIFT, "what": "root", "count": 1,
         "detail": "d", "stage": "video-editor", "first": None}]}


def test_the_triage_on_a_lagging_branch_numbers_past_main():
    main, wt, b = factory()
    tdir = wt / "tasks"
    assert sorted(p.name[:7] for p in tdir.glob("CF-*.md")) == ["CF-0479"]
    assert triage.next_id(tdir) == 486
    filed = triage.file_tasks(_incident(), tdir, dry_run=True)
    assert [t for t, _ in filed] == ["CF-0486"]
    assert not list(tdir.glob("CF-0486*"))                      # dry run writes nothing
    # in the main checkout itself main is the tree: the same answer
    assert triage.next_id(main / "tasks") == 486
    # outside any git tree: the directory alone, as before
    _n[0] += 1
    lone = TMP / f"lone{_n[0]}"
    lone.mkdir()
    (lone / "CF-0007-z.md").write_text("status: open\n")
    assert triage.next_id(lone) == 8


def test_an_open_triage_key_filed_only_on_main_takes_the_incident():
    main, wt, b = factory()
    (main / "tasks" / "CF-0490-triage.md").write_text(
        "---\nid: CF-0490\nstatus: open\n---\n\n## Ключ разбора\ntriage-key: `code_drift:root`\n")
    git(main, "add", "tasks")
    git(main, "commit", "-qm", "a triage task on main")
    assert triage.known_keys(wt / "tasks")["code_drift:root"] == ("CF-0490", "open")
    res = _incident()
    assert triage.file_tasks(res, wt / "tasks", dry_run=True) == []
    assert res["incidents"][0]["task"] == "CF-0490"
    other = _incident("crash:x")
    assert [t for t, _ in triage.file_tasks(other, wt / "tasks", dry_run=True)] == ["CF-0491"]


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

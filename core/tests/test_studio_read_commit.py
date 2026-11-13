#!/usr/bin/env python3
"""CF-0786: the Studio read started from the command center commits its data.

17.10 09:33 MSK the first read from the center (`studio_center.studio_read_launch`)
wrote `analytics/example-film/studio.jsonl`, a new `analytics/example-tech/studio.jsonl`
and the `studio_visits.jsonl` of all three channels - and nobody committed them:
the center commits nothing, the session was told not to touch git. A tracked
analytics/ file left dirty is code to `runlog batch-start` (CF-0479) - the next
batch would be refused.

Nothing here goes to Studio, starts a real `claude` or touches the network:
temp git repositories (their own hooks dir, no push), the session is the
stand-in of tests/test_studio_center.py.

What is pinned:

* `commit_read_data` commits exactly the read's files git sees changed or new
  (analytics/<channel>/studio.jsonl and studio_visits.jsonl) in one commit; the daily series, code, anything else
  dirty stays as it was; nothing to commit is `nothing`; a non-repo or a
  directory inside another work tree is `not_repo`;
* under a batch past its `batch-start` nothing is committed (`deferred`); a
  run whose executor holds its lock before `batch-start` does not defer;
* the launch runs the session under the runner: after the session the read's
  data is committed, `STUDIO_READ_COMMIT:` closes the log, the run record and
  `studio_read_result` carry `commit`, the result line says it; the run is
  `running` until the runner's line;
* a dirty analytics/ file is a record (CF-0895): `batch-start` does not refuse
  it (runlog.repo_problems), a dirty shared/*.json still is refused; the commit
  clears the first.
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "agents" / "analyst"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
from _tmproot import tmp_root  # noqa: E402

TMP = tmp_root("studio-read-commit-test-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "runlog-state")     # the runner imports runlog
os.environ["RUNLOG_PROJECTS_DIR"] = str(TMP / "none")
os.environ["RUNLOG_TRANSCRIPTS"] = str(TMP / "none")

import test_studio_center as tc         # noqa: E402  (world(), the claude stand-in)
import studio_center as sc              # noqa: E402
import runlog                           # noqa: E402

HOOKS = TMP / "no-hooks"
HOOKS.mkdir()


def git(root, *args):
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                        timeout=60)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout


def make_repo(root):
    """`root` as a git repo of its own, everything there committed."""
    git(root, "init", "-q", "-b", "main")
    for k, v in (("user.name", "test"), ("user.email", "test@example.invalid"),
                 ("core.hooksPath", str(HOOKS)), ("commit.gpgsign", "false")):
        git(root, "config", k, v)
    (root / ".gitignore").write_text("schedule/\nnotify/\nbin/\nclaude.mode\nstub-*\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def repo_root(name):
    root = TMP / name
    for d in ("channels", "analytics/example-film", "analytics/example-tech", "shared", "scripts"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "channels" / "example-film.json").write_text("{}\n")
    (root / "analytics/example-film/studio.jsonl").write_text('{"row": 1}\n')
    (root / "analytics/example-film/studio_visits.jsonl").write_text('{"visit": 1}\n')
    (root / "analytics/example-film/daily.jsonl").write_text('{"day": 1}\n')
    (root / "shared/notes.json").write_text('{"notes": []}\n')
    (root / "scripts/tool.py").write_text("x = 1\n")
    return make_repo(root)


def changed_in_head(root):
    return sorted(git(root, "show", "--name-only", "--format=", "HEAD").split())


def porcelain(root):
    return sorted(ln[3:] for ln in git(root, "status", "--porcelain",
                                       "--untracked-files=all").splitlines())


def test_one_commit_of_exactly_the_reads_files():
    root = repo_root("exact")
    head = git(root, "rev-parse", "HEAD").strip()
    with open(root / "analytics/example-film/studio.jsonl", "a") as fh:
        fh.write('{"row": 2}\n')
    with open(root / "analytics/example-film/studio_visits.jsonl", "a") as fh:
        fh.write('{"visit": 2}\n')
    (root / "analytics/example-tech/studio.jsonl").write_text('{"row": "new"}\n')
    # not the read's: the daily series, code, an untracked stray file
    with open(root / "analytics/example-film/daily.jsonl", "a") as fh:
        fh.write('{"day": 2}\n')
    (root / "scripts/tool.py").write_text("x = 2\n")
    (root / "analytics/example-tech/scratch.json").write_text("{}\n")
    res = sc.commit_read_data(root, "20261017T062923Z", "user", "center", open_rows=[])
    assert res["status"] == "committed" and res["sha"], res
    want = ["analytics/example-film/studio.jsonl", "analytics/example-film/studio_visits.jsonl",
            "analytics/example-tech/studio.jsonl"]
    assert res["paths"] == want, res
    assert changed_in_head(root) == want, changed_in_head(root)
    assert git(root, "rev-parse", "HEAD~1").strip() == head, "one commit"
    msg = git(root, "log", "-1", "--format=%B")
    assert "20261017T062923Z" in msg and "user" in msg and "CF-0786" in msg, msg
    assert porcelain(root) == ["analytics/example-film/daily.jsonl",
                               "analytics/example-tech/scratch.json", "scripts/tool.py"], \
        porcelain(root)
    again = sc.commit_read_data(root, open_rows=[])
    assert again["status"] == "nothing" and not again["paths"], again
    assert git(root, "rev-parse", "HEAD").strip() == res["sha"], "nothing more committed"


def test_not_a_repo_and_not_the_repos_root_commit_nothing():
    plain = TMP / "plain"
    (plain / "analytics/example-film").mkdir(parents=True)
    (plain / "analytics/example-film/studio.jsonl").write_text("{}\n")
    assert sc.commit_read_data(plain, open_rows=[])["status"] == "not_repo"
    outer = repo_root("outer")
    inner = outer / "scripts"
    (inner / "analytics/example-film").mkdir(parents=True)
    (inner / "analytics/example-film/studio.jsonl").write_text("{}\n")
    res = sc.commit_read_data(inner, open_rows=[])
    assert res["status"] == "not_repo", res
    assert "scripts/analytics/example-film/studio.jsonl" in porcelain(outer), "left alone"


def test_under_a_started_batch_the_commit_is_deferred():
    root = repo_root("deferred")
    with open(root / "analytics/example-film/studio.jsonl", "a") as fh:
        fh.write('{"row": 2}\n')
    head = git(root, "rev-parse", "HEAD").strip()
    res = sc.commit_read_data(root, open_rows=[(str(root / "pipeline/example-film/b1"),
                                                "нет batch-done")])
    assert res["status"] == "deferred" and "rights-check" in res["line"], res
    assert res["paths"] == ["analytics/example-film/studio.jsonl"], res
    assert git(root, "rev-parse", "HEAD").strip() == head, "nothing committed"
    assert porcelain(root) == ["analytics/example-film/studio.jsonl"]
    # the real rule, read from the root's pipeline/: a run past its batch-start
    bdir = root / "pipeline" / "example-film" / "2026-10-17T0700Z"
    bdir.mkdir(parents=True)
    ts = runlog.datetime.now(runlog.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (bdir / runlog.EVENTS_FILE).write_text(json.dumps(
        {"ts": ts, "kind": runlog.KIND_MARKER, "status": runlog.M_BATCH_START,
         "stage": "batch-start"}) + "\n")
    rows = sc._open_batches(root)
    assert [Path(d).name for d, _w in rows] == ["2026-10-17T0700Z"], rows
    assert sc.commit_read_data(root)["status"] == "deferred"


def test_a_run_before_its_batch_start_does_not_defer():
    """The executor holds the run's lock from its first stage (CF-0670): the
    rights-check of the next batch is such a run - its HEAD is not recorded
    yet, so the commit lands before it (the rule of the read's own commit)."""
    root = repo_root("prestart")
    bdir = root / "pipeline" / "example-film" / "2026-10-17T0800Z"
    bdir.mkdir(parents=True)

    class Row(tuple):
        why = "держит run-executor.lock"
    real = runlog.open_batches
    runlog.open_batches = lambda r, **kw: [Row((bdir, None, True))]
    try:
        assert sc._open_batches(root) == [], "not started: no HEAD to drift from"
    finally:
        runlog.open_batches = real
    with open(root / "analytics/example-film/studio.jsonl", "a") as fh:
        fh.write('{"row": 3}\n')
    assert sc.commit_read_data(root)["status"] == "committed"


def test_a_dirty_analytics_file_is_a_record_and_other_shared_data_still_stops_batch_start():
    """CF-0895: analytics/ is a record path (runlog.NON_CODE_PATHS) - a read
    left uncommitted no longer refuses `batch-start` nor reads as a stage's code
    edit (stage_code_guard); a shared/*.json still refuses.
    The commit clears both."""
    root = repo_root("guard")
    assert runlog.is_non_code("analytics/example-film/studio.jsonl")
    assert not runlog.is_non_code("shared/notes.json")
    with open(root / "analytics/example-film/studio.jsonl", "a") as fh:
        fh.write('{"row": 2}\n')
    st = runlog.repo_state(runlog.ROOT_REPO, root)
    assert st["dirty"] == [] and runlog.repo_problems(st) == [], st
    (root / "shared/notes.json").write_text('{"notes": ["x"]}\n')
    probs = runlog.repo_problems(runlog.repo_state(runlog.ROOT_REPO, root))
    assert probs and "shared/notes.json" in probs[0], probs
    res = sc.commit_read_data(root, open_rows=[])
    assert res["status"] == "committed", res
    assert res["paths"] == ["analytics/example-film/studio.jsonl"]
    git(root, "checkout", "--", "shared/notes.json")
    assert runlog.repo_problems(runlog.repo_state(runlog.ROOT_REPO, root)) == []


def test_the_launch_commits_the_reads_data_after_the_session():
    root, env = tc.world()
    make_repo(root)
    head = git(root, "rev-parse", "HEAD").strip()
    res = tc._launch(root, env, "read")
    assert tc.wait_done(res["pid"], 60), "the runner ended"
    rec = json.loads((root / "schedule/studio-read/runs" / f"{res['run_id']}.json").read_text())
    assert rec["pid"] == res["pid"] and rec["runner"][2:3] == ["session"], rec
    assert rec["argv"][1:3] == ["-p", "--chrome"], "the session's own argv is kept"
    assert rec["commit"]["status"] == "committed", rec["commit"]
    assert "analytics/example-film/studio_visits.jsonl" in changed_in_head(root)
    assert git(root, "rev-parse", "HEAD~1").strip() == head
    assert porcelain(root) == [], porcelain(root)
    log = Path(res["log"]).read_text()
    assert log.rstrip().splitlines()[-1].startswith("STUDIO_READ_COMMIT: committed"), log
    got = sc.studio_read_result(res["run_id"], root, env)
    assert got["code"] == "read" and got["done"], got
    assert got["commit"]["sha"] == rec["commit"]["sha"], got
    assert "данные чтения закоммичены" in got["line"], got["line"]
    assert sc.running_run(root, env) is None


def test_a_launch_outside_a_repo_still_reads_and_says_nothing_of_git():
    root, env = tc.world()
    res = tc._launch(root, env, "read")
    assert tc.wait_done(res["pid"], 60)
    got = sc.studio_read_result(res["run_id"], root, env)
    assert got["code"] == "read" and got["commit"]["status"] == "not_repo", got
    assert "закоммич" not in got["line"], got["line"]


def test_the_run_is_running_until_the_runners_commit_line():
    rec = {"runner": ["python3", "studio_center.py", "session", "x.json"]}
    said = "STUDIO_READ_RESULT: read - example-film\n"
    assert not sc._over(rec, said), "the session said it, the runner has not committed yet"
    assert sc._over(rec, said + "STUDIO_READ_COMMIT: committed - ...\n")
    assert sc._over({}, said), "a run of before CF-0786 ends with the session's line"


def test_the_cli_commit_read_exits_0_and_says_its_status():
    root = repo_root("cli")
    with open(root / "analytics/example-film/studio.jsonl", "a") as fh:
        fh.write('{"row": 9}\n')
    out = io.StringIO()
    assert sc.main(["commit-read", "--root", str(root)], out=out) == 0
    assert out.getvalue().startswith("studio commit-read: committed"), out.getvalue()
    out = io.StringIO()
    assert sc.main(["commit-read", "--root", str(TMP / "plain")], out=out) == 0
    assert "not_repo" in out.getvalue()


def test_the_prompt_leaves_git_to_the_factory():
    p = sc.read_prompt(["example-film"], "20261017T062923Z", TMP / "runs", "user", "center", TMP)
    assert "git не трогай" in p and "CF-0786" in p, p
    assert "Прочие скрипты в этой сессии не запускай" in p
    assert not any(r.startswith("Bash(git") for r in sc.allowed_tools())


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            import traceback
            traceback.print_exc()
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

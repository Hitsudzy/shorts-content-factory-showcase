#!/usr/bin/env python3
"""CF-0399: a video's record in 05-video-editor.json carries the code that
built it - `videos[].code_shas`, `{label: {"commit", "dirty"} | null}` over
the factory's repos (`runlog.factory_repos()`, CF-0398), read from the repos'
current HEAD when the record is written, never from the batch-start header.

The repos are fixture git repos in a temp dir (a root with `agents/<name>`
beneath it), so the tests say exactly which HEAD and which tree each record
must name. One test reads the real checkout, to prove the wiring without a
stand-in: the record names the HEAD of the repo this script runs from.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"

# CF-0107: never let this file's runs write accounting into a real batch.
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0399-runlog-")))

sys.path.insert(0, str(SCRIPTS))
import write_batch_metadata as wbm  # noqa: E402

DEST = "05-video-editor.json"
GIT_ID = ["-c", "user.email=cf0399@test", "-c", "user.name=cf0399",
          "-c", "commit.gpgsign=false"]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *GIT_ID, *args], capture_output=True,
                        text=True, timeout=30)
    assert cp.returncode == 0, f"git {' '.join(args)} in {d}: {cp.stderr}"
    return cp.stdout.strip()


def repo(d, files=None):
    """A git repo at d with one commit of `files` ({relpath: text})."""
    d.mkdir(parents=True, exist_ok=True)
    git(d, "init", "-q", "-b", "main")
    for rel, text in (files or {"code.py": "x = 1\n"}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init")
    return d


def commit(d, rel="code.py", text="x = 2\n"):
    (d / rel).write_text(text)
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "move")
    return git(d, "rev-parse", "HEAD")


def factory(tmp):
    """<tmp>/f: a root repo (with a tracked run record under pipeline/), a git
    agent `agents/video-editor`, a git agent `agents/analyst`, and a plain
    directory `agents/publisher`."""
    root = repo(Path(tmp) / "f", {"README.md": "root\n",
                                  "scripts/tool.py": "x = 1\n",
                                  "pipeline/runs.md": "| run |\n"})
    # The agents are repos of their own under the root, ignored by it the way
    # the real root ignores agents/.
    (root / ".gitignore").write_text("agents/\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "ignore agents")
    repo(root / "agents" / "video-editor")
    repo(root / "agents" / "analyst")
    (root / "agents" / "publisher").mkdir(parents=True)
    return root


@contextlib.contextmanager
def editor_at(path):
    """The editor's own checkout pointed at a fixture repo."""
    real = wbm.EDITOR_REPO
    wbm.EDITOR_REPO = Path(path)
    try:
        yield
    finally:
        wbm.EDITOR_REPO = real


def head(d):
    return git(d, "rev-parse", "HEAD")


def test_every_repo_its_head_and_a_clean_tree():
    with tempfile.TemporaryDirectory() as tmp:
        root = factory(tmp)
        with editor_at(root / "agents" / "video-editor"):
            got = wbm.code_shas(root)
        assert list(got) == ["root", "agents/analyst", "agents/publisher",
                             "agents/video-editor"], list(got)
        assert got["root"] == {"commit": head(root), "dirty": False}, got["root"]
        for n in ("analyst", "video-editor"):
            assert got[f"agents/{n}"] == {"commit": head(root / "agents" / n),
                                          "dirty": False}, got
        assert got["agents/publisher"] is None, "a directory that is not a repo is null"


def test_uncommitted_code_reads_dirty_and_untracked_files_do_not():
    with tempfile.TemporaryDirectory() as tmp:
        root = factory(tmp)
        ed = root / "agents" / "video-editor"
        an = root / "agents" / "analyst"
        (ed / "code.py").write_text("x = 'uncommitted'\n")        # modified
        (an / "new.py").write_text("y = 1\n")                     # staged
        git(an, "add", "new.py")
        (root / "scratch.txt").write_text("untracked\n")          # untracked only
        with editor_at(ed):
            got = wbm.code_shas(root)
        assert got["agents/video-editor"]["dirty"] is True, got
        assert got["agents/analyst"]["dirty"] is True, got
        assert got["root"]["dirty"] is False, "an untracked file is not code"
        assert got["agents/video-editor"]["commit"] == head(ed), (
            "a dirty tree still names the HEAD it sits on")


def test_the_run_records_of_the_root_are_not_dirty_code():
    """A run writes tracked records of its own under the root (CF-0398's
    RUN_DATA_PATHS); a video built mid-run must not read as uncommitted code."""
    with tempfile.TemporaryDirectory() as tmp:
        root = factory(tmp)
        (root / "pipeline" / "runs.md").write_text("| run |\n| another |\n")
        with editor_at(root / "agents" / "video-editor"):
            assert wbm.code_shas(root)["root"]["dirty"] is False
        # CF-0482: a root *code* file, not README.md - since CF-0479 the
        # root's prose (README/ROADMAP/CHANGELOG/IDEAS, docs/, publish/) is
        # NON_CODE_PATHS too, so editing README proves nothing on the 1.5 line
        # and reads clean there. scripts/ is code under every library version.
        (root / "scripts" / "tool.py").write_text("x = 2\n")
        with editor_at(root / "agents" / "video-editor"):
            assert wbm.code_shas(root)["root"]["dirty"] is True


def test_no_runlog_library_is_null_not_a_crash():
    real = wbm.runlog
    wbm.runlog = object()                      # the shim's silent stand-in has no repos
    try:
        assert wbm.code_shas() is None
    finally:
        wbm.runlog = real


# ---------------------------------------------------------------------------
# main(): the set lands on the records this call writes, and only on them
# ---------------------------------------------------------------------------

def _batch(tmp):
    b = Path(tmp) / "pipeline" / "example-film" / "b1"
    (b / "work").mkdir(parents=True)
    return b


def _video(b, sid):
    work = b / "work" / sid
    work.mkdir(parents=True, exist_ok=True)
    p = work / "plan.json"
    p.write_text(json.dumps({"style": "motion", "blocks": [],
                             "duration": {"total": 12.0, "blocks": 0},
                             "audio": {"duration": 12.0},
                             "output": {"width": 1080, "height": 1920}}))
    return [sid, str(p), str(b / "videos" / f"{sid}.mp4")]


def _write(b, *videos):
    argv = ["write_batch_metadata.py", str(b)]
    for v in videos:
        argv += ["--video", *v]
    real_qc, real_argv = wbm.qc_report, sys.argv
    wbm.qc_report = lambda video, plan: {"passed": True, "failures": [], "notes": [],
                                         "measured": {}}
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            wbm.main()
    finally:
        wbm.qc_report, sys.argv = real_qc, real_argv
    return {v["script_id"]: v for v in json.loads((b / DEST).read_text())["videos"]}


def test_a_rebuild_after_the_code_moved_names_the_new_code():
    """The batch-start header is not the source: a video rewritten after a
    commit carries the new HEAD, the video that was not rewritten keeps the
    one it was built by."""
    with tempfile.TemporaryDirectory() as tmp:
        root = factory(tmp)
        ed = root / "agents" / "video-editor"
        b = _batch(tmp)
        real = wbm.code_shas
        wbm.code_shas = lambda: real(root)
        try:
            with editor_at(ed):
                was = head(ed)
                recs = _write(b, _video(b, "s1"), _video(b, "s2"))
                assert recs["s1"]["code_shas"] == recs["s2"]["code_shas"]
                assert recs["s1"]["code_shas"]["agents/video-editor"] == {
                    "commit": was, "dirty": False}

                now = commit(ed)
                recs = _write(b, _video(b, "s2"))
                assert recs["s2"]["code_shas"]["agents/video-editor"]["commit"] == now
                assert recs["s1"]["code_shas"]["agents/video-editor"]["commit"] == was, (
                    "a record this call did not rewrite must keep the code it was built by")
                assert recs["s2"]["code_shas"]["root"] == recs["s1"]["code_shas"]["root"]

                (ed / "code.py").write_text("x = 'uncommitted'\n")
                recs = _write(b, _video(b, "s1"))
                assert recs["s1"]["code_shas"]["agents/video-editor"] == {
                    "commit": now, "dirty": True}, "a video built from uncommitted code"
        finally:
            wbm.code_shas = real


def test_the_real_checkout_is_the_editor_entry():
    """No stand-in: the record names the HEAD of the checkout this script runs
    from (a worktree included) and the root the shim found."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        rec = _write(b, _video(b, "s1"))["s1"]
        code = rec["code_shas"]
        if code is None:
            print("  (no runlog library reachable - code_shas is null, nothing to compare)")
            return
        assert code["agents/video-editor"]["commit"] == head(AGENT_ROOT), code
        assert isinstance(code["agents/video-editor"]["dirty"], bool)
        assert code["root"] and len(code["root"]["commit"]) == 40, code
        for label, v in code.items():
            assert label == "root" or label.startswith("agents/"), label
            assert v is None or set(v) == {"commit", "dirty"}, (label, v)


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

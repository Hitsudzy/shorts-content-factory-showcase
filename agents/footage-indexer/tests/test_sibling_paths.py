"""CF-0267: the Video Editor's scripts and this agent's `.venv` are found from
the factory root (`_fi_paths.sibling_scripts` / `_fi_paths.venv_bin`), not by
counting `..` from the asking file.

`parent.parent.parent / "video-editor"` was right in `<root>/agents/footage-
indexer/scripts/` and wrong in a harness worktree (`agents/footage-indexer/
.claude/worktrees/<x>/scripts/` -> `.claude/worktrees/video-editor`): every
test file importing `index_footage` died on `ModuleNotFoundError: No module
named 'detect_text_band'`, 13 of 19 files at the time. These tests build each
layout in a temp tree and ask the resolver where the sibling is:

  * the normal layout and the harness-worktree layout both reach
    `<root>/agents/video-editor/scripts`;
  * a FACTORY_ROOT without the sibling (a test's temp root) does not end the
    search - the walk is still asked;
  * a checkout outside any factory tree finds it through FACTORY_ROOT, and
    without it fails with FactoryRootError naming FACTORY_ROOT - for
    `index_footage` itself too, never a ModuleNotFoundError.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import _fi_paths  # noqa: E402
from _tmproot import tmp_root  # noqa: E402

_TMP = tmp_root("cf0267-")


def _env(root=None):
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_ROOT"}
    if root is not None:
        env["FACTORY_ROOT"] = str(root)
    return env


def _ask(scripts_dir, code, root=None, py=None):
    """Run `code` with `scripts_dir` first on sys.path; (rc, stdout, stderr)."""
    prog = f"import sys; sys.path.insert(0, {str(scripts_dir)!r})\n{code}"
    out = subprocess.run([py or sys.executable, "-c", prog], capture_output=True,
                         text=True, env=_env(root), timeout=120)
    return out.returncode, out.stdout.strip(), out.stderr


def _fake_root(agent_dir_rel):
    """A temp factory root: shared/runlog/runlog.py, agents/video-editor/scripts,
    and this repo's `_fi_paths.py` copied to `<agent_dir_rel>/scripts/`."""
    root = Path(tempfile.mkdtemp(dir=_TMP)).resolve()
    (root / "shared" / "runlog").mkdir(parents=True)
    (root / "shared" / "runlog" / "runlog.py").write_text("")
    (root / "agents" / "video-editor" / "scripts").mkdir(parents=True)
    scripts = root / agent_dir_rel / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPTS / "_fi_paths.py", scripts / "_fi_paths.py")
    return root, scripts


ASK = "import _fi_paths; print(_fi_paths.sibling_scripts('video-editor'))"


def test_in_this_checkout_the_sibling_is_under_the_factory_root():
    got = _fi_paths.sibling_scripts("video-editor")
    assert got == _fi_paths.root_candidates()[-1] / "agents" / "video-editor" / "scripts", got
    assert (got / "detect_text_band.py").is_file(), got


def test_the_normal_layout_reaches_the_sibling():
    root, scripts = _fake_root("agents/footage-indexer")
    rc, out, err = _ask(scripts, ASK)
    assert rc == 0, err
    assert Path(out) == root / "agents" / "video-editor" / "scripts", out


def test_a_harness_worktree_reaches_the_sibling_not_claude_worktrees():
    root, scripts = _fake_root("agents/footage-indexer/.claude/worktrees/cf-x")
    rc, out, err = _ask(scripts, ASK)
    assert rc == 0, err
    assert Path(out) == root / "agents" / "video-editor" / "scripts", out


def test_a_factory_root_without_the_sibling_falls_back_to_the_walk():
    root, scripts = _fake_root("agents/footage-indexer")
    bare = Path(tempfile.mkdtemp(dir=_TMP))           # a test root: channels/ only
    (bare / "channels").mkdir()
    rc, out, err = _ask(scripts, ASK, root=bare)
    assert rc == 0, err
    assert Path(out) == root / "agents" / "video-editor" / "scripts", out


def test_outside_the_tree_factory_root_finds_it():
    root, _ = _fake_root("agents/footage-indexer")
    lone = Path(tempfile.mkdtemp(dir=_TMP)) / "footage-indexer" / "scripts"
    lone.mkdir(parents=True)
    shutil.copy(SCRIPTS / "_fi_paths.py", lone / "_fi_paths.py")
    rc, out, err = _ask(lone, ASK, root=root)
    assert rc == 0, err
    assert Path(out) == root / "agents" / "video-editor" / "scripts", out


def test_outside_the_tree_without_factory_root_says_so():
    lone = Path(tempfile.mkdtemp(dir=_TMP)) / "footage-indexer" / "scripts"
    lone.mkdir(parents=True)
    shutil.copy(SCRIPTS / "_fi_paths.py", lone / "_fi_paths.py")
    rc, out, err = _ask(lone, ASK)
    assert rc != 0
    assert "FactoryRootError" in err and "set FACTORY_ROOT" in err, err
    assert "ModuleNotFoundError" not in err, err


def test_index_footage_outside_the_tree_fails_with_the_message_not_an_import_error():
    lone = Path(tempfile.mkdtemp(dir=_TMP)) / "footage-indexer"
    shutil.copytree(SCRIPTS, lone / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    rc, out, err = _ask(lone / "scripts", "import index_footage",
                        py=str(_fi_paths.venv_bin("python3")))
    assert rc != 0
    assert "FactoryRootError" in err and "set FACTORY_ROOT" in err, err[-800:]
    assert "ModuleNotFoundError" not in err, err[-800:]


def test_the_venv_comes_from_the_root_when_the_checkout_has_none():
    root, _ = _fake_root("agents/footage-indexer")
    venv = root / "agents" / "footage-indexer" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python3").write_text("")
    lone = Path(tempfile.mkdtemp(dir=_TMP)) / "footage-indexer" / "scripts"
    lone.mkdir(parents=True)
    shutil.copy(SCRIPTS / "_fi_paths.py", lone / "_fi_paths.py")
    code = "import _fi_paths; print(_fi_paths.venv_bin('python3'))"
    rc, out, err = _ask(lone, code, root=root)
    assert rc == 0, err
    assert Path(out) == venv / "python3", out
    rc, out, err = _ask(lone, code)                  # nowhere to look: own path
    assert rc == 0, err
    assert Path(out) == lone.parent.resolve() / ".venv" / "bin" / "python3", out


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # a crash is a failure, not a skip
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)

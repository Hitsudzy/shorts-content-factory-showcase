"""CF-0107: the one place in this repo that finds the factory's run-accounting
library (`<root>/shared/runlog/runlog.py`) and hands it to the scripts:

    from _runlog import runlog

    @runlog.script("footage-indexer", "fetch", name="fetch_footage.py")
    def main(argv=None): ...

Root lookup, same convention as shared/inserts/underlay.py: `FACTORY_ROOT`
wins, otherwise walk this file's ancestors for `shared/runlog/runlog.py`.
That walk works from the normal checkout (`agents/footage-indexer/scripts/`) and
from a worktree (`agents/footage-indexer/.claude/worktrees/<x>/scripts/`) alike,
because both live under the root.

If the root cannot be found at all (this repo copied somewhere on its own),
`runlog` is a silent stand-in with the same surface - accounting must never
break a fetch - and one line on stderr says so. Batch-dir resolution is the
library's own business: with no batch to write to it warns and does nothing,
so tests that import the scripts without a batch stay unaffected.
"""
import contextlib
import os
import subprocess
import sys
from pathlib import Path

RUNLOG_REL = Path("shared") / "runlog" / "runlog.py"


def factory_root():
    """The factory root: FACTORY_ROOT if set, else the nearest ancestor of this
    file that holds shared/runlog/runlog.py."""
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for p in Path(__file__).resolve().parents:
        if (p / RUNLOG_REL).is_file():
            return p
    raise RuntimeError("factory root not found: set FACTORY_ROOT")


# CF-0267: the sibling / venv resolver (sibling_scripts, venv_bin,
# FactoryRootError) lives in `_fi_paths.py`, not here. `_runlog` is the one
# module name every agent repo has, so a process that imports this repo's
# scripts from another repo (video-editor's tests do) may already hold *that*
# repo's `_runlog` in sys.modules; anything only this file defines is then
# unreachable. Keep this file to what every `_runlog` shares: `runlog` and
# `factory_root()`.


class _Silent:
    """runlog's surface with no accounting behind it (root not found)."""

    @staticmethod
    @contextlib.contextmanager
    def run(*args, **kwargs):
        yield {}

    @staticmethod
    def script(*args, **kwargs):
        return lambda fn: fn

    @staticmethod
    @contextlib.contextmanager
    def child(*args, **kwargs):
        yield {}

    @staticmethod
    def run_child(cmd, *, tool=None, batch_dir=None, parent=None, stage=None, step=None,
                  video=None, attempt=None, params=None, **popen_kw):
        return subprocess.run(cmd, **popen_kw)

    @staticmethod
    def annotate(*args, **kwargs):
        return None

    @staticmethod
    def current_id():
        return None


def _load():
    try:
        root = factory_root()
    except RuntimeError as exc:
        sys.stderr.write(f"[runlog] {exc}; run accounting is off for this process\n")
        return _Silent()
    lib_dir = str(root / RUNLOG_REL.parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    try:
        import runlog as mod
    except ImportError as exc:
        # CF-0267: a FACTORY_ROOT that is a test's temp root (channels/ and
        # nothing else) - accounting off, the same as no root at all.
        sys.stderr.write(f"[runlog] no {RUNLOG_REL} under {root} ({exc}); "
                         f"run accounting is off for this process\n")
        return _Silent()
    return mod


runlog = _load()

"""CF-0107: the one place in this repo that finds the factory's run-accounting
library (`<root>/shared/runlog/runlog.py`) and hands it to the scripts:

    from _runlog import runlog

    @runlog.script("content-researcher", "check-budget", name="check_narration_budget.py")
    def main(argv=None): ...

Root lookup, same convention as shared/inserts/underlay.py: `FACTORY_ROOT`
wins, otherwise walk this file's ancestors for `shared/runlog/runlog.py`.
That walk works from the normal checkout (`agents/content-researcher/scripts/`) and
from a worktree (`agents/content-researcher/.claude/worktrees/<x>/scripts/`) alike,
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

import _pipe_safe  # CF-0915: scripts/, on sys.path wherever _runlog is imported from

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
    import runlog as mod
    return mod


class _PipeSafeScripts:
    """CF-0915 / CF-0916: the library as loaded, with one difference -
    `script(...)` also puts the entry under `_pipe_safe.cli`, so every
    `@runlog.script` CLI of this repo survives a reader that closes its pipe
    early (`| head`): the check runs to its end and exits with its own code,
    which the run event records as before (`SystemExit: N` / done), instead
    of a `BrokenPipeError` the triage files as a crash. Everything else is
    the library's own attribute, read through."""

    def __init__(self, lib):
        self._lib = lib

    def script(self, *args, **kwargs):
        deco = self._lib.script(*args, **kwargs)
        return lambda fn: deco(_pipe_safe.cli(fn))

    def __getattr__(self, name):
        return getattr(self._lib, name)


runlog = _PipeSafeScripts(_load())

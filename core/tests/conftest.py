"""CF-0339: no sampler daemon of a test run outlives the test run.

The leak this closes was a hundred and forty `shared/runlog/sampler.py --daemon`
processes, ~270 % CPU together, all of them pointed at temp trees of tests that
had finished hours earlier - the wall of every following run. Two lines hold it
now: the daemon exits by itself when its run goes idle or its batch disappears
(`sampler.py`), and every temp tree of a test stops its samplers and removes
itself at exit (`tests/_tmproot.py`).

This is the backstop under both: whatever a test forgot, the session does not
end while a daemon it started is still sampling a temp directory. It only ever
touches daemons that (a) were not there when the session started and (b) point
inside the system temp directory - never a daemon of a real batch, which may
well belong to a run happening on this machine right now. Each one is named on
stderr, so a test that starts leaking again is visible rather than merely
cleaned up after.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

from pathlib import Path

import pytest

TMP_PREFIX = os.path.realpath(tempfile.gettempdir())

# CF-0591: under pytest too, a notifying source writes to a temp journal and the
# `log` backend alone (tests/run_tests.py does the same per file).
os.environ["NOTIFY_STATE_DIR"] = tempfile.mkdtemp(prefix="notify-pytest-")
os.environ["NOTIFY_BACKENDS"] = "log"
# CF-0652: and a question asked by a source with no root of its own goes to a
# temp journal of questions, never the factory's needs-you/.
os.environ["NEEDS_YOU_DIR"] = tempfile.mkdtemp(prefix="needs-you-pytest-")
# CF-0684: the same for the queue of the user's requests (shared/operator_requests.py).
os.environ["REQUESTS_DIR"] = tempfile.mkdtemp(prefix="requests-pytest-")
# CF-0747: an acceptance in a test starts no card build - no model by accident.
os.environ["PUBLISH_CARD_AUTOBUILD"] = "0"


def _daemons():
    """{pid: batch dir} for every live sampler daemon on this machine."""
    try:
        cp = subprocess.run(["ps", "-axo", "pid=,command="],
                            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in cp.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or "--daemon" not in parts:
            continue
        if not any(p.endswith("sampler.py") for p in parts):
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        i = parts.index("--daemon")
        found[pid] = parts[i + 1] if i + 1 < len(parts) else ""
    return found


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def no_sampler_daemon_is_left_behind():
    before = set(_daemons())
    yield
    leaked = {pid: d for pid, d in _daemons().items()
              if pid not in before and os.path.realpath(d or "/").startswith(TMP_PREFIX)}
    if not leaked:
        return
    for pid, d in sorted(leaked.items()):
        print(f"conftest: sampler daemon {pid} left behind on {d} - stopping it (CF-0339)",
              file=sys.stderr)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + 3.0
    while any(_alive(p) for p in leaked) and time.monotonic() < deadline:
        time.sleep(0.05)
    for pid in leaked:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


# --------------------------------------------------------------------------
# CF-0326: who owns each red. DoD 1.4.1 item 2 - the root suite carries no
# unattributed failure. `pytest` is what the auto-dev driver and the workers
# actually run, so the attribution has to reach a reader here too, and out of
# the same roster the house runner reads (tests/red_roster.py) rather than out
# of a second copy of the rule.
#
# It adds no verdict: an unattributed red is already a red, and this prints
# after pytest's own summary. A roster whose owner has been closed is reported
# as unattributed, which is exactly the defect CF-0326 was raised about.
# --------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _failures_of(terminalreporter):
    """(file name, check name) for every failed or errored test pytest saw."""
    out = []
    for key in ("failed", "error"):
        for rep in terminalreporter.stats.get(key, []):
            nodeid = getattr(rep, "nodeid", "") or ""
            path, _, rest = nodeid.partition("::")
            name = Path(path).name
            check = rest.split("::")[-1].split("[")[0] if rest else None
            out.append((name, check or None))
    seen, unique = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def pytest_terminal_summary(terminalreporter, exitstatus=0, config=None):
    failures = _failures_of(terminalreporter)
    if not failures:
        return
    try:
        import red_roster
    except Exception as exc:                            # pragma: no cover
        terminalreporter.write_line(
            f"red_roster unavailable ({exc}) - failures reported without "
            f"attribution (CF-0326)")
        return
    try:
        terminalreporter.write(red_roster.report(failures))
    except Exception as exc:                            # pragma: no cover
        terminalreporter.write_line(f"attribution failed ({exc}) - CF-0326")


# --------------------------------------------------------------------------
# CF-0384: each test file runs in the process it would have had on its own.
#
# The house runner (tests/run_tests.py) gives every file its own interpreter;
# pytest collects every file into one. The root files set their environment up
# at module level - HOME, RUNLOG_STATE_DIR, FACTORY_ROOT, RUNLOG_PROJECTS_DIR,
# a `tmp_root()` of their own - and then `import runlog`, whose module-level
# state (`_machine_cache`, whatever it read at import) was then shared by every
# file after the first. Eleven checks were green alone and red together, and
# which ones depended on collection order.
#
# The isolation is a property of the run, kept here once rather than in every
# file, so a new root test file cannot reintroduce the leak by forgetting it:
#
#   * while pytest imports a test module, the environment, `sys.path` and the
#     project modules (anything loaded from this repository - `runlog`,
#     `summary`, the agents' own modules) are the session's baseline, taken
#     before the first test file was imported; whatever the file set up at
#     import is recorded as that file's context and then taken back out, so
#     the next file imports its own fresh `runlog` under its own environment;
#   * while that file's tests run, its recorded context is put back - the
#     environment it set, the `sys.path` it built, the very module objects it
#     bound at import (so a function-level `import runlog` inside a test gets
#     the object the file's globals hold);
#   * after its last test the session returns to the baseline, dropping any
#     project module the tests imported lazily and any variable they leaked.
#
# Stdlib and site-packages modules are never unloaded: no file configures
# them, and C extensions do not survive a re-import.
# --------------------------------------------------------------------------
import sysconfig

_REPO = Path(__file__).resolve().parent.parent
_REPO_ROOTS = tuple({str(_REPO), os.path.realpath(str(_REPO))})
_FOREIGN_ROOTS = tuple({os.path.realpath(p) for p in
                        (sysconfig.get_paths().get(k) for k in
                         ("stdlib", "platstdlib", "purelib", "platlib"))
                        if p})


def _is_project_module(name, mod):
    """A module loaded from this repository that a test file may have configured."""
    if name == "conftest" or name.startswith("test_"):
        return False                     # pytest's own conftest and the test modules
    f = getattr(mod, "__file__", None)
    if not f:
        return False
    a, r = os.path.abspath(f), os.path.realpath(f)
    if "site-packages" in r or any(r.startswith(p + os.sep) for p in _FOREIGN_ROOTS):
        return False
    return any(a.startswith(p + os.sep) or r.startswith(p + os.sep) for p in _REPO_ROOTS)


def _project_modules():
    return {n: m for n, m in list(sys.modules.items())
            if m is not None and _is_project_module(n, m)}


class _Context:
    """Environment, import path and project modules of one moment of the session."""

    __slots__ = ("environ", "path", "modules")

    def __init__(self, environ, path, modules):
        self.environ, self.path, self.modules = environ, path, modules

    @classmethod
    def capture(cls):
        return cls(dict(os.environ), list(sys.path), _project_modules())

    def install(self):
        # PYTEST_CURRENT_TEST and friends belong to pytest's own bookkeeping of
        # the moment, not to any file's context: they pass through untouched.
        target = {k: v for k, v in self.environ.items() if not k.startswith("PYTEST_")}
        target.update((k, v) for k, v in os.environ.items() if k.startswith("PYTEST_"))
        if dict(os.environ) != target:
            os.environ.clear()
            os.environ.update(target)
        sys.path[:] = self.path
        for name in list(_project_modules()):
            if name not in self.modules:
                del sys.modules[name]
        sys.modules.update(self.modules)


_BASELINE = []                  # [_Context], taken when the first test module is imported
_FILE_CONTEXT = {}              # test module path -> the _Context it set up at import


def _baseline():
    if not _BASELINE:
        _BASELINE.append(_Context.capture())
    return _BASELINE[0]


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    if not isinstance(collector, pytest.Module):
        yield
        return
    base = _baseline()
    base.install()
    try:
        yield                    # pytest imports the test module here
    finally:
        _FILE_CONTEXT[str(collector.path)] = _Context.capture()
        base.install()


@pytest.fixture(scope="module", autouse=True)
def _each_file_in_its_own_context(request):
    ctx = _FILE_CONTEXT.get(str(request.path))
    if ctx is None:
        yield
        return
    ctx.install()
    try:
        yield
    finally:
        _baseline().install()

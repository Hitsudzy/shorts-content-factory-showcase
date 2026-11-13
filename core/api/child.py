"""The API's one runner of a child process.

The center reads a few things through a child of the factory's own code: the
agents' status (`scripts/agents status`, `versions.py`), the archive's dry run
(`archive_publish_month.py --dry-run [--json]`, `maintenance.py`) and a
channel's ending through the Video Editor's reader (`ending.py`); and it runs
one write so, confirmed by the user - the month archive's real run
(`archive_publish_month.py --publish-only --by user --via center`, CC-0104).
Each is bounded by a timeout. One confirmed start is detached (CC-0114, a
channel's ending render, `brand_ending.py`): `detach` runs a short launcher
child here, bounded like the rest, and the launcher hands the work to the
factory's own detached start - `shared/batch_schedule.py`'s, the one a
batch launch goes through (a session of its own, stdin on DEVNULL, the output
in `schedule/logs/<day>-<label>.log`) - prints the pid and the log, and ends;
the render lives on in its own session, and the center never signals it. This module is where they run, so that nothing else in `api/` imports
`subprocess`, and nothing in `api/` - this module included - names a signal,
a kill or a `Popen` (pinned by
test_cc_api_batches_going.py::test_nothing_here_stops_or_signals_but_the_one_stop_and_resume:
the center stops a batch only through `batch_control.stop`).

`subprocess.run(..., timeout=)` ends its own child when the timeout passes and
raises `Timeout`; the center never signals any other process - neither a
batch's, nor one it did not start right here.

    run(cmd, timeout=, cwd=, env=)    -> (returncode, stdout, stderr), now
    start(cmd, timeout=, cwd=, env=)  -> a `Started`: the same run in a thread,
                                         begun now, read later by
                                         `.communicate()` (stdout, stderr) and
                                         `.returncode` - so a caller reads the
                                         factory's rows while the child runs
    detach(argv, root=, day=, label=, timeout=, env=)
                                      -> (pid, log): `argv` started detached
                                         by the factory's own start; `Detach`
                                         when the launcher did not answer so
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading

from .settings import CODE

Timeout = subprocess.TimeoutExpired

#: The factory's detached start (a batch launch's), loaded by path in the launcher.
DETACHED_START = "shared/batch_schedule.py"
DETACH_TIMEOUT = 30

# The launcher: the factory's own detached start, one JSON line out. Its
# environ is {} - the log goes to <root>/schedule/logs whatever the API's
# environment says of the schedule's state directory.
_LAUNCHER = r"""
import importlib.util, json, sys
mod_path, root, day, label, argv = sys.argv[1:5] + [json.loads(sys.argv[5])]
spec = importlib.util.spec_from_file_location("batch_schedule_for_the_center", mod_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
proc, log = mod.spawn_detached(argv, root, day, label, environ={})
print(json.dumps({"pid": proc.pid, "log": str(log)}))
"""


class Detach(RuntimeError):
    """The launcher did not start the work: `lines` say why (its exit code,
    the tail of its stderr)."""

    def __init__(self, message, lines):
        super().__init__(message)
        self.lines = list(lines)


def run(cmd, *, timeout, cwd=None, env=None):
    """The child, run to its end: (returncode, stdout, stderr). `Timeout` when
    it did not answer in `timeout` s (the child is then already ended),
    `OSError` when it did not start."""
    cp = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                        timeout=timeout)
    return cp.returncode, cp.stdout, cp.stderr


class Started:
    """`run` in a daemon thread, begun at construction."""

    def __init__(self, cmd, *, timeout, cwd=None, env=None):
        self.returncode = None
        self._out = self._exc = None
        self._thread = threading.Thread(target=self._go, args=(cmd, timeout, cwd, env),
                                        name="cc-api-child", daemon=True)
        self._thread.start()

    def _go(self, cmd, timeout, cwd, env):
        try:
            self.returncode, out, err = run(cmd, timeout=timeout, cwd=cwd, env=env)
            self._out = (out, err)
        except BaseException as e:                             # noqa: BLE001 - re-raised
            self._exc = e

    def communicate(self, timeout=None):
        """(stdout, stderr) once the child has ended. Re-raises what `run`
        raised: `Timeout` (the child did not answer in the timeout given at
        start - already ended) or `OSError` (it did not start). `timeout` here
        is accepted for the shape of `Popen.communicate` and not needed: the
        run itself is bounded."""
        self._thread.join()
        if self._exc is not None:
            raise self._exc
        return self._out


def start(cmd, *, timeout, cwd=None, env=None):
    """`run`, begun now in a thread; see `Started`."""
    return Started(cmd, timeout=timeout, cwd=cwd, env=env)


def detach(argv, *, root, day, label, timeout=DETACH_TIMEOUT, env=None):
    """`argv` started detached by the factory's own start (see the module's
    docstring), its cwd the root: (pid, log - the absolute path of
    `<root>/schedule/logs/<day>-<label>.log`). `Timeout` when the launcher
    did not answer in `timeout` s, `OSError` when it did not start, `Detach`
    when it answered without a pid."""
    cmd = [sys.executable, "-c", _LAUNCHER, str(CODE / DETACHED_START), str(root), str(day),
           str(label), json.dumps([str(a) for a in argv])]
    rc, out, err = run(cmd, timeout=timeout, cwd=str(root), env=env)
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    try:
        if rc != 0 or not lines:
            raise ValueError(f"exit {rc}")
        doc = json.loads(lines[-1])
        return int(doc["pid"]), str(doc["log"])
    except (ValueError, KeyError, TypeError) as e:
        tail = [ln for ln in (err or "").splitlines() if ln.strip()][-3:]
        raise Detach(f"the detached start did not answer: {e}", [f"launcher: {e}", *tail]) \
            from None

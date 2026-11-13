#!/usr/bin/env python3
"""CF-0670: who holds a run's `run-executor.lock` - one answer for
`shared/batch_control.py` (stop, resume, rebuild: CF-0667/CF-0668) and for
`runlog.open_batches` / `runlog batch-active` (the one-batch-at-a-time rule).

The executor (`shared/run_executor.py`, CF-0203) takes an exclusive `fcntl.flock`
on `<batch>/run-executor.lock` for the whole run and writes `pid N since TS`
into it; the kernel releases the lock when the holder dies, the file stays.
So, as CF-0667 put it:

* **free** - nobody holds the lock (no file, or a file left by a dead executor);
* **executor** - the lock is held, the pid the file names (or the one the
  caller hands in from `run-state.json`) runs `run_executor.py` - not its
  `_exec` step wrapper, not a zombie;
* **unknown** - the lock is held and the pid is not recognised (no pid, a pid
  that is gone or runs something else). CF-0667 refuses on this, never guesses;
  `open_batches` counts the run open on it (CF-0670): a held lock is held by a
  live process, and a second batch beside an unexplained holder is the guess.

The probe is a shared, non-blocking flock released at once - two probes do not
see each other, and only a held lock costs a `ps` call. Never raises.
"""
import fcntl
import re
import subprocess
from pathlib import Path

TASK = "CF-0670"
LOCK_FILE = "run-executor.lock"          # run_executor.LOCK_FILE
_LOCK_PID = re.compile(r"pid\s+(\d+)")

FREE, EXECUTOR, UNKNOWN = "free", "executor", "unknown"


def ps(pid):
    """`(stat, command)` of a live pid, None when there is none."""
    try:
        cp = subprocess.run(["ps", "-ww", "-o", "stat=", "-o", "command=", "-p", str(int(pid))],
                            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, OverflowError):
        return None
    line = cp.stdout.strip()
    if cp.returncode != 0 or not line:
        return None
    stat, _, cmd = line.partition(" ")
    return stat, cmd.strip()


def is_executor(pid):
    """The pid runs `run_executor.py` (not its `_exec` wrapper) and is no zombie."""
    got = ps(pid) if pid else None
    if not got or got[0].startswith("Z"):
        return False
    words = got[1].split()
    return any(w.endswith("run_executor.py") for w in words) and "_exec" not in words


def lock_held(batch):
    """True while some process holds `<batch>/run-executor.lock`."""
    try:
        fh = open(Path(batch) / LOCK_FILE, "r")
    except OSError:
        return False
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False


def lock_pid(batch):
    """The pid the lock file names, else None."""
    try:
        m = _LOCK_PID.search((Path(batch) / LOCK_FILE).read_text())
    except (OSError, ValueError):
        return None
    return int(m.group(1)) if m else None


def holder(batch, pid=None):
    """`{pid, held, alive, state}` of the lock of `batch`: `state` is FREE,
    EXECUTOR or UNKNOWN (see the module), `alive` is `state == EXECUTOR`.
    `pid`: the one to check when the lock file names none (`run-state.json`'s
    `executor.pid`). A batch with no lock file is free at the cost of a stat."""
    if not (Path(batch) / LOCK_FILE).exists():
        return {"pid": pid, "held": False, "alive": False, "state": FREE}
    pid = lock_pid(batch) or pid
    held = lock_held(batch)
    alive = bool(held and pid and is_executor(pid))
    state = EXECUTOR if alive else (UNKNOWN if held else FREE)
    return {"pid": pid, "held": held, "alive": alive, "state": state}


def why(h):
    """One Russian line for the user: why the lock keeps the run open, else None."""
    if h["state"] == EXECUTOR:
        return f"исполнитель жив (pid {h['pid']})"
    if h["state"] == UNKNOWN:
        who = f"pid {h['pid']}" if h["pid"] else "pid не записан"
        return (f"{LOCK_FILE} держит не исполнитель ({who}) - неизвестный держатель, "
                f"считается открытым (CF-0667)")
    return None

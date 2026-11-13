"""CF-0339: a temp tree for a test file that cannot outlive the test process.

Four test files build their fixtures under `tempfile.mkdtemp()` at import time
and remove them in their `if __name__ == "__main__"` block - which pytest never
runs. The full set is run by pytest, so every one of those trees stayed on
disk, and with it every `runlog` sampler daemon started inside it: each daemon
kept a directory that still existed and a pid-file that still named it, so none
of its self-exits could fire and it sampled an empty machine until its 24 h cap.
Three runs of the set left 140 of them, ~270 % CPU together - the wall of the
next run.

    from _tmproot import tmp_root
    TMP = tmp_root("stopcock-test-")

The tree is removed and the samplers under it are stopped at interpreter exit,
whichever way the file was run. This is the second line only: the daemon itself
now exits when its run goes idle or its events file disappears (`sampler.py`,
CF-0339), so a test that forgets this helper leaks nothing for longer than
`sampler.IDLE_MINUTES`.
"""
import atexit
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path

__all__ = ["tmp_root", "stop_samplers"]

PID_FILE = "RUN_SAMPLER.pid"


def _pids_under(root):
    for pf in Path(root).rglob(PID_FILE):
        try:
            yield pf, int(pf.read_text().strip().split()[0])
        except (OSError, ValueError, IndexError):
            continue


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


def stop_samplers(root, timeout=3.0):
    """Stop every sampler daemon whose pid-file sits under root. Returns their count."""
    stopped = []
    for pf, pid in _pids_under(root):
        if not _alive(pid):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except OSError:
            pass
    deadline = time.monotonic() + timeout
    while any(_alive(p) for p in stopped) and time.monotonic() < deadline:
        time.sleep(0.05)
    for pid in stopped:                       # a daemon wedged in a probe gets no second chance
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    return len(stopped)


def _cleanup(root):
    try:
        stop_samplers(root)
    finally:
        for _ in range(3):                    # a straggler of the test may still be writing
            shutil.rmtree(root, ignore_errors=True)
            if not Path(root).exists():
                return
            time.sleep(0.2)


def tmp_root(prefix):
    """mkdtemp() whose tree is removed - and whose samplers are stopped - at exit."""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(_cleanup, root)
    # CF-0591: a file run by hand gets the runner's isolation of the notification
    # bus too - its journal in this tree, the `log` backend alone.
    os.environ.setdefault("NOTIFY_STATE_DIR", str(root / "notify-state"))
    os.environ["NOTIFY_BACKENDS"] = "log"
    # CF-0747: and an acceptance starts no card build (no model by accident).
    os.environ["PUBLISH_CARD_AUTOBUILD"] = "0"
    return root

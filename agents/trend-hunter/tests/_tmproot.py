"""CF-0489: a temp tree for a test file that cannot outlive the test process.

Same helper as the factory root's `tests/_tmproot.py` (CF-0339/CF-0378) and
the other agents' (CF-0489); brought here by CF-0520. Two trend-hunter test
files built a module-level `tempfile.mkdtemp()` and never removed it: one
`th-apikey-*` (test_api_key.py) and one `th-runlog-*` (test_runlog_events.py)
per full run - 65 and 122 of them in the real TMPDIR by 2026-10-03. Each now
builds under one root of its own:

    from _tmproot import tmp_root
    TMP = tmp_root("th-runlog-")
    (TMP / "state").mkdir()

The tree is removed and any runlog sampler under it is stopped at interpreter
exit, whichever way the file was run (directly, by run_tests.py, or imported
by a sibling test for its helpers). `tests/run_tests.py` fails a file that
still leaves anything in its TMPDIR (CF-0489, CF-0520).
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
    return root

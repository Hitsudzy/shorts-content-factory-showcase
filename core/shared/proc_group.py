#!/usr/bin/env python3
"""CF-0655: kill a whole process group and wait until the group is empty.

Every root process that runs a command in its own session
(`start_new_session=True`, so the command is the leader and its pid is the
group id) and kills it past a ceiling used to wait only for the direct child
after SIGTERM: the child died, the wait ended, and a grandchild in the same
group that caught or ignored SIGTERM outlived the ceiling - SIGKILL was never
sent. Here the wait is for the group:

    import proc_group
    proc_group.kill_group(pgid, grace_s, reap=p.poll)   # "term" | "kill" | "survived"

`group_gone(pgid)` is `os.killpg(pgid, 0)`: ProcessLookupError means nobody is
left. PermissionError counts as empty too - on macOS a group whose only members
are zombies answers EPERM (CF-0504). A zombie leader that is our own child keeps
the group alive on Linux, so the caller passes `reap` (its `Popen.poll`) and it
is called on every tick.

Standard library only: `shared/factrule/` and `shared/runlog/` load this file
by path (importlib), the standalone answerer included.
"""
import os
import signal
import time

POLL_S = 0.05
KILL_WAIT_S = 5.0


def group_gone(pgid):
    """True when no process is left in group `pgid` (or only zombies, macOS)."""
    try:
        os.killpg(int(pgid), 0)
    except ProcessLookupError:
        return True
    except PermissionError:                 # macOS: a zombies-only group (CF-0504)
        return True
    except (OSError, ValueError, TypeError):
        return True
    return False


def wait_gone(pgid, timeout_s, *, reap=None, poll_s=POLL_S):
    """Wait up to `timeout_s` for group `pgid` to empty; True when it did.
    `reap` (e.g. `Popen.poll`) is called each tick so our own dead leader
    does not stay a zombie member."""
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        if reap is not None:
            try:
                reap()
            except Exception:               # noqa: BLE001 - reaping is best effort
                pass
        if group_gone(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)


def signal_group(pgid, sig):
    """killpg, quiet when the group is already gone. False when not sent."""
    try:
        os.killpg(int(pgid), sig)
        return True
    except (OSError, ValueError, TypeError):
        return False


def kill_group(pgid, grace_s, *, reap=None, kill_wait_s=KILL_WAIT_S, poll_s=POLL_S):
    """SIGTERM to the group, wait up to `grace_s` for the WHOLE group to empty,
    SIGKILL to the group when it did not, and wait up to `kill_wait_s` more.
    "term" - empty after SIGTERM; "kill" - empty after SIGKILL; "survived" -
    something is still in the group (stuck in the kernel, or not ours)."""
    signal_group(pgid, signal.SIGTERM)
    if wait_gone(pgid, grace_s, reap=reap, poll_s=poll_s):
        return "term"
    signal_group(pgid, signal.SIGKILL)
    return "kill" if wait_gone(pgid, kill_wait_s, reap=reap, poll_s=poll_s) else "survived"

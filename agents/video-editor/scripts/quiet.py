#!/usr/bin/env python3
"""CF-0098: render logs on disk, a short summary in the operator's context.

Remotion's, ffmpeg's and qc_render.py's output used to land in the operator's
context on every attempt - the main source of `cache_creation` growth on the
stage (batch 2026-09-03T2037Z: 27M tokens for four videos whose machine
render time was 5-6 minutes each). The three wrappers (`render_video.py`,
`build_soundtrack.py`, `qc_render.py`) share this helper so the behaviour is
one implementation, on by default, and not a matter of operator discipline:

    --summary   (default) full stdout/stderr -> <batch>/logs/<slug>-attempt-<n>.log
                (appended, one header per step); the terminal gets at most
                MAX_SUMMARY_LINES lines: return code, the failed blocks with
                their scores, the attempt number, the path to the full log.
    --quiet     the same as --summary.
    --verbose   the old behaviour: everything on the terminal (and still in
                the log when there is one - the log is the record either way).

The log lives beside the batch, not in the work dir, so `ls <batch>/logs`
lists every attempt of every video in one place.
"""
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import attempts
import common  # CF-0135: media_timeout() - the ceiling, defined in one place
from _runlog import runlog  # CF-0107: the child event of the wrapped binary

MAX_SUMMARY_LINES = 20
TAIL_LINES = 6           # of a failed step's log that the summary quotes
LINE_WIDTH = 200         # a summary line is cut here; the log keeps the rest
# CF-0135: how long the killed child's reader is given to drain what is
# already buffered before this thread abandons it. Remotion spawns Chrome, and
# a grandchild can hold the inherited pipe open after its parent is dead, so
# this wait is bounded too - otherwise the ceiling just moves from the read to
# the cleanup. The reader is a daemon and its writes are switched off below,
# so abandoning it costs nothing.
KILL_DRAIN_SECONDS = 1.0
# Lines that name a path or the stop signal are never cut - they are the
# point of the summary, not decoration.
NO_CLIP_PREFIXES = ("rendered ->", "soundtrack ->", "NEEDS-YOU", "  log:")


def add_args(parser):
    """--summary/--quiet/--verbose on a wrapper's argparse parser."""
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--summary", "--quiet", dest="summary", action="store_true",
                   default=True,
                   help="(default) full output to the attempt log on disk, "
                        f"<= {MAX_SUMMARY_LINES} summary lines on the terminal")
    g.add_argument("--verbose", dest="summary", action="store_false",
                   help="the pre-CF-0098 behaviour: full output on the terminal")
    return parser


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def header(step, cmd=None, attempt=None, slug=None):
    parts = [f"=== {step}", _stamp()]
    if slug:
        parts.append(f"slug={slug}")
    if attempt is not None:
        parts.append(f"attempt={attempt}")
    line = " ".join(parts) + " ===\n"
    if cmd:
        line += "$ " + " ".join(str(c) for c in cmd) + "\n"
    return line


def append_text(log, text, step=None, attempt=None, slug=None):
    """Append `text` under a step header to the log (None -> nothing written)."""
    if log is None:
        return None
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as fh:
        if step:
            fh.write(header(step, attempt=attempt, slug=slug))
        fh.write(text if text.endswith("\n") or not text else text + "\n")
    return log


def ceiling(timeout=None, media_seconds=None):
    """The one deadline for a run_logged() call, in seconds.

    CF-0135: there is no `None` branch. An explicit `timeout=` wins - a
    caller that knows its own class of wait - and everything else is the
    ffmpeg-class ceiling `common.media_timeout()` derives from the material
    (300 s + 8 s per media second, the throttling of CF-0052 already inside
    the slope). A caller that cannot say how long its material is gets the
    base alone, which is what media_timeout(0) means everywhere else in the
    agent. The number is derived here rather than copied to the call site,
    so it cannot drift from its definition (CF-0131's lesson)."""
    if timeout is not None:
        return timeout
    return common.media_timeout(media_seconds or 0.0)


# CF-0905: the children a wrapper is running right now, so a stop of the
# wrapper takes them with it. example-tech/2026-10-31T0840Z: the operator
# stopped render_video.py with `pkill -f render_video.py`; SIGTERM's default
# action killed it on the spot (no `failed` line, the attempt left open),
# while build_soundtrack.py - a child reading nothing but its own work - went
# on as an orphan, wrote mix.wav and the plan's audio.bed under the render the
# operator had already restarted, and died on its last print into the pipe
# nobody read any more (BrokenPipeError). The same stop would have left
# Remotion with its node and Chrome rendering into the mp4. A child started
# with `own_session=True` is the leader of its own process group, and the
# stop kills that whole group (killpg SIGKILL, as content-researcher's
# plan_check_loop does since CF-0900); one without is killed alone.
STOP_SIGNALS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGHUP", "SIGINT")
                     if hasattr(signal, n))
_LIVE = {}  # pid -> (Popen, own_session)
_LIVE_LOCK = threading.RLock()  # re-entered by a stop landing inside spawn()


def spawn(cmd, own_session=False, **kwargs):
    """subprocess.Popen(cmd, **kwargs), recorded as a live child until
    forget() - what stop_children() kills on a stop. `own_session=True`
    starts it as the leader of its own session, so the stop (and the ceiling,
    kill_child()) reaches its grandchildren too."""
    proc = subprocess.Popen(cmd, start_new_session=bool(own_session), **kwargs)
    with _LIVE_LOCK:
        _LIVE[proc.pid] = (proc, bool(own_session))
    return proc


def forget(proc):
    with _LIVE_LOCK:
        _LIVE.pop(proc.pid, None)


def kill_child(proc, own_session):
    """Kill `proc` - and its whole process group when it leads its own
    session. A child already gone is not an error."""
    try:
        if own_session:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def stop_children(wait=2.0):
    """Kill every live child spawn() started and reap it. Returns the pids
    that were still running. The reap always has a timeout: Popen.wait()
    without one blocks on the waitpid lock a signal handler may have
    interrupted its own thread holding."""
    with _LIVE_LOCK:
        live = list(_LIVE.values())
    killed = []
    for proc, own in live:
        if proc.poll() is None:
            killed.append(proc.pid)
        kill_child(proc, own)
    for proc, _ in live:
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass
        forget(proc)
    return killed


@contextlib.contextmanager
def stop_on_signals(on_stop=None):
    """CF-0905: inside this block SIGTERM/SIGHUP/SIGINT stop the wrapper
    cleanly instead of killing it bare: every live child is killed with its
    group (stop_children()), `on_stop(signal_name, killed_pids)` closes what
    the wrapper had open (render_video.py: the attempt), and the wrapper
    exits 128+signal through SystemExit - so the runlog's script event ends
    `failed` with `SystemExit: 143` rather than `no end recorded`. A second
    signal during the stop is ignored. Off the main thread (no signals there)
    it is a no-op; the previous handlers are put back on exit."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    state = {"stopping": False}

    def _on_stop(signum, frame):
        if state["stopping"]:
            return
        state["stopping"] = True
        name = signal.Signals(signum).name
        killed = stop_children()
        if on_stop is not None:
            try:
                on_stop(name, killed)
            except Exception as e:  # the stop must still exit
                print(f"[quiet] stop on {name}: closing failed: {e}", file=sys.stderr)
        print(f"STOPPED by {name}: killed {len(killed)} child process group(s) "
              f"{killed} with it (CF-0905)", file=sys.stderr)
        raise SystemExit(128 + signum)

    saved = {}
    try:
        for sig in STOP_SIGNALS:
            saved[sig] = signal.signal(sig, _on_stop)
        yield
    finally:
        for sig, handler in saved.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, TypeError):
                pass


def run_logged(cmd, log, step, verbose=False, cwd=None, env=None, attempt=None,
               slug=None, timeout=None, media_seconds=None, tool=None, on_line=None,
               own_session=False):
    """Run `cmd`, its stdout+stderr merged, into `log` (appended under a
    header) and, when `verbose`, echoed to the terminal line by line. Returns
    (returncode, lines_written, tail) - `tail` is the last TAIL_LINES lines,
    for the summary of a failed step. `log` None: verbose only (no batch
    context - the pre-CF-0098 path).

    CF-0107: the whole call is one `child` event in RUN_EVENTS.jsonl -
    `tool` (default: the basename of cmd[0]; render_video.py passes
    `remotion`), argv, rc, and the enclosing script event as parent. A
    kill at the ceiling is rc 124 here and a `failed` child with rc "timeout"
    there.

    CF-0135: the ceiling is `ceiling(timeout, media_seconds)` - never absent -
    and it covers the whole call, the reading of the pipe included. Pass
    `media_seconds=` (how long the material is) in preference to `timeout=`.

    CF-0305: `on_line(line)` is called with every line read (not on the
    unlogged verbose path, which never reads the child) - render_video.py
    watches Remotion's frame progress and first error line with it.

    CF-0905: the child is a live child (spawn()) for the whole call, so a
    wrapper under stop_on_signals() takes it with it; `own_session=True`
    (render_video.py: Remotion, whose node and Chrome are grandchildren) puts
    it in its own process group, and both the stop and the ceiling kill the
    whole group."""
    tool = tool or Path(str(cmd[0])).name or "child"
    with runlog.child(tool, argv=[str(c) for c in cmd]) as event:
        rc, count, tail = _run_logged(cmd, log, step, verbose, cwd, env, attempt,
                                      slug, ceiling(timeout, media_seconds), event,
                                      on_line, own_session)
    return rc, count, tail


def _run_logged(cmd, log, step, verbose, cwd, env, attempt, slug, timeout, event,
                on_line=None, own_session=False):
    fh = None
    if log is not None:
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "a")
        fh.write(header(step, cmd, attempt=attempt, slug=slug))
        fh.flush()
    if fh is None and verbose:
        # Nothing to record: let the child own the terminal as it used to.
        proc = spawn(cmd, own_session=own_session, cwd=cwd, env=env)
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_child(proc, own_session)
            proc.wait()
            event["rc"] = "timeout"
            raise
        finally:
            forget(proc)
        event["rc"] = rc
        return rc, 0, []
    tail = []
    proc = spawn(cmd, own_session=own_session, cwd=cwd, env=env, stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    # CF-0135: the deadline has to cover the *reading*, not just the wait.
    # `for line in proc.stdout` blocks with no deadline of its own, so a child
    # wedged with its pipe open never reached proc.wait(timeout=...) at all -
    # which is how the longest stage of the pipeline stayed uncapped whatever
    # the caller passed. The read runs on its own thread; this one holds the
    # single deadline for the whole call and kills the child when it runs out.
    # The lines still land on disk as they arrive, which is why this is a
    # reader and not communicate(timeout=...) - CF-0131 put ~3k lines per real
    # video in that log, and a log written only at the end is no log for a
    # render that had to be killed.
    lock = threading.Lock()
    state = {"count": 0, "stopped": False}

    def pump():
        try:
            for line in proc.stdout:
                with lock:
                    if state["stopped"]:
                        return
                    state["count"] += 1
                    if fh is not None:
                        fh.write(line)
                    tail.append(line.rstrip("\n"))
                    if len(tail) > TAIL_LINES:
                        tail.pop(0)
                    if on_line is not None:
                        on_line(line.rstrip("\n"))
                if verbose:
                    sys.stdout.write(line)
                    sys.stdout.flush()
        except (ValueError, OSError):
            return  # the pipe went away under us (interpreter shutdown,
                    # or a caller that closed it); nothing left to read

    reader = threading.Thread(target=pump, name="quiet-reader", daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        reader.join(timeout=max(0.0, deadline - time.monotonic()))
        expired = reader.is_alive()
        if not expired:
            try:
                rc = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                expired = True
        if expired:
            kill_child(proc, own_session)
            proc.wait()
            # The reader can still be parked on a pipe a grandchild inherited -
            # the child is dead and the pipe is not closed. Give it a moment to
            # drain what is buffered, then abandon it: it is a daemon, and
            # `stopped` below turns its writes into no-ops. Closing the pipe
            # from here is not the way out - io's close() waits for the buffer
            # lock the blocked read is holding, so it hangs exactly as long as
            # the read does (measured: 20 s on the grandchild case in
            # tests/test_render_ceiling.py).
            reader.join(timeout=KILL_DRAIN_SECONDS)
            rc = 124
            event["rc"] = "timeout"
            tail.append(f"[quiet] killed after {timeout:g}s")
        else:
            event["rc"] = rc
    finally:
        forget(proc)
        with lock:
            state["stopped"] = True
            count = state["count"]
            if fh is not None:
                fh.write(f"=== end {step} rc={proc.returncode} lines={count} ===\n")
                fh.close()
    return rc, count, tail


def clip(text, width=LINE_WIDTH):
    text = " ".join(str(text).replace("\n", " ").split(" ")).rstrip()
    if text.startswith(NO_CLIP_PREFIXES):
        return text
    return text if len(text) <= width else text[:width - 3] + "..."


def summary(lines, log=None):
    """Cap a summary at MAX_SUMMARY_LINES, the last line always naming the
    log, and print it. Returns the printed lines."""
    lines = [clip(l) for l in lines]
    footer = [f"  log: {log}"] if log is not None else []
    room = MAX_SUMMARY_LINES - len(footer)
    if len(lines) > room:
        kept = lines[:room - 1]
        kept.append(f"  ... {len(lines) - len(kept)} more line(s) in the log")
        lines = kept
    lines += footer
    for l in lines:
        print(l)
    sys.stdout.flush()
    return lines


def attempt_label(attempt, ledger):
    """`attempt k/cap` - or, for a render that only applied QC's own hint
    (CF-0415), `qc degrade k/cap (render n)`: the number against the
    ceiling that render spends."""
    if attempt is None or ledger is None:
        return "attempt -"
    kind = attempts.kind_of(attempt)
    # CF-0305: a render the tool broke before the first frame is no attempt.
    same = [a for a in attempts.renders(ledger) if attempts.kind_of(a) == kind
            and (attempts.is_counted(a) or a.get("n") == attempt.get("n"))]
    k = next((i + 1 for i, a in enumerate(same) if a.get("n") == attempt.get("n")), len(same))
    if kind == attempts.KIND_QC_DEGRADE:
        return f"qc degrade {k}/{attempts.qc_degrade_cap(ledger)} (render {attempt['n']})"
    return f"attempt {k}/{ledger['attempt_cap']}"


class Context:
    """What a wrapper needs to know about the video it is working on: the
    batch, the slug, and - once one is begun - the attempt whose log it
    appends to. None of it exists for a plan outside <batch>/work/<slug>/."""

    def __init__(self, batch_dir, slug):
        self.batch_dir = Path(batch_dir)
        self.slug = slug
        self.attempt = None
        self.ledger = None

    @classmethod
    def for_plan(cls, plan_path):
        found = attempts.batch_context(plan_path)
        return cls(*found) if found else None

    def load(self, cap=None):
        self.ledger = attempts.load(self.batch_dir, self.slug, cap=cap)
        self.attempt = attempts.open_attempt(self.ledger)
        return self

    def latest(self):
        """The most recent attempt, open or not (qc re-run on a finished video)."""
        if self.ledger is None:
            self.load()
        return self.ledger["attempts"][-1] if self.ledger["attempts"] else None

    def begin(self, reason, cap=None, degraded=None, kind=attempts.KIND_ATTEMPT,
              build_inputs=None):
        self.attempt, self.ledger = attempts.begin(self.batch_dir, self.slug, reason,
                                                   cap=cap, degraded=degraded, kind=kind,
                                                   build_inputs=build_inputs)
        return self.attempt

    def end(self, result, detail=None, failed_gates=None, qc_hint=None, error=None,
            frames=None, qc_frozen=None):
        attempt, self.ledger, capped = attempts.end(
            self.batch_dir, self.slug, result, detail=detail, log=self.log,
            failed_gates=failed_gates, qc_hint=qc_hint, error=error, frames=frames,
            qc_frozen=qc_frozen)
        self.attempt = attempt
        return attempt, capped

    @property
    def log(self):
        if self.attempt is None:
            return None
        return Path(self.attempt["log"])

    def needs_you_line(self):
        return attempts.ledger_needs_you_line(self.slug, self.ledger or {})

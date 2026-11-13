#!/usr/bin/env python3
"""Long-lived macOS Vision worker (CF-0029). See vision_client.py for callers.

Accepts one JSON request per connection on a Unix socket and replies with one
JSON line. Vision's own warm-up (~0.7s cold, ~0.1-0.18s once a process has
already answered a request) is then paid at most once for the whole run of
callers talking to this process, instead of once per probed frame.

A bad frame is caught per-request and reported back as a normal failure
reply; it never brings the process down, so one corrupt image cannot cost a
resolve_anchors.py or index_footage.py run its warm state (that isolation is
the whole reason this is a separate process and not folded into the caller).

Exits on its own after IDLE_TIMEOUT seconds without a request, so a dev
machine does not accumulate orphaned daemons across pipeline runs.

CF-0058 - one worker, served strictly one connection at a time, is shared by
everything on the machine that asks macOS Vision anything. That is fine while
every wait it makes is bounded, and it was not: three waits here had no
ceiling at all, and any one of them parked the process for as long as
whatever it was waiting on cared to take, with every other consumer left
paying its own client-side timeout on every single call. So, in order:

  * `serve_one()` reads and writes under CONN_TIMEOUT. A client that connects
    and never finishes its request line used to wedge this loop *for as long
    as it held the socket open* - measured, it turned every other consumer's
    calls from 0.13s into a 30s client timeout apiece;
  * `handle()` runs under OP_TIMEOUT. Vision hanging on one frame is the same
    wedge with a different cause, and the reply this produces ("op timed out")
    is the ordinary per-request failure the docstring above already promises;
  * startup takes an flock instead of guessing from a connect probe whether
    someone else is already serving. Two consumers arriving cold at the same
    instant reproducibly (2 runs in 3) left *two* live workers both claiming
    this path, the loser of the bind race having unlinked the winner's socket
    and bound its own over it. The lock is released by the OS when a worker
    dies, so a crashed worker leaves nothing stale behind to reason about.

The socket path is overridable so tests can drive a private worker instead of
the machine-wide one, which is the only way to test any of the above without
disturbing whatever real run is warm at the time.
"""
import fcntl
import json
import os
import signal
import socket
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# CF-0107: the worker is a daemon serving many scripts and batches; nothing
# it computes is an event of its own - the calling script's `vision` request
# child is. Silence the accounting before smart_crop / detect_text_band bind it.
import _runlog  # noqa: E402
_runlog.runlog = _runlog._Silent()
import smart_crop  # noqa: E402
import detect_text_band  # noqa: E402

SOCK_PATH = os.environ.get("VISION_WORKER_SOCKET",
                           "/tmp/shorts-content-factory-vision-worker.sock")
# Held for the process's whole life, never unlinked: unlinking a lock file is
# how a lock stops being one.
LOCK_PATH = SOCK_PATH + ".lock"

IDLE_TIMEOUT = float(os.environ.get("VISION_WORKER_IDLE_TIMEOUT", 600))  # 10 min

# A request is one short JSON line and arrives in a single write; a reply is
# a few KB at most. Neither has any business taking seconds, so this ceiling
# is about detecting a client that stopped talking, not about being generous.
CONN_TIMEOUT = float(os.environ.get("VISION_WORKER_CONN_TIMEOUT", 15))

# The slowest legitimate request measured on this repo's frames (CF-0058):
# accurate-mode text recognition, 0.18-1.46s over 12 real full-resolution
# stills. 30s is twenty times the worst of those - it fires for a Vision call
# that has stopped making progress, not for a slow one.
OP_TIMEOUT = float(os.environ.get("VISION_WORKER_OP_TIMEOUT", 30))


class OpTimeout(Exception):
    """A single Vision request ran past OP_TIMEOUT."""


@contextmanager
def time_limit(seconds, message):
    """Bound a blocking call that offers no timeout of its own.

    SIGALRM rather than a watchdog thread: this process is single-threaded by
    design (that is what keeps Vision's warm state in one place), and the
    handler only has to raise - the exception then unwinds through the same
    per-request `except` that already turns a bad frame into a failure reply.
    """
    def fire(signum, frame):
        raise OpTimeout(message)

    previous = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def handle(req):
    op = req.get("op")
    if op == "find_roi":
        return smart_crop.analyse(req["image"], req.get("aspect", "9:16"))
    if op == "text_boxes":
        return detect_text_band.text_boxes(req["image"])
    if op == "text_regions":
        return detect_text_band.text_regions(req["image"], req.get("level", 0))
    if op == "ping":
        return {"pong": True}
    raise ValueError(f"unknown op: {op!r}")


def serve_one(conn):
    with conn:
        # Every wait on this connection is bounded from here on: the client
        # that opened it may be gone, wedged, or never have meant to say
        # anything (CF-0058), and none of those may cost the next consumer
        # in the queue its warm worker.
        conn.settimeout(CONN_TIMEOUT)
        try:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            print(f"vision worker: client sent no complete request in "
                  f"{CONN_TIMEOUT}s, dropping the connection", file=sys.stderr)
            return
        if not buf.strip():
            return
        try:
            req = json.loads(buf.decode("utf-8"))
            with time_limit(OP_TIMEOUT, f"op {req.get('op')!r} exceeded "
                                        f"{OP_TIMEOUT}s"):
                result = handle(req)
            reply = {"ok": True, "result": result}
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        except (socket.timeout, OSError) as e:
            print(f"vision worker: could not deliver a reply ({e})",
                  file=sys.stderr)


def claim_singleton():
    """Exclusive right to serve on SOCK_PATH, or None if someone else has it.

    An advisory lock rather than the old "connect and see if anybody answers"
    probe. The probe answered a *different* question - it asked whether a
    worker was reachable right now, which is not the same as whether one
    exists, and it got the answer wrong in exactly the case that matters: two
    workers starting at the same instant, neither yet listening. The kernel
    drops this lock when the holder dies, however it dies, so there is no
    stale-lock case to hand-roll.
    """
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd  # deliberately never closed: the lock lives as long as we do


def main():
    lock = claim_singleton()
    if lock is None:
        print("vision worker already running, exiting", file=sys.stderr)
        return

    # We hold the lock, so nothing else is serving this path and any socket
    # file sitting on it was left by a worker that is already gone.
    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK_PATH)
    st = os.stat(SOCK_PATH)
    ours = (st.st_dev, st.st_ino)

    server.listen(8)
    server.settimeout(IDLE_TIMEOUT)
    print(f"vision worker listening on {SOCK_PATH} (pid {os.getpid()})", file=sys.stderr)

    try:
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                print("vision worker idle timeout, exiting", file=sys.stderr)
                break
            try:
                serve_one(conn)
            except Exception:
                traceback.print_exc(file=sys.stderr)
    finally:
        server.close()
        # Only if the file on that path is still the socket we bound. An
        # exiting worker deleting a *successor's* socket is the same class of
        # bug as two workers racing to bind, and costs the successor every
        # client it has not been reached by yet.
        try:
            now = os.stat(SOCK_PATH)
            if (now.st_dev, now.st_ino) == ours:
                os.unlink(SOCK_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()

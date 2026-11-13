#!/usr/bin/env python3
"""CF-0058: two consumers of the warm Vision worker must not park a run.

The reported symptom was a hung test suite: `test_degrade_blocks.py` (which
shells out to `qc_asset.py`/`smart_crop.py` per block, and so asks Vision
dozens of times) stopped while `remeasure_usability.py` was probing the pool
in another terminal. Reproduced here, the mechanism is not "the second
consumer waits its turn" - the worker serves a request in ~0.13s and two
consumers interleave fine. It is that three waits in the pair had no ceiling,
and once any of them caught, every consumer paid a 30s client timeout *per
frame* and said nothing about why.

So what is pinned below is the ceilings, not the race. The race itself is
timing and there is no honest way to make a test fail reliably on it; a
mechanism that provably cannot wait forever is worth more than a test that
notices contention four times in five. Each check drives a *private* worker
on its own socket path, so running this never disturbs whatever warm worker
a real run is using, and every wait in this file is bounded - a test for a
hang that can hang the suite has learned nothing.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import vision_client  # noqa: E402
import vision_worker  # noqa: E402

WORKER = str(SCRIPTS / "vision_worker.py")


def worker_env(sock, conn_timeout=1.0, idle_timeout=20.0):
    return dict(os.environ,
                VISION_WORKER_SOCKET=str(sock),
                VISION_WORKER_CONN_TIMEOUT=str(conn_timeout),
                VISION_WORKER_IDLE_TIMEOUT=str(idle_timeout))


def start_worker(sock, **kw):
    proc = subprocess.Popen([sys.executable, WORKER], env=worker_env(sock, **kw),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if Path(sock).exists():
            return proc
        if proc.poll() is not None:
            raise AssertionError("worker exited before it began listening")
        time.sleep(0.05)
    proc.kill()
    raise AssertionError(f"worker never bound {sock}")


def ping(sock, timeout):
    """One ping, with every wait bounded. Returns the reply or raises."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock))
        s.sendall(b'{"op": "ping"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return buf
    finally:
        s.close()


def test_worker_drops_a_client_that_never_finishes_its_request():
    """The reproduced wedge, at its root.

    A connection that opens and then says nothing more used to sit in the
    worker's `recv` with no timeout, for as long as the client held the
    socket. Measured before the fix: with one such connection open, an
    ordinary consumer's calls went from 0.13s to a 30s client timeout each -
    three calls took 89s. The worker owes the *next* client in the queue a
    ceiling on how long a silent one can hold the floor.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "w.sock"
        proc = start_worker(sock, conn_timeout=1.0)
        stalled = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            stalled.connect(str(sock))
            stalled.sendall(b'{"op": "ping"')  # no newline: never completes
            time.sleep(0.3)                    # let the worker pick it up

            started = time.monotonic()
            reply = ping(sock, timeout=10)     # bounded: cannot hang the suite
            waited = time.monotonic() - started

            assert b'"pong"' in reply, (
                f"worker did not answer a healthy client while one silent "
                f"connection was open; got {reply!r}")
            assert waited < 8, (
                f"a healthy client waited {waited:.1f}s behind one silent "
                f"connection - the worker's per-connection ceiling "
                f"({vision_worker.CONN_TIMEOUT}s by default, 1s here) is not "
                f"being applied")
        finally:
            stalled.close()
            proc.kill()


def test_only_one_worker_ends_up_serving_the_socket():
    """Four workers started at the same instant leave exactly one.

    Before the fix the loser of the bind race asked "is anyone answering?",
    got no answer because the winner had not finished starting, unlinked the
    winner's socket and bound its own over it. Two consumers arriving cold
    together produced two live workers in 2 runs out of 3 - one of them
    orphaned on a socket nothing could reach, and still holding a Vision
    warm-up nobody would ever use.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "w.sock"
        procs = [subprocess.Popen([sys.executable, WORKER],
                                  env=worker_env(sock),
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
                 for _ in range(4)]
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if sum(p.poll() is None for p in procs) == 1:
                    break
                time.sleep(0.1)
            alive = [p.pid for p in procs if p.poll() is None]
            assert len(alive) == 1, (
                f"{len(alive)} workers are alive on one socket path ({alive}); "
                f"exactly one may serve it")
            assert b'"pong"' in ping(sock, timeout=10), (
                "the surviving worker does not answer on the socket path - "
                "someone unlinked it out from under him")
        finally:
            for p in procs:
                p.kill()


def test_client_stops_asking_a_worker_that_never_answers():
    """One timeout per process, not one per frame.

    The client cannot tell a wedged worker from a busy one, and does not need
    to: waiting REQUEST_TIMEOUT and *then* spending 0.7s computing the answer
    locally is strictly worse than spending the 0.7s straight away. So the
    first transport failure decides for the whole process. What is asserted
    is exactly that - the number of connections a dead worker gets - because
    that is the difference between a run that finishes and one that looks
    hung.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "silent.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock))
        server.listen(8)
        server.settimeout(0.5)
        accepted = []
        stop = threading.Event()

        def accept_and_say_nothing():
            while not stop.is_set():
                try:
                    accepted.append(server.accept()[0])  # held open, never answered
                except socket.timeout:
                    pass
                except OSError:
                    break

        thread = threading.Thread(target=accept_and_say_nothing, daemon=True)
        thread.start()

        saved = (vision_client.SOCK_PATH, vision_client.REQUEST_TIMEOUT,
                 vision_client._gave_up_on_worker, vision_client._local_vision)
        vision_client.SOCK_PATH = str(sock)
        vision_client.REQUEST_TIMEOUT = 1.0
        vision_client._gave_up_on_worker = None
        vision_client._local_vision = True  # this venv has pyobjc; say so plainly
        try:
            # A path with no image behind it: Vision's own answer is [] and
            # the local fallback is instant, so this measures the transport
            # decision and nothing else.
            missing = str(Path(tmp) / "no-such-frame.png")
            for _ in range(3):
                assert vision_client.text_regions(missing, level=1) == []
            assert vision_client._gave_up_on_worker is not None, (
                "client is still willing to ask a worker that never answered")
            assert len(accepted) == 1, (
                f"client opened {len(accepted)} connections to a worker that "
                f"never answers; it must give up after the first, or a run "
                f"pays REQUEST_TIMEOUT on every frame it probes")
        finally:
            vision_client.SOCK_PATH, vision_client.REQUEST_TIMEOUT, \
                vision_client._gave_up_on_worker, \
                vision_client._local_vision = saved
            stop.set()
            server.close()
            thread.join(timeout=5)


def test_an_interpreter_with_no_local_vision_is_never_quietly_switched_off():
    """The other half of the rule above, and the one that cost a real run.

    Footage Indexer's venv has no pyobjc: for it the worker is the only route
    to Vision, so "give up on the worker and compute locally" has no second
    half. Latching there once, on one 10s hiccup, is what turned a
    `remeasure_usability.py` pass over 140 shots into 13 measured and 127
    skipped - reported as "0 of their measurements moved", exit 0. So in that
    interpreter a transport failure must be a named per-frame error, and the
    next frame must still be allowed to ask.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "silent.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock))
        server.listen(8)
        server.settimeout(0.5)
        accepted = []
        stop = threading.Event()

        def accept_and_say_nothing():
            while not stop.is_set():
                try:
                    accepted.append(server.accept()[0])
                except socket.timeout:
                    pass
                except OSError:
                    break

        thread = threading.Thread(target=accept_and_say_nothing, daemon=True)
        thread.start()

        saved = (vision_client.SOCK_PATH, vision_client.REQUEST_TIMEOUT,
                 vision_client._gave_up_on_worker, vision_client._local_vision)
        vision_client.SOCK_PATH = str(sock)
        vision_client.REQUEST_TIMEOUT = 1.0
        vision_client._gave_up_on_worker = None
        vision_client._local_vision = False  # stand in for a venv without pyobjc
        try:
            for attempt in range(2):
                try:
                    vision_client.text_regions(str(Path(tmp) / "f.png"), level=1)
                    raise AssertionError(
                        "an unreachable worker produced an answer in an "
                        "interpreter that cannot compute one")
                except RuntimeError as e:
                    assert "no local Vision" in str(e), (
                        f"the failure does not say why it cannot be recovered "
                        f"from: {e}")
                assert vision_client._gave_up_on_worker is None, (
                    f"the client stopped asking the worker after attempt "
                    f"{attempt}, in an interpreter where not asking it means "
                    f"measuring nothing at all")
            assert len(accepted) == 2, (
                f"the worker was asked {len(accepted)} times for 2 frames - "
                f"every frame must get its own attempt here")
        finally:
            vision_client.SOCK_PATH, vision_client.REQUEST_TIMEOUT, \
                vision_client._gave_up_on_worker, \
                vision_client._local_vision = saved
            stop.set()
            server.close()
            thread.join(timeout=5)


def test_a_vision_call_that_does_not_return_is_cut_off():
    """The third unbounded wait: Vision itself, inside the worker.

    Tested at the mechanism rather than through a real frame - there is no
    image that reliably makes Vision hang, and a test that needed one would
    be testing macOS, not this repo. What matters is that the guard the
    request path runs under actually interrupts a call that does not return,
    and hands back an exception the per-request handler can turn into an
    ordinary failure reply.
    """
    started = time.monotonic()
    try:
        with vision_worker.time_limit(0.3, "test op"):
            time.sleep(10)
        raise AssertionError("time_limit let a 10s call run to completion")
    except vision_worker.OpTimeout:
        pass
    waited = time.monotonic() - started
    assert waited < 5, f"time_limit took {waited:.1f}s to interrupt a 0.3s budget"

    # And it must leave no alarm armed behind it, or the next request in this
    # single-threaded worker inherits someone else's deadline.
    with vision_worker.time_limit(5, "outer"):
        time.sleep(0.5)


def test_two_consumers_at_once_both_finish():
    """End to end, the shape of the reported failure: two processes asking
    the same worker at the same time, both of which must arrive somewhere
    observable. Bounded by `communicate(timeout=...)`, so a regression fails
    this file instead of parking the suite on it."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.png"
        # Not a flat colour: Vision should have something to actually scan.
        img = Image.new("RGB", (1280, 720))
        img.putdata([((x * 7) % 256, (x * 13) % 256, (x * 29) % 256)
                     for x in range(1280 * 720)])
        img.save(frame)

        sock = Path(tmp) / "w.sock"
        worker = start_worker(sock)
        consumer = ("import sys, vision_client as v; "
                    "v.SOCK_PATH = sys.argv[1]; "
                    "[v.text_regions(sys.argv[2], level=1) for _ in range(10)]; "
                    "print('done', v._gave_up_on_worker)")
        try:
            procs = [subprocess.Popen(
                [sys.executable, "-c", consumer, str(sock), str(frame)],
                env=worker_env(sock), cwd=str(SCRIPTS),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(2)]
            outs = []
            for p in procs:
                try:
                    outs.append(p.communicate(timeout=60))
                except subprocess.TimeoutExpired:
                    p.kill()
                    raise AssertionError(
                        "a consumer did not finish within 60s while another "
                        "was using the same worker - this is the CF-0058 hang")
            for i, (out, err) in enumerate(outs):
                assert procs[i].returncode == 0, (
                    f"consumer {i} exited {procs[i].returncode}\n{err}")
                assert "done None" in out, (
                    f"consumer {i} was pushed off the worker by ordinary "
                    f"contention - two consumers must simply queue:\n{out}{err}")
        finally:
            worker.kill()


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

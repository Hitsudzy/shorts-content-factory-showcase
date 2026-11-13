#!/usr/bin/env python3
"""Client for the warm Vision worker (CF-0029).

macOS Vision costs ~0.7s to answer the first request in a fresh process and
~0.1-0.18s in a process that has already answered one - the framework's own
warm-up, not anything in our code. Every Vision call in this pipeline used to
pay the cold price because each check (qc_asset.py's face/saliency probe,
detect_text_band.py's caption scan) ran as its own fresh subprocess. This
module talks to a single long-lived worker process instead (vision_worker.py)
over a Unix socket, so the warm-up is paid at most once per pipeline run
instead of once per probed frame.

Kept as a separate process rather than folded into the caller
(resolve_anchors.py, index_footage.py): a Vision crash on one bad frame
should cost that one request, not the whole run. If the worker cannot be
reached at all - not running, failed to start, socket gone - every call here
falls back to computing the answer locally in this process, which is exactly
today's slower-but-working behaviour. A worker outage costs speed, not
correctness.

CF-0058 changed *how often* that fallback is decided. The rule used to be
per call: ask the worker, wait REQUEST_TIMEOUT, fall back. With a worker that
answers, that is right. With one that does not - wedged, or busy behind
something that will never finish - it is a fresh bill on every frame, and a
run that probes a few dozen frames stops looking slow and starts looking
hung. It is also a bad trade on its face: waiting 30s to then spend 0.7s
doing the work yourself is strictly worse than spending the 0.7s at once. So
where the cold path exists the decision is now made once per process
(`_gave_up_on_worker`): the first transport failure says so on stderr and
every later call in that process computes its own answer. What was N x 30s
of silence is one wait, one line of explanation, and a run that finishes.

Where the cold path does *not* exist - Footage Indexer's venv, which has no
pyobjc and for which this worker is not an optimisation but the only route to
Vision at all - giving up is not "slower but correct", it is giving up on the
answer. Measured, before that distinction was drawn: one 10s hiccup at shot
13 of a `remeasure_usability.py` run disabled the worker for the remaining
127 shots, and the run then reported "0 of their measurements moved" and
exited 0. A clean-looking answer that measured nothing is worse than the hang
this task is about. So there the failure is per frame and named, the worker
is kept for the next frame, and what to do about it belongs to the caller,
which is the only place that knows whether a missing measurement matters.

Deliberately narrow in the other direction too: only a *transport* failure
counts. A worker that answers "that frame is broken" is working correctly and
stays in use.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import repo_paths  # CF-0125: the venv lives in the main checkout
from _runlog import runlog  # CF-0107: one `vision` child per request to the worker

HERE = Path(__file__).resolve().parent
WORKER_SCRIPT = HERE / "vision_worker.py"
# Resolved from this repo, not from the caller's own interpreter - footage
# Indexer's venv has no Quartz/Vision at all, and calls into this client too
# (CF-0029 step 3 asks the indexer to reuse the same warm worker). The worker
# itself always runs under Video Editor's venv, which has them - the main
# checkout's, since a worktree has no venv of its own (CF-0125).
WORKER_PYTHON = repo_paths.VENV_PY

# Overridable so a test can drive a private worker rather than the shared one
# every warm run on this machine is using (CF-0058). Read once, and passed
# down to any worker this client spawns through the inherited environment.
SOCK_PATH = os.environ.get("VISION_WORKER_SOCKET",
                           "/tmp/shorts-content-factory-vision-worker.sock")
LOG_PATH = "/tmp/shorts-content-factory-vision-worker.log"

CONNECT_TIMEOUT = 5.0
# What this ceiling is for changed with CF-0058, and so did the number. The
# old 30s was a guess at "surely longer than any real request" - on an idle
# machine the slowest real request measured here is 1.46s (accurate-mode text
# recognition on a full-resolution still; fast mode and ROI are 0.08-0.64s),
# but under a saturated one, with the test suite and a pool remeasure both
# running, a legitimate request was measured past 10s. Guessing at the tail
# of a latency distribution is the wrong way to set this.
#
# The worker now bounds itself instead: every connection it serves finishes
# within its own CONN_TIMEOUT + OP_TIMEOUT (15 + 30 = 45s) whatever happens
# inside it. So this is set *above* that guarantee. Timing out here no longer
# means "slow" - it means the process on the other end is not honouring its
# own contract (an old binary, a stopped process, a machine in swap), which
# is a different thing to react to and rare enough to be worth a full minute.
REQUEST_TIMEOUT = 60.0

# Set to the reason once this process stops asking the worker. None means
# "still using it". Per process on purpose: the worker is machine-wide state
# and one process giving up on it must not decide anything for the others.
_gave_up_on_worker = None

# Whether this interpreter can compute a Vision answer without the worker.
# None until something needs to know (importing pyobjc costs real time, and
# the happy path never asks).
_local_vision = None


class WorkerUnreachable(Exception):
    """The worker did not answer - as opposed to answering with a failure."""


def _try_connect(timeout):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(SOCK_PATH)
    return sock


def _spawn_worker():
    log = open(LOG_PATH, "a")
    # CF-0107: the worker outlives this script and serves every later one, so
    # it must not inherit this run's batch or parent event - the client's
    # request child (below) is what accounts for its time.
    env = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    subprocess.Popen(
        [WORKER_PYTHON, str(WORKER_SCRIPT)],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=env,
        start_new_session=True,  # detach: outlives whichever script started it
    )


def _connect():
    try:
        return _try_connect(1.0)
    except OSError:
        pass
    _spawn_worker()
    deadline = time.monotonic() + CONNECT_TIMEOUT
    while time.monotonic() < deadline:
        try:
            return _try_connect(1.0)
        except OSError:
            time.sleep(0.15)
    raise WorkerUnreachable(f"no worker on {SOCK_PATH} after "
                            f"{CONNECT_TIMEOUT}s and a spawn attempt")


def _request(op, **payload):
    """CF-0107: one `vision` child event per request answered by the warm
    worker (probe = the op, via worker); the local fallback's own Vision
    call is accounted for inside smart_crop.py / detect_text_band.py."""
    with runlog.child("vision", argv=["vision", op, str(payload.get("image", ""))],
                      params={"probe": op, "via": "worker"}):
        return _request_raw(op, **payload)


def _request_raw(op, **payload):
    sock = _connect()
    try:
        sock.settimeout(REQUEST_TIMEOUT)
        sock.sendall((json.dumps({"op": op, **payload}) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        raise WorkerUnreachable(
            f"worker accepted the connection but did not answer {op!r} within "
            f"{REQUEST_TIMEOUT}s - it is serving someone else, or wedged")
    except OSError as e:
        raise WorkerUnreachable(f"socket error talking to the worker: {e}")
    finally:
        sock.close()
    if not buf.strip():
        raise WorkerUnreachable("worker closed the connection with no response")
    reply = json.loads(buf.decode("utf-8"))
    if not reply.get("ok"):
        # The worker answered. It is healthy; this frame is not.
        raise RuntimeError(reply.get("error", "vision worker request failed"))
    return reply["result"]


def _can_compute_locally():
    """Does this interpreter have Vision of its own to fall back on?

    The whole shape of a worker outage turns on this. Video Editor's venv has
    pyobjc, so an outage costs it speed. Footage Indexer's venv does not, so
    an outage costs it the answer - and the two cannot be handled the same
    way without one of them ending up wrong.
    """
    global _local_vision
    if _local_vision is None:
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
            _local_vision = True
        except ImportError:
            _local_vision = False
    return _local_vision


def _give_up(reason, image):
    global _gave_up_on_worker
    _gave_up_on_worker = reason
    print(f"vision worker unreachable ({reason}) while probing {image}. "
          f"This process will not ask it again and will make its own Vision "
          f"calls from here on - correct, and about 0.7s per call instead of "
          f"0.15s.", file=sys.stderr)


def _locally(compute, image):
    """Run the fallback, and fail loudly if this interpreter cannot.

    Footage Indexer's venv has no pyobjc: for it the worker is not an
    optimisation but the only way to reach Vision at all, and the honest
    outcome there is a named error rather than the raw ModuleNotFoundError
    that used to surface from inside an `except` handler that was busy
    explaining something else (CF-0058).
    """
    try:
        return compute()
    except ModuleNotFoundError as e:
        raise RuntimeError(
            f"the Vision worker could not be reached and {sys.executable} has "
            f"no local Vision to fall back on ({e}). Start the worker under "
            f"Video Editor's venv ({WORKER_PYTHON} {WORKER_SCRIPT}), or run "
            f"this under an interpreter that has pyobjc.") from e


def _ask(op, payload, image, compute_locally):
    """One Vision answer: from the worker if it is answering, else locally."""
    if _gave_up_on_worker is None:
        try:
            return _request(op, **payload)
        except WorkerUnreachable as e:
            if not _can_compute_locally():
                # No cold path here. Latching would silently convert every
                # remaining frame of this run into "no answer" while the run
                # went on reporting success (CF-0058, measured on a real
                # remeasure). One frame fails, loudly; the worker gets asked
                # again for the next one.
                raise RuntimeError(
                    f"could not measure {image}: {e}, and {sys.executable} "
                    f"has no local Vision to fall back on. The worker runs "
                    f"under Video Editor's venv "
                    f"({WORKER_PYTHON} {WORKER_SCRIPT}).") from e
            _give_up(str(e), image)
        except Exception as e:
            # The worker answered and said no. That is this frame's problem,
            # not the worker's - compute it here and keep using the worker.
            print(f"vision worker failed on {image} ({e}) - computing it "
                  f"locally instead", file=sys.stderr)
    return _locally(compute_locally, image)


def find_roi(image, aspect="9:16"):
    """Face/saliency ROI + crop suggestion for `image`. Same shape as
    smart_crop.py's own --json output."""
    def locally():
        import smart_crop
        return smart_crop.analyse(str(image), aspect)

    return _ask("find_roi", {"image": str(image), "aspect": aspect},
                image, locally)


def text_boxes(image_path):
    """[[top, bottom], ...] fractional text bounding boxes in `image_path`."""
    def locally():
        import detect_text_band
        return detect_text_band.text_boxes(image_path)

    return _ask("text_boxes", {"image": str(image_path)}, image_path, locally)


def text_regions(image_path, level=0):
    """[{top, bottom, left, width, height}, ...] fractional text boxes in
    `image_path`, at the given Vision recognition level (0=accurate,
    1=fast). CF-0010: title/end-card detection needs accurate mode's real
    transcription pass and each box's full extent (width, not just its
    vertical band) to judge how much of the frame large text covers."""
    def locally():
        import detect_text_band
        return detect_text_band.text_regions(image_path, level=level)

    return _ask("text_regions", {"image": str(image_path), "level": level},
                image_path, locally)

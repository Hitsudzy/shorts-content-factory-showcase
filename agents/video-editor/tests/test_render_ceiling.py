#!/usr/bin/env python3
"""CF-0135: the render's ceiling covers the reading, not just the wait.

`quiet.run_logged()` runs Remotion - the longest stage of the pipeline, on
every video of every batch, with retries (CF-0098) - through subprocess.Popen
and streams its output to the attempt log line by line. The ceiling used to
sit on `proc.wait(timeout=...)`, which a hung child never reaches: execution
is parked in `for line in proc.stdout`, and that loop has no deadline. So the
stage was uncapped whatever the caller passed - and render_video.py passed
nothing at all.

The two shapes of that hang are both here, and both are faked, in seconds:

  1. the child is alive and silent with its pipe open (a wedged Remotion);
  2. the child has exited, but a grandchild inherited the pipe and holds it
     open - `proc.wait()` would return at once, and the read still never ends
     (Remotion spawns Chrome, so this is the realistic one).

Neither runs a real render. What is asserted is that the call comes back at
its deadline with rc 124, and that the lines the child did print are on disk
by then - a log written only at the end is no log for a render that had to
be killed (CF-0131: ~3k lines on a real video).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import ast
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import common  # noqa: E402
import quiet  # noqa: E402
import render_video  # noqa: E402

CEILING = 1.0            # what the faked children are given
SLACK = 5.0               # a kill that lands this late is a hang, not a ceiling

# 1. alive, silent, pipe open.
WEDGED = ("import sys, time\n"
          "print('bundling', flush=True)\n"
          "print('rendering frame 1', flush=True)\n"
          "time.sleep(600)\n")

# 2. exited, grandchild holding the pipe. The grandchild's own sleep is short
# so nothing is left running behind the suite for longer than a few seconds.
ORPHANED_PIPE = ("import subprocess, sys\n"
                 "print('bundling', flush=True)\n"
                 "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
                 "sys.exit(0)\n")


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"ok: {msg}")


def _run(source, log, **kw):
    """run_logged on a faked child, timed."""
    started = time.monotonic()
    rc, lines, tail = quiet.run_logged([sys.executable, "-c", source], log,
                                       "faked render", verbose=False,
                                       timeout=CEILING, tool="faked", **kw)
    return rc, lines, tail, time.monotonic() - started


# --------------------------------------------------------------------------
# the ceiling is reached, by both shapes of hang
# --------------------------------------------------------------------------

def test_a_child_wedged_with_its_pipe_open_is_killed_at_the_ceiling():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "logs" / "slug-attempt-1.log"
        rc, lines, tail, elapsed = _run(WEDGED, log)
    _check(rc == 124, f"a wedged child comes back as rc 124, not a value (got {rc})")
    _check(elapsed < CEILING + SLACK,
           f"and it comes back at the ceiling: {elapsed:.1f} s for a {CEILING:g} s "
           "ceiling on a child that would have slept 600")
    _check(any("killed after" in t for t in tail),
           "the tail says the child was killed rather than that it failed")


def test_a_grandchild_holding_the_pipe_does_not_outlive_the_ceiling():
    """The shape the old code could not survive at all: `proc.wait()` would
    have returned instantly, so even a ceiling on the wait was no ceiling -
    the read is what never ended."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "logs" / "slug-attempt-1.log"
        rc, lines, tail, elapsed = _run(ORPHANED_PIPE, log)
    _check(rc == 124, f"an inherited open pipe still ends at the ceiling (rc {rc})")
    _check(elapsed < CEILING + SLACK,
           f"and it ends there in {elapsed:.1f} s, not when the grandchild feels like it")


def test_the_output_the_child_did_print_is_on_disk_when_it_is_killed():
    """Why this is a reader thread and not communicate(timeout=...): the log
    is the record of a render, and the render that most needs one is the
    render that was killed."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "logs" / "slug-attempt-1.log"
        rc, lines, tail, _ = _run(WEDGED, log)
        text = log.read_text()
    _check(rc == 124, "the killed child is still rc 124")
    _check("bundling" in text and "rendering frame 1" in text,
           "both lines the child printed before it wedged are in the log")
    _check(lines == 2, f"and they are counted ({lines})")
    _check("=== end faked render" in text, "the step is closed off in the log")


def test_a_child_that_finishes_is_untouched_by_any_of_this():
    """The ceiling is not allowed to cost the ordinary path anything: every
    line, in order, and the real return code."""
    source = ("import sys\n"
              "for i in range(200):\n"
              "    print(f'line {i}', flush=True)\n"
              "sys.exit(3)\n")
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "logs" / "slug-attempt-1.log"
        rc, lines, tail, elapsed = _run(source, log)
        text = log.read_text()
    _check(rc == 3, f"the child's own exit code survives (got {rc})")
    _check(lines == 200, f"every line was read ({lines})")
    _check("line 0" in text and "line 199" in text, "and every line reached the log")
    _check(tail[-1] == "line 199", "the tail is still the end of the output")
    _check(elapsed < CEILING + SLACK, "and it did not wait for the ceiling to finish")


def test_a_child_with_no_log_still_runs_under_the_ceiling():
    """`log=None, verbose=True` is the pre-CF-0098 path - it goes through
    subprocess.run(), which must carry the same number rather than none."""
    started = time.monotonic()
    try:
        quiet.run_logged([sys.executable, "-c", "import time; time.sleep(600)"],
                         None, "faked render", verbose=True, timeout=CEILING)
        raise AssertionError("the no-log path ran a 600 s child to completion")
    except subprocess.TimeoutExpired:
        pass
    _check(time.monotonic() - started < CEILING + SLACK,
           "the no-log path reaches its ceiling too")


# --------------------------------------------------------------------------
# and the number is derived, never absent and never copied
# --------------------------------------------------------------------------

def test_there_is_no_call_without_a_ceiling():
    """CF-0128's form: a ceiling is not an optional argument. `timeout=None`
    used to mean "wait forever", which is how render_video.py went uncapped
    by passing nothing."""
    _check(quiet.ceiling() == common.media_timeout(0),
           "a caller that says nothing gets the base ceiling, not None")
    _check(quiet.ceiling() > 0, "and it is a positive number of seconds")
    _check(quiet.ceiling(media_seconds=60) == common.media_timeout(60),
           "a caller that says how long its material is gets media_timeout()'s number")
    _check(quiet.ceiling(media_seconds=60) > quiet.ceiling(media_seconds=10),
           "longer material, longer ceiling")
    _check(quiet.ceiling(timeout=17) == 17,
           "an explicit timeout= still wins for a caller that knows its own class of wait")


def test_the_render_asks_for_the_length_of_what_is_being_drawn():
    """CF-0117 put the end card after the last word, so the composition is
    longer than the voice-over; the render's ceiling is about the composition."""
    _check(render_video.composition_seconds(
        {"duration": {"composition": 58.2, "actual": 41.0}}) == 58.2,
        "the composition's length, not the narration's")
    _check(render_video.composition_seconds({"duration": {"actual": 41.0}}) == 41.0,
           "a plan written before CF-0117 falls back to the narration")
    for plan in ({}, {"duration": {}}, {"duration": {"composition": None}},
                 {"duration": {"composition": "soon"}}, {"duration": {"composition": 0}}):
        _check(render_video.composition_seconds(plan) == 0.0,
               f"{plan} answers 0.0 - 'cannot say' - rather than crashing the render")


def test_the_render_call_hands_that_length_over():
    """The call site itself, so a later edit cannot drop the argument and
    quietly put the longest stage back on the base ceiling."""
    tree = ast.parse((HERE.parent / "scripts" / "render_video.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "run_logged"]
    _check(len(calls) == 1, f"render_video.py makes one run_logged call ({len(calls)})")
    names = [kw.arg for kw in calls[0].keywords]
    _check("media_seconds" in names or "timeout" in names,
           f"render_video.py:{calls[0].lineno} tells run_logged how long its material is")


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

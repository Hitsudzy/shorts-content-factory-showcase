"""CF-0915 / CF-0916: a reader that closes the pipe early is not a crash.

ExampleTech `2026-11-04T0835Z`: the stage ran its gates in a shell loop of its
own, `python3 $S/$g 2>&1 | head -0` - BSD `head` refuses `-0` ("illegal line
count") and exits at once, so the checker's first line (argparse's usage, on
stderr merged into the pipe) met a pipe nobody read. Python raised
`BrokenPipeError` out of `print`, the run event said `failed` with that error,
and the run's triage (`shared/runlog/triage.py`: `SystemExit: N` is a refusal,
anything else a crash) filed `check_production_fact.py` and
`check_hook_opener.py` as two аварии of our code.

The cure is the conventional one, done so that the verdict survives: a write
or a flush that meets a closed pipe points the stream's file descriptor at
/dev/null (`os.dup2`, as the Python docs advise for SIGPIPE) and the script
goes on. Nothing is re-run and nothing is skipped: the check runs to its end,
writes what it writes (`--write` into the batch file), and exits with its own
code - a failing gate stays failing (1, 2, 4 ...), a passing one 0. Only the
text the closed pipe would have dropped anyway is lost. A real exception is
not touched: it propagates as before, and runlog records it as before.

    from _pipe_safe import guard      # or: @_pipe_safe.cli above the entry
    guard()                           # sys.stdout / sys.stderr now pipe-safe

Every script under `@runlog.script` gets this from `_runlog.py` (its
`script()` installs the guard before the entry runs); a CLI without runlog
calls `guard()` in its `__main__` block.
"""
import functools
import os
import sys

__all__ = ["guard", "cli", "PipeGuard"]


class PipeGuard:
    """A text stream's surface over `stream`; `write`/`writelines`/`flush`
    that meet a closed pipe (BrokenPipeError) send the stream to /dev/null
    instead of raising. Every other attribute is the wrapped stream's."""

    def __init__(self, stream):
        self._stream = stream
        self.broken = False

    @property
    def wrapped(self):
        return self._stream

    def _sink(self):
        """The reader is gone: from now on this stream writes into /dev/null.
        The descriptor itself is redirected, so the underlying object's own
        buffer (flushed again at interpreter exit) drains without a second
        error; a stream without a usable descriptor is swapped for an open
        /dev/null."""
        self.broken = True
        try:
            fd = self._stream.fileno()
            devnull = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull, fd)
            finally:
                os.close(devnull)
        except (AttributeError, OSError, ValueError):
            self._stream = open(os.devnull, "w")
        try:
            self._stream.flush()        # what was pending goes to /dev/null now
        except (OSError, ValueError):
            pass

    def write(self, s):
        try:
            return self._stream.write(s)
        except BrokenPipeError:
            self._sink()
            return len(s)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        try:
            self._stream.flush()
        except BrokenPipeError:
            self._sink()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def guard():
    """Put sys.stdout and sys.stderr under a PipeGuard (idempotent)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and not isinstance(stream, PipeGuard):
            setattr(sys, name, PipeGuard(stream))


def cli(fn):
    """Decorator for a command-line entry: guard() first, then the entry."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        guard()
        return fn(*args, **kwargs)
    return wrapper

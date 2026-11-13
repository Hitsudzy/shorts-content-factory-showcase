"""CC-0156: the commit of a write the center started detached - it happens
when the work ends well, in the detached process itself, the way a confirmed
write of the API commits (`api/root_commit.py`: git's word on the write's own
paths before the work and after, one commit of the files whose bytes moved,
`Cc-Channel` / `Cc-Action`). One detached write:

    a channel's ending render (`api/ending.py`): the argv handed to
    `child.detach` is this module before `brand_ending.py <c> ...`; it runs
    the script in this process (`runpy`, as `python3 brand_ending.py` would),
    then, when it ended with 0, commits the clip (`channels/<c>/ending.mp4`).
    The exit code is the script's.

CC-0158: the meme desk's background jobs are not here any more - their commit
is the factory's own (CF-0847, a switch of `start_job`); the center does not
swap the desk's `JOB_ARGV`, a seam of the factory's tests.

A render that did not end well commits nothing. A commit git refuses leaves
the clip in the tree, nothing staged (the API's 409 `refused` has no request
to answer here): it is said in the log - one line `cc-commit: refused ...`.
Every line of this module in a log starts with `cc-commit:` (the ending's
`_running` reads the render's own last line past them). A root that is not a
git work tree commits nothing.

Run as `python3 -c BOOTSTRAP <kind> ...` (`argv_head`): CODE first on the
path, not the cwd - the API's code is this checkout's, whatever the root is.
"""
import runpy
import sys
from pathlib import Path

from . import memes, root_commit
from .batches import BatchFault
from .settings import CODE

PREFIX = "cc-commit:"
ENDING = "ending_render"
WRITE_BY, VIA = memes.WRITE_BY, memes.VIA

#: The detached process's program: this checkout's `api` first, then `main`.
BOOTSTRAP = ("import sys; sys.path[:] = [p for p in sys.path if p not in ('', '.')]; "
             "sys.path.insert(0, sys.argv[1]); del sys.argv[1]; "
             "from api import detached_commit; "
             "raise SystemExit(detached_commit.main(sys.argv[1:]))")


def argv_head(kind, *args):
    """The argv before the work's own: `[python, -c, BOOTSTRAP, CODE, kind,
    *args]`."""
    return [sys.executable, "-c", BOOTSTRAP, str(CODE), kind, *[str(a) for a in args]]


def _say(line):
    print(f"{PREFIX} {line}", flush=True)


def _commit(root, cid, action, scope, before, subject, body, done):
    """(sha, committed, error): the commit of what moved; git's refusal said,
    not raised."""
    try:
        sha, committed = root_commit.commit_changed(root, cid, action, scope, before,
                                                    lambda: (subject, body), done)
    except BatchFault as e:
        _say(f"refused - {e.message} " + " | ".join(e.details))
        return None, [], " | ".join(e.details)
    if sha:
        _say(f"committed {sha[:12]}: {', '.join(committed)}")
    else:
        _say("nothing to commit")
    return sha, committed, None


def ending(root, cid, out, script, args):
    """The render: `script` with `args` in this process, then the clip's commit
    when it ended with 0. The script's exit code."""
    root = Path(root)
    scope = root_commit.rels(root, [out])
    before = root_commit.snap(root, scope)
    sys.argv = [str(script), *args]
    sys.path.insert(0, str(Path(script).resolve().parent))
    rc = 0
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        if e.code is None or e.code == 0:
            rc = 0
        elif isinstance(e.code, int):
            rc = e.code
        else:
            print(e.code, file=sys.stderr, flush=True)
            rc = 1
    sys.stdout.flush()
    sys.stderr.flush()
    if rc != 0 or before is None:
        return rc
    _commit(root, cid, ENDING, scope, before,
            f"Концовка {cid}: отрендерена ({WRITE_BY}, {VIA})",
            f"CC-0156: рендер концовки из центра (ending.render, {Path(script).name}).\n"
            f"Аргументы: {' '.join(args)}", "Концовка отрендерена")
    return rc


def main(argv):
    """`ending_render <root> <cid> <out> <script> [args...]`."""
    kind, rest = argv[0], argv[1:]
    if kind == ENDING:
        return ending(rest[0], rest[1], rest[2], rest[3], rest[4:])
    print(f"{PREFIX} unknown kind {kind!r}", file=sys.stderr)
    return 2

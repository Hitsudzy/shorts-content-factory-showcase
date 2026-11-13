"""CF-0853 / CF-0854: the batch file a step-6 checker reads, checked where
argparse reads it.

    ap.add_argument("batch_file", type=_batch_arg.batch_file, help=_batch_arg.HELP)

A checker used to take the positional as a bare string and open it later
with `Path.read_text()`. When the argument was not the batch file at all -
ExampleTech `2026-10-23T1504Z`, the operator's shell loop handed
`check_production_fact.py` and `check_hook_opener.py` their own script names
(`python3 $S/$g ${g%% *}`) - the checker died on `FileNotFoundError`: a
traceback, which the run's triage (`shared/runlog/triage.py`) files as a
crash of our code. A wrong argument is a usage error, so it is refused as
one: argparse prints the usage and the reason and exits 2 (`SystemExit: 2`,
a refusal for the triage). No topic and no video is touched - this is not a
gate, it is the shape of the command line.

The value is returned unchanged (a string), so nothing downstream of
`parse_args` changes.

CF-0869: the batch may be named by its folder as well as by its file - the
same two forms `already_published.py` takes ("pipeline/<channel>/<batch> or
its 03-content-researcher.json"). A folder that holds the batch file is
answered with that file's path; a folder without one is still a usage
refusal. And a sibling of the batch file (`--trend` 01-trend-hunter.json) is
read through `beside()`: example-film `2026-10-26T1514Z`, the operator wrote
`--trend <03-content-researcher.json>/../01-trend-hunter.json`, which the
filesystem does not resolve (a file has no `..`), and `check_proofs.py`
died on `NotADirectoryError` - a crash for the triage. `beside()` takes the
file itself, that same path spelled through the batch file (resolved by
text), or the batch folder / batch file (the sibling named inside it); any
other value is argparse's exit 2, never a traceback.
"""
import argparse
import os
from pathlib import Path

RESEARCHER_FILE = "03-content-researcher.json"
TREND_FILE = "01-trend-hunter.json"
HELP = "pipeline/<channel>/<batch>/03-content-researcher.json (or the batch folder)"
EXPECTED = "the batch's 03-content-researcher.json"


def batch_file(value):
    """argparse `type=`: `value` if it names an existing file, the batch
    file inside it if it names a batch folder (CF-0869), otherwise an
    ArgumentTypeError that says what was wrong and what to pass."""
    p = Path(value)
    if p.is_file():
        return value
    if p.is_dir() and (p / RESEARCHER_FILE).is_file():
        return str(p / RESEARCHER_FILE)
    if p.suffix == ".py":
        raise argparse.ArgumentTypeError(
            f"{value!r} is a script name, not the batch file - the first argument is "
            f"{EXPECTED} ({HELP}); run the command exactly as SKILL.md prints it")
    if p.is_dir():
        raise argparse.ArgumentTypeError(
            f"{value!r} is a directory with no {RESEARCHER_FILE} in it - pass "
            f"{EXPECTED} ({HELP})")
    raise argparse.ArgumentTypeError(
        f"no such file {value!r} (from {Path.cwd()}) - pass {EXPECTED} ({HELP})")


def beside(name):
    """argparse `type=` for a file of the batch folder other than the batch
    file itself (CF-0869), e.g. `type=_batch_arg.beside(TREND_FILE)`. The
    returned converter accepts, in this order:

      - an existing file - returned unchanged;
      - a path that names an existing file once `..` is resolved by text
        (`<batch>/03-content-researcher.json/../01-trend-hunter.json`) -
        the resolved path;
      - the batch folder, or a file in it (the batch file), when `name`
        exists in that folder - the path of `name` there.

    Anything else is an ArgumentTypeError (argparse's exit 2) naming `name`."""
    def convert(value):
        p = Path(value)
        if p.is_file() and p.name != RESEARCHER_FILE:
            return value
        norm = Path(os.path.normpath(value))
        if norm.is_file() and norm.name != RESEARCHER_FILE:
            return str(norm)
        folder = p if p.is_dir() else (p.parent if p.is_file() else None)
        if folder is not None and (folder / name).is_file():
            return str(folder / name)
        raise argparse.ArgumentTypeError(
            f"no {name} at {value!r} (from {Path.cwd()}) - pass the batch's {name} "
            f"(pipeline/<channel>/<batch>/{name}), or leave the option out to read "
            f"the one beside the batch file")
    convert.__name__ = name  # argparse names the type in its message
    return convert


def default_beside(batch_file, name):
    """`name` in the batch file's folder when it is there, else None - the
    default of an option read through `beside()`."""
    f = Path(batch_file).parent / name
    return str(f) if f.is_file() else None

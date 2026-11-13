"""CF-0777: the first thing every command line of this agent does with its
arguments - answer `-h`/`--help` and refuse an option it does not know.

The scripts read their arguments by position (`<file> [channel]`) and pick a
flag or two out by name. That left two holes a stage operator falls into the
moment they ask a script how it is called: `check_contribution.py --help`
took `--help` for the file to judge and died with a FileNotFoundError
traceback (`example-tech/2026-10-16T0839Z`, 2026-10-16T17:10:59Z), and the
other scripts answered `--help` with their usage but exit 2 - a usage error
for a question. `screen()` closes both without touching the call forms the
skill and the runner use: positional arguments pass through untouched, the
known flags pass through, and only what starts with `-` and is not one of
them is looked at.

    rc = screen(argv, USAGE, flags=("--dry-run",))
    if rc is not None:
        return rc

- `-h` / `--help` anywhere among the arguments: the usage on stdout, exit 0,
  nothing read or written.
- any other `-x` / `--xyz` the script does not name: the usage and
  "unrecognized option" on stderr, exit 2 - argparse's code for a usage
  error - instead of a traceback or a file named `--xyz`.

`valued` names the options that take the next argument as their value
(`--note N`, `--root R`): that value is skipped, so a note that happens to
begin with `-` is not mistaken for an option. A lone `-` is an argument, not
an option.
"""
import sys

HELP = ("-h", "--help")
USAGE_ERROR = 2


def screen(argv, usage, *, flags=(), valued=(), prog=None):
    """None when the arguments may go on to the script; otherwise the exit
    code, with the answer already printed (0 for help, 2 for an option the
    script does not know)."""
    prog = prog or _prog(usage)
    unknown = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in valued:
            i += 2
            continue
        if arg in HELP:
            print(usage)
            return 0
        if unknown is None and arg.startswith("-") and arg != "-" and arg not in flags:
            unknown = arg
        i += 1
    if unknown is not None:
        print(usage, file=sys.stderr)
        print(f"{prog}: error: unrecognized option {unknown!r} "
              f"(`{prog} --help` prints the usage)", file=sys.stderr)
        return USAGE_ERROR
    return None


def _prog(usage):
    """The script's name, as the usage line gives it."""
    first = usage.split("\n", 1)[0].split()
    if len(first) > 1 and first[0].rstrip(":") == "usage":
        return first[1]
    return "script"

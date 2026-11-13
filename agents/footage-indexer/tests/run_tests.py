#!/usr/bin/env python3
"""Run every test_*.py in this directory. No pytest dependency, no CI - just
a script to run by hand before closing a version (CF-0024, same harness the
Video Editor repo uses).

CF-0612 (docs/test-hygiene.md at the factory root): a test does not go to the
network and does not read live data. Every file of the plain run starts with
the network off past loopback - the root's `shared/no_network` first on its
PYTHONPATH, every proxy variable pointed at a trap of this runner's own - and
whatever it reached for makes it FAILED, whatever it printed. A test that has
to talk to the world is marked live (`LIVE_TEST = "why"` for a whole file,
`LIVE_ENV = "SWITCH"` for a live part, `tests/_live_monitors.py` for the
live-tree monitors) and runs only with `--live`; `--list` prints the plan.
The shared half is `shared/test_hygiene.py` of the factory checkout, loaded by
path through `_fi_paths.factory_root()` (one copy of the rule, CF-0159).

CF-0054: this runner is the instrument the whole dev process leans on, so it
is built to fail loudly rather than quietly. A test file counts as passing
only if it exits 0 *and* prints a `N/N passed` summary line with no failures
in it. A file that dies on import, crashes, or prints no result at all is a
FAIL - "zero tests" is not "success" - and the runner itself exits non-zero.
It also pins the interpreter to the repo's own .venv when there is one, so
that the answer does not depend on which python you happened to type.

CF-0077: a hung file is worse than a failed one - it looks like "still
computing" and eats the whole window. Every file runs under a per-file
ceiling; on expiry the file's whole process group is killed (so a hung
grandchild - Vision worker, ffmpeg - dies with it) and the file is reported
FAILED, naming the file and the ceiling, on the same path as an import death.

CF-0679 (as at the root): `run_tests.py test_x.py [...]` runs only the named
files (as `tests/test_x.py`, `test_x.py` or `test_x`) under the same isolation
as the whole suite - venv, own TMPDIR and leak check, network trap, ceiling,
TOTAL line. `--help` prints the usage and runs nothing; an unknown flag or a
file that is not there is exit 2, never a quiet full run (on 2026-10-10 a
`run_tests.py <file>` started a whole suite three times).
"""
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# CF-0267: `.venv/` is gitignored, so a worktree has none of its own; the
# agent's venv is then found from the factory root (scripts/_runlog.py).
sys.path.insert(0, str(REPO / "scripts"))
import _fi_paths  # noqa: E402  finds the factory checkout (CF-0612)
from _fi_paths import venv_bin  # noqa: E402
VENV_PY = venv_bin("python3")
REEXEC_FLAG = "RUN_TESTS_UNDER_VENV"

# The one line every test file owes this runner. Anything else it prints is
# free-form and ignored; this is the only machine-readable part of the
# contract, so an outside counter can sum the same numbers the runner does.
SUMMARY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s+passed\b")

# CF-0077: ceiling on one test file, in seconds. Well above the slowest
# honest file we have measured (test_degrade_blocks.py in video-editor, ~188 s
# of real Vision calls) so it never bites a file that is merely slow, but not
# multiples beyond that - a file this long is hung, not thinking. Override
# with RUN_TESTS_FILE_TIMEOUT=<int seconds>; 0 means no ceiling at all.
PER_FILE_TIMEOUT_SECONDS = 600
TIMEOUT_ENV = "RUN_TESTS_FILE_TIMEOUT"
DIR_FLAG = "--dir"

# CF-0612: the network guard and the live marks, the shared half loaded by path
# from the factory checkout (docs/test-hygiene.md, shared/test_hygiene.py).
_th_spec = importlib.util.spec_from_file_location(
    "test_hygiene", _fi_paths.factory_root() / "shared" / "test_hygiene.py")
test_hygiene = importlib.util.module_from_spec(_th_spec)
_th_spec.loader.exec_module(test_hygiene)
# CF-0682: the files the audit hook saw open the live tree in report mode
# (CF-0621); main() names them before the TOTAL line.
LIVE_TREE_NOTES = []
LIVE_FLAG, LIST_FLAG = "--live", "--list"


def per_file_timeout():
    """Ceiling in seconds, or None for no ceiling (RUN_TESTS_FILE_TIMEOUT=0)."""
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return PER_FILE_TIMEOUT_SECONDS
    try:
        seconds = int(raw)
    except ValueError:
        print(f"[run_tests] ignoring {TIMEOUT_ENV}={raw!r} (not an integer) - "
              f"using the default ceiling of {PER_FILE_TIMEOUT_SECONDS} s",
              flush=True)
        return PER_FILE_TIMEOUT_SECONDS
    return seconds if seconds > 0 else None


def kill_process_group(proc):
    """Kill the whole group the test file leads (start_new_session=True), so a
    grandchild that inherited our stdout pipe cannot keep the runner waiting
    after the file itself is dead.

    CF-0504: macOS answers EPERM (PermissionError), not ESRCH, when the group
    has no live member left - only a zombie leader not yet reaped. Both mean
    "the group is already dead"; catching only ESRCH killed the runner with a
    traceback - no FAILED, no TOTAL (self-test test_run_tests_killpg_eperm.py)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def reexec_under_venv():
    """CF-0054: pin the interpreter to the repo's own venv.

    The bug this closes was not a bad assertion, it was two people running
    the same suite on two different interpreters and getting two different
    numbers, both of them looking green. Choosing the interpreter here -
    rather than trusting whoever typed `python3` - removes that whole class
    of disagreement: there is exactly one interpreter this suite runs on, and
    it is the one whose dependencies the repo actually declares.

    A repo with no .venv (the pipeline-contract suite at the root, which is
    stdlib-only by design) runs on the current interpreter, and says so.
    """
    if os.environ.get(REEXEC_FLAG) == "1":
        return
    if not VENV_PY.exists():
        print(f"[run_tests] no {VENV_PY} - running on {sys.executable} "
              f"({sys.version.split()[0]})", flush=True)
        return
    if Path(sys.executable).resolve() == VENV_PY.resolve():
        print(f"[run_tests] interpreter: {sys.executable} "
              f"({sys.version.split()[0]}, repo venv)", flush=True)
        return
    print(f"[run_tests] re-running under the repo venv: {VENV_PY} "
          f"(you started it on {sys.executable})", flush=True)
    env = dict(os.environ, **{REEXEC_FLAG: "1"})
    completed = subprocess.run([str(VENV_PY), str(Path(__file__).resolve()),
                                *sys.argv[1:]], env=env)
    sys.exit(completed.returncode)


# CF-0489 (the root's CF-0378 guard): every file runs with TMPDIR pointed at a
# fresh directory of its own (`rt-XXXXXXXX`, flat and short: test paths land
# in runlog params capped at 120 chars). 17 files built fixtures under a
# bare tempfile.mkdtemp() / NamedTemporaryFile(delete=False) and never removed
# them - 14 entries per full run, measured 2026-10-02. Those files now
# build under `_tmproot.tmp_root`; this is the guard that keeps the next one
# from going unnoticed: whatever a file leaves in its TMPDIR once its process
# group is dead makes the file FAILED, by name, and is then removed so that it
# cannot pile up in the meantime.
RUN_TMP_PREFIX = "rt-"


def leftovers(tmp):
    """Names a finished test file left in its own TMPDIR (sorted)."""
    try:
        return sorted(os.listdir(tmp))
    except OSError:
        return []


def run_one(test_file, tmp=None, env_extra=None, env_drop=(), net=None):
    """Run one test file. Returns (passed, total, problems).

    CF-0612: `env_drop` - the live switches of other files, removed; `env_extra`
    - this file's own switch in `--live`; `net` = (trap, log path) - the
    network is off for this file (the plain run), None - `--live`, open.

    `problems` is empty only when the file exited 0 *and* printed a
    `N/N passed` line with N failures of zero. A file that dies on import
    prints no such line, and that alone is a failure: zero tests is not
    success.
    """
    print(f"--- {test_file.name} ---", flush=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    for var in env_drop:                         # live switches of other files: off
        env.pop(var, None)
    env.update(env_extra or {})                  # this file's switch, in --live
    if net is not None:
        trap, net_log = net
        trap.begin(test_file.name)
        env = test_hygiene.network_off_env(env, trap, net_log, test_file.name)
    else:                                        # --live: the guard off even if inherited
        env = test_hygiene.network_open_env(env)
    if tmp is not None:
        Path(tmp).mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(tmp)
    timeout = per_file_timeout()
    proc = subprocess.Popen([sys.executable, str(test_file)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=env,
                            start_new_session=True)
    # CF-0077: the ceiling. A timer rather than subprocess.run(timeout=...)
    # because the output below is streamed line by line, and because run()
    # kills only the direct child - a grandchild holding the pipe would keep
    # it waiting forever, which is the exact disease this closes.
    timed_out = threading.Event()

    def on_ceiling():
        timed_out.set()
        kill_process_group(proc)

    timer = threading.Timer(timeout, on_ceiling) if timeout else None
    if timer:
        timer.daemon = True
        timer.start()
    captured = []
    try:
        for line in proc.stdout:
            # Echoed as it arrives and kept: the runner has to read the
            # child's own summary, and the operator has to see the traceback
            # under the right header. The old runner let the parent's
            # block-buffered headers drift to the end of the log, which is
            # how a file dying on import came to look like a file that had
            # simply printed nothing.
            sys.stdout.write(line)
            captured.append(line)
        sys.stdout.flush()
        returncode = proc.wait()
    finally:
        if timer:
            timer.cancel()
        kill_process_group(proc)

    passed = total = 0
    saw_summary = False
    for line in captured:
        match = SUMMARY_RE.match(line)
        if match:
            saw_summary = True
            passed, total = int(match.group(1)), int(match.group(2))

    problems = []
    if timed_out.is_set():
        # The ceiling is the whole story; "exit code -9" and "no summary"
        # would only be its symptoms.
        problems.append(
            f"exceeded the per-file ceiling of {timeout} s (hung, not slow - "
            f"raise {TIMEOUT_ENV} only if the file is honestly this long)")
    else:
        if returncode != 0:
            problems.append(f"exit code {returncode}")
        if not saw_summary:
            problems.append("printed no 'N/N passed' summary line - it never "
                            "got far enough to run its checks (import "
                            "error?), or it does not print the agreed "
                            "summary at all")
        elif total == 0:
            problems.append("ran zero checks")
        elif passed != total:
            problems.append(f"{total - passed} of {total} checks failed")
    if net is not None:
        reached = test_hygiene.network_reaches(net[1], net[0], test_file.name)
        if reached:
            shown = ", ".join(reached[:5]) + (f" (+{len(reached) - 5})" if len(reached) > 5 else "")
            problems.append(f"reached for the network with it off: {shown} - "
                            f"{test_hygiene.NET_HINT} (CF-0609)")
        # CF-0621/CF-0682: what the audit hook saw the file open or list in the live tree.
        live = test_hygiene.live_tree_reads(net[1])
        if live:
            shown = ", ".join(live[:5]) + (f" (+{len(live) - 5})" if len(live) > 5 else "")
            said = f"opened the live tree: {shown} - {test_hygiene.LIVE_HINT} (CF-0621)"
            if test_hygiene.live_tree_strict():
                problems.append(said)
            else:
                LIVE_TREE_NOTES.append(test_file.name)
                print(f"LIVE-TREE {test_file.name}: {said}; report mode - "
                      f"FAILED under {test_hygiene.LIVE_TREE_MODE_ENV}=strict", flush=True)
    if tmp is not None:
        left = leftovers(tmp)
        if left:
            shown = ", ".join(left[:5]) + (f" (+{len(left) - 5})" if len(left) > 5 else "")
            problems.append(f"left {len(left)} temp entr{'y' if len(left) == 1 else 'ies'} "
                            f"behind in its TMPDIR ({shown}) - build them under "
                            f"_tmproot.tmp_root (CF-0489)")
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        print(f"FAIL {test_file.name}: {'; '.join(problems)}", flush=True)
    else:
        print(f"PASS {test_file.name}: {passed}/{total}", flush=True)
    return passed, total, problems


HELP_FLAGS = ("--help", "-h")
USAGE = f"usage: run_tests.py [{DIR_FLAG} PATH] [{LIVE_FLAG}] [{LIST_FLAG}] [FILE ...]"
HELP_TEXT = f"""{USAGE}

Runs the test_*.py files of this directory, each in its own process with the
network off, its own TMPDIR and a per-file ceiling; ends with a TOTAL line.

  FILE ...      run only these files: tests/test_x.py, test_x.py or test_x
                (same isolation as the whole suite). Without FILE - every file.
  {DIR_FLAG} PATH    another directory of test_*.py (the runner's own tests)
  {LIVE_FLAG}        only the live tests, network open, live switches on
  {LIST_FLAG}        print what would run, run nothing
  --help, -h    this text, nothing run

An unknown flag or a FILE that is not there is exit 2 (CF-0679).
Rule: docs/test-hygiene.md at the factory root."""


class UsageError(Exception):
    """A command line the runner refuses - exit 2, nothing run (CF-0679)."""


def parse_args(argv):
    """{"help", "dir", "live", "list", "files"} from the command line.

    CF-0679: every argument is accounted for. A FILE is kept as written here and
    resolved against the test directory by `select_files`; anything starting with
    `-` that is not a known flag is a UsageError - the old runner ignored what it
    did not know and ran the whole suite."""
    out = {"help": False, "dir": None, "live": False, "list": False, "files": []}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in HELP_FLAGS:
            out["help"] = True
        elif arg == DIR_FLAG:
            if i + 1 >= len(argv):
                raise UsageError(f"{DIR_FLAG} needs a PATH")
            i += 1
            out["dir"] = argv[i]
        elif arg.startswith(DIR_FLAG + "="):
            out["dir"] = arg.split("=", 1)[1]
            if not out["dir"]:
                raise UsageError(f"{DIR_FLAG}= needs a PATH")
        elif arg == LIVE_FLAG:
            out["live"] = True
        elif arg == LIST_FLAG:
            out["list"] = True
        elif arg.startswith("-"):
            raise UsageError(f"unknown argument {arg!r}")
        else:
            out["files"].append(arg)
        i += 1
    return out


def tests_dir(argv):
    """`--dir PATH` points the runner at another directory of test_*.py.
    Exists for the runner's own test (CF-0077); by default it is this one."""
    try:
        given = parse_args(argv)["dir"]
    except UsageError as exc:
        raise SystemExit(f"{exc}\n{USAGE}")
    return Path(given).resolve() if given else HERE


def select_files(where, names):
    """The test files `names` point at in `where`, in the order given, no repeats.

    A name is `tests/test_x.py`, `test_x.py` or `test_x`. One with a directory
    part that exists as a file must be in `where`; otherwise its last part is
    looked up in `where`. A name that matches no test_*.py there is a
    UsageError (CF-0679) - never "run everything instead"."""
    chosen, missing = [], []
    for name in names:
        given = Path(name)
        if given.parent != Path(".") and given.is_file():
            if given.resolve().parent != where:
                raise UsageError(f"{name} is not in {where}")
        base = given.name if given.name.endswith(".py") else given.name + ".py"
        target = where / base
        if not base.startswith("test_") or not target.is_file():
            missing.append(name)
            continue
        if target not in chosen:
            chosen.append(target)
    if missing:
        raise UsageError(f"no such test file in {where}: {', '.join(missing)}")
    return chosen


def main():
    argv = sys.argv[1:]
    # CF-0679: the command line is checked before anything starts - before the
    # venv re-run, before a single file - so a typo costs a line, not the suite.
    try:
        args = parse_args(argv)
        if args["help"]:
            print(HELP_TEXT)
            return 0
        where = Path(args["dir"]).resolve() if args["dir"] else HERE
        selected = select_files(where, args["files"]) if args["files"] else None
    except UsageError as exc:
        print(f"[run_tests] {exc}\n{USAGE}\n(--help for more; nothing was run)",
              file=sys.stderr, flush=True)
        return 2
    reexec_under_venv()
    live_mode = args["live"]
    if selected is not None:
        test_files = selected
        print(f"[run_tests] only {len(selected)} file(s) named on the command line: "
              f"{', '.join(f.name for f in selected)}", flush=True)
    else:
        test_files = sorted(where.glob("test_*.py"))
    if not test_files:
        print(f"FAIL: no test_*.py found in {where}")
        return 1
    runs, skipped, switches = test_hygiene.plan(where, test_files, live_mode)
    if selected is not None and not runs:
        for line in skipped:
            print(line, flush=True)
        print(f"[run_tests] nothing to run: the named file(s) are "
              f"{'not live - drop ' + LIVE_FLAG if live_mode else 'live - add ' + LIVE_FLAG}",
              file=sys.stderr, flush=True)
        return 2
    ceiling = per_file_timeout()
    print(f"[run_tests] per-file ceiling: "
          f"{f'{ceiling} s' if ceiling else 'none'} ({TIMEOUT_ENV})",
          flush=True)
    if live_mode:
        print(f"[run_tests] {LIVE_FLAG}: only the live tests, network open, live data on "
              f"(CF-0612) - {len(runs)} file(s)", flush=True)
    else:
        print(f"[run_tests] network: off past loopback (CF-0612, "
              f"{test_hygiene.NET_GUARD_DIR.name}); live parts skipped - run them "
              f"with {LIVE_FLAG}", flush=True)
    for line in skipped:
        print(line, flush=True)
    if args["list"]:
        for f, switch_on, why in runs:
            on = " ".join(f"{k}={v}" for k, v in switch_on.items())
            print(f"would run: {f.name}{f' ({on})' if on else ''}"
                  f"{f' - {why}' if live_mode and why else ''}")
        print(f"[run_tests] {LIST_FLAG}: {len(runs)} file(s) planned, nothing run")
        return 0
    if live_mode and not runs:
        print(f"[run_tests] no live tests in {where}")
        print("TOTAL 0/0 passed in 0 files")
        return 0

    trap = None if live_mode else test_hygiene.ProxyTrap()
    # The guard's logs live outside every file's own TMPDIR (CF-0489 would
    # flag them as leftovers).
    net_dir = None if live_mode else Path(tempfile.mkdtemp(prefix="rt-net-"))
    passed = total = 0
    broken = []
    try:
        for test_file, switch_on, _why in runs:
            file_tmp = Path(tempfile.mkdtemp(prefix=RUN_TMP_PREFIX))
            net = None if live_mode else (trap, net_dir / f"{test_file.stem}.jsonl")
            try:
                file_passed, file_total, problems = run_one(
                    test_file, file_tmp, env_extra=switch_on,
                    env_drop=[s for s in switches if s not in switch_on], net=net)
            finally:
                shutil.rmtree(file_tmp, ignore_errors=True)
            passed += file_passed
            total += file_total
            if problems:
                broken.append((test_file.name, problems))
    finally:
        if trap is not None:
            trap.close()
        if net_dir is not None:
            shutil.rmtree(net_dir, ignore_errors=True)

    print()
    for name, problems in broken:
        print(f"FAILED {name}: {'; '.join(problems)}")
    if skipped:
        print(f"skipped live: {len(skipped)} (python3 tests/run_tests.py {LIVE_FLAG})")
    if LIVE_TREE_NOTES:
        print(f"live tree: {len(LIVE_TREE_NOTES)} file(s) opened it, not FAILED in report mode "
              f"({test_hygiene.LIVE_TREE_MODE_ENV}=strict fails them, CF-0621): "
              f"{', '.join(LIVE_TREE_NOTES)}")
    print(f"TOTAL {passed}/{total} passed in {len(runs)} files"
          f"{f' - {len(broken)} FAILED' if broken else ''}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())

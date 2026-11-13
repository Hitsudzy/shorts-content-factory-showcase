#!/usr/bin/env python3
"""Run every test_*.py in this directory. No pytest dependency, no CI - just
a script to run by hand before closing a version (CF-0024).

CF-0054: this runner is the instrument the whole dev process leans on, so it
is built to fail loudly rather than quietly. A test file counts as passing
only if it exits 0 *and* prints a `N/N passed` summary line with no failures
in it. A file that dies on import, crashes, or prints no result at all is a
FAIL - "zero tests" is not "success" - and the runner itself exits non-zero.
It also pins the interpreter to the repo's own venv when there is one, so
that the answer does not depend on which python you happened to type - the
*main* checkout's, since a git worktree has none of its own (CF-0125).

CF-0077: a hung file is worse than a failed one - it looks like "still
computing" and eats the whole window. Every file runs under a per-file
ceiling; on expiry the file's whole process group is killed (so a hung
grandchild - Vision worker, ffmpeg - dies with it) and the file is reported
FAILED, naming the file and the ceiling, on the same path as an import death.

CF-0613 (docs/test-hygiene.md at the factory root): a test does not go to the
network and does not read live data. Every file of the plain run starts with
the network off past loopback - the root's `shared/no_network` first on its
PYTHONPATH, every proxy variable pointed at a trap of this runner's own, the
HF/transformers offline switches on (a model in the local cache is a
dependency; asking the hub whether it changed is the network, CF-0521) - and
whatever it reached for makes it FAILED, whatever it printed. A test that has
to talk to the world is marked live (`LIVE_TEST = "why"` for a whole file,
`LIVE_ENV = "SWITCH"` for a live part, `tests/_live_monitors.py` with
VE_TESTS_LIVE for the live-tree monitors) and runs only with `--live`;
`--list` prints the plan. The shared half is `shared/test_hygiene.py` of the
factory checkout, loaded by path through `repo_paths.factory_root()` (one copy
of the rule, CF-0159).

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
REEXEC_FLAG = "RUN_TESTS_UNDER_VENV"


def _repo_paths(repo):
    """`<repo>/scripts/repo_paths.py` loaded by path, or None (see below)."""
    module = repo / "scripts" / "repo_paths.py"
    if not module.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_run_tests_repo_paths", module)
    repo_paths = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(repo_paths)
    except Exception:
        return None
    return repo_paths


def _venv_python(repo):
    """CF-0125: `<repo>/.venv` is the right answer only in the main checkout.
    `.venv/` is gitignored, so a git worktree - which is where every auto-dev
    worker runs - has none, and this runner used to shrug and fall through to
    whatever `python3` the shell meant (3.9, no PIL): 31 of 39 files failed on
    import, indistinguishable from a real regression, every single time.

    scripts/repo_paths.py knows which checkout is the main one (it reads git's
    own worktree metadata). Loaded by path rather than imported, because this
    runner is also the one the stdlib-only pipeline suite at the factory root
    uses, and that repo has no scripts/repo_paths.py at all."""
    repo_paths = _repo_paths(repo)
    if repo_paths is None:
        return repo / ".venv" / "bin" / "python3"  # repo_paths-bootstrap
    return Path(repo_paths.venv_python(name="python3"))


VENV_PY = _venv_python(REPO)


def _factory_root(repo):
    """CF-0613: the factory checkout whose `shared/test_hygiene.py` this runner
    loads - `repo_paths.factory_root()` (a version's root worktree, else the
    checkout above agents/), else the nearest ancestor that holds the file."""
    repo_paths = _repo_paths(repo)
    if repo_paths is not None:
        root = Path(repo_paths.factory_root())
        if (root / "shared" / "test_hygiene.py").is_file():
            return root
    for p in [repo, *repo.parents]:
        if (p / "shared" / "test_hygiene.py").is_file():
            return p
    raise SystemExit(f"[run_tests] no shared/test_hygiene.py above {repo} - "
                     "the factory checkout is not reachable (CF-0613)")


# CF-0613: the network guard and the live marks, the shared half loaded by path
# from the factory checkout (docs/test-hygiene.md, shared/test_hygiene.py).
_th_spec = importlib.util.spec_from_file_location(
    "test_hygiene", _factory_root(REPO) / "shared" / "test_hygiene.py")
test_hygiene = importlib.util.module_from_spec(_th_spec)
_th_spec.loader.exec_module(test_hygiene)
# CF-0682: the files the audit hook saw open the live tree in report mode
# (CF-0621); main() names them before the TOTAL line.
LIVE_TREE_NOTES = []
LIVE_FLAG, LIST_FLAG = "--live", "--list"

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

# CF-0107: run accounting must never write into a batch a test merely reads.
# The instrumented scripts resolve their batch dir, when RUNLOG_BATCH is not
# set, from any path-looking argv element shaped pipeline/<channel>/<batch>
# (shared/runlog/runlog.py, lookup rule 3) - and the e2e tests replay real
# batch paths (work/wren-hollow-lockhart..., 05-video-editor.json, plans
# under pipeline/legacy-film/<batch>/ - the channel is example-film since
# CF-0180, but its batch directories keep the old slug: they are a dated
# journal and were deliberately not renamed). One full suite on main wrote 1596
# stray events into the real 2026-08-31T2155Z batch that way. So the runner
# exports RUNLOG_BATCH to a fresh temp dir for the whole suite (rule 2 wins
# over rule 3) - unless the environment already sets it - and RUNLOG_STATE_DIR
# to a temp dir too, so no test touches ~/.shorts-content-factory. The temp
# dirs are removed when the suite ends. And because an export is a policy, not
# a proof, the runner also snapshots every RUN_EVENTS.jsonl under the real
# pipeline/ before the suite and compares after it: any batch whose events
# file appeared, vanished or changed size is a FAIL of the whole run.
BATCH_ENV = "RUNLOG_BATCH"
STATE_DIR_ENV = "RUNLOG_STATE_DIR"
EVENTS_FILE = "RUN_EVENTS.jsonl"
PIPELINE_ROOT_ENV = "RUN_TESTS_PIPELINE_ROOT"   # the guard's root; default: the checkout's pipeline/
GUARD_NAME = "run-accounting guard"
# pipeline/backfill/<batch>/ holds the synthetic events `runlog backfill`
# (CF-0111) reconstructs for runs that predate accounting - git-tracked, and
# rewritten by that tool, not by any path a test replays. Not a real batch.
GUARD_SKIP_DIRS = ("backfill",)


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
    if VENV_PY.parent.parent.parent != REPO:
        print(f"[run_tests] this is a worktree ({REPO}); its venv, and every "
              f"path outside the repo, come from {VENV_PY.parent.parent.parent} "
              "(CF-0125)", flush=True)
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


def pipeline_root():
    """The pipeline/ directory whose batches the guard watches:
    RUN_TESTS_PIPELINE_ROOT when set, else the nearest ancestor of this repo
    that holds one (two levels up in the main checkout, further up from a
    worktree under .claude/worktrees/), else None - nothing to guard."""
    override = os.environ.get(PIPELINE_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    for p in [REPO, *REPO.parents]:
        if (p / "pipeline").is_dir():
            return p / "pipeline"
    return None


def snapshot_events(root):
    """{path: size} of every <root>/<channel>/<batch>/RUN_EVENTS.jsonl - the
    shape lookup rule 3 resolves a real-batch path to, and the thing a test
    must never change. Skips GUARD_SKIP_DIRS."""
    if root is None or not root.is_dir():
        return {}
    return {str(p): p.stat().st_size
            for p in sorted(root.glob(f"*/*/{EVENTS_FILE}"))
            if p.parent.parent.name not in GUARD_SKIP_DIRS}


def events_drift(before, after):
    """Human-readable list of what changed between two snapshots."""
    drift = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            drift.append(f"appeared: {path} ({after[path]} bytes)")
        elif path not in after:
            drift.append(f"vanished: {path}")
        elif before[path] != after[path]:
            drift.append(f"changed: {path} ({before[path]} -> {after[path]} bytes)")
    return drift


# CF-0482: a batch that is *live* - started and not finished (`runlog
# batch-active`'s own byte test: a batch-start marker and no batch-done), its
# last event before the suite no older than LIVE_HOURS - is written by its own
# processes while the suite runs, and in a version's root worktree pipeline/*
# is a link to the working copy's batches, so the guard saw a production batch
# grow and failed the suite on it. Those files are reported and not judged.
# Nothing else is relaxed: a closed batch that changes is still a FAIL, and a
# test cannot reach a live batch either way - the runner exports RUNLOG_BATCH,
# and every test file imports `_isolated_runlog` for the runs nobody wraps.
LIVE_HOURS = 24.0
BATCH_START = b'"batch-start"'
BATCH_DONE = b'"batch-done"'


def _last_ts_before(path, size):
    """The `ts` of the last whole event in the first `size` bytes, or None."""
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 65536))
            chunk = fh.read(size - max(0, size - 65536))
    except OSError:
        return None
    for line in reversed(chunk.splitlines()):
        m = re.search(rb'"ts":\s*"([^"]+)"', line)
        if m:
            return m.group(1).decode("ascii", "replace")
    return None


def live_batch(path, size_before, now=None):
    """None, or why `path`'s batch counts as live (see LIVE_HOURS)."""
    from datetime import datetime, timezone
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if BATCH_START not in data or BATCH_DONE in data:
        return None
    ts = _last_ts_before(path, size_before) if size_before else None
    if ts is None:
        # it appeared during the suite: live only if it opened itself then
        return "opened during the suite" if BATCH_START in data[:65536] else None
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    if (now - last).total_seconds() > LIVE_HOURS * 3600:
        return None
    return f"open, last event before the suite {ts}"


def appended_writers(path, size_before, limit=3):
    """`name/step pid` of the first few writers of the bytes appended since
    `size_before` - so a FAIL names the processes, not only the file."""
    import json
    try:
        with open(path, "rb") as fh:
            fh.seek(size_before or 0)
            chunk = fh.read(1 << 20)
    except OSError:
        return []
    seen = []
    for line in chunk.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("kind") != "script":
            continue
        who = f"{e.get('name') or e.get('step')} pid {e.get('pid')}"
        if who not in seen:
            seen.append(who)
        if len(seen) >= limit:
            break
    return seen


def judge_drift(before, after, during=None, now=None):
    """(problems, notes): `events_drift` minus live batches, each problem
    naming the test files it happened during and the processes that wrote."""
    during = during or {}
    problems, notes = [], []
    for item in events_drift(before, after):
        path = item.split(": ", 1)[1].rsplit(" (", 1)[0]
        why = live_batch(path, before.get(path, 0), now) if path in after else None
        if why:
            notes.append(f"{path} is a live batch ({why}) - "
                         f"{after[path] - before.get(path, 0)} new bytes not judged")
            continue
        extra = []
        if during.get(path):
            extra.append("during " + ", ".join(during[path]))
        writers = appended_writers(path, before.get(path, 0)) if path in after else []
        if writers:
            extra.append("written by " + ", ".join(writers))
        problems.append(item + (f" [{'; '.join(extra)}]" if extra else ""))
    return problems, notes


class RunlogIsolation:
    """Export RUNLOG_BATCH and RUNLOG_STATE_DIR to fresh temp dirs for the
    suite, unless the environment already sets them; remove what we made."""

    def __init__(self):
        self.exports = {}
        self.made = []

    def __enter__(self):
        for var in (BATCH_ENV, STATE_DIR_ENV):
            if os.environ.get(var):
                print(f"[run_tests] {var}={os.environ[var]} (kept from the environment)",
                      flush=True)
                continue
            path = tempfile.mkdtemp(prefix=f"run-tests-{var.lower()}-")
            self.made.append(path)
            self.exports[var] = path
            os.environ[var] = path
            print(f"[run_tests] {var}={path} (temp, removed when the suite ends)",
                  flush=True)
        return self

    def __exit__(self, *exc):
        for var in self.exports:
            os.environ.pop(var, None)
        for path in self.made:
            shutil.rmtree(path, ignore_errors=True)
        return False


# CF-0489 (the root's CF-0378 guard, as in content-researcher and
# footage-indexer): every file runs with TMPDIR pointed at a fresh directory of
# its own (`rt-XXXXXXXX`, flat and short: test paths land in runlog params
# capped at 120 chars). Video-editor files built fixtures under a bare
# tempfile.mkdtemp() and never removed them, and a dozen made a
# `cfNNNN-runlog-*` dir on every run through an eagerly evaluated
# `os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(...))` - 26 files,
# measured 2026-10-02. Those files now build under `_tmproot.tmp_root`; this is
# the guard that keeps the next one from going unnoticed: whatever a file leaves
# in its TMPDIR once its process group is dead makes the file FAILED, by name,
# and is then removed so that it cannot pile up in the meantime.
RUN_TMP_PREFIX = "rt-"
# Node's module compile cache (the Remotion renders) defaults to
# <tmpdir>/node-compile-cache: one shared, reused cache, not a per-run tree. It
# is pointed at the suite's own tempdir, where it always lived, so a file that
# renders neither loses the cache nor leaves it in its TMPDIR.
NODE_CACHE_ENV = "NODE_COMPILE_CACHE"
NODE_CACHE_DIR = "node-compile-cache"


def leftovers(tmp):
    """Names a finished test file left in its own TMPDIR (sorted)."""
    try:
        return sorted(os.listdir(tmp))
    except OSError:
        return []


def run_one(test_file, extra_env=None, tmp=None, env_extra=None, env_drop=(), net=None):
    """Run one test file. Returns (passed, total, problems).

    CF-0613: `env_drop` - the live switches of other files, removed; `env_extra`
    - this file's own switch in `--live`; `net` = (trap, log path) - the
    network is off for this file (the plain run), None - `--live`, open.

    `problems` is empty only when the file exited 0 *and* printed a
    `N/N passed` line with N failures of zero. A file that dies on import
    prints no such line, and that alone is a failure: zero tests is not
    success.
    """
    print(f"--- {test_file.name} ---", flush=True)
    # CF-0107: the run-accounting exports ride along explicitly, next to the
    # unbuffered flag, so a per-file env built here cannot lose them.
    env = dict(os.environ, PYTHONUNBUFFERED="1", **(extra_env or {}))
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
        env.setdefault(NODE_CACHE_ENV, str(Path(tempfile.gettempdir()) / NODE_CACHE_DIR))
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
              f"(CF-0613) - {len(runs)} file(s)", flush=True)
    else:
        print(f"[run_tests] network: off past loopback (CF-0613, "
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

    root = pipeline_root()
    print(f"[run_tests] {GUARD_NAME}: watching {EVENTS_FILE} under "
          f"{root if root else 'nothing (no pipeline/ found)'} ({PIPELINE_ROOT_ENV})",
          flush=True)
    trap = None if live_mode else test_hygiene.ProxyTrap()
    # The guard's logs live outside every file's own TMPDIR (CF-0489 would
    # flag them as leftovers).
    net_dir = None if live_mode else Path(tempfile.mkdtemp(prefix="rt-net-"))
    passed = total = 0
    broken = []
    during = {}     # CF-0482: which test files a real batch changed during
    try:
        with RunlogIsolation() as isolation:
            before = snapshot_events(root)
            prev = before
            for test_file, switch_on, _why in runs:
                file_tmp = Path(tempfile.mkdtemp(prefix=RUN_TMP_PREFIX))
                net = None if live_mode else (trap, net_dir / f"{test_file.stem}.jsonl")
                try:
                    file_passed, file_total, problems = run_one(
                        test_file, isolation.exports, file_tmp, env_extra=switch_on,
                        env_drop=[s for s in switches if s not in switch_on], net=net)
                finally:
                    shutil.rmtree(file_tmp, ignore_errors=True)
                passed += file_passed
                total += file_total
                if problems:
                    broken.append((test_file.name, problems))
                now = snapshot_events(root)
                for path in set(prev) | set(now):
                    if prev.get(path) != now.get(path):
                        during.setdefault(path, []).append(test_file.name)
                prev = now
            after = prev
    finally:
        if trap is not None:
            trap.close()
        if net_dir is not None:
            shutil.rmtree(net_dir, ignore_errors=True)
    drift, notes = judge_drift(before, after, during)
    for note in notes:
        print(f"NOTE {GUARD_NAME}: {note}", flush=True)
    if drift:
        problems = [f"a test wrote run accounting into a real batch under {root} - "
                    + "; ".join(drift)]
        print(f"FAIL {GUARD_NAME}: {problems[0]}", flush=True)
        broken.append((GUARD_NAME, problems))
    else:
        live = f" ({len(notes)} live batch(es) not judged)" if notes else ""
        print(f"PASS {GUARD_NAME}: {len(before)} {EVENTS_FILE} under {root} unchanged{live}",
              flush=True)

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

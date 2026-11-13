#!/usr/bin/env python3
"""CF-0511: the live monitors are a step of closing a batch - after `batch-done`.

The defect. Since CF-0503 no root test reads the live `pipeline/` or the live
footage pool: `tests/_real_batches.py` walks the frozen corpus, and the live
tree only with `ROOT_TESTS_LIVE=1`. Its registry `LIVE_MONITORS` names the
checks whose question is "what did the factory ship lately" - the fresh window
of the pattern envelope, the funnel vocabulary and the gate rules over every
batch, "today's batches" of the stop-cock, the CF-0224 fact boundary - and the
agents keep the same registry in `agents/<name>/tests/_live_monitors.py`
(`FI_TESTS_LIVE`, `TH_TESTS_LIVE`, `VE_TESTS_LIVE`). Before CF-0503 those
checks caught a new batch on every run of the suite; after it, never - nobody
ran them, and a red one stayed in a log nobody opened.

The user's decision of 2026-10-04: the live monitors are a **step of closing a
batch**, after `batch-done` (as the frame judge and the triage are steps of the
run, not a memory), and **a red monitor reaches a person** - a line near the top
of `RUN_SUMMARY.md` and a keyed task from `runlog triage`.

    runlog monitors [--batch DIR] [--root DIR] [--root-only]
                    [--file-ceiling S] [--ceiling S] [--dry-run] [--json]

What it does:

* reads the registries - the root's `tests/_real_batches.py` and every agent's
  `tests/_live_monitors.py` - by AST (`LIVE_ENV`, `LIVE_MONITORS`), never by
  importing them; a registry that cannot be read is a red line of its own;
* runs each named test FILE once, `<LIVE_ENV>=1 python3 tests/<file>` in its
  repo, under a per-file ceiling (`FILE_CEILING_S`, the per-file ceiling of
  `tests/run_tests.py`) and the step's own ceiling (`TOTAL_CEILING_S`); a file
  past its ceiling is killed with its whole process group (`timeout`), a file
  the step had no time left for is `not_run`. The unit is the file and not the
  test: the house harness runs a file whole, and the agents' registries name
  helpers (`_live_pool`), not tests;
* judges a file by the CF-0054 contract of `tests/run_tests.py`: green only on
  exit 0 *and* a `N/N passed` line with no failure in it; a file whose monitor
  had nothing to check (CF-0558: `NOT_CHECKED <test>: <monitor>: <why>`, the
  line `N-k/N passed, k not checked`, exit 3) is `not_checked` - not green, and
  not red either: nothing broke, the monitor saw nothing (CF-0622);
* writes one event into `RUN_EVENTS.jsonl` - kind `monitors`, status `green` or
  `red`, the field `monitors` with every file's verdict and its first error
  line. It is not activity (it opens nothing and is not part of the wall,
  which ends at `batch-done`), so it goes into the journal of a closed batch;
* writes `MONITORS.txt` into the batch (the output of every file that was not
  green - where the summary line points) and re-writes `RUN_SUMMARY.md`, whose
  line about the monitors `batch-done` wrote as "not run yet".

Exit 0 - every monitor green; 1 - at least one is not (`not_checked` included:
not checked is not green); 2 - no batch, or a batch that has not reached
`batch-done` (the monitors judge a finished run).

The triage (`triage.py`) reads the event: every file that is red, timed out,
missing or not run is an **авария** of the kind `live_monitor`, one task per
file key - see the note at LIVE_MONITOR there for why it is an авария and not a
finding; a monitor that was `not_checked` is a **находка** (`monitor_not_checked`,
CF-0622) - a task on that monitor, one per monitor key.
"""
import ast
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

TASK = "CF-0511"
EVENT_KIND = "monitors"
EVENT_KEY = "monitors"
REPORT_FILE = "MONITORS.txt"
ROOT_REGISTRY = "tests/_real_batches.py"
AGENT_REGISTRY = "tests/_live_monitors.py"
FILE_CEILING_S = 600            # = tests/run_tests.py PER_FILE_TIMEOUT_SECONDS (CF-0077)
TOTAL_CEILING_S = 1800          # the whole step; past it the rest is `not_run`
REPORT_TAIL_LINES = 80

GREEN = "green"
RED = "red"                     # the file ran and failed (or broke the summary-line contract)
TIMEOUT = "timeout"             # killed at its ceiling
MISSING = "missing"             # the registry names a file that is not there / cannot be read
NOT_RUN = "not_run"             # the step's own ceiling left no time for it
NOT_CHECKED = "not_checked"     # CF-0622: no failure, but a monitor had nothing to check
STATES = (GREEN, RED, TIMEOUT, MISSING, NOT_RUN, NOT_CHECKED)

SUMMARY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s+passed\b", re.M)   # tests/run_tests.py
FAIL_RE = re.compile(r"^FAIL[:\s]+([\w.:]+)", re.M)
# CF-0558 (agents/video-editor/tests/_live_monitors.py): a monitor that found
# nothing to check prints `NOT_CHECKED <test>: <monitor>: <why>` and its file
# exits EXIT_NOT_CHECKED (3) when nothing failed.
NOT_CHECKED_RE = re.compile(r"^NOT_CHECKED\s+([\w.:]+):\s*(.*)$", re.M)
EXIT_NOT_CHECKED = 3
MONITOR_RE = re.compile(r"^([\w.-]+\.py::[\w.]+):\s*(.*)$")   # `<file.py::owner>: <why>`
ERROR_MAX = 300
FAILED_MAX = 20


class NotClosed(Exception):
    """The batch has no `batch-done`: the monitors are a step of the close."""


# --------------------------------------------------------------------------
# the registries
# --------------------------------------------------------------------------

def _literals(path, names):
    """{name: value} of the module-level `NAME = <literal>` assignments of
    `path` - read by AST, so a registry is never imported (and never runs)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def _specs_of(label, repo_dir, registry, required):
    """[spec] of one repo's registry, one per test file it names."""
    path = Path(repo_dir) / registry
    base = {"repo": label, "dir": str(repo_dir), "registry": registry}
    if not path.is_file():
        if required:
            return [dict(base, env=None, file=registry, monitors=[],
                         error=f"registry {registry} not found in {repo_dir}")]
        return []
    try:
        lit = _literals(path, ("LIVE_ENV", "LIVE_MONITORS"))
    except (OSError, SyntaxError, ValueError) as e:
        return [dict(base, env=None, file=registry, monitors=[],
                     error=f"registry {registry} unreadable ({e.__class__.__name__}: {e})")]
    env, mons = lit.get("LIVE_ENV"), lit.get("LIVE_MONITORS")
    if not isinstance(env, str) or not isinstance(mons, dict):
        return [dict(base, env=env if isinstance(env, str) else None, file=registry,
                     monitors=[], error=f"registry {registry}: no literal LIVE_ENV / "
                                        f"LIVE_MONITORS to read")]
    files = {}
    for key in mons:
        name, _, owner = str(key).partition("::")
        files.setdefault(name, []).append(owner or name)
    return [dict(base, env=env, file=f"tests/{name}", monitors=owners, error=None)
            for name, owners in sorted(files.items())]


def registry(root=None, agents=True):
    """[spec] - every test file a live-monitor registry names, the root's first:
    {repo, dir, registry, env, file, monitors: [owner], error}."""
    root = Path(root) if root else runlog.factory_root()
    out = _specs_of(runlog.ROOT_REPO, root, ROOT_REGISTRY, required=True)
    if agents:
        for label, d in runlog.factory_repos(root)[1:]:
            out += _specs_of(label, d, AGENT_REGISTRY, required=False)
    return out


# --------------------------------------------------------------------------
# running one file
# --------------------------------------------------------------------------

def _python(repo_dir):
    venv = Path(repo_dir) / ".venv" / "bin" / "python3"
    return str(venv) if venv.is_file() else sys.executable


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def not_checked_of(text):
    """[{test, monitor, why}] of the `NOT_CHECKED` lines of a file's output
    (CF-0558); `monitor` is the registry key the line names, or None when the
    line names none (then the test stands for it)."""
    out = []
    for test, rest in NOT_CHECKED_RE.findall(text or ""):
        m = MONITOR_RE.match(rest.strip())
        out.append({"test": test, "monitor": m.group(1) if m else None,
                    "why": (m.group(2) if m else rest).strip()[:ERROR_MAX]})
    return out


def judge(rc, text):
    """(state, passed line, failed names, error line) of one finished file by
    the CF-0054 contract: green only on exit 0 and a `N/N passed` line.
    CF-0622: no `FAIL` line, exit 0 or EXIT_NOT_CHECKED and a `NOT_CHECKED`
    line - `not_checked`, the failed names being the tests not checked and the
    error line the first `NOT_CHECKED` line."""
    hits = SUMMARY_RE.findall(text or "")
    passed = f"{hits[-1][0]}/{hits[-1][1]}" if hits else None
    failed = list(dict.fromkeys(m.rstrip(":") for m in FAIL_RE.findall(text or "")))
    whole = bool(hits) and hits[-1][0] == hits[-1][1]
    fail_lines = [ln for ln in (text or "").splitlines() if ln.startswith("FAIL")]
    unchecked = NOT_CHECKED_RE.findall(text or "")
    if not fail_lines and rc in (0, EXIT_NOT_CHECKED) and unchecked:
        first = NOT_CHECKED_RE.search(text).group(0).strip()
        tests = list(dict.fromkeys(t for t, _ in unchecked))
        return NOT_CHECKED, passed, tests[:FAILED_MAX], first[:ERROR_MAX]
    if rc == 0 and whole:
        return GREEN, passed, [], None
    if fail_lines:
        err = fail_lines[0]
    elif rc != 0:
        tail = [ln for ln in (text or "").splitlines() if ln.strip()]
        err = f"exit {rc}" + (f": {tail[-1].strip()}" if tail else " with no output")
    else:
        err = (f"exit 0 but {passed} passed" if passed else
               "exit 0 without the `N/N passed` line (CF-0054: no result is no success)")
    return RED, passed, failed[:FAILED_MAX], err[:ERROR_MAX]


def run_file(spec, ceiling_s):
    """Run one registry file live under `ceiling_s`. Returns (verdict, output)."""
    v = {"repo": spec["repo"], "file": spec["file"], "env": spec.get("env"),
         "monitors": list(spec.get("monitors") or []), "state": None, "rc": None,
         "seconds": 0.0, "passed": None, "failed": [], "error": None}
    if spec.get("error"):
        return dict(v, state=MISSING, error=spec["error"][:ERROR_MAX]), spec["error"]
    path = Path(spec["dir"]) / spec["file"]
    if not path.is_file():
        err = f"{spec['file']} not found in {spec['dir']} (named by {spec.get('registry')})"
        return dict(v, state=MISSING, error=err), err
    env = dict(os.environ)
    env[spec["env"]] = "1"
    env.pop(runlog.BATCH_ENV, None)         # a test is never a writer into the closed batch
    env.pop(runlog.STAGE_ENV, None)
    t0 = time.monotonic()
    with tempfile.TemporaryFile() as out:
        # Output to a file, not a pipe: nothing to drain, so the deadline on
        # wait() is the whole deadline (CF-0132), and the group dies past it.
        proc = subprocess.Popen([_python(spec["dir"]), str(path)], cwd=spec["dir"], env=env,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            rc = proc.wait(timeout=ceiling_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            rc = None
        secs = round(time.monotonic() - t0, 1)
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    if rc is None:
        return dict(v, state=TIMEOUT, seconds=secs,
                    error=f"killed at its ceiling of {ceiling_s:g} s"), text
    state, passed, failed, err = judge(rc, text)
    v = dict(v, state=state, rc=rc, seconds=secs, passed=passed, failed=failed, error=err)
    if state == NOT_CHECKED:
        v["not_checked"] = not_checked_of(text)[:FAILED_MAX]
    return v, text


# --------------------------------------------------------------------------
# the step
# --------------------------------------------------------------------------

def _closed(events):
    return any(e.get("kind") == runlog.KIND_MARKER and e.get("status") == runlog.M_BATCH_DONE
               for e in events)


def run(batch_dir, specs=None, root=None, agents=True, file_ceiling=FILE_CEILING_S,
        total_ceiling=TOTAL_CEILING_S, write=True, require_done=True):
    """Run every monitor of the registries; with `write`, append the event,
    write MONITORS.txt and re-write RUN_SUMMARY.md. Returns the result."""
    bd = Path(batch_dir)
    if require_done and not _closed(runlog.read_events(bd)):
        raise NotClosed(f"{bd}: no batch-done - the live monitors are a step of the close "
                        f"(batch-done, then runlog monitors, then runlog triage)")
    root = Path(root) if root else runlog.factory_root()
    specs = registry(root, agents=agents) if specs is None else specs
    t0 = time.monotonic()
    files, outputs = [], []
    for spec in specs:
        left = total_ceiling - (time.monotonic() - t0)
        if left <= 0:
            files.append({"repo": spec["repo"], "file": spec["file"], "env": spec.get("env"),
                          "monitors": list(spec.get("monitors") or []), "state": NOT_RUN,
                          "rc": None, "seconds": 0.0, "passed": None, "failed": [],
                          "error": f"the step's ceiling of {total_ceiling:g} s was spent "
                                   f"before this file"})
            continue
        v, text = run_file(spec, min(file_ceiling, left))
        files.append(v)
        if v["state"] != GREEN:
            outputs.append((v, text))
    bad = [f for f in files if f["state"] != GREEN]
    # `red` counts every file that is not green (not_checked among them: the
    # step's state and exit code stay red - not checked is not green);
    # `not_checked` says how many of those saw nothing rather than broke.
    result = {"task": TASK, "root": str(root), "state": RED if bad else GREEN,
              "files": files, "green": len(files) - len(bad), "red": len(bad),
              "not_checked": len(unchecked_files({"files": files})),
              "seconds": round(time.monotonic() - t0, 1),
              "file_ceiling_s": file_ceiling, "total_ceiling_s": total_ceiling,
              "envs": sorted({f["env"] for f in files if f.get("env")})}
    if write:
        runlog.emit(bd, EVENT_KIND, None, status=result["state"], **{EVENT_KEY: result})
        try:
            (bd / REPORT_FILE).write_text(report(result, outputs), encoding="utf-8")
        except OSError as e:
            runlog._warn(f"{REPORT_FILE} not written ({e})")
        try:
            runlog.sibling("summary").write(bd)
        except Exception as e:                      # noqa: BLE001 - the verdict is in the event
            runlog._warn(f"RUN_SUMMARY.md not re-written ({e.__class__.__name__}: {e})")
    return result


def report(result, outputs=()):
    """MONITORS.txt: the verdict of every file, then the output of each one
    that was not green (its last REPORT_TAIL_LINES lines)."""
    nc = len(unchecked_files(result))
    L = [f"# live monitors ({TASK}) - {result['state']}: {result['green']} green, "
         f"{result['red']} not" + (f" ({nc} of them not checked)" if nc else "")
         + f", {result['seconds']:g} s", ""]
    for f in result["files"]:
        L.append(f"{f['state']:8} {f['repo']}:{f['file']} ({f.get('env') or '-'}=1) "
                 f"{f.get('passed') or ''} {f.get('seconds') or 0:g} s"
                 + (f" - {f['error']}" if f.get("error") else ""))
    for v, text in outputs:
        lines = (text or "").splitlines()
        L += ["", f"## {v['repo']}:{v['file']} - {v['state']}", ""]
        L += lines[-REPORT_TAIL_LINES:] or ["(no output)"]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# readers: the summary and the triage
# --------------------------------------------------------------------------

def of(events):
    """The `monitors` payload of the last monitors event of a batch, or None."""
    hit = None
    for e in events or []:
        if isinstance(e, dict) and e.get("kind") == EVENT_KIND and isinstance(
                e.get(EVENT_KEY), dict):
            hit = dict(e[EVENT_KEY], ts=e.get("ts"))
    return hit


def red_files(m):
    """Every file that is not green - `not_checked` included (CF-0622: not
    checked is never green)."""
    return [f for f in (m or {}).get("files") or [] if f.get("state") != GREEN]


def unchecked_files(m):
    """The files whose monitors had nothing to check (CF-0622) - a part of
    `red_files`, told apart in the headline and the triage."""
    return [f for f in (m or {}).get("files") or [] if f.get("state") == NOT_CHECKED]


def broken_files(m):
    """`red_files` without the not-checked ones: red, timed out, missing, not run."""
    return [f for f in red_files(m) if f.get("state") != NOT_CHECKED]


def _what(f):
    bits = [f"{f['repo']}:{f['file']}", f["state"]]
    if f.get("state") == NOT_CHECKED:
        mons = [x.get("monitor") or x.get("test") for x in f.get("not_checked") or []]
        if mons:
            bits.append(", ".join(dict.fromkeys(mons)))
        elif f.get("error"):
            bits.append(f["error"][:120])
    elif f.get("failed"):
        bits.append("FAIL " + ", ".join(f["failed"][:3]))
    elif f.get("error"):
        bits.append(f["error"][:120])
    return " ".join(bits[:2]) + (f" ({bits[2]})" if len(bits) > 2 else "")


def headline(m):
    """The line near the top of RUN_SUMMARY.md - never silent: a batch whose
    monitors did not run says so (that silence is the defect CF-0511 closed)."""
    if m is None:
        return (f"live monitors: not run yet - the close of a batch is `batch-done`, then "
                f"`runlog monitors`, then `runlog triage` ({TASK})")
    n = len(m.get("files") or [])
    if not red_files(m):
        return (f"live monitors: {n}/{n} files green ({', '.join(m.get('envs') or []) or '-'}"
                f", {m.get('seconds') or 0:g} s) - {TASK}")
    bad, nc = broken_files(m), unchecked_files(m)
    parts = []
    if bad:
        parts.append(f"**live monitors: {len(bad)} of {n} files not green** - "
                     + "; ".join(_what(f) for f in bad)
                     + f" - output in {REPORT_FILE}; by the rule of CF-0319 each is an "
                       f"авария and `runlog triage` files it ({TASK})")
    if nc:
        lead = (f"**live monitors: {len(nc)} of {n} files not checked**" if not bad else
                f"**{len(nc)} files not checked**")
        parts.append(f"{lead} - " + "; ".join(_what(f) for f in nc)
                     + f" - a monitor found nothing to check: not green, a находка, and "
                       f"`runlog triage` files a task on the monitor (CF-0622)")
    return "; ".join(parts)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog monitors",
                                 description="the live monitors, a step of closing a batch "
                                             "(CF-0511)")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--root", default=None, help="factory root (default: this checkout)")
    ap.add_argument("--root-only", action="store_true",
                    help="the root's registry only, not the agents'")
    ap.add_argument("--file-ceiling", type=float, default=FILE_CEILING_S,
                    help=f"seconds per test file (default {FILE_CEILING_S})")
    ap.add_argument("--ceiling", type=float, default=TOTAL_CEILING_S,
                    help=f"seconds for the whole step (default {TOTAL_CEILING_S})")
    ap.add_argument("--dry-run", action="store_true",
                    help="run and print; write no event, no MONITORS.txt, no summary")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    bd = runlog.find_batch_dir(ns.batch)
    if bd is None:
        sys.stderr.write("runlog monitors: error: no batch directory (use --batch DIR)\n")
        return 2
    try:
        res = run(bd, root=ns.root, agents=not ns.root_only, file_ceiling=ns.file_ceiling,
                  total_ceiling=ns.ceiling, write=not ns.dry_run)
    except NotClosed as e:
        sys.stderr.write(f"runlog monitors: error: {e}\n")
        return 2
    if ns.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    else:
        sys.stdout.write(report(res))
        print(headline(res))
    return 1 if res["state"] != GREEN else 0


if __name__ == "__main__":
    sys.exit(main())

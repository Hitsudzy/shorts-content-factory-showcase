#!/usr/bin/env python3
"""CF-0508: nothing in trend-hunter waits on a subprocess without a ceiling.

The rule is the factory's (CF-0077 -> CF-0128 -> CF-0132 -> CF-0135, shared by
CF-0229): every child started carries a deadline, and a function that starts a
child does not drain its pipe on the thread that owns that deadline. Until
CF-0508 this repository was held by attention - three waiting calls
(`pool_coverage.py`, `footage_supplement.py`, `fact_probe_topics.py` through
`runlog.run_child`), all capped, and no guard to stop the next one.

The how-to-scan is the root's `shared/timeout_guard.py`, loaded by path through
`_runlog.factory_root()` (CF-0159: a copied rule drifts). What is this
repository's own: the directory scanned (`scripts/`), the pass-through exempted
by name (`_runlog.py::run_child`, the stand-in of the root's accounting wrapper
that hands the caller's `timeout=` straight down), and POPEN_SITES - empty:
trend-hunter starts no Popen. tests/ is not scanned: a test's child is bounded
by tests/run_tests.py's per-file ceiling (CF-0077).
"""
import ast
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
import _runlog  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "timeout_guard", _runlog.factory_root() / "shared" / "timeout_guard.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

SCANNED = ("scripts",)

# Sites whose subprocess.run takes the caller's kwargs through `**kw` - the
# ceiling is the caller's, so an AST scan of the call cannot see it. Named by
# (file, function), with the reason; a new pass-through fails the scan until it
# is either rewritten to name its timeout= or described here.
PASSTHROUGH = {
    ("scripts/_runlog.py", "run_child"): (
        "the stand-in of the root's runlog.run_child when the factory root is not "
        "found: subprocess.run(cmd, **popen_kw) hands the caller's timeout= straight "
        "down - every caller names it (test_every_run_child_call_names_its_ceiling)."),
}

# trend-hunter starts no subprocess.Popen. A new one fails the scan until it is
# described here with the deadline over the whole operation, its pipe included.
POPEN_SITES = {}


def _check(cond, msg, fix=None):
    if not cond:
        raise AssertionError(msg + (f"\n  {fix}" if fix else ""))
    print(f"ok: {msg}")


def _files():
    out = []
    for d in SCANNED:
        out += tg.python_files(REPO / d)
    return out


def _rel(p):
    return p.relative_to(REPO).as_posix()


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------

def test_the_scan_has_the_agent_code_to_scan():
    """A moved directory or a glob that matches nothing must fail here rather
    than turn every check below into a pass over an empty list."""
    files = [_rel(p) for p in _files()]
    for must in ("scripts/_runlog.py", "scripts/pool_coverage.py",
                 "scripts/footage_supplement.py", "scripts/fact_probe_topics.py"):
        _check(must in files, f"{must} is in the scan")
    _check(len(files) > 20, f"the scan covers the agent's code ({len(files)} files)")


# --------------------------------------------------------------------------
# 1. every waiting call names its ceiling
# --------------------------------------------------------------------------

def test_no_agent_code_waits_on_a_child_without_a_ceiling():
    checked, used = 0, set()
    for path in _files():
        tree = tg.parse(path)
        owner = tg.owners(tree)
        for call in tg.subprocess_calls(tree, tg.WAITING_STARTERS):
            checked += 1
            if tg.has_ceiling(call):
                continue
            key = (_rel(path), owner.get(id(call)))
            if key in PASSTHROUGH:
                used.add(key)
                continue
            _check(False, f"{_rel(path)}:{call.lineno} hands subprocess.{call.func.attr} a ceiling",
                   fix="Pass timeout= with the constant its class of call is documented "
                       "against (and turn TimeoutExpired into a verdict), or - for a "
                       "**kw pass-through - name the site in PASSTHROUGH with why.")
    _check(checked >= 3, f"the scan found waiting calls to check ({checked})")
    for key in PASSTHROUGH:
        _check(key in used, f"PASSTHROUGH describes {key[0]}::{key[1]}, which still passes through",
               fix="Drop the entry rather than leave the guard describing code that is gone.")


def test_every_run_child_call_names_its_ceiling():
    """`runlog.run_child` is a waiting call the subprocess scan does not see
    (it is not `subprocess.<x>`); its deadline is the caller's `timeout=`."""
    calls = []
    for path in _files():
        for n in ast.walk(tg.parse(path)):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr == "run_child":
                calls.append((path, n))
    for path, call in calls:
        _check(tg.has_ceiling(call), f"{_rel(path)}:{call.lineno} run_child() names its timeout=")
    _check(len(calls) >= 1, f"the scan found the run_child calls ({len(calls)})")


# --------------------------------------------------------------------------
# 2. the Popen registry, and the pipe rule
# --------------------------------------------------------------------------

def test_no_agent_code_starts_a_popen_this_guard_has_not_seen():
    found = {}
    for path in _files():
        for call in tg.popen_calls(tg.parse(path)):
            found.setdefault(_rel(path), []).append(call.lineno)
    unregistered, stale = tg.popen_registry_drift(found, POPEN_SITES)
    for name in unregistered:
        _check(False, f"{name}:{found[name][0]} starts a subprocess.Popen this guard has seen",
               fix="A Popen carries no timeout= to check, so name the site in POPEN_SITES "
                   "with the deadline that covers the whole operation - the reading of "
                   "its pipe included - or use subprocess.run(timeout=).")
    for name in stale:
        _check(False, f"POPEN_SITES describes {name}, which still starts one",
               fix="Drop the entry rather than leave the guard describing code that is gone.")
    _check(len(found) == len(POPEN_SITES), f"every Popen site is registered ({len(found)})")


def test_no_agent_code_reads_a_child_pipe_on_the_thread_that_owns_its_deadline():
    for path in _files():
        for fn, read in tg.popen_functions(tg.parse(path)):
            _check(read is None,
                   f"{_rel(path)}:{fn.lineno} {fn.name}() starts a child and leaves the "
                   "reading of its pipe to somewhere that can be bounded"
                   + (f" - line {read.lineno} does not" if read is not None else ""))
    print("ok: the pipe rule holds over the scan")


# --------------------------------------------------------------------------
# 3. the guard catches what it is for (negative controls)
# --------------------------------------------------------------------------

def test_the_shared_scan_catches_a_wait_without_a_ceiling():
    bad = ast.parse("import subprocess\n"
                    "def f():\n    subprocess.run(['sleep', '9'])\n"
                    "def g(**kw):\n    subprocess.check_output(['x'], **kw)\n"
                    "def h():\n    subprocess.run(['true'], timeout=5)\n")
    hits = tg.waits_without_ceiling(bad)
    _check([c.lineno for c in hits] == [3, 5],
           "a bare subprocess.run and a **kw pass-through are both caught; a capped one is not")
    owner = tg.owners(bad)
    _check([owner[id(c)] for c in hits] == ["f", "g"], "and each is attributed to its function")


def test_the_shared_scan_catches_a_popen_and_a_read_on_the_owning_thread():
    bad = ast.parse("import subprocess, threading\n"
                    "def bad():\n    p = subprocess.Popen(['x'], stdout=subprocess.PIPE)\n"
                    "    for line in p.stdout:\n        pass\n    p.wait(timeout=5)\n")
    _check([c.lineno for c in tg.popen_calls(bad)] == [3], "a Popen is found")
    got = {fn.name: (read.lineno if read is not None else None)
           for fn, read in tg.popen_functions(bad)}
    _check(got == {"bad": 4}, "the CF-0135 shape is caught")
    unregistered, stale = tg.popen_registry_drift({"scripts/new.py": [3]}, POPEN_SITES)
    _check(unregistered == ["scripts/new.py"] and stale == [],
           "a Popen in this repository with the registry empty is reported")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
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

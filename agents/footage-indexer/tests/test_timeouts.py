#!/usr/bin/env python3
"""CF-0506: nothing in the Footage Indexer waits on a subprocess without a
ceiling - or, where it still does, the guard names the site and why.

The rule is agents/video-editor's (CF-0077 -> CF-0128 -> CF-0132 -> CF-0135)
and the root's (CF-0229): every child started carries a deadline, and a
function that starts a child does not drain its pipe on the thread that owns
that deadline. The how-to-scan is not copied here: it lives once, in
`<root>/shared/timeout_guard.py`, loaded by path (CF-0159: a copied rule
drifts). The root is found by `_fi_paths.root_candidates()` (CF-0267) - not by
`_runlog`, whose name every agent repo shares.

What lives here is this repository's half: the directory scanned (`scripts/`;
`tests/` is not - a test's child is bounded by tests/run_tests.py's per-file
ceiling), the `**kw` pass-through exempted by name, POPEN_SITES - one line of
review per Popen saying what bounds it - and UNCAPPED, any known wait that
has no ceiling yet and why it has not been given one (none today).

`runlog.run_child(...)` calls are not `subprocess.*` calls and are not scanned
here: one without `timeout=` runs under the CF-0316 silence watchdog, and the
wrapper itself is the root guard's (tests/test_timeouts.py, PASSTHROUGH).
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE.parent
SCRIPTS = AGENT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _fi_paths  # noqa: E402

# The first candidate root that holds the shared half: a FACTORY_ROOT that is a
# test's temp root (channels/ only) does not end the search - the walk is
# still asked, as _fi_paths.sibling_scripts() does.
GUARD_REL = Path("shared") / "timeout_guard.py"
ROOT = next((r for r in _fi_paths.root_candidates() if (r / GUARD_REL).is_file()), None)
if ROOT is None:
    raise _fi_paths.FactoryRootError(
        f"{GUARD_REL} not found under {_fi_paths.root_candidates()}; "
        "set FACTORY_ROOT=<factory root> (CF-0267)")
_spec = importlib.util.spec_from_file_location(
    "timeout_guard", ROOT / GUARD_REL)
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

# Sites whose subprocess.run takes the caller's kwargs through `**kw` - the
# ceiling is the caller's, so an AST scan of the call cannot see it. Named by
# (file, function), with the reason.
PASSTHROUGH = {
    ("scripts/_runlog.py", "run_child"): (
        "_Silent.run_child, the stand-in when the factory root is not found: "
        "subprocess.run(cmd, **popen_kw) hands the caller's timeout= straight "
        "down, as shared/runlog/runlog.py's run_child does (CF-0128, CF-0316)."),
}

# Known waits with no ceiling that are deliberately not capped yet - each with
# the task that owns it and why. Not a pass: the entry must name a site that
# still has no ceiling, and drops out the day it gets one.
UNCAPPED = {
    # Empty since CF-0506 p.1 capped usability_probe.py::extract_full_frames
    # (PROBE_FRAME_TIMEOUT_SECONDS, tests/test_full_frame_ceiling.py).
}

POPEN_SITES = {
    "scripts/ingest_batch.py": (
        "list_descendants(): one `ps -A -o pid=,ppid=`, stdout to a pipe read "
        "by communicate(timeout=10) - the deadline covers the read; any "
        "failure, the ceiling included, returns []."),
    "scripts/sieve_answer_claude.py": (
        "run_claude(): claude -p in its own session, stdout/stderr into a log "
        "file (no pipe to drain), wait(timeout=) is the deadline and "
        "kill_group() takes the whole group down past it."),
}


def _check(cond, msg, fix=None):
    if not cond:
        raise AssertionError(msg + (f"\n  {fix}" if fix else ""))
    print(f"ok: {msg}")


def _files():
    return tg.python_files(SCRIPTS)


def _rel(p):
    return p.relative_to(AGENT).as_posix()


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------

def test_the_scan_has_the_indexer_code_to_scan():
    """A moved directory or a root not found must fail here rather than turn
    every check below into a pass over an empty list."""
    _check((ROOT / GUARD_REL).is_file(),
           f"the shared guard is found from the factory root ({ROOT})")
    files = [_rel(p) for p in _files()]
    for must in ("scripts/usability_probe.py", "scripts/ingest_batch.py",
                 "scripts/sieve_answer_claude.py", "scripts/_runlog.py",
                 "scripts/sharpness.py"):
        _check(must in files, f"{must} is in the scan")
    _check(len(files) > 25, f"the scan covers the indexer's scripts ({len(files)} files)")


# --------------------------------------------------------------------------
# 1. every waiting call names its ceiling
# --------------------------------------------------------------------------

def test_no_indexer_code_waits_on_a_child_without_a_ceiling():
    checked, used = 0, set()
    for path in _files():
        tree = tg.parse(path)
        owner = tg.owners(tree)
        for call in tg.subprocess_calls(tree, tg.WAITING_STARTERS):
            checked += 1
            if tg.has_ceiling(call):
                continue
            key = (_rel(path), owner.get(id(call)))
            if key in PASSTHROUGH or key in UNCAPPED:
                used.add(key)
                continue
            _check(False, f"{_rel(path)}:{call.lineno} hands subprocess.{call.func.attr} a ceiling",
                   fix="Pass timeout= with the constant its class of call is documented "
                       "against (and turn TimeoutExpired into a verdict), or - for a "
                       "**kw pass-through - name the site in PASSTHROUGH with why.")
    _check(checked >= 8, f"the scan found waiting calls to check ({checked})")
    for key in list(PASSTHROUGH) + list(UNCAPPED):
        _check(key in used, f"{key[0]}::{key[1]} is still the uncapped site the guard describes",
               fix="Drop the entry rather than leave the guard describing code that is gone.")


# --------------------------------------------------------------------------
# 2. the Popen registry, and the pipe rule
# --------------------------------------------------------------------------

def test_no_indexer_code_starts_a_popen_this_guard_has_not_seen():
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
    _check(len(found) == len(POPEN_SITES) >= 2,
           f"every Popen site in the indexer is registered ({len(found)})")


def test_no_indexer_code_reads_a_child_pipe_on_the_thread_that_owns_its_deadline():
    checked = 0
    for path in _files():
        for fn, read in tg.popen_functions(tg.parse(path)):
            checked += 1
            _check(read is None,
                   f"{_rel(path)}:{fn.lineno} {fn.name}() starts a child and leaves the "
                   "reading of its pipe to somewhere that can be bounded"
                   + (f" - line {read.lineno} does not" if read is not None else ""))
    _check(checked >= 2, f"the rule was applied to every function that starts a child ({checked})")


# --------------------------------------------------------------------------
# 3. the guard catches what it is for: the negative controls of the shared scan
#    live with the scan, in the root's tests/test_timeouts.py
#    (test_the_shared_scan_catches_*). The copies that stood here ran the same
#    shared/timeout_guard.py on the same snippets (removed by CF-0531).
# --------------------------------------------------------------------------

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

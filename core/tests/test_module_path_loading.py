#!/usr/bin/env python3
"""CF-0231: a root module a neighbouring repository loads must load *by path*.

The bug this guards against, in full. `rotation/shortage.py` said `import
pool` - a bare name, which resolves only while something has already put
`rotation/` on `sys.path`. Two things do that and both are accidents of how
the file happened to be reached:

  * `python3 rotation/rotate.py ...` - the interpreter puts a *script's* own
    directory on sys.path, so the whole CLI path works;
  * this suite - every root test file that touches the rotation opens with
    `sys.path.insert(0, str(ROOT / "rotation"))`, so the checks work too.

Neither is a property of the module. `agents/video-editor/tests/
test_deficit_anchors.py` reaches the same file the third way - by path, with
`importlib.util.spec_from_file_location`, because it runs the rotation's real
reader over the deficit file the Editor writes rather than a copy of it - and
got `ModuleNotFoundError: No module named 'pool'`. Four red checks in a
repository nobody had touched, and the root suite stayed 455/456 the whole
time, because the root suite is one of the two accidents.

So the rule this file pins is a rule about *form*, not about `pool`:

  1. every module in a guarded directory loads through
     `spec_from_file_location` from a process that has nothing of this
     checkout on `sys.path`;
  2. a module that names a neighbour anywhere - at import time or inside a
     function, like `shortage.log_path()`'s `from ledger import
     DEFAULT_LEDGER_DIR` - has put its own directory on `sys.path` by the
     time it finishes importing. That is what makes the deferred import
     resolve too, and it is checked by looking at the loaded process's
     `sys.path`, not by reading the source for a line that looks right.

Both run in a child process per module, deliberately: modules loaded into one
process mask each other, and the first one to register the directory would
make every later bare import look fine - which is the exact shape of the bug.

The mechanism the modules use is not this file's invention and must not
become a second one (`CF-0159`): `rotation/rotate.py` already registered
`ROOT / "patterns"` that way, `rotation/pool.py::_inserts_lib()` registers
`shared/inserts` that way, and all nine modules of `shared/runlog/` register
their own directory that way. Compute the directory from `__file__`, register
it when it is not there, then import by name.

What this guard cannot see: a directory nobody has listed below. The loaders
live in the other repositories, so nothing here can discover that a neighbour
has started loading, say, `channels/`. Adding a directory to GUARDED is part
of the work of teaching another repo to load it.
"""
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The registry, CF-0135's shape: one line of review per directory, saying who
# outside this checkout loads it.
GUARDED = {
    "rotation": (
        "agents/video-editor/tests/test_deficit_anchors.py loads shortage.py by "
        "path - the rotation's real reader over the Editor's deficit file, "
        "because a copy of the reader is how two sides end up green and "
        "agreeing about nothing (CF-0139)."),
    "shared/inserts": (
        "the insert library's schema module: agents/video-editor's "
        "meme_layer._lib() and underlay_layer._module() both reach in here "
        "(CF-0114)."),
    "shared": (
        "channel_ids.py: the names a channel has had (CF-0197). Every agent "
        "repository that resolves a channel out of a batch file loads it here "
        "through its scripts/_channel_ids.py shim, because the mapping is one "
        "fact and a second copy of it would be CF-0159. timeout_guard.py: the "
        "shared half of the no-subprocess-without-a-ceiling guard (CF-0229), "
        "which agents/video-editor's test_common_timeouts.py is to load by path."),
    "shared/runlog": (
        "the one run-accounting library for the whole factory - every agent's "
        "scripts/_runlog.py shim loads it from here (CF-0107)."),
    "shared/factrule": (
        "fact_rule.py: the production-fact refusal, one predicate for the "
        "stage that probes cheaply and the stage that refuses expensively "
        "(CF-0323). agents/trend-hunter's scripts/_factrule.py loads it from "
        "here by path, and agents/content-researcher's fact_refusal.py is to "
        "follow - a second predicate is what the task exists to end."),
    "patterns": (
        "validate_patterns.py: the pattern vocabulary, read by rotate.py and "
        "by inserts/validate_inserts.py."),
    "inserts": (
        "validate_inserts.py: the insert-library validator."),
}

# A child that loads one file the way a foreign repository does, and reports
# whether the module left its own directory on sys.path.
PROBE = r"""
import importlib.util, sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
checkout = str(Path(sys.argv[2]).resolve())

# Nothing of the checkout may be on the path - not the cwd, not an inherited
# PYTHONPATH entry, not a .pth. This is the whole point of the probe.
sys.path[:] = [p for p in sys.path
               if p and not str(Path(p).resolve()).startswith(checkout)]

spec = importlib.util.spec_from_file_location("cf0231_probe", target)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print("REGISTERED" if str(target.parent) in sys.path else "NOT-REGISTERED")
"""


def _modules(directory):
    """The files the rule applies to. `__init__.py` is excluded: it is a
    package marker whose `from . import runlog` is *correct* and cannot work
    under a flat module name - a neighbour loads `runlog.py`, never it."""
    return [p for p in sorted((ROOT / directory).glob("*.py"))
            if p.name != "__init__.py"]


def neighbours_named(path):
    """The sibling modules this file imports by bare name, wherever in the
    file it does it - a deferred import inside a function counts, because it
    is exactly as dependent on sys.path as one at the top."""
    stems = {p.stem for p in path.parent.glob("*.py")} - {path.stem}
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return sorted(found & stems)


def load_by_path(path, checkout=ROOT):
    """(ok, registered, detail) for loading `path` the way a foreign
    repository does. `registered` is meaningless when ok is False."""
    with tempfile.TemporaryDirectory(prefix="cf0231-") as cwd:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run([sys.executable, "-c", PROBE, str(path), str(checkout)],
                              capture_output=True, text=True, cwd=cwd, env=env,
                              timeout=120)
    if proc.returncode != 0:
        tail = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
        return False, False, (tail[-1] if tail else "no output")
    return True, proc.stdout.strip().endswith("REGISTERED"), proc.stdout.strip()


# --------------------------------------------------------------------------
# 1. the rule
# --------------------------------------------------------------------------

def test_every_guarded_module_loads_with_nothing_of_this_checkout_on_sys_path():
    broken = []
    for directory in sorted(GUARDED):
        for path in _modules(directory):
            ok, _, detail = load_by_path(path)
            if not ok:
                broken.append(f"{directory}/{path.name}: {detail}")
    assert not broken, (
        "these modules load only because something upstream arranged sys.path "
        "for them, which a repository loading them by path does not do:\n  "
        + "\n  ".join(broken)
        + "\n\nFix: compute the directory from __file__ and register it before "
          "the name is used, as rotation/rotate.py and every module of "
          "shared/runlog/ already do. Do not write a second mechanism (CF-0159).")


def test_a_module_that_names_a_neighbour_has_registered_its_own_directory():
    """The half a module-level load cannot prove. `shortage.log_path()` calls
    `from ledger import DEFAULT_LEDGER_DIR` when it runs, long after the
    import succeeded; the only thing that makes it resolve is the directory
    being on sys.path, so that is what is checked."""
    broken = []
    for directory in sorted(GUARDED):
        for path in _modules(directory):
            named = neighbours_named(path)
            if not named:
                continue
            ok, registered, detail = load_by_path(path)
            if ok and not registered:
                broken.append(f"{directory}/{path.name} names {named} and left "
                              f"its directory off sys.path ({detail})")
    assert not broken, (
        "a bare `import <neighbour>` that happens to run later would raise:\n  "
        + "\n  ".join(broken))


# --------------------------------------------------------------------------
# 2. the guard is a guard
# --------------------------------------------------------------------------

def test_the_scan_has_something_to_scan():
    """A rename, a moved directory or an emptied glob must fail here rather
    than turn the two checks above into a pair of empty loops."""
    for directory in sorted(GUARDED):
        assert (ROOT / directory).is_dir(), (
            f"GUARDED names {directory}, which is not a directory - drop the "
            f"entry or fix the path, do not leave the guard describing "
            f"something that is gone")
        assert _modules(directory), f"no module to check in {directory}"
    named = [f"{d}/{p.name}" for d in GUARDED for p in _modules(d)
             if neighbours_named(p)]
    assert named, ("no guarded module names a neighbour at all - the second "
                   "check would pass vacuously, so the scan is broken rather "
                   "than the tree being clean")
    assert any(n.startswith("rotation/") for n in named), (
        "rotation/ is the directory CF-0231 was reported against and no module "
        "in it names a neighbour any more - if that is real, say so here")


def test_the_probe_fails_the_form_it_is_meant_to_catch():
    """The negative control: the exact code that was in shortage.py, in a
    scratch directory. If this passes the probe, the probe proves nothing -
    which is how the bug reached a neighbour's suite in the first place."""
    with tempfile.TemporaryDirectory(prefix="cf0231-control-") as tmp:
        scratch = Path(tmp)
        (scratch / "neighbour.py").write_text("VALUE = 1\n", encoding="utf-8")

        bare = scratch / "bare.py"
        bare.write_text("import neighbour\nUSES = neighbour.VALUE\n", encoding="utf-8")
        ok, _, detail = load_by_path(bare, checkout=scratch)
        assert not ok, ("a bare sibling import loaded by path - the probe is not "
                        "isolating sys.path and every check above is a no-op")
        assert "neighbour" in detail, detail

        fixed = scratch / "fixed.py"
        fixed.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "_HERE = str(Path(__file__).resolve().parent)\n"
            "if _HERE not in sys.path:\n"
            "    sys.path.insert(0, _HERE)\n"
            "import neighbour\n"
            "USES = neighbour.VALUE\n", encoding="utf-8")
        ok, registered, detail = load_by_path(fixed, checkout=scratch)
        assert ok, f"the fixed form does not load: {detail}"
        assert registered, f"the fixed form did not register its directory: {detail}"


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

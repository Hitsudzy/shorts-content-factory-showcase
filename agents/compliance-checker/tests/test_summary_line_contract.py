#!/usr/bin/env python3
"""CF-0510 (compliance-checker part; the root's CF-0234): the one line every test
file of this agent owes tests/run_tests.py.

The runner counts a file only through the summary line it prints
(`SUMMARY_RE`). In agents/video-editor (CF-0192) a new file printed
`TOTAL 9/9 passed` - the runner's whole-suite form - and its nine checks fell
out of the denominator while the suite looked exactly as green as the day
before. The quiet variant is worse: a summary the runner parses happily whose
number is not the number of checks the file holds (`3/9 passed` hard-wired,
or checks listed by hand so the tenth is never run).

The how-to-check lives in shared/summary_line_guard.py, one copy for every
repository (CF-0159: a copied rule drifts), loaded by path through
`_runlog.factory_root()`. What lives here is this agent's own half: its runner (whose `SUMMARY_RE` is loaded by path, so this guard cannot
drift from it), the floor on how many files it expects, and the runner
self-tests exempt from the discovery half.

"""
import ast
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_tests.py"
sys.path.insert(0, str(HERE.parent / "scripts"))
import _runlog  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "summary_line_guard", _runlog.factory_root() / "shared" / "summary_line_guard.py")
slg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slg)

SUMMARY_RE = slg.load_summary_re(RUNNER)

# The runner's own tests (CF-0077 ceiling, CF-0489 temp trees, CF-0504 killpg
# EPERM): they define no module-level `test_*` functions - they drive fixture
# files through the runner and count scenarios in a list. The discovery half
# has nothing to say about them; the summary-line half still holds them.
NO_TEST_FUNCTIONS_IS_FINE = {"test_run_tests_timeout.py", "test_run_tests_temp_trees.py",
                             "test_run_tests_killpg_eperm.py"}

# 18 files on 2026-10-07. Well under that, so a new file never trips it, and
# well over zero, so a glob pointed at the wrong directory does.
MIN_FILES = 12


def all_test_files():
    files = sorted(HERE.glob("test_*.py"))
    assert len(files) > MIN_FILES, f"only {len(files)} test files found in {HERE}"
    return files


def test_every_test_file_prints_a_summary_the_runner_can_parse():
    offenders = []
    files = all_test_files()
    for path in files:
        near = slg.unparseable_summary(path.read_text(), SUMMARY_RE)
        if near is not None:
            offenders.append(f"{path.name}: {near or 'nothing about passing'}")
    assert not offenders, (
        "these files print no line matching the runner's SUMMARY_RE, so "
        "tests/run_tests.py counts zero of their checks:\n  " + "\n  ".join(offenders))
    print(f"  {len(files)} files, every one with a parseable summary")


def test_the_total_in_that_line_is_counted_not_written_down():
    offenders = []
    for path in all_test_files():
        for finding in slg.lying_summary(
                path.read_text(), SUMMARY_RE,
                needs_test_functions=path.name not in NO_TEST_FUNCTIONS_IS_FINE):
            offenders.append(f"{path.name}: {finding}")
    assert not offenders, (
        "a summary can be parseable and still be a lie:\n  " + "\n  ".join(offenders))
    print("  every summary counts what the file actually holds")


def test_the_guard_bites_the_shapes_it_is_here_for():
    """Positive control: the two defects above, rejected, on this agent's own
    SUMMARY_RE."""
    assert slg.unparseable_summary('print(f"TOTAL {p}/{t} passed")', SUMMARY_RE) is not None, (
        "`TOTAL n/n passed` is the runner's whole-suite form - a test file "
        "printing it is unparseable, and this guard must say so")
    good = slg.printed_strings(ast.parse('print(f"\\n{p}/{t} passed")'))
    assert slg.summary_lines(good, SUMMARY_RE) == ["{}/{} passed"], good
    hard = slg.lying_summary('print(f"{p}/9 passed")', SUMMARY_RE, needs_test_functions=False)
    assert hard and "hard-wired total" in hard[0], hard
    by_hand = ("def test_a(): pass\ndef test_b(): pass\n"
               "for t in (test_a, test_b): t()\nprint(f'{n}/{m} passed')\n")
    assert any("by hand" in f for f in slg.lying_summary(by_hand, SUMMARY_RE)), \
        "a harness listing its checks by hand must be spotted"
    print("  bad form rejected, house form accepted, hard-wired total and hand list spotted")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception:                               # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

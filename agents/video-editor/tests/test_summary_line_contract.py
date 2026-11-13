#!/usr/bin/env python3
"""CF-0192 (приёмка): the one line every test file owes the runner.

`run_tests.py` counts a file only through the summary line it prints:
`SUMMARY_RE` - a count, a slash, a total, the word `passed`, and nothing
before them on that line. Everything else a file prints is free-form.

The defect that produced this guard: a new file printed `TOTAL 9/9 passed`
(the form the *runner* uses for the whole suite). The runner refused to parse
it and said so loudly - but only because the file matched *nothing*. The
quiet variant is worse: a file that prints a summary the runner parses
happily while the number in it is not the number of checks the file holds.
A harness that lists its checks by hand, or prints a hard-wired total, keeps
reporting `3/3 passed` for years after the fourth check was written; the
runner sees a green file and the suite's denominator never moves.

So two static checks over every `tests/test_*.py`, both read off the source,
neither of them running anything:

1. the file prints a summary line that the runner's own `SUMMARY_RE` - loaded
   from `run_tests.py` by path, so this guard cannot drift from it - matches;
2. the number in that line is *derived*, not written down: the total is an
   expression, and a file that defines `test_*` functions discovers them
   (`globals()` / `inspect.getmembers`) instead of listing them.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import ast
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import _runlog  # noqa: E402

# CF-0234: the rule itself - how printed strings are read off the AST, which
# of them the runner parses, the two ways a parseable summary lies - lives
# once, in the factory root's shared/summary_line_guard.py, and the root's own
# guard (tests/test_summary_line_contract.py) runs on the same copy. Loaded by
# path, the root found the way the run accounting finds it
# (_runlog.factory_root()), as test_common_timeouts.py loads timeout_guard.py.
# What stays here is this repository's own: its runner, the file floor and
# the files exempt from the discovery half.
_SLG_PATH = _runlog.factory_root() / "shared" / "summary_line_guard.py"
_spec = importlib.util.spec_from_file_location("summary_line_guard", _SLG_PATH)
slg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slg)

# The runner's own contract, read from the runner by path, so this guard
# cannot drift from it.
SUMMARY_RE = slg.load_summary_re(HERE / "run_tests.py")

# `test_run_tests_timeout.py` is the runner's own test (CF-0077): it defines
# no module-level `test_*` functions at all - it drives fixture files through
# the runner and counts scenarios. Check 2's discovery half has nothing to
# say about it; check 1 still holds it to the summary line.
NO_TEST_FUNCTIONS_IS_FINE = {"test_run_tests_timeout.py",
                             # CF-0504: the EPERM self-test, the same shape
                             "test_run_tests_killpg_eperm.py"}


def all_test_files():
    files = sorted(HERE.glob("test_*.py"))
    assert len(files) > 90, f"only {len(files)} test files found in {HERE}"
    return files


def test_every_test_file_prints_a_summary_the_runner_can_parse():
    offenders = []
    for path in all_test_files():
        near = slg.unparseable_summary(path.read_text(), SUMMARY_RE)
        if near is not None:
            offenders.append(f"{path.name}: {near or 'nothing about passing'}")
    assert not offenders, (
        "these files print no line matching the runner's SUMMARY_RE, so "
        "run_tests.py counts zero of their checks:\n  " + "\n  ".join(offenders))
    print(f"  {len(all_test_files())} files, every one with a parseable summary")


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
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")
             and callable(v)]
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

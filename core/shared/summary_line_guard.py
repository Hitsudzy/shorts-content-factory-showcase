#!/usr/bin/env python3
"""CF-0234: the shared half of the "summary line a test file owes its runner"
guard.

Every repository's `tests/run_tests.py` counts a file only through the
summary line it prints - `SUMMARY_RE`: a count, a slash, a total, the word
`passed`, nothing but blanks before them. The guard was built in
agents/video-editor (CF-0192, tests/test_summary_line_contract.py) after a
new file printed `TOTAL 9/9 passed` and nine checks fell out of the
denominator unseen. The root runs the same runner contract, and a second copy
of that file would be a second copy of the rule - the CF-0159 drift. So, as
with shared/timeout_guard.py (CF-0229), the rule is split:

  * here, the part that is the same in every repository: how the printed
    strings of a test file are read off its AST, which of them the runner
    would parse as a summary, and the two ways a parseable summary still lies
    (a hard-wired total; checks listed by hand instead of discovered);
  * in each repository's own test: where its runner is (its `SUMMARY_RE` is
    loaded from that runner by path, so the guard cannot drift from the
    runner it guards), the floor on how many files it expects, and the files
    exempt from the discovery half.

Everything here returns findings as data. Nothing is imported from beside
this file, so a neighbouring repository loads it by path
(`spec_from_file_location`), the way the root loads shared/timeout_guard.py.
"""
import ast
import importlib.util
import re
from pathlib import Path

# An f-string placeholder, as `printed_strings` renders it.
PLACEHOLDER = re.compile(r"\{[^{}]*\}")

# How a harness finds its own checks instead of listing them.
DISCOVERY = ("globals()", "getmembers")

_TOTAL = re.compile(r"/\s*(\S*)\s+passed")


def load_summary_re(runner_path):
    """The runner's own `SUMMARY_RE`, read from the runner. Importing
    run_tests.py the usual way could re-exec it under a venv, so load it as a
    module by path with its `__main__` guard inert."""
    spec = importlib.util.spec_from_file_location("_summary_contract_runner", Path(runner_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SUMMARY_RE


def printed_strings(tree):
    """Every string literal that reaches a `print(...)` call, with each
    f-string placeholder standing in as `{}`."""
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "print"):
            continue
        for arg in node.args:
            _collect(arg, out)
    return out


def _collect(node, out):
    """String literals under one expression. f-strings are taken whole - a
    walk into their pieces would hand back fragments that are not lines."""
    if isinstance(node, ast.JoinedStr):
        out.append("".join(v.value if isinstance(v, ast.Constant) else "{}"
                           for v in node.values))
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
        return
    for child in ast.iter_child_nodes(node):
        _collect(child, out)


def summary_lines(printed, summary_re):
    """The printed strings whose lines the runner would parse as a summary.
    A leading `\\n` is the house form and is not part of the line the runner
    sees, so split on newlines and test each line."""
    found = []
    for s in printed:
        for line in s.split("\n"):
            if summary_re.match(PLACEHOLDER.sub("0", line)):
                found.append(line)
    return found


def hard_wired_total(line):
    """True when the total in a summary line is written down, not computed."""
    m = _TOTAL.search(line)
    return bool(m) and "{}" not in m.group(1)


def unparseable_summary(source, summary_re):
    """None when the file prints a line the runner parses; otherwise the
    printed strings that mention `passed` (what the author probably meant)."""
    printed = printed_strings(ast.parse(source))
    if summary_lines(printed, summary_re):
        return None
    return [s for s in printed if "passed" in s]


def lying_summary(source, summary_re, needs_test_functions=True):
    """Ways a parseable summary still misreports the file, as a list of
    plain-language findings (empty when the file is honest)."""
    tree = ast.parse(source)
    findings = [f"hard-wired total in {line!r}"
                for line in summary_lines(printed_strings(tree), summary_re)
                if hard_wired_total(line)]
    if not needs_test_functions:
        return findings
    defined = [n.name for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    if not defined:
        findings.append("defines no module-level test_* function")
    elif not any(mark in source for mark in DISCOVERY):
        findings.append(
            f"{len(defined)} checks defined, but the harness lists them by "
            f"hand - none of {DISCOVERY} appears, so a check added later is "
            f"never run and never missed")
    return findings

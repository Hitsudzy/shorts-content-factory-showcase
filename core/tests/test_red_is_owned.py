#!/usr/bin/env python3
"""CF-0326: the roster of reds is held to the rule it exists to enforce.

DoD 1.4.1 item 2: the root suite carries **no unattributed failure** - every red
check is named by an open task that owns it. Two halves make that real, and this
file is the second one.

The first half reads the run: `tests/run_tests.py` and `tests/conftest.py` both
take the list of failures the run actually produced and print, per red, the task
that owns it or the word UNATTRIBUTED. Both read `tests/red_roster.py`, so the
rule exists once.

The second half is the roster's own hygiene, and it is what this file checks -
statically, running nothing. Every way an attribution can rot:

1. **the owner closes and the check stays red.** This is the CF-0326 defect
   itself, verbatim: `test_pattern_vocabulary.py` was red for three sprints with
   `CF-0194`/`CF-0195` named for it and both long closed, and the four
   `test_rotation_ledger.py` reds pointed at `CF-0145`, closed in 1.4.1. A red
   with a closed owner reads exactly like a red nobody has looked at. So a
   rostered owner that is done/closed turns this file red, and the message says
   which: either the red is stale and comes out of the roster, or it needs a live
   successor.
2. **the check is renamed or deleted and the entry stays.** Then the roster
   quietly excuses a name nothing answers to, and the real red under the new name
   reads as unattributed. So every rostered key must resolve to a file that
   exists and, for a `file::check` key, a `def <check>` in it.
3. **the entry claims the check names its owner and it does not.** `named_in =
   "check"` is a promise that whoever meets the red at 2am reads the task id in
   the assertion message. The promise is checked against the source.
4. **the owner does not exist at all** - a typo'd id, or a task file never filed.

What this file deliberately does NOT do: it does not require the roster to be
non-empty, and it does not fail because the suite is green. A green root suite
with an empty roster is the goal, not an error.
"""
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import red_roster  # noqa: E402


def _check_names(path):
    """`test_*` functions defined at module level in a file."""
    tree = ast.parse(path.read_text())
    return {n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")}


def _module_strings(tree, source):
    """Module-level `NAME = "..."` constants, by name.

    A failure message is often assembled from one of these - `NOT_THE_FIX` in
    test_pattern_vocabulary.py is the whole reason this exists - so a check that
    interpolates the constant does name the task in its message, even though the
    id is not in the function's own text.
    """
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out[target.id] = node.value.value
        else:
            out[target.id] = ast.get_source_segment(source, node.value) or ""
    return out


def _message_text(path, check):
    """Everything the check's failure message can be built out of: its own
    source, plus the module-level string constants it mentions by name."""
    source = path.read_text()
    tree = ast.parse(source)
    body = ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == check:
            body = ast.get_source_segment(source, node) or ""
            break
    if not body:
        return ""
    parts = [body]
    for name, value in _module_strings(tree, source).items():
        if name in body:
            parts.append(value)
    return "\n".join(parts)


def _split(roster_key):
    file_name, _, check = roster_key.partition("::")
    return file_name, (check or None)


def test_every_rostered_red_is_owned_by_a_task_that_is_still_open():
    """Rule 1 - the CF-0326 defect, in the one place it can be caught early."""
    offenders = []
    for roster_key, red in sorted(red_roster.ROSTER.items()):
        status = red_roster.task_status(red.task)
        if status is None:
            offenders.append(f"{roster_key}: names {red.task}, and tasks/{red.task}-*.md "
                             f"is not there (or there are several)")
        elif status in red_roster.CLOSED_STATES:
            offenders.append(
                f"{roster_key}: names {red.task}, whose status is {status!r}. A closed "
                f"owner is not an owner - this is exactly what CF-0326 found (CF-0145 "
                f"closed in 1.4.1, four checks still red). Either the red is stale and "
                f"this entry comes out, or it needs a live successor task")
        elif status not in red_roster.LIVE_STATES:
            offenders.append(f"{roster_key}: names {red.task} with an unknown status "
                             f"{status!r} - add it to red_roster.LIVE_STATES or "
                             f"CLOSED_STATES, do not leave it ambiguous")
    assert not offenders, (
        "a red whose owner cannot be worked on is an unattributed red (DoD 1.4.1 "
        "item 2):\n  " + "\n  ".join(offenders))
    print(f"  {len(red_roster.ROSTER)} rostered red(s), every owner still open")


def test_every_rostered_red_still_exists_under_that_name():
    """Rule 2 - a roster entry cannot outlive the check it excuses."""
    offenders = []
    for roster_key in sorted(red_roster.ROSTER):
        file_name, check = _split(roster_key)
        path = HERE / file_name
        if not path.is_file():
            offenders.append(f"{roster_key}: there is no tests/{file_name}")
            continue
        if check and check not in _check_names(path):
            offenders.append(
                f"{roster_key}: {file_name} defines no `{check}` - renamed or deleted. "
                f"An entry for a check that does not exist excuses nothing and hides "
                f"the same red under its new name")
    assert not offenders, (
        "the roster names checks that are not there:\n  " + "\n  ".join(offenders))
    for roster_key in red_roster.WORKTREE_ONLY:
        file_name, check = _split(roster_key)
        path = HERE / file_name
        assert path.is_file(), f"WORKTREE_ONLY names a missing file: {roster_key}"
        assert not check or check in _check_names(path), \
            f"WORKTREE_ONLY names a missing check: {roster_key}"
    print(f"  every rostered key resolves to a check that exists "
          f"({len(red_roster.ROSTER)} + {len(red_roster.WORKTREE_ONLY)} worktree-only)")


def test_a_red_that_claims_to_name_its_owner_actually_names_it():
    """Rule 3 - `named_in = "check"` is a promise about the failure message."""
    offenders = []
    promised = 0
    for roster_key, red in sorted(red_roster.ROSTER.items()):
        if red.named_in != red_roster.NAMED_IN_CHECK:
            continue
        promised += 1
        file_name, check = _split(roster_key)
        path = HERE / file_name
        if not path.is_file():
            continue                    # rule 2 owns this one
        haystack = _message_text(path, check) if check else path.read_text()
        if red.task not in haystack:
            offenders.append(
                f"{roster_key}: the roster says {red.task} is named in the check, and "
                f"{red.task} does not appear in it. The point of the rule is that the "
                f"person who meets the red reads the task id without going to the "
                f"roster - either put it in the message, or set named_in="
                f"{red_roster.NAMED_IN_RUN!r} and say why the message cannot carry it")
    assert not offenders, (
        "a promise about the failure message, unkept:\n  " + "\n  ".join(offenders))
    for roster_key, red in red_roster.ROSTER.items():
        if red.named_in == red_roster.NAMED_IN_RUN:
            assert red.why, f"{roster_key}: named_in={red.named_in!r} with no reason " \
                            f"given - the run report is then the only place the reader " \
                            f"learns anything, so it has to say something"
    print(f"  {promised} red(s) promise the task id in their own message, and carry it")


def test_the_report_names_an_owner_and_refuses_to_swallow_an_unowned_red():
    """Positive control: the shapes this whole mechanism exists for, exercised.

    Written against the roster's own data so it cannot pass by describing a
    world the module does not live in.
    """
    owned = next((k for k, r in red_roster.ROSTER.items()
                  if "::" in k and red_roster.is_live_owner(r.task)), None)
    saved = dict(red_roster.ROSTER)
    try:
        if owned is None:
            # CF-0488: an empty roster is the goal (DoD 1.5.2 item 1), not a
            # reason to skip the control - roster a red under any open task.
            live = next(m.group(0) for f in sorted(red_roster.TASKS.rglob("CF-*.md"))
                        for m in [re.match(r"CF-\d+", f.name)]
                        if m and red_roster.is_live_owner(m.group(0)))
            owned = "test_summary.py::test_owned_by_an_open_task"
            red_roster.ROSTER[owned] = red_roster.Red(
                live, red_roster.NAMED_IN_RUN, "a live owner, on purpose")
        file_name, check = _split(owned)
        text = red_roster.report([(file_name, check)])
        assert red_roster.ROSTER[owned].task in text, text
        assert "UNATTRIBUTED" not in text, text
    finally:
        red_roster.ROSTER.clear()
        red_roster.ROSTER.update(saved)

    # a red nobody rostered
    text = red_roster.report([("test_summary.py", "test_a_check_nobody_filed_a_task_for")])
    assert "UNATTRIBUTED" in text and "DoD 1.4.1 item 2" in text, text

    # a red whose owner is closed: the roster says CF-0145, which is done
    saved = dict(red_roster.ROSTER)
    try:
        red_roster.ROSTER["test_summary.py::test_owned_by_a_closed_task"] = red_roster.Red(
            "CF-0145", red_roster.NAMED_IN_RUN, "a closed owner, on purpose")
        text = red_roster.report([("test_summary.py", "test_owned_by_a_closed_task")])
        assert "UNATTRIBUTED" in text and "CF-0145" in text, text
        assert red_roster.task_status("CF-0145") in red_roster.CLOSED_STATES
    finally:
        red_roster.ROSTER.clear()
        red_roster.ROSTER.update(saved)

    # nothing failed -> nothing said
    assert red_roster.report([]) == ""
    print("  an owned red names its owner; an unowned and a closed-owner red are "
          "called UNATTRIBUTED")


def test_both_front_ends_read_the_roster_rather_than_a_copy_of_the_rule():
    """The rule lives once. CF-0159's class: two copies drift, and the drift is
    invisible because each of them passes its own tests."""
    runner = (HERE / "run_tests.py").read_text()
    conftest = (HERE / "conftest.py").read_text()
    for name, source in (("run_tests.py", runner), ("conftest.py", conftest)):
        assert "red_roster" in source, (
            f"{name} does not read tests/red_roster.py, so the root suite has a front "
            f"end that prints failures without saying who owns them (CF-0326)")
        assert "red_roster.report(" in source, (
            f"{name} imports the roster but does not call report() - the attribution "
            f"section is the only part of this a reader ever sees")
    print("  run_tests.py and conftest.py both attribute out of the one roster")


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

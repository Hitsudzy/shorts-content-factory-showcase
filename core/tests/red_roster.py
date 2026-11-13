#!/usr/bin/env python3
"""CF-0326: the one place a red check of the root suite is owned.

DoD 1.4.1 item 2 says the root suite has **no unattributed failure**: every red
check is named by an open task that owns it. On 2026-09-22 that rule was broken
and nobody noticed for three sprints - `test_pattern_vocabulary.py` was red with
`CF-0194`/`CF-0195` named in ROADMAP prose, and both had been closed; the four
`test_rotation_ledger.py` reds pointed at `CF-0145`, closed in 1.4.1. A red whose
owner is closed reads exactly like a red that nobody has looked at, which is why
the rule needs an instrument and not a habit.

This module is that instrument's data, and it is data on purpose: two front ends
read it, so the rule lives once.

  * `tests/run_tests.py` - the house runner. It sees `FAIL <check>` lines from
    each file's own harness and `FAILED <file>` for a file that died, and prints
    an ATTRIBUTION section naming the owner of each, or `UNATTRIBUTED`.
  * `tests/conftest.py` - `pytest`, which is what the auto-dev driver and the
    workers actually run. Same section, from `pytest`'s own failure list.

  * `tests/test_red_is_owned.py` - the guard over the roster itself: an owner
    that has been closed, a rostered check that no longer exists, an entry that
    claims the task is named in the check while it is not.

What belongs here and what does not
-----------------------------------
A roster entry is a **written-down expectation that this check is red today**,
with the open task that owns it. It is not permission to be red: the run is still
red, the runner still exits non-zero, nothing here makes a failure green. The only
thing an entry buys is that the next reader gets a name instead of a riddle.

`named_in` says where that name reaches the reader:

  "check" - the task id is inside the check's own source, so the assertion
            message carries it. The guard enforces this.
  "run"   - the check's own message cannot carry it, because the check is not
            what is wrong: a whole file that never gets to print anything at
            all (as `CF-0385`'s file did until it got the house harness).
            For those the front ends' ATTRIBUTION section is the only place
            the name can appear.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TASKS = ROOT / "tasks"

# A task in one of these states is not a live owner: it cannot be worked on, so
# a red it "owns" is unowned. `wontfix` is the user's decision to stop blocking
# (ROADMAP ## Versioning) and counts as a live owner precisely because it is a
# recorded decision rather than an oversight.
CLOSED_STATES = ("done", "closed", "duplicate")
LIVE_STATES = ("open", "in-progress", "in_progress", "needs-you", "blocked", "wontfix")

NAMED_IN_CHECK = "check"
NAMED_IN_RUN = "run"


class Red:
    """One rostered red: which task owns it, where its name reaches a reader."""

    __slots__ = ("task", "named_in", "why")

    def __init__(self, task, named_in, why):
        assert named_in in (NAMED_IN_CHECK, NAMED_IN_RUN), named_in
        self.task, self.named_in, self.why = task, named_in, why

    def __repr__(self):
        return f"Red({self.task}, {self.named_in})"


# --------------------------------------------------------------------------
# The roster. Keys are "<file>.py::<check>", or "<file>.py" for a whole file
# that never gets as far as naming a check.
# --------------------------------------------------------------------------
ROSTER = {
    # -- CF-0864: live monitor (ROOT_TESTS_LIVE / --live) red on 0840Z's
    #    vanguards-doomsday until that batch leaves the 6-batch fresh window.
    #    CF-0859 closed the class (video-editor 106ea5f: held_frame_band_gate
    #    charges score.hold_band_exceeded for a held frame past an emergent
    #    top), but a fixed Editor does not re-score a video already rendered,
    #    and RULINGS admits only the user's per-way rulings - not a per-video
    #    pardon. The video was rejected at acceptance 2026-10-25, never published.
    "test_pattern_vocabulary.py::test_baseline_envelope_covers_the_real_corpus":
        Red("CF-0864", NAMED_IN_CHECK,
            "example-film/2026-10-24T0840Z vanguards-doomsday (rendered by "
            "video-editor 0e9a536, before 106ea5f) held a 1.17 s shot 10.10 s "
            "past explainer's 8.0 s top with no price; the fixed Editor would "
            "charge hold_band_exceeded at plan stage. Rejected at acceptance "
            "2026-10-25, never published; stays red until 0840Z leaves the "
            "fresh window"),
}

# Reds that only ever appear in a bare git worktree, where `agents/` and
# `pipeline/` are not checked out and the git hooks are not installed. Since
# CF-0479 `scripts/agents sync --root <worktree>` checks the agents out and links
# the pool and the real batches, and the hook check reads the shared hooks, so a
# synced worktree has none of these. They are
# green in the real checkout, so they are not the root suite's reds - but a
# worker running the suite in a worktree should not have to re-derive that.
# Attributed, and said to be worktree-only rather than owned by a task.
WORKTREE_ONLY = {
    "test_repo_sync.py::test_installed_hooks_match_the_tracked_source":
        "a worktree has no installed hooks of its own",
    "test_rotation_pool_growth.py::test_the_scratch_pool_has_the_shape_of_the_real_one":
        "no footage pool on disk under a worktree",
}

_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.M)


def task_file(task_id):
    """The one task file for `CF-NNNN`, or None. Archived tasks (tasks/archive/<version>/) count."""
    found = sorted(TASKS.rglob(f"{task_id}-*.md"))
    return found[0] if len(found) == 1 else None


def task_status(task_id):
    """`status:` of the task, "" when the file has none, None when there is no file."""
    path = task_file(task_id)
    if path is None:
        return None
    m = _STATUS_RE.search(path.read_text())
    return (m.group(1) if m else "").strip()


def is_live_owner(task_id):
    st = task_status(task_id)
    return st is not None and st not in CLOSED_STATES


def owner(file_name, check=None):
    """The rostered owner of this red: the check's entry, else its file's."""
    if check:
        red = ROSTER.get(f"{file_name}::{check}")
        if red:
            return red
    return ROSTER.get(file_name)


def key(file_name, check=None):
    return f"{file_name}::{check}" if check else file_name


def attribution(failures):
    """The ATTRIBUTION section for a list of `(file_name, check_or_None)`.

    Returns `(lines, unattributed)`. Never raises and never hides: an owner that
    turns out to be closed is reported as unattributed, because that is what it
    is - it is the exact state CF-0326 was raised about.
    """
    lines, unattributed = [], []
    for file_name, check in failures:
        k = key(file_name, check)
        red = owner(file_name, check)
        if red is None:
            worktree = WORKTREE_ONLY.get(k)
            if worktree:
                lines.append(f"  {k}\n      worktree-only: {worktree} - green in the "
                             f"real checkout, no task owns it")
                continue
            unattributed.append(k)
            lines.append(f"  {k}\n      UNATTRIBUTED - no open task owns this red. "
                         f"DoD 1.4.1 item 2 forbids that: file the task, name it in "
                         f"the check's message, and add it to tests/red_roster.py")
            continue
        if not is_live_owner(red.task):
            unattributed.append(k)
            st = task_status(red.task)
            lines.append(f"  {k}\n      UNATTRIBUTED - the roster names {red.task}, and "
                         f"that task is {st or 'missing'}. A closed owner is not an "
                         f"owner (this is the CF-0326 defect itself): either the red is "
                         f"stale and comes out, or it needs a live successor")
            continue
        lines.append(f"  {k}\n      {red.task} ({task_status(red.task)}, named in the "
                     f"{red.named_in}): {red.why}")
    return lines, unattributed


def report(failures):
    """The whole section as one string, or "" when nothing failed."""
    if not failures:
        return ""
    lines, unattributed = attribution(failures)
    head = ("\nATTRIBUTION (CF-0326, DoD 1.4.1 item 2 - every red is named by an "
            "open task)\n")
    tail = ""
    if unattributed:
        tail = (f"\n  {len(unattributed)} UNATTRIBUTED red(s): "
                f"{', '.join(unattributed)}\n"
                f"  This breaks DoD 1.4.1 item 2. Do not widen the roster to quiet "
                f"it - file the owner.\n")
    else:
        worktree = sum(1 for f, c in failures
                       if owner(f, c) is None and key(f, c) in WORKTREE_ONLY)
        owned = len(failures) - worktree
        tail = (f"\n  {len(failures)} red(s), every one attributed: {owned} owned by an "
                f"open task"
                + (f", {worktree} worktree-only.\n" if worktree else ".\n"))
    return head + "\n".join(lines) + "\n" + tail

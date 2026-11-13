"""CF-0519: the registry of this agent's live monitors - tests that read the
live `pipeline/`, `publish/` or `shared/footage/` on purpose - and the switch
that runs them (DoD 1.6.1 #2; the root's `tests/_real_batches.py` is the same
idea, footage-indexer's and trend-hunter's `tests/_live_monitors.py` the same
shape).

Key: `file.py::owner`, the owner the root's `shared/live_tree_guard.py` names
(a top-level function, or `Class.method`), so `test_live_tree_guard.py` checks
this very dict. Value: why the read has to be live.

In the suite a monitor steps aside and prints why (`live_only()` returns
True). `VE_TESTS_LIVE=1 python3 tests/<file>` runs it on the live tree - a
check by hand, never part of `run_tests.py`. A monitor only reads; the pool
is transient (CF-0358), so a source or batch that is gone says so and passes.
Nothing here ever re-measures or writes the pool.

CF-0558 - two rules for every monitor here:

* **Not checked is not green.** A monitor that finds nothing to check (the
  batch it reads has left the live tree, the pool dropped the trailer) calls
  `not_checked(test_id, reason)`, which raises `NotChecked`. The file's runner
  (`run_tests()` + the file's own summary line) prints `NOT_CHECKED <test>: <monitor>: <reason>`,
  does not count that test as passed, prints `N/M passed, K not checked` and
  exits EXIT_NOT_CHECKED (3) when nothing failed - so the root's `runlog
  monitors` (CF-0511: green only on exit 0 and `N/N passed`) never reads it as
  green. Before, such a monitor printed "nothing checked" and passed.
* **A monitor never writes the live tree.** Outputs go to a temp dir (copy a
  live plan there before a tool that writes next to the plan it reads -
  write_batch_metadata.py writes `<plan stem>.score.json`), and the read runs
  inside `untouched(dir, ...)`, which snapshots the files under each dir
  before and fails the test on any file added, changed or removed after.

A monitor reads the newest live batch of the channel that holds what it needs
(`newest_run()`), not one dated batch: the batches leave the live tree after
publication (CF-0500 carried 2155Z away and four monitors went silent). Their
regressions run in the suite on synthetic media of the same shape (CF-0522,
`_synthetic_media.py`); the monitor is the check of the same rule on the
factory's latest real output.
"""
import contextlib
import os
import sys
from pathlib import Path

LIVE_ENV = "VE_TESTS_LIVE"

LIVE_MONITORS = {
    "test_openings_and_sides.py::_live_batch":
        "CF-0050/CF-0057 on the newest live run: the leading silence measured off "
        "its voice.wav against the opening its plan delivered (a voice that opens "
        "on a cold-frame-long lead under any other opening is a dead-air start), "
        "and the plan's rhythm shortfalls recomputed from its own order.json and "
        "blocks - real media and the real plan; the arithmetic and the end-to-end "
        "run are synthetic in the suite (CF-0522).",
    "test_rhythm_execution.py::_live_run":
        "CF-0041 on the newest live run: a frame lifted out of one of its real "
        "clips (hold_frame), write_batch_metadata.py on a temp copy of its plan "
        "and its rendered mp4 carrying the order and the cadence the plan "
        "recorded - real media; the card / held-frame / record runs are "
        "synthetic in the suite (CF-0522).",
    "test_degrade_blocks.py::_live_batch":
        "CF-0031/CF-0131 on the newest live run: write_batch_metadata.py on a "
        "temp copy of its plan and its rendered mp4 names every degraded block "
        "of that plan with its reason and says 'mixed k/N' - the honesty of the "
        "record on real output; the per-block isolation runs in the suite on "
        "synthetic media of the 2155Z shape (CF-0522).",
    "test_frozen_block_source_check.py::_live_batch_plan":
        "CF-0031/CF-0131 on the newest live plan with a clip block whose clip is "
        "still there (any run of any batch, newest first - CF-0868): no clip block "
        "it shipped runs past its own clip - common.clip_shortfall() and "
        "freeze_verdict() decode the batch's real clips (ffmpeg) and agree; hung / "
        "moving / held-pose verdicts and the pick run in the suite on synthetic "
        "clips and temp batches (CF-0522).",
    "test_pattern_delivery_reason.py::_live_corpus":
        "CF-0192: every plan still under the live pipeline/ carries a delivered "
        "pattern or a reason code - the live corpus is what it checks; the suite "
        "asks the same of the frozen plans (test_every_shipped_plan_...).",
    "test_caption_cache_freshness_of_the_pool.py::_live_pool":
        "CF-0179: the caption-crop stamp of EVERY index in the live pool against "
        "this checkout's code - the pool as it is today is what it checks; a "
        "frozen index cannot follow a code change without a re-measure, which "
        "no test does (CF-0358: the pool is transient).",
    "test_stale_usability_cache.py::_live_pool":
        "CF-0048/CF-0387: every usable_cached stamp in the live pool is today's "
        "key or a legacy stamp of the same code - the pool as it is today is "
        "what it checks; the key rule itself runs in the suite on synthetic "
        "shots (the other tests of the file).",
}


def live():
    return os.environ.get(LIVE_ENV) == "1"


def live_only(test_id):
    """True (the caller returns early) when `test_id` is a live monitor and
    this run is the suite. Prints the step-aside so it is never silent."""
    assert test_id in LIVE_MONITORS, f"{test_id} is not in LIVE_MONITORS"
    if live():
        return False
    print(f"     live monitor, not run in the suite ({LIVE_ENV}=1 runs it): "
          f"{LIVE_MONITORS[test_id]}")
    return True


# --------------------------------------------------------------------------
# CF-0558: not checked is not green; a monitor never writes the live tree
# --------------------------------------------------------------------------

NOT_CHECKED_MARK = "NOT_CHECKED"
EXIT_NOT_CHECKED = 3


class NotChecked(Exception):
    """A live monitor found nothing to check - never a pass."""


def not_checked(test_id, reason):
    """Stop the calling monitor as not checked (see the module docstring)."""
    assert test_id in LIVE_MONITORS, f"{test_id} is not in LIVE_MONITORS"
    raise NotChecked(f"{test_id}: {reason}")


def newest_run(batch_dirs, need, videos=None, accept=None):
    """(batch, work, slug) of the newest batch under `batch_dirs` (the
    channel's batch directories) whose `work/<slug>/` holds every file of
    `need` (and `videos/<slug>.mp4` when `videos`) and, with `accept`, for
    which `accept(work)` is true; None if none does. Reads only."""
    batches = []
    for d in batch_dirs:
        d = Path(d)
        if d.is_dir():
            batches += [b for b in d.iterdir() if b.is_dir() and (b / "work").is_dir()]
    for batch in sorted(batches, key=lambda b: b.name, reverse=True):
        for work in sorted((batch / "work").iterdir()):
            if not work.is_dir():
                continue
            if not all((work / n).exists() for n in need):
                continue
            if videos and not (batch / "videos" / f"{work.name}.mp4").is_file():
                continue
            if accept is not None and not accept(work):
                continue
            return batch, work, work.name
    return None


def _snapshot(root):
    root = Path(root)
    if root.is_file():
        st = root.stat()
        return {root.name: (st.st_size, st.st_mtime_ns)}
    out = {}
    for p in root.rglob("*"):
        try:
            if p.is_file() or p.is_symlink():
                st = p.lstat()
                out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
        except OSError:
            continue
    return out


@contextlib.contextmanager
def untouched(*roots):
    """Fail if anything under `roots` (dirs or files of the live tree a
    monitor reads) was added, changed or removed while the block ran."""
    before = {str(r): _snapshot(r) for r in roots}
    yield
    problems = []
    for r in roots:
        after = _snapshot(r)
        was = before[str(r)]
        added = sorted(set(after) - set(was))
        gone = sorted(set(was) - set(after))
        changed = sorted(k for k in set(after) & set(was) if after[k] != was[k])
        for what, names in (("added", added), ("removed", gone), ("changed", changed)):
            if names:
                problems.append(f"{r}: {what} {', '.join(names[:5])}"
                                + (f" (+{len(names) - 5})" if len(names) > 5 else ""))
    assert not problems, ("a live monitor wrote the live tree (CF-0558): "
                          + "; ".join(problems))


def run_tests(tests):
    """Run a file's test functions the house way, NotChecked counted apart:
    `PASS name`, `FAIL name` + traceback, `NOT_CHECKED name: why`. Returns
    (failed, unchecked, exit code: 1 on a failure, EXIT_NOT_CHECKED when
    nothing failed but something was not checked, else 0). The file prints
    its own summary line (the runner's contract, test_summary_line_contract):

        failed, unchecked, rc = run_tests(tests)
        print(f"\\n{len(tests) - failed - unchecked}/{len(tests)} passed"
              + not_checked_tail(unchecked))
        sys.exit(rc)
    """
    import traceback
    failed = unchecked = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except NotChecked as e:
            unchecked += 1
            print(f"{NOT_CHECKED_MARK} {t.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    sys.stdout.flush()
    return failed, unchecked, (1 if failed else (EXIT_NOT_CHECKED if unchecked else 0))


def not_checked_tail(unchecked):
    """`, k not checked` for the summary line, or nothing."""
    return f", {unchecked} not checked" if unchecked else ""

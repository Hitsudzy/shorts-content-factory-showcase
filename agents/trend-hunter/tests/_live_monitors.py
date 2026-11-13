"""CF-0505: the registry of this agent's live monitors - tests that read the
live `pipeline/`, `publish/` or `shared/footage/` on purpose - and the switch
that runs them (DoD 1.6.1 #2; the root's `tests/_real_batches.py` is the same
idea, footage-indexer's `tests/_live_monitors.py` the same shape).

Key: `file.py::owner`, the owner the root's `shared/live_tree_guard.py` names
(a top-level function, or `Class.method`), so `test_live_tree_guard.py` checks
this very dict. Value: why the read has to be live.

In the suite a monitor steps aside and prints why (`live_only()` returns
True). `TH_TESTS_LIVE=1 python3 tests/<file>` runs it on the live tree - a
check by hand, never part of `run_tests.py`. A monitor only reads; a batch or
publication that is gone says so and passes.
"""
import os

LIVE_ENV = "TH_TESTS_LIVE"

LIVE_MONITORS = {
    "test_fact_rule.py::_live_pipeline":
        "CF-0264 invariant over EVERY batch still under pipeline/: no "
        "no_production_fact loss taken after the indexer in a batch run under "
        "the shortlist - the live batches are what it checks; the suite holds "
        "the same invariant on the frozen replay_pool.",
    "test_published_before.py::test_live_root_says_the_same":
        "CF-0019: the live publish/acceptance-log.json and the live 0705Z batch "
        "still tell backrooms and wolfhame apart as published - the "
        "publications on disk are what it checks; the suite runs the same "
        "audit on the frozen published_before_0705z (test_replay_0705z).",
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

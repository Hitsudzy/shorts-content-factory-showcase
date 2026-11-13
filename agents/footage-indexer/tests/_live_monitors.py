"""CF-0505: the registry of this agent's live monitors - tests that read the
live `pipeline/` or `shared/footage/` on purpose - and the switch that runs
them (DoD 1.6.1 #2; the root's `tests/_real_batches.py` is the same idea).

Key: `file.py::owner`, the owner the root's `shared/live_tree_guard.py` names
(a top-level function, or `Class.method`), so `test_live_tree_guard.py` checks
this very dict. Value: why the read has to be live.

In the suite a monitor steps aside and prints why (`live_only()` returns
True). `FI_TESTS_LIVE=1 python3 tests/<file>` runs it on the live tree - a
check by hand, never part of `run_tests.py` - and so does a real batch's
`$RUNLOG_BATCH` (see live()). The pool is transient (CF-0358:
a source is deleted after its video is published), so a monitor that finds
its source gone says so and passes; it never re-measures or writes the pool.
"""
import os

LIVE_ENV = "FI_TESTS_LIVE"

LIVE_MONITORS = {
    "test_branding_is_not_a_card.py::_real":
        "CF-0413 regression on the real mp4 of 3oy35kY7guU (re-probes its frames "
        "with ffmpeg + Vision): a video is no fixture, and the source leaves the "
        "pool after publishing (CF-0358).",
    "test_text_cut_by_crop.py::_live_pool":
        "CF-0275 separation measured on real full frames of -3NpUXI5juI.mp4 "
        "(ffmpeg + Vision, ~90 s): the frames are the input, no fixture holds them.",
    "test_card_probe_real_footage.py::_live_pool":
        "CF-0413/CF-0331 card probe on real frames of four pool mp4s (Vision "
        "worker): the frames are the input, and the pool is transient (CF-0358).",
    "test_sharpness.py::_live_pool":
        "CF-0452: re-reads the two held frames (kaijura / wolfhame) from the "
        "pool's own mp4s; the recorded values are frozen in cf0452_sharpness.json "
        "and checked in the suite without them.",
    "test_card_phrase_vocabulary.py::test_the_corpus_is_what_the_batches_on_disk_say":
        "CF-0427: compares the frozen phrase corpus with every anchors.json still "
        "under pipeline/ - the live batches are what it checks; the suite checks "
        "the vocabulary on the frozen corpus (test_against_the_frozen_corpus_...).",
    "test_caption_cache_freshness.py::_live_pool":
        "CF-0055: the caption-crop stamp of EVERY index in the pool, and a live "
        "re-probe of three real ZZ_urA56pJE shots - the live pool is what it "
        "checks (pool-maintenance's caption_cache.py is the batch gate); the "
        "rule itself runs on synthetic shots in the suite.",
    "test_usability_cache_freshness.py::_live_pool":
        "CF-0048/CF-0410: the current batch's sources ($RUNLOG_BATCH/01b) and "
        "the pool's stale-stamp line for pool-maintenance, and a live re-probe "
        "of three real shots - never remeasures; synthetic pool in the suite.",
    "test_moment_at_schema.py::_live_pool":
        "CF-0060: a 20-index sample of the live pool loads and carries no bad "
        "moment_at mark - the pool's own state; the schema runs on synthetic "
        "indexes in the suite.",
}


def live():
    """FI_TESTS_LIVE=1, or a real batch is running: `$RUNLOG_BATCH` names a
    directory under the factory's `pipeline/`. The second is the operator's
    `pool-maintenance` run of test_usability_cache_freshness.py (README,
    CF-0410) - the batch check, not the suite, which never sets RUNLOG_BATCH
    to a real batch."""
    if os.environ.get(LIVE_ENV) == "1":
        return True
    batch = os.environ.get("RUNLOG_BATCH")
    if not batch:
        return False
    from pathlib import Path
    from _fi_paths import factory_root
    try:
        pipeline = factory_root() / "pipeline"
    except RuntimeError:
        return False
    # Compared as written and resolved: a version worktree's pipeline/<channel>
    # is a symlink into the main checkout's.
    batch = Path(batch).absolute()
    return any(b.is_relative_to(p) for b in (batch, batch.resolve())
               for p in (pipeline.absolute(), pipeline.resolve()))


def live_only(test_id):
    """True (the caller returns early) when `test_id` is a live monitor and
    this run is the suite. Prints the step-aside so it is never silent."""
    assert test_id in LIVE_MONITORS, f"{test_id} is not in LIVE_MONITORS"
    if live():
        return False
    print(f"     live monitor, not run in the suite ({LIVE_ENV}=1 runs it): "
          f"{LIVE_MONITORS[test_id]}")
    return True

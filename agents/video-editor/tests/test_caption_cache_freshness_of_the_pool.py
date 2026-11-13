#!/usr/bin/env python3
"""CF-0179: the footage pool's caption stamp, asked in the repo that moves it.

`agents/footage-indexer` owns the cache and already asks this question
(`tests/test_caption_cache_freshness.py`). It asks it in the wrong place.
Measured over 2026-08-14..2026-09-14, of the 38 commits that changed a file in
`caption_cache.CAPTION_SOURCES` and so invalidated every `crop_bottom_cached`
in `shared/footage/`, **36 were commits to this repository** - five of the
seven files live in `scripts/` here. Nobody working in this repo learned
anything about it: their own suite never asked, and the refusal surfaced at the
front of the next batch (CF-0151 put the check first in the footage-indexer
stage), as a 51.7-minute re-measure nobody had planned for.

So this file is not a second opinion, it is the same opinion delivered on time.
It imports `caption_cache` rather than re-deriving anything - two copies of
this rule is how they would come to disagree - and costs the same 1.3s the
batch check costs.

## What a failure here means, and what it does not

It does not mean this repo is broken. It means a change made here moved the
code that measures burned-in subtitles, so every cached crop in the pool was
taken by code that no longer exists, and `resolve_anchors.cut()` would hand
those numbers to `prepare_clip.py --crop-bottom` and frame real clips with
them. CF-0055 refuses instead of falling back because the fallback,
`--auto-crop` per candidate, costs a measured 3.19s -> 13.32s per cut.

The fix is a decision, not a chore: re-measuring changes the geometry of every
clip cut from those sources, so it is surfaced and never done automatically.
The command is printed by the failure.

## Why the tax is not "fixed" by hashing less

CF-0179 measured that too: 15 of those 38 commits touched nothing the caption
measurement runs, and 15 of the 15 were `common.py`, 786 lines of which this
measurement uses about 150 (`grab_frames`, `media_duration` and their
closure). Hashing only the closure would drop 39% of the invalidations - but
the unit of the cost is a *re-measure*, and re-measures happen per batch, not
per commit, so a narrower digest only spares a batch when every commit in the
window was incidental: p = 0.31 at a daily cadence, 0.0003 at a weekly one.
That is why CF-0179 kept the digest over whole files and fixed *when* you find
out instead. CF-0387 then narrowed it anyway - two whole-pool incidents in
three days on a 4818-shot pool changed the arithmetic - so the caption key is
now `code_reach`'s digest of what `probe_captions()` reaches, and CF-0406 did
the same for the usability key. This file still answers *when*: an edit to
reached code moves the key, and this is where that is first seen.

## Which checkout this answers about

`caption_cache` resolves `CAPTION_SOURCES` off the *main* checkout (CF-0125),
and so does `repo_paths.INDEXER_SCRIPTS` below. That is deliberate and not a
gap: `remeasure_captions.py` stamps the pool with the main checkout's bytes, so
a fingerprint taken over a worktree's in-progress edit would stamp the pool
with code that is about to disappear. Run from a git worktree this file
therefore reports the main checkout's state, not the worktree's - the alarm
fires when the change lands, which is when the pool actually goes stale. Tasks
in this repo are dispatched into the checkout rather than a worktree anyway
(CF-0196: a worktree of the root repo contains no `agents/` at all), so in
practice that is the same moment.

A version's checkout is different (CF-0479/CF-0482): `.worktrees/release-<v>/`
is a root worktree that does hold `agents/`, each a git worktree of the
agent's repo, named by the version's `agents.lock.json`. There
`repo_paths.INDEXER_SCRIPTS` is the version's indexer, whose `caption_cache`
reads this very checkout's `scripts/` - the version's own code, which is what
will stamp the pool when the version is released. The key is path-free
(`code_reach` digests module stems and source, not locations), so the version
and production agree on it exactly when the reached code is the same.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import repo_paths  # noqa: E402 - CF-0125/CF-0482: the main checkout, or the version's root
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _live_monitors import live_only  # noqa: E402 - CF-0519


def caption_cache():
    """footage-indexer's `caption_cache`, or `None` when that checkout is not
    beside this one.

    Imported here rather than at module level on purpose. A sibling repository
    is not a dependency this repo may die on: an import failure at module level
    is reported by `run_tests.py` as a FAILED file, which would turn "the
    indexer is not checked out" into something indistinguishable from a real
    regression (CF-0054's rule, and CF-0159's actual bug in the other
    direction)."""
    if not (repo_paths.INDEXER_SCRIPTS / "caption_cache.py").exists():
        return None
    sys.path.insert(0, str(repo_paths.INDEXER_SCRIPTS))
    import caption_cache as module
    return module


def _live_pool():
    """Every index of the live pool (CF-0519: a live monitor - the stamp of
    the pool as it is today is what this checks; no fixture can hold it, and
    the pool is never re-measured from a test)."""
    footage = repo_paths.FACTORY_ROOT / "shared" / "footage"
    return sorted(footage.glob("*.shots.json")) if footage.is_dir() else []


def test_the_pool_this_repo_cuts_from_carries_this_checkout_s_stamp():
    """The whole pool, in about a second. Red here is the same red the batch
    would hit at its first footage-indexer step - only hours earlier, in the
    repo whose commit caused it."""
    if live_only("test_caption_cache_freshness_of_the_pool.py::_live_pool"):
        return
    cache = caption_cache()
    if cache is None:
        print("  NOTE: agents/footage-indexer not checked out - nothing checked")
        return
    indexes = _live_pool()
    if not indexes:
        print("  NOTE: no shared/footage indexes present - nothing checked")
        return
    stale = cache.survey(indexes)
    assert not stale, cache.complaint(stale)


def test_this_repo_is_where_most_of_that_stamp_comes_from():
    """Why the check above lives here at all, pinned as a fact rather than
    left in a comment.

    Six of the eight files in `CAPTION_SOURCES` are `scripts/` of this repo.
    Since CF-0387 the key is the digest of what the probe reaches inside them,
    not their bytes, but the list is still the walk's whole universe and this
    repo still holds most of what it reaches. If that stops being true - the
    measurement moves out - this assertion is where someone is told that the
    alarm may now belong somewhere else. It reads the same tuple
    `test_fingerprint_covers_exactly_the_caption_measuring_code` guards in the
    other repo, so the two cannot drift about what the list is."""
    cache = caption_cache()
    if cache is None:
        print("  NOTE: agents/footage-indexer not checked out - nothing checked")
        return
    ours = [p for p in cache.CAPTION_SOURCES
            if Path(p).resolve().is_relative_to(SCRIPTS)]
    assert len(cache.CAPTION_SOURCES) == 8, (
        f"CAPTION_SOURCES is now {len(cache.CAPTION_SOURCES)} files, not 8: "
        f"{[Path(p).name for p in cache.CAPTION_SOURCES]}. If the measurement "
        f"moved, so should this check.")
    assert sorted(p.name for p in ours) == [
        "common.py", "detect_text_band.py", "repo_paths.py",
        "vision_client.py", "vision_compute.py", "vision_worker.py"], (
        f"this repo's share of the caption fingerprint changed: "
        f"{sorted(p.name for p in ours)}")


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

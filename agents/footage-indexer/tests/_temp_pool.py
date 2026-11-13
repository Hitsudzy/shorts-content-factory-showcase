"""CF-0683: the cache index `fetch_footage.load_index()` reads, fenced to a
temp pool for a test file.

`fetch_footage.CACHE` / `INDEX` are `_fi_paths.pool_dir()` at import - the
checkout's live `shared/footage/` (CF-0620). The stage asks that index on paths
no test meant to reach the pool through: `ingest_batch.cache_entry_of` from
`rights_for` (CF-0663: the `rights` an earlier fetch kept on the cache entry)
and from `measure_candidate` (CF-0302). Repointing `ingest_batch.CACHE` does
not cover it - the index is `fetch_footage`'s own - so 19 files opened the live
`shared/footage/index.json` on every run (the CF-0621 audit hook, strict run
of 2026-10-11), and what a cached entry of the live pool said could change a
test's rights answer. Each of them now calls, at import:

    from _temp_pool import fence_cache_index
    fence_cache_index(TMP / "ff-pool")      # or the file's own temp pool

Production is unchanged: there `ingest_batch.CACHE` and `fetch_footage.CACHE`
are the same `pool_dir()`.
"""
from pathlib import Path

__all__ = ["fence_cache_index"]


def fence_cache_index(pool):
    """Point `fetch_footage.CACHE` / `INDEX` at `pool` (created). Returns it."""
    import fetch_footage
    pool = Path(pool)
    pool.mkdir(parents=True, exist_ok=True)
    fetch_footage.CACHE, fetch_footage.INDEX = pool, pool / "index.json"
    return pool

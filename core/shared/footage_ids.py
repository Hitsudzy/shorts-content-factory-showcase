#!/usr/bin/env python3
"""CF-0665: the ids a source of the footage pool (`shared/footage/<id>.*`)
can have - one place for every root reader that asks "is this a pool file?".

Until CF-0665 every source in the pool was a YouTube video, and readers held
it to YouTube's own id shape (`[A-Za-z0-9_-]{11}`). Since then the Footage
Indexer also fetches archive files directly (NASA Image and Video Library,
Wikimedia Commons - FI `scripts/archive_source.py`): the Trend Hunter names
such a candidate `nasa:<id>` / `commons:<pageid>`, and on disk, in the cache
index and in every report of the indexer the source is its *file id*
`nasa-<id>` / `commons-<pageid>` - every character outside `[A-Za-z0-9_-]`
made `_` - with the hunter's id kept beside it as `candidate_id`. A reader
still on `{11}` drops the archive file silently: `pool_release` never listed
it, so it would never be released.

This module is the root's copy of that rule, kept in step with FI's
`archive_source.CANDIDATE_ID_RE` / `FILE_ID_RE` / `file_id()`. Stdlib only,
no neighbour imported: readers load it by path.
"""
import re

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ARCHIVES = ("nasa", "commons")
# The Trend Hunter's name of an archive candidate.
ARCHIVE_CANDIDATE_RE = re.compile(r"^(nasa|commons):(.+)$")
# The file id the indexer keeps an archive source under.
ARCHIVE_FILE_ID_RE = re.compile(r"^(nasa|commons)-([A-Za-z0-9_-]+)$")
# Any source of the pool: a YouTube video or an archive file.
POOL_FILE_ID_RE = re.compile(r"^(?:[A-Za-z0-9_-]{11}|(?:nasa|commons)-[A-Za-z0-9_-]+)$")
UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def is_pool_file_id(value):
    return isinstance(value, str) and bool(POOL_FILE_ID_RE.match(value))


def archive_file_id(value):
    """`nasa:<id>` -> `nasa-<id>` (the indexer's `file_id()`); anything that
    is not an archive candidate id is returned as it is."""
    s = str(value or "")
    m = ARCHIVE_CANDIDATE_RE.match(s)
    if not m:
        return s
    return f"{m.group(1)}-{UNSAFE.sub('_', m.group(2))}"

#!/usr/bin/env python3
"""CF-0718: one loader of a batch's RUN_EVENTS.jsonl for summary, funnel and
triage, that reads a grown journal by its new tail only.

`runlog summary` on a 12 MB journal spent ~9 s, most of it parsing the same
lines again on every call - and the command center asks for the summary, the
funnel and the triage of an open batch over and over while the journal only
grows. `load_events(batch_dir)` keeps, per file and in this process only, the
events already parsed and where the parse stopped:

    key       the absolute path of the journal
    kept      st_dev / st_ino, st_size, st_mtime_ns of the last read; the byte
              offset just past the last complete line consumed; the first and
              the last CHECK_BYTES of the consumed prefix; the events parsed

and on the next call decides by `os.stat` alone, then by those two windows:

    * same inode, same size, same mtime            - nothing read, the kept events;
    * same inode, size >= offset, both windows of the consumed prefix still
      the same bytes                               - only [offset, size) is read
                                                     and parsed (an append);
    * anything else - the size fell below what was consumed (truncated), the
      inode changed (rotated / replaced by os.replace), a window differs (the
      prefix was rewritten)                        - the whole file again.

A last line without its newline is a writer in the middle of an append: it is
not consumed - the offset stays at the last newline, so the next read picks the
whole line up. If what is there already parses, it is in the answer (a file
that simply ends without a newline reads as `runlog.read_events` reads it); if
it does not, it is left out without a warning, since it is not finished yet.

The answer equals `runlog.read_events(batch_dir)`: every event in file order,
blank lines dropped, a line that will not parse skipped with the same warning
(`<path>:<line>: unreadable event line skipped`, said once, when the line is
first parsed). A line that is not UTF-8 is skipped the same way (read_events
raised on it).

**The events are read-only.** Every call returns a new list, but the event
dicts in it are the cached ones, so they are `Event` - a dict that refuses
`e[k] = v`, `del`, `update`, `pop`, `setdefault`, `clear`, `|=` with a
TypeError (every nested JSON object is one too). Reading is a plain dict's
(`isinstance(e, dict)`, `json.dumps`, `==`, `e | {...}`); `dict(e)`,
`copy.copy(e)` and `copy.deepcopy(e)` give a plain mutable dict. Nested JSON
arrays stay lists - nothing in the readers writes into them; don't.

The cache is bounded: MAX_FILES journals, MAX_BYTES of consumed journal in
all, least recently used out first (the most recent one always stays).
`stats()` counts hits, tail reads, full reads and lines parsed; `clear()`
empties the cache. Thread-safe: one lock around a lookup and its read.

`runlog.read_events` itself is untouched (the agents load runlog.py through
their own loaders); this module is the shared loader of summary.py, funnel.py
and triage.py.
"""
import json
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

MAX_FILES = 32
MAX_BYTES = 256 * 1024 * 1024
CHECK_BYTES = 16 * 1024

_LOCK = threading.Lock()
_CACHE = OrderedDict()          # abs path -> _Entry
_STATS = {"hits": 0, "tail_reads": 0, "full_reads": 0, "parsed_lines": 0}

READ_ONLY = ("a cached run event is read-only (CF-0718, shared/runlog/event_log.py); "
             "take a copy first: dict(e) or copy.deepcopy(e)")


class Event(dict):
    """A JSON object of the journal, as kept in the cache: read like a dict,
    never written. Copies (`dict(e)`, `copy.copy`, `copy.deepcopy`) are plain."""
    __slots__ = ()

    def _read_only(self, *args, **kwargs):
        raise TypeError(READ_ONLY)

    __setitem__ = __delitem__ = __ior__ = _read_only
    clear = pop = popitem = setdefault = update = _read_only

    def __copy__(self):
        return dict(self)

    def __deepcopy__(self, memo):
        return _thaw(self)

    def __reduce__(self):
        return (dict, (_thaw(self),))


def _thaw(o):
    if isinstance(o, dict):
        return {k: _thaw(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_thaw(v) for v in o]
    return o


# One decoder for the module: json.loads(s, object_pairs_hook=...) builds a new
# JSONDecoder per line, which cost more than the parse itself.
_DECODE = json.JSONDecoder(object_pairs_hook=Event).decode


def _loads(s):
    return _DECODE(s)


class _Entry:
    __slots__ = ("dev", "ino", "size", "mtime_ns", "offset", "lines", "head", "edge",
                 "events", "pending")

    def __init__(self):
        self.dev = self.ino = None
        self.size = self.mtime_ns = None
        self.offset = 0             # bytes consumed: just past the last complete line
        self.lines = 0              # lines consumed (for the warning's line number)
        self.head = b""             # the first CHECK_BYTES of the consumed prefix
        self.edge = b""             # the last CHECK_BYTES of the consumed prefix
        self.events = []
        self.pending = None         # the unfinished last line, when it already parses




def _parse(path, chunk, entry):
    """Consume the complete lines of `chunk` (bytes from entry.offset on) into
    entry; keep the unfinished last line out of the offset."""
    cut = chunk.rfind(b"\n") + 1
    complete, rest = chunk[:cut], chunk[cut:]
    if complete:
        raws = complete.split(b"\n")[:-1]
        try:
            texts = complete.decode("utf-8").split("\n")[:-1]
        except UnicodeDecodeError:
            texts = None
        for i, raw in enumerate(raws):
            n = entry.lines + i + 1
            if texts is not None:
                line = texts[i].strip()
            else:
                try:
                    line = raw.decode("utf-8").strip()
                except UnicodeDecodeError:
                    runlog._warn(f"{path}:{n}: unreadable event line skipped")
                    continue
            if not line:
                continue
            _STATS["parsed_lines"] += 1
            try:
                entry.events.append(_loads(line))
            except ValueError:
                runlog._warn(f"{path}:{n}: unreadable event line skipped")
        entry.lines += len(raws)
        entry.offset += len(complete)
    entry.pending = None
    if rest.strip():
        try:
            entry.pending = _loads(rest.decode("utf-8").strip())
        except ValueError:                      # UnicodeDecodeError is a ValueError
            entry.pending = None


def _windows(fh, offset):
    fh.seek(0)
    head = fh.read(min(CHECK_BYTES, offset))
    lo = max(0, offset - CHECK_BYTES)
    fh.seek(lo)
    edge = fh.read(offset - lo)
    return head, edge


def _read(path, st, entry):
    """Bring `entry` (None: a fresh one) up to the file as stat()ed; returns the entry."""
    with open(path, "rb") as fh:
        if (entry is not None and entry.dev == st.st_dev and entry.ino == st.st_ino
                and st.st_size >= entry.offset
                and _windows(fh, entry.offset) == (entry.head, entry.edge)):
            _STATS["tail_reads"] += 1
        else:
            entry = _Entry()
            _STATS["full_reads"] += 1
        fh.seek(entry.offset)
        chunk = fh.read(max(0, st.st_size - entry.offset))
        _parse(path, chunk, entry)
        entry.head, entry.edge = _windows(fh, entry.offset)
    entry.dev, entry.ino = st.st_dev, st.st_ino
    entry.size, entry.mtime_ns = st.st_size, st.st_mtime_ns
    return entry


def _evict():
    total = sum(e.offset for e in _CACHE.values())
    while len(_CACHE) > 1 and (len(_CACHE) > MAX_FILES or total > MAX_BYTES):
        _, old = _CACHE.popitem(last=False)
        total -= old.offset


def _answer(entry):
    out = list(entry.events)
    if entry.pending is not None:
        out.append(entry.pending)
    return out


def load_jsonl(path):
    """Every JSON object of the journal at `path`, in file order, read
    incrementally (see the module docstring). `[]` when there is no file."""
    key = os.path.abspath(os.fspath(path))
    with _LOCK:
        try:
            st = os.stat(key)
        except FileNotFoundError:
            _CACHE.pop(key, None)
            return []
        entry = _CACHE.get(key)
        if (entry is not None and entry.dev == st.st_dev and entry.ino == st.st_ino
                and entry.size == st.st_size and entry.mtime_ns == st.st_mtime_ns):
            _STATS["hits"] += 1
            _CACHE.move_to_end(key)
            return _answer(entry)
        try:
            entry = _read(key, st, entry)
        except BaseException:
            _CACHE.pop(key, None)
            raise
        _CACHE[key] = entry
        _CACHE.move_to_end(key)
        _evict()
        return _answer(entry)


def load_events(batch_dir):
    """The events of the batch - `runlog.read_events(batch_dir)`, from the cache."""
    return load_jsonl(runlog.events_path(batch_dir))


def stats():
    with _LOCK:
        return dict(_STATS, files=len(_CACHE),
                    bytes=sum(e.offset for e in _CACHE.values()))


def clear():
    with _LOCK:
        _CACHE.clear()
        for k in _STATS:
            _STATS[k] = 0

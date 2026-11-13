#!/usr/bin/env python3
"""CF-0718: the shared incremental loader of RUN_EVENTS.jsonl
(shared/runlog/event_log.py) - a grown journal is read by its tail only and
answers what a full read answers; a truncated, rotated or rewritten one is read
again from the start; an unfinished last line is not consumed; the cached
events cannot be written through; summary, funnel and triage load through it.
Temp trees only."""
import contextlib
import copy
import io
import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

import event_log  # noqa: E402
import runlog     # noqa: E402

TMP = tmp_root("cf0718-")
_n = [0]


def _batch():
    _n[0] += 1
    d = TMP / f"b{_n[0]}"
    d.mkdir()
    return d


def _ev(i, **kw):
    e = {"ts": f"2026-10-13T10:{i // 60:02d}:{i % 60:02d}Z", "kind": "script",
         "status": "start", "stage": "s", "id": f"id{i}", "n": i,
         "meta": {"nested": {"k": i}}, "list": [i, {"x": i}]}
    e.update(kw)
    return e


def _write(d, events, mode="w", tail=""):
    p = runlog.events_path(d)
    with open(p, mode, encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
        fh.write(tail)
    return p


def _bump_mtime(p):
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def _quiet(fn, *a):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = fn(*a)
    return out, err.getvalue()


def _fresh():
    event_log.clear()


# --------------------------------------------------------------------------

def test_an_unchanged_journal_is_not_read_again():
    _fresh()
    d = _batch()
    _write(d, [_ev(i) for i in range(5)])
    a = event_log.load_events(d)
    b = event_log.load_events(d)
    s = event_log.stats()
    assert a == b == runlog.read_events(d)
    assert a is not b
    assert (s["full_reads"], s["tail_reads"], s["hits"], s["parsed_lines"]) == (1, 0, 1, 5)


def test_an_appended_journal_parses_only_the_tail_and_equals_a_full_read():
    _fresh()
    d = _batch()
    _write(d, [_ev(i) for i in range(100)])
    first = event_log.load_events(d)
    assert len(first) == 100 and event_log.stats()["parsed_lines"] == 100
    p = _write(d, [_ev(i) for i in range(100, 103)], mode="a")
    _bump_mtime(p)
    got = event_log.load_events(d)
    s = event_log.stats()
    assert s["tail_reads"] == 1 and s["full_reads"] == 1
    assert s["parsed_lines"] == 103, s                 # only the three new lines
    assert got == runlog.read_events(d)
    assert [e["n"] for e in got] == list(range(103))
    assert got[:100] == first and len(first) == 100     # the earlier answer kept its length


def test_a_truncated_journal_is_read_again_from_the_start():
    _fresh()
    d = _batch()
    _write(d, [_ev(i) for i in range(50)])
    assert len(event_log.load_events(d)) == 50
    _write(d, [_ev(i, stage="after") for i in range(7)])         # "w": truncated in place
    got = event_log.load_events(d)
    s = event_log.stats()
    assert s["full_reads"] == 2 and s["tail_reads"] == 0
    assert got == runlog.read_events(d)
    assert len(got) == 7 and all(e["stage"] == "after" for e in got)


def test_a_rewritten_prefix_of_a_longer_file_is_read_again():
    _fresh()
    d = _batch()
    _write(d, [_ev(i) for i in range(10)])
    assert len(event_log.load_events(d)) == 10
    # Same inode, longer than before, but not an append: the first line changed.
    _write(d, [_ev(0, stage="X")] + [_ev(i) for i in range(1, 12)])
    _bump_mtime(runlog.events_path(d))
    got = event_log.load_events(d)
    assert event_log.stats()["full_reads"] == 2
    assert got == runlog.read_events(d) and got[0]["stage"] == "X" and len(got) == 12


def test_a_rotated_journal_is_read_again():
    _fresh()
    d = _batch()
    p = _write(d, [_ev(i) for i in range(10)])
    assert len(event_log.load_events(d)) == 10
    other = d / "new.jsonl"
    with open(other, "w", encoding="utf-8") as fh:
        for i in range(10):                     # the same bytes and more, another inode
            fh.write(json.dumps(_ev(i)) + "\n")
        fh.write(json.dumps(_ev(99)) + "\n")
    os.replace(other, p)
    got = event_log.load_events(d)
    assert event_log.stats()["full_reads"] == 2 and event_log.stats()["tail_reads"] == 0
    assert got == runlog.read_events(d) and len(got) == 11


def test_an_unfinished_last_line_is_not_consumed():
    _fresh()
    d = _batch()
    line = json.dumps(_ev(3))
    p = _write(d, [_ev(0), _ev(1), _ev(2)], tail=line[:20])      # a writer mid-append
    got, err = _quiet(event_log.load_events, d)
    assert [e["n"] for e in got] == [0, 1, 2] and err == ""      # no warning for it
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line[20:] + "\n")
    _bump_mtime(p)
    got = event_log.load_events(d)
    assert [e["n"] for e in got] == [0, 1, 2, 3]
    assert got == runlog.read_events(d)
    assert event_log.stats()["tail_reads"] == 1 and event_log.stats()["full_reads"] == 1


def test_a_complete_last_line_without_a_newline_reads_like_read_events():
    _fresh()
    d = _batch()
    p = _write(d, [_ev(0)], tail=json.dumps(_ev(1)))
    got = event_log.load_events(d)
    assert got == runlog.read_events(d) and [e["n"] for e in got] == [0, 1]
    assert event_log.load_events(d) == got                  # the hit keeps it
    with open(p, "a", encoding="utf-8") as fh:              # its newline, and one more
        fh.write("\n" + json.dumps(_ev(2)) + "\n")
    _bump_mtime(p)
    got = event_log.load_events(d)
    assert [e["n"] for e in got] == [0, 1, 2] and got == runlog.read_events(d)
    assert event_log.stats()["full_reads"] == 1


def test_broken_and_blank_lines_are_skipped_with_read_events_warning():
    _fresh()
    d = _batch()
    p = runlog.events_path(d)
    p.write_text(json.dumps(_ev(0)) + "\n\n{broken\n" + json.dumps(_ev(1)) + "\n",
                 encoding="utf-8")
    got, err = _quiet(event_log.load_events, d)
    want, want_err = _quiet(runlog.read_events, d)
    assert got == want and [e["n"] for e in got] == [0, 1]
    assert err == want_err and f"{p}:3: unreadable event line skipped" in err
    with open(p, "ab") as fh:                       # a non-UTF-8 line in the tail
        fh.write(b"\xff\xfe\n" + (json.dumps(_ev(2)) + "\n").encode())
    _bump_mtime(p)
    got, err = _quiet(event_log.load_events, d)
    assert [e["n"] for e in got] == [0, 1, 2]
    assert f"{p}:5: unreadable event line skipped" in err and ":3:" not in err


def test_no_file_is_an_empty_list():
    _fresh()
    d = _batch()
    assert event_log.load_events(d) == [] == runlog.read_events(d)
    _write(d, [_ev(0)])
    assert len(event_log.load_events(d)) == 1
    runlog.events_path(d).unlink()
    assert event_log.load_events(d) == []


def test_callers_cannot_corrupt_the_cache():
    _fresh()
    d = _batch()
    _write(d, [_ev(i) for i in range(3)])
    got = event_log.load_events(d)
    got.sort(key=lambda e: -e["n"])
    got.append({"x": 1})
    e = event_log.load_events(d)[0]
    for write in (lambda: e.__setitem__("n", 9), lambda: e.update(n=9),
                  lambda: e.pop("n"), lambda: e.setdefault("z", 1), lambda: e.clear(),
                  lambda: e.__delitem__("n"), lambda: e["meta"].__setitem__("k", 1),
                  lambda: e["list"][1].__setitem__("x", 0)):
        try:
            write()
        except TypeError:
            pass
        else:
            raise AssertionError("a cached event took a write")
    try:
        e |= {"n": 9}
    except TypeError:
        pass
    else:
        raise AssertionError("|= went through")
    again = event_log.load_events(d)
    assert [x["n"] for x in again] == [0, 1, 2] and again == runlog.read_events(d)
    # reading is a dict's, copies are plain and free to change
    assert isinstance(e, dict) and json.loads(json.dumps(e)) == e and (e | {"n": 5})["n"] == 5
    for c in (dict(e), copy.copy(e), copy.deepcopy(e), pickle.loads(pickle.dumps(e))):
        assert type(c) is dict
        c["n"] = 7
    deep = copy.deepcopy(e)
    deep["meta"]["nested"]["k"] = 42
    assert type(deep["meta"]) is dict and e["meta"]["nested"]["k"] == 0


def test_the_cache_is_bounded():
    _fresh()
    old = event_log.MAX_FILES
    event_log.MAX_FILES = 3
    try:
        ds = [_batch() for _ in range(5)]
        for d in ds:
            _write(d, [_ev(0)])
            event_log.load_events(d)
        assert event_log.stats()["files"] == 3
        event_log.load_events(ds[0])                       # evicted: read again
        assert event_log.stats()["full_reads"] == 6
        event_log.load_events(ds[4])                       # still kept
        assert event_log.stats()["hits"] == 1
    finally:
        event_log.MAX_FILES = old
    _fresh()
    old = event_log.MAX_BYTES
    event_log.MAX_BYTES = 1
    try:
        a, b = _batch(), _batch()
        _write(a, [_ev(0)])
        _write(b, [_ev(1)])
        event_log.load_events(a)
        event_log.load_events(b)
        assert event_log.stats()["files"] == 1             # the most recent stays
        assert event_log.load_events(b)[0]["n"] == 1 and event_log.stats()["hits"] == 1
    finally:
        event_log.MAX_BYTES = old


def test_summary_funnel_and_triage_load_through_it():
    src = {n: (ROOT / "shared" / "runlog" / f"{n}.py").read_text(encoding="utf-8")
           for n in ("summary", "funnel", "triage")}
    for name, text in src.items():
        assert "runlog.read_events(" not in text, f"{name}.py reads the events past the cache"
        assert "load_events(" in text, name


def test_summary_compute_reads_a_grown_journal_by_its_tail():
    import summary
    _fresh()
    d = _batch()
    hdr = {"batch": "x/b", "channel": "x"}
    base = [{"ts": "2026-10-13T10:00:00Z", "kind": runlog.KIND_MARKER,
             "status": runlog.M_BATCH_START, "header": hdr}]
    base += [_ev(i) for i in range(1, 6)]
    _write(d, base)
    s1 = summary.compute(d)
    assert s1["counts"]["events"] == 6
    p = _write(d, [_ev(6)], mode="a")
    _bump_mtime(p)
    s2 = summary.compute(d)
    assert s2["counts"]["events"] == 7
    st = event_log.stats()
    assert st["full_reads"] == 1 and st["tail_reads"] >= 1 and st["parsed_lines"] == 7
    assert summary.compute(events=runlog.read_events(d))["counts"] == s2["counts"]


def test_summary_load_annotates_a_copy_of_a_recorded_gap():
    """The guard found it: summary.load wrote `_t0`/`_t1` into the `params` of
    the journal's own `gap` events - with a cache, into every later answer."""
    import summary
    import gaps
    _fresh()
    d = _batch()
    _write(d, [{"ts": "2026-10-13T10:00:00Z", "kind": runlog.KIND_MARKER,
                "status": runlog.M_BATCH_START, "header": {"batch": "x/b"}},
               {"ts": "2026-10-13T10:30:00Z", "kind": gaps.KIND_GAP,
                "params": {"start": "2026-10-13T10:05:00Z", "end": "2026-10-13T10:25:00Z",
                           "seconds": 1200}},
               _ev(40)])
    for _ in range(2):
        x = summary.load(d)
        assert len(x["gaps"]) == 1 and x["gaps"][0]["_t1"] - x["gaps"][0]["_t0"] == 1200
    assert "_t0" not in event_log.load_events(d)[1]["params"]
    assert event_log.stats()["full_reads"] == 1


# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

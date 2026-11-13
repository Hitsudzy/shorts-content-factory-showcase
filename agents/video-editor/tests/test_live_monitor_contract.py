#!/usr/bin/env python3
"""CF-0558: the two rules every live monitor of this agent keeps, checked on
stand-ins (temp trees, fake test functions) - no live data.

* not checked is not green: `_live_monitors.run_tests()` counts a NotChecked
  test apart, prints `NOT_CHECKED <test>: ...`, never `N/N passed`, and exits
  EXIT_NOT_CHECKED - which the root's `runlog monitors` judge (CF-0511) does
  not read as green;
* a monitor never writes the live tree: `untouched()` fails on a file added,
  changed or removed under the dirs it guards;
* `newest_run()` picks the newest batch that holds what a monitor needs.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import _live_monitors as lm  # noqa: E402
import _runlog  # noqa: E402 - the root's runlog, found from this checkout


def _run(namespace):
    """What a monitor file's __main__ does: run_tests() and its summary line."""
    tests = [v for k, v in namespace.items() if k.startswith("test_")]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        failed, unchecked, rc = lm.run_tests(tests)
        print(f"\n{len(tests) - failed - unchecked}/{len(tests)} passed"
              + lm.not_checked_tail(unchecked))
    return rc, buf.getvalue()


def _ok():
    pass


def _bad():
    raise AssertionError("boom")


def _gone():
    lm.not_checked("test_degrade_blocks.py::_live_batch", "no live run holds the files")


def test_a_not_checked_monitor_is_neither_passed_nor_failed():
    rc, out = _run({"test_a": _ok, "test_b": _gone})
    assert rc == lm.EXIT_NOT_CHECKED, (rc, out)
    assert "NOT_CHECKED _gone: test_degrade_blocks.py::_live_batch: no live run" in out, out
    assert "1/2 passed, 1 not checked" in out, out
    assert "2/2 passed" not in out, out


def test_a_failure_outranks_not_checked_and_all_green_is_zero():
    rc, out = _run({"test_a": _bad, "test_b": _gone, "test_c": _ok})
    assert rc == 1 and "FAIL _bad" in out and "1/3 passed, 1 not checked" in out, out
    rc, out = _run({"test_a": _ok, "test_c": _ok})
    assert rc == 0 and "2/2 passed" in out and "not checked" not in out, out


def test_not_checked_names_a_registered_monitor_only():
    try:
        lm.not_checked("test_nowhere.py::_x", "why")
    except AssertionError as e:
        assert "not in LIVE_MONITORS" in str(e)
    else:
        raise AssertionError("an unregistered monitor could call itself not checked")


def test_the_root_judge_never_reads_not_checked_as_green():
    """CF-0511's judge (shared/runlog/monitors.py, the root of this checkout):
    green only on exit 0 and `N/N passed`. A file with a NOT_CHECKED monitor
    exits 3 with `N-k/N passed` - not green. CF-0622: a root that knows the
    state reads it as `not_checked` (not red, not an авария), the failed names
    being the tests not checked; an older root reads it as red."""
    path = Path(_runlog.factory_root()) / "shared" / "runlog" / "monitors.py"
    spec = importlib.util.spec_from_file_location("ve_root_monitors", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _rc, out = _run({"test_a": _ok, "test_b": _gone})
    state, passed, failed, err = mod.judge(lm.EXIT_NOT_CHECKED, out)
    assert state != mod.GREEN, (state, passed, err)
    assert passed == "1/2", passed
    if hasattr(mod, "NOT_CHECKED"):                    # CF-0622 in the root
        assert state == mod.NOT_CHECKED, (state, err)
        assert failed == ["_gone"], failed
        assert err.startswith("NOT_CHECKED _gone: test_degrade_blocks.py::_live_batch:"), err
        state, *_ = mod.judge(1, _run({"test_a": _bad, "test_b": _gone})[1])
        assert state == mod.RED, state                 # a failure outranks not checked
    state, *_ = mod.judge(0, _run({"test_a": _ok})[1])
    assert state == mod.GREEN, state


def test_untouched_passes_a_read_and_fails_a_write():
    with tempfile.TemporaryDirectory() as tmp:
        live = Path(tmp) / "batch"
        (live / "work" / "v").mkdir(parents=True)
        plan = live / "work" / "v" / "plan.json"
        plan.write_text("{}")
        with lm.untouched(live):
            plan.read_text()
        for act, word in ((lambda: (live / "work" / "v" / "plan.score.json").write_text("{}"),
                           "added"),
                          (lambda: os.utime(plan, ns=(1, 1)), "changed"),
                          (lambda: plan.unlink(), "removed")):
            try:
                with lm.untouched(live):
                    act()
            except AssertionError as e:
                assert word in str(e) and "CF-0558" in str(e), str(e)
            else:
                raise AssertionError(f"a write ({word}) under a guarded dir passed")


def test_newest_run_picks_the_newest_batch_holding_the_files():
    with tempfile.TemporaryDirectory() as tmp:
        chan = Path(tmp) / "chan"
        for batch, slug, files, mp4 in (
                ("2026-10-01T0000Z", "old", ("plan.json", "voice.wav"), True),
                ("2026-10-05T0000Z", "new", ("plan.json",), True),
                ("2026-10-04T0000Z", "mid", ("plan.json", "voice.wav"), False),
                ("2026-10-03T0000Z", "ok", ("plan.json", "voice.wav"), True)):
            work = chan / batch / "work" / slug
            work.mkdir(parents=True)
            for f in files:
                (work / f).write_text("x")
            if mp4:
                (chan / batch / "videos").mkdir()
                (chan / batch / "videos" / f"{slug}.mp4").write_text("x")
        hit = lm.newest_run([chan], ("plan.json", "voice.wav"), videos=True)
        assert hit and hit[2] == "ok" and hit[0].name == "2026-10-03T0000Z", hit
        hit = lm.newest_run([chan], ("plan.json", "voice.wav"))
        assert hit and hit[2] == "mid", hit
        hit = lm.newest_run([chan], ("plan.json",), accept=lambda w: w.name != "new")
        assert hit and hit[2] == "mid", hit
        assert lm.newest_run([chan], ("nothing.json",)) is None
        assert lm.newest_run([Path(tmp) / "no-such"], ("plan.json",)) is None


if __name__ == "__main__":
    from _live_monitors import not_checked_tail, run_tests
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed, unchecked, rc = run_tests(tests)
    print(f"\n{len(tests) - failed - unchecked}/{len(tests)} passed"
          + not_checked_tail(unchecked))
    sys.exit(rc)

#!/usr/bin/env python3
"""CF-0316: the seam where the 28-hour silence began, with the watchdog on it.

On `example-film/2026-09-19T0116Z` the last event of the run was
`footage-indexer/index PEiDNOQ_0ms start` and the next one came **28h30m40s**
later. The seam is `ingest_batch._run_index()`, which ran `index_footage.py`
through a bare `subprocess.run()` - off `runlog.run_child`, with no `timeout=`,
so nothing in the factory was counting and nothing could take it down.

The watchdog itself (silence, not duration - `shared/runlog/watchdog.py`) is the
root's half and is tested there. What is pinned here is the tail: the three
calls of this repo that now name a ceiling, and what happens to a run when one
of them is actually taken down. Until this file the watchdog had never fired on
a real stage call - every check of it was synthetic.

  - `_run_index()` goes through `runlog.run_child` with `tool`, `step`, `video`,
    `on_timeout="code"` and **no** `timeout=` - passing one would put the call
    back on CF-0128's wall clock and kill honest long work;
  - a genuinely quiet child really is taken down: a real child process that
    writes nothing dies at the ceiling, and `index_source()` raises
    `IndexTimedOut` instead of hanging;
  - the kill is on paper - the child event carries the `watchdog` block and
    `rc: index_timeout`, and `watchdog.detect()` reads the source and the
    silence back out of the finished run;
  - the **run goes on**: the stage loses one source, takes the topic's next
    candidate, and the topic's CF-0129 attempt is **not** spent on a kill;
  - the outcome code stays out of `FUNNEL_CODES` (CF-0319: an авария is always
    a task for triage, never a number in the funnel), while the record's own
    `reason_code` is still the funnel word `index_failed`;
  - the two other calls of this repo name their class: `download` for the
    yt-dlp side and `scan` (with the source's own seconds) for the whole-file
    `source-scenedetect` pass.

All of it offline: no yt-dlp, no ffmpeg, no CLIP, no network. The one real
child is a two-line python script that sleeps.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0316-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")   # never touch ~/.shorts-content-factory
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from _runlog import runlog  # noqa: E402
from _fi_paths import factory_root  # noqa: E402 - CF-0267: unique name, see _fi_paths.py
import ingest_batch as ib  # noqa: E402
import index_footage as idx  # noqa: E402
# The CF-0281 harness next door: the offline fetcher, the fingerprint-by-name
# and the ingest() wrapper are the same ones this file needs, and a second copy
# of them would be a second thing to keep true.
import test_index_failure_is_not_done as cf281  # noqa: E402

sys.path.insert(0, str(factory_root() / "shared" / "runlog"))
import watchdog as wd  # noqa: E402
import funnel  # noqa: E402


# ---------------------------------------------------------------------------
# small helpers


@contextlib.contextmanager
def spying(module_owner, name="run_child", answer=None):
    """Replace `<owner>.runlog.run_child` with a recorder. Returns the call
    list: [(cmd, kwargs), ...]."""
    calls = []
    real = getattr(module_owner.runlog, name)

    def spy(cmd, **kw):
        calls.append((list(cmd), dict(kw)))
        return answer(cmd, kw) if callable(answer) else answer

    setattr(module_owner.runlog, name, spy)
    try:
        yield calls
    finally:
        setattr(module_owner.runlog, name, real)


@contextlib.contextmanager
def batch_env(batch):
    saved = os.environ.get("RUNLOG_BATCH")
    os.environ["RUNLOG_BATCH"] = str(batch)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("RUNLOG_BATCH", None)
        else:
            os.environ["RUNLOG_BATCH"] = saved


@contextlib.contextmanager
def ceiling_of(seconds):
    """The operation ceiling, lowered so a test can watch it fire in seconds
    instead of 31 minutes. The number itself is the root's and is checked in
    `test_the_ceilings_are_the_ones_the_root_accepted`."""
    saved = wd.SILENCE_CEILING_S
    wd.SILENCE_CEILING_S = float(seconds)
    try:
        yield
    finally:
        wd.SILENCE_CEILING_S = saved


@contextlib.contextmanager
def quiet_indexer(sleep_s=60):
    """`_run_index()` pointed at a real child process that says nothing at all -
    the shape of the 2026-09-19 silence, in two lines of python."""
    fake = TMP / "fake-scripts"
    fake.mkdir(parents=True, exist_ok=True)
    (fake / "index_footage.py").write_text(
        "import time, sys\ntime.sleep(%d)\n" % sleep_s)
    saved = (ib.VENV_PY, ib.SCRIPTS)
    ib.VENV_PY, ib.SCRIPTS = sys.executable, fake
    try:
        yield
    finally:
        ib.VENV_PY, ib.SCRIPTS = saved


def events(batch):
    path = Path(batch) / "RUN_EVENTS.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def killed_index(*bad, silent_s=1861.0):
    """An `index` stand-in that is taken down on the named ids, exactly as
    `index_source()` reports it after the watchdog fires."""
    bad = set(bad)

    def index(path):
        vid = Path(path).stem
        if vid in bad:
            raise ib.IndexTimedOut(
                f"index_footage.py went quiet on {vid} and was taken down by the "
                f"CF-0316 watchdog (index_timeout, silent for {int(silent_s)} s). "
                f"The run is not dropped and the topic's attempt is not spent.",
                code="index_timeout", silent_s=silent_s, ceiling_s=1860.0)
    return index


# ---------------------------------------------------------------------------
# 1. the seam itself


def test_the_index_call_goes_through_run_child_under_the_watchdog():
    """The call that was a bare subprocess.run() on 2026-09-19."""
    done = subprocess.CompletedProcess([], 0, "", "")
    with spying(ib, answer=done) as calls:
        ib._run_index(str(cf281.media("PEiDNOQ_0ms")))
    assert len(calls) == 1, calls
    cmd, kw = calls[0]
    assert cmd[1].endswith("index_footage.py"), cmd
    assert kw["tool"] == "index_footage.py", kw
    assert kw["step"] == "index", kw
    assert kw["video"] == "PEiDNOQ_0ms", kw          # the source, by slug
    assert kw["on_timeout"] == "code", kw            # never an exception here
    # The whole point of CF-0316: no wall-clock ceiling. A `timeout=` would put
    # this call back on CF-0128's duration rule, which kills honest long work -
    # an index of a 2h14m source is honest and talks the whole way.
    assert "timeout" not in kw, kw
    # No class named: the default is the operation ceiling on *silence*, so
    # "a call without a ceiling" does not exist even here.
    assert wd.ceiling_for(kw.get("watchdog")) == wd.SILENCE_CEILING_S


def test_a_call_that_names_no_class_still_gets_a_ceiling():
    assert wd.ceiling_for(None) == wd.SILENCE_CEILING_S == 1860.0


def test_the_ceilings_are_the_ones_the_root_accepted():
    """The levels are the root's arithmetic, not re-invented here (item 3)."""
    assert wd.ceiling_for("shot") == 360.0
    assert wd.ceiling_for("download") == 1500.0
    assert wd.ceiling_for("scan", source_seconds=3600) == 3600.0
    assert wd.ceiling_for("scan", source_seconds=10) == 120.0      # the floor
    assert wd.ceiling_for("scan") == 120.0                         # length unknown


# ---------------------------------------------------------------------------
# 2. a quiet operation is really taken down, and the kill is on paper


def test_a_silent_index_is_taken_down_and_the_stage_is_told():
    batch = TMP / "batch-kill"
    batch.mkdir(parents=True, exist_ok=True)
    path = cf281.media("PEiDNOQ_0ms")
    t0 = time.monotonic()
    with batch_env(batch), ceiling_of(2), quiet_indexer(sleep_s=120):
        with runlog.run("footage-indexer", "ingest", video="PEiDNOQ_0ms",
                        name="ingest_batch.py"), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                ib.index_source(str(path))
                raise AssertionError("a silent index must not read as a success")
            except ib.IndexTimedOut as e:
                killed = e
    spent = time.monotonic() - t0
    assert spent < 30, f"the child was not taken down at the ceiling ({spent:.1f} s)"
    assert killed.code == "index_timeout", killed.code
    assert killed.silent_s >= 2, killed.silent_s
    assert "not dropped" in str(killed) and "attempt is not spent" in str(killed)

    # on paper: the child event carries the outcome code and the watchdog block
    child = [e for e in events(batch)
             if e.get("kind") == "child" and e.get("tool") == "index_footage.py"
             and e.get("status") == "failed"]
    assert len(child) == 1, child
    assert child[0]["rc"] == "index_timeout", child[0]
    block = child[0][wd.WATCHDOG_KEY]
    assert block["killed"] and block["code"] == "index_timeout", block
    assert block["source"] == "PEiDNOQ_0ms", block
    assert block["ceiling_s"] == 2.0 and block["silent_s"] >= 2, block

    # ... and read back out of the finished run: which source, how long it hung
    rows = wd.detect(batch)
    assert len(rows) == 1, rows
    assert rows[0]["source"] == "PEiDNOQ_0ms", rows[0]
    assert rows[0]["code"] == "index_timeout", rows[0]
    assert rows[0]["silent_s"] >= 2 and rows[0]["ceiling_s"] == 2.0, rows[0]
    assert rows[0]["attempt_spent"] is False, rows[0]
    assert "index_timeout" in (wd.headline(rows) or ""), wd.headline(rows)


def test_a_half_written_index_left_by_a_killed_child_is_removed():
    """The same rule CF-0281 has for a crash: a file that is not an index must
    not be read as a cache hit by the next run."""
    path = cf281.media("halfway")
    dest = ib.shots_path(path)
    dest.write_text('{"shots": [')                      # what a killed write leaves
    out = subprocess.CompletedProcess([], wd.RC_TIMEOUT, "", "")
    out.timed_out, out.timeout_code, out.silent_s = True, "index_timeout", 1861.0
    real, ib._run_index = ib._run_index, lambda p: out
    try:
        try:
            ib.index_source(str(path))
            raise AssertionError("a kill must not read as a success")
        except ib.IndexTimedOut:
            pass
    finally:
        ib._run_index = real
    assert not dest.exists(), "the half-written index is still there"


# ---------------------------------------------------------------------------
# 3. the run is never dropped, and the attempt is not spent


def test_the_stage_goes_on_to_the_next_source_after_a_kill():
    (fetched, _, skipped, failed, by_topic), out, _ = cf281.run(
        [cf281.topic("001", ["killed", "bbb", "ccc"])], killed_index("killed"))
    assert by_topic["001"] == ["bbb", "ccc"], by_topic     # the run went on
    assert skipped == [], skipped                          # no topic was lost
    rec = cf281.one(failed, "killed")
    assert rec["reason_code"] == ib.INDEX_FUNNEL_CODE, rec
    assert rec["refused_at"] == ib.RUNG_INDEX, rec
    assert rec[ib.WATCHDOG_CODE_KEY] == "index_timeout", rec
    assert rec["silent_s"] == 1861.0, rec
    assert rec["attempt_spent"] is False, rec
    assert "WATCHDOG killed" in out, out                   # the line in the log


def test_a_kill_does_not_spend_the_topics_attempt():
    """The CF-0302 shape: a candidate the factory itself refused costs nothing.

    Two attempts allowed, three candidates, the first one taken down. With the
    attempt spent the topic ends with one source (the bug); with it given back
    it reaches the CF-0129 floor of two.
    """
    (_, _, skipped, failed, by_topic), _, _ = cf281.run(
        [cf281.topic("001", ["killed", "bbb", "ccc"])], killed_index("killed"),
        max_per_topic=2, wanted=2, depth_floor=None)
    assert by_topic["001"] == ["bbb", "ccc"], by_topic
    assert skipped == [], skipped
    assert [f["video_id"] for f in failed] == ["killed"], failed


def test_an_ordinary_index_failure_still_spends_it():
    """The refund is the kill's alone - CF-0281's own path is untouched."""
    (_, _, skipped, failed, by_topic), _, _ = cf281.run(
        [cf281.topic("001", ["aaa", "bbb", "ccc"])], cf281.boom("aaa"),
        max_per_topic=2, wanted=2, depth_floor=None)
    assert by_topic["001"] == ["bbb"], by_topic
    assert len(skipped) == 1, skipped
    assert ib.WATCHDOG_CODE_KEY not in cf281.one(failed, "aaa"), failed


# ---------------------------------------------------------------------------
# 4. the statistics, and the funnel that must not learn the word


def test_the_kill_is_in_the_reports_index_failures_with_its_code():
    (_, _, _, failed, _), _, _ = cf281.run(
        [cf281.topic("001", ["killed", "bbb", "ccc"])], killed_index("killed"))
    rows = ib.index_failures(failed)
    mine = [r for r in rows if r["video_id"] == "killed"]
    assert len(mine) == 1, rows
    assert mine[0][ib.WATCHDOG_CODE_KEY] == "index_timeout", mine[0]
    assert mine[0]["silent_s"] == 1861.0, mine[0]
    assert mine[0]["attempt_spent"] is False, mine[0]
    assert mine[0]["reason_code"] == "index_failed", mine[0]


def test_the_operators_line_names_the_source_and_the_silence():
    (_, _, _, failed, _), _, _ = cf281.run(
        [cf281.topic("001", ["killed", "bbb", "ccc"])], killed_index("killed"))
    line = ib.timeout_summary(ib.index_failures(failed))
    assert "killed (001, index_timeout, quiet 1861s)" in line, line
    assert "no attempt spent" in line and "CF-0319" in line, line
    # and nothing at all when nothing was taken down
    (_, _, _, ordinary, _), _, _ = cf281.run(
        [cf281.topic("002", ["aaa", "bbb"])], cf281.boom("aaa"))
    assert ib.timeout_summary(ib.index_failures(ordinary)) is None


def test_the_outcome_code_is_not_a_funnel_word():
    """CF-0319: a kill is an авария - always a task, never a funnel number."""
    assert wd.outcome_code(step="index") == "index_timeout"
    for code in ("index_timeout", "fetch_timeout", "scenedetect_timeout"):
        assert code not in funnel.FUNNEL_CODES, code
    # ... while the record's own reason_code is a word the funnel knows
    assert ib.INDEX_FUNNEL_CODE in funnel.FUNNEL_CODES


# ---------------------------------------------------------------------------
# 5. the two other calls and their classes


def test_the_download_names_the_download_class():
    done = subprocess.CompletedProcess([], 0, "cached -> /tmp/x.mp4", "")
    with spying(ib, answer=done) as calls:
        got = ib.fetch_source("aaa", "batch x")
    assert got.path == "/tmp/x.mp4", got
    cmd, kw = calls[0]
    assert cmd[1].endswith("fetch_footage.py"), cmd
    assert kw["watchdog"] == "download", kw
    assert kw["video"] == "aaa" and kw["step"] == "fetch", kw
    assert "timeout" not in kw, kw
    assert wd.ceiling_for(kw["watchdog"]) == wd.DOWNLOAD_CEILING_S


def test_a_download_taken_down_is_a_lost_download_and_not_a_lost_run():
    out = subprocess.CompletedProcess([], wd.RC_TIMEOUT, "", "")
    out.timed_out, out.timeout_code = True, "fetch_timeout"
    with spying(ib, answer=out):
        try:
            ib.fetch_source("aaa", "batch x")
            raise AssertionError("a killed download must not read as a success")
        except RuntimeError as e:
            assert "fetch_timeout" in str(e), e
    # RuntimeError is the fetcher's own failure shape, which `attempt()` already
    # turns into a `fetch_failed` record and walks on from - the run stands.


def test_the_whole_file_scan_names_the_scan_class_with_the_sources_seconds():
    def answer(cmd, kw):
        return subprocess.CompletedProcess(cmd, 0, "", "pts_time:12.5\n")

    with spying(idx, answer=answer) as calls:
        cuts = idx.shot_boundaries("/tmp/src.mp4", 0.25, source_seconds=804.0)
    assert cuts == [12.5], cuts
    cmd, kw = calls[0]
    assert "select='gt(scene" in " ".join(cmd), cmd       # source-scenedetect
    assert kw["watchdog"] == "scan", kw
    assert kw["source_seconds"] == 804.0, kw
    assert "timeout" not in kw, kw
    assert wd.ceiling_for("scan", source_seconds=kw["source_seconds"]) == 804.0


def test_build_shots_hands_the_scan_the_length_it_just_measured():
    """The ceiling is this source's own seconds, so the number has to travel."""
    seen = {}

    def boundaries(path, threshold, source_seconds=None):
        seen["source_seconds"] = source_seconds
        return [10.0]

    saved = (idx.duration, idx.shot_boundaries)
    idx.duration, idx.shot_boundaries = (lambda p: 1234.5), boundaries
    try:
        shots = idx.build_shots("/tmp/src.mp4", 0.25, 60, split=False)
    finally:
        idx.duration, idx.shot_boundaries = saved
    assert seen["source_seconds"] == 1234.5, seen
    assert shots and shots[0]["start"] == 0.0, shots


if __name__ == "__main__":
    failures = ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)

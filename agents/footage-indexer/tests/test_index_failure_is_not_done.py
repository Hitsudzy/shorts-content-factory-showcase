#!/usr/bin/env python3
"""CF-0281: a source whose index did not get written is not a source.

The defect, on two real batches:

  * `example-film/2026-09-18T1058Z` - `index_footage.py` was killed twice at its
    own 60 s ceiling on `HEaXDIrGhS4` (`IDX ... failed HEaXDIrGhS4` in
    RUN_EVENTS.jsonl, both runs), and the per-source event `ingest_batch.py`
    had opened around it closed as **`done`** all the same: `subprocess.run()`
    in `index_source()` never looked at the return code. The id stayed in
    `fetched[]` and in `sources_by_topic[]`, so the topic read as holding two
    sources while one of them had no `shots.json` at all. The stage operator
    found it by hand, fetched a third candidate himself, and wrote the
    `index_failures[]` block into `01b-footage-index.json` with a pen.
  * `example-film/2026-09-19T0116Z` - the machine went down inside the index of
    `PEiDNOQ_0ms` (an `index` `start` at 08:41:26 with no terminal event), and
    on 2026-09-20 the source was indexed again from scratch.

Both shapes come to the same thing for DoD 1.4.4 item 2: the pool quietly
thins, a topic that holds one usable source counts as two, and the two-source
gate (CF-0129) is measuring a number that is not there.

What is pinned here, all of it offline - no ffmpeg, no CLIP, no network:

  - an index that fails leaves the id out of `fetched[]`, out of
    `sources_by_topic[]` and out of the topic's canonical fingerprint list;
  - it is recorded instead - in `failed[]` with `reason_code: index_failed`
    and `refused_at: index`, and in the report's `index_failures[]` block;
  - the per-source `ingest` event says `failed`, not `done`, and carries the
    error line;
  - the CF-0129 walk goes on to the topic's next candidate by itself, and the
    replacement is named in the record (`replaced_by`), which is what the
    operator did with a pen on 2026-09-18;
  - a topic the index failures leave below the floor is refused with a
    sentence that says "downloaded but failed to index" rather than "failed to
    fetch" - the two are not the same fault and only one of them is YouTube's -
    and, since the funnel learned the code (CF-0281b), a topic that got
    nothing takes `index_failed` when every candidate was lost that way and
    keeps `fetch_failed` when any of them was a download YouTube refused;
  - a half-written `shots.json` is not a cache hit: `shot_schema` refuses it,
    the file is removed, and the source is indexed again.

No pytest dependency - plain asserts, run directly.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0281-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")   # never touch ~/.shorts-content-factory
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from _runlog import runlog  # noqa: E402
import ingest_batch as ib  # noqa: E402


def no_measure(vid, record=None):
    """CF-0302: the duration ceiling's measurement seam, injected away.

    `ingest()` reads how long a candidate is before it downloads it, and the
    real reader asks YouTube. Nothing in this file is about that ceiling, so
    the answer here is "nobody could tell" - which is never a refusal - and no
    request is made.
    """
    return ib.Measured(None, "metadata", "not measured in this test")

import shot_schema  # noqa: E402

STAGE = "footage-indexer"


# ---------------------------------------------------------------------------
# the offline stand-ins: a fetcher that always succeeds and a fingerprint that
# is the name of the cut, the way test_two_sources_per_topic.py does it.

class Cuts:
    """source_fingerprint with the ffmpeg taken out: two uploads are the same
    source when they carry the same cut name."""

    @staticmethod
    def compare(a, b):
        return {"distance": 0 if a["cut"] == b["cut"] else 40,
                "offset_seconds": 0.0, "overlap_frames": 8}

    @staticmethod
    def is_duplicate(cmp):
        return cmp["distance"] <= 12


def media(vid):
    """A stand-in media file inside this test's own temp dir - nothing under
    shared/footage/ is read or written by this file."""
    p = TMP / "cache" / f"{vid}.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(b"\x00")
    return p


def fetch_ok(vid, note):
    return ib.FetchResult(str(media(vid)), False)


def fingerprint_of(path):
    # every id is its own cut unless the test says otherwise
    return {"kind": "dhash", "cut": Path(path).stem}


def topic(tid, ids):
    return {"topic_id": tid, "evidence": {"youtube_video_ids": list(ids)}}


def run(topics, index, fetch=fetch_ok, fingerprint=fingerprint_of, **kw):
    """ingest() with the fingerprint, the waiting and the cache injected away."""
    out, err = io.StringIO(), io.StringIO()
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            kw.setdefault("measure", no_measure)   # CF-0302, no network
            result = ib.ingest(topics, {}, "batch-x", skip_index=False,
                               fetch=fetch, index=index, fingerprint=fingerprint,
                               sleep=lambda s: None, pause=0,
                               is_cached=lambda vid: False, **kw)
    finally:
        ib.source_fingerprint = real
    return result, out.getvalue(), err.getvalue()


def boom(*bad):
    """An `index` that refuses the named ids the way index_source() does."""
    bad = set(bad)

    def index(path):
        vid = Path(path).stem
        if vid in bad:
            raise ib.IndexFailed(
                f"index_footage.py left no usable index for {vid}: exit 1 - "
                f"ffmpeg: no result within the 60 s ceiling")
    return index


def gone(*bad):
    """A `fetch` that loses the named ids the way yt-dlp does - the other half
    of `failed[]`, so a test can mix the two causes in one topic."""
    bad = set(bad)

    def fetch(vid, note):
        if vid in bad:
            raise RuntimeError(f"yt-dlp: {vid} is unavailable")
        return fetch_ok(vid, note)
    return fetch


def one(records, vid):
    hits = [r for r in records if r.get("video_id") == vid]
    assert len(hits) == 1, hits
    return hits[0]


# ---------------------------------------------------------------------------
# the source

def test_a_source_whose_index_failed_is_not_in_fetched():
    (fetched, aliases, skipped, failed, by_topic), _, _ = run(
        [topic("001", ["aaa", "bbb"])], boom("bbb"), wanted=99)
    assert [f["video_id"] for f in fetched] == ["aaa"], fetched
    assert by_topic["001"] == ["aaa"], by_topic


def test_it_is_recorded_as_failed_with_its_own_code():
    (_, _, _, failed, _), _, _ = run([topic("001", ["aaa", "bbb"])],
                                     boom("bbb"), wanted=99)
    rec = one(failed, "bbb")
    assert rec["reason_code"] == ib.INDEX_FUNNEL_CODE == "index_failed", rec
    assert rec["refused_at"] == ib.RUNG_INDEX == "index", rec
    assert rec["topic_id"] == "001", rec
    # the funnel copies `error` into its detail verbatim, so it reads on its own
    assert "bbb" in rec["error"] and "index" in rec["error"].lower(), rec


def test_a_failed_index_does_not_hide_the_next_candidate_as_a_re_upload():
    """The fingerprint of a source that never got an index must not be in the
    topic's canonical list - otherwise the replacement it is compared against
    is a source that is not there."""
    def same_cut(path):
        return {"kind": "dhash", "cut": "one-and-the-same"}

    (fetched, aliases, _, _, by_topic), _, _ = run(
        [topic("001", ["aaa", "bbb"])], boom("aaa"),
        fingerprint=same_cut, wanted=99)
    assert [f["video_id"] for f in fetched] == ["bbb"], fetched
    assert aliases == [], aliases          # bbb is not an alias of a phantom
    assert by_topic["001"] == ["bbb"], by_topic


# ---------------------------------------------------------------------------
# the event

def test_the_per_source_event_says_failed_not_done():
    batch = TMP / "events"
    batch.mkdir(parents=True, exist_ok=True)
    saved = os.environ.get("RUNLOG_BATCH")
    os.environ["RUNLOG_BATCH"] = str(batch)
    try:
        with runlog.run(STAGE, "ingest", name="ingest_batch.py") as outer:
            run([topic("001", ["aaa", "bbb"])], boom("bbb"), wanted=99)
    finally:
        if saved is None:
            os.environ.pop("RUNLOG_BATCH", None)
        else:
            os.environ["RUNLOG_BATCH"] = saved

    events = [json.loads(l) for l in
              (batch / "RUN_EVENTS.jsonl").read_text().splitlines() if l.strip()]
    inner = [e for e in events if e.get("parent") == outer["id"]
             and e.get("kind") == "script"]
    status = {(e["video"], e["status"]) for e in inner}
    assert ("aaa", "done") in status, inner
    assert ("bbb", "failed") in status, inner
    assert ("bbb", "done") not in status, inner
    bad = [e for e in inner if e["video"] == "bbb" and e["status"] == "failed"]
    assert bad and bad[0].get("error"), bad
    assert (bad[0].get("params") or {}).get("index_failed"), bad


# ---------------------------------------------------------------------------
# the walk (CF-0129)

def test_the_walk_takes_the_next_candidate_by_itself():
    """2026-09-18: the operator fetched 80rOmETggNk by hand because the stage
    had already called the topic done. The ladder does it now."""
    (fetched, _, skipped, failed, by_topic), out, _ = run(
        [topic("001", ["aaa", "bbb", "ccc"])], boom("bbb"))
    assert by_topic["001"] == ["aaa", "ccc"], by_topic
    assert skipped == [], skipped                 # the floor is met, no refusal
    assert one(failed, "bbb")["replaced_by"] == ["ccc"], failed


def test_the_attempt_cap_still_bounds_the_topic():
    (fetched, _, skipped, failed, by_topic), _, _ = run(
        [topic("001", ["a1", "a2", "a3", "a4", "a5"])], boom("a1", "a2", "a3", "a4"))
    assert by_topic["001"] == [], by_topic
    assert len(failed) == ib.MAX_ATTEMPTS_PER_TOPIC, failed
    assert "a5" not in [f["video_id"] for f in failed], failed


def test_a_topic_left_short_says_index_not_fetch():
    """Nothing but index failures: the code is ours, not YouTube's.

    CF-0281b - the funnel now owns `index_failed` (shared/runlog/funnel.py
    FUNNEL_CODES), so the record no longer has to borrow the word for a
    refused download.
    """
    (_, _, skipped, failed, by_topic), _, _ = run(
        [topic("001", ["aaa", "bbb"])], boom("aaa", "bbb"))
    assert len(skipped) == 1, skipped
    rec = skipped[0]
    assert rec["reason_code"] == ib.INDEX_FUNNEL_CODE == "index_failed", rec
    assert "failed to index" in rec["reason"], rec
    assert "failed to fetch" not in rec["reason"], rec
    assert rec["index_failed"] == ["aaa", "bbb"], rec
    assert rec["failed"] == [], rec


def test_a_topic_that_only_lost_downloads_still_says_fetch():
    """The other pure form: nothing came down, so nothing is ours to fix."""
    (_, _, skipped, _, _), _, _ = run(
        [topic("001", ["aaa", "bbb"])], boom(), fetch=gone("aaa", "bbb"))
    assert len(skipped) == 1, skipped
    rec = skipped[0]
    assert rec["reason_code"] == ib.FUNNEL_REASON_CODE == "fetch_failed", rec
    assert rec["failed"] == ["aaa", "bbb"], rec
    assert rec["index_failed"] == [], rec
    assert "failed to index" not in rec["reason"], rec


def test_a_mixed_loss_keeps_the_fetch_code_and_names_both():
    """One of each: the code names how the topic left - and a loss that was
    partly YouTube's is never rounded down to our half of it - while the
    sentence still names both causes, which is the funnel's rule too."""
    (_, _, skipped, _, _), _, _ = run(
        [topic("001", ["aaa", "bbb"])], boom("aaa"), fetch=gone("bbb"))
    assert len(skipped) == 1, skipped
    rec = skipped[0]
    assert rec["reason_code"] == ib.FUNNEL_REASON_CODE == "fetch_failed", rec
    assert rec["failed"] == ["bbb"], rec
    assert rec["index_failed"] == ["aaa"], rec
    assert "failed to fetch" in rec["reason"], rec
    assert "failed to index" in rec["reason"], rec


def test_one_indexed_source_is_still_a_no_second_source_refusal():
    (_, _, skipped, _, by_topic), _, _ = run(
        [topic("001", ["aaa", "bbb"])], boom("bbb"))
    assert by_topic["001"] == ["aaa"], by_topic
    assert len(skipped) == 1 and skipped[0]["reason_code"] == "no_second_source", skipped
    assert "failed to index" in skipped[0]["reason"], skipped


# ---------------------------------------------------------------------------
# the report

def test_the_report_carries_an_index_failures_block():
    (fetched, aliases, skipped, failed, by_topic), _, _ = run(
        [topic("001", ["aaa", "bbb", "ccc"])], boom("bbb"))
    report = ib.build_report("b", fetched, aliases, skipped, failed, by_topic)
    rows = report["index_failures"]
    assert isinstance(rows, list) and len(rows) == 1, rows
    row = rows[0]
    # the four keys the CF-0232 funnel reads out of any record of a loss, the
    # same ones the operator wrote by hand on 2026-09-18
    for key in ("topic_id", "video_id", "reason_code", "stage", "reason"):
        assert row.get(key), (key, row)
    assert row["reason_code"] == "index_failed" and row["stage"] == STAGE, row
    assert row["replaced_by"] == ["ccc"], row
    # and a batch where nothing failed to index says so rather than staying silent
    clean = ib.build_report("b", fetched, aliases, [], [], by_topic)
    assert clean["index_failures"] == [], clean["index_failures"]


def test_the_cli_prints_the_index_failures():
    src = (SCRIPTS / "ingest_batch.py").read_text()
    assert "INDEX_FAILURES_LINE" in src, "the stage must say it on stdout too"


# ---------------------------------------------------------------------------
# the half-written index (the 2026-09-19 shape)

def written(vid, shots=2, truncate=False, blank=False):
    """A shots.json beside a stand-in media file, whole or cut off mid-write."""
    p = media(vid)
    dest = p.with_suffix(".shots.json")
    index = {"source": str(p), "model": "m", "shots": [
        {"index": i, "start": float(i), "end": float(i) + 1.0,
         "embedding": [0.1], "description": "", "tile_at": float(i) + 0.5}
        for i in range(0 if blank else shots)]}
    text = json.dumps(index, indent=2)
    dest.write_text(text[:len(text) // 2] if truncate else text)
    return dest


def test_shot_schema_refuses_a_half_written_index():
    whole = written("whole")
    cut = written("cut", truncate=True)
    missing = media("never").with_suffix(".shots.json")
    if missing.exists():
        missing.unlink()
    assert shot_schema.file_problems(whole) == [], shot_schema.file_problems(whole)
    assert shot_schema.is_complete(whole)
    assert not shot_schema.is_complete(cut), "a truncated index must not read as one"
    assert not shot_schema.is_complete(missing)
    assert not shot_schema.is_complete(written("empty", blank=True)), \
        "an index with no shots backs no phrase and is not a source"
    # the reason is a sentence, not a bool - it lands in the refusal
    assert "cut.shots.json" in shot_schema.file_problems(cut)[0]


def test_an_index_written_before_tile_at_is_still_whole():
    """Every index on disk from before CF-0106/CF-0105 carries neither
    `tile_at` nor `split_stats` nor `fingerprint`. Those are optional and must
    not turn the pool into a pool of broken indexes."""
    p = media("old")
    dest = p.with_suffix(".shots.json")
    dest.write_text(json.dumps({"source": str(p), "model": "m", "shots": [
        {"index": 0, "start": 0.0, "end": 1.0, "embedding": [0.1],
         "is_card": False, "description": ""}]}))
    assert shot_schema.file_problems(dest) == [], shot_schema.file_problems(dest)


def test_a_half_written_index_is_not_a_cache_hit():
    dest = written("half", truncate=True)
    seen = []
    (fetched, _, _, _, by_topic), out, _ = run(
        [topic("001", ["half", "whole2"])], seen.append, wanted=99)
    assert str(media("half")) in seen, "the half-written index must be re-indexed"
    assert not dest.exists(), "and the file that is not an index must be gone"
    assert "PARTIAL half" in out, out


def test_a_whole_index_still_is_a_cache_hit():
    written("hit")
    seen = []
    run([topic("001", ["hit"])], seen.append, wanted=99)
    assert seen == [], seen


# ---------------------------------------------------------------------------
# index_source() itself: the seam where main swallowed the return code

class Ran:
    """A stand-in for the index_footage.py subprocess."""

    def __init__(self, rc, stderr="", writes=None):
        self.rc, self.stderr, self.writes = rc, stderr, writes

    def __call__(self, path):
        import subprocess
        if self.writes is not None:
            Path(path).with_suffix(".shots.json").write_text(self.writes)
        return subprocess.CompletedProcess([], self.rc, "", self.stderr)


@contextlib.contextmanager
def runner(ran):
    real, ib._run_index = ib._run_index, ran
    try:
        yield
    finally:
        ib._run_index = real


def index_source_of(vid, ran):
    with runner(ran):
        try:
            ib.index_source(str(media(vid)))
            return None
        except ib.IndexFailed as e:
            return str(e)


def test_index_source_refuses_a_non_zero_exit():
    """The 2026-09-18 shape: killed at its own 60 s ceiling, nothing written."""
    why = index_source_of("rc1", Ran(1, "ffmpeg: no result within the 60 s ceiling"))
    assert why and "exit 1" in why, why
    assert "60 s ceiling" in why, why          # the indexer's own last word is kept


def test_index_source_refuses_an_exit_zero_that_wrote_nothing():
    why = index_source_of("silent", Ran(0))
    assert why and "no index file" in why, why


def test_index_source_removes_a_half_written_index_it_leaves_behind():
    dest = media("halfrc").with_suffix(".shots.json")
    why = index_source_of("halfrc", Ran(1, "killed", writes='{"source": "x", "sh'))
    assert why, why
    assert not dest.exists(), "a file that is not an index must not survive the refusal"


def test_index_source_is_quiet_when_the_index_is_there():
    assert index_source_of("good", Ran(0, writes=json.dumps(
        {"source": "x", "model": "m",
         "shots": [{"index": 0, "start": 0.0, "end": 1.0}]}))) is None


def test_the_writer_is_atomic():
    """CF-0281: the 2026-09-19 shape is a process killed mid-write. Nothing may
    ever observe a half-written shots.json, so the index is written to a
    neighbour and renamed."""
    dest = TMP / "atomic" / "x.shots.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shot_schema.write_index(dest, {"source": "x", "model": "m", "shots": [
        {"index": 0, "start": 0.0, "end": 1.0}]})
    assert json.load(open(dest))["shots"][0]["index"] == 0
    assert list(dest.parent.iterdir()) == [dest], "no temp file left behind"
    src = (SCRIPTS / "index_footage.py").read_text()
    assert "shot_schema.write_index(" in src, "index_footage.py must write through it"
    assert "json.dump(index, open(dest" not in src, "the unguarded write is gone"


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

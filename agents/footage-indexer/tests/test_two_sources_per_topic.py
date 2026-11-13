#!/usr/bin/env python3
"""CF-0129: two canonical sources per topic, four attempts at most, and the
topic refused here rather than at the gate.

The measurement that started it (CF-0118, 2026-09-07): of 13 videos with
footage, 5 passed the two-source gate; in batch 2026-09-03T2037Z, 0 of 4,
because each topic's "three sources" were three re-uploads of one teaser that
CF-0080 collapses into one (GyEpwGQIEZw / SJVmeJaS44s, distance 1.82). The
gate is switched to `enforce` in the root, so the guarantee has to be made
here, on the way in: a topic that will hold one source must be dropped before
a script, a TTS pass and an anchor resolve are spent on it.

What is pinned here, all of it offline - a fake fetcher and a fingerprint
that is just the name of the cut an upload carries (CF-0080's rule with the
ffmpeg taken out):

  - the floor and the cap, and the CLI's defaults for them;
  - the walk takes candidates in Trend Hunter's order and stops at two
    canonical sources - the third candidate is not downloaded;
  - independence is by the fingerprint, not by video_id: a re-upload costs an
    attempt, does not count, and the walk goes on to the next candidate;
  - the cap: four distinct videos per topic, never a fifth, however many
    candidates are left;
  - the refusal: `skipped_topics[]` in the CF-0232 funnel's shape, with
    `no_second_source` (and `fetch_failed` / `no_source` for a topic that got
    nothing), a `reason` that reads on its own, and the report's
    `two_source_floor` block;
  - a `same_cut` re-upload stands in for a candidate that is not there;
  - batches written before 2026-09-16 have no `footage_candidates` /
    `footage_candidate_shortfall`: they still walk, and a one-candidate topic
    is refused rather than crashing the stage.

No pytest dependency - plain asserts, run directly.
"""
import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest_batch as ib           # noqa: E402


def no_measure(vid, record=None):
    """CF-0302: the duration ceiling's measurement seam, injected away.

    `ingest()` reads how long a candidate is before it downloads it, and the
    real reader asks YouTube. Nothing in this file is about that ceiling, so
    the answer here is "nobody could tell" - which is never a refusal - and no
    request is made.
    """
    return ib.Measured(None, "metadata", "not measured in this test")


from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0129-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")

GONE = "ERROR: [youtube] {vid}: Video unavailable"

# id -> the cut it carries. Two ids of the same cut are one source, which is
# what the CF-0080 fingerprint decides on real media.
CUTS = {}


class Cuts:
    """A stand-in for source_fingerprint: the distance is 0 within a cut and
    far outside it, so `is_duplicate` answers exactly as it does on the real
    fingerprints of batch 2026-09-03T2037Z."""

    @staticmethod
    def compare(a, b):
        same = a["cut"] == b["cut"]
        return {"distance": 0.0 if same else 30.0, "offset_seconds": 0.0,
                "overlap_frames": 120, "kind": "cut"}

    @staticmethod
    def is_duplicate(cmp):
        return cmp["distance"] <= 12


def fingerprint(path):
    vid = Path(path).stem
    return {"kind": "cut", "cut": CUTS.get(vid, vid)}


def topic(tid, ids, candidates=None, shortfall=None):
    """Trend Hunter's topic shape. `candidates` is the post-2026-09-16
    `evidence.footage_candidates`; left out, the topic is an older batch's."""
    ev = {"youtube_video_ids": list(ids)}
    if candidates is not None:
        ev["footage_candidates"] = candidates
    if shortfall is not None:
        ev["footage_candidate_shortfall"] = shortfall
    return {"topic_id": tid, "evidence": ev}


class Fetcher:
    """A fake fetch_source. `gone` ids are not there at all (a real per-video
    failure)."""

    def __init__(self, gone=()):
        self.gone = set(gone)
        self.calls = []

    def __call__(self, vid, note):
        self.calls.append((vid, None))
        if vid in self.gone:
            raise RuntimeError(GONE.format(vid=vid))
        return ib.FetchResult(f"/tmp/{vid}.mp4", False)

    @property
    def ids(self):
        """The distinct videos this topic touched, in order of first request."""
        out = []
        for vid, _ in self.calls:
            if vid not in out:
                out.append(vid)
        return out


def run(fetcher, topics, verdict=None, **kw):
    """ingest() with the fingerprint, the waiting and the cache injected away.

    Returns (result, stdout). The real `source_fingerprint` module is swapped
    for `Cuts` - ingest() reaches
    into the module for `compare` / `is_duplicate`.
    """
    def sleep(seconds):
        pass

    out, err = io.StringIO(), io.StringIO()
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with redirect_stdout(out), redirect_stderr(err):
            kw.setdefault("measure", no_measure)   # CF-0302, no network
            result = ib.ingest(topics, verdict or {}, "batch-x", skip_index=True,
                               fetch=fetcher, index=lambda p: None,
                               fingerprint=fingerprint,
                               sleep=sleep, pause=0, is_cached=lambda vid: False,
                               **kw)
    finally:
        ib.source_fingerprint = real
    return result, out.getvalue()


def refusal(skipped, tid):
    recs = [s for s in skipped if s["topic_id"] == tid]
    assert len(recs) == 1, recs
    return recs[0]


# ---------------------------------------------------------------------------
# The numbers

def test_the_floor_and_the_cap_are_the_task_s_two_and_four():
    assert ib.SOURCES_WANTED == 2            # shared/runlog/funnel.TWO_SOURCE_FLOOR
    assert ib.MAX_ATTEMPTS_PER_TOPIC == 4
    assert ib.TOPIC_REFUSAL_CODE == "no_second_source"


def test_the_cli_defaults_to_them():
    import argparse
    src = (SCRIPTS / "ingest_batch.py").read_text()
    assert "default=MAX_ATTEMPTS_PER_TOPIC" in src
    assert "default=SOURCES_WANTED" in src
    # and the pair is actually parsed under those names
    p = argparse.ArgumentParser()
    p.add_argument("batch")
    p.add_argument("--max-per-topic", type=int, default=ib.MAX_ATTEMPTS_PER_TOPIC)
    p.add_argument("--sources-wanted", type=int, default=ib.SOURCES_WANTED)
    a = p.parse_args(["b"])
    assert (a.max_per_topic, a.sources_wanted) == (4, 2)


# ---------------------------------------------------------------------------
# The walk

def test_the_walk_stops_at_two_canonical_sources():
    f = Fetcher()
    (fetched, aliases, skipped, failed, by_topic), _ = run(
        f, [topic("001", ["v1", "v2", "v3", "v4"])])
    assert f.ids == ["v1", "v2"]                  # v3, v4 never downloaded
    assert by_topic == {"001": ["v1", "v2"]}
    assert not aliases and not failed and not skipped


def test_a_reupload_costs_an_attempt_does_not_count_and_the_walk_goes_on():
    """The 2026-09-03T2037Z shape: three uploads of one teaser, then a real
    second source. Independence is by the fingerprint, not by video_id."""
    CUTS.update({"t1": "teaser", "t2": "teaser", "t3": "teaser", "iv": "interview"})
    f = Fetcher()
    (fetched, aliases, skipped, failed, by_topic), out = run(
        f, [topic("001", ["t1", "t2", "t3", "iv"])])
    assert f.ids == ["t1", "t2", "t3", "iv"]
    assert by_topic == {"001": ["t1", "iv"]}      # two sources, not four
    assert [a["video_id"] for a in aliases] == ["t2", "t3"]
    assert all(a["alias_of"] == "t1" for a in aliases)
    assert "DEDUP t2 is a re-upload of t1" in out
    assert not skipped and not failed


def test_the_cap_stops_a_topic_at_four_videos_however_many_candidates_are_left():
    """Four re-uploads of one cut and two more candidates behind them: the
    topic spends four attempts, never a fifth video, and is refused."""
    CUTS.update({f"u{i}": "teaser" for i in range(1, 5)})
    f = Fetcher()
    (fetched, aliases, skipped, failed, by_topic), out = run(
        f, [topic("001", ["u1", "u2", "u3", "u4", "u5", "u6"])])
    assert f.ids == ["u1", "u2", "u3", "u4"]
    assert by_topic == {"001": ["u1"]} and len(aliases) == 3
    rec = refusal(skipped, "001")
    assert rec["reason_code"] == "no_second_source"
    assert rec["attempts"] == 4 and rec["unused"] == ["u5", "u6"]
    assert "4-attempt cap" in rec["reason"] and "u5, u6" in rec["reason"]
    assert ib.TOPIC_REFUSED_LINE.format(tid="001", reason=rec["reason"]) in out


def test_every_topic_walks_on_its_own():
    CUTS.update({"a1": "trailer", "a2": "trailer"})
    f = Fetcher()
    (fetched, _, skipped, _, by_topic), _ = run(
        f, [topic("001", ["a1", "a2"]), topic("002", ["b1", "b2", "b3"])])
    assert by_topic == {"001": ["a1"], "002": ["b1", "b2"]}
    assert [s["topic_id"] for s in skipped] == ["001"]
    assert f.ids == ["a1", "a2", "b1", "b2"]      # 002 stops at two, like 001's cap


# ---------------------------------------------------------------------------
# same_cut: a stand-in, never a second source

def test_a_same_cut_reupload_stands_in_for_a_candidate_that_is_not_there():
    CUTS.update({"g1": "trailer", "g1b": "trailer"})
    cands = [{"video_id": "g1", "kind": "trailer", "nature": "trailer",
              "same_cut": ["g1b"]},
             {"video_id": "iv2", "kind": "interview", "nature": "interview",
              "same_cut": []}]
    f = Fetcher(gone=["g1"])
    (fetched, aliases, skipped, failed, by_topic), _ = run(
        f, [topic("001", ["g1", "iv2"], candidates=cands)])
    assert f.ids == ["g1", "g1b", "iv2"]          # the stand-in goes in g1's place
    assert by_topic == {"001": ["g1b", "iv2"]}
    assert [r["video_id"] for r in failed] == ["g1"] and not skipped
    # a real per-video failure keeps yt-dlp's own line, verbatim
    assert failed[0]["error"] == GONE.format(vid="g1")
    assert failed[0]["refused_at"] == ib.RUNG_FIRST_PASS


# ---------------------------------------------------------------------------
# The refusal record, and the report

def test_the_refusal_has_the_funnel_s_four_keys_and_a_reason_that_reads_alone():
    CUTS.update({"k1": "teaser", "k2": "teaser"})
    f = Fetcher()
    (fetched, aliases, skipped, failed, by_topic), _ = run(
        f, [topic("001", ["k1", "k2"],
                  shortfall={"wanted": 3, "found": 2, "natures": ["trailer"],
                             "reason": "only one nature of footage found"})])
    rec = refusal(skipped, "001")
    assert set(rec) >= {"topic_id", "reason_code", "reason", "stage"}
    assert rec["stage"] == "footage-indexer"      # the funnel's `stage`, like part 1's
    assert rec["reason_code"] == ib.TOPIC_REFUSAL_CODE
    r = rec["reason"]
    assert "1 canonical source" in r and "floor is 2" in r and "CF-0129" in r
    assert "CF-0080" in r and "re-upload" in r and "k2" in r
    assert "only one nature of footage found" in r        # Trend Hunter knew
    assert rec["sources"] == ["k1"] and rec["aliased"] == ["k2"]
    assert rec["candidate_shortfall"]["found"] == 2


def test_a_topic_with_no_candidates_at_all_says_so():
    f = Fetcher()
    (_, _, skipped, failed, by_topic), _ = run(f, [topic("001", [])])
    rec = refusal(skipped, "001")
    assert rec["reason_code"] == "no_source" and rec["attempts"] == 0
    assert "no candidate video to fetch" in rec["reason"]
    assert not f.calls and not failed


def test_the_report_carries_the_records_and_the_floor_block():
    CUTS.update({"m1": "teaser", "m2": "teaser"})
    f = Fetcher()
    (fetched, aliases, skipped, failed, by_topic), _ = run(
        f, [topic("001", ["m1", "m2"]), topic("002", ["n1", "n2"])])
    report = ib.build_report(TMP / "batch", fetched, aliases, skipped, failed,
                             by_topic)
    assert [s["topic_id"] for s in report["skipped_topics"]] == ["001"]
    assert report["skipped_topics"][0]["reason_code"] == "no_second_source"
    floor = report["two_source_floor"]
    assert floor["wanted"] == 2 and floor["max_attempts_per_topic"] == 4
    assert floor["refused"] == ["001"]
    assert "CF-0129" in floor["note"] and "Content Researcher" in floor["note"]
    # the report is JSON, records and all
    json.loads(json.dumps(report))


def test_a_review_verdict_is_fetched_like_any_other():
    """CF-0318: the verdict holds the publication, not the production.

    Until 2026-09-23 this topic was dropped here with `compliance_review` and
    "not signed off" - and over ten instrumented runs that was 19 of 101
    losses, in runs where no human was ever going to sign anything. The
    verdict itself is untouched, and so is what it means legally; what it
    blocks moved to the end of the pipeline, where `publication_hold` and
    `publish/publication-holds.json` (agents/compliance-checker) stop the
    Publisher. Here it buys nothing and costs a video, so it does nothing.
    """
    f = Fetcher()
    (fetched, _, skipped, _, by_topic), _ = run(
        f, [topic("001", ["v1", "v2"])], verdict={"001": "review"})
    assert by_topic["001"] == ["v1", "v2"] and len(fetched) == 2
    assert skipped == []                 # not a refusal, not a skip, no record


def test_the_historical_compliance_code_cannot_be_written_again():
    """CF-0318: `compliance_review` is read out of old reports and never
    written. The guard is in `topic_skip()`, the one place a topic record is
    built, so "no new record carries it" is a fact of the code."""
    assert ib.COMPLIANCE_SKIP_CODE == "compliance_review"
    assert ib.COMPLIANCE_SKIP_CODE in ib.PRE_FETCH_CODES     # old reports
    try:
        ib.topic_skip("001", ib.COMPLIANCE_SKIP_CODE, "not signed off")
    except ValueError as e:
        assert "CF-0318" in str(e) and "publication-holds.json" in str(e)
    else:
        raise AssertionError("topic_skip wrote the historical code")


# ---------------------------------------------------------------------------
# Batches written before 2026-09-16

def test_an_old_batch_without_the_new_evidence_fields_still_walks():
    """`footage_candidates` / `footage_candidate_shortfall` are part 1's, from
    2026-09-16. A topic without them says nothing about its candidates, which
    is not the same as saying there are none: the ids are walked as they are."""
    old = {"topic_id": "001", "evidence": {"youtube_video_ids": ["o1", "o2", "o3"]}}
    f = Fetcher()
    (fetched, _, skipped, failed, by_topic), _ = run(f, [old])
    assert by_topic == {"001": ["o1", "o2"]} and not skipped and not failed
    assert ib.candidate_records(old) == {}
    assert ib.walk_state(old)["shortfall"] is None


def test_an_old_batch_s_single_id_topic_is_refused_and_does_not_crash():
    """The 2026-09-09 shape - one evidence id per topic. It is refused, with a
    reason that says there was nothing else to try, and the stage carries on
    to the next topic."""
    f = Fetcher()
    (fetched, _, skipped, failed, by_topic), _ = run(
        f, [{"topic_id": "001", "evidence": {"youtube_video_ids": ["p1"]}},
            {"topic_id": "002", "evidence": {"youtube_video_ids": ["q1", "q2"]}}])
    assert by_topic == {"001": ["p1"], "002": ["q1", "q2"]}
    rec = refusal(skipped, "001")
    assert rec["reason_code"] == "no_second_source"
    assert "no other candidate to try" in rec["reason"]
    assert not failed


def test_evidence_that_is_not_the_shape_it_should_be_is_read_not_trusted():
    f = Fetcher()
    weird = [{"topic_id": "001"},                                   # no evidence
             {"topic_id": "002", "evidence": None},
             {"topic_id": "003", "evidence": {"youtube_video_ids": None}},
             {"topic_id": "004", "evidence": {"youtube_video_ids": ["r1", 7],
                                              "footage_candidates": "nope",
                                              "footage_candidate_shortfall": "nope"}}]
    (_, _, skipped, failed, by_topic), _ = run(f, weird)
    assert f.ids == ["r1"]
    assert [s["topic_id"] for s in skipped] == ["001", "002", "003", "004"]
    assert {s["reason_code"] for s in skipped} == {"no_source", "no_second_source"}
    assert refusal(skipped, "004")["candidate_shortfall"] is None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        CUTS.clear()
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

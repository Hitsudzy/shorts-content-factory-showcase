#!/usr/bin/env python3
"""CF-0265 (grill of 2026-09-17): the shortlist cut reaches the footage stage.

Compliance now judges a shortlist of up to 8 fact-probed topics and
`agents/compliance-checker/scripts/cut_shortlist.py` cuts it to the batch
target, writing `02-compliance-checker.json` as

    results[]  the topics that go on, in shortlist order, verdict records
               untouched - `review` among them since CF-0318;
    reserve[]  eligible topics with no slot, each carrying
               `reason_code: "reserve_unused"`;
    cut        the record of the cut itself.

Until this task `verdicts()` read `results[]` only and the first pass skipped
`review` alone, so a topic with no verdict at all - which after the cut is
every reserve topic - was downloaded: with a shortlist of 8 the stage would
have spent downloads, YouTube quota and ~19 min of indexing per source on
material nothing downstream ever opens.

What is pinned here, all of it offline (the fake fetcher of
test_two_sources_per_topic.py, no network, no yt-dlp, no CLIP):

  - a shortlist of 8 with 5 in `results[]` (one of them `review`) and 2 in
    `reserve[]`: all 5 carried topics are fetched - CF-0318, the verdict
    holds the publication and not the production - and the other three are
    three records with their own codes, nothing silent;
  - `reserve_unused` is compliance's own code, spelled the same on both
    sides, and its `reason` says it is neither a refusal of this stage nor a
    fault of the topic;
  - a topic in neither list is refused with the funnel's `not_screened`
    rather than fetched;
  - the two-source floor (CF-0129) still holds for the carried topics - the gate is a filter in front of the walk,
    not a change to it;
  - an old batch (`results[]` only, no `reserve` key, a row per topic)
    behaves exactly as it did before, and so does a batch whose compliance
    pass has not run at all.

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
TMP = tmp_root("cf0265-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")

GONE = "ERROR: [youtube] {vid}: Video unavailable"

SHORTLIST = [f"topic-2026-09-17-{n:03d}" for n in range(1, 9)]
# CF-0318: the cut carries five, and the one at `review` is carried with them.
# It used to be the odd one out here - `CARRIED` was the other four - and the
# whole point of the task is that it no longer is.
CARRIED = SHORTLIST[:5]
REVIEWED = SHORTLIST[2]
RESERVED = [SHORTLIST[5], SHORTLIST[6]]
UNJUDGED = SHORTLIST[7]


# ---------------------------------------------------------------------------
# The stand-ins: a fingerprint that is the name of the cut, and a fetcher

class Cuts:
    """test_two_sources_per_topic.py's stand-in for source_fingerprint: every
    id here carries its own cut, so no two candidates are ever duplicates."""

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
    return {"kind": "cut", "cut": vid}


class Fetcher:
    """A fake fetch_source. `gone` ids are not there at all."""

    def __init__(self, gone=()):
        self.gone = set(gone)
        self.calls = []

    def __call__(self, vid, note):
        self.calls.append(vid)
        if vid in self.gone:
            raise RuntimeError(GONE.format(vid=vid))
        return ib.FetchResult(f"/tmp/{vid}.mp4", False)

    @property
    def ids(self):
        out = []
        for vid in self.calls:
            if vid not in out:
                out.append(vid)
        return out


def topic(tid, ids):
    return {"topic_id": tid, "evidence": {"youtube_video_ids": list(ids)}}


def shortlist_topics(ids=SHORTLIST):
    """Two candidates per topic, ids derived from the topic id, so who was
    fetched can be read straight off the fetcher."""
    return [topic(t, [f"{t}-a", f"{t}-b"]) for t in ids]


def run(fetcher, topics, verdict=None, **kw):
    """ingest() with the fingerprint, the waiting and the cache injected away."""
    def sleep(seconds):
        pass

    out, err = io.StringIO(), io.StringIO()
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with redirect_stdout(out), redirect_stderr(err):
            kw.setdefault("measure", no_measure)   # CF-0302, no network
            result = ib.ingest(topics, verdict, "batch-x", skip_index=True,
                               fetch=fetcher, index=lambda p: None,
                               fingerprint=fingerprint, sleep=sleep, pause=0,
                               is_cached=lambda vid: False, **kw)
    finally:
        ib.source_fingerprint = real
    return result, out.getvalue()


# ---------------------------------------------------------------------------
# The artifact, written to disk the way compliance writes it

def verdict_row(tid, verdict="clear"):
    return {"topic_id": tid, "title": f"title of {tid}", "verdict": verdict,
            "risk": "low", "notes": "a whole verdict record, untouched by the cut"}


def write_batch(name, results, reserve=None, cut=True):
    """`02-compliance-checker.json` in a fresh batch dir; `reserve=None` is an
    old batch, written before the cut existed."""
    batch = TMP / name
    batch.mkdir(parents=True, exist_ok=True)
    doc = {"batch_id": name, "channel": "lf", "stage_checked": "trend-hunter",
           "checked_at": "2026-09-17T10:00:00Z", "results": results}
    if reserve is not None:
        doc["reserve"] = reserve
        if cut:
            doc["cut"] = {"task": "CF-0265", "target": 5, "target_from": "channel",
                          "shortlist_size": len(SHORTLIST), "reserve": len(reserve),
                          "reason_code": ib.RESERVE_SKIP_CODE}
    json.dump(doc, open(batch / "02-compliance-checker.json", "w"), indent=2)
    return batch


def cut_batch(name="2026-09-17T1000Z"):
    """The batch this task is about: 8 judged, 5 in results[] (one `review`),
    2 reserved, and one topic of the shortlist in neither list."""
    results = [verdict_row(t, "review" if t == REVIEWED else "clear")
               for t in SHORTLIST[:5]]
    reserve = []
    for t in RESERVED:
        row = verdict_row(t)
        row["reason_code"] = ib.RESERVE_SKIP_CODE
        row["reason"] = ("Eligible and unused: the first 5 eligible topic(s) "
                         "filled the batch. Not a refusal.")
        reserve.append(row)
    return write_batch(name, results, reserve)


def record(skipped, tid):
    recs = [s for s in skipped if s["topic_id"] == tid]
    assert len(recs) == 1, recs
    return recs[0]


# ---------------------------------------------------------------------------
# Reading the artifact

def test_verdicts_reads_both_lists_and_says_the_screening_ran():
    s = ib.verdicts(cut_batch())
    assert s.ran is True
    assert set(s.verdict) == set(SHORTLIST[:5])
    assert s.verdict[REVIEWED] == "review"
    assert s.reserve == frozenset(RESERVED)
    # The reserve is not folded into the verdicts: the two are different losses.
    assert not (set(s.verdict) & s.reserve)


def test_an_old_batch_without_the_reserve_key_reads_as_it_always_did():
    batch = write_batch("old", [verdict_row(t) for t in SHORTLIST[:3]],
                        reserve=None)
    s = ib.verdicts(batch)
    assert s.ran is True
    assert set(s.verdict) == set(SHORTLIST[:3])
    assert s.reserve == frozenset()


def test_an_empty_reserve_is_the_cut_having_reserved_nothing():
    batch = write_batch("empty-reserve", [verdict_row(t) for t in SHORTLIST[:5]],
                        reserve=[])
    s = ib.verdicts(batch)
    assert s.ran is True and s.reserve == frozenset()


def test_no_compliance_file_at_all_is_not_a_screening():
    batch = TMP / "unjudged"
    batch.mkdir(parents=True, exist_ok=True)
    s = ib.verdicts(batch)
    assert s == ib.Screening(ran=False, verdict={}, reserve=frozenset())


def test_a_bare_dict_is_read_the_way_it_always_was():
    """ingest() is called with the plain verdict dict in older tests: empty
    means 'nothing judged', non-empty means the screening named those topics."""
    assert ib.as_screening({}).ran is False
    assert ib.as_screening(None).ran is False
    s = ib.as_screening({"001": "review"})
    assert s.ran is True and s.verdict == {"001": "review"}
    assert s.reserve == frozenset()
    same = ib.Screening(ran=True, verdict={}, reserve=frozenset({"x"}))
    assert ib.as_screening(same) is same


# ---------------------------------------------------------------------------
# The acceptance case: 8 judged, 4 fetched

def test_only_the_carried_topics_of_a_shortlist_of_eight_are_fetched():
    f = Fetcher()
    fetched, _, skipped, failed, by_topic = run(
        f, shortlist_topics(), ib.verdicts(cut_batch()))[0]

    # Five topics carried, two sources each, and not one request for the rest.
    assert sorted(by_topic) == sorted(CARRIED)
    assert f.ids == [f"{t}-{s}" for t in CARRIED for s in ("a", "b")]
    for t in CARRIED:
        assert by_topic[t] == [f"{t}-a", f"{t}-b"]
    assert len(fetched) == 10 and not failed
    for t in RESERVED + [UNJUDGED]:
        assert not any(t in vid for vid in f.calls), t


def test_the_review_topic_is_walked_to_the_end_of_this_stage():
    """CF-0318, the acceptance case: a batch that has a `review` in it is
    replayed and the topic comes out of this stage with footage.

    Both halves matter. It is fetched - two sources, its own candidates, in
    the order the topic offered them - and it is *not* a record anywhere: not
    in `skipped_topics[]`, not under the floor's `refused`, not in the
    `compliance_gate` block, which no longer has a key for a verdict at all.
    A reader of `01b-footage-index.json` cannot tell this topic from a `clear`
    one, which is the point: what its verdict blocks is the publication, and
    that is held in publish/publication-holds.json by another stage.
    """
    f = Fetcher()
    result, _ = run(f, shortlist_topics(), ib.verdicts(cut_batch()))
    fetched, aliases, skipped, failed, by_topic = result
    report = ib.build_report(TMP / "batch-review", fetched, aliases, skipped,
                             failed, by_topic)

    assert by_topic[REVIEWED] == [f"{REVIEWED}-a", f"{REVIEWED}-b"]
    assert [v["video_id"] for v in fetched if v["topic_id"] == REVIEWED] \
        == [f"{REVIEWED}-a", f"{REVIEWED}-b"]
    assert report["sources_by_topic"][REVIEWED] == by_topic[REVIEWED]
    assert not any(s["topic_id"] == REVIEWED for s in report["skipped_topics"])
    assert REVIEWED not in report["two_source_floor"]["refused"]
    assert not any(REVIEWED in v for v in report["compliance_gate"].values()
                   if isinstance(v, list))
    assert "review" not in report["compliance_gate"]


def test_every_topic_not_fetched_is_one_coded_record_and_nothing_is_silent():
    f = Fetcher()
    _, _, skipped, _, by_topic = run(
        f, shortlist_topics(), ib.verdicts(cut_batch()))[0]

    assert [s["topic_id"] for s in skipped] == RESERVED + [UNJUDGED]
    for t in RESERVED:
        assert record(skipped, t)["reason_code"] == ib.RESERVE_SKIP_CODE
    assert record(skipped, UNJUDGED)["reason_code"] == ib.NOT_SCREENED_CODE

    # The funnel's four keys on every record, and a reason that reads alone.
    for s in skipped:
        assert set(s) == {"topic_id", "reason_code", "reason", "stage"}
        assert s["stage"] == ib.STAGE_NAME
        assert len(s["reason"]) > 40 and s["reason"][0].isalnum()

    # A skipped topic gets no row in sources_by_topic: it was never walked.
    for t in RESERVED + [UNJUDGED]:
        assert t not in by_topic


def test_the_reserve_code_is_the_one_compliance_wrote_and_the_reason_says_so():
    assert ib.RESERVE_SKIP_CODE == "reserve_unused"     # cut_shortlist.RESERVE_CODE
    assert ib.NOT_SCREENED_CODE == "not_screened"       # funnel.FUNNEL_CODES
    f = Fetcher()
    _, _, skipped, _, _ = run(f, shortlist_topics(), ib.verdicts(cut_batch()))[0]
    reason = record(skipped, RESERVED[0])["reason"].lower()
    assert "reserve" in reason and "no slot" in reason
    assert "not a refusal" in reason and "not a fault of the topic" in reason
    assert "reserve[]" in record(skipped, RESERVED[0])["reason"]

    unjudged = record(skipped, UNJUDGED)["reason"].lower()
    assert "no verdict" in unjudged
    assert "results[]" in unjudged and "reserve[]" in unjudged


def test_the_report_carries_both_codes_by_name_even_when_empty():
    f = Fetcher()
    result, _ = run(f, shortlist_topics(), ib.verdicts(cut_batch()))
    fetched, aliases, skipped, failed, by_topic = result
    report = ib.build_report(TMP / "batch-x", fetched, aliases, skipped, failed,
                             by_topic)
    gate = report["compliance_gate"]
    assert gate["reserve_unused"] == RESERVED
    assert gate["not_screened"] == [UNJUDGED]
    assert "CF-0265" in gate["note"] and ib.RESERVE_SKIP_CODE in gate["note"]
    # CF-0318: the third key is gone and nothing took its place. The note is
    # what tells a reader where a `review` went instead - the register the
    # Publisher reads, not this file, which is archived in 31 days.
    assert "review" not in gate
    assert "CF-0318" in gate["note"]
    assert "publish/publication-holds.json" in gate["note"]
    assert "publication_hold" in gate["note"]

    # The floor's own block must not claim these topics: they never walked.
    assert report["two_source_floor"]["refused"] == []

    empty = ib.build_report(TMP / "batch-x", [], [], [], [], {})["compliance_gate"]
    assert empty == {"reserve_unused": [], "not_screened": [],
                     "note": gate["note"]}


def test_the_skipped_topics_the_funnel_reads_are_the_same_records():
    f = Fetcher()
    result, _ = run(f, shortlist_topics(), ib.verdicts(cut_batch()))
    fetched, aliases, skipped, failed, by_topic = result
    report = ib.build_report(TMP / "batch-x", fetched, aliases, skipped, failed,
                             by_topic)
    assert report["skipped_topics"] == [dict(s) for s in skipped]


# ---------------------------------------------------------------------------
# The gate is a filter in front of the walk, not a change to it

def test_the_two_source_floor_still_refuses_a_carried_topic_that_is_short():
    """CF-0129 is untouched: a carried topic whose second candidate is gone is
    refused with `no_second_source`, beside the CF-0265 records."""
    short = CARRIED[0]
    f = Fetcher(gone=[f"{short}-b"])
    _, _, skipped, failed, by_topic = run(
        f, shortlist_topics(), ib.verdicts(cut_batch()))[0]

    assert record(skipped, short)["reason_code"] == ib.TOPIC_REFUSAL_CODE
    assert [x["video_id"] for x in failed] == [f"{short}-b"]
    assert by_topic[short] == [f"{short}-a"]
    for t in CARRIED[1:]:
        assert len(by_topic[t]) == 2
    # And the reserve is still reserve, not swept into the floor's refusals.
    for t in RESERVED:
        assert record(skipped, t)["reason_code"] == ib.RESERVE_SKIP_CODE


# ---------------------------------------------------------------------------
# Old batches, unchanged

def test_an_old_batch_with_a_row_per_topic_fetches_every_topic_as_before():
    """Every 02-compliance-checker.json written before this task has one
    result per topic, so `not_screened` cannot bite a re-run of one."""
    topics = shortlist_topics(SHORTLIST[:3])
    batch = write_batch("old-full", [verdict_row(t) for t in SHORTLIST[:3]],
                        reserve=None)
    f = Fetcher()
    _, _, skipped, _, by_topic = run(f, topics, ib.verdicts(batch))[0]
    assert sorted(by_topic) == sorted(SHORTLIST[:3])
    assert skipped == []
    assert len(f.ids) == 6


def test_an_old_batch_with_a_review_in_it_fetches_it_too():
    """CF-0318 is about the rule, not about the file format: a batch written
    before the cut existed (`results[]` only, no `reserve` key) walks its
    `review` topic exactly like a batch written today."""
    topics = shortlist_topics(SHORTLIST[:2])
    batch = write_batch(
        "old-review",
        [verdict_row(SHORTLIST[0]), verdict_row(SHORTLIST[1], "review")],
        reserve=None)
    f = Fetcher()
    _, _, skipped, _, by_topic = run(f, topics, ib.verdicts(batch))[0]
    assert skipped == []
    assert sorted(by_topic) == sorted(SHORTLIST[:2])
    assert by_topic[SHORTLIST[1]] == [f"{SHORTLIST[1]}-a", f"{SHORTLIST[1]}-b"]


def test_a_report_written_before_the_change_is_still_read_as_compliances_word():
    """CF-0318: `COMPLIANCE_SKIP_CODE` is kept in `PRE_FETCH_CODES` for the
    reports that already carry it - `01b-footage-index.json` files written
    before 2026-09-23, which `source_sieve.py` and the CLI's summary both
    re-read. Drop the name from the tuple and every one of those records turns
    into a refusal this stage made, below a floor it never reached: a loss
    invented by the reader, in the very funnel this task exists to correct.
    And `slot_losses()` must not hand such a record a reserve topic a month
    later - the slot was never free."""
    old = {"skipped_topics": [
        {"topic_id": SHORTLIST[0], "reason_code": ib.COMPLIANCE_SKIP_CODE,
         "reason": "compliance verdict is 'review' - not signed off",
         "stage": ib.STAGE_NAME},
        {"topic_id": SHORTLIST[1], "reason_code": ib.TOPIC_REFUSAL_CODE,
         "reason": "one source only", "stage": ib.STAGE_NAME}]}
    refused = [s for s in old["skipped_topics"]
               if s["reason_code"] not in ib.PRE_FETCH_CODES]
    assert [s["topic_id"] for s in refused] == [SHORTLIST[1]]
    assert [s["topic_id"] for s in ib.slot_losses(old)] == [SHORTLIST[1]]


def test_a_batch_whose_compliance_pass_has_not_run_fetches_everything():
    topics = shortlist_topics(SHORTLIST[:3])
    batch = TMP / "no-02"
    batch.mkdir(parents=True, exist_ok=True)
    f = Fetcher()
    _, _, skipped, _, by_topic = run(f, topics, ib.verdicts(batch))[0]
    assert sorted(by_topic) == sorted(SHORTLIST[:3])
    assert skipped == []


# ---------------------------------------------------------------------------
# The stage says so out loud

def test_the_stage_prints_the_gated_topics_apart_from_its_own_refusals():
    """main()'s two summary lines: a reserve topic is not "refused below the
    floor", and it is not invisible either."""
    assert ib.PRE_FETCH_CODES == (ib.COMPLIANCE_SKIP_CODE, ib.RESERVE_SKIP_CODE,
                                  ib.NOT_SCREENED_CODE)
    f = Fetcher()
    _, _, skipped, _, _ = run(f, shortlist_topics(), ib.verdicts(cut_batch()))[0]
    refused = [s for s in skipped if s["reason_code"] not in ib.PRE_FETCH_CODES]
    gated = [s for s in skipped if s["reason_code"] in
             (ib.RESERVE_SKIP_CODE, ib.NOT_SCREENED_CODE)]
    assert refused == []
    assert [s["topic_id"] for s in gated] == RESERVED + [UNJUDGED]


def test_the_skill_records_the_reserve():
    skill = (Path(__file__).resolve().parent.parent / ".claude" / "skills"
             / "footage-indexer" / "SKILL.md").read_text()
    assert "reserve_unused" in skill and "not_screened" in skill
    assert "CF-0265" in skill and "2026-09-17" in skill
    assert "02-compliance-checker.json" in skill
    # CF-0318: and it must not still say a `review` verdict is a third way a
    # topic is dropped here, which is what it said until 2026-09-23.
    assert "CF-0318" in skill and "publication-holds.json" in skill
    assert "`compliance_review` for a `review` verdict" not in skill


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
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

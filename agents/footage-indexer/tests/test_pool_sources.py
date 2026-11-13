#!/usr/bin/env python3
"""CF-0325 part 2: pool sources Trend Hunter matched to a topic count as the
topic's own before any download - once they are shown to be the topic's work.

Pinned here, offline (a fake fetcher, a fingerprint that is the name of the
cut, an injected work check and sieve):

  - `vet()`: a source whose media left the cache, one nobody could check, one
    the work check refuses and one the CF-0299 sieve refuses are not counted,
    each with its check and reason; the rest are counted;
  - only refusals about the video bar it from the topic's walk;
  - `ingest(pooled=)`: two counted pool sources meet the floor and nothing is
    downloaded; one counted source means exactly one download; a pool id that
    is also a candidate is not fetched again; two pool re-uploads of one cut
    are one source (an alias `from_pool`); a barred id is never fetched and
    costs no attempt; a topic compliance does not let through gets nothing;
  - the report block says which sources were counted, refused, aliased;
  - the real `pool_work_check.py` (Trend Hunter's checks, in its own process):
    an Vanguards: Endgame trailer is not counted for Vanguards: Doomsday
    (batch 2026-09-29T0705Z), a Harbourlights preview is not counted for Harry
    Hollow, a fan-made concept trailer is not counted for Silent Tide.

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
import pool_sources as ps           # noqa: E402

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0325-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
CUTS = {}


class Cuts:
    @staticmethod
    def compare(a, b):
        same = a["cut"] == b["cut"]
        return {"distance": 0.0 if same else 30.0, "offset_seconds": 0.0,
                "overlap_frames": 120}

    @staticmethod
    def is_duplicate(cmp):
        return cmp is not None and cmp["distance"] <= 12


def fingerprint(path):
    vid = Path(path).stem
    return {"kind": "cut", "cut": CUTS.get(vid, vid)}


def no_measure(vid, record=None):
    return ib.Measured(None, "metadata", "not measured in this test")


class Fetcher:
    def __init__(self):
        self.calls = []

    def __call__(self, vid, note):
        self.calls.append(vid)
        return ib.FetchResult(f"/tmp/{vid}.mp4", False)


def run(topics, verdict=None, **kw):
    f = Fetcher()
    out = io.StringIO()
    real, ib.source_fingerprint = ib.source_fingerprint, Cuts
    try:
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            res = ib.ingest(topics, verdict or {}, "batch-x", skip_index=True,
                            fetch=f, index=lambda p: None, fingerprint=fingerprint,
                            sleep=lambda s: None, pause=0, is_cached=lambda v: False,
                            measure=no_measure, depth_floor=0, **kw)
    finally:
        ib.source_fingerprint = real
    return res, f, out.getvalue()


def topic(tid, ids, matched=(), name="Some Show"):
    t = {"topic_id": tid, "title_ref": {"name": name, "kind": "work"},
         "evidence": {"youtube_video_ids": list(ids)}}
    if matched:
        t["pool"] = {"matched": [{"video_id": v, "title": f"{name} clip {v}",
                                  "by": ["title"]} for v in matched]}
    return t


def cache_with(*vids, no_mp4=(), no_index=()):
    cache = Path(tempfile.mkdtemp(dir=TMP))
    for v in vids:
        if v not in no_mp4:
            (cache / f"{v}.mp4").write_bytes(b"x")
        if v not in no_index:
            (cache / f"{v}.shots.json").write_text(json.dumps({"shots": []}))
    return cache


def checker_ok(bad=None, error=None):
    bad = bad or {}

    def check(payload):
        if error:
            return {"error": error, "topics": {}}
        return {"error": None, "topics": {
            t["topic_id"]: {s["video_id"]: ({"ok": False, "rule": "work_not_in_title",
                                             "reason_code": "wrong_work",
                                             "reason": bad[s["video_id"]]}
                                            if s["video_id"] in bad else {"ok": True, "host_show": None})
                            for s in t["sources"]} for t in payload}}
    return check


def quiet(**kw):
    return dict(log=lambda *a, **k: None, **kw)


# ---------------------------------------------------------------------------
# vet()

def test_a_topic_without_a_pool_record_has_nothing_to_vet():
    cache = cache_with()
    assert ps.vet([topic("t1", ["a"])], cache, checker=checker_ok(), **quiet()) == {}
    assert ps.matched_of({"pool": {"matched": "nope"}}) == []
    assert ps.matched_of({"pool": None}) == []


def test_each_check_refuses_with_its_own_code_and_the_rest_are_counted():
    cache = cache_with("ok1", "gone", "noidx", "wrong", "sieved", "ok2", no_mp4=("gone",),
                       no_index=("noidx",))

    def judge(path):
        if Path(path).name.startswith("sieved"):
            return {"verdict": "refused", "reason_code": ib.SIEVE_FOREIGN_CODE,
                    "reason": "somebody else's film"}
        return {"verdict": "unsieved"}

    t = topic("t1", [], matched=["ok1", "gone", "noidx", "wrong", "sieved", "ok2"])
    v = ps.vet([t], cache, checker=checker_ok({"wrong": "names Harbourlights"}),
               judge=judge, **quiet())["t1"]
    assert [r["video_id"] for r in v["counted"]] == ["ok1", "ok2"]
    got = {r["video_id"]: (r["reason_code"], r["check"]) for r in v["refused"]}
    assert got == {"gone": (ps.MEDIA_GONE, ps.CHECK_MEDIA),
                   "noidx": (ps.MEDIA_GONE, ps.CHECK_MEDIA),
                   "wrong": ("wrong_work", ps.CHECK_WORK),
                   "sieved": (ib.SIEVE_FOREIGN_CODE, ps.CHECK_SIEVE)}
    assert all(r["reason"] for r in v["refused"])
    assert v["counted"][0]["sieve"] == "unsieved"
    # only what is about the video bars it from the walk
    assert ps.barred_ids({"t1": v}) == {"t1": ["wrong", "sieved"]}
    assert ps.pooled_paths({"t1": v}) == {"t1": [("ok1", str(cache / "ok1.mp4")),
                                                 ("ok2", str(cache / "ok2.mp4"))]}


def test_a_source_nobody_could_check_is_never_counted():
    cache = cache_with("a", "b")
    v = ps.vet([topic("t1", [], matched=["a", "b"])], cache,
               checker=checker_ok(error="no trend-hunter checkout"), judge=None,
               **quiet())["t1"]
    assert v["counted"] == []
    assert {r["reason_code"] for r in v["refused"]} == {ps.NOT_CHECKED}
    assert "no trend-hunter checkout" in v["refused"][0]["reason"]
    assert ps.barred_ids({"t1": v}) == {}


def test_a_work_check_that_crashes_is_an_error_not_a_crash():
    ans = ps.run_work_check([], TMP / "no-such-root", timeout=30)
    assert ans["topics"] == {} and ans["error"]


# ---------------------------------------------------------------------------
# ingest(pooled=)

def test_two_counted_pool_sources_meet_the_floor_and_nothing_is_downloaded():
    (fetched, aliases, skipped, failed, by), f, out = run(
        [topic("t1", ["c1", "c2", "c3"])], pooled={"t1": [("p1", "/c/p1.mp4"),
                                                          ("p2", "/c/p2.mp4")]})
    assert f.calls == []
    assert by["t1"] == ["p1", "p2"] and skipped == []
    assert [r.get(ps.FETCHED_MARK) for r in fetched] == [True, True]
    assert "POOL t1 counts 2 pool source(s)" in out


def test_one_counted_pool_source_means_exactly_one_download():
    (fetched, _, skipped, _, by), f, _ = run(
        [topic("t1", ["p1", "c1", "c2"])], pooled={"t1": [("p1", "/c/p1.mp4")]})
    assert f.calls == ["c1"]                 # p1 is a candidate too, not fetched again
    assert by["t1"] == ["p1", "c1"] and skipped == []
    assert [r.get(ps.FETCHED_MARK, False) for r in fetched] == [True, False]


def test_two_pool_reuploads_of_one_cut_are_one_source():
    CUTS.update({"p1": "teaser", "p2": "teaser"})
    (fetched, aliases, _, _, by), f, _ = run(
        [topic("t1", ["c1", "c2"])], pooled={"t1": [("p1", "/c/p1.mp4"),
                                                   ("p2", "/c/p2.mp4")]})
    assert by["t1"] == ["p1", "c1"] and f.calls == ["c1"]
    assert aliases[0]["video_id"] == "p2" and aliases[0][ps.FETCHED_MARK]
    # and a later candidate of the same cut is deduped against the pool source
    CUTS.update({"c9": "teaser"})
    (_, aliases, _, _, by), f, _ = run(
        [topic("t1", ["c9", "c1"])], pooled={"t1": [("p1", "/c/p1.mp4")]})
    assert by["t1"] == ["p1", "c1"] and aliases[0]["alias_of"] == "p1"


def test_a_barred_pool_id_is_not_fetched_and_costs_no_attempt():
    (_, _, skipped, _, by), f, _ = run(
        [topic("t1", ["bad", "c1", "c2", "c3", "c4"])], pool_barred={"t1": ["bad"]},
        max_per_topic=4)
    assert "bad" not in f.calls and f.calls == ["c1", "c2"]
    assert by["t1"] == ["c1", "c2"]


def test_a_topic_compliance_did_not_let_through_gets_no_pool_sources():
    screening = ib.Screening(ran=True, verdict={"t2": "clear"}, reserve=["t1"], rows={})
    (fetched, _, skipped, _, by), f, _ = run(
        [topic("t1", ["c1"]), topic("t2", ["c2", "c3"])], verdict=screening,
        pooled={"t1": [("p1", "/c/p1.mp4")]})
    assert "t1" not in by and not any(r["video_id"] == "p1" for r in fetched)
    assert [s["topic_id"] for s in skipped] == ["t1"]
    block = ps.report_block({"t1": {"matched": 1, "error": None, "refused": [],
                                    "counted": [{"video_id": "p1", "outcome": ps.COUNTED}]}},
                            by, [])
    assert block["topics"]["t1"]["sources"][0]["outcome"] == ps.NOT_WALKED
    assert block["counted"] == 0


def test_the_report_block_says_counted_refused_and_aliased():
    vetted = {"t1": {"matched": 3, "error": None,
                     "counted": [{"video_id": "p1", "outcome": ps.COUNTED},
                                 {"video_id": "p2", "outcome": ps.COUNTED}],
                     "refused": [{"video_id": "x", "outcome": ps.REFUSED,
                                  "reason_code": "other_installment", "check": "work",
                                  "reason": "Endgame for Doomsday"}]}}
    block = ps.report_block(vetted, {"t1": ["p1", "c1"]},
                            [{"topic_id": "t1", "video_id": "p2", "alias_of": "p1",
                              ps.FETCHED_MARK: True}])
    rows = {r["video_id"]: r for r in block["topics"]["t1"]["sources"]}
    assert rows["p1"]["outcome"] == ps.COUNTED
    assert rows["p2"]["outcome"] == ps.ALIASED and rows["p2"]["alias_of"] == "p1"
    assert rows["x"]["outcome"] == ps.REFUSED
    assert (block["counted"], block["refused"]) == (1, 1)
    assert block["rule"] == "CF-0325"


def test_the_cli_wires_the_pool_in():
    src = (SCRIPTS / "ingest_batch.py").read_text()
    assert "--no-pool" in src
    assert "pooled=pool_sources.pooled_paths(vetted)" in src
    assert "report[pool_sources.BLOCK_KEY]" in src


# ---------------------------------------------------------------------------
# The real work check - Trend Hunter's own rules, in its own process

# CF-0631 (CF-0627): the official footage channels are the batch's channel's
# own list, `channels/<id>/footage-origin.json` of the factory root. A test
# reads no channel's real list: a stand-in root with a made-up channel and the
# three studios these checks name (ids as the factory's list has them).
STAND_IN = "stand-in-channel"
STAND_IN_ORIGIN = {"official_channels": [
    {"pattern": "example network", "what": "network / streamer",
     "channels": [{"id": "UCexample000000000000080", "title": "Example Max",
                   "resolved_by": "a stand-in of the factory's list"}]},
    {"pattern": "example studios", "what": "studio",
     "channels": [{"id": "UCexample000000000000050", "title": "Example Studios",
                   "resolved_by": "a stand-in of the factory's list"}]},
    {"pattern": "zenith", "what": "studio",
     "channels": [{"id": "UCexample000000000000070", "title": "Zenith Entertainment",
                   "resolved_by": "a stand-in of the factory's list"}]}]}


def stand_in_channel_root():
    root = TMP / "channel-root"
    chan = root / "channels" / STAND_IN
    if not chan.exists():
        chan.mkdir(parents=True)
        (root / "channels" / f"{STAND_IN}.json").write_text(
            json.dumps({"channel_id": STAND_IN, "former_channel_ids": []}))
        (chan / "footage-origin.json").write_text(json.dumps(STAND_IN_ORIGIN))
    return root


def work_check(payload, root, channel=STAND_IN):
    return ps.run_work_check(payload, root, channel=channel,
                             channel_root=stand_in_channel_root())


def test_the_work_check_reads_the_batchs_channel():
    """CF-0631: the request names the batch's channel and its root - `vet()`
    hands its `channel` through - and a check asked with no channel answers
    `error` (every source "not checked", never counted), not another
    channel's list."""
    seen = {}
    saved = ps.run_work_check
    try:
        ps.run_work_check = lambda payload, root, channel=None, **kw: (
            seen.update(channel=channel, root=root) or {"error": None, "topics": {}})
        cache = TMP / "cf0631-cache"
        cache.mkdir(exist_ok=True)
        ps.vet([topic("t1", [], matched=["a"])], cache, root=TMP, channel="some-chan",
               **quiet())
    finally:
        ps.run_work_check = saved
    assert seen == {"channel": "some-chan", "root": TMP}, seen
    root = ib.FACTORY_ROOT
    if not (root / ps.TREND_HUNTER_REL / "scripts" / "topic_relevance.py").exists():
        print("  (no trend-hunter checkout beside this repo - skipped)")
        return
    payload = [{"topic_id": "x", "title_ref": {"name": "Sandfall", "kind": "work"},
                "sources": [{"video_id": "d1", "title": "Sandfall | Official Trailer",
                             "channel_title": "Example Studios"}]}]
    ans = work_check(payload, root, channel=None)
    assert ans["topics"] == {} and "no channel named" in (ans["error"] or ""), ans
    ans = work_check(payload, root, channel="no-such-channel")
    assert ans["topics"] == {} and ans["error"], ans
    ans = work_check(payload, root)
    assert ans.get("error") is None and ans["topics"]["x"]["d1"]["ok"] is True, ans

def test_the_real_work_check_turns_away_the_wrong_work():
    root = ib.FACTORY_ROOT
    if not (root / ps.TREND_HUNTER_REL / "scripts" / "topic_relevance.py").exists():
        print("  (no trend-hunter checkout beside this repo - skipped)")
        return
    payload = [
        {"topic_id": "doom", "title_ref": {"name": "Vanguards: Doomsday", "kind": "work"},
         "sources": [{"video_id": "end", "title": "Vanguards: Endgame | Official Trailer",
                      "channel_title": "Zenith Entertainment"},
                     {"video_id": "doom", "title": "Vanguards: Doomsday | Teaser Trailer",
                      "channel_title": "Zenith Entertainment"}]},
        {"topic_id": "hp", "title_ref": {"name": "Wren Hollow", "kind": "work"},
         "sources": [{"video_id": "lan", "title": "Harbourlights | Episode 6 Preview | Example Max",
                      "channel_title": "Example Max"},
                     {"video_id": "hp", "title": "Wren Hollow and the Philosopher's Stone "
                                                 "| Official Teaser Trailer | Example Max",
                      "channel_title": "Example Max"}]},
        {"topic_id": "wwz", "title_ref": {"name": "Silent Tide", "kind": "work"},
         "sources": [{"video_id": "fan", "title": "SILENT TIDE 2: AFTERMATH | Official-Style "
                                                  "Fanmade Concept Trailer | Brad Pitt",
                      "channel_title": "Some Channel"}]},
    ]
    ans = work_check(payload, root)
    assert ans.get("error") is None, ans
    v = ans["topics"]
    assert v["doom"]["end"]["reason_code"] == "other_installment"
    assert v["doom"]["doom"]["ok"] is True
    assert v["hp"]["lan"]["reason_code"] == "wrong_work"
    assert v["hp"]["hp"]["ok"] is True
    assert v["wwz"]["fan"]["reason_code"] == "unofficial_source"


def test_a_name_with_nothing_left_after_its_franchise_refuses_nothing():
    """CF-0444: the pool check asks Trend Hunter's `installment_forms`. A
    degenerate name - its `parent_work` is the name itself, so nothing is left
    once the franchise is taken out - is None there: the rule does not apply
    and the work's own trailer is counted. The indexer's old copy of the rule
    gave `[]` here and refused every source of the topic."""
    root = ib.FACTORY_ROOT
    if not (root / ps.TREND_HUNTER_REL / "scripts" / "topic_relevance.py").exists():
        print("  (no trend-hunter checkout beside this repo - skipped)")
        return
    payload = [{"topic_id": "sandfall",
                "title_ref": {"name": "Sandfall", "parent_work": "Sandfall", "kind": "work"},
                "sources": [{"video_id": "d1", "title": "Sandfall | Official Trailer",
                             "channel_title": "Example Studios"}]}]
    ans = work_check(payload, root)
    assert ans.get("error") is None, ans
    assert ans["topics"]["sandfall"]["d1"]["ok"] is True, ans


# ---------------------------------------------------------------------------
# The replay (item 4) - its arithmetic, on injected checks

def test_the_replay_counts_a_loss_removed_only_by_what_the_check_let_through():
    import pool_sources_replay as rp
    from collections import namedtuple
    D = namedtuple("D", "usable measured")
    cache = cache_with("s1", "s2", "s3", "w1", "t1", "t2")
    CUTS.update({"s2": "cut-a", "s3": "cut-a"})     # s2/s3 are one cut
    losses = [
        {"batch": "none/b1", "topic_id": "a", "code": "no_second_source", "name": "Show",
         "pool_had_it": True, "matched": [["s1", ["title"]], ["w1", ["topic"]]]},
        {"batch": "none/b1", "topic_id": "b", "code": "no_second_source", "name": "Show",
         "pool_had_it": True, "matched": [["s1", ["title"]], ["s2", ["title"]],
                                          ["s3", ["title"]]]},
        {"batch": "none/b1", "topic_id": "c", "code": "pool_too_thin", "name": "Show",
         "pool_had_it": True, "matched": [["t1", ["title"]], ["t2", ["title"]]]},
    ]
    real, rp.source_fingerprint = rp.source_fingerprint, Cuts
    try:
        rows = rp.replay(losses, TMP, cache, checker=checker_ok({"w1": "names Harbourlights"}),
                         judge=lambda p: {"verdict": "kept"},
                         depth=lambda tid, vids: D(30 * len(vids), True),
                         fingerprint=fingerprint)
    finally:
        rp.source_fingerprint = real
    a, b, c = rows
    assert (a["canonical"], a["removed"]) == (["s1"], False)       # w1 refused
    assert a["refused"][0]["reason_code"] == "wrong_work"
    assert (b["canonical"], b["removed"]) == (["s1", "s2"], True)  # s3 = s2's cut
    assert (c["usable"], c["removed"]) == (60, True)
    assert all(r["removed_strict"] == r["removed"] for r in rows)


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

#!/usr/bin/env python3
"""CF-0817: somebody else's podcast, interview or talk show is not reused
from the pool for a topic - unless the topic is about the person in it.

The audit (CF-0818) found the host shows reached published videos through
pool reuse (`topics[].pool.matched` -> `fetched[].from_pool: true`): the
Fallon interview `ZLXL1L0TfsI` (Tom Carver) for three Delver videos, Zenith's
"Countdown to Vanguards: Doomsday Official Podcast" `nSWnovHSDaY` /
`xe3qx0kXArA` for vanguards-doomsday. Pinned here, offline, on trimmed real
metadata (the pool's own title and uploader of those ids):

  - the real `pool_work_check.py` (Trend Hunter's `host_show.judge()` in its
    own process, a stand-in channel list): the Fallon interview is refused
    for Delver, the Zenith podcast for Vanguards: Doomsday, both trailers are
    let through, the interview is let through for a topic about Tom Carver
    (`subject_is_guest`), a pool entry with no uploader is let through and
    marked `host_show_unknown`;
  - a Trend Hunter checkout without the classifier is an `error` naming it,
    and no source is counted;
  - `vet()`: a host show is refused with `reason_code: host_show`, the
    verdict and its signals on the record, and barred from the walk; a
    verdict with no host-show answer is "not checked"; Trend Hunter's own
    candidate verdict on the same id refuses too; the unknown ones are counted
    and counted in the block; `stamp_fetched()` carries the marks to
    `fetched[]`.

No pytest dependency - plain asserts, run directly.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest_batch as ib           # noqa: E402
import pool_sources as ps           # noqa: E402

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0817-")   # removed at exit

STAND_IN = "stand-in-channel"
# The studios these checks name, as a stand-in of a channel's official list -
# Zenith Entertainment is official there, and its podcast is still refused.
STAND_IN_ORIGIN = {"official_channels": [
    {"pattern": "example studios", "what": "studio",
     "channels": [{"id": "UCexample000000000000050", "title": "Example Studios",
                   "resolved_by": "a stand-in of the factory's list"}]},
    {"pattern": "zenith", "what": "studio",
     "channels": [{"id": "UCexample000000000000070", "title": "Zenith Entertainment",
                   "resolved_by": "a stand-in of the factory's list"}]}]}

# Trimmed out of shared/footage/index.json (title, uploader) and the batches'
# 01-trend-hunter.json title_ref - nothing live is read by this test.
FALLON = {"video_id": "ZLXL1L0TfsI",
          "title": "Tom Carver Says Taylor Sterling Was Schooling Him at Chiefs Game, "
                   "Talks Wild Delver Transformation",
          "channel_title": "The Evening Show Starring Jim Fenwick"}
DELVER_TRAILER = {"video_id": "wIM1PDRvKSE",
                  "title": "DELVER Official Trailer #2 (2026, Tom Carver, Riz Ahmed, "
                           "Sandra Hüller, Alejandro G. Iñárritu)",
                  "channel_title": "Example Studios"}
PODCAST = {"video_id": "nSWnovHSDaY",
           "title": "Vanguards: Endgame | Countdown to Vanguards: Doomsday Official Podcast",
           "channel_title": "Zenith Entertainment"}
PODCAST_LOOK = {"video_id": "xe3qx0kXArA",
                "title": "Countdown to Vanguards: Doomsday Official Podcast | Special Look",
                "channel_title": "Zenith Entertainment"}
DOOM_TEASER = {"video_id": "doomTeaser1",
               "title": "Vanguards: Doomsday | Teaser Trailer",
               "channel_title": "Zenith Entertainment"}
NO_UPLOADER = {"video_id": "oldEntry001", "title": "Delver | Official Trailer",
               "channel_title": None}
DELVER = {"name": "Delver", "kind": "work", "type": "film", "year": 2026,
          "parent_work": None, "person": None, "rights_holder": "Example Studios"}
DOOMSDAY = {"name": "Vanguards: Doomsday", "kind": "work", "type": "film", "year": 2026,
            "parent_work": None, "person": None, "rights_holder": None}
CRUISE = {"name": "Tom Carver", "kind": "person", "person": "Tom Carver"}


def has_trend_hunter():
    return (ib.FACTORY_ROOT / ps.TREND_HUNTER_REL / "scripts" / "host_show.py").exists()


def stand_in_channel_root():
    root = TMP / "channel-root"
    chan = root / "channels" / STAND_IN
    if not chan.exists():
        chan.mkdir(parents=True)
        (root / "channels" / f"{STAND_IN}.json").write_text(
            json.dumps({"channel_id": STAND_IN, "former_channel_ids": []}))
        (chan / "footage-origin.json").write_text(json.dumps(STAND_IN_ORIGIN))
    return root


def work_check(payload, root=None):
    return ps.run_work_check(payload, root or ib.FACTORY_ROOT, channel=STAND_IN,
                             channel_root=stand_in_channel_root())


def src(v):
    return {k: v[k] for k in ("video_id", "title", "channel_title")}


# ---------------------------------------------------------------------------
# The real check - Trend Hunter's classifier, in its own process

def test_the_real_check_refuses_the_host_shows_and_lets_the_trailers_through():
    if not has_trend_hunter():
        print("  (no trend-hunter checkout with host_show.py beside this repo - skipped)")
        return
    payload = [
        {"topic_id": "delver", "title_ref": DELVER,
         "sources": [src(FALLON), src(DELVER_TRAILER), src(NO_UPLOADER)]},
        {"topic_id": "doom", "title_ref": DOOMSDAY,
         "sources": [src(PODCAST), src(PODCAST_LOOK), src(DOOM_TEASER)]},
        {"topic_id": "cruise", "title_ref": CRUISE, "sources": [src(FALLON)]},
    ]
    ans = work_check(payload)
    assert ans.get("error") is None, ans
    v = ans["topics"]
    # the Fallon interview for Delver: passes "is it the work", refused here
    fallon = v["delver"][FALLON["video_id"]]
    assert fallon["ok"] is True and fallon["host_show"]["refused"] is True, fallon
    assert any(s["by"] == "show" and s["code"] == "tonight_show"
               for s in fallon["host_show"]["signals"]), fallon
    assert v["delver"][DELVER_TRAILER["video_id"]]["host_show"] is None
    # an old entry with no uploader: judged on its title, nothing found, marked
    old = v["delver"][NO_UPLOADER["video_id"]]
    assert old["ok"] is True and old["host_show"] is None, old
    assert old["host_show_unknown"] == ["channel_title"], old
    # Zenith's own podcast - an official channel does not exempt it
    for vid in (PODCAST["video_id"], PODCAST_LOOK["video_id"]):
        p = v["doom"][vid]
        assert p["ok"] is True and p["host_show"]["refused"] is True, p
        assert any(s["code"] == "podcast" for s in p["host_show"]["signals"]), p
    assert v["doom"][DOOM_TEASER["video_id"]]["host_show"] is None
    # the topic is about the person the interview's title names
    guest = v["cruise"][FALLON["video_id"]]
    assert guest["ok"] is True, guest
    assert guest["host_show"]["refused"] is False, guest
    assert guest["host_show"]["exception"] == "subject_is_guest", guest


def test_vet_over_the_real_check_refuses_from_the_pool_and_bars_the_walk():
    if not has_trend_hunter():
        print("  (no trend-hunter checkout with host_show.py beside this repo - skipped)")
        return
    cache = Path(tempfile.mkdtemp(dir=TMP))
    rows = [FALLON, DELVER_TRAILER, NO_UPLOADER, PODCAST, DOOM_TEASER]
    for r in rows:
        (cache / f"{r['video_id']}.mp4").write_bytes(b"x")
        (cache / f"{r['video_id']}.shots.json").write_text(json.dumps({"shots": []}))
    (cache / "index.json").write_text(json.dumps({"entries": [
        {"id": r["video_id"], "title": r["title"], "uploader": r["channel_title"]}
        for r in rows]}))

    def topic(tid, ref, ids):
        return {"topic_id": tid, "title_ref": ref, "evidence": {"youtube_video_ids": []},
                "pool": {"matched": [{"video_id": i, "by": ["title"]} for i in ids]}}

    topics = [topic("delver", DELVER, [FALLON["video_id"], DELVER_TRAILER["video_id"],
                                       NO_UPLOADER["video_id"]]),
              topic("doom", DOOMSDAY, [PODCAST["video_id"], DOOM_TEASER["video_id"]]),
              topic("cruise", CRUISE, [FALLON["video_id"]])]
    lines = []
    vetted = ps.vet(topics, cache, checker=work_check, judge=None,
                    log=lambda *a, **k: lines.append(a))
    dig, doom, cruise = vetted["delver"], vetted["doom"], vetted["cruise"]
    assert [r["video_id"] for r in dig["counted"]] == [DELVER_TRAILER["video_id"],
                                                       NO_UPLOADER["video_id"]], dig
    assert [(r["video_id"], r["reason_code"], r["check"]) for r in dig["refused"]] == [
        (FALLON["video_id"], ps.HOST_SHOW, ps.CHECK_HOST_SHOW)]
    assert dig["refused"][0]["host_show"]["signals"], dig["refused"][0]
    assert [r["video_id"] for r in doom["counted"]] == [DOOM_TEASER["video_id"]]
    assert doom["refused"][0]["video_id"] == PODCAST["video_id"]
    assert doom["refused"][0]["reason_code"] == ps.HOST_SHOW
    assert [r["video_id"] for r in cruise["counted"]] == [FALLON["video_id"]]
    assert cruise["counted"][0]["host_show"]["exception"] == "subject_is_guest"
    # refused for what it is: the walk may not take it in by the front door
    assert ps.barred_ids(vetted) == {"delver": [FALLON["video_id"]],
                                     "doom": [PODCAST["video_id"]]}
    block = ps.report_block(vetted, {"delver": [DELVER_TRAILER["video_id"],
                                                NO_UPLOADER["video_id"]],
                                     "doom": [DOOM_TEASER["video_id"]],
                                     "cruise": [FALLON["video_id"]]}, [])
    assert (block["host_show"], block["host_show_unknown"]) == (2, 1), block
    assert block["topics"]["delver"]["host_show"] == [FALLON["video_id"]]
    assert block["topics"]["delver"]["host_show_unknown"] == 1


def test_a_trend_hunter_without_the_classifier_is_a_loud_error():
    if not has_trend_hunter():
        print("  (no trend-hunter checkout with host_show.py beside this repo - skipped)")
        return
    real = ib.FACTORY_ROOT / ps.TREND_HUNTER_REL
    root = Path(tempfile.mkdtemp(dir=TMP))
    th = root / ps.TREND_HUNTER_REL
    (th / "scripts").mkdir(parents=True)
    for f in (real / "scripts").iterdir():
        if f.name != "host_show.py" and f.suffix == ".py":
            shutil.copy(f, th / "scripts" / f.name)   # a copy: its HERE is here
    (th / "config").symlink_to(real / "config")
    ans = work_check([{"topic_id": "doom", "title_ref": DOOMSDAY,
                       "sources": [src(DOOM_TEASER)]}], root=root)
    assert ans["topics"] == {} and "CF-0817" in (ans["error"] or ""), ans
    assert "host-show classifier" in ans["error"], ans
    cache = Path(tempfile.mkdtemp(dir=TMP))
    (cache / "doomTeaser1.mp4").write_bytes(b"x")
    (cache / "doomTeaser1.shots.json").write_text("{}")
    lines = []
    v = ps.vet([{"topic_id": "doom", "title_ref": DOOMSDAY,
                 "pool": {"matched": [{"video_id": "doomTeaser1",
                                       "title": DOOM_TEASER["title"]}]}}],
               cache, checker=lambda p: ans, judge=None,
               log=lambda *a, **k: lines.append(" ".join(map(str, a))))["doom"]
    assert v["counted"] == [] and v["refused"][0]["reason_code"] == ps.NOT_CHECKED
    assert any("host-show check unavailable" in ln for ln in lines), lines


# ---------------------------------------------------------------------------
# vet() on injected verdicts

def cache_with(*vids):
    cache = Path(tempfile.mkdtemp(dir=TMP))
    for v in vids:
        (cache / f"{v}.mp4").write_bytes(b"x")
        (cache / f"{v}.shots.json").write_text(json.dumps({"shots": []}))
    return cache


def checker(answers):
    return lambda payload: {"error": None, "topics": {
        t["topic_id"]: {s["video_id"]: answers[s["video_id"]] for s in t["sources"]}
        for t in payload}}


def pool_topic(tid, ids, **ev):
    return {"topic_id": tid, "title_ref": {"name": "Some Show", "kind": "work"},
            "evidence": dict({"youtube_video_ids": []}, **ev),
            "pool": {"matched": [{"video_id": i, "title": f"Some Show {i}"} for i in ids]}}


REFUSED = {"refused": True, "exception": None, "subject": None,
           "signals": [{"by": "format", "code": "podcast", "field": "title",
                        "match": "podcast"}],
           "reason": "a host show (format 'podcast' in title)"}


def test_a_verdict_without_a_host_show_answer_is_not_checked():
    cache = cache_with("a")
    v = ps.vet([pool_topic("t1", ["a"])], cache, checker=checker({"a": {"ok": True}}),
               judge=None, log=lambda *a, **k: None)["t1"]
    assert v["counted"] == [] and v["refused"][0]["reason_code"] == ps.NOT_CHECKED
    assert v["refused"][0]["check"] == ps.CHECK_HOST_SHOW
    assert ps.barred_ids({"t1": v}) == {}


def test_trend_hunters_own_candidate_verdict_refuses_the_pool_copy():
    """It judged the id as a candidate with the nature the pool does not keep
    and dropped it: the pool's copy of the same upload is refused too."""
    cache = cache_with("a", "b", "c")
    dropped = [{"video_id": "a", "reason_code": "host_show", "reason": "an interview",
                "host_show": dict(REFUSED, reason="an interview (nature)")},
               {"video_id": "b", "reason_code": "host_show", "reason": "a talk show"}]
    v = ps.vet([pool_topic("t1", ["a", "b", "c"], footage_candidates_dropped=dropped)],
               cache, checker=checker({k: {"ok": True, "host_show": None}
                                       for k in "abc"}),
               judge=None, log=lambda *a, **k: None)["t1"]
    assert [r["video_id"] for r in v["counted"]] == ["c"]
    got = {r["video_id"]: (r["reason_code"], r["reason"]) for r in v["refused"]}
    assert got == {"a": ("host_show", "an interview (nature)"),
                   "b": ("host_show", "a talk show")}, got


def test_the_marks_ride_onto_fetched():
    cache = cache_with("a", "b", "c")
    kept = dict(REFUSED, refused=False, exception="subject_is_guest", subject="X")
    vetted = ps.vet([pool_topic("t1", ["a", "b", "c"])], cache, checker=checker({
        "a": {"ok": True, "host_show": REFUSED},
        "b": {"ok": True, "host_show": kept},
        "c": {"ok": True, "host_show": None, "host_show_unknown": ["channel_title"]}}),
        judge=None, log=lambda *a, **k: None)
    v = vetted["t1"]
    assert v["refused"][0]["host_show"] == REFUSED
    fetched = [{"video_id": "b", "topic_id": "t1", "from_pool": True},
               {"video_id": "c", "topic_id": "t1", "from_pool": True},
               {"video_id": "c", "topic_id": "t2"}]
    ps.stamp_fetched(fetched, vetted)
    assert fetched[0]["host_show"]["exception"] == "subject_is_guest"
    assert fetched[1]["host_show_unknown"] == ["channel_title"]
    assert "host_show_unknown" not in fetched[2]


def test_the_cli_stamps_the_marks():
    src_text = (SCRIPTS / "ingest_batch.py").read_text()
    assert "pool_sources.stamp_fetched(fetched, vetted)" in src_text


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

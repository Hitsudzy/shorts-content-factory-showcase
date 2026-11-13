#!/usr/bin/env python3
"""CF-0738: the channel's копилка with its details, and placing K of its
videos onto the K nearest free slots (plan/confirm) -
`agents/publisher/publish_stash.py`.

On temp roots only: no live record, no live publish/, no network, no model.
The card's readiness (`publish_card.card_state`, the claim check of CF-0555)
is a stand-in here - what is pinned is the pile and the placing, not the card:

* `stash`: per video in `_queue/` - batch or rebuild, accepted when, the card
  there and ready, mp4 in publish/ and thumbnail in the batch, the age since
  the acceptance and since the topic's news; an accepted row with no place in
  publish/ is listed under `not_queued` with the repair command; a version
  whose other version is placed is not "lost" (CF-0921: one the rule could not
  tell from a new video is listed under `other_version`, the driver decides);
* `place_plan`: K videos in order onto the K nearest free slots (a slot taken
  by a day folder or by the upload journal is skipped), refusals per video,
  nothing written, `base_sha256`;
* `place_confirm`: by/via required, a changed base refused, a paused channel
  and an open batch of the channel refused; every passing video goes through
  `publish_card.place` in order and lands in its day folder; a refused one does
  not stop the others.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("publish-stash-test-")
os.environ.setdefault("RUNLOG_STATE_DIR", str(TMP / "state"))
os.environ["RUNLOG_POOL"] = str(TMP / "no-pool")

import publish_card as pc       # noqa: E402
import publish_stash as ps      # noqa: E402

CH = "scichan"
NOW = "2026-10-13T12:00:00+03:00"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
_n = [0]


def _ready_stub(text):
    return ("READY-STUB" in text, None if "READY-STUB" in text else "stub: not ready")


pc.card_state = _ready_stub          # the claim check is not what is pinned here


def w(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False, indent=1)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")
    return p


def root(slot=True, feed_days=14):
    """CF-0918: `feed_days` - the channel's min_feed_days, the horizon of placing
    (14 here: the placements pinned below reach 4-5 days out)."""
    _n[0] += 1
    d = TMP / f"root{_n[0]}"
    w(d / "channels" / f"{CH}.json", {"channel_id": CH, "publisher": {"slot": SLOT},
                                      "batch_schedule": {"min_feed_days": feed_days}}
      if slot else {"channel_id": CH})
    w(d / "publish" / "uploads.json", {"uploads": []})
    w(d / "publish" / "README.md", "| ролик | статус |\n|---|---|\n")
    w(d / "publish" / "acceptance-log.json", {"note": "t", "task": "CF-0328", "acceptances": []})
    return d


def video(d, slug, batch, where=None, ready=True, card=True, queued=True, accepted=True,
          news="2026-10-10T08:00:00+00:00", answered="2026-10-12", publish_path=True,
          sources=None, title_ref=None, card_title=None, words=None):
    """A rendered video of `batch` (under pipeline/<where or CH>/), its card in
    the batch, its render in publish/<CH>/_queue/ and its accepted row.
    CF-0919: a video with a dated source is news here because its script says
    so (`words`; `words=""` - a dated source and nothing to come: evergreen)."""
    b = d / "pipeline" / (where or CH) / batch
    sid, tid = f"s-{slug}", f"t-{slug}"
    if sources is None:
        sources = [{"published_at": news}, {"published_at": "2026-10-01T00:00:00+00:00"}]
    if words is None:
        words = "It is coming soon." if any(s.get("published_at") for s in sources) else ""
    w(b / "03-content-researcher.json", {"channel": CH, "scripts": [
        {"script_id": sid, "topic_id": tid,
         "claims": [{"text": words}] if words else []}]})
    w(b / "05-video-editor.json", {"channel": CH, "videos": [
        {"script_id": sid, "output_path": str(b / "videos" / f"{slug}.mp4")}]})
    topic = {"topic_id": tid, "evidence": {"sources": sources}}
    if title_ref is not None:
        topic["title_ref"] = title_ref
    w(b / "01-trend-hunter.json", {"topics": [topic]})
    w(b / "videos" / f"{slug}.mp4", b"MP4")
    w(b / "videos" / f"{slug}.jpg", b"JPG")
    if card:
        w(b / "work" / "publish-card" / f"{slug}.md",
          f"# {slug}\n\nБатч `pipeline/{CH}/{batch}`\n\n## Публикация\nне назначена\n\n"
          + (f"## Название\n{card_title}\n\n## Описание\nтекст\n\n" if card_title else "")
          + f"## Карточка\n{'READY-STUB' if ready else 'not ready'}\n")
    if queued:
        w(d / "publish" / CH / "_queue" / f"{slug}.mp4", b"MP4")
    log = d / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    doc["acceptances"].append({
        "entry_id": f"{CH}/{batch}/{slug}", "slug": slug, "channel": CH, "batch_id": batch,
        "verdict": "accepted" if accepted else "rejected", "answered_at": answered,
        "recorded_at": f"{answered}T05:00:00Z", "topic_id": tid,
        "code_shas_source": f"pipeline/{where or CH}/{batch}/05-video-editor.json",
        "publish_path": f"publish/{CH}/_queue/{slug}.mp4" if queued and publish_path else None,
        "history": []})
    w(log, doc)
    return b


def test_the_pile_with_its_details():
    d = root()
    video(d, "sophie-adenot", "2026-10-13T0524Z", where="rebuilds", answered="2026-10-13")
    video(d, "ice-cube", "2026-10-12T2001Z", ready=False, news="2026-10-01T00:00:00+00:00",
          answered="2026-10-12")
    video(d, "lost-one", "2026-10-11T1000Z", queued=False, answered="2026-10-11")
    res = ps.stash(CH, d, NOW)
    assert res["count"] == 2 and res["staleness"]["rule"] == "CF-0741"
    assert res["staleness"]["threshold_days"] == 14 and res["staleness"]["only_marks"]
    assert res["stale"] == 0
    by = {v["slug"]: v for v in res["videos"]}
    s = by["sophie-adenot"]
    assert s["kind"] == "rebuild" and s["batch_id"] == "2026-10-13T0524Z"
    assert s["batch_dir"] == "pipeline/rebuilds/2026-10-13T0524Z"
    assert s["accepted_at"] == "2026-10-13" and s["age"]["accepted_days"] == 0
    assert s["age"]["news_at"].startswith("2026-10-10T08:00") and s["age"]["news_days"] == 3
    assert s["mp4"] == f"publish/{CH}/_queue/sophie-adenot.mp4" and s["mp4_present"]
    assert s["thumbnail"] == "pipeline/rebuilds/2026-10-13T0524Z/videos/sophie-adenot.jpg"
    assert s["card"]["present"] and s["card"]["ready"] and s["card"]["where"] == "batch"
    i = by["ice-cube"]
    assert i["kind"] == "batch" and i["card"]["ready"] is False and i["age"]["news_days"] == 12
    assert [v["slug"] for v in res["not_queued"]] == ["lost-one"]
    lost = res["not_queued"][0]
    assert lost["queue_code"] == "placed" and "--enqueue-accepted" in lost["repair"]
    assert not lost["in_queue"]


def test_the_title_from_the_card_else_the_topic_else_none():
    # CF-0750, the center's request: the title the user knows the video by.
    d = root()
    video(d, "carded", "2026-10-13T0524Z", title_ref="Topic words",
          card_title="Sophie Adenot: the award #shorts")
    video(d, "topical", "2026-10-12T2001Z", title_ref="  Ice Cube returns  ")
    video(d, "bare", "2026-10-12T1000Z", card=False)
    video(d, "lost-one", "2026-10-11T1000Z", queued=False, title_ref="Lost topic")
    res = ps.stash(CH, d, NOW)
    by = {v["slug"]: v for v in res["videos"]}
    # the card's words as it says them - the suffix too, the center trims
    assert (by["carded"]["title"], by["carded"]["title_source"]) == \
        ("Sophie Adenot: the award #shorts", "card")
    assert by["carded"]["card"]["title"] == "Sophie Adenot: the award #shorts"
    assert (by["topical"]["title"], by["topical"]["title_source"]) == ("Ice Cube returns", "topic")
    assert by["topical"]["card"]["present"] and by["topical"]["card"]["title"] is None
    assert (by["bare"]["title"], by["bare"]["title_source"]) == (None, None)
    lost = res["not_queued"][0]
    assert (lost["slug"], lost["title"], lost["title_source"]) == \
        ("lost-one", "Lost topic", "topic")
    # the card next to the video in publish/ is read first
    nxt = d / "publish" / CH / "_queue" / "topical.md"
    w(nxt, "# topical\n\nБатч `pipeline/scichan/2026-10-12T2001Z`\n\n## Название\n"
           "Placed card\n  title\n\n## Карточка\nREADY-STUB\n")
    t = {v["slug"]: v for v in ps.stash(CH, d, NOW)["videos"]}["topical"]
    assert (t["title"], t["title_source"], t["card"]["where"]) == \
        ("Placed card title", "card", "publish")


EVERGREEN = [{"url": "https://example.org/a"}, {"published_at": None}]


def test_age_from_the_news_when_the_topic_has_one_with_the_14_day_boundary():
    # NOW is 2026-10-13 09:00Z: 14 whole days back is 2026-09-29 09:00Z
    d = root()
    video(d, "day-14", "2026-10-12T0100Z", answered="2026-10-13",
          sources=[{"published_at": "2026-09-29T09:00:00+00:00"}])
    video(d, "day-15", "2026-10-12T0200Z", answered="2026-10-13",
          sources=[{"published_at": "2026-09-28T09:00:00+00:00"}])
    video(d, "fresh-news-old-accept", "2026-10-12T0300Z", answered="2026-09-01",
          sources=[{"published_at": "2026-10-12T09:00:00+00:00"}])
    res = ps.stash(CH, d, NOW)
    by = {v["slug"]: v["age"] for v in res["videos"]}
    assert by["day-14"]["basis"] == "news" and by["day-14"]["days"] == 14
    assert by["day-14"]["stale"] is False
    assert by["day-15"]["basis"] == "news" and by["day-15"]["days"] == 15
    assert by["day-15"]["stale"] is True
    # the news decides, not the acceptance (42 days ago)
    a = by["fresh-news-old-accept"]
    assert a["basis"] == "news" and a["days"] == 1 and a["accepted_days"] == 42
    assert a["stale"] is False
    assert res["stale"] == 1


def test_an_evergreen_video_counts_from_the_acceptance_and_does_not_go_stale():
    # CF-0919: the rule of CF-0741 is the news' - only a news video goes stale,
    # a dated source of the topic does not make one
    d = root()
    video(d, "accepted-14", "2026-10-12T0100Z", answered="2026-09-29", sources=EVERGREEN)
    video(d, "accepted-15", "2026-10-12T0200Z", answered="2026-09-28", sources=EVERGREEN)
    video(d, "old-source", "2026-10-12T0300Z", answered="2026-09-01", words="",
          sources=[{"published_at": "2026-08-01T09:00:00+00:00"}])
    res = ps.stash(CH, d, NOW)
    by = {v["slug"]: v["age"] for v in res["videos"]}
    for slug, days in (("accepted-14", 14), ("accepted-15", 15)):
        a = by[slug]
        assert a["news_at"] is None and a["basis"] == "accepted", a
        assert a["days"] == days and a["stale"] is False, a
    a = by["old-source"]
    assert a["news_at"] and a["news_days"] == 73, a
    assert a["basis"] == "accepted" and a["days"] == 42 and a["stale"] is False, a
    assert res["stale"] == 0
    assert ps.choose(CH, d, NOW)[1] == [], "--auto leaves no evergreen video out"


def test_no_date_at_all_is_unknown_not_an_error():
    a = ps.age_of(None, None, None, "no batch or no topic_id")
    assert a["basis"] is None and a["days"] is None and a["stale"] is None
    d = root()
    video(d, "no-dates", "2026-10-12T0100Z", answered=None, sources=EVERGREEN)
    res = ps.stash(CH, d, NOW)
    v = res["videos"][0]
    assert v["age"]["stale"] is False and v["age"]["basis"] is None   # evergreen: does not age
    assert res["stale"] == 0


def test_a_stale_video_is_still_placed_only_marked():
    d = root()
    video(d, "old-one", "2026-10-12T0100Z", answered="2026-10-12",
          sources=[{"published_at": "2026-08-01T00:00:00+00:00"}])
    video(d, "new-one", "2026-10-12T0200Z")
    res = ps.place_plan(CH, ["old-one", "new-one"], d, NOW)
    assert res["ok"] and not res["refusals"], res["refusals"]
    it = {i["slug"]: i for i in res["items"]}
    assert it["old-one"]["ok"] and it["old-one"]["stale"] is True
    assert it["old-one"]["age_basis"] == "news" and it["old-one"]["age_days"] > 14
    assert it["new-one"]["ok"] and it["new-one"]["stale"] is False
    assert "устарел" in res["lines"][0] and "устарел" not in res["lines"][1]
    res = ps.place_confirm(CH, ["old-one"], res["base_sha256"], "test", "test", d, NOW)
    assert res["ok"] and res["written"], res["refusals"]
    assert res["items"][0]["placed"] and res["items"][0]["stale"] is True


def test_plan_takes_the_nearest_free_slots_in_order_and_writes_nothing():
    d = root()
    for s, b in (("a-one", "2026-10-12T0100Z"), ("b-two", "2026-10-12T0200Z"),
                 ("c-three", "2026-10-12T0300Z")):
        video(d, s, b)
    video(d, "not-ready", "2026-10-12T0400Z", ready=False)
    video(d, "no-card", "2026-10-12T0500Z", card=False)
    # 14.10 is taken by a day folder, 15.10 by the upload journal
    w(d / "publish" / CH / "2026-10-14" / "other.mp4", b"MP4")
    w(d / "publish" / "uploads.json", {"uploads": [{
        "channel": CH, "slug": "j", "video_id": "VID1", "publish_at": "2026-10-15T01:00:00+03:00",
        "publish_day": "2026-10-15"}]})
    before = ps.state_sha256(CH, d)
    res = ps.place_plan(CH, ["c-three", "a-one", "not-ready", "no-card", "ghost", "a-one"],
                        d, NOW)
    assert res["dry_run"] and not res["written"] and res["base_sha256"] == before
    it = {i["slug"]: i for i in res["items"][:5]}
    assert it["c-three"]["day"] == "2026-10-16" and it["a-one"]["day"] == "2026-10-17", it
    assert it["not-ready"]["refusals"][0]["code"] == "card_not_ready"
    assert it["no-card"]["refusals"][0]["code"] == "no_card"
    assert it["ghost"]["refusals"][0]["code"] == "not_in_queue"
    assert res["items"][5]["refusals"][0]["code"] == "duplicate"
    assert not res["ok"] and ps.state_sha256(CH, d) == before
    assert not (d / "publish" / CH / "2026-10-16").exists()


def test_the_horizon_keeps_a_video_past_min_feed_days_in_the_kopilka():
    """CF-0918: min_feed_days 3 on 13.10 - slots up to 16.10; 14 and 15 are taken,
    so one video gets 16.10 and the next stays in the копилка, `no_slot` with the
    reason beyond_horizon (the code the center knows)."""
    d = root(feed_days=3)
    for s, b in (("a-one", "2026-10-12T0100Z"), ("b-two", "2026-10-12T0200Z")):
        video(d, s, b)
    w(d / "publish" / CH / "2026-10-14" / "other.mp4", b"MP4")
    w(d / "publish" / CH / "2026-10-15" / "other2.mp4", b"MP4")
    res = ps.place_plan(CH, ["a-one", "b-two"], d, NOW)
    it = {i["slug"]: i for i in res["items"]}
    assert it["a-one"]["ok"] and it["a-one"]["day"] == "2026-10-16", it["a-one"]
    b = it["b-two"]
    assert not b["ok"] and b["beyond_horizon"] and b["refusals"][0]["code"] == "no_slot", b
    assert b["refusals"][0]["line"].startswith("beyond_horizon: b-two")
    assert "до 2026-10-16" in b["refusals"][0]["line"], b["refusals"][0]["line"]
    res = ps.place_confirm(CH, ["a-one", "b-two"], res["base_sha256"], "test", "test", d, NOW,
                           open_rows=[])
    assert res["written"] and (d / "publish" / CH / "2026-10-16" / "a-one.mp4").is_file()
    assert (d / "publish" / CH / "_queue" / "b-two.mp4").is_file()


# ------------------------------------------------------------------ CF-0918
def _future_script(b, slug, line):
    w(b / "03-content-researcher.json", {"channel": CH, "scripts": [
        {"script_id": f"s-{slug}", "topic_id": f"t-{slug}", "narration": line,
         "claims": [{"claim_id": "c1", "text": "The iPad mini 8 has an OLED screen."}]}]})


def test_news_or_evergreen_and_the_day_a_news_goes_stale():
    d = root()
    video(d, "dated", "2026-10-12T0100Z", news="2026-10-10T08:00:00+00:00")
    video(d, "source-only", "2026-10-12T0150Z", news="2026-10-10T08:00:00+00:00", words="")
    video(d, "forever", "2026-10-12T0200Z", sources=EVERGREEN, answered="2026-10-11")
    b = video(d, "coming", "2026-10-12T0300Z", sources=EVERGREEN, answered="2026-10-12")
    _future_script(b, "coming", "Apple's iPad mini will be released on November 6, 2026.")
    res = ps.stash(CH, d, NOW)
    by = {v["slug"]: v for v in res["videos"]}
    assert by["dated"]["feed_kind"] == "news" and by["dated"]["stale_at"] == "2026-10-24"
    assert by["source-only"]["feed_kind"] == "evergreen", "CF-0919: a dated source is not news"
    assert by["source-only"]["stale_at"] is None and by["source-only"]["age"]["stale"] is False
    assert by["forever"]["feed_kind"] == "evergreen" and by["forever"]["stale_at"] is None
    # a date ahead: the day the video's words stop being so, not 14 days from the acceptance
    assert by["coming"]["feed_kind"] == "news" and by["coming"]["stale_at"] == "2026-11-06"
    assert by["coming"]["news_why"] == "«will be released»"
    assert res["news"] == 2 and res["reserve"] == 0 and res["horizon"]["days"] == 14


def test_a_news_with_a_date_ahead_is_fresh_until_that_day():
    d = root()
    b = video(d, "premiere", "2026-10-12T0100Z", answered="2026-09-01",
              sources=[{"published_at": "2026-09-01T08:00:00+00:00"}])
    _future_script(b, "premiere", "The season is slated to premiere on October 20, 2026.")
    assert ps.stash(CH, d, NOW)["videos"][0]["age"]["stale"] is False
    v = ps.stash(CH, d, "2026-10-21T09:00:00+00:00")["videos"][0]
    assert v["stale_at"] == "2026-10-20" and v["age"]["stale"] is True, v["age"]


def test_the_driver_marks_a_disputed_video_and_the_mark_is_the_kind():
    d = root()
    video(d, "disputed", "2026-10-12T0100Z", sources=EVERGREEN)
    video(d, "other", "2026-10-12T0200Z", news="2026-10-10T08:00:00+00:00")
    bad = ps.set_kind(CH, "disputed", "soon", "driver", "t", d, NOW)
    assert not bad["ok"] and bad["refusals"][0]["code"] == "bad_kind", bad
    assert ps.set_kind(CH, "disputed", "news", "", "t", d, NOW)["refusals"][0]["code"] == "bad_who"
    assert ps.set_kind(CH, "ghost", "news", "driver", "t", d, NOW)["refusals"][0]["code"] \
        == "not_in_queue"
    res = ps.set_kind(CH, "disputed", "news", "driver", "Studio 04.11", d, NOW)
    assert res["ok"] and res["written"] and res["batch_id"] == "2026-10-12T0100Z", res
    by = {v["slug"]: v for v in ps.stash(CH, d, NOW)["videos"]}
    v = by["disputed"]
    assert v["feed_kind"] == "news" and v["kind_mark"]["by"] == "driver", v
    assert v["kind_mark"]["via"] == "Studio 04.11" and v["kind_mark"]["at"], v
    assert v["stale_at"] == "2026-10-26", v["stale_at"]      # the acceptance + 14
    assert "руками" in v["news_why"], v["news_why"]
    # the other way round, the last mark wins: no stale_at, no aging
    assert ps.set_kind(CH, f"{'2026-10-12T0200Z'}/other", "evergreen", "driver", "t", d, NOW)["ok"]
    assert ps.set_kind(CH, "disputed", "evergreen", "driver", "t", d, NOW)["ok"]
    by = {v["slug"]: v for v in ps.stash(CH, d, NOW)["videos"]}
    assert by["other"]["feed_kind"] == "evergreen" and by["other"]["stale_at"] is None
    assert by["other"]["age"]["stale"] is False
    assert by["disputed"]["feed_kind"] == "evergreen"
    marks = json.loads((d / "publish" / "feed-kinds.json").read_text(encoding="utf-8"))["marks"]
    assert len(marks) == 3 and marks[0]["task"] == "CF-0919"
    # the CLI
    assert ps.main(["kind", "--channel", CH, "disputed", "news", "--by", "driver", "--via", "t",
                    "--root", str(d), "--now", NOW]) == 0


def test_choose_puts_fresh_news_first_then_the_reserve_and_leaves_stale_news_out():
    d = root(feed_days=3)
    video(d, "ever-old", "2026-10-12T0100Z", sources=EVERGREEN, answered="2026-10-01")
    video(d, "ever-new", "2026-10-12T0200Z", sources=EVERGREEN, answered="2026-10-12")
    video(d, "news-new", "2026-10-12T0300Z", news="2026-10-12T08:00:00+00:00")
    video(d, "news-old", "2026-10-12T0400Z", news="2026-10-05T08:00:00+00:00")
    video(d, "news-gone", "2026-10-12T0500Z",
          sources=[{"published_at": "2026-09-01T08:00:00+00:00"}])
    order, skipped = ps.choose(CH, d, NOW)
    assert order == ["news-old", "news-new", "ever-old", "ever-new"], order
    assert [(x["slug"], x["reason"]) for x in skipped] == [("news-gone", "stale_news")]
    assert all(x["batch_id"] for x in skipped)
    assert ps.choose(CH, d, NOW, force=True)[0][0] == "news-gone"
    # --auto: as many as the horizon's free slots (14, 15, 16.10), the rest wait
    plan = ps.place_plan(CH, [], d, NOW, auto=True)
    assert plan["ok"], plan["refusals"]
    assert [(i["slug"], i["day"]) for i in plan["items"]] == [
        ("news-old", "2026-10-14"), ("news-new", "2026-10-15"), ("ever-old", "2026-10-16")]
    assert {x["slug"]: x["reason"] for x in plan["skipped"]} == {
        "news-gone": "stale_news", "ever-new": "beyond_horizon"}
    # a stale news named by hand is placed, with a warning
    hand = ps.place_plan(CH, ["news-gone"], d, NOW)
    assert hand["ok"] and any(x.startswith("STALE news-gone") for x in hand["items"][0]["warnings"])
    res = ps.place_confirm(CH, [], plan["base_sha256"], "test", "test", d, NOW, open_rows=[],
                           auto=True)
    assert res["written"] and [i["day"] for i in res["items"]] == [
        "2026-10-14", "2026-10-15", "2026-10-16"], res["items"]


def test_confirm_brings_a_reserve_video_back_with_its_video_id():
    d = root(feed_days=3)
    video(d, "kept", "2026-10-12T0100Z", sources=EVERGREEN, card=False)
    vid = "KEPTvideo01"
    w(d / "publish" / CH / "_queue" / "kept.md",
      f"# kept\n\nБатч `pipeline/{CH}/2026-10-12T0100Z`\n\n## Публикация\nСлот не назначен. "
      f"В Studio: ограниченный доступ, video_id {vid}\n\n## Карточка\nREADY-STUB\n")
    w(d / "publish" / "uploads.json", {"uploads": [{
        "channel": CH, "entry_id": f"{CH}/2026-10-12T0100Z/kept", "batch_id": "2026-10-12T0100Z",
        "slug": "kept", "video_id": vid, "publish_at": None, "publish_tz": "Europe/Moscow",
        "publish_day": None, "note": f"publish/{CH}/_queue/kept.md", "source": "studio",
        "recorded_at": "2026-10-01T00:00:00Z",
        "withdrawn": {"at": "2026-10-12T10:00:00Z", "from_at": "2026-10-20T01:00:00+03:00"}}]})
    v = ps.stash(CH, d, NOW)["videos"][0]
    assert v["reserve"] and v["video_id"] == vid and v["feed_kind"] == "evergreen"
    plan = ps.place_plan(CH, ["kept"], d, NOW)
    it = plan["items"][0]
    assert plan["ok"] and it["reserve"] and it["day"] == "2026-10-14", plan
    assert any(x.startswith(f"STUDIO kept ({vid})") for x in it["warnings"])
    res = ps.place_confirm(CH, ["kept"], plan["base_sha256"], "user", "center", d, NOW,
                           open_rows=[])
    assert res["ok"] and res["written"], res["refusals"]
    assert res["items"][0]["path"] == f"publish/{CH}/2026-10-14/kept.md"
    assert (d / "publish" / CH / "2026-10-14" / "kept.mp4").is_file()
    row = json.loads((d / "publish" / "uploads.json").read_text(encoding="utf-8"))["uploads"][0]
    assert row["publish_day"] == "2026-10-14" and "withdrawn" not in row
    assert row["rescheduled"][-1]["from_reserve"] and row["video_id"] == vid
    text = (d / "publish" / CH / "2026-10-14" / "kept.md").read_text(encoding="utf-8")
    assert "**2026-10-14 01:00 МСК** — возвращён из запаса" in text, text


def test_auto_gives_the_slot_of_a_video_without_a_ready_card_to_the_next_one():
    """CF-0919, the center's remark: a video with no ready card does not hold a slot."""
    d = root(feed_days=3)
    video(d, "a-no-card", "2026-10-12T0100Z", card=False, news="2026-10-05T08:00:00+00:00")
    video(d, "b-not-ready", "2026-10-12T0200Z", ready=False, news="2026-10-06T08:00:00+00:00")
    video(d, "c-news", "2026-10-12T0300Z", news="2026-10-07T08:00:00+00:00")
    video(d, "d-ever", "2026-10-12T0400Z", sources=EVERGREEN, answered="2026-10-01")
    video(d, "e-ever", "2026-10-12T0500Z", sources=EVERGREEN, answered="2026-10-02")
    video(d, "f-ever", "2026-10-12T0600Z", sources=EVERGREEN, answered="2026-10-03")
    order, skipped = ps.choose(CH, d, NOW)
    assert order == ["c-news", "d-ever", "e-ever", "f-ever"], order
    assert {x["slug"]: x["reason"] for x in skipped} == {"a-no-card": "no_card",
                                                         "b-not-ready": "card_not_ready"}
    assert ps.choose(CH, d, NOW, force=True)[0] == order        # force is about staleness
    plan = ps.place_plan(CH, [], d, NOW, auto=True)
    assert plan["ok"], plan["refusals"]
    assert [i["slug"] for i in plan["items"]] == ["c-news", "d-ever", "e-ever"]
    assert {x["slug"]: x["reason"] for x in plan["skipped"]} == {
        "a-no-card": "no_card", "b-not-ready": "card_not_ready", "f-ever": "beyond_horizon"}
    # named by hand, the same video is still refused with the same code
    hand = ps.place_plan(CH, ["a-no-card"], d, NOW)
    assert [r["code"] for r in hand["items"][0]["refusals"]] == ["no_card"]


def test_the_order_compares_days_not_strings():
    """CF-0919, the center's remark: a video accepted on 12.10 (a bare date) does
    not stand before a news of 12.10 08:00 for being a shorter string."""
    d = root(feed_days=3)
    video(d, "a-news-dated", "2026-10-12T0100Z", news="2026-10-12T08:00:00+00:00",
          answered="2026-10-12")
    video(d, "b-accepted-only", "2026-10-12T0200Z", sources=[{"title": "no date"}],
          words="It is coming soon.", answered="2026-10-12")
    order = ps.choose(CH, d, NOW)[0]
    assert order == ["a-news-dated", "b-accepted-only"], order
    by = {v["slug"]: v for v in ps.stash(CH, d, NOW)["videos"]}
    assert by["a-news-dated"]["stale_at"] == by["b-accepted-only"]["stale_at"] == "2026-10-26"
    # the evergreen ones: a date and a timestamp of one day are one day
    d = root(feed_days=3)
    video(d, "b-ever", "2026-10-12T0300Z", sources=EVERGREEN, answered="2026-10-12")
    video(d, "a-ever", "2026-10-12T0400Z", sources=EVERGREEN, answered="2026-10-12")
    log = d / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    next(r for r in doc["acceptances"] if r["slug"] == "a-ever")[
        "answered_at"] = "2026-10-12T05:00:00Z"
    w(log, doc)
    assert ps.choose(CH, d, NOW)[0] == ["a-ever", "b-ever"]
    assert [v["slug"] for v in ps.stash(CH, d, NOW)["videos"]] == ["a-ever", "b-ever"]


def _reserve_and_new(d, slug="percy", old="2026-11-01T0832Z", new="2026-11-04T1006Z"):
    """CF-0919, the shape of 04.11: a reserve video in `_reserve/` (withdrawn, in
    Studio) and a new video of the same name accepted into `_queue/`."""
    video(d, slug, old, queued=False, publish_path=False, words="")
    pub = d / "publish"
    w(pub / CH / "_reserve" / f"{slug}.mp4", b"OLD")
    w(pub / CH / "_reserve" / f"{slug}.md",
      f"# {slug}\n\nБатч `pipeline/{CH}/{old}`\n\n## Название\nold title\n\n## Публикация\n"
      f"Слот не назначен. В Studio: ограниченный доступ, video_id OLDvid00001.\n")
    w(pub / "uploads.json", {"uploads": [{
        "channel": CH, "entry_id": f"{CH}/{old}/{slug}", "batch_id": old, "slug": slug,
        "topic_id": f"t-{slug}", "video_id": "OLDvid00001", "publish_at": None,
        "publish_day": None, "publish_tz": "Europe/Moscow",
        "note": f"publish/{CH}/_reserve/{slug}.md", "source": "studio",
        "recorded_at": "2026-10-01T00:00:00Z",
        "withdrawn": {"at": "2026-10-13T00:00:00Z", "from_at": "2026-11-08T01:00:00+03:00",
                      "from_day": "2026-11-08", "from_note": f"publish/{CH}/2026-11-08/{slug}.md",
                      "by": "driver", "via": "studio", "task": "CF-0918"}}]})
    doc = json.loads((pub / "acceptance-log.json").read_text(encoding="utf-8"))
    doc["acceptances"][0]["publish_path"] = f"publish/{CH}/_reserve/{slug}.mp4"
    w(pub / "acceptance-log.json", doc)
    video(d, slug, new)
    return old, new


def test_the_pile_shows_the_reserve_and_a_new_video_of_one_name():
    d = root()
    old, new = _reserve_and_new(d)
    res = ps.stash(CH, d, NOW)
    got = {v["batch_id"]: v for v in res["videos"]}
    assert set(got) == {old, new}, res["videos"]
    assert got[old]["bucket"] == "_reserve" and got[old]["reserve"]
    assert got[old]["video_id"] == "OLDvid00001"
    assert got[new]["bucket"] == "_queue" and not got[new]["reserve"]
    assert got[new]["video_id"] is None


def test_a_name_two_videos_share_is_refused_with_a_hint_and_placed_by_batch():
    d = root()
    old, new = _reserve_and_new(d)
    plan = ps.place_plan(CH, ["percy"], d, NOW)
    assert not plan["ok"], plan["items"]
    line = " ".join(r["line"] for r in plan["items"][0]["refusals"])
    assert f"{new}/percy" in line and f"{old}/percy" in line and "человек" not in line, line
    named = ps.place_plan(CH, [f"{new}/percy"], d, NOW)
    assert named["ok"] and not named["items"][0].get("reserve"), named["items"]
    two = ps.place_plan(CH, [f"{new}/percy", f"{old}/percy"], d, NOW)
    assert two["ok"], two["items"]
    assert two["items"][0]["slot"] != two["items"][1]["slot"]
    twice = ps.place_plan(CH, [f"{new}/percy", f"{new}/percy"], d, NOW)
    assert not twice["ok"]


def test_choose_names_the_batch_when_a_name_is_shared():
    d = root()
    old, new = _reserve_and_new(d)
    order, _skipped = ps.choose(CH, d, NOW)
    assert order == [f"{new}/percy", f"{old}/percy"], order     # the news first, as ever
    auto = ps.place_plan(CH, [], d, NOW, auto=True)
    assert auto["ok"], auto["items"]
    assert [(i["slug"], bool(i.get("reserve"))) for i in auto["items"]] \
        == [("percy", False), ("percy", True)]
    assert auto["items"][0]["slot"] != auto["items"][1]["slot"]


def test_a_pair_in_reserve_with_no_withdrawn_row_is_not_placed():
    d = root()
    video(d, "lost", "2026-10-11T0000Z", queued=False, publish_path=False)
    w(d / "publish" / CH / "_reserve" / "lost.mp4", b"x")
    plan = ps.place_plan(CH, ["lost"], d, NOW)
    assert not plan["ok"]
    assert "_reserve/" in plan["items"][0]["refusals"][0]["line"], plan["items"]


def test_confirm_places_in_order_and_refuses_per_video():
    d = root()
    video(d, "a-one", "2026-10-12T0100Z")
    video(d, "b-two", "2026-10-12T0200Z", where="rebuilds")
    video(d, "held-one", "2026-10-12T0300Z")
    w(d / "publish" / "publication-holds.json", {"holds": [{
        "hold_id": f"{CH}/2026-10-12T0300Z/t-held-one", "channel": CH,
        "batch_id": "2026-10-12T0300Z", "topic_id": "t-held-one", "verdict": "review",
        "reason_code": "compliance_review_hold"}]})
    order = ["b-two", "held-one", "a-one"]
    plan = ps.place_plan(CH, order, d, NOW)
    assert [i["ok"] for i in plan["items"]] == [True, False, True], plan["items"]
    assert plan["items"][1]["refusals"][0]["code"] == "held"
    base = plan["base_sha256"]
    bad = ps.place_confirm(CH, order, base, by="", via="center", root=d, now=NOW, open_rows=[])
    assert bad["refusals"][0]["code"] == "bad_who" and not bad["written"]
    stale = ps.place_confirm(CH, order, "0" * 64, by="user", via="center", root=d, now=NOW,
                             open_rows=[])
    assert [r["code"] for r in stale["refusals"]] == ["check_changed", "held"]
    assert not stale["written"] and ps.state_sha256(CH, d) == base
    going = ps.place_confirm(CH, order, base, by="user", via="center", root=d, now=NOW,
                             open_rows=[(d / "pipeline" / CH / "2026-10-13T1000Z", None, True)])
    assert "batch_open" in [r["code"] for r in going["refusals"]] and not going["written"]
    assert ps.state_sha256(CH, d) == base
    res = ps.place_confirm(CH, order, base, by="user", via="center", root=d, now=NOW,
                           open_rows=[])
    assert res["written"] and res["new_sha256"] != base
    it = {i["slug"]: i for i in res["items"]}
    assert it["b-two"]["placed"] and it["b-two"]["day"] == "2026-10-14", it["b-two"]
    assert it["a-one"]["placed"] and it["a-one"]["day"] == "2026-10-15", it["a-one"]
    assert [r["code"] for r in res["refusals"]] == ["held"]
    for s, day in (("b-two", "2026-10-14"), ("a-one", "2026-10-15")):
        assert (d / "publish" / CH / day / f"{s}.mp4").is_file()
        assert f"**{day} 01:00 МСК**" in (d / "publish" / CH / day / f"{s}.md").read_text(
            encoding="utf-8")
    assert (d / "publish" / CH / "_queue" / "held-one.mp4").is_file()
    log = json.loads((d / "publish" / "acceptance-log.json").read_text(encoding="utf-8"))
    paths = {r["slug"]: r["publish_path"] for r in log["acceptances"]}
    assert paths["a-one"] == f"publish/{CH}/2026-10-15/a-one.mp4", paths


def _git(d, *args):
    import subprocess
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True,
                          text=True, env=env).stdout


def test_confirm_touched_is_what_git_status_shows():
    """`touched` of a confirm = the paths `git status` shows after it in a git
    root (created, modified, removed - a move is both paths); the plan and a
    refused confirm say `touched: []`."""
    d = root()
    video(d, "a-one", "2026-10-12T0100Z")
    video(d, "b-two", "2026-10-12T0200Z", where="rebuilds")
    video(d, "held-one", "2026-10-12T0300Z")
    w(d / "publish" / "publication-holds.json", {"holds": [{
        "hold_id": f"{CH}/2026-10-12T0300Z/t-held-one", "channel": CH,
        "batch_id": "2026-10-12T0300Z", "topic_id": "t-held-one", "verdict": "review",
        "reason_code": "compliance_review_hold"}]})
    w(d / ".gitignore", "*.lock\n")              # as the factory's .gitignore has it
    _git(d, "init", "-q")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "base")
    order = ["b-two", "held-one", "a-one"]
    plan = ps.place_plan(CH, order, d, NOW)
    assert plan["touched"] == []
    stale = ps.place_confirm(CH, order, "0" * 64, by="user", via="center", root=d, now=NOW,
                             open_rows=[])
    assert stale["touched"] == [] and not stale["written"]
    res = ps.place_confirm(CH, order, plan["base_sha256"], by="user", via="center", root=d,
                           now=NOW, open_rows=[])
    assert res["written"]
    status = _git(d, "status", "--porcelain", "-uall", "--no-renames")
    shown = sorted({line[3:] for line in status.splitlines() if line.strip()})
    assert res["touched"] == shown, (res["touched"], shown)
    assert res["touched"] == sorted(set(res["touched"]))
    for s, day in (("b-two", "2026-10-14"), ("a-one", "2026-10-15")):
        assert f"publish/{CH}/{day}/{s}.md" in res["touched"]
        assert f"publish/{CH}/{day}/{s}.mp4" in res["touched"]
        assert f"publish/{CH}/_queue/{s}.mp4" in res["touched"]
    assert "publish/acceptance-log.json" in res["touched"]
    assert not any("held-one" in t for t in res["touched"])


def test_no_slot_config_and_unknown_channel_are_refused_whole():
    d = root(slot=False)
    video(d, "a-one", "2026-10-12T0100Z")
    res = ps.place_plan(CH, ["a-one"], d, NOW)
    assert [r["code"] for r in res["refusals"]][0] == "no_queue"
    res = ps.place_plan("nochan", ["a-one"], d, NOW)
    assert res["refusals"][0]["code"] == "unknown_channel"
    assert ps.place_plan(CH, [], root(), NOW)["refusals"][0]["code"] == "empty_order"


def test_cli_show_and_plan():
    d = root()
    video(d, "a-one", "2026-10-12T0100Z")
    import io
    from contextlib import redirect_stdout
    out = io.StringIO()
    with redirect_stdout(out):
        assert ps.main(["show", "--channel", CH, "--root", str(d), "--now", NOW, "--json"]) == 0
    assert json.loads(out.getvalue())["count"] == 1
    video(d, "b-old", "2026-10-12T0200Z", sources=[{"published_at": "2026-08-01T00:00:00Z"}])
    out = io.StringIO()
    with redirect_stdout(out):
        assert ps.main(["show", "--channel", CH, "--root", str(d), "--now", NOW]) == 0
    text = out.getvalue()
    assert "b-old" in text and "УСТАРЕЛ" in text and "устаревших 1" in text, text
    out = io.StringIO()
    with redirect_stdout(out):
        assert ps.main(["plan", "--channel", CH, "a-one", "--root", str(d), "--now", NOW]) == 0
    assert "2026-10-14 01:00 МСК" in out.getvalue()



def test_a_version_the_rule_could_not_tell_from_a_new_video_is_the_drivers_list():
    """CF-0921: `other_version_placed` is off the bus; what the driver still has to
    decide - a version only for want of a topic or a fact on the record - is listed
    in `other_version` (and in `show`) with the `--other-version-ok` command; a sure
    version (the same topic) is listed nowhere."""
    import io
    from contextlib import redirect_stdout
    d = root()
    for slug in ("sure", "unsure"):
        video(d, slug, "2026-10-01T0100Z", queued=False, publish_path=False,
              answered="2026-10-01")
        video(d, slug, "2026-10-12T0100Z", queued=False, publish_path=False,
              answered="2026-10-12")
    log = d / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    for r in doc["acceptances"]:
        if r["batch_id"] == "2026-10-01T0100Z":
            r["publish_path"] = f"publish/{CH}/2026-10-07/{r['slug']}.mp4"
        elif r["slug"] == "unsure":
            r["topic_id"] = "t-unsure-2"          # another topic, no fact on either row
    w(log, doc)
    res = ps.stash(CH, d, NOW)
    assert res["not_queued"] == [], res["not_queued"]
    [v] = res["other_version"]
    assert v["entry_id"] == f"{CH}/2026-10-12T0100Z/unsure"
    assert v["queue_code"] == "other_version_placed"
    assert v["other_entry"] == f"{CH}/2026-10-01T0100Z/unsure"
    assert v["other_path"] == f"publish/{CH}/2026-10-07/unsure.mp4"
    assert "факта нет" in v["other_why"]
    assert v["repair"].endswith(f"--entry {v['entry_id']} --other-version-ok --apply")
    out = io.StringIO()
    with redirect_stdout(out):
        assert ps.main(["show", "--channel", CH, "--root", str(d), "--now", NOW]) == 0
    text = out.getvalue()
    assert "ВЕРСИЯ ИЛИ НОВЫЙ? " + v["entry_id"] in text and "--other-version-ok" in text, text
    assert "/sure" not in text, text


# --------------------------------------------------------------------------
# CF-0855: a new video under a name that already went out (23.10 Tech `anthropic`)
# --------------------------------------------------------------------------

def _fact(script, text):
    return {"task": "CF-0440", "script_id": script, "fact_text": text,
            "fact_source": {"name": "Wikipedia", "id": "wikipedia", "tier": 2,
                            "url": "https://en.wikipedia.org/wiki/Anthropic#History"}}


def test_the_2310_case_a_new_video_of_a_name_in_the_journal_gets_the_stash_and_a_card():
    """23.10: `anthropic` of 20.10 is in the upload journal and in its day folder;
    `anthropic` of 23.10 (another topic, another fact of the same Wikipedia
    section) is accepted - it must go into the копилка, get its card and a slot
    of its own, and the old pair must stay where it is."""
    import acceptance                                           # noqa: PLC0415
    d = root()
    old_b, new_b = "2026-10-10T1448Z", "2026-10-12T0831Z"
    video(d, "anthropic", old_b, queued=False, publish_path=False, answered="2026-10-10")
    video(d, "anthropic", new_b, queued=False, publish_path=False, answered="2026-10-12")
    day = d / "publish" / CH / "2026-10-14"
    old_note = (f"# anthropic\n\nБатч `pipeline/{CH}/{old_b}`\n\n## Публикация\n"
                f"**2026-10-14 01:00 МСК**\n")
    w(day / "anthropic.md", old_note)
    w(day / "anthropic.mp4", b"OLD")
    w(d / "publish" / "uploads.json", {"uploads": [{
        "channel": CH, "slug": "anthropic", "batch_id": old_b,
        "entry_id": f"{CH}/{old_b}/anthropic", "video_id": "VF9Nw3wxRRg",
        "publish_at": "2026-10-14T01:00:00+03:00", "publish_day": "2026-10-14"}]})
    log = d / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    old_row, new_row = doc["acceptances"]
    old_row.update(publish_path=f"publish/{CH}/2026-10-14/anthropic.mp4",
                   profile=_fact(f"s-old", "The ban was lifted on June 30."))
    new_row.update(topic_id="t-anthropic-2", profile=_fact(
        "s-new", "Anthropic alleged the companies generated over 16 million chats."))
    w(log, doc)
    # the new topic in its batch (the helper wrote t-anthropic for both)
    w(d / "pipeline" / CH / new_b / "01-trend-hunter.json",
      {"topics": [{"topic_id": "t-anthropic-2", "evidence": {"sources": []}}]})

    # the копилка sees it as accepted with no place - not hidden as "another version"
    res = ps.stash(CH, d, NOW)
    lost = [v for v in res["not_queued"] if v["entry_id"] == f"{CH}/{new_b}/anthropic"]
    assert lost and lost[0]["queue_code"] == "placed", res["not_queued"]
    assert lost[0]["batch_id"] == new_b

    # the verdict's own step queues it and starts its card (autobuild off: the call is made)
    rows = acceptance.entries(path=log)
    new = next(r for r in rows if r["entry_id"] == f"{CH}/{new_b}/anthropic")
    os.environ["PUBLISH_CARD_AUTOBUILD"] = "0"
    try:
        q = acceptance._queue_verdict(new, rows, d, d / "publish")
    finally:
        os.environ.pop("PUBLISH_CARD_AUTOBUILD", None)
    assert q["code"] == "placed" and not q["left_out"], q
    assert q["namesake"]["entry_id"] == f"{CH}/{old_b}/anthropic"
    assert q["card_build"]["ok"] and q["card_build"]["skipped"] == "off"
    acceptance.write_log(rows, path=log)
    assert (d / "publish" / CH / "_queue" / "anthropic.mp4").is_file()

    # in the pile, as itself: its own row, its own card from its own batch
    res = ps.stash(CH, d, NOW)
    assert not [v for v in res["not_queued"] if v["slug"] == "anthropic"], res["not_queued"]
    [v] = [v for v in res["videos"] if v["slug"] == "anthropic"]
    assert v["entry_id"] == f"{CH}/{new_b}/anthropic" and v["batch_id"] == new_b
    assert v["card"]["present"] and v["card"]["ready"] and v["card"]["batch"] == new_b

    # placed onto a slot of its own; the old pair and its day stay as they are
    plan = ps.place_plan(CH, ["anthropic"], d, NOW)
    assert plan["ok"] and plan["items"][0]["day"] == "2026-10-15", plan
    done = ps.place_confirm(CH, ["anthropic"], plan["base_sha256"], by="user", via="center",
                            root=d, now=NOW, open_rows=[])
    assert done["written"] and done["items"][0]["placed"], done
    new_day = d / "publish" / CH / "2026-10-15"
    assert f"pipeline/{CH}/{new_b}" in (new_day / "anthropic.md").read_text(encoding="utf-8")
    assert (day / "anthropic.md").read_text(encoding="utf-8") == old_note
    assert (day / "anthropic.mp4").read_bytes() == b"OLD"
    paths = {r["entry_id"]: r["publish_path"] for r in json.loads(
        log.read_text(encoding="utf-8"))["acceptances"]}
    assert paths[f"{CH}/{old_b}/anthropic"] == f"publish/{CH}/2026-10-14/anthropic.mp4"
    assert paths[f"{CH}/{new_b}/anthropic"] == f"publish/{CH}/2026-10-15/anthropic.mp4"


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

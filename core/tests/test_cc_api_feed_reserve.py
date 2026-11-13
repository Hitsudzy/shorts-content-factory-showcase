#!/usr/bin/env python3
"""CC-0179 (CF-0918, the user's policy of 04.11: the feed 3 days ahead, the rest a
reserve of evergreen videos) in the API:

    POST /api/publish/{c}/move/plan        {moves, unplace, withdraw [slug]}
    POST /api/publish/{c}/move/confirm     {confirm, base_sha256?}
    GET  /api/publish/{c}/stash            bucket, feed_kind, kind_mark, news_why,
                                           stale_at, reserve, video_id; news, reserve,
                                           horizon
    POST /api/publish/{c}/stash/place/plan {order} | {auto, force?}
    POST /api/publish/{c}/stash/place      {confirm}
    GET  /api/publish/{c}/queue, /studio, /api/batches/.../videos - a row of
                                           uploads.json with `withdrawn`

Pinned: the withdraw goes through the factory's own move_plan / move_confirm by
user via center, one factory commit; each of its refusals has its code and a
Russian text; a withdrawn row breaks no read and shows as withdrawn; the копилка
gives the new fields and an older answer without them still serves; the auto
placement takes the factory's order and `skipped`, spends a token, and the
return of a reserve video commits the journal.

CC-0181 (CF-0919, factory 2.51): the reserve lives in `_reserve/`, the kind comes from
the video's own fact, `reserve_taken` and the auto's card reasons have Russian texts.

In-process (TestClient) against stand-in factory roots in temp dirs; a fixed clock
and the open batches handed in. No live data, no network.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import H, _w, client, git                  # noqa: E402
from test_cc_api_publish_move import BATCH as JOURNAL_BATCH          # noqa: E402
from test_cc_api_publish_move import (CH, CONFIRM, IDS, PLAN, files, head, journal, jrow,  # noqa: E402
                                      post, world)
from test_cc_api_publish_stash import video as pile_video             # noqa: E402
from test_cc_api_publish_stash import world as pile_world             # noqa: E402
from test_cc_api_videos_upload import B1 as UB1                       # noqa: E402
from test_cc_api_videos_upload import tree as upload_tree             # noqa: E402

from api import factory, publish_move, publish_stash                # noqa: E402


def committed(root):
    return sorted(git(root, "show", "--name-only", "--format=", "HEAD").split())


def clean(root):
    return git(root, "status", "--porcelain").strip() == ""


# ----------------------------------------------------------------- the withdraw
def test_the_plan_of_a_withdraw_writes_nothing_and_gives_a_token():
    root = world()
    c = client(root)
    before, sha = files(root), head(root)
    s, p = post(c, PLAN, {"withdraw": ["openai"]})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert p["withdraw"] == ["openai"] and p["moves"] == [] and p["unplace"] == []
    assert (p["withdrawn"], p["moved"], p["unplaced"]) == (1, 0, 0), p
    it = p["items"][0]
    assert it["op"] == "withdraw" and it["in_studio"] and it["video_id"] == IDS["openai"], it
    assert it["from_day"] == "2026-10-26" and it["day"] is None and it["reserve"] is False, it
    assert any(w.startswith("STUDIO openai") for w in it["warnings"]), it["warnings"]
    assert files(root) == before and head(root) == sha, "a plan writes nothing"


def test_the_confirm_withdraws_by_user_via_center_and_the_factory_commits_once():
    root = world()
    c = client(root)
    _s, p = post(c, PLAN, {"withdraw": ["openai"]})
    sha = head(root)
    s, r = post(c, CONFIRM, {"confirm": p["confirm"], "base_sha256": p["base_sha256"]})
    assert s == 200 and r["ok"] and r["written"] and not r["dry_run"], r
    assert r["withdraw"] == ["openai"] and r["withdrawn"] == 1, r
    assert r["commit"] == head(root) and r["commit"] != sha, r
    assert (r["by"], r["via"]) == ("user", "center")
    it = r["items"][0]
    assert it["path"] == f"publish/{CH}/_reserve/openai.md", it
    assert it["journal"] == {"from_at": "2026-10-26T01:00:00+03:00", "to_at": None}, it
    row = journal(root)["openai"]
    assert row["publish_at"] is None and row["publish_day"] is None, row
    assert row["withdrawn"]["by"] == "user" and row["withdrawn"]["via"] == "center", row
    assert row["withdrawn"]["from_day"] == "2026-10-26", row
    pub = root / "publish" / CH
    assert (pub / "_reserve" / "openai.md").is_file() and (pub / "_reserve" / "openai.mp4").is_file()
    assert not (pub / "2026-10-26").exists() or not list((pub / "2026-10-26").glob("openai*"))
    assert "publish/uploads.json" in committed(root) and clean(root), committed(root)


def test_a_withdraw_and_moves_are_one_plan():
    """ipad-mini of 04.11: the day is freed by a withdraw in the same plan."""
    root = world()
    c = client(root)
    s, p = post(c, PLAN, {"withdraw": ["openai"],
                          "moves": [{"slug": "iphone-duo", "day": "2026-10-26"}]})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert [it["op"] for it in p["items"]] == ["withdraw", "move"], p["items"]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["withdrawn"] == 1 and r["moved"] == 1, r
    rows = journal(root)
    assert rows["iphone-duo"]["publish_day"] == "2026-10-26" and rows["openai"]["withdrawn"]


def test_a_video_of_the_reserve_comes_back_by_a_move_with_no_new_upload():
    root = world()
    c = client(root)
    _s, p = post(c, PLAN, {"withdraw": ["openai"]})
    post(c, CONFIRM, {"confirm": p["confirm"]})
    s, p = post(c, PLAN, {"moves": [{"slug": "openai", "day": "2026-10-27"}]})
    assert s == 200 and p["ok"], p
    it = p["items"][0]
    assert it["reserve"] is True and it["from_day"] is None and it["from_slot"] is None, it
    assert any("comes back from the копилка" in w for w in it["warnings"]), it["warnings"]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["moved"] == 1 and r["items"][0]["journal"]["from_at"] is None, r
    row = journal(root)["openai"]
    assert row["publish_day"] == "2026-10-27" and not row.get("withdrawn"), row
    assert row["video_id"] == IDS["openai"] and clean(root)


def test_a_move_past_the_horizon_is_written_with_a_warning():
    root = world()
    s, p = post(client(root), PLAN, {"moves": [{"slug": "openai", "day": "2026-11-20"}]})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert any(w.startswith("HORIZON openai") for w in p["items"][0]["warnings"]), p["items"]


# ----------------------------------------------------------------- its refusals
def _refused(p, code):
    assert not p["ok"] and p["confirm"] is None, p
    assert [r["code"] for r in p["refusals"]] == [code], p["refusals"]
    r = p["refusals"][0]
    assert r["message"] == publish_move.MOVE_RU[code][1] and p["why"] == r["message"], p
    assert p["items"][0]["refusals"][0]["message"] == r["message"], p["items"]
    assert p["withdrawn"] == 0, p


def test_the_factory_s_withdraw_codes_are_all_known_in_russian():
    pm = factory.publish_move()
    assert {"not_in_studio", "in_reserve", "not_placed"} <= set(pm.WITHDRAW_REFUSALS)
    assert set(pm.WITHDRAW_REFUSALS) <= set(publish_move.MOVE_RU)
    # CF-0919's code stays known here even if the factory stops giving it (CF-0920)
    assert publish_move.MOVE_RU["reserve_taken"][0] == 409
    for code in pm.WITHDRAW_REFUSALS:
        status, text = publish_move.MOVE_RU[code]
        assert status == 409 and any("а" <= ch <= "я" for ch in text.lower()), code


def test_a_withdraw_with_the_name_and_the_name_with_its_batch_taken_is_reserve_taken():
    """CF-0920: a second video of a name lies as `<slug>~<batch>` - only that taken too refuses."""
    root = world()
    res = root / "publish" / CH / "_reserve"
    res.mkdir(parents=True)
    for suffix in (".md", ".mp4"):
        for stem in ("openai", f"openai~{JOURNAL_BATCH}"):
            (res / f"{stem}{suffix}").write_text("another video of this name\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "a video of the name in the reserve")
    before, sha = files(root), head(root)
    s, p = post(client(root), PLAN, {"withdraw": ["openai"]})
    assert s == 200, p
    _refused(p, "reserve_taken")
    assert "reserve" in p["refusals"][0]["line"], p["refusals"]
    assert files(root) == before and head(root) == sha


def test_a_video_not_in_studio_is_not_in_studio():
    root = world()
    s, p = post(client(root), PLAN, {"withdraw": ["gemini"]})
    assert s == 200, p
    _refused(p, "not_in_studio")


def test_a_video_already_in_the_reserve_is_in_reserve():
    root = world()
    c = client(root)
    _s, p = post(c, PLAN, {"withdraw": ["openai"]})
    post(c, CONFIRM, {"confirm": p["confirm"]})
    s, p = post(c, PLAN, {"withdraw": ["openai"]})
    assert s == 200, p
    _refused(p, "in_reserve")


def test_a_journal_row_with_no_pair_in_a_day_is_not_placed():
    root = world()
    day = root / "publish" / CH / "2026-10-26"
    for name in ("openai.md", "openai.mp4"):
        (day / name).unlink()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the pair is gone")
    s, p = post(client(root), PLAN, {"withdraw": ["openai"]})
    assert s == 200, p
    _refused(p, "not_placed")


def test_a_slot_already_past_is_published():
    root = world()
    rows = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    rows["uploads"].append(dict(jrow("openai", "2026-10-22"), slug="old",
                                entry_id=f"{CH}/2026-10-23T1504Z/old", video_id="oldVIDEO001"))
    _w(root / "publish" / "uploads.json", rows)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "an old row")
    s, p = post(client(root), PLAN, {"withdraw": ["old"]})
    assert s == 200, p
    _refused(p, "published")


def test_an_edit_named_twice_and_an_unknown_video_and_the_shape():
    root = world()
    c = client(root)
    s, p = post(c, PLAN, {"withdraw": ["openai"], "unplace": ["openai"]})
    assert s == 200 and "duplicate" in [r["code"] for r in p["refusals"]], p
    s, p = post(c, PLAN, {"withdraw": ["nobody"]})
    assert s == 200 and [r["code"] for r in p["refusals"]] == ["not_found"], p
    _s, p = post(c, PLAN, {"unplace": ["gemini"]})
    post(c, CONFIRM, {"confirm": p["confirm"]})
    s, p = post(c, PLAN, {"withdraw": ["gemini"]})       # in _queue/ with no row: the old code
    assert s == 200 and [r["code"] for r in p["refusals"]] == ["in_queue"], p
    s, p = post(c, PLAN, {"withdraw": ["x"] * 61})
    assert s == 422 and p["code"] == "invalid", p
    s, p = post(c, PLAN, {"withdraw": "openai"})
    assert s == 422, p


def test_a_token_of_a_withdraw_already_done_stops_with_its_code_and_writes_nothing():
    root = world()
    c = client(root)
    _s, a = post(c, PLAN, {"withdraw": ["openai"]})
    _s, b = post(c, PLAN, {"withdraw": ["openai"]})
    s, r = post(c, CONFIRM, {"confirm": b["confirm"]})
    assert s == 200, r
    sha = head(root)
    s, r = post(c, CONFIRM, {"confirm": a["confirm"]})
    assert s == 409 and r["code"] == "in_reserve", r
    assert r["message"] == publish_move.MOVE_RU["in_reserve"][1] and head(root) == sha, r


def test_the_token_is_bound_to_the_withdraws():
    root = world()
    c = client(root)
    _s, p = post(c, PLAN, {"withdraw": ["openai"]})
    s, r = post(c, CONFIRM, {"confirm": p["confirm"], "base_sha256": "0" * 64})
    assert s == 409 and r["code"] == "check_changed", r
    assert "withdrawn" not in journal(root)["openai"]


def test_an_open_batch_stops_a_withdraw():
    root = world()
    c = client(root)
    _s, p = post(c, PLAN, {"withdraw": ["openai"]})
    publish_move.FACTORY_KW["open_rows"] = [(root / "pipeline" / CH / "2026-10-23T2000Z",
                                             None, True)]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    publish_move.FACTORY_KW["open_rows"] = []
    assert s == 409 and r["code"] == "batch_open", r
    assert "withdrawn" not in journal(root)["openai"]


# ----------------------------------------------------------------- the копилка
RES = "RESvideo001"
ACTIONS = f"/api/publish/{CH}/stash"


def reserve_video(root, slug="r-res", answered="2026-10-09"):
    """A video withdrawn from the feed: its pair in _reserve/, its row with `withdrawn`."""
    batch = "2026-10-09T0100Z"
    pile_video(root, slug, batch, news=None, answered=answered)
    q = root / "publish" / CH / "_reserve"
    q.mkdir(parents=True, exist_ok=True)
    (root / "publish" / CH / "_queue" / f"{slug}.mp4").rename(q / f"{slug}.mp4")
    (root / "publish" / CH / "_queue" / f"{slug}.md").unlink(missing_ok=True)
    _w(q / f"{slug}.md", f"# {slug}\n\nБатч `pipeline/{CH}/{batch}/`\n\n## Название\n{slug} t\n\n"
                         f"## Публикация\nСлот не назначен. В Studio: ограниченный доступ, "
                         f"video_id {RES}\n\n## Настройки\n- Не для детей.\n")
    log = root / "publish" / "uploads.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    doc["uploads"].append({
        "channel": CH, "entry_id": f"{CH}/{batch}/{slug}", "batch_id": batch, "topic_id": f"t-{slug}",
        "slug": slug, "video_id": RES, "url": f"https://youtube.com/shorts/{RES}",
        "publish_at": None, "publish_tz": "Europe/Moscow", "publish_day": None,
        "note": f"publish/{CH}/_reserve/{slug}.md", "source": "studio",
        "recorded_at": "2026-10-09T17:00:00Z", "user_edited": False,
        "withdrawn": {"at": "2026-10-12T11:40:00Z", "by": "driver", "via": "studio",
                      "task": "CF-0918", "from_at": "2026-10-20T01:00:00+03:00",
                      "from_day": "2026-10-20", "from_note": f"publish/{CH}/2026-10-20/{slug}.md",
                      "studio": "Ограниченный доступ"},
        "rescheduled": [{"from_at": "2026-10-20T01:00:00+03:00", "to_at": None,
                         "at": "2026-10-12T11:40:00Z", "by": "driver", "via": "studio",
                         "withdrawn": True}]})
    _w(log, doc)


def future_words(root, slug, batch, words="This gadget will be released in November."):
    p = root / "pipeline" / CH / batch / "03-content-researcher.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["scripts"][0]["narration"] = words
    _w(p, doc)


def pile():
    """13.10 12:00, slots 14-16.10 inside the horizon (min_feed_days 3 by default):
    news in an order of their own, a stale one, evergreen ones, a reserve one."""
    root = pile_world()
    for name in ("a-one", "b-two", "c-raw"):
        (root / "publish" / CH / "_queue" / f"{name}.mp4").unlink()
    log = root / "publish" / "acceptance-log.json"
    _w(log, {"note": "test", "task": "CF-0328", "acceptances": []})
    pile_video(root, "n-new", "2026-10-12T0100Z", news="2026-10-12T08:00:00+00:00")
    pile_video(root, "n-old", "2026-10-12T0200Z", news="2026-10-08T08:00:00+00:00")
    pile_video(root, "z-stale", "2026-10-12T0300Z", news="2026-09-01T08:00:00+00:00")
    pile_video(root, "e-one", "2026-10-11T0100Z", news=None, answered="2026-10-11")
    pile_video(root, "f-soon", "2026-10-11T0200Z", news=None, answered="2026-10-12")
    future_words(root, "f-soon", "2026-10-11T0200Z")
    reserve_video(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the pile of 13.10")
    return root


def test_the_pile_gives_the_kind_the_reserve_and_the_horizon():
    root = pile()
    r = client(root).get(ACTIONS, headers=H)
    assert r.status_code == 200, r.text
    j = r.json()
    v = {x["slug"]: x for x in j["videos"]}
    assert v["n-old"]["feed_kind"] == "news", v["n-old"]
    assert v["n-old"]["news_why"] == "«is coming»", v["n-old"]     # CF-0919: the fact's words
    assert v["n-old"]["stale_at"] == "2026-10-22" and v["n-old"]["reserve"] is False
    assert v["n-old"]["video_id"] is None
    assert v["e-one"]["feed_kind"] == "evergreen" and v["e-one"]["news_why"] is None, v["e-one"]
    assert v["e-one"]["stale_at"] is None
    assert v["f-soon"]["feed_kind"] == "news" and v["f-soon"]["news_why"] == "«will be released»", \
        v["f-soon"]
    assert v["f-soon"]["stale_at"] == "2026-10-26", v["f-soon"]
    assert v["r-res"]["reserve"] is True and v["r-res"]["video_id"] == RES, v["r-res"]
    assert v["r-res"]["feed_kind"] == "evergreen", v["r-res"]
    assert v["r-res"]["bucket"] == "_reserve" and v["n-old"]["bucket"] == "_queue", v["r-res"]
    assert v["r-res"]["mp4"] == f"publish/{CH}/_reserve/r-res.mp4", v["r-res"]
    assert v["n-old"]["kind_mark"] is None, v["n-old"]
    assert j["news"] == 4 and j["reserve"] == 1, (j["news"], j["reserve"])
    assert j["horizon"] == {"days": 3, "last_day": "2026-10-16", "source": "по умолчанию"}, \
        j["horizon"]


def test_a_dated_source_alone_is_no_news_any_more():
    """CF-0919: Doctor Who (1964) has a dated source too - it is where the topic was found."""
    root = pile()
    batch = "2026-10-12T0500Z"
    pile_video(root, "o-dated", batch, news="2026-09-01T08:00:00+00:00", answered="2026-10-12")
    p = root / "pipeline" / CH / batch / "03-content-researcher.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["scripts"][0]["claims"] = [{"text": "It first aired in 1964."}]
    _w(p, doc)
    v = {x["slug"]: x for x in client(root).get(ACTIONS, headers=H).json()["videos"]}["o-dated"]
    assert v["feed_kind"] == "evergreen" and v["news_why"] is None, v
    assert v["stale_at"] is None and v["age"]["stale"] is False, v
    assert v["age"]["basis"] == "accepted", v["age"]


def test_the_driver_s_mark_overrides_the_fact_and_shows():
    root = pile()
    _w(root / "publish" / "feed-kinds.json", {"task": "CF-0919", "marks": [
        {"channel": CH, "slug": "e-one", "batch_id": "2026-10-11T0100Z", "kind": "news",
         "by": "driver", "via": "terminal", "at": "2026-10-12T09:00:00Z", "task": "CF-0919"}]})
    r = client(root).get(ACTIONS, headers=H)
    assert r.status_code == 200, r.text
    v = {x["slug"]: x for x in r.json()["videos"]}["e-one"]
    assert v["feed_kind"] == "news" and v["news_why"].startswith("вид поставлен руками"), v
    m = v["kind_mark"]
    assert (m["kind"], m["by"], m["via"], m["task"]) == ("news", "driver", "terminal", "CF-0919"), m


def _in_queue_still(root, slug="r-res"):
    """A video withdrawn before `_reserve/` existed, --migrate-reserve not run yet."""
    pub = root / "publish" / CH
    for suffix in (".md", ".mp4"):
        (pub / "_reserve" / f"{slug}{suffix}").rename(pub / "_queue" / f"{slug}{suffix}")
    log = root / "publish" / "uploads.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    next(r for r in doc["uploads"] if r["slug"] == slug)["note"] = f"publish/{CH}/_queue/{slug}.md"
    _w(log, doc)


def test_a_reserve_video_not_migrated_yet_reads_as_reserve_in_the_queue_folder():
    root = pile()
    _in_queue_still(root)
    v = {x["slug"]: x for x in client(root).get(ACTIONS, headers=H).json()["videos"]}["r-res"]
    assert v["reserve"] is True and v["video_id"] == RES and v["bucket"] == "_queue", v


def test_one_name_in_the_queue_and_the_reserve_reads_by_its_bucket():
    """percy-jackson of 04.11: a new video of the name of a withdrawn one."""
    root = pile()
    batch = "2026-10-12T0600Z"
    pile_video(root, "r-res", batch, news=None, answered="2026-10-12")
    _w(root / "publish" / CH / "_queue" / "r-res.md",
       f"# r-res\n\nБатч `pipeline/{CH}/{batch}/`\n\n## Название\nnew r-res\n\n"
       f"## Публикация\nСлот не назначен.\n\n## Настройки\n- Не для детей.\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "a new video of the reserve's name")
    c = client(root)
    two = {x["bucket"]: x for x in c.get(ACTIONS, headers=H).json()["videos"]
           if x["slug"] == "r-res"}
    assert sorted(two) == ["_queue", "_reserve"], two
    assert two["_reserve"]["reserve"] is True and two["_queue"]["reserve"] is False, two
    r = c.get(f"/api/publish/{CH}/notes/r-res", params={"day": "_reserve"}, headers=H)
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["day"] == "_reserve" and n["path"] == f"publish/{CH}/_reserve/r-res.md", n
    assert n["title"] == "r-res t" and n["studio"] is None and n["studio_refusal"], n
    r = c.get(f"/api/publish/{CH}/notes/r-res", params={"day": "_queue"}, headers=H)
    assert r.status_code == 200 and r.json()["title"] == "new r-res", r.text
    # no day: the place of the name not in the upload journal - the new one
    r = c.get(f"/api/publish/{CH}/notes/r-res", headers=H)
    assert r.status_code == 200 and r.json()["day"] == "_queue", r.text


def _older(res):
    for v in res["videos"]:
        for k in ("bucket", "feed_kind", "kind_mark", "news_why", "stale_at", "reserve",
                  "video_id"):
            v.pop(k, None)
    for k in ("news", "reserve", "horizon"):
        res.pop(k, None)
    return res


def test_an_older_answer_without_the_new_fields_still_serves():
    root = pile()
    ps = factory.publish_stash()
    stash, plan = ps.stash, ps.place_plan

    def old_plan(*a, **k):
        res = plan(*a, **k)
        for it in res["items"]:
            for f in ("beyond_horizon", "feed_kind", "stale_at", "reserve", "video_id"):
                it.pop(f, None)
        return res

    c = client(root)
    ps.stash = lambda *a, **k: _older(stash(*a, **k))
    try:
        j = c.get(ACTIONS, headers=H).json()
        v = {x["slug"]: x for x in j["videos"]}["n-new"]
        assert (v["feed_kind"], v["news_why"], v["stale_at"], v["reserve"], v["video_id"]) == \
            ("evergreen", None, None, False, None), v
        assert (v["bucket"], v["kind_mark"]) == (None, None), v
        assert (j["news"], j["reserve"], j["horizon"]) == (0, 0, None), j
    finally:
        ps.stash = stash
    ps.place_plan = old_plan
    try:
        s, p = post(c, f"{ACTIONS}/place/plan", {"order": ["n-new"]})
        assert s == 200 and p["ok"], p
        it = p["items"][0]
        assert (it["beyond_horizon"], it["feed_kind"], it["reserve"]) == (False, None, False), it
        assert p["auto"] is False and p["skipped"] == [], p
    finally:
        ps.place_plan = plan


def test_a_slot_past_the_horizon_is_no_slot_with_beyond_horizon():
    root = pile()
    s, p = post(client(root), f"{ACTIONS}/place/plan",
                {"order": ["n-new", "n-old", "e-one", "f-soon"]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    it = {i["slug"]: i for i in p["items"]}
    assert it["e-one"]["day"] == "2026-10-16" and it["e-one"]["beyond_horizon"] is False, it
    assert it["f-soon"]["beyond_horizon"] is True and not it["f-soon"]["ok"], it["f-soon"]
    r = it["f-soon"]["refusals"][0]
    assert r["code"] == "no_slot" and r["line"].startswith("beyond_horizon: f-soon"), r
    assert r["message"] == publish_stash.PLACE_RU["no_slot"][1], r


def test_a_video_of_the_reserve_comes_back_with_the_journal_in_one_center_commit():
    root = pile()
    c = client(root)
    s, p = post(c, f"{ACTIONS}/place/plan", {"order": ["r-res"]})
    assert s == 200 and p["ok"] and p["confirm"], p
    it = p["items"][0]
    assert it["reserve"] is True and it["video_id"] == RES and it["feed_kind"] == "evergreen", it
    assert any(w.startswith(f"STUDIO r-res ({RES})") for w in it["warnings"]), it["warnings"]
    s, r = post(c, f"{ACTIONS}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["ok"] and r["placed"] == 1 and r["commit"] == head(root), r
    assert r["touched_from"] == "factory" and "publish/uploads.json" in r["committed"], r
    assert "из запаса" in git(root, "log", "-1", "--format=%B")
    row = journal(root)["r-res"]
    assert row["publish_day"] == "2026-10-14" and not row.get("withdrawn"), row
    assert (root / "publish" / CH / "2026-10-14" / "r-res.md").is_file()
    assert clean(root), git(root, "status", "--porcelain")


def test_an_uncommitted_journal_stops_only_a_plan_with_a_reserve_video():
    root = pile()
    log = root / "publish" / "uploads.json"
    log.write_text(log.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    c = client(root)
    s, p = post(c, f"{ACTIONS}/place/plan", {"order": ["r-res"]})
    assert s == 200 and not p["ok"] and p["refusals"][0]["code"] == "dirty", p
    s, p = post(c, f"{ACTIONS}/place/plan", {"order": ["n-new"]})
    assert s == 200 and p["ok"], p


def test_a_stale_news_video_named_by_hand_goes_with_a_warning():
    root = pile()
    s, p = post(client(root), f"{ACTIONS}/place/plan", {"order": ["z-stale"]})
    assert s == 200 and p["ok"] and p["items"][0]["stale"] is True, p
    assert any(w.startswith("STALE z-stale") for w in p["items"][0]["warnings"]), p["items"]


# ----------------------------------------------------------------- the auto placement
def test_the_auto_plan_takes_the_factory_s_order_and_says_what_waits():
    root = pile()
    c = client(root)
    before, sha = files(root), head(root)
    s, p = post(c, f"{ACTIONS}/place/plan", {"auto": True})
    assert s == 200 and p["ok"] and p["confirm"] and p["auto"] is True, p
    assert p["force"] is False and p["dry_run"] is True, p
    # by the day it goes stale (CF-0919: a day whatever it was counted from), then the name:
    # n-old 22.10; f-soon and n-new both 26.10
    assert p["order"] == ["n-old", "f-soon", "n-new"], p["order"]
    assert [i["slug"] for i in p["items"]] == p["order"]
    assert [i["day"] for i in p["items"]] == ["2026-10-14", "2026-10-15", "2026-10-16"], p["items"]
    skip = {x["slug"]: x for x in p["skipped"]}
    assert skip["z-stale"]["reason"] == "stale_news", skip
    assert skip["z-stale"]["message"] == publish_stash.SKIP_RU["stale_news"]
    assert skip["r-res"]["reason"] == "beyond_horizon", skip
    assert skip["e-one"]["message"] == publish_stash.SKIP_RU["beyond_horizon"]
    assert any(line.startswith("ждёт: z-stale") for line in p["lines"]), p["lines"]
    assert files(root) == before and head(root) == sha, "a plan writes nothing"


def test_one_accepted_day_sorts_by_name_whatever_the_form_of_its_date():
    """CF-0919: a date and a timestamp of one day are one day (as raw strings the date
    stood first). The pile and the evergreen part of the auto's order are this sort."""
    root = pile()
    pile_video(root, "a-stamp", "2026-10-11T0300Z", news=None, answered="2026-10-11T08:00:00Z")
    pile_video(root, "b-date", "2026-10-11T0400Z", news=None, answered="2026-10-11")
    pile_video(root, "c-stamp", "2026-10-11T0500Z", news=None, answered="2026-10-11T02:00:00Z")
    got = [x["slug"] for x in client(root).get(ACTIONS, headers=H).json()["videos"]
           if x["accepted_at"].startswith("2026-10-11")]
    assert got == ["a-stamp", "b-date", "c-stamp", "e-one"], got


def test_the_auto_s_card_reasons_wait_with_a_russian_message():
    root = pile()
    pile_video(root, "m-no-card", "2026-10-12T0700Z", news=None, answered="2026-10-01", card=False)
    pile_video(root, "m-unready", "2026-10-12T0800Z", news=None, answered="2026-10-01", ready=False)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "two videos with no card to place")
    s, p = post(client(root), f"{ACTIONS}/place/plan", {"auto": True})
    assert s == 200 and p["ok"], p
    assert not {"m-no-card", "m-unready"} & set(p["order"]), p["order"]
    skip = {x["slug"]: x for x in p["skipped"]}
    assert skip["m-no-card"]["reason"] == "no_card", skip
    assert skip["m-no-card"]["message"] == publish_stash.SKIP_RU["no_card"], skip
    assert skip["m-unready"]["reason"] == "card_not_ready", skip
    assert skip["m-unready"]["message"] == publish_stash.SKIP_RU["card_not_ready"], skip
    for code in ("no_card", "card_building", "card_not_ready", "note_differs", "stale_news",
                 "beyond_horizon"):
        [row] = publish_stash._skipped([{"slug": "x", "reason": code, "line": "x: in English"}])
        assert row["message"] == publish_stash.SKIP_RU[code], code
        assert any("а" <= ch <= "я" for ch in row["message"].lower()), code


def test_the_auto_confirm_spends_the_token_places_the_choice_and_commits_once():
    root = pile()
    c = client(root)
    _s, p = post(c, f"{ACTIONS}/place/plan", {"auto": True})
    s, r = post(c, f"{ACTIONS}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["ok"] and r["auto"] is True and r["placed"] == 3, r
    assert r["order"] == p["order"], r
    assert {x["slug"] for x in r["skipped"]} == {x["slug"] for x in p["skipped"]}, r["skipped"]
    assert all(x["message"] for x in r["skipped"]), r["skipped"]
    assert r["commit"] == head(root) and clean(root), git(root, "status", "--porcelain")
    pub = root / "publish" / CH
    assert (pub / "2026-10-14" / "n-old.md").is_file() and (pub / "2026-10-16" / "n-new.md").is_file()
    s, r = post(c, f"{ACTIONS}/place", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "confirm_unknown", r


def test_the_auto_force_lets_stale_news_in():
    root = pile()
    c = client(root)
    s, p = post(c, f"{ACTIONS}/place/plan", {"auto": True, "force": True})
    assert s == 200 and p["ok"] and p["force"] is True, p
    assert p["order"][0] == "z-stale" and "z-stale" not in {x["slug"] for x in p["skipped"]}, p
    assert any(w.startswith("STALE z-stale") for w in p["items"][0]["warnings"]), p["items"]
    s, r = post(c, f"{ACTIONS}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["force"] is True and r["items"][0]["slug"] == "z-stale", r
    assert (root / "publish" / CH / "2026-10-14" / "z-stale.md").is_file()


def test_the_auto_with_a_reserve_video_in_the_choice_commits_its_journal():
    root = pile()
    for slug in ("n-new", "n-old", "f-soon"):
        pub = root / "publish" / CH / "_queue"
        (pub / f"{slug}.mp4").unlink()
    log = root / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    doc["acceptances"] = [a for a in doc["acceptances"] if a["slug"] not in ("n-new", "n-old", "f-soon")]
    _w(log, doc)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "only the reserve and the evergreen one")
    c = client(root)
    s, p = post(c, f"{ACTIONS}/place/plan", {"auto": True})
    assert s == 200 and p["ok"] and p["order"] == ["r-res", "e-one"], p
    s, r = post(c, f"{ACTIONS}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["placed"] == 2, r
    assert "publish/uploads.json" in r["committed"] and clean(root), r
    assert journal(root)["r-res"]["publish_day"] == "2026-10-14"


def test_a_state_changed_since_the_auto_plan_is_check_changed():
    root = pile()
    c = client(root)
    _s, p = post(c, f"{ACTIONS}/place/plan", {"auto": True})
    pile_video(root, "n-later", "2026-10-12T0400Z", news="2026-10-09T08:00:00+00:00")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one more")
    s, r = post(c, f"{ACTIONS}/place", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "check_changed", r


def test_the_auto_with_nothing_to_place_says_so_and_gives_no_token():
    root = pile_world()
    for name in ("a-one", "b-two", "c-raw"):
        (root / "publish" / CH / "_queue" / f"{name}.mp4").unlink()
    _w(root / "publish" / "acceptance-log.json",
       {"note": "test", "task": "CF-0328", "acceptances": []})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "an empty pile")
    s, p = post(client(root), f"{ACTIONS}/place/plan", {"auto": True})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    assert [r["code"] for r in p["refusals"]] == ["empty_order"], p["refusals"]
    assert p["why"] == publish_stash.AUTO_EMPTY_RU and p["order"] == [], p


def test_the_auto_refuses_a_named_order_and_force_alone():
    root = pile()
    c = client(root)
    s, p = post(c, f"{ACTIONS}/place/plan", {"auto": True, "order": ["n-new"]})
    assert s == 422 and p["code"] == "invalid", p
    s, p = post(c, f"{ACTIONS}/place/plan", {"order": ["n-new"], "force": True})
    assert s == 422 and p["code"] == "invalid", p


# ----------------------------------------------------------------- a withdrawn row in the journal
def _withdrawn_world():
    root = world()
    c = client(root)
    _s, p = post(c, PLAN, {"withdraw": ["openai"]})
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200, r
    return root, c


def test_the_queue_and_studio_show_the_row_as_withdrawn():
    root, c = _withdrawn_world()
    q = c.get(f"/api/publish/{CH}/queue", headers=H).json()
    assert [o["slug"] for o in q["occupants"]].count("openai") == 0, q["occupants"]
    assert {s["day"]: s["taken_by"] for s in q["slots"]}.get("2026-10-26") is None, q["slots"]
    [w] = q["withdrawn"]
    assert w["slug"] == "openai" and w["video_id"] == IDS["openai"], w
    assert w["note"] == f"publish/{CH}/_reserve/openai.md", w
    assert w["url"] == f"https://youtube.com/shorts/{IDS['openai']}", w
    m = w["withdrawn"]
    assert (m["by"], m["via"], m["task"]) == ("user", "center", "CF-0918"), m
    assert m["from_at"] == "2026-10-26T01:00:00+03:00" and m["from_day"] == "2026-10-26", m
    assert m["from_note"] == f"publish/{CH}/2026-10-26/openai.md" and m["studio"], m
    s = c.get(f"/api/publish/{CH}/studio", headers=H).json()
    assert s["rows"] == 2 and [x["slug"] for x in s["withdrawn"]] == ["openai"], s
    st = c.get(f"/api/publish/{CH}/stash", headers=H).json()
    v = {x["slug"]: x for x in st["videos"]}["openai"]
    assert v["reserve"] is True and v["video_id"] == IDS["openai"], v
    assert st["reserve"] == 1, st


def test_old_rows_without_withdrawn_read_as_none_withdrawn():
    c = client(world())
    assert c.get(f"/api/publish/{CH}/queue", headers=H).json()["withdrawn"] == []
    s = c.get(f"/api/publish/{CH}/studio", headers=H).json()
    assert s["withdrawn"] == [] and s["rows"] == 2, s
    assert client(pile_world()).get(f"/api/publish/{CH}/queue", headers=H).json()["withdrawn"] == []


def test_a_removed_or_another_channel_s_withdrawn_row_is_not_shown():
    root, c = _withdrawn_world()
    log = root / "publish" / "uploads.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    rows = doc["uploads"]
    row = next(r for r in rows if r["slug"] == "openai")
    rows.append(dict(row, channel="demo", video_id="demoVIDEO01", slug="elsewhere"))
    row["removed_at"] = "2026-10-23T18:00:00Z"
    _w(log, doc)
    assert c.get(f"/api/publish/{CH}/queue", headers=H).json()["withdrawn"] == []


def test_every_read_of_publication_and_analytics_stands_on_a_withdrawn_row():
    root, c = _withdrawn_world()
    spec = c.get("/api/openapi.json").json()
    asked = 0
    for path, ops in spec["paths"].items():
        if "get" not in ops or not path.startswith(("/api/publish", "/api/analytics", "/api/studio")):
            continue
        tail = path.replace("{channel}", CH)
        if "{" in tail:
            continue
        r = c.get(tail, headers=H)
        asked += 1
        assert r.status_code < 500, (path, r.status_code, r.text[:400])
    assert asked >= 8, asked


def test_a_video_s_upload_carries_the_withdrawn_mark():
    root = upload_tree()
    log = root / "publish" / "uploads.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    mark = {"at": "2026-10-01T10:00:00Z", "by": "driver", "via": "studio", "task": "CF-0918",
            "from_at": "2026-10-02T01:00:00+03:00", "from_day": "2026-10-02",
            "from_note": "publish/reel/2026-10-02/delver.md", "studio": "Ограниченный доступ"}
    row = next(r for r in doc["uploads"] if r["video_id"] == "AAAAAAAAAA1")
    row.update(publish_at=None, publish_day=None, withdrawn=mark)
    _w(log, doc)
    r = client(root).get(f"/api/batches/reel/{UB1}/videos")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["uploads_error"] is None, j
    u = {v["slug"]: v["upload"] for v in j["videos"]}["delver"]
    assert u["video_id"] == "AAAAAAAAAA1" and u["withdrawn"] == mark, u
    assert u["publish_day"] is None and u["publish_at"] is None, u


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

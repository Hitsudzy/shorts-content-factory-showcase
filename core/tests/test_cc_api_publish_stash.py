#!/usr/bin/env python3
"""CC-0122: the channel's копилка in the center (`api/publish_stash.py` over
`agents/publisher/publish_stash.py` and `acceptance.repair_queue`, CF-0738):

    GET  /api/publish/{c}/stash                   the pile with its details
    POST /api/publish/{c}/stash/place/plan        place_plan + not_repo / dirty
    POST /api/publish/{c}/stash/place {confirm}   place_confirm + one commit
    POST /api/publish/{c}/stash/repair/plan       repair_queue dry run
    POST /api/publish/{c}/stash/repair {confirm}  repair_queue by user via center

Pinned: the pile's paths relative and the media routes only where they
serve; an unknown channel 404 in Russian; the plan writes nothing, says every
refusal in Russian and gives a token only when every video places; an
uncommitted change in what a placement writes is `dirty` (no token); the
confirm places in order and makes one commit of exactly the files it touched
- from git status (before/after) when the factory names none, from the
factory's `touched` when it does; an open batch of the channel is
`batch_open`, a moved state `check_changed`, a commit git refuses
`commit_refused` with nothing left staged; the repair puts a lost accepted
video into `_queue/` and the factory commits the record; the routes are
guarded writes; every refusal code has a Russian text; the aging rule of
CF-0741 (0.53.0) - age.basis news / accepted, age.days, age.stale strictly
past 14 days, the pile's stale count, the rule as staleness, the plan's and
confirm's items stale / age_days / age_basis and « (устарел: N дн.)» - no
refusal from age.

In-process (TestClient) against a stand-in factory root in a temp dir
(`tests/test_cc_api_batches.py` `factory_tree`: `reel`, one slot a day at
01:00 МСК, lead 2 h); a fixed clock and the open batches handed in
(`publish_stash.FACTORY_KW`); the card's readiness is a stand-in (the claim
check of CF-0555 is not what is pinned). No live data, no network.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import H, TMP, _w, client, factory_tree, git  # noqa: E402

import api                                                          # noqa: E402
from api import factory, publish_stash                              # noqa: E402

CH = "reel"
NOW = "2026-10-13T12:00:00+03:00"
GITIGNORE = ("/schedule/\npublish/*.mp4\npublish/**/*.mp4\npublish/acceptance-pending.jsonl\n"
             "publish/acceptance-pending.jsonl.tmp\npublish/acceptance-pending.lock\n")


def _ready_stub(text):
    return ("READY-STUB" in text, None if "READY-STUB" in text else "stub: not ready")


factory.collect().card().card_state = _ready_stub   # the claim check is not what is pinned


def video(d, slug, batch, where=CH, ready=True, card=True, queued=True,
          news="2026-10-10T08:00:00+00:00", answered="2026-10-12", title=None, title_ref=None):
    b = d / "pipeline" / where / batch
    sid, tid = f"s-{slug}", f"t-{slug}"
    # CF-0919: a video with a dated source is news here because its script says so
    _w(b / "03-content-researcher.json", {"channel": CH, "scripts": [
        {"script_id": sid, "topic_id": tid,
         "claims": [{"text": "It is coming soon."}] if news else []}]})
    _w(b / "05-video-editor.json", {"channel": CH, "videos": [
        {"slug": slug, "script_id": sid, "output_path": str(b / "videos" / f"{slug}.mp4")}]})
    topic = {"topic_id": tid, "evidence": {"sources": [
        {"published_at": news} if news else {"url": "https://example.invalid/evergreen"}]}}
    if title_ref:
        topic["title_ref"] = title_ref
    _w(b / "01-trend-hunter.json", {"topics": [topic]})
    (b / "videos").mkdir(parents=True, exist_ok=True)
    (b / "videos" / f"{slug}.mp4").write_bytes(b"MP4")
    (b / "videos" / f"{slug}.jpg").write_bytes(b"\xff\xd8JPG")
    if card:
        _w(b / "work" / "publish-card" / f"{slug}.md",
           f"# {slug}\n\nБатч `pipeline/{where}/{batch}`\n\n"
           + (f"## Название\n{title}\n\n" if title else "")
           + "## Публикация\nне назначена\n\n"
           f"## Карточка\n{'READY-STUB' if ready else 'not ready'}\n")
    if queued:
        q = d / "publish" / CH / "_queue"
        q.mkdir(parents=True, exist_ok=True)
        (q / f"{slug}.mp4").write_bytes(b"MP4")
    log = d / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    doc["acceptances"].append({
        "entry_id": f"{CH}/{batch}/{slug}", "slug": slug, "channel": CH, "batch_id": batch,
        "verdict": "accepted", "answered_at": answered, "recorded_at": f"{answered}T05:00:00Z",
        "topic_id": tid, "code_shas_source": f"pipeline/{where}/{batch}/05-video-editor.json",
        "publish_path": f"publish/{CH}/_queue/{slug}.mp4" if queued else None, "history": []})
    _w(log, doc)


def world(lost=False):
    root = factory_tree()
    _w(root / ".gitignore", GITIGNORE)
    _w(root / "publish" / "uploads.json", {"uploads": []})
    _w(root / "publish" / "README.md", "| ролик | статус |\n|---|---|\n"
                                       "| `reel/_queue/a-one.mp4` | ждёт слота |\n")
    _w(root / "publish" / "acceptance-log.json",
       {"note": "test", "task": "CF-0328", "acceptances": []})
    video(root, "a-one", "2026-10-12T0100Z")
    video(root, "b-two", "2026-10-12T0200Z", where="rebuilds", answered="2026-10-13")
    video(root, "c-raw", "2026-10-12T0300Z", ready=False)
    if lost:
        video(root, "lost-one", "2026-10-11T1000Z", queued=False, answered="2026-10-11")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the pile")
    publish_stash.FACTORY_KW.clear()
    publish_stash.FACTORY_KW.update({"now": NOW, "open_rows": []})
    return root


def get(c, path):
    r = c.get(path)
    return r.status_code, r.json()


def post(c, path, body=None):
    r = c.post(path, headers=H, json=body)
    return r.status_code, r.json()


def head(root):
    return git(root, "rev-parse", "HEAD")


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts
            and p.name != "acceptance-pending.lock"}


# ----------------------------------------------------------------- the contract
def test_the_contract_and_the_russian_texts():
    spec = client(world()).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    base = "/api/publish/{channel}/stash"
    assert "get" in spec["paths"][base]
    for tail in ("/place/plan", "/place", "/repair/plan", "/repair"):
        assert "post" in spec["paths"][base + tail], tail
    ps = factory.publish_stash()
    from api.app import STASH_PLACE_CODES
    assert set(ps.TOP_REFUSALS) | set(ps.ITEM_REFUSALS) <= set(publish_stash.PLACE_RU)
    assert set(STASH_PLACE_CODES) == set(publish_stash.PLACE_RU)
    for code, (_status, text) in publish_stash.PLACE_RU.items():
        assert any("а" <= ch <= "я" for ch in text.lower()), code
    assert set(publish_stash.REPAIR_RU) >= {"bad_who", "batch_open", "check_changed",
                                            "commit_refused", "not_found"}


def test_the_writes_need_the_session():
    root = world()
    c = client(root)
    for tail in ("/place/plan", "/place", "/repair/plan", "/repair"):
        r = c.post(f"/api/publish/{CH}/stash{tail}", json={"order": ["a-one"], "confirm": "x"})
        assert r.status_code == 403, (tail, r.text)


# ----------------------------------------------------------------- the pile
def test_the_pile_with_its_details_and_routes():
    root = world(lost=True)
    c = client(root)
    before = files(root)
    s, d = get(c, f"/api/publish/{CH}/stash")
    assert s == 200, d
    assert d["channel"] == CH and d["count"] == 3 and d["staleness"]["rule"] == "CF-0741", d
    assert d["stale"] == 0, d
    by = {v["slug"]: v for v in d["videos"]}
    a, b = by["a-one"], by["b-two"]
    assert a["kind"] == "batch" and b["kind"] == "rebuild", (a["kind"], b["kind"])
    assert a["mp4"] == f"publish/{CH}/_queue/a-one.mp4" and a["mp4_present"], a
    assert a["thumbnail"] == "pipeline/reel/2026-10-12T0100Z/videos/a-one.jpg", a
    assert a["card"]["present"] and a["card"]["ready"] and a["card"]["where"] == "batch"
    assert a["card"]["path"] == "pipeline/reel/2026-10-12T0100Z/work/publish-card/a-one.md"
    assert by["c-raw"]["card"]["ready"] is False, by["c-raw"]["card"]
    assert a["age"]["accepted_days"] == 1 and a["age"]["news_days"] == 3, a["age"]
    assert a["mp4_url"] == "/api/batches/reel/2026-10-12T0100Z/videos/a-one/mp4", a
    assert a["preview_url"] == "/api/batches/reel/2026-10-12T0100Z/videos/a-one/preview", a
    assert b["mp4_url"] == "/api/batches/rebuilds/2026-10-12T0200Z/videos/b-two/mp4", b
    assert c.get(a["mp4_url"]).status_code == 200 and c.get(b["preview_url"]).status_code == 200
    assert [v["slug"] for v in d["not_queued"]] == ["lost-one"], d["not_queued"]
    assert d["not_queued"][0]["queue_code"] == "placed" and not d["not_queued"][0]["in_queue"]
    assert str(root) not in json.dumps(d) and str(root.resolve()) not in json.dumps(d)
    assert files(root) == before, "a GET writes nothing"
    s, d = get(c, "/api/publish/nope/stash")
    assert s == 404 and d["code"] == "unknown_channel" and "Канала" in d["message"], d


def test_other_version_is_the_factory_s_list_with_its_command_and_empty_without_it():
    # CC-0186 (CF-0921): an accepted row the rule took for a version of a placed video
    # only for want of a fact on the record is `other_version` - the placed one, why,
    # the factory's --other-version-ok command as data; a sure version (the same topic)
    # is not listed; an older factory without the key reads as an empty list
    root = world()
    log = root / "publish" / "acceptance-log.json"
    for slug in ("sure", "unsure"):
        video(root, slug, "2026-10-01T0100Z", queued=False, answered="2026-10-01")
        video(root, slug, "2026-10-12T0400Z", queued=False, answered="2026-10-12")
    doc = json.loads(log.read_text(encoding="utf-8"))
    for r in doc["acceptances"]:
        if r["batch_id"] == "2026-10-01T0100Z":
            r["publish_path"] = f"publish/{CH}/2026-10-07/{r['slug']}.mp4"
        elif r["slug"] == "unsure":
            r["topic_id"] = "t-unsure-2"          # another topic, no fact on either row
    _w(log, doc)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "two versions")
    c = client(root)
    before = files(root)
    s, d = get(c, f"/api/publish/{CH}/stash")
    assert s == 200, d
    assert d["not_queued"] == [], d["not_queued"]
    [v] = d["other_version"]
    assert v["entry_id"] == f"{CH}/2026-10-12T0400Z/unsure" and v["slug"] == "unsure", v
    assert v["queue_code"] == "other_version_placed" and not v["in_queue"], v
    assert v["other_entry"] == f"{CH}/2026-10-01T0100Z/unsure", v
    assert v["other_path"] == f"publish/{CH}/2026-10-07/unsure.mp4", v
    assert "факта нет" in v["other_why"], v
    assert v["repair"] == (f"runlog acceptance --enqueue-accepted --entry {v['entry_id']} "
                           f"--other-version-ok --apply"), v
    assert v["mp4_url"] == f"/api/batches/{CH}/2026-10-12T0400Z/videos/unsure/mp4", v
    assert "card" in v and "title_clean" in v, v
    assert files(root) == before, "a GET writes nothing"
    spec = c.get("/api/openapi.json").json()["components"]["schemas"]
    assert {"other_entry", "other_path", "other_why"} <= set(spec["StashOtherVersion"][
        "properties"]), spec["StashOtherVersion"]
    assert "other_version" in spec["PublishStash"]["properties"]
    ps = factory.publish_stash()
    real = ps.stash

    def older(*a, **kw):
        out = real(*a, **kw)
        out.pop("other_version")
        return out
    ps.stash = older
    try:
        s, d = get(c, f"/api/publish/{CH}/stash")
    finally:
        ps.stash = real
    assert s == 200 and d["other_version"] == [], d


def test_the_title_from_the_card_else_the_topic_else_none_with_the_tags_cut():
    # CF-0750 (contract 0.57.0): title / title_source as the factory reads them
    # (the card's ## Название with the channel's « #shorts» - card; else the
    # topic's title_ref - topic; else null), card.title beside; title_clean
    # the same with the trailing hashtags cut, for display.
    root = factory_tree()
    _w(root / ".gitignore", GITIGNORE)
    _w(root / "publish" / "uploads.json", {"uploads": []})
    _w(root / "publish" / "README.md", "| ролик | статус |\n|---|---|\n")
    _w(root / "publish" / "acceptance-log.json",
       {"note": "test", "task": "CF-0328", "acceptances": []})
    video(root, "t-card", "2026-10-12T0100Z", title="Мозг стареет не везде #shorts",
          title_ref="Topic title of the card's video")
    video(root, "t-topic", "2026-10-12T0200Z", title_ref="Why octopuses dream")
    video(root, "t-none", "2026-10-12T0300Z", card=False)
    video(root, "t-lost", "2026-10-11T1000Z", queued=False, title="Lost #shorts #science")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the titled pile")
    publish_stash.FACTORY_KW.clear()
    publish_stash.FACTORY_KW.update({"now": NOW, "open_rows": []})
    s, d = get(client(root), f"/api/publish/{CH}/stash")
    assert s == 200, d
    by = {v["slug"]: v for v in d["videos"] + d["not_queued"]}
    t = by["t-card"]
    assert (t["title"], t["title_source"], t["title_clean"]) == (
        "Мозг стареет не везде #shorts", "card", "Мозг стареет не везде"), t
    assert (t["card"]["title"], t["card"]["title_clean"]) == (
        "Мозг стареет не везде #shorts", "Мозг стареет не везде"), t["card"]
    t = by["t-topic"]
    assert (t["title"], t["title_source"], t["title_clean"]) == (
        "Why octopuses dream", "topic", "Why octopuses dream"), t
    assert t["card"]["present"] and t["card"]["title"] is None and \
        t["card"]["title_clean"] is None, t["card"]
    t = by["t-none"]
    assert (t["title"], t["title_source"], t["title_clean"]) == (None, None, None), t
    assert not t["card"]["present"] and t["card"]["title"] is None, t["card"]
    t = by["t-lost"]
    assert not t["in_queue"] and t["title_source"] == "card" and t["title_clean"] == "Lost", t
    assert [publish_stash.title_clean(x) for x in (
        None, "", "#shorts", "Ranked #1", "Learn C# #shorts", "A  #shorts  #наука ")] == [
        None, None, None, "Ranked #1", "Learn C#", "A"]


def test_the_aging_rule_marks_stale_videos_by_news_else_by_acceptance():
    # CF-0741 (contract 0.53.0): the age from the topic's dated news, else from
    # the acceptance; stale strictly past 14 days - only marked
    root = world()
    video(root, "d-old-news", "2026-10-12T0400Z", news="2026-09-01T08:00:00+00:00")
    video(root, "e-evergreen", "2026-10-12T0500Z", news=None)
    video(root, "f-old-evergreen", "2026-09-20T0100Z", news=None, answered="2026-09-20")
    video(root, "g-day-fourteen", "2026-09-29T0100Z", news=None, answered="2026-09-29")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "more of the pile")
    c = client(root)
    s, d = get(c, f"/api/publish/{CH}/stash")
    assert s == 200, d
    by = {v["slug"]: v["age"] for v in d["videos"]}
    assert by["a-one"]["basis"] == "news" and by["a-one"]["days"] == 3, by["a-one"]
    assert by["a-one"]["stale"] is False, by["a-one"]
    assert (by["d-old-news"]["basis"], by["d-old-news"]["stale"]) == ("news", True), by
    assert by["d-old-news"]["days"] == by["d-old-news"]["news_days"] == 42, by["d-old-news"]
    assert by["d-old-news"]["accepted_days"] == 1, "the news counts, not the acceptance"
    assert by["e-evergreen"]["news_at"] is None, by["e-evergreen"]
    assert (by["e-evergreen"]["basis"], by["e-evergreen"]["days"],
            by["e-evergreen"]["stale"]) == ("accepted", 1, False), by["e-evergreen"]
    assert (by["f-old-evergreen"]["basis"], by["f-old-evergreen"]["days"],
            by["f-old-evergreen"]["stale"]) == ("accepted", 23, False), by["f-old-evergreen"]
    assert (by["g-day-fourteen"]["days"], by["g-day-fourteen"]["stale"]) == (14, False), \
        "day 14 is still fresh"
    assert d["count"] == 7 and d["stale"] == 1, (d["count"], d["stale"])
    st = d["staleness"]
    assert st["rule"] == "CF-0741" and st["threshold_days"] == 14, st
    assert st["stale_when"] == "days > 14" and st["only_marks"] is True, st
    assert st["decided"] and st["basis"] and st["note"], st
    # the plan: stale ones place like any other, their items say so
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan",
                {"order": ["d-old-news", "a-one", "f-old-evergreen"]})
    assert s == 200 and p["ok"] and p["confirm"], p
    it = {i["slug"]: i for i in p["items"]}
    assert (it["d-old-news"]["stale"], it["d-old-news"]["age_days"],
            it["d-old-news"]["age_basis"]) == (True, 42, "news"), it["d-old-news"]
    assert (it["a-one"]["stale"], it["a-one"]["age_days"],
            it["a-one"]["age_basis"]) == (False, 3, "news"), it["a-one"]
    assert (it["f-old-evergreen"]["stale"],
            it["f-old-evergreen"]["age_basis"]) == (False, "accepted"), it["f-old-evergreen"]
    assert not any(i["refusals"] for i in p["items"]), "age is never a refusal"
    lines = {ln.split(":")[0]: ln for ln in p["lines"]}
    assert lines["d-old-news"].endswith(" (устарел: 42 дн.)"), p["lines"]
    assert "устарел" not in lines["f-old-evergreen"], p["lines"]    # CF-0919
    assert "устарел" not in lines["a-one"], p["lines"]
    # a video not in the копилка: no age on its item
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["ghost"]})
    g = p["items"][0]
    assert (g["stale"], g["age_days"], g["age_basis"]) == (None, None, None), g
    # the confirm's items carry the same
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["d-old-news"]})
    s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 200 and r["placed"] == 1, r
    assert (r["items"][0]["stale"], r["items"][0]["age_days"]) == (True, 42), r["items"][0]
    assert r["lines"][0].endswith(" (устарел: 42 дн.)"), r["lines"]


# ----------------------------------------------------------------- placing
def test_the_plan_writes_nothing_says_why_in_russian_and_gives_no_token_on_a_refusal():
    root = world()
    c = client(root)
    before, h = files(root), head(root)
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one", "c-raw", "ghost"]})
    assert s == 200, p
    assert not p["ok"] and p["confirm"] is None and p["dry_run"] is True, p
    it = {i["slug"]: i for i in p["items"]}
    assert it["a-one"]["ok"] and it["a-one"]["day"] == "2026-10-14", it["a-one"]
    assert it["c-raw"]["refusals"][0]["code"] == "card_not_ready"
    assert it["c-raw"]["refusals"][0]["message"] == publish_stash.PLACE_RU["card_not_ready"][1]
    assert it["ghost"]["refusals"][0]["code"] == "not_in_queue"
    assert p["why"] and p["placed"] == 1, p
    assert files(root) == before and head(root) == h
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": []})
    assert s == 200 and [r["code"] for r in p["refusals"]] == ["empty_order"], p
    assert p["why"] == publish_stash.PLACE_RU["empty_order"][1]
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["x"] * 61})
    assert s == 422 and p["code"] == "invalid", p


def test_an_uncommitted_change_in_publish_is_dirty_and_no_token():
    root = world()
    c = client(root)
    (root / "publish" / "README.md").write_text("hand edit\n", encoding="utf-8")
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    assert [r["code"] for r in p["refusals"]] == ["dirty"], p["refusals"]
    assert "publish/README.md" in p["refusals"][0]["line"]
    assert p["why"] == publish_stash.PLACE_RU["dirty"][1]


def _committed(root, rev="HEAD"):
    return sorted(git(root, "show", "--name-only", "--format=", "--no-renames", rev)
                  .splitlines())


def test_the_confirm_places_in_order_and_commits_exactly_what_it_touched():
    root = world()
    c = client(root)
    h = head(root)
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["b-two", "a-one"]})
    assert s == 200 and p["ok"] and p["confirm"] and p["expires_in_s"] == 120, p
    assert [i["day"] for i in p["items"]] == ["2026-10-14", "2026-10-15"], p["items"]
    s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 200, r
    assert r["ok"] and r["written"] and r["placed"] == 2 and r["touched_from"] == "factory", r
    assert r["by"] == "user" and r["via"] == "center"
    it = {i["slug"]: i for i in r["items"]}
    assert it["b-two"]["placed"] and it["b-two"]["path"] == f"publish/{CH}/2026-10-14/b-two.md"
    assert (root / "publish" / CH / "2026-10-15" / "a-one.mp4").is_file()
    want = sorted([f"publish/{CH}/2026-10-14/b-two.md", f"publish/{CH}/2026-10-15/a-one.md",
                   "publish/README.md", "publish/acceptance-log.json"])
    assert r["committed"] == want, r["committed"]
    # the factory's touched: these and the moved mp4s (gitignored - never staged)
    extra = set(r["touched"]) - set(want)
    assert set(want) <= set(r["touched"]) and extra == {
        f"publish/{CH}/_queue/a-one.mp4", f"publish/{CH}/_queue/b-two.mp4",
        f"publish/{CH}/2026-10-14/b-two.mp4", f"publish/{CH}/2026-10-15/a-one.mp4"}, extra
    assert r["commit"] == head(root) and git(root, "rev-parse", "HEAD~1") == h
    assert _committed(root) == want
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith("Копилка: 2 в слоты reel (user, center)"), msg
    assert "Cc-Channel: reel" in msg and "Cc-Action: stash_place" in msg, msg
    assert git(root, "status", "--porcelain", "--", "publish") == "", "nothing left behind"
    assert "`reel/2026-10-15/a-one.mp4`" in (root / "publish" / "README.md").read_text(
        encoding="utf-8")
    s, again = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 409 and again["code"] == "confirm_unknown", again


def test_a_card_moved_out_of_the_queue_by_git_mv_is_committed_as_a_move():
    root = world()
    src = root / "pipeline" / CH / "2026-10-12T0100Z" / "work" / "publish-card" / "a-one.md"
    (root / "publish" / CH / "_queue" / "a-one.md").write_bytes(src.read_bytes())
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the card in the queue")
    c = client(root)
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
    assert s == 200 and p["ok"], p
    s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 200, r
    assert f"publish/{CH}/_queue/a-one.md" in r["committed"], r["committed"]
    assert f"publish/{CH}/2026-10-14/a-one.md" in r["committed"], r["committed"]
    assert git(root, "status", "--porcelain", "--", "publish") == ""
    assert git(root, "ls-files", f"publish/{CH}/_queue/a-one.md") == ""


def test_the_factory_s_touched_is_taken_first():
    root = world()
    c = client(root)
    ps = factory.publish_stash()
    real = ps.place_confirm
    seen = {}

    def with_touched(*a, **k):
        ans = real(*a, **k)
        # what the factory will say (CF-0738 follow-up): the files from the root
        ans["touched"] = [f"publish/{CH}/2026-10-14/a-one.md", "publish/README.md"]
        seen["ans"] = ans
        return ans
    ps.place_confirm = with_touched
    try:
        s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
        assert s == 200 and p["ok"], p
        s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    finally:
        ps.place_confirm = real
    assert s == 200, r
    assert r["touched_from"] == "factory", r
    assert r["touched"] == r["committed"] == ["publish/README.md",
                                              f"publish/{CH}/2026-10-14/a-one.md"], r
    assert _committed(root) == r["committed"]
    # what the factory did not name stays in the tree, uncommitted
    assert "publish/acceptance-log.json" in git(root, "status", "--porcelain", "--", "publish")


def test_without_the_factory_s_touched_git_status_before_and_after_decides():
    root = world()
    c = client(root)
    ps = factory.publish_stash()
    real = ps.place_confirm

    def without(*a, **k):
        ans = real(*a, **k)
        ans.pop("touched", None)            # a factory of before the CF-0738 follow-up
        return ans
    ps.place_confirm = without
    try:
        s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
        assert s == 200 and p["ok"], p
        s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    finally:
        ps.place_confirm = real
    assert s == 200, r
    want = sorted([f"publish/{CH}/2026-10-14/a-one.md", "publish/README.md",
                   "publish/acceptance-log.json"])
    assert r["touched_from"] == "git_status" and r["touched"] == r["committed"] == want, r
    assert _committed(root) == want
    assert git(root, "status", "--porcelain", "--", "publish") == ""


def test_an_open_batch_of_the_channel_is_batch_open():
    root = world()
    c = client(root)
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
    assert s == 200 and p["ok"], p
    before, h = files(root), head(root)
    publish_stash.FACTORY_KW["open_rows"] = [(root / "pipeline" / CH / "2026-10-13T1000Z",
                                              NOW, True)]
    s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "batch_open", r
    assert r["message"] == publish_stash.PLACE_RU["batch_open"][1]
    assert files(root) == before and head(root) == h
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    assert "batch_open" in [x["code"] for x in p["refusals"]]


def test_a_moved_state_is_check_changed():
    root = world()
    c = client(root)
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
    assert s == 200 and p["ok"], p
    (root / "publish" / CH / "_queue" / "b-two.mp4").write_bytes(b"MP4 longer")
    h = head(root)
    s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "check_changed", r
    assert head(root) == h and not (root / "publish" / CH / "2026-10-14").exists()


def test_a_commit_git_refuses_is_commit_refused_and_nothing_stays_staged():
    root = world()
    hooks = TMP / f"refusing-hooks-{root.name}"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))
    c = client(root)
    h = head(root)
    s, p = post(c, f"/api/publish/{CH}/stash/place/plan", {"order": ["a-one"]})
    assert s == 200 and p["ok"], p
    s, r = post(c, f"/api/publish/{CH}/stash/place", {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "commit_refused", r
    assert r["message"] == publish_stash.PLACE_RU["commit_refused"][1]
    assert any("a-one -> 2026-10-14" in x for x in r["details"]), r["details"]
    assert head(root) == h
    assert git(root, "diff", "--cached", "--name-only") == "", "nothing left staged"
    assert str(root) not in json.dumps(r)


# ----------------------------------------------------------------- the repair
def test_the_repair_puts_the_lost_video_into_the_queue_and_the_factory_commits():
    root = world(lost=True)
    c = client(root)
    h = head(root)
    s, p = post(c, f"/api/publish/{CH}/stash/repair/plan")
    assert s == 200 and p["ok"] and p["confirm"], p
    assert p["entries"] == [f"{CH}/2026-10-11T1000Z/lost-one"], p
    assert [i["code"] for i in p["items"]] == ["placed"], p["items"]
    assert not (root / "publish" / CH / "_queue" / "lost-one.mp4").exists()
    s, bad = post(c, f"/api/publish/{CH}/stash/repair/plan", {"entries": ["reel/x/y"]})
    assert s == 422 and bad["code"] == "not_found", bad
    s, r = post(c, f"/api/publish/{CH}/stash/repair", {"confirm": p["confirm"]})
    assert s == 200, r
    assert r["ok"] and r["written"] and r["commit"] == head(root) != h, r
    assert (root / "publish" / CH / "_queue" / "lost-one.mp4").is_file()
    assert _committed(root) == ["publish/acceptance-log.json"]
    s, p = post(c, f"/api/publish/{CH}/stash/repair/plan")
    assert s == 200 and not p["ok"] and p["confirm"] is None and p["why"], p


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

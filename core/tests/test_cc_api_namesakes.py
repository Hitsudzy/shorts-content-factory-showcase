#!/usr/bin/env python3
"""CC-0182 (CF-0920, factory 2.51): two live videos of one name in the копилка -
the second lies as `<slug>~<batch>.mp4 + .md` in `_queue/` or `_reserve/` - in the API.

The center names a video by `slug` and, when it has to tell two apart, `batch_id`
(the field every row already carries); the file's `~` name is never an address:

    GET  /api/publish/{c}/stash                    every row: slug plain, batch_id, bucket
    GET  /api/publish/{c}/notes/{slug}?batch_id    the note of that video
    POST /api/publish/{c}/stash/place/plan         {order ["<batch>/<slug>"]} | {auto}
    POST /api/publish/{c}/move/plan                {moves [{slug, batch_id?, day}],
                                                    unplace|withdraw ["<batch>/<slug>"]}
    GET  /api/publish/{c}/cards/{slug}?batch_id, POST .../cards/{slug}/build/plan
    POST /api/publish/{c}/card/place/plan          {batch_id, slug}
    POST /api/publish/{c}/upload/plan, /studio/record/plan  {slug, batch_id?}

Pinned: end to end on a temp tree with two namesakes in `_queue/` and one in `_reserve/`,
each read and write lands on the video asked for and the pair loses its suffix on the
way to a day; with two namesakes and no batch the answer is never the wrong video - the
factory's own refusal (`not_in_queue`, `ambiguous`) with a Russian message naming the
batches, else 409 `namesakes`; one video of the name goes on as before, with or without
the suffix.

In-process (TestClient) against stand-in factory roots in temp dirs; a fixed clock and
the open batches handed in. No live data, no network; the launcher of a card build is a
stand-in (no test starts a build or a model).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import H, _w, client, git                  # noqa: E402
from test_cc_api_publish_move import CH, CONFIRM, PLAN, head, journal, post  # noqa: E402
from test_cc_api_publish_stash import NOW, video as pile_video        # noqa: E402
from test_cc_api_publish_stash import world as pile_world             # noqa: E402
from test_cc_api_publish_stash import files                           # noqa: E402

from api import card_center, publish, publish_move, publish_net     # noqa: E402
from api.batches import BatchFault                                  # noqa: E402

SLUG = "x-name"
PLAIN, SUFFIXED, RESERVED, PLACED = ("2026-10-11T0100Z", "2026-10-12T0100Z", "2026-10-09T0100Z",
                                     "2026-10-08T0100Z")
TILDE = f"{SLUG}~{SUFFIXED}"
VID, VID2 = "resVID12345", "plcVID12345"
STASH = f"/api/publish/{CH}/stash"
NOTES = f"/api/publish/{CH}/notes/{SLUG}"
CARDS = f"/api/publish/{CH}/cards/{SLUG}"
CARD_PLACE = f"/api/publish/{CH}/card/place"
DAY1, DAY2, DAY3 = "2026-10-14", "2026-10-15", "2026-10-16"


def note_text(batch, publication="Слот не назначен."):
    return (f"# {SLUG}\n\nБатч `pipeline/{CH}/{batch}/`\n\n## Название\ntitle of {batch}\n\n"
            f"## Публикация\n{publication}\n\n## Настройки\n- Не для детей.\n\n"
            f"## Карточка\nREADY-STUB\n")


def _repoint(root, batch, stem, bucket):
    log = root / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    for r in doc["acceptances"]:
        if r["batch_id"] == batch:
            r["publish_path"] = f"publish/{CH}/{bucket}/{stem}.mp4"
    _w(log, doc)


def pair(root, batch, stem, bucket, notes=True, publication="Слот не назначен.", **kw):
    """The accepted row of `batch` with its pair at publish/<c>/<bucket>/<stem>."""
    pile_video(root, SLUG, batch, queued=False, **kw)
    d = root / "publish" / CH / bucket
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.mp4").write_bytes(batch.encode())
    if notes:
        _w(d / f"{stem}.md", note_text(batch, publication))
    _repoint(root, batch, stem, bucket)


def journal_row(batch, day=None, vid=VID, stem=SLUG, bucket=None):
    row = {"channel": CH, "entry_id": f"{CH}/{batch}/{SLUG}", "batch_id": batch,
           "topic_id": f"t-{SLUG}", "slug": SLUG, "video_id": vid,
           "url": f"https://youtube.com/shorts/{vid}",
           "publish_at": f"{day}T01:00:00+03:00" if day else None,
           "publish_tz": "Europe/Moscow", "publish_day": day,
           "note": f"publish/{CH}/{bucket or day}/{stem}.md", "source": "studio",
           "recorded_at": "2026-10-09T17:00:00Z", "user_edited": False}
    if day is None:
        row["withdrawn"] = {"at": "2026-10-12T11:40:00Z", "by": "driver", "via": "studio",
                            "task": "CF-0918", "from_at": "2026-10-20T01:00:00+03:00",
                            "from_day": "2026-10-20",
                            "from_note": f"publish/{CH}/2026-10-20/{SLUG}.md",
                            "studio": "Ограниченный доступ"}
    return row


def world(notes=True, queue=True, reserve=True, **plain_kw):
    """13.10 12:00, slots 14-16.10 inside the horizon: `x-name` of PLAIN and `x-name~SUFFIXED`
    in `_queue/`, `x-name` of RESERVED in `_reserve/` (withdrawn from Studio)."""
    root = pile_world()
    for name in ("a-one", "b-two", "c-raw"):
        (root / "publish" / CH / "_queue" / f"{name}.mp4").unlink()
    _w(root / "publish" / "acceptance-log.json", {"note": "test", "task": "CF-0328",
                                                  "acceptances": []})
    _w(root / "publish" / "README.md", "| ролик | статус |\n|---|---|\n")
    rows = []
    if reserve:
        pair(root, RESERVED, SLUG, "_reserve", news=None, answered="2026-10-09")
        rows.append(journal_row(RESERVED, bucket="_reserve"))
    if queue:
        pair(root, PLAIN, SLUG, "_queue", notes=notes, news=None, answered="2026-10-11",
             **plain_kw)
    pair(root, SUFFIXED, TILDE, "_queue", notes=notes, news=None, answered="2026-10-12")
    _w(root / "publish" / "uploads.json", {"uploads": rows})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the namesakes")
    publish.FACTORY_KW.clear()
    publish.FACTORY_KW.update({"now": NOW})
    publish_move.FACTORY_KW.clear()
    publish_move.FACTORY_KW.update({"now": NOW, "open_rows": []})
    card_center.FACTORY_KW.clear()
    return root


def get(c, path, **params):
    r = c.get(path, params=params, headers=H)
    return r.status_code, r.json()


def clean(root):
    return git(root, "status", "--porcelain").strip() == ""


def rows(c):
    return {v["batch_id"]: v for v in get(c, STASH)[1]["videos"]}


def names_both(message, *batches):
    assert any("а" <= ch <= "я" for ch in message.lower()), message
    for b in batches:
        assert b in message, (b, message)


# ----------------------------------------------------------------- the stash read
def test_the_pile_tells_the_three_apart_by_batch_and_bucket_and_the_name_stays_plain():
    c = client(world())
    s, res = get(c, STASH)
    assert s == 200 and res["count"] == 3, res
    got = {v["batch_id"]: v for v in res["videos"]}
    assert sorted(got) == sorted([PLAIN, SUFFIXED, RESERVED]), got
    assert {v["slug"] for v in res["videos"]} == {SLUG}
    assert got[PLAIN]["bucket"] == got[SUFFIXED]["bucket"] == "_queue"
    assert got[RESERVED]["bucket"] == "_reserve" and got[RESERVED]["reserve"] is True
    assert got[RESERVED]["video_id"] == VID
    assert got[SUFFIXED]["mp4"] == f"publish/{CH}/_queue/{TILDE}.mp4", got[SUFFIXED]
    assert got[SUFFIXED]["card"]["path"] == f"publish/{CH}/_queue/{TILDE}.md", got[SUFFIXED]
    assert got[PLAIN]["mp4"] == f"publish/{CH}/_queue/{SLUG}.mp4", got[PLAIN]
    assert got[SUFFIXED]["entry_id"] == f"{CH}/{SUFFIXED}/{SLUG}"
    assert got[SUFFIXED]["videos_url"].endswith(f"/batches/{CH}/{SUFFIXED}/videos")


# ----------------------------------------------------------------- the note read
def test_a_note_is_read_by_its_batch():
    c = client(world())
    for batch, path, day in ((PLAIN, f"{SLUG}.md", "_queue"), (SUFFIXED, f"{TILDE}.md", "_queue"),
                             (RESERVED, f"{SLUG}.md", "_reserve")):
        s, n = get(c, NOTES, batch_id=batch)
        assert s == 200, n
        assert n["path"] == f"publish/{CH}/{day}/{path}" and n["day"] == day, n
        assert n["slug"] == SLUG and n["title"] == f"title of {batch}", n
        assert n["batch"]["batch_id"] == batch, n["batch"]
    # with the folder it lies in; the day says where to look, the batch which video
    s, n = get(c, NOTES, batch_id=SUFFIXED, day="_queue")
    assert s == 200 and n["path"].endswith(f"/{TILDE}.md"), n


def test_a_note_with_no_batch_is_refused_naming_the_batches_never_the_last_one():
    c = client(world())
    for params in ({}, {"day": "_queue"}):
        s, r = get(c, NOTES, **params)
        assert s == 409 and r["code"] == "namesakes", (params, r)
        names_both(r["message"], PLAIN, SUFFIXED)
    # one video in that folder: the day tells them apart, as before
    s, n = get(c, NOTES, day="_reserve")
    assert s == 200 and n["title"] == f"title of {RESERVED}", n


def test_a_note_of_a_batch_that_is_not_there_is_unknown_note():
    c = client(world())
    for params in ({"batch_id": "2026-01-01T0000Z"}, {"batch_id": "a~b"}, {"batch_id": "../up"},
                   {"batch_id": SUFFIXED, "day": "_reserve"}):
        s, r = get(c, NOTES, **params)
        assert s == 404 and r["code"] == "unknown_note", (params, r)
    assert get(c, f"/api/publish/{CH}/notes/{TILDE}")[0] == 404, "the ~ name is not an address"


def test_the_only_video_of_the_name_under_its_suffix_reads_with_no_batch():
    """Its plain namesake went onto a day: the note is the one file left, `~` and all."""
    c = client(world(queue=False, reserve=False))
    s, n = get(c, NOTES)
    assert s == 200 and n["path"] == f"publish/{CH}/_queue/{TILDE}.md", n
    s, n = get(c, NOTES, day="_queue")
    assert s == 200 and n["slug"] == SLUG, n


# ----------------------------------------------------------------- placing by name
def test_the_placement_with_no_batch_says_which_and_gives_no_token():
    root = world()
    before = files(root)
    s, p = post(client(root), f"{STASH}/place/plan", {"order": [SLUG]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    it = p["items"][0]
    assert it["refusals"][0]["code"] == "not_in_queue", it
    names_both(it["refusals"][0]["message"], PLAIN, SUFFIXED, RESERVED)
    names_both(p["why"], PLAIN, SUFFIXED, RESERVED)
    assert files(root) == before


def test_the_batch_places_that_video_and_the_pair_loses_its_suffix():
    root = world()
    c = client(root)
    s, p = post(c, f"{STASH}/place/plan", {"order": [f"{SUFFIXED}/{SLUG}"]})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert p["items"][0]["batch_id"] == SUFFIXED and p["items"][0]["slug"] == SLUG, p["items"]
    s, r = post(c, f"{STASH}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["placed"] == 1 and r["commit"] == head(root), r
    pub = root / "publish" / CH
    assert (pub / DAY1 / f"{SLUG}.mp4").read_bytes() == SUFFIXED.encode()
    assert f"pipeline/{CH}/{SUFFIXED}" in (pub / DAY1 / f"{SLUG}.md").read_text(encoding="utf-8")
    assert not (pub / "_queue" / f"{TILDE}.mp4").exists()
    assert not (pub / "_queue" / f"{TILDE}.md").exists()
    assert (pub / "_queue" / f"{SLUG}.mp4").read_bytes() == PLAIN.encode(), "the other one stays"
    assert clean(root), git(root, "status", "--porcelain")
    got = rows(c)
    assert sorted(got) == sorted([PLAIN, RESERVED]), got


def test_the_reserve_video_comes_back_by_its_batch_in_a_placement():
    root = world()
    c = client(root)
    s, p = post(c, f"{STASH}/place/plan", {"order": [f"{RESERVED}/{SLUG}"]})
    assert s == 200 and p["ok"], p
    assert p["items"][0]["reserve"] is True and p["items"][0]["video_id"] == VID, p["items"]
    s, r = post(c, f"{STASH}/place", {"confirm": p["confirm"]})
    assert s == 200 and "publish/uploads.json" in r["committed"], r
    assert journal(root)[SLUG]["publish_day"] == DAY1, journal(root)
    assert (root / "publish" / CH / "_queue" / f"{TILDE}.mp4").is_file()
    assert clean(root), git(root, "status", "--porcelain")


# ----------------------------------------------------------------- the auto plan
def test_the_auto_plan_names_each_namesake_by_its_batch_and_confirms():
    root = world()
    c = client(root)
    s, p = post(c, f"{STASH}/place/plan", {"auto": True})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert sorted(p["order"]) == sorted(f"{b}/{SLUG}" for b in (PLAIN, SUFFIXED, RESERVED)), p
    assert sorted(i["batch_id"] for i in p["items"]) == sorted([PLAIN, SUFFIXED, RESERVED]), p
    assert sorted(i["day"] for i in p["items"]) == [DAY1, DAY2, DAY3], p["items"]
    s, r = post(c, f"{STASH}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["placed"] == 3 and r["commit"] == head(root), r
    pub = root / "publish" / CH
    for it in r["items"]:
        assert (pub / it["day"] / f"{SLUG}.mp4").read_bytes() == it["batch_id"].encode(), it
    assert not list((pub / "_queue").glob(f"{SLUG}*")), "the pile is empty"
    assert clean(root), git(root, "status", "--porcelain")


def test_the_auto_plan_says_which_namesake_waits_and_why():
    root = world(reserve=False)
    # the three slots go to older videos of other names: both of ours wait past the horizon
    for i, name in enumerate(("a-old", "b-old", "c-old")):
        pile_video(root, name, f"2026-10-0{i + 1}T0100Z", news=None, answered=f"2026-10-0{i + 1}")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "older videos")
    s, p = post(client(root), f"{STASH}/place/plan", {"auto": True})
    assert s == 200 and p["ok"], p
    waits = [(x["slug"], x["batch_id"], x["reason"]) for x in p["skipped"]]
    assert sorted(waits) == sorted([(SLUG, PLAIN, "beyond_horizon"),
                                    (SLUG, SUFFIXED, "beyond_horizon")]), waits


def test_the_auto_plan_tells_namesakes_the_factory_leaves_nameless():
    """`choose` gives a skipped row no batch: the card's reason is of one of the two."""
    root = world(reserve=False, notes=False, card=False)
    s, p = post(client(root), f"{STASH}/place/plan", {"auto": True})
    assert s == 200, p
    assert [(x["slug"], x["batch_id"], x["reason"]) for x in p["skipped"]] == [
        (SLUG, PLAIN, "no_card")], p["skipped"]
    assert [i["batch_id"] for i in p["items"]] == [SUFFIXED], p["items"]


# ----------------------------------------------------------------- moving to a day
def placed_world():
    """A pile video of SUFFIXED placed on 14.10 through the center, the reserve one beside."""
    root = world()
    c = client(root)
    _s, p = post(c, f"{STASH}/place/plan", {"order": [f"{SUFFIXED}/{SLUG}"]})
    s, r = post(c, f"{STASH}/place", {"confirm": p["confirm"]})
    assert s == 200, r
    return root, c


def test_a_bare_move_of_a_name_on_a_day_and_in_the_reserve_is_ambiguous_naming_the_batches():
    root, c = placed_world()
    before = files(root)
    s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "day": DAY2}]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    ref = p["items"][0]["refusals"][0]
    assert ref["code"] == "ambiguous", ref
    names_both(ref["message"], SUFFIXED, RESERVED)
    names_both(p["why"], SUFFIXED, RESERVED)
    assert files(root) == before


def test_a_move_by_batch_moves_that_video():
    root, c = placed_world()
    pub = root / "publish" / CH
    s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "batch_id": SUFFIXED, "day": DAY2}]})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert p["moves"] == [{"slug": SLUG, "batch_id": SUFFIXED, "day": DAY2}], p["moves"]
    assert p["items"][0]["slug"] == SLUG and p["items"][0]["batch_id"] == SUFFIXED, p["items"]
    assert p["items"][0]["from_day"] == DAY1 and p["items"][0]["day"] == DAY2, p["items"]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["moved"] == 1 and r["commit"] == head(root), r
    assert (pub / DAY2 / f"{SLUG}.mp4").read_bytes() == SUFFIXED.encode()
    assert (pub / "_reserve" / f"{SLUG}.mp4").read_bytes() == RESERVED.encode()
    assert clean(root), git(root, "status", "--porcelain")


def test_a_move_of_a_namesake_with_no_slot_is_in_queue_and_a_bad_batch_is_invalid():
    root = world()
    c = client(root)
    s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "batch_id": PLAIN, "day": DAY1}]})
    assert s == 200 and not p["ok"], p
    assert p["items"][0]["refusals"][0]["code"] == "in_queue", p["items"]
    for bad in ("a~b", "../up", ""):
        s, r = post(c, PLAN, {"moves": [{"slug": SLUG, "batch_id": bad, "day": DAY1}]})
        assert s == 422 and r["code"] == "invalid", (bad, r)
    s, r = post(c, PLAN, {"moves": [{"slug": f"{PLAIN}/{SLUG}", "batch_id": PLAIN, "day": DAY1}]})
    assert s == 422 and r["code"] == "invalid", r


def test_the_token_is_bound_to_the_batch():
    root, c = placed_world()
    _s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "batch_id": RESERVED, "day": DAY2}]})
    assert p["ok"] and p["items"][0]["reserve"] is True, p
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["moves"] == [{"slug": SLUG, "batch_id": RESERVED, "day": DAY2}], r
    pub = root / "publish" / CH
    assert (pub / DAY2 / f"{SLUG}.mp4").read_bytes() == RESERVED.encode()
    assert (pub / DAY1 / f"{SLUG}.mp4").read_bytes() == SUFFIXED.encode()


def test_a_name_on_two_days_is_ambiguous_bare_and_taken_back_by_its_batch():
    root, c = placed_world()
    _s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "batch_id": RESERVED, "day": DAY2}]})
    post(c, CONFIRM, {"confirm": p["confirm"]})
    s, p = post(c, PLAN, {"unplace": [SLUG]})
    assert s == 200 and not p["ok"], p
    assert p["items"][0]["refusals"][0]["code"] == "ambiguous", p["items"]
    names_both(p["why"], SUFFIXED, RESERVED)
    s, p = post(c, PLAN, {"unplace": [f"{SUFFIXED}/{SLUG}"]})
    assert s == 200 and p["ok"] and p["items"][0]["from_day"] == DAY1, p
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["unplaced"] == 1, r
    assert (root / "publish" / CH / "_queue" / f"{TILDE}.mp4").read_bytes() == SUFFIXED.encode()
    assert (root / "publish" / CH / DAY2 / f"{SLUG}.mp4").read_bytes() == RESERVED.encode()
    assert clean(root), git(root, "status", "--porcelain")


# ----------------------------------------------------------------- withdraw and the return
def studio_world():
    """The reserve's `x-name` of RESERVED and a placed `x-name` of PLACED in Studio on 16.10."""
    root = world(queue=False)
    pair(root, PLACED, SLUG, DAY3, news=None, answered="2026-10-08",
         publication=f"**{DAY3} 01:00 МСК** — ближайший свободный слот канала `{CH}`.")
    log = root / "publish" / "uploads.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    doc["uploads"].append(journal_row(PLACED, DAY3, VID2))
    _w(log, doc)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one in Studio")
    return root, client(root)


def by_video(root):
    doc = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    return {r["video_id"]: r for r in doc["uploads"]}


def test_a_bare_withdraw_means_the_placed_one_and_it_lies_under_its_batch():
    root, c = studio_world()
    s, p = post(c, PLAN, {"withdraw": [SLUG]})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert p["items"][0]["batch_id"] == PLACED and p["items"][0]["from_day"] == DAY3, p["items"]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["withdrawn"] == 1 and r["commit"] == head(root), r
    res = root / "publish" / CH / "_reserve"
    assert (res / f"{SLUG}~{PLACED}.mp4").read_bytes() == PLACED.encode()
    assert (res / f"{SLUG}.mp4").read_bytes() == RESERVED.encode(), "the older one stays"
    assert by_video(root)[VID2]["withdrawn"]["from_day"] == DAY3
    assert by_video(root)[VID2]["note"] == f"publish/{CH}/_reserve/{SLUG}~{PLACED}.md"
    assert clean(root), git(root, "status", "--porcelain")
    got = rows(c)
    assert got[PLACED]["bucket"] == got[RESERVED]["bucket"] == "_reserve", got
    assert got[PLACED]["video_id"] == VID2 and got[RESERVED]["video_id"] == VID, got


def test_a_withdraw_by_batch_names_the_placed_one_and_another_batch_is_refused():
    root, c = studio_world()
    s, p = post(c, PLAN, {"withdraw": [f"{PLACED}/{SLUG}"]})
    assert s == 200 and p["ok"] and p["withdraw"] == [f"{PLACED}/{SLUG}"], p
    s, p = post(c, PLAN, {"withdraw": [f"{RESERVED}/{SLUG}"]})
    assert s == 200 and not p["ok"], p
    assert p["items"][0]["refusals"][0]["code"] == "in_reserve", p["items"]


def test_two_in_the_reserve_come_back_by_batch_and_with_no_batch_are_ambiguous():
    root, c = studio_world()
    _s, p = post(c, PLAN, {"withdraw": [SLUG]})
    post(c, CONFIRM, {"confirm": p["confirm"]})
    s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "day": DAY2}]})
    assert s == 200 and not p["ok"], p
    ref = p["items"][0]["refusals"][0]
    assert ref["code"] == "ambiguous", ref
    names_both(ref["message"], PLACED, RESERVED)
    s, p = post(c, PLAN, {"moves": [{"slug": SLUG, "batch_id": PLACED, "day": DAY2}]})
    assert s == 200 and p["ok"] and p["items"][0]["reserve"] is True, p
    assert p["items"][0]["video_id"] == VID2, p["items"]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["moved"] == 1, r
    pub = root / "publish" / CH
    assert (pub / DAY2 / f"{SLUG}.mp4").read_bytes() == PLACED.encode()
    assert not (pub / "_reserve" / f"{SLUG}~{PLACED}.mp4").exists()
    assert (pub / "_reserve" / f"{SLUG}.mp4").read_bytes() == RESERVED.encode()
    row = by_video(root)[VID2]
    assert row["publish_day"] == DAY2 and not row.get("withdrawn"), row
    assert clean(root), git(root, "status", "--porcelain")


def test_an_unplace_by_batch_takes_the_day_s_video_back_under_its_suffix():
    root = world()
    c = client(root)
    _s, p = post(c, f"{STASH}/place/plan", {"order": [f"{PLAIN}/{SLUG}"]})
    post(c, f"{STASH}/place", {"confirm": p["confirm"]})
    s, p = post(c, f"{STASH}/place/plan", {"order": [f"{SUFFIXED}/{SLUG}"]})
    s, r = post(c, f"{STASH}/place", {"confirm": p["confirm"]})
    assert s == 200 and r["items"][0]["day"] == DAY2, r
    # back into `_queue/`: the file named by the name, whichever came first
    s, p = post(c, PLAN, {"unplace": [f"{PLAIN}/{SLUG}"]})
    assert s == 200 and p["ok"] and p["items"][0]["from_day"] == DAY1, p
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 200 and r["unplaced"] == 1, r
    assert (root / "publish" / CH / "_queue" / f"{SLUG}.mp4").read_bytes() == PLAIN.encode()
    assert (root / "publish" / CH / DAY2 / f"{SLUG}.mp4").read_bytes() == SUFFIXED.encode()
    assert clean(root), git(root, "status", "--porcelain")


# ----------------------------------------------------------------- the card
def test_a_card_read_and_its_build_with_no_batch_are_refused_when_two_wait():
    c = client(world(notes=False))
    s, r = get(c, CARDS)
    assert s == 409 and r["code"] == "namesakes", r
    names_both(r["message"], PLAIN, SUFFIXED, RESERVED)
    s, r = post(c, f"{CARDS}/build/plan", {})
    assert s == 409 and r["code"] == "namesakes", r
    s, r = post(c, f"{CARDS}/ruling/plan", {"words": "берём"})
    assert s == 409 and r["code"] == "namesakes", r


def test_a_card_is_read_and_built_by_its_batch():
    root = world(notes=False)
    c = client(root)
    s, got = get(c, CARDS, batch_id=SUFFIXED)
    assert s == 200 and got["batch_id"] == SUFFIXED and got["state"] == "ready", got
    calls = []
    keep = card_center.launcher
    card_center.launcher = lambda *a: calls.append(a) or {"ok": True, "launched": True,
                                                          "run_id": None, "lines": []}
    try:
        s, p = post(c, f"{CARDS}/build/plan", {"batch_id": SUFFIXED})
        assert s == 200 and p["ok"] and p["batch_id"] == SUFFIXED, p
        s, r = post(c, f"{CARDS}/build", {"confirm": p["confirm"]})
        assert s == 200 and r["batch_id"] == SUFFIXED, r
    finally:
        card_center.launcher = keep
    assert calls and calls[0][1] == SLUG and calls[0][4] == SUFFIXED, calls


def test_one_accepted_video_of_a_name_builds_with_no_batch_as_before():
    c = client(world(notes=False, queue=False, reserve=False))
    s, got = get(c, CARDS)
    assert s == 200 and got["batch_id"] == SUFFIXED, got


def test_the_card_goes_beside_the_suffixed_file_and_the_slot_gives_the_plain_name():
    root = world(notes=False)
    c = client(root)
    s, p = post(c, f"{CARD_PLACE}/plan", {"batch_id": SUFFIXED, "slug": SLUG})
    assert s == 200 and p["ok"] and p["confirm"], p
    assert p["target"] == f"publish/{CH}/_queue/{TILDE}.md", p
    assert p["bucket"] == "_queue" and p["slot"]["day"] == DAY1, p
    s, r = post(c, CARD_PLACE, {"confirm": p["confirm"]})
    assert s == 200 and r["path"] == f"publish/{CH}/{DAY1}/{SLUG}.md", r
    pub = root / "publish" / CH
    assert (pub / DAY1 / f"{SLUG}.mp4").read_bytes() == SUFFIXED.encode()
    assert not (pub / "_queue" / f"{TILDE}.mp4").exists()
    assert (pub / "_queue" / f"{SLUG}.mp4").read_bytes() == PLAIN.encode()
    assert clean(root), git(root, "status", "--porcelain")
    log = json.loads((root / "publish" / "acceptance-log.json").read_text(encoding="utf-8"))
    paths = {r["batch_id"]: r["publish_path"] for r in log["acceptances"]}
    assert paths[SUFFIXED] == f"publish/{CH}/{DAY1}/{SLUG}.mp4", paths
    assert paths[PLAIN] == f"publish/{CH}/_queue/{SLUG}.mp4", paths


def test_the_card_of_the_plain_namesake_goes_beside_the_plain_file():
    root = world(notes=False)
    c = client(root)
    s, p = post(c, f"{CARD_PLACE}/plan", {"batch_id": PLAIN, "slug": SLUG})
    assert s == 200 and p["ok"] and p["target"] == f"publish/{CH}/_queue/{SLUG}.md", p
    s, r = post(c, CARD_PLACE, {"confirm": p["confirm"]})
    assert s == 200, r
    assert (root / "publish" / CH / DAY1 / f"{SLUG}.mp4").read_bytes() == PLAIN.encode()
    assert (root / "publish" / CH / "_queue" / f"{TILDE}.mp4").is_file()


# ----------------------------------------------------------------- the upload and the record
def test_the_upload_and_the_studio_record_plans_name_the_video_by_batch():
    c = client(world())
    for path, extra in ((f"/api/publish/{CH}/upload/plan", {}),
                        (f"/api/publish/{CH}/studio/record/plan",
                         {"video_id": "abcdefghijk", "read": {}})):
        s, r = post(c, path, {"slug": SLUG, "day": "_queue", **extra})
        assert s == 409 and r["code"] == "namesakes", (path, r)
        names_both(r["message"], PLAIN, SUFFIXED)
        s, p = post(c, path, {"slug": SLUG, "batch_id": SUFFIXED, **extra})
        assert s == 200 and p["note"] == f"publish/{CH}/_queue/{TILDE}.md", (path, p)
        assert p["slug"] == SLUG and p["day"] == "_queue", (path, p)


def test_the_upload_s_batch_is_the_factory_s_entry_and_a_different_entry_is_invalid():
    """`upload.run` itself is pinned by test_cc_api_publish_net: here, what it is handed."""
    c = client(world())
    seen = []
    keep = publish_net._upload_check

    def spy(_root, _cid, bound):
        seen.append(bound)
        raise BatchFault(409, "refused", "заглушка", [])
    publish_net._upload_check = spy
    try:
        post(c, f"/api/publish/{CH}/upload/plan", {"slug": SLUG, "batch_id": SUFFIXED})
    finally:
        publish_net._upload_check = keep
    assert seen and seen[0]["entry"] == f"{CH}/{SUFFIXED}/{SLUG}", seen
    assert seen[0]["batch_id"] == SUFFIXED, seen
    s, r = post(c, f"/api/publish/{CH}/upload/plan",
                {"slug": SLUG, "batch_id": SUFFIXED, "entry": f"{CH}/{PLAIN}/{SLUG}"})
    assert s == 422 and r["code"] == "invalid", r


# ----------------------------------------------------------------- the contract
def test_the_contract_declares_the_batch_everywhere_and_the_refusal():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    for name in ("StashVideo", "StashPlaceItem", "StashSkipped", "MoveItem", "MoveEdit",
                 "UploadPlanIn", "StudioRecordPlanIn"):
        assert "batch_id" in sch[name]["properties"], name
        assert "batch_id" not in sch[name].get("required", []), name
    route = spec["paths"]["/api/publish/{channel}/notes/{slug}"]["get"]
    assert "batch_id" in [x["name"] for x in route["parameters"]]
    assert not next(x for x in route["parameters"] if x["name"] == "batch_id").get("required")
    assert "409" in spec["paths"]["/api/publish/{channel}/cards/{slug}"]["get"]["responses"]
    for name in ("PublishProblem", "CardCenterProblem"):
        assert "namesakes" in sch[name]["properties"]["code"]["enum"], name


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
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

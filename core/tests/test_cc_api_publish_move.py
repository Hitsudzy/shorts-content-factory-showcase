#!/usr/bin/env python3
"""CC-0165: moving a placed video to another day, or taking it back into the
копилка, from the center (`api/publish_move.py` over
`agents/publisher/publish_move.py`, CF-0856):

    POST /api/publish/{c}/move/plan     {moves [{slug, day}], unplace [slug]}
    POST /api/publish/{c}/move/confirm  {confirm, base_sha256?}

Pinned: the plan writes nothing, judges the shift of 23.10 as a whole
(unplace the 24th, 25->24, 26->25) and gives a token with the factory's
base_sha256; the confirm moves by user via center and the factory makes one
commit, the journal rows of the videos in Studio rewritten with a STUDIO
warning; a shift named in any order is the same plan; an open batch is
`batch_open`, a stale base_sha256 or a state changed since the plan
`check_changed`, unplacing a video in Studio `in_studio` (no token); a
request without the session / origin is refused; every code has a Russian
text.

In-process (TestClient) against a stand-in factory root in a temp dir
(`tests/test_cc_api_batches.py` `factory_tree`: `reel`, one slot a day at
01:00 МСК, lead 2 h); a fixed clock and the open batches handed in
(`publish_move.FACTORY_KW`). No live data, no network.
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

from test_cc_api_batches import H, _w, client, factory_tree, git  # noqa: E402

import api                                                          # noqa: E402
from api import factory, publish_move                               # noqa: E402

CH = "reel"
BATCH = "2026-10-23T1504Z"
NOW = "2026-10-23T21:30:00+03:00"
IDS = {"iphone-duo": "8-MBFrW93lk", "openai": "uzrmS1z-ji8"}
PLAN, CONFIRM = f"/api/publish/{CH}/move/plan", f"/api/publish/{CH}/move/confirm"
SHIFT = {"moves": [{"slug": "iphone-duo", "day": "2026-10-24"},
                   {"slug": "openai", "day": "2026-10-25"}], "unplace": ["gemini"]}


def note(slug, day):
    return (f"# {slug}\n\nБатч `pipeline/{CH}/{BATCH}/`\n\n## Название\n{slug} title\n\n"
            f"## Публикация\n**{day} 01:00 МСК** — ближайший свободный слот канала `{CH}`.\n\n"
            f"## Настройки\n- Не для детей.\n")


def jrow(slug, day):
    vid = IDS[slug]
    return {"channel": CH, "entry_id": f"{CH}/{BATCH}/{slug}", "batch_id": BATCH,
            "topic_id": f"t-{slug}", "slug": slug, "video_id": vid,
            "url": f"https://youtube.com/shorts/{vid}", "publish_at": f"{day}T01:00:00+03:00",
            "publish_tz": "Europe/Moscow", "publish_day": day,
            "note": f"publish/{CH}/{day}/{slug}.md", "source": "studio",
            "recorded_at": "2026-10-23T17:51:55Z", "user_edited": False}


def world():
    """23.10: gemini on 24 (not in Studio), iphone-duo on 25 and openai on 26
    (both in Studio - live journal rows)."""
    root = factory_tree()
    placed = {"gemini": "2026-10-24", "iphone-duo": "2026-10-25", "openai": "2026-10-26"}
    studio = {"iphone-duo": "2026-10-25", "openai": "2026-10-26"}
    _w(root / ".gitignore", "/schedule/\n*.mp4\n*.lock\n")
    pub = root / "publish"
    rows, readme = [], ["| ролик | статус |", "|---|---|"]
    for slug, day in placed.items():
        _w(pub / CH / day / f"{slug}.md", note(slug, day))
        (pub / CH / day / f"{slug}.mp4").write_bytes(slug.encode())
        rows.append({"entry_id": f"{CH}/{BATCH}/{slug}", "channel": CH, "batch_id": BATCH,
                     "slug": slug, "topic_id": f"t-{slug}", "verdict": "accepted",
                     "answered_at": "2026-10-23T16:00:00Z",
                     "publish_path": f"publish/{CH}/{day}/{slug}.mp4", "history": []})
        readme.append(f"| `{CH}/{day}/{slug}.mp4` | принят |")
    _w(pub / "uploads.json", {"note": "t", "task": "CF-0586", "format": 2,
                              "uploads": [jrow(s, d) for s, d in studio.items()]})
    _w(pub / "acceptance-log.json", {"note": "t", "task": "CF-0328", "acceptances": rows})
    _w(pub / "publication-holds.json", {"holds": []})
    _w(pub / "README.md", "\n".join(readme) + "\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "23.10")
    publish_move.FACTORY_KW.clear()
    publish_move.FACTORY_KW.update({"now": NOW, "open_rows": []})
    return root


def post(c, path, body=None):
    r = c.post(path, headers=H, json=body)
    return r.status_code, r.json()


def head(root):
    return git(root, "rev-parse", "HEAD")


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts
            and not p.name.endswith(".lock")}


def journal(root):
    return {r["slug"]: r for r in json.loads((root / "publish" / "uploads.json").read_text(
        encoding="utf-8"))["uploads"]}


# ----------------------------------------------------------------- the contract
def test_the_contract_and_the_russian_texts():
    spec = client(world()).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for tail in ("/plan", "/confirm"):
        assert sorted(spec["paths"][f"/api/publish/{{channel}}/move{tail}"]) == ["post"], tail
    pm = factory.publish_move()
    from api.app import MOVE_ITEM_CODES, MOVE_TOP_CODES
    assert set(pm.TOP_REFUSALS) | set(pm.ITEM_REFUSALS) <= set(publish_move.MOVE_RU)
    assert set(MOVE_TOP_CODES) | set(MOVE_ITEM_CODES) == set(publish_move.MOVE_RU)
    for code, (_status, text) in publish_move.MOVE_RU.items():
        assert any("а" <= ch <= "я" for ch in text.lower()), code
    on_disk = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert "/api/publish/{channel}/move/plan" in on_disk["paths"]


def test_the_writes_need_the_session_and_the_origin():
    root = world()
    c = client(root)
    for path, body in ((PLAN, SHIFT), (CONFIRM, {"confirm": "x"})):
        r = c.post(path, json=body)
        assert r.status_code == 403, (path, r.text)
        r = c.post(path, json=body, headers={k: v for k, v in H.items() if k != "Origin"})
        assert r.status_code == 403, (path, r.text)
        r = c.post(path, json=body, headers=dict(H, Origin="http://evil.example"))
        assert r.status_code == 403, (path, r.text)


# ----------------------------------------------------------------- the plan
def test_the_plan_of_the_shift_writes_nothing_and_gives_a_token():
    root = world()
    c = client(root)
    before, h = files(root), head(root)
    s, p = post(c, PLAN, SHIFT)
    assert s == 200, p
    assert p["ok"] and p["dry_run"] and p["confirm"] and p["expires_in_s"] == 120, p
    assert p["action"] == "publish_move" and p["task"] == "CF-0856"
    assert p["by"] == "user" and p["via"] == "center"
    assert p["base_sha256"] and p["base_sha256"] == p["sha256"], p
    assert p["moved"] == 2 and p["unplaced"] == 1 and p["why"] is None
    it = {i["slug"]: i for i in p["items"]}
    assert it["gemini"]["op"] == "unplace" and it["gemini"]["from_day"] == "2026-10-24"
    assert it["iphone-duo"]["day"] == "2026-10-24" and it["iphone-duo"]["in_studio"]
    assert it["openai"]["from_day"] == "2026-10-26" and it["openai"]["day"] == "2026-10-25"
    assert any(w.startswith("STUDIO iphone-duo") for w in it["iphone-duo"]["warnings"]), it
    assert p["ledger"] and p["refusals"] == []
    assert files(root) == before and head(root) == h


def test_the_shift_named_in_any_order_is_the_same_plan():
    root = world()
    c = client(root)
    back = {"moves": list(reversed(SHIFT["moves"])), "unplace": SHIFT["unplace"]}
    s, a = post(c, PLAN, SHIFT)
    s2, b = post(c, PLAN, back)
    assert s == s2 == 200 and a["ok"] and b["ok"], (a, b)
    days = lambda p: {i["slug"]: (i["day"], i["slot"]) for i in p["items"]}   # noqa: E731
    assert days(a) == days(b)
    # without the unplace the 24th is still gemini's: iphone-duo there is day_taken
    s, p = post(c, PLAN, {"moves": SHIFT["moves"]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    # ... and openai, whose 25th iphone-duo then keeps
    assert [(r["code"], r["slug"]) for r in p["refusals"]] == [("day_taken", "iphone-duo"),
                                                              ("day_taken", "openai")], p
    assert p["refusals"][0]["message"] == publish_move.MOVE_RU["day_taken"][1]
    assert p["why"] == publish_move.MOVE_RU["day_taken"][1]


def test_unplacing_a_video_in_studio_is_in_studio_and_no_token():
    root = world()
    c = client(root)
    s, p = post(c, PLAN, {"unplace": ["openai"]})
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    assert [r["code"] for r in p["refusals"]] == ["in_studio"], p["refusals"]
    assert p["items"][0]["in_studio"] and p["items"][0]["video_id"] == IDS["openai"]
    assert p["why"] == publish_move.MOVE_RU["in_studio"][1]
    s, p = post(c, PLAN, {})
    assert s == 200 and [r["code"] for r in p["refusals"]] == ["empty_order"], p
    s, p = post(c, PLAN, {"moves": [{"slug": "x", "day": "2026-10-30", "extra": 1}]})
    assert s == 422, p
    s, p = post(c, PLAN, {"unplace": ["x"] * 61})
    assert s == 422 and p["code"] == "invalid", p


def test_an_uncommitted_change_in_publish_is_dirty_and_no_token():
    root = world()
    c = client(root)
    (root / "publish" / "uploads.json").write_text('{"uploads": []}\n', encoding="utf-8")
    s, p = post(c, PLAN, SHIFT)
    assert s == 200 and not p["ok"] and p["confirm"] is None, p
    assert "dirty" in [r["code"] for r in p["refusals"]], p["refusals"]
    assert any("publish/uploads.json" in r["line"] for r in p["refusals"] if r["code"] == "dirty")


# ----------------------------------------------------------------- the confirm
def test_the_confirm_moves_the_shift_and_the_factory_commits_once():
    root = world()
    c = client(root)
    h = head(root)
    s, p = post(c, PLAN, SHIFT)
    assert s == 200 and p["ok"], p
    s, r = post(c, CONFIRM, {"confirm": p["confirm"], "base_sha256": p["base_sha256"]})
    assert s == 200, r
    assert r["ok"] and r["written"] and not r["dry_run"] and r["by"] == "user", r
    assert r["via"] == "center" and r["moved"] == 2 and r["unplaced"] == 1
    assert r["commit"] == head(root) and git(root, "rev-parse", "HEAD~1") == h, r
    assert r["new_sha256"] and r["new_sha256"] != r["base_sha256"]
    pub = root / "publish" / CH
    assert (pub / "_queue" / "gemini.md").is_file() and (pub / "_queue" / "gemini.mp4").is_file()
    assert (pub / "2026-10-24" / "iphone-duo.md").is_file()
    assert (pub / "2026-10-25" / "openai.md").is_file()
    assert not (pub / "2026-10-26" / "openai.md").exists()
    j = journal(root)
    assert j["iphone-duo"]["publish_day"] == "2026-10-24", j["iphone-duo"]
    assert j["openai"]["note"] == f"publish/{CH}/2026-10-25/openai.md"
    assert j["openai"]["rescheduled"][-1]["by"] == "user", j["openai"]
    it = {i["slug"]: i for i in r["items"]}
    assert it["openai"]["journal"]["from_at"] == "2026-10-26T01:00:00+03:00", it["openai"]
    assert it["gemini"]["path"] == f"publish/{CH}/_queue/gemini.md"
    assert any(w.startswith("STUDIO openai") for w in it["openai"]["warnings"])
    assert "publish/uploads.json" in r["touched"]
    assert git(root, "status", "--porcelain", "--", "publish") == "", "nothing left behind"
    assert str(root) not in json.dumps(r)
    s, again = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 409 and again["code"] == "confirm_unknown", again


def test_an_open_batch_is_batch_open_and_nothing_written():
    root = world()
    c = client(root)
    s, p = post(c, PLAN, SHIFT)
    assert s == 200 and p["ok"], p
    before, h = files(root), head(root)
    publish_move.FACTORY_KW["open_rows"] = [(root / "pipeline" / CH / "2026-10-23T2000Z",
                                             None, True)]
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "batch_open", r
    assert r["message"] == publish_move.MOVE_RU["batch_open"][1]
    assert files(root) == before and head(root) == h


def test_a_stale_base_or_a_changed_state_is_check_changed():
    root = world()
    c = client(root)
    s, p = post(c, PLAN, SHIFT)
    assert s == 200 and p["ok"], p
    before, h = files(root), head(root)
    s, r = post(c, CONFIRM, {"confirm": p["confirm"], "base_sha256": "0" * 64})
    assert s == 409 and r["code"] == "check_changed", r
    assert r["message"] == publish_move.MOVE_RU["check_changed"][1]
    assert files(root) == before and head(root) == h
    # the state moves on after the plan (a committed edit of the journal)
    s, p = post(c, PLAN, SHIFT)
    assert s == 200 and p["ok"], p
    doc = json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))
    doc["note"] = "edited after the plan"
    _w(root / "publish" / "uploads.json", doc)
    git(root, "commit", "-q", "-am", "an edit after the plan")
    before, h = files(root), head(root)
    s, r = post(c, CONFIRM, {"confirm": p["confirm"]})
    assert s == 409 and r["code"] == "check_changed", r
    assert files(root) == before and head(root) == h


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

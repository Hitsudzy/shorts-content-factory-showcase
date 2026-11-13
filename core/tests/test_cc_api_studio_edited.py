#!/usr/bin/env python3
"""CC-0106: the user's hand edit of a Studio video (`studio_fields.py edited`,
and `--undo`), plan -> confirm as the other publication writes
(`api/publish_net.py`):

    POST /api/publish/{c}/studio/edited/plan | edited            mark_user_edited(edited)
    POST /api/publish/{c}/studio/edited/undo/plan | undo         mark_user_edited(edited=False)

In-process (the TestClient) against stand-in factory roots in a temp dir
(`tests/test_cc_api_publish.py` `world`: two `studio` rows in
`publish/uploads.json`, `old-one` already marked). Nothing outside the temp
dir is written, the network is refused (`no_network`), the clock is fixed.

What is pinned: the plan is the factory's own dry run (`mark_user_edited(
dry_run=True)`, CF-0720) - the journal's bytes stay, the row after and the
streak after are the factory's; the confirm writes the row once with the
note as given and `user_edited_by: user`, `user_edited_via: center`; by slug or by id,
exactly one; the factory's refusals (no row) and the API's (another
channel's row, already so) get no token; a journal that moved since the plan
is `check_changed`; the undo takes the mark off; a token of the mark is not
an undo's.
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

from test_cc_api_batches import _w, client, git                                 # noqa: E402
from test_cc_api_publish import files, setup, studio_row, world              # noqa: E402
from test_cc_api_publish_writes import head, no_network, post                # noqa: E402

BASE = "/api/publish/reel/studio/edited"
VID = "ZyXwVuTsRq9"          # world()'s `delver`, not marked
OLD = "AbCdEfGhIj0"          # world()'s `old-one`, marked


def journal(root):
    return json.loads((root / "publish" / "uploads.json").read_text(encoding="utf-8"))["uploads"]


def row_of(root, vid):
    return next(r for r in journal(root) if r["video_id"] == vid)


def test_the_mark_plan_writes_nothing_then_the_confirm_marks_the_row_once():
    setup()
    with no_network() as nn:
        root = world()
        c = client(root)
        h0, before = head(root), files(root)
        code, plan = post(c, f"{BASE}/plan", {"slug": "delver", "note": "поправил название"})
        assert code == 200 and plan["ok"] and plan["confirm"], plan
        assert (plan["action"], plan["edited"], plan["video_id"], plan["slug"]) == \
            ("studio_edited", True, VID, "delver"), plan
        assert plan["note"] == "поправил название" and (plan["by"], plan["via"]) == \
            ("user", "center"), plan
        assert plan["before"]["user_edited"] is False and plan["row"]["user_edited"] is True, plan
        assert plan["row"]["user_edit_note"] == "поправил название", plan
        assert (plan["row"]["user_edited_by"], plan["row"]["user_edited_via"]) == \
            ("user", "center"), plan["row"]
        assert "user_edited_by" not in plan["before"], plan["before"]
        assert plan["streak"]["streak"] == 0, plan["streak"]
        assert plan["journal"] == "publish/uploads.json", plan
        assert files(root) == before, "a plan writes nothing"
        assert str(root) not in json.dumps(plan, ensure_ascii=False)
        code, done = post(c, BASE, {"confirm": plan["confirm"]})
        assert code == 200, done
        assert (done["action"], done["edited"]) == ("studio_edited", True), done
        r = row_of(root, VID)
        assert r["user_edited"] is True and r["user_edit_note"] == "поправил название"
        assert (r["user_edited_by"], r["user_edited_via"]) == ("user", "center"), r
        assert (done["by"], done["via"]) == ("user", "center"), done
        assert r["user_edited_at"], r
        assert done["streak"]["streak"] == 0 and done["streak"]["last_edited"]["slug"] == "delver"
        # the token is single use; the plan again: already marked, no token
        code, again = post(c, BASE, {"confirm": plan["confirm"]})
        assert code == 409 and again["code"] == "confirm_unknown", again
        code, again = post(c, f"{BASE}/plan", {"video_id": VID})
        assert code == 200 and not again["ok"] and again["confirm"] is None, again
        assert "уже отмечена" in again["why"], again
        # CC-0153: the mark is one commit of the journal - the tree stays clean there
        assert git(root, "rev-parse", "HEAD~1") == h0, "one commit on top"
        msg = git(root, "log", "-1", "--format=%B")
        assert msg.startswith(f"Публикация: {VID} - правлен в Studio руками (user, center)"), msg
        assert "Cc-Action: studio_edited" in msg and "Cc-Channel: reel" in msg, msg
        assert git(root, "show", "--name-only", "--format=", "HEAD") == "publish/uploads.json"
        assert git(root, "status", "--porcelain", "--", "publish/uploads.json") == ""
    assert nn.net == [], nn.net


def test_the_undo_takes_the_mark_off_and_a_mark_token_is_not_an_undo():
    setup()
    with no_network():
        root = world()
        c = client(root)
        code, plan = post(c, f"{BASE}/undo/plan", {"video_id": OLD})
        assert code == 200 and plan["ok"], plan
        assert (plan["action"], plan["edited"], plan["row"]["user_edited"]) == \
            ("studio_edited_undo", False, False), plan
        # the mark's own token on the undo route: mismatch, nothing written
        code, mark = post(c, f"{BASE}/plan", {"video_id": VID})
        assert mark["ok"], mark
        before = files(root)
        code, r = post(c, f"{BASE}/undo", {"confirm": mark["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        assert files(root) == before
        code, done = post(c, f"{BASE}/undo", {"confirm": plan["confirm"]})
        assert code == 200 and done["edited"] is False, done
        assert row_of(root, OLD)["user_edited"] is False
        assert "Cc-Action: studio_edited_undo" in git(root, "log", "-1", "--format=%B")
        assert git(root, "status", "--porcelain", "--", "publish/uploads.json") == ""
        assert "user_edit_note" not in row_of(root, OLD), row_of(root, OLD)
        assert (row_of(root, OLD)["user_edited_by"], row_of(root, OLD)["user_edited_via"]) == \
            ("user", "center"), row_of(root, OLD)
        # nothing marked: the undo has nothing to change
        code, again = post(c, f"{BASE}/undo/plan", {"video_id": VID})
        assert code == 200 and not again["ok"] and "отметки ручной правки нет" in again["why"]


def test_the_refusals_name_one_video_its_channel_the_factory_s_line_and_a_moved_journal():
    setup()
    with no_network():
        root = world()
        c = client(root)
        for body in ({}, {"video_id": VID, "slug": "delver"}):
            code, r = post(c, f"{BASE}/plan", body)
            assert code == 422 and r["code"] == "invalid", (body, r)
        # the factory's refusal: no such row
        code, r = post(c, f"{BASE}/plan", {"slug": "nobody"})
        assert code == 200 and not r["ok"] and "no journal row" in r["why"], r
        # a row of another channel
        jp = root / "publish" / "uploads.json"
        doc = json.loads(jp.read_text(encoding="utf-8"))
        other = dict(studio_row("elsewhere", "2026-10-07", "OtHeRcHaN01", "2026-10-05T12:00:00Z"),
                     channel="other")
        doc["uploads"].append(other)
        _w(jp, doc)
        code, r = post(c, f"{BASE}/plan", {"video_id": "OtHeRcHaN01"})
        assert code == 200 and not r["ok"] and "канала other" in r["why"], r
        # an unknown channel
        code, r = post(c, "/api/publish/nope/studio/edited/plan", {"video_id": VID})
        assert code == 404 and r["code"] == "unknown_channel", r
        # the journal moved since the plan
        code, plan = post(c, f"{BASE}/plan", {"video_id": VID})
        assert plan["ok"], plan
        doc = json.loads(jp.read_text(encoding="utf-8"))
        doc["uploads"][0]["user_edit_note"] = "кто-то в терминале"
        _w(jp, doc)
        moved = jp.read_bytes()
        code, r = post(c, BASE, {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert jp.read_bytes() == moved
        assert set(r) == {"message", "code", "details"}, r
        # a journal that does not read
        jp.write_text("{not json", encoding="utf-8")
        code, r = post(c, f"{BASE}/plan", {"video_id": VID})
        assert code == 409 and r["code"] == "journal_unreadable", r


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""CC-0107: taking a video off for good on the user's word (`runlog
pool-release --record-withdrawal CHANNEL/BATCH/SLUG --answer "..."`), plan ->
confirm (`api/withdrawal.py`):

    POST /api/batches/{c}/{b}/videos/{slug}/withdraw/plan      the topic, its status, the
                                                               pool's what-if - nothing written
    POST /api/batches/{c}/{b}/videos/{slug}/withdraw {confirm, answer}   record_withdrawal

In-process (the TestClient) against a stand-in factory root in a temp dir: a
batch with two videos whose topics share a pool source, the pool's files
(bytes of nothing), a rejection in the acceptance log. Nothing outside the
temp dir is written, the network is refused (`no_network`).

What is pinned: the plan writes nothing and says what the withdrawal frees
and what stays kept (the shared source, by the other topic); the confirm
takes a Russian answer naming the video - checked before the token is spent
(an empty or non-Russian one: `answer_required`, the factory's rule:
`answer_without_name`, its `check_answer`); then one `withdrawn` row with
the answer as given and `by: user, via: center` (CF-0720), nothing deleted; a second plan has nothing to write; a
world that moved since the plan is `check_changed`; a token of another video
is a mismatch; an unknown batch, a slug that resolves to no topic.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("FACTORY_ROOT", None)
os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import _w, client, factory_tree                    # noqa: E402
from test_cc_api_publish import files                                        # noqa: E402
from test_cc_api_publish_writes import head, no_network, post                # noqa: E402

from api import factory                                                      # noqa: E402

BATCH = "2026-10-01T1000Z"
BASE = f"/api/batches/reel/{BATCH}/videos"
GONE, KEEP = "gone-girl", "keeper"
OWN, SHARED, OTHER = "AaAaAaAaAa1", "ShArEdSrC01", "KkKkKkKkKk1"
ANSWER = f"снимаю {GONE} окончательно, не будем переделывать"


def world():
    root = factory_tree()
    d = root / "pipeline" / "reel" / BATCH
    _w(d / "05-video-editor.json", {"videos": [
        {"output_path": f"/x/videos/{GONE}.mp4", "script_id": "t-gone-script1", "topic_id": "t-gone"},
        {"output_path": f"/x/videos/{KEEP}.mp4", "script_id": "t-keep-script1",
         "topic_id": "t-keep"}]})
    _w(d / "01b-footage-index.json", {"sources_by_topic": {"t-gone": [OWN, SHARED],
                                                           "t-keep": [SHARED, OTHER]}})
    pool = root / "shared" / "footage"
    pool.mkdir(parents=True, exist_ok=True)
    for vid in (OWN, SHARED, OTHER):
        (pool / f"{vid}.mp4").write_bytes(b"\0" * 10)
        (pool / f"{vid}.shots.json").write_text("{}", encoding="utf-8")
    _w(root / "publish" / "acceptance-log.json", {"acceptances": [
        {"entry_id": f"reel/{BATCH}/{GONE}", "topic_id": "t-gone", "verdict": "rejected",
         "answered_at": "2026-10-02T10:00:00Z"}]})
    return root


def journal(root):
    p = root / "shared" / "footage" / "release-log.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if p.is_file() else []


def test_the_plan_says_what_it_frees_then_the_user_s_words_record_one_row():
    with no_network() as nn:
        root = world()
        c = client(root)
        h0, before = head(root), files(root)
        code, plan = post(c, f"{BASE}/{GONE}/withdraw/plan")
        assert code == 200 and plan["ok"] and plan["confirm"], plan
        assert (plan["action"], plan["entry_id"], plan["topic_id"]) == \
            ("video_withdraw", f"reel/{BATCH}/{GONE}", "t-gone"), plan
        assert plan["status"]["status"] == "rejected_not_withdrawn", plan["status"]
        assert plan["status_after"]["status"] == "withdrawn", plan["status_after"]
        assert [s["video_id"] for s in plan["frees"]] == [OWN], plan["frees"]
        assert plan["frees"][0]["files"] == [f"{OWN}.mp4", f"{OWN}.shots.json"], plan["frees"]
        assert plan["frees_bytes"] == 12, plan
        assert [(k["video_id"], k["blocked_by"]) for k in plan["kept"]] == \
            [(SHARED, ["no_video"])], plan["kept"]
        assert plan["journal"] == "shared/footage/release-log.jsonl" and not plan["deletes_now"]
        assert plan["withdrawn_before"] == [] and plan["open_batches"] == [], plan
        assert (plan["by"], plan["via"]) == ("user", "center"), plan
        assert files(root) == before, "a plan writes nothing"
        assert str(root) not in json.dumps(plan, ensure_ascii=False)
        tok = {"confirm": plan["confirm"]}
        # the user's word: empty, not Russian, not naming the video - the token stays
        for answer, code_ in (("", "answer_required"), (f"withdraw {GONE}", "answer_required"),
                              ("снимаю его окончательно", "answer_without_name")):
            code, r = post(c, f"{BASE}/{GONE}/withdraw", dict(tok, answer=answer))
            assert code == 422 and r["code"] == code_, (answer, r)
            assert set(r) == {"message", "code", "details"}, r
            assert files(root) == before, answer
        code, done = post(c, f"{BASE}/{GONE}/withdraw", dict(tok, answer=ANSWER))
        assert code == 200 and done["written"], done
        rows = journal(root)
        assert len(rows) == 1, rows
        row = rows[0]
        assert (row["event"], row["entry_id"], row["topic_id"], row["task"]) == \
            ("withdrawn", f"reel/{BATCH}/{GONE}", "t-gone", "CF-0358"), row
        assert row["answer"] == ANSWER and (row["by"], row["via"]) == ("user", "center"), row
        assert (done["by"], done["via"]) == ("user", "center"), done
        assert done["row"] == row and [s["video_id"] for s in done["frees"]] == [OWN], done
        after = files(root)
        assert set(after) - set(before) == {"shared/footage/release-log.jsonl"}, \
            set(after) ^ set(before)
        assert all(after[k] == v for k, v in before.items()), "nothing else touched, nothing deleted"
        # spent; and recorded - the plan again has nothing to write
        code, r = post(c, f"{BASE}/{GONE}/withdraw", dict(tok, answer=ANSWER))
        assert code == 409 and r["code"] == "confirm_unknown", r
        code, again = post(c, f"{BASE}/{GONE}/withdraw/plan")
        assert code == 200 and not again["ok"] and again["confirm"] is None, again
        assert "уже снят" in again["why"] and len(again["withdrawn_before"]) == 1, again
        assert head(root) == h0, "the journal is state outside git, not a commit"
    assert nn.net == [], nn.net


def test_a_world_that_moved_is_check_changed_and_another_video_s_token_a_mismatch():
    with no_network():
        root = world()
        c = client(root)
        code, plan = post(c, f"{BASE}/{GONE}/withdraw/plan")
        assert plan["ok"], plan
        code, other = post(c, f"{BASE}/{KEEP}/withdraw/plan")
        assert other["ok"], other
        code, r = post(c, f"{BASE}/{GONE}/withdraw",
                       {"confirm": other["confirm"], "answer": ANSWER})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        # the keeper withdrawn at the terminal meanwhile: what the plan frees moved
        factory.pool_release().record_withdrawal(root, f"reel/{BATCH}/{KEEP}",
                                                 f"снять {KEEP} тоже")
        moved = journal(root)
        code, r = post(c, f"{BASE}/{GONE}/withdraw", {"confirm": plan["confirm"], "answer": ANSWER})
        assert code == 409 and r["code"] == "check_changed", r
        assert journal(root) == moved


def test_an_unknown_batch_a_bad_slug_and_a_slug_with_no_topic():
    with no_network():
        root = world()
        c = client(root)
        before = files(root)
        code, r = post(c, f"/api/batches/reel/2026-01-01T0000Z/videos/{GONE}/withdraw/plan")
        assert code == 404 and r["code"] == "unknown_batch", r
        code, r = post(c, f"{BASE}/.../withdraw/plan")
        assert code == 404 and r["code"] in ("unknown_video", "unknown_batch"), r
        code, r = post(c, f"{BASE}/nobody/withdraw/plan")
        assert code == 200 and not r["ok"] and r["topic_id"] is None and r["confirm"] is None, r
        assert "не находится" in r["why"], r
        assert files(root) == before


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

"""CC-0152 (CF-0821): an accepted video the копилка did not get, in the
verdict's answer (`POST /api/batches/{c}/{b}/videos/{slug}/acceptance`).

In-process against the stand-in factory of `tests/test_cc_api_videos.py`; the
factory's acceptance code is this checkout's. The notification bus is the
factory's own stand-in (`acceptance.NOTIFY`), never the real one; nothing
leaves the machine.

What is pinned:

* `queued` carries `left_out`, `alert_ru`, `namesake` and `notified` - a
  placed video: left_out false, alert null, nothing sent; a video with no
  render: left_out true, `text_ru` opening with «НЕ В КОПИЛКЕ: », the alert,
  the bus's answer; the top-level `left_out` is the factory's record;
* a verdict queued under an open batch and flushed by the next verdict: the
  flush's `left_out` lists it;
* `_queued` keeps a namesake as `{entry_id, publish_path, why}` and an older
  factory's answer (no CF-0821 keys) still reads.
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

from test_cc_api_batches import client, marker, write_batch   # noqa: E402
from test_cc_api_videos import BATCH, _post, tree              # noqa: E402

from api import videos                                         # noqa: E402
from api.app import AcceptQueued, AcceptResult                 # noqa: E402

MARK = "НЕ В КОПИЛКЕ: "
SENT = []


class bus:
    """The factory's own stand-in of the notification bus, restored after."""

    def __enter__(self):
        self.acc = videos._acc()
        self.saved = self.acc.NOTIFY
        SENT.clear()

        def notify(kind, key, text, channel=None, link=None, root=None):
            SENT.append({"kind": kind, "key": key, "text": text, "channel": channel})
            return {"status": "sent", "key": key}
        self.acc.NOTIFY = notify
        return self

    def __exit__(self, *exc):
        self.acc.NOTIFY = self.saved


def test_a_placed_video_is_not_left_out():
    root = tree()
    with bus():
        r = _post(client(root), "paper-dragon", verdict="yes", words="Paper Dragon — да")
    assert r.status_code == 200, r.text
    j = r.json()
    q = j["queued"]
    assert q["code"] == "placed" and q["left_out"] is False, q
    assert q["alert_ru"] is None and q["namesake"] is None and q["notified"] is None, q
    assert not q["text_ru"].startswith(MARK), q
    assert j["left_out"] is None and SENT == [], (j["left_out"], SENT)


def test_a_video_with_no_render_is_left_out_and_said_loudly():
    root = tree()
    with bus():
        r = _post(client(root), "no-file", verdict="yes", words="no-file — да")
    assert r.status_code == 200, r.text
    j = r.json()
    q = j["queued"]
    assert q["code"] == "render_missing" and q["left_out"] is True and q["refused"], q
    assert q["text_ru"].startswith(MARK), q
    assert q["alert_ru"] and "no-file" in q["alert_ru"] and "копилку" in q["alert_ru"], q
    assert q["notified"] == {"status": "sent", "key": f"stash-left-out:reel/{BATCH}/no-file:"
                                                      f"render_missing"}, q
    assert len(SENT) == 1 and SENT[0]["kind"] == "needs_human", SENT
    lo = j["left_out"]
    assert lo["entry_id"] == f"reel/{BATCH}/no-file" and lo["slug"] == "no-file", lo
    assert lo["batch_id"] == BATCH and lo["code"] == "render_missing", lo
    assert lo["text_ru"] == q["text_ru"] and lo["alert_ru"] == q["alert_ru"], lo
    assert lo["notified"] == q["notified"] and lo["namesake"] is None, lo
    assert str(root) not in json.dumps([q, lo]), (q, lo)


def test_a_flushed_queue_names_its_left_out_videos():
    root = tree()
    c = client(root)
    going = write_batch(root, "reel", "2026-10-10T1200Z", [marker("batch-start", hours_ago=0.05)])
    with bus():
        r = _post(c, "no-file", verdict="yes", words="no-file — да")
        assert r.status_code == 200 and r.json()["pending"] is True, r.text
        assert r.json()["left_out"]["code"] == "render_missing", r.json()
        with open(going / "RUN_EVENTS.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(marker("batch-done")) + "\n")
        r = _post(c, "night-owl", verdict="no", words="night-owl нет", reason="скучно",
                  reason_code="boring")
    assert r.status_code == 200, r.text
    f = r.json()["flushed"]
    assert f and f["committed"] is True, f
    assert [x["entry_id"] for x in f["left_out"]] == [f"reel/{BATCH}/no-file"], f
    assert f["left_out"][0]["text_ru"].startswith(MARK), f
    assert r.json()["left_out"] is None, r.json()          # a rejection has none


def test_the_queued_answer_keeps_a_namesake_and_an_older_answer_reads():
    root = Path("/x/root")
    q = {"code": "placed", "text_ru": "в копилке", "publish_path": "publish/reel/_queue/a.mp4",
         "ok": True, "changed": True, "left_out": False, "alert_ru": None,
         "namesake": {"entry_id": "reel/2026-09-01T0900Z/a",
                      "publish_path": "publish/reel/_published/a.mp4", "why": "другая тема",
                      "extra": 1}}
    got = videos._queued(root, q)
    assert got["namesake"] == {"entry_id": "reel/2026-09-01T0900Z/a",
                               "publish_path": "publish/reel/_published/a.mp4",
                               "why": "другая тема"}, got
    AcceptQueued.model_validate(got)
    old = videos._queued(root, {"code": "placed", "text_ru": "x", "ok": True})
    assert old["left_out"] is False and old["namesake"] is None and old["notified"] is None
    m = AcceptQueued.model_validate({"code": "placed", "text_ru": "x", "ok": True,
                                     "skipped": False, "refused": False, "changed": False})
    assert m.left_out is False and m.alert_ru is None and m.namesake is None
    assert AcceptResult.model_fields["left_out"].default is None


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

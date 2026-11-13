#!/usr/bin/env python3
"""CC-0167 (CF-0857): the center finds a video by its batch, and a name with
two places by the day the request names.

    POST /api/publish/{c}/card/place/plan   `_place_check` -> publish_layout.of_batch
    GET  /api/publish/{c}/notes/{slug}      studio_fields.locate (?day=)
    POST /api/publish/{c}/upload/plan       studio_fields.locate (body day)
    POST /api/publish/{c}/studio/record/plan

23.10 Tech: «Разместить в слот» for `anthropic` was refused «ролика нет в
publish/example-tech/» with the video in `_queue/` - the «День» field held the
slot (26.10), not the folder the video lies in. The plan now reads the video
the way the confirm (`publish_card.place`) does: the batch's own acceptance
row (`publish_path`), the day narrowing to the folder it lies in now, the
refusal saying where it is. A namesake of another batch is never the video.

A bare name with two or more places not in the upload journal is 404
`unknown_note` naming the day; with the day, that place.

In-process against stand-in roots in a temp dir (`test_cc_api_batches`
`factory_tree`); the clock is fixed, the network refused, nothing outside the
temp dir is written.
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

from test_cc_api_batches import _w, client                                 # noqa: E402
from test_cc_api_publish import (BATCH, DAY, SLUG, acceptance, card_text,  # noqa: E402
                                 files, get, setup, world)
from test_cc_api_publish_writes import card_world, no_network, post        # noqa: E402

from api import publish                                                   # noqa: E402

OTHER = "2026-10-06T0900Z"          # a later batch that reused the name
PLAN = "/api/publish/reel/card/place/plan"


def _log(root, *rows):
    _w(root / "publish" / "acceptance-log.json", {"acceptances": list(rows)})


# --------------------------------------------------------------- the placing
def test_a_video_in_the_queue_with_the_slot_s_day_is_refused_saying_where_it_is():
    """The 23.10 shape: the video waits in _queue/, the request names the slot's day."""
    setup()
    root, _d = card_world()
    c = client(root)
    before = files(root)
    code, plan = post(c, PLAN, {"batch_id": BATCH, "slug": SLUG, "day": "2026-10-07"})
    assert code == 200 and not plan["ok"] and plan["confirm"] is None, plan
    why = plan["why"]
    assert f"ролика батча {BATCH} нет в publish/reel/2026-10-07/" in why, why
    assert "«День» - папка, где ролик лежит сейчас" in why, why
    assert "is in publish/reel/_queue/" in why, why           # of_batch's where
    assert plan["bucket"] is None and plan["target"] is None and plan["day"] == "2026-10-07"
    # the folder it lies in: found, no slot planned (the day was named)
    code, plan = post(c, PLAN, {"batch_id": BATCH, "slug": SLUG, "day": "_queue"})
    assert code == 200 and plan["ok"] and plan["bucket"] == "_queue", plan
    assert plan["target"] == f"publish/reel/_queue/{SLUG}.md" and plan["slot"] is None, plan
    # no day: the batch's video in _queue/ and the next slot
    code, plan = post(c, PLAN, {"batch_id": BATCH, "slug": SLUG})
    assert code == 200 and plan["ok"] and plan["why"] is None, plan
    assert plan["bucket"] == "_queue" and plan["slot"]["day"] == "2026-10-07", plan
    assert files(root) == before, "a plan writes nothing"


def test_the_batch_s_video_not_the_latest_namesake():
    """The batch's video lies on a day; a later batch's video of the same name
    waits in _queue/ (the latest place of the name). The plan and the confirm
    take the batch's own - before CC-0167 the plan took _queue/."""
    setup()
    root, _d = card_world()
    pub = root / "publish" / "reel"
    (pub / "_queue" / f"{SLUG}.mp4").rename(pub / "_queue" / "tmp.mp4")
    day = pub / "2026-10-09"
    day.mkdir()
    (pub / "_queue" / "tmp.mp4").rename(day / f"{SLUG}.mp4")
    (pub / "_queue" / f"{SLUG}.mp4").write_bytes(b"\1")            # the other batch's
    _log(root, acceptance(SLUG, day="2026-10-09"), acceptance(SLUG, batch=OTHER, day="_queue"))
    c = client(root)
    code, plan = post(c, PLAN, {"batch_id": BATCH, "slug": SLUG})
    assert code == 200 and plan["ok"], plan
    assert plan["bucket"] == "2026-10-09" and plan["slot"] is None, plan
    assert plan["target"] == f"publish/reel/2026-10-09/{SLUG}.md", plan
    code, done = post(c, "/api/publish/reel/card/place", {"confirm": plan["confirm"]})
    assert code == 200, done
    assert done["path"] == f"publish/reel/2026-10-09/{SLUG}.md", done
    assert (day / f"{SLUG}.md").is_file()
    assert not (pub / "_queue" / f"{SLUG}.md").exists(), "the namesake is left alone"
    assert (pub / "_queue" / f"{SLUG}.mp4").read_bytes() == b"\1"
    # the namesake's folder named: the batch's video is not there
    code, plan = post(c, PLAN, {"batch_id": BATCH, "slug": SLUG, "day": "_queue",
                                "replace": True})
    assert code == 200 and not plan["ok"] and "is in publish/reel/2026-10-09/" in plan["why"], plan


def test_an_acceptance_record_that_does_not_read_is_the_refusal_not_a_500():
    setup()
    root, _d = card_world()
    (root / "publish" / "acceptance-log.json").write_text("{not json", encoding="utf-8")
    code, plan = post(client(root), PLAN, {"batch_id": BATCH, "slug": SLUG})
    assert code == 200 and not plan["ok"] and "acceptance record" in plan["why"], plan


# --------------------------------------------------------------- two places of one name
def two_places():
    """test_cc_api_publish's world (SLUG placed on DAY) and a second SLUG of
    another batch in _queue/ - neither in the upload journal."""
    root = world()
    q = root / "publish" / "reel" / "_queue"
    (q / f"{SLUG}.md").write_text(card_text(batch=OTHER, publish_line="Слот не назначен."),
                                  encoding="utf-8")
    (q / f"{SLUG}.mp4").write_bytes(b"\0")
    return root


def test_two_places_of_one_name_need_the_day():
    setup()
    root = two_places()
    code, bad = get(root, f"/api/publish/reel/notes/{SLUG}")
    assert code == 404 and bad["code"] == "unknown_note", bad
    assert "2 places of this name" in bad["message"] and "(--day)" in bad["message"], bad
    assert "в запросе поле day" in bad["message"], bad
    code, n = get(root, f"/api/publish/reel/notes/{SLUG}", day=DAY)
    assert code == 200 and n["path"] == f"publish/reel/{DAY}/{SLUG}.md", n
    code, n = get(root, f"/api/publish/reel/notes/{SLUG}", day="_queue")
    assert code == 200 and n["path"] == f"publish/reel/_queue/{SLUG}.md", n
    c = client(root)
    with no_network():
        for path, body in (("/api/publish/reel/upload/plan", {"slug": SLUG}),
                           ("/api/publish/reel/studio/record/plan",
                            {"slug": SLUG, "video_id": "AbCdEfGhIj1", "read": {}})):
            code, bad = post(c, path, body)
            assert code == 404 and bad["code"] == "unknown_note", (path, bad)
            assert "(--day)" in bad["message"], (path, bad)
            code, r = post(c, path, dict(body, day=DAY))
            assert code != 404 or r.get("code") != "unknown_note", (path, r)


def test_a_place_already_in_the_journal_leaves_the_other_one():
    setup()
    root = two_places()
    j = root / "publish" / "uploads.json"
    doc = json.loads(j.read_text(encoding="utf-8"))
    doc["uploads"].append({"channel": "reel", "slug": SLUG, "video_id": "PlAcEd12345",
                           "source": "studio", "publish_at": f"{DAY}T01:00:00+03:00",
                           "publish_day": DAY, "recorded_at": "2026-10-06T08:30:00Z",
                           "user_edited": False, "entry_id": f"reel/{BATCH}/{SLUG}",
                           "note": f"publish/reel/{DAY}/{SLUG}.md"})
    _w(j, doc)
    code, n = get(root, f"/api/publish/reel/notes/{SLUG}")
    assert code == 200 and n["path"] == f"publish/reel/_queue/{SLUG}.md", n


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    publish.FACTORY_KW.clear()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

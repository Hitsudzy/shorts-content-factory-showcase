#!/usr/bin/env python3
"""CF-0587: the channel's publication queue (`agents/publisher/publish_queue.py`).

Every root is a fixture in a temp dir; the committed publish/ is never read.

What is pinned:

* the slot comes from `channels/<ch>.json` -> `publisher.slot` (the committed
  ExampleFilm block is 01:00 Europe/Moscow, 1/day); a channel without it has no
  queue; a block without a zone, with a bad time, or with per_day > 1 and one
  time is refused;
* the nearest free slot: from today's slot if it is still `lead` ahead, else
  tomorrow; days held by a day folder or a live journal row are skipped (a
  removed row holds nothing; one video in both is one occupant);
* placing: only an accepted video with no open publication hold;
* tomorrow: an empty slot is exit 1 with a line naming the slot and the
  _queue/, a taken one is `ok`, a paused channel is exit 3;
* a second channel in New York at 23:30: its slot falls on the next Moscow
  day (the folder), across the DST change too;
* the two extension points (CF-0569 pause, CF-0042 candidate check) are called
  and obeyed (the window itself: tests/test_publish_window.py).
"""
import io
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import publish_queue as pq          # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("publish-queue-test-")
_n = [0]
CH = "example-film"
NY = "testnight"
MSK_SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
NY_SLOT = {"time": "23:30", "tz": "America/New_York", "per_day": 1, "lead_hours": 1}


def _root(slot=MSK_SLOT, channel=CH, days=(), journal=(), accepted=(), holds=()):
    """A data root: channels/<channel>.json with `slot`, day folders `days`
    (`{day: [slug or (slug, publish line)]}`), journal rows, acceptances."""
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    (r / "channels").mkdir(parents=True)
    (r / "publish").mkdir()
    cfg = {"channel_id": channel, "publisher": {} if slot is None else {"slot": slot}}
    (r / "channels" / f"{channel}.json").write_text(json.dumps(cfg), encoding="utf-8")
    for day, items in dict(days).items():
        d = r / "publish" / channel / day
        d.mkdir(parents=True)
        for it in items:
            slug, line = it if isinstance(it, tuple) else (it, None)
            (d / f"{slug}.mp4").write_bytes(b"\0")
            if line:
                (d / f"{slug}.md").write_text(f"# {slug}\n\n## Публикация\n{line}\n", encoding="utf-8")
    (r / "publish" / "uploads.json").write_text(json.dumps({"uploads": list(journal)}),
                                                encoding="utf-8")
    (r / "publish" / "acceptance-log.json").write_text(json.dumps({"acceptances": [
        {"entry_id": f"{channel}/B1/{s}", "channel": channel, "batch_id": "B1", "slug": s,
         "topic_id": f"t-{s}", "verdict": v, "answered_at": "2026-10-06T10:00:00Z"}
        for s, v in accepted]}), encoding="utf-8")
    (r / "publish" / "publication-holds.json").write_text(json.dumps({"holds": [
        {"hold_id": f"{channel}/B1/t-{s}", "channel": channel, "batch_id": "B1",
         "topic_id": f"t-{s}", "verdict": "review", "reason_code": "compliance_review_hold"}
        for s in holds]}), encoding="utf-8")
    return r


def _row(day, slug, vid, at=True, removed=False, channel=CH):
    r = {"channel": channel, "slug": slug, "video_id": vid, "publish_day": day,
         "publish_at": f"{day}T01:00:00+03:00" if at else None}
    if removed:
        r["removed_at"] = "2026-10-05T00:00:00Z"
    return r


def _day(at):
    return pq.msk_day(at)


def _refused(fn, kind=pq.QueueError):
    try:
        fn()
    except kind as e:
        return str(e)
    raise AssertionError("not refused")


# ------------------------------------------------------------------ config
def test_the_committed_channel_slot_is_one_am_moscow_one_a_day():
    cfg = pq.slot_config(CH, ROOT)
    assert cfg["tz"] == "Europe/Moscow" and cfg["per_day"] == 1
    assert [t.strftime("%H:%M") for t in cfg["times"]] == ["01:00"]


def test_a_channel_without_a_slot_has_no_queue_and_a_bad_block_is_refused():
    assert pq.slot_config(CH, _root(slot=None)) is None
    assert "no publisher.slot" in _refused(lambda: pq.table(CH, _root(slot=None), "2026-10-06T12:00Z"))
    assert "`tz`" in _refused(lambda: pq.slot_config(CH, _root(slot={"time": "01:00"})))
    assert "HH:MM" in _refused(lambda: pq.slot_config(CH, _root(slot={"time": "25:00", "tz": "UTC"})))
    assert "need `times`" in _refused(lambda: pq.slot_config(
        CH, _root(slot={"time": "01:00", "tz": "UTC", "per_day": 2})))
    assert "IANA" in _refused(lambda: pq.slot_config(CH, _root(slot={"time": "01:00", "tz": "Mars/Base"})))
    two = pq.slot_config(CH, _root(slot={"times": ["18:00", "01:00"], "tz": "UTC", "per_day": 2}))
    assert [t.strftime("%H:%M") for t in two["times"]] == ["01:00", "18:00"]


# ------------------------------------------------------------------ nearest
def test_the_nearest_slot_is_tomorrow_once_todays_has_passed():
    r = _root()
    assert _day(pq.next_free(CH, r, "2026-10-06T12:00:00+03:00")) == "2026-10-07"
    # 00:30 MSK: today's 01:00 is 30 minutes away - inside the 2 h lead
    assert _day(pq.next_free(CH, r, "2026-10-06T00:30:00+03:00")) == "2026-10-07"
    # with no lead it is still today's
    r0 = _root(slot=dict(MSK_SLOT, lead_hours=0))
    at = pq.next_free(CH, r0, "2026-10-06T00:30:00+03:00")
    assert _day(at) == "2026-10-06" and at.strftime("%H:%M") == "01:00"
    # never in the past
    assert pq.next_free(CH, r0, "2026-10-06T12:00:00+03:00") > datetime.fromisoformat(
        "2026-10-06T12:00:00+03:00")


def test_taken_days_from_folders_and_the_journal_are_skipped():
    r = _root(days={"2026-10-07": ["a"], "2026-10-08": [("b", "**2026-10-08 01:00 МСК** — слот")],
                    "2026-10-10": ["d"]},
              journal=[_row("2026-10-08", "b", "VIDEOBBBBBB"), _row("2026-10-09", "c", "VIDEOCCCCCC"),
                       _row("2026-10-11", "x", "VIDEOXXXXXX", removed=True),
                       _row("2026-10-12", "e", "VIDEOEEEEEE", at=False)])
    rows = pq.table(CH, r, "2026-10-06T12:00:00+03:00", days=8)
    taken = {r_["day"]: r_["taken_by"] for r_ in rows}
    assert taken["2026-10-07"] == "a" and taken["2026-10-08"] == "b" and taken["2026-10-09"] == "c"
    assert taken["2026-10-10"] == "d" and taken["2026-10-12"] == "e"
    assert taken["2026-10-11"] is None                      # a removed row holds nothing
    occ = [o for o in pq.occupants(CH, r) if o["slug"] == "b"]
    assert len(occ) == 1 and len(occ[0]["sources"]) == 2    # folder + journal = one video
    assert _day(pq.next_free(CH, r, "2026-10-06T12:00:00+03:00")) == "2026-10-11"


def test_an_unreadable_journal_stops_the_queue():
    r = _root()
    (r / "publish" / "uploads.json").write_text("[]", encoding="utf-8")
    assert "journal" in _refused(lambda: pq.next_free(CH, r, "2026-10-06T12:00Z"))


# ------------------------------------------------------------------ placing
def test_only_an_accepted_video_without_a_hold_gets_a_slot():
    r = _root(accepted=[("ok", "accepted"), ("held", "accepted"), ("no", "rejected")],
              holds=["held"], days={"2026-10-07": ["a"]})
    plan = pq.plan_slot(CH, "B1", "ok", r, "2026-10-06T12:00:00+03:00")
    assert plan["day"] == "2026-10-08" and "**2026-10-08 01:00 МСК**" in plan["line"]
    assert "hold" in _refused(lambda: pq.plan_slot(CH, "B1", "held", r, "2026-10-06T12:00Z"))
    assert "not accepted" in _refused(lambda: pq.plan_slot(CH, "B1", "no", r, "2026-10-06T12:00Z"))
    assert "not accepted" in _refused(lambda: pq.plan_slot(CH, "B1", "ghost", r, "2026-10-06T12:00Z"))


# ------------------------------------------------------------------ tomorrow
def test_tomorrow_empty_taken_and_the_line_for_the_orchestrator():
    r = _root(days={"2026-10-07": ["a"]})
    code, line = pq.tomorrow(CH, r, "2026-10-06T12:00:00+03:00")
    assert code == pq.EXIT_OK and "2026-10-07 01:00 МСК a" in line, line
    q = r / "publish" / CH / "_queue"
    q.mkdir(parents=True)
    (q / "waiting.mp4").write_bytes(b"\0")
    code, line = pq.tomorrow(CH, r, "2026-10-07T12:00:00+03:00")
    assert code == pq.EXIT_EMPTY, line
    assert "EMPTY SLOT 2026-10-08 01:00 МСК" in line and "waiting" in line, line
    out = io.StringIO()
    assert pq.main(["tomorrow", "--root", str(r), "--now", "2026-10-07T12:00:00+03:00"], out=out) == 1
    assert "EMPTY SLOT" in out.getvalue()
    # 00:30: today's slot is still ahead and counts
    code, line = pq.tomorrow(CH, _root(days={"2026-10-07": ["a"]}), "2026-10-06T00:30:00+03:00")
    assert code == pq.EXIT_EMPTY and "2026-10-06 01:00" in line and "2026-10-07" not in line, line


def test_show_and_next_print_the_table():
    r = _root(days={"2026-10-07": ["a"]})
    out = io.StringIO()
    assert pq.main(["show", "--root", str(r), "--now", "2026-10-06T12:00:00+03:00", "--days", "3"],
                   out=out) == 0
    text = out.getvalue()
    assert "2026-10-07 01:00 МСК" in text and "a" in text and "<- next free" in text, text
    out = io.StringIO()
    pq.main(["next", "--root", str(r), "--now", "2026-10-06T12:00:00+03:00"], out=out)
    assert "next free slot 2026-10-08 01:00 МСК -> publish/example-film/2026-10-08/" in out.getvalue()


# ------------------------------------------------------------------ another zone
def test_a_new_york_channel_crosses_midnight_into_the_next_moscow_day():
    r = _root(slot=NY_SLOT, channel=NY)
    at = pq.next_free(NY, r, "2026-10-07T20:00:00-04:00")
    assert at.strftime("%Y-%m-%d %H:%M") == "2026-10-07 23:30" and _day(at) == "2026-10-08"
    assert "(2026-10-08 06:30 МСК)" in pq.label(at, pq.slot_config(NY, r))
    # the folder of the Moscow day holds that slot
    r2 = _root(slot=NY_SLOT, channel=NY, days={"2026-10-08": ["n1"]})
    at2 = pq.next_free(NY, r2, "2026-10-07T20:00:00-04:00")
    assert at2.strftime("%Y-%m-%d %H:%M") == "2026-10-08 23:30" and _day(at2) == "2026-10-09"
    # 22:45 local: the 23:30 slot is inside the 1 h lead
    assert pq.next_free(NY, r, "2026-10-07T22:45:00-04:00").strftime("%d %H:%M") == "08 23:30"
    # the DST change (1 Nov 2026): the same local 23:30 is 06:30 then 07:30 in Moscow
    rows = pq.table(NY, r, "2026-10-31T12:00:00-04:00", days=2)
    assert [(x["day"], x["at"].astimezone(pq._zone("Europe/Moscow")).strftime("%H:%M")) for x in rows] \
        == [("2026-11-01", "06:30"), ("2026-11-02", "07:30")]
    plan = pq.plan_slot  # the publish line names both zones
    r3 = _root(slot=NY_SLOT, channel=NY, accepted=[("v", "accepted")])
    line = plan(NY, "B1", "v", r3, "2026-10-07T20:00:00-04:00")["line"]
    assert line.startswith("**2026-10-08 06:30 МСК** (2026-10-07 23:30 America/New_York"), line
    import publish_note
    assert publish_note.publish_time(line).isoformat() == "2026-10-08T03:30:00+00:00"


# ------------------------------------------------------------------ extension points
def test_the_pause_and_candidate_hooks_are_called_and_obeyed():
    r = _root(accepted=[("v", "accepted")])
    seen = []

    def pause(channel, root, now):
        seen.append(("pause", channel))
        return "paused by the operator" if channel == CH else None

    def candidate(channel, slug, slot, root, now, ctx=None):
        seen.append(("candidate", channel, slug, _day(slot), (ctx or {}).get("batch_id")))
        return {"verdict": "reorder", "reason": "pattern list x4 in the window"}

    saved, saved_pause = list(pq.CANDIDATE_CHECKS), list(pq.PAUSE_CHECKS)
    try:
        pq.PAUSE_CHECKS.append(pause)
        assert "paused" in _refused(lambda: pq.plan_slot(CH, "B1", "v", r, "2026-10-06T12:00Z"),
                                    pq.Paused)
        code, line = pq.tomorrow(CH, r, "2026-10-06T12:00Z")
        assert code == pq.EXIT_PAUSED and "paused" in line
        pq.PAUSE_CHECKS.remove(pause)
        pq.CANDIDATE_CHECKS[:] = [candidate]
        # CF-0042: a reorder with nothing to swap with still places, out loud
        plan = pq.plan_slot(CH, "B1", "v", r, "2026-10-06T12:00:00+03:00")
        assert plan["day"] == "2026-10-07" and plan["moves"] == []
        assert any("ПОВТОРОМ" in w and "pattern list x4" in w for w in plan["warnings"])
        assert ("candidate", CH, "v", "2026-10-07", "B1") in seen and ("pause", CH) in seen
        # a check that says nothing lets the slot through
        pq.CANDIDATE_CHECKS[:] = [lambda *a: None]
        plan = pq.plan_slot(CH, "B1", "v", r, "2026-10-06T12:00:00+03:00")
        assert plan["day"] == "2026-10-07" and plan["warnings"] == []
    finally:
        pq.PAUSE_CHECKS[:] = saved_pause
        pq.CANDIDATE_CHECKS[:] = saved


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

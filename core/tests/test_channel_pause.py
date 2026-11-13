#!/usr/bin/env python3
"""CF-0569: the channel's pause flag (`agents/publisher/channel_pause.py`) and
the gates that obey it - the queue (`publish_queue.PAUSE_CHECKS`) and the
upload / Studio gate (`upload_gate.check_channel_not_paused`).

Every root is a fixture in a temp dir; the committed publish/ is never read.
`publish_card.py place` on a paused channel: tests/test_publish_card.py;
`upload.py` on a paused channel: tests/test_publisher_upload.py.

What is pinned:

* set / clear / show (CLI and functions): who, why, when, until; clearing
  keeps the row with who and when (history is never lost); one open pause per
  channel (a second is refused, `--replace` closes the first with a note); a
  typo of a channel, an empty reason, a past `--until` are refused;
* `--until DATE` is 00:00 Moscow of that day; an expired pause holds nothing
  but is said (status `expired`, a notice);
* a registry that does not parse pauses every channel (fail closed);
* the queue: `plan_slot` raises `Paused`, `tomorrow` answers exit 3; an
  expired pause places and carries a `PAUSE` warning; the other channel is not
  touched;
* the upload / Studio gate refuses a paused channel and passes the other.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import channel_pause as cp          # noqa: E402
import publish_queue as pq          # noqa: E402
import upload_gate                  # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("channel-pause-test-")
_n = [0]
CH, OTHER = "example-film", "testnight"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
NOW = "2026-10-06T12:00:00+03:00"


def _root():
    """Two channels with a slot, both with an accepted video `v` in _queue/."""
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    (r / "channels").mkdir(parents=True)
    (r / "publish").mkdir()
    for ch in (CH, OTHER):
        (r / "channels" / f"{ch}.json").write_text(
            json.dumps({"channel_id": ch, "publisher": {"slot": SLOT}}), encoding="utf-8")
        (r / "publish" / ch / "_queue").mkdir(parents=True)
        (r / "publish" / ch / "_queue" / "v.mp4").write_bytes(b"\0")
    (r / "publish" / "uploads.json").write_text(json.dumps({"uploads": []}), encoding="utf-8")
    (r / "publish" / "acceptance-log.json").write_text(json.dumps({"acceptances": [
        {"entry_id": f"{ch}/B1/v", "channel": ch, "batch_id": "B1", "slug": "v",
         "topic_id": "t-v", "verdict": "accepted", "answered_at": "2026-10-06T10:00:00Z"}
        for ch in (CH, OTHER)]}), encoding="utf-8")
    return r


def _cli(*argv):
    out = io.StringIO()
    code = cp.main(list(argv), out=out)
    return code, out.getvalue()


def _refused(fn, kind=cp.PauseError):
    try:
        fn()
    except kind as e:
        return str(e)
    raise AssertionError("not refused")


def _doc(r):
    return json.loads((r / "publish" / cp.REGISTRY).read_text(encoding="utf-8"))["pauses"]


# ------------------------------------------------------------------ the flag
def test_set_show_clear_keep_the_history():
    r = _root()
    code, out = _cli("show", "--root", str(r), "--now", NOW)
    assert code == 0 and "не на паузе" in out, out
    code, out = _cli("set", "--channel", CH, "--by", "user", "--reason", "нарушение от студии X",
                     "--until", "2026-10-20", "--root", str(r), "--now", NOW)
    assert code == 0 and "на паузе" in out and "2026-10-20 00:00 МСК" in out, out
    row = _doc(r)[0]
    assert row["by"] == "user" and row["reason"] == "нарушение от студии X"
    assert row["set_at"] == "2026-10-06T09:00:00Z" and row["until"] == "2026-10-20T00:00:00+03:00"
    assert row["cleared_at"] is None
    code, out = _cli("show", "--channel", CH, "--root", str(r), "--now", NOW)
    assert code == cp.EXIT_PAUSED and "НА ПАУЗЕ" in out and "нарушение" in out, out
    # a second pause is refused; --replace closes the first with a note
    code, out = _cli("set", "--channel", CH, "--by", "monitor", "--reason", "2 нарушение",
                     "--root", str(r), "--now", "2026-10-06T13:00:00+03:00")
    assert code == cp.EXIT_ERROR and "already has a pause" in out, out
    code, out = _cli("set", "--channel", CH, "--by", "monitor", "--reason", "2 нарушение",
                     "--replace", "--root", str(r), "--now", "2026-10-06T13:00:00+03:00")
    assert code == 0, out
    rows = _doc(r)
    assert len(rows) == 2 and rows[0]["cleared_by"] == "monitor"
    assert "заменена" in rows[0]["clear_note"] and rows[1]["until"] is None
    assert "бессрочно" in cp.status(CH, r, NOW)["line"]
    code, out = _cli("clear", "--channel", CH, "--by", "user", "--note", "нарушение отозван",
                     "--root", str(r), "--now", "2026-10-07T10:00:00Z")
    assert code == 0 and "снята" in out, out
    rows = _doc(r)
    assert len(rows) == 2 and rows[1]["cleared_at"] == "2026-10-07T10:00:00Z"
    assert rows[1]["cleared_by"] == "user" and rows[1]["clear_note"] == "нарушение отозван"
    code, out = _cli("show", "--channel", CH, "--history", "--root", str(r),
                     "--now", "2026-10-07T11:00:00Z")
    assert code == 0 and "паузы нет" in out and out.count("снята") == 2, out
    assert len(cp.history(CH, r)) == 2 and cp.open_row(CH, r) is None
    code, out = _cli("clear", "--channel", CH, "--by", "user", "--root", str(r))
    assert code == cp.EXIT_ERROR and "no pause to clear" in out, out


def test_bad_input_is_refused():
    r = _root()
    assert "channels/example-film.json" in _refused(
        lambda: cp.set_pause("example-film", "user", "x", root=r, now=NOW))
    assert "--reason" in _refused(lambda: cp.set_pause(CH, "user", "  ", root=r, now=NOW))
    assert "--by" in _refused(lambda: cp.set_pause(CH, "Пользователь", "x", root=r, now=NOW))
    assert "already past" in _refused(
        lambda: cp.set_pause(CH, "user", "x", until="2026-10-01", root=r, now=NOW))
    assert "no zone" in _refused(
        lambda: cp.set_pause(CH, "user", "x", until="2026-10-20T10:00", root=r, now=NOW))
    assert not (r / "publish" / cp.REGISTRY).exists()


def test_an_expired_pause_holds_nothing_but_is_said():
    r = _root()
    cp.set_pause(CH, "user", "нарушение", until="2026-10-08", root=r, now=NOW)
    assert cp.status(CH, r, "2026-10-07T20:59:59Z")["state"] == cp.PAUSED
    st = cp.status(CH, r, "2026-10-07T21:00:00Z")          # 2026-10-08 00:00 МСК
    assert st["state"] == cp.EXPIRED and "ИСТЕКЛА" in st["line"] and "clear" in st["line"]
    reason, notice = cp.gate(CH, r, "2026-10-09T00:00:00Z")
    assert reason is None and "ИСТЕКЛА" in notice
    code, out = _cli("show", "--root", str(r), "--now", "2026-10-09T00:00:00Z")
    assert code == 0 and "ИСТЕКЛА" in out, out


def test_an_unreadable_registry_pauses_every_channel():
    r = _root()
    (r / "publish" / cp.REGISTRY).write_text("{not json", encoding="utf-8")
    for ch in (CH, OTHER):
        reason, _ = cp.gate(ch, r, NOW)
        assert reason and "нечитаем" in reason, reason
    code, out = _cli("show", "--root", str(r))
    assert code == cp.EXIT_ERROR and "does not parse" in out, out
    assert "does not parse" in _refused(lambda: cp.set_pause(CH, "user", "x", root=r, now=NOW))


# ------------------------------------------------------------------ the queue
def test_the_queue_places_nothing_on_a_paused_channel_and_the_other_one_goes_on():
    r = _root()
    assert pq.plan_slot(CH, "B1", "v", r, NOW)["day"] == "2026-10-07"
    cp.set_pause(CH, "user", "нарушение от студии X", root=r, now=NOW)
    why = _refused(lambda: pq.plan_slot(CH, "B1", "v", r, NOW), pq.Paused)
    assert "paused" in why and "нарушение от студии X" in why, why
    code, line = pq.tomorrow(CH, r, NOW)
    assert code == pq.EXIT_PAUSED == 3 and "PAUSED" in line and "нарушение" in line, line
    out = io.StringIO()
    assert pq.main(["tomorrow", "--channel", CH, "--root", str(r), "--now", NOW], out=out) == 3
    out = io.StringIO()
    pq.main(["show", "--channel", CH, "--root", str(r), "--now", NOW], out=out)
    assert "PAUSED" in out.getvalue(), out.getvalue()
    # the second channel is not touched
    plan = pq.plan_slot(OTHER, "B1", "v", r, NOW)
    assert plan["day"] == "2026-10-07" and not any("PAUSE" in w for w in plan["warnings"])
    assert pq.tomorrow(OTHER, r, NOW)[0] == pq.EXIT_EMPTY
    # cleared: the slot is back
    cp.clear_pause(CH, "user", root=r, now=NOW)
    assert pq.plan_slot(CH, "B1", "v", r, NOW)["day"] == "2026-10-07"


def test_an_expired_pause_places_with_a_warning():
    r = _root()
    cp.set_pause(CH, "user", "нарушение", until="2026-10-06T10:00:00+03:00", root=r,
                 now="2026-10-06T09:00:00+03:00")
    plan = pq.plan_slot(CH, "B1", "v", r, NOW)
    assert plan["day"] == "2026-10-07"
    assert any(w.startswith("PAUSE ") and "ИСТЕКЛА" in w for w in plan["warnings"]), plan
    code, line = pq.tomorrow(CH, r, NOW)
    assert code == pq.EXIT_EMPTY and "ИСТЕКЛА" in line, line


# ------------------------------------------------------------------ the upload / Studio gate
def test_the_upload_and_studio_gate_refuses_a_paused_channel():
    r = _root()
    assert upload_gate.check_channel_not_paused(CH, r, NOW) is None
    cp.set_pause(CH, "monitor", "2 активных нарушение", root=r, now=NOW)
    why = _refused(lambda: upload_gate.check_channel_not_paused(CH, r, NOW), upload_gate.GateError)
    assert "paused" in why and "Studio" in why and "2 активных нарушение" in why, why
    assert upload_gate.check_channel_not_paused(OTHER, r, NOW) is None
    assert "no channel" in _refused(lambda: upload_gate.check_channel_not_paused("", r, NOW),
                                    upload_gate.GateError)
    (r / "publish" / cp.REGISTRY).write_text("[]", encoding="utf-8")
    _refused(lambda: upload_gate.check_channel_not_paused(OTHER, r, NOW), upload_gate.GateError)


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

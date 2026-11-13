#!/usr/bin/env python3
"""CF-0018: the Studio path - `agents/publisher/studio_fields.py` prepares the
fields of a ready card, checks what Studio shows after saving, writes the
journal row with the video id and counts the videos in a row with no hand
edit (the 2.0 exit).

Every root is a fixture in a temp dir; the committed publish/ is never read.

What is pinned:

* prepare refuses a card that is not ready (no marker, title edited after the
  build), a video with no acceptance or a rejected one, a standing hold, a
  paused channel, a video already in the journal, a slot that is missing or
  past;
* the JSON of the fields: title, description, tags (list + comma input +
  length), visibility "Запланировать", the slot in the channel's zone with
  the picker's text, the file name, the form answers from `## Настройки` - and
  null + `ask_user` for a question the settings do not answer;
* verify: `ok` through the changes Studio makes (CRLF, NBSP, zero width,
  trailing spaces, doubled blank lines, tags as one string, the picker's
  Russian date, the same moment read in another zone); every field that
  differs is listed and the command exits 1;
* record: verifies again, writes one `studio` row with `user_edited: false`,
  a second run is `exists`; a mismatch or another video id writes nothing;
  the ledger's publication columns are filled once the slot has passed;
* edited / streak: a hand edit breaks the run, `--undo` restores it, a
  non-Studio row cannot be marked.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _p in (AGENT, ROOT / "shared" / "runlog", ROOT / "shared", ROOT / "rotation"):
    sys.path.insert(0, str(_p))

import channel_pause as cp          # noqa: E402
import note_claims                  # noqa: E402
import studio_fields as sf          # noqa: E402
import upload_records               # noqa: E402
from ledger import Ledger, ledger_path   # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("studio-fields-test-")
_n = [0]
CH = "testreel"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
NOW = "2026-10-06T12:00:00+03:00"
DAY = "2026-10-08"
TITLE = "Delver Took Ten Years Because Iñárritu Waited for the Right Story #shorts"
ABOUT = "Alejandro G. Iñárritu says the idea came in 2015 — and it took ten more years."
SOURCE = "The fact in this video comes from: Wikipedia, Delver · https://en.wikipedia.org/wiki/Delver"
DESCRIPTION = f"{ABOUT}\n\n{SOURCE}\n\n#Delver #Inarritu #ExampleStudios"
TAGS = ["Delver", "Alejandro G. Iñárritu", "Example Studios", "movie news"]
SETTINGS = ("Не для детей. Язык: английский. ИИ/синтетический контент: нет. Прямой рекламы нет. "
            "Снять «Автоматическое объяснение понятий».")
VID, VID2 = "AbCdEfGhIj0", "ZyXwVuTsRq9"


def card_text(slug="v", batch="B1", title=TITLE, description=DESCRIPTION, tags=TAGS,
              publish=f"**{DAY} 01:00 МСК** — ближайший свободный слот канала",
              settings=SETTINGS, status="ready", marker=True):
    """A card as publish_card.py writes it: the claim block and the card
    marker both carry the fingerprint of exactly this title and description."""
    body = (f"# {slug} — карточка публикации\n\n## Название\n{title}\n\n## Описание\n{description}\n")
    fp = note_claims.fingerprint(body)
    claims = json.dumps({"rule": "CF-0555", "fingerprint": fp, "checked_at": "2026-10-06T09:00:00Z",
                         "batch": batch, "script_id": f"s-{slug}", "claims": 2, "struck": []},
                        ensure_ascii=False)
    mark = json.dumps({"rule": "CF-0017", "status": status, "channel": CH, "slug": slug,
                       "batch": f"pipeline/{CH}/{batch}", "script_id": f"s-{slug}",
                       "topic_id": f"t-{slug}", "problems": [], "fingerprint": fp},
                      ensure_ascii=False, sort_keys=True)
    return (body + f"\n## Утверждения\n<!-- note_claims {claims} -->\nПроверено машиной.\n"
            f"\n## Теги\n{', '.join(tags)}\n\n## Публикация\n{publish}\n\n## Настройки\n- {settings}\n"
            f"\n## Карточка\nСтатус: **готова**\n" + (f"<!-- publish_card {mark} -->\n" if marker else ""))


class World:
    def __init__(self):
        _n[0] += 1
        self.r = TMP / f"w{_n[0]}"
        self.pub = self.r / "publish"
        self.pub.mkdir(parents=True)
        (self.r / "channels").mkdir()
        (self.r / "channels" / f"{CH}.json").write_text(json.dumps(
            {"channel_id": CH, "publisher": {"slot": SLOT}}), encoding="utf-8")
        self.acc, self.holds, self.journal = [], [], []
        self.flush()

    def flush(self, journal=True):
        """Write the fixture files; `journal=False` leaves the journal to the
        code under test (it may hold rows `record` wrote)."""
        (self.pub / "acceptance-log.json").write_text(json.dumps({"acceptances": self.acc}),
                                                      encoding="utf-8")
        (self.pub / "publication-holds.json").write_text(json.dumps({"holds": self.holds}),
                                                         encoding="utf-8")
        if journal:
            (self.pub / "uploads.json").write_text(json.dumps({"uploads": self.journal}),
                                                   encoding="utf-8")

    def card(self, slug="v", batch="B1", day=DAY, verdict="accepted", **kw):
        d = self.pub / CH / day
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{slug}.mp4").write_bytes(b"\0")
        if "publish" not in kw and day != DAY:
            kw["publish"] = f"**{day} 01:00 МСК**"
        (d / f"{slug}.md").write_text(card_text(slug, batch, **kw), encoding="utf-8")
        if verdict:
            self.acc.append({"entry_id": f"{CH}/{batch}/{slug}", "channel": CH, "batch_id": batch,
                             "slug": slug, "topic_id": f"t-{slug}", "verdict": verdict,
                             "answered_at": "2026-10-06T08:00:00Z",
                             "publish_path": f"publish/{CH}/{day}/{slug}.mp4"})
            self.flush(journal=False)
        return d / f"{slug}.md"

    def read(self, **over):
        r = {"title": TITLE, "description": DESCRIPTION, "tags": list(TAGS),
             "visibility": "Запланировано",
             "schedule": {"date_text": "8 окт. 2026 г.", "time": "01:00",
                          "zone_text": "(GMT+03:00) Москва"}}
        r.update(over)
        return r

    def write_read(self, read):
        p = self.r / f"read-{_n[0]}-{len(list(self.r.glob('read-*')))}.json"
        p.write_text(json.dumps(read, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def rows(self):
        return upload_records.uploads(self.pub / "uploads.json")


def _cli(*argv):
    out = io.StringIO()
    code = sf.main(list(argv), out=out)
    return code, out.getvalue()


def _refused(fn, kind=sf.FieldsError):
    try:
        fn()
    except kind as e:
        return str(e)
    raise AssertionError("not refused")


# ------------------------------------------------------------------ prepare
def test_prepare_gives_the_fields_of_a_ready_card():
    w = World()
    note = w.card()
    f = sf.prepare(note, w.r, now=NOW)
    assert f["title"] == TITLE and f["description"] == DESCRIPTION, f
    assert f["tags"] == TAGS and f["tags_input"] == ", ".join(TAGS)
    assert f["tags_length"] <= f["tags_max"] == 500
    assert f["visibility"] == "scheduled" and f["visibility_studio"] == "Запланировать"
    s = f["schedule"]
    assert s["zone"] == "Europe/Moscow" and s["zone_offset"] == "GMT+03:00", s
    assert s["zone_label"] == "(GMT+03:00) Москва" and s["date_picker_text"] == "8 окт. 2026 г."
    assert s["date"] == DAY and s["time"] == "01:00" and s["publish_at_utc"] == "2026-10-07T22:00:00Z"
    assert s["msk"] == f"{DAY} 01:00 МСК"
    assert f["file_name"] == "v.mp4" and f["studio_draft_title"] == "v"
    assert f["video_file"] == f"publish/{CH}/{DAY}/v.mp4" and f["note"] == f"publish/{CH}/{DAY}/v.md"
    assert f["entry_id"] == f"{CH}/B1/v" and f["channel"] == CH
    form = f["form"]
    assert form["made_for_kids"]["value"] is False and "не для детей" in form["made_for_kids"]["studio"]
    assert form["altered_content"]["value"] is False and form["paid_promotion"]["value"] is False
    assert form["auto_concepts"]["value"] is False and form["language"]["value"] == "английский"
    assert f["ask_user"] == [] and f["notices"] == []
    # the CLI by slug prints the same JSON
    code, out = _cli("prepare", "v", "--channel", CH, "--root", str(w.r), "--now", NOW)
    assert code == 0 and json.loads(out)["schedule"]["msk"] == s["msk"], out


def test_a_question_the_settings_do_not_answer_is_null_and_asked():
    w = World()
    note = w.card(settings="Язык: английский.")
    f = sf.prepare(note, w.r, now=NOW)
    assert f["form"]["made_for_kids"]["value"] is None and "спросить" in f["form"]["made_for_kids"]["ask_user"]
    assert set(f["ask_user"]) == {"made_for_kids", "altered_content", "paid_promotion", "auto_concepts"}
    assert f["form"]["language"]["value"] == "английский"


def test_prepare_refuses_a_card_that_is_not_ready():
    w = World()
    note = w.card(marker=False)
    assert "not ready" in _refused(lambda: sf.prepare(note, w.r, now=NOW))
    w2 = World()
    note = w2.card(status="not_ready")
    assert "not ready" in _refused(lambda: sf.prepare(note, w2.r, now=NOW))
    # a hand edit of the title after the build makes the card stale
    w3 = World()
    note = w3.card()
    note.write_text(note.read_text(encoding="utf-8").replace("Ten Years", "A Decade"), encoding="utf-8")
    why = _refused(lambda: sf.prepare(note, w3.r, now=NOW))
    assert "not ready" in why and "changed" in why, why
    code, out = _cli("prepare", str(note), "--root", str(w3.r), "--now", NOW)
    assert code == 2 and out.startswith("refused:"), out


def test_prepare_refuses_without_an_acceptance_or_with_a_hold():
    w = World()
    note = w.card(verdict=None)
    assert "no acceptance" in _refused(lambda: sf.prepare(note, w.r, now=NOW))
    w2 = World()
    note = w2.card(verdict="rejected")
    assert "not accepted" in _refused(lambda: sf.prepare(note, w2.r, now=NOW))
    w3 = World()
    note = w3.card()
    w3.holds.append({"hold_id": f"{CH}/B1/t-v", "channel": CH, "batch_id": "B1", "topic_id": "t-v",
                     "verdict": "review", "reason_code": "compliance_review_hold"})
    w3.flush()
    assert "hold" in _refused(lambda: sf.prepare(note, w3.r, now=NOW))


def test_prepare_refuses_a_paused_channel():
    w = World()
    note = w.card()
    cp.set_pause(CH, "user", "разбор нарушение", root=w.r, now=NOW)
    why = _refused(lambda: sf.prepare(note, w.r, now=NOW))
    assert "paused" in why and "Studio" in why, why
    cp.clear_pause(CH, "user", root=w.r, now=NOW)
    assert sf.prepare(note, w.r, now=NOW)["slug"] == "v"


def test_prepare_refuses_a_video_already_journalled_and_a_missing_or_past_slot():
    w = World()
    note = w.card()
    sf.record(note, VID, w.read(), w.r, now=NOW)
    why = _refused(lambda: sf.prepare(note, w.r, now=NOW))
    assert VID in why and "--replaces" in why, why
    assert sf.prepare(note, w.r, now=NOW, replaces=VID)["slug"] == "v"
    w2 = World()
    note = w2.card(publish="Слот не назначен.")
    assert "no slot" in _refused(lambda: sf.prepare(note, w2.r, now=NOW))
    w3 = World()
    note = w3.card()
    assert "past" in _refused(lambda: sf.prepare(note, w3.r, now="2026-10-08T02:00:00+03:00"))
    w4 = World()
    note = w4.card(day="2026-10-09", publish=f"**{DAY} 01:00 МСК**")
    assert "day folder" in _refused(lambda: sf.prepare(note, w4.r, now=NOW))


# ------------------------------------------------------------------ verify
def test_verify_is_ok_through_what_studio_changes():
    w = World()
    note = w.card()
    studio_desc = ("﻿" + ABOUT.replace(" — ", " — ") + "  \r\n\r\n\r\n"
                   + SOURCE + "​\r\n\n#Delver #Inarritu #ExampleStudios\n")
    read = w.read(title="  " + TITLE.replace(" ", "  ", 1) + " ", description=studio_desc,
                  tags=", ".join(TAGS) + ", ", visibility="Отложенная публикация")
    _f, mism = sf.verify(note, read, w.r, now=NOW)
    assert mism == [], mism
    # the same moment read in New York's zone, and ISO, agree
    ny = w.read(schedule={"date_text": "7 окт. 2026 г.", "time": "18:00",
                          "zone_text": "(GMT-04:00) Нью-Йорк"})
    assert sf.verify(note, ny, w.r, now=NOW)[1] == []
    iso = w.read(schedule=None, publish_at="2026-10-07T22:00:00Z")
    assert sf.verify(note, iso, w.r, now=NOW)[1] == []
    code, out = _cli("verify", str(note), "--read", w.write_read(read), "--root", str(w.r),
                     "--now", NOW)
    assert code == 0 and out.strip() == "ok", out


def test_verify_lists_every_field_that_differs():
    w = World()
    note = w.card()
    read = w.read(title=TITLE.replace("Ten", "10"), description=DESCRIPTION.replace("2015", "2016"),
                  tags=TAGS[:-1] + ["film news"], visibility="Открытый доступ",
                  schedule={"date_text": "8 окт. 2026 г.", "time": "02:00",
                            "zone_text": "(GMT+03:00) Москва"},
                  made_for_kids=True)
    _f, mism = sf.verify(note, read, w.r, now=NOW)
    fields = [m["field"] for m in mism]
    assert fields == ["title", "description", "tags", "visibility", "publish_at", "made_for_kids"], mism
    tags = mism[2]["expected"]
    assert tags["missing"] == ["movie news"] and tags["extra"] == ["film news"]
    assert mism[4]["read"] == f"{DAY} 02:00 МСК"
    # a time with no zone is not a moment
    nozone = w.read(schedule={"date_text": "8 окт. 2026 г.", "time": "01:00"})
    m = sf.verify(note, nozone, w.r, now=NOW)[1]
    assert [x["field"] for x in m] == ["publish_at"] and "zone" in m[0]["read"], m
    code, out = _cli("verify", str(note), "--read", w.write_read(read), "--root", str(w.r),
                     "--now", NOW)
    assert code == 1 and out.count("MISMATCH") == 6 and "nothing written" in out, out


# ------------------------------------------------------------------ record
def test_record_writes_one_studio_row_and_is_idempotent():
    w = World()
    note = w.card()
    res = sf.record(note, VID, w.read(url=f"https://youtube.com/shorts/{VID}"), w.r, now=NOW)
    assert res["status"] == "added", res
    rows = w.rows()
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "studio" and r["user_edited"] is False and r["video_id"] == VID
    assert r["publish_at"] == f"{DAY}T01:00:00+03:00" and r["publish_tz"] == "Europe/Moscow"
    assert r["publish_day"] == DAY and r["entry_id"] == f"{CH}/B1/v"
    assert r["note"] == f"publish/{CH}/{DAY}/v.md" and upload_records.check_row(r) == []
    again = sf.record(note, VID, w.read(), w.r, now="2026-10-06T13:00:00+03:00")
    assert again["status"] == "exists" and len(w.rows()) == 1
    code, out = _cli("record", str(note), "--video-id", VID, "--read", w.write_read(w.read()),
                     "--root", str(w.r), "--now", NOW)
    assert code == 0 and out.startswith("exists:") and "streak: 1/5" in out, out
    # another id for the same accepted video needs --replaces
    assert "--replaces" in _refused(lambda: sf.record(note, VID2, w.read(), w.r, now=NOW))


def test_record_writes_nothing_on_a_mismatch_or_another_video_id():
    w = World()
    note = w.card()
    bad = w.read(title="Something else")
    assert "nothing written" in _refused(lambda: sf.record(note, VID, bad, w.r, now=NOW))
    code, out = _cli("record", str(note), "--video-id", VID, "--read", w.write_read(bad),
                     "--root", str(w.r), "--now", NOW)
    assert code == 1 and "MISMATCH title" in out, out
    other = w.read(url=f"https://studio.youtube.com/video/{VID2}/edit")
    assert VID2 in _refused(lambda: sf.record(note, VID, other, w.r, now=NOW))
    assert "not a YouTube video id" in _refused(lambda: sf.record(note, "short", w.read(), w.r, now=NOW),
                                                upload_records.JournalError)
    code, _out = _cli("record", str(note), "--video-id", VID, "--read", w.write_read(bad),
                      "--root", str(w.r), "--now", NOW, "--dry-run")
    assert code == 1 and w.rows() == []


def test_record_fills_the_ledger_once_the_slot_has_passed():
    w = World()
    d = w.r / "pipeline" / CH / "B1"
    d.mkdir(parents=True)
    (d / "05-video-editor.json").write_text(json.dumps({"batch_id": "B1", "channel": CH, "videos": [
        {"script_id": "s-v", "output_path": str(d / "videos" / "v.mp4"),
         "pattern_delivered": "explainer", "rhythm_delivered": "even"}]}), encoding="utf-8")
    led = Ledger(ledger_path(CH, w.r / "rotation" / "ledger"))
    led.append(channel=CH, batch_id="B1", script_id="s-v", pattern_id="explainer",
               rhythm_id="even", assigned_by="rotation")
    note = w.card()
    early = sf.record(note, VID, w.read(), w.r, now=NOW, dry_run=True)
    assert early["status"] == "would-add" and w.rows() == [] and early["ledger"] is None
    # recorded late (after the slot): the journal row and the ledger columns at once
    res = sf.record(note, VID, w.read(), w.r, now="2026-10-08T09:00:00+03:00")
    assert res["status"] == "added" and res["ledger"]["filled"] == ["B1/v -> seq 1"], res["ledger"]
    row = {r["script_id"]: r for r in led.rows()}["s-v"]
    assert row["video_id"] == VID and row["feed_position"] == "1"
    assert row["published_at"].startswith("2026-10-07T22:00:00")
    again = sf.record(note, VID, w.read(), w.r, now="2026-10-08T10:00:00+03:00")
    assert again["status"] == "exists" and again["ledger"]["already"] == ["B1/v"]


def test_record_does_not_warn_about_a_shifted_feed_rank():
    """CF-0866: an early video written into the journal after the ranks were
    filled re-derives them; `record` prints one ledger line, no WARNING."""
    w = World()
    d = w.r / "pipeline" / CH / "B1"
    d.mkdir(parents=True)
    (d / "05-video-editor.json").write_text(json.dumps({"batch_id": "B1", "channel": CH, "videos": [
        {"script_id": "s-v", "output_path": str(d / "videos" / "v.mp4"),
         "pattern_delivered": "explainer", "rhythm_delivered": "even"}]}), encoding="utf-8")
    led = Ledger(ledger_path(CH, w.r / "rotation" / "ledger"))
    led.append(channel=CH, batch_id="B1", script_id="s-v", pattern_id="explainer",
               rhythm_id="even", assigned_by="rotation")
    note = w.card()
    sf.record(note, VID, w.read(), w.r, now="2026-10-08T09:00:00+03:00")
    assert {r["script_id"]: r for r in led.rows()}["s-v"]["feed_position"] == "1"
    early = w.card(slug="early", batch="B0", day="2026-10-05")
    read = w.read(schedule={"date_text": "5 окт. 2026 г.", "time": "01:00",
                            "zone_text": "(GMT+03:00) Москва"})
    code, out = _cli("record", str(early), "--video-id", "E0000000000", "--read",
                     w.write_read(read), "--root", str(w.r), "--now", "2026-10-08T10:00:00+03:00")
    assert code == 0, out
    assert "WARNING" not in out and "feed rank shifted for 1 video(s)" in out, out
    assert {r["script_id"]: r for r in led.rows()}["s-v"]["feed_position"] == "2"


# ------------------------------------------------------------------ the 2.0 exit
def test_edited_breaks_the_streak_and_undo_restores_it():
    w = World()
    for i, slug in enumerate(("a", "b", "c")):
        day = f"2026-10-{8 + i:02d}"
        note = w.card(slug=slug, batch=f"B{slug}", day=day)
        read = w.read(schedule={"date_text": f"{8 + i} окт. 2026 г.", "time": "01:00",
                                "zone_text": "(GMT+03:00) Москва"})
        sf.record(note, f"{slug.upper()}0000000000", read, w.r,
                  now=f"2026-10-06T1{2 + i}:00:00+03:00")
    s = sf.streak(w.rows())
    assert s["streak"] == 3 and s["studio_videos"] == 3 and not s["done"] and s["run"] == ["a", "b", "c"]
    code, out = _cli("edited", "--slug", "b", "--note", "поправил тег", "--root", str(w.r))
    assert code == 0 and "user_edited=True" in out and "streak 1/5" in out, out
    s = sf.streak(w.rows(), CH)
    assert s["streak"] == 1 and s["last_edited"]["slug"] == "b" and s["last_edited"]["note"] == "поправил тег"
    code, out = _cli("streak", "--root", str(w.r))
    assert code == 0 and "streak: 1/5" in out and "last edit: b" in out, out
    code, out = _cli("edited", "--video-id", "B0000000000", "--undo", "--root", str(w.r))
    assert code == 0 and sf.streak(w.rows())["streak"] == 3
    # five in a row reach the exit; a backfill row is not counted and cannot be marked
    rows = [dict(r, recorded_at=f"2026-10-0{i}T00:00:00Z") for i, r in enumerate(
        [{"source": "studio", "slug": f"s{i}"} for i in range(5)], 1)]
    rows.append({"source": "backfill", "slug": "old", "user_edited": True})
    assert sf.streak(rows)["done"] is True
    w.journal = [{"channel": CH, "entry_id": f"{CH}/B0/old", "slug": "old", "video_id": VID2,
                  "source": "backfill", "recorded_at": "2026-10-01T00:00:00Z"}]
    w.flush()
    code, out = _cli("edited", "--video-id", VID2, "--root", str(w.r))
    assert code == 2 and "Studio path" in out, out


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

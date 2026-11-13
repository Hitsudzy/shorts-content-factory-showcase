#!/usr/bin/env python3
"""CF-0586: the upload journal `publish/uploads.json` - its one writer
(`agents/publisher/upload_records.py`), the Studio row CF-0018 writes, and the
backfill of the videos that went up before it (`backfill_uploads.py`).

Every file is a fixture in a temp dir; the committed publish/ is never read
(`upload_records.py check` checks the committed journal).

What is pinned:

* the format: a row without an acceptance, with a short id, a slot without a
  zone, a source outside studio/api/backfill, a publish_day that is not the MSK
  day of the slot - each refused;
* idempotence: the same row twice is one row; the same id for another video is
  DuplicateVideoId, so is an id the journal holds as a deleted copy; a second
  live video of one acceptance needs --replaces, which marks the old row;
* the Studio row: entry or slug, the 11-character id, the slot with its zone,
  the day folder must be the slot's MSK day, a rejected video is not written;
  the CLI says `added` / `exists` / `refused`;
* the backfill on a fixture of README prose + day notes + acceptance log: ids
  from the note before the README, struck ids and earlier note ids are
  superseded, the slot from the note / the README's last `на DD.MM HH:MM МСК`,
  a re-upload's slot left empty with the reason; dry run writes nothing,
  --write writes, a second run adds nothing;
* unresolved: no id, no acceptance, two live ids, note vs README, slot vs
  folder, an id named for two videos, a journal row that says otherwise.
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

import backfill_uploads as bf       # noqa: E402
import upload_records as ur         # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("upload-journal-test-")
_n = [0]
CH = "example-film"
NOW = "2026-10-06T12:00:00Z"


def _dir():
    _n[0] += 1
    d = TMP / f"r{_n[0]}"
    (d / "publish").mkdir(parents=True)
    return d


def _acc(batch, slug, verdict="accepted", publish_path=None, channel=CH):
    return {"entry_id": f"{channel}/{batch}/{slug}", "slug": slug, "channel": channel,
            "batch_id": batch, "topic_id": f"topic-{slug}", "verdict": verdict,
            "publish_path": publish_path}


def _log(root, rows):
    p = root / "publish" / "acceptance-log.json"
    p.write_text(json.dumps({"note": "t", "task": "CF-0328", "acceptances": rows},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _row(**kw):
    base = ur.make_row(_acc("2026-10-01T1313Z", "rennick"), CH, "JWyd0AwT47E", "studio",
                       publish_at="2026-10-08T01:00:00+03:00", publish_tz="Europe/Moscow",
                       publish_day="2026-10-08", note="publish/example-film/2026-10-08/rennick.md",
                       recorded_at=NOW)
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# format
# --------------------------------------------------------------------------

def test_a_well_formed_row_passes_and_each_defect_is_named():
    assert ur.check_row(_row()) == []
    for kw, word in ((dict(entry_id=None), "entry_id"), (dict(video_id="JWyd0AwT47"), "video_id"),
                     (dict(source="manual"), "source"), (dict(channel="2026-10-08"), "channel"),
                     (dict(publish_at="2026-10-08T01:00:00"), "offset"),
                     (dict(publish_day="2026-10-07"), "MSK day"),
                     (dict(publish_tz=None), "publish_tz"), (dict(recorded_at=None), "recorded_at"),
                     (dict(slug="delver"), "slug")):
        problems = ur.check_row(_row(**kw))
        assert problems and any(word in p for p in problems), (kw, problems)
    assert ur.check_row(_row(publish_at=None, publish_tz=None)) == [], "an unknown slot is allowed"


def test_the_slot_needs_its_zone_and_is_written_in_the_studio_zone():
    assert ur.parse_slot("2026-10-08T01:00+03:00") == \
        ("2026-10-08T01:00:00+03:00", "Europe/Moscow", "2026-10-08")
    assert ur.parse_slot("2026-10-07T22:00:00Z")[0] == "2026-10-08T01:00:00+03:00"
    assert ur.parse_slot("2026-10-08 01:00 МСК")[0] == "2026-10-08T01:00:00+03:00"
    assert ur.parse_slot("2026-10-07 18:00 ET")[2] == "2026-10-08"
    for bad in ("2026-10-08T01:00", "2026-10-08 01:00", "tomorrow"):
        try:
            ur.parse_slot(bad)
        except ur.JournalError:
            continue
        raise AssertionError(f"{bad!r} must be refused")


def test_a_new_journal_carries_its_note_and_format():
    j = _dir() / "publish" / "uploads.json"
    assert ur.record(_row(), j) == "added"
    doc = json.loads(j.read_text())
    assert doc["format"] == ur.FORMAT and "studio" in doc["note"] and len(doc["uploads"]) == 1
    assert ur.check_journal(j) == []


# --------------------------------------------------------------------------
# idempotence and duplicates
# --------------------------------------------------------------------------

def test_the_same_row_twice_is_one_row():
    j = _dir() / "publish" / "uploads.json"
    assert ur.record(_row(), j) == "added"
    assert ur.record(_row(recorded_at="2026-10-07T00:00:00Z", source="backfill"), j) == "exists"
    assert len(ur.uploads(j)) == 1


def test_a_video_id_twice_is_an_error():
    j = _dir() / "publish" / "uploads.json"
    ur.record(_row(), j)
    other = _row(entry_id=f"{CH}/2026-10-01T1313Z/delver", slug="delver")
    try:
        ur.record(other, j)
    except ur.DuplicateVideoId as e:
        assert "JWyd0AwT47E" in str(e) and "entry_id" in str(e)
    else:
        raise AssertionError("a second video with the same id must be refused")
    try:
        ur.record(_row(publish_at="2026-10-08T02:00:00+03:00"), j)
    except ur.DuplicateVideoId:
        pass
    else:
        raise AssertionError("the same id with another slot is not the same row")
    assert len(ur.uploads(j)) == 1


def test_a_reupload_needs_replaces_and_marks_the_old_row():
    j = _dir() / "publish" / "uploads.json"
    ur.record(_row(), j)
    new = _row(video_id="NEWNEWNEW01", url="https://youtube.com/shorts/NEWNEWNEW01")
    try:
        ur.record(new, j)
    except ur.JournalError as e:
        assert "--replaces" in str(e)
    else:
        raise AssertionError("a second live video of one acceptance must be refused")
    assert ur.record(new, j, replaces="JWyd0AwT47E", now=NOW) == "added"
    old, cur = ur.uploads(j)
    assert old["removed_at"] == NOW and old["replaced_by"] == "NEWNEWNEW01"
    assert cur["superseded_video_ids"] == ["JWyd0AwT47E"]
    again = _row(entry_id=f"{CH}/2026-10-01T1313Z/delver", slug="delver")
    try:
        ur.record(again, j)
    except ur.DuplicateVideoId:
        pass
    else:
        raise AssertionError("the deleted copy's id must not be reused")
    assert ur.check_journal(j) == []


# --------------------------------------------------------------------------
# the Studio row (CF-0018)
# --------------------------------------------------------------------------

def _studio_root():
    root = _dir()
    log = _log(root, [
        _acc("2026-10-01T1313Z", "rennick", publish_path="publish/example-film/2026-10-08/rennick.mp4"),
        _acc("2026-10-01T1313Z", "delver", verdict="rejected"),
        _acc("2026-10-05T0701Z", "harbourlights"),
        _acc("2026-10-05T1244Z", "harbourlights", channel="rebuilds",
             publish_path="publish/example-film/2026-10-07/harbourlights.mp4"),
    ])
    return root, log, root / "publish" / "uploads.json"


def _cli(*argv):
    out = io.StringIO()
    rc = ur.main(list(argv), out=out)
    return rc, out.getvalue()


def test_the_studio_row_is_written_once_from_the_acceptance():
    root, log, j = _studio_root()
    args = ["--journal", str(j), "studio", "--channel", CH, "--entry",
            f"{CH}/2026-10-01T1313Z/rennick", "--video-id", "JWyd0AwT47E",
            "--slot", "2026-10-08 01:00 МСК", "--log", str(log)]
    rc, out = _cli(*args[:-2], "--log", str(log), "--dry-run")
    assert rc == 0 and out.startswith("would-add") and not j.exists(), out
    rc, out = _cli(*args)
    assert rc == 0 and out.startswith("added"), out
    rc, out = _cli(*args)
    assert rc == 0 and out.startswith("exists"), out
    (row,) = ur.uploads(j)
    assert row["source"] == "studio" and row["publish_at"] == "2026-10-08T01:00:00+03:00"
    assert row["publish_tz"] == "Europe/Moscow" and row["topic_id"] == "topic-rennick"
    assert row["note"] == "publish/example-film/2026-10-08/rennick.md"
    rc, out = _cli("--journal", str(j), "check")
    assert rc == 0 and "1 rows, 0 problems" in out


def test_the_studio_row_refuses_what_it_cannot_vouch_for():
    root, log, j = _studio_root()
    common = ["--journal", str(j), "studio", "--channel", CH, "--log", str(log)]
    cases = [
        (["--entry", f"{CH}/2026-10-01T1313Z/rennick", "--video-id", "JWyd0AwT47",
          "--slot", "2026-10-08T01:00+03:00"], "not a YouTube video id"),
        (["--entry", f"{CH}/2026-10-01T1313Z/rennick", "--video-id", "JWyd0AwT47E",
          "--slot", "2026-10-08T01:00"], "no zone"),
        (["--entry", f"{CH}/2026-10-01T1313Z/rennick", "--video-id", "JWyd0AwT47E",
          "--slot", "2026-10-06T01:00+03:00"], "day folder 2026-10-08"),
        (["--entry", f"{CH}/2026-10-01T1313Z/delver", "--video-id", "wflcaodx5-0",
          "--slot", "2026-10-10T01:00+03:00"], "rejected"),
        (["--slug", "harbourlights", "--video-id", "ZgcR5Ex5_CQ",
          "--slot", "2026-10-07T01:00+03:00"], "more than one batch"),
        (["--video-id", "ZgcR5Ex5_CQ", "--slot", "2026-10-07T01:00+03:00"], "name the video"),
    ]
    for extra, word in cases:
        rc, out = _cli(*common, *extra)
        assert rc == 1 and "refused" in out and word in out, (extra, out)
    rc, out = _cli("--journal", str(j), "studio", "--channel", "othertube", "--log", str(log),
                   "--entry", f"{CH}/2026-10-01T1313Z/rennick", "--video-id", "JWyd0AwT47E",
                   "--slot", "2026-10-08T01:00+03:00")
    assert rc == 1 and "publishes on 'example-film'" in out, out
    rc, out = _cli(*common, "--entry", "rebuilds/2026-10-05T1244Z/harbourlights",
                   "--video-id", "ZgcR5Ex5_CQ", "--slot", "2026-10-07T01:00+03:00")
    assert rc == 0 and ur.uploads(j)[0]["channel"] == CH, out
    assert not [r for r in ur.uploads(j) if r["slug"] != "harbourlights"]


# --------------------------------------------------------------------------
# backfill
# --------------------------------------------------------------------------

README = """# Ролики для публикации

| ролик | батч | вердикт пользователя |
|---|---|---|
| `example-film/2026-09-22/outrider.mp4` | `example-film/2026-09-21T1541Z` | принят 2026-09-22 |
| `everyday-sorcery.mp4` | `example-film/2026-09-15T1034Z` | принят; **снят** |
| `Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-23/widows.mp4` | `rebuilds/2026-09-23T1053Z` | **опубликован 2026-09-23**, `youtube.com/shorts/qPb2tGoBbZc` |
| `Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-25/seeall.mp4` | `example-film/2026-09-23T1722Z` | отложенная публикация 2026-09-24 18:00 ET; ~~`youtube.com/shorts/YouJGDeGtY4`~~ → `youtube.com/shorts/X9QuS5WKFGA` |
| `Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-28/backrooms.mp4` | `rebuilds/2026-09-27T1757Z` (батч `example-film/2026-09-27T0929Z`) | **загружен и запланирован 2026-09-27** на 28.09 01:00 МСК (18:00 ET), `youtube.com/shorts/VV-UM01wb5c` |
| `example-film/2026-10-01/endgame.mp4` | `example-film/2026-09-29T0705Z` | слот 2026-10-01 01:00 МСК, `youtube.com/shorts/oo-f6Oiob3M` |
| `example-film/2026-10-03/primetime.mp4` | `example-film/2026-09-30T2210Z` | слот 2026-10-03 01:00 МСК — **запланирован в Studio** (youtube.com/shorts/mW6_ybR57lk) |
| `example-film/2026-10-08/rennick.mp4` | `example-film/2026-10-01T1313Z` | слот 2026-10-06 01:00 МСК, `youtube.com/shorts/JWyd0AwT47E`; дата выхода перенесена в Studio 2026-10-05 на 08.10 01:00 МСК |
| `example-film/2026-10-09/orphan.mp4` | `example-film/2026-10-09T0000Z` | слот 2026-10-09 01:00 МСК, `youtube.com/shorts/ORPHANORPH0` |
| `example-film/2026-10-11/twice.mp4` | `example-film/2026-10-05T0701Z` | `youtube.com/shorts/TWICETWICE1`, потом `youtube.com/shorts/TWICETWICE2` |
| `example-film/2026-10-12/clash.mp4` | `example-film/2026-10-05T0701Z` | слот 2026-10-12 01:00 МСК, `youtube.com/shorts/README00012` |
| `example-film/2026-10-13/dupe-a.mp4` | `example-film/2026-10-05T0701Z` | слот 2026-10-13 01:00 МСК, `youtube.com/shorts/DUPEDUPEDUP` |
| `example-film/2026-10-14/dupe-b.mp4` | `example-film/2026-10-05T0701Z` | слот 2026-10-14 01:00 МСК, `youtube.com/shorts/DUPEDUPEDUP` |
| `example-film/2026-10-15/badslot.mp4` | `example-film/2026-10-05T0701Z` | `youtube.com/shorts/BADSLOTBAD1` |
| `example-film/2026-10-16/rejected.mp4` | `example-film/2026-10-05T0701Z` | слот 2026-10-16 01:00 МСК, `youtube.com/shorts/REJECTEDREJ` |

| ролик | батч | что назвал пользователь |
|---|---|---|
| `dtf-st-louis` | `2026-09-15T1034Z` | зависший кадр |
"""

NOTES = {
    "2026-10-01/endgame": "## Публикация\n**2026-10-01 01:00 МСК** (30.09 22:00 UTC)\n\n"
                          "**Загружен** `youtube.com/shorts/oo-f6Oiob3M`.\n\n**Перезалит.** Копия "
                          "(`youtube.com/shorts/oo-f6Oiob3M`) удалена; новый адрес — "
                          "`youtube.com/shorts/bp4c5Oi9ntM`.\n",
    "2026-10-03/primetime": "## Публикация\n**2026-10-03 01:00 МСК** (02.10 22:00 UTC)\n",
    "2026-10-08/rennick": "## Публикация\n**2026-10-08 01:00 МСК** (07.10 22:00 UTC)\n\n"
                          "**Загружен** — `youtube.com/shorts/JWyd0AwT47E`, 06.10 01:00.\n",
    "2026-10-12/clash": "## Публикация\n**2026-10-12 01:00 МСК**\n\n`youtube.com/shorts/NOTE0000012`\n",
    "2026-10-15/badslot": "## Публикация\n**2026-10-16 01:00 МСК**\n",
    "2026-10-17/noteonly": "## Публикация\n**2026-10-17 01:00 МСК**\n\n`youtube.com/shorts/NOTEONLY017`\n",
}


def _backfill_root():
    root = _dir()
    pub = root / "publish"
    (pub / "README.md").write_text(README, encoding="utf-8")
    for rel, text in NOTES.items():
        p = pub / CH / f"{rel}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {p.stem}\n\n" + text, encoding="utf-8")
    arch = "Archive:shorts-content-factory-publish/example-film/2026-09.zip#"
    _log(root, [
        _acc("2026-09-21T1541Z", "outrider", publish_path="publish/example-film/2026-09-22/outrider.mp4"),
        _acc("2026-09-15T1034Z", "everyday-sorcery", verdict="rejected"),
        _acc("2026-09-23T1053Z", "widows", channel="rebuilds", publish_path=f"{arch}2026-09-23/widows.mp4"),
        _acc("2026-09-23T1722Z", "seeall", publish_path=f"{arch}2026-09-25/seeall.mp4"),
        _acc("2026-09-27T1757Z", "backrooms", channel="rebuilds"),
        _acc("2026-09-29T0705Z", "endgame", publish_path="publish/example-film/2026-10-01/endgame.mp4"),
        _acc("2026-09-30T2210Z", "primetime", publish_path="publish/example-film/2026-10-03/primetime.mp4"),
        _acc("2026-10-01T1313Z", "rennick", publish_path="publish/example-film/2026-10-08/rennick.mp4"),
        _acc("2026-10-05T0701Z", "twice"), _acc("2026-10-05T0701Z", "clash"),
        _acc("2026-10-05T0701Z", "dupe-a"), _acc("2026-10-05T0701Z", "dupe-b"),
        _acc("2026-10-05T0701Z", "badslot"), _acc("2026-10-05T0701Z", "rejected", verdict="rejected"),
        _acc("2026-10-05T0701Z", "noteonly", publish_path="publish/example-film/2026-10-17/noteonly.mp4"),
    ])
    return root


def _by_slug(rows):
    return {r["slug"]: r for r in rows}


def test_backfill_reads_the_prose_the_notes_and_the_acceptance_log():
    root = _backfill_root()
    res = bf.plan(root)
    add = _by_slug(res["add"])
    assert set(add) == {"widows", "seeall", "backrooms", "endgame", "primetime", "rennick",
                        "noteonly"}, sorted(add)
    assert all(r["source"] == "backfill" and ur.check_row(r) == [] for r in res["add"])
    w = add["widows"]
    assert w["video_id"] == "qPb2tGoBbZc" and w["publish_at"] is None and w["channel"] == CH
    assert w["entry_id"] == "rebuilds/2026-09-23T1053Z/widows" and "опубликован сразу" in w["gaps"][0]
    assert w["note"].endswith("2026-09.zip#2026-09-23/widows.md"), w["note"]
    s = add["seeall"]
    assert s["video_id"] == "X9QuS5WKFGA" and s["superseded_video_ids"] == ["YouJGDeGtY4"]
    assert s["publish_at"] is None and "перезалит" in s["gaps"][0], "a re-upload's slot is not guessed"
    b = add["backrooms"]
    assert b["entry_id"] == "rebuilds/2026-09-27T1757Z/backrooms", "linked by the README batch cell"
    assert b["publish_at"] == "2026-09-28T01:00:00+03:00" and b["publish_day"] == "2026-09-28"
    e = add["endgame"]
    assert e["video_id"] == "bp4c5Oi9ntM" and e["superseded_video_ids"] == ["oo-f6Oiob3M"]
    assert any("удалённую копию" in g for g in e["gaps"])
    assert add["primetime"]["video_id"] == "mW6_ybR57lk" and "gaps" not in add["primetime"]
    r = add["rennick"]
    assert r["publish_at"] == "2026-10-08T01:00:00+03:00", "the note's slot, not the stale prose"
    assert r["note"] == "publish/example-film/2026-10-08/rennick.md"
    assert add["noteonly"]["video_id"] == "NOTEONLY017"


def test_backfill_lists_what_it_cannot_resolve_and_writes_none_of_it():
    root = _backfill_root()
    res = bf.plan(root)
    why = {u["video"].split("/")[-1]: u["why"] for u in res["unresolved"]}
    assert "video_id нет" in why["outrider"], why
    assert "нет строки приёмки" in why["orphan"], why
    assert "несколько живых id" in why["twice"], why
    assert "id расходятся" in why["clash"], why
    assert "назван у нескольких роликов" in why["dupe-a"] and "dupe-b" in why, why
    assert "в папке дня" in why["badslot"], why
    assert "не принят" in why["rejected"], why
    assert "everyday-sorcery" not in str(res), "a withdrawn video with no id is not a video on YouTube"
    assert len(res["unresolved"]) == 8, res["unresolved"]


def test_backfill_is_a_dry_run_until_write_and_a_rerun_adds_nothing():
    root = _backfill_root()
    j = root / "publish" / "uploads.json"
    out = io.StringIO()
    bf.main(["--root", str(root)], out=out)
    assert not j.exists() and "сухой прогон" in out.getvalue() and "к записи: 7" in out.getvalue()
    out = io.StringIO()
    bf.main(["--root", str(root), "--write"], out=out)
    assert len(ur.uploads(j)) == 7 and ur.check_journal(j) == []
    before = j.read_text()
    out = io.StringIO()
    bf.main(["--root", str(root), "--write"], out=out)
    assert j.read_text() == before and "к записи: 0" in out.getvalue() \
        and "уже в журнале: 7" in out.getvalue(), out.getvalue()


def test_backfill_adds_only_what_is_new_and_reports_a_journal_that_disagrees():
    root = _backfill_root()
    j = root / "publish" / "uploads.json"
    bf.main(["--root", str(root), "--write"], out=io.StringIO())
    readme = root / "publish" / "README.md"
    readme.write_text(readme.read_text().replace(
        "| `everyday-sorcery.mp4`",
        "| `example-film/2026-10-20/fresh.mp4` | `example-film/2026-10-05T0701Z` | слот 2026-10-20 "
        "01:00 МСК, `youtube.com/shorts/FRESHFRESH1` |\n| `everyday-sorcery.mp4`"), encoding="utf-8")
    log = json.loads((root / "publish" / "acceptance-log.json").read_text())
    log["acceptances"].append(_acc("2026-10-05T0701Z", "fresh"))
    (root / "publish" / "acceptance-log.json").write_text(json.dumps(log, ensure_ascii=False))
    note = root / "publish" / CH / "2026-10-03" / "primetime.md"
    note.write_text(note.read_text().replace("01:00 МСК", "02:00 МСК").replace("22:00 UTC", "23:00 UTC"))
    res = bf.plan(root)
    assert [r["slug"] for r in res["add"]] == ["fresh"], res["add"]
    assert len(res["exists"]) == 6
    assert any("primetime" in u["video"] and "расходится с журналом" in u["why"]
               for u in res["unresolved"]), res["unresolved"]


def test_the_api_row_has_the_journal_shape():
    from types import SimpleNamespace
    acc = dict(_acc("2026-09-29T0705Z", "harbourlights"), profile={"script_id": "s1", "pattern": "list"})
    rec = ur.build_record(acc, {"id": "APIVIDEO001", "status": {"privacyStatus": "private",
                                                               "publishAt": "2026-09-29T22:00:00Z"}},
                          {"snippet": {"title": "t"}, "status": {"privacyStatus": "private"}},
                          TMP / "publish" / CH / "2026-09-30" / "harbourlights.mp4",
                          SimpleNamespace(answer="да", at=NOW), NOW)
    assert ur.check_row(rec) == [], ur.check_row(rec)
    assert rec["source"] == "api" and rec["publish_tz"] == "UTC" and rec["publish_day"] == "2026-09-30"
    assert rec["note"] == "publish/example-film/2026-09-30/harbourlights.md" and rec["channel"] == CH


def test_cf0720_mark_user_edited_by_via_and_dry_run():
    root, log, j = _studio_root()
    vid = "JWyd0AwT47E"
    rc, out = _cli("--journal", str(j), "studio", "--channel", CH, "--entry",
                   f"{CH}/2026-10-01T1313Z/rennick", "--video-id", vid,
                   "--slot", "2026-10-08 01:00 МСК", "--log", str(log))
    assert rc == 0, out
    before = j.read_bytes()
    at = "2026-10-13T10:00:00Z"
    dry = ur.mark_user_edited(vid, note="поправил тег (из центра)", path=j, now=at, by="user",
                              via="center", dry_run=True)
    assert j.read_bytes() == before, "a dry run wrote the journal"
    real = ur.mark_user_edited(vid, note="поправил тег (из центра)", path=j, now=at, by="user",
                               via="center")
    assert dry == real, (dry, real)
    (row,) = ur.uploads(j)
    assert row == real and row["user_edited"] is True
    assert row["user_edited_by"] == "user" and row["user_edited_via"] == "center"
    rc, out = _cli("--journal", str(j), "check")
    assert rc == 0 and "0 problems" in out, out
    # the undo without who: the pair of the earlier mark does not stay on the row
    undo = ur.mark_user_edited(slug="rennick", channel=CH, edited=False, path=j, now=at)
    assert undo["user_edited"] is False and "user_edited_by" not in undo
    assert "user_edited_via" not in ur.uploads(j)[0] and "user_edit_note" not in undo
    mid = j.read_bytes()
    for kw in ({"by": ""}, {"via": "a\nb"}, {"by": "x" * 41}, {"via": 3}):
        try:
            ur.mark_user_edited(vid, path=j, now=at, **kw)
        except ur.JournalError as e:
            assert "by=" in str(e) or "via=" in str(e), e
        else:
            raise AssertionError(f"{kw} was taken")
    assert j.read_bytes() == mid
    try:
        ur.mark_user_edited("ZZZZZZZZZZZ", path=j, dry_run=True)
    except ur.JournalError as e:
        assert "no journal row" in str(e)
    else:
        raise AssertionError("a dry run of an unknown video answered")


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

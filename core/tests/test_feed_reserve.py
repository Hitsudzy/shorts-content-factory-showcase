#!/usr/bin/env python3
"""CF-0918: the feed 3 days ahead and the reserve of evergreen videos - a video
already in Studio taken off its slot back into the копилка
(`publish_move.py --withdraw`), brought back to a day (`--move`,
`publish_stash.py confirm`), and everything that counts the feed not counting it.

On temp git roots only: no live publish/, no live journal, no network.

The shape of 04.11: a Tech channel with videos in Studio on 05, 08, 09 and 13.11
(1/day at 01:00 MSK). The user's policy - make videos 3 days ahead, keep a
reserve of evergreen ones - takes the 08/09 videos into the копилка (Studio:
«Ограниченный доступ»), and ipad-mini (13.11, «will be released on November 6»)
to 05.11 is refused while 05 is taken and goes when the video of 05 is moved.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "agents" / "analyst"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("feed-reserve-test-")
os.environ.setdefault("RUNLOG_STATE_DIR", str(TMP / "state"))
os.environ["RUNLOG_POOL"] = str(TMP / "no-pool")

import publish_move as pm       # noqa: E402
import publish_note             # noqa: E402
import publish_queue as pq      # noqa: E402
import publish_window           # noqa: E402
import upload_records as ur     # noqa: E402

CH = "techchan"
BATCH = "2026-11-01T0835Z"
NOW = "2026-11-04T14:30:00+03:00"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
IDS = {"exp-time": "EXPtime0001", "windows-11": "WIN11vid001", "rivian-r2": "RIVr2vid001",
       "ipad-mini": "IPADmini001", "old-one": "OLDoneVIDEO"}
PLACED = {"exp-time": "2026-11-05", "windows-11": "2026-11-08", "rivian-r2": "2026-11-09",
          "ipad-mini": "2026-11-13", "old-one": "2026-11-02"}
_n = [0]


def w(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False, indent=1)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")
    return p


def git(d, *args):
    return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True,
                          timeout=60, check=True).stdout


def note(slug, day):
    return (f"# {slug}\n\nБатч `pipeline/{CH}/{BATCH}/`\n\n## Название\n{slug} title\n\n"
            f"## Описание\nAbout {slug}.\n\n## Теги\n{slug}, tech\n\n## Публикация\n"
            f"**{day} 01:00 МСК** — ближайший свободный слот канала `{CH}` (очередь CF-0587, "
            f"`agents/publisher/publish_queue.py`), поставлен 2026-11-01T17:36Z.\n\n"
            f"## Настройки\n- Не для детей. ИИ/синтетический контент: нет.\n")


def jrow(slug, day, vid):
    return {"channel": CH, "entry_id": f"{CH}/{BATCH}/{slug}", "batch_id": BATCH,
            "topic_id": f"t-{slug}", "slug": slug, "video_id": vid,
            "url": f"https://youtube.com/shorts/{vid}", "publish_at": f"{day}T01:00:00+03:00",
            "publish_tz": "Europe/Moscow", "publish_day": day,
            "note": f"publish/{CH}/{day}/{slug}.md", "source": "studio",
            "recorded_at": "2026-11-01T17:51:55Z", "user_edited": False}


def make_root(placed=None, studio=None, queued=(), slot=SLOT):
    placed = dict(PLACED) if placed is None else placed
    studio = dict(PLACED) if studio is None else studio
    _n[0] += 1
    d = TMP / f"root{_n[0]}"
    w(d / ".gitignore", "*.mp4\n*.lock\n")
    w(d / "channels" / f"{CH}.json", {"channel_id": CH, "publisher": {"slot": slot}})
    pub = d / "publish"
    rows, readme = [], ["| ролик | статус |", "|---|---|"]
    for slug, day in placed.items():
        w(pub / CH / day / f"{slug}.md", note(slug, day))
        w(pub / CH / day / f"{slug}.mp4", slug.encode())
        rows.append({"entry_id": f"{CH}/{BATCH}/{slug}", "channel": CH, "batch_id": BATCH,
                     "slug": slug, "topic_id": f"t-{slug}", "verdict": "accepted",
                     "answered_at": "2026-11-01T16:00:00Z",
                     "publish_path": f"publish/{CH}/{day}/{slug}.mp4", "history": []})
        readme.append(f"| `{CH}/{day}/{slug}.mp4` | принят |")
    for slug in queued:
        w(pub / CH / "_queue" / f"{slug}.md", note(slug, "2026-11-30").replace(
            "**2026-11-30 01:00 МСК**", "Слот не назначен."))
        w(pub / CH / "_queue" / f"{slug}.mp4", slug.encode())
    w(pub / "uploads.json", {"note": "t", "task": "CF-0586", "format": 2,
                             "uploads": [jrow(s, day, IDS[s]) for s, day in studio.items()]})
    w(pub / "acceptance-log.json", {"note": "t", "task": "CF-0328", "acceptances": rows})
    w(pub / "publication-holds.json", {"holds": []})
    w(pub / "README.md", "\n".join(readme) + "\n")
    git(d, "init", "-q")
    git(d, "config", "user.email", "t@example.com")
    git(d, "config", "user.name", "t")
    git(d, "config", "commit.gpgsign", "false")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "fixture")
    return d


def journal(d):
    return {r["slug"]: r for r in json.loads((d / "publish" / "uploads.json").read_text(
        encoding="utf-8"))["uploads"]}


def taken(d, now=NOW, days=12):
    return {r["day"]: r["taken_by"] for r in pq.table(CH, d, now, days)}


def codes(ans, slug=None):
    return [r["code"] for r in ans["refusals"] if slug is None or r.get("slug") == slug]


def confirm(d, **kw):
    kw.setdefault("by", "driver")
    kw.setdefault("via", "studio")
    return pm.move_confirm(CH, kw.pop("moves", ()), kw.pop("unplace", ()), root=d, now=NOW,
                           open_rows=[], **kw)


# ------------------------------------------------------------------ the journal
def test_withdraw_marks_the_row_and_reschedule_brings_it_back():
    d = make_root()
    jp = d / "publish" / "uploads.json"
    row = ur.withdraw(IDS["windows-11"], note=f"publish/{CH}/_queue/windows-11.md", by="driver",
                      via="studio", path=jp, now="2026-11-04T11:40:00Z")
    assert row["publish_at"] is None and row["publish_day"] is None
    assert row["publish_tz"] == "Europe/Moscow"
    assert row["withdrawn"]["from_at"] == "2026-11-08T01:00:00+03:00"
    assert row["withdrawn"]["from_note"] == f"publish/{CH}/2026-11-08/windows-11.md"
    assert row["withdrawn"]["by"] == "driver" and row["withdrawn"]["task"] == "CF-0918"
    assert row["rescheduled"][-1]["withdrawn"] and row["rescheduled"][-1]["to_at"] is None
    assert ur.is_withdrawn(row) and not ur.holds_slot(row) and not ur.check_row(row)
    assert ur.is_withdrawn(journal(d)["windows-11"])
    try:
        ur.withdraw(IDS["windows-11"], path=jp)
        raise AssertionError("withdrawn twice")
    except ur.JournalError as e:
        assert "already withdrawn" in str(e)
    back = ur.reschedule(IDS["windows-11"], "2026-11-06T01:00:00+03:00",
                         note=f"publish/{CH}/2026-11-06/windows-11.md", by="driver",
                         via="studio", path=jp, task="CF-0918")
    assert back["publish_day"] == "2026-11-06" and "withdrawn" not in back
    assert back["rescheduled"][-1]["from_reserve"] and back["rescheduled"][-1]["from_at"] is None
    assert ur.holds_slot(journal(d)["windows-11"])


def test_the_readers_of_the_journal_do_not_count_a_withdrawn_row():
    import metrics
    import pool_release
    d = make_root()
    jp = d / "publish" / "uploads.json"
    before = taken(d)
    assert before["2026-11-08"] == "windows-11"
    ur.withdraw(IDS["windows-11"], path=jp)
    # the day folder still holds it here (the journal alone): the folder counts, the row not
    occ = [o for o in pq.occupants(CH, d) if o["slug"] == "windows-11"]
    assert occ and all(not s.startswith("uploads.json:") for s in occ[0]["sources"])
    feed = {x["slug"]: x for x in publish_window.feed(CH, d, NOW)}
    assert not feed["windows-11"]["in_studio"] and feed["windows-11"]["video_id"] is None
    # published: neither the ledger's reading nor the pool's release take it
    later = "2026-11-20T12:00:00+03:00"
    assert "windows-11" not in [r["slug"] for r in publish_window.published_rows(CH, d, later)]
    out = pool_release.published_from_uploads(d, pq.now_utc(later))
    assert f"{CH}/{BATCH}/windows-11" not in [e for e, _t, _a in out]
    assert f"{CH}/{BATCH}/rivian-r2" in [e for e, _t, _a in out]
    jobs, skips = metrics.plan(jp, channel=CH, now=pq.now_utc(later), root=d)
    assert {"video_id": IDS["windows-11"], "reason": "withdrawn"}.items() <= next(
        s for s in skips if s["video_id"] == IDS["windows-11"]).items()


# ------------------------------------------------------------------ --withdraw
WITHDRAW = dict(withdraw=["windows-11", "rivian-r2"])


def test_withdraw_plan_writes_nothing_and_says_what_studio_must_read():
    d = make_root()
    head = git(d, "rev-parse", "HEAD")
    ans = pm.move_plan(CH, root=d, now=NOW, **WITHDRAW)
    assert ans["ok"] and ans["dry_run"] and not ans["written"], ans["refusals"]
    by = {it["slug"]: it for it in ans["items"]}
    assert by["windows-11"]["op"] == "withdraw" and by["windows-11"]["in_studio"]
    assert by["windows-11"]["from_day"] == "2026-11-08"
    assert any("Ограниченный доступ" in w for w in by["windows-11"]["warnings"])
    assert any("запас" in line for line in ans["lines"])
    assert git(d, "rev-parse", "HEAD") == head and not git(d, "status", "--porcelain")


def test_withdraw_takes_the_videos_into_the_kopilka_with_their_ids_in_one_commit():
    d = make_root()
    head = git(d, "rev-parse", "HEAD")
    base = pm.move_plan(CH, root=d, now=NOW, **WITHDRAW)["sha256"]
    ans = confirm(d, base_sha256=base, **WITHDRAW)
    assert ans["ok"] and ans["written"] and ans["commit"], ans["refusals"]
    pub = d / "publish" / CH
    for slug, day in (("windows-11", "2026-11-08"), ("rivian-r2", "2026-11-09")):
        assert (pub / "_reserve" / f"{slug}.md").is_file()
        assert (pub / "_reserve" / f"{slug}.mp4").is_file()
        assert not (pub / "_queue" / f"{slug}.md").exists()
        assert not (pub / day / f"{slug}.md").exists()
        sec = publish_note.sections((pub / "_reserve" / f"{slug}.md").read_text(encoding="utf-8"))
        body = sec["Публикация"]
        assert body.startswith(f"Слот не назначен. В Studio: ограниченный доступ, video_id "
                               f"{IDS[slug]}"), body
        assert publish_note.publish_time(body) is None
        row = journal(d)[slug]
        assert row["withdrawn"]["from_day"] == day and row["publish_at"] is None
        assert row["note"] == f"publish/{CH}/_reserve/{slug}.md"
        assert row["withdrawn"]["from_note"] == f"publish/{CH}/{day}/{slug}.md"
    assert sorted(pq.waiting(CH, d)) == ["rivian-r2", "windows-11"]
    t = taken(d)
    assert t["2026-11-08"] is None and t["2026-11-09"] is None
    assert t["2026-11-05"] == "exp-time" and t["2026-11-13"] == "ipad-mini"
    assert git(d, "rev-parse", "HEAD") != head and not git(d, "status", "--porcelain")
    log = git(d, "log", "-1", "--format=%B")
    assert "в запас" in log and IDS["windows-11"] in log


def test_withdraw_and_moves_in_one_plan_ipad_mini_to_the_5th():
    d = make_root()
    # 05.11 taken by exp-time: the move alone is refused
    alone = pm.move_plan(CH, ["ipad-mini=2026-11-05"], root=d, now=NOW)
    assert codes(alone, "ipad-mini") == ["day_taken"]
    # exp-time withdrawn in the same plan frees the day
    ans = confirm(d, moves=["ipad-mini=2026-11-05"], withdraw=["exp-time", "windows-11"])
    assert ans["ok"], ans["refusals"]
    t = taken(d)
    assert t["2026-11-05"] == "ipad-mini" and t["2026-11-13"] is None
    row = journal(d)["ipad-mini"]
    assert row["publish_day"] == "2026-11-05" and not ur.is_withdrawn(row)
    assert ur.is_withdrawn(journal(d)["exp-time"])


def test_withdraw_refusals():
    d = make_root(studio={k: v for k, v in PLACED.items() if k != "rivian-r2"})
    ans = pm.move_plan(CH, root=d, now=NOW, withdraw=["old-one", "rivian-r2", "nope"])
    assert codes(ans, "old-one") == ["published"]
    assert codes(ans, "rivian-r2") == ["not_in_studio"]
    assert codes(ans, "nope") == ["not_found"]
    unp = pm.move_plan(CH, root=d, now=NOW, unplace=["windows-11"])
    assert codes(unp, "windows-11") == ["in_studio"]
    assert "--withdraw" in unp["refusals"][0]["line"]
    # a confirm with a refusal writes nothing
    head = git(d, "rev-parse", "HEAD")
    bad = confirm(d, withdraw=["windows-11", "old-one"])
    assert not bad["ok"] and not bad["written"]
    assert git(d, "rev-parse", "HEAD") == head and not git(d, "status", "--porcelain")
    # once withdrawn: neither withdraw nor unplace again
    assert confirm(d, withdraw=["windows-11"])["ok"]
    again = pm.move_plan(CH, root=d, now=NOW, withdraw=["windows-11"], unplace=[])
    assert codes(again, "windows-11") == ["in_reserve"]
    assert codes(pm.move_plan(CH, root=d, now=NOW, unplace=["windows-11"]),
                 "windows-11") == ["in_queue"]
    assert set(pm.WITHDRAW_REFUSALS).isdisjoint(pm.ITEM_REFUSALS)


# ------------------------------------------------------------------ back from the reserve
def test_move_brings_a_withdrawn_video_back_to_a_day_without_a_new_upload():
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    plan = pm.move_plan(CH, ["windows-11=2026-11-06"], root=d, now=NOW)
    assert plan["ok"], plan["refusals"]
    it = plan["items"][0]
    assert it["reserve"] and it["in_studio"] and it["from_day"] is None
    assert any("Отложенная публикация" in w for w in it["warnings"])
    assert "_reserve/ (запас) -> 2026-11-06 01:00 МСК" in plan["lines"][0]
    ans = confirm(d, moves=["windows-11=2026-11-06"], base_sha256=plan["sha256"])
    assert ans["ok"] and ans["commit"], ans["refusals"]
    pub = d / "publish" / CH
    md = pub / "2026-11-06" / "windows-11.md"
    assert md.is_file() and (pub / "2026-11-06" / "windows-11.mp4").is_file()
    assert not (pub / "_reserve" / "windows-11.md").exists()
    body = publish_note.sections(md.read_text(encoding="utf-8"))["Публикация"]
    assert body.startswith("**2026-11-06 01:00 МСК** — возвращён из запаса"), body
    row = journal(d)["windows-11"]
    assert row["publish_at"] == "2026-11-06T01:00:00+03:00" and "withdrawn" not in row
    assert row["note"] == f"publish/{CH}/2026-11-06/windows-11.md"
    assert row["video_id"] == IDS["windows-11"]
    assert taken(d)["2026-11-06"] == "windows-11" and pq.waiting(CH, d) == []
    assert not git(d, "status", "--porcelain")



# ------------------------------------------------------------------ the horizon
def test_the_horizon_is_min_feed_days_and_a_manual_move_past_it_is_a_warning():
    d = make_root()
    hz = pq.horizon(CH, d, NOW)
    assert hz["days"] == 3 and hz["last_day"] == "2026-11-07", hz
    assert pq.within_horizon(pq.now_utc("2026-11-07T01:00:00+03:00"), hz)
    assert not pq.within_horizon(pq.now_utc("2026-11-08T01:00:00+03:00"), hz)
    w(d / "channels" / f"{CH}.json", {"channel_id": CH, "publisher": {"slot": SLOT},
                                      "batch_schedule": {"min_feed_days": 14}})
    assert pq.horizon(CH, d, NOW)["last_day"] == "2026-11-18"
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    plan = pm.move_plan(CH, ["windows-11=2026-11-12"], root=d, now=NOW)
    assert plan["ok"], plan["refusals"]
    assert any(x.startswith("HORIZON windows-11") for x in plan["items"][0]["warnings"])


def test_a_reserve_video_is_not_placed_by_the_queue_itself():
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    try:
        pq.plan_slot(CH, BATCH, "windows-11", d, NOW)
        raise AssertionError("a reserve video got a slot by itself")
    except pq.QueueError as e:
        assert "reserve" in str(e) and "--move" in str(e), e
    assert pq._waiting_ready(CH, "other", d) == []


# ------------------------------------------------------------------ the batch planner
PLAN_NOW = "2026-11-04T23:30:00Z"           # 05.11 02:30 МСК - inside the default window


def _planner_root(days, queued=(), withdrawn=()):
    """A channel with `run_plan` and min_feed_days 3 (the horizon; the batch
    threshold, batch_feed_days, is the default 14 - CF-0922), Studio rows on `days`
    (01:00 MSK), pairs in `_queue/` for `queued`; the rows of `withdrawn`
    (slugs `v-<day>`) taken into the копилка through the journal's writer."""
    _n[0] += 1
    d = TMP / f"plan{_n[0]}"
    w(d / "channels" / f"{CH}.json", {"channel_id": CH, "publisher": {"slot": SLOT},
                                      "run_plan": {"stages": []},
                                      "batch_schedule": {"min_feed_days": 3}})
    rows = []
    for i, day in enumerate(days):
        slug = f"v-{day}"
        rows.append(dict(jrow(slug, day, f"VID{i:08d}"), entry_id=f"{CH}/{BATCH}/{slug}"))
    jp = w(d / "publish" / "uploads.json", {"uploads": rows})
    for slug in queued:
        w(d / "publish" / CH / "_queue" / f"{slug}.md", note(slug, "2026-11-30").replace(
            "**2026-11-30 01:00 МСК**", "Слот не назначен."))
        w(d / "publish" / CH / "_queue" / f"{slug}.mp4", b"x")
    for slug in withdrawn:
        vid = next(r["video_id"] for r in rows if r["slug"] == slug)
        ur.withdraw(vid, note=f"publish/{CH}/_queue/{slug}.md", by="driver", via="studio",
                    path=jp)
    return d


def test_withdrawing_the_far_days_makes_the_feed_short_and_the_plan_needs_a_batch():
    sys.path.insert(0, str(ROOT / "shared"))
    import batch_schedule as bs
    days = [f"2026-11-{x:02d}" for x in range(6, 21)]       # 15 days: past the threshold 14
    fed = bs.plan(_planner_root(days), PLAN_NOW, 1, open_rows=[])["days"][0]
    assert fed["status"] == "idle" and fed["kind"] == "fed", fed
    far = [f"v-{x}" for x in days[1:]]
    d = _planner_root(days, queued=far, withdrawn=far)
    assert sorted(pq.reserve(CH, d)) == sorted(far)
    day = bs.plan(d, PLAN_NOW, 1, open_rows=[])["days"][0]
    assert day["status"] == "planned" and day["kind"] == "needs_batch", day
    assert "лента короче 14 дн." in day["why"], day
    # the same pairs in _queue/ that are not in Studio still fill the feed (as before)
    plain = _planner_root(days[:1], queued=far)
    assert pq.reserve(CH, plain) == []
    assert bs.plan(plain, PLAN_NOW, 1, open_rows=[])["days"][0]["kind"] == "fed"


# ------------------------------------------------------------------ CF-0919: _reserve/
NEW = "2026-11-04T1006Z"


def _namesake(d, slug):
    """A new video of the same name in `_queue/`, another batch, not in Studio."""
    w(d / "publish" / CH / "_queue" / f"{slug}.md",
      note(slug, "2026-11-30").replace(BATCH, NEW).replace("**2026-11-30 01:00 МСК**",
                                                           "Слот не назначен."))
    w(d / "publish" / CH / "_queue" / f"{slug}.mp4", b"new")


def _legacy_withdraw(d, slug):
    """A video withdrawn by v2.50: the pair moved to `_queue/`, the row's note there."""
    pub = d / "publish"
    day = PLACED[slug]
    (pub / CH / "_queue").mkdir(parents=True, exist_ok=True)
    git(d, "mv", f"publish/{CH}/{day}/{slug}.md", f"publish/{CH}/_queue/{slug}.md")
    (pub / CH / "_queue" / f"{slug}.mp4").write_bytes(
        (pub / CH / day / f"{slug}.mp4").read_bytes())
    (pub / CH / day / f"{slug}.mp4").unlink()
    ur.withdraw(IDS[slug], note=f"publish/{CH}/_queue/{slug}.md", by="driver", via="studio",
                path=pub / "uploads.json", now="2026-11-04T11:40:00Z")
    log = pub / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    for r in doc["acceptances"]:
        if r["slug"] == slug:
            r["publish_path"] = f"publish/{CH}/_queue/{slug}.mp4"
    w(log, doc)
    rd = pub / "README.md"
    rd.write_text(rd.read_text(encoding="utf-8").replace(f"{CH}/{day}/{slug}.mp4",
                                                         f"{CH}/_queue/{slug}.mp4"),
                  encoding="utf-8")
    git(d, "add", "-A")
    git(d, "commit", "-qm", f"v2.50 withdraw {slug}")


def test_migration_is_dry_first_moves_the_pairs_and_keeps_the_history():
    d = make_root()
    _legacy_withdraw(d, "windows-11")
    _legacy_withdraw(d, "rivian-r2")
    stamp = journal(d)["windows-11"]["withdrawn"]
    assert sorted(pq.reserve(CH, d)) == ["rivian-r2", "windows-11"]    # the legacy place is read
    head, pub = git(d, "rev-parse", "HEAD"), d / "publish" / CH
    dry = pm.migrate_plan(CH, d)
    assert dry["ok"] and dry["dry_run"] and not dry["written"]
    assert sorted(i["slug"] for i in dry["items"]) == ["rivian-r2", "windows-11"]
    assert any("publish/techchan/_queue/windows-11.md -> publish/techchan/_reserve/windows-11.md"
               in x for x in dry["lines"])
    assert (pub / "_queue" / "windows-11.md").is_file() and git(d, "rev-parse", "HEAD") == head
    assert not (pub / "_reserve").exists()
    bad = pm.migrate_confirm(CH, by="driver", via=None, root=d, open_rows=[])
    assert not bad["ok"] and "bad_who" in codes(bad) and git(d, "rev-parse", "HEAD") == head
    going = pm.migrate_confirm(CH, by="driver", via="t", root=d,
                               open_rows=[(d / "pipeline" / CH / "b", NOW, True)])
    assert "batch_open" in codes(going) and git(d, "rev-parse", "HEAD") == head
    ans = pm.migrate_confirm(CH, by="driver", via="t", root=d, base_sha256=dry["sha256"],
                             open_rows=[])
    assert ans["ok"] and ans["written"] and ans["commit"], ans["refusals"]
    assert ans["commit"] == git(d, "rev-parse", "HEAD").strip() and not git(d, "status", "--porcelain")
    assert (pub / "_reserve" / "windows-11.md").is_file()
    assert (pub / "_reserve" / "windows-11.mp4").read_bytes() == b"windows-11"
    assert not (pub / "_queue" / "windows-11.md").exists()
    row = journal(d)["windows-11"]
    assert row["note"] == f"publish/{CH}/_reserve/windows-11.md"
    assert row["withdrawn"] == stamp
    assert row["withdrawn"]["from_note"] == f"publish/{CH}/2026-11-08/windows-11.md"
    log = {r["slug"]: r for r in json.loads((d / "publish" / "acceptance-log.json").read_text(
        encoding="utf-8"))["acceptances"]}
    assert log["windows-11"]["publish_path"] == f"publish/{CH}/_reserve/windows-11.mp4"
    assert f"{CH}/_reserve/windows-11.mp4" in (d / "publish" / "README.md").read_text(
        encoding="utf-8")
    assert sorted(pq.reserve(CH, d)) == ["rivian-r2", "windows-11"] and pq.queued(CH, d) == []
    # the second run finds nothing, and the CLI is the same call
    again = pm.migrate_confirm(CH, by="driver", via="t", root=d, open_rows=[])
    assert again["ok"] and not again["written"] and not again["items"]
    assert any("nothing to migrate" in x for x in again["lines"])
    # a video brought back from where the migration left it
    moved = confirm(d, moves=["windows-11=2026-11-06"])
    assert moved["ok"], moved["refusals"]
    assert (pub / "2026-11-06" / "windows-11.md").is_file()
    assert not (pub / "_reserve" / "windows-11.md").exists()
    assert (pub / "2026-11-06" / "windows-11.mp4").is_file()


def test_migration_names_a_second_video_by_its_batch_and_leaves_a_namesake_in_the_queue():
    d = make_root()
    _legacy_withdraw(d, "windows-11")
    w(d / "publish" / CH / "_reserve" / "windows-11.md",
      note("windows-11", "2026-11-30").replace(BATCH, "2026-10-01T0000Z"))
    w(d / "publish" / CH / "_reserve" / "windows-11.mp4", b"x")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "another of the name")
    # CF-0920: not refused - the name is taken, the file carries its batch
    ans = pm.migrate_confirm(CH, by="driver", via="t", root=d, open_rows=[])
    assert ans["ok"] and ans["written"], ans["refusals"]
    moved = f"publish/{CH}/_reserve/windows-11~{BATCH}.md"
    assert ans["items"][0]["to"] == moved and (d / moved).is_file()
    assert (d / moved).with_suffix(".mp4").is_file()
    assert journal(d)["windows-11"]["note"] == moved
    assert not git(d, "status", "--porcelain").strip()
    # a new video of the name in _queue/ is not the reserve's: nothing to migrate
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    _namesake(d, "windows-11")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "new one")
    plan = pm.migrate_plan(CH, d)
    assert plan["ok"] and plan["items"] == []


def test_a_namesake_of_a_reserve_video_is_a_video_of_its_own():
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    _namesake(d, "windows-11")
    assert pq.reserve(CH, d) == ["windows-11"] and pq.queued(CH, d) == ["windows-11"]
    assert pq.waiting(CH, d) == ["windows-11"]      # a name once; publish_stash tells the two
    # the new one can take a slot of its own - the reserve one does not stand in its way
    log = d / "publish" / "acceptance-log.json"
    doc = json.loads(log.read_text(encoding="utf-8"))
    doc["acceptances"].append({"entry_id": f"{CH}/{NEW}/windows-11", "channel": CH,
                               "batch_id": NEW, "slug": "windows-11", "topic_id": "t-new",
                               "verdict": "accepted", "answered_at": "2026-11-04T10:00:00Z",
                               "publish_path": f"publish/{CH}/_queue/windows-11.mp4",
                               "history": []})
    w(log, doc)
    assert pq.plan_slot(CH, NEW, "windows-11", root=d, now=NOW)["slot"]
    try:
        pq.plan_slot(CH, BATCH, "windows-11", root=d, now=NOW)
    except pq.QueueError as e:
        assert "запас" in str(e) or "reserve" in str(e) or "копилк" in str(e), e
    else:
        raise AssertionError("the reserve one went into a slot by itself")


def test_move_by_name_returns_the_reserve_one_and_a_placed_namesake_asks_which():
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    _namesake(d, "windows-11")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "new one")
    # the only one with a Studio row is the reserve's: by name, by batch - the same
    plan = pm.move_plan(CH, [f"{BATCH}/windows-11=2026-11-06"], root=d, now=NOW)
    assert plan["ok"] and plan["items"][0]["reserve"], plan["refusals"]
    other = pm.move_plan(CH, [f"{NEW}/windows-11=2026-11-06"], root=d, now=NOW)
    assert "in_queue" in codes(other) or "not_found" in codes(other), other["refusals"]
    ans = confirm(d, moves=["windows-11=2026-11-06"])
    assert ans["ok"], ans["refusals"]
    pub = d / "publish" / CH
    assert (pub / "2026-11-06" / "windows-11.md").is_file()
    assert (pub / "_queue" / "windows-11.mp4").read_bytes() == b"new"   # the new one stayed
    # now a namesake on a day and another withdrawn: `--move` by name asks which
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    pub = d / "publish" / CH
    w(pub / "2026-11-12" / "windows-11.md",
      note("windows-11", "2026-11-12").replace(BATCH, NEW))
    w(pub / "2026-11-12" / "windows-11.mp4", b"new")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "placed new one")
    two = pm.move_plan(CH, ["windows-11=2026-11-06"], root=d, now=NOW)
    assert "ambiguous" in codes(two), two["refusals"]
    assert "--move BATCH/windows-11=DAY" in two["refusals"][0]["line"]
    named = pm.move_plan(CH, [f"{BATCH}/windows-11=2026-11-06"], root=d, now=NOW)
    assert named["ok"] and named["items"][0]["reserve"], named["refusals"]


def test_a_second_video_of_one_name_goes_into_the_reserve_under_its_batch():
    d = make_root()
    assert confirm(d, withdraw=["windows-11"])["ok"]
    pub = d / "publish" / CH
    # the new one of the name, placed and uploaded
    w(pub / "2026-11-12" / "windows-11.md",
      note("windows-11", "2026-11-12").replace(BATCH, NEW))
    w(pub / "2026-11-12" / "windows-11.mp4", b"new")
    jp = d / "publish" / "uploads.json"
    doc = json.loads(jp.read_text(encoding="utf-8"))
    doc["uploads"].append(dict(jrow("windows-11", "2026-11-12", "WIN11vid002"),
                               batch_id=NEW, entry_id=f"{CH}/{NEW}/windows-11"))
    w(jp, doc)
    git(d, "add", "-A")
    git(d, "commit", "-qm", "new one in Studio")
    # CF-0920: the live one is named by the plan (the reserve one has a row too)
    ans = confirm(d, withdraw=[f"{NEW}/windows-11"])
    assert ans["ok"], ans["refusals"]
    assert ans["items"][0]["path"] == f"publish/{CH}/_reserve/windows-11~{NEW}.md"
    assert (pub / "_reserve" / f"windows-11~{NEW}.mp4").read_bytes() == b"new"
    assert (pub / "_reserve" / "windows-11.md").is_file()
    assert sorted(r.get("batch_id") for _e, r in pq.reserve_entries(CH, d)) == sorted([BATCH, NEW])
    # back: the bare name is ambiguous, the batch's name is not, and the day has the plain name
    two = pm.move_plan(CH, ["windows-11=2026-11-06"], root=d, now=NOW)
    assert not two["ok"] and codes(two) == ["ambiguous"], two["refusals"]
    back = confirm(d, moves=[f"{NEW}/windows-11=2026-11-06"])
    assert back["ok"], back["refusals"]
    assert (pub / "2026-11-06" / "windows-11.mp4").read_bytes() == b"new"
    assert not (pub / "_reserve" / f"windows-11~{NEW}.md").exists()
    assert (pub / "_reserve" / "windows-11.md").is_file()
    rows = json.loads((d / "publish" / "uploads.json").read_text(encoding="utf-8"))["uploads"]
    new = next(r for r in rows if r["video_id"] == "WIN11vid002")
    assert new["note"] == f"publish/{CH}/2026-11-06/windows-11.md"


def test_the_new_namesake_fills_the_feed_and_the_reserve_one_does_not():
    sys.path.insert(0, str(ROOT / "shared"))
    import batch_schedule as bs
    days = ["2026-11-06"]
    d = _planner_root(days)
    jp = d / "publish" / "uploads.json"
    # the 15-th: a reserve pair in _reserve/ with a row and a new namesake in _queue/
    doc = json.loads(jp.read_text(encoding="utf-8"))
    doc["uploads"].append(jrow("kept", "2026-11-20", "KEPTvid0001"))
    w(jp, doc)
    ur.withdraw("KEPTvid0001", note=f"publish/{CH}/_reserve/kept.md", by="driver", via="studio",
                path=jp)
    w(d / "publish" / CH / "_reserve" / "kept.md", note("kept", "2026-11-30"))
    w(d / "publish" / CH / "_reserve" / "kept.mp4", b"x")
    assert pq.reserve(CH, d) == ["kept"] and pq.queued(CH, d) == []
    alone = bs.plan(d, PLAN_NOW, 1, open_rows=[])["days"][0]
    assert alone["kind"] == "needs_batch", alone
    more = [f"more{i:02d}" for i in range(12)]     # CF-0922: 1 + 13 - the batch threshold 14
    for slug in ["kept"] + more:
        w(d / "publish" / CH / "_queue" / f"{slug}.md",
          note(slug, "2026-11-30").replace(BATCH, NEW))
        w(d / "publish" / CH / "_queue" / f"{slug}.mp4", b"y")
    assert sorted(pq.queued(CH, d)) == sorted(["kept"] + more)
    assert bs.plan(d, PLAN_NOW, 1, open_rows=[])["days"][0]["kind"] == "fed"


def test_the_cli_of_the_migration():
    d = make_root()
    _legacy_withdraw(d, "windows-11")
    cmd = [sys.executable, str(AGENT / "publish_move.py"), "--channel", CH, "--migrate-reserve",
           "--root", str(d)]
    dry = subprocess.run(cmd + ["--json"], capture_output=True, text=True, timeout=60)
    assert dry.returncode == 0, dry.stderr
    assert json.loads(dry.stdout)["dry_run"] and (d / "publish" / CH / "_queue" /
                                                  "windows-11.md").is_file()
    both = subprocess.run(cmd + ["--withdraw", "exp-time"], capture_output=True, text=True,
                          timeout=60)
    assert both.returncode != 0

def test_a_horizon_filled_from_the_reserve_needs_a_batch_and_keeps_the_horizon():
    """CF-0922 (06.11: no batch at all): the morning fills the 3-day horizon from
    the reserve (05.11: 06-08.11 in Studio) - the plan needs a batch (the
    threshold is batch_feed_days 14), and placing still stops at the horizon:
    the next free slot, 09.11, is beyond_horizon."""
    sys.path.insert(0, str(ROOT / "shared"))
    import batch_schedule as bs
    d = _planner_root(["2026-11-06", "2026-11-07", "2026-11-08"])
    day = bs.plan(d, PLAN_NOW, 1, open_rows=[])["days"][0]
    assert day["status"] == "planned" and day["kind"] == "needs_batch", day
    assert "лента короче 14 дн. (на 3 дн.)" in day["why"], day
    hz = pq.horizon(CH, d, PLAN_NOW)
    assert hz["days"] == 3 and hz["last_day"] == "2026-11-08", hz
    assert pq.within_horizon(pq.now_utc("2026-11-08T01:00:00+03:00"), hz)
    nxt = pq.now_utc("2026-11-09T01:00:00+03:00")
    assert not pq.within_horizon(nxt, hz)
    assert pq.beyond_line("v-x", nxt, hz).startswith("beyond_horizon: v-x"), hz


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

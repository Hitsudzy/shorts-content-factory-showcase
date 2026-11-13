#!/usr/bin/env python3
"""CF-0856: move a placed video to another day, or take it back into the
копилка - `agents/publisher/publish_move.py`.

On temp git roots only: no live publish/, no live journal, no network.

What is pinned - the shape of 23.10 (commit 09ba3029, done by hand then):
three videos of a channel placed on 24, 25, 26.10; gemini (24) is not in
Studio, iphone-duo (25) and openai (26) are (live journal rows). One command -
unplace gemini, iphone-duo to 24, openai to 25 - gives:

* gemini's pair in `_queue/`, its `## Публикация` "Слот не назначен..." (no
  time: the queue reads it as waiting);
* the two pairs in their new day folders, their notes naming the new slot in
  bold, the journal rows' `publish_at` / `publish_day` / `note` rewritten and
  the move recorded in `rescheduled` (by, via, from, to);
* the queue: 24 iphone-duo, 25 openai, 26 free;
* one commit, nothing left dirty; the plan judged as a whole, whatever order
  the moves are named in;

and the refusals: a day still taken, a published video, a video not found,
unplacing a video that is in Studio, one in `_queue/`, a slot sooner than the
lead; a confirm with any refusal writes nothing; by/via, an open batch and a
changed base are refused.
"""
import io
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

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("publish-move-test-")
os.environ.setdefault("RUNLOG_STATE_DIR", str(TMP / "state"))
os.environ["RUNLOG_POOL"] = str(TMP / "no-pool")

import publish_move as pm       # noqa: E402
import publish_note             # noqa: E402
import publish_queue as pq      # noqa: E402

CH = "techchan"
BATCH = "2026-10-23T1504Z"
NOW = "2026-10-23T21:30:00+03:00"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
IDS = {"iphone-duo": "8-MBFrW93lk", "openai": "uzrmS1z-ji8", "old-one": "OLDoneVIDEO"}
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
            f"`agents/publisher/publish_queue.py`), поставлен 2026-10-23T17:36Z.\n\n"
            f"## Настройки\n- Не для детей. ИИ/синтетический контент: нет.\n")


def jrow(slug, day, vid):
    return {"channel": CH, "entry_id": f"{CH}/{BATCH}/{slug}", "batch_id": BATCH,
            "topic_id": f"t-{slug}", "slug": slug, "video_id": vid,
            "url": f"https://youtube.com/shorts/{vid}", "publish_at": f"{day}T01:00:00+03:00",
            "publish_tz": "Europe/Moscow", "publish_day": day,
            "note": f"publish/{CH}/{day}/{slug}.md", "source": "studio",
            "recorded_at": "2026-10-23T17:51:55Z", "user_edited": False}


def root(placed=None, studio=None, queued=(), slot=SLOT):
    """A git root of 23.10: `placed` {slug: day} in day folders (note + mp4),
    `studio` {slug: day} with live journal rows, `queued` slugs in `_queue/`."""
    placed = {"gemini": "2026-10-24", "iphone-duo": "2026-10-25", "openai": "2026-10-26",
              "old-one": "2026-10-22"} if placed is None else placed
    studio = {"iphone-duo": "2026-10-25", "openai": "2026-10-26",
              "old-one": "2026-10-22"} if studio is None else studio
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
                     "answered_at": "2026-10-23T16:00:00Z",
                     "publish_path": f"publish/{CH}/{day}/{slug}.mp4", "history": []})
        readme.append(f"| `{CH}/{day}/{slug}.mp4` | принят |")
    for slug in queued:
        w(pub / CH / "_queue" / f"{slug}.md", note(slug, "2026-10-30").replace(
            "**2026-10-30 01:00 МСК**", "Слот не назначен."))
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


def taken(d, now=NOW, days=5):
    return {r["day"]: r["taken_by"] for r in pq.table(CH, d, now, days)}


def codes(ans, slug=None):
    return [r["code"] for r in ans["refusals"] if slug is None or r.get("slug") == slug]


def confirm(d, **kw):
    kw.setdefault("by", "user")
    kw.setdefault("via", "center")
    return pm.move_confirm(CH, kw.pop("moves", ()), kw.pop("unplace", ()), root=d, now=NOW,
                           open_rows=[], **kw)


# ------------------------------------------------------------------ 23.10
SHIFT = dict(moves=["iphone-duo=2026-10-24", "openai=2026-10-25"], unplace=["gemini"])


def test_the_plan_of_23_10_writes_nothing_and_judges_the_whole_shift():
    d = root()
    head = git(d, "rev-parse", "HEAD")
    ans = pm.move_plan(CH, root=d, now=NOW, **SHIFT)
    assert ans["ok"] and ans["dry_run"] and not ans["written"], ans["refusals"]
    by = {it["slug"]: it for it in ans["items"]}
    assert by["gemini"]["op"] == "unplace" and by["gemini"]["from_day"] == "2026-10-24"
    assert by["iphone-duo"]["day"] == "2026-10-24" and by["iphone-duo"]["in_studio"]
    assert by["iphone-duo"]["slot"] == "2026-10-23T22:00:00Z"
    assert by["openai"]["label"] == "2026-10-25 01:00 МСК"
    assert any(w.startswith("STUDIO openai") for w in by["openai"]["warnings"])
    assert ans["sha256"] == ans["base_sha256"] and "not touched" in ans["ledger"]
    assert git(d, "rev-parse", "HEAD") == head and not git(d, "status", "--porcelain")
    # the order the moves are named in does not matter
    rev = pm.move_plan(CH, ["openai=2026-10-25", "iphone-duo=2026-10-24"], ["gemini"],
                       root=d, now=NOW)
    assert rev["ok"], rev["refusals"]


def test_the_confirm_of_23_10_gives_the_form_of_09ba3029_in_one_commit():
    d = root()
    head = git(d, "rev-parse", "HEAD")
    base = pm.move_plan(CH, root=d, now=NOW, **SHIFT)["sha256"]
    ans = confirm(d, base_sha256=base, **SHIFT)
    assert ans["ok"] and ans["written"] and ans["commit"], ans["refusals"]
    pub = d / "publish" / CH
    # gemini back in the копилка, read as waiting
    assert (pub / "_queue" / "gemini.md").is_file() and (pub / "_queue" / "gemini.mp4").is_file()
    assert not (pub / "2026-10-24" / "gemini.md").exists()
    sec = publish_note.sections((pub / "_queue" / "gemini.md").read_text(encoding="utf-8"))
    assert sec["Публикация"].startswith("Слот не назначен. Снят с 2026-10-24")
    assert "user, center" in sec["Публикация"]
    assert publish_note.publish_time(sec["Публикация"]) is None
    assert sec["Название"] == "gemini title"                     # the rest of the note stays
    assert pq.waiting(CH, d) == ["gemini"]
    # the two moved pairs and their notes
    for slug, day, old in (("iphone-duo", "2026-10-24", "2026-10-25"),
                           ("openai", "2026-10-25", "2026-10-26")):
        md = pub / day / f"{slug}.md"
        assert md.is_file() and (pub / day / f"{slug}.mp4").is_file()
        assert not (pub / old / f"{slug}.md").exists()
        body = publish_note.sections(md.read_text(encoding="utf-8"))["Публикация"]
        assert body.startswith(f"**{day} 01:00 МСК** — перенесён с {old}"), body
        assert pq.msk_day(publish_note.publish_time(body)) == day
        row = journal(d)[slug]
        assert row["publish_at"] == f"{day}T01:00:00+03:00" and row["publish_day"] == day
        assert row["note"] == f"publish/{CH}/{day}/{slug}.md"
        step = row["rescheduled"][-1]
        assert step["from_at"] == f"{old}T01:00:00+03:00" and step["from_day"] == old
        assert step["to_day"] == day and step["by"] == "user" and step["via"] == "center"
        assert step["task"] == "CF-0856"
    # the queue now
    t = taken(d)
    assert t["2026-10-24"] == "iphone-duo" and t["2026-10-25"] == "openai"
    assert t["2026-10-26"] is None
    # the acceptance record and the README follow the files
    acc = {r["slug"]: r["publish_path"] for r in json.loads(
        (d / "publish" / "acceptance-log.json").read_text(encoding="utf-8"))["acceptances"]}
    assert acc["gemini"] == f"publish/{CH}/_queue/gemini.mp4"
    assert acc["openai"] == f"publish/{CH}/2026-10-25/openai.mp4"
    assert f"`{CH}/2026-10-24/iphone-duo.mp4`" in (d / "publish" / "README.md").read_text(
        encoding="utf-8")
    # one commit, nothing left behind
    assert git(d, "rev-list", "--count", f"{head.strip()}..HEAD").strip() == "1"
    assert git(d, "rev-parse", "HEAD").strip() == ans["commit"]
    assert not git(d, "status", "--porcelain"), git(d, "status", "--porcelain")
    msg = git(d, "log", "-1", "--format=%B")
    assert msg.startswith(f"Очередь {CH}: перенос iphone-duo 10-25→10-24, openai 10-26→10-25; "
                          f"gemini в копилку (user, center)"), msg
    files = git(d, "show", "--name-status", "--format=", "HEAD")
    assert "uploads.json" in files and f"_queue/gemini.md" in files and ".mp4" not in files
    assert f"publish/{CH}/_queue/gemini.md" in ans["touched"]
    assert ans["new_sha256"] != ans["sha256"]


def test_a_video_not_in_studio_is_moved_by_its_folder_only():
    d = root()
    ans = confirm(d, moves=["gemini=2026-10-27"])
    assert ans["ok"], ans["refusals"]
    it = ans["items"][0]
    assert it["path"] == f"publish/{CH}/2026-10-27/gemini.md" and not it["in_studio"]
    assert "journal" not in it and "gemini" not in journal(d)
    assert taken(d, days=6)["2026-10-27"] == "gemini" and taken(d)["2026-10-24"] is None


def test_a_swap_of_two_days_is_no_conflict():
    d = root()
    ans = confirm(d, moves=["iphone-duo=2026-10-26", "openai=2026-10-25"])
    assert ans["ok"], ans["refusals"]
    t = taken(d)
    assert t["2026-10-25"] == "openai" and t["2026-10-26"] == "iphone-duo"


# ------------------------------------------------------------------ refusals
def test_a_day_still_taken_is_refused_and_the_chain_behind_it_too():
    d = root()
    ans = pm.move_plan(CH, ["openai=2026-10-24"], root=d, now=NOW)
    assert codes(ans) == ["day_taken"] and "gemini" in ans["refusals"][0]["line"]
    # without unplacing gemini, iphone-duo cannot take 24 - so it stays on 25
    # and openai cannot take 25 either
    ans = pm.move_plan(CH, ["iphone-duo=2026-10-24", "openai=2026-10-25"], root=d, now=NOW)
    assert codes(ans, "iphone-duo") == ["day_taken"] and codes(ans, "openai") == ["day_taken"]
    assert "iphone-duo" in [r for r in ans["refusals"] if r["slug"] == "openai"][0]["line"]


def test_published_not_found_in_studio_in_queue_same_day_and_too_soon():
    d = root(queued=["spacex"])
    ans = pm.move_plan(CH, ["old-one=2026-10-28", "ghost=2026-10-28", "spacex=2026-10-28",
                            "openai=2026-10-26", "gemini=31.10"], ["iphone-duo"],
                       root=d, now=NOW)
    assert codes(ans, "old-one") == ["published"]
    assert codes(ans, "ghost") == ["not_found"]
    assert codes(ans, "spacex") == ["in_queue"]
    assert codes(ans, "openai") == ["same_day"]
    assert codes(ans, "gemini") == ["bad_day"]
    assert codes(ans, "iphone-duo") == ["in_studio"]
    # 00:30 of the 24th: gemini's 01:00 is still ahead, but within the 2 h lead
    late = pm.move_plan(CH, ["iphone-duo=2026-10-24"], ["gemini"], root=d,
                        now="2026-10-24T00:30:00+03:00")
    assert codes(late, "iphone-duo") == ["too_soon"] and not codes(late, "gemini")
    # past 01:00 of the 24th gemini is published
    past = pm.move_plan(CH, [], ["gemini"], root=d, now="2026-10-24T02:00:00+03:00")
    assert codes(past, "gemini") == ["published"]


def test_a_confirm_with_any_refusal_writes_nothing():
    d = root()
    head = git(d, "rev-parse", "HEAD")
    before = (d / "publish" / "uploads.json").read_bytes()
    ans = confirm(d, moves=["iphone-duo=2026-10-24", "ghost=2026-10-28"], unplace=["gemini"])
    assert not ans["ok"] and not ans["written"] and ans["commit"] is None
    assert codes(ans) == ["not_found"]
    assert (d / "publish" / CH / "2026-10-24" / "gemini.md").is_file()
    assert (d / "publish" / "uploads.json").read_bytes() == before
    assert git(d, "rev-parse", "HEAD") == head and not git(d, "status", "--porcelain")


def test_who_an_open_batch_and_a_changed_base_are_refused():
    d = root()
    assert codes(confirm(d, by="", **SHIFT)) == ["bad_who"]
    assert codes(confirm(d, via=None, **SHIFT)) == ["bad_who"]
    ans = pm.move_confirm(CH, SHIFT["moves"], SHIFT["unplace"], "user", "center", root=d,
                          now=NOW, open_rows=[(d / "pipeline" / CH / "B", None, True)])
    assert codes(ans) == ["batch_open"]
    assert codes(confirm(d, base_sha256="0" * 64, **SHIFT)) == ["check_changed"]
    assert codes(pm.move_plan("nochan", ["a=2026-10-24"], root=d, now=NOW)) == ["unknown_channel"]
    assert codes(pm.move_plan(CH, root=d, now=NOW)) == ["empty_order"]
    assert (d / "publish" / CH / "2026-10-24" / "gemini.md").is_file()


def test_the_candidate_checks_see_the_whole_plan_and_only_warn():
    d = root()
    seen = []

    def check(channel, slug, slot, root_, now, ctx):
        seen.append((slug, pq.msk_day(slot), sorted(ctx.get("moved") or {}),
                     list(ctx.get("removed") or ())))
        return {"verdict": "reorder", "reason": f"pair repeat at {slug}"}

    saved = list(pq.CANDIDATE_CHECKS)
    pq.CANDIDATE_CHECKS[:] = [check]
    try:
        ans = pm.move_plan(CH, root=d, now=NOW, **SHIFT)
    finally:
        pq.CANDIDATE_CHECKS[:] = saved
    assert ans["ok"], ans["refusals"]                            # a warning, never a refusal
    assert sorted(seen) == [("iphone-duo", "2026-10-24", ["openai"], ["gemini"]),
                            ("openai", "2026-10-25", ["iphone-duo"], ["gemini"])]
    assert any("WINDOW" in w and "pair repeat at openai" in w
               for it in ans["items"] for w in it["warnings"])


def test_the_journal_moves_only_a_live_row():
    import upload_records as ur
    d = root()
    path = d / "publish" / "uploads.json"
    row = ur.reschedule(IDS["openai"], "2026-10-27T01:00:00+03:00", by="user", via="t",
                        path=path, dry_run=True)
    assert row["publish_day"] == "2026-10-27" and journal(d)["openai"]["publish_day"] == "2026-10-26"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["uploads"][0]["removed_at"] = "2026-10-23T00:00:00Z"
    path.write_text(json.dumps(doc), encoding="utf-8")
    for vid, at in ((doc["uploads"][0]["video_id"], "2026-10-27T01:00:00+03:00"),
                    ("NOSUCHVIDEO", "2026-10-27T01:00:00+03:00"),
                    (IDS["openai"], "2026-10-27T01:00:00")):
        try:
            ur.reschedule(vid, at, by="user", via="t", path=path)
        except ur.JournalError:
            continue
        raise AssertionError(f"{vid} {at}: not refused")


# ------------------------------------------------------------------ the command
def test_the_command_is_a_dry_run_unless_apply():
    d = root()
    out = io.StringIO()
    args = ["--channel", CH, "--root", str(d), "--now", NOW, "--unplace", "gemini",
            "--move", "iphone-duo=2026-10-24", "--move", "openai=2026-10-25"]
    assert pm.main(args, out=out) == 0
    text = out.getvalue()
    assert "unplace gemini: 2026-10-24 -> _queue/" in text and "dry run" in text, text
    assert (d / "publish" / CH / "2026-10-24" / "gemini.md").is_file()
    out = io.StringIO()
    assert pm.main(args + ["--json"], out=out) == 0
    assert json.loads(out.getvalue())["dry_run"] is True
    out = io.StringIO()
    assert pm.main(args + ["--apply", "--by", "user", "--via", "cli"], out=out) == 0, out.getvalue()
    assert "commit " in out.getvalue()
    assert (d / "publish" / CH / "_queue" / "gemini.md").is_file()
    out = io.StringIO()
    assert pm.main(["--channel", CH, "--root", str(d), "--now", NOW,
                    "--move", "ghost=2026-10-28"], out=out) == 1


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

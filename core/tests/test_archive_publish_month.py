#!/usr/bin/env python3
"""CF-0476: a month that is over leaves `publish/` for one zip on Archive.

`scripts/archive_publish_month.py` packs every `publish/<channel>/<day>/` of a
month that is over into `<volume>/shorts-content-factory-publish/<channel>/
<YYYY-MM>.zip` (stored), writes `<YYYY-MM>.manifest.json` next to it, reads
the zip back and checks every member's sha256 against its source, and only
then moves the month out of `publish/`: mp4 deleted, notes `git rm`'d, day
folders removed, README rows and `publish_path` pointing into the zip, one
commit made by the script itself. `--repack-legacy` turns a month archived the
old way (folders + MANIFEST.json) into the same zip.

Everything runs in a temp dir: a fake factory root with its own `publish/`
(a temp git repo where the case needs one), a plain folder standing in for the
volume (`--skip-mount-check`, the flag the tests use; without it a plain
folder is *not* a volume - that is one of the cases), a temp NEEDS-YOU note
and a temp log. The real /Volumes/Archive, the real publish/ and the real
Notebook vault are never touched.
"""
import contextlib
import hashlib
import io
import json
import plistlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

import archive_publish_month as apm     # noqa: E402
import upload_records                   # noqa: E402  (agents/publisher, via apm)
import acceptance                       # noqa: E402
import publish_layout as pl             # noqa: E402

from _tmproot import tmp_root           # noqa: E402

sys.path.insert(0, str(ROOT / "shared"))
import needs_you as nyj                 # noqa: E402

QF = f"needs-you/{nyj.JOURNAL}"          # CF-0652: the journal of questions under the base

TMP = tmp_root("archive-publish-month-test-")
_n = [0]
REAL_BATCH_OPEN = apm.batch_open

README = """# Ролики для публикации

| ролик | батч | вердикт пользователя |
|---|---|---|
| `example-film/2026-09-22/outrider.mp4` | `b` | принят; ~~`youtube.com/shorts/OLDOLDold1`~~ → `youtube.com/shorts/NEWnew1234` |
| `example-film/2026-09-29/wolfhame.mp4` | `b` | принят; метаданные — `example-film/2026-09-29/wolfhame.md`; `youtube.com/shorts/README9999` |
| `example-film/2026-10-01/vanguards.mp4` | `b` | принят; метаданные — `example-film/2026-10-01/vanguards.md` |
"""



def note(slug, link=None):
    tail = f"\n**Загружен** — `youtube.com/shorts/{link}`, пояс GMT+03:00.\n" if link else ""
    return f"# {slug} — к публикации\n\n## Публикация\n2026-09-28 01:00 МСК\n{tail}"


def git(cwd, *args):
    cp = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                        timeout=60)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout


class World:
    def __init__(self, channels=("example-film",)):
        _n[0] += 1
        self.base = TMP / f"w{_n[0]}"
        self.root = self.base / "factory"
        self.pub = self.root / "publish"
        self.volume = self.base / "Archive"
        self.log = self.base / "archive.log"
        self.needs = self.base / "needs-you"          # CF-0652: the journal of questions
        self.pub.mkdir(parents=True)
        self.volume.mkdir()
        (self.pub / "README.md").write_text(README, encoding="utf-8")
        nyj.add("other", "other:example-note", "Example open question.", directory=self.needs,
                notify=False)
        self.rows = []
        for c in channels:
            (self.pub / c).mkdir()
        self.is_git = False

    def video(self, channel, day, slug, note_link=None, with_note=True, size=40000):
        d = self.pub / channel / day
        d.mkdir(parents=True, exist_ok=True)
        data = hashlib.sha256(f"{channel}/{day}/{slug}".encode()).digest() * (size // 32)
        (d / f"{slug}.mp4").write_bytes(data)
        if with_note:
            (d / f"{slug}.md").write_text(note(slug, note_link), encoding="utf-8")
        self.rows.append({"entry_id": f"{channel}/b/{slug}", "channel": channel,
                          "batch_id": "b", "slug": slug, "verdict": "accepted",
                          "answer": slug, "answered_at": f"2026-09-{len(self.rows) + 10}",
                          "publish_path": pl.rel(channel, day, slug)})
        self.write_log()
        return d

    def write_log(self):
        (self.pub / "acceptance-log.json").write_text(json.dumps(
            {"note": "n", "task": "CF-0328", "acceptances": self.rows},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def make_git(self):
        """The factory root as a git checkout: notes, README and the record
        committed, mp4 ignored - as in the real one."""
        (self.root / ".gitignore").write_text("publish/**/*.mp4\n*.lock\n", encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "test")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.is_git = True
        return self

    def run(self, *extra, today="2026-10-01", mounted=True, volume=None):
        args = ["--root", str(self.root), "--volume", str(volume or self.volume),
                "--log", str(self.log), "--needs-you-dir", str(self.needs),
                "--today", today, "--min-free-gb", "0", "--publish-only"]
        if mounted:
            args.append("--skip-mount-check")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = apm.main(args + list(extra))
        self.out = out.getvalue()
        return code

    def adir(self, channel):
        return self.volume / apm.ARCHIVE_DIR / channel

    def zip(self, channel, month):
        return self.adir(channel) / f"{month}{apm.ZIP}"

    def members(self, channel, month):
        with zipfile.ZipFile(self.zip(channel, month)) as zf:
            return {i.filename: hashlib.sha256(zf.read(i)).hexdigest() for i in zf.infolist()}

    def manifest(self, channel, month):
        p = self.adir(channel) / f"{month}{apm.MANIFEST}"
        return json.loads(p.read_text(encoding="utf-8"))

    def log_text(self):
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def reminders(self, marker=apm.MARKER):
        """The live questions of this marker, as texts."""
        return [q["text"] for q in nyj.live(directory=self.needs)
                if q["key"] == apm.reminder_key(marker)]

    def live_texts(self):
        return " ".join(q["text"] for q in nyj.live(directory=self.needs))

    def acc_rows(self):
        return {r["slug"]: r for r in acceptance.entries(path=self.pub / "acceptance-log.json")}

    def tree(self):
        """Every file under the base with its bytes - to prove nothing moved."""
        return {str(p.relative_to(self.base)): p.read_bytes()
                for p in sorted(self.base.rglob("*")) if p.is_file() and p != self.log
                and not p.name.endswith(".lock") and ".git/" not in str(p)}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sept_world(git_repo=False):
    w = World()
    w.video("example-film", "2026-09-22", "outrider", with_note=False)
    w.video("example-film", "2026-09-29", "wolfhame", note_link="TFPZe_mqoUM")
    w.video("example-film", "2026-09-29", "second")
    w.video("example-film", "2026-10-01", "vanguards", note_link="oo-f6Oiob3M")
    w.video("example-film", "2026-10-07", "delver")
    w.video("example-film", "_queue", "waiting")
    w.rows[-1]["publish_path"] = pl.rel("example-film", pl.QUEUE, "waiting")
    w.write_log()
    return w.make_git() if git_repo else w


SEPT = {"2026-09-22/outrider.mp4", "2026-09-29/wolfhame.mp4", "2026-09-29/wolfhame.md",
        "2026-09-29/second.mp4", "2026-09-29/second.md"}


# --------------------------------------------------------------------------

def test_month_becomes_one_verified_zip():
    w = sept_world()
    src = {f"{p.parent.name}/{p.name}": sha(p)
           for p in (w.pub / "example-film").rglob("2026-09-*/*") if p.is_file()}
    assert set(src) == SEPT
    assert w.run() == 0, w.out
    # One zip per channel and month, holding exactly September, byte for byte.
    assert w.members("example-film", "2026-09") == src
    with zipfile.ZipFile(w.zip("example-film", "2026-09")) as zf:
        assert {i.compress_type for i in zf.infolist()} == {zipfile.ZIP_STORED}
        assert zf.testzip() is None
    if shutil.which("unzip"):       # the Mac's own unzip opens it
        cp = subprocess.run(["unzip", "-tq", str(w.zip("example-film", "2026-09"))],
                            capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0, cp.stdout + cp.stderr
    # No folders on the volume, no half-written files.
    assert not (w.adir("example-film") / "2026-09").exists()
    assert not list(w.volume.rglob("*" + apm.PARTIAL))
    m = w.manifest("example-film", "2026-09")
    assert m["channel"] == "example-film" and m["month"] == "2026-09"
    assert m["zip"] == "2026-09.zip" and m["zip_sha256"] == sha(w.zip("example-film", "2026-09"))
    assert m["zip_size"] == w.zip("example-film", "2026-09").stat().st_size
    rows = {r["path"]: r for r in m["files"]}
    assert set(rows) == SEPT
    assert rows["2026-09-29/wolfhame.mp4"]["sha256"] == src["2026-09-29/wolfhame.mp4"]
    assert rows["2026-09-29/wolfhame.mp4"]["size"] == 40000 // 32 * 32
    assert rows["2026-09-29/wolfhame.mp4"]["day"] == "2026-09-29"
    assert rows["2026-09-29/wolfhame.mp4"]["slug"] == "wolfhame"
    # The link: the note first (over the README), the README row when there is
    # no note, a struck-through link is a deleted upload, and no link is None.
    assert rows["2026-09-29/wolfhame.mp4"]["youtube"] == "https://youtube.com/shorts/TFPZe_mqoUM"
    assert rows["2026-09-22/outrider.mp4"]["youtube"] == "https://youtube.com/shorts/NEWnew1234"
    assert rows["2026-09-29/second.mp4"]["youtube"] is None


def test_month_moves_out_of_publish_with_git_rm_and_one_commit():
    w = sept_world(git_repo=True)
    head = git(w.root, "rev-parse", "HEAD").strip()
    assert w.run() == 0, w.out
    # The day folders are gone - files and folders.
    for day in ("2026-09-22", "2026-09-29"):
        assert not (w.pub / "example-film" / day).exists(), day
    assert git(w.root, "ls-files", "publish/example-film/2026-09-29") == ""
    # README and publish_path point into the zip.
    readme = (w.pub / "README.md").read_text(encoding="utf-8")
    ref = "Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-29"
    assert f"| `{ref}/wolfhame.mp4` |" in readme, readme
    assert f"`{ref}/wolfhame.md`" in readme
    assert "| `example-film/2026-10-01/vanguards.mp4` |" in readme, "October was repointed"
    rows = w.acc_rows()
    assert rows["wolfhame"]["publish_path"] == f"{ref}/wolfhame.mp4"
    assert rows["outrider"]["publish_path"].endswith("2026-09.zip#2026-09-22/outrider.mp4")
    assert rows["vanguards"]["publish_path"] == "publish/example-film/2026-10-01/vanguards.mp4"
    # One commit by the script, tree clean, with an understandable message.
    assert git(w.root, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    msg = git(w.root, "log", "-1", "--format=%B")
    assert msg.startswith("CF-0476: past month moved to the archive: example-film 2026-09"), msg
    assert git(w.root, "status", "--porcelain") == "", git(w.root, "status", "--porcelain")
    changed = set(git(w.root, "show", "--name-only", "--format=", "HEAD").split())
    assert changed == {"publish/README.md", "publish/acceptance-log.json",
                       "publish/example-film/2026-09-29/wolfhame.md",
                       "publish/example-film/2026-09-29/second.md"}, changed
    # "In the archive" is understood: not a problem, not no_verdict; `where` says so.
    # CF-0683: the holds of this tree - without it check() reads the checkout's
    # live publish/publication-holds.json (acceptance.HOLDS)
    res = acceptance.check(path=w.pub / "acceptance-log.json", publish_dir=w.pub,
                           holds_path=w.pub / "publication-holds.json")
    assert res["problems"] == [], res["problems"]
    assert {g["slug"] for g in res["archived"]} == {"outrider", "wolfhame", "second"}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = pl.main(["where", "wolfhame", "--root", str(w.root)])
    assert code == 0 and "в архиве: " + ref + "/wolfhame.mp4" in out.getvalue(), out.getvalue()
    # A second run: no debt, says nothing to the log, changes nothing.
    before, log_before = w.tree(), w.log_text()
    assert w.run() == 0, w.out
    assert w.tree() == before and w.log_text() == log_before
    assert "долга архива нет" in w.out
    assert git(w.root, "rev-list", "--count", f"{head}..HEAD").strip() == "1"


def journal_row(slug, day, vid, **extra):
    row = {"channel": "example-film", "entry_id": f"example-film/b/{slug}", "batch_id": "b",
           "slug": slug, "video_id": vid, "url": f"https://youtube.com/shorts/{vid}",
           "publish_at": None, "publish_tz": None, "publish_day": day,
           "note": pl.rel("example-film", day, slug, ".md"), "source": "studio",
           "recorded_at": "2026-09-30T10:00:00Z"}
    row.update(extra)
    return row


def test_upload_journal_notes_follow_the_month():
    """CF-0594: the `note` of a row in publish/uploads.json follows the month
    into the zip - live, replaced and API-Data-deleted rows alike - through
    agents/publisher/upload_records.py, and the journal is in the one commit."""
    w = sept_world()
    old_wolfhame = journal_row("wolfhame", "2026-09-29", "OLDwerwulf1", removed_at="2026-09-29T12:00:00Z",
                              replaced_by="TFPZe_mqoUM")
    live_wolfhame = journal_row("wolfhame", "2026-09-29", "TFPZe_mqoUM",
                               superseded_video_ids=["OLDwerwulf1"])
    deleted_second = {k: v for k, v in journal_row("second", "2026-09-29", "x").items()
                      if k not in ("video_id", "url", "publish_at", "publish_tz")}
    deleted_second.update(api_data_deleted_at="2026-09-30T00:00:00Z")
    vanguards = journal_row("vanguards", "2026-10-01", "oo-f6Oiob3M")
    no_note = journal_row("outrider", "2026-09-22", "NEWnew12345", note=None)
    (w.pub / "uploads.json").write_text(json.dumps(
        {"note": "n", "task": "CF-0586", "format": 2,
         "uploads": [old_wolfhame, live_wolfhame, vanguards, no_note],
         "api_data_deleted": [deleted_second]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    w.make_git()
    head = git(w.root, "rev-parse", "HEAD").strip()
    assert w.run() == 0, w.out
    ref = "Archive:shorts-content-factory-publish/example-film/2026-09.zip#2026-09-29"
    doc = json.loads((w.pub / "uploads.json").read_text(encoding="utf-8"))
    rows = doc["uploads"]
    assert [r["note"] for r in rows] == [f"{ref}/wolfhame.md", f"{ref}/wolfhame.md",
                                         "publish/example-film/2026-10-01/vanguards.md", None], rows
    assert doc["api_data_deleted"][0]["note"] == f"{ref}/second.md", doc["api_data_deleted"]
    # Only `note` changed in a row; the journal was written by its own writer.
    for before, after in zip((old_wolfhame, live_wolfhame, vanguards, no_note), rows):
        assert {k: v for k, v in after.items() if k != "note"} == \
            {k: v for k, v in before.items() if k != "note"}, after
    assert doc["note"] == upload_records.NOTE and doc["task"] == upload_records.TASK
    # The archive pointer is one the publisher reads back as the same video.
    assert upload_records.placement(rows[1]["note"]) == ("example-film", "2026-09-29", "wolfhame")
    # One commit, with the journal in it; tree clean.
    assert git(w.root, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    changed = set(git(w.root, "show", "--name-only", "--format=", "HEAD").split())
    assert "publish/uploads.json" in changed, changed
    assert git(w.root, "status", "--porcelain") == ""
    assert "uploads.json note → архив 3" in w.log_text(), w.log_text()
    # A second run: nothing to repoint, nothing written.
    before = w.tree()
    assert w.run() == 0, w.out
    assert w.tree() == before


def test_repoint_notes_without_a_journal_writes_nothing():
    w = World()
    p = w.pub / "uploads.json"
    assert upload_records.repoint_notes({"publish/example-film/2026-09-29/a.md": "x"}, path=p) == 0
    assert not p.exists()
    # A journal none of whose notes moved is not rewritten either.
    p.write_text('{"uploads": [{"note": "publish/example-film/2026-10-01/b.md"}]}', encoding="utf-8")
    assert upload_records.repoint_notes({"example-film/2026-09-29/a.md": "x"}, path=p) == 0
    assert p.read_text(encoding="utf-8") == '{"uploads": [{"note": "publish/example-film/2026-10-01/b.md"}]}'


def test_no_commit_flag_and_non_git_root():
    w = sept_world(git_repo=True)
    head = git(w.root, "rev-parse", "HEAD").strip()
    assert w.run("--no-commit") == 0, w.out
    assert git(w.root, "rev-parse", "HEAD").strip() == head
    st = git(w.root, "status", "--porcelain")
    assert "D  publish/example-film/2026-09-29/wolfhame.md" in st, st
    assert " M publish/README.md" in st or "M  publish/README.md" in st, st
    assert "вручную: git commit" in w.out
    # No git at all: the notes are simply deleted, nothing to commit.
    w2 = sept_world()
    assert w2.run() == 0, w2.out
    assert not (w2.pub / "example-film" / "2026-09-29").exists()


def test_foreign_changes_block_the_commit():
    w = sept_world(git_repo=True)
    with (w.pub / "README.md").open("a", encoding="utf-8") as f:
        f.write("\nчужая правка\n")
    head = git(w.root, "rev-parse", "HEAD").strip()
    assert w.run() == 0, w.out
    # The move happened, the commit did not; NEEDS-YOU says so.
    assert not (w.pub / "example-film" / "2026-09-29").exists()
    assert git(w.root, "rev-parse", "HEAD").strip() == head
    assert "чужая правка" in (w.pub / "README.md").read_text(encoding="utf-8")
    lines = w.reminders(apm.COMMIT_MARKER)
    assert len(lines) == 1 and "чужие изменения" in lines[0] and "publish/README.md" in lines[0]


def test_open_batch_defers_the_commit():
    w = sept_world(git_repo=True)
    head = git(w.root, "rev-parse", "HEAD").strip()
    apm.batch_open = lambda root: True
    try:
        assert w.run() == 0, w.out
        assert git(w.root, "rev-parse", "HEAD").strip() == head
        pend = Path(str(w.log) + ".publish.pending.json")
        assert pend.is_file()
        assert any("--commit-pending" in r for r in w.reminders(apm.COMMIT_MARKER))
        # Still open: the next run (any trigger) waits too.
        assert w.run() == 0
        assert git(w.root, "rev-parse", "HEAD").strip() == head
    finally:
        apm.batch_open = REAL_BATCH_OPEN
    # Batch over: the next run makes the commit and drops the reminder.
    assert w.run("--commit-pending") == 0, w.out
    assert git(w.root, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    assert git(w.root, "status", "--porcelain") == ""
    assert not pend.exists() and w.reminders(apm.COMMIT_MARKER) == []
    # A deferred commit whose files changed afterwards is not made.
    w2 = sept_world(git_repo=True)
    head2 = git(w2.root, "rev-parse", "HEAD").strip()
    apm.batch_open = lambda root: True
    try:
        w2.run()
    finally:
        apm.batch_open = REAL_BATCH_OPEN
    with (w2.pub / "README.md").open("a", encoding="utf-8") as f:
        f.write("\nпосле архива\n")
    assert w2.run() == 0, w2.out
    assert git(w2.root, "rev-parse", "HEAD").strip() == head2
    assert any("после архива менялись" in r for r in w2.reminders(apm.COMMIT_MARKER))


def test_real_batch_check_sees_no_batch_in_an_empty_root():
    w = World()
    assert REAL_BATCH_OPEN(w.root) is False


def test_current_month_and_queue_untouched():
    w = sept_world()
    assert w.run() == 0, w.out
    for day, slug in (("2026-10-01", "vanguards"), ("2026-10-07", "delver"),
                      ("_queue", "waiting")):
        assert (w.pub / "example-film" / day / f"{slug}.mp4").exists(), slug
        assert (w.pub / "example-film" / day / f"{slug}.md").exists(), slug
    assert not w.zip("example-film", "2026-10").exists()
    assert not any("2026-10" in n or "waiting" in n for n in w.members("example-film", "2026-09"))
    assert w.acc_rows()["waiting"]["publish_path"] == "publish/example-film/_queue/waiting.mp4"
    # On the last day of September, September itself is still the current month.
    w2 = sept_world()
    before = w2.tree()
    assert w2.run(today="2026-09-30") == 0, w2.out
    assert w2.tree() == before
    assert "долга архива нет" in w2.out and w2.log_text() == ""


def test_failed_verification_deletes_nothing():
    w = sept_world(git_repo=True)
    head = git(w.root, "rev-parse", "HEAD").strip()
    real = apm.build_zip
    victim = (w.pub / "example-film" / "2026-09-29" / "wolfhame.mp4").read_bytes()[:64]

    def corrupt(zpath, members):
        tmp = real(zpath, members)
        data = bytearray(tmp.read_bytes())
        at = data.find(victim)
        assert at >= 0
        data[at:at + 4] = b"XXXX"           # same size, other bytes
        tmp.write_bytes(bytes(data))
        return tmp

    before = w.tree()
    apm.build_zip = corrupt
    try:
        assert w.run() == 1, w.out
    finally:
        apm.build_zip = real
    after = w.tree()
    assert {k: v for k, v in after.items() if k != QF} == \
        {k: v for k, v in before.items() if k != QF}, "something moved"
    assert not w.zip("example-film", "2026-09").exists()
    assert git(w.root, "rev-parse", "HEAD").strip() == head
    assert "сверка не сошлась" in w.log_text()
    assert any("сверка архива не сошлась" in r for r in w.reminders()), w.reminders()
    # The next run builds it right and finishes; the reminder goes.
    assert w.run() == 0, w.out
    assert not (w.pub / "example-film" / "2026-09-29").exists()
    assert w.reminders() == [], "the reminder outlived the debt"


def test_late_file_joins_the_months_zip_and_conflict_touches_nothing():
    w = sept_world()
    assert w.run() == 0, w.out
    first = w.members("example-film", "2026-09")
    w.video("example-film", "2026-09-30", "late")
    assert w.run() == 0, w.out
    now = w.members("example-film", "2026-09")
    assert set(now) == set(first) | {"2026-09-30/late.mp4", "2026-09-30/late.md"}
    assert all(now[k] == v for k, v in first.items())
    # Same name, other bytes: a conflict - nothing is touched.
    d = w.video("example-film", "2026-09-30", "late", size=64000)
    before = w.tree()
    assert w.run() == 1, w.out
    assert (d / "late.mp4").exists()
    assert {k: v for k, v in w.tree().items() if k != QF} == \
        {k: v for k, v in before.items() if k != QF}
    assert "разные файлы с одним именем" in w.log_text()


def test_not_mounted_does_nothing_and_reminds():
    w = sept_world()
    before = w.tree()
    # A plain folder at the volume's path is not a volume.
    assert w.run(mounted=False) == 0, w.out
    assert w.tree() == {**before, QF: (w.needs / nyj.JOURNAL).read_bytes()}
    assert not (w.volume / apm.ARCHIVE_DIR).exists()
    assert "не смонтирован" in w.log_text()
    lines = w.reminders()
    assert len(lines) == 1, lines
    assert "подключите Archive: долг архива publish example-film 2026-09" in lines[0]
    # Same day again (another volume mounted): no second line, no log line.
    log_before = w.log_text()
    w.run(mounted=False)
    assert w.reminders() == lines and w.log_text() == log_before
    w.run(mounted=False, today="2026-10-02")
    again = w.reminders()
    assert again == lines, again
    # No folder at all: the same.
    assert w.run(volume=w.base / "nowhere", mounted=False, today="2026-10-02") == 0
    assert len(w.reminders()) == 1
    for p in (w.pub / "example-film").rglob("*.mp4"):
        assert p.exists()
    # Plugged in: archived, and the reminder goes away.
    assert w.run(today="2026-10-03") == 0, w.out
    assert w.reminders() == []
    assert "Юрисдикция выплат" in w.live_texts()


def test_low_space_does_nothing():
    w = sept_world()
    before = w.tree()
    assert w.run("--min-free-gb", "1000000000") == 1, w.out
    after = w.tree()
    assert {k: v for k, v in after.items() if k != QF} == \
        {k: v for k, v in before.items() if k != QF}
    assert "мало места" in w.log_text()
    assert any("мало места на Archive" in r for r in w.reminders())


def test_two_channels_do_not_mix():
    w = World(channels=("alpha", "beta"))
    w.video("alpha", "2026-09-10", "same-slug")
    w.video("beta", "2026-09-10", "same-slug")
    w.video("beta", "2026-08-31", "older")
    a_sha = sha(w.pub / "alpha" / "2026-09-10" / "same-slug.mp4")
    b_sha = sha(w.pub / "beta" / "2026-09-10" / "same-slug.mp4")
    assert a_sha != b_sha
    assert w.run() == 0, w.out
    assert w.members("alpha", "2026-09")["2026-09-10/same-slug.mp4"] == a_sha
    assert w.members("beta", "2026-09")["2026-09-10/same-slug.mp4"] == b_sha
    ma, mb = w.manifest("alpha", "2026-09"), w.manifest("beta", "2026-09")
    assert ma["channel"] == "alpha" and mb["channel"] == "beta"
    # Older months are debt too, each in its own zip; alpha has no August.
    assert set(w.members("beta", "2026-08")) == {"2026-08-31/older.mp4", "2026-08-31/older.md"}
    assert not w.zip("alpha", "2026-08").exists()
    refs = {(r["channel"], r["slug"]): r["publish_path"] for r in
            acceptance.entries(path=w.pub / "acceptance-log.json")}
    assert refs[("alpha", "same-slug")].startswith(
        "Archive:shorts-content-factory-publish/alpha/2026-09.zip#")
    assert refs[("beta", "same-slug")].startswith(
        "Archive:shorts-content-factory-publish/beta/2026-09.zip#")


def test_dry_run_changes_nothing():
    w = sept_world(git_repo=True)
    before = w.tree()
    assert w.run("--dry-run") == 0, w.out
    assert w.tree() == before
    assert git(w.root, "status", "--porcelain") == ""
    assert not w.log.exists(), "a dry run wrote the log"
    assert "план example-film 2026-09: соберу" in w.out, w.out
    assert "mp4 3 удалить, заметок 2 git rm, папок дней 2 убрать" in w.out, w.out
    for later in ("vanguards", "delver", "waiting", "_queue"):
        assert later not in w.out, (later, w.out)


# --------------------------------------------------------------------------
# the folder form of 2026-10-01 -> one zip
# --------------------------------------------------------------------------

def legacy_world():
    """September as the first live run left it: every file on the volume in
    `<channel>/2026-09/<day>/` with MANIFEST.json, the mp4 gone from the Mac,
    the notes still in publish/ (and in git), one empty day folder."""
    w = sept_world()
    mdir = w.adir("example-film") / "2026-09"
    rows = []
    for p in sorted((w.pub / "example-film").rglob("2026-09-*/*")):
        dest = mdir / p.parent.name / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        rows.append({"day": p.parent.name, "release_day": p.parent.name, "slug": p.stem,
                     "file": p.name, "kind": p.suffix[1:], "size": p.stat().st_size,
                     "sha256": sha(p), "path": f"{p.parent.name}/{p.name}",
                     "youtube": "https://youtube.com/shorts/LEGACY0001" if p.stem == "outrider"
                     else None, "archived_at": "2026-10-01T23:09:59+03:00"})
        if p.suffix == ".mp4":
            p.unlink()
    (mdir / ".DS_Store").write_bytes(b"finder")
    (mdir / "2026-09-29" / ".DS_Store").write_bytes(b"finder")
    (mdir / apm.LEGACY_MANIFEST).write_text(json.dumps(
        {"channel": "example-film", "month": "2026-09", "files": rows}), encoding="utf-8")
    return w.make_git(), mdir


def test_regular_run_leaves_a_legacy_month_to_repack():
    w, mdir = legacy_world()
    before = w.tree()
    assert w.run() == 0, w.out
    assert w.tree() == {**before, QF: (w.needs / nyj.JOURNAL).read_bytes()}
    assert "--repack-legacy" in w.log_text()
    assert any("--repack-legacy --apply" in r for r in w.reminders())


def test_repack_legacy_dry_then_apply():
    w, mdir = legacy_world()
    head = git(w.root, "rev-parse", "HEAD").strip()
    want = {str(p.relative_to(mdir)): sha(p) for p in mdir.rglob("*")
            if p.is_file() and p.name not in (".DS_Store", apm.LEGACY_MANIFEST)}
    assert set(want) == SEPT
    before = w.tree()
    assert w.run("--repack-legacy") == 0, w.out
    assert w.tree() == before and not w.log.exists(), "the dry run changed something"
    assert "сухой прогон example-film 2026-09" in w.out, w.out
    assert "на томе после сверки удалить" in w.out and "git rm" in w.out, w.out
    assert w.run("--repack-legacy", "--apply") == 0, w.out
    assert w.members("example-film", "2026-09") == want
    assert not mdir.exists(), "the folder form stayed on the volume"
    assert not (w.pub / "example-film" / "2026-09-22").exists()
    assert not (w.pub / "example-film" / "2026-09-29").exists()
    assert (w.pub / "example-film" / "2026-10-01" / "vanguards.md").exists()
    rows = {r["path"]: r for r in w.manifest("example-film", "2026-09")["files"]}
    assert rows["2026-09-22/outrider.mp4"]["youtube"] == "https://youtube.com/shorts/LEGACY0001"
    assert rows["2026-09-22/outrider.mp4"]["archived_at"] == "2026-10-01T23:09:59+03:00"
    assert w.acc_rows()["wolfhame"]["publish_path"] == (
        "Archive:shorts-content-factory-publish/example-film/2026-09.zip"
        "#2026-09-29/wolfhame.mp4")
    assert git(w.root, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    assert git(w.root, "status", "--porcelain") == ""
    assert "folder-form month repacked" in git(w.root, "log", "-1", "--format=%s")
    # Nothing left to repack; the regular run has no debt.
    assert w.run("--repack-legacy", "--apply") == 0
    assert "нет месяцев в старой форме" in w.out
    assert w.run() == 0 and "долга архива нет" in w.out


def test_repack_legacy_mismatch_touches_nothing():
    w, mdir = legacy_world()
    with open(mdir / "2026-09-29" / "wolfhame.mp4", "r+b") as f:
        f.write(b"XXXX")
    before = w.tree()
    assert w.run("--repack-legacy", "--apply") == 1, w.out
    assert w.tree() == before
    assert not w.zip("example-film", "2026-09").exists()
    assert "не совпадает с MANIFEST.json" in w.out, w.out
    # A local note that differs from its archived copy is a conflict, too.
    w2, mdir2 = legacy_world()
    (w2.pub / "example-film" / "2026-09-29" / "wolfhame.md").write_text("edited", encoding="utf-8")
    before = w2.tree()
    assert w2.run("--repack-legacy", "--apply") == 1, w2.out
    assert w2.tree() == before and mdir2.is_dir()


# --------------------------------------------------------------------------

def test_plist_runs_on_the_first_and_on_mount():
    p = ROOT / "scripts" / "launchd" / "com.example-film.archive-publish-month.plist"
    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "com.example-film.archive-publish-month"
    assert any(a.endswith("scripts/archive_publish_month.py") for a in d["ProgramArguments"])
    cal = d["StartCalendarInterval"]
    assert isinstance(cal, dict), "one calendar entry: the 1st of the month"
    assert cal == {"Day": 1, "Hour": 10, "Minute": 0}, (
        "the job runs once a month - a calendar entry without Day would run it daily")
    assert d["StartOnMount"] is True, "plugging Archive in must pay a debt the 1st could not"
    assert "StartInterval" not in d and "RunAtLoad" not in d


# --------------------------------------------------------------------------
# CF-0720: --json (the dry run as a document, the real run the same), --by/--via

def _doc(w, *extra, **kw):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = w.run(*extra, **kw)
    return code, json.loads(w.out), err.getvalue()


def test_cf0720_dry_run_json_is_the_plan_and_changes_nothing():
    w = sept_world(git_repo=True)
    head = git(w.root, "rev-parse", "HEAD").strip()
    before = sorted(str(p.relative_to(w.root)) for p in w.root.rglob("*") if ".git" not in p.parts)
    code, doc, err = _doc(w, "--dry-run", "--json", "--by", "user", "--via", "center")
    assert code == 0 and doc["exit_code"] == 0, (code, doc)
    assert sorted(str(p.relative_to(w.root)) for p in w.root.rglob("*")
                  if ".git" not in p.parts) == before
    assert git(w.root, "rev-parse", "HEAD").strip() == head and not w.log.exists()
    assert doc["dry_run"] is True and doc["mode"] == "month" and doc["mounted"] is True
    assert doc["by"] == "user" and doc["via"] == "center" and doc["today"] == "2026-10-01"
    assert doc["debt"] == [{"channel": "example-film", "month": "2026-09",
                            "days": ["2026-09-22", "2026-09-29"], "files": 5}], doc["debt"]
    (job,) = doc["jobs"]
    assert job["action"] == "create" and job["members"] == 5 and job["status"] == "planned"
    assert job["zip"].endswith("example-film/2026-09.zip") and job["old_members"] == 0
    ops = {(x["path"], x["op"]) for x in job["from_publish"]}
    assert ("publish/example-film/2026-09-29/wolfhame.md", "git rm") in ops, ops
    assert ("publish/example-film/2026-09-22/outrider.mp4", "delete") in ops, ops
    assert job["day_dirs"] == ["publish/example-film/2026-09-22", "publish/example-film/2026-09-29"]
    assert doc["need_bytes"] == job["bytes"] and doc["enough_space"] is True
    assert doc["commit"] is None and doc["monthly"] is None
    assert doc["lines"] and any("сухой прогон" in ln for ln in doc["lines"]), doc["lines"]
    assert "сухой прогон" in err                    # the lines go to stderr under --json


def test_cf0720_real_run_json_has_the_same_shape_and_by_via_in_the_commit():
    w = sept_world(git_repo=True)
    code, dry, _ = _doc(w, "--dry-run", "--json", "--by", "user", "--via", "center")
    code, doc, _ = _doc(w, "--json", "--by", "user", "--via", "center")
    assert code == 0, doc
    assert set(doc) == set(dry) and doc["dry_run"] is False
    assert [set(j) for j in doc["jobs"]] == [set(j) for j in dry["jobs"]]
    (job,) = doc["jobs"]
    assert job["status"] == "moved" and job["members"] == dry["jobs"][0]["members"]
    assert doc["commit"]["by"] == "user" and doc["commit"]["via"] == "center"
    assert doc["commit"]["message"].startswith("CF-0476: past month moved to the archive")
    msg = git(w.root, "log", "-1", "--format=%B")
    assert "Requested-by: user via center" in msg, msg
    assert "кто: by user, via center" in w.log.read_text()
    assert not (w.pub / "example-film" / "2026-09-29").exists()


def test_cf0720_unmounted_dry_run_json_names_the_debt_and_a_bad_who_is_refused():
    w = sept_world()
    code, doc, _ = _doc(w, "--dry-run", "--json", mounted=False,
                        volume=w.base / "not-mounted")
    assert code == 0 and doc["mounted"] is False, doc
    (job,) = doc["jobs"]
    assert job["action"] is None and job["status"] == "planned" and len(job["from_publish"]) == 5
    for bad in (["--by", ""], ["--via", "x" * 41]):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                w.run("--dry-run", "--json", *bad)
        except SystemExit as e:
            assert e.code == 2 and ("by=" in err.getvalue() or "via=" in err.getvalue())
        else:
            raise AssertionError(f"{bad} was taken")


def test_cf0720_without_json_the_lines_are_as_before():
    w = sept_world()
    assert w.run("--dry-run") == 0
    assert not w.out.lstrip().startswith("{") and "сухой прогон" in w.out, w.out


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

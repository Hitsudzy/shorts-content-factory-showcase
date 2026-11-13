#!/usr/bin/env python3
"""CF-0760: the meme desk's delta for the command center 0.4.1 (CC-0075,
CC-0076) - plans with no network, the URL boundary, limits, `by`/`via` and the
jobs journal, the index race, crashes in the middle of a pass, the venv of a
worktree, the video cache and the progress callable.

Temp banks only (test_meme_desk_jobs.world); no network - the download, yt-dlp,
ffmpeg's children, Vision and the embedding are stand-ins; a git repo with a
worktree is made here for the venv lookup.
"""
import contextlib
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import inserts_lib as lib  # noqa: E402
import meme_desk as desk  # noqa: E402
from test_meme_cutout import W, H, disk  # noqa: E402
from test_meme_desk_jobs import (FakeVision, png_bytes, quiet, refused,  # noqa: E402
                                 snapshot, stand_ins, world)


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


# --------------------------------------------------------------------------
# 7. the venv of a worktree
# --------------------------------------------------------------------------

def test_a_worktree_finds_the_main_checkouts_venv():
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / "main"
        main.mkdir()
        git("init", "-q", cwd=main)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty",
            "-m", "x", cwd=main)
        git("worktree", "add", "-q", str(main / ".worktrees" / "release-x"), cwd=main)
        wt = main / ".worktrees" / "release-x"
        rel = Path("agents") / "footage-indexer" / ".venv" / "bin" / "yt-dlp"
        (main / rel).parent.mkdir(parents=True)
        (main / rel).write_text("#!/bin/sh\n")
        assert desk.venv_path(rel, wt).resolve() == (main / rel).resolve()
        (wt / rel).parent.mkdir(parents=True)
        (wt / rel).write_text("#!/bin/sh\n")
        assert desk.venv_path(rel, wt) == wt / rel, "the worktree's own venv comes first"
        # no git at all: the checkout's own path, never an exception
        lone = Path(tmp) / "lone"
        lone.mkdir()
        assert desk.venv_path(rel, lone) == lone / rel
    # the three venv users go through the lookup
    for fn in (desk.indexer_python, desk.indexer_ytdlp, desk.vision_python):
        assert isinstance(fn(), Path)



# --------------------------------------------------------------------------
# stand-ins for the children: yt-dlp, ffmpeg, ffprobe, the sheet script
# --------------------------------------------------------------------------

class FakeRun:
    """desk.run with no child: yt-dlp writes a fake clip, ffmpeg a fake GIF or
    `frames` sheet frames, ffprobe answers 640x480, the sheet script writes
    the sheet. `calls` - the tools in order."""

    def __init__(self, frames=3):
        self.calls, self.frames = [], frames

    def __call__(self, cmd, *, timeout=desk.MEDIA_TIMEOUT_SECONDS):
        assert timeout and timeout > 0
        tool = Path(cmd[0]).name
        self.calls.append(tool)
        if tool == "yt-dlp":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"fake mp4")
        elif tool == "ffprobe":
            return "640,480\n"
        elif tool == "ffmpeg":
            out = cmd[-1]
            if "%04d" in out:
                n = self.frames
                if "-frames:v" in cmd:
                    n = min(n, int(cmd[cmd.index("-frames:v") + 1]))
                for i in range(n):
                    Path(out.replace("%04d", f"{i + 1:04d}")).write_bytes(b"jpg")
            else:
                Path(out).write_bytes(b"GIF89a fake")
        elif "-c" in cmd:
            Path(cmd[cmd.index("-c") + 3]).write_bytes(b"sheet")
        else:
            raise AssertionError(f"unexpected child {cmd}")
        return ""


@contextlib.contextmanager
def children(tmp, frames=3):
    """stand_ins plus FakeRun, no scene detection and a yt-dlp that is there
    (in a temp dir of its own: the test's tree stays as the test made it)."""
    with tempfile.TemporaryDirectory() as bin_:
        ytdlp = Path(bin_) / "yt-dlp"
        ytdlp.write_text("")
        fake = FakeRun(frames)
        with stand_ins(run=fake, scene_cuts=lambda path, start=0.0, end=None: [],
                       indexer_ytdlp=lambda: ytdlp,
                       indexer_python=lambda: Path(sys.executable)) as c:
            c["run"] = fake
            yield c


# --------------------------------------------------------------------------
# 2. URLs are http(s) only; a local video only on local=True, inside the bank
# --------------------------------------------------------------------------

def test_urls_are_http_only():
    for bad in ("file:///etc/passwd", "/etc/x.png", "ftp://x.org/a.png", "http://",
                "javascript:alert(1)", "https://x.org/a b.png", "", None, 42):
        try:
            desk.check_url(bad)
        except desk.MemeDeskError as e:
            assert e.code == "bad_url" and e.text and e.en, bad
        else:
            raise AssertionError(f"{bad!r} passed as a URL")
    assert desk.check_url("https://i.imgflip.com/a.png") == "https://i.imgflip.com/a.png"
    assert desk.check_url("HTTP://x.org/v") == "HTTP://x.org/v"
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = dict(channel="tech", repo=repo, root=inserts)
        before = snapshot(t)
        fetched = []
        with stand_ins(_fetch=lambda url: fetched.append(url)):
            refused("bad_url", desk.add_image_entry, "ok-id", "file:///etc/a.png",
                    "https://x.org/a", "d", "a", **kw)
            refused("bad_url", desk.add_image_entry, "ok-id", str(t / "outside.png"),
                    "https://x.org/a", "d", "a", **kw)
        assert fetched == []
        # the download itself refuses a non-http URL before urlopen
        with stand_ins():
            refused("bad_url", desk._fetch, "file:///etc/passwd")
        assert snapshot(t) == before


def test_a_local_video_only_on_local_true_and_inside_the_bank():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        tech = inserts / "memes-tech"
        (t / "clip.mp4").write_bytes(b"outside")
        (tech / "_desk" / "uploads").mkdir(parents=True)
        (tech / "_desk" / "uploads" / "in.mp4").write_bytes(b"inside")
        kw = dict(channel="tech", repo=repo, root=inserts)
        gif_args = ("new-gif", None, 0.5, 1.5, "a gif", ["a"])
        before = snapshot(t)
        with children(tmp) as calls:
            for video, local, code in ((str(t / "clip.mp4"), False, "bad_url"),
                                       ("file://" + str(t / "clip.mp4"), False, "bad_url"),
                                       (str(t / "clip.mp4"), True, "outside_bank"),
                                       ("../../clip.mp4", True, "outside_bank"),
                                       ("_desk/uploads/none.mp4", True, "video_failed")):
                a = list(gif_args)
                a[1] = video
                refused(code, desk.add_gif_entry, *a, source_url="https://x.org/v",
                        local=local, **kw)
                refused(code, desk.make_sheet, video, 0, 4, 1, local=local, **kw)
            assert calls["run"].calls == [], "a refused video started a child"
        assert snapshot(t) == before
        # inside the bank, by name or by absolute path
        for video in ("_desk/uploads/in.mp4", str(tech / "_desk" / "uploads" / "in.mp4")):
            src = desk.video_source(video, tech, True, repo)
            assert src["will_fetch"] == "local" and Path(src["path"]).read_bytes() == b"inside"


# --------------------------------------------------------------------------
# 3. limits: a still's body, a sheet's frames
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, size, length=None):
        self.size, self.headers = size, ({"Content-Length": str(length)} if length else {})
        self.read_with = None

    def read(self, n=-1):
        self.read_with = n
        return b"x" * (self.size if n < 0 else min(n, self.size))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_still_over_25_mb_is_not_downloaded():
    import urllib.request
    ceiling = desk.MAX_IMAGE_BYTES
    assert ceiling == 25 * 1024 * 1024
    saved = urllib.request.urlopen
    try:
        for resp in (FakeResponse(ceiling + 10), FakeResponse(10, length=ceiling + 1)):
            urllib.request.urlopen = lambda req, timeout=None, r=resp: r
            refused("download_failed", desk._fetch, "https://x.org/huge.png")
        ok = FakeResponse(1000)
        urllib.request.urlopen = lambda req, timeout=None: ok
        assert desk._fetch("https://x.org/a.png") == b"x" * 1000
        assert ok.read_with == ceiling + 1, "the body is read with a bound"
    finally:
        urllib.request.urlopen = saved


def test_a_sheet_over_300_frames_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = dict(channel="tech", repo=repo, root=inserts)
        assert desk.MAX_SHEET_FRAMES == 300
        assert desk.sheet_frames(0, 600, 2) == 300 and desk.sheet_frames(0, None, 2) is None
        before = snapshot(t)
        with children(tmp) as calls:
            refused("too_many_frames", desk.make_sheet, "https://x.org/v", 0, 3600, 1, **kw)
            refused("too_many_frames", desk.plan_sheet, "https://x.org/v", 0, 3600, 1, **kw) \
                if hasattr(desk, "plan_sheet") else None
            assert calls["run"].calls == [], "a sheet known to be too long fetched the video"
        assert snapshot(t) == before
        # an open end: counted after extraction, one frame past the ceiling is enough
        with children(tmp, frames=5000) as calls:
            refused("too_many_frames", desk.make_sheet, "https://x.org/v", 0, None, 1, **kw)
        assert calls["run"].calls == ["yt-dlp", "ffmpeg"]
        assert not (inserts / "memes-tech" / "_desk" / "sheets" / "sheet.jpg").exists()
        with children(tmp, frames=40) as calls:
            r = quiet(desk.make_sheet, "https://x.org/v", 0, None, 1, **kw)
        assert Path(r["sheet"]).is_file()


# --------------------------------------------------------------------------
# 8. the video cache: one URL is fetched once
# --------------------------------------------------------------------------

def test_one_video_is_fetched_once_for_the_sheet_and_the_gif():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = dict(channel="tech", repo=repo, root=inserts)
        url = "https://www.youtube.com/watch?v=abc"
        cache = (inserts / "memes-tech" / "_desk" / "clips"
                 / (hashlib.sha1(url.encode()).hexdigest() + ".mp4"))
        with children(tmp) as calls:
            quiet(desk.make_sheet, url, 0, 10, 2, **kw)
            assert cache.read_bytes() == b"fake mp4"
            assert not list(cache.parent.glob("*.part*"))
            r = quiet(desk.add_gif_entry, "from-url", url, 1, 2, "a gif", "a, b", **kw)
            quiet(desk.make_sheet, url, 0, 10, 2, "again.jpg", **kw)
        assert calls["run"].calls.count("yt-dlp") == 1, calls["run"].calls
        assert r["entry"]["source_url"] == url and r["entry"]["cutout"] is False
        other = desk.video_source("https://x.org/other", inserts / "memes-tech")
        assert other["cache"] != cache and not other["cached"]
        assert desk.video_source(url, inserts / "memes-tech")["cached"] is True


# --------------------------------------------------------------------------
# 6. a crash in the middle of a pass; 5. the index moving under it
# --------------------------------------------------------------------------

def index_of(inserts, bank="memes-tech"):
    return {e["id"]: e for e in lib.load_index("meme", inserts, bank)["entries"]}


def edit_index(inserts, fn, bank="memes-tech"):
    """What apply_marks / accept_candidates do meanwhile: read, change, save."""
    idx = lib.load_index("meme", inserts, bank)
    fn(idx)
    lib.save_index(idx, "meme", inserts, bank)


class CrashVision(FakeVision):
    """FakeVision whose run on `bad` raises `exc` (after `before(…)`, if any)."""

    def __init__(self, masks, bad=None, exc=None, before=None):
        super().__init__(masks)
        self.bad, self.exc, self.before = bad, exc, before

    def __call__(self, src, out_png):
        if self.before and Path(src).name in self.before:
            self.before.pop(Path(src).name)()
        if Path(src).name == self.bad:
            self.calls.append(Path(src).name)
            raise self.exc
        return super().__call__(src, out_png)


def test_a_vision_crash_is_a_refused_cut_and_the_pass_goes_on():
    good = {"cut-good.png": disk(), "cut-bad.png": disk()}
    for exc, word in ((subprocess.TimeoutExpired(["python"], 180), "TimeoutExpired"),
                      (json.JSONDecodeError("Expecting value", "", 0), "JSONDecodeError"),
                      (KeyError("size"), "KeyError")):
        with tempfile.TemporaryDirectory() as tmp:
            t, repo, inserts = world(tmp, escape=False)
            with stand_ins(run_vision=CrashVision(good, "cut-good.png", exc)):
                r = quiet(desk.cutout_entries, "tech", repo=repo, root=inserts)
            assert [x["id"] for x in r["made"]] == ["cut-bad"], r
            assert [x["id"] for x in r["refused"]] == ["cut-good"], r
            assert word in r["refused"][0]["en"] and r["written"] is True
            assert r["refused"][0]["reason"] == "распознавание фигуры не сработало на этом файле"
            got = index_of(inserts)
            assert got["cut-good"]["cutout_asset"]["refused"].startswith("Vision failed")
            assert got["cut-bad"]["cutout_asset"]["file"] == "cut-bad.cutout.png"
            assert not list((inserts / "memes-tech").glob("*.part.png"))


def test_a_pass_that_breaks_off_still_writes_what_it_cut():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp, escape=False)
        # the index lists cut-bad first: it is cut, then cut-good's run is interrupted
        fake = CrashVision({"cut-bad.png": disk()}, "cut-good.png", KeyboardInterrupt())
        with stand_ins(run_vision=fake):
            try:
                desk.cutout_entries("tech", repo=repo, root=inserts)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("the interrupt was swallowed")
        got = index_of(inserts)
        assert got["cut-bad"]["cutout_asset"]["file"] == "cut-bad.cutout.png", \
            "the cut made before the break was not recorded"
        assert "cutout_asset" not in got["cut-good"]
    # the trim: a cut that fails is `left`, the file untouched, the pass goes on
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        tech = inserts / "memes-tech"
        before = (tech / "banded.png").read_bytes()

        def broken(src, dst, m):
            Path(dst).write_bytes(b"half")
            raise OSError("disk full")

        with stand_ins(trim_blank_file=broken):
            r = quiet(desk.trim_blank_entries, "tech", repo=repo, root=inserts)
        assert r["changed"] == [] and r["trim"] == [], r
        left = {x["id"]: x["en"] for x in r["left"]}
        assert "disk full" in left["banded"], left
        assert (tech / "banded.png").read_bytes() == before
        assert not (tech / "banded.png.part").exists()
        assert "notes" not in index_of(inserts)["banded"]


def test_marks_applied_during_the_pass_are_kept():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp, escape=False)

        def mark():
            edit_index(inserts, lambda idx: [e.update(notes="the user's note")
                                             for e in idx["entries"] if e["id"] == "plain"])

        fake = CrashVision({"cut-good.png": disk(), "cut-bad.png": disk()},
                           before={"cut-good.png": mark})
        with stand_ins(run_vision=fake):
            r = quiet(desk.cutout_entries, "tech", repo=repo, root=inserts)
        got = index_of(inserts)
        assert got["plain"]["notes"] == "the user's note"
        assert got["cut-good"]["cutout_asset"]["file"] and got["cut-bad"]["cutout_asset"]["file"]
        assert r["written"] is True


def test_an_entry_gone_during_the_pass_is_index_changed():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp, escape=False)
        tech = inserts / "memes-tech"

        def drop():
            edit_index(inserts, lambda idx: idx.update(
                entries=[e for e in idx["entries"] if e["id"] != "cut-good"]))

        fake = CrashVision({"cut-good.png": disk(), "cut-bad.png": disk()},
                           before={"cut-bad.png": drop})
        with stand_ins(run_vision=fake):
            e = refused("index_changed", desk.cutout_entries, "tech", by="user", via="center",
                        repo=repo, root=inserts)
        assert "cut-good" in e.text
        got = index_of(inserts)
        assert "cut-good" not in got and got["cut-bad"]["cutout_asset"]["file"]
        assert not (tech / "cut-good.cutout.png").exists(), "the cut of a gone entry was kept"
        rows = [json.loads(x) for x in (tech / "_desk" / "jobs.jsonl").read_text().splitlines()]
        assert rows[-1]["ids"] == ["cut-bad"] and rows[-1]["kind"] == "cutout"
    # the trim: an entry removed while it is cut
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        real = desk.trim_blank_file

        def trim_and_drop(src, dst, m):
            edit_index(inserts, lambda idx: idx.update(
                entries=[e for e in idx["entries"] if e["id"] != "banded"]))
            real(src, dst, m)

        with stand_ins(trim_blank_file=trim_and_drop):
            refused("index_changed", desk.trim_blank_entries, "tech", repo=repo, root=inserts)
        assert "banded" not in index_of(inserts)


# --------------------------------------------------------------------------
# 4. by / via: the stamp in notes and the jobs journal
# --------------------------------------------------------------------------

def journal(inserts, bank="memes-tech"):
    path = inserts / bank / "_desk" / "jobs.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def test_by_and_via_stamp_the_notes_and_the_jobs_journal():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(repo=repo, root=inserts)
        fake = FakeVision({"cut-good.png": disk(), "cut-bad.png": ["1" * W] * H})
        with stand_ins(run_vision=fake):
            for who in ({"by": "a\nb"}, {"via": "x" * 41}, {"by": ""}, {"via": 5}):
                refused("bad_who", desk.cutout_entries, "tech", **who, **kw)
                refused("bad_who", desk.trim_blank_entries, "tech", **who, **kw)
            assert journal(inserts) == []
            quiet(desk.cutout_entries, "tech", by="user", via="center", **kw)
            quiet(desk.cutout_entries, "tech", ids=["cut-good"], force=True, by="user",
                  via="center", **kw)
        got = index_of(inserts)
        for i in ("cut-good", "cut-bad"):
            stamps = [x for x in got[i]["notes"].split("; ") if x.startswith("cutout ")]
            assert len(stamps) == 1 and stamps[0].endswith("(by user, via center)"), got[i]
        rows = journal(inserts)
        assert [(r["kind"], sorted(r["ids"]), r["by"], r["via"]) for r in rows] == \
            [("cutout", ["cut-bad", "cut-good"], "user", "center"),
             ("cutout", ["cut-good"], "user", "center")], rows
        assert set(rows[0]) == {"at", "by", "via", "kind", "ids"}
        with stand_ins():
            quiet(desk.trim_blank_entries, "tech", via="center", **kw)
            quiet(desk.trim_blank_entries, "tech", dry_run=True, by="user", **kw)
        notes = index_of(inserts)["banded"]["notes"]
        assert "CF-0534" in notes and notes.endswith("(via center)") and "trim_blank 20" in notes
        assert journal(inserts)[-1] == {**journal(inserts)[-1], "kind": "trim_blank",
                                        "ids": ["banded"], "by": None, "via": "center"}
        assert len(journal(inserts)) == 3, "a dry run wrote a journal row"
        # no by/via: the notes stay as they were (the terminal's runs)
        assert desk._stamp("a", "cutout", None, None) == "a"


# --------------------------------------------------------------------------
# 9. progress
# --------------------------------------------------------------------------

def test_progress_of_the_cutout_and_the_trim_and_a_callback_that_raises():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp, escape=False)
        kw = dict(repo=repo, root=inserts)
        seen = []
        fake = FakeVision({"cut-good.png": disk(), "cut-bad.png": disk()})
        with stand_ins(run_vision=fake):
            refused("bad_progress", desk.cutout_entries, "tech", progress=5, **kw)
            quiet(desk.cutout_entries, "tech", progress=lambda *a: seen.append(a), **kw)
        assert seen == [("cutout", 0, 2, ""), ("cutout", 1, 2, "cut-bad"),
                        ("cutout", 2, 2, "cut-good")], seen

        def boom(*a):
            raise RuntimeError("the job table is gone")

        with stand_ins(run_vision=fake):
            r = quiet(desk.cutout_entries, "tech", force=True, progress=boom, **kw)
        assert len(r["made"]) == 2, "a raising callback stopped the work"
        seen.clear()
        with stand_ins():
            r = quiet(desk.trim_blank_entries, "tech", progress=lambda *a: seen.append(a), **kw)
            quiet(desk.trim_blank_entries, "tech", id="banded-small", progress=boom, **kw)
        n = len(index_of(inserts))
        assert seen[0] == ("trim", 0, n, "") and seen[n] == ("trim", n, n, seen[n][3])
        assert [x[1] for x in seen[:n + 1]] == list(range(n + 1))
        assert seen[-1][0] == "embedding" and r["changed"] == ["banded"]


# --------------------------------------------------------------------------
# 1. the plans: no network, no child, no write; the add's refusals
# --------------------------------------------------------------------------

def same_refusal(code, plan, add, *a, **kw):
    """`plan` and `add` refuse the same arguments with the same code."""
    refused(code, plan, *a, **kw)
    refused(code, add, *a, **kw)


def test_plan_add_image_says_what_the_add_would_do():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = dict(channel="tech", repo=repo, root=inserts)
        (inserts / "memes-tech" / "taken.png").write_bytes(b"x")
        before = snapshot(t)
        fetched = []
        with stand_ins(_fetch=lambda url: fetched.append(url)) as calls:
            p = quiet(desk.plan_add_image, "new-still", "https://i.imgflip.com/abc.png?x=1",
                      "https://imgflip.com/meme/abc", "a still", " shock, , surprise ", **kw)
            assert p == {"bank": "memes-tech", "id": "new-still", "file": "new-still.png",
                         "will_fetch": "url", "url": "https://i.imgflip.com/abc.png?x=1",
                         "video": None, "source_url": "https://imgflip.com/meme/abc",
                         "span": None, "tags": ["shock", "surprise"],
                         "steps": ["download", "check", "index", "embedding"],
                         "max_seconds": desk.FETCH_TIMEOUT_SECONDS + 2 * desk.PROBE_TIMEOUT_SECONDS
                         + desk.EMBED_TIMEOUT_SECONDS}, p
            p = quiet(desk.plan_add_image, "new-still", "https://x.org/a.webp", "https://x.org/a",
                      "d", ["a"], embed=False, **kw)
            assert p["max_seconds"] == 90 and p["steps"][-1] == "index" and p["file"] == "new-still.webp"
            args = ("ok-id", "https://x.org/a.png", "https://x.org/a", "d", "a")
            for code, a, extra in (
                    ("duplicate_id", ("plain",) + args[1:], {}),
                    ("bad_entry", ("../up",) + args[1:], {}),
                    ("bad_entry", args[:4] + (5,), {}),
                    ("bad_entry", args[:3] + ("",) + args[4:], {}),
                    ("bad_suffix", (args[0], "https://x.org/a.gif") + args[2:], {}),
                    ("bad_url", (args[0], "file:///a.png") + args[2:], {}),
                    ("no_source_url", args[:2] + ("",) + args[3:], {}),
                    ("file_exists", ("taken",) + args[1:], {}),
                    ("bad_who", args, {"by": "a\nb"}),
                    ("bad_progress", args, {"progress": 5})):
                same_refusal(code, desk.plan_add_image, desk.add_image_entry, *a, **extra, **kw)
            refused("bad_bank", desk.plan_add_image, *args, repo=repo, root=inserts,
                    bank="memes-none")
        assert fetched == [] and calls["embed"] == []
        assert snapshot(t) == before, "a plan wrote something"


def test_plan_add_gif_says_what_the_add_would_do():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        tech = inserts / "memes-tech"
        kw = dict(channel="tech", repo=repo, root=inserts)
        (tech / "_desk" / "uploads").mkdir(parents=True)
        (tech / "_desk" / "uploads" / "in.mp4").write_bytes(b"inside")
        (tech / "taken.gif").write_bytes(b"GIF89a")
        url = "https://www.youtube.com/watch?v=abc"
        media, probe = desk.MEDIA_TIMEOUT_SECONDS, desk.PROBE_TIMEOUT_SECONDS
        embed = probe + desk.EMBED_TIMEOUT_SECONDS
        before = snapshot(t)
        with children(tmp) as calls:
            p = quiet(desk.plan_add_gif, "new-gif", url, "1", 2.5, "a gif", "a, b", **kw)
            assert p == {"bank": "memes-tech", "id": "new-gif", "file": "new-gif.gif",
                         "will_fetch": "yt-dlp", "url": url, "video": url, "cached": False,
                         "source_url": url, "span": {"start_s": 1.0, "end_s": 2.5},
                         "tags": ["a", "b"],
                         "steps": ["download", "scenes", "cut", "check", "index", "embedding"],
                         "max_seconds": probe + media + 2 * media + probe + embed}, p
            p = quiet(desk.plan_add_gif, "new-gif", "_desk/uploads/in.mp4", 0, 1, "a gif", ["a"],
                      source_url="https://x.org/v", local=True, embed=False, **kw)
            assert p["will_fetch"] == "local" and p["url"] is None and not p["cached"]
            assert Path(p["video"]) == tech / "_desk" / "uploads" / "in.mp4"
            assert p["source_url"] == "https://x.org/v"
            assert p["max_seconds"] == 2 * media + probe and "embedding" not in p["steps"]
            g = ("new-gif", url, 1, 2, "a gif", ["a"])
            for code, a, extra in (
                    ("bad_span", g[:2] + (2, 1) + g[4:], {}),
                    ("bad_span", g[:2] + ("x", 1) + g[4:], {}),
                    ("bad_url", ("new-gif", "file:///v.mp4") + g[2:], {}),
                    ("no_source_url", ("new-gif", "_desk/uploads/in.mp4") + g[2:],
                     {"local": True}),
                    ("outside_bank", ("new-gif", "../../v.mp4") + g[2:], {"local": True}),
                    ("video_failed", ("new-gif", "_desk/uploads/no.mp4") + g[2:],
                     {"local": True, "source_url": "https://x.org/v"}),
                    ("duplicate_id", ("plain",) + g[1:], {}),
                    ("file_exists", ("taken",) + g[1:], {}),
                    ("bad_entry", g[:5] + (7,), {}),
                    ("bad_who", g, {"via": "x" * 41}),
                    ("bad_progress", g, {"progress": "no"})):
                same_refusal(code, desk.plan_add_gif, desk.add_gif_entry, *a, **extra, **kw)
            assert calls["run"].calls == [] and calls["embed"] == []
        assert snapshot(t) == before, "a plan wrote something"
        # a cached URL: no download in the plan's time
        cache = desk.video_source(url, tech)["cache"]
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"mp4")
        with children(tmp):
            p = quiet(desk.plan_add_gif, "new-gif", url, 1, 2, "a gif", ["a"], **kw)
        assert p["cached"] is True and p["max_seconds"] == 2 * media + probe + embed


def test_plan_sheet_says_what_the_sheet_would_do():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        tech = inserts / "memes-tech"
        kw = dict(channel="tech", repo=repo, root=inserts)
        url = "https://x.org/v"
        media, probe = desk.MEDIA_TIMEOUT_SECONDS, desk.PROBE_TIMEOUT_SECONDS
        before = snapshot(t)
        with children(tmp) as calls:
            p = quiet(desk.plan_sheet, url, 4, 24, 2, "find.png", **kw)
            sheets = tech / "_desk" / "sheets"
            assert p == {"bank": "memes-tech", "id": None, "file": "_desk/sheets/find.png",
                         "sheet": str((sheets / "find.png").resolve()),
                         "will_fetch": "yt-dlp", "url": url, "video": url, "cached": False,
                         "source_url": url,
                         "span": {"start_s": 4.0, "end_s": 24.0, "every_s": 2.0, "frames": 10},
                         "tags": None, "steps": ["download", "frames", "sheet"],
                         "max_seconds": probe + media + media + probe + 2 * media}, p
            p = quiet(desk.plan_sheet, url, **kw)
            assert p["span"] == {"start_s": 0.0, "end_s": None, "every_s": 2.0, "frames": None}
            assert p["file"] == "_desk/sheets/sheet.jpg"
            for code, a, extra in (
                    ("bad_span", (url, 3, 1, 1), {}),
                    ("bad_span", (url, 0, 4, 0), {}),
                    ("bad_suffix", (url, 0, 4, 1, "x.gif"), {}),
                    ("outside_bank", (url, 0, 4, 1, "../x.jpg"), {}),
                    ("bad_url", ("/etc/v.mp4", 0, 4, 1), {}),
                    ("video_failed", ("none.mp4", 0, 4, 1), {"local": True}),
                    ("too_many_frames", (url, 0, 3600, 1), {}),
                    ("bad_progress", (url,), {"progress": 3})):
                same_refusal(code, desk.plan_sheet, desk.make_sheet, *a, **extra, **kw)
            assert calls["run"].calls == []
        assert snapshot(t) == before, "a plan wrote something"


# --------------------------------------------------------------------------
# 4 and 9 for the adds and the sheet: by/via, the journal, progress
# --------------------------------------------------------------------------

def test_the_adds_stamp_by_and_via_and_journal_the_job():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = dict(channel="tech", repo=repo, root=inserts)
        with stand_ins(_fetch=lambda url: png_bytes(1000, 800, top=200)):
            r = quiet(desk.add_image_entry, "new-still", "https://x.org/a.png",
                      "https://x.org/a", "a still", "a", notes="from a Short", by="user",
                      via="center", **kw)
            quiet(desk.add_image_entry, "plain-add", "https://x.org/b.png", "https://x.org/b",
                  "a still", "a", **kw)
        notes = r["entry"]["notes"].split("; ")
        assert notes[0] == "from a Short" and "CF-0534" in notes[1], notes
        assert notes[-1].startswith("add_image 20") and notes[-1].endswith("(by user, via center)")
        assert "add_image" not in index_of(inserts)["plain-add"]["notes"], "no by/via: no stamp"
        with children(tmp):
            r = quiet(desk.add_gif_entry, "new-gif", "https://x.org/v", 1, 2, "a gif", "a",
                      via="center", **kw)
        assert r["entry"]["notes"].startswith("add_gif 20") and \
            r["entry"]["notes"].endswith("(via center)")
        rows = journal(inserts)
        assert [(x["kind"], x["ids"], x["by"], x["via"]) for x in rows] == [
            ("add_image", ["new-still"], "user", "center"),
            ("add_image", ["plain-add"], None, None),
            ("add_gif", ["new-gif"], None, "center")], rows
        # a refused add writes no row
        with children(tmp):
            refused("duplicate_id", desk.add_gif_entry, "new-gif", "https://x.org/v", 1, 2, "g",
                    "a", by="user", **kw)
        assert len(journal(inserts)) == 3


def test_progress_of_the_adds_and_the_sheet():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = dict(channel="tech", repo=repo, root=inserts)
        seen = []
        log = lambda *a: seen.append(a)  # noqa: E731

        def boom(*a):
            raise RuntimeError("the job table is gone")

        with stand_ins(_fetch=lambda url: png_bytes(1000, 800, top=200)) as calls:
            quiet(desk.add_image_entry, "s1", "https://x.org/a.png", "https://x.org/a", "d",
                  "a", progress=log, **kw)
            assert [x[:3] for x in seen] == [("download", 1, 4), ("check", 2, 4),
                                             ("index", 3, 4), ("embedding", 4, 4)], seen
            seen.clear()
            quiet(desk.add_image_entry, "s2", "https://x.org/a.png", "https://x.org/a", "d",
                  "a", progress=log, embed=False, **kw)
            assert [x[:3] for x in seen] == [("download", 1, 3), ("check", 2, 3),
                                             ("index", 3, 3)], seen
            r = quiet(desk.add_image_entry, "s3", "https://x.org/a.png", "https://x.org/a",
                      "d", "a", progress=boom, **kw)
            assert r["embedding"]["done"] and len(calls["embed"]) == 2
        url = "https://x.org/v"
        seen.clear()
        with children(tmp):
            quiet(desk.add_gif_entry, "g1", url, 1, 2, "a gif", "a", progress=log, **kw)
            assert [x[:3] for x in seen] == [("download", 1, 6), ("scenes", 2, 6),
                                             ("cut", 3, 6), ("check", 4, 6), ("index", 5, 6),
                                             ("embedding", 6, 6)], seen
            assert seen[0][3] == url and seen[4][3] == "g1"
            seen.clear()
            quiet(desk.add_gif_entry, "g2", url, 1, 2, "a gif", "a", progress=log, embed=False,
                  **kw)
            assert seen[0] == ("download", 1, 5, "из кэша банка") and seen[-1][:3] == \
                ("index", 5, 5)
            quiet(desk.add_gif_entry, "g3", url, 1, 2, "a gif", "a", progress=boom, **kw)
            seen.clear()
            quiet(desk.make_sheet, url, 0, 10, 2, progress=log, **kw)
            assert [x[:3] for x in seen] == [("download", 1, 3), ("frames", 2, 3),
                                             ("sheet", 3, 3)], seen
            assert seen[1][3] == "5 кадров"
            r = quiet(desk.make_sheet, url, 0, 10, 2, "b.jpg", progress=boom, **kw)
        assert Path(r["sheet"]).is_file()
        assert {"g1", "g2", "g3", "s1", "s2", "s3"} <= set(index_of(inserts))


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

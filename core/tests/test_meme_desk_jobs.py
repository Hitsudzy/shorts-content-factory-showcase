#!/usr/bin/env python3
"""CF-0694: the meme desk's long jobs as functions the command center runs in
the background - cutout_available, cutout_entries, trim_blank_entries,
add_image_entry, add_gif_entry, make_sheet.

What is checked, on temp banks only (the real banks are never opened, no
network - the download and the embedding are stand-ins, the video is made
here by ffmpeg):
* every function prints nothing and refuses with MemeDeskError(code);
* the bank is a parameter: a call on Tech's bank leaves the default bank
  byte-identical;
* dry_run writes nothing (the whole temp tree is byte-identical);
* the cutout cuts only what the user ticked: a still without `cutout: true`
  and a GIF are never cut, and the flag is never set by a function;
* the cutout's macOS dependency is behind cutout_available (CF-0654): on a
  substituted platform it says why and cutout_entries starts nothing;
* nothing is read, cut or written outside the bank (CF-0697);
* a refused add leaves nothing in the bank.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import inserts_lib as lib  # noqa: E402
import meme_desk as desk  # noqa: E402
from test_meme_cutout import W, H, disk, rec_for  # noqa: E402

DAY = "2026-10-12"
REAL_RUN_VISION = desk.run_vision


def png(path, w=W, h=H, top=0, color="red"):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), color)
    if top:
        ImageDraw.Draw(im).rectangle((0, 0, w - 1, top - 1), fill="white")
    im.save(path)


def png_bytes(w, h, top=0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), "red")
    if top:
        ImageDraw.Draw(im).rectangle((0, 0, w - 1, top - 1), fill="white")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def gif(path, top=0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 300), "blue")
    if top:
        ImageDraw.Draw(im).rectangle((0, 0, 399, top - 1), fill="white")
    im.save(path, format="GIF")


def entry(eid, file, **over):
    e = {"id": eid, "file": file, "kind": "meme", "description": f"synthetic meme {eid}",
         "tags": ["x", "y"], "source_url": f"https://example.org/{file}", "added": DAY}
    e.update(over)
    return e


def world(tmp, escape=True):
    """A repo (channels/tech.json naming memes-tech, the real inserts/meme.json
    copied in) and an inserts library with the default bank and Tech's."""
    t = Path(tmp)
    repo, inserts = t / "repo", t / "inserts"
    (repo / "channels").mkdir(parents=True)
    (repo / "inserts").mkdir()
    shutil.copy(ROOT / "inserts" / "meme.json", repo / "inserts" / "meme.json")
    (repo / "channels" / "tech.json").write_text(json.dumps(
        {"insert_layers": {"meme": {"enabled": False, "bank": "shared/inserts/memes-tech/"}}}))
    default = inserts / "memes"
    default.mkdir(parents=True)
    d_entries = [entry("reel-cut", "reel-cut.png", cutout=True)]
    png(default / "reel-cut.png", 1000, 800, top=200)
    idx = lib.empty_index("meme")
    idx["entries"] = d_entries
    lib.save_index(idx, "meme", inserts)
    tech = inserts / "memes-tech"
    tech.mkdir()
    (t / "outside.png").parent.mkdir(exist_ok=True)
    png(t / "outside.png", 1000, 800, top=200)
    entries = [entry("cut-good", "cut-good.png", cutout=True),
               entry("cut-bad", "cut-bad.png", cutout=True),
               entry("plain", "plain.png"),
               entry("whole", "whole.png", cutout=False),
               entry("a-gif", "a-gif.gif", clip={"start_s": 1.0, "end_s": 2.0}),
               entry("banded", "banded.png"),
               entry("banded-small", "banded-small.png"),
               entry("escape", "../outside.png", cutout=True)]
    if not escape:      # an index naming a file outside its bank is invalid, never written
        entries = entries[:-1]
    for e in entries:
        if e["id"] == "a-gif":
            gif(tech / e["file"], top=150)
        elif e["id"] == "banded":
            png(tech / e["file"], 1000, 800, top=200)
        elif e["id"] == "banded-small":
            png(tech / e["file"], 400, 300, top=150)
        elif e["id"] != "escape":
            png(tech / e["file"])
    idx = lib.empty_index("meme")
    idx["entries"] = entries
    lib.save_index(idx, "meme", inserts, "memes-tech")
    return t, repo, inserts


def snapshot(top):
    out = {}
    for p in sorted(Path(top).rglob("*")):
        rel = str(p.relative_to(top))
        if p.is_symlink():
            out[rel] = "link:" + str(p.readlink())
        elif p.is_dir():
            out[rel] = "dir"
        else:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def quiet(fn, *a, **kw):
    """fn's value; the call must print nothing (the center runs it in the background)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    assert out.getvalue() == "" and err.getvalue() == "", (fn.__name__, out.getvalue(),
                                                           err.getvalue())
    return r


def refused(code, fn, *a, **kw):
    try:
        quiet(fn, *a, **kw)
    except desk.MemeDeskError as e:
        assert e.code == code, (fn.__name__, code, e.code, e.text)
        assert e.text and e.en, e
        return e
    raise AssertionError(f"{fn.__name__}{a} {kw} was not refused ({code})")


class FakeVision:
    def __init__(self, masks):
        self.masks, self.calls = masks, []

    def __call__(self, src, out_png):
        self.calls.append(Path(src).name)
        rec = rec_for(self.masks[Path(src).name])
        if rec["bbox"]:
            Path(out_png).write_bytes(b"\x89PNG fake")
            rec["out"] = str(out_png)
        return rec


@contextlib.contextmanager
def stand_ins(**over):
    """Replace module attributes of the desk for one test; the network is
    closed for the whole block (urlopen raises), the embedding is recorded."""
    calls = {"embed": [], "fetch": []}

    def embed(name, root):
        calls["embed"].append((name, Path(root)))
        return {"done": True, "line": "embedded", "error": None, "en": None, "fatal": False}

    def no_net(*a, **kw):
        raise AssertionError("a test reached the network")

    saved = {k: getattr(desk, k) for k in ("_embed_run", "run_vision", "_platform", "_fetch",
                                           *over)}
    saved_open = urllib.request.urlopen
    desk._embed_run = embed
    urllib.request.urlopen = no_net
    for k, v in over.items():
        setattr(desk, k, v)
    try:
        yield calls
    finally:
        urllib.request.urlopen = saved_open
        for k, v in saved.items():
            setattr(desk, k, v)


def ids_flags(inserts, bank="memes-tech"):
    return {e["id"]: e.get("cutout") for e in lib.load_index("meme", inserts, bank)["entries"]}


# --------------------------------------------------------------------------
# cutout
# --------------------------------------------------------------------------

def test_cutout_available_on_a_substituted_platform():
    real_env = os.environ.get("MEME_VISION_PY")
    try:
        with stand_ins(_platform=lambda: ("linux", "")):
            ok, why = quiet(desk.cutout_available)
            assert ok is False and "linux" in why and "CF-0654" not in why, why
            assert "CF-0654" in quiet(desk._cutout_check)[2]          # CF-0762: the id is in en
        with stand_ins(_platform=lambda: ("darwin", "13.6")):
            ok, why = quiet(desk.cutout_available)
            assert ok is False and "14" in why and "13.6" in why, why
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MEME_VISION_PY"] = str(Path(tmp) / "no-python")
            with stand_ins(_platform=lambda: ("darwin", "26.0")):
                ok, why = quiet(desk.cutout_available)
                assert ok is False and "no-python" not in why and "среда" in why, why
                assert "no-python" in quiet(desk._cutout_check)[2]    # CF-0762: the path is in en
            os.environ["MEME_VISION_PY"] = sys.executable
            with stand_ins(_platform=lambda: ("darwin", "26.0")):
                ok, why = quiet(desk.cutout_available)
                assert ok is True and "26.0" in why, why
    finally:
        if real_env is None:
            os.environ.pop("MEME_VISION_PY", None)
        else:
            os.environ["MEME_VISION_PY"] = real_env


def test_cutout_on_a_machine_that_cannot_cut_starts_nothing_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        before = snapshot(t)
        started = []
        real_run = subprocess.run

        def spy(cmd, *a, **kw):
            started.append(cmd)
            return real_run(cmd, *a, **kw)

        subprocess.run = spy
        try:
            with stand_ins(_platform=lambda: ("linux", ""), run_vision=REAL_RUN_VISION):
                e = refused("cutout_unavailable", desk.cutout_entries, "tech", repo=repo,
                            root=inserts)
                assert "linux" in e.text
        finally:
            subprocess.run = real_run
        assert not any("meme_cutout_vision" in " ".join(map(str, c)) for c in started), started
        assert snapshot(t) == before


def test_cutout_entries_cuts_only_ticked_stills_and_never_sets_the_flag():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp, escape=False)
        fake = FakeVision({"cut-good.png": disk(), "cut-bad.png": ["1" * W] * H})
        flags = ids_flags(inserts)
        default_before = snapshot(inserts / "memes")
        outside_before = (t / "outside.png").read_bytes()
        with stand_ins(run_vision=fake):
            r = quiet(desk.cutout_entries, "tech", repo=repo, root=inserts)
        assert sorted(fake.calls) == ["cut-bad.png", "cut-good.png"], fake.calls
        assert r["bank"] == "memes-tech" and r["written"] is True and r["dry_run"] is False
        assert [m["id"] for m in r["made"]] == ["cut-good"], r
        m = r["made"][0]
        assert m["file"] == "cut-good.cutout.png" and len(m["bbox_px"]) == 4 and m["coverage"] > 0
        assert [x["id"] for x in r["refused"]] == ["cut-bad"] and r["refused"][0]["reason"]
        assert r["missing"] == [] and r["outside_bank"] == [], r
        assert (inserts / "memes-tech" / "cut-good.cutout.png").exists()
        assert not (inserts / "memes-tech" / "a-gif.cutout.png").exists()
        assert not (inserts / "memes-tech" / "plain.cutout.png").exists()
        assert ids_flags(inserts) == flags, "a function changed a cutout flag"
        got = {e["id"]: e for e in lib.load_index("meme", inserts, "memes-tech")["entries"]}
        assert got["cut-good"]["cutout_asset"]["file"] == "cut-good.cutout.png"
        assert got["cut-bad"]["cutout_asset"]["file"] is None
        for i in ("plain", "whole", "a-gif"):
            assert "cutout_asset" not in got[i], i
        assert snapshot(inserts / "memes") == default_before, "the default bank was touched"
        assert (t / "outside.png").read_bytes() == outside_before
        # the second pass: nothing changed, nothing cut
        with stand_ins(run_vision=fake):
            again = quiet(desk.cutout_entries, "tech", repo=repo, root=inserts)
        assert sorted(again["unchanged"]) == ["cut-bad", "cut-good"] and not again["made"]
        assert again["written"] is False
        # force recuts
        with stand_ins(run_vision=fake):
            forced = quiet(desk.cutout_entries, "tech", ids=["cut-good"], force=True,
                           repo=repo, root=inserts)
        assert [x["id"] for x in forced["made"]] == ["cut-good"]


def test_cutout_entries_refuses_a_gif_an_unticked_still_and_an_unknown_id():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        fake = FakeVision({})
        before = snapshot(t)
        with stand_ins(run_vision=fake):
            e = refused("not_cutout", desk.cutout_entries, "tech", ids=["a-gif"], repo=repo,
                        root=inserts)
            assert "GIF" in e.text
            e = refused("not_cutout", desk.cutout_entries, "tech", ids=["plain"], repo=repo,
                        root=inserts)
            assert "можно вырезать" in e.text
            refused("not_cutout", desk.cutout_entries, "tech", ids=["whole"], repo=repo,
                    root=inserts)
            refused("unknown_id", desk.cutout_entries, "tech", ids=["nope"], repo=repo,
                    root=inserts)
            refused("bad_ids", desk.cutout_entries, "tech", ids=[1], repo=repo, root=inserts)
            refused("bad_bank", desk.cutout_entries, bank="memes-gone", repo=repo, root=inserts)
        assert fake.calls == [] and snapshot(t) == before


def test_cutout_entries_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        fake = FakeVision({"cut-good.png": disk(), "cut-bad.png": disk()})
        before = snapshot(t)
        with stand_ins(run_vision=fake):
            r = quiet(desk.cutout_entries, "tech", dry_run=True, repo=repo, root=inserts)
        assert fake.calls == [] and snapshot(t) == before
        assert sorted(x["id"] for x in r["made"]) == ["cut-bad", "cut-good"]
        assert r["missing"] == ["escape"] and r["outside_bank"][0]["id"] == "escape", r
        assert "вне банка" in r["outside_bank"][0]["reason"]
        assert all(x["bbox_px"] is None and x["coverage"] is None for x in r["made"])
        assert r["written"] is False and r["dry_run"] is True


# --------------------------------------------------------------------------
# trim-blank
# --------------------------------------------------------------------------

def test_trim_blank_entries_dry_run_then_the_cut():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        tech = inserts / "memes-tech"
        before = snapshot(t)
        with stand_ins() as calls:
            dry = quiet(desk.trim_blank_entries, "tech", dry_run=True, repo=repo, root=inserts)
        assert snapshot(t) == before and calls["embed"] == []
        assert [x["id"] for x in dry["trim"]] == ["banded"] and dry["changed"] == []
        row = dry["trim"][0]
        assert row["size"] == [1000, 800] and row["trimmed_size"] == [1000, 600], row
        assert row["crop"] == [200, 0] and row["stretch"] <= row["ceiling"]
        assert [x["id"] for x in dry["under"]] == ["banded-small"], dry
        left = {x["id"]: x["reason"] for x in dry["left"]}
        assert set(left) == {"a-gif", "escape"}, left
        assert "GIF" in left["a-gif"]
        assert dry["embedding"] is None

        with stand_ins() as calls:
            r = quiet(desk.trim_blank_entries, "tech", repo=repo, root=inserts)
        assert r["changed"] == ["banded"]
        with Image.open(tech / "banded.png") as im:
            assert im.size == (1000, 600)
        with Image.open(tech / "_desk" / "originals" / "banded.png") as im:
            assert im.size == (1000, 800)
        with Image.open(tech / "banded-small.png") as im:
            assert im.size == (400, 300), "under the ceiling once cut: left whole"
        with Image.open(t / "outside.png") as im:
            assert im.size == (1000, 800), "a file outside the bank was cut"
        got = {e["id"]: e for e in lib.load_index("meme", inserts, "memes-tech")["entries"]}
        assert "CF-0534" in got["banded"]["notes"]
        assert calls["embed"] == [("memes-tech", inserts)] and r["embedding"]["done"] is True
        assert r["originals"] == str(tech / "_desk" / "originals")
        # only one id; an unknown id is refused
        with stand_ins():
            one = quiet(desk.trim_blank_entries, "tech", id="banded-small", dry_run=True,
                        repo=repo, root=inserts)
            assert [x["id"] for x in one["under"]] == ["banded-small"] and not one["trim"]
            refused("unknown_id", desk.trim_blank_entries, "tech", id="nope", repo=repo,
                    root=inserts)


def test_trim_blank_entries_leaves_the_default_bank_alone():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        default_before = snapshot(inserts / "memes")
        with stand_ins():
            quiet(desk.trim_blank_entries, "tech", repo=repo, root=inserts, embed=False)
        assert snapshot(inserts / "memes") == default_before


# --------------------------------------------------------------------------
# adding
# --------------------------------------------------------------------------

def test_add_image_entry_cuts_the_panel_and_adds_pending():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        tech = inserts / "memes-tech"
        flags = ids_flags(inserts)

        def fetch(url):
            fetched.append(url)
            return png_bytes(1000, 800, top=200)

        fetched = []
        with stand_ins(_fetch=fetch) as calls:
            r = quiet(desk.add_image_entry, "new-still", "https://i.imgflip.com/abc.png",
                      "https://imgflip.com/meme/abc", "a still", "shock, surprise",
                      channel="tech", repo=repo, root=inserts)
        assert fetched == ["https://i.imgflip.com/abc.png"]
        e = r["entry"]
        assert r["bank"] == "memes-tech" and r["file"] == "new-still.png" and r["size"] == [1000, 600]
        assert e["review"] == "pending" and e["tags"] == ["shock", "surprise"]
        assert "cutout" not in e, "an add never sets the cutout flag"
        assert e["download_url"] == "https://i.imgflip.com/abc.png"
        assert "CF-0534" in e["notes"] and r["trim_note"]
        assert (tech / "new-still.png").exists() and not (tech / "new-still.png.part").exists()
        assert calls["embed"] == [("memes-tech", inserts)]
        assert {k: v for k, v in ids_flags(inserts).items() if k != "new-still"} == flags


def test_add_image_entry_refusals_leave_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        fetched = []

        def fetch(url):
            fetched.append(url)
            return png_bytes(100, 100)

        before = snapshot(t)
        kw = dict(channel="tech", repo=repo, root=inserts)
        with stand_ins(_fetch=fetch):
            refused("duplicate_id", desk.add_image_entry, "plain", "https://x.org/a.png",
                    "https://x.org/a", "d", "a", **kw)
            refused("bad_entry", desk.add_image_entry, "../up", "https://x.org/a.png",
                    "https://x.org/a", "d", "a", **kw)
            refused("bad_suffix", desk.add_image_entry, "ok-id", "https://x.org/a.gif",
                    "https://x.org/a", "d", "a", **kw)
            refused("no_source_url", desk.add_image_entry, "ok-id", "https://x.org/a.png",
                    "", "d", "a", **kw)
            assert fetched == [], "a refusal known beforehand downloaded the file"
            refused("over_ceiling", desk.add_image_entry, "tiny", "https://x.org/a.png",
                    "https://x.org/a", "d", "a", **kw)
        assert fetched == ["https://x.org/a.png"]
        assert snapshot(t) == before, "a refused add left something behind"


def make_video(path, seconds=3):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=size=640x480:rate=10:duration={seconds}", "-pix_fmt", "yuv420p",
                    str(path)], check=True, capture_output=True, timeout=120)


def test_add_gif_entry_from_a_local_video():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        # CF-0760: a local video only with local=True and only inside the bank
        video = inserts / "memes-tech" / "_desk" / "uploads" / "clip.mp4"
        video.parent.mkdir(parents=True)
        make_video(video)
        before = snapshot(inserts)
        with stand_ins() as calls:
            refused("no_source_url", desk.add_gif_entry, "new-gif", str(video), 0.5, 1.5,
                    "a gif", ["a", "b"], channel="tech", local=True, repo=repo, root=inserts)
            refused("bad_span", desk.add_gif_entry, "new-gif", str(video), 1.5, 0.5,
                    "a gif", ["a", "b"], source_url="https://x.org/v", channel="tech",
                    local=True, repo=repo, root=inserts)
            refused("bad_url", desk.add_gif_entry, "new-gif", str(video), 0.5, 1.5,
                    "a gif", ["a", "b"], source_url="https://x.org/v", channel="tech",
                    repo=repo, root=inserts)
            assert snapshot(inserts) == before
            r = quiet(desk.add_gif_entry, "new-gif", "_desk/uploads/clip.mp4", 0.5, 1.5, "a gif",
                      ["a", "b"], source_url="https://x.org/v", width=640, fps=5,
                      channel="tech", local=True, repo=repo, root=inserts)
        e = r["entry"]
        assert r["file"] == "new-gif.gif" and r["size"] == [640, 480], r
        assert e["cutout"] is False and e["clip"] == {"start_s": 0.5, "end_s": 1.5}
        assert e["source_url"] == "https://x.org/v" and e["review"] == "pending"
        assert r["duration_s"] == 1.0 and isinstance(r["cuts_inside"], list)
        assert (inserts / "memes-tech" / "new-gif.gif").exists()
        assert calls["embed"] == [("memes-tech", inserts)]
        # a GIF in the bank is never cut, not even when asked by id
        with stand_ins(run_vision=FakeVision({})):
            refused("not_cutout", desk.cutout_entries, "tech", ids=["new-gif"], repo=repo,
                    root=inserts)


def test_make_sheet_writes_inside_the_bank_only():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        video = inserts / "memes-tech" / "_desk" / "uploads" / "clip.mp4"
        video.parent.mkdir(parents=True)
        make_video(video, 4)
        with stand_ins():
            r = quiet(desk.make_sheet, str(video), 0, 4, 1, "find.jpg", channel="tech",
                      local=True, repo=repo, root=inserts)
        sheet = Path(r["sheet"])
        assert sheet == (inserts / "memes-tech" / "_desk" / "sheets" / "find.jpg").resolve()
        assert sheet.is_file() and isinstance(r["scene_cuts"], list)
        before = snapshot(t)
        with stand_ins():
            for out in ("../escape.jpg", str(t / "abs.jpg"), "../../x.jpg"):
                refused("outside_bank", desk.make_sheet, str(video), 0, 4, 1, out,
                        channel="tech", local=True, repo=repo, root=inserts)
            refused("bad_span", desk.make_sheet, str(video), 2, 1, 1, channel="tech",
                    local=True, repo=repo, root=inserts)
            refused("bad_span", desk.make_sheet, str(video), 0, 4, 0, channel="tech",
                    local=True, repo=repo, root=inserts)
        assert snapshot(t) == before


def test_cli_add_gif_and_sheet_print_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        video = t / "clip.mp4"
        make_video(video)
        saved = desk._embed, desk.LIBRARY
        desk._embed, desk.LIBRARY = (lambda: None), inserts
        cwd = os.getcwd()
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                desk.main(["add-gif", "--bank", "memes-tech", "--id", "cli-gif", "--video",
                           str(video), "--source-url", "https://x.org/v", "--start", "0.5",
                           "--end", "1.5", "--width", "640", "--fps", "5",
                           "--description", "d", "--tags", "a,b"])
            assert out.getvalue().splitlines()[-1] == \
                "added cli-gif: cli-gif.gif 640x480, 1.00 s, review pending", out.getvalue()
            os.chdir(tmp)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                desk.main(["sheet", "--video", str(video), "--every", "1", "--out", "s.jpg"])
            lines = out.getvalue().splitlines()
            assert lines[0] == f"sheet: {(Path(tmp) / 's.jpg').resolve()}", lines
            assert lines[1].startswith("scene cuts (s): ["), lines
            try:
                desk.main(["add-gif", "--bank", "memes-tech", "--id", "cli-gif2", "--video",
                           str(video), "--start", "0.5", "--end", "1.5",
                           "--description", "d", "--tags", "a"])
            except SystemExit as e:
                assert str(e) == "a local --video needs --source-url: where the video came from"
            else:
                raise AssertionError("a local video without --source-url was added")
        finally:
            os.chdir(cwd)
            desk._embed, desk.LIBRARY = saved
            desk.BANK = None


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

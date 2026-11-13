#!/usr/bin/env python3
"""CF-0697: the meme desk opens, thumbnails and deletes only media that lie in
the bank. An entry's `file` (or its cut's `file`) that is `../x`, an absolute
path or a link leading out of the bank is MemeDeskError('outside_bank' - the
center's code for the same refusal) in `thumb` of a still, a
`blank_band_errors` / `cut_refused` line in `desk_state`, an `errors` line in `plan_apply` (so `apply_marks` refuses and deletes nothing) -
and nothing is written anywhere. A bank linked into the library and the
per-file links `scripts/agents sync` makes in a version worktree are the
bank's own and work as before. `thumb` of a GIF opens and makes nothing: it
hands the path as written to the API, whose own guard refuses it
(test_cc_api_memes). The terminal's trim-blank and cutout check the name only
(they follow a link into the media it names, CF-0393).

Temp banks only (the real banks are never opened); the worktree case is a
local `git init` + `git worktree add` in a temp folder, no network.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
import inserts_lib as lib  # noqa: E402
import meme_desk as desk  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def _png(path, w=120, h=90):
    from PIL import Image
    Image.new("RGB", (w, h), "red").save(path)


def entry(eid, file, **over):
    e = {"id": eid, "file": file, "kind": "meme", "description": f"synthetic meme {eid}",
         "tags": ["x", "y"], "source_url": f"https://example.org/{eid}", "added": "2026-10-12"}
    e.update(over)
    return e


def write_bank(folder, entries, dec=None):
    """index.json written as is (no validation - the bad names are the point)
    and the page's draft."""
    folder.mkdir(parents=True, exist_ok=True)
    idx = lib.empty_index("meme")
    idx["entries"] = entries
    (folder / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1))
    if dec is not None:
        (folder / "_desk").mkdir(exist_ok=True)
        (folder / "_desk" / "decisions.json").write_text(json.dumps(dec, sort_keys=True))


def make_repo(t):
    repo = t / "repo"
    (repo / "channels").mkdir(parents=True)
    (repo / "inserts").mkdir()
    shutil.copy(ROOT / "inserts" / "meme.json", repo / "inserts" / "meme.json")
    (repo / "channels" / "reel.json").write_text(json.dumps({"insert_layers": {}}))
    return repo


def snapshot(top):
    out = {}
    for p in sorted(Path(top).rglob("*")):
        rel = str(p.relative_to(top))
        if p.is_symlink():
            out[rel] = "link:" + os.readlink(p)
        elif p.is_dir():
            out[rel] = "dir"
        else:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def code(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except desk.MemeDeskError as e:
        assert e.text and e.en, e.code
        return e.code
    return None


def escaping_world(t):
    """A default bank whose entries name media out of it three ways, each a
    real image (so a missing guard would open, thumbnail or delete it)."""
    repo = make_repo(t)
    inserts = t / "inserts"
    bank = inserts / "memes"
    bank.mkdir(parents=True)
    outside = t / "outside"
    outside.mkdir()
    for n in ("up.png", "abs.png", "linked.png", "cut.png"):
        _png(outside / n)
    shutil.copy(outside / "up.png", inserts / "up.png")         # ../up.png from the bank
    (bank / "linked.png").symlink_to(outside / "linked.png")
    _png(bank / "honest.png")
    entries = [entry("up", "../up.png", review="pending"),
               entry("abs", str(outside / "abs.png"), review="pending"),
               entry("linked", "linked.png", review="pending"),
               entry("cut-out", "honest.png", cutout=True,
                     cutout_asset={"file": "../../outside/cut.png", "source_sha256": "0" * 64,
                                   "method": "vision", "made": "2026-10-12", "coverage": 0.3})]
    write_bank(bank, entries, {"up": {"v": "drop"}, "abs": {"v": "drop"},
                               "linked": {"v": "drop"}, "cut-out": {"cut": False}})
    return repo, inserts, bank, outside


def test_thumb_refuses_a_path_out_of_the_bank_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo, inserts, bank, outside = escaping_world(t)
        before = snapshot(t)
        kw = {"root": inserts, "repo": repo}
        for mid in ("up", "abs", "linked"):
            assert code(desk.thumb, "reel", mid, **kw) == "outside_bank", mid
        assert snapshot(t) == before
        assert not (bank / "_desk" / "thumbs").exists()


def test_desk_state_never_opens_media_out_of_the_bank():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo, inserts, bank, outside = escaping_world(t)
        before = snapshot(t)
        s = desk.desk_state("reel", root=inserts, repo=repo)
        assert snapshot(t) == before
        st = s["status"]
        if st["blank_bands_checked"]:
            bad = {x["id"] for x in st["blank_band_errors"]}
            assert bad == {"up", "abs", "linked"}, st["blank_band_errors"]
            assert all("вне банка" in x["error"] for x in st["blank_band_errors"])
        cut = next(e for e in s["entries"] if e["id"] == "cut-out")
        assert cut["cut_file"] is None and "вне банка" in cut["cut_refused"]


def test_apply_never_deletes_out_of_the_bank_and_says_so_in_errors():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo, inserts, bank, outside = escaping_world(t)
        before = snapshot(t)
        kw = {"root": inserts, "repo": repo}
        plan = desk.plan_apply("reel", **kw)
        assert sorted(plan["remove"]) == ["abs", "linked", "up"]
        assert plan["files_to_delete"] == []
        assert len([x for x in plan["errors"] if "вне банка" in x]) == 4, plan["errors"]
        assert code(desk.apply_marks, "reel", **kw) == "invalid_index"
        assert snapshot(t) == before


def test_honest_entries_beside_a_bad_one_keep_their_behaviour():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo, inserts, bank, outside = escaping_world(t)
        # drop the bad entries from the index: the honest rest plans and applies
        idx = json.loads((bank / "index.json").read_text())
        idx["entries"] = [entry("honest", "honest.png", review="pending")]
        (bank / "index.json").write_text(json.dumps(idx))
        (bank / "_desk" / "decisions.json").write_text(json.dumps({"honest": {"v": "drop"}}))
        res = desk.apply_marks("reel", root=inserts, repo=repo)
        assert res["files_to_delete"] == ["honest.png"] and not res["errors"]
        assert not (bank / "honest.png").exists()
        assert sorted(p.name for p in outside.iterdir()) == ["abs.png", "cut.png",
                                                             "linked.png", "up.png"]


def test_bank_media_names():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        bank = t / "memes"
        (bank / "sub").mkdir(parents=True)
        assert desk.bank_media(bank, "a.png", t) == bank / "a.png"
        assert desk.bank_media(bank, "sub/a.gif", t) == bank / "sub" / "a.gif"
        for bad in ("../a.png", "sub/../../a.png", "/etc/hosts", "", ".", "sub/..", None):
            assert code(desk.bank_media, bank, bad, t) == "outside_bank", bad
        for bad in ("../a.png", "/etc/hosts"):
            assert code(desk.bank_media, bank, bad, t, links=False) == "outside_bank", bad
        (bank / "back").symlink_to(t)                      # a folder link out of the bank
        assert code(desk.bank_media, bank, "back/other.png", t) == "outside_bank"


def test_a_bank_linked_into_the_library_works_as_before():
    """CF-0393: the bank folder itself a link to a library elsewhere - its
    media resolve inside the resolved bank and are the bank's own."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = make_repo(t)
        (repo / "channels" / "tech.json").write_text(json.dumps(
            {"insert_layers": {"meme": {"enabled": False, "bank": "shared/inserts/memes-tech/"}}}))
        real = t / "library" / "memes-tech"
        real.mkdir(parents=True)
        for n in ("keep.png", "drop.png", "drop.cutout.png"):
            _png(real / n)
        write_bank(real, [entry("keep", "keep.png"),
                          entry("drop", "drop.png", review="pending", cutout=True,
                                cutout_asset={"file": "drop.cutout.png", "source_sha256": "0" * 64,
                                              "method": "vision", "made": "2026-10-12",
                                              "coverage": 0.3})],
                   {"drop": {"v": "drop"}})
        inserts = t / "inserts"
        inserts.mkdir()
        (inserts / "memes-tech").symlink_to(real)
        kw = {"root": inserts, "repo": repo}
        s = desk.desk_state("tech", **kw)
        assert s["status"]["blank_band_errors"] == []
        assert next(e for e in s["entries"] if e["id"] == "drop")["cut_file"] == "drop.cutout.png"
        if HAVE_FFMPEG:
            p = desk.thumb("tech", "keep", **kw)
            assert p == inserts / "memes-tech" / "_desk" / "thumbs" / "keep.jpg" and p.exists()
        res = desk.apply_marks("tech", **kw)
        assert sorted(res["files_to_delete"]) == ["drop.cutout.png", "drop.png"]
        assert not (real / "drop.png").exists() and (real / "keep.png").exists()


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org",
                    "-c", "init.defaultBranch=main", *args], cwd=cwd, check=True,
                   capture_output=True, timeout=60)


def test_a_version_worktrees_synced_links_are_the_banks_own():
    """A version worktree's bank holds links `scripts/agents sync` made
    (links.root `shared/inserts/*/*`) to the same file of the working copy:
    those are opened, thumbnailed and deleted as before; a link in the same
    bank to any other place is out of the bank."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        wc = t / "wc"
        wc.mkdir()
        _git(wc, "init", "-q")
        (wc / "README").write_text("x")
        _git(wc, "add", "README")
        _git(wc, "commit", "-q", "-m", "x")
        _git(wc, "worktree", "add", "-q", "-b", "release", str(t / "wt"))
        wt = t / "wt"
        prod = wc / "shared" / "inserts" / "memes"
        prod.mkdir(parents=True)
        for n in ("a.png", "b.png", "elsewhere.png"):
            _png(prod / n)
        (wt / "agents.lock.json").write_text(json.dumps(
            {"agents": {"x": {"rev": "main"}}, "links": {"root": ["shared/inserts/*/*"]}}))
        stand_in = make_repo(t / "r")
        for d in ("channels", "inserts"):
            shutil.copytree(stand_in / d, wt / d)
        bank = wt / "shared" / "inserts" / "memes"
        bank.mkdir(parents=True)
        (bank / "a.png").symlink_to(prod / "a.png")
        (bank / "b.png").symlink_to(prod / "b.png")
        (bank / "c.png").symlink_to(prod / "elsewhere.png")      # not the same path: out
        write_bank(bank, [entry("a", "a.png"), entry("b", "b.png", review="pending"),
                          entry("c", "c.png")], {"b": {"v": "drop"}})
        kw = {"root": wt / "shared" / "inserts", "repo": wt}
        desk._WORKING_COPY.clear()
        st = desk.desk_state("reel", **kw)["status"]
        if st["blank_bands_checked"]:
            assert [x["id"] for x in st["blank_band_errors"]] == ["c"], st["blank_band_errors"]
        assert code(desk.thumb, "reel", "c", **kw) == "outside_bank"
        if HAVE_FFMPEG:
            assert desk.thumb("reel", "a", **kw).exists()
        res = desk.apply_marks("reel", **kw)
        assert res["files_to_delete"] == ["b.png"]
        assert (prod / "elsewhere.png").exists() and (prod / "a.png").exists()
        # without the lock's links the same links are out of the bank
        (wt / "agents.lock.json").write_text(json.dumps({"agents": {"x": {"rev": "main"}}}))
        assert code(desk.thumb, "reel", "a", **kw) == "outside_bank"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

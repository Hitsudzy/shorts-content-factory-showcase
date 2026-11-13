#!/usr/bin/env python3
"""CF-0725: accepting a bank's candidates from the command center -
candidates_state, plan_accept, check_accept_answer, accept_candidates.

What is checked, on temp banks only (the real banks are never opened, no
network - urllib is replaced by a trap, the embedding by a stand-in):
* candidates_state reads only and says, per candidate, what the disk says
  (ready / in_bank / not_downloaded / outside_bank), with a fingerprint that
  is stable and moves when the list or the disk moves;
* plan_accept writes nothing and gives the reason of every refusal and the
  answer the user types;
* accept_candidates refuses whole on a changed list, a wrong answer, an
  unknown id, a missing fingerprint, a bad by/via - nothing written;
* a real accept adds `review: pending` entries with add-image's keys, never
  `cutout`, downloads nothing, journals by/via, leaves the default bank alone;
* dry_run writes nothing.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
import inserts_lib as lib  # noqa: E402
import meme_desk as desk  # noqa: E402

DAY = "2026-10-13"
ADD_IMAGE_KEYS = {"id", "file", "kind", "description", "tags", "source_url", "licence",
                  "medium", "added", "review", "notes", "download_url"}


def picture(path, w, h, fmt=None):
    from PIL import Image
    Image.new("RGB", (w, h), "red").save(path, format=fmt)


def cand(cid, url, **over):
    c = {"id": cid, "name": cid.replace("-", " ").title(), "imgflip_id": "123",
         "url": url, "width": 1000, "height": 800, "stretch": 1.08, "passes_ceiling": True,
         "bytes": 1000, "blank_band": "none", "intents": ["deadpan"],
         "use": f"when {cid} fits"}
    c.update(over)
    return c


def world(tmp):
    """A repo (channels/tech.json naming memes-tech, the real inserts/meme.json)
    and an inserts library: the default bank, and Tech's bank with an index of
    one entry and a candidates.json of six rows plus a reel_tail one."""
    t = Path(tmp)
    repo, inserts = t / "repo", t / "inserts"
    (repo / "channels").mkdir(parents=True)
    (repo / "inserts").mkdir()
    shutil.copy(ROOT / "inserts" / "meme.json", repo / "inserts" / "meme.json")
    (repo / "channels" / "tech.json").write_text(json.dumps(
        {"insert_layers": {"meme": {"enabled": False, "bank": "shared/inserts/memes-tech/"}}}))
    default = inserts / "memes"
    default.mkdir(parents=True)
    picture(default / "reel.png", 1000, 800)
    idx = lib.empty_index("meme")
    idx["entries"] = [{"id": "reel", "file": "reel.png", "kind": "meme", "description": "d",
                       "tags": ["x"], "source_url": "https://example.org/reel.png",
                       "added": DAY}]
    lib.save_index(idx, "meme", inserts)
    tech = inserts / "memes-tech"
    tech.mkdir()
    picture(tech / "ready-a.jpg", 1000, 800, "JPEG")
    picture(tech / "ready-b.png", 900, 900)
    picture(tech / "old.png", 1000, 800)
    picture(tech / "tiny.png", 100, 80)
    picture(t / "outside.png", 1000, 800)
    os.symlink(t / "outside.png", tech / "escape.png")
    idx = lib.empty_index("meme")
    idx["entries"] = [{"id": "old", "file": "old.png", "kind": "meme",
                       "description": "an accepted one", "tags": ["x"],
                       "source_url": "https://i.imgflip.com/old.png", "added": DAY}]
    lib.save_index(idx, "meme", inserts, "memes-tech")
    (tech / "candidates.json").write_text(json.dumps({
        "candidates": [cand("ready-a", "https://i.imgflip.com/a.jpg"),
                       cand("ready-b", "https://i.imgflip.com/b.png", width=900, height=900,
                            intents=["shock", "smug"]),
                       cand("old", "https://i.imgflip.com/old.png"),
                       cand("missing", "https://i.imgflip.com/m.jpg"),
                       cand("tiny", "https://i.imgflip.com/t.png", width=100, height=80,
                            passes_ceiling=False),
                       cand("escape", "https://i.imgflip.com/e.png")],
        "reel_tail": {"candidates": [cand("tail-one", None, width=None, height=None,
                                          passes_ceiling=None)]}}, indent=2))
    return t, repo, inserts


def tree(t):
    """Every file under `t` (links as links) with its digest."""
    out = {}
    for dirpath, _, files in os.walk(t):
        for f in files:
            p = Path(dirpath) / f
            out[str(p.relative_to(t))] = (os.readlink(p) if p.is_symlink()
                                          else hashlib.sha256(p.read_bytes()).hexdigest())
    return out


@contextlib.contextmanager
def sealed(embed_calls=None):
    """No network, no print, and the embedding a stand-in."""
    saved = urllib.request.urlopen, desk._embed_run

    def trap(*a, **k):
        raise AssertionError("a candidate accept must never download")

    def fake_embed(name, lib_root):
        if embed_calls is not None:
            embed_calls.append(name)
        return {"done": True, "line": "stand-in", "error": None, "en": None, "fatal": False}

    urllib.request.urlopen, desk._embed_run = trap, fake_embed
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            yield
    finally:
        urllib.request.urlopen, desk._embed_run = saved
    assert out.getvalue() == "", f"printed: {out.getvalue()!r}"


def refused(fn, code):
    try:
        fn()
    except desk.MemeDeskError as e:
        assert e.code == code, (e.code, e.text)
        return e
    raise AssertionError(f"expected MemeDeskError({code!r})")


def test_candidates_state_reads_only_and_says_what_the_disk_says():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        before = tree(t)
        s = desk.candidates_state("tech", root=inserts, repo=repo)
        assert tree(t) == before
        status = {r["id"]: r["status"] for r in s["candidates"]}
        assert status == {"ready-a": "ready", "ready-b": "ready", "old": "in_bank",
                          "missing": "not_downloaded", "tiny": "ready",
                          "escape": "outside_bank"}, status
        a = next(r for r in s["candidates"] if r["id"] == "ready-a")
        assert a["file"] == "ready-a.jpg" and a["downloaded"] and a["kind"] == "still"
        assert a["bytes"] == (inserts / "memes-tech" / "ready-a.jpg").stat().st_size
        assert a["source_url"] == "https://i.imgflip.com/a.jpg" and a["licence"] is None
        m = next(r for r in s["candidates"] if r["id"] == "missing")
        assert m["file"] is None and not m["downloaded"] and m["bytes"] == 1000
        assert s["counts"] == {"total": 6, "ready": 3, "in_bank": 1, "not_downloaded": 1,
                               "outside_bank": 1}
        assert s["other_bank"] == ["tail-one"] and s["bank"] == "memes-tech"
        assert s["fingerprint"].startswith("sha256:")
        assert desk.candidates_state("tech", root=inserts, repo=repo)["fingerprint"] \
            == s["fingerprint"]
        assert desk.candidates_state(bank="memes-tech", root=inserts, repo=repo) == s


def test_fingerprint_moves_with_the_list_and_with_the_disk():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        fp = desk.candidates_state("tech", root=inserts, repo=repo)["fingerprint"]
        picture(inserts / "memes-tech" / "missing.jpg", 1000, 800, "JPEG")
        fp2 = desk.candidates_state("tech", root=inserts, repo=repo)["fingerprint"]
        assert fp2 != fp
        path = inserts / "memes-tech" / "candidates.json"
        data = json.loads(path.read_text())
        data["candidates"][0]["use"] = "changed"
        path.write_text(json.dumps(data))
        assert desk.candidates_state("tech", root=inserts, repo=repo)["fingerprint"] != fp2


def test_a_bank_without_candidates_is_refused():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        refused(lambda: desk.candidates_state(root=inserts, repo=repo), "no_candidates")
        (inserts / "memes-tech" / "candidates.json").write_text("{nope")
        refused(lambda: desk.candidates_state("tech", root=inserts, repo=repo),
                "bad_candidates")


def test_plan_accept_writes_nothing_and_gives_every_reason():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        before = tree(t)
        ids = ["ready-a", "ready-b", "old", "missing", "tiny", "escape", "tail-one"]
        p = desk.plan_accept("tech", ids, by="user", via="center", root=inserts, repo=repo)
        assert tree(t) == before
        assert p["accept"] == ["ready-a", "ready-b"]
        reasons = {r["id"]: r["reason"] for r in p["refused"]}
        assert reasons == {"old": "in_bank", "missing": "not_downloaded",
                           "tiny": "over_ceiling", "escape": "outside_bank",
                           "tail-one": "other_bank"}, reasons
        assert all(r["text"] for r in p["refused"])
        assert p["answer"]["must_contain"] == "да" and "да" in p["answer"]["prompt"]
        assert p["downloads"] == 0 and p["review"] == "pending" and p["dry_run"] is True
        assert (p["by"], p["via"]) == ("user", "center")
        assert p["fingerprint"] == desk.candidates_state("tech", root=inserts,
                                                         repo=repo)["fingerprint"]
        every = desk.plan_accept("tech", root=inserts, repo=repo)
        assert every["ids"] == ["ready-a", "ready-b", "tiny"]
        assert every["accept"] == ["ready-a", "ready-b"]
        refused(lambda: desk.plan_accept("tech", ["ready-a", "nobody"], root=inserts,
                                         repo=repo), "unknown_id")
        refused(lambda: desk.plan_accept("tech", "ready-a", root=inserts, repo=repo), "bad_ids")
        refused(lambda: desk.plan_accept("tech", ["ready-a"], by="x\ny", root=inserts,
                                         repo=repo), "bad_who")
        refused(lambda: desk.plan_accept("tech", ["ready-a"], details={"ready-b": {}},
                                         root=inserts, repo=repo), "bad_details")
        assert tree(t) == before


def test_check_accept_answer():
    assert desk.check_accept_answer("да")["ok"]
    assert desk.check_accept_answer("Да, принимаю")["ok"]
    assert desk.check_accept_answer("yes")["ok"]
    for bad in (None, "", "ок", "дайте подумать", "да нет", "нет", "no, yes"):
        got = desk.check_accept_answer(bad)
        assert not got["ok"] and got["why"], bad


def test_accept_refuses_whole_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        ids = ["ready-a", "ready-b"]
        fp = desk.plan_accept("tech", ids, root=inserts, repo=repo)["fingerprint"]
        before = tree(t)
        kw = dict(root=inserts, repo=repo, embed=False)
        refused(lambda: desk.accept_candidates("tech", ids, "да", **kw), "no_fingerprint")
        refused(lambda: desk.accept_candidates("tech", ids, "ок", fingerprint=fp, **kw),
                "bad_answer")
        refused(lambda: desk.accept_candidates("tech", ids, "нет", fingerprint=fp, **kw),
                "bad_answer")
        refused(lambda: desk.accept_candidates("tech", ids, None, fingerprint=fp, **kw),
                "bad_answer")
        refused(lambda: desk.accept_candidates("tech", ids + ["nobody"], "да",
                                               fingerprint=fp, **kw), "unknown_id")
        refused(lambda: desk.accept_candidates("tech", ids, "да", by="", fingerprint=fp, **kw),
                "bad_who")
        refused(lambda: desk.accept_candidates("tech", ids, "да", fingerprint="sha256:0", **kw),
                "list_changed")
        assert tree(t) == before
        # the list moved after the plan: a file came in
        picture(inserts / "memes-tech" / "missing.jpg", 1000, 800, "JPEG")
        before = tree(t)
        refused(lambda: desk.accept_candidates("tech", ids, "да", fingerprint=fp, **kw),
                "list_changed")
        assert tree(t) == before


def test_accept_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        p = desk.plan_accept("tech", ["ready-a", "old"], root=inserts, repo=repo)
        before = tree(t)
        r = desk.accept_candidates("tech", ["ready-a", "old"], "да", "user", "center",
                                   fingerprint=p["fingerprint"], dry_run=True, root=inserts,
                                   repo=repo, today=DAY)
        assert tree(t) == before
        assert r["accepted"] == ["ready-a"] and r["unchanged"] and r["dry_run"]
        assert [x["id"] for x in r["refused"]] == ["old"]
        assert r["entries"][0]["review"] == "pending"


def test_accept_adds_pending_entries_like_add_image_and_journals_who():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        with sealed(calls):
            t, repo, inserts = world(tmp)
            default_before = tree(inserts / "memes")
            media_before = {f: v for f, v in tree(inserts / "memes-tech").items()
                            if f not in ("index.json",) and not f.startswith("_desk")}
            ids = ["ready-a", "ready-b", "missing"]
            p = desk.plan_accept("tech", ids, root=inserts, repo=repo)
            r = desk.accept_candidates(
                "tech", ids, "Да", "user", "center", fingerprint=p["fingerprint"],
                details={"ready-b": {"description": "A red square on a plain field.",
                                     "tags": "red, square, plain", "notes": "from the center"}},
                root=inserts, repo=repo, today=DAY)
        assert r["accepted"] == ["ready-a", "ready-b"] and not r["unchanged"]
        assert [(x["id"], x["reason"]) for x in r["refused"]] == [("missing", "not_downloaded")]
        assert calls == ["memes-tech"] and r["embedding"]["done"]
        assert tree(inserts / "memes") == default_before
        media_after = {f: v for f, v in tree(inserts / "memes-tech").items()
                       if f not in ("index.json",) and not f.startswith("_desk")}
        assert media_after == media_before          # nothing downloaded, nothing moved
        idx = lib.load_index("meme", inserts, "memes-tech")
        assert lib.validate_index(idx, "meme", inserts / "memes-tech") == []
        by_id = {e["id"]: e for e in idx["entries"]}
        assert list(by_id) == ["old", "ready-a", "ready-b"]
        for i in ("ready-a", "ready-b"):
            e = by_id[i]
            assert set(e) == ADD_IMAGE_KEYS, set(e) ^ ADD_IMAGE_KEYS
            assert "cutout" not in e and e["review"] == "pending" and e["licence"] is None
            assert e["added"] == DAY and e["source_url"] == e["download_url"]
            assert "by user" in e["notes"] and "via center" in e["notes"]
        a, b = by_id["ready-a"], by_id["ready-b"]
        assert a["file"] == "ready-a.jpg" and a["source_url"] == "https://i.imgflip.com/a.jpg"
        assert a["description"] == "Imgflip template «Ready A»."
        assert a["tags"] == ["ready a", "deadpan"]
        assert "rewrite them on the desk" in a["notes"]
        assert b["description"] == "A red square on a plain field."
        assert b["tags"] == ["red", "square", "plain"]
        assert "from the center" in b["notes"] and "rewrite them" not in b["notes"]
        rows = [json.loads(x) for x in (inserts / "memes-tech" / "_desk" /
                                        desk.ACCEPT_JOURNAL).read_text().splitlines()]
        assert len(rows) == 1
        row = rows[0]
        assert row["event"] == "candidates_accepted" and row["accepted"] == ["ready-a", "ready-b"]
        assert row["refused"] == ["missing"] and row["answer"] == "Да"
        assert (row["by"], row["via"]) == ("user", "center")
        assert row["fingerprint"] == p["fingerprint"]
        # the list moved with the accept: the old plan is refused now
        with sealed():
            refused(lambda: desk.accept_candidates("tech", ids, "да",
                                                   fingerprint=p["fingerprint"],
                                                   root=inserts, repo=repo, embed=False),
                    "list_changed")


def test_accept_with_nothing_acceptable_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp, sealed():
        t, repo, inserts = world(tmp)
        p = desk.plan_accept("tech", ["old", "missing"], root=inserts, repo=repo)
        before = tree(t)
        r = desk.accept_candidates("tech", ["old", "missing"], "да", fingerprint=p["fingerprint"],
                                   root=inserts, repo=repo)
        assert r["accepted"] == [] and r["unchanged"] and r["embedding"] is None
        assert tree(t) == before


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

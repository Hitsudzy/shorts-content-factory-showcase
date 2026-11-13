#!/usr/bin/env python3
"""CF-0693: the meme desk as functions the command center calls.

What is checked, on temp banks only (the real banks are never opened):
* `desk_state` of Reel's and Tech's banks computed at once in threads do not
  mix - the bank is a parameter, there is no module-global bank on that path;
* `desk_state` writes nothing: the whole temp tree is byte-identical after it,
  no `_desk` folder appears, no thumbnail is made;
* `save_marks` validates the draft's shape and with `by`/`via` stamps the
  changed marks; without them the draft is byte-identical to the page's;
* `plan_apply` writes nothing and is exactly what `apply_marks` then does;
* the CLI's `status` and `apply` print what they printed before CF-0693.
"""
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
import inserts_lib as lib  # noqa: E402
import meme_desk as desk  # noqa: E402

LEADER = next(iter(desk.intent_leaders()))


def _png(path, w=64, h=48, top=0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), "red")
    if top:
        ImageDraw.Draw(im).rectangle((0, 0, w - 1, top - 1), fill="white")
    im.save(path)


def _gif(path):
    from PIL import Image
    Image.new("RGB", (64, 48), "blue").save(path, format="GIF")


CUT = {"source_sha256": "0" * 64, "method": "vision", "made": "2026-10-12", "coverage": 0.3}


def entry(eid, file, **over):
    e = {"id": eid, "file": file, "kind": "meme", "description": f"synthetic meme {eid}",
         "tags": ["x", "y"], "source_url": f"https://example.org/{file}", "added": "2026-10-12"}
    e.update(over)
    return e


def _draft(folder, dec):
    (folder / "_desk").mkdir(parents=True, exist_ok=True)
    (folder / "_desk" / "decisions.json").write_text(
        json.dumps(dec, ensure_ascii=False, indent=1, sort_keys=True))


def world(tmp):
    """Two banks and a repo: Reel's default `memes/` and Tech's `memes-tech/`,
    channels/reel.json (no bank) and channels/tech.json (its bank), and the
    real inserts/meme.json copied in (the intent defaults, the band spec)."""
    t = Path(tmp)
    repo, inserts = t / "repo", t / "inserts"
    (repo / "channels").mkdir(parents=True)
    (repo / "inserts").mkdir()
    shutil.copy(ROOT / "inserts" / "meme.json", repo / "inserts" / "meme.json")
    (repo / "channels" / "reel.json").write_text(json.dumps({"insert_layers": {}}))
    (repo / "channels" / "tech.json").write_text(json.dumps(
        {"insert_layers": {"meme": {"enabled": False, "bank": "shared/inserts/memes-tech/"}}}))
    reel = inserts / "memes"
    reel.mkdir(parents=True)
    entries = [entry("new-keep", "new-keep.png", review="pending"),
               entry("new-drop", "new-drop.png", review="pending"),
               entry("old-drop", "old-drop.png", notes="kept for the old cut"),
               entry(LEADER, "leader.png"),
               entry("old-cut", "old-cut.png", cutout=True,
                     cutout_asset=dict(CUT, file="old-cut.cutout.png", bbox_px=[0, 0, 40, 30])),
               entry("refused-cut", "refused-cut.png", cutout=True,
                     cutout_asset=dict(CUT, file=None, refused="two figures")),
               entry("a-gif", "a-gif.gif", clip={"start_s": 1.0, "end_s": 2.0}),
               entry("banded", "banded.png")]
    for e in entries:
        if e["file"].endswith(".gif"):
            _gif(reel / e["file"])
        else:
            _png(reel / e["file"], 400, 300, top=150 if e["id"] == "banded" else 0)
    _png(reel / "old-cut.cutout.png")
    idx = lib.empty_index("meme")
    idx["entries"] = entries
    lib.save_index(idx, "meme", inserts)
    _draft(reel, {"new-keep": {"v": "keep"}, "new-drop": {"v": "drop"},
                  "old-drop": {"v": "drop"}, LEADER: {"v": "drop"},
                  "old-cut": {"cut": False, "note": "слишком пёстрый"},
                  "a-gif": {"cut": True}, "banded": {"cut": True},
                  "gone": {"v": "drop"}})
    tech = inserts / "memes-tech"
    tech.mkdir()
    t_entries = [entry("tech-new", "tech-new.png", review="pending"),
                 entry("tech-old", "tech-old.png"),
                 entry(LEADER, "leader.png")]
    for e in t_entries:
        _png(tech / e["file"], 300, 300)
    idx = lib.empty_index("meme")
    idx["entries"] = t_entries
    lib.save_index(idx, "meme", inserts, "memes-tech")
    _draft(tech, {"tech-new": {"v": "keep"}, "tech-old": {"cut": True, "note": "fine"},
                  LEADER: {"v": "drop"}})
    return t, repo, inserts


def snapshot(top):
    """path -> sha256 (or 'dir'/'link') of every node under `top`."""
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


def cli(argv, inserts):
    """Run the CLI on the temp library, as the user does; return stdout."""
    out = io.StringIO()
    old = desk.LIBRARY
    desk.LIBRARY = inserts
    try:
        with contextlib.redirect_stdout(out):
            desk.main(argv)
    finally:
        desk.LIBRARY, desk.BANK = old, None
    return out.getvalue()


def call(fn, *a, **kw):
    """The MemeDeskError code of a refused call, or None."""
    try:
        fn(*a, **kw)
    except desk.MemeDeskError as e:
        assert e.text and e.code, e
        return e.code
    return None


def test_reel_and_tech_states_computed_in_threads_do_not_mix():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = {"root": inserts, "repo": repo}
        ref = {ch: desk.desk_state(channel=ch, **kw) for ch in ("reel", "tech")}
        assert ref["reel"]["bank"] == "memes" and ref["reel"]["default_bank"]
        assert ref["tech"]["bank"] == "memes-tech" and not ref["tech"]["default_bank"]
        assert {e["id"] for e in ref["tech"]["entries"]} == {"tech-new", "tech-old", LEADER}
        sentinel = desk.BANK
        desk.BANK = "memes-tech"        # a CLI default left behind must not leak in
        got, errors = [], []

        def worker(ch):
            try:
                for _ in range(4):
                    got.append((ch, desk.desk_state(channel=ch, **kw)))
            except Exception as e:          # noqa: BLE001
                errors.append(repr(e))
        try:
            threads = [threading.Thread(target=worker, args=(ch,))
                       for ch in ("reel", "tech") * 4]
            for th in threads:
                th.start()
            for th in threads:
                th.join(60)
            assert desk.BANK == "memes-tech", "a desk function moved the CLI's bank"
        finally:
            desk.BANK = sentinel
        assert not errors, errors
        assert len(got) == 32
        for ch, state in got:
            assert state == ref[ch], f"{ch}'s state mixed with the other bank's"


def test_desk_state_writes_nothing_and_says_what_status_says():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        shutil.rmtree(inserts / "memes-tech" / "_desk")
        before = snapshot(t)
        reel = desk.desk_state(root=inserts, repo=repo)
        tech = desk.desk_state(bank="memes-tech", root=inserts, repo=repo)
        assert snapshot(t) == before, "desk_state wrote to disk"
        assert not (inserts / "memes-tech" / "_desk").exists()
        assert not (inserts / "memes" / "_desk" / "thumbs").exists(), "a thumbnail was made"
        assert tech["decisions"] == {} and tech["status"]["pending"] == ["tech-new"]
        st = reel["status"]
        assert st["pending"] == ["new-drop", "new-keep"]
        assert st["keep"] == ["new-keep"]
        assert st["drop"] == sorted([LEADER, "new-drop", "old-drop"])
        assert st["cut_diff"] == ["a-gif", "banded", "old-cut"]
        assert st["notes"] == {"old-cut": "слишком пёстрый"} and st["stale"] == ["gone"]
        assert st["blank_bands_checked"] is True
        assert st["blank_bands"] == [{"id": "banded", "phrase": "top 150 white rows (50%)",
                                      "phrase_ru": "сверху 150 белых строк (50%)"}]
        e = {x["id"]: x for x in reel["entries"]}
        keys = {"id", "file", "gif", "description", "tags", "source_url", "notes", "review",
                "cutout", "cutout_asset", "cut_file", "cut_refused", "clip"}
        assert all(keys <= set(x) for x in reel["entries"])
        assert e["old-cut"]["cut_file"] == "old-cut.cutout.png" and not e["old-cut"]["cut_refused"]
        assert e["refused-cut"]["cut_refused"] == "two figures" and not e["refused-cut"]["cut_file"]
        assert e["a-gif"]["gif"] and e["a-gif"]["clip"] == {"start_s": 1.0, "end_s": 2.0}
        assert e["new-keep"]["review"] == "pending" and e["old-drop"]["notes"]
        assert reel["decisions"]["gone"] == {"v": "drop"}


def test_desk_state_without_pillow_skips_the_band_check_and_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        saved = {k: v for k, v in sys.modules.items() if k == "PIL" or k.startswith("PIL.")}
        for k in saved:
            del sys.modules[k]
        sys.modules["PIL"] = None           # import PIL -> ImportError
        try:
            st = desk.desk_state(root=inserts, repo=repo)["status"]
        finally:
            del sys.modules["PIL"]
            sys.modules.update(saved)
        assert st["blank_bands_checked"] is False and "Pillow" in st["blank_bands_note_en"]
        assert "не проверены" in st["blank_bands_note"]          # CF-0762: the user's words
        assert st["blank_bands"] == [] and st["pending"] == ["new-drop", "new-keep"]


def test_a_bank_is_resolved_or_refused_never_defaulted():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = {"root": inserts, "repo": repo}
        assert call(desk.desk_state, channel="tech", bank="memes-tech", **kw) == "bank_conflict"
        assert call(desk.desk_state, channel="nope", **kw) == "no_channel"
        assert call(desk.desk_state, bank="memes-gone", **kw) == "bad_bank"
        assert call(desk.desk_state, bank="footage", **kw) == "bad_bank"
        assert call(desk.plan_apply, bank="memes-gone", **kw) == "bad_bank"
        assert desk.resolve_bank(channel="reel", **kw) == (None, inserts / "memes")
        assert desk.resolve_bank(channel="tech", **kw) == ("memes-tech", inserts / "memes-tech")


def test_save_marks_validates_the_shape_and_writes_nothing_when_refused():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = {"bank": "memes-tech", "root": inserts, "repo": repo}
        before = snapshot(t)
        bad = [([], "bad_decisions"), ({"nope": {"v": "keep"}}, "unknown_id"),
               ({"tech-new": "keep"}, "bad_decisions"),
               ({"tech-new": {"v": "maybe"}}, "bad_decisions"),
               ({"tech-new": {"cut": "yes"}}, "bad_decisions"),
               ({"tech-new": {"note": 5}}, "bad_decisions"),
               ({"tech-new": {"v": "keep", "cutout": True}}, "bad_decisions"),
               ({"tech-new": {"v": "keep", "marked_by": 3}}, "bad_decisions")]
        for dec, code in bad:
            assert call(desk.save_marks, dec, **kw) == code, dec
        assert snapshot(t) == before


def test_save_marks_without_by_is_the_pages_draft_and_with_by_stamps_changes():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = {"channel": "tech", "root": inserts, "repo": repo}
        draft = inserts / "memes-tech" / "_desk" / "decisions.json"
        dec = {"tech-new": {"v": "keep"}, "tech-old": {"cut": True, "note": "fine"},
               LEADER: {}}
        assert desk.save_marks(dec, **kw)["saved"] == 3
        assert draft.read_text() == json.dumps(dec, ensure_ascii=False, indent=1, sort_keys=True)
        # the center changes one mark: only that mark is stamped
        dec2 = {"tech-new": {"v": "keep"}, "tech-old": {"cut": False, "note": "fine"},
                LEADER: {"v": "drop"}}
        desk.save_marks(dec2, by="example-user", via="center", **kw)
        got = json.loads(draft.read_text())
        assert got["tech-new"] == {"v": "keep"}, "an unchanged mark was stamped"
        for i in ("tech-old", LEADER):
            assert got[i]["marked_by"] == "example-user" and got[i]["via"] == "center", got[i]
            assert got[i]["marked_at"].endswith("+00:00"), got[i]
        # saved again by someone else, unchanged: the first stamp stays
        state = desk.desk_state(**kw)
        desk.save_marks(state["decisions"], by="other", via="center", **kw)
        assert json.loads(draft.read_text()) == got
        # the stamped draft reads and applies like any other
        assert state["status"]["drop"] == [LEADER]
        plan = desk.plan_apply(drop=True, **kw)
        assert plan["remove"] == [LEADER] and plan["cutout_changed"] == ["tech-old"]


def test_plan_apply_writes_nothing_and_is_what_apply_marks_does():
    for drop in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            t, repo, inserts = world(tmp)
            kw = {"root": inserts, "repo": repo}
            memes = inserts / "memes"
            before = snapshot(t)
            plan = desk.plan_apply(drop=drop, **kw)
            assert snapshot(t) == before, "plan_apply wrote to disk"
            assert plan["accept"] == ["new-keep"] and not plan["errors"]
            assert plan["cutout_changed"] == ["a-gif", "banded", "old-cut"]
            if drop:
                assert plan["remove"] == ["new-drop", "old-drop"] and plan["held"] == []
                assert plan["refused"] == [{"id": LEADER,
                                            "intent": desk.leaders_of(None, repo)[LEADER]}]
                assert plan["files_to_delete"] == ["new-drop.png", "old-drop.png",
                                                   "old-cut.cutout.png"]
            else:
                assert plan["remove"] == ["new-drop"] and plan["refused"] == []
                assert plan["held"] == ["old-drop"], "an intent default is not held, it is refused"
                assert plan["files_to_delete"] == ["new-drop.png", "old-cut.cutout.png"]
            done = desk.apply_marks(drop=drop, **kw)
            assert done.pop("written") is True and done == plan
            for f in plan["files_to_delete"]:
                assert not (memes / f).exists(), f
            assert (memes / "leader.png").exists() and (memes / "new-keep.png").exists()
            got = {e["id"]: e for e in lib.load_index("meme", inserts)["entries"]}
            assert set(plan["remove"]).isdisjoint(got) and "review" not in got["new-keep"]
            assert got["old-cut"]["cutout"] is False and "cutout_asset" not in got["old-cut"]
            assert got["a-gif"]["cutout"] is False, "a GIF is never a cutout"
            assert got["refused-cut"]["cutout"] is True, "an unmarked cutout was touched"
            again = desk.plan_apply(drop=drop, **kw)
            assert again["accept"] == again["remove"] == again["files_to_delete"] == []


def test_apply_marks_refuses_an_invalid_index_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        idx = lib.load_index("meme", inserts)
        idx["entries"][0]["tags"] = "not a list"
        lib.save_index(idx, "meme", inserts)
        before = snapshot(t)
        plan = desk.plan_apply(root=inserts, repo=repo)
        assert plan["errors"], plan
        assert call(desk.apply_marks, root=inserts, repo=repo) == "invalid_index"
        assert snapshot(t) == before


def test_thumb_is_made_on_its_own_call():
    with tempfile.TemporaryDirectory() as tmp:
        t, repo, inserts = world(tmp)
        kw = {"root": inserts, "repo": repo}
        assert desk.thumb("reel", "a-gif", **kw) == inserts / "memes" / "a-gif.gif"
        assert not (inserts / "memes" / "_desk" / "thumbs").exists()
        p = desk.thumb("reel", "old-cut", **kw)
        assert p == inserts / "memes" / "_desk" / "thumbs" / "old-cut.jpg" and p.stat().st_size
        assert desk.thumb("tech", "tech-old", **kw).parent == inserts / "memes-tech" / "_desk" / "thumbs"
        assert call(desk.thumb, "reel", "nope", **kw) == "unknown_id"
        (inserts / "memes" / "old-drop.png").unlink()
        assert call(desk.thumb, "reel", "old-drop", **kw) == "no_file"


# What `status` and `apply` printed before CF-0693, on this world (captured
# from the code at 3089b7c); LEADER and its intent are the real vocabulary's.
def _golden():
    intent = desk.leaders_of(None)[LEADER]
    drops = ", ".join(sorted([LEADER, "new-drop", "old-drop"]))
    refused = ("refused to remove (rewrite inserts/meme.json intent_vocabulary first): "
               f"{LEADER} (default of intent '{intent}')\n")
    head = "accept 1: new-keep\ncutout written 3: a-gif, banded, old-cut\n"
    held = "marked drop but kept - accepted entries leave only with --drop: 1\n"
    wrote = "index.json written; run the insert tests before committing\n"
    return {
        ("status",): "library: 8 memes, 2 awaiting review: new-drop, new-keep\n"
                     f"marked keep 1, drop 3: {drops}\n"
                     "cutout ticks differing from index.json: a-gif, banded, old-cut\n"
                     "note old-cut: слишком пёстрый\n"
                     "blank caption panels over 12% (CF-0534, trim-blank): "
                     "banded (top 150 white rows (50%))\n"
                     "marks for ids no longer in the library (ignored): gone\n",
        ("status", "--bank", "memes-tech"):
            "library memes-tech: 3 memes, 1 awaiting review: tech-new\n"
            f"marked keep 1, drop 1: {LEADER}\n"
            "cutout ticks differing from index.json: tech-old\n"
            "note tech-old: fine\n"
            "blank caption panels over 12% (CF-0534, trim-blank): -\n",
        ("apply", "--dry-run"): head + "remove 1: new-drop\n" + held + "dry run - nothing written\n",
        ("apply", "--drop", "--dry-run"):
            head + "remove 2: new-drop, old-drop\n" + refused + "dry run - nothing written\n",
        ("apply",): head + "remove 1: new-drop\n" + held + wrote,
        ("apply", "--drop"): head + "remove 2: new-drop, old-drop\n" + refused + wrote,
        ("apply", "--drop", "--bank", "memes-tech"):
            f"bank memes-tech\naccept 1: tech-new\ncutout written 1: tech-old\nremove 1: {LEADER}\n"
            + wrote,
    }


def test_cli_status_and_apply_print_what_they_printed_before():
    for argv, want in _golden().items():
        with tempfile.TemporaryDirectory() as tmp:
            t, repo, inserts = world(tmp)
            assert cli(list(argv), inserts) == want, argv
            if argv == ("apply", "--drop"):
                draft = json.loads((inserts / "memes" / "_desk" / "decisions.json").read_text())
                assert set(draft) == {"a-gif", "banded", LEADER, "gone", "new-keep", "old-cut"}


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

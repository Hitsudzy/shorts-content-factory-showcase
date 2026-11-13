#!/usr/bin/env python3
"""CF-0403: the foreground cutout of a `cutout: true` meme.

What is checked, on a fixture library of synthetic images (media never
reaches git, and Vision is replaced by a fake that returns a chosen mask):
* the machine check accepts a clean silhouette and refuses, with a reason,
  an empty mask, a whole-frame mask, a fragmented one and a ragged one;
* `meme_desk.py cutout` cuts only `cutout: true` stills, writes
  `<id>.cutout.png` and `cutout_asset`, is a no-op on an unchanged source,
  recuts a changed one, and on a refused cut records the reason, leaves no
  file behind and keeps the entry - the meme stays whole;
* the schema takes `cutout_asset` on a `cutout: true` meme only, in shape;
* the desk shows the cut beside the source; unticking the cutout drops it;
* the Vision helper's describe() crops the RGBA to the silhouette (run under
  Video Editor's venv when it exists).
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
import inserts_lib as lib  # noqa: E402
import meme_desk as desk  # noqa: E402

W, H = 64, 48


def make_image(path, w=W, h=H, color="red"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}",
                    "-frames:v", "1", str(path)], check=True, capture_output=True)


def disk(w=W, h=H, r=14, cx=None, cy=None):
    cx, cy = (w // 2 if cx is None else cx), (h // 2 if cy is None else cy)
    return ["".join("1" if (x - cx) ** 2 + (y - cy) ** 2 <= r * r else "0" for x in range(w))
            for y in range(h)]


def rec_for(grid, soft=0.03):
    cells = [(x, y) for y, row in enumerate(grid) for x, ch in enumerate(row) if ch == "1"]
    cov = len(cells) / (len(grid) * len(grid[0]))
    bbox = None
    if cells:
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        bbox = [min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]
    return {"size": [len(grid[0]), len(grid)], "instances": 1 if cells else 0,
            "coverage": round(cov, 4), "bbox": bbox, "soft": soft, "grid": grid, "out": None}


def ragged(grid):
    """The same silhouette with every other edge cell flipped - a torn contour."""
    h, w = len(grid), len(grid[0])
    rows = [list(r) for r in grid]
    for y in range(h):
        for x in range(w):
            near = any(0 <= y + d < h and grid[y + d][x] != grid[y][x] for d in (-2, -1, 1, 2)) or \
                any(0 <= x + d < w and grid[y][x + d] != grid[y][x] for d in (-2, -1, 1, 2))
            if near and (x + y) % 2 == 0:
                rows[y][x] = "0" if grid[y][x] == "1" else "1"
    return ["".join(r) for r in rows]


# --------------------------------------------------------------------------
# the machine check
# --------------------------------------------------------------------------

def test_clean_silhouette_passes():
    reason, m = desk.judge_cutout(rec_for(disk()))
    assert reason is None, reason
    assert m["parts"] == 1 and m["edge_noise"] < desk.CUT_MAX_NOISE


def test_person_cut_by_the_frame_edge_is_not_ragged():
    # a bust whose body runs off the bottom of the picture
    g = disk(r=16, cy=H - 4)
    assert desk.judge_cutout(rec_for(g))[0] is None


def test_empty_mask_is_refused():
    reason, _ = desk.judge_cutout(rec_for(["0" * W] * H))
    assert reason and reason.startswith("empty mask")
    tiny = ["0" * W] * H
    tiny = tiny[:10] + ["0" * 30 + "11" + "0" * (W - 32)] + tiny[11:]
    assert desk.judge_cutout(rec_for(tiny))[0].startswith("empty mask")


def test_whole_frame_is_refused():
    g = ["1" * W] * H
    reason, _ = desk.judge_cutout(rec_for(g))
    assert reason and reason.startswith("nothing was cut")


def test_fragments_are_refused():
    g = [["0"] * W for _ in range(H)]
    for i in range(6):                      # six separate 6x6 squares
        for y in range(4, 10):
            for x in range(2 + i * 10, 8 + i * 10):
                g[y][x] = "1"
    reason, m = desk.judge_cutout(rec_for(["".join(r) for r in g]))
    assert reason and reason.startswith("fragmented") and m["parts"] == 6


def test_two_people_are_not_fragments():
    a, b = disk(r=9, cx=16), disk(r=9, cx=48)
    g = ["".join("1" if "1" in (p, q) else "0" for p, q in zip(ra, rb)) for ra, rb in zip(a, b)]
    assert desk.judge_cutout(rec_for(g))[0] is None


def test_ragged_edge_is_refused():
    reason, m = desk.judge_cutout(rec_for(ragged(disk(r=16))))
    assert reason and reason.startswith(("ragged edge", "fragmented")), (reason, m)
    # the torn contour, not the blob count, is what flags it
    assert m["edge_noise"] > desk.CUT_MAX_NOISE


def test_unsure_mask_is_refused():
    reason, _ = desk.judge_cutout(rec_for(disk(), soft=0.6))
    assert reason and reason.startswith("unsure mask")


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def entry(eid, file, **over):
    e = {"id": eid, "file": file, "kind": "meme", "description": f"synthetic meme {eid}",
         "tags": ["x"], "source_url": f"https://example.org/{file}", "added": "2026-09-24"}
    e.update(over)
    return e


class Args:
    def __init__(self, **kw):
        self.__dict__.update({"id": None, "force": False, "dry_run": False, **kw})


class FakeVision:
    """Stands in for scripts/meme_cutout_vision.py: a mask per file name."""

    def __init__(self, masks):
        self.masks, self.calls = masks, []

    def __call__(self, src, out_png):
        self.calls.append(Path(src).name)
        m = self.masks[Path(src).name]
        if isinstance(m, Exception):
            raise m
        rec = rec_for(m)
        if rec["bbox"]:
            Path(out_png).write_bytes(b"\x89PNG fake")
            rec["out"] = str(out_png)
        return rec


def fixture(tmp, masks):
    lib_root = Path(tmp) / "inserts"
    memes = lib_root / "memes"
    memes.mkdir(parents=True)
    entries = [entry("cut-good", "cut-good.jpg", cutout=True),
               entry("cut-bad", "cut-bad.png", cutout=True),
               entry("whole", "whole.jpg", cutout=False),
               entry("plain", "plain.jpg"),
               entry("a-gif", "a-gif.gif", clip={"start_s": 1.0, "end_s": 2.0})]
    for e in entries:
        make_image(memes / e["file"])
    idx = lib.empty_index("meme")
    idx["entries"] = entries
    lib.save_index(idx, "meme", lib_root)
    desk.LIBRARY = lib_root
    fake = FakeVision(masks)
    desk.run_vision = fake
    return lib_root, memes, fake


REAL_RUN_VISION = desk.run_vision


def restore():
    desk.LIBRARY = lib.INSERTS_ROOT
    desk.run_vision = REAL_RUN_VISION


def by_id(lib_root):
    return {e["id"]: e for e in lib.load_index("meme", lib_root)["entries"]}


def test_cutout_cuts_only_ticked_stills_and_records_the_asset():
    with tempfile.TemporaryDirectory() as tmp:
        lib_root, memes, fake = fixture(tmp, {"cut-good.jpg": disk(), "cut-bad.png": ["1" * W] * H})
        try:
            desk.cutout(Args())
            assert sorted(fake.calls) == ["cut-bad.png", "cut-good.jpg"]
            got = by_id(lib_root)
            a = got["cut-good"]["cutout_asset"]
            assert a["file"] == "cut-good.cutout.png" and (memes / a["file"]).exists()
            assert a["bbox_px"][2:] == [29, 29] and a["source_size_px"] == [W, H]
            assert 0 < a["coverage"] < 1 and a["method"] == desk.CUTOUT_METHOD
            assert a["source_sha256"] == desk.sha256_file(memes / "cut-good.jpg")
            b = got["cut-bad"]["cutout_asset"]
            assert b["file"] is None and b["refused"].startswith("nothing was cut")
            assert not (memes / "cut-bad.cutout.png").exists()
            assert not list(memes.glob("*.part.png")), "no temp file left behind"
            for i in ("whole", "plain", "a-gif"):
                assert "cutout_asset" not in got[i]
            idx = lib.load_index("meme", lib_root)
            assert lib.validate_index(idx, "meme", folder=memes) == []
        finally:
            restore()


def test_cutout_is_idempotent_and_recuts_a_changed_source():
    with tempfile.TemporaryDirectory() as tmp:
        lib_root, memes, fake = fixture(tmp, {"cut-good.jpg": disk(), "cut-bad.png": ["0" * W] * H})
        try:
            desk.cutout(Args())
            before = json.loads((memes / "index.json").read_text())
            fake.calls.clear()
            desk.cutout(Args())
            assert fake.calls == [], "an unchanged source is not cut again"
            assert json.loads((memes / "index.json").read_text()) == before
            make_image(memes / "cut-good.jpg", color="blue")
            desk.cutout(Args())
            assert fake.calls == ["cut-good.jpg"]
            desk.cutout(Args(force=True, id="cut-bad"))
            assert fake.calls == ["cut-good.jpg", "cut-bad.png"]
            # a deleted cutout file is made again
            fake.calls.clear()
            (memes / "cut-good.cutout.png").unlink()
            desk.cutout(Args())
            assert fake.calls == ["cut-good.jpg"]
        finally:
            restore()


def test_refused_recut_removes_the_old_file_and_keeps_the_entry():
    with tempfile.TemporaryDirectory() as tmp:
        lib_root, memes, fake = fixture(tmp, {"cut-good.jpg": disk(), "cut-bad.png": disk()})
        try:
            desk.cutout(Args())
            assert (memes / "cut-bad.cutout.png").exists()
            fake.masks["cut-bad.png"] = RuntimeError("Vision request failed")
            desk.cutout(Args(force=True, id="cut-bad"))
            got = by_id(lib_root)
            assert "cut-bad" in got and got["cut-bad"]["cutout"] is True
            a = got["cut-bad"]["cutout_asset"]
            assert a["file"] is None and "Vision failed" in a["refused"]
            assert not (memes / "cut-bad.cutout.png").exists()
            assert (memes / "cut-bad.png").exists(), "the source is never touched"
        finally:
            restore()


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        lib_root, memes, fake = fixture(tmp, {"cut-good.jpg": disk(), "cut-bad.png": disk()})
        try:
            before = (memes / "index.json").read_text()
            desk.cutout(Args(dry_run=True))
            assert fake.calls == [] and (memes / "index.json").read_text() == before
            assert not list(memes.glob("*.cutout.png"))
        finally:
            restore()


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------

GOOD = {"file": "m.cutout.png", "source_sha256": "a" * 64, "method": desk.CUTOUT_METHOD,
        "made": "2026-09-27", "coverage": 0.3, "bbox_px": [2, 3, 20, 30],
        "source_size_px": [64, 48], "parts": 1, "edge_noise": 0.02, "soft": 0.03}


def errs_for(asset, **over):
    e = entry("m", "m.jpg", cutout=True, cutout_asset=asset)
    e.update(over)
    return lib.validate_entry(e, "meme")


def test_schema_accepts_an_accepted_and_a_refused_cut():
    assert errs_for(copy.deepcopy(GOOD)) == []
    refused = {k: GOOD[k] for k in ("source_sha256", "method", "made", "coverage")}
    refused.update(file=None, refused="empty mask: nothing found")
    assert errs_for(refused) == []


def test_schema_refuses_a_cut_where_it_does_not_belong_or_out_of_shape():
    assert any("cutout: true only" in x for x in errs_for(GOOD, cutout=False))
    assert errs_for(GOOD, cutout=None)
    no_flag = entry("m", "m.jpg", cutout_asset=GOOD)
    assert any("cutout: true only" in x for x in lib.validate_entry(no_flag, "meme"))
    loop = entry("m", "m.mp4", cutout_asset=GOOD, rights_holder="x")
    assert lib.validate_entry(loop, "loop")
    bad = [dict(GOOD, file="other.png"), dict(GOOD, source_sha256="xyz"),
           dict(GOOD, coverage=1.5), dict(GOOD, bbox_px=[0, 0, 0, 5]),
           dict(GOOD, bbox_px=[50, 0, 20, 5]), dict(GOOD, refused="but it has a file"),
           dict(GOOD, file=None), dict(GOOD, extra=1), dict(GOOD, made="yesterday"),
           {k: v for k, v in GOOD.items() if k != "method"}, "m.cutout.png"]
    for a in bad:
        assert errs_for(a), a


def test_schema_checks_the_cut_file_when_the_folder_is_given():
    with tempfile.TemporaryDirectory() as tmp:
        e = entry("m", "m.jpg", cutout=True, cutout_asset=dict(GOOD))
        make_image(Path(tmp) / "m.jpg")
        assert any("m.cutout.png" in x for x in lib.validate_entry(e, "meme", folder=tmp))
        (Path(tmp) / "m.cutout.png").write_bytes(b"x")
        assert lib.validate_entry(e, "meme", folder=tmp) == []


# --------------------------------------------------------------------------
# the desk
# --------------------------------------------------------------------------

def test_unticking_the_cut_drops_it():
    with tempfile.TemporaryDirectory() as tmp:
        lib_root, memes, fake = fixture(tmp, {"cut-good.jpg": disk(), "cut-bad.png": ["0" * W] * H})
        try:
            desk.cutout(Args())
            desk.save_decisions({"cut-good": {"cut": False}, "cut-bad": {"cut": False}})
            desk.apply(Args(drop=False, dry_run=False))
            got = by_id(lib_root)
            assert got["cut-good"]["cutout"] is False and "cutout_asset" not in got["cut-good"]
            assert "cutout_asset" not in got["cut-bad"]
            assert not (memes / "cut-good.cutout.png").exists()
            assert (memes / "cut-good.jpg").exists()
        finally:
            restore()


# --------------------------------------------------------------------------
# the Vision helper (Video Editor's venv; skipped where it is absent)
# --------------------------------------------------------------------------

HELPER_CHECK = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import numpy as np
from PIL import Image
import meme_cutout_vision as mcv
src, out = sys.argv[2], sys.argv[3]
Image.new("RGB", (80, 60), (200, 30, 30)).save(src)
alpha = np.zeros((60, 80), np.float32)
alpha[10:40, 20:50] = 1.0
rec = mcv.describe(src, out, alpha, 1, grid=20)
img = Image.open(out)
print(json.dumps({"rec": rec, "mode": img.mode, "size": list(img.size),
                  "corner_alpha": img.getpixel((0, 0))[3]}))
"""


def test_vision_helper_crops_rgba_to_the_silhouette():
    py = desk.vision_python()
    if not py.exists():
        print(f"skipped: no {py}")   # tests/run_tests.py has no skip
        return
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([str(py), "-c", HELPER_CHECK, str(ROOT / "scripts"),
                            str(Path(tmp) / "s.png"), str(Path(tmp) / "s.cutout.png")],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[-600:]
        got = json.loads(r.stdout)
        assert got["mode"] == "RGBA" and got["size"] == [30, 30]
        assert got["corner_alpha"] == 255
        rec = got["rec"]
        assert rec["bbox"] == [20, 10, 30, 30] and rec["coverage"] == round(900 / 4800, 4)
        assert len(rec["grid"]) == 15 and len(rec["grid"][0]) == 20
        reason, _ = desk.judge_cutout(rec)
        assert reason is None, reason


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

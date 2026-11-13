#!/usr/bin/env python3
"""CF-0665: a clip name read back to its source id - YouTube and archive.

The Footage Indexer now downloads archive files directly (FI f537616): their
ids are `nasa-<id>` / `commons-<pageid>` of any length, where a YouTube id is
exactly 11 chars. The fallback readers of clip names (old plans with no
`shot`, batches whose work/ is gone) used an 11-char window and read
`a00_commons-151359165_s053.mp4` as source `s-151359165`. One reading now
lives in scripts/_clip_names.py; retired_shots.py, entity_guard.py and
source_gate.py take it from there.

Synthetic names only, in the shape resolve_anchors.py / build_render_plan.py
write (`a00_<id>_s009.mp4`, `nc01_<id>_s008.mp4`, `open_left_<id>_s003.mp4`,
`s01_held_a01_<id>_s011.png`). No batch, no pool, no network.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import _clip_names  # noqa: E402
import entity_guard  # noqa: E402
import retired_shots  # noqa: E402
import source_gate  # noqa: E402

YT = "H6RXVb_J5J4"                       # 11 chars, an underscore inside
YT_DASH = "_LE1L4Huy-s"                  # leading underscore, a dash
NASA = "nasa-Artemis_II_Science_-_AVATAR_Vertical_Video"
NASA_SHORT = "nasa-ab"                   # prefix + id would make 11 chars
COMMONS = "commons-151359165"
OWN = "own_capture-acme-fox-demo-20261011t120000z"   # CF-0567: our own recording
OWN_SHORT = "own_capture-a"
WORK = "/x/pipeline/chan/2026-10-10T0000Z/work/some-video"


def clip(prefix, vid, n, ext="mp4"):
    return f"{WORK}/{prefix}_{vid}_s{n:03d}.{ext}"


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_clip_shot_reads_every_shape():
    for vid in (YT, YT_DASH, NASA, NASA_SHORT, COMMONS, OWN, OWN_SHORT):
        for prefix in ("a00", "nc01", "open_left", "s01_held_a01"):
            stem = Path(clip(prefix, vid, 9)).stem
            got = _clip_names.clip_shot(stem)
            _check(got == (vid, "009"), f"{stem} -> {got}")
        _check(_clip_names.clip_shot(f"{vid}_s12") == (vid, "12"), vid)


def test_archive_id_is_never_cut_to_eleven_chars():
    # the old window (retired_shots.ASSET_SHOT): `s-151359165` out of the
    # commons clip, `a00_nasa-ab` out of the short nasa clip
    old = re.compile(r"(?P<vid>[A-Za-z0-9_-]{11})_s\d{3,}$")
    for vid, false in ((COMMONS, "s-151359165"), (NASA_SHORT, "a00_nasa-ab")):
        stem = f"a00_{vid}_s053"
        _check(old.search(stem).group("vid") == false, "the old reading, as reported")
        _check(_clip_names.clip_shot(stem)[0] == vid, stem)


def test_false_candidates_read_as_nothing():
    for stem in ("frame_4_clean", "s0", "a00_short-id_s001", "a00_nasa-_s001",
                 "a00_NASA-Foo_s001", "a00_wiki-151359165_s001",
                 f"a00_{YT}_s", f"a00_{YT}_s01x", "", "a00_foo"):
        _check(_clip_names.clip_shot(stem) is None, f"{stem!r} read as a clip")
    for v in ("frame_4_clean", "nasa-", "commons", "short", "a" * 12, "x y z" * 3):
        _check(not _clip_names.is_source_id(v), v)
    for v in (YT, NASA, COMMONS):
        _check(_clip_names.is_source_id(v), v)


def test_retired_shots_fallback():
    for vid in (YT, NASA, COMMONS):
        _check(retired_shots.asset_shot(clip("a00", vid, 53)) == f"{vid}:53", vid)
        # a block from before plans carried `shot`
        blk = {"kind": "clip", "asset": {"src": clip("a03", vid, 7)}}
        _check(retired_shots.block_shots(blk) == [f"{vid}:7"], vid)
    _check(retired_shots.asset_shot(clip("a00", COMMONS, 53)) != "s-151359165:53", "false id")
    # still three digits at least, still an extension
    _check(retired_shots.asset_shot(f"{WORK}/a00_{NASA}_s09.mp4") is None, "two digits")
    _check(retired_shots.asset_shot(f"{WORK}/a00_{NASA}_s009") is None, "no extension")
    _check(retired_shots.asset_shot(None) is None, "None")
    rec = {"assets": [{"src": clip("a00", NASA, 1)}, {"src": clip("a01", COMMONS, 2)},
                      {"src": clip("a02", YT, 3)}, {"src": clip("a03", NASA, 1)},
                      {"src": f"{WORK}/title_card.png"}]}
    _check(retired_shots.record_shots(rec) == [f"{NASA}:1", f"{COMMONS}:2", f"{YT}:3"],
           retired_shots.record_shots(rec))


def test_entity_guard_reads_archive_clip_names():
    blk = {"kind": "split", "asset": {"halves": [{"src": clip("a00", NASA, 4)},
                                                 {"clip": clip("a01", COMMONS, 12)}],
                                      "cuts": [{"asset": clip("a02", YT, 5)}]}}
    refs = entity_guard._shot_refs(blk)
    _check(refs == [(f"{NASA}:4", NASA, "004"), (f"{COMMONS}:12", COMMONS, "012"),
                    (f"{YT}:5", YT, "005")], refs)
    # a `shot` key still wins over the file name
    _check(entity_guard._shot_refs({"shot": f"{COMMONS}:3",
                                    "src": clip("a00", COMMONS, 99)})
           == [(f"{COMMONS}:3", COMMONS, "3")], "shot key")


def test_source_gate_source_id():
    for vid in (YT, NASA, COMMONS):
        _check(source_gate.source_id(clip("a00", vid, 9)) == vid, vid)
        _check(source_gate.source_id(clip("s01_held_a01", vid, 11, "png")) == vid, vid)
        _check(source_gate.source_id(f"/pool/shared/footage/{vid}.mp4") == vid, vid)
        _check(source_gate.source_id(f"{vid}:12") == vid, vid)
    _check(source_gate.source_id(clip("a00", COMMONS, 53)) != "s-151359165", "false id")
    for v in ("/b/work/v/s0.mp4", "/b/frame_4_clean.png", "/b/a00_short-id_s001.mp4"):
        _check(source_gate.source_id(v) is None, v)
    # two archive files are two sources
    plan = {"blocks": [{"kind": "clip", "asset": {"src": clip("a00", NASA, 1)}},
                       {"kind": "clip", "asset": {"src": clip("a01", COMMONS, 2)}}]}
    got = [source_gate.source_id(b["asset"]["src"]) for b in plan["blocks"]]
    _check(got == [NASA, COMMONS], got)


def test_own_capture_ids():
    """CF-0567: `own_capture-<id>` on disk / in shot keys, `own_capture:<id>`
    as the Trend Hunter and the Footage Indexer name it."""
    for vid in (OWN, OWN_SHORT):
        _check(_clip_names.is_source_id(vid) and _clip_names.is_own_capture(vid), vid)
        _check(source_gate.source_id(f"{vid}:4") == vid, vid)
        _check(source_gate.source_id(f"/pool/shared/footage/{vid}.mp4") == vid, vid)
    _check(_clip_names.is_own_capture("own_capture:acme-1"), "the candidate name")
    for vid in (YT, NASA, COMMONS, "own_capturX-a", None):
        _check(not _clip_names.is_own_capture(vid), vid)
    _check(_clip_names.own_capture_file_id("own_capture:acme/fox.1") == "own_capture-acme_fox_1",
           "file id")
    _check(_clip_names.own_capture_file_id(OWN) == OWN, "idempotent")
    _check(_clip_names.own_capture_file_id("bare-id") == "own_capture-bare-id", "bare")


def test_nothing_else_in_the_editor_waits_for_eleven_chars():
    scripts = HERE.parent / "scripts"
    left = [f"{p.name}" for p in sorted(scripts.glob("*.py"))
            if p.name != "_clip_names.py" and "{11}" in p.read_text(encoding="utf-8")]
    _check(not left, f"an 11-char id reading outside _clip_names: {left}")


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

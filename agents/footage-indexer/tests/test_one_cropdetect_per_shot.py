#!/usr/bin/env python3
"""CF-0740 L6: one cropdetect per shot, not two.

The usability frame (usability_probe.extract_full_frames) and the card-text
probe (index_footage.probe_card_text) asked detect_letterbox() about the same
shot with the same (start, duration). index_footage.main() now keeps the
first answer in a LetterboxMemo and the card probe reuses it. Everything that
would decode is stubbed: detect_letterbox counts its calls, ffmpeg writes
empty files, Vision answers nothing.

usability_probe.py itself is not edited (its bytes are in the usability
fingerprint); the memo is handed to it for the length of the call and taken
back after - also pinned here.
"""
import contextlib
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import index_footage as ix  # noqa: E402
import usability_probe  # noqa: E402

SHOTS = [{"start": 0.0, "end": 4.2}, {"start": 4.2, "end": 11.0},
         {"start": 11.0, "end": 13.4}]


class World:
    """detect_letterbox, ffmpeg (subprocess.run / runlog.run_child), Vision
    and runlog.child stubbed for one test; restored on exit."""

    def __init__(self, bars="crop=1920:800:0:140"):
        self.bars = bars
        self.cropdetects = []
        self.ffmpeg = []
        self.children = []

    def fake_letterbox(self, source, start, duration):
        self.cropdetects.append((source, start, duration))
        return self.bars

    def fake_run(self, cmd, **kw):
        self.ffmpeg.append(list(cmd))
        out = Path(cmd[-1])
        if "%02d" in out.name:
            n = int(cmd[cmd.index("-frames:v") + 1])
            for i in range(n):
                (out.parent / (out.name % i)).write_bytes(b"")
        else:
            out.write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    @contextlib.contextmanager
    def fake_child(self, tool, argv=None, **kw):
        self.children.append((tool, list(argv or [])))
        yield None

    def __enter__(self):
        self.saved = (ix.detect_letterbox, subprocess.run, ix.runlog.run_child,
                      ix.runlog.child, ix.detect_text_band.sample_text_regions,
                      usability_probe.detect_letterbox)
        ix.detect_letterbox = self.fake_letterbox
        # A stand-in for usability_probe's own import too, so a memo miss
        # there would be counted (and never decode for real).
        usability_probe.detect_letterbox = self.fake_letterbox
        subprocess.run = self.fake_run
        ix.runlog.run_child = self.fake_run
        ix.runlog.child = self.fake_child
        ix.detect_text_band.sample_text_regions = lambda *a, **k: []
        return self

    def __exit__(self, *exc):
        (ix.detect_letterbox, subprocess.run, ix.runlog.run_child,
         ix.runlog.child, ix.detect_text_band.sample_text_regions,
         usability_probe.detect_letterbox) = self.saved
        return False


def _index_like_main(world, video="/pool/src.mp4"):
    """The two calls in main()'s order: full frames under the shared memo,
    then the card probe per shot with it."""
    memo = ix.LetterboxMemo()
    with tempfile.TemporaryDirectory() as tmp:
        with ix.shared_letterbox(memo):
            frames = usability_probe.extract_full_frames(Path(video), SHOTS, Path(tmp))
        rates = [ix.probe_card_text(Path(video), s["start"], s["end"], letterbox=memo)
                 for s in SHOTS]
    return memo, frames, rates


def test_one_cropdetect_per_shot():
    with World() as w:
        memo, frames, rates = _index_like_main(w)
    assert len(w.cropdetects) == len(SHOTS), w.cropdetects
    assert memo.decodes == len(SHOTS), memo.decodes
    # Each shot asked once, with the usability probe's own arguments.
    assert [c[1] for c in w.cropdetects] == [s["start"] for s in SHOTS], w.cropdetects
    assert all(f is not None for f in frames), frames
    assert all(r == {"card": 0.0, "caption": 0.0, "branding": 0.0} for r in rates), rates
    # The card probe opened no cropdetect child of its own: nothing ran.
    assert not [a for t, a in w.children if a[1:2] == ["cropdetect"]], w.children


def test_the_reused_crop_still_reaches_both_ffmpeg_calls():
    with World(bars="crop=748:1080:586:0") as w:
        _index_like_main(w)
    full = [c for c in w.ffmpeg if c[-1].endswith("_full.png")]
    grabs = [c for c in w.ffmpeg if c[-1].endswith("ct%02d.png")]
    assert len(full) == len(SHOTS) and len(grabs) == len(SHOTS), w.ffmpeg
    for c in full:
        assert c[c.index("-vf") + 1] == "crop=748:1080:586:0", c
    for c in grabs:
        assert c[c.index("-vf") + 1].startswith("crop=748:1080:586:0,select="), c


def test_no_bars_is_remembered_too():
    """None (no bars) is an answer, not a miss - no second decode for it."""
    with World(bars=None) as w:
        _index_like_main(w)
    assert len(w.cropdetects) == len(SHOTS), w.cropdetects


def test_usability_probe_gets_its_own_function_back():
    with World() as w:
        mine = usability_probe.detect_letterbox
        memo = ix.LetterboxMemo()
        with ix.shared_letterbox(memo):
            assert usability_probe.detect_letterbox is memo
        assert usability_probe.detect_letterbox is mine
        try:
            with ix.shared_letterbox(memo):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert usability_probe.detect_letterbox is mine
    # And outside any test stand-in, it is prepare_clip's.
    import prepare_clip
    assert usability_probe.detect_letterbox is prepare_clip.detect_letterbox


def test_without_a_memo_the_probe_asks_itself():
    """remeasure scripts call probe_card_text() bare: cropdetect as before,
    under its own `cropdetect` child."""
    with World() as w:
        ix.probe_card_text("/pool/src.mp4", 2.0, 6.0)
    assert len(w.cropdetects) == 1, w.cropdetects
    assert [a[1] for t, a in w.children if t == "ffmpeg"] == ["cropdetect"], w.children


def test_a_memo_miss_decodes_once_and_is_kept():
    with World() as w:
        memo = ix.LetterboxMemo()
        ix.probe_card_text("/pool/src.mp4", 2.0, 6.0, letterbox=memo)
        ix.probe_card_text("/pool/src.mp4", 2.0, 6.0, letterbox=memo)
    assert len(w.cropdetects) == 1, w.cropdetects
    assert [a[1] for t, a in w.children if t == "ffmpeg"] == ["cropdetect"], w.children


def test_main_wires_the_memo():
    """main() opens the full-frame grab under shared_letterbox and passes the
    same memo to the card probe (a source check: main() needs a real video)."""
    import inspect
    src = inspect.getsource(ix.main)
    assert "letterbox = LetterboxMemo()" in src, src
    assert "shared_letterbox(letterbox)" in src, src
    assert "letterbox=letterbox" in src, src


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

#!/usr/bin/env python3
"""CF-0904: past the strip allowance the resolver cuts a cover-ready shot of
the same pool instead of one more picture its own probe frame says the 9:16
crop cuts.

After CF-0903 the strip a plan keeps past the signed allowance
(`shot_score.STRIP_ALLOW_SECONDS`, 5 s of `score.narrow_strip_on_blur`) is
the strip the plan's own probe asks for (`framed_by: probe`): a wide trailer
frame whose subject is wider than the crop. wildwood 0840Z, the-long-voyage 1624Z
and sandfall-part-three 0841Z kept 27-36 % of it while their works' pools held
cover-ready shots.

Pinned here, without ffmpeg, Vision or a real pool:
  * `strip_wide` / `clip_size` / `strip_seconds_of`: which cut is a strip
    the plan's probe asks for (16:9 and wider, first probe low, not a card);
  * usable() hands back its first probe's framing (`first_out`) - the frame
    build_render_plan.py frames the clip from;
  * end to end through main(): under the allowance the low-framed cut is
    taken as before; past it the cut is held back and the next cover-ready
    candidate of the same pool is the block's picture (`strip_picks`), the
    held cut's clip is thrown away and its line is in rejected_candidates;
  * with no cover-ready shot within STRIP_SPARE_CUTS the held cut is the
    picture after all (no hold line left behind, `length_supply` says cut),
    and so it is when the pool runs out - nothing is refused for the strip.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - run accounting never lands in a real batch
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import cache_fingerprint  # noqa: E402
import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402

IDX = "/idx/v.shots.json"
SRC = "/src/vid00000000.mp4"
WIDE = "1920x872"        # a 2.2:1 trailer frame: 0.255 of the screen shown whole


def need_indexer():
    if shot_score.indexer() is None:
        print("SKIP: footage-indexer's shot_usability.py is not beside the main checkout")
        return False
    return True


# --- which cut is a strip the probe asks for --------------------------------------
def test_strip_wide_is_16_9_and_wider():
    assert ra.strip_wide((1920, 1080))
    assert ra.strip_wide((1920, 872))
    assert ra.strip_wide((1920, 803))
    assert not ra.strip_wide((1440, 1080))      # 4:3 whole is 0.42 of the height
    assert not ra.strip_wide((1080, 1920))
    assert not ra.strip_wide(None)
    assert not ra.strip_wide((0, 0))


def test_clip_size_reads_the_cut_and_its_caption_crop():
    assert ra.clip_size({"frame_before_crop": "1920x1080", "crop_bottom": 0.0}) == (1920, 1080)
    w, h = ra.clip_size({"frame_before_crop": "1920x1080", "crop_bottom": 0.1})
    assert (w, round(h)) == (1920, 972)
    shot = {"usable_cached": {"width": 1280, "height": 720}}
    assert ra.clip_size({"frame_before_crop": None}, shot) == (1280, 720)
    assert ra.clip_size({}, {}) is None


def test_strip_seconds_need_a_low_first_probe_a_wide_clip_and_no_card():
    low, ok = [{"low_framing": True}], [{"low_framing": False}]
    wide = {"frame_before_crop": WIDE}
    tall = {"frame_before_crop": "1080x1920"}
    assert ra.strip_seconds_of(2.5, low, wide) == 2.5
    assert ra.strip_seconds_of(2.5, ok, wide) == 0.0
    assert ra.strip_seconds_of(2.5, [], wide) == 0.0
    assert ra.strip_seconds_of(2.5, low, tall) == 0.0
    assert ra.strip_seconds_of(2.5, low, wide, card=True) == 0.0


# --- usable() hands back the plan's own probe frame ---------------------------------
class _Out:
    def __init__(self, verdict):
        self.stdout, self.stderr, self.returncode = json.dumps(verdict), "", 0


def _verdict(coverage):
    v = {"usable": coverage >= 0.65, "failures": [], "failed": [],
         "roi_coverage": coverage, "roi_source": "faces",
         "coverage_window": {"focus": {"x": 0.5, "y": 0.5}, "zoom": 1.0}}
    if coverage < 0.65:
        v["failed"] = ["coverage"]
        v["failures"] = [f"coverage: {coverage:.0%} of the subject in the window"]
    return v


def _usable_with(coverages):
    saved = ra.grab_frames, ra.run_tool
    calls = iter(coverages)
    ra.grab_frames = lambda clip, first, step, n, pattern: [f"/nope/p{i}.png" for i in range(n)]
    ra.run_tool = lambda cmd, **kw: _Out(_verdict(next(calls)))
    try:
        soft, first = [], []
        with contextlib.redirect_stderr(io.StringIO()):
            ok, _ = ra.usable("/nope/clip.mp4", 3.0, 720, 0.65, 0.5,
                              soft_out=soft, first_out=first)
        return ok, soft, first
    finally:
        ra.grab_frames, ra.run_tool = saved


def test_usable_reports_the_first_probe_frame():
    ok, soft, first = _usable_with([0.30, 0.9, 0.9, 0.9])
    assert ok and soft == ["low_framing"], (ok, soft)
    assert len(first) == 1 and first[0]["low_framing"] is True, first
    assert first[0]["roi_coverage"] == 0.30, first


def test_a_later_frame_alone_is_not_the_plan_probe():
    """Low framing on a later probe only is the record-only case CF-0903
    takes back - not a strip this task counts."""
    ok, soft, first = _usable_with([0.9, 0.3, 0.9, 0.9])
    assert ok and soft == ["low_framing"], (ok, soft)
    assert first[0]["low_framing"] is False, first


# --- end to end through main() -------------------------------------------------------
def cached(**kw):
    c = {"roi_source": "faces", "roi_coverage": 0.9, "black_fraction": 0.02,
         "mean_luma": 80.0, "short_side": 872, "width": 1920, "height": 872,
         "measured_by": cache_fingerprint.usability_fingerprint()}
    c.update(kw)
    return c


def shot(n, start, end):
    # The pool's record says the crop keeps the subject for every shot - the
    # cut clip's own probe is what finds it low (the stand-in usable below).
    return {"index": n, "start": start, "end": end, "on_topic": True,
            "burned_text": False, "description": f"shot {n}",
            "usable_cached": cached()}


@contextlib.contextmanager
def _patched(index_shots, pools, low):
    names = ("match", "cut", "usable", "audio_duration", "leading_silence", "load_words")
    saved = {k: getattr(ra, k) for k in names}
    index_data = {IDX: {"source": SRC, "shots": index_shots}}
    by = {s["index"]: s for s in index_shots}
    cuts = []

    def fake_match(indexes, phrases, min_score, top, python):
        out = []
        for ph in phrases:
            cands = [{"shot": n, "score": sc, "start": by[n]["start"], "end": by[n]["end"],
                      "card": False, "promoted": False, "index": IDX, "source": SRC}
                     for n, sc in pools[ph]]
            out.append({"phrase": ph, "found": True, "discriminative": True,
                        "margin": 0.1, "candidates": ra.order_candidates(cands, 0)})
        return out, index_data

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        cuts.append(int(re.search(r"_s(\d+)\.mp4$", str(dest)).group(1)))
        return {"crop_bottom": 0.0, "frame_before_crop": WIDE}

    def fake_usable(clip, seconds, *a, soft_out=None, first_out=None, **kw):
        n = int(re.search(r"_s(\d+)\.mp4$", str(clip)).group(1))
        if n in low:
            if soft_out is not None:
                soft_out.append(shot_score.LOW_FRAMING)
        if first_out is not None:
            first_out.append({"offset": 0.5, "roi_coverage": 0.3 if n in low else 0.9,
                              "low_framing": n in low})
        return True, []

    ra.match, ra.cut, ra.usable = fake_match, fake_cut, fake_usable
    ra.audio_duration = lambda path: 16.0
    ra.leading_silence = lambda path: 0.0
    ra.load_words = lambda path: [{"word": "w", "start": 0.5 * i, "end": 0.5 * i + 0.4}
                                  for i in range(32)]
    try:
        yield cuts
    finally:
        for k, v in saved.items():
            setattr(ra, k, v)


PHRASES = ["a sand sandfall at dusk", "a rider on a worm", "a ship over the desert",
           "a duel in a hall"]


EXTRA = ["--rhythm", "even"]   # one ~4 s block per anchor


def _run_main(index_shots, pools, low, extra=None):
    with tempfile.TemporaryDirectory() as tmp, _patched(index_shots, pools, low) as cuts:
        tmp = Path(tmp)
        anchors = tmp / "anchors.json"
        anchors.write_text(json.dumps({"script_id": "t", "anchors": [
            {"word_index": 1 + 8 * k, "phrase": ph, "emphasis_words": []}
            for k, ph in enumerate(PHRASES)]}))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(anchors), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out), "--index", IDX,
                "--clips-dir", str(tmp / "clips"), "--min-score", "0.22",
                "--no-stretch-split"] + (extra or EXTRA)
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                ra.main()
        finally:
            sys.argv = saved_argv
        story = json.loads(out.read_text())
        clips = sorted(p.name for p in (tmp / "clips").glob("*.mp4"))
        return story, list(cuts), clips


def _pool(n_low, n_clean, base):
    """Per phrase: `n_low` low-framed shots ranked first, then `n_clean`
    cover-ready ones - every one long enough for its block."""
    shots, pools, low = [], {}, set()
    n = base
    for k, ph in enumerate(PHRASES):
        pools[ph] = []
        for j in range(n_low + n_clean):
            shots.append(shot(n, 10.0 * n, 10.0 * n + 8.0))
            pools[ph].append((n, 0.40 - 0.01 * j))
            if j < n_low:
                low.add(n)
            n += 1
    return shots, pools, low


def _block_shot(b):
    return int(str(b["shot"]).rsplit(":", 1)[1])


def test_past_the_allowance_a_cover_ready_shot_is_cut():
    if not need_indexer():
        return
    shots, pools, low = _pool(1, 1, 1)
    story, cuts, clips = _run_main(shots, pools, low)
    blocks = [b for b in story["blocks"] if b.get("shot")]
    assert len(blocks) == 4, [b.get("shot") for b in story["blocks"]]
    picks = story["strip_picks"]
    assert picks["task"] == "CF-0904" and picks["allow_seconds"] == 5.0, picks
    # The first block's ~4 s strip is within the allowance: taken as before.
    assert _block_shot(blocks[0]) in low, blocks[0]["shot"]
    # Every later block: the low-framed cut held back, the clean one shown.
    for b in blocks[1:]:
        assert _block_shot(b) not in low, [x["shot"] for x in blocks]
    assert len(picks["picks"]) == 3, picks
    assert all(p["outcome"] == "cover_ready_picked" and p["picked"] for p in picks["picks"]), picks
    assert picks["probe_strip_seconds"] <= 5.0 + 1e-6, picks
    held = [r for r in story["rejected_candidates"] if r.get("strip_hold") == "CF-0904"]
    assert len(held) == 3, story["rejected_candidates"]
    # The held cuts' clips are gone; the clips on disk are the blocks' own.
    shown = {_block_shot(b) for b in blocks}
    assert {int(re.search(r"_s(\d+)\.mp4$", c).group(1)) for c in clips} == shown, clips


def test_no_cover_ready_shot_within_the_spare_cuts_takes_the_held_one():
    if not need_indexer():
        return
    n_low = ra.STRIP_SPARE_CUTS + 2
    shots, pools, low = _pool(n_low, 1, 1)
    # Staccato: one-shot blocks, so each carries its `length_supply`.
    story, cuts, clips = _run_main(shots, pools, low, ["--rhythm", "staccato"])
    blocks = [b for b in story["blocks"] if b.get("shot")]
    assert all(_block_shot(b) in low for b in blocks), [b["shot"] for b in blocks]
    later = [p for p in story["strip_picks"]["picks"]]
    assert later and all(p["outcome"] == "spare_cuts_spent" and p["picked"] is None
                         and p["spare_cuts"] == ra.STRIP_SPARE_CUTS for p in later), later
    # The held cut is the picture: no hold line left behind for it, and its
    # length record says cut.
    assert not [r for r in story["rejected_candidates"] if r.get("strip_hold")], \
        story["rejected_candidates"]
    for b in blocks[1:]:
        rec = {e["shot"]: e for e in b["length_supply"]["long_enough"]}
        assert rec[b["shot"]]["outcome"] == ra.LENGTH_CUT, (b["shot"], rec)
    # The clean shot past the spare cuts was never cut.
    clean = {n for n, _ in sum(pools.values(), [])} - low
    assert not clean & set(cuts), (clean, cuts)


def test_a_pool_without_a_cover_ready_shot_takes_the_held_one():
    if not need_indexer():
        return
    shots, pools, low = _pool(2, 0, 1)
    story, cuts, clips = _run_main(shots, pools, low)
    blocks = [b for b in story["blocks"] if b.get("shot")]
    assert len(blocks) == 4 and all(_block_shot(b) in low for b in blocks), \
        [b.get("shot") for b in story["blocks"]]
    outcomes = {p["outcome"] for p in story["strip_picks"]["picks"]}
    assert outcomes == {"pool_spent"}, story["strip_picks"]


def test_a_held_long_shot_is_not_traded_for_a_short_one():
    """CF-0517 (length first) stands: a one-shot block whose held cut is long
    enough does not take a cover-ready shot too short for it."""
    if not need_indexer():
        return
    shots, pools, low = [], {}, set()
    n = 1
    for ph in PHRASES:
        shots.append(shot(n, 10.0 * n, 10.0 * n + 8.0))        # long, low-framed
        shots.append(shot(n + 1, 10.0 * n + 8.5, 10.0 * n + 9.7))   # 1.2 s, clean
        pools[ph] = [(n, 0.40), (n + 1, 0.39)]
        low.add(n)
        n += 2
    story, cuts, clips = _run_main(shots, pools, low, ["--rhythm", "staccato"])
    picks = story["strip_picks"]["picks"]
    outcomes = {p["outcome"] for p in picks}
    assert "no_long_enough_shot" in outcomes, picks
    assert "cover_ready_picked" not in outcomes, picks
    assert all(p["spare_cuts"] == 0 for p in picks
               if p["outcome"] == "no_long_enough_shot"), picks


def test_under_the_allowance_nothing_is_held():
    if not need_indexer():
        return
    shots, pools, low = _pool(1, 1, 1)
    low = {min(low)}   # one low-framed shot in the video: ~4 s, within 5 s
    story, cuts, clips = _run_main(shots, pools, low)
    assert story["strip_picks"]["picks"] == [], story["strip_picks"]
    assert not [r for r in story["rejected_candidates"] if r.get("strip_hold")]


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

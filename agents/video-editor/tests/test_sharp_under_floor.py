#!/usr/bin/env python3
"""CF-0537 (the user's decision of 2026-10-05): a soft shot over the similarity
floor yields to a sharp shot of the same phrase just under it.

delver of `example-film/2026-10-05T0701Z`, block 2 ("A huge indoor crowd
gathered under an ornate rotunda ceiling."): the phrase's sharp shots at or
above 0.22 were spent by block 1 and by earlier delver videos, and the one
shot left over the floor was `ZLXL1L0TfsI:15` - the 1920x786 scope trailer,
`low_sharpness` 0.51 under the 0.57 floor (warned: the price stays unsigned).
The phrase's sharp candidates sat at 0.2194 / 0.2158 / 0.2155. Now, when every
cut a block got from its match is soft, the phrase's measured-sharp candidates
under the floor (`below_floor_pool()` - the lower bound the CF-0536 split
already goes on into, no new threshold) are walked through every gate, and a
survivor replaces the soft cut; the block is marked `below_floor` and priced
`score.low_similarity` (-3, signed) like any block filled under the floor.

Fixtures only - nothing here reads pipeline/. No pytest dependency.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0537s-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402
import shot_score  # noqa: E402

TMP = tmp_root("cf0537s-")
MEASURE = "CF-0452/test/v1"
FLOOR = 0.22
PHRASE = "A huge indoor crowd gathered under an ornate rotunda ceiling."


class _Sharp:
    """A stand-in for footage-indexer's sharpness.py: fresh when stamped with
    MEASURE, low_sharpness under 0.57, no `mode` (so: warn, unsigned)."""
    def is_fresh(self, r):
        return isinstance(r, dict) and r.get("measured_by") == MEASURE

    def verdict(self, r, held=False):
        v = r.get("value")
        return ({"rule": "low_sharpness", "value": v, "floor": 0.57, "held": held}
                if v < 0.57 else None)


@contextlib.contextmanager
def _sharp():
    saved = dict(shot_score._MEMO)
    shot_score._MEMO["sharp"] = _Sharp()
    try:
        yield
    finally:
        shot_score._MEMO.clear()
        shot_score._MEMO.update(saved)


def _rec(v):
    return {"measured_by": MEASURE, "value": v}


# ---------------------------------------------------------------- the parts

def test_soft_cut_reads_the_storyboard_record():
    assert ra.soft_cut({"usability": {"warn": ["low_sharpness"], "soft": []}})
    assert ra.soft_cut({"usability": {"soft": ["low_sharpness"]}})   # signed
    assert not ra.soft_cut({"usability": {"soft": ["low_coverage"]}})
    assert not ra.soft_cut({})


def test_only_a_measured_sharp_shot_is_called_sharp():
    lut = {("i", 1): {"index": 1, "start": 0, "end": 5, "sharpness_cached": _rec(0.7)},
           ("i", 2): {"index": 2, "start": 0, "end": 5, "sharpness_cached": _rec(0.51)},
           ("i", 3): {"index": 3, "start": 0, "end": 5}}
    with _sharp():
        assert ra.measured_sharp({"index": "i", "shot": 1, "source": "v"}, lut)
        assert not ra.measured_sharp({"index": "i", "shot": 2, "source": "v"}, lut)
        assert not ra.measured_sharp({"index": "i", "shot": 3, "source": "v"}, lut), \
            "an unmeasured shot is not traded for at a price"
        assert not ra.measured_sharp({"index": "i", "shot": 1, "source": "v",
                                      "card": True}, lut)


def test_the_sharp_pool_is_the_phrase_under_the_floor_measured_sharp():
    lut = {("i", n): {"index": n, "start": 0, "end": 5, "sharpness_cached": _rec(v)}
           for n, v in ((1, 0.7), (2, 0.51), (3, 0.8), (4, 0.75), (5, 0.9))}
    cands = [{"index": "i", "shot": n, "score": s, "source": "v", "start": 0, "end": 5}
             for n, s in ((1, 0.2194), (2, 0.2158), (3, 0.2155), (4, 0.30), (5, 0.10))]
    with _sharp():
        got = ra.sharp_under_pool(cands, FLOOR, None, lut, skip={("v", 3)})
        assert [c["shot"] for c in got] == [1, 5], got
        # --score-floor is the one floor under it, as for below_floor_pool()
        got = ra.sharp_under_pool(cands, FLOOR, 0.15, lut)
        assert [c["shot"] for c in got] == [1, 3], got


def test_the_closest_unmeasured_shots_are_measured_first():
    """The old pool stores no sharpness: the pool is asked in score order (the
    rank probes only its cleanest top three, and delver 0701Z's 0.2194 shot -
    a dark doorway, sharp 0.68 - was never measured that way)."""
    lut = {("i", n): {"index": n, "start": 0, "end": 5} for n in range(1, 6)}
    cands = [{"index": "i", "shot": n, "score": 0.22 - n / 1000, "source": "v",
              "start": 0, "end": 5} for n in range(1, 6)]
    measured = []
    saved = (shot_score.probe_sharpness, shot_score._wants_probe)

    def probe(shot, video):
        measured.append(shot["index"])
        shot["sharpness_cached"] = _rec(0.7 if shot["index"] != 1 else 0.5)
        return shot["sharpness_cached"]
    shot_score.probe_sharpness = probe
    shot_score._wants_probe = lambda c, shot, video: "sharpness_cached" not in shot
    try:
        with _sharp():
            got = ra.sharp_under_pool(cands, FLOOR, None, lut)
    finally:
        shot_score.probe_sharpness, shot_score._wants_probe = saved
    assert measured == [1, 2, 3], measured          # SHARPNESS_PROBES_PER_RANK
    assert [c["shot"] for c in got] == [2, 3], got  # 1 soft, 4-5 unmeasured


def test_the_ledger_gives_a_take_back():
    led = rhythm.ShotLedger(1)
    led.take(("v", 1))
    assert led.blocked(("v", 1))
    assert led.give_back(("v", 1)) == 0 and not led.blocked(("v", 1))
    assert led.give_back(("v", 9)) == 0 and led.uses() == {}


# ----------------------------------------------------- resolve_anchors.main()

def _run(shots, block=5.0):
    """One `hold` block over `shots`: [(name, score, seconds, sharpness)]."""
    index_path = "/nowhere/src.shots.json"
    source = "/nowhere/src.mp4"
    index_data = {index_path: {"source": source, "shots": [
        {"index": n, "start": 0.0, "end": sec, "description": f"shot {n}",
         **({"sharpness_cached": _rec(v)} if v is not None else {})}
        for n, (_name, _s, sec, v) in enumerate(shots, 1)]}}

    def fake_match(indexes, phrases, min_score, top, python):
        cands = [{"shot": n, "score": s, "start": 0.0, "end": sec, "card": False,
                  "promoted": False, "index": index_path, "source": source}
                 for n, (_name, s, sec, _v) in enumerate(shots, 1)]
        cands = ra.order_candidates(cands, 0)
        return [{"phrase": ph, "found": True, "discriminative": True, "margin": 0.1,
                 "candidates": cands} for ph in phrases], index_data

    def fake_cut(src, start, dur, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"clip")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_grab(clip, at, dest):
        Path(dest).write_bytes(b"")
        return str(dest)

    names = ("match", "cut", "usable", "audio_duration", "leading_silence",
             "load_words", "grab_frame")
    saved = {k: getattr(ra, k) for k in names}
    ra.match, ra.cut, ra.grab_frame = fake_match, fake_cut, fake_grab
    ra.usable = lambda *a, **kw: (True, [])
    ra.audio_duration = lambda path: block
    ra.leading_silence = lambda path: 0.0
    ra.load_words = lambda path: [{"word": "w", "start": 0.05 + i * block / 12,
                                   "end": 0.1 + i * block / 12} for i in range(10)]
    tmp = Path(TMP) / f"run{len(list(Path(TMP).iterdir()))}"
    tmp.mkdir(parents=True)
    src = tmp / "anchors.json"
    src.write_text(json.dumps({"script_id": "t", "anchors": [
        {"word_index": 1, "phrase": PHRASE, "emphasis_words": []}]}))
    out = tmp / "storyboard.json"
    argv = ["resolve_anchors.py", str(src), str(tmp / "words.json"), str(tmp / "voice.wav"),
            str(out), "--index", index_path, "--clips-dir", str(tmp / "clips"),
            "--rhythm", "hold", "--min-score", str(FLOOR)]
    err = io.StringIO()
    saved_argv, sys.argv = sys.argv, argv
    try:
        with _sharp(), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            ra.main()
    finally:
        sys.argv = saved_argv
        for k, v in saved.items():
            setattr(ra, k, v)
    return json.loads(out.read_text()), err.getvalue(), tmp / "clips"


def test_a_soft_shot_over_the_floor_yields_to_a_sharp_one_under_it():
    # delver 0701Z block 2's shape: the soft trailer shot alone over the floor
    story, err, clips = _run([("soft", 0.25, 12.9, 0.51), ("sharp", 0.2194, 6.0, 0.72),
                              ("unmeasured", 0.2190, 6.0, None)])
    b = story["blocks"][0]
    assert b["shot"] == "src:2", b
    bf = b["below_floor"]
    assert bf["score"] == 0.2194 and bf["min_score"] == FLOOR, bf
    sw = bf["sharp_swap"]
    assert sw["task"] == "CF-0537" and sw["shots"] == ["src:2"], sw
    assert sw["instead_of"][0]["shot"] == "src:1" and sw["instead_of"][0]["sharpness"] == 0.51
    assert "SHARP UNDER THE FLOOR" in err, err
    assert not any("src_s001" in p.name for p in clips.iterdir()), \
        "the soft cut's clip is removed"
    assert "src:1" not in {x.get("shot") for x in story["blocks"]}


def test_without_a_sharp_shot_under_the_floor_the_soft_one_stays():
    story, err, _ = _run([("soft", 0.25, 12.9, 0.51), ("soft_under", 0.2194, 6.0, 0.50)])
    b = story["blocks"][0]
    assert b["shot"] == "src:1" and "below_floor" not in b, b
    assert "SHARP UNDER THE FLOOR" not in err


def test_a_sharp_shot_over_the_floor_is_not_traded():
    story, err, _ = _run([("sharp", 0.25, 12.9, 0.70), ("sharper_under", 0.2194, 6.0, 0.90)])
    b = story["blocks"][0]
    assert b["shot"] == "src:1" and "below_floor" not in b, b


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
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

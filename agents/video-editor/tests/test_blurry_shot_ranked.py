#!/usr/bin/env python3
"""CF-0452 (editor half): a blurry shot ranks behind a sharp one, a held
frame is the shot's sharpest moment, and `low_sharpness` is a warning until
the root signs its price.

The indexer's `sharpness.py` (part 1, branch ready/CF-0452 of footage-indexer)
and `shot_usability.py` are replaced with stubs of their interface, so the
test pins this repo's side only:
  * no module -> the order is CF-0436's and nothing is measured;
  * `low_sharpness` in the pool record's `warn` (unsigned) puts the shot
    behind a clean one of the same score, sharper first among blurry ones,
    the matcher's order kept among sharp ones;
  * the old pool (no `sharpness_cached`) is measured on the fly for the top
    SHARPNESS_PROBES_PER_RANK candidates only, once per shot, never cards,
    and within the run's ceiling;
  * the storyboard record: `warn` unsigned, `soft` + price signed;
    plan_findings charges it only while the table carries the row;
  * a held frame is lifted at `best_at` - from the clip when the moment is
    inside it, from a fresh snippet of the source when it is not; without a
    fresh record the frame is the old one.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0452-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402

MEASURE = "CF-0452/crete-tiles-p90/v1"
FLOOR = 0.57
TMP = tmp_root("cf0452-")
VIDEO = TMP / "vid00000000.mp4"
VIDEO.write_bytes(b"not a real video - the stub never opens it")


def rec(value, best=None, best_at=3.0, measured_by=MEASURE):
    return {"task": "CF-0452", "measured_by": measured_by, "value": value,
            "best": value if best is None else best, "best_at": best_at,
            "motion": 0.0, "motion_excused": False, "frames": [], "floor": FLOOR}


class StubSharpness:
    """sharpness.py's interface as part 1 hands it over."""
    RULE = "low_sharpness"
    MIN_SHARPNESS = FLOOR

    def __init__(self, measured=None, signed=False, price=3):
        self.measured = measured or {}   # shot index -> value
        self.calls = []
        self.signed, self.price = signed, price

    def is_fresh(self, r):
        return isinstance(r, dict) and r.get("measured_by") == MEASURE

    def verdict(self, r, held=False):
        v = r["best"] if held else r["value"]
        if v >= FLOOR:
            return None
        return {"rule": self.RULE, "value": v, "floor": FLOOR, "held": held}

    def of_shot(self, shot, video):
        self.calls.append(shot["index"])
        return rec(self.measured.get(shot["index"], 0.9))

    def mode(self):
        return {"mode": "penalty" if self.signed else "warn",
                "price": self.price, "price_key": "score.low_sharpness",
                "signed": self.signed}


class StubUsability:
    """shot_usability.of(): what the shot's `u` field says, else clean."""
    def of(self, shot, measurements=True):
        return shot.get("u") or {"soft": [], "hard": [], "warn": [], "score": 1.0}

    def prices(self):
        return {"low_framing": 3, "low_brightness": 3, "low_resolution": 2,
                "off_topic_shot": 4}


def install(sharp, usab=None):
    shot_score._MEMO.clear()
    shot_score._MEMO["sharp"] = sharp
    shot_score._MEMO["mod"] = usab if usab is not None else StubUsability()
    shot_score._SHARP.clear()
    shot_score._SHARP_RUN["probes"] = 0


def shot(n, **kw):
    s = {"index": n, "start": 0.0, "end": 8.0}
    s.update(kw)
    return s


def cand(n, card=False):
    return {"shot": n, "index": "/idx/v.shots.json", "source": str(VIDEO),
            "start": 0.0, "end": 8.0, "score": 0.3, "card": card}


def lut_of(shots):
    return {("/idx/v.shots.json", s["index"]): s for s in shots}


def order(pool, lut):
    return [c["shot"] for c in ra.rank_by_usability(pool, lut)]


def warn_u(value):
    return {"soft": [], "hard": [], "score": 1.0, "sharpness": value,
            "warn": [{"rule": "low_sharpness", "value": value, "floor": FLOOR,
                      "price_key": "score.low_sharpness", "signed": False,
                      "proposed_price": 3}]}


# --- item 1: the rank -------------------------------------------------------

def test_without_the_module_nothing_is_measured_and_the_order_stands():
    install(None)
    shots = [shot(i) for i in range(4)]
    assert order([cand(i) for i in range(4)], lut_of(shots)) == [0, 1, 2, 3]
    assert shot_score.blur_rank(None, shots[0], str(VIDEO)) == 0.0
    assert shot_score.record(shots[0], (), video=str(VIDEO)) is None


def test_a_warned_blurry_shot_ranks_behind_a_sharp_one_of_its_score():
    install(StubSharpness())
    shots = [shot(0, u=warn_u(0.30)), shot(1), shot(2, u=warn_u(0.50)), shot(3)]
    # sharp ones in the matcher's order, then the blurry ones sharper first
    assert order([cand(i) for i in range(4)], lut_of(shots)) == [1, 3, 2, 0]


def test_the_score_still_comes_first_blur_is_a_rank_among_equals():
    install(StubSharpness())
    weak = {"soft": [{"rule": "off_topic_shot", "price": 4}], "hard": [], "score": 0.96}
    shots = [shot(0, u=warn_u(0.30)), shot(1, u=weak)]
    # the blurry shot of score 1.0 beats the off-topic one of 0.96
    assert order([cand(1), cand(0)], lut_of(shots)) == [0, 1]


def test_a_fresh_pool_record_ranks_without_a_measure():
    sharp = StubSharpness()
    install(sharp)
    shots = [shot(0, sharpness_cached=rec(0.35)), shot(1, sharpness_cached=rec(0.8)),
             shot(2, sharpness_cached=rec(0.2, measured_by="CF-0452/old/v0"))]
    got = order([cand(0), cand(1)], lut_of(shots))
    assert got == [1, 0] and sharp.calls == []
    # a record another measure wrote is not read - that shot is measured anew
    assert order([cand(2)], lut_of(shots)) == [2] and sharp.calls == [2]


def test_the_old_pool_is_measured_on_the_fly_top_candidates_only():
    sharp = StubSharpness(measured={0: 0.30, 1: 0.40, 2: 0.9, 3: 0.9, 4: 0.9, 5: 0.9})
    install(sharp)
    shots = [shot(i) for i in range(6)]
    lut = lut_of(shots)
    got = order([cand(i) for i in range(6)], lut)
    # at most SHARPNESS_PROBES_PER_RANK measures, the blurry top ones drop
    assert len(sharp.calls) <= shot_score.SHARPNESS_PROBES_PER_RANK
    assert got[0] == 2 and got[-2:] == [1, 0], got
    assert 5 not in sharp.calls
    # measured once per run: a second rank of the same pool measures nothing new
    n = len(sharp.calls)
    order([cand(0), cand(1), cand(2)], lut)
    assert len(sharp.calls) == n


def test_cards_missing_files_and_the_run_ceiling_are_not_measured():
    sharp = StubSharpness(measured={0: 0.1})
    install(sharp)
    shots = [shot(0), shot(1, is_card=True)]
    order([cand(0, card=True), cand(1)], lut_of(shots))
    assert sharp.calls == []
    missing = [dict(cand(0), source=str(TMP / "gone.mp4"))]
    order(missing, lut_of(shots))
    assert sharp.calls == []
    shot_score._SHARP_RUN["probes"] = shot_score.SHARPNESS_PROBES_PER_RUN
    order([cand(0)], lut_of(shots))
    assert sharp.calls == []


def test_a_failed_measure_is_not_blurry_and_not_tried_again():
    class Broken(StubSharpness):
        def of_shot(self, shot, video):
            self.calls.append(shot["index"])
            raise RuntimeError("ffmpeg said no")
    sharp = Broken()
    install(sharp)
    shots = [shot(0), shot(1)]
    assert order([cand(0), cand(1)], lut_of(shots)) == [0, 1]
    order([cand(0), cand(1)], lut_of(shots))
    assert sharp.calls == [0, 1]


# --- item 3: warn until signed, the price is the table's ---------------------

def test_the_record_warns_until_signed_and_is_priced_once_signed():
    install(StubSharpness(signed=False))
    s = shot(0, sharpness_cached=rec(0.40))
    r = shot_score.record(s, (), video=str(VIDEO))
    assert r["soft"] == [] and r["warn"] == ["low_sharpness"]
    assert r["penalty"] == 0 and r["score"] == 1.0
    assert r["sharpness"]["value"] == 0.40 and r["sharpness"]["signed"] is False
    install(StubSharpness(signed=True, price=3))
    r = shot_score.record(s, ("low_framing",), video=str(VIDEO))
    assert r["soft"] == ["low_framing", "low_sharpness"] and "warn" not in r
    assert r["penalty"] == 6 and r["score"] == 0.94
    # judged again as a held frame at its best moment: sharp -> price gone
    again = shot_score.with_sharpness(r, None)
    assert again["soft"] == ["low_framing"] and again["penalty"] == 3
    assert shot_score.with_sharpness(shot_score.record(
        shot(1, sharpness_cached=rec(0.4)), (), video=str(VIDEO)), None) is None


def test_plan_findings_charge_low_sharpness_only_while_the_table_has_the_row():
    install(StubSharpness(signed=True))
    blocks = [{"start": 5.0, "shot": "v:0",
               "usability": {"soft": ["low_sharpness"], "penalty": 3}},
              {"start": 9.0, "shot": "v:1",
               "usability": {"soft": [], "warn": ["low_sharpness"], "penalty": 0}}]
    fin = lambda rule, where, hook=False, note=None: {"rule": rule, **where}
    hook = lambda t: False
    saved = shot_score._priced
    try:
        shot_score._priced = lambda key: False
        assert shot_score.plan_findings(blocks, finding=fin, in_hook=hook) == []
        shot_score._priced = lambda key: key == "score.low_sharpness"
        got = shot_score.plan_findings(blocks, finding=fin, in_hook=hook)
        assert [(f["rule"], f["shot"]) for f in got] == [("score.low_sharpness", "v:0")]
    finally:
        shot_score._priced = saved


# --- item 2: a held frame is the shot's sharpest moment ----------------------

class Grabs:
    """Stand-ins for common.grab_frame and resolve_anchors.cut."""
    def __init__(self, ok=True):
        self.grabs, self.cuts, self.ok = [], [], ok

    def grab(self, source, at, dest, extra_vf=None):
        self.grabs.append((Path(str(source)).name, at))
        if self.ok:
            Path(dest).write_bytes(b"png")
        return self.ok

    def cut(self, source, start, duration, dest, crop_bottom=None, card=False):
        self.cuts.append((start, duration, crop_bottom, card))
        Path(dest).write_bytes(b"mp4")
        return {"crop_bottom": crop_bottom or 0.0}


def held(used, g):
    saved = ra.grab_frame, ra.cut
    ra.grab_frame, ra.cut = g.grab, g.cut
    try:
        dest = TMP / f"held_{len(g.grabs)}_{len(g.cuts)}.png"
        return ra.hold_frame(str(TMP / "clip.mp4"), used["seconds"], dest, used=used)
    finally:
        ra.grab_frame, ra.cut = saved


def used_rec(sharp, cut_at=20.0, seconds=2.0):
    return {"clip": str(TMP / "clip.mp4"), "shot": 21, "key": (str(VIDEO), 21),
            "seconds": seconds, "cut_at": cut_at, "crop_bottom": 0.12,
            "card": False, **({"sharpness": sharp} if sharp else {})}


def test_a_held_frame_inside_the_clip_is_lifted_at_best_at():
    install(StubSharpness())
    g = Grabs()
    u = used_rec(rec(0.524, best=0.728, best_at=21.3))
    assert held(u, g)
    assert g.grabs == [("clip.mp4", 1.3)] and g.cuts == []
    assert u["held_from"] == {"task": "CF-0452", "at": 21.3, "sharpness": 0.728,
                              "from": "clip"}


def test_a_best_moment_outside_the_clip_is_cut_from_the_source():
    install(StubSharpness())
    g = Grabs()
    u = used_rec(rec(0.524, best=0.728, best_at=26.0))
    assert held(u, g)
    # the clip's own caption crop, a half-second snippet, its first frame
    assert g.cuts == [(26.0, ra.HELD_SNIPPET_SECONDS, 0.12, False)]
    assert g.grabs[-1][1] == 0 and u["held_from"]["from"] == "source"
    assert not list(TMP.glob("*_best.mp4"))   # the snippet is not left behind


def test_without_a_fresh_record_the_frame_is_the_old_one():
    for sharp, module in ((None, StubSharpness()),
                          (rec(0.5, best_at=21.0, measured_by="x/old"), StubSharpness()),
                          (rec(0.5, best_at=21.0), None)):
        install(module)
        g = Grabs()
        u = used_rec(sharp)
        assert held(u, g)
        assert g.grabs == [("clip.mp4", 1.0)] and "held_from" not in u


def test_a_failed_best_grab_falls_back_to_the_old_frame():
    install(StubSharpness())

    class FailFirst(Grabs):
        def grab(self, source, at, dest, extra_vf=None):
            self.grabs.append((Path(str(source)).name, at))
            if len(self.grabs) == 1:
                return False
            Path(dest).write_bytes(b"png")
            return True
    g = FailFirst()
    u = used_rec(rec(0.4, best=0.7, best_at=21.0))
    assert held(u, g)
    assert g.grabs == [("clip.mp4", 1.0), ("clip.mp4", 1.0)] and "held_from" not in u


def test_the_held_block_is_judged_again_at_its_best_moment():
    install(StubSharpness(signed=True, price=3))
    sharp = rec(0.524, best=0.728, best_at=21.3)
    u = used_rec(sharp)
    u["usability"] = shot_score.record(shot(21, sharpness_cached=sharp), (),
                                       video=str(VIDEO))
    assert u["usability"]["soft"] == ["low_sharpness"]
    # not held -> the cut's own record; held at 0.728 -> sharp, nothing to pay
    assert ra.held_usability(u, False) == u["usability"]
    u["held_from"] = {"at": 21.3}
    assert ra.held_usability(u, True) is None
    # still under the floor at its best -> judged as held, priced
    blurry = rec(0.3, best=0.4, best_at=21.3)
    u2 = dict(used_rec(blurry), held_from={"at": 21.3})
    u2["usability"] = shot_score.record(shot(21, sharpness_cached=blurry), (),
                                        video=str(VIDEO))
    r = ra.held_usability(u2, True)
    assert r["soft"] == ["low_sharpness"] and r["sharpness"]["held"] is True
    assert r["sharpness"]["value"] == 0.4 and r["penalty"] == 3


def test_a_split_or_sequence_record_carries_held_from_on_the_held_frame_only():
    c = {"asset": "a.png", "kind": "still", "held_frame": True, "source": str(VIDEO),
         "shot": 21, "score": 0.3, "at": 1.0, "seconds": 1.0, "card": False,
         "held_from": {"at": 21.3}}
    assert ra.split_cut_record(c)["held_from"] == {"at": 21.3}
    assert "held_from" not in ra.split_cut_record({**c, "held_frame": False})


def test_the_editor_never_writes_the_price_row():
    # CF-0320: the table is the root's - no low_sharpness row is written here
    src = (SCRIPTS / "shot_score.py").read_text()
    assert "write_text" not in src and '"w"' not in src and "'w'" not in src


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e!r}")
    install(None)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""CF-0435: the resolver takes the best shot it has, and a weak one carries
its price to the plan.

Pinned at the resolver's own seams, with cut() and qc_asset.py stubbed:
  * the pre-cut filter no longer refuses framing / brightness / resolution
    under their floors, nor `on_topic: false`; it still refuses a black or an
    empty frame on a fresh cache, and `entity_guard` still refuses
    `burned_text: true` - the hard list;
  * candidates are ranked clean first, then weak by usability score;
  * with a clean candidate in the pool the clean one is cut; when the clean
    one fails its real gate (hard), the weak one is cut and its record carries
    the soft rules (`usability`) - the clip's measured ones plus
    `off_topic_shot` from the flag;
  * the record reaches the storyboard block and a sequence's cut.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0435-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import cache_fingerprint  # noqa: E402
import entity_guard  # noqa: E402
import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402

THRESHOLDS = (720, 0.65, ra.MAX_BLACK_CLIPS)
ARGS = SimpleNamespace(min_short_side=720, min_coverage=0.65,
                       max_black=ra.MAX_BLACK_CLIPS)
IDX = "/idx/v.shots.json"


def cached(**kw):
    c = {"roi_source": "face", "roi_coverage": 0.9, "black_fraction": 0.02,
         "mean_luma": 80.0, "short_side": 1080, "width": 1920, "height": 1080,
         "measured_by": cache_fingerprint.usability_fingerprint()}
    c.update(kw)
    return c


def shot(n, cache=None, **kw):
    s = {"index": n, "start": 0.0, "end": 8.0, "on_topic": True,
         "burned_text": False, "usable_cached": cached(**(cache or {}))}
    s.update(kw)
    return s


def cand(n, score=0.30):
    return {"shot": n, "start": 0.0, "end": 8.0, "score": score, "card": False,
            "promoted": False, "index": IDX, "source": "/src/vid00000000.mp4"}


def need_indexer():
    if shot_score.indexer() is None:
        print("SKIP: footage-indexer's shot_usability.py is not beside the main checkout")
        return False
    return True


# --- the pre-cut filter -------------------------------------------------------

def test_soft_floors_and_off_topic_are_not_refused_before_the_cut():
    if not need_indexer():
        return
    for s in (shot(1, {"roi_coverage": 0.40}),
              shot(2, {"mean_luma": 12.0}),
              shot(3, {"short_side": 480, "width": 854, "height": 480}),
              shot(4, on_topic=False)):
        assert ra.precut_cache_refusal(s, *THRESHOLDS) is None, s
        at, origin, span, refusal = ra.precut_refusal(cand(s["index"]), s, *THRESHOLDS,
                                                      need=3.0)
        assert refusal is None, (s, refusal)
        assert entity_guard.refusal("/src/vid00000000.mp4", s["index"], s, {}) is None


def test_black_empty_and_burned_text_stay_out():
    if not need_indexer():
        return
    black = shot(5, {"black_fraction": 0.97, "mean_luma": 2.0})
    empty = shot(6, {"roi_source": "none", "roi_coverage": 0.0})
    for s, rule in ((black, "black_frame"), (empty, "empty_frame")):
        why = ra.precut_cache_refusal(s, *THRESHOLDS)
        assert why and rule in why, why
    burned = shot(7, burned_text=True)
    assert entity_guard.refusal("/src/vid00000000.mp4", 7, burned, {})


def test_a_stale_cache_refuses_nothing_before_the_cut():
    if not need_indexer():
        return
    s = shot(5, {"black_fraction": 0.97, "measured_by": "0123456789ab"})
    with contextlib.redirect_stderr(io.StringIO()):
        assert ra.precut_cache_refusal(s, *THRESHOLDS) is None


# --- ranking and the choice -----------------------------------------------------

def test_clean_candidates_are_ranked_ahead_of_weak_ones():
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, {"roi_coverage": 0.4}), (IDX, 2): shot(2, on_topic=False),
           (IDX, 3): shot(3)}
    pool = [cand(1, 0.40), cand(2, 0.35), cand(3, 0.25)]   # matcher order
    assert [c["shot"] for c in ra.rank_by_usability(pool, lut)] == [3, 1, 2]


@contextlib.contextmanager
def stubbed(gate):
    """cut() writes an empty clip; usable() is `gate(dest) -> (ok, soft)`."""
    saved = (ra.cut, ra.usable)

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    def fake_usable(clip, seconds, *a, soft_out=None, **k):
        ok, soft = gate(Path(clip).name)
        if ok and soft_out is not None:
            soft_out.extend(soft)
        return ok, ([] if ok else ["subject: nothing"])

    ra.cut, ra.usable = fake_cut, fake_usable
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            yield
    finally:
        ra.cut, ra.usable = saved


def first_cut(pool, lut, gate):
    """The choice loop every rung runs (ranked pool, first that survives the
    real gate) - the split opening's loop, reduced to one block."""
    with tempfile.TemporaryDirectory() as tmp, stubbed(gate):
        for c in ra.rank_by_usability(pool, lut):
            u = ra.cut_usable(c, 3.0, Path(tmp) / f"a00_s{c['shot']:03d}.mp4", lut, ARGS)
            if u:
                return u
    return None


def test_the_clean_shot_is_taken_when_there_is_one():
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, {"roi_coverage": 0.4}), (IDX, 2): shot(2)}
    u = first_cut([cand(1, 0.40), cand(2, 0.30)], lut,
                  lambda name: (True, ["low_framing"] if "s001" in name else []))
    assert u["shot"] == 2 and "usability" not in u, u


def test_the_weak_shot_is_taken_when_nothing_better_survives_and_carries_its_price():
    if not need_indexer():
        return
    lut = {(IDX, 1): shot(1, {"roi_coverage": 0.4}), (IDX, 2): shot(2)}
    # the clean one fails its real gate on something hard
    u = first_cut([cand(1, 0.40), cand(2, 0.30)], lut,
                  lambda name: (False, []) if "s002" in name else (True, ["low_framing"]))
    assert u["shot"] == 1, u
    assert u["usability"]["soft"] == ["low_framing"], u
    assert u["usability"]["penalty"] == 3, u


def test_off_topic_is_a_price_not_an_exclusion():
    if not need_indexer():
        return
    lut = {(IDX, 4): shot(4, on_topic=False)}
    u = first_cut([cand(4)], lut, lambda name: (True, []))
    assert u and u["usability"]["soft"] == ["off_topic_shot"], u


def test_the_record_reaches_the_storyboard():
    rec = {"task": "CF-0435", "soft": ["low_brightness"], "penalty": 3, "score": 0.97}
    c = ra.split_cut_record({"asset": "a.mp4", "kind": "clip", "held_frame": False,
                             "source": "/src/vid00000000.mp4", "shot": 3, "score": 0.3,
                             "at": 0.0, "seconds": 2.0, "card": False, "usability": rec})
    assert c["usability"] == rec and c["shot"] == "vid00000000:3"
    clean = ra.split_cut_record({"asset": "a.mp4", "kind": "clip", "held_frame": False,
                                 "source": "/src/vid00000000.mp4", "shot": 3,
                                 "score": 0.3, "at": 0.0, "seconds": 2.0, "card": False})
    assert "usability" not in clean
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    # block_for() and fill()'s own record carry it too (CF-0452: block_for's
    # through held_usability(), which is the cut's record unless held at best)
    assert src.count('**({"usability": held_u} if (held_u := held_usability(u, held)) else {})') == 1
    assert src.count('**({"usability": weak} if weak else {})') == 2


def test_the_pool_cache_key_does_not_see_the_new_rules():
    """CF-0435 item 4: the soft/hard split is not measuring code, so it must
    not move the usability cache key - the pool is transient and is never
    re-measured wholesale. The rules live in files outside the key, and the
    probe's own entry points do not import them."""
    names = {p.name for p in cache_fingerprint.USABILITY_SOURCES}
    for f in ("shot_score.py", "resolve_anchors.py", "build_render_plan.py",
              "score_log.py"):
        assert f not in names, f
    probe = (cache_fingerprint.INDEXER_SCRIPTS / "usability_probe.py")
    if probe.is_file():
        text = probe.read_text()
        assert "shot_score" not in text and "shot_usability" not in text


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

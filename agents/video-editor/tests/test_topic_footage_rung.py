#!/usr/bin/env python3
"""CF-0337: a block nothing matched is filled from the topic's own footage,
before any repeat and never with the procedural background; and no picture
(or a look-alike of the same source) comes back within 5 s.

The user on widows-bay (2026-09-23), both halves of one "no": several takes
of one frame in the first 5 seconds (blocks 0-2: shot 14, shot 11 of the same
set-up, shot 14 again 1.60 s later), and three blocks of abstract background
where the topic had 88 shots in three sources.

Pure checks on `resolve_anchors.topic_pool()` and `repeat_guard`, plus the
structural order of the ladder in the resolver (the behavioural version
needs real footage; the widows-bay rebuild in the task file is that).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import repeat_guard  # noqa: E402
import resolve_anchors  # noqa: E402
from common import FFMPEG  # noqa: E402


def _cand(idx, shot, score):
    return {"index": idx, "shot": shot, "score": score, "start": 0.0,
            "end": 3.0, "source": f"/f/{idx}.mp4"}


def _index(n, start=0):
    return {"source": "/f/src.mp4",
            "shots": [{"index": i, "start": float(i), "end": float(i) + 2.0}
                      for i in range(start, start + n)]}


# --------------------------------------------------------------------------
# topic_pool
# --------------------------------------------------------------------------

def test_below_floor_candidates_come_first_nearest_first():
    cands = [_cand("a", 1, 0.30), _cand("a", 2, 0.209), _cand("b", 3, 0.216),
             _cand("a", 4, 0.212)]
    pool = resolve_anchors.topic_pool(cands, {"a": _index(0), "b": _index(0)},
                                      0.22, None)
    assert [(c["shot"], c["score"]) for c in pool] == [
        (3, 0.216), (4, 0.212), (2, 0.209)], pool
    assert all(c["topic_rung"] == "below_floor" for c in pool)


def test_then_every_other_shot_of_every_source_best_source_first():
    cands = [_cand("a", 0, 0.21), _cand("b", 0, 0.25)]
    data = {"a": _index(3), "b": _index(2), "c": _index(1)}
    pool = resolve_anchors.topic_pool(cands, data, 0.22, None)
    rest = [(c["index"], c["shot"]) for c in pool
            if c["topic_rung"] == "topic_pool"]
    # b scored best (0.25), then a (0.21), then c (never offered); the
    # offered shots b:0 and a:0 are not offered twice.
    assert rest == [("b", 1), ("a", 1), ("a", 2), ("c", 0)], rest
    assert all(c["unscored"] and c["score"] == 0.0
               for c in pool if c["topic_rung"] == "topic_pool")


def test_the_score_floor_refusals_are_in_the_pool_too():
    cands = [_cand("a", 1, 0.30), _cand("a", 2, 0.25)]
    pool = resolve_anchors.topic_pool(cands, {"a": _index(0)}, 0.22, 0.28)
    assert [c["shot"] for c in pool] == [2], pool


# --------------------------------------------------------------------------
# the ladder in the resolver
# --------------------------------------------------------------------------

def _loop():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    return src, src.split("for si, seg in enumerate(segments):")[1].split(
        "def block_for")[0]


def test_topic_rung_sits_after_the_supply_record_and_before_the_repeat():
    _, loop = _loop()
    supply = loop.index("supply_by_segment[si] = candidate_supply(\n"
                        "            a[\"phrase\"], m[\"candidates\"], used,")
    topic = loop.index("tpool = topic_pool(")
    repeat = loop.index("reuse_budget.allow(")
    settle = loop.rindex("settled = settle_unresolved(")
    assert supply < topic < repeat < settle, (supply, topic, repeat, settle)


def test_the_rung_is_on_unless_the_channel_switched_the_background_on():
    src, loop = _loop()
    assert "topic_rung = not assetless_rung.enabled(channel_cfg)" in src
    assert "if not used and topic_rung and is_ordered_segment(seg):" in loop
    # an anchor the matcher had nothing for still climbs it
    assert ('if not m["candidates"] and not (topic_rung and '
            'is_ordered_segment(seg)):') in loop


def test_every_pick_goes_through_the_repeat_guard():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    fill = src.split("def fill(pool, reuse_key=None, length_first=False):")[1].split(
        "return used, capped")[0]
    assert "repeat_guard.conflict(placed + block_placed, here)" in fill
    # CF-0904: a cut is laid down by take() - a fresh one at `if take(c):`,
    # a held one (it passed every gate before it was held) by take_held().
    assert fill.index("repeat_guard.conflict(") < fill.index("if take(c):")
    assert fill.index("repeat_guard.conflict(") < fill.index("held = c")


# --------------------------------------------------------------------------
# repeat_guard
# --------------------------------------------------------------------------

def _show(key, start, end, sig=None):
    return {"key": key, "start": start, "end": end, "sig": sig}


FLAT_A = [[(i * 7) % 256 for i in range(32 * 18)]]
FLAT_B = [[(i * 13 + 91) % 256 for i in range(32 * 18)]]


def test_the_rejected_repeat_is_caught_at_1_6_seconds():
    placed = [_show("hG2tH_gTvRI:14", 0.0, 1.43),
              _show("hG2tH_gTvRI:11", 1.43, 3.03)]
    c = repeat_guard.conflict(placed, _show("hG2tH_gTvRI:14", 3.03, 4.75))
    assert c and c["kind"] == "repeat" and c["gap"] == 1.6, c


def test_a_repeat_after_five_seconds_of_other_pictures_is_allowed():
    placed = [_show("s:14", 0.0, 1.43)]
    assert repeat_guard.conflict(placed, _show("s:14", 6.43, 8.0)) is None
    assert repeat_guard.conflict(placed, _show("s:14", 6.42, 8.0))


def test_a_look_alike_of_the_same_source_is_a_near_duplicate():
    placed = [_show(("/f/s.mp4", 14), 0.0, 1.4, FLAT_A)]
    c = repeat_guard.conflict(placed, _show(("/f/s.mp4", 11), 1.4, 3.0, FLAT_A))
    assert c and c["kind"] == "near_duplicate" and c["similarity"] >= 0.85, c
    # different picture: fine
    assert repeat_guard.conflict(
        placed, _show(("/f/s.mp4", 11), 1.4, 3.0, FLAT_B)) is None
    # same picture, other source: not this rule - an identical picture from
    # another source is a copy of the same video, a repeat (CF-0461)
    c = repeat_guard.conflict(placed, _show(("/f/t.mp4", 11), 1.4, 3.0, FLAT_A))
    assert c and c["kind"] == "repeat" and c.get("copy"), c
    # unmeasured is never a duplicate
    assert repeat_guard.conflict(
        placed, _show(("/f/s.mp4", 11), 1.4, 3.0, None)) is None


def test_tuple_and_plan_keys_name_the_same_shot():
    placed = [_show(("/x/hG2tH_gTvRI.mp4", 14), 0.0, 1.0)]
    assert repeat_guard.conflict(placed, _show("hG2tH_gTvRI:14", 2.0, 3.0))


def test_signature_separates_a_real_clip_from_its_negative():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "a.mp4", Path(tmp) / "b.mp4"
        for dest, src in ((a, "testsrc2=size=320x180:rate=10"),
                          (b, "mandelbrot=size=320x180:rate=10")):
            subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                            src, "-t", "1", "-pix_fmt", "yuv420p", str(dest)],
                           check=True, timeout=60)
        sa, sb = repeat_guard.signature(a, 1.0), repeat_guard.signature(b, 1.0)
        assert sa and len(sa) == 3, sa
        assert repeat_guard.similarity(sa, sa) > 0.999
        assert repeat_guard.similarity(sa, sb) < repeat_guard.NEAR_DUPLICATE_SIMILARITY
        assert repeat_guard.signature(Path(tmp) / "none.mp4", 1.0) is None


def test_plan_violations_reads_the_plan_shape():
    plan = {"blocks": [
        {"start": 0.0, "end": 1.4, "shot": "s:14", "asset": {"kind": "clip", "src": "/nope"}},
        {"start": 1.4, "end": 3.0, "shot": "s:11", "asset": {"kind": "clip", "src": "/nope"}},
        {"start": 3.0, "end": 4.7, "shot": "s:14", "asset": {"kind": "clip", "src": "/nope"}},
        {"start": 4.7, "end": 6.4, "shot": None, "asset": {"kind": "procedural"}},
    ]}
    v = repeat_guard.plan_violations(plan)
    assert [x["blocks"] for x in v["violations"]] == [[0, 2]], v
    assert v["showings"] == 3 and v["unmeasured"] == 3, v


# --------------------------------------------------------------------------
# qc_render's background check
# --------------------------------------------------------------------------

def test_qc_fails_a_background_block_only_where_the_rung_is_off():
    import qc_render
    blocks = [{"asset": {"kind": "clip"}}, {"asset": {"kind": "procedural"}},
              {"asset": {"kind": "procedural"},
               "insert": {"kind": "meme", "file": "/m.png"}}]
    off = {"blocks": blocks, "assetless_rung": {"rung_enabled": False}}
    assert qc_render.background_holes(off) == [1]
    assert qc_render.background_holes({"blocks": blocks}) == [1]
    on = {"blocks": blocks, "assetless_rung": {"rung_enabled": True}}
    assert qc_render.background_holes(on) == []
    flat = {"blocks": blocks, "style": "typographic"}
    assert qc_render.background_holes(flat) == []
    assert "background" in qc_render.failed_gates(
        ["1 block(s) on the procedural background (block(s) [1])"])
    assert "repeat" in qc_render.failed_gates(["repeated picture: blocks 0 and 2"])


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

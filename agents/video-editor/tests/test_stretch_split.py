#!/usr/bin/env python3
"""CF-0480: a one-frame block is not built out of one shot stretched past
twice its length.

vanguards-doomsday 1313Z, refused by the user for "stop-frames": 7 of 7 blocks
were frames held off one source, shots of 1.4-3.3 s standing for 5-9 s
(x2.4-x3.9), with 12 eligible shots of the pool unused. Pinned here: when a
one-frame block of an ordered rhythm is cut into 2-3 shots of its phrase
(`stretch_split_wanted`), which shots a split leaves to the blocks after it
(`later_first_picks`), which cut a split block holds - the sharpest of the
ones long enough for the tail, CF-0465's "hold only a sharp frame"
(`sharpest_last`) - and the wiring: the split is decided after the block's
first fill, goes on from its first cut, is built as a `sequence`, carries
`stretch_split` onto the plan, and a block the pool could not split says so.

Fixtures only - nothing here reads pipeline/. No pytest dependency.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0480-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors as ra  # noqa: E402
import still_share  # noqa: E402

HOLD = {"role": "hold", "max_shots": 1, "side": None, "start": 0.0, "end": 9.0}
PUNCT = {"role": "punctuation", "max_shots": 1, "side": None}
SWING = {"role": "swing", "max_shots": 1, "side": "a"}
EVEN = {"role": "beat", "max_shots": None, "side": None}


def _loop():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    return src.split("for si, seg in enumerate(segments):")[1]


# ------------------------------------------------------------ when to split

def test_the_line_is_the_plans_stretched_line():
    """One home for "stretched": the plan's own price reads the same two
    numbers (still_share, CF-0418)."""
    assert still_share.STRETCH_MIN_RATIO == 2.0
    assert still_share.STRETCH_MIN_SECONDS == 2.0
    assert ra.STRETCH_SPLIT_MAX_SHOTS == 3


def test_doomsday_blocks_are_split():
    # 1313Z: xe3qx0kXArA:18 1.376 s under a 5.02 s block, :16 2.169 s under 8.48 s
    rec = ra.stretch_split_wanted(1.376, 5.02, PUNCT)
    assert rec and rec["wanted"] == 3 and rec["ratio"] == 3.65, rec
    assert rec["task"] == "CF-0480" and rec["first_shot_seconds"] == 1.376
    rec = ra.stretch_split_wanted(2.169, 8.48, HOLD)
    assert rec and rec["wanted"] == 3, rec
    # just over twice its shot: past twice, ceil(need / shot) is already 3
    rec = ra.stretch_split_wanted(2.5, 5.1, PUNCT)
    assert rec and rec["wanted"] == ra.STRETCH_SPLIT_MAX_SHOTS, rec


def test_no_split_when_the_hold_is_not_stretched():
    # at most twice its shot: the plan does not call it stretched either
    assert ra.stretch_split_wanted(2.5, 5.0, PUNCT) is None
    assert ra.stretch_split_wanted(3.0, 4.0, HOLD) is None
    # a block of 2 s or less is one beat of a cut, not a slide
    assert ra.stretch_split_wanted(0.8, 2.0, PUNCT) is None
    assert ra.stretch_split_wanted(0.0, 6.0, PUNCT) is None


def test_only_one_frame_blocks_of_an_ordered_rhythm():
    # a swing chain has its own multi-shot answer (CF-0120); `even` chains
    # shots into blocks of its own and is budgeted by its band (CF-0370)
    assert ra.stretch_split_wanted(1.0, 6.0, SWING) is None
    assert ra.stretch_split_wanted(1.0, 6.0, EVEN) is None
    assert ra.stretch_split_wanted(1.0, 6.0, {**PUNCT, "max_shots": 2}) is None


# -------------------------------------------- what a split leaves to the rest

def _cand(src, shot, start, end, score):
    return {"source": src, "shot": shot, "start": start, "end": end, "score": score,
            "index": 0}


def test_a_split_leaves_the_later_blocks_their_first_picks():
    segs = [
        {"role": "punctuation", "max_shots": 1, "anchors": [0], "start": 0.0, "end": 6.0},
        {"role": "hold", "max_shots": 1, "anchors": [1], "start": 6.0, "end": 15.0},
        {"role": "swing", "max_shots": 3, "anchors": [2], "start": 15.0, "end": 20.0},
    ]
    matches = [
        {"candidates": [_cand("v", 1, 0, 1.5, 0.4)]},
        # the later hold block: best by score (1.0 s), longest (3.25 s)
        {"candidates": [_cand("v", 2, 10, 11, 0.40), _cand("v", 3, 20, 23.25, 0.30),
                        _cand("v", 4, 30, 31.5, 0.25)]},
        {"candidates": [_cand("v", 5, 40, 44, 0.5)]},
    ]
    keep = ra.later_first_picks(segs, matches, 0, 0.22, None)
    # its first pick in a one-shot block's order (long enough first, then by
    # score: none is 9 s long, so the best score) and its longest
    assert ("v", 2) in keep and ("v", 3) in keep, keep
    assert ("v", 4) not in keep
    # a swing segment is not a one-frame block
    assert ("v", 5) not in keep
    # nothing after the last segment
    assert ra.later_first_picks(segs, matches, 2, 0.22, None) == set()


# ------------------------------------------- which cut a split block holds

class _Frames:
    """hold_frame / frame_value stand-ins: the sharpness each clip's frame reads."""

    def __init__(self, values):
        self.values = values
        self.grabbed = []

    def hold(self, clip, seconds, dest, used=None):
        self.grabbed.append(clip)
        Path(dest).write_bytes(b"png")
        return True

    def value(self, path):
        for clip, v in self.values.items():
            if Path(clip).stem in str(path):
                return v
        return None


def _with_frames(values, fn):
    import held_sharpness
    fr = _Frames(values)
    old_h, old_v = ra.hold_frame, held_sharpness.frame_value
    ra.hold_frame, held_sharpness.frame_value = fr.hold, fr.value
    try:
        return fn(fr)
    finally:
        ra.hold_frame, held_sharpness.frame_value = old_h, old_v


def _u(name, seconds):
    return {"clip": f"/c/a00_{name}.mp4", "seconds": seconds}


def test_the_sharpest_of_the_long_enough_cuts_is_held_last():
    used = [_u("a", 2.5), _u("b", 2.4), _u("c", 2.0)]   # tail 8.5 - 6.9 = 1.6
    with tempfile.TemporaryDirectory() as tmp:
        out, frames = _with_frames(
            {"/c/a00_a.mp4": 0.70, "/c/a00_b.mp4": 0.50, "/c/a00_c.mp4": 0.62},
            lambda fr: ra.sharpest_last(used, Path(tmp), 0, need=8.5))
    assert [u["clip"] for u in out] == ["/c/a00_b.mp4", "/c/a00_c.mp4", "/c/a00_a.mp4"], out
    assert set(frames) == {"/c/a00_a.mp4", "/c/a00_b.mp4", "/c/a00_c.mp4"}


def test_a_cut_shorter_than_the_tail_is_not_held():
    # tail 6.0 - 3.0 = 3.0: no cut is that long, so the longest one holds (its stretch (2.0 + 3.0) / 2.0 is the least)
    used = [_u("a", 1.0), _u("b", 2.0)]
    with tempfile.TemporaryDirectory() as tmp:
        out, _ = _with_frames({"/c/a00_a.mp4": 0.9, "/c/a00_b.mp4": 0.5},
                              lambda fr: ra.sharpest_last(used, Path(tmp), 0, need=6.0))
    assert out[-1]["clip"] == "/c/a00_b.mp4", out
    # tail 4.0 - 3.0 = 1.0: both are long enough, the sharper one holds
    used = [_u("a", 1.0), _u("b", 2.0)]
    with tempfile.TemporaryDirectory() as tmp:
        out, _ = _with_frames({"/c/a00_a.mp4": 0.9, "/c/a00_b.mp4": 0.5},
                              lambda fr: ra.sharpest_last(used, Path(tmp), 0, need=4.0))
    assert out[-1]["clip"] == "/c/a00_a.mp4", out


def test_nothing_is_measured_when_nothing_is_held():
    used = [_u("a", 3.0), _u("b", 3.0)]
    with tempfile.TemporaryDirectory() as tmp:
        out, frames = _with_frames({}, lambda fr: (ra.sharpest_last(
            used, Path(tmp), 0, need=6.2), fr.grabbed)[0])
    assert out == used and frames == {}
    assert ra.sharpest_last([_u("a", 1.0)], Path("/nowhere"), 0, need=6.0)[0] == [_u("a", 1.0)]


def test_an_unmeasured_frame_counts_as_the_softest():
    used = [_u("a", 3.0), _u("b", 3.0)]
    with tempfile.TemporaryDirectory() as tmp:
        out, _ = _with_frames({"/c/a00_b.mp4": 0.4},
                              lambda fr: ra.sharpest_last(used, Path(tmp), 0, need=8.0))
    assert out[-1]["clip"] == "/c/a00_b.mp4", out


def test_a_soft_held_frame_is_split_too():
    """CF-0465's proposal: a block not stretched but holding a soft frame
    (paper-dragon 1722Z block 2: MLwTyQOhBkw:51 3.25 s under 4.60 s, frame
    0.512 under 0.53) is cut into shots too, and holds only a tail."""
    import held_sharpness
    u = {"clip": "/c/a02_MLwTyQOhBkw_s051.mp4", "seconds": 3.25}
    with tempfile.TemporaryDirectory() as tmp:
        rec = _with_frames({u["clip"]: 0.512},
                           lambda fr: ra.soft_hold_wanted(u, 4.6, PUNCT, Path(tmp), 2))
        assert rec and rec["why"] == "soft_frame" and rec["soft_frame"] == 0.512, rec
        assert rec["floor"] == held_sharpness.FLOOR and rec["wanted"] == 3
        assert list(Path(tmp).iterdir()) == [], "the probe frame is removed"
        # sharp, or not measurable: kept
        assert _with_frames({u["clip"]: 0.60}, lambda fr: ra.soft_hold_wanted(
            u, 4.6, PUNCT, Path(tmp), 2)) is None
        assert _with_frames({}, lambda fr: ra.soft_hold_wanted(
            u, 4.6, PUNCT, Path(tmp), 2)) is None
        # nothing held (the shot covers the block within the slack), or not a
        # one-frame block: never measured
        fr_calls = []
        assert _with_frames({u["clip"]: 0.3}, lambda fr: (ra.soft_hold_wanted(
            u, 3.5, PUNCT, Path(tmp), 2), fr_calls.extend(fr.grabbed))[0]) is None
        assert fr_calls == []
        assert _with_frames({u["clip"]: 0.3}, lambda fr: ra.soft_hold_wanted(
            u, 4.6, SWING, Path(tmp), 2)) is None
    assert ra.stretch_split_wanted(1.0, 6.0, PUNCT)["why"] == "stretched"


# ------------------------------------------------------------- the wiring

def test_the_split_is_decided_after_the_first_fill_and_goes_on_from_it():
    loop = _loop()
    first = loop.index("used, capped = fill(pool, length_first=budget == 1)")
    decide = loop.index("split = (stretch_split_wanted(used[0][\"seconds\"], need, seg)")
    under = loop.index("# --- CF-0433: under the floor")
    assert first < decide < under
    body = loop[decide:under]
    # only a one-shot block that got exactly one shot
    assert "if budget != 1 or len(used) != 1 or args.no_stretch_split:" \
        in loop[first:decide]
    assert "or soft_hold_wanted(used[0], need, seg, clips_dir, si)\n" in loop[decide:]
    # CF-0536: and a one-frame block that would hold a frozen face
    assert "or frozen_hold_wanted(used[0], need, seg, clips_dir, si," in loop[decide:]
    # on the phrase's own pool and on its candidates under the floor; the
    # topic's footage is never split into more frames of something else
    assert 'used, capped = stretch_split(used, capped, pool, "match")' in loop
    assert 'used, capped = stretch_split(used, capped, bpool, "below_floor")' in loop
    topic = loop[loop.index("used, _ = fill(tpool, length_first=budget == 1)"):]
    assert 'split.update(rung="topic", got=1, short=True' in topic[:1200]
    # the second fill goes on from the first cut, never takes it again, and
    # leaves the later blocks their first picks
    assert "fill_cont.update(covered=first[\"seconds\"], last=first[\"key\"]" in body
    assert "later_first_picks(segments, matches, si" in body
    assert "!= first[\"key\"]" in body
    # the first cut no longer stands over the whole block (repeat guard)
    assert "pl[\"end\"] = pl[\"start\"] + first[\"seconds\"]" in body
    # a split the pool could not serve says so
    assert "split[\"short\"] = True" in body and "STRETCH SPLIT SHORT" in body


def test_fill_stops_once_the_tail_is_no_longer_than_its_last_cut():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    fill = src.split("def fill(pool, reuse_key=None, length_first=False):")[1].split("return used, capped")[0]
    # CF-0536: a split's extension stops on its own question instead
    assert "if split and (stop(used) if stop else need - covered <= span):" in fill
    assert 'cap = fill_cont.get("cap", budget)' in fill
    assert "len(used) >= cap" in fill


def test_a_split_block_is_a_sequence_and_a_short_one_is_held():
    loop = _loop()
    one = loop.index("or (split and len(used) == 1):")
    seq = loop.index('if seg["role"] == "swing" or split:')
    assert one < seq
    assert 'blocks[-1]["stretch_split"] = split' in loop[one:seq]
    # CF-0536: a frame that is not a frozen face goes first
    assert "sharpest_last(used, clips_dir, si, need,\n" in loop[seq:]
    assert '**({"stretch_split": split} if split else {}),' in loop[seq:]


def test_the_plan_carries_the_record():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    carried = src.split("for key in (\"rhythm_role\", \"side\", \"shot\", \"held_frame\",")[1] \
        .split("):")[0]
    assert '"stretch_split"' in carried



# ------------------------------------------- items 3-4: the plan's answer

def _plan(blocks):
    """(seconds, shot, held, shot_seconds, stretch_split) laid end to end."""
    out, t = [], 0.0
    for sec, shot, held, src_s, sp in blocks:
        asset = ({"kind": "still", "src": f"/w/clips/s_held_{shot}.png"} if held
                 else {"kind": "clip", "src": f"/w/clips/a_{shot}.mp4"})
        b = {"start": round(t, 3), "end": round(t + sec, 3), "asset": asset,
             "shot": shot, "held_frame": held}
        if src_s is not None:
            b["shot_seconds"] = src_s
        if sp:
            b["stretch_split"] = sp
        out.append(b)
        t += sec
    return {"blocks": out, "duration": {"composition": t}}


SHORT = {"task": "CF-0480", "need": 9.0, "first_shot_seconds": 1.2, "ratio": 7.5,
         "wanted": 3, "got": 1, "short": True}
SPLIT = {"task": "CF-0480", "need": 6.0, "first_shot_seconds": 2.0, "ratio": 3.0,
         "wanted": 3, "got": 3}


def test_one_source_behind_every_held_frame_is_named():
    p = _plan([(9.0, "vidA:4", True, 1.2, SHORT), (6.0, "vidA:5", True, 2.0, None),
               (3.0, "vidB:1", False, None, None)])
    rec = still_share.held_sources(p, shots_of=lambda s: None)
    assert rec["one_source"] == "vidA", rec
    assert rec["held_seconds"] == 15.0 and rec["stretched_seconds"] == 15.0, rec
    assert rec["rule"] == still_share.RULE_ONE_SOURCE
    assert "all off one source vidA" in still_share.describe_sources(rec)
    p = _plan([(9.0, "vidA:4", True, 1.2, None), (6.0, "vidB:5", True, 2.0, None)])
    rec = still_share.held_sources(p, shots_of=lambda s: None)
    assert rec["one_source"] is None and set(rec["sources"]) == {"vidA", "vidB"}, rec
    assert "from 2 sources" in still_share.describe_sources(rec)
    rec = still_share.held_sources(_plan([(3.0, "vidB:1", False, None, None)]),
                                   shots_of=lambda s: None)
    assert rec["held_seconds"] == 0 and rec["one_source"] is None
    assert still_share.describe_sources(rec) == "held frames: none"


def test_the_one_source_line_is_charged_only_once_the_table_prices_it():
    rec = {"one_source": "vidA", "held_seconds": 15.0, "stretched_seconds": 15.0,
           "sources": {"vidA": 15.0}}
    old = still_share._priced
    try:
        still_share._priced = lambda rule: False
        assert still_share.one_source_findings(rec) == []
        still_share._priced = lambda rule: rule == still_share.RULE_ONE_SOURCE
        got = still_share.one_source_findings(rec)
        assert len(got) == 1 and got[0]["rule"] == still_share.RULE_ONE_SOURCE, got
        assert still_share.one_source_findings({**rec, "one_source": None}) == []
    finally:
        still_share._priced = old
    # proposed at no charge: a fact for the user to price, paper-dragon (accepted)
    # holds one source too
    assert still_share.PROPOSED_ONE_SOURCE["price"] == 0


def test_the_signed_row_puts_a_zero_point_line_in_the_plans_score_log():
    """CF-0490: the user signed `score.held_one_source` at 0 on 2026-10-02 -
    with the version root's real table the gate writes the line into the
    plan's score (and its log) and takes nothing."""
    import argparse
    import contextlib
    import io
    import _score
    import build_render_plan as brp
    if not _score.has_rule(still_share.RULE_ONE_SOURCE):
        print("  skip: the root's table does not carry the signed row")
        return
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work" / "slug"
        work.mkdir(parents=True)
        args = argparse.Namespace(output=str(work / "plan.json"), script_id="s1",
                                  degrade_block=None, channel="example-film", index=None)
        p = _plan([(9.0, "vidA:4", True, 9.0, None), (6.0, "vidA:5", True, 6.0, None),
                   (3.0, "vidB:1", False, None, None)])
        score = _score.score_block([])
        p["score"] = score
        p["still_share"] = {"over": False}  # still_share_gate() writes it before this gate
        notes, warnings = [], []
        with contextlib.redirect_stderr(io.StringIO()):
            brp.pool_holds_gate(args, p, score, {}, warnings, notes=notes)
        assert p["still_share"]["held_sources"]["one_source"] == "vidA"
        got = [x for x in p["score"]["log"] if x["rule"] == still_share.RULE_ONE_SOURCE]
        assert len(got) == 1 and got[0]["price"] == 0, p["score"]
        assert p["score"]["score"] == 100 and p["score"].get("line"), p["score"]
        assert any("all off one source vidA" in n for n in notes), notes


def test_the_pool_does_not_hold_the_video():
    p = _plan([(9.0, "vidA:4", True, 1.2, SHORT), (6.0, "vidA:5", True, 2.0, None),
               (3.0, "vidB:1", False, None, SPLIT)])
    rec = still_share.measure(p, shots_of=lambda s: None)
    pool = still_share.pool_holds(p, rec)
    assert rec["stretched"]["share"] > 0.5
    assert pool["verdict"] == still_share.POOL_SHORT, pool
    assert pool["gate"] == "pool_holds_video" and pool["split_blocks"] == 1
    assert [x["block"] for x in pool["short_blocks"]] == [0]
    assert "the pool does not hold this video" in still_share.describe_pool(pool)
    # under the stretched line the short block is the montage's business
    p = _plan([(9.0, "vidA:4", True, 1.2, SHORT), (20.0, "vidB:1", False, None, None)])
    rec = still_share.measure(p, shots_of=lambda s: None)
    assert still_share.pool_holds(p, rec)["verdict"] == still_share.POOL_HOLDS
    # over it, but every block was split: not the pool's shortage
    p = _plan([(9.0, "vidA:4", True, 1.2, None), (6.0, "vidA:5", True, 2.0, None)])
    rec = still_share.measure(p, shots_of=lambda s: None)
    assert rec["stretched"]["share"] > 0.5
    assert still_share.pool_holds(p, rec)["verdict"] == still_share.POOL_HOLDS


def test_the_gate_warns_with_the_pools_funnel_code():
    import plan_refusal
    assert plan_refusal.code_for(plan_refusal.GATE_POOL_HOLDS_VIDEO) == "pool_too_thin"
    assert plan_refusal.GATE_POOL_HOLDS_VIDEO == still_share.POOL_GATE
    # never a refusal by itself: a warning until the user signs (CF-0320)
    assert not plan_refusal.warns(plan_refusal.GATE_POOL_HOLDS_VIDEO)
    src = (SCRIPTS / "build_render_plan.py").read_text()
    gate = src.split("def pool_holds_gate(")[1].split("\ndef ")[0]
    assert "refuse_plan(" not in gate and "sys.exit" not in gate
    assert "warnings.append(w)" in gate and "CF-0320" in gate
    main = src.split("still_share_gate(args, plan, plan_score, story)\n")[-1]
    assert main.index("held_soft_gate(") < main.index("pool_holds_gate(")


def test_the_supplement_request_of_the_topic_is_named():
    import build_render_plan as brp
    with tempfile.TemporaryDirectory() as tmp:
        batch = Path(tmp) / "2026-10-01T1313Z"
        work = batch / "work" / "vanguards-doomsday"
        work.mkdir(parents=True)
        (work / "order.json").write_text('{"topic_id": "lf-6"}')
        out = work / "plan.json"
        got = brp.supplement_request_for(out)
        assert got == {"topic_id": "lf-6", "request": None, "state": None,
                       "step": None}, got
        req = batch / "work" / "supplement-requests"
        req.mkdir()
        (req / "lf-6.json").write_text("{}")
        (batch / "work" / "supplement-step.json").write_text(
            '{"topics": {"lf-6": {"phase": "skipped", "outcome": "wall_ceiling"}}}')
        got = brp.supplement_request_for(out)
        assert got["state"] == "pending" and got["request"].endswith("lf-6.json")
        assert got["step"] == {"phase": "skipped", "outcome": "wall_ceiling"}
        assert brp.supplement_request_for(Path(tmp) / "plan.json") is None

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

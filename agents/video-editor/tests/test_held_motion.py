#!/usr/bin/env python3
"""CF-0481: a face held still out of a moving shot - `score.held_moving_face`.

The user rejected vanguards-doomsday 1313Z for "стоп-кадры в движении": a
podcast host frozen mid-word while his shot moves. Pinned here: which frames
are read (the held frames of the plan), the frozen test (motion around the
held moment AND a face), the per-video allowance and per-second units over
it, warn-only until the price row carries the user's signature, the gate's
wiring in the plan builder, and the motion measure itself on a synthetic
source (a moving pattern against a still one).

Fixtures only - nothing here reads pipeline/. No pytest dependency.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0481-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import _score  # noqa: E402
import held_motion as hm  # noqa: E402

CLIP = {"kind": "clip", "src": "/x/a00_v_s001.mp4"}


def held(name):
    return {"kind": "still", "src": f"/x/clips/{name}.png"}


def plan(blocks):
    out, t = [], 0.0
    for sec, asset, extra in blocks:
        out.append({"start": t, "end": t + sec, "asset": asset, **extra})
        t += sec
    return {"blocks": out, "duration": {"actual": t}}


# shot -> (motion, face): the doomsday-like plan after CF-0480
READINGS = {"v:4": (5.62, 0.0707), "v:15": (11.21, 0.0491), "v:13": (29.2, 0.0244),
            "v:8": (11.79, 0.0554), "v:16": (4.23, 0.0035), "v:9": (40.0, 0.0),
            "v:2": (4.57, 0.272)}


def fake(shot, picture):
    m, f = READINGS.get(shot, (None, None))
    return {"motion": m, "face_area": f, "at": 1.0, "match": 2.0, "shot_motion": m}


def doomsday_like():
    seq = {"kind": "sequence", "cuts": [
        dict(CLIP, seconds=1.5, shot="v:3"),
        dict(held("s06_held_a"), seconds=3.06, held_frame=True, shot="v:15")]}
    return plan([
        (1.54, held("s01_held_a"), {"held_frame": True, "shot": "v:8"}),
        (1.44, held("s02_held_a"), {"held_frame": True, "shot": "v:2"}),   # face, still
        (4.85, held("s03_held_a"), {"held_frame": True, "shot": "v:16"}),  # still, no face
        (2.24, held("s04_held_a"), {"held_frame": True, "shot": "v:13"}),
        (8.96, held("s05_held_a"), {"held_frame": True, "shot": "v:4"}),
        (4.56, seq, {"shot": "v:3"}),
        (3.0, held("s07_held_a"), {"held_frame": True, "shot": "v:9"}),    # moves, no face
        (2.0, dict(CLIP, shot="v:1"), {"shot": "v:1"}),                    # a clip: not read
    ])


def stamped(p):
    hm.stamp(p, measure=fake)
    return p


def test_only_held_frames_are_read_and_frozen_needs_motion_and_a_face():
    seen = []
    p = doomsday_like()
    hm.stamp(p, measure=lambda shot, pic: seen.append(shot) or fake(shot, pic))
    assert sorted(seen) == sorted(["v:8", "v:2", "v:16", "v:13", "v:4", "v:15", "v:9"]), seen
    rec = hm.record(p)
    frozen = [(x["block"], x["cut"]) for x in rec["frames"] if x["frozen"]]
    assert frozen == [(0, None), (3, None), (4, None), (5, 1)], frozen
    assert rec["frozen_seconds"] == round(1.54 + 2.24 + 8.96 + 3.06, 3)


def test_the_allowance_sits_between_the_accepted_maximum_and_the_rejected_replay():
    # accepted max 11.1 s (vanguards-endgame 0705Z), doomsday 1313Z after
    # CF-0480 15.8 s - measured 2026-10-02 on the acceptance log
    assert 11.1 < hm.ALLOW < 15.8
    rec = hm.record(stamped(doomsday_like()))
    assert rec["over_seconds"] == round(15.8 - hm.ALLOW, 3)
    # the defect alone takes a clean video under N (40)
    assert 100 + rec["proposed_penalty"] < 40, rec["proposed_penalty"]


def test_under_the_allowance_nothing_is_over():
    p = plan([(8.96, held("s05_held_a"), {"held_frame": True, "shot": "v:4"})])
    rec = hm.record(stamped(p))
    assert rec["frozen_seconds"] == 8.96 and rec["over_seconds"] == 0
    assert rec["proposed_penalty"] == 0.0
    assert "within the" in hm.describe(rec)


def test_an_unmeasured_frame_is_not_frozen():
    p = plan([(9.0, held("s00_held_a"), {"held_frame": True, "shot": "nope:1"})])
    rec = hm.record(stamped(p))
    assert rec["frames"][0]["frozen"] is False and rec["frozen_seconds"] == 0
    assert hm.frozen(None, 0.5) is False and hm.frozen(9.0, None) is False


def test_stamp_writes_once_per_measure():
    p = stamped(doomsday_like())
    rec = p["blocks"][4]["held_motion"]
    assert rec["measured_by"] == hm.MEASURED_BY and rec["motion"] == 5.62
    assert hm.stamp(p, measure=fake) == 0
    p["blocks"][4]["held_motion"]["measured_by"] = "old"
    assert hm.stamp(p, measure=fake) == 1


def test_a_missing_picture_measures_nothing():
    got = hm.measure_frame("v:1", "/nowhere/x.png", lambda k: ("/x.mp4", 0, 1))
    assert got["motion"] is None and got["face_area"] is None


def _ledger(tmp, row):
    path = Path(tmp) / "gate-prices.json"
    path.write_text(json.dumps({"rules": {} if row is None else {hm.RULE: row}}))
    return path


def test_without_a_signed_row_it_only_warns():
    with tempfile.TemporaryDirectory() as tmp:
        assert hm.mode(_ledger(tmp, None))["mode"] == hm.MODE_WARN
        unsigned = hm.proposed_row()
        assert unsigned["signature"] is None
        m = hm.mode(_ledger(tmp, unsigned))
        assert m == {"mode": hm.MODE_WARN, "price": None, "cap": None, "signed": False}
        rec = hm.record(stamped(doomsday_like()))
        assert hm.findings(rec, m) == []
        assert "warn (unsigned)" in hm.describe(rec, m)


def test_a_signed_row_charges_the_seconds_over_on_the_longest_frozen_frame():
    with tempfile.TemporaryDirectory() as tmp:
        row = dict(hm.proposed_row(), signature={"user": "u", "date": "2026-10-02"})
        m = hm.mode(_ledger(tmp, row))
        assert m["mode"] == hm.MODE_PENALTY and m["price"] == 16 and m["cap"] == 64
        found = hm.findings(hm.record(stamped(doomsday_like())), m)
        assert [(f["rule"], f["where"].get("block"), f["units"]) for f in found] == \
            [(hm.RULE, 4, round(15.8 - hm.ALLOW, 2))], found


def test_the_plan_builder_asks_it_after_the_held_soft_gate_before_the_plan_is_written():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    main = src[src.index("\ndef main():"):]
    at_soft = main.index("held_soft_gate(args, plan, plan_score, story")
    at_gate = main.index("held_motion_gate(args, plan, plan_score, story")
    at_dump = main.index("json.dump(plan, open(args.output")
    assert at_soft < at_gate < at_dump


def test_the_gate_warns_and_leaves_the_score_alone_while_unsigned():
    import build_render_plan as brp
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work" / "slug"
        (work / "clips").mkdir(parents=True)
        args = argparse.Namespace(output=str(work / "plan.json"), script_id="s1",
                                  degrade_block=None, channel="example-film", index=None)
        p = stamped(doomsday_like())
        score = _score.score_block([])
        p["score"] = score
        notes = []
        old_mode = hm.mode
        hm.mode = lambda path=None: {"mode": hm.MODE_WARN, "price": None,
                                     "cap": None, "signed": False}
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                rec = brp.held_motion_gate(args, p, score, {}, notes=notes)
        finally:
            hm.mode = old_mode
        assert rec["mode"] == hm.MODE_WARN and p["held_motion"] is rec
        assert rec["over_seconds"] > 0
        assert "HELD MOVING FACE" in err.getvalue() and len(notes) == 1
        assert not [f for f in p["score"].get("findings") or [] if f["rule"] == hm.RULE]


def test_the_gate_charges_the_signed_price_from_the_version_roots_table():
    """CF-0490: the user signed `score.held_moving_face` on 2026-10-02 (-16 a
    second over 12 s, cap 64). Read through the real table of this version's
    root, the gate puts the finding in the plan's score - units are the
    seconds over the allowance, the 12 s are taken off here, not by the
    model - and the plan stage of the score log carries it."""
    import build_render_plan as brp
    m = hm.mode()
    if not m["signed"]:
        print("  skip: the root's table does not carry the signed row")
        return
    assert m == {"mode": hm.MODE_PENALTY, "price": 16, "cap": 64, "signed": True}, m
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work" / "slug"
        (work / "clips").mkdir(parents=True)
        args = argparse.Namespace(output=str(work / "plan.json"), script_id="s1",
                                  degrade_block=None, channel="example-film", index=None)
        p = stamped(doomsday_like())
        score = _score.score_block([])
        p["score"] = score
        notes = []
        with contextlib.redirect_stderr(io.StringIO()):
            rec = brp.held_motion_gate(args, p, score, {}, notes=notes)
        assert rec["mode"] == hm.MODE_PENALTY
        got = [f for f in p["score"].get("findings") or [] if f["rule"] == hm.RULE]
        assert len(got) == 1 and got[0]["units"] == round(15.8 - hm.ALLOW, 2), got
        # 3.8 s over at 16/s = 60.8, under the cap of 64
        assert abs(p["score"]["score"] - (100 - 60.8)) < 0.01, p["score"]
        assert "charged at the signed price" in notes[0]
        assert (work / "plan.score.json").exists() or list(work.glob("*.score.json"))


def _video(path, moving):
    src = "testsrc2=size=320x180:rate=25" if moving else "color=c=gray:size=320x180:rate=25"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}:d=2",
                        "-pix_fmt", "yuv420p", str(path)], capture_output=True)
    return r.returncode == 0


def _frame(video, at, png):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(video),
                        "-frames:v", "1", str(png)], capture_output=True)
    return r.returncode == 0


def test_the_measure_reads_a_moving_source_above_a_still_one():
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        print("SKIP: no numpy/PIL")
        return
    with tempfile.TemporaryDirectory() as tmp:
        mv, st = Path(tmp) / "m.mp4", Path(tmp) / "s.mp4"
        pm, ps = Path(tmp) / "m.png", Path(tmp) / "s.png"
        if not (_video(mv, True) and _video(st, False) and _frame(mv, 1.0, pm)
                and _frame(st, 1.0, ps)):
            print("SKIP: no ffmpeg")
            return
        a = hm.source_motion(str(mv), 0.0, 2.0, str(pm))
        b = hm.source_motion(str(st), 0.0, 2.0, str(ps))
        assert a and b, (a, b)
        assert a["motion"] >= hm.MOTION_MIN > b["motion"], (a, b)
        assert abs(a["at"] - 1.0) < 0.2, a
        assert hm.source_motion(str(Path(tmp) / "missing.mp4"), 0, 1, str(pm)) is None


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

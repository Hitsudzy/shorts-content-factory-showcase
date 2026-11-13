#!/usr/bin/env python3
"""CF-0465: a soft frame held still - `score.held_soft_frame`.

The user's call of 2026-10-01 (B2+B3): the smear kaijura-minus-zero 1248Z
was rejected for is a soft frame stopped and held, not soft footage in
motion. Pinned here: which frames are measured (the held_frame pictures of
the plan - a held block, a sequence's held cut, a clip degraded to its frame;
never a clip, a picture, a card), that the value is stamped onto the plan,
the floor, the per-second units, warn-only until the price row carries the
user's signature (and charged at the row's price once it does), the gate's
wiring in the plan builder, and the measure itself on synthetic pictures
(a sharp test pattern against the same pattern blurred).

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
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0465-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import _score  # noqa: E402
import held_sharpness as hs  # noqa: E402
import shot_score  # noqa: E402

CLIP = {"kind": "clip", "src": "/x/a00_v_s001.mp4"}


def held(name):
    return {"kind": "still", "src": f"/x/clips/{name}.png"}


def plan(blocks):
    out, t = [], 0.0
    for sec, asset, extra in blocks:
        out.append({"start": round(t, 3), "end": round(t + sec, 3),
                    "asset": asset, **(extra or {})})
        t += sec
    return {"blocks": out, "duration": {"composition": t}}


VALUES = {"/x/clips/s00_held_a.png": 0.64, "/x/clips/s02_held_b.png": 0.518,
          "/x/clips/c.png": 0.50, "/x/clips/_degraded_still_3.png": 0.60}


def fake(path):
    return VALUES.get(str(path))


def kaijura_like():
    """Held block (sharp), clip, held block (soft, 5.1 s), a sequence whose
    held tail is soft, a clip degraded to its frame."""
    seq = {"kind": "sequence", "cuts": [
        {"kind": "clip", "src": "/x/a.mp4", "seconds": 1.0, "shot": "v:9"},
        {"kind": "still", "src": "/x/clips/c.png", "seconds": 2.0, "held_frame": True,
         "shot": "v:9"}]}
    return plan([(4.0, held("s00_held_a"), {"held_frame": True}),
                 (3.0, CLIP, None),
                 (5.1, held("s02_held_b"), {"held_frame": True}),
                 (3.0, seq, None),
                 (2.5, {"kind": "still", "src": "/x/clips/_degraded_still_3.png"}, None),
                 (3.0, {"kind": "still", "src": "/x/poster.jpg"}, None)])


def test_only_held_frames_are_measured_and_the_soft_ones_named():
    rec = hs.record(kaijura_like(), measure=fake)
    got = [(x["block"], x["cut"], x["seconds"], x["value"], x["soft"]) for x in rec["frames"]]
    assert got == [(0, None, 4.0, 0.64, False), (2, None, 5.1, 0.518, True),
                   (3, 1, 2.0, 0.50, True), (4, None, 2.5, 0.60, False)], got
    assert rec["soft_seconds"] == 7.1 and rec["units"] == 7.1
    assert rec["floor"] == hs.FLOOR == 0.53
    # the proposal: 5 a second, capped at 30
    assert rec["proposed_penalty"] == -30.0


def test_the_floor_sits_between_the_rejected_frame_and_the_softest_accepted():
    # 2026-10-01: kaijura 1248Z block 6 (xiEmt197Bk8:41) 0.5184; the softest
    # accepted held frames: primetime 2210Z 0.5356, paper-dragon 1722Z 0.5406.
    assert 0.5184 < hs.FLOOR < 0.5356
    p = plan([(5.1, held("s02_held_b"), {"held_frame": True})])
    rec = hs.record(p, measure=lambda _p: 0.5356)
    assert rec["soft_seconds"] == 0 and rec["proposed_penalty"] == 0.0
    rec = hs.record(p, measure=lambda _p: 0.5184)
    assert rec["soft_seconds"] == 5.1 and rec["proposed_penalty"] == -25.5


def test_an_unreadable_frame_is_not_soft():
    rec = hs.record(kaijura_like(), measure=lambda _p: None)
    assert rec["soft_seconds"] == 0 and all(x["value"] is None for x in rec["frames"])


def test_stamp_writes_the_value_onto_the_holder_and_record_reads_it_back():
    p = kaijura_like()
    calls = []

    def counting(path):
        calls.append(path)
        return fake(path)
    assert hs.stamp(p, measure=counting) == 4
    assert p["blocks"][2][hs.FIELD]["value"] == 0.518
    assert p["blocks"][2][hs.FIELD]["measured_by"] == hs.MEASURED_BY
    assert p["blocks"][3]["asset"]["cuts"][1][hs.FIELD]["value"] == 0.50
    assert hs.FIELD not in p["blocks"][1] and hs.FIELD not in p["blocks"][5]
    # stamped once: neither a second stamp nor the record measures again
    assert hs.stamp(p, measure=counting) == 0
    n = len(calls)
    rec = hs.record(p, measure=counting)
    assert len(calls) == n and rec["soft_seconds"] == 7.1


def test_a_stamp_of_another_measure_is_measured_again():
    p = kaijura_like()
    p["blocks"][2][hs.FIELD] = {"measured_by": "old", "value": 0.9}
    hs.stamp(p, measure=fake)
    assert p["blocks"][2][hs.FIELD]["value"] == 0.518


def test_stamp_finds_the_picture_beside_the_plan_when_the_path_moved():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "clips").mkdir()
        (Path(tmp) / "clips" / "s02_held_b.png").write_bytes(b"x")
        p = plan([(5.1, held("s02_held_b"), {"held_frame": True})])
        seen = []
        hs.stamp(p, measure=lambda path: seen.append(path) or 0.6, base=tmp)
        assert seen == [str(Path(tmp) / "clips" / "s02_held_b.png")], seen


def _ledger(tmp, row):
    path = Path(tmp) / "gate-prices.json"
    path.write_text(json.dumps({"rules": {hs.RULE: row} if row else {}}))
    return path


def test_without_a_signed_row_it_only_warns():
    with tempfile.TemporaryDirectory() as tmp:
        assert hs.mode(_ledger(tmp, None))["mode"] == hs.MODE_WARN
        unsigned = hs.proposed_row()
        assert unsigned["signature"] is None
        m = hs.mode(_ledger(tmp, unsigned))
        assert m == {"mode": hs.MODE_WARN, "price": None, "cap": None, "signed": False}
        rec = hs.record(kaijura_like(), measure=fake)
        assert hs.findings(rec, m) == []
        assert "warn (unsigned)" in hs.describe(rec, m)
        assert hs.mode(Path(tmp) / "missing.json")["mode"] == hs.MODE_WARN


def test_a_signed_row_charges_per_second_of_each_soft_frame():
    with tempfile.TemporaryDirectory() as tmp:
        row = dict(hs.proposed_row(), signature={"user": "u", "date": "2026-10-02"})
        m = hs.mode(_ledger(tmp, row))
        assert m["mode"] == hs.MODE_PENALTY and m["price"] == 5 and m["cap"] == 30
        rec = hs.record(kaijura_like(), measure=fake)
        found = hs.findings(rec, m)
        assert [(f["rule"], f["where"].get("block"), f["where"].get("cut"), f["units"])
                for f in found] == [(hs.RULE, 2, None, 5.1), (hs.RULE, 3, 1, 2.0)], found
        assert all(f["source"] == "metric" for f in found)
        # block 0 starts in the hook; neither soft frame does
        assert [f["hook"] for f in found] == [False, False]


def test_the_score_model_charges_the_signed_row_at_its_price():
    mod = _score.module()
    if mod is None:
        print("SKIP: no score model")
        return
    real = json.loads(Path(_score.factory_root(), "shared", "gate-prices.json").read_text())
    row = dict(hs.proposed_row(), signature={"user": "u", "date": "2026-10-02"})
    real["rules"][hs.RULE] = row
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gate-prices.json"
        path.write_text(json.dumps(real, ensure_ascii=False))
        p = plan([(5.1, held("s02_held_b"), {"held_frame": True})])
        found = hs.findings(hs.record(p, measure=fake), hs.mode(path))
        block = _score.score_block(found, ledger=str(path))
        assert block["by_rule"][hs.RULE]["charged"] == -25.5, block["by_rule"]


def test_the_plan_builder_asks_it_after_the_still_share_before_the_plan_is_written():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    main = src[src.index("\ndef main():"):]
    at_share = main.index("still_share_gate(args, plan, plan_score, story)")
    at_gate = main.index("held_soft_gate(args, plan, plan_score, story")
    at_dump = main.index("json.dump(plan, open(args.output")
    assert at_share < at_gate < at_dump


def test_the_gate_warns_and_leaves_the_score_alone_while_unsigned():
    import build_render_plan as brp
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work" / "slug"
        (work / "clips").mkdir(parents=True)
        args = argparse.Namespace(output=str(work / "plan.json"), script_id="s1",
                                  degrade_block=None, channel="example-film")
        p = kaijura_like()
        score = _score.score_block([])
        p["score"] = score
        notes = []
        old_fv, old_mode = hs.frame_value, hs.mode
        hs.frame_value = fake
        hs.mode = lambda path=None: {"mode": hs.MODE_WARN, "price": None,
                                     "cap": None, "signed": False}
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                rec = brp.held_soft_gate(args, p, score, {}, notes=notes)
        finally:
            hs.frame_value, hs.mode = old_fv, old_mode
        assert rec is p["held_sharpness"] and rec["mode"] == hs.MODE_WARN
        assert rec["soft_seconds"] == 7.1
        assert "HELD SOFT FRAME" in err.getvalue(), err.getvalue()
        assert notes and hs.RULE in notes[0]
        assert p["score"] is score and score.get("findings") == []
        assert not (work / "plan.score.json").exists()
        assert p["blocks"][2][hs.FIELD]["value"] == 0.518


def _png(path, blur):
    ff = None
    mod = shot_score.sharpness_module()
    if mod is not None:
        ff = getattr(mod, "FFMPEG", None)
    if not ff or not Path(ff).exists():
        return False
    vf = "format=rgb24" + (",gblur=sigma=3" if blur else "")
    r = subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=960x540:rate=1", "-frames:v", "1", "-vf", vf,
                        str(path)], capture_output=True, timeout=60)
    return r.returncode == 0 and Path(path).exists()


def test_the_measure_reads_a_blurred_picture_softer_than_the_sharp_one():
    if shot_score.sharpness_module() is None:
        print("SKIP: no footage-indexer sharpness module")
        return
    with tempfile.TemporaryDirectory() as tmp:
        sharp, soft = Path(tmp) / "sharp.png", Path(tmp) / "soft.png"
        if not (_png(sharp, False) and _png(soft, True)):
            print("SKIP: no ffmpeg to draw the pictures")
            return
        a, b = hs.frame_value(sharp), hs.frame_value(soft)
        assert a is not None and b is not None, (a, b)
        assert a > hs.FLOOR > b, (a, b)
        assert hs.frame_value(Path(tmp) / "missing.png") is None


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

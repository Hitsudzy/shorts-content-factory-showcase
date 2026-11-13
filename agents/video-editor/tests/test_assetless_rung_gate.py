#!/usr/bin/env python3
"""CF-0137: a block with no picture does not reach a shipped video.

CF-0123 (grill 2026-09-07) declared per-block degradation to the assetless
rung brak - not for how it looks in isolation but for how it actually arrived:
runs of 2.1 to 14.3 consecutive blocks, 14-38 % of the running time in three
of the four videos of batch `2026-09-03T2037Z`. So the rung becomes a channel
switch, off by default and off on every channel that does not exist yet, and
under it the planner refuses.

What this file pins:

  * the flag defaults to off for every shape of missing answer - no channel,
    an unreadable config, the key absent, the key null;
  * one assetless block refuses the plan. One, with no share-of-runtime
    threshold: CF-0137 rejects the proposed "> 25 % or a run > 6 s" outright,
    because with the rung off the rule is boolean and a percentage would be a
    constant nobody measured;
  * the flat `typographic` style (CF-0015, one of three in the rotation) is
    untouched - the ban is on the tearing, not on the look;
  * the refusal happens *before* the render. `qc_render.py` has never heard
    of degradation (the string `degraded` does not occur in it) and probes a
    rendered file, so a refusal there would arrive after the render was paid
    for.

Mostly pure over `assetless_rung.py`, plus two end-to-end runs of the real
build_render_plan.py on a synthetic storyboard. No footage, no CLIP, no
ffmpeg beyond what the planner does for itself. No pytest - plain asserts,
run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import assetless_rung
import plan_refusal  # noqa: E402
import resolve_anchors  # noqa: E402
import write_batch_metadata  # noqa: E402


def blocks(*kinds, seconds=1.4):
    out, t = [], 0.0
    for k in kinds:
        b = {"start": round(t, 3), "end": round(t + seconds, 3)}
        if k is not None:
            b["asset"] = {"kind": k}
        out.append(b)
        t += seconds
    return out


def assetless_of(bs):
    return [{"index": i, "from": "unfilled", "reason": "no shot in any index"}
            for i, b in enumerate(bs)
            if b.get("asset", {}).get("kind") not in ("clip", "still", "card", "split")]


# --------------------------------------------------------------------------
# the flag
# --------------------------------------------------------------------------

def test_the_rung_is_off_for_every_shape_of_no_answer():
    """Item 1: `false` by default on all channels, "including future ones".
    That has to mean the *absence* of the key is off - otherwise a channel
    added next month inherits the rung unless somebody remembers to write
    the flag down, which is exactly the failure mode this is protecting
    against."""
    for cfg in (None, {}, {"insert_layers": {}},
                {"assetless_block_rung": None},
                {"assetless_block_rung": "yes"},
                {"assetless_block_rung": {}},
                {"assetless_block_rung": {"reason": "no enabled key"}},
                {"assetless_block_rung": {"enabled": False}}):
        assert assetless_rung.enabled(cfg) is False, cfg
    assert assetless_rung.DEFAULT_ENABLED is False


def test_a_channel_can_switch_the_rung_on_in_either_shape():
    assert assetless_rung.enabled(
        {"assetless_block_rung": {"enabled": True}}) is True
    assert assetless_rung.enabled({"assetless_block_rung": True}) is True


def test_the_real_channel_has_the_rung_off():
    """The one channel this factory has today must not be shipping assetless
    blocks. Read, never written, by this repo - the file lives in the factory
    root and belongs to the channel, not to the Video Editor."""
    path = repo_paths.CHANNELS_DIR / "example-film.json"
    if not path.exists():
        print("SKIP (factory channels/ not reachable from this checkout)")
        return
    cfg = json.loads(path.read_text())
    assert assetless_rung.enabled(cfg) is False, (
        "the live channel allows per-block assetless degradation - CF-0123 "
        "says it must not")


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------

def test_one_assetless_block_refuses_the_plan_with_no_threshold():
    """"The acceptance threshold on the share of picture is not needed:
    without the rung the rule is boolean - the hole is there, the video is
    not published." One block out of thirty, 1.4s of 42, and it is a
    refusal."""
    bs = blocks(*(["clip"] * 29 + ["procedural"]))
    rec = assetless_rung.judge(assetless_of(bs), None, style="motion", blocks=bs)
    assert rec["passed"] is False, rec
    # CF-0330: counted exactly as before, and it warns rather than refuses
    assert rec["warned"] is True and rec["mode"] == "warn", rec
    assert rec["blocks"] == [29] and rec["block_count"] == 1, rec
    assert rec["seconds"] == 1.4, rec
    assert rec["rung_enabled"] is False
    assert "WARNING, not a refusal" in rec["note"], rec["note"]
    # No number anywhere that could be read as a tolerance.
    for field in ("threshold", "max_share", "max_seconds", "tolerance"):
        assert field not in rec, f"{field} is a threshold CF-0137 refused to invent"


def test_a_channel_that_switched_the_rung_on_still_builds_and_is_recorded():
    bs = blocks("clip", "procedural", "clip")
    rec = assetless_rung.judge(assetless_of(bs),
                               {"assetless_block_rung": {"enabled": True}},
                               style="motion", blocks=bs)
    assert rec["passed"] is True and rec["rung_enabled"] is True, rec
    assert rec["blocks"] == [1], rec
    assert "switched the rung on" in rec["note"], rec["note"]


def test_a_plan_with_a_picture_everywhere_passes_and_says_so():
    bs = blocks("clip", "still", "card", "split")
    rec = assetless_rung.judge(assetless_of(bs), None, style="motion", blocks=bs)
    assert rec["passed"] is True and rec["blocks"] == [], rec
    assert rec["applies"] is True, rec


def test_the_flat_typographic_style_is_not_what_was_banned():
    """The ban covers per-block degradation only. `typographic` as a
    whole-video style is one of the three in CF-0015's rotation, chosen
    before a frame is cut, and CF-0123 left it alone: what was called brak is
    the tearing, not the look."""
    bs = blocks("procedural", "procedural", "procedural")
    rec = assetless_rung.judge(assetless_of(bs), None, style="typographic",
                               blocks=bs)
    assert rec["passed"] is True, rec
    assert rec["applies"] is False and rec["style_typographic"] is True, rec
    assert "CF-0015" in rec["note"], rec["note"]
    # ... and the same blocks under any other style are a refusal
    assert assetless_rung.judge(assetless_of(bs), None, style="motion",
                                blocks=bs)["passed"] is False


def test_an_unreadable_channel_refuses_rather_than_permits():
    """`enabled()` is asked about configs that may be broken, absent or
    unreachable. Every one of those has to fall to a refusal: a switch that
    cannot be read has not been switched on."""
    rec = assetless_rung.judge([{"index": 0, "reason": "x"}], "not a dict at all",
                               style="motion")
    assert rec["passed"] is False, rec


# --------------------------------------------------------------------------
# before the render, not after
# --------------------------------------------------------------------------

def test_qc_render_still_knows_nothing_about_degradation():
    """The acceptance criterion, kept as a check rather than a claim: the
    post-render QC has no notion of a degraded block, so if the refusal ever
    moved there it would arrive after the render was paid for. If this ever
    fails because qc_render.py learned the word, the gate's placement should
    be reconsidered - deliberately, not silently.

    CF-0337 did reconsider it, deliberately: qc_render now also fails a
    procedural block on a channel with the rung off (`background_holes`), as
    a second net *after* this gate - it reads `asset.kind`, never the
    planner's degradation record, and the planner's gate stays first."""
    src = (SCRIPTS / "qc_render.py").read_text()
    assert "degraded" not in src, (
        "qc_render.py now mentions degradation - CF-0137 placed the refusal "
        "in build_render_plan.py precisely because it did not")


def test_the_gate_is_asked_before_the_expensive_layers():
    """Structural: the refusal has to happen while the blocks are final and
    before the proof/meme/sound layers and their vision calls - a video that
    will not be published should not pay for a vision call either."""
    src = (SCRIPTS / "build_render_plan.py").read_text()
    gate = src.index("assetless_gate = build_assetless_rung_gate(")
    for later in ("meme_result = build_meme_layer(",
                  "underlay_layer.apply_to_plan(",
                  "sound_result = build_sound_layer("):
        assert gate < src.index(later), f"the gate is asked after {later}"


def _silent_wav(path, seconds=6.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = 2000 if (i // 40) % 2 else -2000
            frames += int(v).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _anchor(i):
    return {"phrase": f"p{i}", "word_index": i, "emphasis_words": []}


def _storyboard(segs):
    return {
        "script_id": "cf-0137",
        "style": "motion",
        "resolved_from_anchors": True,
        "rhythm": {"pattern_requested": "explainer",
                   "rhythm_requested": "staccato", "rhythm_built": "staccato",
                   "parameters": {"block_count": 3, "key_frame_hold_seconds": 1.4},
                   "opening_requested": "count_card",
                   "opening_delivered": "count_card", "anchor_count": 3},
        "blocks": [
            {"word_range": [0, 0], "intent": "count card", "asset_kind": "card",
             "card": {"kind": "count_card", "text": "3"}, "emphasis_words": [],
             "rhythm_role": "opening_card", "side": None, "shot": None,
             "held_frame": False, "_start": segs[0][0], "_end": segs[0][1]},
            resolve_anchors.unfilled_block(_anchor(1), {"role": "beat"},
                                           *segs[1], "every candidate failed to cut"),
            resolve_anchors.unfilled_block(_anchor(2), {"role": "beat"},
                                           *segs[2], "no shot in any index"),
        ],
        "unresolved_anchors": [], "rejected_candidates": [],
    }


def _run(tmp, extra):
    venv_py = Path(repo_paths.VENV_PY3)
    py = str(venv_py) if venv_py.exists() else sys.executable
    out = tmp / "plan.json"
    r = subprocess.run(
        [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
         str(tmp / "words.json"), str(tmp / "voice.wav"), str(out)] + extra,
        capture_output=True, text=True, cwd=tmp)
    return r, out


def _fixture(tmp):
    _silent_wav(tmp / "voice.wav")
    words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]
    (tmp / "words.json").write_text(json.dumps(words))
    segs = [(0.0, 1.4), (1.4, 2.8), (2.8, 4.2)]
    (tmp / "storyboard.json").write_text(json.dumps(_storyboard(segs)))
    return segs


def test_end_to_end_the_planner_warns_and_writes_the_plan():
    """CF-0330 (the user, 2026-09-23): the situation that used to refuse -
    two blocks with no picture on a channel with the flag off, nothing the
    ladder could fill - now writes the plan. Exit 0, the holes on the
    procedural rung (the deterministic render every assetless block has had
    since CF-0031), a warning record with the gate's code and numbers in
    `plan["warnings"]`, and the same machine-readable deficit beside the plan
    for CF-0139's rotation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _fixture(tmp)
        # and the preflight's warning, left in the same work directory by
        # `script_anchors.py preflight --out`, rides into the same list
        plan_refusal.write_warning(tmp / "anchor_preflight.json", "cf-0137",
                                   plan_refusal.GATE_ANCHOR_PREFLIGHT,
                                   "ANCHORS NOT COVERED: 1 absent", numbers={"absent": 1})
        r, out = _run(tmp, ["--style", "motion", "--target-duration", "1", "60"])
        assert r.returncode == 0, (r.returncode, r.stderr[-2000:])
        assert out.exists(), "a warned plan was not written"
        assert [w["gate"] for w in json.loads(out.read_text())["warnings"]] == \
            ["anchor_preflight", "assetless_rung"]
        assert "ASSETLESS BLOCKS - WARNING, the plan is written" in r.stderr, r.stderr[-2000:]
        assert not (tmp / "plan.refusal.json").exists()
        plan = json.loads(out.read_text())
        assert [b["asset"]["kind"] for b in plan["blocks"]] == \
            ["card", "procedural", "procedural"]
        rec = plan["assetless_rung"]
        assert rec["passed"] is False and rec["warned"] is True, rec
        assert rec["blocks"] == [1, 2], rec
        ws = [w for w in plan["warnings"] if w["gate"] == "assetless_rung"]
        assert len(ws) == 1, plan["warnings"]
        w = ws[0]
        assert w["reason_code"] == "pattern_undeliverable" and w["severity"] == "warn", w
        assert w["numbers"]["blocks"] == [1, 2] and w["numbers"]["block_count"] == 2, w
        assert w["numbers"]["total_blocks"] == 3 and w["numbers"]["seconds"] == rec["seconds"] > 0, w
        deficit = tmp / "plan.assetless-rung.json"
        assert deficit.exists(), "no machine-readable deficit for CF-0139 to read"
        rec = json.loads(deficit.read_text())["assetless_rung"]
        assert rec["passed"] is False and rec["blocks"] == [1, 2], rec
        assert rec["kind"] == assetless_rung.DEFICIT_KIND, rec
        assert rec["reasons"] == ["every candidate failed to cut",
                                  "no shot in any index"], rec


def test_end_to_end_a_channel_with_the_rung_on_builds_and_records_it():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _fixture(tmp)
        cfg = tmp / "rung-on.json"
        cfg.write_text(json.dumps({
            "channel_id": "test-rung-on",
            "display_name": "Test Channel", "theme": STAND_IN_THEME,
            "assetless_block_rung": {"enabled": True, "reason": "test config"}}))
        r, out = _run(tmp, ["--style", "motion", "--target-duration", "1", "60",
                            "--channel", str(cfg)])
        assert r.returncode == 0, r.stderr[-2000:]
        plan = json.loads(out.read_text())
        rec = plan["assetless_rung"]
        assert rec["passed"] is True and rec["rung_enabled"] is True, rec
        assert rec["blocks"] == [1, 2], rec
        assert [b["asset"]["kind"] for b in plan["blocks"]] == \
            ["card", "procedural", "procedural"]
        assert "assetless-block rung passed" in r.stderr, r.stderr[-1500:]


def test_end_to_end_the_flat_style_needs_no_channel_at_all():
    """`--style typographic` on the same storyboard, with no channel and so
    no permission anywhere: it builds, because the whole-video flat style is
    not what CF-0123 refused."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _fixture(tmp)
        r, out = _run(tmp, ["--style", "typographic",
                            "--target-duration", "1", "60"])
        assert r.returncode == 0, r.stderr[-2000:]
        plan = json.loads(out.read_text())
        assert plan["assetless_rung"]["applies"] is False, plan["assetless_rung"]
        assert {b["asset"]["kind"] for b in plan["blocks"]} == {"procedural"}


def test_the_batch_metadata_says_whether_the_video_was_checked():
    """A video that reaches 05-video-editor.json passed the gate, and its
    record says which of the two ways. A plan from before CF-0137 says
    `passed: null` - never `true`, because a video that was never checked
    must not read as a video that passed."""
    bs = blocks("clip", "clip")
    plan = {
        "script_id": "cf-0137", "style": "motion",
        "duration": {"actual": 2.8, "target": [1, 60], "deviation": 0},
        "blocks": bs,
        "assetless_rung": assetless_rung.judge([], None, style="motion", blocks=bs),
        "rhythm": {"rhythm_requested": "staccato", "rhythm_delivered": "staccato",
                   "rhythm_shortfalls": [], "rhythm_delivered_fully": True},
    }
    qc = {"passed": True, "verdict": "pass", "checks": []}
    v = write_batch_metadata.video_record("cf-0137", plan, "video.mp4", qc, "motion")
    assert v["assetless_rung"]["passed"] is True, v["assetless_rung"]

    bare = json.loads(json.dumps(plan))
    bare.pop("assetless_rung")
    old = write_batch_metadata.video_record("cf-0137", bare, "video.mp4", qc, "motion")
    assert old["assetless_rung"]["passed"] is None, old["assetless_rung"]
    assert "predates" in old["assetless_rung"]["note"]


def test_the_batch_metadata_carries_the_plans_warnings():
    """CF-0330: a warned video reaches `05-video-editor.json` with its
    warnings - gate, code, numbers - under `videos[].warnings`; a plan from
    before warnings existed says `null`, not `[]`."""
    bs = blocks("clip", "procedural")
    gate = assetless_rung.judge(assetless_of(bs), None, style="motion", blocks=bs)
    w = plan_refusal.warning("cf-0330", plan_refusal.GATE_ASSETLESS_RUNG, "ASSETLESS BLOCKS: 1",
                             numbers={"blocks": [1], "block_count": 1})
    plan = {
        "script_id": "cf-0330", "style": "motion",
        "duration": {"actual": 2.8, "target": [1, 60], "deviation": 0},
        "blocks": bs, "assetless_rung": gate, "warnings": [w],
        "rhythm": {"rhythm_requested": "staccato", "rhythm_delivered": "staccato",
                   "rhythm_shortfalls": [], "rhythm_delivered_fully": True},
    }
    qc = {"passed": True, "verdict": "pass", "checks": []}
    v = write_batch_metadata.video_record("cf-0330", plan, "video.mp4", qc, "motion")
    assert v["assetless_rung"]["warned"] is True, v["assetless_rung"]
    assert v["warnings"] == [w], v["warnings"]
    assert v["warnings"][0]["reason_code"] == plan_refusal.PATTERN_UNDELIVERABLE
    plan.pop("warnings")
    assert write_batch_metadata.video_record("cf-0330", plan, "video.mp4", qc,
                                             "motion")["warnings"] is None


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

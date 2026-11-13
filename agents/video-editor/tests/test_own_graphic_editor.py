#!/usr/bin/env python3
"""CF-0689: `own_graphic` - the graphics the factory draws itself from the
script's facts (ExampleTech's base footage) - through the editor: the anchor
that places one (`visual_anchors[].graphic_id`), the storyboard block
(`asset_kind: "own_graphic"`), the plan's asset and `plan["own_graphics"]`,
the refusals, no credit, the gates (two sources, proof-quote cap, demo), the
kind lists, the frozen-graphic probe and the frame judge's overlay.

Stand-ins only: hand-made scripts, plans and storyboards, a faked matcher, a
tmp dir. No network, no real batch, no pool, no render.
"""
import _isolated_runlog  # noqa: F401 - CF-0482: run accounting never lands in a real batch
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import anchor_coverage  # noqa: E402
import meme_layer  # noqa: E402
import resolve_anchors  # noqa: E402
import script_anchors as sa  # noqa: E402
from _root_shared import root_module  # noqa: E402

og = root_module("own_graphic")

BENCH = {
    "graphic_id": "g1", "template": "benchmark",
    "data": {"metric": "SWE-bench Verified",
             "rows": [{"name": "Gemini 2.5 Pro", "score": "63.8%"},
                      {"name": "Claude 3.7", "score": "62.3%"}]},
    "values": [{"path": "data.metric", "text": "SWE-bench Verified", "claim_ids": ["c1"]},
               {"path": "data.rows[0].name", "text": "Gemini 2.5 Pro", "claim_ids": ["c1"]},
               {"path": "data.rows[0].score", "text": "63.8%", "claim_ids": ["c1"]},
               {"path": "data.rows[1].name", "text": "Claude 3.7", "claim_ids": ["c1"]},
               {"path": "data.rows[1].score", "text": "62.3%", "claim_ids": ["c1"]}],
    "source_label": "Google",
}
SPEC = {
    "graphic_id": "g2", "template": "spec_card",
    "data": {"product": "Pixel 10", "rows": [{"label": "Chip", "value": "Tensor G5"}]},
    "values": [{"path": "data.product", "text": "Pixel 10", "claim_ids": ["c2"]},
               {"path": "data.rows[0].label", "text": "Chip", "claim_ids": ["c2"]},
               {"path": "data.rows[0].value", "text": "Tensor G5", "claim_ids": ["c2"]}],
}

SCRIPT = {
    "script_id": "tech-1",
    "hook": "Google says its new model wins the coding test",
    "commentary": "the numbers are close and the chip is new",
    "payoff": "so who really wins",
    "visual_anchors": [
        {"anchor_id": "a1", "graphic_id": "g1", "beat_text": "wins the coding test"},
        {"anchor_id": "a2", "phrase": "a phone on a desk", "beat_text": "the chip is new"},
        {"anchor_id": "a3", "graphic_id": "g2", "beat_text": "who really wins"},
    ],
    "graphics": [BENCH, SPEC],
}


def _words(script):
    out, t = [], 0.2
    for sec in sa.SPOKEN_SECTIONS:
        for tok in (script.get(sec) or "").split():
            out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
            t += 0.4
    return out


# ------------------------------------------------------------ the anchors
def test_a_graphic_anchor_needs_no_phrase_and_asks_the_pool_nothing():
    anchors = sa.visual_anchors(SCRIPT)
    assert sa.phrases(anchors) == ["a phone on a desk"], sa.phrases(anchors)
    assert [a["anchor_id"] for a in sa.pool_anchors(anchors)] == ["a2"]
    # a pool anchor without its phrase is still a hand-back
    broken = {**SCRIPT, "visual_anchors": [{"anchor_id": "x", "beat_text": "the chip is new"}]}
    try:
        sa.visual_anchors(broken)
    except sa.HandBack as e:
        assert "phrase" in str(e)
    else:
        raise AssertionError("an anchor with neither phrase nor graphic_id passed")


def test_the_spec_carries_the_graphic_and_its_order():
    kept, dropped = sa.spec_anchors(sa.visual_anchors(SCRIPT), SCRIPT, _words(SCRIPT))
    assert not dropped, dropped
    by = {a["anchor_id"]: a for a in kept}
    assert by["a1"]["graphic_id"] == "g1" and by["a1"]["phrase"] is None
    assert "graphic_id" not in by["a2"] and by["a2"]["phrase"] == "a phone on a desk"
    spec = sa.build_spec(SCRIPT, kept)
    assert spec["graphics"] == {"g1": BENCH, "g2": SPEC}, spec.get("graphics")
    # a script without graphic anchors: no `graphics` key at all (Reel unchanged)
    plain = {**SCRIPT, "visual_anchors": [SCRIPT["visual_anchors"][1]]}
    kept, _ = sa.spec_anchors(sa.visual_anchors(plain), plain, _words(plain))
    assert "graphics" not in sa.build_spec(plain, kept)


def test_an_all_graphic_script_passes_the_preflight_without_a_pool():
    saved = resolve_anchors.match
    resolve_anchors.match = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the matcher was asked about a graphic"))
    try:
        rec = anchor_coverage.preflight([], ["/nowhere/pool.shots.json"])
    finally:
        resolve_anchors.match = saved
    assert rec["passed"] and rec["anchor_count"] == 0, rec
    assert "graphic" in rec["note"], rec["note"]


# ------------------------------------------------------------ the resolver
IDX = "/nowhere/pool.shots.json"
SRC = "/nowhere/pool.mp4"


@contextlib.contextmanager
def _patched(asked):
    saved = {k: getattr(resolve_anchors, k) for k in
             ("match", "cut", "usable", "audio_duration", "leading_silence", "load_words")}
    index_data = {IDX: {"source": SRC, "shots": [{"index": i, "start": i * 3.0,
                                                  "end": i * 3.0 + 3.0} for i in range(20)]}}

    def fake_match(indexes, phrases, min_score, top, python):
        asked.append(list(phrases))
        out = []
        for k, ph in enumerate(phrases):
            cands = [{"shot": s, "score": 0.31, "start": s * 3.0, "end": s * 3.0 + 3.0,
                      "card": False, "promoted": False, "index": IDX, "source": SRC}
                     for s in (2 * k + 1, 2 * k + 2)]
            out.append({"phrase": ph, "found": True, "discriminative": True, "margin": 0.1,
                        "candidates": cands})
        return out, index_data

    def fake_cut(source, start, duration, dest, crop_bottom=None, card=False):
        Path(dest).write_bytes(b"")
        return {"crop_bottom": 0.0, "frame_before_crop": "1920x1080"}

    resolve_anchors.match = fake_match
    resolve_anchors.cut = fake_cut
    resolve_anchors.usable = lambda clip, seconds, *a, **kw: (True, [])
    resolve_anchors.audio_duration = lambda path: 9.0
    resolve_anchors.leading_silence = lambda path: 0.0
    resolve_anchors.load_words = lambda path: [{"word": "w", "start": 0.4 + 0.4 * i,
                                                "end": 0.7 + 0.4 * i} for i in range(20)]
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(resolve_anchors, k, v)


def run_resolve(anchors, graphics, extra=(), index=(IDX,)):
    asked = []
    with tempfile.TemporaryDirectory() as tmp, _patched(asked):
        tmp = Path(tmp)
        spec = {"script_id": "tech-1", "anchors": anchors}
        if graphics is not None:
            spec["graphics"] = graphics
        (tmp / "anchors.json").write_text(json.dumps(spec))
        out = tmp / "storyboard.json"
        argv = ["resolve_anchors.py", str(tmp / "anchors.json"), str(tmp / "words.json"),
                str(tmp / "voice.wav"), str(out),
                *[x for ix in index for x in ("--index", ix)],
                "--clips-dir", str(tmp / "clips"), "--min-score", "0.22", *extra]
        saved_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                resolve_anchors.main()
        finally:
            sys.argv = saved_argv
        return json.loads(out.read_text()), asked


def test_resolve_writes_an_own_graphic_block_and_asks_only_the_pool_anchor():
    story, asked = run_resolve(
        [{"anchor_id": "a1", "phrase": None, "graphic_id": "g1", "word_index": 1},
         {"anchor_id": "a2", "phrase": "a phone on a desk", "word_index": 8}],
        {"g1": BENCH}, extra=["--rhythm", "staccato"])
    assert asked == [["a phone on a desk"]], asked
    g = [b for b in story["blocks"] if b["asset_kind"] == "own_graphic"]
    assert g, story["blocks"]
    assert g[0]["graphic"] == BENCH and g[0]["graphic_id"] == "g1"
    assert g[0]["shot"] is None and g[0]["graphic_offset"] == 0.0
    others = [b for b in story["blocks"] if b["asset_kind"] != "own_graphic"]
    assert others and all(b["asset_kind"] != "typographic" for b in others), others


def test_an_all_graphic_storyboard_never_calls_the_matcher():
    story, asked = run_resolve(
        [{"anchor_id": "a1", "phrase": None, "graphic_id": "g1", "word_index": 1},
         {"anchor_id": "a3", "phrase": None, "graphic_id": "g2", "word_index": 9}],
        {"g1": BENCH, "g2": SPEC})
    assert asked == [], asked
    kinds = {b["asset_kind"] for b in story["blocks"]}
    assert kinds == {"own_graphic"}, story["blocks"]
    ids = [b["graphic_id"] for b in story["blocks"]]
    assert ids[0] == "g1" and ids[-1] == "g2", ids


def test_an_all_graphic_storyboard_needs_no_index_at_all():
    """CF-0814: Tech 0844Z - both scripts on own graphics, no pool; the
    resolve is asked with no --index and builds the graphic blocks."""
    story, asked = run_resolve(
        [{"anchor_id": "a1", "phrase": None, "graphic_id": "g1", "word_index": 1},
         {"anchor_id": "a3", "phrase": None, "graphic_id": "g2", "word_index": 9}],
        {"g1": BENCH, "g2": SPEC}, index=())
    assert asked == [], asked
    assert {b["asset_kind"] for b in story["blocks"]} == {"own_graphic"}, story["blocks"]


def test_an_anchor_that_asks_the_pool_still_needs_an_index():
    try:
        run_resolve(
            [{"anchor_id": "a1", "phrase": None, "graphic_id": "g1", "word_index": 1},
             {"anchor_id": "a2", "phrase": "a phone on a desk", "word_index": 8}],
            {"g1": BENCH}, index=())
    except SystemExit as e:
        assert e.code == 2, e.code    # argparse's usage error, "which pool is it?"
    else:
        raise AssertionError("a pool anchor was resolved against no pool")


def test_the_preflight_refuses_no_index_under_a_pool_anchor():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "03-content-researcher.json"
        path.write_text(json.dumps({"scripts": [SCRIPT]}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = sa.main(["preflight", str(path), "--script-id", "tech-1"])
        assert code == sa.EXIT_CANNOT_ANSWER, (code, err.getvalue())
        assert "which pool is it?" in err.getvalue(), err.getvalue()


def test_a_graphic_the_script_never_ordered_reaches_the_block_as_none():
    story, _ = run_resolve(
        [{"anchor_id": "a1", "phrase": None, "graphic_id": "g9", "word_index": 1}], {})
    b = story["blocks"][0]
    assert b["asset_kind"] == "own_graphic" and b["graphic"] is None, b


def test_a_split_run_of_one_graphic_continues_its_animation():
    prev = {"asset_kind": "own_graphic", "graphic_id": "g1", "graphic_offset": 0.0,
            "_start": 0.4, "_end": 3.0}
    b = resolve_anchors.graphic_block({"graphic_id": "g1", "word_index": 1}, {"g1": BENCH},
                                      3.0, 6.0, {"role": "even"}, prev)
    assert b["graphic_offset"] == 2.6, b
    b = resolve_anchors.graphic_block({"graphic_id": "g2", "word_index": 1}, {"g2": SPEC},
                                      3.0, 6.0, {"role": "even"}, prev)
    assert b["graphic_offset"] == 0.0, b



# ------------------------------------------------------------ the plan
import subprocess  # noqa: E402
import wave  # noqa: E402

import own_graphic_plan  # noqa: E402
import plan_refusal  # noqa: E402
import repo_paths  # noqa: E402
from _stand_in_theme import STAND_IN_THEME  # noqa: E402

SCRIPTS = HERE.parent / "scripts"


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


def _gblock(gid, graphic, start, end, offset=0.0):
    return {"word_range": [0, 0], "intent": f"own graphic {gid}", "asset_kind": "own_graphic",
            "graphic_id": gid, "graphic": graphic, "graphic_offset": offset,
            "emphasis_words": [], "rhythm_role": "beat", "side": None, "shot": None,
            "held_frame": False, "_start": start, "_end": end}


def _storyboard(blocks):
    return {"script_id": "tech-1", "style": "motion", "resolved_from_anchors": True,
            "rhythm": {"pattern_requested": "explainer", "rhythm_requested": "staccato",
                       "rhythm_built": "staccato",
                       "parameters": {"block_count": len(blocks), "key_frame_hold_seconds": 2.0},
                       "opening_requested": "hook_over_footage",
                       "opening_delivered": "hook_over_footage", "anchor_count": len(blocks)},
            "blocks": blocks, "unresolved_anchors": [], "rejected_candidates": []}


def run_plan(blocks, extra=(), language="en"):
    """build_render_plan.py on a hand-made storyboard -> (proc, plan|None, refusal|None)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _silent_wav(tmp / "voice.wav")
        words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
                  "end": round(0.9 + i * 0.5, 2)} for i in range(10)]
        (tmp / "words.json").write_text(json.dumps(words))
        (tmp / "storyboard.json").write_text(json.dumps(_storyboard(blocks)))
        cfg = tmp / "tech.json"
        cfg.write_text(json.dumps({"channel_id": "test-tech", "display_name": "Test Tech",
                                   "language": language, "theme": STAND_IN_THEME}))
        venv_py = Path(repo_paths.VENV_PY3)
        py = str(venv_py) if venv_py.exists() else sys.executable
        out = tmp / "plan.json"
        r = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "motion", "--target-duration", "1", "60", "--channel", str(cfg),
             *extra], capture_output=True, text=True, cwd=tmp, timeout=240)
        plan = json.loads(out.read_text()) if out.exists() else None
        ref = tmp / "plan.refusal.json"
        refusal = json.loads(ref.read_text()) if ref.exists() else None
        return r, plan, refusal


GRAPHIC_ONLY = [_gblock("g1", BENCH, 0.0, 2.0), _gblock("g1", BENCH, 2.0, 3.6, offset=2.0),
                _gblock("g2", SPEC, 3.6, 5.6)]


def test_a_graphic_only_plan_is_built_with_its_asset_and_record():
    r, plan, refusal = run_plan(GRAPHIC_ONLY)
    assert r.returncode == 0 and plan, (r.returncode, r.stderr[-3000:])
    assert refusal is None, refusal
    a = plan["blocks"][0]["asset"]
    assert a == {"kind": "own_graphic", "graphic_id": "g1", "template": "benchmark",
                 "data": BENCH["data"], "source_label": "Google",
                 "caption": "According to Google", "lang": "en", "offset_seconds": 0.0,
                 "bars": [1.0, round(62.3 / 63.8, 4)]}, a
    assert "bars" not in plan["blocks"][2]["asset"]
    assert plan["blocks"][1]["asset"]["offset_seconds"] == 2.0
    assert plan["blocks"][2]["asset"]["caption"] is None
    rows = plan[own_graphic_plan.FIELD]
    assert [r_["graphic_id"] for r_ in rows] == ["g1", "g2"], rows
    assert rows[0]["blocks"] == [0, 1] and rows[0]["seconds"] == 3.6, rows[0]
    assert "Gemini 2.5 Pro: 63.8%" in rows[0]["viewer_text"]
    assert rows[0]["viewer_text"].endswith("According to Google"), rows[0]
    # no credit: a graphic is not a borrowed source
    assert not plan.get("footage_credits"), plan.get("footage_credits")
    assert not plan.get("credit_overlays"), plan.get("credit_overlays")
    # the two-source gate: entirely ours, the rule does not apply
    gate = plan["two_source_gate"]
    assert gate["passed"] is True and gate["applies"] is False, gate
    assert gate["own_graphic_seconds"] > 5 and gate["own_graphic_blocks"] == [0, 1, 2], gate
    assert "own_graphic" in gate["note"], gate["note"]
    # nothing went to the assetless rung or was flattened
    assert plan["assetless_rung"]["passed"] is True, plan["assetless_rung"]
    assert {b["asset"]["kind"] for b in plan["blocks"]} == {"own_graphic"}


def test_bars_are_read_off_the_scores():
    g = {"template": "benchmark", "data": {"rows": [{"name": "A", "score": "1.5B"},
                                                    {"name": "B", "score": "750M"}]}}
    assert own_graphic_plan.bars(g) == [1.0, 0.5]
    g["data"]["rows"][1]["score"] = "n/a"
    assert own_graphic_plan.bars(g) is None


def test_a_russian_channel_gets_the_russian_source_line():
    r, plan, _ = run_plan([_gblock("g1", BENCH, 0.0, 5.6)], language="ru")
    assert r.returncode == 0, r.stderr[-2000:]
    assert plan["blocks"][0]["asset"]["caption"] == "По данным Google"


def test_the_whole_video_typographic_drop_keeps_the_graphic():
    r, plan, _ = run_plan(GRAPHIC_ONLY, extra=["--style", "typographic"])
    assert r.returncode == 0, r.stderr[-2000:]
    assert {b["asset"]["kind"] for b in plan["blocks"]} == {"own_graphic"}, plan["blocks"]
    assert any("kept through the whole-video typographic drop" in n
               for n in plan.get("notes") or []), plan.get("notes")


def _refused(blocks, code):
    r, plan, refusal = run_plan(blocks)
    assert r.returncode == 2 and plan is None, (r.returncode, r.stderr[-2000:])
    assert refusal and refusal["gate"] == plan_refusal.GATE_OWN_GRAPHIC, refusal
    assert refusal["reason_code"] == "held_back", refusal
    assert code in refusal["reason"], refusal["reason"]
    return refusal


def test_a_graphic_anchor_naming_no_order_refuses_the_plan():
    _refused([_gblock("g9", None, 0.0, 5.6)], own_graphic_plan.CODE_NOT_ORDERED)


def test_a_malformed_order_refuses_the_plan():
    bad = json.loads(json.dumps(BENCH))
    bad["data"]["rows"] = bad["data"]["rows"][:1]          # a benchmark needs 2..5 rows
    bad["values"] = [v for v in bad["values"] if "rows[1]" not in v["path"]]
    _refused([_gblock("g1", bad, 0.0, 5.6)], og.FAIL_MALFORMED)


def test_text_no_value_names_refuses_the_plan():
    extra = json.loads(json.dumps(SPEC))
    extra["values"] = [v for v in extra["values"] if v["path"] != "data.rows[0].label"]
    rec = _refused([_gblock("g2", extra, 0.0, 5.6)], og.FAIL_ADDS_TEXT)
    assert "data.rows[0].label" in rec["reason"], rec["reason"]


def test_an_unbenchmarked_source_line_refuses_the_plan():
    bare = {k: v for k, v in BENCH.items() if k != "source_label"}
    _refused([_gblock("g1", bare, 0.0, 5.6)], og.FAIL_BENCHMARK_UNATTRIBUTED)



# ------------------------------------------------------------ kinds and QC
import qc_render  # noqa: E402
import rhythm  # noqa: E402


def test_the_kind_lists_know_the_graphic():
    assert "own_graphic" in rhythm.PICTURE_KINDS
    assert "own_graphic" not in rhythm.FROZEN_KINDS, "a graphic moves - QC holds it to that"
    assert "own_graphic" in meme_layer.NO_FOOTAGE_KINDS
    assert "own_graphic" in qc_render._NO_INSERT_LAYER_KINDS
    b = {"start": 0, "end": 3, "shot": None, "asset": {"kind": "own_graphic", "graphic_id": "g1"}}
    assert rhythm.has_picture(b) and not rhythm._is_frozen(b)
    # two graphics are two pictures, the same graphic continued is one
    c = {**b, "asset": {"kind": "own_graphic", "graphic_id": "g2"}}
    assert rhythm._picture_id(b) != rhythm._picture_id(c)
    assert rhythm._picture_id(b) == rhythm._picture_id(dict(b))
    # an ordinary clip's picture id is what it always was
    clip = {"shot": "x:1", "asset": {"kind": "clip", "src": "a.mp4"}}
    assert rhythm._picture_id(clip) == ("x:1", "a.mp4", None)


def _frozen_with(timeline):
    saved = qc_render.motion_timeline
    qc_render.motion_timeline = lambda video, vf, seconds=None: timeline
    try:
        plan = {"blocks": [{"start": 0.0, "end": 3.0, "shot": None,
                            "asset": {"kind": "own_graphic", "graphic_id": "g1"}}]}
        return qc_render.frozen_blocks("/nowhere/video.mp4", plan)
    finally:
        qc_render.motion_timeline = saved


def test_a_moving_graphic_passes_qc_and_a_frozen_one_is_a_fault():
    gap = qc_render.PROBE_GAP
    n = int(3.0 / gap)
    assert _frozen_with([(round(i * gap, 3), 6.0) for i in range(n)]) == []
    recs = _frozen_with([(round(i * gap, 3), 6.0 if i < 2 else 0.1) for i in range(n)])
    assert len(recs) == 1 and recs[0]["fault"] is True, recs
    assert "own graphic g1" in recs[0]["reason"], recs[0]
    assert recs[0]["still_run"] >= qc_render.MAX_HELD_RUN, recs[0]


# ------------------------------------------------------------ CF-0923
# Tech 08.11 github: on a declared `alternate` a run of same-side anchors is
# one swing block, and only its first graphic was ever drawn - g11 held the
# last 10.2 s while the narrator moved on to the summing-up (g12, never shown).
SPEC3 = {**SPEC, "graphic_id": "g3",
         "data": {"product": "Pixel 11", "rows": [{"label": "Chip", "value": "Tensor G6"}]},
         "values": [{"path": "data.product", "text": "Pixel 11", "claim_ids": ["c3"]},
                    {"path": "data.rows[0].label", "text": "Chip", "claim_ids": ["c3"]},
                    {"path": "data.rows[0].value", "text": "Tensor G6", "claim_ids": ["c3"]}]}
BENCH_A = {**BENCH, "graphic_id": "g1"}


def _run_alternate(third_word):
    # words at 0.4 + 0.4 i, voice 9.0 s (the _patched stand-ins)
    return run_resolve(
        [{"anchor_id": "a1", "phrase": None, "graphic_id": "g1", "word_index": 1, "side": "a"},
         {"anchor_id": "a2", "phrase": None, "graphic_id": "g2", "word_index": 6, "side": "b"},
         {"anchor_id": "a3", "phrase": None, "graphic_id": "g3", "word_index": third_word,
          "side": "b"}],
        {"g1": BENCH_A, "g2": SPEC, "g3": SPEC3}, extra=["--rhythm", "alternate"], index=())


def test_every_graphic_of_a_same_side_run_is_drawn_from_its_own_word():
    story, asked = _run_alternate(14)
    assert asked == [], asked
    blocks = story["blocks"]
    assert [b["graphic_id"] for b in blocks] == ["g1", "g2", "g3"], blocks
    assert [b["side"] for b in blocks] == ["a", "b", "b"], blocks
    # g3 takes over LEAD_SECONDS before its word (6.0 s), g2 holds up to it,
    # and the run's outer boundaries are where the crossing put them
    g2, g3 = blocks[1], blocks[2]
    lead = resolve_anchors.LEAD_SECONDS
    assert abs(g3["_start"] - (6.0 - lead)) < 1e-6 and abs(g2["_end"] - g3["_start"]) < 1e-6
    assert abs(g2["_start"] - (2.8 - lead)) < 1e-6 and abs(g3["_end"] - 9.0) < 1e-6
    assert g3["graphic"] == SPEC3 and g3["graphic_offset"] == 0.0


def test_a_too_short_piece_folds_into_its_longer_neighbour():
    # g3 at word 7 (3.2 s): g2 would hold 0.4 s, under MIN_SWING_CUT_SECONDS
    story, _ = _run_alternate(7)
    assert [b["graphic_id"] for b in story["blocks"]] == ["g1", "g3"], story["blocks"]
    assert abs(story["blocks"][1]["_start"] - (2.8 - resolve_anchors.LEAD_SECONDS)) < 1e-6


def test_graphic_shots_keeps_one_picture_off_the_swing():
    anchors = [{"graphic_id": "g1"}, {"graphic_id": "g2"}]
    starts = [0.4, 5.0]
    for role in ("hold", "beat", "staccato"):
        seg = {"anchors": [0, 1], "role": role, "start": 0.0, "end": 9.0}
        assert resolve_anchors.graphic_shots(seg, 0, anchors, starts, 0.0, 9.0) == \
            [(0, 0.0, 9.0)], role
    seg = {"anchors": [0, 1], "role": "swing", "start": 0.0, "end": 9.0}
    lead = resolve_anchors.LEAD_SECONDS
    assert resolve_anchors.graphic_shots(seg, 0, anchors, starts, 0.0, 9.0) == \
        [(0, 0.0, round(5.0 - lead, 3)), (1, round(5.0 - lead, 3), 9.0)]
    # the same graphic placed twice in a run is one piece, not a cut
    same = [{"graphic_id": "g1"}, {"graphic_id": "g1"}]
    assert resolve_anchors.graphic_shots(seg, 0, same, starts, 0.0, 9.0) == [(0, 0.0, 9.0)]
    # a pool anchor inside the run is not a graphic: the graphic holds over it
    mixed = [{"graphic_id": "g1"}, {"phrase": "a phone"}]
    assert resolve_anchors.graphic_shots(seg, 0, mixed, starts, 0.0, 9.0) == [(0, 0.0, 9.0)]


def test_the_hook_graphic_is_never_folded_away():
    """CF-0923 (coordinator's correction): the first graphic of the opening
    segment is the hook. The github 08.11 numbers (copied, no batch read):
    v1 g1 at 0.25 s and v2 g2 at 1.60 s are one side-a run 0-4.57 s; g1's own
    piece would be 1.25 s - it holds 1.6 s and g2 follows. The tail run
    (v11 g11 at 30.76 s, v12 g12 at 34.28 s, voice to 40.575 s) is cut as
    before."""
    gids = [{"graphic_id": f"g{n}"} for n in range(1, 13)]
    starts = [0.25, 1.6] + [5.0 + 2.5 * n for n in range(8)] + [30.76, 34.28]
    head = {"anchors": [0, 1], "role": "swing", "start": 0.0, "end": 4.57}
    shots = resolve_anchors.graphic_shots(head, 0, gids, starts, 0.0, 4.57, opening=True)
    assert shots == [(0, 0.0, 1.6), (1, 1.6, 4.57)], shots
    # off the opening the same numbers fold the short g1 piece, as before
    assert resolve_anchors.graphic_shots(head, 0, gids, starts, 0.0, 4.57) == [(1, 0.0, 4.57)]
    tail = {"anchors": [10, 11], "role": "swing", "start": 30.41, "end": 40.575}
    assert resolve_anchors.graphic_shots(tail, 10, gids, starts, 30.41, 40.575) == \
        [(10, 30.41, 33.93), (11, 33.93, 40.575)]
    # a neighbour too short after the hook takes its floor folds into the hook
    shots = resolve_anchors.graphic_shots(head, 0, gids, [0.25, 1.6], 0.0, 2.8, opening=True)
    assert shots == [(0, 0.0, 2.8)], shots


def test_the_hook_holds_its_graphic_through_the_resolver():
    # words at 0.4 + 0.4 i (the _patched stand-ins): g1 at 0.8 s and g2 at
    # 1.2 s open the video on side a, g3 at 5.2 s is side b
    story, _ = run_resolve(
        [{"anchor_id": "a1", "phrase": None, "graphic_id": "g1", "word_index": 1, "side": "a"},
         {"anchor_id": "a2", "phrase": None, "graphic_id": "g2", "word_index": 2, "side": "a"},
         {"anchor_id": "a3", "phrase": None, "graphic_id": "g3", "word_index": 12, "side": "b"}],
        {"g1": BENCH_A, "g2": SPEC, "g3": SPEC3}, extra=["--rhythm", "alternate"], index=())
    blocks = story["blocks"]
    assert [b["graphic_id"] for b in blocks] == ["g1", "g2", "g3"], blocks
    floor = resolve_anchors.rhythm.MIN_SWING_CUT_SECONDS
    assert blocks[0]["_start"] == 0.0 and abs(blocks[0]["_end"] - floor) < 1e-6, blocks[0]
    assert abs(blocks[1]["_start"] - floor) < 1e-6, blocks[1]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
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

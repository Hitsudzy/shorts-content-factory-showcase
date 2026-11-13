#!/usr/bin/env python3
"""CF-0567: the proof-quote cap (scripts/proof_quote_cap.py) and its two gates
in build_render_plan.py - a vendor's official clip is a short quote, never the
base; a demo's footage is our own recording. Channels without `proof_quotes`
(ExampleFilm, ExampleScience) are not measured at all.

Stand-ins only: hand-made plans and footage-origin documents in the channel's
shape, a tmp factory root and batch. No network, no real channel data, no pool.
"""
import _isolated_runlog  # noqa: F401 - CF-0482: run accounting never lands in a real batch
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_refusal  # noqa: E402
import proof_quote_cap as pq  # noqa: E402
import repo_paths  # noqa: E402

VENDOR = "vendorQuote"            # official upload, rights name the origin
VENDOR2 = "vendorTwoXX"           # rights carry role: proof_quote
VENDOR3 = "vendorThree"           # rights name the channel id only
OWN = "own_capture-acme-fox-demo-20261011t120000z"
YT = "someTrailer"                # anybody else's upload (not a quote source)
CHANNEL_ID = "UCexample000000000000040"

TECH = {
    "proof_quotes": {"role": "proof_quote", "max_seconds_per_quote": 5.0,
                     "max_quotes_per_video": 2, "max_seconds_per_video": 8.0,
                     "never_the_base": True},
    "official_channels": [{"pattern": "openai", "origin": "vendor_official",
                           "role": "proof_quote",
                           "channels": [{"id": CHANNEL_ID, "title": "OpenAI"}]}],
}
SCIENCE = {"licences": {"accepted": [{"id": "cc_by"}]},
           "official_channels": [{"pattern": "nasa", "origin": "nasa",
                                  "channels": [{"id": "UCexample000000000000010"}]}]}
RIGHTS = {
    VENDOR: {"judged": True, "licence": "youtube_official_upload",
             "footage_origin": "vendor_official"},
    VENDOR2: {"judged": True, "role": "proof_quote"},
    VENDOR3: {"judged": False, "channel_id": CHANNEL_ID},
    OWN: {"judged": True, "licence": "own_capture", "footage_origin": "own_capture"},
    YT: {"judged": False},
}


def _reader(calls=None):
    def read(vid):
        if calls is not None:
            calls.append(vid)
        return RIGHTS.get(vid), "01b"
    return read


def _b(start, end, vid):
    return {"start": start, "end": end, "shot": f"{vid}:1",
            "asset": {"kind": "clip", "src": f"/nonexistent/a00_{vid}_s001.mp4"}}


def _plan(*spans):
    return {"blocks": [_b(s, e, v) for s, e, v in spans]}


def test_who_is_a_quote():
    for vid in (VENDOR, VENDOR2, VENDOR3):
        assert pq.is_quote(vid, RIGHTS[vid], TECH), vid
    assert not pq.is_quote(OWN, RIGHTS[OWN], TECH)
    assert not pq.is_quote(OWN, {"role": "proof_quote"}, TECH), "own capture is never a quote"
    assert not pq.is_quote(YT, RIGHTS[YT], TECH)
    assert not pq.is_quote(VENDOR, RIGHTS[VENDOR], SCIENCE)


def test_a_demo_with_one_short_quote_passes():
    plan = _plan((0, 6, OWN), (6, 10, VENDOR), (10, 30, OWN))
    rec = pq.judge(plan, _reader(), TECH, "demo")
    assert rec["applies"] and rec["passed"], rec
    assert rec["quote_count"] == 1 and rec["quote_seconds"] == 4.0
    assert rec["own_capture_seconds"] == 26.0 and rec["footage_seconds"] == 30.0
    assert rec["quotes"][0] == {"video_id": VENDOR, "blocks": [1], "start_s": 6.0,
                                "end_s": 10.0, "seconds": 4.0}


def test_one_quote_over_five_seconds_even_across_two_blocks():
    rec = pq.judge(_plan((0, 10, OWN), (10, 13, VENDOR), (13, 16, VENDOR), (16, 40, OWN)),
                   _reader(), TECH, "demo")
    assert rec["refused_because"] == [pq.CODE_QUOTE_TOO_LONG], rec
    assert rec["quote_count"] == 1 and rec["quotes"][0]["blocks"] == [1, 2]
    assert rec["gate"] == plan_refusal.GATE_PROOF_QUOTE_CAP
    # the same source twice, apart: two quotes, each within the cap
    rec = pq.judge(_plan((0, 10, OWN), (10, 13, VENDOR), (13, 20, OWN), (20, 23, VENDOR),
                         (23, 40, OWN)), _reader(), TECH, "demo")
    assert rec["passed"] and rec["quote_count"] == 2, rec


def test_three_quotes_are_too_many():
    rec = pq.judge(_plan((0, 10, OWN), (10, 12, VENDOR), (12, 20, OWN), (20, 22, VENDOR2),
                         (22, 30, OWN), (30, 32, VENDOR3), (32, 45, OWN)), _reader(), TECH)
    assert rec["refused_because"] == [pq.CODE_TOO_MANY_QUOTES], rec


def test_two_quotes_over_eight_seconds_in_all():
    rec = pq.judge(_plan((0, 10, OWN), (10, 14.5, VENDOR), (14.5, 25, OWN),
                         (25, 29.5, VENDOR2), (29.5, 45, OWN)), _reader(), TECH)
    assert rec["refused_because"] == [pq.CODE_QUOTES_OVER_VIDEO], rec
    assert rec["quote_seconds"] == 9.0


def test_quotes_are_never_the_base():
    # quotes within every cap, but most of the footage there is
    rec = pq.judge(_plan((0, 4, VENDOR), (4, 6, OWN), (6, 10, VENDOR2)), _reader(), TECH)
    assert rec["refused_because"] == [pq.CODE_QUOTE_IS_BASE], rec
    assert rec["gate"] == plan_refusal.GATE_PROOF_QUOTE_CAP


def test_a_demo_must_be_mostly_our_recording():
    rec = pq.judge(_plan((0, 4, OWN), (4, 8, VENDOR), (8, 20, YT)), _reader(), TECH, "demo")
    assert rec["refused_because"] == [pq.CODE_DEMO_NOT_OWN], rec
    assert rec["gate"] == plan_refusal.GATE_DEMO_OWN_CAPTURE
    # the same plan is not a demo under another pattern: only the caps apply
    assert pq.judge(_plan((0, 4, OWN), (4, 8, VENDOR), (8, 20, YT)), _reader(),
                    TECH, "explainer")["passed"]


def test_reel_and_science_are_not_measured():
    """No `proof_quotes`: nothing read, nothing refused - even a plan made of
    one official upload end to end."""
    for doc in (SCIENCE, {}, None):
        calls = []
        rec = pq.judge(_plan((0, 30, VENDOR)), _reader(calls), doc, "explainer")
        assert rec["applies"] is False and rec["passed"] is True, rec
        assert rec["refused_because"] == [] and rec["quotes"] == []
        assert calls == [], "a channel without caps had its rights read"
    assert pq.stage_fields({}) is None


def test_the_two_gates_have_their_funnel_codes():
    assert plan_refusal.code_for(plan_refusal.GATE_PROOF_QUOTE_CAP) == plan_refusal.HELD_BACK
    assert (plan_refusal.code_for(plan_refusal.GATE_DEMO_OWN_CAPTURE)
            == plan_refusal.PATTERN_UNDELIVERABLE)
    src = (SCRIPTS / "build_render_plan.py").read_text()
    assert "build_proof_quote_cap(args, blocks, order[\"pattern_id\"])" in src
    assert "proof_quote_cap.FIELD: quote_record" in src


def test_build_proof_quote_cap_reads_the_channel_and_the_batch():
    import build_render_plan as brp
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        root = tmp / "root"
        for ch, doc in (("techstand", TECH), ("scistand", SCIENCE)):
            (root / "channels" / ch).mkdir(parents=True)
            (root / "channels" / f"{ch}.json").write_text(json.dumps({"channel_id": ch}))
            (root / "channels" / ch / "footage-origin.json").write_text(json.dumps(doc))
        batch = tmp / "batch"
        (batch / "work" / "slug").mkdir(parents=True)
        (batch / "01b-footage-index.json").write_text(json.dumps({"fetched": [
            {"video_id": v, "rights": RIGHTS[v]} for v in (VENDOR, OWN)]}))
        blocks = _plan((0, 4, OWN), (4, 10, VENDOR), (10, 30, OWN))["blocks"]
        env = {k: os.environ.get(k) for k in ("FACTORY_ROOT", "FOOTAGE_DIR")}
        os.environ["FACTORY_ROOT"] = str(root)
        os.environ["FOOTAGE_DIR"] = str(tmp / "empty-pool")
        try:
            got = {}
            for ch in ("techstand", "scistand"):
                args = argparse.Namespace(footage_index=None, index=[], channel=ch,
                                          output=str(batch / "work" / "slug" / "plan.json"))
                got[ch] = brp.build_proof_quote_cap(args, blocks, "explainer")
        finally:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    assert got["techstand"]["refused_because"] == [pq.CODE_QUOTE_TOO_LONG], got["techstand"]
    assert got["scistand"]["applies"] is False and got["scistand"]["passed"], got["scistand"]


def _voice_wav(path, seconds=6.0):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))


def test_a_plan_without_a_channel_carries_the_record_unmeasured():
    """The planner end to end on a typographic stand-in with no channel: the
    plan carries `proof_quote_cap` (applies false) and `own_captures` ([])."""
    py = Path(repo_paths.VENV_PY3)
    py = str(py) if py.exists() else sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _voice_wav(tmp / "voice.wav")
        words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
                  "end": round(0.9 + i * 0.5, 2)} for i in range(10)]
        (tmp / "words.json").write_text(json.dumps(words))
        story = {"script_id": "cf-0567", "style": "typographic",
                 "blocks": [{"word_range": [0, 4], "intent": "hook", "asset_kind": "text",
                             "asset_query": "", "emphasis_words": []},
                            {"word_range": [5, 9], "intent": "payoff", "asset_kind": "text",
                             "asset_query": "", "emphasis_words": []}]}
        (tmp / "storyboard.json").write_text(json.dumps(story))
        out = tmp / "plan.json"
        res = subprocess.run(
            [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
             str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
             "--style", "typographic", "--target-duration", "1", "60"],
            capture_output=True, text=True, cwd=tmp, timeout=240,
            env={**os.environ, "FOOTAGE_DIR": str(tmp / "pool")})
        assert res.returncode == 0, res.stderr[-2000:]
        plan = json.loads(out.read_text())
        assert plan["proof_quote_cap"]["applies"] is False, plan["proof_quote_cap"]
        assert plan["own_captures"] == [], plan["own_captures"]
        assert "proof-quote cap" not in res.stderr


# ---------------------------------------------------------------- CF-0689
def _g(start, end, gid="g1"):
    return {"start": start, "end": end, "shot": None,
            "asset": {"kind": "own_graphic", "graphic_id": gid, "template": "benchmark"}}


def test_own_graphics_are_footage_and_ours_cf0689():
    """A graphic-based video: the graphics are the base, a short quote beside
    them is within its caps, and `never_the_base` measures against them."""
    plan = {"blocks": [_g(0, 10), _b(10, 14, VENDOR), _g(14, 30, "g2")]}
    rec = pq.judge(plan, _reader(), TECH, "explainer")
    assert rec["passed"], rec
    assert rec["own_graphic_seconds"] == 26.0 and rec["footage_seconds"] == 30.0, rec
    # without the graphics the same quote would be the whole base
    rec = pq.judge({"blocks": [_b(10, 14, VENDOR)]}, _reader(), TECH, "explainer")
    assert rec["refused_because"] == [pq.CODE_QUOTE_IS_BASE], rec


def test_a_demo_still_needs_its_recording_with_graphics_cf0689():
    # graphics alone are not a demo: a demo shows the tool
    rec = pq.judge({"blocks": [_g(0, 30)]}, _reader(), TECH, "demo")
    assert rec["refused_because"] == [pq.CODE_DEMO_NOT_OWN], rec
    assert rec["gate"] == plan_refusal.GATE_DEMO_OWN_CAPTURE
    assert "no recording at all and no API chat" in rec["refusals"][0]["text"], rec
    assert rec["api_demo_seconds"] == 0.0, rec
    # a recording plus graphics: own = capture + graphic, more than half
    rec = pq.judge({"blocks": [_b(0, 8, OWN), _g(8, 20), _b(20, 24, VENDOR), _b(24, 30, YT)]},
                   _reader(), TECH, "demo")
    assert rec["passed"], rec
    assert rec["own_capture_seconds"] == 8.0 and rec["own_graphic_seconds"] == 12.0
    # the same recording without the graphics is not more than half
    rec = pq.judge({"blocks": [_b(0, 8, OWN), _b(8, 20, YT), _b(20, 24, VENDOR),
                               _b(24, 30, YT)]}, _reader(), TECH, "demo")
    assert rec["refused_because"] == [pq.CODE_DEMO_NOT_OWN], rec



# ---------------------------------------------------------------- CF-0690
def _chat(start, end, gid="chat1"):
    return {"start": start, "end": end, "shot": None,
            "asset": {"kind": "own_graphic", "graphic_id": gid, "template": "api_chat"}}


def test_the_api_chat_shows_the_tool_cf0690():
    """The model's real answer through its API stands where a recording would:
    a chat + graphics over half of the footage is a demo with no capture."""
    rec = pq.judge({"blocks": [_chat(0, 8), _g(8, 20), _b(20, 24, VENDOR), _b(24, 30, YT)]},
                   _reader(), TECH, "demo")
    assert rec["passed"], rec
    assert rec["api_demo_seconds"] == 8.0 and rec["own_graphic_seconds"] == 20.0, rec
    assert rec["own_capture_seconds"] == 0.0, rec
    assert "API chat 8.00s" in rec["note"], rec["note"]
    # a chat alone is a demo too
    assert pq.judge({"blocks": [_chat(0, 12)]}, _reader(), TECH, "demo")["passed"]
    # a chat beside a recording: both count
    rec = pq.judge({"blocks": [_b(0, 6, OWN), _chat(6, 14), _b(14, 24, YT)]},
                   _reader(), TECH, "demo")
    assert rec["passed"], rec


def test_a_chat_is_still_held_to_more_than_half_cf0690():
    rec = pq.judge({"blocks": [_chat(0, 6), _b(6, 20, YT), _b(20, 24, VENDOR)]},
                   _reader(), TECH, "demo")
    assert rec["refused_because"] == [pq.CODE_DEMO_NOT_OWN], rec
    assert "of them the API chat 6.00s" in rec["refusals"][0]["text"], rec
    assert "no API chat" not in rec["refusals"][0]["text"], rec


def test_api_demo_seconds_count_only_the_chat_template():
    plan = {"blocks": [_chat(0, 4), _g(4, 10), _b(10, 12, OWN), _chat(12, 13.5, "chat2")]}
    assert pq.api_demo_seconds(plan) == 5.5
    assert pq.api_demo_seconds({"blocks": [_g(0, 10)]}) == 0.0


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

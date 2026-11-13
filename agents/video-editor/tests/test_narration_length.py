#!/usr/bin/env python3
"""CF-0087: the narration-length gate at the TTS stage.

Batch 2026-09-03T2037Z rendered four videos of 62-70s against a 35-60s
target, each one announced on stderr and in RUN_LOG and none of them
stopped. What is pinned here is the line between a note and a refusal:

  voice + end card <= 55s   silent
  55s < total <= 60s        a warning line, the pipeline proceeds
  total > 60s               rejected - build_render_plan.py writes no plan,
                            narration_length.py exits 2

plus: a script with no `narration` block (any batch before CF-0087) is still
gated on the actual length; the end card's seconds come from the channel
config and are not typed into this repo a third time; the estimate the
script carries is reported against the actual and never gates anything.

Seconds to run: synthetic silent wavs, no TTS, no render.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import ast
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from repo_paths import CHANNELS_DIR, VENV_PY  # noqa: E402 - CF-0125: resolved against the main checkout

import narration_length as nl  # noqa: E402

# The block as the channel config carries it (channels/example-film.json),
# minus the prose. Tests build their own copy so they do not depend on the
# factory root being reachable from this checkout.
BUDGET = {
    "target_total_seconds": 55,
    "end_card_seconds": 3,
    "narration_seconds": 52,
    "words_per_second": 2.75,
    "words_per_second_source": "batch 2026-09-03T2037Z, Kokoro am_puck@0.95, ±5%",
    "narration_words_min": 135,
    "narration_words_max": 150,
    "counted_sections": ["hook", "commentary", "payoff"],
}

REAL_CHANNEL = CHANNELS_DIR / "example-film.json"


def silent_wav(path, seconds, rate=24000):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(round(seconds * rate)))
    return path


def channel_file(tmp, budget=BUDGET):
    path = Path(tmp) / "channel.json"
    path.write_text(json.dumps({"id": "test", "display_name": "Test Channel", "theme": STAND_IN_THEME, "narration_budget": budget}))
    return path


def run_cli(*args):
    return subprocess.run([VENV_PY, str(SCRIPTS / "narration_length.py"), *map(str, args)],
                          capture_output=True, text=True)


def run_plan(tmp, voice, *extra):
    """build_render_plan.py on an empty storyboard: the gate sits before the
    first block is looked at, so no asset is needed to reach it."""
    story = Path(tmp) / "storyboard.json"
    story.write_text(json.dumps({"style": "stills", "blocks": []}))
    words = Path(tmp) / "words.json"
    words.write_text(json.dumps({"words": []}))
    out = Path(tmp) / "plan.json"
    r = subprocess.run([VENV_PY, str(SCRIPTS / "build_render_plan.py"), str(story),
                        str(words), str(voice), str(out), *map(str, extra)],
                       capture_output=True, text=True)
    return r, out


# --------------------------------------------------------------------------
# 1. the verdict - pure arithmetic
# --------------------------------------------------------------------------

def test_under_the_target_is_silent():
    rec = nl.judge(50.0, BUDGET)
    assert rec["verdict"] == "ok", rec
    assert rec["total_seconds"] == 53.0, rec
    assert rec["over_target_by"] == 0.0 and rec["over_ceiling_by"] == 0.0, rec
    assert nl.report_lines(rec) == [], nl.report_lines(rec)


def test_exactly_on_the_target_is_still_silent():
    assert nl.judge(52.0, BUDGET)["verdict"] == "ok"


def test_over_the_target_under_the_ceiling_is_a_warning():
    rec = nl.judge(54.0, BUDGET)
    assert rec["verdict"] == "warn", rec
    assert rec["total_seconds"] == 57.0 and rec["over_target_by"] == 2.0, rec
    lines = nl.report_lines(rec)
    assert len(lines) == 1 and lines[0].startswith("NARRATION OVER TARGET"), lines
    assert "60s ceiling" in lines[0], lines


def test_exactly_on_the_ceiling_is_not_a_rejection():
    """60.0 total is the last allowed second - the range was 35-60 inclusive."""
    assert nl.judge(57.0, BUDGET)["verdict"] == "warn"


def test_over_the_ceiling_is_rejected():
    rec = nl.judge(58.0, BUDGET)
    assert rec["verdict"] == "reject", rec
    assert rec["total_seconds"] == 61.0 and rec["over_ceiling_by"] == 1.0, rec
    lines = nl.report_lines(rec)
    assert lines[0].startswith("NARRATION OVER CEILING"), lines


def test_the_batch_that_started_this_would_have_been_stopped():
    """The four voice.wav lengths of 2026-09-03T2037Z, as RUN_LOG recorded
    them. Every one of them rendered; every one of them is a rejection now."""
    for seconds in (62.12, 64.58, 69.72, 63.73):
        assert nl.judge(seconds, BUDGET)["verdict"] == "reject", seconds


def test_the_end_card_is_what_tips_a_voice_over_the_line():
    """58s of voice is under 60 on its own. It is the card, reserved from the
    channel config, that makes the total 61 - a gate on the voice alone would
    have let this one through and produced a 61s video."""
    assert nl.judge(58.0, None)["verdict"] == "ok"
    assert nl.judge(58.0, BUDGET)["verdict"] == "reject"


# --------------------------------------------------------------------------
# 2. missing pieces - the ceiling holds without them
# --------------------------------------------------------------------------

def test_no_budget_at_all_still_gates_on_the_ceiling():
    """A checkout without the factory root, or a channel with no
    narration_budget: no target, no end card, no estimate - and 61s of voice
    is still refused."""
    rec = nl.judge(61.0, None)
    assert rec["verdict"] == "reject", rec
    assert rec["target_total_seconds"] is None and rec["tail_seconds"] == 0.0, rec
    assert rec["tail_key"] is None and rec["video_length"] is None, rec
    assert nl.judge(59.0, None)["verdict"] == "ok"
    assert nl.load_narration_budget(None) is None
    assert nl.load_narration_budget("no-such-channel-anywhere") is None


def test_a_script_without_the_narration_block_is_still_gated():
    """Every script before CF-0087 has no `narration`; some carry the old
    `estimated_spoken_duration_seconds`, which undercounted. Neither shape
    crashes, neither skips the ceiling."""
    old = {"script_id": "s", "hook": "..", "commentary": "..", "payoff": ".."}
    assert nl.script_estimate(old) == (None, None)
    rec = nl.judge(61.0, BUDGET, nl.script_estimate(old)[0])
    assert rec["verdict"] == "reject" and rec["delta_vs_estimate"] is None, rec

    legacy = dict(old, estimated_spoken_duration_seconds=45)
    est, label = nl.script_estimate(legacy)
    assert (est, label) == (45.0, "estimated_spoken_duration_seconds")

    new = dict(old, narration={"estimated_seconds": 60.0, "verdict": "over"},
               estimated_spoken_duration_seconds=45)
    est, label = nl.script_estimate(new)
    assert (est, label) == (60.0, "narration.estimated_seconds"), \
        "the CF-0087 block wins over the legacy field when both are present"
    assert nl.script_estimate(None) == (None, None)
    assert nl.script_estimate({"narration": "not a dict"}) == (None, None)


def test_the_estimate_is_reported_and_never_gates():
    """A voice that came out 8s shorter than estimated is fine; one that came
    out 3s longer than a 62s estimate is rejected for its length, not for
    the miss. The delta is on the record either way."""
    rec = nl.judge(50.0, BUDGET, estimated_seconds=58.0)
    assert rec["verdict"] == "ok" and rec["delta_vs_estimate"] == -8.0, rec
    lines = nl.report_lines(rec)
    assert len(lines) == 1 and lines[0].startswith("NARRATION ESTIMATE"), lines
    assert "-8.0s" in lines[0] and "am_puck" in lines[0], lines

    rec = nl.judge(65.0, BUDGET, estimated_seconds=62.0)
    assert rec["verdict"] == "reject" and rec["delta_vs_estimate"] == 3.0, rec


# --------------------------------------------------------------------------
# 3. the end card comes from the config
# --------------------------------------------------------------------------

def test_end_card_seconds_is_read_from_the_channel_config():
    with tempfile.TemporaryDirectory() as tmp:
        four = channel_file(tmp, dict(BUDGET, end_card_seconds=4))
        budget = nl.load_narration_budget(four)
        assert budget["end_card_seconds"] == 4
        assert nl.judge(56.5, budget)["verdict"] == "reject", \
            "56.5 + 4 = 60.5 is over the ceiling once the config says 4"
        assert nl.judge(56.5, BUDGET)["verdict"] == "warn", \
            "56.5 + 3 = 59.5 is under it with the config's 3"

        none = channel_file(tmp, {"target_total_seconds": 55})
        rec = nl.judge(58.0, nl.load_narration_budget(none))
        assert rec["tail_seconds"] == 0.0 and rec["verdict"] == "warn", rec


def test_end_card_seconds_is_not_a_literal_anywhere_in_this_repo():
    """The config calls its 3 a PLACEHOLDER pending CF-0065. When it changes
    there, nothing here may still say 3: no assignment or default in the two
    files that know about the card carries a numeric end-card literal."""
    for name in ("narration_length.py", "build_render_plan.py"):
        tree = ast.parse((SCRIPTS / name).read_text())
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.keyword) and node.arg:
                targets, value = [node.arg], node.value
            else:
                continue
            if any("end_card" in t for t in targets):
                assert not isinstance(value, ast.Constant) or not isinstance(
                    value.value, (int, float)), (
                    f"{name}: {targets} is assigned a numeric literal - the "
                    f"end card's length lives in channels/<channel>.json only")


def test_the_real_channel_config_reads_back_the_agreed_numbers():
    """Only when the factory root is on disk next to this checkout."""
    if not REAL_CHANNEL.exists():
        print("SKIP (channels/example-film.json is not reachable from here)")
        return
    budget = nl.load_narration_budget("example-film")
    assert budget is not None
    assert budget["target_total_seconds"] == 55 and budget["end_card_seconds"] == 3
    # CF-0141: the narration is what is left after the *tail*, and the tail is
    # the channel's ending clip when it has one - `end_card_seconds` beside it
    # is only the floor it would fall back to if the file went away. Same
    # precedence and the same tolerance as patterns/validate_patterns.py
    # (NARRATION_TAIL_KEYS, NARRATION_SECONDS_TOLERANCE): the stored
    # `narration_seconds` is rounded for a human reader (49.83 for 55 - 5.167),
    # so it is checked to the hundredth rather than exactly.
    tail = next(budget[k] for k in ("ending_seconds", "end_card_seconds")
                if budget.get(k) is not None)
    assert abs(budget["narration_seconds"]
               - (budget["target_total_seconds"] - tail)) <= 0.005
    assert nl.HARD_CEILING_SECONDS == 60.0


# --------------------------------------------------------------------------
# 4. the CLI at the TTS stage
# --------------------------------------------------------------------------

def test_cli_verdicts_and_exit_codes():
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp)
        cases = [(50.0, 0, ""), (54.0, 0, "NARRATION OVER TARGET"),
                 (58.0, nl.REJECT_EXIT_CODE, "NARRATION OVER CEILING")]
        for seconds, code, marker in cases:
            wav = silent_wav(Path(tmp) / f"v{seconds}.wav", seconds)
            r = run_cli(wav, "--channel", ch)
            assert r.returncode == code, (seconds, r.returncode, r.stderr)
            if marker:
                assert marker in r.stderr, (seconds, r.stderr)
            else:
                # CF-0107: the run-accounting library's "no batch dir" warning
                # is not the gate's output.
                noise = [l for l in r.stderr.splitlines() if l.strip() and not l.startswith("[runlog]")]
                assert noise == [], (seconds, r.stderr)


def test_cli_reads_the_estimate_off_the_script_file():
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp)
        wav = silent_wav(Path(tmp) / "v.wav", 50.0)
        scripts = Path(tmp) / "03-content-researcher.json"
        scripts.write_text(json.dumps({"scripts": [
            {"script_id": "new", "narration": {"estimated_seconds": 52.0}},
            {"script_id": "old", "estimated_spoken_duration_seconds": 45},
            {"script_id": "bare"},
        ]}))
        r = run_cli(wav, "--channel", ch, "--script", scripts, "--script-id", "new",
                    "--json")
        assert r.returncode == 0, r.stderr
        rec = json.loads(r.stdout)
        assert rec["delta_vs_estimate"] == -2.0 and rec["verdict"] == "ok", rec
        assert "NARRATION ESTIMATE" in r.stderr, r.stderr

        r = run_cli(wav, "--channel", ch, "--script", scripts, "--script-id", "bare",
                    "--json")
        assert r.returncode == 0 and json.loads(r.stdout)["delta_vs_estimate"] is None

        r = run_cli(wav, "--channel", ch, "--script", scripts, "--script-id", "gone")
        assert r.returncode == 0 and "no estimate to compare" in r.stderr, r.stderr


def test_cli_without_a_channel_says_so_and_holds_the_ceiling():
    with tempfile.TemporaryDirectory() as tmp:
        wav = silent_wav(Path(tmp) / "v.wav", 61.0)
        r = run_cli(wav)
        assert r.returncode == nl.REJECT_EXIT_CODE, r.stderr
        r = run_cli(wav, "--channel", "no-such-channel")
        assert r.returncode == nl.REJECT_EXIT_CODE, r.stderr
        assert "no narration_budget" in r.stderr, r.stderr


# --------------------------------------------------------------------------
# 5. build_render_plan.py refuses the plan
# --------------------------------------------------------------------------

def test_build_render_plan_writes_no_plan_over_the_ceiling():
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp)
        wav = silent_wav(Path(tmp) / "v.wav", 58.0)
        r, out = run_plan(tmp, wav, "--channel", ch)
        assert r.returncode == nl.REJECT_EXIT_CODE, (r.returncode, r.stderr)
        assert "NARRATION OVER CEILING - plan not written" in r.stderr, r.stderr
        assert not out.exists(), "a refused plan must not be on disk"


def test_build_render_plan_holds_the_ceiling_with_no_channel_and_no_estimate():
    """A run the way every batch before CF-0087 invoked it: no --channel, a
    script with no narration block. 61s of voice is still refused."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = silent_wav(Path(tmp) / "v.wav", 61.0)
        r, out = run_plan(tmp, wav)
        assert r.returncode == nl.REJECT_EXIT_CODE, (r.returncode, r.stderr)
        assert not out.exists()


def test_build_render_plan_proceeds_on_a_warning_and_records_it():
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp)
        wav = silent_wav(Path(tmp) / "v.wav", 54.0)
        r, out = run_plan(tmp, wav, "--channel", ch, "--estimated-seconds", 52)
        assert r.returncode == 0, (r.returncode, r.stderr)
        assert "NARRATION OVER TARGET" in r.stderr, r.stderr
        assert "plan not written" not in r.stderr, r.stderr
        rec = json.loads(out.read_text())["duration"]["narration"]
        assert rec["verdict"] == "warn" and rec["total_seconds"] == 57.0, rec
        assert rec["tail_seconds"] == 3.0 and rec["tail_key"] == "end_card_seconds", rec
        assert rec["delta_vs_estimate"] == 2.0, rec

        wav = silent_wav(Path(tmp) / "ok.wav", 50.0)
        r, out = run_plan(tmp, wav, "--channel", ch)
        assert r.returncode == 0, (r.returncode, r.stderr)
        assert "NARRATION" not in r.stderr, r.stderr
        assert json.loads(out.read_text())["duration"]["narration"]["verdict"] == "ok"


def test_the_ceiling_is_the_upper_target_bound_not_a_second_constant():
    """--target-duration's upper bound is the ceiling the gate holds, so a
    channel that legitimately moves its range moves the gate with it."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = silent_wav(Path(tmp) / "v.wav", 61.0)
        r, out = run_plan(tmp, wav, "--target-duration", 35, 70)
        assert r.returncode == 0, (r.returncode, r.stderr)
        assert json.loads(out.read_text())["duration"]["narration"]["ceiling_seconds"] == 70.0


# --------------------------------------------------------------------------
# 6. CF-0158: the band is derived, and the floor of it exists at all
# --------------------------------------------------------------------------

# A channel of the shape CF-0158 left behind: its own finished-video band, and
# an ending clip that is what the video really closes on. `end_card_seconds`
# sits beside it as the floor a channel with no clip would fall back to - and
# as the number this gate wrongly counted between CF-0141 and CF-0158.
BANDED = dict(BUDGET, total_seconds_min=45, total_seconds_max=60,
              ending_seconds=5.167, narration_seconds=49.833)


def test_the_tail_is_the_ending_clip_and_not_the_drawn_card():
    """The defect CF-0141 left in this file and CF-0158 folded in: with both
    keys present the gate counted the 3s card the channel does not use
    instead of the 5.167s clip it does, and every verdict came out 2.167s
    short of the video it was about."""
    rec = nl.judge(50.0, BANDED)
    assert rec["tail_key"] == "ending_seconds" and rec["tail_seconds"] == 5.167, rec
    assert rec["total_seconds"] == 55.167, rec
    assert round(rec["total_seconds"] - (50.0 + BANDED["end_card_seconds"]), 3) == 2.167, \
        "the card-vs-clip gap is exactly the length the old gate under-counted"
    # A voice that fits under the ceiling on the card and does not on the clip:
    # the case the old arithmetic let through into a 61s video.
    assert nl.judge(56.0, dict(BANDED, ending_seconds=None))["verdict"] == "warn"
    assert nl.judge(56.0, BANDED)["verdict"] == "reject"


def test_the_fallback_tail_order_is_the_validators_order():
    """`TAIL_KEYS_WITHOUT_ROOT` is a copy, reached only on a checkout with no
    factory root above it. Pinned equal to the original wherever the original
    is readable, so it cannot become a second opinion on CF-0141's
    precedence."""
    vp = nl.validator()
    if vp is None:
        print("SKIP (patterns/validate_patterns.py is not reachable from here)")
        return
    assert tuple(vp.NARRATION_TAIL_KEYS) == nl.TAIL_KEYS_WITHOUT_ROOT


def test_the_narration_band_is_the_channels_band_minus_its_tail():
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    assert nl.narration_band(BANDED) == (39.833, 54.833)
    # The first acceptance line of CF-0158: the floor is not a constant.
    longer = nl.narration_band(dict(BANDED, ending_seconds=7.167))
    assert longer == (37.833, 52.833), longer
    # A config from before CF-0158 has no band of its own; the factory's own
    # 45-60 still applies and this channel's tail still comes out of it.
    assert nl.narration_band(BUDGET) == (42.0, 57.0)
    # Nothing to subtract from, and nothing invented: the whole-video band.
    assert nl.narration_band(None) == (45.0, 60.0)


def test_the_plans_target_is_derived_and_moves_with_the_ending_clip():
    """`duration.target` in the plan - the literal `[35.0, 60.0]` this task
    replaces. Lengthen the channel's ending clip by two seconds and both ends
    of the plan's target come down by exactly two."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        wav = silent_wav(Path(tmp) / "v.wav", 45.0)
        r, out = run_plan(tmp, wav, "--channel", channel_file(tmp, BANDED))
        assert r.returncode == 0, r.stderr
        plan = json.loads(out.read_text())
        assert plan["duration"]["target"] == [39.833, 54.833], plan["duration"]
        assert any("derived (CF-0158)" in n for n in plan["notes"]), plan["notes"]

        longer = channel_file(tmp, dict(BANDED, ending_seconds=7.167))
        r, out = run_plan(tmp, wav, "--channel", longer)
        assert r.returncode == 0, r.stderr
        assert json.loads(out.read_text())["duration"]["target"] == [37.833, 52.833]


def test_the_argparse_default_carries_no_length_literal():
    """The 35 had no second occurrence in the factory because it was nobody's
    arithmetic. Nothing may put a length literal back into that default."""
    tree = ast.parse((SCRIPTS / "build_render_plan.py").read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "add_argument"
                and node.args and getattr(node.args[0], "value", None) == "--target-duration"):
            continue
        default = next((k.value for k in node.keywords if k.arg == "default"), None)
        assert isinstance(default, ast.Constant) and default.value is None, \
            "--target-duration's default is derived from the channel, not typed"
        break
    else:
        raise AssertionError("--target-duration is gone from build_render_plan.py")


def test_the_gate_ceiling_is_the_band_top_plus_the_tail():
    """The band is on the narration, the ceiling is on the finished video.
    On today's channel the derived 54.833s top plus the 5.167s clip is the
    same 60s CF-0087 has always refused above - the refusal did not move."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp, BANDED)
        r, out = run_plan(tmp, silent_wav(Path(tmp) / "ok.wav", 54.5), "--channel", ch)
        assert r.returncode == 0, r.stderr
        rec = json.loads(out.read_text())["duration"]["narration"]
        assert rec["ceiling_seconds"] == 60.0, rec
        # 55s of voice is 60.167s of video: over the ceiling, and refused -
        # under the old arithmetic (voice + the 3s card = 58s) it was not.
        out.unlink()  # run_plan writes one plan.json per tmp dir
        r, out = run_plan(tmp, silent_wav(Path(tmp) / "long.wav", 55.0), "--channel", ch)
        assert r.returncode == nl.REJECT_EXIT_CODE, (r.returncode, r.stderr)
        assert not out.exists(), "a refused plan must not be on disk"


def test_a_short_video_is_recognised_named_and_not_refused():
    """The second acceptance line of CF-0158. Before it a 40s video passed
    every gate in silence; it is now a warning with a number on it, and it is
    deliberately NOT a refusal - the fix is more substance, which no step of
    this pipeline can add."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    rec = nl.judge(30.0, BANDED)
    assert rec["verdict"] == "ok", "the old two lines still say nothing about it"
    band = rec["video_length"]
    assert band["verdict"] == "short" and band["action"] == "warn", band
    assert band["total_seconds"] == 35.167 and band["deviation"] == -9.833, band
    assert any("UNDER THE BAND" in line for line in nl.report_lines(rec)), rec

    with tempfile.TemporaryDirectory() as tmp:
        wav = silent_wav(Path(tmp) / "short.wav", 30.0)
        r, out = run_plan(tmp, wav, "--channel", channel_file(tmp, BANDED))
        assert r.returncode == 0, (r.returncode, r.stderr)
        assert out.exists(), "a short video is a warning, never a refused plan"
        assert "UNDER THE BAND" in r.stderr, r.stderr
        rec = json.loads(out.read_text())["duration"]["narration"]["video_length"]
        assert rec["verdict"] == "short" and rec["action"] == "warn", rec
        assert json.loads(out.read_text())["duration"]["deviation"] < 0


# --------------------------------------------------------------------------
# 5. CF-0293: the hard floor below the band
#
# The user, 2026-09-20: "keep videos up to 45 s, hard limit down to 30 s.
# Everything under 45 s - with a warning and counted for later." So the band's
# 45 s floor keeps behaving exactly as CF-0158 left it - a loud line, the
# video is made - and a *second* floor at 30 s refuses before the render, with
# the machine-readable record the 60 s ceiling has had since CF-0087.
#
# The arithmetic these four lines pin is the root's, not this repo's: the
# channel's tail here is the 5.167 s ending clip, so the voice lengths below
# are the four finished-video lengths minus it.
# --------------------------------------------------------------------------

sys.path.insert(0, str(SCRIPTS))
import plan_refusal  # noqa: E402

FLOORED = dict(BANDED, total_seconds_hard_min=30)

#       voice    video   verdict      action
BOUNDARIES = [(24.733, 29.9, "too_short", "refuse"),
              (24.833, 30.0, "short", "warn"),
              (39.733, 44.9, "short", "warn"),
              (39.833, 45.0, "in_band", "pass")]


def test_the_four_boundaries_the_decision_names():
    """29.9 / 30 / 44.9 / 45, on this side of the fence. The floor is
    inclusive like both ends of the band: 30.00s is a short video that gets
    made, 29.90s is not a video at all."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    for voice, video, verdict, action in BOUNDARIES:
        rec = nl.judge(voice, FLOORED)
        band = rec["video_length"]
        assert rec["total_seconds"] == video, (voice, rec["total_seconds"])
        assert (band["verdict"], band["action"]) == (verdict, action), (voice, band)
        assert band["hard_min"] == 30.0, band
        # The ceiling's own verdict is untouched by any of them.
        assert rec["verdict"] == "ok", (voice, rec["verdict"])
        lines = nl.report_lines(rec)
        if action == "pass":
            assert not any("VIDEO" in l for l in lines), (voice, lines)
        else:
            # The defect this task found: `too_short` fell through to the
            # `elif` and a 25s video was announced as being OVER the band.
            assert any("VIDEO UNDER THE BAND" in l for l in lines), (voice, lines)
            assert not any("VIDEO OVER THE BAND" in l for l in lines), (voice, lines)


def test_the_verdict_and_the_code_are_the_roots_own():
    """This repo spells `too_short` and `video_too_short` in two files
    (scripts/ is stdlib-only and does not import the root at module level).
    Pinned against the root wherever the root is on disk, so neither copy can
    drift into a second opinion - the same guard CF-0158 put on the tail
    keys."""
    vp = nl.validator()
    if vp is None:
        print("SKIP (no factory root)")
        return
    assert nl.VIDEO_TOO_SHORT_VERDICT in vp.VIDEO_LENGTH_VERDICTS
    assert nl.VIDEO_TOO_SHORT_VERDICT not in vp.VIDEO_LENGTH_MADE, \
        "a video under the hard floor is not made"
    # The two verdicts this repo calls "under the band", and nothing else: the
    # root's four, minus the one inside the band and the one above it.
    assert set(nl.VIDEO_UNDER_VERDICTS) == \
        set(vp.VIDEO_LENGTH_VERDICTS) - {"in_band", "over"}, nl.VIDEO_UNDER_VERDICTS
    assert plan_refusal.GATE_CODES[plan_refusal.GATE_NARRATION_FLOOR] == \
        vp.VIDEO_LENGTH_REFUSAL_CODE


def test_a_video_under_the_hard_floor_is_refused_before_the_plan():
    """The plan builder's half: no plan on disk, exit 2, and the refusal
    record the funnel reads - the same three things the 60s ceiling has
    produced since CF-0254."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp, FLOORED)
        wav = silent_wav(Path(tmp) / "tiny.wav", 24.733)
        r, out = run_plan(tmp, wav, "--channel", ch, "--script-id", "s1")
        assert r.returncode == nl.REJECT_EXIT_CODE, (r.returncode, r.stderr)
        assert not out.exists(), "a refused plan must not be on disk"
        assert "VIDEO UNDER THE HARD FLOOR - plan not written" in r.stderr, r.stderr
        rec = json.loads((Path(tmp) / "plan.refusal.json").read_text())
        assert rec["gate"] == plan_refusal.GATE_NARRATION_FLOOR, rec
        assert rec["reason_code"] == plan_refusal.VIDEO_TOO_SHORT, rec
        assert rec["script_id"] == "s1" and "29.90s" in rec["reason"], rec


def test_a_video_of_thirty_to_forty_five_seconds_is_still_made():
    """The half of the decision that is NOT a refusal. Both ends of the
    30-45s stretch reach a written plan, carrying the `short` mark the run
    summary counts them by."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    for voice in (24.833, 39.733):
        with tempfile.TemporaryDirectory() as tmp:
            ch = channel_file(tmp, FLOORED)
            wav = silent_wav(Path(tmp) / "short.wav", voice)
            r, out = run_plan(tmp, wav, "--channel", ch)
            assert r.returncode == 0, (voice, r.returncode, r.stderr)
            assert out.exists(), (voice, "a short video is made, it is not refused")
            assert "UNDER THE BAND" in r.stderr and "HARD FLOOR" not in r.stderr, r.stderr
            band = json.loads(out.read_text())["duration"]["narration"]["video_length"]
            assert band["verdict"] == "short" and band["action"] == "warn", band
            assert not (Path(tmp) / "plan.refusal.json").exists()


def test_the_gate_itself_refuses_the_voice_it_measured():
    """The gate runs before the plan builder does (that is CF-0282's whole
    point), so the refusal has to be complete here too: exit 2, the sidecar
    beside the wav, and the numbers the floor refused on."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        ch = channel_file(tmp, FLOORED)
        scripts = Path(tmp) / "03-content-researcher.json"
        scripts.write_text(json.dumps({"scripts": [{"script_id": "s1"}]}))
        wav = silent_wav(Path(tmp) / "voice.wav", 24.733)
        r = run_cli(wav, "--channel", ch, "--script", scripts, "--script-id", "s1")
        assert r.returncode == nl.REJECT_EXIT_CODE, (r.returncode, r.stderr)
        assert "VIDEO UNDER THE HARD FLOOR" in r.stderr, r.stderr
        assert "ok/too_short" in r.stdout, r.stdout
        rec = json.loads((Path(tmp) / "voice.refusal.json").read_text())
        assert rec["gate"] == plan_refusal.GATE_NARRATION_FLOOR, rec
        assert rec["reason_code"] == plan_refusal.VIDEO_TOO_SHORT, rec
        assert rec["numbers"]["hard_min_seconds"] == 30.0, rec["numbers"]
        assert rec["numbers"]["total_seconds"] == 29.9, rec["numbers"]

        # And the 30s end of the same channel: nothing refused, nothing written.
        ok = silent_wav(Path(tmp) / "ok.wav", 24.833)
        r = run_cli(ok, "--channel", ch, "--script", scripts, "--script-id", "s1")
        assert r.returncode == 0, r.stderr
        assert not (Path(tmp) / "ok.refusal.json").exists()


def test_a_channel_with_no_hard_floor_is_judged_as_before():
    """`total_seconds_hard_min` is a key of the channel config, and a config
    that does not carry one (a checkout from before CF-0293, a test's budget)
    gets the three old verdicts - the floor is never invented here."""
    if nl.validator() is None:
        print("SKIP (no factory root)")
        return
    rec = nl.judge(24.733, BANDED)
    assert rec["video_length"]["verdict"] == "short", rec["video_length"]
    with tempfile.TemporaryDirectory() as tmp:
        wav = silent_wav(Path(tmp) / "tiny.wav", 24.733)
        r, out = run_plan(tmp, wav, "--channel", channel_file(tmp, BANDED))
        assert r.returncode == 0 and out.exists(), (r.returncode, r.stderr)


def test_the_real_channel_carries_the_hard_floor():
    """The decision is only real if the channel on disk states it: 30s, and
    strictly below the 45s floor of the band it sits under."""
    if not REAL_CHANNEL.is_file():
        print("SKIP (no factory root)")
        return
    budget = json.loads(REAL_CHANNEL.read_text())["narration_budget"]
    assert budget["total_seconds_hard_min"] == 30, budget
    assert budget["total_seconds_hard_min"] < budget["total_seconds_min"]
    assert nl.judge(20.0, budget)["video_length"]["verdict"] == "too_short"


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

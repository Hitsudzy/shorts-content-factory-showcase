#!/usr/bin/env python3
"""CF-0087: the narration-length gate at the TTS stage.

Batch 2026-09-03T2037Z put all four videos over the 35-60s target (62-70s of
voice each) and the pipeline said so twice - `synthesize_voiceover.py` printed
the length, `build_render_plan.py` printed `DURATION OFF TARGET (+2.1s)` - and
then rendered them anyway. Both were notes. This module is the gate: the
actual `voice.wav` length, plus the end card, against the channel's budget.

Two lines, and only one of them is hard:

- `target_total_seconds` (55 on example-film; the middle of the channel's
  band since CF-0158) - a total over it is a warning on stderr, exactly what
  the old `DURATION OFF TARGET` line was.
- `HARD_CEILING_SECONDS` (60 - the never-cross top of the finished video's
  45-60s band, CF-0158) - a total over it is a rejection: the voice-over is
  handed back to the script, nothing downstream of it gets built.
  `build_render_plan.py` refuses to write a plan for it, the same way it
  refuses one with a rejected asset.

CF-0158: the total is voice + **the channel's tail**, and the tail is the
ending clip on a channel that ships one (`ending_seconds`, 5.167s here),
falling back to the drawn card (`end_card_seconds`, 3s) on a channel with
none. Until CF-0158 this gate added `end_card_seconds` unconditionally, which
CF-0141 had already stopped being the truth: on example-film it judged
every voice-over 2.167s shorter than the video it was going to become. The
choice between the two keys is not made here - `patterns/validate_patterns.py
tail_seconds()` makes it for the whole factory, and this module asks it.

The budget block is `narration_budget` in `channels/<channel>.json`, read
the way `build_render_plan.py` reads `patterns/` - relative to the factory
root, read-only from this side, and absent on a checkout of this repo alone.
Without it the gate still holds the 60s ceiling; only the 55s target and
the end-card buffer need the config. `end_card_seconds` there is a
placeholder pending CF-0065 (the card is not built), so here it is a
reservation of seconds the render does not yet contain, not a segment of it.
(CF-0141 built the card; on a channel with an `ending.mp4` the tail is that
file and the card's constant is only the floor a channel without one gets.)

The script's own estimate (`narration.estimated_seconds`, written by Content
Researcher since CF-0087; older batches carry only
`estimated_spoken_duration_seconds` or nothing) is compared and reported,
not gated: it is the signal for whether words-per-second still holds.

Usage: narration_length.py voice.wav [--channel example-film]
                           [--script 03-content-researcher.json --script-id ID]
                           [--ceiling 60] [--json]
Exit 0 on ok/warn, 2 on reject (the code build_render_plan.py uses for a
refused plan).

CF-0293: a second refusal at the other end - the finished video under the
channel's hard floor (`narration_budget.total_seconds_hard_min`, 30 s on
example-film, the user's decision of 2026-09-20). Same exit code, same record,
gate `narration_floor`, funnel code `video_too_short`. A video of 30-45 s is
untouched by it: `short`, a loud line on stderr, and the video is made.

CF-0282: a rejection also writes the refusal record - `plan_refusal` (CF-0254),
gate `narration_ceiling`, funnel code `held_back`, a `voice.refusal.json`
sidecar beside the wav it measured - because this gate fires before a plan
exists and the plan builder's copy of the same gate therefore never runs. It
needs `--script`/`--script-id` to key the record on; without them it says so
and writes nothing.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import audio_duration  # noqa: E402
from repo_paths import CHANNELS_DIR, FACTORY_ROOT  # noqa: E402 - CF-0125: above the main checkout
import plan_refusal  # noqa: E402 - CF-0282: a refusal here is a record, not just an exit code
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

# The never-cross top of the finished video's 45-60s band (CF-0158; before it
# the same number was described as the top of a "35-60s range" whose floor was
# nobody's arithmetic). The 55s target is the middle of that band and the
# channel config can move it; this one is the ceiling the whole factory agrees
# on (patterns/validate_patterns.py MAX_TARGET_SECONDS), so a caller
# overriding it is expected to say why on the command line. It is a ceiling on
# the whole video - voice plus tail - not on the voice alone.
HARD_CEILING_SECONDS = 60.0

# CF-0158: the tail-key precedence, used only when the factory root is not
# reachable from this checkout (a bare clone of this repo with a budget handed
# in as a file). patterns/validate_patterns.py NARRATION_TAIL_KEYS is the
# source of it; test_narration_length.py pins the two lists equal whenever the
# root IS on disk, so this copy cannot quietly drift into a second opinion.
TAIL_KEYS_WITHOUT_ROOT = ("ending_seconds", "end_card_seconds")

# Same convention as build_render_plan.py's PATTERNS_DIR: the channel config
# lives in the factory root, one level above agents/ (imported above - two
# levels up from a worktree lands inside .claude, CF-0125).

# Exit code of a refused plan in build_render_plan.py ("ASSETS REJECTED - plan
# not written"). Reused so the caller has one code to mean "hand it back".
REJECT_EXIT_CODE = 2

# CF-0293: the fourth verdict of the root's `judge_video_length()`. The names
# are spelled here rather than imported because the validator may be out of
# reach (see validator()); when it IS reachable the record simply carries one
# of these strings and `tests/test_narration_length.py` pins the tuple against
# the root's `VIDEO_LENGTH_VERDICTS` / `VIDEO_LENGTH_MADE`.
#
# `too_short` is the *finished video* under the channel's hard floor
# (`narration_budget.total_seconds_hard_min`, 30 s on example-film - the user's
# decision of 2026-09-20). It is a refusal before the render, by the same
# machinery the 60 s ceiling has used since CF-0087, and not a warning: under
# half the target there is no short video to rescue, there is a broken one.
# 30-45 s is unchanged - `short`, a loud line, the video is still made.
VIDEO_TOO_SHORT_VERDICT = "too_short"
VIDEO_UNDER_VERDICTS = ("short", VIDEO_TOO_SHORT_VERDICT)
VIDEO_TOO_SHORT_HEADLINE = "VIDEO UNDER THE HARD FLOOR"


def load_narration_budget(channel):
    """`narration_budget` from channels/<channel>.json, or None when the
    factory root is not reachable from here or the block is not there."""
    if not channel:
        return None
    # A channel name resolves under the factory root; a path to a .json is
    # read as given (a test's temp config, or a checkout where the root is
    # somewhere else).
    path = Path(channel) if str(channel).endswith(".json") else CHANNELS_DIR / f"{channel}.json"
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    block = cfg.get("narration_budget")
    return block if isinstance(block, dict) else None


# --------------------------------------------------------------------------
# CF-0158: the factory's length arithmetic, asked for rather than copied
# --------------------------------------------------------------------------

_VALIDATOR = []  # one-slot cache: [] not tried yet, [None] tried and absent


def validator():
    """`patterns/validate_patterns.py`, imported by path, or None.

    The same seam `end_card.py:_validator_min_block_seconds()` opened for
    MIN_BLOCK_SECONDS, for the same reason: the length arithmetic of CF-0158
    (`tail_seconds()`, `narration_band()`, `judge_video_length()`) is one
    subtraction that the whole factory has to agree on, and a copy of it here
    is exactly how the two repos would come to disagree - which is what
    CF-0141 already did to this file once, leaving it adding the drawn card
    to a channel whose videos end on a clip.

    None when the factory root is not reachable (a checkout of this repo
    alone, the case the module docstring describes) or when the root's own
    channel config will not load: every caller here degrades instead of
    raising, because the 60s ceiling has to hold either way.
    """
    if not _VALIDATOR:
        try:
            import importlib.util
            path = Path(FACTORY_ROOT) / "patterns" / "validate_patterns.py"
            spec = importlib.util.spec_from_file_location(
                "_cf0158_validate_patterns", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _VALIDATOR.append(module)
        except Exception:  # noqa: BLE001 - no root, no derivation, no crash
            _VALIDATOR.append(None)
    return _VALIDATOR[0]


def tail_seconds(budget):
    """How long the video runs past the last word, and under which key.

    Returns `(seconds, key)` - `(0.0, None)` for a budget that names no tail
    at all, which is what a config from before CF-0087 and a run with no
    `--channel` both look like. The choice between `ending_seconds` and
    `end_card_seconds` is the validator's (CF-0141); `TAIL_KEYS_WITHOUT_ROOT`
    stands in only when the validator is out of reach.
    """
    budget = budget or {}
    vp = validator()
    keys = getattr(vp, "NARRATION_TAIL_KEYS", TAIL_KEYS_WITHOUT_ROOT)
    for key in keys:
        value = budget.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value), key
    return 0.0, None


def total_seconds(voice_seconds, budget=None):
    """The finished video: the voice plus the channel's tail. Routed through
    the validator's `total_seconds_from_narration()` when it is reachable, so
    that this file cannot hold a second opinion on the same addition."""
    vp = validator()
    if vp is not None:
        try:
            return vp.total_seconds_from_narration(voice_seconds, budget or {})
        except Exception:  # noqa: BLE001 - a budget with no tail: below
            pass
    return round(float(voice_seconds) + tail_seconds(budget)[0], 3)


def narration_band(budget=None):
    """What the channel's finished-video band leaves for the voice track,
    `(low, high)`, or None when it cannot be derived here.

    This is what a plan's `duration.target` is, and CF-0158's whole point:
    `[total_seconds_min - tail, total_seconds_max - tail]`, so the floor
    follows the length of `ending.mp4` instead of standing at the literal 35
    that followed nothing.

    Three answers, in order:
      * the channel states its own band -> the validator's `narration_band()`;
      * it does not (a config from before CF-0158) -> the factory's own
        MIN/MAX_TARGET_SECONDS minus *this channel's* tail, same subtraction;
      * no validator at all -> None, and the caller says so rather than
        inventing a floor this repo has no number for.
    """
    vp = validator()
    if vp is None:
        return None
    budget = budget or {}
    try:
        return vp.narration_band(budget)
    except Exception:  # noqa: BLE001 - no band in this config; fall through
        pass
    tail = tail_seconds(budget)[0]
    lo = round(vp.MIN_TARGET_SECONDS - tail, 3)
    hi = round(vp.MAX_TARGET_SECONDS - tail, 3)
    return (lo, hi) if 0 < lo < hi else None


def video_length(voice_seconds, budget=None):
    """CF-0158's verdict on the *finished video's* length - voice + tail
    against the channel's 45-60s band - as `judge_video_length()` returns it
    (`verdict` in {in_band, short, over}, `action` in {pass, warn, refuse}).

    None when the channel states no band or the validator is out of reach.
    Over the ceiling is already a refusal one line up (that is CF-0087's
    gate); what this adds is the end that had nothing at all before it - a
    video coming out under 45s is now named, in the plan and on stderr,
    without stopping the pipeline. The asymmetry is the task's decision, not
    an oversight: see VIDEO_LENGTH_ACTIONS in the validator.
    """
    vp = validator()
    if vp is None or not budget:
        return None
    try:
        return vp.judge_video_length(vp.total_seconds_from_narration(voice_seconds, budget),
                                     budget)
    except Exception:  # noqa: BLE001 - a config with no band of its own
        return None


def script_estimate(script):
    """The estimate Content Researcher wrote, whichever shape it used.

    `narration.estimated_seconds` is the CF-0087 shape (whole narrative,
    hook+commentary+payoff, at the measured rate). Older scripts carry only
    `estimated_spoken_duration_seconds`, which undercounted (the bug that
    became CF-0087) but is still the number the researcher believed; it is
    reported under a different label so the two are never confused. None when
    the script says nothing.
    """
    if not isinstance(script, dict):
        return None, None
    narration = script.get("narration")
    if isinstance(narration, dict) and narration.get("estimated_seconds") is not None:
        return float(narration["estimated_seconds"]), "narration.estimated_seconds"
    legacy = script.get("estimated_spoken_duration_seconds")
    if legacy is not None:
        return float(legacy), "estimated_spoken_duration_seconds"
    return None, None


def find_script(scripts_json, script_id):
    """One script out of 03-content-researcher.json by `script_id`."""
    data = json.load(open(scripts_json))
    scripts = data.get("scripts", []) if isinstance(data, dict) else data
    for s in scripts:
        if s.get("script_id") == script_id or s.get("id") == script_id:
            return s
    return None


def judge(voice_seconds, budget=None, estimated_seconds=None,
          ceiling=HARD_CEILING_SECONDS):
    """The verdict on one voice-over.

    `voice_seconds` is the measured wav length (lead silence included - it is
    in the video). `budget` is the channel's `narration_budget` or None.
    Returns a record with `verdict` in {"ok", "warn", "reject"}:

      reject  total (voice + the channel's tail) is over `ceiling`
      warn    total is over the budget's `target_total_seconds`
      ok      otherwise, including when there is no budget at all

    CF-0158: the tail is `tail_seconds()` - the channel's ending clip when it
    has one, the drawn card otherwise - and not `end_card_seconds` unread.
    The record says which key it used (`tail_key`), so a total can always be
    traced back to the number it was built from. The tail is only added when
    the budget names one; nothing else in this record is invented when the
    config is missing.
    """
    budget = budget or {}
    tail, tail_name = tail_seconds(budget)
    target = budget.get("target_total_seconds")
    target = float(target) if target is not None else None
    total = total_seconds(voice_seconds, budget)

    if total > ceiling:
        verdict = "reject"
    elif target is not None and total > target:
        verdict = "warn"
    else:
        verdict = "ok"

    rec = {
        "voice_seconds": round(voice_seconds, 3),
        # CF-0158: replaces `end_card_seconds`, which named one of the two
        # possible tails and was read on channels that use the other.
        "tail_seconds": tail,
        "tail_key": tail_name,
        "total_seconds": total,
        "target_total_seconds": target,
        "ceiling_seconds": float(ceiling),
        "over_target_by": (round(total - target, 3)
                           if target is not None and total > target else 0.0),
        "over_ceiling_by": round(total - ceiling, 3) if total > ceiling else 0.0,
        "estimated_seconds": (round(estimated_seconds, 3)
                              if estimated_seconds is not None else None),
        "delta_vs_estimate": (round(voice_seconds - estimated_seconds, 3)
                              if estimated_seconds is not None else None),
        "verdict": verdict,
        # CF-0158: the same length judged against the channel's editorial
        # band instead of against the target and the ceiling - this is the
        # end that catches a video coming out SHORT, which nothing did
        # before. None when the channel states no band (see video_length()).
        "video_length": video_length(voice_seconds, budget),
    }
    if budget.get("words_per_second_source"):
        rec["rate_source"] = budget["words_per_second_source"]
    return rec


def report_lines(rec):
    """What to say on stderr, one line per finding. Empty on a clean run."""
    lines = []
    # CF-0158: name the tail that was actually counted - "ending clip" reads
    # differently from "end card", and the two are different lengths.
    tail_label = ("ending clip" if rec.get("tail_key") == "ending_seconds"
                  else "end card")
    card = (f" + {rec['tail_seconds']:.2f}s {tail_label}"
            if rec["tail_seconds"] else "")
    if rec["verdict"] == "reject":
        lines.append(
            f"NARRATION OVER CEILING - {rec['voice_seconds']:.2f}s voice{card} = "
            f"{rec['total_seconds']:.2f}s, ceiling {rec['ceiling_seconds']:.0f}s "
            f"(+{rec['over_ceiling_by']:.1f}s): the script has to lose words, "
            f"not the video (CF-0087)")
    elif rec["verdict"] == "warn":
        lines.append(
            f"NARRATION OVER TARGET: {rec['voice_seconds']:.2f}s voice{card} = "
            f"{rec['total_seconds']:.2f}s vs target "
            f"{rec['target_total_seconds']:.0f}s (+{rec['over_target_by']:.1f}s), "
            f"under the {rec['ceiling_seconds']:.0f}s ceiling")
    # CF-0158: the band, once the channel states one. `short` is the case
    # that had no line anywhere before this task - a 42s video went out
    # unremarked. It stays a warning on purpose (VIDEO_LENGTH_ACTIONS): the
    # fix is more substance, and no step of this pipeline can add that.
    #
    # CF-0293: `too_short` is the fourth verdict - a finished video under the
    # channel's 30s hard floor - and it is UNDER the band like `short`, not
    # over it. Before this branch existed it fell through to the `elif` and a
    # 25s video was announced as "VIDEO OVER THE BAND", which is the one
    # sentence that would send an operator looking in the opposite direction.
    # The refusal headline itself (VIDEO_TOO_SHORT_HEADLINE) is printed by the
    # gate, not here: this list is what stderr says about a record, and
    # `plan_refusal.reason_text()` puts the headline in front of it.
    band = rec.get("video_length")
    if band and band["action"] != "pass":
        if band["verdict"] in VIDEO_UNDER_VERDICTS:
            lines.append(f"VIDEO UNDER THE BAND - {band['reason']}")
        elif rec["verdict"] != "reject":
            lines.append(f"VIDEO OVER THE BAND - {band['reason']}")
    if rec["delta_vs_estimate"] is not None:
        lines.append(
            f"NARRATION ESTIMATE: script estimated {rec['estimated_seconds']:.1f}s, "
            f"voice is {rec['voice_seconds']:.2f}s "
            f"({rec['delta_vs_estimate']:+.1f}s"
            + (f"; rate from {rec['rate_source']}" if rec.get("rate_source") else "")
            + ")")
    return lines


def refusal_numbers(rec):
    """CF-0282: what the ceiling refused on, as numbers rather than prose.

    CF-0293: when the record carries a band verdict, its numbers ride along -
    the floor gate refuses on exactly those (`hard_min`, the band, how far
    under), and a ceiling refusal is no worse for carrying the band it was
    also outside of. Absent on a run with no channel band, like every other
    key here.
    """
    keys = ("voice_seconds", "tail_seconds", "tail_key", "total_seconds",
            "ceiling_seconds", "over_ceiling_by", "target_total_seconds",
            "over_target_by", "estimated_seconds", "delta_vs_estimate")
    numbers = {k: rec.get(k) for k in keys if rec.get(k) is not None}
    band = rec.get("video_length")
    if isinstance(band, dict):
        for src, dst in (("verdict", "video_length_verdict"),
                         ("hard_min", "hard_min_seconds"),
                         ("band", "video_band"),
                         ("deviation", "video_band_deviation")):
            if band.get(src) is not None:
                numbers[dst] = band[src]
    return numbers


def record_refusal(rec, voice, script_id, gate=plan_refusal.GATE_NARRATION_CEILING,
                   headline="NARRATION OVER CEILING"):
    """The refusal sidecar beside the voice.wav it measured (CF-0282).

    `build_render_plan.py` has recorded this refusal since CF-0254 - but only
    when the plan builder is the one that meets it. Run the way the skill runs
    it, this gate fires *before* the plan: the voice is synthesised, measured
    here, found over the ceiling, and the plan is never built, so the record
    CF-0254 arranged never happened either. On
    `example-film/2026-09-18T1058Z` the Famine Trials script was refused at
    61.64 s and the batch's artifact said nothing; a later rescue pass wrote
    the `narration_ceiling` / `held_back` entry by hand through
    `plan_refusal`. This writes the same entry from the gate that made the
    decision, under the same gate id, so a hand-written record is never the
    only one.

    Needs `--script-id`: a `refusals[]` record is keyed on it and a record
    nobody can attach to a script is not a record. Without one the run says so
    and writes nothing.

    CF-0293: `gate` and `headline` are arguments because this stage now has a
    second length refusal - the hard floor under the band - and it is owed the
    same record by the same route. They default to the ceiling's pair so that
    CF-0282's caller and every test of it read exactly as before; the floor
    passes `GATE_NARRATION_FLOOR` / `VIDEO_TOO_SHORT_HEADLINE`, and the funnel
    code follows from the gate through `plan_refusal.GATE_CODES` rather than
    being chosen here.
    """
    if not script_id:
        print("  REFUSAL NOT RECORDED: pass --script <03-content-researcher.json> "
              "--script-id <id> so the refusal reaches 05-video-editor.json -> "
              "refusals[] (CF-0282); a record with no script_id cannot be "
              "attached to anything", file=sys.stderr)
        return None
    reason = plan_refusal.reason_text(headline, report_lines(rec))
    path = plan_refusal.write(voice, script_id, gate, reason,
                              numbers=refusal_numbers(rec))
    print(f"  REFUSAL RECORDED [{plan_refusal.code_for(gate)}"
          f"/{gate}] {path} - run "
          f"write_batch_metadata.py <batch> so it reaches 05-video-editor.json "
          f"-> refusals[]", file=sys.stderr)
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("voice", help="the synthesized voice.wav")
    p.add_argument("--channel", default=None,
                   help="channel whose channels/<channel>.json#narration_budget "
                        "supplies the target, the tail the video ends on and "
                        "(CF-0158) the 45-60s band (a path to that .json is "
                        "accepted too)")
    p.add_argument("--script", default=None,
                   help="03-content-researcher.json, to compare the actual "
                        "length with the estimate the script carries")
    p.add_argument("--script-id", default=None)
    p.add_argument("--ceiling", type=float, default=HARD_CEILING_SECONDS,
                   help="hard ceiling on voice + the channel's tail; over it "
                        "the voice-over is rejected (default %(default)ss)")
    p.add_argument("--json", action="store_true",
                   help="print the verdict record as JSON on stdout")
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.voice))  # CF-0107: slug from work/<slug>/voice.wav

    budget = load_narration_budget(args.channel)
    if args.channel and budget is None:
        print(f"  NOTE: no narration_budget for channel {args.channel!r} under "
              f"{CHANNELS_DIR} - gating on the {args.ceiling:.0f}s ceiling alone",
              file=sys.stderr)

    estimate = None
    if args.script:
        if not args.script_id:
            p.error("--script needs --script-id")
        script = find_script(args.script, args.script_id)
        if script is None:
            print(f"  NOTE: script {args.script_id!r} not in {args.script} - "
                  f"no estimate to compare", file=sys.stderr)
        else:
            estimate, _ = script_estimate(script)

    rec = judge(audio_duration(args.voice), budget, estimate, args.ceiling)
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        tail_label = (rec["tail_key"] or "no tail in the config").replace("_", " ")
        band_word = (rec.get("video_length") or {}).get("verdict")
        # CF-0293: the record's own `verdict` is about the ceiling and the
        # target, and it says "ok" about a video this run is refusing for
        # being too short. The band's verdict is printed beside it so the
        # summary line and the exit code never disagree.
        band_word = f"/{band_word}" if band_word == VIDEO_TOO_SHORT_VERDICT else ""
        print(f"{rec['voice_seconds']:.2f}s voice, {rec['total_seconds']:.2f}s "
              f"with the tail ({tail_label}) - {rec['verdict']}{band_word}")
    for line in report_lines(rec):
        print(f"  {line}", file=sys.stderr)
    if rec["verdict"] == "reject":
        # CF-0282: the record, before the exit. This gate stops the script
        # before a plan exists, so nothing downstream will write it for us.
        record_refusal(rec, args.voice, args.script_id)
        sys.exit(REJECT_EXIT_CODE)
    # CF-0293: the other end of the same measurement. The ceiling above is on
    # the voice-over the script wrote too much of; this one is on the finished
    # video being under the channel's hard floor, and it is a refusal by the
    # user's decision of 2026-09-20 - the plan is not built, nothing is
    # rendered, and the funnel gets `video_too_short` instead of a batch that
    # quietly shipped a 25s short. 30-45 s does not come through here: it is
    # `short`, it printed its line above, and the video is made.
    band = rec.get("video_length")
    if band and band.get("verdict") == VIDEO_TOO_SHORT_VERDICT:
        print(f"  {VIDEO_TOO_SHORT_HEADLINE} - the video is not built "
              f"(CF-0293); the script has to carry more, which no step after "
              f"this one can add", file=sys.stderr)
        record_refusal(rec, args.voice, args.script_id,
                       gate=plan_refusal.GATE_NARRATION_FLOOR,
                       headline=VIDEO_TOO_SHORT_HEADLINE)
        sys.exit(REJECT_EXIT_CODE)
    sys.exit(0)


@video_script("video-editor", "narration", name="narration_length.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
"""CF-0254: why the Editor refused a script it never rendered.

Every gate in `build_render_plan.py` that refuses a *whole* plan used to end
the same way: a headline on stderr, a deficit file for the gates that have
one, and exit 2. Nothing survived into the batch's own artifact. The stage's
convention said so out loud - "a refused video has no plan and therefore no
entry in 05-video-editor.json at all" - so `write_batch_metadata.py`, which
needs an existing `plan.json` and an `.mp4`, was never even called for a batch
whose only script was refused, and `05-video-editor.json` did not exist.

What that costs is visible from the root: the funnel (`shared/runlog/funnel.py`
in the factory root) reads this stage's artifact and, finding neither a video
nor a refusal for a cleared script, reports the loss as `unexplained` / SILENT
- the one outcome DoD 1.4.4 item 1 forbids. Batch
`example-film/2026-09-16T2148Z` is the case: one script, refused at the source
badge gate (CF-0166), `unexplained 1, SILENT 1`. The refusal was in RUN_EVENTS
and in the operator's `stage-done --note`, and the funnel reads artifacts, not
events.

So the convention is now the other one: **a refused video has an entry in
`refusals[]` and no entry in `videos[]`**. This module owns that entry.

The shape is the root's, not ours - `funnel._recorded()` reads three keys:

    {"script_id": ..., "reason_code": ..., "reason": ...}

`reason_code` must be one of `funnel.FUNNEL_CODES`; a code the root does not
know is printed by the funnel as "a contract to fix". `reason` is the gate's
own sentence, self-contained: it has to read on its own in a table of losses,
without the batch's stderr beside it. Two keys of our own ride along -
`gate` (which gate, by id, since several gates share one funnel code) and `at`
- and the funnel ignores what it does not read.

How a refusal travels from the gate to the artifact: the gate writes a sidecar
beside where the plan would have been (`<output stem>.refusal.json`, the same
move as CF-0118's `plan.two-source-gate.json` and CF-0139's
`plan.assetless-rung.json`), because at that moment there is no plan to carry
anything and the process is about to exit. `write_batch_metadata.py` then
collects every sidecar under `<batch>/work/*/` - no operator has to remember a
flag - and merges them into `refusals[]`.

**A video wins over a refusal for the same `script_id`.** A rejected asset
refuses the plan on an attempt that the caller then retries with another
candidate (SKILL.md's degradation ladder); when a later attempt renders, the
video record is the truth and the stale refusal is dropped at merge.

**Except when the refusal is what rejected that mp4** (CF-0270). The sentence
above used to end "the reverse never happens: a gate cannot refuse a script
that already has an mp4 in this batch", and the pattern ceiling gate is the
case that makes it false. Post-QC degradation reaches the Editor as
`--degrade-block` on a *rebuild* of the plan: an attempt has already been
spent, its mp4 is on disk, and the rebuild is the answer to that mp4 having
failed QC. When the rebuild is refused, the mp4 beside it is the render the
refusal is about - not a later attempt that succeeded - and letting it win
would publish exactly the video the gate refused. Such a refusal carries
`supersedes_video: true`; `superseded_video_ids()` names those scripts and the
caller drops their video records *before* the merge, so `merge()` keeps its one
rule ("a video wins") and the exception lives in one place with a name.

**A gate that refuses *before* the render is in this table too (CF-0282).**
Until then only `build_render_plan.py` wrote refusals, and the two gates that
stop a script earlier - the anchor preflight (`script_anchors.py preflight`,
CF-0140, before the TTS) and the narration ceiling measured on the finished
`voice.wav` (`narration_length.py`, CF-0087, before the plan) - ended in exit 2
and a headline on stderr and nothing else. Batch
`example-film/2026-09-18T1058Z` is the case: `lf-2026-09-18-003-script1`
(Pine Park) was refused by the preflight with 23 anchors against 7 distinct
usable samples, and the funnel printed `not_built` - "the Editor neither
rendered nor refused it" - about a script the Editor refused out loud. The
earlier a stage refuses, the *more* it has saved and the less there is on disk
to infer it from, so a pre-render gate needs the sidecar more than a plan gate
does, not less. Both now write one through this module, and because the
sidecar lands under `<batch>/work/<slug>/`, `collect()` finds it with no flag
and `write_batch_metadata.py` carries it into `refusals[]` for a script that
produced no plan at all.

The gate table below maps each refusing gate to the funnel code it writes:

    gate id            funnel code               the gate
    anchor_preflight   pool_too_thin             ANCHORS NOT COVERED (CF-0140/CF-0282)
    unresolved_anchor  pool_too_thin             UNDER-FLOOR PICTURE (CF-0290)
    narration_ceiling  held_back                 NARRATION OVER CEILING (CF-0087)
    narration_floor    video_too_short           VIDEO UNDER THE HARD FLOOR (CF-0293)
    assets_rejected    pool_too_thin             ASSETS REJECTED
    assetless_rung     pattern_undeliverable     ASSETLESS BLOCKS (CF-0137/CF-0138)
    pattern_ceiling    pattern_undeliverable     PATTERN CEILING BROKEN (CF-0270)
    two_source_gate    no_second_source          TWO-SOURCE GATE FAILED (CF-0118)
    blooper_borders    held_back                 BLOOPER BORDERS (CF-0190)
    proof_beat         held_back                 PROOF REQUEST POINTS AT NOTHING (CF-0243)
    source_badge       held_back                 SOURCE BADGE NOT PLANNED (CF-0164/CF-0166)
    end_card           held_back                 END CARD NOT PLANNED (CF-0063/CF-0117)
    score_below_threshold score_below_threshold  SCORE UNDER THE THRESHOLD (CF-0434)
    still_share_over_half score_below_threshold  PICTURES OVER THE STILL SHARE (CF-0418)
    proof_quote_cap    held_back                 PROOF-QUOTE CAP BROKEN (CF-0567)
    demo_own_capture   pattern_undeliverable     DEMO WITHOUT ITS OWN RECORDING (CF-0567)
    own_graphic        held_back                 OWN GRAPHIC REFUSED (CF-0689)

`proof_quote_cap` and `demo_own_capture` (CF-0567, `proof_quote_cap.py`): a
vendor's official clip (`official_channels[].role: proof_quote`) over the
channel's `proof_quotes` caps - one quote longer than `max_seconds_per_quote`,
more than `max_quotes_per_video`, more than `max_seconds_per_video` in all, or
quotes that are most of the footage (`never_the_base`); and a plan of the
`demo` pattern whose own recording is not most of its footage. Which cap it
was is in the reason (`[quote_too_long]`, `[too_many_quotes]`,
`[quotes_over_video_total]`, `[quote_is_the_base]`, `[demo_not_own_capture]`).

`still_share_over_half` (CF-0418) is a point of the score model's hard list:
more than the channel's `video_editor.max_still_share` (0.5) of the running
time in pictures - cards, posters, proof cards, whole-frame memes; a frame held
from a video does not count (the user, 2026-09-30). The hard list makes the
tier F, and F is under N, so it takes the score model's code; the gate id says
which point of the list it was. Written by `build_render_plan.py` before the
render, with `plan.still-share.json` beside it (`still_share.py`).

`score_below_threshold` (CF-0434) is the early stop of the score model: the
real penalties recorded so far (score_log.py) put the video under N after the
render or QC, and it goes no further. Written by `score_log.check()` as
`<plan stem>.score.refusal.json`, always with `supersedes_video` (the mp4 on
disk is the render it refuses) and with `score` / `score_line` riding along.
It has a code of its own, `score_below_threshold`: the root added it to
`funnel.FUNNEL_CODES` for exactly this stop (CF-0434), and the funnel still
reads an older record's `held_back` + `gate: score_below_threshold` as it.

`unresolved_anchor` (CF-0290) takes `pool_too_thin` for the same reason and
about the same fact one stage later: the storyboard says out loud, in
`unresolved_anchors`, that a block's picture scores under the similarity floor
- nothing in the pool depicts that phrase and a frame of something else went
on screen under it (`example-film/2026-09-18T2232Z`, delver.mp4, two blocks).
`resolve_anchors.screen_pool()` makes that unreachable from this repo's own
resolver; this gate is what stops such a storyboard from being rendered
anyway - one built before the screen existed, or by a caller that skipped it -
and it is the DoD ролика item 3 rule stated where the plan is written:
an unresolved anchor means the phrase is dropped or the video goes to
needs-you, never a random frame.

`narration_floor` (CF-0293) is the one gate here with a code of its own rather
than a share of `held_back`: the root added `video_too_short` to `FUNNEL_CODES`
for exactly this refusal, because a video refused for coming out under 30 s is
not the stage's judgement about a topic - it is a measured length, and a
channel reading a run of these knows to look at the scripts' word counts and
not at the Editor. The 45 s floor of the band is NOT this gate: 30-45 s stays
a warning and a made video (CF-0158, and the user again on 2026-09-20), and it
reaches the run summary through `videos[].duration.narration.video_length`,
never through `refusals[]`.

`anchor_preflight` takes `pool_too_thin` - "fewer usable samples in the pool
than the pattern's anchors" - because that is the preflight's finding said in
the root's words, whichever of its three causes fired: `sample_contention`
(more anchors than distinct samples, the Pine Park case), `absent_anchors`
(nothing in the pool matches the phrase at all) and `weak_anchors` (what
matches is under the usability floor) are all "the pool has fewer usable
samples than this script asks pictures for". Which one it was is in the
record's `refused_because`, and the counts are in `numbers`, so nothing about
the refusal has to be reconstructed from the code alone. The gate deliberately
does *not* take `held_back`: `pool_too_thin` names the pool, and a channel
reading a run of these knows to widen the footage rather than to look at the
Editor.

Five of the gates share `held_back` ("the stage held the topic back by its own
judgement") because the root's vocabulary has nothing narrower for them and
this repo does not get to widen it - `FUNNEL_CODES` lives in the factory root
and a stage that writes a code the root has never heard of has broken the
contract rather than used it. `held_back` is true of all five, `gate` says
which one, and `reason` carries the gate's sentence. If the root adds a
narrower code, only `GATE_CODES` here changes - as it did for
`score_below_threshold` (CF-0434), which started as a sixth `held_back`.

    plan_refusal.write(output, script_id, gate, reason)   the sidecar
    plan_refusal.entry(script_id, gate, reason)           just the record
    plan_refusal.collect(batch_dir)                       every sidecar of a batch
    plan_refusal.merge(existing, written, videos)         union by script_id

**Three gates warn instead of refusing (CF-0330, the user 2026-09-23).** On
2026-09-23 two videos the user had accepted for publication were rebuilt on the
current code and both were refused before the render: `everyday-sorcery-2` by
`anchor_preflight` (one anchor with no survivor, best candidate 0.2198 against a
floor of 0.22) and `widows-bay` by `assetless_rung` (3 of 24 blocks with no
picture). `two_source_gate` had been priced by CF-0320 at 2 of 5 ready videos.
The user's answer, in chat: none of the three prices is signed - all three go
back to a warning. `WARN_GATES` below is that decision. `two_source_gate`
warns through its own `measure` mode, which the channel switches (see
`WARN_GATES`). A warned gate writes the *same* record a refusal would - gate id, funnel code, the sentence and the
numbers - with `severity: "warn"`, and the run goes on:

    plan_refusal.warning(script_id, gate, reason, numbers)   the record
    plan_refusal.write_warning(output, ...)                   `<stem>.warning.json`
    plan_refusal.collect_warnings(work_dir)                   every one of a video

A warning sidecar is never a refusal: `collect()` reads `*.refusal.json` only,
so a warned script is never listed in `refusals[]`, and its warnings ride the
plan (`plan["warnings"]`) into `videos[].warnings` instead. The gate code
stays in the table above because the same gate may be switched back to a
refusal by the next decision, and the code is what the funnel joins on either
way.

Stdlib only, like the rest of scripts/.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

FIELD = "refusals"
SUFFIX = ".refusal.json"

# The loss codes of shared/runlog/funnel.py FUNNEL_CODES this stage can
# honestly write. Spelled here rather than imported: scripts/ is stdlib-only
# and does not reach into the factory root at import time. tests/
# test_plan_refusal.py checks them against the root's tuple when the root is
# reachable, so a divergence is a failing test and not a silent drift.
HELD_BACK = "held_back"
POOL_TOO_THIN = "pool_too_thin"
PATTERN_UNDELIVERABLE = "pattern_undeliverable"
NO_SECOND_SOURCE = "no_second_source"
# CF-0293: the finished video came out under the channel's hard floor (30 s on
# example-film). In FUNNEL_CODES since CF-0293, as
# validate_patterns.VIDEO_LENGTH_REFUSAL_CODE.
VIDEO_TOO_SHORT = "video_too_short"
# CF-0356: the script never passed the Researcher's text gates (the cadence
# gate's own funnel code, `check_anchor_cadence.SKIP_REASON_CODE`) - the
# Editor ran the gate itself before the TTS and it did not pass.
THIN_SCENE = "thin_scene"
# CF-0434: the real penalties recorded so far put the video under the score
# threshold N (score_log.check()). In FUNNEL_CODES since CF-0434; the funnel
# reads the older `held_back` + `gate: score_below_threshold` as this code.
SCORE_BELOW_THRESHOLD = "score_below_threshold"

GATE_ANCHOR_PREFLIGHT = "anchor_preflight"
GATE_UNRESOLVED_ANCHOR = "unresolved_anchor"
GATE_NARRATION_CEILING = "narration_ceiling"
GATE_NARRATION_FLOOR = "narration_floor"
GATE_ASSETS_REJECTED = "assets_rejected"
GATE_ASSETLESS_RUNG = "assetless_rung"
GATE_PATTERN_CEILING = "pattern_ceiling"
GATE_TWO_SOURCE = "two_source_gate"
GATE_BLOOPER = "blooper_borders"
GATE_PROOF_BEAT = "proof_beat"
GATE_SOURCE_BADGE = "source_badge"
GATE_END_CARD = "end_card"
GATE_TEXT_GATES = "text_gates"
GATE_SCORE = "score_below_threshold"
GATE_STILL_SHARE = "still_share_over_half"  # CF-0418
GATE_PROOF_QUOTE_CAP = "proof_quote_cap"     # CF-0567
GATE_DEMO_OWN_CAPTURE = "demo_own_capture"   # CF-0567
# CF-0689: a graphic the factory would draw whose order does not hold
# (shared/own_graphic.py order_errors / adds_text), or a graphic anchor that
# names no graphic of the script's `graphics[]`.
GATE_OWN_GRAPHIC = "own_graphic"
# CF-0480: one-frame blocks the pool had no second shot for leave the video
# over the stretched line - a warning until the user signs its price (CF-0320).
GATE_POOL_HOLDS_VIDEO = "pool_holds_video"

GATE_CODES = {
    GATE_ANCHOR_PREFLIGHT: POOL_TOO_THIN,
    GATE_UNRESOLVED_ANCHOR: POOL_TOO_THIN,
    GATE_NARRATION_CEILING: HELD_BACK,
    GATE_NARRATION_FLOOR: VIDEO_TOO_SHORT,
    GATE_ASSETS_REJECTED: POOL_TOO_THIN,
    GATE_ASSETLESS_RUNG: PATTERN_UNDELIVERABLE,
    GATE_PATTERN_CEILING: PATTERN_UNDELIVERABLE,
    GATE_TWO_SOURCE: NO_SECOND_SOURCE,
    GATE_BLOOPER: HELD_BACK,
    GATE_PROOF_BEAT: HELD_BACK,
    GATE_SOURCE_BADGE: HELD_BACK,
    GATE_END_CARD: HELD_BACK,
    GATE_TEXT_GATES: THIN_SCENE,
    GATE_SCORE: SCORE_BELOW_THRESHOLD,
    GATE_STILL_SHARE: SCORE_BELOW_THRESHOLD,
    GATE_POOL_HOLDS_VIDEO: POOL_TOO_THIN,
    GATE_PROOF_QUOTE_CAP: HELD_BACK,
    GATE_DEMO_OWN_CAPTURE: PATTERN_UNDELIVERABLE,
    GATE_OWN_GRAPHIC: HELD_BACK,
}


class UnknownGate(Exception):
    """A gate id with no funnel code. A programming error, never a run's."""


def code_for(gate):
    try:
        return GATE_CODES[gate]
    except KeyError:
        raise UnknownGate(
            f"{gate!r} is not in plan_refusal.GATE_CODES - a gate that refuses "
            f"a plan has to name the funnel code its refusal carries") from None


def reason_text(headline, lines=()):
    """The gate's sentence, self-contained.

    `headline` is the gate's stderr headline without the " - plan not written"
    tail (the tail says the same thing the record's existence does); `lines`
    are its detail lines. Joined with "; " so the whole reason is one cell of
    the funnel's table, and squeezed onto one line - a newline in this field
    breaks a Markdown row.
    """
    detail = [" ".join(str(line).split()) for line in lines]
    detail = [d for d in detail if d]
    head = " ".join(str(headline).split())
    return f"{head}: {'; '.join(detail)}" if detail else head


def entry(script_id, gate, reason, deficit=None, supersedes_video=False,
          numbers=None):
    """One `refusals[]` record. Three keys the root reads, three of ours."""
    rec = {
        "script_id": script_id,
        "reason_code": code_for(gate),
        "reason": reason,
        "gate": gate,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if deficit:
        # The gates that write one (two-source, assetless rung, proof beat)
        # already print its path; carrying it here means a reader of the
        # artifact can find the machine-readable half without the stderr.
        rec["deficit"] = str(deficit)
    if supersedes_video:
        # CF-0270, see the module docstring: this refusal was made on a
        # rebuild, so the mp4 of this script in this batch is the render it
        # refuses. Written only when true - an absent key is the ordinary
        # "there is no video here to argue with".
        rec["supersedes_video"] = True
    if numbers:
        # CF-0282: the measurement the gate refused on, as numbers rather than
        # as a sentence to be parsed back out of `reason`. The funnel ignores
        # the key; a human reading `05-video-editor.json` a week later gets
        # "23 anchors, 7 distinct samples, 16 without a picture, 2 sources"
        # without opening the stage's own report, and a query over a run of
        # batches can count them. `reason` keeps saying the same thing in
        # words - the two are written from one place in the gate, never
        # separately.
        rec["numbers"] = dict(numbers)
    return rec


def sidecar_path(output):
    p = Path(output)
    return p.with_name(f"{p.stem}{SUFFIX}")


def write(output, script_id, gate, reason, deficit=None, supersedes_video=False,
          numbers=None):
    """The refusal beside where the plan would have been. Returns the path, or
    a `<not written: ...>` string - a gate is refusing a plan and must not
    also fail on a full disk. Never raises for an I/O reason.

    CF-0282: for a gate that refuses before there is a plan, `output` is the
    artifact that gate *does* write in the video's work directory - the
    preflight's report, the voice.wav the ceiling measured - because what
    `collect()` needs is only that the sidecar sit under `<batch>/work/<slug>/`,
    and putting it beside the evidence keeps the pair findable by hand too.
    """
    path = sidecar_path(output)
    try:
        with open(path, "w") as fh:
            json.dump(entry(script_id, gate, reason, deficit=deficit,
                            supersedes_video=supersedes_video,
                            numbers=numbers), fh, indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)


def read(path):
    """One sidecar as a record, or None when it is not one of ours."""
    try:
        with open(path) as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or not rec.get("script_id") or not rec.get("reason_code"):
        return None
    return rec


def collect(batch_dir):
    """Every refusal sidecar under `<batch>/work/*/`, oldest first.

    Nothing has to be passed on a command line: a gate that refused wrote its
    sidecar where the plan would have been, and that is inside the batch. A
    directory with several (a video refused twice under two names) yields
    both; `merge()` keeps the last per script_id.
    """
    work = Path(batch_dir) / "work"
    if not work.is_dir():
        return []
    found = []
    for path in sorted(work.glob(f"*/*{SUFFIX}")):
        rec = read(path)
        if rec is not None:
            found.append(rec)
    found.sort(key=lambda r: (r.get("at") or ""))
    return found


def superseded_video_ids(refusals):
    """The scripts whose video record this batch's refusals reject (CF-0270).

    The caller drops these from `videos[]` before calling `merge()`. Kept as a
    function of its own rather than folded into `merge()` so that the merge
    rule stays the single sentence it has been since CF-0254 - a video wins -
    and the one exception is something a reader can find by name.
    """
    return {rec.get("script_id") for rec in refusals or []
            if isinstance(rec, dict) and rec.get("supersedes_video")
            and rec.get("script_id")}


def merge(existing, written, video_ids=()):
    """The union by `script_id`: (refusals, dropped_ids).

    `existing` is what an earlier write of 05-video-editor.json carried,
    `written` what this call found. This call's record replaces the existing
    one with the same id in place; new ids are appended. `video_ids` are the
    scripts this file now has a video for - their refusals are dropped and
    named in `dropped_ids`, because a script that rendered is not a script
    that was refused.
    """
    videos = set(video_ids)
    by_id, order = {}, []
    for rec in list(existing or []) + list(written or []):
        if not isinstance(rec, dict):
            continue
        sid = rec.get("script_id")
        if not sid:
            continue
        if sid not in by_id:
            order.append(sid)
        by_id[sid] = rec
    dropped = [sid for sid in order if sid in videos]
    return [by_id[sid] for sid in order if sid not in videos], dropped


# CF-0330: the gates the user returned to a warning on 2026-09-23 ("0330 -
# предупреждение, 0320 - предупреждение"). A gate in this set never exits the
# stage: it writes `warning()` where it would have written `entry()`.
#
# `two_source_gate` is the third gate of that decision and is deliberately not
# in this set: it already has a warn mode of its own (`measure`, CF-0118) and
# the mode is the *channel's* (`channels/<channel>.json` ->
# `video_editor.two_source_gate`, in the factory root). The decision reaches it
# by that switch going back to `measure`; this repo only makes a measured
# failure write the same `warning()` record the other two do. A code override
# of a channel that says `enforce` would make the channel file lie.
WARN_GATES = frozenset({GATE_ANCHOR_PREFLIGHT, GATE_ASSETLESS_RUNG})
WARN_SUFFIX = ".warning.json"
WARNINGS_FIELD = "warnings"
SEVERITY_WARN = "warn"
WARN_DECISION = "CF-0330: the user, 2026-09-23 - a warning, not a refusal"


def warns(gate):
    """Whether this gate warns instead of refusing (CF-0330)."""
    return gate in WARN_GATES


def warning(script_id, gate, reason, numbers=None, deficit=None):
    """One warning record: a refusal record's fields, `severity: warn`, and
    the decision it rests on. Same code and numbers the refusal would carry -
    only the consequence differs."""
    rec = entry(script_id, gate, reason, deficit=deficit, numbers=numbers)
    rec["severity"] = SEVERITY_WARN
    rec["decision"] = WARN_DECISION
    return rec


def warning_sidecar_path(output):
    p = Path(output)
    return p.with_name(f"{p.stem}{WARN_SUFFIX}")


def write_warning(output, script_id, gate, reason, numbers=None, deficit=None):
    """The warning beside the artifact the gate wrote. Returns the path, or a
    `<not written: ...>` string; never raises for an I/O reason."""
    path = warning_sidecar_path(output)
    try:
        with open(path, "w") as fh:
            json.dump(warning(script_id, gate, reason, numbers=numbers,
                              deficit=deficit), fh, indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)


def collect_warnings(work_dir):
    """Every warning sidecar in one video's work directory, oldest first."""
    d = Path(work_dir)
    if not d.is_dir():
        return []
    found = []
    for path in sorted(d.glob(f"*{WARN_SUFFIX}")):
        rec = read(path)
        if rec is not None and rec.get("severity") == SEVERITY_WARN:
            found.append(rec)
    found.sort(key=lambda r: (r.get("at") or ""))
    return found


def warning_line(rec):
    """The operator's one line for a warned gate."""
    return (f"WARNING (video goes on): {rec.get('script_id')} "
            f"[{rec.get('reason_code')}/{rec.get('gate')}] {rec.get('reason')}")


def report_line(rec):
    """The operator's one line for a refused script."""
    return (f"REFUSED (no video): {rec.get('script_id')} "
            f"[{rec.get('reason_code')}/{rec.get('gate')}] {rec.get('reason')}")

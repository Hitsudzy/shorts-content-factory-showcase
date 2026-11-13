#!/usr/bin/env python3
"""Render a plan through Remotion.

Assets are staged into a public directory of the render's own first: the
bundle is served over http, and Chrome refuses file:// references from an http
origin, so absolute paths in the plan would silently render as blank frames.

CF-0340: every call has its own job directory, `render/jobs/<slug>-<pid>-<hex>/`
(`public/` - the fonts and the staged `job/` files, handed to Remotion as
`--public-dir` - and `props.json` beside it). Until this task every render
wiped and refilled one shared `render/public/job/`, so a second render started
alongside the first deleted its assets and overwrote its props (`durationInFrames
NaN`, a 404 on an asset - batch 0705Z lost three attempts that way). A render
removes only its own directory, on success and on failure alike; directories
left behind by a killed process are swept at the next start once they are a
day old and their owner is no longer running.

Usage: render_video.py <plan.json> <output.mp4> [--concurrency N] [--gl angle]
                       [--audio mix.wav | --bare-voice]
                       [--summary | --verbose] [--reason <why>] [--cap N]

CF-0098: for a plan under <batch>/work/<slug>/ this is where an attempt
begins. Before Remotion runs, `attempts.begin()` is called on the video's
ledger; at the cap it refuses with exit 3 and the NEEDS-YOU line, and no
render happens - the ceiling is mechanical, not a sentence in SKILL.md. The
reason is read off the ledger and the plan (`first`, `degraded:<idx:to>`
when the plan carries a fresh CF-0031 degradation, the previous attempt's
failure, or `operator`) unless --reason says otherwise. Remotion's whole
output goes to <batch>/logs/<slug>-attempt-<n>.log; the terminal gets a
summary (--verbose for the old firehose). A failed render ends the attempt
as `render_failed`; a successful one stays open for qc_render.py to end.

CF-0305: a render the tool broke before the first frame - Remotion printed
no `Rendered N/M` with N >= 1, or the mix failed before it ran - ends as
`render_broken` instead: recorded with its error line, not counted against
the cap; the second in a row with the same (normalised) error is the
`NEEDS-YOU <slug>: render_broken - ...` stop, lifted by a change to the code
or the plan (attempts.py).

CF-0518: a `render_failed` right after a render failure with the same
(normalised) error is the `NEEDS-YOU <slug>: render_stuck_on_asset - ...`
stop - the video runs into the same asset; both renders count, the stop is
lifted the same way (attempts.py).

CF-0434: the score. A plan whose score log (`<plan stem>.score.json`) is
already under N is not rendered - exit 4 and the `SCORE F` line, before any
attempt begins. After a render the file's length and frame are recorded as the
log's `render` stage and the remainder is checked (score_log.py).

CF-0902: a plan whose script the batch's `04-compliance-checker.json` does
not clear (a `contribution_check` block - the claims gate's
`claim_unsupported` among them -, a `reject`, a `review` without its
publication hold) is not rendered - exit 5 and the `NOT CLEARED` line, before
any attempt begins (pending_scripts.render_refusal). A plan whose script `04`
has no row for renders as before.

CF-0423: the render plays the mix. Without --audio, a plan built for a
channel plays the mix recorded on it (`audio.bed.mix`), and when it has none
build_soundtrack.py is run here first - the mix is no longer a step the
operator can skip between the plan and the render.
"""
import argparse
import json
import os
import re
import shutil
import time
import uuid
import subprocess
import sys
from pathlib import Path

import attempts
import quiet
import score_log  # CF-0434: the video's score log and the early stop
import pending_scripts  # CF-0902: compliance's verdict, enforced before the attempt
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197

ROOT = Path(__file__).resolve().parent.parent

# CF-0434: the video's score log says it is already under N - not rendered.
EXIT_SCORE_F = 4
# CF-0902: the batch's 04 row does not clear the plan's script - not rendered.
EXIT_NOT_CLEARED = 5
RENDER = ROOT / "render"

# CF-0131: what Remotion is told to log. It used to be `error`, which meant a
# successful render wrote *nothing*: every attempt log under <batch>/logs/ read
# `lines=0`, and "why did this render take 29 minutes" could only be answered by
# booking a fresh measurement session, because the render that actually took 29
# minutes had left no record of where the time went. `info` is Remotion's own
# default and prints the stages - bundling, then rendered-frame progress, then
# encoding - which is exactly the decomposition that question needs. The log is
# a file on disk (CF-0098); only quiet.py's tail ever reaches a terminal, so a
# chattier child does not cost context. `verbose` is a line per frame and is
# left as a flag for tracing one block, not as the default.
REMOTION_LOG = "info"
PUBLIC = RENDER / "public"

# CF-0340: one job directory per render call, never a shared one. The staged
# files keep the `job/` prefix inside the job's own public dir, so the
# composition (staticFile(`job/...`)) is unchanged.
JOBS = RENDER / "jobs"
STAGED = "job"
# What the job's public dir carries from render/public besides the staged
# files - named, not globbed, so a directory another tool is filling or
# removing in render/public at that moment is never copied (or half-copied).
# test_render_job_dir.py fails when render/public gains a tracked entry that
# is not listed here.
SHARED_PUBLIC = ("fonts",)
# A job directory older than this whose owner is no longer running is left
# over from a crash and is swept at the next render's start. A render never
# runs this long - quiet.ceiling() kills one after 300 s + 8 s per second of
# composition.
JOB_STALE_SECONDS = 24 * 3600
LEGACY_JOB = PUBLIC / "job"   # the shared directory of every render before CF-0340
_JOB_NAME = re.compile(r"-(\d+)-[0-9a-f]{8}$")


def _alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def job_owner(job):
    """The pid in a job directory's name (`<slug>-<pid>-<hex>`), or None."""
    m = _JOB_NAME.search(Path(job).name)
    return int(m.group(1)) if m else None


def sweep_stale_jobs(jobs=None, now=None, max_age=JOB_STALE_SECONDS):
    """Remove job directories left behind by a render that crashed: older
    than `max_age` and whose owner pid is not running. A fresh directory, or
    one whose owner is alive, is someone's render in progress and is never
    touched. Returns the removed paths."""
    jobs = Path(jobs) if jobs is not None else JOBS
    now = time.time() if now is None else now
    removed = []
    candidates = list(jobs.iterdir()) if jobs.is_dir() else []
    if jobs == JOBS and LEGACY_JOB.is_dir():
        candidates.append(LEGACY_JOB)
    for d in candidates:
        try:
            if not d.is_dir() or now - d.stat().st_mtime <= max_age:
                continue
        except FileNotFoundError:
            continue
        if _alive(job_owner(d)):
            continue
        shutil.rmtree(d, ignore_errors=True)
        removed.append(d)
    return removed


def new_job(slug=None, jobs=None, public=None):
    """Create this call's own job directory and return it:
    `<jobs>/<slug>-<pid>-<hex>/public/{fonts,job}/`. The stale sweep runs
    first. Nothing in another render's directory is read or written."""
    jobs = Path(jobs) if jobs is not None else JOBS
    public = Path(public) if public is not None else PUBLIC
    sweep_stale_jobs(jobs)
    tag = re.sub(r"[^A-Za-z0-9._]+", "-", slug or "plan").strip("-")[:60] or "plan"
    job = jobs / f"{tag}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    (job / "public").mkdir(parents=True)
    for name in SHARED_PUBLIC:
        src = public / name
        if src.is_dir():
            shutil.copytree(src, job / "public" / name)
        elif src.exists():
            shutil.copy2(src, job / "public" / name)
    (job / "public" / STAGED).mkdir()
    return job


def job_public(job):
    """The directory Remotion is given as --public-dir."""
    return Path(job) / "public"

# CF-0052: Chrome's rasteriser, chosen per plan rather than globally.
#
# Remotion leaves --gl unset, so Chrome rasterises in software (SwiftShader);
# --gl=angle hands rasterisation to the GPU. CF-0052 introduced the flag for
# ProceduralBg's full-frame CSS blurs (3.4x on them then); CF-0130 baked those
# blurs into an offscreen canvas, and CF-0134 re-measured what the flag is
# worth now.
#
# Measured 2026-10-03 on a cold machine (CPU_Speed_Limit 100 throughout,
# work/cf0052-measure/measured.json, ABBA pairs in one session), software
# minus angle, seconds of render per second of output: procedural +0.53
# (18%), held picture +0.30 (17%), whole-video typographic +0.66 (20%),
# footage -0.09 (angle ~3% *slower*, inside the software runs' own spread).
# The real raygun-sneak-peek plan (34s footage + 36s procedural) rendered in
# 194s with the flag against 223s without.
#
# So the flag is chosen by what the plan is made of: the seconds of each block
# kind times that kind's measured saving, and --gl=angle when the sum is
# positive. Against footage alone that is a procedural share of about 15%
# (0.09 / (0.53 + 0.09)); a footage-only plan stays on the software
# rasteriser. Kinds that were not measured (card, meme, split, ...) count
# zero either way.
#
# --gl on the command line overrides this; --gl=default turns it off.
GL_FOR_PROCEDURAL = "angle"
GL_SAVING_S_PER_S = {"procedural": 0.527, "still": 0.304, "clip": -0.092}


def gl_saving(plan):
    """Seconds of render --gl=angle is expected to save on this plan's blocks
    (negative: it would cost). Typographic plans are not summed here - their
    background is ProceduralBg for the whole composition."""
    total = 0.0
    for block in plan.get("blocks") or []:
        kind = (block.get("asset") or {}).get("kind")
        try:
            seconds = max(0.0, float(block["end"]) - float(block["start"]))
        except (KeyError, TypeError, ValueError):
            seconds = 0.0
        total += seconds * GL_SAVING_S_PER_S.get(kind, 0.0)
    return total


def gl_for(plan):
    """The --gl value this plan wants, or None for Chrome's own default.

    `typographic` paints ProceduralBg for the whole composition (Video.jsx),
    which the flag makes ~20% cheaper at any length; any other plan gets it
    when gl_saving() says its blocks come out cheaper with it (CF-0134)."""
    if plan.get("style") == "typographic":
        return GL_FOR_PROCEDURAL
    if gl_saving(plan) > 0:
        return GL_FOR_PROCEDURAL
    return None


def gl_here(plan):
    """CF-0711: gl_for(plan) on a machine whose GPU the factory may use, None
    (Chrome's software rasteriser) where it may not - every Intel Mac by
    default (vision_compute.gpu_off(), FACTORY_GPU overrides). The Intel
    UHD 630 here hung under the factory's Vision work on 12.10 and under the
    Claude app's Chromium GPU process on 11.10; a ~20% faster procedural
    render is not worth a third way to take the laptop down. `--gl` on the
    command line still wins over both."""
    import vision_compute
    if vision_compute.gpu_off():
        return None
    return gl_for(plan)


def composition_seconds(plan):
    """How long the video this plan renders is, in seconds - the material the
    render's ceiling is derived from (CF-0135).

    `duration.composition` is the number Video.jsx turns into durationInFrames
    (CF-0117: the narration plus the end card), so it, not the voice-over's
    `actual`, is what Remotion has to draw. A plan written before CF-0117 has
    only `actual`; one that has neither answers 0.0, which quiet.ceiling()
    reads as "the caller cannot say" and gives the base ceiling alone."""
    duration = plan.get("duration") or {}
    for key in ("composition", "actual"):
        try:
            seconds = float(duration.get(key))
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return 0.0


# CF-0423: the file the mix lands in, beside the plan - the name the
# hand-run mixes of widows-bay and outrider already used.
MIX_NAME = "mix.wav"


# CF-0305: Remotion's progress line (`--log=info`) - `Rendered 0/1630` is
# printed before any frame, so a drawn frame is N >= 1.
RENDERED_RE = re.compile(r"^\s*Rendered (\d+)/(\d+)")
# The line a failure names itself in: `Error: ...`, `... compositor Error: ...`,
# a node `ERR_...` code, a shell's `...: error: ...`.
ERROR_RE = re.compile(r"(\bError\b|\bERR_[A-Z_]+|\berror:|command not found)")


class RemotionWatch:
    """CF-0305: what render_video.py needs from Remotion's output beyond
    the tail - how many frames were drawn and the first error line - read
    line by line as quiet.run_logged() writes the log."""

    def __init__(self):
        self.frames = 0
        self.error = None

    def __call__(self, line):
        m = RENDERED_RE.match(line)
        if m:
            self.frames = max(self.frames, int(m.group(1)))
        elif self.error is None and ERROR_RE.search(line) and not line.lstrip().startswith("at "):
            self.error = line.strip()

    def failure_line(self, tail):
        """The error line, or the last non-empty line of the tail."""
        if self.error:
            return self.error
        return next((t.strip() for t in reversed(tail or []) if t.strip()), "")


# The mix builder ensure_mix() runs as a child (CF-0423); a name, so a test
# stand can put a stand-in in its place.
SOUNDTRACK_SCRIPT = Path(__file__).resolve().parent / "build_soundtrack.py"


class MixFailed(Exception):
    """build_soundtrack.py did not produce the mix this render needs."""


def channel_for_mix(plan):
    """(channel, root) the plan was built for - what build_soundtrack.py is
    told with --channel/--root - or (None, None) when the plan does not say.

    `audio.channel` is what build_render_plan.py was given with --channel
    (CF-0423, written from then on). A plan built before that still names
    its channel in the bed the rotation chose (CF-0271): the chosen file is
    `<root>/channels/<id>/beds/<file>`, which gives the factory root as well
    - the root the plan itself was built against, not whichever one this
    process would default to."""
    audio = plan.get("audio") or {}
    channel, root = resolve_channel(audio.get("channel")), None
    chosen = (audio.get("bed_rotation") or {}).get("chosen")
    if chosen:
        parts = Path(chosen).parts
        if "channels" in parts:
            i = len(parts) - 1 - parts[::-1].index("channels")
            if i + 1 < len(parts):
                root = str(Path(*parts[:i]))
                channel = channel or resolve_channel(parts[i + 1])
    return channel, root


def recorded_mix(plan):
    """The mix build_soundtrack.py recorded on this plan (`audio.bed.mix`),
    when it is still on disk. A rebuilt plan carries no `audio.bed` - the
    planner writes `audio` fresh - so a recorded mix is always the mix of
    this plan, never of the one before it."""
    mix = ((plan.get("audio") or {}).get("bed") or {}).get("mix")
    return mix if mix and Path(mix).exists() else None


def ensure_mix(plan_path, plan, summary=True):
    """CF-0423: the mix this render plays, built here when the plan has none.

    Until this task the mix was a separate step the operator had to remember
    between `build_render_plan.py` and this script, named only in SKILL.md's
    notes and never in its numbered procedure - and without `--audio` this
    script rendered the bare voiceover. From `example-film/2026-09-23T1722Z`
    on it was forgotten on every video of every batch and rebuild but one
    (kaijura-minus-zero in 2026-09-27T1757Z), and the lofi bed the plan chose
    (`audio.bed_rotation`) never reached a single mp4: the pauses between
    phrases were digital silence, and qc_render.py passed them, because a
    plan with no `audio.bed` was "not claiming a bed".

    So a plan built for a channel is never rendered from its bare voice: the
    recorded mix when there is one, otherwise build_soundtrack.py runs now,
    against this plan and the channel it was built for, and writes
    `audio.bed` back onto it the way it always has. A plan with no channel at
    all (a fixture, a hand-made plan) is left as it was - there is nothing to
    ask which bed it wants. Returns (mix path or None, report lines)."""
    mix = recorded_mix(plan)
    if mix:
        return mix, [f"mix: {mix} (recorded on the plan as audio.bed.mix)"]
    channel, root = channel_for_mix(plan)
    if not channel:
        return None, []
    voice = (plan.get("audio") or {}).get("src")
    if not voice or not Path(voice).exists():
        raise MixFailed(f"the plan's voice {voice!r} is not on disk - nothing to mix")
    out = Path(plan_path).resolve().parent / MIX_NAME
    cmd = [sys.executable, str(SOUNDTRACK_SCRIPT),
           str(voice), str(plan_path), str(out), "--channel", str(channel),
           *(["--root", root] if root else []),
           "--summary" if summary else "--verbose"]
    import common  # the ceiling helper; imported late, the module is heavy
    # CF-0905: a live child in its own session - a stop of this render
    # (quiet.stop_on_signals() in cli()) kills it with its ffmpeg, instead of
    # leaving it to write mix.wav and audio.bed under the next render and die
    # on a print into the pipe nobody reads (example-tech/2026-10-31T0840Z).
    proc = quiet.spawn(cmd, own_session=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    try:
        try:
            stdout, stderr = proc.communicate(
                timeout=common.media_timeout(composition_seconds(plan) or 60.0))
        except subprocess.TimeoutExpired:
            quiet.kill_child(proc, True)
            proc.communicate()
            raise MixFailed("build_soundtrack.py did not finish under its ceiling")
    finally:
        quiet.forget(proc)
    said = [l for l in ((stdout or "") + (stderr or "")).splitlines() if l.strip()]
    if proc.returncode != 0 or not out.exists():
        raise MixFailed(f"build_soundtrack.py exit {proc.returncode}: "
                        + quiet.clip(said[-1] if said else "no output", 160))
    fresh = json.load(open(plan_path))
    if not ((fresh.get("audio") or {}).get("bed") or {}).get("mix"):
        raise MixFailed("build_soundtrack.py mixed but could not record audio.bed "
                        "on the plan - qc_render.py would not know a bed was mixed")
    keep = [l.strip() for l in said
            if l.strip().startswith(("bed:", "rotation:", "SUBSTITUTED"))]
    return str(out), [f"mix: built {out} for channel {channel} (build_soundtrack.py, "
                      f"CF-0423)"] + [f"  {l}" for l in keep[:3]]


def src_holders(block):
    """Every dict of a block that names a file Remotion will mount.

    CF-0075: a half of a `side_by_side` block plays several pictures (`cuts`),
    each its own file. CF-0301: and so does a `sequence` block (CF-0120) -
    its cuts sit on `asset.cuts` directly, not under `sides`, and until this
    task nothing staged them: `asset.src` is only the first cut, so the second
    one reached Chrome as `file:///...` and the render died on it three times
    running (batch 2026-09-21T0358Z, the first live plan with a swing block).
    """
    asset = block["asset"]
    sides = asset.get("sides") or []
    cuts = [c for holder in (asset, *sides) for c in (holder.get("cuts") or [])]
    return [asset, *sides, *cuts]


def stage(path, seen, job):
    """Copy an asset into the job's own public/job and return its
    staticFile-relative path (CF-0340: `job` is this render's directory from
    new_job(), never a shared one)."""
    src = Path(path)
    if not src.exists():
        raise SystemExit(f"asset missing: {src}")
    if src in seen:
        return seen[src]
    dest = job_public(job) / STAGED / f"{len(seen):02d}_{src.name}"
    shutil.copy2(src, dest)
    rel = f"{STAGED}/{dest.name}"
    seen[src] = rel
    return rel


def main():
    p = argparse.ArgumentParser()
    p.add_argument("plan")
    p.add_argument("output")
    p.add_argument("--concurrency", default=None)
    p.add_argument("--gl", default=None,
                   help="CF-0052: Chrome's rasteriser. Default: "
                        f"--gl={GL_FOR_PROCEDURAL} for a typographic plan or "
                        "one whose procedural/still seconds outweigh its "
                        "footage by the measured costs (CF-0134), nothing "
                        "otherwise. `--gl=default` renders with Chrome's own.")
    p.add_argument("--audio", default=None,
                   help="final mixed audio, replacing the plan's bare voiceover "
                        "(see build_soundtrack.py). CF-0423: optional - without "
                        "it the plan's recorded mix plays, or the mix is built "
                        "here for the channel the plan was built for")
    p.add_argument("--bare-voice", action="store_true",
                   help="CF-0423: render the plan's voiceover with no mix at all "
                        "(diagnostics only - qc_render.py fails a channel's "
                        "video without its bed)")
    p.add_argument("--reason", default=None,
                   help="CF-0098: why this attempt is started (default: read off "
                        "the ledger - first | degraded:.. | qc_failed:.. | operator)")
    p.add_argument("--cap", type=int, default=None,
                   help=f"CF-0098: override {attempts.CHANNEL_KEY} (tests)")
    p.add_argument("--remotion-log", default=REMOTION_LOG,
                   choices=("error", "warn", "info", "verbose"),
                   help=f"CF-0131: Remotion's own log level (default {REMOTION_LOG}). "
                        "`error` is what this script used to pass, and it wrote an "
                        "empty attempt log; `verbose` adds a line per frame when a "
                        "single block has to be traced.")
    quiet.add_args(p)
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.plan))  # CF-0107: slug + the ledger's attempt so far

    plan = json.load(open(args.plan))

    # CF-0902: compliance's verdict is a stop here, not a sentence the
    # operator reads - example-film/2026-10-30T1033Z rendered a script whose
    # 04 row the claims gate had blocked. Asked before the attempt, so the
    # stop spends nothing; 04 is already the record of the loss (the funnel
    # counts the block), so nothing is written for 05.
    stop = pending_scripts.render_refusal(args.plan)
    if stop is not None:
        print(f"NOT CLEARED: {stop[0]} - {pending_scripts.VERDICTS_FILE} does not clear it: "
              f"{stop[1]} - not rendered ({pending_scripts.TASK}); the row of 04 is the "
              f"record, write nothing for it in 05")
        sys.exit(EXIT_NOT_CLEARED)

    # CF-0434: a video whose real penalties already put it under N is not
    # rendered (again). Asked before the attempt begins, so the stop spends
    # nothing; the stage that stopped it already wrote the refusal. A plan
    # with no score log (built before CF-0434, or outside this stage) renders
    # as before.
    block = score_log.current(args.plan)
    if block is not None and score_log.stops(block):
        # CF-0794: the refusal is this stop's record too. A stage that put
        # the log under N should have written it; when none is there (a
        # plan stage priced after its own check, a log from older code) it is
        # written here, so the script reaches 05-video-editor.json as
        # `score_below_threshold` without the operator naming it.
        side = score_log.refusal_path(args.plan)
        if not side.exists():
            side = score_log.check(args.plan, block, score_log.script_id_for(args.plan),
                                   block.get("stopped_at") or score_log.STAGE_PLAN)
        print(f"SCORE F after {block.get('stopped_at')}: {block['line']} - not rendered "
              f"(CF-0434: the video goes no further; refusal {side}) - "
              f"no video, so no QC: record the refusal with write_batch_metadata.py")
        sys.exit(EXIT_SCORE_F)

    # CF-0098: one render = one attempt, begun here so the cap cannot be
    # skipped. Outside a batch (a plan in a temp dir) there is no ledger and
    # no log, and the script behaves as it did before.
    ctx = quiet.Context.for_plan(args.plan)
    _STOP["ctx"] = ctx  # CF-0905: what a stop closes
    if ctx is not None:
        ctx.load(cap=args.cap)
        degraded = attempts.degraded_tags(plan)
        # CF-0415: a render whose only change is the degradation QC itself
        # suggested spends the degrade cap, not an attempt - classified off
        # the ledger and the plan's build_inputs digest, never off --reason.
        kind, auto = attempts.classify(ctx.ledger, plan)
        reason = args.reason or auto
        try:
            ctx.begin(reason, cap=args.cap, degraded=degraded, kind=kind,
                      build_inputs=attempts.plan_digest(plan))
        except attempts.Capped as capped:
            print(str(capped))
            sys.exit(attempts.EXIT_CAPPED)
        # CF-0107: this render *is* attempt n - the event carries the number
        # attempts.begin() just handed out, not the one before it.
        runlog.annotate(attempt=ctx.attempt["n"], attempt_kind=kind)

    # CF-0423: the render plays the mix, never the bare voice of a plan that
    # was built for a channel. Inside the attempt just begun: the mix is part
    # of it (build_soundtrack.py writes into this attempt's log), and a mix
    # that fails ends it like a render that fails.
    mix_lines = []
    if args.bare_voice:
        mix_lines = ["mix: NONE - --bare-voice renders the voiceover alone; "
                     "qc_render.py fails a channel's video without its bed"]
    elif not args.audio:
        try:
            mixed, mix_lines = ensure_mix(args.plan, plan, summary=args.summary)
        except MixFailed as e:
            detail = f"mix failed: {e}"
            capped = False
            label = quiet.attempt_label(ctx.attempt if ctx else None,
                                        ctx.ledger if ctx else None)
            if ctx is not None:
                # CF-0305: the mix broke before Remotion ran - no frame, not counted.
                _, capped = ctx.end(attempts.RESULT_RENDER_BROKEN, detail=detail,
                                    error=detail, frames=0)
            summary = [f"render BROKEN  rc=1  {label}  (no render: {detail}; "
                       f"not counted against the cap)"]
            if capped:
                summary.append(ctx.needs_you_line())
            if ctx is None or ctx.log is None:
                for l in summary:
                    print(l)
            else:
                quiet.summary(summary, ctx.log)
            sys.exit(1)
        if mixed:
            # build_soundtrack.py wrote audio.bed onto the plan on disk; the
            # props are built from that plan, so the render's record matches.
            plan = json.load(open(args.plan))
            args.audio = mixed

    # CF-0340: this call's own job directory - staged files, fonts and
    # props - so a render running alongside cannot delete or overwrite them.
    # Only this directory is removed afterwards, whatever the outcome - the
    # staged files are copies, and what Remotion said is in the attempt log.
    job = new_job(ctx.slug if ctx is not None else Path(args.plan).resolve().parent.name)
    try:
        _stage_and_render(args, plan, ctx, mix_lines, job)
    finally:
        shutil.rmtree(job, ignore_errors=True)


def _stage_and_render(args, plan, ctx, mix_lines, job):
    """Stage every asset into `job` (new_job()), write its props and run
    Remotion against it: the rest of main()."""
    seen = {}
    for block in plan["blocks"]:
        # `typographic` blocks are procedural and carry no file to stage, and a
        # `side_by_side` block (CF-0050) carries two files rather than one -
        # under `sides`, because the block is one composition of two pictures.
        # Staging only `asset.src` left those two as absolute paths, which
        # Remotion serves as 404s and renders as an unusable file.
        for holder in src_holders(block):
            src_path = holder.get("src")
            if src_path:
                holder["src"] = stage(src_path, seen, job)
        # An insert (CF-0071 proof `capture_path`, CF-0067 meme `render_src`)
        # is a file beside the block's asset and is served the same way -
        # unstaged it is an absolute path Chrome refuses from the http origin.
        insert = block.get("insert") or {}
        for key in ("capture_path", "render_src"):
            if insert.get(key):
                insert[key] = stage(insert[key], seen, job)
        # CF-0404: a meme laid over the shot as a cutout draws its PNG too.
        cutout = insert.get("cutout") or {}
        if cutout.get("render_src"):
            cutout["render_src"] = stage(cutout["render_src"], seen, job)
        # A sound insert (CF-0068, `sound` on the block) is not staged: it is
        # already in the mix build_soundtrack.py wrote (--audio below), and
        # Remotion draws nothing for it - the picture is unchanged by it.
    # CF-0117: the end card's logo is a channel asset on disk, staged like
    # every other picture - unstaged it is an absolute path Chrome refuses
    # from the http origin, and the card would silently lose its logo at the
    # one moment the channel is signing its name. A typographic card has no
    # file and needs none.
    card = plan.get("end_card") or {}
    if card.get("logo_path"):
        card["logo_path"] = stage(card["logo_path"], seen, job)
    # CF-0141: and the channel's ending clip, for exactly the same reason -
    # it is a file in `channels/<id>/`, outside the bundle, and an unstaged
    # absolute path is a 404 Chrome answers with nothing. The failure mode is
    # the worst one this repo has: the ending renders black, and the render
    # gate does not measure that interval (decision 3), so nothing would say
    # so. It is staged like every other picture, per render, and the plan on
    # disk is untouched.
    if card.get("path"):
        card["path"] = stage(card["path"], seen, job)
    # CF-0127: the second plane's file - the underlay loop the factory chose
    # for this video - is staged like every other picture, and for the same
    # reason: Chrome refuses an absolute path from the http origin, so an
    # unstaged loop is a silently black band. `plan["underlay"]["render_src"]`
    # is rewritten in the props too, so the job's own props.json says what was
    # served rather than what was chosen (`seen` dedupes: one staged file for
    # both fields). The plan on disk is untouched, as it is for every other
    # asset here - staging is per render, not a rewrite of the plan.
    if plan.get("secondary_source", {}) and plan["secondary_source"].get("src"):
        plan["secondary_source"]["src"] = stage(plan["secondary_source"]["src"], seen, job)
    underlay = plan.get("underlay") or {}
    if underlay.get("render_src"):
        underlay["render_src"] = stage(underlay["render_src"], seen, job)
    if args.audio:
        plan["audio"]["src"] = args.audio
    plan["audio"]["src"] = stage(plan["audio"]["src"], seen, job)

    # --props supplies the composition's ENTIRE props object, so the plan has to
    # be wrapped under the prop name. Passing the bare plan silently renders the
    # placeholder instead - which is exactly what happened until qc_render caught
    # a 5s video against a 41s voiceover.
    staged_plan = Path(job) / "props.json"
    json.dump({"plan": plan}, open(staged_plan, "w"), indent=2)

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["npx", "remotion", "render", "src/index.js", "Video", str(out),
           f"--props={staged_plan}", f"--public-dir={job_public(job)}",
           f"--log={args.remotion_log}"]
    if args.concurrency:
        cmd.append(f"--concurrency={args.concurrency}")
    # CF-0052: the measured knob, unless the caller said otherwise.
    gl = args.gl if args.gl is not None else gl_here(plan)  # CF-0711: not on an Intel GPU
    if gl and gl != "default":
        cmd.append(f"--gl={gl}")

    log = ctx.log if ctx is not None else None
    # No batch, no log: nothing to summarise against, so the terminal gets
    # everything as it did before CF-0098.
    verbose = not args.summary or log is None
    # CF-0135: the render is the longest stage of the pipeline and was the one
    # stage with no ceiling at all - this call passed no `timeout=`, and the
    # ceiling would not have covered the read even if it had. What it passes is
    # how long the material is; quiet.ceiling() turns that into the number
    # (common.media_timeout(): 300 s + 8 s per composition second, CF-0052's
    # throttling already inside the slope).
    watch = RemotionWatch()
    rc, lines, tail = quiet.run_logged(cmd, log, "render_video (remotion+ffmpeg)",
                                       verbose=verbose, cwd=RENDER, tool="remotion",
                                       on_line=watch,
                                       media_seconds=composition_seconds(plan),
                                       attempt=ctx.attempt["n"] if ctx else None,
                                       slug=ctx.slug if ctx else None,
                                       own_session=True)  # CF-0905: node + Chrome go with it
    # Remotion has been seen to exit 0 after failing to fetch an asset, leaving
    # a file ffprobe cannot read (CF-0050, a side_by_side block whose halves
    # were not staged). A zero exit code is therefore not on its own evidence
    # that anything was rendered.
    empty = rc == 0 and (not out.exists() or out.stat().st_size < 1024)
    if empty:
        tail.append(f"remotion exited 0 but {out} is missing or empty - check the "
                    f"log for an asset it could not load")
        rc = 1

    label = quiet.attempt_label(ctx.attempt if ctx else None, ctx.ledger if ctx else None)
    if rc != 0:
        # CF-0305: the detail names the error line Remotion printed (the last
        # line of the tail is a code frame or a blank - 0358Z recorded
        # `remotion exit 1: ` three times), and a failure before the first
        # frame is the tool's, not an attempt.
        failure = watch.failure_line(tail)
        detail = "remotion exit %d%s" % (rc, (": " + quiet.clip(failure, 120)) if failure else "")
        broken = watch.frames == 0
        capped = False
        if ctx is not None:
            _, capped = ctx.end(attempts.RESULT_RENDER_BROKEN if broken
                                else attempts.RESULT_RENDER_FAILED, detail=detail,
                                error=f"rc={rc}: {failure}", frames=watch.frames)
        if broken:
            summary = [f"render BROKEN  rc={rc}  {label}  (before the first frame - not "
                       f"counted against the cap; {lines} output line(s) in the log)"]
        else:
            summary = [f"render FAILED  rc={rc}  {label}  (after {watch.frames} frame(s); "
                       f"{lines} output line(s) in the log)"]
        summary += [f"  | {t}" for t in tail if t.strip()]
        if capped:
            summary.append(ctx.needs_you_line())
        if verbose and log is None:
            for l in summary:
                print(l)
        else:
            quiet.summary(summary, log)
        sys.exit(rc)

    summary = [f"rendered -> {out}",
               f"render OK  rc=0  {label}  ({lines} output line(s) in the log)",
               *mix_lines]
    # CF-0434: the render stage of the score log - the file's length and
    # frame - and the remainder after it. Under N the refusal is written here;
    # qc_render.py still runs (it ends the attempt) and says the same.
    block = score_log.record_render(args.plan, out)
    if block is not None:
        side = score_log.check(args.plan, block, score_log.script_id_for(args.plan),
                               score_log.STAGE_RENDER)
        summary.append(score_log.stop_line(block, score_log.STAGE_RENDER, side) if side
                       else f"score after render: {block['line']}")
    if log is None:
        for l in [summary[0], *summary[2:]]:
            print(l)
    else:
        quiet.summary(summary, log)


# CF-0905: the video context main() works under, for the stop to close.
_STOP = {"ctx": None}


def close_attempt_on_stop(signal_name, killed):
    """CF-0905: a render stopped by a signal ends its open attempt at once -
    `abandoned`, as attempts.begin() would have closed it on the next render
    (counted the same way), but with the stop named and its own end time,
    instead of `begun and never ended`. Nothing is open (stopped before the
    begin, or after the end): nothing is written."""
    ctx = _STOP.get("ctx")
    if ctx is None or ctx.attempt is None or ctx.attempt.get("ended_at"):
        return
    _, capped = ctx.end(attempts.RESULT_ABANDONED,
                        detail=f"stopped by {signal_name} before it finished - "
                               f"{len(killed)} child process group(s) killed with it "
                               f"(CF-0905)")
    if capped:
        print(ctx.needs_you_line())


@video_script("video-editor", "render", name="render_video.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests.

    CF-0905: under quiet.stop_on_signals() - a SIGTERM/SIGHUP/SIGINT (the
    operator's `kill`, a `pkill -f`, a closed terminal) kills the live
    children with their groups (build_soundtrack.py and its ffmpeg, Remotion
    with node and Chrome), closes the attempt and exits 128+signal, so the
    `failed` line is written and no orphan writes on."""
    with quiet.stop_on_signals(close_attempt_on_stop):
        main()


if __name__ == "__main__":
    cli()

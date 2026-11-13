#!/usr/bin/env python3
"""The source sieve, step 2 of three - a source refused for what is in it
(CF-0299, 2026-09-21).

Step 1 is Trend Hunter's: it picks candidate videos by title and channel, and
it cannot see a frame. Step 3 is the two-source floor of CF-0129, which counts
sources. Between them there was nothing, and batch
`example-film/2026-09-21T0358Z` is what that costs:

  `9a7i4LHHZNs`  offered as Delver's second source, and actually "Fred Perry's
                 Animated Antarctic Press Universe Trailer" - a comic-universe
                 reel with GD, Ninja High School and Dragon Arms title cards
                 and not one frame of the film. It was fetched, indexed (21
                 minutes), described by a subagent, counted by the two-source
                 gate, and refused by the writer with `no_second_source` after
                 the whole stage had been paid for.
  `bYKJxZYd66o`  offered as Coach Hale's first source, and actually a vertical
                 interview Short with a dating-app promo in it. The frame
                 judge rejected the finished render over **six** burned-in
                 captions, every one of them a frame of this source - after
                 the script, the TTS and the render.

**Why the describer answers this and not a detector.** The measurement that
looks like it should already know sits on every shot, and it says the opposite
of the truth. Over the pool of that batch, the share of shots with
`usable_cached.text_outside_crop > 0`:

    JzA-WopbYnc (real Coach Hale scenes, good)          0.60
    QJ1WSiMUVFA (a foreign overlay on every shot)      1.00
    bYKJxZYd66o (mid-frame captions, the render died)  0.00
    9a7i4LHHZNs (foreign title cards)                  0.18
    0vjwu1hjqK0 / -gp7j-DhWDU (good)                   0.00 / 0.00

The good Coach Hale source measures *worse* than the one that killed the
render, because its subtitles are in the bottom band the 9:16 caption crop
removes (CF-0275) and the interview's are across the middle, where the
detector's own crop logic files them as nothing. So the flags come from
whoever reads the contact sheet - `burned_text` and `on_topic`, on every shot,
see `shot_schema.py` and SKILL.md - and this script does the arithmetic.

**The thresholds, and where they come from.** Same pool, the two shares this
script computes, from the flags in `tests/fixtures/cf0299_sieve_flags.json`:

    source         burned_text   off_topic    the sieve says
    9a7i4LHHZNs        0.216       1.000       source_foreign
    bYKJxZYd66o        1.000       0.022       source_burned_text (kept since CF-0435)
    QJ1WSiMUVFA        1.000       0.000       source_burned_text (kept since CF-0435)
    wS6wtevVlmc        0.017       1.000       source_foreign
    JzA-WopbYnc        0.000       0.000       kept
    0vjwu1hjqK0        0.000       0.000       kept
    -gp7j-DhWDU        0.000       0.000       kept
    ZLXL1L0TfsI        0.048       0.000       kept

Every source that has to go is at 1.000 on one of the two shares; every source
that has to stay is at 0.048 or below on both. The empty band between them is
the whole width of the scale, so the threshold is not fitted to the sample -
it is put in the middle of a gap that nothing is in, at the word the task was
written with: **a majority of the shots**, 0.5. A source at 0.216 burned text
(`9a7i4LHHZNs` and its title cards) is not refused for its text and is refused
for being somebody else's film, which is the true answer about it.

A source is refused **whole**, never shot by shot. The floor below it counts
sources, and a source that is three-quarters of another film is not made
usable by its good quarter - the anchors would land in the quarter and the
render would show the rest.

**CF-0435 (2026-09-30): only somebody else's film is refused whole.** The
grill of 2026-09-29 (Q19 step 4, Q24) moved the factory to the score model of
CF-0432: the hard list keeps "footage of someone else's work, by the sieve's
decision" (`score.hard.foreign_work_footage`) - the `source_foreign` verdict
above, unchanged, majority `on_topic: false`. A majority of burned-in text is
no longer a whole-source refusal: `bYKJxZYd66o` and `QJ1WSiMUVFA` in the table
are now `kept`, their `burned_text: true` shots stay out one by one
(`shot_usability` hard rule `burned_text`, the Editor's `entity_guard`) until
the grill "вшитый текст", and whatever clean shots they have stay in the pool.
In a kept source an `on_topic: false` shot is no longer lost either: it is a
weak shot (`score.off_topic_shot`), counted by `pool_depth` and charged by the
score model when it reaches the screen. `source_burned_text` stays a known
funnel code for the reports written before this task. After the sieve the
kept sources this batch fetched carry `shot.usability` on every shot
(`stamp_usability()`; never the pool's old sources, and nothing is
re-measured).

Usage:
    source_sieve.py <batch-dir> [--dry-run] [--no-top-up] [--sources-wanted 2]
                    [--pool-depth-floor 60] [--no-second-source warn|enforce]

CF-0362 / CF-0419: the floor's mode is `ingest_batch.floor_mode()` - the
channel's `footage_indexer.no_second_source` (the rule's own switch, where
`runlog triage` reads it; `warn` by the user's decision of 2026-09-28), else
its `video_editor.two_source_gate`, else `warn`. Under `warn` / `measure` a
topic left with at least one kept source is not refused `no_second_source`: it
stays in `sources_by_topic` with a `warnings[]` entry carrying its counts.
`enforce` refuses as before. A topic with no kept source is refused in every
mode, and a pool under the depth floor is a `pool_too_thin` warning in every
mode (`ingest_batch.apply_floor_mode`).

CF-0359: **the flags of the batch's own sources are answered here, before the
judging.** CF-0355 gave this script an exit code over a source nobody answered
for, and that is what a batch reusing an old pool source (the same official
trailer, indexed before CF-0299) walked into: the stage could not close, and a
run that cannot close waits for a human, which DoD 1 of milestone 1.4.5
forbids. The full old pool is not marked - 2708 shots in 82 sources of dead
topics, deleted after publication anyway (CF-0358, the user's ruling of
2026-09-23) - so the marking happens where it is needed and nowhere else:
`backfill_sieve_flags.batch` over this batch's sources, one sheet and one
answer per source, run from `main()` before `sieve_report()`. `--no-backfill`
turns it off.

CF-0374: **who answers is a setting of the run.** CF-0359 left the answerer to
`--answer-cmd` or `$SIEVE_FLAGS_ANSWER_CMD`, and neither was ever set: the step
shrank to "apply the answers already in the directory", so an unattended run
took every reused old source *out with a record* instead of marking it - legal
under DoD 1 and a lost topic each time, when marking one source is cheaper than
losing a topic. The command now comes from the channel's config, where the
length ceiling and `two_source_gate` come from:
`channels/<channel>.json` -> `footage_indexer.sieve_flags_answer_cmd` (a
string, or a block with `command` and `timeout_seconds`). `--answer-cmd` still
wins for one run and the environment variable is still read after the config,
for the pilot's shell sessions. Having no answerer stays legal - the run goes
on - but it is no longer silent: the sieve writes a `sieve_answers` run-log
event whose `line` says how many sources it marked on the spot and how many it
took out with a record, and the root prints that line in `RUN_SUMMARY.md`.

A source the backfill could not answer (no mp4 left to take frames from, an
answerer that failed or timed out, answers that did not cover every shot) is
**refused and recorded**, not waited for: `refuse_unanswered()` turns its
`unsieved` record into a refusal with `UNANSWERED_CODE` and the sentence that
says what failed, and from there it is an ordinary refused source - out of
`fetched` and `sources_by_topic`, into `failed[]` with `refused_at: sieve`,
with the top-up and the floor mode settling the topic. The run goes on and the
stage closes. The exit code of CF-0355 stays as the insurance it was: a source
still unsieved when nothing tried to answer it (`--no-backfill`) exits 3.

CF-0304: a source taken out here is a pool made shallower, so the top-up is
settled against the depth floor as well as the source count - a topic left
with its two sources and a pool the Editor's pre-cut gate would empty takes
its next candidate too. `pool_depth.py` owns that measurement; this file only
asks it, with the same floor `ingest_batch.py` walked to.
"""
import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import backfill_sieve_flags as backfill  # noqa: E402 - CF-0359: the flags of an old source, answered before the judging
import ingest_batch  # noqa: E402
import pool_depth  # noqa: E402 - CF-0304: the same depth floor the first pass walked to
import pool_sources  # noqa: E402 - CF-0817: the host-show marks of the pool check
import shot_schema  # noqa: E402
import shot_usability  # noqa: E402 - CF-0435: a shot's score, and its stamp on the batch's own sources
import screen_recording  # noqa: E402 - CF-0451: the cinema cam, a warning until a price is signed
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting

STAGE_NAME = ingest_batch.STAGE_NAME
REPORT_FILE = ingest_batch.REPORT_FILE

# The share of a source's shots that has to carry a flag before the source is
# refused for it. See the table in the module docstring: the measured pool has
# nothing at all between 0.071 and 1.000, and this sits in the middle of that
# gap. Shares are always over *every* shot of the source, never over the ones
# that were flagged - see shot_schema.sieve_counts().
#
# CF-0435 (the grill of 2026-09-29, Q19 step 4 and Q24): only one of the two
# still refuses a source whole. A majority of `on_topic: false` is the sieve's
# decision that the source is **somebody else's film** - the hard list's
# `score.hard.foreign_work_footage` - and stays exactly as it was. A majority
# of `burned_text: true` no longer refuses anything: those shots stay out one
# by one (`shot_usability`'s hard rule `burned_text`, the Editor's
# `entity_guard`) until the grill "вшитый текст", and the source's clean shots
# stay in the pool. `BURNED_TEXT_SHARE` is None - "no whole-source threshold";
# the share is still measured and reported on every record.
BURNED_TEXT_SHARE = None
OFF_TOPIC_SHARE = 0.5

# What one source's record says it is.
KEPT = "kept"
REFUSED = "refused"
UNSIEVED = "unsieved"       # nobody answered for it: not judged, not refused

SIEVE_LINE = "SIEVE {vid} refused for {tid}: {reason}"
UNSIEVED_LINE = ("SIEVE {vid} ({tid}) carries sieve flags on {decided}/{shots} "
                 "shot(s) - not judged. Describe the rest before the writer "
                 "sees this batch (CF-0299).")
# CF-0355: a batch whose sources are not all answered for is not sieved, and
# the stage must not close as if it were. Up to this task `unsieved` was only
# a printed line and the script still exited 0, so an index described before
# CF-0299 (the whole old pool: 2821 shots in 84 sources) went through every
# batch that reused it with no answer on `burned_text` - `vCOn4RibD1g:19`,
# "name captions visible", reached block 0 of everyday-sorcery-2 that way. The
# report is still written (the refusals it holds are real); the exit code is
# what makes the runlog record the stage's sieve step `failed`.
UNSIEVED_EXIT = 3
UNSIEVED_GATE_LINE = ("SIEVE {n} source(s) carry no complete burned_text/"
                      "on_topic answer ({ids}) - the stage is not done: "
                      "describe or backfill them (backfill_sieve_flags.py, "
                      "CF-0355) and run the sieve again (exit {code}).")
TOPUP_LINE = ("SIEVE {tid} is below the {wanted}-source floor after the sieve "
              "and takes its next candidate ({left} attempt(s) left)")

# ---------------------------------------------------------------------------
# CF-0359: the batch's own backfill, and what happens when it fails
#
# Where the sheets, the questions and the answers of one batch's backfill go.
# Under the batch, beside the other working files, so that the answers a run
# was given are still readable when somebody asks why a source was refused.
BACKFILL_DIR = Path("work") / "sieve-backfill"
BACKFILL_KEY = "sieve_backfill"
BACKFILL_LINE = ("SIEVE backfill (CF-0359): {ok} source(s) of this batch "
                 "answered on the spot, {bad} not answered{names}")
BACKFILL_DRY_LINE = ("SIEVE backfill (CF-0359) would answer {n} source(s) of "
                     "this batch first; nothing was written (--dry-run)")
BACKFILL_BROKE_LINE = ("SIEVE backfill (CF-0359) did not run: {error}. The "
                       "sieve judges the batch as it stands - a source left "
                       "unanswered is refused with a record, and the run goes "
                       "on")
REFUSED_UNANSWERED_LINE = ("SIEVE {vid} ({tid}) could not be answered for and "
                           "is taken out of the batch: {error}")

# The code a source refused for having no answer carries. Deliberately the
# code CF-0281 already writes and not a new word: `index_failed` is "it came
# down and our own indexing did not finish for it", and since CF-0299 the two
# flags are part of what a finished description pass leaves - an index that
# cannot be sieved is ours, unfinished, exactly like one with no shots. A new
# word would also have to be taught to `shared/runlog/funnel.py` FUNNEL_CODES
# and to `ingest_batch.TOPIC_REFUSAL_CODES` (a topic that loses everything this
# way is refused by `topic_refusal`, which raises on a code outside that
# tuple), and a loss code the funnel does not know is a loss nobody counts -
# which is the ratchet this milestone exists to avoid, not to add to.
UNANSWERED_CODE = ingest_batch.INDEX_FUNNEL_CODE
UNANSWERED_REASON = (
    "the two sieve flags (`burned_text`, `on_topic`) could not be answered for "
    "this source, so the sieve cannot judge it: {decided} of its {shots} "
    "shot(s) carry both. Its index was written before CF-0299, or its "
    "description pass did not finish, and the backfill that answers such shots "
    "on the spot before the sieve (backfill_sieve_flags.py batch, "
    "CF-0355/CF-0359) failed on it - {error}. An unjudged source is not sent "
    "to the writer (that is what the sieve is for), so it is taken out of the "
    "batch here with this record; the topic takes its next candidate inside the "
    "same attempt cap if it has one, and the run goes on rather than stopping "
    "the stage (DoD 1 of milestone 1.4.5).")


# ---------------------------------------------------------------------------
# CF-0374: the answerer is a setting of the run, not of the session
#
# CF-0359 made the marking happen here and left the answerer nameless: with
# neither `--answer-cmd` nor `$SIEVE_FLAGS_ANSWER_CMD` the step shrank to
# "apply the answers already lying in the directory", so in an unattended run
# every source of the old pool was *taken out with a record* instead of being
# marked - legal under DoD 1 (the run does not stop) and a lost topic every
# time, when marking one source is cheaper than losing a topic.
#
# An environment variable is not a setting of a run: nobody sets it, and a run
# started by the root has no session to set it in. So the command lives where
# the ceiling and `two_source_gate` live - in the channel's
# config, read at the point of use through `_channel_ids`, exactly the way
# `ingest_batch.two_source_mode()` reads its own key:
#
#     channels/<channel>.json -> footage_indexer.sieve_flags_answer_cmd
#
# A bare string is the command; a block is `{"command": ..., "timeout_seconds":
# N, "note": ...}`, the shape `max_source_duration_seconds` already uses, so
# the ceiling on one source's answerer can be configured beside it.
# Precedence, most explicit first: `--answer-cmd` (one run, by hand), the
# channel's config (every run of that channel), `$SIEVE_FLAGS_ANSWER_CMD` (kept
# for the pilot's shell sessions and for a repo copied out of the factory),
# nothing. **Nothing stays legal** - it is the pre-CF-0374 behaviour and the
# run still goes on; what changes is that the summary now says so.
ANSWER_CMD_KEY_PATH = ("footage_indexer", "sieve_flags_answer_cmd")
ANSWER_CMD_KEY = ".".join(ANSWER_CMD_KEY_PATH)
ANSWER_CMD_FIELD = "command"
ANSWER_TIMEOUT_FIELD = "timeout_seconds"
# Where a command came from, as the summary line and the report name it.
ANSWER_FROM_FLAG = "--answer-cmd"
ANSWER_FROM_CONFIG = f"channels/<channel>.json {ANSWER_CMD_KEY}"
ANSWER_FROM_ENV = f"${backfill.ANSWER_CMD_ENV}"
ANSWER_FROM_NOWHERE = "none"


def answer_cmd_from_config(cfg):
    """`footage_indexer.sieve_flags_answer_cmd` of a loaded channel config, as
    `(command, timeout_seconds)` - None for whatever the config does not say.

    A string is the command; a block's `command` is the command and its
    `timeout_seconds` the ceiling on one source. Anything else is silence: a
    typo must not become a shell line, and it must not become a refusal
    either - see `answerer()`."""
    node = cfg
    for part in ANSWER_CMD_KEY_PATH:
        node = node.get(part) if isinstance(node, dict) else None
    timeout = None
    if isinstance(node, dict):
        t = node.get(ANSWER_TIMEOUT_FIELD)
        if isinstance(t, int) and not isinstance(t, bool) and t > 0:
            timeout = t
        node = node.get(ANSWER_CMD_FIELD)
    cmd = node.strip() if isinstance(node, str) and node.strip() else None
    return cmd, timeout


def channel_config(channel, config_path=None, root=None):
    """The channel's loaded config, or `{}` when there is no readable one - the
    same read, and the same silence, as `ingest_batch.two_source_mode()`."""
    root = Path(root) if root else (Path(ingest_batch.FACTORY_ROOT)
                                   if ingest_batch.FACTORY_ROOT else None)
    try:
        channel = ingest_batch.resolve_channel(channel, root=root)
        path = (Path(config_path) if config_path
                else ingest_batch.channel_config_path(channel, root=root))
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:       # noqa: BLE001 - a missing config is "no answerer"
        return {}


def answerer(channel=None, flag=None, timeout_flag=None, config_path=None,
             root=None, env=None):
    """Which command answers this batch's open sieve flags, where it came from,
    and how long one source may take.

    Returns `{"command": str|None, "from": str, "timeout": int}`. `from` is one
    of the `ANSWER_FROM_*` words and is what the summary line quotes, so an
    operator reading it knows which file to edit. `timeout_flag` (the CLI's
    `--answer-timeout`) wins over the config's `timeout_seconds` only when it
    is not the default - the flag has no "unset".
    """
    cfg_cmd, cfg_timeout = answer_cmd_from_config(
        channel_config(channel, config_path=config_path, root=root)
        if channel or config_path else {})
    env = os.environ if env is None else env
    env_cmd = (env.get(backfill.ANSWER_CMD_ENV) or "").strip() or None
    flag = (flag or "").strip() or None
    cmd, came_from = None, ANSWER_FROM_NOWHERE
    for value, name in ((flag, ANSWER_FROM_FLAG), (cfg_cmd, ANSWER_FROM_CONFIG),
                        (env_cmd, ANSWER_FROM_ENV)):
        if value:
            cmd, came_from = value, name
            break
    timeout = backfill.ANSWER_TIMEOUT_SECONDS
    if cfg_timeout:
        timeout = cfg_timeout
    if timeout_flag and timeout_flag != backfill.ANSWER_TIMEOUT_SECONDS:
        timeout = timeout_flag
    return {"command": cmd, "from": came_from, "timeout": timeout}


# ---------------------------------------------------------------------------
# CF-0374: what the run summary says about the marking
#
# The root builds `RUN_SUMMARY.md` out of `RUN_EVENTS.jsonl` and opens no
# stage artifact (CF-0368), so a count that only sits in
# `01b-footage-index.json -> sieve_backfill` never reaches the summary. This
# stage therefore writes the finished sentence into its own event, the way
# `trend-hunter/scripts/search_quota.py` writes its `quota` line, and the root
# prints `line` of the last such event verbatim.
ANSWER_EVENT_KIND = "sieve_answers"
ANSWER_EVENT_TASK = "CF-0374"
ANSWER_EVENT_STEP = "sieve-answers"
ANSWER_SUMMARY_NOTHING = (
    "Sieve flag answers: nothing to mark - every source of this batch was "
    "already answered for on `burned_text`/`on_topic` before the sieve "
    "(CF-0374)")
ANSWER_SUMMARY_OFF = (
    "Sieve flag answers: the on-the-spot marking was off (--no-backfill), so "
    "{asked} source(s) went into the sieve unanswered (CF-0374)")
ANSWER_SUMMARY_NO_CMD = (
    "Sieve flag answers: no answerer is configured ({key}), so nothing could "
    "be marked on the spot - {marked} of {asked} source(s) marked, {taken} "
    "taken out of the batch with a record ({code}); the run went on (CF-0374, "
    "DoD 1)")
ANSWER_SUMMARY = (
    "Sieve flag answers: {marked} of {asked} source(s) marked on the spot, "
    "{taken} taken out of the batch with a record ({code}) - answerer "
    "{name}from {origin} (CF-0374)")
# CF-0478: the answerer's own word for "the console claude has no session"
# (`sieve_answer_claude.NOT_LOGGED_IN`, quoted by the backfill in the failed
# source's error), and what the summary adds when a source failed on it - the
# run went on, the login is the user's (the journal of questions asks it,
# CF-0652).
ANSWER_NOT_LOGGED_IN_MARK = "NOT_LOGGED_IN"
ANSWER_SUMMARY_NOT_LOGGED_IN = (
    "; {n} source(s) failed because the console claude is not logged in - "
    "the journal of questions asks for a login (CF-0478)")


def answerer_name(cmd):
    """The answerer's short name for the summary line: the script the command
    runs (`sieve_answer_claude.py`), else its first word - so the line says
    *which* configured answerer answered, not only where it was configured."""
    if not cmd:
        return None
    words = cmd.split()
    for w in words:
        w = w.strip("'\"")
        if w.endswith((".py", ".sh")):
            return Path(w).name
    return Path(words[0].strip("'\"")).name if words else None


def not_logged_in(block):
    """The sources of a backfill block that failed on the answerer's
    not-logged-in word."""
    return [r.get("video_id") for r in (block or {}).get("sources") or []
            if not r.get("ok")
            and ANSWER_NOT_LOGGED_IN_MARK in str(r.get("error") or "")]


def answers_summary_line(block, answerer=None, taken=None, off=False,
                         asked=None):
    """The one finished line about this batch's on-the-spot marking, for the
    root's `RUN_SUMMARY.md`.

    Rendered here and shipped inside the event: the root has no business
    knowing what a sieve flag is or why an unmarked source becomes an
    `index_failed` record. Four states, and they must not read the same -
    telling "the marking works" from "there is no answerer, everything is being
    taken out" is the whole point of this line.
    """
    block = block or {}
    answerer = answerer or {"command": None, "from": ANSWER_FROM_NOWHERE}
    asked = len(block.get("sources") or []) if asked is None else asked
    marked = len(block.get("answered") or [])
    taken = len(taken or [])
    if off:
        return ANSWER_SUMMARY_OFF.format(asked=asked)
    if not asked and not taken:
        return ANSWER_SUMMARY_NOTHING
    if not answerer.get("command"):
        return ANSWER_SUMMARY_NO_CMD.format(
            key=ANSWER_FROM_CONFIG, marked=marked, asked=asked, taken=taken,
            code=UNANSWERED_CODE)
    name = answerer_name(answerer.get("command"))
    line = ANSWER_SUMMARY.format(marked=marked, asked=asked, taken=taken,
                                 code=UNANSWERED_CODE,
                                 name=f"`{name}` " if name else "",
                                 origin=answerer.get("from"))
    logged_out = not_logged_in(block)
    if logged_out:
        line += ANSWER_SUMMARY_NOT_LOGGED_IN.format(n=len(logged_out))
    return line


def record_answers_event(batch, block, answerer=None, taken=None, off=False,
                         asked=None, emit=None):
    """Write the `sieve_answers` event the root's summary line is made of, and
    return it (None when there is no run log to write to).

    Accounting never breaks a run: a missing or broken runlog is silence, as in
    `search_quota.record_event()`."""
    emit = emit or getattr(runlog, "emit", None)
    if emit is None:
        return None
    line = answers_summary_line(block, answerer=answerer, taken=taken, off=off,
                                asked=asked)
    payload = {
        "task": ANSWER_EVENT_TASK,
        "asked": (len(((block or {}).get("sources")) or [])
                  if asked is None else asked),
        "marked": len(((block or {}).get("answered")) or []),
        "taken_out": list(taken or []),
        "answerer_from": (answerer or {}).get("from") or ANSWER_FROM_NOWHERE,
        "answerer_configured": bool((answerer or {}).get("command")),
        "answerer": answerer_name((answerer or {}).get("command")),
        "not_logged_in": not_logged_in(block),
        "refusal_code": UNANSWERED_CODE,
        "backfill_ran": bool((block or {}).get("ran")) and not off,
    }
    try:
        return emit(str(batch), ANSWER_EVENT_KIND, STAGE_NAME,
                    step=ANSWER_EVENT_STEP, status="done",
                    params={"task": ANSWER_EVENT_TASK}, line=line,
                    sieve_answers=payload)
    except Exception:       # noqa: BLE001 - see the docstring
        return None


def examples(index, indices, limit=3):
    """The first few flagged shots, as `12: <description>` - what the refusal
    quotes so it can be read with no other file open."""
    by_index = {s.get("index"): s for s in (index.get("shots") or [])
                if isinstance(s, dict)}
    out = []
    for i in indices[:limit]:
        text = (by_index.get(i) or {}).get("description") or ""
        text = " ".join(text.split())
        if len(text) > 160:
            text = text[:157] + "..."
        out.append(f"{i}: {text}" if text else str(i))
    return out


def judge(index, burned_share=BURNED_TEXT_SHARE, off_topic_share=OFF_TOPIC_SHARE,
          entity=None, title=None):
    """The sieve's answer about one loaded index.

    Returns the record that goes into the report's `source_sieve.sources[]`:
    verdict (`kept` / `refused` / `unsieved`), the two shares it was measured
    on, and for a refusal the funnel code and a sentence that names what was
    seen. `off_topic` is asked first: a source that is somebody else's work is
    refused for being that, whatever its text does.

    CF-0435: that is the only whole-source refusal left. A source with a
    majority of burned-in text is `kept`; its `burned_text_shots` are listed
    on the record and stay out shot by shot, and `usability` counts how many
    of its shots are clean, weak (a soft rule - they stay, at a cost) and hard
    (black, empty, burned text - out).

    CF-0344: `entity` is set for a thin-pool supplement source (CF-0338,
    `fetched[].supplement.entity`). Such a source was fetched *for* that
    entity - the actor's other film, an interview - so "another work" is what
    it is meant to be, and a shot counts as off topic only when it is neither
    the topic's work nor shows the entity (`shot_schema.shows_entity`). A
    frame of the other film without the actor still counts against it. The
    threshold and the whole-source rule are the same.

    CF-0451: `screen_recording` on the record - the shots filmed off a screen
    (`screen_recording.source_summary`, the describer's flag or sentence) and
    whether the candidate's `title` names a cam copy. Never a verdict: until
    the user signs a price it is a `warnings[]` entry (`screen_warnings()`).
    """
    c = shot_schema.sieve_counts(index, entity=entity)
    n = c["shots"] or 1
    burned = c["burned_text"] / n
    off = c["off_topic"] / n
    rec = {
        "shots": c["shots"], "decided": c["decided"],
        "burned_text": c["burned_text"], "burned_text_share": round(burned, 3),
        "off_topic": c["off_topic"], "off_topic_share": round(off, 3),
        "thresholds": {"burned_text_share": burned_share,
                       "off_topic_share": off_topic_share},
        "verdict": KEPT, "reason_code": None, "reason": None, "examples": [],
        # CF-0435: what the source holds shot by shot - `burned_text_shots`
        # stay out one by one, everything else (weak ones included) is pool.
        "burned_text_shots": list(c["burned_text_shots"]),
        "usability": shot_usability.summary(
            index.get("shots") if isinstance(index, dict) else index),
        "screen_recording": screen_recording.source_summary(index, title=title),
    }
    if entity:
        rec["judged_by"] = "entity"
        rec["entity"] = entity
        rec["entity_shots"] = len(c["entity_shots"])
        rec["off_topic_shots"] = list(c["off_topic_shots"])
    if not c["complete"]:
        rec["verdict"] = UNSIEVED
        rec["reason"] = (
            f"{c['decided']} of {c['shots']} shot(s) carry both sieve flags "
            f"(burned_text, on_topic), so this source has not been through the "
            f"sieve and is neither refused nor cleared by it. The share is "
            f"measured over every shot, so a partly flagged index would read "
            f"as whatever the describer happened to look at. Finish the "
            f"description pass for it (CF-0299).")
        return rec
    if off > off_topic_share:
        rec["verdict"] = REFUSED
        rec["reason_code"] = ingest_batch.SIEVE_FOREIGN_CODE
        rec["examples"] = examples(index, c["off_topic_shots"])
        what = (f"picture this topic's work or show {entity}, the entity "
                f"this supplement source was fetched for (CF-0344)"
                if entity else "picture this topic's work at all")
        rec["reason"] = (
            f"{c['off_topic']} of {c['shots']} shot(s) ({off:.0%}) do not "
            f"{what}, over the {off_topic_share:.0%} "
            f"the sieve allows: this is somebody else's material offered under "
            f"the topic's name (CF-0299). Refused whole - a source whose "
            f"majority is another work is not made usable by its remainder, "
            f"the anchors would land in the remainder and the render would "
            f"show the rest. Seen in it: "
            + " | ".join(rec["examples"]))
        return rec
    if burned_share is not None and burned > burned_share:
        # Off since CF-0435 (BURNED_TEXT_SHARE is None): kept for a caller
        # that asks for the old whole-source rule by passing a share.
        rec["verdict"] = REFUSED
        rec["reason_code"] = ingest_batch.SIEVE_BURNED_TEXT_CODE
        rec["examples"] = examples(index, c["burned_text_shots"])
        rec["reason"] = (
            f"{c['burned_text']} of {c['shots']} shot(s) ({burned:.0%}) carry "
            f"somebody else's burned-in text that the 9:16 caption crop does "
            f"not remove, over the {burned_share:.0%} the sieve allows "
            f"(CF-0299). A studio's corner logo is not counted. This is the "
            f"fault the frame judge rejected a finished render for on "
            f"2026-09-21, six entries in, after the script, the TTS and the "
            f"render had been paid for. Seen in it: "
            + " | ".join(rec["examples"]))
        return rec
    return rec


def index_path(vid, cache=None):
    cache = Path(cache) if cache else ingest_batch.CACHE
    return cache / f"{vid}.shots.json"


def read_index(vid, cache=None):
    """The loaded index of one source, or None when there is no readable one.

    An unreadable index is not the sieve's business: CF-0281 already refuses a
    source that has none, and this step runs after it."""
    p = index_path(vid, cache)
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def run_backfill(report, batch, only, out=None, answer=None, answer_cmd=None,
                 timeout=backfill.ANSWER_TIMEOUT_SECONDS, log=print,
                 cache=None, pipeline=None):
    """Answer the open sieve flags of `only` - the sources of this batch the
    sieve has just called `unsieved` - and nothing else.

    The list comes from the sieve's own verdicts rather than from the pool, for
    two reasons: a source the describer answered for is not asked about again,
    and no index outside this batch is opened at all (the user's ruling of
    2026-09-23 - the old pool is not marked wholesale).

    Never raises and never stops the run: an answerer that dies, an mp4 that
    CF-0358 has already deleted, a whole step that cannot start - each comes
    back as a record, and the sieve goes on to judge the batch as it stands
    (DoD 1). Returns the block the report carries under `sieve_backfill`.
    """
    out = Path(out) if out else Path(batch) / BACKFILL_DIR
    footage = Path(cache) if cache else ingest_batch.CACHE
    empty = {"ran": True, "task": "CF-0359", "answerer": None,
             "out_dir": str(out), "sources": [], "answered": [], "failed": [],
             "note": backfill.BATCH_NOTE}
    if not only:
        # Every source of the batch was answered for by the describer, so
        # there is nothing to ask and no file to open. The block is written
        # anyway: "nobody had to be asked" and "nobody asked" must not read the
        # same, for the reason the sieve's own block is always written.
        return empty
    try:
        block = backfill.backfill_batch(
            report, out, footage=footage,
            pipeline=Path(pipeline) if pipeline else backfill.PIPELINE,
            answer=answer, answer_cmd=answer_cmd, timeout=timeout, log=log,
            only=list(only))
    except Exception as e:                      # noqa: BLE001 - see docstring
        error = f"{type(e).__name__}: {e}"
        log(BACKFILL_BROKE_LINE.format(error=error))
        return {"ran": False, "task": "CF-0359", "error": error,
                "out_dir": str(out), "sources": [], "answered": [],
                "failed": [], "note": backfill.BATCH_NOTE}
    if block["sources"]:
        log(BACKFILL_LINE.format(
            ok=len(block["answered"]), bad=len(block["failed"]),
            names=(" (" + ", ".join(block["failed"]) + ")")
                  if block["failed"] else ""))
    return block


def refuse_unanswered(sieved, block, log=print):
    """Turn every source the backfill could not answer into a refusal.

    The one thing this task changes about the stage's outcome. Up to CF-0359
    such a source stayed `unsieved`, the script exited 3 and the stage never
    closed - a run waiting for a human over a source of a dead topic. Now the
    record it already has becomes an ordinary sieve refusal (`UNANSWERED_CODE`,
    the sentence that names what failed), and `apply_sieve()` below does the
    rest exactly as it does for a source refused for foreign text: out of
    `fetched` and `sources_by_topic`, into `failed[]` with `refused_at: sieve`,
    the top-up and the floor mode settling the topic. Nothing else refuses
    anything new here - a source the backfill answered is judged on its flags
    like any other.

    Returns the ids taken. `sieved` is modified in place.
    """
    block = block or {}
    why = {r["video_id"]: r.get("error") or "not answered"
           for r in block.get("sources") or [] if not r.get("ok")}
    # A step that could not start at all (`ran: false`) answered for nothing,
    # so its error is every unsieved source's error - otherwise one broken
    # backfill would put the stage back to waiting on the CF-0355 exit code,
    # which is the whole thing this task removes.
    step_error = block.get("error") if block.get("ran") is False else None
    taken = []
    for rec in sieved["sources"]:
        if rec["verdict"] != UNSIEVED:
            continue
        error = why.get(rec["video_id"]) or step_error
        if not error:
            continue
        rec["verdict"] = REFUSED
        rec["reason_code"] = UNANSWERED_CODE
        rec["backfill_error"] = error
        rec["reason"] = UNANSWERED_REASON.format(
            decided=rec.get("decided", 0), shots=rec.get("shots", 0),
            error=error)
        sieved["refused"].setdefault(rec["topic_id"], []).append(rec)
        taken.append(rec["video_id"])
        log(REFUSED_UNANSWERED_LINE.format(vid=rec["video_id"],
                                           tid=rec["topic_id"], error=error))
    return taken


def supplement_entities(report):
    """`{(topic_id, video_id): entity}` for the sources a thin-pool supplement
    brought (CF-0338 writes `supplement.entity` on their `fetched[]` record).
    A source with no such record is an ordinary one and is judged as before."""
    out = {}
    for f in report.get("fetched") or []:
        ent = (f.get("supplement") or {}).get("entity")
        if isinstance(ent, dict):
            ent = ent.get("name")
        if ent and f.get("video_id"):
            out[(f.get("topic_id"), f["video_id"])] = ent
    return out


HOST_SHOW_CODE = pool_sources.HOST_SHOW          # CF-0817


def host_show_refusals(report, topics=None):
    """CF-0817: `{(topic_id, video_id): verdict}` of the held sources somebody
    already found to be another people's host show - their `fetched[]`
    record carries `host_show.refused` (the pool check's mark), or Trend
    Hunter's candidate record of the same id for the topic does (it dropped
    it with `reason_code: host_show`, or offered it with the verdict on it).
    Neither should reach a held source any more: the pool check refuses a
    host show before it is counted and Trend Hunter does not offer one. This
    is the guard for when one did."""
    out = {}
    for f in report.get("fetched") or []:
        v = f.get(HOST_SHOW_CODE)
        if isinstance(v, dict) and v.get("refused") and f.get("video_id"):
            out[(f.get("topic_id"), f["video_id"])] = v
    by_id = {t.get("topic_id"): t for t in topics or () if isinstance(t, dict)}
    for tid, vids in (report.get("sources_by_topic") or {}).items():
        for vid in vids or ():
            if (tid, vid) in out or tid not in by_id:
                continue
            v = pool_sources.trend_hunter_host_show(by_id[tid], vid)
            if isinstance(v, dict) and v.get("refused"):
                out[(tid, vid)] = v
    return out


def host_show_record(verdict):
    """One sieve record of a host show - Trend Hunter's shape (`reason_code:
    host_show`, the verdict with its signals under `host_show`), refused
    without reading its shots: what the upload is, not what is in it."""
    return {"verdict": REFUSED, "shots": 0, "decided": 0,
            "burned_text": 0, "burned_text_share": 0.0,
            "off_topic": 0, "off_topic_share": 0.0,
            "reason_code": HOST_SHOW_CODE, "examples": [],
            "burned_text_shots": [], "usability": None,
            "signals": list(verdict.get("signals") or []),
            HOST_SHOW_CODE: verdict, "judged_by": HOST_SHOW_CODE,
            "reason": verdict.get("reason") or "somebody else's host show (CF-0817)"}


def host_show_summary(report, sieved_sources):
    """CF-0817: the `host_show` part of the sieve block - the held sources
    this stage refused as a host show, the pool matches the indexer's pool
    check refused before they were counted (`pool_sources` block), and the
    counted pool sources whose pool entry had no title or uploader to judge
    (`host_show_unknown`: counted, said)."""
    pool = report.get(pool_sources.BLOCK_KEY) or {}
    at_pool = [{"topic_id": tid, "video_id": r.get("video_id"), "reason": r.get("reason")}
               for tid, b in (pool.get("topics") or {}).items()
               for r in b.get("sources") or ()
               if r.get("reason_code") == HOST_SHOW_CODE]
    held = {(tid, v) for tid, vids in (report.get("sources_by_topic") or {}).items()
            for v in vids or ()}
    unknown = [{"topic_id": f.get("topic_id"), "video_id": f.get("video_id"),
                "missing": f.get(pool_sources.HOST_SHOW_UNKNOWN)}
               for f in report.get("fetched") or []
               if f.get(pool_sources.HOST_SHOW_UNKNOWN)
               and (f.get("topic_id"), f.get("video_id")) in held]
    return {"rule": "CF-0817",
            "refused": [r["video_id"] for r in sieved_sources
                        if r.get("reason_code") == HOST_SHOW_CODE],
            "refused_at_pool": at_pool,
            pool_sources.HOST_SHOW_UNKNOWN: len(unknown),
            "unknown": unknown}


def sieve_report(report, cache=None, burned_share=BURNED_TEXT_SHARE,
                 off_topic_share=OFF_TOPIC_SHARE, load=None, titles=None,
                 only=None, topics=None):
    """Judge every canonical source of a loaded `01b-footage-index.json`.

    CF-0456: `only` (a set of topic ids, `--only-topics`) limits the judging
    to those topics; the others are not read at all.

    Pure: reads indexes, changes nothing. Returns
    `{"sources": [record, ...], "refused": {topic_id: [record, ...]}}`, with
    `video_id`/`topic_id` on every record and the records in the report's own
    topic order, so that two runs over one batch read the same.

    `titles` is `{video_id: title}` (Trend Hunter's candidate records,
    `candidate_titles()`), read only for the CF-0451 cam words.

    CF-0817: `topics` (`01-trend-hunter.json`) for the host-show guard - a
    held source Trend Hunter's candidate record or the pool check marks as
    somebody else's host show is refused with `reason_code: host_show`
    before its shots are read (`host_show_refusals()`); the result's
    `host_show` is the block's summary (`host_show_summary()`).
    """
    titles = titles or {}
    load = load or (lambda vid: read_index(vid, cache))
    entities = supplement_entities(report)
    hosts = host_show_refusals(report, topics)
    sources, refused = [], {}
    for tid, vids in (report.get("sources_by_topic") or {}).items():
        if only is not None and tid not in only:
            continue
        for vid in vids or []:
            if ingest_batch.is_own_capture(vid):
                # CF-0567: our own recording is the topic's footage by
                # construction - no sieve (root docs/tech-footage.md, FI step).
                rec = {"video_id": vid, "topic_id": tid, **own_capture_kept(load(vid))}
                sources.append(rec)
                continue
            if (tid, vid) in hosts:
                rec = {"video_id": vid, "topic_id": tid,
                       **host_show_record(hosts[(tid, vid)])}
                sources.append(rec)
                refused.setdefault(tid, []).append(rec)
                continue
            index = load(vid)
            if index is None:
                rec = {"verdict": UNSIEVED, "shots": 0, "decided": 0,
                       "burned_text": 0, "burned_text_share": 0.0,
                       "off_topic": 0, "off_topic_share": 0.0,
                       "reason_code": None, "examples": [],
                       "burned_text_shots": [], "usability": None,
                       "reason": "no readable index for this source, so there "
                                 "is nothing to sieve (CF-0281 owns that case)"}
            else:
                rec = judge(index, burned_share, off_topic_share,
                            entity=entities.get((tid, vid)),
                            title=titles.get(vid))
            rec = {"video_id": vid, "topic_id": tid, **rec}
            sources.append(rec)
            if rec["verdict"] == REFUSED:
                refused.setdefault(tid, []).append(rec)
    return {"sources": sources, "refused": refused,
            HOST_SHOW_CODE: host_show_summary(report, sources)}


OWN_CAPTURE_REASON = ("an own capture (CF-0567): the factory's own recording of the "
                      "tool the topic is about - kept by its kind, not sieved")


def own_capture_kept(index):
    """CF-0567: the sieve's record of an own capture - `kept`, by its kind,
    whatever the describer answered (or did not answer) on its shots."""
    shots = (index.get("shots") if isinstance(index, dict) else index) or []
    shots = [s for s in shots if isinstance(s, dict)]
    return {"verdict": KEPT, "shots": len(shots), "decided": 0,
            "burned_text": 0, "burned_text_share": 0.0,
            "off_topic": 0, "off_topic_share": 0.0,
            "reason_code": None, "examples": [], "burned_text_shots": [],
            "usability": shot_usability.summary(shots) if shots else None,
            "screen_recording": None, "judged_by": "own_capture",
            "reason": OWN_CAPTURE_REASON}


def candidate_titles(topics):
    """`{video_id: title}` over the topics of `01-trend-hunter.json`
    (`evidence.footage_candidates[].title`); empty for a batch without them."""
    out = {}
    for t in topics or []:
        for vid, rec in ingest_batch.candidate_records(t).items():
            if isinstance(rec.get("title"), str) and rec["title"]:
                out.setdefault(vid, rec["title"])
    return out


SCREEN_LINE = ("SIEVE screen_recording (CF-0451): {vid} ({tid}) - {detail}. "
               "{mode}")
SCREEN_WARN_MODE = ("A warning, the shots stay in the pool: no signed price "
                    "for it yet (CF-0320).")


def screen_warnings(report, sieved, log=print, rule_mode=None):
    """Rebuild this stage's `screen_recording` entries of `warnings[]` from
    the sieve's records, in place (idempotent - a second sieve pass never
    doubles them). Only the sources the report still holds: a refused one is
    gone anyway. Returns the entries written."""
    rule_mode = rule_mode or screen_recording.mode()
    keep = [w for w in report.get(ingest_batch.WARNINGS_FIELD) or []
            if not (isinstance(w, dict) and w.get("stage") == STAGE_NAME
                    and w.get("gate") == screen_recording.WARN_GATE)]
    held = {(tid, v) for tid, vids in (report.get("sources_by_topic") or {}).items()
            for v in vids or []}
    new = []
    for rec in sieved.get("sources") or []:
        if rec.get("verdict") == REFUSED:
            continue
        if (rec.get("topic_id"), rec.get("video_id")) not in held:
            continue
        w = screen_recording.warning(rec.get("topic_id"), rec.get("video_id"),
                                     rec.get("screen_recording"), STAGE_NAME,
                                     rule_mode=rule_mode)
        if w:
            new.append(w)
            log(SCREEN_LINE.format(
                vid=w["video_id"], tid=w["topic_id"], detail=w["detail"],
                mode=(SCREEN_WARN_MODE if w["mode"] == screen_recording.MODE_WARN
                      else f"Signed `{w['price_key']}` ({w['mode']}).")))
    report[ingest_batch.WARNINGS_FIELD] = keep + new
    return new


def failed_record(rec):
    """One refused source in the shape of `failed[]` - the same list a
    download YouTube refused and an index that did not finish land in, told
    apart by `reason_code` (CF-0253/CF-0281/CF-0299)."""
    return {
        "video_id": rec["video_id"],
        "topic_id": rec["topic_id"],
        "error": rec["reason"],
        "reason_code": rec["reason_code"],
        "refused_at": ingest_batch.RUNG_SIEVE,
        "attempts": [{"rung": ingest_batch.RUNG_SIEVE,
                      "error": rec["reason"]}],
    }


def sieve_block(sieved, burned_share, off_topic_share, settled=None):
    """The report's own `source_sieve` block. Always written, even when it
    refused nothing: "the sieve cleared this batch" and "nobody sieved it"
    must not read the same, for the reason `compliance_gate` lists its three
    codes when they are empty.

    CF-0456: `settled` is the `burned_settled` marks - the topics a run of the
    sieve already walked for their burned-text shots - carried from run to
    run so the next one does not walk them again."""
    return {
        "ran": True,
        SETTLED_KEY: dict(settled or {}),
        "thresholds": {"burned_text_share": burned_share,
                       "off_topic_share": off_topic_share},
        "sources": sieved["sources"],
        "refused": [r["video_id"] for recs in sieved["refused"].values()
                    for r in recs],
        "unsieved": [s["video_id"] for s in sieved["sources"]
                     if s["verdict"] == UNSIEVED],
        # CF-0817: somebody else's host show - refused here, refused at the
        # pool, and the counted pool sources nobody could call one.
        HOST_SHOW_CODE: sieved.get(HOST_SHOW_CODE) or {
            "rule": "CF-0817", "refused": [], "refused_at_pool": [],
            pool_sources.HOST_SHOW_UNKNOWN: 0, "unknown": []},
        "note": "CF-0299, step 2 of the footage-origin sieve. After the "
                "description pass, a source is refused whole when a majority "
                "of its shots are flagged `on_topic: false` (`source_foreign`: "
                "somebody else's film, the hard list's "
                "`score.hard.foreign_work_footage`). CF-0435: a majority of "
                "`burned_text: true` no longer refuses the source - those "
                "shots stay out one by one (`burned_text_shots` on the record) "
                "and the rest stay in the pool, weak shots included "
                "(`usability` on the record: clean / weak / hard). Both are the "
                "describer's answers, not a measurement: "
                "`usable_cached.text_outside_crop` reads 0.60 on the good Ted "
                "Lasso source and 0.00 on the interview Short the frame judge "
                "rejected a render over. The refused ids are in `failed[]` "
                "with `refused_at: sieve`, out of `fetched` and out of "
                "`sources_by_topic`, so the CF-0129 floor counts only what "
                "survived. `unsieved` is not a verdict: those sources carry "
                "the flags on some of their shots and have not been judged. "
                "CF-0344: a thin-pool supplement source (`supplement.entity` "
                "on its `fetched[]` record) is judged by its entity - a shot "
                "counts off topic only when it is neither the topic's work nor "
                "shows the entity; its record says `judged_by: entity`.",
    }


def prior_state(report, tid):
    """What topic `tid` already spent in the pass that wrote `report`.

    `tried` is every id that pass touched for this topic - its sources, its
    aliases, its losses - and `attempts` their number: the CF-0129 cap counts
    videos a topic touches across the batch, not per invocation, so a second
    pass may not hand any of them back.
    """
    tried = []
    for vid in (report.get("sources_by_topic") or {}).get(tid) or []:
        tried.append(vid)
    for a in report.get("aliases") or []:
        if a.get("topic_id") == tid and a.get("video_id") not in tried:
            tried.append(a["video_id"])
    for f in report.get("failed") or []:
        if f.get("topic_id") == tid and f.get("video_id") not in tried:
            tried.append(f["video_id"])
    return {"tried": tried, "attempts": len(tried)}


def held_sources(report, tid, refused_ids, cache=None):
    """`(video_id, path)` for the sources topic `tid` keeps after the sieve,
    taken from `fetched` so the paths are the ones the first pass recorded."""
    out = []
    for f in report.get("fetched") or []:
        if f.get("topic_id") != tid or f.get("video_id") in refused_ids:
            continue
        path = f.get("path") or str(index_path(f["video_id"], cache)).replace(
            ".shots.json", ".mp4")
        out.append((f["video_id"], path))
    return out


def merge_depths(report, fresh, floor):
    """The amended report's `pool_depth` block.

    A topic this pass re-walked has a new record; every other topic keeps the
    one the first pass wrote, because nothing about its pool changed. Merged
    rather than replaced for exactly that reason - `apply_sieve` only calls
    `ingest()` for the topics that lost a source, so a rebuilt-from-scratch
    block would forget every pool the sieve did not touch.
    """
    by_id = {r["topic_id"]: r
             for r in ((report.get("pool_depth") or {}).get("topics") or [])}
    for r in fresh:
        by_id[r["topic_id"]] = r
    return pool_depth.pool_depth_report(list(by_id.values()), floor)


THINNED_LINE = ("SIEVE {tid} keeps its sources, but their burned-text shots "
                "stay out one by one (CF-0435) and the pool is under the "
                "{floor}-shot depth floor - it takes its next candidate")
# CF-0456: a topic the sieve already walked for its burned-text shots is
# settled and is not walked again by the next run - the mark is the topic's
# burned-shot count per source at the time of the walk, kept in the report's
# `source_sieve` block under this key. Before it, every run of the sieve
# re-walked every topic with burned shots under the depth floor (the counts
# were on the records, "we already walked it" was nowhere): on the
# 2026-09-30T1248Z repeat that re-downloaded NvKt1-z08do for
# lf-2026-09-27-001 - a topic the batch had lost at `scripts` and replaced
# from the reserve - and the step's 30-minute ceiling killed the run.
SETTLED_KEY = "burned_settled"
# `walk_started` is written to the report on disk before the download
# (`apply_sieve(on_walk=...)`), so a walk the ceiling kills is settled too -
# the same topic walked again by the next run is the same half-hour lost again.
SETTLED_OUTCOMES = ("walked", "walk_started", "deep_enough")
SETTLED_LINE = ("SIEVE {tid} was walked for its burned-text shots by an "
                "earlier run ({outcome}) and none of its sources gained one "
                "since - settled, not walked again (CF-0456)")
OUT_OF_WORK_LINE = ("SIEVE {tid} is no longer worked on by this batch "
                    "({why}) - not topped up (CF-0456)")


def burned_counts(sieved, tid):
    """`{video_id: burned-text shots}` over the kept sources of topic `tid`."""
    return {rec["video_id"]: len(rec.get("burned_text_shots") or [])
            for rec in sieved["sources"]
            if rec["topic_id"] == tid and rec["verdict"] == KEPT}


def prior_settled(report):
    """The settled marks an earlier run of the sieve left on `report`."""
    block = report.get("source_sieve")
    marks = block.get(SETTLED_KEY) if isinstance(block, dict) else None
    return dict(marks) if isinstance(marks, dict) else {}


def is_settled(mark, counts):
    """Whether `mark` (a `burned_settled` entry) still covers `counts`.

    Settled when an earlier run walked (or found deep enough) this topic and
    no source of it carries more burned-text shots now than it did then. A
    source described since with burned shots of its own is news, and the topic
    may be walked once more for it - inside the same CF-0129 attempt cap."""
    if not isinstance(mark, dict) or mark.get("outcome") not in SETTLED_OUTCOMES:
        return False
    seen = mark.get("sources") or {}
    return all(n <= int(seen.get(vid, 0)) for vid, n in counts.items())


def settled_mark(counts, outcome):
    return {"task": "CF-0456", "outcome": outcome,
            "burned_text_shots": sum(counts.values()),
            "sources": dict(counts)}


def out_of_work(report, batch=None):
    """`{topic_id: why}` - the topics this batch no longer works on.

    A topic Content Researcher refused (`03-content-researcher.json`
    `skipped[]`, read by `ingest_batch.researcher_refusals()`) and a topic
    whose slot the reserve took (`01b reserve_substitution.substitutions[]
    .replaced`) is gone from the batch: no script will be written from its
    pool, so walking it for a source or for depth is a download for nobody
    (CF-0456). Without `batch` only the report is read.
    """
    out = {}
    subs = report.get(ingest_batch.SUBSTITUTION_KEY) or {}
    for s in subs.get("substitutions") or ():
        tid = s.get("replaced") if isinstance(s, dict) else None
        if tid:
            out[tid] = (f"its slot went to {s.get('topic_id')} from the "
                        f"reserve, lost at {s.get('replaced_stage')} with "
                        f"{s.get('replaced_reason_code')}")
    if batch is not None:
        refusals, _ = ingest_batch.researcher_refusals(batch)
        for r in refusals:
            out.setdefault(r["topic_id"],
                           f"refused at {r['stage']} with {r['reason_code']}")
    return out


def keep_other_topics(block, prior, only):
    """`--only-topics` (CF-0456): the block this run wrote covers only the
    named topics, so every other topic's records - its `sources[]` entries,
    its refused and unsieved ids - are carried over from the block the
    earlier run left. Returns `block`, amended in place."""
    if not isinstance(prior, dict):
        return block
    theirs = [s for s in prior.get("sources") or ()
              if isinstance(s, dict) and s.get("topic_id") not in only]
    ids = {s.get("video_id") for s in theirs}
    block["sources"] = theirs + list(block.get("sources") or ())
    for key in ("refused", "unsieved"):
        block[key] = ([v for v in prior.get(key) or () if v in ids]
                      + [v for v in block.get(key) or () if v not in ids])
    return block


def persist_walk(batch, tid, mark):
    """Put one `burned_settled` mark into the `01b` on disk (CF-0456).

    Called before a burned topic's download: the report in hand is half
    amended and is not written until the run ends, so only the mark goes into
    the file as it stands. A run killed by a ceiling inside that walk leaves
    the mark behind and the next run does not walk the topic again. Never
    raises - a mark that cannot be written costs one repeated walk, not the
    run."""
    try:
        dest = Path(batch) / REPORT_FILE
        disk = json.loads(dest.read_text())
        block = disk.get("source_sieve")
        if not isinstance(block, dict):
            block = disk["source_sieve"] = {}
        marks = block.get(SETTLED_KEY)
        if not isinstance(marks, dict):
            marks = block[SETTLED_KEY] = {}
        marks[tid] = mark
        ingest_batch.write_report(batch, disk)
    except Exception as e:              # noqa: BLE001 - see the docstring
        print(f"SIEVE {tid}: the walk mark was not written ({e}) - a run "
              f"killed inside this walk will walk it again", file=sys.stderr)


STAMP_LINE = ("SIEVE usability (CF-0435): {n} index(es) of this batch's kept "
              "sources stamped with shot.usability - {weak} weak shot(s) stay "
              "in the pool at a cost, {hard} out (black, empty, burned text)")


def stamp_usability(report, cache=None, log=print):
    """Write `shot.usability` on every shot of the kept sources this batch
    fetched itself (CF-0435).

    Only the sources in `sources_by_topic` whose `fetched[]` record is not
    `from_pool` (CF-0325): the pool's old sources are judged on the fly by
    `shot_usability.of()` and not written again (the pool is transient,
    CF-0358/CF-0410). Runs after the description pass, so the stamp carries the
    describer's `on_topic`/`burned_text` beside the measurements. Nothing is
    re-measured. Never raises: an index that cannot be read or written is
    skipped - the stamp is a convenience for readers outside this repo, the
    same record `shot_usability.of()` derives. Returns the block the report
    carries under `source_sieve.usability`.
    """
    kept = {v for vids in (report.get("sources_by_topic") or {}).values()
            for v in vids or []}
    own = [f["video_id"] for f in report.get("fetched") or []
           if f.get("video_id") in kept and not f.get("from_pool")]
    stamped, weak, hard, errors = [], 0, 0, []
    for vid in dict.fromkeys(own):
        path = index_path(vid, cache)
        try:
            data = json.loads(path.read_text())
            changed = shot_usability.stamp_index(data)
            summ = shot_usability.summary(data.get("shots") or [])
            weak += summ["weak"]
            hard += summ["hard"]
            if changed:
                shot_schema.write_index(path, data)
                stamped.append(vid)
        except Exception as e:          # noqa: BLE001 - see the docstring
            errors.append(f"{vid}: {type(e).__name__}: {e}")
    if own:
        log(STAMP_LINE.format(n=len(stamped), weak=weak, hard=hard))
    return {"task": shot_usability.TASK, "stamped": stamped,
            "weak_shots": weak, "hard_shots": hard, "errors": errors}


def apply_sieve(report, topics, verdict, sieved, wanted=ingest_batch.SOURCES_WANTED,
                max_attempts=ingest_batch.MAX_ATTEMPTS_PER_TOPIC,
                top_up=True, cache=None, log=print,
                burned_share=BURNED_TEXT_SHARE,
                off_topic_share=OFF_TOPIC_SHARE,
                depth_floor=pool_depth.POOL_DEPTH_FLOOR, dropped=None,
                on_walk=None, **ingest_kwargs):
    """Take the refused sources out of `report` and re-settle the topics.

    The whole of step 3 is here, and none of it is new arithmetic: for every
    topic that lost a source, `ingest_batch.ingest()` is run again over that
    topic alone, holding the sources it keeps (`already`), barred from ever
    registering the refused ones again (`barred`), and starting from the
    attempts the first pass spent (`prior`). So the topic takes its next
    candidate inside the same four-attempt cap if it has one, and is refused
    by the one piece of code that has always written that refusal if it does
    not - carrying `sieved` so the refusal names the source that was taken and
    what was seen in it.

    `top_up=False` does everything but the walk: the counts, the records and
    the refusals, with no download. Returns the amended report.

    CF-0304: a source taken out is a pool made shallower, so "the topic that
    lost something" is now settled against the depth floor as well as the
    source count. A topic left with its two sources and a pool under
    `depth_floor` is re-walked exactly like one left under the count - the walk
    inside `ingest()` asks the same question this stage's first pass asked, so
    the sieve's top-up and the first pass cannot disagree about what a deep
    enough pool is. It is still never refused for depth.

    CF-0456: two kinds of topic are not walked at all. `dropped` is
    `{topic_id: why}` of the topics the batch no longer works on
    (`out_of_work()`; by default read from the report alone - the reserve's
    `replaced` topics): their refused sources still leave the counts, nothing
    is fetched for them. And a topic with burned-text shots that an earlier
    run already walked or found deep enough (`source_sieve.burned_settled`,
    `is_settled()`) is settled. Every burned topic this run decides is marked
    there; `on_walk(tid, mark)` is called with a `walk_started` mark before a
    burned topic's walk, so a caller can put it on disk before the download
    (`main()` does) and a walk killed by a ceiling is not repeated.
    """
    if dropped is None:
        dropped = out_of_work(report)
    settled = prior_settled(report)
    # CF-0307: a topic this batch took out of the reserve is a topic of the
    # batch, and the only record of that is the report in hand - the compliance
    # artifact `verdict` was read from still has it in `reserve[]`. Promoted
    # here, before any walk, or the top-up below would call `ingest()` for a
    # substitute and be answered `reserve_unused` before the first download.
    verdict = ingest_batch.promoted(report, verdict)
    refused_by_topic = sieved["refused"]
    refused_ids = {r["video_id"] for recs in refused_by_topic.values()
                   for r in recs}
    # CF-0435: a kept source's burned-text shots stay out one by one, so a
    # topic can lose depth at the sieve without losing a source - the first
    # pass counted those shots before anybody had flagged them. Such a topic
    # is settled against the depth floor exactly like one that lost a source.
    burned_topics = [
        rec["topic_id"] for rec in sieved["sources"]
        if rec["verdict"] == KEPT and rec.get("burned_text_shots")
        and rec["topic_id"] not in refused_by_topic]
    burned_topics = list(dict.fromkeys(burned_topics)) if depth_floor else []
    # CF-0456: a topic out of the batch's work, or one an earlier run already
    # walked for these same burned shots, is not the sieve's to walk again.
    burned_topics = [tid for tid in burned_topics if tid not in dropped]
    for tid in list(burned_topics):
        mark = settled.get(tid)
        if is_settled(mark, burned_counts(sieved, tid)):
            log(SETTLED_LINE.format(tid=tid, outcome=mark["outcome"]))
            burned_topics.remove(tid)
    if not refused_ids and not burned_topics:
        report["source_sieve"] = sieve_block(sieved, burned_share,
                                             off_topic_share, settled)
        return report
    # A screening is remembered by (path, mtime, size); a top-up writes new
    # indexes into the same directory inside one run, so the memo is dropped
    # here rather than trusted across a pass that changes the pool.
    pool_depth.forget()

    ib_topic_skip = ingest_batch.topic_skip
    by_id = {t["topic_id"]: t for t in topics}
    for tid, recs in refused_by_topic.items():
        for r in recs:
            log(SIEVE_LINE.format(vid=r["video_id"], tid=tid, reason=r["reason"]))

    # Out of the two places a source counts, and into the one a loss counts.
    report["sources_by_topic"] = {
        tid: [v for v in vids or [] if v not in refused_ids]
        for tid, vids in (report.get("sources_by_topic") or {}).items()}
    report["fetched"] = [f for f in report.get("fetched") or []
                         if f.get("video_id") not in refused_ids]
    # CF-0308: what earlier passes lost, per topic - read by the refusal of a
    # topic that ends with nothing, so its code is the whole loss's.
    earlier = {}
    for f in report.get("failed") or []:
        if f.get("video_id") not in refused_ids:
            earlier.setdefault(f.get("topic_id"), []).append(f)
    report["failed"] = list(report.get("failed") or []) + [
        failed_record(r) for recs in refused_by_topic.values() for r in recs]

    # The topics that lost something and are not whole again by themselves.
    # Under the source count (CF-0129), or at the count and under the depth
    # floor (CF-0304) - a topic that is both is left exactly as it was: no
    # walk, no record, nothing to re-decide.
    def unsettled(tid):
        held = report["sources_by_topic"].get(tid) or []
        if len(held) < wanted:
            return True
        if not depth_floor:
            return False
        return not pool_depth.deep_enough(
            pool_depth.topic_depth(tid, held, cache=cache), depth_floor)

    short = [tid for tid in refused_by_topic if unsettled(tid)]
    for tid in [t for t in short if t in dropped]:
        log(OUT_OF_WORK_LINE.format(tid=tid, why=dropped[tid]))
        short.remove(tid)
    thinned = [tid for tid in burned_topics if unsettled(tid)]
    for tid in burned_topics:
        if tid not in thinned:
            settled[tid] = settled_mark(burned_counts(sieved, tid),
                                        "deep_enough")
    for tid in thinned:
        log(THINNED_LINE.format(tid=tid, floor=depth_floor))
    short += thinned
    fresh_depths = []
    report["skipped_topics"] = [
        s for s in report.get("skipped_topics") or []
        if s.get("topic_id") not in short]
    for tid in short:
        topic = by_id.get(tid)
        if topic is None:
            # The two artifacts disagree: the report holds a topic
            # `01-trend-hunter.json` does not. There is no candidate list to
            # walk, and a topic that quietly loses a source is the one thing
            # this stage may not do - so it is refused, by name.
            report["skipped_topics"].append(ib_topic_skip(
                tid, ingest_batch.TOPIC_REFUSAL_CODE,
                f"{len(report['sources_by_topic'].get(tid) or [])} source(s) "
                f"left after the sieve, floor is {wanted} (CF-0129/CF-0299), "
                f"and no candidate could be taken in place of the refused "
                f"one: this topic is in 01b-footage-index.json and not in "
                f"01-trend-hunter.json, so the stage has no candidate list "
                f"for it. Taken by the sieve: "
                + "; ".join(f"{r['video_id']} - {r['reason']}"
                            for r in refused_by_topic.get(tid) or [])))
            continue
        prior = prior_state(report, tid)
        left = max(0, max_attempts - prior["attempts"])
        if top_up and left:
            log(TOPUP_LINE.format(tid=tid, wanted=wanted, left=left))
        # CF-0456: a burned topic's walk is marked before the download, so a
        # run killed inside it does not leave the next run the same walk.
        walked = tid in thinned and top_up
        if walked and on_walk is not None:
            on_walk(tid, settled_mark(burned_counts(sieved, tid),
                                      "walk_started"))
        got, aliases, skipped, failed, by_topic = ingest_batch.ingest(
            [topic], verdict, Path(report.get("batch") or "").name,
            max_per_topic=max_attempts if top_up else prior["attempts"],
            wanted=wanted, log=log,
            prior={tid: prior},
            barred={tid: sorted(refused_ids
                                & {r["video_id"]
                                   for r in refused_by_topic.get(tid) or []})},
            already={tid: held_sources(report, tid, refused_ids, cache)},
            sieved={tid: [{"video_id": r["video_id"],
                           "reason_code": r["reason_code"],
                           "reason": r["reason"]}
                          for r in refused_by_topic.get(tid) or []]},
            earlier={tid: earlier.get(tid) or []},
            # CF-0304: the same floor and the same index directory the first
            # pass used, so the sieve's top-up and the walk that wrote this
            # report cannot disagree about what a deep enough pool is.
            depth_floor=depth_floor, depth_cache=cache, depths=fresh_depths,
            **ingest_kwargs)
        # Only what this pass added. The sources the topic kept were handed
        # to `ingest()` as `already`, so they come back in `by_topic` and are
        # already in the report - appending them again would double a floor.
        new = [v for v in (by_topic.get(tid) or [])
               if v not in (report["sources_by_topic"].get(tid) or [])]
        report["sources_by_topic"].setdefault(tid, []).extend(new)
        report["fetched"].extend(f for f in got if f.get("video_id") in new)
        report["aliases"] = list(report.get("aliases") or []) + list(aliases)
        report["failed"].extend(failed)
        report["skipped_topics"].extend(skipped)
        if walked:
            settled[tid] = settled_mark(burned_counts(sieved, tid), "walked")

    report["source_sieve"] = sieve_block(sieved, burned_share, off_topic_share,
                                         settled)
    report["two_source_floor"] = ingest_batch.two_source_report(
        report["skipped_topics"], wanted, max_attempts)
    # CF-0304: the depth the re-walked topics ended with, over the depths the
    # first pass recorded for everyone else.
    report["pool_depth"] = merge_depths(report, fresh_depths, depth_floor)
    report["dedup_log"] = [ingest_batch.alias_line(a)
                           for a in report.get("aliases") or []]
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("batch")
    p.add_argument("--dry-run", action="store_true",
                   help="judge and print, write nothing and fetch nothing")
    p.add_argument("--no-top-up", action="store_true",
                   help="do not let a topic take its next candidate; record "
                        "the refusal as it stands")
    p.add_argument("--sources-wanted", type=int,
                   default=ingest_batch.SOURCES_WANTED)
    p.add_argument("--max-per-topic", type=int,
                   default=ingest_batch.MAX_ATTEMPTS_PER_TOPIC)
    p.add_argument("--pool-depth-floor", type=int,
                   default=pool_depth.POOL_DEPTH_FLOOR,
                   help="CF-0304: a topic left by the sieve at the source "
                        "count but under this many usable shots takes its next "
                        "candidate too; 0 turns the question off")
    p.add_argument("--no-reserve", action="store_true",
                   help="CF-0306: do not refill a slot the sieve emptied from "
                        "02-compliance-checker.json reserve[]")
    p.add_argument("--no-backfill", action="store_true",
                   help="CF-0359: do not answer the open sieve flags of this "
                        "batch's sources before judging them. An unanswered "
                        "source then stays `unsieved` and the script exits "
                        f"{UNSIEVED_EXIT}, as it did before this task")
    p.add_argument("--backfill-out",
                   help="where the backfill's sheets, questions and answers go "
                        f"(default <batch>/{BACKFILL_DIR})")
    p.add_argument("--answer-cmd",
                   help="CF-0359: the command that answers one source's sheet "
                        "(the frame subagent); see backfill_sieve_flags.py "
                        f"batch. One run only - the setting is "
                        f"{ANSWER_FROM_CONFIG} (CF-0374), then "
                        f"${backfill.ANSWER_CMD_ENV}, and with none of the "
                        "three, the answers already in --backfill-out")
    p.add_argument("--answer-timeout", type=int,
                   default=backfill.ANSWER_TIMEOUT_SECONDS,
                   help="ceiling on one source's answerer, seconds; over it "
                        "the source counts as unanswered and is refused. "
                        f"Passed, it wins over {ANSWER_CMD_KEY}."
                        f"{ANSWER_TIMEOUT_FIELD} (CF-0374)")
    p.add_argument("--no-second-source", "--two-source-gate",
                   dest="no_second_source", choices=ingest_batch.FLOOR_MODES,
                   default=None,
                   help=f"CF-0419: override {ingest_batch.FLOOR_RULE} for this "
                        "run (else the channel's key, else its "
                        "video_editor.two_source_gate, else `warn`). "
                        "`warn`/`measure`/`off` keep a topic holding one kept "
                        "source (a warning in warnings[]), `enforce`/`fail`/"
                        "`refuse` refuse it with no_second_source; a topic "
                        "with no source is refused in every mode. "
                        "`--two-source-gate` is the CF-0362 spelling")
    p.add_argument("--only-topics",
                   help="CF-0456: comma-separated topic ids - judge, answer "
                        "and walk only these topics; every other topic's "
                        "sieve records are kept as the last run wrote them")
    args = p.parse_args(argv)

    batch = Path(args.batch)
    dest = batch / REPORT_FILE
    if not dest.exists():
        sys.exit(f"no {REPORT_FILE} in {batch} - the sieve runs after "
                 f"ingest_batch.py and after the description pass")
    report = json.load(open(dest))
    only = None
    if args.only_topics:
        only = {t.strip() for t in args.only_topics.split(",") if t.strip()}
        known = set(report.get("sources_by_topic") or {})
        if not only & known:
            sys.exit(f"--only-topics names no topic of {REPORT_FILE}: "
                     f"{', '.join(sorted(only))}")
        for t in sorted(only - known):
            print(f"SIEVE --only-topics: {t} is not in {REPORT_FILE}, "
                  f"nothing to sieve for it", file=sys.stderr)
    prior_block = report.get("source_sieve")
    th = batch / "01-trend-hunter.json"
    topics = json.load(open(th))["topics"] if th.exists() else []

    # CF-0362 / CF-0419: the floor's mode - the flag, else the channel's
    # `footage_indexer.no_second_source`, else its `video_editor.two_source_gate`,
    # else `warn` (`ingest_batch.floor_mode()`, the one read of it).
    channel = ingest_batch.resolve_channel(batch.resolve().parent.name)
    gate_mode, gate_from = ingest_batch.floor_mode(
        channel, flag=args.no_second_source)
    # CF-0689: which topics stand on the channel's own graphics - read here,
    # so every apply_floor_mode below (the dry run's preview included) keeps
    # them instead of refusing them below the source floor.
    ingest_batch.mark_own_graphic(report, topics,
                                  ingest_batch.footage_origins(channel))
    # CF-0374: the answerer of this run - `--answer-cmd`, else the channel's
    # `footage_indexer.sieve_flags_answer_cmd`, else the environment, else
    # none. None is legal (the run goes on, DoD 1) and is said out loud below.
    answer = answerer(channel=channel, flag=args.answer_cmd,
                      timeout_flag=args.answer_timeout)
    titles = candidate_titles(topics)
    sieved = sieve_report(report, titles=titles, only=only, topics=topics)
    unanswered_before = [s["video_id"] for s in sieved["sources"]
                         if s["verdict"] == UNSIEVED]
    # CF-0359: the sources this batch took and nobody answered for are answered
    # here, before anything is decided about them - a reused old source is
    # marked on the spot instead of stopping the stage on UNSIEVED_EXIT. Then
    # the batch is judged again, with the answers in place, so the flags the
    # backfill wrote go through exactly the same arithmetic as a describer's.
    # Not under --dry-run, which writes nothing.
    if not args.no_backfill and not args.dry_run:
        report[BACKFILL_KEY] = run_backfill(
            report, batch, unanswered_before,
            out=args.backfill_out or (batch / BACKFILL_DIR),
            answer_cmd=answer["command"], timeout=answer["timeout"])
        # CF-0374: which setting the command came from, beside the command
        # itself - "there was no answerer" and "the answerer was the config's"
        # are different runs and the report must not read the same for both.
        report[BACKFILL_KEY]["answerer_from"] = answer["from"]
        if report[BACKFILL_KEY]["sources"]:
            sieved = sieve_report(report, titles=titles, only=only, topics=topics)
    # A source nothing could answer for is refused with a record, and the run
    # goes on (CF-0359, DoD 1). Only those the backfill actually tried and
    # failed on: with --no-backfill nothing is converted and the CF-0355 exit
    # code is still the insurance it was.
    taken_out = refuse_unanswered(sieved, report.get(BACKFILL_KEY))
    # CF-0374: how many sources this run marked on the spot and how many it
    # took out with a record, in the run summary - without it "the marking
    # works" and "there is no answerer, everything is being taken out" read the
    # same. The line is finished here and the root prints it verbatim
    # (CF-0368's contract); nothing is written under --dry-run.
    answers_line = answers_summary_line(
        report.get(BACKFILL_KEY), answerer=answer, taken=taken_out,
        off=args.no_backfill, asked=len(unanswered_before) if args.no_backfill
        else None)
    print(answers_line)
    if not args.dry_run:
        record_answers_event(batch, report.get(BACKFILL_KEY), answerer=answer,
                             taken=taken_out, off=args.no_backfill,
                             asked=len(unanswered_before) if args.no_backfill
                             else None)
    for s in sieved["sources"]:
        if s["verdict"] == UNSIEVED:
            print(UNSIEVED_LINE.format(vid=s["video_id"], tid=s["topic_id"],
                                       decided=s["decided"], shots=s["shots"]))
    if args.dry_run:
        if not args.no_backfill:
            print(BACKFILL_DRY_LINE.format(
                n=len(backfill.batch_queue(report, ingest_batch.CACHE))))
        report["source_sieve"] = sieve_block(sieved, BURNED_TEXT_SHARE,
                                             OFF_TOPIC_SHARE,
                                             prior_settled(report))
        for recs in sieved["refused"].values():
            for r in recs:
                print(SIEVE_LINE.format(vid=r["video_id"], tid=r["topic_id"],
                                        reason=r["reason"]))
        screen_warnings(json.loads(json.dumps(report)), sieved)
        print(f"{len(sieved['refused'])} topic(s) would lose "
              f"{len(report['source_sieve']['refused'])} source(s); "
              f"nothing was written (--dry-run)")
        # CF-0362: which refused-at-the-floor topics the channel's mode keeps.
        # Over the report as it stands (no top-up is simulated).
        preview = json.loads(json.dumps(report))
        for recs in sieved["refused"].values():
            for r in recs:
                preview["sources_by_topic"][r["topic_id"]] = [
                    v for v in preview["sources_by_topic"].get(r["topic_id"]) or []
                    if v != r["video_id"]]
        kept = ingest_batch.apply_floor_mode(preview, gate_mode,
                                             wanted=args.sources_wanted,
                                             whence=gate_from)
        print(f"{ingest_batch.FLOOR_RULE} `{gate_mode}` ({gate_from}): "
              f"{len(kept)} topic(s) would be "
              f"kept with a warning instead of no_second_source"
              + (": " + ", ".join(kept) if kept else ""))
        graphic = (preview.get("two_source_floor") or {}).get(
            "kept_on_own_graphics") or []
        if graphic:
            print(f"{len(graphic)} topic(s) would be "
                  f"{ingest_batch.OWN_GRAPHIC_KEPT_NOTE} (CF-0689): "
                  + ", ".join(graphic))
        return 0

    report = apply_sieve(report, topics, ingest_batch.verdicts(batch), sieved,
                         wanted=args.sources_wanted,
                         max_attempts=args.max_per_topic,
                         top_up=not args.no_top_up,
                         depth_floor=args.pool_depth_floor,
                         # CF-0456: the topics lost after Researcher are not
                         # walked, and a burned topic's walk is on disk
                         # before its download.
                         dropped=out_of_work(report, batch),
                         on_walk=lambda tid, mark: persist_walk(batch, tid, mark),
                         # CF-0302: the top-up walk takes the topic's next
                         # candidates, so it is held to the same duration
                         # ceiling the first pass was - read from the same
                         # channel config, through `**ingest_kwargs`.
                         ceiling=ingest_batch.duration_ceiling(
                             ingest_batch.resolve_channel(
                                 batch.resolve().parent.name)))
    if only is not None:
        keep_other_topics(report["source_sieve"], prior_block, only)
    # CF-0362: in `measure` a topic left with one kept source stays in the
    # batch with a warning - before the reserve, which must not refill a slot
    # that is not free. Runs whether or not this pass refused anything, so a
    # report written before CF-0362 is settled by a sieve run with no fetch.
    ingest_batch.apply_floor_mode(report, gate_mode, wanted=args.sources_wanted,
                                  whence=gate_from)
    # CF-0306: a topic the sieve leaves below the floor is a topic lost after
    # compliance, exactly like one the first pass refused, and its slot is
    # refilled from the reserve here - after the re-count, so the losses are
    # final. Not under `--no-top-up`: that flag says nothing is to be fetched,
    # and a substitute is a whole topic's worth of downloads.
    if not args.no_reserve and not args.no_top_up:
        channel = ingest_batch.resolve_channel(batch.resolve().parent.name)
        ingest_batch.substitute_reserve(
            report, topics, ingest_batch.verdicts(batch), at="sieve",
            wanted=args.sources_wanted, max_attempts=args.max_per_topic,
            depth_floor=args.pool_depth_floor,
            ceiling=ingest_batch.duration_ceiling(channel),
            floor=gate_mode)
        ingest_batch.apply_floor_mode(report, gate_mode,
                                      wanted=args.sources_wanted,
                                      whence=gate_from)
    # CF-0435: the kept sources this batch fetched carry their shots' usability
    # (score, soft and hard violations) for the readers outside this repo.
    if isinstance(report.get("source_sieve"), dict):
        report["source_sieve"]["usability"] = stamp_usability(report)
    # CF-0451: the cinema cam - one warning per kept source that holds shots
    # filmed off a screen or is titled like a cam copy. After every walk and
    # the reserve, so it reads the sources the batch actually keeps.
    screen_warnings(report, sieved)
    ingest_batch.write_report(batch, report)
    if report.get("aliases"):
        # A top-up may have found a re-upload of a source the topic kept, and
        # `work/footage-aliases.json` is written from the whole list, so it is
        # rewritten here rather than appended to.
        ingest_batch.write_aliases(batch, report["aliases"])

    block = report["source_sieve"]
    print(f"{len(block['refused'])} source(s) refused by the sieve, "
          f"{len(block['unsieved'])} unsieved -> {dest}")
    subs = report.get(ingest_batch.SUBSTITUTION_KEY) or {}
    if subs.get("substitutions"):
        print(f"  {len(subs['substitutions'])} slot(s) refilled from the "
              f"compliance reserve (CF-0306) - describe their sources and run "
              f"the sieve again: "
              + ", ".join(f"{s['topic_id']} for {s['replaced']}"
                          for s in subs["substitutions"]))
    if subs.get("unmatched"):
        print(f"  {len(subs['unmatched'])} slot(s) left empty, the reserve is "
              f"used up ({ingest_batch.RESERVE_EXHAUSTED_CODE}): "
              + ", ".join(u["replaced"] for u in subs["unmatched"]))
    warned = [w for w in report.get(ingest_batch.WARNINGS_FIELD) or []
              if w.get("stage") == STAGE_NAME]
    if warned:
        print(f"  {len(warned)} warning(s), the topics go on "
              f"({ingest_batch.FLOOR_RULE} `{gate_mode}` from {gate_from}, "
              f"CF-0419): "
              + ", ".join(f"{w['topic_id']} ({w['warning_code']})"
                          for w in warned))
    ingest_batch.print_own_graphic_kept(report)            # CF-0689
    refused_topics = [s for s in report.get("skipped_topics") or []
                      if s.get("reason_code") not in ingest_batch.PRE_FETCH_CODES]
    if refused_topics:
        print(f"  {len(refused_topics)} topic(s) refused below the "
              f"{args.sources_wanted}-source floor and must not be written: "
              + ", ".join(f"{s['topic_id']} ({s['reason_code']})"
                          for s in refused_topics))
    if block["unsieved"]:
        print(UNSIEVED_GATE_LINE.format(n=len(block["unsieved"]),
                                        ids=", ".join(block["unsieved"]),
                                        code=UNSIEVED_EXIT))
        return UNSIEVED_EXIT
    return 0


@runlog.script("footage-indexer", "sieve", name="source_sieve.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()

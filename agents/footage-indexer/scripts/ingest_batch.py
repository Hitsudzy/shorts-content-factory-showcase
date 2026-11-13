#!/usr/bin/env python3
"""Fetch and index the footage a batch's topics point at, before anything is written.

Trend Hunter has always recorded `evidence.youtube_video_ids` for every topic
and nothing ever read them. With acquisition moved ahead of writing, they are
the natural input: the batch already knows which videos the discussion is about.

Compliance verdicts no longer decide what is fetched (CF-0318). Until
2026-09-23 a topic at `review` was dropped here - "not signed off by a human" -
and the funnel's count over ten instrumented runs made that 19 of 101 losses,
in an autonomous run where no human was ever going to sign anything. The
user's ruling: without a human's approval only the *publication* of a video is
forbidden; the video itself is made without a human. So `review` is still
`review` - the legal reading is untouched - and this stage fetches its footage
like any other topic's. What the verdict blocks now lives elsewhere:
`agents/compliance-checker` writes a `publication_hold` onto the batch
artifact and a row into `publish/publication-holds.json`, and the Publisher is
what must refuse. Compliance still decides this stage's work in two other
ways, both about a slot rather than a verdict - unused reserve and a topic
nobody judged (CF-0265, below).

CF-0080: search returns re-uploads - the same trailer under three ids - and
every one of them used to be indexed from scratch (12 of 23 sources in batch
2026-09-03T2037Z, about half of a 3h19m window), while the source count lied
to every gate that counts sources. So each fetched file is fingerprinted
(source_fingerprint.py, a few seconds of ffmpeg) and compared with the
sources of the *same topic* that came before it; a match is not indexed but
recorded as an alias of the canonical id, in `aliases` of the report and in
`<batch>/work/footage-aliases.json`, with a `DEDUP <id> is a re-upload of
<id> (distance N)` line on stdout. `fetched` - the list Content Researcher
and Video Editor take their sources from - carries canonical ids only, so
downstream counts real footage. Never across topics: two topics that list the
same id share it by id already, and two different topics' trailers are never
compared. The alias's media stays in the cache; the LRU handles space.

CF-0464: the fingerprint compares whole frames, so an upload that was cropped
or pillarboxed passes it (you-can-see-everything, 2026-10-01T0200Z: one
trailer as `HvW_N5p1q44` and `jsw92T7KpqM`, distance 14.2 against 12.0, both
counted as sources). Once a source is indexed its shot list is compared with
the topic's held sources (`shot_copy.py`, CLIP embeddings aligned in order,
no decode); a copy is filed in `aliases` with `method: "shots"` and is no
source. The better copy (`shot_copy.keeper()`) keeps the topic's place - if
that is the newcomer it replaces the held one in `sources_by_topic` and
`fetched`, and the held one becomes the alias. Pool sources are checked the
same way; a source an earlier pass handed in (`already=`) is never replaced.

CF-0281: a source is a source only when its index was written. Until this task
`index_source()` ran `index_footage.py` through `subprocess.run()` and never
read the return code, so a crashed index was indistinguishable from a good
one: on batch 2026-09-18T1058Z `HEaXDIrGhS4` was killed twice at the indexer's
own 60 s ceiling and still went into `fetched`, into `sources_by_topic` and
into a per-source event that said `done` - the topic read as holding two
sources with one of them carrying no `shots.json` at all, and the stage
operator had to fetch a replacement by hand. Now the index is part of
admitting a source: an id whose index did not finish is not registered, is
recorded in `failed[]` (`reason_code: index_failed`, `refused_at: index`) and
in the report's `index_failures[]`, its per-source event says `failed`, and
the CF-0129 walk below goes on to the topic's next candidate by itself.

CF-0129: a topic with one source fails the two-source gate at the very end
of the batch, after a script, a TTS pass and an anchor resolve have been
spent on it - and the source count that gate reads is the one CF-0080
deduplication leaves, so "three uploads" can be one source. So this stage
does not simply take the first N ids: it walks the candidates Trend Hunter
ordered (`evidence.youtube_video_ids`, round-robin by nature of footage since
2026-09-16) until the topic holds SOURCES_WANTED canonical sources after
dedup, spending at most MAX_ATTEMPTS_PER_TOPIC attempts on it. A topic still
short of the floor when its walk has ended is refused here, with
`no_second_source` in `skipped_topics[]` for the CF-0232 funnel - it never
reaches the writer.

CF-0338: a topic whose pool the writer or the editor found too thin is not
left with empty blocks. The user's ruling (2026-09-23, `widows-bay`): "if they
talk about an actor's Emmy and the sources have no footage of the actor, find
his highlights and his other work and put them in". The search belongs to
Trend Hunter; this stage is the consumer of its answer - a *supplement
request* (`kind: thin_pool_supplement`, one topic, the entities of its
uncovered anchors and the candidates found for them), walked by the same
`ingest()` as any source and appended to the topic's pool in the report. See
`supplement_mode()`. CF-0429: `--deadline <epoch|iso>` bounds that call by
the wall clock - past it nothing new starts, what is in flight is killed, what
is downloaded and indexed is written, the rest is listed with `outcome:
wall_ceiling`, exit 0 (see the block above `parse_deadline()`).

CF-0325: what the pool already holds for a topic is counted before its walk.
Trend Hunter writes `topics[].pool.matched` (the sources of `shared/footage`
whose title names the topic); `pool_sources.vet()` checks each one is really
the topic's work - its media still cached, Trend Hunter's CF-0272 / CF-0309 /
CF-0297 checks and `other_installment` (`pool_work_check.py`, in Trend
Hunter's process), CF-0817's host show (somebody else's podcast, interview
or talk show - Trend Hunter's `host_show.judge()`, same process), the CF-0299
sieve - and `ingest(pooled=)` registers the
survivors as the topic's sources before a byte is fetched, so the source and
depth floors count them and the walk downloads only what is missing. The
report's `pool_sources` block says which were counted and which refused, and
why. `--no-pool` turns it off.

Usage:
    ingest_batch.py <batch-dir> [--max-per-topic 4] [--no-pool]
    ingest_batch.py <batch-dir> --supplement <request.json|dir> [...]
                    [--deadline <epoch|iso>]
"""
import argparse
import concurrent.futures
import contextlib
import copy
import itertools
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque, namedtuple
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import archive_source  # noqa: E402 - CF-0665: NASA / Commons files, their file ids
import own_capture_source  # noqa: E402 - CF-0567: ExampleTech's own screen recordings
import fetch_footage  # noqa: E402
import pool_depth  # noqa: E402 - CF-0304: how deep a topic's pool is, before a word is written
import pool_sources  # noqa: E402 - CF-0325: pool sources counted before any download
import shot_copy  # noqa: E402 - CF-0464: two indexed uploads of one video, by their shots
import shot_schema  # noqa: E402 - CF-0281: whether a shots.json is a finished index
import source_fingerprint  # noqa: E402
import source_rights  # noqa: E402 - CF-0663: the rights record of a source, the licence refusal
from _channel_ids import ROOT as FACTORY_ROOT  # noqa: E402 - CF-0197
from _channel_ids import channel_config_path, resolve_channel  # noqa: E402
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
from _fi_paths import pool_dir, venv_bin as _runlog_venv_bin  # noqa: E402 - CF-0267, CF-0620

VENV_PY = str(_runlog_venv_bin("python"))  # CF-0267: a worktree has no .venv of its own
CACHE = pool_dir()  # CF-0620: this checkout's factory (or FACTORY_ROOT), not the home checkout

ALIASES_FILE = "footage-aliases.json"   # under <batch>/work/
REPORT_FILE = "01b-footage-index.json"
DEDUP_LINE = "DEDUP {alias} is a re-upload of {canonical} (distance {distance})"
# CF-0464: the same verdict reached by the shot lists after both were indexed.
SHOT_COPY_LINE = ("DEDUP {alias} is a re-upload of {canonical} (shots: {share} of the "
                  "shorter source aligned, {matched} shots; distance {distance})")
# Fields an alias record carries only when CF-0464 decided it.
SHOT_COPY_FIELDS = ("method", "shot_share", "matched_shots", "copy_kind", "kept_by")

# ---------------------------------------------------------------------------
# Pacing and the refusal record
#
# A real download is followed by a short pause before the next one, so twenty
# sources arrive as twenty requests over a few minutes. A cache hit costs the
# source nothing and neither owes nor earns a pause.
#
# Every id the fetch refused is one record in `failed`, with `reason_code:
# fetch_failed` for the CF-0232 funnel, the attempt history, and a
# self-describing `error` sentence (the funnel copies it into its `detail`
# verbatim).
FETCH_PAUSE_SECONDS = (5.0, 10.0)
FUNNEL_REASON_CODE = "fetch_failed"     # CF-0232's code for a source not fetched

# The step an id was refused at, as it lands in `failed[].refused_at`.
RUNG_FIRST_PASS = "first_pass"

# ---------------------------------------------------------------------------
# A source whose index did not finish (CF-0281)
#
# `failed[]` is this report's list of ids the stage did not turn into a usable
# source, and until this task every record in it was a download YouTube
# refused. An id that came down and could not be indexed belongs in the same
# list - downstream the two are the same absence, a topic with no footage to
# cut - and `reason_code` tells them apart: `fetch_failed` is YouTube's
# refusal, `index_failed` is ours. `refused_at: index` says where in the stage
# it happened, beside the other steps.
#
# `skipped_topics[]` may now carry the same word: the CF-0232 funnel's
# vocabulary (shared/runlog/funnel.py FUNNEL_CODES) has `index_failed` in it,
# so it is no longer a code the funnel does not know. A topic left below the
# floor takes `no_second_source` when it still holds a source, `index_failed`
# when it holds none and every candidate was lost on indexing, and
# `fetch_failed` when any of the lost ones was a download YouTube refused -
# the same split the funnel's `two_sources` step makes by reading the
# `reason_code` written here. The `reason` says "downloaded but failed to
# index" in every case where that happened, so the record is never read as
# YouTube's fault even when the code is `fetch_failed`.
INDEX_FUNNEL_CODE = "index_failed"
RUNG_INDEX = "index"

# ---------------------------------------------------------------------------
# The index that went quiet (CF-0316)
#
# `example-film/2026-09-19T0116Z`: the last event of the run was
# `footage-indexer/index PEiDNOQ_0ms start` and the next one came 28h30m40s
# later. This seam is where that silence began - `_run_index()` ran
# `index_footage.py` through a bare `subprocess.run()`, off `runlog.run_child`
# and without a `timeout=`, so nothing in the factory was counting. Now the
# call goes through `runlog.run_child(..., on_timeout="code")`, which times the
# **silence** of the operation's own subtree and not its duration: an honest
# index writes ~3000 child events per source, so the 31-minute ceiling
# (`watchdog.SILENCE_CEILING_S`) cannot bite honest work of any length.
#
# What a kill costs, in the user's own decision (grill 2026-09-22, Q18): the
# **source**, and nothing above it. The run is never dropped; the stage takes
# the media off and walks to the topic's next candidate, and - like the CF-0302
# ceiling - the topic's CF-0129 attempt is **not** spent on it (`attempt_spent:
# False`), because an operation the factory itself took down says nothing about
# the video. The record keeps `reason_code: index_failed`: a kill is one of the
# ways an id came down and got no index, and that is the word the funnel's
# vocabulary knows.
#
# The watchdog's own outcome code (`index_timeout`, from
# `watchdog.outcome_code`) is kept beside it in `watchdog_code`, with how long
# the operation hung, and is carried into `index_failures[]`. It is deliberately
# **not** a `FUNNEL_CODES` word: by the rule of CF-0319 a kill is an авария -
# always a task for the post-run triage, never a number in the funnel.
# `scripts/_runlog.py` is left alone. Its rootless stand-in would have to learn
# the three new keyword arguments; when this was written a byte there staled
# the caption-band measurement of the whole pool (144 index(es), 4818 shots) -
# since CF-0387 it does not (`_runlog` is opaque to the caption key). Nothing
# is lost by leaving it: neither this script nor `index_footage.py`
# can even be imported without the factory root (`_channel_ids`, the Video
# Editor's scripts), so the stand-in is unreachable from either of them.
WATCHDOG_CODE_KEY = "watchdog_code"
WATCHDOG_STEP = "index"
WATCHDOG_TOOL = "index_footage.py"

# CF-0332: how many sources are indexed at once. Downloads stay one at a time
# (the pacing is about the source site, not about this machine); what runs side
# by side is `index_footage.py`, which is where the stage's machine time is.
# 1 is the pre-CF-0332 walk exactly - same order, same events, same process
# environment. Overridable per run with `--index-workers` or the environment
# variable below.
#
# Measured 2026-09-26 (`scripts/measure_source_parallelism.py`, 4 clips of 6 s
# cut from 4 pool sources, 10 shots, the same clips at every N, machine under
# a foreign load average of ~6 on 12 cores): N=1 353.8 s (the four indexed one
# by one), N=2 168.1 s (-52 %), N=4 113.4 s (-68 %). One index process peaks at
# 0.77 GB RSS, so 4 of them fit a 16 GB machine beside the shared Vision worker.
# The sample is short-source heavy and runs today's watchdog, whose 5 s poll
# pads every short call (see the task file) - the real gain on 34-shot sources
# will be smaller; Amdahl on the frozen runs after CF-0331 says about -45 %.
INDEX_WORKERS_ENV = "FOOTAGE_INDEX_WORKERS"
DEFAULT_INDEX_WORKERS = 4
# CF-0332 / CF-0058: with more than one index process, each worker slot may
# talk to a Vision worker of its own instead of queueing at the machine-wide
# one. Measured at N=4 on the same clips: 101.0 s against 113.4 s shared
# (-11 %), Vision time 97.7 s against 143.0 s (the rest is the queue). Off by
# default: a Vision worker grows to ~0.85 GB after a run, so four of them add
# ~2.5 GB on a 16 GB machine for a tenth of the wall. `--vision-per-worker`
# turns it on for a run; the switch below for good.
#
# CF-0843 (the user's decision of 2026-10-21, Q5, reversing the 14.10 "wait for
# Docker" of CF-0745): ON by default. The Reel batch of 21.10 had Vision busy
# 63 % of the main pass (131 min) and in flight 93 % of the time, the median
# text_regions call at 3.93 s in the queue against 0.31-0.39 s without one -
# the worker serves its connections one at a time. Rolled back without a code
# release by env FOOTAGE_VISION_PER_WORKER=0 (the schedule starts the batch, so
# the environment is the switch nobody has to edit code for) or by
# `--no-vision-per-worker`; the flag wins over the env, the env over the
# constant. Each extra Vision worker is ~0.85 GB, so a run that finds less
# available memory than `workers x VISION_WORKER_GB + VISION_MEMORY_HEADROOM_GB`
# falls back to the shared worker instead of swapping, and says so - in the log
# and in 01b's `vision_mode` / `vision_mode_reason`, which is what makes the
# next batch a measurement.
VISION_SOCKET_ENV = "VISION_WORKER_SOCKET"
VISION_SLOT_SOCKET = "/tmp/shorts-content-factory-vision-worker.w{slot}.sock"
VISION_PER_WORKER = True
VISION_PER_WORKER_ENV = "FOOTAGE_VISION_PER_WORKER"
VISION_WORKER_GB = 0.85
VISION_MEMORY_HEADROOM_GB = 2.0
VISION_MODE_FIELD = "vision_mode"
VISION_MODE_REASON_FIELD = "vision_mode_reason"
VISION_MODE_PER_WORKER = "per_worker"
VISION_MODE_SHARED = "shared"
_ENV_OFF = ("0", "false", "no", "off")
_ENV_ON = ("1", "true", "yes", "on")

# The worker thread's own view of the run (CF-0332). Empty in the main thread,
# which is the sequential path: nothing below looks at it unless it is set.
_WORKER = threading.local()


def index_workers(value=None, environ=None):
    """The worker count this run uses: `--index-workers`, else the
    environment, else DEFAULT_INDEX_WORKERS. Anything unreadable or below 1
    falls back to the default rather than stopping the stage."""
    env = os.environ if environ is None else environ
    for raw in (value, env.get(INDEX_WORKERS_ENV)):
        if raw is None or raw == "":
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n >= 1:
            return n
    return DEFAULT_INDEX_WORKERS


def _worker_env():
    """The environment a subprocess started from a worker thread gets, or None
    on the sequential path (the child then inherits os.environ as before).

    CF-0332: `runlog.run()` exports RUNLOG_PARENT into os.environ, which is
    one dict for the whole process - with two topics walking at once, a child
    would chain under whichever run() exported last. The thread's own stack
    knows the right parent, so it is handed down explicitly. The CF-0316
    watchdog does not depend on this (it follows the child's pid), but the
    event tree and the per-source accounting do."""
    if not getattr(_WORKER, "active", False):
        return None
    env = dict(os.environ)
    try:
        parent = runlog.current_id()
        batch_dir = runlog.current_batch_dir()
    except Exception:
        parent = batch_dir = None
    if parent:
        env["RUNLOG_PARENT"] = str(parent)
    if batch_dir:
        env["RUNLOG_BATCH"] = str(batch_dir)
    sock = getattr(_WORKER, "vision_socket", None)
    if sock:
        env[VISION_SOCKET_ENV] = sock
    return env


def vision_slot_sockets(workers, per_worker=None):
    """One Vision socket path per worker slot when per-worker Vision is on
    (`per_worker`, else VISION_PER_WORKER) and more than one source is indexed
    at a time; None otherwise (every slot then queues at the machine-wide
    worker, the CF-0058 shape)."""
    on = VISION_PER_WORKER if per_worker is None else per_worker
    if not on or workers < 2:
        return None
    return [VISION_SLOT_SOCKET.format(slot=i) for i in range(workers)]


def vision_per_worker_wanted(flag=None, environ=None):
    """(wanted, whence) - whether this run asks for a Vision worker per slot,
    and who said so: `flag` (`--vision-per-worker` / `--no-vision-per-worker`),
    else env FOOTAGE_VISION_PER_WORKER (0/false/no/off, 1/true/yes/on; anything
    else is ignored), else VISION_PER_WORKER (CF-0843)."""
    if flag is not None:
        return bool(flag), ("--vision-per-worker" if flag
                            else "--no-vision-per-worker")
    env = os.environ if environ is None else environ
    raw = str(env.get(VISION_PER_WORKER_ENV) or "").strip().lower()
    if raw in _ENV_OFF or raw in _ENV_ON:
        return raw in _ENV_ON, f"{VISION_PER_WORKER_ENV}={raw}"
    return VISION_PER_WORKER, "default"


def available_memory_gb():
    """The memory this machine can hand out without swapping, in GB, or None
    when it cannot be read. macOS: `vm_stat` free + inactive + speculative
    pages; elsewhere /proc/meminfo's MemAvailable. No new dependency (CF-0843:
    psutil is not in this agent's requirements)."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        out = ""
    if out:
        m = re.search(r"page size of (\d+) bytes", out)
        page = int(m.group(1)) if m else 4096
        pages = 0
        for key in ("Pages free", "Pages inactive", "Pages speculative"):
            m = re.search(rf"^{key}:\s+(\d+)", out, re.M)
            if m:
                pages += int(m.group(1))
        if pages:
            return pages * page / 1024 ** 3
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 ** 2
    except Exception:
        pass
    return None


def vision_plan(workers, flag=None, environ=None, free_gb=None):
    """CF-0843: the Vision mode of this run - a dict with `vision_mode`
    (`per_worker` | `shared`), `vision_mode_reason` and `sockets` (the slot
    sockets, or None for the machine-wide worker). `free_gb` is a callable
    returning available GB (default available_memory_gb; tests hand in their
    own). Per-worker needs more than one slot and
    `workers x VISION_WORKER_GB + VISION_MEMORY_HEADROOM_GB` GB available;
    short of that the run falls back to the shared worker. Memory that cannot
    be read does not stop the per-worker mode - the reason says it was not
    checked."""
    wanted, whence = vision_per_worker_wanted(flag, environ)
    plan = {VISION_MODE_FIELD: VISION_MODE_SHARED, "sockets": None}
    if not wanted:
        plan[VISION_MODE_REASON_FIELD] = f"off: {whence}"
        return plan
    if workers < 2:
        plan[VISION_MODE_REASON_FIELD] = f"one_worker: {workers} index worker"
        return plan
    need = workers * VISION_WORKER_GB + VISION_MEMORY_HEADROOM_GB
    free = (free_gb or available_memory_gb)()
    if free is not None and free < need:
        plan[VISION_MODE_REASON_FIELD] = (
            f"low_memory: {free:.1f} GB free < {need:.1f} GB needed "
            f"({workers} x {VISION_WORKER_GB} + {VISION_MEMORY_HEADROOM_GB})")
        return plan
    plan[VISION_MODE_FIELD] = VISION_MODE_PER_WORKER
    plan["sockets"] = vision_slot_sockets(workers, per_worker=True)
    plan[VISION_MODE_REASON_FIELD] = (
        f"on ({whence}): " + (f"{free:.1f} GB free >= {need:.1f} GB needed"
                              if free is not None else "memory not readable, "
                              "not checked"))
    return plan


def add_vision_flags(p):
    """`--vision-per-worker` / `--no-vision-per-worker` onto parser `p`, one
    dest (`vision_per_worker`: True / False / None = env, then default)."""
    p.add_argument("--vision-per-worker", dest="vision_per_worker",
                   action="store_const", const=True, default=None,
                   help="CF-0332: give each index worker its own Vision worker "
                        "instead of the machine-wide one (-11 %% wall at 4 "
                        "workers, ~0.85 GB of memory per extra Vision worker). "
                        "CF-0843: on by default; falls back to the shared "
                        "worker when memory is short")
    p.add_argument("--no-vision-per-worker", dest="vision_per_worker",
                   action="store_const", const=False,
                   help="CF-0843: the rollback - every index worker queues at "
                        f"the machine-wide Vision worker (also env "
                        f"{VISION_PER_WORKER_ENV}=0)")
    return p


def stamp_vision_mode(report, plan, workers):
    """The pass's Vision mode into 01b (CF-0843), additive fields only."""
    report[VISION_MODE_FIELD] = plan[VISION_MODE_FIELD]
    report[VISION_MODE_REASON_FIELD] = plan[VISION_MODE_REASON_FIELD]
    report["index_workers"] = workers
    return report


def _env_kw():
    env = _worker_env()
    return {"env": env} if env is not None else {}

# ---------------------------------------------------------------------------
# The source sieve, step 2 (CF-0299)
#
# A third way an id that came down is not a source, and the first one that is
# about what is *in* the picture: the description pass says so. The codes live
# here beside the other two because they land in the same `failed[].reason_code`
# and, when a topic loses everything to the sieve, in the same
# `skipped_topics[].reason_code` - one vocabulary, read by
# shared/runlog/funnel.py. `refused_at: sieve` says where it happened, beside
# the other steps and `index`.
#
# `source_foreign` is the Delver case of batch 2026-09-21T0358Z: `9a7i4LHHZNs`
# is an animated Antarctic Press comic-universe trailer that was accepted as
# the topic's second source, indexed, described, and only refused by the
# writer after the whole stage had been paid for. `source_burned_text` is the
# Coach Hale case of the same batch: `bYKJxZYd66o` is a vertical interview
# Short with captions in the middle of the frame, and the frame judge rejected
# the finished render over six of them - after the script, the TTS and the
# render.
#
# CF-0435 (2026-09-30): only `source_foreign` is still written. A source is
# refused whole only for being somebody else's film (the score model's hard
# `score.hard.foreign_work_footage`); a burned-text majority keeps the source
# and its burned shots stay out one by one (`shot_usability`, hard rule
# `burned_text`). `source_burned_text` stays in the vocabulary because the
# reports written before this task carry it and the funnel still counts them.
SIEVE_FOREIGN_CODE = "source_foreign"
SIEVE_BURNED_TEXT_CODE = "source_burned_text"
SIEVE_CODES = (SIEVE_FOREIGN_CODE, SIEVE_BURNED_TEXT_CODE)
# CF-0817: the sieve's guard refuses a held source somebody already found to be
# another people's host show (`source_sieve.host_show_refusals`) - in
# `failed[]` under its own word, a loss of the sieve's kind. A topic that lost
# everything that way is refused as `source_foreign` (somebody else's
# material): `host_show` is not a topic word the funnel's vocabulary knows.
HOST_SHOW_CODE = "host_show"
SIEVE_REFUSAL_CODES = SIEVE_CODES + (HOST_SHOW_CODE,)
RUNG_SIEVE = "sieve"

# ---------------------------------------------------------------------------
# The duration ceiling (CF-0302)
#
# The fourth way an id is not a source, and the only one decided before a byte
# of media moves. On batch 2026-09-21T0358Z the Silent Tide topic
# (`lf-2026-09-21-004`) was offered `Lv_GOa6HXVA` - "Lakeside Trailer,
# Example Pictures Leaving California, People vs. Gorilla Boss & More - SMALL ZERO",
# a 2 h 14 min news talk show with 46 views whose title carries the word
# "Trailer", which is all it took for Trend Hunter to file it under
# `nature: trailer`. It came down whole (507 s) and its
# index was still splitting shots around minute 19 of the file 41 minutes
# later, when the stage operator killed it by hand. The record was honest
# afterwards - `index_failed`, CF-0281 - but the attempt was spent, the
# CF-0129 cap was reached, and the topic was refused with a good first source
# (`0vjwu1hjqK0`) and two candidates it never got to try.
#
# So the length is asked for before the download (fetch_footage.probe_duration,
# `--skip-download`), and a candidate over its nature's ceiling is refused
# here, at `refused_at: metadata`, with `reason_code: source_too_long` - and
# **without spending the topic's attempt**. That last part is the whole point:
# the cap of CF-0129 counts videos this stage downloads, and a candidate it
# declined to download by reading one number is not one of them. Refusing it
# at the cost of an attempt would have lost the same topic just as surely.
#
# Where the number comes from, in order, so that the usual batch asks YouTube
# nothing extra: `01-trend-hunter.json` -> `evidence.footage_candidates[]` ->
# `duration_seconds` (the CF-0302 half in Trend Hunter, which already calls
# `videos.list` and gets `contentDetails.duration`), then this factory's own
# cache entry for the id, then one metadata request. A candidate whose length
# nobody can tell is **not** refused: it walks the normal path, and the fact
# that nothing was measured is recorded (`duration_ceiling.unmeasured[]` in
# the report, and a CEILING line in the log). A probe that gets no answer is
# one of those cases, which is why the metadata request cannot cost a topic
# anything: the download behind it still goes ahead.
TOO_LONG_CODE = "source_too_long"
RUNG_METADATA = "metadata"
# CF-0333: the same refusal, made inside the download request on yt-dlp's own
# number when the probe above could not tell (see fetch_footage.py).
RUNG_DOWNLOAD = "download"

# Where the ceiling is configured, inside `channels/<id>.json`: what this
# channel takes from its video source. Either one
# number for everything, or `{nature: seconds}` with an optional `default`;
# a key that is not there leaves the numbers below, which are this stage's
# own safety net and not a channel preference.
CEILING_KEY_PATH = ("sources", "youtube", "max_source_duration_seconds")
CEILING_KEY = ".".join(CEILING_KEY_PATH)
CEILING_DEFAULT_NATURE = "default"

# The numbers, measured 2026-09-21 over the 93 accepted sources of the eight
# written batches (`shared/footage/index.json` durations against the
# `fetched[]` of every `01b-footage-index.json`), their natures from
# `evidence.footage_candidates[]`, and the per-source cost in
# `RUN_EVENTS.jsonl` (`footage-indexer/ingest` and `/index` script events):
#
#   default 3600 - the longest source that ever reached a finished video is
#     3426 s (`-3NpUXI5juI`, a 57-minute interview used in a written video),
#     and it is also the longest that was ever indexed successfully at all -
#     45 min of indexing, the most expensive honest source on record. Above
#     that there are exactly two: 4307 s (`HEaXDIrGhS4`, killed three times at
#     the indexer's own ceiling, CF-0281) and 8019 s (`Lv_GOa6HXVA`, this
#     task). An hour is therefore just above everything that has ever worked
#     and below everything that has ever failed, and the cost curve agrees:
#     indexing is flat at ~15-30 min up to ~5 min of source and climbs from
#     there (304 s -> 30 min, 1769 s -> 33 min, 3426 s -> 46 min, 8019 s ->
#     unfinished after 41 min at a tenth of the file).
#
#   trailer 900 - `nature` is decided by the words in the title (CF-0297),
#     so "trailer" is the label a two-hour news podcast wears when it is
#     mislabelled, and both incidents above were labelled exactly that. The
#     real population behind the label has nothing near it: of the 14 accepted
#     sources with `nature: trailer` the longest that was ever used is 501 s,
#     the next 260 s, the median 144 s. 900 s refuses nothing this factory has
#     ever cut with and catches both incidents by a factor of five.
#
# An `interview` is deliberately left on the default: interviews are honestly
# long (median 804 s, up to 3426 s used) and a tight ceiling there would
# refuse material that has made finished videos.
DEFAULT_MAX_SOURCE_SECONDS = {CEILING_DEFAULT_NATURE: 3600, "trailer": 900}

# The key Trend Hunter writes the measured length into, per candidate.
CANDIDATE_DURATION_KEY = "duration_seconds"

TOO_LONG_LINE = ("CEILING {vid} refused before the download: {seconds} s is over "
                 "the {limit} s ceiling for nature '{nature}' (CF-0302) - the "
                 "topic's attempt is not spent")
# CF-0663 (FI-2 of the root's docs/science-footage.md): a candidate whose
# licence the channel does not take is refused before anything is asked of
# YouTube - the Trend Hunter's own verdict (`licence.accepted: false`, which
# its CF-0662 drop should have kept away), the channel's lists re-read, or a
# licence named NC / ND / non-free (`source_rights.refusal`). Defence in
# depth, so it costs the topic no attempt and is not a lost download.
LICENCE_CODE = source_rights.LICENCE_REFUSED_CODE
# CF-0665: an archive file whose licence changed since the Trend Hunter judged
# it (`fetch_footage.py --archive-json`, LICENCE_CHANGED_EXIT) - refused before
# anything came down, no attempt spent, the same way as LICENCE_CODE.
LICENCE_CHANGED_CODE = fetch_footage.LICENCE_CHANGED_CODE
LICENCE_CHANGED_LINE = ("LICENCE {vid} not taken for {topic}: {reason} - read again from "
                        "the archive before the download, nothing came down, the "
                        "topic's attempt is not spent (CF-0665)")
LICENCE_LINE = ("LICENCE {vid} not taken for {topic}: {reason} - nothing was asked of "
                "YouTube, the topic's attempt is not spent (CF-0663)")
TOO_LONG_DOWNLOAD_LINE = ("CEILING {vid} refused inside the download ({rung}): {seconds} s "
                          "is over the {limit} s ceiling for nature '{nature}' "
                          "(CF-0333) - nothing came down, the topic's attempt is "
                          "not spent")
UNMEASURED_LINE = ("CEILING {vid}: length unknown ({why}) - not refused here, "
                   "the candidate goes the usual way (CF-0302) and its download "
                   "carries the ceiling (CF-0333)")
TOO_LONG_SUMMARY = ("  {n} candidate(s) refused before the download, over the "
                    "CF-0302 duration ceiling (no attempt spent): ")

INDEX_FAILED_LINE = "INDEX {vid} failed, not registered as a source: {error}"
INDEX_TIMEOUT_LINE = ("WATCHDOG {vid} taken down by the CF-0316 watchdog: quiet "
                      "for {silent} s of the {ceiling} s this operation is "
                      "allowed ({code}) - the source is lost, the run is not, "
                      "and the topic's attempt is not spent")
INDEX_TIMEOUT_SUMMARY = ("  {n} source(s) taken down by the CF-0316 watchdog "
                         "(no attempt spent, always a task by CF-0319): ")
PARTIAL_INDEX_LINE = ("PARTIAL {vid}: {why} - not a cache hit, indexing again "
                      "from scratch (CF-0281)")
INDEX_FAILURES_LINE = ("  {n} source(s) came down and could not be indexed "
                       "(CF-0281), so they are not sources: ")


class IndexFailed(RuntimeError):
    """`index_footage.py` left no index a reader may trust for this source.

    Raised by `index_source()` and caught in `admit()`. The media is in the cache and the id is not worth another
    download - what is missing is the index, and the topic's next candidate is
    the way on."""


class IndexTimedOut(IndexFailed):
    """The index went quiet and the CF-0316 watchdog took it down.

    An `IndexFailed` on purpose: for everyone downstream this is the same
    absence - an id that came down and has no index - so the whole CF-0281 path
    (out of `fetched`, into `failed[]` with `index_failed`, on to the next
    candidate) is reused as it is. What this class adds is what only a kill
    has: the watchdog's outcome code, how long the operation hung, the ceiling
    it hung past, and the fact that the topic's attempt is not spent."""

    def __init__(self, message, code=None, silent_s=None, ceiling_s=None):
        super().__init__(message)
        self.code = code
        self.silent_s = silent_s
        self.ceiling_s = ceiling_s

# ---------------------------------------------------------------------------
# The two-source floor (CF-0129)
#
# How many canonical sources a topic needs, and how many downloads it may
# spend getting them. `wanted` is the same 2 the Video Editor's gate and
# shared/runlog/funnel.py's TWO_SOURCE_FLOOR read - spelled again rather than
# imported, the way the funnel spells it rather than importing from patterns/.
#
# An *attempt* is one distinct candidate id this stage started a download for;
# the cap bounds the *videos a topic touches* at four.
SOURCES_WANTED = 2
MAX_ATTEMPTS_PER_TOPIC = 4

# The rung of an attempt made in the top-up pass - for a topic the first
# pass left short of the floor.
RUNG_TOP_UP = "top_up"

# CF-0232 codes for a topic (not a source) this stage drops, and the `stage`
# every such record carries. `no_second_source` is the one the floor is about;
# the other two are for a topic that got nothing at all, so that the record
# and the funnel's own reading of `sources_by_topic` agree about what happened.
TOPIC_REFUSAL_CODE = "no_second_source"
TOPIC_NO_SOURCE_CODE = "no_source"
STAGE_NAME = "footage-indexer"

# CF-0318: the code this stage used to drop a `review` topic with. Kept for
# reading and never for writing - `topic_skip()` raises on it, so no pass can
# write one again. The name stays because reports written before 2026-09-23
# carry these records, and two readers tell compliance's word from this
# stage's own refusals by asking `PRE_FETCH_CODES` (`source_sieve.py`, and the
# CLI's "refused below the floor" line). Delete the name and every one of
# those old records is re-read as a refusal this stage made - a loss invented
# by the reader, in the same funnel this task exists to correct.
COMPLIANCE_SKIP_CODE = "compliance_review"

# CF-0265 (grill of 2026-09-17): the two codes for a topic this stage does not
# fetch *because of what 02-compliance-checker.json says about it*, decided
# before a single download.
#
# `reserve_unused` is compliance's own code, spelled the same here on purpose -
# `agents/compliance-checker/scripts/cut_shortlist.py` writes it into
# `reserve[]` and the funnel reads it from both files; a second name for one
# outcome would be two losses in the summary instead of one. A reserve topic
# passed compliance and the batch simply had no slot for it, so it is neither a
# refusal of this stage nor a fault of the topic - and fetching it would spend
# downloads, YouTube quota and ~19 min of indexing per source on material
# nothing downstream ever opens.
#
# `not_screened` is the funnel's own code (shared/runlog/funnel.py) for a topic
# of `01-trend-hunter.json` that 02-compliance-checker.json names in neither
# `results[]` nor `reserve[]`. It is a refusal: downloading unjudged material
# is the worse error of the two, and no batch written so far is missing a row
# (every 02- file checked on 2026-09-17 has one result per topic), so re-running
# an old batch does not meet this code at all.
RESERVE_SKIP_CODE = "reserve_unused"
NOT_SCREENED_CODE = "not_screened"

# Codes decided by reading the compliance artifact - before the walk, before
# any download. They are not this stage's own refusals, so the CLI's
# "refused below the floor" line must not sweep them up. Two of the three are
# live; `COMPLIANCE_SKIP_CODE` is in the tuple for old reports alone
# (CF-0318), and a tuple that dropped it would misread every one of them.
PRE_FETCH_CODES = (COMPLIANCE_SKIP_CODE, RESERVE_SKIP_CODE, NOT_SCREENED_CODE)

# CF-0306 (user's decision of 2026-09-21, "да, подставлять"). A topic lost
# after compliance has already had its slot paid for - the shortlist was cut to
# the batch target and the topics above that target are sitting in `reserve[]`,
# judged and unused. On batch `example-film/2026-09-21T0358Z` five topics were
# carried, four were lost (one here, three at the writer), two reserve topics
# were never touched, and the batch shipped one script against a target of
# three. So a lost slot is refilled from the reserve instead of being left
# empty.
#
# `reserve_substituted` is the code of the substitution itself - not a loss and
# not a skip: it is written into the report's own block (below) and onto the
# refused topic's record as `replaced_by_topic`, so the funnel can say "this
# topic was lost AND its slot was refilled" without either half hiding the
# other. `reserve_exhausted` is the honest end of the queue: a slot fell free
# and there was nothing left to put in it.
RESERVE_SUBSTITUTED_CODE = "reserve_substituted"
RESERVE_EXHAUSTED_CODE = "reserve_exhausted"

# The report key the block goes under.
SUBSTITUTION_KEY = "reserve_substitution"

# The whole vocabulary `topic_refusal()` refuses a topic with - every code
# `refusal_code()` below can return, and nothing else. It is one tuple because
# CF-0307 was one tuple short: the list of codes that free a slot used to be
# written out again beside this one, with three of the six in it, and Rennick
# (`lf-2026-09-21-005` of batch `example-film/2026-09-21T1541Z`) - a topic
# that lost all three of its sources to the sieve and was refused with
# `source_burned_text` - was not seen as a loss at all. Its slot stayed empty
# while a reserve topic sat unused, and no `reserve_exhausted` was written
# either, because a slot nobody noticed falling free cannot be reported empty.
#
# So the set is named once. A code added to `refusal_code()` and not to this
# tuple is a `ValueError` in the one place that chooses a code, not a slot
# quietly lost three stages later.
TOPIC_REFUSAL_CODES = (TOPIC_REFUSAL_CODE, TOPIC_NO_SOURCE_CODE,
                       FUNNEL_REASON_CODE, INDEX_FUNNEL_CODE,
                       TOO_LONG_CODE) + SIEVE_CODES

# The codes on a *topic* record of `skipped_topics[]` that free a slot: this
# stage's own refusals, which is exactly the vocabulary above. A topic refused
# here is a topic the batch has lost, whatever it died of - the cause changes
# what the record says, never whether the slot it was carrying is now empty.
#
# The source-level codes of `failed[]` are a different list read off a
# different array: a source lost while its topic still reaches the floor costs
# the batch nothing, and a source lost that takes the topic below the floor
# arrives here anyway, as the topic refusal the floor writes. Those codes are
# recorded per substitution in `source_codes` instead, which is how the block
# says *what* the replaced topic died of.
SLOT_FREEING_CODES = TOPIC_REFUSAL_CODES

SUBSTITUTION_LINE = ("RESERVE {sub} takes the slot of {tid} ({code}) - "
                     "{left} reserve topic(s) left")
EXHAUSTED_LINE = ("RESERVE {tid} ({code}) leaves a slot nobody can fill: the "
                  "reserve is used up ({code_out})")

TOPIC_REFUSED_LINE = ("FLOOR {tid} refused: {reason}")

# CF-0304: the depth floor is not a refusal, so its line is a warning and the
# topic goes on to Content Researcher behind it. Written once per topic, after
# the walk, only for a topic that did reach the source floor - one that did not
# is already being refused above, and two lines about one topic read as two
# faults.
POOL_THIN_LINE = ("DEPTH {tid} keeps a thin pool: {usable} usable shot(s) of "
                  "{shots} against a floor of {floor}, and {why} - it is NOT "
                  "refused here (the anchors decide that), it is in "
                  "`pool_depth.thin[]`")

FetchResult = namedtuple("FetchResult", "path cached")

# CF-0302: one candidate's measured length. `source` is where the number came
# from - `candidate` (the batch artifact), `cache` (this factory already holds
# the media) or `metadata` (one request to YouTube) - and `seconds` is None
# when nobody could tell, which is never a refusal.
Measured = namedtuple("Measured", "seconds source error")


class Ceiling(namedtuple("Ceiling", "limits configured config_path key")):
    """How long a source of a given nature may be (CF-0302).

    `limits` is `{nature: seconds}` with a `default` entry that answers for
    every nature not named; `configured` says whether the channel config had
    anything to say, so the report can tell the channel's number from this
    stage's own safety net.
    """

    def seconds(self, nature=None):
        """The ceiling this nature is held to, or None if there is none."""
        v = self.limits.get(nature) if isinstance(nature, str) else None
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            v = self.limits.get(CEILING_DEFAULT_NATURE)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

# What `02-compliance-checker.json` says about this batch's topics (CF-0265).
#
#   ran      - the file exists at all. Without it nothing has been judged and
#              the stage fetches every topic, exactly as it did before the
#              shortlist cut - that is how a batch from before CF-0265, and a
#              batch whose compliance pass has not run yet, keep working.
#   verdict  - {topic_id: verdict} from `results[]`: every topic the cut
#              carried into the batch, whatever verdict it carries. Since
#              CF-0318 the verdict itself decides nothing here - membership of
#              `results[]` is the whole question, and a `review` topic in it is
#              fetched like any other. The map is still read, because the
#              promotion of a reserve topic carries a verdict with it.
#   reserve  - the topic ids of `reserve[]`: judged, eligible, no slot.
#   rows     - CF-0306: the `reserve[]` rows themselves, in the order the cut
#              wrote them (the shortlist's own order), so a slot that falls
#              free can be filled by the next reserve topic *and* by the
#              verdict compliance gave it. `reserve` stays the membership test
#              every reader of this record already uses.
class Screening(namedtuple("Screening", "ran verdict reserve rows",
                           defaults=((),))):
    """What `02-compliance-checker.json` says about this batch's topics."""

    def promoting(self, *tids):
        """This screening with reserve topics `tids` moved into the batch.

        CF-0306: a reserve topic that takes the slot of a topic this stage
        lost is walked by the same `ingest()` as any other topic, and that
        function asks `compliance_skip()` first - which would skip it for
        being reserve. So the promotion is expressed where the decision is
        read: the topic moves out of `reserve` and into `verdict`, carrying
        the verdict compliance actually gave it (`clear`/`caution`, and since
        CF-0318 `review` too - the cut reserves every eligible topic). Nothing is written back to
        `02-compliance-checker.json`: that file is another stage's record of
        what it judged, and it judged this topic already.

        CF-0307 takes more than one id, because the promotion has to outlive
        the run that made it: every topic this batch has already substituted
        is promoted together, by `promoted()` below.
        """
        tids = {t for t in tids if t}
        verdict = dict(self.verdict)
        for tid in tids:
            row = next((r for r in self.rows if r.get("topic_id") == tid), None)
            verdict[tid] = (row or {}).get("verdict") or "clear"
        return Screening(ran=True, verdict=verdict,
                         reserve=frozenset(self.reserve) - tids,
                         rows=tuple(r for r in self.rows
                                    if r.get("topic_id") not in tids))


class TooLong(RuntimeError):
    """CF-0333: the download itself refused the video over the duration
    ceiling (`fetch_footage.py --max-duration`, yt-dlp's match filter). Nothing
    came down. `seconds` is the length yt-dlp read in that same request."""

    def __init__(self, message, seconds=None, limit=None):
        super().__init__(message)
        self.seconds = seconds
        self.limit = limit


class LicenceChanged(RuntimeError):
    """CF-0665: an archive file's licence, read again from the archive before
    the download, is not the one its candidate was judged on. Nothing came
    down. `record` is the fetcher's LICENCE_CHANGED record (`was` / `now`)."""

    def __init__(self, message, record=None):
        super().__init__(message)
        self.record = dict(record or {})


def _takes(fn, name):
    """Whether callable `fn` accepts keyword `name` - an injected fetcher
    written before CF-0333 takes (vid, note) and nothing more."""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind == p.VAR_KEYWORD for p in params.values())


def verdicts(batch):
    """What the compliance pass said about this batch's topics (`Screening`).

    Both lists are read, because since CF-0265 the pass judges the whole
    shortlist and `cut_shortlist.py` then splits its verdicts in two:

      results[]  the topics that go on - every one of them, `review`
                 included since CF-0318: the cut hands out the slot and the
                 verdict does not take it back;
      reserve[]  eligible topics the batch target left without a slot, each
                 already carrying `reason_code: reserve_unused`.

    Reading `results[]` alone - which is what this did until 2026-09-17 - makes
    a reserve topic indistinguishable from a topic nobody judged, and the stage
    downloaded both. `reserve[]` missing altogether is not the same thing: it
    means the cut never ran (a batch from before CF-0265), and there is then no
    reserve to skip. The cut writes `reserve: []` whenever it did run.
    """
    f = Path(batch) / "02-compliance-checker.json"
    if not f.exists():
        return Screening(ran=False, verdict={}, reserve=frozenset())
    doc = json.load(open(f))
    reserve = doc.get("reserve")
    rows = tuple(r for r in reserve
                 if isinstance(r, dict) and r.get("topic_id")) \
        if isinstance(reserve, list) else ()
    return Screening(
        ran=True,
        verdict={r["topic_id"]: r["verdict"] for r in doc["results"]},
        reserve=frozenset(r["topic_id"] for r in rows),
        rows=rows)


def as_screening(verdict):
    """`verdict` as a `Screening`, however it was passed in.

    `ingest()` is called with the plain `{topic_id: verdict}` dict in older
    tests and from other entry points, and an empty one has always meant "no
    compliance output to read" - that reading is kept: a bare dict is taken as
    an unjudged batch when it is empty, and as a screening that named exactly
    the topics it names when it is not.
    """
    if isinstance(verdict, Screening):
        return verdict
    verdict = dict(verdict or {})
    return Screening(ran=bool(verdict), verdict=verdict, reserve=frozenset())


def _ceiling_limits(node):
    """`{nature: seconds}` out of whatever the config key holds, and whether
    the config said anything at all.

    One number is a ceiling for every nature; a mapping names natures and may
    carry its own `default`, and the natures it does not name keep the numbers
    measured in DEFAULT_MAX_SOURCE_SECONDS. Anything else - a string, a
    negative, a `_note` key beside the numbers the way the rest of this
    factory's config writes them - is ignored rather than crashing the stage:
    a ceiling nobody can parse must not be the reason a batch has no footage.
    """
    limits = dict(DEFAULT_MAX_SOURCE_SECONDS)
    if isinstance(node, bool):
        return limits, False
    if isinstance(node, (int, float)) and node > 0:
        return {CEILING_DEFAULT_NATURE: node}, True
    if isinstance(node, dict):
        got = {k: v for k, v in node.items()
               if isinstance(k, str) and not k.endswith("_note")
               and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
        if got:
            limits.update(got)
            return limits, True
    return limits, False


def duration_ceiling(channel, config_path=None, root=None):
    """The CF-0302 ceiling as the channel config describes it.

    The channel name is resolved through CF-0197 first, the config is
    opened once, and a file that is missing, unreadable or silent on the key
    is a normal state - the stage then holds sources to the numbers measured
    in DEFAULT_MAX_SOURCE_SECONDS and the report says `configured: false`.
    """
    root = Path(root) if root else (Path(FACTORY_ROOT) if FACTORY_ROOT else None)
    channel = resolve_channel(channel, root=root)
    cfg_path = (Path(config_path) if config_path
                else channel_config_path(channel, root=root))
    node = None
    if Path(cfg_path).is_file():
        try:
            cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        node = cfg
        for part in CEILING_KEY_PATH:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
    limits, configured = _ceiling_limits(node)
    return Ceiling(limits=limits, configured=configured,
                   config_path=Path(cfg_path), key=CEILING_KEY)


def footage_origins(channel, root=None):
    """CF-0663: the channel's `channels/<id>/footage-origin.json` ({} when it
    has none) - the licence lists and the origins' credits the `rights` record
    of every source is read against."""
    root = Path(root) if root else (Path(FACTORY_ROOT) if FACTORY_ROOT else None)
    return source_rights.load_origins(resolve_channel(channel, root=root), root=root)


# ---------------------------------------------------------------------------
# CF-0689: a topic kept on own graphics (ExampleTech, the user's decision of
# 2026-10-12)
#
# On a channel whose footage-origin.json names an origin under the
# `own_graphic` licence the base footage is the graphics the Video Editor
# draws from the script's facts at the edit - never a pool source, never
# indexed here. Trend Hunter keeps such a channel's topic with 0-1 footage
# candidates when its `support_text` holds enough quotable facts and says so in
# `evidence.own_graphic_footing` (`meets_floor: true`). This stage's floor
# would refuse that topic (`no_source` with no candidate at all,
# `no_second_source` with one source, the code of its whole loss otherwise)
# before Content Researcher - who writes it an all-graphic script - ever saw
# it. So `apply_floor_mode()` lets it through, and only it: the channel names
# the origin AND the topic's footing says met. It leaves `skipped_topics[]`
# and is recorded under `OWN_GRAPHIC_KEY` (`kept[]`, with the refusal it
# replaces), never as a `warnings[]` entry and never as `no_second_source`. A
# Reel or Science topic, and a Tech topic without `meets_floor`, is floored
# exactly as before.
# ---------------------------------------------------------------------------
OWN_GRAPHIC_KEY = "own_graphic_footing"         # the report block = TH's key
OWN_GRAPHIC_KEPT_NOTE = "kept on own graphics"
OWN_GRAPHIC_KEPT_LINE = "OWN GRAPHICS {tid} kept: {detail}"


def own_graphic_eligible(topics, origins):
    """-> `(origin, {topic_id: footing})`: the channel's `own_graphic` origin
    (`source_rights.own_graphic_origin`, None on a channel without one) and
    the topics whose `evidence.own_graphic_footing.meets_floor` is true - an
    empty dict whenever the origin is missing, whatever the topics say."""
    origin = source_rights.own_graphic_origin(origins)
    if not origin:
        return None, {}
    out = {}
    for t in topics or ():
        if not isinstance(t, dict) or not isinstance(t.get("topic_id"), str):
            continue
        footing = (t.get("evidence") or {}).get(OWN_GRAPHIC_KEY)
        if isinstance(footing, dict) and footing.get("meets_floor") is True:
            out[t["topic_id"]] = footing
    return origin, out


def mark_own_graphic(report, topics, origins):
    """Write (or refresh) the report's `OWN_GRAPHIC_KEY` block from the batch's
    topics and the channel's origins, so every later reader of the report -
    `apply_floor_mode()`, the reserve, the sieve's second pass - knows which
    topics stand on graphics. On a channel without the origin nothing is
    written and a stale block is removed: the floor is the floor."""
    origin, eligible = own_graphic_eligible(topics, origins)
    if not origin:
        report.pop(OWN_GRAPHIC_KEY, None)
        return None
    block = report.get(OWN_GRAPHIC_KEY)
    kept = list(block.get("kept") or []) if isinstance(block, dict) else []
    report[OWN_GRAPHIC_KEY] = {
        "origin": origin,
        "eligible": {tid: {k: f.get(k) for k in
                           ("quotable_facts", "floor", "meets_floor", "note")}
                     for tid, f in eligible.items()},
        "kept": [k for k in kept if k.get("topic_id") in eligible],
        "note": ("CF-0689: this channel's footage-origin.json names the "
                 f"`{origin}` origin (`own_graphic` licence) - the graphics "
                 "the Video Editor draws from the script's facts, never "
                 "fetched or indexed here. A topic in `eligible` (Trend "
                 "Hunter's `evidence.own_graphic_footing.meets_floor`) that "
                 "this stage's source floor would refuse is "
                 f"{OWN_GRAPHIC_KEPT_NOTE} instead: out of `skipped_topics[]`, "
                 "into `kept[]` with the refusal it replaces, and on to "
                 "Content Researcher, who writes it an all-graphic script. "
                 "Every other topic is floored as before."),
    }
    return report[OWN_GRAPHIC_KEY]


def print_own_graphic_kept(report, out=print):
    """The operator's line for the topics kept on own graphics (CF-0689),
    nothing when there are none - said on stdout like the floor's warnings,
    so it reaches `stage-done --note` and not only 01b."""
    kept = ((report or {}).get(OWN_GRAPHIC_KEY) or {}).get("kept") or []
    if kept:
        out(f"  {len(kept)} topic(s) {OWN_GRAPHIC_KEPT_NOTE} (CF-0689, "
            f"{report[OWN_GRAPHIC_KEY].get('origin')} origin), not refused "
            f"below the source floor: "
            + ", ".join(f"{k['topic_id']} ({len(k.get('sources') or [])} "
                        f"source(s), {k.get('quotable_facts')} fact(s))"
                        for k in kept))


def own_graphic_keeps(report, tid):
    """Whether the report's block says `tid` stands on own graphics."""
    block = (report or {}).get(OWN_GRAPHIC_KEY)
    return (isinstance(block, dict) and bool(block.get("origin"))
            and tid in (block.get("eligible") or {}))


ARCHIVE_MEASURE = "archive"
OWN_CAPTURE_MEASURE = own_capture_source.MEASURE     # CF-0567

# CF-0567: the directories an own capture's recording is looked for in after
# the candidate's own `capture_file` (`own_capture_source.capture_dirs`) -
# None is the factory's inbox alone; main() puts the batch's `captures/` first.
CAPTURE_DIRS = None


def is_own_capture(vid):
    """CF-0567: `own_capture:<id>` / `own_capture-<id>` - our own recording."""
    return own_capture_source.is_own_capture(vid)


def is_direct(vid):
    """A source that is not a YouTube video - an archive file (CF-0665) or an
    own capture (CF-0567): walked under its file id, never paced, never asked
    of YouTube."""
    return archive_source.is_archive(vid) or own_capture_source.is_own_capture(vid)


def source_file_id(vid):
    """The id a source is walked, kept and reported under: `nasa:<id>` ->
    `nasa-<id>` (CF-0665), `own_capture:<id>` -> `own_capture-<id>` (CF-0567),
    a YouTube id as it is."""
    return own_capture_source.file_id(archive_source.file_id(vid))


def capture_dirs(batch_dir=None):
    """CAPTURE_DIRS when main() set it, else the inbox of the factory whose
    pool this stage fills (`<root>/shared/own-captures`, beside CACHE)."""
    if CAPTURE_DIRS is not None and batch_dir is None:
        return CAPTURE_DIRS
    return own_capture_source.capture_dirs(batch_dir=batch_dir, root=CACHE.parent.parent)


def own_capture_record(vid, record=None):
    """CF-0567: the candidate record of own capture `vid` with `capture_file`
    set to the recording found (`own_capture_source.locate`), or left as the
    candidate gave it when none is found - the fetch then refuses it."""
    rec = dict(record) if isinstance(record, dict) else {"video_id":
                                                          own_capture_source.candidate_name(vid)}
    rec.setdefault("candidate_id", rec.get("video_id") or own_capture_source.candidate_name(vid))
    found = own_capture_source.locate(vid, rec, capture_dirs())
    if found is not None:
        rec[own_capture_source.CAPTURE_FILE_KEY] = str(found)
    return rec


def own_capture_sidecar(vid, record=None):
    """CF-0567: the recorder's sidecar of `vid` - the pool's copy when it is
    in the pool, else the one beside the recording ingest would take; None."""
    fid = own_capture_source.file_id(vid)
    side = own_capture_source.read_sidecar(CACHE / f"{fid}{own_capture_source.SIDECAR_SUFFIX}")
    if side is None:
        found = own_capture_source.locate(vid, record, capture_dirs())
        side = own_capture_source.read_sidecar(found) if found is not None else None
    return side


def source_url(vid, record=None):
    """The address a source is registered under in the cache: YouTube's watch
    URL, or an archive file's page (`source_url`, CF-0665), or the page an
    own capture recorded (CF-0567)."""
    if is_own_capture(vid):
        rec = record if isinstance(record, dict) else {}
        return (rec.get("source_url") or rec.get("url")
                or own_capture_source.candidate_name(own_capture_source.file_id(vid)))
    if archive_source.is_archive(vid):
        rec = record if isinstance(record, dict) else {}
        return rec.get("source_url") or rec.get("download_url") or vid
    return f"https://www.youtube.com/watch?v={vid}"


def cache_entry_of(vid, record=None, idx=None):
    """The cache entry that answers for `vid` (its file present), or None -
    an archive file by its file id (CF-0665), a YouTube video by its URL."""
    idx = idx if idx is not None else fetch_footage.load_index()
    if is_own_capture(vid):
        return fetch_footage.cached_by_id(idx, own_capture_source.file_id(vid))
    if archive_source.is_archive(vid):
        return fetch_footage.cached_by_id(idx, archive_source.file_id(vid))
    return fetch_footage.cached_entry(idx, source_url(vid, record))


def measure_candidate(vid, record=None, probe=None):
    """How long candidate `vid` is, without downloading it (CF-0302).

    Three places are asked, cheapest first, and the first number wins:

      the batch artifact  `evidence.footage_candidates[].duration_seconds`,
                          written by Trend Hunter, which calls `videos.list`
                          for these ids anyway and already reads
                          `contentDetails.duration`. A batch written before
                          CF-0302 has no such field, which is why the two
                          fallbacks exist and why this stage keeps its own
                          safety net rather than trusting the artifact;
      the cache           an id this factory already holds was measured when
                          it was fetched (`shared/footage/index.json`), and
                          asking YouTube about it again would be for nothing;
      the source          one metadata request, `--skip-download`.

    Returns a `Measured`. `seconds` None means nobody could tell - the caller
    must then let the candidate through, not refuse it.
    """
    rec = record if isinstance(record, dict) else {}
    raw = rec.get(CANDIDATE_DURATION_KEY)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return Measured(float(raw), "candidate", None)

    try:
        entry = cache_entry_of(vid, rec)
    except (OSError, ValueError):
        entry = None
    if entry:
        held = entry.get("duration")
        if isinstance(held, (int, float)) and not isinstance(held, bool) and held > 0:
            return Measured(float(held), "cache", None)
    if is_own_capture(vid):
        # CF-0567: our own recording - no ceiling, nothing to ask anyone.
        return Measured(None, OWN_CAPTURE_MEASURE, "an own capture - no duration "
                        "ceiling (CF-0567)")
    if archive_source.is_archive(vid):
        # CF-0665: nothing to ask YouTube - the fetcher holds the ceiling on
        # ffprobe's length after the download.
        return Measured(None, ARCHIVE_MEASURE, "an archive file without a length - "
                        "ffprobe measures it after the download (CF-0665)")

    url = f"https://www.youtube.com/watch?v={vid}"
    ask = probe or fetch_footage.probe_duration
    meta = ask(url)
    return Measured(meta.seconds, "metadata", meta.error)


def fetch_source(vid, note, max_seconds=None, rights=None, record=None, licences=None):
    """Download (or hit the cache) via fetch_footage.py: one call per source.

    CF-0663: `rights` is the source's `rights` record (`source_rights`),
    handed on as `--rights-json` and kept on the cache entry.

    CF-0333: `max_seconds` is the duration ceiling of this candidate's nature,
    handed to the download itself (`--max-duration`), so the ceiling holds on
    the length the source reports in the download request and not only on the
    one a probe may or may not have got. A refusal there raises `TooLong`.

    Returns a `FetchResult` (path, and whether the cache answered). Raises
    `TooLong` / `LicenceChanged` for the two refusals the fetcher reports by
    exit code, and plain `RuntimeError`, carrying the fetcher's last stderr
    line, for anything else.
    """
    archive = archive_source.is_archive(vid) and isinstance(record, dict)
    own = is_own_capture(vid)
    url = source_url(vid, record)
    # Provenance is never inferred: these come from a search, so the
    # uploader is unknown here and --official stays off. Compliance
    # Checker reads that flag and cannot recover it later.
    cmd = [VENV_PY, str(SCRIPTS / "fetch_footage.py"), url, "--note", note]
    if own:
        # CF-0567: the finished recording is copied in - no ceiling.
        rec = own_capture_record(vid, record)
        cmd += ["--own-capture-json", json.dumps(rec, ensure_ascii=False)]
        if rights:
            cmd += ["--rights-json", json.dumps(rights, ensure_ascii=False)]
        max_seconds = rights = None
    elif archive:
        # CF-0665: an archive file, downloaded directly - the candidate's own
        # record goes along whole. NASA's library is an official
        # origin (the Trend Hunter's `origin: official`); a Commons file is anyone's
        # upload and goes through the sieve as one.
        cmd += ["--archive-json", json.dumps(dict(record, candidate_id=record.get(
            "candidate_id") or record.get("video_id")), ensure_ascii=False)]
        if licences:
            cmd += ["--licences-json", json.dumps(licences, ensure_ascii=False)]
        if record.get("origin") == "official":
            cmd += ["--official"]
    if max_seconds:
        cmd += ["--max-duration", str(int(max_seconds))]
    if rights:
        cmd += ["--rights-json", json.dumps(rights, ensure_ascii=False)]
    # CF-0316: the download is the watchdog's `download` class - 1500 s of
    # silence. `on_timeout="code"` and not a raise: a download the factory
    # took down is a failed download like any other, and the `fetch_failed`
    # path below is already the way on. The run is never dropped for it.
    out = runlog.run_child(cmd, tool="fetch_footage.py", step="fetch", video=vid,
                           watchdog="download", on_timeout="code",
                           capture_output=True, text=True, **_env_kw())
    if getattr(out, "timed_out", False):
        raise RuntimeError(
            f"{getattr(out, 'timeout_code', None) or 'fetch_timeout'}: the download of "
            f"{vid} was quiet past the CF-0316 `download` ceiling and was taken down "
            f"- nothing came down, so this candidate is a lost download and the walk "
            f"goes on")
    if out.returncode != 0:
        err = (out.stderr or "").strip()
        last = err.splitlines()[-1] if err else "?"
        too_long = (fetch_footage.parse_too_long(err)
                    if out.returncode == fetch_footage.TOO_LONG_EXIT else None)
        if too_long:
            raise TooLong(last, seconds=too_long[0], limit=too_long[1])
        changed = (fetch_footage.parse_licence_changed(err)
                   if out.returncode == fetch_footage.LICENCE_CHANGED_EXIT else None)
        if changed is not None:
            raise LicenceChanged(changed.get("reason") or last, changed)
        raise RuntimeError(last)
    stdout = out.stdout.strip()
    return FetchResult(stdout.split("-> ")[-1], stdout.startswith("cached"))


def shots_path(path):
    """Where `index_footage.py` leaves this source's index."""
    return Path(path).with_suffix(".shots.json")


def indexed_already(path, log=print):
    """Whether this source already carries an index worth keeping (CF-0281).

    The old test was `shots.json exists`, which a file a killed process left
    half-written passes. A file that is there and is not an index is worse
    than no file: it is read as a cache hit for the rest of the pool's life,
    and the source it stands for silently backs nothing. So it is named on
    stdout and removed, and the caller indexes the source again.
    """
    dest = shots_path(path)
    problems = shot_schema.file_problems(dest)
    if not problems:
        return True
    if dest.exists():
        log(PARTIAL_INDEX_LINE.format(vid=Path(path).stem, why=problems[0]))
        try:
            dest.unlink()
        except OSError as e:          # never a reason to fail the stage
            log(f"  could not remove {dest}: {e}")
    return False


def watchdog_ceiling(cls=None, source_seconds=None):
    """Seconds of silence the CF-0316 watchdog allows a call of this class, or
    None when there is no accounting library behind this checkout. Asked of the
    library rather than spelled again here: the arithmetic behind the numbers is
    the root's (`shared/runlog/watchdog.py`) and must have one home."""
    try:
        return runlog.sibling("watchdog").ceiling_for(cls, source_seconds=source_seconds)
    except Exception:                       # no library, or a class it refuses
        return None


def _run_index(path):
    """The subprocess itself, as its own seam so a test can stand in for it.

    CF-0316: through `runlog.run_child`, with no `timeout=` - so the call is run
    under the watchdog, which times the silence of this operation's own subtree
    (`step="index"`, the events `index_footage.py` writes) against
    `watchdog.SILENCE_CEILING_S`. `on_timeout="code"` because this caller can go
    on: a kill comes back as a CompletedProcess with `timed_out=True` and a
    `timeout_code`, never as an exception that would take the run with it.
    """
    return runlog.run_child(
        [VENV_PY, str(SCRIPTS / "index_footage.py"), str(path)],
        tool=WATCHDOG_TOOL, step=WATCHDOG_STEP, video=Path(path).stem,
        on_timeout="code", capture_output=True, text=True, **_env_kw())


def index_source(path):
    """Index one source, or raise `IndexFailed` saying why it has none.

    CF-0281: both halves are checked, because they fail separately. A non-zero
    exit is the 2026-09-18 shape (`index_footage.py` killed at its own 60 s
    ceiling inside a Vision sample); an exit of 0 with no usable index behind
    it would be a defect of the indexer, and either way what the pool gets is
    a source that cannot be cut from. A leftover half-file is removed here and
    not left for the next run to mistake for a cache hit.
    """
    out = _run_index(path)
    dest = shots_path(path)
    vid = Path(path).stem
    if getattr(out, "timed_out", False):
        # CF-0316: the watchdog took this operation down. Whatever half of an
        # index it left is removed here for the same reason CF-0281 removes
        # one - the next run must not read it as a cache hit - and the raise
        # below sends the stage to the topic's next candidate with the run
        # untouched.
        code = getattr(out, "timeout_code", None) or f"{WATCHDOG_STEP}_timeout"
        silent = getattr(out, "silent_s", None)
        ceiling = getattr(out, "ceiling_s", None) or watchdog_ceiling()
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise IndexTimedOut(
            f"index_footage.py went quiet on {vid} and was taken down by the "
            f"CF-0316 watchdog ({code}"
            + (f", silent for {int(round(float(silent)))} s" if silent is not None else "")
            + (f" of {int(round(float(ceiling)))} s allowed" if ceiling is not None else "")
            + "). The media is in the cache and no index was written, so this id "
              "is not a source; the run is not dropped and the topic's attempt is "
              "not spent - the stage goes on to the next candidate (CF-0316).",
            code=code, silent_s=silent, ceiling_s=ceiling)
    problems = shot_schema.file_problems(dest)
    if out.returncode == 0 and not problems:
        return None
    err = (out.stderr or "").strip()
    last = err.splitlines()[-1] if err else ""
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass
    why = problems[0] if problems else f"{dest.name}: written, but unreadable since"
    raise IndexFailed(
        f"index_footage.py left no usable index for {vid}: exit {out.returncode}"
        + (f" - {last}" if last else "")
        + f"; {why}. The media is in the cache and is not worth another "
          f"download - what is missing is the index, so this id is not a "
          f"source and the topic's next candidate is taken instead (CF-0281)")


# CF-0239: one line on stdout when a source's attempt starts and one when it
# ends, so the stage has a voice of its own between its first and its last
# line. The machine record of the same attempt is the `ingest` start/done pair
# in RUN_EVENTS.jsonl (topic and size_mb are in its params); these lines are
# the operator's reading of it, not a second event.
SOURCE_START_LINE = "SOURCE start {vid} topic {topic} rung {rung}"
SOURCE_DONE_LINE = "SOURCE done {vid} topic {topic} rung {rung}: {outcome}, {size}, {secs} s"


def file_mb(path):
    """Size of the file at `path` in MB (one decimal), None when unreadable."""
    try:
        return round(Path(path).stat().st_size / 1e6, 1)
    except (OSError, TypeError, ValueError):
        return None


def source_done_line(vid, topic, rung, outcome, size_mb, seconds, cached=None):
    size = "size ?" if size_mb is None else f"{size_mb} MB"
    if cached:
        size += " (cache)"
    return SOURCE_DONE_LINE.format(vid=vid, topic=topic, rung=rung, outcome=outcome,
                                   size=size, secs=int(round(seconds)))


def dedup_line(alias, canonical, distance):
    return DEDUP_LINE.format(alias=alias, canonical=canonical, distance=distance)


def alias_line(rec):
    """The DEDUP line of one alias record, whichever check decided it."""
    if rec.get("method") == shot_copy.METHOD:
        return SHOT_COPY_LINE.format(alias=rec["video_id"], canonical=rec["alias_of"],
                                     share=rec.get("shot_share"),
                                     matched=rec.get("matched_shots"),
                                     distance=rec.get("distance"))
    return dedup_line(rec["video_id"], rec["alias_of"], rec.get("distance"))


def _refusal_sentence(vid, attempts, rung):
    """The `error` of a final refusal, written to be read on its own: the
    CF-0232 funnel copies it into its `detail` verbatim, where nothing else of
    this report is in reach."""
    return attempts[-1]["error"] if attempts else "?"


def cached_already(vid):
    """Whether the factory-wide cache can answer for this id without asking
    YouTube anything. Pacing reads it so a re-run of a batch whose sources are
    all cached does not sit through a wait per source: a cache hit is not a
    request, and it neither earns a pause nor owes one."""
    try:
        return cache_entry_of(vid) is not None
    except (OSError, ValueError):
        return False


def _pause_seconds(pause):
    """A wait drawn from the configured range, so the gaps are not a metronome."""
    if pause is None:
        return 0.0
    if isinstance(pause, (int, float)):
        return float(pause)
    low, high = pause
    return random.uniform(float(low), float(high))


def candidate_records(topic):
    """`evidence.footage_candidates` as {video_id: record}, for the batches
    that carry it (CF-0129 part 1: Trend Hunter's step 5b, since 2026-09-16).

    A batch written before that has no such key, which is "nothing was said
    about the candidates", not "there are none": the ids in
    `evidence.youtube_video_ids` are then all this stage knows about them, and
    that is enough to walk them in order. Nothing here requires the key to
    exist, and nothing here trusts its shape.
    """
    recs = (topic.get("evidence") or {}).get("footage_candidates")
    out = {}
    if isinstance(recs, list):
        for r in recs:
            if isinstance(r, dict) and isinstance(r.get("video_id"), str):
                vid = r["video_id"]
                if is_direct(vid):
                    # CF-0665: the stage knows an archive file by its file id;
                    # the Trend Hunter's own id rides along. CF-0567: an own
                    # capture the same way.
                    r = dict(r, candidate_id=r.get("candidate_id") or vid)
                    vid = source_file_id(vid)
                out[vid] = r
    return out


def walk_state(topic):
    """One topic's bookkeeping for the CF-0129 walk.

    `queue` is the candidate order Trend Hunter chose - round-robin by nature
    of footage, so the first two ids are of different natures and the most
    likely pair to survive the CF-0080 fingerprint. `same_cut` is the
    re-uploads of each candidate: never a second source (the dedup would
    collapse them into the candidate itself), only a stand-in for a candidate
    that is not there at all.
    """
    ev = topic.get("evidence") or {}
    # CF-0665: an archive candidate (`nasa:<id>` / `commons:<pageid>`) is walked,
    # fetched and reported under its file id (`nasa-<id>` / `commons-<pageid>`).
    # CF-0567: an own capture (`own_capture:<id>`) the same way, `own_capture-<id>`.
    ids = [source_file_id(i) for i in (ev.get("youtube_video_ids") or [])
           if isinstance(i, str)]
    ids = list(dict.fromkeys(ids))
    recs = candidate_records(topic)
    same_cut = {}
    for vid in ids:
        alt = (recs.get(vid) or {}).get("same_cut")
        same_cut[vid] = ([source_file_id(a) for a in alt
                          if isinstance(a, str) and source_file_id(a) not in ids]
                         if isinstance(alt, list) else [])
    shortfall = ev.get("footage_candidate_shortfall")
    return {"queue": deque(ids), "offered": ids, "same_cut": same_cut,
            # CF-0302: the candidate records themselves, for the nature the
            # ceiling is read against and the length Trend Hunter measured.
            "records": recs,
            "tried": [], "attempts": 0, "pending": 0,
            "shortfall": shortfall if isinstance(shortfall, dict) else None}


def seed_prior(st, prior, barred=()):
    """Carry one topic's spent attempts into a second pass (CF-0299).

    `prior` is `{"tried": [...], "attempts": n}` as the previous run left it,
    `barred` the ids no pass may register again (the sieve's refusals). Both
    end up in `tried`, which the walk skips for free; `attempts` is the count
    the cap is measured against and is never lowered by re-reading the report.
    A topic with no prior is untouched, so the first pass of a batch behaves
    exactly as it did before this task.
    """
    if not prior and not barred:
        return st
    tried = list((prior or {}).get("tried") or [])
    for vid in barred or ():
        if vid not in tried:
            tried.append(vid)
    for vid in tried:
        if vid not in st["tried"]:
            st["tried"].append(vid)
    spent = (prior or {}).get("attempts")
    st["attempts"] = max(st["attempts"],
                         spent if isinstance(spent, int) else len(st["tried"]))
    return st


def topic_skip(tid, code, reason):
    """A topic this stage drops, in the shape the CF-0232 funnel reads out of
    `skipped_topics[]` - the same four keys Trend Hunter writes.

    CF-0318: `COMPLIANCE_SKIP_CODE` is the one code that cannot be written
    here. A compliance verdict stopped taking topics off this stage on
    2026-09-23, and the guard is what makes "no new record carries that code"
    a fact of the code rather than a promise in a comment - the same job the
    guard in `refusal_code()` does for its own vocabulary.
    """
    if code == COMPLIANCE_SKIP_CODE:
        raise ValueError(
            f"{STAGE_NAME} does not skip a topic for its compliance verdict "
            f"any more (CF-0318), so '{COMPLIANCE_SKIP_CODE}' is a historical "
            f"code: read out of reports written before 2026-09-23, never "
            f"written again. A topic at `review` is fetched like any other; "
            f"what its verdict blocks is publication, and that is recorded by "
            f"agents/compliance-checker in publish/publication-holds.json.")
    return {"topic_id": tid, "reason_code": code, "reason": reason,
            "stage": STAGE_NAME}


def compliance_skip(tid, screening):
    """The record for a topic the compliance artifact takes off this stage's
    hands, or None if it does not (CF-0265).

    Two outcomes, each with its own code and a `reason` the funnel copies into
    its `detail` verbatim - so each sentence is written to be read with no
    other file open, and says which of the two kinds of loss this is.

    Both are about a *slot*, never about a verdict. There was a third until
    CF-0318, for a topic at `review`, and it is gone: the verdict blocks the
    publication of the video, not its making, so a `review` topic is walked
    here exactly like a `clear` one. Compliance takes a topic off this stage
    only when it gave the batch no slot for it (`reserve[]`) or when it never
    saw the topic at all.
    """
    if not screening.ran:
        return None                      # nothing judged yet: fetch as before
    if tid in screening.reserve:
        return topic_skip(
            tid, RESERVE_SKIP_CODE,
            "compliance judged this topic eligible and the batch had no slot "
            "left for it, so it is unused reserve (02-compliance-checker.json "
            "-> reserve[], CF-0265). Not a refusal of the footage stage and not "
            "a fault of the topic: no footage is fetched for it, because "
            "downloads, YouTube quota and the indexing time of every source "
            "would be spent on a topic nothing downstream opens. It is fetched "
            "the day it takes a slot.")
    if tid not in screening.verdict:
        return topic_skip(
            tid, NOT_SCREENED_CODE,
            "02-compliance-checker.json exists and carries no verdict for this "
            "topic - it is in neither results[] nor reserve[]. Refused here "
            "rather than fetched: downloading material nobody has judged is the "
            "worse error, and a topic that reached no verdict would be refused "
            "downstream anyway, after the downloads had been paid for "
            "(CF-0265). Re-run the compliance pass over the whole shortlist.")
    return None


def refusal_code(sources, lost=(), index_failed=(), sieved=(), too_long=()):
    """The code `topic_refusal()` refuses a topic with, and the only place one
    is chosen (CF-0307).

    `no_second_source` when the topic holds at least one source - the case the
    floor exists for. A topic that got nothing is not a second-source problem
    and takes the code for the whole of its loss, in the priority CF-0281,
    CF-0299 and CF-0302 settled: a download YouTube refused outranks an index
    that never finished, both outrank a source the sieve took (the first two
    are defects, the third is the stage working), and last of all comes a
    candidate refused on its metadata, which cost the topic no download, no
    index and not even one of its four attempts. `no_source` when there was
    nothing to try at all.

    Every code returned here is in `TOPIC_REFUSAL_CODES`, which is also
    `SLOT_FREEING_CODES` - the guard below is what keeps those two facts one
    fact. `shared/runlog/funnel.py` reads the same words out of the record.
    """
    if sources:
        code = TOPIC_REFUSAL_CODE
    elif lost:
        code = FUNNEL_REASON_CODE
    elif index_failed:
        code = INDEX_FUNNEL_CODE
    elif sieved:
        code = next(iter(sieved)).get("reason_code") or SIEVE_FOREIGN_CODE
        if code == HOST_SHOW_CODE:
            code = SIEVE_FOREIGN_CODE           # CF-0817, see HOST_SHOW_CODE
    elif too_long:
        code = TOO_LONG_CODE
    else:
        code = TOPIC_NO_SOURCE_CODE
    if code not in TOPIC_REFUSAL_CODES:
        raise ValueError(
            f"{code!r} is a topic refusal this stage can write and not one of "
            f"TOPIC_REFUSAL_CODES {TOPIC_REFUSAL_CODES} - a refusal outside "
            f"that tuple frees no slot (CF-0307) and is a word the funnel's "
            f"FUNNEL_CODES does not know. Add it to the tuple.")
    return code


def split_losses(mine, earlier=(), sieved=()):
    """The four kinds of loss `topic_refusal()` is handed, out of the failed
    records of the pass that refuses the topic (`mine`), the ones earlier
    passes wrote for it (`earlier`, CF-0308) and the sources this pass's
    sieve took (`sieved`, `{video_id, reason_code, reason}`).

    One id is one loss: the first record of it wins, in the order this pass,
    this sieve, earlier passes. The split is the funnel's
    (`shared/runlog/funnel.py`, step `two_sources`): `index_failed`, a sieve
    code and `source_too_long` are their own kinds, anything else - the
    funnel reads a record with no code as `fetch_failed` too - is a download
    YouTube did not hand over (CF-0302: a candidate refused for its length
    was never asked for, so it is not in `lost`)."""
    seen = set()
    out = {"lost": [], "index_failed": [], "sieved": [], "too_long": []}

    def fresh(vid):
        if not vid or vid in seen:
            return False
        seen.add(vid)
        return True

    for f in mine:
        if fresh(f.get("video_id")):
            _file_loss(out, f)
    for r in sieved:
        if fresh(r.get("video_id")):
            out["sieved"].append(dict(r))
    for f in earlier:
        if fresh(f.get("video_id")):
            _file_loss(out, f)
    return out


def _file_loss(out, f):
    code = f.get("reason_code")
    if code in (LICENCE_CODE, LICENCE_CHANGED_CODE):
        # CF-0663: refused on its licence before anything was asked of
        # YouTube - nothing it may take, not a lost download. CF-0665: the
        # same for an archive file whose licence changed.
        return
    if code == INDEX_FUNNEL_CODE:
        out["index_failed"].append(f["video_id"])
    elif code == TOO_LONG_CODE:
        out["too_long"].append(f)
    elif code in SIEVE_REFUSAL_CODES:
        out["sieved"].append({"video_id": f["video_id"], "reason_code": code,
                              "reason": f.get("error") or f.get("reason")})
    else:
        out["lost"].append(f["video_id"])


def topic_refusal(tid, st, sources, aliased, lost, wanted=SOURCES_WANTED,
                  max_attempts=MAX_ATTEMPTS_PER_TOPIC, index_failed=(),
                  sieved=(), too_long=()):
    """The record of a topic refused for standing below the source floor.

    The funnel copies `reason` into its `detail` verbatim, so it is written to
    be read on its own: how many sources the topic ended with, how many of its
    candidates were tried, what became of the rest (a re-upload of a source it
    already had, a failed fetch, an unused candidate the attempt cap cut off),
    and whether Trend Hunter had already recorded a thin pool for it.

    The code is chosen by `refusal_code()` - one place, one vocabulary
    (`TOPIC_REFUSAL_CODES`), and that vocabulary is what frees a slot
    (`SLOT_FREEING_CODES`, CF-0307). Here only the sentence is built.

    CF-0281: `lost` is the ids YouTube refused and `index_failed` the ids that
    came down and could not be indexed. They are counted the same - neither is
    a source - and named separately, because only the first is YouTube's doing
    and the two are fixed in different places. A topic that got nothing takes
    the code for the whole of its loss: `index_failed` when every candidate was
    lost that way, and `fetch_failed` when any of them was a download YouTube
    refused - a mixed loss is never rounded down to our half of it. The funnel
    now owns the same rule (shared/runlog/funnel.py: `INDEX_FAILED` in
    `FUNNEL_CODES`, and the `two_sources` step splits `failed[]` by the
    `reason_code` it reads here), so this record and the funnel's own reading
    of the batch reach the same word instead of one contradicting the other.
    The `reason` sentence names both causes whichever code won.
    """
    n = len(sources)
    index_failed = list(index_failed)
    sieved = [dict(s) for s in sieved]
    too_long = [dict(t) for t in too_long]
    code = refusal_code(sources, lost, index_failed, sieved, too_long)
    # CF-0302: a candidate refused over the duration ceiling was never
    # downloaded and cost no attempt, so it is neither "tried" nor left
    # "unused" - it is its own line in the sentence below.
    over = [t.get("video_id") for t in too_long]
    tried, offered = st["tried"], st["offered"]
    unused = [v for v in offered if v not in tried and v not in over]
    if n:
        reason = (f"{n} canonical source(s) after CF-0080 dedup, floor is {wanted} "
                  f"(CF-0129); {len(tried)} of {len(offered)} candidate(s) tried")
    elif lost or index_failed or sieved or too_long:
        # The code itself came from `refusal_code()` above - here only the
        # sentence that goes with it.
        reason = (f"no source at all, floor is {wanted} (CF-0129); "
                  f"{len(tried)} candidate(s) tried and every one was lost"
                  if tried else
                  f"no source at all, floor is {wanted} (CF-0129); not one of "
                  f"its {len(offered)} candidate(s) was worth a download")
    else:
        reason = (f"no source at all, floor is {wanted} (CF-0129); the topic "
                  f"offered no candidate video to fetch"
                  if not offered else
                  f"no source at all, floor is {wanted} (CF-0129); none of its "
                  f"{len(offered)} candidate(s) was tried")
    if aliased:
        reason += (f"; {len(aliased)} was a re-upload of a source it already had "
                   f"({', '.join(aliased)})" if len(aliased) == 1 else
                   f"; {len(aliased)} were re-uploads of sources it already had "
                   f"({', '.join(aliased)})")
    if lost:
        reason += f"; {len(lost)} failed to fetch ({', '.join(lost)})"
    if index_failed:
        # CF-0281: said in its own words - these came down cleanly and are in
        # the cache; what is missing is the index, and a source with no index
        # backs no phrase. Never folded into "failed to fetch".
        reason += (f"; {len(index_failed)} downloaded but failed to index "
                   f"({', '.join(index_failed)})")
    if sieved:
        # CF-0299: the one loss whose cause is visible in the footage itself,
        # so the record says which source was taken and what was seen in it -
        # a reader of this sentence must not have to open a second file to
        # learn that the topic's second source was somebody else's film.
        reason += ("; " + str(len(sieved)) + " indexed and then taken by the "
                   "source sieve (CF-0299): "
                   + "; ".join(f"{s.get('video_id')} - {s.get('reason')}"
                               for s in sieved))
    if too_long:
        # CF-0302: said in its own words and never folded into a failure -
        # nothing was downloaded, no attempt was spent, and the reader has to
        # be able to see that the candidate was refused for its length alone.
        reason += ("; " + str(len(too_long)) + " refused before the download "
                   "as too long for indexing (CF-0302, no attempt spent): "
                   + "; ".join(f"{t.get('video_id')} "
                               f"{int(t.get('duration_seconds') or 0)} s over the "
                               f"{int(t.get('ceiling_seconds') or 0)} s ceiling for "
                               f"'{t.get('nature')}'" for t in too_long))
    if unused and st["attempts"] >= max_attempts:
        reason += (f"; the {max_attempts}-attempt cap stopped it with "
                   f"{len(unused)} candidate(s) unused ({', '.join(unused)})")
    elif unused:
        reason += f"; {len(unused)} candidate(s) left untried ({', '.join(unused)})"
    elif offered:
        reason += "; it had no other candidate to try"
    if st["shortfall"]:
        why = st["shortfall"].get("reason") or "thin candidate pool"
        reason += f"; Trend Hunter had already recorded a thin pool: {why}"
    record = topic_skip(tid, code, reason)
    record.update({
        "wanted": wanted,
        "sources": list(sources),
        "attempts": st["attempts"],
        "candidates": list(offered),
        "tried": list(tried),
        "unused": unused,
        "aliased": list(aliased),
        "failed": list(lost),
        # CF-0281: the ids that came down and have no index, kept apart from
        # `failed` so a reader never has to guess which fault this was.
        "index_failed": index_failed,
        # CF-0299: the ids that were fetched, indexed, described - and then
        # taken by the source sieve. Each carries its own `reason_code` and
        # the sentence above quotes its `reason`.
        "sieved": sieved,
        # CF-0302: the candidates refused over the duration ceiling, with the
        # length that was measured and the ceiling it broke. Kept apart from
        # every list above: these were never fetched and cost no attempt.
        "too_long": too_long,
        "candidate_shortfall": st["shortfall"],
    })
    return record


def ingest(topics, verdict, batch_name, max_per_topic=MAX_ATTEMPTS_PER_TOPIC,
           skip_index=False,
           fetch=fetch_source, index=index_source,
           fingerprint=source_fingerprint.load_or_make, log=print,
           sleep=time.sleep, pause=FETCH_PAUSE_SECONDS, is_cached=cached_already,
           wanted=SOURCES_WANTED, prior=None, barred=None, already=None,
           sieved=None, ceiling=None, measure=measure_candidate,
           measurements=None, depth_floor=pool_depth.POOL_DEPTH_FLOOR,
           depth_cache=None, depths=None, workers=1, vision_sockets=None,
           deadline=None, cut=None, on_source=None, pooled=None, pool_barred=None,
           earlier=None, origins=None, tracker=None):
    """Fetch, dedup and index every topic's evidence videos.

    CF-0715: `tracker` is the root's `footage_progress.Tracker` (or None):
    the topics go into `<batch>/work/footage-progress.json` as queued, a topic
    compliance drops as refused, every walk step with the sources the topic
    holds and the candidates it spent, the CF-0129 refusals at the end -
    `main()` settles the file from the written report. A progress write never
    stops the walk.

    CF-0663: `origins` is the channel's footage-origin.json (None or {} for a
    channel without one): every `fetched[]` record carries `rights`
    (`source_rights.rights_of`), the record goes to the cache entry through
    the fetch, and a candidate whose licence is refused never reaches it.

    Returns (fetched, aliases, skipped, failed, sources_by_topic):
      fetched   - [{video_id, path, topic_id}] canonical sources only
      aliases   - [{topic_id, video_id, alias_of, distance, fingerprint_kind,
                    offset_seconds, overlap_frames, path}]
      skipped   - [{topic_id, reason_code, reason, stage, ...}] - one record
                  per topic this stage drops, in the CF-0232 funnel's shape:
                  the two decided by reading compliance before any download
                  (`reserve_unused`, `not_screened`), or
                  the CF-0129 floor (`no_second_source` and its two neighbours)
      failed    - [{video_id, topic_id, error, reason_code,
                    refused_at, attempts}] - one record per id this stage did
                  not get, `reason_code` being CF-0232's funnel code
      sources_by_topic - {topic_id: [canonical video_id, ...]}

    `max_per_topic` is the CF-0129 attempt cap - distinct candidate ids the
    topic may spend - and `wanted` the number of canonical sources it is trying to reach.

    `fetch`, `index`, `fingerprint` are injectable so tests run without
    yt-dlp, CLIP or a network; `sleep`, `pause` and `is_cached`
    so they run without waiting and without the real cache.
    `fetch` may return a plain path instead of a `FetchResult` - it is then
    read as a real download, which is the conservative side for pacing.

    `verdict` is the `Screening` `verdicts()` returns, or the bare
    `{topic_id: verdict}` dict it used to return (see `as_screening`).

    CF-0299, the two arguments that make a *second* pass over a batch
    possible. The source sieve runs after the description pass, which is after
    this function has returned, so a topic whose source the sieve takes away
    has to be able to spend its remaining candidates without spending its
    attempt cap twice:

      `prior`   {topic_id: {"tried": [video_id, ...], "attempts": n}} - what
                the topic already spent in the run that wrote the report. The
                walk starts from that count, so the cap bounds the videos a
                topic touches across *the batch*, not per invocation.
      `barred`  {topic_id: [video_id, ...]} - ids this topic must never
                register as a source again, the ones the sieve refused *for
                it*. Per topic and not a flat list on purpose: `on_topic` is
                an answer about this topic, and a source that is somebody
                else's film here may be exactly the right footage there. They
                are put into the topic's `tried` list, where the walk skips
                them for free - they already cost their attempt.
      `earlier` {topic_id: [failed record, ...]} - CF-0308: the `failed[]`
                records earlier passes over the batch already wrote for the
                topic (the report's own, the sieve's from an earlier run
                included). They are not returned again - the report holds
                them - and they change nothing in the walk; they are read only
                when the topic is refused, so that the code chosen for a topic
                that ended with nothing is the code for the *whole* of its
                loss, the way `shared/runlog/funnel.py` reads it off the
                report's `failed[]`. Without them a topic whose candidate
                the source refused on the first pass and whose last sources the
                sieve took was written `source_burned_text` by the stage and
                read `fetch_failed` by the funnel (Rennick, `1541Z`).
    CF-0302, the duration ceiling. `ceiling` is the `Ceiling` record
    `duration_ceiling()` reads from the channel config (None means the
    measured defaults, which is the state of every caller that has nothing to
    say about it - the ceiling is a safety net and is never off). `measure` is
    the seam that answers how long a candidate is without downloading it, so
    tests make no request; `measurements` is an optional list this function
    appends one record to per candidate it measured, which is how the report
    can say what was measured, from where, and what could not be measured at
    all. A candidate over its nature's ceiling is refused before the fetch,
    with `reason_code: source_too_long` and `refused_at: metadata`, and the
    topic's attempt is *not* spent on it.

      `already` {topic_id: [(video_id, path), ...]} - the sources the topic
                keeps from the previous pass. They are registered before the
                walk, with their fingerprints, so the floor is counted with
                them in and a new candidate is deduped against the footage the
                topic really holds - and they are *not* fetched, indexed or
                put into `fetched` again: the report that already lists them
                is the one being amended.

    CF-0304, the depth floor. `wanted` counts sources; `depth_floor` counts
    what is in them - shots of the topic's pool the Video Editor's own pre-cut
    gate would leave standing (`pool_depth.py`). A topic that holds its
    canonical sources and is still under the floor goes on taking candidates,
    inside the same CF-0129 cap and the same CF-0302 ceiling. It is never
    refused for depth: the count is an upper bound on what
    `check_anchor_coverage.py` measures against real anchors, and that stage
    owns `pool_too_thin`. `depth_floor=0` turns the question off and restores
    the pre-CF-0304 walk exactly. `depth_cache` is the directory the indexes
    are read from (the tests' seam, `pool_depth.CACHE` otherwise), and `depths`
    an optional list this function appends one `pool_depth.depth_record()` to
    per topic it walked - which is how the report can say what every pool ended
    up holding, not only the ones that were short.

    CF-0332, `workers`. With 1 (the default) the walk is the one described
    above, topic after topic. With N > 1 the first pass and the top-up pass
    walk up to N topics at once, each topic still walked by one thread in its
    own order; the downloads stay strictly one at a time behind one lock (with
    the same pacing), so what overlaps is indexing - `index_footage.py`, where
    the stage's machine time is. A source two topics share is fingerprinted and
    indexed under a per-path lock, so the second topic finds the first one's
    index instead of writing the same `shots.json` beside it. The lists this returns are put
    back in topic order after each parallel pass, so a report does not depend
    on which thread finished first. `vision_sockets` is an optional list of
    Vision worker socket paths, one per worker slot (CF-0058 / CF-0332); None
    keeps every slot on the machine-wide worker.

    CF-0429, the wall-clock deadline. `deadline` is a `Deadline` (None: no
    deadline, the walk above exactly). Once it has passed, nothing new is
    started: no metadata probe, no download, no fingerprint, no
    `index_footage.py`. A candidate caught in the middle -
    its download or its index killed by `Deadline`'s watcher, or downloaded
    and not yet indexed - is not a source and not a loss either: it is not put
    in `failed[]` (which would make it "already tried" for the next call), its
    attempt is given back, and it goes into `cut` - an optional list this
    function appends one record to per candidate the deadline took, the
    untried rest of the topic's queue included, `outcome: wall_ceiling` (the
    root step's CF-0426 word). `on_source(fetched, aliases, failed,
    sources_by_topic)` is called after every source that got in, so a caller
    can put it on disk before anything else can go wrong.

    CF-0325, the pool. `pooled` {topic_id: [(video_id, path), ...]} is the
    pool sources `pool_sources.vet()` let through for a topic - matched by
    Trend Hunter (`topics[].pool.matched`) and checked to be the topic's work.
    They are registered when the topic's walk starts, deduped against each
    other by the CF-0080 fingerprint (a re-upload goes to `aliases` with
    `from_pool: true`), and go into `fetched` with `from_pool: true` and into
    `sources_by_topic` - so the source floor and the depth floor count them
    and the walk downloads only what is still missing. Nothing is fetched or
    indexed for them. A topic compliance does not let through (CF-0265) gets
    none. `pool_barred` {topic_id: [video_id, ...]} is the pool sources the
    check refused for what they are: put into the topic's `tried` for free, so
    the walk does not admit as a candidate what the check refused. Neither
    costs an attempt.
    """
    screening = as_screening(verdict)
    verdict = screening.verdict
    # CF-0302: with no ceiling handed in, the measured defaults apply. A
    # caller that says nothing gets the safety net, never no net at all.
    if ceiling is None:
        ceiling = Ceiling(limits=dict(DEFAULT_MAX_SOURCE_SECONDS), configured=False,
                          config_path=None, key=CEILING_KEY)
    measured = measurements if isinstance(measurements, list) else []
    depth_records = depths if isinstance(depths, list) else []
    depth_floor = int(depth_floor or 0)
    fetched, aliases, skipped, failed = [], [], [], []
    sources_by_topic = {}
    canon_by_topic = {}        # topic_id -> [(video_id, fingerprint)] of this topic
    held_paths = {}            # topic_id -> {video_id: media path} (CF-0464)
    cuts = cut if isinstance(cut, list) else []
    indexed_at = {}            # topic_id -> when its newest source got in (CF-0715)

    def note(method, *args):
        """CF-0715: one call on the progress tracker; never raises."""
        if tracker is None:
            return
        try:
            getattr(tracker, method)(*args)
        except Exception as e:
            log(f"  footage progress not noted ({method}): {type(e).__name__}: {e}")

    def past():
        """CF-0429: has the deadline come? Always False without one."""
        return deadline is not None and deadline.passed()

    def cut_one(tid, vid, at):
        if any(c["topic_id"] == tid and c["video_id"] == vid for c in cuts):
            return
        cuts.append({"video_id": vid, "topic_id": tid, "outcome": WALL_CEILING,
                     "refused_at": WALL_CEILING, "at": at, "task": WALL_TASK,
                     "attempt_spent": False})

    def cut_rest(tid):
        """The candidates of `tid` the walk will not get to any more."""
        st = state[tid]
        for vid in list(st["queue"]):
            if vid not in st["tried"]:
                cut_one(tid, vid, CUT_BEFORE)
        st["queue"].clear()

    def wall_miss(rung, at):
        return {"rung": rung, "wall_ceiling": True,
                "cut_at": at, "error": f"{WALL_CEILING}: the deadline has passed "
                                       f"({deadline.cause}) - {WALL_TASK}"}
    network_calls = [0]        # only a real request owes the next one a pause
    state = {}                 # topic_id -> walk_state(), in topic order

    # CF-0332: the guards parallel walks need. On the sequential path every one
    # of them is a no-op, so workers=1 is the pre-CF-0332 walk exactly.
    workers = max(1, int(workers or 1))
    parallel = workers > 1
    fetch_guard = threading.Lock() if parallel else contextlib.nullcontext()
    path_locks, path_locks_guard = {}, threading.Lock()
    run_kw = {}
    if parallel:
        # A worker thread starts with an empty runlog stack, and os.environ's
        # RUNLOG_PARENT is shared by every thread - so the ingest event of each
        # attempt is chained to the caller's event taken here, once.
        try:
            run_kw = {"parent": runlog.current_id(),
                      "batch_dir": runlog.current_batch_dir()}
        except Exception:
            run_kw = {}

    def path_lock(path):
        if not parallel:
            return contextlib.nullcontext()
        with path_locks_guard:
            return path_locks.setdefault(str(Path(path).resolve()), threading.Lock())

    # CF-0299: the sources a second pass keeps. Registered before anything is
    # walked, so `canon_count()` and the dedup see the topic as it stands.
    for tid, entries in (already or {}).items():
        canon = canon_by_topic.setdefault(tid, [])
        held = sources_by_topic.setdefault(tid, [])
        for vid, path in entries:
            if vid in held:
                continue
            fp = None
            try:
                fp = fingerprint(path)
            except Exception as e:
                log(f"  fingerprint failed for {vid}: {e}", file=sys.stderr)
            canon.append((vid, fp))
            held.append(vid)
            held_paths.setdefault(tid, {})[vid] = str(path)

    def shot_copy_check(tid, vid, path, fp, record):
        """CF-0464: is the indexed source `vid` the same video as one the topic
        already holds, by the shot lists (`shot_copy.py`)? The fingerprint
        above compares whole frames and misses an upload that was cropped or
        pillarboxed (you-can-see-everything, 2026-10-01T0200Z: 14.2 against
        12.0); the shots do not care.

        Returns None when it is not a copy - the caller registers it as usual -
        or "alias" / "swapped". "alias": `vid` is filed in `aliases` as a
        re-upload of the held one and is not a source. "swapped": `vid` is the
        better copy (`shot_copy.keeper()`), so it takes the held one's place in
        `sources_by_topic`, the canonical list and `fetched` (`record`, the
        record the caller would have appended) and the held one is filed as
        its alias. A swap is only made for a source this walk itself admitted
        (it has a `fetched` record); a source an earlier pass handed in through
        `already=` is what the batch already wrote about, and stays.
        Either way the topic's count does not grow, so the walk goes on to its
        next candidate exactly as after a CF-0080 alias.
        """
        mine = held_paths.setdefault(tid, {})
        canon = canon_by_topic.setdefault(tid, [])
        held = sources_by_topic.setdefault(tid, [])
        for cvid in list(held):
            cpath = mine.get(cvid)
            if not cpath or cvid == vid:
                continue
            try:
                cmp = shot_copy.compare(shots_path(cpath), shots_path(path))
            except Exception as e:     # a measure that fails never blocks a source
                log(f"  shot copy check failed for {vid} / {cvid}: "
                    f"{type(e).__name__}: {e}", file=sys.stderr)
                continue
            if not shot_copy.is_copy(cmp):
                continue
            ci = next((k for k, (v, _f) in enumerate(canon) if v == cvid), None)
            cfp = canon[ci][1] if ci is not None else None
            pos = next((k for k, f in enumerate(fetched)
                        if f.get("video_id") == cvid and f.get("topic_id") == tid), None)
            swap = (pos is not None and
                    shot_copy.keeper(shots_path(cpath), shots_path(path)) == "newcomer")
            alias, alias_path, alias_fp, keep, keep_fp = (
                (cvid, cpath, cfp, vid, fp) if swap else (vid, path, fp, cvid, cfp))
            fpc = None
            if alias_fp is not None and keep_fp is not None:
                fpc = source_fingerprint.compare(alias_fp, keep_fp)
            rec = {
                "topic_id": tid, "video_id": alias, "alias_of": keep,
                "distance": (fpc or {}).get("distance"),
                "fingerprint_kind": (alias_fp or {}).get("kind"),
                "offset_seconds": (fpc or {}).get("offset_seconds"),
                "overlap_frames": (fpc or {}).get("overlap_frames"),
                "path": str(alias_path),
                "method": shot_copy.METHOD,
                "shot_share": cmp["share"], "matched_shots": cmp["matched_shots"],
                "copy_kind": cmp["kind"],
                "kept_by": "quality" if swap else "held",
            }
            if swap:
                held[held.index(cvid)] = vid
                if ci is not None:
                    canon[ci] = (vid, fp)
                fetched[pos] = record
                mine.pop(cvid, None)
                mine[vid] = str(path)
                for a in aliases:       # CF-0080 aliases of the replaced copy
                    if a.get("topic_id") == tid and a.get("alias_of") == cvid:
                        a["alias_of"] = vid
            aliases.append(rec)
            log(alias_line(rec))
            return "swapped" if swap else "alias"
        return None

    def register_pooled(tid):
        """CF-0325: the topic's checked pool sources, in before its walk."""
        st = state[tid]
        for vid in (pool_barred or {}).get(tid) or ():
            if vid not in st["tried"]:
                st["tried"].append(vid)
        canon = canon_by_topic.setdefault(tid, [])
        held = sources_by_topic.setdefault(tid, [])
        for vid, path in (pooled or {}).get(tid) or ():
            if vid not in st["tried"]:
                st["tried"].append(vid)       # never walked again, no attempt
            if vid in held:
                continue
            fp = None
            try:
                fp = fingerprint(path)
            except Exception as e:
                log(f"  fingerprint failed for {vid}: {e}", file=sys.stderr)
            match = None
            if fp is not None:
                for cvid, cfp in canon:
                    if cfp is None:
                        continue
                    cmp = source_fingerprint.compare(fp, cfp)
                    if source_fingerprint.is_duplicate(cmp):
                        match = (cvid, cmp)
                        break
            if match:
                cvid, cmp = match
                aliases.append({
                    "topic_id": tid, "video_id": vid, "alias_of": cvid,
                    "distance": cmp["distance"],
                    "fingerprint_kind": fp.get("kind"),
                    "offset_seconds": cmp.get("offset_seconds"),
                    "overlap_frames": cmp.get("overlap_frames"),
                    "path": str(path), pool_sources.FETCHED_MARK: True})
                log(dedup_line(vid, cvid, cmp["distance"]))
                continue
            record = {"video_id": vid, "path": str(path), "topic_id": tid,
                      pool_sources.FETCHED_MARK: True,
                      source_rights.RIGHTS_KEY: rights_for(tid, vid),     # CF-0663
                      **candidate_of(tid, vid)}                           # CF-0665
            if shot_copy_check(tid, vid, path, fp, record):
                continue                       # CF-0464: a copy by its shots
            canon.append((vid, fp))
            held.append(vid)
            held_paths.setdefault(tid, {})[vid] = str(path)
            fetched.append(record)
        mine = [f["video_id"] for f in fetched
                if f.get("topic_id") == tid and f.get(pool_sources.FETCHED_MARK)]
        if mine:
            log(pool_sources.COUNTED_LINE.format(tid=tid, n=len(mine),
                                                 ids=", ".join(mine)))

    def pace(vid):
        """The wait between two real downloads (rung 0). Skipped in front of
        a source the cache already holds, and in front of the first one."""
        if not network_calls[0] or is_direct(vid):
            return          # CF-0665 / CF-0567: not YouTube - nothing to pace
        seconds = _pause_seconds(pause)
        if seconds > 0 and not is_cached(vid):
            sleep(seconds)

    def admit(tid, vid, path):
        """`_admit()` under the source's own lock (CF-0332): two topics that
        hold the same file never fingerprint or index it at the same time."""
        with path_lock(path):
            return _admit(tid, vid, path)

    def _admit(tid, vid, path):
        """Fingerprint, dedup and index one source that did come down, inside
        its own topic, against the same topic's canonical sources.

        Returns None when the source is in, or the `failed[]` record when its
        index did not finish (CF-0281). The index is taken *before* the id is
        registered anywhere: a source with no index is not a source, so it may
        not reach `fetched`, `sources_by_topic` or the topic's canonical
        fingerprint list - a later candidate compared against a phantom would
        be filed as a re-upload of a source that is not there.
        """
        canon = canon_by_topic.setdefault(tid, [])
        sources_by_topic.setdefault(tid, [])
        if past():
            # CF-0429: after the deadline nothing is admitted - not even a
            # fingerprint (ffmpeg) is started for it.
            return {"wall_ceiling": True}
        fp = None
        try:
            fp = fingerprint(path)
        except Exception as e:  # a fingerprint that fails never blocks indexing
            log(f"  fingerprint failed for {vid}: {e}", file=sys.stderr)

        match = None
        if fp is not None:
            for cvid, cfp in canon:
                if cfp is None:
                    continue
                cmp = source_fingerprint.compare(fp, cfp)
                if source_fingerprint.is_duplicate(cmp):
                    match = (cvid, cmp)
                    break
        if match:
            cvid, cmp = match
            aliases.append({
                "topic_id": tid, "video_id": vid, "alias_of": cvid,
                "distance": cmp["distance"],
                "fingerprint_kind": fp["kind"],
                "offset_seconds": cmp["offset_seconds"],
                "overlap_frames": cmp["overlap_frames"],
                "path": str(path),
            })
            log(dedup_line(vid, cvid, cmp["distance"]))
            return

        # CF-0281: the index comes first, and a source that has none is not
        # admitted at all.
        if not skip_index and not indexed_already(path, log=log):
            if past():
                return {"wall_ceiling": True}   # CF-0429: no new index_footage.py
            try:
                index(path)
            except Exception as e:
                if past():
                    # CF-0429: killed at the deadline (or it failed while the
                    # deadline came) - not an index failure of this video.
                    log(f"{WALL_CEILING.upper()} {vid}: index stopped at the "
                        f"deadline, not a source and not a loss")
                    return {"wall_ceiling": True}
                rec = {
                    "video_id": vid,
                    "topic_id": tid,
                    "error": str(e),
                    # not `fetch_failed`: the download worked and the media is
                    # in the cache. See INDEX_FUNNEL_CODE above.
                    "reason_code": INDEX_FUNNEL_CODE,
                    "refused_at": RUNG_INDEX,
                    "attempts": [{"rung": RUNG_INDEX, "error": str(e)}],
                    "path": str(path),
                    # Filled in after the walk: the candidate the CF-0129
                    # walk took in this one's place.
                    "replaced_by": [],
                    "sources_at_failure": list(sources_by_topic[tid]),
                }
                if isinstance(e, IndexTimedOut):
                    # CF-0316: the same absence, with the kill named beside it.
                    # `attempt_spent: False` is the CF-0302 shape and is read by
                    # the walk below, which gives the attempt back.
                    rec[WATCHDOG_CODE_KEY] = e.code
                    rec["silent_s"] = e.silent_s
                    rec["ceiling_s"] = e.ceiling_s
                    rec["attempt_spent"] = False
                    rec["refused_at"] = RUNG_INDEX
                    log(INDEX_TIMEOUT_LINE.format(
                        vid=vid, code=e.code,
                        silent=int(round(float(e.silent_s))) if e.silent_s is not None else "?",
                        ceiling=int(round(float(e.ceiling_s))) if e.ceiling_s is not None else "?"))
                else:
                    log(INDEX_FAILED_LINE.format(vid=vid, error=str(e)))
                failed.append(rec)
                return rec

        record = {"video_id": vid, "path": str(path), "topic_id": tid,
                  source_rights.RIGHTS_KEY: rights_for(tid, vid),         # CF-0663
                  **candidate_of(tid, vid)}                               # CF-0665
        # CF-0464: now that it has shots, is it a copy the fingerprint missed?
        copy = shot_copy_check(tid, vid, path, fp, record)
        if copy == "alias":
            return None
        indexed_at[tid] = pool_depth.now_z()                              # CF-0715
        if copy is None:
            canon.append((vid, fp))
            sources_by_topic[tid].append(vid)
            held_paths.setdefault(tid, {})[vid] = str(path)
            fetched.append(record)
        if on_source is not None:
            try:
                on_source(fetched, aliases, failed, sources_by_topic)
            except Exception as e:     # a flush that fails never stops the walk
                log(f"  could not flush after {vid}: {type(e).__name__}: {e}")
        return None

    def attempt(tid, vid, rung):
        """`_attempt()` with its two CF-0239 progress lines around it.

        The stage's own voice on stdout: `SOURCE start` the moment the
        download is about to begin, `SOURCE done` when the attempt is over,
        whatever its end - with the topic, the rung, the outcome in one word,
        the size of the file and the seconds it took. Both are flushed at
        once, so a log file or a pipe shows them while the walk is still on
        (on 2026-09-15 the stage's log stayed at 0 bytes for an hour). An
        attempt cut before its download started prints neither.
        """
        seen = {}
        try:
            res = _attempt(tid, vid, rung, seen)
        except BaseException as e:
            if "t0" in seen:
                progress(source_done_line(vid, tid, rung, f"error {type(e).__name__}",
                                          seen.get("size"), time.monotonic() - seen["t0"],
                                          seen.get("cached")))
            raise
        if "t0" in seen:
            progress(source_done_line(vid, tid, rung, attempt_outcome(tid, vid, res),
                                      seen.get("size"), time.monotonic() - seen["t0"],
                                      seen.get("cached")))
        return res

    def progress(line):
        log(line)
        try:
            sys.stdout.flush()
        except Exception:      # a closed or odd stdout never stops the walk
            pass

    def attempt_outcome(tid, vid, res):
        if res is None:
            if vid in sources_by_topic.get(tid, ()):
                return "source"
            for a in reversed(aliases):
                if a.get("video_id") == vid and a.get("topic_id") == tid:
                    return f"alias of {a.get('alias_of')}"
            return "not a source"
        for key in ("too_long", LICENCE_CHANGED_CODE, WALL_CEILING,
                    "index_timeout", "index_failed"):
            if res.get(key):
                return key
        return "fetch_failed"

    def _attempt(tid, vid, rung, seen):
        """One download attempt and, on success, the whole admit path.

        Returns None when the source is in, or the attempt record
        {rung, error} when it is not. CF-0107: one nested event per
        attempt (video = the id), so a retry's cost reads separately from the
        first pass and `params.fetch_failed` carries the error line.

        CF-0281: an index that does not finish is one of the ways an attempt
        does not end in a source, and the event has to say so. `runlog.run()`
        writes `failed` for an exception that leaves its block and `done` for
        anything else, so the failure is raised through it and caught here -
        the record `admit()` already wrote goes into `failed[]`, and the
        attempt record carries `index_failed` so the caller knows the refusal
        is on paper already and the topic's next candidate is the way on.
        """
        if not parallel:
            pace(vid)
        if past():
            return wall_miss(rung, CUT_BEFORE)      # CF-0429
        try:
            with runlog.run("footage-indexer", "ingest", video=vid,
                            name="ingest_batch.py", params={"topic": tid},
                            **run_kw):
                # CF-0332: one download at a time, whatever the worker count -
                # the pause and the request are taken under the same lock, so
                # parallel walks keep the pacing a sequential walk had.
                with fetch_guard:
                    if parallel:
                        pace(vid)
                    if past():
                        runlog.annotate(wall_ceiling=True, fetch_rung=rung)
                        return wall_miss(rung, CUT_BEFORE)
                    # CF-0333: the ceiling goes into the download too - the
                    # probe before the walk may have got no answer, and the
                    # download must not take a two-hour file just because
                    # nobody knew.
                    fkw = {}
                    archive = archive_source.is_archive(vid)
                    own = is_own_capture(vid)           # CF-0567
                    # CF-0567: an own capture has no ceiling.
                    limit = None if own else ceiling.seconds(nature_of(tid, vid))
                    if limit and fetch_takes_ceiling:
                        fkw["max_seconds"] = limit
                    if fetch_takes_rights:
                        fkw["rights"] = rights_for(tid, vid)    # CF-0663
                    if archive and fetch_takes_record:
                        # CF-0665: the archive file's candidate record and the
                        # channel's licence lists, for the direct download.
                        fkw["record"] = (state[tid].get("records") or {}).get(vid)
                        fkw["licences"] = (origins or {}).get("licences")
                    if own and fetch_takes_record:
                        # CF-0567: the candidate with the recording found.
                        fkw["record"] = own_capture_record(
                            vid, (state[tid].get("records") or {}).get(vid))
                    seen["t0"] = time.monotonic()
                    progress(SOURCE_START_LINE.format(vid=vid, topic=tid, rung=rung))
                    try:
                        result = fetch(vid, f"batch {batch_name}, topic {tid}", **fkw)
                    except LicenceChanged as e:
                        # CF-0665: the archive's licence is not the one the
                        # candidate was judged on - nothing came down.
                        runlog.annotate(licence_changed=True, fetch_rung=rung)
                        refuse_licence_changed(tid, vid, e.record, rung)
                        return {"rung": rung, "error": str(e),
                                LICENCE_CHANGED_CODE: True}
                    except TooLong as e:
                        network_calls[0] += 1
                        runlog.annotate(too_long=True, fetch_rung=rung,
                                        duration_s=e.seconds)
                        refuse_too_long(tid, vid, e.seconds, limit, rung)
                        return {"rung": rung, "error": str(e),
                                "too_long": True}
                    except RuntimeError as e:
                        network_calls[0] += 1
                        if past():
                            # CF-0429: the watcher killed this download at the
                            # deadline - nothing the source said about the video.
                            runlog.annotate(wall_ceiling=True, fetch_rung=rung)
                            return wall_miss(rung, CUT_DOWNLOAD)
                        runlog.annotate(fetch_failed=str(e), fetch_rung=rung)
                        return {"rung": rung, "error": str(e)}

                    path, cached = result if isinstance(result, tuple) else (result, False)
                    if not cached and not (archive or own):
                        # CF-0665: an archive download is not a video-site
                        # call - it does not pace the next one.
                        network_calls[0] += 1
                    seen["cached"] = bool(cached)
                    seen["size"] = file_mb(path)
                    if seen["size"] is not None:
                        runlog.annotate(size_mb=seen["size"])     # CF-0239
                bad = admit(tid, vid, path)
                if bad is not None and bad.get("wall_ceiling"):
                    runlog.annotate(wall_ceiling=True, fetch_rung=rung)
                    return wall_miss(rung, CUT_INDEX)
                if bad is not None:
                    killed = bad.get(WATCHDOG_CODE_KEY)
                    runlog.annotate(index_failed=bad["error"], fetch_rung=rung,
                                    **({WATCHDOG_CODE_KEY: killed,
                                        "silent_s": bad.get("silent_s")} if killed else {}))
                    if killed:
                        # CF-0316: the same failure path, with the kill kept
                        # visible so the walk can decline to spend the attempt.
                        raise IndexTimedOut(bad["error"], code=killed,
                                            silent_s=bad.get("silent_s"),
                                            ceiling_s=bad.get("ceiling_s"))
                    raise IndexFailed(bad["error"])
                return None
        except IndexTimedOut as e:
            return {"rung": RUNG_INDEX, "error": str(e),
                    "index_failed": True, "index_timeout": True,
                    WATCHDOG_CODE_KEY: e.code, "silent_s": e.silent_s}
        except IndexFailed as e:
            return {"rung": RUNG_INDEX, "error": str(e),
                    "index_failed": True}

    def refuse(tid, vid, attempts, rung):
        failed.append({
            "video_id": vid,
            "topic_id": tid,
            "error": _refusal_sentence(vid, attempts, rung),
            # CF-0232: the funnel counts this source as a loss under this code.
            "reason_code": FUNNEL_REASON_CODE,
            "refused_at": rung,
            "attempts": attempts,
        })

    def canon_count(tid):
        """Canonical sources this topic holds - what the two-source gate and
        the funnel will count, so an alias is not one of them."""
        return len(sources_by_topic.get(tid) or [])

    def depth_of(tid):
        """This topic's pool as it stands right now (CF-0304).

        Asked from inside the walk on purpose: every field it reads
        (`usable_cached`, `crop_bottom_cached`, `is_card`) is written by
        `index_footage.py` into the same `shots.json` it produces, so the
        answer exists the moment `admit()` registers a source - there is no
        describer pass owed and no later stage to wait for. `pool_depth`
        remembers a screening by (path, mtime, size), so asking once per
        candidate costs one read per source and not one per question.
        """
        return pool_depth.topic_depth(tid, sources_by_topic.get(tid) or [],
                                      cache=depth_cache)

    def wants_more(tid):
        """Is there a reason for this topic to take another candidate?

        Two reasons, in this order, and the second one is CF-0304:

          * it is under the CF-0129 source floor - the count, which has always
            been here;
          * it is at the source floor and under the depth floor - two sources
            whose shots the Editor's gate would throw away are two sources and
            no pool. Batch 2026-09-21T0358Z lost Harbourlights and Rennick to
            exactly this, with four untried candidates each.

        The depth question is not asked while something is pending: a
        candidate holding a place toward `wanted` may still become a source,
        and its shots are not in the pool to be counted yet.
        """
        st = state[tid]
        if canon_count(tid) + st["pending"] < wanted:
            return True
        if not depth_floor or st["pending"]:
            return False
        depth = depth_of(tid)
        if pool_depth.deep_enough(depth, depth_floor):
            return False
        log(pool_depth.depth_line(depth, depth_floor))
        return True

    fetch_takes_ceiling = _takes(fetch, "max_seconds")
    fetch_takes_rights = _takes(fetch, "rights")
    fetch_takes_record = _takes(fetch, "record")            # CF-0665

    def rights_for(tid, vid):
        """CF-0663: the `rights` record of `vid` as a source of `tid`.

        The candidate's licence block when it carries one; else what an
        earlier fetch kept on the cache entry (a pool source a judged batch
        took); else the unjudged record of what the candidate does say."""
        rec = ((state.get(tid) or {}).get("records") or {}).get(vid)
        if is_own_capture(vid):
            # CF-0567: decided by the kind; the page and host from the sidecar.
            return source_rights.own_capture_rights(
                vid, rec, own_capture_sidecar(vid, rec), origins)
        if isinstance((rec or {}).get(source_rights.LICENCE_KEY), dict):
            return source_rights.rights_of(vid, rec, origins)
        try:
            entry = cache_entry_of(vid, rec)
        except (OSError, ValueError, KeyError, TypeError):
            entry = None
        held = (entry or {}).get(source_rights.RIGHTS_KEY)
        if isinstance(held, dict):
            return dict(held, read_from="cache")
        return source_rights.rights_of(vid, rec, origins)

    def licence_refused(tid, vid):
        """CF-0663: the `failed[]` record when `vid`'s licence is refused -
        already appended and logged - else None. Asked before the attempt is
        counted and before anything is asked of YouTube."""
        rec = (state[tid].get("records") or {}).get(vid)
        reason = source_rights.refusal(vid, rec, origins)
        if reason is None:
            return None
        rec_out = {
            "video_id": vid,
            "topic_id": tid,
            "error": (f"{reason}. Refused before anything was asked of the source "
                      "(CF-0663); the topic's CF-0129 attempt was not spent on it - the "
                      "walk goes on to its next candidate."),
            "reason_code": LICENCE_CODE,
            "refused_at": "candidate",
            "attempts": [],
            "attempt_spent": False,
            source_rights.RIGHTS_KEY: source_rights.rights_of(vid, rec, origins),
        }
        failed.append(rec_out)
        log(LICENCE_LINE.format(vid=vid, topic=tid, reason=reason))
        return rec_out

    def candidate_of(tid, vid):
        """CF-0665: `{"candidate_id": "nasa:<id>"}` for an archive file (the
        Trend Hunter's own id beside the file id), {} for anything else.
        CF-0567: `{"candidate_id": "own_capture:<id>"}` for an own capture."""
        if is_own_capture(vid):
            return {"candidate_id": own_capture_source.candidate_name(vid)}
        if not archive_source.is_archive(vid):
            return {}
        rec = ((state.get(tid) or {}).get("records") or {}).get(vid) or {}
        cid = rec.get("candidate_id") or rec.get("video_id")
        return {"candidate_id": cid} if cid and cid != vid else {}

    def refuse_licence_changed(tid, vid, record, rung):
        """CF-0665: `vid`, an archive file, refused because its licence read
        again from the archive is not the one the candidate was judged on.
        One `failed[]` record with `reason_code: licence_changed`, both
        versions (`licence_was`, `licence_now`) and `attempt_spent: false`."""
        rec = (state[tid].get("records") or {}).get(vid)
        reason = record.get("reason") or "the archive's licence changed"
        failed.append({
            "video_id": vid,
            "topic_id": tid,
            "candidate_id": (rec or {}).get("candidate_id") or record.get("candidate_id"),
            "error": (f"{reason}. Read again from the archive before the download "
                      f"(CF-0665) and refused there - nothing came down and the "
                      "topic's CF-0129 attempt was not spent on it; the walk goes on "
                      "to its next candidate."),
            "reason_code": LICENCE_CHANGED_CODE,
            "refused_at": RUNG_DOWNLOAD,
            "attempts": [],
            "attempt_spent": False,
            "fetch_rung": rung,
            "licence_was": record.get("was"),
            "licence_now": record.get("now"),
            source_rights.RIGHTS_KEY: source_rights.rights_of(vid, rec, origins),
        })
        log(LICENCE_CHANGED_LINE.format(vid=vid, topic=tid, reason=reason))

    def nature_of(tid, vid):
        rec = (state[tid].get("records") or {}).get(vid)
        return (rec or {}).get("nature")

    def refuse_too_long(tid, vid, seconds, limit, rung):
        """CF-0333: the download request refused `vid` over the ceiling.

        The same `source_too_long` record the metadata check writes, with
        `refused_at: download` and `measured_from: download` - the length is
        yt-dlp's own, read in the request that would have fetched the media.
        Nothing came down, so no attempt is spent (the caller gives it back).
        """
        rec = (state[tid].get("records") or {}).get(vid)
        nature = (rec or {}).get("nature")
        title = (rec or {}).get("title") or ""
        secs = int(round(seconds)) if seconds else None
        failed.append({
            "video_id": vid,
            "topic_id": tid,
            "error": (f"{secs} s is over the {int(limit)} s ceiling for a source of "
                      f"nature '{nature}' (CF-0302), read by yt-dlp inside the "
                      f"download request at rung '{rung}' and refused there before "
                      "any media moved (CF-0333)"
                      + (f": \"{title}\"" if title else "")
                      + ". Nothing was fetched and the topic's CF-0129 attempt was "
                        "not spent on it - the walk goes on to its next candidate."),
            "reason_code": TOO_LONG_CODE,
            "refused_at": RUNG_DOWNLOAD,
            "attempts": [],
            "duration_seconds": seconds,
            "ceiling_seconds": limit,
            "nature": nature,
            "measured_from": RUNG_DOWNLOAD,
            "fetch_rung": rung,
            "attempt_spent": False,
        })
        log(TOO_LONG_DOWNLOAD_LINE.format(vid=vid, seconds=secs, limit=int(limit),
                                          nature=nature, rung=rung))

    def over_ceiling(tid, vid):
        """CF-0302: is this candidate too long to be worth downloading?

        Returns the `failed[]` record when it is - already appended, already
        logged - and None when it is not, *including* when its length could
        not be measured: a probe that did not answer decides nothing, and the
        candidate then walks the normal path with the fact recorded.

        Called before the attempt is counted. That is the whole mechanism:
        the CF-0129 cap counts videos this stage downloads, and this one it
        did not download.
        """
        rec = (state[tid].get("records") or {}).get(vid)
        nature = (rec or {}).get("nature")
        if is_own_capture(vid):
            # CF-0567: our own recording - no ceiling and nothing to measure.
            measured.append({"video_id": vid, "topic_id": tid, "nature": nature,
                             "duration_seconds": None,
                             "measured_from": OWN_CAPTURE_MEASURE,
                             "ceiling_seconds": None, "error": None})
            return None
        limit = ceiling.seconds(nature)
        try:
            m = measure(vid, record=rec)
        except Exception as e:
            # The ceiling is a safety net, never a new way to lose a batch:
            # whatever went wrong reading one number, the candidate keeps its
            # ordinary path and the failure is on paper.
            m = Measured(None, "metadata", f"{type(e).__name__}: {e}")
        measured.append({"video_id": vid, "topic_id": tid, "nature": nature,
                         "duration_seconds": m.seconds, "measured_from": m.source,
                         "ceiling_seconds": limit, "error": m.error})
        if m.seconds is None:
            why = m.error or "no answer"
            log(UNMEASURED_LINE.format(vid=vid, why=why))
            return None
        if limit is None or m.seconds <= limit:
            return None
        title = (rec or {}).get("title") or ""
        seconds = int(round(m.seconds))
        rec_out = {
            "video_id": vid,
            "topic_id": tid,
            "error": (f"{seconds} s is over the {int(limit)} s ceiling for a source "
                      f"of nature '{nature}' (CF-0302), measured from "
                      f"{m.source} before anything was downloaded"
                      + (f": \"{title}\"" if title else "")
                      + ". Nothing was fetched and the topic's CF-0129 attempt was "
                        "not spent on it - the walk goes on to its next candidate."),
            "reason_code": TOO_LONG_CODE,
            "refused_at": RUNG_METADATA,
            # No attempt was made: the list is empty on purpose, and the two
            # fields below are what a reader of this record needs instead.
            "attempts": [],
            "duration_seconds": m.seconds,
            "ceiling_seconds": limit,
            "nature": nature,
            "measured_from": m.source,
            "attempt_spent": False,
        }
        failed.append(rec_out)
        log(TOO_LONG_LINE.format(vid=vid, seconds=seconds, limit=int(limit),
                                 nature=nature))
        return rec_out

    def climb(tid, vid, rung):
        """One candidate's download: a single attempt.

        Returns (miss, history): miss None when the source is in, else the
        attempt record; history every attempt made here, in order.
        """
        miss = attempt(tid, vid, rung)
        return miss, ([miss] if miss else [])

    def walk(tid, rung):
        """Take this topic's candidates, in Trend Hunter's order, until it
        holds `wanted` canonical sources or runs out of attempts (CF-0129).

        A candidate that turns out to be a re-upload of a source the topic
        already has costs an attempt and leaves the count where it was, so the
        walk goes on to the next candidate - that is the whole point: on batch
        2026-09-03T2037Z three uploads of one teaser looked like three sources
        and were one.

        CF-0304: "until it holds `wanted` canonical sources" is now
        `wants_more()`, which also asks how deep those sources are. The cap,
        the queue, the dedup and the ceiling are untouched - the
        only thing that changed is when the walk is satisfied.
        """
        st = state[tid]
        note("walking", tid, canon_count(tid), st["attempts"])          # CF-0715
        while (wants_more(tid)
               and st["attempts"] < max_per_topic and st["queue"]):
            if past():
                cut_rest(tid)               # CF-0429: nothing new after it
                break
            vid = st["queue"].popleft()
            if vid in st["tried"]:
                continue
            # CF-0302: the length is read before the attempt is counted, so a
            # candidate refused for it costs the topic nothing. A `same_cut`
            # stand-in is not offered either - it is the same cut and so the
            # same length.
            if licence_refused(tid, vid) is not None:
                continue                    # CF-0663: never asked of YouTube
            if over_ceiling(tid, vid) is not None:
                continue
            st["tried"].append(vid)
            st["attempts"] += 1
            miss, history = climb(tid, vid, rung)
            note("walking", tid, canon_count(tid), st["attempts"], vid)  # CF-0715
            if miss is None:
                continue
            if miss.get("wall_ceiling"):
                # CF-0429: the deadline took it - nothing was decided about
                # the video, so the attempt goes back and the walk ends here.
                st["attempts"] -= 1
                cut_one(tid, vid, miss["cut_at"])
                cut_rest(tid)
                break
            if miss.get("too_long") or miss.get(LICENCE_CHANGED_CODE):
                # CF-0333: refused inside the download request - nothing came
                # down, so the attempt goes back like the CF-0302 refusal's.
                st["attempts"] -= 1
                continue
            if miss.get("index_timeout"):
                # CF-0316: the factory took this operation down itself, which
                # says nothing about the video - so the attempt goes back, the
                # same way the CF-0302 ceiling never spends one. The id stays
                # in `tried`, so this is not a retry of the same candidate but
                # one more candidate for the topic, and the run goes on.
                st["attempts"] -= 1
                continue
            if miss.get("index_failed"):
                # CF-0281: admit() has already written the refusal, and the
                # media is in the cache - nothing here is YouTube's doing and
                # nothing is worth retrying. The walk simply goes on to this
                # topic's next candidate, inside the same attempt cap: the
                # automatic version of the top-up the stage operator did with
                # his hands on 2026-09-18.
                continue
            refuse(tid, vid, history, miss["rung"])
            # A candidate that is not there at all can be stood in for by a
            # re-upload of the same cut, which Trend Hunter already found
            # (`footage_candidates[].same_cut`). It is the same footage, so it
            # is worth one attempt in that candidate's place and is never a
            # second independent source.
            subs = [s for s in st["same_cut"].get(vid) or () if s not in st["tried"]]
            if subs:
                st["queue"].extendleft(reversed(subs))

    def walk_all(tids, rung):
        """CF-0332: `walk()` for every topic in `tids`, `workers` at a time.

        Each topic is walked by one thread start to end, so everything a walk
        decides about its own topic is decided in the same order as before.
        What the walks share is appended to shared lists; each list's new tail
        is put back in topic order afterwards (a stable sort, so one topic's
        own records keep their order). os.environ's runlog pair is restored,
        since run() in two threads can leave the other thread's id behind."""
        if not parallel or len(tids) < 2:
            for tid in tids:
                walk(tid, rung)
            return
        lists = (fetched, aliases, failed, measured)
        starts = [len(x) for x in lists]
        saved = {k: os.environ.get(k) for k in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
        slots = itertools.count()

        def enter():
            slot = next(slots)
            _WORKER.active = True
            _WORKER.slot = slot
            _WORKER.vision_socket = (vision_sockets[slot % len(vision_sockets)]
                                     if vision_sockets else None)

        try:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(workers, len(tids)), initializer=enter,
                    thread_name_prefix="ingest-walk") as ex:
                futures = [ex.submit(walk, tid, rung) for tid in tids]
                for f in futures:
                    f.result()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            order = {tid: i for i, tid in enumerate(state)}

            def rank(rec):
                tid = rec[0] if isinstance(rec, list) else rec.get("topic_id")
                return order.get(tid, len(order))

            for lst, start in zip(lists, starts):
                lst[start:] = sorted(lst[start:], key=rank)

    # First pass, in topic order.
    walks = []
    note("start", [t["topic_id"] for t in topics])                       # CF-0715
    for topic in topics:
        tid = topic["topic_id"]
        # CF-0265: whether compliance gave this topic a slot decides whether
        # it is fetched at all, and it is decided here, before the first
        # download - unused reserve, or never judged. Not the verdict: since
        # CF-0318 a topic at `review` is walked like any other, because what
        # its verdict blocks is publication and not production.
        gate = compliance_skip(tid, screening)
        if gate is not None:
            skipped.append(gate)
            note("skip", tid, gate.get("reason_code"))                   # CF-0715
            continue

        canon_by_topic.setdefault(tid, [])
        sources_by_topic.setdefault(tid, [])
        state[tid] = walk_state(topic)
        # CF-0299: a second pass over this batch starts where the first one
        # stopped - the candidates it already tried are not tried again and
        # the attempts they cost are not handed back.
        seed_prior(state[tid], (prior or {}).get(tid), (barred or {}).get(tid))
        register_pooled(tid)
        if parallel:
            walks.append(tid)       # CF-0332: walked below, `workers` at a time
        else:
            walk(tid, RUNG_FIRST_PASS)
    if parallel:
        walk_all(walks, RUNG_FIRST_PASS)

    # CF-0129, the top-up pass. The first pass is over, so nothing is pending
    # any more. A topic left short of the floor now gets its next candidates,
    # inside the same attempt cap.
    #
    # CF-0304: every topic is offered this pass, not only the ones under the
    # source floor - `walk()` asks `wants_more()` and returns at once for a
    # topic that is both at the floor and deep enough, so a deep topic costs
    # one screening of indexes it already holds and no download.
    if parallel:
        for st in state.values():
            st["pending"] = 0
        walk_all(list(state), RUNG_TOP_UP)
    else:
        for tid, st in state.items():
            st["pending"] = 0
            walk(tid, RUNG_TOP_UP)

    # CF-0304: what every topic's pool ended up holding, and why the walk
    # stopped where it did. Measured here, after the top-up, so
    # this is the pool Content Researcher is actually handed - and written for
    # every topic, not only the thin ones, because "no pool was thin" and
    # "nobody measured" must not read the same.
    for tid, st in state.items():
        depth = depth_of(tid)
        at_floor = canon_count(tid) >= wanted
        if pool_depth.deep_enough(depth, depth_floor):
            why = None
        elif not st["queue"]:
            why = "no_more_candidates"
        elif st["attempts"] >= max_per_topic:
            why = "attempt_cap"
        else:
            why = None
        depth_records.append(pool_depth.depth_record(
            depth, depth_floor, exhausted=why, attempts=st["attempts"],
            at_source_floor=at_floor, indexed_at=indexed_at.get(tid)))
        if why and at_floor:
            log(POOL_THIN_LINE.format(tid=tid, usable=depth.usable,
                                      shots=depth.shots, floor=depth_floor,
                                      why=("its candidates are used up"
                                           if why == "no_more_candidates"
                                           else f"the {max_per_topic}-attempt "
                                                f"cap stopped it")))

    # CF-0281: which candidate the walk took in place of a source whose index
    # failed. The walk is over, so this is now knowable: whatever the topic
    # registered after the failure is what stood in for it.
    for rec in failed:
        if rec.get("reason_code") != INDEX_FUNNEL_CODE:
            continue
        before = rec.pop("sources_at_failure", [])
        rec["replaced_by"] = [v for v in (sources_by_topic.get(rec["topic_id"]) or [])
                              if v not in before]

    # CF-0129 / CF-0232, the refusal. A topic below the floor is refused here,
    # where the reason is still known, and not after a script, a TTS pass and
    # an anchor resolve have been spent on a video the gate would reject.
    for tid, st in state.items():
        if canon_count(tid) >= wanted:
            continue
        losses = split_losses(
            [f for f in failed if f.get("topic_id") == tid],
            (earlier or {}).get(tid) or (), (sieved or {}).get(tid) or ())
        record = topic_refusal(
            tid, st, sources_by_topic.get(tid) or [],
            [a["video_id"] for a in aliases if a["topic_id"] == tid],
            losses["lost"], wanted=wanted, max_attempts=max_per_topic,
            index_failed=losses["index_failed"], sieved=losses["sieved"],
            too_long=losses["too_long"])
        skipped.append(record)
        note("skip", tid, record.get("reason_code"))                     # CF-0715
        log(TOPIC_REFUSED_LINE.format(tid=tid, reason=record["reason"]))

    return fetched, aliases, skipped, failed, sources_by_topic


def write_aliases(batch, aliases):
    """<batch>/work/footage-aliases.json: {topic_id: [alias record, ...]}."""
    by_topic = {}
    for a in aliases:
        by_topic.setdefault(a["topic_id"], []).append(
            {k: a[k] for k in ("video_id", "alias_of", "distance", "fingerprint_kind",
                               "offset_seconds", "overlap_frames")}
            | {k: a[k] for k in SHOT_COPY_FIELDS if k in a})
    work = Path(batch) / "work"
    work.mkdir(parents=True, exist_ok=True)
    dest = work / ALIASES_FILE
    json.dump(by_topic, open(dest, "w"), indent=2)
    return dest


def two_source_report(skipped, wanted=SOURCES_WANTED,
                      max_attempts=MAX_ATTEMPTS_PER_TOPIC):
    """What the report says about the CF-0129 floor, whether or not it bit."""
    return {
        "wanted": wanted,
        "max_attempts_per_topic": max_attempts,
        "refused": [s["topic_id"] for s in skipped
                    if s.get("reason_code") == TOPIC_REFUSAL_CODE],
        "note": "CF-0129: a topic is fetched candidate by candidate, in Trend "
                "Hunter's order, until it holds `wanted` canonical sources after "
                "CF-0080 dedup, at most `max_attempts_per_topic` distinct videos "
                "per topic. A topic still short when its walk has ended "
                "and holding one source is settled by `mode` (CF-0419, "
                "`footage_indexer.no_second_source`, read from `mode_from`): "
                "`warn`/`measure` keep it in the batch with a `warnings[]` entry "
                "(`warned`), `enforce` puts it in `skipped_topics` with "
                "`no_second_source` (`refused`) and it does not reach Content "
                "Researcher. The user's decision of "
                "2026-09-28 is `warn`. CF-0689: on a channel whose "
                "footage-origin.json names the `own_graphic` origin, a topic "
                "whose `evidence.own_graphic_footing.meets_floor` is true is "
                "never refused by this floor, in any mode: it is kept on own "
                "graphics (`kept_on_own_graphics`, the report's "
                "`own_graphic_footing` block).",
    }


# ---------------------------------------------------------------------------
# CF-0362: the floor warns in `measure` (CF-0320 / CF-0330, the user,
# 2026-09-23)
#
# The user's answer of 2026-09-23: `two_source_gate` / `no_second_source` and
# the thin pool (`pool_too_thin`) are a warning, not a refusal. The Video
# Editor and the Content Researcher already follow the channel's switch
# (`channels/<channel>.json` -> `video_editor.two_source_gate`, read the way
# `check_two_sources.mode_from_config()` reads it); this stage did not, and on
# batch `example-film/2026-09-23T1722Z` it dropped four topics that each held a
# kept, sieved source (Paper Dragon `MLwTyQOhBkw`, 56 shots; Delver
# `ZLXL1L0TfsI`; Ray Gunn `VL-xjzQFWsY`; `1Ee_FK7vTD8`).
#
# So, after the walk has had its round (the walk and the sieve's top-up are
# unchanged - a topic still takes its next candidate while it is short):
#   * `measure` - a `no_second_source` topic that holds at least one source is
#     taken out of `skipped_topics[]` and stays in the batch, with a
#     `warnings[]` entry carrying the counts;
#   * `enforce` - the refusal stands, exactly as before;
#   * a topic with no source at all (`no_source`, `fetch_failed`,
#     `index_failed`, `source_foreign`, `source_burned_text`, ...) is refused
#     in either mode - there is nothing to cut.
# A pool under the depth floor was never refused here (CF-0304); it now also
# gets a `pool_too_thin` warning entry, in either mode.
# ---------------------------------------------------------------------------
TWO_SOURCE_GATE_KEY_PATH = ("video_editor", "two_source_gate")
GATE_MEASURE, GATE_ENFORCE = "measure", "enforce"
GATE_MODES = (GATE_MEASURE, GATE_ENFORCE)
DEFAULT_GATE_MODE = GATE_MEASURE          # the Editor's own default
WARNINGS_FIELD = "warnings"
WARN_SEVERITY = "warn"
WARN_DECISION = ("CF-0320/CF-0330: the user, 2026-09-23 - a warning, "
                 "not a refusal; CF-0419: footage_indexer.no_second_source "
                 "is `warn` by the user's decision of 2026-09-28")

# ---------------------------------------------------------------------------
# CF-0419: the floor has a switch of its own (the user, 2026-09-28)
#
# `runlog triage` prices every rule of `shared/runlog/gate_price.RULES` and
# reads how each stands in production at the rule's own path in the channel
# config. For `footage_indexer.no_second_source` that path did not exist: this
# stage followed the Editor's `video_editor.two_source_gate`, so the triage
# found no switch, called the rule `hard-wired` and filed an
# `unpriced_refusal` on every batch (CF-0408) - while the stage, under
# `measure`, had refused nothing. The user's answer of 2026-09-28: the rule is
# a warning. So the switch is now where the triage looks:
#
#     channels/<channel>.json -> footage_indexer.no_second_source
#
# a string or `{"mode": ..., "note": ...}`. `warn` / `measure` / `off` keep a
# one-source topic with a `warnings[]` entry; `enforce` / `fail` / `refuse`
# refuse it. Precedence, most explicit first: the run's `--no-second-source`
# flag, this key, the Editor's `video_editor.two_source_gate` (the CF-0362
# reading, kept for a channel that never set the key: under an enforcing
# Editor a one-source topic is a video refused after the TTS, which is the
# CF-0129 reason this floor exists), and with none of them `warn`. An unknown
# value is silence, not a refusal - a typo falls through to the next source.
# `two_source_floor` in `01b` carries the mode and where it came from, so a
# reader of the batch never has to guess which of the three it was.
# ---------------------------------------------------------------------------
FLOOR_RULE = "footage_indexer.no_second_source"
FLOOR_KEY_PATH = tuple(FLOOR_RULE.split("."))
FLOOR_WARN = "warn"
FLOOR_KEEP_MODES = (FLOOR_WARN, GATE_MEASURE, "off")
FLOOR_REFUSE_MODES = (GATE_ENFORCE, "fail", "refuse")
FLOOR_MODES = FLOOR_KEEP_MODES + FLOOR_REFUSE_MODES
DEFAULT_FLOOR_MODE = FLOOR_WARN            # the user, 2026-09-28
FLOOR_FROM_FLAG = "--no-second-source"
FLOOR_FROM_OWN_KEY = f"channels/<channel>.json {FLOOR_RULE}"
FLOOR_FROM_EDITOR = ("channels/<channel>.json "
                     + ".".join(TWO_SOURCE_GATE_KEY_PATH))
FLOOR_FROM_DEFAULT = "default (the user, 2026-09-28)"
FLOOR_WARNINGS_LINE = ("  {n} topic(s) short of a second source kept with a "
                       "warning ({rule} `{mode}` from {whence}): {topics}")


def floor_keeps(mode):
    """Whether `mode` keeps a one-source topic (with a warning)."""
    return str(mode or "").strip().lower() not in FLOOR_REFUSE_MODES


def _mode_at(cfg, path, allowed):
    node = cfg
    for part in path:
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, dict):
        node = node.get("mode")
    if isinstance(node, str) and node.strip().lower() in allowed:
        return node.strip().lower()
    return None


def floor_mode_from_config(cfg):
    """`(mode, whence)` of the CF-0129 floor for a loaded channel config:
    `footage_indexer.no_second_source`, else the Editor's
    `video_editor.two_source_gate`, else `warn`."""
    own = _mode_at(cfg, FLOOR_KEY_PATH, FLOOR_MODES)
    if own:
        return own, FLOOR_FROM_OWN_KEY
    editor = _mode_at(cfg, TWO_SOURCE_GATE_KEY_PATH, GATE_MODES)
    if editor:
        return editor, FLOOR_FROM_EDITOR
    return DEFAULT_FLOOR_MODE, FLOOR_FROM_DEFAULT


def floor_mode(channel, config_path=None, root=None, flag=None):
    """The floor's `(mode, whence)` for this run: the flag, else the channel
    config (read as `two_source_mode()` reads it), else `warn`."""
    if flag:
        return str(flag).strip().lower(), FLOOR_FROM_FLAG
    root = Path(root) if root else (Path(FACTORY_ROOT) if FACTORY_ROOT else None)
    try:
        channel = resolve_channel(channel, root=root)
        cfg_path = (Path(config_path) if config_path
                    else channel_config_path(channel, root=root))
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing config is the default mode
        return DEFAULT_FLOOR_MODE, FLOOR_FROM_DEFAULT
    return floor_mode_from_config(cfg)
WARN_GATE_TWO_SOURCES = "two_source_gate"
WARN_GATE_POOL_DEPTH = "pool_depth"
POOL_THIN_WARNING_CODE = "pool_too_thin"
FLOOR_WARNED_LINE = ("FLOOR {tid} kept with a warning ({mode}): {detail}")


def gate_mode_from_config(cfg, default=DEFAULT_GATE_MODE):
    """`video_editor.two_source_gate` of a loaded channel config: the string,
    or `mode` of a block. Anything else is the default - a typo must neither
    turn every one-source topic into a refusal nor the other way round."""
    node = cfg
    for part in TWO_SOURCE_GATE_KEY_PATH:
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, dict):
        node = node.get("mode")
    if isinstance(node, str) and node.strip().lower() in GATE_MODES:
        return node.strip().lower()
    return default


def two_source_mode(channel, config_path=None, root=None):
    """The channel's `two_source_gate` mode, read the way the ceiling is
    read. No readable config is the Editor's default."""
    root = Path(root) if root else (Path(FACTORY_ROOT) if FACTORY_ROOT else None)
    try:
        channel = resolve_channel(channel, root=root)
        cfg_path = (Path(config_path) if config_path
                    else channel_config_path(channel, root=root))
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing config is the default mode
        return DEFAULT_GATE_MODE
    return gate_mode_from_config(cfg)


def _depth_numbers(report, tid):
    for r in ((report.get("pool_depth") or {}).get("topics") or []):
        if r.get("topic_id") == tid:
            return r
    return None


def apply_floor_mode(report, mode, wanted=SOURCES_WANTED, log=print,
                     whence=None):
    """Settle `report` against the floor's mode, in place (CF-0362; CF-0419:
    any of `FLOOR_KEEP_MODES` keeps a one-source topic, `FLOOR_REFUSE_MODES`
    refuse it). `whence` is where the mode was read (`floor_mode()`), written
    into `two_source_floor.mode_from`.

    Idempotent: this stage's own floor/depth warnings are rebuilt from the
    report every call, so a second pass (the sieve after the first walk) never
    doubles them. Returns the ids of the topics kept with a warning."""
    kept = []
    keeps = floor_keeps(mode)
    held = report.get("sources_by_topic") or {}
    # The depth warnings are rebuilt whole; a floor warning an earlier pass
    # wrote survives only while its topic still holds a source and is not
    # refused (the refusal it replaced is no longer in `skipped_topics[]`, so
    # it cannot be re-derived from there).
    skipped_before = {s.get("topic_id") for s in report.get("skipped_topics") or []}
    warnings = []
    for w in report.get(WARNINGS_FIELD) or []:
        if not isinstance(w, dict):
            continue
        if w.get("stage") == STAGE_NAME and w.get("gate") == WARN_GATE_POOL_DEPTH:
            continue
        if (w.get("stage") == STAGE_NAME and w.get("gate") == WARN_GATE_TWO_SOURCES
                and (not keeps or not held.get(w.get("topic_id"))
                     or w.get("topic_id") in skipped_before)):
            continue
        warnings.append(w)
    graphic = report.get(OWN_GRAPHIC_KEY)
    graphic_kept = ({k.get("topic_id"): k for k in graphic.get("kept") or []}
                    if isinstance(graphic, dict) else {})
    skipped = []
    for s in report.get("skipped_topics") or []:
        tid = s.get("topic_id")
        sources = list(held.get(tid) or [])
        if (s.get("reason_code") in TOPIC_REFUSAL_CODES
                and own_graphic_keeps(report, tid)):
            # CF-0689: the topic's footing is the graphics, not the pool -
            # in any floor mode, whatever its whole loss was.
            footing = graphic["eligible"].get(tid) or {}
            detail = (f"{len(sources)} pool source(s)"
                      + (f" ({', '.join(sources)})" if sources else "")
                      + f", {footing.get('quotable_facts')} quotable fact(s) "
                      f"of {footing.get('floor')} wanted in its support text; "
                      f"the channel's `{graphic.get('origin')}` origin is its "
                      f"base footage, so the topic goes on instead of "
                      f"`{s.get('reason_code')}`")
            graphic_kept[tid] = {
                "topic_id": tid, "note": OWN_GRAPHIC_KEPT_NOTE,
                "origin": graphic.get("origin"), "sources": sources,
                "quotable_facts": footing.get("quotable_facts"),
                "floor": footing.get("floor"), "detail": detail,
                "refusal_it_replaces": {"reason_code": s.get("reason_code"),
                                        "reason": s.get("reason")}}
            log(OWN_GRAPHIC_KEPT_LINE.format(tid=tid, detail=detail))
            continue
        if (keeps and s.get("reason_code") == TOPIC_REFUSAL_CODE
                and sources):
            d = _depth_numbers(report, tid) or {}
            numbers = {"sources": len(sources), "wanted": wanted,
                       "shots": d.get("shots"),
                       "usable_shots": d.get("usable_shots"),
                       "usable_seconds": d.get("usable_seconds")}
            detail = (f"{len(sources)} canonical source(s) of {wanted} wanted "
                      f"({', '.join(sources)}), {d.get('usable_shots')} usable "
                      f"shot(s) of {d.get('shots')}; {FLOOR_RULE} is "
                      f"`{mode}`, so the topic goes on")
            warnings.append({
                "topic_id": tid, "warning_code": TOPIC_REFUSAL_CODE,
                "gate": WARN_GATE_TWO_SOURCES, "rule": FLOOR_RULE,
                "stage": STAGE_NAME,
                "severity": WARN_SEVERITY, "mode": mode,
                "mode_from": whence,
                "decision": WARN_DECISION, "detail": detail,
                "numbers": numbers, "refusal_it_replaces": s.get("reason")})
            kept.append(tid)
            log(FLOOR_WARNED_LINE.format(tid=tid, mode=mode, detail=detail))
            continue
        skipped.append(s)
    report["skipped_topics"] = skipped
    dead = {s.get("topic_id") for s in skipped}
    if isinstance(graphic, dict):
        graphic["kept"] = [k for t, k in graphic_kept.items() if t not in dead]
    on_graphics = {t for t in graphic_kept if t not in dead}
    # A floor warning an earlier pass wrote for a topic now kept on graphics
    # is not what the topic stands on any more (CF-0689).
    warnings = [w for w in warnings
                if not (w.get("stage") == STAGE_NAME
                        and w.get("gate") == WARN_GATE_TWO_SOURCES
                        and w.get("topic_id") in on_graphics)]
    for tid, sources in held.items():
        if not sources or tid in dead or tid in on_graphics:
            # CF-0689: a topic on graphics is not measured by its pool's depth.
            continue
        d = _depth_numbers(report, tid)
        if not d or d.get("deep_enough") or not d.get("measured"):
            continue
        warnings.append({
            "topic_id": tid, "warning_code": POOL_THIN_WARNING_CODE,
            "gate": WARN_GATE_POOL_DEPTH, "stage": STAGE_NAME,
            "severity": WARN_SEVERITY, "mode": mode,
            "decision": WARN_DECISION,
            "detail": (f"{d.get('usable_shots')} usable shot(s) of "
                       f"{d.get('shots')} in {len(sources)} source(s), under "
                       f"the {d.get('floor')}-shot depth floor (CF-0304)"),
            "numbers": {"sources": len(sources), "shots": d.get("shots"),
                        "usable_shots": d.get("usable_shots"),
                        "usable_seconds": d.get("usable_seconds"),
                        "floor": d.get("floor")}})
    report[WARNINGS_FIELD] = warnings
    floor = report.get("two_source_floor")
    if isinstance(floor, dict):
        floor["refused"] = [s["topic_id"] for s in skipped
                            if s.get("reason_code") == TOPIC_REFUSAL_CODE]
        floor["mode"] = mode
        floor["mode_from"] = whence
        floor["rule"] = FLOOR_RULE
        floor["warned"] = [w["topic_id"] for w in warnings
                           if w.get("stage") == STAGE_NAME
                           and w.get("gate") == WARN_GATE_TWO_SOURCES]
        if isinstance(graphic, dict):
            floor["kept_on_own_graphics"] = sorted(on_graphics)    # CF-0689
    return kept


def compliance_gate_report(skipped):
    """What the report says about the topics compliance took off this stage
    (CF-0265), whether or not there were any.

    The funnel reads `skipped_topics[]`; this block is for a person opening
    `01b-footage-index.json` and asking why a topic of `01-trend-hunter.json`
    has no footage - both codes are listed by name even when empty, so
    "nothing was reserved" and "the stage never looked" read differently.

    CF-0318: there were three keys until 2026-09-23, the third being `review`.
    A verdict is not a reason for missing footage any more, so the key is gone
    rather than renamed - and nothing takes its place, because this block
    answers why a topic has *no* footage and a held topic has footage. Where
    the hold is recorded is said in the note, once, with no second copy of it
    kept here to drift from the register.
    """
    def ids(code):
        return [s["topic_id"] for s in skipped if s.get("reason_code") == code]

    return {
        "reserve_unused": ids(RESERVE_SKIP_CODE),
        "not_screened": ids(NOT_SCREENED_CODE),
        "note": "CF-0265: compliance judges the whole shortlist and "
                "cut_shortlist.py cuts it to the batch target. This stage "
                "fetches everything `02-compliance-checker.json` carried into "
                "results[], whatever verdict each topic carries - since "
                "CF-0318 the verdict decides nothing here, only membership "
                "does. A topic in reserve[] is skipped with `reserve_unused` "
                "- eligible, no slot, not a refusal and not a fault of the "
                "topic. A topic in neither list is skipped with "
                "`not_screened`: unjudged material is not downloaded. With no "
                "02- file at all nothing has been judged yet and every topic "
                "is fetched, as before. A `review` verdict was a third key "
                "here until 2026-09-23 and is not a loss of any kind now: the "
                "video gets made, and what may not happen without a human's "
                "signature is its publication. That is recorded by "
                "agents/compliance-checker as a `publication_hold` on the "
                "batch artifact and as a row in publish/publication-holds.json "
                "- the register the Publisher reads, and the only place a "
                "signature is ever written.",
    }


def timeout_summary(index_failures_rows):
    """The operator's line for the sources the CF-0316 watchdog took down, or
    None when it took none - which source, which code, how long it hung. Its
    own function so it can be read back in a test without a whole report."""
    killed = [b for b in index_failures_rows or [] if b.get(WATCHDOG_CODE_KEY)]
    if not killed:
        return None
    return INDEX_TIMEOUT_SUMMARY.format(n=len(killed)) + ", ".join(
        f"{b.get('video_id')} ({b.get('topic_id')}, {b[WATCHDOG_CODE_KEY]}"
        + (f", quiet {int(round(float(b['silent_s'])))}s"
           if b.get("silent_s") is not None else "") + ")"
        for b in killed)


def index_failures(failed):
    """The `index_failures[]` block of the report (CF-0281).

    A projection of the `failed[]` records whose fault was ours rather than
    YouTube's, in the four keys every record of a loss in this factory carries
    (`topic_id`, `reason_code`, `stage`, `reason`) plus what only this fault
    has: the media still in the cache, and the candidate the CF-0129 walk took
    in its place. The shape is the one the stage operator wrote by hand into
    `example-film/2026-09-18T1058Z` on the day the defect cost a source.

    Always present, empty list included: "no index failed" and "nobody looked"
    must not read the same, the reason `compliance_gate` lists its codes even
    when they are empty.
    """
    return [{
        "topic_id": f.get("topic_id"),
        "video_id": f.get("video_id"),
        "reason_code": f.get("reason_code"),
        "stage": STAGE_NAME,
        "reason": f.get("error"),
        "path": f.get("path"),
        "replaced_by": f.get("replaced_by") or [],
        # CF-0316: present only for a source the watchdog took down - the
        # outcome code, how long it hung, and that the attempt was not spent.
        # Deliberately outside `reason_code`: a kill is an авария (CF-0319),
        # never a funnel word.
        **({WATCHDOG_CODE_KEY: f.get(WATCHDOG_CODE_KEY),
            "silent_s": f.get("silent_s"),
            "ceiling_s": f.get("ceiling_s"),
            "attempt_spent": False} if f.get(WATCHDOG_CODE_KEY) else {}),
    } for f in failed if f.get("reason_code") == INDEX_FUNNEL_CODE]


def ceiling_report(ceiling, failed, measurements=()):
    """The `duration_ceiling` block of the report (CF-0302).

    Three things a reader needs and cannot get from `failed[]` alone: which
    numbers were in force and whether they came from the channel config or
    from this stage's measured defaults; the candidates they refused; and the
    candidates whose length nobody could measure - the case where the ceiling
    was simply not applied, which must be visible rather than silent, because
    a batch where every probe got no answer is a batch with no ceiling.

    Always present, empty lists included: "nothing was too long" and "nothing
    was looked at" must not read the same.
    """
    unmeasured = [m for m in (measurements or ()) if m.get("duration_seconds") is None]
    return {
        "limits": dict(ceiling.limits) if ceiling else dict(DEFAULT_MAX_SOURCE_SECONDS),
        "configured": bool(ceiling.configured) if ceiling else False,
        "key": ceiling.key if ceiling else CEILING_KEY,
        "config": str(ceiling.config_path) if ceiling and ceiling.config_path else None,
        "refused": [{
            "topic_id": f.get("topic_id"),
            "video_id": f.get("video_id"),
            "reason_code": f.get("reason_code"),
            "stage": STAGE_NAME,
            "reason": f.get("error"),
            "nature": f.get("nature"),
            "duration_seconds": f.get("duration_seconds"),
            "ceiling_seconds": f.get("ceiling_seconds"),
            "measured_from": f.get("measured_from"),
        } for f in failed if f.get("reason_code") == TOO_LONG_CODE],
        "measured": list(measurements or ()),
        "unmeasured": unmeasured,
        "note": "CF-0302: a candidate longer than its nature's ceiling is refused "
                "before the download (`failed[]`, reason_code `source_too_long`, "
                "refused_at `metadata`) and does NOT spend one of the topic's "
                "CF-0129 attempts - the cap counts videos this stage downloaded. "
                "The length is read from `evidence.footage_candidates[]."
                + CANDIDATE_DURATION_KEY + "`, then from this factory's cache, then "
                "from one yt-dlp metadata request. A length nobody could measure is "
                "never a refusal: those candidates are in `unmeasured` and were "
                "fetched as usual - with the ceiling handed to the download itself "
                "(CF-0333), so yt-dlp refuses one that turns out too long before any "
                "media moves (`refused_at: download`, no attempt spent).",
    }


# CF-0341: the verdicts a freed slot goes to first - the publishable pair, the
# one `cut_shortlist.PUBLISH_VERDICTS` (agents/compliance-checker) fills the cut
# with first since CF-0335. Spelled again rather than imported: the two agents
# are separate repositories.
RESERVE_FIRST_VERDICTS = ("clear", "caution")


def reserve_queue(screening, topics=(), used=()):
    """The reserve topics still available, in the shortlist's own order.

    `cut_shortlist.py` walks `01-trend-hunter.json` `topics[]` and appends what
    it reserves, so `reserve[]` is already in that order - but the order is the
    thing this queue is about, so it is re-established against `topics[]`
    rather than assumed. A reserve id the shortlist does not name keeps its
    place at the end (a stable sort), because an id nobody can rank is still an
    id compliance cleared.

    CF-0341: the publishable topics (`clear`/`caution`, `RESERVE_FIRST_VERDICTS`)
    come first and the held ones (`review`) after them, each class keeping the
    rank order above - the same rule `cut_shortlist.cut_document` hands the
    batch's slots out by since CF-0335 (user's answer of 2026-09-23 to
    CF-0318, "0318 - B"). Without it a `review` ranked 6 took a freed slot
    ahead of a `clear` ranked 7, which is the very thing the cut stopped doing.
    A row with no verdict counts as publishable, as `Screening.promoting` reads
    it.
    """
    used = set(used or ())
    rows = [r for r in as_screening(screening).rows
            if r.get("topic_id") not in used]
    rank = {t.get("topic_id"): i for i, t in enumerate(topics or ())
            if isinstance(t, dict)}
    if rank:
        rows.sort(key=lambda r: rank.get(r["topic_id"], len(rank)))
    rows.sort(key=lambda r: (r.get("verdict") or "clear")
              not in RESERVE_FIRST_VERDICTS)
    return [r["topic_id"] for r in rows]


def slot_losses(report, codes=SLOT_FREEING_CODES, stage=STAGE_NAME):
    """The records in `report` of topics whose slot fell free (CF-0306).

    This stage's own refusals only: `PRE_FETCH_CODES` are compliance's word
    about a topic and never free anything - a reserve topic is not a loss, it
    is the thing that fills one, and a topic nobody judged never held a slot
    to free.

    CF-0318: `COMPLIANCE_SKIP_CODE` is in that tuple for old reports alone. A
    topic at `review` holds its slot now and is walked like any other, so
    there is nothing to refill; and in a report written before 2026-09-23 the
    record is history, which must not be re-read as a slot falling free a
    month later and spending the reserve on it.
    """
    return [s for s in (report.get("skipped_topics") or [])
            if s.get("reason_code") in codes
            and (stage is None or s.get("stage") == stage)]


SUBSTITUTION_NOTE = (
    "CF-0306 (user's decision of 2026-09-21): a topic this pipeline loses "
    "*after* compliance has judged the shortlist leaves a paid-for slot empty, "
    "and the topics compliance cleared but the batch target left over are "
    "sitting in `02-compliance-checker.json` -> reserve[]. The next unused one, "
    "in the shortlist's own order, takes the slot and is walked like any other "
    "topic of the batch: the same candidates from 01-trend-hunter.json, the "
    "same CF-0129 two-source gate, the same CF-0302 ceiling, the same CF-0304 "
    "depth floor. `substitutions[]` says who replaced whom and what the "
    "replaced topic died of; `unmatched[]` is a slot that fell free with "
    "nothing left to fill it (`reserve_exhausted`); `remaining[]` is the "
    "reserve still untouched, which stays reserve. "
    "`02-compliance-checker.json` is never rewritten - it is another stage's "
    "record of what it judged, and it judged these topics already.")


def substitution_block(report=None):
    """The report's `reserve_substitution` block, fresh or as it stands.

    Always present once this ran, empty lists included: "the reserve was not
    needed" and "nobody ever looked at the reserve" must not read the same -
    the same rule `compliance_gate` and `pool_depth` follow.
    """
    block = (report or {}).get(SUBSTITUTION_KEY)
    if not isinstance(block, dict):
        block = {"task": "CF-0306"}
    for key in ("substitutions", "unmatched", "reserve", "remaining"):
        if not isinstance(block.get(key), list):
            block[key] = []
    block["note"] = SUBSTITUTION_NOTE
    return block


def substituted(report):
    """The ids of every topic this report has already taken out of the
    reserve and into the batch, in the order they took their slots."""
    out = []
    for s in ((report or {}).get(SUBSTITUTION_KEY) or {}).get("substitutions") or ():
        tid = isinstance(s, dict) and s.get("topic_id")
        if tid and tid not in out:
            out.append(tid)
    return out


def promoted(report, verdict):
    """`verdict` with every topic `report` already substituted in promoted out
    of the reserve (CF-0307).

    The bug this closes cost batch `example-film/2026-09-21T1541Z` a slot. A
    substitution is remembered in `01b-footage-index.json` and nowhere else -
    `02-compliance-checker.json` is never rewritten, and rightly so - so any
    pass that opens the compliance artifact afresh sees the substitute sitting
    in `reserve[]` exactly as it did before it was promoted. `source_sieve.py`
    is such a pass: when the sieve took both sources of The Long Voyage
    (`lf-2026-09-21-008`, substituted a run earlier), its top-up called
    `ingest()` with that untouched screening, `compliance_skip()` answered
    `reserve_unused` before a single download, and the topic was left with no
    sources, no fetch and a record saying it had never been touched. The log
    said `takes its next candidate` and nothing was ever taken.

    So the promotion is re-read from the report wherever a walk is about to
    happen, not carried in memory from the call that made it. `Screening` is
    unchanged on disk; only this process's copy knows.
    """
    screening = as_screening(verdict)
    ids = [t for t in substituted(report) if t in screening.reserve]
    return screening.promoting(*ids) if ids else screening


def mark_substitutes(report, block=None):
    """Put every record of a substituted topic in the state the batch is
    really in (CF-0307).

    Two things, and both are about the same sentence being wrong about the
    same topic. A substitute is no longer reserve, so a `reserve_unused`
    record for one is stale whoever wrote it - the CF-0265 gate wrote The
    Odyssey's on batch `1541Z`, after the topic had been carried, walked and
    lost, and the funnel would have read a participant as an untouched spare.
    And a substitute this stage then refuses keeps its own refusal - that is
    what it died of - plus the two facts that say the refusal is a
    substitute's: `replaced`, the topic whose slot it took, and `at`, the
    moment it took it. The block's own entry stops claiming the sources the
    topic no longer holds.

    Called at the top of `substitute_reserve()`, which is the pass that runs
    after every walk of this stage, so a record written anywhere - the first
    pass, the sieve's top-up, the reserve mode - is put right in one place.
    """
    block = substitution_block(report) if block is None else block
    entries = {s["topic_id"]: s for s in block["substitutions"]
               if isinstance(s, dict) and s.get("topic_id")}
    if not entries:
        return block
    report["skipped_topics"] = [
        s for s in (report.get("skipped_topics") or [])
        if not (s.get("topic_id") in entries
                and s.get("reason_code") == RESERVE_SKIP_CODE)]
    for s in report["skipped_topics"]:
        entry = entries.get(s.get("topic_id"))
        if entry is None or s.get("reason_code") not in SLOT_FREEING_CODES:
            continue
        s["replaced"] = entry.get("replaced")
        s["at"] = entry.get("at")
        entry["outcome"] = "refused"
        entry["sources"] = [
            v for v in (report.get("sources_by_topic") or {}).get(s["topic_id"]) or ()]
    return block


def substitute_reserve(report, topics, screening, losses=None, at="index_pass",
                       wanted=SOURCES_WANTED, max_attempts=MAX_ATTEMPTS_PER_TOPIC,
                       depth_floor=pool_depth.POOL_DEPTH_FLOOR, cache=None,
                       log=print, walk=True, ceiling=None, floor=None,
                       exhausted=True, **ingest_kwargs):
    """Fill every free slot of `report` from the compliance reserve (CF-0306).

    `floor` is the CF-0419 floor mode (`floor_mode()`); None is the
    pre-CF-0419 reading, where a one-source substitute frees its slot again.

    `report` is the `01b-footage-index.json` document, amended in place and
    returned. `losses` is the list of records whose slots fell free, in the
    order they are to be refilled; with `None` it is this stage's own refusals
    in the report (`slot_losses`), which is what the first pass and the sieve
    hand in. The `--reserve-for` mode hands in the Content Researcher's
    refusals instead, which is the only difference between the two modes:
    where the loss was noticed. What happens to the slot is one piece of code.

    `at` goes onto every record written here and says which of the two it was
    (`index_pass` / `researcher_refusal`).

    A substitute is walked by `ingest()` itself, over the promoted screening
    (`Screening.promoting`), so nothing about the walk is re-implemented. A
    substitute the walk refuses frees the slot again and the next reserve topic
    is offered for it - the queue ends when the losses are all answered or the
    reserve is used up, and every topic is answered exactly once, which is what
    makes a second call idempotent.

    `walk=False` records the arithmetic and downloads nothing.

    `exhausted=False` (CF-0799, the after-judge mode) writes no
    `reserve_exhausted` record for a slot the reserve cannot fill: the frame
    judge's refusal is already the loss the funnel counts, and a second record
    of the same empty slot would be two losses where there is one. The line is
    still logged.
    """
    screening = as_screening(screening)
    block = substitution_block(report)
    by_id = {t["topic_id"]: t for t in (topics or ())
             if isinstance(t, dict) and t.get("topic_id")}
    if screening.rows:
        block["reserve"] = [r["topic_id"] for r in screening.rows]
    mark_substitutes(report, block)

    # Idempotency, and the reason a second `--reserve-for` call costs nothing:
    # a loss already answered - with a substitute or with `reserve_exhausted` -
    # is never answered twice, and a reserve topic already spent is never
    # offered twice.
    handled = {s.get("replaced") for s in block["substitutions"]}
    handled |= {u.get("replaced") for u in block["unmatched"]}
    used = {s.get("topic_id") for s in block["substitutions"] if s.get("topic_id")}
    queue = [dict(s) for s in
             (slot_losses(report) if losses is None else losses)
             if s.get("topic_id") and s.get("topic_id") not in handled]
    available = reserve_queue(screening, topics, used)
    fresh_depths, fresh_measured = [], []

    while queue:
        loss = queue.pop(0)
        tid = loss["topic_id"]
        if tid in handled:
            continue
        handled.add(tid)
        code = loss.get("reason_code")
        stage = loss.get("stage") or STAGE_NAME
        if not available and not exhausted:
            log(EXHAUSTED_LINE.format(tid=tid, code=code,
                                      code_out="nothing recorded"))
            continue
        if not available:
            block["unmatched"].append({
                "replaced": tid,
                "replaced_reason_code": code,
                "replaced_stage": stage,
                "topic_id": None,
                "reason_code": RESERVE_EXHAUSTED_CODE,
                "stage": STAGE_NAME,
                "at": at,
                "reason": (f"topic {tid} was lost at '{stage}' with "
                           f"'{code}' and its slot cannot be refilled: every "
                           f"topic compliance put in reserve[] has already "
                           f"been spent on an earlier loss of this batch "
                           f"(CF-0306). The slot stays empty - the batch ends "
                           f"one video short of its target, and the fix is a "
                           f"longer shortlist (`scope.shortlist_size`), not "
                           f"anything this stage can do."),
            })
            log(EXHAUSTED_LINE.format(tid=tid, code=code,
                                      code_out=RESERVE_EXHAUSTED_CODE))
            continue
        sub = available.pop(0)
        used.add(sub)

        # The substitute stops being reserve the moment it takes a slot: its
        # `reserve_unused` record goes, so `compliance_gate.reserve_unused`
        # and the funnel's "held in reserve" count only the topics that really
        # stayed behind.
        report["skipped_topics"] = [
            s for s in (report.get("skipped_topics") or [])
            if not (s.get("topic_id") == sub
                    and s.get("reason_code") == RESERVE_SKIP_CODE)]
        # The replaced topic keeps its own refusal - it really was refused -
        # and gains the one fact the funnel needs to print the replacement.
        for s in report["skipped_topics"]:
            if s.get("topic_id") == tid:
                s["replaced_by_topic"] = sub

        entry = {
            "replaced": tid,
            "replaced_reason_code": code,
            "replaced_stage": stage,
            # What the replaced topic actually died of, id by id: the
            # source-level codes of `failed[]` (`fetch_failed`, `index_failed`,
            # `source_foreign`, `source_burned_text`, `source_too_long`).
            "source_codes": sorted({f.get("reason_code")
                                    for f in (report.get("failed") or ())
                                    if f.get("topic_id") == tid
                                    and f.get("reason_code")}),
            "topic_id": sub,
            "reason_code": RESERVE_SUBSTITUTED_CODE,
            "stage": STAGE_NAME,
            "at": at,
            "sources": [],
            "outcome": None,
            "reason": (f"{sub} takes the slot of {tid}, which was lost at "
                       f"'{stage}' with '{code}'. {sub} passed compliance in "
                       f"this batch's own shortlist and was unused reserve "
                       f"until now (CF-0306)."),
        }
        block["substitutions"].append(entry)
        log(SUBSTITUTION_LINE.format(sub=sub, tid=tid, code=code,
                                     left=len(available)))

        topic = by_id.get(sub)
        if topic is None:
            # Compliance reserved a topic `01-trend-hunter.json` does not name.
            # There is no candidate list to walk, so the slot is free again.
            entry["outcome"] = "no_candidates"
            rec = topic_skip(
                sub, TOPIC_NO_SOURCE_CODE,
                f"{sub} was taken from reserve[] to fill the slot of {tid} "
                f"(CF-0306) and 01-trend-hunter.json names no such topic, so "
                f"this stage has no candidate list for it. The slot is free "
                f"again and goes to the next reserve topic.")
            report["skipped_topics"] = list(report.get("skipped_topics") or [])
            report["skipped_topics"].append(rec)
            queue.append(rec)
            continue
        if not walk:
            entry["outcome"] = "not_walked"
            continue

        got, aliases, skipped, failed, by_topic = ingest(
            [topic], screening.promoting(sub),
            Path(report.get("batch") or "").name,
            max_per_topic=max_attempts, wanted=wanted, log=log,
            ceiling=ceiling, measurements=fresh_measured,
            depth_floor=depth_floor, depth_cache=cache, depths=fresh_depths,
            **ingest_kwargs)

        held = report.setdefault("sources_by_topic", {}).setdefault(sub, [])
        held.extend(v for v in (by_topic.get(sub) or ()) if v not in held)
        report["fetched"] = list(report.get("fetched") or []) + list(got)
        report["aliases"] = list(report.get("aliases") or []) + list(aliases)
        report["failed"] = list(report.get("failed") or []) + list(failed)
        report["skipped_topics"] = list(report.get("skipped_topics") or []) \
            + list(skipped)
        entry["sources"] = list(held)
        # CF-0419: under a floor that keeps (`warn`), a substitute short of
        # its second source but holding one is not a loss - `apply_floor_mode`
        # keeps it with a warning after this pass, so its slot is not free and
        # the queue must not offer it to the next reserve topic.
        # CF-0689: nor is a substitute standing on own graphics - the next
        # `apply_floor_mode` keeps it whatever the floor's mode.
        lost = [s for s in skipped
                if s.get("reason_code") in SLOT_FREEING_CODES
                and not (floor is not None and floor_keeps(floor)
                         and s.get("reason_code") == TOPIC_REFUSAL_CODE
                         and held)
                and not own_graphic_keeps(report, s.get("topic_id"))]
        entry["outcome"] = "refused" if lost else "sources"
        # A substitute this stage refuses leaves the same empty slot the topic
        # it replaced did, so it goes back into the queue as a loss of its own.
        queue.extend(lost)

    block["remaining"] = reserve_queue(screening, topics, used)
    report[SUBSTITUTION_KEY] = block

    # The blocks derived from the two lists this may have changed. Rebuilt, not
    # appended to, so they cannot drift from the records they are a view of.
    skipped_now = report.get("skipped_topics") or []
    report["two_source_floor"] = two_source_report(skipped_now, wanted,
                                                   max_attempts)
    report["compliance_gate"] = compliance_gate_report(skipped_now)
    report["index_failures"] = index_failures(report.get("failed") or [])
    report["dedup_log"] = [alias_line(a) for a in (report.get("aliases") or ())]
    if fresh_depths:
        by_topic_depth = {r["topic_id"]: r for r in
                          ((report.get("pool_depth") or {}).get("topics") or ())}
        for r in fresh_depths:
            by_topic_depth[r["topic_id"]] = r
        report["pool_depth"] = pool_depth.pool_depth_report(
            list(by_topic_depth.values()), depth_floor)
    if fresh_measured or block["substitutions"]:
        old = report.get("duration_ceiling") or {}
        measured = list(old.get("measured") or ()) + fresh_measured
        fresh = ceiling_report(ceiling, report.get("failed") or [], measured)
        if ceiling is None:
            # Nothing was handed in, so the numbers already in the report are
            # the channel's own and are kept - a substitution must never turn a
            # configured ceiling into this stage's defaults.
            for key in ("limits", "configured", "key", "config"):
                if key in old:
                    fresh[key] = old[key]
        report["duration_ceiling"] = fresh
    return report


# CF-0306, the second mode: the Content Researcher's own artifact, which is
# where a topic lost at the writing stage is on paper. `skipped[]` is the list
# it writes its refusals into (`pool_too_thin`, `no_production_fact`, ...) and
# `scripts[]` the topics it did write - the one list says which slots fell free
# and the other is the guard against being asked to replace a topic that is
# alive and written.
RESEARCHER_FILE = "03-content-researcher.json"
RESEARCHER_STAGE = "content-researcher"
RESEARCHER_REFUSAL_KEYS = ("skipped", "held_back", "skipped_topics")


def researcher_refusals(batch):
    """`(refusals, ran)` - the topics Content Researcher refused, in its order.

    `ran` is whether `03-content-researcher.json` is there at all: without it
    nothing has been written yet and the ids have to be named by hand, which
    the CLI says rather than guesses.
    """
    f = Path(batch) / RESEARCHER_FILE
    if not f.exists():
        return [], False
    doc = json.load(open(f))
    out, seen = [], set()
    for key in RESEARCHER_REFUSAL_KEYS:
        for s in doc.get(key) or ():
            tid = s.get("topic_id") if isinstance(s, dict) else None
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append({"topic_id": tid,
                        "reason_code": s.get("reason_code") or "unknown",
                        "reason": s.get("reason") or "",
                        "stage": s.get("stage") or RESEARCHER_STAGE})
    return out, True


def researcher_scripts(batch):
    """The topic ids Content Researcher did write a script for."""
    f = Path(batch) / RESEARCHER_FILE
    if not f.exists():
        return frozenset()
    doc = json.load(open(f))
    return frozenset(s["topic_id"] for s in doc.get("scripts") or ()
                     if isinstance(s, dict) and s.get("topic_id"))


def refill_slots(batch, args, report, topics, losses, at, log=print,
                 exhausted=True, **ingest_kwargs):
    """The walk both reserve modes share: `losses` refilled from the reserve
    under the channel's own settings, `report` amended in place (not written).

    CF-0197: the channel comes from the batch's own Trend Hunter file, or
    failing that from the `pipeline/<channel>/<batch>` directory name.
    CF-0419: a substitute walked here is held to the same floor mode as the
    first pass - under `warn` one held source keeps it, with a warning.
    """
    th = Path(batch) / "01-trend-hunter.json"
    th_doc = json.load(open(th)) if th.exists() else {}
    channel = resolve_channel(th_doc.get("channel") or Path(batch).resolve().parent.name)
    gate_mode, gate_from = floor_mode(
        channel, flag=getattr(args, "no_second_source", None))
    mark_own_graphic(report, topics, footage_origins(channel))   # CF-0689
    substitute_reserve(
        report, topics, verdicts(batch), losses=losses,
        at=at, wanted=args.sources_wanted,
        max_attempts=args.max_per_topic, depth_floor=args.pool_depth_floor,
        ceiling=duration_ceiling(channel),
        log=log, floor=gate_mode, exhausted=exhausted,
        **{"origins": footage_origins(channel), **ingest_kwargs})
    apply_floor_mode(report, gate_mode, wanted=args.sources_wanted, log=log,
                     whence=gate_from)
    return report


def reserve_mode(batch, args, log=print, **ingest_kwargs):
    """`ingest_batch.py <batch> --reserve-for [ids]` (CF-0306).

    The stage is asked back after Content Researcher: the topics it refused
    left their slots free, and this mode fetches and indexes *only* the reserve
    topics that take them, appending the result to the `01b-footage-index.json`
    that is already there. Nothing that already passed is walked again.

    The ids may be named on the command line or read from
    `03-content-researcher.json`; named ids are checked against it when it
    exists, because "replace topic X" for a topic that has a script is the one
    mistake this mode must not carry out silently.
    """
    dest = Path(batch) / REPORT_FILE
    if not dest.exists():
        sys.exit(f"no {REPORT_FILE} in {batch} - the reserve mode amends the "
                 f"report the first pass wrote, it does not start one")
    report = json.load(open(dest))
    th = Path(batch) / "01-trend-hunter.json"
    topics = json.load(open(th))["topics"] if th.exists() else []
    refusals, ran = researcher_refusals(batch)
    by_id = {r["topic_id"]: r for r in refusals}

    named = [t.strip() for t in (args.reserve_for or "").split(",") if t.strip()]
    if named:
        written = researcher_scripts(batch)
        losses = []
        for tid in named:
            if tid in written:
                sys.exit(f"{tid} has a script in {RESEARCHER_FILE} - it was "
                         f"not refused and its slot is not free. Nothing was "
                         f"written.")
            if ran and tid not in by_id:
                sys.exit(f"{RESEARCHER_FILE} records no refusal of {tid} "
                         f"(refused there: "
                         f"{', '.join(sorted(by_id)) or 'none'}). Nothing was "
                         f"written - name a topic that stage really lost, or "
                         f"re-read the artifact.")
            losses.append(by_id.get(tid) or {
                "topic_id": tid, "reason_code": "unknown", "stage": RESEARCHER_STAGE,
                "reason": f"named on the command line; no {RESEARCHER_FILE} to "
                          f"check it against"})
    else:
        if not ran:
            sys.exit(f"no {RESEARCHER_FILE} in {batch} and no topic ids given: "
                     f"--reserve-for reads that file to learn which slots fell "
                     f"free, or takes the ids itself")
        losses = refusals

    refill_slots(batch, args, report, topics, losses, "researcher_refusal",
                 log=log, **ingest_kwargs)
    write_report(batch, report)
    if report.get("aliases"):
        write_aliases(Path(batch), report["aliases"])

    block = report[SUBSTITUTION_KEY]
    mine = [s for s in block["substitutions"] if s.get("at") == "researcher_refusal"]
    empty = [u for u in block["unmatched"] if u.get("at") == "researcher_refusal"]
    log(f"{len(losses)} refused topic(s) from {RESEARCHER_STAGE}, "
        f"{len(mine)} slot(s) refilled, {len(block['remaining'])} reserve "
        f"topic(s) left -> {dest}")
    for s in mine:
        log(f"  {s['topic_id']} for {s['replaced']} "
            f"({s['replaced_reason_code']}): {s['outcome']}, "
            f"{len(s['sources'])} source(s)"
            + (f" - {', '.join(s['sources'])}" if s["sources"] else ""))
    for u in empty:
        log(f"  {u['replaced']} ({u['replaced_reason_code']}): "
            f"{RESERVE_EXHAUSTED_CODE}, the slot stays empty")
    if any(s["sources"] for s in mine):
        log("  next: describe every shot of the new sources (and their "
            "`burned_text`/`on_topic` flags), run source_sieve.py, then "
            "Content Researcher over the substituted topics ONLY - the "
            "scripts already in 03-content-researcher.json stay.")
    return 0


# CF-0799 (part of CF-0798, the user's "да" of 2026-10-18): the third place a
# slot falls free is the frame judge. Its artifact lists every finished video
# with a `gate`; anything but `pass` (`judge_footage_defect`,
# `score_below_threshold` after the judge, `frame_judge_failed`, ...) is a video
# the batch will not publish, so its topic's slot is free - although the topic
# has a script in 03, which is exactly what the researcher mode refuses. One
# round only: a topic that is itself a frame-judge substitute is never replaced
# again, whatever the judge says about it.
JUDGE_FILE = "06-frame-judge.json"
JUDGE_STAGE = "frame-judge"
JUDGE_AT = "frame_judge_refusal"
JUDGE_PASS = "pass"
JUDGE_INCOMPLETE_CODE = "frame_judge_failed"
JUDGE_REASON = "после судьи кадра"
NO_RESERVE_LINE = ("RESERVE no reserve left for {n} topic(s) the frame judge "
                   "refused ({ids}) - nothing recorded, the slot(s) stay empty")
_SCRIPT_SUFFIX = re.compile(r"-script\d+$")


def judge_refusals(batch):
    """`(refusals, ran)` - the topics whose video the frame judge did not pass.

    A topic counts as refused only when none of its videos passed. The topic id
    comes from the video's own `topic_id` when it has one, else from 03's
    `scripts[]` (`script_id` -> `topic_id`), else from the script id with its
    `-scriptN` suffix cut off. `ran` is whether `06-frame-judge.json` exists.
    """
    f = Path(batch) / JUDGE_FILE
    if not f.exists():
        return [], False
    doc = json.load(open(f))
    by_script = {}
    rf = Path(batch) / RESEARCHER_FILE
    if rf.exists():
        for s in json.load(open(rf)).get("scripts") or ():
            if isinstance(s, dict) and s.get("script_id") and s.get("topic_id"):
                by_script[s["script_id"]] = s["topic_id"]
    passed, out, seen = set(), [], set()
    for v in doc.get("videos") or ():
        if not isinstance(v, dict):
            continue
        sid = v.get("script_id")
        tid = (v.get("topic_id") or by_script.get(sid)
               or (_SCRIPT_SUFFIX.sub("", sid) if sid else None))
        if not tid:
            continue
        if v.get("gate") == JUDGE_PASS:
            passed.add(tid)
            continue
        if tid in seen:
            continue
        seen.add(tid)
        out.append({"topic_id": tid,
                    "reason_code": v.get("reason_code") or JUDGE_INCOMPLETE_CODE,
                    "reason": v.get("reason") or "",
                    "stage": JUDGE_STAGE,
                    "gate": v.get("gate"),
                    "script_id": sid,
                    "slug": v.get("slug")})
    return [r for r in out if r["topic_id"] not in passed], True


def judge_substitutes(report):
    """The topic ids already brought in to replace a frame-judge refusal."""
    return {s.get("topic_id") for s in
            ((report or {}).get(SUBSTITUTION_KEY) or {}).get("substitutions") or ()
            if isinstance(s, dict) and s.get("at") == JUDGE_AT and s.get("topic_id")}


def judge_reserve_mode(batch, args, log=print, **ingest_kwargs):
    """`ingest_batch.py <batch> --reserve-for [ids] --after-judge` (CF-0799).

    The lost slots are the frame judge's refusals in `06-frame-judge.json`
    (named ids are checked against them); the substitutes are picked, walked
    and recorded exactly as `reserve_mode` does - same reserve, same order,
    same accounting of what is already spent - with `at: frame_judge_refusal`,
    a reason starting «после судьи кадра», and the refused video's
    `replaced_script_id` / `replaced_slug` / `replaced_gate`.

    Idempotent: a refusal already answered is skipped, and a call that adds no
    substitution does not rewrite `01b`. No reserve left is a logged line and
    nothing recorded (`exhausted=False`), exit 0.
    """
    dest = Path(batch) / REPORT_FILE
    if not dest.exists():
        sys.exit(f"no {REPORT_FILE} in {batch} - the reserve mode amends the "
                 f"report the first pass wrote, it does not start one")
    refusals, ran = judge_refusals(batch)
    if not ran:
        sys.exit(f"no {JUDGE_FILE} in {batch}: --after-judge reads the frame "
                 f"judge's refusals from it. Nothing was written.")
    report = json.load(open(dest))
    th = Path(batch) / "01-trend-hunter.json"
    topics = json.load(open(th))["topics"] if th.exists() else []
    by_id = {r["topic_id"]: r for r in refusals}

    named = [t.strip() for t in (args.reserve_for or "").split(",") if t.strip()]
    for tid in named:
        if tid not in by_id:
            sys.exit(f"{JUDGE_FILE} records no refusal of {tid} (refused "
                     f"there: {', '.join(sorted(by_id)) or 'none'}). Nothing "
                     f"was written.")
    losses = [by_id[t] for t in named] if named else list(refusals)

    # One round only: a frame-judge substitute the judge refuses in turn
    # keeps its empty slot.
    second = judge_substitutes(report)
    for r in losses:
        if r["topic_id"] in second:
            log(f"RESERVE {r['topic_id']} ({r['reason_code']}) is itself a "
                f"frame-judge substitute - one round only, not replaced again")
    losses = [r for r in losses if r["topic_id"] not in second]

    block = (report.get(SUBSTITUTION_KEY) or {})
    answered = {s.get("replaced") for s in block.get("substitutions") or ()}
    answered |= {u.get("replaced") for u in block.get("unmatched") or ()}
    todo = [r for r in losses if r["topic_id"] not in answered]
    if not todo:
        log(f"{len(refusals)} topic(s) refused by {JUDGE_STAGE}, nothing left "
            f"to refill - {dest} unchanged")
        return 0
    if not reserve_queue(verdicts(batch), topics,
                         {s.get("topic_id") for s in block.get("substitutions") or ()
                          if s.get("topic_id")}):
        log(NO_RESERVE_LINE.format(n=len(todo),
                                   ids=", ".join(r["topic_id"] for r in todo)))
        return 0

    before = len(block.get("substitutions") or ())
    refill_slots(batch, args, report, topics, todo, JUDGE_AT, log=log,
                 exhausted=False, **ingest_kwargs)
    block = report[SUBSTITUTION_KEY]
    mine = block["substitutions"][before:]
    for s in mine:
        loss = by_id.get(s.get("replaced"))
        if loss is not None:
            s["replaced_script_id"] = loss.get("script_id")
            s["replaced_slug"] = loss.get("slug")
            s["replaced_gate"] = loss.get("gate")
        s["reason"] = (f"{JUDGE_REASON}: {s['topic_id']} занимает слот "
                       f"{s['replaced']}, отказанного на '{s['replaced_stage']}' "
                       f"с '{s['replaced_reason_code']}'"
                       + (f" (ролик {s['replaced_script_id']})"
                          if s.get("replaced_script_id") else "")
                       + f". {s['topic_id']} прошёл compliance в шортлисте "
                         f"этого батча и был неиспользованным резервом "
                         f"(CF-0306, CF-0799).")
    if not mine:
        log(f"{len(todo)} topic(s) refused by {JUDGE_STAGE}, no slot refilled "
            f"- {dest} unchanged")
        return 0
    write_report(batch, report)
    if report.get("aliases"):
        write_aliases(Path(batch), report["aliases"])
    log(f"{len(todo)} topic(s) refused by {JUDGE_STAGE}, {len(mine)} "
        f"substitution(s), {len(block['remaining'])} reserve topic(s) left "
        f"-> {dest}")
    for s in mine:
        log(f"  {s['topic_id']} for {s['replaced']} "
            f"({s['replaced_reason_code']}): {s['outcome']}, "
            f"{len(s['sources'])} source(s)"
            + (f" - {', '.join(s['sources'])}" if s["sources"] else ""))
    if any(s["sources"] for s in mine):
        log("  next: describe every shot of the new sources, run "
            "source_sieve.py, then compliance, Content Researcher, Video "
            "Editor and the frame judge over the substituted topics ONLY - "
            "everything the judge already passed stays.")
    return 0


# ---------------------------------------------------------------------------
# CF-0338, the thin-pool supplement.
#
# The user's ruling of 2026-09-23 on `widows-bay`: an anchor the topic's own
# sources cannot picture ("the actor's Emmy", and no frame of the actor) is
# answered by *more footage of the anchor's entity* - highlights, trailers,
# the actor's other work - fetched before the Video Editor, and not by an
# empty block. CF-0337 fills an empty block from whatever the topic's pool
# already holds; this is the step before that, for a pool that holds too
# little to fill anything.
#
# Three stages share the work, one repository each (the task's split): the
# writer's pool gates name the uncovered anchors and their entities, Trend
# Hunter searches for those entities with its own filters and quota, and this
# stage fetches what it found. What passes between them is one request file
# per topic - the shape a CF-0324 ingest-queue item will carry, so the queue,
# when it exists, gets a second producer and not a second path.
#
# The request is walked by `ingest()` itself: the CF-0302 length ceiling, the
# the single-attempt download, the CF-0080 fingerprint dedup (against the sources
# the topic *already holds* - `already=`), the CF-0281 index check and the
# CF-0304 depth measure are the same code as for any other source. Two things
# are this mode's own: the checks on the request itself (below), and that a
# supplement never refuses the topic - a topic that holds its sources and got
# nothing more from the supplement is exactly as alive as it was.

SUPPLEMENT_KIND = "thin_pool_supplement"
SUPPLEMENT_KEY = "supplements"
SUPPLEMENT_MAX_ATTEMPTS = 3
# A YouTube video id: the only host this stage fetches from, so a candidate
# that is not one is refused on the request, before any network is touched.
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Keys Trend Hunter uses on a candidate it dropped (`footage_candidates_dropped`
# records carry `drop_reason`/`reason_code`): such a record handed in as a
# candidate is a caller's mistake, and the upstream verdict stands.
SUPPLEMENT_DROP_KEYS = ("drop_reason", "dropped", "reason_code")

SUPPLEMENT_REJECT_NOT_YOUTUBE = "not_youtube_id"
SUPPLEMENT_REJECT_NO_ENTITY = "no_entity"
SUPPLEMENT_REJECT_DROPPED = "dropped_upstream"
SUPPLEMENT_REJECT_TRIED = "already_tried"


class SupplementRefused(ValueError):
    """The request file itself is unusable - nothing is fetched for it."""


# ---------------------------------------------------------------------------
# CF-0429, the supplement's wall-clock deadline.
#
# Verification run `example-film/2026-09-28T1126Z`: the root step's 30-minute
# wall ceiling (CF-0426) came inside this stage, the root killed
# `--supplement` at its timeout, and `01b` - written once, at the end - never
# was: everything downloaded in that call was lost, 0 of 23 candidates reached
# the pool, 84 search calls spent for nothing.
#
# `--deadline <epoch|iso>` is the ceiling handed down. Past it nothing new is
# started (no probe, download, fingerprint, `index_footage.py`); what is already downloaded *and indexed* is written to `01b`; every
# candidate the call did not finish is listed under the request's entry with
# `outcome: wall_ceiling`; the exit is 0.
#
# A download or an index in flight at the deadline is killed, not finished: a
# single yt-dlp call has been measured at 494 s and an index of an hour-long
# source runs for minutes, so "finish it" would put the end of the call up to
# ten minutes past a deadline whose whole point is that the call ends there -
# and the root kills at its own timeout anyway, which is the loss this task
# is about. `Deadline.arm()` starts a watcher thread that, once the deadline
# has passed, sends SIGTERM to every descendant of this process (yt-dlp,
# ffmpeg, index_footage.py and theirs) and SIGKILL to one still there after
# `WALL_KILL_GRACE_SECONDS` - by the pids and start times it SIGTERMed, not
# by a fresh walk, since a grandchild orphaned by its parent's death drops off
# that walk (CF-0680; not a group kill: the root starts FI in its own session,
# so its children share FI's group and `killpg` would take FI down too); the walk reads the kill as "the deadline took
# it", never as a lost download or a failed index. The candidate's media, if
# it came down whole, stays in the cache, so a later call gets it for free.
#
# Killed anyway (the outer SIGTERM, CF-0426's `_kill_group`): SIGTERM is read
# as "the deadline is now" - the same path, inside the root's 10 s grace - and
# `01b` is also written after every source that got in and after every
# request, so a SIGKILL loses at most the candidate that was in flight.

WALL_CEILING = "wall_ceiling"      # the root step's word (shared/runlog/supplement.py)
WALL_TASK = "CF-0429"
CUT_BEFORE = "before_download"     # never started
CUT_DOWNLOAD = "download"          # the download was killed at the deadline
CUT_INDEX = "index"                # came down, index not started or killed
IN_PROGRESS = "in_progress"        # an entry flushed mid-walk (see above)
WALL_SWEEP_SECONDS = 0.5
WALL_KILL_GRACE_SECONDS = 3.0
WALL_CAUSE_DEADLINE = "deadline"
WALL_CAUSE_SIGTERM = "sigterm"


def parse_deadline(text):
    """`--deadline`: epoch seconds (`1790000000`, `1790000000.5`) or ISO 8601
    (`2026-09-28T12:00:00Z`, `...+03:00`; no zone = UTC). -> epoch float."""
    raw = str(text).strip()
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z"))
                                    else raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--deadline {text!r}: neither epoch seconds nor ISO 8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _iso(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_descendants(pid=None):
    """Every live descendant of `pid` (this process by default), one `ps`."""
    pid = os.getpid() if pid is None else pid
    try:
        ps = subprocess.Popen(["ps", "-A", "-o", "pid=,ppid="],
                              stdout=subprocess.PIPE, text=True)
        out, _ = ps.communicate(timeout=10)
    except Exception:
        return []
    kids = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for c in kids.get(todo.pop(), ()):
            if c != ps.pid and c not in found:
                found.append(c)
                todo.append(c)
    return found



def process_starts(pids):
    """{pid: start time} of those of `pids` still running, one `ps -o lstart`
    (CF-0680: the watcher's check that a pid it SIGTERMed is still the same
    process, not a reused one). A pid that is gone is absent; any failure of
    `ps` itself, the ceiling included, returns {}."""
    pids = [int(p) for p in pids]
    if not pids:
        return {}
    try:
        out = subprocess.run(["ps", "-o", "pid=,lstart=", "-p",
                              ",".join(map(str, pids))],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return {}
    found = {}
    for line in out.splitlines():
        head, _, stamp = line.strip().partition(" ")
        if head.isdigit() and stamp.strip():
            found[int(head)] = stamp.strip()
    return found

class Deadline:
    """The moment after which the supplement starts nothing new (CF-0429).

    `at` is epoch seconds or None (no deadline - `passed()` is then False
    until `expire()`); `clock` is the seam tests turn. `cause` says what ended
    the call: `deadline` or `sigterm`.
    """

    def __init__(self, at=None, clock=time.time):
        self.at = at
        self.clock = clock
        self.cause = None
        self.killed = []            # pids the watcher signalled
        self._stop = threading.Event()
        self._thread = None

    def passed(self):
        if self.cause:
            return True
        if self.at is not None and self.clock() >= self.at:
            self.cause = WALL_CAUSE_DEADLINE
            return True
        return False

    def remaining(self):
        """Seconds left, 0 once passed, None with no deadline at all."""
        if self.passed():
            return 0.0
        return None if self.at is None else max(0.0, self.at - self.clock())

    def expire(self, cause=WALL_CAUSE_SIGTERM):
        """The deadline is now. Safe in a signal handler: it only sets a
        field, which the walk and the watcher both poll."""
        if not self.cause:
            self.cause = cause

    def arm(self, descendants=list_descendants, send=os.kill,
            sweep=WALL_SWEEP_SECONDS, grace=WALL_KILL_GRACE_SECONDS,
            starts=None):
        """Start the watcher: past the deadline, SIGTERM every descendant,
        SIGKILL one still alive `grace` seconds later; every `sweep` s.

        CF-0680: the SIGKILL goes by the watcher's own memory of what it
        SIGTERMed - pid and start time (`starts`, `process_starts` by
        default) - not by a fresh `descendants()`: a grandchild that ignores
        SIGTERM and whose parent died on it is adopted by launchd/init and
        drops off that list. A remembered pid is SIGKILLed while it is still
        the same process (same start time) or is still on the list; gone or
        reused (another start time), it is forgotten."""
        if self._thread is not None:
            return self
        starts = process_starts if starts is None else starts

        def signal_(pid, sig):
            try:
                send(pid, sig)
            except (OSError, ProcessLookupError):
                pass

        def watch():
            termed = {}             # pid -> (monotonic at SIGTERM, start time)
            while not self._stop.is_set():
                if self.passed():
                    now = time.monotonic()
                    listed = list(descendants())
                    new = [pid for pid in listed if pid not in termed]
                    if new:
                        stamps = starts(new) or {}      # before the SIGTERM
                        for pid in new:
                            termed[pid] = (now, stamps.get(pid))
                            self.killed.append(pid)
                            signal_(pid, signal.SIGTERM)
                    due = [pid for pid, (at, _) in termed.items()
                           if now - at >= grace]
                    if due:
                        stamps = starts(due) or {}
                        for pid in due:
                            was = termed[pid][1]
                            same = was is not None and stamps.get(pid) == was
                            if same or pid in listed:
                                signal_(pid, signal.SIGKILL)
                            else:
                                del termed[pid]
                self._stop.wait(sweep)

        self._thread = threading.Thread(target=watch, name="supplement-deadline",
                                        daemon=True)
        self._thread.start()
        return self

    def disarm(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def view(self):
        return {"deadline": _iso(self.at), "deadline_epoch": self.at,
                "cause": self.cause, "task": WALL_TASK}


def _entity_names(raw):
    out = []
    for e in raw or ():
        name = e.get("name") if isinstance(e, dict) else e
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip())
    return out


def read_supplement(doc, where="request"):
    """A supplement request, checked and normalised; `SupplementRefused` if
    it cannot be walked at all.

    `doc` is the parsed JSON (or a path to it). Refused outright: another
    `kind`, no `topic_id`, no entity (a supplement answers an uncovered
    anchor's *entity* - without one it is an unexplained list of videos), and
    a `candidates` that is not a list. An empty candidate list is not refused:
    it is a request the search could not answer, and is recorded as such.
    """
    if not isinstance(doc, dict):
        where = str(doc)
        try:
            doc = json.load(open(doc))
        except Exception as e:
            raise SupplementRefused(f"{where}: unreadable ({type(e).__name__}: {e})")
    if not isinstance(doc, dict):
        raise SupplementRefused(f"{where}: not a JSON object")
    if doc.get("kind") != SUPPLEMENT_KIND:
        raise SupplementRefused(f"{where}: kind is {doc.get('kind')!r}, not "
                                f"{SUPPLEMENT_KIND!r}")
    tid = doc.get("topic_id")
    if not isinstance(tid, str) or not tid:
        raise SupplementRefused(f"{where}: no topic_id")
    entities = _entity_names(doc.get("entities"))
    if not entities:
        raise SupplementRefused(f"{where}: no entities - a supplement answers "
                                f"the entity of an uncovered anchor (CF-0338)")
    cands = doc.get("candidates", [])
    if not isinstance(cands, list):
        raise SupplementRefused(f"{where}: candidates is not a list")
    wanted = doc.get("shots_wanted")
    if not (isinstance(wanted, int) and not isinstance(wanted, bool)
            and wanted > 0):
        wanted = None
    attempts = doc.get("max_attempts")
    if not (isinstance(attempts, int) and not isinstance(attempts, bool)
            and attempts > 0):
        attempts = SUPPLEMENT_MAX_ATTEMPTS
    return {"topic_id": tid, "entities": entities,
            "reason_code": doc.get("reason_code") or "pool_too_thin",
            "shots_wanted": wanted, "max_attempts": attempts,
            "candidates": [c for c in cands if isinstance(c, dict)],
            "where": where}


def supplement_candidates(req, tried=()):
    """`(accepted, rejected)` over the request's candidates, in its order.

    The request-level half of "the same host and rights checks as any
    source": YouTube ids only, a candidate that names one of the request's
    entities (it was searched *for* this shortfall), and never a record the
    hunter had already dropped. An id the topic already touched - a source,
    an alias, a loss - is not offered again; it costs nothing and is listed.
    """
    names = {n.casefold() for n in req["entities"]}
    accepted, rejected, seen = [], [], set()
    for c in req["candidates"]:
        vid = c.get("video_id")
        if not isinstance(vid, str) or not YOUTUBE_ID.match(vid):
            rejected.append({"video_id": vid, "reason_code":
                             SUPPLEMENT_REJECT_NOT_YOUTUBE})
            continue
        if vid in seen:
            continue
        seen.add(vid)
        if any(c.get(k) for k in SUPPLEMENT_DROP_KEYS):
            rejected.append({"video_id": vid, "reason_code":
                             SUPPLEMENT_REJECT_DROPPED,
                             "upstream": next(c.get(k) for k in SUPPLEMENT_DROP_KEYS
                                              if c.get(k))})
            continue
        ent = c.get("entity")
        if not isinstance(ent, str) or ent.strip().casefold() not in names:
            rejected.append({"video_id": vid, "reason_code":
                             SUPPLEMENT_REJECT_NO_ENTITY, "entity": ent})
            continue
        if vid in tried:
            rejected.append({"video_id": vid, "reason_code":
                             SUPPLEMENT_REJECT_TRIED})
            continue
        accepted.append(c)
    return accepted, rejected


def topic_tried(report, tid):
    """Every id topic `tid` has touched in this batch - sources, aliases,
    losses - the same list `source_sieve.prior_state()` reads."""
    tried = list((report.get("sources_by_topic") or {}).get(tid) or [])
    for key in ("aliases", "failed"):
        for r in report.get(key) or ():
            if r.get("topic_id") == tid and r.get("video_id") not in tried:
                tried.append(r.get("video_id"))
    return tried


def topic_held_paths(report, tid, cache=None):
    """`(video_id, path)` of the sources topic `tid` holds, for `already=`."""
    held = (report.get("sources_by_topic") or {}).get(tid) or []
    paths = {f.get("video_id"): f.get("path") for f in report.get("fetched") or ()
             if f.get("topic_id") == tid}
    return [(v, paths.get(v) or str(pool_depth.index_path(v, cache)).replace(
        ".shots.json", ".mp4")) for v in held]


def _depth_view(depth):
    return {"usable_shots": depth.usable, "shots": depth.shots,
            "sources": depth.sources, "measured": depth.measured}


def supplement_key(req):
    """What makes two requests the same one: the topic and the set of ids."""
    return f"{req['topic_id']}:" + ",".join(sorted(
        str(c.get("video_id")) for c in req["candidates"]))


def _answered(block, key):
    """The last entry of the same request that is a finished answer, or None.

    CF-0429: an entry the deadline cut (`wall_ceiling`), or one a killed call
    left half-written (`in_progress`), is not an answer - the next call walks
    what it did not get to (the ids it did get are `already_tried` then)."""
    same = [e for e in block if e.get("key") == key]
    if not same:
        return None
    last = same[-1]
    if last.get(WALL_CEILING) or last.get("outcome") in (WALL_CEILING, IN_PROGRESS):
        return None
    return last


def _merge_walk(report, entry, req, held, accepted, got, aliases, failed, by_topic):
    """What one walk brought, into `report` and its `entry` (in place)."""
    tid = req["topic_id"]
    new = [v for v in (by_topic.get(tid) or []) if v not in held]
    report.setdefault("sources_by_topic", {})[tid] = held + new
    for f in got:
        f["supplement"] = {"reason_code": req["reason_code"],
                           "entity": next((c.get("entity") for c in accepted
                                           if c["video_id"] == f["video_id"]),
                                          None)}
    report["fetched"] = list(report.get("fetched") or []) + list(got)
    report["aliases"] = list(report.get("aliases") or []) + list(aliases)
    report["failed"] = list(report.get("failed") or []) + list(failed)
    report["index_failures"] = index_failures(report["failed"])
    report["dedup_log"] = [alias_line(a) for a in report["aliases"]]
    entry["new_sources"] = new
    entry["aliases"] = [a["video_id"] for a in aliases]
    entry["failed"] = [{"video_id": f["video_id"],
                        "reason_code": f.get("reason_code")} for f in failed]
    return new


def _wall_block(deadline, cut, accepted, reached_at=None):
    """`entry["wall_ceiling"]`: when, why, and the candidates it took."""
    ents = {c["video_id"]: c.get("entity") for c in accepted}
    block = dict(deadline.view())
    block["reached_at"] = reached_at or _iso(time.time())
    block["candidates"] = [{"video_id": c["video_id"], "entity": ents.get(c["video_id"]),
                            "outcome": WALL_CEILING, "refused_at": WALL_CEILING,
                            "at": c["at"], "task": WALL_TASK, "attempt_spent": False}
                           for c in cut]
    return block


def supplement_topic(report, req, screening, cache=None, log=print,
                     ceiling=None, measurements=None, deadline=None, flush=None,
                     **ingest_kwargs):
    """Walk one supplement request and append what it brought to `report`.

    Returns the entry written to `report["supplements"]` - one per request,
    and a request already answered (same topic, same candidate ids) is not
    walked again, which is what makes the mode idempotent.

    CF-0429: `deadline` (a `Deadline`) stops the walk - see the block above
    `parse_deadline()`; the candidates it took are in `entry["wall_ceiling"]`.
    `flush(report)` is called with a snapshot after every new source, the
    entry then at `outcome: in_progress`.
    """
    tid = req["topic_id"]
    block = report.setdefault(SUPPLEMENT_KEY, [])
    key = supplement_key(req)
    old = _answered(block, key)
    if old is not None:
        log(f"SUPPLEMENT {tid}: already answered ({old.get('outcome')}), "
            f"nothing walked")
        return old
    if any(e.get("key") == key for e in block):
        log(f"SUPPLEMENT {tid}: resuming a request the deadline cut last time")
    held = list((report.get("sources_by_topic") or {}).get(tid) or [])
    entry = {"key": key, "topic_id": tid, "request": req["where"],
             "reason_code": req["reason_code"], "entities": req["entities"],
             "shots_wanted": req["shots_wanted"],
             "max_attempts": req["max_attempts"], "offered": [],
             "rejected": [], "new_sources": [], "aliases": [], "failed": [],
             "shots_before": None, "shots_after": None, "shots_added": None,
             "covers_shortfall": None, "outcome": None}
    block.append(entry)

    refused = [s for s in report.get("skipped_topics") or ()
               if s.get("topic_id") == tid]
    if refused or not held:
        # A supplement adds to a pool; it is not a second way through the
        # CF-0129 two-source walk for a topic this stage already dropped.
        entry["outcome"] = "topic_refused" if refused else "topic_not_held"
        log(f"SUPPLEMENT {tid}: {entry['outcome']} - this stage holds no pool "
            f"for it, nothing walked")
        return entry

    accepted, rejected = supplement_candidates(req, topic_tried(report, tid))
    entry["offered"] = [c["video_id"] for c in accepted]
    entry["rejected"] = rejected
    before = pool_depth.topic_depth(tid, held, cache=cache)
    entry["shots_before"] = _depth_view(before)
    if not accepted:
        entry["outcome"] = "nothing_to_try"
        entry["shots_after"] = entry["shots_before"]
        entry["shots_added"] = 0
        log(f"SUPPLEMENT {tid}: nothing to try ({len(rejected)} candidate(s) "
            f"rejected on the request)")
        return entry
    if deadline is not None and deadline.passed():
        # CF-0429: the deadline came before this request - nothing started.
        entry[WALL_CEILING] = _wall_block(
            deadline, [{"video_id": c["video_id"], "at": CUT_BEFORE}
                       for c in accepted], accepted)
        entry["outcome"] = WALL_CEILING
        entry["shots_after"] = entry["shots_before"]
        entry["shots_added"] = 0
        log(f"SUPPLEMENT {tid}: {WALL_CEILING} - the deadline came before this "
            f"request, {len(accepted)} candidate(s) not tried")
        return entry

    # How much is enough. With `shots_wanted` and a pool that could be
    # measured, the CF-0304 depth floor is moved to "what it holds now plus
    # what is missing" and the walk stops the moment the pool gets there; the
    # source count is already met (`wanted = held`). Otherwise the ask is one
    # new canonical source - a supplement that adds nothing is not an answer.
    if req["shots_wanted"] and before.measured:
        depth_floor = before.usable + req["shots_wanted"]
        wanted = len(held)
    else:
        depth_floor = 0
        wanted = len(held) + 1
    entry["depth_floor"] = depth_floor

    topic = {"topic_id": tid,
             "evidence": {"youtube_video_ids": [c["video_id"] for c in accepted],
                          "footage_candidates": accepted}}
    screening = as_screening(screening)
    gate = screening.promoting(tid) if tid in screening.reserve else screening
    fresh_depths = []
    cut = []
    index_at = len(block) - 1

    def snapshot(got_, aliases_, failed_, by_topic_):
        # CF-0429: the report as it would read if the call ended right now.
        if flush is None:
            return
        snap = copy.deepcopy(report)
        e = snap[SUPPLEMENT_KEY][index_at]
        _merge_walk(snap, e, req, held, accepted, copy.deepcopy(list(got_)),
                    copy.deepcopy(list(aliases_)), copy.deepcopy(list(failed_)),
                    copy.deepcopy(dict(by_topic_)))
        e["outcome"] = IN_PROGRESS
        flush(snap)

    got, aliases, _skipped, failed, by_topic = ingest(
        [topic], gate, Path(report.get("batch") or "").name,
        max_per_topic=req["max_attempts"], wanted=wanted,
        already={tid: topic_held_paths(report, tid, cache)},
        depth_floor=depth_floor, depth_cache=cache, depths=fresh_depths,
        ceiling=ceiling, measurements=measurements, log=log,
        deadline=deadline, cut=cut, on_source=snapshot, **ingest_kwargs)
    # `_skipped` is not copied into the report: with `wanted = held + 1` a walk that
    # found nothing reads to `ingest()` as a topic under its floor, and this
    # topic is not refused - it holds exactly what it held before.
    new = _merge_walk(report, entry, req, held, accepted, got, aliases, failed,
                      by_topic)
    after = pool_depth.topic_depth(tid, held + new, cache=cache)
    entry["shots_after"] = _depth_view(after)
    if before.measured and after.measured:
        entry["shots_added"] = after.usable - before.usable
        if req["shots_wanted"]:
            entry["covers_shortfall"] = entry["shots_added"] >= req["shots_wanted"]
    if cut:
        entry[WALL_CEILING] = _wall_block(deadline, cut, accepted)
    gated = [x for x in _skipped if x.get("reason_code") in PRE_FETCH_CODES]
    entry["outcome"] = ("sources" if new else WALL_CEILING if cut else
                        gated[0]["reason_code"] if gated else "no_new_source")
    log(f"SUPPLEMENT {tid}: {len(new)} new source(s)"
        + (f" ({', '.join(new)})" if new else "")
        + f", usable shots {before.usable} -> {after.usable}"
        + (f", {req['shots_wanted']} wanted" if req["shots_wanted"] else "")
        + (f"; {WALL_CEILING}: {len(cut)} candidate(s) not finished "
           f"({', '.join(c['video_id'] for c in cut)})" if cut else ""))
    return entry


def supplement_paths(items):
    """Request files named on the command line; a directory stands for the
    `*.json` in it, in name order."""
    out = []
    for item in items or ():
        p = Path(item)
        if p.is_dir():
            out.extend(sorted(p.glob("*.json")))
        else:
            out.append(p)
    return out


def supplement_mode(batch, args, log=print, reap=True, **ingest_kwargs):
    """`ingest_batch.py <batch> --supplement <request.json|dir> ...` (CF-0338).

    Amends the `01b-footage-index.json` already in the batch, as the
    `--reserve-for` mode does; a request that cannot be read is named and
    skipped, the others still run.

    CF-0429: `args.deadline` (epoch seconds, `--deadline`) bounds the call -
    see the block above `parse_deadline()`. A test hands a ready `Deadline`
    in as `deadline=` instead (its clock is the test's); `reap=False` keeps
    the watcher that kills descendants at the deadline off. SIGTERM is taken
    as the deadline arriving now. `01b` is written after every new source,
    after every request, and at the end.
    """
    dest = Path(batch) / REPORT_FILE
    if not dest.exists():
        sys.exit(f"no {REPORT_FILE} in {batch} - the supplement mode adds to "
                 f"the pool the first pass wrote, it does not start one")
    report = json.load(open(dest))
    th = Path(batch) / "01-trend-hunter.json"
    th_doc = json.load(open(th)) if th.exists() else {}
    channel = resolve_channel(th_doc.get("channel")
                              or Path(batch).resolve().parent.name)
    ceiling = ingest_kwargs.pop("ceiling", None) or duration_ceiling(channel)
    if "origins" not in ingest_kwargs:
        ingest_kwargs["origins"] = footage_origins(channel)     # CF-0663
    cache = ingest_kwargs.pop("depth_cache", None)
    screening = verdicts(batch)
    paths = supplement_paths(args.supplement)
    if not paths:
        sys.exit("--supplement names no request file")
    deadline = (ingest_kwargs.pop("deadline", None)
                or Deadline(getattr(args, "deadline", None)))
    if deadline.at is not None:
        log(f"DEADLINE {_iso(deadline.at)} ({deadline.at:.0f}): nothing new is "
            f"started after it (CF-0429)")
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM,
                                 lambda signum, frame: deadline.expire())
    if reap:
        deadline.arm()
    entries, bad = [], []
    measured = []
    try:
        for path in paths:
            try:
                req = read_supplement(path)
            except SupplementRefused as e:
                bad.append(str(e))
                log(f"SUPPLEMENT refused: {e}")
                continue
            entries.append(supplement_topic(
                report, req, screening, cache=cache, log=log, ceiling=ceiling,
                measurements=measured,
                deadline=deadline, flush=lambda snap: write_report(batch, snap),
                **ingest_kwargs))
            write_report(batch, report)      # CF-0429: request by request
    finally:
        deadline.disarm()
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    write_report(batch, report)
    if report.get("aliases"):
        write_aliases(Path(batch), report["aliases"])
    grew = [e for e in entries if e.get("new_sources")]
    log(f"{len(entries)} supplement request(s) walked, {len(bad)} unreadable, "
        f"{len(grew)} topic pool(s) grew -> {dest}")
    walled = [e for e in entries if e.get(WALL_CEILING)]
    if walled:
        log(f"{WALL_CEILING.upper()} ({deadline.cause}): "
            f"{sum(len(e[WALL_CEILING]['candidates']) for e in walled)} "
            f"candidate(s) of {len(walled)} request(s) not finished - "
            f"supplements[].wall_ceiling in {dest.name} (CF-0429)")
    if grew:
        log("  next: describe every shot of the new sources, run "
            "source_sieve.py, then the writer's pool gates over these topics "
            "again - the Video Editor reads the grown pool from "
            "sources_by_topic.")
    return 0


def progress_tracker(batch, wanted=SOURCES_WANTED, max_attempts=MAX_ATTEMPTS_PER_TOPIC,
                     floor=pool_depth.POOL_DEPTH_FLOOR):
    """CF-0715: the root's `footage_progress.Tracker` for `batch` - the writer
    of `<batch>/work/footage-progress.json`, the command center's per-topic
    view of this stage (`shared/runlog/footage_progress.py` holds the format
    and the reader). None when the root is not there (`_runlog`'s silent
    stand-in) or has no such module: the walk then runs without the file, and
    the reader falls back to RUN_EVENTS."""
    try:
        make = getattr(runlog.sibling("footage_progress"), "tracker", None)
        return make(batch, needed=wanted, max_attempts=max_attempts,
                    floor=floor) if make else None
    except Exception:
        return None


def write_report(batch, report):
    """`01b-footage-index.json`, written whole or not at all.

    CF-0306: the `--reserve-for` mode amends a file other passes of this stage
    wrote - `sources_by_topic`, `failed[]`, `pool_depth`, the sieve's block -
    so a half-written document would lose a batch's whole footage record. The
    temporary file is in the batch directory so the rename is on one
    filesystem and is therefore atomic.
    """
    dest = Path(batch) / REPORT_FILE
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(report, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dest)
    return dest


def build_report(batch, fetched, aliases, skipped, failed, sources_by_topic,
                 wanted=SOURCES_WANTED,
                 max_attempts=MAX_ATTEMPTS_PER_TOPIC, ceiling=None,
                 measurements=(), depths=(),
                 depth_floor=pool_depth.POOL_DEPTH_FLOOR):
    return {
        "batch": str(batch),
        "fetched": fetched,
        "sources_by_topic": sources_by_topic,
        "aliases": aliases,
        "dedup_log": [alias_line(a) for a in aliases],
        # CF-0129 / CF-0232: one record per topic this stage dropped, each
        # with the funnel's `reason_code` and `stage` - the same four keys
        # Trend Hunter writes in its own `skipped_topics`.
        "skipped_topics": [dict(s) for s in skipped],
        # CF-0281: one record per id this stage did not turn into a
        # usable source, each carrying `reason_code` - `fetch_failed` for a
        # download YouTube refused, `index_failed` for one that came down and
        # could not be indexed - the rung it was refused at and every attempt.
        "failed": failed,
        # CF-0281: the second kind on its own, for a reader asking why a topic
        # has less footage than `fetched` suggests. Empty when none failed.
        "index_failures": index_failures(failed),
        "two_source_floor": two_source_report(skipped, wanted, max_attempts),
        # CF-0304: how deep every topic's pool ended up, the floor that was in
        # force, and the topics that stayed under it with nothing left to try.
        # Never a refusal - see the block's own note.
        "pool_depth": pool_depth.pool_depth_report(depths, depth_floor),
        # CF-0302: the ceiling that was in force, what it refused before any
        # download, and what could not be measured.
        "duration_ceiling": ceiling_report(ceiling, failed, measurements),
        # CF-0265: the topics compliance decided before any download.
        "compliance_gate": compliance_gate_report(skipped),
        "fetch": {"pause_seconds": list(FETCH_PAUSE_SECONDS)},
        "note": "Evidence videos come from search, so none are marked official. "
                "Prefer an official upload for anything that reaches a "
                "finished video. `fetched` lists canonical "
                "sources only: a re-upload of another source of the same topic is in "
                "`aliases` (CF-0080), not indexed, and is referred to by its canonical id.",
    }


def line_buffered(stream=None):
    """CF-0239: switch stdout (or `stream`) to line buffering, so the stage's
    progress reaches a log file or a pipe line by line. Silent where the
    stream cannot be reconfigured (a test's StringIO)."""
    stream = sys.stdout if stream is None else stream
    try:
        stream.reconfigure(line_buffering=True)
    except (AttributeError, ValueError, OSError):
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("batch")
    p.add_argument("--max-per-topic", type=int, default=MAX_ATTEMPTS_PER_TOPIC,
                   help="CF-0129: how many distinct candidate videos one topic "
                        "may spend reaching the two-source floor")
    p.add_argument("--sources-wanted", type=int, default=SOURCES_WANTED,
                   help="canonical sources a topic needs after CF-0080 dedup; "
                        "below it the topic is refused with `no_second_source`")
    p.add_argument("--pool-depth-floor", type=int,
                   default=pool_depth.POOL_DEPTH_FLOOR,
                   help="CF-0304: shots of a topic's pool that must survive the "
                        "Video Editor's pre-cut gate before this stage stops "
                        "taking candidates for it. A topic under it is never "
                        "refused here, only listed in `pool_depth.thin[]`; 0 "
                        "turns the question off")
    p.add_argument("--reserve-for", nargs="?", const="", default=None,
                   metavar="TOPIC_ID[,TOPIC_ID...]",
                   help="CF-0306: do not run the batch's own pass - fetch and "
                        "index only the reserve topics that take the slots of "
                        "the named topics, and append them to the "
                        "01b-footage-index.json that is already there. With no "
                        "ids, the refusals of 03-content-researcher.json are "
                        "the list; named ids are checked against it. Run it "
                        "after Content Researcher has refused topics and the "
                        "reserve still holds something.")
    p.add_argument("--after-judge", action="store_true",
                   help="CF-0799: with --reserve-for, the lost slots are the "
                        "frame judge's refusals in 06-frame-judge.json (every "
                        "video whose gate is not `pass`), not 03's; a topic "
                        "with a script is allowed (the judge freed its slot). "
                        "Substitutes are recorded with at: frame_judge_refusal; "
                        "one round only, a second call does nothing.")
    p.add_argument("--no-reserve", action="store_true",
                   help="CF-0306: do not refill a slot this stage lost from "
                        "02-compliance-checker.json reserve[]; record the "
                        "refusal and leave the slot empty, as before 2026-09-21")
    p.add_argument("--supplement", nargs="+", default=None,
                   metavar="REQUEST",
                   help="CF-0338: do not run the batch's own pass - walk the "
                        "thin-pool supplement request(s) (a file, or a "
                        "directory of *.json) and append the new sources to "
                        "their topics in 01b-footage-index.json")
    p.add_argument("--deadline", type=parse_deadline, default=None,
                   metavar="EPOCH|ISO",
                   help="CF-0429, with --supplement only: start nothing new after "
                        "this moment (epoch seconds or ISO 8601, no zone = UTC); "
                        "what is downloaded and indexed by then is written to "
                        "01b-footage-index.json, the rest is listed as "
                        "supplements[].wall_ceiling; exit 0")
    p.add_argument("--no-pool", action="store_true",
                   help="CF-0325: do not count the pool sources Trend Hunter "
                        "matched to a topic (topics[].pool.matched); fetch "
                        "every topic from its candidates alone, as before")
    p.add_argument("--index-workers", type=int, default=None, metavar="N",
                   help="CF-0332: sources indexed at once (downloads stay one "
                        f"at a time). Default ${INDEX_WORKERS_ENV}, else "
                        f"{DEFAULT_INDEX_WORKERS}; 1 is the sequential walk")
    add_vision_flags(p)                                     # CF-0843
    p.add_argument("--no-second-source", "--two-source-gate",
                   dest="no_second_source", choices=FLOOR_MODES, default=None,
                   help=f"CF-0419: override {FLOOR_RULE} for this run (else "
                        f"the channel's {FLOOR_RULE}, else its "
                        "video_editor.two_source_gate, else `warn`). "
                        "`warn`/`measure`/`off` keep a one-source topic with "
                        "a warning, `enforce`/`fail`/`refuse` refuse it with "
                        "no_second_source. `--two-source-gate` is the CF-0362 "
                        "spelling of the same flag")
    args = p.parse_args()
    # CF-0239: every line out at once, also when stdout is a file or a pipe
    # (the 2026-09-15 log stayed at 0 bytes for an hour of work).
    line_buffered()
    if args.deadline is not None and args.supplement is None:
        p.error("--deadline bounds the --supplement mode only (CF-0429)")
    if args.after_judge and args.reserve_for is None:
        p.error("--after-judge is a variant of --reserve-for (CF-0799)")

    batch = Path(args.batch)
    th = batch / "01-trend-hunter.json"
    if not th.exists():
        sys.exit(f"no Trend Hunter output in {batch}")
    # CF-0567: an own capture is looked for in the batch's captures/ first.
    global CAPTURE_DIRS
    CAPTURE_DIRS = capture_dirs(batch_dir=batch)

    # CF-0306: the stage called back after Content Researcher. It walks the
    # substitutes and nothing else, so it is its own path out of here - the
    # pass below would re-decide every topic of the batch.
    if args.supplement is not None:
        fetch_footage.sweep_partials(log=print)
        return supplement_mode(batch, args)
    if args.reserve_for is not None:
        # CF-0090: the same sweep the ordinary pass does, for the same reason -
        # this mode downloads too.
        fetch_footage.sweep_partials(log=print)
        mode = judge_reserve_mode if args.after_judge else reserve_mode
        return mode(batch, args)

    doc = json.load(open(th))
    topics = doc["topics"]
    verdict = verdicts(batch)

    # CF-0197: the channel name comes from outside - the `channel` field frozen
    # into this batch's Trend Hunter file, or failing that the name of the
    # `pipeline/<channel>/<batch-id>` directory - so it is resolved to the
    # current id here, where it is read, before any channel config is opened.
    channel = resolve_channel(doc.get("channel") or batch.resolve().parent.name)
    # CF-0302: read from the same config, at the same moment, for the same
    # reason - what this channel takes from YouTube.
    ceiling = duration_ceiling(channel)
    # CF-0663: the licence lists and the origins' credits, read once.
    origins = footage_origins(channel)
    measurements = []
    depths = []

    # CF-0090: orphan partials from earlier failed fetches go before the
    # first download, and the SWEEP line lands in this run's log. Not in
    # ingest() - the tests call that against the real cache.
    fetch_footage.sweep_partials(log=print)

    # CF-0332: said once, so a run's log tells which walk it was.
    workers = index_workers(args.index_workers)
    vision = vision_plan(workers, args.vision_per_worker)       # CF-0843
    sockets = vision["sockets"]
    print(f"  indexing {workers} source(s) at a time (CF-0332"
          + (", Vision worker per slot" if sockets else "") + ")")
    print(f"  Vision: {vision[VISION_MODE_FIELD]} "
          f"({vision[VISION_MODE_REASON_FIELD]})")
    if vision[VISION_MODE_REASON_FIELD].startswith("low_memory"):
        print(f"WARNING Vision per slot is off for this pass: "
              f"{vision[VISION_MODE_REASON_FIELD]} - the shared worker instead "
              f"of swapping (CF-0843)")

    # CF-0325: what the pool already holds for each topic, checked to be the
    # topic's work, counted before the walk. Never a refusal, never a download.
    vetted = {} if args.no_pool else pool_sources.vet(topics, CACHE, root=FACTORY_ROOT,
                                                         channel=channel)

    # CF-0715: the command center's view of the walk, written as it goes.
    progress = progress_tracker(batch, wanted=args.sources_wanted,
                                max_attempts=args.max_per_topic,
                                floor=args.pool_depth_floor)
    fetched, aliases, skipped, failed, by_topic = ingest(
        topics, verdict, batch.name, args.max_per_topic,
        wanted=args.sources_wanted,
        ceiling=ceiling, measurements=measurements,
        depth_floor=args.pool_depth_floor, depths=depths,
        workers=workers, vision_sockets=sockets,
        pooled=pool_sources.pooled_paths(vetted),
        pool_barred=pool_sources.barred_ids(vetted),
        origins=origins,                                    # CF-0663
        tracker=progress)                                   # CF-0715
    pool_sources.stamp_fetched(fetched, vetted)             # CF-0817

    report = build_report(batch, fetched, aliases, skipped, failed, by_topic,
                          wanted=args.sources_wanted,
                          max_attempts=args.max_per_topic,
                          ceiling=ceiling, measurements=measurements,
                          depths=depths, depth_floor=args.pool_depth_floor)
    report[pool_sources.BLOCK_KEY] = pool_sources.report_block(
        vetted, by_topic, aliases)
    stamp_vision_mode(report, vision, workers)              # CF-0843
    # CF-0362: in the channel's `measure` mode a one-source topic stays, with
    # a warning - settled before the reserve, which must not refill a slot
    # that is not free.
    gate_mode, gate_from = floor_mode(channel, flag=args.no_second_source)
    mark_own_graphic(report, topics, origins)               # CF-0689
    apply_floor_mode(report, gate_mode, wanted=args.sources_wanted,
                     whence=gate_from)
    # CF-0306: a topic this pass refused leaves a slot compliance already paid
    # for, and the reserve is what fills it. Inside the same run, before the
    # report is written: the descriptions the operator is about to write must
    # cover the substitute's sources too.
    if not args.no_reserve:
        substitute_reserve(report, topics, verdict,
                           wanted=args.sources_wanted,
                           max_attempts=args.max_per_topic,
                           depth_floor=args.pool_depth_floor,
                           ceiling=ceiling,
                           floor=gate_mode,
                           origins=origins)                 # CF-0663
        apply_floor_mode(report, gate_mode, wanted=args.sources_wanted,
                         whence=gate_from)
    dest = write_report(batch, report)
    if progress is not None:
        progress.settle(report)                             # CF-0715
    if aliases:
        write_aliases(batch, aliases)

    # CF-0306: the report is the truth from here on, not the return values of
    # the first walk - a substitution adds sources, aliases, losses and
    # refusals of its own, and every line below has to count them.
    fetched = report["fetched"]
    aliases = report["aliases"]
    failed = report["failed"]
    skipped = report["skipped_topics"]
    from_pool = [f for f in fetched if f.get(pool_sources.FETCHED_MARK)]
    # CF-0265: the codes decided by reading compliance are not this stage's
    # own refusals, so they stay out of the floor line below - but they are
    # printed on their own, because a topic silently not fetched is the loss
    # both CF-0232 and this task exist to prevent.
    refused = [s for s in skipped if s["reason_code"] not in PRE_FETCH_CODES]
    gated = [s for s in skipped
             if s["reason_code"] in (RESERVE_SKIP_CODE, NOT_SCREENED_CODE)]
    print(f"{len(fetched)} fetched, {len(aliases)} aliased as re-uploads, "
          f"{len(skipped)} topics skipped, {len(failed)} failed -> {dest}")
    # CF-0419: a topic the floor kept is said here too, not only in 01b - the
    # operator carries it into `stage-done --note`, and a warning nobody reads
    # is the silence CF-0232 exists against.
    floor_warned = [w for w in report.get(WARNINGS_FIELD) or []
                    if w.get("stage") == STAGE_NAME
                    and w.get("warning_code") == TOPIC_REFUSAL_CODE]
    if floor_warned:
        print(FLOOR_WARNINGS_LINE.format(
            n=len(floor_warned), rule=FLOOR_RULE, mode=gate_mode,
            whence=gate_from,
            topics=", ".join(f"{w['topic_id']} "
                             f"({(w.get('numbers') or {}).get('sources')} source)"
                             for w in floor_warned)))
    print_own_graphic_kept(report)                          # CF-0689
    pool_block = report.get(pool_sources.BLOCK_KEY) or {}
    if pool_block.get("topics"):
        # CF-0325: what the pool gave, and what the check turned away - the
        # second half is the one an operator must be able to see.
        print(f"  {len(from_pool)} source(s) taken from the pool before any "
              f"download (CF-0325), {pool_block.get('refused', 0)} pool "
              f"match(es) not counted: "
              + ", ".join(f"{tid} {b['counted']}/{b['matched']}"
                          for tid, b in pool_block["topics"].items()))
        if pool_block.get(pool_sources.HOST_SHOW) or pool_block.get(
                pool_sources.HOST_SHOW_UNKNOWN):
            # CF-0817: the host shows the pool held, turned away, and the
            # counted sources nobody could call one either way.
            print(f"  {pool_block.get(pool_sources.HOST_SHOW, 0)} pool source(s) "
                  f"refused as somebody else's host show (CF-0817), "
                  f"{pool_block.get(pool_sources.HOST_SHOW_UNKNOWN, 0)} counted "
                  f"with no title or uploader to judge ({pool_sources.HOST_SHOW_UNKNOWN})")
    # CF-0281: the ids that came down and have no index. Said on stdout, and
    # the media is in the
    # cache, nothing about this is the source's, and the stage has already taken
    # the next candidate in each one's place.
    broken = report["index_failures"]
    if broken:
        print(INDEX_FAILURES_LINE.format(n=len(broken))
              + ", ".join(f"{b['video_id']} ({b['topic_id']}"
                          + (f" -> {', '.join(b['replaced_by'])}" if b["replaced_by"]
                             else ", not replaced") + ")"
                          for b in broken))
    # CF-0316: and, separately again, the ones the factory took down itself.
    # Not mixed into the line above either: an index that failed is one thing,
    # an index that went quiet for half an hour is an авария (CF-0319) and a
    # task for the triage - and no attempt of the topic was spent on it.
    killed = timeout_summary(broken)
    if killed:
        print(killed)
    # CF-0302: what the duration ceiling took off the list before a byte moved,
    # and - separately - the candidates whose length nobody could measure, so
    # that "the ceiling refused nothing" and "the ceiling could not look" are
    # two different lines on the operator's screen.
    over = report["duration_ceiling"]["refused"]
    if over:
        print(TOO_LONG_SUMMARY.format(n=len(over))
              + ", ".join(f"{o['video_id']} ({o['topic_id']}, "
                          f"{int(o['duration_seconds'])}s > {int(o['ceiling_seconds'])}s "
                          f"for '{o['nature']}')" for o in over))
    blind = report["duration_ceiling"]["unmeasured"]
    if blind:
        print(f"  {len(blind)} candidate(s) had no measurable length and were "
              f"fetched without a ceiling (CF-0302): "
              + ", ".join(o["video_id"] for o in blind))
    # CF-0304: the topics that hold their sources and a thin pool anyway, with
    # nothing left to try. Not a refusal and deliberately not in the "refused"
    # line below - it is the warning that the writer is likely to refuse them
    # for the pool rather than for the writing, and it is the operator's cue to
    # look at `pool_depth.thin[]` before the batch spends a model call on them.
    thin = report["pool_depth"]["thin"]
    if thin:
        by_id = {r["topic_id"]: r for r in report["pool_depth"]["topics"]}
        print(f"  {len(thin)} topic(s) kept a pool under the "
              f"{args.pool_depth_floor}-usable-shot depth floor and are NOT "
              f"refused here (CF-0304): "
              + ", ".join(f"{t} ({by_id[t]['usable_shots']}/{by_id[t]['shots']}"
                          f" shots, {by_id[t]['exhausted']})" for t in thin))
    unmeasured = report["pool_depth"]["unmeasured"]
    if unmeasured:
        print(f"  {len(unmeasured)} topic(s) had no measurable pool depth and "
              f"stopped at the source floor (CF-0304): " + ", ".join(unmeasured))
    # CF-0306: who took whose slot, and what is left in the reserve. Printed
    # before the refusal line below, because a refused topic whose slot was
    # refilled is a different piece of news from one whose slot stayed empty.
    subs = report.get(SUBSTITUTION_KEY) or {}
    if subs.get("substitutions"):
        print(f"  {len(subs['substitutions'])} slot(s) refilled from the "
              f"compliance reserve (CF-0306): "
              + ", ".join(f"{s['topic_id']} for {s['replaced']} "
                          f"({s['replaced_reason_code']}, {s['outcome']})"
                          for s in subs["substitutions"])
              + f"; {len(subs.get('remaining') or [])} reserve topic(s) left")
    if subs.get("unmatched"):
        print(f"  {len(subs['unmatched'])} slot(s) could not be refilled - the "
              f"reserve is used up ({RESERVE_EXHAUSTED_CODE}): "
              + ", ".join(u["replaced"] for u in subs["unmatched"]))
    if gated:
        print(f"  {len(gated)} topic(s) not fetched on compliance's word "
              f"(CF-0265), no download spent on them: "
              + ", ".join(f"{s['topic_id']} ({s['reason_code']})" for s in gated))
    if refused:
        # The one thing the invoking agent has to carry into its report: these
        # topics do not go to Content Researcher (CF-0129).
        print(f"  {len(refused)} topic(s) refused below the {args.sources_wanted}"
              f"-source floor and must not be written: "
              + ", ".join(f"{s['topic_id']} ({s['reason_code']})" for s in refused))
    for s in skipped:
        print(f"  skipped {s['topic_id']}: {s['reason']}", file=sys.stderr)
    for f in failed:
        print(f"  failed {f['video_id']}: {f['error']}", file=sys.stderr)


@runlog.script("footage-indexer", "ingest", name="ingest_batch.py")
def cli():
    """CF-0107: start/done|failed around main(); fetch_footage.py and
    index_footage.py run as subprocesses and chain under this event by
    themselves (RUNLOG_BATCH/RUNLOG_PARENT), one nested event per source."""
    sys.exit(main())


if __name__ == "__main__":
    cli()

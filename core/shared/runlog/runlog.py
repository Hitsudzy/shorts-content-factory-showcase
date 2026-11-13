#!/usr/bin/env python3
"""CF-0107: event accounting for one pipeline run - RUN_EVENTS.jsonl.

One run (a batch under pipeline/<channel>/<batch-id>/) leaves one append-only
file, RUN_EVENTS.jsonl, one JSON object per line, from which the start and
finish of every script and every attempt, the time of every external binary,
the stage boundaries and the run header can be recovered. RUN_LOG.txt is
*derived* from it (`runlog render`), no longer written by hand.

Stdlib only, on purpose: every agent lives in its own venv with its own
requirements.txt and nothing third-party may be added there. This is the one
copy for the whole factory; agents import it by path:

    import os, sys
    from pathlib import Path

    def _factory_root():
        env = os.environ.get("FACTORY_ROOT")
        if env:
            return Path(env).expanduser().resolve()
        for p in Path(__file__).resolve().parents:       # agents/<name>/scripts/x.py -> root
            if (p / "shared" / "runlog" / "runlog.py").is_file():
                return p
        raise RuntimeError("factory root not found: set FACTORY_ROOT")

    sys.path.insert(0, str(_factory_root() / "shared" / "runlog"))
    import runlog

(`from shared.runlog import runlog` works too when the root itself is on
sys.path - the root's own tests do that.) The root lookup is the same
convention shared/inserts/underlay.py already uses: FACTORY_ROOT wins, the
ancestor walk is the fallback.

Event shape (every key is always present; unknown values are null):

    ts          ISO 8601, UTC only, always with the Z suffix ("2026-09-07T10:00:05.123Z")
    machine     stable machine id, "<short-hostname>-<8 hex>" (see machine_id())
    kind        "script" | "child" | "marker" | "sample" | "limits" | "limit-hit" | "gap"
                | "usage" (sample..gap are the CF-0108 accounting layer: sampler.py,
                limits.py, limit_hook.py, gaps.py beside this file; usage is CF-0109,
                usage.py - tokens per stage x video x model x role from transcripts)
    stage       pipeline stage: trend-hunter, compliance-checker, footage-indexer,
                content-researcher, video-editor, frame-judge, publisher (markers
                may carry a sub-stage name such as footage-indexer-descriptions
                verbatim)
    video       slug of the video the event belongs to, or null
    step        script step (resolve, plan, tts, align, soundtrack, render, qc,
                metadata; fetch, index, descriptions, sieve; plan-check - the
                content-researcher's step 6b, one `child` event per script with
                tool plan_check.py, CF-0411 ...) or null
    attempt     attempt number passed in by the caller (attempts.py owns the
                numbering; this module never invents one), or null
    status      script/child: "start" | "done" | "failed"
                marker:       "batch-start" | "stage-start" | "stage-done" | "batch-done"
    params      short dict of arguments (strings are cut to 120 chars, at most
                24 keys), or null
    duration_s  seconds from the matching start, on done/failed; null on start
    pid         process id of the writer
    id          12 hex chars, unique per script/child/marker; the start and the
                done/failed event of one script share the id
    parent      id of the enclosing script event for a child (and for a script
                launched from another instrumented script), else null

    plus, when present:
    name        script name (basename of the entry file) on kind=script
    tool        ffmpeg | kokoro | whisper.cpp | yt-dlp | vision | chrome | ...   on kind=child
    argv        truncated argv of the child                                       on kind=child
    rc          return code                                                        on kind=child done/failed
    error       "ExcClass: first line of the message"                             on status=failed
    note        free text                                                          on kind=marker
    header      run header (git, version, models, counts, machine facts)          on marker batch-start

Where the batch directory comes from, in order (the first hit wins):

    1. an explicit `batch_dir=` argument;
    2. the RUNLOG_BATCH environment variable (the marker CLI and `run()` export
       it to children, so a script started under an instrumented parent
       inherits it);
    3. the nearest ancestor of any path-looking element of sys.argv (or of the
       `paths=` argument) that contains RUN_EVENTS.jsonl or RUN_LOG.txt, or
       whose parents look like pipeline/<channel>/<batch-id>;
    4. the same walk from the current working directory.

CF-0251, where the events may go - the lookup above answers *which* batch,
this answers whether it may be written:

    * the walk (3, 4) is a guess from a path on the command line, so it is
      taken only for an *open* journal: one that exists, has a `batch-start`,
      and whose last marker is not `batch-done`. A closed batch, or a directory
      that merely looks like `pipeline/<channel>/<batch-id>` with no journal of
      its own, is not written by it (one warning) - that is how 86 000 test
      lines landed in finished batches 2026-09-07..10-02;
    * an explicit batch (1, 2) that is closed gets its script/child/sample
      events in AFTER_CLOSE_FILE beside the journal, never in the journal;
      accounting written *about* a finished run (usage, gap, limits) and
      markers (a `stage-start` reopens the batch on purpose) go in as before;
    * a process descending from a test file (`test_*.py`, `run_tests.py`,
      pytest) writes nothing outside the temp directories, whatever the route:
      a test run by hand cannot reach the real `pipeline/`.

If nothing is found, `emit()` prints one warning to stderr and does nothing:
accounting must never break a run. The marker CLI, which is the operator's
explicit act, errors out instead (exit 2).

Nothing in this module raises into the caller because of accounting: a full
disk, an unwritable directory, a broken header probe - all end as one line on
stderr and the run goes on.
"""
import contextlib
import functools
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "EVENTS_FILE", "RUNLOG_FILE", "BATCH_ENV", "PARENT_ENV", "STAGE_ENV",
    "KIND_SCRIPT", "KIND_CHILD", "KIND_MARKER", "MARKERS",
    "AGENT_NAMES", "MAINTENANCE_STAGES", "S_POOL_MAINTENANCE",
    "S_FRAME_JUDGE", "S_SUPPLEMENT", "NON_AGENT_STAGES",
    "MARKUP", "MARKUP_LEGACY", "markup_of",
    "events_path", "runlog_path", "machine_id", "now_z", "find_batch_dir",
    "emit", "run", "script", "child", "run_child", "annotate", "current_id",
    "marker", "header", "read_events", "render_runlog", "write_runlog",
    "main", "RunlogError", "sibling", "active_batch_file", "ACTIVE_BATCH_FILE",
    "AFTER_CLOSE_FILE", "journal_state", "write_path", "under_test",
    "RERUN_KEY", "RERUN_MODES", "rerun_mode", "KIND_QUESTION", "question",
    "resolve_batch_path", "normalize_batch_env",
]

EVENTS_FILE = "RUN_EVENTS.jsonl"
AFTER_CLOSE_FILE = "RUN_EVENTS.after-close.jsonl"   # CF-0251: activity explicitly sent to a closed batch
UNDER_TEST_ENV = "RUNLOG_UNDER_TEST"        # CF-0251: "1"/"0", the ancestry verdict handed to children
RUNLOG_FILE = "RUN_LOG.txt"
BATCH_ENV = "RUNLOG_BATCH"
PARENT_ENV = "RUNLOG_PARENT"
STAGE_ENV = "RUNLOG_STAGE"                  # CF-0173: relabels the script/child events under it
FACTORY_ROOT_ENV = "FACTORY_ROOT"
STATE_DIR_ENV = "RUNLOG_STATE_DIR"          # where machine-id lives; default ~/.shorts-content-factory
ACTIVE_BATCH_FILE = "active-batch"          # CF-0108: <state dir>/active-batch names the running batch

KIND_SCRIPT = "script"
KIND_CHILD = "child"
KIND_MARKER = "marker"
# CF-0494: the orchestrator asked the user in the middle of a run. Not a
# marker (it opens and closes nothing) and not activity (gaps.ACTIVITY_KINDS):
# a fact the no-waiting register reads, so the wait it begins is a named point
# (`orchestrator_question_mid_run`) and not `unclassified_wait`.
KIND_QUESTION = "question"

M_BATCH_START = "batch-start"
M_STAGE_START = "stage-start"
M_STAGE_DONE = "stage-done"
M_BATCH_DONE = "batch-done"
MARKERS = (M_BATCH_START, M_STAGE_START, M_STAGE_DONE, M_BATCH_DONE)

ST_START = "start"
ST_DONE = "done"
ST_FAILED = "failed"

AGENT_NAMES = ("trend-hunter", "compliance-checker", "footage-indexer",
               "content-researcher", "video-editor")

# CF-0173: stages that are not an agent's turn in the batch. `pool-maintenance`
# is pool-wide work that does not depend on the topics of this batch - the
# freshness check of the caption cache (CF-0151) and the remeasures that clear
# it - run before the first agent stage. It carries its own markers so that the
# stretch lands in the per-stage sections under its own name instead of the
# `between` bucket, and so that the day it leaves the critical path (CF-0099) is
# visible as a row going to zero rather than as a row disappearing.
S_POOL_MAINTENANCE = "pool-maintenance"
MAINTENANCE_STAGES = (S_POOL_MAINTENANCE,)

# CF-0298, 2026-09-20: the frame judge - the stage that reads the finished
# frames against the narration (DoD item 3) and is a gate on `ready`. It is a
# stage of the batch and not an agent: there is no `agents/frame-judge/`, the
# project's rule is zero new agent repositories, and its operator runs from the
# root's own skill (`.claude/skills/frame-judge/SKILL.md`). It is named here for
# the reason `pool-maintenance` is - the two scripts that run inside it
# (`agents/video-editor/scripts/frame_judge_pack.py`, which is the Editor's code
# run under `RUNLOG_STAGE=frame-judge`, and the root's
# `scripts/frame_judge_gate.py`) must land in the per-stage sections as
# themselves instead of being folded into `video-editor`, whose turn is over.
S_FRAME_JUDGE = "frame-judge"

# Every stage of a batch that is not one agent's turn. A reader asking "is this
# stage name a typo" has one place to look, and a stage missing from here is a
# stretch of the run that lands in `between`.
# CF-0345, 2026-09-23: the thin-pool supplement - after the Content
# Researcher, the hunter, the indexer, the descriptions, the sieve and the pool
# gates again, over the topics whose pool the gates found thin
# (`shared/runlog/supplement.py`, `scripts/thin_pool_supplement.py`). Its
# scripts are three agents' code run under `RUNLOG_STAGE=thin-pool-supplement`.
S_SUPPLEMENT = "thin-pool-supplement"

NON_AGENT_STAGES = MAINTENANCE_STAGES + (S_FRAME_JUDGE, S_SUPPLEMENT)

# CF-0173: the generation of the stage markup a run was recorded under. Runs of
# generation 1 have no marker around the pre-stage block, so their per-stage
# sections put that stretch in `between`; a generation-1 row and a generation-2
# row are not comparable stage by stage. Bump this whenever the *vocabulary* of
# the markers changes - not when a stage is renamed inside the same vocabulary.
MARKUP = 2
MARKUP_LEGACY = 1                           # no header stamp = recorded before CF-0173


def markup_of(header):
    """The markup generation of a run, from its `batch-start` header. A header
    that carries no stamp was written before CF-0173, so it is generation 1."""
    if not isinstance(header, dict):
        return MARKUP_LEGACY
    try:
        return int(header.get("markup") or MARKUP_LEGACY)
    except (TypeError, ValueError):
        return MARKUP_LEGACY

GENERATED_BANNER = ("# RUN_LOG.txt - generated by `runlog render` from RUN_EVENTS.jsonl "
                    "(CF-0107). All times UTC. Do not edit by hand.")

PARAM_STR_MAX = 120
PARAM_KEYS_MAX = 24
ARGV_MAX_ITEMS = 24
ARGV_ITEM_MAX = 160

_EVENT_KEYS = ("ts", "machine", "kind", "stage", "video", "step", "attempt",
               "status", "params", "duration_s", "pid", "id", "parent")

_local = threading.local()
_machine_lock = threading.Lock()
_machine_cache = {}


class RunlogError(Exception):
    """Raised by the marker CLI only (exit 2); never by emit/run/child."""


# --------------------------------------------------------------------------
# time, ids, machine
# --------------------------------------------------------------------------

def now_z(t=None):
    """ISO 8601 in UTC with millisecond precision and the Z suffix, never an offset."""
    dt = datetime.fromtimestamp(time.time() if t is None else t, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_z(ts):
    """Inverse of now_z (also accepts second precision). Returns a POSIX float."""
    ts = ts.rstrip("Z")
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in ts else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc).timestamp()


def new_id():
    return uuid.uuid4().hex[:12]


def _state_dir():
    override = os.environ.get(STATE_DIR_ENV)
    return Path(override).expanduser() if override else Path.home() / ".shorts-content-factory"


def machine_id():
    """Stable id of this machine: short hostname + 8 hex of sha1(hostname, first-run uuid).

    The uuid is minted once and kept in ~/.shorts-content-factory/machine-id
    (RUNLOG_STATE_DIR overrides the directory), so two rented machines with the
    same hostname still get different ids and one machine keeps its id across
    reboots and renames of the batch. Falls back to hostname-only when the
    state dir cannot be written.
    """
    with _machine_lock:
        if "id" in _machine_cache:
            return _machine_cache["id"]
        host = socket.gethostname().split(".")[0] or "host"
        short = re.sub(r"[^A-Za-z0-9-]+", "-", host).strip("-")[:24] or "host"
        path = _state_dir() / "machine-id"
        salt = None
        try:
            if path.is_file():
                salt = path.read_text().strip() or None
            if not salt:
                salt = uuid.uuid4().hex
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(salt + "\n")
                os.replace(tmp, path)
        except OSError as e:
            _warn(f"machine-id not persisted ({e}); using hostname only")
            salt = ""
        digest = hashlib.sha1(f"{host}\n{salt}".encode()).hexdigest()[:8]
        mid = f"{short}-{digest}"
        _machine_cache["id"] = mid
        return mid


def _warn(msg):
    try:
        sys.stderr.write(f"[runlog] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


# --------------------------------------------------------------------------
# where the batch is
# --------------------------------------------------------------------------

def events_path(batch_dir):
    return Path(batch_dir) / EVENTS_FILE


def runlog_path(batch_dir):
    return Path(batch_dir) / RUNLOG_FILE


def _looks_like_batch(d):
    d = Path(d)
    if (d / EVENTS_FILE).exists() or (d / RUNLOG_FILE).exists():
        return True
    # pipeline/<channel>/<batch-id>: the batch is two below a dir named pipeline
    try:
        return d.parent.parent.name == "pipeline" and d.is_dir()
    except (AttributeError, OSError):
        return False


def _walk_up(start):
    try:
        p = Path(start).expanduser().resolve()
    except OSError:
        return None
    if p.is_file():
        p = p.parent
    for cand in (p, *p.parents):
        if _looks_like_batch(cand):
            return cand
    return None


def resolve_batch_path(value, cwd=None):
    """CF-0541: a batch path as an absolute one. A relative path is the
    caller's, from the caller's directory - but a child the root starts with
    `cwd=agents/<agent>` inherits `RUNLOG_BATCH=pipeline/<channel>/<batch>`
    and would read it from its own directory (batch 0701Z: the supplement's
    hunter and indexer events went to `agents/trend-hunter/pipeline/...` and
    were lost). So: from `cwd` when it exists there, else from the factory
    root when it exists there, else from `cwd` as before."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    here = (Path(cwd) if cwd else Path.cwd()) / path
    if here.exists():
        return here.resolve()
    try:
        rooted = factory_root() / path
        if rooted.exists():
            return rooted.resolve()
    except (OSError, RuntimeError, ValueError):
        pass
    return here.resolve()


def normalize_batch_env(environ=None, cwd=None):
    """CF-0541: `RUNLOG_BATCH` made absolute in `environ` (os.environ by
    default) before any child is started, so every child - whatever its
    `cwd` - names the same batch. Called once at import: every root entry
    point that starts agents (the marker CLI, the supplement step, ...)
    imports this library first. Returns the value it left there."""
    environ = os.environ if environ is None else environ
    value = environ.get(BATCH_ENV)
    if not value:
        return value
    try:
        if not Path(value).expanduser().is_absolute():
            environ[BATCH_ENV] = str(resolve_batch_path(value, cwd=cwd))
    except (OSError, RuntimeError, ValueError):
        pass
    return environ.get(BATCH_ENV)


def find_batch_dir(batch_dir=None, paths=None, use_cwd=True):
    """The batch directory per the lookup order in the module docstring, or None."""
    if batch_dir:
        return resolve_batch_path(batch_dir)
    env = os.environ.get(BATCH_ENV)
    if env:
        return resolve_batch_path(env)
    candidates = list(paths or [])
    if paths is None:
        candidates = [a for a in sys.argv[1:] if not a.startswith("-")]
    for c in candidates:
        try:
            s = str(c)
            if "/" not in s and not Path(s).exists():
                continue
            hit = _walk_up(s)
        except (OSError, TypeError, ValueError):
            hit = None
        if hit:
            return hit
    if use_cwd:
        try:
            return _walk_up(os.getcwd())
        except OSError:
            return None
    return None


_ACTIVITY_KINDS = (KIND_SCRIPT, KIND_CHILD, "sample")
_journal_cache = {}                         # path -> [offset, started, last marker status]
_journal_lock = threading.Lock()
_warned_once = set()


def _warn_once(key, msg):
    if key not in _warned_once:
        _warned_once.add(key)
        _warn(msg)


def journal_state(batch_dir):
    """CF-0251: (started, closed) of the batch's journal, read incrementally -
    only the bytes appended since the last call of this process are scanned, so
    a hot path that writes thousands of events pays for the file once.
    `closed` means the last marker is `batch-done`; a later `stage-start`
    (a rework of a finished batch) or `batch-start` reopens it."""
    with _journal_lock:
        return _journal_state(events_path(batch_dir))


def _journal_state(path):
    key = str(path)
    st = _journal_cache.get(key)
    try:
        size = path.stat().st_size
    except OSError:
        _journal_cache.pop(key, None)
        return False, False
    if st is None or size < st[0]:
        st = _journal_cache[key] = [0, False, None]
    if size > st[0]:
        try:
            with open(path, "rb") as fh:
                fh.seek(st[0])
                chunk = fh.read(size - st[0])
        except OSError:
            return st[1], st[2] == M_BATCH_DONE
        cut = chunk.rfind(b"\n")
        if cut >= 0:
            st[0] += cut + 1
            pos = 0
            body = chunk[:cut + 1]
            while True:
                i = body.find(b'"marker"', pos)
                if i < 0:
                    break
                a = body.rfind(b"\n", 0, i) + 1
                b = body.find(b"\n", i)
                pos = b + 1
                try:
                    e = json.loads(body[a:b])
                except ValueError:
                    continue
                if not isinstance(e, dict) or e.get("kind") != KIND_MARKER:
                    continue
                status = e.get("status")
                if status == M_BATCH_START:
                    st[1] = True
                if status in MARKERS:
                    st[2] = status
    return st[1], st[2] == M_BATCH_DONE


_TEST_RE = re.compile(r"(?:^|[\s/])(?:test_[\w.-]*\.py|run_tests\.py|pytest|py\.test)(?:\s|$)")
_under_test = None


def _ancestry():
    """Command lines of this process and its ancestors, nearest first."""
    out = [" ".join(sys.argv or [])]
    try:
        cp = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True,
                            text=True, timeout=5)
        table = {}
        for line in cp.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                table[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
        pid = os.getppid()
        for _ in range(16):
            if pid <= 1 or pid not in table:
                break
            ppid, cmd = table[pid]
            out.append(cmd)
            pid = ppid
    except Exception:
        pass
    return out


def under_test():
    """CF-0251: True when this process is a test file or descends from one
    (`test_*.py`, `run_tests.py`, pytest). Decided once per process tree: the
    verdict is exported in RUNLOG_UNDER_TEST, so a child does not walk the
    process table again."""
    global _under_test
    if _under_test is None:
        env = os.environ.get(UNDER_TEST_ENV)
        if env in ("0", "1"):
            _under_test = env == "1"
        else:
            _under_test = any(_TEST_RE.search(c or "") for c in _ancestry())
            try:
                os.environ[UNDER_TEST_ENV] = "1" if _under_test else "0"
            except Exception:
                pass
    return _under_test


TEMP_ROOTS_ENV = "RUNLOG_TEMP_ROOTS"         # CF-0251: os.pathsep list replacing SYSTEM_TEMP_ROOTS (tests)
SYSTEM_TEMP_ROOTS = ("/tmp", "/var/folders", "/var/tmp")


def _temp_roots():
    """Where a test process may write: the system temp areas and $TMPDIR. The
    runners hand every file a narrower TMPDIR of its own while the suite's
    temp batch sits in the outer one, so the whole system area counts."""
    env = os.environ.get(TEMP_ROOTS_ENV)
    cands = env.split(os.pathsep) if env else (tempfile.gettempdir(), *SYSTEM_TEMP_ROOTS)
    roots = []
    for r in cands:
        if not r:
            continue
        try:
            roots.append(Path(r).resolve())
        except OSError:
            pass
    return roots


def _in_temp(path):
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    return any(p == r or r in p.parents for r in _temp_roots())


def write_path(batch_dir, kind):
    """CF-0251: the file an event of `kind` for `batch_dir` goes to, or None
    when it may not be written at all (see the module docstring)."""
    if batch_dir is None:
        return None
    bdir = Path(batch_dir)
    if not _in_temp(bdir) and under_test():
        _warn_once(("test", str(bdir)),
                   f"event not written: a test process may not write into {bdir} "
                   f"(outside the temp dirs, CF-0251); set {BATCH_ENV} to a temp batch")
        return None
    if kind in _ACTIVITY_KINDS and journal_state(bdir)[1]:
        _warn_once(("closed", str(bdir)),
                   f"{bdir} is closed (batch-done): its {kind} events go to "
                   f"{AFTER_CLOSE_FILE}, not to the journal (CF-0251)")
        return bdir / AFTER_CLOSE_FILE
    return bdir / EVENTS_FILE


def _find_for_write(batch_dir=None, paths=None, use_cwd=True):
    """find_batch_dir() for a writer: an explicit batch (argument, RUNLOG_BATCH)
    as is, a walked-to one only when its journal is open (CF-0251)."""
    if batch_dir or os.environ.get(BATCH_ENV):
        return find_batch_dir(batch_dir, paths=paths, use_cwd=use_cwd)
    hit = find_batch_dir(None, paths=paths, use_cwd=use_cwd)
    if hit is None:
        return None
    started, closed = journal_state(hit)
    if started and not closed:
        return hit
    why = "closed (batch-done)" if closed else "has no open journal (no batch-start)"
    _warn_once(("walk", str(hit)),
               f"not writing into {hit}: found from a path on the command line, and it {why}; "
               f"reopen it with a marker or name the batch with --batch/{BATCH_ENV} (CF-0251)")
    return None


# --------------------------------------------------------------------------
# writing one event
# --------------------------------------------------------------------------

def _short(v):
    if isinstance(v, str):
        return v if len(v) <= PARAM_STR_MAX else v[:PARAM_STR_MAX - 1] + "…"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if isinstance(v, Path):
        return _short(str(v))
    if isinstance(v, dict):
        return {str(k): _short(x) for k, x in list(v.items())[:PARAM_KEYS_MAX]}
    if isinstance(v, (list, tuple, set)):
        return [_short(x) for x in list(v)[:PARAM_KEYS_MAX]]
    return _short(repr(v))


def _short_params(params):
    if params is None:
        return None
    if not isinstance(params, dict):
        return {"value": _short(params)}
    return _short(params)


def _short_argv(argv):
    if argv is None:
        return None
    if isinstance(argv, (str, bytes)):
        argv = [argv.decode(errors="replace") if isinstance(argv, bytes) else argv]
    out = []
    for a in list(argv)[:ARGV_MAX_ITEMS]:
        s = a.decode(errors="replace") if isinstance(a, bytes) else str(a)
        out.append(s if len(s) <= ARGV_ITEM_MAX else s[:ARGV_ITEM_MAX - 1] + "…")
    if len(argv) > ARGV_MAX_ITEMS:
        out.append(f"…(+{len(argv) - ARGV_MAX_ITEMS})")
    return out


def _round(x):
    return None if x is None else round(float(x), 3)


def _stage_override(kind, stage):
    """CF-0173: `RUNLOG_STAGE` renames the stage of every script and child event
    written under it, markers excepted (a marker's stage is what the operator
    typed). The same script belongs to different stages depending on who ran it:
    `remeasure_captions.py` is footage-indexer's code, and inside that stage it
    labels itself so, but when the operator runs it over the whole pool before
    the run it is `pool-maintenance` - the events have to say which, because the
    per-stage sections read the label and the marker window together."""
    if kind == KIND_MARKER:
        return stage
    return (os.environ.get(STAGE_ENV) or "").strip() or stage


def emit(batch_dir, kind, stage, step=None, video=None, attempt=None, status=None,
         params=None, duration_s=None, parent=None, event_id=None, **extra):
    """Append one event line to <batch_dir>/RUN_EVENTS.jsonl and return the event dict.

    Atomic append: the file is opened O_APPEND and the whole line goes out in a
    single write(), so concurrent writers (two scripts, a script and the
    marker CLI) interleave whole lines, never bytes. Never raises: a missing
    batch dir, a full disk or an unencodable value become one stderr line and
    the returned dict (or None when there was nowhere to write).
    """
    try:
        target = _find_for_write() if batch_dir is None else Path(batch_dir)
        stage = _stage_override(kind, stage)
        ev = {
            "ts": now_z(),
            "machine": machine_id(),
            "kind": kind,
            "stage": stage,
            "video": video,
            "step": step,
            "attempt": attempt,
            "status": status,
            "params": _short_params(params),
            "duration_s": _round(duration_s),
            "pid": os.getpid(),
            "id": event_id or new_id(),
            "parent": parent,
        }
        for k, v in extra.items():
            if v is not None:
                ev[k] = v
        if target is None:
            _warn(f"no batch dir for {kind}/{stage}/{step or '-'} event; set {BATCH_ENV}")
            return ev
        out = write_path(target, kind)
        if out is None:
            return ev
        line = json.dumps(ev, ensure_ascii=False, default=_short) + "\n"
        data = line.encode("utf-8")
        fd = os.open(str(out),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return ev
    except Exception as e:                      # accounting never breaks a run
        _warn(f"event not written ({e.__class__.__name__}: {e})")
        return None


# --------------------------------------------------------------------------
# scripts: start / done | failed
# --------------------------------------------------------------------------

def _stack():
    st = getattr(_local, "stack", None)
    if st is None:
        st = _local.stack = []
    return st


def _child_stack():
    """CF-0160: the open child() frames of this thread, innermost last. Kept apart
    from _stack() on purpose: annotate(), current_batch_dir() and run() read the
    script stack and must keep seeing the script, not the call inside it."""
    st = getattr(_local, "children", None)
    if st is None:
        st = _local.children = []
    return st


def current_id():
    """Id of the innermost open run() in this thread, else RUNLOG_PARENT from the env, else None."""
    st = _stack()
    if st:
        return st[-1]["id"]
    return os.environ.get(PARENT_ENV) or None


def current_batch_dir():
    st = _stack()
    if st:
        return st[-1]["batch_dir"]
    return _find_for_write()


def annotate(video=None, attempt=None, **params):
    """Attach video / attempt / extra params to the innermost open run(); they
    land on its done/failed event. For scripts that learn the slug or the
    attempt number only after they started."""
    st = _stack()
    if not st:
        return
    fr = st[-1]
    if video is not None:
        fr["video"] = video
    if attempt is not None:
        fr["attempt"] = attempt
    if params:
        fr["params"] = dict(fr.get("params") or {}, **params)


def _error_text(exc):
    msg = str(exc).strip().splitlines()
    first = msg[0] if msg else ""
    return f"{exc.__class__.__name__}: {first}"[:300] if first else exc.__class__.__name__


@contextlib.contextmanager
def run(stage, step=None, video=None, attempt=None, params=None, batch_dir=None,
        name=None, paths=None, parent=None):
    """Context manager around one script (or one attempt): writes `start`, then
    `done` or `failed` with duration_s. The exception propagates unchanged.

    `attempt` is the caller's number (attempts.py owns it); `name` defaults to
    the basename of sys.argv[0]. The batch dir follows the lookup order in the
    module docstring; `paths` may name files to walk up from instead of argv.
    While the block runs, RUNLOG_BATCH and RUNLOG_PARENT are exported so that
    subprocesses (instrumented scripts or run_child) chain to this event.
    """
    bdir = _find_for_write(batch_dir, paths=paths)
    frame = {
        "id": new_id(), "batch_dir": bdir, "stage": stage, "step": step,
        "video": video, "attempt": attempt, "params": params,
        "name": name or (Path(sys.argv[0]).name if sys.argv and sys.argv[0] else None),
        "parent": parent if parent is not None else current_id(),
    }
    saved_env = {k: os.environ.get(k) for k in (BATCH_ENV, PARENT_ENV)}
    t0 = time.perf_counter()
    emit(bdir, KIND_SCRIPT, stage, step=step, video=video, attempt=attempt, status=ST_START,
         params=params, parent=frame["parent"], event_id=frame["id"], name=frame["name"])
    _stack().append(frame)
    try:
        if bdir is not None:
            os.environ[BATCH_ENV] = str(bdir)
        os.environ[PARENT_ENV] = frame["id"]
    except Exception:
        pass
    status, error = ST_DONE, None
    try:
        yield frame
    except SystemExit as e:
        if e.code not in (None, 0):
            status, error = ST_FAILED, f"SystemExit: {e.code}"
        raise
    except BaseException as e:
        status, error = ST_FAILED, _error_text(e)
        raise
    finally:
        dur = time.perf_counter() - t0
        try:
            st = _stack()
            if st and st[-1] is frame:
                st.pop()
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        except Exception:
            pass
        emit(bdir, KIND_SCRIPT, stage, step=frame["step"], video=frame["video"],
             attempt=frame["attempt"], status=status, params=frame["params"],
             duration_s=dur, parent=frame["parent"], event_id=frame["id"],
             name=frame["name"], error=error)


def _argv_params(argv):
    """A short dict of the script's own arguments for the start event: flags
    become keys ({"--slug": "x", "--attempt": "2"}), positionals go under "args"."""
    out, pos = {}, []
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1:
            if "=" in a:
                k, v = a.split("=", 1)
                out[k] = v
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                out[a] = args[i + 1]
                i += 1
            else:
                out[a] = True
        else:
            pos.append(a)
        i += 1
    if pos:
        out["args"] = pos
    return out or None


def script(stage, step=None, video_arg=None, attempt_arg=None, name=None):
    """Decorator for a script's entry point: `@runlog.script("video-editor", "render",
    video_arg="--slug", attempt_arg="--attempt")` above main(). Writes start and
    done/failed around the call; the slug and the attempt are read from
    sys.argv when the flag names are given (or from the decorated function's
    keyword arguments of the same bare name), params is the parsed argv.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            argv = sys.argv[1:]
            params = _argv_params(argv)
            video = attempt = None
            if video_arg:
                video = (params or {}).get(video_arg) or kwargs.get(video_arg.lstrip("-").replace("-", "_"))
            if attempt_arg:
                raw = (params or {}).get(attempt_arg) or kwargs.get(attempt_arg.lstrip("-").replace("-", "_"))
                try:
                    attempt = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    attempt = raw
            with run(stage, step=step, video=video, attempt=attempt, params=params, name=name):
                return fn(*args, **kwargs)
        return wrapper
    return deco


# --------------------------------------------------------------------------
# children: external binaries
# --------------------------------------------------------------------------

@contextlib.contextmanager
def child(tool, argv=None, batch_dir=None, parent=None, stage=None, step=None,
          video=None, attempt=None, params=None):
    """Context manager around one external call (ffmpeg, kokoro, whisper.cpp,
    yt-dlp, vision, chrome ...): a `child` start event, then done/failed with
    duration_s and `parent` = the innermost open child() of this thread when
    there is one (CF-0160: a wrapper like `ffmpeg full-frames` around the real
    `ffmpeg` call is the real call's parent, so the summary can count leaves
    only), else the enclosing script event (current_id()). An explicit
    `parent=` wins over both. Both events carry `depth` (0 = directly under a
    script). RUNLOG_PARENT is NOT re-exported to the child's id: a script that
    run_child() starts still chains to the script that started it (decided in
    CF-0160 - the watchdog's liveness, the script tree of section 1 and every
    frozen journal read script parents as scripts).
    Yields a dict; set `frame["rc"] = returncode` inside the block to record
    the return code (run_child does that for you). rc != 0 counts as failed.
    `frame["watchdog"] = {...}` (CF-0316) rides along into the done event as its
    own key: the operation was taken down, and this says by which ceiling.
    """
    st = _stack()
    outer = st[-1] if st else None
    kids = _child_stack()
    enclosing = kids[-1] if kids else None
    if enclosing is not None and enclosing["_level"] != len(st):
        enclosing = None                        # a run() opened inside that call is nearer
    bdir = _find_for_write(batch_dir) if batch_dir is None and outer is None else (
        Path(batch_dir) if batch_dir else outer["batch_dir"])
    if parent is not None:
        par = parent
    elif enclosing is not None:
        par = enclosing["id"]                   # CF-0160: a call inside a call nests under it
    else:
        par = current_id()
    frame = {
        "id": new_id(), "rc": None, "batch_dir": bdir,
        "stage": stage or (outer["stage"] if outer else None),
        "step": step or (outer["step"] if outer else None),
        "video": video or (outer["video"] if outer else None),
        "attempt": attempt if attempt is not None else (outer["attempt"] if outer else None),
        "parent": par,
        # CF-0160: how many open child() frames of this thread enclose this one.
        # Its presence also tells the summary that this journal records nesting
        # by `parent` (older journals do not, and get the geometric fallback).
        "depth": (enclosing["depth"] + 1) if enclosing is not None else 0,
        "_level": len(st),
    }
    argv_s = _short_argv(argv)
    t0 = time.perf_counter()
    emit(bdir, KIND_CHILD, frame["stage"], step=frame["step"], video=frame["video"],
         attempt=frame["attempt"], status=ST_START, params=params, parent=frame["parent"],
         event_id=frame["id"], tool=tool, argv=argv_s, depth=frame["depth"])
    kids.append(frame)
    status, error = ST_DONE, None
    try:
        yield frame
    except BaseException as e:
        status, error = ST_FAILED, _error_text(e)
        raise
    finally:
        dur = time.perf_counter() - t0
        try:
            if kids and kids[-1] is frame:
                kids.pop()
            elif frame in kids:                 # closed out of order (a generator kept open)
                kids.remove(frame)
        except Exception:
            pass
        rc = frame.get("rc")
        if status == ST_DONE and rc not in (None, 0):
            status = ST_FAILED
        emit(bdir, KIND_CHILD, frame["stage"], step=frame["step"], video=frame["video"],
             attempt=frame["attempt"], status=status, params=params, duration_s=dur,
             parent=frame["parent"], event_id=frame["id"], tool=tool, argv=argv_s,
             rc=rc, error=error, watchdog=frame.get("watchdog"), depth=frame["depth"])


def _tool_name(cmd):
    try:
        first = cmd if isinstance(cmd, (str, bytes)) else cmd[0]
        first = first.decode(errors="replace") if isinstance(first, bytes) else str(first)
        base = Path(first.split()[0] if isinstance(cmd, str) else first).name
        return {"whisper-cli": "whisper.cpp", "main": "whisper.cpp"}.get(base, base) or "child"
    except Exception:
        return "child"


def _drain(stream, into):
    try:
        into.append(stream.read())
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _watched(cmd, ceiling_s, bdir, **popen_kw):
    """Run `cmd` under the CF-0316 watchdog. Returns (CompletedProcess, silent_s)
    with the process' own return code, or (None, silent_s) when it was taken down.

    Popen and not subprocess.run, because the ceiling is on *silence* and has to
    be re-read while the process lives; the pipes are drained by threads, which
    is the hole CF-0132 named beside itself (a ceiling on wait() is no ceiling
    when the reader loop is what is stuck).
    """
    wd = sibling("watchdog")
    kw = dict(popen_kw)
    kw.pop("timeout", None)
    kw.pop("check", None)               # the caller's check= is honoured by run_child,
                                        # after the return code is in the event
    data = kw.pop("input", None)
    if kw.pop("capture_output", False):
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if data is not None:
        kw.setdefault("stdin", subprocess.PIPE)
    proc = subprocess.Popen(cmd, **kw)
    outs, errs, readers = [], [], []
    for stream, sink in ((proc.stdout, outs), (proc.stderr, errs)):
        if stream is not None:
            t = threading.Thread(target=_drain, args=(stream, sink), daemon=True)
            t.start()
            readers.append(t)
    if data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(data)
        except Exception:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
    live = wd.Liveness(bdir, pid=proc.pid)
    rc, silent = wd.wait(proc, ceiling_s, liveness=live)
    if rc is None:                                  # the ceiling was reached: take it down
        for step_ in (proc.terminate, proc.kill):
            try:
                step_()
                proc.wait(timeout=5)
                break
            except (subprocess.TimeoutExpired, OSError, ValueError):
                continue
    for t in readers:
        t.join(timeout=5)
    out = outs[0] if outs else None
    err = errs[0] if errs else None
    if rc is None:
        return None, silent
    return subprocess.CompletedProcess(cmd, rc, out, err), silent


def run_child(cmd, *, tool=None, batch_dir=None, parent=None, stage=None, step=None,
              video=None, attempt=None, params=None, watchdog=None, on_timeout="raise",
              source_seconds=None, **popen_kw):
    """subprocess.run(cmd, **popen_kw) inside a child() event. `tool` defaults
    to the basename of cmd[0]. Returns the CompletedProcess; `check=True`
    raises CalledProcessError after the event is written (status failed, rc).

    CF-0316: no call goes out without a ceiling. A caller that passes an explicit
    `timeout=` keeps the old wall-clock behaviour of CF-0128 (subprocess.run,
    TimeoutExpired, rc "timeout"). A caller that passes none is run under the
    watchdog instead - a ceiling on *silence*, `watchdog=` naming the class
    ("operation" by default, "shot", "download", "scan" with `source_seconds=`)
    or a number of seconds. Signs of life are the events the call's own subtree
    writes, so an honestly long operation is never taken down.

    `on_timeout="raise"` (the default) turns the kill into TimeoutExpired, as an
    unprepared caller already expected. `on_timeout="code"` is for the caller
    that can go on to the next source: it gets a CompletedProcess with
    returncode 124, `timed_out=True` and `timeout_code="<step>_timeout"` - a
    value that cannot be mistaken for a result (CF-0128's rule), while the run
    itself is never dropped (CF-0316, the user's decision Q18).
    """
    tool = tool or _tool_name(cmd)
    wd = sibling("watchdog")
    explicit = popen_kw.get("timeout") is not None
    ceiling = None if explicit else wd.ceiling_for(watchdog, step=step, tool=tool,
                                                   source_seconds=source_seconds)
    with child(tool, argv=cmd, batch_dir=batch_dir, parent=parent, stage=stage, step=step,
               video=video, attempt=attempt, params=params) as fr:
        if explicit:
            try:
                cp = subprocess.run(cmd, **popen_kw)
            except subprocess.CalledProcessError as e:
                fr["rc"] = e.returncode
                raise
            except subprocess.TimeoutExpired:
                fr["rc"] = "timeout"
                raise
            fr["rc"] = cp.returncode
            return cp
        cp, silent = _watched(cmd, ceiling, fr.get("batch_dir"), **popen_kw)
        if cp is not None:
            fr["rc"] = cp.returncode
            if popen_kw.get("check") and cp.returncode != 0:
                raise subprocess.CalledProcessError(cp.returncode, cmd, cp.stdout, cp.stderr)
            return cp
        code = wd.outcome_code(step=step or fr.get("step"), tool=tool)
        fr["rc"] = code
        fr["watchdog"] = {"code": code, "silent_s": round(silent, 3),
                          "ceiling_s": round(float(ceiling), 3),
                          "source": video or fr.get("video"), "tool": tool,
                          "killed": True}
        if on_timeout == "code":
            out = subprocess.CompletedProcess(cmd, wd.RC_TIMEOUT, None, None)
            out.timed_out = True
            out.timeout_code = code
            out.silent_s = silent
            return out
        raise subprocess.TimeoutExpired(cmd, ceiling)


# --------------------------------------------------------------------------
# markers and the run header
# --------------------------------------------------------------------------

def read_events(batch_dir):
    """All events of the batch, in file order. Broken lines are skipped with a warning."""
    path = events_path(batch_dir)
    out = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                _warn(f"{path}:{n}: unreadable event line skipped")
    return out


def _git(dir_):
    d = Path(dir_)
    if not (d / ".git").exists():
        return None
    try:
        gr = sibling("git_read")                    # CF-0717: optional locks off
        head = gr.run(["-C", str(d), "rev-parse", "HEAD"], capture_output=True,
                      text=True, timeout=5)
        if head.returncode != 0:
            return None
        dirty = gr.run(["-C", str(d), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True, timeout=10)
        return {"commit": head.stdout.strip(),
                "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}
    except (OSError, subprocess.SubprocessError):
        return None


def factory_root():
    env = os.environ.get(FACTORY_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def readme_version(root):
    """The version from the first heading of README.md ("# ... — 1.2, with 1.3 in progress" -> "1.2")."""
    try:
        for line in (Path(root) / "README.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", line)
                return m.group(1) if m else None
    except OSError:
        return None
    return None


#: CF-0716: a release tag - `v` and dotted numbers (`v2.3`, `v2.3.3`); a tag
#: with a suffix (`v2.4-rc1`, `v2.3.x-wip`) is no release.
RELEASE_TAG_RX = re.compile(r"^v(\d+(?:\.\d+)*)$")
RELEASE_BRANCH = "refs/heads/main"


def release_key(tag):
    """The version order of a release tag ("v2.3.1" -> (2, 3, 1)), None for a
    tag that is no release. "v2.3" < "v2.3.1" < "v2.10"."""
    m = RELEASE_TAG_RX.match(tag or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def release_tag(root=None):
    """CF-0716: the latest release tag on `main` of the root - "v2.3.3" - or None.

    The tags `RELEASE_TAG_RX` names that are reachable from `refs/heads/main`
    (the tip of `main` or an ancestor of it), the greatest by version order -
    not by date, not by `git describe`'s commit distance (two tags on one
    commit, or a lower tag re-made later, would answer differently). Read from
    the branch `main`, never from HEAD: the command center asks from any
    checkout (`.worktrees/release-<v>`, `cc-api`), and a version's own tags
    before its release are not the factory's release. None when the root is
    no git repo, has no `main` or no release tag on it, or git fails. A git
    read with optional locks off (CF-0717)."""
    root = Path(root) if root else factory_root()
    if not (root / ".git").exists():        # else git answers with a parent's repo
        return None
    out = _git_out(root, "for-each-ref", f"--merged={RELEASE_BRANCH}",
                   "--format=%(refname:short)", "refs/tags/", timeout=10)
    if not out:
        return None
    tags = [t for t in out.splitlines() if release_key(t) is not None]
    return max(tags, key=release_key) if tags else None


def _sh(cmd, timeout=5):
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return cp.stdout.strip() if cp.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _gpu():
    if sys.platform == "darwin":
        cache = _state_dir() / "gpu.json"
        try:
            if cache.is_file():
                return json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
        raw = _sh(["system_profiler", "SPDisplaysDataType", "-json"], timeout=20)
        names = []
        if raw:
            try:
                for g in json.loads(raw).get("SPDisplaysDataType", []):
                    nm = g.get("sppci_model") or g.get("_name")
                    cores = g.get("sppci_cores")
                    names.append(f"{nm} ({cores} cores)" if nm and cores else nm)
            except ValueError:
                pass
        gpu = ", ".join(n for n in names if n) or None
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(gpu))
        except OSError:
            pass
        return gpu
    out = _sh(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=5)
    return out.replace("\n", ", ") if out else None


def machine_facts():
    facts = {"platform": platform.platform(), "arch": platform.machine(),
             "os": None, "cpu": None, "cpu_count": os.cpu_count(), "ram_gb": None, "gpu": None,
             "python": platform.python_version()}
    try:
        if sys.platform == "darwin":
            facts["cpu"] = _sh(["sysctl", "-n", "machdep.cpu.brand_string"])
            mem = _sh(["sysctl", "-n", "hw.memsize"])
            facts["ram_gb"] = round(int(mem) / 2**30, 1) if mem else None
            ver = _sh(["sw_vers", "-productVersion"])
            facts["os"] = f"macOS {ver}" if ver else platform.platform()
        else:
            try:
                for line in Path("/proc/cpuinfo").read_text().splitlines():
                    if line.lower().startswith("model name"):
                        facts["cpu"] = line.split(":", 1)[1].strip()
                        break
                for line in Path("/proc/meminfo").read_text().splitlines():
                    if line.startswith("MemTotal"):
                        facts["ram_gb"] = round(int(line.split()[1]) / 2**20, 1)
                        break
            except (OSError, ValueError, IndexError):
                pass
            facts["os"] = platform.platform()
        facts["gpu"] = _gpu()
    except Exception as e:
        _warn(f"machine facts incomplete ({e})")
    return facts


def pipeline_agents(root=None):
    """The agent names of the pipeline: AGENT_NAMES plus every `agents/<name>/`
    of the root. CF-0176: the list that says which agents belong in a run's
    header - `~/.claude/agents/*.md` also holds agents of the *development*
    process (`auto-dev-worker`), and those never touch a batch."""
    root = Path(root) if root else factory_root()
    names = list(AGENT_NAMES)
    try:
        for d in sorted((root / "agents").iterdir()):
            if d.is_dir() and d.name not in names:
                names.append(d.name)
    except OSError:
        pass
    return names


def _models(root=None):
    """{operator, subagent_default, subagents} of the run. `subagents` holds the
    pinned model of the *pipeline* agents only (CF-0176): the same
    `~/.claude/agents/*.md` directory also defines the agents that drive
    development, and a row of the runs table must describe the run, not the
    machine it was started on."""
    operator = None
    for key in ("CLAUDE_MODEL", "ANTHROPIC_MODEL"):
        if os.environ.get(key):
            operator = os.environ[key]
            break
    known = set(pipeline_agents(root))
    subagents = {}
    for d in (Path.home() / ".claude" / "agents", factory_root() / ".claude" / "agents"):
        try:
            for f in sorted(d.glob("*.md")):
                text = f.read_text(encoding="utf-8", errors="replace")
                if not text.startswith("---"):
                    continue
                fm = text.split("---", 2)[1]
                name = re.search(r"^name:\s*(.+)$", fm, re.M)
                model = re.search(r"^model:\s*(.+)$", fm, re.M)
                nm = (name.group(1) if name else f.stem).strip()
                if model and nm in known:
                    subagents[nm] = model.group(1).strip()
        except OSError:
            continue
    return {"operator": operator,
            "subagent_default": os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL") or None,
            "subagents": subagents or None}


VIDEO_EDITOR_FILE = "05-video-editor.json"


def editor_videos(batch_dir):
    """CF-0176: the videos the run actually built, from `<batch>/05-video-editor.json`
    - the output of the video-editor stage and the only place that names *finished*
    videos. Returns [{"slug", "script_id", "qc_passed", "entry"}], empty when the
    file is missing or unreadable.

    Not to be confused with the `video` field of RUN_EVENTS.jsonl: that field is
    overloaded - a finished-video slug under `video-editor`, the id of a source
    clip on YouTube under `footage-indexer` - so counting its distinct values
    counts the footage pool as videos (51 for a batch that built 3)."""
    p = Path(batch_dir) / VIDEO_EDITOR_FILE
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _warn(f"{p}: unreadable ({e})")
        return []
    out = []
    for v in (data.get("videos") or []) if isinstance(data, dict) else []:
        if not isinstance(v, dict):
            continue
        out.append({"slug": Path(v.get("output_path") or "").stem or v.get("script_id"),
                    "script_id": v.get("script_id"),
                    "qc_passed": (v.get("qc") or {}).get("passed"),
                    "entry": v})
    return out


def _counts(batch_dir):
    counts = {"topics": None, "sources": None, "videos": None}
    try:
        p = Path(batch_dir) / "01-trend-hunter.json"
        if p.is_file():
            topics = json.loads(p.read_text(encoding="utf-8")).get("topics") or []
            counts["topics"] = len(topics)
            srcs = set()
            for t in topics:
                for s in ((t.get("evidence") or {}).get("sources") or []):
                    srcs.add(json.dumps(s, sort_keys=True) if not isinstance(s, str) else s)
            counts["sources"] = len(srcs)
        p = Path(batch_dir) / "03-content-researcher.json"
        if p.is_file():
            counts["videos"] = len(json.loads(p.read_text(encoding="utf-8")).get("scripts") or [])
    except (OSError, ValueError, AttributeError) as e:
        _warn(f"counts incomplete ({e})")
    return counts


def header(batch_dir, root=None):
    """The run header for the batch-start marker: git of the root and of every
    agents/<name> (null when absent), README version, models, counts, machine facts."""
    root = Path(root) if root else factory_root()
    agents = {}
    names = pipeline_agents(root)
    for n in names:
        agents[n] = _git(root / "agents" / n)
    bd = Path(batch_dir)
    return {
        "batch": f"{bd.parent.name}/{bd.name}",
        "markup": MARKUP,                            # CF-0173
        # CF-0492: the checkout whose HEADs these are - the drift under the run
        # is read from this tree, not from whichever checkout a later marker
        # happens to be called from.
        "git": {"root": _git(root), "agents": agents, "checkout": str(Path(root).resolve())},
        "version": readme_version(root),
        "models": _models(root),
        "counts": _counts(bd),
        "machine": machine_facts(),
    }


# --------------------------------------------------------------------------
# CF-0398: a batch runs on `main` of every factory repo, and the code under it
# does not move
# --------------------------------------------------------------------------
#
# The user's decision of 2026-09-26: batches run on the `main` version only.
# Two ways the code under a live run changed on that day: an auto-dev worker in
# a nested repo switched the shared checkout to `work/<id>`, and the driver
# fast-forwarded `main` ~15 times while a 5-7 h run was going (1722Z: two of
# three videos built after five code changes, CF-0376). So:
#
#   * `batch-start` refuses unless every repo (the root + every `agents/<name>`
#     that is a git repo) is on branch `main`, its HEAD is `main`, and no
#     tracked file is modified or staged. Untracked files do not count - the
#     pipeline's outputs and caches live untracked - and neither do the tracked
#     records a run itself writes (RUN_DATA_PATHS). `--anyway REASON` goes on
#     and writes `code_override` into the event, as `stage-start` does for the
#     stop-cock (CF-0322) and the supplement (CF-0345).
#   * `stage-start` / `stage-done` compare every repo's HEAD with the header
#     and write each move once as `code_drift` on the marker event. They never
#     refuse: DoD 1 forbids dropping production on a suspicion. The triage
#     (CF-0319) counts a drift as an авария, RUN_SUMMARY prints it. Only HEAD
#     is compared after the start, never the working tree: the run writes its
#     own tracked records while it goes.
#   * `runlog batch-active` tells the auto-dev driver whether a batch is open
#     now, so that it does not move `main` under it (CF-0400).
#
# The rule is for the batches of the factory the code belongs to: a batch
# directory under `<root>/pipeline/` (rebuilds included). A run directory
# anywhere else (the tests' temp trees) is not checked and its event says so;
# a directory under `agents/` that is not a git repo is recorded as unknown and
# never refused.
#
# CF-0479 (the user, 2026-10-02) changed what "the version" is. The agents are
# libraries pinned in `agents.lock.json` (shared/agents_lock.py), so:
#
#   * the root must be clean on `main` or on a `release/<version>` branch, and
#     every agent of the lock must sit on the commit its pin resolves to, with
#     no modified or staged tracked file - on which branch, or detached, does
#     not matter. An agent repo the lock does not name is refused. The resolved
#     pins go into `code_check.lock` and the header (`agents_lock`), from which
#     the runs table writes them into the run's row.
#   * a move of the root counts as code drift only when it touches code: the
#     paths of NON_CODE_PATHS (task notes, publish notes, the runs table, docs,
#     analytics/ since CF-0895) are records, and a commit touching only them is not drift (CF-0457).
#     Nor is a commit touching only another channel's config (channels/<X>.json,
#     channels/<X>/**) under a batch of a channel other than X (CF-0685).
#     An agent is drift on any move of its HEAD, as before.

MAIN_BRANCH = "main"
RELEASE_PREFIX = "release/"                 # CF-0479: a version worktree of the root
CODE_LOCK_KEY = "lock"
HEADER_LOCK_KEY = "agents_lock"
CODE_OVERRIDE_KEY = "code_override"
CODE_CHECK_KEY = "code_check"
CODE_DRIFT_KEY = "code_drift"
FOREIGN_CHECKOUT_KEY = "foreign_checkout"   # CF-0492: a marker from another checkout than the batch's
# CF-0494: a verification rerun says what it may not do at batch-start, by a
# flag of the script and never by an edit of a step's record. The CLI value ->
# the mode written into the event (`rerun: {"mode": ...}`). `no-search`: the
# thin-pool supplement step searches and fetches nothing - every request is
# closed `skipped` with `outcome: rerun_no_search` (supplement.py).
RERUN_KEY = "rerun"
RERUN_MODES = {"no-search": "no_search"}
RERUN_TASK = "CF-0494"
ROOT_REPO = "root"
# Tracked paths of the root that a run's own code writes, so that their changes
# are records, not code: the runs table (`batch-done`, CF-0110) and the
# synthetic backfill runs under pipeline/, the rotation ledger (rotation/ledger/),
# and the task notes + INDEX.md rows the post-run triage files (CF-0319). None
# of them is imported by the pipeline.
RUN_DATA_PATHS = ("pipeline/", "rotation/ledger/", "tasks/")
# CF-0479 / CF-0457: tracked paths of the root that are not code - the run
# records above plus the publish notes, the docs and the project's own prose. A
# change to them is neither dirt at batch-start nor drift under a run; anything
# else in the root (scripts, shared/, channels/, agents/publisher/, tests/, the
# lock itself) is code.
# CF-0895: analytics/ too - only machine records live there (a Studio read's
# studio.jsonl / studio_visits.jsonl, the daily series, the
# footage-wanted list of commit-records). 30.10 a manual Studio read from the
# center during a trend-hunter stage was reported as "the stage changed the
# factory's code" (stage_code_guard).
NON_CODE_PATHS = RUN_DATA_PATHS + ("publish/", "docs/", "ROADMAP.md", "CHANGELOG.md",
                                   "README.md", "IDEAS.md", "analytics/")


def _git_out(d, *args, timeout=10):
    try:
        cp = sibling("git_read").run(["-C", str(d), *args], capture_output=True, text=True,
                                     timeout=timeout)      # CF-0717: optional locks off
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout.strip() if cp.returncode == 0 else None


def factory_repos(root=None):
    """[(label, path)] of the repos a batch runs: the root, then every existing
    `agents/<name>` directory in name order. A label is `root` or
    `agents/<name>`."""
    root = Path(root) if root else factory_root()
    out = [(ROOT_REPO, root)]
    try:
        for d in sorted((root / "agents").iterdir()):
            if d.is_dir():
                out.append((f"agents/{d.name}", d))
    except OSError:
        pass
    return out


def repo_head(d):
    """HEAD of the repo at d, or None when d is not a git repo of its own (a
    directory without .git would otherwise answer with its parent's HEAD)."""
    if not (Path(d) / ".git").exists():
        return None
    return _git_out(d, "rev-parse", "HEAD", timeout=5)


def repo_state(label, d):
    """{repo, git, branch, head, main, dirty} of one repo. `git` is False for a
    directory that is not a git repo; `dirty` lists the modified or staged
    tracked files (untracked files never count; for the root, RUN_DATA_PATHS
    are left out), None when `git status` failed."""
    st = {"repo": label, "git": False, "branch": None, "head": None, "main": None,
          "dirty": []}
    head = repo_head(d)
    if head is None:
        return st
    st.update(git=True, head=head,
              branch=_git_out(d, "symbolic-ref", "--short", "-q", "HEAD", timeout=5),
              main=_git_out(d, "rev-parse", "--verify", "-q", f"refs/heads/{MAIN_BRANCH}",
                            timeout=5))
    try:
        cp = sibling("git_read").run(["-C", str(d), "status", "--porcelain",
                                      "--untracked-files=no"], capture_output=True,
                                     text=True, timeout=10)      # CF-0717
        porcelain = cp.stdout if cp.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        porcelain = None
    if porcelain is None:
        st["dirty"] = None
        return st
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if label == ROOT_REPO and is_non_code(path):
            continue
        st["dirty"].append(path)
    return st


def is_non_code(path):
    """CF-0479: True for a root path that is a record, not code (NON_CODE_PATHS)."""
    return path.startswith(NON_CODE_PATHS)


def root_branch_ok(branch):
    """CF-0479: the root carries a batch on `main` or on a `release/<version>`."""
    return bool(branch) and (branch == MAIN_BRANCH or branch.startswith(RELEASE_PREFIX))


def repo_problems(st):
    """Why the root may not carry a batch: [] when it may (CF-0479: clean, on
    `main` or `release/*`). A non-git directory is unknown, not refused. The
    agents are checked against the lock instead (lock_problems)."""
    if not st["git"]:
        return []
    out = []
    if not root_branch_ok(st["branch"]):
        where = f"branch {st['branch']!r}" if st["branch"] else "a detached HEAD"
        out.append(f"{st['repo']}: on {where}, not {MAIN_BRANCH} or {RELEASE_PREFIX}*")
    if st["dirty"] is None:
        out.append(f"{st['repo']}: `git status` failed, the tree cannot be vouched for")
    elif st["dirty"]:
        shown = ", ".join(st["dirty"][:5]) + (" ..." if len(st["dirty"]) > 5 else "")
        out.append(f"{st['repo']}: {len(st['dirty'])} uncommitted tracked file(s) ({shown})")
    return out


def under_factory(bdir, root=None):
    """True when the batch directory lives under `<root>/pipeline/` - a run of
    this factory, which the rule of CF-0398 is about."""
    root = Path(root) if root else factory_root()
    b, p = Path(bdir), root / "pipeline"
    for x, y in ((b.absolute(), p.absolute()), (b.resolve(), p.resolve())):
        try:
            x.relative_to(y)
            return True
        except ValueError:
            continue
    return False


def agents_lock():
    """shared/agents_lock.py, the one reader of agents.lock.json (CF-0479)."""
    import importlib.util
    mod = sys.modules.get("agents_lock")
    if mod is not None:
        return mod
    path = Path(__file__).resolve().parents[1] / "agents_lock.py"
    spec = importlib.util.spec_from_file_location("agents_lock", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agents_lock"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop("agents_lock", None)
        raise
    return mod


def lock_problems(root, repos):
    """CF-0479: ({path: {rev, sha}} of the lock's resolved pins, [problems]).
    Every agent of the lock must be on its pinned commit with a clean tracked
    tree; a git repo under agents/ that the lock does not name is refused; no
    lock at all is refused only when there is an agent repo to vouch for."""
    al = agents_lock()
    agent_repos = sorted(lbl for lbl, st in repos.items() if lbl != ROOT_REPO and st.get("git"))
    try:
        lock = al.load(root, required=False)
    except al.LockError as e:
        return {}, [f"{al.LOCK_NAME}: {e}"]
    if lock is None:
        return {}, ([f"no {al.LOCK_NAME} in the root - the agents' revisions cannot be vouched "
                     f"for ({', '.join(agent_repos)})"] if agent_repos else [])
    pins, problems = {}, []
    for r in al.status(root):
        pins[r["path"]] = {"rev": r["rev"], "sha": r["sha"]}
        if not r["ok"]:
            problems.append(f"{r['path']}: {r['why']} ({al.LOCK_NAME} pins {r['rev']}; "
                            f"`scripts/agents sync`)")
    named = {e[1] for e in al.entries(lock)}
    for lbl in agent_repos:
        if lbl not in named:
            problems.append(f"{lbl}: a git repo {al.LOCK_NAME} does not pin")
    return pins, problems


def code_check(bdir, root=None):
    """CF-0398 / CF-0479: the state of every factory repo at batch-start and the
    reasons the batch may not start: {"checked", "why", "repos": {label: state},
    "lock": {path: {rev, sha}}, "problems": [str]}. Never raises."""
    root = Path(root) if root else factory_root()
    if not under_factory(bdir, root):
        return {"checked": False, "why": f"batch outside {root / 'pipeline'}",
                "repos": {}, "lock": {}, "problems": []}
    repos, problems = {}, []
    for label, d in factory_repos(root):
        st = repo_state(label, d)
        repos[label] = {k: v for k, v in st.items() if k != "repo"}
        if label == ROOT_REPO:
            problems += repo_problems(st)
    pins, lp = lock_problems(root, repos)
    return {"checked": True, "why": None, "repos": repos, "lock": pins,
            "problems": problems + lp}


def _header_heads(events):
    """{label: commit} from the batch-start header, then moved by every
    code_drift already recorded, so that one move is written once."""
    heads = {}
    for e in events:
        if not isinstance(e, dict) or e.get("kind") != KIND_MARKER:
            continue
        if e.get("status") == M_BATCH_START:
            git = (e.get("header") or {}).get("git") or {}
            heads = {}
            if (git.get("root") or {}).get("commit"):
                heads[ROOT_REPO] = git["root"]["commit"]
            for n, v in (git.get("agents") or {}).items():
                if (v or {}).get("commit"):
                    heads[f"agents/{n}"] = v["commit"]
        for d in e.get(CODE_DRIFT_KEY) or []:
            if isinstance(d, dict) and d.get("repo") and d.get("now"):
                heads[d["repo"]] = d["now"]
    return heads


# CF-0685 (user's decision 2026-10-11): the command center refuses an edit of a
# channel only while a batch of *that* channel is open; an edit of another
# channel is allowed, and its commit moves the root's HEAD under the open run.
# `channels/<X>.json` and `channels/<X>/**` with X (by its current id) other
# than the batch's own channel are therefore not the code of that batch.
CHANNELS_DIR = "channels/"
# Run dirs under pipeline/ that are not one channel's batches.
NON_CHANNEL_RUN_DIRS = ("rebuilds", "backfill")


def _channel_ids_mod():
    """shared/channel_ids.py, loaded by path (as funnel._channel_ids, CF-0231),
    or None when it cannot be loaded (then names are compared as written)."""
    mod = sys.modules.get("channel_ids_for_runlog")
    if mod is not None:
        return mod
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "channel_ids.py"
    try:
        spec = importlib.util.spec_from_file_location("channel_ids_for_runlog", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:                                   # noqa: BLE001
        return None
    sys.modules["channel_ids_for_runlog"] = mod
    return mod


def resolve_channel(name, root=None):
    """CF-0685: the current id of a channel that may be named by a former one
    (channel_ids.resolve_channel against `root`'s channels/); the name as
    written when that cannot be read."""
    mod = _channel_ids_mod()
    if not name or mod is None:
        return name
    try:
        return mod.resolve_channel(name, root)
    except Exception:                                   # noqa: BLE001
        return name


def path_channel(path):
    """CF-0685: the channel a root path configures - X for `channels/X.json` and
    for anything under `channels/X/` - or None for every other path (a shared
    file of channels/, such as ACCOUNTS.md, is the code of every channel)."""
    if not path.startswith(CHANNELS_DIR):
        return None
    rest = path[len(CHANNELS_DIR):]
    head, sep, _ = rest.partition("/")
    if sep:
        return head or None
    if rest.endswith(".json") and len(rest) > len(".json"):
        return rest[:-len(".json")]
    return None


def batch_channel(bdir, root=None):
    """CF-0685: the channel of the batch at `bdir` (`pipeline/<channel>/<batch>`),
    under its current id; None when the directory is not one channel's batch
    (a rebuild, a backfill run, a dir outside a pipeline/) - then no channel's
    edit is excused."""
    if not bdir:
        return None
    b = Path(bdir)
    if b.parent.parent.name != "pipeline" or b.parent.name in NON_CHANNEL_RUN_DIRS:
        return None
    return resolve_channel(b.parent.name, root) or None


def code_paths_moved(d, was, now, channel=None):
    """CF-0479 / CF-0457: the code paths of the root that differ between two
    commits - [] when every changed path is a record (NON_CODE_PATHS), None
    when git cannot tell (then the move counts as drift).

    CF-0685: with `channel` (the open batch's channel), the config of another
    channel (`channels/<X>.json`, `channels/<X>/**`, X resolved to its current
    id) is not code either; the batch's own channel config still is. Without
    `channel` every channel config is code, as before."""
    out = _git_out(d, "diff", "--name-only", "--no-renames", was, now, timeout=30)
    if out is None:
        return None
    paths = [p.strip() for p in out.splitlines() if p.strip() and not is_non_code(p.strip())]
    if not channel:
        return paths
    own = resolve_channel(channel, d)
    return [p for p in paths
            if (pc := path_channel(p)) is None or resolve_channel(pc, d) == own]


def code_moved(label, was, now, root=None, channel=None):
    """CF-0479 / CF-0484: the one rule of "the code of `label` is not the same
    between commits `was` and `now`" - for the drift under a run (code_drift)
    and for a ready video built off the run's code (triage). An agent differs
    with any other sha; the root only when the move touches a code path - a
    move of records alone (NON_CODE_PATHS: task notes, publish notes, the runs
    table, docs) is the same code. A move git cannot read counts.

    CF-0685: `channel` is the open batch's channel; a root move that touches
    only other channels' configs is the same code for it (code_paths_moved)."""
    if not was or not now or was == now:
        return False
    if label == ROOT_REPO:
        return code_paths_moved(Path(root) if root else factory_root(), was, now,
                                channel=channel) != []
    return True


def _batch_start_event(events):
    """The last batch-start marker of the run, or None."""
    out = None
    for e in events:
        if (isinstance(e, dict) and e.get("kind") == KIND_MARKER
                and e.get("status") == M_BATCH_START):
            out = e
    return out


def question(text, batch_dir=None):
    """CF-0494: record that the orchestrator asked the user mid-run - the
    question's words in `note`, the stage open at the moment in `stage`. Needs
    an open run (a batch-start). Returns the event; RunlogError on a bad call.
    Recording a question does not make waiting for its answer lawful: the
    wait is still measured and still an incident; it is only no longer one
    nobody can name."""
    if not (text or "").strip():
        raise RunlogError("question needs its text (--note TEXT)")
    bdir = find_batch_dir(batch_dir)
    if bdir is None:
        raise RunlogError(f"no batch directory: pass --batch DIR, set {BATCH_ENV}, "
                          f"or run from inside pipeline/<channel>/<batch-id>")
    events = read_events(bdir)
    if _batch_start_event(events) is None:
        raise RunlogError(f"question before batch-start: no open run in {bdir}")
    stages = _open_stages(events)
    ev = emit(bdir, KIND_QUESTION, list(stages)[-1] if stages else None, status="asked",
              note=text.strip(), task=RERUN_TASK)
    if ev is None:
        raise RunlogError("event not written (see stderr)")
    return ev


def rerun_mode(events):
    """CF-0494: the mode the batch was opened with (`batch-start --rerun`),
    read from its batch-start event - `"no_search"` or None. A batch opened
    without the flag, or before CF-0494, is not a rerun of any mode: nothing
    is inferred from its note."""
    r = (_batch_start_event(events) or {}).get(RERUN_KEY)
    m = r.get("mode") if isinstance(r, dict) else None
    return m if m in RERUN_MODES.values() else None


def header_checkout(events):
    """CF-0492: the checkout path batch-start recorded beside the HEADs
    (`header.git.checkout`), or None for a batch opened before CF-0492."""
    e = _batch_start_event(events)
    git = ((e or {}).get("header") or {}).get("git") or {}
    c = git.get("checkout") if isinstance(git, dict) else None
    return c if isinstance(c, str) and c else None


def _same_path(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, RuntimeError):
        return str(a) == str(b)


def foreign_checkout(events, root=None):
    """CF-0492: {batch, caller} when this marker is called from another checkout
    than the one batch-start recorded - a warning, not an авария: the drift is
    read from the batch's own tree anyway. None when they are the same, or for
    a batch opened before CF-0492 (no path recorded)."""
    rec = header_checkout(events)
    if rec is None:
        return None
    caller = Path(root).resolve() if root else factory_root()
    if _same_path(rec, caller):
        return None
    return {"batch": rec, "caller": str(caller)}


def code_drift(events, bdir, root=None):
    """CF-0398: [{repo, was, now}] for every repo whose code moved since the
    header (or since its last recorded move). An agent moves with its HEAD; the
    root only when the move touches a code path - commits to task notes, publish
    notes, the runs table or the docs are not drift (CF-0479, CF-0457). [] outside
    the factory, without a header, or when nothing moved. Never raises, never
    refuses.

    CF-0492: the repos are read in the checkout batch-start recorded
    (`header.git.checkout`), not in the one this marker is called from - a
    batch opened from a version worktree and marked from the main checkout
    compares the worktree's HEADs. Whether the run is a factory batch at all is
    then what batch-start's own check said (`code_check.checked`). A batch
    without a recorded path (opened before CF-0492) is read as before: in the
    caller's checkout."""
    try:
        caller = Path(root) if root else factory_root()
        rec = header_checkout(events)
        if rec is None:
            base = caller
            if not under_factory(bdir, base):
                return []
        else:
            base = Path(rec)
            checked = ((_batch_start_event(events) or {}).get(CODE_CHECK_KEY) or {}).get("checked")
            if checked is False or (checked is None and not under_factory(bdir, base)):
                return []
            if not base.is_dir():
                _warn(f"code drift not checked: the checkout batch-start recorded is gone ({base})")
                return []
        was = _header_heads(events)
        channel = batch_channel(bdir, base)                 # CF-0685
        out = []
        for label, d in factory_repos(base):
            if not was.get(label):
                continue
            now = repo_head(d)
            if not code_moved(label, was[label], now, d, channel=channel):
                continue
            out.append({"repo": label, "was": was[label], "now": now})
        return out
    except Exception as e:                                  # noqa: BLE001
        _warn(f"code drift not checked ({e.__class__.__name__}: {e})")
        return []


def drift_rows(events, resets=None, channel=None, root=None):
    """Every recorded move of the code under this run, in file order:
    [{ts, marker, stage, repo, was, now, reset}]. `reset` (CF-0739) is the
    brief of the recorded reset that explains the move - seen at the first
    stage-start after the reset (the run's new code base), or seen before the
    reset by a stage the reset threw away - else None, and the move is an
    авария as before."""
    pts = rebase_points(events, resets) if resets else {}
    cache = {}
    out = []
    for e in events:
        for d in (e.get(CODE_DRIFT_KEY) or []) if isinstance(e, dict) else []:
            if not isinstance(d, dict):
                continue
            why = pts.get(id(e))
            if why is None and resets:
                t = _reset_t(e.get("ts"))
                for r in resets:
                    if (t is not None and t < r["t"]
                            and _marker_name(e) in reset_names(r, channel, root, cache)):
                        why = r
                        break
            out.append({"ts": e.get("ts"), "marker": e.get("status"),
                        "stage": e.get("stage"), "repo": d.get("repo"),
                        "was": d.get("was"), "now": d.get("now"),
                        "reset": reset_brief(why) if why else None})
    return out


# --------------------------------------------------------------------------
# CF-0739 items 3-5: a recorded reset of the batch's stages
#
# `batch_control.rerun_from` (or a hand reset done the same way, 13.10 on
# example-film/2026-10-13T1411Z for CF-0734) sets stages back to pending and
# writes a `manual_resets` row into run-state.json: {at (UTC Z), by, task, why,
# reset: [plan stage ids], ...}; rerun_from also writes a `control
# batch-rerun-from` event. The post-run readers take the reset as a fact of the
# run, not as an accident of it:
#   * code_drift  - the HEAD at the first stage-start after the reset is the
#                   run's new code base for the reset stages; the move seen
#                   there, and a move seen before the reset by a reset stage
#                   (its output was thrown away), is not an авария. A move
#                   after the reset still is.
#   * built_off_run - a ready video of a reset video-editor is judged against
#                   that new base.
#   * crash       - a stage opened before the reset and reset by it is closed
#                   by the reset.
#   * no_waiting  - the silence that holds the reset (the batch stopped, then
#                   resumed after it) is a ruled stop, named by the reset.
# Readers work from run-state.json alone (a hand reset writes nothing else);
# the event is accepted as well, and one that repeats a run-state row (the
# same stages, within RESET_EVENT_SLACK_S) is the same reset.
# --------------------------------------------------------------------------

STATE_FILE = "run-state.json"
MANUAL_RESETS_KEY = "manual_resets"
KIND_CONTROL = "control"
EV_RERUN_FROM = "batch-rerun-from"          # batch_control.EV_RERUN
RESET_EVENT_SLACK_S = 300


def _reset_t(s):
    try:
        return parse_z(str(s))
    except (TypeError, ValueError):
        return None


def manual_resets(bdir=None, events=None, state=None):
    """Every recorded reset of the batch's stages, oldest first:
    [{at, t, by, task, why, from, reset: [plan ids], markers: [names] | None,
    via, source: "run-state" | "event"}]. `state` (a dict) replaces reading
    run-state.json. Never raises."""
    out = []
    try:
        if state is None and bdir is not None:
            p = Path(bdir) / STATE_FILE
            try:
                state = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
            except (OSError, ValueError):
                state = None
        for r in ((state or {}).get(MANUAL_RESETS_KEY) or []) if isinstance(state, dict) else []:
            if not isinstance(r, dict):
                continue
            t = _reset_t(r.get("at"))
            if t is None:
                continue
            out.append({"at": r.get("at"), "t": t, "by": r.get("by"), "task": r.get("task"),
                        "why": r.get("why"), "from": r.get("from"),
                        "reset": [s for s in r.get("reset") or [] if isinstance(s, str)],
                        "markers": (list(r["markers"]) if isinstance(r.get("markers"), list)
                                    else None),
                        "via": r.get("via"), "source": "run-state"})
        for e in events or []:
            if not (isinstance(e, dict) and e.get("kind") == KIND_CONTROL
                    and e.get("status") == EV_RERUN_FROM):
                continue
            t = _reset_t(e.get("ts"))
            pr = e.get("params") if isinstance(e.get("params"), dict) else {}
            ids = [s for s in pr.get("reset") or [] if isinstance(s, str)]
            if t is None or not ids:
                continue
            if any(sorted(o["reset"]) == sorted(ids) and abs(o["t"] - t) <= RESET_EVENT_SLACK_S
                   for o in out):
                continue
            out.append({"at": e.get("ts"), "t": t, "by": e.get("by"), "task": e.get("task"),
                        "why": pr.get("why") or e.get("note"), "from": pr.get("from"),
                        "reset": ids,
                        "markers": (list(pr["markers"]) if isinstance(pr.get("markers"), list)
                                    else None),
                        "via": pr.get("via"), "source": "event"})
    except Exception as ex:                                   # noqa: BLE001
        _warn(f"manual resets not read ({ex.__class__.__name__}: {ex})")
    out.sort(key=lambda r: r["t"])
    return out


def _plan_markers(channel, root=None):
    """{plan stage id: marker name} of the channel's run plan, {} when unreadable."""
    if not channel:
        return {}
    try:
        shared = str(Path(__file__).resolve().parent.parent)
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import run_plan                                       # noqa: PLC0415
        plan = run_plan.load(channel, root)
        return {s["id"]: s["marker"] for s in plan.get("stages") or []
                if isinstance(s, dict) and s.get("id") and s.get("marker")}
    except Exception:                                         # noqa: BLE001
        return {}


def plan_producers(channel, root=None):
    """CF-0730: {contract file: plan stage id that produces it} of the
    channel's run plan, {} when unreadable. Two plan stages may share a marker
    (compliance-shortlist and compliance-scripts both write compliance-checker);
    the file each one owes tells them apart."""
    if not channel:
        return {}
    try:
        shared = str(Path(__file__).resolve().parent.parent)
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import run_plan                                       # noqa: PLC0415
        plan = run_plan.load(channel, root)
        return {f: s["id"] for s in plan.get("stages") or [] if isinstance(s, dict)
                for f in s.get("produces") or [] if s.get("id")}
    except Exception:                                         # noqa: BLE001
        return {}


def reset_names(r, channel=None, root=None, _cache=None):
    """The stage names a reset covers as the journal writes them: its plan ids,
    the markers it recorded, and - for a row without `markers` (a hand reset) -
    the markers the channel's plan gives those ids."""
    names = set(r.get("reset") or [])
    if r.get("markers") is not None:
        names |= set(r["markers"])
    else:
        if _cache is None:
            _cache = {}
        if channel not in _cache:
            _cache[channel] = _plan_markers(channel, root)
        names |= {m for sid, m in _cache[channel].items() if sid in names}
    return names


# CF-0899: the executor's halts on `claude` not logged in (shared/run_executor.py
# LOGIN_HALTS_KEY). A batch halted before the key existed is read from what the
# executor left anyway: a `discarded_runs` row of an LLM stage - the executor
# discards a run on NOT_LOGGED_IN and nowhere else - followed by a `resumed`.
LOGIN_HALTS_KEY = "login_halts"
LOGIN_TASK = "CF-0899"


def login_halts(bdir=None, state=None):
    """Every recorded halt of the run on `claude` not logged in, oldest first:
    [{at, t, stage, reason, task, resumed, t_resumed, source: "run-state" |
    "discarded_run"}]; `resumed` None while the batch still stands. `state`
    (a dict) replaces reading run-state.json. Never raises."""
    out = []
    try:
        if state is None and bdir is not None:
            p = Path(bdir) / STATE_FILE
            try:
                state = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
            except (OSError, ValueError):
                state = None
        if not isinstance(state, dict):
            return []
        resumed = sorted(t for t in (_reset_t(x) for x in state.get("resumed") or []
                                     if isinstance(x, str)) if t is not None)
        if isinstance(state.get(LOGIN_HALTS_KEY), list):
            for h in state[LOGIN_HALTS_KEY]:
                t = _reset_t(h.get("at")) if isinstance(h, dict) else None
                if t is None:
                    continue
                out.append({"at": h.get("at"), "t": t, "stage": h.get("stage"),
                            "reason": h.get("reason"), "task": h.get("task") or LOGIN_TASK,
                            "resumed": h.get("resumed"), "t_resumed": _reset_t(h.get("resumed")),
                            "source": "run-state"})
        else:
            for r in state.get("discarded_runs") or []:
                if not (isinstance(r, dict) and str(r.get("key") or "").endswith(".llm")):
                    continue
                at = r.get("ended") or r.get("started")
                t = _reset_t(at)
                if t is None:
                    continue
                after = [x for x in resumed if x >= t]
                out.append({"at": at, "t": t, "stage": r.get("stage"),
                            "reason": "NOT_LOGGED_IN (the run the executor discarded on it)",
                            "task": LOGIN_TASK,
                            "resumed": now_z_of(after[0]) if after else None,
                            "t_resumed": after[0] if after else None,
                            "source": "discarded_run"})
    except Exception as ex:                                   # noqa: BLE001
        _warn(f"login halts not read ({ex.__class__.__name__}: {ex})")
    out.sort(key=lambda r: r["t"])
    return out


def now_z_of(t):
    """An epoch second as `YYYY-MM-DDTHH:MM:SSZ`."""
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reset_brief(r):
    """The reset as a reader names it: {at, task, by, why, from}."""
    return {"at": r.get("at"), "task": r.get("task"), "by": r.get("by"), "why": r.get("why"),
            "from": r.get("from") or ((r.get("reset") or [None])[0])}


def reset_text(r):
    b = reset_brief(r)
    return (f"reset {b['at']} ({b['task'] or 'no task'}, {b['by'] or '?'}: "
            f"{b['why'] or 'no reason recorded'}; from {b['from']})")


def _marker_name(e):
    return e.get("stage") or e.get("status")


def rebase_points(events, resets):
    """{id(event): reset} - for each reset, the first stage-start marker at or
    after its `at`: the HEADs there are the run's new code base."""
    out = {}
    marks = []
    for e in events or []:
        if (isinstance(e, dict) and e.get("kind") == KIND_MARKER
                and e.get("status") == M_STAGE_START):
            t = _reset_t(e.get("ts"))
            if t is not None:
                marks.append((t, e))
    marks.sort(key=lambda x: x[0])
    for r in resets or []:
        hit = next((e for t, e in marks if t >= r["t"]), None)
        if hit is not None and id(hit) not in out:
            out[id(hit)] = r
    return out


def code_bases(events, resets):
    """[(reset, {label: commit})] - the code base each reset set: the HEADs at
    the first stage-start after it (the header moved by every recorded move up
    to and including that marker)."""
    pts = rebase_points(events, resets)
    out, seen = [], []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        seen.append(e)
        if id(e) in pts:
            out.append((pts[id(e)], _header_heads(seen)))
    return out


def code_override_of(events):
    """The `--anyway` record of batch-start, or None."""
    for e in events:
        if (isinstance(e, dict) and e.get("kind") == KIND_MARKER
                and e.get("status") == M_BATCH_START):
            return e.get(CODE_OVERRIDE_KEY)
    return None


def drift_headline(rows, override=None):
    """The line near the top of RUN_SUMMARY.md: None on a run that started on
    a clean main and whose code stood still under it."""
    parts = []
    based = [r for r in rows or [] if r.get("reset")]            # CF-0739
    rows = [r for r in rows or [] if not r.get("reset")]
    if based:
        parts.append("code base moved at a recorded reset (not an авария, CF-0739): " + "; ".join(
            f"{r['repo']} {str(r['was'])[:7]} -> {str(r['now'])[:7]} at {r['marker']} "
            f"{r['stage'] or ''} - {r['reset']['task'] or 'no task'}, {r['reset']['by'] or '?'}: "
            f"{r['reset']['why'] or 'no reason recorded'}" for r in based))
    if rows:
        moves = "; ".join(f"{r['repo']} {str(r['was'])[:7]} -> {str(r['now'])[:7]} "
                          f"at {r['marker']} {r['stage'] or ''}".rstrip() for r in rows)
        parts.append(f"**code drift: the code moved {len(rows)} time(s) under the run** "
                     f"({moves}) - CF-0398; the output of this run does not belong to one "
                     f"version of the code, and by the rule of CF-0319 each move is an авария")
    if override:
        parts.append(f"**started off a clean main** (`--anyway`: {override.get('reason')}) - "
                     f"{'; '.join(override.get('was') or [])} - CF-0398")
    return "  \n".join(parts) or None


# --------------------------------------------------------------------------
# CF-0398 item 3: is a batch open now
# --------------------------------------------------------------------------

def _last_ts(path):
    """ts of the last readable event of the file, else its mtime."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            tail = fh.read().splitlines()
        for line in reversed(tail):
            try:
                return datetime.fromtimestamp(parse_z(json.loads(line).get("ts")),
                                              tz=timezone.utc)
            except (ValueError, AttributeError, TypeError, OverflowError):
                continue
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


# CF-0656: `open_batches` took 7-40 s on the live tree - every call read the
# whole ~460 MB of events and json-parsed every line of every rebuild (the
# `child` lines alone are ~32 MB in one rebuild). What it needs is far less:
#
#   * a batch is closed once `"batch-done"` is anywhere in it - and batch-done is
#     the last marker, so a search from the END finds it in the tail (the batch
#     is read whole only while it is open);
#   * a rebuild's stage markers are found by a byte search, not a split of the
#     file into lines;
#   * a rebuild is working (CF-0401) by its newest work event and its open
#     scripts started within `hours`. The events are appended in time order
#     (the live rebuilds go back by at most 0.3 s), so the newest one is in
#     the tail, and only the tail since `now - hours` holds a script that may
#     count - plus ORDER_SLACK_S of margin for the writers' jitter. Older than
#     that, the file is not parsed at all.
#
# Nothing here is cached and nothing is shared between calls: the API calls this
# from a pool of threads (CC-0039), each call reads its own file handles.

ORDER_SLACK_S = 600.0        # CF-0656: events of one file are in time order within this
_SCAN_CHUNK = 1 << 18
_SAMPLE_B = b'"kind": "sample"'
_SCRIPT_RE = re.compile(rb'"kind"\s*:\s*"script"')
_START_RE = re.compile(rb'"status"\s*:\s*"start"')
_PID_RE = re.compile(rb'"pid"\s*:\s*"?\s*([0-9]+)')
_HEAD_TS_RE = re.compile(rb'\{\s*"ts"\s*:\s*"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})')
_ZTS_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
                     r"(?:\.([0-9]{1,6}))?Z*\Z")


def _parse_z_fast(ts):
    """parse_z without strptime for the common shape (strptime is ~25 us a call,
    and a working rebuild has tens of thousands of lines); anything else goes to
    parse_z itself, errors included."""
    m = _ZTS_RE.match(ts) if isinstance(ts, str) else None
    if not m or int(m.group(6)) > 59:
        return parse_z(ts)
    y, mo, d, h, mi, sec, frac = m.groups()
    return datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec),
                    int((frac or "0").ljust(6, "0")), tzinfo=timezone.utc).timestamp()


def _file_has(fh, size, needle, from_end=False):
    """True when `needle` is anywhere in the first `size` bytes of `fh`, read in
    chunks from the start or from the end (chunks overlap by the needle)."""
    keep = len(needle) - 1
    if from_end:
        pos, carry = size, b""
        while pos > 0:
            start = max(0, pos - _SCAN_CHUNK)
            fh.seek(start)
            buf = fh.read(pos - start) + carry
            if needle in buf:
                return True
            carry, pos = buf[:keep], start
        return False
    pos, carry = 0, b""
    while pos < size:
        fh.seek(pos)
        buf = carry + fh.read(min(_SCAN_CHUNK, size - pos))
        if not buf or needle in buf:
            return bool(buf)
        carry, pos = buf[-keep:] if keep else b"", pos + _SCAN_CHUNK
    return False


def _reverse_lines(fh, size):
    """The non-empty lines of the first `size` bytes of `fh`, last first."""
    pos, rest = size, b""
    while pos > 0:
        start = max(0, pos - _SCAN_CHUNK)
        fh.seek(start)
        parts = (fh.read(pos - start) + rest).split(b"\n")
        pos = start
        rest = parts.pop(0) if pos > 0 else b""
        for line in reversed(parts):
            if line:
                yield line


def _marker_lines(data):
    """Every line of `data` that holds `"marker"`, in order (a byte search)."""
    pos, n = 0, len(data)
    while True:
        i = data.find(b'"marker"', pos)
        if i < 0:
            return
        a = data.rfind(b"\n", 0, i) + 1
        b = data.find(b"\n", i)
        b = n if b < 0 else b
        yield data[a:b]
        pos = b + 1


def _last_at(fh, size, needle):
    """The offset of the last `needle` in the first `size` bytes of `fh`, read
    in chunks from the end (overlapping by the needle); -1 when there is none."""
    keep = len(needle) - 1
    pos, carry = size, b""
    while pos > 0:
        start = max(0, pos - _SCAN_CHUNK)
        fh.seek(start)
        buf = fh.read(pos - start) + carry
        i = buf.rfind(needle)
        if i >= 0:
            return start + i
        carry, pos = buf[:keep], start
    return -1


REOPENED_WHY = "снова открыт после batch-done: стадия {stage} начата и не закрыта (CF-0739)"
RESTARTED_WHY = "снова открыт после batch-done: новый batch-start (CF-0739)"


def _batch_open(path):
    """CF-0739: why a channel batch is open, or None when it is closed.

    Open with a batch-start and no batch-done ("нет batch-done"). After the
    last batch-done it is open again while what follows it reopens it (the
    rework CF-0251 allows: `run_executor` re-running a stage after
    `batch_control rerun-from`): a batch-start, or a stage-start with no
    stage-done after it. A rework whose stages all closed again is closed - a
    marker after batch-done alone does not hold the batch open forever (the
    rework of 2026-09-23T1722Z). Between two re-run stages the run's lock
    keeps it open (CF-0670, `open_batches`).

    Byte searches from the end (CF-0656): the last `"batch-done"` is found
    from the end, only the bytes after its line are parsed, and only their
    marker lines."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            at = _last_at(fh, size, b'"batch-done"')
            if at < 0:
                return "нет batch-done" if _file_has(fh, size, b'"batch-start"') else None
            fh.seek(at)
            rest = fh.read(size - at)
    except OSError:
        return None
    nl = rest.find(b"\n")
    if nl < 0:
        return None
    markers = []
    for line in _marker_lines(rest[nl + 1:]):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("kind") == KIND_MARKER:
            markers.append(e)
    if any(e.get("status") == M_BATCH_START for e in markers):
        return RESTARTED_WHY
    open_ = _open_stages(markers)
    if open_:
        return REOPENED_WHY.format(stage=", ".join(str(s) for s in open_))
    return None


def _is_open(path, rebuild):
    """A batch is open with a batch-start and no batch-done - or, after its
    batch-done, while a re-run stage is going (CF-0739, `_batch_open`). A
    rebuild has no batch-done by design (CF-0339) - its stages close it, so it
    is open while a stage-start is not matched by a stage-done. Byte searches
    only, the batch-done one from the end (CF-0656): the whole pool of events
    is ~460 MB and this must stay well under a second."""
    if not rebuild:
        return _batch_open(path) is not None
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            if not _file_has(fh, size, b'"batch-start"'):
                return False
            fh.seek(0)
            data = fh.read(size)
    except OSError:
        return False
    markers = []
    for line in _marker_lines(data):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("kind") == KIND_MARKER:
            markers.append(e)
    return bool(_open_stages(markers))


class OpenRow(tuple):
    """CF-0670: a row of `open_batches` - the triple `(dir, last_ts, fresh)` every
    caller unpacks and compares, plus `why`: one Russian line on why the run is
    open, for the user («исполнитель жив (pid N)», «нет batch-done», ...)."""

    def __new__(cls, d, last, fresh, why=None):
        row = super().__new__(cls, (d, last, fresh))
        row.why = why
        return row


def open_batches(root=None, now=None, hours=None):
    """CF-0398: [(dir, last_ts, fresh)] of every open run under
    `<root>/pipeline/<channel>/<id>` and `<root>/pipeline/rebuilds/<ts>`.
    `fresh` is False when its last event is older than `hours` - by default
    the sampler's own cap (`sampler.MAX_HOURS`, 24 h): past it not even the
    daemon that follows a run believes the run is alive, so a batch that
    crashed without batch-done does not hold `main` forever. Synthetic
    `pipeline/backfill/` runs are never open.

    CF-0401: a rebuild is also open while it is working, markers or none - the
    rebuilds since 2026-09-23T1053Z write only the events of their scripts,
    because nobody runs `batch-start` by hand. See `_rebuild_working`.

    CF-0670: a batch or a rebuild is open (and fresh) while its
    `run-executor.lock` is held - by a live executor, which holds it for the
    whole run, pauses between stages with no event included, or by a holder
    that is not recognised (CF-0667's refusal: see `executor_lock`). The lock is
    probed only where the file is. Each row is an `OpenRow`, its `why` the line
    for the user."""
    root = Path(root) if root else factory_root()
    if hours is None:
        hours = float(sibling("sampler").MAX_HOURS)
    now = now or datetime.now(timezone.utc)
    pipe = root / "pipeline"
    runs = {p.parent for p in pipe.glob(f"*/*/{EVENTS_FILE}")}
    xl = sibling("executor_lock")
    locked = {p.parent for p in pipe.glob(f"*/*/{xl.LOCK_FILE}")}
    out = []
    for d in sorted(runs | locked):             # Paths sort by parts: as their events files did
        chan = d.parent.name
        if chan == "backfill":
            continue
        path = d / EVENTS_FILE
        rebuild = chan == "rebuilds"
        if d in locked:
            h = xl.holder(d)
            if h["held"]:
                last = _last_ts(path) if d in runs else _mtime(d / xl.LOCK_FILE)
                out.append(OpenRow(d, last, True, xl.why(h)))
                continue
            if d not in runs:
                continue
        why = (("стадия пересборки начата и не закрыта (stage-start без stage-done)"
                if _is_open(path, rebuild=True) else None) if rebuild else _batch_open(path))
        if not why:
            working = _rebuild_work(path, now, hours) if rebuild else None
            if working:
                out.append(OpenRow(d, working[0], True, working[1]))
            continue
        last = _last_ts(path)
        fresh = bool(last) and (now - last).total_seconds() <= hours * 3600
        out.append(OpenRow(d, last, fresh, why))
    return out


def _mtime(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _process_age_s(pid):
    """Seconds since the process started (`ps -o etime=`), or None."""
    try:
        cp = subprocess.run(["ps", "-o", "etime=", "-p", str(int(pid))],
                            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None
    txt = cp.stdout.strip()
    if cp.returncode != 0 or not txt:
        return None
    days, _, hms = txt.rpartition("-")
    try:
        parts = [int(x) for x in hms.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return (int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2])
    except ValueError:
        return None


def _script_alive(ev, now):
    """True when the process of an open script event is still that script: it
    runs on this machine, answers kill(pid, 0) and is at least as old as the
    event (a reused pid is younger). Never raises."""
    try:
        if ev.get("machine") != machine_id() or not sibling("sampler").pid_alive(ev.get("pid")):
            return False
        age = _process_age_s(ev.get("pid"))
        since = (now.timestamp() - parse_z(ev.get("ts")))
        return age is None or age + 60 >= since
    except Exception:                                   # noqa: BLE001
        return False


def _work_event(line):
    """(event, ts) of a work line - valid JSON, a parseable ts, any kind but the
    sampler's `sample` - else None."""
    if _SAMPLE_B in line:                               # the sampler's own, not work
        return None
    try:
        e = json.loads(line)
        t = _parse_z_fast(e.get("ts"))
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None
    if e.get("kind") == "sample":
        return None
    return e, t


def _newest_work_ts(fh, size):
    """The newest ts of a work event of the file, read from its end: past a work
    event ORDER_SLACK_S older than the newest seen, none can be newer. A line
    whose opening ts is a second older than the newest seen is skipped unparsed."""
    best = best_s = stop_s = None
    for line in _reverse_lines(fh, size):
        if best is not None:
            m = _HEAD_TS_RE.match(line)
            if m:
                if m.group(1) < stop_s:
                    break
                if m.group(1) < best_s:
                    continue
        got = _work_event(line)
        if got is None:
            continue
        t = got[1]
        if best is None or t > best:
            best = t
            best_s = now_z(best)[:19].encode("ascii")
            stop_s = now_z(best - ORDER_SLACK_S)[:19].encode("ascii")
    return best


def _tail_bytes(fh, size, cutoff):
    """The end of the file from a line stamped before `cutoff` (a POSIX time; by
    the ts a line opens with, to the second) on - read back a chunk at a time;
    the chunk whose first full line is older than `cutoff` is the last one read.
    More lines than needed is harmless; a line with no such ts does not stop it."""
    edge = now_z(cutoff)[:19].encode("ascii")
    pos, parts = size, []
    while pos > 0:
        start = max(0, pos - _SCAN_CHUNK * 4)
        fh.seek(start)
        buf = fh.read(pos - start)
        parts.append(buf)
        pos = start
        first = buf if start == 0 else buf[buf.find(b"\n") + 1:]
        m = _HEAD_TS_RE.match(first)
        if m and m.group(1) < edge:
            break
    parts.reverse()
    return b"".join(parts)


def _lines_matching(data, rx, pos=0, literal=None):
    """(line, end) of every line of `data` from `pos` on in which `rx` matches.
    `literal`: bytes every such line holds - found first by a plain search,
    which is several times faster than the regex over the whole of `data`."""
    n = len(data)
    while True:
        if literal is not None:
            i = data.find(literal, pos)
            if i < 0:
                return
            a = data.rfind(b"\n", 0, i) + 1
            b = data.find(b"\n", i)
            b = n if b < 0 else b
            pos = b + 1
            if rx.search(data, a, b):
                yield data[a:b], b
            continue
        m = rx.search(data, pos)
        if not m:
            return
        a = data.rfind(b"\n", 0, m.start()) + 1
        b = data.find(b"\n", m.end())
        b = n if b < 0 else b
        yield data[a:b], b
        pos = b + 1


def _pid_answers(pid):
    """kill(pid, 0) only - no waitpid, which would reap a child of the caller."""
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError, OverflowError):
        return False


def _open_script_starts(data):
    """The script starts of `data` (whole lines of the end of a RUN_EVENTS file)
    that the full read of CF-0401 leaves open - the last start of its id, with no
    start/done/failed of that id after it - narrowed to the ones that can be
    alive: written on this machine, with a pid that answers. By bytes first, so
    that only those lines and the later lines holding their id are parsed."""
    me, answers = machine_id().encode(), {}
    for line, end in _lines_matching(data, _SCRIPT_RE, literal=b'"script"'):
        if b'"start"' not in line or me not in line or not _START_RE.search(line):
            continue
        pids = _PID_RE.findall(line)
        for p in pids:
            if p not in answers:
                answers[p] = _pid_answers(p)
        if not any(answers[p] for p in pids):
            continue
        got = _work_event(line)
        if got is None:
            continue
        ev = got[0]
        sid = ev.get("id")
        if ev.get("kind") != KIND_SCRIPT or not sid or ev.get("status") != ST_START:
            continue
        lit = json.dumps(sid).encode()
        superseded = False
        for later, _ in _lines_matching(data, re.compile(re.escape(lit)), end + 1, literal=lit):
            got = _work_event(later) if _SCRIPT_RE.search(later) else None
            if got and got[0].get("kind") == KIND_SCRIPT and got[0].get("id") == sid \
                    and got[0].get("status") in (ST_START, ST_DONE, ST_FAILED):
                superseded = True
                break
        if not superseded:
            yield ev


def _rebuild_working(path, now, hours):
    """CF-0401: the ts of the last work event of a rebuild that is working now,
    else None - `_rebuild_work` without its line for the user."""
    got = _rebuild_work(path, now, hours)
    return got[0] if got else None


def _rebuild_work(path, now, hours):
    """CF-0401: `(ts of the last work event, why)` of a rebuild that is working
    now (`why`: the line for the user, CF-0670), else None. A rebuild has no entry point that could open it - the orchestrator
    calls the editor's scripts one by one, and `batch-start` is a step it forgets
    (every rebuild since 2026-09-23T1053Z) - so this reads what the scripts write
    anyway. Working is the sampler's own rule for a run that is still alive
    (CF-0339), with no invented window: a script of the run is alive (start
    without done/failed, its pid alive on this machine and as old as the event),
    or the run wrote a work event (any kind but `sample`) within
    `sampler.IDLE_MINUTES`. An open script older than `hours` does not count.

    CF-0656: only the tail is read - the newest work event from the end, then
    the script starts since `now - hours` (see ORDER_SLACK_S) that can be alive;
    a rebuild whose newest work is older than `hours` is read no further."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            last = _newest_work_ts(fh, size)
            if last is None:
                return None
            idle_s = float(sibling("sampler").IDLE_MINUTES) * 60.0
            last_dt = datetime.fromtimestamp(last, tz=timezone.utc)
            ago = (now - last_dt).total_seconds()
            if ago <= idle_s:
                return last_dt, (f"пересборка работает: рабочее событие {ago / 60:.0f} мин назад "
                                 f"(CF-0401)")
            horizon = now.timestamp() - hours * 3600
            if last < horizon:                          # every script started before it
                return None
            data = _tail_bytes(fh, size, horizon - ORDER_SLACK_S)
    except OSError:
        return None
    for ev in _open_script_starts(data):
        try:
            if (now.timestamp() - parse_z(ev.get("ts"))) > hours * 3600:
                continue
        except (ValueError, TypeError, AttributeError, OverflowError):
            continue
        if _script_alive(ev, now):
            return last_dt, (f"пересборка работает: жив скрипт {ev.get('id')} "
                             f"(pid {ev.get('pid')}, CF-0401)")
    return None


def _open_stages(events):
    """Stages with a stage-start after their last stage-done, in order."""
    open_ = {}
    for e in events:
        if e.get("kind") != KIND_MARKER:
            continue
        if e.get("status") == M_STAGE_START:
            open_[e.get("stage")] = e
        elif e.get("status") == M_STAGE_DONE:
            open_.pop(e.get("stage"), None)
    return open_


def _stopcock(bdir):
    """CF-0322: the stop-cock verdict of this batch, or None when it cannot be
    read. Never raises - a marker must not fail because a module beside it did."""
    try:
        return sibling("stopcock").verdict(bdir)
    except Exception as e:                                  # noqa: BLE001
        _warn(f"stop-cock not read ({e.__class__.__name__}: {e})")
        return None


def _supplement(bdir, stage):
    """CF-0345: the supplement verdict when it refuses `stage-start <stage>`,
    else None. Never raises."""
    try:
        return sibling("supplement").blocks(stage, bdir)
    except Exception as e:                                  # noqa: BLE001
        _warn(f"supplement step not read ({e.__class__.__name__}: {e})")
        return None


def _plan_pending(bdir, stage, root=None):
    """CF-0422: the refusal while scripts deferred at step 6b owe the plan
    check after the supplement, else None. Never raises; cannot answer = None."""
    try:
        return sibling("supplement").plan_blocks(stage, bdir, root)
    except Exception as e:                                  # noqa: BLE001
        _warn(f"plan check after the supplement not read ({e.__class__.__name__}: {e})")
        return None


def _wait_incident(events, which, stage):
    """CF-0317: the wait this marker is about to close, or None.

    An autonomous run may not stand still, so the moment it starts moving again
    is the moment the standing still becomes a fact - and a fact is written
    where nobody has to remember to write it. Never raises, and never refuses:
    refusing here would stop a run that has already lost the time, which is the
    disease, not the cure."""
    try:
        return sibling("no_waiting").pending(events, which, stage)
    except Exception as e:                                  # noqa: BLE001
        _warn(f"wait incident not read ({e.__class__.__name__}: {e})")
        return None


def marker(which, stage=None, note=None, batch_dir=None, strict=True, root=None,
           anyway=None, rerun=None):
    """Write one marker event: batch-start | stage-start | stage-done | batch-done.

    batch-start carries the run header. With strict=True (the CLI) the order is
    checked - any marker before batch-start, or a stage-done without an open
    stage-start for that stage, raises RunlogError; strict=False only warns.
    stage may be null for batch-start/batch-done. Returns the event dict.

    CF-0322, the stop-cock: a batch whose Content Researcher wrote no script and
    that has no reserve topic left to substitute may open no further stage. The
    check sits here, on `stage-start`, rather than in a skill, because a rule
    written in prose is executed by whoever happens to be reading it (CF-0318).
    `stage-done` is deliberately not checked - the Researcher's own stage is
    still open when its artifact lands - and neither is `batch-done`, which is
    the one thing a stopped batch is supposed to do next. `anyway` is the
    override: it does not disable the check, it records it (`stopcock_override`
    in the event, and the reason is required), so an operator who had to go on
    leaves that in the statistics instead of editing an artifact to get past it.
    """
    if which not in MARKERS:
        raise RunlogError(f"unknown marker {which!r}; one of {', '.join(MARKERS)}")
    bdir = find_batch_dir(batch_dir)
    if bdir is None:
        raise RunlogError(f"no batch directory: pass --batch DIR, set {BATCH_ENV}, "
                          f"or run from inside pipeline/<channel>/<batch-id>")
    if which in (M_STAGE_START, M_STAGE_DONE) and not stage:
        raise RunlogError(f"{which} needs a stage name")
    if rerun is not None and (which != M_BATCH_START or rerun not in RERUN_MODES):
        raise RunlogError(f"--rerun {rerun!r}: only on batch-start, one of "
                          f"{', '.join(sorted(RERUN_MODES))} ({RERUN_TASK})")
    events = read_events(bdir)
    problems = []
    if which != M_BATCH_START:
        if not any(e.get("kind") == KIND_MARKER and e.get("status") == M_BATCH_START for e in events):
            problems.append(f"{which} before batch-start: no open run in {bdir} "
                            f"(run `runlog batch-start` first)")
        elif which == M_STAGE_DONE and stage not in _open_stages(events):
            problems.append(f"stage-done {stage}: no open stage-start for {stage!r} in {bdir}")
    cock = _stopcock(bdir) if which == M_STAGE_START else None
    if cock is not None and cock["state"] in sibling("stopcock").STOPPED and not anyway:
        problems.append(
            f"stage-start {stage}: the stop-cock is down (CF-0322) - {cock['reason']}. "
            f"Close the batch with `runlog batch-done`; to go on anyway, say why with "
            f"`--anyway REASON` and it is recorded")
    # CF-0345: the thin-pool supplement step sits between the Researcher and
    # the stages that read its pool; while a request waits or its sources owe
    # descriptions, those stages may not open. Same override as the cock.
    sup = _supplement(bdir, stage) if which == M_STAGE_START else None
    if sup is not None and not anyway:
        problems.append(
            f"stage-start {stage}: the thin-pool supplement step is {sup['state']} "
            f"(CF-0345) - {sup['reason']}; to go on anyway, say why with "
            f"`--anyway REASON` and it is recorded")
    # CF-0422: after the step, the scripts step 6b deferred for it are checked
    # again (`plan_check_loop.py --write --after-supplement`); until then the
    # same stages stay closed. Named only once the step itself is not in the
    # way - its command comes first.
    plan = _plan_pending(bdir, stage, root) if which == M_STAGE_START else None
    if plan is not None and sup is None and not anyway:
        problems.append(
            f"stage-start {stage}: {plan['reason']}; to go on anyway, say why with "
            f"`--anyway REASON` and it is recorded")
    # CF-0398 / CF-0479: a batch starts on a clean root (`main` or `release/*`)
    # with every agent on its pin of agents.lock.json.
    code = None
    if which == M_BATCH_START:
        try:
            code = code_check(bdir, root=root)
        except Exception as e:                              # noqa: BLE001
            _warn(f"code check not done ({e.__class__.__name__}: {e})")
        if code and code["problems"] and not anyway:
            problems.append(
                "batch-start refused (CF-0479): a batch runs on a clean root on `main` or "
                "`release/*` with every agent on its pin of agents.lock.json - "
                + "; ".join(code["problems"]) + ". Commit or move the changes and run "
                "`scripts/agents sync`, or say why with `--anyway REASON` and it is recorded")
    if problems:
        if strict:
            raise RunlogError("; ".join(problems))
        for p in problems:
            _warn(p)
    extra = {"note": note}
    # CF-0317: a stage-start or a batch-done that ends a silence of WAIT_MIN_S
    # or more carries what that silence was - the register entry it belongs to
    # and the code the automatic outcome should have written. It is attached
    # here, to the event, for the reason CF-0322 put the stop-cock here: a rule
    # that lives in prose is kept by whoever happens to be reading it.
    _inc = _wait_incident(events, which, stage)
    if _inc is not None:
        extra[sibling("no_waiting").EVENT_KEY] = _inc
    if anyway and which == M_STAGE_START:
        extra["stopcock_override"] = {"reason": anyway,
                                      "state": (cock or {}).get("state"),
                                      "was": (cock or {}).get("reason")}
    if anyway and which == M_STAGE_START and sup is not None:
        extra["supplement_override"] = {"reason": anyway, "state": sup["state"],
                                        "was": sup["reason"]}
    if anyway and which == M_STAGE_START and plan is not None:
        extra["plan_check_override"] = {
            "reason": anyway, "task": "CF-0422", "command": plan["command"],
            "pending": [r.get("script_id") for r in plan["pending"]]}
    if which == M_BATCH_START and rerun is not None:
        # CF-0494: set by the flag, here, once - the step reads it from this
        # event, so no record of a step has to be written by hand for it.
        extra[RERUN_KEY] = {"mode": RERUN_MODES[rerun], "flag": f"--rerun {rerun}",
                            "task": RERUN_TASK}
    if which == M_BATCH_START and code is not None:
        # CF-0398: what the check saw is kept whether it passed or not - a
        # skipped check (a run outside <root>/pipeline) says so instead of
        # looking like a clean main.
        extra[CODE_CHECK_KEY] = {"checked": code["checked"], "why": code["why"],
                                 "problems": code["problems"],
                                 "branches": {k: v.get("branch")
                                              for k, v in code["repos"].items()},
                                 CODE_LOCK_KEY: code.get("lock") or {}}
        if anyway and code["problems"]:
            extra[CODE_OVERRIDE_KEY] = {"reason": anyway, "was": code["problems"]}
    missing = _rebuild_record_missing(bdir, which, stage)
    if missing is not None:
        # CF-0416: a warning and a field, not a refusal - stage-done is never
        # refused on content (see the docstring), and the Editor's stage may
        # have ended on a refusal of every script, which is itself a record.
        _warn(missing["warning"])
        extra[REBUILD_RECORD_KEY] = missing
    if which != M_BATCH_START:
        # CF-0492: a marker called from another checkout than the batch's own
        # is said once per event, beside the drift read from the batch's tree.
        fc = foreign_checkout(events, root=root)
        if fc:
            extra[FOREIGN_CHECKOUT_KEY] = fc
            _warn(f"marker from a foreign checkout (CF-0492): the batch was opened in "
                  f"{fc['batch']}, this runlog runs from {fc['caller']}; the code drift is "
                  f"read from the batch's checkout")
    if which in (M_STAGE_START, M_STAGE_DONE):
        drift = code_drift(events, bdir, root=root)     # CF-0398: written, never refused
        if drift:
            extra[CODE_DRIFT_KEY] = drift
            for d in drift:
                _warn(f"code drift (CF-0398): {d['repo']} {d['was'][:12]} -> "
                      f"{d['now'][:12]} under the open batch {bdir}")
    if which == M_BATCH_DONE:
        # CF-0322 item 1: the batch closes *with a record*. It is written for
        # every close, not only a stopped one, so that "the cock was up" and
        # "nobody looked" are different answers in the events of a run.
        cock = _stopcock(bdir)
        if cock is not None:
            extra[sibling("stopcock").EVENT_KEY] = cock
    if which == M_BATCH_START:
        # CF-0230: the state of the window-percentage source as the run begins -
        # section 5 of the summary names from it why the run has no readings,
        # and the operator is told now, while a terminal session can still help.
        try:
            _lim = sibling("limits")
            extra[_lim.SOURCE_KEY] = _lim.source_state()
            _prob = _lim.source_problem(extra[_lim.SOURCE_KEY])
            if _prob:
                _warn(f"limits (CF-0230): {_prob} - unless a terminal session's statusline "
                      f"redraws during the run, section 5 of the summary will have no window share")
        except Exception as e:                              # noqa: BLE001
            _warn(f"limits source not probed ({e.__class__.__name__}: {e})")
    if which == M_BATCH_START:
        try:
            extra["header"] = header(bdir, root=root)
            if code is not None and code.get("checked"):
                extra["header"][HEADER_LOCK_KEY] = code.get("lock") or {}   # CF-0479
        except Exception as e:
            _warn(f"header incomplete ({e.__class__.__name__}: {e})")
            extra["header"] = {"error": _error_text(e)}
    ev = emit(bdir, KIND_MARKER, stage, status=which, **extra)
    _accounting_layer(which, bdir)
    return ev


# CF-0416: a rebuild (`pipeline/rebuilds/<ts>`) writes its own
# `05-video-editor.json` with the Editor's code (`write_batch_metadata.py
# pipeline/rebuilds/<ts> --video ...`). On 0929Z it had none, and the frame
# judge's operators were told to hand-assemble one - with `qc.passed: true` -
# so the gate would run. A rebuild's video-editor stage that closes with no
# record says so at the moment it closes, while the operator can still write it.
REBUILD_RECORD_KEY = "rebuild_record_missing"
REBUILD_GROUP = "rebuilds"
REBUILD_RECORDS = {"video-editor": "05-video-editor.json"}


def _rebuild_record_missing(bdir, which, stage):
    """None, or `{"stage", "file", "warning"}` for a rebuild stage-done whose
    record is not on disk."""
    if which != M_STAGE_DONE or stage not in REBUILD_RECORDS:
        return None
    try:
        if Path(bdir).resolve().parent.name != REBUILD_GROUP:
            return None
    except OSError:
        return None
    name = REBUILD_RECORDS[stage]
    if (Path(bdir) / name).is_file():
        return None
    return {"stage": stage, "file": name,
            "warning": (f"stage-done {stage}: this rebuild has no {name} of its own (CF-0416) - "
                        f"write it with the Editor's code: `python3 agents/video-editor/scripts/"
                        f"write_batch_metadata.py {bdir} --video <script_id> "
                        f"work/<slug>/plan.json videos/<slug>.mp4`; the frame judge reads "
                        f"nothing else, and nobody assembles it by hand")}


# CC-0039: the command center's API calls into runlog from a threadpool; two
# first calls of `sibling("sampler")` at once handed the second one the module
# the first was still executing (`module 'sampler' has no attribute
# 'MAX_HOURS'`). One loader at a time; reentrant, as a sibling may load another.
_SIBLING_LOCK = threading.RLock()


def sibling(name):
    """Import a module that lives beside this file (sampler, limits, gaps), whether
    this module was imported as `runlog` or as `shared.runlog.runlog`.

    Thread-safe: a module another thread is still executing is not handed out -
    here the lock is held until it is done, a plain import is waited for."""
    import importlib
    import importlib.util
    with _SIBLING_LOCK:
        mod = sys.modules.get(name)
        if mod is not None and getattr(getattr(mod, "__spec__", None), "_initializing", False):
            return importlib.import_module(name)    # a plain import running: wait for it
        if mod is not None:
            return mod
        path = Path(__file__).resolve().parent / f"{name}.py"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod
        except Exception:
            sys.modules.pop(name, None)
            return importlib.import_module(name)


def active_batch_file():
    return _state_dir() / ACTIVE_BATCH_FILE


NOT_A_BATCH = ("rebuilds", "backfill")   # CF-0339: pipeline/<these>/<ts> is a run, not a batch


def not_a_batch(bdir):
    """True for `pipeline/rebuilds/<ts>` and `pipeline/backfill/<ts>`: instrumented
    runs that are deliberately not batches (CF-0330, CF-0350), so no batch-done
    marker ever closes them."""
    try:
        return Path(bdir).resolve().parent.name in NOT_A_BATCH
    except OSError:
        return False


def _accounting_layer(which, bdir):
    """CF-0108: the sampler daemon follows the markers, the state dir names the
    active batch for the user-level hooks (statusline_hook.py, limit_hook.py).
    Never raises."""
    try:
        sampler = sibling("sampler")
        if which in (M_BATCH_START, M_STAGE_START):
            if which == M_BATCH_START or not sampler.running(bdir):
                sampler.start(bdir)
        elif which == M_BATCH_DONE:
            sampler.stop(bdir)
        elif which == M_STAGE_DONE and not_a_batch(bdir):
            # CF-0339: a rebuild ends on its last stage-done - batch-done would run the
            # whole close of a batch (summary, runs table, prices) on something that is
            # not one, so nobody sends it and the sampler of the rebuild of 2026-09-23
            # kept writing into a finished run for a day. Its stages close it instead;
            # the next stage-start starts a fresh daemon.
            sampler.stop(bdir)
    except Exception as e:
        _warn(f"sampler not toggled ({e.__class__.__name__}: {e})")
    if which == M_BATCH_DONE:                       # CF-0110: the summary and the runs table
        try:                                        # CF-0172: count the tokens BEFORE the summary,
            sibling("usage").refresh(bdir)          # so section 4 carries numbers, not a to-do
        except Exception as e:                      # a failed scan must not cost the run its summary
            _warn(f"usage not counted ({e.__class__.__name__}: {e}); "
                  f"RUN_SUMMARY.md section 4 will say so")
        try:
            sibling("summary").write(bdir)
        except Exception as e:
            _warn(f"RUN_SUMMARY.md not written ({e.__class__.__name__}: {e})")
        try:
            rt = sibling("runs_table")
            rt.append(rt.row(bdir))
        except Exception as e:
            _warn(f"runs table not updated ({e.__class__.__name__}: {e})")
    try:
        state = active_batch_file()
        if which == M_BATCH_START:
            state.parent.mkdir(parents=True, exist_ok=True)
            tmp = state.with_suffix(".tmp")
            tmp.write_text(str(Path(bdir).resolve()) + "\n")
            os.replace(tmp, state)
        elif which == M_BATCH_DONE and state.is_file():
            if state.read_text().strip() == str(Path(bdir).resolve()):
                state.unlink()
    except Exception as e:
        _warn(f"active-batch not updated ({e.__class__.__name__}: {e})")


# --------------------------------------------------------------------------
# RUN_LOG.txt from events
# --------------------------------------------------------------------------

def _hms(seconds):
    if seconds is None:
        return "?"
    s = float(seconds)
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(int(round(s)), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m}m{sec:02d}s"


def _hdr_line(h):
    if not h or "error" in h:
        return None
    git = h.get("git") or {}
    root = (git.get("root") or {}).get("commit")
    parts = [f"version={h.get('version')}", f"root={root[:12] if root else None}"]
    agents = git.get("agents") or {}
    ag = ",".join(f"{n}:{(v or {}).get('commit', '')[:12] or 'null'}" for n, v in agents.items())
    if ag:
        parts.append(f"agents={ag}")
    c = h.get("counts") or {}
    parts.append(f"topics={c.get('topics')} sources={c.get('sources')} videos={c.get('videos')}")
    m = h.get("models") or {}
    parts.append(f"operator={m.get('operator')}")
    subs = m.get("subagents") or {}
    if subs:
        parts.append("subagents=" + ",".join(f"{k}:{v}" for k, v in subs.items()))
    mf = h.get("machine") or {}
    parts.append(f"cpu={mf.get('cpu')!s} x{mf.get('cpu_count')} ram={mf.get('ram_gb')}G "
                 f"gpu={mf.get('gpu')} os={mf.get('os')}")
    return "  " + " ".join(parts)


def _label(e):
    """'video-editor/render lisa-and-kirby attempt 2' style label of a script/child event."""
    bits = []
    if e.get("kind") == KIND_CHILD:
        return e.get("tool") or "child"          # nested under its parent, which carries slug/attempt
    else:
        stage, step, name = e.get("stage"), e.get("step"), e.get("name")
        head = f"{stage}/{step}" if stage and step else (stage or step or name or "?")
        bits.append(head)
        if name and name not in head:
            bits.append(f"({name})")
    if e.get("video"):
        bits.append(e["video"])
    if e.get("attempt") is not None:
        bits.append(f"attempt {e['attempt']}")
    return " ".join(bits)


def render_runlog(batch_dir):
    """Human-readable RUN_LOG.txt text from the batch's events, all times UTC (Z).

    Line shapes (token first, then the stage, so `grep '^STAGE_DONE <stage>'`
    still works the way it did on the hand-written log):

        BATCH_START <channel>/<batch> <ts> machine=<id> [note]
          version=… root=… agents=… topics=… sources=… videos=… operator=… cpu=… ram=… gpu=… os=…
        STAGE_START <stage> <ts> [note]
          <stage>/<step> [slug] [attempt N] done|failed <ts> <duration> [Error: msg]
            <tool> done|failed <duration> [rc=N] [Error: msg]        (children, under their parent)
          <stage>/<step> … started <ts> (no end recorded)
        STAGE_DONE <stage> <ts> <duration since stage-start> [note] [tokens=in/cw/cr/out calls=N]
        BATCH_DONE <channel>/<batch> <ts> <duration since batch-start> [note] [tokens=… calls=N]
                                                    (CF-0109: from the newest `usage` events)
        GAP <start> <end> <dur> cause=limit|idle_exit|<step>_timeout|unknown after '…' before '…' (evidence)
                                                    (CF-0108: gaps.detect, silences > 10 min)
    """
    events = read_events(batch_dir)
    bd = Path(batch_dir)
    out = [GENERATED_BANNER]
    if not events:
        out.append(f"(no events in {events_path(bd)})")
        return "\n".join(out) + "\n"
    # pair start/end by id
    ends = {e["id"]: e for e in events if e.get("kind") in (KIND_SCRIPT, KIND_CHILD)
            and e.get("status") in (ST_DONE, ST_FAILED) and e.get("id")}
    children = {}
    for e in events:
        if e.get("kind") == KIND_CHILD and e.get("status") == ST_START:
            children.setdefault(e.get("parent"), []).append(e)
    seen_child = set()
    started = {}
    stage_started = {}
    batch_started = None
    name = f"{bd.parent.name}/{bd.name}"
    try:
        gaps_mod = sibling("gaps")
        pending_gaps = gaps_mod.detect(bd, events=events)
    except Exception as e:
        _warn(f"gaps not detected ({e.__class__.__name__}: {e})")
        gaps_mod, pending_gaps = None, []
    try:
        usage_mod = sibling("usage")
        usage_by_stage = usage_mod.stage_totals(events)
        usage_all = usage_mod.stage_totals([e for e in events if e.get("kind") != "usage"] +
                                           [dict(e, stage="*") for e in events if e.get("kind") == "usage"])
        tok = usage_mod.tokens_suffix
    except Exception as e:
        _warn(f"usage not read ({e.__class__.__name__}: {e})")
        usage_by_stage, usage_all, tok = {}, {}, (lambda st: "")

    def fmt_end(e, indent):
        end = ends.get(e["id"])
        if end is None:
            return f"{indent}{_label(e)} started {e['ts']} (no end recorded)"
        line = f"{indent}{_label(e)} {end['status']} {end['ts']} {_hms(end.get('duration_s'))}"
        if e.get("kind") == KIND_CHILD and end.get("rc") not in (None, 0):
            line += f" rc={end['rc']}"
        if end.get("error"):
            line += f" {end['error']}"
        return line

    for e in events:
        kind, status = e.get("kind"), e.get("status")
        while pending_gaps and pending_gaps[0]["end"] <= (e.get("ts") or ""):
            out.append(gaps_mod.format_gap(pending_gaps.pop(0)))
        if kind == KIND_MARKER:
            note = f" {e['note']}" if e.get("note") else ""
            ts = e.get("ts")
            if status == M_BATCH_START:
                batch_started = ts
                out.append(f"BATCH_START {name} {ts} machine={e.get('machine')}{note}")
                hl = _hdr_line(e.get("header"))
                if hl:
                    out.append(hl)
            elif status == M_STAGE_START:
                stage_started[e.get("stage")] = ts
                out.append(f"STAGE_START {e.get('stage')} {ts}{note}")
            elif status == M_STAGE_DONE:
                t0 = stage_started.pop(e.get("stage"), None)
                dur = _hms(parse_z(ts) - parse_z(t0)) if t0 else "?"
                out.append(f"STAGE_DONE {e.get('stage')} {ts} {dur}{note}"
                           f"{tok(usage_by_stage.get(e.get('stage')))}")
            elif status == M_BATCH_DONE:
                dur = _hms(parse_z(ts) - parse_z(batch_started)) if batch_started else "?"
                out.append(f"BATCH_DONE {name} {ts} {dur}{note}{tok(usage_all.get('*'))}")
        elif kind == KIND_SCRIPT and status == ST_START:
            out.append(fmt_end(e, "  "))
            for c in children.get(e["id"], []):
                seen_child.add(c["id"])
                out.append(fmt_end(c, "    "))
        elif kind == KIND_CHILD and status == ST_START and e["id"] not in seen_child \
                and e.get("parent") not in started:
            # orphan child (no enclosing instrumented script)
            out.append(fmt_end(e, "  "))
        if kind == KIND_SCRIPT and status == ST_START:
            started[e["id"]] = e
    for g in pending_gaps:
        out.append(gaps_mod.format_gap(g))
    return "\n".join(out) + "\n"


def is_generated(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readline().startswith("# RUN_LOG.txt - generated")
    except OSError:
        return False


def write_runlog(batch_dir, force=False):
    """Render and write RUN_LOG.txt. A hand-written RUN_LOG.txt (no generated
    banner) is not overwritten unless force=True: the text goes to
    RUN_LOG.generated.txt instead and the returned path says so."""
    text = render_runlog(batch_dir)
    target = runlog_path(batch_dir)
    if target.exists() and not force and not is_generated(target):
        target = Path(batch_dir) / "RUN_LOG.generated.txt"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return target


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

USAGE = """usage:
  runlog batch-start [<stage>] [--batch DIR] [--note TEXT] [--anyway REASON] [--rerun no-search]
                                       (CF-0398/CF-0479: exit 2 unless the root is on main or
                                        release/*, every agent of agents.lock.json sits on the
                                        commit its pin resolves to, and no tracked file is
                                        modified or staged (untracked never counts; the root's
                                        records - pipeline/, rotation/ledger/, tasks/, publish/,
                                        docs/, ROADMAP/CHANGELOG/README/IDEAS.md - are not code).
                                        The resolved pins go into code_check.lock and the header.
                                        --anyway REASON starts anyway and writes code_override.
                                        Checked only for a batch under <root>/pipeline/)
                                        --rerun no-search (CF-0494): a verification rerun that
                                        may not search or fetch - the thin-pool supplement step
                                        closes every request skipped rerun_no_search.
  runlog stage-start <stage>   [--batch DIR] [--note TEXT] [--anyway REASON]
  runlog stage-done  <stage>   [--batch DIR] [--note TEXT]
                                       (CF-0398: both compare every repo's HEAD with the header
                                        and write a move as code_drift on the event - never refused;
                                        CF-0479: a root move that touches only records is no drift)
  runlog question --note TEXT  [--batch DIR]
                                       (CF-0494: the orchestrator asked the user mid-run - a
                                        `question` event; the wait it begins is read as the
                                        register point orchestrator_question_mid_run, still an
                                        incident. Ask before batch-start instead.)
  runlog batch-done  [<stage>] [--batch DIR] [--note TEXT]
  runlog batch-active [--root DIR] [--hours H]
                                       (CF-0398: exit 0 and the directory of every open batch -
                                        batch-start without batch-done, or a rebuild with an open
                                        stage or still working (CF-0401: a live script of it, or
                                        a work event within sampler.IDLE_MINUTES) - one per line on stdout; exit 1 when none. An open
                                        batch silent for more than H hours (default
                                        sampler.MAX_HOURS = 24) is stale: named on stderr, not
                                        counted. The auto-dev driver moves `main` only on exit 1)
  runlog release-tag [--root DIR] [--json]
                                       (CF-0716: the latest release tag (v<n>.<n>...) reachable
                                        from main - by version order; exit 1 when there is none)
  runlog render [--batch DIR] [--force] [--stdout]
  runlog tail   [--batch DIR] [-n N]
  runlog header [--batch DIR]          (print the run header as JSON, write nothing)
  runlog gaps   [--batch DIR] [--transcript FILE]... [--session ID]... [--min-gap S] [--json] [--write]
                                       (CF-0108: silences > 10 min and their cause)
  runlog sampler start|stop|status [--batch DIR]      (CF-0108: the resource sampler daemon)
  runlog usage  <batch DIR> [--transcripts DIR] [--session ID]... [--write] [--json]
                                       (CF-0109: tokens per stage x model x role from transcripts)
  runlog summary [--batch DIR] [--stdout] [--json]
                                       (CF-0110: RUN_SUMMARY.md - the six DoD answers plus the topic
                                        funnel; batch-done writes it)
  runlog scene-holds [--batch DIR] [--dry-run] [--no-notify] [--json]
                                       (CF-0846: lift the publication holds whose content-sensitivity
                                        flags all rest on a scene the batch's scripts did not take -
                                        resolved_reason_code flagged_scene_not_in_script, a line to the
                                        user (notify kind hold_released); a hold this rule lifted is put
                                        back when a later script takes the flagged scene. The plan's
                                        close stage scene-holds. Exit 1 = the ledger or the batch could
                                        not be read, nothing lifted)
  runlog stopcock [--batch DIR] [--json]
                                       (CF-0322: is there anything left to do after the Content
                                        Researcher? `stop` when it wrote no script and there is no
                                        reserve topic left to substitute - and then `stage-start` is
                                        refused for every stage until `batch-done`. Exit 3 when the
                                        cock is down, 0 while the batch may go on)
  runlog watchdog [--batch DIR] [--json]
                                       (CF-0316: the operations this run lost to the watchdog - one
                                        source taken down for silence past its ceiling, the run
                                        itself never dropped. Every line is an авария by CF-0319)
  runlog no-waiting [--batch DIR] [--json] [--list] [--dod] [--since DAY]
                                       (CF-0317: in an autonomous run no stage waits for a human.
                                        --list is the register - every place a stage can block on a
                                        person, and the automatic outcome with its code that replaces
                                        the question; with no flag it reads this batch's own waits
                                        (measured by CF-0252, never re-measured here) and exits 3 when
                                        a run started on or after the rule's epoch stood still; --dod
                                        answers DoD 1 over pipeline/runs.jsonl)
  runlog funnel [--batch DIR] [--json]
                                       (CF-0232: the topic funnel of one batch - selected -> after
                                        compliance -> with two sources -> scripts -> ready, a reason
                                        code on every loss. Section 7 of the summary on its own, read
                                        from the stage artifacts and not from the events)
  runlog scores [--batch DIR] [--json]
                                       (CF-0434: the score line of every video of one batch -
                                        after the judge where it ran, else after QC; the line of a
                                        video the score stopped at 6b or at the Editor. The block
                                        the summary prints under its headlines)
  runlog gate-price [--rule NAME]... [--window N] [--before DAY] [--pool DIR] [--json] [--write]
                                       (CF-0320: what a refusal would have cost. Replays a rule over
                                        the frozen artifacts of the last 5 batches and answers with
                                        the number of already-ready videos it would have killed;
                                        exit 1 when any rule may not land as a refusal)
  runlog monitors [--batch DIR] [--root DIR] [--root-only] [--file-ceiling S] [--ceiling S]
                  [--dry-run] [--json]
                                       (CF-0511: the live monitors, a step of the close - after
                                        batch-done, before triage. Runs every file the registries
                                        name (tests/_real_batches.py LIVE_MONITORS under
                                        ROOT_TESTS_LIVE=1, each agent's tests/_live_monitors.py
                                        under its LIVE_ENV) under a ceiling per file (600 s) and
                                        for the step (1800 s); writes a `monitors` event,
                                        MONITORS.txt and re-writes RUN_SUMMARY.md. Exit 0 all
                                        green, 1 any not green, 2 no batch or before batch-done)
  runlog triage [--batch DIR] [--tasks DIR] [--milestone M] [--dry-run] [--json]
                                       (CF-0319: the post-run triage, after batch-done - the run
                                        itself files no task. Sorts the run's events into авария
                                        (crash, watchdog kill, broken artifact, broken contract
                                        between stages, a refusal in force without a signed
                                        price - the gate-price step of CF-0320 runs every time)
                                        and topic losses (funnel codes: numbers, never tasks);
                                        files one task per авария key into tasks/ + INDEX.md
                                        with no human signature, writes TRIAGE.md in the batch.
                                        Exit 1 when there is an авария, 2 before batch-done)
  runlog acceptance [--ask CHANNEL/BATCH SLUG...] [--record CHANNEL/BATCH/SLUG --verdict V
                    --answer TEXT [--reason ...] [--reason-code C] [--write [--commit --by WHO]]]
                    [--commit-pending] [--reasons] [--check] [--state CHANNEL/BATCH/SLUG] [--json]
                    [--enqueue-accepted [--entry CHANNEL/BATCH/SLUG ...] [--other-version-ok]
                     [--apply --by WHO --via WHAT [--base-sha256 H]] [--root DIR]]
                                       (CF-0328: the user's acceptance of a video, recorded
                                        under the name of the video in publish/acceptance-log.json.
                                        --ask shows the files by name and numbers nothing; --record
                                        refuses a verdict whose answer does not name the video (the
                                        misattribution of 2026-09-22); --reasons is the dictionary
                                        of refusals with the repeatability rule of CF-0319; --check
                                        reads publish/ back against the record, exit 1 on a video
                                        there that the record does not stand behind; --state answers
                                        the verdict and the CF-0318 hold separately, exit 1 when the
                                        video is not publishable. Nothing here uploads anything -
                                        the button is a human's, CF-0018. CF-0675: --commit makes
                                        the verdict one git commit of the record, or - under an
                                        open batch - queues it in publish/acceptance-pending.jsonl;
                                        --commit-pending applies the queue as one commit.
                                        CF-0738: an accepted verdict also copies the render into
                                        publish/<channel>/_queue/ (publish_path in the same commit);
                                        --enqueue-accepted finds accepted rows with no place and
                                        does the same - a dry run unless --apply)
  runlog pool-release [--root DIR] [--json] [--variants] [--stale-days N] [--withdrawn CHANNEL/BATCH/SLUG]
                      [--delete] [--record-withdrawal CHANNEL/BATCH/SLUG --answer TEXT]
                                       (CF-0358: sources of topics whose video is published or
                                        withdrawn leave shared/footage/ - only when no other live
                                        topic references them. Plan by default; --delete removes
                                        them and writes shared/footage/release-log.jsonl, refused
                                        while a batch is open)
  runlog profile [--fill [--refresh] [--dry-run]] [--root DIR] [--json]
                                       (CF-0440: fact kind and source, pattern/rhythm, hook opener,
                                        tier and score of each accepted video - field `profile` on
                                        its row of publish/acceptance-log.json, read from the
                                        batch's 03/05/06; --fill writes it on rows filed before
                                        CF-0440 and the line under "## Профиль ролика" in
                                        publish/<channel>/<day>/<slug>.md; --root reads another data root)
  runlog publish where SLUG [--channel C] [--day D] | assign SLUG [--channel C] [--day D]
                 [--apply] | migrate [--root DIR] [--day SLUG=D ...] [--channel SLUG=C ...]
                 [--apply] [--json]
                                       (CF-0475: publish/ by channel and by the day a video goes
                                        out - publish/<channel>/<YYYY-MM-DD>/<slug>.mp4+.md, Moscow
                                        day of the note's "## Публикация"; publish/<channel>/_queue/
                                        without a slot; journals at the root. where - the pair of
                                        a name (a day tells two versions apart); assign - _queue/
                                        -> its day, README row and publish_path follow; migrate -
                                        the flat layout into channels and days (notes by git mv).
                                        Both print a plan without --apply)
  runlog diversity [--last N] [--channel ID] [--root DIR] [--json]
                                       (CF-0440: share of each fact kind, pattern, rhythm and hook
                                        opener over the last N videos the user accepted - how
                                        uniform the feed is; --channel one channel's feed, CF-0719;
                                        a broken acceptance log - exit 2 naming it)
  runlog runs [--batch DIR] [--rebuild] [--root DIR]
                                       (CF-0110: one row per run in pipeline/runs.jsonl + RUNS.md)
  runlog backfill <batch DIR> [--out DIR] [--root DIR] [--transcripts DIR] [--session ID]... [--no-table]
                                       (CF-0111: a hand-written RUN_LOG.txt -> synthetic events + summary + a
                                        row marked `manual-runlog`; nothing is written into the batch dir)

<stage> is an agent of the pipeline, or one of the stages that are nobody's turn
(`runlog.NON_AGENT_STAGES`):

  pool-maintenance  (CF-0173) the pool-wide work that runs before the first agent
                    - the caption-cache freshness check and the remeasures that
                    clear it. It gets its markers even when the pool is fresh and
                    the stage is a second long, so that the summary shows a zero
                    instead of a silence.
  thin-pool-supplement
                    (CF-0345) after the content-researcher, when its pool gates
                    laid requests in work/supplement-requests/: hunter ->
                    indexer -> descriptions -> sieve -> the pool gates again,
                    driven by scripts/thin_pool_supplement.py. Until it is done,
                    stage-start of compliance-checker / video-editor /
                    frame-judge / publisher is refused (exit 2, --anyway).
                    (CF-0422) Then, while scripts step 6b deferred for the step
                    owe `plan_check_loop.py <batch> --write --after-supplement`
                    (content-researcher --pending-after-supplement says 1), the
                    same stages are refused the same way.
  frame-judge       (CF-0298) the frame judge, after video-editor and before the
                    batch is closed: an LLM operator reads the finished frames
                    against the narration (DoD item 3) and
                    scripts/frame_judge_gate.py writes 06-frame-judge.json. The
                    funnel counts `ready` after it.

Run the scripts of such a stage under RUNLOG_STAGE=<stage>: that relabels their
`script`/`child` events (which otherwise say `footage-indexer` or `video-editor`,
whose code they are) without touching markers.

--batch DIR defaults to $RUNLOG_BATCH, then the batch that contains the current
directory. Markers re-render RUN_LOG.txt after writing (a hand-written
RUN_LOG.txt is left alone and RUN_LOG.generated.txt is written instead).
Exit 2 on a marker out of order or without a batch."""


def _batch_active_main(ap, rest):
    """CF-0398: exit 0 and the directory of every open batch (one per line on
    stdout; why it is open on stderr, CF-0670) when a batch is open now; exit 1
    when none is. An open batch whose
    last event is older than --hours (default sampler.MAX_HOURS) is stale: it
    is named on stderr and does not count."""
    ap.add_argument("--root", default=None, help="factory root (default: this checkout)")
    ap.add_argument("--hours", type=float, default=None,
                    help="an open batch silent longer than this is stale "
                         "(default: sampler.MAX_HOURS)")
    ns = ap.parse_args(rest)
    hours = ns.hours if ns.hours is not None else float(sibling("sampler").MAX_HOURS)
    now = datetime.now(timezone.utc)
    rows = open_batches(ns.root, now=now, hours=hours)
    fresh = [r for r in rows if r[2]]
    for r in fresh:
        print(r[0])
        why = getattr(r, "why", None)
        if why:
            sys.stderr.write(f"runlog batch-active: open: {r[0]} - {why}\n")
    for d, last, ok in rows:
        if ok:
            continue
        ago = f"{(now - last).total_seconds() / 3600:.0f} h ago" if last else "never"
        sys.stderr.write(f"runlog batch-active: stale, not counted: {d} (open, last event "
                         f"{ago}, over the {hours:g} h bound)\n")
    if not fresh:
        sys.stderr.write("runlog batch-active: no open batch\n")
    return 0 if fresh else 1


def main(argv=None):
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"runlog {cmd}", add_help=True)
    ap.add_argument("--batch", default=None)
    if cmd in MARKERS:
        ap.add_argument("stage", nargs="?" if cmd in (M_BATCH_START, M_BATCH_DONE) else None)
        ap.add_argument("--note", default=None)
        ap.add_argument("--no-render", action="store_true")
        # CF-0322: not a switch that turns the stop-cock off - a reason that is
        # written into the event beside the verdict it went past.
        ap.add_argument("--anyway", default=None, metavar="REASON")
        if cmd == M_BATCH_START:
            # CF-0494: what a verification rerun may not do, said before it starts.
            ap.add_argument("--rerun", default=None, choices=sorted(RERUN_MODES))
        ns = ap.parse_args(rest)
        try:
            ev = marker(cmd, stage=ns.stage, note=ns.note, batch_dir=ns.batch, strict=True,
                        anyway=ns.anyway, rerun=getattr(ns, "rerun", None))
            if ev is None:
                raise RunlogError("event not written (see stderr)")
        except RunlogError as e:
            sys.stderr.write(f"runlog: error: {e}\n")
            return 2
        bdir = find_batch_dir(ns.batch)
        print(f"{cmd} {ns.stage or ''} {ev['ts']} -> {events_path(bdir)}".replace("  ", " "))
        if not ns.no_render:
            try:
                write_runlog(bdir)
            except OSError as e:
                _warn(f"RUN_LOG.txt not rendered ({e})")
        return 0
    if cmd == "render":
        ap.add_argument("--force", action="store_true")
        ap.add_argument("--stdout", action="store_true")
        ns = ap.parse_args(rest)
        bdir = find_batch_dir(ns.batch)
        if bdir is None:
            sys.stderr.write("runlog: error: no batch directory (use --batch DIR)\n")
            return 2
        if ns.stdout:
            sys.stdout.write(render_runlog(bdir))
        else:
            print(write_runlog(bdir, force=ns.force))
        return 0
    if cmd == "question":
        ap.add_argument("--note", required=True, help="the question, as asked")
        ap.add_argument("--no-render", action="store_true")
        ns = ap.parse_args(rest)
        try:
            ev = question(ns.note, batch_dir=ns.batch)
        except RunlogError as e:
            sys.stderr.write(f"runlog: error: {e}\n")
            return 2
        bdir = find_batch_dir(ns.batch)
        print(f"question {ev['ts']} -> {events_path(bdir)}")
        if not ns.no_render:
            try:
                write_runlog(bdir)
            except OSError as e:
                _warn(f"RUN_LOG.txt not rendered ({e})")
        return 0
    if cmd == "tail":
        ap.add_argument("-n", type=int, default=20)
        ns = ap.parse_args(rest)
        bdir = find_batch_dir(ns.batch)
        if bdir is None:
            sys.stderr.write("runlog: error: no batch directory (use --batch DIR)\n")
            return 2
        for e in read_events(bdir)[-ns.n:]:
            print(json.dumps(e, ensure_ascii=False))
        return 0
    if cmd == "header":
        ns = ap.parse_args(rest)
        bdir = find_batch_dir(ns.batch) or Path.cwd()
        print(json.dumps(header(bdir), ensure_ascii=False, indent=2))
        return 0
    if cmd == "batch-active":
        return _batch_active_main(ap, rest)
    if cmd == "release-tag":
        ap.add_argument("--root", default=None, help="factory root (default: this checkout)")
        ap.add_argument("--json", action="store_true")
        ns = ap.parse_args(rest)
        tag = release_tag(ns.root)
        if ns.json:
            print(json.dumps({"release_tag": tag}))
        elif tag:
            print(tag)
        else:
            sys.stderr.write("runlog release-tag: no release tag on main\n")
        return 0 if tag else 1
    if cmd == "gaps":
        return sibling("gaps").main(rest)
    if cmd == "usage":
        return sibling("usage").main(rest)
    if cmd == "summary":
        return sibling("summary").main(rest)
    if cmd == "funnel":
        return sibling("funnel").main(rest)
    if cmd == "scores":
        return sibling("scores").main(rest)
    if cmd == "stopcock":
        return sibling("stopcock").main(rest)
    if cmd == "no-waiting":
        return sibling("no_waiting").main(rest)
    if cmd == "watchdog":
        return sibling("watchdog").main(rest)
    if cmd == "gate-price":
        return sibling("gate_price").main(rest)
    if cmd == "monitors":
        return sibling("monitors").main(rest)
    if cmd == "triage":
        return sibling("triage").main(rest)
    if cmd == "acceptance":
        return sibling("acceptance").main(rest)
    if cmd in ("profile", "diversity"):
        return sibling("publish_profile").main([cmd] + rest)
    if cmd == "publish":
        return sibling("publish_layout").main(rest)
    if cmd == "pool-release":
        return sibling("pool_release").main(rest)
    if cmd == "scene-holds":
        return sibling("scene_holds").main(rest)
    if cmd == "runs":
        return sibling("runs_table").main(rest)
    if cmd == "backfill":
        return sibling("backfill").main(rest)
    if cmd == "sampler":
        ap.add_argument("action", choices=("start", "stop", "status"))
        ns = ap.parse_args(rest)
        bdir = find_batch_dir(ns.batch)
        if bdir is None:
            sys.stderr.write("runlog: error: no batch directory (use --batch DIR)\n")
            return 2
        smp = sibling("sampler")
        if ns.action == "start":
            pid = smp.start(bdir)
            print(f"sampler pid {pid} for {bdir}" if pid else "sampler not started")
            return 0 if pid else 1
        if ns.action == "stop":
            print("sampler stopped" if smp.stop(bdir) else "sampler was not running")
            return 0
        pid = smp.running(bdir)
        print(f"sampler pid {pid} alive" if pid else "sampler not running")
        return 0
    sys.stderr.write(f"runlog: unknown command {cmd!r}\n{USAGE}\n")
    return 2



# CF-0541: before anything here can start a child, the inherited batch path is
# absolute - a child with another `cwd` must not read it from there.
normalize_batch_env()


if __name__ == "__main__":
    sys.exit(main())

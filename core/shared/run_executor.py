#!/usr/bin/env python3
"""CF-0203 (closes CF-0095): the executor of a channel's run plan, and the
state file a run resumes from.

The plan (`channels/<channel>.json` -> `run_plan`, read and refused only by
`shared/run_plan.py`, CF-0202) says which stages a batch has and in what
order. This program walks it. What it takes off the LLM operator is the
waiting and the memory, not the judgement:

    launch a process, wait for it, write a marker,   -> this program
    take the next stage from the plan
    remember where the run stopped                   -> <batch>/run-state.json
    work a stage by its SKILL.md, answer a decision  -> `claude -p` (an LLM)

    python3 shared/run_executor.py run <channel> [--batch DIR] [--until STAGE] [--dry-run]
    python3 shared/run_executor.py run <channel> --resume DIR [--until STAGE]
    python3 shared/run_executor.py status DIR

**Machine steps are processes of their own.** Each one is started through a
small wrapper (`_exec`) in a new session (its own process group, no terminal),
with its output in `<batch>/logs/<run key>.log`; the wrapper writes the exit
code to `<run key>.exit` when the command ends. The executor only polls - the
pid (checked against the command line, so a reused pid is not mistaken for
it) and the exit file. Killing the executor, or the session that started it,
does not touch the step: it runs to its end and leaves its exit code on disk.

**LLM stages** run `claude -p` the same way - a process with a log and an
exit file - so a three-hour Indexer survives a dead executor too. The command
is built in one place, `claude_stage_argv()`; the prompt (stage, channel,
batch, the SKILL path and its arguments, who writes the markers) goes in on
stdin. **Decisions** (`decided_by: llm`) ask `claude -p` with no tools for one
of `outcomes`; anything else is `default`. `decided_by: human` never waits: it
takes `default` and leaves a `needs_human` line in the state (CF-0317) - or, with `notify: quiet` in the
plan (CF-0735), a quiet line (`quiet` in the state, the journal) and no
notification; the user's line is the plan's Russian `say`. An
outcome whose name starts with `stop` ends the run like a failed stage.

**The state file** `<batch>/run-state.json` is rewritten atomically after
every change: the plan's fingerprint, every stage's status (pending, running,
done, skipped + why, failed + why), every process launched (`runs`: key,
argv, pid, pgid, start, log, exit code, end), the current stage and run, the
next stage, the rerun counters, the human lines. `--resume DIR` replays the
plan against it: a finished stage is not touched, a finished process is not
started again (its recorded exit code drives the same `on_exit` path), a
process still alive is waited for, and one that died without an exit code is
started again - at most `--max-reruns` times. A run that changed plan since
it started is refused (`--plan-changed-ok` to go on anyway).

**Markers.** Only stages with `marker_by: executor` get `runlog stage-start /
stage-done <marker>` from here, through `scripts/runlog` (the format and the
`role: operator` it records are runlog's, unchanged); `marker_by: skill`
stages write their own and the prompt says so. A step's `note_on_exit` text
for the code it exited with goes into the stage's `stage-done --note` (CF-0204:
`usability: stale, not remeasured` of pool-maintenance).

**A restarted LLM stage** (CF-0204). A `marker_by: skill` stage whose process
died without an exit code is started again from the top of its SKILL.md, which
writes `stage-start` once more. Before that the executor closes the attempt
that died: if the stage's marker is open in `RUN_EVENTS.jsonl` it writes
`runlog stage-done <marker> --note "restarted (CF-0204): ..."`, so every
attempt is one start/done pair - the runlog format is unchanged and the
triage does not see a stage opened and never closed.

**Ceilings** (CF-0204). An LLM stage with `timeout_min` in the plan is killed
past it - SIGTERM to its process group, SIGKILL after `KILL_GRACE_S` - and
fails with `timeout_min N exceeded`; the close still runs. The clock is the
attempt's own start (`runs.<key>.started`), so a resumed executor kills a
stage that outlived its ceiling while nobody watched.

**Stops.**
* a step exits with a code in neither `ok_exit` nor `on_exit`, an `on_exit`
  rerun past the limit (unless the step has `exhausted`: then it runs once
  more with `exhausted.argv_add` - `--final` for the plan check, CF-0793 - and
  that run's exit decides), an LLM stage that fails: the stage is `failed`, every
  later stage that is not `always` is skipped, the close still runs; exit 1;
* the stop-cock (`runlog stopcock` exit 3) is a `when` of the plan: the
  stages it guards are skipped with the verdict as the reason, the close runs;
* `claude` not logged in (`NOT_LOGGED_IN`): the run halts where it is - no
  close, nothing marked failed - with `status: halted` in the state; log in
  and `--resume`; exit 4;
* `--until STAGE`: the run pauses after it (exit 3), `--resume` goes on;
* two executors on one batch: an exclusive lock on `<batch>/run-executor.lock`
  (released by the kernel when the holder dies); the second exits 2;
* a new run while a batch is open (`runlog batch-active`): exit 2, nothing
  opened;
* a channel that may not start yet (`run_plan.start_refusal`, CF-0659: its
  voice is a `TODO` placeholder): `run` and `--resume` exit 2 before anything
  is created; `--dry-run` prints the plan under a `НЕ СТАРТУЕТ` line.

**A rebuild** (CF-0668) is a run whose starting state somebody else wrote:
`shared/batch_control.py rebuild()` makes `pipeline/rebuilds/<ts>`, copies the
source batch's records, marks the stages before the mode's `from` (and its
`skip`) `skipped` in `run-state.json` with a `rebuild` block, and starts
`--resume` on it. The executor walks it like any resumed run; the only thing
it reads of the block is `rebuild.args.<stage>`, added to that stage's args
in the prompt. `--dry-run --resume DIR` prints the plan against that state.

**The code check** (CF-0713). An LLM stage is told it writes data, never the
factory's code (`CODE_RULE_LINES` in its prompt), and is checked for it: before
it the executor snapshots every repo (`shared/stage_code_guard.py`: tracked
files only, the root's records excepted - what `batch-start` refuses), after
it compares. A tracked file the stage changed, or a commit of code it made,
goes into `code_edits` (the stage's and the run's), a `stage_code_edit` event
in RUN_EVENTS.jsonl (an авария of the triage), the stage-done note, a
`needs_human` notification and the stage's reason. Until the rule has a
signed price (CF-0320) that is a warning: the stage keeps its status. The
dirt is not cleaned: the next `batch-start` refuses the tree (CF-0479).

**Notifications** (CF-0591). A halt, the end of a run (done or failed) and a
`decided_by: human` default are each one notification through the bus
(`shared/notify.py`), linked to the channel's batch section of the console;
`--no-notify` turns them off. A notification is never on the critical path:
the bus cannot stop or fail the run.

**Work left running** (CF-0734). An LLM stage that exits 0 while a `script`
event it started (RUN_EVENTS, its own stage, since its start) has no
done/failed is failed with `operator_left_running_work`: `claude -p` ending
its turn ends the session and the processes it started with it, so the
stage's work was cut, whatever the operator said. A start that a later end of
the same script/step/video replaced (a retry) does not count - and a start
with no video is matched by its args, since the end may name the video the
script found (CF-0889: `index_footage.py ufOCfVnLlzI` starts with video null
and ends with video set). Nothing is
killed here; the prompt tells the operator to wait in the foreground.

**No output, no close** (CF-0730). An LLM stage whose SKILL writes its
markers and that exits 0 owing a `produces` file it did not write is failed
with `stage_left_no_output` - unless it wrote its own stage-done since its
start: that is the SKILL's no-waiting exit (CF-0317) and the stage is done,
its note carried as the reason. After a `rerun-from` (CF-0781) a `produces`
file still carrying the bytes the reset recorded (`manual_resets[] ->
previous_run`, shared/runlog/previous_run.py) is the previous run's and is
read as missing.

**A broken contract** (CF-0917). An LLM stage whose output file is there
but breaks the contract it owes the files it read (`run_checks.OUTPUT_CONTRACTS`:
today `04-compliance-checker.json` - a row under every script id of `03`,
each with its `claims_gate`) is failed with `stage_broke_contract`, its own
stage-done notwithstanding: 0835Z's compliance pass keyed 04 by the topic id
and closed done, and the Editor rendered nothing. A `produces` file is read
strictly, an `updates` file (a merging pass) without the rows it replaced.
The break is a `stage_contract_break` event in RUN_EVENTS.jsonl as well - the
triage files it under the stage, and the downstream silence as its consequence.

Exit codes: 0 done; 1 done with a failed stage; 2 refused (bad call, invalid
plan, lock held, a batch open, plan changed); 3 paused (`--until`); 4 halted,
claude not logged in. Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import glob as globmod
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import channel_ids  # noqa: E402
import proc_group  # noqa: E402
import quota_day  # noqa: E402
import run_plan  # noqa: E402
import stage_code_guard  # noqa: E402

TASK = "CF-0203"
STATE_FILE = "run-state.json"
LOCK_FILE = "run-executor.lock"
LOCK_TRIES, LOCK_RETRY_S = 3, 0.05   # CF-0670: a lock probe holds it for microseconds
LOGS_DIR = "logs"
EVENTS_FILE = "RUN_EVENTS.jsonl"          # runlog.EVENTS_FILE: the batch is open once it exists
STATE_VERSION = 1

EXIT_DONE, EXIT_FAILED, EXIT_REFUSED, EXIT_PAUSED, EXIT_NOT_LOGGED_IN = 0, 1, 2, 3, 4

MAX_RERUNS = 3                 # on_exit `rerun` loops, and restarts of a process that died
POLL_SECONDS = 5.0
PROBE_TIMEOUT = 300            # a `when.cmd` probe is a quick read, never a stage
LOG_TAIL_LINES = 60            # what a handler is shown of the step that called it
KILL_GRACE_S = 30.0            # SIGTERM -> SIGKILL of a stage past its ceiling (CF-0204)
RESTART_NOTE = "restarted (CF-0204)"
OPERATOR_LEFT_RUNNING_WORK = "operator_left_running_work"   # CF-0734
STAGE_LEFT_NO_OUTPUT = "stage_left_no_output"               # CF-0730
STAGE_BROKE_CONTRACT = "stage_broke_contract"               # CF-0917
CONTRACT_TASK = "CF-0917"
CONTRACT_BREAK_EVENT = "stage_contract_break"               # = triage.STAGE_CONTRACT_BREAK

CLAUDE_ENV = "RUN_EXECUTOR_CLAUDE"       # the claude binary (tests put a stand-in here)
TOOLS_ENV = "RUN_EXECUTOR_CLAUDE_TOOLS"  # comma list overriding LLM_TOOLS
DEFAULT_CLAUDE_FALLBACK = Path.home() / ".local" / "bin" / "claude"
# What a stage may use. No prompt can be answered headless, so `dontAsk` with
# an explicit allow-list: anything outside it is denied, never waited on.
LLM_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebFetch", "WebSearch",
             "Agent", "TodoWrite")
PERMISSION_MODE = "dontAsk"
NOT_LOGGED_IN = "NOT_LOGGED_IN"
# CF-0899: every halt on NOT_LOGGED_IN is a row of run-state.json `login_halts`
# - `{at, stage, reason, task, resumed}`, `resumed` set by the `--resume` that
# goes on from it. The stop is the user's (only a person logs in): runlog
# no-waiting sets the wait/gap that holds it aside, named, on the stage that
# halted (shared/runlog/no_waiting.py `login_stops`), and the schedule's tick
# resumes the batch by itself once `claude auth status` says logged in.
LOGIN_HALTS_KEY = "login_halts"
LOGIN_TASK = "CF-0899"
# The same patterns the claim judge reads (shared/factrule/claim_answer_claude.py).
NOT_LOGGED_IN_RE = re.compile(
    r"not logged in|please run /login|run /login|/login\b|"
    r"oauth[^\n]{0,60}(expired|revoked|invalid)|session expired|"
    r"invalid api key|authentication_error", re.I)
DECISION_SYSTEM = ("You decide one question for an automated pipeline. Answer only with the "
                   "JSON object asked for, choosing exactly one of the listed outcomes.")

TERMINAL = ("done", "skipped", "failed")

# CF-0713: a stage is not the factory's developer. The Science batch 2001Z had
# its footage-indexer model patch `agents/footage-indexer/scripts/source_rights.py`
# (uncommitted, on a pinned agent) after a crash and finish the batch on code
# nobody recorded. The prohibition is said here, in every LLM stage's prompt;
# what the stage changed anyway is caught after it (stage_code_guard).
CODE_RULE_LINES = [
    "Never change the factory's code or configuration (CF-0713): no Edit, Write, sed, "
    "patch or git command on a tracked file of the factory root or of an agent repo - "
    "`agents/*/scripts/`, `agents/*/.claude/`, any agent's tracked files, `shared/`, "
    "`scripts/`, `tests/`, `channels/*.json`, `channels/<channel>/` configs, "
    "`agents.lock.json`. You write data only: the batch directory, the footage pool, "
    "caches, and whatever the SKILL's own scripts write.",
    "When one of our scripts crashes or refuses, do not fix it, patch it or work around "
    "it in code: the stage fails with the error, and the run's triage files the task. "
    "The executor compares the git trees before and after this stage; a tracked file "
    "you changed is recorded against the stage (`stage_code_edit`) and reported.",
]



def _args(e):
    params = e.get("params")
    args = params.get("args") if isinstance(params, dict) else None
    return list(args) if isinstance(args, (list, tuple)) else None


def _retry_of(start, end):
    """CF-0734/CF-0889: whether `end` (a done/failed `script` event of the same
    name and step, later than `start`) finished the work `start` began. Same
    video, or - when the start names no video (the script learns it from its
    args, `index_footage.py <path>`) - the same `params.args`, or, if the end
    carries no args, a start arg whose file stem is the end's video."""
    if start.get("video") == end.get("video"):
        return True
    if start.get("video"):
        return False
    s_args, e_args = _args(start), _args(end)
    if s_args is None:
        return False
    if e_args is not None:
        return s_args == e_args
    video = end.get("video")
    return bool(video) and any(Path(str(a)).stem == video for a in s_args)

class Halt(Exception):
    """The run stops where it is and can be resumed (not logged in)."""

    def __init__(self, reason, code=EXIT_NOT_LOGGED_IN):
        super().__init__(reason)
        self.reason, self.code = reason, code


class Refused(Exception):
    """The run does not start (exit 2)."""


def _previous_run():
    """shared/runlog/previous_run.py of this checkout, by path (CF-0781)."""
    import importlib.util                                     # noqa: PLC0415
    name = "previous_run"
    here = (HERE / "runlog" / "previous_run.py").resolve()
    mod = sys.modules.get(name)
    if mod is None or Path(getattr(mod, "__file__", "") or "").resolve() != here:
        spec = importlib.util.spec_from_file_location(name, here)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[name] = mod
    return mod


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def msk_day():
    """Today's Moscow date, YYYY-MM-DD - the day a once-a-day notification is keyed by."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Moscow")
    except Exception:                                            # noqa: BLE001
        tz = dt.timezone(dt.timedelta(hours=3))
    return dt.datetime.now(tz).date().isoformat()


def new_batch_id():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def fingerprint(plan):
    """The plan's stages as a hash. The rebuild modes (CF-0668) are left out: a
    rebuild reads them once, into its state, and an edit of them must not make
    every open run refuse its `--resume`."""
    body = {k: v for k, v in plan.items() if k != run_plan.REBUILD_KEY} \
        if isinstance(plan, dict) else plan
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def write_json_atomic(path, doc):
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def safe(key):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)


# --------------------------------------------------------------------------
# the claude command - the one place it is built
# --------------------------------------------------------------------------

def claude_binary(flag=None, env=None):
    env = os.environ if env is None else env
    for c in (flag, env.get(CLAUDE_ENV)):
        if c:
            return str(c)
    import shutil  # noqa: PLC0415
    return shutil.which("claude") or str(DEFAULT_CLAUDE_FALLBACK)


def llm_tools(env=None):
    env = os.environ if env is None else env
    raw = env.get(TOOLS_ENV)
    return tuple(t.strip() for t in raw.split(",") if t.strip()) if raw else LLM_TOOLS


def claude_stage_argv(claude, model, add_dirs, tools=None):
    """`claude -p` for a stage worked by its SKILL.md: tools allowed (it reads
    and writes the batch, runs the agent's scripts), nothing that would ask,
    one JSON result at the end. The prompt goes in on stdin. The session is
    kept (no --no-session-persistence): the transcripts are what the token
    accounting reads (scripts/usage_from_transcripts.py)."""
    tools = tuple(tools or LLM_TOOLS)
    argv = [claude, "-p", "--model", model, "--output-format", "json",
            "--permission-mode", PERMISSION_MODE,
            "--tools", ",".join(tools), "--allowedTools", ",".join(tools)]
    for d in add_dirs:
        argv += ["--add-dir", str(d)]
    return argv


def claude_decision_argv(claude, model):
    """`claude -p` for a decision: no tools, no session, text out - the shape
    of the claim judge's answerer (CF-0553)."""
    return [claude, "-p", "--model", model, "--tools", "", "--no-session-persistence",
            "--output-format", "text", "--system-prompt", DECISION_SYSTEM]


def last_json_object(text):
    dec = json.JSONDecoder()
    found, i = None, 0
    text = text or ""
    while True:
        i = text.find("{", i)
        if i < 0:
            return found
        try:
            doc, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(doc, dict):
            found = doc
        i = end


# --------------------------------------------------------------------------
# processes: launched detached, followed by pid + exit file
# --------------------------------------------------------------------------

def pid_alive(pid, token):
    """True when `pid` is running and its command line carries `token` (the
    exit-file path: a recycled pid runs something else). A zombie is dead."""
    try:
        cp = subprocess.run(["ps", "-ww", "-o", "stat=", "-o", "command=", "-p", str(int(pid))],
                            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return False
    line = cp.stdout.strip()
    if cp.returncode != 0 or not line:
        return False
    stat, _, cmd = line.partition(" ")
    return not stat.startswith("Z") and token in cmd


def read_exit(exit_file):
    try:
        doc = json.loads(Path(exit_file).read_text())
        return int(doc["exit"]), doc.get("ended")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def exec_main(argv):
    """`_exec`: the wrapper every launched command runs under. Runs the
    command, appends its output to --log, writes {"exit", "ended"} to
    --exit-file when it ends. Started in its own session by the executor."""
    ap = argparse.ArgumentParser(prog="run_executor.py _exec")
    ap.add_argument("--exit-file", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--stdin", default=None)
    ap.add_argument("--cwd", default=None)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    ns = ap.parse_args(argv)
    cmd = ns.cmd[1:] if ns.cmd[:1] == ["--"] else ns.cmd
    for sig in (signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.SIG_IGN)
    child = {"p": None}

    def _term(signum, _frame):
        if child["p"] is not None:
            try:
                child["p"].send_signal(signum)
            except OSError:
                pass

    signal.signal(signal.SIGTERM, _term)
    with open(ns.log, "a", encoding="utf-8") as log:
        log.write(f"# {TASK} {now_iso()} start: {shlex.join(cmd)}\n")
        log.flush()
        stdin = open(ns.stdin, encoding="utf-8") if ns.stdin else subprocess.DEVNULL
        try:
            p = subprocess.Popen(cmd, stdin=stdin, stdout=log, stderr=subprocess.STDOUT,
                                 cwd=ns.cwd)
            child["p"] = p
            while True:
                try:
                    rc = p.wait()
                    break
                except InterruptedError:
                    continue
        except OSError as e:
            log.write(f"# {TASK} cannot start: {e}\n")
            rc = 127
        finally:
            if ns.stdin:
                stdin.close()
        log.write(f"# {TASK} {now_iso()} exit {rc}\n")
    write_json_atomic(ns.exit_file, {"exit": rc, "ended": now_iso()})
    return 0


# --------------------------------------------------------------------------
# the executor
# --------------------------------------------------------------------------

class Executor:
    def __init__(self, root, channel, plan, batch, state, *, poll=POLL_SECONDS,
                 max_reruns=MAX_RERUNS, claude=None, out=print, minute_s=60.0,
                 kill_grace_s=KILL_GRACE_S, notifier=None, clock=None):
        self.root = Path(root)
        self.channel = channel
        self.plan = plan
        self.batch = Path(batch)
        self.batch_id = self.batch.name
        self.state = state
        self.poll = poll
        self.max_reruns = max_reruns
        self.claude = claude_binary(claude)
        self.out = out
        self.agents = run_plan.lock_agents(self.root)
        self.by_id = {s["id"]: s for s in plan["stages"]}
        self.order = run_plan.order(plan)
        self._children = {}
        self.minute_s = minute_s            # seconds in a `timeout_min` minute (tests shrink it)
        self.kill_grace_s = kill_grace_s
        self._current = None                # the ordered stage a step's note belongs to
        self.notifier = notifier            # CF-0591: fn(kind, key, text, channel); None = off
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))   # CF-0787 (tests fix it)

    def notify(self, kind, key, text, whole=False):
        """One notification of the run (CF-0591) - never raises. CF-0925: the
        line starts with the channel's name and the batch's day («Reel, батч
        08.11: ...»), not their ids; `whole` - the text already says it (the
        multi-line «батч готов»)."""
        if self.notifier is None:
            return
        try:
            if not whole:
                text = f"{self.where()}: {text}"
            self.notifier(kind, f"{kind}:{self.channel}:{self.batch_id}:{key}", text,
                          self.channel)
        except Exception as e:                                   # noqa: BLE001
            self.out(f"  notify {kind}: {e.__class__.__name__}: {e}")

    def where(self):
        """`Reel, батч 08.11` (CF-0925); the ids when the words cannot be had."""
        try:
            import notify_human                 # shared/ is on sys.path (HERE)
            day = notify_human.batch_day(self.batch_id)
            return (f"{notify_human.notify.channel_label(self.channel, self.root)}, батч "
                    f"{day or self.batch_id}")
        except Exception:                                        # noqa: BLE001
            return f"{self.channel} {self.batch_id}"

    def done_text(self, broken):
        """CF-0925: «✅ Reel: батч готов — 4 ролика из 9 тем» with a line per
        video (shared/notify_human.py, from the batch's 05 and 06)."""
        try:
            import notify_human                 # shared/ is on sys.path (HERE)
            return notify_human.batch_done_text(self.channel, self.batch, root=self.root,
                                                broken=broken)
        except Exception as e:                                   # noqa: BLE001
            self.out(f"  notify run_done text: {e.__class__.__name__}: {e}")
            return (f"{self.where()}: батч закончен с упавшей стадией {broken} - разбор"
                    if broken else f"{self.where()}: батч закончен - итог в центре")

    # ---- state ----------------------------------------------------------

    def save(self):
        self.state["updated"] = now_iso()
        write_json_atomic(self.batch / STATE_FILE, self.state)

    def stage_state(self, sid):
        return self.state["stages"].setdefault(sid, {"status": "pending"})

    # ---- templates ------------------------------------------------------

    def agent_dir(self, owner):
        return self.root if owner in (None, run_plan.ROOT_OWNER) else \
            self.root / self.agents.get(owner, f"agents/{owner}")

    def python_of(self, owner):
        venv = self.agent_dir(owner) / ".venv" / "bin" / "python3"
        if venv.exists():
            return str(venv)
        return sys.executable if owner in (None, run_plan.ROOT_OWNER) else "python3"

    def expand(self, s, owner):
        def sub(m):
            name = m.group(1)
            fixed = {"root": str(self.root), "channel": self.channel, "batch": str(self.batch),
                     "batch_id": self.batch_id, "runlog": str(self.root / "scripts" / "runlog"),
                     "python": self.python_of(owner), "agent_dir": str(self.agent_dir(owner))}
            if name in fixed:
                return fixed[name]
            head, _, agent = name.partition(":")
            if head == "python" and agent:
                return self.python_of(agent)
            if head == "dir" and agent:
                return str(self.agent_dir(agent))
            return m.group(0)
        return run_plan._PH.sub(sub, s)

    def argv_of(self, argv, owner, glob=False):
        out = []
        for a in argv:
            a = self.expand(a, owner)
            if glob and any(c in a for c in "*?["):
                hits = sorted(globmod.glob(a))
                out += hits or [a]          # the shell's behaviour: an empty glob stays literal
            else:
                out.append(a)
        return out

    def env_of(self, step=None):
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env.pop("RUNLOG_BATCH", None)
        if (self.batch / EVENTS_FILE).exists():
            env["RUNLOG_BATCH"] = str(self.batch)
        for k, v in ((step or {}).get("env") or {}).items():
            env[k] = self.expand(str(v), None)
        for k in (step or {}).get("env_unset") or []:
            env.pop(k, None)
        return env

    # ---- processes ------------------------------------------------------

    def process(self, key, stage_id, argv, cwd, env, stdin_text=None, timeout_s=None,
                on_restart=None):
        """Run one command to its end and return its exit code - or the
        recorded one, when this run key already finished in an earlier life
        of the executor. A run still alive is waited for; one that died with
        no exit code is started again (at most max_reruns times), after
        `on_restart(rec)`. With `timeout_s` a run older than that is killed
        (its process group) and `rec["timed_out"]` set (CF-0204)."""
        runs = self.state["runs"]
        rec = runs.get(key)
        if rec and rec.get("exit") is not None:
            return rec["exit"]
        if rec and rec.get("pid"):
            code = self._follow(key, rec, timeout_s)
            if code is not None:
                return code
            rec["restarts"] = rec.get("restarts", 0) + 1
            if rec["restarts"] > self.max_reruns:
                rec["exit"], rec["ended"] = -1, now_iso()
                rec["lost"] = True
                self.save()
                return -1
            self.out(f"  {key}: pid {rec['pid']} died without an exit code - started again "
                     f"({rec['restarts']}/{self.max_reruns})")
            if on_restart is not None:
                on_restart(rec)
        logs = self.batch / LOGS_DIR
        logs.mkdir(parents=True, exist_ok=True)
        base = logs / safe(key)
        log, exit_file = Path(f"{base}.log"), Path(f"{base}.exit")
        try:
            exit_file.unlink()
        except FileNotFoundError:
            pass
        wrapped = [sys.executable, str(Path(__file__).resolve()), "_exec",
                   "--exit-file", str(exit_file), "--log", str(log), "--cwd", str(cwd)]
        if stdin_text is not None:
            pf = Path(f"{base}.prompt.txt")
            pf.write_text(stdin_text, encoding="utf-8")
            wrapped += ["--stdin", str(pf)]
        wrapped += ["--", *argv]
        p = subprocess.Popen(wrapped, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, env=env)
        self._children[key] = p
        rec = runs.setdefault(key, {})
        rec.update({"stage": stage_id, "argv": argv, "cwd": str(cwd), "pid": p.pid,
                    "pgid": p.pid, "started": now_iso(), "log": str(log.relative_to(self.batch)),
                    "exit_file": str(exit_file.relative_to(self.batch)), "exit": None,
                    "ended": None})
        rec.setdefault("restarts", 0)
        self.state["current"] = {"stage": stage_id, "run": key, "pid": p.pid}
        self.save()
        self.out(f"  {key}: started pid {p.pid}: {shlex.join(argv)[:200]}")
        code = self._follow(key, rec, timeout_s)
        if code is None:                       # the wrapper itself died (killed)
            return self.process(key, stage_id, argv, cwd, env, stdin_text, timeout_s,
                                on_restart)
        return code

    def _follow(self, key, rec, timeout_s=None):
        """Poll until the run's exit file appears; None if the process is gone
        without one. Past `timeout_s` since the run started: killpg, and the
        exit code of the killed run (CF-0204)."""
        exit_file = self.batch / rec["exit_file"]
        child = self._children.get(key)
        deadline = None
        if timeout_s:
            try:
                started = dt.datetime.strptime(rec["started"], "%Y-%m-%dT%H:%M:%SZ") \
                    .replace(tzinfo=dt.timezone.utc).timestamp()
            except (KeyError, TypeError, ValueError):
                started = time.time()
            deadline = started + timeout_s
        while True:
            running = child is not None and child.poll() is None
            got = read_exit(exit_file)
            if got is not None:
                rec["exit"], rec["ended"] = got
                self.save()
                return got[0]
            if not running and not pid_alive(rec["pid"], str(exit_file)):
                got = read_exit(exit_file)
                if got is not None:
                    rec["exit"], rec["ended"] = got
                    self.save()
                    return got[0]
                return None
            if deadline is not None and time.time() >= deadline:
                return self._kill_past_ceiling(key, rec, timeout_s)
            time.sleep(self.poll)

    def _kill_past_ceiling(self, key, rec, timeout_s):
        """SIGTERM to the run's process group, SIGKILL after the grace; the
        exit code is the wrapper's (the signal) or -9 when it left none.
        CF-0655: the grace waits for the WHOLE group to empty, not for the
        wrapper's exit file - the wrapper forwards SIGTERM to its child and
        writes the file when that child dies, and a grandchild that caught
        SIGTERM used to outlive the ceiling with no SIGKILL ever sent."""
        rec["timed_out"] = {"after_s": timeout_s, "at": now_iso()}
        self.save()
        pgid = rec.get("pgid") or rec["pid"]
        self.out(f"  {key}: past its ceiling ({timeout_s / self.minute_s:g} min) - "
                 f"killing process group {pgid}")
        exit_file = self.batch / rec["exit_file"]
        child = self._children.get(key)
        how = proc_group.kill_group(pgid, self.kill_grace_s,
                                    reap=child.poll if child is not None else None)
        if how == "survived":
            self.out(f"  {key}: process group {pgid} still has members after SIGKILL")
        got = read_exit(exit_file)
        rec["exit"], rec["ended"] = (got if got is not None else (-int(signal.SIGKILL), now_iso()))
        self.save()
        return rec["exit"]

    def log_text(self, key):
        rec = self.state["runs"].get(key) or {}
        try:
            return (self.batch / rec["log"]).read_text(encoding="utf-8", errors="replace")
        except (OSError, KeyError):
            return ""

    def log_tail(self, key, n=LOG_TAIL_LINES):
        return "\n".join(self.log_text(key).splitlines()[-n:])

    def discard_run(self, key):
        rec = self.state["runs"].pop(key, None)
        if rec:
            self.state.setdefault("discarded_runs", []).append(dict(rec, key=key))

    # ---- markers --------------------------------------------------------

    def runlog(self, *args, timeout=120):
        argv = [str(self.root / "scripts" / "runlog"), *args]
        try:
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env=self.env_of(), cwd=str(self.root))
            return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
        except (OSError, subprocess.SubprocessError) as e:
            return 127, str(e)

    def marker(self, st, which, note=None):
        if not st.get("marker") or st.get("marker_by") != "executor":
            return
        ss = self.stage_state(st["id"])
        marks = ss.setdefault("markers", {})
        if marks.get(which):
            return
        args = [which, st["marker"], "--batch", str(self.batch)]
        if note:
            args += ["--note", note]
        rc, text = self.runlog(*args)
        marks[which] = now_iso() if rc == 0 else f"refused (exit {rc}): {text.strip()[-300:]}"
        self.save()
        if rc != 0:
            self.out(f"  runlog {which} {st['marker']}: exit {rc}: {text.strip()[-300:]}")

    def open_markers(self):
        """Stage names with a stage-start after their last stage-done in the
        batch's events (runlog._open_stages, read here without importing it)."""
        open_ = set()
        try:
            lines = (self.batch / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
        except OSError:
            return open_
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("kind") != "marker":
                continue
            if e.get("status") == "stage-start":
                open_.add(e.get("stage"))
            elif e.get("status") == "stage-done":
                open_.discard(e.get("stage"))
        return open_

    def close_dead_attempt(self, st, rec):
        """CF-0204: before a `marker_by: skill` stage starts again, the attempt
        that died is closed - its SKILL will write stage-start once more."""
        if not st.get("marker") or st.get("marker_by") != "skill":
            return
        if st["marker"] not in self.open_markers():
            return
        note = (f"{RESTART_NOTE}: pid {rec.get('pid')} died without an exit code; "
                f"the stage starts again")
        rc, text = self.runlog("stage-done", st["marker"], "--batch", str(self.batch),
                               "--note", note)
        ss = self.stage_state(self._current or st["id"])
        ss.setdefault("restarted", []).append(
            {"at": now_iso(), "pid": rec.get("pid"),
             "closed": "stage-done" if rc == 0 else f"refused (exit {rc}): {text.strip()[-200:]}"})
        self.save()
        self.out(f"  {st['marker']}: closed the dead attempt ({'ok' if rc == 0 else f'exit {rc}'})")

    def add_note(self, text):
        if not self._current:
            return
        notes = self.stage_state(self._current).setdefault("notes", [])
        if text not in notes:
            notes.append(text)
            self.save()

    # ---- conditions -----------------------------------------------------

    def condition(self, c, owner):
        """(holds, text)."""
        if "cmd" in c:
            argv = self.argv_of(c["cmd"], owner)
            try:
                cp = subprocess.run(argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT,
                                    env=self.env_of(), cwd=str(self.agent_dir(owner)))
                rc, said = cp.returncode, ((cp.stdout or "") + (cp.stderr or "")).strip()
            except subprocess.TimeoutExpired:
                rc, said = None, f"probe ran past {PROBE_TIMEOUT}s"
            except OSError as e:
                rc, said = None, str(e)
            name = " ".join(Path(a).name for a in c["cmd"][:3])
            text = f"{name} exits {rc}" + (f" ({said.splitlines()[0][:160]})" if said else "")
            return rc in c["exit"], text
        (k, v), = c.items()
        if k == "exists":
            hits = globmod.glob(str(self.batch / v))
            return bool(hits), f"{v}: {len(hits)} file(s)"
        if k == "ran":
            st = self.state["stages"].get(v, {}).get("status")
            return st == "done", f"{v} {st or 'pending'}"
        if k == "check":
            import run_checks  # noqa: PLC0415
            holds, why = run_checks.check(v, self.batch, root=self.root)
            return holds, f"{v}: {why}"
        return False, f"unknown condition {c}"

    def evaluate_when(self, st):
        when = st.get("when")
        if not when:
            return True, ""
        seen = []
        for c in (when if isinstance(when, list) else [when]):
            holds, text = self.condition(c, st.get("owner"))
            if not holds:
                return False, text
            seen.append(text)
        return True, "; ".join(seen)

    # ---- stages ---------------------------------------------------------

    def run(self, until=None):
        """Walk the plan. Returns the exit code."""
        self.state["status"] = "running"
        self.state.pop("halt_reason", None)
        self.save()
        broken = next((sid for sid in self.order
                       if self.state["stages"].get(sid, {}).get("status") == "failed"), None)
        for i, sid in enumerate(self.order):
            st = self.by_id[sid]
            ss = self.stage_state(sid)
            self.state["next"] = sid
            if ss["status"] in TERMINAL:
                continue
            if broken and not st.get("always"):
                self.finish(st, "skipped", f"after failed stage {broken}")
                continue
            if ss.get("when") is None:
                holds, why = self.evaluate_when(st)
                ss["when"] = {"holds": holds, "why": why, "at": now_iso()}
                self.save()
            if not ss["when"]["holds"]:
                self.finish(st, "skipped", f"when: {ss['when']['why']}")
                continue
            ss["status"] = "running"
            ss.setdefault("started", now_iso())
            self.state["current"] = {"stage": sid}
            self.save()
            self.out(f"stage {sid} ({st['kind']})")
            self._current = sid
            self.marker(st, "stage-start")
            try:
                status, reason = self.body(st, sid)
            except Halt as h:
                self.state["status"] = "halted"
                self.state["halt_reason"] = h.reason
                login = h.reason.startswith(NOT_LOGGED_IN)
                if login:                                         # CF-0899
                    self.state.setdefault(LOGIN_HALTS_KEY, []).append(
                        {"at": now_iso(), "stage": sid, "reason": h.reason,
                         "task": LOGIN_TASK, "resumed": None})
                self.save()
                self.out(f"HALT at {sid}: {h.reason}")
                # CF-0899: a login halt is told once a day - the tick resumes the
                # batch by itself, and a resume that halts again is the same news
                key = (f"{sid}:{NOT_LOGGED_IN}:{msk_day()}" if login
                       else f"{sid}:{len(self.state.get('resumed') or [])}")
                text = f"батч остановлен на {sid} - {h.reason}"
                if login:
                    text += ("; войди в claude: в терминале `claude`, затем /login - "
                             "батч продолжит тик расписания сам")
                self.notify("run_halted", key, text)
                self.out(f"  state: {self.batch / STATE_FILE}; resume with: python3 "
                         f"shared/run_executor.py run {self.channel} --resume {self.batch}")
                return h.code
            notes = list(ss.get("notes") or [])
            if status != "done":
                notes.insert(0, f"{status}: {reason}")
            self.marker(st, "stage-done", "; ".join(notes) or None)
            self._current = None
            self.finish(st, status, reason)
            if status == "failed" and not broken:
                broken = sid
            if until and sid == until and i + 1 < len(self.order):
                self.state["status"] = "paused"
                self.state["next"] = self.order[i + 1]
                self.state["current"] = None
                self.save()
                self.out(f"PAUSED after {sid} (--until); next {self.order[i + 1]}")
                return EXIT_PAUSED
        self.state["next"] = None
        self.state["current"] = None
        self.state["status"] = "failed" if broken else "done"
        self.save()
        self.out(f"run {self.state['status']}: {self.batch}")
        self.notify("run_done", self.state["status"], self.done_text(broken), whole=True)
        return EXIT_FAILED if broken else EXIT_DONE

    def finish(self, st, status, reason):
        ss = self.stage_state(st["id"])
        ss["status"] = status
        if reason:
            ss["reason"] = reason
        ss["ended"] = now_iso()
        self.save()
        if status != "done" or reason:
            self.out(f"  {st['id']}: {status}{' - ' + reason if reason else ''}")

    def body(self, st, prefix, caller_key=None):
        """Run a stage's (or a handler's) work. (status, reason)."""
        kind = st["kind"]
        if kind == "machine":
            for idx, step in enumerate(st.get("steps") or []):
                ok, reason = self.step(st, idx, step, prefix)
                if not ok:
                    return "failed", reason
            return "done", ""
        if kind == "llm":
            return self.llm(st, prefix, caller_key)
        if kind == "decision":
            outcome = self.decide(st, prefix, caller_key)
            if str(outcome).startswith("stop"):
                return "failed", f"decision {st['id']} took {outcome}"
            return "done", f"outcome {outcome}"
        return "failed", f"unknown kind {kind}"

    def step(self, st, idx, step, prefix):
        owner = st.get("owner")
        ok = step.get("ok_exit") or [0]
        on_exit = step.get("on_exit") or {}
        exhausted = step.get("exhausted")
        attempt = 0
        rerun_env = {}      # CF-0793: what the last on_exit act hands its rerun
        last = False        # CF-0793: the one run past the rerun limit (`exhausted`)
        while True:
            key = f"{prefix}.s{idx}.a{attempt}"
            argv = self.argv_of(step["argv"], owner, glob=step.get("glob", False))
            if last:
                argv += [self.expand(str(a), owner) for a in exhausted.get("argv_add") or []]
            if argv and Path(argv[0]).name == "runlog" and len(argv) > 1 \
                    and argv[1] == "batch-start":
                self.batch.mkdir(parents=True, exist_ok=True)
            env = self.env_of(step)
            env.update(rerun_env)
            rc = self.process(key, st["id"], argv, self.agent_dir(owner), env)
            note = (step.get("note_on_exit") or {}).get(str(rc))
            if note and (rc in ok or str(rc) in on_exit):
                self.add_note(note)
            if last:
                if rc in ok:
                    self.add_note(exhausted.get("note") or
                                  f"reruns exhausted: closed by the last run "
                                  f"({' '.join(exhausted.get('argv_add') or [])})")
                    return True, ""
                return False, (f"step {idx}: exit {rc} on the last run past {self.max_reruns} "
                               f"rerun(s) ({' '.join(exhausted.get('argv_add') or [])}); log "
                               f"{self.state['runs'][key]['log']}")
            if rc in ok:
                return True, ""
            act = on_exit.get(str(rc))
            if act is None:
                return False, (f"step {idx} ({Path(argv[0]).name if argv else '?'} "
                               f"{' '.join(Path(a).name for a in argv[1:2])}) exited {rc}; "
                               f"log {self.state['runs'][key]['log']}")
            if act.get("run"):
                h = self.by_id[act["run"]]
                hkey = f"{act['run']}@{key}"
                hs = self.state["handlers"].setdefault(hkey, {"status": "pending"})
                if hs["status"] not in TERMINAL:
                    hs["status"] = "running"
                    self.save()
                    self.out(f"  exit {rc} -> handler {act['run']}")
                    status, reason = self.body(h, hkey, caller_key=key)
                    hs.update({"status": status, "reason": reason, "ended": now_iso()})
                    self.save()
                if hs["status"] == "failed":
                    return False, f"handler {act['run']} failed: {hs.get('reason')}"
            if act.get("then") == "continue":
                return True, ""
            rerun_env = {k: self.expand(str(v), owner)
                         for k, v in (act.get("rerun_env") or {}).items()}
            attempt += 1
            counter = f"{prefix}.s{idx}"
            self.state["reruns"][counter] = attempt
            self.save()
            if attempt > self.max_reruns:
                if not exhausted:
                    return False, f"step {idx}: exit {rc} still after {self.max_reruns} rerun(s)"
                # CF-0793: the reruns are spent - one last run that closes what
                # is still open (plan_check_loop.py --final) instead of failing
                # the batch with the scripts that are ready
                self.out(f"  {counter}: exit {rc} still after {self.max_reruns} rerun(s) - the "
                         f"last run with {' '.join(exhausted.get('argv_add') or [])}")
                last = True

    # ---- llm ------------------------------------------------------------

    def rebuild_args(self, sid):
        """CF-0668: the args a rebuild adds to a stage (filled when it started)."""
        rb = self.state.get("rebuild") if isinstance(self.state, dict) else None
        extra = ((rb or {}).get("args") or {}).get(sid) if isinstance(rb, dict) else None
        return extra if isinstance(extra, dict) else {}

    def prompt(self, st, caller_key=None):
        args = {k: self.expand(str(v), st.get("owner"))
                for k, v in {**(st.get("args") or {}), **self.rebuild_args(st["id"])}.items()}
        skill = st.get("skill", "")
        path, _, anchor = skill.partition("#")
        lines = [
            f"You run one stage of a Shorts Content Factory batch, headless: started by "
            f"shared/run_executor.py ({TASK}). Nobody is watching this session and nobody "
            f"will answer a question.",
            "",
            f"Stage: {st['id']} - {st.get('title', '')}",
            f"Channel: {self.channel}",
            f"Batch directory: {self.batch}",
            f"Factory root: {self.root}",
            f"Follow {self.root / path}" + (f", the section `{anchor}`" if anchor else "")
            + " for this stage, with these arguments:",
        ]
        lines += [f"  {k}: {v}" for k, v in args.items()] or ["  (none)"]
        lines += self.quota_lines(st)
        rb = self.state.get("rebuild") or {}
        if rb:
            src = rb.get("of") or {}
            lines.append(f"This batch is a rebuild (CF-0668, mode {rb.get('mode')}) of "
                         f"{channel_ids.resolve_channel(src.get('channel'), self.root)}/"
                         f"{src.get('batch_id')}: only the videos "
                         f"{', '.join(v.get('slug') or v.get('script_id') for v in rb.get('videos') or [])}; "
                         f"the records before this stage are the source's, copied.")
        if st.get("marker") and st.get("marker_by") == "skill":
            lines.append(f"The SKILL writes its own runlog stage-start/stage-done "
                         f"`{st['marker']}` markers, as it says.")
        elif st.get("marker"):
            lines.append(f"The executor writes the `{st['marker']}` stage markers; do not "
                         f"write stage-start/stage-done for it yourself.")
        else:
            lines.append("This step has no stage markers of its own; write none.")
        lines += [
            "Do this stage's work only: do not open or close the batch and do not start "
            "other stages - the executor runs them. Do not start background subagents.",
            "You run non-interactively: ending your turn ends this session and kills every "
            "process you started, background ones included. Never end your turn while a "
            "command you started is still running.",
            "A command longer than the Bash timeout: start it in the background with its "
            "output to a file, then wait for it in the FOREGROUND - a Bash call with timeout "
            "<= 540000 ms running a loop such as `until <done-check>; do sleep 20; done` - "
            "and repeat that wait call until the command has finished; only then go on.",
            f"A script you started that has no end recorded when you exit fails the stage "
            f"({OPERATOR_LEFT_RUNNING_WORK}, CF-0734).",
            "Where the SKILL asks a human, take its default and say so in your last message.",
        ]
        lines += CODE_RULE_LINES
        lines.append(f"A crash of our code ends this stage with `STAGE {st['id']}: failed - "
                     f"<script>: <the error>`.")
        if st.get("fallback"):
            lines.append(f"If the stage cannot be done: {st['fallback']}")
        if caller_key:
            lines += ["", f"You were called by the step `{caller_key}`; the end of its output:",
                      self.log_tail(caller_key) or "(empty)"]
        lines += ["", f"End with one line: `STAGE {st['id']}: done` or "
                      f"`STAGE {st['id']}: failed - <reason>`."]
        return "\n".join(lines) + "\n"

    def quota_lines(self, st):
        """CF-0787: the trend-hunter stage is told what its quota day already
        spent in other batches (`quota_day.day_spend`: the batches that started
        in the quota day of now, this one left out) and passes it on as
        `--searches-spent` - search_quota's `searches_before_stage`, which
        before this only a person could give. Written into the stage's state
        too (`searches_before_stage`), so the run-state shows what was handed.
        A rebuild runs no trend-hunter; a failure to count is said, not fatal."""
        if st.get("id") != quota_day.QUOTA_STAGE:
            return []
        try:
            spend = quota_day.day_spend(self.root, exclude=self.batch, now=self.clock())
        except Exception as e:                                   # noqa: BLE001
            return [f"YouTube Search quota ({quota_day.TASK}): the executor could not count "
                    f"what this quota day already spent ({e.__class__.__name__}: {e}); pass "
                    f"`--searches-spent` yourself, as the SKILL says."]
        self.stage_state(st["id"])["searches_before_stage"] = {
            k: spend[k] for k in ("quota_day", "searches", "batches")}
        return quota_day.prompt_lines(spend)

    def llm(self, st, prefix, caller_key=None):
        """An LLM stage (or handler), with the code check of CF-0713 around it:
        what it changed in the tracked code is recorded - a warning until the
        rule has a signed price (stage_code_guard.MODE), never a refusal."""
        key = f"{prefix}.llm"
        self.code_before(key)
        status, reason = self._llm(st, prefix, caller_key)
        edits = self.code_after(st, key)
        if edits:
            line = (f"warning ({stage_code_guard.TASK}): the stage changed tracked code - "
                    f"{stage_code_guard.describe(edits)}")
            reason = f"{reason}; {line}" if reason else line
        return status, reason

    # ---- the code check (CF-0713) ---------------------------------------

    def code_before(self, key):
        """The snapshot of every repo before the run `key` starts - kept in the
        state, so a resumed executor compares with the tree the stage began on."""
        guard = self.state.setdefault("code_guard", {})
        if key in guard:
            return
        guard[key] = {"before": stage_code_guard.snapshot(self.root), "at": now_iso()}
        self.save()

    def code_after(self, st, key):
        """[{repo, files, ...}] the stage changed; recorded once per run key."""
        g = (self.state.get("code_guard") or {}).get(key)
        if not g:
            return []
        if g.get("checked"):
            return g.get("edits") or []
        edits = stage_code_guard.compare(g.get("before"), stage_code_guard.snapshot(self.root),
                                         self.root, channel=self.channel)
        g.update(checked=now_iso(), edits=edits)
        self.save()
        if edits:
            self.record_code_edits(st, key, edits)
        return edits

    def record_code_edits(self, st, key, edits):
        """Loud, in every place a person or the triage looks: the stage's state
        and the run's `code_edits` (the console), a `stage_code_edit` event in
        RUN_EVENTS.jsonl (the triage files it as an авария), the stage-done
        note where the executor writes the markers, the notification bus. The
        dirt itself stays: the next `batch-start` refuses the tree (CF-0479)."""
        line = stage_code_guard.describe(edits)
        row = {"stage": st["id"], "run": key, "at": now_iso(), "mode": stage_code_guard.MODE,
               "task": stage_code_guard.TASK, "edits": edits}
        self.stage_state(self._current or st["id"]).setdefault("code_edits", []).append(row)
        self.state.setdefault("code_edits", []).append(row)
        self.save()
        self.add_note(f"{stage_code_guard.EVENT_KIND} ({stage_code_guard.TASK}, "
                      f"{stage_code_guard.MODE}): {line}")
        if (self.batch / EVENTS_FILE).exists():
            try:
                rl = stage_code_guard._runlog()
                rl.emit(self.batch, stage_code_guard.EVENT_KIND, st.get("marker") or st["id"],
                        status=stage_code_guard.MODE, note=line, edits=edits,
                        task=stage_code_guard.TASK, run=key, plan_stage=st["id"])
            except Exception as e:                                   # noqa: BLE001
                self.out(f"  {stage_code_guard.EVENT_KIND} event not written: {e}")
        self.out(f"  WARNING {st['id']}: the stage changed tracked code "
                 f"({stage_code_guard.TASK}): {line} - the next batch-start refuses this tree")
        self.notify("needs_human", f"code:{key}",
                    f"стадия {st['id']} изменила код фабрики ({line}) - следующий batch-start "
                    f"откажет, пока дерево не чистое ({stage_code_guard.TASK})")

    def _llm(self, st, prefix, caller_key=None):
        owner = st.get("owner")
        key = f"{prefix}.llm"
        dirs = [self.root, self.batch]
        argv = claude_stage_argv(self.claude, st.get("model", "sonnet"), dirs, llm_tools())
        ceiling = st.get("timeout_min")
        rc = self.process(key, st["id"], argv, self.agent_dir(owner), self.env_of(),
                          stdin_text=self.prompt(st, caller_key),
                          timeout_s=ceiling * self.minute_s if ceiling else None,
                          on_restart=lambda rec: self.close_dead_attempt(st, rec))
        text = self.log_text(key)
        if self.state["runs"].get(key, {}).get("timed_out"):
            return "failed", (f"timeout_min {ceiling} exceeded - process group killed; "
                              f"log {self.state['runs'][key]['log']}")
        if rc != 0:
            if NOT_LOGGED_IN_RE.search(text):
                self.discard_run(key)
                self.save()
                raise Halt(f"{NOT_LOGGED_IN}: `claude` is not logged in (stage {st['id']}); "
                           f"log in and resume")
            return "failed", f"claude exited {rc}; log {self.state['runs'][key]['log']}"
        doc = last_json_object(text)
        if isinstance(doc, dict) and doc.get("is_error"):
            res = str(doc.get("result", ""))
            if NOT_LOGGED_IN_RE.search(res):
                self.discard_run(key)
                self.save()
                raise Halt(f"{NOT_LOGGED_IN}: `claude` is not logged in (stage {st['id']})")
            return "failed", f"claude reported an error: {res[:200]}"
        result = str((doc or {}).get("result", ""))
        m = re.search(rf"STAGE {re.escape(st['id'])}: failed\s*-?\s*(.*)", result)
        if m:
            return "failed", f"the stage said: {m.group(1)[:200]}"
        left = self.unfinished_scripts(st, self.state["runs"].get(key, {}).get("started"))
        if left:
            return "failed", (f"{OPERATOR_LEFT_RUNNING_WORK}: оператор закончил сессию, пока "
                              f"шли его скрипты ({', '.join(left[:3])}"
                              f"{f' и ещё {len(left) - 3}' if len(left) > 3 else ''}) - "
                              f"конца у них нет, стадия не доделана; "
                              f"log {self.state['runs'][key]['log']}")
        status, reason = self.output_check(st, self.state["runs"].get(key, {}).get("started"))
        if status == "done" and not reason:
            broken = self.output_contracts(st)
            if broken:
                return "failed", f"{broken}; log {self.state['runs'][key]['log']}"
        return status, reason

    def output_contracts(self, st):
        """CF-0917: the contract the stage's output owes what it read
        (run_checks.OUTPUT_CONTRACTS), asked once the file is there: a
        `produces` file strictly, an `updates` file as a merge. A broken one
        fails the stage (`stage_broke_contract`) - the stage is not recorded
        done, so the next stage is not started on it (0835Z: compliance-scripts
        keyed 04 by the topic id and closed done, the Editor then found no row
        for any script and rendered nothing). '' when every contract holds."""
        files = [(f, True) for f in st.get("produces") or [] if isinstance(f, str)]
        files += [(f, False) for f in st.get("updates") or [] if isinstance(f, str)]
        if not files:
            return ""
        import run_checks  # noqa: PLC0415
        for name, strict in files:
            if name not in run_checks.OUTPUT_CONTRACTS:
                continue
            if not (self.batch / name).is_file():
                continue
            try:
                kept, why = run_checks.output_contract(name, self.batch, strict=strict)
            except Exception as e:                                   # noqa: BLE001
                self.out(f"  contract of {name} not checked: {e}")
                continue
            if not kept:
                self.record_contract_break(st, name, why)
                return (f"{STAGE_BROKE_CONTRACT}: стадия закрылась, но {name} нарушает "
                        f"контракт со стадией до неё - {why}; стадия не сделана, "
                        f"дальше по батчу идти не на чем ({CONTRACT_TASK})")
        return ""

    def record_contract_break(self, st, name, why):
        """A `stage_contract_break` event in RUN_EVENTS.jsonl - what the triage
        files as the stage's broken contract (shared/runlog/triage.py), the
        way `stage_code_edit` carries CF-0713 there. Never fails the run."""
        if not (self.batch / EVENTS_FILE).exists():
            return
        try:
            rl = stage_code_guard._runlog()
            rl.emit(self.batch, CONTRACT_BREAK_EVENT, st.get("marker") or st["id"],
                    status="failed", note=why, file=name, plan_stage=st["id"],
                    task=CONTRACT_TASK, reason_code=STAGE_BROKE_CONTRACT)
        except Exception as e:                                       # noqa: BLE001
            self.out(f"  {CONTRACT_BREAK_EVENT} event not written: {e}")

    def output_check(self, st, since):
        """CF-0730: an LLM stage that exits 0 owing a contract file (`produces`)
        it did not write. With its own stage-done marker since its start it
        took the SKILL's no-waiting exit (CF-0317, e.g. `01b-footage-index.json
        is missing, no scripts written`): done, the note carried as the reason.
        With neither the file nor the close the stage did not do its work and
        is failed (`stage_left_no_output`) - never recorded done, so the next
        stage is not started on a hole (13.10, 1411Z: the indexer recorded done
        without 01b, the researcher then closed on it). Only stages whose SKILL
        writes the markers are read; the executor's own markers prove nothing."""
        owed = [f for f in st.get("produces") or [] if isinstance(f, str)]
        if not owed or st.get("marker_by") != "skill" or not st.get("marker"):
            return "done", ""
        # CF-0781: a file the last rerun-from recorded and the stage did not
        # rewrite is the previous run's output, not this run's
        pr = _previous_run()
        missing, old = [], []
        for f in owed:
            hits = globmod.glob(str(self.batch / f))
            fresh = [h for h in hits if not pr.is_previous_file(
                self.batch, Path(h).relative_to(self.batch), self.state)]
            if not fresh:
                missing.append(f)
                if hits:
                    old.append(f)
        if not missing:
            return "done", ""
        stale = (f" (на диске только файл прошлого прогона до rerun-from: {', '.join(old)}, "
                 f"{pr.TASK})" if old else "")
        close = self.own_close_since(st["marker"], since)
        if close is None:
            return "failed", (f"{STAGE_LEFT_NO_OUTPUT}: стадия закончилась без "
                              f"{', '.join(missing)} и без своего stage-done - работа не "
                              f"сделана, дальше по батчу идти не на чем{stale}")
        return "done", (f"closed without {', '.join(missing)}{stale}: "
                        f"{close.get('note') or 'stage-done without a note'}")

    def own_close_since(self, marker, since):
        """The last stage-done marker of `marker` written at or after `since`."""
        if not since:
            return None
        try:
            lines = (self.batch / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        last = None
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("kind") == "marker" \
                    and e.get("status") == "stage-done" and e.get("stage") == marker \
                    and str(e.get("ts") or "")[:19] >= since[:19]:
                last = e
        return last

    def unfinished_scripts(self, st, since):
        """CF-0734: labels of the stage's own `script` events started since
        `since` (the operator's start) that have no done/failed - and no later
        end of the same script/step that is its retry (`_retry_of`: same video,
        or for a start with no video the same args - CF-0889)."""
        if not since:
            return []
        stages = {st.get("marker") or st["id"], st["id"]}
        try:
            lines = (self.batch / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("kind") == "script" \
                    and e.get("stage") in stages and str(e.get("ts") or "")[:19] >= since[:19]:
                events.append(e)
        ended, ends = set(), {}
        for i, e in enumerate(events):
            if e.get("status") in ("done", "failed"):
                ended.add(e.get("id"))
                ends.setdefault((e.get("name"), e.get("step")), []).append((i, e))
        return [f"{e.get('stage')}/{e.get('step') or e.get('name')}"
                + (f" {e['video']}" if e.get("video") else "")
                for i, e in enumerate(events)
                if e.get("status") == "start" and e.get("id") not in ended
                and not any(j > i and _retry_of(e, end)
                            for j, end in ends.get((e.get("name"), e.get("step")), []))]

    # ---- decisions ------------------------------------------------------

    def decide(self, st, prefix, caller_key=None):
        outcomes, default = list(st.get("outcomes") or []), st.get("default")
        question = self.expand(st.get("question", ""), st.get("owner"))
        rec = self.state["decisions"].get(prefix)
        if rec and rec.get("outcome"):
            return rec["outcome"]
        if st.get("decided_by") == "human":
            # CF-0735: the user reads Russian - the plan's `say`, else a line
            # naming the stage; `notify: quiet` is a line in the state and the
            # journal, never a notification (a safety net elsewhere calls him).
            say = self.expand(st.get("say") or "", st.get("owner")).strip() or \
                f"стадия {st['id']} ждала решения человека"
            ru = f"{say} - никто не ждёт (CF-0317), взято по умолчанию «{default}»"
            if st.get("notify") == "quiet":
                self.state.setdefault("quiet", []).append({"stage": st["id"], "key": prefix,
                                                           "line": ru, "took": default,
                                                           "at": now_iso()})
                self.state["decisions"][prefix] = {"outcome": default,
                                                   "by": "default (human, quiet)"}
                self.save()
                self.out(f"  QUIET {st['id']}: {ru}")
                return default
            line = (f"NEEDS-YOU {st['id']}: {question} - nobody waits (CF-0317), took the "
                    f"default `{default}`")
            self.state["needs_human"].append({"stage": st["id"], "key": prefix,
                                              "question": question, "took": default,
                                              "at": now_iso()})
            self.state["decisions"][prefix] = {"outcome": default, "by": "default (human)"}
            self.save()
            self.out(f"  {line}")
            self.notify("needs_human", prefix, ru)
            return default
        prompt = [f"Question about batch {self.batch} of channel {self.channel}, stage "
                  f"{st['id']}:", question, "",
                  "Outcomes (choose exactly one): " + ", ".join(outcomes)]
        if caller_key:
            prompt += ["", f"Output of the step that asks ({caller_key}), its end:",
                       self.log_tail(caller_key) or "(empty)"]
        prompt += ["", 'Answer with {"outcome": "<one of the outcomes>", "why": "<one line>"}.']
        key = f"{prefix}.decide"
        argv = claude_decision_argv(self.claude, st.get("model", "sonnet"))
        rc = self.process(key, st["id"], argv, self.batch, self.env_of(),
                          stdin_text="\n".join(prompt) + "\n")
        text = self.log_text(key)
        outcome, by = default, "default"
        if rc != 0:
            by = (f"default ({NOT_LOGGED_IN})" if NOT_LOGGED_IN_RE.search(text)
                  else f"default (claude exited {rc})")
        else:
            doc = last_json_object(text) or {}
            if doc.get("outcome") in outcomes:
                outcome, by = doc["outcome"], "llm"
            else:
                by = f"default (answer {str(doc.get('outcome'))[:60]!r} not an outcome)"
        self.state["decisions"][prefix] = {"outcome": outcome, "by": by, "at": now_iso()}
        self.save()
        self.out(f"  decision {st['id']}: {outcome} ({by})")
        return outcome


# --------------------------------------------------------------------------
# dry run
# --------------------------------------------------------------------------

def dry_run_lines(ex):
    lines = [f"run_executor {ex.channel}: dry run - nothing is started",
             f"batch: {ex.batch}", f"state: {ex.batch / STATE_FILE}"]

    def describe(st, indent):
        pad = " " * indent
        out = []
        if st["kind"] == "machine":
            for idx, step in enumerate(st.get("steps") or []):
                argv = ex.argv_of(step["argv"], st.get("owner"))
                extra = []
                if step.get("env"):
                    extra.append("env " + " ".join(f"{k}={v}" for k, v in step["env"].items()))
                if step.get("env_unset"):
                    extra.append("unset " + " ".join(step["env_unset"]))
                if step.get("ok_exit"):
                    extra.append(f"ok {step['ok_exit']}")
                out.append(f"{pad}$ {shlex.join(argv)}" + (f"   [{'; '.join(extra)}]" if extra else ""))
                for code, act in (step.get("on_exit") or {}).items():
                    renv = act.get("rerun_env") or {}
                    out.append(f"{pad}  exit {code} -> {act.get('run') or '-'}, then {act.get('then')}"
                               + (" with env " + " ".join(f"{k}={v}" for k, v in renv.items())
                                  if renv else ""))
                    if act.get("run"):
                        out += describe(ex.by_id[act["run"]], indent + 4)
                if step.get("exhausted"):
                    out.append(f"{pad}  reruns spent -> once more with "
                               f"{' '.join(step['exhausted'].get('argv_add') or [])}")
        elif st["kind"] == "llm":
            argv = claude_stage_argv(ex.claude, st.get("model", "sonnet"), [ex.root, ex.batch],
                                     llm_tools())
            ceiling = f", ceiling {st['timeout_min']} min" if st.get("timeout_min") else ""
            out.append(f"{pad}$ (cd {ex.agent_dir(st.get('owner'))}) {shlex.join(argv)} "
                       f"< prompt  [skill {st.get('skill')}{ceiling}]")
        else:
            if st.get("decided_by") == "human":
                out.append(f"{pad}decision by human: nobody waits, takes `{st.get('default')}` "
                           + ("and leaves a quiet line, no notification (CF-0735)"
                              if st.get("notify") == "quiet" else "and leaves a NEEDS-YOU line"))
            else:
                argv = claude_decision_argv(ex.claude, st.get("model", "sonnet"))
                out.append(f"{pad}$ {shlex.join(argv[:-1])} <system> < question  "
                           f"[outcomes {st.get('outcomes')}, default {st.get('default')}]")
        return out

    rb = ex.state.get("rebuild") or {}
    if rb:
        src = rb.get("of") or {}
        lines.append(f"rebuild ({rb.get('task')}, mode {rb.get('mode')}) of "
                     f"{channel_ids.resolve_channel(src.get('channel'), ex.root)}/"
                     f"{src.get('batch_id')}: "
                     + ", ".join(v.get("slug") or v.get("script_id") for v in rb.get("videos") or []))
    for n, sid in enumerate(ex.order, 1):
        st = ex.by_id[sid]
        ss = ex.state.get("stages", {}).get(sid) or {}
        mk = f" <{st['marker']} by {st.get('marker_by')}>" if st.get("marker") else ""
        lines.append(f"{n:2d}. {sid}  {st['kind']}  {st['owner']}{mk}"
                     f"{run_plan._when_text(st.get('when'))}{' (always)' if st.get('always') else ''}")
        if ss.get("status") in TERMINAL:
            lines.append(f"      [{ss['status']}{': ' + ss['reason'] if ss.get('reason') else ''}]")
            continue
        lines += describe(st, 6)
        for k, v in ex.rebuild_args(sid).items():
            lines.append(f"      + {k}: {ex.expand(str(v), st.get('owner'))}")
    return lines


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def open_batches(root, env=None):
    """Directories `runlog batch-active` names as open (empty when none)."""
    try:
        cp = subprocess.run([str(Path(root) / "scripts" / "runlog"), "batch-active",
                             "--root", str(root)], capture_output=True, text=True,
                            timeout=120, env=env)
    except (OSError, subprocess.SubprocessError):
        return []
    if cp.returncode != 0:
        return []
    return [Path(line.strip()).resolve() for line in cp.stdout.splitlines() if line.strip()]


def acquire_lock(batch):
    batch.mkdir(parents=True, exist_ok=True)
    fh = open(batch / LOCK_FILE, "a+")
    for attempt in range(LOCK_TRIES):
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            # CF-0670: `runlog.open_batches` probes a held-or-not lock with a
            # shared flock for a moment - a probe is not another executor.
            if attempt + 1 < LOCK_TRIES:
                time.sleep(LOCK_RETRY_S)
    else:
        fh.seek(0)
        holder = fh.read().strip()
        fh.close()
        raise Refused(f"another executor holds {batch / LOCK_FILE}"
                      + (f" ({holder})" if holder else ""))
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid {os.getpid()} since {now_iso()}\n")
    fh.flush()
    return fh


def new_state(root, channel, plan, batch, order):
    return {"version": STATE_VERSION, "task": TASK, "channel": channel, "root": str(root),
            "batch": str(batch), "batch_id": batch.name, "plan_fingerprint": fingerprint(plan),
            "order": order, "status": "new", "created": now_iso(), "current": None,
            "next": order[0] if order else None,
            "stages": {sid: {"status": "pending"} for sid in order},
            "handlers": {}, "decisions": {}, "runs": {}, "reruns": {}, "needs_human": [],
            "executor": {}}


def bus_notifier(root):
    """CF-0591: the executor's notifications through `shared/notify.py`, linked
    to the channel's batch section of the console; None when the bus cannot be
    loaded (a notification is never on the critical path)."""
    try:
        import notify as bus                    # shared/ is on sys.path (HERE)
    except Exception:                                            # noqa: BLE001
        return None

    def send(kind, key, text, channel):
        # CF-0925: a text of several lines («батч готов» and its videos) keeps them for Telegram
        return bus.send(kind, key, text, channel=channel, link=bus.link_of(channel, "batch"),
                        root=Path(root), multiline="\n" in str(text))
    return send


def cmd_run(ns):
    root = Path(ns.root).resolve() if ns.root else ROOT
    try:
        plan = run_plan.load(ns.channel, root)
    except run_plan.PlanError as e:
        print(f"run_executor: {e}", file=sys.stderr)
        return EXIT_REFUSED
    errs = run_plan.validate(plan, root)
    if errs:
        print(f"run_executor: the plan of {ns.channel} is not valid ({len(errs)} error(s)):",
              file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return EXIT_REFUSED
    order = run_plan.order(plan)
    if ns.until and ns.until not in order:
        print(f"run_executor: --until {ns.until!r} is not a stage of the plan", file=sys.stderr)
        return EXIT_REFUSED
    if ns.resume:
        batch = Path(ns.resume).resolve()
    elif ns.batch:
        batch = Path(ns.batch).resolve()
    else:
        tmpl = plan.get("batch_dir", "pipeline/{channel}/{batch_id}")
        batch = (root / tmpl.format(channel=ns.channel, batch_id=new_batch_id())).resolve()
    refusal = run_plan.start_refusal(ns.channel, root)
    if refusal and not ns.dry_run:
        print(f"run_executor: {ns.channel} не стартует - {refusal} (CF-0659)", file=sys.stderr)
        return EXIT_REFUSED
    if ns.dry_run:
        if refusal:
            print(f"НЕ СТАРТУЕТ (CF-0659): {refusal} - `run` без --dry-run откажет")
        # CF-0668: with --resume the dry run reads the state it would go on from
        # (a rebuild's starting state: the copied stages already skipped).
        state = None
        if ns.resume and (batch / STATE_FILE).is_file():
            try:
                state = json.loads((batch / STATE_FILE).read_text())
            except (OSError, ValueError) as e:
                print(f"run_executor: --resume {batch}: {STATE_FILE} unreadable ({e})",
                      file=sys.stderr)
                return EXIT_REFUSED
            for sid in order:
                state.setdefault("stages", {}).setdefault(sid, {"status": "pending"})
        ex = Executor(root, ns.channel, plan, batch,
                      state or new_state(root, ns.channel, plan, batch, order), claude=ns.claude)
        for line in dry_run_lines(ex):
            print(line)
        return EXIT_DONE
    state_path = batch / STATE_FILE
    if ns.resume:
        if not state_path.is_file():
            print(f"run_executor: --resume {batch}: no {STATE_FILE} there", file=sys.stderr)
            return EXIT_REFUSED
    else:
        if state_path.exists():
            print(f"run_executor: {batch} already has {STATE_FILE} - resume it with "
                  f"--resume {batch}", file=sys.stderr)
            return EXIT_REFUSED
        busy = [d for d in open_batches(root) if d != batch]
        if busy:
            print(f"run_executor: a batch is open: {', '.join(map(str, busy))} - one batch at "
                  f"a time; close it (runlog batch-done) or resume it", file=sys.stderr)
            return EXIT_REFUSED
    try:
        lock = acquire_lock(batch)
    except Refused as e:
        print(f"run_executor: {e}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        if ns.resume:
            state = json.loads(state_path.read_text())
            if state.get("plan_fingerprint") != fingerprint(plan) and not ns.plan_changed_ok:
                print(f"run_executor: the plan of {ns.channel} changed since this run started "
                      f"({state.get('plan_fingerprint')} -> {fingerprint(plan)}); "
                      f"--plan-changed-ok to go on with the new one", file=sys.stderr)
                return EXIT_REFUSED
            state["plan_fingerprint"] = fingerprint(plan)
            state["order"] = order
            for sid in order:
                state["stages"].setdefault(sid, {"status": "pending"})
            for k in ("handlers", "decisions", "runs", "reruns"):
                state.setdefault(k, {})
            state.setdefault("needs_human", [])
            state.setdefault("resumed", []).append(now_iso())
            for h in state.get(LOGIN_HALTS_KEY) or []:            # CF-0899
                if isinstance(h, dict) and not h.get("resumed"):
                    h["resumed"] = state["resumed"][-1]
        else:
            state = new_state(root, ns.channel, plan, batch, order)
        state["executor"] = {"pid": os.getpid(), "started": now_iso(),
                             "argv": [sys.executable, *sys.argv]}
        ex = Executor(root, ns.channel, plan, batch, state, poll=ns.poll,
                      max_reruns=ns.max_reruns, claude=ns.claude, minute_s=ns.minute_s,
                      kill_grace_s=ns.kill_grace_s,
                      notifier=None if ns.no_notify else bus_notifier(root))
        ex.save()
        return ex.run(until=ns.until)
    finally:
        lock.close()


def cmd_status(ns):
    path = Path(ns.batch) / STATE_FILE
    try:
        st = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        print(f"run_executor: cannot read {path} ({e})", file=sys.stderr)
        return EXIT_REFUSED
    print(f"{st.get('batch')}: {st.get('status')}"
          + (f" - {st['halt_reason']}" if st.get("halt_reason") else "")
          + (f"; next {st['next']}" if st.get("next") else ""))
    for sid in st.get("order", []):
        s = st["stages"].get(sid, {})
        print(f"  {sid:<30} {s.get('status', 'pending'):<8} {s.get('reason', '')}")
    cur = st.get("current") or {}
    if cur.get("run"):
        rec = st["runs"].get(cur["run"], {})
        alive = rec.get("pid") and rec.get("exit") is None and \
            pid_alive(rec["pid"], str(Path(st["batch"]) / rec.get("exit_file", "")))
        print(f"  current: {cur['run']} pid {rec.get('pid')} "
              f"{'alive' if alive else 'exit ' + str(rec.get('exit'))}")
    for h in st.get("needs_human", []):
        print(f"  NEEDS-YOU {h['stage']}: took {h['took']}")
    for h in st.get("quiet", []):                                # CF-0735
        print(f"  тихо {h['stage']}: {h['line']}")
    return EXIT_DONE


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_exec"]:
        return exec_main(argv[1:])
    ap = argparse.ArgumentParser(prog="run_executor.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("channel")
    r.add_argument("--root", default=None)
    g = r.add_mutually_exclusive_group()
    g.add_argument("--batch", default=None, help="a new batch directory (default: the plan's batch_dir)")
    g.add_argument("--resume", default=None, metavar="DIR", help="go on with the run in DIR")
    r.add_argument("--until", default=None, metavar="STAGE")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--max-reruns", type=int, default=MAX_RERUNS)
    r.add_argument("--poll", type=float, default=POLL_SECONDS)
    r.add_argument("--claude", default=None, help=f"the claude binary (default ${CLAUDE_ENV}, PATH)")
    r.add_argument("--plan-changed-ok", action="store_true")
    r.add_argument("--no-notify", action="store_true",
                   help="no notification of a halt, the end, a human default (CF-0591)")
    r.add_argument("--minute-s", type=float, default=60.0, help=argparse.SUPPRESS)  # tests: a shorter minute
    r.add_argument("--kill-grace-s", type=float, default=KILL_GRACE_S, help=argparse.SUPPRESS)
    s = sub.add_parser("status")
    s.add_argument("batch")
    ns = ap.parse_args(argv)
    return cmd_run(ns) if ns.cmd == "run" else cmd_status(ns)


if __name__ == "__main__":
    sys.exit(main())

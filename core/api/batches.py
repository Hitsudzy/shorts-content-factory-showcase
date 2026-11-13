"""CC-0044: the batch schedule and the batches - the plan, the switch, a
channel's schedule settings, the runs and who launched them, a batch's stages
and logs. Only through the factory's own functions (`api/factory.py`):

    shared/batch_schedule.py   plan, switch_state / set_switch, channel_settings /
                               settings_history / validate_settings /
                               set_channel_settings, launches, msk_day / parse_ts,
                               timer_state
    shared/runlog/runs_table.py  read_rows - pipeline/runs.jsonl, one row per run
    shared/runlog/event_log.py   load_events - a batch's RUN_EVENTS.jsonl (its markers),
                                 cached, a grown journal read by its tail (CF-0718,
                                 CC-0119; the events read-only)

**Writes** (the switch, a channel's settings) are the factory's state, not
code: `schedule/switch.json` and `schedule/channel-settings.json` in the
schedule's state directory (`<root>/schedule/`, gitignored, or
`BATCH_SCHEDULE_STATE_DIR`). They never touch a file in git and never move the
root's HEAD, so an open batch does not refuse them (unlike a channel's config,
`api/channels.py`): the factory's own rule - the tick and the console read the
switch and the overlay afresh every time. Who writes is always `user` (the
center is the user's hands); the note is prefixed `центр: `. Turning the
switch **on** needs a note of the user's own - where and when they said
«включай» (`set_switch` takes `enable` only `by user`, with a note); an empty
one is refused before the factory is called, since the prefix alone would
make it non-empty.

Nothing here starts, stops, resumes or rebuilds a batch but four functions,
each the user's own press in the center after a plan and a confirmation:
`launch` (CC-0046, «запускай»), `stop` and `resume` (CC-0047, «остановить» /
«продолжить» - `shared/batch_control.py`), `rebuild` (CC-0048, «пересобрать
ролики»); `tick` is never called, and nothing here spawns or signals a
process itself.

**The timer** (`timer_state`, the launchd plist of the tick, macOS only): the
plan carries its line (`timer`) as the factory says it - a file check, no
launchctl; on another OS the line says it is not checked there
(docs/platform-audit.md, П6).

**A batch's stages**: `pipeline/<channel>/<batch_id>` - the markers of its
events (batch-start, stage-start / stage-done, batch-done), the stages they
span, and the files `logs/*.log` of the batch. A log's tail is read on request,
at most TAIL_MAX bytes, and only a file of that listing: the name has no
separator, it resolves inside `<batch>/logs/` (a symlink out is refused).

**The batches going** (CC-0045): the list is the console's own
(`shared/factory_state.py` `batches` over `runlog.open_batches` - every
open batch, stale ones too, `fresh` says which; each with its stage, elapsed,
the stage's ceiling `timeout_min` and the estimate to the end from the mean
wall of the channel's runs, `mean_wall` - computed by `collect`, nothing of
the API's own). It reads every open batch's RUN_EVENTS.jsonl whole, so it is
a kept scan refreshed in the background (`channels.cached_scan`, the
machinery of the open batches, CC-0041): a read answers the last result with
`checked_at` / `age_s` / `checking` and never waits, past the first one. The
times in it are as of `as_of`, the moment the scan computed them. A stopped
batch (CF-0667, `status: stopped`) has no batch-done, so it stays in the list
with its status.

**One batch** (CC-0045): its `run-state.json` whole (the executor's, CF-0203:
stages, `runs` - every process with `alive` from `run_executor.pid_alive`, a
`ps` read, no signal - reruns, needs_human, halt_reason, `stops` when the
factory writes them; `quiet` - CF-0735's quiet human decisions, also as
the answer's own `quiet`, paths cut) and its channel's live questions (`shared/needs_you.py`
`questions`, what `GET /api/questions` reads; a checkout where they do not
read - no `shared/needs_you.py` - answers `questions: []` and the reason as
`questions_error`, CC-0053). A batch with no run-state.json
(markers only) says so (`state: null`). `code_edits` (CC-0111, CF-0713): what
a batch stage changed in the factory's tracked code - run-state.json
`code_edits[]` as `run_executor.record_code_edits` writes it, else the
journal's `stage_code_edit` events; each row with every file from the root
and `shared/stage_code_guard.py` `describe`'s line; in the list, the console's
lines (`collect`) and `code_edits_count`.

**A batch's events** (CC-0045): `RUN_EVENTS.jsonl` by byte cursor - `after`
the offset the last answer gave as `next`; whole lines only (a line being
written is left for the next poll), at most EVENTS_LIMIT_MAX lines and
EVENTS_BYTES_MAX bytes read per request, so a 43 MB journal is never read
whole. No `after`: the tail. A cursor past the end (the file was replaced)
answers the tail with `reset: true`. Polling, not SSE (a stream would hold a
pool thread per viewer): the answer carries `poll_s`, the interval to ask
again at - EVENTS_POLL_S while the batch writes, the list's LIST_POLL_S.

**The launch** (CC-0046): two steps, the console's button made two calls.
`launch_plan` is `batch_schedule.launch_check` (read only: the guards, the
executor's `argv`, the checks a manual start skips) and, when every guard
holds, a confirm token: kept here, in this process (`_TOKENS`), bound to the
factory root, the channel and a fingerprint of the check (`_fingerprint`:
sha256 of the channel, the Moscow day, the argv, every guard's name, verdict
and line, the skipped lines), alive CONFIRM_TTL seconds, used once - any
`launch` that presents it spends it, whatever comes of it. `launch` checks
the token (known, of this root and channel, not expired), runs `launch_check`
again and compares the fingerprint (a batch opened, the day turned, the plan
changed: refused - a failing guard's own Russian line as is, else
«проверка изменилась»), then `manual_launch(confirmed=True, by="user
(центр)")` - the factory's own detached start (`spawn_detached`, its log in
`schedule/logs/`, a `launches.jsonl` row, the `batch_started` notice), which
checks every guard once more under the tick's lock. It answers at once: pid,
log, the row. Launches go one at a time (`_LAUNCH`), so two confirms never
both start one. The factory's refusals (`why`, `line`) are passed as they
are - «1 батч в сутки» too. **Logging in** (CC-0176, the factory's CF-0899): before
`manual_launch` the launch asks `batch_schedule.login_state(root, environ)` - the
very check the tick makes before it opens a batch (`claude auth status --json`,
no tokens): `ok` false - refused `not_logged_in` with the factory's line, the
batch not opened, nothing written; `ok` null (unknown: no binary, a timeout, a
root that is not the factory's without `RUN_EXECUTOR_CLAUDE`) holds nothing, as
in the tick - the launch goes on and the answer's `login` carries the line as a
warning; `ok` true - as before, with `login` too. The plan carries `login` as
well (not a guard, not in the fingerprint, the token is issued by the guards
alone). The probe is not under `_SCHED`. `FACTORY_KW` is the factory's own injection
points (`executor=`, `open_rows=`, `now=`, `environ=`), empty in production:
only the tests fill it (a stand-in executor, a temp state directory).

**Stop and resume** (CC-0047): the same two steps over `shared/batch_control.py`
(CF-0667), whose answer (`ok`, the Russian `reason`, the executor's pid and
group, the step) is passed as is. `stop_plan` is `stop_check` (read only),
`resume_plan` is `resume_check` (read only: the executor dead, the status
halted/paused/failed/stopped - or running/new with a dead executor - no other
fresh batch, the plan unchanged); when it says ok, a confirm token of the
launch's machinery (`_issue` / `_spend`: the same store, life and single use),
bound to the root, the batch directory, the action, for a stop `also_step`,
and a fingerprint of the check (`_control_fingerprint`: the status, the
executor's pid, group and liveness, the lock, the step's pid, the argv a
resume would start). `stop` / `resume` take the batch's control lock
(`_CONTROLS`, one stop or resume of a batch at a time; a second while one is
going is `busy` at once, never queued, and its token is not spent), spend the
token, run the check again and compare (a refusal now: the factory's `reason`
as is; otherwise changed: `check_changed`), then `batch_control.stop(batch,
by="user (центр)", confirmed=True, also_step)` or `batch_control.resume(batch,
by="user (центр)", confirmed=True)`. **The wait is the factory's, bounded**:
a stop waits for the executor to die at most `grace_s` (GRACE_S, 30 s) after
its SIGTERM, and with `also_step` at most `grace_s` more for the step - so a
stop answers within about 2 x 30 s plus the `ps` calls; it never SIGKILLs (an
executor that survives is answered `ok: false` with the `kill -9 -<pgid>`
line for the user's own hands). A resume waits at most RESUME_TAKE_S (15 s)
for the new executor to take the lock. Nothing was touched (the factory
refused before a signal or a start): a `BatchFault` with its `reason` - a
stop's `refused`, a resume's the factory's `code` (CF-0739 `RESUME_CODES`,
`refused` from a factory without codes) with the center's Russian line of
`RESUME_CODES` before the factory's; something was done: 200 with the
factory's dict whatever its `ok` (`stopped`, `step_killed`,
`step_left_running`, `executor_signalled` - or `resumed`, `pid`, `log`, `row`
`kind: resume`, `exit`, a resume's `code` - `exited_at_once` - and
`message`). The resume plan carries `code` / `message` too. `FACTORY_KW` may carry
`grace_s` / `take_s` too - only in the tests.

**The rebuild** (CC-0048): «пересобрать ролики» of a finished batch over
`batch_control.rebuild_check` / `rebuild` (CF-0668), the same two steps.
`rebuild_modes` lists the modes of the batch's channel (id, title, the stage it
starts at) off the factory's run plan reader (`run_plan.load` /
`rebuild_modes`) - nothing parsed here. `rebuild_plan(videos, mode, notes)` is
`rebuild_check` (read only: the source closed, no other batch or rebuild open,
the videos in its `05`, the exclusions only for a mode that takes them, their
blocks in the storyboard) and, when ok, a token bound to the root, the batch,
the action, the videos, the mode and the notes, and to a fingerprint of the
whole check (`_rebuild_fingerprint`: the layout, the copies, the videos with
their exclusions and notes, the source, the verdict). `rebuild(confirm)`
sends nothing else - the videos, the mode and the notes are the token's. It
goes one at a time with the launches (`_LAUNCH`: a rebuild opens a batch),
spends the token, checks again and compares (refused: the factory's `reason`
as is; changed: `check_changed`), then `batch_control.rebuild(confirmed=True,
by="user (центр)")` - `pipeline/rebuilds/<ts>`, the copies, `batch-start`,
the executor detached on `--resume`, a `launches.jsonl` row `kind: rebuild`,
the `batch_started` notice; «1 батч в сутки» does not apply to it. It answers
at once (the factory waits at most RESUME_TAKE_S for the lock). Seconds of the
video -> storyboard blocks for the exclusions is the factory's `blocks_at`
(CF-0669): `blocks` (CC-0049, `GET .../videos/{slug}/blocks?at=12,18,24`)
answers it as is, and the screen sends the block exclusions it gave into the
notes - the notes themselves take block numbers only (`SECONDS_TO_BLOCKS`).

**The stranded batches** (CC-0114, the factory's CF-0723): `stranded` is
`batch_schedule.stranded_batches(root, now)` as is - the batches (and
rebuilds) whose `run-state.json` says the run stopped badly
(failed/halted/stopped), with no `pipeline/runs.jsonl` row and not open (a
stale open one, > 24 h, is listed), what `batch_schedule.py stranded --json`
prints; `holds_day` is the factory's (a rebuild never holds the day). The
selection is the factory's only: here a channel filter (the row's own
`channel`), a `limit` in the factory's order, `batch` («<dir>/<batch_id>»,
the path of the other batch routes, as `GoingBatch.batch`), `log_name` - the
`{name}` of `GET /api/batches/{channel}/{batch_id}/logs/{name}` when the
row's `log` is a file `<dir>/logs/<name>` that route serves (`_logs`), else
null (a launch's log in `schedule/logs/` has no route) - and `log_url`, that
route. A failed read is the answer's `error`
(the factory's exception), not a refusal.

Every refusal is a `BatchFault`: a Russian `message` (shown as is), a `code`,
the technical `details` (behind «подробнее»).
"""
import hashlib
import json
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from . import channels, factory, paths

NOTE_PREFIX = "центр"
BY = "user"
HISTORY_LIMIT = 200
STRANDED_LIMIT = 20
STRANDED_LIMIT_MAX = 200
PLAN_DAYS_MAX = 31
TAIL_DEFAULT = 64 * 1024
TAIL_MAX = 1024 * 1024
LOGS_DIR = "logs"
PIPELINE_DIR = "pipeline"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,199}$")
#: batch_schedule loads its neighbours (`collect` and what it loads) by its own
#: loader, not under `factory._mod`'s lock: every call into it goes one at a
#: time (a plan is ~0.2 s).
_SCHED = threading.Lock()
_MARKERS = {}               # str(events path) -> ((mtime_ns, size), markers)
_MARKERS_KEEP = 16
_MARKERS_LOCK = threading.Lock()


#: The list of the batches going: a kept scan (`channels.cached_scan`) - past
#: VIEW_TTL seconds a read starts one refresh in the background and answers
#: the last result; VIEW_WAIT: seconds a read waits for it (0 - never; the
#: tests set it high).
VIEW_TTL = 15.0
VIEW_WAIT = 0.0
_VIEWS = {}                 # str(root) -> channels._Scan
#: The recommended poll intervals, seconds: the list (no faster than its
#: refresh) and a batch's events.
LIST_POLL_S = 15
EVENTS_POLL_S = 3
EVENTS_LIMIT = 200
EVENTS_LIMIT_MAX = 1000
EVENTS_BYTES_MAX = 1024 * 1024
LINE_TEXT_MAX = 2000        # an unparsable line is shown cut to this

#: The launch (CC-0046): who the factory writes in `launches.jsonl`, how long
#: a confirm token lives, how many are kept, how long a launch waits for one
#: going before it (seconds).
LAUNCH_BY = "user (центр)"
CONFIRM_TTL = 120.0
TOKENS_MAX = 32
LAUNCH_WAIT = 30.0
#: The factory's own injection points of `launch_check` / `manual_launch`
#: (`executor`, `open_rows`, `now`, `environ`) - empty in production; the
#: tests put a stand-in executor and planted open rows here.
FACTORY_KW = {}
_FACTORY_KEYS = ("executor", "open_rows", "now", "environ", "grace_s", "take_s")
_TOKENS = {}                # token -> {root, action, key, bound, fingerprint, expires, at}
_TOKENS_LOCK = threading.Lock()
_LAUNCH = threading.Lock()  # one launch at a time
#: Stop and resume (CC-0047): who the factory writes, one control of a batch
#: at a time (str(batch dir) -> Lock).
CONTROL_BY = LAUNCH_BY
_CONTROLS = {}
_CONTROLS_LOCK = threading.Lock()
#: What a token is of, for the lines: the plan to ask again, what did not happen.
_ACTIONS = {"launch": ("план запуска", "батч не запущен", "запуска канала"),
            "stop": ("план остановки", "батч не остановлен", "остановки батча"),
            "resume": ("план продолжения", "батч не продолжен", "продолжения батча"),
            "rebuild": ("план пересборки", "пересборка не начата", "пересборки роликов батча"),
            "rerun_from": ("план повтора", "повтор не начат", "повтора батча со стадии")}
_clock = time.monotonic     # the tests turn it to expire a token


class BatchFault(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = [str(d) for d in (details or [])]

    def body(self):
        return {"message": self.message, "code": self.code, "details": self.details}


def _bs():
    return factory.batch_schedule()


def _note(note):
    note = (note or "").strip()
    return f"{NOTE_PREFIX}: {note}" if note else NOTE_PREFIX


def _channel(root, name):
    cid = factory.resolve_channel(root, name)
    if cid not in factory.channel_list(root):
        raise BatchFault(404, "unknown_channel", f"Канала «{name}» нет в фабрике.",
                         [f"no {factory.CHANNELS_SUBDIR}/{cid}.json under {root}"])
    return cid


# ---------------------------------------------------------------- the plan
def timer_line():
    """The tick's timer, as the factory's `timer_state` says it - launchd is
    macOS's; elsewhere it is not checked (docs/platform-audit.md П6)."""
    if sys.platform != "darwin":
        return (f"таймер тика не проверяется на этой ОС ({sys.platform}): установка - launchd, "
                f"только macOS (docs/platform-audit.md, П6)")
    try:
        return _bs().timer_state()["line"]
    except Exception as e:                                      # noqa: BLE001
        return f"таймер тика не читается ({type(e).__name__}: {e})"


def schedule(root, days=None):
    """`batch_schedule.plan` for `days` Moscow days, plus the timer's line."""
    bs = _bs()
    try:
        with _SCHED:
            p = bs.plan(root, days=days or bs.PLAN_DAYS)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "schedule_broken", "План батчей не строится - фабрика ответила "
                                                 "ошибкой.", [f"{type(e).__name__}: {e}"])
    p["timer"] = timer_line()
    return p


def switch(root, on, note=None):
    """`set_switch(on, "user", "центр: <note>")`; on needs a note of its own."""
    bs = _bs()
    if on and not (note or "").strip():
        raise BatchFault(422, "note_required",
                         "Чтобы включить расписание, нужна заметка: где и когда пользователь "
                         "сказал «включай».", ["set_switch(on=True) needs a note (ENABLE_BY: user)"])
    try:
        with _SCHED:
            return bs.set_switch(bool(on), BY, _note(note), root)
    except bs.ScheduleError as e:
        raise BatchFault(409, "refused", "Фабрика не приняла переключатель расписания.",
                         [str(e)]) from e


# ---------------------------------------------------------------- a channel's settings
def channel_schedule(root, name):
    cid = _channel(root, name)
    bs = _bs()
    with _SCHED:
        return {"channel": cid, "settings": bs.channel_settings(cid, root),
                "history": list(reversed(bs.settings_history(root, channel=cid)))}


#: CC-0152 (CF-0830): a window of `windows` - two-digit HH:MM, as the factory's
#: validate_settings takes it; at most MAX_WINDOWS of them.
WINDOW_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MAX_WINDOWS = 4


def _windows(value):
    """CC-0152: the center's own check of `windows` before the factory's - a
    list of 1-4 "HH:MM" strings, [] to remove; BatchFault 422 invalid
    otherwise (the factory's validate_settings checks it again)."""
    if not isinstance(value, (list, tuple)):
        raise BatchFault(422, "invalid", "Настройка не принята: окна запуска - список времён "
                                         "ЧЧ:ММ.", [f"windows {value!r}: not a list"])
    if len(value) > MAX_WINDOWS:
        raise BatchFault(422, "invalid", f"Настройка не принята: окна запуска - не больше "
                                         f"{MAX_WINDOWS}.",
                         [f"windows: {len(value)} values, at most {MAX_WINDOWS}"])
    for x in value:
        if not isinstance(x, str) or not WINDOW_RE.match(x.strip()):
            raise BatchFault(422, "invalid", f"Настройка не принята: окна запуска: {x!r} - "
                                             f"время ЧЧ:ММ, 00:00-23:59.",
                             [f"windows {x!r}: not HH:MM (00:00-23:59)"])
    return [x.strip() for x in value]


#: CC-0184 (CF-0922): the factory's refusal of a batch threshold below the feed's
#: horizon (batch_schedule.window_config): "... batch_feed_days 4 < min_feed_days 5:
#: порог батча не меньше горизонта ленты (CF-0922)".
THRESHOLD_REFUSED_RE = re.compile(r"batch_feed_days (\d+) < min_feed_days (\d+):\s*([^(]+)")


def _settings_refused(cid, e):
    """The 409's message: the factory's own Russian reason when it refuses a
    batch threshold below the horizon (the rule is the factory's, not the
    API's), the general words otherwise; `details` carry its text as is."""
    m = THRESHOLD_REFUSED_RE.search(str(e))
    if m:
        return (f"Фабрика не приняла настройки расписания канала {cid}: "
                f"{m.group(3).strip()} - порог батча {m.group(1)} дн., горизонт ленты "
                f"{m.group(2)} дн.")
    return f"Фабрика не приняла настройки расписания канала {cid}."


def set_settings(root, name, body):
    """`set_channel_settings(<ch>, changes, "user", "центр: <note>")` - the
    changes are the keys of `body` that are not None. CC-0152: `windows` []
    removes the key (the route turns an explicit null into [])."""
    cid = _channel(root, name)
    bs = _bs()
    changes = {k: body[k] for k in bs.SETTINGS_KEYS if body.get(k) is not None}
    if "windows" in changes:
        changes["windows"] = _windows(changes["windows"])
    try:
        bs.validate_settings(changes)
    except bs.ScheduleError as e:
        raise BatchFault(422, "invalid", f"Настройка не принята: {e}", [str(e)]) from e
    try:
        with _SCHED:
            res = bs.set_channel_settings(cid, changes, BY, _note(body.get("note")), root)
            hist = bs.settings_history(root, channel=cid)
    except bs.ScheduleError as e:
        raise BatchFault(409, "refused", _settings_refused(cid, e), [str(e)]) from e
    return {"channel": cid, "changed": res["changed"], "settings": res["settings"],
            "history": list(reversed(hist))}


# ---------------------------------------------------------------- the runs
def _before(bs, at, limit):
    """A launch row's `at` is not later than `limit`; False when it does not parse."""
    try:
        return bs.parse_ts(at) <= limit
    except Exception:                                           # noqa: BLE001
        return False


def history(root, channel=None, limit=50):
    """The runs of `pipeline/runs.jsonl` (`runs_table.read_rows`), newest first,
    each with the launch of the schedule's journal (`launches`) of its channel
    and Moscow day - the tick or the console's button; none: started by hand
    in chat (or before the journal). And the journal's own rows."""
    cid = _channel(root, channel) if channel else None
    bs = _bs()
    with _SCHED:
        rows = factory.runs_table().read_rows(root)
        launches = bs.launches(root)

        def chan(x):
            return factory.resolve_channel(root, x.get("channel")) if x.get("channel") else None

        runs = [dict(r, channel=chan(r)) for r in rows if isinstance(r, dict)]
        launches = [dict(x, channel=chan(x)) for x in launches]
        if cid:
            runs = [r for r in runs if r["channel"] == cid]
            launches = [x for x in launches if x["channel"] == cid]
        # CC-0152: a row that starts no batch (resume, rebuild, CF-0822's repeat_held)
        # is no run's launch; with two batches a day (CF-0830) a run takes the day's
        # last launch at or before its start (+ the factory's LAUNCH_MATCH), else the
        # day's first
        skip = set(getattr(bs, "NOT_A_BATCH_KINDS", ()))
        slack = getattr(bs, "LAUNCH_MATCH", timedelta(minutes=30))
        by_day = {}
        for x in sorted(launches, key=lambda x: str(x.get("at") or "")):
            if x.get("kind") not in skip:
                by_day.setdefault((x["channel"], x.get("day")), []).append(x)
        for r in runs:
            t = bs.parse_ts(r.get("started")) if r.get("started") else None
            day = bs.msk_day(t).isoformat() if t else None
            got = by_day.get((r["channel"], day)) if day else None
            if got:
                at = [x for x in got if x.get("at") and _before(bs, x["at"], t + slack)]
                r["launch"] = at[-1] if at else got[0]
            else:
                r["launch"] = None
    runs.sort(key=lambda r: str(r.get("started") or r.get("id") or ""), reverse=True)
    launches.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
    return {"channel": cid, "runs": runs[:limit], "launches": launches[:limit]}


# ---------------------------------------------------------------- stranded (CC-0114)
def _log_name(root, row):
    """The `{name}` of `GET /api/batches/{channel}/{batch_id}/logs/{name}` for
    the row's `log` when it is `pipeline/<dir>/<batch_id>/logs/<name>` and
    `log_tail` serves that name (`_logs` lists it), else None."""
    log, where = row.get("log"), row.get("dir")
    if not isinstance(log, str) or not isinstance(where, str):
        return None
    parts, lp = Path(where).parts, Path(log)
    if len(parts) != 3 or parts[0] != PIPELINE_DIR or lp.parent != Path(where) / LOGS_DIR:
        return None
    try:
        d = batch_dir(root, parts[1], parts[2])
    except BatchFault:
        return None
    if lp.name not in {x["name"] for x in _logs(root, d)}:
        return None
    return lp.name


def _stranded_row(root, r, prefix):
    """A factory row (cut) + `batch` («<dir>/<batch_id>», the path of the batch
    routes, as GoingBatch.batch), `log_name` and `log_url` (its route)."""
    name = _log_name(root, r)
    out = paths.clean(r, root)
    batch = (_path_of(r) if isinstance(r.get("dir"), str) and isinstance(r.get("batch_id"), str)
             else None)
    url = None
    if name is not None:
        parts = Path(r["dir"]).parts
        url = f"{prefix}/batches/{parts[1]}/{parts[2]}/{LOGS_DIR}/{quote(name)}"
    return dict(out, batch=batch, log_name=name, log_url=url)


def stranded(root, channel=None, limit=STRANDED_LIMIT, prefix=""):
    """{batches, as_of, error}: `batch_schedule.stranded_batches(root, now)` as
    the factory selects them, the channel's only (a known channel), the first
    `limit`, each with `log_url`; no absolute path (`paths.clean`)."""
    cid = _channel(root, channel) if channel else None
    bs = _bs()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        with _SCHED:
            rows = bs.stranded_batches(root, now=now)
        err = None
    except Exception as e:                                      # noqa: BLE001
        rows, err = [], f"{type(e).__name__}: {e}"
    rows = [r for r in rows if isinstance(r, dict) and (cid is None or r.get("channel") == cid)]
    # the factory's part through the one cutter (CC-0097/0098), the route after
    # it - a URL path is no path of this machine
    return {"batches": [_stranded_row(root, r, prefix) for r in rows[:limit]],
            "as_of": bs.iso(now), "error": paths.clean(err, root)}


# ---------------------------------------------------------------- a batch
def batch_dir(root, channel, batch_id):
    """`pipeline/<channel>/<batch_id>` - names without separators, inside
    `pipeline/` (`factory.contained`: a link `scripts/agents sync` made from a
    worktree to the working copy's batches is inside, CC-0053). The path as the
    factory lists it (`<root>/pipeline/...`, only the root resolved)."""
    for what, v in (("channel", channel), ("batch", batch_id)):
        if not SAFE_NAME.match(v or "") or v in (".", ".."):
            raise BatchFault(404, "unknown_batch", f"Батча «{channel}/{batch_id}» нет.",
                             [f"{what} {v!r}: not a directory name"])
    d = factory.contained(root, PIPELINE_DIR, channel, batch_id)
    if d is None or not d.is_dir():
        raise BatchFault(404, "unknown_batch", f"Батча «{channel}/{batch_id}» нет.",
                         [f"no directory {PIPELINE_DIR}/{channel}/{batch_id} under {root}"
                          if d is None or not d.exists() else
                          f"{PIPELINE_DIR}/{channel}/{batch_id} is not a directory"])
    return d


def _markers(d):
    """The marker events of the batch, kept per file state - a big batch's
    events are tens of MB. CC-0119 (CF-0718): read through the factory's
    `event_log.load_events` - what `runlog.read_events` gives, from its cache:
    a journal that only grew is read by its new tail. Its events are
    read-only (`Event`, a write is a TypeError): the markers are new dicts."""
    return _journal(d)[0]


def _journal(d):
    """(markers, code edit events) of the batch dir `d`, one read of its
    RUN_EVENTS.jsonl kept per file state (`_markers`). The second list is
    CC-0111's: every `stage_code_edit` event (CF-0713, the executor's), as new
    dicts."""
    rl = factory.runlog()
    path = Path(rl.events_path(d))
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return [], []
    with _MARKERS_LOCK:
        got = _MARKERS.get(str(path))
        if got and got[0] == key:
            return got[1], got[2]
    kind = _code_edit_kind()
    marks, edits = [], []
    for e in rl.sibling("event_log").load_events(d):
        if e.get("kind") == rl.KIND_MARKER:
            marks.append({"ts": e.get("ts"), "marker": e.get("status"), "stage": e.get("stage"),
                          "note": e.get("note")})
        elif kind and e.get("kind") == kind:
            edits.append(json.loads(json.dumps(dict(e), default=str)))
    with _MARKERS_LOCK:
        _MARKERS[str(path)] = (key, marks, edits)
        while len(_MARKERS) > _MARKERS_KEEP:
            _MARKERS.pop(next(iter(_MARKERS)))
    return marks, edits


# ---------------------------------------------------------------- code edits (CC-0111)
def _code_edit_kind():
    """`stage_code_guard.EVENT_KIND` - None in a checkout without CF-0713."""
    try:
        return factory.stage_code_guard().EVENT_KIND
    except Exception:                                           # noqa: BLE001
        return None


def _describe(edits):
    """The factory's one line of a row's edits (`stage_code_guard.describe`)."""
    try:
        return factory.stage_code_guard().describe(edits) or None
    except Exception:                                           # noqa: BLE001
        return None


def _edit_rows(edits):
    """[{repo, files, head_was, head_now}] - the factory's `edits[]` of a row,
    the rows that are objects, `files` a list of strings."""
    out = []
    for e in edits if isinstance(edits, list) else []:
        if not isinstance(e, dict):
            continue
        files = e.get("files") if isinstance(e.get("files"), list) else []
        out.append(dict(e, repo=e.get("repo"), files=[str(f) for f in files],
                        head_was=e.get("head_was"), head_now=e.get("head_now")))
    return out


def _from_root(edits):
    """Every file of `edits` from the factory root: a root file as it is, an
    agent's under its `agents/<name>/` (the repo label `stage_code_guard`
    records - `runlog.factory_repos`)."""
    rl = factory.runlog()
    root_label = getattr(rl, "ROOT_REPO", "root")
    return [f if e.get("repo") in (None, root_label) else f"{e['repo']}/{f}"
            for e in edits for f in e["files"]]


def code_edits(root, d, state):
    """CC-0111 (CF-0713): what the batch's stages changed in the factory's
    tracked code. run-state.json `code_edits[]` (`run_executor.record_code_edits`)
    when the state carries the key, else the journal's `stage_code_edit`
    events (a batch whose state is gone or never written). Each row the
    factory's `{stage, run, at, mode, task, edits}` with `files` - every file
    from the root - the factory's `describe` line and `source`; paths cut
    (`paths.clean`). [] for a batch before CF-0713."""
    rows = []
    if isinstance(state, dict) and isinstance(state.get("code_edits"), list):
        for r in state["code_edits"]:
            if isinstance(r, dict):
                rows.append(dict(r, source="state"))
    else:
        for e in _journal(d)[1]:
            rows.append({"stage": e.get("plan_stage") or e.get("stage"), "run": e.get("run"),
                         "at": e.get("ts"), "mode": e.get("status"), "task": e.get("task"),
                         "edits": e.get("edits"), "note": e.get("note"), "source": "events"})
    out = []
    for r in rows:
        edits = _edit_rows(r.get("edits"))
        out.append(dict(r, stage=r.get("stage"), run=r.get("run"), at=r.get("at"),
                        mode=r.get("mode"), task=r.get("task"), edits=edits,
                        files=_from_root(edits), line=_describe(edits)))
    return paths.clean(out, root)


def _spans(markers):
    """Each stage-start with the stage-done that closes it."""
    bs = _bs()
    spans, open_ = [], {}
    for m in markers:
        if m["marker"] == "stage-start":
            span = {"stage": m["stage"], "started": m["ts"], "done": None, "open": True,
                    "duration_s": None}
            spans.append(span)
            open_[m["stage"]] = span
        elif m["marker"] == "stage-done" and m["stage"] in open_:
            span = open_.pop(m["stage"])
            span.update(done=m["ts"], open=False)
            a, b = bs.parse_ts(span["started"]), bs.parse_ts(m["ts"])
            if a and b:
                span["duration_s"] = round((b - a).total_seconds(), 1)
    return spans


def _logs(root, d):
    """The files `logs/*.log` of the batch dir `d` (one `batch_dir` gave) -
    each `factory.contained` under `pipeline/` as the batch is: a symlink out
    of the batch is not listed (CC-0053: one guard for the dir and its logs)."""
    ld = d / LOGS_DIR
    out = []
    if not ld.is_dir():
        return out
    for p in sorted(ld.glob("*.log")):
        try:
            got = factory.contained(root, PIPELINE_DIR, d.parent.name, d.name,
                                    LOGS_DIR, p.name)
            if got is None or not p.is_file():
                continue
            st = p.stat()
        except OSError:
            continue
        out.append({"name": p.name, "size": st.st_size,
                    "modified": factory.utc_iso(st.st_mtime)})
    return out


def stages(root, channel, batch_id):
    d = batch_dir(root, channel, batch_id)
    marks = _markers(d)
    rl = factory.runlog()
    return {"batch": f"{channel}/{batch_id}", "channel": channel, "batch_id": batch_id,
            "markers": marks, "stages": _spans(marks),
            "open_stages": [s for s in rl._open_stages(
                [{"kind": rl.KIND_MARKER, "status": m["marker"], "stage": m["stage"]}
                 for m in marks])],
            **_closed(rl, d, marks), "logs": _logs(root, d)}


def _closed(rl, d, marks):
    """CC-0123: `{closed, open_why}` by the factory's rule (`runlog._batch_open`,
    CF-0739 - what `open_batches` decides by): a batch whose last batch-done is
    followed by a stage-start not closed, or by a new batch-start, is open
    again; a rework whose stages all closed is closed. A rebuild (no
    batch-done by design) is open while a stage-start is not closed. No
    markers: not closed. A factory without the rule: the last marker is
    batch-done."""
    if not marks:
        return {"closed": False, "open_why": None}
    path = rl.events_path(d)
    if Path(d).parent.name == "rebuilds" and hasattr(rl, "_is_open"):
        is_open = rl._is_open(path, rebuild=True)
        return {"closed": not is_open, "open_why": "стадия пересборки начата и не закрыта "
                                                   "(stage-start без stage-done)"
                if is_open else None}
    rule = getattr(rl, "_batch_open", None)
    if rule is None:
        closed = marks[-1]["marker"] == "batch-done"
        return {"closed": closed, "open_why": None if closed else "нет batch-done"}
    why = rule(path)
    return {"closed": why is None, "open_why": why}


def log_tail(root, channel, batch_id, name, size=TAIL_DEFAULT):
    """The last `size` bytes (at most TAIL_MAX) of `<batch>/logs/<name>`, from
    the first whole line; only a file `stages` lists."""
    d = batch_dir(root, channel, batch_id)
    known = {x["name"]: x for x in _logs(root, d)}
    if name not in known or "/" in name or "\\" in name:
        raise BatchFault(404, "unknown_log", f"Журнала «{name}» у батча {channel}/{batch_id} нет.",
                         [f"not a file of pipeline/{channel}/{batch_id}/{LOGS_DIR}/*.log"])
    size = max(1, min(int(size), TAIL_MAX))
    p = d / LOGS_DIR / name
    with open(p, "rb") as fh:
        fh.seek(0, 2)
        total = fh.tell()
        start = max(0, total - size)
        fh.seek(start)
        raw = fh.read(total - start)
    if start > 0:
        nl = raw.find(b"\n")
        cut = nl + 1 if 0 <= nl < len(raw) - 1 else 0
        raw, start = raw[cut:], start + cut
    return {"name": name, "size": total, "offset": start, "truncated": start > 0,
            "text": raw.decode("utf-8", errors="replace")}


# ---------------------------------------------------------------- the batches going (CC-0045)
def _path_of(b):
    """«<dir>/<batch_id>» of a listed batch - the path form of the routes
    (`pipeline/<dir>/<batch_id>`; for a rebuild the dir is `rebuilds`)."""
    return f"{Path(b['dir']).parent.name}/{b['batch_id']}"


def _executor(d, st=None):
    """CC-0110: `{executor_alive, lock_held, executor_why}` of the batch dir `d` -
    `batch_control.executor_of` (what `resume_check` / `stop_check` answer as
    `executor_alive` / `lock_held`: a stat when there is no lock file, else the
    lock's pid, a non-blocking probe and one `ps`) and, while the lock is held,
    `executor_lock.why` of its holder (the factory's line: the executor alive,
    or an unknown holder - CF-0667); none when nobody holds it. A check that
    raises: both null and the error as the why."""
    try:
        ex = _bc().executor_of(str(d), st)
        why = None
        if ex.get("lock_held"):
            xl = factory.executor_lock()
            why = xl.why(xl.holder(str(d), pid=ex.get("pid")))
        return {"executor_alive": bool(ex.get("alive")), "lock_held": bool(ex.get("lock_held")),
                "executor_why": why}
    except Exception as e:                                      # noqa: BLE001
        return {"executor_alive": None, "lock_held": None,
                "executor_why": f"исполнитель не проверяется ({type(e).__name__}: {e})"}


def _stage_reasons(stages, st):
    """CC-0110: each `{id, status}` of `collect` with its `reason` from
    run-state.json `stages[id].reason` (the executor's: «after failed stage
    …», «step 0 (…) exited 2; log …»), null where it has none."""
    ss = (st or {}).get("stages") if isinstance((st or {}).get("stages"), dict) else {}
    out = []
    for s in stages or []:
        if not isinstance(s, dict):
            out.append(s)
            continue
        rec = ss.get(s.get("id"))
        out.append(dict(s, reason=s.get("reason", (rec or {}).get("reason")
                                         if isinstance(rec, dict) else None)))
    return out


def _view_scan(root):
    """One scan: `collect.batches(root, now, runlog.open_batches(root, now))`,
    each with its executor (`_executor`) and its stages' reasons - in the kept
    scan, so the list's 15 s poll never probes a lock itself."""
    col, rl, bc = factory.collect(), factory.runlog(), _bc()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    open_rows = rl.open_batches(root, now=now)
    # CC-0123: why each is open - `OpenRow.why` (CF-0670 / CF-0739: «нет
    # batch-done», «снова открыт после batch-done: …», the executor alive)
    whys = {Path(r[0]).name + "\0" + Path(r[0]).parent.name: getattr(r, "why", None)
            for r in open_rows}
    rows = col.batches(root, now, open_rows=open_rows)
    base = Path(root).resolve()
    for b in rows:
        b["batch"] = _path_of(b)
        b["open_why"] = whys.get(b["batch_id"] + "\0" + Path(b["dir"]).parent.name)
        d = base / b["dir"]
        st = bc.read_state(str(d))
        b.update(_executor(d, st if st is not None else {}))
        if isinstance(b.get("stages"), list):
            b["stages"] = _stage_reasons(b["stages"], st)
        # CC-0111 (CF-0713): `code_edits` - the console's lines (collect, from
        # run-state.json); a batch whose state does not carry the key, from its
        # `stage_code_edit` events (the factory's describe line)
        if isinstance(st, dict) and isinstance(st.get("code_edits"), list):
            b["code_edits_count"] = len([r for r in st["code_edits"] if isinstance(r, dict)])
        else:
            ce = code_edits(root, d, st)
            b["code_edits_count"] = len(ce)
            if ce:
                b["code_edits"] = [f"{r['stage']}: {r['line'] or ', '.join(r['files'])}"
                                   for r in ce]
        if isinstance(b.get("code_edits"), list):
            b["code_edits"] = paths.clean(b["code_edits"], root)
    return {"as_of": col.iso(now), "batches": rows}


def warm(root):
    """The first scan of the list, in the background (`serve` at boot)."""
    channels.warm(root, _VIEWS, _view_scan, "cc-batches-going")


def going(root):
    """{batches, as_of, checked_at, age_s, checking, poll_s}: every open batch
    as the console shows it - see the module's docstring."""
    try:
        got, meta = channels.cached_scan(root, False, _VIEWS, _view_scan, VIEW_TTL, VIEW_WAIT,
                                         "cc-batches-going")
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "scan_broken", "Список идущих батчей не строится - фабрика "
                                             "ответила ошибкой.", [f"{type(e).__name__}: {e}"])
    return dict(meta, as_of=got["as_of"], batches=[dict(b) for b in got["batches"]],
                poll_s=LIST_POLL_S)


# ---------------------------------------------------------------- one batch (CC-0045)
def _alive(state, d, rec):
    """`run_executor.pid_alive` of a process that has no exit code yet, its
    token the exit file's path as the executor wrote it (`cmd_status`)."""
    if not isinstance(rec, dict) or not rec.get("pid") or rec.get("exit") is not None:
        return False
    base = Path(state.get("batch") or d)
    return bool(factory.run_executor().pid_alive(rec["pid"],
                                                 str(base / (rec.get("exit_file") or ""))))


def detail(root, channel, batch_id):
    """The batch's run-state.json whole, every process with `alive`, and its
    channel's live questions."""
    d = batch_dir(root, channel, batch_id)
    ex = factory.run_executor()
    state, err = None, None
    sp = d / ex.STATE_FILE
    if sp.is_file():
        try:
            state = json.loads(sp.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state, err = None, "run-state.json: not an object"
        except (OSError, ValueError) as e:
            err = f"run-state.json не читается ({e})"
    if state is not None:
        runs = state.get("runs")
        if isinstance(runs, dict):
            state["runs"] = {k: dict(r, alive=_alive(state, d, r)) if isinstance(r, dict) else r
                             for k, r in runs.items()}
    col = factory.collect()
    cid = col._batch_channel(d, root)
    qs, qs_err = [], None
    if cid:
        try:
            qs = factory.questions(root, "live", channel=cid)
        except Exception as e:                                  # noqa: BLE001
            # CC-0053: a checkout without the journal's module (the root's main
            # before 2.3 has no shared/needs_you.py) - the batch, no questions
            qs_err = f"вопросы не читаются ({type(e).__name__}: {e})"
    runs = (state or {}).get("runs") if isinstance((state or {}).get("runs"), dict) else {}
    # CF-0735: the quiet human decisions (`notify: quiet` in the plan) - a line
    # of the batch's journal each, no notification; paths cut (CC-0098)
    quiet = (state or {}).get("quiet")
    quiet = paths.clean([q for q in quiet if isinstance(q, dict)], root) \
        if isinstance(quiet, list) else []
    if state is not None and "quiet" in state:
        state["quiet"] = quiet
    # CF-0713 (CC-0111): what a stage changed in the factory's tracked code
    edits = code_edits(root, d, state)
    if state is not None and isinstance(state.get("code_edits"), list):
        state["code_edits"] = paths.clean([r for r in state["code_edits"]
                                           if isinstance(r, dict)], root)
    executor = _executor(d, state if state is not None else {})
    # CC-0119: the run-state goes out with its paths cut - `batch` (the
    # executor writes the batch's absolute directory), the processes'
    # `exit_file` / `log` / argv, a stage's verdict path, a halt reason that
    # names a file: inside the root relative, elsewhere `.../<name>`. Cut after
    # `_alive` and `_executor`, which need the paths as written. The questions
    # are not cut: their `link` is a center route (`/batches/...`), not a path.
    if state is not None:
        state = paths.clean(state, root)
    out = {"batch": f"{channel}/{batch_id}", "channel": cid, "batch_id": batch_id,
           "dir": col.rel(d, Path(root).resolve()), "state": state, "state_error": err,
           "status": (state or {}).get("status"), **executor,
           "alive": sorted(k for k, r in runs.items() if isinstance(r, dict) and r.get("alive")),
           "questions": qs, "questions_error": qs_err, "quiet": quiet,
           "code_edits": edits}
    return {k: v if k == "questions" else paths.clean(v, root) for k, v in out.items()}


# ---------------------------------------------------------------- a batch's events (CC-0045)
def _entry(off, line):
    text = line.decode("utf-8", errors="replace").rstrip("\r")
    try:
        ev = json.loads(text)
    except ValueError:
        ev = None
    if isinstance(ev, dict):
        return {"offset": off, "event": ev, "text": None}
    return {"offset": off, "event": None, "text": text[:LINE_TEXT_MAX]}


def events(root, channel, batch_id, after=None, limit=EVENTS_LIMIT):
    """{events [{offset, event | text}], next, size, more, reset, poll_s}:
    the whole lines of RUN_EVENTS.jsonl from byte `after` (None: the tail),
    at most `limit` lines and EVENTS_BYTES_MAX bytes read. `next` is the
    offset to ask from next time; `more`: whole lines past it are there now."""
    d = batch_dir(root, channel, batch_id)
    limit = max(1, min(int(limit), EVENTS_LIMIT_MAX))
    path = Path(factory.runlog().events_path(d))
    out = {"batch": f"{channel}/{batch_id}", "events": [], "next": 0, "size": 0,
           "more": False, "reset": False, "poll_s": EVENTS_POLL_S}
    try:
        fh = open(path, "rb")
    except FileNotFoundError:
        return out
    with fh:
        fh.seek(0, 2)
        size = fh.tell()
        reset = after is not None and int(after) > size
        tail = after is None or reset
        start = max(0, size - EVENTS_BYTES_MAX) if tail else max(0, int(after))
        if start > 0:                                   # begin at a whole line
            fh.seek(start - 1)
            if fh.read(1) != b"\n":
                start = _next_line(fh, start, size) or size
        fh.seek(start)
        raw = fh.read(min(EVENTS_BYTES_MAX, size - start))
        read_to = start + len(raw)
        end = raw.rfind(b"\n")
        lines, nxt, more = [], start, False
        if end >= 0:
            pos = []
            off = start
            for line in raw[:end + 1].split(b"\n")[:-1]:
                pos.append((off, line))
                off += len(line) + 1
            if tail:
                lines = pos[-limit:]
            else:
                lines, more = pos[:limit], len(pos) > limit
            nxt = lines[-1][0] + len(lines[-1][1]) + 1
            more = more or (read_to < size and _next_line(fh, read_to, size) is not None)
        elif len(raw) == EVENTS_BYTES_MAX:              # one line longer than a read
            past = _next_line(fh, read_to, size)
            if past is not None:                        # stepped over, shown cut
                lines, nxt = [(start, raw[:LINE_TEXT_MAX])], past
                more = _next_line(fh, past, size) is not None
        # else: nothing, or a line still being written - it is the next poll's
    out.update(events=[_entry(o, ln) for o, ln in lines], next=nxt, size=size, more=more,
               reset=reset)
    return out


def _next_line(fh, pos, size):
    """The offset just past the first newline at or after `pos`, or None -
    read in chunks, nothing kept."""
    fh.seek(pos)
    while pos < size:
        chunk = fh.read(min(64 * 1024, size - pos))
        if not chunk:
            break
        i = chunk.find(b"\n")
        if i >= 0:
            return pos + i + 1
        pos += len(chunk)
    return None


# ---------------------------------------------------------------- the launch (CC-0046)
def _kw():
    return {k: FACTORY_KW[k] for k in _FACTORY_KEYS if k in FACTORY_KW}


def _check(root, cid):
    """`batch_schedule.launch_check` - read only."""
    bs = _bs()
    kw = _kw()
    try:
        with _SCHED:
            return bs.launch_check(cid, root, kw.get("now"), kw.get("open_rows"),
                                   kw.get("environ"), kw.get("executor"))
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "schedule_broken", "Проверка запуска не выполняется - фабрика "
                                                 "ответила ошибкой.", [f"{type(e).__name__}: {e}"])


def _guard_batches(root, chk):
    """CC-0110: every guard of the check with `batches` - «<dir>/<batch_id>» of
    the batches it is about. `open`: the fresh rows of
    `batch_schedule.open_batches` (the very call the guard decides by, with the
    same injection points); a call that raises: null. Another guard: the row's
    own `batches` as the factory gives it, else null - `today` carries
    launch_check's own list (CF-0724: `started_on(records=True)` ->
    `started_batches`, `[]` when none; a launch whose folder is not made yet
    names none). The line text is never parsed. Not in the fingerprint: it
    names what the verdict already says."""
    kw = _kw()
    out, fresh = [], None
    for g in chk.get("guards") or []:
        g = dict(g)
        if g.get("name") == "open":
            if fresh is None:
                try:
                    bs = _bs()
                    with _SCHED:
                        fresh = [_path_of(b) for b in bs.open_batches(
                            Path(root).resolve(), bs.now_utc(kw.get("now")),
                            kw.get("open_rows"))[0]]
                except Exception:                               # noqa: BLE001
                    fresh = False
            g["batches"] = list(fresh) if fresh is not False else None
        else:
            g["batches"] = [str(x) for x in g["batches"]] \
                if isinstance(g.get("batches"), list) else None
        out.append(g)
    return dict(chk, guards=out)


def _fingerprint(chk):
    """sha256 of what the check decided: the channel, the day, the argv, every
    guard (name, verdict, line), the skipped checks."""
    return _digest({"channel": chk.get("channel"), "today": chk.get("today"),
                    "argv": chk.get("argv"),
                    "guards": [[g.get("name"), bool(g.get("ok")), g.get("line")]
                               for g in chk.get("guards") or []],
                    "skipped": list(chk.get("skipped") or []), "ok": bool(chk.get("ok"))})


def _digest(doc):
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()


def _prune(now):
    for t in [t for t, x in _TOKENS.items() if x["expires"] <= now]:
        _TOKENS.pop(t, None)
    while len(_TOKENS) >= TOKENS_MAX:
        _TOKENS.pop(min(_TOKENS, key=lambda t: _TOKENS[t]["at"]))


def _login(root):
    """CC-0176 (CF-0899): `{ok, checked, line}` - the factory's own
    `batch_schedule.login_state` (the tick's check before it opens a batch),
    with the injection point `environ` (tests: `RUN_EXECUTOR_CLAUDE` a stand-in).
    `ok` True / False / None (unknown); a check that raises is unknown too - it
    never holds a batch, as the factory's own unknown does not."""
    try:
        got = _bs().login_state(Path(root).resolve(), _kw().get("environ"))
    except Exception as e:                                      # noqa: BLE001
        return {"ok": None, "checked": False,
                "line": f"вход в claude не проверен - проверка фабрики упала ({type(e).__name__})"}
    got = got if isinstance(got, dict) else {}
    ok = got.get("ok")
    return {"ok": ok if isinstance(ok, bool) else None, "checked": bool(got.get("checked")),
            "line": str(got.get("line") or "вход в claude не проверен")}


def launch_plan(root, name):
    """{channel, ok, why, guards, argv, today, skipped, login, fingerprint,
    confirm, expires_in_s}: `launch_check`, and a confirm token when it says ok;
    `login` (CC-0176) is told, never a guard."""
    cid = _channel(root, name)
    chk = _check(root, cid)
    fp = _fingerprint(chk)
    out = dict(_guard_batches(root, chk), channel=cid, login=_login(root), fingerprint=fp,
               confirm=None, expires_in_s=None)
    if chk.get("ok"):
        out.update(confirm=_issue(root, "launch", cid, fp), expires_in_s=int(CONFIRM_TTL))
    return out


def _issue(root, action, key, fp, bound=None):
    """A confirm token of `action` on `key` (a channel for a launch, the batch
    directory for a stop or a resume): CONFIRM_TTL seconds, single use."""
    token = secrets.token_urlsafe(24)
    with _TOKENS_LOCK:
        now = _clock()
        _prune(now)
        _TOKENS[token] = {"root": str(Path(root).resolve()), "action": action, "key": key,
                          "bound": dict(bound or {}), "fingerprint": fp,
                          "expires": now + CONFIRM_TTL, "at": now}
    return token


def register_actions(actions):
    """CC-0065: another module's confirm actions on this one store (`_issue` /
    `_spend`: the same life, single use, the same refusals) - {action: (the
    plan to ask again, what did not happen, what the token is of)}. A name is
    registered once; the batches' own are never replaced."""
    for action, words in actions.items():
        have = _ACTIONS.get(action)
        if have is not None and tuple(have) != tuple(words):
            raise ValueError(f"confirm action {action!r} is already registered as {have!r}")
        _ACTIONS[action] = tuple(words)


def _label(action, key):
    """A launch's key is its channel, a stop's / resume's / rebuild's the batch
    directory (shown as <dir>/<id>); a key that is not a path (CC-0065: a
    publication action's channel) is shown as it is."""
    if action == "launch" or not Path(key).is_absolute():
        return key
    return f"{Path(key).parent.name}/{Path(key).name}"


def _spend(root, action, key, token):
    """The token's record, spent - or a BatchFault. Presenting a token spends
    it, whatever comes of it."""
    plan, nope, what = _ACTIONS[action]
    with _TOKENS_LOCK:
        got = _TOKENS.pop(token or "", None)
        now = _clock()
    if got is None or got["root"] != str(Path(root).resolve()):
        raise BatchFault(409, "confirm_unknown", f"Подтверждение не найдено или уже использовано - "
                                                 f"запросите {plan} заново.",
                         ["no such confirm token in this API process (used, unknown, or the "
                          "server restarted)"])
    if action == "launch" == got["action"] and got["key"] != key:
        raise BatchFault(409, "confirm_channel", f"Подтверждение выдано для канала "
                                                 f"{got['key']}, а не {key} - батч не запущен.",
                         [f"token of {got['key']}, launch asked for {key}; the token is spent"])
    if (got["action"], got["key"]) != (action, key):
        theirs = f"{_ACTIONS[got['action']][2]} {_label(got['action'], got['key'])}"
        raise BatchFault(409, "confirm_mismatch", f"Подтверждение выдано для {theirs}, а не для "
                                                  f"{what} {_label(action, key)} - {nope}.",
                         [f"token of {got['action']} {got['key']}, asked {action} {key}; "
                          f"the token is spent"])
    if got["expires"] <= now:
        raise BatchFault(409, "confirm_expired", f"Подтверждение устарело (живёт "
                                                 f"{int(CONFIRM_TTL)} с) - запросите {plan} "
                                                 f"заново.",
                         [f"expired {round(now - got['expires'], 1)} s ago"])
    return got


def launch(root, name, token):
    """{ok, line, channel, pid, log, row, login}: the confirmed token spent, the
    check the same as the plan's, claude logged in (CC-0176: `login_state` false
    - `not_logged_in`, nothing opened; unknown - goes on, `login` warns), then
    `manual_launch(confirmed=True, by=LAUNCH_BY)`."""
    cid = _channel(root, name)
    if not _LAUNCH.acquire(timeout=LAUNCH_WAIT):
        raise BatchFault(409, "busy", "Идёт другой запуск - подождите и запросите план заново.",
                         [f"the launch lock was not free in {LAUNCH_WAIT} s"])
    try:
        got = _spend(root, "launch", cid, token)
        chk = _check(root, cid)
        if _fingerprint(chk) != got["fingerprint"]:
            if not chk.get("ok"):
                raise BatchFault(409, "refused", chk.get("why") or "Фабрика отказала в запуске.",
                                 ["the check changed since the plan", *(
                                     f"{g['name']}: {g['line']}" for g in chk.get("guards") or []
                                     if not g.get("ok"))])
            raise BatchFault(409, "check_changed", "Проверка изменилась с момента плана - батч не "
                                                   "запущен; посмотрите план заново.",
                             ["the fingerprint of launch_check differs from the plan's"])
        login = _login(root)                            # CC-0176: the tick's check, CF-0899
        if login["ok"] is False:
            raise BatchFault(409, "not_logged_in", f"{login['line']} - батч не открыт.",
                             [login["line"], "batch_schedule.login_state: ok false "
                              "(claude auth status --json); the token is spent"])
        bs = _bs()
        kw = _kw()
        try:
            with _SCHED:
                ok, line, row = bs.manual_launch(cid, root, kw.get("now"), by=LAUNCH_BY,
                                                 confirmed=True, executor=kw.get("executor"),
                                                 open_rows=kw.get("open_rows"),
                                                 environ=kw.get("environ"))
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "schedule_broken", "Запуск не выполнен - фабрика ответила "
                                                     "ошибкой.", [f"{type(e).__name__}: {e}"])
        if not ok:
            raise BatchFault(409, "refused", line, [line])
        return {"ok": True, "line": line, "channel": cid, "pid": row.get("pid"),
                "log": row.get("log"), "row": row, "login": login}
    finally:
        _LAUNCH.release()


# ---------------------------------------------------------------- stop and resume (CC-0047)
def _bc():
    return factory.batch_control()


def _control_check(action, root, d):
    """`batch_control.stop_check` / `resume_check` of the batch - read only."""
    bc = _bc()
    kw = _kw()
    try:
        if action == "stop":
            return bc.stop_check(str(d), root)
        return bc.resume_check(str(d), root, kw.get("now"), kw.get("open_rows"),
                               kw.get("executor"))
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "control_broken", "Проверка батча не выполняется - фабрика "
                                                "ответила ошибкой.", [f"{type(e).__name__}: {e}"])


def _control_fingerprint(chk):
    """sha256 of what the check decided: the action, the batch, its status, the
    executor (pid, group, alive, the lock), the step's pid, the argv a resume
    would start."""
    step = chk.get("step") or {}
    return _digest({"action": chk.get("action"), "batch": chk.get("batch"),
                    "ok": bool(chk.get("ok")), "status": chk.get("status"),
                    "executor_pid": chk.get("executor_pid"),
                    "executor_pgid": chk.get("executor_pgid"),
                    "executor_alive": bool(chk.get("executor_alive")),
                    "lock_held": bool(chk.get("lock_held")), "step_pid": step.get("pid"),
                    "argv": chk.get("argv")})


#: Each refusal of `resume_check` / `resume` (CF-0739 `RESUME_CODES`) as a
#: stable code and the center's own Russian line; `refused` when the factory
#: gives no code (an older one) or one the center does not know. A stop has no
#: codes yet - its refusal stays `refused` with the factory's line.
RESUME_CODES = {
    "bad_who": "Не указано, кто продолжает (by) - это ошибка центра, не батча.",
    "not_posix": "На этой системе нет групп процессов POSIX - продолжение батча здесь не "
                 "работает.",
    "no_state": "У батча нет run-state.json - это не батч исполнителя, продолжать нечего.",
    "executor_alive": "Батч идёт - исполнитель жив, продолжать нечего.",
    "lock_foreign": "Замок батча держит процесс, не узнанный как исполнитель - разберитесь "
                    "руками; батч не продолжен.",
    "no_channel": "В состоянии батча не указан канал - продолжать нечем.",
    "batch_finished": "Батч не стоит, а закончен - продолжать нечего; его можно повторить со "
                      "стадии или пересобрать ролики.",
    "plan_changed": "План канала изменился с начала батча - исполнитель откажется его "
                    "продолжать; продолжение только руками (--plan-changed-ok).",
    "plan_unreadable": "План канала не читается - продолжение невозможно, пока план не "
                       "починят.",
    "open_unreadable": "Открытые батчи не читаются - батч не продолжен.",
    "other_batch_open": "Открыт другой батч - один батч за раз, сначала он.",
    "not_confirmed": "Продолжение не подтверждено - батч не продолжен.",
    "locked": "Батч или расписание сейчас заняты (замок) - батч не продолжен; попробуйте "
              "ещё раз.",
    "spawn_failed": "Исполнитель не стартовал - батч не продолжен; подробности в строке "
                    "фабрики.",
    "exited_at_once": "Исполнитель стартовал и сразу закончил с ошибкой - батч стоит; "
                      "посмотрите его журнал.",
    "refused": "Фабрика отказала в продолжении батча.",
}


def _resume_code(chk):
    """The code of a resume answer: None when it went (`ok`), else the
    factory's `code` when the center knows it, else `refused`."""
    if chk.get("ok"):
        return None
    code = chk.get("code")
    return code if code in RESUME_CODES else "refused"


def _resume_message(chk):
    code = _resume_code(chk)
    return RESUME_CODES[code] if code else (chk.get("reason") or "")


def _resume_fault(chk):
    """A refused resume: the factory's code, the center's line and the factory's."""
    code = _resume_code(chk) or "refused"
    why = chk.get("reason") or ""
    details = [why] + ([f"factory code: {chk.get('code')}"]
                       if chk.get("code") and chk.get("code") != code else [])
    return BatchFault(409, code, RESUME_CODES[code] + (f" Фабрика: {why}" if why else ""),
                      details)


def _control_plan(root, channel, batch_id, action, bound=None):
    d = batch_dir(root, channel, batch_id)
    chk = _control_check(action, root, d)
    fp = _control_fingerprint(chk)
    out = dict(chk, fingerprint=fp, confirm=None, expires_in_s=None, **(bound or {}))
    if action == "resume":
        out.update(code=_resume_code(chk), message=_resume_message(chk))
    if chk.get("ok"):
        out.update(confirm=_issue(root, action, str(d), fp, bound),
                   expires_in_s=int(CONFIRM_TTL))
    return out


def stop_plan(root, channel, batch_id, also_step=False):
    """`stop_check` of the batch, `also_step`, its fingerprint, and a confirm
    token when it says ok. Nothing is signalled."""
    return _control_plan(root, channel, batch_id, "stop", {"also_step": bool(also_step)})


def resume_plan(root, channel, batch_id):
    """`resume_check` of the batch, its fingerprint, and a confirm token when it
    says ok. Nothing is started."""
    return _control_plan(root, channel, batch_id, "resume")


def _control_lock(d):
    with _CONTROLS_LOCK:
        return _CONTROLS.setdefault(str(d), threading.Lock())


def _confirm(root, channel, batch_id, action, token, act, also_step=None):
    """The batch's control lock (busy at once if taken), the token spent, the
    check again and the same, then `act(bc, d, kw, also_step)` - the factory's
    own stop or resume. Nothing done: a `refused` BatchFault with its reason."""
    d = batch_dir(root, channel, batch_id)
    lock = _control_lock(d)
    if not lock.acquire(blocking=False):
        raise BatchFault(409, "busy", f"Над батчем {channel}/{batch_id} уже идёт остановка или "
                                      f"продолжение - дождитесь ответа и запросите план заново.",
                         ["the batch's control lock is taken; the token is not spent"])
    try:
        got = _spend(root, action, str(d), token)
        if action == "stop":
            bound = bool(got["bound"].get("also_step"))
            if also_step is not None and bool(also_step) != bound:
                raise BatchFault(409, "confirm_mismatch",
                                 "Подтверждение выдано для остановки " + (
                                     "вместе с шагом" if bound else "без шага") +
                                 ", а просят " + ("вместе с шагом" if also_step else "без шага") +
                                 " - батч не остановлен; запросите план остановки заново.",
                                 [f"token also_step={bound}, asked also_step={bool(also_step)}; "
                                  f"the token is spent"])
            also_step = bound
        chk = _control_check(action, root, d)
        if _control_fingerprint(chk) != got["fingerprint"]:
            if not chk.get("ok"):
                if action == "resume":
                    raise _resume_fault(chk)
                raise BatchFault(409, "refused", chk.get("reason") or "Фабрика отказала.",
                                 ["the check changed since the plan", chk.get("reason") or ""])
            raise BatchFault(409, "check_changed", f"Проверка изменилась с момента плана - "
                                                   f"{_ACTIONS[action][1]}; посмотрите план "
                                                   f"заново.",
                             [f"the fingerprint of {action}_check differs from the plan's"])
        bc = _bc()
        try:
            res = act(bc, d, _kw(), also_step)
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "control_broken", "Фабрика ответила ошибкой посреди действия - "
                                                    "посмотрите батч, прежде чем повторять.",
                             [f"{type(e).__name__}: {e}"])
        done = res.get("executor_signalled") is not None if action == "stop" \
            else bool(res.get("resumed"))
        if not done:
            if action == "resume":
                raise _resume_fault(res)
            raise BatchFault(409, "refused", res.get("reason") or "Фабрика отказала.",
                             [res.get("reason") or ""])
        if action == "resume":
            return dict(res, code=_resume_code(res), message=_resume_message(res))
        return res
    finally:
        lock.release()


def stop(root, channel, batch_id, token, also_step=None):
    """The confirmed stop: `batch_control.stop(confirmed=True, by=CONTROL_BY)`.
    Its dict once a signal went (`ok` false when the executor outlived
    `grace_s` - the `kill -9` line is in `reason`); a refusal before that is a
    BatchFault. `also_step` None: the plan's."""
    return _confirm(root, channel, batch_id, "stop", token, lambda bc, d, kw, also: bc.stop(
        str(d), CONTROL_BY, confirmed=True, also_step=also, root=root,
        grace_s=kw.get("grace_s", bc.GRACE_S), environ=kw.get("environ")), also_step)


def resume(root, channel, batch_id, token):
    """The confirmed resume: `batch_control.resume(confirmed=True,
    by=CONTROL_BY)` - `run_executor.py run <ch> --resume DIR` detached. Its
    dict once started (`ok` false when it ended at once with a bad code); a
    refusal before that is a BatchFault."""
    return _confirm(root, channel, batch_id, "resume", token, lambda bc, d, kw, _also: bc.resume(
        str(d), CONTROL_BY, confirmed=True, root=root, now=kw.get("now"),
        environ=kw.get("environ"), executor=kw.get("executor"), open_rows=kw.get("open_rows"),
        take_s=kw.get("take_s", bc.RESUME_TAKE_S)))


# ---------------------------------------------------------------- rerun from a stage (CC-0123)
#: Who the factory writes in `manual_resets` and the journal (CF-0700's rule:
#: by / via short single-line names).
RERUN_BY = BY
RERUN_VIA = "center"
RERUN_NOTE_MAX = 500
#: Each refusal of `rerun_from_check` / `rerun_from` (CF-0739) as a stable
#: code and the center's own Russian line. The factory's `code` (its
#: `RERUN_CODES`) is read as is; only an older factory without `code` is told
#: apart by the fragments of `_RERUN_RULES` in its Russian `reason` (pinned
#: against this checkout's batch_control by tests/test_cc_api_batches_rerun.py).
#: An unknown code or line is `refused`. `resume_failed` is not a refusal: the
#: reset was done and the resume asked after it did not go (its own code in
#: `resume.code`, `resume_code`).
RERUN_CODES = {
    "bad_who": "Не указано, кто повторяет (by / via) - это ошибка центра, не батча.",
    "bad_note": "Пояснение к повтору - одна строка, не длиннее 500 знаков.",
    "not_posix": "На этой системе нет групп процессов POSIX - повтор батча здесь не работает.",
    "no_state": "У батча нет run-state.json - это не батч исполнителя, повторять нечего.",
    "executor_alive": "Батч идёт - сначала остановите его («Остановить»), потом повторяйте "
                      "со стадии.",
    "lock_foreign": "Замок батча держит процесс, не узнанный как исполнитель - разберитесь "
                    "руками; повтор не начат.",
    "no_channel": "В состоянии батча не указан канал - повторять нечем.",
    "plan_changed": "План канала изменился с начала батча - исполнитель откажется его "
                    "продолжать; повтор только руками (--plan-changed-ok).",
    "plan_unreadable": "План канала не читается - повтор невозможен, пока план не починят.",
    "stage_handler": "Это обработчик, а не стадия - он повторяется вместе со стадией, которая "
                     "его вызывает; выберите её.",
    "stage_unknown": "Такой стадии в плане канала нет.",
    "stage_opens_batch": "Повтор с этой стадии открыл бы журнал заново - это был бы новый "
                         "батч, а не повтор; выберите стадию после открытия батча.",
    "stage_not_run": "Эта стадия ещё не шла - повторять нечего; батч можно просто продолжить.",
    "earlier_failed": "Раньше этой стадии есть упавшая - повторяйте с неё, иначе исполнитель "
                      "снова пропустит всё после неё.",
    "step_running": "Шаг сбрасываемой стадии ещё работает - дождитесь его или остановите батч "
                    "вместе с шагом.",
    "open_unreadable": "Открытые батчи не читаются - повтор не начат.",
    "other_batch_open": "Открыт другой батч - один батч за раз, сначала он.",
    "not_confirmed": "Повтор не подтверждён - состояние батча не тронуто.",
    "locked": "Батч или расписание сейчас заняты (замок) - повтор не начат; попробуйте ещё раз.",
    "state_gone": "run-state.json пропал во время повтора - ничего не сделано.",
    "resume_failed": "Стадии сброшены, но продолжение после сброса не удалось - батч стоит "
                     "(stopped), его можно продолжить позже кнопкой «Продолжить».",
    "refused": "Фабрика отказала в повторе батча со стадии.",
}
#: (code, a fragment of the factory's line) - the first that matches wins; read
#: only when the answer carries no `code` (a factory before CF-0739's codes).
_RERUN_RULES = (
    ("bad_who", "нужно указать "), ("bad_who", "не длиннее 40 знаков"),
    ("bad_note", "note: одна строка"),
    ("not_posix", "нет POSIX-групп процессов"),
    ("no_state", ".json - повторять нечего"),
    ("lock_foreign", "не узнанный как исполнитель"),
    ("executor_alive", "жив - батч идёт"),
    ("no_channel", "нет канала - повторять нечем"),
    ("plan_changed", "изменился с начала батча"),
    ("plan_unreadable", " не читается ("),
    ("stage_handler", ": обработчик - он повторяется"),
    ("stage_unknown", ": такой стадии в плане нет"),
    ("stage_opens_batch", "заново открыл бы журнал"),
    ("stage_not_run", "ещё не шла (pending)"),
    ("earlier_failed", " упала стадия "),
    ("step_running", "ещё работает - повтор запустил бы второй"),
    ("open_unreadable", "открытые батчи не читаются"),
    ("other_batch_open", "открыт другой батч "),
    ("not_confirmed", "не подтверждено"),
    ("state_gone", " пропал - отказ"),
    ("locked", "отказ: "),
)


def _rerun_code(chk):
    """The code of the factory's answer: None when ok; else the factory's own
    `code` (`refused` when the center does not know it); without one (an older
    factory) the first rule whose fragment is in its `reason` (`not_posix` off
    the check's own `posix`)."""
    if chk.get("ok"):
        return None
    code = chk.get("code")
    if code:
        return code if code in RERUN_CODES else "refused"
    if chk.get("done") and isinstance(chk.get("resume"), dict):
        return "resume_failed"
    if chk.get("posix") is False:
        return "not_posix"
    why = str(chk.get("reason") or "")
    for code, frag in _RERUN_RULES:
        if frag in why:
            return code
    return "refused"


def _rerun_fault(chk, status=409):
    """A refusal of the rerun: its code, the center's line and the factory's."""
    code = _rerun_code(chk) or "refused"
    why = chk.get("reason") or ""
    details = [why] + ([f"factory code: {chk.get('code')}"]
                       if chk.get("code") and chk.get("code") != code else [])
    return BatchFault(status, code, RERUN_CODES[code] + (f" Фабрика: {why}" if why else ""),
                      details)


def _rerun_check(root, d, stage, open_rows=None):
    """`batch_control.rerun_from_check(by=RERUN_BY, via=RERUN_VIA)` - read only.
    `open_rows`: the open batches read once for many stages (the factory's
    own injection point; FACTORY_KW's wins - the tests')."""
    bc = _bc()
    kw = _kw()
    rows = kw.get("open_rows", open_rows)
    try:
        return bc.rerun_from_check(str(d), stage, root, kw.get("now"), rows, RERUN_BY, RERUN_VIA)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "control_broken", "Проверка повтора не выполняется - фабрика "
                                                "ответила ошибкой.", [f"{type(e).__name__}: {e}"])


def _rerun_stages(root, d):
    """`stages_for_rerun`: each stage of run-state.json `order` with its
    `stages[id].status` (pending when none) and whether a rerun from it would
    go now - the factory's own `rerun_from_check` per stage, the open batches
    read once; `why` the factory's line, `code` the refusal's (null when
    `can`)."""
    st = _bc().read_state(str(d)) or {}
    order = [s for s in st.get("order") or [] if isinstance(s, str)]
    if not order:
        return []
    rows = None
    if "open_rows" not in _kw():
        try:
            rows = factory.runlog().open_batches(Path(root).resolve(),
                                                 now=datetime.now(timezone.utc))
        except Exception:                                       # noqa: BLE001
            rows = None             # each check reads them itself and says so
    stages = st.get("stages") if isinstance(st.get("stages"), dict) else {}
    out = []
    for sid in order:
        chk = _rerun_check(root, d, sid, rows)
        out.append({"stage": sid,
                    "status": ((stages.get(sid) or {}) if isinstance(stages.get(sid), dict)
                               else {}).get("status") or "pending",
                    "can": bool(chk.get("ok")), "why": chk.get("reason") or "",
                    "code": _rerun_code(chk)})
    return out


def rerun_stages(root, channel, batch_id):
    """{batch, channel, batch_id, status, executor_alive, lock_held, stages_for_rerun}:
    what «повторить со стадии» can offer - read only."""
    d = batch_dir(root, channel, batch_id)
    st = _bc().read_state(str(d))
    return {"batch": f"{channel}/{batch_id}", "channel": factory.collect()._batch_channel(d, root),
            "batch_id": batch_id, "status": (st or {}).get("status"),
            "has_state": st is not None, **_executor(d, st if st is not None else {}),
            "stages_for_rerun": _rerun_stages(root, d) if st is not None else []}


def _rerun_message(chk):
    code = _rerun_code(chk)
    if code:
        return RERUN_CODES[code]
    n = len(chk.get("reset") or [])
    return (f"Можно повторить со стадии {chk.get('from_stage')}: {n} стад. вернутся в pending; "
            f"файлы стадий не удаляются - повтор их перезапишет.")


def rerun_plan(root, channel, batch_id, stage):
    """`rerun_from_check` of the stage (CF-0739) - the factory's plan as is
    (`reset`, `reset_status`, `keys`, `logs`, `kept`, `lines`, its Russian
    `reason`, also as `why`) with `code` / `message`, `stages_for_rerun`, its
    fingerprint and, when ok, a confirm token bound to the stage. Nothing is
    written."""
    d = batch_dir(root, channel, batch_id)
    stage = str(stage or "")
    chk = _rerun_check(root, d, stage)
    fp = _digest(chk)
    out = dict(chk, why=chk.get("reason") or "", code=_rerun_code(chk),
               message=_rerun_message(chk), stages_for_rerun=_rerun_stages(root, d),
               fingerprint=fp, confirm=None, expires_in_s=None)
    if chk.get("ok"):
        out.update(confirm=_issue(root, "rerun_from", str(d), fp, {"stage": stage}),
                   expires_in_s=int(CONFIRM_TTL))
    return out


def _rerun_note(note):
    """The note as the factory takes it (one line, <= RERUN_NOTE_MAX); empty is
    none. Checked before the token is spent: a 422 `bad_note`."""
    if note is None or not str(note).strip():
        return None
    note = str(note).strip()
    if "\n" in note or "\r" in note or len(note) > RERUN_NOTE_MAX:
        raise BatchFault(422, "bad_note", RERUN_CODES["bad_note"],
                         [f"note: {len(note)} chars" + (", several lines" if "\n" in note or
                                                        "\r" in note else "")])
    return note


def rerun_from(root, channel, batch_id, token, note=None, resume_after=False):
    """The confirmed rerun: the batch's control lock (one stop / resume /
    rerun of a batch at a time - busy at once), the token spent, the check of
    its stage again and the same, then `batch_control.rerun_from(stage,
    RERUN_BY, RERUN_VIA, confirmed=True, note, resume_after)` - the
    backup, the stages pending, status stopped, `next` the stage, the
    `manual_resets` row, the journal event; with `resume_after` the factory's own
    `resume` right after (the detached `run_executor --resume`, at most
    RESUME_TAKE_S for the lock). Its dict once the state was written (`ok`
    false when the resume after it failed - `code` resume_failed, `resumed`,
    `resume_code`, `resume_reason`); a refusal before that is a BatchFault with
    the refusal's code."""
    d = batch_dir(root, channel, batch_id)
    note = _rerun_note(note)
    lock = _control_lock(d)
    if not lock.acquire(blocking=False):
        raise BatchFault(409, "busy", f"Над батчем {channel}/{batch_id} уже идёт остановка, "
                                      f"продолжение или повтор - дождитесь ответа и запросите "
                                      f"план заново.",
                         ["the batch's control lock is taken; the token is not spent"])
    try:
        got = _spend(root, "rerun_from", str(d), token)
        stage = got["bound"]["stage"]
        chk = _rerun_check(root, d, stage)
        if _digest(chk) != got["fingerprint"]:
            if not chk.get("ok"):
                raise _rerun_fault(chk)
            raise BatchFault(409, "check_changed", "Проверка изменилась с момента плана - "
                                                   "повтор не начат; посмотрите план заново.",
                             ["the fingerprint of rerun_from_check differs from the plan's"])
        bc = _bc()
        kw = _kw()
        try:
            res = bc.rerun_from(str(d), stage, RERUN_BY, RERUN_VIA, confirmed=True, root=root,
                                now=kw.get("now"), open_rows=kw.get("open_rows"), note=note,
                                resume_after=bool(resume_after), environ=kw.get("environ"),
                                executor=kw.get("executor"),
                                take_s=kw.get("take_s", bc.RESUME_TAKE_S))
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "control_broken", "Фабрика ответила ошибкой посреди повтора - "
                                                    "посмотрите run-state.json батча, прежде чем "
                                                    "повторять.", [f"{type(e).__name__}: {e}"])
        if not res.get("done"):
            raise _rerun_fault(res)
        after = res.get("resume") if isinstance(res.get("resume"), dict) else None
        n = len(res.get("reset") or [])
        backup = Path(str(res.get("backup") or "")).name
        msg = f"Стадии с {stage} сброшены в pending ({n}); копия состояния {backup}."
        code = _rerun_code(res)
        if after is None:
            msg += " Чтобы прогнать их, нажмите «Продолжить»."
        elif after.get("resumed") and after.get("ok"):
            msg += f" Исполнитель запущен (pid {after.get('pid')})."
        else:
            code = "resume_failed"
            msg += (f" {RERUN_CODES['resume_failed']} {RESUME_CODES[_resume_code(after)]} "
                    f"Фабрика: {after.get('reason') or ''}")
        return dict(res, code=code if code == "resume_failed" else None, message=msg,
                    resume_asked=bool(resume_after),
                    resume_code=None if after is None else _resume_code(after),
                    resumed=bool(after and after.get("resumed")),
                    pid=(after or {}).get("pid"), log=(after or {}).get("log"),
                    exit=(after or {}).get("exit"),
                    resume_ok=None if after is None else bool(after.get("ok")),
                    resume_reason=(after or {}).get("reason"))
    finally:
        lock.release()


# ---------------------------------------------------------------- the rebuild (CC-0048)
def _source_videos(d):
    """CC-0116: `batch_control._source_videos` of a batch - [] when the factory
    does not answer (the modes still do)."""
    try:
        return [v for v in factory.batch_control()._source_videos(d) if v.get("script_id")]
    except Exception:                                       # noqa: BLE001
        return []


def rebuild_modes(root, channel, batch_id):
    """{batch, channel, batch_id, modes [{id, title, from_stage, doc}], reason,
    seconds_to_blocks, videos}: the rebuild modes of the batch's channel, off its run
    plan as the factory reads it (`run_plan.load` / `run_plan.rebuild_modes`).
    A plan that does not load: no modes and the factory's error as `reason`.
    CC-0116: `videos` - what a plan can name, `batch_control._source_videos`
    (CF-0727: a video refused after the render too, `refused` its gate)."""
    d = batch_dir(root, channel, batch_id)
    cid = factory.collect()._batch_channel(d, root)
    out = {"batch": f"{channel}/{batch_id}", "channel": cid, "batch_id": batch_id, "modes": [],
           "reason": None, "seconds_to_blocks": SECONDS_TO_BLOCKS is not None,
           "videos": _source_videos(d)}
    if not cid:
        out["reason"] = f"батч {channel}/{batch_id} не называет канал - режимов пересборки нет"
        return out
    rp = factory.run_plan()
    try:
        plan = rp.load(cid, root)
    except rp.PlanError as e:
        out["reason"] = f"план канала {cid} не читается ({e})"
        return out
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "control_broken", "Режимы пересборки не читаются - фабрика "
                                                "ответила ошибкой.", [f"{type(e).__name__}: {e}"])
    modes = rp.rebuild_modes(plan)
    out["modes"] = [{"id": k, "title": (v or {}).get("title") or k,
                     "from_stage": (v or {}).get("from"), "doc": (v or {}).get("doc")}
                    for k, v in modes.items()]
    if not modes:
        out["reason"] = f"у плана канала {cid} нет режимов пересборки"
    return out


# ---------------------------------------------------------------- seconds -> blocks (CC-0049)
#: How many seconds one `.../blocks?at=` may ask (a remark names a few).
BLOCKS_AT_MAX = 20
_AT_SPLIT = re.compile(r"[\s,;]+")


def _seconds(at):
    """`at` of the query - «12,18,24» (commas, semicolons or spaces between;
    a decimal point, not a comma) - as floats, each finite and >= 0, 1 to
    BLOCKS_AT_MAX of them; else a 422 `invalid`."""
    raw = [x for x in _AT_SPLIT.split(str(at or "").strip()) if x]
    bad = []
    out = []
    for x in raw:
        try:
            v = float(x)
        except ValueError:
            bad.append(x)
            continue
        if v != v or v in (float("inf"), float("-inf")) or v < 0:
            bad.append(x)
        else:
            out.append(v)
    if bad or not out or len(out) > BLOCKS_AT_MAX:
        raise BatchFault(422, "invalid", "Секунды ролика - числа от 0 через запятую "
                                         f"(«12,18,24»), не больше {BLOCKS_AT_MAX}.",
                         [f"at={at!r}: " + (f"not seconds: {', '.join(bad)}" if bad else
                                            "none given" if not out else
                                            f"{len(out)} > {BLOCKS_AT_MAX}")])
    return out


def blocks(root, channel, batch_id, slug, at):
    """CC-0049: `batch_control.blocks_at` (CF-0669) of a video of the batch,
    as the factory answers it - which storyboard block each second of the
    finished video falls in: `{ok, reason, batch, slug, plan, duration,
    moments [{at, block, window, kind, shots, ending, exclude, near, note?}],
    exclude}`. The top-level `exclude` (`BLOCK=SOURCE:SHOT`) goes as is into
    `rebuild/plan`'s `notes.videos[slug].exclude`; `near` is the neighbour
    block for a second within 0.5 s of a cut (not in `exclude` - the screen
    offers it); `exclude: null` + `note` where the editor would refuse. `slug`
    may be the script id. Read only. No plan of the video: 404 `no_plan` with
    the factory's line; the plan read must be the batch's own
    (`work/<slug>/plan.json` through `factory.contained`)."""
    d = batch_dir(root, channel, batch_id)
    if not SAFE_NAME.match(slug or "") or slug in (".", ".."):
        raise BatchFault(404, "unknown_video", f"Ролика «{slug}» в батче «{channel}/{batch_id}» "
                                               f"нет.", [f"slug {slug!r}: not a name"])
    seconds = _seconds(at)
    try:
        res = _bc().blocks_at(str(d), slug, seconds, root)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "control_broken", "Секунды не переводятся в блоки - фабрика "
                                                "ответила ошибкой.", [f"{type(e).__name__}: {e}"])
    own = factory.contained(root, PIPELINE_DIR, channel, batch_id, "work",
                            str(res.get("slug") or ""), "plan.json")
    if not res.get("ok") or own is None:
        raise BatchFault(404, "no_plan", f"У ролика «{slug}» нет плана монтажа - секунды не "
                                         f"переводятся в блоки.",
                         [x for x in (res.get("reason"), None if own is not None else
                                      f"work/{res.get('slug')}/plan.json is not the batch's own")
                          if x])
    return res


#: The seam of «seconds of the video -> storyboard blocks» for the notes'
#: exclusions (CC-0048 left it None): the factory's `blocks_at` (CF-0669)
#: behind `blocks` and `GET .../videos/{slug}/blocks?at=`. The modes answer
#: says `seconds_to_blocks: true`. The rebuild's notes take block exclusions
#: only (`BLOCK` / `BLOCK=SOURCE:SHOT`) - the screen asks `/blocks` first,
#: shows the moments (the neighbour of a second near a cut, the split or the
#: ending that has nothing to exclude) and sends the exclusions the user
#: kept. `_rebuild_notes` converts nothing: a conversion inside the plan
#: would pick for the user what `near` and `note` leave to them, and the
#: token would bind exclusions nobody saw.
SECONDS_TO_BLOCKS = blocks


def _rebuild_notes(notes):
    """The notes as the factory takes them (`rebuild_check(notes=)`): a text,
    or `{text, videos: {slug|script_id: text | {exclude, note}}}` - the
    exclusions block numbers, as `GET .../blocks` gave them (no seconds here,
    see SECONDS_TO_BLOCKS)."""
    return json.loads(json.dumps(notes, ensure_ascii=False)) if notes is not None else None


def _rebuild_check(root, d, videos, mode, notes):
    """`batch_control.rebuild_check` of the batch - read only."""
    bc = _bc()
    kw = _kw()
    try:
        return bc.rebuild_check(str(d), list(videos or []), mode, root, kw.get("now"),
                                kw.get("open_rows"), notes)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "control_broken", "Проверка пересборки не выполняется - фабрика "
                                                "ответила ошибкой.", [f"{type(e).__name__}: {e}"])


def _rebuild_fingerprint(chk):
    """sha256 of the whole check: the batch, the mode and its plan (from,
    layout, copies), the videos with their exclusions and notes, the source,
    the verdict and its line."""
    return _digest(chk)


def rebuild_plan(root, channel, batch_id, videos, mode, notes=None):
    """`rebuild_check` of these videos in this mode, its fingerprint, and a
    confirm token when it says ok - the videos, the mode and the notes are
    bound to the token (the confirm does not send them again). Nothing made."""
    d = batch_dir(root, channel, batch_id)
    videos = [str(v) for v in videos or []]
    notes = _rebuild_notes(notes)
    chk = _rebuild_check(root, d, videos, mode, notes)
    fp = _rebuild_fingerprint(chk)
    out = dict(chk, fingerprint=fp, confirm=None, expires_in_s=None)
    if chk.get("ok"):
        out.update(confirm=_issue(root, "rebuild", str(d), fp,
                                  {"videos": videos, "mode": mode, "notes": notes}),
                   expires_in_s=int(CONFIRM_TTL))
    return out


def rebuild(root, channel, batch_id, token):
    """The confirmed rebuild: one at a time with the launches (`_LAUNCH` - a
    rebuild opens a batch), the token spent, the check of its videos, mode and
    notes again and the same, then `batch_control.rebuild(confirmed=True,
    by=CONTROL_BY)` - `pipeline/rebuilds/<ts>`, `batch-start`, the executor
    detached; it answers at once. Its dict once the rebuild was opened
    (`started`, or the state written and the start failed - `ok` false with
    the factory's line); a refusal before that is a BatchFault."""
    d = batch_dir(root, channel, batch_id)
    if not _LAUNCH.acquire(timeout=LAUNCH_WAIT):
        raise BatchFault(409, "busy", "Идёт запуск или другая пересборка - подождите и запросите "
                                      "план пересборки заново.",
                         [f"the launch lock was not free in {LAUNCH_WAIT} s; the token is not "
                          f"spent"])
    try:
        got = _spend(root, "rebuild", str(d), token)
        b = got["bound"]
        chk = _rebuild_check(root, d, b["videos"], b["mode"], b["notes"])
        if _rebuild_fingerprint(chk) != got["fingerprint"]:
            if not chk.get("ok"):
                raise BatchFault(409, "refused", chk.get("reason") or "Фабрика отказала.",
                                 ["the check changed since the plan", chk.get("reason") or ""])
            raise BatchFault(409, "check_changed", "Проверка изменилась с момента плана - "
                                                   "пересборка не начата; посмотрите план "
                                                   "заново.",
                             ["the fingerprint of rebuild_check differs from the plan's"])
        bc = _bc()
        kw = _kw()
        try:
            res = bc.rebuild(str(d), b["videos"], b["mode"], CONTROL_BY, confirmed=True,
                             notes=b["notes"], root=root, now=kw.get("now"),
                             environ=kw.get("environ"), executor=kw.get("executor"),
                             open_rows=kw.get("open_rows"),
                             take_s=kw.get("take_s", bc.RESUME_TAKE_S))
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "control_broken", "Фабрика ответила ошибкой посреди "
                                                    "пересборки - посмотрите pipeline/rebuilds/, "
                                                    "прежде чем повторять.",
                             [f"{type(e).__name__}: {e}"])
        if not (res.get("started") or res.get("state")):
            raise BatchFault(409, "refused", res.get("reason") or "Фабрика отказала.",
                             [res.get("reason") or ""])
        return res
    finally:
        _LAUNCH.release()

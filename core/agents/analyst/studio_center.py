#!/usr/bin/env python3
"""CF-0735: the Studio read driven by the user's own actions in the command
center (request CC-0120, the user's «да» 13.10).

Reading YouTube Studio is done by a Claude session driving the user's Chrome
(Claude in Chrome); an unattended `claude -p --chrome` is not something the
Claude Code documentation describes, so the read starts from a ONE-CLICK
BUTTON in the center - a click means the user is at the laptop with Chrome
open. The read itself is the procedure of `agents/analyst/SKILL.md`,
«Чтение Studio (CF-0588)»: only `studio.youtube.com`, only reading, recorded
through `studio_read.py record --by --via`. This module never goes to Studio
and never talks to the network: it says whether a read is due, starts the
reading session as a detached process with a log, and reads its outcome.

**The first real launch was done with the user present** (his «да» 13.10);
since then the center's button has read Studio many times. **CF-0926 (the
user's decision 09.11: «чтение studio запускал сам по расписанию, как и
батчи+публикацию»):** the read also starts on its own - the tick of
`shared/batch_schedule.py` calls `scheduled_read` once a Moscow day at the
schedule's `studio_read_at` (08:15 by default), `by: schedule, via: tick`,
not while a batch is open, not in the hour before a batch window, not while
another read is going, at most SCHED_MAX_ATTEMPTS launches a day; its outcome
goes to Telegram once per run. The tests stub the binary (`STUDIO_READ_CLAUDE`).

Only the channels the factory still runs are read (CF-0926): a channel whose
schedule is off (`enabled: false`, the rule of
CF-0925 `scheduled_channels`) is left out of the button, the due check and
the safety net alike.

Python (the center's api/ loads this file by path):

    studio_read_due(channel=None, hook=None, root=None, now=None, environ=None)
        -> {task, channel, hook, hooks, due, why, last_read_at, age_hours,
            first_open_today, running, channels: [{channel, due, why,
            last_read_at, age_hours}], skipped: [line]}
        hook: `batch-start` | `upload` (the rule of `studio_read.due` with the
        hook gap) | `center-first-open-of-day` (records the open in a state
        file: the first open of the Moscow day takes the hook rule, a later
        open the daily insurance) | None (the daily insurance alone)
    studio_read_launch(by, via, confirmed=False, root=None, now=None,
                       channels=None, claude=None, environ=None)
        -> the CF-0726 answer shape: {ok, launched, confirmed, task, by, via,
           channels, argv, run_id, pid, log, refusals: [{code, line}], lines}
        Without `confirmed` - the plan, nothing started. Refusal codes:
        LAUNCH_REFUSALS.
    studio_read_result(ref, root=None, environ=None)
        -> {run_id, log, code, done, line, detail, recorded}
        ref: the run id the launch answered, or its log's path. Codes:
        OUTCOMES - read (прочитано), no_extension (расширение не подключено),
        login_needed (нужен вход), error (ошибка), running (ещё читается).
    commit_read_data(root=None, run_id=None, by=None, via=None, open_rows=None)
        -> {task, status, sha, paths, line, details}  (CF-0786)
        One commit of exactly the read's files git sees changed or new
        (`read_data_paths`: analytics/<channel>/studio.jsonl, studio_visits.jsonl).
        status: committed | nothing | deferred (a batch is open: a root commit
        under a run is code_drift - the next run's plan commits it before its
        batch-start) | not_repo | refused. The launch's runner calls it after the
        session; `studio_read_result` gives it back as `commit` and adds its line.
    studio_insurance_notify(root=None, now=None, environ=None, dry_run=False)
        -> {sent, why, text, link, channels, status}
        The safety net: one Russian line «Studio не читали N часов — откройте
        центр» with the center's link, at most once in INSURANCE_EVERY_H
        hours for the whole factory; called by every tick of
        shared/batch_schedule.py and by the `studio-read-due` stage of a batch.
        CF-0926: it speaks only when the planned read did not read
        (`scheduled_insurance_gate`), and says what came of it and what is
        needed from the user.
    scheduled_read(root=None, now=None, at=None, enabled=None, blocked=None,
                   environ=None, dry_run=False)
        -> {task, launched, run_id, collected, notified, line, lines, state}
        CF-0926: one tick of the planned read (the tick of
        shared/batch_schedule.py passes `blocked` - an open batch, the hour
        before a window); `at`/`enabled` - the schedule's `studio_read_at` /
        `studio_read` (`schedule_settings`).
    scheduled_insurance_gate(root=None, now=None, environ=None) -> {quiet, why, need}

CLI:

    python3 agents/analyst/studio_center.py due [--channel C] [--hook H] [--now ISO] [--root DIR]
    python3 agents/analyst/studio_center.py launch --by WHO --via WHAT [--confirm] [--channel C ...]
    python3 agents/analyst/studio_center.py result RUN_ID|LOG
    python3 agents/analyst/studio_center.py commit-read [--root DIR]
        # CF-0786: commit the read's data left uncommitted (before batch-start;
        # SKILL step 7 after a read by hand);
        # exit 0 whatever it came to
    python3 agents/analyst/studio_center.py session RUN_JSON
        # the launch's detached runner: the session, then commit_read_data
    python3 agents/analyst/studio_center.py insurance [--now ISO] [--dry-run] [--root DIR]
        # exit 0 whatever was decided (a notification is never on the critical
        # path), 2 bad call
    python3 agents/analyst/studio_center.py scheduled [--now ISO] [--dry-run] [--root DIR]
        # CF-0926: one step of the planned read by hand (the tick does it every
        # 15 min, with the batch/window guard); exit 0

**State** (gitignored, `<root>/schedule/studio-read/`, or `STUDIO_READ_STATE_DIR`):

* `center-opens.json` - `{day, first_open_at, last_open_at, opens}`: the
  Moscow day of the center's first open; rewritten atomically under the lock;
* `insurance.json` - `{last_sent_at, key, text, status}`: the safety net's
  last notification (the 24-hour dedupe);
* `scheduled.json` - CF-0926, the planned read: `{day, attempts: [{at, run_id,
  channels, code, line, done_at}], run_id (going), outcome (read | not_due |
  failed | null), outcome_at, waiting (why the last tick did not launch),
  last_read_at, previous: {day, outcome, attempts, last_code, last_line,
  waiting}}`;
* `runs/<run_id>.json` (who, when, pid - of the runner, CF-0786 -, argv of the
  session, runner, root, channels; `commit` - what the runner committed), `runs/<run_id>.log`
  (the session's output), `runs/<run_id>.prompt.txt` (its stdin), and the
  read JSON files the session writes, `runs/<run_id>-<channel>.json`;
* `.lock` - one `fcntl.flock` for all of the above.
"""
import argparse
import contextlib
import fcntl
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import studio_read as sr                                        # noqa: E402

TASK = "CF-0735"
HOOK_BATCH, HOOK_UPLOAD, HOOK_CENTER = "batch-start", "upload", "center-first-open-of-day"
HOOKS = (HOOK_BATCH, HOOK_UPLOAD, HOOK_CENTER)
HOOK_WORDS = {HOOK_BATCH: "перед батчем", HOOK_UPLOAD: "после загрузки",
              HOOK_CENTER: "первое открытие центра за день", None: "страховка раз в сутки"}
# CF-0926: the tick's planned read takes the hook rule (`hook_min_gap_hours`: a
# read a few hours old is one visit) - not the 24-hour insurance window, which
# a daily read at the same hour would miss every other day by minutes
HOOK_SCHEDULE = "schedule"
HOOK_WORDS[HOOK_SCHEDULE] = "плановое чтение раз в сутки"
STATE_ENV = "STUDIO_READ_STATE_DIR"
STATE_DIR = Path("schedule") / "studio-read"
OPENS_FILE = "center-opens.json"
INSURANCE_FILE = "insurance.json"
RUNS_DIR = "runs"
LOCK_FILE = ".lock"
CLAUDE_ENV = "STUDIO_READ_CLAUDE"          # the claude binary (tests put a stand-in here)
DEFAULT_CLAUDE_FALLBACK = Path.home() / ".local" / "bin" / "claude"
MODEL = "sonnet"
CHROME_TOOLS = "mcp__claude-in-chrome__*"
INSURANCE_EVERY_H = 24
INSURANCE_KIND = "needs_human"
INSURANCE_KEY = "studio_insurance"

LAUNCH_REFUSALS = ("bad_who", "no_channels", "running", "no_claude", "spawn_failed")
OUTCOMES = ("read", "no_extension", "login_needed", "error", "running")
OUTCOME_WORDS = {"read": "прочитано", "no_extension": "расширение не подключено",
                 "login_needed": "нужен вход", "error": "ошибка", "running": "читается"}
RESULT_RE = re.compile(r"STUDIO_READ_RESULT:\s*(read|no_extension|login_needed|error)\b"
                       r"\s*[—–:-]*\s*(.*)$", re.MULTILINE)
# What the log says when the session itself could not go on (no marker line).
NOT_LOGGED_IN_RE = re.compile(r"not logged in|please run /login|invalid api key|"
                              r"authentication_error|session expired", re.I)
NO_EXTENSION_RE = re.compile(r"(chrome|browser)[^\n]{0,60}extension[^\n]{0,40}"
                             r"(not (connected|installed|found|available)|disconnected)|"
                             r"extension[^\n]{0,40}not connected|no (connected )?browser|"
                             r"claude[- ]in[- ]chrome[^\n]{0,60}(not|unavailable)|"
                             r"расширени[ея][^\n]{0,40}не (подключено|установлено|найдено)", re.I)
# CF-0786: the read's data is committed by the launch's runner after the session.
COMMIT_TASK = "CF-0786"
COMMIT_MARK = "STUDIO_READ_COMMIT:"
COMMIT_RE = re.compile(r"^STUDIO_READ_COMMIT:\s*(\w+)", re.MULTILINE)
READ_DATA = ("studio.jsonl", "studio_visits.jsonl")                     # analytics/<channel>/
LOGIN_RE = re.compile(r"accounts\.google\.com|sign in to (continue|youtube)|"
                      r"войдите в аккаунт|войти в аккаунт|нужен вход", re.I)


class CenterError(ValueError):
    """A bad call (unknown hook or channel)."""


# ------------------------------------------------------------------ helpers

def _root(root=None):
    return Path(root or ROOT).resolve()


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc)
    return sr._instant(now, "now")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _msk_day(dt):
    return dt.astimezone(sr.MSK).date().isoformat()


def state_dir(root=None, environ=None):
    env = os.environ if environ is None else environ
    if env.get(STATE_ENV):
        return Path(env[STATE_ENV]).expanduser()
    return _root(root) / STATE_DIR


@contextlib.contextmanager
def _locked(root=None, environ=None, d=None):
    d = state_dir(root, environ) if d is None else Path(d)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / LOCK_FILE, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _read_json(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _write_json_atomic(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def hours_word(n):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _notify_module():
    spec = importlib.util.spec_from_file_location("notify_for_studio_center",
                                                  ROOT / "shared" / "notify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def readable_channels(root=None):
    """`(channels, skipped)`: the channels with a pipeline, Studio settings and
    a schedule that is on (CF-0926: a closed channel is not read); the rest as
    one line each."""
    out, skipped = [], []
    names = sr.all_channels(root)
    running = scheduled_channels(names, root)
    for ch in names:
        if ch not in running:
            skipped.append(f"{ch}: расписание канала выключено (канал закрыт) - Studio не читаем")
            continue
        stub = sr.no_pipeline(ch, root)
        if stub:
            skipped.append(f"{ch}: {stub} - читать в Studio нечего")
            continue
        try:
            sr.studio_settings(ch, root)
        except (sr.ReadError, OSError, ValueError) as e:
            skipped.append(f"{ch}: {e}")
            continue
        out.append(ch)
    return out, skipped


# ------------------------------------------------------------------ the center's first open

def record_center_open(root=None, now=None, environ=None):
    """Note an open of the center; True when it is the first of the Moscow day.
    The file is rewritten atomically under the lock - two tabs opening at once
    make one first open."""
    now = _now(now)
    day = _msk_day(now)
    with _locked(root, environ) as d:
        path = d / OPENS_FILE
        st = _read_json(path) or {}
        first = st.get("day") != day
        doc = {"day": day, "first_open_at": _iso(now) if first else st.get("first_open_at"),
               "last_open_at": _iso(now), "opens": 1 if first else int(st.get("opens") or 0) + 1,
               "task": TASK}
        _write_json_atomic(path, doc)
    return first


# ------------------------------------------------------------------ due

def _channel_due(ch, root, now, hook):
    """One channel by the rule of `studio_read.due`: the hook gap for a hook,
    the insurance window without one."""
    is_due, _line = sr.due(ch, root, _iso(now), hook)
    last = sr.store.last_visit(ch, sr.store_root(root))
    if last is None:
        return {"channel": ch, "due": True, "last_read_at": None, "age_hours": None,
                "why": f"{ch}: Studio ни разу не читали - пора читать"}
    at = sr._instant(last["read_at"])
    age = round((now - at).total_seconds() / 3600, 1)
    when = f"последнее чтение {sr._msk(at)}, {age:g} ч назад"
    if is_due:
        why = f"{ch}: пора читать Studio - {when}"
    else:
        why = f"{ch}: Studio прочитан недавно - {when}"
    return {"channel": ch, "due": bool(is_due), "last_read_at": sr._utc_text(at),
            "age_hours": age, "why": why}


def studio_read_due(channel=None, hook=None, root=None, now=None, environ=None):
    """Is a Studio read due - for one channel or the whole factory (None)?
    See the module's docstring for the answer. `center-first-open-of-day`
    records the open (the only write here)."""
    if hook not in HOOKS + (HOOK_SCHEDULE, None):
        raise CenterError(f"hook {hook!r}: one of {', '.join(HOOKS)} or none")
    root = _root(root)
    now = _now(now)
    first = None
    rule_hook = hook
    if hook == HOOK_CENTER:
        first = record_center_open(root, now, environ)
        rule_hook = HOOK_CENTER if first else None
    if channel:
        if channel not in sr.all_channels(root):
            raise CenterError(f"channel {channel!r} has no channels/{channel}.json")
        names, skipped = [channel], []
    else:
        names, skipped = readable_channels(root)
    rows = []
    for ch in names:
        try:
            rows.append(_channel_due(ch, root, now, rule_hook))
        except sr.ReadError as e:
            if channel:
                raise CenterError(str(e)) from None
            skipped.append(f"{ch}: {e}")
    due_rows = [r for r in rows if r["due"]]
    ages = [r["age_hours"] for r in rows]
    never = any(a is None for a in ages)
    word = HOOK_WORDS[hook] + ("" if first is not False else
                               " уже было сегодня - по страховке раз в сутки")
    if not rows:
        why = "читать нечего: ни у одного канала нет настроек чтения Studio"
    elif due_rows:
        why = f"пора читать Studio ({word}): " + "; ".join(r["why"] for r in due_rows)
    else:
        why = f"читать не нужно ({word}): " + "; ".join(r["why"] for r in rows)
    last_reads = [r["last_read_at"] for r in rows if r["last_read_at"]]
    return {"task": TASK, "channel": channel, "hook": hook, "hooks": list(HOOKS),
            "due": bool(due_rows), "why": why,
            "last_read_at": None if never or not last_reads else min(last_reads),
            "age_hours": None if never or not ages else max(ages),
            "first_open_today": first, "running": running_run(root, environ),
            "channels": rows, "skipped": skipped}


# ------------------------------------------------------------------ the launch

def claude_binary(claude=None, environ=None):
    env = os.environ if environ is None else environ
    for c in (claude, env.get(CLAUDE_ENV)):
        if c:
            return str(c)
    return shutil.which("claude") or str(DEFAULT_CLAUDE_FALLBACK)


# CF-0759: the session runs Bash only in these exact forms, from the factory
# root (its cwd). The first real launch (15.10, run 20261015T185106Z) was
# denied because the model wrapped the allowed command in a shell loop
# (`for c in ...; do python3 agents/analyst/studio_read.py plan --channel $c;
# done`): a loop with a variable matches no prefix rule, so it would ask, and
# `dontAsk` turns every ask into a deny. The prompt therefore names each
# command line as it must be typed, one call per command.
PYTHON = "python3"
READ_SCRIPT = "agents/analyst/studio_read.py"
READ_STEPS = ("plan", "parse", "record")
CLOCK = "date -u +%Y-%m-%dT%H:%M:%SZ"   # `read_at`; python 3.9 reads Z, not +0300


def allowed_tools():
    """Chrome for Studio; Bash only for the read's own command lines (the
    three `studio_read.py` steps, the clock for `read_at`);
    Read/Write for the read JSON. Everything else is denied (`dontAsk`),
    never waited on. Each rule is one argv element (`launch_argv`)."""
    return ([CHROME_TOOLS]
            + [f"Bash({PYTHON} {READ_SCRIPT} {step}:*)" for step in READ_STEPS]
            + [f"Bash({CLOCK})", "Read", "Write"])


def launch_argv(claude, root, extra_dirs=()):
    """`--allowedTools` takes each rule as its own argument (the option is
    variadic), so no rule depends on how claude splits a joined list; the
    session's cwd is `root` (the launch), `--add-dir` also names any state
    dir outside it (STUDIO_READ_STATE_DIR)."""
    dirs = [str(root)] + [str(d) for d in extra_dirs if str(d) != str(root)]
    return [claude, "-p", "--chrome", "--model", MODEL, "--output-format", "text",
            "--permission-mode", "dontAsk", "--allowedTools", *allowed_tools(),
            "--add-dir", *dirs]


def _shown_path(path, root):
    """`path` as the session types it: relative to its cwd (the root) when
    inside it, else absolute."""
    path = Path(path)
    if root is not None:
        try:
            return str(path.resolve().relative_to(Path(root).resolve()))
        except ValueError:
            pass
    return str(path)


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def read_commands(run_id, runs_dir, by, via, root=None):
    """The exact Bash lines of the read, `<канал>` to be put in by the
    session: {clock, plan, parse, record}."""
    read_json = f"{_shown_path(runs_dir, root)}/{run_id}-<канал>.json"
    return {
        "clock": CLOCK,
        "plan": f"{PYTHON} {READ_SCRIPT} plan --channel <канал>",
        "parse": f"{PYTHON} {READ_SCRIPT} parse {read_json} --channel <канал>",
        "record": f"{PYTHON} {READ_SCRIPT} record {read_json} --channel <канал> "
                  f"--by {by} --via {via}",
    }


def read_prompt(channels, run_id, runs_dir, by, via, root=None):
    root = _root(root)                      # the session's cwd (the launch)
    cmd = read_commands(run_id, runs_dir, by, via, root)
    read_json = f"{_shown_path(runs_dir, root)}/{run_id}-<канал>.json"
    if by == SCHED_BY:                      # CF-0926: the tick's planned read
        start = (f"Запуск - плановое чтение по расписанию ({SCHED_TASK}, запуск {run_id}): "
                 f"пользователя у ноутбука может не быть; Chrome с расширением должен быть "
                 f"открыт - если нет, итог no_extension, не жди.")
    else:
        start = (f"Запуск - кнопка «Прочитать Studio» в командном центре ({TASK}, запуск "
                 f"{run_id}): пользователь у ноутбука, Chrome открыт.")
    lines = [
        f"Прочитай YouTube Studio по agents/analyst/SKILL.md, раздел «Чтение Studio (CF-0588)», "
        f"шаги 1-7, для каналов: {', '.join(channels)}. " + start,
        "",
        "Правила:",
        "- Только studio.youtube.com и только чтение: открыть страницу, переключить вкладку "
        "или период, прочитать. Никаких «Изменить», «Оспорить», «Удалить», «Принять», никаких "
        "форм и отправок.",
        "- Chrome: сначала tabs_context_mcp с createIfEmpty: true, работай во вкладке своей "
        "группы; вкладки пользователя не трогай и не закрывай. Если подключено несколько "
        "браузеров - switch_browser (пользователь подтвердит у себя), не AskUserQuestion: "
        "спросить в этой сессии некого.",
        "- Убедись, что Studio показывает нужный канал (переключатель аккаунта); если нет - "
        "переключи канал, это не действие над контентом.",
        f"- В прочитанном JSON `hook` = \"{'daily' if by == SCHED_BY else 'manual'}\", `read_at` - вывод команды `{cmd['clock']}` "
        f"сразу после чтения; файл клади инструментом Write в {read_json} "
        "(вместо scratchpad из шага 5).",
        "",
        f"Bash в этой сессии разрешён ТОЛЬКО на эти строки, из текущего каталога (корень "
        f"фабрики, {root}), по одному каналу и по одной "
        "команде за вызов, ровно в этом виде; <канал> - имя канала:",
        f"  {cmd['plan']}",
        f"  {cmd['clock']}",
        f"  {cmd['parse']}",
        f"  {cmd['record']}",
        "- Никаких циклов (for/while), переменных ($c), `;`, `&&`, `|`, `cd`, `2>&1`, "
        "абсолютных путей к скриптам, .venv/bin/python или python вместо python3: любая "
        "другая форма отказана без вопроса (режим dontAsk). Файлы (SKILL.md и прочие) читай "
        "инструментом Read, не через Bash.",
        "- Отказ Bash - повтори эту же команду ровно в виде из списка выше; итог error только "
        "если отказана строка ровно из списка.",
        "- Прочие скрипты в этой сессии не запускай.",
        f"- git не трогай: записанное (analytics/<канал>/studio*.jsonl) коммитит фабрика "
        f"сама, когда сессия закончится ({COMMIT_TASK}).",
        "",
        "Последней строкой ответа - ровно одна строка итога:",
        "STUDIO_READ_RESULT: read - <какие каналы прочитаны и записаны>",
        "STUDIO_READ_RESULT: no_extension - <инструменты Claude in Chrome недоступны, "
        "расширение не подключено>",
        "STUDIO_READ_RESULT: login_needed - <Studio просит войти в аккаунт Google>",
        "STUDIO_READ_RESULT: error - <что не получилось>",
    ]
    return "\n".join(lines) + "\n"


def _alive(pid):
    if not pid:
        return False
    try:
        got, _status = os.waitpid(int(pid), os.WNOHANG)     # our own child: reap it
        if got:
            return False
    except ChildProcessError:
        pass
    except OSError:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _runs(root=None, environ=None):
    d = state_dir(root, environ) / RUNS_DIR
    if not d.is_dir():
        return []
    rows = []
    for p in sorted(d.glob("*.json")):
        doc = _read_json(p)
        if doc and doc.get("task") == TASK and doc.get("run_id") == p.stem:
            rows.append(doc)
    return rows


def _over(rec, text):
    """The run has come to its end by its log: the result line - and, for a run
    under the runner (CF-0786), the runner's commit line after it."""
    if rec and rec.get("runner"):
        return bool(COMMIT_RE.search(text))
    return bool(RESULT_RE.search(text))


def running_run(root=None, environ=None):
    """The run id of a reading session still going, or None."""
    for r in reversed(_runs(root, environ)):
        if _alive(r.get("pid")) and not _over(r, _log_text(r.get("log"))):
            return r["run_id"]
    return None


def _new_run_id(d, now):
    base = now.strftime("%Y%m%dT%H%M%SZ")
    run_id, n = base, 1
    while (d / f"{run_id}.json").exists() or (d / f"{run_id}.log").exists():
        n += 1
        run_id = f"{base}-{n}"
    return run_id


# ------------------------------------------------------------------ the commit (CF-0786)

def _git_commit_module():
    return _by_path("git_commit_for_studio_center", ROOT / "shared" / "runlog" / "git_commit.py")


def _by_path(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _open_batches(root):
    """The fresh open runs (`runlog.open_batches`, what `runlog batch-active`
    counts) a root commit would be `code_drift` for: [(dir, why)]. A channel
    run whose executor holds its lock but which has not reached `batch-start`
    yet is left out - its HEAD is not recorded yet, the commit lands before
    it. A rebuild always counts. A runlog that cannot answer counts as a
    batch open (any doubt is open - the rule of `scripts/monthly_archive.py`)."""
    d = str(ROOT / "shared" / "runlog")
    try:
        if d not in sys.path:
            sys.path.insert(0, d)
        import runlog                                            # noqa: PLC0415
        out = []
        for r in runlog.open_batches(root):
            if not r[2]:
                continue
            bdir = Path(r[0])
            if (bdir.parent.name != "rebuilds"
                    and runlog._batch_start_event(runlog.read_events(bdir)) is None):
                continue                                         # not started: no HEAD yet
            out.append((r[0], getattr(r, "why", None)))
        return out
    except Exception as e:                                       # noqa: BLE001
        return [(None, f"runlog batch-active не ответил ({type(e).__name__}: {e})")]


def read_data_paths(root=None):
    """The tracked files a Studio read writes, relative to `root`, that exist
    now: `analytics/<канал>/{studio,studio_visits}.jsonl` of every channel
    directory under analytics/ (studio_read record). Nothing else - never the
    daily series, never `git add -A`."""
    root = _root(root)
    out = []
    store = sr.store_root(root)
    if store.is_dir():
        for d in sorted(p for p in store.iterdir() if p.is_dir()):
            out += [f"analytics/{d.name}/{f}" for f in READ_DATA if (d / f).is_file()]
    return out


def commit_read_data(root=None, run_id=None, by=None, via=None, open_rows=None):
    """CF-0786: commit what the Studio read left uncommitted - one commit of
    exactly `read_data_paths` that git sees changed or new (shared/runlog/
    git_commit.write_and_commit, the factory's committer). `batch-start`
    refuses a root with an uncommitted tracked file of code (CF-0479); since
    CF-0895 analytics/ is a record path there (runlog.NON_CODE_PATHS).

    **Under an open batch past its `batch-start` nothing is committed**
    (`deferred`): the run's next plan - before its `batch-start` - commits it
    then (`_open_batches`). A read left dirty meanwhile is not a stage's code
    edit (stage_code_guard, CF-0895).

    -> {task, status, sha, paths, line, details}; status: committed | nothing |
       deferred | not_repo | refused. Never raises."""
    root = _root(root)
    out = {"task": COMMIT_TASK, "status": "nothing", "sha": None, "paths": [], "line": "",
           "details": []}
    try:
        gc = _git_commit_module()
        top = (gc.git(root, "rev-parse", "--show-toplevel", check=False).stdout.strip()
               if gc.is_repo(root) else "")
        if not top or Path(top).resolve() != root:
            # a directory inside somebody else's work tree is not the factory's repo
            out.update(status="not_repo", line=f"{root} - не корень git-репозитория, "
                                               f"коммитить некуда")
            return out
        rels = read_data_paths(root)
        pending = []
        if rels:
            for ln in gc.dirty(root, rels):
                path = ln[3:].split(" -> ")[-1].strip().strip('"')
                if (root / path).is_file() and path not in pending:
                    pending.append(path)
        out["paths"] = sorted(pending)
        if not pending:
            out["line"] = "данные чтения уже в git - коммитить нечего"
            return out
        rows = _open_batches(root) if open_rows is None else open_rows
        if rows:
            first = rows[0][0]
            where = Path(first).name if first else (rows[0][1] or "?")
            out.update(status="deferred",
                       line=(f"данные чтения не закоммичены: идёт батч ({where}) - их "
                             f"закоммитит следующий план перед batch-start"),
                       details=[f"{d}: {w}" for d, w in rows if d or w])
            return out
        who = ", ".join(x for x in (by, f"via {via}" if via else None) if x)
        msg = (f"Studio read{' ' + run_id if run_id else ''}"
               f"{' (' + who + ')' if who else ''}: its data committed by the factory "
               f"({COMMIT_TASK})\n\n" + "\n".join(out["paths"]) + "\n")
        writes = {root / p: (root / p).read_bytes() for p in out["paths"]}
        sha = gc.write_and_commit(root, writes, msg)
        out.update(status="committed", sha=sha,
                   line=f"данные чтения закоммичены ({sha[:12]}, файлов: {len(out['paths'])})")
    except Exception as e:                                       # noqa: BLE001
        details = list(getattr(e, "details", None) or [])
        out.update(status="refused", sha=None,
                   line=f"данные чтения не закоммичены: {type(e).__name__}: {e}",
                   details=details)
    return out


def run_session(run_json):
    """The detached runner of a launch (`studio_center.py session RUN_JSON`):
    the reading session (`argv` of the run, the prompt on stdin, its output in
    the run's log), then - whatever it came to - `commit_read_data`; the
    outcome is one COMMIT_MARK line of the log and `commit` of the run record.
    Returns the session's exit code."""
    run_json = Path(run_json)
    rec = _read_json(run_json)
    if not rec:
        sys.stderr.write(f"studio_center session: no run record {run_json}\n")
        return 2
    root = _root(rec.get("root"))
    code = 1
    try:
        with open(rec["prompt"], "rb") as stdin, open(rec["log"], "ab") as fh:
            proc = subprocess.Popen(rec["argv"], stdin=stdin, stdout=fh,
                                    stderr=subprocess.STDOUT, cwd=str(root), close_fds=True)
            code = proc.wait()
    except OSError as e:
        with open(rec["log"], "a", encoding="utf-8") as fh:
            fh.write(f"\nсессия не стартовала: {type(e).__name__}: {e}\n")
    res = commit_read_data(root, rec.get("run_id"), rec.get("by"), rec.get("via"))
    # the launch's lock: the launch writes the record's pid after the spawn
    with _locked(d=run_json.parent.parent):
        rec = _read_json(run_json) or rec
        rec["commit"] = res
        _write_json_atomic(run_json, rec)
        with open(rec["log"], "a", encoding="utf-8") as fh:
            fh.write(f"\n{COMMIT_MARK} {res['status']} - {res['line']}\n")
    return code


def runner_argv(run_json):
    """The detached runner of a launch: this file's `session` (CF-0786)."""
    return [sys.executable or PYTHON, str(AGENT / "studio_center.py"), "session", str(run_json)]


def studio_read_launch(by, via, confirmed=False, root=None, now=None, channels=None,
                       claude=None, environ=None):
    """The center's button «Прочитать Studio». Without `confirmed` - the plan
    (what would start), nothing started; with it - the reading session as a
    detached process (a session of its own, the prompt on stdin, its output in
    the run's log). The answer is a dict, never an exception for a refusal."""
    root = _root(root)
    now = _now(now)
    out = {"ok": False, "launched": False, "confirmed": bool(confirmed), "task": TASK,
           "by": by, "via": via, "channels": [], "argv": None, "run_id": None, "pid": None,
           "log": None, "refusals": [], "lines": []}

    def refuse(code, line):
        out["refusals"].append({"code": code, "line": line})

    try:
        out["by"], out["via"] = sr._who(by, "by"), sr._who(via, "via")
        if out["by"] is None or out["via"] is None:
            raise sr.ReadError("by and via are both required: the button is somebody's")
    except sr.ReadError as e:
        refuse("bad_who", str(e))
    names, skipped = readable_channels(root)
    if channels:
        unknown = [c for c in channels if c not in names]
        if unknown:
            refuse("no_channels", f"не читаются (нет настроек чтения Studio или канал "
                                  f"закрыт): {', '.join(unknown)}")
        names = [c for c in names if c in channels]
    out["channels"] = names
    if not names and not out["refusals"]:
        refuse("no_channels", "читать нечего: ни у одного канала нет настроек чтения Studio")
    exe = claude_binary(claude, environ)
    out["argv"] = launch_argv(exe, root, [state_dir(root, environ) / RUNS_DIR]
                              if not _inside(state_dir(root, environ), root) else ())
    if not (Path(exe).is_file() and os.access(exe, os.X_OK)):
        refuse("no_claude", f"нет исполняемого claude ({exe})")
    going = running_run(root, environ)
    if going:
        refuse("running", f"чтение уже идёт (запуск {going}) - дождитесь итога")
    out["lines"] = [f"каналы: {', '.join(names) or '-'}"] + [f"пропуск {s}" for s in skipped] + [
        "только studio.youtube.com и только чтение; запись studio_read.py record "
        f"--by {out['by']} --via {out['via']}",
        "первый настоящий запуск - только при пользователе у ноутбука (CF-0735)"]
    if out["refusals"]:
        out["lines"].insert(0, "отказ: " + out["refusals"][0]["line"])
        return out
    if not confirmed:
        out["ok"] = True
        out["lines"].insert(0, "план: ничего не запущено (нужно подтверждение)")
        return out
    with _locked(root, environ) as d:
        going = running_run(root, environ)
        if going:
            refuse("running", f"чтение уже идёт (запуск {going}) - дождитесь итога")
            out["lines"].insert(0, "отказ: " + out["refusals"][0]["line"])
            return out
        runs = d / RUNS_DIR
        runs.mkdir(parents=True, exist_ok=True)
        run_id = _new_run_id(runs, now)
        log = runs / f"{run_id}.log"
        prompt = runs / f"{run_id}.prompt.txt"
        prompt.write_text(read_prompt(names, run_id, runs, out["by"], out["via"], root),
                          encoding="utf-8")
        run_json = runs / f"{run_id}.json"
        # CF-0786: the session runs under the runner (`session`), which commits the
        # read's data after it; `pid` is the runner's (its group holds the session)
        runner = runner_argv(run_json)
        rec = {"run_id": run_id, "task": TASK, "started_at": _iso(now), "by": out["by"],
               "via": out["via"], "channels": names, "pid": None, "argv": out["argv"],
               "runner": runner, "root": str(root), "log": str(log), "prompt": str(prompt)}
        _write_json_atomic(run_json, rec)
        try:
            with open(os.devnull, "rb") as stdin, open(log, "ab") as fh:
                proc = subprocess.Popen(runner, stdin=stdin, stdout=fh,
                                        stderr=subprocess.STDOUT, cwd=str(root),
                                        start_new_session=True, close_fds=True)
        except OSError as e:
            run_json.unlink(missing_ok=True)
            refuse("spawn_failed", f"не стартовал {Path(runner[0]).name} ({e})")
            out["lines"].insert(0, "отказ: " + out["refusals"][0]["line"])
            return out
        rec["pid"] = proc.pid
        _write_json_atomic(run_json, rec)
    out.update(ok=True, launched=True, run_id=run_id, pid=proc.pid, log=str(log))
    out["lines"].insert(0, f"запущено чтение Studio: pid {proc.pid}, журнал {log}")
    return out


# ------------------------------------------------------------------ the outcome

def _log_text(log):
    if not log:
        return ""
    try:
        return Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _run_of(ref, root=None, environ=None):
    """(run record or None, log path or None) for a run id or a log path."""
    ref = str(ref or "").strip()
    if not ref:
        return None, None
    runs = state_dir(root, environ) / RUNS_DIR
    if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z(-[0-9]+)?", ref):
        rec = _read_json(runs / f"{ref}.json")
        return rec, Path(rec["log"]) if rec and rec.get("log") else runs / f"{ref}.log"
    p = Path(ref).expanduser()
    rec = _read_json(p.with_suffix(".json")) if p.suffix == ".log" else None
    return (rec if rec and rec.get("task") == TASK else None), p


def _recorded(rec, root):
    """The channels whose Studio visit was recorded since the run started,
    through `via` of the run."""
    if not rec:
        return []
    since = sr._instant(rec["started_at"])
    out = []
    for ch in rec.get("channels") or []:
        for v in sr.store.read_visits(ch, sr.store_root(root)):
            try:
                at = sr._instant(v.get("recorded_at") or "", "recorded_at")
            except sr.ReadError:
                continue
            if at >= since - timedelta(seconds=1) and v.get("via") == rec.get("via"):
                out.append(ch)
                break
    return out


def studio_read_result(ref, root=None, environ=None):
    """One line of what the reading session came to (see OUTCOMES)."""
    root = _root(root)
    rec, log = _run_of(ref, root, environ)
    out = {"run_id": (rec or {}).get("run_id"), "log": str(log) if log else None,
           "code": "error", "done": True, "line": "", "detail": "", "recorded": [],
           "commit": None}
    text = _log_text(log)
    if log is None or (not text and not (log and Path(log).exists())):
        out["detail"] = f"нет журнала запуска {ref!r}"
        out["line"] = f"{OUTCOME_WORDS['error']}: {out['detail']}"
        return out
    found = list(RESULT_RE.finditer(text))
    alive = _alive((rec or {}).get("pid")) and not _over(rec, text)
    if found and alive:
        code, detail = "running", "сессия прочитала Studio, фабрика коммитит данные чтения"
    elif found:
        code, detail = found[-1].group(1), found[-1].group(2).strip()
    elif alive:
        code, detail = "running", "сессия ещё читает Studio"
    elif NOT_LOGGED_IN_RE.search(text):
        code, detail = "error", "claude не вошёл в аккаунт (claude /login)"
    elif NO_EXTENSION_RE.search(text):
        code, detail = "no_extension", "Chrome без подключённого расширения Claude in Chrome"
    elif LOGIN_RE.search(text):
        code, detail = "login_needed", "Studio просит войти в аккаунт Google"
    else:
        tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-1:] or ["журнал пуст"]
        code, detail = "error", f"сессия закончилась без итога ({tail[0][:160]})"
    out["recorded"] = _recorded(rec, root)
    if code == "read" and rec and not out["recorded"]:
        code, detail = "error", (f"сессия сказала «прочитано», но записи чтения через "
                                 f"{rec.get('via')} нет ({detail})")
    out.update(code=code, done=code != "running", detail=detail)
    word = OUTCOME_WORDS[code]
    out["line"] = word + (f": {detail}" if detail else "")
    # CF-0786: what the runner did with the read's data (None: not yet / not a runner)
    out["commit"] = (rec or {}).get("commit") if out["done"] else None
    if out["commit"] and out["commit"].get("status") in ("committed", "deferred", "refused"):
        out["line"] += f"; {out['commit']['line']}"
    return out


# ------------------------------------------------------------------ the insurance

def insurance_text(due_rows, label=None, why=None, need=None):
    """CF-0925/0926: «📊 Studio не читали 54 часа (Reel) — статистика роликов не
    обновляется.» + what came of the planned read (`why`) + what is needed from
    the user (`need`) - the channels by their names (`label`)."""
    label = label or (lambda ch: ch)
    aged = [r for r in due_rows if r["age_hours"] is not None]
    never = [label(r["channel"]) for r in due_rows if r["age_hours"] is None]
    parts = []
    if aged:
        n = int(max(r["age_hours"] for r in aged))
        parts.append(f"Studio не читали {n} {hours_word(n)} "
                     f"({', '.join(label(r['channel']) for r in aged)})")
    if never:
        parts.append(("Studio ни разу не читали" if not aged else "ни разу")
                     + f" ({', '.join(never)})")
    lines = ["📊 " + "; ".join(parts) + " — статистика роликов не обновляется."]
    if why:
        lines.append(f"Плановое чтение: {why}.")
    lines.append(f"Нужно от вас: {need or nh().STUDIO_BUTTON}.")
    return "\n".join(lines)


def _bs_module():
    """shared/batch_schedule.py by path (once a process), None when it does not load."""
    try:
        return _by_path("batch_schedule_for_studio_center", ROOT / "shared" / "batch_schedule.py")
    except Exception:                                            # noqa: BLE001
        sys.modules.pop("batch_schedule_for_studio_center", None)
        return None


def scheduled_channels(names, root):
    """CF-0925: the channels the factory still runs - its schedule's `enabled`
    (channels/<c>.json `batch_schedule` under the center's overlay,
    shared/batch_schedule.py `channel_settings`). A closed one (ExampleScience
    since 05.11) needs no Studio read and no call. A setting that does not read
    keeps the channel: the call is a safety net."""
    bs = _bs_module()
    if bs is None:
        return list(names)
    out = []
    for ch in names:
        try:
            on = bs.channel_settings(ch, root).get("enabled", True)
        except Exception:                                        # noqa: BLE001
            on = True
        if on is not False:
            out.append(ch)
    return out


def studio_insurance_notify(root=None, now=None, environ=None, dry_run=False):
    """The safety net: at most one notification in INSURANCE_EVERY_H hours,
    when a channel's last full read is older than its `insurance_hours` (or
    there is none). Never raises for the bus; `dry_run` writes and sends
    nothing."""
    root = _root(root)
    now = _now(now)
    names, _skipped = readable_channels(root)                    # CF-0925/0926: no closed
    rows = []
    for ch in names:
        try:
            rows.append(_channel_due(ch, root, now, None))
        except sr.ReadError:
            continue
    due_rows = [r for r in rows if r["due"]]
    out = {"task": TASK, "sent": False, "status": None, "text": None, "link": None,
           "channels": [r["channel"] for r in due_rows], "why": "", "planned": None}
    if not due_rows:
        out["why"] = "страховка не нужна: Studio читали в пределах суток"
        return out
    gate = scheduled_insurance_gate(root, now, environ)          # CF-0926
    out["planned"] = gate
    if gate["quiet"]:
        out["why"] = f"страховка молчит: {gate['why']}"
        return out
    nf = _notify_module()
    out["text"] = insurance_text(due_rows, lambda ch: nf.channel_label(ch, root),
                                 gate["why"], gate["need"])
    out["link"] = nf.center_url("", environ=environ)
    if running_run(root, environ):
        out["why"] = "чтение Studio уже идёт - не звать"
        return out
    with _locked(root, environ) as d:
        path = d / INSURANCE_FILE
        st = _read_json(path) or {}
        last = st.get("last_sent_at")
        if last:
            try:
                age = (now - sr._instant(last, "last_sent_at")).total_seconds() / 3600
            except sr.ReadError:
                age = None
            if age is not None and 0 <= age < INSURANCE_EVERY_H:
                out["why"] = (f"уже звали {sr._msk(sr._instant(last))} - не чаще раза в "
                              f"{INSURANCE_EVERY_H} ч")
                return out
        if dry_run:
            out["why"] = "сухой прогон: ничего не отправлено"
            return out
        key = f"{INSURANCE_KEY}:{_iso(now)}"
        try:
            res = nf.send(INSURANCE_KIND, key, out["text"], link=out["link"], root=root,
                          now=_iso(now), environ=environ, multiline=True)
        except Exception as e:                                   # noqa: BLE001
            res = {"status": f"error: {type(e).__name__}: {e}"}
        out["status"] = (res or {}).get("status")
        if out["status"] in ("sent", "duplicate"):
            _write_json_atomic(path, {"last_sent_at": _iso(now), "key": key, "text": out["text"],
                                      "status": out["status"], "task": TASK})
            out["sent"] = True
            out["why"] = "позвали пользователя"
        else:
            out["why"] = f"уведомление не ушло ({out['status']})"
    return out


# ------------------------------------------------------------------ the planned read (CF-0926)

SCHED_TASK = "CF-0926"
SCHED_FILE = "scheduled.json"
SCHED_BY, SCHED_VIA = "schedule", "tick"
SCHED_MAX_ATTEMPTS = 3
SCHED_RETRY_AFTER = timedelta(minutes=30)       # after an error or a refused launch
SCHED_FIX_WAIT = timedelta(minutes=60)          # after a failure only the user fixes
SCHED_LATE = timedelta(hours=3)                 # no state for today this long after the hour
SCHED_KIND = "studio_read"
SCHED_KEY = "studio_read"
USER_FIXABLE = ("login_needed", "no_extension")
SCHED_DEFAULT_AT = "08:15"
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def nh():
    """shared/notify_human.py by path (the message builders)."""
    return _by_path("notify_human_for_studio_center", ROOT / "shared" / "notify_human.py")


def _hhmm(text):
    m = _HHMM.match(str(text or "").strip())
    if not m:
        raise CenterError(f"studio_read_at {text!r}: время ЧЧ:ММ")
    return int(m.group(1)), int(m.group(2))


def _at_today(now, at):
    h, m = _hhmm(at)
    local = now.astimezone(sr.MSK)
    return local.replace(hour=h, minute=m, second=0, microsecond=0).astimezone(timezone.utc)


def _msk_hhmm(dt):
    return dt.astimezone(sr.MSK).strftime("%H:%M")


def schedule_settings(root=None, environ=None):
    """`{studio_read: bool, studio_read_at: "HH:MM"}` of shared/batch_schedule.py
    (`factory_settings`); the defaults when it does not load."""
    bs = _bs_module()
    try:
        got = bs.factory_settings(root, environ) if bs else {}
    except Exception:                                            # noqa: BLE001
        got = {}
    return {"studio_read": got.get("studio_read", True) is not False,
            "studio_read_at": got.get("studio_read_at") or SCHED_DEFAULT_AT}


def scheduled_state(root=None, environ=None):
    """The planned read's state file (`schedule/studio-read/scheduled.json`), {} when none."""
    return _read_json(state_dir(root, environ) / SCHED_FILE) or {}


def _save_state(st, root, environ):
    with _locked(root, environ) as d:
        _write_json_atomic(d / SCHED_FILE, dict(st, task=SCHED_TASK))


def read_summary(rec, root=None):
    """CF-0926: what a run read, per channel - `[{channel, videos}]`:
    the videos of its visit (recorded through the run's `via` since it started)."""
    if not rec:
        return []
    since = sr._instant(rec["started_at"]) - timedelta(seconds=1)
    out = []
    for ch in rec.get("channels") or []:
        visit = None
        for v in sr.store.read_visits(ch, sr.store_root(root)):
            try:
                at = sr._instant(v.get("recorded_at") or "", "recorded_at")
            except sr.ReadError:
                continue
            if at >= since and v.get("via") == rec.get("via"):
                visit = v
        if visit is None:
            continue
        out.append({"channel": ch, "videos": int(visit.get("videos_read") or 0)})
    return out


def _send(kind, key, text, root, now, environ):
    nf = _notify_module()
    try:
        res = nf.send(kind, key, text, link=nf.center_url("", environ=environ), root=root,
                      now=_iso(now), environ=environ, multiline=True)
    except Exception as e:                                       # noqa: BLE001
        res = {"status": f"error: {type(e).__name__}: {e}"}
    return (res or {}).get("status")


def _counted(st):
    return len(st.get("attempts") or [])


def _last_attempt(st):
    att = st.get("attempts") or []
    return att[-1] if att else None


def _retry_at(att, max_left):
    """When the next attempt may go after `att`, or None when none is left."""
    if not max_left or not att:
        return None
    base = sr._instant(att.get("done_at") or att["at"], "at")
    return base + (SCHED_FIX_WAIT if att.get("code") in USER_FIXABLE else SCHED_RETRY_AFTER)


def _collect(st, root, now, environ, out):
    """The finished run of the planned read: its attempt row, the day's outcome,
    one message per run id (`studio_read:<run_id>`)."""
    run_id = st.get("run_id")
    res = studio_read_result(run_id, root, environ)
    if not res["done"]:
        out["lines"].append(f"плановое чтение {run_id} ещё идёт")
        return
    st["run_id"] = None
    att = next((a for a in reversed(st.get("attempts") or []) if a.get("run_id") == run_id),
               None)
    if att is None:
        att = {"at": _iso(now), "run_id": run_id}
        st.setdefault("attempts", []).append(att)
    att.update(code=res["code"], line=res["line"], done_at=_iso(now))
    rec = _read_json(state_dir(root, environ) / RUNS_DIR / f"{run_id}.json") or {}
    left = SCHED_MAX_ATTEMPTS - _counted(st)
    text = kind = None
    if res["code"] == "read":
        st.update(outcome="read", outcome_at=_iso(now), last_read_at=_iso(now))
        text, kind = nh().studio_read_text(read_summary(rec, root), root), SCHED_KIND
    else:
        if left <= 0:
            st.update(outcome="failed", outcome_at=_iso(now))
        if res["code"] in USER_FIXABLE:
            nxt = _retry_at(att, left)
            text = nh().studio_failed_text(res["code"], rec.get("channels") or [], root,
                                           retry_at=_msk_hhmm(nxt) if nxt else None)
            kind = INSURANCE_KIND
    out["collected"] = {"run_id": run_id, "code": res["code"], "line": res["line"]}
    out["lines"].append(f"плановое чтение {run_id}: {res['line']}")
    if text:
        status = _send(kind, f"{SCHED_KEY}:{run_id}", text, root, now, environ)
        out["notified"].append({"kind": kind, "key": f"{SCHED_KEY}:{run_id}", "text": text,
                                "status": status})


def _roll(st, day):
    """A new Moscow day: the old one goes to `previous` (the safety net reads
    it), a run still going carries over with its attempt."""
    if st.get("day") == day:
        return st
    carried = [a for a in st.get("attempts") or [] if st.get("run_id")
               and a.get("run_id") == st.get("run_id")]
    prev = None
    if st.get("day"):
        last = _last_attempt(st) or {}
        prev = {"day": st["day"], "outcome": st.get("outcome"),
                "attempts": _counted(st), "last_code": last.get("code"),
                "last_line": last.get("line"), "waiting": st.get("waiting")}
    return {"day": day, "attempts": carried, "run_id": st.get("run_id") if carried else None,
            "outcome": None, "outcome_at": None, "waiting": None,
            "last_read_at": st.get("last_read_at"), "previous": prev}


def scheduled_read(root=None, now=None, at=None, enabled=None, blocked=None, environ=None,
                   dry_run=False):
    """CF-0926: one tick of the planned Studio read. First the outcome of a
    launch that has ended is collected (and told: «📊 Studio прочитана…», or
    «⚠️ Studio не прочитана…» for what only the user fixes); then, once a
    Moscow day at `at` (the schedule's `studio_read_at`), the read is launched
    - `studio_read_launch(by="schedule", via="tick", confirmed=True)` for the
    channels `studio_read_due(hook="schedule")` finds due - unless `enabled`
    is False, `blocked` (the tick's reason: a batch open, the hour before a
    window), another read is going, the day's SCHED_MAX_ATTEMPTS are spent or
    the last failure is too fresh. `at`/`enabled` default to the schedule's
    settings. Returns {task, launched, run_id, collected, notified, line,
    lines, state}; never raises for a refusal."""
    root = _root(root)
    now = _now(now)
    cfg = schedule_settings(root, environ) if at is None or enabled is None else {}
    at = at or cfg["studio_read_at"]
    enabled = cfg["studio_read"] if enabled is None else enabled
    out = {"task": SCHED_TASK, "launched": False, "run_id": None, "collected": None,
           "notified": [], "lines": [], "line": "", "state": None}
    st = scheduled_state(root, environ)
    if st.get("run_id") and not dry_run:
        _collect(st, root, now, environ, out)
    st = _roll(st, _msk_day(now))
    why = None
    nxt = _retry_at(_last_attempt(st), SCHED_MAX_ATTEMPTS - _counted(st))
    if not enabled:
        why = "плановое чтение выключено (batch_schedule.py settings --studio-read on)"
    elif st.get("outcome") == "read":
        why = f"сегодня уже прочитано ({sr._msk(sr._instant(st['outcome_at']))})"
    elif st.get("outcome") == "not_due":
        why = "сегодня не нужно: Studio читали недавно"
    elif st.get("outcome") == "failed":
        why = f"сегодня не вышло: {SCHED_MAX_ATTEMPTS} попытки из {SCHED_MAX_ATTEMPTS} истрачены"
    elif st.get("run_id"):
        why = f"идёт плановое чтение {st['run_id']}"
    elif now < _at_today(now, at):
        why = f"ещё не время: плановое чтение в {at} МСК"
    elif _counted(st) >= SCHED_MAX_ATTEMPTS:
        st.update(outcome="failed", outcome_at=_iso(now))
        why = f"сегодня не вышло: {SCHED_MAX_ATTEMPTS} попытки из {SCHED_MAX_ATTEMPTS} истрачены"
    elif nxt and now < nxt:
        why = f"следующая попытка не раньше {_msk_hhmm(nxt)} МСК"
    elif blocked:
        why = f"ждёт: {blocked}"
        st["waiting"] = blocked
    elif running_run(root, environ):
        why = f"ждёт: идёт другое чтение Studio ({running_run(root, environ)})"
        st["waiting"] = "шло другое чтение Studio"
    else:
        try:
            due = studio_read_due(None, HOOK_SCHEDULE, root, now, environ)
        except (CenterError, sr.ReadError) as e:
            due = {"due": False, "channels": [], "why": str(e)}
        names = [r["channel"] for r in due["channels"] if r["due"]]
        if not names:
            st.update(outcome="not_due", outcome_at=_iso(now))
            why = "сегодня не нужно: " + due["why"]
        elif dry_run:
            why = f"запустил бы плановое чтение (сухой прогон): {', '.join(names)}"
        else:
            res = studio_read_launch(SCHED_BY, SCHED_VIA, confirmed=True, root=root, now=now,
                                     channels=names, environ=environ)
            if res["launched"]:
                st.setdefault("attempts", []).append({"at": _iso(now), "run_id": res["run_id"],
                                                      "channels": names})
                st.update(run_id=res["run_id"], waiting=None)
                out.update(launched=True, run_id=res["run_id"])
                why = (f"запущено плановое чтение {res['run_id']} "
                       f"(попытка {_counted(st)} из {SCHED_MAX_ATTEMPTS}): {', '.join(names)}")
            else:
                ref = res["refusals"][0] if res["refusals"] else {"code": "error", "line": "?"}
                if ref["code"] == "running":
                    why = f"ждёт: {ref['line']}"
                else:
                    st.setdefault("attempts", []).append({
                        "at": _iso(now), "run_id": None, "code": f"refused:{ref['code']}",
                        "line": ref["line"], "done_at": _iso(now)})
                    if _counted(st) >= SCHED_MAX_ATTEMPTS:
                        st.update(outcome="failed", outcome_at=_iso(now))
                    why = (f"плановое чтение не запустилось ({ref['line']}); попытка "
                           f"{_counted(st)} из {SCHED_MAX_ATTEMPTS}")
    out["lines"].append(why)
    out["line"] = "чтение Studio: " + "; ".join(out["lines"])
    out["state"] = st
    if not dry_run:
        _save_state(st, root, environ)
    return out


def _gate_words(code, line=None):
    """(why, need) of a planned read that did not read, by its last code."""
    words = nh().STUDIO_FAIL_WORDS
    fix = nh().STUDIO_FIX
    button = nh().STUDIO_BUTTON
    if code in fix:
        return words[code], f"{fix[code]}; потом {button}"
    if code and code.startswith("refused:"):
        return (f"не запустилось ({line or code})",
                f"проверить claude на Mac (в терминале `claude`); потом {button}")
    return (f"чтение закончилось ошибкой ({line})" if line else words["error"],
            f"посмотреть журнал запуска в центре; потом {button}")


def scheduled_insurance_gate(root=None, now=None, environ=None):
    """CF-0926: may the safety net speak? `{quiet, why, need}`. Quiet while the
    planned read of the day is still to come or going, and after it read;
    speaks when it is off, when today's attempts are spent without a read, when
    the last day's read did not read (before today's hour) and when no planned
    read ran today long past its hour (the tick is not running)."""
    root = _root(root)
    now = _now(now)
    cfg = schedule_settings(root, environ)
    button = nh().STUDIO_BUTTON
    if not cfg["studio_read"]:
        return {"quiet": False, "why": "выключено",
                "need": f"{button} (или включить плановое: batch_schedule.py settings "
                        f"--studio-read on)"}
    st = scheduled_state(root, environ)
    day = _msk_day(now)
    today = st if st.get("day") == day else None
    prev = (st.get("previous") if today else (st if st.get("day") else None)) or None
    at = cfg["studio_read_at"]
    try:
        at_dt = _at_today(now, at)
    except CenterError:
        at_dt = _at_today(now, SCHED_DEFAULT_AT)
    if today and today.get("outcome") in ("read", "not_due"):
        return {"quiet": True, "why": "сегодня плановое чтение прошло", "need": None}
    if today and today.get("outcome") == "failed":
        last = _last_attempt(today) or {}
        why, need = _gate_words(last.get("code"), last.get("line"))
        return {"quiet": False, "why": f"сегодня не вышло — {why} "
                f"({_counted(today)} {plural_attempts(_counted(today))})", "need": need}
    if now >= at_dt:
        if today or now - at_dt < SCHED_LATE:
            return {"quiet": True, "why": "плановое чтение сегодня ещё идёт или впереди",
                    "need": None}
        return {"quiet": False, "why": ("ещё ни разу не запускалось" if not st.get("day") else
                                        "сегодня не запускалось")
                + f", хотя пора было в {at} МСК (тик расписания не работает?)", "need": button}
    if prev is None:
        if today:                       # the tick is on it: the first planned read is today
            return {"quiet": True, "why": f"первое плановое чтение — сегодня в {at} МСК",
                    "need": None}
        return {"quiet": False, "why": f"ещё ни разу не запускалось (первое — в {at} МСК)",
                "need": button}
    if prev.get("outcome") in ("read", "not_due"):
        return {"quiet": True, "why": f"плановое чтение {prev['day']} прошло, следующее в {at}",
                "need": None}
    if prev.get("attempts"):
        why, need = _gate_words(prev.get("last_code"), prev.get("last_line"))
        return {"quiet": False, "why": f"вчера не вышло — {why}", "need": need}
    return {"quiet": False,
            "why": "вчера не запускалось" + (f" — {prev['waiting']}" if prev.get("waiting")
                                             else ""),
            "need": f"ничего срочного: следующее — сегодня в {at} МСК; прочитать сейчас — "
                    f"{button}"}


def plural_attempts(n):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "попытка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "попытки"
    return "попыток"


# ------------------------------------------------------------------ CLI

def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="studio_center.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("due", "launch", "result", "insurance", "commit-read", "session", "scheduled"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None)
        if name in ("due", "launch", "insurance", "scheduled"):
            p.add_argument("--now", default=None)
        if name == "due":
            p.add_argument("--channel", default=None)
            p.add_argument("--hook", choices=HOOKS, default=None)
        if name == "launch":
            p.add_argument("--by", required=True)
            p.add_argument("--via", required=True)
            p.add_argument("--confirm", action="store_true")
            p.add_argument("--channel", action="append", default=None)
        if name == "result":
            p.add_argument("ref", help="the run id or its log")
        if name in ("insurance", "scheduled"):
            p.add_argument("--dry-run", action="store_true")
        if name == "session":
            p.add_argument("run_json", help="the run record the launch wrote")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "session":
            return run_session(args.run_json)
        if args.cmd == "commit-read":
            res = commit_read_data(args.root)
            out.write(f"studio commit-read: {res['status']} - {res['line']}\n")
            for d in res["details"]:
                out.write(f"  {d}\n")
            return 0
        if args.cmd == "due":
            res = studio_read_due(args.channel, args.hook, args.root, args.now)
            out.write(("due: " if res["due"] else "ok: ") + res["why"] + "\n")
            return 1 if res["due"] else 0
        if args.cmd == "launch":
            res = studio_read_launch(args.by, args.via, args.confirm, args.root, args.now,
                                     args.channel)
            for ln in res["lines"]:
                out.write(ln + "\n")
            return 0 if res["ok"] else 2
        if args.cmd == "scheduled":
            res = scheduled_read(args.root, args.now, dry_run=args.dry_run)
            out.write(res["line"] + "\n")
            return 0
        if args.cmd == "result":
            res = studio_read_result(args.ref, args.root)
            out.write(f"{res['code']}: {res['line']}\n")
            return 0
        try:
            res = studio_insurance_notify(args.root, args.now, dry_run=args.dry_run)
        except Exception as e:                                   # noqa: BLE001
            # the safety net never stops a batch: said, exit 0
            out.write(f"страховка Studio: не проверена ({type(e).__name__}: {e})\n")
            return 0
        out.write(f"страховка Studio: {res['why']}" + (f" - {res['text']}" if res["text"] else "")
                  + "\n")
        return 0
    except (CenterError, sr.ReadError) as e:
        out.write(f"refused: {e}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

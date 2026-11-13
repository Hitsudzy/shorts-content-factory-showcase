#!/usr/bin/env python3
"""CF-0592: the batch plan of the factory, the switch that lets it run by
itself, and the tick that starts the day's batch.

Grill 2026-10-06 (Q10, Q10', Q12, Q14): **one batch a day for the whole
factory** (the YouTube Search quota - the search is never cut to fit more); a
batch gives 3-5 videos = 3-5 days of a channel's feed; with several channels
the day's batch goes to the channel whose nearest empty slot comes first.
Batches by the schedule start only after the center shows the plan AND the
user said «включай»: until then a batch is started by hand («запускай»).

    python3 shared/batch_schedule.py plan [--days N] [--now ISO] [--root DIR] [--json]
    python3 shared/batch_schedule.py status [--now ISO] [--json] [--root DIR]
    python3 shared/batch_schedule.py stranded [--now ISO] [--root DIR] [--json]
    python3 shared/batch_schedule.py enable --by user --note "«включай» в чате 07.10" [--root DIR]
    python3 shared/batch_schedule.py disable --by <who> [--note "..."] [--root DIR]
    python3 shared/batch_schedule.py tick [--dry-run] [--now ISO] [--root DIR]
    python3 shared/batch_schedule.py install-timer --print [--interval S] [--root DIR]
    python3 shared/batch_schedule.py settings [<channel> --by <who> [--enabled yes|no]
        [--window HH:MM] [--window-hours H] [--min-feed-days N] [--batch-feed-days N]
        [--note "..."]] [--root DIR]
    python3 shared/batch_schedule.py settings --by <who> [--studio-read on|off]
        [--studio-read-at HH:MM] [--note "..."] [--root DIR]      # CF-0926, the factory's

**The plan** (read only) - for each of the next N days (the Moscow day, by which its
windows are named): which
channel, when, why. Per channel of `channels/*.json`, nothing spelled here:

* the feed is `publish_queue.table` (CF-0587: day folders + the upload
  journal); the videos in `_queue/` and the ones of the last
  PENDING_HORIZON_DAYS waiting for acceptance (shared/factory_state.py, CF-0590)
  count as filling the next free slots - an estimate, said so;
* the window is `channels/<ch>.json` -> `batch_schedule`
  `{"window": "02:00", "tz": "Europe/Moscow", "window_hours": 3,
  "min_feed_days": 3, "batch_feed_days": 14}` (DEFAULTS when the block is absent -
  and the plan says "по умолчанию"); the tick starts a batch only inside it;
  CF-0922: `min_feed_days` is the feed's horizon (`publish_queue.horizon`: how far
  ahead a video is put into a slot), `batch_feed_days` the batch threshold below;
* how long a batch takes and how many videos it gives are the mean of the
  channel's last runs in `pipeline/runs.jsonl` - an **estimate**, with the
  number of runs it stands on (DEFAULT_WALL_S / DEFAULT_VIDEOS without runs);
* a day gets a batch when the feed after the window's start covers fewer than
  `batch_feed_days` days ("лента короче 14 дн.: пусто 10.10 01:00 МСК"; CF-0922:
  not `min_feed_days` - the morning fills the 3-day horizon from the reserve, so
  a threshold equal to the horizon is never crossed and no batch runs); of the
  channels that need one, the one whose first empty slot comes first; the
  planned batch fills its estimated videos into the free slots after its
  estimated end, and the next day is planned on that;
* a channel on pause (CF-0569, at the window's time), with no slot (no
  queue), with no `run_plan` (nothing for the executor) or with a placeholder
  voice (`TODO` in `voice_profile`, CF-0659 - the executor would refuse it) is
  not planned - and the plan says why;
* every day carries a `kind` next to its `why` (CF-0785, DAY_KINDS: running /
  done_today / nobody_plannable / nobody_available / fed / needs_batch); a
  planned day also carries `covers_days` (the days, in the slot's zone, its
  batch fills) and `first_empty_slot` (the feed's first empty slot at the
  window's start - before the batch, so not `fills[0]`, which comes after the
  batch's estimated end + lead);
* today is taken when a batch is open (`runlog.open_batches`, fresh ones:
  what `runlog batch-active` counts) or a batch already started today
  (`pipeline/runs.jsonl`, a batch directory of today, the tick's journal);
* CF-0787: **"a day" of the one-a-day rule is the YouTube Search quota day**
  (`quota_day`, shared/quota_day.py: Pacific midnight to Pacific midnight in
  America/Los_Angeles - 07:00Z under PDT, 08:00Z under PST, so 10:00 or 11:00
  МСК), not the Moscow calendar day: a window whose quota day already had a
  batch that spent quota (`started_on(quota=True)`, `spent_no_quota` still
  frees a batch that stopped before trend-hunter) - or that an earlier day of
  the plan takes - is blocked; the day says so (`kind: quota_day_taken`,
  `quota_day`, `next_windows`: each blocked channel's next possible window)
  and the tick refuses with that line. On 17.10 a Science batch at 11:17 МСК
  took the quota day 17.10, and the Reel window 18.10 02:00 МСК (23:00Z 17.10)
  falls in it; the next one is 19.10 02:00 МСК. «Today» for done_today, the
  button's `today` guard and the stranded rows' `holds_day` is the quota day
  of `now`. The executor hands the trend-hunter stage the day's earlier spend
  (`quota_day.day_spend`, `--searches-spent`).

**The switch** `schedule/switch.json` (the state directory, gitignored;
`BATCH_SCHEDULE_STATE_DIR` moves it): off when there is no file. `enable`
takes `--by user` only - the switch is the user's word «включай», relayed;
`disable` takes anyone. Every change is a row of its history (who, when,
note). No code path turns it on by itself: `plan`, `tick` and
`install-timer` never write it.

**The tick** - what a timer calls every INTERVAL_S. It starts
`shared/run_executor.py run <channel> --root <root>` in the background (a
session of its own, its output in `schedule/logs/<day>-<channel>.log`) only
when all of these hold, and otherwise prints the one line why not:
the switch is on; no batch is open; no batch started today; today's plan has
a channel; now is inside its window; the channel is not paused. The launch is
a row of `schedule/launches.jsonl` and one `batch_started` notification
(CF-0591). One attempt a day: a launch that failed at once still counts as
today's batch (the quota), its own halt/done notification says what happened.
Under an exclusive lock, so two ticks never start two batches.
Before all that, every tick (switch on or off, not on a dry run) runs the
API Data auto-run of `agents/publisher/api_data.py` (CF-0618, YouTube API
Services Developer Policies III.D.2.b / III.E.4.c): it deletes only what is
due - the API Data after a revocation mark 25 days old, journal API rows not
refreshed for 28 days - and only for the factory's own checkout (a tick on
another `--root`, e.g. a test's, runs it only when handed a `publisher_env`).

**The timer** is never installed by code: `install-timer --print` prints the
launchd plist (template `scripts/launchd/com.example-film.batch-schedule.plist
.template`) on stdout and the commands to install and remove it on stderr.
What «включай» turns on, and how to turn it off: `docs/batch-schedule.md`.

**The channel's settings** (CF-0605, set in the command center): per channel - whether it takes part in
the schedule, the window's start and length, the feed threshold - live in
`schedule/channel-settings.json` (the state directory, gitignored), an overlay
`window_config` reads over `channels/<ch>.json` -> `batch_schedule`, so the
center never changes a file in git. One writer, `set_channel_settings`
(validated, under a lock, a history row per change); `settings` prints them.
**The planned Studio read** (CF-0926, the user's decision 09.11): the tick
starts `agents/analyst/studio_center.py` `scheduled_read` once a Moscow day at
the factory's `studio_read_at` (08:15 by default), not while a batch is open
(`open_batches`, what `runlog batch-active` counts), not in the hour before
any running channel's window (STUDIO_COOLDOWN - the cooldown rule), at most 3
launches a day; it does not depend on the batch switch - it has its own
(`studio_read`). The two factory settings live in `schedule/factory-settings.json`
(`factory_settings` / `set_factory_settings`, a history row per change;
`settings --studio-read on|off --studio-read-at HH:MM --by <who>`), shown by
`settings` and `plan` (`studio_read`).
**«Запустить батч сейчас»** (`manual_launch`, the center's button): the
tick's guards but the window and the switch - an open batch, a batch already
today (refused too: one a day), the pause - and only when confirmed; the
same detached start, a `launches.jsonl` row `by: user (центр)` (rows of the
retired 2.2 console say `user (пульт)`), a
`batch_started` notification. **«Продолжить»** (CF-0667,
`shared/batch_control.py`) starts through the same `spawn_detached`; its
`launches.jsonl` row (`kind: resume`) is the same batch going on, so it does
not count as a batch of the day (`started_on` skips it).
**Stranded batches** (CF-0723, `stranded`, the center's screen): a batch or
a rebuild whose run-state says `failed`/`halted`/`stopped`, with no
`pipeline/runs.jsonl` row and not open - where it stopped, why, its log, and
whether it holds today the way `started_on` counts it.
**The repeat breaker** (CF-0822, `breakers`): a channel whose last batch of
the current quota day stopped (`failed`/`halted`) before spending quota is not
started again by the tick in that quota day while the code is the one the
failed batch ran on (its run header, else its launch row's `code`); new code
lets one repeat through; «запускай» (the button) is not held. The plan's day
carries `breaker` (kind `nobody_available` when no other channel takes the
day), `plan`/`status` list the breakers, and the tick
writes one `kind: repeat_held` row of `launches.jsonl` and one `run_halted`
notification per channel and quota day.
**A next batch in the same quota day** (CF-0830, by the Search budget): a
channel whose settings carry `windows` (a list of "HH:MM" - its windows of one
day, overriding `window`; the center's key, `settings --windows`) may take a
batch in a quota day that already has one when the quota day's spend
(`quota_day.day_spend`, plus the expected spend of a counted batch not on
record yet) + the channel's expected spend (`expected_searches`: the median
of its last QUOTA_BUDGET["expected_batches"] batches with a recorded
`search_quota`, `default_searches` without one) stays within the limit less
the margin and the quota day has fewer than `max_batches` - and never while
another runs (a next window starts after the plan's previous batch ends). The
plan's channel order is the same (the nearest empty slot); the day's further
batches go to `more` (the same fields as a planned day), every check of the
day to `budget` (`admission` records, `why` for a human), a booking admitted
by the budget carries `budget_admission`; the plan's `quota_budget` and
`status --json` `budget` give the values, the quota day's spend and each
channel's expected spend. The breaker holds a window of `windows` the same
way. Without `windows` nothing changes: one batch per quota day.

**`claude` logged in** (CF-0899). On 29.10 a Reel batch opened, halted a
minute later at trend-hunter on NOT_LOGGED_IN (`claude -p`: the OAuth session
expired and could not be refreshed) and, open, took the day until the driver
resumed it by hand 19 h later. Now: before the tick starts a batch it asks
`claude auth status --json` (no tokens; `login_state`) - not logged in, the
batch is not opened, the day is not taken, and one `needs_human` of the day
(key `claude_login:<Moscow day>`) says how to log in; the next tick after the
login starts it as usual. An open batch whose run-state says `halted` on
NOT_LOGGED_IN is the tick's to resume (`_resume_login_halted`, switch on): not
logged in - the same one notification a day; logged in, or not known (the
executor is the real check) - `batch_control.resume` by `tick (CF-0899)`, at
most once per LOGIN_RESUME_BACKOFF. The CLI is asked only on the factory's own
checkout, or when `RUN_EXECUTOR_CLAUDE` names a binary (tests: a stand-in).

Exit codes: 0 ok (a tick that starts nothing is ok); 2 refused / bad call.
"""
import argparse
import fcntl
import math
import importlib.util
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

TASK = "CF-0592"
CODE = Path(__file__).resolve().parent.parent
STATE_ENV = "BATCH_SCHEDULE_STATE_DIR"
STATE_DIR = "schedule"
SWITCH = "switch.json"
LAUNCHES = "launches.jsonl"
TICK_LOCK = "tick.lock"
TICK_LOG = "tick.log"
FACTORY_TZ = "Europe/Moscow"
BATCHES_PER_DAY = 1                 # the whole factory (grill 06.10, Q10: the Search quota)
PLAN_DAYS = 7
NEXT_WINDOW_DAYS = 14               # CF-0787: how far the plan looks for a blocked channel's window
PENDING_HORIZON_DAYS = 2
RUNS_FOR_ESTIMATE = 10
DEFAULT_WALL_S = 4 * 3600
DEFAULT_VIDEOS = 3
DEFAULTS = {"window": "02:00", "tz": FACTORY_TZ, "window_hours": 3, "min_feed_days": 3,
            "batch_feed_days": 14, "enabled": True}
# CF-0922: `min_feed_days` - the feed's horizon (publish_queue.horizon), `batch_feed_days` -
# the threshold of the tick (a batch when the feed covers fewer days). One key for both
# (CF-0918, 3) stopped the daily batch on 06.11; 14 is the threshold before CF-0918.
BATCH_FEED_TASK = "CF-0922"
SETTINGS = "channel-settings.json"   # CF-0605: the center's overlay over channels/*.json
SETTINGS_LOCK = "settings.lock"
SETTINGS_TASK = "CF-0605"
SETTINGS_KEYS = ("enabled", "window", "window_hours", "min_feed_days", "batch_feed_days",
                 "windows")
MAX_WINDOWS = 4                     # CF-0830: `windows` - the channel's windows of one day
FACTORY_SETTINGS = "factory-settings.json"   # CF-0926: the factory's own settings (not a channel's)
FACTORY_TASK = "CF-0926"
FACTORY_DEFAULTS = {"studio_read": True, "studio_read_at": "08:15"}
FACTORY_KEYS = tuple(FACTORY_DEFAULTS)
STUDIO_COOLDOWN = timedelta(minutes=60)      # no Studio read in the hour before a batch window
MIN_FEED_DAYS_MAX = 30
MANUAL_BY = "user (центр)"          # CC-0035; old rows of the retired console: "user (пульт)"
INTERVAL_S = 900
# CF-0899: `claude` not logged in. 29.10 a Reel batch opened, halted a minute
# later on NOT_LOGGED_IN at trend-hunter, and - open - took the day: nobody
# resumed it until the driver did by hand 19 h later.
LOGIN_TASK = "CF-0899"
CLAUDE_ENV = "RUN_EXECUTOR_CLAUDE"           # run_executor.CLAUDE_ENV: the binary (tests: a stand-in)
CLAUDE_FALLBACK = Path.home() / ".local" / "bin" / "claude"   # run_executor.DEFAULT_CLAUDE_FALLBACK
LOGIN_PROBE_TIMEOUT_S = 30
LOGIN_RESUME_BACKOFF = timedelta(minutes=60)  # the tick's resumes of one halted batch, apart
LOGIN_BY = "tick (CF-0899)"
LOGIN_HINT = "войди в claude: в терминале `claude`, затем /login"
NOT_LOGGED_IN = "NOT_LOGGED_IN"              # run_executor.NOT_LOGGED_IN
NOT_LOGGED_IN_RE = re.compile(               # run_executor.NOT_LOGGED_IN_RE
    r"not logged in|please run /login|run /login|/login\b|"
    r"oauth[^\n]{0,60}(expired|revoked|invalid)|session expired|"
    r"invalid api key|authentication_error", re.I)
LABEL = "com.example-film.batch-schedule"
TEMPLATE = CODE / "scripts" / "launchd" / f"{LABEL}.plist.template"
ENABLE_BY = ("user",)
BY_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
BATCH_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z")
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
EXIT_OK, EXIT_REFUSED = 0, 2
# CF-0785: a plan day's structured reason, next to its `why` (for a human, unchanged) - one
# `kind` per branch of `plan` that writes a `why`, so the center reads no prefix of the text.
DAY_KINDS = {
    "running": "today, status busy: a batch is open (runlog batch-active) - no second one",
    "done_today": "today, status done: a batch of the factory already started in the current "
                  "quota day (CF-0787: Pacific midnight to Pacific midnight, the Search quota's "
                  "day) and no window of today lies past its reset",
    "quota_day_taken": "status done (a batch that spent quota started in it) or idle (an "
                       "earlier day of this plan takes it): every window of this day that "
                       "needs a batch falls in a quota day that already has its batch "
                       "(CF-0787); `quota_day` names it, notes say each channel's next "
                       "possible window",
    "nobody_plannable": "status idle: no channel can be planned at all (none has a slot and "
                        "a run_plan, or each is out of the schedule) - notes empty",
    "nobody_available": "status idle: channels are plannable, but on this day each one's "
                        "window is gone or it is paused - notes say which; or (CF-0822) the "
                        "one that needs the batch is held by the repeat breaker - then the day "
                        "also carries `breaker` (that channel's record of `breakers`), "
                        "`window_start`/`window_end` (its window) and `next_windows`",
    "fed": "status idle: every channel's feed reaches its batch_feed_days (CF-0922: the "
           "batch threshold, not the horizon min_feed_days) - no batch needed",
    "needs_batch": "status planned: a channel's feed is shorter than batch_feed_days - the "
                   "day's batch; with covers_days and first_empty_slot",
}


class ScheduleError(Exception):
    pass


# --------------------------------------------------------------------------
# the neighbours, loaded by path from this checkout (one instance with the center's)
# --------------------------------------------------------------------------

def collect():
    return _load("factory_state")


def qday():
    """CF-0787: shared/quota_day.py - the YouTube Search quota day."""
    return _load("quota_day")


def _load(name):
    path = CODE / "shared" / f"{name}.py"
    m = sys.modules.get(name)
    if m is not None and Path(getattr(m, "__file__", "") or "").resolve() == path.resolve():
        return m
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def queue():
    return collect().queue()


def _zone(name):
    return queue()._zone(name)


def _msk():
    return _zone(FACTORY_TZ)


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def now_utc(now=None):
    return collect().now_utc(now)


def iso(dt):
    return collect().iso(dt)


def parse_ts(text):
    return collect().parse_ts(text)


def msk_day(dt):
    return dt.astimezone(_msk()).date()


def quota_day(dt):
    """CF-0787: the YouTube Search quota day of `dt` (its date in
    America/Los_Angeles: Pacific midnight, 07:00Z under PDT, 08:00Z under
    PST) - the factory's batch day."""
    return qday().quota_day(dt)


def quota_span(qd):
    """`сутки квоты 17.10 (10:00 МСК 17.10 – 10:00 МСК 18.10)`."""
    s, e = qday().bounds(qd)
    return (f"сутки квоты YouTube {qd:%d.%m} ({s.astimezone(_msk()):%H:%M} МСК {s.astimezone(_msk()):%d.%m}"
            f" – {e.astimezone(_msk()):%H:%M} МСК {e.astimezone(_msk()):%d.%m})")


def fmt(dt):
    """`08.10 02:00 МСК`."""
    return f"{dt.astimezone(_msk()):%d.%m %H:%M} МСК"


def fmt_day(d):
    return f"{d:%d.%m} {WEEKDAYS[d.weekday()]}"


def videos_word(n):
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} ролик"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} ролика"
    return f"{n} роликов"


def dur(seconds):
    m = int(round(seconds / 60))
    return f"{m // 60} ч {m % 60:02d} мин" if m >= 60 else f"{m} мин"


# --------------------------------------------------------------------------
# state: the switch and the launch journal
# --------------------------------------------------------------------------

def state_dir(root=None, environ=None):
    env = os.environ if environ is None else environ
    if env.get(STATE_ENV):
        return Path(env[STATE_ENV]).expanduser()
    return Path(root or CODE) / STATE_DIR


def _write_json_atomic(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def switch_state(root=None, environ=None):
    """`{on, since, by, note, history, line, path}` - off when there is no file."""
    p = state_dir(root, environ) / SWITCH
    if not p.is_file():
        return {"on": False, "history": [], "path": str(p),
                "line": "переключатель ВЫКЛЮЧЕН (не включался): батчи по расписанию не запускаются, "
                        "батч - по «запускай» вручную"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"on": False, "history": [], "path": str(p), "error": str(e),
                "line": f"переключатель не читается ({p.name}: {e}) - считаю ВЫКЛЮЧЕННЫМ"}
    hist = [h for h in doc.get("history") or [] if isinstance(h, dict)]
    on = doc.get("on") is True
    last = hist[-1] if hist else {}
    who = f"{last.get('by')} {last.get('at')}" + (f" - {last['note']}" if last.get("note") else "")
    line = (f"переключатель ВКЛЮЧЁН ({who}): тик запускает батч дня по плану" if on else
            f"переключатель ВЫКЛЮЧЕН ({who}): батчи по расписанию не запускаются, "
            f"батч - по «запускай» вручную")
    return {"on": on, "history": hist, "path": str(p), "by": last.get("by"),
            "since": last.get("at"), "note": last.get("note"), "line": line}


def set_switch(on, by, note=None, root=None, now=None, environ=None):
    """The only writer of the switch. `on=True` takes `by` in ENABLE_BY only."""
    by = str(by or "").strip()
    if not BY_RE.match(by):
        raise ScheduleError(f"--by {by!r}: a short lower-case name (user, operator, ...)")
    if on and by not in ENABLE_BY:
        raise ScheduleError(f"only the user turns the schedule on (--by {' | '.join(ENABLE_BY)}): "
                            f"«включай» is the user's word; {by!r} may only turn it off")
    if on and not (note or "").strip():
        raise ScheduleError("--note is required to turn it on: where and when the user said «включай»")
    st = switch_state(root, environ)
    if st.get("error"):
        raise ScheduleError(f"{st['path']} does not parse ({st['error']}) - fix or remove it by hand")
    row = {"at": iso(now_utc(now)), "by": by, "action": "enable" if on else "disable",
           "note": (note or "").strip() or None, "task": TASK}
    doc = {"on": bool(on), "history": st["history"] + [row]}
    _write_json_atomic(Path(st["path"]), doc)
    return switch_state(root, environ)


def launches(root=None, environ=None):
    p = state_dir(root, environ) / LAUNCHES
    out = []
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


@contextmanager
def _locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / TICK_LOCK, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ScheduleError(f"another tick holds {directory / TICK_LOCK}")
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# --------------------------------------------------------------------------
# the channel's settings and estimates
# --------------------------------------------------------------------------

def _channel_json(channel, root):
    p = Path(root) / "channels" / f"{channel}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def no_pipeline(channel, doc):
    """CF-0562: «конвейера нет - батча не будет (...)» for a channel whose config
    says `status: no_pipeline`, None for a channel with a pipeline;
    ScheduleError for a status that is unknown or a stub that is not one."""
    ids = collect().channel_ids()
    try:
        return ids.no_pipeline_reason(doc, channel)
    except ids.ChannelIdError as e:
        raise ScheduleError(str(e)) from e


def voice_placeholder(channel, doc):
    """CF-0659: the line why a channel with a pipeline may not start yet - its
    voice is a `TODO` placeholder (`channel_ids.voice_placeholder_reason`) -
    or None. The plan does not plan it, `launch_check` fails its `voice` guard."""
    return collect().channel_ids().voice_placeholder_reason(doc, channel)


def window_config(channel, root, doc=None, overlay=None, environ=None):
    """`{window: time, tz, zone, window_hours, min_feed_days, batch_feed_days, enabled,
    source}`;
    ScheduleError when the block is there and wrong. The center's overlay
    (`schedule/channel-settings.json`, CF-0605) goes over the channel's block:
    DEFAULTS < channels/<ch>.json batch_schedule < the overlay. CF-0922:
    `batch_feed_days` set nowhere is the default raised to `min_feed_days`; set
    below `min_feed_days` it is an error (a threshold under the horizon)."""
    doc = _channel_json(channel, root) if doc is None else doc
    if overlay is None:
        overlay = settings_overlay(root, environ)
    block = doc.get("batch_schedule")
    where = f"channels/{channel}.json: batch_schedule"
    if block is None:
        cfg, source = dict(DEFAULTS), "по умолчанию"
    else:
        if not isinstance(block, dict):
            raise ScheduleError(f"{where} must be an object")
        cfg, source = dict(DEFAULTS, **{k: v for k, v in block.items()
                                        if k in DEFAULTS or k == "windows"}), \
            f"channels/{channel}.json batch_schedule"
    mine = (overlay.get("channels") or {}).get(channel) or {}
    mine = {k: v for k, v in mine.items() if k in SETTINGS_KEYS}
    bfd_set = "batch_feed_days" in mine or (isinstance(block, dict)
                                            and "batch_feed_days" in block)
    if mine:
        cfg.update(mine)
        source += f" + центр (schedule/{SETTINGS}: {', '.join(sorted(mine))})"
        where = f"schedule/{SETTINGS}: {channel} / {where}"
    m = HHMM.match(str(cfg["window"]).strip())
    if not m:
        raise ScheduleError(f"{where}.window {cfg['window']!r} is not HH:MM")
    try:
        zone = _zone(cfg["tz"])
    except Exception as e:                                      # noqa: BLE001
        raise ScheduleError(f"{where}.tz {cfg['tz']!r}: {e}") from e
    wh = cfg["window_hours"]
    if not isinstance(wh, (int, float)) or isinstance(wh, bool) or not 0 < wh <= 24:
        raise ScheduleError(f"{where}.window_hours must be a number in (0, 24]")
    mfd = cfg["min_feed_days"]
    if not isinstance(mfd, int) or isinstance(mfd, bool) or mfd < 1:
        raise ScheduleError(f"{where}.min_feed_days must be an integer >= 1")
    bfd = cfg["batch_feed_days"]
    if not isinstance(bfd, int) or isinstance(bfd, bool) or bfd < 1:
        raise ScheduleError(f"{where}.batch_feed_days must be an integer >= 1")
    if not bfd_set:
        bfd = max(bfd, mfd)
    elif bfd < mfd:
        raise ScheduleError(f"{where}.batch_feed_days {bfd} < min_feed_days {mfd}: порог "
                            f"батча не меньше горизонта ленты ({BATCH_FEED_TASK})")
    if not isinstance(cfg["enabled"], bool):
        raise ScheduleError(f"{where}.enabled must be true or false")
    first = time(int(m.group(1)), int(m.group(2)))
    wins = cfg.get("windows")
    if wins is None:                # CF-0830: no `windows` - one window, as before
        windows, multi = [first], False
    else:
        if not isinstance(wins, list) or not 1 <= len(wins) <= MAX_WINDOWS:
            raise ScheduleError(f"{where}.windows must be a list of 1-{MAX_WINDOWS} HH:MM")
        windows = []
        for x in wins:
            mx = HHMM.match(str(x).strip())
            if not mx:
                raise ScheduleError(f"{where}.windows {x!r} is not HH:MM")
            windows.append(time(int(mx.group(1)), int(mx.group(2))))
        windows, multi = sorted(set(windows)), True
        first = windows[0]          # `windows` overrides `window`
    return {"window": first, "tz": str(cfg["tz"]), "zone": zone,
            "window_hours": float(wh), "min_feed_days": mfd, "batch_feed_days": bfd,
            "enabled": cfg["enabled"],
            "source": source, "windows": windows, "multi": multi}


# --------------------------------------------------------------------------
# CF-0605: the center's settings of a channel - an overlay in the state dir
# --------------------------------------------------------------------------
# The center must not change a file in git (channels/*.json is the channel's
# code: a release carries it), so what the user sets in the center lives in
# `schedule/channel-settings.json` (gitignored, next to the switch) and
# `window_config` reads it over the channel's block. One writer:
# `set_channel_settings` - validated, under a lock, a history row per change.

def settings_overlay(root=None, environ=None):
    """`{"channels": {ch: {...}}, "history": [...]}`; empty when there is no file.
    ScheduleError when the file is there and does not parse."""
    p = state_dir(root, environ) / SETTINGS
    if not p.is_file():
        return {"channels": {}, "history": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScheduleError(f"schedule/{SETTINGS} does not parse ({e}) - fix or remove it by hand")
    if not isinstance(doc, dict) or not isinstance(doc.get("channels", {}), dict):
        raise ScheduleError(f"schedule/{SETTINGS} must be an object with \"channels\"")
    return {"channels": doc.get("channels") or {},
            "history": [h for h in doc.get("history") or [] if isinstance(h, dict)]}


def _num(value, what):
    if isinstance(value, bool):
        raise ScheduleError(f"{what}: a number, not {value!r}")
    if isinstance(value, (int, float)):
        x = float(value)
    else:
        try:
            x = float(str(value).strip().replace(",", "."))
        except ValueError:
            raise ScheduleError(f"{what}: {value!r} is not a number") from None
    if x != x or x in (float("inf"), float("-inf")):
        raise ScheduleError(f"{what}: {value!r} is not a number")
    return x


def validate_settings(changes):
    """The center's values, checked and normalised: `{key: value}`; ScheduleError
    on the first wrong one (unknown keys included)."""
    out = {}
    for k, v in (changes or {}).items():
        if k not in SETTINGS_KEYS:
            raise ScheduleError(f"unknown setting {k!r} (only {', '.join(SETTINGS_KEYS)})")
        if k == "enabled":
            if isinstance(v, bool):
                out[k] = v
            elif str(v).strip().lower() in ("1", "true", "yes", "on", "да"):
                out[k] = True
            elif str(v).strip().lower() in ("0", "false", "no", "off", "нет", ""):
                out[k] = False
            else:
                raise ScheduleError(f"участие в расписании: {v!r} - да или нет")
        elif k == "window":
            m = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", str(v).strip())
            if not m:
                raise ScheduleError(f"начало окна {v!r}: время ЧЧ:ММ, 00:00-23:59")
            out[k] = f"{m.group(1)}:{m.group(2)}"
        elif k == "window_hours":
            x = _num(v, "длительность окна")
            if not 0.5 <= x <= 24:
                raise ScheduleError(f"длительность окна {v!r}: от 0.5 до 24 ч")
            if abs(x * 4 - round(x * 4)) > 1e-9:
                raise ScheduleError(f"длительность окна {v!r}: шаг 0.25 ч")
            out[k] = int(x) if x == int(x) else x
        elif k == "windows":                # CF-0830: None/[]/"" - back to the one `window`
            items = v if isinstance(v, (list, tuple)) else \
                [x for x in re.split(r"[,;\s]+", str(v or "").strip()) if x]
            if not items:
                out[k] = None
                continue
            got = set()
            for x in items:
                m = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", str(x).strip())
                if not m:
                    raise ScheduleError(f"окна запуска: {x!r} - время ЧЧ:ММ, 00:00-23:59")
                got.add(f"{m.group(1)}:{m.group(2)}")
            if len(got) > MAX_WINDOWS:
                raise ScheduleError(f"окна запуска: не больше {MAX_WINDOWS}")
            out[k] = sorted(got)
        elif k == "min_feed_days":
            x = _num(v, "горизонт ленты")
            if x != int(x) or not 1 <= x <= MIN_FEED_DAYS_MAX:
                raise ScheduleError(f"горизонт ленты {v!r}: целое число дней от 1 до {MIN_FEED_DAYS_MAX}")
            out[k] = int(x)
        elif k == "batch_feed_days":        # CF-0922: >= min_feed_days - window_config checks
            x = _num(v, "порог батча")
            if x != int(x) or not 1 <= x <= MIN_FEED_DAYS_MAX:
                raise ScheduleError(f"порог батча {v!r}: целое число дней от 1 до {MIN_FEED_DAYS_MAX}")
            out[k] = int(x)
    return out


@contextmanager
def _settings_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / SETTINGS_LOCK, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def set_channel_settings(channel, changes, by, note=None, root=None, now=None, environ=None):
    """The only writer of `schedule/channel-settings.json`. Returns
    `{"changed": {key: [old, new]}, "settings": channel_settings(...)}` - no row
    when nothing changes. The result is checked as a whole (`window_config`)
    before it is written."""
    root = Path(root or CODE).resolve()
    by = str(by or "").strip()
    if not BY_RE.match(by):
        raise ScheduleError(f"--by {by!r}: a short lower-case name (user, operator, ...)")
    if channel not in collect().channels(root):
        raise ScheduleError(f"канала {channel!r} нет в channels/")
    stub = no_pipeline(channel, _channel_json(channel, root))
    if stub:
        raise ScheduleError(f"{channel}: {stub} - настройки расписания ему не к чему "
                            f"(CF-0562; channels/{channel}.json `status`)")
    new = validate_settings(changes)
    d = state_dir(root, environ)
    with _settings_lock(d):
        ov = settings_overlay(root, environ)
        before = channel_settings(channel, root, environ, overlay=ov)
        if before.get("error") and not new:
            raise ScheduleError(before["error"])
        mine = dict(ov["channels"].get(channel) or {})
        changed = {}
        for k, v in new.items():
            old = before.get(k) if not before.get("error") else mine.get(k)
            if old != v:
                changed[k] = [old, v]
            if v is None:
                mine.pop(k, None)
            else:
                mine[k] = v
        if not changed:
            return {"changed": {}, "settings": before}
        try:                    # the overlay keeps only what differs from the channel's file
            base = window_config(channel, root, overlay={"channels": {}, "history": []})
            base = {"enabled": base["enabled"], "window": base["window"].strftime("%H:%M"),
                    "window_hours": base["window_hours"], "min_feed_days": base["min_feed_days"],
                    "batch_feed_days": base["batch_feed_days"],
                    "windows": [t.strftime("%H:%M") for t in base["windows"]]
                    if base["multi"] else None}
        except ScheduleError:
            base = {}
        mine = {k: v for k, v in mine.items()
                if v is not None and (k not in base or base[k] != v)}
        chans = {k: v for k, v in ov["channels"].items() if k != channel}
        if mine:
            chans[channel] = mine
        trial = {"channels": chans, "history": ov["history"]}
        window_config(channel, root, overlay=trial)           # the whole, before it is written
        row = {"at": iso(now_utc(now)), "by": by, "channel": channel, "changes": changed,
               "note": (note or "").strip() or None, "task": SETTINGS_TASK}
        _write_json_atomic(d / SETTINGS, {"channels": chans, "history": ov["history"] + [row]})
    return {"changed": changed, "settings": channel_settings(channel, root, environ)}


def channel_settings(channel, root=None, environ=None, overlay=None):
    """What the center's form shows: the values in force and where they come
    from, or `{"error": ...}`."""
    root = Path(root or CODE).resolve()
    try:
        ov = settings_overlay(root, environ) if overlay is None else overlay
        w = window_config(channel, root, overlay=ov)
    except (ScheduleError, OSError, ValueError) as e:
        return {"error": str(e)}
    mine = (ov["channels"].get(channel) or {})
    return {"enabled": w["enabled"], "window": w["window"].strftime("%H:%M"),
            "window_hours": int(w["window_hours"]) if w["window_hours"] == int(w["window_hours"])
            else w["window_hours"], "min_feed_days": w["min_feed_days"],
            "batch_feed_days": w["batch_feed_days"], "tz": w["tz"],
            "windows": [t.strftime("%H:%M") for t in w["windows"]] if w["multi"] else None,
            "source": w["source"], "overlay": {k: v for k, v in mine.items() if k in SETTINGS_KEYS}}


def settings_history(root=None, environ=None, channel=None):
    try:
        h = settings_overlay(root, environ)["history"]
    except ScheduleError:
        return []
    c = collect()
    return [row for row in h
            if channel is None or c.resolve_channel(row.get("channel"), root or CODE) == channel]


def window_on(day, wcfg, at=None):
    start = datetime.combine(day, at or wcfg["window"], tzinfo=wcfg["zone"])
    return start, start + timedelta(hours=wcfg["window_hours"])


def windows_on(day, wcfg):
    """CF-0830: `[(start, end)]` of every window of the channel on `day`, by start."""
    return [window_on(day, wcfg, t) for t in wcfg.get("windows") or [wcfg["window"]]]


def _runs(root):
    p = Path(root) / "pipeline" / "runs.jsonl"
    out = []
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def estimates(channel, root, runs=None):
    """`{wall_s, wall_n, videos, videos_n}` - the mean of the channel's last runs."""
    c = collect()
    runs = _runs(root) if runs is None else runs
    mine = [r for r in runs if c.resolve_channel(r.get("channel"), root) == channel]
    walls = [float(r["wall_s"]) for r in mine
             if isinstance(r.get("wall_s"), (int, float)) and r["wall_s"] > 0][-RUNS_FOR_ESTIMATE:]
    vids = [int(r["videos"]) for r in mine
            if isinstance(r.get("videos"), int) and not isinstance(r["videos"], bool)
            and r["videos"] > 0][-RUNS_FOR_ESTIMATE:]
    return {"wall_s": sum(walls) / len(walls) if walls else float(DEFAULT_WALL_S),
            "wall_n": len(walls),
            "videos": max(1, int(sum(vids) / len(vids))) if vids else DEFAULT_VIDEOS,
            "videos_n": len(vids)}


def _est_word(n):
    return f"оценка по {n} прогонам" if n else "оценка по умолчанию, прогонов нет"


# --------------------------------------------------------------------------
# what the factory did today
# --------------------------------------------------------------------------

def _batch_start(batch_id):
    m = BATCH_ID_RE.match(str(batch_id or ""))
    if not m:
        return None
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00+00:00")


def open_batches(root, now, open_rows=None):
    """`(fresh, stale)`: `[{dir, batch_id, channel, started, why}]` of the open
    batches (`why`: runlog's line on why it is open, CF-0670; None from a stand-in)."""
    c = collect()
    rows = open_rows if open_rows is not None else c.runlog().open_batches(root, now=now)
    fresh, stale = [], []
    for row in rows:
        d, _last, is_fresh = row
        d = Path(d)
        b = {"dir": c.rel(d, root), "batch_id": d.name, "channel": c._batch_channel(d, root),
             "started": _batch_start(d.name), "why": getattr(row, "why", None)}
        (fresh if is_fresh else stale).append(b)
    return fresh, stale


def _why(b):
    """`: <why>` of an open batch for a refusal line, '' when unknown (CF-0670)."""
    return f": {b['why']}" if b.get("why") else ""


QUOTA_STAGE = "trend-hunter"       # the first stage of a run_plan that spends YouTube Search
RUN_STATE = "run-state.json"       # run_executor.STATE_FILE (CF-0203)
STOPPED = ("failed", "halted")     # a run that ended and spent nothing may not hold the day
LAUNCH_MATCH = timedelta(minutes=30)


def _run_state(batch):
    try:
        st = json.loads((Path(batch) / RUN_STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return st if isinstance(st, dict) else None


def spent_no_quota(batch):
    """Hotfix 2.3.1: True when the batch is not a batch of the day - its
    `run-state.json` says the run stopped (`failed`/`halted`) and its plan's
    `trend-hunter` stage (the first that spends YouTube Search quota) never
    started, and nobody holds its `run-executor.lock`. Everything else counts
    (conservative): no run-state (an old manual batch), a plan with no
    trend-hunter, a running/paused/done run, a held lock."""
    st = _run_state(batch)
    if not st or st.get("status") not in STOPPED or QUOTA_STAGE not in (st.get("order") or []):
        return False
    ss = (st.get("stages") or {}).get(QUOTA_STAGE)
    if not isinstance(ss, dict) or ss.get("started") \
            or ss.get("status") not in ("pending", "skipped"):
        return False
    if (st.get("current") or {}).get("stage") == QUOTA_STAGE:
        return False
    try:
        return not collect().runlog().sibling("executor_lock").lock_held(batch)
    except Exception:                                           # noqa: BLE001
        return False


def _quota_free_batches(root):
    """`{channel/batch_id: (channel, created, pids)}` of today's candidates that
    spent no quota (`spent_no_quota`)."""
    out = {}
    pipe = Path(root) / "pipeline"
    if not pipe.is_dir():
        return out
    for d in pipe.glob("*/*"):
        if d.parent.name in ("backfill", "rebuilds") or not d.is_dir() \
                or not _batch_start(d.name) or not spent_no_quota(d):
            continue
        out[f"{d.parent.name}/{d.name}"] = _launch_key(d)
    return out


def _launch_key(d, channel=None):
    """`(channel, created, pids)` of a batch folder - what `_launch_of_free_batch`
    matches a launch row against (the executor's pid, or the creation time)."""
    st = _run_state(d) or {}
    created = parse_ts(st.get("created")) or _batch_start(d.name)
    pids = {(st.get("executor") or {}).get("pid")}
    try:
        pids.add(collect().runlog().sibling("executor_lock").lock_pid(d))
    except Exception:                                           # noqa: BLE001
        pass
    return (channel or d.parent.name, created, pids - {None})


def _launch_of_free_batch(r, free, root):
    """The launch row started one of the batches that spent no quota: the
    same channel and the executor's pid, or the batch created within
    LAUNCH_MATCH after the row's `at`."""
    ch = collect().resolve_channel(r.get("channel"), root)
    at = parse_ts(r.get("at"))
    for fch, created, pids in free.values():
        if fch != ch:
            continue
        if r.get("pid") in pids:
            return True
        if at and created and timedelta(0) <= created - at <= LAUNCH_MATCH:
            return True
    return False


def _dir_holds_day(d, day, free, day_of=None):
    """The batch folder `d` is a batch of `day` for `started_on`: a channel's
    batch (not `backfill/`, not `rebuilds/`) whose id starts on `day` (by
    `day_of`: the Moscow day, or `quota_day`, CF-0787) and that spent quota
    (not in `free`, `_quota_free_batches`)."""
    d = Path(d)
    if d.parent.name in ("backfill", "rebuilds") or not d.is_dir():
        return False
    t = _batch_start(d.name)
    return bool(t) and (day_of or msk_day)(t) == day and f"{d.parent.name}/{d.name}" not in free


def _batch_of_run(r, root):
    """`<dir>/<batch_id>` of a pipeline/runs.jsonl row: its `batch`
    (`<channel>/<batch_id>`), else its `id` under the folder of its channel -
    the one on disk (a batch made before a rename sits under the former id,
    CF-0250), else the channel's current id; None without an id."""
    b = str(r.get("batch") or "").strip().rstrip("/")
    if b:
        p = Path(b)
        return f"{p.parent.name}/{p.name}" if p.parent.name else None
    bid = str(r.get("id") or "").strip()
    ch = collect().resolve_channel(r.get("channel"), root)
    if not bid or not ch:
        return None
    pipe = Path(root) / "pipeline"
    if pipe.is_dir():
        for d in sorted(pipe.iterdir()):
            if d.name not in ("backfill", "rebuilds") and (d / bid).is_dir() \
                    and collect().resolve_channel(d.name, root) == ch:
                return f"{d.name}/{bid}"
    return f"{ch}/{bid}"


def _batch_of_launch(r, day, root, day_of=None):
    """`<dir>/<batch_id>` of the batch folder of the Moscow `day` the launch row
    started (matched as `_launch_of_free_batch` matches: the executor's pid, or
    the folder created within LAUNCH_MATCH after the row's `at`); None while
    no folder matches (the executor has not made it yet)."""
    pipe = Path(root) / "pipeline"
    if not pipe.is_dir():
        return None
    for d in sorted(pipe.glob("*/*")):
        if d.parent.name in ("backfill", "rebuilds") or not d.is_dir():
            continue
        t = _batch_start(d.name)
        if not t or (day_of or msk_day)(t) != day:
            continue
        key = _launch_key(d, collect().resolve_channel(d.parent.name, root))
        if _launch_of_free_batch(r, {d.name: key}, root):
            return f"{d.parent.name}/{d.name}"
    return None


def started_on(day, root, environ=None, runs=None, records=False, quota=False):
    """What says a batch of the factory started on the Moscow `day`: `[why]`.
    `quota=True` (CF-0787): `day` is a quota day (`quota_day`) - the
    factory's batch day; a launch row is placed by its `at`.
    A batch that stopped before its quota stage is no batch of the day
    (`spent_no_quota`, hotfix 2.3.1) - nor its runs.jsonl row, nor its launch.

    `records=True` (CF-0724): the same evidence as `[{batch, source, line}]`,
    one per line and in the same order - `batch` the batch it names as
    `<dir>/<batch_id>` (None for a launch whose folder is not made yet),
    `source` where it was read (`pipeline/runs.jsonl`, `pipeline/`,
    `schedule/launches.jsonl`), `line` the very line the plain call returns."""
    out = []
    day_of = quota_day if quota else msk_day
    free = _quota_free_batches(root)
    for r in _runs(root) if runs is None else runs:
        t = parse_ts(r.get("started")) or _batch_start(r.get("id"))
        if str(r.get("batch", "")) in free:
            continue
        if t and day_of(t) == day and not str(r.get("batch", "")).startswith("backfill/"):
            ch = collect().resolve_channel(r.get("channel"), root)
            out.append({"batch": _batch_of_run(r, root), "source": "pipeline/runs.jsonl",
                        "line": f"{ch} {r.get('id') or r.get('batch')} (pipeline/runs.jsonl)"})
    pipe = Path(root) / "pipeline"
    if pipe.is_dir():
        for d in sorted(pipe.glob("*/*")):
            if _dir_holds_day(d, day, free, day_of):
                out.append({"batch": f"{d.parent.name}/{d.name}", "source": "pipeline/",
                            "line": f"{d.parent.name} {d.name} (pipeline/)"})
    for r in launches(root, environ):
        if r.get("kind") in NOT_A_BATCH_KINDS:      # CF-0667: the same batch going on;
            continue                                # CF-0668: a rebuild is not a batch of the day;
                                                    # CF-0822: a held repeat started nothing
        if free and _launch_of_free_batch(r, free, root):
            continue
        if quota:
            at = parse_ts(r.get("at"))
            mine = bool(at) and quota_day(at) == day
        else:
            mine = r.get("day") == day.isoformat()
        if mine:
            ch = collect().resolve_channel(r.get("channel"), root)
            who = "тиком" if r.get("by", "tick") == "tick" else f"вручную ({r.get('by')})"
            out.append({"batch": _batch_of_launch(r, day, root, day_of) if records else None,
                        "source": f"schedule/{LAUNCHES}",
                        "line": f"{ch} запущен {who} {r.get('at')} (schedule/{LAUNCHES})"})
    seen, uniq = set(), []
    for w in out:
        k = w["line"].split(" (")[0]
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    return uniq if records else [w["line"] for w in uniq]


def started_batches(recs):
    """`["<dir>/<batch_id>"]` of `started_on(..., records=True)`: each named
    batch once, in order (CF-0724)."""
    out = []
    for x in recs:
        if x.get("batch") and x["batch"] not in out:
            out.append(x["batch"])
    return out


# --------------------------------------------------------------------------
# CF-0830: a next batch in the same quota day, by the Search budget
# --------------------------------------------------------------------------
# A batch costs 42-85 `search.list` calls of the 100 a quota day gives
# (shared/quota_day.py). With `windows` (a channel's windows of one day, the
# center's setting) a quota day that already has a batch takes one more when
# what the day spent + the channel's expected spend fits under the limit less
# the margin, and the quota day has fewer than `max_batches` - never two at
# once. Without `windows` nothing changes: one batch per quota day.
BUDGET_TASK = "CF-0830"
QUOTA_BUDGET = {
    "max_batches": 2,
    "margin": 5,
    "expected_batches": 3,
    "default_searches": 85,
    "_note": "CF-0830 (21.10, the user: two batches a quota day when the Search budget allows). "
             "A channel with `windows` gets a next batch in a quota day that already has one "
             "when spent + expected <= limit - margin (limit: quota_day.SEARCH_CALLS_PER_DAY = "
             "100) and the quota day has fewer than max_batches; expected = the median "
             "(rounded up) of the channel's own `search.list` calls (quota_day.batch_searches) "
             "in its last expected_batches batches with a recorded 01-trend-hunter.json "
             "search_quota, default_searches without one. Values from the prod record of "
             "21.10: Reel's last three 66/47/58 (median 58), Tech's 52/63/85 (63), the largest "
             "of the last month 85-98 - hence the default 85; margin 5 for a call the record "
             "misses.",
}


def budget_config():
    """The budget's values (QUOTA_BUDGET) with the limit of the quota day."""
    return dict(QUOTA_BUDGET, limit=qday().SEARCH_CALLS_PER_DAY)


def expected_searches(channel, root, now=None):
    """`{channel, searches, n, batches: [{batch, searches}], source, line}` - what the
    channel's next batch is expected to spend of the Search quota: the median
    (rounded up) of its last `expected_batches` batches whose trend-hunter wrote
    its `search_quota` (a finished quota stage), `default_searches` without one."""
    c, q = collect(), qday()
    cfg = budget_config()
    root = Path(root)
    now = now_utc(now)
    pipe = root / "pipeline"
    rows, owner = [], {}
    if pipe.is_dir():
        for d in pipe.glob("*/*"):
            if d.parent.name in ("backfill", "rebuilds") or not d.is_dir():
                continue
            t = _batch_start(d.name)
            if not t or t > now:
                continue
            if d.parent.name not in owner:
                owner[d.parent.name] = c.resolve_channel(d.parent.name, root)
            if owner[d.parent.name] != channel or q.searches_from_file(d) is None:
                continue
            n, _src = q.batch_searches(d)
            rows.append((t, f"{d.parent.name}/{d.name}", n))
    last = sorted(rows)[-cfg["expected_batches"]:]
    if not last:
        return {"channel": channel, "searches": cfg["default_searches"], "n": 0, "batches": [],
                "source": "default",
                "line": f"{cfg['default_searches']} (по умолчанию: батчей с записанным "
                        f"расходом поиска нет)"}
    vals = sorted(n for _t, _b, n in last)
    k = len(vals)
    med = vals[k // 2] if k % 2 else (vals[k // 2 - 1] + vals[k // 2]) / 2
    med = int(math.ceil(med))
    return {"channel": channel, "searches": med, "n": k,
            "batches": [{"batch": b, "searches": n} for _t, b, n in last], "source": "median",
            "line": f"{med} (медиана {k} последн. батчей: "
                    + ", ".join(str(n) for _t, _b, n in last) + ")"}


def quota_budget(qd, root, environ=None, runs=None, exp_of=None):
    """What the quota day `qd` already holds of the Search budget: `{quota_day,
    limit, margin, max_batches, batches, spent, spent_recorded, unrecorded:
    [{batch, channel, expected}], left, held: [line]}`. `batches` counts the
    batches `started_on` names for it (quota=True); `spent` is `day_spend` (what
    the executor hands the next trend-hunter) plus, for a counted batch whose
    spend is not on record yet (a launch with no folder, a folder with no 01
    and no run log), its channel's expected spend - so the guess errs high."""
    c, q = collect(), qday()
    root = Path(root)
    cfg = budget_config()
    exp_of = exp_of or (lambda ch: expected_searches(ch, root))
    recs = started_on(qd, root, environ, runs, records=True, quota=True)
    named = started_batches(recs)
    loose = [x for x in recs if not x.get("batch") and x["source"] == f"schedule/{LAUNCHES}"]
    spend = q.day_spend(root, qd)
    unrec = []
    for b in named:
        _n, src = q.batch_searches(root / "pipeline" / b)
        if src is None:
            unrec.append({"batch": b, "channel": c.resolve_channel(b.split("/")[0], root)
                          or b.split("/")[0]})
    for x in loose:
        unrec.append({"batch": None, "channel": x["line"].split()[0]})
    for u in unrec:
        u["expected"] = exp_of(u["channel"])["searches"]
    spent = spend["searches"] + sum(u["expected"] for u in unrec)
    return {"task": BUDGET_TASK, "quota_day": qd.isoformat(), "limit": cfg["limit"],
            "margin": cfg["margin"], "max_batches": cfg["max_batches"],
            "batches": len(named) + len(loose), "spent": spent,
            "spent_recorded": spend["searches"], "unrecorded": unrec,
            "left": cfg["limit"] - spent, "held": [x["line"] for x in recs]}


def _batches_word(n):
    return f"{n} батч" + ("" if n % 10 == 1 and n % 100 != 11 else
                          "а" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "ей")


def admission(channel, base, expected, booked=(), window_start=None, start=None,
              window_end=None):
    """CF-0830: may `channel` take a next batch in the quota day of `base`
    (`quota_budget`) - `booked` the batches this plan already put in it
    (`[{channel, expected, ...}]`). One record: `{task, channel, quota_day,
    window_start, start, nth, batches, max_batches, limit, margin, spent,
    spent_recorded, spent_unrecorded, spent_planned, expected, expected_n,
    expected_line, after, left, admitted, reason, why}` - `reason` one of
    `ok`, `max_batches`, `budget`, `busy` (the window passes while the plan's
    previous batch runs); `why` one Russian line."""
    limit, margin, cap = base["limit"], base["margin"], base["max_batches"]
    count = base["batches"] + len(booked)
    planned = sum(b["expected"] for b in booked)
    spent = base["spent"] + planned
    exp = expected["searches"]
    after = spent + exp
    nth = count + 1
    span = quota_span(date.fromisoformat(base["quota_day"]))
    sums = (f"потрачено {spent}" + (f" (из них по плану {planned})" if planned else "")
            + f" + ожидается {exp} ({channel}: {expected['line']}) = {after}")
    if count >= cap:
        reason = "max_batches"
        why = (f"{nth}-й батч в {span} не допущен: потолок {_batches_word(cap)} в сутки квоты "
               f"уже набран ({count})")
    elif after > limit - margin:
        reason = "budget"
        why = (f"{nth}-й батч в {span} не допущен по бюджету поиска: {sums} > "
               f"{limit - margin} ({limit} − запас {margin}); остаток {limit - spent}")
    elif start is not None and window_end is not None and start >= window_end:
        reason = "busy"
        why = (f"{nth}-й батч в {span} не допущен: окно {fmt(window_start)} проходит, пока идёт "
               f"батч плана (конец ~{fmt(start)})")
    else:
        reason = "ok"
        why = (f"{nth}-й батч в {span} допущен по бюджету поиска: {sums} ≤ {limit - margin} "
               f"({limit} − запас {margin})")
    return {"task": BUDGET_TASK, "channel": channel, "quota_day": base["quota_day"],
            "window_start": iso(window_start) if window_start else None,
            "start": iso(start) if start else None, "nth": nth, "batches": count,
            "max_batches": cap, "limit": limit, "margin": margin, "spent": spent,
            "spent_recorded": base["spent_recorded"],
            "spent_unrecorded": base["spent"] - base["spent_recorded"], "spent_planned": planned,
            "expected": exp, "expected_n": expected["n"], "expected_line": expected["line"],
            "after": after, "left": limit - spent, "admitted": reason == "ok", "reason": reason,
            "why": why}


def budget_status(root, now=None, environ=None, channels=None):
    """`status --json` / the plan's `quota_budget`: the values, the current quota
    day's budget and every channel's expected spend."""
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    exp = {}

    def exp_of(ch):
        if ch not in exp:
            exp[ch] = expected_searches(ch, root, now)
        return exp[ch]

    base = quota_budget(quota_day(now), root, environ, None, exp_of)
    for ch in channels if channels is not None else collect().channels(root):
        exp_of(ch)
    cfg = budget_config()
    line = (f"Бюджет поиска ({BUDGET_TASK}): {quota_span(quota_day(now))} - потрачено "
            f"{base['spent']} из {cfg['limit']} (остаток {base['left']}, запас {cfg['margin']}), "
            f"{_batches_word(base['batches'])} из {cfg['max_batches']}; ожидаемый расход батча: "
            + "; ".join(f"{ch} {e['line']}" for ch, e in exp.items()))
    return {"config": cfg, "today": base, "expected": exp, "line": line}


# --------------------------------------------------------------------------
# stranded batches (CF-0723): ended badly, no runs.jsonl row, not open
# --------------------------------------------------------------------------

STRANDED = ("failed", "halted", "stopped")   # run-state statuses of a run that stopped badly
STRANDED_TASK = "CF-0723"


def _stop_stage(st):
    """The stage the run stopped on: the one in work, the stop's stage, the
    first failed one, else the next one."""
    cur = (st.get("current") or {}).get("stage")
    if cur:
        return cur
    if st.get("status") == "stopped":
        stops = st.get("stops") or []
        if stops and isinstance(stops[-1], dict) and stops[-1].get("stage"):
            return stops[-1]["stage"]
    stages = st.get("stages") or {}
    for sid in st.get("order") or []:
        if (stages.get(sid) or {}).get("status") == "failed":
            return sid
    return st.get("next")


def _stop_reason(st, stage):
    ss = (st.get("stages") or {}).get(stage) or {}
    if ss.get("reason"):
        return ss["reason"]
    if st.get("halt_reason"):
        return st["halt_reason"]
    stops = st.get("stops") or []
    if st.get("status") == "stopped" and stops and isinstance(stops[-1], dict):
        row = stops[-1]
        return f"остановлен {row.get('by') or '?'} {row.get('at') or ''}".strip()
    return None


def _step_log(d, st, stage):
    """`<batch>/logs/...` of the stage's last step (the one in work first)."""
    runs = st.get("runs") or {}
    cur = st.get("current") or {}
    keys = [cur["run"]] if cur.get("run") and cur.get("stage") == stage else []
    keys += [k for k in reversed(list(runs)) if (runs.get(k) or {}).get("stage") == stage]
    for k in keys:
        log = (runs.get(k) or {}).get("log")
        if log:
            return Path(d) / log
    return None


def _launch_log(d, channel, root, environ):
    """The executor's log of the batch's last launch (`schedule/launches.jsonl`):
    a resume/rebuild row naming the folder, or the start matched as
    `_launch_of_free_batch` matches it."""
    d = Path(d).resolve()
    key = {d.name: _launch_key(d, channel)}
    log = None
    for r in launches(root, environ):
        if r.get("kind") == HELD_KIND:              # CF-0822: started nothing
            continue
        if r.get("batch"):
            if Path(str(r["batch"])).resolve() != d:
                continue
        elif not _launch_of_free_batch(r, key, root):
            continue
        log = r.get("log") or log
    return log


def stranded_batches(root, now=None, open_rows=None, runs=None, environ=None):
    """CF-0723: the batches (and rebuilds) whose `run-state.json` says the run
    stopped badly (`failed`/`halted`/`stopped`), that have no row in
    `pipeline/runs.jsonl` and are not open (`runlog.open_batches`, the fresh
    rows - what `runlog batch-active` counts; a stale open one is listed) -
    nothing else shows them. Read only. Rows, by folder:

    `{dir, channel, batch_id, status, created, updated, stage, reason, log,
    halt_reason, stages: [{id, status, reason}], holds_day}` - `stage` is
    where it stopped, `reason` that stage's reason (else the halt's, else the
    stop's), `log` the stage's step log (else the executor's log of its
    launch), root-relative when under the root; `holds_day` is True when the
    batch is what `started_on` counts for today (the quota day of `now`, CF-0787):
    a channel's batch of today that spent quota (`spent_no_quota`, hotfix
    2.3.1), never a rebuild. `open_rows`/`runs` stand in for
    `runlog.open_batches` / `pipeline/runs.jsonl` (tests)."""
    c = collect()
    root = Path(root)
    pipe = root / "pipeline"
    if not pipe.is_dir():
        return []
    now = now_utc(now)
    today = quota_day(now)
    rows = open_rows if open_rows is not None else c.runlog().open_batches(root, now=now)
    is_open = {Path(r[0]).resolve() for r in rows if r[2]}
    recorded = set()
    for r in _runs(root) if runs is None else runs:
        if r.get("batch"):
            recorded.add(str(r["batch"]))
        if r.get("id") and r.get("channel"):
            recorded.add(f"{c.resolve_channel(r.get('channel'), root)}/{r['id']}")
    free = None
    out = []
    for d in sorted(pipe.glob("*/*")):
        if d.parent.name == "backfill" or not d.is_dir() or not _batch_start(d.name):
            continue
        st = _run_state(d)
        if not st or st.get("status") not in STRANDED:
            continue
        if f"{d.parent.name}/{d.name}" in recorded or d.resolve() in is_open:
            continue
        if free is None:
            free = _quota_free_batches(root)
        channel = c._batch_channel(d, root)
        stage = _stop_stage(st)
        log = _step_log(d, st, stage) if stage else None
        if log is None:
            log = _launch_log(d, channel, root, environ)
        stages = st.get("stages") or {}
        out.append({
            "dir": c.rel(d, root), "channel": channel, "batch_id": d.name,
            "status": st.get("status"), "created": st.get("created"),
            "updated": st.get("updated"), "stage": stage,
            "reason": _stop_reason(st, stage), "log": c.rel(log, root) if log else None,
            "halt_reason": st.get("halt_reason"),
            "stages": [{"id": sid, "status": (stages.get(sid) or {}).get("status") or "pending",
                        "reason": (stages.get(sid) or {}).get("reason")}
                       for sid in st.get("order") or list(stages)],
            "holds_day": _dir_holds_day(d, today, free, quota_day)})
    return out


def stranded_line(b):
    return (f"{b['dir']}: {b['status']}" + (f" на {b['stage']}" if b.get("stage") else "")
            + (f" - {b['reason']}" if b.get("reason") else "")
            + ("; держит сегодняшний день" if b["holds_day"] else "; день не держит"))


# --------------------------------------------------------------------------
# CF-0822: the repeat breaker - no blind repeat of the same failure in one quota day
# --------------------------------------------------------------------------
# 20.10: Tech 0831Z failed in pool-maintenance before trend-hunter, spent no
# quota (`spent_no_quota`), so the quota day stayed free and the tick at 11:01Z
# started 1101Z - which failed the same way. The breaker: when a channel's last
# batch of the current quota day stopped (`failed`/`halted`) without spending
# quota, the tick starts no batch of that channel until the quota resets - as
# long as the code is the one the failed batch ran on. New code (another HEAD
# of the root that touches code, or of an agent) lets one repeat through: that
# repeat is then the last batch, and if it fails on the same code the breaker
# holds again. The user's «запускай» (`launch_check` / `manual_launch`) is not
# held. Another channel may still take the day.

BREAKER_TASK = "CF-0822"
HELD_KIND = "repeat_held"            # its launches.jsonl row: the tick did not repeat a failure
# Root paths a batch's own commit-records writes besides runlog.NON_CODE_PATHS: the
# footage-wanted list (analytics/<ch>/footage-wanted.*) - a record, not code.
# Since CF-0895 analytics/ is in NON_CODE_PATHS itself; kept so the breaker does
# not depend on that list.
BREAKER_RECORD_PATHS = ("analytics/",)
NOT_A_BATCH_KINDS = ("resume", "rebuild", HELD_KIND)   # launches.jsonl rows that start no batch


def _failed_code(d, channel, root, environ=None):
    """`(heads, source)`: `{label: commit}` of the code the batch at `d` ran on -
    its run header (`RUN_EVENTS.jsonl` batch-start, moved by recorded drift,
    `runlog._header_heads`), else the `code` of the launch row that started it
    (written by the tick and the button since CF-0822); `({}, None)` unknown."""
    rl = collect().runlog()
    try:
        heads = rl._header_heads(rl.read_events(d))
    except Exception:                                           # noqa: BLE001
        heads = {}
    if heads:
        return heads, "RUN_EVENTS.jsonl (batch-start)"
    key = {d.name: _launch_key(d, channel)}
    for r in reversed(launches(root, environ)):
        if r.get("kind") in NOT_A_BATCH_KINDS or not isinstance(r.get("code"), dict):
            continue
        if r["code"] and _launch_of_free_batch(r, key, root):
            return dict(r["code"]), f"schedule/{LAUNCHES}"
    return {}, None


def code_heads(root):
    """`{label: commit}` of the code a batch of `root` would run on now: the HEAD
    of the root and of every `agents/<name>` that is a git repo (the labels of
    the run header). `{}` without git."""
    rl = collect().runlog()
    out = {}
    for label, d in rl.factory_repos(root):
        try:
            h = rl.repo_head(d)
        except Exception:                                       # noqa: BLE001
            h = None
        if h:
            out[label] = h
    return out


def code_changes(was, root, channel=None, now_heads=None):
    """`[label]` of the repos whose code differs between `was` (the failed
    batch's heads) and now: an agent with any other commit (or one that came or
    went); the root only when the move touches code (`runlog.code_paths_moved`
    with the channel - records, docs, task notes, other channels' configs and
    BREAKER_RECORD_PATHS are not code; a move git cannot read counts)."""
    rl = collect().runlog()
    now_heads = code_heads(root) if now_heads is None else now_heads
    out = []
    repos = dict(rl.factory_repos(root))
    for label in sorted(set(was) | set(now_heads)):
        w, n = was.get(label), now_heads.get(label)
        if w == n:
            continue
        if not w or not n:
            out.append(label)
            continue
        if label == rl.ROOT_REPO:
            try:
                paths = rl.code_paths_moved(repos.get(label, Path(root)), w, n, channel=channel)
            except Exception:                                   # noqa: BLE001
                paths = None
            if paths is None or [p for p in paths if not p.startswith(BREAKER_RECORD_PATHS)]:
                out.append(label)
            continue
        out.append(label)
    return out


def _short_sha(h):
    return str(h or "")[:8] or "?"


def breakers(root, now=None, environ=None, now_heads=None):
    """CF-0822: `{channel: record}` for every channel whose last batch of the
    current quota day (by its id's start) stopped `failed`/`halted` without
    spending quota (`spent_no_quota`). Read only. A record:

    `{channel, batch, status, stage, reason, failure, quota_day, until, held,
    code_source, code_failed, code_now, code_changed, line}` - `batch` is
    `<dir>/<batch_id>`; `stage`/`reason` where and why it stopped (the stage's
    reason names the handler / check), `failure` the two as one line; `until`
    the quota reset (ISO UTC) - the end of the hold; `held` True when the tick
    must not repeat it (the same code, or the failed batch's code unknown);
    False when the code changed since (`code_changed`: the repos that moved) -
    one repeat is allowed; `code_failed`/`code_now` the heads compared
    (`{label: sha}`); `line` one Russian line for the plan, the tick, the
    notification and `status`."""
    c = collect()
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    now_q = quota_day(now)
    pipe = root / "pipeline"
    if not pipe.is_dir():
        return {}
    last = {}
    for d in pipe.glob("*/*"):
        if d.parent.name in ("backfill", "rebuilds") or not d.is_dir():
            continue
        t = _batch_start(d.name)
        if not t or t > now or quota_day(t) != now_q:
            continue
        ch = c.resolve_channel(d.parent.name, root)
        if ch not in last or t > last[ch][0]:
            last[ch] = (t, d)
    until = qday().bounds(now_q)[1]
    out = {}
    for ch, (_t, d) in sorted(last.items()):
        if not spent_no_quota(d):
            continue
        st = _run_state(d) or {}
        stage = _stop_stage(st)
        reason = _stop_reason(st, stage) if stage else None
        failure = (stage or "?") + (f": {reason}" if reason else "")
        was, src = _failed_code(d, ch, root, environ)
        if now_heads is None:
            now_heads = code_heads(root)
        if was and now_heads:
            moved = code_changes(was, root, ch, now_heads)
        else:
            moved = []
        held = not moved
        batch = f"{d.parent.name}/{d.name}"
        if held:
            line = (f"{ch}: повтор того же отказа не запущен - батч {d.name} упал без трат "
                    f"квоты ({st.get('status')} на {failure}), код тот же"
                    + ("" if was else " (код упавшего неизвестен)")
                    + f"; следующий батч {ch} - после сброса квоты {fmt(until)}, по «запускай» "
                      f"или после смены кода ({BREAKER_TASK})")
        else:
            line = (f"{ch}: батч {d.name} упал без трат квоты ({st.get('status')} на "
                    f"{failure}), но код сменился ({', '.join(moved)}) - один повтор "
                    f"разрешён ({BREAKER_TASK})")
        out[ch] = {"channel": ch, "batch": batch, "status": st.get("status"), "stage": stage,
                   "reason": reason, "failure": failure, "quota_day": now_q.isoformat(),
                   "until": iso(until), "held": held, "code_source": src,
                   "code_failed": {k: _short_sha(v) for k, v in sorted(was.items())},
                   "code_now": {k: _short_sha(v) for k, v in sorted((now_heads or {}).items())},
                   "code_changed": moved, "line": line}
    return out


def _held_journaled(root, environ, channel, qd):
    """A `repeat_held` row of `channel` in quota day `qd` is in launches.jsonl.
    The row's channel is frozen on the day it was written and is resolved at the
    door (CF-0835, CF-0197): a row written before a rename still holds the day."""
    for r in launches(root, environ):
        if r.get("kind") == HELD_KIND and r.get("quota_day") == qd \
                and collect().resolve_channel(r.get("channel"), root) == channel:
            return True
    return False


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------

def _channel_state(channel, root, now, horizon_days, fresh, runs, environ=None):
    """Everything the plan needs of one channel, or `{"why_not": ...}`."""
    c, pq = collect(), queue()
    st = {"channel": channel}
    try:
        doc = _channel_json(channel, root)
    except (OSError, ValueError) as e:
        st["why_not"] = f"channels/{channel}.json не читается ({e})"
        return st
    try:
        stub = no_pipeline(channel, doc)
    except ScheduleError as e:
        st["why_not"] = str(e)
        return st
    if stub:
        st["why_not"], st["no_pipeline"] = stub, True
        return st
    try:
        cfg = pq.slot_config(channel, root)
    except Exception as e:                                      # noqa: BLE001
        st["why_not"] = f"publisher.slot сломан ({e})"
        return st
    if cfg is None:
        st["why_not"] = "нет publisher.slot - у канала нет очереди публикаций (CF-0587), планировать нечего"
        return st
    if "run_plan" not in doc:
        st["why_not"] = "нет run_plan - исполнителю (CF-0203) нечего запускать"
        return st
    voice = voice_placeholder(channel, doc)
    if voice:
        st["why_not"] = voice
        return st
    try:
        st["wcfg"] = window_config(channel, root, doc, environ=environ)
    except ScheduleError as e:
        st["why_not"] = str(e)
        return st
    if not st["wcfg"]["enabled"]:
        st["why_not"] = (f"не участвует в расписании ({st['wcfg']['source']}) - батч только "
                         f"вручную")
        return st
    st["cfg"] = cfg
    st["slot_rule"] = (f"{cfg['per_day']}/день в "
                       f"{', '.join(t.strftime('%H:%M') for t in cfg['times'])} {cfg['tz']}")
    st["est"] = estimates(channel, root, runs)
    jpath = Path(root) / "publish" / "uploads.json"
    rows = pq.table(channel, root, now, horizon_days, journal=jpath if jpath.is_file() else None,
                    cfg=cfg)
    earliest = now + cfg["lead"]
    st["free"] = sorted(r["at"] for r in rows if r["taken_by"] is None and r["at"] >= earliest)
    st["taken"] = sorted(r["at"] for r in rows if r["taken_by"] is not None and r["at"] >= now)
    st["horizon_end"] = rows[-1]["at"] if rows else now
    # CF-0925: how far the feed really stands (scheduled videos, before the копилка's
    # virtual fill) - the last taken slot before the first empty one; None: nothing
    st["feed_until"] = None
    for r in rows:
        if r["at"] < now:
            continue
        if r["taken_by"] is None:
            break
        st["feed_until"] = iso(r["at"])
    st["fills"] = []
    # CF-0918: the копилка's reserve (in Studio, taken off its slot) is not the feed's
    # fill - it comes back by the user's word when there is no news. CF-0920: counted by
    # the video, two live ones may share a name (`<slug>~<batch>`)
    q = len(pq.queued(channel, root))
    try:
        acc = c.waiting_acceptance(channel, root, now, PENDING_HORIZON_DAYS)
        pend = len([v for v in acc.get("videos") or [] if v.get("slug") and v.get("mp4_exists")])
    except Exception:                                           # noqa: BLE001
        pend = 0
    st["queue"], st["pending"] = q, pend
    _fill(st, earliest, q + pend, "в _queue/ и ждут приёмки")
    st["open"] = [b for b in fresh if b["channel"] == channel]
    for b in st["open"]:
        end = max((b["started"] or now) + timedelta(seconds=st["est"]["wall_s"]), now)
        _fill(st, end + cfg["lead"], st["est"]["videos"], f"идущий батч {b['batch_id']}")
    return st


def _fill(st, after, n, what):
    """`n` videos take the first free slots at or after `after` (virtually)."""
    took = [at for at in st["free"] if at >= after][:n]
    for at in took:
        st["free"].remove(at)
        st["taken"].append(at)
    st["taken"].sort()
    if n:
        st["fills"].append({"what": what, "n": n, "slots": [iso(a) for a in took]})
    return took


def _first_empty(st, after):
    return next((at for at in st["free"] if at >= after), None)


def _covered_days(st, start, first_empty):
    """Distinct days (the slot's zone) of taken slots in [start, first_empty)."""
    end = first_empty or st["horizon_end"] + timedelta(seconds=1)
    return len({at.astimezone(st["cfg"]["zone"]).date() for at in st["taken"] if start <= at < end})


def plan(root=None, now=None, days=PLAN_DAYS, open_rows=None, environ=None):
    """The factory's batch plan from `now` for `days` Moscow days, as data."""
    c = collect()
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    days = max(1, int(days))
    today = msk_day(now)
    runs = _runs(root)
    fresh, stale = open_batches(root, now, open_rows)
    chans = c.channels(root)
    max_mfd = 1
    states = {}
    for ch in chans:
        try:
            wc = window_config(ch, root, environ=environ)
            max_mfd = max(max_mfd, wc["min_feed_days"], wc["batch_feed_days"])
        except Exception:                                       # noqa: BLE001
            pass
    horizon = days + max_mfd + 3
    for ch in chans:
        try:
            states[ch] = _channel_state(ch, root, now, horizon, fresh, runs, environ)
        except Exception as e:                                  # noqa: BLE001
            states[ch] = {"channel": ch, "why_not": f"{type(e).__name__}: {e}"}
    # CF-0787: the batch day is the YouTube Search quota day. `held(qd)`: what
    # says a batch that spent quota started in it (started_on, quota=True);
    # `planned_q`: the quota days this plan's own earlier days take.
    held_cache = {}

    def held(qd):
        if qd not in held_cache:
            held_cache[qd] = started_on(qd, root, environ, runs, quota=True)
        return held_cache[qd]

    def next_window(st, day):
        """The channel's first window after `day` whose quota day has no batch yet."""
        for k in range(1, NEXT_WINDOW_DAYS + 1):
            for ws, we in windows_on(day + timedelta(days=k), st["wcfg"]):
                if we > now and not held(quota_day(ws)):
                    return ws
        return None

    # CF-0830: the Search budget of a quota day (a channel with `windows` may take
    # a next batch in a quota day that has one); `planned_q[qd]`: this plan's
    # bookings in it; `busy`: the estimated end of the plan's last booking.
    planned_q = {}
    busy = [None]
    exp_cache, base_cache = {}, {}

    def exp_of(ch):
        if ch not in exp_cache:
            exp_cache[ch] = expected_searches(ch, root, now)
        return exp_cache[ch]

    def base_of(qd):
        if qd not in base_cache:
            base_cache[qd] = quota_budget(qd, root, environ, runs, exp_of)
        return base_cache[qd]

    now_q = quota_day(now)
    brk = breakers(root, now, environ)              # CF-0822

    def candidates(day, after=None):
        """`(cands, notes, blocked, repeat, evals)` of `day`: per channel its first
        window that may take the batch. `after` (CF-0830): the end of the day's
        booked batch - then only the channels with `windows`, windows after it."""
        cands, notes, blocked, repeat, evals = [], [], [], [], []
        for ch in chans:
            st = states[ch]
            if st.get("why_not"):
                continue
            w = st["wcfg"]
            if after is not None and not w["multi"]:
                continue
            wins = windows_on(day, w)
            live = [(ws, we) for ws, we in wins
                    if we > now and (after is None or we > after)]
            if not live:
                if after is None:
                    notes.append(f"{ch}: окно {fmt(wins[-1][0])} сегодня прошло")
                continue
            try:
                why_paused = queue().paused(ch, root, max(live[0][0], now))
            except Exception as e:                              # noqa: BLE001
                why_paused = f"пауза не читается ({e})"
            if why_paused:
                if after is None:
                    notes.append(f"{ch}: на паузе - {why_paused}")
                continue
            verdicts, got = [], None
            for ws, we in live:
                fe = _first_empty(st, ws)
                cov = _covered_days(st, ws, fe)
                need = cov < w["batch_feed_days"]          # CF-0922: not the horizon
                rec = {"ch": ch, "ws": ws, "we": we, "fe": fe, "cov": cov, "need": need,
                       "start": max(ws, now, after) if after else max(ws, now), "budget": None}
                if not need:
                    verdicts.append(("fed", rec))
                    continue
                qd = quota_day(ws)
                done = held(qd)
                by_plan = planned_q.get(qd)
                if (done or by_plan) and w["multi"]:            # CF-0830
                    if busy[0] and busy[0] > rec["start"]:
                        rec["start"] = busy[0]
                    ev = admission(ch, base_of(qd), exp_of(ch), by_plan or (), ws, rec["start"],
                                   we)
                    evals.append(ev)
                    rec["budget"] = ev
                    if not ev["admitted"]:
                        verdicts.append(("budget", dict(rec, qd=qd, done=done)))
                        continue
                elif done or by_plan:
                    verdicts.append(("blocked", dict(rec, qd=qd, done=done, by_plan=by_plan)))
                    continue
                b = brk.get(ch)
                if b and b["held"] and qd == now_q:              # CF-0822
                    verdicts.append(("repeat", dict(rec, b=b)))
                    continue
                got = rec
                break
            if got:
                cands.append(got)
                continue
            kind, x = verdicts[0]
            if kind == "fed":
                cands.append(x)
                notes.append(f"{ch}: лента на {x['cov']}{'' if x['fe'] else '+'} дн. вперёд "
                             f"(≥ порога батча {w['batch_feed_days']})"
                             + (f", пусто {fmt(x['fe'])}" if x["fe"] else "") + " - батч не нужен")
                continue
            if after is not None:
                continue            # a later window refused: its record is in `evals`
            nx = next_window(st, day)
            nx_line = fmt(nx) if nx else f"не в ближайшие {NEXT_WINDOW_DAYS} дн."
            if kind == "blocked":
                done, by_plan = x["done"], x["by_plan"]
                holder = (f"там уже был батч: {done[0]}" if done else
                          f"их берёт батч плана {by_plan[0]['channel']} "
                          f"{fmt_day(date.fromisoformat(by_plan[0]['day']))}")
                notes.append(f"{ch}: окно {fmt(x['ws'])} - в сутках квоты, где уже есть батч "
                             f"({quota_span(x['qd'])}; {holder}); следующее окно {ch}: "
                             + nx_line)
                blocked.append({"ch": ch, "ws": x["ws"], "qd": x["qd"], "done": done, "next": nx})
            elif kind == "budget":
                notes.append(f"{ch}: окно {fmt(x['ws'])} - {x['budget']['why']}; следующее окно "
                             f"{ch}: " + nx_line)
                blocked.append({"ch": ch, "ws": x["ws"], "qd": x["qd"], "done": x["done"],
                                "next": nx, "budget": x["budget"]})
            else:
                notes.append(f"{x['b']['line']}; следующее окно {ch}: " + nx_line)
                repeat.append({"ch": ch, "ws": x["ws"], "we": x["we"], "b": x["b"], "next": nx})
        return cands, notes, blocked, repeat, evals

    def by_deficit(cands):
        return sorted((x for x in cands if x["need"]),
                      key=lambda x: (x["fe"] or datetime.max.replace(tzinfo=timezone.utc), x["ch"]))

    def book(x, day, what):
        """Books the batch of `x` - its videos fill the free slots after its end;
        the fields of a planned day (needs_batch)."""
        st = states[x["ch"]]
        est = st["est"]
        start = x["start"]
        end = start + timedelta(seconds=est["wall_s"])
        took = _fill(st, end + st["cfg"]["lead"], est["videos"], what)
        qd = quota_day(x["ws"])
        planned_q.setdefault(qd, []).append({"day": day.isoformat(), "channel": x["ch"],
                                             "expected": exp_of(x["ch"])["searches"],
                                             "end": iso(end)})
        busy[0] = max(busy[0], end) if busy[0] else end
        rec = dict(
            channel=x["ch"], window_start=iso(x["ws"]), window_end=iso(x["we"]),
            quota_day=qd.isoformat(),
            est_end=iso(end), est_wall_s=est["wall_s"], est_wall_n=est["wall_n"],
            est_videos=est["videos"], est_videos_n=est["videos_n"],
            fills=[iso(a) for a in took],
            covers_days=sorted({a.astimezone(st["cfg"]["zone"]).date().isoformat() for a in took}),
            first_empty_slot=iso(x["fe"]) if x["fe"] else None)
        if x.get("budget"):
            rec["budget_admission"] = x["budget"]
        return rec, end

    def need_why(x, needing):
        st = states[x["ch"]]
        others = [f"{y['ch']}: пусто {fmt(y['fe'])}" if y["fe"] else y["ch"] for y in needing[1:]
                  if y["fe"] != x["fe"]]
        tied = [y["ch"] for y in needing[1:] if y["fe"] == x["fe"]]
        return (f"лента короче {st['wcfg']['batch_feed_days']} дн. (на {x['cov']} дн.)"
                + (f": пусто {fmt(x['fe'])}" if x["fe"] else "")
                + (f"; ближайший пустой слот раньше, чем у {', '.join(others)}" if others else "")
                + (f"; пустой слот в то же время у {', '.join(tied)} - день по алфавиту "
                   f"канала" if tied else "")
                + (f"; {x['budget']['why']}" if x.get("budget") else ""))

    multi_any = any(not st.get("why_not") and st["wcfg"]["multi"] for st in states.values())
    out_days = []
    for i in range(days):
        day = today + timedelta(days=i)
        entry = {"day": day.isoformat(), "channel": None, "status": "idle", "notes": []}
        if i == 0 and fresh:
            b = fresh[0]
            entry.update(status="busy", kind="running", channel=b["channel"],
                         why=f"день занят: идёт батч {b['channel']} {b['batch_id']} - второй не "
                             f"запускается (runlog batch-active{_why(b)})")
            out_days.append(entry)
            continue
        cands, notes, blocked, repeat, evals = candidates(day)
        entry["notes"] = notes
        needing = by_deficit(cands)
        if evals:
            entry["budget"] = evals
        if not needing and repeat and (not blocked or (i == 0 and held(now_q))):   # CF-0822
            # (CF-0830: before done_today - with `windows` a held repeat may follow a
            # batch of today; without them a repeat means the quota day of today has no
            # batch, so done_today never meets it, and a blocked window still wins)
            x = repeat[0]
            # kind stays one of the center's (api PlanDay.kind is a closed list):
            # nobody_available, with the breaker's record beside it
            entry.update(status="idle", kind="nobody_available",
                         window_start=iso(x["ws"]), window_end=iso(x["we"]), breaker=x["b"],
                         next_windows={y["ch"]: iso(y["next"]) if y["next"] else None
                                       for y in repeat},
                         why="некого планировать: " + "; ".join(notes))
            out_days.append(entry)
            continue
        if not needing and i == 0 and held(now_q):
            entry.update(status="done", kind="done_today", quota_day=now_q.isoformat(),
                         why=f"сегодня батч уже был: {held(now_q)[0]} - {BATCHES_PER_DAY} батч "
                             f"в сутки квоты на фабрику ({quota_span(now_q)})"
                             + "".join(f"; {e['why']}" for e in evals[:1]))
            out_days.append(entry)
            continue
        if not needing and blocked:
            x = blocked[0]
            entry.update(status="done" if x["done"] else "idle", kind="quota_day_taken",
                         quota_day=x["qd"].isoformat(),
                         next_windows={b["ch"]: iso(b["next"]) if b["next"] else None
                                       for b in blocked},
                         why=f"{quota_span(x['qd'])} уже заняты - "
                             + (f"второй батч только по бюджету поиска ({BUDGET_TASK})"
                                if any(b.get("budget") for b in blocked) else
                                f"{BATCHES_PER_DAY} батч в сутки квоты на фабрику")
                             + ": " + "; ".join(
                                 f"{b['ch']}: окно {fmt(b['ws'])}, следующее "
                                 + (fmt(b["next"]) if b["next"] else "не скоро")
                                 + (f" ({b['budget']['why']})" if b.get("budget") else "")
                                 for b in blocked))
            out_days.append(entry)
            continue
        if not needing:
            if not cands and not notes:
                entry["kind"] = "nobody_plannable"
                entry["why"] = "некого планировать: ни у одного канала нет слота и run_plan"
            elif not cands:
                entry["kind"] = "nobody_available"
                entry["why"] = "некого планировать: " + "; ".join(notes)
            else:
                entry["kind"] = "fed"
                entry["why"] = "батч не нужен: у всех каналов лента не короче порога батча"
            out_days.append(entry)
            continue
        x = needing[0]
        rec, end = book(x, day, f"батч {day.isoformat()}")
        entry.update(status="planned", kind="needs_batch", why=need_why(x, needing), **rec)
        # CF-0830: the next batches of the day - channels with `windows`, after this one
        more = []
        for _k in range(MAX_WINDOWS * max(1, len(chans)) if multi_any else 0):
            c2, _n2, _b2, _r2, e2 = candidates(day, after=end)
            evals.extend(e for e in e2 if e not in evals)
            n2 = by_deficit(c2)
            if not n2:
                break
            y = n2[0]
            rec2, end = book(y, day, f"батч {day.isoformat()} #{len(more) + 2}")
            more.append(dict(rec2, status="planned", kind="needs_batch", why=need_why(y, n2)))
        if more:
            entry["more"] = more
        if evals:
            entry["budget"] = evals
        out_days.append(entry)
    ch_out = {}
    for ch in chans:
        st = states[ch]
        if st.get("why_not"):
            ch_out[ch] = {"plannable": False, "why_not": st["why_not"],
                          "no_pipeline": bool(st.get("no_pipeline")),
                          "settings": channel_settings(ch, root, environ),
                          "breaker": brk.get(ch)}
            continue
        w, est = st["wcfg"], st["est"]
        wtext = (f"{w['window'].strftime('%H:%M')} {w['tz']} + {w['window_hours']:g} ч"
                 if not w["multi"] else
                 f"{', '.join(t.strftime('%H:%M') for t in w['windows'])} {w['tz']} "
                 f"+ {w['window_hours']:g} ч")
        ch_out[ch] = {
            "plannable": True, "slot_rule": st["slot_rule"],
            "window": wtext,
            "windows": [t.strftime("%H:%M") for t in w["windows"]] if w["multi"] else None,
            "expected_searches": exp_of(ch),
            "window_source": w["source"], "min_feed_days": w["min_feed_days"],
            "batch_feed_days": w["batch_feed_days"],
            "est_wall_s": est["wall_s"], "est_wall_n": est["wall_n"],
            "est_videos": est["videos"], "est_videos_n": est["videos_n"],
            "queue": st["queue"], "pending": st["pending"],
            "feed_until": st.get("feed_until"),                 # CF-0925
            "open": [b["batch_id"] for b in st["open"]],
            "settings": channel_settings(ch, root, environ),
            "breaker": brk.get(ch)}
    return {"task": TASK, "now": iso(now), "today": today.isoformat(),
            "quota_day": now_q.isoformat(), "quota_tz": qday().QUOTA_TZ, "root": str(root),
            "per_day": BATCHES_PER_DAY, "switch": switch_state(root, environ),
            "stale_open": [f"{b['channel']} {b['batch_id']}" for b in stale],
            "breakers": brk, "channels": ch_out, "days": out_days,
            "studio_read": studio_read_plan(root, now, environ),            # CF-0926
            "quota_budget": dict(budget_config(), today=base_of(now_q),
                                 windows_channels=sorted(ch for ch, st in states.items()
                                                         if not st.get("why_not")
                                                         and st["wcfg"]["multi"]))}


# --------------------------------------------------------------------------
# lines
# --------------------------------------------------------------------------

def day_line(d):
    day = date.fromisoformat(d["day"])
    head = fmt_day(day)
    if d["status"] == "planned":
        ws, we, end = parse_ts(d["window_start"]), parse_ts(d["window_end"]), parse_ts(d["est_end"])
        return (f"{head}  {d['channel']}: окно {fmt(ws)}–{we.astimezone(_msk()):%H:%M}, "
                f"конец ~{fmt(end)} ({dur(d['est_wall_s'])}, {_est_word(d['est_wall_n'])}), "
                f"~{videos_word(d['est_videos'])} ({_est_word(d['est_videos_n'])}) - {d['why']}")
    return f"{head}  —  {d.get('why') or ''}"


def channel_line(ch, c):
    if c.get("no_pipeline"):
        return f"{ch}: {c['why_not']}"
    if not c["plannable"]:
        return f"{ch}: не планируется - {c['why_not']}"
    return (f"{ch}: слот {c['slot_rule']}; окно {c['window']} ({c['window_source']}); горизонт "
            f"ленты {c['min_feed_days']} дн., порог батча {c['batch_feed_days']} дн.; "
            f"батч ~{dur(c['est_wall_s'])} и ~{videos_word(c['est_videos'])} "
            f"({_est_word(c['est_wall_n'])}); в _queue/ {c['queue']}, ждут приёмки {c['pending']}"
            + (f"; идёт {', '.join(c['open'])}" if c["open"] else ""))


def plan_lines(p):
    out = [f"План батчей ({TASK}) от {fmt(parse_ts(p['now']))}: {p['per_day']} батч в сутки "
           f"квоты YouTube на фабрику (сброс в полночь {p.get('quota_tz', 'America/Los_Angeles')},"
           f" CF-0787), день батча - канал с ближайшим пустым слотом",
           p["switch"]["line"]]
    for d in p["days"]:
        out.append(day_line(d))
        for m in d.get("more") or []:                               # CF-0830
            out.append("      + " + day_line(dict(m, day=d["day"])))
        if not str(d.get("why", "")).startswith("некого планировать: "):
            out.extend(f"        {n}" for n in d.get("notes") or [])
    out.append("Каналы:")
    out.extend(f"  {channel_line(ch, c)}" for ch, c in p["channels"].items())
    if p.get("studio_read"):                                        # CF-0926
        out.append(p["studio_read"]["line"])
    if p["stale_open"]:
        out.append("Залежавшиеся открытые батчи (не держат день): " + ", ".join(p["stale_open"]))
    out.extend(breaker_lines(p.get("breakers")))
    qb = p.get("quota_budget") or {}
    if qb.get("windows_channels"):                                  # CF-0830
        t = qb["today"]
        out.append(f"Бюджет поиска ({BUDGET_TASK}, второй батч в сутки квоты у "
                   f"{', '.join(qb['windows_channels'])}): сутки квоты {t['quota_day']} - "
                   f"потрачено {t['spent']} из {t['limit']} (остаток {t['left']}, запас "
                   f"{t['margin']}), {_batches_word(t['batches'])} из {t['max_batches']}; "
                   "ожидаемый расход: " + "; ".join(
                       f"{ch} {c['expected_searches']['line']}" for ch, c in p["channels"].items()
                       if c.get("expected_searches")))
    return out


def breaker_lines(brk):
    """CF-0822: the breaker's lines for `plan` and `status` ([] when none)."""
    if not brk:
        return []
    return [f"Размыкатель повторов ({BREAKER_TASK}):"] + [f"  {b['line']}" for b in brk.values()]


# --------------------------------------------------------------------------
# the factory's state (CF-0590 `factory_state.SCHEDULE_PROVIDERS`)
# --------------------------------------------------------------------------

def factory_section(p):
    return {"switch": {"on": p["switch"]["on"], "line": p["switch"]["line"]},
            "rows": [day_line(d) + "".join(f"; {n}" for n in d.get("notes") or []
                                           if not str(d.get("why", "")).startswith("некого"))
                     for d in p["days"]],
            "channels": [channel_line(ch, c) for ch, c in p["channels"].items()],
            "stale_open": p["stale_open"],
            "breakers": [b["line"] for b in (p.get("breakers") or {}).values()]}


def channel_section(channel, p):
    c = p["channels"].get(channel)
    if c is None:
        return None
    rows = [day_line(d) for d in p["days"] if d["channel"] == channel]
    return {"switch": {"on": p["switch"]["on"], "line": p["switch"]["line"]},
            "settings": c.get("settings"),
            "settings_history": settings_history(p.get("root"), channel=channel)[-5:],
            "summary": channel_line(channel, c),
            "breaker": c.get("breaker"),
            "rows": rows or [f"в ближайшие {len(p['days'])} дн. батча этого канала в плане нет"]}


# --------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------

def _executor_argv(channel, root, executor=None):
    exe = Path(executor) if executor else CODE / "shared" / "run_executor.py"
    return [sys.executable, str(exe), "run", channel, "--root", str(root)]


def _notify(kind, key, text, channel, root, multiline=False):
    try:
        shared = str(CODE / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus
        return bus.send(kind, key, text, channel=channel, link=bus.link_of(channel, "batch"),
                        root=Path(root), multiline=multiline)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY {kind}: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _label(ch, root=None):
    """CF-0925: the channel as a message names it (Reel, Tech) - notify.channel_label."""
    try:
        shared = str(CODE / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus
        return bus.channel_label(ch, root)
    except Exception:                                            # noqa: BLE001
        return ch


def _started_text(ch, d, p, root, now):
    """CF-0925: «▶️ Reel: батч запущен по расписанию.» - what the feed has, why
    the batch runs (the batch threshold, with the копилка), when it ends
    (shared/notify_human.py). The plan's own `why` stays the center's line."""
    try:
        shared = str(CODE / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify_human
        return notify_human.batch_started_text(ch, d, (p.get("channels") or {}).get(ch) or {},
                                               root=root, now=now)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY batch_started text: {type(e).__name__}: {e}", file=sys.stderr)
        return f"{ch}: батч запущен по расписанию; конец ~{fmt(parse_ts(d['est_end']))} (оценка)"


def spawn_detached(argv, root, day, channel, environ=None):
    """The executor, detached: a session of its own, stdin on DEVNULL, its output
    in `schedule/logs/<day>-<channel>.log`. `(proc, log)`; OSError when it does
    not start. The one start of a batch for the tick, the center's «запустить»
    and «продолжить» (`shared/batch_control.py` `resume`, CF-0667) alike."""
    logs = state_dir(root, environ) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{day}-{channel}.log"
    with open(log, "ab") as fh:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT, cwd=str(root),
                                start_new_session=True, close_fds=True)
    return proc, log


def journal_launch(row, root, environ=None):
    """One row of `schedule/launches.jsonl`."""
    with open(state_dir(root, environ) / LAUNCHES, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _send_reminders(root, now):
    """CF-0606: the user's reminders that have come due (shared/notify.py
    `send_due`) - in every tick, whatever the switch says. Never raises."""
    try:
        shared = str(CODE / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus
        return bus.send_due(root=Path(root), now=now)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY reminders: {type(e).__name__}: {e}", file=sys.stderr)
        return []


def _api_data_auto(root, now, publisher_env=None):
    """CF-0618: the API Data auto-run (agents/publisher/api_data.py `auto`,
    deleting only what is due). The publisher's configuration names the token
    whose revocation mark counts; it is read for the factory's own checkout,
    or from `publisher_env` (tests). Never raises; returns the lines."""
    if publisher_env is None and Path(root).resolve() != CODE.resolve():
        return []
    try:
        pub = str(CODE / "agents" / "publisher")
        if pub not in sys.path:
            sys.path.append(pub)
        import api_data
        import publisher_config
        cfg = publisher_config.load(publisher_env)
        return [f"API Data удалены ({p['reason']}): {len(api_data.describe(p))} поз."
                for p, _ in api_data.auto(cfg, root, now, delete=True)]
    except Exception as e:                                       # noqa: BLE001
        print(f"API DATA auto-run: {type(e).__name__}: {e}", file=sys.stderr)
        return []


# --------------------------------------------------------------------------
# CF-0926: the factory's own settings - the planned Studio read
# --------------------------------------------------------------------------

def _factory_doc(root=None, environ=None):
    p = state_dir(root, environ) / FACTORY_SETTINGS
    if not p.is_file():
        return {"settings": {}, "history": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScheduleError(f"schedule/{FACTORY_SETTINGS} does not parse ({e}) - fix or remove "
                            f"it by hand")
    if not isinstance(doc, dict) or not isinstance(doc.get("settings", {}), dict):
        raise ScheduleError(f"schedule/{FACTORY_SETTINGS} must be an object with \"settings\"")
    return {"settings": doc.get("settings") or {},
            "history": [h for h in doc.get("history") or [] if isinstance(h, dict)]}


def validate_factory_settings(changes):
    """`{studio_read: bool, studio_read_at: "HH:MM"}` checked and normalised;
    ScheduleError on the first wrong one (unknown keys included)."""
    out = {}
    for k, v in (changes or {}).items():
        if k not in FACTORY_KEYS:
            raise ScheduleError(f"unknown factory setting {k!r} (only {', '.join(FACTORY_KEYS)})")
        if k == "studio_read":
            if isinstance(v, bool):
                out[k] = v
            elif str(v).strip().lower() in ("1", "true", "yes", "on", "да", "вкл"):
                out[k] = True
            elif str(v).strip().lower() in ("0", "false", "no", "off", "нет", "выкл"):
                out[k] = False
            else:
                raise ScheduleError(f"плановое чтение Studio: {v!r} - on или off")
        else:
            m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", str(v).strip())
            if not m:
                raise ScheduleError(f"время чтения Studio {v!r}: ЧЧ:ММ, 00:00-23:59 (МСК)")
            out[k] = f"{int(m.group(1)):02d}:{m.group(2)}"
    return out


def factory_settings(root=None, environ=None):
    """`{studio_read, studio_read_at, tz, source, history}`: FACTORY_DEFAULTS under
    `schedule/factory-settings.json`. A file that does not parse - the defaults,
    with `error` (the read is never stopped by a broken settings file)."""
    out = dict(FACTORY_DEFAULTS, tz=FACTORY_TZ, source="по умолчанию", history=[])
    try:
        doc = _factory_doc(root, environ)
        mine = validate_factory_settings({k: v for k, v in doc["settings"].items()
                                          if k in FACTORY_KEYS})
    except ScheduleError as e:
        return dict(out, error=str(e))
    out.update(mine)
    out["history"] = doc["history"]
    if mine:
        out["source"] = f"schedule/{FACTORY_SETTINGS}: {', '.join(sorted(mine))}"
    return out


def set_factory_settings(changes, by, note=None, root=None, now=None, environ=None):
    """The only writer of `schedule/factory-settings.json`: `{"changed": {key:
    [old, new]}, "settings": factory_settings(...)}`; no row when nothing changes."""
    by = str(by or "").strip()
    if not BY_RE.match(by):
        raise ScheduleError(f"--by {by!r}: a short lower-case name (user, operator, ...)")
    new = validate_factory_settings(changes)
    d = state_dir(root, environ)
    with _settings_lock(d):
        doc = _factory_doc(root, environ)
        before = factory_settings(root, environ)
        mine = dict(doc["settings"])
        changed = {k: [before.get(k), v] for k, v in new.items() if before.get(k) != v}
        if not changed:
            return {"changed": {}, "settings": before}
        mine.update(new)
        mine = {k: v for k, v in mine.items() if k in FACTORY_KEYS and FACTORY_DEFAULTS[k] != v}
        row = {"at": iso(now_utc(now)), "by": by, "changes": changed,
               "note": (note or "").strip() or None, "task": FACTORY_TASK}
        _write_json_atomic(d / FACTORY_SETTINGS, {"settings": mine,
                                                  "history": doc["history"] + [row]})
    return {"changed": changed, "settings": factory_settings(root, environ)}


def studio_read_line(fs):
    if fs.get("studio_read"):
        line = f"Чтение Studio: по расписанию, раз в сутки в {fs['studio_read_at']} МСК"
    else:
        line = "Чтение Studio: плановое выключено - только кнопка центра"
    return line + f" ({fs.get('source', 'по умолчанию')}; {FACTORY_TASK})" + (
        f" - {fs['error']}" if fs.get("error") else "")


def _studio_center():
    import importlib.util
    name = "studio_center_for_tick"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, CODE / "agents" / "analyst" / "studio_center.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def studio_read_plan(root=None, now=None, environ=None):
    """What `plan` shows of the planned read: the settings and today's state
    (`schedule/studio-read/scheduled.json`). Never raises."""
    fs = factory_settings(root, environ)
    out = {"enabled": fs["studio_read"], "at": fs["studio_read_at"], "tz": FACTORY_TZ,
           "source": fs["source"], "today": None, "line": studio_read_line(fs)}
    try:
        st = _studio_center().scheduled_state(root)
    except Exception:                                            # noqa: BLE001
        st = {}
    if st.get("day") == msk_day(now_utc(now)).isoformat():
        out["today"] = {k: st.get(k) for k in ("outcome", "run_id", "waiting")}
        out["today"]["attempts"] = len(st.get("attempts") or [])
        word = {"read": "прочитано", "not_due": "не нужно (читали недавно)",
                "failed": "не вышло"}.get(st.get("outcome"))
        if word or st.get("run_id") or st.get("attempts") or st.get("waiting"):
            out["line"] += "; сегодня: " + (word or ("идёт" if st.get("run_id") else
                                                     f"ждёт - {st.get('waiting')}"
                                                     if st.get("waiting") else "впереди")) + \
                f", попыток {out['today']['attempts']}"
    return out


def studio_read_gate(root, now, open_rows=None, environ=None):
    """Why the planned Studio read may not start now, or None: a batch open
    (the fresh rows of `open_batches` - what `runlog batch-active` counts; a
    runlog that cannot answer counts as open), the hour before any running
    channel's window today or tomorrow (STUDIO_COOLDOWN)."""
    try:
        fresh, _stale = open_batches(root, now, open_rows)
    except Exception as e:                                      # noqa: BLE001
        return f"открытые батчи не проверить ({type(e).__name__}) - считаю, что батч открыт"
    if fresh:
        b = fresh[0]
        return f"открыт батч {_label(b['channel'], root)} {b['batch_id']}"
    msk = now.astimezone(_msk()).date()
    for ch in collect().channels(root):
        try:
            if no_pipeline(ch, _channel_json(ch, root)):
                continue
            w = window_config(ch, root, environ=environ)
        except Exception:                                       # noqa: BLE001
            continue
        if not w["enabled"]:
            continue
        for day in (msk, msk + timedelta(days=1)):
            for ws, _we in windows_on(day, w):
                if ws - STUDIO_COOLDOWN <= now < ws:
                    return (f"до окна батча {_label(ch, root)} {fmt(ws)} меньше часа "
                            f"(остывание перед батчем)")
    return None


def _studio_read_scheduled(root, now, open_rows=None, environ=None, force=None):
    """CF-0926: the planned Studio read's step of this tick (studio_center
    `scheduled_read`) with the guard of `studio_read_gate`. Only for the
    factory's own checkout unless `force` (tests). Never raises; the line."""
    if not force and Path(root).resolve() != CODE.resolve():
        return ""
    try:
        fs = factory_settings(root, environ)
        mod = _studio_center()
        st = mod.scheduled_state(root, environ)
        blocked = None
        if fs["studio_read"] and not st.get("run_id"):
            blocked = studio_read_gate(root, now, open_rows, environ)
        res = mod.scheduled_read(root=root, now=iso(now), at=fs["studio_read_at"],
                                 enabled=fs["studio_read"], blocked=blocked, environ=environ)
        quiet = not (res["launched"] or res["collected"] or res["notified"])
        return "" if quiet else res["line"]
    except Exception as e:                                       # noqa: BLE001
        print(f"STUDIO scheduled read: {type(e).__name__}: {e}", file=sys.stderr)
        return f"чтение Studio: шаг не сделан ({type(e).__name__})"


def _studio_insurance(root, now, force=None):
    """CF-0735: the Studio safety net (agents/analyst/studio_center.py
    `studio_insurance_notify`) - one Russian line «Studio не читали N часов —
    откройте центр» at most once a day, from every tick, whatever the switch
    says. Only for the factory's own checkout unless `force` (tests). Never
    raises; returns the line for the tick's own, or ""."""
    if not force and Path(root).resolve() != CODE.resolve():
        return ""
    try:
        mod = _studio_center()
        res = mod.studio_insurance_notify(root=root, now=iso(now))
        return "страховка Studio: позвали пользователя" if res.get("sent") else ""
    except Exception as e:                                       # noqa: BLE001
        print(f"STUDIO insurance: {type(e).__name__}: {e}", file=sys.stderr)
        return ""


def _acceptance_flush(root, now, open_rows=None):
    """CF-0675: the verdicts the user gave while a batch was going wait in
    `publish/acceptance-pending.jsonl`; once no batch is going (the batch-done is
    in, no live executor holds a lock) they go into the record as one commit -
    `acceptance.commit_pending`. Before the day's launch, so the commit lands
    ahead of the next batch. No queue file - nothing loaded, nothing run. Never
    raises; returns the line for the tick ('' when nothing happened)."""
    acc = collect().acceptance()
    queue_file = Path(root) / acc.ACCEPTANCE_LOG_REL.parent / acc.PENDING_NAME
    try:
        if not queue_file.is_file() or queue_file.stat().st_size == 0:
            return ""
        rows = open_rows if open_rows is not None else collect().runlog().open_batches(
            root, now=now)
        res = acc.commit_pending(root, by="расписание", open_rows=rows)
    except Exception as e:                                       # noqa: BLE001
        print(f"ACCEPTANCE queue: {type(e).__name__}: {e}", file=sys.stderr)
        return f"приёмка: очередь не закоммичена ({type(e).__name__})"
    if res["committed"]:
        line = (f"приёмка: {len(res['applied'])} из очереди закоммичено "
                f"{res['commit'][:7]}")
        return line + (f", осталось {res['left']}" if res["left"] else "")
    return ""


def tick(root=None, now=None, dry_run=False, executor=None, open_rows=None, environ=None,
         publisher_env=None, studio_insurance=None, studio_read=None):
    """`(code, line, launched)`; `launched` is the launch row or None.

    CF-0606: first the user's reminders that have come due are sent - the
    switch does not gate them (an off schedule starts no batch, it does not
    silence a reminder); a dry run sends none. CF-0618: then the API Data
    auto-run (`_api_data_auto`), on the same terms. CF-0675: then the
    acceptance queue, once no batch is going (`_acceptance_flush`). CF-0735:
    then the Studio safety net (`_studio_insurance`; `studio_insurance=True`
    runs it on a root that is not the factory's checkout - tests). CF-0926:
    before the safety net, the planned Studio read (`_studio_read_scheduled`;
    `studio_read=True` - the same for tests), whatever the batch switch says."""
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    sent = [] if dry_run else _send_reminders(root, now)
    purged = [] if dry_run else _api_data_auto(root, now, publisher_env)
    accepted = "" if dry_run else _acceptance_flush(root, now, open_rows)
    planned = "" if dry_run else _studio_read_scheduled(root, now, open_rows, environ,
                                                        studio_read)
    studio = "" if dry_run else _studio_insurance(root, now, studio_insurance)
    code, line, row = _tick(root, now, dry_run, executor, open_rows, environ)
    if accepted:
        line += "; " + accepted
    if planned:
        line += "; " + planned
    if studio:
        line += "; " + studio
    if purged:
        line += "; " + "; ".join(purged)
    if sent:
        ok = [g for g in sent if g.get("status") in ("sent", "duplicate")]
        gone = [g for g in sent if g.get("status") == "exhausted"]      # CF-0617
        line += f"; напоминания: отправлено {len(ok)}" + (
            f", не ушло {len(sent) - len(ok)}" if len(ok) < len(sent) else "") + (
            f" (исчерпано попыток: {len(gone)})" if gone else "")
    return code, line, row


def _launch_code(root):
    """CF-0822: the heads a launch starts on (`code_heads`), for the breaker
    when the batch fails before its run header; `{}` when unreadable."""
    try:
        return code_heads(root)
    except Exception:                                           # noqa: BLE001
        return {}


# --------------------------------------------------------------------------
# CF-0899: `claude` logged in - before a batch opens, and to resume a halted one
# --------------------------------------------------------------------------

def claude_binary(environ=None):
    """The `claude` the executor would run: `RUN_EXECUTOR_CLAUDE`, else the one
    on PATH, else ~/.local/bin/claude; None when there is none."""
    env = os.environ if environ is None else environ
    if env.get(CLAUDE_ENV):
        return env[CLAUDE_ENV]
    import shutil
    found = shutil.which("claude")
    if found:
        return found
    return str(CLAUDE_FALLBACK) if CLAUDE_FALLBACK.is_file() else None


def _last_json(text):
    for line in reversed((text or "").strip().splitlines()):
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    try:
        doc = json.loads(text)
        return doc if isinstance(doc, dict) else None
    except ValueError:
        return None


def login_state(root, environ=None):
    """`{ok, line, checked}`: is `claude` logged in - `claude auth status --json`,
    which spends no tokens. `ok` True / False / None (unknown: no binary, a
    timeout, an answer that says neither - never holds a batch: the executor's
    own NOT_LOGGED_IN halt stays the last word). Asked only for the factory's
    own checkout, or when `RUN_EXECUTOR_CLAUDE` names the binary (tests: a
    stand-in) - a tick on another root never calls the real CLI."""
    env = os.environ if environ is None else environ
    if Path(root).resolve() != CODE.resolve() and not env.get(CLAUDE_ENV):
        return {"ok": None, "checked": False, "line": "вход в claude не проверялся (не корень фабрики)"}
    exe = claude_binary(environ)
    if not exe:
        return {"ok": None, "checked": False, "line": "claude не найден - вход не проверен"}
    try:
        cp = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=LOGIN_PROBE_TIMEOUT_S,
                            env=dict(env) if environ is not None else None)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": None, "checked": True,
                "line": f"`claude auth status` не ответил ({type(e).__name__}) - вход не проверен"}
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    doc = _last_json(cp.stdout or "")
    flag = None
    if isinstance(doc, dict):
        for k in ("loggedIn", "logged_in"):
            if isinstance(doc.get(k), bool):
                flag = doc[k]
                break
    if flag is None and NOT_LOGGED_IN_RE.search(out):
        flag = False
    if flag is True:
        return {"ok": True, "checked": True, "line": "claude залогинен"}
    if flag is False:
        return {"ok": False, "checked": True, "line": f"claude не залогинен - {LOGIN_HINT}"}
    return {"ok": None, "checked": True,
            "line": f"`claude auth status` не сказал, залогинен ли (код {cp.returncode}) - "
                    f"вход не проверен"}


def _login_notify(root, now, text, channel=None):
    """The one `needs_human` of a day about logging in (CF-0899): the key is the
    Moscow day, so every tick after the first finds it sent."""
    return _notify("needs_human", f"claude_login:{msk_day(now).isoformat()}",
                   f"{text}. {LOGIN_HINT} - после входа тик расписания продолжит сам "
                   f"({LOGIN_TASK})", channel, root)


def login_halted(root, now, open_rows=None):
    """The open batches (fresh or stale) whose run-state.json says the executor
    halted on NOT_LOGGED_IN: `[{dir (Path), channel, batch_id, stage, reason}]`."""
    c = collect()
    rows = open_rows if open_rows is not None else c.runlog().open_batches(root, now=now)
    out = []
    for row in rows:
        d = Path(row[0])
        st = _run_state(d)
        if not st or st.get("status") != "halted":
            continue
        reason = str(st.get("halt_reason") or "")
        if not reason.startswith(NOT_LOGGED_IN):
            continue
        halts = [h for h in st.get("login_halts") or [] if isinstance(h, dict)]
        stage = (halts[-1].get("stage") if halts else None) or (st.get("current") or {}).get("stage")
        # a batch written before a channel's rename carries the old id: resolved at the door
        channel = c.resolve_channel(st.get("channel"), root) if st.get("channel") \
            else c._batch_channel(d, root)
        out.append({"dir": d, "channel": channel,
                    "batch_id": d.name, "stage": stage, "reason": reason})
    return out


def _last_auto_resume(root, environ, batch):
    """When the tick last resumed this batch on its own (CF-0899), or None."""
    last = None
    for r in launches(root, environ):
        if r.get("kind") == "resume" and r.get("by") == LOGIN_BY and \
                Path(str(r.get("batch"))).resolve() == Path(batch).resolve():
            t = parse_ts(r.get("at"))
            if t and (last is None or t > last):
                last = t
    return last


def _resume_login_halted(root, now, dry_run, executor, open_rows, environ):
    """CF-0899: a batch halted on NOT_LOGGED_IN is the tick's to resume once the
    CLI is logged in again - no person. `(code, line, row)`, or None when no
    open batch stands on it. Not logged in: one `needs_human` a day, nothing
    else. Logged in (or unknown - the executor is the real check): resumed
    through `batch_control.resume`, at most once per LOGIN_RESUME_BACKOFF."""
    halted = login_halted(root, now, open_rows)
    if not halted:
        return None
    b = halted[0]
    name = f"{b['channel']} {b['batch_id']}"
    where = f"батч {name} стоит на {b['stage'] or '?'}: {NOT_LOGGED_IN}"
    if dry_run:
        return EXIT_OK, f"TICK no (dry run): {where} - тик продолжит его после входа в claude", None
    login = login_state(root, environ)
    if login["ok"] is False:
        _login_notify(root, now, where, b["channel"])
        return EXIT_OK, f"TICK no: {where}; {login['line']} - продолжу сам после входа", None
    last = _last_auto_resume(root, environ, b["dir"])
    if last and now - last < LOGIN_RESUME_BACKOFF:
        return EXIT_OK, (f"TICK no: {where}; тик продолжал его в {fmt(last)}, следующая попытка "
                         f"после {fmt(last + LOGIN_RESUME_BACKOFF)} ({login['line']})"), None
    try:
        shared = str(CODE / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import batch_control
        res = batch_control.resume(b["dir"], LOGIN_BY, confirmed=True, root=root, now=now,
                                   environ=environ, executor=executor, open_rows=open_rows,
                                   auto=f"{NOT_LOGGED_IN} на {b['stage'] or '?'}, {login['line']}")
    except Exception as e:                                       # noqa: BLE001
        return EXIT_REFUSED, f"TICK error: {where}; продолжить не вышло ({type(e).__name__}: {e})", None
    if res.get("resumed"):
        return EXIT_OK, f"TICK resumed {name} ({where}; {login['line']}): {res.get('reason')}", res.get("row")
    _notify("needs_human", f"claude_login_resume:{b['batch_id']}:{msk_day(now).isoformat()}",
            f"{where}; тик не смог продолжить: {res.get('reason')} ({LOGIN_TASK})", b["channel"], root)
    return EXIT_OK, f"TICK no: {where}; не продолжен: {res.get('reason')}", None


def _hold_repeat(d, p, root, now, dry_run, environ):
    """CF-0822: the day is held by the breaker. Once the held channel's window has
    come (the tick would have started it), one `repeat_held` row of
    launches.jsonl and one `run_halted` notification per channel and quota day;
    returns that row when written now, else None. Under the tick's lock."""
    b = d["breaker"]
    ch, qd = b["channel"], b["quota_day"]
    ws = parse_ts(d.get("window_start"))
    if dry_run or (ws and now < ws) or _held_journaled(root, environ, ch, qd):
        return None
    row = {"at": iso(now), "day": p["today"], "quota_day": qd, "channel": ch, "pid": None,
           "by": "tick", "kind": HELD_KIND, "failed_batch": b["batch"],
           "failure": b["failure"], "until": b["until"], "why": b["line"],
           "task": BREAKER_TASK}
    journal_launch(row, root, environ)
    _notify("run_halted", f"{HELD_KIND}:{ch}:{qd}", b["line"], ch, root)
    return row


def _tick(root, now, dry_run, executor, open_rows, environ):
    sw = switch_state(root, environ)
    if not sw["on"]:
        return EXIT_OK, f"TICK no: {sw['line']}", None
    resumed = _resume_login_halted(root, now, dry_run, executor, open_rows, environ)   # CF-0899
    if resumed is not None:
        return resumed
    try:
        with _locked(state_dir(root, environ)):
            p = plan(root, now, 1, open_rows, environ)
            d = p["days"][0]
            if d.get("breaker"):                                 # CF-0822
                _hold_repeat(d, p, root, now, dry_run, environ)
                return EXIT_OK, f"TICK no: {d.get('why')}", None
            if d["status"] != "planned":
                return EXIT_OK, f"TICK no: {d.get('why')}", None
            ch = d["channel"]
            ws, we = parse_ts(d["window_start"]), parse_ts(d["window_end"])
            if now < ws:
                return EXIT_OK, (f"TICK no: окно {ch} {fmt(ws)}–{we.astimezone(_msk()):%H:%M} "
                                 f"ещё не наступило ({d['why']})"), None
            why_paused = queue().paused(ch, root, now)
            if why_paused:
                return EXIT_OK, f"TICK no: {ch} на паузе - {why_paused}", None
            argv = _executor_argv(ch, root, executor)
            if dry_run:
                return EXIT_OK, f"TICK would start (dry run): {' '.join(argv)} - {d['why']}", None
            login = login_state(root, environ)                   # CF-0899: before anything opens
            if login["ok"] is False:
                _login_notify(root, now, f"батч {ch} не открыт: claude не залогинен", ch)
                return EXIT_OK, (f"TICK no: {login['line']} - батч {ch} не открыт, день не "
                                 f"занят: следующий тик после входа запустит его"), None
            try:
                proc, log = spawn_detached(argv, root, p["today"], ch, environ)
            except OSError as e:
                return EXIT_REFUSED, f"TICK error: cannot start {' '.join(argv)} ({e})", None
            row = {"at": iso(now), "day": p["today"], "channel": ch, "pid": proc.pid,
                   "argv": argv, "log": str(log), "why": d["why"], "by": "tick", "task": TASK,
                   "code": _launch_code(root)}
            nkey = f"batch_started:{p['today']}"
            if d.get("budget_admission"):                       # CF-0830: a next batch of the day
                row["budget"] = d["budget_admission"]
                nkey += f":{ch}:{ws.astimezone(_msk()):%H%M}"
            journal_launch(row, root, environ)
    except ScheduleError as e:
        return EXIT_OK, f"TICK no: {e}", None
    _notify("batch_started", nkey, _started_text(ch, d, p, root, now), ch, root, multiline=True)
    return EXIT_OK, f"TICK started {ch} pid {proc.pid}, log {log} - {d['why']}", row


# --------------------------------------------------------------------------
# CF-0605: «запустить батч сейчас» - the user's «запускай» as a button
# --------------------------------------------------------------------------
# The same guards as the tick's but the window and the switch: an open batch,
# a batch already today (one a day for the factory - a manual start is refused
# too, with the reason), the channel's pause. Not the plan either: the user
# picks the channel; a channel out of the schedule may still be started by hand.

def launch_check(channel, root=None, now=None, open_rows=None, environ=None, executor=None):
    """What the button would do, as data: `{channel, ok, why, guards: [{name, ok,
    line}], argv, today, skipped: [line]}` - read only. The `open` and `today`
    guards also carry `batches` (CF-0724): `["<dir>/<batch_id>"]` of the batches
    the guard is about - the fresh open ones; those `started_on` names for today
    (a launch whose folder is not made yet names none) - `[]` when none."""
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    today = msk_day(now)
    now_q = quota_day(now)
    out = {"channel": channel, "today": today.isoformat(), "quota_day": now_q.isoformat(),
           "guards": [], "argv": None,
           "skipped": ["окно запуска - ручной запуск его не ждёт",
                       "переключатель расписания - ручной запуск от него не зависит",
                       "участие канала в расписании - ручной запуск его не требует"]}
    g = out["guards"]

    def guard(name, ok, line):
        g.append({"name": name, "ok": bool(ok), "line": line})

    chans = collect().channels(root)
    if channel not in chans:
        guard("channel", False, f"канала {channel!r} нет в channels/")
    else:
        try:
            doc = _channel_json(channel, root)
            stub = no_pipeline(channel, doc)
            if stub:
                guard("run_plan", False, f"у канала нет run_plan - {stub}")
            else:
                guard("run_plan", "run_plan" in doc,
                      "run_plan есть - исполнителю есть что запускать" if "run_plan" in doc else
                      f"нет run_plan в channels/{channel}.json - исполнителю (CF-0203) нечего "
                      f"запускать")
                voice = voice_placeholder(channel, doc)
                guard("voice", not voice, voice or "голос канала выбран")
        except (OSError, ValueError) as e:
            guard("channel", False, f"channels/{channel}.json не читается ({e})")
        except ScheduleError as e:
            guard("channel", False, str(e))
        fresh, _stale = open_batches(root, now, open_rows)
        guard("open", not fresh,
              "открытого батча нет" if not fresh else
              f"идёт батч {fresh[0]['channel']} {fresh[0]['batch_id']} - второй не запускается "
              f"(runlog batch-active{_why(fresh[0])})")
        g[-1]["batches"] = [f"{Path(b['dir']).parent.name}/{b['batch_id']}" for b in fresh]
        recs = started_on(now_q, root, environ, records=True, quota=True)
        done = [x["line"] for x in recs]
        reset = qday().bounds(now_q)[1]
        bud = None
        if done:                    # CF-0830: a channel with `windows` - by the Search budget
            try:
                multi = window_config(channel, root, environ=environ)["multi"]
            except (ScheduleError, OSError, ValueError):
                multi = False
            if multi:
                bud = admission(channel, quota_budget(now_q, root, environ),
                                expected_searches(channel, root, now), (), now, now, None)
        out["budget"] = bud
        if bud and bud["admitted"]:
            guard("today", True, f"сегодня батч уже был ({done[0]}), но {bud['why']}")
        else:
            guard("today", not done,
                  "сегодня батча ещё не было" if not done else
                  f"сегодня батч уже был: {done[0]} - {BATCHES_PER_DAY} батч в сутки квоты "
                  f"YouTube Search на фабрику ({quota_span(now_q)}), ручной запуск тоже ждёт "
                  f"сброса квоты {fmt(reset)}" + (f"; {bud['why']}" if bud else ""))
        g[-1]["batches"] = started_batches(recs)
        try:
            why_paused = queue().paused(channel, root, now)
        except Exception as e:                                  # noqa: BLE001
            why_paused = f"пауза не читается ({e})"
        guard("pause", not why_paused,
              "канал не на паузе" if not why_paused else f"канал на паузе - {why_paused}")
        out["argv"] = _executor_argv(channel, root, executor)
        try:
            b = breakers(root, now, environ).get(channel)
        except Exception:                                       # noqa: BLE001
            b = None
        out["breaker"] = b
        if b and b["held"]:
            out["skipped"].append(f"размыкатель повторов ({BREAKER_TASK}) - ручной запуск его "
                                  f"не ждёт: {b['line']}")
    bad = [x for x in g if not x["ok"]]
    out["ok"] = not bad
    out["why"] = bad[0]["line"] if bad else "все защиты пройдены"
    return out


def manual_launch(channel, root=None, now=None, by=MANUAL_BY, confirmed=False, executor=None,
                  open_rows=None, environ=None):
    """`(ok, line, row)`. Starts nothing unless `confirmed` and every guard of
    `launch_check` holds - checked again under the tick's lock, so a tick and
    the button never start two batches."""
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    if not confirmed:
        return False, "не подтверждено: батч не запущен (нужна галочка подтверждения)", None
    try:
        with _locked(state_dir(root, environ)):
            chk = launch_check(channel, root, now, open_rows, environ, executor)
            if not chk["ok"]:
                return False, f"отказ: {chk['why']}", None
            argv = chk["argv"]
            try:
                proc, log = spawn_detached(argv, root, chk["today"], channel, environ)
            except OSError as e:
                return False, f"не стартовал {' '.join(argv)} ({e})", None
            row = {"at": iso(now), "day": chk["today"], "channel": channel, "pid": proc.pid,
                   "argv": argv, "log": str(log), "why": "ручной запуск («запускай» кнопкой)",
                   "by": by, "kind": "manual", "task": SETTINGS_TASK,
                   "code": _launch_code(root)}
            nkey = f"batch_started:{chk['today']}"
            if chk.get("budget") and chk["budget"]["admitted"]:     # CF-0830
                row["budget"] = chk["budget"]
                nkey += f":{channel}:{now.astimezone(_msk()):%H%M}"
            journal_launch(row, root, environ)
    except ScheduleError as e:
        return False, f"отказ: {e}", None
    _notify("batch_started", nkey, f"▶️ {_label(channel, root)}: батч запущен вручную ({by})",
            channel, root)
    return True, f"запущен {channel}: pid {proc.pid}, журнал {log}", row


# --------------------------------------------------------------------------
# the timer (printed, never installed)
# --------------------------------------------------------------------------

def plist_text(root=None, interval=INTERVAL_S, python=None, path_env=None):
    root = Path(root or CODE).resolve()
    text = TEMPLATE.read_text(encoding="utf-8")
    subst = {"LABEL": LABEL, "PYTHON": python or sys.executable,
             "SCRIPT": str(CODE / "shared" / "batch_schedule.py"), "ROOT": str(root),
             "INTERVAL": str(int(interval)), "LOG": str(state_dir(root, {}) / TICK_LOG),
             "PATH": path_env if path_env is not None else os.environ.get("PATH", "/usr/bin:/bin")}
    for k, v in subst.items():
        text = text.replace("{{" + k + "}}", _xml(v))
    return text


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def timer_state(home=None):
    """CF-0607: is the tick's timer installed - its plist in
    ~/Library/LaunchAgents (the step `install_commands` prints). Read only:
    a file check, no launchctl. The deletion of API Data by its term
    (CF-0618) runs in the tick, so the API upload's switch warns without it."""
    plist = Path(home or Path.home()).expanduser() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if plist.is_file():
        return {"installed": True, "path": str(plist),
                "line": f"таймер тика установлен ({plist})"}
    return {"installed": False, "path": str(plist),
            "line": f"таймер тика НЕ установлен (нет {plist}): батчи по расписанию и удаление "
                    f"API Data по сроку (CF-0618) держатся на ручных запусках - "
                    f"`python3 shared/batch_schedule.py install-timer --print` "
                    f"(docs/batch-schedule.md)"}


def install_commands():
    dest = f"~/Library/LaunchAgents/{LABEL}.plist"
    return [f"# {TASK}: the timer of `batch_schedule.py tick` - printed, NOT installed.",
            "# Install only on the user's «включай» (docs/batch-schedule.md), after:",
            "#   python3 shared/batch_schedule.py enable --by user --note \"...\"",
            f"#   python3 shared/batch_schedule.py install-timer --print > {dest}",
            f"#   launchctl bootstrap gui/$(id -u) {dest}",
            "# Remove:",
            f"#   launchctl bootout gui/$(id -u)/{LABEL} && rm {dest}"]


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------

def main(argv=None, out=sys.stdout, err=sys.stderr):
    ap = argparse.ArgumentParser(prog="batch_schedule.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "status", "enable", "disable", "tick", "install-timer", "settings",
                 "stranded"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None, help="the factory tree (default: this checkout)")
        if name in ("plan", "tick", "stranded", "status"):
            p.add_argument("--now", default=None, help="ISO time with a zone")
        if name in ("stranded", "status"):
            p.add_argument("--json", action="store_true")
        if name == "plan":
            p.add_argument("--days", type=int, default=PLAN_DAYS)
            p.add_argument("--json", action="store_true")
        if name in ("enable", "disable"):
            p.add_argument("--by", required=True)
            p.add_argument("--note", default=None)
        if name == "tick":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--executor", default=None, help=argparse.SUPPRESS)   # tests: a stand-in
        if name == "settings":
            p.add_argument("channel", nargs="?")
            p.add_argument("--by", default=None)
            p.add_argument("--note", default=None)
            p.add_argument("--enabled", default=None, help="yes | no: takes part in the schedule")
            p.add_argument("--window", default=None, help="the window's start, HH:MM")
            p.add_argument("--window-hours", dest="window_hours", default=None)
            p.add_argument("--min-feed-days", dest="min_feed_days", default=None,
                           help="the feed's horizon: how far ahead a video is put into a slot")
            p.add_argument("--batch-feed-days", dest="batch_feed_days", default=None,
                           help="CF-0922: a batch when the feed covers fewer days (>= the horizon)")
            p.add_argument("--windows", default=None,
                           help="CF-0830: the windows of a day, HH:MM,HH:MM ('' - back to --window)")
            p.add_argument("--studio-read", dest="studio_read", default=None,
                           help="CF-0926: on | off - the planned Studio read (the factory's)")
            p.add_argument("--studio-read-at", dest="studio_read_at", default=None,
                           help="CF-0926: HH:MM (Moscow) - when the planned Studio read starts")
        if name == "install-timer":
            p.add_argument("--print", dest="print_", action="store_true",
                           help="print the plist (stdout) and the commands (stderr); nothing is installed")
            p.add_argument("--interval", type=int, default=INTERVAL_S)
    try:
        ns = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_REFUSED if e.code else EXIT_OK
    root = Path(ns.root).resolve() if ns.root else CODE
    try:
        if ns.cmd == "plan":
            p = plan(root, ns.now, ns.days)
            if ns.json:
                print(json.dumps(p, ensure_ascii=False, indent=2), file=out)
            else:
                print("\n".join(plan_lines(p)), file=out)
            return EXIT_OK
        if ns.cmd == "stranded":
            got = stranded_batches(root, ns.now)
            if ns.json:
                print(json.dumps(got, ensure_ascii=False, indent=2), file=out)
            else:
                print("\n".join(stranded_line(b) for b in got) or "застрявших батчей нет", file=out)
            return EXIT_OK
        if ns.cmd == "status":
            st = switch_state(root)
            brk = breakers(root, ns.now)                           # CF-0822
            bud = budget_status(root, ns.now)                      # CF-0830
            if ns.json:
                print(json.dumps({"switch": st, "breakers": brk, "budget": bud},
                                 ensure_ascii=False, indent=2), file=out)
                return EXIT_OK
            print(st["line"], file=out)
            for h in st["history"]:
                print(f"  {h.get('at')} {h.get('action')} by {h.get('by')}"
                      + (f" - {h['note']}" if h.get("note") else ""), file=out)
            for line in breaker_lines(brk):
                print(line, file=out)
            print(bud["line"], file=out)
            return EXIT_OK
        if ns.cmd in ("enable", "disable"):
            st = set_switch(ns.cmd == "enable", ns.by, ns.note, root)
            print(st["line"], file=out)
            if ns.cmd == "enable":
                print("the timer is a separate step: install-timer --print (docs/batch-schedule.md)",
                      file=out)
            return EXIT_OK
        if ns.cmd == "tick":
            code, line, _row = tick(root, ns.now, ns.dry_run, ns.executor)
            print(line, file=out)
            return code
        if ns.cmd == "settings":
            fchanges = {k: getattr(ns, k) for k in FACTORY_KEYS if getattr(ns, k) is not None}
            if fchanges:                                        # CF-0926: the factory's own
                if not ns.by:
                    raise ScheduleError("settings: --studio-read / --studio-read-at need --by")
                got = set_factory_settings(fchanges, ns.by, ns.note, root)
                print(("changed: " + ", ".join(f"{k} {a} -> {b}" for k, (a, b) in got["changed"].items()))
                      if got["changed"] else "no change", file=out)
            fs = factory_settings(root)
            print(studio_read_line(fs), file=out)
            if fchanges:
                for h in fs["history"][-5:]:
                    print(f"  {h.get('at')} by {h.get('by')}: "
                          + ", ".join(f"{k} {a} -> {b}" for k, (a, b) in (h.get("changes") or {}).items())
                          + (f" - {h['note']}" if h.get("note") else ""), file=out)
            changes = {k: getattr(ns, k) for k in SETTINGS_KEYS if getattr(ns, k) is not None}
            if fchanges and not changes and not ns.channel:
                return EXIT_OK
            if changes:
                if not ns.channel or not ns.by:
                    raise ScheduleError("settings: a change needs <channel> and --by")
                got = set_channel_settings(ns.channel, changes, ns.by, ns.note, root)
                print(("changed: " + ", ".join(f"{k} {a} -> {b}" for k, (a, b) in got["changed"].items()))
                      if got["changed"] else "no change", file=out)
            for ch in ([ns.channel] if ns.channel else collect().channels(root)):
                st = channel_settings(ch, root)
                try:
                    stub = no_pipeline(ch, _channel_json(ch, root))
                except (OSError, ValueError, ScheduleError):
                    stub = None
                if stub:                                        # CF-0562
                    print(f"{ch}: {stub} - в расписании не участвует", file=out)
                    continue
                print(f"{ch}: " + (st["error"] if st.get("error") else
                                   f"{'участвует' if st['enabled'] else 'НЕ участвует'}; окно "
                                   f"{', '.join(st['windows']) if st.get('windows') else st['window']}"
                                   f" {st['tz']} + {st['window_hours']} ч; горизонт ленты "
                                   f"{st['min_feed_days']} дн., порог батча "
                                   f"{st['batch_feed_days']} дн. ({st['source']})"), file=out)
                for h in settings_history(root, channel=ch):
                    print(f"  {h.get('at')} by {h.get('by')}: "
                          + ", ".join(f"{k} {a} -> {b}" for k, (a, b) in (h.get("changes") or {}).items())
                          + (f" - {h['note']}" if h.get("note") else ""), file=out)
            return EXIT_OK
        if ns.cmd == "install-timer":
            if not ns.print_:
                print("install-timer: only --print - the timer is installed by the user (or by "
                      "Claude on the user's explicit word), never by this program; "
                      "see docs/batch-schedule.md", file=err)
                return EXIT_REFUSED
            print(plist_text(root, ns.interval), file=out, end="")
            print("\n".join(install_commands()), file=err)
            return EXIT_OK
    except (ScheduleError, ValueError) as e:
        print(f"batch_schedule: {e}", file=err)
        return EXIT_REFUSED
    return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

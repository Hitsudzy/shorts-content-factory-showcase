#!/usr/bin/env python3
"""CF-0667: «остановить батч» and «продолжить батч» - the two actions the
command center's batch screen (CC-0047) calls, as functions and a CLI;
CF-0668: «пересобрать ролики» (rebuild) beside them.

Before this a batch was stopped by hand with `kill -9` (docs/running-a-batch.md)
and resumed with `run_executor.py run <ch> --resume DIR` in the foreground.

    python3 shared/batch_control.py stop   --batch DIR --by user [--confirm] [--also-step] [--json]
    python3 shared/batch_control.py resume --batch DIR --by user [--confirm] [--json]

Without `--confirm` (or with `--check`) only the check runs and nothing is
touched. Every function returns a dict with `ok` and `reason` (Russian, one
line, for the screen); the CLI prints `reason` (or the dict with `--json`) and
exits 0 when `ok`, 2 when refused. `rerun_from_check` / `rerun_from` and
`resume_check` / `resume` also carry `code`: a stable snake_case name of the
refusal (`RERUN_CODES`, `RESUME_CODES`), None when `ok` - the command center
reads it instead of parsing `reason`, whose wording may change.

**Which process is the executor.** The one that holds `<batch>/run-executor.lock`
(`fcntl.flock`, released by the kernel when the holder dies - CF-0203) and whose
pid the lock file names, its command line checked as `pid_alive` checks a step:
a `run_executor.py` that is not a `_exec` wrapper, not a zombie. A lock held by
a process that is not recognised is a refusal, never a guess.
The rule lives in `shared/runlog/executor_lock.py` (CF-0670), which
`runlog.open_batches` reads too: a run whose lock is held stays open.

**stop.** SIGTERM to the executor's process group (only the pid when that
group is the caller's own), then a wait of at most `grace_s`. One that is still
alive is said so - SIGKILL is never sent silently; the line names the command
to send it by hand. The step being run lives in a session of its own (CF-0203)
and is left running unless `also_step`: then it gets SIGTERM to its group too,
after the executor is gone (so no dead executor records the killed step's exit
code). A step killed this way has its exit file moved aside (`<key>.exit.stopped`),
so `--resume` starts it again (`restarts` +1, CF-0204 closes a skill stage's
dead attempt) instead of taking the kill for the step's answer. A step left
running is waited for by `--resume` (same pid, no second start). The step is
killed only when its whole group is empty (CF-0655): the wrapper dies with its
direct child, and a grandchild that caught SIGTERM is said as left running.
Then `run-state.json` gets `status: stopped` and a row in `stops` (who, when,
the executor, the step), the batch's journal a `control` event `batch-stop`
(through `runlog.emit`, only when RUN_EVENTS.jsonl exists - the stop never
creates a journal), and the bus (`shared/notify.py`) one `run_halted`
notification. Nothing writes `batch-done`: the stopped batch stays open for
`runlog batch-active` / `open_batches` (CF-0656) and keeps the factory's
one-batch-at-a-time rule; nothing moves HEAD, so there is no `code_drift`.

**resume.** Refused while the executor is alive; allowed when `run-state.json`
says halted, paused, failed or stopped - and for running/new with a dead
executor (killed or crashed without writing its end, the old `kill -9` path).
Refused while another batch is open (fresh), and when the channel's plan
changed since the run started (the executor would refuse it with exit 2).
The start is `batch_schedule.spawn_detached` - the same detached start as the
tick's and the console's «запустить» - of `run_executor.py run <ch> --root R
--resume DIR`, under the tick's lock, a row of `schedule/launches.jsonl` with
`kind: resume` (not a batch of the day: the one-a-day rule does not limit a
resume, it is the same batch), a `control` event `batch-resume` in the journal,
a `batch_started` notification. It waits up to `RESUME_TAKE_S` for the new
executor to take the lock (or to end at once - then its exit code is said).

**rebuild** (CF-0668, grill CF-0626 Q5: «пересборка - напрямую через
исполнитель»). `rebuild_check(batch, videos, mode)` / `rebuild(batch, videos,
mode, by, confirmed, notes)`: chosen videos of a *finished* batch made again
in a mode of the channel's plan (`run_plan.rebuild.modes`: `reedit` from the
video-editor, `rewrite` from the content-researcher). Refused for a video not
in the batch's 05, a source that is not closed (its run-state not done/failed,
its executor alive, its journal open), another batch or rebuild open (fresh in
`runlog.open_batches`, or a rebuild whose executor is alive) - batches one at
a time; the one-a-day rule does not apply (a rebuild spends no search quota;
`started_on` skips `kind: rebuild`). The start: `pipeline/rebuilds/<ts>`, the
mode's `copy` (in `only_videos` files `scripts[]`/`results[]` keep only the
chosen videos; `work/<slug>/` without its attempts ledger, judge frames and
locks), `runlog batch-start --note` (refused -> the directory is removed),
`run-state.json` with the stages before `from` and the mode's `skip` skipped
and a `rebuild` block (source, videos, exclusions, notes, the stage args
filled), then `run_executor run <ch> --resume <dir>` detached like resume,
a `launches.jsonl` row `kind: rebuild`, a `batch_started` notification. From
there it is a batch: `stop`/`resume` above work on it; its 05/06 carry
`rebuild_of` (write_batch_metadata, CF-0416) and acceptance is a batch's.

    python3 shared/batch_control.py rebuild --batch DIR --video SLUG [--video ..] --mode reedit|rewrite
            --by user [--exclude SLUG:BLOCK[=SHOT]] [--note TEXT] [--video-note SLUG:TEXT]
            [--confirm | --dry-run] [--json]

**rerun-from** (CF-0739). `rerun_from_check(batch, stage)` / `rerun_from(batch,
stage, by, via, confirmed, note, resume_after)`: the stages from `stage` to the
end of the plan (`always` ones too) back to `pending` and their records in
run-state.json (`RERUN_KEYS`) removed, so that `resume` runs them again -
`failed` is terminal for the executor. The plan names the stages, the records,
the logs the re-run rewrites and the files the stages wrote (`produces` /
`updates` on disk): nothing is deleted, the re-run overwrites them - except
the files a `stage-start` guard reads (CF-0776, `GUARD_FILES`: the stop-cock's
and the plan check's 03, the supplement step's work files), which are moved
into `before-rerun-<ts>/` beside the state's copy when the stage that starts
them is reset, so the guards judge the re-run and not the run before it; the
entries a reset stage wrote into an earlier stage's block (CF-0784,
`STALE_BLOCKS`: the reserve loop's in `01b -> reserve_substitution`; the
reserve round after the frame judge's in `01b`, `03`, `04`, `05` and `06`,
CF-0801/CF-0802), which go there too, the file copied whole and the block
left with the earlier stage's own entries; and a reset from the stage that assigns the rotation closes the batch's standing,
unproduced ledger rows (`rotation/ledger/<channel>.closures.jsonl`), so the
re-run's `assign` draws them again under today's rules. Confirmed:
`run-state.before-rerun-<ts>.json`, the state written atomically under the
tick's lock and the run's lock, status `stopped`, `next` the stage, a
`manual_resets` row, a `control batch-rerun-from` event; `resume_after` calls
`resume`. Refused: a live executor / a held lock, a step still running,
another open batch, an unknown stage or a handler, the stage that opens the
journal or one before it, a stage not yet run, an earlier failed stage, a
changed plan, bad by / via.

    python3 shared/batch_control.py rerun-from --batch DIR --stage S --by user [--via center]
            [--note TEXT] [--confirm] [--resume] [--json]

**blocks** (CF-0669): `blocks_at(batch, slug, seconds)` - the seconds of a
remark («12 с мыло») to the blocks of the video's `work/<slug>/plan.json`:
block number, its window, the shot(s) on screen then, the ending - and the
`BLOCK=SOURCE:SHOT` exclusions `rebuild` takes. Reads only.

    python3 shared/batch_control.py blocks --batch DIR --video SLUG --at 12 18 24 [--json]

**Not only Mac** (CF-0654): both need POSIX process groups (`os.killpg`,
`start_new_session`) and `ps`; elsewhere both refuse with that reason.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import batch_schedule as bs  # noqa: E402
import channel_ids  # noqa: E402
import proc_group  # noqa: E402
import run_executor as rx  # noqa: E402
import run_plan  # noqa: E402

TASK = "CF-0667"
GRACE_S = 30.0                  # SIGTERM -> dead, for the executor and for the step
RESUME_TAKE_S = 15.0            # the resumed executor takes the lock within this
POLL_S = 0.1
RESUMABLE = ("halted", "paused", "failed", "stopped")
CRASHED = ("running", "new")    # with a dead executor: it died without writing its end
KIND_CONTROL = "control"        # a journal event that opens and closes nothing
EV_STOP, EV_RESUME = "batch-stop", "batch-resume"
STOPPED = "stopped"
EXIT_OK, EXIT_REFUSED = 0, 2


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def posix():
    """Process groups and `ps`: what stop and resume stand on (CF-0654)."""
    return os.name == "posix" and hasattr(os, "killpg") and hasattr(os, "getpgid")


NOT_POSIX = ("на этой системе нет POSIX-групп процессов (os.killpg) - остановка и продолжение "
             "батча здесь не работают (CF-0654, «Не только Mac»)")


# --------------------------------------------------------------------------
# reading the batch
# --------------------------------------------------------------------------

def _resolve(batch, root=None):
    b = Path(batch).expanduser()
    if not b.is_absolute():
        b = Path(root or bs.CODE) / b
    return b.resolve()


def read_state(batch):
    try:
        doc = json.loads((Path(batch) / rx.STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _xl():
    """`shared/runlog/executor_lock.py`: who holds the run's lock - the one
    answer this module and `runlog.open_batches` share (CF-0670)."""
    return _runlog().sibling("executor_lock")


def _ps(pid):
    """`(stat, command)` of a live pid, None when there is none."""
    return _xl().ps(pid)


def _is_executor(pid):
    """The pid runs `run_executor.py` (not its `_exec` wrapper) and is no zombie."""
    return _xl().is_executor(pid)


def lock_held(batch):
    """True while some process holds `<batch>/run-executor.lock` (a shared,
    non-blocking probe released at once)."""
    return _xl().lock_held(batch)


def _lock_pid(batch):
    return _xl().lock_pid(batch)


def executor_of(batch, st=None):
    """`{pid, alive, pgid, lock_held}` of the batch's executor."""
    st = st if st is not None else (read_state(batch) or {})
    h = _xl().holder(batch, pid=(st.get("executor") or {}).get("pid"))
    pid, alive = h["pid"], h["alive"]
    pgid = None
    if alive and posix():
        try:
            pgid = os.getpgid(int(pid))
        except OSError:
            pgid = None
    return {"pid": pid, "alive": alive, "pgid": pgid, "lock_held": h["held"]}


def step_of(batch, st):
    """The step the run is on: `{stage, run, pid, pgid, alive, exit, log}` or None."""
    cur = (st or {}).get("current") or {}
    key = cur.get("run")
    rec = ((st or {}).get("runs") or {}).get(key) if key else None
    if not rec or not rec.get("pid"):
        return None
    exit_file = Path(batch) / rec.get("exit_file", "")
    alive = rec.get("exit") is None and bool(rec.get("exit_file")) and \
        rx.pid_alive(rec["pid"], str(exit_file))
    return {"stage": cur.get("stage") or rec.get("stage"), "run": key, "pid": rec["pid"],
            "pgid": rec.get("pgid") or rec["pid"], "alive": alive, "exit": rec.get("exit"),
            "log": rec.get("log")}


def _base(action, batch, st, root=None):
    """The fields both checks share. The channel is resolved at the door: a
    batch from before a rename carries its former id (CF-0250)."""
    root = root or (st or {}).get("root")
    return {"task": TASK, "action": action, "ok": False, "reason": "", "batch": str(batch),
            "batch_id": Path(batch).name,
            "channel": channel_ids.resolve_channel((st or {}).get("channel"), root),
            "status": (st or {}).get("status"), "stage": ((st or {}).get("current") or {}).get("stage"),
            "executor_pid": None, "executor_pgid": None, "executor_alive": False,
            "lock_held": False, "step": None, "posix": posix()}


def _with_executor(out, ex):
    out.update(executor_pid=ex["pid"], executor_pgid=ex["pgid"], executor_alive=ex["alive"],
               lock_held=ex["lock_held"])
    return out


def _wait(cond, seconds):
    t0 = time.time()
    while True:
        if cond():
            return True
        if time.time() - t0 >= seconds:
            return False
        time.sleep(POLL_S)


def _term(pid, pgid):
    """SIGTERM to the group (to the pid alone when the group is ours). What was
    signalled, as words; None when the target is already gone."""
    try:
        if pgid and pgid != os.getpgrp():
            os.killpg(int(pgid), signal.SIGTERM)
            return f"группе {pgid}"
        os.kill(int(pid), signal.SIGTERM)
        return f"процессу {pid}"
    except ProcessLookupError:
        return None


# --------------------------------------------------------------------------
# the journal and the bus
# --------------------------------------------------------------------------

def _runlog():
    return bs.collect().runlog()


def journal_event(batch, status, by, note, params=None, task=TASK):
    """A `control` event in `<batch>/RUN_EVENTS.jsonl` - only when the journal
    exists (a stop never creates one). The event or None."""
    if not (Path(batch) / rx.EVENTS_FILE).exists():
        return None
    try:
        return _runlog().emit(Path(batch), KIND_CONTROL, None, status=status,
                              params=params, by=by, note=note, task=task)
    except Exception as e:                                       # noqa: BLE001
        print(f"batch_control: journal event {status} not written ({e})", file=sys.stderr)
        return None


def _label(channel, root=None):
    """CF-0925: the channel as a message names it (Reel, Tech)."""
    try:
        import notify as bus                    # shared/ is on sys.path
        return bus.channel_label(channel, root)
    except Exception:                                            # noqa: BLE001
        return channel


def _day(batch_id):
    """CF-0925: `08.11` for a batch id, the id itself when it is not one."""
    try:
        import notify_human                     # shared/ is on sys.path
        return notify_human.batch_day(batch_id) or batch_id
    except Exception:                                            # noqa: BLE001
        return batch_id


def _where_words(channel, batch_id, root=None):
    """CF-0925: `Reel, батч 08.11`."""
    return f"{_label(channel, root)}, батч {_day(batch_id)}"


def _notify(kind, key, text, channel, root, environ=None):
    try:
        import notify as bus                    # shared/ is on sys.path
        return bus.send(kind, key, text, channel=channel, link=bus.link_of(channel, "batch"),
                        root=Path(root), environ=environ)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY {kind}: {type(e).__name__}: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# stop
# --------------------------------------------------------------------------

def stop_check(batch, root=None):
    """Can the batch be stopped - read only. `{ok, reason, batch, batch_id,
    channel, status, stage, executor_pid, executor_pgid, executor_alive,
    lock_held, step: {stage, run, pid, pgid, alive, exit, log} | None, posix}`."""
    batch = _resolve(batch, root)
    st = read_state(batch)
    out = _base("stop", batch, st, root)
    if not posix():
        out["reason"] = NOT_POSIX
        return out
    if st is None:
        out["reason"] = f"в {batch} нет {rx.STATE_FILE} - это не батч исполнителя"
        return out
    ex = executor_of(batch, st)
    _with_executor(out, ex)
    out["step"] = step_of(batch, st)
    if ex["alive"]:
        out["ok"] = True
        out["reason"] = (f"исполнитель pid {ex['pid']} жив" + (f", стадия {out['stage']}"
                         if out["stage"] else "") + " - можно остановить")
    elif ex["lock_held"]:
        out["reason"] = (f"{rx.LOCK_FILE} держит процесс, не узнанный как исполнитель (в файле "
                         f"pid {ex['pid']}) - отказ, разобраться руками")
    else:
        out["reason"] = (f"исполнитель не жив (статус {out['status']}) - батч уже стоит; "
                         f"продолжить: resume")
    return out


def stop(batch, by, confirmed=False, also_step=False, root=None, grace_s=GRACE_S,
         environ=None):
    """Stop the batch's executor (and, with `also_step`, the step it runs).
    The check's dict plus `{by, also_step, stopped, step_killed,
    step_left_running, executor_signalled, stop}` (`stop`: the row written to
    run-state.json `stops`). Nothing is touched unless `confirmed` and the
    check holds."""
    batch = _resolve(batch, root)
    chk = stop_check(batch, root)
    res = dict(chk, by=by, also_step=bool(also_step), stopped=False, step_killed=False,
               step_left_running=False, executor_signalled=None, stop=None)
    if not by or not str(by).strip():
        res.update(ok=False, reason="нужно указать, кто останавливает (by)")
        return res
    if not confirmed:
        res.update(ok=False, reason="не подтверждено: батч не остановлен (нужно подтверждение)")
        return res
    if not chk["ok"]:
        return res
    pid, pgid = chk["executor_pid"], chk["executor_pgid"]
    channel, stage = chk["channel"], chk["stage"]
    try:
        whom = _term(pid, pgid)
    except OSError as e:
        res.update(ok=False, reason=f"SIGTERM исполнителю pid {pid} не послан ({e})")
        return res
    res["executor_signalled"] = whom or "уже не было"
    if not _wait(lambda: not _is_executor(pid), grace_s):
        res.update(ok=False, reason=(
            f"исполнитель pid {pid} не умер за {grace_s:g} с после SIGTERM ({whom}); SIGKILL не "
            f"послан - решить руками: kill -9 -{pgid or pid} (docs/running-a-batch.md)"))
        journal_event(batch, EV_STOP, by, f"executor pid {pid} survived SIGTERM",
                      {"result": "executor_alive", "pid": pid, "pgid": pgid})
        return res
    st = read_state(batch) or {}                # what the executor wrote before it died
    prev = st.get("status")
    step = step_of(batch, st)
    if also_step and step and step["alive"]:
        rec = st["runs"][step["run"]]
        exit_file = batch / rec["exit_file"]
        try:
            _term(step["pid"], step["pgid"])
        except OSError as e:
            res["reason_step"] = f"SIGTERM шагу pid {step['pid']} не послан ({e})"
        group = step["pgid"] if step["pgid"] and step["pgid"] != os.getpgrp() else None
        wrapper_gone = _wait(lambda: not rx.pid_alive(step["pid"], str(exit_file)), grace_s)
        if wrapper_gone and exit_file.exists():  # the kill is not the step's answer
            os.replace(exit_file, exit_file.with_name(exit_file.name + ".stopped"))
        # CF-0655: the wrapper dies with its direct child; a grandchild in the
        # group that caught SIGTERM is still running - the step is not killed.
        if wrapper_gone and (group is None or proc_group.wait_gone(group, 1.0)):
            res["step_killed"] = True
        elif wrapper_gone:
            res["step_left_running"] = True
            res["reason_step"] = (f"шаг {step['run']} pid {step['pid']} умер, но в его группе "
                                  f"{group} остались процессы после SIGTERM; SIGKILL не послан - "
                                  f"kill -9 -{group} руками")
        else:
            res["step_left_running"] = True
            res["reason_step"] = (f"шаг {step['run']} pid {step['pid']} не умер за {grace_s:g} с "
                                  f"после SIGTERM; SIGKILL не послан - kill -9 -{step['pgid']} "
                                  f"руками, иначе --resume его дождётся")
    elif step and step["alive"]:
        res["step_left_running"] = True
    row = {"at": now_iso(), "by": by, "task": TASK, "executor_pid": pid, "executor_pgid": pgid,
           "previous_status": prev, "stage": stage, "also_step": bool(also_step),
           "step": dict(step or {}, killed=res["step_killed"],
                        left_running=res["step_left_running"]) if step else None}
    if st and prev in CRASHED:
        st["status"] = STOPPED
        st.setdefault("stops", []).append(row)
        rx.write_json_atomic(batch / rx.STATE_FILE, st)
        res["status"] = STOPPED
        res["stopped"] = True
    res["stop"] = row
    res["executor_alive"] = False
    step_words = ("шаг остановлен" if res["step_killed"] else
                  f"шаг {step['run']} pid {step['pid']} работает дальше, --resume его дождётся"
                  if res["step_left_running"] else "шага в работе не было")
    if res["stopped"]:
        res["ok"] = True
        res["reason"] = (f"батч {batch.name} остановлен" + (f" на {stage}" if stage else "")
                         + f" ({by}); {step_words}; продолжить: resume")
        res["resume_hint"] = (f"python3 shared/batch_control.py resume --batch {batch} --by {by} "
                              f"--confirm")
    else:
        res["ok"] = False
        res["reason"] = (f"исполнитель pid {pid} закончил сам (статус {prev}) - "
                         f"статус не тронут")
    journal_event(batch, EV_STOP, by, res["reason"],
                  {"result": "stopped" if res["stopped"] else "ended_itself", "pid": pid,
                   "stage": stage, "also_step": bool(also_step), "step_killed": res["step_killed"],
                   "step_left_running": res["step_left_running"]})
    if res["stopped"]:
        root_ = Path(root or st.get("root") or bs.CODE)
        _notify("run_halted", f"batch_stop:{batch.name}:{row['at']}",
                f"⏸ {_where_words(channel, batch.name, root_)}: остановлен вручную ({by})"
                + (f" на {stage}" if stage else "")
                + " - продолжить можно с того же места", channel, root_, environ)
    return res


# --------------------------------------------------------------------------
# resume
# --------------------------------------------------------------------------

def _executor_argv(channel, root, batch, executor=None, executor_args=()):
    exe = Path(executor) if executor else Path(rx.__file__).resolve()
    return [sys.executable, str(exe), "run", channel, "--root", str(root), "--resume",
            str(batch), *executor_args]


# `code` of a resume answer (None when ok): the rerun-from names where the
# refusal is the same, plus resume's own.
RESUME_CODES = frozenset({
    "not_posix", "no_state", "executor_alive", "lock_foreign", "no_channel",
    "batch_finished", "plan_changed", "plan_unreadable", "open_unreadable",
    "other_batch_open", "bad_who", "not_confirmed", "locked", "spawn_failed",
    "exited_at_once"})


def resume_check(batch, root=None, now=None, open_rows=None, executor=None, executor_args=()):
    """Can the batch go on - read only. `{ok, reason, batch, batch_id, channel,
    status, stage, executor_pid, executor_alive, lock_held, step, posix, root,
    argv}`. `open_rows` stands in for `runlog.open_batches` (tests)."""
    batch = _resolve(batch, root)
    st = read_state(batch)
    out = _base("resume", batch, st, root)
    out["argv"] = None
    out["code"] = None
    if not posix():
        out["code"] = "not_posix"
        out["reason"] = NOT_POSIX
        return out
    if st is None:
        out["code"] = "no_state"
        out["reason"] = f"в {batch} нет {rx.STATE_FILE} - продолжать нечего"
        return out
    root = Path(root or st.get("root") or bs.CODE).resolve()
    out["root"] = str(root)
    ex = executor_of(batch, st)
    _with_executor(out, ex)
    out["step"] = step_of(batch, st)
    status, channel = st.get("status"), out["channel"]
    if ex["alive"]:
        out["code"] = "executor_alive"
        out["reason"] = f"исполнитель pid {ex['pid']} жив - батч идёт, продолжать нечего"
        return out
    if ex["lock_held"]:
        out["code"] = "lock_foreign"
        out["reason"] = (f"{rx.LOCK_FILE} держит процесс, не узнанный как исполнитель (в файле "
                         f"pid {ex['pid']}) - отказ, разобраться руками")
        return out
    if not channel:
        out["code"] = "no_channel"
        out["reason"] = f"в {rx.STATE_FILE} нет канала - продолжать нечем"
        return out
    if status in RESUMABLE:
        why = f"батч стоит (статус {status})"
    elif status in CRASHED:
        why = f"исполнитель умер, не записав конца (статус {status}: kill -9 или сбой)"
    else:
        out["code"] = "batch_finished"
        out["reason"] = f"батч не стоит, а закончен (статус {status}) - продолжать нечего"
        return out
    try:
        plan = run_plan.load(channel, root)
        if st.get("plan_fingerprint") and st["plan_fingerprint"] != rx.fingerprint(plan):
            out["code"] = "plan_changed"
            out["reason"] = (f"план канала {channel} изменился с начала батча - исполнитель "
                             f"откажется (--plan-changed-ok только руками)")
            return out
    except run_plan.PlanError as e:
        out["code"] = "plan_unreadable"
        out["reason"] = f"план канала {channel} не читается ({e})"
        return out
    try:
        rows = open_rows if open_rows is not None else _runlog().open_batches(root, now=now)
    except Exception as e:                                       # noqa: BLE001
        out["code"] = "open_unreadable"
        out["reason"] = f"открытые батчи не читаются ({e}) - отказ"
        return out
    others = [r for r in rows if r[2] and Path(r[0]).resolve() != batch]
    if others:
        o = Path(others[0][0])
        out["code"] = "other_batch_open"
        out["reason"] = (f"открыт другой батч {o.parent.name}/{o.name}{_why(others[0])} - "
                         f"один батч за раз, сначала он")
        return out
    out["argv"] = _executor_argv(channel, root, batch, executor, executor_args)
    out["ok"] = True
    out["code"] = None
    out["reason"] = f"{why} - можно продолжить с {st.get('next') or 'того же места'}"
    return out


def resume(batch, by, confirmed=False, root=None, now=None, environ=None, executor=None,
           open_rows=None, executor_args=(), take_s=RESUME_TAKE_S, auto=None):
    """Start `run_executor run <ch> --resume DIR` detached. The check's dict
    plus `{by, resumed, pid, log, row, exit}` (`row`: the launches.jsonl row;
    `exit`: the executor's code when it ended before taking the lock).
    Nothing starts unless `confirmed` and the check holds - checked again
    under the tick's lock.

    CF-0899: `auto` - the tick's own resume of a batch halted on `claude` not
    logged in, a short reason (the row's `auto`); its notification is keyed by
    the batch and the Moscow day, so a resume that halts again and is retried
    tells the user once, not every attempt."""
    batch = _resolve(batch, root)
    res = {"task": TASK, "action": "resume", "ok": False, "batch": str(batch),
           "batch_id": batch.name, "by": by, "resumed": False, "pid": None, "log": None,
           "row": None, "exit": None, "code": None}
    if not by or not str(by).strip():
        res["code"] = "bad_who"
        res["reason"] = "нужно указать, кто продолжает (by)"
        return res
    if not confirmed:
        res.update(resume_check(batch, root, now, open_rows, executor, executor_args),
                   ok=False, by=by, resumed=False, code="not_confirmed",
                   reason="не подтверждено: батч не продолжен (нужно подтверждение)")
        return res
    st = read_state(batch) or {}
    root_ = Path(root or st.get("root") or bs.CODE).resolve()
    # CF-0899: the tick's resume is stamped with the tick's clock (its back-off reads it)
    at = bs.iso(bs.now_utc(now)) if auto and now else now_iso()
    day = bs.msk_day(bs.now_utc(now)).isoformat()
    try:
        with bs._locked(bs.state_dir(root_, environ)):
            chk = resume_check(batch, root_, now, open_rows, executor, executor_args)
            res.update(chk, by=by, resumed=False)
            if not chk["ok"]:
                return res
            try:
                proc, log = bs.spawn_detached(chk["argv"], root_, day, chk["channel"], environ)
            except OSError as e:
                res.update(ok=False, code="spawn_failed",
                           reason=f"не стартовал {' '.join(chk['argv'])} ({e})")
                return res
            row = {"at": at, "day": day, "channel": chk["channel"], "pid": proc.pid,
                   "argv": chk["argv"], "log": str(log), "kind": "resume", "batch": str(batch),
                   "from_status": chk["status"], "by": by,
                   "why": f"продолжение батча {batch.name} (был {chk['status']})", "task": TASK}
            if auto:                                             # CF-0899
                row["auto"] = auto
            bs.journal_launch(row, root_, environ)
            _wait(lambda: proc.poll() is not None or
                  (lock_held(batch) and _lock_pid(batch) == proc.pid), take_s)
    except bs.ScheduleError as e:
        res.update(ok=False, code="locked", reason=f"отказ: {e}")
        return res
    res.update(pid=proc.pid, log=str(log), row=row, resumed=True)
    code = proc.poll()
    if code is None:
        res.update(ok=True, code=None, reason=(f"батч {batch.name} продолжен ({by}): исполнитель pid "
                                    f"{proc.pid}, журнал {log}"))
    else:
        took = code in (rx.EXIT_DONE, rx.EXIT_FAILED, rx.EXIT_PAUSED)
        res.update(exit=code, ok=took, code=None if took else "exited_at_once",
                   reason=(f"исполнитель pid {proc.pid} сразу закончил с кодом {code} "
                           f"(журнал {log})"))
    journal_event(batch, EV_RESUME, by, res["reason"],
                  {"pid": proc.pid, "from_status": chk["status"], "exit": code})
    if auto:                                                     # CF-0899
        _notify("batch_started", f"batch_resume:{batch.name}:auto:{day}",
                f"▶️ {_where_words(chk['channel'], batch.name, root_)}: продолжен сам ({by}): {auto}",
                chk["channel"], root_, environ)
    else:
        _notify("batch_started", f"batch_resume:{batch.name}:{at}",
                f"▶️ {_where_words(chk['channel'], batch.name, root_)}: продолжен вручную ({by})",
                chk["channel"],
                root_, environ)
    return res


# --------------------------------------------------------------------------
# rerun-from (CF-0739)
# --------------------------------------------------------------------------

RERUN_TASK = "CF-0739"
EV_RERUN = "batch-rerun-from"
# What a stage leaves in run-state.json beside `stages[sid]`, keyed by the run
# key (`<stage>.s0.a1`, `<stage>.llm`, `<stage>.s0` in `reruns`, a handler's
# `<handler>@<stage>.s0.a0`), by the stage's prefix (`decisions`) or by the llm
# key (`code_guard`, CF-0713). A reset stage loses them all, so the executor
# starts its runs afresh instead of taking the old exit codes for answers.
RERUN_KEYS = ("runs", "reruns", "handlers", "decisions", "code_guard")
WHO_MAX = 40                    # by / via: the CF-0700 rule (notify._who)
RERUN_STATUS = STOPPED          # resumable; and not «closed» for rebuild_check
# `code` of a rerun-from answer (None when ok) - the names the command center
# keys on; `reason` stays the Russian line for the screen. `no_channel` and
# `resume_failed` (rerun done, the `resume_after` start refused or failed - its
# own `code` is in `resume`) are not among the center's names yet. CF-0776
# adds none: a failed move of the guards' files is `locked` (nothing written,
# the reason says what), an unreadable rotation ledger is a line of the plan.
RERUN_CODES = frozenset({
    "executor_alive", "lock_foreign", "plan_changed", "stage_handler", "stage_unknown",
    "stage_opens_batch", "stage_not_run", "earlier_failed", "step_running",
    "other_batch_open", "bad_who", "bad_note", "locked", "state_gone", "no_state",
    "not_posix", "plan_unreadable", "open_unreadable", "not_confirmed",
    "no_channel", "resume_failed"})


def _who(value, what):
    """CF-0700's rule for `by` / `via`: a short non-empty single-line string.
    The refusal line, or None when it holds."""
    if not isinstance(value, str) or not value.strip():
        return f"нужно указать {what} - короткая непустая строка (например by=user, via=center)"
    if len(value.strip()) > WHO_MAX or any(c in value for c in "\r\n\t"):
        return f"{what}={value!r}: не длиннее {WHO_MAX} знаков, одной строкой"
    return None


def key_stage(key):
    """The plan stage a run-state key belongs to: the stage a handler runs
    inside of (the part after the last `@`), up to the first `.` or `:`."""
    tail = str(key).rsplit("@", 1)[-1]
    return tail.split(".", 1)[0].split(":", 1)[0]


# CF-0776: what a `stage-start` guard of `runlog.marker` reads off the batch,
# as `(path, origin, guard)`: `origin` is the plan contract whose producer
# starts the file - when that stage is reset the file is the run before's,
# not the re-run's, and it is moved out of the guard's way (16.10, 0839Z: the
# re-run from content-researcher was refused by the stop-cock reading the old
# 03 - «0 scripts ... nothing to substitute»). A reset is a suffix of the plan,
# so the producer reset means every later writer is reset too. The rest of the
# reset stages' files stay: the re-run overwrites them, and an earlier stage's
# file (01b, only `updates`d by a reset stage) is not the re-run's to drop.
# The work files of the thin-pool supplement step start with the Researcher's
# requests (step 6b), so they go with 03: its record of a topic «taken» would
# otherwise swallow the re-run's request for the same topic.
GUARD_FILES = (
    ("03-content-researcher.json", "03-content-researcher.json",
     "стоп-кран CF-0322, проверка плана CF-0422"),
    ("work/supplement-requests", "03-content-researcher.json", "шаг добора CF-0345"),
    ("work/supplement-step.json", "03-content-researcher.json", "шаг добора CF-0345"),
    ("work/supplement-recheck", "03-content-researcher.json", "шаг добора CF-0345"),
)
MOVED_PREFIX = "before-rerun-"
# CF-0781: blocks a reset stage writes into an earlier stage's file, as
# `(path, key, origin, readers, lists, own)`: the file stays (it is the
# earlier stage's), and the part of the block `origin`'s producer wrote is the
# run before's when that producer is reset - the CF-0306 reserve loop answers
# the Researcher's refusals, so its entries go with 03, like the supplement
# step's work files.
# CF-0784: CF-0781 fingerprinted the whole block and left it in the file, so
# that the root's readers (stop-cock, reserve-refill) could read it as absent.
# That did not reach the agents' readers, and could not: the Indexer's loop
# appends to the block it finds (`ingest_batch.substitution_block`), so after
# the re-run's own loop the block is the two runs mixed - `substituted()` and
# the loop's «already answered» took the previous run's losses for answered,
# the Researcher's `fact_refusal` / `parent_decisions` and the funnel counted
# its substitutes into the batch. So the reset moves that part out: the file
# as it stood goes to `before-rerun-<ts>/<path>` beside the guards' files, and
# the block keeps only the entries of `lists` whose `at` is one of `own` (the
# Indexer's own passes, which are not reset); a topic whose entry left goes
# back into `remaining` (in the block's `reserve` order), since the re-run's
# loop may offer it again. Nothing else in the file is touched (the sources a
# substitute got stay in `sources_by_topic` - the re-run's loop reuses them).
OWN_SUBSTITUTION_ATS = ("index_pass", "sieve")   # ingest_batch / source_sieve passes


class Drop(tuple):
    """`own` of a STALE_BLOCKS row read the other way round: the `at`s that
    leave (every other entry stays) - CF-0801."""


# CF-0801 (part of CF-0798): the reserve round after the frame judge writes into
# three earlier stages' files - `01b` (the indexer's `--after-judge` records,
# `at: frame_judge_refusal`), `04` and `06` (the rows `merge_verdicts.py` /
# `frame_judge_merge.py` append, named in their `merges[]`). They are the run
# before's when the round is reset: when the frame judge's own stage (the
# producer of 06) is reset, or a stage after it that `updates` the file
# (CF-0802's round stages). AFTER_JUDGE is that origin; MERGED_ROWS marks a
# row whose part is the `merges[]`-named rows of `key`, not entries by `at`.
# CF-0802: the round also adds rows to `03` (the Researcher's
# `merge_batch_file.py --add`, keyed by topic_id) and `05` (the Editor's
# `write_batch_metadata.py`, merged by script_id) with no merge record of
# their own; ROUND_ROWS marks a row whose part is the rows of the lists in
# `own` that belong to the round - a topic `01b` substituted
# `at: frame_judge_refusal` (read off the file as it stands before the reset
# strips it), or a script of such a topic. The part is the run before's when
# the judge is reset or the round's first stage that `updates` the file is
# (`_origin_reset`): the round's later stages re-run over what that one wrote,
# they do not rewrite it (a re-run from the plan check must keep the scripts
# the Researcher's round stage merged into 03).
AFTER_JUDGE = "after:06-frame-judge.json"
JUDGE_CONTRACT = "06-frame-judge.json"
AFTER_JUDGE_AT = "frame_judge_refusal"            # ingest_batch.JUDGE_AT (CF-0799)
MERGED_ROWS = "merges"
MERGE_MODE = "new-only"
ROUND_ROWS = "round"
ROUND_INDEX = "01b-footage-index.json"
ROUND_SCRIPTS = "03-content-researcher.json"
_ROUND_SCRIPT_SUFFIX = re.compile(r"-script\d+$")
STALE_BLOCKS = (
    ("01b-footage-index.json", "reserve_substitution", "03-content-researcher.json",
     "стоп-кран CF-0322, reserve-refill CF-0306, Индексатор substituted/substitution_block, "
     "Исследователь fact_refusal/parent_decisions, воронка funnel",
     ("substitutions", "unmatched"), OWN_SUBSTITUTION_ATS),
    ("01b-footage-index.json", "reserve_substitution", AFTER_JUDGE,
     "reserve_after_judge CF-0801, Индексатор --after-judge, воронка funnel",
     ("substitutions", "unmatched"), Drop((AFTER_JUDGE_AT,))),
    ("04-compliance-checker.json", "results", AFTER_JUDGE,
     "compliance merge_verdicts pending CF-0800, воронка funnel", MERGED_ROWS, ()),
    ("06-frame-judge.json", "videos", AFTER_JUDGE,
     "судья кадра frame_judge_merge pending CF-0800, воронка funnel", MERGED_ROWS, ()),
    ("03-content-researcher.json", "scripts", AFTER_JUDGE,
     "Исследователь merge_batch_file --add CF-0802, стоп-кран, compliance pending, воронка funnel",
     ROUND_ROWS, ("scripts", "skipped", "warnings")),
    ("05-video-editor.json", "videos", AFTER_JUDGE,
     "Монтажёр new-only CF-0802, судья кадра pending, воронка funnel",
     ROUND_ROWS, ("videos", "refusals")),
)
PREVIOUS_TASK = "CF-0781"
MOVE_BLOCKS_TASK = "CF-0784"
# CF-0776: the stage that assigns the rotation's pairs is the producer of this
# contract; a reset of it closes the batch's standing rows that made no video.
ASSIGNS_CONTRACT = "03-content-researcher.json"
CLOSE_TASK = "CF-0776"


def _producer(by_id, contract):
    return next((sid for sid, st in by_id.items()
                 if contract in (st.get("produces") or [])), None)


def _guard_files(batch, reset, by_id):
    """`[{path, stage, guard}]` of GUARD_FILES on disk whose origin stage is
    reset - the files `rerun_from` moves away."""
    out = []
    for path, origin, guard in GUARD_FILES:
        sid = _producer(by_id, origin)
        if sid in reset and (Path(batch) / path).exists():
            out.append({"path": path, "stage": sid, "guard": guard})
    return out


def _previous_run():
    """shared/runlog/previous_run.py of this checkout, by path (CF-0781)."""
    import importlib.util                                     # noqa: PLC0415
    name = "previous_run"
    here = HERE / "runlog" / "previous_run.py"
    mod = sys.modules.get(name)
    if mod is None or Path(getattr(mod, "__file__", "") or "").resolve() != here.resolve():
        spec = importlib.util.spec_from_file_location(name, here)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[name] = mod
    return mod


def _strip_block(block, lists, own, remaining="remaining", order="reserve"):
    """`(block without the entries of `lists` whose `at` is not in `own`,
    [the entries taken out])` - CF-0784. A topic whose substitution was taken
    out is put back into `remaining` (when the block has one), in the order of
    the block's `order` list when it has one."""
    if not isinstance(block, dict):
        return block, []
    out, gone = dict(block), []
    for name in lists:
        rows = block.get(name)
        if not isinstance(rows, list):
            continue
        if isinstance(own, Drop):
            stays = lambda r: not (isinstance(r, dict) and r.get("at") in own)  # noqa: E731
        else:
            stays = lambda r: isinstance(r, dict) and r.get("at") in own  # noqa: E731
        keep = [r for r in rows if stays(r)]
        gone += [r for r in rows if not stays(r)]
        out[name] = keep
    back = [r.get("topic_id") for r in gone if isinstance(r, dict) and r.get("topic_id")]
    if back and isinstance(block.get(remaining), list):
        have = list(block[remaining])
        want = set(have) | set(back)
        ranked = [t for t in (block.get(order) if isinstance(block.get(order), list) else [])
                  if isinstance(t, str) and t in want]
        tail = [t for t in have + back if t not in ranked]
        merged = []
        for t in ranked + tail:
            if t not in merged:
                merged.append(t)
        out[remaining] = merged
    return out, gone


def _origin_reset(origin, path, reset, by_id):
    """Whether the part of `path` that `origin` stands for is the run before's
    under this reset: the producer of the contract is reset - or, for
    AFTER_JUDGE (CF-0801), the producer of 06 is reset, or a stage placed after
    it in the plan that `updates` `path` is."""
    if origin != AFTER_JUDGE:
        return _producer(by_id, origin) in reset
    judge = _producer(by_id, JUDGE_CONTRACT)
    if judge is None:
        return False
    if judge in reset:
        return True
    ids = list(by_id)
    after = ids[ids.index(judge) + 1:]
    # CF-0802: the round's first writer of the file; its later writers (the
    # supplement and the plan check of the round, on 01b / 03) work over what
    # the first one wrote and do not answer for it
    first = next((sid for sid in after if path in (by_id[sid].get("updates") or [])), None)
    return first is not None and first in reset


def _strip_merges(doc, key):
    """CF-0801: `(doc without the rows of `key` that a `new-only` merge added
    and without those `merges[]` records, [the rows taken out])`. `06`'s
    `counts` are recounted over what stays and its `nothing_to_judge` comes
    back from the first merge's record."""
    merges = doc.get("merges") if isinstance(doc.get("merges"), list) else []
    ours = [m for m in merges if isinstance(m, dict) and m.get("mode") == MERGE_MODE]
    if not ours:
        return doc, []
    ids = {a.get("script_id") for m in ours for a in m.get("added") or []
           if isinstance(a, dict) and a.get("script_id")}
    out = dict(doc)
    gone = []
    for k in (key, "not_judged") if key == "videos" else (key,):
        rows = doc.get(k)
        if not isinstance(rows, list):
            continue
        gone += [r for r in rows if isinstance(r, dict) and r.get("script_id") in ids]
        out[k] = [r for r in rows if not (isinstance(r, dict) and r.get("script_id") in ids)]
    rest = [m for m in merges if m not in ours]
    if rest:
        out["merges"] = rest
    else:
        out.pop("merges", None)
    if key == "videos":
        if "nothing_to_judge_before" in ours[0]:
            out["nothing_to_judge"] = ours[0].get("nothing_to_judge_before")
        if isinstance(out.get("counts"), dict):
            out["counts"] = _recount_06(out)
    return out, gone


def _round_ids(batch):
    """CF-0802: `(topics, scripts)` of the reserve round after the judge, off
    the files as they stand: the topics `01b -> reserve_substitution` holds
    `at: frame_judge_refusal` (substitutions and unmatched), and the script
    ids `03` holds for them."""
    def read(name):
        try:
            return json.loads((Path(batch) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    idx = read(ROUND_INDEX)
    sub = idx.get("reserve_substitution") if isinstance(idx, dict) else None
    topics = set()
    if isinstance(sub, dict):
        for name in ("substitutions", "unmatched"):
            for r in sub.get(name) or []:
                if isinstance(r, dict) and r.get("at") == AFTER_JUDGE_AT and r.get("topic_id"):
                    topics.add(r["topic_id"])
    scripts = set()
    cr = read(ROUND_SCRIPTS) if topics else None
    for r in (cr.get("scripts") or []) if isinstance(cr, dict) else []:
        if isinstance(r, dict) and r.get("topic_id") in topics and r.get("script_id"):
            scripts.add(r["script_id"])
    return topics, scripts


def _strip_round(doc, lists, topics, scripts):
    """CF-0802: `(doc without the rows of `lists` that belong to the round,
    [the rows taken out])` - a row whose `topic_id` is a round topic, or whose
    `script_id` is a round script (or a round topic's `-scriptN`)."""
    def ours(r):
        if not isinstance(r, dict):
            return False
        if r.get("topic_id") in topics:
            return True
        sid = r.get("script_id")
        return bool(sid) and (sid in scripts or _ROUND_SCRIPT_SUFFIX.sub("", sid) in topics)
    if not topics:
        return doc, []
    out, gone = dict(doc), []
    for name in lists:
        rows = doc.get(name)
        if not isinstance(rows, list):
            continue
        gone += [r for r in rows if ours(r)]
        out[name] = [r for r in rows if not ours(r)]
    return (out if gone else doc), gone


def _recount_06(doc):
    """`06`'s `counts` over its rows, by the merger's own arithmetic."""
    import importlib.util                                     # noqa: PLC0415
    name = "frame_judge_merge"
    here = HERE.parent / "scripts" / "frame_judge_merge.py"
    mod = sys.modules.get(name)
    if mod is None or Path(getattr(mod, "__file__", "") or "").resolve() != here.resolve():
        spec = importlib.util.spec_from_file_location(name, here)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[name] = mod
    return mod.recount(doc)


def _stale_blocks(batch, reset, by_id):
    """`[{path, key, readers, block, stripped, moved, doc}]` of STALE_BLOCKS
    present on disk whose origin stage is reset (CF-0781) - read only.
    `stripped` is the block as the reset leaves it, `moved` the entries it
    takes out (CF-0784): `[]` when the block holds only the earlier stage's
    own. `doc` is the whole file as the reset leaves it: two rows on one file
    (`01b`: the Researcher's loop and the round after the judge, CF-0801)
    strip the same document one after the other, so the file is written - and
    copied away - once."""
    out, docs = [], {}
    round_ids = None
    # CF-0802: a file the reset moves whole (GUARD_FILES: 03 when the
    # Researcher is reset) is not stripped first - its copy must be the original
    whole = {g["path"] for g in _guard_files(batch, reset, by_id)}
    for path, key, origin, readers, lists, own in STALE_BLOCKS:
        if path in whole or not _origin_reset(origin, path, reset, by_id):
            continue
        if path not in docs:
            try:
                docs[path] = json.loads((Path(batch) / path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                docs[path] = None
        doc = docs[path]
        if not isinstance(doc, dict) or doc.get(key) is None:
            continue
        if lists == MERGED_ROWS:
            new, moved = _strip_merges(doc, key)
        elif lists == ROUND_ROWS:
            if round_ids is None:            # off the disk: 01b's row may be stripped already
                round_ids = _round_ids(batch)
            new, moved = _strip_round(doc, own, *round_ids)
        else:
            stripped, moved = _strip_block(doc[key], lists, own)
            new = dict(doc)
            new[key] = stripped
        docs[path] = new
        out.append({"path": path, "key": key, "readers": readers, "block": doc[key],
                    "stripped": new[key], "moved": moved})
    for b in out:
        b["doc"] = docs[b["path"]]
    return out


def _move_stale_blocks(batch, stale, dest):
    """CF-0784: for each stale block with entries to move, the file as it
    stands is copied to `dest/<path>` and rewritten with the stripped block.
    `[{path, key, entries}]` of what moved. All or nothing: on an OSError the
    files rewritten get their copy back and it raises."""
    done, out, written = [], [], set()
    try:
        for b in stale:
            if not b["moved"]:
                continue
            src, dst = Path(batch) / b["path"], dest / b["path"]
            if b["path"] not in written:
                doc = b.get("doc")
                if doc is None:                       # a row built by hand (tests)
                    doc = json.loads(src.read_text(encoding="utf-8"))
                    doc[b["key"]] = b["stripped"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                rx.write_json_atomic(src, doc)
                done.append((src, dst))
                written.add(b["path"])
            out.append({"path": b["path"], "key": b["key"], "entries": len(b["moved"]),
                        "topics": [m.get("topic_id") or m.get("replaced") or m.get("script_id")
                                   for m in b["moved"] if isinstance(m, dict)]})
    except (OSError, ValueError):
        for src, dst in reversed(done):
            try:
                shutil.copy2(dst, src)
            except OSError:
                pass
        raise
    return out


def _previous_record(batch, kept, blocks):
    """The `previous_run` record of a reset's row (CF-0781): the sha256 of each
    kept file and of each stale block, as they stand when the reset is
    written."""
    pr = _previous_run()
    files = {}
    for k in kept:
        sha = pr.file_sha(Path(batch) / k["path"])
        if sha and (Path(batch) / k["path"]).is_file():
            files[k["path"]] = sha
    return {"task": PREVIOUS_TASK, "files": files,
            "blocks": {pr.block_ref(b["path"], b["key"]): pr.block_sha(b["block"])
                       for b in blocks}}


def _ledger_mod():
    """rotation/ledger.py of this checkout (the format of the ledger)."""
    here = str(HERE.parent / "rotation")
    if here not in sys.path:
        sys.path.insert(0, here)
    import ledger                                             # noqa: PLC0415
    return ledger


def _ledger_rows_to_close(batch, channel, root, reset, by_id):
    """CF-0776: `(ledger path, [rows])` - the batch's standing rotation rows a
    reset of the assigning stage closes: standing (not rejected, not closed),
    no video produced or published. `(None, [])` when the reset does not cover
    the assigning stage or the channel has no ledger."""
    if _producer(by_id, ASSIGNS_CONTRACT) not in reset or not channel:
        return None, []
    led = _ledger_mod()
    path = led.ledger_path(channel, Path(root) / "rotation" / "ledger")
    if not path.is_file():
        return None, []
    ledger = led.Ledger(path)
    rows = [r for r in ledger.standing_rows() if r["batch_id"] == Path(batch).name
            and not r["produced_at"] and not r["published_at"]]
    return path, rows


def _close_ledger_rows(batch, chk, by, via, stage, note, backup, at):
    """CF-0776: close the rotation rows the plan named (`chk["close_rows"]`),
    as they stand now. `([closure records], error line or None)`; never
    raises - the reset is already written, a ledger that refuses is said."""
    if not chk.get("close_rows"):
        return [], chk.get("ledger_error")
    try:
        led = _ledger_mod()
        ledger = led.Ledger(chk["ledger"])
        named = {r["seq"] for r in chk["close_rows"]}
        out, errs = [], []
        for r in ledger.standing_rows():
            if int(r["seq"]) not in named or r["batch_id"] != Path(batch).name:
                continue
            try:
                out.append(ledger.close(
                    r["seq"], by, CLOSE_TASK,
                    f"rerun-from {stage}: the batch writes this script again" +
                    (f" - {note}" if note else ""), at=at, via=via, backup=backup,
                    rejection_verdict=r["rejection_verdict"] or None))
            except led.LedgerError as e:
                errs.append(str(e))
        return out, ("; ".join(errs) or None)
    except Exception as e:                                       # noqa: BLE001
        return [], f"{e.__class__.__name__}: {e}"


def _contract_files(batch, stages, by_id):
    """`(path, stage)` of the files the plan says the reset stages (and the
    handlers they call) write - `produces` and `updates` - that are on disk."""
    seen, out = set(), []
    todo = list(stages)
    while todo:
        sid = todo.pop(0)
        st = by_id.get(sid) or {}
        for f in list(st.get("produces") or []) + list(st.get("updates") or []):
            hits = sorted(Path(batch).glob(f)) if any(c in f for c in "*?[") else \
                [Path(batch) / f]
            for h in hits:
                rel = str(h.relative_to(batch)) if h.is_relative_to(batch) else str(h)
                if h.exists() and rel not in seen:
                    seen.add(rel)
                    out.append((rel, sid))
        for _code, hid, _then in run_plan.handlers_of(st):
            if hid and hid not in stages and hid not in todo:
                todo.append(hid)
    return out


def _live_runs(batch, st, keys):
    """Run keys among `keys` whose step is still alive (no exit code, its pid
    running): resetting under it would start a second one beside it."""
    out = []
    for k in keys:
        rec = (st.get("runs") or {}).get(k) or {}
        if rec.get("pid") and rec.get("exit") is None and rec.get("exit_file") and \
                rx.pid_alive(rec["pid"], str(Path(batch) / rec["exit_file"])):
            out.append((k, rec["pid"]))
    return out


def rerun_from_check(batch, stage, root=None, now=None, open_rows=None, by=None, via=None):
    """The plan of `rerun_from` - read only. The check's dict (`_base`) plus
    `{task, from_stage, reset: [stage ids, from `stage` to the end of the plan,
    `always` ones included], reset_status: {sid: status before}, keys: {runs:
    [..], reruns, handlers, decisions, code_guard}, logs: [the reset runs'
    logs the re-run overwrites], kept: [{path, stage}: files the reset stages
    wrote - they stay on disk, the re-run overwrites them], moved: [{path,
    stage, guard}: CF-0776, the files a stage-start guard reads that go to
    `before-rerun-<ts>/`], close_rows: [{seq, script_id, pattern_id,
    rhythm_id, rejection_verdict}: CF-0776, the batch's standing rotation rows
    with no video that the reset closes], ledger, ledger_error, lines: [the
    plan for the screen], root}`. `open_rows` stands in for `runlog.open_batches`
    (tests); `by` / `via` are checked when given."""
    batch = _resolve(batch, root)
    st = read_state(batch)
    out = _base("rerun-from", batch, st, root)
    out.update(task=RERUN_TASK, from_stage=stage, reset=[], markers=[], reset_status={},
               keys={k: [] for k in RERUN_KEYS}, logs=[], kept=[], moved=[], close_rows=[],
               moved_blocks=[],
               ledger=None, lines=[], root=None, code=None)
    for value, what in ((by, "by"), (via, "via")):
        why = _who(value, what) if value is not None else None
        if why:
            out["code"] = "bad_who"
            out["reason"] = why
            return out
    if not posix():
        out["code"] = "not_posix"
        out["reason"] = NOT_POSIX
        return out
    if st is None:
        out["code"] = "no_state"
        out["reason"] = f"в {batch} нет {rx.STATE_FILE} - повторять нечего"
        return out
    root = Path(root or st.get("root") or bs.CODE).resolve()
    out["root"] = str(root)
    ex = executor_of(batch, st)
    _with_executor(out, ex)
    out["step"] = step_of(batch, st)
    channel = out["channel"]
    if ex["alive"]:
        out["code"] = "executor_alive"
        out["reason"] = (f"исполнитель pid {ex['pid']} жив - батч идёт; сначала остановить "
                         f"(stop), потом повторять")
        return out
    if ex["lock_held"]:
        out["code"] = "lock_foreign"
        out["reason"] = (f"{rx.LOCK_FILE} держит процесс, не узнанный как исполнитель (в файле "
                         f"pid {ex['pid']}) - отказ, разобраться руками")
        return out
    if not channel:
        out["code"] = "no_channel"
        out["reason"] = f"в {rx.STATE_FILE} нет канала - повторять нечем"
        return out
    try:
        plan = run_plan.load(channel, root)
        if st.get("plan_fingerprint") and st["plan_fingerprint"] != rx.fingerprint(plan):
            out["code"] = "plan_changed"
            out["reason"] = (f"план канала {channel} изменился с начала батча - исполнитель "
                             f"откажется (--plan-changed-ok только руками)")
            return out
        order = run_plan.order(plan)
    except (run_plan.PlanError, ValueError) as e:
        out["code"] = "plan_unreadable"
        out["reason"] = f"план канала {channel} не читается ({e})"
        return out
    by_id = {s["id"]: s for s in plan.get("stages") or []}
    if stage not in order:
        kind = ("обработчик - он повторяется вместе со стадией, что его вызывает"
                if stage in by_id else "такой стадии в плане нет")
        out["code"] = "stage_handler" if stage in by_id else "stage_unknown"
        out["reason"] = f"стадия {stage!r}: {kind} (стадии: {', '.join(order)})"
        return out
    i = order.index(stage)
    opener = next((j for j, sid in enumerate(order) if _opens_the_batch(by_id[sid])), None)
    if opener is not None and i <= opener:
        out["code"] = "stage_opens_batch"
        out["reason"] = (f"повтор с {stage} заново открыл бы журнал (runlog batch-start в "
                         f"{order[opener]}) - это новый батч, а не повтор; повторять можно со "
                         f"стадий после {order[opener]}")
        return out
    stages = st.get("stages") or {}
    status_of = {sid: (stages.get(sid) or {}).get("status") or "pending" for sid in order}
    if status_of[stage] == "pending":
        out["code"] = "stage_not_run"
        out["reason"] = (f"стадия {stage} ещё не шла (pending) - повторять нечего; "
                         f"продолжить: resume")
        return out
    failed = [sid for sid in order[:i] if status_of[sid] == "failed"]
    if failed:
        out["code"] = "earlier_failed"
        out["reason"] = (f"раньше {stage} упала стадия {failed[0]} - после повтора исполнитель "
                         f"снова пропустит всё после неё; повторять с {failed[0]}")
        return out
    reset = order[i:]
    out["reset"] = reset
    out["reset_status"] = {sid: status_of[sid] for sid in reset}
    # CF-0739: the names the journal writes for the reset stages (a stage's
    # `marker`), so that the post-run readers match a reset to its markers
    # without the plan (runlog.reset_names).
    out["markers"] = sorted({by_id[sid]["marker"] for sid in reset
                             if (by_id.get(sid) or {}).get("marker")})
    for part in RERUN_KEYS:
        out["keys"][part] = sorted(k for k in (st.get(part) or {}) if key_stage(k) in reset)
    live = _live_runs(batch, st, out["keys"]["runs"])
    if live:
        k, pid = live[0]
        out["code"] = "step_running"
        out["reason"] = (f"шаг {k} pid {pid} ещё работает - повтор запустил бы второй рядом; "
                         f"сначала дождаться или остановить его (stop --also-step)")
        return out
    out["logs"] = sorted({r["log"] for k in out["keys"]["runs"]
                          if (r := (st.get("runs") or {}).get(k) or {}).get("log")})
    out["moved"] = _guard_files(batch, reset, by_id)
    gone = {m["path"] for m in out["moved"]}
    out["kept"] = [{"path": p, "stage": s} for p, s in _contract_files(batch, reset, by_id)
                   if p not in gone]
    try:
        lpath, lrows = _ledger_rows_to_close(batch, channel, root, reset, by_id)
        out["ledger_error"] = None
    except Exception as e:                                       # noqa: BLE001
        lpath, lrows = None, []
        out["ledger_error"] = f"{e.__class__.__name__}: {e}"
    out["ledger"] = str(lpath) if lpath else None
    out["close_rows"] = [{"seq": int(r["seq"]), "script_id": r["script_id"],
                          "pattern_id": r["pattern_id"], "rhythm_id": r["rhythm_id"],
                          "rejection_verdict": r["rejection_verdict"]} for r in lrows]
    try:
        rows = open_rows if open_rows is not None else _runlog().open_batches(root, now=now)
    except Exception as e:                                       # noqa: BLE001
        out["code"] = "open_unreadable"
        out["reason"] = f"открытые батчи не читаются ({e}) - отказ"
        return out
    others = [r for r in rows if r[2] and Path(r[0]).resolve() != batch]
    if others:
        o = Path(others[0][0])
        out["code"] = "other_batch_open"
        out["reason"] = (f"открыт другой батч {o.parent.name}/{o.name}{_why(others[0])} - "
                         f"один батч за раз, сначала он")
        return out
    ran = [sid for sid in reset if status_of[sid] != "pending"]
    lines = [f"сбросить в pending {len(reset)} стад.: " + ", ".join(
                 f"{sid} ({status_of[sid]})" for sid in reset),
             f"из {rx.STATE_FILE} убрать записи сбрасываемых стадий: " + "; ".join(
                 f"{part} {len(out['keys'][part])}" for part in RERUN_KEYS),
             "файлы, которые писали эти стадии, НЕ удаляются - повтор их перезапишет"]
    if out["moved"]:
        lines.append(f"файлы прошлого прогона, которые читают сторожа stage-start, уносятся в "
                     f"{MOVED_PREFIX}<время>/ (CF-0776): " + ", ".join(
                         f"{m['path']} ({m['guard']})" for m in out["moved"]))
    if out["close_rows"]:
        lines.append(f"журнал ротации: закрыть {len(out['close_rows'])} стоящ. строк(и) батча "
                     f"без ролика - повтор вытянет пары заново (CF-0776): " + ", ".join(
                         f"seq {r['seq']} {r['script_id']} {r['pattern_id']}/{r['rhythm_id']}"
                         for r in out["close_rows"]))
    if out.get("ledger_error"):
        lines.append(f"журнал ротации не читается ({out['ledger_error']}) - строки батча не "
                     f"закрываются; assign повтора вернёт стоящие пары")
    if out["kept"]:
        lines.append("на диске сейчас (повтор перезапишет): " + ", ".join(
            f"{k['path']} ({k['stage']})" for k in out["kept"]))
        lines.append(f"их отпечатки (sha256) пишутся в запись сброса: стадия повтора не "
                     f"засчитывается по файлу прошлого прогона ({PREVIOUS_TASK})")
    stale = [b for b in _stale_blocks(batch, reset, by_id) if b["moved"]]
    out["moved_blocks"] = [{"path": b["path"], "key": b["key"], "entries": len(b["moved"])}
                           for b in stale]
    if stale:
        lines.append(f"записи прошлого прогона в блоках файлов ранних стадий уносятся в "
                     f"{MOVED_PREFIX}<время>/ (копия файла), в файле остаются записи самой "
                     f"ранней стадии ({MOVE_BLOCKS_TASK}): " + ", ".join(
                         f"{b['path']} -> {b['key']}: {len(b['moved'])} зап. ({b['readers']})"
                         for b in stale))
    if out["logs"]:
        lines.append(f"журналы шагов, которые повтор перепишет: {len(out['logs'])} в "
                     f"{rx.LOGS_DIR}/")
    lines.append(f"копия состояния: {rx.STATE_FILE} -> run-state.before-rerun-<время>.json; "
                 f"статус станет {RERUN_STATUS}, next {stage}")
    out["lines"] = lines
    out["ok"] = True
    out["code"] = None
    out["reason"] = (f"батч {batch.name} (статус {out['status']}): повтор с {stage} - "
                     f"{len(reset)} стад. в pending, из них шли {len(ran)}; дальше resume")
    return out


def _backup_name(batch, at):
    """The state's copy `run-state.before-rerun-<stamp>.json` and the directory
    `before-rerun-<stamp>/` the guards' files go to (CF-0776) - one stamp,
    neither taken yet."""
    stamp = at.replace("-", "").replace(":", "")
    tag, n = stamp, 1
    while (Path(batch) / f"run-state.before-rerun-{tag}.json").exists() or \
            (Path(batch) / f"{MOVED_PREFIX}{tag}").exists():
        n += 1
        tag = f"{stamp}-{n}"
    return Path(batch) / f"run-state.before-rerun-{tag}.json"


def _moved_dir(backup):
    """`before-rerun-<stamp>/` of a state copy named by `_backup_name`."""
    tag = backup.name[len("run-state.before-rerun-"):-len(".json")]
    return backup.parent / f"{MOVED_PREFIX}{tag}"


def _move_guard_files(batch, moved, dest):
    """Move `moved` (paths under the batch) into `dest`, keeping their paths.
    All or nothing: on an OSError the ones moved go back and it raises."""
    done = []
    try:
        for rel in moved:
            src, dst = Path(batch) / rel, dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            done.append((src, dst))
    except OSError:
        for src, dst in reversed(done):
            try:
                os.replace(dst, src)
            except OSError:
                pass
        raise


def rerun_from(batch, stage, by, via, confirmed=False, root=None, now=None, open_rows=None,
               note=None, resume_after=False, environ=None, executor=None, executor_args=(),
               take_s=RESUME_TAKE_S):
    """Reset the batch's stages from `stage` to the end of the plan so that
    `resume` runs them again. The check's dict plus `{by, via, note, done,
    backup, moved_to, closed, ledger_error, row, resume}` (`row`: the
    `manual_resets` record; `moved_to`: the `before-rerun-<ts>/` the guards'
    files went to; `closed`: the rotation closure records, CF-0776; `resume`:
    the dict of `resume` when `resume_after`). Nothing is touched unless
    `confirmed` and the check holds - checked again under the tick's lock and
    with the run's lock taken, so no executor starts while the state is
    written."""
    batch = _resolve(batch, root)
    res = {"task": RERUN_TASK, "action": "rerun-from", "ok": False, "batch": str(batch),
           "batch_id": batch.name, "from_stage": stage, "by": by, "via": via, "note": note,
           "done": False, "backup": None, "row": None, "resume": None, "code": None}
    for value, what in ((by, "by"), (via, "via")):
        why = _who(value, what)
        if why:
            res.update(code="bad_who", reason=why)
            return res
    if note is not None and (not isinstance(note, str) or "\n" in note or len(note) > 500):
        res["code"] = "bad_note"
        res["reason"] = "note: одна строка, не длиннее 500 знаков"
        return res
    if not confirmed:
        res.update(rerun_from_check(batch, stage, root, now, open_rows, by, via), ok=False,
                   by=by, via=via, note=note, done=False, code="not_confirmed",
                   reason="не подтверждено: состояние батча не тронуто (нужно подтверждение)")
        return res
    st0 = read_state(batch) or {}
    root_ = Path(root or st0.get("root") or bs.CODE).resolve()
    at = now_iso()
    try:
        with bs._locked(bs.state_dir(root_, environ)):
            chk = rerun_from_check(batch, stage, root_, now, open_rows, by, via)
            res.update(chk, by=by, via=via, note=note, done=False, backup=None, row=None,
                       resume=None)
            if not chk["ok"]:
                return res
            try:
                lock = rx.acquire_lock(batch)
            except rx.Refused as e:
                res.update(ok=False, code="locked", reason=f"отказ: {e}")
                return res
            try:
                st = read_state(batch)
                if st is None:
                    res.update(ok=False, code="state_gone",
                               reason=f"{rx.STATE_FILE} пропал - отказ")
                    return res
                try:
                    by_id_ = {s["id"]: s for s in
                              run_plan.load(chk["channel"], root_).get("stages") or []}
                except (run_plan.PlanError, ValueError):
                    by_id_ = {}
                # CF-0784: the stale blocks' run-before part is moved, not
                # fingerprinted - what stays in the block is the earlier
                # stage's own and is read as it is
                stale = _stale_blocks(batch, chk["reset"], by_id_)
                backup = _backup_name(batch, at)
                moved = [m["path"] for m in chk.get("moved") or []]
                dest = _moved_dir(backup)
                try:
                    moved_blocks = _move_stale_blocks(batch, stale, dest)
                except (OSError, ValueError) as e:
                    res.update(ok=False, code="locked",
                               reason=f"блоки прошлого прогона не перенесены в {dest.name} "
                                      f"({e}) - отказ, ничего не тронуто")
                    return res
                try:
                    _move_guard_files(batch, moved, dest)
                except OSError as e:
                    for b in moved_blocks:
                        try:
                            shutil.copy2(dest / b["path"], batch / b["path"])
                        except OSError:
                            pass
                    res.update(ok=False, code="locked",
                               reason=f"файлы прошлого прогона не перенесены в {dest.name} "
                                      f"({e}) - отказ, ничего не тронуто")
                    return res
                # CF-0801: fingerprinted after the stale part left - a kept file
                # the reset stripped (06 after the round) is still the run
                # before's, and its bytes are now these
                previous = _previous_record(batch, chk.get("kept") or [], [])
                shutil.copy2(batch / rx.STATE_FILE, backup)
                reset = chk["reset"]
                for sid in reset:
                    st.setdefault("stages", {})[sid] = {"status": "pending"}
                for part in RERUN_KEYS:
                    d = st.get(part)
                    if isinstance(d, dict):
                        for k in [k for k in d if key_stage(k) in reset]:
                            del d[k]
                prev = st.get("status")
                st["status"] = RERUN_STATUS
                st["next"] = stage
                st["current"] = None
                st.pop("halt_reason", None)
                row = {"at": at, "by": by, "via": via, "task": RERUN_TASK, "from": stage,
                       "reset": reset, "markers": chk.get("markers") or [],
                       "previous_status": prev,
                       "reset_status": chk["reset_status"],
                       "removed": {p: len(chk["keys"][p]) for p in RERUN_KEYS},
                       "backup": backup.name, "why": note,
                       "moved": moved,
                       "moved_to": dest.name if moved or moved_blocks else None,
                       "moved_blocks": moved_blocks,
                       "close_rows": [r["seq"] for r in chk.get("close_rows") or []],
                       "previous_run": previous}
                st.setdefault("manual_resets", []).append(row)
                rx.write_json_atomic(batch / rx.STATE_FILE, st)
                closed, ledger_error = _close_ledger_rows(batch, chk, by, via, stage, note,
                                                          backup.name, at)
            finally:
                lock.close()
    except bs.ScheduleError as e:
        res.update(ok=False, code="locked", reason=f"отказ: {e}")
        return res
    res.update(ok=True, code=None, done=True, backup=str(backup), row=row, status=RERUN_STATUS,
               moved_to=str(dest) if moved or moved_blocks else None, closed=closed,
               ledger_error=ledger_error, moved_blocks=moved_blocks,
               reason=(f"батч {batch.name}: стадии с {stage} сброшены ({len(reset)}, {by} через "
                       f"{via}); копия {backup.name}"
                       + (f"; файлы прошлого прогона ({len(moved)}) в {dest.name}/"
                          if moved else "")
                       + ("; записи прошлого прогона в блоках (" + ", ".join(
                           f"{b['path']} -> {b['key']}: {b['entries']}" for b in moved_blocks)
                          + f") в {dest.name}/" if moved_blocks else "")
                       + (f"; строк ротации закрыто: {len(closed)} (seq "
                          + ", ".join(str(c["seq"]) for c in closed) + ")" if closed else "")
                       + (f"; журнал ротации не закрыт: {ledger_error}" if ledger_error else "")
                       + "; продолжить: resume"))
    journal_event(batch, EV_RERUN, by, res["reason"],
                  {"from": stage, "reset": reset, "markers": row["markers"], "via": via,
                   "backup": backup.name, "previous_status": prev, "why": note,
                   "moved": moved, "moved_to": row["moved_to"],
                   "moved_blocks": moved_blocks,
                   "closed": [c["seq"] for c in closed], "ledger_error": ledger_error},
                  task=RERUN_TASK)
    if resume_after:
        r = resume(batch, by, True, root_, now, environ, executor, open_rows, executor_args,
                   take_s)
        res["resume"] = r
        res["ok"] = bool(r.get("ok"))
        res["code"] = None if res["ok"] else "resume_failed"
        res["reason"] += f"; resume: {r.get('reason')}"
    return res


# --------------------------------------------------------------------------
# rebuild (CF-0668)
# --------------------------------------------------------------------------

REBUILD_TASK = "CF-0668"
CLOSED = ("done", "failed")             # a run-state that ended: the batch can be rebuilt
_EXCLUDE = re.compile(r"^\d+(=\S+)?$")  # resolve_anchors --exclude-candidate BLOCK[=SOURCE:SHOT]
# Not copied from the source's work/<slug>/: a rebuild's renders are attempts of
# its own ledger (the 2026-10-09T1208Z rebuild's ledgers start at attempt 1),
# the judge's frames are the old video's, a lock is a process's, a refusal
# sidecar is the old video's verdict (CF-0727: the editor's write_batch_metadata
# collects every work/*/*.refusal.json - a copied one would refuse the re-edit
# before its own gates have said a word).
WORK_SKIP = ("attempts.json", "frame-judge", "*.lock", ".*.lock", "*.refusal.json")
# CF-0727: a 05 refusal names only its script - the work files the editor
# writes with `script_id` in them, cheapest first, name its work/<slug>/.
SCRIPT_ID_FILES = ("order.json", "plan_check_loop.json", "plan_check.json", "anchors.json",
                   "plan.score.json", "storyboard.json")


def _read_json(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _work_slugs(batch, script_ids):
    """CF-0727: `{script_id: slug}` of these scripts off `work/<slug>/` - the
    first of SCRIPT_ID_FILES (then a refusal sidecar) that names a script names
    the directory's. Two directories of one script (refused twice under two
    names): the one with a plan, the newer plan first."""
    found = {}
    work = Path(batch) / "work"
    for d in (sorted(p for p in work.iterdir() if p.is_dir()) if work.is_dir() else []):
        sid = None
        for f in [*(d / n for n in SCRIPT_ID_FILES), *sorted(d.glob("*.refusal.json"))]:
            sid = (_read_json(f) or {}).get("script_id") if f.is_file() else None
            if sid:
                break
        if sid in script_ids:
            plan = d / "plan.json"
            found.setdefault(sid, []).append(
                (plan.is_file(), plan.stat().st_mtime if plan.is_file() else 0.0, d.name))
    return {sid: max(c)[2] for sid, c in found.items()}


def _source_videos(batch):
    """`[{slug, script_id, topic_id, refused, plan}]` of a batch's 05 (topic off
    its 03). CF-0727: a video refused after the render sits in 05 `refusals[]`,
    not `videos[]` - and those are the ones most often rebuilt (refused by QC,
    the cause fixed). Every refusal whose script is in 03 is one too, `refused`
    its gate (None for a video of `videos[]`), its slug off `output_path` or its
    `work/<slug>/`; `plan`: `work/<slug>/plan.json` is there."""
    d05 = _read_json(Path(batch) / "05-video-editor.json") or {}
    d03 = _read_json(Path(batch) / "03-content-researcher.json") or {}
    topics = {s.get("script_id"): s.get("topic_id") for s in d03.get("scripts") or []
              if isinstance(s, dict)}
    out = []
    for v in d05.get("videos") or []:
        if not isinstance(v, dict) or not v.get("script_id"):
            continue
        slug = Path(str(v.get("output_path") or "")).stem or None
        out.append({"slug": slug, "script_id": v["script_id"],
                    "topic_id": topics.get(v["script_id"]), "refused": None})
    seen = {v["script_id"] for v in out}
    refused = {}
    for r in d05.get("refusals") or []:
        sid = r.get("script_id") if isinstance(r, dict) else None
        if sid and sid in topics and sid not in seen:
            refused[sid] = r                    # the last per script, as the editor merges
    slugs = _work_slugs(batch, set(refused)) if refused else {}
    for sid, r in refused.items():
        slug = Path(str(r.get("output_path") or "")).stem or slugs.get(sid)
        out.append({"slug": slug, "script_id": sid, "topic_id": topics.get(sid),
                    "refused": r.get("gate") or r.get("reason_code") or "refused"})
    for v in out:
        v["plan"] = bool(v["slug"]) and (Path(batch) / "work" / v["slug"] / "plan.json").is_file()
    return out


def _notes_of(notes):
    """`(text, {video key: {exclude: [..], note}})` of `notes`: None, a text,
    or `{"text": .., "videos": {slug|script_id: text | {exclude, note}}}`."""
    if notes is None:
        return "", {}
    if isinstance(notes, str):
        return notes.strip(), {}
    if not isinstance(notes, dict):
        raise ValueError("notes: текст или {text, videos}")
    per = {}
    for k, v in (notes.get("videos") or {}).items():
        if isinstance(v, str):
            per[k] = {"exclude": [], "note": v.strip()}
        elif isinstance(v, dict):
            ex = v.get("exclude") or []
            if isinstance(ex, (str, int)):
                ex = [ex]
            per[k] = {"exclude": [str(x).strip() for x in ex], "note": str(v.get("note") or "").strip()}
        else:
            raise ValueError(f"notes.videos.{k}: текст или {{exclude, note}}")
    return str(notes.get("text") or "").strip(), per


def _live_rebuilds(root, but=None):
    """Rebuild directories whose executor is alive (a rebuild between two
    stages may have no open marker - its live executor still holds it)."""
    out = []
    for d in sorted((Path(root) / "pipeline" / run_plan.REBUILDS_GROUP).glob("*/")):
        if but is not None and d.resolve() == Path(but).resolve():
            continue
        if (d / rx.LOCK_FILE).exists() and executor_of(d)["alive"]:
            out.append(d)
    return out


def _why(row):
    """` (<why>)` of an open row for a refusal line, '' from a stand-in (CF-0670)."""
    why = getattr(row, "why", None)
    return f" ({why})" if why else ""


def _work_ignore(_dir, names):
    import fnmatch  # noqa: PLC0415
    return {n for n in names for pat in WORK_SKIP if fnmatch.fnmatch(n, pat)}


def rebuild_check(batch, videos, mode, root=None, now=None, open_rows=None, notes=None):
    """Can these videos of a finished batch be rebuilt in this mode - read
    only. `{ok, reason, task, action, batch, batch_id, channel, mode, title,
    from_stage, layout {copied, skipped, run}, copy, only_videos, work, videos
    [{slug, script_id, topic_id, refused, plan, exclude, note}], rebuild_of {channel, batch_id,
    path}, root, posix}`. `open_rows` stands in for `runlog.open_batches`."""
    batch = _resolve(batch, root)
    out = {"task": REBUILD_TASK, "action": "rebuild", "ok": False, "reason": "",
           "batch": str(batch), "batch_id": batch.name, "channel": None, "mode": mode,
           "title": None, "from_stage": None, "layout": None, "copy": [], "only_videos": [],
           "work": [], "videos": [], "rebuild_of": None, "root": None, "posix": posix()}
    if not posix():
        out["reason"] = NOT_POSIX
        return out
    if not batch.is_dir():
        out["reason"] = f"нет каталога батча {batch}"
        return out
    d05 = _read_json(batch / "05-video-editor.json")
    d03 = _read_json(batch / "03-content-researcher.json") or {}
    if d05 is None:
        out["reason"] = f"в {batch.name} нет 05-video-editor.json - пересобирать нечего"
        return out
    st = read_state(batch)
    root = Path(root or (st or {}).get("root") or batch.parent.parent.parent).resolve()
    out["root"] = str(root)
    channel = channel_ids.resolve_channel(d03.get("channel") or d05.get("channel")
                                          or (st or {}).get("channel"), root)
    out["channel"] = channel
    if not channel:
        out["reason"] = "батч не называет канал (03/05 без channel)"
        return out
    try:
        plan = run_plan.load(channel, root)
    except run_plan.PlanError as e:
        out["reason"] = f"план канала {channel} не читается ({e})"
        return out
    modes = run_plan.rebuild_modes(plan)
    if mode not in modes:
        out["reason"] = (f"у плана {channel} нет режима пересборки {mode!r} (есть: "
                         f"{', '.join(sorted(modes)) or 'никаких'})")
        return out
    errs = run_plan.validate(plan, root)
    if errs:
        out["reason"] = f"план канала {channel} не проходит проверку: {errs[0]}"
        return out
    spec = modes[mode]
    out.update(title=spec["title"], from_stage=spec["from"],
               layout=run_plan.rebuild_layout(plan, mode), copy=list(spec["copy"]),
               only_videos=list(spec.get("only_videos") or []), work=list(spec.get("work") or []))
    # the source is closed
    if st is not None:
        ex = executor_of(batch, st)
        if ex["alive"]:
            out["reason"] = f"батч {batch.name} ещё идёт (исполнитель pid {ex['pid']}) - не закрыт"
            return out
        if st.get("status") not in CLOSED:
            out["reason"] = (f"батч {batch.name} не закрыт (статус {st.get('status')}) - "
                             f"сначала закончить или продолжить его")
            return out
    try:
        rows = open_rows if open_rows is not None else _runlog().open_batches(root, now=now)
    except Exception as e:                                       # noqa: BLE001
        out["reason"] = f"открытые батчи не читаются ({e}) - отказ"
        return out
    fresh = [r for r in rows if r[2]]
    mine = [r for r in fresh if Path(r[0]).resolve() == batch]
    if mine:
        why = getattr(mine[0], "why", None) or "нет batch-done"
        out["reason"] = f"батч {batch.name} ещё открыт ({why}) - не закрыт"
        return out
    seen = {Path(r[0]).resolve() for r in fresh}
    others = fresh + [_runlog().OpenRow(d, None, True, _xl().why(_xl().holder(d)))
                      for d in _live_rebuilds(root) if d.resolve() not in seen]
    if others:
        o = Path(others[0][0])
        out["reason"] = (f"открыт другой батч или пересборка {o.parent.name}/{o.name}"
                         f"{_why(others[0])} - "
                         f"батчи по одному, сначала он")
        return out
    # the videos
    try:
        text, per = _notes_of(notes)
    except ValueError as e:
        out["reason"] = str(e)
        return out
    wanted = [str(v).strip() for v in (videos or []) if str(v).strip()]
    if not wanted:
        out["reason"] = "не названо ни одного ролика"
        return out
    have = _source_videos(batch)
    chosen = []
    for key in wanted:
        hit = [v for v in have if key in (v["slug"], v["script_id"])]
        if len(hit) != 1:
            out["reason"] = (f"ролика {key!r} нет в батче {batch.name} (есть: "
                             f"{', '.join(_named(v) for v in have) or 'ничего'})")
            return out
        if hit[0]["refused"] and not hit[0]["plan"] and any(
                "{slug}" in w for w in spec.get("work") or []):
            where = f"work/{hit[0]['slug']}/plan.json" if hit[0]["slug"] else "work/<slug>/"
            out["reason"] = (f"ролик {key!r} отказан до плана ({hit[0]['refused']}): нет "
                             f"{where} - режиму {mode} пересобирать не из чего")
            return out
        if any(c["script_id"] == hit[0]["script_id"] for c in chosen):
            out["reason"] = f"ролик {key!r} назван дважды"
            return out
        chosen.append(dict(hit[0], exclude=[], note=""))
    for key, v in per.items():
        hit = [c for c in chosen if key in (c["slug"], c["script_id"])]
        if not hit:
            out["reason"] = f"замечание к ролику {key!r}, которого нет среди пересобираемых"
            return out
        hit[0]["exclude"] += v["exclude"]
        hit[0]["note"] = v["note"]
    takes_exclusions = any("{exclusions}" in t for a in (spec.get("args") or {}).values()
                           for t in a.values())
    for c in chosen:
        if not c["exclude"]:
            continue
        if not takes_exclusions:
            out["reason"] = (f"режим {mode} не исключает кадры (это только у перемонтажа), "
                             f"а для {c['slug']} они названы")
            return out
        bad = [x for x in c["exclude"] if not _EXCLUDE.match(x)]
        if bad:
            out["reason"] = (f"{c['slug']}: исключение {bad[0]!r} - нужно BLOCK или "
                             f"BLOCK=SOURCE:SHOT (как --exclude-candidate)")
            return out
        sb = _read_json(batch / "work" / str(c["slug"]) / "storyboard.json")
        if sb is None:
            out["reason"] = (f"{c['slug']}: нет work/{c['slug']}/storyboard.json - исключать "
                             f"кадры не из чего")
            return out
        n = len(sb.get("blocks") or [])
        over = [x for x in c["exclude"] if int(x.split("=")[0]) >= n]
        if over:
            out["reason"] = f"{c['slug']}: блока {over[0]} нет (в раскадровке блоки 0-{n - 1})"
            return out
    out["videos"] = chosen
    out["notes"] = text
    missing = [f for f in spec["copy"] if not (batch / f).is_file()]
    if missing:
        out["reason"] = f"в {batch.name} нет {', '.join(missing)} - копировать нечего"
        return out
    src_id = d03.get("batch_id") or (_read_json(batch / "01-trend-hunter.json") or {}).get(
        "batch_id") or batch.name
    try:
        rel = str(batch.relative_to(root))
    except ValueError:
        rel = None
    out["rebuild_of"] = {"channel": channel, "batch_id": src_id, "path": rel}
    out["ok"] = True
    out["reason"] = (f"можно: {spec['title']} - {len(chosen)} ролик(а) "
                     f"({', '.join(c['slug'] or c['script_id'] for c in chosen)}) из "
                     f"{channel}/{batch.name}, с {spec['from']}")
    return out


def _named(v):
    """A source video as the refusal lines list it (CF-0727: a refused one says so)."""
    name = v["slug"] or v["script_id"]
    return f"{name} (отказан: {v['refused']})" if v.get("refused") else name


def _fill(template, values):
    return run_plan._PH.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def rebuild_values(chk):
    """The rebuild placeholders of a passed check, as text."""
    vids = chk["videos"]
    ex = [f"{v['slug']}: " + " ".join(f"--exclude-candidate {x}" for x in v["exclude"])
          for v in vids if v["exclude"]]
    notes = ([chk.get("notes")] if chk.get("notes") else []) + \
        [f"{v['slug']}: {v['note']}" for v in vids if v["note"]]
    src = chk["rebuild_of"]
    return {"source": f"{src['channel']}/{src['batch_id']}",
            "videos": ", ".join(v["slug"] or v["script_id"] for v in vids),
            "scripts": ", ".join(v["script_id"] for v in vids),
            "topics": ", ".join(str(v["topic_id"]) for v in vids if v["topic_id"]) or "-",
            "exclusions": "; ".join(ex) or "none",
            "notes": "; ".join(notes) or "none"}


def _opens_the_batch(st):
    return st.get("kind") == "machine" and any(
        "batch-start" in (step.get("argv") or [])[1:2] for step in st.get("steps") or [])


def make_rebuild(chk, dest, plan):
    """Copy the source into `dest` and return the starting run-state (not yet
    written). `chk` is a passed `rebuild_check`."""
    src = Path(chk["batch"])
    keep = {v["script_id"] for v in chk["videos"]}
    dest.mkdir(parents=True)
    copied = []
    for f in chk["copy"]:
        if f in chk["only_videos"]:
            doc = json.loads((src / f).read_text(encoding="utf-8"))
            for key in run_plan.REBUILD_FILTERED:
                if isinstance(doc.get(key), list):
                    doc[key] = [x for x in doc[key]
                                if not isinstance(x, dict) or x.get("script_id") in keep]
            (dest / f).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        else:
            shutil.copy2(src / f, dest / f)
        copied.append(f)
    work = []
    for pat in chk["work"]:
        for rel in dict.fromkeys(pat.replace("{slug}", str(v["slug"])) for v in chk["videos"]):
            s, d = src / "work" / rel, dest / "work" / rel
            if s.is_dir():
                shutil.copytree(s, d, symlinks=True, ignore=_work_ignore)
            elif s.is_file():
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
            else:
                continue
            work.append(f"work/{rel}")
    order = run_plan.order(plan)
    by_id = {s["id"]: s for s in plan["stages"]}
    root = Path(chk["root"])
    st = rx.new_state(root, chk["channel"], plan, dest, order)
    lay, mode, src_id = chk["layout"], chk["mode"], chk["rebuild_of"]["batch_id"]
    for sid in lay["copied"]:
        why = (f"rebuild {mode}: opened by batch_control.rebuild (batch-start --note)"
               if _opens_the_batch(by_id[sid]) else
               f"rebuild {mode}: before `{chk['from_stage']}` - the records are "
               f"{chk['channel']}/{src_id}'s, copied")
        st["stages"][sid] = {"status": "skipped", "reason": why, "ended": rx.now_iso()}
    for sid in lay["skipped"]:
        st["stages"][sid] = {"status": "skipped", "ended": rx.now_iso(),
                             "reason": f"rebuild {mode}: not in a rebuild (no batch-done, CF-0339)"}
    st["next"] = lay["run"][0] if lay["run"] else None
    values = rebuild_values(chk)
    spec = run_plan.rebuild_modes(plan)[mode]
    st["rebuild"] = {
        "task": REBUILD_TASK, "mode": mode, "title": chk["title"], "of": chk["rebuild_of"],
        "videos": chk["videos"], "notes": chk.get("notes") or "", "copied": copied,
        "work": work, "values": values,
        "args": {sid: {k: _fill(v, values) for k, v in a.items()}
                 for sid, a in (spec.get("args") or {}).items()}}
    return st


def _batch_start(root, dest, note, environ=None):
    """`runlog batch-start --batch DEST --note NOTE`: `(rc, output)`."""
    env = dict(os.environ if environ is None else environ)
    env.pop("RUNLOG_BATCH", None)
    try:
        cp = subprocess.run([str(Path(root) / "scripts" / "runlog"), "batch-start", "--batch",
                             str(dest), "--note", note], capture_output=True, text=True,
                            timeout=300, cwd=str(root), env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def rebuild(batch, videos, mode, by, confirmed=False, notes=None, root=None, now=None,
            environ=None, executor=None, open_rows=None, executor_args=(),
            take_s=RESUME_TAKE_S, dry_run=False):
    """Rebuild these videos of a finished batch: `pipeline/rebuilds/<ts>`, the
    copies, `batch-start --note`, the starting `run-state.json`, the executor
    detached on `--resume` of it. The check's dict plus `{by, rebuild_dir,
    rebuild_id, started, pid, log, row, exit, state, batch_start, dry_run}`.
    Nothing is made unless `confirmed` and the check holds - checked again
    under the tick's lock. `dry_run`: the directory and the state are made
    (no batch-start, no start), the executor's `--dry-run --resume` output is
    `dry_run` (lines)."""
    batch = _resolve(batch, root)
    res = {"task": REBUILD_TASK, "action": "rebuild", "ok": False, "batch": str(batch),
           "batch_id": batch.name, "mode": mode, "by": by, "started": False,
           "rebuild_dir": None, "rebuild_id": None, "pid": None, "log": None, "row": None,
           "exit": None, "batch_start": None, "dry_run": None}
    if not by or not str(by).strip():
        res["reason"] = "нужно указать, кто пересобирает (by)"
        return res
    if not confirmed:
        res.update(rebuild_check(batch, videos, mode, root, now, open_rows, notes),
                   ok=False, by=by, started=False,
                   reason="не подтверждено: пересборка не начата (нужно подтверждение)")
        return res
    chk0 = rebuild_check(batch, videos, mode, root, now, open_rows, notes)
    if not chk0["ok"]:
        res.update(chk0, by=by, started=False)
        return res
    root_ = Path(chk0["root"])
    at = now_iso()
    day = bs.msk_day(bs.now_utc(now)).isoformat()
    try:
        with bs._locked(bs.state_dir(root_, environ)):
            chk = rebuild_check(batch, videos, mode, root_, now, open_rows, notes)
            res.update(chk, by=by, started=False)
            if not chk["ok"]:
                return res
            rid = bs.now_utc(now).strftime("%Y-%m-%dT%H%MZ")
            dest = root_ / "pipeline" / run_plan.REBUILDS_GROUP / rid
            res.update(rebuild_id=rid, rebuild_dir=str(dest))
            if dest.exists():
                res.update(ok=False, reason=f"{dest} уже есть - пересборка в эту минуту уже "
                                            f"начата, повторить через минуту")
                return res
            plan = run_plan.load(chk["channel"], root_)
            try:
                st = make_rebuild(chk, dest, plan)
            except OSError as e:
                shutil.rmtree(dest, ignore_errors=True)
                res.update(ok=False, reason=f"копии не сделаны ({e}) - каталог убран")
                return res
            vals = st["rebuild"]["values"]
            note = (f"rebuild {mode} of {vals['source']} ({REBUILD_TASK}, {by}): {vals['videos']}"
                    + (f"; exclusions {vals['exclusions']}" if vals["exclusions"] != "none" else "")
                    + (f"; {vals['notes']}" if vals["notes"] != "none" else ""))
            st["rebuild"].update(by=by, at=at, note=note)
            if dry_run:
                res["batch_start"] = {"note": note, "skipped": "dry run"}
            else:
                rc, said = _batch_start(root_, dest, note, environ)
                res["batch_start"] = {"note": note, "exit": rc, "said": said.strip()[-500:]}
                if rc != 0:
                    shutil.rmtree(dest, ignore_errors=True)
                    res.update(ok=False, reason=(f"batch-start отказал (exit {rc}): "
                                                 f"{said.strip()[-300:]} - каталог убран"))
                    return res
            rx.write_json_atomic(dest / rx.STATE_FILE, st)
            res["state"] = str(dest / rx.STATE_FILE)
            argv = _executor_argv(chk["channel"], root_, dest, executor, executor_args)
            res["argv"] = argv
            if dry_run:
                try:
                    cp = subprocess.run([*argv, "--dry-run"], capture_output=True, text=True,
                                        timeout=120, cwd=str(root_))
                except (OSError, subprocess.SubprocessError) as e:
                    res.update(ok=False, reason=f"сухой прогон исполнителя не прошёл ({e})")
                    return res
                res["dry_run"] = (cp.stdout or "").splitlines()
                res.update(exit=cp.returncode, ok=cp.returncode == rx.EXIT_DONE,
                           reason=(f"сухой прогон: {dest} готов, исполнитель не запускался"
                                   if cp.returncode == rx.EXIT_DONE else
                                   f"сухой прогон исполнителя: exit {cp.returncode} "
                                   f"{(cp.stderr or '').strip()[-300:]}"))
                return res
            try:
                proc, log = bs.spawn_detached(argv, root_, day, chk["channel"], environ)
            except OSError as e:
                res.update(ok=False, reason=(f"пересборка {rid} открыта, но исполнитель не "
                                             f"стартовал ({e}) - продолжить: resume"))
                return res
            row = {"at": at, "day": day, "channel": chk["channel"], "pid": proc.pid,
                   "argv": argv, "log": str(log), "kind": "rebuild", "batch": str(dest),
                   "mode": mode, "rebuild_of": chk["rebuild_of"],
                   "videos": [v["slug"] or v["script_id"] for v in chk["videos"]], "by": by,
                   "why": f"пересборка ({mode}) {vals['videos']} из {vals['source']}",
                   "task": REBUILD_TASK}
            bs.journal_launch(row, root_, environ)
            _wait(lambda: proc.poll() is not None or
                  (lock_held(dest) and _lock_pid(dest) == proc.pid), take_s)
    except bs.ScheduleError as e:
        res.update(ok=False, reason=f"отказ: {e}")
        return res
    res.update(pid=proc.pid, log=str(log), row=row, started=True)
    code = proc.poll()
    if code is None:
        res.update(ok=True, reason=(f"пересборка {rid} ({mode}) начата ({by}): {vals['videos']} "
                                    f"из {vals['source']}; исполнитель pid {proc.pid}, журнал {log}"))
    else:
        res.update(exit=code, ok=code in (rx.EXIT_DONE, rx.EXIT_FAILED, rx.EXIT_PAUSED),
                   reason=(f"исполнитель пересборки {rid} pid {proc.pid} сразу закончил с "
                           f"кодом {code} (журнал {log})"))
    _notify("batch_started", f"rebuild:{rid}",
            f"🔁 {_label(chk['channel'], root_)}: пересборка ({mode}) — {vals['videos']} из батча "
            f"{_day(chk['rebuild_of']['batch_id'])} ({by})", chk["channel"], root_, environ)
    return res


# --------------------------------------------------------------------------
# seconds -> blocks (CF-0669)
# --------------------------------------------------------------------------

BLOCKS_TASK = "CF-0669"
NEAR_S = 0.5    # a remark's second is rounded: closer than this to a cut, the neighbour is named too


def _moment_shots(asset, block, off):
    """The shots on screen `off` seconds into a plan block: every side of a
    split (both are on screen), the cut a sequence is on, else the block's own."""
    def at_cut(part):
        cuts = [c for c in (part.get("cuts") or []) if isinstance(c, dict)]
        hit = [c for c in cuts if float(c.get("from_seconds") or 0) <= off
               < float(c.get("from_seconds") or 0) + float(c.get("seconds") or 0)]
        pick = hit[0] if hit else (cuts[-1] if cuts else None)
        return (pick or {}).get("shot") or part.get("shot")
    sides = [s for s in (asset.get("sides") or []) if isinstance(s, dict)]
    if sides:
        return [x for x in (at_cut(s) for s in sides) if x]
    shot = at_cut(asset) or block.get("shot")
    return [shot] if shot else []


def _block_exclude(blocks, j, t):
    """`J=SOURCE:SHOT` for the moment of block j nearest to `t`, None for a split
    or a block without a shot."""
    blk = blocks[j]
    asset = blk.get("asset") if isinstance(blk.get("asset"), dict) else {}
    if asset.get("sides"):
        return None
    start, end = float(blk.get("start") or 0), float(blk.get("end") or 0)
    off = min(max(t, start), max(start, end - 1e-3)) - start
    shots = _moment_shots(asset, blk, off)
    return f"{j}={shots[0]}" if shots else None


def blocks_at(batch, slug, seconds, root=None):
    """CF-0669: which block of a finished video a second of it falls in - the
    bridge from a remark («12 с мыло») to `rebuild`'s exclusions.

    Reads `work/<slug>/plan.json` (the time each block takes on screen; plan
    block N is storyboard block N, the index `--exclude-candidate` takes).
    Returns `{ok, reason, batch, slug, plan, duration, moments, exclude}`:
    `moments` one per second asked, `{at, block, window: [start, end], kind,
    shots: ["SOURCE:SHOT", ..], ending, exclude, near}` - `block` None and `ending`
    True inside the channel's end card, both None/False past the end (`note`
    says so); `exclude` is `BLOCK=SOURCE:SHOT` for that moment, or None where
    `--exclude-candidate` would refuse (a split, a block with no shot, the
    ending) with the why in `note`. The top-level `exclude` is the distinct
    exclusions in order - `notes.videos[slug].exclude` of `rebuild()` as is,
    `--exclude SLUG:<each>` on its CLI. A second on a boundary belongs to the
    block that starts there; a remark's second is rounded, so `near` names
    the neighbouring block (`{block, exclude}`, not in the top-level list)
    when the second is closer than NEAR_S to the cut between them - CF-0646's
    «12 с» is the end of block 4, 0.41 s before block 5. Nothing is written.
    """
    b = _resolve(batch, root)
    out = {"ok": False, "reason": "", "batch": str(b), "slug": slug, "task": BLOCKS_TASK,
           "moments": [], "exclude": []}
    key = str(slug or "").strip()
    hit = [v for v in _source_videos(b) if key and key in (v["slug"], v["script_id"])]
    if len(hit) == 1 and hit[0]["slug"]:
        key = hit[0]["slug"]
    plan_path = b / "work" / key / "plan.json"
    plan = _read_json(plan_path) if key else None
    if plan is None:
        out["reason"] = f"нет плана ролика {slug!r}: {plan_path}"
        return out
    out.update(slug=key, plan=str(plan_path))
    blocks = [x for x in (plan.get("blocks") or []) if isinstance(x, dict)]
    card = plan.get("end_card") if isinstance(plan.get("end_card"), dict) else {}
    voice_end = max([float(x.get("end") or 0) for x in blocks] or [0.0])
    card_start = float(card.get("start_s") if card.get("start_s") is not None else voice_end)
    card_end = card_start + float(card.get("seconds") or 0)
    out["duration"] = round(max(voice_end, card_end), 3)
    try:
        asked = [float(s) for s in seconds]
    except (TypeError, ValueError):
        out["reason"] = f"секунды должны быть числами: {seconds!r}"
        return out
    for t in asked:
        m = {"at": t, "block": None, "window": None, "kind": None, "shots": [],
             "ending": False, "exclude": None, "near": []}
        inside = [(i, x) for i, x in enumerate(blocks)
                  if float(x.get("start") or 0) <= t < float(x.get("end") or 0)]
        if inside:
            i, blk = inside[0]
            asset = blk.get("asset") if isinstance(blk.get("asset"), dict) else {}
            start, end = float(blk.get("start") or 0), float(blk.get("end") or 0)
            shots = _moment_shots(asset, blk, t - start)
            m.update(block=i, window=[start, end], kind=asset.get("kind"), shots=shots)
            if asset.get("sides"):
                m["note"] = ("сплит: --exclude-candidate его не исключает (нет своего шота) - "
                             "перемонтаж с замечанием")
            elif not shots:
                m["note"] = "в блоке нет шота (карточка) - исключать нечего"
            else:
                m["exclude"] = f"{i}={shots[0]}"
            for j, edge in ((i - 1, t - start), (i + 1, end - t)):
                if 0 <= j < len(blocks) and edge < NEAR_S:
                    m["near"].append({"block": j, "exclude": _block_exclude(blocks, j, t)})
        elif card_end > card_start and card_start <= t < card_end:
            m.update(ending=True, window=[card_start, card_end], kind="end_card",
                     note="концовка канала - не кадр ролика, исключать нечего")
        else:
            m["note"] = f"вне ролика (0-{out['duration']} с)"
        out["moments"].append(m)
        if m["exclude"] and m["exclude"] not in out["exclude"]:
            out["exclude"].append(m["exclude"])
    out["ok"] = True
    out["reason"] = (f"{key}: " + ", ".join(
        f"{m['at']:g} с - " + (f"блок {m['block']}" if m["block"] is not None
                               else "концовка" if m["ending"] else "вне ролика")
        for m in out["moments"]))
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None, out=sys.stdout, err=sys.stderr):
    ap = argparse.ArgumentParser(prog="batch_control.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("stop", "resume"):
        p = sub.add_parser(name)
        p.add_argument("--batch", required=True, help="the batch directory")
        p.add_argument("--by", default=None, help="who (user, ...)")
        p.add_argument("--root", default=None, help="the factory tree (default: the batch's)")
        p.add_argument("--confirm", action="store_true", help="do it (without: only the check)")
        p.add_argument("--check", action="store_true", help="only the check, even with --confirm")
        p.add_argument("--json", action="store_true")
        if name == "stop":
            p.add_argument("--also-step", action="store_true",
                           help="SIGTERM to the step being run too (--resume starts it again)")
            p.add_argument("--grace-s", type=float, default=GRACE_S)
    p = sub.add_parser("rebuild", help="CF-0668: rebuild chosen videos of a finished batch")
    p.add_argument("--batch", required=True, help="the source batch directory")
    p.add_argument("--video", action="append", required=True,
                   help="a video to rebuild: its slug or script id (repeatable)")
    p.add_argument("--mode", required=True, help="a rebuild mode of the channel's plan "
                                                 "(reedit | rewrite)")
    p.add_argument("--by", default=None, help="who (user, ...)")
    p.add_argument("--root", default=None, help="the factory tree (default: the batch's)")
    p.add_argument("--exclude", action="append", default=[], metavar="SLUG:BLOCK[=SHOT]",
                   help="a frame to exclude (resolve_anchors --exclude-candidate), reedit only")
    p.add_argument("--note", default=None, help="the remark, into batch-start --note and the prompts")
    p.add_argument("--video-note", action="append", default=[], metavar="SLUG:TEXT")
    p.add_argument("--confirm", action="store_true", help="do it (without: only the check)")
    p.add_argument("--check", action="store_true", help="only the check, even with --confirm")
    p.add_argument("--dry-run", action="store_true",
                   help="make the directory and the state, no batch-start, the executor --dry-run")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("rerun-from", help="CF-0739: reset the stages from STAGE to the end "
                                          "so that resume runs them again")
    p.add_argument("--batch", required=True, help="the batch directory")
    p.add_argument("--stage", required=True, help="the first stage to run again (a plan stage id)")
    p.add_argument("--by", default=None, help="who (user, ...)")
    p.add_argument("--via", default="cli", help="through what (center, telegram, cli; default cli)")
    p.add_argument("--note", default=None, help="why, one line (into manual_resets)")
    p.add_argument("--root", default=None, help="the factory tree (default: the batch's)")
    p.add_argument("--confirm", action="store_true", help="do it (without: only the plan)")
    p.add_argument("--check", action="store_true", help="only the plan, even with --confirm")
    p.add_argument("--resume", action="store_true", help="start the executor right after (resume)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("blocks", help="CF-0669: seconds of a finished video -> its blocks "
                                      "and rebuild exclusions")
    p.add_argument("--batch", required=True, help="the batch directory")
    p.add_argument("--video", required=True, help="the video: its slug or script id")
    p.add_argument("--at", type=float, nargs="+", required=True, metavar="SECONDS")
    p.add_argument("--root", default=None, help="the factory tree (default: the batch's)")
    p.add_argument("--json", action="store_true")
    try:
        ns = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_REFUSED if e.code else EXIT_OK
    if ns.cmd == "blocks":
        res = blocks_at(ns.batch, ns.video, ns.at, ns.root)
        if ns.json:
            print(json.dumps(res, ensure_ascii=False, indent=2), file=out)
        elif not res["ok"]:
            print("NO " + res["reason"], file=err)
        else:
            for m in res["moments"]:
                where = (f"блок {m['block']}" if m["block"] is not None
                         else "концовка" if m["ending"] else "-")
                win = "" if not m["window"] else f" [{m['window'][0]:g}-{m['window'][1]:g}]"
                print(f"{m['at']:g} с: {where}{win} {m['kind'] or ''} "
                      f"{' + '.join(m['shots']) or ''}".rstrip()
                      + (f"  -> {m['exclude']}" if m["exclude"] else "")
                      + "".join(f"  (рядом блок {n['block']}"
                                + (f": {n['exclude']})" if n["exclude"] else ")")
                                for n in m.get("near") or [])
                      + (f"  ({m['note']})" if m.get("note") else ""), file=out)
            if res["exclude"]:
                print("rebuild: " + " ".join(f"--exclude {res['slug']}:{x}"
                                             for x in res["exclude"]), file=out)
        return EXIT_OK if res["ok"] else EXIT_REFUSED
    if ns.cmd == "rerun-from":
        if ns.check or not ns.confirm:
            res = rerun_from_check(ns.batch, ns.stage, ns.root, by=ns.by, via=ns.via)
            if not ns.check and res["ok"]:
                res["reason"] += " (только план: --confirm, чтобы сделать)"
        else:
            res = rerun_from(ns.batch, ns.stage, ns.by, ns.via, True, ns.root, note=ns.note,
                             resume_after=ns.resume)
        if ns.json:
            print(json.dumps(res, ensure_ascii=False, indent=2), file=out)
        else:
            print(("OK " if res["ok"] else "NO ") + res["reason"], file=out if res["ok"] else err)
            for line in res.get("lines") or []:
                print(f"   {line}", file=out)
        return EXIT_OK if res["ok"] else EXIT_REFUSED
    if ns.cmd == "rebuild":
        per = {}
        for arg, field in [(a, "exclude") for a in ns.exclude] + \
                          [(a, "note") for a in ns.video_note]:
            slug, sep, val = arg.partition(":")
            if not sep or not slug or not val:
                print(f"NO {arg!r}: нужно SLUG:значение", file=err)
                return EXIT_REFUSED
            v = per.setdefault(slug, {"exclude": [], "note": ""})
            if field == "exclude":
                v["exclude"].append(val)
            else:
                v["note"] = val
        notes = {"text": ns.note or "", "videos": per}
        if ns.check or not (ns.confirm or ns.dry_run):
            res = rebuild_check(ns.batch, ns.video, ns.mode, ns.root, notes=notes)
            if not ns.check and res["ok"]:
                res["reason"] += " (только проверка: --confirm, чтобы сделать)"
        else:
            res = rebuild(ns.batch, ns.video, ns.mode, ns.by, True, notes, ns.root,
                          dry_run=ns.dry_run)
        if ns.json:
            print(json.dumps(res, ensure_ascii=False, indent=2), file=out)
        else:
            print(("OK " if res["ok"] else "NO ") + res["reason"], file=out if res["ok"] else err)
            for line in res.get("dry_run") or []:
                print(f"   {line}", file=out)
        return EXIT_OK if res["ok"] else EXIT_REFUSED
    if ns.check or not ns.confirm:
        res = stop_check(ns.batch, ns.root) if ns.cmd == "stop" else resume_check(ns.batch, ns.root)
        if not ns.check and res["ok"]:
            res["reason"] += " (только проверка: --confirm, чтобы сделать)"
    elif ns.cmd == "stop":
        res = stop(ns.batch, ns.by, True, ns.also_step, ns.root, ns.grace_s)
    else:
        res = resume(ns.batch, ns.by, True, ns.root)
    if ns.json:
        print(json.dumps(res, ensure_ascii=False, indent=2), file=out)
    else:
        print(("OK " if res["ok"] else "NO ") + res["reason"], file=out if res["ok"] else err)
        for k in ("reason_step",):
            if res.get(k):
                print(f"   {res[k]}", file=out)
    return EXIT_OK if res["ok"] else EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

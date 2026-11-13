"""CC-0032: maintenance and spend - the factory's archives, cleanups and
reports, through its own functions and CLIs, nothing of the API's own on top.

What each script is to the center (`GET /api/maintenance` says the same, with
the routes):

* `scripts/usage_report.py` - read (`GET /maintenance/usage/{c}/{b}`): what it
  prints with `--json`, through its own functions - `usage.read_usage` (the
  newest generation of the batch's `usage` events) and `usage.totals`. No
  usage events yet: `rows` empty and the factory's hint (`why`).
* `scripts/compare_runs.py` - read (`GET /maintenance/compare?manual=c/b&
  executor=c/b`): `compare_runs.compare` - what `--json` prints - with its
  verdict (`same`: no defect; the CLI's exit 0).
* `scripts/archive_publish_month.py` - a view (`GET /maintenance/archive`:
  its own `--dry-run`, `--publish-only` unless `?monthly=true`, run as the
  user runs it, its lines kept with the exit code) and, CC-0104, a write of
  step (a), the month leaving `publish/` (`POST /maintenance/archive/plan`
  -> `POST /maintenance/archive {confirm}`). The plan is the script's own
  `--dry-run --json --publish-only` (CF-0720): per channel and month the
  zip, its members and bytes, what leaves `publish/` (each file, its bytes,
  `git rm` or delete; the day folders), whether the volume is mounted and
  has room - a confirm token (action `publish_month_archive`, 120 s, single
  use) when there is a debt, the volume is mounted with room, the run said
  0 and no batch is open. The confirm spends the token, refuses while a
  batch is open, runs the same dry run again and compares the document
  (`check_changed`; the volume gone - `volume_missing` with the factory's
  own line), then the real run `--publish-only --json --by user --via
  center` (`child.start`, ARCHIVE_APPLY_TIMEOUT_S: it writes and verifies
  the zips on the volume, moves the month out and commits); the factory's
  document is the answer. The pool, old batches and `$TMPDIR` (steps b-d,
  `monthly_archive.py`) are not run from the center: their dry run is lines
  only.
* `scripts/cleanup_batch_journals.py` - a write (`POST /maintenance/journals/
  plan` -> `POST /maintenance/journals {confirm}`): its own `plan(root)` (the
  journals it would touch: file, lines/bytes before, what goes, sha256) is the
  plan; the confirm spends the token (action `batch_journals_cleanup`, 120 s,
  single use), refuses while a batch is open (`factory.open_batches`, what
  `runlog batch-active` counts - and `delete` asks `runlog batch-active`
  again itself), runs `plan(root)` again and compares (`check_changed`), then
  `delete(root, rows, by="user", via="center")` - the script's own copy,
  cut, accounting check and restore; who and from where go into the
  script's own log as its `кто: by user, via center` line (CF-0720), and
  the answer carries the log lines this run wrote and, per journal, what
  `delete` reports (`after_lines`, `after_bytes`, `applied`).
* `scripts/runlog pool-release` (CC-0105, `api/pool.py`) - a read (`GET
  /maintenance/pool`: its `plan()` and `variants()`) and a write (`POST
  /maintenance/pool/release/plan` -> `POST /maintenance/pool/release
  {confirm}`: the same plan, then its own `delete`), no batch open.
* `scripts/cleanup_tmpdir.sh` - not exposed: it cleans the machine's
  `$TMPDIR`, not the factory tree (the tree the center serves), and it is
  macOS-shaped (its guards name the macOS temp roots). The monthly
  archive's step (d) frees `$TMPDIR` already. (CF-0720 gave it `--json`,
  `--only`, `--by/--via` - a plan a confirm could hold it to; exposing it is
  a task of its own.)
* `scripts/cleanup_1_6_archive.sh` - not exposed: a one-off move of 04.10 with
  no dry run (its plain run already writes zips to the Archive volume), its paths
  default to the home directory and the macOS volume.

No absolute path leaves: the factory root's prefix is cut (as
`api/versions.py` does), the archive volume is `<its name>:` as
`publish_layout.archive_ref` writes it, any other absolute path is
`.../<its last part>`.
"""
import json
import re
import sys
import threading
from pathlib import Path

from . import batches, child, factory, paths, pool, versions
from .batches import BatchFault, _digest, _issue, _spend
from .settings import CODE

ACTION = "batch_journals_cleanup"
KEY = "batch-journals"
ARCHIVE_ACTION = "publish_month_archive"
ARCHIVE_KEY = "publish-month"
ACTIONS = {ACTION: ("план уборки журналов батчей", "журналы не тронуты",
                    "уборки журналов батчей"),
           ARCHIVE_ACTION: ("план месячного архива", "архив не тронут, publish/ на месте",
                            "месячного архива")}
batches.register_actions(ACTIONS)
WRITE_BY, VIA = "user", "center"

USAGE_CLI = "scripts/usage_report.py"
COMPARE_CLI = "scripts/compare_runs.py"
ARCHIVE_CLI = "scripts/archive_publish_month.py"
JOURNALS_CLI = "scripts/cleanup_batch_journals.py"
TMPDIR_CLI = "scripts/cleanup_tmpdir.sh"
ARCHIVE_16_CLI = "scripts/cleanup_1_6_archive.sh"
ARCHIVE_TIMEOUT_S = 240
#: The real run: it writes every zip of a past month onto the volume, reads
#: each back from the device, moves the month out of publish/ and commits.
ARCHIVE_APPLY_TIMEOUT_S = 3600
#: The seams of the tests: more arguments of the archive's dry run (a temp
#: volume, `--skip-mount-check`, `--today`), and the volume they name.
ARCHIVE_ARGS = []
ARCHIVE_VOLUME = None
WRITE_WAIT = 5.0

_ARCHIVE_LOCK = threading.Lock()
_WRITE = threading.Lock()

SCRIPTS = [
    {"script": USAGE_CLI, "exposed": "read",
     "routes": ["GET /api/maintenance/usage/{channel}/{batch_id}"],
     "why": "только чтение: usage.read_usage и usage.totals - то, что печатает --json"},
    {"script": COMPARE_CLI, "exposed": "read",
     "routes": ["GET /api/maintenance/compare"],
     "why": "только чтение: compare_runs.compare - то, что печатает --json"},
    {"script": ARCHIVE_CLI, "exposed": "plan_confirm",
     "routes": ["GET /api/maintenance/archive", "POST /api/maintenance/archive/plan",
                "POST /api/maintenance/archive"],
     "why": "просмотр - его сухой прогон строками; план - --dry-run --json --publish-only, "
            "подтверждение - тот же сухой прогон снова и настоящий запуск --by user --via "
            "center; при открытом батче или без тома архива отказ. Шаги пула, старых "
            "батчей и $TMPDIR из центра не запускаются"},
    {"script": JOURNALS_CLI, "exposed": "plan_confirm",
     "routes": ["POST /api/maintenance/journals/plan", "POST /api/maintenance/journals"],
     "why": "план - его plan(root), подтверждение - delete(root, rows) после той же "
            "проверки; при открытом батче отказ"},
    pool.SCRIPT,
    {"script": TMPDIR_CLI, "exposed": "none", "routes": [],
     "why": "не открыт: чистит $TMPDIR машины, а не дерево фабрики, которое показывает "
            "центр, и устроен под macOS; $TMPDIR уже чистит шаг (d) месячного архива "
            "(его --json/--only/--by/--via, CF-0720, есть - открыть можно отдельной задачей)"},
    {"script": ARCHIVE_16_CLI, "exposed": "none", "routes": [],
     "why": "не открыт: разовый перенос 04.10 без сухого прогона (обычный запуск уже "
            "пишет zip на том Archive), пути по умолчанию - домашний каталог и том macOS"},
]


# ---------------------------------------------------------------- the factory's modules
def _usage():
    factory.runlog()
    return factory._mod("usage", "shared/runlog/usage.py")


def _compare():
    return factory._mod("compare_runs", COMPARE_CLI)


def _journals():
    return factory._mod("cleanup_batch_journals", JOURNALS_CLI)


def _archive():
    return factory._mod("archive_publish_month", ARCHIVE_CLI)


def _prefixes(root, volume=None):
    pre = list(versions._prefixes(root))
    if volume:
        v = str(volume).rstrip("/\\")
        pre = [(v, Path(v).name + ":")] + pre
    return sorted(pre, key=lambda pr: len(pr[0]), reverse=True)


def _scrub(obj, root, volume=None):
    return versions._scrub(obj, _prefixes(root, volume))


def _batch(root, ref, what="батч"):
    """`<channel>/<batch_id>` (or the two names) -> the batch directory; a
    refusal never names the root."""
    parts = ref if isinstance(ref, (list, tuple)) else str(ref or "").split("/")
    if len(parts) != 2:
        raise BatchFault(422, "invalid", f"{what}: ждём «<канал>/<батч>», дано «{ref}».",
                         [f"{what} {ref!r}: not <channel>/<batch_id>"])
    try:
        return batches.batch_dir(root, *parts)
    except BatchFault as e:
        raise BatchFault(e.status, e.code, e.message, _scrub(e.details, root)) from None


def overview():
    return {"scripts": [dict(s, routes=list(s["routes"])) for s in SCRIPTS],
            "journals_action": ACTION, "pool_action": pool.ACTION, "by": WRITE_BY,
            "via": VIA}


# ---------------------------------------------------------------- usage_report
USAGE_KEYS = ("ts", "stage", "video", "model", "role", "agent", "session", "calls",
              "minutes", "first", "last", "computed", "window")


def usage(root, channel, batch_id):
    """`usage_report.py <batch> --json` through its functions: the newest
    generation of the `usage` events, row by row, and `usage.totals`."""
    d = _batch(root, (channel, batch_id))
    us = _usage()
    try:
        # CC-0119 (CF-0718): the factory's cached loader, a grown journal read by
        # its tail; the events are read-only - read_usage and totals only read
        events = us.runlog.sibling("event_log").load_events(d)
        rows = us.read_usage(events=events)
        tot = us.totals(rows)
    except Exception as e:                                       # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Отчёт о расходе фабрики не составлен.",
                         _scrub([f"{type(e).__name__}: {e}"], root)) from e
    out_rows = []
    for r in rows:
        row = {k: r.get(k) for k in USAGE_KEYS}
        row["usage"] = {c: int((r.get("usage") or {}).get(c) or 0) for c in us.COUNTERS}
        out_rows.append(row)
    why = None
    if not rows:
        why = (f"В журнале батча нет событий usage - сначала "
               f"scripts/usage_from_transcripts.py {d.parent.name}/{d.name} --write.")
    return _scrub({"batch": f"{d.parent.name}/{d.name}", "command": USAGE_CLI,
                   "events": str(Path(us.runlog.events_path(d))),
                   "computed": rows[0].get("computed") if rows else None,
                   "ok": bool(rows), "why": why, "rows": out_rows, "totals": tot}, root)


# ---------------------------------------------------------------- compare_runs
def compare(root, manual, executor):
    """`compare_runs.py <manual> <executor> --root <root> --json` - its
    `compare`, with its verdict (`same`: no defect, the CLI's exit 0)."""
    m = _batch(root, manual, "manual")
    e = _batch(root, executor, "executor")
    cr = _compare()
    try:
        r = cr.compare(m, e, str(root))
    except cr.BadCall as x:
        raise BatchFault(422, "bad_call", f"Сравнение не составлено: {x}",
                         _scrub([f"compare_runs: {x}"], root)) from None
    except Exception as x:                                       # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Сравнение прогонов фабрики не составлено.",
                         _scrub([f"{type(x).__name__}: {x}"], root)) from x
    r = dict(r, manual=f"{m.parent.name}/{m.name}", executor=f"{e.parent.name}/{e.name}")
    return _scrub(dict(r, command=COMPARE_CLI, same=not r["defects"],
                       exit_code=1 if r["defects"] else 0), root)


# ---------------------------------------------------------------- archive_publish_month (read only)
def run_archive(cmd):
    """The dry run, started (`child.start`, bounded by ARCHIVE_TIMEOUT_S): a
    run whose output `archive` reads. A seam of the tests."""
    return child.start(cmd, timeout=ARCHIVE_TIMEOUT_S,
                       env=factory.git_env())            # CC-0098: no optional git locks


def _volume():
    if ARCHIVE_VOLUME is not None:
        return str(ARCHIVE_VOLUME)
    try:
        return _archive().DEFAULT_VOLUME
    except Exception:                                            # noqa: BLE001 - a prefix less
        return None


def archive(root, monthly=False):
    """`archive_publish_month.py --dry-run [--publish-only] --root <root>` as
    the user runs it: its lines and exit code, nothing changed (its dry run
    writes neither the log nor a question). The write of step (a) is
    `archive_plan` / `archive_run` (CC-0104). One at a time: the dry run reads
    every file of a past month."""
    if not _ARCHIVE_LOCK.acquire(blocking=False):
        raise BatchFault(409, "busy", "Сухой прогон архива уже идёт - подождите и запросите "
                                      "заново.", ["one archive dry run at a time"])
    try:
        args = ["--dry-run", "--root", str(root)] + ([] if monthly else ["--publish-only"])
        shown = [ARCHIVE_CLI, *(a for a in args if a not in ("--root", str(root)))]
        cmd = [sys.executable, str(CODE / ARCHIVE_CLI), *args, *ARCHIVE_ARGS]
        res = {"exit_code": None, "lines": [], "stderr": None, "error": None}
        try:
            proc = run_archive(cmd)
        except OSError as e:
            proc = None
            res["error"] = f"`{ARCHIVE_CLI}` did not start ({e})"
        if proc is not None:
            try:
                out, err = proc.communicate(timeout=ARCHIVE_TIMEOUT_S)
                res.update(exit_code=proc.returncode,
                           lines=[ln for ln in (out or "").splitlines() if ln.strip()],
                           stderr=(err or "").strip() or None)
            except child.Timeout:                        # already ended by `child`
                res["error"] = f"`{ARCHIVE_CLI} --dry-run` did not answer in {ARCHIVE_TIMEOUT_S} s"
            except OSError as e:
                res["error"] = f"`{ARCHIVE_CLI}` did not start ({e})"
    finally:
        _ARCHIVE_LOCK.release()
    vol = _volume()
    return _scrub(dict(res, command=" ".join(shown), dry_run=True, monthly=bool(monthly),
                       ok=res["exit_code"] == 0,
                       volume=Path(vol).name if vol else None,
                       confirm_available=not monthly, plan_action=ARCHIVE_ACTION), root, vol)


# ---------------------------------------------------------------- archive_publish_month (a write, CC-0104)
#: What the confirm holds the plan to - the document of `--dry-run --json`
#: but its lines and the volume's free bytes (they move with every write).
ARCHIVE_FACTS = ("today", "volume", "mounted", "debt", "legacy_skipped", "jobs", "need_bytes",
                 "margin_bytes", "enough_space", "exit_code")
JOB_KEYS = ("channel", "month", "zip", "action", "old_members", "members", "bytes",
            "from_publish", "day_dirs", "status")
UNMOUNTED = "не смонтирован"
COMMITTED = re.compile(r"коммит [0-9a-f]{7,40}: ")


def run_archive_apply(cmd):
    """The real run (`child.start`, bounded by ARCHIVE_APPLY_TIMEOUT_S) - a
    seam of the tests. The child inherits the environment: it commits."""
    return child.start(cmd, timeout=ARCHIVE_APPLY_TIMEOUT_S)


def _archive_cmd(root, real):
    args = ["--publish-only", "--json", "--root", str(root)]
    args += ["--by", WRITE_BY, "--via", VIA] if real else ["--dry-run"]
    shown = [ARCHIVE_CLI, *(a for a in args if a not in ("--root", str(root)))]
    return [sys.executable, str(CODE / ARCHIVE_CLI), *args, *ARCHIVE_ARGS], " ".join(shown)


def _archive_doc(root, real=False):
    """The script's `--json` document (the plan, or what the real run did).
    A run that did not start, did not answer or printed no document is
    `factory_broken`."""
    cmd, shown = _archive_cmd(root, real)
    what = "Месячный архив" if real else "Сухой прогон месячного архива"
    try:
        proc = (run_archive_apply if real else run_archive)(cmd)
        out, err = proc.communicate()
    except child.Timeout as e:
        limit = ARCHIVE_APPLY_TIMEOUT_S if real else ARCHIVE_TIMEOUT_S
        raise BatchFault(500, "factory_broken", f"{what} не ответил за {limit} с - посмотрите "
                                                f"scripts/archive.log, прежде чем повторять.",
                         [f"`{shown}` did not answer in {limit} s"]) from e
    except OSError as e:
        raise BatchFault(500, "factory_broken", f"{what} не запустился.",
                         _scrub([f"`{shown}` did not start ({e})"], root)) from e
    try:
        doc = json.loads(out or "")
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except ValueError as e:
        tail = [ln for ln in (err or "").splitlines() if ln.strip()][-5:]
        raise BatchFault(500, "factory_broken", f"{what} не выдал документ --json.",
                         _scrub([f"`{shown}`: exit {proc.returncode}, stdout is not JSON ({e})",
                                 *tail], root, _volume())) from e
    return doc, shown


def _archive_facts(doc):
    facts = {k: doc.get(k) for k in ARCHIVE_FACTS}
    facts["jobs"] = [{k: v for k, v in (j or {}).items() if k != "status"}
                     for j in doc.get("jobs") or []]
    return dict(facts, action=ARCHIVE_ACTION)


def _factory_line(doc, word):
    return next((ln for ln in doc.get("lines") or [] if word in ln), None)


def _archive_why(doc, going):
    """Why the plan has no token - in Russian, the factory's own line where it
    gave one."""
    if doc.get("exit_code") != 0:
        last = (doc.get("lines") or ["-"])[-1]
        return f"Сухой прогон архива завершился с кодом {doc.get('exit_code')}: {last}"
    if not doc.get("debt"):
        return (_factory_line(doc, "долга архива нет")
                or "Архивировать нечего: в publish/ нет дней прошедших месяцев.")
    if not doc.get("mounted"):
        return _factory_line(doc, UNMOUNTED) or f"Том архива {doc.get('volume')} не подключён."
    if not doc.get("jobs"):
        return ("Все месяцы долга лежат на томе в старой форме - сначала "
                "`archive_publish_month.py --repack-legacy --apply`.")
    if not doc.get("enough_space"):
        return (f"На томе архива мало места: нужно {doc.get('need_bytes')} байт и запас "
                f"{doc.get('margin_bytes')}, свободно {doc.get('free_bytes')} - ничего не тронуто.")
    if going:
        return ("Открыт батч (" + ", ".join(going) + ") - месячный архив ждёт его закрытия: "
                "архив делает коммит.")
    return None


def _job(j):
    return {k: j.get(k) for k in JOB_KEYS}


def archive_plan(root):
    """`archive_publish_month.py --dry-run --json --publish-only`: what step (a)
    would move to the volume and out of `publish/`, and a confirm token when
    it can run now - nothing touched."""
    if not _ARCHIVE_LOCK.acquire(blocking=False):
        raise BatchFault(409, "busy", "Месячный архив уже считается или идёт - подождите и "
                                      "запросите план заново.", ["one archive run at a time"])
    try:
        doc, shown = _archive_doc(root)
    finally:
        _ARCHIVE_LOCK.release()
    going = _open(root)
    fp = _digest(_archive_facts(doc))
    why = _archive_why(doc, going)
    vol = _volume()
    out = {"action": ARCHIVE_ACTION, "ok": why is None, "why": why, "command": shown,
           "apply_command": _archive_cmd(root, True)[1], "today": doc.get("today"),
           "volume": Path(str(doc.get("volume") or vol or "")).name or None,
           "mounted": doc.get("mounted"), "debt": doc.get("debt") or [],
           "legacy_skipped": doc.get("legacy_skipped") or [],
           "jobs": [_job(j) for j in doc.get("jobs") or []],
           "need_bytes": doc.get("need_bytes"), "free_bytes": doc.get("free_bytes"),
           "margin_bytes": doc.get("margin_bytes"), "enough_space": doc.get("enough_space"),
           "open_batches": going, "lines": doc.get("lines") or [],
           "exit_code": doc.get("exit_code"), "by": WRITE_BY, "via": VIA, "fingerprint": fp,
           "confirm": None, "expires_in_s": None}
    if why is None:
        out.update(confirm=_issue(root, ARCHIVE_ACTION, ARCHIVE_KEY, fp),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return _scrub(out, root, doc.get("volume") or vol)


def _unmounted(doc, root, when):
    line = _factory_line(doc, UNMOUNTED) or f"том архива {doc.get('volume')} не подключён"
    return BatchFault(409, "volume_missing", f"Фабрика отказала: {line}",
                      _scrub([f"archive_publish_month {when}: mounted false", line], root,
                             doc.get("volume")))


def archive_run(root, token):
    """The confirmed month archive: the token spent, no batch open, the same
    dry run (else `check_changed`; the volume gone - `volume_missing`), then
    the real run `--publish-only --json --by user --via center`."""
    if not _ARCHIVE_LOCK.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Месячный архив уже считается или идёт - подождите и "
                                      "запросите план заново.",
                         [f"the archive lock was not free in {WRITE_WAIT} s; the token is not "
                          f"spent"])
    try:
        got = _spend(root, ARCHIVE_ACTION, ARCHIVE_KEY, token)
        going = _open(root)
        if going:
            raise BatchFault(409, "batch_open", "Открыт батч (" + ", ".join(going) + ") - "
                                                "архив не тронут; месячный архив - после его "
                                                "закрытия.",
                             ["factory.open_batches (runlog batch-active) is not empty"])
        doc, _shown = _archive_doc(root)
        if doc.get("debt") and doc.get("mounted") is False:
            raise _unmounted(doc, root, "--dry-run")
        if _digest(_archive_facts(doc)) != got["fingerprint"]:
            if not doc.get("debt") or not doc.get("jobs"):
                raise BatchFault(409, "refused", "Архивировать уже нечего - publish/ не тронут.",
                                 _scrub([_archive_why(doc, []) or "the plan is empty now"],
                                        root, doc.get("volume")))
            raise BatchFault(409, "check_changed", "Месяц в publish/ или том архива изменились с "
                                                   "момента плана - ничего не тронуто; "
                                                   "посмотрите план заново.",
                             [f"the fingerprint of the {ARCHIVE_ACTION} plan differs from the "
                              f"plan's"])
        done, shown = _archive_doc(root, real=True)
    finally:
        _ARCHIVE_LOCK.release()
    vol = done.get("volume") or _volume()
    lines = done.get("lines") or []
    if done.get("debt") and done.get("mounted") is False:
        raise _unmounted(done, root, "run")
    jobs = [_job(j) for j in done.get("jobs") or []]
    if done.get("exit_code") != 0 or any(j["status"] == "failed" for j in jobs):
        raise BatchFault(500, "factory_broken", "Месячный архив не завершился - посмотрите "
                                                "scripts/archive.log и вопросы фабрики, прежде "
                                                "чем повторять.",
                         _scrub([f"`{shown}`: exit {done.get('exit_code')}",
                                 *[f"{j['channel']} {j['month']}: {j['status']}" for j in jobs],
                                 *lines[-8:]], root, vol))
    if not any(j["status"] == "moved" for j in jobs):
        raise BatchFault(409, "refused", "Месячный архив ничего не перенёс: " +
                         (lines[-1] if lines else "фабрика не сказала почему"),
                         _scrub([f"`{shown}`: no job moved", *lines[-5:]], root, vol))
    return _scrub({"action": ARCHIVE_ACTION, "written": True, "by": WRITE_BY, "via": VIA,
                   "command": shown, "today": done.get("today"),
                   "volume": Path(str(vol or "")).name or None, "jobs": jobs,
                   "commit": done.get("commit"),
                   "committed": any(COMMITTED.search(ln) for ln in lines),
                   "exit_code": done.get("exit_code"), "lines": lines}, root, vol)


# ---------------------------------------------------------------- cleanup_batch_journals (a write)
ROW_KEYS = ("rel", "mode", "lines", "bytes", "drop", "drop_bytes", "sha")
#: What `delete` reports on each row (CF-0720).
DONE_KEYS = ("after_lines", "after_bytes", "applied")


def _rows(root, cbj):
    try:
        return cbj.plan(Path(root).resolve())
    except cbj.Stop as e:
        raise BatchFault(409, "refused", f"Уборка журналов отказала: {e}",
                         _scrub([f"cleanup_batch_journals.plan: {e}"], root)) from None
    except Exception as e:                                       # noqa: BLE001
        raise BatchFault(500, "factory_broken", "План уборки журналов фабрики не составлен.",
                         _scrub([f"{type(e).__name__}: {e}"], root)) from e


def _row_doc(r):
    doc = {k: r[k] for k in ROW_KEYS}
    doc["after"] = 0 if r["mode"] == "whole" else r["lines"] - r["drop"]
    return doc


def _totals(docs):
    """What the script's `report` sums on its last line."""
    whole = [d for d in docs if d["mode"] == "whole"]
    part = [d for d in docs if d["mode"] == "lines"]
    return {"journals": len(docs), "whole": len(whole),
            "whole_lines": sum(d["drop"] for d in whole),
            "whole_bytes": sum(d["drop_bytes"] for d in whole),
            "cut_journals": len(part), "cut_lines": sum(d["drop"] for d in part),
            "cut_bytes": sum(d["drop_bytes"] for d in part)}


def _open(root):
    try:
        return [f"{Path(b['dir']).parent.name}/{Path(b['dir']).name}"
                for b in factory.open_batches(root)]
    except Exception as e:                                       # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Не проверено, открыт ли батч - уборка не "
                                                "начата.",
                         _scrub([f"runlog.open_batches: {type(e).__name__}: {e}"], root)) from e


def _log_rel(cbj):
    return paths.rel(CODE, cbj.LOG)


def journals_plan(root):
    """`cleanup_batch_journals.plan(root)` - the journals it would touch - and
    a confirm token when there is something and no batch is open."""
    cbj = _journals()
    docs = [_row_doc(r) for r in _rows(root, cbj)]
    going = _open(root)
    fp = _digest({"action": ACTION, "rows": docs})
    ok = bool(docs) and not going
    why = None
    if going:
        why = "Открыт батч (" + ", ".join(going) + ") - уборка журналов отложена до его закрытия."
    elif not docs:
        why = "Чистить нечего: чужих строк в журналах батчей нет."
    out = {"action": ACTION, "ok": ok, "why": why, "command": f"{JOURNALS_CLI} --delete",
           "journals": docs, "totals": _totals(docs), "open_batches": going,
           "log": _log_rel(cbj), "by": WRITE_BY, "via": VIA, "fingerprint": fp,
           "confirm": None, "expires_in_s": None}
    if ok:
        out.update(confirm=_issue(root, ACTION, KEY, fp), expires_in_s=int(batches.CONFIRM_TTL))
    return _scrub(out, root)


def _log_size(cbj):
    try:
        return Path(cbj.LOG).stat().st_size
    except OSError:
        return 0


def _log_since(cbj, at):
    try:
        with open(cbj.LOG, "rb") as fh:
            fh.seek(at)
            return [ln for ln in fh.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    except OSError:
        return []


def journals_clean(root, token):
    """The confirmed cleanup: the token spent, no batch open, the plan again
    and the same (else `check_changed`; nothing to clean now - `refused`),
    then `delete(root, rows, by, via)` - the script's own run, which asks
    `runlog batch-active` once more, copies, cuts, checks the accounting,
    restores on a mismatch and logs who asked."""
    cbj = _journals()
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая уборка журналов - подождите и запросите "
                                      "план заново.",
                         [f"the cleanup lock was not free in {WRITE_WAIT} s; the token is not "
                          f"spent"])
    try:
        got = _spend(root, ACTION, KEY, token)
        going = _open(root)
        if going:
            raise BatchFault(409, "batch_open", "Открыт батч (" + ", ".join(going) + ") - "
                                                "журналы не тронуты; уборка - после его "
                                                "закрытия.",
                             ["factory.open_batches (runlog batch-active) is not empty"])
        rows = _rows(root, cbj)
        docs = [_row_doc(r) for r in rows]
        if _digest({"action": ACTION, "rows": docs}) != got["fingerprint"]:
            if not docs:
                raise BatchFault(409, "refused", "Чистить уже нечего - журналы не тронуты.",
                                 ["the plan is empty now"])
            raise BatchFault(409, "check_changed", "Журналы изменились с момента плана - ничего "
                                                   "не тронуто; посмотрите план заново.",
                             [f"the fingerprint of the {ACTION} plan differs from the plan's"])
        at = _log_size(cbj)
        backup = None
        try:
            backup = cbj.delete(Path(root).resolve(), rows, by=WRITE_BY, via=VIA)
        except cbj.Stop as e:
            raise BatchFault(409, "refused", f"Уборка журналов остановлена: {e}",
                             _scrub([f"cleanup_batch_journals.delete: {e}",
                                     *_log_since(cbj, at)], root)) from None
        except Exception as e:                                   # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Фабрика ответила ошибкой посреди уборки - "
                                                    "посмотрите журнал уборки, прежде чем "
                                                    "повторять.",
                             _scrub([f"{type(e).__name__}: {e}", *_log_since(cbj, at)],
                                    root)) from e
    finally:
        _WRITE.release()
    done = [dict(d, **{k: r.get(k) for k in DONE_KEYS}) for d, r in zip(docs, rows)]
    return _scrub({"action": ACTION, "written": True, "by": WRITE_BY, "via": VIA,
                   "done": done, "totals": _totals(docs),
                   "backup": str(backup) if backup else None,
                   "log": _log_rel(cbj), "lines": _log_since(cbj, at)}, root)

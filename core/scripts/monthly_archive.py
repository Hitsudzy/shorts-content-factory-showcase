#!/usr/bin/env python3
"""CF-0358: the monthly archive, after `publish/` - what else leaves the disk.

The user's decision of 2026-10-04: everything that frees the disk lives inside
the ONE monthly archive job (`scripts/archive_publish_month.py`, launchd on the
1st and on every mount of a volume). That script does step (a) itself - a past
month of `publish/` becomes one zip on Archive - and then calls `run_steps()`
here for the rest, in this order:

  (b) pool  - `shared/runlog/pool_release.py`: the footage of every topic whose
              video is published or withdrawn leaves `shared/footage/`, and so
              does the footage of a topic that never became a video (`no_video`,
              or rejected and not withdrawn) once every batch it appears in is
              older than 14 days (`pool_release.STALE_DAYS`, the user's rule of
              2026-10-04). It has to run BEFORE (c): a batch's
              `01b-footage-index.json` is what names its sources - once the
              batch is in a zip, its sources are orphans nobody can attribute.
              Needs no Archive (sources are deleted for good, the published video
              keeps its full copy in `publish/` and then in the month's zip).
  (c) batches - every batch folder `pipeline/<dir>/<YYYY-MM-DDTHHMMZ>` older
              than 30 days (by the date in its name) goes, whole, into ONE zip
              per folder group and month on Archive:
                  <volume>/shorts-content-factory-pipeline/<dir>/<YYYY-MM>.zip
                      <batch>/<path inside the batch>      (stored)
                  <volume>/shorts-content-factory-pipeline/<dir>/<YYYY-MM>.manifest.json
              The user's rule "archive = one file": the zip is written as
              `.partial`, read back from the device and every member's sha256
              compared with its original (exactly the expected set of names),
              renamed, its manifest written - and only then the batch folders
              are removed whole. A month already in a zip gets its late batches
              by a new zip carrying the old members and the new ones.
              CF-0056 (from the retired `archive_old_batches.sh`): before the
              first batch of a channel leaves, `rotate.py backfill <channel>`
              fills the rotation ledger from the batches' `05-video-editor.json`
              and `rotate.py backfill <channel> --check` must then exit 0 -
              otherwise none of that channel's batches is touched, in writing.
              `pipeline/rebuilds/<ts>` answers to the channel its own records
              name (`rotate.channel_of_batch`); `pipeline/backfill/` is
              synthetic (CF-0111) and never touched.
  (d) other - copies of factory runs in `$TMPDIR` older than 24 h
              (`scripts/cleanup_tmpdir.sh --delete --min-age-hours 24`, CF-0501:
              its own white list, its own journal `scripts/cleanup_tmpdir.log`).

Guards, for all three: nothing is deleted while a batch is open (`runlog
batch-active`; any doubt counts as open) - the step is put off and a question
of the journal of questions (shared/needs_you.py, CF-0652) says so; a deletion in (c) only after its zip is verified; `--dry-run` (the
plan) writes nothing anywhere - no deletions, no Archive writes, no ledger writes
(it asks `backfill --check`, which writes nothing).

"Monthly": each step remembers the month (MSK) it last completed in
`<log>.month-state.json` (next to `scripts/archive.log`, outside git) and runs
again only in a later month - the mount trigger pays a debt the 1st could not
(Archive unplugged, a batch open), it does not make the job daily. `--force` runs
the steps regardless (a manual run).

Every line goes to `scripts/archive.log` with the prefix `month:`.

    python3 scripts/archive_publish_month.py [--dry-run] [--force]   # (a)..(d)
    python3 scripts/monthly_archive.py [--dry-run] [--force] [--root DIR]
        [--volume /Volumes/Archive] [--log FILE] [--today YYYY-MM-DD]
        [--runlog CMD] [--rotate PATH] [--tmpdir DIR] [--skip-mount-check]
                                                                 # (b)..(d) only
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "shared" / "runlog"))
# appended, not inserted: `shared/runlog/` the directory must not shadow
# `shared/runlog/runlog.py` the module
sys.path.append(str(REPO / "shared"))
import archive_publish_month as apm                             # noqa: E402

TASK = "CF-0358"
STEPS = ("pool", "batches", "other")
BATCH_ARCHIVE_DIR = "shorts-content-factory-pipeline"
MAX_AGE_DAYS = 30
TMPDIR_MIN_AGE_HOURS = 24
NOT_A_CHANNEL = ("backfill",)
REBUILDS = "rebuilds"
BATCH_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T\d{4}Z$")
MARKER = "долг месячной уборки"
STATE_SUFFIX = ".month-state.json"


class Log(apm.Log):
    def _line(self, msg):
        return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} month: {msg}"


def gb(n):
    return f"{n / 1024 ** 3:.2f} ГБ"


# --------------------------------------------------------------------------
# the context
# --------------------------------------------------------------------------

class Ctx:
    def __init__(self, root, volume, log, today, dry=False, force=False, runlog=None,
                 rotate=None, python=None, tmpdir=None, needs_you=None,
                 skip_mount_check=False, max_age_days=MAX_AGE_DAYS,
                 stale_days=None, tmpdir_script=None):
        self.root = Path(root).resolve()
        self.volume = Path(volume)
        self.log = log
        self.today = today
        self.month = today[:7]
        self.dry = dry
        self.force = force
        self.runlog = runlog
        self.rotate = Path(rotate) if rotate else self.root / "rotation" / "rotate.py"
        venv = self.root / ".venv" / "bin" / "python3"
        self.python = python or (str(venv) if venv.exists() else sys.executable)
        self.tmpdir = tmpdir
        self.needs_you = needs_you
        self.skip_mount_check = skip_mount_check
        self.max_age_days = max_age_days
        self.stale_days = stale_days
        self.tmpdir_script = Path(tmpdir_script) if tmpdir_script else \
            REPO / "scripts" / "cleanup_tmpdir.sh"

    @property
    def mounted(self):
        return (self.skip_mount_check and self.volume.is_dir()) or apm.is_mounted(self.volume)

    @property
    def archive_root(self):
        return self.volume / BATCH_ARCHIVE_DIR


def batch_active(ctx):
    """True when a batch is open - or when that could not be told (any doubt
    counts as open). `--runlog CMD` asks `CMD batch-active --root ROOT`
    (exit 0 open, 1 closed, anything else doubt); by default `runlog` is asked
    in-process (`runlog.open_batches`), as step (a) does."""
    if ctx.runlog:
        try:
            cp = subprocess.run([*ctx.runlog.split(), "batch-active", "--root", str(ctx.root)],
                                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return True
        return cp.returncode != 1
    return apm.batch_open(ctx.root)


# --------------------------------------------------------------------------
# state: the month each step last completed in
# --------------------------------------------------------------------------

def state_path(ctx):
    return Path(str(ctx.log.path) + STATE_SUFFIX)


def read_state(ctx):
    d = apm.load_json(state_path(ctx))
    return d if isinstance(d, dict) else {}


def mark_done(ctx, step):
    if ctx.dry:
        return
    st = read_state(ctx)
    st[step] = ctx.month
    st["updated_at"] = apm.now_iso()
    p = state_path(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(p))


def due(ctx):
    if ctx.dry or ctx.force:
        return list(STEPS)
    st = read_state(ctx)
    return [s for s in STEPS if (st.get(s) or "") < ctx.month]


# --------------------------------------------------------------------------
# (b) pool
# --------------------------------------------------------------------------

def step_pool(ctx):
    """True when done (nothing left to do this month)."""
    import pool_release as pr
    stale = ctx.stale_days if ctx.stale_days is not None else pr.STALE_DAYS
    now = datetime.now(timezone.utc)
    try:
        p = pr.plan(ctx.root, now=now, stale_days=stale)
    except Exception as e:                                      # noqa: BLE001
        ctx.log(f"пул: план не собран — {e.__class__.__name__}: {e}; ничего не удаляю")
        return False
    rel = p["release"]
    by_stale = [e for e in rel if any(v.get("stale") for v in e["topics"].values())]
    ctx.log(f"пул: {p['pool']['sources']} источников, {gb(p['pool']['bytes'])}; освободить "
            f"{len(rel)} ({gb(sum(e['bytes'] for e in rel))}), из них по правилу "
            f"{stale} дней {len(by_stale)} ({gb(sum(e['bytes'] for e in by_stale))}); держит "
            f"живая тема {len(p['keep'])} ({gb(sum(e['bytes'] for e in p['keep']))}); сироты "
            f"{len(p['orphan'])} ({gb(sum(e['bytes'] for e in p['orphan']))}) — не трогаются")
    if ctx.dry:
        for e in rel:
            ctx.log(f"  освободить {e['video_id']} {gb(e['bytes'])} — темы {', '.join(e['topics'])}")
        return True
    if not rel:
        return True
    try:
        gone = pr.delete(p, ctx.root, now=now)
    except (RuntimeError, OSError) as e:
        ctx.log(f"пул: удаление прервано — {e}")
        return False
    ctx.log(f"пул: удалено {len(gone)} источников, журнал {pr.journal_path(ctx.root)}")
    return True


# --------------------------------------------------------------------------
# (c) batches
# --------------------------------------------------------------------------

def batch_date(name):
    m = BATCH_RE.match(name)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def due_batches(ctx):
    """[(group dir name, batch dir)] older than `max_age_days`, oldest first."""
    pipe = ctx.root / "pipeline"
    cutoff = date.fromisoformat(ctx.today) - timedelta(days=ctx.max_age_days)
    out = []
    if not pipe.is_dir():
        return out
    for gdir in sorted(p for p in pipe.iterdir() if p.is_dir()):
        if gdir.name in NOT_A_CHANNEL or gdir.name.startswith("."):
            continue
        for b in sorted(p for p in gdir.iterdir() if p.is_dir()):
            d = batch_date(b.name)
            if d is None:
                if BATCH_RE.match(b.name) is None and b.name[:1].isdigit():
                    ctx.log(f"батчи: пропускаю {gdir.name}/{b.name} — не распознан timestamp")
                continue
            if d < cutoff:
                out.append((gdir.name, b))
    return out


def _read_json(p):
    d = apm.load_json(p)
    return d if isinstance(d, dict) else None


def ledger_channel(ctx, group, bdir):
    """The channel whose rotation ledger the batch feeds (current id), or None.
    Every name read off disk goes through `channel_ids.resolve_channel` at the
    read itself (CF-0197: a frozen batch file may carry a former id)."""
    import channel_ids

    def resolve(raw):
        return channel_ids.resolve_channel(str(raw), root=ctx.root) if raw else None

    if group != REBUILDS:
        return resolve(group)
    ve = _read_json(bdir / "05-video-editor.json") or {}
    src = ve.get("rebuild_of") if isinstance(ve.get("rebuild_of"), dict) else {}
    name = channel_ids.resolve_channel(str(src.get("channel") or ""), root=ctx.root) \
        if src.get("channel") else None
    if not name and ve.get("channel") not in (None, "", REBUILDS):
        name = channel_ids.resolve_channel(str(ve.get("channel")), root=ctx.root)
    for rec in ("03-content-researcher.json", "01-trend-hunter.json"):
        if name:
            break
        d = _read_json(bdir / rec) or {}
        name = channel_ids.resolve_channel(str(d.get("channel")), root=ctx.root) \
            if d.get("channel") else None
    return name


def _note(raw):
    """One line out of rotate.py's JSON report (as archive_old_batches.sh did)."""
    try:
        report = json.loads(raw)
    except ValueError:
        return " ".join(raw.split())[:400] or "(пустой вывод)"

    def rows(section):
        return sum(len(v) for v in section.values())

    parts = []
    if "filled" in report:
        batches = report.get("batches") or []
        parts.append(f"заполнено строк: {len(report['filled'])}"
                     + (f" (из батчей {', '.join(batches)})" if batches else ""))
    else:
        parts.append(f"произведено, но не в реестре (строк): {rows(report.get('recoverable') or {})}")
    if report.get("conflicts"):
        parts.append(f"конфликтов в строках: {len(report['conflicts'])}")
    if report.get("awaiting"):
        parts.append(f"ждут видео (строк): {rows(report['awaiting'])}")
    if report.get("unrecorded"):
        parts.append("вне реестра, ничем не восстановимо: " + "; ".join(
            f"{b}: {', '.join(ids)}" for b, ids in sorted(report["unrecorded"].items())))
    return "; ".join(parts)


def _rotate(ctx, *args):
    try:
        cp = subprocess.run([ctx.python, str(ctx.rotate), *args], capture_output=True,
                            text=True, timeout=240)
    except (OSError, subprocess.SubprocessError) as e:
        return 2, str(e)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def ledger_caught_up(ctx, channel):
    """CF-0056: True when `backfill --check` exits 0 after `backfill` (the dry
    run only asks `--check`, which writes nothing)."""
    if not ctx.rotate.is_file():
        ctx.log(f"{channel}: не найден {ctx.rotate} — спросить реестр нечем, батчи не переношу")
        return False
    if not ctx.dry:
        rc, out = _rotate(ctx, "backfill", channel)
        if rc != 0:
            ctx.log(f"{channel}: backfill не отработал, батчи не переношу — {_note(out)}")
            return False
        ctx.log(f"{channel}: backfill — {_note(out)}")
    rc, out = _rotate(ctx, "backfill", channel, "--check")
    if rc != 0:
        if ctx.dry:
            ctx.log(f"{channel}: backfill --check = {rc} — перед переносом будет `backfill "
                    f"{channel}`; если и после него не 0, батчи канала останутся — {_note(out)}")
            return True
        ctx.log(f"{channel}: реестр отстаёт от диска и после backfill, батчи не переношу — "
                f"{_note(out)}")
        return False
    ctx.log(f"{channel}: реестр догнал диск — {_note(out)}")
    return True


def batch_files(bdir):
    """[(path inside the batch, file)] - every regular file; `(None, link)`
    for a symlink, which keeps the batch where it is."""
    out = []
    for p in sorted(bdir.rglob("*")):
        if p.is_symlink():
            out.append((None, p))
        elif p.is_file() and p.name not in apm.JUNK:
            out.append((str(p.relative_to(bdir)), p))
    return out


def write_manifest(path, group, month, members, batches, zip_size, zip_sha):
    data = {"group": group, "month": month, "task": TASK, "zip": f"{month}{apm.ZIP}",
            "zip_size": zip_size, "zip_sha256": zip_sha, "updated_at": apm.now_iso(),
            "batches": sorted(batches),
            "files": [{"path": m["name"], "size": m["size"], "sha256": m["sha256"]}
                      for m in members]}
    tmp = Path(str(path) + apm.PARTIAL)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def pack(ctx, group, month, batches, verify=apm.verify_zip):
    """Zip one group's month on the volume, read it back and verify it. True
    only when the zip is in place with the size it was verified at."""
    adir = ctx.archive_root / group
    zpath = adir / f"{month}{apm.ZIP}"
    local = []
    for b in batches:
        for rel, f in batch_files(b):
            st = f.stat()
            local.append(apm._member(f"{b.name}/{rel}", st.st_size, apm.sha256(f), "local",
                                     src=f, mtime=st.st_mtime))
    try:
        adir.mkdir(parents=True, exist_ok=True)
        old = apm.zip_members(zpath, None) if zpath.is_file() else []
        members = apm.merge(old, local)
        old_batches = {m["name"].split("/", 1)[0] for m in old}
        tmp = apm.build_zip(zpath, members)
    except (apm.ArchiveError, OSError, zipfile.BadZipFile) as e:
        ctx.log(f"батчи {group} {month}: zip не собран — {e}; ничего не удаляю")
        Path(str(zpath) + apm.PARTIAL).unlink(missing_ok=True)
        return False
    problems, size, digest = verify(tmp, members)
    if problems:
        for p in problems[:20]:
            ctx.log(f"батчи {group} {month}: сверка не сошлась — {p}")
        ctx.log(f"батчи {group} {month}: zip не принят, ничего не удаляю")
        tmp.unlink(missing_ok=True)
        return False
    os.replace(str(tmp), str(zpath))
    write_manifest(adir / f"{month}{apm.MANIFEST}", group, month, members,
                   old_batches | {b.name for b in batches}, size, digest)
    if not zpath.is_file() or zpath.stat().st_size != size:
        ctx.log(f"батчи {group} {month}: {zpath} после переименования не подтвердился, "
                f"ничего не удаляю")
        return False
    ctx.log(f"батчи {group} {month}: {zpath} — батчей {len(batches)} (+{len(old_batches)} "
            f"прежних), членов {len(members)}, {apm.mb(size)}, sha256 {digest[:12]}…, сверка "
            f"с оригиналами сошлась")
    return True


def step_batches(ctx, verify=apm.verify_zip):
    todo = due_batches(ctx)
    if not todo:
        ctx.log.say(f"батчи: старше {ctx.max_age_days} дней нет")
        return True
    if not ctx.dry and not ctx.mounted:
        ctx.log(f"батчи: {ctx.volume} не смонтирован — батчи старше {ctx.max_age_days} дней "
                f"({len(todo)}) остаются до подключения Archive")
        return False
    # CF-0056: the ledger is asked once per channel, and only for a channel with
    # something due.
    verdict, keep = {}, []
    for group, b in todo:
        ch = ledger_channel(ctx, group, b)
        if ch is None:
            ctx.log(f"батчи: пропускаю {group}/{b.name} — ни одна запись батча не называет канал")
            continue
        if ch not in verdict:
            verdict[ch] = ledger_caught_up(ctx, ch)
        if not verdict[ch]:
            ctx.log(f"батчи: пропускаю {group}/{b.name} — реестр {ch} не догнал диск, "
                    f"батч остаётся на месте")
            continue
        links = [f for rel, f in batch_files(b) if rel is None]
        if links:
            ctx.log(f"батчи: пропускаю {group}/{b.name} — в нём симлинки "
                    f"({', '.join(str(x.relative_to(b)) for x in links[:3])}), разобрать руками")
            continue
        keep.append((group, b))
    groups = {}
    for group, b in keep:
        groups.setdefault((group, b.name[:7]), []).append(b)
    size = {k: sum(f.stat().st_size for b in v for _r, f in batch_files(b)) for k, v in groups.items()}
    total = sum(size.values())
    ctx.log(f"батчи: старше {ctx.max_age_days} дней {len(todo)}, к переносу {len(keep)} "
            f"({gb(total)}) в {len(groups)} zip")
    for (group, month), bs in sorted(groups.items()):
        ctx.log(f"  {ctx.archive_root / group / (month + apm.ZIP)} ← "
                f"{', '.join(b.name for b in bs)} ({gb(size[(group, month)])}); затем "
                f"удалить эти папки целиком")
    if ctx.dry:
        return True
    ok = len(keep) == len(todo)
    if not groups:
        return ok
    free = shutil.disk_usage(ctx.volume).free
    margin = int(apm.MIN_FREE_GB * (1 << 30)) + apm.ZIP_OVERHEAD
    if total + margin > free:
        ctx.log(f"батчи: мало места на {ctx.volume}: нужно {apm.mb(total)} + запас, "
                f"свободно {apm.mb(free)} — ничего не трогаю")
        return False
    for (group, month), bs in sorted(groups.items()):
        if not pack(ctx, group, month, bs, verify=verify):
            ok = False
            continue
        if batch_active(ctx):
            ctx.log(f"батчи {group} {month}: открылся батч — zip на месте, оригиналы не удаляю "
                    f"(следующий запуск дополнит тот же zip и удалит)")
            return False
        for b in bs:
            shutil.rmtree(b)
            ctx.log(f"батчи: удалён {group}/{b.name} (в {month}{apm.ZIP})")
    return ok


# --------------------------------------------------------------------------
# (d) other
# --------------------------------------------------------------------------

def user_tmpdir(ctx):
    """$TMPDIR as the user's shell sees it - under launchd it may be unset."""
    if ctx.tmpdir:
        return str(ctx.tmpdir)
    if os.environ.get("TMPDIR"):
        return os.environ["TMPDIR"]
    try:
        cp = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True,
                            text=True, timeout=10)
        if cp.returncode == 0 and cp.stdout.strip():
            return cp.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return tempfile.gettempdir()


def step_other(ctx):
    root = user_tmpdir(ctx)
    args = ["bash", str(ctx.tmpdir_script), "--min-age-hours", str(TMPDIR_MIN_AGE_HOURS)]
    if not ctx.dry:
        args.append("--delete")
    env = dict(os.environ, CLEANUP_TMPDIR_ROOT=root)
    try:
        cp = subprocess.run(args, capture_output=True, text=True, timeout=280, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        ctx.log(f"прочее: cleanup_tmpdir.sh не запустился — {e}")
        return False
    lines = [ln.strip() for ln in (cp.stdout + cp.stderr).splitlines() if ln.strip()]
    tail = [ln for ln in lines if any(w in ln for w in ("итог", "после:", "удалено", "Итого",
                                                       "ИТОГО", "СТОП", "не трону"))][-4:] \
        or lines[-3:]
    ctx.log(f"прочее: $TMPDIR {root}, порог {TMPDIR_MIN_AGE_HOURS} ч — "
            + (" | ".join(tail) or "(пустой вывод)")
            + ("" if cp.returncode == 0 else f" (код {cp.returncode})"))
    return cp.returncode == 0


# --------------------------------------------------------------------------

STEP_FUNCS = {"pool": step_pool, "batches": step_batches, "other": step_other}


def run_steps(ctx):
    """(b) pool -> (c) batches -> (d) other, each at most once a month. 0 when
    every due step is done, 1 when one is put off or failed (NEEDS-YOU says so)."""
    os.environ["FACTORY_ROOT"] = str(ctx.root)
    todo = due(ctx)
    if not todo:
        ctx.log.say(f"месячная уборка за {ctx.month} уже сделана")
        return 0
    if ctx.dry:
        ctx.log("план (сухой прогон): ничего не удаляется, на Archive и в реестр не пишется")
    if batch_active(ctx):
        msg = "открыт батч (runlog batch-active) — шаги " + ", ".join(todo) + " отложены"
        if ctx.dry:
            ctx.log(msg + "; план ниже — на будущее")
        else:
            ctx.log(msg)
            remind(ctx, f"{MARKER} {ctx.month}: был открыт батч, шаги {', '.join(todo)} "
                   f"отложены до следующего запуска")
            return 1
    failed = []
    for step in STEPS:
        if step not in todo:
            continue
        try:
            done = STEP_FUNCS[step](ctx)
        except Exception as e:                                  # noqa: BLE001
            ctx.log(f"шаг {step}: ошибка {e.__class__.__name__}: {e}")
            done = False
        if done:
            mark_done(ctx, step)
        else:
            failed.append(step)
    if ctx.dry:
        return 0
    if failed:
        remind(ctx, f"{MARKER} {ctx.month}: не сделаны шаги {', '.join(failed)} — "
               f"см. scripts/archive.log (строки `month:`)")
        return 1
    if ctx.needs_you:
        apm.clear_reminder(ctx.needs_you, ctx.log, marker=MARKER)
    return 0


def remind(ctx, text):
    if ctx.needs_you:
        apm.remind(ctx.needs_you, ctx.today, text, ctx.log, marker=MARKER)


def add_arguments(ap):
    ap.add_argument("--force", action="store_true",
                    help="run the monthly steps even if this month already had them")
    ap.add_argument("--runlog", default=None,
                    help="command answering `batch-active --root ROOT` (tests); default: in-process")
    ap.add_argument("--rotate", default=None, help="rotation/rotate.py (default: <root>/rotation)")
    ap.add_argument("--tmpdir", default=None, help="the $TMPDIR to clean (default: the user's)")
    ap.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)


def ctx_from_args(a, root, log, today):
    return Ctx(root, a.volume, log, today, dry=a.dry_run, force=a.force, runlog=a.runlog,
               rotate=a.rotate, tmpdir=a.tmpdir, needs_you=a.needs_you,
               skip_mount_check=a.skip_mount_check, max_age_days=a.max_age_days)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--volume", default=apm.DEFAULT_VOLUME)
    ap.add_argument("--log", default=None)
    ap.add_argument("--needs-you-dir", default=None,
                    help="the journal of questions' directory (CF-0652)")
    ap.add_argument("--today", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-mount-check", action="store_true")
    add_arguments(ap)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    a.needs_you = apm.needs_you_dir(a.needs_you_dir, root)
    today = apm.pl.release_day(a.today) if a.today else apm.msk_today()
    log = Log(a.log or (root / "scripts" / "archive.log"), write=not a.dry_run)
    return run_steps(ctx_from_args(a, root, log, today))


if __name__ == "__main__":
    sys.exit(main())

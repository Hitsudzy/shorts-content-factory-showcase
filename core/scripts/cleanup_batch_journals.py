#!/usr/bin/env python3
"""CF-0530 (веха 1.6.4 «Уборка», решение пользователя 04.10 по CF-0251):
удаление мусора, дописанного тестами и ручными перепроверками в журналы
батчей `pipeline/<канал>/<батч>/RUN_EVENTS.jsonl`.

Признак - разметка CF-0251 (раздел «Разметка источников», логика журнала -
`shared/runlog/runlog.py: journal_state / write_path`):

  * журнал ведётся по маркерам: `batch-start` открывает батч, `batch-done`
    закрывает, `stage-start` после `batch-done` открывает заново (законная
    переделка, как 1722Z 24.09); `stage-done` состояние не меняет;
  * ЧУЖАЯ строка - событие активности (`script` / `child` / `sample`),
    записанное, пока журнал был закрыт (после `batch-done` и до следующего
    `stage-start` / `batch-start`). Учёт (`usage` / `gap` / `limits` /
    `limit-hit` / `quota` / ...) и маркеры не трогаются никогда; строки до
    первого `batch-start` журнала, у которого он есть, - тоже (это подготовка
    самого батча, например `parent_decisions.py` перед `batch-start` 1748Z);
  * ЦЕЛИКОМ ЧУЖОЙ журнал - без единого `batch-start`, в котором ВСЕ строки -
    события активности, а настоящий учёт батча лежит в
    `pipeline/backfill/<тот же id>/RUN_EVENTS.jsonl` (2026-08-31T2155Z,
    2026-09-03T2037Z). Журналы пересборок без `batch-start`
    (`pipeline/rebuilds/…`, старая процедура до CF-0401) - настоящая работа,
    не трогаются: у них нет backfill-двойника.
  * `pipeline/backfill/` не трогается никогда.

Без флага - только список: файл, строк/байт до, сколько удаляется, после.
С `--delete`:
  1. отказ, если открыт батч (`scripts/runlog batch-active --root <корень>`);
  2. копия каждого затронутого журнала во временный каталог
     ($TMPDIR/cf0530-journals-XXXX, его подберёт CF-0501 по классу cfNNNN-*);
  3. целиком чужие журналы удаляются; из остальных чужие строки вырезаются
     атомарно (временный файл рядом + fsync + os.replace), режим файла
     сохраняется; если файл изменился между чтением и записью - отказ;
  4. сверка учёта: на копии «до» и на результате «после» совпадают все
     нечужие строки байт в байт и проекция учёта сводки (`summary.load` /
     `summary.tokens`: usage, limits, limit-hit, quota, записанные gap,
     маркеры, окна батча и стадий, токены итого/по стадиям). Расхождение -
     журнал восстанавливается из копии, скрипт падает.
  Каждое действие и итог до/после - в журнал `scripts/cleanup_batch_journals.log`.

Запуск (корень по умолчанию - ОСНОВНОЙ чекаут репозитория, в котором лежит
скрипт: родитель общего git-каталога, т. е. живой `pipeline/`, даже если
скрипт запущен из `.worktrees/release-<v>/`):
  python3 scripts/cleanup_batch_journals.py            # список
  python3 scripts/cleanup_batch_journals.py --delete   # удалить
  --root DIR   другой корень фабрики (тесты); то же - CLEANUP_JOURNALS_ROOT
  CLEANUP_LOG  другой журнал (тесты)
  --by WHO --via WHERE  (CF-0720) кто и откуда - строкой «кто: ...» в журнал уборки

CF-0720 (просьба 3 центра 13.10): `delete(root, rows, by=, via=, dry_run=)` -
by/via проверяются (`_who`) до любого действия и пишутся в журнал уборки;
отчёт - сами строки плана: `after_lines`, `after_bytes`, `applied`, и у
настоящего прогона, и у сухого (`dry_run=True`: те же проверки и отказы,
ничего не копируется, не пишется и не логируется, возвращает None).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_ROOT = HERE.parent
sys.path.insert(0, str(CODE_ROOT / "shared" / "runlog"))
import git_read  # noqa: E402  (CF-0717: git reads with optional locks off)

EVENTS_FILE = "RUN_EVENTS.jsonl"
ACTIVITY = ("script", "child", "sample")
LOG = Path(os.environ.get("CLEANUP_LOG") or HERE / "cleanup_batch_journals.log")


class Stop(Exception):
    pass


def log(msg, quiet=False):
    if not quiet:
        print(msg)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError as e:
        raise Stop(f"журнал не пишется ({LOG}): {e}")


def default_root():
    env = os.environ.get("CLEANUP_JOURNALS_ROOT")
    if env:
        return Path(env)
    try:
        cp = git_read.run(["-C", str(CODE_ROOT), "rev-parse", "--path-format=absolute",
                           "--git-common-dir"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        raise Stop(f"корень не определён (git): {e}")
    if cp.returncode != 0 or not cp.stdout.strip():
        raise Stop(f"корень не определён (git rev-parse): {cp.stderr.strip()}")
    return Path(cp.stdout.strip()).parent


def _parse(raw):
    try:
        e = json.loads(raw)
    except ValueError:
        return None
    return e if isinstance(e, dict) else None


def classify(lines):
    """[(raw, foreign)] for one journal, by the CF-0251 markup; plus `started`."""
    started = closed = False
    out = []
    for raw in lines:
        e = _parse(raw)
        foreign = False
        if e is not None:
            kind = e.get("kind")
            if kind == "marker":
                st = e.get("status")
                if st == "batch-start":
                    started, closed = True, False
                elif st == "batch-done":
                    closed = True
                elif st == "stage-start":
                    closed = False
            elif kind in ACTIVITY and started and closed:
                foreign = True
        out.append((raw, foreign))
    return out, started


def is_activity(raw):
    e = _parse(raw)
    return e is not None and e.get("kind") in ACTIVITY


def read_lines(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return data, data.splitlines(keepends=True)


def journals(root):
    pipe = (root / "pipeline").resolve()
    if not pipe.is_dir():
        raise Stop(f"нет каталога pipeline: {pipe}")
    for p in sorted(pipe.glob(f"*/*/{EVENTS_FILE}")):
        if p.parent.parent.name == "backfill":
            continue
        rp = p.resolve()
        if p.is_symlink() or not rp.is_file() or pipe not in rp.parents or rp.parent.parent.parent != pipe:
            log(f"ПРОПУСК (не обычный файл внутри pipeline/*/*/): {p}")
            continue
        yield rp


def plan(root):
    """[{path, rel, mode: whole|lines, lines, bytes, drop, drop_bytes}] - only the touched journals."""
    pipe = (root / "pipeline").resolve()
    rows = []
    for p in journals(root):
        data, lines = read_lines(p)
        cls, started = classify(lines)
        rel = str(p.relative_to(root.resolve()))
        base = {"path": p, "rel": rel, "lines": len(lines), "bytes": len(data),
                "sha": hashlib.sha256(data).hexdigest()}
        if not started:
            twin = pipe / "backfill" / p.parent.name / EVENTS_FILE
            if twin.is_file() and lines and all(is_activity(r) for r in lines):
                rows.append(dict(base, mode="whole", drop=len(lines), drop_bytes=len(data)))
            continue
        drop = [r for r, f in cls if f]
        if drop:
            rows.append(dict(base, mode="lines", drop=len(drop), drop_bytes=sum(map(len, drop))))
    return rows


def _mb(n):
    return f"{n / 1e6:.1f} МБ" if n >= 1e6 else f"{n / 1e3:.1f} КБ"


def report(rows):
    if not rows:
        log("чистить нечего")
        return
    log(f"{'файл':<62} {'строк до':>9} {'удаляется':>10} {'после':>9} {'байт до':>10} {'удаляется':>10}")
    for r in rows:
        after = 0 if r["mode"] == "whole" else r["lines"] - r["drop"]
        tag = "  [журнал целиком]" if r["mode"] == "whole" else ""
        log(f"{r['rel']:<62} {r['lines']:>9} {r['drop']:>10} {after:>9} {_mb(r['bytes']):>10} "
            f"{_mb(r['drop_bytes']):>10}{tag}")
    whole = [r for r in rows if r["mode"] == "whole"]
    part = [r for r in rows if r["mode"] == "lines"]
    log(f"итого: журналов целиком {len(whole)} ({sum(r['drop'] for r in whole)} строк, "
        f"{_mb(sum(r['drop_bytes'] for r in whole))}); строк из {len(part)} журналов "
        f"{sum(r['drop'] for r in part)} ({_mb(sum(r['drop_bytes'] for r in part))})")


def active_batches(root):
    runlog_cmd = CODE_ROOT / "scripts" / "runlog"
    try:
        cp = subprocess.run([sys.executable, str(runlog_cmd), "batch-active", "--root", str(root)],
                            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise Stop(f"runlog batch-active не отработал: {e}")
    if cp.returncode == 0:
        return [l for l in cp.stdout.splitlines() if l.strip()] or ["(без имени)"]
    if cp.returncode == 1:
        return []
    raise Stop(f"runlog batch-active: код {cp.returncode}: {cp.stderr.strip()}")


def accounting(events_bytes, batch_dir):
    """The accounting projection of a journal through the summary's own loader."""
    import summary
    ev = [e for e in (_parse(r) for r in events_bytes.splitlines()) if e is not None]
    d = summary.load(batch_dir, events=ev)
    tok = summary.tokens(d)
    gaps_mod = summary.runlog.sibling("gaps")
    proj = {
        "usage": d["usage"], "usage_error": d["usage_error"], "limits": d["limits"],
        "limit_hits": d["limit_hits"], "quota": d["quota"], "markers": d["markers"],
        "gap_events": [e for e in ev if e.get("kind") == gaps_mod.KIND_GAP],
        "wall": d["wall"], "stages": d["stages"],
        "tokens_total": tok["total"], "tokens_by_stage": tok["by_stage"],
    }
    return json.dumps(proj, sort_keys=True, default=str, ensure_ascii=False)


def kept_bytes(data):
    return b"".join(r for r, f in classify(data.splitlines(keepends=True))[0] if not f)


def write_atomic(path, payload, mode):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.cf0530-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


WHO_MAX = 40                # CF-0720: `by` / `via` (the shape of notify._who, CF-0700)


def _who(value, what):
    """CF-0720: `by` / `via` - None (not given) or a short non-empty
    single-line string; anything else is a Stop and nothing is touched."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise Stop(f"{what}={value!r}: короткая непустая строка (by='user', via='center') "
                   f"или не задано вовсе")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise Stop(f"{what}={value!r}: не длиннее {WHO_MAX} символов, одной строкой")
    return value


def delete(root, rows, by=None, via=None, dry_run=False):
    """Cut the foreign lines (or remove a whole-foreign journal) of every row
    of `plan(root)`; returns the directory with the copies «до».

    CF-0720: `by` / `via` (checked before anything is touched) go into the
    log line that opens the run (`кто: by <by>, via <via>`). The report is
    the rows themselves, for the real run and the dry run alike: each gets
    `after_lines`, `after_bytes` and `applied` (True when written). With
    `dry_run=True` the same checks run - an open batch, a journal changed
    since the plan, the accounting of the summary before/after (computed on
    the bytes that would be written) - the same Stop on a refusal, and
    nothing is copied, written or logged; the return is None."""
    by, via = _who(by, "by"), _who(via, "via")
    act = active_batches(root)
    if act:
        raise Stop("открыт батч, чистка отложена: " + ", ".join(act))
    if dry_run:
        for r in rows:
            data = r["path"].read_bytes()
            if hashlib.sha256(data).hexdigest() != r["sha"]:
                raise Stop(f"файл изменился после списка: {r['rel']} (сухой прогон)")
            if r["mode"] == "whole":
                r.update(after_lines=0, after_bytes=0, applied=False)
                continue
            payload = kept_bytes(data)
            if accounting(payload, r["path"].parent) != accounting(data, r["path"].parent):
                raise Stop(f"{r['rel']}: проекция учёта сводки до/после не совпала бы "
                           f"(сухой прогон, ничего не тронуто)")
            r.update(after_lines=len(payload.splitlines()), after_bytes=len(payload),
                     applied=False)
        return None
    if by is not None or via is not None:
        log(f"кто: by {by or '-'}, via {via or '-'}")
    backup = Path(tempfile.mkdtemp(prefix="cf0530-journals-"))
    log(f"копия оригиналов: {backup}")
    for r in rows:
        dst = backup / r["rel"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(r["path"], dst)
        if hashlib.sha256(dst.read_bytes()).hexdigest() != r["sha"]:
            raise Stop(f"копия не совпала с оригиналом (файл меняется?): {r['rel']}")
        r["backup"] = dst
    done = 0
    for r in rows:
        p = r["path"]
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != r["sha"]:
            raise Stop(f"файл изменился после списка, остановлено на нём: {r['rel']} "
                       f"(сделано {done} из {len(rows)})")
        if r["mode"] == "whole":
            p.unlink()
            r.update(after_lines=0, after_bytes=0, applied=True)
            log(f"УДАЛЁН журнал целиком: {r['rel']} ({r['lines']} строк, {r['bytes']} байт)")
            done += 1
            continue
        before_acc = accounting(data, p.parent)
        payload = kept_bytes(data)
        write_atomic(p, payload, p.stat().st_mode & 0o7777)
        after = p.read_bytes()
        bad = None
        if after != payload:
            bad = "записанное не совпало с рассчитанным"
        elif b"".join(r2 for r2 in data.splitlines(keepends=True) if not is_activity(r2)) != \
                b"".join(r2 for r2 in after.splitlines(keepends=True) if not is_activity(r2)):
            bad = "учёт/маркеры изменились (строки не-активности не совпали байт в байт)"
        elif accounting(after, p.parent) != before_acc:
            bad = "проекция учёта сводки до/после не совпала"
        if bad:
            shutil.copy2(r["backup"], p)
            raise Stop(f"{r['rel']}: {bad} - журнал восстановлен из копии")
        n_after = len(after.splitlines())
        r.update(after_lines=n_after, after_bytes=len(after), applied=True)
        log(f"ВЫРЕЗАНО: {r['rel']}: строк {r['lines']} -> {n_after} (-{r['lines'] - n_after}), "
            f"байт {r['bytes']} -> {len(after)} (-{r['bytes'] - len(after)}); учёт сводки совпал")
        done += 1
    log(f"готово: обработано {done} журналов; копия «до» - {backup}")
    return backup


def main(argv=None):
    ap = argparse.ArgumentParser(description="CF-0530: удаление тестового мусора из журналов батчей")
    ap.add_argument("--delete", action="store_true", help="удалить (по умолчанию - только список)")
    ap.add_argument("--root", default=None, help="корень фабрики (по умолчанию - основной чекаут)")
    ap.add_argument("--by", default=None, help="CF-0720: кто просил (user) - в журнал уборки")
    ap.add_argument("--via", default=None, help="CF-0720: откуда (cli, center) - в журнал уборки")
    ns = ap.parse_args(argv)
    try:
        by, via = _who(ns.by, "by"), _who(ns.via, "via")
        root = Path(ns.root) if ns.root else default_root()
        if not root.is_absolute():
            raise Stop(f"корень должен быть абсолютным путём: {root}")
        root = root.resolve()
        log(f"--- {'УДАЛЕНИЕ' if ns.delete else 'список'}; корень {root}")
        rows = plan(root)
        report(rows)
        if ns.delete and rows:
            delete(root, rows, by=by, via=via)
        elif not ns.delete and rows:
            log("ничего не удалено (список); удалить: --delete")
    except Stop as e:
        try:
            log(f"СТОП: {e}", quiet=True)
        except Stop:
            pass
        print(f"СТОП: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

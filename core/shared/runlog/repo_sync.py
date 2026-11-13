#!/usr/bin/env python3
"""CF-0247: расхождение репозиториев проекта с origin, видимое в статусной строке.

Почему это здесь, а не в логе. Автопуш (`post-commit`/`post-merge`, CF-0036)
при ошибке пишет в `/tmp/post-*-push-error.log` и не блокирует коммит - и это
правильно, ронять коммит из-за сети нельзя. Но 2026-09-16 выяснилось, что цена
такой тишины - двое суток: `agents/video-editor` ушёл на 40 коммитов вперёд и
1 назад, и всплыло это случайно. Лог как канал не работает по трём причинам
сразу: он один на все восемь репозиториев и на оба хука, он перезаписывается
(`2>`) при каждом пуше, и git пишет в него прогресс даже при **успешном** пуше -
то есть непустой лог не значит ничего. Ещё одна строка в такой лог ничего бы не
изменила.

Что делает этот модуль: считает для каждого репозитория проекта, насколько он
разошёлся с `origin`, и отдаёт одну короткую строку для статусной строки Claude
Code - той, что человек видит при каждом своём вводе. Пока всё сведено, строка
пустая и ничего не занимает; как только где-то появляется незапушенный коммит,
в статусе висит `git: video-editor +40`, и незамеченным это не проживёт и дня.

Дешевизна обеспечена кэшем: statusline читает только JSON-кэш (одно чтение
файла), а пересчёт - включая `git fetch` - уходит в отдельный отвязанный
процесс, когда кэш протух. Сама статусная строка не ждёт git никогда.

CLI:

    python3 repo_sync.py                # таблица по всем репозиториям (из кэша)
    python3 repo_sync.py --refresh      # пересчитать, с fetch; печатает таблицу
    python3 repo_sync.py --no-fetch     # пересчитать без сети
    python3 repo_sync.py --segment      # то, что видит statusline ("" если чисто)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import git_read  # noqa: E402  (CF-0717)
import runlog  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV = "REPO_SYNC_ROOT"
CACHE_NAME = "repo-sync.json"
#  Кэш считается свежим 10 минут: достаточно, чтобы расхождение всплыло в тот же
#  час, и достаточно редко, чтобы fetch по восьми репозиториям не мешал никому.
CACHE_TTL_S = 600
#  Fetch по сети - единственное место, где можно зависнуть; режем жёстко.
FETCH_TIMEOUT_S = 20
GIT_TIMEOUT_S = 10


def project_root():
    override = os.environ.get(ROOT_ENV)
    return Path(override).expanduser().resolve() if override else PROJECT_ROOT


def cache_path():
    return runlog._state_dir() / CACHE_NAME


def repos(root=None):
    """Корень проекта плюс каждый `agents/*`, если это git-репозиторий.

    Возвращает `(репозитории, пропущенные)`. Пропущенные - каталоги под
    `agents/`, которые репозиториями не являются (на 2026-09-16 это пустые
    заглушки `analyst` и `publisher`): сводить там нечего, но молча терять их
    из виду тоже не надо - иначе «проверены все репозитории» будет неправдой.
    """
    root = Path(root) if root else project_root()
    out, skipped = [], []
    if (root / ".git").exists():
        out.append((root.name, root))
    agents = root / "agents"
    if agents.is_dir():
        for p in sorted(agents.iterdir()):
            if not p.is_dir():
                continue
            if (p / ".git").exists():
                out.append((f"agents/{p.name}", p))
            else:
                skipped.append(f"agents/{p.name}")
    return out, skipped


def _git(path, *args, timeout=GIT_TIMEOUT_S):
    cp = git_read.run(["-C", str(path), *args],
                      capture_output=True, text=True, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "git failed").strip().splitlines()[-1][:200])
    return cp.stdout.strip()


def divergence(path, fetch=True):
    """{'branch', 'ahead', 'behind'} для ветки относительно её upstream.

    `ahead` считается без сети и поэтому надёжен всегда - именно он ловит наш
    случай (локальные коммиты, которые никуда не уехали). `behind` без свежего
    fetch показывает последнее, что мы знали об origin, поэтому фоновый пересчёт
    делает fetch; если сети нет, отдаём то, что знаем, и помечаем `stale`.
    """
    info = {"branch": None, "ahead": 0, "behind": 0, "stale": False, "error": None}
    try:
        info["branch"] = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception as e:
        info["error"] = str(e)
        return info
    #  CF-0479: агент в рабочей копии стоит на пине из agents.lock.json - теге,
    #  то есть на detached HEAD. Незапушенные коммиты тогда живут в его `main`
    #  (линия разработки), её и сверяем с origin.
    ref = "HEAD"
    if info["branch"] == "HEAD":
        try:
            _git(path, "rev-parse", "--verify", "-q", "refs/heads/main")
            ref, info["branch"] = "main", "main (HEAD на пине)"
        except Exception:
            pass
    upstream = "@{upstream}" if ref == "HEAD" else f"{ref}@{{upstream}}"
    try:
        _git(path, "rev-parse", "--abbrev-ref", upstream)
    except Exception:
        info["error"] = "нет upstream"
        return info
    if fetch:
        try:
            _git(path, "fetch", "--quiet", timeout=FETCH_TIMEOUT_S)
        except Exception:
            info["stale"] = True
    try:
        counts = _git(path, "rev-list", "--left-right", "--count", f"{upstream}...{ref}")
        behind, ahead = counts.split()
        info["ahead"], info["behind"] = int(ahead), int(behind)
    except Exception as e:
        info["error"] = str(e)
    return info


def scan(root=None, fetch=True, write=True):
    found, skipped = repos(root)
    data = {"checked_at": time.time(), "fetched": bool(fetch), "repos": {}, "skipped": skipped}
    for name, path in found:
        data["repos"][name] = divergence(path, fetch=fetch)
    if write:
        try:
            p = cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            tmp.replace(p)
        except Exception as e:
            runlog._warn(f"repo-sync cache not written ({e.__class__.__name__}: {e})")
    return data


def read_cache():
    try:
        return json.loads(cache_path().read_text())
    except Exception:
        return None


def refresh_in_background():
    """Отвязанный пересчёт: statusline его не ждёт и не видит его вывода."""
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--refresh", "--quiet"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        runlog._warn(f"repo-sync refresh not spawned ({e.__class__.__name__}: {e})")


def short_name(name):
    return name.split("/", 1)[1] if name.startswith("agents/") else name


def format_repo(name, info):
    """Короткая пометка про один репозиторий; '' - если сводить нечего."""
    if info.get("error"):
        return f"{short_name(name)}?"
    bits = ""
    if info.get("ahead"):
        bits += f"+{info['ahead']}"
    if info.get("behind"):
        bits += f"-{info['behind']}"
    return f"{short_name(name)} {bits}" if bits else ""


def segment(ttl=CACHE_TTL_S, spawn=True):
    """Кусок статусной строки. Пусто, когда все репозитории сведены."""
    cache = read_cache()
    if cache is None or (time.time() - cache.get("checked_at", 0)) > ttl:
        if spawn:
            refresh_in_background()
        if cache is None:
            return ""
    parts = [s for s in (format_repo(n, i) for n, i in sorted(cache.get("repos", {}).items())) if s]
    return "⚠ git: " + ", ".join(parts) if parts else ""


def table(cache):
    rows = [("репозиторий", "ветка", "ahead", "behind", "примечание")]
    for name, info in sorted(cache.get("repos", {}).items()):
        note = info.get("error") or ("origin не опрошен" if info.get("stale") else "")
        rows.append((name, info.get("branch") or "-", str(info.get("ahead", 0)),
                     str(info.get("behind", 0)), note))
    w = [max(len(r[i]) for r in rows) for i in range(5)]
    out = [" | ".join(r[i].ljust(w[i]) for i in range(5)).rstrip() for r in rows]
    out.insert(1, "-+-".join("-" * x for x in w))
    age = time.time() - cache.get("checked_at", 0)
    out.append(f"\nпроверено {int(age)} с назад, fetch: {'да' if cache.get('fetched') else 'нет'}")
    if cache.get("skipped"):
        out.append("не репозитории (сводить нечего): " + ", ".join(cache["skipped"]))
    return "\n".join(out)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    quiet = "--quiet" in argv
    if "--segment" in argv:
        print(segment())
        return 0
    if "--refresh" in argv or "--no-fetch" in argv:
        cache = scan(fetch="--no-fetch" not in argv)
    else:
        cache = read_cache()
        if cache is None:
            cache = scan(fetch=True)
    if not quiet:
        print(table(cache))
    return 1 if any(i.get("ahead") or i.get("behind") for i in cache.get("repos", {}).values()) else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CF-0247: канонические git-хуки проекта, в репозитории, а не только в `.git/hooks`.

Автопуш (`post-commit`, CF-0036; `post-merge`, 2026-09-07) до сих пор жил
исключительно внутри `.git/hooks/` каждого чекаута - то есть нигде: файлы не
версионируются, не ревьюятся, и никакой новый репозиторий их не получает, пока
кто-нибудь не вспомнит скопировать. Здесь лежит их текст и установщик.

Что поменялось в самих хуках по итогам разбора 2026-09-16:

- лог перестал быть общим на все репозитории и оба хука. Был один
  `/tmp/post-commit-push-error.log`, куда писали восемь репозиториев;
- лог перестал перезаписываться. Было `2>файл` - каждый пуш затирал прошлый, то
  есть улика жила до следующего коммита;
- в лог пишется только провал. Раньше git сваливал туда прогресс и при успешном
  пуше, поэтому «в логе что-то есть» не значило ничего, и читать его было
  бессмысленно;
- лог больше и не претендует на роль сигнала - сигнал теперь в статусной строке
  (`shared/runlog/repo_sync.py`), а хук при провале сразу пинает её пересчёт,
  чтобы пометка появилась в течение секунд, а не в пределах TTL кэша.

    python3 scripts/install_git_hooks.py           # поставить во все репозитории
    python3 scripts/install_git_hooks.py --check   # только проверить, exit 1 если разошлось
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
import repo_sync  # noqa: E402
import git_read  # noqa: E402  (CF-0717)

sys.path.insert(0, str(ROOT / "shared"))
import agents_lock  # noqa: E402

#  CF-0479: the hooks are shared by every worktree of a repo, so they call the
#  working copy's repo_sync, never a version worktree's that is removed at release.
REFRESH = agents_lock.working_copy(ROOT) / "shared" / "runlog" / "repo_sync.py"

TEMPLATE = """#!/bin/sh
# Автопуш после {event} ({origin_task}). Сгенерирован scripts/install_git_hooks.py - правь там.
# Не пушит ветки воркеров (worktree-*/wip/*): они живут до слияния в main
# и раньше засоряли origin десятками мёртвых веток.
# Провал пуша не блокирует {blocks} - ронять работу из-за сети нельзя. Но и молчать
# нельзя (CF-0247): расхождение уходит в статусную строку, а лог ниже - улика к нему.
branch=$(git rev-parse --abbrev-ref HEAD)
case "$branch" in
  worktree-*|wip/*) exit 0 ;;
esac
if out=$(git push origin "$branch" 2>&1); then
  exit 0
fi
repo=$(basename "$(git rev-parse --show-toplevel)")
log="${{TMPDIR:-/tmp}}/push-failures-$repo.log"
printf '%s\\t{hook}\\t%s\\n%s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$branch" "$out" >> "$log"
py=$(command -v python3 2>/dev/null)
[ -n "$py" ] && ( "$py" {refresh} --refresh --quiet >/dev/null 2>&1 & )
echo "{hook}: push в origin/$branch не удался - расхождение теперь видно в статусной строке; улика в $log" >&2
"""

HOOKS = {
    "post-commit": {"event": "каждого коммита", "origin_task": "CF-0036", "blocks": "коммит"},
    "post-merge": {"event": "слияния", "origin_task": "2026-09-07",
                   "blocks": "слияние"},  # post-commit тут не срабатывает: ff-merge не создаёт коммита
}


def body(hook):
    """Текст хука. Интерпретатор ищется в PATH на месте, а не вшивается при
    установке: иначе хук намертво привязывается к тому .venv, из которого
    случайно запустили установщик."""
    return TEMPLATE.format(hook=hook, refresh=REFRESH, **HOOKS[hook])


def _hooks_dir(path):
    """The hooks directory git itself reads for the checkout at `path`. In a
    worktree (CF-0479: a root version worktree and the agents' worktrees under
    it) `.git` is a file and the hooks are the main repo's, shared."""
    try:
        cp = git_read.run(["-C", str(path), "rev-parse", "--path-format=absolute",
                           "--git-path", "hooks"], capture_output=True, text=True, timeout=10)
        if cp.returncode == 0 and cp.stdout.strip():
            return Path(cp.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(path) / ".git" / "hooks"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in argv
    found, skipped = repo_sync.repos(ROOT)
    drift = 0
    for name, path in found:
        hooks_dir = _hooks_dir(path)
        for hook in HOOKS:
            target, want = hooks_dir / hook, body(hook)
            same = target.is_file() and target.read_text() == want
            if same:
                print(f"  ok      {name}/{hook}")
                continue
            drift += 1
            if check:
                print(f"  РАЗОШЁЛСЯ {name}/{hook}" if target.is_file() else f"  НЕТ     {name}/{hook}")
                continue
            hooks_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(want)
            target.chmod(0o755)
            print(f"  записан {name}/{hook}")
    for name in skipped:
        print(f"  пропущен {name} (не репозиторий)")
    return 1 if (check and drift) else 0


if __name__ == "__main__":
    sys.exit(main())

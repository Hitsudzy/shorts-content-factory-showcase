#!/bin/bash
# CF-0516 (решение пользователя 2026-10-04): разовое удаление отработанного хвоста
# батча pipeline/example-film/2026-09-15T1034Z, который тогда писал прямо в агент
# (batch_dir = сам агент), из БОЕВОГО чекаута agents/video-editor:
#   work/dtf-st-louis/  work/everyday-sorcery-2/  work/widows-bay/
#   work/spirerunner-fresh-dawn/                      (~84 МБ вместе с wav/клипами)
#   logs/<slug>-attempt-N.log этих слагов и cf0141-fullrun (находка CF-0497,
#   attempts.py пишет <batch_dir>/logs/...; 624 КБ, 10 файлов на 04.10)
# Ничего другого не трогает: остальные work/cf*/ и чужие файлы logs/ остаются;
# logs/ убирается `rmdir`, только если после удаления он пуст.
#
# По умолчанию - сухой прогон: печатает каждый путь и размер, ничего не удаляет.
# Удаляет только с `--delete` и только если:
#   - цель - боевой чекаут: <FACTORY_ROOT>/agents/video-editor, корень своего git
#     (не worktree: .git - каталог), в нём есть scripts/attempts.py;
#   - батч закрыт: `<FACTORY_ROOT>/scripts/runlog batch-active` вернул 1
#     (0 = открыт -> отказ; любой другой код -> отказ, состояние неизвестно);
#   - на HEAD чекаута этих файлов уже нет в git. До v1.7 (коммит CF-0516 в
#     агенте) 42 файла work/<slug>/ отслеживаются, и их удаление сделало бы
#     чекаут грязным (agents_lock.dirty, code_shas.dirty у записей роликов).
#     Сначала перевести агента на пин с этим коммитом - checkout сам уберёт
#     отслеживаемые файлы, - потом `--delete` доберёт игнорируемые (wav, клипы).
#
# Запуск:
#   bash scripts/cleanup_cf0516_leftovers.sh            # сухой прогон
#   bash scripts/cleanup_cf0516_leftovers.sh --delete   # удаление
# Повторный запуск безопасен: отсутствующий путь печатается как «нет» и пропускается.
#
# Подменяемо для теста (по умолчанию - живая фабрика):
#   FACTORY_ROOT  корень фабрики;  AGENT_DIR - чекаут агента (<FACTORY_ROOT>/agents/video-editor)
#   RUNLOG        команда runlog (batch-active)
set -euo pipefail

FACTORY_ROOT="${FACTORY_ROOT:-$HOME/shorts-content-factory}"
AGENT_DIR="${AGENT_DIR:-$FACTORY_ROOT/agents/video-editor}"
RUNLOG="${RUNLOG:-$FACTORY_ROOT/scripts/runlog}"

WORK_SLUGS="dtf-st-louis everyday-sorcery-2 widows-bay spirerunner-fresh-dawn"
LOG_SLUGS="dtf-st-louis everyday-sorcery-2 widows-bay spirerunner-fresh-dawn cf0141-fullrun"

DELETE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --delete) DELETE=1 ;;
        -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
        *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "СТОП: $*" >&2; exit 1; }

# --- цель - боевой чекаут агента ---
[ -d "$FACTORY_ROOT" ] || die "нет корня фабрики: $FACTORY_ROOT"
[ -d "$AGENT_DIR" ] || die "нет чекаута агента: $AGENT_DIR"
want="$(cd "$FACTORY_ROOT/agents/video-editor" 2>/dev/null && pwd -P)" \
    || die "нет $FACTORY_ROOT/agents/video-editor"
AGENT="$(cd "$AGENT_DIR" && pwd -P)"
[ "$AGENT" = "$want" ] || die "$AGENT - не боевой чекаут агента ($want)"
top="$(git -C "$AGENT" rev-parse --show-toplevel 2>/dev/null)" || die "$AGENT - не git-репозиторий"
[ "$(cd "$top" && pwd -P)" = "$AGENT" ] || die "$AGENT - не корень своего git ($top)"
[ -d "$AGENT/.git" ] || die "$AGENT - worktree (.git не каталог), а не боевой чекаут"
[ -f "$AGENT/scripts/attempts.py" ] || die "$AGENT - не video-editor (нет scripts/attempts.py)"

# --- что удалять: точные пути ---
TARGETS=()
for s in $WORK_SLUGS; do TARGETS+=("work/$s"); done
for s in $LOG_SLUGS; do
    for f in "$AGENT/logs/$s-attempt-"[0-9]*.log; do
        [ -e "$f" ] || continue
        TARGETS+=("logs/${f##*/}")
    done
done

human() {  # КБ -> «12.3 МБ» / «456 КБ»
    awk -v k="$1" 'BEGIN { if (k >= 1024) printf "%.1f МБ", k/1024; else printf "%d КБ", k }'
}

total=0
present=0
for t in "${TARGETS[@]}"; do
    p="$AGENT/$t"
    if [ -L "$p" ]; then die "$p - симлинк, не трогаю"; fi
    if [ ! -e "$p" ]; then echo "  нет      $t"; continue; fi
    kb=$(du -sk "$p" | awk '{print $1}')
    total=$((total + kb))
    present=$((present + 1))
    if [ -d "$p" ]; then n=$(find "$p" -type f | wc -l | tr -d ' '); extra=" ($n файлов)"; else extra=""; fi
    printf '  %-9s %s%s\n' "$(human "$kb")" "$t" "$extra"
done
echo "итого: $present путей, $(human "$total") в $AGENT"

tracked=$(git -C "$AGENT" ls-files -- $(for s in $WORK_SLUGS; do printf 'work/%s ' "$s"; done) | wc -l | tr -d ' ')
echo "отслеживается в git на HEAD чекаута ($(git -C "$AGENT" describe --tags --always HEAD 2>/dev/null)): $tracked файлов"

rc=0
"$RUNLOG" batch-active --root "$FACTORY_ROOT" >/dev/null 2>&1 || rc=$?
case $rc in
    0) batch="открыт" ;;
    1) batch="закрыт" ;;
    *) batch="неизвестно (runlog batch-active вернул $rc)" ;;
esac
echo "батч: $batch"

if [ "$DELETE" -eq 0 ]; then
    echo "сухой прогон - ничего не удалено; удаление: $0 --delete"
    exit 0
fi

[ "$rc" -eq 1 ] || die "батч $batch - удаление только при закрытом батче"
[ "$tracked" -eq 0 ] || die "на HEAD чекаута $tracked файлов work/<slug>/ ещё в git - сначала перевести агента на пин с коммитом CF-0516 (git checkout уберёт их сам), потом повторить"
[ "$present" -gt 0 ] || { echo "удалять нечего"; exit 0; }

for t in "${TARGETS[@]}"; do
    p="$AGENT/$t"
    [ -e "$p" ] || continue
    rm -rf -- "$p"
    echo "удалено: $t"
done
if [ -d "$AGENT/logs" ] && [ -z "$(ls -A "$AGENT/logs")" ]; then
    rmdir "$AGENT/logs"
    echo "удалено: logs/ (пуст)"
fi
echo "готово: $(human "$total") освобождено"

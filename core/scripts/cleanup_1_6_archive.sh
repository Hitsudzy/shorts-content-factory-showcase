#!/bin/bash
# CF-0500 (веха 1.6.4 «Уборка»): разовый перенос мёртвых данных вне git в архив
# на Archive по правилу пользователя «архив = перенос одним файлом»: один zip на
# группу, `unzip -t`, сверка sha256 каждого файла против оригинала, и только
# после этого - удаление оригиналов, точными путями, по одному, с печатью пути.
#
# Без флага скрипт только архивирует и сверяет - оригиналы не трогает. Удаляет
# он их лишь с явным `--delete-originals`, после успешной сверки, при закрытом
# батче (`runlog batch-active` вернул 1) и при реестре ротации, догнавшем диск
# (`rotate.py backfill <канал> --check` вернул 0, как у месячного архива scripts/monthly_archive.py:
# 05-video-editor.json уносимых батчей - единственный источник производственных
# колонок реестра).
#
# Запуск (пользователь, 04.10):
#   bash scripts/cleanup_1_6_archive.sh                     # zip + сверка
#   bash scripts/cleanup_1_6_archive.sh --delete-originals  # zip + сверка + удаление
# Повторный запуск безопасен: готовый zip не пересобирается, а сверяется заново;
# группа, у которой оригиналов уже нет, а zip лежит, пропускается.
#
# Перепаковка одной группы (CF-0358, 04.10): zip собран, а оригиналы с тех пор
# изменились (CF-0530 удалил 2 мусорных журнала из pipeline/legacy-film уже
# после того, как legacy-film-batches.zip был собран), - старый zip несёт
# лишнее, и обычный запуск на нём остановится (в zip файлов больше, чем в
# оригиналах). `--repack <группа>` собирает НОВЫЙ zip рядом (<группа>.zip.repack),
# проверяет его так же (unzip -t, sha256 каждого файла против оригиналов, то же
# число файлов) и только потом заменяет им старый zip и опись .sha256.
# Оригиналы не трогает; при открытом батче отказывается.
#   bash scripts/cleanup_1_6_archive.sh --repack legacy-film-batches
#
# Подменяемо для теста (по умолчанию - живая фабрика и Archive):
#   FACTORY_ROOT  корень фабрики, где лежат оригиналы
#   ARCHIVE_DIR   куда класть zip, .sha256 и журнал
#   RUNLOG        команда `runlog` (batch-active)
#   ROTATE        rotation/rotate.py;  PYTHON - интерпретатор для него
#   CHANNEL       канал для проверки реестра (example-film)
set -euo pipefail

FACTORY_ROOT="${FACTORY_ROOT:-$HOME/shorts-content-factory}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/Volumes/Archive/shorts-content-factory-cleanup-1.6}"
RUNLOG="${RUNLOG:-$FACTORY_ROOT/scripts/runlog}"
ROTATE="${ROTATE:-$FACTORY_ROOT/rotation/rotate.py}"
CHANNEL="${CHANNEL:-example-film}"
if [ -z "${PYTHON:-}" ]; then
    if [ -x "$FACTORY_ROOT/.venv/bin/python3" ]; then PYTHON="$FACTORY_ROOT/.venv/bin/python3"; else PYTHON=python3; fi
fi

DELETE=0
REPACK=""
while [ $# -gt 0 ]; do
    case "$1" in
        --delete-originals) DELETE=1 ;;
        --repack) shift; REPACK="${1:-}"; [ -n "$REPACK" ] || { echo "--repack ждёт имя группы" >&2; exit 2; } ;;
        -h|--help) sed -n '2,37p' "$0"; exit 0 ;;
        *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
    shift
done
[ -z "$REPACK" ] || [ "$DELETE" -eq 0 ] || { echo "--repack и --delete-originals - разными запусками" >&2; exit 2; }

# Группа = имя zip | пути относительно FACTORY_ROOT через пробел.
ARCHIVE_GROUPS=(
    "legacy-film-batches|pipeline/legacy-film"
    "rebuilds-2026-09-23-to-25|pipeline/rebuilds/2026-09-23T0330Z pipeline/rebuilds/2026-09-23T0725Z pipeline/rebuilds/2026-09-23T1053Z pipeline/rebuilds/2026-09-23T1344Z pipeline/rebuilds/2026-09-24T2027Z pipeline/rebuilds/2026-09-25T0100Z"
    "video-editor-work-leftovers|agents/video-editor/work/cf0116-sample agents/video-editor/work/cf0117-sample agents/video-editor/work/cf0130-frames agents/video-editor/work/cf0162-ambient"
)
# Пустые каталоги: архивировать нечего, убираются `rmdir` (только если пусты).
EMPTY_DIRS=(agents/video-editor/videos agents/analyst)
# Группы, чьи батчи несут 05-video-editor.json - перед их удалением спрашивается реестр.
LEDGER_GROUPS=" legacy-film-batches rebuilds-2026-09-23-to-25 "

die() { echo "СТОП: $*" >&2; exit 1; }
LOG=""
log() { echo "$*"; [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; return 0; }

no_open_batch() {
    local rc=0
    "$RUNLOG" batch-active --root "$FACTORY_ROOT" >/dev/null 2>&1 || rc=$?
    case $rc in
        1) return 0 ;;
        0) die "открыт батч (runlog batch-active) - дождаться его закрытия" ;;
        *) die "runlog batch-active завершился с кодом $rc - открытость батча не проверена" ;;
    esac
}

# Опись оригиналов -> zip (готовый не пересобирается) -> unzip -t -> распаковка
# во временный каталог на томе архива, sha256 каждого файла против описи и то же
# число файлов. Любое расхождение - СТОП, оригиналы не трогаются.
zip_and_verify() {
    local name="$1" paths="$2" zip_path="$3" sums="$4" count verify got zsum

    # 1. Опись оригиналов: sha256 каждого файла, пути относительно FACTORY_ROOT.
    # shellcheck disable=SC2086
    (cd "$FACTORY_ROOT" && find $paths -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$sums.tmp"
    count=$(wc -l < "$sums.tmp" | tr -d ' ')
    [ "$count" -gt 0 ] || die "$name: в оригиналах нет ни одного файла"
    mv "$sums.tmp" "$sums"

    # 2. Zip (готовый не пересобирается - пересверяется).
    if [ ! -f "$zip_path" ]; then
        # shellcheck disable=SC2086
        (cd "$FACTORY_ROOT" && zip -r -q -X -y "$zip_path.tmp" $paths)
        mv "$zip_path.tmp" "$zip_path"
    fi

    # 3. Целостность архива.
    unzip -tq "$zip_path" >/dev/null || die "$name: unzip -t не прошёл - оригиналы не трогаю"

    # 4. Сверка: распаковать во временный каталог на томе архива, sha256 каждого
    #    файла против описи оригиналов, и число файлов - то же самое.
    verify="$ARCHIVE_DIR/.verify-$name"
    rm -rf "$verify"; mkdir -p "$verify"
    unzip -q "$zip_path" -d "$verify"
    got=$(cd "$verify" && find . -type f | wc -l | tr -d ' ')
    if ! (cd "$verify" && shasum -a 256 -c --quiet "$sums"); then
        rm -rf "$verify"; die "$name: sha256 распакованного не совпал с оригиналами - оригиналы не трогаю"
    fi
    rm -rf "$verify"
    [ "$got" -eq "$count" ] || die "$name: в zip $got файлов, в оригиналах $count - оригиналы не трогаю"
    zsum=$(shasum -a 256 "$zip_path" | awk '{print $1}')
    log "$name: $(echo "$paths" | wc -w | tr -d ' ') путей, $count файлов -> $zip_path ($(du -h "$zip_path" | cut -f1), sha256 $zsum); unzip -t и sha256 всех файлов сошлись"
}

[ -d "$FACTORY_ROOT" ] || die "нет корня фабрики $FACTORY_ROOT"
[ -d "$(dirname "$ARCHIVE_DIR")" ] || die "нет $(dirname "$ARCHIVE_DIR") - Archive не смонтирован?"
mkdir -p "$ARCHIVE_DIR"
LOG="$ARCHIVE_DIR/cleanup.log"
no_open_batch

if [ -n "$REPACK" ]; then
    g=""
    for cand in "${ARCHIVE_GROUPS[@]}"; do
        [ "${cand%%|*}" = "$REPACK" ] && g="$cand"
    done
    [ -n "$g" ] || die "нет группы $REPACK (есть: $(for c in "${ARCHIVE_GROUPS[@]}"; do printf '%s ' "${c%%|*}"; done))"
    paths="${g#*|}"
    for p in $paths; do
        [ -e "$FACTORY_ROOT/$p" ] || die "$REPACK: нет оригинала $p - перепаковывать не из чего"
    done
    new="$ARCHIVE_DIR/$REPACK.zip.repack"
    rm -f "$new" "$new.tmp" "$new.sha256"
    free_kb=$(df -k "$ARCHIVE_DIR" | awk 'NR==2 {print $4}')
    # shellcheck disable=SC2086
    need_kb=$(cd "$FACTORY_ROOT" && du -sk $paths | awk '{s+=$1} END {print s+0}')
    [ $((need_kb * 2)) -le "$free_kb" ] || die "на томе архива свободно $((free_kb / 1024)) МБ, нужно ~$((need_kb * 2 / 1024)) МБ"
    log "$REPACK: перепаковка - новый zip рядом со старым"
    zip_and_verify "$REPACK" "$paths" "$new" "$new.sha256"
    old_sum="нет"
    [ -f "$ARCHIVE_DIR/$REPACK.zip" ] && old_sum=$(shasum -a 256 "$ARCHIVE_DIR/$REPACK.zip" | awk '{print $1}')
    mv -f "$new" "$ARCHIVE_DIR/$REPACK.zip"
    mv -f "$new.sha256" "$ARCHIVE_DIR/$REPACK.sha256"
    log "$REPACK: старый zip (sha256 $old_sum) заменён сверенным новым; оригиналы на месте"
    exit 0
fi

# Что делать с каждой группой: archive (оригиналы на месте), skip (zip есть, оригиналов нет).
declare -a TODO=()
need_kb=0
for g in "${ARCHIVE_GROUPS[@]}"; do
    name="${g%%|*}"; paths="${g#*|}"
    present=0; missing=0
    for p in $paths; do
        if [ -e "$FACTORY_ROOT/$p" ]; then present=$((present + 1)); else missing=$((missing + 1)); fi
    done
    if [ "$present" -eq 0 ] && [ -f "$ARCHIVE_DIR/$name.zip" ]; then
        log "$name: оригиналов нет, $name.zip на месте - уже сделано, пропускаю"
        continue
    fi
    [ "$missing" -eq 0 ] || die "$name: часть путей отсутствует ($missing из $((present + missing))) - разобраться руками"
    TODO+=("$g")
    if [ ! -f "$ARCHIVE_DIR/$name.zip" ]; then
        # shellcheck disable=SC2086
        kb=$(cd "$FACTORY_ROOT" && du -sk $paths | awk '{s+=$1} END {print s+0}')
        need_kb=$((need_kb + kb))
    fi
done

free_kb=$(df -k "$ARCHIVE_DIR" | awk 'NR==2 {print $4}')
# x2: zip рядом с временной распаковкой для сверки.
if [ $((need_kb * 2)) -gt "$free_kb" ]; then
    die "на томе архива свободно $((free_kb / 1024)) МБ, нужно ~$((need_kb * 2 / 1024)) МБ (zip + распаковка для сверки)"
fi
log "к архивации $((need_kb / 1024)) МБ, на томе свободно $((free_kb / 1024)) МБ"

for g in ${TODO[@]+"${TODO[@]}"}; do
    name="${g%%|*}"; paths="${g#*|}"
    if [ -f "$ARCHIVE_DIR/$name.zip" ]; then
        log "$name: $name.zip уже есть - сверяю его заново"
    fi
    zip_and_verify "$name" "$paths" "$ARCHIVE_DIR/$name.zip" "$ARCHIVE_DIR/$name.sha256"
done

if [ "$DELETE" -ne 1 ]; then
    log "сверка закончена; оригиналы на месте (удаление - только с --delete-originals)"
    exit 0
fi

# Удаление: ещё раз - батч закрыт, реестр догнал диск.
no_open_batch
for g in ${TODO[@]+"${TODO[@]}"}; do
    name="${g%%|*}"
    case "$LEDGER_GROUPS" in
        *" $name "*)
            out=$("$PYTHON" "$ROTATE" backfill "$CHANNEL" --check 2>&1) \
                || die "реестр ротации $CHANNEL отстаёт от диска (rotate.py backfill $CHANNEL --check): сначала \`rotate.py backfill $CHANNEL\`, потом повторить. $out"
            break ;;
    esac
done

for g in ${TODO[@]+"${TODO[@]}"}; do
    name="${g%%|*}"; paths="${g#*|}"
    [ -f "$ARCHIVE_DIR/$name.zip" ] && [ -f "$ARCHIVE_DIR/$name.sha256" ] || die "$name: нет zip/описи - не удаляю"
    for p in $paths; do
        target="$FACTORY_ROOT/$p"
        log "удаляю: $target"
        rm -rf -- "$target"
    done
done
for p in "${EMPTY_DIRS[@]}"; do
    target="$FACTORY_ROOT/$p"
    if [ -d "$target" ]; then
        if [ -z "$(ls -A "$target")" ]; then
            log "удаляю пустой каталог: $target"
            rmdir -- "$target"
        else
            log "НЕ удаляю $target: каталог не пуст"
        fi
    fi
done
log "готово: оригиналы удалены, архив в $ARCHIVE_DIR"

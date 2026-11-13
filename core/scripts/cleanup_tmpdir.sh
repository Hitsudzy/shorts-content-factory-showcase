#!/bin/bash
# CF-0501 (веха 1.6.4 «Уборка»): уборка старых фабричных деревьев в $TMPDIR -
# остатков прогонов тестов и проверочных повторов (решение пользователя 03.10:
# удалить, без переноса в архив).
#
# Без флага скрипт только перечисляет: число, размер и возраст по классам, и
# сколько записей он НЕ тронет. С `--delete` удаляет - только каталоги верхнего
# уровня корня, только классы из белого списка ниже, только старше
# MIN_AGE_HOURS (по самому свежему mtime во всём дереве, чтобы не задеть идущий
# прогон), каждый путь печатается и пишется в журнал вместе с итогом до/после.
#
# Белый список (выведен из кода корня и agents/* ветки release/1.6 + замер 03.10):
#   по имени:  rt-* (раннеры run_tests.py), leaky-*/clean-* (их тест),
#              th-runlog-*, th-apikey-* (trend-hunter), cc-runlog-* (compliance-checker),
#              ve-runlog-*, ve-text-gates-*, ve-script-anchors-* (video-editor),
#              run-tests-* (раннер video-editor), frame-judge-contract-*,
#              text_gates.*, publication-hold-*, cr-fact-*, cut-shortlist-*,
#              hook-openers-*, blooper-relax-*, cfNNNN-* (тесты/замеры корня),
#              remotion-webpack-bundle-*, react-motion-render* (рендер video-editor)
#   по содержимому: безымянные `tmpXXXXXXXX` (mkdtemp) и `tmp.XXXXXXXXXX`
#              (mktemp -d), в которых на верхнем уровне есть фабричный след
#              (channels/, patterns/, plan.json, RUN_EVENTS.jsonl,
#              NNN-<агент>.json, *.shots.json, ...) - класс tmp-factory;
#              пустые такие же каталоги - класс tmp-empty (только rmdir).
# Всё остальное (com.apple.*, сокеты, файлы, claude-*, кэши IDE/Chrome,
# remotion-v*, безымянные tmp* без фабричного следа) не трогается никогда.
#
# Запуск:
#   bash scripts/cleanup_tmpdir.sh            # только список и итог
#   bash scripts/cleanup_tmpdir.sh --delete   # удалить (пользователь)
#   --min-age-hours N   порог возраста (по умолчанию 24)
#   --verbose           в режиме списка печатать каждый путь
#   --json              (CF-0720) вместо текста - один JSON на stdout: записи
#                       фабричных классов (имя, класс, действие rm|rmdir|keep,
#                       КБ, возраст, selected), итог, by/via, only и - с
#                       --delete - результат (removed, failed); строки журнала
#                       тогда идут в stderr. Без --delete это сухой прогон той же
#                       формы, что и настоящий.
#   --only ИМЕНА        (CF-0720) только эти записи (через запятую; флаг можно
#                       повторять). Имя, которого нет в списке на удаление
#                       (нет в корне, не фабричное, моложе порога) - отказ,
#                       код 2, ничего не удалено.
#   --by КТО --via ОТКУДА  (CF-0720) кто и откуда - строкой «кто:» в журнал и в JSON;
#                       короткая непустая строка (до 40 символов, одной строкой)
#
# Подменяемо для теста:
#   CLEANUP_TMPDIR_ROOT  корень (по умолчанию $TMPDIR)
#   CLEANUP_LOG          журнал (по умолчанию <репо>/scripts/cleanup_tmpdir.log)
#   NOW                  «сейчас», epoch-секунды (по умолчанию текущее время)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_IN="${CLEANUP_TMPDIR_ROOT:-${TMPDIR:-}}"
LOG="${CLEANUP_LOG:-$SCRIPT_DIR/cleanup_tmpdir.log}"
MIN_AGE_HOURS=24
DELETE=0
VERBOSE=0
JSON=0
ONLY=""
ONLY_SET=0
BY=""; BY_SET=0
VIA=""; VIA_SET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --delete) DELETE=1 ;;
        --verbose) VERBOSE=1 ;;
        --json) JSON=1 ;;
        --min-age-hours) shift; MIN_AGE_HOURS="${1:-}" ;;
        --only) [ $# -ge 2 ] || { echo "--only ждёт имена" >&2; exit 2; }
                shift; ONLY="${ONLY:+$ONLY,}$1"; ONLY_SET=1 ;;
        --by) [ $# -ge 2 ] || { echo "--by ждёт значение" >&2; exit 2; }
              shift; BY="$1"; BY_SET=1 ;;
        --via) [ $# -ge 2 ] || { echo "--via ждёт значение" >&2; exit 2; }
               shift; VIA="$1"; VIA_SET=1 ;;
        -h|--help) sed -n '2,49p' "$0"; exit 0 ;;
        *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "СТОП: $*" >&2; exit 1; }
refuse() { echo "СТОП: $*" >&2; exit 2; }
# CF-0720: by/via - короткая непустая строка одной строкой (как notify._who)
who() {  # $1 имя, $2 значение
    local v="$2"
    v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
    [ -n "$v" ] || refuse "$1='$2': короткая непустая строка (user, center) или не задано вовсе"
    case "$v" in *$'\t'*|*$'\n'*|*$'\r'*) refuse "$1: одной строкой, без табуляций" ;; esac
    [ "${#v}" -le 40 ] || refuse "$1: не длиннее 40 символов"
    printf '%s' "$v"
}
if [ "$BY_SET" = 1 ]; then BY="$(who by "$BY")" || exit 2; fi
if [ "$VIA_SET" = 1 ]; then VIA="$(who via "$VIA")" || exit 2; fi
if [ "$ONLY_SET" = 1 ] && [ -z "${ONLY//[,[:space:]]/}" ]; then refuse "--only: не названо ни одного имени"; fi
[[ "$MIN_AGE_HOURS" =~ ^[0-9]+$ ]] || die "--min-age-hours ждёт целое число часов, дано '$MIN_AGE_HOURS'"
[ -n "$ROOT_IN" ] || die "корень не задан (нет ни CLEANUP_TMPDIR_ROOT, ни TMPDIR)"
case "$ROOT_IN" in /*) ;; *) die "корень должен быть абсолютным путём: $ROOT_IN" ;; esac
[ -d "$ROOT_IN" ] || die "корня нет: $ROOT_IN"
ROOT="$(cd "$ROOT_IN" && pwd -P)"
case "$ROOT" in /|/Users|/home/*/|"$HOME"|/private|/var|/tmp|/private/tmp|/private/var) die "корень слишком широкий: $ROOT" ;; esac

log() {
    if [ "$JSON" = 1 ]; then echo "$*" >&2; else echo "$*"; fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; return 0
}

# Классификатор: одна строка TSV на запись верхнего уровня корня -
# класс \t действие(rm|rmdir|keep) \t размер_КБ \t возраст_ч \t имя
classify() {
    ROOT="$ROOT" MIN_AGE_HOURS="$MIN_AGE_HOURS" NOW="${NOW:-}" python3 - <<'PY'
import os, re, stat, sys, time
root = os.environ["ROOT"]
now = float(os.environ["NOW"] or time.time())
NAMED = [
    ("rt", r"rt-.*"), ("leaky", r"leaky-.*"), ("clean", r"clean-.*"),
    ("th-runlog", r"th-runlog-.*"), ("th-apikey", r"th-apikey-.*"),
    ("cc-runlog", r"cc-runlog-.*"), ("ve-runlog", r"ve-runlog-.*"),
    ("ve-text-gates", r"ve-text-gates-.*"), ("ve-script-anchors", r"ve-script-anchors-.*"),
    ("run-tests", r"run-tests-.*"), ("frame-judge-contract", r"frame-judge-contract-.*"),
    ("text_gates", r"text_gates\..*"), ("publication-hold", r"publication-hold-.*"),
    ("cr-fact", r"cr-fact-.*"), ("cut-shortlist", r"cut-shortlist-.*"),
    ("hook-openers", r"hook-openers-.*"), ("blooper-relax", r"blooper-relax-.*"),
    ("cfNNNN", r"cf\d{4}-.*"),
    ("remotion-bundle", r"remotion-webpack-bundle-.*"), ("react-motion-render", r"react-motion-render.*"),
]
NAMED = [(c, re.compile(p)) for c, p in NAMED]
GENERIC = re.compile(r"tmp[a-z0-9_]{8}|tmp\.[A-Za-z0-9]{10}")
SIG = re.compile(
    r"(channels|patterns|plan\.json|plan\.score\.json|pipeline|inserts|RUN_EVENTS\.jsonl"
    r"|example-film(\.json|\.csv)?|resolve_anchors\.py|runlog|numbered|slow-channel\.json"
    r"|.*-(content-researcher|trend-hunter|video-editor|compliance-checker|footage-indexer|publisher)\.json"
    r"|.*-footage-index\.json|.*\.shots\.json|_degraded_still_\d+\.png|_probe_\d+\.png"
    r"|lf-.*|vgr-.*|sig-.*\.json|th-runlog-.*|shot_\d+(_full)?\.png)")

def walk(p):
    size, newest = 0, 0.0
    for dp, dn, fn in os.walk(p, onerror=lambda e: None):
        try:
            newest = max(newest, os.lstat(dp).st_mtime)
        except OSError:
            pass
        for f in fn:
            try:
                st = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            size += st.st_blocks * 512
            newest = max(newest, st.st_mtime)
    return size, newest

for e in sorted(os.scandir(root), key=lambda e: e.name):
    name = e.name
    try:
        st = e.stat(follow_symlinks=False)
    except OSError:
        continue
    if "\t" in name or "\n" in name:
        continue
    if not stat.S_ISDIR(st.st_mode):
        print(f"other\tkeep\t{st.st_blocks // 2}\t0\t{name}")
        continue
    cls = next((c for c, rx in NAMED if rx.fullmatch(name)), None)
    mode = "rm"
    if cls is None and GENERIC.fullmatch(name):
        try:
            kids = os.listdir(e.path)
        except OSError:
            kids = None
        if kids == []:
            cls, mode = "tmp-empty", "rmdir"
        elif kids and any(SIG.fullmatch(k) for k in kids):
            cls = "tmp-factory"
    if cls is None:
        print(f"other\tkeep\t0\t0\t{name}")
        continue
    size, newest = walk(e.path)
    age_h = (now - max(newest, st.st_mtime)) / 3600
    if age_h < float(os.environ["MIN_AGE_HOURS"]):
        cls, mode = cls + " (моложе порога)", "keep"
    print(f"{cls}\t{mode}\t{size // 1024}\t{age_h:.1f}\t{name}")
PY
}

summary() {  # stdin: TSV классификатора
    awk -F'\t' '
        { n[$1]++; kb[$1]+=$3; if (!($1 in mx) || $4>mx[$1]) mx[$1]=$4; if (!($1 in mn) || $4<mn[$1]) mn[$1]=$4
          if ($2=="rm"||$2=="rmdir") { tn++; tkb+=$3 } else { kn++; kkb+=$3 } }
        END {
          for (c in n) if (c!="other") printf "  %6d шт  %9.1f МБ  возраст %3.0f-%3.0f ч  %s\n", n[c], kb[c]/1024, mn[c], mx[c], c | "LC_ALL=C sort -k8"
          close("LC_ALL=C sort -k8")
          printf "  %6d шт  не фабричное (не трогается)\n", n["other"]
          printf "ИТОГО к удалению: %d шт, %.2f ГБ; не тронет: %d записей\n", tn, tkb/1048576, kn
        }'
}

TSV="$(mktemp "${TMPDIR:-/tmp}/cleanup-tmpdir-list.XXXXXX")"
SEL="$(mktemp "${TMPDIR:-/tmp}/cleanup-tmpdir-sel.XXXXXX")"
RES="$(mktemp "${TMPDIR:-/tmp}/cleanup-tmpdir-res.XXXXXX")"
trap 'rm -f "$TSV" "$SEL" "$RES"' EXIT
classify > "$TSV"

# CF-0720: что именно удаляется - все записи на удаление или только --only;
# имя не из списка на удаление - отказ до любого удаления.
select_rows() {
    TSV="$TSV" ONLY="$ONLY" ONLY_SET="$ONLY_SET" python3 - <<'PY'
import os, sys
rows = [l.rstrip("\n").split("\t") for l in open(os.environ["TSV"], encoding="utf-8") if l.strip()]
go = {r[4]: r for r in rows if len(r) == 5 and r[1] in ("rm", "rmdir")}
if os.environ["ONLY_SET"] == "1":
    names = [n.strip() for n in os.environ["ONLY"].split(",") if n.strip()]
    bad = [n for n in names if n not in go]
    if bad:
        print("не в списке на удаление (нет в корне, не фабричное или моложе порога): "
              + ", ".join(bad), file=sys.stderr)
        sys.exit(2)
    want = set(names)
else:
    want = set(go)
for r in rows:
    if len(r) == 5 and r[4] in want and r[1] in ("rm", "rmdir"):
        print("\t".join(r))
PY
}
if ! select_rows > "$SEL"; then
    echo "СТОП: --only: ничего не удалено" >&2
    exit 2
fi

as_json() {  # $1 - 1, если был настоящий прогон
    TSV="$TSV" SEL="$SEL" RES="$RES" DONE="$1" ROOT="$ROOT" MIN_AGE_HOURS="$MIN_AGE_HOURS" \
    ONLY="$ONLY" ONLY_SET="$ONLY_SET" BY="$BY" BY_SET="$BY_SET" VIA="$VIA" VIA_SET="$VIA_SET" \
    python3 - <<'PY'
import json, os
env = os.environ
rows = [l.rstrip("\n").split("\t") for l in open(env["TSV"], encoding="utf-8") if l.strip()]
sel = {l.rstrip("\n").split("\t")[4] for l in open(env["SEL"], encoding="utf-8") if l.strip()}
entries, other = [], 0
for cls, mode, kb, age, name in (r for r in rows if len(r) == 5):
    if cls == "other":
        other += 1
        continue
    entries.append({"name": name, "class": cls, "action": mode, "kb": int(kb),
                    "age_h": float(age), "selected": name in sel})
chosen = [e for e in entries if e["selected"]]
result = None
if env["DONE"] == "1":
    result = {"removed": [], "failed": []}
    for line in open(env["RES"], encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if parts[0] == "removed":
            result["removed"].append(parts[1])
        elif parts[0] == "failed":
            result["failed"].append({"name": parts[1], "why": parts[2] if len(parts) > 2 else ""})
print(json.dumps({
    "root": env["ROOT"], "min_age_hours": int(env["MIN_AGE_HOURS"]),
    "dry_run": env["DONE"] != "1",
    "by": env["BY"] if env["BY_SET"] == "1" else None,
    "via": env["VIA"] if env["VIA_SET"] == "1" else None,
    "only": ([n.strip() for n in env["ONLY"].split(",") if n.strip()]
             if env["ONLY_SET"] == "1" else None),
    "entries": entries,
    "totals": {"selected": len(chosen), "selected_kb": sum(e["kb"] for e in chosen),
               "kept": sum(1 for e in entries if e["action"] == "keep") + other,
               "not_factory": other},
    "result": result,
}, ensure_ascii=False, indent=2))
PY
}

if [ "$DELETE" = 0 ]; then
    if [ "$JSON" = 1 ]; then
        as_json 0
        exit 0
    fi
    echo "Корень: $ROOT (порог возраста ${MIN_AGE_HOURS} ч; режим: только список)"
    summary < "$TSV"
    if [ "$VERBOSE" = 1 ]; then
        awk -F'\t' -v r="$ROOT" '$2!="keep" { printf "%s\t%s/%s\n", $1, r, $5 }' "$TSV"
    fi
    echo "Удалить: bash $0 --delete"
    exit 0
fi

log "=== CF-0501 cleanup_tmpdir --delete: корень $ROOT, порог ${MIN_AGE_HOURS} ч"
if [ "$BY_SET" = 1 ] || [ "$VIA_SET" = 1 ]; then log "кто: by ${BY:--}, via ${VIA:--}"; fi
if [ "$ONLY_SET" = 1 ]; then log "только: $ONLY"; fi
log "--- до:"
summary < "$TSV" | while IFS= read -r l; do log "$l"; done
log "до: всего записей в корне $(find "$ROOT" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' '), объём $(du -sk "$ROOT" 2>/dev/null | cut -f1) КБ"

removed=0; failed=0
while IFS=$'\t' read -r cls mode kb age name; do
    [ "$mode" = rm ] || [ "$mode" = rmdir ] || continue
    path="$ROOT/$name"
    # Повторные проверки перед каждым удалением: имя без '/', не '.'/'..',
    # каталог (не симлинк), лежит прямо в корне.
    case "$name" in */*|.|..|"") log "ПРОПУСК (имя): $path"; printf 'failed\t%s\tимя\n' "$name" >> "$RES"; failed=$((failed+1)); continue ;; esac
    if [ -L "$path" ] || [ ! -d "$path" ]; then log "ПРОПУСК (не каталог): $path"; printf 'failed\t%s\tне каталог\n' "$name" >> "$RES"; failed=$((failed+1)); continue; fi
    parent="$(cd "$path/.." && pwd -P)"
    [ "$parent" = "$ROOT" ] || { log "ПРОПУСК (вне корня): $path"; printf 'failed\t%s\tвне корня\n' "$name" >> "$RES"; failed=$((failed+1)); continue; }
    if [ "$mode" = rmdir ]; then
        if rmdir "$path" 2>/dev/null; then log "rmdir $path"; printf 'removed\t%s\n' "$name" >> "$RES"; removed=$((removed+1)); else log "ПРОПУСК (уже не пуст): $path"; printf 'failed\t%s\tуже не пуст\n' "$name" >> "$RES"; failed=$((failed+1)); fi
    else
        if rm -rf -- "$path"; then log "rm -rf $path  [$cls, ${kb} КБ, ${age} ч]"; printf 'removed\t%s\n' "$name" >> "$RES"; removed=$((removed+1)); else log "ОШИБКА rm: $path"; printf 'failed\t%s\tошибка rm\n' "$name" >> "$RES"; failed=$((failed+1)); fi
    fi
done < "$SEL"

log "--- после: удалено $removed, пропущено/ошибок $failed"
classify | summary | while IFS= read -r l; do log "$l"; done
log "после: всего записей в корне $(find "$ROOT" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' '), объём $(du -sk "$ROOT" 2>/dev/null | cut -f1) КБ"
if [ "$JSON" = 1 ]; then as_json 1; fi
[ "$failed" = 0 ]

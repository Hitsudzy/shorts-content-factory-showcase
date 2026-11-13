#!/usr/bin/env bash
# CC-0042: прогнать команду несколько раз подряд под искусственной нагрузкой на CPU —
# проверить, что тесты центра не падают по таймауту рядом с полным прогоном фабрики.
#
#   scripts/under-load.sh [-n LOADERS] [-r RUNS] -- <команда…>
#   scripts/under-load.sh -- npm test
#   scripts/under-load.sh -n 16 -r 3 -- npm run e2e
#
# LOADERS — сколько фоновых `yes > /dev/null` (по умолчанию — число ядер), RUNS — сколько
# раз подряд (по умолчанию 3). Нагрузка снимается всегда — и при падении, и по Ctrl-C:
# скрипт убивает только свои процессы по PID, ничего по шаблону.
# Если у фабрики открыт батч (`scripts/runlog batch-active` в её корне), нагрузку не
# добавляет и выходит с кодом 3. Корень фабрики — CC_FACTORY_ROOT, иначе папка над репо центра.
set -u

loaders=""
runs=3
while getopts "n:r:" opt; do
  case "$opt" in
    n) loaders="$OPTARG" ;;
    r) runs="$OPTARG" ;;
    *) echo "usage: $0 [-n LOADERS] [-r RUNS] -- <command…>" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
[ "${1:-}" = "--" ] && shift
if [ $# -eq 0 ]; then
  echo "usage: $0 [-n LOADERS] [-r RUNS] -- <command…>" >&2
  exit 2
fi
if [ -z "$loaders" ]; then
  loaders=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)
fi

here=$(cd "$(dirname "$0")" && pwd)
if [ -z "${CC_FACTORY_ROOT:-}" ]; then
  common=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
  [ -n "$common" ] && CC_FACTORY_ROOT=$(dirname "$(dirname "$common")")
fi
runlog="${CC_FACTORY_ROOT:-}/scripts/runlog"
if [ -x "$runlog" ] && "$runlog" batch-active >/dev/null 2>&1; then
  echo "under-load: у фабрики открыт батч ($runlog batch-active) — нагрузку не добавляю" >&2
  exit 3
fi

pids=()
stop_load() {
  if [ ${#pids[@]} -gt 0 ]; then
    kill "${pids[@]}" 2>/dev/null
    wait "${pids[@]}" 2>/dev/null
    pids=()
  fi
}
trap stop_load EXIT
trap 'stop_load; exit 130' INT TERM

load() { uptime | sed 's/.*load averages*: *//'; }

for _ in $(seq "$loaders"); do
  yes >/dev/null &
  pids+=($!)
done
echo "under-load: $loaders × yes (PID ${pids[*]}), $runs прогон(а): $*"
sleep 5

summary=()
failed=0
for i in $(seq "$runs"); do
  before=$(load)
  start=$(date +%s)
  "$@"
  code=$?
  line="run $i/$runs: exit $code, $(($(date +%s) - start)) с, load до [$before] после [$(load)]"
  echo "under-load: $line"
  summary+=("$line")
  [ $code -ne 0 ] && failed=$((failed + 1))
done

stop_load
echo "under-load: итог — $((runs - failed))/$runs зелёных"
printf '  %s\n' "${summary[@]}"
[ $failed -eq 0 ]

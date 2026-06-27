#!/usr/bin/env bash
# Run generated services_skill entries and collect fault artifacts, without judging.
# Usage:
#   bash run_skill_demos.sh                  # all services_skill entries
#   bash run_skill_demos.sh 1 5              # 1-based inclusive slice
#   bash run_skill_demos.sh --list           # dry-run: list services that would run
#   bash run_skill_demos.sh --failed RUN_TS  # retry only services with no fault artifacts in RUN_TS
#   bash run_skill_demos.sh --failed RUN_TS --list
#
# ENV overrides:
#   MAX_PARALLEL   max concurrent service runners  (default: 1)
#   RUN_TS         shared run timestamp             (default: current UTC timestamp)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
if [[ -f "${VIBE_VENV:-.venv}/bin/activate" ]]; then
  source "${VIBE_VENV:-.venv}/bin/activate"
fi

mapfile -t SERVICES < <(find services_skill -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | grep -E '^[0-9]+-' | sort -V || true)
if [[ ${#SERVICES[@]} -eq 0 ]]; then
  echo "no services_skill entries found; run: make skill-specs LIMIT=5 && make skill-materialize LIMIT=5"
  exit 2
fi

START_IDX=0
END_IDX=$(( ${#SERVICES[@]} - 1 ))

FAILED_ONLY=0
FAILED_RUN_TS=""
LIST_ONLY=0

if [[ "${1:-}" == "--failed" ]]; then
  FAILED_ONLY=1
  FAILED_RUN_TS="${2:-}"
  if [[ -z "$FAILED_RUN_TS" ]]; then
    echo "error: --failed requires RUN_TS" >&2
    exit 2
  fi
  shift 2
fi

if [[ "${1:-}" == "--list" ]]; then
  LIST_ONLY=1
  shift
fi

if [[ -n "${1:-}" ]]; then
  START_IDX=$(( $1 - 1 ))
  END_IDX=$(( ${2:-$1} - 1 ))
fi

BATCH_TS="${RUN_TS:-${FAILED_RUN_TS:-$(date -u +%Y%m%dT%H%M%SZ)}}"
LOG_DIR="runs/_skill_${BATCH_TS}"
mkdir -p "$LOG_DIR"

if [[ "$FAILED_ONLY" -eq 1 ]]; then
  SELECTED_SERVICES=()
  for svc in "${SERVICES[@]}"; do
    fault_count="$(find "runs/$svc/$FAILED_RUN_TS" -maxdepth 1 -type d -name 'F*' 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "$fault_count" == "0" ]]; then
      SELECTED_SERVICES+=("$svc")
    fi
  done
else
  SELECTED_SERVICES=( "${SERVICES[@]:$START_IDX:$(( END_IDX - START_IDX + 1 ))}" )
fi

if [[ "$LIST_ONLY" -eq 1 ]]; then
  for svc in "${SELECTED_SERVICES[@]}"; do echo "  $svc"; done
  exit 0
fi

MAX_PAR="${MAX_PARALLEL:-1}"
if ! [[ "$MAX_PAR" =~ ^[0-9]+$ ]] || [[ "$MAX_PAR" -lt 1 ]]; then
  echo "error: MAX_PARALLEL must be a positive integer (got '$MAX_PAR')" >&2
  exit 2
fi

echo "═══════════════════════════════════════════════════════════════════"
echo " Skill capture run  batch=$BATCH_TS"
echo " Services: ${#SELECTED_SERVICES[@]}  (indices $START_IDX..$END_IDX)"
if [[ "$FAILED_ONLY" -eq 1 ]]; then
  echo " Retry failed from: $FAILED_RUN_TS"
fi
echo " Max parallel: $MAX_PAR"
echo " Logs: $LOG_DIR/"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

printf "%-36s %-6s %s\n" "SERVICE" "STATUS" "ARTIFACTS"
echo "--------------------------------------------------------------------------------"

run_one() {
  local svc="$1"
  log="$LOG_DIR/${svc}.log"
  if [[ -f "$log" ]]; then
    mv "$log" "$log.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  status="OK"
  RUN_TS="$BATCH_TS" make capture-skill SVC="$svc" >"$log" 2>&1 || status="FAIL"
  latest_run="$(ls -t "runs/$svc/" 2>/dev/null | head -1 || true)"
  artifacts=""
  if [[ -n "$latest_run" ]]; then
    produced="$(find "runs/$svc/$latest_run" -maxdepth 1 -type d -name 'F*' 2>/dev/null | wc -l | tr -d ' ')"
    artifacts="run_ts=$latest_run fault_dirs=$produced"
  fi
  printf "%-36s %-6s %s\n" "$svc" "$status" "$artifacts"
}

declare -a PIDS=()

cleanup_children() {
  trap - INT TERM
  echo "" >&2
  echo "interrupt received; stopping active skill workers..." >&2

  if [[ ${#PIDS[@]} -gt 0 ]]; then
    mapfile -t child_tree < <(
      python3 - "${PIDS[@]}" <<'PY'
import subprocess
import sys

roots = {int(pid) for pid in sys.argv[1:] if pid.isdigit()}
rows = subprocess.check_output(["ps", "-eo", "pid=,ppid="], text=True).splitlines()
children = {}
for row in rows:
    parts = row.split()
    if len(parts) != 2:
        continue
    pid, ppid = map(int, parts)
    children.setdefault(ppid, []).append(pid)

seen = set()
stack = list(roots)
while stack:
    pid = stack.pop()
    if pid in seen:
        continue
    seen.add(pid)
    stack.extend(children.get(pid, []))

for pid in sorted(seen, reverse=True):
    print(pid)
PY
    )
    if [[ ${#child_tree[@]} -gt 0 ]]; then
      kill -TERM "${child_tree[@]}" 2>/dev/null || true
      sleep 1
      kill -KILL "${child_tree[@]}" 2>/dev/null || true
    fi
  fi

  echo "stopped; discard partial RUN_TS=$BATCH_TS" >&2
  exit 130
}

trap cleanup_children INT TERM

for svc in "${SELECTED_SERVICES[@]}"; do
  run_one "$svc" &
  PIDS+=("$!")
  while [[ ${#PIDS[@]} -ge $MAX_PAR ]]; do
    wait -n || true
    alive=()
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        alive+=("$pid")
      fi
    done
    PIDS=("${alive[@]}")
  done
done

for pid in "${PIDS[@]}"; do
  wait "$pid" || true
done

trap - INT TERM

echo "--------------------------------------------------------------------------------"
echo "logs: $LOG_DIR"
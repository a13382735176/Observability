#!/usr/bin/env bash
# run_parallel_demos.sh — run all services CONCURRENTLY.
#
# Prerequisites:
#   • F05-F10 faults use per-service NetworkChaos (not shared PodChaos).
#   • Each service's cleanup only touches its own chaos CRDs (APP_LABEL filter).
#
# Usage:
#   bash run_parallel_demos.sh               # all services
#   bash run_parallel_demos.sh 16 25         # services 16..25 (inclusive, by index)
#   bash run_parallel_demos.sh --list        # dry-run: list services that would run
#
# ENV overrides:
#   MAX_PARALLEL   max concurrent service runners  (default: all)
#   RUNS_DIR       override output directory        (default: vibe_coding/runs)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
if [[ -f "${VIBE_VENV:-.venv}/bin/activate" ]]; then
  source "${VIBE_VENV:-.venv}/bin/activate"
fi

BATCH_TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG_DIR="runs/_parallel_${BATCH_TS}"
mkdir -p "$LOG_DIR"

# ── collect service dirs ────────────────────────────────────────────────────
# Use version sort on numeric prefixes so 1..200 are all included.
mapfile -t ALL_SVCS < <(find services -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  | grep -E '^[0-9]+-' \
  | sort -V \
  | sed 's#^#services/#')
START_IDX=0
END_IDX=$(( ${#ALL_SVCS[@]} - 1 ))

if [[ "${1:-}" == "--list" ]]; then
  for d in "${ALL_SVCS[@]}"; do echo "  $(basename "$d")"; done
  exit 0
fi
if [[ -n "${1:-}" && "${1}" != "--"* ]]; then
  # convert 1-based service numbers to 0-based indices
  START_IDX=$(( ${1:-1} - 1 ))
  END_IDX=$(( ${2:-${#ALL_SVCS[@]}} - 1 ))
fi

SVCS=( "${ALL_SVCS[@]:$START_IDX:$(( END_IDX - START_IDX + 1 ))}" )
MAX_PAR="${MAX_PARALLEL:-${#SVCS[@]}}"
if ! [[ "$MAX_PAR" =~ ^[0-9]+$ ]] || [[ "$MAX_PAR" -lt 1 ]]; then
  echo "error: MAX_PARALLEL must be a positive integer (got '$MAX_PAR')" >&2
  exit 2
fi

echo "═══════════════════════════════════════════════════════════════════"
echo " Parallel demo run  batch=$BATCH_TS"
echo " Services: ${#SVCS[@]}  (indices $START_IDX..$END_IDX)"
echo " Max parallel: $MAX_PAR"
echo " Logs → $LOG_DIR/"
echo "═══════════════════════════════════════════════════════════════════"

# ── launch workers ──────────────────────────────────────────────────────────
declare -A PIDS        # svc_basename → pid
declare -a QUEUE=("${SVCS[@]}")
running=0

_launch_one() {
  local svc_dir="$1"
  local svc; svc="$(basename "$svc_dir")"
  local log="$LOG_DIR/${svc}.log"
  echo "[start] $svc → $log"
  (
    export RUN_TS="$BATCH_TS"
    export RUNS_DIR="$HERE/runs"
    cd "$svc_dir"
    bash run.sh demo
  ) >"$log" 2>&1 &
  PIDS["$svc"]=$!
  running=$(( running + 1 ))
}

# Seed up to MAX_PAR workers
i=0
for svc_dir in "${SVCS[@]}"; do
  [[ $i -lt $MAX_PAR ]] || break
  _launch_one "$svc_dir"
  i=$(( i + 1 ))
done
launched=$i

# As workers finish, launch remaining ones. `wait -n` reaps one completed child;
# after that, `kill -0` can identify which PID disappeared from our map.
declare -A EXIT_CODES
while [[ $launched -lt ${#SVCS[@]} ]]; do
  set +e
  wait -n
  wait_rc=$?
  set -e
  [[ $wait_rc -eq 127 ]] && break

  completed=""
  for svc in "${!PIDS[@]}"; do
    pid="${PIDS[$svc]}"
    if ! kill -0 "$pid" 2>/dev/null; then
      completed="$svc"
      break
    fi
  done

  [[ -n "$completed" ]] || continue
  EXIT_CODES["$completed"]=$wait_rc
  echo "[done] $completed (exit=$wait_rc)"
  unset 'PIDS[$completed]'

  next_dir="${SVCS[$launched]}"
  _launch_one "$next_dir"
  launched=$(( launched + 1 ))
done

# ── wait for all remaining ─────────────────────────────────────────────────
echo ""
echo "All launched. Waiting for ${#PIDS[@]} remaining workers…"
for svc in "${!PIDS[@]}"; do
  pid="${PIDS[$svc]}"
  if wait "$pid" 2>/dev/null; then
    EXIT_CODES["$svc"]=0
  else
    EXIT_CODES["$svc"]=$?
  fi
  echo "[done] $svc (exit=${EXIT_CODES[$svc]})"
done

# ── aggregate results ──────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════"
printf "%-36s %-6s  %s\n" "SERVICE" "STATUS" "JUDGE SUMMARY"
echo "───────────────────────────────────────────────────────────────────"

total_caught=0
total_faults=0
if [[ -f "${VIBE_VENV:-.venv}/bin/activate" ]]; then
  source "${VIBE_VENV:-.venv}/bin/activate"
fi

for svc_dir in "${SVCS[@]}"; do
  svc="$(basename "$svc_dir")"
  exit_code="${EXIT_CODES[$svc]:-?}"
  status="OK"
  [[ "$exit_code" != "0" ]] && status="FAIL"

  # Extract judge summary from run log
  run_log="$LOG_DIR/${svc}.log"
  summary=""
  if [[ -f "$run_log" ]]; then
    summary_path="runs/$svc/$BATCH_TS/summary.json"
    if [[ ! -f "$summary_path" ]]; then
      latest_run=$(ls -t "runs/$svc/" 2>/dev/null | head -1 || true)
      summary_path="runs/$svc/$latest_run/summary.json"
    fi
    if [[ -f "$summary_path" ]]; then
      summary=$(python3 -c '
import json, sys
path = sys.argv[1]
with open(path) as f:
    raw = json.load(f)
results = raw.get("results", raw) if isinstance(raw, dict) else raw
caught = sum(1 for r in results if isinstance(r, dict) and r.get("caught"))
parts = []
for r in results:
    if not isinstance(r, dict):
        continue
    fid = r.get("fault_id", "?")
    sym = "OK" if r.get("caught") else "MISS"
    parts.append(f"{fid}={sym}")
print(f"{caught}/{len(results)}  " + " ".join(parts))
' "$summary_path" 2>/dev/null || echo "?/?")
      total_caught=$(( total_caught + $(echo "$summary" | grep -oE '^[0-9]+' || echo 0) ))
      total_faults=$(( total_faults + $(echo "$summary" | grep -oE '/[0-9]+' | tr -d '/' | head -1 || echo 0) ))
    fi
  fi
  printf "%-36s %-6s  %s\n" "$svc" "$status" "$summary"
done

echo "───────────────────────────────────────────────────────────────────"
printf "%-36s %-6s  %s\n" "TOTAL" "" "${total_caught}/${total_faults}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Logs: $LOG_DIR/"
echo "Batch TS: $BATCH_TS"

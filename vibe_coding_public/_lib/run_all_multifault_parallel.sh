#!/usr/bin/env bash
# Run all services' fault suites concurrently with robust status accounting.
# Default is tuned for the 200-service vibe_coding benchmark.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONCURRENCY=128
PER_SERVICE_TIMEOUT="60m"
DEMO_RETRIES=1
RETRY_SLEEP="15s"
RUN_TS=""
OUT_DIR=""
ALLOW_OTHER_CAMPAIGNS=0

usage() {
  cat <<'EOF'
Usage:
  _lib/run_all_multifault_parallel.sh [options]

Options:
  -p, --parallel N            Parallel workers (default: 128)
    -t, --timeout DURATION      Per-service timeout for `run.sh capture` (default: 60m)
      --demo-retries N        Retry failed capture runs N times (default: 1)
      --retry-sleep DURATION  Sleep between retries (default: 15s)
  -r, --run-ts VALUE          Fixed run timestamp/tag (default: auto UTC)
  -o, --out-dir PATH          Output campaign directory (default: runs/chaos_multifault_<run_ts>)
      --allow-overlap         Allow starting even if another chaos_multifault xargs campaign exists
  -h, --help                  Show help

Examples:
  _lib/run_all_multifault_parallel.sh -p 128
  _lib/run_all_multifault_parallel.sh -p 128 -t 75m -r 20260526T120000Z_multifault_p128
  _lib/run_all_multifault_parallel.sh -p 64 --demo-retries 1 --retry-sleep 20s
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--parallel)
      CONCURRENCY="$2"; shift 2 ;;
    -t|--timeout)
      PER_SERVICE_TIMEOUT="$2"; shift 2 ;;
    --demo-retries)
      DEMO_RETRIES="$2"; shift 2 ;;
    --retry-sleep)
      RETRY_SLEEP="$2"; shift 2 ;;
    -r|--run-ts)
      RUN_TS="$2"; shift 2 ;;
    -o|--out-dir)
      OUT_DIR="$2"; shift 2 ;;
    --allow-overlap)
      ALLOW_OTHER_CAMPAIGNS=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2 ;;
  esac
done

if [[ -z "$RUN_TS" ]]; then
  RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)_multifault_p${CONCURRENCY}"
fi
if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="$ROOT/runs/chaos_multifault_${RUN_TS}"
fi
mkdir -p "$OUT_DIR"

if [[ "$ALLOW_OTHER_CAMPAIGNS" -eq 0 ]]; then
  existing_pid="$(pgrep -f "xargs -P .*chaos_multifault_" | head -1 || true)"
  if [[ -n "$existing_pid" ]]; then
    echo "[ERROR] Another chaos_multifault xargs campaign is running (pid=$existing_pid)." >&2
    echo "        Use --allow-overlap if you intentionally want overlap." >&2
    ps -p "$existing_pid" -o pid,etimes,cmd --no-headers || true
    exit 3
  fi
fi

# Build target list from services that have run.sh wrappers.
find "$ROOT/services" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  | sort \
  | while read -r svc; do
      [[ -f "$ROOT/services/$svc/run.sh" ]] && echo "$svc"
    done > "$OUT_DIR/targets.txt"

TOTAL="$(wc -l < "$OUT_DIR/targets.txt" | tr -d ' ')"
echo "MULTIFAULT_ALL_START run_ts=$RUN_TS total=$TOTAL parallel=$CONCURRENCY timeout=$PER_SERVICE_TIMEOUT out=$OUT_DIR"

export ROOT RUN_TS OUT_DIR PER_SERVICE_TIMEOUT DEMO_RETRIES RETRY_SLEEP

set +e
cat "$OUT_DIR/targets.txt" | xargs -P "$CONCURRENCY" -I{} bash -lc '
  set -u
  svc="$1"
  svcdir="$ROOT/services/$svc"
  logfile="$OUT_DIR/$svc.log"
  statusfile="$OUT_DIR/$svc.status"
  app_label=""
  lock_wait_s=0

  final_rc=0
  expected=0
  produced=0
  reason=""
  attempts=0
  capture_rc=1

  if [[ -f "$svcdir/run.sh" ]]; then
    app_label="$(grep -m1 "^APP_LABEL=\"" "$svcdir/run.sh" | sed -E "s/^APP_LABEL=\"([^\"]+)\".*/\1/" || true)"
  fi
  if [[ -z "$app_label" ]]; then
    app_label="$svc"
  fi

  global_locks_dir="$ROOT/runs/.app_label_locks"
  mkdir -p "$global_locks_dir"
  lockfile="$global_locks_dir/${app_label}.lock"
  exec 9>"$lockfile"
  lock_start="$(date +%s)"
  flock -x 9
  lock_wait_s="$(( $(date +%s) - lock_start ))"

  {
    echo "[START] svc=$svc app_label=$app_label lock_wait_s=$lock_wait_s at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cd "$svcdir"

    expected="$(bash run.sh list-faults | sed "/^$/d" | wc -l | tr -d " ")"
    echo "[INFO ] expected_faults=$expected"

    bash run.sh cleanup || true

    while true; do
      attempts=$((attempts + 1))
      echo "[INFO ] capture_attempt=${attempts}/$((DEMO_RETRIES + 1))"
      set +e
      timeout --preserve-status "$PER_SERVICE_TIMEOUT" env RUN_TS="$RUN_TS" bash run.sh capture
      capture_rc=$?
      set -e
      if [[ "$capture_rc" -eq 0 || "$attempts" -gt "$DEMO_RETRIES" ]]; then
        break
      fi
      echo "[WARN ] capture attempt $attempts failed with rc=$capture_rc; cleanup + retry after $RETRY_SLEEP"
      bash run.sh cleanup || true
      sleep "$RETRY_SLEEP"
    done

    run_dir="$ROOT/runs/$svc/$RUN_TS"
    if [[ -d "$run_dir" ]]; then
      produced="$(find "$run_dir" -maxdepth 1 -type d -name "F*" | wc -l | tr -d " ")"
      echo "[INFO ] produced_fault_dirs=$produced"

      if [[ "$capture_rc" -ne 0 ]]; then
        final_rc=1
        reason="capture_rc=$capture_rc attempts=$attempts"
      fi

      if [[ "$produced" -lt "$expected" ]]; then
        final_rc=1
        reason="$reason fault_dirs=$produced/$expected"
      fi

    else
      final_rc=1
      reason="$reason missing_run_dir"
    fi

    bash run.sh cleanup || true
    echo "[END  ] svc=$svc rc=$final_rc reason=${reason:-none} at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$logfile" 2>&1

  if [[ "$final_rc" -eq 0 ]]; then
    echo "$svc OK expected=$expected produced=$produced reason=${reason:-none}" > "$statusfile"
    exit 0
  else
    echo "$svc FAIL expected=$expected produced=$produced reason=${reason:-unknown}" > "$statusfile"
    exit 1
  fi
' _ {}
XRC=$?
set -e

WRITTEN="$(ls "$OUT_DIR"/*.status 2>/dev/null | wc -l | tr -d ' ')"
OK="$(grep -h ' OK ' "$OUT_DIR"/*.status 2>/dev/null | wc -l | tr -d ' ')"
FAIL="$(grep -h ' FAIL ' "$OUT_DIR"/*.status 2>/dev/null | wc -l | tr -d ' ')"

echo "MULTIFAULT_ALL_DONE run_ts=$RUN_TS xargs_rc=$XRC completed=$WRITTEN/$TOTAL ok=$OK fail=$FAIL out=$OUT_DIR"

echo "$RUN_TS" > "$OUT_DIR/RUN_TS.txt"
exit "$XRC"

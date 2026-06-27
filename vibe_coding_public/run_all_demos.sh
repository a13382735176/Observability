#!/usr/bin/env bash
# Run demo for every service sequentially and collect results.
# Usage: bash run_all_demos.sh [start_index]  (0-based, default=0)
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f "${VIBE_VENV:-.venv}/bin/activate" ]]; then
  source "${VIBE_VENV:-.venv}/bin/activate"
fi

SERVICES=(
  01-catalog-api
  02-cart-service
  03-order-api
  04-payment-gateway
  05-inventory-tracker
  06-user-profile
  07-session-cache
  08-notification-dispatcher
  09-order-processor
  10-search-indexer
  11-image-resizer
  12-rate-limiter-proxy
  13-auth-token-svc
  14-metrics-aggregator
  15-webhook-fanout
)

START=${1:-0}
LOG_DIR="runs/_batch_$(date +%Y%m%dT%H%M%SZ)"
mkdir -p "$LOG_DIR"

echo "Batch log: $LOG_DIR"
echo ""

for i in "${!SERVICES[@]}"; do
  [[ $i -lt $START ]] && continue
  SVC="${SERVICES[$i]}"
  echo "========================================"
  echo "[$((i+1))/15] SVC=$SVC"
  echo "========================================"

  SVC_LOG="$LOG_DIR/${SVC}.log"

  DEMO_EXIT=0
  make demo SVC="$SVC" > "$SVC_LOG" 2>&1 || DEMO_EXIT=$?

  # Always try to show summary.json (judge writes it even on partial success)
  LATEST=$(ls -t "runs/$SVC/" 2>/dev/null | head -1 || true)
  if [[ -n "$LATEST" && -f "runs/$SVC/$LATEST/summary.json" ]]; then
    python3 -c "
import json
with open('runs/$SVC/$LATEST/summary.json') as f:
    raw = json.load(f)
# summary.json may be a list (old format) or dict with 'results' key (new format)
data = raw.get('results', raw) if isinstance(raw, dict) else raw
total = len(data)
caught = sum(1 for r in data if isinstance(r, dict) and r.get('caught'))
print(f'  smoke=OK  caught={caught}/{total}')
for r in data:
    if not isinstance(r, dict): continue
    flag = 'OK  ' if r.get('caught') else 'MISS'
    print(f'    [{flag}] {r.get(\"fault_id\",\"?\")}  reason={r.get(\"verdict_reason\",\"?\")}')
" || echo "  (summary parse error)"
  elif [[ $DEMO_EXIT -ne 0 ]]; then
    echo "  [FAIL] demo failed (no summary) — tail of log:"
    tail -10 "$SVC_LOG" || true
  fi
  echo ""
done

echo "========================================"
echo "BATCH COMPLETE"
echo "========================================"
# Print aggregate
python3 - <<'PYEOF'
import json, os, glob

services = [
    "01-catalog-api","02-cart-service","03-order-api","04-payment-gateway",
    "05-inventory-tracker","06-user-profile","07-session-cache",
    "08-notification-dispatcher","09-order-processor","10-search-indexer",
    "11-image-resizer","12-rate-limiter-proxy","13-auth-token-svc",
    "14-metrics-aggregator","15-webhook-fanout"
]

print(f"{'Service':<30} {'Smoke':<8} {'Caught':<10} Details")
print("-" * 90)
total_faults = total_caught = 0
for svc in services:
    runs = sorted(glob.glob(f"runs/{svc}/*/summary.json"), reverse=True)
    if not runs:
        print(f"{svc:<30} {'NO RUN':<8}")
        continue
    with open(runs[0]) as f:
        raw = json.load(f)
    data = raw.get('results', raw) if isinstance(raw, dict) else raw
    n = len(data); c = sum(1 for r in data if isinstance(r, dict) and r.get("caught"))
    total_faults += n; total_caught += c
    details = " ".join(
        f"{r['fault_id']}={'✓' if r.get('caught') else '✗'}"
        for r in data if isinstance(r, dict)
    )
    print(f"{svc:<30} {'OK':<8} {c}/{n:<8} {details}")

print("-" * 90)
print(f"{'TOTAL':<30} {'':8} {total_caught}/{total_faults}")
PYEOF


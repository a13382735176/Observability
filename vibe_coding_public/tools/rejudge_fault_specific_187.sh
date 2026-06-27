#!/usr/bin/env bash
set -euo pipefail

CAMPAIGN="${1:-20260526T161758Z_multifault_p48_postfix_v2}"
PARALLEL="${PARALLEL:-24}"
STATUS_DIR="runs/chaos_multifault_${CAMPAIGN}"

if [[ ! -d "$STATUS_DIR" ]]; then
  echo "ERROR: status dir not found: $STATUS_DIR" >&2
  exit 2
fi

tmp_services="$(mktemp)"
trap 'rm -f "$tmp_services"' EXIT

# Keep only services that actually produced judge artifacts in the original run.
for f in "$STATUS_DIR"/*.status; do
  line="$(cat "$f")"
  if [[ "$line" == *"reason=demo_rc=1"* ]]; then
    continue
  fi
  echo "$line" | awk '{print $1}'
done | sort -u > "$tmp_services"

target_services="$(wc -l < "$tmp_services" | tr -d ' ')"
echo "target_services=$target_services"

# Re-judge existing run artifacts only (no rebuild/redeploy/inject).
cat "$tmp_services" | xargs -I{} -P "$PARALLEL" bash -lc '
  python3 judge/judge.py "runs/{}/'"$CAMPAIGN"'" --mode fault-specific >/dev/null 2>&1 || true
'

python3 - <<'PY' "$tmp_services" "$CAMPAIGN"
import json
import sys
from pathlib import Path

services_file = Path(sys.argv[1])
campaign = sys.argv[2]

services = [s.strip() for s in services_file.read_text().splitlines() if s.strip()]

svc_with_summary = 0
svc_all_no_signal = 0
fault_total = 0
fault_no_signal = 0

for svc in services:
    summary_path = Path("runs") / svc / campaign / "summary.json"
    if not summary_path.exists():
        continue
    summary = json.loads(summary_path.read_text())
    results = summary.get("results", [])
    if not results:
        continue

    svc_with_summary += 1
    this_svc_no_signal = 0

    for r in results:
        fault_total += 1
        if r.get("verdict_reason") == "no_signal":
            fault_no_signal += 1
            this_svc_no_signal += 1

    if this_svc_no_signal == len(results):
        svc_all_no_signal += 1

print("services_with_summary=", svc_with_summary)
if svc_with_summary:
    print("services_all_no_signal=", svc_all_no_signal)
    print("service_all_no_signal_ratio=", f"{svc_all_no_signal/svc_with_summary:.4%}")
else:
    print("services_all_no_signal=0")
    print("service_all_no_signal_ratio=NA")

print("fault_total=", fault_total)
print("fault_no_signal=", fault_no_signal)
if fault_total:
    print("fault_no_signal_ratio=", f"{fault_no_signal/fault_total:.4%}")
else:
    print("fault_no_signal_ratio=NA")
PY

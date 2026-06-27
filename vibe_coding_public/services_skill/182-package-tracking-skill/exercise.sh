# 182-package-tracking - create package and checkpoint flow.
exercise_once() {
  local base="$1"
  local tracking="trk-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/packages" \
       -H 'content-type: application/json' \
       -d '{"tracking_number":"'"$tracking"'","origin":"SEA","destination":"SFO","weight_kg":2.3}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/packages/$tracking" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/packages/$tracking/checkpoint" \
       -H 'content-type: application/json' \
       -d '{"location":"PDX","status":"in_transit"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/packages/$tracking/history" 2>&1
}

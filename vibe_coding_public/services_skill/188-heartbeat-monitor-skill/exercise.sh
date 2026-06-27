# 188-heartbeat-monitor - emit heartbeat and inspect monitor state.
exercise_once() {
  local base="$1"
  local service_id="svc-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/beat" \
       -H 'content-type: application/json' \
       -d '{"service_id":"'"$service_id"'","status_code":200}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/status/$service_id" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/alive" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/alarms" 2>&1
}

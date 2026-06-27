# 119-audit-log-svc - create and fetch actor audit events.
exercise_once() {
  local base="$1"
  local actor_id="actor-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/events" \
       -H 'content-type: application/json' \
       -d '{"actor_id":"'"$actor_id"'","action":"read","resource_type":"article","resource_id":"a-1","details":{"source":"exercise"}}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/events/$actor_id" 2>&1
}
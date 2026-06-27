# 173-usage-analytics - post events and query user aggregates.
exercise_once() {
  local base="$1"
  local user_id="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/events" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user_id"'","event_type":"click","properties":{"page":"home"}}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/events/user/$user_id" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/counts/$user_id" 2>&1
}

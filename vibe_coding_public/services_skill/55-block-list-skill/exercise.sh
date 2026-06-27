exercise_once() {
  local base="$1"
  local blocker_id blocked_id
  blocker_id="u-$RANDOM"
  blocked_id="u-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/block" \
    -H 'content-type: application/json' \
    -d '{"blocker_id":"'"$blocker_id"'","blocked_id":"'"$blocked_id"'"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/blocked/$blocker_id" 2>&1
}
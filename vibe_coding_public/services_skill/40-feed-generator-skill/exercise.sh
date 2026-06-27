exercise_once() {
  local base="$1"
  local user="u$RANDOM"
  local post_id="p$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/events" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","post_id":"'"$post_id"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/feed/$user" 2>&1
}
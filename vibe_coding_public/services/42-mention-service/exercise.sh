exercise_once() {
  local base="$1"
  local user="u$RANDOM"
  local content_id="c$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/mentions" \
       -H 'content-type: application/json' \
       -d '{"content":"hello @'"$user"'","mentioned_users":["'"$user"'"],"content_id":"'"$content_id"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/mentions/$user" 2>&1
}
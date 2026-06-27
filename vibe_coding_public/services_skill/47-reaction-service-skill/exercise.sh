exercise_once() {
  local base="$1"
  local content_id="content-$RANDOM"
  local user_id="u$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/react" \
       -H 'content-type: application/json' \
       -d '{"content_id":"'"$content_id"'","user_id":"'"$user_id"'","emoji":"like"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/reactions/$content_id" 2>&1
}
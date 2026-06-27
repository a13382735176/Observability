exercise_once() {
  local base="$1"
  local user="u$RANDOM"
  local content_id="content-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/share" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","content_id":"'"$content_id"'","platform":"timeline"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/shares/$content_id" 2>&1
}
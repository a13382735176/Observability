exercise_once() {
  local base="$1"
  local tag="topic$((RANDOM % 1000))"
  local content_id="c$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tag" \
       -H 'content-type: application/json' \
       -d '{"tag":"'"$tag"'","content_id":"'"$content_id"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/tag/$tag" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/trending" 2>&1
}
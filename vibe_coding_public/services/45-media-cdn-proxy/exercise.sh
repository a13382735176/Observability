exercise_once() {
  local base="$1"
  local media_id="m$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/media/$media_id/meta" \
       -H 'content-type: application/json' \
       -d '{"url":"https://cdn.example.com/'"$media_id"'.jpg","size_bytes":"1024"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/media/$media_id" 2>&1
}
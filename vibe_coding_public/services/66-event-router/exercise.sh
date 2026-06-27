exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/route" \
    -H 'content-type: application/json' \
    -d '{"event_type":"device.update","payload":{"id":"dev-1","status":"ok"}}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/stats" 2>&1
}
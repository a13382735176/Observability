exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -o /dev/null -w 'healthz HTTP_CODE:%{http_code}\n' \
    "$base/healthz" 2>&1 || true

  curl -sS --max-time 3 -o /dev/null -w 'business HTTP_CODE:%{http_code}\n' \
    -X POST "$base/configure" \
    -H 'content-type: application/json' \
    -d '{"key":"demo-key","limit":20,"window_seconds":60}' 2>&1 || true
}

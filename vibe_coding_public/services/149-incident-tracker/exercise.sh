exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -o /dev/null -w 'healthz HTTP_CODE:%{http_code}\n' \
    "$base/healthz" 2>&1 || true

  curl -sS --max-time 3 -o /dev/null -w 'business HTTP_CODE:%{http_code}\n' \
    "$base/incidents/active" 2>&1 || true
}

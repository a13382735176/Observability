# 111-translation-svc — drive dependency paths so chaos faults produce
# app-level observability signals in logs.
exercise_once() {
  local base="$1"
  curl -sS --max-time 4 -X POST "$base/probe" \
    -H 'content-type: application/json' \
    -d '{}' >/dev/null 2>&1 || true
}

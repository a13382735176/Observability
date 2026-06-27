# 107-embed-service - health plus dependency probe.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/probe" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
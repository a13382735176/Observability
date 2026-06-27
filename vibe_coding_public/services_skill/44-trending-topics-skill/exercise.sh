exercise_once() {
  local base="$1"
  local topic="topic$((RANDOM % 1000))"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/signal" \
       -H 'content-type: application/json' \
       -d '{"topic":"'"$topic"'","weight":2}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/trending" 2>&1
}
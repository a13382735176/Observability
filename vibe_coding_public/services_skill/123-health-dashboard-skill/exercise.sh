# 123-health-dashboard - report service health then query it.
exercise_once() {
  local base="$1"
  local svc="payment-api"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/report" \
       -H 'content-type: application/json' \
       -d '{"service_name":"'"$svc"'","status":"ok","latency_ms":42}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/health/$svc" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/health/summary" 2>&1
}
# 123-health-dashboard - publish and read service health reports.
exercise_once() {
  local base="$1"
  local svc="search-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/health/summary" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/report" \
       -H 'content-type: application/json' \
       -d '{"service_name":"'"$svc"'","status":"ok","latency_ms":42}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/health/$svc" 2>&1
}
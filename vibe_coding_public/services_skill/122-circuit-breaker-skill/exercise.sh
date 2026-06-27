# 122-circuit-breaker - probe breaker state and record/reset outcomes.
exercise_once() {
  local base="$1"
  local svc="payment-gateway"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/state/$svc" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/record" \
       -H 'content-type: application/json' \
       -d '{"service_name":"'"$svc"'","success":false}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/reset/$svc" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 122-circuit-breaker - drive breaker probe/state and mutation endpoints.
exercise_once() {
  local base="$1"
  local svc="payments-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/state/$svc" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/record" \
       -H 'content-type: application/json' \
       -d '{"service_name":"'"$svc"'","success":false}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/state/$svc" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/reset/$svc" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
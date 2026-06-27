exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/rates" \
    -H 'content-type: application/json' \
    -d '{"productType":"personal_loan","ratePct":7.5}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/calculate" \
    -H 'content-type: application/json' \
    -d '{"principalCents":1000000,"annualRatePct":7.5,"termMonths":24}' 2>&1
}
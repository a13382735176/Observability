# 178-tax-calculator - drive health and tax/rate endpoints.
exercise_once() {
  local base="$1"
  local region="us-ca"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tax" \
       -H 'content-type: application/json' \
       -d '{"region":"'"$region"'","subtotal_cents":12999}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/rates" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rates/refresh?region=$region" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}

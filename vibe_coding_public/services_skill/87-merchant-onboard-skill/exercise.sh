exercise_once() {
  local base="$1"
  local merchant_email
  merchant_email="merchant-$RANDOM@example.test"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/merchants" \
    -H 'content-type: application/json' \
    -d '{"name":"Demo Merchant","email":"'"$merchant_email"'","business_type":"retail"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/pending" 2>&1
}
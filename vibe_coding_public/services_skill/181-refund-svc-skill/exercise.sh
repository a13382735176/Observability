# 181-refund-svc - submit and query refunds.
exercise_once() {
  local base="$1"
  local order_id=$((1000 + RANDOM % 9000))

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/refunds" \
       -H 'content-type: application/json' \
       -d '{"order_id":'"$order_id"',"amount_cents":1500,"reason":"damaged"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/refunds/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/refunds/order/$order_id" 2>&1
}

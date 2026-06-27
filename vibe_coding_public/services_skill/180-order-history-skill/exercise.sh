# 180-order-history - create and query order history.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/orders" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","total_cents":4567,"item_count":2}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/user/$user/recent?n=5" 2>&1
}

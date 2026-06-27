# 19-recommendation-api - push events and fetch recommendations.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/events" \
       -H 'content-type: application/json' \
       -d '{"product_id":"sku-101","user_id":"'"$user"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/recommendations/$user" 2>&1
}

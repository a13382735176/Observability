# 18-review-service - create and fetch reviews.
exercise_once() {
  local base="$1"
  local product_id=$((100 + RANDOM % 900))

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/reviews" \
       -H 'content-type: application/json' \
       -d '{"product_id":'"$product_id"',"rating":4,"body":"solid"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/reviews/$product_id" 2>&1
}

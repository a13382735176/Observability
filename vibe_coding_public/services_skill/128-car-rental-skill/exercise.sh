# 128-car-rental - create rental and mark return.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rentals" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","vehicle_type":"sedan","pickup_date":"2026-06-01","return_date":"2026-06-03","daily_rate_cents":4999}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/rentals/$user/active" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/rentals/1/return" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 128-car-rental - create and complete rentals around active-rental reads.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rentals" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","vehicle_type":"sedan","pickup_date":"2026-06-01","return_date":"2026-06-03","daily_rate_cents":4500}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/rentals/$user/active" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/rentals/1/return" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
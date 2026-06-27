# 137-reservation-svc - create reservation, query by date, then cancel.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  local restaurant="r-1"
  local date="2026-06-15"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/reservations" \
       -H 'content-type: application/json' \
       -d '{"restaurant_id":"'"$restaurant"'","user_id":"'"$user"'","date":"'"$date"'","time":"19:00","party_size":2}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/reservations/$restaurant?date=$date" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/reservations/1/cancel" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/reservations/user/$user" 2>&1
}
# 137-reservation-svc - create and query reservations plus cancellation.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  local restaurant="resto-1"
  local day="2026-06-15"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/reservations" \
       -H 'content-type: application/json' \
       -d '{"restaurant_id":"'"$restaurant"'","user_id":"'"$user"'","date":"'"$day"'","time":"19:00","party_size":2}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/reservations/$restaurant?date=$day" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/reservations/1/cancel" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/reservations/user/$user" 2>&1
}
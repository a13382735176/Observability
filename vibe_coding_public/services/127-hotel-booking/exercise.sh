# 127-hotel-booking - create, fetch, and cancel booking.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/bookings" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","hotel_id":"h-1","room_type":"queen","check_in":"2026-06-01","check_out":"2026-06-02"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/bookings/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/bookings/1/cancel" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 127-hotel-booking - create, read, and cancel bookings.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/bookings" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","hotel_id":"H100","room_type":"queen","check_in":"2026-06-01","check_out":"2026-06-03"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/bookings/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/bookings/1/cancel" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 129-itinerary-planner - create itinerary and mutate items.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/itineraries" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","title":"Tokyo Trip","start_date":"2026-07-01","end_date":"2026-07-05"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/itineraries/1/items" \
       -H 'content-type: application/json' \
       -d '{"day":1,"activity":"Museum","location":"Ueno"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/itineraries/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/users/$user/itineraries" 2>&1
}
# 129-itinerary-planner - write itinerary data and read cached views.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/itineraries" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","title":"City Trip","start_date":"2026-07-01","end_date":"2026-07-05"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/itineraries/1/items" \
       -H 'content-type: application/json' \
       -d '{"day":1,"activity":"Museum","location":"Downtown"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/itineraries/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/users/$user/itineraries" 2>&1
}
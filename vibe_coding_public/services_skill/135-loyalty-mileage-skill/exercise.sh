# 135-loyalty-mileage - earn/redeem miles and fetch balances.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/miles/earn" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","miles":500,"source":"flight"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/miles/redeem" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","miles":200,"reward":"upgrade"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/miles/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/history/$user" 2>&1
}
# 135-loyalty-mileage - exercise earn/redeem flows and user reads.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/miles/earn" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","miles":500,"source":"flight"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/miles/redeem" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","miles":100,"reward":"upgrade"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/miles/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/history/$user" 2>&1
}
# 125-ab-test-assigner - define experiment and assign a user.
exercise_once() {
  local base="$1"
  local exp="homepage-color"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/experiments" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$exp"'","variants":["A","B"],"weights":[50,50]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/assign" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$exp"'","user_id":"'"$user"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/assignments/$user" 2>&1
}
# 125-ab-test-assigner - create experiment and request user assignment.
exercise_once() {
  local base="$1"
  local exp="homepage-$RANDOM"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/experiments" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$exp"'","variants":["A","B"],"weights":[50,50]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/assign" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$exp"'","user_id":"'"$user"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/assignments/$user" 2>&1
}
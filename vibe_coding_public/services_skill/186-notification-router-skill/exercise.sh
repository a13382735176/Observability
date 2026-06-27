# 186-notification-router - register channels and route notifications.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/channels" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","channel_type":"email","target":"'"$user"'@example.com"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/route" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","message":"ping","priority":2}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/channels/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/notifications/$user" 2>&1
}

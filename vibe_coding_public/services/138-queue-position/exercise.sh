# 138-queue-position - join queue and inspect position/length.
exercise_once() {
  local base="$1"
  local queue="support"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/queue/join" \
       -H 'content-type: application/json' \
       -d '{"queue_name":"'"$queue"'","user_id":"'"$user"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/queue/$queue/position/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/queue/$queue/length" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/queue/$queue/next" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 138-queue-position - join queue and inspect position/length.
exercise_once() {
  local base="$1"
  local queue="support"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/queue/join" \
       -H 'content-type: application/json' \
       -d '{"queue_name":"'"$queue"'","user_id":"'"$user"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/queue/$queue/position/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/queue/$queue/next" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/queue/$queue/length" 2>&1
}
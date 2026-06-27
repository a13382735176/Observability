exercise_once() {
  local base="$1"
  local post_id=$((100 + RANDOM % 900))

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/comments" \
       -H 'content-type: application/json' \
       -d '{"post_id":'"$post_id"',"user_id":"u1","text":"nice post"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/comments/$post_id" 2>&1
}
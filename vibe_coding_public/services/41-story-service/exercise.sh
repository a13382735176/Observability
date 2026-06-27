exercise_once() {
  local base="$1"
  local user="u$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/stories" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","media_url":"https://cdn.example.com/story.jpg","ttl_s":600}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stories/$user" 2>&1
}
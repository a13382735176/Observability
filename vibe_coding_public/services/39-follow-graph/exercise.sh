exercise_once() {
  local base="$1"
  local follower="u$RANDOM"
  local followee="u$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/follow" \
       -H 'content-type: application/json' \
       -d '{"follower_id":"'"$follower"'","followee_id":"'"$followee"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/followers/$followee" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/following/$follower" 2>&1
}
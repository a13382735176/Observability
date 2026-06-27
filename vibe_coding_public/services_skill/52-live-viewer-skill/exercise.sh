exercise_once() {
  local base="$1"
  local stream_id user_id
  stream_id="stream-1"
  user_id="u-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/join" \
    -H 'content-type: application/json' \
    -d '{"stream_id":"'"$stream_id"'","user_id":"'"$user_id"'"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/viewers/$stream_id" 2>&1
}
exercise_once() {
  local base="$1"
  local user_id
  user_id="user-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/verify" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","doc_type":"passport","doc_number":"P'$RANDOM'"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/status/$user_id" 2>&1
}
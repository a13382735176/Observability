exercise_once() {
  local base="$1"
  local user_id
  user_id="user-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/accounts" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","account_type":"checking","currency":"USD"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/accounts/$user_id" 2>&1
}
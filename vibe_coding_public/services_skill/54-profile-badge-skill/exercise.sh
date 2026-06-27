exercise_once() {
  local base="$1"
  local user_id
  user_id="u-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/badges/award" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","badge_id":"starter"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/badges/$user_id" 2>&1
}
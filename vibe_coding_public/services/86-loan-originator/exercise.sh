exercise_once() {
  local base="$1"
  local user_id
  user_id="user-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/loans/apply" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","amount_cents":2500000,"purpose":"working_capital"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/loans/1/status" 2>&1
}
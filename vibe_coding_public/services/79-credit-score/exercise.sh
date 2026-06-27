exercise_once() {
  local base="$1"
  local user_id
  user_id="user-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/compute" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","payment_history_pct":96.0,"credit_utilization_pct":24.5}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/score/$user_id" 2>&1
}
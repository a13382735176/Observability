exercise_once() {
  local base="$1"
  local payer_id
  local participant_a
  local participant_b
  payer_id="payer-$RANDOM"
  participant_a="user-$RANDOM"
  participant_b="user-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/split" \
    -H 'content-type: application/json' \
    -d '{"payer_id":"'"$payer_id"'","participants":[{"user_id":"'"$participant_a"'","amount_cents":1200},{"user_id":"'"$participant_b"'","amount_cents":800}],"description":"exercise split"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/splits/user/$participant_a" 2>&1
}
exercise_once() {
  local base="$1"
  local account_id
  account_id="acct-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X PUT "$base/balance/$account_id" \
    -H 'content-type: application/json' \
    -d '{"amount_cents":12345}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/balance/$account_id" 2>&1
}
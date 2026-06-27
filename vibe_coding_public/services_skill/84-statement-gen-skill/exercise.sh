exercise_once() {
  local base="$1"
  local account_id
  account_id="acct-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/generate" \
    -H 'content-type: application/json' \
    -d '{"account_id":"'"$account_id"'","from_date":"2026-01-01","to_date":"2026-01-31"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/statements/$account_id" 2>&1
}
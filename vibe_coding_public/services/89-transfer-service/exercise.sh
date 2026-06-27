exercise_once() {
  local base="$1"
  local from_account
  local to_account
  from_account="acct-$RANDOM"
  to_account="acct-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/transfers" \
    -H 'content-type: application/json' \
    -d '{"fromAccount":"'"$from_account"'","toAccount":"'"$to_account"'","amountCents":6400,"reference":"exercise transfer"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/transfers/account/$from_account" 2>&1
}
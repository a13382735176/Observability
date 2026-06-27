exercise_once() {
  local base="$1"
  local account
  account="acct-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/entries" \
    -H 'content-type: application/json' \
    -d '{"debit_account":"'"$account"'","credit_account":"merchant-main","amount_cents":875,"description":"exercise entry"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/entries/$account" 2>&1
}
exercise_once() {
  local base="$1"
  local account_id
  account_id=$((100000 + RANDOM))

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/transactions" \
    -H 'content-type: application/json' \
    -d '{"account_id":'"$account_id"',"amount_cents":4200,"tx_type":"debit","description":"exercise tx"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/transactions/$account_id" 2>&1
}
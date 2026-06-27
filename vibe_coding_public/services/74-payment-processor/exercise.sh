exercise_once() {
  local base="$1"
  local payer_id
  local payee_id
  payer_id="payer-$RANDOM"
  payee_id="payee-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/payments" \
    -H 'content-type: application/json' \
    -d '{"payer_id":"'"$payer_id"'","payee_id":"'"$payee_id"'","amount_cents":2500,"currency":"USD"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/payments/user/$payer_id" 2>&1
}
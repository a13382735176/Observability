exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/escrows" \
    -H 'content-type: application/json' \
    -d '{"payer_id":"buyer-'"$RANDOM"'","payee_id":"seller-'"$RANDOM"'","amount_cents":450000,"condition":"delivery_confirmed"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/escrows/1" 2>&1
}
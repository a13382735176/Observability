exercise_once() {
  local base="$1"
  local payment_id
  payment_id=$((200000 + RANDOM))

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/refunds" \
    -H 'content-type: application/json' \
    -d '{"payment_id":'"$payment_id"',"amount_cents":999,"reason":"exercise refund"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/refunds/$payment_id" 2>&1
}
# 04-payment-gateway (upstream) — POST a charge; service relays to mock-upstream.
exercise_once() {
  local base="$1"
  curl -sS --max-time 5 -w 'HTTP_CODE:%{http_code}\n' \
       -X POST "$base/charge" -H 'content-type: application/json' \
       -d '{"user_id":"u1","amount_cents":'"$((RANDOM % 999 + 1))"'}' 2>&1
}

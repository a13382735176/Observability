# 179-promo-engine - create and apply a promo code.
exercise_once() {
  local base="$1"
  local code="PROMO-$RANDOM"
  local valid_until="2030-01-01T00:00:00Z"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/promos" \
       -H 'content-type: application/json' \
       -d '{"code":"'"$code"'","discount_pct":15,"valid_until_iso":"'"$valid_until"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/apply" \
       -H 'content-type: application/json' \
       -d '{"code":"'"$code"'","subtotal_cents":20000}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/promos" 2>&1
}

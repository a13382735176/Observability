# 175-funnel-analyzer - define funnels and inspect conversion reads.
exercise_once() {
  local base="$1"
  local funnel_name="checkout-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/funnels" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$funnel_name"'","steps":["view","add_to_cart","purchase"]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/funnels" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/funnels/1/conversion" 2>&1
}

exercise_once() {
  local base="$1"
  local code="aff-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/affiliates" \
       -H 'content-type: application/json' \
       -d '{"code":"'"$code"'","commission_pct":12}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/click" \
       -H 'content-type: application/json' \
       -d '{"affiliate_code":"'"$code"'","product_id":101}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stats/$code" 2>&1
}
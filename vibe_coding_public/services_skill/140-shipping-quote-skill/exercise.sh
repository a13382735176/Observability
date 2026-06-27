# 140-shipping-quote - request quote and inspect cache.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/quote" \
       -H 'content-type: application/json' \
       -d '{"origin_zip":"98101","dest_zip":"94105","weight_kg":2.5}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/quote/cached" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/quote/refresh" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 140-shipping-quote - request and inspect shipping quotes/cached entries.
exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/quote" \
       -H 'content-type: application/json' \
       -d '{"origin_zip":"98101","dest_zip":"94105","weight_kg":2.5}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/quote/cached" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/quote/refresh" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
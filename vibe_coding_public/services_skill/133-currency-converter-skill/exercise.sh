# 133-currency-converter - refresh rates and convert amount.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rates/refresh" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/convert?from=USD&to=EUR&amount=100" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/rates" 2>&1
}
# 133-currency-converter - refresh rates and perform conversion reads.
exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/convert?from=USD&to=EUR&amount=100" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rates/refresh" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/rates" 2>&1
}
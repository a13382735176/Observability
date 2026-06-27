# 163-dns-resolver-svc - resolve domain names through cache and refresh APIs.
exercise_once() {
  local base="$1"
  local domain="example.com"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/resolve/$domain" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/resolve/refresh" \
       -H 'content-type: application/json' \
       -d '{"domain":"'"$domain"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cached" 2>&1
}

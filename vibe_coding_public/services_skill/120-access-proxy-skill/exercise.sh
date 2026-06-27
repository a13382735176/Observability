# 120-access-proxy - issue and validate a token.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tokens" \
       -H 'content-type: application/json' \
       -d '{"user_id":"user-1","scopes":["read"]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/validate" \
       -H 'content-type: application/json' \
       -d '{"token":"invalid-token"}' 2>&1
}
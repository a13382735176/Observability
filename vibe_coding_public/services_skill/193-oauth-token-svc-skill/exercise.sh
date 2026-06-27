# 193-oauth-token-svc - register client and exercise token APIs.
exercise_once() {
  local base="$1"
  local client="client-$RANDOM"
  local secret="secret-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/clients" \
       -H 'content-type: application/json' \
       -d '{"client_id":"'"$client"'","client_secret":"'"$secret"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/token" \
       -H 'content-type: application/json' \
       -d '{"client_id":"'"$client"'","client_secret":"'"$secret"'","grant_type":"client_credentials"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/introspect" \
       -H 'content-type: application/json' \
       -d '{"token":"dummy-token"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/tokens/active" 2>&1
}

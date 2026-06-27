# 124-cert-renewal-svc - create/list/renew certificate records.
exercise_once() {
  local base="$1"
  local domain="example.com"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/certs" \
       -H 'content-type: application/json' \
       -d '{"domain":"'"$domain"'","expires_at":"2026-12-31T00:00:00Z"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/certs/$domain" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/certs/1/renew" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
# 124-cert-renewal-svc - touch health, create certs, and trigger renewals.
exercise_once() {
  local base="$1"
  local domain="example-$RANDOM.com"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/certs" \
       -H 'content-type: application/json' \
       -d '{"domain":"'"$domain"'","expires_at":"2026-12-31"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/certs/expiring" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/certs/$domain" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/certs/1/renew" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}
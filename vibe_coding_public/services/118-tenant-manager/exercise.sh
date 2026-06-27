# 118-tenant-manager - create a tenant and list tenants.
exercise_once() {
  local base="$1"
  local domain="tenant-$RANDOM.example.com"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tenants" \
       -H 'content-type: application/json' \
       -d '{"name":"demo-tenant","plan":"pro","domain":"'"$domain"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/tenants" 2>&1
}

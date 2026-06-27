# 121-quota-enforcer - set quota and perform usage check.
exercise_once() {
  local base="$1"
  local api_key="key-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/quotas/$api_key" \
       -H 'content-type: application/json' \
       -d '{"limit_per_hour":10}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/check" \
       -H 'content-type: application/json' \
       -d '{"api_key":"'"$api_key"'","resource":"articles"}' 2>&1
}
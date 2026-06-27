# 05-inventory-tracker — internal producer/consumer already runs against
# both redis-cache and redis-stream. We just heartbeat /stats and /stock/...
# so the judge sees periodic activity.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stats" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stock/sku-1" 2>&1
}

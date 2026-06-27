# 09-order-processor — internal producer + consumer over redis-stream and
# postgres. Heartbeat /stats only.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stats" 2>&1
}

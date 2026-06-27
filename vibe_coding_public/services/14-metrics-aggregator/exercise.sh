# 14-metrics-aggregator — internal loop produces + consumes against both
# redis-cache and redis-stream. Heartbeat /metrics for outside visibility.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/metrics" 2>&1
}

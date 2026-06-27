# 172-anomaly-detector - ingest samples and query anomaly stats.
exercise_once() {
  local base="$1"
  local metric="latency.$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/samples" \
       -H 'content-type: application/json' \
       -d '{"metric":"'"$metric"'","value":120.0}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/samples/$metric/stats" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/samples/$metric/recent" 2>&1
}

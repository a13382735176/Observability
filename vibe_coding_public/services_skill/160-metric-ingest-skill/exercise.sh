# 160-metric-ingest - ingest a metric and read the latest value.
exercise_once() {
  local base="$1"
  local metric="cpu.load.$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/metrics" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$metric"'","value":42.5,"tags":{"host":"edge-1"}}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/metrics/$metric" 2>&1
}

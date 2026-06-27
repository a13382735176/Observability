# 161-trace-collector - submit a span and query trace views.
exercise_once() {
  local base="$1"
  local trace_id="trace-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/spans" \
       -H 'content-type: application/json' \
       -d '{"trace_id":"'"$trace_id"'","span_id":"span-1","service":"checkout","operation":"charge","start_ns":1710000000000000000,"duration_ns":1200000000,"attributes":{"region":"us-east"}}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/traces/$trace_id" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/slow" 2>&1
}

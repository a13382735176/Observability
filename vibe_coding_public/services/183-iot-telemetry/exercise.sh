# 183-iot-telemetry - ingest and query telemetry.
exercise_once() {
  local base="$1"
  local device="dev-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/readings" \
       -H 'content-type: application/json' \
       -d '{"device_id":"'"$device"'","sensor_type":"temp","value":42.5}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/readings/$device" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/readings/$device/avg?since_minutes=30" 2>&1
}

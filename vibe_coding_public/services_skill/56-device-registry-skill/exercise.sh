exercise_once() {
  local base="$1"
  local device_id
  device_id="dev-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/devices" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","type":"sensor","firmware_version":"1.0.0"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/devices/$device_id" 2>&1
}
# 184-device-registry - upsert and query devices.
exercise_once() {
  local base="$1"
  local device="device-$RANDOM"
  local owner="owner-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/devices" \
       -H 'content-type: application/json' \
       -d '{"device_id":"'"$device"'","model":"v1","firmware_version":"1.0.0","owner_id":"'"$owner"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/devices/$device" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/devices/$device/firmware" \
       -H 'content-type: application/json' \
       -d '{"firmware_version":"1.0.1"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/devices/owner/$owner" 2>&1
}

exercise_once() {
  local base="$1"
  local device_id
  device_id="dev-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/provision" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","device_type":"sensor"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/provision/$device_id" 2>&1
}
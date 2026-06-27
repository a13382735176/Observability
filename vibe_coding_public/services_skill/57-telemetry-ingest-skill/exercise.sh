exercise_once() {
  local base="$1"
  local device_id
  device_id="dev-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/telemetry" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","metric":"temp","value":23.5,"unit":"C"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/telemetry/$device_id" 2>&1
}
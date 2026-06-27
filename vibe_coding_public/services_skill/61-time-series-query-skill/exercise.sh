exercise_once() {
  local base="$1"
  local device_id ts_iso
  device_id="dev-$RANDOM"
  ts_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/datapoints" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","metric":"temp","value":21.7,"ts_iso":"'"$ts_iso"'"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/series/$device_id?metric=temp" 2>&1
}
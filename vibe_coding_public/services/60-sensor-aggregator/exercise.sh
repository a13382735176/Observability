exercise_once() {
  local base="$1"
  local device_id
  device_id="dev-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/readings" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","readings":[{"metric":"temp","value":24.1},{"metric":"hum","value":46.2}]}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/aggregate/$device_id" 2>&1
}
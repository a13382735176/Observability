exercise_once() {
  local base="$1"
  local device_id
  device_id="dev-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/rules" \
    -H 'content-type: application/json' \
    -d '{"metric":"temp","threshold":70,"op":"gt"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/evaluate" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","metric":"temp","value":72}' 2>&1
}
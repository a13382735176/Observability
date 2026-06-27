exercise_once() {
  local base="$1"
  local device_id
  device_id="dev-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/configs" \
    -H 'content-type: application/json' \
    -d '{"device_id":"'"$device_id"'","config":{"mode":"eco","sample_s":30}}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/configs/$device_id" 2>&1
}
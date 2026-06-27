# 117-secret-rotation - create secret metadata and read it back.
exercise_once() {
  local base="$1"
  local secret_name="secret-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/secrets" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$secret_name"'","value":"v1"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/secrets/$secret_name/metadata" 2>&1
}
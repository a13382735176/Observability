exercise_once() {
  local base="$1"
  local pid
  pid="010C"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/parse" \
    -H 'content-type: application/json' \
    -d '{"pid":"'"$pid"'","raw_value":"1AF8"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/cached/$pid" 2>&1
}
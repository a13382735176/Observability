# 103-image-catalog - write and query image metadata.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/images" \
       -H 'content-type: application/json' \
       -d '{"filename":"image-'"$RANDOM"'.jpg","width":640,"height":480,"url":"https://example.com/i.jpg"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/images?width_min=320" 2>&1
}
# 192-thumbnail-generator - create and fetch thumbnail jobs.
exercise_once() {
  local base="$1"
  local rid="$RANDOM"
  local src="https://example.com/img-$rid.jpg"
  local src_q="https%3A%2F%2Fexample.com%2Fimg-$rid.jpg"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/thumbnails" \
       -H 'content-type: application/json' \
       -d '{"sourceImageUrl":"'"$src"'","sizes":[64,128]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/thumbnails/by-source?url=$src_q" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/thumbnails/cached/64?url=$src_q" 2>&1
}

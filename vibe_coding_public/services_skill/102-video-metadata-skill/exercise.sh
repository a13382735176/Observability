# 102-video-metadata - write and query video metadata.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/videos" \
       -H 'content-type: application/json' \
       -d '{"title":"clip-'"$RANDOM"'","duration_s":42,"url":"https://example.com/v.mp4","tags":["demo"]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/videos?tag=demo" 2>&1
}
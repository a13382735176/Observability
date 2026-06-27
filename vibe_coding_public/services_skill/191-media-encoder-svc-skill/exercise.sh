# 191-media-encoder-svc - enqueue and progress encoding jobs.
exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/jobs" \
       -H 'content-type: application/json' \
       -d '{"input_url":"https://example.com/in.mp4","format":"mp4","quality":"720p"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/jobs/queue" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/jobs/1/start" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/jobs/1/complete" \
       -H 'content-type: application/json' \
       -d '{"output_url":"https://cdn.example.com/out.mp4","duration_sec":60}' 2>&1
}

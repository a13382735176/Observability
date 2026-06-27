# 168-job-scheduler - enqueue due jobs and trigger dispatcher.
exercise_once() {
  local base="$1"
  local job_name="digest-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/jobs" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$job_name"'","payload":{"scope":"daily"},"run_at_iso":"2020-01-01T00:00:00Z"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/jobs/run-due" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/jobs?status=dispatched" 2>&1
}

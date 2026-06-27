# 170-cron-svc - register cron jobs and inspect due queue.
exercise_once() {
  local base="$1"
  local cron_name="heartbeat-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/cron" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$cron_name"'","expression":"* * * * *","action_url":"https://example.org/hook"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cron/due" 2>&1
}

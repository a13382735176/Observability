# 169-task-runner - queue tasks and inspect task lists.
exercise_once() {
  local base="$1"
  local task_type="sync-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tasks" \
       -H 'content-type: application/json' \
       -d '{"type":"'"$task_type"'","parameters":{"target":"warehouse","attempt":1}}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/tasks?status=queued&limit=5" 2>&1
}

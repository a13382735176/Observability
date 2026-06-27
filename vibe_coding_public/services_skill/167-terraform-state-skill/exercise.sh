# 167-terraform-state - store state, list versions, and exercise lock workflow.
exercise_once() {
  local base="$1"
  local workspace="ws-$RANDOM"
  local lock_id="lock-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/state/$workspace" \
       -H 'content-type: application/json' \
       -d '{"resources":[{"type":"null_resource","name":"example"}],"serial":1}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/state/$workspace" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/state/$workspace/versions" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/state/$workspace/lock" \
       -H 'content-type: application/json' \
       -d '{"lock_id":"'"$lock_id"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X DELETE "$base/state/$workspace/lock/$lock_id" 2>&1
}

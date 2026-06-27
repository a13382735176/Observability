# 174-cohort-builder - create cohort definitions and inspect registry.
exercise_once() {
  local base="$1"
  local cohort_name="cohort-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/cohorts" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$cohort_name"'","criteria":{"event_type":"click","min_count":1,"since_days":30}}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cohorts" 2>&1
}

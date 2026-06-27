# 164-backup-orchestrator - create backup records and query resource history.
exercise_once() {
  local base="$1"
  local resource_id="db-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/backups" \
       -H 'content-type: application/json' \
       -d '{"resource_type":"postgres","resource_id":"'"$resource_id"'","location":"s3://backups/'"$resource_id"'.dump","size_bytes":1048576}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/backups/postgres/$resource_id" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/backups" 2>&1
}

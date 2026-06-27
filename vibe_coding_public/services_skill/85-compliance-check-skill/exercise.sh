exercise_once() {
  local base="$1"
  local entity_id
  entity_id="entity-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/check" \
    -H 'content-type: application/json' \
    -d '{"entity_id":"'"$entity_id"'","check_type":"kyc"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/results/$entity_id" 2>&1
}
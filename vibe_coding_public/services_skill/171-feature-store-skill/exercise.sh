# 171-feature-store - write feature values and read cached lookups.
exercise_once() {
  local base="$1"
  local entity="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/features" \
       -H 'content-type: application/json' \
       -d '{"entity_id":"'"$entity"'","feature_name":"ctr","value":0.42,"version":1}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/features/$entity/ctr" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/features/entity/$entity" 2>&1
}

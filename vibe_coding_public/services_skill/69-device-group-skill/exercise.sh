exercise_once() {
  local base="$1"
  local group_name
  group_name="grp-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/groups" \
    -H 'content-type: application/json' \
    -d '{"name":"'"$group_name"'","device_ids":["dev-a","dev-b"]}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/groups" 2>&1
}
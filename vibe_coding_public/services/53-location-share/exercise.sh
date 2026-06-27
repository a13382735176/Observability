exercise_once() {
  local base="$1"
  local user_id
  user_id="u-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X PUT "$base/location/$user_id" \
    -H 'content-type: application/json' \
    -d '{"lat":37.7749,"lng":-122.4194,"ttl_s":120}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    "$base/nearby?lat=37.7749&lng=-122.4194&radius_km=1" 2>&1
}
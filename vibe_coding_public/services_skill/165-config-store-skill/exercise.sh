# 165-config-store - write, read, and snapshot environment config.
exercise_once() {
  local base="$1"
  local env="dev"
  local key="feature-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/config" \
       -H 'content-type: application/json' \
       -d '{"key":"'"$key"'","value":"enabled","environment":"'"$env"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/config/$env/$key" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/config/$env/snapshot" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}

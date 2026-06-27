# 12-rate-limiter-proxy (redis_cache + upstream) — GET through the proxy. Each
# call performs a redis INCR and forwards to mock-upstream, exercising both deps.
exercise_once() {
  local base="$1"
  curl -sS --max-time 4 -w 'HTTP_CODE:%{http_code}\n' "$base/api/anything" 2>&1
}

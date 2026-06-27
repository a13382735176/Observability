# 131-weather-fetcher - warm and read weather cache.
exercise_once() {
  local base="$1"
  local city="seattle"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/weather/$city" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cached" 2>&1
}
# 131-weather-fetcher - probe health and weather/cache endpoints.
exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/weather/seattle" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cached" 2>&1
}
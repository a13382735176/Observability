# 126-flight-search - search flights and populate cache.
exercise_once() {
  local base="$1"
  local origin="SFO"
  local dest="LAX"
  local date="2026-06-01"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/flights/search" \
       -H 'content-type: application/json' \
       -d '{"origin":"'"$origin"'","dest":"'"$dest"'","date":"'"$date"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/flights/search?origin=$origin&dest=$dest&date=$date" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/flights/cache-populate" \
       -H 'content-type: application/json' \
       -d '{"origin":"'"$origin"'","dest":"'"$dest"'","date":"'"$date"'"}' 2>&1
}
# 126-flight-search - drive cached and uncached search paths.
exercise_once() {
  local base="$1"
  local origin="SFO"
  local dest="LAX"
  local date="2026-06-01"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/flights/search" \
       -H 'content-type: application/json' \
       -d '{"origin":"'"$origin"'","dest":"'"$dest"'","date":"'"$date"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/flights/search?origin=$origin&dest=$dest&date=$date" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/flights/cache-populate" \
       -H 'content-type: application/json' \
       -d '{"origin":"'"$origin"'","dest":"'"$dest"'","date":"'"$date"'"}' 2>&1
}
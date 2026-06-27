# 130-price-tracker - track a route and inspect changes.
exercise_once() {
  local base="$1"
  local route="SFO-LAX"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/track" \
       -H 'content-type: application/json' \
       -d '{"route":"'"$route"'","current_price_cents":12999}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/prices/$route" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/changes" 2>&1
}
# 130-price-tracker - submit observations and inspect history.
exercise_once() {
  local base="$1"
  local route="SFO-LAX-2026-06-01"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/track" \
       -H 'content-type: application/json' \
       -d '{"route":"'"$route"'","current_price_cents":12999}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/prices/$route" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/changes" 2>&1
}
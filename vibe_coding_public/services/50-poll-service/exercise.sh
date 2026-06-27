exercise_once() {
  local base="$1"
  local creator="u$RANDOM"
  local voter="u$RANDOM"
  local resp poll_id

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  resp="$(curl -sS --max-time 3 -w '\nHTTP_CODE:%{http_code}' -X POST "$base/polls" \
           -H 'content-type: application/json' \
           -d '{"question":"best color?","options":["red","blue"],"creator_id":"'"$creator"'"}' 2>&1)"
  echo "$resp"
  poll_id="$(printf '%s' "$resp" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
  if [[ -n "$poll_id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/vote" \
         -H 'content-type: application/json' \
         -d '{"poll_id":'"$poll_id"',"user_id":"'"$voter"'","option_idx":0}' 2>&1
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/polls/$poll_id/results" 2>&1
  fi
}
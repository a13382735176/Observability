exercise_once() {
  local base="$1"
  local host="u$RANDOM"
  local guest="u$RANDOM"
  local resp event_id

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  resp="$(curl -sS --max-time 3 -w '\nHTTP_CODE:%{http_code}' -X POST "$base/events" \
           -H 'content-type: application/json' \
           -d '{"title":"event-'"$RANDOM"'","host_id":"'"$host"'","max_guests":5}' 2>&1)"
  echo "$resp"
  event_id="$(printf '%s' "$resp" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
  if [[ -n "$event_id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rsvp" \
         -H 'content-type: application/json' \
         -d '{"event_id":'"$event_id"',"user_id":"'"$guest"'"}' 2>&1
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/events/$event_id/guests" 2>&1
  fi
}
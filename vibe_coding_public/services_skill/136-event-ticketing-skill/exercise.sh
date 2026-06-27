# 136-event-ticketing - create event and buy ticket.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/events" \
       -H 'content-type: application/json' \
       -d '{"name":"TechConf","venue":"Hall-A","event_date":"2026-09-01","total_tickets":100}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/events/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tickets/buy" \
       -H 'content-type: application/json' \
       -d '{"event_id":1,"user_id":"'"$user"'","quantity":1}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/tickets/$user" 2>&1
}
# 136-event-ticketing - create events, buy tickets, and read views.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  local event_name="tech-conf-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/events" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$event_name"'","venue":"Hall A","event_date":"2026-09-01","total_tickets":100}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/tickets/buy" \
       -H 'content-type: application/json' \
       -d '{"event_id":1,"user_id":"'"$user"'","quantity":2}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/events/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/tickets/$user" 2>&1
}
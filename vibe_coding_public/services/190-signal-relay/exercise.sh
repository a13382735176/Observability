# 190-signal-relay - send signals and manage sessions.
exercise_once() {
  local base="$1"
  local from_user="alice-$RANDOM"
  local to_user="bob-$RANDOM"
  local sid="sess-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/signals" \
       -H 'content-type: application/json' \
       -d '{"from_user":"'"$from_user"'","to_user":"'"$to_user"'","signal_type":"offer","payload":"{}"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/signals/$to_user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/sessions" \
       -H 'content-type: application/json' \
       -d '{"session_id":"'"$sid"'","initiator_user":"'"$from_user"'","joiner_user":"'"$to_user"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/sessions/active" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/sessions/$sid/end" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}

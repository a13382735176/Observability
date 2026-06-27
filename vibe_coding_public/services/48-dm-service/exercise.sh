exercise_once() {
  local base="$1"
  local sender="u$RANDOM"
  local recipient="u$RANDOM"
  local conv="${sender}:${recipient}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/messages" \
       -H 'content-type: application/json' \
       -d '{"sender_id":"'"$sender"'","recipient_id":"'"$recipient"'","text":"hello"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/messages/$conv" 2>&1
}
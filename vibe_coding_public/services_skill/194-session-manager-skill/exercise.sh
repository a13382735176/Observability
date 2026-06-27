# 194-session-manager - create and inspect user sessions.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/sessions" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","ip_address":"127.0.0.1","user_agent":"exercise"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/sessions/user/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/sessions/does-not-exist" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/sessions/does-not-exist/refresh" \
       -H 'content-type: application/json' \
       -d '{}' 2>&1
}

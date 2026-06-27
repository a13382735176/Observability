# Exerciser for 07-session-cache — POST a session then GET it back. Touches
# redis-cache on both calls so cache-down/cache-slow faults surface.
exercise_once() {
  local base="$1"
  local resp tok
  resp="$(curl -sS --max-time 3 -w '\nHTTP_CODE:%{http_code}' \
            -X POST "$base/session" -H 'content-type: application/json' \
            -d '{"user_id":"u1"}' 2>&1)"
  echo "[create] $resp"
  tok="$(printf '%s' "$resp" | grep -oE '"token":"[a-f0-9]+"' | head -1 \
         | sed -E 's/.*"([a-f0-9]+)".*/\1/')"
  if [[ -n "$tok" ]]; then
    echo "[get  ] tok=$tok"
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}' \
         "$base/session/$tok" 2>&1
    echo ""
  fi
}

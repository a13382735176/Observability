exercise_once() {
  local base="$1"
  local user="u$RANDOM"
  local resp post_id

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  resp="$(curl -sS --max-time 3 -w '\nHTTP_CODE:%{http_code}' -X POST "$base/posts" \
           -H 'content-type: application/json' \
           -d '{"user_id":"'"$user"'","content":"hello from exercise"}' 2>&1)"
  echo "$resp"
  post_id="$(printf '%s' "$resp" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
  if [[ -n "$post_id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/posts/$post_id" 2>&1
  fi
}
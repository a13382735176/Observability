# 06-user-profile (postgres) — POST a new user with random email; touches pg.
exercise_once() {
  local base="$1"
  local email="u${RANDOM}-${RANDOM}@vibe.local"
  local resp id
  resp="$(curl -sS --max-time 4 -w '\nHTTP_CODE:%{http_code}' \
           -X POST "$base/users" -H 'content-type: application/json' \
           -d '{"email":"'"$email"'","name":"Test User"}' 2>&1)"
  echo "[create] $resp"
  id="$(printf '%s' "$resp" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
  if [[ -n "$id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/users/$id" 2>&1
  fi
}

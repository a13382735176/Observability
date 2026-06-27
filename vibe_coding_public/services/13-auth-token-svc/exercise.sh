# 13-auth-token-svc (postgres) — signup a fresh user, then issue token.
exercise_once() {
  local base="$1"
  local email="u${RANDOM}-${RANDOM}@vibe.local"
  curl -sS --max-time 4 -w 'HTTP_CODE:%{http_code}\n' \
       -X POST "$base/signup" -H 'content-type: application/json' \
       -d '{"email":"'"$email"'","password":"vibe-test"}' 2>&1
  curl -sS --max-time 4 -w 'HTTP_CODE:%{http_code}\n' \
       -X POST "$base/token" -H 'content-type: application/json' \
       -d '{"email":"'"$email"'","password":"vibe-test"}' 2>&1
}

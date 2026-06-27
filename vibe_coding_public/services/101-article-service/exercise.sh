# 101-article-service - article CRUD path.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/articles" \
       -H 'content-type: application/json' \
       -d '{"title":"hello-'"$RANDOM"'","content":"sample body","author_id":"author-1"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/articles" 2>&1
}
# 10-search-indexer — internal indexing loop reads pg + writes redis-cache.
# Heartbeat /stats and try fetching a known index entry.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stats" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/index/1" 2>&1
}

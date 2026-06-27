# 132-review-aggregator — drive DB + cache paths during fault windows.
exercise_once() {
  local base="$1"
  local eid="item-1"

  curl -sS --max-time 4 -X POST "$base/reviews" \
    -H 'content-type: application/json' \
    -d '{"entity_id":"item-1","entity_type":"movie","rating":4,"body":"ok","author_id":"u1"}' \
    >/dev/null 2>&1 || true

  curl -sS --max-time 4 "$base/aggregate/movie/$eid" >/dev/null 2>&1 || true
}

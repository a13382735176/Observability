# 15-webhook-fanout (upstream) — POST a webhook; service fans out in parallel
# to 3 upstream paths. Any upstream fault should surface here.
exercise_once() {
  local base="$1"
  curl -sS --max-time 5 -w 'HTTP_CODE:%{http_code}\n' \
       -X POST "$base/webhook" -H 'content-type: application/json' \
       -d '{"event":"ping","seq":'"$RANDOM"'}' 2>&1
}

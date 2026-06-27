# 189-pubsub-broker - subscribe and publish to a topic.
exercise_once() {
  local base="$1"
  local topic="topic-$RANDOM"
  local sub="sub-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/subscribe" \
       -H 'content-type: application/json' \
       -d '{"subscriber_id":"'"$sub"'","topic":"'"$topic"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/publish" \
       -H 'content-type: application/json' \
       -d '{"topic":"'"$topic"'","payload":"hello"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/messages/$topic?count=5" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/subscribers/$topic" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X DELETE "$base/subscribe" \
       -H 'content-type: application/json' \
       -d '{"subscriber_id":"'"$sub"'","topic":"'"$topic"'"}' 2>&1
}

# 185-mqtt-bridge - publish messages and manage subscriptions.
exercise_once() {
  local base="$1"
  local topic="devices/$RANDOM"
  local client="client-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/messages" \
       -H 'content-type: application/json' \
       -d '{"topic":"'"$topic"'","payload":"hello","qos":1}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/subscriptions" \
       -H 'content-type: application/json' \
       -d '{"client_id":"'"$client"'","topic_pattern":"'"$topic"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/messages/topic/$topic?limit=5" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/subscriptions/$client" 2>&1
}

# 08-notification-dispatcher — producer (XADD) + consumer (XREADGROUP + POST
# to upstream/send) run internally. We heartbeat /stats so judges see periodic
# activity even when external traffic is light.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/stats" 2>&1
}

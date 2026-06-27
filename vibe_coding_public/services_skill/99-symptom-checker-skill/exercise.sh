# 99-symptom-checker - condition update path.
exercise_once() {
  local base="$1"
  local condition="condition-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/conditions" \
    -H 'content-type: application/json' \
    -d '{"condition_name":"'"$condition"'","symptoms":["fever","cough"]}' 2>&1
}
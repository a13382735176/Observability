# 162-alert-manager - register a rule and trigger evaluation.
exercise_once() {
  local base="$1"
  local rule_name="cpu-rule-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/rules" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$rule_name"'","metric":"cpu","threshold":80,"comparator":"gt"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/evaluate" \
       -H 'content-type: application/json' \
       -d '{"metric":"cpu","value":92}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/alerts" 2>&1
}

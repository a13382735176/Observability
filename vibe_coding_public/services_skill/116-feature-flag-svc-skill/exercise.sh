# 116-feature-flag-svc - create and evaluate a rollout flag.
exercise_once() {
  local base="$1"
  local flag_name="flag-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/flags" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$flag_name"'","enabled":true,"rollout_pct":35}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/check" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$flag_name"'","user_id":"user-1"}' 2>&1
}
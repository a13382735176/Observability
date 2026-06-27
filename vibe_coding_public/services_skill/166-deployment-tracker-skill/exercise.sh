# 166-deployment-tracker - create deployment entries and inspect history.
exercise_once() {
  local base="$1"
  local svc="checkout-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/deployments" \
       -H 'content-type: application/json' \
       -d '{"service":"'"$svc"'","version":"1.0.0","environment":"dev","deployed_by":"chaos-bot"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/deployments/$svc" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/deployments/active/dev" 2>&1
}

exercise_once() {
  local base="$1"
  local user_id
  user_id="user-$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/reports" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","tax_year":2025,"income_cents":6500000,"deductions_cents":1250000}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/reports/$user_id" 2>&1
}
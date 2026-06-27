# 90-budget-tracker - budget write path.
exercise_once() {
  local base="$1"
  local user_id="user-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/budgets" \
    -H 'content-type: application/json' \
    -d '{"user_id":"'"$user_id"'","category":"groceries","limit_cents":50000,"period":"monthly"}' 2>&1
}
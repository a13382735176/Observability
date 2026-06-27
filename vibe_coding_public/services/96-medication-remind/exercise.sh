# 96-medication-remind - create reminder flow.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/reminders" \
    -H 'content-type: application/json' \
    -d '{"patient_id":"'"$patient_id"'","medication":"metformin","times_per_day":2,"duration_days":14}' 2>&1
}
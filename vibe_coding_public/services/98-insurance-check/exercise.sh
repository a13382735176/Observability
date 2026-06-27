# 98-insurance-check - eligibility verification flow.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/eligibility" \
    -H 'content-type: application/json' \
    -d '{"patient_id":"'"$patient_id"'","insurance_id":"ins-12345"}' 2>&1
}
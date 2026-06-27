# 94-lab-results - ingest lab result.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/results" \
    -H 'content-type: application/json' \
    -d '{"patient_id":"'"$patient_id"'","test_type":"glucose","value":5.6,"unit":"mmol/L","reference_range":"3.9-6.1"}' 2>&1
}
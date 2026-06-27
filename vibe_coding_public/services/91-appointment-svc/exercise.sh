# 91-appointment-svc - create appointment flow.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"
  local doctor_id="doctor-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/appointments" \
    -H 'content-type: application/json' \
    -d '{"patient_id":"'"$patient_id"'","doctor_id":"'"$doctor_id"'","datetime_iso":"2026-06-01T09:00:00Z","reason":"checkup"}' 2>&1
}
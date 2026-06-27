# 93-prescription-svc - prescription create path.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"
  local doctor_id="doctor-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/prescriptions" \
    -H 'content-type: application/json' \
    -d '{"patient_id":"'"$patient_id"'","doctor_id":"'"$doctor_id"'","medication":"amoxicillin","dosage":"500mg","duration_days":7}' 2>&1
}
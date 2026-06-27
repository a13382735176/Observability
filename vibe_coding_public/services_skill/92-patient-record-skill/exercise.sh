# 92-patient-record - create patient record.
exercise_once() {
  local base="$1"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/patients" \
    -H 'content-type: application/json' \
    -d '{"name":"Alice","dob_str":"1990-01-01","blood_type":"O+","allergies":["pollen"]}' 2>&1
}
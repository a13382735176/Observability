# 95-vitals-monitor - publish vitals event.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/vitals" \
    -H 'content-type: application/json' \
    -d '{"patient_id":"'"$patient_id"'","heart_rate":72,"bp":"120/80","spo2":98,"temp_c":36.7}' 2>&1
}
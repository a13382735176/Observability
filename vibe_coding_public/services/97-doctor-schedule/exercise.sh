# 97-doctor-schedule - create available slot.
exercise_once() {
  local base="$1"
  local doctor_id="doctor-${RANDOM}${RANDOM}"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/schedules" \
    -H 'content-type: application/json' \
    -d '{"doctor_id":"'"$doctor_id"'","slot_datetime_iso":"2026-06-01T10:00:00Z"}' 2>&1
}
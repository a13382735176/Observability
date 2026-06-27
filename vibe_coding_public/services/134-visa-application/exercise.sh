# 134-visa-application - submit and update visa application.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/applications" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","destination_country":"JP","travel_date":"2026-10-10","purpose":"tourism"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/applications/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/applications/1/status" \
       -H 'content-type: application/json' \
       -d '{"status":"approved"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/applications" 2>&1
}
# 134-visa-application - create and update visa applications.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/applications" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","destination_country":"JP","travel_date":"2026-10-01","purpose":"tourism"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/applications/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/applications/1/status" \
       -H 'content-type: application/json' \
       -d '{"status":"approved"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/applications" 2>&1
}
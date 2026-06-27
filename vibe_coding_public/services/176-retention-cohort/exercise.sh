# 176-retention-cohort - record signup/activity and query retention math.
exercise_once() {
  local base="$1"
  local user_id="user-$RANDOM"
  local signup_date="2026-05-01"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/signups" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user_id"'","signup_date_iso":"'"$signup_date"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/activity" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user_id"'","activity_date_iso":"2026-05-02"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/activity/user/$user_id" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/retention/$signup_date" 2>&1
}

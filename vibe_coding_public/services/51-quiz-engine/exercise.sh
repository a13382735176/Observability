exercise_once() {
  local base="$1"
  local resp quiz_id

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  resp="$(curl -sS --max-time 3 -w '\nHTTP_CODE:%{http_code}' -X POST "$base/quizzes" \
           -H 'content-type: application/json' \
           -d '{"title":"quick-math","questions":[{"q":"2+2?","choices":["3","4"],"answer_idx":1}]}' 2>&1)"
  echo "$resp"
  quiz_id="$(printf '%s' "$resp" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
  if [[ -n "$quiz_id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/quizzes/$quiz_id" 2>&1
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/quizzes/$quiz_id/submit" \
         -H 'content-type: application/json' \
         -d '{"answers":[1]}' 2>&1
  fi
}
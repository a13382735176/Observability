# 100-telemedicine-svc — exercise session lifecycle endpoints during fault windows.
exercise_once() {
  local base="$1"
  local patient_id="patient-${RANDOM}${RANDOM}"
  local doctor_id="doctor-${RANDOM}${RANDOM}"
  local payload
  local post_resp post_code post_body token code

  _curl_code() {
    local method="$1"
    local url="$2"
    shift 2
    local out
    out="$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' -X "$method" "$url" "$@" 2>/dev/null || true)"
    if [[ "$out" =~ ^[0-9]{3}$ ]]; then
      printf '%s' "$out"
    else
      printf '000'
    fi
  }

  payload="$(printf '{"patient_id":"%s","doctor_id":"%s"}' "$patient_id" "$doctor_id")"

  code="$(_curl_code GET "$base/healthz")"
  printf 'GET /healthz -> HTTP %s\n' "$code"

  post_resp="$(curl -sS --max-time 3 -X POST "$base/sessions" \
    -H 'content-type: application/json' \
    -d "$payload" \
    -w $'\n__HTTP_CODE__:%{http_code}' 2>/dev/null || true)"
  post_code="$(printf '%s\n' "$post_resp" | sed -n 's/^__HTTP_CODE__://p' | tail -1)"
  [[ "$post_code" =~ ^[0-9]{3}$ ]] || post_code="000"
  post_body="$(printf '%s\n' "$post_resp" | sed '/^__HTTP_CODE__:/d')"
  printf 'POST /sessions -> HTTP %s\n' "$post_code"

  token="$(printf '%s' "$post_body" \
    | sed -nE 's/.*"token"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' \
    | head -1)"
  if [[ -z "$token" ]]; then
    token="fallback-token-${RANDOM}${RANDOM}"
  fi

  code="$(_curl_code GET "$base/sessions/$token/status")"
  printf 'GET /sessions/%s/status -> HTTP %s\n' "$token" "$code"

  code="$(_curl_code DELETE "$base/sessions/$token")"
  printf 'DELETE /sessions/%s -> HTTP %s\n' "$token" "$code"
}
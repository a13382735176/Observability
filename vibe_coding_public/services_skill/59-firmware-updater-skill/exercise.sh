exercise_once() {
  local base="$1"
  local version
  version="v1.$RANDOM"

  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' \
    -X POST "$base/updates" \
    -H 'content-type: application/json' \
    -d '{"version":"'"$version"'","changelog":"auto","artifact_url":"https://example.invalid/fw.bin"}' 2>&1
  curl -sS --max-time 3 -w ' HTTP_CODE:%{http_code}\n' "$base/updates/latest" 2>&1
}
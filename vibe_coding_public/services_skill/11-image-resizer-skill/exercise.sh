# 11-image-resizer (no deps) — POST a tiny "image" blob then GET it back.
exercise_once() {
  local base="$1"
  local resp id
  resp="$(curl -sS --max-time 3 -w '\nHTTP_CODE:%{http_code}' \
           -X POST "$base/resize" -H 'content-type: application/octet-stream' \
           --data-binary 'fake-image-bytes' 2>&1)"
  echo "[upload] $resp"
  id="$(printf '%s' "$resp" | grep -oE '"id":"[a-f0-9]+"' | head -1 \
        | sed -E 's/.*"([a-f0-9]+)".*/\1/')"
  if [[ -n "$id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -o /dev/null \
         "$base/resized/$id" 2>&1
  fi
}

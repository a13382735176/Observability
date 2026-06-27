# 187-file-metadata - create and query file metadata.
exercise_once() {
  local base="$1"
  local owner="owner-$RANDOM"
  local sha="sha-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/files" \
       -H 'content-type: application/json' \
       -d '{"filename":"img.png","mime_type":"image/png","size_bytes":12345,"sha256":"'"$sha"'","owner_id":"'"$owner"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/files/owner/$owner" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/files/search?mime=image/" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/files/sha/$sha" 2>&1
}

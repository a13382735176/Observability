# 163-dns-resolver-svc

Cached DNS resolver. Resolves domain names by consulting a Redis hash cache (`dns:{domain}` → comma-joined IP list) and falling back to a mock upstream resolver on miss. Cached entries expire after 300 seconds. Operators can force a refresh, list currently cached domains, or wipe the cache.

Endpoints: `GET /healthz`, `GET /resolve/<domain>`, `POST /resolve/refresh`, `GET /cached`, `DELETE /cache`.

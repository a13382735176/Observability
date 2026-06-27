# 197-policy-engine

Spring Boot policy decision service. Stores allow/deny rules in Postgres (principal/resource/action patterns supporting `*` wildcard or exact match) and caches decisions in Redis (`policy_decision:{principal}:{resource}:{action}`, TTL 60s). Deny-wins semantics; no matching policy defaults to deny.

Endpoints: `GET /healthz`, `POST /policies`, `POST /evaluate`, `GET /policies`, `DELETE /policies/{id}`, `POST /policies/refresh` (clears decision cache).

Dependencies: postgres, redis-cache. Faults: F01, F02, F05, F06, F07, F08, F11, F12, F13.

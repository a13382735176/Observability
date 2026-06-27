# 125-ab-test-assigner

A/B experiment definition and assignment service. Stores experiments in Redis, deterministically maps users to variants via SHA-256 hashing with traffic-percentage gating, and persists per-variant assignment sets.

Endpoints: `GET /healthz`, `POST /experiments`, `GET /experiments/:name`, `POST /assign`, `GET /assignments/:user_id`.

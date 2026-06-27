# 145-warranty-claims

Spring Boot 3.3 / Java 21 microservice that tracks product warranty claims and emits domain events to Redis streams.

**Stack**: Spring Boot, Spring Data JPA, Spring Data Redis (Lettuce), PostgreSQL.

**Storage**:
- Postgres table `warranty_claims(id, product_id, user_id, defect_description, status, resolution, created_at, updated_at)` auto-created via JPA `ddl-auto=update`.
- Redis stream `events:claims` (on `${REDIS_STREAM_HOST:redis-stream}`): one entry per new claim with `{id, product_id}`.
- Redis stream `events:claim_status`: one entry per status update with `{id, status}`.

Stream publish failures are logged and swallowed — they do **not** fail the HTTP request.

## Endpoints

| Method | Path                         | Body / Result                                                |
|--------|------------------------------|--------------------------------------------------------------|
| GET    | `/healthz`                   | `{"status":"ok","service":"warranty-claims"}`                |
| POST   | `/claims`                    | `{product_id, user_id, defect_description}` → 201 claim      |
| GET    | `/claims/{id}`               | claim row or 404                                             |
| GET    | `/claims/user/{userId}`      | latest 20 claims for user                                    |
| PUT    | `/claims/{id}/status`        | `{status, resolution?}` → updated claim                      |

Error responses: `400` for missing required fields, `404` when an id is unknown, `503 {"error":"db error"}` on Postgres failure.

# 191-media-encoder-svc

Rust/Axum media encoding job tracker. Persists encoding jobs in postgres and emits lifecycle events to redis streams (`events:enc_jobs`, `events:enc_started`, `events:enc_complete`).

Endpoints: `GET /healthz`, `POST /jobs`, `GET /jobs/:id`, `PUT /jobs/:id/start`, `PUT /jobs/:id/complete`, `GET /jobs/queue`.

Dependencies: postgres (table `encoding_jobs` auto-created), redis-stream. Faults: F01, F02, F05, F06, F09, F10, F11, F12, F13.

# 151-leaderboard-svc

Rust/Axum service that maintains per-game leaderboards using a redis sorted set
(`lb:{game_id}`) keyed by user id and ordered by score (descending).

## Dependencies
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"leaderboard-svc"}`
- `POST /score` → body `{game_id, user_id, score}`; ZADD into `lb:{game_id}`.
- `GET /leaderboard/{game_id}?top=N` → top-N entries with `{user_id, score, rank}` (default N=10).
- `GET /rank/{game_id}/{user_id}` → `{rank, score}` (404 if user not present).
- `DELETE /leaderboard/{game_id}` → DEL the sorted set; returns `{removed}`.

## Faults
F01, F02, F07, F08, F11, F12, F13.

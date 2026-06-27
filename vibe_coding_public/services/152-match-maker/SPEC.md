# 152-match-maker

Go/chi service that performs simple 1v1 matchmaking. It buffers waiting users in
a per-mode redis list (`mm:{mode}`) on the cache instance, and emits match
events on the stream instance.

## Dependencies
- redis-cache (queue + accepted sets)
- redis-stream (`events:matches`, `events:match_ready`)

## Endpoints
- `GET /healthz`
- `POST /queue` → body `{user_id, skill_rating, mode}`. RPUSH onto `mm:{mode}`;
  if the queue reaches ≥2, LPOP two players and XADD `events:matches`.
- `GET /queue/{mode}/length` → LLEN.
- `POST /match/accept` → body `{match_id, user_id}`. SADD into
  `accepted:{match_id}`; when SCARD==2, XADD `events:match_ready`.
- `GET /matches/recent` → XREVRANGE `events:matches` + - COUNT 20.

## Faults
F01, F02, F07, F08, F09, F10, F11, F12, F13.

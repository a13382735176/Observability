# 189-pubsub-broker

Topic-based pub/sub broker layered on top of Redis streams. Publishers push messages onto `stream:{topic}` in `redis-stream`; subscriber memberships live in `redis-cache` as Redis sets (`subs:{topic}` + reverse lookup `topics:{subscriber_id}`). Per-topic publish counters live in `redis-cache` (`pubcount:{topic}`).

**Stack:** Go / chi (golang:1.22-alpine → alpine:3.20)
**Deps:** redis-cache, redis-stream

## Endpoints
- `GET /healthz`
- `POST /publish` — body `{topic, payload}` → `XADD stream:{topic}` + `INCR pubcount:{topic}`
- `POST /subscribe` — body `{subscriber_id, topic}` → `SADD subs:{topic} subscriber_id`, `SADD topics:{subscriber_id} topic`
- `DELETE /subscribe` — body `{subscriber_id, topic}` → `SREM` from both keys
- `GET /messages/{topic}?count=20` — `XREVRANGE stream:{topic} + - COUNT count` (max 200)
- `GET /subscribers/{topic}` — `SMEMBERS subs:{topic}`
- `GET /stats` — `SCAN pubcount:*` and return `{topic: count}` map

Each Redis call wrapped in `context.WithTimeout(ctx, 2*time.Second)`. All errors logged as `ERROR pubsub-broker: …` via `log.Printf`.

# 129-itinerary-planner

Trip itinerary planning service. Persists itineraries and items in Postgres; caches read-through itinerary snapshots in Redis with 10 min TTL.

**Stack:** Kotlin / Ktor (gradle:8.7-jdk21 → eclipse-temurin:21-jre-jammy)
**Deps:** postgres, redis-cache

## Endpoints
- `GET /healthz`
- `POST /itineraries` — body `{user_id, title, start_date, end_date}`
- `GET /itineraries/:id` — cache-aside via `itin:{id}` (SETEX 600)
- `POST /itineraries/:id/items` — body `{day, activity, location?}` → DEL `itin:{id}`
- `GET /users/:user_id/itineraries`

## Schema
```sql
CREATE TABLE itineraries(id serial PRIMARY KEY, user_id text, title text, start_date date, end_date date, created_at timestamptz DEFAULT now());
CREATE TABLE itinerary_items(id serial PRIMARY KEY, itinerary_id int REFERENCES itineraries(id) ON DELETE CASCADE, day int, activity text, location text);
```

All errors logged via SLF4J as `log.error("itinerary-planner: {}", e.message, e)`. Jedis 2 s connection timeout, single-connection pool (max=4).

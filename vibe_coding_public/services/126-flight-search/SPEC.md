# 126-flight-search

Flight search and caching service. Looks up flights by origin/destination/date in a Redis cache; on miss calls the mock upstream, caches the response for 5 minutes, and persists it to Postgres for warm rebuilds.

Endpoints: `GET /healthz`, `POST /flights/search`, `GET /flights/search?origin=&dest=&date=`, `POST /flights/cache-populate`.

# 137-reservation-svc

Restaurant reservation service. Persists reservations in Postgres and indexes them per restaurant+date in a Redis cache (`rsv:{restaurant_id}:{YYYY-MM-DD}` set of reservation ids) for fast lookups. Listing reservations for a restaurant on a given date hits Redis first and falls back to Postgres on miss/error.

Endpoints: `GET /healthz`, `POST /reservations`, `GET /reservations/{restaurant_id}?date=YYYY-MM-DD`, `PUT /reservations/{id}/cancel`, `GET /reservations/user/{user_id}`.

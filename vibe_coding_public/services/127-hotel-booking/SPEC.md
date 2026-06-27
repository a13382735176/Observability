# 127-hotel-booking

Hotel booking service with event streaming. Persists bookings in Postgres and emits booking-created / booking-cancelled events to a Redis Stream (`events:bookings`).

Endpoints: `GET /healthz`, `POST /bookings`, `GET /bookings/{user_id}`, `PUT /bookings/{id}/cancel`.

# 136-event-ticketing

Event ticketing service with sales event streaming. Persists events and tickets in Postgres and emits ticket-sold events to a Redis Stream (`events:ticket_sales`). Enforces capacity (sum of ticket quantities < total_tickets) and returns 409 when sold out.

Endpoints: `GET /healthz`, `POST /events`, `POST /tickets/buy`, `GET /events/{id}`, `GET /tickets/{user_id}`.

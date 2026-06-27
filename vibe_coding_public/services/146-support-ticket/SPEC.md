# 146-support-ticket

Python/Flask service for customer support ticket tracking. Tickets stored in Postgres; the set of currently-open ticket IDs is mirrored in a Redis SET for fast listing.

Endpoints: GET /healthz, POST /tickets, GET /tickets/:id, GET /tickets/open, PUT /tickets/:id/close, GET /tickets/user/:user_id.

Deps: postgres (support_tickets table, auto-created), redis-cache (open_tickets SET).

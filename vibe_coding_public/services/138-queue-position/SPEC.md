# 138-queue-position

Generic FIFO queue position service backed by Redis lists. Tracks per-named-queue waiting users, exposes position lookup (LPOS), dequeue (LPOP), and length (LLEN). Used as a building block for things like virtual waiting rooms or ticket-sale queues.

Endpoints: `GET /healthz`, `POST /queue/join`, `GET /queue/{queue_name}/position/{user_id}`, `POST /queue/{queue_name}/next`, `GET /queue/{queue_name}/length`.

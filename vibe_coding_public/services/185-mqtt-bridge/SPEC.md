# 185-mqtt-bridge

Simulated MQTT broker bridge. Accepts publish requests over HTTP (no real MQTT client), persists every message to Postgres `mqtt_messages` with QoS 0/1/2, and fans the event out onto the Redis Stream `events:mqtt` so downstream consumers can react. Also tracks per-client subscription patterns in Postgres so a future broker can match them against incoming topics.

Endpoints: `GET /healthz`, `POST /messages`, `GET /messages/topic/{topic}?limit=50`, `POST /subscriptions`, `GET /subscriptions/{client_id}`, `DELETE /subscriptions/{id}`.

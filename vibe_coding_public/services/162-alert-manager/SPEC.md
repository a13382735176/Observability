# 162-alert-manager

Threshold-based alerting service. Operators register rules against named metrics; evaluation requests check incoming metric values, fire alerts when comparators match, persist them in Postgres, and publish to the `events:alerts` Redis stream. Operators acknowledge alerts to close them out.

Endpoints: `GET /healthz`, `POST /rules`, `GET /rules`, `POST /evaluate`, `GET /alerts`, `PUT /alerts/<id>/ack`.

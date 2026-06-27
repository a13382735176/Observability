# 124-cert-renewal-svc

TLS certificate inventory and renewal service. Tracks certificates by domain, surfaces expiring ones, and extends their validity period on demand. Persists state in Postgres.

Endpoints: `GET /healthz`, `POST /certs`, `GET /certs/expiring`, `GET /certs/<domain>`, `POST /certs/<id>/renew`.

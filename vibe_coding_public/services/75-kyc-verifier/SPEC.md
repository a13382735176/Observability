# 75-kyc-verifier

Financial KYC (Python/FastAPI, postgres+upstream).

## Deps
- postgres
- upstream (mock-upstream:8080)

## Endpoints
- GET /healthz
- POST /verify {user_id, doc_type, doc_number}
- GET /status/:user_id

## Table
kyc_records(id serial, user_id text, status text, doc_type text, verified_at timestamptz)

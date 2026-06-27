# 134-visa-application

Java 21 / Spring Boot 3.3 service that manages visa applications backed by postgres
via Spring Data JPA.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"visa-application"}`
- `POST /applications` body `{user_id, destination_country, travel_date, purpose}`
- `GET /applications/{user_id}` → list ordered by id desc
- `PUT /applications/{id}/status` body `{status:"pending"|"approved"|"rejected"}`
- `GET /applications` → all applications

## Schema
`visa_applications(id serial PK, user_id text, destination_country text,
travel_date date, purpose text, status text default 'pending',
submitted_at timestamptz default now())`

## Faults
F01, F02, F05, F06, F11, F12, F13.

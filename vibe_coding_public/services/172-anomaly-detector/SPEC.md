# 172-anomaly-detector

Python/Flask service that ingests numerical metric samples, computes a 1-hour rolling
mean/stddev per metric, flags points more than 3 stddevs from the mean as anomalies,
and emits an event to a redis stream.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"anomaly-detector"}`
- `POST /samples` → body `{metric, value:float}`; INSERT `data_samples`. If 1h sample count > 10 and `|value - avg| > 3*stddev`, INSERT `anomalies` and `XADD events:anomalies metric=<metric> value=<value> z_score=<z>`.
- `GET /anomalies` → last 50 anomalies (`detected_at DESC`).
- `GET /samples/{metric}/stats` → `{metric, avg, stddev, count}` for the last hour.
- `GET /samples/{metric}/recent` → last 100 raw samples.

## Schema
```
data_samples(id bigserial PK, metric text, value double precision,
             created_at timestamptz default now())

anomalies(id bigserial PK, metric text, value double precision,
          z_score double precision, detected_at timestamptz default now())
```

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.

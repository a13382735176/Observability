# Generate 141-order-fulfillment-skill

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `services_skill/141-order-fulfillment-skill`
- Service ID: `141-order-fulfillment-skill`
- Kubernetes app label: `order-fulfillment-skill`
- Image: `vibe/141-order-fulfillment-skill:dev`
- Language/stack: Python
- Port: 8080

## Invariants

- Keep the HTTP API paths and request/response field names compatible.
- Keep database table structure compatible.
- Keep dependency usage compatible: postgres, redis-stream.
- Keep the service runnable on port 8080 with the listed environment variables.
- Logs and internal implementation are free to differ from the baseline.

## Service Contract

```json
{
  "schema_version": 1,
  "service": {
    "service_id": "141-order-fulfillment-skill",
    "app_label": "order-fulfillment-skill",
    "image": "vibe/141-order-fulfillment-skill:dev",
    "target_dir": "services_skill/141-order-fulfillment-skill",
    "port": 8080,
    "language": "python",
    "language_stack": "Python"
  },
  "responsibility": "141-order-fulfillment",
  "behavior_contract": "",
  "endpoints": [
    "GET /healthz` → `{\"status\":\"ok\",\"service\":\"order-fulfillment\"}",
    "POST /orders` — body `{user_id, items:[{sku, quantity, price_cents}]}`. Computes `total_cents = sum(quantity * price_cents)`, INSERTs into `orders` + `order_items` in one connection (transactional commit), then `XADD events:orders {order_id, user_id, total_cents}`.",
    "GET /orders/:id` — returns order header + all line items via `LEFT JOIN`.",
    "GET /orders/user/:user_id` — last 20 orders by `id DESC`.",
    "PUT /orders/:id/status` — body `{status}` — `UPDATE orders SET status=$1`, then `XADD events:order_status {order_id, status}`."
  ],
  "dependencies": [
    "postgres",
    "redis-stream"
  ],
  "state_contract": {
    "postgres_schema_sql": [
      "CREATE TABLE orders( id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, total_cents BIGINT NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'placed', created_at TIMESTAMPTZ NOT NULL DEFAULT now() );",
      "CREATE TABLE order_items( id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL, sku TEXT NOT NULL, quantity INT NOT NULL, price_cents INT NOT NULL );",
      "CREATE TABLE IF NOT EXISTS orders(\" \"id BIGSERIAL PRIMARY KEY,\" \"user_id TEXT NOT NULL,\" \"total_cents BIGINT NOT NULL DEFAULT 0,\" \"status TEXT NOT NULL DEFAULT 'placed',\" \"created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
      "CREATE TABLE IF NOT EXISTS order_items(\" \"id BIGSERIAL PRIMARY KEY,\" \"order_id BIGINT NOT NULL,\" \"sku TEXT NOT NULL,\" \"quantity INT NOT NULL,\" \"price_cents INT NOT NULL)"
    ],
    "named_state_keys_or_streams": [
      "events:order_status",
      "events:orders"
    ]
  },
  "runtime_env": [
    {
      "name": "APP_NAME",
      "value": "order-fulfillment-skill"
    },
    {
      "name": "PG_DSN",
      "value": "postgres://vibe:vibe@postgres:5432/vibe"
    },
    {
      "name": "REDIS_STREAM_HOST",
      "value": "redis-stream"
    },
    {
      "name": "REDIS_STREAM_PORT",
      "value": "6379"
    }
  ],
  "docker_build_contract": {
    "build_context_after_import": "services_skill/141-order-fulfillment-skill",
    "image": "vibe/141-order-fulfillment-skill:dev",
    "source_root_visible_to_generator": "src",
    "generator_may_create_or_modify": [
      "src/**"
    ],
    "generator_must_not_create_or_modify": [
      "anything outside src/"
    ],
    "validation_command_after_import": "docker build -t vibe/141-order-fulfillment-skill:dev .",
    "dockerfile_used_by_private_harness": "FROM python:3.12-slim\nWORKDIR /app\nCOPY src/requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY src/ .\nEXPOSE 8080\nCMD [\"python\", \"-u\", \"main.py\"]\n"
  },
  "readiness_path": "/healthz",
  "generation_constraints": [
    "Generate a fresh implementation from this contract only.",
    "Keep API paths, request fields, response fields, dependencies, and database schema compatible with the contract.",
    "Keep the service runnable on port 8080 with the listed environment variables and Docker build contract.",
    "Do not copy any pre-existing source code or log wording.",
    "Do not infer or implement hidden evaluation behavior from this contract.",
    "The observability skill may only affect application-level diagnostic messages inside the described service shape.",
    "Do not add endpoints, dependencies, persistent state, background workers, or external telemetry infrastructure beyond the contract.",
    "Do not add OpenTelemetry, Prometheus, Jaeger, Grafana, or external telemetry infrastructure.",
    "Create or modify only files under src/; all other files are owned by the private runtime environment."
  ]
}
```

## Observability Engineering Skill

Apply this skill internally while generating the service. Do not output your plan.

1. Discover the operational role.
   Generation mode: identify the service responsibility, endpoints, background
   work, state, dependencies, startup and shutdown behavior, and operational
   boundaries where failures or latency would affect users.
2. Mine or establish observability conventions.
   Generation mode: follow local project conventions if they exist. Otherwise,
   choose simple, idiomatic application-level observability for the selected
   stack, with consistent service, operation, dependency, error, latency, and
   request context fields.
3. Plan diagnostic signals internally.
   Add only signals with clear operational value. Each signal should help an
   operator understand failure, latency, throughput, or an important state
   transition. Prefer dependency boundaries and control-flow boundaries. Avoid
   high-cardinality fields, secrets, credentials, tokens, raw payloads, or PII.
4. Instrument only the target scope.
   Generation mode: include observability inside the generated service's
   handlers, dependency calls, background tasks, startup and shutdown, and error
   handling, without adding unrelated infrastructure or external telemetry
   stacks unless explicitly requested.
5. Self-check internally.
   Generation mode: check that the generated code remains simple, runnable, and
   diagnosable from its own application-level signals during ordinary failures,
   latency, and degraded paths. Remove noisy or duplicate signals.



## Output Contract

Create or update only files under `services_skill/141-order-fulfillment-skill`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/141-order-fulfillment` or hidden experiment harness files.

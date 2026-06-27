# Generate 08-notification-dispatcher-skill

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `services_skill/08-notification-dispatcher-skill`
- Service ID: `08-notification-dispatcher-skill`
- Kubernetes app label: `notification-dispatcher-skill`
- Image: `vibe/08-notification-dispatcher-skill:dev`
- Language/stack: Python
- Port: 8080

## Invariants

- Keep the HTTP API paths and request/response field names compatible.
- Keep database table structure compatible.
- Keep dependency usage compatible: mock-upstream, redis-stream.
- Keep the service runnable on port 8080 with the listed environment variables.
- Logs and internal implementation are free to differ from the baseline.

## Service Contract

```json
{
  "schema_version": 1,
  "service": {
    "service_id": "08-notification-dispatcher-skill",
    "app_label": "notification-dispatcher-skill",
    "image": "vibe/08-notification-dispatcher-skill:dev",
    "target_dir": "services_skill/08-notification-dispatcher-skill",
    "port": 8080,
    "language": "python",
    "language_stack": "Python"
  },
  "responsibility": "Python + FastAPI + redis.asyncio + httpx。后台生产者每 2s 向 `notifications:queue` XADD 通知；消费者用 XREADGROUP 拉取，POST 到 mock-upstream `/send`。",
  "behavior_contract": "`，并把 failed 计数加一。",
  "endpoints": [
    "GET /healthz",
    "GET /stats dispatched / failed 计数"
  ],
  "dependencies": [
    "mock-upstream",
    "redis-stream"
  ],
  "state_contract": {
    "postgres_schema_sql": [],
    "named_state_keys_or_streams": [
      "notifications:queue"
    ]
  },
  "runtime_env": [
    {
      "name": "APP_NAME",
      "value": "notification-dispatcher-skill"
    },
    {
      "name": "REDIS_STREAM_URL",
      "value": "redis://redis-stream:6379/0"
    },
    {
      "name": "REDIS_STREAM_HOST",
      "value": "redis-stream"
    },
    {
      "name": "REDIS_STREAM_PORT",
      "value": "6379"
    },
    {
      "name": "UPSTREAM_URL",
      "value": "http://mock-upstream:8080"
    }
  ],
  "docker_build_contract": {
    "build_context_after_import": "services_skill/08-notification-dispatcher-skill",
    "image": "vibe/08-notification-dispatcher-skill:dev",
    "source_root_visible_to_generator": "src",
    "generator_may_create_or_modify": [
      "src/**"
    ],
    "generator_must_not_create_or_modify": [
      "anything outside src/"
    ],
    "validation_command_after_import": "docker build -t vibe/08-notification-dispatcher-skill:dev .",
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

Create or update only files under `services_skill/08-notification-dispatcher-skill`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/08-notification-dispatcher` or hidden experiment harness files.

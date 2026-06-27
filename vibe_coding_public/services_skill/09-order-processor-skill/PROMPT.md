# Generate 09-order-processor-skill

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `services_skill/09-order-processor-skill`
- Service ID: `09-order-processor-skill`
- Kubernetes app label: `order-processor-skill`
- Image: `vibe/09-order-processor-skill:dev`
- Language/stack: Java
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
    "service_id": "09-order-processor-skill",
    "app_label": "order-processor-skill",
    "image": "vibe/09-order-processor-skill:dev",
    "target_dir": "services_skill/09-order-processor-skill",
    "port": 8080,
    "language": "java",
    "language_stack": "Java"
  },
  "responsibility": "Java + Javalin + JDBC + Jedis。后台生产者每 5s 向 `orders:queue` XADD 订单；消费者 XREADGROUP 拉取后 INSERT 到 `processed_orders` 表并 XACK。",
  "behavior_contract": "`。",
  "endpoints": [
    "GET /healthz"
  ],
  "dependencies": [
    "postgres",
    "redis-stream"
  ],
  "state_contract": {
    "postgres_schema_sql": [
      "CREATE TABLE IF NOT EXISTS processed_orders( id BIGSERIAL PRIMARY KEY, source_order_id TEXT NOT NULL, user_id TEXT NOT NULL, payload TEXT NOT NULL, processed_at TIMESTAMPTZ DEFAULT NOW())"
    ],
    "named_state_keys_or_streams": [
      "orders:queue"
    ]
  },
  "runtime_env": [
    {
      "name": "APP_NAME",
      "value": "order-processor-skill"
    },
    {
      "name": "PG_DSN",
      "value": "postgres://vibe:vibe@postgres:5432/vibe"
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
    }
  ],
  "docker_build_contract": {
    "build_context_after_import": "services_skill/09-order-processor-skill",
    "image": "vibe/09-order-processor-skill:dev",
    "source_root_visible_to_generator": "src",
    "generator_may_create_or_modify": [
      "src/**"
    ],
    "generator_must_not_create_or_modify": [
      "anything outside src/"
    ],
    "validation_command_after_import": "docker build -t vibe/09-order-processor-skill:dev .",
    "dockerfile_used_by_private_harness": "FROM maven:3.9-eclipse-temurin-21 AS build\nWORKDIR /work\nCOPY src/pom.xml .\nRUN mvn -q -B -DskipTests dependency:go-offline || true\nCOPY src/src/ src/\nRUN mvn -q -B -DskipTests package\n\nFROM eclipse-temurin:21-jre-alpine\nCOPY --from=build /work/target/*-jar-with-dependencies.jar /app.jar\nEXPOSE 8080\nCMD [\"java\", \"-jar\", \"/app.jar\"]\n"
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

Create or update only files under `services_skill/09-order-processor-skill`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/09-order-processor` or hidden experiment harness files.

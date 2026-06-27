# Generate 120-access-proxy-skill

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `services_skill/120-access-proxy-skill`
- Service ID: `120-access-proxy-skill`
- Kubernetes app label: `access-proxy-skill`
- Image: `vibe/120-access-proxy-skill:dev`
- Language/stack: Rust
- Port: 8080

## Invariants

- Keep the HTTP API paths and request/response field names compatible.
- Keep database table structure compatible.
- Keep dependency usage compatible: redis-cache.
- Keep the service runnable on port 8080 with the listed environment variables.
- Logs and internal implementation are free to differ from the baseline.

## Service Contract

```json
{
  "schema_version": 1,
  "service": {
    "service_id": "120-access-proxy-skill",
    "app_label": "access-proxy-skill",
    "image": "vibe/120-access-proxy-skill:dev",
    "target_dir": "services_skill/120-access-proxy-skill",
    "port": 8080,
    "language": "rust",
    "language_stack": "Rust"
  },
  "responsibility": "access-proxy",
  "behavior_contract": "",
  "endpoints": [
    "POST /tokens` body `{user_id, scopes:[str]}` → `{token, user_id, scopes, ttl}` (UUID; HSET token:{uuid}; EXPIRE 3600)",
    "POST /validate` body `{token}` → `{valid:true,user_id,scopes}` or 401",
    "DELETE /tokens/:token` → 204"
  ],
  "dependencies": [
    "redis-cache"
  ],
  "state_contract": {
    "postgres_schema_sql": [],
    "named_state_keys_or_streams": []
  },
  "runtime_env": [
    {
      "name": "APP_NAME",
      "value": "access-proxy-skill"
    },
    {
      "name": "REDIS_CACHE_HOST",
      "value": "redis-cache"
    },
    {
      "name": "REDIS_CACHE_PORT",
      "value": "6379"
    }
  ],
  "docker_build_contract": {
    "build_context_after_import": "services_skill/120-access-proxy-skill",
    "image": "vibe/120-access-proxy-skill:dev",
    "source_root_visible_to_generator": "src",
    "generator_may_create_or_modify": [
      "src/**"
    ],
    "generator_must_not_create_or_modify": [
      "anything outside src/"
    ],
    "validation_command_after_import": "docker build -t vibe/120-access-proxy-skill:dev .",
    "dockerfile_used_by_private_harness": "FROM rust:1.88-slim AS build\nWORKDIR /work\nRUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*\nCOPY src/ ./\nRUN cargo build --release\n\nFROM debian:bookworm-slim\nWORKDIR /app\nRUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*\nCOPY --from=build /work/target/release/access-proxy-skill /app/access-proxy-skill\nEXPOSE 8080\nENTRYPOINT [\"/app/access-proxy-skill\"]\n"
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

Create or update only files under `services_skill/120-access-proxy-skill`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/120-access-proxy` or hidden experiment harness files.

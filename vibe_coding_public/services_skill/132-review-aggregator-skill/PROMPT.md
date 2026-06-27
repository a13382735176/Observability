# Generate 132-review-aggregator-skill

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `services_skill/132-review-aggregator-skill`
- Service ID: `132-review-aggregator-skill`
- Kubernetes app label: `review-aggregator-skill`
- Image: `vibe/132-review-aggregator-skill:dev`
- Language/stack: Rust
- Port: 8080

## Invariants

- Keep the HTTP API paths and request/response field names compatible.
- Keep database table structure compatible.
- Keep dependency usage compatible: none.
- Keep the service runnable on port 8080 with the listed environment variables.
- Logs and internal implementation are free to differ from the baseline.

## Service Contract

```json
{
  "schema_version": 1,
  "service": {
    "service_id": "132-review-aggregator-skill",
    "app_label": "review-aggregator-skill",
    "image": "vibe/132-review-aggregator-skill:dev",
    "target_dir": "services_skill/132-review-aggregator-skill",
    "port": 8080,
    "language": "rust",
    "language_stack": "Rust"
  },
  "responsibility": "132-review-aggregator",
  "behavior_contract": "",
  "endpoints": [
    "GET /healthz` → `{\"status\":\"ok\",\"service\":\"review-aggregator\"}",
    "POST /reviews` → body `{entity_id, entity_type, rating, body, author_id}`; persists row.",
    "GET /reviews/{entity_id}` → last 50 reviews for the entity.",
    "GET /aggregate/{entity_type}/{entity_id}` → `{avg, count}` (cache TTL 300s)."
  ],
  "dependencies": [],
  "state_contract": {
    "postgres_schema_sql": [
      "CREATE TABLE IF NOT EXISTS aggregated_reviews( id serial PRIMARY KEY, entity_id text, entity_type text, rating int, body text, author_id text, created_at timestamptz default now() )"
    ],
    "named_state_keys_or_streams": []
  },
  "runtime_env": [],
  "docker_build_contract": {
    "build_context_after_import": "services_skill/132-review-aggregator-skill",
    "image": "vibe/132-review-aggregator-skill:dev",
    "source_root_visible_to_generator": "src",
    "generator_may_create_or_modify": [
      "src/**"
    ],
    "generator_must_not_create_or_modify": [
      "anything outside src/"
    ],
    "validation_command_after_import": "docker build -t vibe/132-review-aggregator-skill:dev .",
    "dockerfile_used_by_private_harness": "FROM rust:1.88-slim AS build\nWORKDIR /work\nRUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*\nCOPY src/Cargo.toml .\nRUN mkdir -p src && echo 'fn main(){}' > src/main.rs && cargo build --release && rm -rf src target/release/deps/review_aggregator*\nCOPY src/src/ src/\nRUN cargo build --release\n\nFROM debian:bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3 && rm -rf /var/lib/apt/lists/*\nCOPY --from=build /work/target/release/review-aggregator-skill /app\nEXPOSE 8080\nCMD [\"/app\"]\n"
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

Create or update only files under `services_skill/132-review-aggregator-skill`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/132-review-aggregator` or hidden experiment harness files.

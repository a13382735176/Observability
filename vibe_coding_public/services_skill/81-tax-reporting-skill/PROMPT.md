# Generate 81-tax-reporting-skill

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `services_skill/81-tax-reporting-skill`
- Service ID: `81-tax-reporting-skill`
- Kubernetes app label: `tax-reporting-skill`
- Image: `vibe/81-tax-reporting-skill:dev`
- Language/stack: Python
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
    "service_id": "81-tax-reporting-skill",
    "app_label": "tax-reporting-skill",
    "image": "vibe/81-tax-reporting-skill:dev",
    "target_dir": "services_skill/81-tax-reporting-skill",
    "port": 8080,
    "language": "python",
    "language_stack": "Python"
  },
  "responsibility": "81-tax-reporting",
  "behavior_contract": "",
  "endpoints": [
    "GET /healthz` → `{\"status\":\"ok\",\"service\":\"tax-reporting\"}",
    "POST /reports` body: `{user_id, tax_year, income_cents, deductions_cents}` → taxable=income-deductions; saves to DB",
    "GET /reports/:user_id` → list all reports for user",
    "GET /report/:id` → single report by id"
  ],
  "dependencies": [],
  "state_contract": {
    "postgres_schema_sql": [
      "CREATE TABLE IF NOT EXISTS tax_reports( id serial PRIMARY KEY, user_id text, tax_year int, income_cents bigint, deductions_cents bigint, taxable_cents bigint, created_at timestamptz DEFAULT now() )"
    ],
    "named_state_keys_or_streams": []
  },
  "runtime_env": [],
  "docker_build_contract": {
    "build_context_after_import": "services_skill/81-tax-reporting-skill",
    "image": "vibe/81-tax-reporting-skill:dev",
    "source_root_visible_to_generator": "src",
    "generator_may_create_or_modify": [
      "src/**"
    ],
    "generator_must_not_create_or_modify": [
      "anything outside src/"
    ],
    "validation_command_after_import": "docker build -t vibe/81-tax-reporting-skill:dev .",
    "dockerfile_used_by_private_harness": "FROM python:3.12-slim\nWORKDIR /app\nCOPY src/requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY src/ .\nEXPOSE 8080\nCMD [\"python\", \"-u\", \"app.py\"]\n"
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

Create or update only files under `services_skill/81-tax-reporting-skill`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/81-tax-reporting` or hidden experiment harness files.

---
name: p_skill_vibe_transfer
description: >
  Verbatim-transfer observability skill prompt. Holds the same task framing,
  module context, sibling examples, and final-output contract as p_fewshot,
  then inserts the Generation-mode Observability Engineering Skill block used
  by the vibe-coding microservice-generation benchmark. This prompt is intended
  as a clean transfer ablation: the skill text is not adapted to function-level
  patching.
strip_telemetry: false
fewshot_k: 2
forbid:
  # Same ladder constraint as p_fewshot.
  - opentelemetry
  - otel
  - prometheus
  - jaeger
  - grafana
  - structured log
---
You are a senior backend engineer reviewing a pull request.

Below is **one** {{LANGUAGE_NAME}} function from a service that is about to be
deployed to a high-traffic production environment. A senior reviewer has
identified that this function **lacks observability**: an on-call engineer
would not be able to debug a production incident affecting this code path.

Add appropriate observability -- logging, metrics, tracing, or whatever
combination you judge necessary -- so that a failed call leaves enough
evidence to root-cause it, a slow call can be attributed to the right
sub-step, and aggregate health (rate, error, duration) can be measured.
**Do not over-instrument.** Each signal you add should provide clear
operational value.

For your reference, here are the module-level symbols already initialised
elsewhere in this file. **Do not redeclare any of them, do not modify them,
do not wrap them in getter functions.** Reuse the libraries and handles you
see below -- do not introduce a different telemetry stack.

```{{LANGUAGE_FENCE}}
{{MODULE_CONTEXT}}
```

Here are neighbouring functions from the **same file** that already have
appropriate observability. **Match their style, naming conventions, and the
libraries / handles they use.** Treat them as the project's house style.

{{SIBLING_EXAMPLES}}

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

You MUST follow these constraints exactly:

1. **Return exactly ONE {{LANGUAGE_NAME}} code block** containing **only the
   single function definition**. No prose before or after. No second code
   block. No additional helper functions.
2. Preserve the function signature **byte-identically** -- same name,
   parameters, type hints, default values, decorators.
3. Preserve the function's external behaviour (inputs -> outputs on the happy
   path) and its return type.
4. Do **not** add new helper functions, do **not** add new `import` lines,
   do **not** add new module-level variables.
5. Do **not** rename local variables or change the function's local control
   flow beyond what is strictly necessary for the observability you add.
6. Do **not** change the database schema, SQL queries, or RPC contracts.
7. Do **not** add unit tests (not in scope for this review).

File: `{{FILEPATH}}`
Function to instrument: `{{FUNCTION}}`

```{{LANGUAGE_FENCE}}
{{TARGET_FUNCTION_SOURCE}}
```
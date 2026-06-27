---
name: p_skill_observability
description: >
  Skill-augmented few-shot observability prompt. Holds the same task framing,
  module context, sibling examples, and final-output contract as p_fewshot,
  then adds one bounded five-step Observability Engineering Skill block. The
  skill generalizes across patching existing code and generating new services
  by adapting only the target scope; it must never ask questions or output its
  plan.
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

Apply this Observability Engineering Skill internally before writing the final
answer. Do not output your skill procedure, reasoning, plan, assumptions, tool
usage, checklist, or validation notes.

First determine the task mode:

- Patch mode: the task asks you to modify, reconstruct, or complete existing
  code, a target function, a target file, or a bounded code region.
- Generation mode: the task asks you to create a new service, microservice,
  endpoint set, background worker, or application component.

Then apply the same five-step workflow with the appropriate target scope:

1. Discover the operational role.
   Patch mode: identify what the target code does, including request or job
   boundaries, error paths, external calls, retries, state transitions, cache or
   database access, and branches that would matter during an incident.
   Generation mode: identify the service responsibility, endpoints, background
   work, state, dependencies, startup and shutdown behavior, and operational
   boundaries where failures or latency would affect users.
2. Mine or establish observability conventions.
   Patch mode: reuse the logger, tracer, metric handles, severity levels,
   message style, key names, span names, metric names, correlation IDs, and
   context fields that already appear nearby. Prefer the same file, then the
   same directory or module, then the wider repository.
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
   Patch mode: keep changes limited to the requested code, preserve behavior,
   and prefer existing handles and helper APIs. Do not introduce a new
   observability stack.
   Generation mode: include observability inside the generated service's
   handlers, dependency calls, background tasks, startup and shutdown, and error
   handling, without adding unrelated infrastructure or external telemetry
   stacks unless explicitly requested.
5. Self-check internally.
   Patch mode: remove duplicate or noisy signals; check that the final code
   follows local style, preserves the function signature when one is provided,
   and contains only changes needed for observability.
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

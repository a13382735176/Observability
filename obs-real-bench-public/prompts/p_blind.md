---
name: p_blind
description: >
  Telemetry-blind baseline. Identical prose to p0_vanilla (no mention of
  observability anywhere in the natural-language portion), AND the
  surrounding module context shown to the LLM is scrubbed of every
  telemetry tell — opentelemetry / prometheus / jaeger / structlog /
  logging imports are removed, and module-level tracer/logger/meter
  setup assignments are dropped before rendering. This isolates the
  causal question p0_vanilla was meant to answer ("does the LLM add
  observability spontaneously?") from the contamination of the LLM
  seeing OTel already wired up in the file. p2_otel_explicit keeps the
  full setup visible by design and is unaffected.
strip_telemetry: true
forbid:
  # Substrings (case-insensitive) that must NOT appear in the rendered prompt
  # OUTSIDE the source-code block. run_llm.py aborts before sending if any
  # match is found. Same list as p0_vanilla.
  - observ
  - telemetr
  - tracing
  - traces
  - span
  - spans
  - metric
  - metrics
  - instrument
  - monitor
  - opentelemetry
  - otel
  - prometheus
  - jaeger
  - grafana
  - sre
  - rca
  - structured log
  - log level
  - log-level
  - logger
  - logging
---
You are a senior backend engineer reviewing a pull request.

Below is **one** {{LANGUAGE_NAME}} function from a service that is about to be
deployed to a high-traffic production environment. The current implementation
works on the happy path but a senior reviewer has flagged it as not ready for
production.

Improve **only this function** so that it is production-ready. Focus on what
an experienced on-call engineer would want when debugging an incident at
3 AM. Apply only the changes you believe a senior reviewer would actually
require.

For your reference only, here are the module-level symbols already initialised
elsewhere in this file. **Do not redeclare any of them, do not modify them,
do not wrap them in getter functions.** Reference them by name if you need
them.

```{{LANGUAGE_FENCE}}
{{MODULE_CONTEXT}}
```

You MUST follow these constraints exactly:

1. **Return exactly ONE {{LANGUAGE_NAME}} code block** containing **only the
   single function definition**. No prose before or after. No second code
   block. No additional helper functions.
2. Preserve the function signature **byte-identically** — same name,
   parameters, type hints, default values, decorators.
3. Preserve the function's external behaviour (inputs → outputs on the happy
   path) and its return type.
4. Do **not** add new helper functions (`def _foo(...)`), do **not** add new
   `import` lines, do **not** add new module-level variables.
5. Do **not** rename local variables or change the function's local control
   flow beyond what is strictly necessary for the improvement you are making.
6. Do **not** change the database schema, SQL queries, or RPC contracts.
7. Do **not** add unit tests (not in scope for this review).

File: `{{FILEPATH}}`
Function to improve: `{{FUNCTION}}`

```{{LANGUAGE_FENCE}}
{{TARGET_FUNCTION_SOURCE}}
```

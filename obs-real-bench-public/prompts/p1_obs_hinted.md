---
name: p1_obs_hinted
description: >
  Observability-hinted prompt. Holds scaffolding identical to p_blind
  (module context visible, ONE-function output, same 7 hard constraints)
  and changes ONLY the task framing: the model is explicitly told the
  function lacks observability and should be instrumented. No specific
  library named (OpenTelemetry / Prometheus / etc. are forbidden in the
  prose) so the LLM must pick a library from the module context.
  Isolates the marginal effect of "telling the model what to do" while
  holding context constant.
strip_telemetry: false
forbid:
  # Naming a specific telemetry technology would prescribe the answer and
  # confound this rung of the ladder with p2-style explicit prompts.
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

Add appropriate observability — logging, metrics, tracing, or whatever
combination you judge necessary — so that a failed call leaves enough
evidence to root-cause it, a slow call can be attributed to the right
sub-step, and aggregate health (rate, error, duration) can be measured.


For your reference, here are the module-level symbols already initialised
elsewhere in this file. **Do not redeclare any of them, do not modify them,
do not wrap them in getter functions.** Reuse the libraries and handles you
see below — do not introduce a different telemetry stack.

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

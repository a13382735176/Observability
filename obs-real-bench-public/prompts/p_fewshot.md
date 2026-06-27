---
name: p_fewshot
description: >
  Few-shot observability prompt. Holds scaffolding and task framing
  identical to p1_obs_hinted (module context visible, ONE-function
  output, same 7 hard constraints, same "lacks observability" prose)
  and adds ONLY k sibling functions from the same file — with their
  ground-truth observability intact — spliced in as style anchors.
  Isolates the marginal effect of project-specific exemplars on top
  of the obs-hint.

  K is the experiment variable. Storage K (the cap in
  build_siblings.py) is 5; render-time k is `fewshot_k` below.
strip_telemetry: false
fewshot_k: 2
forbid:
  # Same ladder constraint as p1_obs_hinted.
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
**Do not over-instrument.** Each signal you add should provide clear
operational value.

For your reference, here are the module-level symbols already initialised
elsewhere in this file. **Do not redeclare any of them, do not modify them,
do not wrap them in getter functions.** Reuse the libraries and handles you
see below — do not introduce a different telemetry stack.

```{{LANGUAGE_FENCE}}
{{MODULE_CONTEXT}}
```

Here are neighbouring functions from the **same file** that already have
appropriate observability. **Match their style, naming conventions, and the
libraries / handles they use.** Treat them as the project's house style.

{{SIBLING_EXAMPLES}}

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

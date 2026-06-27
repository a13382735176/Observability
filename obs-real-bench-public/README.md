# obs-real-bench

A benchmark for evaluating whether code models and coding agents can restore
observability instrumentation that has been stripped from real production or
reference code.

The benchmark is function-level: each instance points to a real source file and
a target function. The pipeline reads the original function, removes logging,
tracing, and metrics calls, asks a model or agent to add observability back, and
then scores the generated function against the original observability behavior.

This public copy contains the open-source benchmark instances only. Local run
outputs are intentionally not bundled.

---

## Repository Status

The current repository is the OSS-only public benchmark subset.

Current on-disk instance set:

```text
instance JSON files: 680
runnable instances:  561
quarantined:         119
languages:           cpp, cs, go, java, js, php, py, rb, rs, ts
largest slices:      trainticket, otel-demo, deathstar, vector, strapi,
              eshop, nestjs, boutique, sockshop, robusta
```

The public copy does not include generated `results/` or `runs/` directories.
New experiment outputs are generated locally when you run the pilot.

Important: `python -m tools.pilot --all` uses the current contents of
`instances/function/`, skipping only files marked `_runnable: false`. In this
repository, `--all` means the OSS-only public benchmark unless an explicit
filter or manifest is added.

---

## Core Task

For each target function:

1. Read the ground-truth source from `repo.local_path + target.file`.
2. Extract the target function by name.
3. Strip observability calls from that function.
4. Render one prompt level.
5. Call the selected backend.
6. Extract one generated function from the response.
7. Extract observability sites from ground truth and generated code.
8. Score placement and key recovery.
9. Persist per-cell results under `results/<run-id>/`.

The benchmark does not score whole-file text similarity. It scores whether the
model put observability in the right business-logic slots and recovered the
right observability keys or keyword concepts.

---

## Prompt Ladder

The active prompt ladder is:

| Prompt | Purpose |
|---|---|
| `p_blind` | Control prompt. Gives the stripped target function and scrubbed context without explicitly asking for observability. |
| `p1_obs_hinted` | Adds the instruction that the function lacks observability and should be instrumented. |
| `p_fewshot` | Same task framing as `p1_obs_hinted`, plus same-file sibling examples when available. |

Prompt files live in `prompts/`:

- `prompts/p_blind.md`
- `prompts/p1_obs_hinted.md`
- `prompts/p_fewshot.md`

All active prompts enforce the same output discipline: exactly one code block,
only the target function definition, no helper functions, no imports, no
module-level variables, and no prose outside the code block. These constraints
are important because the scorer expects to recover usable code from the model
response.

Headline comparisons should use the three active prompts above.

---

## Few-Shot Sibling Selection

`p_fewshot` uses sibling functions selected ahead of time and stored in each
instance JSON under the `siblings` field.

The sibling builder is `tools/build_siblings.py`. Its selection rule is:

1. Read the same ground-truth source file as the target function.
2. Enumerate functions or methods in that file.
3. Exclude the target function itself.
4. Extract observability sites for each remaining function.
5. Keep only functions with `n_gt > 0` observability sites.
6. Sort by `n_gt` descending, then by function name ascending.
7. Store up to `K` siblings in the instance JSON.

At render time, `p_fewshot.md` currently has `fewshot_k: 2`, so the pilot takes
the first two stored siblings and inserts their full original function bodies
with observability intact.

Some instances have no available sibling examples. In that case the rendered
prompt contains a neutral fallback message. Analyses of few-shot effects should
report or stratify by the number of rendered siblings.

---

## Backends

The unified model caller is `tools/llm_client.py`. The pilot supports:

| Backend | Meaning |
|---|---|
| `api` | Direct model call through the local Azure OpenAI helper. |
| `agent` | GitHub Copilot SDK / agent runtime. |

The agent batch wrapper is `run_all_agent.sh`. It performs a lightweight auth
and model preflight, then calls `tools.pilot` with `--backend agent`.

Authentication should be supplied through environment variables or local CLI
auth. Do not store tokens in the repository, result files, prompts, or shell
history intended for sharing.

---

## Results

Generated results are not included in this public copy. A completed pilot run
will create `results/<run-id>/summary.json`, and
`tools/aggregate_repo_lang.py <run-id>` will create the corresponding aggregate
Markdown report.

## Scoring

The primary metric for v2.x is **Key Bag F1 under STRICT filtering**.

STRICT policy:

1. Drop cells where the ground-truth function has `n_gt == 0` observability
   sites. These functions do not define a meaningful restoration target.
2. For remaining cells, count `key_bag_f1 == null` as 0 rather than removing the
   cell from the denominator.

Main scoring files:

| File | Purpose |
|---|---|
| `tools/score_anchor.py` | Python AST branch and shared anchor/Key Bag scoring. |
| `tools/score_anchor_ts.py` | Tree-sitter-backed scoring for non-Python languages. |
| `tools/aggregate_repo_lang.py` | Aggregates summary rows by repo and language. |
| `tools/rescore.py` | Recomputes scores for existing result directories. |

Each summary row may also include:

- Position F1: whether observability appears in the correct anchor slot.
- Key Bag precision/recall/F1: whether observability keys or keyword concepts
  match the ground truth.
- OldF1: legacy type-bag metric retained for backward compatibility.

Use Key Bag F1 as the primary metric unless a specific analysis says
otherwise.

---

## Directory Guide

| Path | Purpose |
|---|---|
| `instances/function/` | Function-level benchmark instances. |
| `prompts/` | Prompt templates and prompt frontmatter. |
| `tools/pilot.py` | End-to-end runner: strip, prompt, call backend, score, persist. |
| `tools/prompt_render.py` | Loads prompt templates and substitutes fields. |
| `tools/strip/` | Per-language observability stripping. |
| `tools/extract/` | Per-language observability-site extraction. |
| `tools/langspec.py` | Language registry for polyglot parsing and obs APIs. |
| `results/` | Generated run outputs and summaries; not bundled in this public copy. |
| `runs/` | Optional local experiment logs; not bundled in this public copy. |
| `run_all_agent.sh` | Batch wrapper for agent-runtime experiments. |

---

## Common Commands

Activate the local environment:

```bash
python -m venv .venv
source .venv/bin/activate
cd obs-real-bench-public
```

Run a single cell:

```bash
python -m tools.pilot \
  --instance otel-demo__py__recommendation__ListRecommendations-v1 \
  --prompt p_fewshot \
  --model gpt-5.5-20260424 \
  --backend api \
  --run-id scratch-one
```

Run all currently runnable instances with the API backend:

```bash
python -m tools.pilot \
  --all \
  --prompts p_blind,p1_obs_hinted,p_fewshot \
  --model gpt-5.5-20260424 \
  --backend api \
  --run-id my-api-run \
  --workers 70 \
  --skip-existing
```

Run all currently runnable instances with the agent backend:

```bash
./run_all_agent.sh \
  --run-id my-agent-run \
  --model gpt-5.5 \
  --prompts p_blind,p1_obs_hinted,p_fewshot \
  --workers 64
```

For audited repo-visible agent runs, add:

```bash
./run_all_agent.sh \
  --run-id my-agent-trace-run \
  --model gpt-5.5 \
  --prompts p_blind,p1_obs_hinted,p_fewshot \
  --workers 64 \
  --allow-agent-tools \
  --agent-repo-context related \
  --agent-trace
```

If an instance JSON contains a stale `repo.local_path`, override it at runtime
instead of editing the instance file:

```bash
python tools/pilot.py \
  --instance otel-demo__py__recommendation__ListRecommendations \
  --prompts p_blind \
  --model gpt-4.1 \
  --backend agent \
  --repo-path-override open-telemetry/opentelemetry-demo=/path/to/opentelemetry-demo
```

For larger batches, repeat `--repo-path-override KEY=/abs/path` or add
`--repo-search-root /path/to/repos`. `KEY` may be the repo name, the old
`repo.local_path`, a basename, or an `owner__repo` form.

Run a repo-visible agent cell while blocking direct reads of the target file and
persisting the full Copilot SDK trace:

```bash
python tools/pilot.py \
  --instance otel-demo__py__recommendation__ListRecommendations \
  --prompts p_blind \
  --model gpt-4.1 \
  --backend agent \
  --allow-agent-tools \
  --agent-repo-context related \
  --agent-trace \
  --run-id my-agent-trace-run
```

In this mode the source repo is still exposed as the Copilot workspace, but the
current instance's target file (`target.file` resolved under that instance's
repo root) is added to the permission deny list. The preflight turn asks the
agent to inspect other related files in that same instance repo for conventions
relevant to the task, helper APIs, and similar non-target implementations. Each
cell writes `agent_trace.json` beside `result.json`; inspect `tool.execution_*`
and `permission.*` events to verify whether the agent actually used repo tools
and which paths were touched.

Aggregate a run:

```bash
python tools/aggregate_repo_lang.py <run-id>
```

Re-score an existing run without new model calls:

```bash
python -m tools.rescore --run-id <run-id>
python tools/aggregate_repo_lang.py <run-id>
```

---

## Reproducibility Notes

This public copy omits generated runs and source checkouts. Prepare local source
repositories and configure runtime paths before reproducing experiments:

| Resource | Current assumption |
|---|---|
| API backend helper | Set `OBS_CLOUDGPT_HELPER` to a CloudGPT-compatible helper script if using `--backend api` |
| Python environment | Create a local virtual environment such as `.venv` |
| Source repositories | Paths stored in each instance JSON under `repo.local_path`, or supplied with `--repo-path-override` |
| Source snapshot | Record the exact source commit used for each reproduction run |

Before publishing or sharing a new result, record:

- run id
- backend
- model id
- prompt list
- prompt file hashes
- instance set or manifest
- number of rendered siblings per few-shot cell
- source repository snapshot
- scoring code version

The current `--all` behavior is convenient for exploration but depends on the
contents of `instances/function/` at run time. For paper-grade reproduction,
prefer a fixed manifest or explicitly documented instance list.

---



## Recommended Next Cleanups

1. Add fixed manifests for the expanded benchmark and any smaller comparison sets.
2. Add `--manifest` or `--corpus` support to `tools.pilot`.
3. Record rendered sibling count in each `result.json` and summary row.
4. Normalize source repository commit metadata across all instances.
5. Move local absolute paths behind environment variables.
6. Add a short publication checklist before pushing new runs to GitHub.

---

## Short Summary

`obs-real-bench` is an OSS-only public observability-restoration benchmark in
this copy. Always state the corpus scope, prompt set, backend, model, and run id
before comparing prompt or backend performance.

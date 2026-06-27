# obs-real-bench

`obs-real-bench` is a benchmark for evaluating whether code models and coding
agents can restore observability instrumentation that has been removed from
real functions.

Each instance points to one target function in a source repository. The runner
loads the original function, removes logging, tracing, and metrics calls, asks a
model or coding agent to add observability back, and scores the generated
function against the original observability behavior.

## Public Release Scope

The full research corpus contains both open-source and industrial instances:

```text
open-source instances: 441
industrial instances:  782
```

Due to company policy, the industrial instances cannot be released. This public
repository contains only the open-source portion of the benchmark. Industrial
source-code references, internal instance files, generated runs, logs, and
experiment outputs are intentionally excluded.

No paper result tables are bundled in this repository. The code here is for
reproducing runs on the public open-source instances and for inspecting the
benchmark pipeline.

## Task Definition

For each benchmark instance, the pipeline:

1. Reads the source repository configured by `repo.local_path` or a runtime
   override.
2. Locates the target function described by the instance JSON.
3. Strips observability statements from the target function.
4. Renders a prompt from `prompts/`.
5. Calls the selected backend.
6. Extracts the generated target function from the model response.
7. Extracts observability sites from both the original and generated function.
8. Computes placement and key-recovery scores.
9. Writes local outputs under `results/<run-id>/`.

The benchmark does not score whole-file text similarity. It evaluates whether
the generated function restores observability in the right control-flow slots
and recovers the expected observability keys or keyword concepts.

## Prompt Levels

The public runner includes three prompt levels:

| Prompt | Description |
|---|---|
| `p_blind` | Control prompt with the stripped target function and context, without explicitly asking for observability. |
| `p1_obs_hinted` | Observability-restoration prompt that tells the model the function is missing instrumentation. |
| `p_fewshot` | Same task as `p1_obs_hinted`, plus same-file sibling examples when available. |
| `p_skill_vibe_transfer` | Skill-transfer prompt that uses observability guidance derived from the vibe-coding benchmark. |

Prompt templates are stored in `prompts/`.

## Metrics

The main scoring code lives in `tools/score_anchor.py` and
`tools/score_anchor_ts.py`.

Commonly reported metrics include:

| Metric | Meaning |
|---|---|
| Position F1 | Whether restored observability appears in the correct anchor slot. |
| Key Bag F1 | Whether restored observability keys or keyword concepts match the ground truth. |

For paper-style aggregation, use the same corpus scope, prompt set, backend,
model, and filtering policy across all compared systems.

## Directory Layout

| Path | Purpose |
|---|---|
| `instances/function/` | Public open-source function-level benchmark instances. |
| `prompts/` | Prompt templates. |
| `tools/pilot.py` | End-to-end runner. |
| `tools/prompt_render.py` | Prompt rendering utilities. |
| `tools/strip/` | Language-specific observability stripping. |
| `tools/extract/` | Language-specific observability-site extraction. |
| `tools/langspec.py` | Language and observability API registry. |
| `tools/aggregate_repo_lang.py` | Aggregates local run summaries. |
| `run_all_agent.sh` | Convenience wrapper for agent-backend runs. |

Generated `results/`, `runs/`, logs, traces, and model outputs are not included
in this public copy.

## Setup

Create a local Python environment:

```bash
cd obs-real-bench-public
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

Install any parser or backend dependencies required by the tools you plan to
run. The repository intentionally does not bundle source checkouts for the
upstream open-source projects. Clone the needed source repositories locally and
either update `repo.local_path` in a private copy of the instance files or pass
runtime overrides.

## Running One Instance

```bash
python -m tools.pilot \
  --instance otel-demo__py__recommendation__ListRecommendations-v1 \
  --prompt p_fewshot \
  --model <model-id> \
  --backend api \
  --run-id scratch-one \
  --repo-path-override open-telemetry/opentelemetry-demo=/path/to/opentelemetry-demo
```

Use `--backend agent` for an agent-runtime experiment:

```bash
python -m tools.pilot \
  --instance otel-demo__py__recommendation__ListRecommendations-v1 \
  --prompt p1_obs_hinted \
  --model <model-id> \
  --backend agent \
  --run-id scratch-agent \
  --repo-path-override open-telemetry/opentelemetry-demo=/path/to/opentelemetry-demo
```

## Running A Batch

Run all runnable public open-source instances:

```bash
python -m tools.pilot \
  --all \
  --prompts p_blind,p1_obs_hinted,p_fewshot \
  --model <model-id> \
  --backend api \
  --run-id my-public-run \
  --workers 16 \
  --skip-existing \
  --repo-search-root /path/to/source-repos
```

The agent wrapper provides the same kind of batch workflow for the agent
backend:

```bash
./run_all_agent.sh \
  --run-id my-agent-run \
  --model <model-id> \
  --prompts p_blind,p1_obs_hinted,p_fewshot \
  --workers 16 \
  --repo-search-root /path/to/source-repos
```

Example full agent run with sanitized source-repository copies:

```bash
python -m tools.pilot \
  --all \
  --prompts p_blind,p1_obs_hinted,p_fewshot,p_skill_vibe_transfer \
  --model gemini-3.1-pro \
  --backend agent \
  --agentic \
  --allow-agent-tools \
  --agent-workspace-mode sanitized-copy \
  --agent-sanitized-copy-root /tmp/obs-real-bench-sanitized \
  --skip-zero-gt \
  --agent-trace \
  --run-id agent-sanitized-copy-gemini3.1 \
  --workers 32 \
  --skip-existing
```

The sanitized-copy root is a local scratch directory used during agent runs. It
can be any writable temporary path outside the repository.

## Aggregating Local Results

After a run finishes, aggregate the local output:

```bash
python tools/aggregate_repo_lang.py <run-id>
```

To recompute scores for an existing local run:

```bash
python -m tools.rescore --run-id <run-id>
python tools/aggregate_repo_lang.py <run-id>
```

## Reproducibility Notes

When reporting new results, record the public instance set, source repository
commits, prompt files, backend, model id, run id, and scorer version. Generated
results should be kept outside the public source tree unless they have been
reviewed for release.

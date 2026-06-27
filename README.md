# Observability Benchmarks

This repository contains public releases for two observability benchmark
artifacts:

| Directory | Description |
|---|---|
| `obs-real-bench-public/` | Function-level observability-restoration benchmark for real open-source code. |
| `vibe_coding_public/` | Kubernetes-based benchmark environment for generated microservices and fault-injection observability. |

The repository intentionally excludes industrial benchmark instances, internal
source-code references, generated runs, logs, traces, and model outputs.

## obs-real-bench-public

`obs-real-bench` evaluates whether code models and coding agents can restore
logging, tracing, and metrics instrumentation that has been removed from target
functions.

The full research corpus contains 441 open-source instances and 782 industrial
instances. Due to company policy, only the open-source instances can be released
publicly.

Start here: [obs-real-bench-public/README.md](obs-real-bench-public/README.md)

## vibe_coding_public

`vibe_coding` provides generated microservices, Kubernetes manifests, fault
injection templates, and a log-window judge for local observability experiments.

This public copy includes source and configuration needed to run local
experiments, but not generated result directories.

Start here: [vibe_coding_public/README.md](vibe_coding_public/README.md)

## Reproducing Runs

Each subproject README contains setup and command examples. In general:

1. Clone any required upstream source repositories locally.
2. Create a Python environment for the subproject.
3. Configure model or agent credentials outside the repository.
4. Run the provided commands with local scratch/output paths.
5. Review generated outputs before sharing them.

Do not commit local result directories, logs, traces, API keys, personal paths,
or private source-code references.

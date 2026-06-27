# vibe_coding

`vibe_coding` is a local benchmark environment for running generated
microservices under Kubernetes and checking whether their logs expose useful
signals during fault injection.

The repository contains service implementations, Kubernetes manifests, fault
templates, and a log-window judge. It is designed for local experiments with a
kind cluster and Chaos Mesh.

## Public Release Scope

This public copy includes the runnable benchmark code and service definitions.
Generated experiment outputs are intentionally excluded: no `runs/`, `results/`,
logs, traces, or model output directories are bundled.

The README does not include result tables. Run the benchmark locally to generate
fresh outputs for your own environment.

## What Is Included

The benchmark contains generated microservice directories under `services/`.
Each service directory is expected to include:

- source code
- `Dockerfile`
- `k8s/deployment.yaml`
- rendered fault manifests under `faults/`
- `run.sh`
- `exercise.sh`
- `SPEC.md`

The framework provides:

| Path | Purpose |
|---|---|
| `Makefile` | Top-level local workflow. |
| `infra/` | kind cluster setup, Chaos Mesh installation, and shared dependencies. |
| `faults/` | Fault primitive documentation and templates. |
| `_lib/fault-templates/` | Additional reusable fault templates. |
| `judge/` | Log-window detection logic and oracle patterns. |
| `services/` | Service implementations and per-service run scripts. |
| `tools/` | Helper scripts for generation and local workflows. |

## Requirements

Install these tools before running the benchmark:

- Docker
- kind
- kubectl
- helm
- make
- Python 3.10 or newer

The local cluster and service builds can use substantial CPU, memory, and disk
space. Start with a single service before running the full suite.

## Quick Start

```bash
cd vibe_coding_public

# Create the local cluster, install Chaos Mesh, and deploy shared dependencies.
make up

# Build, deploy, exercise, inject faults, and judge one service.
make demo SVC=01-catalog-api

# Tear down the local cluster when finished.
make down
```

## Running Individual Steps

```bash
cd vibe_coding_public

make build SVC=01-catalog-api
make deploy SVC=01-catalog-api
make inject SVC=01-catalog-api FAULT=F01-pod-kill
make judge SVC=01-catalog-api
```

Most services also support direct script usage:

```bash
cd services/01-catalog-api
./run.sh build
./run.sh deploy
./run.sh wait
./run.sh smoke
./run.sh inject F01-pod-kill
./run.sh judge
./run.sh cleanup
```

## Running Multiple Services

The repository includes serial and parallel helpers:

```bash
./run_all_demos.sh
./run_parallel_demos.sh
```

For a full local run through the Makefile:

```bash
make all
```

Large runs create local output directories such as `runs/`. These directories
are intentionally ignored by git and should be reviewed before sharing.

## Faults And Judging

Fault primitives are documented in `faults/README.md`. During a fault window,
the framework drives traffic through each service with `exercise.sh`, collects
pod logs, and applies the detection rules in `judge/oracle.yaml`.

The judge marks a fault as detected when a configured pattern appears in the
log window. Pod-kill faults can also be detected through Kubernetes restart
counts.

## Service Documentation

Each service has a `SPEC.md` with its endpoints, dependencies, run commands,
fault commands, and expected detection behavior. For example:

```bash
less services/01-catalog-api/SPEC.md
```

Use the per-service `SPEC.md` files as the source of truth for service-specific
details.

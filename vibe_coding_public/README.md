# vibe_coding — observability of vibe-coded microservices

Agent handoff / operational notes: see [`AGENT_README.md`](AGENT_README.md).

187 core microservices, plus 13 later extension services, for local
observability and fault-injection experiments. The current checkout contains
200 runnable service directories under `services/`: IDs `01` through `187` are
the core benchmark set, and IDs `188` through `200` are extension cases.

Each service is deployable to a local kind cluster, has a chaos-mesh
fault-injection set, and is judged by analyzing pod-log windows around each
injection.

This repo is **self-contained**: it brings its own kind cluster, chaos-mesh,
log collector, and judge. Nothing is shared with `obs-real-bench/`.

## At a glance

Current service inventory:

```text
core service set:      187 services, IDs 01-187
extension services:     13 services, IDs 188-200
service directories:   200 total under services/
service marker files:  every service has SPEC.md, run.sh, Dockerfile, and k8s/deployment.yaml
fault YAMLs:           1,615 rendered fault manifests, 2-11 per service
evaluated fault types: 13 primitives, F01-F13
```

The service set spans several implementation stacks, including Python, Go,
Java, C#, C++, JavaScript/TypeScript, Rust, Ruby, PHP, and additional lightweight
framework stacks documented in each `SPEC.md`.

Representative boundary examples:

| Range | Examples |
|---|---|
| Core start | `01-catalog-api`, `02-cart-service`, `03-order-api` |
| Core end | `185-mqtt-bridge`, `186-notification-router`, `187-file-metadata` |
| Extensions | `188-heartbeat-monitor`, `189-pubsub-broker`, ..., `200-event-enricher` |

Use `make list` to print the current service list from the filesystem.

Fault primitives are documented in [`faults/README.md`](faults/README.md). The
result of record below evaluates 13 fault types, F01-F13.
Detection model is documented in [`judge/README.md`](judge/README.md).

## Result of Record

The current multifault result is stored under
`runs/chaos_multifault_20260526T161758Z_multifault_p48_postfix_v2/`. The
human-readable Markdown summary is
`runs/chaos_multifault_20260526T161758Z_multifault_p48_postfix_v2/fault-specific-by-fault.md`.

Campaign summary:

```text
campaign:              20260526T161758Z_multifault_p48_postfix_v2
generated:             2026-05-27 06:55:06 UTC
services targeted:     187
services with summary: 187
fault instances total: 1507
fault instances caught: 312 (20.70%)
fault instances no_signal: 1195 (79.30%)
```

Scoring modes supported by the judge:

| Mode | Meaning |
|---|---|
| `current` | Generic matchers plus per-fault matchers. |
| `strict` | Drops synthetic `[access]` lines and excludes the generic HTTP 5xx matcher. |
| `fault-specific` | Strongest anti-inflation mode: drops synthetic `[access]` lines and uses only per-fault matchers. |

The Markdown table below is the fault-specific by-fault result for the campaign.

By-fault detection results from that run:

| Fault | Samples | Caught | Detection Rate | No Signal | No Signal Ratio | Matcher | Pod Restart | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F01-pod-kill | 187 | 111 | 59.36% | 76 | 40.64% | 111 | 0 | 0 |
| F02-network-delay | 187 | 63 | 33.69% | 124 | 66.31% | 63 | 0 | 0 |
| F03-upstream-fail | 15 | 11 | 73.33% | 4 | 26.67% | 11 | 0 | 0 |
| F04-upstream-slow | 15 | 3 | 20.00% | 12 | 80.00% | 3 | 0 | 0 |
| F05-db-down | 128 | 12 | 9.38% | 116 | 90.62% | 12 | 0 | 0 |
| F06-db-slow | 128 | 6 | 4.69% | 122 | 95.31% | 6 | 0 | 0 |
| F07-cache-down | 100 | 39 | 39.00% | 61 | 61.00% | 39 | 0 | 0 |
| F08-cache-slow | 100 | 28 | 28.00% | 72 | 72.00% | 28 | 0 | 0 |
| F09-queue-down | 61 | 7 | 11.48% | 54 | 88.52% | 7 | 0 | 0 |
| F10-queue-slow | 61 | 4 | 6.56% | 57 | 93.44% | 4 | 0 | 0 |
| F11-cpu-stress | 175 | 11 | 6.29% | 164 | 93.71% | 11 | 0 | 0 |
| F12-net-corrupt | 175 | 17 | 9.71% | 158 | 90.29% | 17 | 0 | 0 |
| F13-time-skew | 175 | 0 | 0.00% | 175 | 100.00% | 0 | 0 | 0 |

This campaign covers 13 fault types, F01-F13.

## Quick start

Prereqs on your machine: `docker`, `kind` (>=0.20), `kubectl`, `helm`,
`make`, `python3` (>=3.10), and ~8 GB free RAM.

```bash
cd vibe_coding

# One-time: bring up cluster + chaos-mesh + shared deps (postgres/redis/...)
make up

# Build + deploy a single service end-to-end, then run all its faults
make demo SVC=01-catalog-api

# Or just one piece at a time
make build SVC=01-catalog-api      # docker build + kind load
make deploy SVC=01-catalog-api     # kubectl apply
make inject SVC=01-catalog-api FAULT=F01-pod-kill
make judge SVC=01-catalog-api

# Run every service end-to-end (slow; serializes per service)
make all

# Tear down
make down
```

## Layout

```
vibe_coding/
├── README.md
├── Makefile                            top-level orchestrator
├── infra/
│   ├── kind-cluster.yaml               kind config (cluster: vibe)
│   ├── install/
│   │   ├── up.sh                       create cluster + install chaos-mesh + apply deps
│   │   └── down.sh                     delete cluster
│   └── deps/
│       ├── namespace.yaml              vibe-coding ns
│       ├── postgres.yaml               one shared Postgres (app=postgres)
│       ├── redis-cache.yaml            one shared Redis cache (app=redis-cache)
│       ├── redis-stream.yaml           one shared Redis stream broker (app=redis-stream)
│       └── mock-upstream.yaml          one shared echo-style upstream (app=mock-upstream)
├── faults/
│   ├── README.md                       fault primitive defs + chaos-mesh gotchas
│   └── templates/                      base F01-F10 *.tpl.yaml templates
├── _lib/
│   └── fault-templates/                extension F11-F15 templates
├── judge/
│   ├── README.md                       detection model
│   ├── judge.py                        log-window analyzer
│   └── oracle.yaml                     per-fault regex patterns (canonical)
├── services/
│   ├── 01-catalog-api/                 core service
│   ├── ...
│   ├── 187-file-metadata/              final core service
│   ├── 188-heartbeat-monitor/          extension service
│   ├── ...
│   └── 200-event-enricher/             extension service
└── runs/                               (created at runtime) one dir per `make demo`
```

Each `services/<id>/` contains:

- `src/` (Python, Go) or root-level (Java/C#/C++) — source code
- `Dockerfile`
- `k8s/deployment.yaml` — Deployment + Service in ns `vibe-coding`
- `faults/F*.yaml` — rendered chaos CRDs (selectors filled in)
- `run.sh` — `build | deploy | wait | smoke | inject FAULT | judge | cleanup | demo`
- `exercise.sh` — per-service traffic generator. Defines `exercise_once <BASE_URL>`. The framework runs this in a tight 1 Hz loop during the fault window so the service exercises its deps and emits log signal the judge can score.
- `SPEC.md` — Chinese-language project spec for this service (endpoints, deps, all run/inject/judge commands)

## Detection model (short version)

Each fault `inject` records `t_start` and `t_end`. During the window, the
framework also runs a per-service traffic generator (`exercise.sh::exercise_once`)
through a kubectl port-forward, exercising the dep being faulted. The judge
then runs `kubectl logs --since-time=t_start` on the service pod(s),
filters to lines with timestamps in `[t_start, t_end + buffer]`, and applies
the per-fault regex set from `judge/oracle.yaml`. A fault is **caught** if
at least one regex hits inside the window. F01 (pod-kill) is additionally
caught when the pod's `restartCount` advances from the baseline.

Full detail in [`judge/README.md`](judge/README.md).

## Status

- 187 core service implementations ✅
- 13 extension service implementations ✅
- 200 total service directories with `SPEC.md`, `run.sh`, `Dockerfile`, and Kubernetes manifests ✅
- 13 evaluated fault primitives in the result of record ✅
- Cluster + chaos-mesh + shared deps ✅
- Per-service `SPEC.md` with run / inject / detect commands ✅ — see `services/<id>/SPEC.md`
- Multifault result of record: 187 services, 1507 fault instances, 312 caught (20.70%) ✅
- Parallel and serial demo runners available via `run_parallel_demos.sh`, `run_all_demos.sh`, and `make all` ✅

For per-service usage details (Chinese), open the matching SPEC, e.g.
[`services/01-catalog-api/SPEC.md`](services/01-catalog-api/SPEC.md).

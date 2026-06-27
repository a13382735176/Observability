# Dataset Source Seed Material

This note summarizes the `vibe_coding_no_runs_20260615_105738` benchmark as seed material for a paper dataset/source description.

## Dataset Overview

The dataset is a self-contained synthetic microservice observability benchmark. It contains 200 runnable microservice directories under `services/`:

| Split | Service IDs | Count |
|---|---:|---:|
| Core service set | `01`-`187` | 187 |
| Extension service set | `188`-`200` | 13 |
| Total | `01`-`200` | 200 |

Each service includes a natural-language specification, source implementation, Docker build definition, Kubernetes deployment, traffic exerciser, and rendered Chaos Mesh fault manifests.

Typical per-service files are:

- `SPEC.md`: service behavior, endpoints, dependencies, and run/inject/judge commands.
- `Dockerfile`: container build contract.
- `k8s/deployment.yaml`: Kubernetes Deployment and Service in the `vibe-coding` namespace.
- `run.sh`: service-local harness entrypoint for build, deploy, wait, smoke, inject, judge, cleanup, and demo.
- `exercise.sh`: per-service traffic generator used during fault windows.
- `faults/F*.yaml`: rendered Chaos Mesh fault manifests with service-specific selectors.

The benchmark runs locally on a kind Kubernetes cluster with Chaos Mesh. During each fault injection window, the harness drives service traffic through `exercise.sh`, captures pod logs, and evaluates whether application-level logs contain evidence of the injected fault.

## Service Domains

The 200 services cover common cloud microservice domains rather than a single application. The naming and specifications span the following categories:

| Category | Representative Services |
|---|---|
| E-commerce, order, inventory, and payment | `catalog-api`, `cart-service`, `order-api`, `payment-gateway`, `inventory-tracker`, `checkout-service`, `shipping-calculator`, `returns-processor`, `tax-calculator`, `promo-engine`, `order-history` |
| Social and user interaction | `post-service`, `comment-service`, `like-counter`, `follow-graph`, `feed-generator`, `story-service`, `mention-service`, `hashtag-index`, `dm-service`, `poll-service` |
| IoT, devices, and telemetry | `device-registry`, `telemetry-ingest`, `firmware-updater`, `sensor-aggregator`, `edge-proxy`, `provisioning-svc`, `iot-telemetry`, `mqtt-bridge`, `notification-router` |
| Finance, payment, and accounting | `account-service`, `transaction-log`, `balance-cache`, `payment-processor`, `kyc-verifier`, `fx-rate-service`, `ledger-service`, `credit-score`, `loan-originator`, `transfer-service` |
| Healthcare | `appointment-svc`, `patient-record`, `prescription-svc`, `lab-results`, `vitals-monitor`, `medication-remind`, `doctor-schedule`, `insurance-check`, `symptom-checker`, `telemedicine-svc` |
| Content, media, and CMS | `article-service`, `video-metadata`, `image-catalog`, `tag-service`, `content-search`, `reading-list`, `embed-service`, `cdn-manifest`, `translation-svc`, `media-convert-job` |
| SaaS platform, security, and operations | `feature-flag-svc`, `secret-rotation`, `tenant-manager`, `audit-log-svc`, `access-proxy`, `quota-enforcer`, `circuit-breaker`, `cert-renewal-svc`, `api-key-vault`, `policy-engine` |
| Travel, ticketing, and reservation | `flight-search`, `hotel-booking`, `car-rental`, `itinerary-planner`, `price-tracker`, `weather-fetcher`, `currency-converter`, `visa-application`, `event-ticketing`, `reservation-svc` |
| Logistics, customer support, and operations | `warehouse-routing`, `invoice-generator`, `chargeback-svc`, `warranty-claims`, `support-ticket`, `knowledge-base-svc`, `feedback-collector`, `incident-tracker`, `status-page` |
| Gaming and real-time collaboration | `leaderboard-svc`, `match-maker`, `achievement-svc`, `tournament-bracket`, `chat-room`, `presence-tracker` |
| Observability, DevOps, and analytics | `log-aggregator`, `metric-ingest`, `trace-collector`, `alert-manager`, `dns-resolver-svc`, `backup-orchestrator`, `deployment-tracker`, `job-scheduler`, `anomaly-detector`, `usage-analytics`, `funnel-analyzer` |
| Extension infrastructure services | `heartbeat-monitor`, `pubsub-broker`, `signal-relay`, `media-encoder-svc`, `thumbnail-generator`, `oauth-token-svc`, `session-manager`, `mfa-svc`, `event-enricher` |

## Implementation Stacks

For this checkout, a rough build-file-based language count over the 200 baseline services is:

| Stack | Service Count | Example Services |
|---|---:|---|
| Python | 180 | `01-catalog-api`, `02-cart-service`, `05-inventory-tracker`, `07-session-cache`, `08-notification-dispatcher` |
| C# | 7 | `04-payment-gateway`, `15-webhook-fanout`, `135-loyalty-mileage`, `143-invoice-generator`, `156-presence-tracker` |
| Rust | 7 | `132-review-aggregator`, `142-warehouse-routing`, `151-leaderboard-svc`, `159-log-aggregator`, `171-feature-store` |
| Java | 5 | `03-order-api`, `06-user-profile`, `09-order-processor`, `13-auth-token-svc`, `134-visa-application` |
| C++ | 1 | `11-image-resizer` |

The project README describes the broader service set as spanning Python, Go, Java, C#, C++, JavaScript/TypeScript, Rust, Ruby, PHP, and other lightweight frameworks. For this specific experimental checkout, the actual baseline service directories are dominated by Python with smaller numbers of C#, Rust, Java, and C++ services.

## Evaluated Fault Types

The evaluated fault set contains 13 Chaos Mesh fault primitives, `F01`-`F13`. The repository also contains documentation/templates for additional faults such as `F14-mem-stress` and `F15-dns-fail`, but those are not part of the 13-fault result-of-record described here.

| ID | Fault | Chaos Kind | Target | What It Tests |
|---|---|---|---|---|
| F01 | `pod-kill` | PodChaos | Service pod | Whether restart or service unavailability is visible in logs. |
| F02 | `network-delay` | NetworkChaos | Service network interface | Whether latency and request timeout are surfaced. |
| F03 | `upstream-fail` | HTTPChaos | `mock-upstream` pod | Whether upstream 503/5xx failures are logged. |
| F04 | `upstream-slow` | NetworkChaos | `mock-upstream` pod | Whether slow upstream responses or upstream timeouts are logged. |
| F05 | `db-down` | PodChaos | Postgres pod | Whether database disconnects or connection failures are logged. |
| F06 | `db-slow` | NetworkChaos | Postgres pod | Whether slow queries, DB timeouts, or pool checkout delays are logged. |
| F07 | `cache-down` | PodChaos | Redis cache pod | Whether cache connection failures are logged. |
| F08 | `cache-slow` | NetworkChaos | Redis cache pod | Whether cache latency or cache operation timeouts are logged. |
| F09 | `queue-down` | PodChaos | Redis stream pod | Whether queue/stream disconnects are logged. |
| F10 | `queue-slow` | NetworkChaos | Redis stream pod | Whether queue read/write latency or delivery timeouts are logged. |
| F11 | `cpu-stress` | StressChaos | Service pod | Whether CPU saturation, latency spikes, or timeout cascades are logged. |
| F12 | `net-corrupt` | NetworkChaos | Service network interface | Whether packet corruption, protocol errors, parse errors, or reset connections are logged. |
| F13 | `time-skew` | TimeChaos | Service pod | Whether clock skew effects such as token expiry, TTL mismatch, invalid timestamps, or rate-window anomalies are logged. |

## Fault Coverage Across Services

The 200 service directories contain 1,615 rendered fault manifests. Coverage varies because not every service uses every dependency type.

| Fault | Rendered Service Count |
|---|---:|
| F01-pod-kill | 200 |
| F02-network-delay | 200 |
| F03-upstream-fail | 17 |
| F04-upstream-slow | 17 |
| F05-db-down | 140 |
| F06-db-slow | 140 |
| F07-cache-down | 107 |
| F08-cache-slow | 107 |
| F09-queue-down | 66 |
| F10-queue-slow | 66 |
| F11-cpu-stress | 185 |
| F12-net-corrupt | 185 |
| F13-time-skew | 185 |

## Judging Model

The benchmark uses a log-window judge. For each injected fault, the harness records `t_start` and `t_end`, drives traffic during the fault window, captures pod logs, filters framework/library noise, and applies fault-specific regular expressions from `judge/oracle.yaml`.

A fault is marked caught if application-level log evidence matches the relevant oracle pattern inside the window. For `F01-pod-kill`, restart/startup evidence can also count as detection. The strictest scoring mode is `fault-specific`, which drops synthetic access lines and uses only per-fault matchers.

## Expanded Experiment Table Candidates

The compact result table can be expanded by showing the experimental scale behind each model run. In particular, every model targets the same 200-service benchmark and the same 1,615 intended service-fault instances, while the `offline` subset counts only services that produced runnable summaries.

Recommended larger no-skill baseline table:

| Model | Service Generation Targets | Runnable Services | Runnable Rate | Fault Types | Intended Fault Instances | Offline Fault Windows | Fault-Specific Caught | Full-Intent FSR | Subset FSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT 5.5 | 200 | 151 / 200 | 75.5% | 13 | 1,615 | 1,220 | 80 | 4.95% | 6.56% |
| Claude Opus 4.5 | 200 | 154 / 200 | 77.0% | 13 | 1,615 | 1,232 | 102 | 6.32% | 8.28% |
| Gemini 3.5 Flash | 200 | 136 / 200 | 68.0% | 13 | 1,615 | 1,096 | 226 | 13.99% | 20.62% |
| **Total / mean** | **600** | **441 / 600** | **73.5%** | **13** | **4,845** | **3,548** | **408** | **8.42%** | **11.50%** |

If the paper also reports the observability-skill ablation, use a second table to show that the result is based on six full 200-service campaigns rather than a single small run:

| Model | Condition | Target Services | Runnable Services | Intended Fault Instances | Offline Fault Windows | Fault-Specific Caught | Full-Intent FSR | Subset FSR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| GPT 5.5 | No skill | 200 | 151 | 1,615 | 1,220 | 80 | 4.95% | 6.56% |
| GPT 5.5 | With skill | 200 | 169 | 1,615 | 1,371 | 220 | 13.62% | 16.05% |
| Claude Opus 4.5 | No skill | 200 | 154 | 1,615 | 1,232 | 102 | 6.32% | 8.28% |
| Claude Opus 4.5 | With skill | 200 | 126 | 1,615 | 1,013 | 118 | 7.31% | 11.65% |
| Gemini 3.5 Flash | No skill | 200 | 136 | 1,615 | 1,096 | 226 | 13.99% | 20.62% |
| Gemini 3.5 Flash | With skill | 200 | 121 | 1,615 | 967 | 267 | 16.53% | 27.61% |
| **Total** | **All campaigns** | **1,200** | **857** | **9,690** | **6,899** | **1,013** | **10.45%** | **14.68%** |

Suggested caption language:

> Experimental scale and fault-specific detection results. Each model is evaluated on a 200-service synthetic microservice benchmark with 13 Chaos Mesh fault primitives and 1,615 intended service-fault instances. `Full-intent FSR` treats missing or non-runnable service summaries as no-signal outcomes, while `Subset FSR` is computed only over services that produced runnable summaries.

For a narrower paper layout, keep the larger no-skill table and move the skill-ablation table to an appendix. The key point is to expose `Service Generation Targets`, `Intended Fault Instances`, and `Offline Fault Windows`, since those columns communicate the experimental workload without changing the scoring definition.

## Suggested Paper Wording

> We construct a synthetic microservice observability benchmark consisting of 200 runnable services. The services cover common cloud application domains such as e-commerce, social applications, IoT telemetry, finance, healthcare, content management, SaaS platform infrastructure, travel, logistics, gaming, and DevOps/observability pipelines. Each service includes a natural-language specification, source implementation, Docker build, Kubernetes deployment, per-service traffic exerciser, and rendered Chaos Mesh fault manifests. We evaluate 13 fault primitives spanning pod failures, network latency, upstream failures, database/cache/queue outages and slowdowns, CPU pressure, packet corruption, and clock skew. Fault detection is judged from application log windows around each injection.

## Caveats for Paper Framing

- Describe the benchmark as synthetic/generated rather than production or industrial data.
- State that service domains are representative cloud microservice scenarios, not traces from a deployed production system.
- Use the actual 13 evaluated faults, `F01`-`F13`; do not include `F14`/`F15` unless discussing unused templates.
- If reporting implementation stacks for this checkout, use the build-file-based counts above rather than the broader README language list.
- Fault coverage differs by service dependency structure; dependency-specific faults such as DB/cache/queue/upstream faults do not apply to all 200 services.
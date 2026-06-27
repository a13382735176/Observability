# Detection model

Each fault injection writes a `meta.json` capturing `[t_start, t_end]`.
After the fault is over, `judge.py` calls `kubectl logs --since-time=t_start`
on the target service's pods, filters to lines in the window, and applies
per-fault regex patterns from `oracle.yaml`. A fault is **caught** if at
least one matcher hits in the window OR (for `F01-pod-kill`) the pod's
`restartCount` increased OR a new pod with the same label came up inside
the window.

## Why log-only

Because per user spec ("故障注射后的logs窗口中中去反应"): the only signal
we evaluate is what shows up in the pod's logs in the time window
surrounding the fault. No metrics, no traces, no events. This is a strict
baseline that purposely matches what a human operator with only
`kubectl logs` would see.

## Files

```
judge/
├── README.md            this file
├── judge.py             the analyzer (stdlib + PyYAML)
└── oracle.yaml          per-fault regex catalog (generic + fault-specific)
```

## meta.json schema

Each `runs/<timestamp>/<fault-id>/meta.json`:

```json
{
  "service":     "01-catalog-api",
  "fault_id":    "F01-pod-kill",
  "fault_yaml":  "/abs/path/to/faults/F01-pod-kill.yaml",
  "namespace":   "vibe-coding",
  "app_label":   "catalog-api",
  "t_start":     "2026-05-24T12:00:00Z",
  "t_end":       "2026-05-24T12:01:30Z",
  "duration_s":  90,
  "buffer_s":    30
}
```

`t_start` is captured immediately before `kubectl apply -f fault.yaml`.
`t_end = t_start + duration_s + buffer_s`. The judge sleeps until `t_end`
before sampling, so logs are guaranteed to be flushed by `kubectl logs`.

## Verdict format

`runs/<timestamp>/<fault-id>/verdict.json`:

```json
{
  "service": "01-catalog-api",
  "fault_id": "F01-pod-kill",
  "caught": true,
  "matchers": [
    {"name": "generic-error",  "hits": 0, "samples": []},
    {"name": "f01-pod-restart", "hits": 1, "samples": ["restartCount went 0 -> 1"]},
    {"name": "f01-startup",     "hits": 2, "samples": ["INFO Started Application in 3.1 seconds"]}
  ],
  "n_log_lines_in_window": 47,
  "pod_restart_counts": {"catalog-api-7b8...-xj9k": 1}
}
```

## Generic vs fault-specific matchers

`oracle.yaml::generic`: applied to every fault. Catches the most common
language-agnostic signals:

- `(?i)\b(error|exception|timeout|timed[- ]out|refused|reset by peer|panic|fatal|unhealthy)\b`
- `(?i)\b(50[0-9]|connection (refused|reset|timed))\b`
- `(?i)\b(unable to|cannot connect|connect failed|dial tcp.*: i/o timeout)\b`

`oracle.yaml::faults.<fault-id>`: applied only when judging that fault.
Examples:

- `F05-db-down`:    `(?i)(postgres|5432|psql|pq:|FATAL: connection)`
- `F07-cache-down`: `(?i)(redis|6379|MOVED|LOADING|connection reset)`
- `F01-pod-kill`:   plus the special pod-restart check

## Caveats

- **F02 / F04 / F06 / F08 / F10 (slow variants)**: a service can be
  affected by added latency without logging anything (it just gets slower).
  This is detected by the generic `(?i)timeout` matcher *only if* the
  service has a timeout shorter than the injected delay (500 ms here).
  Several of our reference services do set a 250 ms client timeout for
  exactly this reason. Real LLM-generated code may not — those services
  will MISS the slow variants under the strict oracle, which is the point.
- **F01-pod-kill**: the pod-restart heuristic is robust against services
  that emit zero logs on death/restart; without it, killed-and-restarted
  services that boot silently would all miss F01.
- **`kubectl logs --since-time` precision is seconds**: a fault shorter
  than 1 s may misalign the window by ~1 s. All faults here are ≥30 s, so
  this is not an issue.

## Running one saved fault

```bash
# Judge one fault directory from saved run artifacts
python3 judge/judge.py \
  runs/04-payment-gateway-skill/with_skill_gpt55_capture_retry_20260612T140707Z/F01-pod-kill \
  --mode fault-specific \
  --offline
```

The important input path is:

```text
runs/<service>/<RUN_TS>/<fault>/
```

Do not judge from batch orchestration logs such as:

```text
runs/_skill_<RUN_TS>/*.log
```

Those `_skill_` files only record build/deploy/capture progress. The judge
input is each fault directory's `meta.json` plus saved logs such as
`logs_snapshot.txt`.

`--offline` uses saved run artifacts only. Prefer it for completed campaigns
because it avoids querying the live Kubernetes cluster and mixing old runs with
current pod state.

## Running one saved service run

```bash
RUN_TS="with_skill_gpt55_capture_full_20260612T154416Z"

python3 judge/judge.py \
  "runs/17-pricing-engine-skill/$RUN_TS" \
  --mode fault-specific \
  --offline
```

This judges all `F*` directories under that service run and writes:

```text
runs/17-pricing-engine-skill/<RUN_TS>/summary.json
```

`judge.py` returns non-zero when any fault is missed. That is expected; it still
writes `summary.json`.

## Running all skill services for one campaign

This judges every skill service that already produced fault artifacts for a
campaign:

```bash
RUN_TS="with_skill_gpt55_capture_full_20260612T154416Z"

find runs -mindepth 2 -maxdepth 2 -type d -path "runs/*-skill/$RUN_TS" \
  | while IFS= read -r d; do
      if find "$d" -maxdepth 1 -type d -name 'F*' -exec test -f '{}/meta.json' \; -print -quit | grep -q .; then
        echo "$d"
      fi
    done \
  | sort -V \
  | xargs -P 8 -I{} bash -lc 'python3 judge/judge.py "$1" --mode fault-specific --offline >/dev/null 2>&1 || true' _ {}
```

## Summarizing captured services only

This summarizes only services that have a campaign `summary.json`:

```bash
RUN_TS="with_skill_gpt55_capture_full_20260612T154416Z"
OUT="runs/skill_${RUN_TS}_fault-specific-offline-by-fault.md"

python3 tools/summarize_campaign.py \
  --campaign "$RUN_TS" \
  --service-suffix=-skill \
  --out "$OUT" \
  --title "Skill Campaign Fault-Specific Offline Judge Summary"
```

This answers:

```text
Among services that ran and produced fault artifacts, how often did logs contain fault-specific evidence?
```

## Summarizing full-intent score

For large-scale generated-service experiments, use the full-intent score. This
keeps failed or non-runnable generated microservices in the denominator.

If a service has no `summary.json` for the campaign, each intended fault under
that service is counted as a `no_signal` miss. The intended fault set comes from:

```text
services_skill/<service>/faults/*.yaml
```

Command:

```bash
RUN_TS="with_skill_gpt55_capture_full_20260612T154416Z"
OUT="runs/skill_${RUN_TS}_fault-specific-full-intent-by-fault.md"

python3 tools/summarize_campaign.py \
  --campaign "$RUN_TS" \
  --service-suffix=-skill \
  --expected-services-dir services_skill \
  --count-missing-as-no-signal \
  --out "$OUT" \
  --title "Skill Campaign Fault-Specific Full-Intent Summary"
```

This answers:

```text
Across all generated skill services and all intended fault injections, how often did we get fault-specific evidence?
```

Report both metrics when possible:

```text
Runnable/captured detection rate = caught faults / fault instances with summary.json
Full-intent end-to-end score     = caught faults / all intended fault instances
```

Example from `with_skill_gpt55_capture_full_20260612T154416Z`:

```text
Generated services: 200
Runnable / produced summaries: 83 / 200
Runnable/captured detection rate: 89 / 613 = 14.52%
Full-intent end-to-end score: 89 / 1600 = 5.56%
```

## Legacy examples

```bash
# Judge one fault dir using live kubectl state when no snapshot is available
python3 judge/judge.py runs/20260524T120000Z/F01-pod-kill/

# Judge a whole run (all faults under one timestamp dir)
python3 judge/judge.py runs/20260524T120000Z/

# Use a non-default oracle
python3 judge/judge.py runs/<dir>/ --oracle path/to/custom.yaml
```

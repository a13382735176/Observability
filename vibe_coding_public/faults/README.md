# Fault primitives

Fifteen chaos-mesh templates. Each one is rendered per service into
`services/<id>/faults/F<NN>-<name>.yaml` with concrete `app=` selectors
filled in. The template fields use sigil placeholders: `__APP__`,
`__NAMESPACE__`, `__FAULT_NAME__`, `__DURATION__`.

F01-F10 live under `faults/templates/`. F11-F15 live under
`_lib/fault-templates/` and are rendered into the same per-service `faults/`
directories when applicable.

`services/<id>/run.sh` ships pre-rendered yamls; rendering is one-shot
during the scaffold. To re-render after editing a template, run the
service's own `render.sh` (each service has one).

## Primitives

| ID | Kind | Action | Default duration | Targets | What it tests |
|---|---|---|---:|---|---|
| F01-pod-kill        | PodChaos     | `pod-kill mode=one`              | one-shot | the service itself     | restart visible? |
| F02-network-delay   | NetworkChaos | `delay 500±100 ms` (egress)      | 90 s     | the service itself     | latency surfaced? |
| F03-upstream-fail   | HTTPChaos    | `replace.code=503 target=Response`| 90 s    | mock-upstream pod      | 5xx logged? |
| F04-upstream-slow   | NetworkChaos | `delay 500 ms` (egress)          | 90 s     | mock-upstream pod      | upstream latency surfaced? |
| F05-db-down         | PodChaos     | `pod-kill mode=one`              | one-shot | postgres pod           | DB disconnect logged? |
| F06-db-slow         | NetworkChaos | `delay 500 ms` (egress)          | 90 s     | postgres pod           | DB latency surfaced? |
| F07-cache-down      | PodChaos     | `pod-kill mode=one`              | one-shot | redis-cache pod        | cache error logged? |
| F08-cache-slow      | NetworkChaos | `delay 500 ms` (egress)          | 90 s     | redis-cache pod        | cache latency surfaced? |
| F09-queue-down      | PodChaos     | `pod-kill mode=one`              | one-shot | redis-stream pod       | queue disconnect logged? |
| F10-queue-slow      | NetworkChaos | `delay 500 ms` (egress)          | 90 s     | redis-stream pod       | queue latency surfaced? |
| F11-cpu-stress      | StressChaos  | `cpu workers=2 load=80`          | 120 s    | the service itself     | CPU saturation surfaced? |
| F12-net-corrupt     | NetworkChaos | `corrupt=30 correlation=25`      | 120 s    | the service itself     | packet corruption surfaced? |
| F13-time-skew       | TimeChaos    | `timeOffset=+3600s`              | 120 s    | the service itself     | clock skew surfaced? |
| F14-mem-stress      | StressChaos  | `memory workers=1 size=200Mi`    | 120 s    | the service itself     | memory pressure surfaced? |
| F15-dns-fail        | DNSChaos     | `action=error`                   | 90 s     | the service itself     | DNS failure surfaced? |

## Chaos-mesh gotchas (baked into templates — do not edit blindly)

These were validated on kind+kindnet+chaos-mesh 2.7.x. Removing them
re-introduces silent-noop bugs.

1. **NetworkChaos: no `target.selector`**. On kindnet, the iptables
   CLASSIFY rule that chaos-daemon writes when a `target.selector` is
   present matches zero packets — the netem qdisc never sees traffic and
   the chaos is silently absent. Solution: omit `target` entirely so
   netem becomes the root qdisc on eth0 and all egress is affected.
2. **HTTPChaos: `target: Response`, not `Request`**. With `Request`,
   chaos-daemon mangles the body in flight and still proxies to the real
   upstream, which returns 200 — so the injected 503 never reaches the
   client.
3. **HTTPChaos: `replace.body` must be base64**. The CRD field is
   `[]byte`. Plain ASCII silently truncates to garbage.
4. **HTTPChaos: warmup ~7 s**. The in-pod tproxy needs time to bind. The
   judge harness waits ≥10 s after `kubectl apply` before sampling.

## Adding a primitive

1. Add `FNN-<name>` under the appropriate template directory with `__APP__` /
   `__NAMESPACE__` / `__FAULT_NAME__` placeholders when the renderer expects
   them.
2. Add a per-fault regex to `judge/oracle.yaml::faults: FNN-<name>`.
3. Mark which services it applies to in their `faults/` dir (scaffold
   step) and in `README.md`'s service table.

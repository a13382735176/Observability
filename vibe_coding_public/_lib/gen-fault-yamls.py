#!/usr/bin/env python3
"""
gen-fault-yamls.py — generate fault YAML files for a new service.

Usage:
  python3 _lib/gen-fault-yamls.py <service_dir> <app_label> [--deps postgres redis-cache redis-stream upstream] [--extra F11 F12 F13 F14 F15]

Examples:
  # Service with postgres + redis-cache, plus new harder faults:
  python3 _lib/gen-fault-yamls.py services/16-product-catalog product-catalog \
      --deps postgres redis-cache --extra F11 F12 F13

  # Minimal service (no shared deps), all new harder faults:
  python3 _lib/gen-fault-yamls.py services/11-image-resizer image-resizer \
      --extra F11 F12 F13 F14 F15

Always generates:
  F01-pod-kill.yaml        (PodChaos — kills own app pod)
  F02-network-delay.yaml   (NetworkChaos — delays own pod's network)

Per dep flag:
  --deps postgres        → F05-db-down.yaml, F06-db-slow.yaml
  --deps redis-cache     → F07-cache-down.yaml, F08-cache-slow.yaml
  --deps redis-stream    → F09-queue-down.yaml, F10-queue-slow.yaml
  --deps upstream        → F03-upstream-fail.yaml, F04-upstream-slow.yaml

Per extra flag:
  --extra F11  → F11-cpu-stress.yaml
  --extra F12  → F12-net-corrupt.yaml
  --extra F13  → F13-time-skew.yaml
  --extra F14  → F14-mem-stress.yaml
  --extra F15  → F15-dns-fail.yaml
"""

import argparse
import os
import re
import sys

NS = "vibe-coding"

ALWAYS_FAULTS = {
    "F01-pod-kill": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: {app}-f01-pod-kill
  namespace: {ns}
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
""",
    "F02-network-delay": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f02-network-delay
  namespace: {ns}
spec:
  action: delay
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
  delay:
    latency: "3000ms"
    correlation: "0"
    jitter: "0ms"
  duration: "150s"
""",
}

UPSTREAM_FAULTS = {
    "F03-upstream-fail": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: HTTPChaos
metadata:
  name: {app}-f03-upstream-fail
  namespace: {ns}
spec:
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: mock-upstream
  target: Response
  statusCode: 503
  duration: "150s"
""",
    "F04-upstream-slow": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f04-upstream-slow
  namespace: {ns}
spec:
  action: delay
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: mock-upstream
  delay:
    latency: "3000ms"
    correlation: "0"
    jitter: "0ms"
  duration: "150s"
""",
}

DEP_FAULTS = {
    "postgres": {
        "F05-db-down": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f05-db-down
  namespace: {ns}
spec:
  action: partition
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}        # only this service's pod — parallel-safe
  direction: both
  target:
    mode: all
    selector:
      namespaces: [{ns}]
      labelSelectors:
        app: postgres      # network-partition to postgres
  duration: "75s"
""",
        "F06-db-slow": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f06-db-slow
  namespace: {ns}
spec:
  action: delay
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}        # only this service's pod — parallel-safe
  direction: both
  target:
    mode: all
    selector:
      namespaces: [{ns}]
      labelSelectors:
        app: postgres      # delay traffic to/from postgres
  delay:
    latency: "3000ms"
    correlation: "0"
    jitter: "0ms"
  duration: "150s"
""",
    },
    "redis-cache": {
        "F07-cache-down": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f07-cache-down
  namespace: {ns}
spec:
  action: partition
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}        # only this service's pod — parallel-safe
  direction: both
  target:
    mode: all
    selector:
      namespaces: [{ns}]
      labelSelectors:
        app: redis-cache   # network-partition to redis-cache
  duration: "75s"
""",
        "F08-cache-slow": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f08-cache-slow
  namespace: {ns}
spec:
  action: delay
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}        # only this service's pod — parallel-safe
  direction: both
  target:
    mode: all
    selector:
      namespaces: [{ns}]
      labelSelectors:
        app: redis-cache   # delay traffic to/from redis-cache
  delay:
    latency: "3000ms"
    correlation: "0"
    jitter: "0ms"
  duration: "150s"
""",
    },
    "redis-stream": {
        "F09-queue-down": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f09-queue-down
  namespace: {ns}
spec:
  action: partition
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}        # only this service's pod — parallel-safe
  direction: both
  target:
    mode: all
    selector:
      namespaces: [{ns}]
      labelSelectors:
        app: redis-stream  # network-partition to redis-stream
  duration: "75s"
""",
        "F10-queue-slow": """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f10-queue-slow
  namespace: {ns}
spec:
  action: delay
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}        # only this service's pod — parallel-safe
  direction: both
  target:
    mode: all
    selector:
      namespaces: [{ns}]
      labelSelectors:
        app: redis-stream  # delay traffic to/from redis-stream
  delay:
    latency: "3000ms"
    correlation: "0"
    jitter: "0ms"
  duration: "150s"
""",
    },
}

EXTRA_FAULTS = {
    "F11": ("F11-cpu-stress", """\
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: {app}-f11-cpu-stress
  namespace: {ns}
spec:
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
  stressors:
    cpu:
      workers: 2
      load: 80          # 80% CPU × 2 threads — service alive but throttled
  duration: "120s"
"""),
    "F12": ("F12-net-corrupt", """\
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {app}-f12-net-corrupt
  namespace: {ns}
spec:
  action: corrupt
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
  corrupt:
    corrupt: "30"       # 30% packet bit-flip → garbled frames / parse errors
    correlation: "25"
  duration: "120s"
"""),
    "F13": ("F13-time-skew", """\
apiVersion: chaos-mesh.org/v1alpha1
kind: TimeChaos
metadata:
  name: {app}-f13-time-skew
  namespace: {ns}
spec:
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
  timeOffset: "+3600s"  # 1 hour ahead — breaks JWT expiry / cache TTL / rate limits
  duration: "120s"
"""),
    "F14": ("F14-mem-stress", """\
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: {app}-f14-mem-stress
  namespace: {ns}
spec:
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
  stressors:
    memory:
      workers: 1
      size: "200Mi"     # 40% of 512Mi limit — GC pressure / potential OOM
  duration: "120s"
"""),
    "F15": ("F15-dns-fail", """\
apiVersion: chaos-mesh.org/v1alpha1
kind: DNSChaos
metadata:
  name: {app}-f15-dns-fail
  namespace: {ns}
spec:
  action: error         # returns NXDOMAIN for all DNS queries
  mode: all
  selector:
    namespaces: [{ns}]
    labelSelectors:
      app: {app}
  duration: "90s"
"""),
}


def gen(service_dir: str, app_label: str, deps: list, extras: list):
    faults_dir = os.path.join(service_dir, "faults")
    os.makedirs(faults_dir, exist_ok=True)

    written = []
    fmt = dict(app=app_label, ns=NS)

    # Always: F01, F02
    for fname, tmpl in ALWAYS_FAULTS.items():
        path = os.path.join(faults_dir, f"{fname}.yaml")
        with open(path, "w") as f:
            f.write(tmpl.format(**fmt))
        written.append(fname)

    # Upstream deps
    if "upstream" in deps:
        for fname, tmpl in UPSTREAM_FAULTS.items():
            path = os.path.join(faults_dir, f"{fname}.yaml")
            with open(path, "w") as f:
                f.write(tmpl.format(**fmt))
            written.append(fname)

    # Shared dep faults (now per-service NetworkChaos)
    for dep in ["postgres", "redis-cache", "redis-stream"]:
        if dep in deps:
            for fname, tmpl in DEP_FAULTS[dep].items():
                path = os.path.join(faults_dir, f"{fname}.yaml")
                with open(path, "w") as f:
                    f.write(tmpl.format(**fmt))
                written.append(fname)

    # Extra harder faults
    for key in extras:
        key = key.upper()
        if key in EXTRA_FAULTS:
            fname, tmpl = EXTRA_FAULTS[key]
            path = os.path.join(faults_dir, f"{fname}.yaml")
            with open(path, "w") as f:
                f.write(tmpl.format(**fmt))
            written.append(fname)

    print(f"Generated {len(written)} fault YAMLs in {faults_dir}:")
    for w in written:
        print(f"  {w}.yaml")
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_dir", help="Path to service directory, e.g. services/16-product-catalog")
    parser.add_argument("app_label", help="k8s app label, e.g. product-catalog")
    parser.add_argument("--deps", nargs="*", default=[],
                        choices=["postgres", "redis-cache", "redis-stream", "upstream"],
                        help="Dependencies this service uses")
    parser.add_argument("--extra", nargs="*", default=[],
                        choices=["F11", "F12", "F13", "F14", "F15"],
                        help="Extra harder fault types to generate")
    args = parser.parse_args()

    gen(args.service_dir, args.app_label, args.deps, args.extra)
    # Print the FAULTS array line for run.sh
    faults_dir = os.path.join(args.service_dir, "faults")
    fault_ids = sorted(
        f.replace(".yaml", "") for f in os.listdir(faults_dir) if f.endswith(".yaml")
    )
    print(f"\nFAULTS array for run.sh:")
    print('FAULTS=( "' + '" "'.join(fault_ids) + '" )')


if __name__ == "__main__":
    main()

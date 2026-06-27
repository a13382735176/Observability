#!/usr/bin/env python3
"""
vibe_coding scaffold — generates per-service boilerplate from a single
catalog. Idempotent: re-run after editing to refresh boilerplate without
touching `src/` (which is hand-written per service).

Generates per service:
  k8s/deployment.yaml         (Deployment + Service)
  Dockerfile                  (per-language template; only if absent)
  faults/F*.yaml              (rendered from ../../faults/templates/F*.tpl.yaml)
  run.sh                      (5-line wrapper sourcing _lib/run-common.sh)

DOES NOT touch:
  src/                        (hand-written)
  SPEC.md                     (written last per user instruction)
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # _lib/
ROOT = HERE.parent                              # vibe_coding/
SERVICES_ROOT = ROOT / "services"
FAULT_TEMPLATES = ROOT / "faults" / "templates"
NAMESPACE = "vibe-coding"
# Chaos `duration` should outlive the orchestrator observation window
# (max 120s for slow/upstream faults; see _lib/run-common.sh FAULT_WINDOW).
DURATION_DEFAULT = "150s"

# -----------------------------------------------------------------------------
# Catalog: 15 services. Each entry MUST list:
#   id          dir name under services/
#   app         k8s pod label (and Deployment name)
#   lang        python|go|java|csharp|cpp
#   deps        any subset of {postgres, redis_cache, redis_stream, upstream}
#   faults      list of fault ids — must match files in faults/templates/
#   smoke_path  optional override (default "/healthz")
# -----------------------------------------------------------------------------
SERVICES = [
    {"id": "01-catalog-api",            "app": "catalog-api",         "lang": "python", "deps": ["postgres"],                              "faults": ["F01-pod-kill","F02-network-delay","F05-db-down","F06-db-slow"], "smoke_path": "/products"},
    {"id": "02-cart-service",           "app": "cart-service",        "lang": "go",     "deps": ["redis_cache"],                            "faults": ["F01-pod-kill","F02-network-delay","F07-cache-down","F08-cache-slow"], "smoke_path": "/cart/u1"},
    {"id": "03-order-api",              "app": "order-api",           "lang": "java",   "deps": ["postgres","redis_stream"],                "faults": ["F01-pod-kill","F02-network-delay","F05-db-down","F06-db-slow","F09-queue-down","F10-queue-slow"]},
    {"id": "04-payment-gateway",        "app": "payment-gateway",     "lang": "csharp", "deps": ["upstream"],                               "faults": ["F01-pod-kill","F02-network-delay","F03-upstream-fail","F04-upstream-slow"]},
    {"id": "05-inventory-tracker",      "app": "inventory-tracker",   "lang": "go",     "deps": ["redis_cache","redis_stream"],             "faults": ["F01-pod-kill","F02-network-delay","F07-cache-down","F08-cache-slow","F09-queue-down","F10-queue-slow"]},
    {"id": "06-user-profile",           "app": "user-profile",        "lang": "java",   "deps": ["postgres"],                                "faults": ["F01-pod-kill","F02-network-delay","F05-db-down","F06-db-slow"]},
    {"id": "07-session-cache",          "app": "session-cache",       "lang": "go",     "deps": ["redis_cache"],                            "faults": ["F01-pod-kill","F02-network-delay","F07-cache-down","F08-cache-slow"]},
    {"id": "08-notification-dispatcher","app": "notification-dispatcher","lang": "python","deps": ["redis_stream","upstream"],              "faults": ["F01-pod-kill","F02-network-delay","F03-upstream-fail","F04-upstream-slow","F09-queue-down","F10-queue-slow"]},
    {"id": "09-order-processor",        "app": "order-processor",     "lang": "java",   "deps": ["postgres","redis_stream"],                "faults": ["F01-pod-kill","F02-network-delay","F05-db-down","F06-db-slow","F09-queue-down","F10-queue-slow"]},
    {"id": "10-search-indexer",         "app": "search-indexer",      "lang": "python", "deps": ["postgres","redis_cache"],                 "faults": ["F01-pod-kill","F02-network-delay","F05-db-down","F06-db-slow","F07-cache-down","F08-cache-slow"]},
    {"id": "11-image-resizer",          "app": "image-resizer",       "lang": "cpp",    "deps": [],                                          "faults": ["F01-pod-kill","F02-network-delay"]},
    {"id": "12-rate-limiter-proxy",     "app": "rate-limiter-proxy",  "lang": "go",     "deps": ["redis_cache","upstream"],                 "faults": ["F01-pod-kill","F02-network-delay","F03-upstream-fail","F04-upstream-slow","F07-cache-down","F08-cache-slow"], "smoke_path": "/api/anything"},
    {"id": "13-auth-token-svc",         "app": "auth-token-svc",      "lang": "java",   "deps": ["postgres"],                                "faults": ["F01-pod-kill","F02-network-delay","F05-db-down","F06-db-slow"]},
    {"id": "14-metrics-aggregator",     "app": "metrics-aggregator",  "lang": "python", "deps": ["redis_cache","redis_stream"],             "faults": ["F01-pod-kill","F02-network-delay","F07-cache-down","F08-cache-slow","F09-queue-down","F10-queue-slow"], "smoke_path": "/metrics"},
    {"id": "15-webhook-fanout",         "app": "webhook-fanout",      "lang": "csharp", "deps": ["upstream"],                               "faults": ["F01-pod-kill","F02-network-delay","F03-upstream-fail","F04-upstream-slow"]},
]


def env_for_deps(deps: list[str]) -> list[tuple[str, str]]:
    env: list[tuple[str, str]] = []
    if "postgres" in deps:
        env.append(("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"))
    if "redis_cache" in deps:
        env.append(("REDIS_CACHE_URL", "redis://redis-cache:6379/0"))
        env.append(("REDIS_CACHE_HOST", "redis-cache"))
        env.append(("REDIS_CACHE_PORT", "6379"))
    if "redis_stream" in deps:
        env.append(("REDIS_STREAM_URL", "redis://redis-stream:6379/0"))
        env.append(("REDIS_STREAM_HOST", "redis-stream"))
        env.append(("REDIS_STREAM_PORT", "6379"))
    if "upstream" in deps:
        env.append(("UPSTREAM_URL", "http://mock-upstream:8080"))
    return env


K8S_DEPLOY_TPL = """\
apiVersion: v1
kind: Service
metadata:
  name: {app}
  namespace: {ns}
spec:
  selector: {{ app: {app} }}
  ports: [ {{ name: http, port: 8080, targetPort: 8080 }} ]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app}
  namespace: {ns}
spec:
  replicas: 1
  selector: {{ matchLabels: {{ app: {app} }} }}
  template:
    metadata:
      labels: {{ app: {app} }}
    spec:
      containers:
        - name: app
          image: vibe/{svc_id}:dev
          imagePullPolicy: Never
          ports: [ {{ containerPort: 8080 }} ]
          env:
            - {{ name: APP_NAME, value: {app} }}
{env_block}
          readinessProbe:
            httpGet: {{ path: /healthz, port: 8080 }}
            initialDelaySeconds: 3
            periodSeconds: 3
            failureThreshold: 5
          resources:
            requests: {{ cpu: 50m, memory: 64Mi }}
            limits:   {{ cpu: 500m, memory: 512Mi }}
"""


DOCKERFILE_TPLS = {
    "python": """\
FROM python:3.12-slim
WORKDIR /app
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ .
EXPOSE 8080
CMD ["python", "-u", "main.py"]
""",
    "go": """\
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY src/ .
# We do not vendor a go.sum (services depend on a tiny set of well-known
# modules). `go mod tidy` regenerates it from go.mod inside the build.
RUN go mod tidy && CGO_ENABLED=0 go build -o /app ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /app /app
EXPOSE 8080
CMD ["/app"]
""",
    # Java: pom.xml + src/main/java/... live at the SERVICE ROOT (not under src/).
    # This matches the standard Maven layout.
    "java": """\
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /work
COPY pom.xml .
RUN mvn -q -B -DskipTests dependency:go-offline || true
COPY src/ src/
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:21-jre-alpine
COPY --from=build /work/target/*-jar-with-dependencies.jar /app.jar
EXPOSE 8080
CMD ["java", "-jar", "/app.jar"]
""",
    # C#: .csproj + Program.cs live at the SERVICE ROOT.
    "csharp": """\
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /work
COPY *.csproj .
RUN dotnet restore
COPY . .
RUN dotnet publish -c Release -o /app /p:UseAppHost=false /p:GenerateDocumentationFile=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine
WORKDIR /app
COPY --from=build /app .
EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080
ENTRYPOINT ["dotnet", "app.dll"]
""",
    # C++: CMakeLists.txt + main.cpp + httplib.h at the SERVICE ROOT.
    "cpp": """\
FROM debian:bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends \\
    g++ cmake ninja-build pkg-config ca-certificates curl \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN mkdir -p build && cd build && cmake -GNinja .. && ninja

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \\
    libstdc++6 ca-certificates \\
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/app /usr/local/bin/app
EXPOSE 8080
CMD ["/usr/local/bin/app"]
""",
}


RUN_SH_TPL = """\
#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
SERVICE_ID="{svc_id}"
APP_LABEL="{app}"
LANG="{lang}"
FAULTS=({faults_arr})
{smoke_path_line}
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"
"""


def render_k8s(svc: dict) -> str:
    env_lines = []
    for k, v in env_for_deps(svc["deps"]):
        env_lines.append(f"            - {{ name: {k}, value: \"{v}\" }}")
    # If no extra deps, leave the trailing slot empty — the APP_NAME entry
    # already inserted by the template above keeps the list valid.
    env_block = "\n".join(env_lines)
    return K8S_DEPLOY_TPL.format(
        app=svc["app"],
        ns=NAMESPACE,
        svc_id=svc["id"],
        env_block=env_block,
    )


def render_fault(template_path: Path, svc: dict, fault_id: str) -> str:
    raw = template_path.read_text()
    # __APP__ varies by fault target.
    if fault_id in ("F01-pod-kill", "F02-network-delay"):
        target_app = svc["app"]
    elif fault_id in ("F03-upstream-fail", "F04-upstream-slow"):
        target_app = "mock-upstream"
    elif fault_id in ("F05-db-down", "F06-db-slow"):
        target_app = "postgres"
    elif fault_id in ("F07-cache-down", "F08-cache-slow"):
        target_app = "redis-cache"
    elif fault_id in ("F09-queue-down", "F10-queue-slow"):
        target_app = "redis-stream"
    else:
        raise ValueError(f"unknown fault id {fault_id}")
    # __FAULT_NAME__ is namespaced per service to avoid collisions if two
    # services inject in the same cluster at once.
    fault_name = f"{svc['app']}-{fault_id.lower()}"
    return (raw
            .replace("__APP__", target_app)
            .replace("__NAMESPACE__", NAMESPACE)
            .replace("__FAULT_NAME__", fault_name)
            .replace("__DURATION__", DURATION_DEFAULT))


def render_run_sh(svc: dict) -> str:
    faults_arr = " ".join(f'"{f}"' for f in svc["faults"])
    smoke_line = ""
    if "smoke_path" in svc:
        smoke_line = f'SMOKE_PATH="{svc["smoke_path"]}"'
    return RUN_SH_TPL.format(
        svc_id=svc["id"],
        app=svc["app"],
        lang=svc["lang"],
        faults_arr=faults_arr,
        smoke_path_line=smoke_line,
    )


def write_if_changed(p: Path, content: str, executable: bool = False) -> bool:
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text() if p.exists() else None
    if old == content:
        if executable:
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return False
    p.write_text(content)
    if executable:
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def scaffold_one(svc: dict) -> dict[str, int]:
    base = SERVICES_ROOT / svc["id"]
    base.mkdir(parents=True, exist_ok=True)
    (base / "src").mkdir(exist_ok=True)

    counts = {"written": 0, "unchanged": 0}

    # 1. k8s
    if write_if_changed(base / "k8s" / "deployment.yaml", render_k8s(svc)):
        counts["written"] += 1
    else:
        counts["unchanged"] += 1

    # 2. Dockerfile — only write if missing (hand-edits preserved)
    docker_p = base / "Dockerfile"
    if not docker_p.exists():
        write_if_changed(docker_p, DOCKERFILE_TPLS[svc["lang"]])
        counts["written"] += 1
    else:
        counts["unchanged"] += 1

    # 3. faults
    for fid in svc["faults"]:
        tpl_p = FAULT_TEMPLATES / f"{fid}.tpl.yaml"
        if not tpl_p.exists():
            print(f"  WARN no template for {fid}, skipping", file=sys.stderr)
            continue
        out = render_fault(tpl_p, svc, fid)
        if write_if_changed(base / "faults" / f"{fid}.yaml", out):
            counts["written"] += 1
        else:
            counts["unchanged"] += 1

    # 4. run.sh
    if write_if_changed(base / "run.sh", render_run_sh(svc), executable=True):
        counts["written"] += 1
    else:
        counts["unchanged"] += 1

    return counts


def main() -> int:
    total_w = total_u = 0
    for svc in SERVICES:
        print(f"-> {svc['id']:36s} lang={svc['lang']:6s} deps={svc['deps']}")
        c = scaffold_one(svc)
        total_w += c["written"]
        total_u += c["unchanged"]
    print(f"\nscaffold done: {total_w} files written, {total_u} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())

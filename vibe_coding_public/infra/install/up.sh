#!/usr/bin/env bash
# Bring up the vibe_coding cluster end-to-end.
#   - create kind cluster `vibe`
#   - install chaos-mesh v2.7.x via helm
#   - apply shared deps (postgres, redis-cache, redis-stream, mock-upstream)
# Idempotent: re-running on an existing cluster is a no-op for the cluster step.

set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"

CLUSTER="vibe"
NS="vibe-coding"
CHAOS_NS="chaos-mesh"
CHAOS_VERSION="${CHAOS_VERSION:-2.7.2}"

need() { command -v "$1" >/dev/null || { echo "missing tool: $1"; exit 1; }; }
need docker
need kind
need kubectl
need helm

# --- cluster ---
if kind get clusters | grep -qx "$CLUSTER"; then
  echo "[infra] cluster '$CLUSTER' already exists; reusing"
else
  echo "[infra] creating kind cluster '$CLUSTER'"
  kind create cluster --config "$ROOT/infra/kind-cluster.yaml" --wait 120s
fi

kubectl cluster-info --context "kind-$CLUSTER" >/dev/null
kubectl config use-context "kind-$CLUSTER"

# --- chaos-mesh ---
if helm -n "$CHAOS_NS" list 2>/dev/null | grep -q chaos-mesh; then
  echo "[infra] chaos-mesh already installed"
else
  echo "[infra] installing chaos-mesh $CHAOS_VERSION"
  kubectl create ns "$CHAOS_NS" 2>/dev/null || true
  helm repo add chaos-mesh https://charts.chaos-mesh.org 2>/dev/null || true
  helm repo update chaos-mesh
  helm install chaos-mesh chaos-mesh/chaos-mesh \
    --namespace "$CHAOS_NS" \
    --version "$CHAOS_VERSION" \
    --set chaosDaemon.runtime=containerd \
    --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
    --set dashboard.create=false \
    --wait --timeout 5m
fi

echo "[infra] waiting for chaos-mesh controller"
kubectl -n "$CHAOS_NS" rollout status deploy/chaos-controller-manager --timeout=180s

# --- namespace + deps ---
echo "[infra] applying deps in ns/$NS"
kubectl apply -f "$ROOT/infra/deps/"
kubectl -n "$NS" rollout status deploy/postgres --timeout=180s
kubectl -n "$NS" rollout status deploy/redis-cache --timeout=120s
kubectl -n "$NS" rollout status deploy/redis-stream --timeout=120s
kubectl -n "$NS" rollout status deploy/mock-upstream --timeout=120s

echo
echo "[infra] ready. Try:  make demo SVC=01-catalog-api"

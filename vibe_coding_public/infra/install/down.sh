#!/usr/bin/env bash
# Delete the vibe_coding kind cluster.
set -euo pipefail
CLUSTER="vibe"
if kind get clusters | grep -qx "$CLUSTER"; then
  kind delete cluster --name "$CLUSTER"
else
  echo "no cluster '$CLUSTER' to delete"
fi

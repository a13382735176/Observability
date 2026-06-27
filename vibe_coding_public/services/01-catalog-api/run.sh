#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="01-catalog-api"
APP_LABEL="catalog-api"
LANG="python"
FAULTS=("F01-pod-kill" "F02-network-delay" "F05-db-down" "F06-db-slow")
SMOKE_PATH="/products"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

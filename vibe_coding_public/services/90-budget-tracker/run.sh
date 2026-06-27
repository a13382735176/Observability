#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="90-budget-tracker"
APP_LABEL="budget-tracker"
LANG="python"
FAULTS=("F01-pod-kill" "F02-network-delay" "F05-db-down" "F06-db-slow" "F07-cache-down" "F08-cache-slow" "F11-cpu-stress" "F12-net-corrupt" "F13-time-skew")
SMOKE_PATH="/healthz"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

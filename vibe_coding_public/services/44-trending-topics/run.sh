#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="44-trending-topics"
APP_LABEL="trending-topics"
LANG="typescript"
FAULTS=("F01-pod-kill" "F02-network-delay" "F07-cache-down" "F08-cache-slow" "F09-queue-down" "F10-queue-slow" "F11-cpu-stress" "F12-net-corrupt" "F13-time-skew")
SMOKE_PATH="/healthz"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

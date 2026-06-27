#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="23-checkout-service"
APP_LABEL="checkout-service"
LANG="typescript"
FAULTS=("F01-pod-kill" "F02-network-delay" "F05-db-down" "F06-db-slow" "F09-queue-down" "F10-queue-slow" "F11-cpu-stress" "F12-net-corrupt" "F13-time-skew")
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

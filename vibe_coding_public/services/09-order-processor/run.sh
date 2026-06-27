#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="09-order-processor"
APP_LABEL="order-processor"
LANG="java"
FAULTS=("F01-pod-kill" "F02-network-delay" "F05-db-down" "F06-db-slow" "F09-queue-down" "F10-queue-slow")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

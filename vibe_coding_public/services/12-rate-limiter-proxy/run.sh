#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="12-rate-limiter-proxy"
APP_LABEL="rate-limiter-proxy"
LANG="go"
FAULTS=("F01-pod-kill" "F02-network-delay" "F03-upstream-fail" "F04-upstream-slow" "F07-cache-down" "F08-cache-slow")
SMOKE_PATH="/api/anything"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

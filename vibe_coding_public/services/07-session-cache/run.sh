#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="07-session-cache"
APP_LABEL="session-cache"
LANG="go"
FAULTS=("F01-pod-kill" "F02-network-delay" "F07-cache-down" "F08-cache-slow")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

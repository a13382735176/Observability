#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="13-auth-token-svc"
APP_LABEL="auth-token-svc"
LANG="java"
FAULTS=("F01-pod-kill" "F02-network-delay" "F05-db-down" "F06-db-slow")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

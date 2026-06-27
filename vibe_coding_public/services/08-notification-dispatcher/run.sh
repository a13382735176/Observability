#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="08-notification-dispatcher"
APP_LABEL="notification-dispatcher"
LANG="python"
FAULTS=("F01-pod-kill" "F02-network-delay" "F03-upstream-fail" "F04-upstream-slow" "F09-queue-down" "F10-queue-slow")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

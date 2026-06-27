#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="04-payment-gateway"
APP_LABEL="payment-gateway"
LANG="csharp"
FAULTS=("F01-pod-kill" "F02-network-delay" "F03-upstream-fail" "F04-upstream-slow")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

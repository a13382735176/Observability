#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="02-cart-service"
APP_LABEL="cart-service"
LANG="go"
FAULTS=("F01-pod-kill" "F02-network-delay" "F07-cache-down" "F08-cache-slow")
SMOKE_PATH="/cart/u1"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

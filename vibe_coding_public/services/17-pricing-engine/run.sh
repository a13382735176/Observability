#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="17-pricing-engine"
APP_LABEL="pricing-engine"
LANG="go"
FAULTS=("F01-pod-kill" "F02-network-delay" "F07-cache-down" "F08-cache-slow" "F11-cpu-stress" "F12-net-corrupt" "F13-time-skew")
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="11-image-resizer"
APP_LABEL="image-resizer"
LANG="cpp"
FAULTS=("F01-pod-kill" "F02-network-delay")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

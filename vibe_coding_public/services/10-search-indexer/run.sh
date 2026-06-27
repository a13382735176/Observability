#!/usr/bin/env bash
# Auto-generated wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="10-search-indexer"
APP_LABEL="search-indexer"
LANG="python"
FAULTS=("F01-pod-kill" "F02-network-delay" "F05-db-down" "F06-db-slow" "F07-cache-down" "F08-cache-slow")

source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

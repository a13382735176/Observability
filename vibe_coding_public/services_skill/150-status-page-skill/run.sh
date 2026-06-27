#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="150-status-page-skill"
APP_LABEL="status-page-skill"
LANG="java"
SMOKE_PATH="/healthz"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

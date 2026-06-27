#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="12-rate-limiter-proxy-skill"
APP_LABEL="rate-limiter-proxy-skill"
LANG="go"
SMOKE_PATH="/api/anything"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

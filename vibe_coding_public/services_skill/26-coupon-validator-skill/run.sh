#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="26-coupon-validator-skill"
APP_LABEL="coupon-validator-skill"
LANG="typescript"
SMOKE_PATH="/healthz"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

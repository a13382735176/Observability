#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="140-shipping-quote-skill"
APP_LABEL="shipping-quote-skill"
LANG="typescript"
SMOKE_PATH="/healthz"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

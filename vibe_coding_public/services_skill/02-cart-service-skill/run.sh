#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="02-cart-service-skill"
APP_LABEL="cart-service-skill"
LANG="go"
SMOKE_PATH="/cart/u1"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

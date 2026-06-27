#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ID="01-catalog-api-skill"
APP_LABEL="catalog-api-skill"
LANG="python"
SMOKE_PATH="/products"
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"

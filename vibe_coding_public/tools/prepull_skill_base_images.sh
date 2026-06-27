#!/usr/bin/env bash
# Pre-pull base images used by services_skill Dockerfiles.

set -euo pipefail

RUN_TS=""
ONLY_FAILED=0
RETRIES="${PULL_RETRIES:-3}"
SLEEP_S="${PULL_RETRY_SLEEP_S:-20}"

usage() {
  cat <<EOF
Usage:
  bash tools/prepull_skill_base_images.sh
  bash tools/prepull_skill_base_images.sh --failed RUN_TS

Environment:
  PULL_RETRIES             retry count per image, default: 3
  PULL_RETRY_SLEEP_S       sleep between retries, default: 20
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--failed" ]]; then
  ONLY_FAILED=1
  RUN_TS="${2:-}"
  if [[ -z "$RUN_TS" ]]; then
    echo "error: --failed requires RUN_TS" >&2
    exit 2
  fi
fi

services=()
if [[ "$ONLY_FAILED" -eq 1 ]]; then
  while IFS= read -r svc; do
    fault_count="$(find "runs/$svc/$RUN_TS" -maxdepth 1 -type d -name 'F*' 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "$fault_count" == "0" ]]; then
      services+=("$svc")
    fi
  done < <(find services_skill -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | grep -E '^[0-9]+-' | sort -V)
else
  mapfile -t services < <(find services_skill -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | grep -E '^[0-9]+-' | sort -V)
fi

if [[ ${#services[@]} -eq 0 ]]; then
  echo "no services selected"
  exit 0
fi

mapfile -t images < <(
  for svc in "${services[@]}"; do
    dockerfile="services_skill/$svc/Dockerfile"
    [[ -f "$dockerfile" ]] || continue
    awk 'toupper($1)=="FROM" {print $2}' "$dockerfile" | sed 's/@.*//'
  done | sort -u
)

echo "services: ${#services[@]}"
echo "base images: ${#images[@]}"
printf '  %s\n' "${images[@]}"

for image in "${images[@]}"; do
  attempt=1
  max_attempts=$((RETRIES + 1))
  rc=1
  while [[ "$attempt" -le "$max_attempts" ]]; do
    echo "[pull] $image attempt ${attempt}/${max_attempts}"
    set +e
    docker pull "$image"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      break
    fi
    if [[ "$attempt" -lt "$max_attempts" ]]; then
      echo "[pull] $image failed rc=$rc; sleeping ${SLEEP_S}s" >&2
      sleep "$SLEEP_S"
    fi
    attempt=$((attempt + 1))
  done
  if [[ "$rc" -ne 0 ]]; then
    echo "[pull] FAILED $image after ${max_attempts} attempts" >&2
  fi
done
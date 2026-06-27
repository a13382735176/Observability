#!/usr/bin/env bash
# Stop interrupted/active services_skill capture workers.

set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "--list" ]]; then
  DRY_RUN=1
fi

is_target_cmd() {
  local cmd="$1"
  [[ "$cmd" =~ (^|[[:space:]/])bash[[:space:]]+run_skill_demos\.sh([[:space:]]|$) ]] && return 0
  [[ "$cmd" == *"make capture-skill SVC="* ]] && return 0
  [[ "$cmd" =~ bash[[:space:]]+services_skill/.*/run\.sh[[:space:]]+capture ]] && return 0
  return 1
}

mapfile -t PS_ROWS < <(ps -eo pid=,ppid=,cmd=)

declare -A PPID_BY_PID=()
declare -A CMD_BY_PID=()
declare -a ROOTS=()

for row in "${PS_ROWS[@]}"; do
  read -r pid ppid cmd <<<"$row"
  [[ -n "${pid:-}" && -n "${ppid:-}" ]] || continue
  PPID_BY_PID["$pid"]="$ppid"
  CMD_BY_PID["$pid"]="${cmd:-}"
  if [[ "$pid" != "$$" ]] && is_target_cmd "${cmd:-}"; then
    ROOTS+=("$pid")
  fi
done

if [[ ${#ROOTS[@]} -eq 0 ]]; then
  echo "no active skill capture workers found"
  exit 0
fi

declare -A WANT=()
declare -a QUEUE=("${ROOTS[@]}")

while [[ ${#QUEUE[@]} -gt 0 ]]; do
  pid="${QUEUE[0]}"
  QUEUE=("${QUEUE[@]:1}")
  [[ -n "${WANT[$pid]:-}" ]] && continue
  WANT["$pid"]=1
  for child in "${!PPID_BY_PID[@]}"; do
    if [[ "${PPID_BY_PID[$child]}" == "$pid" ]]; then
      QUEUE+=("$child")
    fi
  done
done

mapfile -t PIDS < <(printf '%s\n' "${!WANT[@]}" | sort -n)

echo "skill capture processes:"
for pid in "${PIDS[@]}"; do
  printf '  %s  %s\n' "$pid" "${CMD_BY_PID[$pid]:-}"
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  exit 0
fi

echo "sending TERM..."
kill -TERM "${PIDS[@]}" 2>/dev/null || true

remaining=()
for pid in "${PIDS[@]}"; do
  if kill -0 "$pid" 2>/dev/null; then
    remaining+=("$pid")
  fi
done

if [[ ${#remaining[@]} -gt 0 ]]; then
  echo "sending KILL to remaining processes..."
  kill -KILL "${remaining[@]}" 2>/dev/null || true
fi

echo "done"
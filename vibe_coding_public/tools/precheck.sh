#!/usr/bin/env bash
# tools/precheck.sh — scan (and optionally clean) chaos-mesh residue before a run.
#
# What it checks for each shared-dep pod:
#   1. Zombie chaos CRDs in the namespace (NetworkChaos, PodChaos, ...).
#   2. Leftover iptables-legacy CHAOS-INPUT / CHAOS-OUTPUT chains inside the pod netns.
#   3. tc qdisc anomalies (anything other than the default noqueue) on pod interfaces.
#
# Usage:
#   tools/precheck.sh                       # scan defaults, read-only, exit 1 if dirty
#   tools/precheck.sh --pods 'postgres,redis-cache,redis-stream,mock-upstream'
#   tools/precheck.sh --pods 'app=tax-calculator'   # one app= selector also ok
#   tools/precheck.sh --fix                 # clean what's dirty (idempotent)
#   tools/precheck.sh --fix --crds          # also delete zombie chaos CRDs
#   tools/precheck.sh --quiet               # just print summary line + exit code
#
# Exit codes: 0=clean, 1=dirty (no --fix), 2=invocation error.

set -uo pipefail

NS="${NS:-vibe-coding}"
NODE_CTR="${NODE_CTR:-vibe-control-plane}"
DEFAULT_PODS='postgres,redis-cache,redis-stream,mock-upstream'

PODS_SPEC="$DEFAULT_PODS"
DO_FIX=0
DO_CRDS=0
QUIET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pods)   PODS_SPEC="$2"; shift 2 ;;
    --fix)    DO_FIX=1; shift ;;
    --crds)   DO_CRDS=1; shift ;;
    --quiet)  QUIET=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0" >&2; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

say()   { (( QUIET )) || echo "$@"; }
hr()    { (( QUIET )) || echo "─────────────────────────────────────────────"; }

# --- 0. Sanity ------------------------------------------------------------
if ! kubectl get ns "$NS" >/dev/null 2>&1; then
  echo "❌ namespace '$NS' not found" >&2; exit 2
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$NODE_CTR"; then
  echo "❌ node container '$NODE_CTR' not running" >&2; exit 2
fi
if ! docker exec "$NODE_CTR" sh -c 'command -v jq && command -v nsenter && command -v crictl' >/dev/null 2>&1; then
  echo "❌ node container missing one of: jq / nsenter / crictl" >&2; exit 2
fi

DIRTY=0

# --- 1. Zombie chaos CRDs -------------------------------------------------
hr; say "[1/3] chaos-mesh CRD residue in ns/$NS"
declare -A CRD_COUNTS
TOTAL_CRDS=0
for kind in networkchaos podchaos httpchaos stresschaos timechaos iochaos dnschaos kernelchaos; do
  n=$(kubectl -n "$NS" get "$kind" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  CRD_COUNTS[$kind]=$n
  TOTAL_CRDS=$((TOTAL_CRDS + n))
  if (( n > 0 )); then
    say "  ⚠  $kind: $n"
  fi
done
if (( TOTAL_CRDS == 0 )); then
  say "  ✅ no chaos CRDs"
else
  say "  → total $TOTAL_CRDS chaos CRDs present"
  DIRTY=1
fi

# --- 2. Build pod list ----------------------------------------------------
declare -a TARGET_PODS
if [[ "$PODS_SPEC" == *=* ]]; then
  # treat as a single label selector
  while IFS= read -r p; do TARGET_PODS+=("$p"); done < <(
    kubectl -n "$NS" get pod -l "$PODS_SPEC" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null
  )
else
  IFS=',' read -ra APPS <<<"$PODS_SPEC"
  for app in "${APPS[@]}"; do
    app="${app// /}"
    while IFS= read -r p; do
      [[ -n "$p" ]] && TARGET_PODS+=("$p")
    done < <(
      kubectl -n "$NS" get pod -l "app=$app" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null
    )
  done
fi

if (( ${#TARGET_PODS[@]} == 0 )); then
  echo "❌ no pods matched '$PODS_SPEC' in ns/$NS" >&2; exit 2
fi

# --- 3. Per-pod netns inspection -----------------------------------------
hr; say "[2/3] iptables-legacy CHAOS-INPUT / CHAOS-OUTPUT in pod netns"

# Returns container PID (host-PID) for a given pod, or empty.
pod_pid() {
  local pod="$1"
  local ctr
  ctr=$(kubectl -n "$NS" get pod "$pod" -o jsonpath='{.status.containerStatuses[0].containerID}' 2>/dev/null | sed 's|containerd://||')
  [[ -z "$ctr" ]] && return 1
  docker exec "$NODE_CTR" sh -c "crictl inspect $ctr 2>/dev/null | jq -r '.info.pid // empty'"
}

declare -a ACTIVE_DIRTY_PODS=()   # actively blocking traffic — must fix
declare -a STALE_PODS=()          # leftover chains but unlinked — cosmetic
for pod in "${TARGET_PODS[@]}"; do
  pid=$(pod_pid "$pod") || pid=""
  if [[ -z "$pid" || "$pid" == "null" || "$pid" == "0" ]]; then
    say "  ⚠  $pod: cannot resolve container PID (pod not running?)"
    continue
  fi

  # Pull the whole iptables-legacy listing once to avoid 6× docker-exec round-trips per pod.
  ipt_dump=$(docker exec "$NODE_CTR" nsenter -t "$pid" -n iptables-legacy -L -n 2>/dev/null)
  tc_dump=$(docker exec "$NODE_CTR" nsenter -t "$pid" -n tc qdisc show 2>/dev/null)

  # Is CHAOS-* actually referenced from the mainline INPUT/OUTPUT chains? -> actively blocking.
  active_in=$(awk '/^Chain INPUT \(/{f=1;next} /^Chain /{f=0} f && /CHAOS-INPUT/{c++} END{print c+0}' <<<"$ipt_dump")
  active_out=$(awk '/^Chain OUTPUT \(/{f=1;next} /^Chain /{f=0} f && /CHAOS-OUTPUT/{c++} END{print c+0}' <<<"$ipt_dump")

  # Stale leftovers (chains exist but no jump from mainline).
  in_chains=$(awk '/^Chain INPUT\//{c++} END{print c+0}' <<<"$ipt_dump")
  out_chains=$(awk '/^Chain OUTPUT\//{c++} END{print c+0}' <<<"$ipt_dump")
  has_chaos_in=$(awk '/^Chain CHAOS-INPUT /{print 1; exit}' <<<"$ipt_dump")
  has_chaos_out=$(awk '/^Chain CHAOS-OUTPUT /{print 1; exit}' <<<"$ipt_dump")

  # tc qdisc anomalies — netem/tbf/htb/etc. on a pod interface = active throttle.
  bad_qdisc=$(grep -vE 'noqueue|mq |pfifo_fast|^$' <<<"$tc_dump" | grep -c '^qdisc')

  if (( active_in > 0 || active_out > 0 || bad_qdisc > 0 )); then
    say "  ⛔ $pod ACTIVE: INPUT→CHAOS=$active_in OUTPUT→CHAOS=$active_out tc-bad=$bad_qdisc"
    ACTIVE_DIRTY_PODS+=("$pod:$pid")
    DIRTY=1
  elif (( in_chains > 0 || out_chains > 0 || ${has_chaos_in:-0} > 0 || ${has_chaos_out:-0} > 0 )); then
    say "  · $pod stale: $in_chains+$out_chains orphan sub-chains (not referenced; harmless)"
    STALE_PODS+=("$pod:$pid")
  else
    say "  ✅ $pod clean"
  fi
done

# --- 4. Fix mode ----------------------------------------------------------
hr
if (( DO_FIX )); then
  say "[3/3] FIX mode"
  # 4a. Clean both ACTIVE and STALE pods (full sweep — same operations either way)
  FIX_TARGETS=("${ACTIVE_DIRTY_PODS[@]}" "${STALE_PODS[@]}")
  if (( ${#FIX_TARGETS[@]} > 0 )); then
    for entry in "${FIX_TARGETS[@]}"; do
      pod="${entry%:*}"; pid="${entry#*:}"
      say "  · cleaning $pod (pid=$pid)"
      docker exec "$NODE_CTR" nsenter -t "$pid" -n bash -c '
        set +e
        iptables-legacy -D INPUT  -j CHAOS-INPUT  2>/dev/null
        iptables-legacy -D OUTPUT -j CHAOS-OUTPUT 2>/dev/null
        # Collect every chaos-mesh sub-chain (INPUT/* and OUTPUT/*) — no awk/$-escaping headaches.
        chains=$(iptables-legacy -L -n 2>/dev/null \
          | sed -nE "s|^Chain (INPUT/[^ ]+).*|\1|p; s|^Chain (OUTPUT/[^ ]+).*|\1|p")
        for ch in $chains; do
          iptables-legacy -F "$ch" 2>/dev/null
          iptables-legacy -X "$ch" 2>/dev/null
        done
        iptables-legacy -F CHAOS-INPUT  2>/dev/null
        iptables-legacy -F CHAOS-OUTPUT 2>/dev/null
        iptables-legacy -X CHAOS-INPUT  2>/dev/null
        iptables-legacy -X CHAOS-OUTPUT 2>/dev/null
        # Wipe stray netem/tbf qdiscs on every interface except lo.
        for dev in $(ls /sys/class/net 2>/dev/null | grep -v "^lo$"); do
          tc qdisc del dev "$dev" root 2>/dev/null
        done
        true
      ' >/dev/null 2>&1
    done
  fi

  # 4b. Zombie CRDs (only if --crds given)
  if (( DO_CRDS )) && (( TOTAL_CRDS > 0 )); then
    say "  · stripping finalizers + deleting $TOTAL_CRDS chaos CRDs"
    for kind in networkchaos podchaos httpchaos stresschaos timechaos iochaos dnschaos kernelchaos; do
      (( ${CRD_COUNTS[$kind]} == 0 )) && continue
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        ns_="${line%/*}"; name_="${line#*/}"
        kubectl -n "$ns_" patch "$kind" "$name_" --type=merge \
          -p '{"metadata":{"finalizers":[]}}' >/dev/null 2>&1
      done < <(kubectl get "$kind" -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}')
      kubectl delete "$kind" -A --all --wait=false >/dev/null 2>&1
    done
  fi

  say "  ✓ fix done — re-run without --fix to verify"
  exit 0
else
  if (( DIRTY )); then
    echo "RESULT: DIRTY (CRDs=$TOTAL_CRDS, active_pods=${#ACTIVE_DIRTY_PODS[@]}, stale_pods=${#STALE_PODS[@]}). Re-run with --fix to clean."
    exit 1
  else
    if (( ${#STALE_PODS[@]} > 0 )); then
      echo "RESULT: CLEAN (with ${#STALE_PODS[@]} pods carrying harmless stale chains; use --fix to wipe them)."
    else
      echo "RESULT: CLEAN — safe to run experiment."
    fi
    exit 0
  fi
fi

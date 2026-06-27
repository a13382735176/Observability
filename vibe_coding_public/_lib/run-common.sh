# Shared run.sh library — sourced by every services/*/run.sh.
# Per-service run.sh must declare BEFORE sourcing this:
#   SERVICE_ID   - matches dir name, e.g. "01-catalog-api"
#   APP_LABEL    - kubernetes pod label, e.g. "catalog-api"
#   LANG         - one of python|go|java|csharp|cpp (only used for logging)
#   FAULTS       - bash array of fault ids, e.g. ("F01-pod-kill" "F02-network-delay")
# Per-service run.sh MAY optionally define:
#   cmd_smoke    - bash function that does a service-specific smoke test
#                  (default: curl /healthz via port-forward)
#   SMOKE_PATH   - if cmd_smoke is NOT overridden, this overrides default "/healthz"
#
# Per-service may also drop a sibling file `exercise.sh` that defines:
#   exercise_once <BASE_URL>   - one request cycle that touches the deps under
#                                test. Called repeatedly during the fault
#                                window so the judge has log signal to score.
# If exercise.sh is absent, the default exerciser just GETs SMOKE_PATH.

set -euo pipefail

# --- globals (resolved from caller's $HERE) ---
NAMESPACE="${NAMESPACE:-vibe-coding}"
IMAGE_TAG="${IMAGE_TAG:-vibe/${SERVICE_ID}:dev}"
KIND_CLUSTER="${KIND_CLUSTER:-vibe}"
RUNS_DIR="${RUNS_DIR:-$HERE/../../runs}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-420s}"
ROLLOUT_RETRIES="${ROLLOUT_RETRIES:-1}"
ROLLOUT_RETRY_SLEEP_S="${ROLLOUT_RETRY_SLEEP_S:-12}"
DOCKER_BUILD_RETRIES="${DOCKER_BUILD_RETRIES:-2}"
DOCKER_BUILD_RETRY_SLEEP_S="${DOCKER_BUILD_RETRY_SLEEP_S:-20}"
KIND_LOAD_RETRIES="${KIND_LOAD_RETRIES:-3}"
KIND_LOAD_RETRY_SLEEP_S="${KIND_LOAD_RETRY_SLEEP_S:-20}"
JUDGE_MODE="${JUDGE_MODE:-current}"
FAULT_WINDOW_SCALE="${FAULT_WINDOW_SCALE:-0.5}"
FAULT_WINDOW_MIN_S="${FAULT_WINDOW_MIN_S:-15}"

# Per-fault window in seconds. NetworkChaos/HTTPChaos have built-in duration;
# pod-kill is one-shot but we still wait so the new pod's startup logs land.
# The effective window is scaled by FAULT_WINDOW_SCALE. Default 0.5 makes the
# benchmark faster while preserving relative slow/fail fault durations.
declare -A FAULT_WINDOW=(
  ["F01-pod-kill"]=60
  ["F02-network-delay"]=120
  ["F03-upstream-fail"]=120
  ["F04-upstream-slow"]=120
  ["F05-db-down"]=75
  ["F06-db-slow"]=150
  ["F07-cache-down"]=75
  ["F08-cache-slow"]=150
  ["F09-queue-down"]=75
  ["F10-queue-slow"]=150
  ["F11-cpu-stress"]=120
  ["F12-net-corrupt"]=120
  ["F13-time-skew"]=120
  ["F14-mem-stress"]=120
  ["F15-dns-fail"]=90
)

if [[ "$(declare -p FAULTS 2>/dev/null || true)" != declare\ -a* ]]; then
  declare -a FAULTS=()
  if [[ -d "$HERE/faults" ]]; then
    while IFS= read -r yaml; do
      FAULTS+=("$(basename "$yaml" .yaml)")
    done < <(find "$HERE/faults" -maxdepth 1 -type f -name '*.yaml' -printf '%f\n' | sort)
  fi
fi

# --- helpers ---
log() { printf "[%s][%s] %s\n" "$(date -u +%H:%M:%S)" "$SERVICE_ID" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

now_iso()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
plus_iso() { date -u -d "@$(($(date +%s) + ${1}))" +%Y-%m-%dT%H:%M:%SZ; }

_fault_window_seconds() {
  local base="${1:-90}"
  awk -v base="$base" -v scale="$FAULT_WINDOW_SCALE" -v min_s="$FAULT_WINDOW_MIN_S" '
    BEGIN {
      window = int(base * scale + 0.5)
      if (window < min_s) window = min_s
      print window
    }
  '
}

# --- subcommands ---
cmd_help() {
  cat <<EOF
Usage: ./run.sh <subcommand>

Subcommands:
  build           docker build + kind load into cluster '${KIND_CLUSTER}'
  deploy          kubectl apply -f k8s/
  wait            kubectl rollout status (configurable timeout + retry)
  smoke           service-specific smoke test (default: curl /healthz)
  inject FAULT    apply chaos faults/FAULT.yaml, capture meta.json, wait window
  judge [RUN_TS]  run judge.py on the most recent run dir (or specific RUN_TS)
  cleanup         kubectl delete -f k8s/ + delete any leftover chaos CRDs
  capture         build + deploy + wait + smoke + inject every applicable fault; no judge
  demo            capture + judge (legacy convenience target)
  list-faults     print FAULTS for this service
  help            this message

Service: ${SERVICE_ID}   Lang: ${LANG}   App label: ${APP_LABEL}
Faults:  ${FAULTS[@]}
Timing:  FAULT_WINDOW_SCALE=${FAULT_WINDOW_SCALE} FAULT_WINDOW_MIN_S=${FAULT_WINDOW_MIN_S}
EOF
}

cmd_list-faults() {
  printf '%s\n' "${FAULTS[@]}"
}

cmd_build() {
  local build_flags="${DOCKER_BUILD_FLAGS:---pull=false}"
  local attempt=1
  local max_attempts=$((DOCKER_BUILD_RETRIES + 1))
  local rc=1

  while [[ "$attempt" -le "$max_attempts" ]]; do
    log "docker build attempt ${attempt}/${max_attempts}: $build_flags $IMAGE_TAG"
    set +e
    ( cd "$HERE" && docker build $build_flags -t "$IMAGE_TAG" . )
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      break
    fi
    if [[ "$attempt" -lt "$max_attempts" ]]; then
      log "docker build failed (rc=$rc); retrying in ${DOCKER_BUILD_RETRY_SLEEP_S}s"
      sleep "$DOCKER_BUILD_RETRY_SLEEP_S"
    fi
    attempt=$((attempt + 1))
  done
  [[ "$rc" -eq 0 ]] || return "$rc"

  attempt=1
  max_attempts=$((KIND_LOAD_RETRIES + 1))
  while [[ "$attempt" -le "$max_attempts" ]]; do
    log "kind load attempt ${attempt}/${max_attempts}: $IMAGE_TAG into cluster '$KIND_CLUSTER'"
    set +e
    kind load docker-image "$IMAGE_TAG" --name "$KIND_CLUSTER"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      return 0
    fi
    if [[ "$attempt" -lt "$max_attempts" ]]; then
      log "kind load failed (rc=$rc); retrying in ${KIND_LOAD_RETRY_SLEEP_S}s"
      sleep "$KIND_LOAD_RETRY_SLEEP_S"
    fi
    attempt=$((attempt + 1))
  done
  return "$rc"
}

cmd_deploy() {
  log "kubectl apply -f k8s/"
  kubectl apply -f "$HERE/k8s/"
}

_wait_rollout() {
  local deploy_ref="$1"
  local attempt=1
  local max_attempts=$((ROLLOUT_RETRIES + 1))
  local rc=1
  while [[ "$attempt" -le "$max_attempts" ]]; do
    log "waiting for rollout attempt ${attempt}/${max_attempts} (timeout=${ROLLOUT_TIMEOUT})"
    set +e
    kubectl -n "$NAMESPACE" rollout status "$deploy_ref" --timeout="$ROLLOUT_TIMEOUT"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      return 0
    fi

    kubectl -n "$NAMESPACE" get pods -l "app=$APP_LABEL" -o wide >&2 || true
    if [[ "$attempt" -lt "$max_attempts" ]]; then
      log "rollout still not ready (rc=$rc); retrying in ${ROLLOUT_RETRY_SLEEP_S}s"
      sleep "$ROLLOUT_RETRY_SLEEP_S"
    fi
    attempt=$((attempt + 1))
  done
  return "$rc"
}

cmd_wait() {
  _wait_rollout "deploy/$APP_LABEL"
}

# Default smoke: port-forward to 8080 inside cluster and curl SMOKE_PATH (default /healthz).
cmd_smoke() {
  local path="${SMOKE_PATH:-/healthz}"
  local pf_log
  pf_log="$(mktemp)"
  kubectl -n "$NAMESPACE" port-forward "deploy/$APP_LABEL" 0:8080 >"$pf_log" 2>&1 &
  local pf_pid=$!
  trap "kill $pf_pid 2>/dev/null || true; rm -f $pf_log" RETURN
  # Find the local port kubectl chose.
  local port=""
  for _ in $(seq 1 30); do
    sleep 0.3
    port="$(grep -oE 'Forwarding from 127.0.0.1:[0-9]+' "$pf_log" | head -1 | grep -oE '[0-9]+$' || true)"
    [[ -n "$port" ]] && break
  done
  [[ -n "$port" ]] || { cat "$pf_log" >&2; die "port-forward did not bind"; }
  log "smoke: curl http://127.0.0.1:$port$path"
  local http_code
  http_code=$(curl -sS --max-time 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port$path" 2>&1) || true
  if [[ "$http_code" =~ ^[45] ]]; then
    die "smoke failed: $path returned HTTP $http_code"
  fi
  log "smoke OK (HTTP $http_code)"
}

# Resolve target app label per fault primitive.
# F05-F10 are now NetworkChaos on the APP pod (parallel-safe) — target = APP_LABEL.
_target_for_fault() {
  case "$1" in
    F03-upstream-fail|F04-upstream-slow) echo "mock-upstream" ;;
    *) echo "$APP_LABEL" ;;
  esac
}

cmd_inject() {
  local fault="${1:-}"
  [[ -n "$fault" ]] || die "FAULT id required"
  local yaml="$HERE/faults/$fault.yaml"
  [[ -f "$yaml" ]] || die "no fault yaml at $yaml — is $fault in FAULTS for this service?"

  local base_window="${FAULT_WINDOW[$fault]:-90}"
  local window; window="$(_fault_window_seconds "$base_window")"
  local target; target="$(_target_for_fault "$fault")"

  # We always judge against OUR service's logs, even when the fault targets a dep.
  # That's what tests detection.
  local run_ts="${RUN_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
  local fault_dir="$RUNS_DIR/$SERVICE_ID/$run_ts/$fault"
  mkdir -p "$fault_dir"

  # Capture baseline pod restart counts BEFORE injection (for F01 detection).
  kubectl -n "$NAMESPACE" get pods -l "app=$APP_LABEL" -o json 2>/dev/null \
    | python3 -c '
import json,sys
j = json.load(sys.stdin)
out = {}
for it in j.get("items", []):
    out[it["metadata"]["name"]] = sum(int(cs.get("restartCount",0)) for cs in it.get("status",{}).get("containerStatuses",[]))
print(json.dumps(out))
' > "$fault_dir/pod_restarts_baseline.json" || echo "{}" > "$fault_dir/pod_restarts_baseline.json"

  local t_start; t_start="$(now_iso)"
  local t_end;   t_end="$(plus_iso "$window")"

  # Write meta.json
  cat > "$fault_dir/meta.json" <<EOF
{
  "service":     "$SERVICE_ID",
  "fault_id":    "$fault",
  "fault_yaml":  "$yaml",
  "namespace":   "$NAMESPACE",
  "app_label":   "$APP_LABEL",
  "target":      "$target",
  "t_start":     "$t_start",
  "t_end":       "$t_end",
  "duration_s":  $window,
  "buffer_s":    0
}
EOF

  log "inject $fault (target=$target window=${window}s) -> $fault_dir"
  kubectl apply -f "$yaml" >>"$fault_dir/inject.log" 2>&1

  # Start a background traffic generator against OUR service so the judge has
  # log signal to score. We rely on a port-forward into the pod; failures of
  # the curl/POST itself are expected and ignored.
  local traffic_pid=""
  local pf_pid="" pf_log=""
  if [[ "$fault" != F01* ]]; then
    pf_log="$(mktemp)"
    kubectl -n "$NAMESPACE" port-forward "deploy/$APP_LABEL" 0:8080 \
       >"$pf_log" 2>&1 &
    pf_pid=$!
    local port=""
    for _ in $(seq 1 30); do
      sleep 0.3
      port="$(grep -oE 'Forwarding from 127.0.0.1:[0-9]+' "$pf_log" | head -1 | grep -oE '[0-9]+$' || true)"
      [[ -n "$port" ]] && break
    done
    if [[ -n "$port" ]]; then
      log "traffic: hitting http://127.0.0.1:$port via exercise_once (every 1s)"
      _run_traffic_loop "http://127.0.0.1:$port" "$fault_dir" &
      traffic_pid=$!
    else
      log "traffic: port-forward did not bind, skipping exerciser"
    fi
  else
    log "traffic: skipped (F01 pod-kill — pod is gone)"
  fi

  log "sleeping ${window}s for fault to play out"
  sleep "$window"

  # Persist a log snapshot at fault-window end so judge does not depend on
  # future pod availability (pods may be replaced/cleaned before batch judge).
  kubectl -n "$NAMESPACE" logs -l "app=$APP_LABEL" \
    --all-containers=true --timestamps=true --prefix=true \
    "--since-time=$t_start" --tail=-1 >"$fault_dir/logs_snapshot.txt" 2>&1 || true
  kubectl -n "$NAMESPACE" get pods -l "app=$APP_LABEL" -o wide \
    >"$fault_dir/pods_snapshot.txt" 2>&1 || true

  # Tear down traffic + port-forward FIRST so cleanup is quiet.
  [[ -n "$traffic_pid" ]] && kill "$traffic_pid" 2>/dev/null || true
  [[ -n "$pf_pid" ]] && kill "$pf_pid" 2>/dev/null || true
  [[ -n "$pf_log" ]] && rm -f "$pf_log" || true
  wait 2>/dev/null || true

  # Merge synthetic access logs (generated by the exerciser) into the snapshot
  # so judge has request-level evidence even when app access middleware is absent.
  if [[ -s "$fault_dir/access.log" ]]; then
    {
      printf -- '--- synthetic access log (traffic loop) ---\n'
      sed 's/^/[access] /' "$fault_dir/access.log"
    } >>"$fault_dir/logs_snapshot.txt" 2>&1 || true
  fi

  # Best-effort cleanup of the CRD (network/http chaos have duration; pod-kill is one-shot).
  # Some delete calls can hang; cap wait time so one stuck cleanup does not block the whole run.
  timeout 20s kubectl delete -f "$yaml" --ignore-not-found=true >>"$fault_dir/inject.log" 2>&1 || true

  # F01 pod-kill: re-wait for OUR app pod to come back up.
  # F05/F07/F09 are now NetworkChaos partition — no pod was killed, no recovery wait needed.
  if [[ "$fault" == F01* ]]; then
    log "post-kill: waiting for $APP_LABEL rollout to recover"
    _wait_rollout "deploy/$APP_LABEL" || true
  fi

  log "injected $fault recorded at $fault_dir/meta.json"
  echo "$fault_dir"   # so callers can pipe
}

# Background traffic loop. Sources per-service exercise.sh if present;
# otherwise GETs SMOKE_PATH (default /healthz). All errors are swallowed —
# the point is to exercise the service, not to validate responses.
_run_traffic_loop() {
  # Drop strict modes so a single failed pipeline/grep does not kill the loop.
  set +eo pipefail
  local base="$1" out_dir="$2"
  local access_log="$out_dir/access.log"
  local exercise="$HERE/exercise.sh"
  if [[ -f "$exercise" ]]; then
    # shellcheck disable=SC1090
    source "$exercise"
  fi
  if ! declare -F exercise_once >/dev/null; then
    local path="${EXERCISE_PATH:-${SMOKE_PATH:-/healthz}}"
    exercise_once() {
      local probe
      probe="$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' "$1$path" 2>&1)"
      local rc=$?
      if [[ $rc -eq 0 ]]; then
        printf 'http_code=%s path=%s\n' "$probe" "$path"
      else
        printf 'curl_error=%s path=%s\n' "$probe" "$path"
      fi
      return $rc
    }
  fi
  local iter=0
  while true; do
    iter=$((iter + 1))
    local ts rc out method path code
    ts="$(date -u +%H:%M:%S)"
    out="$(exercise_once "$base" 2>&1)"
    rc=$?
    {
      printf -- '--- iter=%d ts=%s rc=%d ---\n' "$iter" "$ts" "$rc"
      [[ -n "$out" ]] && printf '%s\n' "$out"
    } >>"$out_dir/traffic.log" 2>&1

    {
      if [[ -n "$out" ]]; then
        while IFS= read -r line; do
          [[ -z "$line" ]] && continue
          printf 'ts=%s iter=%d rc=%d raw=%s\n' "$ts" "$iter" "$rc" "$line"

          method=""
          path=""
          code=""
          if [[ "$line" =~ ^(GET|POST|PUT|PATCH|DELETE)[[:space:]]+([^[:space:]]+) ]]; then
            method="${BASH_REMATCH[1]}"
            path="${BASH_REMATCH[2]}"
          fi
          if [[ "$line" =~ HTTP_CODE:?([0-9]{3}) ]]; then
            code="${BASH_REMATCH[1]}"
            if [[ -n "$method" && -n "$path" ]]; then
              printf 'ts=%s iter=%d access method=%s path=%s status %s rc=%d\n' \
                "$ts" "$iter" "$method" "$path" "$code" "$rc"
            else
              printf 'ts=%s iter=%d access status %s rc=%d line=%s\n' \
                "$ts" "$iter" "$code" "$rc" "$line"
            fi
          fi
        done <<< "$out"
      else
        printf 'ts=%s iter=%d rc=%d raw=<empty>\n' "$ts" "$iter" "$rc"
      fi
    } >>"$access_log" 2>&1

    sleep 1
  done
}

cmd_judge() {
  local run_ts="${1:-}"
  local base="$RUNS_DIR/$SERVICE_ID"
  if [[ -z "$run_ts" ]]; then
    run_ts="$(ls -1 "$base" 2>/dev/null | sort | tail -1)"
    [[ -n "$run_ts" ]] || die "no runs under $base"
  fi
  local run_dir="$base/$run_ts"
  [[ -d "$run_dir" ]] || die "no such run dir $run_dir"
  log "judging $run_dir (mode=$JUDGE_MODE)"
  python3 "$HERE/../../judge/judge.py" "$run_dir" --mode "$JUDGE_MODE"
}

cmd_cleanup() {
  log "kubectl delete -f k8s/"
  timeout 30s kubectl delete -f "$HERE/k8s/" --ignore-not-found=true || true
  # Sweep leftover chaos CRDs belonging to THIS service only (parallel-safe).
  for kind in podchaos networkchaos httpchaos stresschaos timechaos dnschaos; do
    kubectl -n "$NAMESPACE" get "$kind" -o name 2>/dev/null \
      | grep "${APP_LABEL}" \
      | while read -r obj; do
          timeout 20s kubectl -n "$NAMESPACE" delete "$obj" --ignore-not-found=true || true
        done || true
  done
}

cmd_verify() {
  # Lightweight smoke-only check: build → deploy → rollout → smoke → cleanup.
  # Does NOT inject any faults. Used after service creation to confirm the
  # service starts and responds correctly before running the full fault suite.
  cmd_build
  cmd_deploy
  cmd_wait
  sleep 3
  cmd_smoke
  cmd_cleanup
  log "verify OK (no faults injected)"
}

cmd_capture() {
  RUN_TS="${RUN_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
  export RUN_TS
  mkdir -p "$RUNS_DIR/$SERVICE_ID/$RUN_TS"
  cmd_build
  cmd_deploy
  cmd_wait
  sleep 5
  cmd_smoke || log "smoke failed; continuing anyway"
  for f in "${FAULTS[@]}"; do
    log "=== fault $f ==="
    cmd_inject "$f" || log "inject $f errored; continuing"
    sleep 2
  done
  log "capture complete at $RUNS_DIR/$SERVICE_ID/$RUN_TS (judge not run)"
}

cmd_demo() {
  cmd_capture
  cmd_judge "$RUN_TS"
}

# --- dispatch ---
main_dispatch() {
  local sub="${1:-help}"
  shift || true
  case "$sub" in
    build|deploy|wait|smoke|inject|judge|cleanup|capture|demo|verify|help|list-faults)
      "cmd_$sub" "$@" ;;
    *) die "unknown subcommand: $sub (try ./run.sh help)" ;;
  esac
}

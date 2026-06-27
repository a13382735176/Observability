#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Defaults
RUN_ID="agent-all-$(date -u +%Y%m%dT%H%M%SZ)"
PROMPTS="p_blind,p1_obs_hinted,p_fewshot"
if command -v nproc >/dev/null 2>&1; then
  CPU_COUNT="$(nproc)"
  WORKERS="$((CPU_COUNT * 2))"
  if [[ "$WORKERS" -lt 8 ]]; then WORKERS=8; fi
  if [[ "$WORKERS" -gt 64 ]]; then WORKERS=64; fi
else
  WORKERS=16
fi
MODEL="gpt-5.5"
AGENT_NAME="${OBS_COPILOT_AGENT:-}"
SKIP_EXISTING=1
SKIP_ZERO_GT=0
DRY_RUN=0
PREFLIGHT=1
LIST_MODELS=0
PREFLIGHT_ONLY=0
ALLOW_AGENT_TOOLS=0
AGENT_REPO_CONTEXT="none"
AGENT_TRACE=0
AGENT_WORKSPACE_MODE="original"
AGENT_SANITIZED_COPY_ROOT=""
REPO_PATH_OVERRIDES=()
REPO_SEARCH_ROOTS=()

usage() {
  cat <<'USAGE'
Usage:
  ./run_all_agent.sh [options]

Options:
  --run-id <id>                 Run id under results/ (default: agent-all-<UTC timestamp>)
  --prompts <csv>               Prompt levels (default: p_blind,p1_obs_hinted,p_fewshot)
  --workers <n>                 Parallel workers (default: min(max(2*CPU,8),64))
  --model <id>                  Single model id to run (default: gpt-5.5)
  --agent <name>                Optional custom Copilot agent name
  --allow-agent-tools           Allow Copilot agent tool calls during benchmark cells
  --agent-repo-context <mode>   none|related. related preflights related repo files while target file remains blocked
  --agent-workspace-mode <mode> original|sanitized-copy. sanitized-copy exposes a temporary stripped repo copy
  --agent-sanitized-copy-root <path>
                                Directory for temporary sanitized repo copies, e.g. /Data2/v-yongtao/obs-real-bench-tmp
  --agent-trace                 Write per-cell Copilot SDK event trace to agent_trace.json
  --repo-path-override <k=p>    Override repo root for instances; passed to tools.pilot. Can be repeated
  --repo-search-root <path>     Extra root for resolving stale repo.local_path values. Can be repeated
  --list-models                 List models available to current Copilot auth and exit
  --no-preflight                Skip one-call auth/model preflight check
  --preflight-only              Run preflight check and exit (no benchmark execution)
  --no-skip-existing            Re-run even if result.json already exists
  --skip-zero-gt                Locally skip instances whose GT obs-site count is 0 before agent calls
  --dry-run                     Pipeline dry-run (no LLM calls)
  -h, --help                    Show this help

Environment:
  OBS_AGENT_AUTH_TOKEN
  OBS_COPILOT_AGENT

Notes:
  - Runs with backend=agent + --agentic using a SINGLE model (default gpt-5.5).
  - No candidate probing / fallback is performed.
  - By default, performs one lightweight preflight call to fail fast when
    auth is missing or the model is unavailable.
  - Agent workspace defaults per-instance to instance.repo.local_path (configured in tools/pilot.py).
  - Guardrail: agent permission requests are blocked from reading the target file
    of the current instance (prevents direct ground-truth leakage).
  - Use --allow-agent-tools --agent-repo-context related --agent-trace to expose
    repo context, force a related-file preflight, and audit tool usage per cell.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      RUN_ID="$2"
      shift 2
      ;;
    --prompts)
      PROMPTS="$2"
      shift 2
      ;;
    --workers)
      WORKERS="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --agent)
      AGENT_NAME="$2"
      shift 2
      ;;
    --allow-agent-tools)
      ALLOW_AGENT_TOOLS=1
      shift
      ;;
    --agent-repo-context)
      AGENT_REPO_CONTEXT="$2"
      shift 2
      ;;
    --agent-workspace-mode)
      AGENT_WORKSPACE_MODE="$2"
      shift 2
      ;;
    --agent-sanitized-copy-root)
      AGENT_SANITIZED_COPY_ROOT="$2"
      shift 2
      ;;
    --agent-trace)
      AGENT_TRACE=1
      shift
      ;;
    --repo-path-override)
      REPO_PATH_OVERRIDES+=("$2")
      shift 2
      ;;
    --repo-search-root)
      REPO_SEARCH_ROOTS+=("$2")
      shift 2
      ;;
    --list-models)
      LIST_MODELS=1
      shift
      ;;
    --no-preflight)
      PREFLIGHT=0
      shift
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      PREFLIGHT=1
      shift
      ;;
    --no-skip-existing)
      SKIP_EXISTING=0
      shift
      ;;
    --skip-zero-gt)
      SKIP_ZERO_GT=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! [[ "$WORKERS" =~ ^[0-9]+$ ]] || [[ "$WORKERS" -lt 1 ]]; then
  echo "Invalid --workers: $WORKERS" >&2
  exit 1
fi
if [[ "$AGENT_REPO_CONTEXT" != "none" && "$AGENT_REPO_CONTEXT" != "related" ]]; then
  echo "Invalid --agent-repo-context: $AGENT_REPO_CONTEXT (expected none|related)" >&2
  exit 1
fi
if [[ "$AGENT_WORKSPACE_MODE" != "original" && "$AGENT_WORKSPACE_MODE" != "sanitized-copy" ]]; then
  echo "Invalid --agent-workspace-mode: $AGENT_WORKSPACE_MODE (expected original|sanitized-copy)" >&2
  exit 1
fi

if [[ -n "${OBS_AGENT_AUTH_TOKEN:-}" ]]; then
  echo "[run-all-agent] token env: detected (explicit)"
else
  echo "[run-all-agent] token env: not set; configure OBS_AGENT_AUTH_TOKEN if your agent backend requires it"
fi

if [[ "$LIST_MODELS" -eq 1 ]]; then
  echo "[run-all-agent] listing models available to current Copilot auth..."
  python - <<'PY'
import asyncio
import sys
from copilot import CopilotClient

async def main() -> int:
    try:
        async with CopilotClient() as client:
            parse_error = None
            ids = []
            try:
                models = await client.list_models()

                def _model_id(item):
                    return getattr(item, "id", None) or getattr(item, "model", None) or str(item)

                ids = sorted({_model_id(m) for m in models})
            except Exception as e:  # noqa: BLE001
                parse_error = e
                message = str(e).lower()
                # Older SDK builds can fail to parse billing metadata (e.g., missing multiplier).
                # Fall back to raw RPC payload and print only model ids.
                if "modelbilling" in message or "multiplier" in message:
                    raw = await client._client.request("models.list", {})
                    models_data = raw.get("models", []) if isinstance(raw, dict) else []
                    ids = sorted(
                        {
                            str(m.get("id"))
                            for m in models_data
                            if isinstance(m, dict) and m.get("id")
                        }
                    )
                    print(
                        "[run-all-agent] warning: SDK model parsing failed; using raw models.list fallback.",
                        file=sys.stderr,
                    )
                else:
                    raise parse_error
    except Exception as e:  # noqa: BLE001
        print("[run-all-agent] failed to list models:", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(
            "[run-all-agent] hint: authenticate first (OBS_AGENT_AUTH_TOKEN or Copilot CLI auth).",
            file=sys.stderr,
        )
        return 2

    print(f"MODEL_COUNT={len(ids)}")
    for mid in ids:
        print(mid)
    return 0

raise SystemExit(asyncio.run(main()))
PY
  exit $?
fi

if [[ "$PREFLIGHT" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
  echo "[run-all-agent] preflight: validating agent auth + model availability..."
  RUN_ALL_AGENT_MODEL="$MODEL" \
  RUN_ALL_AGENT_AGENT="$AGENT_NAME" \
  python - <<'PY'
import os
import sys
from tools import llm_client

model = os.environ.get("RUN_ALL_AGENT_MODEL", "gpt-5.5")
agent = os.environ.get("RUN_ALL_AGENT_AGENT") or None

try:
    reply = llm_client.call(
        "Reply with exactly: OK",
        model=model,
        backend="agent",
        agent=agent,
        max_retries=1,
        timeout=60,
    )
except Exception as e:  # noqa: BLE001
    print("[run-all-agent] preflight failed:", file=sys.stderr)
    print(f"  {e}", file=sys.stderr)
    print(
        "[run-all-agent] hint: authenticate first (e.g., OBS_AGENT_AUTH_TOKEN) "
        "or choose an available model with --model (e.g., gpt-4.1, claude-sonnet-4).",
        file=sys.stderr,
    )
    sys.exit(2)

print(f"[run-all-agent] preflight ok (model={model}, reply={reply.strip()[:40]!r})")
PY
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  echo "[run-all-agent] preflight-only requested; exiting without benchmark run."
  exit 0
fi

CMD=(
  python -m tools.pilot
  --all
  --prompts "$PROMPTS"
  --model "$MODEL"
  --backend agent
  --agentic
  --run-id "$RUN_ID"
  --workers "$WORKERS"
)

if [[ "$SKIP_EXISTING" -eq 1 ]]; then
  CMD+=(--skip-existing)
fi
if [[ "$SKIP_ZERO_GT" -eq 1 ]]; then
  CMD+=(--skip-zero-gt)
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
  CMD+=(--dry-run)
fi
if [[ -n "$AGENT_NAME" ]]; then
  CMD+=(--agent "$AGENT_NAME")
fi
if [[ "$ALLOW_AGENT_TOOLS" -eq 1 ]]; then
  CMD+=(--allow-agent-tools)
fi
if [[ "$AGENT_REPO_CONTEXT" != "none" ]]; then
  CMD+=(--agent-repo-context "$AGENT_REPO_CONTEXT")
fi
if [[ "$AGENT_WORKSPACE_MODE" != "original" ]]; then
  CMD+=(--agent-workspace-mode "$AGENT_WORKSPACE_MODE")
fi
if [[ -n "$AGENT_SANITIZED_COPY_ROOT" ]]; then
  CMD+=(--agent-sanitized-copy-root "$AGENT_SANITIZED_COPY_ROOT")
fi
if [[ "$AGENT_TRACE" -eq 1 ]]; then
  CMD+=(--agent-trace)
fi
for override in "${REPO_PATH_OVERRIDES[@]}"; do
  CMD+=(--repo-path-override "$override")
done
for search_root in "${REPO_SEARCH_ROOTS[@]}"; do
  CMD+=(--repo-search-root "$search_root")
done

echo "[run-all-agent] root=$ROOT_DIR"
echo "[run-all-agent] run_id=$RUN_ID"
echo "[run-all-agent] model=$MODEL"
echo "[run-all-agent] prompts=$PROMPTS"
echo "[run-all-agent] workers=$WORKERS"
echo "[run-all-agent] skip_zero_gt=$SKIP_ZERO_GT"
echo "[run-all-agent] preflight=$PREFLIGHT"
echo "[run-all-agent] allow_agent_tools=$ALLOW_AGENT_TOOLS"
echo "[run-all-agent] agent_repo_context=$AGENT_REPO_CONTEXT"
echo "[run-all-agent] agent_workspace_mode=$AGENT_WORKSPACE_MODE"
echo "[run-all-agent] agent_sanitized_copy_root=${AGENT_SANITIZED_COPY_ROOT:-<default>}"
echo "[run-all-agent] agent_trace=$AGENT_TRACE"
if [[ "${#REPO_PATH_OVERRIDES[@]}" -gt 0 ]]; then
  echo "[run-all-agent] repo_path_overrides=${REPO_PATH_OVERRIDES[*]}"
fi
if [[ "${#REPO_SEARCH_ROOTS[@]}" -gt 0 ]]; then
  echo "[run-all-agent] repo_search_roots=${REPO_SEARCH_ROOTS[*]}"
fi
echo "[run-all-agent] executing:"
printf '  %q' "${CMD[@]}"
echo

"${CMD[@]}"

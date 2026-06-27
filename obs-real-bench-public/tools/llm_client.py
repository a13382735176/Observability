"""
LLM client wrapper.

The API backend loads a CloudGPT-compatible helper from the path specified by
`OBS_CLOUDGPT_HELPER`.

We load the helper ONCE on first call, build the client ONCE, and reuse both.
Thread-safe: the OpenAI sync client itself is safe under concurrent use; we
just protect first-time client construction with a lock so concurrent
workers don't race the Azure CLI login.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import importlib.util
import json
import os
import re
import shutil
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional


_CLOUDGPT_PY = Path(os.environ.get("OBS_CLOUDGPT_HELPER", "cloudgpt_helper.py"))

ENV_BACKEND = "OBS_LLM_BACKEND"
ENV_AGENT_NAME = "OBS_COPILOT_AGENT"
ENV_AGENT_TOKEN = "OBS_AGENT_AUTH_TOKEN"
ENV_AGENT_WORKSPACE = "OBS_COPILOT_WORKING_DIRECTORY"
ENV_AGENTIC = "OBS_COPILOT_AGENTIC"
ENV_DISABLE_AGENT_TOOLS = "OBS_COPILOT_DISABLE_TOOLS"
ENV_AGENT_TRACE = "OBS_COPILOT_TRACE"
ENV_AGENT_REPO_CONTEXT = "OBS_COPILOT_REPO_CONTEXT"
DEFAULT_BACKEND = "api"

_BENCHMARK_AGENT_SYSTEM_MESSAGE = (
    "You are a code transformation engine for benchmark evaluation. "
    "Return only the final answer, with no analysis or planning. "
    "Do not describe steps. Do not ask questions. "
    "Output exactly one fenced code block that contains only the requested function definition."
)

_PLANNING_PREFIXES = (
    "i need to",
    "i should",
    "let me",
    "i'm considering",
    "i am considering",
    "the user wants",
    "first,",
    "i will",
)

# module-level caches + their build lock.
# RLock (not Lock) because _get_client() acquires the lock and then calls
# _load_helper(), which also acquires it — that would self-deadlock with a
# plain threading.Lock since it is not reentrant.
_helper_mod: Any = None
_client: Any = None
_init_lock = threading.RLock()


def _load_helper() -> Any:
    global _helper_mod
    if _helper_mod is not None:
        return _helper_mod
    with _init_lock:
        if _helper_mod is not None:
            return _helper_mod
        spec = importlib.util.spec_from_file_location("cloudgpt_helper", _CLOUDGPT_PY)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load helper from {_CLOUDGPT_PY}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _helper_mod = mod
        return mod


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    with _init_lock:
        if _client is not None:
            return _client
        helper = _load_helper()
        _client = helper.get_openai_client(use_azure_cli=True)
        return _client


def resolve_backend(backend: Optional[str] = None) -> str:
    """Normalize backend names to one of: api | agent."""
    raw = (backend or os.environ.get(ENV_BACKEND, DEFAULT_BACKEND)).strip().lower()
    aliases = {
        "api": "api",
        "openai": "api",
        "responses": "api",
        "agent": "agent",
        "copilot": "agent",
        "copilot-agent": "agent",
        "copilot_agent": "agent",
    }
    resolved = aliases.get(raw)
    if resolved is None:
        allowed = "api, agent"
        raise ValueError(f"Unknown backend {raw!r}. Allowed values: {allowed}")
    return resolved


def prewarm(*, backend: Optional[str] = None) -> None:
    """Force backend initialization now (use before dispatching worker threads)."""
    if resolve_backend(backend) == "api":
        _get_client()
        return
    _import_copilot_sdk()


# Default model for local experiments.
DEFAULT_MODEL = "gpt-5.5-20260424"

# Other useful presets (see 12.py for the full list):
KNOWN_MODELS = {
    "gpt-5.5":           "gpt-5.5-20260424",
    "gpt-5.4":           "gpt-5.4-20240305",
    "gpt-5.4-pro":       "gpt-5.4-pro-20260305",
    "gpt-5.4-mini":      "gpt-5.4-mini-20260317",
    "gpt-5.3-codex":     "gpt-5.3-codex-20260224",
    "gpt-5.1-codex-max": "gpt-5.1-codex-max-20251204",
    "o3":                "o3-20250416",
    "o3-pro":            "o3-pro-20250610",
}


def resolve(model: str) -> str:
    return KNOWN_MODELS.get(model, model)


def _call_api(
    prompt: str,
    *,
    model: str,
    max_retries: int,
    timeout: float,
) -> str:
    """Send `prompt` and return the assistant's text response.

    `timeout` is a per-request wall-clock cap (seconds). Without it a stalled
    LLM call would hang the pilot indefinitely. Default 240s is generous for
    a single ~200-line completion (we have observed individual calls up to
    ~170s on slow days); we still retry up to `max_retries`.
    """
    client = _get_client()
    last_exc: Optional[BaseException] = None
    for _ in range(max_retries):
        try:
            resp = client.with_options(timeout=timeout).responses.create(
                model=resolve(model), input=prompt
            )
            if hasattr(resp, "output_text") and resp.output_text:
                return resp.output_text
            if hasattr(resp, "output"):
                try:
                    return str(resp.output[0].get("content", ""))
                except Exception:
                    return str(resp.output)
            return str(resp)
        except Exception as e:  # noqa: BLE001
            last_exc = e
    assert last_exc is not None
    raise last_exc


def _import_copilot_sdk() -> tuple[Any, Any, Any]:
    """Import Copilot SDK lazily so default API mode has zero extra deps."""
    try:
        from copilot import CopilotClient
        from copilot.session import PermissionHandler, PermissionRequestResult
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Agent backend requires github-copilot-sdk. "
            "Install it with `pip install github-copilot-sdk`."
        ) from e
    return CopilotClient, PermissionHandler, PermissionRequestResult


def _extract_text(payload: Any) -> str:
    """Best-effort text extraction across SDK/OpenAI response shapes."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (list, tuple)):
        chunks = [_extract_text(item).strip() for item in payload]
        chunks = [c for c in chunks if c]
        return "\n".join(chunks)
    if isinstance(payload, dict):
        for key in ("content", "text", "output_text", "message", "data", "output"):
            if key in payload:
                txt = _extract_text(payload[key]).strip()
                if txt:
                    return txt
        return ""

    # Objects: common SDK event/response containers.
    for attr in (
        "output_text",
        "content",
        "text",
        "delta_content",
        "message",
        "value",
    ):
        if hasattr(payload, attr):
            txt = _extract_text(getattr(payload, attr)).strip()
            if txt:
                return txt
    # Keep reasoning text as last resort only. It should never override
    # final assistant message content for benchmark outputs.
    if hasattr(payload, "reasoning_text"):
        txt = _extract_text(getattr(payload, "reasoning_text")).strip()
        if txt:
            return txt
    if hasattr(payload, "data"):
        txt = _extract_text(getattr(payload, "data")).strip()
        if txt:
            return txt
    if hasattr(payload, "output"):
        txt = _extract_text(getattr(payload, "output")).strip()
        if txt:
            return txt
    return ""


def _event_type_str(event: Any) -> str:
    """Return a normalized event type string (handles Enum and plain str)."""
    typ = getattr(event, "type", "")
    if typ is None:
        return ""
    value = getattr(typ, "value", typ)
    return str(value).strip().lower()


def _is_tool_event_type(type_name: str) -> bool:
    return (
        type_name.startswith("tool.")
        or type_name.startswith("external_tool.")
        or type_name in ("command.execute", "command.completed")
    )


def _to_jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item, depth=depth + 1) for key, item in value.items()}
    if dataclasses.is_dataclass(value):
        return {
            field.name: _to_jsonable(getattr(value, field.name), depth=depth + 1)
            for field in dataclasses.fields(value)
        }
    if hasattr(value, "to_dict"):
        try:
            return _to_jsonable(value.to_dict(), depth=depth + 1)
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "__dict__"):
        return {
            key: _to_jsonable(item, depth=depth + 1)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


def _event_record(event: Any) -> dict[str, Any]:
    return {
        "type": _event_type_str(event),
        "data": _to_jsonable(getattr(event, "data", None)),
    }


def _write_agent_trace(
    path: str,
    *,
    prompt: str,
    answer: str,
    events: list[Any],
    workspace: Optional[str],
    forbidden_paths: Optional[list[str]],
    preflight_prompt: Optional[str],
) -> None:
    trace_path = Path(path).expanduser().resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    event_records = [_event_record(event) for event in events]
    event_types = [record["type"] for record in event_records]
    tool_events = [record for record in event_records if _is_tool_event_type(record["type"])]
    permission_events = [record for record in event_records if record["type"].startswith("permission.")]
    payload = {
        "prompt": prompt,
        "preflight_prompt": preflight_prompt,
        "answer": answer,
        "workspace": workspace,
        "forbidden_paths": forbidden_paths or [],
        "events_total": len(events),
        "event_types_unique": sorted(set(event_types)),
        "tool_events_total": len(tool_events),
        "permission_events_total": len(permission_events),
        "events": event_records,
    }
    trace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _referenced_file_paths(prompt: str) -> list[str]:
    paths: list[str] = []
    for pattern in (
        r"File:\s*`([^`]+)`",
        r"file:\s*`([^`]+)`",
        r"Path:\s*`([^`]+)`",
        r"path:\s*`([^`]+)`",
    ):
        for match in re.finditer(pattern, prompt):
            candidate = match.group(1).strip()
            if candidate and candidate not in paths:
                paths.append(candidate)
    return paths


def _display_forbidden_paths(
    forbidden_paths: Optional[list[str]],
    *,
    workspace: str,
) -> list[str]:
    workspace_path = Path(workspace).expanduser().resolve()
    paths: list[str] = []
    for raw in forbidden_paths or []:
        if not raw:
            continue
        path = Path(str(raw).strip()).expanduser()
        if not path.is_absolute():
            path = workspace_path / path
        resolved = path.resolve()
        try:
            display = resolved.relative_to(workspace_path).as_posix()
        except ValueError:
            display = str(resolved)
        if display and display not in paths:
            paths.append(display)
    return paths


def _build_related_repo_preflight_prompt(
    prompt: str,
    workspace: str,
    *,
    forbidden_paths: Optional[list[str]] = None,
) -> str:
    paths = _display_forbidden_paths(forbidden_paths, workspace=workspace)
    if not paths:
        paths = _referenced_file_paths(prompt)
    if paths:
        path_lines = "\n".join(f"- {path}" for path in paths)
        target = (
            "The current instance's target file(s) are blocked by policy. "
            "Do NOT open, view, grep, cat, or otherwise inspect their contents:\n"
            f"{path_lines}\n"
            "Use repository tools only within this instance's workspace to inspect other nearby "
            "or related files for project conventions relevant to the task, existing helper APIs, "
            "and similar non-target implementations."
        )
    else:
        target = (
            "Use repository tools only within this instance's workspace and identify non-target "
            "files relevant to the user's task."
        )
    return (
        "Repository-context preflight for benchmark evaluation.\n"
        f"Workspace root: {workspace}\n"
        f"{target}\n"
        "This is only preparation for the next user request. After using tools, reply with exactly: READY"
    )


def _extract_text_from_events(events: list[Any]) -> str:
    """Best-effort extraction from session events when send_and_wait returns None."""
    if not events:
        return ""

    # Prefer final assistant message payload when present.
    for event in reversed(events):
        if _event_type_str(event) == "assistant.message":
            txt = _extract_text(getattr(event, "data", None)).strip()
            if txt:
                return txt

    # Some SDK/runtime combinations only emit message deltas before session.idle.
    # Stitch deltas together to recover the full response body.
    delta_chunks: list[str] = []
    for event in events:
        et = _event_type_str(event)
        if et == "assistant.message_delta":
            txt = _extract_text(getattr(event, "data", None)).strip()
            if txt:
                delta_chunks.append(txt)
    if delta_chunks:
        stitched = "".join(delta_chunks).strip()
        if stitched:
            return stitched

    # Secondary fallback for other assistant event shapes.
    for event in reversed(events):
        et = _event_type_str(event)
        if et in ("assistant.reasoning", "assistant.usage", "assistant.turn_end"):
            continue
        if et.startswith("assistant."):
            txt = _extract_text(getattr(event, "data", None)).strip()
            if txt:
                return txt

    # IMPORTANT: do NOT scan non-assistant events here.
    # Returning user/system event payloads can accidentally surface the input
    # prompt as if it were a model response.
    return ""


def _pick_agent_token() -> Optional[str]:
    """Pick the first available GitHub auth token for Copilot SDK."""
    for key in (ENV_AGENT_TOKEN,):
        token = os.environ.get(key)
        if token:
            return token
    token = _token_from_gh_cli()
    if token:
        return token
    return _token_from_gh_hosts_file()


def _token_from_gh_cli() -> Optional[str]:
    """Read GitHub CLI auth without printing the secret."""
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        return None
    if result.returncode != 0:
        return None
    token = result.stdout.strip()
    return token or None


def _token_from_gh_hosts_file() -> Optional[str]:
    """Small fallback for the common GitHub CLI hosts.yml token location."""
    hosts_file = Path.home() / ".config" / "gh" / "hosts.yml"
    if not hosts_file.exists():
        return None
    try:
        for line in hosts_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("oauth_token:"):
                token = stripped.split(":", 1)[1].strip()
                return token or None
    except Exception:  # noqa: BLE001
        return None
    return None


def _is_truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes", "on")


def _looks_like_planning_text(text: str) -> bool:
    low = text.strip().lower()
    if not low:
        return False
    if "```" in low:
        return False
    return any(low.startswith(prefix) for prefix in _PLANNING_PREFIXES)


def _wire_agent_token(
    CopilotClient: Any,
    *,
    token: Optional[str],
    client_kwargs: dict[str, Any],
    session_kwargs: dict[str, Any],
) -> None:
    """Attach token to whichever surface the installed SDK exposes.

    SDKs differ by version:
    - some accept token in CopilotClient(...)
    - some accept token in create_session(...)
    - some only auto-read environment variables
    """
    if not token:
        return

    try:
        init_params = set(inspect.signature(CopilotClient.__init__).parameters)
    except Exception:  # noqa: BLE001
        init_params = set()

    # Python SDK usually uses snake_case; keep camelCase fallback for safety.
    if "github_token" in init_params:
        client_kwargs["github_token"] = token
        return
    if "gitHubToken" in init_params:
        client_kwargs["gitHubToken"] = token
        return

    try:
        create_params = set(inspect.signature(CopilotClient.create_session).parameters)
    except Exception:  # noqa: BLE001
        create_params = set()

    if "github_token" in create_params:
        session_kwargs["github_token"] = token
        return
    if "gitHubToken" in create_params:
        session_kwargs["gitHubToken"] = token
        return

    # Old/future fallback: expose the auth value through the public benchmark
    # variable that the runtime may auto-detect.
    os.environ.setdefault(ENV_AGENT_TOKEN, token)


def _wire_single_turn_behavior(
    CopilotClient: Any,
    *,
    session_kwargs: dict[str, Any],
) -> None:
    """Force best-effort single-turn completion when SDK supports it.

    Some agent runtimes may ask interactive follow-up questions (user_input).
    For benchmark determinism, auto-answer with a fixed instruction so the
    model must finish in the same call.
    """
    try:
        create_params = set(inspect.signature(CopilotClient.create_session).parameters)
    except Exception:  # noqa: BLE001
        create_params = set()

    if "on_user_input_request" in create_params:

        def _single_turn_user_input_handler(_: Any, __: dict[str, str]) -> dict[str, Any]:
            return {
                "answer": (
                    "No follow-up questions are allowed in this benchmark. "
                    "Use repository context, make minimal reasonable assumptions, "
                    "and return the complete final answer now."
                ),
                "wasFreeform": True,
            }

        session_kwargs["on_user_input_request"] = _single_turn_user_input_handler


def _iter_strings(obj: Any) -> Iterable[str]:
    """Yield nested string leaves from arbitrary request payloads."""
    if obj is None:
        return
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _iter_strings(key)
            yield from _iter_strings(value)
        return
    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            yield from _iter_strings(item)
        return

    # Dataclass-like / SDK objects.
    if hasattr(obj, "to_dict"):
        try:
            yield from _iter_strings(obj.to_dict())
            return
        except Exception:  # noqa: BLE001
            pass

    for attr in (
        "path",
        "file_name",
        "filePath",
        "full_command_text",
        "command",
        "args",
        "value",
        "text",
    ):
        if hasattr(obj, attr):
            try:
                yield from _iter_strings(getattr(obj, attr))
            except Exception:  # noqa: BLE001
                continue


def _norm_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _build_permission_handler(
    PermissionHandler: Any,
    PermissionRequestResult: Any,
    *,
    forbidden_paths: Optional[list[str]],
    workspace: Optional[str],
) -> Any:
    """Create a permission handler that rejects requests touching forbidden files."""
    if not forbidden_paths:
        return PermissionHandler.approve_all

    workspace_abs = _norm_path(workspace) if workspace else None
    forbidden_abs: set[str] = set()
    forbidden_rel: set[str] = set()
    markers: set[str] = set()

    for raw in forbidden_paths:
        if not raw:
            continue
        text = str(raw).strip()
        if not text:
            continue

        if os.path.isabs(text):
            abs_path = _norm_path(text)
        elif workspace_abs:
            abs_path = _norm_path(str(Path(workspace_abs) / text))
        else:
            abs_path = _norm_path(text)

        forbidden_abs.add(abs_path)
        markers.add(abs_path.lower().replace("\\", "/"))

        if workspace_abs:
            try:
                rel = os.path.relpath(abs_path, workspace_abs)
                if not rel.startswith(".."):
                    rel_norm = Path(rel).as_posix().lower()
                    forbidden_rel.add(rel_norm)
                    markers.add(rel_norm)
                    markers.add(f"./{rel_norm}")
            except Exception:  # noqa: BLE001
                pass

    def _candidate_abs(path_text: str) -> str:
        if os.path.isabs(path_text):
            return _norm_path(path_text)
        if workspace_abs:
            return _norm_path(str(Path(workspace_abs) / path_text))
        return _norm_path(path_text)

    def _handler(request: Any, invocation: dict[str, str]) -> Any:
        try:
            kind_text = str(getattr(request, "kind", "")).lower()
            # For benchmark integrity, disallow shell and write permissions.
            # This prevents wildcard/indirect reads of blocked files and keeps
            # source repos immutable during runs.
            if "shell" in kind_text or "write" in kind_text:
                return PermissionRequestResult(kind="reject")

            payloads = (
                getattr(request, "path", None),
                getattr(request, "file_name", None),
                getattr(request, "possible_paths", None),
                getattr(request, "full_command_text", None),
                getattr(request, "commands", None),
                getattr(request, "args", None),
                getattr(request, "tool_args", None),
                invocation,
            )

            for raw in payloads:
                for token in _iter_strings(raw):
                    text = token.strip()
                    if not text:
                        continue

                    normalized_text = text.lower().replace("\\", "/")
                    if any(marker in normalized_text for marker in markers):
                        return PermissionRequestResult(kind="reject")

                    if "/" in text or text.startswith(".") or os.path.isabs(text):
                        abs_candidate = _candidate_abs(text)
                        if abs_candidate in forbidden_abs:
                            return PermissionRequestResult(kind="reject")
                        if workspace_abs:
                            try:
                                rel = os.path.relpath(abs_candidate, workspace_abs)
                                rel_norm = Path(rel).as_posix().lower()
                                if not rel.startswith("..") and rel_norm in forbidden_rel:
                                    return PermissionRequestResult(kind="reject")
                            except Exception:  # noqa: BLE001
                                pass
        except Exception:  # noqa: BLE001
            # Fail closed for benchmark integrity if permission parsing changes.
            return PermissionRequestResult(kind="reject")

        return PermissionHandler.approve_all(request, invocation)

    return _handler


def _reject_all_permissions(_: Any, __: dict[str, str]) -> Any:
    _, _, PermissionRequestResult = _import_copilot_sdk()
    return PermissionRequestResult(kind="reject")


async def _call_agent_once(
    prompt: str,
    *,
    model: str,
    timeout: float,
    agent: Optional[str],
    agent_disable_tools: bool,
    agent_workspace: Optional[str],
    agentic: bool,
    agent_forbidden_paths: Optional[list[str]],
    agent_trace_path: Optional[str],
    agent_repo_context: str,
) -> str:
    CopilotClient, PermissionHandler, PermissionRequestResult = _import_copilot_sdk()

    # Keep agent model IDs as user-specified strings. API alias resolution
    # is Azure-helper specific and can incorrectly pin Copilot runs to
    # dated IDs the account does not expose.
    agent_model = (model or "").strip()
    if not agent_model:
        agent_model = "gpt-4.1"

    session_kwargs: dict[str, Any] = {
        "model": agent_model,
    }
    selected_agent = agent or os.environ.get(ENV_AGENT_NAME)
    if selected_agent:
        session_kwargs["agent"] = selected_agent

    selected_workspace = agent_workspace or os.environ.get(ENV_AGENT_WORKSPACE)
    effective_agentic = agentic or _is_truthy(os.environ.get(ENV_AGENTIC))
    if not selected_workspace and effective_agentic:
        # Agentic mode should have repo visibility by default.
        selected_workspace = os.getcwd()
    if selected_workspace:
        selected_workspace = str(Path(selected_workspace).expanduser().resolve())
        session_kwargs["working_directory"] = selected_workspace

    selected_repo_context = (
        agent_repo_context
        or os.environ.get(ENV_AGENT_REPO_CONTEXT, "none")
        or "none"
    ).strip().lower()
    if selected_repo_context not in ("none", "related"):
        raise ValueError("agent_repo_context must be one of: none, related")

    # In benchmark mode we want API-like deterministic behavior by default:
    # no tool workflow, no planning chatter, final answer only.
    if not agentic:
        system_content = _BENCHMARK_AGENT_SYSTEM_MESSAGE
        if selected_workspace:
            system_content += (
                f" The workspace directory for this session is {selected_workspace}."
                " When the user says workspace, current workspace, or repo, use this exact directory."
                " Do not assume /workspace."
            )
        if selected_repo_context == "related":
            system_content += (
                " When repository-context preflight is requested, inspect related repository files "
                "in the resolved workspace for this instance, but do not open current instance "
                "target file(s) blocked by the permission policy."
            )
        session_kwargs["system_message"] = {
            "mode": "replace",
            "content": system_content,
        }
        session_kwargs["enable_config_discovery"] = False
        session_kwargs["include_sub_agent_streaming_events"] = bool(agent_trace_path)

    disable_tools = agent_disable_tools
    if ENV_DISABLE_AGENT_TOOLS in os.environ:
        disable_tools = _is_truthy(os.environ.get(ENV_DISABLE_AGENT_TOOLS))

    if disable_tools:
        session_kwargs["available_tools"] = []
        session_kwargs["on_permission_request"] = _reject_all_permissions
    else:
        session_kwargs["on_permission_request"] = _build_permission_handler(
            PermissionHandler,
            PermissionRequestResult,
            forbidden_paths=agent_forbidden_paths,
            workspace=selected_workspace,
        )

    client_kwargs: dict[str, Any] = {}
    github_token = _pick_agent_token()
    _wire_agent_token(
        CopilotClient,
        token=github_token,
        client_kwargs=client_kwargs,
        session_kwargs=session_kwargs,
    )
    _wire_single_turn_behavior(
        CopilotClient,
        session_kwargs=session_kwargs,
    )

    async with CopilotClient(**client_kwargs) as client:
        try:
            session_obj = await client.create_session(**session_kwargs)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "Model" in msg and "is not available" in msg:
                raise RuntimeError(
                    f"Agent backend model {agent_model!r} is not available for this Copilot account. "
                    "Authentication appears to be working, but this specific model is not enabled "
                    "for your plan/account. Try another model, for example: gpt-4.1 or claude-sonnet-4."
                ) from e
            if "401" in msg and (
                "Copilot user info" in msg
                or "session.create" in msg
                or "Unauthorized" in msg
            ):
                raise RuntimeError(
                    "Agent backend authentication failed (401). "
                    "Your GitHub token may be invalid, expired, or missing required permissions."
                ) from e
            raise

        async with session_obj as session:
            if not hasattr(session, "send_and_wait"):
                raise RuntimeError(
                    "Installed Copilot SDK does not expose send_and_wait(). "
                    "Please upgrade github-copilot-sdk."
                )

            observed_events: list[Any] = []

            def _capture(event: Any) -> None:
                observed_events.append(event)

            unsubscribe = session.on(_capture)

            preflight_prompt: Optional[str] = None
            try:
                if selected_repo_context == "related" and selected_workspace:
                    preflight_prompt = _build_related_repo_preflight_prompt(
                        prompt,
                        selected_workspace,
                        forbidden_paths=agent_forbidden_paths,
                    )
                    await session.send_and_wait(preflight_prompt, timeout=timeout)
                response = await session.send_and_wait(prompt, timeout=timeout)
                if agent_trace_path and hasattr(session, "get_events"):
                    all_events = await session.get_events()
                    if all_events:
                        observed_events = list(all_events)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "Session was not created with authentication info" in msg:
                    raise RuntimeError(
                        "Agent backend authentication is missing. "
                        "Provide agent authentication via OBS_AGENT_AUTH_TOKEN "
                        "or install Copilot CLI and run `copilot auth login`."
                    ) from e
                raise
            finally:
                unsubscribe()

            text = _extract_text(response).strip()
            if text:
                if _looks_like_planning_text(text):
                    raise RuntimeError(
                        "Agent backend returned planning text instead of final code output."
                    )
                if agent_trace_path:
                    _write_agent_trace(
                        agent_trace_path,
                        prompt=prompt,
                        answer=text,
                        events=observed_events,
                        workspace=selected_workspace,
                        forbidden_paths=agent_forbidden_paths,
                        preflight_prompt=preflight_prompt,
                    )
                return text

            msg = _extract_text_from_events(observed_events)
            if msg:
                if _looks_like_planning_text(msg):
                    raise RuntimeError(
                        "Agent backend returned planning text instead of final code output."
                    )
                if agent_trace_path:
                    _write_agent_trace(
                        agent_trace_path,
                        prompt=prompt,
                        answer=msg,
                        events=observed_events,
                        workspace=selected_workspace,
                        forbidden_paths=agent_forbidden_paths,
                        preflight_prompt=preflight_prompt,
                    )
                return msg

            # Include compact event-type context to aid debugging SDK behavior.
            event_types = [_event_type_str(e) for e in observed_events[-12:]]
            if event_types:
                raise RuntimeError(
                    "Agent backend returned an empty response "
                    f"(recent event types: {event_types})."
                )

    raise RuntimeError("Agent backend returned an empty response.")


def _call_agent(
    prompt: str,
    *,
    model: str,
    max_retries: int,
    timeout: float,
    agent: Optional[str],
    agent_disable_tools: bool,
    agent_workspace: Optional[str],
    agentic: bool,
    agent_forbidden_paths: Optional[list[str]],
    agent_trace_path: Optional[str],
    agent_repo_context: str,
) -> str:
    last_exc: Optional[BaseException] = None
    current_prompt = prompt
    for _ in range(max_retries):
        try:
            return asyncio.run(
                _call_agent_once(
                    current_prompt,
                    model=model,
                    timeout=timeout,
                    agent=agent,
                    agent_disable_tools=agent_disable_tools,
                    agent_workspace=agent_workspace,
                    agentic=agentic,
                    agent_forbidden_paths=agent_forbidden_paths,
                    agent_trace_path=agent_trace_path,
                    agent_repo_context=agent_repo_context,
                )
            )
        except Exception as e:  # noqa: BLE001
            last_exc = e
            lower_msg = str(e).lower()
            # This is deterministic (not transient), so retries only waste time.
            if "model" in lower_msg and "not available" in lower_msg:
                raise
            if "planning text instead of final code output" in lower_msg:
                current_prompt = (
                    prompt
                    + "\n\n[Hard requirement] Respond now with exactly one fenced code block containing only the target function. "
                    + "No analysis, no tool narration, no planning text."
                )
    assert last_exc is not None
    raise last_exc


def call(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_retries: int = 2,
    timeout: float = 240.0,
    backend: Optional[str] = None,
    agent: Optional[str] = None,
    agent_disable_tools: bool = True,
    agent_workspace: Optional[str] = None,
    agentic: bool = False,
    agent_forbidden_paths: Optional[list[str]] = None,
    agent_trace_path: Optional[str] = None,
    agent_repo_context: str = "none",
) -> str:
    """Send `prompt` and return the assistant's text response.

    Backends:
    - api   : CloudGPT-compatible helper configured by OBS_CLOUDGPT_HELPER
    - agent : GitHub Copilot SDK session (agent runtime)
    """
    selected = resolve_backend(backend)
    if selected == "api":
        return _call_api(
            prompt,
            model=model,
            max_retries=max_retries,
            timeout=timeout,
        )
    return _call_agent(
        prompt,
        model=model,
        max_retries=max_retries,
        timeout=timeout,
        agent=agent,
        agent_disable_tools=agent_disable_tools,
        agent_workspace=agent_workspace,
        agentic=agentic,
        agent_forbidden_paths=agent_forbidden_paths,
        agent_trace_path=agent_trace_path or os.environ.get(ENV_AGENT_TRACE),
        agent_repo_context=agent_repo_context,
    )

"""
obs-real-bench pilot orchestrator.

End-to-end for ONE instance × ONE prompt level × ONE model:

    instance JSON
        -> read ground-truth source from local repo
        -> strip obs in target function -> stripped source
        -> render prompt (p_blind | p1_obs_hinted | p_fewshot)
        -> validate forbid list
        -> call LLM -> raw response
        -> extract python code block -> llm_source
        -> extract ObsSites from {ground_truth, llm_source} restricted to fn
        -> score (precision / recall / F1)
        -> persist to results/<run_id>/<instance>/<prompt>/<model>/result.json

CLI:

    python -m tools.pilot --dry-run --instance otel-demo__py__recommendation__ListRecommendations
        # strip + extract only, no LLM call. Prints stripped source and gt sites.

    python -m tools.pilot --instance <id> --prompt p_fewshot --model gpt-5.5
        # full pipeline, one shot.

    python -m tools.pilot --all --prompts p_blind,p1_obs_hinted,p_fewshot --model gpt-5.5
        # full pipeline over every instance × listed prompts (the canonical 3-rung ladder).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

# bootstrap so `python tools/pilot.py` works (not just `python -m tools.pilot`)
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from tools import extract as extract_pkg            # noqa: E402
from tools import function_io                       # noqa: E402
from tools import llm_client, prompt_render, score, ts_obs  # noqa: E402
from tools.score_anchor import score_anchor         # noqa: E402
from tools.strip import strip as do_strip           # noqa: E402

ROOT = _HERE.parent
INSTANCES_DIR = ROOT / "instances" / "function"
PROMPTS_DIR = ROOT / "prompts"
RESULTS_DIR = ROOT / "results"

AGENT_WORKSPACE_ORIGINAL = "original"
AGENT_WORKSPACE_SANITIZED_COPY = "sanitized-copy"
ENV_AGENT_SANITIZED_COPY_ROOT = "OBS_AGENT_SANITIZED_COPY_ROOT"

_SANITIZED_COPY_IGNORE_NAMES = {
    ".git", ".hg", ".svn",
    "bin", "obj", "node_modules", ".venv", "venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "target", "build", "dist", "out", "artifacts", "results",
}


def _ignore_for_sanitized_copy(_dirpath: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SANITIZED_COPY_IGNORE_NAMES}


def _create_sanitized_agent_workspace(
    *,
    source_repo_root: Path,
    target_file_rel: str,
    stripped_source: str,
    out_dir: Path,
    temp_root: Optional[Path] = None,
) -> tuple[Path, Path]:
    """Copy the source repo and overwrite the target file with stripped content."""
    run_id = out_dir.relative_to(RESULTS_DIR).parts[0]
    if temp_root is None:
        tmp_parent = RESULTS_DIR / run_id / ".tmp_sanitized"
    else:
        tmp_parent = temp_root.expanduser().resolve() / run_id / ".tmp_sanitized"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    copy_root = tmp_parent / f"{out_dir.parent.parent.name}__{out_dir.parent.name}__{uuid.uuid4().hex}"
    sanitized_repo_root = copy_root / source_repo_root.name
    try:
        shutil.copytree(
            source_repo_root,
            sanitized_repo_root,
            ignore=_ignore_for_sanitized_copy,
            symlinks=False,
        )
        sanitized_target = sanitized_repo_root / target_file_rel
        if not sanitized_target.exists():
            raise FileNotFoundError(f"sanitized target missing after copy: {sanitized_target}")
        sanitized_target.write_text(stripped_source, encoding="utf-8")
        return sanitized_repo_root.resolve(), sanitized_target.resolve()
    except Exception:
        shutil.rmtree(copy_root, ignore_errors=True)
        raise


def _agent_output_contract(language: str) -> str:
    lang = (language or "").strip().lower() or "text"
    return (
        "[Final Output Contract — Non-negotiable]\n"
        f"- Start the response with exactly: ```{lang}\\n\n"
        "- Return exactly one fenced code block.\n"
        "- The block must contain only the single target function definition.\n"
        "- Do not output prose, analysis, checklist, apologies, or tool narration.\n"
        "- Forbidden phrases include: 'I need to', 'I will', 'Let me', 'first tool call', 'plan'.\n"
        "- End the response immediately after the closing triple backticks."
    )


def _build_agent_single_turn_prompt(
    *,
    rendered_prompt: str,
    language: str,
    repo_abs_path: Optional[str],
) -> str:
    repo_line = repo_abs_path or "(unknown)"
    return (
        "[Agent Runtime Context]\n"
        f"- Target repository root (absolute path): {repo_line}\n"
        "- Repo/tool usage is optional; decide yourself based on need.\n"
        "- Do NOT ask follow-up questions.\n\n"
        f"{rendered_prompt}\n\n"
        f"{_agent_output_contract(language)}"
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _repo_identity_keys(repo: dict) -> list[str]:
    keys: list[str] = []
    for value in (repo.get("name"), repo.get("local_path")):
        if not value:
            continue
        text = str(value).strip()
        if text and text not in keys:
            keys.append(text)
        name = Path(text).name
        if name and name not in keys:
            keys.append(name)
        normalized = text.replace("/", "__")
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _parse_repo_path_overrides(items: Optional[list[str]]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"[err] --repo-path-override must be KEY=/abs/path, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise SystemExit(f"[err] --repo-path-override must be KEY=/abs/path, got: {item}")
        overrides[key] = value
    return overrides


def _repo_search_roots(extra_roots: Optional[list[str]]) -> list[Path]:
    roots: list[Path] = []
    for value in (os.environ.get("OBS_REPO_SEARCH_ROOTS") or "").split(os.pathsep):
        if value.strip():
            roots.append(Path(value.strip()).expanduser())
    for value in extra_roots or []:
        if value.strip():
            roots.append(Path(value.strip()).expanduser())
    roots.extend([
        ROOT / "repos",
        ROOT.parent / "_obs_repos",
        ROOT.parent / "obs-bench" / "repos",
        ROOT.parent,
    ])

    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            out.append(resolved)
    return out


def _target_exists(repo_root: Path, file_rel: str) -> bool:
    return (repo_root / file_rel).exists()


def _resolve_repo_root(
    instance: dict,
    *,
    file_rel: str,
    repo_path_overrides: Optional[dict[str, str]] = None,
    repo_search_roots: Optional[list[str]] = None,
) -> Path:
    """Resolve the source repo root for an instance with override/fallback support."""
    repo = instance.get("repo") or {}
    keys = _repo_identity_keys(repo)
    overrides = repo_path_overrides or {}

    for key in keys:
        if key in overrides:
            candidate = Path(overrides[key]).expanduser().resolve()
            if not _target_exists(candidate, file_rel):
                raise SystemExit(
                    f"[err] repo override for {key!r} does not contain target file: "
                    f"{candidate / file_rel}"
                )
            return candidate

    raw_local = str(repo.get("local_path") or "").strip()
    local_candidates: list[Path] = []
    if raw_local:
        local = Path(raw_local).expanduser()
        local_candidates.append(local)
        if not local.is_absolute():
            local_candidates.append(ROOT / local)
            local_candidates.append(ROOT.parent / local)
    for candidate in local_candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if _target_exists(resolved, file_rel):
            return resolved

    names = []
    for key in keys:
        name = Path(key).name
        if name and name not in names:
            names.append(name)
        normalized = key.replace("/", "__")
        if normalized and normalized not in names:
            names.append(normalized)

    for root in _repo_search_roots(repo_search_roots):
        for name in names:
            candidate = root / name
            if _target_exists(candidate, file_rel):
                return candidate.resolve()

    raise SystemExit(
        "[err] could not resolve repo root for instance "
        f"{instance.get('instance_id', '<unknown>')} target {file_rel!r}. "
        "Use --repo-path-override repo_name=/abs/path or --repo-search-root /root."
    )

def _load_instance(instance_id: str) -> dict:
    path = INSTANCES_DIR / f"{instance_id}.json"
    if not path.exists():
        raise SystemExit(f"[err] instance not found: {path}")
    return json.loads(path.read_text())


def _read_ground_truth(instance: dict, repo_root: Path) -> str:
    file_rel = instance["target"]["file"]
    file_abs = repo_root / file_rel
    if not file_abs.exists():
        raise SystemExit(f"[err] ground-truth file not found: {file_abs}")
    return file_abs.read_text()


def _render_sibling_examples(
    instance: dict,
    gt_source: str,
    *,
    language: str,
    k: int,
) -> str:
    """Render up to k sibling functions (from instance["siblings"]) as a
    prompt fragment.

    The siblings field is a pre-ranked list (by n_gt desc) produced by
    tools/build_siblings.py. We take the FIRST k entries (the heaviest
    obs-bearing functions in the same file) and emit each as a labelled
    code block:

        ### Sibling 1: `foo`  (4 observability sites in this codebase)

        ```python
        <full source of foo from ground_truth, with obs intact>
        ```

    These are the LLM's only project-style anchor. The function bodies
    come straight out of the same gt_source we already read, dedented to
    column 0 to match the formatting of {{TARGET_FUNCTION_SOURCE}}.

    Returns an empty string if k <= 0 or there are no siblings.
    """
    if k <= 0:
        return ""
    siblings = instance.get("siblings") or []
    if not siblings:
        # 4/29 Python instances live in single-function files (loggers,
        # metric initialisers, JSON formatters) and have no obs-bearing
        # siblings to anchor on. Emitting a coherent placeholder is
        # cleaner than letting {{SIBLING_EXAMPLES}} render as an empty
        # gap inside p_fewshot prose ("here are some neighbouring
        # functions: <blank>"). The phrasing is deliberately neutral —
        # it doesn't name a library or push the LLM toward p2 style.
        return (
            "_(No sibling functions with observability are available in "
            "this file. Use your judgement for this codebase's idioms.)_"
        )
    fence = prompt_render._LANGUAGE_FENCE.get(language.lower(), language.lower())
    parts: list[str] = []
    rendered = 0
    for entry in siblings:
        if rendered >= k:
            break
        sib_fn = entry.get("function")
        n_gt = entry.get("n_gt", 0)
        if not sib_fn:
            continue
        try:
            body = function_io.extract_target_function(
                gt_source, sib_fn, language=language
            )
        except (SyntaxError, ValueError):
            # Sibling moved or was renamed since build_siblings ran;
            # silently skip so a single stale entry can't kill the run.
            continue
        rendered += 1
        suffix = "" if n_gt == 1 else "s"
        parts.append(
            f"### Sibling {rendered}: `{sib_fn}`  "
            f"({n_gt} observability site{suffix} in this codebase)\n\n"
            f"```{fence}\n{body.rstrip()}\n```"
        )
    return "\n\n".join(parts)


_CODE_BLOCK_RE = re.compile(r"```(?:[a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)


def _extract_code_block(response: str) -> str:
    """Legacy whole-file extractor — kept for non-Python paths only.

    For Python instances we use function_io.extract_code_from_response which
    is smarter about picking the block that actually contains a `def`.
    """
    blocks = _CODE_BLOCK_RE.findall(response)
    if not blocks:
        return response.strip()
    # pick the longest block (usually the full file)
    return max(blocks, key=len).strip() + "\n"


@dataclass
class RunResult:
    instance_id: str
    prompt_level: str
    model: str
    backend: str
    agent: Optional[str]
    agentic: bool
    agent_workspace: Optional[str]
    agent_workspace_mode: str
    agent_repo_context: str
    agent_trace_path: Optional[str]
    elapsed_s: float
    score: dict           # legacy type-bag score (tools.score.score_sites)
    anchor_score: dict    # new anchor-based score (tools.score_anchor)
    gt_sites: list[dict]
    llm_sites: list[dict]
    llm_response_preview: str  # first 500 chars only


# ---------------------------------------------------------------------------
# core run
# ---------------------------------------------------------------------------

def run_one(
    instance_id: str,
    prompt_level: str,
    model: str,
    *,
    backend: str = llm_client.DEFAULT_BACKEND,
    agent: Optional[str] = None,
    agent_disable_tools: bool = True,
    agentic: bool = False,
    agent_workspace: Optional[str] = None,
    agent_workspace_mode: str = AGENT_WORKSPACE_ORIGINAL,
    agent_sanitized_copy_root: Optional[str] = None,
    agent_repo_context: str = "none",
    agent_trace: bool = False,
    repo_path_overrides: Optional[dict[str, str]] = None,
    repo_search_roots: Optional[list[str]] = None,
    dry_run: bool = False,
    run_id: str = "pilot",
) -> Optional[RunResult]:
    instance = _load_instance(instance_id)
    language = instance["target"]["language"]
    function = instance["target"]["function"]
    file_path = instance["target"]["file"]
    instance_repo_root = _resolve_repo_root(
        instance,
        file_rel=file_path,
        repo_path_overrides=repo_path_overrides,
        repo_search_roots=repo_search_roots,
    )
    instance_repo_path = str(instance_repo_root)

    gt_source = _read_ground_truth(instance, instance_repo_root)
    # Agent should be able to inspect repo context, but not the current
    # instance target file (prevents direct GT leakage during evaluation).
    agent_blocked_paths: list[str] = []
    if backend == "agent":
        target_abs = str((instance_repo_root / file_path).resolve())
        agent_blocked_paths.append(target_abs)

    # 1. strip obs out of the target function only
    stripped_source = do_strip(gt_source, language=language, function=function)

    # 2. extract ground-truth sites (always — useful even in dry-run)
    gt_sites = extract_pkg.extract(gt_source, language=language, function=function)

    # 3. function-tier roundtrip inputs:
    #    - target function dedented to col 0 (what the LLM gets to edit)
    #    - module-level context (imports + obs setup the LLM may reference)
    # Load the prompt template up front so we know whether to blind the stub
    # (p0-class "strip_telemetry" experiments need module_context scrubbed
    # of every OTel/logging/prom tell before the LLM sees it).
    tmpl = prompt_render.load(PROMPTS_DIR, prompt_level)
    target_function_source = function_io.extract_target_function(
        stripped_source, function, language=language
    )
    module_context = function_io.extract_module_context(
        stripped_source, function,
        language=language,
        strip_telemetry=tmpl.strip_telemetry,
    )

    # Few-shot: render up to `fewshot_k` sibling functions (with obs intact)
    # from the SAME file. The list is pre-mined into instance["siblings"]
    # by tools/build_siblings.py, ranked by n_gt desc. Empty string for
    # every existing prompt (fewshot_k defaults to 0).
    sibling_examples = _render_sibling_examples(
        instance, gt_source, language=language, k=tmpl.fewshot_k
    )

    # output dir
    out_dir = RESULTS_DIR / run_id / instance_id / prompt_level / model
    out_dir.mkdir(parents=True, exist_ok=True)

    if agent_workspace_mode not in (AGENT_WORKSPACE_ORIGINAL, AGENT_WORKSPACE_SANITIZED_COPY):
        raise ValueError(
            "agent_workspace_mode must be one of: "
            f"{AGENT_WORKSPACE_ORIGINAL}, {AGENT_WORKSPACE_SANITIZED_COPY}"
        )

    sanitized_copy_root: Optional[Path] = None
    sanitized_repo_root: Optional[Path] = None
    sanitized_target_path: Optional[Path] = None
    sanitized_copy_temp_root = agent_sanitized_copy_root or os.environ.get(ENV_AGENT_SANITIZED_COPY_ROOT)

    # In agent mode, default workspace should be the source repo of THIS instance,
    # so tool calls/search operate on the target project rather than the benchmark
    # harness repo. In sanitized-copy mode, the workspace is a temporary repo copy
    # where only the target function has had ground-truth observability removed.
    resolved_agent_workspace = agent_workspace
    if backend == "agent" and agent_workspace_mode == AGENT_WORKSPACE_SANITIZED_COPY and not dry_run:
        if agent_workspace:
            raise ValueError("--agent-workspace cannot be combined with --agent-workspace-mode sanitized-copy")
        sanitized_repo_root, sanitized_target_path = _create_sanitized_agent_workspace(
            source_repo_root=instance_repo_root,
            target_file_rel=file_path,
            stripped_source=stripped_source,
            out_dir=out_dir,
            temp_root=Path(sanitized_copy_temp_root) if sanitized_copy_temp_root else None,
        )
        sanitized_copy_root = sanitized_repo_root.parent
        resolved_agent_workspace = str(sanitized_repo_root)
    elif backend == "agent" and not resolved_agent_workspace:
        resolved_agent_workspace = instance_repo_path
    if resolved_agent_workspace:
        ws_path = Path(resolved_agent_workspace)
        if not ws_path.exists():
            sys.stderr.write(
                f"[warn] agent workspace path does not exist: {resolved_agent_workspace}; "
                "falling back to runtime defaults\n"
            )
            resolved_agent_workspace = None
        else:
            resolved_agent_workspace = str(ws_path.resolve())

    if backend == "agent":
        workspace_meta = {
            "mode": agent_workspace_mode,
            "original_repo_root": instance_repo_path,
            "original_target_file": str((instance_repo_root / file_path).resolve()),
            "agent_workspace": resolved_agent_workspace,
            "sanitized_copy_root": str(sanitized_copy_root) if sanitized_copy_root else None,
            "sanitized_copy_temp_root": str(Path(sanitized_copy_temp_root).expanduser().resolve())
            if sanitized_copy_temp_root else None,
            "sanitized_target_file": str(sanitized_target_path) if sanitized_target_path else None,
            "cleanup": "removed_after_llm_call" if sanitized_copy_root else None,
            "ignored_copy_names": sorted(_SANITIZED_COPY_IGNORE_NAMES)
            if sanitized_copy_root else [],
        }
        (out_dir / "agent_workspace_mode.json").write_text(
            json.dumps(workspace_meta, indent=2) + "\n"
        )

    # always persist all inputs for human inspection
    (out_dir / "stripped.py").write_text(stripped_source)
    (out_dir / "ground_truth.py").write_text(gt_source)
    (out_dir / "target_function.py").write_text(target_function_source)
    (out_dir / "module_context.py").write_text(module_context)
    (out_dir / "ground_truth_sites.json").write_text(
        json.dumps([s.to_dict() for s in gt_sites], indent=2) + "\n"
    )
    if sibling_examples:
        (out_dir / "sibling_examples.md").write_text(sibling_examples + "\n")

    # 4. prompt — rendered up front so --dry-run still writes prompt.md for
    # human inspection (the whole point of dry-run is prompt authoring).
    rendered = prompt_render.render(
        tmpl,
        language=language,
        file_path=file_path,
        function=function,
        source=target_function_source,   # legacy var, points at function now
        available_imports=instance["task"].get("available_imports", []),
        module_context=module_context,
        target_function_source=target_function_source,
        sibling_examples=sibling_examples,
    )
    (out_dir / "prompt.md").write_text(rendered)

    if dry_run:
        print(f"[dry-run] {instance_id}: inputs written under {out_dir}")
        return None

    # 5. LLM
    t0 = time.time()
    request_prompt = rendered
    if backend == "agent" and agentic:
        # Keep legacy agentic behavior only when explicitly enabled.
        request_prompt = _build_agent_single_turn_prompt(
            rendered_prompt=rendered,
            language=language,
            repo_abs_path=resolved_agent_workspace or instance_repo_path,
        )
        (out_dir / "agentic_prompt.md").write_text(request_prompt)
    if agent_blocked_paths:
        (out_dir / "agent_blocked_paths.json").write_text(
            json.dumps(agent_blocked_paths, indent=2) + "\n"
        )
    agent_trace_path: Optional[str] = None
    if backend == "agent" and agent_trace:
        agent_trace_path = str(out_dir / "agent_trace.json")

    try:
        response = llm_client.call(
            request_prompt,
            model=model,
            backend=backend,
            agent=agent,
            agent_disable_tools=agent_disable_tools,
            agent_workspace=resolved_agent_workspace,
            agentic=agentic,
            agent_forbidden_paths=agent_blocked_paths,
            agent_trace_path=agent_trace_path,
            agent_repo_context=agent_repo_context,
        )
    finally:
        if sanitized_copy_root is not None:
            shutil.rmtree(sanitized_copy_root, ignore_errors=True)

    elapsed = time.time() - t0
    (out_dir / "llm_response.md").write_text(response)

    # 6. parse — pull the function block out of the response
    llm_function_block = function_io.extract_code_from_response(
        response,
        language=language,
        function=function,
    )
    (out_dir / "llm_function.py").write_text(llm_function_block)

    # 7. splice the LLM-returned function back into the stripped file
    try:
        llm_source = function_io.splice_function(
            stripped_source, function, llm_function_block, language=language
        )
    except (SyntaxError, ValueError) as e:
        sys.stderr.write(
            f"[warn] splice failed for {instance_id}/{prompt_level}: {e}\n"
            "       Falling back to stripped source to keep parsing stable.\n"
        )
        (out_dir / "llm_function_invalid.py").write_text(llm_function_block)
        llm_source = stripped_source
    (out_dir / "llm_source.py").write_text(llm_source)

    # 8. extract LLM sites from the spliced file
    try:
        llm_sites = extract_pkg.extract(
            llm_source, language=language, function=function
        )
    except (SyntaxError, ValueError) as e:
        sys.stderr.write(
            f"[warn] extract failed for {instance_id}/{prompt_level}: {e}\n"
        )
        llm_sites = []

    (out_dir / "llm_sites.json").write_text(
        json.dumps([s.to_dict() for s in llm_sites], indent=2) + "\n"
    )

    # 9. score — both metrics:
    #   - legacy type-bag F1 (kept for backward compatibility with earlier runs)
    #   - new anchor-based Position F1 + independent Key F1 (the real metric)
    s = score.score_sites(gt_sites, llm_sites)
    try:
        anchor = score_anchor(gt_source, llm_source, function, language=language)
    except Exception as e:  # noqa: BLE001  defensive: never let scoring kill the cell
        sys.stderr.write(
            f"[warn] score_anchor failed for {instance_id}/{prompt_level}: {e}\n"
        )
        anchor = {
            "n_anchors_gt": 0, "n_anchors_llm": 0, "n_anchors_aligned": 0,
            "n_buckets": 0, "n_gt_obs_buckets": 0, "n_llm_obs_buckets": 0,
            "tp": 0, "fp": 0, "fn": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "key_tp": 0, "key_fp": 0, "key_fn": 0,
            "key_n_comparable_buckets": 0,
            "key_precision": None, "key_recall": None, "key_f1": None,
            "key_bag_tp": 0, "key_bag_fp": 0, "key_bag_fn": 0,
            "key_bag_n_comparable_buckets": 0,
            "key_bag_precision": None, "key_bag_recall": None, "key_bag_f1": None,
            "buckets": [],
        }
    result = RunResult(
        instance_id=instance_id,
        prompt_level=prompt_level,
        model=model,
        backend=backend,
        agent=agent,
        agentic=agentic,
        agent_workspace=resolved_agent_workspace,
        agent_workspace_mode=agent_workspace_mode,
        agent_repo_context=agent_repo_context,
        agent_trace_path=agent_trace_path,
        elapsed_s=round(elapsed, 2),
        score=s,
        anchor_score=anchor,
        gt_sites=[g.to_dict() for g in gt_sites],
        llm_sites=[m.to_dict() for m in llm_sites],
        llm_response_preview=response[:500],
    )
    (out_dir / "result.json").write_text(json.dumps(asdict(result), indent=2) + "\n")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _list_instances(*, language: Optional[str] = None) -> list[str]:
    """List instance IDs, optionally filtered by target.language.

    Non-runnable (e.g. auto-mined for languages without a stripper yet) are
    skipped when `language` is specified or when `_runnable: false` is set.
    """
    out: list[str] = []
    for p in sorted(INSTANCES_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            doc = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if doc.get("_runnable") is False:
            continue
        if language is not None and doc.get("target", {}).get("language") != language:
            continue
        out.append(p.stem)
    return out


def _count_gt_sites_for_instance(
    instance_id: str,
    *,
    repo_path_overrides: Optional[dict[str, str]] = None,
    repo_search_roots: Optional[list[str]] = None,
) -> Optional[int]:
    """Return this instance's GT obs-site count, or None if it cannot be checked."""
    try:
        instance = _load_instance(instance_id)
        language = instance["target"]["language"]
        function = instance["target"]["function"]
        file_path = instance["target"]["file"]
        repo_root = _resolve_repo_root(
            instance,
            file_rel=file_path,
            repo_path_overrides=repo_path_overrides,
            repo_search_roots=repo_search_roots,
        )
        gt_source = _read_ground_truth(instance, repo_root)
        return len(extract_pkg.extract(gt_source, language=language, function=function))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] --skip-zero-gt: could not inspect {instance_id}: {e}\n")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="obs-real-bench pilot runner.")
    ap.add_argument("--instance", help="Instance id (without .json). Mutually exclusive with --all.")
    ap.add_argument("--all", action="store_true", help="Run every instance in instances/function/.")
    ap.add_argument(
        "--prompts",
        default="p_blind,p1_obs_hinted,p_fewshot",
        help="Comma-separated prompt levels (default: canonical 3-rung ladder).",
    )
    ap.add_argument("--model", default=llm_client.DEFAULT_MODEL, help="Model id or alias.")
    ap.add_argument(
        "--backend",
        default=llm_client.DEFAULT_BACKEND,
        help="LLM backend: api (Azure OpenAI helper) or agent (Copilot SDK).",
    )
    ap.add_argument(
        "--agent",
        help="Optional Copilot custom agent name (used only when --backend agent).",
    )
    ap.add_argument(
        "--allow-agent-tools",
        action="store_true",
        help=(
            "Allow Copilot agent tool calls (off by default for stability). "
            "When omitted, agent mode behaves closer to API mode."
        ),
    )
    ap.add_argument(
        "--agentic",
        action="store_true",
        help="Enable agentic mode: allow repo-aware planning/search before final answer (agent backend only).",
    )
    ap.add_argument(
        "--agent-repo-context",
        choices=("none", "related"),
        default="none",
        help=(
            "Agent backend only. 'related' sends a preflight turn asking the "
            "agent to inspect related repo files while target files remain blocked."
        ),
    )
    ap.add_argument(
        "--agent-trace",
        action="store_true",
        help="Agent backend only. Write full Copilot SDK session events to agent_trace.json per cell.",
    )
    ap.add_argument(
        "--agent-workspace",
        help=(
            "Override working directory exposed to Copilot agent tools "
            "(agent backend only). By default, each instance uses its own "
            "source repo path from instances/function/*.json (repo.local_path)."
        ),
    )
    ap.add_argument(
        "--agent-workspace-mode",
        choices=(AGENT_WORKSPACE_ORIGINAL, AGENT_WORKSPACE_SANITIZED_COPY),
        default=AGENT_WORKSPACE_ORIGINAL,
        help=(
            "Agent backend only. 'original' exposes the resolved source repo. "
            "'sanitized-copy' exposes a temporary copy of that repo where the "
            "target file contains the stripped target function, while the "
            "original target file remains forbidden."
        ),
    )
    ap.add_argument(
        "--agent-sanitized-copy-root",
        help=(
            "Directory for temporary sanitized repo copies (agent backend only). "
            f"Defaults to results/<run-id>/.tmp_sanitized or ${ENV_AGENT_SANITIZED_COPY_ROOT}. "
            "Useful for placing large copies on a separate disk such as /Data2."
        ),
    )
    ap.add_argument(
        "--repo-path-override",
        action="append",
        default=[],
        metavar="KEY=/abs/path",
        help=(
            "Override instance repo roots at runtime. KEY may be repo.name, "
            "repo.local_path, basename, or owner__repo. Can be repeated."
        ),
    )
    ap.add_argument(
        "--repo-search-root",
        action="append",
        default=[],
        help=(
            "Additional root to search when instance repo.local_path is stale. "
            "Also supports OBS_REPO_SEARCH_ROOTS separated by os.pathsep."
        ),
    )
    ap.add_argument("--run-id", default="pilot", help="Logical run id (results/<run-id>/).")
    ap.add_argument("--dry-run", action="store_true", help="Skip LLM call; just strip + extract.")
    ap.add_argument(
        "--language",
        help="Restrict --all to instances where target.language matches (e.g. python).",
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help="Number of parallel worker threads for LLM calls. "
             "Default 1 (sequential). The OpenAI sync client is thread-safe; "
             "for 58 cells, --workers 8 typically cuts wall-time ~6-7x.",
    )
    ap.add_argument(
        "--skip-existing", action="store_true",
        help="Skip (instance, prompt) cells whose result.json already exists "
             "under results/<run-id>/. Use after a partial run to fill gaps "
             "without re-doing finished cells.",
    )
    ap.add_argument(
        "--skip-zero-gt",
        action="store_true",
        help=(
            "Before calling the LLM/agent, locally extract GT obs sites and "
            "skip instances with n_gt == 0. This matches STRICT aggregate "
            "filtering and avoids spending model calls on unscored cells."
        ),
    )
    args = ap.parse_args()

    if args.all and args.instance:
        ap.error("--all and --instance are mutually exclusive")
    if not args.all and not args.instance:
        ap.error("specify either --instance or --all")
    if args.workers < 1:
        ap.error("--workers must be >= 1")
    if args.agent_workspace and args.agent_workspace_mode == AGENT_WORKSPACE_SANITIZED_COPY:
        ap.error("--agent-workspace cannot be combined with --agent-workspace-mode sanitized-copy")
    repo_path_overrides = _parse_repo_path_overrides(args.repo_path_override)
    try:
        backend = llm_client.resolve_backend(args.backend)
    except ValueError as e:
        ap.error(str(e))

    if backend != "agent" and (
        args.agent
        or args.agentic
        or args.agent_workspace
        or args.agent_workspace_mode != AGENT_WORKSPACE_ORIGINAL
        or args.agent_sanitized_copy_root
        or args.agent_repo_context != "none"
        or args.agent_trace
    ):
        print(
            "[pilot] warning: agent-specific options are ignored when backend != agent",
            flush=True,
        )

    instances = _list_instances(language=args.language) if args.all else [args.instance]
    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]

    missing = [p for p in prompts if not (PROMPTS_DIR / f"{p}.md").exists()]
    if missing:
        available = sorted(p.stem for p in PROMPTS_DIR.glob("*.md") if not p.stem.endswith(".bak"))
        ap.error(
            f"prompt file(s) not found in {PROMPTS_DIR}: {missing}. "
            f"Available: {available}"
        )

    # Build the full work list of (instance, prompt) pairs.
    work: list[tuple[str, str]] = [(inst, pr) for inst in instances for pr in prompts]

    # --skip-existing: drop cells whose result.json is already written.
    if args.skip_existing:
        before = len(work)
        kept: list[tuple[str, str]] = []
        for inst, pr in work:
            result_path = RESULTS_DIR / args.run_id / inst / pr / args.model / "result.json"
            if result_path.exists():
                continue
            kept.append((inst, pr))
        work = kept
        skipped = before - len(work)
        if skipped:
            print(f"[pilot] --skip-existing: skipping {skipped} cells already in results/{args.run_id}/", flush=True)
        if not work:
            # Don't early-return: fall through so the on-disk summary.json
            # still gets rebuilt. This lets users refresh the aggregate after
            # a scoring-code change (e.g. new metric) without re-running cells.
            print(
                f"[pilot] --skip-existing: no new cells to run "
                f"(all {before} complete) \u2014 will refresh summary.json from disk",
                flush=True,
            )

    if args.skip_zero_gt and work:
        before = len(work)
        n_gt_cache: dict[str, Optional[int]] = {}
        kept_zero_filtered: list[tuple[str, str]] = []
        for inst, pr in work:
            if inst not in n_gt_cache:
                n_gt_cache[inst] = _count_gt_sites_for_instance(
                    inst,
                    repo_path_overrides=repo_path_overrides,
                    repo_search_roots=args.repo_search_root,
                )
            n_gt = n_gt_cache[inst]
            if n_gt == 0:
                continue
            kept_zero_filtered.append((inst, pr))
        work = kept_zero_filtered
        skipped_cells = before - len(work)
        skipped_instances = sum(1 for n_gt in n_gt_cache.values() if n_gt == 0)
        if skipped_cells:
            print(
                f"[pilot] --skip-zero-gt: skipping {skipped_cells} cells "
                f"from {skipped_instances} instances with n_gt==0",
                flush=True,
            )

    total = len(work)
    summary: list[dict] = []
    print_lock = Lock()
    t_start = time.time()

    def _format_done(idx: int, inst: str, prompt: str, r: Optional[RunResult]) -> str:
        if r is None:
            return f"[{idx}/{total}] DRY-RUN  {inst} | {prompt}"
        s = r.score
        a = r.anchor_score
        def _fmt(v: object) -> str:
            return "N/A" if v is None else f"{v:.3f}"  # type: ignore[arg-type]
        key_f1 = a.get("key_f1")
        bag_r = a.get("key_bag_recall")
        return (
            f"[{idx}/{total}] DONE  {inst} | {prompt}  "
            f"n_gt={s['n_gt']} n_llm={s['n_llm']} "
            f"OldF1={_fmt(s['f1'])} PosF1={_fmt(a['f1'])} "
            f"KeyF1(strict)={_fmt(key_f1)} BagR={_fmt(bag_r)} "
            f"(anch {a['n_anchors_aligned']}/{a['n_anchors_gt']}↔{a['n_anchors_llm']}, "
            f"keyN={a['key_n_comparable_buckets']}, bagN={a.get('key_bag_n_comparable_buckets', 0)}) ({r.elapsed_s}s)"
        )

    def _run_cell(inst: str, prompt: str) -> tuple[str, str, Optional[RunResult], Optional[str]]:
        """Worker entry point. Returns (inst, prompt, RunResult|None, error|None).

        Catches BaseException (not just Exception) so per-cell SystemExit or
        KeyboardInterrupt in one worker doesn't tear down the whole concurrent
        run via fut.result() re-raising in the main thread.
        """
        try:
            r = run_one(
                inst, prompt, args.model,
                backend=backend,
                agent=args.agent,
                agent_disable_tools=not args.allow_agent_tools,
                agentic=args.agentic,
                agent_workspace=args.agent_workspace,
                agent_workspace_mode=args.agent_workspace_mode,
                agent_sanitized_copy_root=args.agent_sanitized_copy_root,
                agent_repo_context=args.agent_repo_context,
                agent_trace=args.agent_trace,
                repo_path_overrides=repo_path_overrides,
                repo_search_roots=args.repo_search_root,
                dry_run=args.dry_run, run_id=args.run_id,
            )
            return inst, prompt, r, None
        except BaseException:  # noqa: BLE001  intentional: isolate one cell
            return inst, prompt, None, traceback.format_exc()
        finally:
            ts_obs.clear_parser_cache()

    # ---- sequential path: keeps stdout clean when --workers 1 ----
    if args.workers == 1:
        for i, (inst, prompt) in enumerate(work, 1):
            print(f"[{i}/{total}] START {inst} | {prompt} | {args.model}", flush=True)
            inst_o, prompt_o, r, err = _run_cell(inst, prompt)
            if err is not None:
                print(f"[{i}/{total}] FAIL  {inst} | {prompt}\n{err}", flush=True)
                continue
            print(_format_done(i, inst_o, prompt_o, r), flush=True)
            if r is not None:
                summary.append({
                    "instance": inst_o,
                    "prompt": prompt_o,
                    "model": args.model,
                    "backend": r.backend,
                    "agent": r.agent,
                    "agentic": r.agentic,
                    "agent_workspace": r.agent_workspace,
                    "agent_workspace_mode": r.agent_workspace_mode,
                    "agent_repo_context": r.agent_repo_context,
                    "agent_trace_path": r.agent_trace_path,
                    **r.score, "elapsed_s": r.elapsed_s,
                })
    # ---- concurrent path ----
    else:
        print(
            f"[pilot] dispatching {total} cells across {args.workers} workers "
            f"(model={args.model}, backend={backend}, run_id={args.run_id}, agentic={args.agentic})",
            flush=True,
        )
        if not args.dry_run:
            # Build the OpenAI client ONCE in the main thread before workers
            # start, so concurrent workers don't race Azure CLI login.
            t_prewarm = time.time()
            if backend == "api":
                print("[pilot] pre-warming API client (Azure CLI auth + helper load, ~5-15s)...", flush=True)
            else:
                print("[pilot] pre-warming Agent backend (Copilot SDK import + runtime checks)...", flush=True)
            llm_client.prewarm(backend=backend)
            print(f"[pilot] pre-warm done in {time.time() - t_prewarm:.1f}s", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            # Submit all cells; print one START line per cell so the user
            # can see what's in flight before the first DONE arrives.
            future_to_meta: dict[Future, tuple[int, str, str]] = {}
            for submit_idx, (inst, prompt) in enumerate(work, 1):
                fut = ex.submit(_run_cell, inst, prompt)
                future_to_meta[fut] = (submit_idx, inst, prompt)
                print(f"[submit {submit_idx}/{total}] {inst} | {prompt}", flush=True)

            done_count = 0
            for fut in as_completed(future_to_meta):
                done_count += 1
                inst_o, prompt_o, r, err = fut.result()
                with print_lock:
                    if err is not None:
                        print(
                            f"[{done_count}/{total}] FAIL  {inst_o} | {prompt_o}\n{err}",
                            flush=True,
                        )
                    else:
                        print(_format_done(done_count, inst_o, prompt_o, r), flush=True)
                if r is not None:
                    summary.append({
                        "instance": inst_o,
                        "prompt": prompt_o,
                        "model": args.model,
                        "backend": r.backend,
                        "agent": r.agent,
                        "agentic": r.agentic,
                        "agent_workspace": r.agent_workspace,
                        "agent_workspace_mode": r.agent_workspace_mode,
                        "agent_repo_context": r.agent_repo_context,
                        "agent_trace_path": r.agent_trace_path,
                        **r.score, "elapsed_s": r.elapsed_s,
                    })

    elapsed_total = time.time() - t_start

    # Build/refresh the run summary from all result.json files on disk in this
    # run directory — not just the cells executed this invocation. This makes
    # --skip-existing safe (we merge pre-existing results) and survives mid-run
    # restarts.
    #
    # Each summary row carries BOTH metrics side-by-side:
    #   - legacy type-bag F1 under "f1" (+ precision/recall/n_gt/n_llm/n_matched)
    #   - anchor Position F1 under "pos_f1" (+ pos_precision/pos_recall + anchor metadata)
    #   - independent Key F1 under "key_f1" (None when not measurable)
    # Old result.json files without an anchor_score block degrade gracefully:
    # the anchor_* fields are simply absent / None for those rows.
    run_dir = RESULTS_DIR / args.run_id
    on_disk_summary: list[dict] = []
    for result_path in sorted(run_dir.glob(f"*/*/{args.model}/result.json")):
        try:
            data = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        score_block = data.get("score") or {}
        anchor_block = data.get("anchor_score") or {}
        row: dict = {
            "instance": data.get("instance_id", ""),
            "prompt": data.get("prompt_level", ""),
            "model": data.get("model", args.model),
            "backend": data.get("backend", backend),
            "agent": data.get("agent", args.agent),
            "agentic": data.get("agentic", args.agentic),
            "agent_workspace": data.get("agent_workspace", args.agent_workspace),
            "agent_workspace_mode": data.get("agent_workspace_mode", args.agent_workspace_mode),
            "agent_repo_context": data.get("agent_repo_context", args.agent_repo_context),
            "agent_trace_path": data.get("agent_trace_path"),
            **score_block,
            "elapsed_s": data.get("elapsed_s", 0.0),
        }
        if anchor_block:
            row.update({
                "pos_precision": anchor_block.get("precision"),
                "pos_recall":    anchor_block.get("recall"),
                "pos_f1":        anchor_block.get("f1"),
                "key_precision": anchor_block.get("key_precision"),
                "key_recall":    anchor_block.get("key_recall"),
                "key_f1":        anchor_block.get("key_f1"),
                "key_n_comparable_buckets": anchor_block.get("key_n_comparable_buckets"),
                "key_bag_precision": anchor_block.get("key_bag_precision"),
                "key_bag_recall":    anchor_block.get("key_bag_recall"),
                "key_bag_f1":        anchor_block.get("key_bag_f1"),
                "key_bag_n_comparable_buckets": anchor_block.get("key_bag_n_comparable_buckets"),
                "n_anchors_gt":      anchor_block.get("n_anchors_gt"),
                "n_anchors_llm":     anchor_block.get("n_anchors_llm"),
                "n_anchors_aligned": anchor_block.get("n_anchors_aligned"),
            })
        on_disk_summary.append(row)
    on_disk_summary.sort(key=lambda d: (d["instance"], d["prompt"]))

    if on_disk_summary:
        out = run_dir / "summary.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(on_disk_summary, indent=2) + "\n")
        n_total = len(on_disk_summary)

        def _mean(rows: list[dict], key: str) -> Optional[float]:
            vs = [d[key] for d in rows if d.get(key) is not None]
            return sum(vs) / len(vs) if vs else None

        def _mean_harsh(rows: list[dict], key: str) -> Optional[float]:
            """Mean across ALL rows, treating None as 0.0.

            Use for headline F1: if the LLM emitted nothing or emitted at
            wrong anchors, the cell still counts in the denominator with
            score 0 — no 'measurable subset' survivor bias.
            """
            if not rows:
                return None
            return sum((d.get(key) or 0.0) for d in rows) / len(rows)

        def _fmt(v: Optional[float]) -> str:
            return " N/A " if v is None else f"{v:.3f}"

        def _print_block(rows: list[dict], label: str) -> None:
            """Print the OldF1 / Position / Key(strict) / Key(bag) aggregate
            for one subset of rows. Used once for the global aggregate and
            once per prompt-level so p0 vs p1 vs p2 vs p_blind can be
            compared at a glance.

            Key strict / Key bag are reported HARSH by default — every cell
            in the denominator, N/A counted as 0. This avoids the survivor
            bias where a prompt that makes the LLM silent (p_blind: only
            2/29 cells had any LLM obs) looks ARTIFICIALLY good because the
            27 silent cells get filtered out of the measurable-subset
            average. The 'zero-score cells: M/N' note next to each harsh
            number tells you how much of that harshness was actually
            applied for this prompt.
            """
            nn = len(rows)
            if nn == 0:
                print(f"[pilot] {label}: no rows", flush=True)
                return
            mean_old = sum(d.get("f1", 0.0) for d in rows) / nn
            mean_n_llm = _mean(rows, "n_llm")
            mean_n_gt  = _mean(rows, "n_gt")
            mean_pos_p = _mean(rows, "pos_precision")
            mean_pos_r = _mean(rows, "pos_recall")
            mean_pos_f = _mean(rows, "pos_f1")
            # Position is always measurable on our corpus (every GT has
            # ≥1 anchor); the n=X/Y line was always n_total/n_total.
            # Harsh treatment of Key strict + Key bag:
            mean_key_p = _mean_harsh(rows, "key_precision")
            mean_key_r = _mean_harsh(rows, "key_recall")
            mean_key_f = _mean_harsh(rows, "key_f1")
            n_strict_zero = sum(1 for d in rows if d.get("key_f1") is None)
            mean_bag_p = _mean_harsh(rows, "key_bag_precision")
            mean_bag_r = _mean_harsh(rows, "key_bag_recall")
            mean_bag_f = _mean_harsh(rows, "key_bag_f1")
            n_bag_zero = sum(1 for d in rows if d.get("key_bag_f1") is None)
            print(f"[pilot] === {label} (n={nn}) ===", flush=True)
            print(
                f"[pilot]   counts                   :  "
                f"n_gt={_fmt(mean_n_gt)}  n_llm={_fmt(mean_n_llm)}    "
                f"(raw obs-site counts; F1-free signal)",
                flush=True,
            )
            print(f"[pilot]   OldF1   (legacy type-bag) :  F1={_fmt(mean_old)}", flush=True)
            print(
                f"[pilot]   Position                  :  "
                f"P={_fmt(mean_pos_p)}  R={_fmt(mean_pos_r)}  F1={_fmt(mean_pos_f)}",
                flush=True,
            )
            print(
                f"[pilot]   Key strict ({nn}-cell mean):  "
                f"P={_fmt(mean_key_p)}  R={_fmt(mean_key_r)}  F1={_fmt(mean_key_f)}   "
                f"[{n_strict_zero} of those {nn} cells contributed 0]",
                flush=True,
            )
            print(
                f"[pilot]   Key bag    ({nn}-cell mean):  "
                f"P={_fmt(mean_bag_p)}  R={_fmt(mean_bag_r)}  F1={_fmt(mean_bag_f)}   "
                f"[{n_bag_zero} of those {nn} cells contributed 0]    \u2190 HEADLINE",
                flush=True,
            )

        this_run_done = len(summary)

        print(
            f"\n[pilot] this run: {this_run_done}/{total} cells executed, "
            f"on-disk total: {n_total} cells, "
            f"wall-time={elapsed_total:.1f}s",
            flush=True,
        )
        _print_block(on_disk_summary, "ALL")

        # Per-prompt breakdown so p0 / p1 / p2 / p_blind can be compared
        # directly without re-running rescore. Sorted by prompt name for
        # stable output across runs.
        prompts_seen = sorted({d.get("prompt", "") for d in on_disk_summary if d.get("prompt")})
        if len(prompts_seen) > 1:
            for p in prompts_seen:
                sub = [d for d in on_disk_summary if d.get("prompt") == p]
                _print_block(sub, f"prompt={p}")

        print(f"[pilot] summary -> {out}", flush=True)
    else:
        print(f"\n[pilot] no result.json files found under {run_dir} (wall-time={elapsed_total:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

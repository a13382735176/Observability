#!/usr/bin/env python3
"""Run Copilot SDK generation inside generated-service workspaces.

Generation safety model:
- Run `python3 tools/skill_experiment.py strip-faults` before this script.
- Each SDK workspace is one `<workspace-root>/<service>-skill` directory.
- The workspace may contain prompt/contract/docker/k8s/run harness files, but
  must not contain `faults/` during generation.
- Run `python3 tools/skill_experiment.py restore-faults` after generation before
  private evaluation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "services_skill"
EXP_ROOT = ROOT / "experiments" / "skill_observability"
RUNS_ROOT = EXP_ROOT / "sdk_service_runs"
DEFAULT_SDK = Path(os.environ.get("COPILOT_SDK_SCRIPT", "demo_call_copilot_agent.py"))
WORKSPACE_SDK = ROOT.parent / "demo_call_copilot_agent.py"
DEFAULT_PYTHON = Path(os.environ.get("PYTHON", "python3"))


def default_sdk_script() -> Path:
    if DEFAULT_SDK.exists():
        return DEFAULT_SDK
    if WORKSPACE_SDK.exists():
        return WORKSPACE_SDK
    return DEFAULT_SDK


def sort_key(name: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def selected_services(workspace_root: Path, limit: int | None, names: list[str] | None) -> list[str]:
    if names:
        selected = [name if name.endswith("-skill") else f"{name}-skill" for name in names]
    else:
        selected = sorted(
            [p.name for p in workspace_root.iterdir() if p.is_dir() and re.match(r"^\d+-", p.name)],
            key=sort_key,
        )
    if limit is not None:
        selected = selected[:limit]
    missing = [name for name in selected if not (workspace_root / name).is_dir()]
    if missing:
        raise SystemExit(f"missing workspace dirs under {workspace_root}: {', '.join(missing)}")
    return selected


def ensure_generation_safe(workspace: Path, *, dry_run: bool = False) -> None:
    if not dry_run and (workspace / "faults").exists():
        raise RuntimeError(
            f"{workspace}/faults exists; run `make skill-strip-faults` before SDK generation"
        )
    if not (workspace / "PROMPT.md").exists():
        raise RuntimeError(f"missing {workspace}/PROMPT.md; run `make skill-materialize` first")


def maybe_clean_src(workspace: Path, clean_src: bool) -> None:
    if not clean_src:
        return
    src = workspace / "src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True, exist_ok=True)


def text_from_timeout_payload(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_one(service_id: str, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    workspace = args.workspace_root / service_id
    ensure_generation_safe(workspace, dry_run=args.dry_run)
    maybe_clean_src(workspace, args.clean_src)

    trace = run_dir / "traces" / f"{service_id}.trace.json"
    trace.parent.mkdir(parents=True, exist_ok=True)
    prompt = workspace / "PROMPT.md"
    cmd = [
        str(args.python),
        str(args.sdk_script),
        "--model",
        args.model,
        "--workspace",
        str(workspace),
        "--permission-mode",
        "autopilot",
        "--prompt-file",
        str(prompt),
        "--trace-file",
        str(trace),
        "--timeout",
        str(args.timeout),
    ]
    if args.agent:
        cmd.extend(["--agent", args.agent])
    if args.show_trace:
        cmd.append("--show-trace")

    print(
        f"[generated-service-sdk] prompt_variant={args.prompt_variant} service={service_id}: "
        f"model={args.model} workspace={workspace}",
        flush=True,
    )
    if args.dry_run:
        print(" ".join(cmd), flush=True)
        return {"service_id": service_id, "status": "DRY_RUN", "cmd": cmd, "trace": str(trace)}

    out_dir = run_dir / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = out_dir / f"{service_id}.stdout.txt"
    stderr_path = out_dir / f"{service_id}.stderr.txt"

    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=args.timeout + 60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(text_from_timeout_payload(exc.stdout), encoding="utf-8")
        stderr_path.write_text(text_from_timeout_payload(exc.stderr), encoding="utf-8")
        generated_files = [p for p in (workspace / "src").rglob("*") if p.is_file()]
        return {
            "service_id": service_id,
            "status": "FAIL",
            "model": args.model,
            "workspace": str(workspace),
            "generated_files": [str(path.relative_to(workspace)) for path in generated_files],
            "error": f"sdk timed out after {args.timeout + 60} seconds",
            "trace": str(trace),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }

    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")

    generated_files = [p for p in (workspace / "src").rglob("*") if p.is_file()]
    status = "OK" if result.returncode == 0 and generated_files else "FAIL"
    error = None
    if result.returncode != 0:
        error = f"sdk exited {result.returncode}"
    elif not generated_files:
        error = "no files generated under src/"
    return {
        "service_id": service_id,
        "status": status,
        "returncode": result.returncode,
        "model": args.model,
        "workspace": str(workspace),
        "generated_files": [str(path.relative_to(workspace)) for path in generated_files],
        "error": error,
        "trace": str(trace),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def merged_summary(run_id: str, previous_path: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    previous_results = previous.get("results", [])
    result_by_service = {str(item.get("service_id", "")): item for item in results}

    merged_results = []
    seen = set()
    for item in previous_results:
        service_id = str(item.get("service_id", ""))
        if service_id in result_by_service:
            merged_results.append(result_by_service[service_id])
            seen.add(service_id)
        else:
            merged_results.append(item)

    for item in results:
        service_id = str(item.get("service_id", ""))
        if service_id and service_id not in seen:
            merged_results.append(item)

    previous["run_id"] = run_id
    previous["count"] = len(merged_results)
    previous["results"] = sorted(merged_results, key=lambda item: sort_key(str(item.get("service_id", ""))))
    return previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="*", help="Specific services, with or without -skill suffix")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--run-id", help="Experiment run id; default is utc timestamp + model")
    parser.add_argument("--prompt-variant", choices=["with-skill", "no-skill", "unknown"], default="unknown")
    parser.add_argument("--agent")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--sdk-script", type=Path, default=default_sdk_script())
    parser.add_argument("--show-trace", action="store_true")
    parser.add_argument("--workspace-root", type=Path, default=SKILL_ROOT, help="Directory containing per-service SDK workspaces")
    parser.add_argument("--clean-src", action="store_true", help="Clear each <workspace-root>/<svc>/src before SDK generation")
    parser.add_argument("--merge-existing-summary", action="store_true", help="Replace this run's selected service results inside an existing summary.json instead of overwriting it")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")
    if not args.dry_run and not args.sdk_script.exists():
        raise SystemExit(
            f"SDK wrapper not found: {args.sdk_script}. Pass --sdk-script <real path> "
            f"or restore {DEFAULT_SDK} / {WORKSPACE_SDK}."
        )
    if not args.workspace_root.exists():
        raise SystemExit(f"workspace root not found: {args.workspace_root}")
    selected = selected_services(args.workspace_root, args.limit, args.services)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_part = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    run_id = args.run_id or f"{stamp}_{model_part}"
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = run_dir / "manifest.json"
    if args.merge_existing_summary and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["last_retry"] = {
            "model": args.model,
            "prompt_variant": args.prompt_variant,
            "workspace_root": str(args.workspace_root),
            "workers": args.workers,
            "timeout": args.timeout,
            "clean_src": args.clean_src,
            "services": selected,
        }
    else:
        manifest = {
            "run_id": run_id,
            "model": args.model,
            "prompt_variant": args.prompt_variant,
            "workspace_root": str(args.workspace_root),
            "workers": args.workers,
            "timeout": args.timeout,
            "clean_src": args.clean_src,
            "services": selected,
            "note": "Run skill-strip-faults before generation and skill-restore-faults before private evaluation.",
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.workers == 1 or len(selected) <= 1:
        results = [run_one(service_id, args, run_dir) for service_id in selected]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_service = {executor.submit(run_one, service_id, args, run_dir): service_id for service_id in selected}
            for future in as_completed(future_to_service):
                service_id = future_to_service[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    results.append({"service_id": service_id, "status": "FAIL", "error": str(exc)})

    summary_path = run_dir / "summary.json"
    if args.merge_existing_summary and summary_path.exists():
        summary = merged_summary(run_id, summary_path, results)
    else:
        summary = {"run_id": run_id, "count": len(results), "results": sorted(results, key=lambda item: sort_key(str(item.get("service_id", ""))))}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [item for item in results if item.get("status") == "FAIL"]
    merged_failures = [item for item in summary.get("results", []) if item.get("status") == "FAIL"]
    print(
        f"[generated-service-sdk] prompt_variant={args.prompt_variant} "
        f"wrote {summary_path} failures={len(failures)}/{len(results)} "
        f"merged_failures={len(merged_failures)}/{len(summary.get('results', []))}",
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

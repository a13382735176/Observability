#!/usr/bin/env python3
"""Run Copilot SDK generation against isolated skill workspaces only."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXP_ROOT = ROOT / "experiments" / "skill_observability"
ISOLATED_ROOT = EXP_ROOT / "isolated_workspaces"
TRACE_ROOT = EXP_ROOT / "traces"
DEFAULT_SDK = Path(os.environ.get("COPILOT_SDK_SCRIPT", "demo_call_copilot_agent.py"))
WORKSPACE_SDK = ROOT.parent / "demo_call_copilot_agent.py"
DEFAULT_PYTHON = Path(os.environ.get("PYTHON", "python3"))


def default_sdk_script() -> Path:
    if DEFAULT_SDK.exists():
        return DEFAULT_SDK
    if WORKSPACE_SDK.exists():
        return WORKSPACE_SDK
    return DEFAULT_SDK


def services(limit: int | None, names: list[str] | None) -> list[str]:
    if names:
        return [name if name.endswith("-skill") else f"{name}-skill" for name in names]
    found = sorted(
        [p.name for p in ISOLATED_ROOT.iterdir() if p.is_dir()],
        key=lambda name: [int(x) if x.isdigit() else x for x in __import__("re").split(r"(\d+)", name)],
    )
    return found[:limit] if limit is not None else found


def run_one(service_id: str, args: argparse.Namespace) -> dict[str, object]:
    workspace = ISOLATED_ROOT / service_id
    prompt = workspace / "PROMPT.md"
    if not prompt.exists():
        raise SystemExit(f"missing isolated prompt {prompt}; run make skill-prepare-workspace first")

    TRACE_ROOT.mkdir(parents=True, exist_ok=True)
    trace = TRACE_ROOT / f"{service_id}.isolated.trace.json"
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
    if args.show_trace:
        cmd.append("--show-trace")
    if args.agent:
        cmd.extend(["--agent", args.agent])
    print(f"[isolated-sdk] {service_id}: workspace={workspace}")
    if args.dry_run:
        print(" ".join(cmd))
        return {"service_id": service_id, "status": "DRY_RUN", "trace": str(trace)}

    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=args.timeout + 60, check=False)
    out_dir = EXP_ROOT / "sdk_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{service_id}.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (out_dir / f"{service_id}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    generated_files = [p for p in (workspace / "src").rglob("*") if p.is_file()]
    status = "OK" if result.returncode == 0 and generated_files else "FAIL"
    error = None if generated_files else "no files generated under isolated src/"
    return {
        "service_id": service_id,
        "status": status,
        "returncode": result.returncode,
        "generated_files": [str(p.relative_to(workspace)) for p in generated_files],
        "error": error,
        "trace": str(trace),
        "stdout": str(out_dir / f"{service_id}.stdout.txt"),
        "stderr": str(out_dir / f"{service_id}.stderr.txt"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="*")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--agent")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--sdk-script", type=Path, default=default_sdk_script())
    parser.add_argument("--show-trace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected = services(args.limit, args.services)
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")
    if not args.dry_run and not args.sdk_script.exists():
        raise SystemExit(
            f"SDK wrapper not found: {args.sdk_script}. Pass --sdk-script <real path> "
            f"or restore {DEFAULT_SDK} / {WORKSPACE_SDK}."
        )
    if args.workers == 1 or len(selected) <= 1:
        results = [run_one(service_id, args) for service_id in selected]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_service = {executor.submit(run_one, service_id, args): service_id for service_id in selected}
            for future in as_completed(future_to_service):
                service_id = future_to_service[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    results.append({"service_id": service_id, "status": "FAIL", "error": str(exc)})
    summary = {"count": len(results), "results": results}
    path = EXP_ROOT / "manifests" / "isolated_sdk_generation_results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [item for item in results if item.get("status") == "FAIL"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
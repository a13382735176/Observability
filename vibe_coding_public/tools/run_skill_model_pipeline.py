#!/usr/bin/env python3
"""Run model x prompt-variant generation, capture, and offline judge pipeline.

This orchestrates the generated microservice experiment:
1. materialize template prompts for with-skill or no-skill
2. hide private faults from the Copilot SDK workspace
3. run Copilot SDK generation for one model
4. restore faults
5. create a run-scoped eval service tree
6. capture runtime fault artifacts
7. run fault-specific offline judge
8. write captured-only and full-intent summaries
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


ROOT = Path(__file__).resolve().parents[1]
EXP_ROOT = ROOT / "experiments" / "skill_observability"
GENERATED_WORKSPACES_ROOT = EXP_ROOT / "generated_workspaces"
EVAL_SERVICES_ROOT = EXP_ROOT / "eval_services"
SKILL_ROOT = ROOT / "services_skill"
DEFAULT_PYTHON = Path(os.environ.get("PYTHON", "python3"))
DEFAULT_SDK = Path(os.environ.get("COPILOT_SDK_SCRIPT", "demo_call_copilot_agent.py"))
WORKSPACE_SDK = ROOT.parent / "demo_call_copilot_agent.py"
PLACEHOLDER_SDK = Path("/path/to/demo_call_copilot_agent.py")


def default_sdk_script() -> Path:
    if DEFAULT_SDK.exists():
        return DEFAULT_SDK
    if WORKSPACE_SDK.exists():
        return WORKSPACE_SDK
    return DEFAULT_SDK


def natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).replace("-", "_")


def selected_service_args(args: argparse.Namespace) -> list[str]:
    if args.services:
        return [name if name.endswith("-skill") else f"{name}-skill" for name in args.services]
    return []


def selected_services(args: argparse.Namespace) -> list[str]:
    if args.services:
        selected = selected_service_args(args)
    else:
        selected = sorted(
            [p.name for p in SKILL_ROOT.iterdir() if p.is_dir() and re.match(r"^\d+-", p.name)],
            key=natural_key,
        )
    if args.limit is not None:
        selected = selected[: args.limit]
    return selected


def run_cmd(cmd: list[str], *, env: dict[str, str] | None = None, dry_run: bool = False, check: bool = True) -> int:
    printable = " ".join(str(part) for part in cmd)
    print(f"$ {printable}", flush=True)
    if dry_run:
        return 0
    result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, check=False)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    if os.name == "posix":
        subprocess.run(["rm", "-rf", "--", str(path)], check=True)
    else:
        shutil.rmtree(path)


def skill_experiment_cmd(subcommand: str, args: argparse.Namespace, extra: list[str] | None = None) -> list[str]:
    cmd = [str(args.python), "tools/skill_experiment.py", subcommand]
    if args.limit is not None:
        cmd.extend(["--limit", str(args.limit)])
    if args.services:
        cmd.append("--services")
        cmd.extend(selected_service_args(args))
    if extra:
        cmd.extend(extra)
    return cmd


def materialize_variant(variant: str, args: argparse.Namespace) -> None:
    extra = ["--prompt-variant", variant]
    if args.refresh_specs:
        run_cmd(skill_experiment_cmd("extract", args, extra), dry_run=args.dry_run)
    run_cmd(skill_experiment_cmd("materialize", args, extra), dry_run=args.dry_run)


def strip_faults(args: argparse.Namespace) -> None:
    run_cmd(skill_experiment_cmd("strip-faults", args), dry_run=args.dry_run)


def restore_faults(args: argparse.Namespace) -> None:
    run_cmd(skill_experiment_cmd("restore-faults", args), dry_run=args.dry_run, check=False)


def generated_workspace_root(run_id: str) -> Path:
    return GENERATED_WORKSPACES_ROOT / run_id


def eval_services_root(run_id: str) -> Path:
    return EVAL_SERVICES_ROOT / run_id


def prepare_generated_workspaces(run_id: str, args: argparse.Namespace) -> Path:
    workspace_root = generated_workspace_root(run_id)
    services = selected_services(args)
    print(f"== prepare SDK workspaces root={workspace_root.relative_to(ROOT)} services={len(services)} ==", flush=True)
    if args.dry_run:
        for service in services[:20]:
            print(f"$ copy services_skill/{service} -> {workspace_root.relative_to(ROOT)}/{service}", flush=True)
        if len(services) > 20:
            print("...", flush=True)
        return workspace_root

    if workspace_root.exists():
        remove_tree(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    for service in services:
        src = SKILL_ROOT / service
        dst = workspace_root / service
        if not src.is_dir():
            raise SystemExit(f"missing services_skill dir: {src}")
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "src").mkdir(parents=True, exist_ok=True)
        for filename in ("PROMPT.md", "CONTRACT.json", "README.md"):
            source_file = src / filename
            if source_file.exists():
                shutil.copy2(source_file, dst / filename)
        prompt_path = dst / "PROMPT.md"
        if prompt_path.exists():
            prompt_text = prompt_path.read_text(encoding="utf-8")
            prompt_text = prompt_text.replace(
                f"- Directory: `services_skill/{service}`",
                "- Directory: `src/` inside this run-scoped SDK workspace",
            )
            prompt_text = prompt_text.replace(
                f"Create or update only files under `services_skill/{service}`.",
                "Create or update only files under `src/` in this run-scoped SDK workspace.",
            )
            prompt_text = prompt_text.replace(
                "You are generating a fresh microservice from a source-free service contract.\n"
                "Use only the contract below. Do not inspect any prior implementation or hidden\n"
                "test harness files.\n",
                "You are generating a fresh microservice from a source-free service contract.\n"
                "Use only the contract below. Do not inspect any prior implementation or hidden\n"
                "test harness files. This is a run-scoped SDK workspace; write generated files\n"
                "under `src/` only. The benchmark will import `src/` into a separate run-scoped eval tree later.\n",
            )
            prompt_path.write_text(prompt_text, encoding="utf-8")
    return workspace_root


def copy_file_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copy_dir_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        if dst.exists():
            remove_tree(dst)
        shutil.copytree(src, dst)


def rewrite_eval_run_sh(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace('source "$HERE/../../_lib/run-common.sh"', f'source "{ROOT / "_lib" / "run-common.sh"}"')
    path.write_text(text, encoding="utf-8")


def load_sdk_summary(run_id: str) -> dict:
    summary_path = EXP_ROOT / "sdk_service_runs" / run_id / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"missing SDK summary: {summary_path}")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def generated_ok_services(run_id: str, args: argparse.Namespace) -> list[str]:
    selected = set(selected_services(args))
    summary = load_sdk_summary(run_id)
    services = []
    for item in summary.get("results", []):
        service_id = str(item.get("service_id", ""))
        if service_id not in selected:
            continue
        if item.get("status") != "OK":
            continue
        if not item.get("generated_files"):
            continue
        services.append(service_id)
    return sorted(services, key=natural_key)


def generated_failed_services(run_id: str, args: argparse.Namespace) -> list[str]:
    selected = set(selected_services(args))
    summary = load_sdk_summary(run_id)
    services = []
    for item in summary.get("results", []):
        service_id = str(item.get("service_id", ""))
        if service_id not in selected:
            continue
        if item.get("status") != "OK" or not item.get("generated_files"):
            services.append(service_id)
    return sorted(services, key=natural_key)


def sdk_failure_count(run_id: str, args: argparse.Namespace) -> tuple[int, int]:
    selected = set(selected_services(args))
    summary = load_sdk_summary(run_id)
    results = [item for item in summary.get("results", []) if str(item.get("service_id", "")) in selected]
    failures = [item for item in results if item.get("status") != "OK"]
    return len(failures), len(results)


def prepare_eval_services(workspace_root: Path, run_id: str, args: argparse.Namespace, services: list[str] | None = None) -> Path:
    services = services or selected_services(args)
    eval_root = eval_services_root(run_id)
    print(
        f"== prepare eval services root={eval_root.relative_to(ROOT)} "
        f"from {workspace_root.relative_to(ROOT)} services={len(services)} ==",
        flush=True,
    )
    if args.dry_run:
        for service in services[:20]:
            print(f"$ create {eval_root.relative_to(ROOT)}/{service} with harness + generated src", flush=True)
        if len(services) > 20:
            print("...", flush=True)
        return eval_root

    if eval_root.exists():
        remove_tree(eval_root)
    eval_root.mkdir(parents=True, exist_ok=True)

    for service in services:
        template = SKILL_ROOT / service
        generated_src = workspace_root / service / "src"
        dst = eval_root / service
        if not template.is_dir():
            raise SystemExit(f"missing eval template service: {template}")
        if not generated_src.exists() or not any(path.is_file() for path in generated_src.rglob("*")):
            raise SystemExit(f"missing generated files for {service}: {generated_src}")

        dst.mkdir(parents=True, exist_ok=True)
        for filename in ("CONTRACT.json", "Dockerfile", "exercise.sh", "PROMPT.md", "README.md", "run.sh"):
            copy_file_if_exists(template / filename, dst / filename)
        copy_dir_if_exists(template / "k8s", dst / "k8s")
        copy_dir_if_exists(template / "faults", dst / "faults")
        shutil.copytree(generated_src, dst / "src")
        run_sh = dst / "run.sh"
        if run_sh.exists():
            rewrite_eval_run_sh(run_sh)
    return eval_root


def generate(
    model: str,
    variant: str,
    run_id: str,
    workspace_root: Path,
    args: argparse.Namespace,
    services: list[str] | None = None,
    merge_existing_summary: bool = False,
) -> int:
    cmd = [
        str(args.python),
        "tools/run_services_skill_sdk_generation.py",
        "--model",
        model,
        "--workers",
        str(args.workers),
        "--timeout",
        str(args.sdk_timeout),
        "--run-id",
        run_id,
        "--prompt-variant",
        variant,
        "--workspace-root",
        str(workspace_root),
        "--clean-src",
    ]
    if merge_existing_summary:
        cmd.append("--merge-existing-summary")
    if services is not None:
        cmd.extend(services)
    elif args.limit is not None:
        cmd.extend(["--limit", str(args.limit)])
    if services is None:
        cmd.extend(selected_service_args(args))
    if args.sdk_script:
        cmd.extend(["--sdk-script", str(args.sdk_script)])
    if args.agent:
        cmd.extend(["--agent", args.agent])
    print(f"== SDK generation variant={variant} model={model} run_id={run_id} ==", flush=True)
    return run_cmd(cmd, dry_run=args.dry_run, check=False)


def run_service_subcommand(
    service: str,
    eval_root: Path,
    subcommand: str,
    log_file,
    env: dict[str, str],
) -> int:
    print(f"\n== {subcommand} {service} ==", file=log_file, flush=True)
    result = subprocess.run(
        ["bash", str(eval_root / service / "run.sh"), subcommand],
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    print(f"== {subcommand} {service} rc={result.returncode} ==", file=log_file, flush=True)
    return result.returncode


def capture_one_eval_service(
    service: str,
    eval_root: Path,
    campaign: str,
    log_dir: Path,
    env: dict[str, str],
    cleanup_before: bool,
    cleanup_after: bool,
) -> tuple[str, int]:
    log_path = log_dir / f"{service}.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        if cleanup_before:
            run_service_subcommand(service, eval_root, "cleanup", log_file, env)

        capture_rc = 1
        try:
            capture_rc = run_service_subcommand(service, eval_root, "capture", log_file, env)
        finally:
            if cleanup_after:
                cleanup_rc = run_service_subcommand(service, eval_root, "cleanup", log_file, env)
                if capture_rc == 0 and cleanup_rc != 0:
                    capture_rc = cleanup_rc
    return service, capture_rc


def capture(campaign: str, eval_root: Path, args: argparse.Namespace, services: list[str] | None = None) -> int:
    env = os.environ.copy()
    env["RUN_TS"] = campaign
    env["MAX_PARALLEL"] = str(args.capture_parallel)
    env["RUNS_DIR"] = str(ROOT / "runs")
    services = services or selected_services(args)
    cleanup_before = not args.skip_pre_capture_cleanup
    cleanup_after = not args.keep_k8s_after_capture
    print(
        f"== capture campaign={campaign} eval_root={eval_root.relative_to(ROOT)} services={len(services)} "
        f"cleanup_before={cleanup_before} cleanup_after={cleanup_after} ==",
        flush=True,
    )
    if args.dry_run:
        for service in services[:20]:
            if cleanup_before:
                print(f"$ RUN_TS={campaign} RUNS_DIR={ROOT / 'runs'} bash {eval_root.relative_to(ROOT)}/{service}/run.sh cleanup", flush=True)
            print(f"$ RUN_TS={campaign} RUNS_DIR={ROOT / 'runs'} bash {eval_root.relative_to(ROOT)}/{service}/run.sh capture", flush=True)
            if cleanup_after:
                print(f"$ RUN_TS={campaign} RUNS_DIR={ROOT / 'runs'} bash {eval_root.relative_to(ROOT)}/{service}/run.sh cleanup", flush=True)
        if len(services) > 20:
            print("...", flush=True)
        return 0

    rc = 0
    log_dir = ROOT / "runs" / f"_eval_{campaign}"
    log_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.capture_parallel) as executor:
        futures = {
            executor.submit(
                capture_one_eval_service,
                service,
                eval_root,
                campaign,
                log_dir,
                env,
                cleanup_before,
                cleanup_after,
            ): service
            for service in services
        }
        for future in as_completed(futures):
            service, service_rc = future.result()
            status = "OK" if service_rc == 0 else f"FAIL rc={service_rc}"
            print(f"{service:36s} {status}", flush=True)
            rc = rc or service_rc
    print(f"capture logs: {log_dir.relative_to(ROOT)}", flush=True)
    return rc


def judge_service_run(run_dir: Path, args: argparse.Namespace) -> tuple[str, int]:
    service = run_dir.parent.name
    cmd = [str(args.python), "judge/judge.py", str(run_dir), "--mode", "fault-specific", "--offline"]
    result = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return service, result.returncode


def judge_campaign(campaign: str, args: argparse.Namespace) -> None:
    run_dirs = []
    for run_dir in sorted((ROOT / "runs").glob(f"*-skill/{campaign}"), key=lambda p: natural_key(str(p))):
        if any((fault / "meta.json").exists() for fault in run_dir.glob("F*")):
            run_dirs.append(run_dir)
    print(f"== offline judge campaign={campaign} service_run_dirs={len(run_dirs)} ==", flush=True)
    if args.dry_run:
        for run_dir in run_dirs[:20]:
            print(f"$ {args.python} judge/judge.py {run_dir.relative_to(ROOT)} --mode fault-specific --offline", flush=True)
        if len(run_dirs) > 20:
            print("...", flush=True)
        return
    with ThreadPoolExecutor(max_workers=args.judge_parallel) as executor:
        futures = {executor.submit(judge_service_run, run_dir, args): run_dir for run_dir in run_dirs}
        for future in as_completed(futures):
            service, rc = future.result()
            status = "ALL_CAUGHT" if rc == 0 else "JUDGED_WITH_MISSES"
            print(f"{service:36s} {status}", flush=True)


def summarize(campaign: str, expected_services_dir: Path, args: argparse.Namespace) -> None:
    captured_out = f"runs/generated_{campaign}_fault-specific-offline-by-fault.md"
    full_out = f"runs/generated_{campaign}_fault-specific-full-intent-by-fault.md"
    run_cmd(
        [
            str(args.python),
            "tools/summarize_campaign.py",
            "--campaign",
            campaign,
            "--service-suffix=-skill",
            "--out",
            captured_out,
            "--title",
            "Generated Campaign Fault-Specific Offline Judge Summary",
        ],
        dry_run=args.dry_run,
        check=False,
    )
    run_cmd(
        [
            str(args.python),
            "tools/summarize_campaign.py",
            "--campaign",
            campaign,
            "--service-suffix=-skill",
            "--expected-services-dir",
            str(expected_services_dir),
            "--count-missing-as-no-signal",
            "--out",
            full_out,
            "--title",
            "Generated Campaign Fault-Specific Full-Intent Summary",
        ],
        dry_run=args.dry_run,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True, help="Models to evaluate, e.g. gpt-5.5 gpt-4.1")
    parser.add_argument("--variants", nargs="+", choices=["with-skill", "no-skill"], default=["with-skill", "no-skill"])
    parser.add_argument("--services", nargs="*", help="Optional service ids, with or without -skill suffix")
    parser.add_argument("--limit", type=int, help="Optional first-N services")
    parser.add_argument("--workers", type=int, default=4, help="SDK generation workers")
    parser.add_argument("--capture-parallel", type=int, default=2)
    parser.add_argument("--judge-parallel", type=int, default=8)
    parser.add_argument("--sdk-timeout", type=int, default=1200)
    parser.add_argument("--sdk-script", type=Path, default=default_sdk_script())
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--agent")
    parser.add_argument("--run-prefix", default="")
    parser.add_argument("--refresh-specs", action="store_true")
    parser.add_argument("--reuse-run-id", help="Reuse an existing SDK generation run id and continue with eval/capture")
    parser.add_argument("--retry-failed-generate", action="store_true", help="With --reuse-run-id, skip existing OK services and regenerate only SDK failures, merging results back into that run")
    parser.add_argument("--allow-partial-capture", action="store_true", help="Capture only SDK services with status=OK; full-intent summary still counts missing services as no_signal")
    parser.add_argument("--skip-pre-capture-cleanup", action="store_true", help="Do not clean a service's existing Kubernetes objects before capture")
    parser.add_argument("--keep-k8s-after-capture", action="store_true", help="Leave service Kubernetes objects running after capture for debugging")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--skip-capture", action="store_true")
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--skip-summary", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.skip_generate and args.sdk_script and (not args.reuse_run_id or args.retry_failed_generate):
        if args.sdk_script == PLACEHOLDER_SDK:
            raise SystemExit(
                "SDK wrapper path is still the documentation placeholder: "
                f"{args.sdk_script}. Set SDK_SCRIPT to the real Copilot SDK wrapper path, "
                f"or omit --sdk-script if {DEFAULT_SDK} or {WORKSPACE_SDK} exists."
            )
        if not args.sdk_script.exists():
            raise SystemExit(
                f"SDK wrapper not found: {args.sdk_script}. Pass --sdk-script <real path> "
                f"or restore {DEFAULT_SDK} / {WORKSPACE_SDK}."
            )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for model in args.models:
        for variant in args.variants:
            variant_tag = variant.replace("-", "_")
            model_tag = slug(model)
            if args.reuse_run_id:
                run_base = args.reuse_run_id
            else:
                run_base = f"{variant_tag}_{model_tag}_{stamp}"
                if args.run_prefix:
                    run_base = f"{args.run_prefix}_{run_base}"
            sdk_run_id = run_base
            campaign = f"{run_base}_capture"
            print(f"\n==== pipeline variant={variant} model={model} sdk_run_id={sdk_run_id} campaign={campaign} ====", flush=True)

            if args.reuse_run_id:
                print(f"== reuse SDK generation run_id={sdk_run_id} ==", flush=True)
            else:
                materialize_variant(variant, args)
            generation_failed = False
            workspace_root = generated_workspace_root(sdk_run_id)
            eval_root = eval_services_root(sdk_run_id)
            services_for_eval: list[str] | None = None
            if args.reuse_run_id:
                if args.retry_failed_generate and not args.skip_generate:
                    retry_services = generated_failed_services(sdk_run_id, args)
                    if retry_services:
                        print(
                            f"== retry failed SDK generation: skipping OK services, "
                            f"regenerating {len(retry_services)} services ==",
                            flush=True,
                        )
                        generate_rc = generate(
                            model,
                            variant,
                            sdk_run_id,
                            workspace_root,
                            args,
                            services=retry_services,
                            merge_existing_summary=True,
                        )
                        if generate_rc != 0:
                            failures, total = sdk_failure_count(sdk_run_id, args)
                            print(
                                f"warning: retry SDK generation returned {generate_rc}; "
                                f"remaining failures={failures}/{total}",
                                flush=True,
                            )
                    else:
                        print("== retry failed SDK generation: no failures found; generation skipped ==", flush=True)
                restore_faults(args)
                failures, total = sdk_failure_count(sdk_run_id, args)
                if failures:
                    if not args.allow_partial_capture:
                        raise SystemExit(
                            f"SDK run {sdk_run_id} has failures={failures}/{total}; "
                            "pass --allow-partial-capture to run only generated OK services"
                        )
                    services_for_eval = generated_ok_services(sdk_run_id, args)
                    print(f"== partial capture enabled: generated OK services={len(services_for_eval)}/{total} ==", flush=True)
            elif not args.skip_generate:
                try:
                    strip_faults(args)
                    workspace_root = prepare_generated_workspaces(sdk_run_id, args)
                    generate_rc = generate(model, variant, sdk_run_id, workspace_root, args)
                    if generate_rc != 0:
                        failures, total = sdk_failure_count(sdk_run_id, args)
                        if args.allow_partial_capture:
                            services_for_eval = generated_ok_services(sdk_run_id, args)
                            print(
                                f"warning: SDK generation returned {generate_rc}; "
                                f"partial capture generated OK services={len(services_for_eval)}/{total}",
                                flush=True,
                            )
                        else:
                            print(f"error: SDK generation returned {generate_rc}; skipping eval/capture/judge/summary for this run", flush=True)
                            generation_failed = True
                finally:
                    restore_faults(args)
            else:
                restore_faults(args)

            if generation_failed:
                continue

            if not args.skip_capture:
                eval_root = prepare_eval_services(workspace_root, sdk_run_id, args, services_for_eval)

            if not args.skip_capture:
                capture(campaign, eval_root, args, services_for_eval)
            if not args.skip_judge:
                judge_campaign(campaign, args)
            if not args.skip_summary:
                summarize(campaign, SKILL_ROOT, args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

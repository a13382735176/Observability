#!/usr/bin/env python3
"""Summarize vibe_coding fault-detection campaign artifacts.

Reads existing runs/<service>/<campaign>/summary.json files and optionally a
campaign status directory such as runs/chaos_multifault_<campaign>/*.status.
It does not rebuild, deploy, inject, or rejudge anything.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def natural_key(value: str) -> list[int | str]:
    import re

    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def load_status_services(status_dir: Path, include_demo_failures: bool) -> tuple[list[str], Counter[str]]:
    services: list[str] = []
    status_counts: Counter[str] = Counter()
    for status_file in sorted(status_dir.glob("*.status"), key=lambda p: natural_key(p.name)):
        line = status_file.read_text(errors="replace").strip()
        if not line:
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        service, status = parts[0], parts[1]
        status_counts[status] += 1
        if not include_demo_failures and "reason=demo_rc=1" in line:
            continue
        services.append(service)
    return services, status_counts


def discover_services(campaign: str, suffix: str | None) -> list[str]:
    services: list[str] = []
    for service_dir in RUNS.iterdir():
        if not service_dir.is_dir():
            continue
        if suffix and not service_dir.name.endswith(suffix):
            continue
        if (service_dir / campaign / "summary.json").exists():
            services.append(service_dir.name)
    return sorted(services, key=natural_key)


def discover_expected_services(expected_services_dir: Path, suffix: str | None) -> list[str]:
    services: list[str] = []
    for service_dir in expected_services_dir.iterdir():
        if not service_dir.is_dir():
            continue
        if suffix and not service_dir.name.endswith(suffix):
            continue
        if (service_dir / "faults").is_dir():
            services.append(service_dir.name)
    return sorted(services, key=natural_key)


def expected_fault_ids(service: str, expected_services_dir: Path | None) -> list[str]:
    if expected_services_dir is None:
        return []
    fault_dir = expected_services_dir / service / "faults"
    if not fault_dir.is_dir():
        return []
    return sorted((p.stem for p in fault_dir.glob("F*.yaml")), key=natural_key)


def load_results(summary_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(summary_path.read_text(errors="replace"))
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    return [item for item in items if isinstance(item, dict)]


def pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "NA"
    return f"{numerator / denominator:.2%}"


def summarize(
    campaign: str,
    services: list[str],
    expected_services_dir: Path | None = None,
    count_missing_as_no_signal: bool = False,
) -> dict[str, Any]:
    by_fault: dict[str, Counter[str]] = defaultdict(Counter)
    service_rows: list[dict[str, Any]] = []
    services_with_summary = 0
    fault_total = 0
    fault_caught = 0
    fault_no_signal = 0

    for service in services:
        summary_path = RUNS / service / campaign / "summary.json"
        if not summary_path.exists():
            expected_faults = expected_fault_ids(service, expected_services_dir)
            service_rows.append(
                {
                    "service": service,
                    "missing_summary": True,
                    "expected_faults": len(expected_faults),
                }
            )
            if count_missing_as_no_signal:
                for fault_id in expected_faults:
                    fault_total += 1
                    fault_no_signal += 1
                    by_fault[fault_id]["samples"] += 1
                    by_fault[fault_id]["miss"] += 1
                    by_fault[fault_id]["no_signal"] += 1
            continue

        results = load_results(summary_path)
        services_with_summary += 1
        caught = sum(1 for result in results if result.get("caught"))
        service_rows.append(
            {
                "service": service,
                "faults": len(results),
                "caught": caught,
                "summary": str(summary_path),
            }
        )

        for result in results:
            fault_id = str(result.get("fault_id", "?"))
            reason = str(result.get("verdict_reason", "?"))
            caught_result = bool(result.get("caught"))
            fault_total += 1
            by_fault[fault_id]["samples"] += 1
            if caught_result:
                fault_caught += 1
                by_fault[fault_id]["caught"] += 1
                by_fault[fault_id][reason] += 1
            else:
                by_fault[fault_id]["miss"] += 1
                if reason == "no_signal":
                    fault_no_signal += 1
                    by_fault[fault_id]["no_signal"] += 1
                else:
                    by_fault[fault_id][reason] += 1
            if "error" in result:
                by_fault[fault_id]["errors"] += 1

    return {
        "campaign": campaign,
        "services_targeted": len(services),
        "services_with_summary": services_with_summary,
        "services_missing_summary": len(services) - services_with_summary,
        "fault_total": fault_total,
        "fault_caught": fault_caught,
        "fault_no_signal": fault_no_signal,
        "missing_counted_as_no_signal": count_missing_as_no_signal,
        "by_fault": by_fault,
        "services": service_rows,
    }


def render_markdown(summary: dict[str, Any], title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Campaign: {summary['campaign']}",
        f"- Services targeted: {summary['services_targeted']}",
        f"- Services with summary: {summary['services_with_summary']}",
        f"- Services missing summary: {summary['services_missing_summary']}",
        f"- Missing services counted as no_signal: {summary['missing_counted_as_no_signal']}",
        f"- Fault instances total: {summary['fault_total']}",
        f"- Fault instances caught: {summary['fault_caught']} ({pct(summary['fault_caught'], summary['fault_total'])})",
        f"- Fault instances no_signal: {summary['fault_no_signal']} ({pct(summary['fault_no_signal'], summary['fault_total'])})",
        "",
        "## By Fault Type",
        "",
        "| Fault | Samples | Caught | Detection Rate | No Signal | No Signal Ratio | Matcher | Pod Restart | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fault_id in sorted(summary["by_fault"], key=natural_key):
        counts = summary["by_fault"][fault_id]
        samples = counts["samples"]
        caught = counts["caught"]
        no_signal = counts["no_signal"]
        lines.append(
            "| {fault} | {samples} | {caught} | {rate} | {no_signal} | {no_signal_rate} | {matcher} | {pod_restart} | {errors} |".format(
                fault=fault_id,
                samples=samples,
                caught=caught,
                rate=pct(caught, samples),
                no_signal=no_signal,
                no_signal_rate=pct(no_signal, samples),
                matcher=counts["matcher"],
                pod_restart=counts["pod_restart"],
                errors=counts["errors"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, help="RUN_TS/campaign name under runs/<service>/")
    parser.add_argument("--status-dir", help="Optional campaign status directory with *.status files")
    parser.add_argument("--service-suffix", help="Only scan run services ending with this suffix, e.g. -skill")
    parser.add_argument("--expected-services-dir", help="Directory of expected services whose faults/*.yaml define intended fault samples")
    parser.add_argument("--count-missing-as-no-signal", action="store_true", help="For services without summary.json, count each expected faults/*.yaml as a no_signal miss")
    parser.add_argument("--include-demo-failures", action="store_true", help="Do not exclude status lines with reason=demo_rc=1")
    parser.add_argument("--out", help="Write markdown summary to this path")
    parser.add_argument("--title", default="Fault-Specific Detection Rate By Fault")
    args = parser.parse_args()

    status_counts: Counter[str] = Counter()
    expected_services_dir = Path(args.expected_services_dir) if args.expected_services_dir else None

    if args.status_dir:
        services, status_counts = load_status_services(Path(args.status_dir), args.include_demo_failures)
    elif expected_services_dir:
        services = discover_expected_services(expected_services_dir, args.service_suffix)
    else:
        services = discover_services(args.campaign, args.service_suffix)

    summary = summarize(
        args.campaign,
        services,
        expected_services_dir=expected_services_dir,
        count_missing_as_no_signal=args.count_missing_as_no_signal,
    )
    markdown = render_markdown(summary, args.title)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
    else:
        print(markdown)

    print(
        f"campaign={summary['campaign']} services={summary['services_with_summary']}/{summary['services_targeted']} "
        f"faults={summary['fault_caught']}/{summary['fault_total']} caught_rate={pct(summary['fault_caught'], summary['fault_total'])}"
    )
    if status_counts:
        print("status_counts=" + ",".join(f"{key}:{status_counts[key]}" for key in sorted(status_counts)))
    if args.out:
        print(f"wrote={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""Compare latest baseline runs with matching services_skill runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def latest_summary(service: str) -> Path | None:
    service_dir = RUNS / service
    if not service_dir.exists():
        return None
    for run_dir in sorted([p for p in service_dir.iterdir() if p.is_dir()], reverse=True):
        summary = run_dir / "summary.json"
        if summary.exists():
            return summary
    return None


def load_counts(service: str) -> tuple[int, int, dict[str, bool]] | None:
    summary = latest_summary(service)
    if summary is None:
        return None
    raw = json.loads(summary.read_text())
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    verdicts = {
        item.get("fault_id", "?"): bool(item.get("caught"))
        for item in items
        if isinstance(item, dict)
    }
    caught = sum(1 for value in verdicts.values() if value)
    return caught, len(verdicts), verdicts


def service_names(limit: int | None, services: list[str] | None) -> list[str]:
    if services:
        return [name.removesuffix("-skill") for name in services]
    names = sorted(
        [p.name for p in (ROOT / "services_skill").iterdir() if p.is_dir() and p.name.endswith("-skill")],
        key=lambda name: [int(x) if x.isdigit() else x for x in __import__("re").split(r"(\d+)", name)],
    )
    names = [name.removesuffix("-skill") for name in names]
    return names[:limit] if limit is not None else names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("services", nargs="*")
    args = parser.parse_args()

    total_base_caught = total_base_faults = 0
    total_skill_caught = total_skill_faults = 0
    print(f"{'SERVICE':<32} {'BASELINE':<12} {'SKILL':<12} DELTA")
    print("-" * 72)
    for base in service_names(args.limit, args.services):
        skill = f"{base}-skill"
        base_counts = load_counts(base)
        skill_counts = load_counts(skill)
        if base_counts is None:
            base_label = "NO RUN"
            base_rate = None
        else:
            bc, bn, _ = base_counts
            base_label = f"{bc}/{bn}"
            base_rate = bc / bn if bn else 0.0
            total_base_caught += bc
            total_base_faults += bn
        if skill_counts is None:
            skill_label = "NO RUN"
            skill_rate = None
        else:
            sc, sn, _ = skill_counts
            skill_label = f"{sc}/{sn}"
            skill_rate = sc / sn if sn else 0.0
            total_skill_caught += sc
            total_skill_faults += sn
        delta = ""
        if base_rate is not None and skill_rate is not None:
            delta = f"{(skill_rate - base_rate) * 100:+.1f} pp"
        print(f"{base:<32} {base_label:<12} {skill_label:<12} {delta}")
    print("-" * 72)
    base_total = f"{total_base_caught}/{total_base_faults}" if total_base_faults else "NO RUN"
    skill_total = f"{total_skill_caught}/{total_skill_faults}" if total_skill_faults else "NO RUN"
    delta = ""
    if total_base_faults and total_skill_faults:
        delta = f"{((total_skill_caught / total_skill_faults) - (total_base_caught / total_base_faults)) * 100:+.1f} pp"
    print(f"{'TOTAL':<32} {base_total:<12} {skill_total:<12} {delta}")


if __name__ == "__main__":
    main()